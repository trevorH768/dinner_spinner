import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///meal_planner.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Food Data Provider Configuration
app.config['USDA_FDC_API_KEY'] = os.environ.get('USDA_FDC_API_KEY', '')
app.config['OFF_USER_AGENT'] = os.environ.get('OFF_USER_AGENT', 'DinnerSpinner/1.0')
app.config['CNF_CSV_PATH'] = os.environ.get('CNF_CSV_PATH', '')

db = SQLAlchemy(app)

# Import canonical unit conversion
from units import (
    convert, to_base, to_grams, to_ml, is_compatible, parse_unit,
    UnitConversionError, MissingDensityError, MissingItemWeightError
)

# Import food_data models to register IngredientFoodLink with SQLAlchemy
# Must be done before defining Ingredient class which references it
import food_data.models

# Import food_data CLI commands
from food_data.cli import register_food_commands

# Register CLI commands
register_food_commands(app)


class Ingredient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(30), nullable=False, default='Other')  # Dairy, Meat, Produce, Dry Goods, Canned Goods, Other
    unit = db.Column(db.String(20), nullable=False)  # recipe unit: 'g', 'ml', 'cup', 'piece', 'tbsp', 'tsp', etc.
    
    # Package info (what you buy at the store)
    package_price = db.Column(db.Float, nullable=False)      # total price paid
    package_quantity = db.Column(db.Float, nullable=False)   # e.g., 2 (for 2kg, 2L, 2lb, etc.)
    package_unit = db.Column(db.String(10), nullable=False)  # 'g', 'kg', 'ml', 'l', 'lb', 'oz', 'each'
    
    quantity_on_hand = db.Column(db.Float, default=0.0)  # inventory tracking (in recipe unit)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Nutrition link
    food_link = db.relationship('IngredientFoodLink', backref='ingredient', uselist=False, lazy='joined')

    def __repr__(self):
        return f'<Ingredient {self.name}>'
    
    @property
    def linked_food(self):
        """Get the linked canonical Food for nutrition data."""
        if self.food_link:
            return self.food_link.food
        return None
    
    def get_nutrition(self, serving_weight_g: float = None):
        """Get nutrition info for this ingredient."""
        if not self.food_link:
            return None
        from meal_planner.food_data.service import FoodService
        service = FoodService()
        return service.get_ingredient_nutrition(self.id)

    def cost_per_base_unit(self):
        """Return cost per gram (for weight) or per ml (for volume) or per piece"""
        try:
            base_qty = to_base(self.package_quantity, self.package_unit)
        except UnitConversionError:
            # Fallback for unrecognized units
            return 0
        
        if base_qty <= 0:
            return 0
        return self.package_price / base_qty
    
    def cost_per_recipe_unit(self, recipe_unit=None, density=None):
        """Cost per recipe unit (g, ml, piece, cup, etc.)
        
        Args:
            recipe_unit: The unit used in the recipe (defaults to self.unit)
            density: Optional density in g/ml for volume↔mass conversion
        """
        if recipe_unit is None:
            recipe_unit = self.unit
        
        base_cost = self.cost_per_base_unit()
        
        try:
            # Get cost per recipe unit by converting base cost to recipe unit
            # cost_per_base_unit is $/g or $/ml
            # We need $/recipe_unit
            if is_compatible(self.package_unit, recipe_unit):
                # Same type conversion - direct
                base_qty = to_base(self.package_quantity, self.package_unit)
                recipe_qty = to_base(1.0, recipe_unit)
                return self.package_price / (base_qty / recipe_qty)
            else:
                # Cross-type conversion needs density
                if density is not None:
                    # Convert 1 recipe_unit to base mass (g), then to base cost
                    mass_g = to_grams(1.0, recipe_unit, density=density)
                    return base_cost * mass_g
                else:
                    # No density available - cannot convert across types
                    # Return base cost as fallback with warning
                    return base_cost
        except UnitConversionError:
            # Unrecognized unit - return base cost
            return base_cost


class Recipe(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    servings = db.Column(db.Integer, default=1)
    instructions = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship to recipe ingredients
    recipe_ingredients = db.relationship('RecipeIngredient', backref='recipe', cascade='all, delete-orphan', lazy=True)

    def __repr__(self):
        return f'<Recipe {self.name}>'

    def total_cost(self):
        return sum(ri.cost() for ri in self.recipe_ingredients)

    def cost_per_serving(self):
        total = self.total_cost()
        return total / self.servings if self.servings > 0 else 0


class RecipeIngredient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredient.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)  # e.g., 200 (for 200g)
    unit = db.Column(db.String(20), nullable=False)  # unit used in recipe

    ingredient = db.relationship('Ingredient')

    def cost(self):
        """Calculate cost: quantity * cost per recipe unit"""
        cost_per_unit = self.ingredient.cost_per_recipe_unit(self.unit)
        return self.quantity * cost_per_unit


class MealPlan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.String(20), nullable=False)  # 'Monday', 'Tuesday', etc.
    meal_type = db.Column(db.String(20), nullable=False)  # 'breakfast', 'lunch', 'dinner', 'snack'
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)
    servings = db.Column(db.Integer, default=1)
    week_start = db.Column(db.Date, nullable=False)  # Monday of the week

    recipe = db.relationship('Recipe')

    def __repr__(self):
        return f'<MealPlan {self.day} {self.meal_type}: {self.recipe.name}>'


def get_week_start(date=None):
    """Get Monday of the week for a given date (default today)"""
    if date is None:
        date = datetime.utcnow().date()
    if isinstance(date, datetime):
        date = date.date()
    return date - timedelta(days=date.weekday())


def parse_week_start(week_str):
    """Parse week string (YYYY-MM-DD) to date object"""
    try:
        return datetime.strptime(week_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return get_week_start()


@app.route('/')
def index():
    week_str = request.args.get('week')
    week_start = parse_week_start(week_str)
    meal_plans = MealPlan.query.filter_by(week_start=week_start).order_by(
        db.case(
            (MealPlan.meal_type == 'breakfast', 1),
            (MealPlan.meal_type == 'lunch', 2),
            (MealPlan.meal_type == 'dinner', 3),
            (MealPlan.meal_type == 'snack', 4),
            else_=5
        ),
        MealPlan.day
    ).all()

    # Group by day and meal_type for template
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    meal_types = ['breakfast', 'lunch', 'dinner', 'snack']
    schedule = {day: {mt: None for mt in meal_types} for day in days}

    total_meals = 0
    total_cost = 0.0

    for mp in meal_plans:
        schedule[mp.day][mp.meal_type] = mp
        total_meals += 1
        if mp.recipe:
            total_cost += mp.recipe.cost_per_serving() * mp.servings

    # Get all available weeks for dropdown
    all_weeks = db.session.query(MealPlan.week_start).distinct().order_by(MealPlan.week_start.desc()).all()
    all_weeks = [w[0] for w in all_weeks]
    if week_start not in all_weeks:
        all_weeks.append(week_start)
    all_weeks.sort(reverse=True)

    # Prev/next week
    prev_week = week_start - timedelta(days=7)
    next_week = week_start + timedelta(days=7)
    is_current_week = (week_start == get_week_start())

    recipes = Recipe.query.all()
    return render_template('index.html', schedule=schedule, recipes=recipes, 
                           week_start=week_start, total_meals=total_meals, total_cost=total_cost,
                           all_weeks=all_weeks, prev_week=prev_week, next_week=next_week,
                           is_current_week=is_current_week)


@app.route('/month')
def month_view():
    """Month view showing 6 weeks (fixed grid)"""
    from datetime import date
    import calendar
    
    # Parse month from query params (YYYY-MM)
    month_str = request.args.get('month')
    if month_str:
        try:
            year, month = map(int, month_str.split('-'))
            first_day = date(year, month, 1)
        except (ValueError, TypeError):
            first_day = date.today().replace(day=1)
    else:
        first_day = date.today().replace(day=1)
    
    # Get the Monday of the week containing the 1st of the month
    month_start = first_day - timedelta(days=first_day.weekday())
    
    # Generate 6 weeks (42 days) of data
    weeks = []
    current_week_start = month_start
    today = date.today()
    for week_idx in range(6):
        week_end = current_week_start + timedelta(days=6)
        meal_plans = MealPlan.query.filter_by(week_start=current_week_start).all()
        
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        meal_types = ['breakfast', 'lunch', 'dinner', 'snack']
        schedule = {day: {mt: None for mt in meal_types} for day in days}
        
        for mp in meal_plans:
            schedule[mp.day][mp.meal_type] = mp
        
        # Pre-compute day dates for this week
        day_dates = []
        for day_idx in range(7):
            day_date = current_week_start + timedelta(days=day_idx)
            day_dates.append(day_date)
        
        weeks.append({
            'week_start': current_week_start,
            'week_end': week_end,
            'schedule': schedule,
            'day_dates': day_dates,
            'is_current_month': current_week_start.month == first_day.month,
            'is_current_week': current_week_start == get_week_start(),
        })
        
        current_week_start += timedelta(days=7)
    
    # Calculate month totals
    total_meals = 0
    total_cost = 0.0
    for w in weeks:
        for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']:
            for meal_type in ['breakfast', 'lunch', 'dinner', 'snack']:
                mp = w['schedule'][day][meal_type]
                if mp:
                    total_meals += 1
                    if mp.recipe:
                        total_cost += mp.recipe.cost_per_serving() * mp.servings
    
    # Prev/next month
    if first_day.month == 1:
        prev_month = first_day.replace(year=first_day.year - 1, month=12)
        next_month = first_day.replace(month=2)
    elif first_day.month == 12:
        prev_month = first_day.replace(month=11)
        next_month = first_day.replace(year=first_day.year + 1, month=1)
    else:
        prev_month = first_day.replace(month=first_day.month - 1)
        next_month = first_day.replace(month=first_day.month + 1)
    
    recipes = Recipe.query.all()
    return render_template('month.html', weeks=weeks, 
                           current_month=first_day, prev_month=prev_month, next_month=next_month,
                           recipes=recipes, total_meals=total_meals, total_cost=total_cost,
                           today=today)


@app.route('/recipes')
def recipes():
    recipes = Recipe.query.all()
    return render_template('recipes.html', recipes=recipes)


@app.route('/recipes/new', methods=['GET', 'POST'])
def new_recipe():
    ingredients = Ingredient.query.all()
    if request.method == 'POST':
        name = request.form['name']
        servings = int(request.form['servings'])
        instructions = request.form.get('instructions', '')

        recipe = Recipe(name=name, servings=servings, instructions=instructions)
        db.session.add(recipe)
        db.session.flush()  # Get recipe.id

        # Handle recipe ingredients
        ingredient_ids = request.form.getlist('ingredient_id[]')
        quantities = request.form.getlist('quantity[]')
        units = request.form.getlist('unit[]')

        for ing_id, qty, unit in zip(ingredient_ids, quantities, units):
            if ing_id and qty:
                ri = RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=int(ing_id),
                    quantity=float(qty),
                    unit=unit
                )
                db.session.add(ri)

        db.session.commit()
        flash('Recipe created!')
        return redirect(url_for('recipes'))

    return render_template('recipe_form.html', recipe=None, ingredients=ingredients)


@app.route('/recipes/<int:id>/edit', methods=['GET', 'POST'])
def edit_recipe(id):
    recipe = Recipe.query.get_or_404(id)
    ingredients = Ingredient.query.all()

    if request.method == 'POST':
        recipe.name = request.form['name']
        recipe.servings = int(request.form['servings'])
        recipe.instructions = request.form.get('instructions', '')

        # Delete old recipe ingredients
        RecipeIngredient.query.filter_by(recipe_id=recipe.id).delete()

        # Add new ones
        ingredient_ids = request.form.getlist('ingredient_id[]')
        quantities = request.form.getlist('quantity[]')
        units = request.form.getlist('unit[]')

        for ing_id, qty, unit in zip(ingredient_ids, quantities, units):
            if ing_id and qty:
                ri = RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=int(ing_id),
                    quantity=float(qty),
                    unit=unit
                )
                db.session.add(ri)

        db.session.commit()
        flash('Recipe updated!')
        return redirect(url_for('recipes'))

    return render_template('recipe_form.html', recipe=recipe, ingredients=ingredients)


@app.route('/recipes/<int:id>/delete', methods=['POST'])
def delete_recipe(id):
    recipe = Recipe.query.get_or_404(id)
    # Delete associated meal plans first
    MealPlan.query.filter_by(recipe_id=recipe.id).delete()
    db.session.delete(recipe)
    db.session.commit()
    flash('Recipe deleted!')
    return redirect(url_for('recipes'))


@app.route('/ingredients')
def ingredients():
    ingredients = Ingredient.query.order_by(Ingredient.category, Ingredient.name).all()
    
    # Group by category
    categories = ['Dairy', 'Meat', 'Produce', 'Dry Goods', 'Canned Goods', 'Other']
    grouped = {cat: [] for cat in categories}
    for ing in ingredients:
        if ing.category in grouped:
            grouped[ing.category].append(ing)
        else:
            grouped['Other'].append(ing)
    
    has_ingredients = len(ingredients) > 0
    
    return render_template('ingredients.html', grouped=grouped, categories=categories, has_ingredients=has_ingredients)


@app.route('/ingredients/new', methods=['GET', 'POST'])
def new_ingredient():
    if request.method == 'POST':
        name = request.form['name']
        category = request.form.get('category', 'Other')
        unit = request.form['unit']
        package_price = float(request.form['package_price'])
        package_quantity = float(request.form['package_quantity'])
        package_unit = request.form.get('package_unit', 'g')
        quantity_on_hand = float(request.form.get('quantity_on_hand', 0.0))

        ingredient = Ingredient(
            name=name, 
            category=category, 
            unit=unit, 
            package_price=package_price, 
            package_quantity=package_quantity, 
            package_unit=package_unit, 
            quantity_on_hand=quantity_on_hand
        )
        db.session.add(ingredient)
        db.session.commit()
        flash('Ingredient added!')
        return redirect(url_for('ingredients'))

    return render_template('ingredient_form.html', ingredient=None)


@app.route('/ingredients/<int:id>/edit', methods=['GET', 'POST'])
def edit_ingredient(id):
    ingredient = Ingredient.query.get_or_404(id)

    if request.method == 'POST':
        ingredient.name = request.form['name']
        ingredient.category = request.form.get('category', 'Other')
        ingredient.unit = request.form['unit']
        ingredient.package_price = float(request.form['package_price'])
        ingredient.package_quantity = float(request.form['package_quantity'])
        ingredient.package_unit = request.form.get('package_unit', 'g')
        ingredient.quantity_on_hand = float(request.form.get('quantity_on_hand', 0.0))
        db.session.commit()
        flash('Ingredient updated!')
        return redirect(url_for('ingredients'))

    return render_template('ingredient_form.html', ingredient=ingredient)


@app.route('/ingredients/<int:id>/delete', methods=['POST'])
def delete_ingredient(id):
    ingredient = Ingredient.query.get_or_404(id)
    db.session.delete(ingredient)
    db.session.commit()
    flash('Ingredient deleted!')
    return redirect(url_for('ingredients'))


@app.route('/meal-plan', methods=['GET', 'POST'])
def meal_plan():
    # For month view, week_start comes from form data; for week view, from query param
    if request.method == 'POST':
        week_str = request.form.get('week_start') or request.args.get('week')
    else:
        week_str = request.args.get('week')
    week_start = parse_week_start(week_str)

    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        # Handle delete meal action
        if request.form.get('action') == 'delete_meal':
            day = request.form['day']
            meal_type = request.form['meal_type']
            mp = MealPlan.query.filter_by(
                week_start=week_start, day=day, meal_type=meal_type
            ).first()
            if mp:
                db.session.delete(mp)
                db.session.commit()
                if is_ajax:
                    return jsonify({'success': True})
                flash('Meal removed!')
            return redirect(url_for('meal_plan', week=week_start.strftime('%Y-%m-%d')))

        # Handle update servings action
        if request.form.get('action') == 'update_servings':
            meal_id = request.form.get('meal_id')
            servings = int(request.form.get('servings', 1))
            mp = MealPlan.query.get(meal_id)
            if mp:
                mp.servings = servings
                db.session.commit()
                if is_ajax:
                    return jsonify({'success': True, 'servings': servings})
                flash('Servings updated!')
            return redirect(url_for('meal_plan', week=week_start.strftime('%Y-%m-%d')))

        # Handle add meal action (from month view inline form)
        if request.form.get('action') == 'add_meal':
            days_selected = request.form.getlist('days')
            if not days_selected:
                # Single day from form
                days_selected = [request.form['day']]
            
            meal_type = request.form['meal_type']
            recipe_id = int(request.form['recipe_id'])
            servings = int(request.form.get('servings', 1))
            
            count = 0
            for day in days_selected:
                existing = MealPlan.query.filter_by(
                    week_start=week_start, day=day, meal_type=meal_type
                ).first()
                if existing:
                    existing.recipe_id = recipe_id
                    existing.servings = servings
                else:
                    mp = MealPlan(
                        week_start=week_start,
                        day=day,
                        meal_type=meal_type,
                        recipe_id=recipe_id,
                        servings=servings
                    )
                    db.session.add(mp)
                count += 1
            
            db.session.commit()
            if is_ajax:
                return jsonify({'success': True, 'count': count})
            flash(f'Meal plan updated for {count} day(s)!')
            return redirect(url_for('meal_plan', week=week_start.strftime('%Y-%m-%d')))

        # Handle copy week action
        if request.form.get('action') == 'copy_week':
            source_week_str = request.form.get('source_week')
            if source_week_str:
                source_week = parse_week_start(source_week_str)
                if source_week != week_start:
                    # Copy meal plans from source week to target week
                    source_plans = MealPlan.query.filter_by(week_start=source_week).all()
                    for sp in source_plans:
                        # Check if target already exists
                        existing = MealPlan.query.filter_by(
                            week_start=week_start, day=sp.day, meal_type=sp.meal_type
                        ).first()
                        if not existing:
                            mp = MealPlan(
                                week_start=week_start,
                                day=sp.day,
                                meal_type=sp.meal_type,
                                recipe_id=sp.recipe_id,
                                servings=sp.servings
                            )
                            db.session.add(mp)
                    db.session.commit()
                    flash(f'Copied meal plan from week of {source_week.strftime("%b %d")}!')
                else:
                    flash('Cannot copy to the same week.')
            return redirect(url_for('meal_plan', week=week_start.strftime('%Y-%m-%d')))

        # Handle multiple days from checkboxes
        days_selected = request.form.getlist('days')
        if not days_selected:
            flash('Please select at least one day!')
            return redirect(url_for('meal_plan', week=week_start.strftime('%Y-%m-%d')))

        meal_type = request.form['meal_type']
        recipe_id = int(request.form['recipe_id'])
        servings = int(request.form.get('servings', 1))

        count = 0
        for day in days_selected:
            # Check if entry exists
            existing = MealPlan.query.filter_by(
                week_start=week_start, day=day, meal_type=meal_type
            ).first()

            if existing:
                existing.recipe_id = recipe_id
                existing.servings = servings
            else:
                mp = MealPlan(
                    week_start=week_start,
                    day=day,
                    meal_type=meal_type,
                    recipe_id=recipe_id,
                    servings=servings
                )
                db.session.add(mp)
            count += 1

        db.session.commit()
        flash(f'Meal plan updated for {count} day(s)!')
        return redirect(url_for('meal_plan', week=week_start.strftime('%Y-%m-%d')))

    recipes = Recipe.query.all()
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    meal_types = ['breakfast', 'lunch', 'dinner', 'snack']

    meal_plans = MealPlan.query.filter_by(week_start=week_start).all()
    schedule = {day: {mt: None for mt in meal_types} for day in days}
    
    total_meals = 0
    total_cost = 0.0
    
    for mp in meal_plans:
        schedule[mp.day][mp.meal_type] = mp
        total_meals += 1
        if mp.recipe:
            total_cost += mp.recipe.cost_per_serving() * mp.servings

    # Get all available weeks for dropdown
    all_weeks = db.session.query(MealPlan.week_start).distinct().order_by(MealPlan.week_start.desc()).all()
    all_weeks = [w[0] for w in all_weeks]
    if week_start not in all_weeks:
        all_weeks.append(week_start)
    all_weeks.sort(reverse=True)

    # Prev/next week
    prev_week = week_start - timedelta(days=7)
    next_week = week_start + timedelta(days=7)
    is_current_week = (week_start == get_week_start())

    return render_template('meal_plan.html', recipes=recipes, schedule=schedule,
                           days=days, meal_types=meal_types, week_start=week_start,
                           total_meals=total_meals, total_cost=total_cost,
                           all_weeks=all_weeks, prev_week=prev_week, next_week=next_week,
                           is_current_week=is_current_week)


@app.route('/shopping-list')
def shopping_list():
    week_str = request.args.get('week')
    week_start = parse_week_start(week_str)
    meal_plans = MealPlan.query.filter_by(week_start=week_start).all()

    # Aggregate ingredients needed
    shopping_dict = {}  # (ingredient_id, unit) -> total_quantity

    for mp in meal_plans:
        recipe = mp.recipe
        if not recipe:
            continue
        for ri in recipe.recipe_ingredients:
            key = (ri.ingredient_id, ri.unit)
            qty = ri.quantity * mp.servings / recipe.servings
            if key in shopping_dict:
                shopping_dict[key] += qty
            else:
                shopping_dict[key] = qty

    # Convert to list with ingredient info, subtract inventory
    shopping_items = []
    for (ing_id, unit), total_needed in shopping_dict.items():
        ingredient = Ingredient.query.get(ing_id)
        if ingredient:
            on_hand = ingredient.quantity_on_hand or 0.0
            to_buy = max(0.0, total_needed - on_hand)
            
            # Create a temporary RecipeIngredient to use the cost() method
            temp_ri = RecipeIngredient(ingredient_id=ing_id, quantity=to_buy, unit=unit)
            temp_ri.ingredient = ingredient
            estimated_cost = temp_ri.cost()
            
            shopping_items.append({
                'ingredient': ingredient,
                'total_needed': round(total_needed, 2),
                'on_hand': round(on_hand, 2),
                'to_buy': round(to_buy, 2),
                'unit': unit,
                'estimated_cost': round(estimated_cost, 2)
            })

    total_cost = sum(item['estimated_cost'] for item in shopping_items)

    # Prev/next week
    prev_week = week_start - timedelta(days=7)
    next_week = week_start + timedelta(days=7)
    is_current_week = (week_start == get_week_start())

    return render_template('shopping_list.html', items=shopping_items, total_cost=total_cost, week_start=week_start,
                           prev_week=prev_week, next_week=next_week, is_current_week=is_current_week)


@app.route('/api/ingredients')
def api_ingredients():
    ingredients = Ingredient.query.all()
    return jsonify([{'id': i.id, 'name': i.name, 'category': i.category, 'unit': i.unit, 
                     'package_price': i.package_price, 'package_quantity': i.package_quantity, 
                     'package_unit': i.package_unit, 'quantity_on_hand': i.quantity_on_hand,
                     'cost_per_base_unit': i.cost_per_base_unit()} for i in ingredients])


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Initialize food data providers after tables are created
        from food_data import init_providers
        init_providers(
            usda_api_key=app.config.get('USDA_FDC_API_KEY'),
            off_user_agent=app.config.get('OFF_USER_AGENT'),
            cnf_csv_path=app.config.get('CNF_CSV_PATH'),
        )
    app.run(debug=True)