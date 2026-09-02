"""
Food Service - High-level interface for food data operations.

This service integrates the canonical Food model with the existing
Ingredient model and provides a clean API for the application.
"""

from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

from app import db
from .models import (
    Food, FoodNutrient, Nutrient, FoodProvider, FoodProvenance,
    FoodAlias, FoodCategory, IngredientFoodLink
)
from .registry import provider_registry


class FoodService:
    """
    Main service for food data operations.
    
    Provides a clean interface for:
    - Searching foods across providers
    - Importing foods from providers
    - Linking Ingredients to Foods for nutrition
    - Calculating nutrition for recipes/meals
    """
    
    def __init__(self):
        self.registry = provider_registry
    
    # ==================== SEARCH & DISCOVERY ====================
    
    def search(self, query: str, max_results: int = 20, 
               providers: List[str] = None) -> List[Dict[str, Any]]:
        """
        Search for foods across all providers.
        
        Returns unified list with provider attribution.
        """
        if providers is None:
            providers = ['openfoodfacts', 'usda_fdc', 'hc_cnf']
        
        results = self.registry.search_all(query, max_results, providers)
        
        unified = []
        for provider_code, provider_results in results.items():
            for r in provider_results:
                unified.append({
                    'external_id': r.external_id,
                    'name': r.name,
                    'brand': r.brand,
                    'category': r.category,
                    'data_type': r.data_type,
                    'provider': provider_code,
                })
        
        # Sort: branded first (OFF), then foundation
        unified.sort(key=lambda x: (x['data_type'] != 'branded', x['name']))
        return unified[:max_results]
    
    def search_by_barcode(self, barcode: str) -> Optional[Dict[str, Any]]:
        """Search for product by barcode."""
        result = self.registry.get_food_by_barcode(barcode)
        if result:
            return {
                'external_id': result.external_id,
                'name': result.name,
                'brand': getattr(result, 'brand', None),
                'category': result.category,
                'data_type': result.data_type,
                'provider': result.provider_data.get('provider', 'unknown'),
            }
        return None
    
    def get_food_details(self, food_id: int) -> Optional[Dict[str, Any]]:
        """Get full details for a canonical Food."""
        food = Food.query.get(food_id)
        if not food:
            return None
        
        return {
            'id': food.id,
            'name': food.name,
            'scientific_name': food.scientific_name,
            'category': food.category,
            'data_type': food.data_type,
            'density': food.density,
            'water_content': food.water_content,
            'refuse_pct': food.refuse_pct,
            'common_serving': food.common_serving,
            'common_serving_weight': food.common_serving_weight,
            'macros': food.get_macros(),
            'provenances': [
                {
                    'provider': p.provider.code,
                    'external_id': p.external_id,
                    'external_url': p.external_url,
                    'imported_at': p.imported_at,
                    'confidence': p.confidence,
                }
                for p in food.provenances
            ],
            'aliases': [a.alias for a in food.aliases],
        }
    
    # ==================== IMPORT MANAGEMENT ====================
    
    def import_food(self, external_id: str, provider_code: str) -> Optional[Food]:
        """Import a food from a specific provider."""
        return self.registry.import_food(external_id, provider_code)
    
    def import_by_barcode(self, barcode: str) -> Optional[Food]:
        """Import product by barcode (tries OFF first, then USDA)."""
        result = self.registry.get_food_by_barcode(barcode)
        if not result:
            return None
        
        # Determine provider from result
        provider_code = 'openfoodfacts'
        if 'usda' in str(result.provider_data).lower():
            provider_code = 'usda_fdc'
        
        return self.import_food(result.external_id, provider_code)
    
    def bulk_import_usda(self, limit: int = 1000) -> int:
        """Bulk import USDA foundation foods."""
        provider = self.registry.get('usda_fdc')
        if provider and hasattr(provider, 'import_foundation_foods'):
            return provider.import_foundation_foods(limit)
        return 0
    
    def bulk_import_cnf(self, limit: int = None) -> int:
        """Bulk import CNF foods."""
        provider = self.registry.get('hc_cnf')
        if provider and hasattr(provider, 'import_all'):
            return provider.import_all(limit)
        return 0
    
    # ==================== INGREDIENT INTEGRATION ====================
    
    def link_ingredient_to_food(self, ingredient_id: int, food_id: int,
                                 match_type: str = 'manual', 
                                 confidence: float = 1.0,
                                 user_id: int = None) -> IngredientFoodLink:
        """
        Link an Ingredient to a canonical Food for nutrition data.
        
        This is the key integration point between the existing
        Ingredient model (pricing, packaging, inventory) and
        the canonical Food model (nutrition).
        """
        from app import Ingredient
        ingredient = Ingredient.query.get_or_404(ingredient_id)
        food = Food.query.get_or_404(food_id)
        
        # Check existing link
        existing = IngredientFoodLink.query.filter_by(
            ingredient_id=ingredient_id, food_id=food_id
        ).first()
        
        if existing:
            existing.match_type = match_type
            existing.confidence = confidence
            existing.matched_by = user_id
            existing.matched_at = datetime.utcnow()
        else:
            existing = IngredientFoodLink(
                ingredient_id=ingredient_id,
                food_id=food_id,
                match_type=match_type,
                confidence=confidence,
                matched_by=user_id,
            )
            db.session.add(existing)
        
        db.session.commit()
        return existing
    
    def unlink_ingredient(self, ingredient_id: int) -> bool:
        """Remove nutrition link for an ingredient."""
        link = IngredientFoodLink.query.filter_by(ingredient_id=ingredient_id).first()
        if link:
            db.session.delete(link)
            db.session.commit()
            return True
        return False
    
    def get_ingredient_nutrition(self, ingredient_id: int) -> Optional[Dict]:
        """Get nutrition info for an ingredient via its linked Food."""
        link = IngredientFoodLink.query.filter_by(ingredient_id=ingredient_id).first()
        if not link:
            return None
        
        food = link.food
        ingredient = link.ingredient
        
        # Calculate nutrition per recipe unit
        macros = food.get_macros()
        
        # Use ingredient's recipe unit for serving
        serving_weight = 100.0  # Default 100g
        
        # If ingredient has a recipe unit that's not grams, we need conversion
        # This is where density from food helps
        if food.density and ingredient.unit in ('ml', 'cup', 'tbsp', 'tsp'):
            # Convert volume to weight using density
            volume_ml = self._unit_to_ml(ingredient.unit)
            if volume_ml:
                serving_weight = volume_ml * food.density
        elif ingredient.unit in ('g', 'gram', 'grams'):
            serving_weight = 100.0  # Per 100g
        elif ingredient.unit in ('kg', 'kilogram'):
            serving_weight = 100000.0
        elif ingredient.unit in ('lb', 'pound'):
            serving_weight = 45359.2
        elif ingredient.unit in ('oz', 'ounce'):
            serving_weight = 2834.95
        elif ingredient.unit in ('each', 'piece'):
            # Use common serving weight from food
            serving_weight = food.common_serving_weight or 100.0
        
        # Calculate per serving
        factor = serving_weight / 100.0
        return {
            'food_id': food.id,
            'food_name': food.name,
            'serving_weight_g': serving_weight,
            'serving_unit': ingredient.unit,
            'macros_per_serving': {k: round(v * factor, 2) for k, v in macros.items()},
            'match_confidence': link.confidence,
            'match_type': link.match_type,
        }
    
    def _unit_to_ml(self, unit: str) -> Optional[float]:
        """Convert volume unit to ml."""
        unit = unit.lower()
        conversions = {
            'ml': 1.0, 'milliliter': 1.0, 'milliliters': 1.0,
            'l': 1000.0, 'liter': 1000.0, 'liters': 1000.0,
            'cup': 236.588, 'cups': 236.588, 'c': 236.588,
            'tbsp': 14.787, 'tablespoon': 14.787, 'tablespoons': 14.787,
            'tsp': 4.929, 'teaspoon': 4.929, 'teaspoons': 4.929,
        }
        return conversions.get(unit)
    
    # ==================== RECIPE/MEAL NUTRITION ====================
    
    def calculate_recipe_nutrition(self, recipe_id: int) -> Optional[Dict]:
        """Calculate full nutrition for a recipe."""
        from app import Recipe, RecipeIngredient
        
        recipe = Recipe.query.get(recipe_id)
        if not recipe:
            return None
        
        total_macros = {
            'energy_kcal': 0,
            'protein_g': 0,
            'fat_g': 0,
            'carbs_g': 0,
            'fiber_g': 0,
            'sugar_g': 0,
            'sodium_mg': 0,
        }
        
        ingredients_nutrition = []
        
        for ri in recipe.recipe_ingredients:
            ing_nutrition = self.get_ingredient_nutrition(ri.ingredient_id)
            if ing_nutrition:
                # Scale by quantity used in recipe
                factor = ri.quantity / 100.0  # Assuming per 100g base
                
                for macro, value in ing_nutrition['macros_per_serving'].items():
                    total_macros[macro] += value * factor
                
                ingredients_nutrition.append({
                    'ingredient_id': ri.ingredient_id,
                    'name': ing_nutrition['food_name'],
                    'quantity': ri.quantity,
                    'unit': ri.unit,
                    'macros': {k: round(v * factor, 2) for k, v in ing_nutrition['macros_per_serving'].items()},
                })
        
        per_serving = {k: round(v / recipe.servings, 2) for k, v in total_macros.items()}
        
        return {
            'recipe_id': recipe.id,
            'recipe_name': recipe.name,
            'servings': recipe.servings,
            'total_macros': total_macros,
            'per_serving': per_serving,
            'ingredients': ingredients_nutrition,
        }
    
    def calculate_meal_plan_nutrition(self, week_start) -> Dict:
        """Calculate nutrition for a week's meal plan."""
        from meal_planner.app import MealPlan
        
        meal_plans = MealPlan.query.filter_by(week_start=week_start).all()
        
        daily_totals = {}
        weekly_totals = {
            'energy_kcal': 0,
            'protein_g': 0,
            'fat_g': 0,
            'carbs_g': 0,
            'fiber_g': 0,
            'sugar_g': 0,
            'sodium_mg': 0,
        }
        
        for mp in meal_plans:
            if not mp.recipe:
                continue
            
            nutrition = self.calculate_recipe_nutrition(mp.recipe_id)
            if not nutrition:
                continue
            
            # Scale by servings planned
            factor = mp.servings / nutrition['servings']
            
            day_key = mp.day
            if day_key not in daily_totals:
                daily_totals[day_key] = {
                    'energy_kcal': 0, 'protein_g': 0, 'fat_g': 0,
                    'carbs_g': 0, 'fiber_g': 0, 'sugar_g': 0, 'sodium_mg': 0
                }
            
            for macro, value in nutrition['per_serving'].items():
                scaled = value * factor
                daily_totals[day_key][macro] += scaled
                weekly_totals[macro] += scaled
        
        return {
            'week_start': week_start,
            'daily': daily_totals,
            'weekly': weekly_totals,
        }
    
    # ==================== NUTRIENT DEFINITIONS ====================
    
    def ensure_core_nutrients(self) -> int:
        """Ensure core nutrient definitions exist in database."""
        core_nutrients = [
            (1008, 'Energy', 'kcal', True),
            (1003, 'Protein', 'g', True),
            (1004, 'Total Fat', 'g', True),
            (1005, 'Carbohydrates', 'g', True),
            (1079, 'Fiber', 'g', False),
            (2000, 'Total Sugars', 'g', False),
            (1093, 'Sodium', 'mg', False),
            (1087, 'Calcium', 'mg', False),
            (1089, 'Iron', 'mg', False),
            (1092, 'Potassium', 'mg', False),
            (1106, 'Vitamin A (RAE)', 'µg', False),
            (1109, 'Vitamin D', 'IU', False),
            (1110, 'Vitamin D', 'µg', False),
            (1111, 'Vitamin E', 'mg', False),
            (1114, 'Vitamin K', 'µg', False),
            (1162, 'Vitamin C', 'mg', False),
            (1165, 'Thiamin', 'mg', False),
            (1166, 'Riboflavin', 'mg', False),
            (1167, 'Niacin', 'mg', False),
            (1175, 'Vitamin B6', 'mg', False),
            (1177, 'Vitamin B12', 'µg', False),
            (1178, 'Folate', 'µg', False),
            (1253, 'Cholesterol', 'mg', False),
            (1257, 'Saturated Fat', 'g', False),
        ]
        
        created = 0
        for nut_id, name, unit, is_macro in core_nutrients:
            # Check by name since unique constraint is on name
            existing = Nutrient.query.filter_by(name=name).first()
            if not existing:
                nut = Nutrient(
                    id=nut_id,
                    name=name,
                    unit=unit,
                    is_macro=is_macro,
                    category='macronutrient' if is_macro else 'micronutrient',
                )
                db.session.add(nut)
                created += 1
            elif existing.id != nut_id:
                # Nutrient with same name exists but different ID - skip
                pass
        
        db.session.commit()
        return created
    
    # ==================== AUTO-LINKING ====================
    
    def auto_link_ingredients(self, confidence_threshold: float = 0.8) -> int:
        """
        Attempt to auto-link unlinked ingredients to foods by name matching.
        """
        from app import Ingredient
        unlinked = Ingredient.query.filter(
            ~Ingredient.id.in_(
                db.session.query(IngredientFoodLink.ingredient_id)
            )
        ).all()
        
        linked = 0
        for ingredient in unlinked:
            # Search for matching food
            results = self.search(ingredient.name, max_results=3)
            if results:
                best = results[0]
                # Only link if high confidence
                if best['data_type'] == 'foundation' or confidence_threshold <= 0.7:
                    food = Food.query.filter_by(name=best['name']).first()
                    if food:
                        self.link_ingredient_to_food(
                            ingredient.id, food.id,
                            match_type='auto',
                            confidence=confidence_threshold
                        )
                        linked += 1
        
        return linked