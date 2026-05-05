"""
Экстрактор данных рецептов для сайта 160cal.com
"""

import logging
import sys
from pathlib import Path
import json
import re
from typing import Optional, List

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class Cal160ComExtractor(BaseRecipeExtractor):
    """Экстрактор для 160cal.com"""

    # Known Hebrew measurement units, sorted by length (longest first) to prefer longer matches
    HEBREW_MEASUREMENT_UNITS: List[str] = sorted([
        'כוסות', 'כוס',
        'כפיות', 'כפית',
        'כפות', 'כף',
        'קופסאות', 'קופסא', 'קופסה',
        'שקיות', 'שקית',
        'חבילות', 'חבילה',
        'מ״ל', 'מ"ל',
        'גרם', 'גר',
        'ק״ג', 'קג',
    ], key=len, reverse=True)

    @staticmethod
    def _find_recipe_in_data(data) -> Optional[dict]:
        """Recursively find a JSON-LD @type=Recipe object."""
        if isinstance(data, dict):
            if data.get('@type') == 'Recipe':
                return data
            for v in data.values():
                if isinstance(v, (dict, list)):
                    result = Cal160ComExtractor._find_recipe_in_data(v)
                    if result:
                        return result
        elif isinstance(data, list):
            for item in data:
                result = Cal160ComExtractor._find_recipe_in_data(item)
                if result:
                    return result
        return None

    def _get_recipe_json_ld(self) -> dict:
        """Return the Recipe JSON-LD object, or empty dict if not found."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                recipe = self._find_recipe_in_data(data)
                if recipe:
                    return recipe
            except (json.JSONDecodeError, TypeError):
                logger.debug("Failed to parse JSON-LD script block")
        return {}

    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Convert ISO 8601 duration string to human-readable minutes string.

        Args:
            duration: string like "PT20M" or "PT1H30M"

        Returns:
            String like "20 minutes" or None
        """
        if not duration or not duration.startswith('PT'):
            return None

        body = duration[2:]  # strip leading "PT"

        hours = 0
        minutes = 0

        hour_match = re.search(r'(\d+)H', body)
        if hour_match:
            hours = int(hour_match.group(1))

        min_match = re.search(r'(\d+)M', body)
        if min_match:
            minutes = int(min_match.group(1))

        total = hours * 60 + minutes
        return f"{total} minutes" if total > 0 else None

    def parse_ingredient_text(self, text: str) -> dict:
        """
        Parse a Hebrew ingredient line into {name, amount, unit}.

        Typical formats:
          "2 כוסות אורז עגול"        → amount=2, unit=כוסות, name=אורז עגול
          "1/2 כפית מלח (לא חובה)"   → amount=1/2, unit=כפית, name=מלח
          "מעט צ׳ילי חריף (לא חובה)" → amount=מעט, unit=None, name=צ׳ילי חריף
          "גרידת לימון/תפוז"          → amount=None, unit=None, name=גרידת לימון/תפוז
        """
        text = self.clean_text(text)
        if not text:
            return {"name": None, "amount": None, "unit": None}

        amount: Optional[str] = None
        unit: Optional[str] = None
        rest = text

        # ------------------------------------------------------------------
        # Step 1: Extract leading amount token
        #   Handles: plain number, fraction (1/2), range (1-2), "מעט"/"כמה"
        # ------------------------------------------------------------------
        amount_re = re.compile(
            r'^(מעט|כמה|הרבה|(?:\d+\s+)?(?:\d+/\d+|\d+(?:\s*[-–]\s*\d+(?:/\d+)?)?))'
            r'(?=\s|$)',
            re.UNICODE,
        )
        m = amount_re.match(text)
        if m:
            amount = m.group(1).strip()
            rest = text[m.end():].strip()

        # ------------------------------------------------------------------
        # Step 2: If we found an amount, check if the next word is a known unit
        # ------------------------------------------------------------------
        if amount and rest:
            for u in self.HEBREW_MEASUREMENT_UNITS:
                if rest.startswith(u) and (
                    len(rest) == len(u) or rest[len(u)] in (' ', '\t', '(')
                ):
                    remaining = rest[len(u):].strip()
                    # Optionally absorb a parenthetical annotation directly after unit
                    # e.g., "כוס (200 גרם)" → unit = "כוס (200 גרם)"
                    paren_m = re.match(r'^(\([^)]+\))', remaining)
                    if paren_m:
                        unit = u + ' ' + paren_m.group(1)
                        remaining = remaining[paren_m.end():].strip()
                    else:
                        unit = u
                    rest = remaining
                    break

        # ------------------------------------------------------------------
        # Step 3: Whatever is left becomes the ingredient name.
        #   Strip trailing parenthetical qualifiers like "(לא חובה)", "(אופציונלי)".
        # ------------------------------------------------------------------
        name = rest.strip() if rest else text
        if name:
            # Remove trailing parenthetical content (qualifiers / weight hints)
            name = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()

        return {
            "name": name if name else text,
            "amount": amount,
            "unit": unit,
        }

    # ------------------------------------------------------------------
    # Individual field extractors
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Extract dish name from H1 or JSON-LD, stripping subtitles."""
        # 1. H1 with Elementor heading class
        h1 = self.soup.find('h1', class_='elementor-heading-title')
        if not h1:
            h1 = self.soup.find('h1')

        title = None
        if h1:
            title = self.clean_text(h1.get_text())

        # 2. Fallback: JSON-LD name
        if not title:
            recipe_data = self._get_recipe_json_ld()
            title = recipe_data.get('name')
            if title:
                title = self.clean_text(title)

        # 3. Fallback: og:title
        if not title:
            og_title = self.soup.find('meta', property='og:title')
            if og_title and og_title.get('content'):
                title = self.clean_text(og_title['content'])
                # Strip site name suffix
                title = re.sub(r'\s*[-–]\s*מטבח קל.*$', '', title).strip()

        if not title:
            return None

        # Strip common subtitle patterns:
        #   "אורז לסושי – מתכון קל ובדוק שתמיד מצליח!" → "אורז לסושי"
        #   "סושי – המתכון הכי קל, מהיר ופשוט לארוחה מושלמת!" → "סושי"
        title = re.sub(r'\s*[–—]\s*(ה?מתכון|המתכון).+$', '', title).strip()
        # Strip trailing "!" or "."
        title = title.rstrip('!.').strip()

        return title if title else None

    def extract_description(self) -> Optional[str]:
        """Extract description from meta description tag."""
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Extract ingredients from jet-listing-dynamic-field__content divs.
        Each div with a UL inside contains one ingredient group.
        """
        ingredients = []

        jet_fields = self.soup.find_all(class_='jet-listing-dynamic-field__content')
        for field in jet_fields:
            ul = field.find('ul')
            if not ul:
                continue
            for li in ul.find_all('li'):
                raw = self.clean_text(li.get_text(strip=True))
                if raw:
                    parsed = self.parse_ingredient_text(raw)
                    ingredients.append(parsed)

        if not ingredients:
            logger.warning("No ingredients found in %s", self.html_path)
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def extract_instructions(self) -> Optional[str]:
        """
        Extract cooking instructions from the element with id="ofen".
        Steps are joined with a single space.
        """
        ofen = self.soup.find(id='ofen')
        if not ofen:
            # Fallback: find any text-editor widget that contains an OL
            for editor in self.soup.find_all(
                attrs={'data-widget_type': 'text-editor.default'}
            ):
                if editor.find('ol'):
                    ofen = editor
                    break

        if not ofen:
            logger.warning("No instructions element found in %s", self.html_path)
            return None

        steps = []
        ol = ofen.find('ol')
        if ol:
            for li in ol.find_all('li'):
                text = self.clean_text(li.get_text(strip=True))
                if text:
                    steps.append(text)
        else:
            for p in ofen.find_all('p'):
                text = self.clean_text(p.get_text(strip=True))
                if text:
                    steps.append(text)

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Extract and map recipeCategory from JSON-LD."""
        recipe_data = self._get_recipe_json_ld()
        category = recipe_data.get('recipeCategory')
        if not category:
            return None

        CATEGORY_MAP = {
            'main': 'Main Course',
            'mains': 'Main Course',
            'dessert': 'Dessert',
            'desserts': 'Dessert',
            'salad': 'Salad',
            'salads': 'Salad',
            'side': 'Side Dish',
            'sides': 'Side Dish',
            'breakfast': 'Breakfast',
            'soup': 'Soup',
            'soups': 'Soup',
            'appetizer': 'Appetizer',
            'appetizers': 'Appetizer',
            'snack': 'Snack',
            'snacks': 'Snack',
        }

        return CATEGORY_MAP.get(category.lower(), category)

    def extract_time(self, time_key: str) -> Optional[str]:
        """
        Extract a time field from JSON-LD and convert to "X minutes" string.

        Args:
            time_key: one of 'prepTime', 'cookTime', 'totalTime'
        """
        recipe_data = self._get_recipe_json_ld()
        iso_time = recipe_data.get(time_key)
        if not iso_time:
            return None
        return self.parse_iso_duration(iso_time)

    def extract_notes(self) -> Optional[str]:
        """
        Extract notes/tips from the last text-editor widget that appears
        after the instructions (id='ofen') and is not a social CTA.
        """
        SOCIAL_CTA_MARKERS = ['הכנתם', 'אינסטגרם', 'טיק טוק', 'פייסבוק', 'הרשמו לקבלת']

        editors = self.soup.find_all(attrs={'data-widget_type': 'text-editor.default'})

        ofen_found = False
        for editor in editors:
            ed_id = editor.get('id', '')

            if ed_id == 'ofen':
                ofen_found = True
                continue

            if not ofen_found:
                continue

            text = self.clean_text(editor.get_text(strip=True))
            if not text:
                continue

            # Skip social media CTA blocks
            if any(marker in text for marker in SOCIAL_CTA_MARKERS):
                continue

            return text

        logger.debug("No notes found in %s", self.html_path)
        return None

    def extract_tags(self) -> Optional[str]:
        """Extract tags from JSON-LD keywords field (pipe-separated)."""
        recipe_data = self._get_recipe_json_ld()
        keywords = recipe_data.get('keywords', '')
        if not keywords:
            return None

        tags = [t.strip() for t in keywords.split('|') if t.strip()]
        return ', '.join(tags) if tags else None

    def extract_image_urls(self) -> Optional[str]:
        """
        Extract recipe image URLs from og:image meta tag and JSON-LD.
        Returns a comma-separated string of unique URLs.
        """
        urls: List[str] = []

        # og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # JSON-LD image
        recipe_data = self._get_recipe_json_ld()
        img = recipe_data.get('image')
        if isinstance(img, str):
            if img not in urls:
                urls.append(img)
        elif isinstance(img, dict):
            url = img.get('url') or img.get('contentUrl')
            if url and url not in urls:
                urls.append(url)
        elif isinstance(img, list):
            for item in img:
                if isinstance(item, str) and item not in urls:
                    urls.append(item)
                elif isinstance(item, dict):
                    url = item.get('url') or item.get('contentUrl')
                    if url and url not in urls:
                        urls.append(url)

        return ','.join(urls) if urls else None

    # ------------------------------------------------------------------
    # Main extraction entry point
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """
        Extract all recipe fields and return as a JSON-compatible dict.

        Returns:
            dict with keys: dish_name, description, ingredients, instructions,
            category, prep_time, cook_time, total_time, notes, image_urls, tags.
            Missing fields are set to None.
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()

        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": self.extract_time('prepTime'),
            "cook_time": self.extract_time('cookTime'),
            "total_time": self.extract_time('totalTime'),
            "notes": notes,
            "image_urls": self.extract_image_urls(),
            "tags": tags,
        }


def main() -> None:
    """
    Process all HTML files in the preprocessed/160cal_com directory.
    Extracts recipe data and saves JSON files next to each HTML file.
    """
    import os

    repo_root = Path(__file__).parent.parent
    recipes_dir = repo_root / 'preprocessed' / '160cal_com'

    if recipes_dir.exists() and recipes_dir.is_dir():
        process_directory(Cal160ComExtractor, str(recipes_dir))
    else:
        print(f"Directory not found: {recipes_dir}")
        print("Usage: python extractor/160cal_com.py")


if __name__ == '__main__':
    main()
