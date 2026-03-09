"""
Экстрактор данных рецептов для сайта equipenutrition.ca
"""

import logging
import re
import sys
import json
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class EquipenutritionCaExtractor(BaseRecipeExtractor):
    """Экстрактор для equipenutrition.ca (Drupal-based recipe site)"""

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _get_recipe_jsonld(self) -> Optional[dict]:
        """Возвращает словарь Recipe из JSON-LD (@graph или корневой объект)."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
                if isinstance(data, dict):
                    for item in data.get('@graph', []):
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                    if data.get('@type') == 'Recipe':
                        return data
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    @staticmethod
    def _parse_minutes_from_html_field(text: str) -> Optional[str]:
        """
        Извлекает число минут из строки вида «Préparation15min» или «Cuisson50min».
        Возвращает строку вида «15 minutes».
        """
        # Check hours + minutes first (e.g. "1h30min")
        h_match = re.search(r'(\d+)\s*h(?:eure)?s?\s*(\d+)?\s*min?', text, re.IGNORECASE)
        if h_match:
            hours = int(h_match.group(1))
            mins = int(h_match.group(2)) if h_match.group(2) else 0
            return f"{hours * 60 + mins} minutes"
        # Hours only
        h_only = re.search(r'(\d+)\s*h(?:eure)?s?(?!\w)', text, re.IGNORECASE)
        if h_only:
            return f"{int(h_only.group(1)) * 60} minutes"
        # Minutes only
        m_match = re.search(r'(\d+)\s*min', text, re.IGNORECASE)
        if m_match:
            return f"{int(m_match.group(1))} minutes"
        return None

    @staticmethod
    def _normalize_apostrophe(text: str) -> str:
        """Replace all apostrophe variants with standard ASCII apostrophe."""
        return (text
                .replace('\u2019', "'")
                .replace('\u02bc', "'")
                .replace('\u2018', "'"))

    @staticmethod
    def _parse_french_ingredient(raw: str) -> dict:
        """
        Парсит строку французского ингредиента в словарь {name, amount, unit}.

        Форматы:
          «125 ml (½ tasse) de yogourt grec»  -> amount=125, unit=ml, name=yogourt grec
          «2,5 ml (½ c. à thé) d'extrait»     -> amount=2.5, unit=ml, name=extrait
          «3 bananes mûres, écrasées»          -> amount=3, unit=pcs, name=bananes mûres, écrasées
          «2 oeufs, de calibre gros»           -> amount=2, unit=pcs, name=oeufs, de calibre gros
          «1 pincée de sel»                    -> amount=1, unit=pincée, name=sel
          «1 conserve de 540 ml de pois …»    -> amount=1, unit=conserve, name=540 ml de pois …
          «Copeaux de chocolat noir»           -> amount=None, unit=None, name=Copeaux de chocolat noir
        """
        text = EquipenutritionCaExtractor._normalize_apostrophe(raw.strip())

        # Unicode fractions to decimal string
        fraction_map = [
            ('\u00bd', '0.5'), ('\u00bc', '0.25'), ('\u00be', '0.75'),
            ('\u2153', '0.333'), ('\u2154', '0.667'), ('\u215b', '0.125'),
            ('\u215c', '0.375'), ('\u215d', '0.625'), ('\u215e', '0.875'),
        ]
        for frac, dec in fraction_map:
            text = text.replace(frac, dec)

        # French decimal separator: "2,5" -> "2.5" (only between digits)
        text = re.sub(r'(\d),(\d)', r'\1.\2', text)

        def normalize_amount(s: str) -> str:
            s = s.strip()
            try:
                v = float(s)
                return str(int(v)) if v == int(v) else s
            except ValueError:
                return s

        # de/d' prefix that may appear before the name
        DE = r"(?:de\s+|d'\s*)"

        # --- Pattern 1: N metric_unit (optional sub-unit) de/d' name ---
        m = re.match(
            r'^([\d.]+)\s+(ml|g|kg|l)\s*(?:\([^)]*\))?\s*' + DE + r'(.+)$',
            text, re.IGNORECASE,
        )
        if m:
            return {"name": re.sub(r'\s+', ' ', m.group(3)).strip(),
                    "amount": normalize_amount(m.group(1)),
                    "unit": m.group(2).strip()}

        # --- Pattern 2: N named_unit (optional de/d') name ---
        named_units = (
            r"pinc\xe9e?s?|conserve|sachet|bo\xeete|tasse|"
            r"c\.\s*\xe0\s*(?:th\xe9|soupe)|c\.\s*\xe0\s*[st]\.|"
            r"cuill\xe8re\s*\xe0\s*(?:th\xe9|soupe)|"
            r"portion|once|oz|lb|lbs?|gousse|branche|tranche|filet|poign\xe9e|cube"
        )
        m = re.match(
            r'^([\d.]+)\s+(' + named_units + r')\s*(?:' + DE + r')?(.+)$',
            text, re.IGNORECASE,
        )
        if m:
            return {"name": re.sub(r'\s+', ' ', m.group(3)).strip(),
                    "amount": normalize_amount(m.group(1)),
                    "unit": m.group(2).strip()}

        # --- Pattern 3: integer count + alphabetic name (no unit keyword) ---
        m = re.match(
            r'^(\d+)\s+(?:' + DE + r')?([A-Za-z\u00C0-\u024F].+)$',
            text,
        )
        if m:
            return {"name": re.sub(r'\s+', ' ', m.group(2)).strip(),
                    "amount": m.group(1),
                    "unit": "pcs"}

        # --- Fallback: pure name, no amount ---
        return {"name": text, "amount": None, "unit": None}

    @staticmethod
    def _extract_minutes(time_str: str) -> Optional[int]:
        """Извлекает число минут из строки вида «15 minutes»."""
        m = re.search(r'(\d+)', time_str)
        return int(m.group(1)) if m else None

    # ------------------------------------------------------------------ #
    # Field extractors
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из h1 или JSON-LD."""
        h1 = self.soup.find('h1')
        if h1:
            name = self.clean_text(h1.get_text())
            if name:
                return name

        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('name'):
            return self.clean_text(recipe['name'])

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта из поля body (внутри статьи рецепта) или JSON-LD."""
        article = self.soup.find('article', class_=re.compile(r'node--type-recipe'))
        if article:
            body = article.find('div', class_=re.compile(r'field--name-body'))
            if body:
                text = self.clean_text(body.get_text(separator=' ', strip=True))
                if text and len(text) > 30:
                    return text

        for div in self.soup.find_all('div', class_=re.compile(r'field--name-body')):
            text = self.clean_text(div.get_text(separator=' ', strip=True))
            if text and len(text) > 30:
                return text

        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('description'):
            return self.clean_text(recipe['description'])

        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из HTML-списка field--name-field-ingredients-description.
        Возвращает JSON-строку со списком словарей {name, amount, unit}.
        """
        ing_div = self.soup.find(
            'div', class_=re.compile(r'field--name-field-ingredients-description')
        )
        if not ing_div:
            logger.warning("Ingredients container not found in HTML")
            return None

        items = ing_div.find_all('li')
        if not items:
            logger.warning("No <li> elements found inside ingredients container")
            return None

        ingredients = []
        for li in items:
            raw = self.clean_text(li.get_text(separator=' ', strip=True))
            if not raw:
                continue
            # Skip section headers that end with colon or are very short without digits
            if raw.endswith(':') or (len(raw) < 4 and not re.search(r'\d', raw)):
                continue
            parsed = self._parse_french_ingredient(raw)
            if parsed:
                ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления из field--name-field-preparation-description."""
        prep_div = self.soup.find(
            'div', class_=re.compile(r'field--name-field-preparation-description')
        )
        if not prep_div:
            logger.warning("Preparation container not found in HTML")
            return None

        steps = []
        items = prep_div.find_all('li')
        if items:
            for li in items:
                text = self.clean_text(li.get_text(separator=' ', strip=True))
                if text:
                    steps.append(text)
        else:
            for p in prep_div.find_all('p'):
                text = self.clean_text(p.get_text(separator=' ', strip=True))
                if text:
                    steps.append(text)

        if not steps:
            return None

        return ' '.join(steps)

    def extract_category(self) -> Optional[str]:
        """Категория из JSON-LD recipeCategory или мета-тега article:section."""
        recipe = self._get_recipe_jsonld()
        if recipe:
            cat = recipe.get('recipeCategory')
            if isinstance(cat, list):
                cat = ', '.join(str(c) for c in cat)
            if cat:
                return self.clean_text(str(cat))

        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки из HTML-поля field--name-field-preparation."""
        prep_div = self.soup.find(
            'div', class_=re.compile(r'\bfield--name-field-preparation\b')
        )
        if prep_div:
            return self._parse_minutes_from_html_field(
                prep_div.get_text(separator=' ', strip=True)
            )
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки из HTML-поля field--name-field-cooking."""
        cook_div = self.soup.find(
            'div', class_=re.compile(r'\bfield--name-field-cooking\b')
        )
        if cook_div:
            return self._parse_minutes_from_html_field(
                cook_div.get_text(separator=' ', strip=True)
            )
        return None

    def extract_total_time(self) -> Optional[str]:
        """
        Общее время приготовления.
        Вычисляется как сумма prep_time и cook_time, если оба присутствуют.
        """
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        if prep and cook:
            prep_m = self._extract_minutes(prep)
            cook_m = self._extract_minutes(cook)
            if prep_m is not None and cook_m is not None:
                total = prep_m + cook_m
                if total > 0:
                    return f"{total} minutes"
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок из поля field--name-field-outro (секция «Notes»)."""
        outro_div = self.soup.find(
            'div', class_=re.compile(r'field--name-field-outro')
        )
        if outro_div:
            text = self.clean_text(outro_div.get_text(separator=' ', strip=True))
            # Remove the section heading at the start
            text = re.sub(r'^Notes\s*', '', text, flags=re.IGNORECASE).strip()
            return text if text else None
        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords или meta keywords."""
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('keywords'):
            keywords = recipe['keywords']
            tags = [t.strip() for t in re.split(r'[,;]', keywords) if t.strip()]
            if tags:
                return ', '.join(tags)

        meta_kw = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_kw and meta_kw.get('content'):
            tags = [t.strip() for t in meta_kw['content'].split(',') if t.strip()]
            if tags:
                return ', '.join(tags)

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений (og:image + JSON-LD image)."""
        urls = []

        og_img = self.soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            urls.append(og_img['content'])

        recipe = self._get_recipe_jsonld()
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

        seen: set = set()
        unique: list = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь со стандартными полями рецепта.
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception as e:
            logger.error("Error extracting dish_name: %s", e)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as e:
            logger.error("Error extracting description: %s", e)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as e:
            logger.error("Error extracting ingredients: %s", e)
            ingredients = None

        try:
            instructions = self.extract_instructions()
        except Exception as e:
            logger.error("Error extracting instructions: %s", e)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as e:
            logger.error("Error extracting category: %s", e)
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception as e:
            logger.error("Error extracting prep_time: %s", e)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception as e:
            logger.error("Error extracting cook_time: %s", e)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception as e:
            logger.error("Error extracting total_time: %s", e)
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception as e:
            logger.error("Error extracting notes: %s", e)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as e:
            logger.error("Error extracting tags: %s", e)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as e:
            logger.error("Error extracting image_urls: %s", e)
            image_urls = None

        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "notes": notes,
            "image_urls": image_urls,
            "tags": tags,
        }


def main():
    import os

    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'preprocessed', 'equipenutrition_ca'
    )
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(EquipenutritionCaExtractor, preprocessed_dir)
        return

    print(f"Directory not found: {preprocessed_dir}")
    print("Usage: python equipenutrition_ca.py")


if __name__ == "__main__":
    main()
