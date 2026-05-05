"""
Экстрактор данных рецептов для сайта cuisinaweb.ca
Сайт использует WordPress + WP Recipe Maker (WPRM) и JSON-LD Schema.org.
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


class CuisinawebCaExtractor(BaseRecipeExtractor):
    """Экстрактор для cuisinaweb.ca (использует WPRM и JSON-LD)"""

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

    def _get_article_jsonld(self) -> Optional[dict]:
        """
        Возвращает объект Article из JSON-LD @graph.
        """
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
            except (json.JSONDecodeError, TypeError):
                continue

            if isinstance(data, dict) and '@graph' in data:
                for item in data['@graph']:
                    if isinstance(item, dict) and item.get('@type') == 'Article':
                        return item

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

    def _extract_wprm_time(self, time_key: str) -> Optional[str]:
        """
        Извлекает время из WPRM HTML time container.
        Поддерживает часы и минуты с оригинальными единицами (heures/minutes).

        Args:
            time_key: «prep», «cook» или «total»

        Returns:
            Строка вида «8 heures 10 minutes», «10 minutes» или None
        """
        container = self.soup.find(
            class_=lambda x: x and f'wprm-recipe-{time_key}-time-container' in x
        )
        if not container:
            return None

        parts = []
        for unit_type in ('hours', 'minutes'):
            # span с числом (содержит sr-only дочерний span с названием единицы)
            val_span = container.find(
                class_=lambda x: x and f'wprm-recipe-{time_key}_time-{unit_type}' in x
                and 'unit' not in x
            )
            if not val_span:
                continue

            # Текст sr-only содержит полное название единицы («heures», «minutes»)
            sr_span = val_span.find(class_='wprm-screen-reader-text')
            unit_label = self.clean_text(sr_span.get_text()) if sr_span else unit_type

            # Число — это прямой текстовый узел val_span (без sr-only)
            raw_number = val_span.find(string=True, recursive=False)
            if raw_number:
                number = raw_number.strip()
            else:
                # fallback: весь текст минус sr-only
                if sr_span:
                    sr_span.extract()
                number = self.clean_text(val_span.get_text())

            if number and number != '0':
                parts.append(f'{number} {unit_label}')

        return ' '.join(parts) if parts else None

    def _parse_wprm_ingredient(self, li_tag) -> Optional[dict]:
        """
        Разбирает элемент <li class="wprm-recipe-ingredient"> на поля
        name / amount / unit.

        Логика:
          1. Берём явные поля amount, unit, name из WPRM-spans.
          2. Если name начинается с «de » или «d'» (французский артикль),
             убираем этот префикс.
          3. Если name содержит ведущий скобочный модификатор (напр. «(1 kg)»),
             переносим его в unit для более чистого названия.

        Returns:
            dict с полями name, amount, unit или None
        """
        amount_span = li_tag.find(class_='wprm-recipe-ingredient-amount')
        unit_span = li_tag.find(class_='wprm-recipe-ingredient-unit')
        name_span = li_tag.find(class_='wprm-recipe-ingredient-name')

        raw_amount = self.clean_text(amount_span.get_text()) if amount_span else None
        raw_unit = self.clean_text(unit_span.get_text()) if unit_span else None
        raw_name = self.clean_text(name_span.get_text()) if name_span else None

        if not raw_name and not raw_amount:
            return None

        # Нормализуем количество (оставляем как строку, сохраняя «2,2»)
        amount = raw_amount if raw_amount else None

        unit = raw_unit if raw_unit else None
        name = raw_name or ''

        # Если name начинается со скобочного модификатора вида «(1 kg) de ...»,
        # перемещаем скобки в unit и продолжаем очистку name.
        bracket_match = re.match(r'^(\([^)]+\))\s*(.*)', name)
        if bracket_match:
            bracket_part = bracket_match.group(1).strip()
            remainder = bracket_match.group(2).strip()
            if unit:
                unit = f'{unit} {bracket_part}'
            else:
                unit = bracket_part
            name = remainder

        # Убираем французские предлоги «de » / «d'» / «d'» в начале названия
        name = re.sub(r"^d[e'\u2019]\s*", '', name, flags=re.IGNORECASE).strip()

        name = self.clean_text(name) if name else None
        if not name:
            return None

        return {'name': name, 'amount': amount, 'unit': unit}

    # ------------------------------------------------------------------
    # Методы извлечения полей
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Приоритет: WPRM h2.wprm-recipe-name
        wprm_name = self.soup.find(class_='wprm-recipe-name')
        if wprm_name:
            return self.clean_text(wprm_name.get_text())

        # JSON-LD Recipe.name
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('name'):
            return self.clean_text(recipe['name'])

        # Резервный вариант — h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Приоритет: WPRM summary
        wprm_summary = self.soup.find(class_='wprm-recipe-summary')
        if wprm_summary:
            text = self.clean_text(wprm_summary.get_text())
            if text:
                return text

        # JSON-LD Recipe.description
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('description'):
            return self.clean_text(recipe['description'])

        # Резервный вариант — og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def _get_main_recipe_block(self):
        """
        Возвращает основной div WPRM-рецепта (не snippet/roundup).
        BS4 вызывает class_ лямбду для каждого отдельного класса, поэтому
        проверяем список классов напрямую.
        """
        for div in self.soup.find_all('div'):
            classes = div.get('class', [])
            if 'wprm-recipe' in classes and 'wprm-recipe-snippet' not in classes:
                return div
        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из WPRM-разметки основного блока рецепта.
        Каждый ингредиент — словарь {name, amount, unit}.
        """
        ingredients = []

        # Ищем основной блок рецепта (не snippet)
        source = self._get_main_recipe_block() or self.soup

        for li in source.find_all('li', class_='wprm-recipe-ingredient'):
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
                if raw and raw.strip():
                    fallback.append({'name': self.clean_text(raw), 'amount': None, 'unit': None})
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

        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда"""
        # JSON-LD Recipe.recipeCategory
        recipe = self._get_recipe_jsonld()
        if recipe:
            cat = recipe.get('recipeCategory')
            if cat:
                if isinstance(cat, list):
                    return ', '.join(self.clean_text(c) for c in cat if c)
                return self.clean_text(str(cat))

        # WPRM HTML: span.wprm-recipe-course
        course_container = self.soup.find(
            class_=lambda x: x and 'wprm-recipe-course-container' in x
        )
        if course_container:
            course_span = course_container.find(
                class_=lambda x: x and 'wprm-recipe-course' in x
                and 'label' not in x and 'container' not in x
            )
            if course_span:
                return self.clean_text(course_span.get_text())

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self._extract_wprm_time('prep')

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self._extract_wprm_time('cook')

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени приготовления"""
        return self._extract_wprm_time('total')

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок из блока WPRM notes"""
        notes_div = self.soup.find('div', class_='wprm-recipe-notes')
        if notes_div:
            text = self.clean_text(notes_div.get_text(separator=' '))
            return text if text else None

        # Резервный вариант — контейнер с notes
        notes_container = self.soup.find('div', class_='wprm-recipe-notes-container')
        if notes_container:
            # Убираем заголовок «Notes»
            text = notes_container.get_text(separator=' ', strip=True)
            text = re.sub(r'^Notes?\s*', '', text, flags=re.IGNORECASE).strip()
            return self.clean_text(text) if text else None

        return None

    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов.
        Порядок: JSON-LD Recipe.keywords → Article.keywords → WPRM wprm-recipe-keyword.
        Для cuisinaweb.ca теги хранятся в Article.keywords в JSON-LD @graph.
        """
        # JSON-LD Recipe keywords
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('keywords'):
            keywords = recipe['keywords']
            if isinstance(keywords, list):
                return ', '.join(k.strip() for k in keywords if k.strip())
            if isinstance(keywords, str):
                return self.clean_text(keywords)

        # JSON-LD Article.keywords (cuisinaweb.ca хранит теги здесь)
        article = self._get_article_jsonld()
        if article and article.get('keywords'):
            keywords = article['keywords']
            if isinstance(keywords, list):
                parts = []
                # Добавляем articleSection как первый тег
                section = article.get('articleSection', [])
                if isinstance(section, list):
                    parts.extend(s.strip() for s in section if s.strip())
                elif isinstance(section, str) and section.strip():
                    parts.append(section.strip())
                parts.extend(k.strip() for k in keywords if k.strip())
                # Убираем дубликаты, сохраняя порядок
                seen: set = set()
                unique = []
                for p in parts:
                    if p.lower() not in seen:
                        seen.add(p.lower())
                        unique.append(p)
                return ', '.join(unique) if unique else None
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

        # 3. og:image как запасной вариант
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

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

    preprocessed_dir = os.path.join('preprocessed', 'cuisinaweb_ca')

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(CuisinawebCaExtractor, preprocessed_dir)
        return

    print(f'Директория не найдена: {preprocessed_dir}')
    print('Использование: python cuisinaweb_ca.py')


if __name__ == '__main__':
    main()
