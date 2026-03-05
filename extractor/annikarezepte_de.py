"""
Экстрактор данных рецептов для сайта annikarezepte.de
Сайт использует плагин WP Recipe Maker (WPRM) и JSON-LD Schema.org.
"""

import sys
from pathlib import Path
import json
import logging
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Немецкие единицы измерения, которые могут оказаться в начале поля «name» в WPRM
_DE_UNIT_WORDS = {
    'esslöffel', 'el', 'teelöffel', 'tl', 'tasse', 'tassen',
    'stück', 'stücke', 'stücken',
    'dose', 'dosen', 'glas', 'gläser',
    'liter', 'l', 'milliliter', 'ml',
    'kilogramm', 'kg', 'gramm', 'g', 'mg',
    'prise', 'prisen', 'päckchen', 'paket', 'pakete',
    'bund', 'zweig', 'zweige', 'zehe', 'zehen',
    'scheibe', 'scheiben', 'stiel', 'stiele',
    'becher', 'pkg',
}

# Специальные «единицы» в конце строки без количества
_DE_SUFFIX_UNITS = [
    'nach geschmack',
    'zur garnitur',
    'nach bedarf',
    'zum frittieren',
    'zum braten',
    'zum bestreuen',
    'zum bestreichen',
    'zum anbraten',
    'optional',
]


class AnnikaRezepteExtractor(BaseRecipeExtractor):
    """Экстрактор для annikarezepte.de (использует WPRM и JSON-LD)"""

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _get_recipe_jsonld(self) -> Optional[dict]:
        """
        Возвращает объект Recipe из JSON-LD (ищет в @graph и напрямую).
        """
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
            except (json.JSONDecodeError, TypeError):
                continue

            # Случай 1: объект с @graph
            if isinstance(data, dict) and '@graph' in data:
                for item in data['@graph']:
                    if self._is_recipe(item):
                        return item

            # Случай 2: список на верхнем уровне
            if isinstance(data, list):
                for item in data:
                    if self._is_recipe(item):
                        return item

            # Случай 3: одиночный объект Recipe
            if isinstance(data, dict) and self._is_recipe(data):
                return data

        return None

    @staticmethod
    def _is_recipe(item: dict) -> bool:
        """Проверяет, является ли элемент JSON-LD рецептом."""
        if not isinstance(item, dict):
            return False
        item_type = item.get('@type', '')
        if isinstance(item_type, list):
            return 'Recipe' in item_type
        return item_type == 'Recipe'

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в строку «N minutes».

        Args:
            duration: строка вида «PT20M» или «PT1H30M»

        Returns:
            Строка вида «90 minutes» или None
        """
        if not duration or not duration.startswith('PT'):
            return None

        body = duration[2:]  # убираем «PT»
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

    def _parse_wprm_ingredient(self, li_tag) -> Optional[dict]:
        """
        Разбирает элемент <li class="wprm-recipe-ingredient"> на поля
        name / amount / unit.

        Логика:
          1. Берём явные поля amount, unit, name из WPRM-spans.
          2. Если unit явно не задан, проверяем первое слово name:
             если оно — известная немецкая единица, выносим его в unit.
          3. Если name — контейнер («Dose») с notes, берём имя ингредиента
             из notes.
          4. Обрабатываем специальные суффиксы («nach Geschmack» и т.п.)
             как unit при отсутствии количества.

        Returns:
            dict с полями name, amount, unit или None
        """
        # ---- Извлекаем сырые значения ----
        amount_span = li_tag.find(class_='wprm-recipe-ingredient-amount')
        unit_span = li_tag.find(class_='wprm-recipe-ingredient-unit')
        name_span = li_tag.find(class_='wprm-recipe-ingredient-name')
        notes_span = li_tag.find(class_='wprm-recipe-ingredient-notes')

        raw_amount = self.clean_text(amount_span.get_text()) if amount_span else None
        raw_unit = self.clean_text(unit_span.get_text()) if unit_span else None
        raw_name = self.clean_text(name_span.get_text()) if name_span else None
        raw_notes = self.clean_text(notes_span.get_text()) if notes_span else None

        if not raw_name and not raw_amount:
            return None

        # ---- Нормализуем количество ----
        amount = self._normalize_amount(raw_amount)

        # ---- Разбираем unit / name ----
        unit = raw_unit  # может быть None
        name = raw_name or ''

        if not unit and name:
            name_lower = name.lower()

            # Случай: name содержит только название контейнера («Dose») +
            # notes содержат размер и реальный ингредиент
            # Пример: name="Dose", notes="425 g weiße Bohnen, abgetropft"
            if name_lower in ('dose', 'dosen', 'glas', 'gläser', 'becher') and raw_notes:
                size_match = re.match(r'^(\d+[\d.,]*\s*(?:g|kg|ml|l))\s+(.+)$', raw_notes, re.IGNORECASE)
                if size_match:
                    size_str = size_match.group(1).strip()
                    remainder = size_match.group(2).strip()
                    # Убираем лишние комментарии после запятой
                    ingredient_name = re.split(r',\s*', remainder)[0].strip()
                    unit = f"{name} ({size_str})"
                    name = ingredient_name
                else:
                    # notes есть, но формат другой — берём notes как имя
                    ingredient_name = re.split(r',\s*', raw_notes)[0].strip()
                    unit = name
                    name = ingredient_name
            else:
                # Проверяем, не начинается ли name с немецкой единицы
                first_word = name.split()[0].lower() if name.split() else ''
                if first_word in _DE_UNIT_WORDS:
                    unit = name.split()[0]
                    name = name[len(unit):].strip()

        # Случай без количества: «Salz und Pfeffer nach Geschmack»
        if amount is None and not unit and name:
            name_lower = name.lower()
            for suffix in _DE_SUFFIX_UNITS:
                if name_lower.endswith(suffix):
                    unit = name[len(name) - len(suffix):].strip()
                    name = name[: len(name) - len(suffix)].strip()
                    break

        name = self.clean_text(name) if name else None
        if not name:
            return None

        return {'name': name, 'amount': amount, 'unit': unit}

    @staticmethod
    def _normalize_amount(raw: Optional[str]):
        """
        Нормализует строку количества в число или строку.

        Returns:
            int / float / None
        """
        if not raw:
            return None

        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.333', '⅔': '0.667', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
        }
        text = raw.strip()
        for frac, dec in fraction_map.items():
            text = text.replace(frac, dec)

        text = text.replace(',', '.')

        try:
            # «1 0.5» → 1.5
            parts = text.split()
            total = sum(float(p) for p in parts)
            return int(total) if total == int(total) else total
        except (ValueError, OverflowError):
            return raw  # возвращаем как строку если не распознали

    # ------------------------------------------------------------------
    # Методы извлечения полей
    # ------------------------------------------------------------------

    def _extract_wprm_time(self, time_type: str) -> Optional[str]:
        """
        Извлекает время из WPRM-spans (fallback, когда JSON-LD недоступен).

        Args:
            time_type: «prep_time», «cook_time» или «total_time»

        Returns:
            Строка вида «15 minutes» или None
        """
        # WPRM хранит значение в минутах в span с классом wprm-recipe-<type>-minutes
        minutes_span = self.soup.find(class_=re.compile(
            rf'wprm-recipe-{time_type}-minutes', re.I
        ))
        if minutes_span:
            # Текст содержит число и скрытый span «minutes» — берём только число
            raw = minutes_span.find(string=True, recursive=False)
            if raw:
                raw = raw.strip()
                if raw.isdigit():
                    return f"{raw} minutes"
        return None

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('name'):
            return self.clean_text(recipe['name'])

        # WPRM fallback
        wprm_name = self.soup.find(class_='wprm-recipe-name')
        if wprm_name:
            return self.clean_text(wprm_name.get_text())

        # Резервный вариант — h1 на странице
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('description'):
            return self.clean_text(recipe['description'])

        # Резервный вариант — meta description
        meta = self.soup.find('meta', attrs={'name': 'description'})
        if meta and meta.get('content'):
            return self.clean_text(meta['content'])

        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из WPRM-разметки.
        Каждый ингредиент — словарь {name, amount, unit}.
        """
        ingredients = []

        for li in self.soup.find_all('li', class_='wprm-recipe-ingredient'):
            try:
                parsed = self._parse_wprm_ingredient(li)
                if parsed:
                    ingredients.append(parsed)
            except Exception as exc:
                logger.warning("Ошибка при разборе ингредиента: %s", exc)

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        # Резервный вариант — recipeIngredient из JSON-LD
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('recipeIngredient'):
            from extractor.allrecipes_com import AllRecipesExtractor
            fallback = []
            for raw in recipe['recipeIngredient']:
                parsed = AllRecipesExtractor.parse_ingredient(None, raw)  # type: ignore[arg-type]
                if parsed:
                    fallback.append(parsed)
            if fallback:
                return json.dumps(fallback, ensure_ascii=False)

        return None

    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления из JSON-LD или WPRM HTML"""
        recipe = self._get_recipe_jsonld()
        if recipe:
            raw_instructions = recipe.get('recipeInstructions')
            if raw_instructions:
                steps = []
                if isinstance(raw_instructions, list):
                    for step in raw_instructions:
                        if isinstance(step, dict):
                            text = step.get('text') or step.get('name', '')
                        elif isinstance(step, str):
                            text = step
                        else:
                            continue
                        text = self.clean_text(text)
                        if text:
                            steps.append(text)
                elif isinstance(raw_instructions, str):
                    steps.append(self.clean_text(raw_instructions))

                if steps:
                    return ' '.join(steps)

        # WPRM HTML fallback
        wprm_steps = self.soup.find_all(class_='wprm-recipe-instruction-text')
        if wprm_steps:
            texts = [self.clean_text(s.get_text()) for s in wprm_steps]
            return ' '.join(t for t in texts if t) or None

        # Ещё один fallback — li элементы в wprm-recipe-instructions
        instr_list = self.soup.find(class_='wprm-recipe-instructions')
        if instr_list:
            items = [
                self.clean_text(li.get_text())
                for li in instr_list.find_all('li', class_='wprm-recipe-instruction')
            ]
            return ' '.join(i for i in items if i) or None

        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда"""
        recipe = self._get_recipe_jsonld()
        if recipe:
            cat = recipe.get('recipeCategory')
            if cat:
                if isinstance(cat, list):
                    return ', '.join(self.clean_text(c) for c in cat if c)
                return self.clean_text(str(cat))

        # WPRM fallback: wprm-recipe-course (курс блюда)
        course = self.soup.find(class_='wprm-recipe-course')
        if course:
            return self.clean_text(course.get_text())

        # Резервный вариант — meta article:section
        meta = self.soup.find('meta', property='article:section')
        if meta and meta.get('content'):
            return self.clean_text(meta['content'])

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('prepTime'):
            return self._parse_iso_duration(recipe['prepTime'])
        return self._extract_wprm_time('prep_time')

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('cookTime'):
            return self._parse_iso_duration(recipe['cookTime'])
        return self._extract_wprm_time('cook_time')

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени приготовления"""
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('totalTime'):
            return self._parse_iso_duration(recipe['totalTime'])
        return self._extract_wprm_time('total_time')

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок из блока WPRM notes"""
        notes_div = self.soup.find('div', class_='wprm-recipe-notes')
        if notes_div:
            text = self.clean_text(notes_div.get_text(separator=' '))
            return text if text else None

        # Резервный вариант — контейнер с notes
        notes_container = self.soup.find('div', class_='wprm-recipe-notes-container')
        if notes_container:
            # Убираем заголовок «Notizen»
            text = notes_container.get_text(separator=' ', strip=True)
            text = re.sub(r'^Notizen?\s*', '', text, flags=re.IGNORECASE).strip()
            return self.clean_text(text) if text else None

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из keywords в JSON-LD или WPRM HTML"""
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('keywords'):
            keywords = recipe['keywords']
            if isinstance(keywords, list):
                return ', '.join(k.strip() for k in keywords if k.strip())
            if isinstance(keywords, str):
                return self.clean_text(keywords)

        # WPRM HTML fallback
        kw_span = self.soup.find(class_='wprm-recipe-keyword')
        if kw_span:
            text = self.clean_text(kw_span.get_text())
            if text:
                return text

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из JSON-LD и мета-тегов"""
        urls = []

        # 1. JSON-LD Recipe.image
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('image'):
            img = recipe['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend(i for i in img if isinstance(i, str))
            elif isinstance(img, dict):
                url = img.get('url') or img.get('contentUrl')
                if url:
                    urls.append(url)

        # 2. JSON-LD ImageObject в @graph
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
                graph = data.get('@graph', []) if isinstance(data, dict) else []
                for item in graph:
                    if item.get('@type') == 'ImageObject':
                        url = item.get('url') or item.get('contentUrl')
                        if url:
                            urls.append(url)
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue

        # 3. og:image и twitter:image как запасной вариант
        for prop, attr in [('og:image', 'property'), ('twitter:image', 'name')]:
            meta = self.soup.find('meta', attrs={attr: prop})
            if meta and meta.get('content'):
                urls.append(meta['content'])

        # Убираем дубликаты, сохраняя порядок
        seen: set = set()
        unique: list = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с полями рецепта
        """
        return {
            'dish_name': self.extract_dish_name(),
            'description': self.extract_description(),
            'ingredients': self.extract_ingredients(),
            'instructions': self.extract_instructions(),
            'category': self.extract_category(),
            'prep_time': self.extract_prep_time(),
            'cook_time': self.extract_cook_time(),
            'total_time': self.extract_total_time(),
            'notes': self.extract_notes(),
            'tags': self.extract_tags(),
            'image_urls': self.extract_image_urls(),
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os

    preprocessed_dir = os.path.join('preprocessed', 'annikarezepte_de')

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(AnnikaRezepteExtractor, preprocessed_dir)
        return

    print(f'Директория не найдена: {preprocessed_dir}')
    print('Использование: python annikarezepte_de.py')


if __name__ == '__main__':
    main()
