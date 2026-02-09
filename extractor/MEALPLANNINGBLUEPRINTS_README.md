# Meal Planning Blueprints Parser

## Overview
This parser extracts recipe data from mealplanningblueprints.com HTML pages.

## File
`extractor/mealplanningblueprints_com.py`

## Class
`MealPlanningBlueprintsExtractor` - inherits from `BaseRecipeExtractor`

## Features

### Extraction Strategy
1. **Primary**: JSON-LD structured data (most reliable)
2. **Fallback**: HTML parsing with BeautifulSoup

### Supported Fields
All fields are guaranteed to be present in the output. Missing values are set to `None`.

- `dish_name` (str): Recipe title
- `description` (str): Recipe description/summary
- `ingredients` (str): JSON-encoded list of dicts with `name`, `amount`, `unit`
- `instructions` (str): Step-by-step cooking instructions
- `category` (str): Recipe category (e.g., "Dinner", "Dessert")
- `prep_time` (str): Preparation time in readable format
- `cook_time` (str): Cooking time in readable format
- `total_time` (str): Total time in readable format
- `notes` (str): Additional notes or tips
- `image_urls` (str): Comma-separated image URLs (no spaces)
- `tags` (str): Comma-separated tags

### Ingredient Parsing
The parser intelligently extracts ingredients into structured format:

```json
{
  "name": "olive oil",
  "amount": "2",
  "unit": "tablespoons"
}
```

Features:
- Handles fractions (1/2, 1 1/2)
- Handles Unicode fractions (½, ¼, ¾)
- Extracts quantities, units, and ingredient names
- Cleans up common phrases ("to taste", "optional", etc.)

### Time Parsing
Converts ISO 8601 duration format to readable format:
- `PT15M` → "15 minutes"
- `PT1H` → "1 hour"
- `PT1H30M` → "1 hour 30 minutes"

## Usage

### As Module
```python
from extractor.mealplanningblueprints_com import MealPlanningBlueprintsExtractor

extractor = MealPlanningBlueprintsExtractor('path/to/recipe.html')
data = extractor.extract_all()
```

### As Script
```bash
python extractor/mealplanningblueprints_com.py
```

This will process all HTML files in `preprocessed/mealplanningblueprints_com/`

## Testing

Run unit tests:
```bash
python -m unittest tests.extractor.test_mealplanningblueprints_com -v
```

Test files are located in `preprocessed/mealplanningblueprints_com/`:
- `sample-recipe_1.html` - Full recipe with all fields
- `chocolate-cookies_1.html` - Dessert recipe example
- `minimal-recipe_1.html` - Minimal HTML (tests None handling)

## Implementation Details

### JSON-LD Extraction
The parser first looks for `<script type="application/ld+json">` tags containing Recipe schema.org data. This is the most reliable source.

### HTML Fallback
If JSON-LD is not available, the parser falls back to:
- Meta tags (`og:title`, `og:description`, etc.)
- HTML structure (h1, lists, paragraphs)
- CSS classes (ingredient lists, instruction lists, etc.)

### Error Handling
- Missing fields return `None` instead of raising exceptions
- Invalid ingredient formats are handled gracefully
- HTML entity decoding is automatic
- Unicode character normalization

## Code Quality
- ✅ All tests passing (16 tests)
- ✅ Code review completed
- ✅ Security scan (CodeQL) passed
- ✅ Type hints and documentation
- ✅ Follows project conventions

## Compatibility
Compatible with existing parsers in the project (allrecipes, simplyrecipes, etc.)
