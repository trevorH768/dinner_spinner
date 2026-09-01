"""
CLI commands for food data management.
Add these to your Flask app's CLI.
"""

import click
from flask import current_app
from flask.cli import with_appcontext


def register_food_commands(app):
    """Register food data CLI commands."""
    
    @app.cli.group()
    def food():
        """Food data management commands."""
        pass
    
    @food.command()
    @click.option('--limit', default=1000, help='Max foods to import')
    @with_appcontext
    def import_usda(limit):
        """Import foundation foods from USDA FoodData Central."""
        from food_data.service import FoodService
        service = FoodService()
        count = service.bulk_import_usda(limit)
        click.echo(f'Imported {count} foods from USDA FDC')
    
    @food.command()
    @click.option('--limit', default=None, type=int, help='Max foods to import')
    @with_appcontext
    def import_cnf(limit):
        """Import foods from Health Canada CNF."""
        from food_data.service import FoodService
        service = FoodService()
        count = service.bulk_import_cnf(limit)
        click.echo(f'Imported {count} foods from CNF')
    
    @food.command()
    @click.argument('barcode')
    @with_appcontext
    def import_barcode(barcode):
        """Import a product by barcode."""
        from food_data.service import FoodService
        service = FoodService()
        food = service.import_by_barcode(barcode)
        if food:
            click.echo(f'Imported: {food.name} (ID: {food.id})')
        else:
            click.echo('Product not found')
    
    @food.command()
    @with_appcontext
    def init_nutrients():
        """Initialize core nutrient definitions."""
        from food_data.service import FoodService
        service = FoodService()
        count = service.ensure_core_nutrients()
        click.echo(f'Created {count} core nutrients')
    
    @food.command()
    @click.option('--threshold', default=0.8, help='Confidence threshold')
    @with_appcontext
    def auto_link(threshold):
        """Auto-link ingredients to foods by name matching."""
        from food_data.service import FoodService
        service = FoodService()
        count = service.auto_link_ingredients(threshold)
        click.echo(f'Auto-linked {count} ingredients')
    
    @food.command()
    @click.argument('query')
    @click.option('--max', default=10, help='Max results')
    @with_appcontext
    def search(query, max):
        """Search foods across all providers."""
        from food_data.service import FoodService
        service = FoodService()
        results = service.search(query, max)
        for r in results:
            click.echo(f"  [{r['provider']}] {r['name']} ({r['category']}) - {r['data_type']}")
    
    @food.command()
    @click.argument('barcode')
    @with_appcontext
    def barcode(barcode):
        """Search by barcode."""
        from food_data.service import FoodService
        service = FoodService()
        result = service.search_by_barcode(barcode)
        if result:
            click.echo(f"Found: {result['name']} ({result['category']}) via {result['provider']}")
        else:
            click.echo('Not found')
    
    @food.command()
    @with_appcontext
    def providers():
        """List registered providers."""
        from food_data.registry import provider_registry
        for p in provider_registry.get_all():
            info = p.get_provider_info()
            click.echo(f"  {info.code}: {info.name} (nutrients={info.provides_nutrients}, barcodes={info.provides_barcodes}, branded={info.provides_branded})")
    
    @food.command()
    @click.argument('ingredient_id', type=int)
    @click.argument('food_id', type=int)
    @with_appcontext
    def link(ingredient_id, food_id):
        """Link ingredient to food for nutrition."""
        from food_data.service import FoodService
        service = FoodService()
        link = service.link_ingredient_to_food(ingredient_id, food_id)
        click.echo(f'Linked ingredient {ingredient_id} to food {food_id} ({link.match_type})')
    
    @food.command()
    @click.argument('ingredient_id', type=int)
    @with_appcontext
    def nutrition(ingredient_id):
        """Get nutrition for an ingredient."""
        from food_data.service import FoodService
        service = FoodService()
        nut = service.get_ingredient_nutrition(ingredient_id)
        if nut:
            click.echo(f"Food: {nut['food_name']}")
            click.echo(f"Serving: {nut['serving_weight_g']}g ({nut['serving_unit']})")
            for macro, value in nut['macros_per_serving'].items():
                click.echo(f"  {macro}: {value}")
        else:
            click.echo('No nutrition link found')
    
    @food.command()
    @click.argument('recipe_id', type=int)
    @with_appcontext
    def recipe_nutrition(recipe_id):
        """Calculate nutrition for a recipe."""
        from food_data.service import FoodService
        service = FoodService()
        nut = service.calculate_recipe_nutrition(recipe_id)
        if nut:
            click.echo(f"Recipe: {nut['recipe_name']} ({nut['servings']} servings)")
            click.echo("Per serving:")
            for macro, value in nut['per_serving'].items():
                click.echo(f"  {macro}: {value}")
            click.echo(f"\nTotal:")
            for macro, value in nut['total_macros'].items():
                click.echo(f"  {macro}: {value}")
        else:
            click.echo('Recipe not found or no nutrition data')