"""
Экстрактор данных рецептов для сайта lovefoodfeed.com
"""

import sys
from pathlib import Path
import copy
import json
import re
import logging
from typing import Optional, Union

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class LoveFoodFeedExtractor(BaseRecipeExtractor):
    """Экстрактор для lovefoodfeed.com (WP Recipe Maker plugin)"""

    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение данных JSON-LD Recipe из страницы"""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, KeyError):
                continue
        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в формат "X minutes"

        Args:
            duration: строка вида "PT20M" или "PT1H30M"

        Returns:
            Время в формате "20 minutes" или "90 minutes"
        """
        if not duration or not duration.startswith('PT'):
            return None

        body = duration[2:]  # Убираем "PT"

        hours = 0
        minutes = 0

        hour_match = re.search(r'(\d+)H', body)
        if hour_match:
            hours = int(hour_match.group(1))

        min_match = re.search(r'(\d+)M', body)
        if min_match:
            minutes = int(min_match.group(1))

        total_minutes = hours * 60 + minutes
        if total_minutes == 0:
            return None

        unit = 'minute' if total_minutes == 1 else 'minutes'
        return f"{total_minutes} {unit}"

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_recipe()
        if json_ld and json_ld.get('name'):
            return self.clean_text(json_ld['name'])

        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        json_ld = self._get_json_ld_recipe()
        if json_ld and json_ld.get('description'):
            return self.clean_text(json_ld['description'])

        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        return None

    def _parse_amount(self, amount_str: str) -> Optional[Union[int, float, str]]:
        """
        Парсинг строки количества в число или строку

        Args:
            amount_str: строка с количеством (может содержать дроби)

        Returns:
            Число или строку
        """
        if not amount_str:
            return None

        # Словарь Unicode-дробей
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5'
        }
        text = amount_str.strip()
        for frac, replacement in fraction_map.items():
            text = text.replace(frac, replacement)

        text = text.replace(',', '.')

        if '/' in text:
            parts = text.split()
            total = 0.0
            for part in parts:
                if '/' in part:
                    try:
                        num, denom = part.split('/', 1)
                        total += float(num) / float(denom)
                    except (ValueError, ZeroDivisionError):
                        return amount_str
                else:
                    try:
                        total += float(part)
                    except ValueError:
                        return amount_str
            return int(total) if total == int(total) else total

        try:
            val = float(text)
            return int(val) if val == int(val) else val
        except ValueError:
            return amount_str if amount_str.strip() else None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из WPRM HTML (с резервным вариантом на JSON-LD).
        Возвращает JSON-строку со списком словарей {name, amount, unit}.
        """
        ingredients = []

        # Основной метод: WPRM ingredient list items
        ingredient_items = self.soup.find_all(
            'li', class_='wprm-recipe-ingredient'
        )

        if ingredient_items:
            for item in ingredient_items:
                amount_el = item.find(class_='wprm-recipe-ingredient-amount')
                unit_el = item.find(class_='wprm-recipe-ingredient-unit')
                name_el = item.find(class_='wprm-recipe-ingredient-name')

                if not name_el:
                    continue

                name = self.clean_text(name_el.get_text())
                if not name:
                    continue

                raw_amount = amount_el.get_text().strip() if amount_el else None
                amount = self._parse_amount(raw_amount) if raw_amount else None

                unit = self.clean_text(unit_el.get_text()) if unit_el else None

                ingredients.append({
                    "name": name,
                    "unit": unit,
                    "amount": amount
                })

        # Резервный метод: JSON-LD recipeIngredient
        if not ingredients:
            json_ld = self._get_json_ld_recipe()
            if json_ld and json_ld.get('recipeIngredient'):
                for ingredient_text in json_ld['recipeIngredient']:
                    parsed = self._parse_ingredient_string(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def _parse_ingredient_string(self, text: str) -> Optional[dict]:
        """Парсинг строки ингредиента из JSON-LD в структурированный формат"""
        if not text:
            return None

        text = self.clean_text(text)

        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
        }
        for frac, decimal in fraction_map.items():
            text = text.replace(frac, decimal)

        pattern = (
            r'^([\d\s/.,]+)?\s*'
            r'(cups?|tablespoons?|tbsps?|teaspoons?|tsps?|pounds?|lbs?|'
            r'ounces?|oz|grams?|g|kilograms?|kg|milliliters?|ml|liters?|l|'
            r'pinch(?:es)?|dash(?:es)?|pieces?|slices?|cloves?|bunches?|'
            r'sprigs?|whole|heads?|cans?|jars?)?\s*(.+)'
        )
        match = re.match(pattern, text, re.IGNORECASE)
        if not match:
            return {"name": text, "amount": None, "unit": None}

        amount_str, units, name = match.groups()

        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0.0
                for part in parts:
                    if '/' in part:
                        try:
                            n, d = part.split('/')
                            total += float(n) / float(d)
                        except (ValueError, ZeroDivisionError):
                            pass
                    else:
                        try:
                            total += float(part)
                        except ValueError:
                            pass
                amount = int(total) if total == int(total) else total
            else:
                try:
                    val = float(amount_str.replace(',', '.'))
                    amount = int(val) if val == int(val) else val
                except ValueError:
                    amount = amount_str

        units = units.strip() if units else None

        # Очистка названия
        name = re.sub(r'\([^)]*\)', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        name = re.sub(r'[,;]+$', '', name).strip()

        if not name or len(name) < 2:
            return None

        return {"name": name, "amount": amount, "unit": units}

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления из JSON-LD"""
        json_ld = self._get_json_ld_recipe()
        if not json_ld:
            return None

        instructions = json_ld.get('recipeInstructions')
        if not instructions:
            return None

        steps = []
        if isinstance(instructions, list):
            for step in instructions:
                if isinstance(step, dict) and step.get('text'):
                    steps.append(self.clean_text(step['text']))
                elif isinstance(step, str):
                    steps.append(self.clean_text(step))
        elif isinstance(instructions, str):
            steps.append(self.clean_text(instructions))

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из WPRM course элемента"""
        # WPRM course (translated)
        course_el = self.soup.find('span', class_='wprm-recipe-course')
        if course_el:
            text = self.clean_text(course_el.get_text())
            if text:
                return text

        # Резервный вариант: JSON-LD recipeCategory
        json_ld = self._get_json_ld_recipe()
        if json_ld:
            category = json_ld.get('recipeCategory')
            if category:
                if isinstance(category, list):
                    return ', '.join(category)
                return str(category)

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self._get_json_ld_recipe()
        if json_ld and json_ld.get('prepTime'):
            return self._parse_iso_duration(json_ld['prepTime'])
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_recipe()
        if json_ld and json_ld.get('cookTime'):
            return self._parse_iso_duration(json_ld['cookTime'])
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_recipe()
        if json_ld and json_ld.get('totalTime'):
            return self._parse_iso_duration(json_ld['totalTime'])
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок из WPRM notes контейнера"""
        notes_div = self.soup.find('div', class_='wprm-recipe-notes')
        if not notes_div:
            return None

        # Работаем с глубокой копией чтобы не изменять оригинальный документ
        notes_copy = copy.deepcopy(notes_div)

        # Удаляем разделители (wprm-spacer)
        for spacer in notes_copy.find_all(class_='wprm-spacer'):
            spacer.decompose()

        # Если есть список — берём элементы списка (самый структурированный вариант)
        list_items = notes_copy.find_all('li')
        if list_items:
            parts = [self.clean_text(li.get_text()) for li in list_items]
            parts = [p for p in parts if p]
            if parts:
                return ' '.join(parts)

        # Иначе собираем текст из span[style*="display: block"]
        block_spans = notes_copy.find_all(
            'span', style=lambda s: s and 'display: block' in s
        )
        if block_spans:
            texts = [self.clean_text(s.get_text()) for s in block_spans if s.get_text().strip()]
            # Пропускаем первый span если он похож на заголовок (короткий, без знаков препинания)
            if texts and len(texts[0]) < 40 and not re.search(r'[.,;!?]', texts[0]):
                texts = texts[1:]
            result = ' '.join(t for t in texts if t)
            return result if result else None

        # Последний резерв — весь текст блока
        text = self.clean_text(notes_copy.get_text(separator=' ', strip=True))
        return text if text else None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из WPRM keyword элемента"""
        keyword_el = self.soup.find('span', class_='wprm-recipe-keyword')
        if keyword_el:
            text = self.clean_text(keyword_el.get_text())
            if text:
                return text

        # Резервный вариант: JSON-LD keywords
        json_ld = self._get_json_ld_recipe()
        if json_ld and json_ld.get('keywords'):
            return self.clean_text(str(json_ld['keywords']))

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из JSON-LD и мета-тегов"""
        urls = []

        json_ld = self._get_json_ld_recipe()
        if json_ld and json_ld.get('image'):
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        url = item.get('url') or item.get('contentUrl')
                        if url:
                            urls.append(url)
            elif isinstance(img, dict):
                url = img.get('url') or img.get('contentUrl')
                if url:
                    urls.append(url)

        # Резервный вариант: og:image
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])

        if not urls:
            return None

        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ','.join(unique_urls) if unique_urls else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта

        Returns:
            Словарь с данными рецепта
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags(),
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "lovefoodfeed_com")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(LoveFoodFeedExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python lovefoodfeed_com.py")


if __name__ == "__main__":
    main()