"""
Canonical unit conversion module for Dinner Spinner.

This module is the single authority for all unit conversions in the application.
It replaces duplicated conversion logic in Ingredient.cost_per_base_unit(),
Ingredient.cost_per_recipe_unit(), FoodService._unit_to_ml(), and
FoodService.get_ingredient_nutrition().
"""

from enum import Enum
from typing import Optional
from dataclasses import dataclass


class UnitType(Enum):
    """Classification of unit categories."""
    MASS = "mass"
    VOLUME = "volume"
    COUNT = "count"


# Canonical unit definitions
# Each unit maps to its canonical name and conversion factor to base unit
MASS_UNITS = {
    "g": {"canonical": "g", "factor": 1.0, "aliases": ["g", "gram", "grams"]},
    "kg": {"canonical": "kg", "factor": 1000.0, "aliases": ["kg", "kilogram", "kilograms"]},
    "lb": {"canonical": "lb", "factor": 453.592, "aliases": ["lb", "lbs", "pound", "pounds"]},
    "oz": {"canonical": "oz", "factor": 28.3495, "aliases": ["oz", "ounce", "ounces"]},
}

VOLUME_UNITS = {
    "ml": {"canonical": "ml", "factor": 1.0, "aliases": ["ml", "milliliter", "milliliters"]},
    "l": {"canonical": "l", "factor": 1000.0, "aliases": ["l", "liter", "liters"]},
    "cup": {"canonical": "cup", "factor": 236.588, "aliases": ["cup", "cups", "c"]},
    "tbsp": {"canonical": "tbsp", "factor": 14.787, "aliases": ["tbsp", "tablespoon", "tablespoons"]},
    "tsp": {"canonical": "tsp", "factor": 4.929, "aliases": ["tsp", "teaspoon", "teaspoons"]},
}

COUNT_UNITS = {
    "each": {"canonical": "each", "factor": 1.0, "aliases": ["each", "piece", "pieces", "count"]},
    "piece": {"canonical": "each", "factor": 1.0, "aliases": ["each", "piece", "pieces", "count"]},
    "pieces": {"canonical": "each", "factor": 1.0, "aliases": ["each", "piece", "pieces", "count"]},
    "count": {"canonical": "each", "factor": 1.0, "aliases": ["each", "piece", "pieces", "count"]},
}

# Build unified lookup
ALL_UNITS = {}
for category_name, category in (("MASS", MASS_UNITS), ("VOLUME", VOLUME_UNITS), ("COUNT", COUNT_UNITS)):
    for canonical, info in category.items():
        for alias in info["aliases"]:
            ALL_UNITS[alias] = {
                "canonical": info["canonical"],
                "type": category_name,
                "factor": info["factor"],
            }

# Build canonical name sets for type checking
MASS_CANONICAL = {info["canonical"] for info in MASS_UNITS.values()}
VOLUME_CANONICAL = {info["canonical"] for info in VOLUME_UNITS.values()}
COUNT_CANONICAL = {info["canonical"] for info in COUNT_UNITS.values()}


class UnitConversionError(Exception):
    """Raised when unit conversion cannot be performed."""
    pass


class IncompatibleUnitsError(UnitConversionError):
    """Raised when attempting to convert between incompatible unit types."""
    pass


class MissingDensityError(UnitConversionError):
    """Raised when density is required but not available."""
    pass


class MissingItemWeightError(UnitConversionError):
    """Raised when item weight is required but not available."""
    pass


def parse_unit(unit: str) -> dict:
    """
    Parse a unit string and return its canonical information.
    
    Args:
        unit: Unit string (e.g., "g", "kg", "cup", "tbsp")
        
    Returns:
        Dict with canonical name, type, and factor to base unit
        
    Raises:
        UnitConversionError: If unit is not recognized
    """
    if not unit:
        raise UnitConversionError("Empty unit string")
    
    normalized = unit.lower().strip()
    if normalized not in ALL_UNITS:
        raise UnitConversionError(f"Unrecognized unit: '{unit}'")
    
    return ALL_UNITS[normalized]


def unit_type(unit: str) -> Optional[str]:
    """
    Get the unit type (MASS, VOLUME, COUNT) for a unit.
    
    Returns None if unit is not recognized.
    """
    try:
        info = parse_unit(unit)
        return info["type"]
    except UnitConversionError:
        return None


def is_compatible(unit_a: str, unit_b: str) -> bool:
    """
    Check if two units are compatible for conversion.
    
    Compatible means both are MASS, both are VOLUME, or both are COUNT.
    """
    type_a = unit_type(unit_a)
    type_b = unit_type(unit_b)
    return type_a is not None and type_a == type_b


def convert(
    quantity: float,
    from_unit: str,
    to_unit: str,
    density: Optional[float] = None,
    item_weight: Optional[float] = None,
) -> float:
    """
    Convert quantity from one unit to another.
    
    Args:
        quantity: Amount to convert
        from_unit: Source unit (e.g., "cup", "g", "tbsp")
        to_unit: Target unit (e.g., "ml", "kg", "each")
        density: Optional density in g/ml for volume↔mass conversions
        item_weight: Optional weight per item in grams (for count→mass)
        
    Returns:
        Converted quantity in target unit
        
    Raises:
        UnitConversionError: If units are incompatible or conversion not possible
        MissingDensityError: If density required but not provided
        MissingItemWeightError: If item_weight required but not provided
    """
    if quantity == 0:
        return 0.0
    
    from_info = parse_unit(from_unit)
    to_info = parse_unit(to_unit)
    
    from_type = from_info["type"]
    to_type = to_info["type"]
    
    # Same type - direct conversion
    if from_type == to_type:
        return quantity * from_info["factor"] / to_info["factor"]
    
    # Mass ↔ Volume conversions require density
    if (from_type == "MASS" and to_type == "VOLUME") or (from_type == "VOLUME" and to_type == "MASS"):
        if density is None:
            raise MissingDensityError(
                f"Cannot convert between {from_unit} and {to_unit} without density"
            )
        if density <= 0:
            raise UnitConversionError("Density must be positive")
        
        # Convert to base units first, then apply density
        if from_type == "MASS":
            # g → ml: grams / (g/ml) = ml
            base_g = quantity * from_info["factor"]
            return base_g / density / to_info["factor"]
        else:
            # ml → g: ml * (g/ml) = g
            base_ml = quantity * from_info["factor"]
            return base_ml * density / to_info["factor"]
    
    # Count ↔ Mass/Volume requires item_weight
    if from_type == "COUNT" and to_type in ("MASS", "VOLUME"):
        if item_weight is None:
            raise MissingItemWeightError(
                f"Cannot convert {from_unit} to {to_unit} without item_weight"
            )
        if item_weight <= 0:
            raise UnitConversionError("item_weight must be positive")
        
        # count → g: count × item_weight(g) → target unit
        base_g = quantity * item_weight
        return base_g / to_info["factor"]
    
    if from_type in ("MASS", "VOLUME") and to_type == "COUNT":
        if item_weight is None:
            raise MissingItemWeightError(
                f"Cannot convert {from_unit} to {to_unit} without item_weight"
            )
        if item_weight <= 0:
            raise UnitConversionError("item_weight must be positive")
        
        # g → count: g / item_weight(g) = count
        base_g = quantity * from_info["factor"]
        return base_g / item_weight
    
    raise IncompatibleUnitsError(
        f"Cannot convert between {from_unit} ({from_type}) and {to_unit} ({to_type})"
    )


def to_base(quantity: float, unit: str, density: Optional[float] = None, 
            item_weight: Optional[float] = None) -> float:
    """
    Convert quantity to its base unit (g for mass, ml for volume, each for count).
    
    Args:
        quantity: Amount to convert
        unit: Source unit
        density: Optional density in g/ml for volume↔mass
        item_weight: Optional weight per item in grams
        
    Returns:
        Quantity in base unit (g, ml, or each)
    """
    info = parse_unit(unit)
    unit_type = info["type"]
    
    if unit_type == "MASS":
        return quantity * info["factor"]
    elif unit_type == "VOLUME":
        if density is not None:
            return quantity * info["factor"] * density
        return quantity * info["factor"]  # Returns ml
    elif unit_type == "COUNT":
        return quantity * info["factor"]  # Returns count
    
    raise IncompatibleUnitsError(f"Unknown unit type for {unit}")


def to_grams(quantity: float, unit: str, density: Optional[float] = None,
             item_weight: Optional[float] = None) -> float:
    """
    Convert quantity to grams (mass).
    
    For mass units: direct conversion to grams.
    For volume units: requires density (g/ml).
    For count units: requires item_weight (g per item).
    
    Returns:
        Quantity in grams
    """
    return convert(quantity, unit, "g", density=density, item_weight=item_weight)


def to_ml(quantity: float, unit: str, density: Optional[float] = None) -> float:
    """
    Convert quantity to milliliters (volume).
    
    For volume units: direct conversion to ml.
    For mass units: requires density (g/ml).
    
    Returns:
        Quantity in ml
    """
    return convert(quantity, unit, "ml", density=density)


def is_valid_unit(unit: str) -> bool:
    """Check if a unit string is recognized."""
    try:
        parse_unit(unit)
        return True
    except UnitConversionError:
        return False


def get_unit_category(unit: str) -> Optional[str]:
    """Get the category (MASS, VOLUME, COUNT) for a unit."""
    return unit_type(unit)


def normalize_unit(unit: str) -> str:
    """
    Return the canonical name for a unit.
    e.g., "grams" -> "g", "tablespoons" -> "tbsp", "pieces" -> "each"
    """
    return parse_unit(unit)["canonical"]


# For backwards compatibility with existing code
def unit_to_ml(unit: str) -> Optional[float]:
    """
    Legacy compatibility: convert 1 unit to ml.
    Returns None if not a volume unit.
    """
    try:
        return convert(1.0, unit, "ml")
    except UnitConversionError:
        return None