"""
Экстрактор данных рецептов для сайта orami.co.id
"""

import logging
import re
import sys
import json
from pathlib import Path
from typing import Optional, List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class OramiCoIdExtractor(BaseRecipeExtractor):
    """Экстрактор для orami.co.id"""

    # Indonesian and common cooking units
    _UNITS = (
        r'ikat|siung|buah|keping|lembar|helai|butir|bungkus|sachet|batang|'
        r'potong|iris|ruas|tangkai|genggam|sendok|loyang|kaleng|kantong|'
        r'sdm|sdt|sdm\.|sdt\.|'  # tablespoon/teaspoon abbreviations
        r'gram|gr|g|kg|kilogram|'
        r'ml|mL|liter|l|L|cc|'
        r'cup|cups|mangkuk|gelas|cangkir|'
        r'tablespoon|tablespoons|tbsp|tsp|teaspoon|teaspoons|'
        r'ounce|ounces|oz|pound|pounds|lb|lbs|'
        r'cm|mm|inch|inches'
    )

    # ------------------------------------------------------------------ #
    #  Low-level helpers                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """Convert ISO 8601 duration (PT15M, PT1H30M) → human-readable string."""
        if not duration or not isinstance(duration, str):
            return None
        duration = duration.strip()
        if not duration.upper().startswith('PT'):
            return None
        duration = duration[2:]
        hours, minutes = 0, 0
        h = re.search(r'(\d+)H', duration, re.I)
        m = re.search(r'(\d+)M', duration, re.I)
        if h:
            hours = int(h.group(1))
        if m:
            minutes = int(m.group(1))
        total = hours * 60 + minutes
        if total <= 0:
            return None
        if hours > 0 and minutes > 0:
            return f"{hours} hour{'s' if hours > 1 else ''} {minutes} minute{'s' if minutes > 1 else ''}"
        if hours > 0:
            return f"{hours} hour{'s' if hours > 1 else ''}"
        return f"{minutes} minute{'s' if minutes > 1 else ''}"

    def _get_json_ld(self) -> List[Dict[str, Any]]:
        """Return parsed list of all JSON-LD objects on the page."""
        results = []
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
                results.append(data)
            except (json.JSONDecodeError, TypeError):
                logger.debug("Failed to parse JSON-LD script")
        return results

    def _get_article_ld(self) -> Optional[Dict[str, Any]]:
        """Return the Article JSON-LD object, or None."""
        for obj in self._get_json_ld():
            if isinstance(obj, dict) and obj.get('@type') in ('Article', 'NewsArticle', 'BlogPosting'):
                return obj
        return None

    def _get_item_list_recipes(self) -> List[Dict[str, Any]]:
        """Return list of Recipe dicts from the ItemList JSON-LD, if present."""
        recipes = []
        for obj in self._get_json_ld():
            if isinstance(obj, dict) and obj.get('@type') == 'ItemList':
                for item in obj.get('itemListElement', []):
                    recipe = item.get('item', {})
                    if isinstance(recipe, dict) and recipe.get('@type') == 'Recipe':
                        recipes.append(recipe)
        return recipes

    # ------------------------------------------------------------------ #
    #  Ingredient parsing                                                  #
    # ------------------------------------------------------------------ #

    # Words meaning "to taste" / "as needed" in Indonesian/English
    _TO_TASTE = re.compile(
        r'\b(secukupnya|sesuai\s+selera|sedikit|secukup|as needed|to taste)\b',
        re.IGNORECASE,
    )

    def _parse_ingredient(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Parse a single ingredient string (Indonesian / English) into
        {"name": ..., "amount": ..., "unit": ...}.

        Handles patterns like:
          "200 gram buah naga"  → name="buah naga",  amount="200",   unit="gram"
          "1 ikat kangkung"     → name="kangkung",   amount="1",     unit="ikat"
          "Tauge secukupnya"    → name="tauge",      amount="secukupnya", unit=None
          "Kacang tanah"        → name="kacang tanah", amount=None, unit=None
        """
        if not text:
            return None
        text = self.clean_text(text)
        if not text:
            return None

        # Normalize Unicode fractions
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
        }
        for frac, replacement in fraction_map.items():
            text = text.replace(frac, replacement)

        # Check for trailing "secukupnya" / "to taste" style words
        to_taste_match = self._TO_TASTE.search(text)
        if to_taste_match:
            # Remove the to-taste phrase from the text
            name_part = self._TO_TASTE.sub('', text).strip().rstrip(',').strip()
            # If what remains starts with digits (amount) strip them into amount
            num_pfx = re.match(r'^([\d]+(?:[.,/\-][\d]+)*)\s+(.+)$', name_part)
            if num_pfx:
                amount_str, name_part = num_pfx.group(1).strip(), num_pfx.group(2).strip()
                return {"name": name_part, "amount": amount_str, "unit": None}
            if name_part:
                return {"name": name_part, "amount": to_taste_match.group(0), "unit": None}
            return {"name": text, "amount": None, "unit": None}

        # Pattern: optional number (including fractions and ranges like 1-2 or 8-10),
        # optional unit, then the ingredient name.
        pattern = (
            r'^'
            r'([\d]+(?:[.,/\-][\d]+)*(?:\s+[\d]+/[\d]+)?)'  # amount (required group 1)
            r'\s+'
            r'(' + self._UNITS + r')'                          # unit (required group 2)
            r'\.?\s+'
            r'(.+)$'                                           # name (group 3)
        )
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            amount_str, unit, name = match.group(1), match.group(2), match.group(3)
            amount = amount_str.strip() if amount_str else None
            unit = unit.strip() if unit else None
            name = re.sub(r'\s+', ' ', name).strip() if name else None
            if name:
                return {"name": name, "amount": amount, "unit": unit}

        # Check if string starts with a number (no unit found)
        num_match = re.match(r'^([\d]+(?:[.,/\-][\d]+)*(?:\s+[\d]+/[\d]+)?)\s+(.+)$', text)
        if num_match:
            amount = num_match.group(1).strip()
            name = num_match.group(2).strip()
            return {"name": name, "amount": amount, "unit": None}

        # No number at all – the whole string is the name
        return {"name": text, "amount": None, "unit": None}

    # ------------------------------------------------------------------ #
    #  Field extractors                                                    #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Extract dish name: first Recipe name from ItemList, else article headline."""
        try:
            recipes = self._get_item_list_recipes()
            if recipes:
                name = recipes[0].get('name')
                if name:
                    return self.clean_text(name)

            article = self._get_article_ld()
            if article:
                headline = article.get('headline')
                if headline:
                    return self.clean_text(headline)

            h1 = self.soup.find('h1')
            if h1:
                return self.clean_text(h1.get_text())
        except Exception as e:
            logger.warning("Error extracting dish_name: %s", e)
        return None

    def extract_description(self) -> Optional[str]:
        """Extract description from Article JSON-LD or meta description."""
        try:
            article = self._get_article_ld()
            if article:
                desc = article.get('description')
                if desc:
                    return self.clean_text(desc)

            meta = self.soup.find('meta', attrs={'name': 'description'})
            if meta and meta.get('content'):
                return self.clean_text(meta['content'])

            og_desc = self.soup.find('meta', property='og:description')
            if og_desc and og_desc.get('content'):
                return self.clean_text(og_desc['content'])
        except Exception as e:
            logger.warning("Error extracting description: %s", e)
        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Extract ingredients from the primary (first) ItemList Recipe
        recipeIngredient, falling back to HTML h4 'Bahan:' sections.
        Returns JSON-encoded list of {name, amount, unit} dicts.
        """
        try:
            recipes = self._get_item_list_recipes()
            if recipes:
                # Use only the first (primary) recipe for a coherent ingredient list
                result: List[Dict[str, Any]] = []
                seen_names: set = set()
                for raw in recipes[0].get('recipeIngredient', []):
                    raw = self.clean_text(raw)
                    if not raw:
                        continue
                    parsed = self._parse_ingredient(raw)
                    if not parsed:
                        continue
                    name_key = (parsed.get('name') or '').lower().strip()
                    if name_key and name_key not in seen_names:
                        seen_names.add(name_key)
                        result.append(parsed)
                if result:
                    return json.dumps(result, ensure_ascii=False)

            # Fallback: parse HTML h4 "Bahan:" sections (aggregate unique across all recipe sections)
            result = []
            seen_names: set = set()
            for h4 in self.soup.find_all('h4'):
                h4_text = h4.get_text().strip().lower()
                if 'bahan' not in h4_text:
                    continue
                ul = h4.find_next_sibling('ul')
                if not ul:
                    continue
                for li in ul.find_all('li'):
                    raw = self.clean_text(li.get_text())
                    if not raw:
                        continue
                    parsed = self._parse_ingredient(raw)
                    if not parsed:
                        continue
                    # Normalize name: strip trailing commas and qualifiers
                    name = parsed.get('name') or ''
                    name = re.sub(r'[,\.]+$', '', name).strip()
                    name = re.sub(r',\s*(ditumbuk|dipotong|dihaluskan|diiris|diparut|dibekukan|bekukan|beku|sangrai|goreng)$',
                                  '', name, flags=re.I).strip()
                    parsed['name'] = name
                    name_key = name.lower()
                    if name_key and name_key not in seen_names:
                        seen_names.add(name_key)
                        result.append(parsed)
            if result:
                return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            logger.warning("Error extracting ingredients: %s", e)
        return None

    def extract_instructions(self) -> Optional[str]:
        """
        Extract instructions from the primary (first) ItemList Recipe
        recipeInstructions, falling back to HTML 'Cara Membuat:' sections.
        """
        try:
            recipes = self._get_item_list_recipes()
            if recipes:
                # Use only the first (primary) recipe for coherent instructions
                steps: List[str] = []
                for step in recipes[0].get('recipeInstructions', []):
                    if isinstance(step, dict):
                        text = self.clean_text(step.get('text', ''))
                    elif isinstance(step, str):
                        text = self.clean_text(step)
                    else:
                        continue
                    if text:
                        steps.append(text)
                if steps:
                    numbered = [f"{i}. {s}" for i, s in enumerate(steps, 1)]
                    return '\n'.join(numbered)

            # Fallback: scan all headers in document order, group h4 'Cara Membuat:'
            # sections under their nearest preceding h3 recipe heading.
            all_headers = self.soup.find_all(['h3', 'h4'])
            current_recipe_name: str = ''
            recipe_counter: int = 0
            all_parts: List[str] = []
            for header in all_headers:
                text = header.get_text().strip()
                if header.name == 'h3':
                    # Strip leading numbering like "1. " or "1) "
                    label = re.sub(r'^\d+[\.\)]\s*', '', text).strip()
                    current_recipe_name = label
                    recipe_counter += 1
                elif header.name == 'h4':
                    h4_lower = text.lower()
                    if 'cara membuat' not in h4_lower and 'cara memasak' not in h4_lower:
                        continue
                    ol = header.find_next_sibling('ol')
                    if not ol:
                        continue
                    steps_list: List[str] = []
                    for li in ol.find_all('li'):
                        step = self.clean_text(li.get_text())
                        if step:
                            steps_list.append(step)
                    if steps_list:
                        # Strip trailing punctuation from each step before joining
                        cleaned = [s.rstrip('.').strip() for s in steps_list]
                        joined = '. '.join(cleaned)
                        if current_recipe_name:
                            block = f"{recipe_counter}. {current_recipe_name}: {joined}"
                        else:
                            block = joined
                        all_parts.append(block)
            if all_parts:
                return '\n'.join(all_parts)
        except Exception as e:
            logger.warning("Error extracting instructions: %s", e)
        return None

    def extract_category(self) -> Optional[str]:
        """Extract category from Article articleSection or BreadcrumbList."""
        try:
            article = self._get_article_ld()
            if article:
                section = article.get('articleSection')
                if section:
                    return self.clean_text(section)

            # Fallback: BreadcrumbList second-to-last item
            for obj in self._get_json_ld():
                if isinstance(obj, dict) and obj.get('@type') == 'BreadcrumbList':
                    items = obj.get('itemListElement', [])
                    # Skip Home (first) and current page (last)
                    if len(items) >= 3:
                        cat_item = items[-2].get('item', {})
                        name = cat_item.get('name')
                        if name:
                            return self.clean_text(name)
        except Exception as e:
            logger.warning("Error extracting category: %s", e)
        return None

    def _extract_time_from_recipes(self, key: str) -> Optional[str]:
        """Extract prep/cook/total time from the first ItemList recipe that has it."""
        try:
            for recipe in self._get_item_list_recipes():
                value = recipe.get(key)
                if value:
                    result = self._parse_iso_duration(value)
                    if result:
                        return result
        except Exception as e:
            logger.warning("Error extracting time (%s): %s", key, e)
        return None

    def extract_prep_time(self) -> Optional[str]:
        result = self._extract_time_from_recipes('prepTime')
        if result is None:
            # If no separate prepTime but there is totalTime and no cookTime, use totalTime
            total = self._extract_time_from_recipes('totalTime')
            cook = self._extract_time_from_recipes('cookTime')
            if total and not cook:
                return total
        return result

    def extract_cook_time(self) -> Optional[str]:
        return self._extract_time_from_recipes('cookTime')

    def extract_total_time(self) -> Optional[str]:
        return self._extract_time_from_recipes('totalTime')

    def extract_notes(self) -> Optional[str]:
        """
        Extract notes from the article body concluding paragraph(s)
        or advisory/tip text found in the article.
        """
        try:
            # Look for paragraphs that appear to be advisory/note text
            # (contain keywords like 'disarankan', 'perlu diperhatikan', 'tips', etc.)
            note_keywords = (
                'disarankan', 'perlu diingat', 'perhatikan', 'penting',
                'catatan', 'tips', 'saran', 'jangan lupa', 'hindari',
                'pastikan', 'sebaiknya'
            )
            for p in self.soup.find_all('p'):
                text = p.get_text().strip()
                lower = text.lower()
                if any(kw in lower for kw in note_keywords):
                    cleaned = self.clean_text(text)
                    if cleaned and len(cleaned) > 20:
                        return cleaned
        except Exception as e:
            logger.warning("Error extracting notes: %s", e)
        return None

    def extract_tags(self) -> Optional[str]:
        """Extract tags from Article JSON-LD keywords."""
        try:
            article = self._get_article_ld()
            if article:
                keywords = article.get('keywords')
                if keywords:
                    tags = [t.strip() for t in keywords.split(',') if t.strip()]
                    if tags:
                        return ', '.join(tags)
        except Exception as e:
            logger.warning("Error extracting tags: %s", e)
        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Collect image URLs from og:image, Article JSON-LD image,
        and ItemList Recipe images.  Return comma-joined unique URLs.
        """
        urls: List[str] = []
        seen: set = set()

        def _add(url: Any) -> None:
            if isinstance(url, str) and url and url not in seen:
                seen.add(url)
                urls.append(url)

        try:
            og = self.soup.find('meta', property='og:image')
            if og and og.get('content'):
                _add(og['content'])

            for obj in self._get_json_ld():
                if not isinstance(obj, dict):
                    continue
                img = obj.get('image')
                if img:
                    if isinstance(img, dict):
                        _add(img.get('url') or img.get('contentUrl'))
                    elif isinstance(img, list):
                        for item in img:
                            if isinstance(item, str):
                                _add(item)
                            elif isinstance(item, dict):
                                _add(item.get('url') or item.get('contentUrl'))
                    elif isinstance(img, str):
                        _add(img)

                # ItemList recipes
                if obj.get('@type') == 'ItemList':
                    for list_item in obj.get('itemListElement', []):
                        recipe = list_item.get('item', {})
                        r_img = recipe.get('image')
                        if isinstance(r_img, list):
                            for i in r_img:
                                _add(i) if isinstance(i, str) else None
                        elif isinstance(r_img, str):
                            _add(r_img)
        except Exception as e:
            logger.warning("Error extracting image_urls: %s", e)

        return ','.join(urls) if urls else None

    # ------------------------------------------------------------------ #
    #  Main entry point                                                    #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """
        Extract all recipe data from the HTML page.

        Returns:
            dict with keys: dish_name, description, ingredients, instructions,
            category, prep_time, cook_time, total_time, notes, image_urls, tags.
            Missing values are None.
        """
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_instructions(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags(),
        }


def main() -> None:
    import os
    recipes_dir = os.path.join("preprocessed", "orami_co_id")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(OramiCoIdExtractor, str(recipes_dir))
        return
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python orami_co_id.py")


if __name__ == "__main__":
    main()
