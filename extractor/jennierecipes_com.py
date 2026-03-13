"""
Экстрактор данных рецептов для сайта jennierecipes.com
Сайт использует плагин Tasty Recipes (WordPress), поэтому данные хорошо
структурированы в блоке div.tasty-recipes и в JSON-LD разметке.
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


class JennieRecipesComExtractor(BaseRecipeExtractor):
    """Экстрактор для jennierecipes.com (Tasty Recipes plugin)"""

    # ------------------------------------------------------------------ #
    # Вспомогательные методы
    # ------------------------------------------------------------------ #

    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Возвращает первый JSON-LD блок с @type == 'Recipe' или None."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                # Прямой Recipe объект
                if isinstance(data, dict):
                    if data.get('@type') == 'Recipe':
                        return data
                    # Граф объектов
                    for item in data.get('@graph', []):
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                # Список объектов
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
            except (json.JSONDecodeError, KeyError):
                continue
        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в человеко-читаемую строку.
        Например: "PT15M" -> "15 minutes", "PT1H30M" -> "1 hour 30 minutes".
        """
        if not duration or not duration.startswith('PT'):
            return None

        body = duration[2:]  # убираем "PT"
        hours = 0
        minutes = 0

        hour_match = re.search(r'(\d+)H', body)
        if hour_match:
            hours = int(hour_match.group(1))

        min_match = re.search(r'(\d+)M', body)
        if min_match:
            minutes = int(min_match.group(1))

        parts = []
        if hours:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")

        return ' '.join(parts) if parts else None

    # ------------------------------------------------------------------ #
    # Извлечение отдельных полей
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из заголовка блока Tasty Recipes."""
        # Основной заголовок в блоке рецепта
        title_tag = self.soup.find('h2', class_='tasty-recipes-title')
        if title_tag:
            return self.clean_text(title_tag.get_text())

        # Запасной вариант: h1 страницы
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        # og:title мета-тег
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания из блока Tasty Recipes."""
        # Тело описания из блока рецепта
        desc_body = self.soup.find('div', class_='tasty-recipes-description-body')
        if desc_body:
            text = self.clean_text(desc_body.get_text(separator=' '))
            if text:
                return text

        # JSON-LD description
        recipe_ld = self._get_recipe_json_ld()
        if recipe_ld and recipe_ld.get('description'):
            return self.clean_text(recipe_ld['description'])

        # meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из блока Tasty Recipes.
        Каждый <li> содержит span с атрибутами data-amount / data-unit
        и текстовый узел с оставшейся частью (единица измерения + название),
        а также input[aria-label] с полной строкой ингредиента.
        """
        ingredients = []

        container = self.soup.find('div', class_='tasty-recipes-ingredients')
        if not container:
            logger.warning("Не найден блок tasty-recipes-ingredients, пробуем JSON-LD")
            return self._extract_ingredients_from_json_ld()

        items = container.find_all('li')
        for item in items:
            parsed = self._parse_ingredient_li(item)
            if parsed:
                ingredients.append(parsed)

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        # Запасной вариант — JSON-LD recipeIngredient
        return self._extract_ingredients_from_json_ld()

    def _parse_ingredient_li(self, item) -> Optional[dict]:
        """Разбирает один <li> ингредиента в {'name', 'amount', 'unit'}."""
        # Предпочтительный источник: aria-label="1 cup heavy cream"
        input_tag = item.find('input', attrs={'aria-label': True})
        full_text = input_tag['aria-label'] if input_tag else None

        # Structured data: span с data-amount / data-unit
        amount_span = item.find('span', attrs={'data-amount': True})
        amount = None
        unit_from_span = None
        if amount_span:
            amount = amount_span.get('data-amount') or None
            unit_from_span = amount_span.get('data-unit') or None

        if full_text:
            return self._parse_ingredient_text(
                full_text, amount_override=amount, unit_override=unit_from_span
            )

        # Если aria-label отсутствует, собираем текст вручную
        raw_text = item.get_text(separator=' ', strip=True)
        raw_text = self.clean_text(raw_text)
        if raw_text:
            return self._parse_ingredient_text(
                raw_text, amount_override=amount, unit_override=unit_from_span
            )

        return None

    def _parse_ingredient_text(
        self,
        text: str,
        amount_override: Optional[str] = None,
        unit_override: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Парсит строку ингредиента и возвращает {'name', 'amount', 'unit'}.
        Если переданы amount_override / unit_override, они имеют приоритет.
        """
        if not text:
            return None

        cleaned = self.clean_text(text)

        # Заменяем Unicode дроби
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
        }
        for frac, rep in fraction_map.items():
            cleaned = cleaned.replace(frac, rep)

        UNITS = (
            r'cups?|tablespoons?|teaspoons?|tbsps?|tsps?|'
            r'pounds?|lbs?|ounces?|oz|grams?|g|kilograms?|kg|'
            r'milliliters?|ml|liters?|l|'
            r'cloves?|pieces?|slices?|bunches?|sprigs?|heads?|'
            r'cans?|jars?|packages?|bags?|bottles?|'
            r'pinch(?:es)?|dash(?:es)?|'
            r'medium|large|small|whole'
        )

        NUMBER = r'[\d]+(?:[./][\d]+)?(?:\s+[\d]+/[\d]+)?'

        pattern = re.compile(
            rf'^({NUMBER})?\s*({UNITS})?\s+(.+)',
            re.IGNORECASE,
        )

        amount = amount_override
        unit = unit_override
        name = cleaned

        match = pattern.match(cleaned)
        if match:
            parsed_amount, parsed_unit, parsed_name = match.groups()
            if amount is None:
                amount = parsed_amount.strip() if parsed_amount else None
            if unit is None:
                unit = parsed_unit.strip() if parsed_unit else None
            name = parsed_name.strip() if parsed_name else cleaned
        elif amount_override:
            # Убираем числовую часть из начала строки
            name_without_amount = re.sub(
                rf'^\s*{re.escape(str(amount_override))}\s*', '', cleaned
            ).strip()
            if name_without_amount:
                name = name_without_amount

        # Чистим название
        name = re.sub(r'\([^)]*\)', '', name)  # убираем скобки
        name = re.sub(
            r'\b(to taste|as needed|or more|if needed|optional|for garnish|for serving)\b',
            '',
            name,
            flags=re.IGNORECASE,
        )
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()

        if not name or len(name) < 2:
            return None

        return {'name': name, 'amount': amount, 'unit': unit}

    def _extract_ingredients_from_json_ld(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD recipeIngredient как запасной вариант."""
        recipe_ld = self._get_recipe_json_ld()
        if not recipe_ld:
            return None

        raw_list = recipe_ld.get('recipeIngredient', [])
        ingredients = []
        for raw in raw_list:
            if not raw:
                continue
            parsed = self._parse_ingredient_text(raw)
            if parsed:
                ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления из блока Tasty Recipes."""
        steps = []

        instr_div = self.soup.find('div', class_='tasty-recipes-instructions')
        if instr_div:
            # li с id="instruction-step-*"
            step_items = instr_div.find_all(
                'li', id=re.compile(r'instruction-step', re.I)
            )
            if not step_items:
                step_items = instr_div.find_all('li')

            for item in step_items:
                text = self.clean_text(item.get_text(separator=' '))
                if text:
                    steps.append(text)

            if steps:
                return ' '.join(steps)

        # Запасной вариант — JSON-LD recipeInstructions
        recipe_ld = self._get_recipe_json_ld()
        if recipe_ld:
            instructions = recipe_ld.get('recipeInstructions', [])
            for idx, step in enumerate(instructions, 1):
                if isinstance(step, dict):
                    text = step.get('text', '')
                elif isinstance(step, str):
                    text = step
                else:
                    continue
                text = self.clean_text(text)
                if text:
                    steps.append(f"{idx}. {text}")

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из блока Tasty Recipes."""
        cat_span = self.soup.find('span', class_='tasty-recipes-category')
        if cat_span:
            return self.clean_text(cat_span.get_text())

        # JSON-LD recipeCategory
        recipe_ld = self._get_recipe_json_ld()
        if recipe_ld and recipe_ld.get('recipeCategory'):
            cat = recipe_ld['recipeCategory']
            if isinstance(cat, list):
                return ', '.join(cat)
            return self.clean_text(str(cat))

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки."""
        span = self.soup.find('span', class_='tasty-recipes-prep-time')
        if span:
            return self.clean_text(span.get_text())

        recipe_ld = self._get_recipe_json_ld()
        if recipe_ld and recipe_ld.get('prepTime'):
            return self._parse_iso_duration(recipe_ld['prepTime'])

        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления."""
        span = self.soup.find('span', class_='tasty-recipes-cook-time')
        if span:
            return self.clean_text(span.get_text())

        recipe_ld = self._get_recipe_json_ld()
        if recipe_ld and recipe_ld.get('cookTime'):
            return self._parse_iso_duration(recipe_ld['cookTime'])

        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени приготовления."""
        span = self.soup.find('span', class_='tasty-recipes-total-time')
        if span:
            return self.clean_text(span.get_text())

        recipe_ld = self._get_recipe_json_ld()
        if recipe_ld and recipe_ld.get('totalTime'):
            return self._parse_iso_duration(recipe_ld['totalTime'])

        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок из блока Tasty Recipes."""
        notes_body = self.soup.find('div', class_='tasty-recipes-notes-body')
        if notes_body:
            text = self.clean_text(notes_body.get_text(separator=' '))
            if text:
                return text

        # Целый блок заметок (содержит заголовок "Notes", убираем его)
        notes_div = self.soup.find('div', class_='tasty-recipes-notes')
        if notes_div:
            text = notes_div.get_text(separator=' ', strip=True)
            text = re.sub(r'^Notes\s*', '', text, flags=re.IGNORECASE)
            text = self.clean_text(text)
            if text:
                return text

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords или блока Tasty Recipes."""
        # Приоритет: JSON-LD keywords
        recipe_ld = self._get_recipe_json_ld()
        if recipe_ld:
            keywords = recipe_ld.get('keywords', '')
            if keywords and str(keywords).strip().lower() not in ('', 'empty', 'none'):
                return self.clean_text(str(keywords))

        # HTML блок с ключевыми словами
        kw_div = self.soup.find('div', class_='tasty-recipes-keywords')
        if kw_div:
            # Убираем метку "Keywords:"
            span_label = kw_div.find('span', class_='tasty-recipes-label')
            if span_label:
                span_label.extract()
            text = self.clean_text(kw_div.get_text(separator=' '))
            if text and text.lower() not in ('empty', 'none', ''):
                return text

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта."""
        urls: list[str] = []

        # 1. JSON-LD Recipe image (наиболее точные)
        recipe_ld = self._get_recipe_json_ld()
        if recipe_ld:
            img = recipe_ld.get('image')
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend(i for i in img if isinstance(i, str))
            elif isinstance(img, dict):
                url = img.get('url') or img.get('contentUrl')
                if url:
                    urls.append(url)

        # 2. og:image мета-тег
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # 3. Изображения внутри блока tasty-recipes-image
        img_div = self.soup.find('div', class_='tasty-recipes-image')
        if img_div:
            for img_tag in img_div.find_all('img'):
                src = img_tag.get('src') or img_tag.get('data-src')
                if src:
                    urls.append(src)

        # Дедупликация с сохранением порядка
        seen: set[str] = set()
        unique_urls: list[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ','.join(unique_urls) if unique_urls else None

    # ------------------------------------------------------------------ #
    # Главный метод
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта.
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_steps()
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
            "image_urls": self.extract_image_urls(),
            "tags": tags,
        }


def main():
    """Точка входа для обработки директории с HTML файлами."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "jennierecipes_com")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(JennieRecipesComExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python jennierecipes_com.py")


if __name__ == "__main__":
    main()
