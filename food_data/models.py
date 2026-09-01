"""
Canonical Food data models for the provider-agnostic food subsystem.

These models form the single source of truth for nutritional information.
All external providers import into these models with full provenance tracking.
"""

from datetime import datetime
from enum import Enum
from app import db


class FoodCategory(str, Enum):
    """Standardized food categories across providers."""
    DAIRY = "dairy"
    MEAT_POULTRY = "meat_poultry"
    FISH_SEAFOOD = "fish_seafood"
    EGGS = "eggs"
    LEGUMES = "legumes"
    NUTS_SEEDS = "nuts_seeds"
    GRAINS = "grains"
    VEGETABLES = "vegetables"
    FRUITS = "fruits"
    FATS_OILS = "fats_oils"
    SWEETS = "sweets"
    BEVERAGES = "beverages"
    SPICES_HERBS = "spices_herbs"
    BABY_FOOD = "baby_food"
    PREPARED_MEALS = "prepared_meals"
    FAST_FOOD = "fast_food"
    OTHER = "other"


class DataType(str, Enum):
    """Type of data this food entry represents."""
    FOUNDATION = "foundation"        # USDA Foundation Foods / CNF core
    SURVEY = "survey"                # USDA Survey (FNDDS) / CNF
    BRANDED = "branded"              # Branded products with barcodes
    RECIPE = "recipe"                # Multi-ingredient foods
    USER = "user"                    # User-entered custom foods


class Food(db.Model):
    """
    Canonical food model - single source of truth for nutritional data.
    
    All providers (USDA, CNF, OFF) import into this model.
    Nutritional values are per 100g (standard reference amount).
    """
    __tablename__ = 'food'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Core identification
    name = db.Column(db.String(255), nullable=False, index=True)
    scientific_name = db.Column(db.String(255), nullable=True)
    category = db.Column(db.String(50), db.ForeignKey('food_category.name'), nullable=True, index=True)
    data_type = db.Column(db.String(20), nullable=False, default=DataType.FOUNDATION.value, index=True)
    
    # Physical properties (per 100g)
    density = db.Column(db.Float, nullable=True)  # g/ml for volume-weight conversion
    water_content = db.Column(db.Float, nullable=True)  # g per 100g
    refuse_pct = db.Column(db.Float, nullable=True)  # % inedible portion
    
    # Serving info
    common_serving = db.Column(db.String(100), nullable=True)  # e.g., "1 cup, chopped"
    common_serving_weight = db.Column(db.Float, nullable=True)  # grams
    
    # Metadata
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    nutrients = db.relationship('FoodNutrient', backref='food', cascade='all, delete-orphan', lazy='dynamic')
    provenances = db.relationship('FoodProvenance', backref='food', cascade='all, delete-orphan', lazy='dynamic')
    aliases = db.relationship('FoodAlias', backref='food', cascade='all, delete-orphan', lazy='dynamic')
    ingredient_links = db.relationship('IngredientFoodLink', backref='food', lazy='dynamic')
    
    def __repr__(self):
        return f'<Food {self.id}: {self.name}>'
    
    def get_nutrient(self, nutrient_id_or_name):
        """Get nutrient value per 100g by nutrient ID or name."""
        if isinstance(nutrient_id_or_name, int):
            return self.nutrients.filter_by(nutrient_id=nutrient_id_or_name).first()
        return self.nutrients.join(Nutrient).filter(Nutrient.name == nutrient_id_or_name).first()
    
    def get_nutrient_value(self, nutrient_id_or_name, default=0.0):
        """Get nutrient amount per 100g, return default if not found."""
        fn = self.get_nutrient(nutrient_id_or_name)
        return fn.amount if fn else default
    
    def get_macros(self):
        """Get macronutrients per 100g as dict."""
        return {
            'energy_kcal': self.get_nutrient_value(1008),      # Energy (kcal)
            'protein_g': self.get_nutrient_value(1003),        # Protein
            'fat_g': self.get_nutrient_value(1004),            # Total fat
            'carbs_g': self.get_nutrient_value(1005),          # Carbohydrates
            'fiber_g': self.get_nutrient_value(1079),          # Fiber
            'sugar_g': self.get_nutrient_value(2000),          # Total sugars
            'sodium_mg': self.get_nutrient_value(1093),        # Sodium
        }
    
    def get_nutrition_per_serving(self, serving_weight_g):
        """Calculate nutrition for a specific serving weight in grams."""
        factor = serving_weight_g / 100.0
        macros = self.get_macros()
        return {k: round(v * factor, 2) for k, v in macros.items()}


class Nutrient(db.Model):
    """Nutrient definition - standardized across all providers."""
    __tablename__ = 'nutrient'
    
    id = db.Column(db.Integer, primary_key=True)  # USDA nutrient ID
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    unit = db.Column(db.String(20), nullable=False)  # g, mg, µg, kcal, kJ
    nutrient_nbr = db.Column(db.String(10), nullable=True)  # USDA nutrient number
    rank = db.Column(db.Integer, nullable=True)  # Display order
    
    # Classification
    category = db.Column(db.String(50), nullable=True)  # macronutrient, vitamin, mineral, etc.
    is_macro = db.Column(db.Boolean, default=False, nullable=False)
    
    # Daily values (for %DV calculations)
    dv_adult = db.Column(db.Float, nullable=True)  # Adult daily value
    dv_child = db.Column(db.Float, nullable=True)  # Child (4+) daily value
    dv_pregnant = db.Column(db.Float, nullable=True)  # Pregnant/lactating DV
    
    def __repr__(self):
        return f'<Nutrient {self.id}: {self.name} ({self.unit})>'


class FoodNutrient(db.Model):
    """Nutrient amount for a specific food (per 100g)."""
    __tablename__ = 'food_nutrient'
    
    id = db.Column(db.Integer, primary_key=True)
    food_id = db.Column(db.Integer, db.ForeignKey('food.id', ondelete='CASCADE'), nullable=False, index=True)
    nutrient_id = db.Column(db.Integer, db.ForeignKey('nutrient.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Amount per 100g of food
    amount = db.Column(db.Float, nullable=False)
    
    # Data quality
    min_amount = db.Column(db.Float, nullable=True)
    max_amount = db.Column(db.Float, nullable=True)
    median_amount = db.Column(db.Float, nullable=True)
    std_dev = db.Column(db.Float, nullable=True)
    num_samples = db.Column(db.Integer, nullable=True)
    
    # Derivation
    derivation_code = db.Column(db.String(10), nullable=True)  # USDA derivation code
    derivation_desc = db.Column(db.String(255), nullable=True)
    
    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    nutrient = db.relationship('Nutrient', lazy='joined')
    
    # Unique constraint: one nutrient per food
    __table_args__ = (
        db.UniqueConstraint('food_id', 'nutrient_id', name='uq_food_nutrient'),
    )
    
    def __repr__(self):
        return f'<FoodNutrient food={self.food_id} nutrient={self.nutrient_id} amount={self.amount}>'


class FoodCategory(db.Model):
    """Standardized food categories."""
    __tablename__ = 'food_category'
    
    name = db.Column(db.String(50), primary_key=True)
    display_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    parent_category = db.Column(db.String(50), db.ForeignKey('food_category.name'), nullable=True)
    display_order = db.Column(db.Integer, default=0)
    
    def __repr__(self):
        return f'<FoodCategory {self.name}>'


class FoodProvider(db.Model):
    """External data provider registry."""
    __tablename__ = 'food_provider'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), nullable=False, unique=True, index=True)  # 'usda_fdc', 'hc_cnf', 'off'
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    base_url = db.Column(db.String(500), nullable=True)
    api_version = db.Column(db.String(20), nullable=True)
    
    # Capabilities
    provides_nutrients = db.Column(db.Boolean, default=True)
    provides_barcodes = db.Column(db.Boolean, default=False)
    provides_branded = db.Column(db.Boolean, default=False)
    provides_foundation = db.Column(db.Boolean, default=True)
    
    # Rate limiting
    rate_limit_per_min = db.Column(db.Integer, default=60)
    rate_limit_per_day = db.Column(db.Integer, default=10000)
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    last_sync = db.Column(db.DateTime, nullable=True)
    last_sync_status = db.Column(db.String(50), nullable=True)
    
    # Relationships
    provenances = db.relationship('FoodProvenance', backref='provider', lazy='dynamic')
    
    def __repr__(self):
        return f'<FoodProvider {self.code}: {self.name}>'


class FoodProvenance(db.Model):
    """
    Provenance tracking for each food-provider relationship.
    
    Each food can have multiple provenances (one per provider).
    Tracks exactly where data came from and when.
    """
    __tablename__ = 'food_provenance'
    
    id = db.Column(db.Integer, primary_key=True)
    food_id = db.Column(db.Integer, db.ForeignKey('food.id', ondelete='CASCADE'), nullable=False, index=True)
    provider_id = db.Column(db.Integer, db.ForeignKey('food_provider.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # External identifier in the provider's system
    external_id = db.Column(db.String(100), nullable=False, index=True)
    external_url = db.Column(db.String(500), nullable=True)
    
    # Provider-specific metadata (JSON)
    provider_data = db.Column(db.JSON, nullable=True)
    
    # Import tracking
    imported_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_verified = db.Column(db.DateTime, nullable=True)
    
    # Data quality flags
    is_primary = db.Column(db.Boolean, default=False)  # Primary source for this food
    confidence = db.Column(db.Float, default=1.0)  # 0.0-1.0 match confidence
    notes = db.Column(db.Text, nullable=True)
    
    # Unique constraint: one provenance per food-provider-external_id
    __table_args__ = (
        db.UniqueConstraint('food_id', 'provider_id', 'external_id', name='uq_food_provenance'),
    )
    
    def __repr__(self):
        return f'<FoodProvenance food={self.food_id} provider={self.provider_id} ext={self.external_id}>'


class FoodAlias(db.Model):
    """Alternative names for foods (synonyms, brand names, common names)."""
    __tablename__ = 'food_alias'
    
    id = db.Column(db.Integer, primary_key=True)
    food_id = db.Column(db.Integer, db.ForeignKey('food.id', ondelete='CASCADE'), nullable=False, index=True)
    
    alias = db.Column(db.String(255), nullable=False, index=True)
    alias_type = db.Column(db.String(30), nullable=True)  # 'synonym', 'brand', 'common', 'scientific', 'abbreviation'
    language = db.Column(db.String(10), default='en', nullable=False)
    region = db.Column(db.String(10), nullable=True)  # 'US', 'CA', 'UK', etc.
    
    # Source
    provider_id = db.Column(db.Integer, db.ForeignKey('food_provider.id'), nullable=True)
    external_id = db.Column(db.String(100), nullable=True)
    
    # Search weight
    is_primary_name = db.Column(db.Boolean, default=False)
    search_weight = db.Column(db.Float, default=1.0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Unique constraint
    __table_args__ = (
        db.UniqueConstraint('food_id', 'alias', 'language', name='uq_food_alias'),
    )
    
    def __repr__(self):
        return f'<FoodAlias food={self.food_id} alias={self.alias}>'


class IngredientFoodLink(db.Model):
    """
    Links user's pantry Ingredient to canonical Food for nutritional data.
    
    This is the integration point between the existing Ingredient model
    (which has pricing, packaging, inventory) and the canonical Food model
    (which has nutritional data).
    """
    __tablename__ = 'ingredient_food_link'
    
    id = db.Column(db.Integer, primary_key=True)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredient.id', ondelete='CASCADE'), nullable=False, index=True)
    food_id = db.Column(db.Integer, db.ForeignKey('food.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Match info
    match_type = db.Column(db.String(20), nullable=False)  # 'auto', 'manual', 'barcode', 'verified'
    confidence = db.Column(db.Float, default=1.0)  # 0.0-1.0
    matched_by = db.Column(db.Integer, nullable=True)  # User who confirmed (no FK for now)
    matched_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Override options (if user wants to adjust)
    override_density = db.Column(db.Float, nullable=True)  # g/ml override
    override_refuse_pct = db.Column(db.Float, nullable=True)  # % inedible override
    notes = db.Column(db.Text, nullable=True)
    
    # Unique constraint: one link per ingredient-food
    __table_args__ = (
        db.UniqueConstraint('ingredient_id', 'food_id', name='uq_ingredient_food_link'),
    )
    
    def __repr__(self):
        return f'<IngredientFoodLink ingredient={self.ingredient_id} food={self.food_id} type={self.match_type}>'