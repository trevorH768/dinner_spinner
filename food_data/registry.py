"""
Provider registry for managing food data providers.

The registry handles provider registration, discovery, and routing
of requests to appropriate providers.
"""

from typing import Dict, List, Optional, Type
from datetime import datetime

from app import db
from .providers import FoodProviderBase, FoodProvider
from .models import FoodProvider as FoodProviderModel


class ProviderRegistry:
    """Registry for food data providers."""
    
    def __init__(self):
        self._providers: Dict[str, FoodProviderBase] = {}
        self._provider_classes: Dict[str, Type[FoodProviderBase]] = {}
    
    def register_class(self, provider_class: Type[FoodProviderBase], *args, **kwargs):
        """Register a provider class for lazy instantiation."""
        instance = provider_class(*args, **kwargs)
        self._provider_classes[instance.PROVIDER_CODE] = provider_class
        self._providers[instance.PROVIDER_CODE] = instance
        # Don't sync to database here - use sync_providers() explicitly
    
    def sync_providers(self, db_instance=None):
        """Sync all registered providers to database. Must be called within app context."""
        if db_instance is None:
            from flask import current_app
            db_instance = current_app.extensions['sqlalchemy'].db
        from .models import FoodProvider as FoodProviderModel
        
        for provider in self._providers.values():
            provider_info = provider.get_provider_info()
            db_provider = FoodProviderModel.query.filter_by(code=provider_info.code).first()
            if not db_provider:
                db_provider = FoodProviderModel(
                    code=provider_info.code,
                    name=provider_info.name,
                    base_url=provider_info.base_url,
                    provides_nutrients=provider_info.provides_nutrients,
                    provides_barcodes=provider_info.provides_barcodes,
                    provides_branded=provider_info.provides_branded,
                    provides_foundation=provider_info.provides_foundation,
                    rate_limit_per_min=provider_info.rate_limit_per_min,
                    rate_limit_per_day=provider_info.rate_limit_per_day,
                )
                db_instance.session.add(db_provider)
            else:
                # Update fields
                db_provider.name = provider_info.name
                db_provider.base_url = provider_info.base_url
                db_provider.provides_nutrients = provider_info.provides_nutrients
                db_provider.provides_barcodes = provider_info.provides_barcodes
                db_provider.provides_branded = provider_info.provides_branded
                db_provider.provides_foundation = provider_info.provides_foundation
                db_provider.rate_limit_per_min = provider_info.rate_limit_per_min
                db_provider.rate_limit_per_day = provider_info.rate_limit_per_day
        db_instance.session.commit()
    
    def get(self, code: str) -> Optional[FoodProviderBase]:
        """Get provider instance by code."""
        return self._providers.get(code)
    
    def get_all(self) -> List[FoodProviderBase]:
        """Get all registered providers."""
        return list(self._providers.values())
    
    def get_active(self) -> List[FoodProviderBase]:
        """Get only active providers (from database)."""
        active_codes = [p.code for p in FoodProviderModel.query.filter_by(is_active=True).all()]
        return [self._providers[c] for c in active_codes if c in self._providers]
    
    def search_all(self, query: str, max_results: int = 20, 
                   providers: List[str] = None) -> Dict[str, List]:
        """
        Search across multiple providers.
        
        Returns dict of provider_code -> list of search results.
        """
        if providers is None:
            providers = [p.PROVIDER_CODE for p in self.get_active()]
        
        results = {}
        for code in providers:
            provider = self.get(code)
            if provider:
                try:
                    results[code] = provider.search(query, max_results)
                except Exception as e:
                    results[code] = []
        return results
    
    def get_food(self, external_id: str, provider_code: str) -> Optional[object]:
        """Get food from specific provider by external ID."""
        provider = self.get(provider_code)
        if provider:
            return provider.get_food(external_id)
        return None
    
    def get_food_by_barcode(self, barcode: str, 
                             providers: List[str] = None) -> Optional[object]:
        """
        Look up food by barcode across providers.
        
        Tries providers in order: OFF -> USDA -> others
        """
        if providers is None:
            # Default priority: OFF for barcodes, then USDA
            providers = ['openfoodfacts', 'usda_fdc']
        
        for code in providers:
            provider = self.get(code)
            if provider and provider.get_provider_info().provides_barcodes:
                try:
                    result = provider.get_food_by_barcode(barcode)
                    if result:
                        return result
                except Exception as e:
                    continue
        return None
    
    def import_food(self, external_id: str, provider_code: str) -> Optional[object]:
        """Import food from specific provider."""
        provider = self.get(provider_code)
        if provider:
            return provider.import_food(external_id)
        return None
    
    def list_nutrients(self) -> List:
        """Get all nutrients from all providers."""
        all_nutrients = []
        for provider in self.get_active():
            try:
                all_nutrients.extend(provider.list_nutrients())
            except Exception:
                pass
        return all_nutrients
    
    def sync_provider_status(self):
        """Update provider status from database."""
        db_providers = FoodProviderModel.query.all()
        for db_p in db_providers:
            if db_p.code in self._providers:
                self._providers[db_p.code]._get_or_create_provider_record()


# Global registry instance
provider_registry = ProviderRegistry()


def init_providers(usda_api_key: str = None, off_user_agent: str = None, 
                   cnf_csv_path: str = None, db_instance=None):
    """Initialize all providers with configuration."""
    
    # USDA FoodData Central
    if usda_api_key:
        from .providers import USDAFoodDataCentralProvider
        provider_registry.register_class(USDAFoodDataCentralProvider, usda_api_key)
    
    # Open Food Facts
    from .off_provider import OpenFoodFactsProvider
    provider_registry.register_class(OpenFoodFactsProvider, off_user_agent)
    
    # Health Canada CNF
    if cnf_csv_path:
        from .cnf_provider import HealthCanadaCNFProvider
        provider_registry.register_class(HealthCanadaCNFProvider, cnf_csv_path)
    
    # Note: Database sync is now manual - call provider_registry.sync_providers(db) after db.create_all()
    
    return provider_registry