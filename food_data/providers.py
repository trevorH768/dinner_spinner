"""
Provider interface and implementations for food data sources.

Each provider implements the FoodProviderBase interface and handles
communication with its respective API/data source.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Iterator
from datetime import datetime
import requests
import logging

from app import db
from .models import (
    Food, FoodNutrient, Nutrient, FoodProvider, FoodProvenance, 
    FoodAlias, FoodCategory, DataType
)

logger = logging.getLogger(__name__)


@dataclass
class ProviderFoodResult:
    """Standardized result from a provider search/import."""
    external_id: str
    name: str
    scientific_name: Optional[str] = None
    category: Optional[str] = None
    data_type: str = "foundation"
    density: Optional[float] = None
    water_content: Optional[float] = None
    refuse_pct: Optional[float] = None
    common_serving: Optional[str] = None
    common_serving_weight: Optional[float] = None
    nutrients: Dict[int, float] = field(default_factory=dict)  # nutrient_id -> amount per 100g
    nutrient_details: Dict[int, Dict[str, Any]] = field(default_factory=dict)  # full nutrient metadata
    aliases: List[str] = field(default_factory=list)
    provider_data: Dict[str, Any] = field(default_factory=dict)
    external_url: Optional[str] = None


@dataclass
class ProviderSearchResult:
    """Result from a provider search."""
    external_id: str
    name: str
    brand: Optional[str] = None
    category: Optional[str] = None
    data_type: str = "branded"
    provider_data: Dict[str, Any] = field(default_factory=dict)


class FoodProviderBase(ABC):
    """
    Abstract base class for food data providers.
    
    All providers must implement this interface to ensure
    consistent integration with the FoodService.
    """
    
    PROVIDER_CODE: str = "base"
    PROVIDER_NAME: str = "Base Provider"
    BASE_URL: str = ""
    RATE_LIMIT_PER_MIN: int = 60
    RATE_LIMIT_PER_DAY: int = 10000
    
    def __init__(self, api_key: Optional[str] = None, timeout: int = 30):
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        self._request_count_min = 0
        self._request_count_day = 0
        self._minute_start = datetime.utcnow()
        self._day_start = datetime.utcnow().date()
    
    @abstractmethod
    def get_provider_info(self) -> FoodProvider:
        """Return FoodProvider database record for this provider."""
        pass
    
    @abstractmethod
    def search(self, query: str, max_results: int = 20, **kwargs) -> List[ProviderSearchResult]:
        """Search for foods by name/keyword."""
        pass
    
    @abstractmethod
    def get_food(self, external_id: str) -> Optional[ProviderFoodResult]:
        """Get full food details by external ID."""
        pass
    
    @abstractmethod
    def get_food_by_barcode(self, barcode: str) -> Optional[ProviderFoodResult]:
        """Get food by barcode/UPC (if supported)."""
        pass
    
    @abstractmethod
    def list_nutrients(self) -> List[Nutrient]:
        """Get nutrient definitions from provider."""
        pass
    
    def _rate_limit(self):
        """Enforce rate limits."""
        now = datetime.utcnow()
        # Reset minute counter
        if (now - self._minute_start).total_seconds() >= 60:
            self._request_count_min = 0
            self._minute_start = now
        # Reset day counter
        if now.date() > self._day_start:
            self._request_count_day = 0
            self._day_start = now.date()
        
        if self._request_count_min >= self.RATE_LIMIT_PER_MIN:
            raise Exception(f"Rate limit exceeded: {self.RATE_LIMIT_PER_MIN} requests/min")
        if self._request_count_day >= self.RATE_LIMIT_PER_DAY:
            raise Exception(f"Rate limit exceeded: {self.RATE_LIMIT_PER_DAY} requests/day")
        
        self._request_count_min += 1
        self._request_count_day += 1
    
    def _make_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make HTTP request with rate limiting and error handling."""
        self._rate_limit()
        try:
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            logger.error(f"Provider {self.PROVIDER_CODE} request failed: {e}")
            raise
    
    def _get_or_create_provider_record(self) -> FoodProvider:
        """Get or create the FoodProvider database record."""
        provider = FoodProvider.query.filter_by(code=self.PROVIDER_CODE).first()
        if not provider:
            provider = FoodProvider(
                code=self.PROVIDER_CODE,
                name=self.PROVIDER_NAME,
                base_url=self.BASE_URL,
                provides_nutrients=True,
                provides_barcodes=False,
                provides_branded=False,
                provides_foundation=True,
            )
            db.session.add(provider)
            db.session.flush()
        return provider
    
    def import_food(self, external_id: str, match_existing: bool = True) -> Optional[Food]:
        """
        Import a food from this provider into the canonical Food model.
        
        Args:
            external_id: Provider-specific food identifier
            match_existing: Try to match with existing foods first
            
        Returns:
            Food object if imported/found, None if failed
        """
        result = self.get_food(external_id)
        if not result:
            return None
        
        provider_record = self._get_or_create_provider_record()
        
        # Check for existing provenance
        existing_prov = FoodProvenance.query.filter_by(
            provider_id=provider_record.id,
            external_id=external_id
        ).first()
        
        if existing_prov:
            # Update existing food
            food = existing_prov.food
            self._update_food_from_result(food, result, provider_record, existing_prov)
            return food
        
        # Try to find matching food if requested
        food = None
        if match_existing:
            food = self._find_matching_food(result)
        
        if not food:
            food = self._create_food_from_result(result)
        
        # Create provenance link
        provenance = FoodProvenance(
            food_id=food.id,
            provider_id=provider_record.id,
            external_id=external_id,
            external_url=result.external_url,
            provider_data=result.provider_data,
            is_primary=True,
            confidence=1.0,
        )
        db.session.add(provenance)
        
        # Add aliases
        self._add_aliases(food, result.aliases, provider_record)
        
        db.session.commit()
        return food
    
    def _find_matching_food(self, result: ProviderFoodResult) -> Optional[Food]:
        """Try to find an existing food that matches the result."""
        # Exact name match
        food = Food.query.filter(Food.name.ilike(result.name)).first()
        if food:
            return food
        
        # Alias match
        alias = FoodAlias.query.filter(FoodAlias.alias.ilike(result.name)).first()
        if alias:
            return alias.food
        
        return None
    
    def _create_food_from_result(self, result: ProviderFoodResult) -> Food:
        """Create new Food from provider result."""
        category = None
        if result.category:
            cat = FoodCategory.query.filter_by(name=result.category.lower()).first()
            if not cat:
                cat = FoodCategory(
                    name=result.category.lower(),
                    display_name=result.category.title()
                )
                db.session.add(cat)
                db.session.flush()
            category = cat.name
        
        food = Food(
            name=result.name,
            scientific_name=result.scientific_name,
            category=category,
            data_type=result.data_type,
            density=result.density,
            water_content=result.water_content,
            refuse_pct=result.refuse_pct,
            common_serving=result.common_serving,
            common_serving_weight=result.common_serving_weight,
        )
        db.session.add(food)
        db.session.flush()
        
        # Add nutrients
        for nutrient_id, amount in result.nutrients.items():
            fn = FoodNutrient(
                food_id=food.id,
                nutrient_id=nutrient_id,
                amount=amount,
            )
            if nutrient_id in result.nutrient_details:
                details = result.nutrient_details[nutrient_id]
                fn.min_amount = details.get('min')
                fn.max_amount = details.get('max')
                fn.median_amount = details.get('median')
                fn.std_dev = details.get('std_dev')
                fn.num_samples = details.get('n')
                fn.derivation_code = details.get('derivation_code')
                fn.derivation_desc = details.get('derivation_desc')
            db.session.add(fn)
        
        return food
    
    def _update_food_from_result(self, food: Food, result: ProviderFoodResult, 
                                  provider: FoodProvider, provenance: FoodProvenance):
        """Update existing food with new provider data."""
        # Update basic fields if not set
        if not food.scientific_name and result.scientific_name:
            food.scientific_name = result.scientific_name
        if not food.category and result.category:
            # ... category handling
            pass
        if not food.density and result.density:
            food.density = result.density
        if not food.water_content and result.water_content:
            food.water_content = result.water_content
        if not food.refuse_pct and result.refuse_pct:
            food.refuse_pct = result.refuse_pct
        
        # Update nutrients (add missing, don't overwrite existing)
        for nutrient_id, amount in result.nutrients.items():
            existing = FoodNutrient.query.filter_by(
                food_id=food.id, nutrient_id=nutrient_id
            ).first()
            if not existing:
                fn = FoodNutrient(food_id=food.id, nutrient_id=nutrient_id, amount=amount)
                if nutrient_id in result.nutrient_details:
                    details = result.nutrient_details[nutrient_id]
                    fn.min_amount = details.get('min')
                    fn.max_amount = details.get('max')
                    fn.median_amount = details.get('median')
                    fn.std_dev = details.get('std_dev')
                    fn.num_samples = details.get('n')
                db.session.add(fn)
        
        # Update provenance
        provenance.provider_data = result.provider_data
        provenance.last_updated = datetime.utcnow()
        provenance.last_verified = datetime.utcnow()
        
        # Add new aliases
        self._add_aliases(food, result.aliases, self._get_or_create_provider_record())
        
        food.updated_at = datetime.utcnow()
    
    def _add_aliases(self, food: Food, aliases: List[str], provider: FoodProvider):
        """Add aliases for a food."""
        for alias in aliases:
            if not alias or alias.lower() == food.name.lower():
                continue
            existing = FoodAlias.query.filter_by(
                food_id=food.id, alias=alias
            ).first()
            if not existing:
                fa = FoodAlias(
                    food_id=food.id,
                    alias=alias,
                    alias_type='synonym',
                    provider_id=provider.id,
                    search_weight=0.8,
                )
                db.session.add(fa)


class USDAFoodDataCentralProvider(FoodProviderBase):
    """USDA FoodData Central API provider."""
    
    PROVIDER_CODE = "usda_fdc"
    PROVIDER_NAME = "USDA FoodData Central"
    BASE_URL = "https://api.nal.usda.gov/fdc/v1"
    RATE_LIMIT_PER_MIN = 60
    RATE_LIMIT_PER_DAY = 10000
    
    # USDA Nutrient ID mappings (FDC -> our Nutrient.id)
    NUTRIENT_MAP = {
        1008: 1008,   # Energy (kcal)
        1003: 1003,   # Protein
        1004: 1004,   # Total lipid (fat)
        1005: 1005,   # Carbohydrate
        1079: 1079,   # Fiber
        2000: 2000,   # Total sugars
        1093: 1093,   # Sodium
        1087: 1087,   # Calcium
        1089: 1089,   # Iron
        1092: 1092,   # Potassium
        1104: 1104,   # Vitamin A (IU)
        1106: 1106,   # Vitamin A (RAE)
        1162: 1162,   # Vitamin C
        1109: 1109,   # Vitamin D (IU)
        1110: 1110,   # Vitamin D (µg)
        1111: 1111,   # Vitamin E
        1114: 1114,   # Vitamin K
        1165: 1165,   # Thiamin
        1166: 1166,   # Riboflavin
        1167: 1167,   # Niacin
        1175: 1175,   # Vitamin B6
        1177: 1177,   # Vitamin B12
        1178: 1178,   # Folate
        1180: 1180,   # Choline
        1253: 1253,   # Cholesterol
        1257: 1257,   # Saturated fat
        1258: 1258,   # Monounsaturated fat
        1259: 1259,   # Polyunsaturated fat
        1329: 1329,   # Omega-3 fatty acids
        1330: 1330,   # Omega-6 fatty acids
    }
    
    def __init__(self, api_key: str = None, timeout: int = 30):
        super().__init__(api_key, timeout)
        if not self.api_key:
            raise ValueError("USDA FDC API key required")
    
    def get_provider_info(self) -> FoodProvider:
        return FoodProvider(
            code=self.PROVIDER_CODE,
            name=self.PROVIDER_NAME,
            base_url=self.BASE_URL,
            provides_nutrients=True,
            provides_barcodes=False,
            provides_branded=True,
            provides_foundation=True,
            rate_limit_per_min=self.RATE_LIMIT_PER_MIN,
            rate_limit_per_day=self.RATE_LIMIT_PER_DAY,
        )
    
    def _get_headers(self) -> Dict[str, str]:
        return {
            'api_key': self.api_key,
            'Content-Type': 'application/json',
        }
    
    def search(self, query: str, max_results: int = 20, 
               data_type: Optional[List[str]] = None, **kwargs) -> List[ProviderSearchResult]:
        """Search USDA FDC for foods."""
        url = f"{self.BASE_URL}/foods/search"
        params = {
            'query': query,
            'pageSize': max_results,
            'api_key': self.api_key,
        }
        if data_type:
            params['dataType'] = data_type
        
        response = self._make_request('GET', url, params=params)
        data = response.json()
        
        results = []
        for item in data.get('foods', []):
            results.append(ProviderSearchResult(
                external_id=str(item['fdcId']),
                name=item.get('description', ''),
                brand=item.get('brandOwner'),
                category=item.get('foodCategory'),
                data_type=item.get('dataType', 'foundation').lower(),
                provider_data={'fdc_id': item['fdcId']}
            ))
        return results
    
    def get_food(self, external_id: str) -> Optional[ProviderFoodResult]:
        """Get full food details from USDA FDC."""
        url = f"{self.BASE_URL}/food/{external_id}"
        params = {'api_key': self.api_key}
        
        try:
            response = self._make_request('GET', url, params=params)
            data = response.json()
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise
        
        return self._parse_food(data)
    
    def get_food_by_barcode(self, barcode: str) -> Optional[ProviderFoodResult]:
        """USDA FDC doesn't support barcode lookup directly."""
        # Search by barcode as query
        results = self.search(barcode, max_results=1, data_type=['branded'])
        if results:
            return self.get_food(results[0].external_id)
        return None
    
    def list_nutrients(self) -> List[Nutrient]:
        """Get nutrient definitions from USDA."""
        url = f"{self.BASE_URL}/nutrients"
        params = {'api_key': self.api_key, 'pageSize': 200}
        
        response = self._make_request('GET', url, params=params)
        data = response.json()
        
        nutrients = []
        for item in data:
            nut = Nutrient(
                id=item['id'],
                name=item['name'],
                unit=item['unitName'],
                nutrient_nbr=str(item.get('nutrientNbr', '')),
                rank=item.get('rank'),
            )
            nutrients.append(nut)
        return nutrients
    
    def _parse_food(self, data: Dict) -> ProviderFoodResult:
        """Parse USDA FDC food response into standardized result."""
        nutrients = {}
        nutrient_details = {}
        
        for nut in data.get('foodNutrients', []):
            nut_id = nut['nutrient']['id']
            if nut_id in self.NUTRIENT_MAP:
                mapped_id = self.NUTRIENT_MAP[nut_id]
                amount = nut.get('amount', 0)
                # Convert to per 100g if needed
                if nut.get('amountPer100g') is not None:
                    amount = nut['amountPer100g']
                nutrients[mapped_id] = amount
                nutrient_details[mapped_id] = {
                    'min': nut.get('min'),
                    'max': nut.get('max'),
                    'median': nut.get('median'),
                    'std_dev': nut.get('stdDev'),
                    'n': nut.get('numberOfSamples'),
                    'derivation_code': nut.get('derivationCode'),
                    'derivation_desc': nut.get('derivationDescription'),
                }
        
        # Extract aliases
        aliases = []
        for syn in data.get('synonyms', []):
            aliases.append(syn)
        if data.get('brandOwner'):
            aliases.append(data['brandOwner'])
        
        # Category mapping
        category = data.get('foodCategory')
        if category:
            category = category.lower().replace(' ', '_')
        
        return ProviderFoodResult(
            external_id=str(data['fdcId']),
            name=data.get('description', ''),
            scientific_name=data.get('scientificName'),
            category=category,
            data_type=data.get('dataType', 'foundation').lower(),
            density=None,  # Not directly provided
            common_serving=None,
            common_serving_weight=None,
            nutrients=nutrients,
            nutrient_details=nutrient_details,
            aliases=aliases,
            provider_data={'fdc_id': data['fdcId'], 'data_type': data.get('dataType')},
            external_url=f"https://fdc.nal.usda.gov/fdc-app.html#/food-details/{data['fdcId']}",
        )
    
    def import_foundation_foods(self, limit: int = 1000, offset: int = 0) -> int:
        """Bulk import foundation foods from USDA."""
        url = f"{self.BASE_URL}/foods/list"
        params = {
            'api_key': self.api_key,
            'dataType': ['Foundation', 'SR Legacy'],
            'pageSize': min(limit, 200),
            'pageNumber': (offset // 200) + 1,
        }
        
        imported = 0
        while imported < limit:
            response = self._make_request('GET', url, params=params)
            data = response.json()
            
            if not data:
                break
            
            for item in data:
                try:
                    self.import_food(str(item['fdcId']))
                    imported += 1
                    if imported >= limit:
                        break
                except Exception as e:
                    logger.error(f"Failed to import FDC {item['fdcId']}: {e}")
            
            params['pageNumber'] += 1
        
        return imported