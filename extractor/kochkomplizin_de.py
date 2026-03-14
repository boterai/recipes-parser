"""
Экстрактор данных рецептов для сайта kochkomplizin.de

Сайт построен на WordPress с плагином WP Recipe Maker (WPRM).
Основные источники данных:
  - Карточка рецепта WPRM (div.wprm-recipe-container и вложенные блоки)
  - JSON-LD типа Recipe (application/ld+json)
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Немецкие единицы измерения, которые могут встречаться в начале поля «name» в WPRM
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

# Стоп-слова для фильтрации тегов
_TAG_STOPWORDS = {
    'rezept', 'rezepte', 'kochen', 'backen', 'einfach', 'schnell',
    'lecker', 'kochkomplizin', 'küche', 'zubereitung', 'zutaten',
    'deutsch', 'deutsche', 'deutsches', 'einfaches', 'schnelles',
    'recipe', 'recipes', 'easy', 'quick', 'cooking',
}


class KochkomplizinDeExtractor(BaseRecipeExtractor):
    """Экстрактор для kochkomplizin.de (WordPress + WP Recipe Maker)"""

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

    @staticmethod
    def _normalize_amount(raw: Optional[str]):
        """
        Нормализует строку количества в число или строку.

        Returns:
            int / float / str / None
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
            parts = text.split()
            total = sum(float(p) for p in parts)
            return int(total) if total == int(total) else total
        except (ValueError, OverflowError):
            return raw  # возвращаем как строку если не распознали

    def _parse_wprm_ingredient(self, li_tag) -> Optional[dict]:
        """
        Разбирает элемент <li class="wprm-recipe-ingredient"> на поля
        name / amount / unit.

        Returns:
            dict с полями name, amount, unit или None
        """
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

        amount = self._normalize_amount(raw_amount)
        unit = raw_unit if raw_unit else None
        name = raw_name or ''

        if not unit and name:
            name_lower = name.lower()

            # Случай: name содержит только название контейнера («Dose») +
            # notes содержат размер и реальный ингредиент
            if name_lower in ('dose', 'dosen', 'glas', 'gläser', 'becher') and raw_notes:
                size_match = re.match(r'^(\d+[\d.,]*\s*(?:g|kg|ml|l))\s+(.+)$', raw_notes, re.IGNORECASE)
                if size_match:
                    size_str = size_match.group(1).strip()
                    remainder = size_match.group(2).strip()
                    ingredient_name = re.split(r',\s*', remainder)[0].strip()
                    unit = f"{name} ({size_str})"
                    name = ingredient_name
                else:
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

    def _extract_wprm_time(self, time_type: str) -> Optional[str]:
        """
        Извлекает время из WPRM-spans.

        Args:
            time_type: «prep_time», «cook_time» или «total_time»

        Returns:
            Строка вида «15 minutes» или None
        """
        minutes_span = self.soup.find(class_=re.compile(
            rf'wprm-recipe-{time_type}-minutes', re.I
        ))
        if minutes_span:
            raw = minutes_span.find(string=True, recursive=False)
            if raw:
                raw = raw.strip()
                if raw.isdigit():
                    return f"{raw} minutes"

        # Пробуем также считать часы и минуты по отдельности
        hours_span = self.soup.find(class_=re.compile(
            rf'wprm-recipe-{time_type}-hours', re.I
        ))
        h_val = 0
        m_val = 0
        if hours_span:
            raw_h = hours_span.find(string=True, recursive=False)
            if raw_h and raw_h.strip().isdigit():
                h_val = int(raw_h.strip())
        if minutes_span:
            raw_m = minutes_span.find(string=True, recursive=False)
            if raw_m and raw_m.strip().isdigit():
                m_val = int(raw_m.strip())
        total = h_val * 60 + m_val
        if total > 0:
            return f"{total} minutes"

        return None

    # ------------------------------------------------------------------
    # Методы извлечения полей
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # 1. WPRM карточка
        wprm_name = self.soup.find(class_='wprm-recipe-name')
        if wprm_name:
            return self.clean_text(wprm_name.get_text())

        # 2. JSON-LD
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('name'):
            return self.clean_text(recipe['name'])

        # 3. Резервный вариант — h1 на странице
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # 1. WPRM карточка
        wprm_summary = self.soup.find(class_='wprm-recipe-summary')
        if wprm_summary:
            text = self.clean_text(wprm_summary.get_text(separator=' '))
            if text:
                return text

        # 2. JSON-LD
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('description'):
            return self.clean_text(recipe['description'])

        # 3. Meta description
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
            fallback = []
            for raw in recipe['recipeIngredient']:
                parsed = self._parse_ingredient_string(raw)
                if parsed:
                    fallback.append(parsed)
            if fallback:
                return json.dumps(fallback, ensure_ascii=False)

        return None

    def _parse_ingredient_string(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат.
        Поддерживает немецкие и английские единицы измерения.
        """
        if not text:
            return None

        text = self.clean_text(text)
        original = text
        text_lower = text.lower()

        # Замена Unicode дробей
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.333', '⅔': '0.667', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
        }
        for frac, dec in fraction_map.items():
            text_lower = text_lower.replace(frac, dec)

        # Паттерн для извлечения: "количество единица название"
        units_pattern = (
            r'(?:esslöffel|el|teelöffel|tl|tasse[n]?|stücke?[n]?|dose[n]?|glas|gläser|'
            r'liter|l|milliliter|ml|kilogramm|kg|gramm|g|mg|prise[n]?|päckchen|pakete?|'
            r'bund|zweige?|zehe[n]?|scheibe[n]?|stiele?|becher|pkg|'
            r'cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|'
            r'pinch(?:es)?|dash(?:es)?|pieces?|whole|halves?|cloves?|slices?|bunches?|sprigs?)'
        )
        pattern = rf'^([\d\s/.,]+)?\s*({units_pattern})?\s*(.+)'

        match = re.match(pattern, text_lower, re.IGNORECASE)
        if not match:
            return {'name': self.clean_text(original), 'amount': None, 'unit': None}

        amount_str, unit, name = match.groups()

        # Нормализуем количество
        amount = self._normalize_amount(amount_str.strip() if amount_str else None)

        # Очищаем название
        name = re.sub(r'\([^)]*\)', '', name)
        name = re.sub(r'\b(to taste|nach geschmack|optional|nach bedarf)\b', '', name, flags=re.IGNORECASE)
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()

        if not name or len(name) < 2:
            return None

        return {
            'name': name,
            'amount': amount,
            'unit': unit.strip() if unit else None
        }

    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления из JSON-LD или WPRM HTML"""
        # 1. JSON-LD
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

        # 2. WPRM HTML — текст шагов в span.wprm-recipe-instruction-text
        wprm_steps = self.soup.find_all(class_='wprm-recipe-instruction-text')
        if wprm_steps:
            texts = [self.clean_text(s.get_text()) for s in wprm_steps]
            return ' '.join(t for t in texts if t) or None

        # 3. WPRM HTML — li.wprm-recipe-instruction
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
        # 1. JSON-LD
        recipe = self._get_recipe_jsonld()
        if recipe:
            cat = recipe.get('recipeCategory')
            if cat:
                if isinstance(cat, list):
                    return ', '.join(self.clean_text(c) for c in cat if c)
                return self.clean_text(str(cat))

        # 2. WPRM course span
        course = self.soup.find(class_='wprm-recipe-course')
        if course:
            return self.clean_text(course.get_text())

        # 3. Meta article:section
        meta = self.soup.find('meta', property='article:section')
        if meta and meta.get('content'):
            return self.clean_text(meta['content'])

        # 4. Breadcrumbs
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())

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
        # 1. WPRM notes div
        notes_div = self.soup.find('div', class_='wprm-recipe-notes')
        if notes_div:
            text = self.clean_text(notes_div.get_text(separator=' '))
            return text if text else None

        # 2. WPRM notes container
        notes_container = self.soup.find('div', class_='wprm-recipe-notes-container')
        if notes_container:
            text = notes_container.get_text(separator=' ', strip=True)
            text = re.sub(r'^Notizen?\s*', '', text, flags=re.IGNORECASE).strip()
            return self.clean_text(text) if text else None

        # 3. Секция с «tips» или «Tipps»
        for class_pattern in [r'recipe-tips', r'recipe-notes', r'recipe-hint']:
            tips_div = self.soup.find(class_=re.compile(class_pattern, re.I))
            if tips_div:
                text = self.clean_text(tips_div.get_text(separator=' '))
                if text:
                    return text

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из keywords в JSON-LD или WPRM HTML"""
        # 1. JSON-LD keywords
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('keywords'):
            keywords = recipe['keywords']
            if isinstance(keywords, list):
                tags = ', '.join(k.strip() for k in keywords if k.strip())
            elif isinstance(keywords, str):
                tags = self.clean_text(keywords)
            else:
                tags = None
            if tags:
                return tags

        # 2. WPRM keyword span
        kw_span = self.soup.find(class_='wprm-recipe-keyword')
        if kw_span:
            text = self.clean_text(kw_span.get_text())
            if text:
                return text

        # 3. Meta keywords
        meta_kw = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_kw and meta_kw.get('content'):
            raw = meta_kw['content']
            tags_list = [t.strip() for t in raw.split(',') if t.strip()]
            # Фильтрация стоп-слов
            filtered = [t for t in tags_list if t.lower() not in _TAG_STOPWORDS and len(t) >= 3]
            if filtered:
                return ', '.join(filtered)

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
                for i in img:
                    if isinstance(i, str):
                        urls.append(i)
                    elif isinstance(i, dict):
                        url = i.get('url') or i.get('contentUrl')
                        if url:
                            urls.append(url)
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

        # 3. og:image и twitter:image
        for prop, attr in [('og:image', 'property'), ('twitter:image', 'name')]:
            meta = self.soup.find('meta', attrs={attr: prop})
            if meta and meta.get('content'):
                urls.append(meta['content'])

        # 4. Основное изображение карточки WPRM
        wprm_img = self.soup.find(class_='wprm-recipe-image')
        if wprm_img:
            img_tag = wprm_img.find('img')
            if img_tag:
                src = img_tag.get('src') or img_tag.get('data-src')
                if src and src not in urls:
                    urls.append(src)

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
        dish_name = self.extract_dish_name()
        description = self.extract_description()

        return {
            'dish_name': dish_name.lower() if dish_name else None,
            'description': description.lower() if description else None,
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

    preprocessed_dir = os.path.join('preprocessed', 'kochkomplizin_de')

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(KochkomplizinDeExtractor, preprocessed_dir)
        return

    print(f'Директория не найдена: {preprocessed_dir}')
    print('Использование: python kochkomplizin_de.py')


if __name__ == '__main__':
    main()
