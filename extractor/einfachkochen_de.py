"""
Экстрактор данных рецептов для сайта einfachkochen.de
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


class EinfachkochenDeExtractor(BaseRecipeExtractor):
    """Экстрактор для einfachkochen.de"""

    # Fraction characters → decimal equivalents
    _FRACTION_MAP = {
        '½': 0.5, '¼': 0.25, '¾': 0.75,
        '⅓': 1/3, '⅔': 2/3, '⅛': 0.125,
        '⅜': 0.375, '⅝': 0.625, '⅞': 0.875,
        '⅕': 0.2, '⅖': 0.4, '⅗': 0.6, '⅘': 0.8,
    }

    # Generic keywords to exclude from tags
    _TAG_STOPWORDS = {
        'rezepte', 'anlässe', 'saison', 'lifestyle', 'gäste',
        'einfache rezepte', 'günstige rezepte', 'familienküche',
    }

    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение данных Recipe из JSON-LD (@graph или прямой объект)"""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, dict):
                    # Pattern: {"@graph": [...]}
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and item.get('@type') == 'Recipe':
                                return item
                    # Pattern: direct Recipe object
                    if data.get('@type') == 'Recipe':
                        return data
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            t = item.get('@type', '')
                            if t == 'Recipe' or (isinstance(t, list) and 'Recipe' in t):
                                return item
            except (json.JSONDecodeError, KeyError, TypeError):
                logger.debug("Failed to parse JSON-LD script", exc_info=True)
        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в строку вида 'X minutes'.

        Args:
            duration: строка вида "PT30M" или "PT1H30M"

        Returns:
            Строка вида "45 minutes" или None
        """
        if not duration or not duration.startswith('PT'):
            return None
        body = duration[2:]
        hours = 0
        minutes = 0
        h_match = re.search(r'(\d+)H', body)
        if h_match:
            hours = int(h_match.group(1))
        m_match = re.search(r'(\d+)M', body)
        if m_match:
            minutes = int(m_match.group(1))
        total = hours * 60 + minutes
        if total <= 0:
            return None
        return f"{total} minutes"

    def _parse_quantity(self, qty_text: str) -> Optional[float | int]:
        """
        Конвертирует строку количества в число.
        Поддерживает Unicode-дроби, обычные числа и диапазоны ('200 - 250' → 200).
        Возвращает int если значение целое, иначе float.
        """
        if not qty_text:
            return None
        text = qty_text.strip()
        # Replace unicode fractions
        for frac, val in self._FRACTION_MAP.items():
            text = text.replace(frac, str(val))
        # Take first number from a range like "200 - 250" or "1 - 2"
        range_match = re.match(r'^([\d.,]+)\s*[-–]\s*[\d.,]+$', text)
        if range_match:
            text = range_match.group(1)
        try:
            value = float(text.replace(',', '.'))
            # Return int when the value is a whole number
            return int(value) if value == int(value) else value
        except ValueError:
            return None

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда (только первая часть до ' - ' или ' – ')"""
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('name'):
            name = self.clean_text(recipe['name'])
            # Strip subtitle after ' - ' or ' – '
            name = re.split(r'\s+[-–]\s+', name, maxsplit=1)[0]
            return name

        h1 = self.soup.find('h1')
        if h1:
            name = self.clean_text(h1.get_text())
            name = re.split(r'\s+[-–]\s+', name, maxsplit=1)[0]
            return name

        logger.warning("dish_name not found in %s", self.html_path)
        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('description'):
            return self.clean_text(recipe['description'])

        meta = self.soup.find('meta', attrs={'name': 'description'})
        if meta and meta.get('content'):
            return self.clean_text(meta['content'])

        og = self.soup.find('meta', property='og:description')
        if og and og.get('content'):
            return self.clean_text(og['content'])

        logger.warning("description not found in %s", self.html_path)
        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из структурированного HTML.

        Каждый ингредиент — словарь {"name": ..., "amount": ..., "unit": ...}.
        Возвращает JSON-строку со списком ингредиентов.
        """
        ingredients = []

        # Collect all ingredient sections (there may be multiple for sub-groups)
        sections = self.soup.find_all('div', class_='recipe--full__ingredients')
        if not sections:
            # Fallback: look for any ingredients-wrapper on the page (deduplicate by position)
            sections = [self.soup]

        seen_names = set()
        for section in sections:
            wrappers = section.find_all('div', class_='ingredients-wrapper')
            for wrapper in wrappers:
                qty_span = wrapper.find('span', class_='ingredients__quantity')
                unit_span = wrapper.find('span', class_='ingredients__unit')
                prefix_span = wrapper.find('span', class_='ingredient_prefix')
                name_span = wrapper.find('span', class_='ingredient')

                if not name_span:
                    continue

                name = self.clean_text(name_span.get_text())
                if not name:
                    continue

                # Deduplicate (ingredients can appear twice in the page)
                if name in seen_names:
                    continue
                seen_names.add(name)

                # Amount
                qty_text = qty_span.get_text(strip=True) if qty_span else ''
                amount = self._parse_quantity(qty_text)

                # Unit: use the unit span if it has text; otherwise fall back to prefix
                unit_text = unit_span.get_text(strip=True) if unit_span else ''
                if unit_text:
                    unit = unit_text
                elif prefix_span:
                    unit = self.clean_text(prefix_span.get_text())
                else:
                    unit = None

                # Suffix handling (e.g. "(zerdrückt und geschält)" or "(Größe M)")
                suffix_span = wrapper.find('span', class_='suffix')
                suffix = self.clean_text(suffix_span.get_text()) if suffix_span else ''
                if suffix and not unit_text:
                    # When there's no proper unit and a suffix exists, put it in unit
                    unit = suffix if not unit else unit

                ingredient = {
                    "name": name,
                    "amount": amount,
                    "unit": unit if unit else None,
                }
                ingredients.append(ingredient)

        if not ingredients:
            logger.warning("ingredients not found in %s, falling back to JSON-LD", self.html_path)
            ingredients = self._extract_ingredients_from_json_ld()

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def _extract_ingredients_from_json_ld(self) -> list:
        """Запасной вариант: парсинг ингредиентов из recipeIngredient в JSON-LD"""
        recipe = self._get_recipe_json_ld()
        if not recipe or 'recipeIngredient' not in recipe:
            return []
        result = []
        for item_text in recipe['recipeIngredient']:
            text = self.clean_text(item_text)
            if not text:
                continue
            # Try to split "amount unit name" for known German units
            pattern = (
                r'^([\d.,½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘\s/]+)?'
                r'\s*(g|ml|EL|TL|Pck\.|Prise|Stange|Bund|Scheibe|Stück|kg|l)?\s*'
                r'(.+)$'
            )
            m = re.match(pattern, text, re.IGNORECASE)
            if m:
                amt_str, unit, name = m.groups()
                amount = self._parse_quantity(amt_str) if amt_str else None
                result.append({
                    "name": self.clean_text(name),
                    "amount": amount,
                    "unit": unit.strip() if unit else None,
                })
            else:
                result.append({"name": text, "amount": None, "unit": None})
        return result

    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        recipe = self._get_recipe_json_ld()
        if recipe and 'recipeInstructions' in recipe:
            instructions = recipe['recipeInstructions']
            steps = []
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        steps.append(self.clean_text(step['text']))
                    elif isinstance(step, str):
                        steps.append(self.clean_text(step))
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            if steps:
                # Steps may already be numbered (e.g. "1. ..."); join as-is
                return ' '.join(steps)

        # Fallback: look for HTML instruction list
        for container in [
            self.soup.find('ol', class_=re.compile(r'instruction', re.I)),
            self.soup.find('div', class_=re.compile(r'instruction', re.I)),
        ]:
            if not container:
                continue
            items = container.find_all('li') or container.find_all('p')
            step_texts = [self.clean_text(i.get_text(separator=' ', strip=True)) for i in items]
            step_texts = [s for s in step_texts if s]
            if step_texts:
                if not re.match(r'^\d+\.', step_texts[0]):
                    step_texts = [f"{idx}. {s}" for idx, s in enumerate(step_texts, 1)]
                return ' '.join(step_texts)

        logger.warning("instructions not found in %s", self.html_path)
        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда из кикера заголовка"""
        kicker = self.soup.find(class_='recipe--heading__kicker')
        if kicker:
            text = self.clean_text(kicker.get_text())
            if text:
                return text

        # Fallback: recipeCategory from JSON-LD
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('recipeCategory'):
            return self.clean_text(str(recipe['recipeCategory']))

        logger.debug("category not found in %s", self.html_path)
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe = self._get_recipe_json_ld()
        if recipe:
            return self._parse_iso_duration(recipe.get('prepTime', ''))
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe = self._get_recipe_json_ld()
        if recipe:
            return self._parse_iso_duration(recipe.get('cookTime', ''))
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe = self._get_recipe_json_ld()
        if recipe:
            return self._parse_iso_duration(recipe.get('totalTime', ''))
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов из блока «Mein Tipp»"""
        tipbox = self.soup.find('div', class_='paragraph-tipbox')
        if tipbox:
            title_el = tipbox.find(class_='paragraph-tipbox__content__title')
            text_el = tipbox.find(class_='paragraph-tipbox__text')

            parts = []
            if title_el:
                title_text = self.clean_text(title_el.get_text())
                # Strip trailing ellipsis-like characters
                title_text = re.sub(r'[.…]+$', '', title_text).strip()
                if title_text:
                    parts.append(title_text)
            if text_el:
                text = self.clean_text(text_el.get_text(separator=' ', strip=True))
                if text:
                    parts.append(text)

            if parts:
                return ' '.join(parts)

        logger.debug("notes not found in %s", self.html_path)
        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из ключевых слов JSON-LD (keywords)"""
        recipe = self._get_recipe_json_ld()
        if not recipe:
            return None

        keywords_raw = recipe.get('keywords', '')
        if not keywords_raw:
            return None

        # Keywords is a comma-separated string
        tags = [t.strip() for t in keywords_raw.split(',') if t.strip()]

        # Filter out stopwords and ingredient names (single-word ingredient names
        # appear after the special separators in the keywords list; we keep
        # category-level keywords which are multi-word or recognisable categories).
        filtered = []
        seen = set()
        for tag in tags:
            low = tag.lower()
            if low in self._TAG_STOPWORDS:
                continue
            if len(tag) < 3:
                continue
            if low in seen:
                continue
            seen.add(low)
            filtered.append(tag)

        return ', '.join(filtered) if filtered else None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls: list[str] = []

        # 1. og:image meta tag
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # 2. JSON-LD image field
        recipe = self._get_recipe_json_ld()
        if recipe and 'image' in recipe:
            img = recipe['image']
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

        # Deduplicate preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта
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
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": self.extract_image_urls(),
        }


def main():
    """Точка входа: обработка всех HTML-файлов из preprocessed/einfachkochen_de"""
    repo_root = Path(__file__).parent.parent
    directory = repo_root / 'preprocessed' / 'einfachkochen_de'

    if directory.exists():
        process_directory(EinfachkochenDeExtractor, str(directory))
    else:
        print(f"Directory not found: {directory}")


if __name__ == '__main__':
    main()
