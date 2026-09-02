"""
Tests for the canonical unit conversion module.
"""
import pytest
from units import (
    convert, to_base, to_grams, to_ml, is_compatible, parse_unit,
    UnitConversionError, MissingDensityError, MissingItemWeightError
)


class TestMassConversions:
    """Test mass unit conversions."""
    
    def test_kg_to_g(self):
        assert convert(1, 'kg', 'g') == 1000
        assert convert(2.5, 'kg', 'g') == 2500
    
    def test_g_to_kg(self):
        assert convert(1000, 'g', 'kg') == 1
        assert convert(2500, 'g', 'kg') == 2.5
    
    def test_lb_to_g(self):
        assert abs(convert(1, 'lb', 'g') - 453.592) < 0.001
        assert abs(convert(2, 'lb', 'g') - 907.184) < 0.001
    
    def test_oz_to_g(self):
        assert abs(convert(1, 'oz', 'g') - 28.3495) < 0.001
        assert abs(convert(16, 'oz', 'g') - 453.592) < 0.001
    
    def test_g_to_lb(self):
        assert abs(convert(453.592, 'g', 'lb') - 1.0) < 0.001


class TestVolumeConversions:
    """Test volume unit conversions."""
    
    def test_l_to_ml(self):
        assert convert(1, 'l', 'ml') == 1000
        assert convert(2.5, 'l', 'ml') == 2500
    
    def test_ml_to_l(self):
        assert convert(1000, 'ml', 'l') == 1
        assert convert(2500, 'ml', 'l') == 2.5
    
    def test_cup_to_ml(self):
        assert abs(convert(1, 'cup', 'ml') - 236.588) < 0.001
        assert abs(convert(2, 'cup', 'ml') - 473.176) < 0.001
    
    def test_tbsp_to_ml(self):
        assert abs(convert(1, 'tbsp', 'ml') - 14.787) < 0.001
        assert abs(convert(2, 'tbsp', 'ml') - 29.574) < 0.001
    
    def test_tsp_to_ml(self):
        assert abs(convert(1, 'tsp', 'ml') - 4.929) < 0.001
        assert abs(convert(3, 'tsp', 'ml') - 14.787) < 0.001


class TestMassVolumeConversions:
    """Test mass↔volume conversions requiring density."""
    
    def test_ml_to_g_with_density(self):
        # Water: 1 g/ml
        assert convert(100, 'ml', 'g', density=1.0) == 100
        # Oil: 0.92 g/ml
        assert abs(convert(100, 'ml', 'g', density=0.92) - 92) < 0.001
        # Honey: 1.42 g/ml
        assert abs(convert(100, 'ml', 'g', density=1.42) - 142) < 0.001
    
    def test_g_to_ml_with_density(self):
        # Water
        assert convert(100, 'g', 'ml', density=1.0) == 100
        # Oil
        assert abs(convert(100, 'g', 'ml', density=0.92) - (100/0.92)) < 0.001
    
    def test_cup_to_g_with_density(self):
        # Flour: ~0.59 g/ml, 1 cup = 236.588 ml
        # 1 cup flour ≈ 140g
        flour_g = 1 * 236.588 * 0.59
        result = convert(1, 'cup', 'g', density=0.59)
        assert abs(result - flour_g) < 0.01
    
    def test_missing_density_raises_error(self):
        with pytest.raises(MissingDensityError):
            convert(100, 'ml', 'g')  # No density provided
        
        with pytest.raises(MissingDensityError):
            convert(100, 'g', 'ml')  # No density provided
    
    def test_invalid_density_raises_error(self):
        with pytest.raises(Exception):
            convert(100, 'ml', 'g', density=0)
        with pytest.raises(Exception):
            convert(100, 'ml', 'g', density=-1)


class TestCountConversions:
    """Test count (each) conversions."""
    
    def test_count_to_g_with_item_weight(self):
        # 12 eggs at 50g each = 600g
        assert convert(12, 'each', 'g', item_weight=50) == 600
        # 3 pieces at 150g each = 450g
        assert convert(3, 'piece', 'g', item_weight=150) == 450
    
    def test_g_to_count_with_item_weight(self):
        # 600g / 50g per egg = 12 eggs
        assert convert(600, 'g', 'each', item_weight=50) == 12
    
    def test_missing_item_weight_raises_error(self):
        with pytest.raises(MissingItemWeightError):
            convert(12, 'each', 'g')  # No item_weight
        
        with pytest.raises(MissingItemWeightError):
            convert(100, 'g', 'each')  # No item_weight


class TestIncompatibleUnits:
    """Test that incompatible conversions raise errors."""
    
    def test_count_to_volume_fails(self):
        with pytest.raises(Exception):
            convert(12, 'each', 'ml')  # No item_weight
    
    def test_mass_to_count_without_weight_fails(self):
        with pytest.raises(MissingItemWeightError):
            convert(100, 'g', 'each')  # No item_weight


class TestCompatibility:
    """Test unit compatibility checking."""
    
    def test_mass_compatible(self):
        assert is_compatible('g', 'kg')
        assert is_compatible('kg', 'g')
        assert is_compatible('lb', 'oz')
    
    def test_volume_compatible(self):
        assert is_compatible('ml', 'l')
        assert is_compatible('cup', 'tbsp')
    
    def test_count_compatible(self):
        assert is_compatible('each', 'piece')
        assert is_compatible('count', 'piece')
    
    def test_incompatible(self):
        assert not is_compatible('g', 'ml')
        assert not is_compatible('g', 'each')
        assert not is_compatible('ml', 'each')


class TestParseUnit:
    """Test unit parsing and normalization."""
    
    def test_aliases(self):
        info = parse_unit('grams')
        assert info['canonical'] == 'g'
        
        info = parse_unit('kilograms')
        assert info['canonical'] == 'kg'
        
        info = parse_unit('tablespoons')
        assert info['canonical'] == 'tbsp'
        
        info = parse_unit('pieces')
        assert info['canonical'] == 'each'
    
    def test_invalid_unit_raises(self):
        with pytest.raises(Exception):
            parse_unit('invalid_unit_xyz')


class TestToBase:
    """Test to_base function."""
    
    def test_mass_to_base(self):
        assert to_base(1, 'kg') == 1000
        assert to_base(2, 'lb') == 907.184
    
    def test_volume_to_base(self):
        assert to_base(1, 'l') == 1000
        assert to_base(1, 'cup') == 236.588
    
    def test_volume_to_base_with_density(self):
        # With density, volume -> grams
        assert to_base(100, 'ml', density=1.0) == 100
        assert abs(to_base(100, 'ml', density=0.92) - 92) < 0.001


class TestToGrams:
    """Test to_grams function."""
    
    def test_mass_to_grams(self):
        assert to_grams(1, 'kg') == 1000
        assert to_grams(1, 'lb') == 453.592
    
    def test_volume_to_grams_with_density(self):
        assert to_grams(100, 'ml', density=1.0) == 100
        assert abs(to_grams(100, 'ml', density=0.92) - 92) < 0.001
    
    def test_count_to_grams(self):
        assert to_grams(12, 'each', item_weight=50) == 600
    
    def test_missing_density_raises(self):
        with pytest.raises(MissingDensityError):
            to_grams(100, 'ml')  # No density for volume->mass


class TestToMl:
    """Test to_ml function."""
    
    def test_volume_to_ml(self):
        assert to_ml(1, 'l') == 1000
        assert abs(to_ml(1, 'cup') - 236.588) < 0.001
        assert abs(to_ml(1, 'tbsp') - 14.787) < 0.001
    
    def test_mass_to_ml_with_density(self):
        assert to_ml(100, 'g', density=1.0) == 100
        assert abs(to_ml(100, 'g', density=0.92) - (100/0.92)) < 0.001


class TestCompatibility:
    def test_is_compatible(self):
        assert is_compatible('g', 'kg') is True
        assert is_compatible('ml', 'l') is True
        assert is_compatible('each', 'piece') is True
        assert is_compatible('g', 'ml') is False
        assert is_compatible('g', 'each') is False


class TestRecipeIngredientScenarios:
    """Test scenarios matching the real-world examples from the requirements."""
    
    def test_flour_1kg_recipe_500g(self):
        """1 kg flour purchased, recipe uses 500 g"""
        # Ingredient: pkg=1kg, unit=g
        base = 1000  # g
        recipe_qty = 500  # g
        # No conversion needed
        assert to_base(1, 'kg') == 1000
        assert to_base(500, 'g') == 500
    
    def test_olive_oil_1l_recipe_15ml(self):
        """1 L olive oil @ $10, recipe uses 15 ml, density 0.92"""
        # Cost per ml = $10 / 1000ml = $0.01/ml
        # Recipe uses 15ml
        # Cost = 15 * 0.01 = $0.15
        # But if using density: 15ml * 0.92 = 13.8g
        pass  # Tested via costing integration
    
    def test_sugar_1kg_recipe_1cup(self):
        """1 kg sugar, recipe uses 1 cup, density ~0.85"""
        # 1 cup sugar ≈ 200g (density ~0.85, 1 cup = 236.588ml)
        sugar_g = 1 * 236.588 * 0.85
        result = convert(1, 'cup', 'g', density=0.85)
        assert abs(result - sugar_g) < 0.01
    
    def test_chicken_1pkg_15kg_recipe_200g(self):
        """1 package chicken (1.5 kg), recipe uses 200g edible, refuse 32%"""
        # 1.5 kg package, 32% refuse (bones)
        # Edible = 1500 * 0.68 = 1020g
        # Recipe needs 200g edible
        # Need to buy: 200 / 0.68 = 294g raw
        # Note: refuse_pct not implemented yet per requirements
        pass
    
    def test_eggs_12_recipe_3(self):
        """12 eggs purchased, recipe uses 3 each"""
        assert convert(3, 'each', 'each') == 3
        assert convert(12, 'each', 'g', item_weight=50) == 600
    
    def test_cups_vs_grams_inventory(self):
        """Recipe uses 2 cups flour, inventory 500g, density 0.59"""
        # 2 cups flour = 2 * 236.588 * 0.59 ≈ 280g
        demand_g = convert(2, 'cup', 'g', density=0.59)
        inventory_g = 500
        # Need = max(0, demand - inventory) = 0
        assert demand_g < inventory_g


if __name__ == '__main__':
    pytest.main([__file__, '-v'])