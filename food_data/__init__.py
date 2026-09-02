"""
Provider-agnostic food data subsystem for Dinner Spinner.

This module provides a canonical Food model and a provider interface for
importing nutritional data from multiple sources:
- USDA FoodData Central (nutritional data)
- Health Canada Canadian Nutrient File (nutritional data)  
- Open Food Facts (product/barcode data)

The canonical Food model is the single source of truth for nutritional
information. All providers import into this model with full provenance tracking.
"""

from .models import (
    Food,
    FoodNutrient,
    Nutrient,
    FoodProvider,
    FoodProvenance,
    FoodAlias,
    IngredientFoodLink,
)
from .providers import (
    FoodProviderBase,
    USDAFoodDataCentralProvider,
)
from .cnf_provider import HealthCanadaCNFProvider
from .off_provider import OpenFoodFactsProvider
from .registry import ProviderRegistry, provider_registry, init_providers
from .service import FoodService

__all__ = [
    'Food',
    'FoodNutrient',
    'Nutrient',
    'FoodProvider',
    'FoodProvenance',
    'FoodAlias',
    'FoodProviderBase',
    'USDAFoodDataCentralProvider',
    'HealthCanadaCNFProvider',
    'OpenFoodFactsProvider',
    'ProviderRegistry',
    'provider_registry',
    'init_providers',
    'FoodService',
]