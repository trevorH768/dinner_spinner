"""
Health Canada Canadian Nutrient File (CNF) Provider.

The CNF is Canada's authoritative food composition database.
Available as CSV downloads from Health Canada.
"""

import csv
import io
import zipfile
from typing import Optional, List, Dict, Any
from datetime import datetime

from .providers import (
    FoodProviderBase, ProviderFoodResult, ProviderSearchResult, 
    FoodProviderBase
)
from app import db
from .models import Nutrient, FoodProvider


class HealthCanadaCNFProvider(FoodProviderBase):
    """Health Canada Canadian Nutrient File provider."""
    
    PROVIDER_CODE = "hc_cnf"
    PROVIDER_NAME = "Health Canada Canadian Nutrient File"
    BASE_URL = "https://www.canada.ca/en/health-canada/services/food-nutrition/healthy-eating/nutrient-data/canadian-nutrient-file.html"
    RATE_LIMIT_PER_MIN = 30
    RATE_LIMIT_PER_DAY = 1000
    
    # CNF Nutrient ID mappings (CNF nutrient code -> our Nutrient.id)
    NUTRIENT_MAP = {
        # Energy & macros
        208: 1008,   # Energy (kcal)
        203: 1003,   # Protein
        204: 1004,   # Total fat
        205: 1005,   # Carbohydrate
        291: 1079,   # Fiber
        269: 2000,   # Total sugars
        307: 1093,   # Sodium
        # Minerals
        301: 1087,   # Calcium
        303: 1089,   # Iron
        306: 1092,   # Potassium
        304: 304,    # Magnesium
        305: 305,    # Phosphorus
        309: 309,    # Zinc
        312: 312,    # Copper
        # Vitamins
        318: 1106,   # Vitamin A (RAE)
        320: 1109,   # Vitamin D (IU)
        323: 1162,   # Vitamin C
        328: 1111,   # Vitamin E
        329: 1114,   # Vitamin K
        401: 1165,   # Thiamin
        404: 1166,   # Riboflavin
        405: 1167,   # Niacin
        415: 1175,   # Vitamin B6
        418: 1177,   # Vitamin B12
        417: 1178,   # Folate
        # Lipids
        606: 1253,   # Cholesterol
        606: 1257,   # Saturated fat (approximate)
    }
    
    def __init__(self, csv_path: str = None, timeout: int = 30):
        super().__init__(api_key=None, timeout=timeout)
        self.csv_path = csv_path
        self._food_data = None
        self._nutrient_data = None
        self._conversion_data = None
        self._refuse_data = None
        self._yield_data = None
    
    def get_provider_info(self) -> FoodProvider:
        return FoodProvider(
            code=self.PROVIDER_CODE,
            name=self.PROVIDER_NAME,
            base_url=self.BASE_URL,
            provides_nutrients=True,
            provides_barcodes=False,
            provides_branded=False,
            provides_foundation=True,
            rate_limit_per_min=self.RATE_LIMIT_PER_MIN,
            rate_limit_per_day=self.RATE_LIMIT_PER_DAY,
        )
    
    def _load_data(self):
        """Load CNF CSV files into memory."""
        if self._food_data is not None:
            return
        
        if not self.csv_path:
            raise ValueError("CNF CSV path required. Download from Health Canada.")
        
        # Expected files in the CNF release:
        # - FOOD NAME.csv
        # - NUTRIENT AMOUNT.csv
        # - NUTRIENT NAME.csv
        # - CONVERSION FACTOR.csv
        # - REFUSE AMOUNT.csv
        # - YIELD AMOUNT.csv
        
        import os
        
        # Load food names
        self._food_data = {}
        with open(os.path.join(self.csv_path, 'FOOD NAME.csv'), 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                food_id = int(row['FoodID'])
                self._food_data[food_id] = row
        
        # Load nutrient names
        self._nutrient_data = {}
        with open(os.path.join(self.csv_path, 'NUTRIENT NAME.csv'), 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                self._nutrient_data[int(row['NutrientID'])] = row
        
        # Load nutrient amounts
        self._amount_data = {}
        with open(os.path.join(self.csv_path, 'NUTRIENT AMOUNT.csv'), 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                food_id = int(row['FoodID'])
                nut_id = int(row['NutrientID'])
                if food_id not in self._amount_data:
                    self._amount_data[food_id] = {}
                self._amount_data[food_id][nut_id] = float(row['NutrientValue'])
        
        # Load conversion factors
        self._conversion_data = {}
        with open(os.path.join(self.csv_path, 'CONVERSION FACTOR.csv'), 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                food_id = int(row['FoodID'])
                if food_id not in self._conversion_data:
                    self._conversion_data[food_id] = []
                self._conversion_data[food_id].append(row)
        
        # Load refuse amounts
        self._refuse_data = {}
        with open(os.path.join(self.csv_path, 'REFUSE AMOUNT.csv'), 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                self._refuse_data[int(row['FoodID'])] = float(row['RefuseAmount'])
        
        # Load yield amounts
        self._yield_data = {}
        with open(os.path.join(self.csv_path, 'YIELD AMOUNT.csv'), 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                self._yield_data[int(row['FoodID'])] = float(row['YieldAmount'])
    
    def get_provider_info(self) -> FoodProvider:
        return FoodProvider(
            code=self.PROVIDER_CODE,
            name=self.PROVIDER_NAME,
            base_url=self.BASE_URL,
            provides_nutrients=True,
            provides_barcodes=False,
            provides_branded=False,
            provides_foundation=True,
        )
    
    def search(self, query: str, max_results: int = 20, **kwargs) -> List[ProviderSearchResult]:
        self._load_data()
        query_lower = query.lower()
        results = []
        
        for food_id, food in self._food_data.items():
            if query_lower in food['FoodDescription'].lower():
                results.append(ProviderSearchResult(
                    external_id=str(food_id),
                    name=food['FoodDescription'],
                    category=food.get('FoodGroup'),
                    data_type='foundation',
                    provider_data={'food_id': food_id}
                ))
                if len(results) >= max_results:
                    break
        
        return results
    
    def get_food(self, external_id: str) -> Optional[ProviderFoodResult]:
        self._load_data()
        food_id = int(external_id)
        
        if food_id not in self._food_data:
            return None
        
        food = self._food_data[food_id]
        amounts = self._amount_data.get(food_id, {})
        conversions = self._conversion_data.get(food_id, [])
        refuse = self._refuse_data.get(food_id)
        
        nutrients = {}
        nutrient_details = {}
        
        for cnf_id, amount in amounts.items():
            if cnf_id in self.NUTRIENT_MAP:
                mapped_id = self.NUTRIENT_MAP[cnf_id]
                # CNF values are per 100g edible portion
                nutrients[mapped_id] = amount
                nutrient_details[mapped_id] = {
                    'source': 'cnf',
                    'cnf_nutrient_id': cnf_id,
                }
        
        # Get density from conversion factors
        density = None
        serving_weight = None
        serving_desc = None
        for conv in conversions:
            if conv['ConversionFactorValue'] and float(conv['ConversionFactorValue']) > 0:
                # First conversion is usually density (g/ml)
                if density is None:
                    density = float(conv['ConversionFactorValue'])
                elif serving_weight is None:
                    serving_weight = float(conv['ConversionFactorValue'])
                    serving_desc = conv.get('MeasureDescription')
        
        refuse_pct = refuse if refuse else None
        
        # Get aliases from synonyms if available
        aliases = []
        # CNF doesn't provide synonyms in standard download
        
        category = food.get('FoodGroup')
        if category:
            category = category.lower().replace(' ', '_')
        
        return ProviderFoodResult(
            external_id=external_id,
            name=food['FoodDescription'],
            category=category,
            data_type='foundation',
            density=density,
            refuse_pct=refuse_pct,
            common_serving=serving_desc,
            common_serving_weight=serving_weight,
            nutrients=nutrients,
            nutrient_details=nutrient_details,
            aliases=aliases,
            provider_data={'food_id': food_id},
            external_url=None,
        )
    
    def get_food_by_barcode(self, barcode: str) -> Optional[ProviderFoodResult]:
        """CNF doesn't have barcodes."""
        return None
    
    def list_nutrients(self) -> List[Nutrient]:
        self._load_data()
        nutrients = []
        for nut_id, nut_data in self._nutrient_data.items():
            if nut_id in self.NUTRIENT_MAP:
                mapped_id = self.NUTRIENT_MAP[nut_id]
                nut = Nutrient(
                    id=mapped_id,
                    name=nut_data['NutrientName'],
                    unit=nut_data['Unit'],
                    nutrient_nbr=str(nut_id),
                )
                nutrients.append(nut)
        return nutrients
    
    def import_all(self, limit: int = None) -> int:
        """Bulk import all CNF foods."""
        self._load_data()
        imported = 0
        
        for food_id in self._food_data:
            try:
                self.import_food(str(food_id))
                imported += 1
                if limit and imported >= limit:
                    break
            except Exception as e:
                logger.error(f"Failed to import CNF {food_id}: {e}")
        
        return imported