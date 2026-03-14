"""
Экстрактор данных рецептов для сайта parastapoytaan.fi

Сайт построен на Webflow и использует структуру вкладок:
 - Вкладка 1 (ainekset / ingredients): ингредиенты в <ul><li> или <p> тегах
 - Вкладка 2 (valmistusohje / instructions): шаги приготовления в <p> тегах
 - Вкладка 3 (lisätietoja / notes): дополнительные заметки
"""

import sys
import json
import logging
import re
from pathlib import Path
from typing import List, Optional, Set

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


# Finnish units common in cooking
_FINNISH_UNITS = {
    'kg', 'g', 'l', 'dl', 'ml', 'cl',
    'tl', 'rkl',
    'kpl',
    'oksaa', 'oksa',
    'tlk',
    'prk',
    'pkt', 'pussia', 'pussi',
    'annos',
    'pala', 'palaa',
    'viipale', 'viipaletta',
    'lehti', 'lehteä',
    'raastettu', 'hienonnettu', 'pilkottu', 'silputtua',
    'murustettu', 'murskattua',
}

# Unicode fractions → decimal strings
_FRACTION_MAP = {
    '½': '0.5',
    '¼': '0.25',
    '¾': '0.75',
    '⅓': '1/3',
    '⅔': '2/3',
    '⅛': '0.125',
    '⅜': '0.375',
    '⅝': '0.625',
    '⅞': '0.875',
    '⅕': '0.2',
    '⅖': '0.4',
    '⅗': '0.6',
    '⅘': '0.8',
}

# Build a regex pattern for Finnish units (longest first to avoid partial matches)
_UNITS_PATTERN = '|'.join(
    re.escape(u) for u in sorted(_FINNISH_UNITS, key=len, reverse=True)
)

# Pattern: optional_amount  optional_unit  name
# Amount: digits with commas, dots, slashes, dashes (e.g. 1,5  1/2  1-2)
_INGREDIENT_RE = re.compile(
    r'^'
    r'([\d][\d,./\s-]*?(?=\s|$))?'   # group 1: amount (optional)
    r'\s*'
    r'(' + _UNITS_PATTERN + r')?'      # group 2: unit (optional)
    r'\s*'
    r'(.+)?'                           # group 3: name
    r'$',
    re.IGNORECASE,
)


class ParastapoytaanFiExtractor(BaseRecipeExtractor):
    """Экстрактор для parastapoytaan.fi"""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Возвращает данные Recipe из JSON-LD блока, если найдены."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    def _get_recipe_tabs(self) -> list:
        """
        Возвращает список div.recipe-tab вкладок рецепта.
        Порядок: [ainekset(Tab1), valmistusohje(Tab2), lisätietoja(Tab3)]
        """
        tabs_div = self.soup.find('div', class_=re.compile(r'\btabs\b.*\brecipe\b|\brecipe\b.*\btabs\b', re.I))
        if tabs_div:
            return tabs_div.find_all('div', class_='recipe-tab')
        # Fallback: find any recipe-tab divs on the page
        return self.soup.find_all('div', class_='recipe-tab')

    def _tab_richtext(self, tab_index: int):
        """Возвращает div.rich-text из указанной вкладки или None."""
        tabs = self._get_recipe_tabs()
        if tab_index >= len(tabs):
            return None
        return tabs[tab_index].find('div', class_='rich-text')

    # ------------------------------------------------------------------
    # Dish name
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Название блюда — из JSON-LD name или og:title."""
        # 1. JSON-LD (most reliable — shorter, clean title)
        ld = self._get_recipe_json_ld()
        if ld and ld.get('name'):
            return self.clean_text(ld['name'])

        # 2. og:title meta tag
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        # 3. First h1 on the page
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    # ------------------------------------------------------------------
    # Description
    # ------------------------------------------------------------------

    def extract_description(self) -> Optional[str]:
        """Описание рецепта — из meta description или og:description."""
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    # ------------------------------------------------------------------
    # Ingredient parsing
    # ------------------------------------------------------------------

    def _replace_fractions(self, text: str) -> str:
        """Заменяет Unicode-дроби на десятичные строки."""
        for frac, val in _FRACTION_MAP.items():
            text = text.replace(frac, val)
        return text

    def _parse_single_ingredient(self, raw: str) -> Optional[dict]:
        """
        Разбирает строку одного ингредиента на компоненты.

        Returns:
            {"name": ..., "amount": ..., "unit": ...}  или None
        """
        text = self._replace_fractions(raw.strip())
        if not text:
            return None

        # Strip extra description after em-dash (–)
        text = re.split(r'\s*–\s*', text, maxsplit=1)[0].strip()

        # Strip extra description after comma (keep only first part as name)
        # e.g. "3 oksaa tuoretta rosmariinia, morttelissa kevyesti murskattuna"
        # → "3 oksaa tuoretta rosmariinia"
        #
        # But we need to be careful not to strip part of the name itself
        # (e.g. "kapriksia" shouldn't be split).  We'll only strip comma-suffix
        # when a comma is followed by a qualifier word.
        comma_qualifier = re.match(
            r'^(.+?),\s+(?:ohuina|paksuina|pilkottuna|hienonnettuna|murskattuna|'
            r'raastettuna|halkaistuna|kuorittuna|silputtuna|paahdettuna|'
            r'morttelissa|vedessä|sulatettu|huoneenlämpöistä|siivuina|'
            r'paloiteltuna|kuivattuna|kevyesti)',
            text, re.IGNORECASE
        )
        if comma_qualifier:
            text = comma_qualifier.group(1).strip()

        # Try to match: amount + unit + name
        m = re.match(
            r'^'
            r'([\d][\d,./\s-]*?(?=\s|$))?'
            r'\s*'
            r'(' + _UNITS_PATTERN + r')?\s*'
            r'(.+)?$',
            text, re.IGNORECASE
        )

        if not m:
            return {"name": self.clean_text(text), "amount": None, "unit": None}

        amount_str, unit, name = m.group(1), m.group(2), m.group(3)

        # Normalise amount
        amount: Optional[str] = None
        if amount_str:
            amount_str = amount_str.strip()
            # Convert Finnish decimal comma to dot for normalisation
            normalised = amount_str.replace(',', '.')
            # For display, keep original (but normalised comma → dot)
            if '/' in amount_str:
                # Keep as fraction string (e.g. "1/2")
                amount = amount_str.strip()
            else:
                amount = normalised.strip()

        unit = unit.strip().lower() if unit else None

        # Clean up name
        if name:
            name = self.clean_text(name)
        else:
            # If no name was captured after unit, the unit might be part of the name
            if unit and not amount:
                return {"name": self.clean_text(unit), "amount": None, "unit": None}
            name = None

        if not name:
            return None

        return {"name": name, "amount": amount, "unit": unit}

    def _parse_ingredient_line(self, raw: str) -> list:
        """
        Разбирает строку, которая может содержать несколько ингредиентов,
        разделённых ' ja ' или ' sekä ' (финские союзы).

        Returns:
            Список dict-объектов ингредиентов
        """
        # Split on common Finnish conjunctions used to join ingredients
        parts = re.split(r'\s+(?:ja|sekä)\s+', raw.strip(), flags=re.IGNORECASE)
        result = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            parsed = self._parse_single_ingredient(part)
            if parsed:
                result.append(parsed)
        return result

    def extract_ingredients(self) -> Optional[str]:
        """
        Ингредиенты из первой вкладки (ainekset / Tab 1).
        Возвращает JSON-строку списка dict'ов {"name", "amount", "unit"}.
        """
        richtext = self._tab_richtext(0)
        if not richtext:
            logger.warning("Ingredients tab (Tab 1) not found")
            return None

        # Max length for a section header label (e.g. "KAPRISKASTIKE")
        _MAX_SECTION_HEADER_LENGTH = 40

        items: List[str] = []

        # Case 1: ingredients in <ul><li>
        ul = richtext.find('ul')
        if ul:
            for li in ul.find_all('li'):
                text = self.clean_text(li.get_text(separator=' ', strip=True))
                if text:
                    items.append(text)

        # Case 2: ingredients in <p> tags
        if not items:
            for p in richtext.find_all('p'):
                # Skip section headers (e.g. bold "KAPRISKASTIKE")
                if p.find('strong') and len(p.get_text(strip=True)) < _MAX_SECTION_HEADER_LENGTH and p.get_text(strip=True).isupper():
                    continue
                text = self.clean_text(p.get_text(separator=' ', strip=True))
                if text:
                    items.append(text)

        if not items:
            logger.warning("No ingredient items found in Tab 1")
            return None

        # Parse each line
        parsed_ingredients = []
        for line in items:
            parsed_ingredients.extend(self._parse_ingredient_line(line))

        if not parsed_ingredients:
            return None

        return json.dumps(parsed_ingredients, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Instructions
    # ------------------------------------------------------------------

    def extract_steps(self) -> Optional[str]:
        """
        Шаги приготовления из второй вкладки (valmistusohje / Tab 2).
        Извлекаем только реальные шаги, останавливаемся перед маркетинговым текстом.
        """
        richtext = self._tab_richtext(1)
        if not richtext:
            logger.warning("Instructions tab (Tab 2) not found")
            return None

        step_texts: List[str] = []

        for child in richtext.children:
            if not hasattr(child, 'name') or child.name is None:
                continue

            tag = child.name.lower()

            if tag not in ('p', 'h2', 'h3', 'ol', 'ul', 'li'):
                continue

            if tag in ('ol', 'ul'):
                for li in child.find_all('li'):
                    text = self.clean_text(li.get_text(separator=' ', strip=True))
                    if text:
                        step_texts.append(text)
                continue

            text = self.clean_text(child.get_text(separator=' ', strip=True))
            if not text:
                continue

            # Stop when we hit the time/serving metadata line embedded in Tab 2
            if re.search(r'valmistusaika|annosmäärä', text, re.IGNORECASE):
                break

            # Skip pure marketing paragraph (bold intro that doesn't contain
            # actual step content — heuristic: first bold paragraph with no digits
            # and no Finnish imperative-like verb at the start)
            if child.find('strong') and not any(c.isdigit() for c in text):
                # If the entire paragraph is wrapped in <strong>, treat as intro/note
                strong_children = [c for c in child.children
                                   if hasattr(c, 'name') and c.name == 'strong']
                non_strong = [c for c in child.children
                              if not (hasattr(c, 'name') and c.name == 'strong')
                              and str(c).strip()]
                if strong_children and not non_strong:
                    # All content is in <strong> — likely intro, skip
                    continue

            # Skip h2/h3 section titles (they're not cooking steps themselves)
            if tag in ('h2', 'h3'):
                continue

            step_texts.append(text)

        if not step_texts:
            logger.warning("No step texts found in Tab 2")
            return None

        return ' '.join(step_texts)

    # ------------------------------------------------------------------
    # Times
    # ------------------------------------------------------------------

    def _extract_about_recipe_items(self) -> dict:
        """
        Извлекает словарь {label: value} из блока 'about-the-recipe-card'.
        Пример: {"valmistusaika": "120 min", "annosmäärä": "6"}
        """
        result = {}
        about = self.soup.find('div', class_='about-the-recipe-card')
        if not about:
            return result
        for item in about.find_all('div', class_='about-the-recipe-item'):
            # Label is in the first non-class child div, value in about-the-recipe-text
            text_val = item.find('div', class_='about-the-recipe-text')
            # Label: all text except the value
            full_text = item.get_text(separator=' ', strip=True)
            val = text_val.get_text(strip=True) if text_val else ''
            label = full_text.replace(val, '').strip().rstrip(':').strip().lower()
            if label and val:
                result[label] = val
        return result

    def extract_total_time(self) -> Optional[str]:
        """Общее время из блока 'Tietoja reseptistä' (valmistusaika)."""
        items = self._extract_about_recipe_items()
        # 'valmistusaika' = cook/total time on this site
        val = items.get('valmistusaika')
        if val:
            return self.clean_text(val)

        # Fallback: JSON-LD cookTime
        ld = self._get_recipe_json_ld()
        if ld and ld.get('cookTime'):
            return self.clean_text(ld['cookTime'])

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки — не указывается на сайте, возвращает None."""
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Время готовки — не указывается отдельно на сайте, возвращает None."""
        return None

    # ------------------------------------------------------------------
    # Category
    # ------------------------------------------------------------------

    def extract_category(self) -> Optional[str]:
        """
        Категория рецепта из JSON-LD recipeCategory.
        На сайте поле обычно пустое, возвращает None.
        """
        ld = self._get_recipe_json_ld()
        if ld:
            cat = ld.get('recipeCategory', '')
            if cat:
                return self.clean_text(cat)
        return None

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------

    def extract_notes(self) -> Optional[str]:
        """Заметки из третьей вкладки (lisätietoja / Tab 3)."""
        richtext = self._tab_richtext(2)
        if not richtext:
            return None

        parts: list[str] = []
        for tag in richtext.find_all(['p', 'li']):
            text = self.clean_text(tag.get_text(separator=' ', strip=True))
            if text:
                parts.append(text)

        return ' '.join(parts) if parts else None

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def extract_tags(self) -> Optional[str]:
        """
        Теги рецепта. Сайт не содержит явных тегов,
        пробуем извлечь из мета-тега keywords.
        """
        keywords = self.soup.find('meta', {'name': 'keywords'})
        if keywords and keywords.get('content'):
            tags = [t.strip() for t in keywords['content'].split(',') if t.strip()]
            if tags:
                return ', '.join(tags)

        ld = self._get_recipe_json_ld()
        if ld and ld.get('keywords'):
            kw = ld['keywords']
            if isinstance(kw, list):
                tags = [str(k).strip() for k in kw if str(k).strip()]
            else:
                tags = [t.strip() for t in str(kw).split(',') if t.strip()]
            if tags:
                return ', '.join(tags)

        return None

    # ------------------------------------------------------------------
    # Image URLs
    # ------------------------------------------------------------------

    def extract_image_urls(self) -> Optional[str]:
        """URL изображений рецепта (og:image, JSON-LD image, card-image)."""
        urls: List[str] = []
        seen: Set[str] = set()

        def _add(url: str) -> None:
            url = url.strip()
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        # 1. og:image meta
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            _add(og_image['content'])

        # 2. JSON-LD image
        ld = self._get_recipe_json_ld()
        if ld and ld.get('image'):
            img = ld['image']
            if isinstance(img, str):
                _add(img)
            elif isinstance(img, list):
                for i in img:
                    if isinstance(i, str):
                        _add(i)
                    elif isinstance(i, dict):
                        _add(i.get('url', '') or i.get('contentUrl', ''))
            elif isinstance(img, dict):
                _add(img.get('url', '') or img.get('contentUrl', ''))

        # 3. First card-image within the recipe wrapper (not sidebar/listing)
        recipe_wrapper = self.soup.find('div', class_='main-recipe-card')
        if recipe_wrapper is None:
            recipe_wrapper = self.soup.find('div', class_='recipe-details-wrapper')
        if recipe_wrapper:
            card_img = recipe_wrapper.find('img', class_='card-image')
            if card_img and card_img.get('src'):
                _add(card_img['src'])

        return ','.join(urls) if urls else None

    # ------------------------------------------------------------------
    # extract_all
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """
        Извлекает все данные рецепта и возвращает словарь.
        Все поля присутствуют; отсутствующие данные — None.
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
            instructions = self.extract_steps()
        except Exception as e:
            logger.error("Error extracting instructions: %s", e)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as e:
            logger.error("Error extracting category: %s", e)
            category = None

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
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": image_urls,
        }


def main() -> None:
    """Обрабатывает директорию preprocessed/parastapoytaan_fi."""
    import os
    recipes_dir = os.path.join("preprocessed", "parastapoytaan_fi")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(ParastapoytaanFiExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python parastapoytaan_fi.py")


if __name__ == "__main__":
    main()
