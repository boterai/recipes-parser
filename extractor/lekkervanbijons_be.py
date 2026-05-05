"""
Экстрактор данных рецептов для сайта lekkervanbijons.be
"""

import logging
import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Known Dutch measurement units (single and plural forms)
_DUTCH_UNITS = {
    # Volume
    'ml', 'l', 'dl', 'cl',
    # Mass
    'g', 'gr', 'kg',
    # Tablespoon / teaspoon
    'el', 'tl', 'eetlepel', 'eetlepels', 'theelepel', 'theelepels',
    # Other common units
    'bollen', 'bol',
    'stuks', 'stuk',
    'kopje', 'kopjes', 'kop', 'koppen',
    'zakje', 'zakjes',
    'snufje', 'snuf',
    'scheutje',
    'plak', 'plakje', 'plakken', 'plakjes',
    'takje', 'takjes',
    'blaadje', 'blaadjes',
    'teen', 'teentje', 'teentjes',
    'bosje',
    'pak', 'pakje', 'pakjes',
    'blik', 'blikje',
    'fles', 'flesje',
    'pot', 'potje',
    'cm',
}


class LekkervanbijonsBeExtractor(BaseRecipeExtractor):
    """Экстрактор для lekkervanbijons.be"""

    def __init__(self, html_path: str):
        super().__init__(html_path)
        self._json_ld_recipe: Optional[dict] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Return the Recipe node from JSON-LD @graph (cached)."""
        if self._json_ld_recipe is not None:
            return self._json_ld_recipe

        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
            except json.JSONDecodeError:
                continue

            # @graph structure (main pattern for this site)
            if isinstance(data, dict) and '@graph' in data:
                for item in data['@graph']:
                    if isinstance(item, dict) and item.get('@type') == 'Recipe':
                        self._json_ld_recipe = item
                        return item

            # Flat list
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get('@type') == 'Recipe':
                        self._json_ld_recipe = item
                        return item

            # Single object
            if isinstance(data, dict) and data.get('@type') == 'Recipe':
                self._json_ld_recipe = data
                return data

        self._json_ld_recipe = {}
        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Convert ISO 8601 duration string to a human-readable "X min" string.

        Args:
            duration: e.g. "PT15M", "PT1H30M", "PT0M"

        Returns:
            "X min" or None if duration is zero or invalid.
        """
        if not duration:
            return None

        # Strip leading P and optional T separator
        text = duration.upper()
        if not text.startswith('P'):
            return None
        text = text[1:]  # remove 'P'

        # Split on 'T' to separate date and time portions
        if 'T' in text:
            _, time_part = text.split('T', 1)
        else:
            time_part = text

        hours = 0
        minutes = 0

        h_match = re.search(r'(\d+)H', time_part)
        m_match = re.search(r'(\d+)M', time_part)

        if h_match:
            hours = int(h_match.group(1))
        if m_match:
            minutes = int(m_match.group(1))

        total_minutes = hours * 60 + minutes
        if total_minutes <= 0:
            return None

        return f"{total_minutes} min"

    @staticmethod
    def _parse_ingredient_string(text: str) -> dict:
        """
        Parse a Dutch ingredient string like "400 g frambozen" into a dict.

        Handles:
          - "{amount} {unit} {name}"   e.g. "400 g frambozen"
          - "{amount} {name}"          e.g. "1 cake" → unit inferred as "stuk"/"stuks"
          - "{name}"                   e.g. "opgeklopte slagroom" → amount/unit None

        Returns dict with keys: name, amount, unit.
        """
        text = text.strip()
        if not text:
            return {"name": text, "amount": None, "unit": None}

        # Pattern: optional leading number (int/float/fraction), then optional unit, then name
        # We allow commas as decimal separator (Dutch: "0,5")
        number_pat = r'(?:\d+(?:[.,]\d+)?(?:\s*[/]\s*\d+)?)'
        unit_pat = '|'.join(re.escape(u) for u in sorted(_DUTCH_UNITS, key=len, reverse=True))

        full_pattern = re.compile(
            r'^(?P<amount>' + number_pat + r')\s+'
            r'(?:(?P<unit>' + unit_pat + r')\s+)?'
            r'(?P<name>.+)$',
            re.IGNORECASE
        )

        match = full_pattern.match(text)
        if not match:
            # No leading number → name only
            return {"name": text, "amount": None, "unit": None}

        raw_amount = match.group('amount').strip()
        unit = match.group('unit')
        name = match.group('name').strip()

        # Normalise amount: replace comma decimal → dot, evaluate simple fractions
        raw_amount = raw_amount.replace(',', '.')
        if '/' in raw_amount:
            parts = raw_amount.split('/')
            try:
                raw_amount = str(float(parts[0].strip()) / float(parts[1].strip()))
            except (ValueError, ZeroDivisionError):
                pass
        # Remove trailing .0
        if raw_amount.endswith('.0'):
            raw_amount = raw_amount[:-2]

        # If unit was not found but we have a count, infer stuk / stuks
        if unit is None:
            try:
                count = float(raw_amount)
                unit = 'stuk' if count == 1 else 'stuks'
            except ValueError:
                unit = None

        unit = unit.strip() if unit else None

        return {"name": name, "amount": raw_amount, "unit": unit}

    # ------------------------------------------------------------------
    # Public extraction methods
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Extract recipe name."""
        recipe = self._get_recipe_json_ld()
        if recipe:
            name = recipe.get('name')
            if name:
                return self.clean_text(name)

        # Fallback: og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        # Fallback: h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def extract_description(self) -> Optional[str]:
        """Extract recipe description."""
        recipe = self._get_recipe_json_ld()
        if recipe:
            desc = recipe.get('description')
            if desc:
                return self.clean_text(desc)

        # Fallback: og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Extract ingredients as a JSON string of dicts with name/amount/unit.

        Primary source: JSON-LD recipeIngredient list.
        Fallback: HTML label elements with data-ingredient-labels attribute.
        """
        # --- Primary: JSON-LD recipeIngredient ---
        recipe = self._get_recipe_json_ld()
        ingredients = []

        if recipe:
            raw_list = recipe.get('recipeIngredient', [])
            if isinstance(raw_list, list) and raw_list:
                for item in raw_list:
                    if isinstance(item, str) and item.strip():
                        parsed = self._parse_ingredient_string(self.clean_text(item))
                        ingredients.append(parsed)

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        # --- Fallback: HTML labels ---
        labels = self.soup.find_all('label', class_='option custom-control-label')
        for label in labels:
            text = self.clean_text(label.get_text())
            if text:
                parsed = self._parse_ingredient_string(text)
                ingredients.append(parsed)

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        return None

    def extract_steps(self) -> Optional[str]:
        """Extract recipe instructions as a single string of numbered steps."""
        recipe = self._get_recipe_json_ld()
        steps = []

        if recipe:
            raw_instructions = recipe.get('recipeInstructions', [])
            if isinstance(raw_instructions, list):
                for step in raw_instructions:
                    if isinstance(step, dict):
                        text = step.get('text', '')
                        if isinstance(text, list):
                            # Join sub-parts with ", "
                            text = ', '.join(str(t).strip() for t in text if t)
                        text = self.clean_text(str(text))
                        if text:
                            steps.append(text)
                    elif isinstance(step, str):
                        text = self.clean_text(step)
                        if text:
                            steps.append(text)
            elif isinstance(raw_instructions, str):
                text = self.clean_text(raw_instructions)
                if text:
                    steps.append(text)

        if steps:
            return ' '.join(steps)

        logger.warning("No instructions found in JSON-LD for %s", self.html_path)
        return None

    @staticmethod
    def _has_meta_item_class(class_attr) -> bool:
        """Return True if the element's class list contains recipe-header__info__meta__item."""
        if isinstance(class_attr, str):
            return 'recipe-header__info__meta__item' in class_attr
        return bool(class_attr) and 'recipe-header__info__meta__item' in ' '.join(class_attr)

    def _get_recipe_header_meta_items(self):
        """Return all recipe header meta item divs."""
        return self.soup.find_all('div', class_=self._has_meta_item_class)

    def extract_category(self) -> Optional[str]:
        """Extract recipe category."""
        # Primary: JSON-LD recipeCategory
        recipe = self._get_recipe_json_ld()
        if recipe:
            cat = recipe.get('recipeCategory')
            if cat:
                if isinstance(cat, list):
                    return self.clean_text(', '.join(str(c) for c in cat if c))
                return self.clean_text(str(cat))

        # Fallback: HTML category meta item (link to /recepten/type/...)
        for item in self._get_recipe_header_meta_items():
            a_tag = item.find('a', href=re.compile(r'/recepten/type/'))
            if a_tag:
                return self.clean_text(a_tag.get_text())

        return None

    def extract_prep_time(self) -> Optional[str]:
        """
        Извлечение отображаемого времени приготовления.

        Сайт показывает единое значение времени в шапке рецепта.
        Оно соответствует cookTime/totalTime в JSON-LD (prepTime всегда 0).
        Возвращается как prep_time для соответствия эталонному формату.
        """
        # Primary: HTML time meta item (most accurate display value)
        for item in self._get_recipe_header_meta_items():
            a_tag = item.find('a', href=re.compile(r'[?&]duration='))
            if a_tag:
                text = self.clean_text(item.get_text())
                if text:
                    return text

        # Fallback: JSON-LD cookTime or totalTime
        recipe = self._get_recipe_json_ld()
        if recipe:
            for key in ('cookTime', 'totalTime', 'prepTime'):
                value = recipe.get(key)
                if value:
                    result = self._parse_iso_duration(value)
                    if result:
                        return result

        return None

    def extract_cook_time(self) -> Optional[str]:
        """Cook time – not separately displayed on this site; returns None."""
        return None

    def extract_total_time(self) -> Optional[str]:
        """Total time – not separately displayed on this site; returns None."""
        return None

    def extract_notes(self) -> Optional[str]:
        """Extract recipe notes/tips if present."""
        # Look for a dedicated notes/tips container (Dutch: opmerking, tip, nota)
        # using class names that specifically denote a notes section
        notes_class_pattern = re.compile(r'^recipe[-_]?(notes?|tips?|opmerkingen?)$', re.I)
        candidate = self.soup.find(class_=notes_class_pattern)
        if candidate:
            text = self.clean_text(candidate.get_text())
            if text and len(text) > 10:
                return text

        # Look for a heading with "tip" or "opmerking" keyword followed by content
        for heading in self.soup.find_all(['h2', 'h3', 'h4']):
            heading_text = self.clean_text(heading.get_text()).lower()
            if re.search(r'\b(tip|tips|opmerking|opmerkingen|nota)\b', heading_text):
                # Collect the sibling paragraph/div text
                parts = []
                for sibling in heading.find_next_siblings():
                    if sibling.name in ('h2', 'h3', 'h4'):
                        break
                    text = self.clean_text(sibling.get_text())
                    if text:
                        parts.append(text)
                if parts:
                    return ' '.join(parts)

        return None

    def extract_tags(self) -> Optional[str]:
        """Extract tags from JSON-LD keywords field."""
        recipe = self._get_recipe_json_ld()
        if recipe:
            keywords = recipe.get('keywords', '')
            if isinstance(keywords, str) and keywords.strip():
                # Keywords may start with a comma: ",Fruit"
                tags = [t.strip() for t in keywords.split(',') if t.strip()]
                if tags:
                    return ', '.join(tags)
            elif isinstance(keywords, list):
                tags = [str(t).strip() for t in keywords if str(t).strip()]
                if tags:
                    return ', '.join(tags)

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Extract recipe image URLs."""
        urls = []

        # Primary: JSON-LD Recipe image
        recipe = self._get_recipe_json_ld()
        if recipe:
            img = recipe.get('image')
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                url = img.get('url') or img.get('contentUrl')
                if url:
                    urls.append(url)
            elif isinstance(img, list):
                for i in img:
                    if isinstance(i, str):
                        urls.append(i)
                    elif isinstance(i, dict):
                        url = i.get('url') or i.get('contentUrl')
                        if url:
                            urls.append(url)

        # Fallback: og:image
        og_img = self.soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            urls.append(og_img['content'])

        # Deduplicate preserving order
        seen: set = set()
        unique: list = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    def extract_all(self) -> dict:
        """
        Extract all recipe data.

        Returns:
            dict with keys: dish_name, description, ingredients, instructions,
            category, prep_time, cook_time, total_time, notes, tags, image_urls.
        """
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_steps(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls(),
        }


def main():
    """Entry point: process all HTML files in preprocessed/lekkervanbijons_be."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "lekkervanbijons_be")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(LekkervanbijonsBeExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python lekkervanbijons_be.py")


if __name__ == "__main__":
    main()
