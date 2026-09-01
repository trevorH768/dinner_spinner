"""
Open Food Facts Provider - Product/Barcode data source.

Open Food Facts is a collaborative, free database of food products
with barcodes, ingredients, and nutritional information.
"""

import requests
from typing import Optional, List, Dict, Any
from datetime import datetime

from .providers import (
    FoodProviderBase, ProviderFoodResult, ProviderSearchResult
)
from app import db
from .models import Nutrient, FoodProvider


class OpenFoodFactsProvider(FoodProviderBase):
    """Open Food Facts API provider for branded products and barcodes."""
    
    PROVIDER_CODE = "openfoodfacts"
    PROVIDER_NAME = "Open Food Facts"
    BASE_URL = "https://world.openfoodfacts.org"
    RATE_LIMIT_PER_MIN = 100
    RATE_LIMIT_PER_DAY = 10000
    
    # OFF nutrient mappings (OFF key -> our Nutrient.id)
    NUTRIENT_MAP = {
        'energy-kcal_100g': 1008,        # Energy (kcal)
        'proteins_100g': 1003,           # Protein
        'fat_100g': 1004,                # Total fat
        'carbohydrates_100g': 1005,      # Carbohydrates
        'fiber_100g': 1079,              # Fiber
        'sugars_100g': 2000,             # Total sugars
        'sodium_100g': 1093,             # Sodium
        'salt_100g': 1093,               # Salt (convert: salt * 400 = sodium mg)
        'calcium_100g': 1087,            # Calcium
        'iron_100g': 1089,               # Iron
        'potassium_100g': 1092,          # Potassium
        'vitamin-a_100g': 1106,          # Vitamin A
        'vitamin-d_100g': 1110,          # Vitamin D
        'vitamin-e_100g': 1111,          # Vitamin E
        'vitamin-k_100g': 1114,          # Vitamin K
        'vitamin-c_100g': 1162,          # Vitamin C
        'vitamin-b12_100g': 1177,        # Vitamin B12
        'folates_100g': 1178,            # Folate
        'cholesterol_100g': 1253,        # Cholesterol
        'saturated-fat_100g': 1257,      # Saturated fat
        'trans-fat_100g': 1257,          # Trans fat (include in sat fat)
        'omega-3-fat_100g': 1329,        # Omega-3
        'omega-6-fat_100g': 1330,        # Omega-6
    }
    
    def __init__(self, user_agent: str = None, timeout: int = 30):
        super().__init__(api_key=None, timeout=timeout)
        self.session.headers.update({
            'User-Agent': user_agent or 'DinnerSpinner/1.0 (contact@dinnerspinner.app) - Python/requests',
        })
    
    def get_provider_info(self) -> FoodProvider:
        return FoodProvider(
            code=self.PROVIDER_CODE,
            name=self.PROVIDER_NAME,
            base_url=self.BASE_URL,
            provides_nutrients=True,
            provides_barcodes=True,
            provides_branded=True,
            provides_foundation=False,
            rate_limit_per_min=self.RATE_LIMIT_PER_MIN,
            rate_limit_per_day=self.RATE_LIMIT_PER_DAY,
        )
    
    def search(self, query: str, max_results: int = 20, **kwargs) -> List[ProviderSearchResult]:
        """Search Open Food Facts for products."""
        url = f"{self.BASE_URL}/cgi/search.pl"
        params = {
            'search_terms': query,
            'search_simple': 1,
            'action': 'process',
            'json': 1,
            'page_size': max_results,
            'fields': 'code,product_name,brands,categories,nutriments,nutrition_grades',
        }
        
        response = self._make_request('GET', url, params=params)
        data = response.json()
        
        results = []
        for product in data.get('products', []):
            results.append(ProviderSearchResult(
                external_id=product.get('code', ''),
                name=product.get('product_name', ''),
                brand=product.get('brands', ''),
                category=product.get('categories', ''),
                data_type='branded',
                provider_data={
                    'code': product.get('code'),
                    'nutrition_grade': product.get('nutrition_grades'),
                    'nutriments': product.get('nutriments', {}),
                }
            ))
        return results
    
    def get_food(self, external_id: str) -> Optional[ProviderFoodResult]:
        """Get product by barcode/code."""
        url = f"{self.BASE_URL}/api/v0/product/{external_id}.json"
        
        try:
            response = self._make_request('GET', url)
            data = response.json()
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise
        
        if data.get('status') != 1 or 'product' not in data:
            return None
        
        return self._parse_product(data['product'])
    
    def get_food_by_barcode(self, barcode: str) -> Optional[ProviderFoodResult]:
        """Primary barcode lookup - Open Food Facts excels at this."""
        return self.get_food(barcode)
    
    def list_nutrients(self) -> List[Nutrient]:
        """OFF doesn't have a standard nutrient list endpoint."""
        nutrients = []
        for off_key, mapped_id in self.NUTRIENT_MAP.items():
            # We'd need to map OFF keys to proper nutrient definitions
            # For now, return empty - nutrients are created on-demand
            pass
        return nutrients
    
    def _parse_product(self, product: Dict) -> ProviderFoodResult:
        """Parse OFF product into standardized result."""
        nutriments = product.get('nutriments', {})
        
        nutrients = {}
        nutrient_details = {}
        
        for off_key, mapped_id in self.NUTRIENT_MAP.items():
            if off_key in nutriments and nutriments[off_key] is not None:
                amount = nutriments[off_key]
                # Handle salt -> sodium conversion
                if off_key == 'salt_100g':
                    amount = amount * 400  # Convert salt(g) to sodium(mg)
                nutrients[mapped_id] = amount
                nutrient_details[mapped_id] = {
                    'source': 'openfoodfacts',
                    'off_key': off_key,
                }
        
        # Extract aliases
        aliases = []
        if product.get('brands'):
            aliases.extend([b.strip() for b in product['brands'].split(',')])
        if product.get('brands_tags'):
            aliases.extend(product['brands_tags'])
        if product.get('labels'):
            aliases.extend([l.strip() for l in product['labels'].split(',')])
        
        # Category
        category = product.get('categories', '')
        if category:
            category = category.lower().split(',')[0].strip()
        
        # Serving info
        serving_size = product.get('serving_size')
        serving_qty = product.get('serving_quantity')
        
        # Density (if available)
        density = None
        if product.get('nutriments', {}).get('density'):
            density = product['nutriments']['density']
        
        return ProviderFoodResult(
            external_id=product.get('code', ''),
            name=product.get('product_name', ''),
            brand=product.get('brands', ''),
            category=category,
            data_type='branded',
            density=density,
            common_serving=serving_size,
            common_serving_weight=serving_qty,
            nutrients=nutrients,
            nutrient_details=nutrient_details,
            aliases=aliases,
            provider_data={
                'code': product.get('code'),
                'brands': product.get('brands'),
                'categories': product.get('categories'),
                'labels': product.get('labels'),
                'ingredients_text': product.get('ingredients_text'),
                'additives': product.get('additives_tags', []),
                'nutrition_grade': product.get('nutrition_grades'),
                'nova_group': product.get('nova_group'),
                'ecoscore': product.get('ecoscore_grade'),
            },
            external_url=f"https://world.openfoodfacts.org/product/{product.get('code', '')}",
        )
    
    def import_by_barcode(self, barcode: str) -> Optional[object]:
        """Import a product by barcode."""
        return self.import_food(barcode)