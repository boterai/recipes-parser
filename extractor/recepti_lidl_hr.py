"""
Экстрактор данных рецептов для сайта recepti.lidl.hr
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


class ReceptiLidlHrExtractor(BaseRecipeExtractor):
    """Экстрактор для recepti.lidl.hr"""

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из <h1>"""
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        # Запасной вариант: og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта.

        Сайт recepti.lidl.hr использует общее описание «Lidl Recipes» в meta-тегах,
        поэтому возвращаем None, если описание не специфично для рецепта или
        совпадает с названием блюда.
        """
        dish_name = self.extract_dish_name()
        for attr, prop in [('name', 'description'), ('property', 'og:description')]:
            tag = self.soup.find('meta', {attr: prop})
            if tag and tag.get('content'):
                text = self.clean_text(tag['content'])
                # Пропускаем общие заглушки и описания, идентичные названию блюда
                if text.lower() in ('lidl recipes', 'lidl recepti', ''):
                    continue
                if dish_name and text.strip().lower() == dish_name.strip().lower():
                    continue
                return text

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из списка рецепта.

        Каждый ингредиент возвращается в виде словаря:
            {"name": str, "amount": str | None, "unit": str | None}
        """
        ingredients_container = self.soup.find(
            'div', {'data-testid': 'recipe-detail-ingredients-list'}
        )
        if not ingredients_container:
            logger.warning("Блок ингредиентов не найден (data-testid='recipe-detail-ingredients-list')")
            return None

        ingredients = []
        for li in ingredients_container.find_all('li'):
            try:
                # Название ингредиента
                ingredient_div = li.find('div', {'data-testid': 'ingredient'})
                if not ingredient_div:
                    continue
                name_span = ingredient_div.find('span')
                name = self.clean_text(name_span.get_text()) if name_span else None
                if not name:
                    continue

                # Количество (может отсутствовать, напр. «по желанию»)
                # Поддерживаем диапазон: quantity-from и quantity-to (напр. "3-4")
                amount_from_span = li.find('span', {'data-testid': 'quantity-from'})
                amount_to_span = li.find('span', {'data-testid': 'quantity-to'})
                if amount_from_span:
                    amount_from = self.clean_text(amount_from_span.get_text())
                    amount_to = self.clean_text(amount_to_span.get_text()) if amount_to_span else None
                    amount = f"{amount_from}-{amount_to}" if amount_to else amount_from
                else:
                    amount = None

                # Единица измерения
                unit_span = li.find('span', {'data-testid': 'unit'})
                unit_text = self.clean_text(unit_span.get_text()) if unit_span else None

                # Нормализуем разделитель дробных чисел (запятая → точка)
                if amount:
                    amount = amount.replace(',', '.')

                # Если количество не задано, а в unit написано «по желанию» / «po želji»
                if not amount and unit_text:
                    amount = unit_text
                    unit_text = None

                ingredients.append({
                    'name': name,
                    'amount': amount,
                    'unit': unit_text,
                })
            except Exception as exc:
                logger.warning("Ошибка при разборе ингредиента: %s", exc)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления из <ol data-rid='cooking-step'>"""
        # Раздел «Priprema» содержит <ol data-rid="cooking-step">
        cooking_ol = self.soup.find('ol', {'data-rid': 'cooking-step'})
        if not cooking_ol:
            logger.warning("Список шагов приготовления не найден (data-rid='cooking-step')")
            return None

        steps = []
        for li in cooking_ol.find_all('li', recursive=False):
            text = self.clean_text(li.get_text(separator=' '))
            if text:
                steps.append(text)

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из хлебных крошек.

        В хлебных крошках breadcrumb содержатся ссылки с классом «capitalize-first-letter».
        Первые два элемента — «Naslovnica» и «Svi recepti», далее идёт фактическая категория.
        """
        breadcrumb_spans = self.soup.find_all(
            'span', class_=lambda c: c and 'capitalize-first-letter' in c
        )
        skip = {'naslovnica', 'svi recepti', '...'}
        categories = []
        seen = set()
        for span in breadcrumb_spans:
            txt = self.clean_text(span.get_text())
            if txt and txt.lower() not in skip and txt not in seen:
                categories.append(txt)
                seen.add(txt)

        if categories:
            return categories[0]

        return None

    def _extract_time_from_badge(self, badge_testid: str) -> Optional[str]:
        """Вспомогательный метод: извлечение времени из badge-блока.

        Ищет span с классом «font-small_1-prominent-*» внутри badge-div.
        """
        badge = self.soup.find('div', {'data-testid': badge_testid})
        if not badge:
            return None

        time_span = badge.find(
            'span',
            class_=lambda c: isinstance(c, str) and 'font-small_1-prominent' in c,
        )
        if time_span:
            return self.clean_text(time_span.get_text())

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self._extract_time_from_badge('recipe-info-badge-preparation')

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        return self._extract_time_from_badge('recipe-info-badge-cooking')

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени приготовления"""
        return self._extract_time_from_badge('recipe-info-badge-total')

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов к рецепту"""
        # На сайте нет стандартного блока с заметками
        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из chip-ссылок (data-name='tag')"""
        tag_links = self.soup.find_all('a', attrs={'data-name': 'tag'})
        tags = []
        seen = set()
        for link in tag_links:
            txt = self.clean_text(link.get_text())
            if txt and txt not in seen:
                tags.append(txt)
                seen.add(txt)

        return ', '.join(tags) if tags else None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта.

        Основное изображение берётся из og:image. Дополнительно собираются
        изображения из тега <img> внутри основного блока рецепта.
        """
        urls = []

        # og:image — основное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'].strip())

        # Дополнительные изображения из основного содержимого
        main_content = self.soup.find('main')
        if main_content:
            for img in main_content.find_all('img'):
                src = img.get('src') or img.get('data-src')
                if not src:
                    continue
                src = src.strip()
                if not src or src.startswith('/_next/') or src.startswith('data:'):
                    continue
                if src.startswith('http') and src not in urls:
                    urls.append(src)

        # Убираем дубликаты с сохранением порядка
        seen: set = set()
        unique_urls = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ','.join(unique_urls) if unique_urls else None

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
            'dish_name': dish_name,
            'description': description,
            'ingredients': ingredients,
            'instructions': instructions,
            'category': category,
            'prep_time': self.extract_prep_time(),
            'cook_time': self.extract_cook_time(),
            'total_time': self.extract_total_time(),
            'notes': notes,
            'tags': tags,
            'image_urls': self.extract_image_urls(),
        }


def main() -> None:
    """Точка входа для обработки директории с HTML-файлами recepti.lidl.hr"""
    import os

    preprocessed_dir = os.path.join('preprocessed', 'recepti_lidl_hr')

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f'Обработка директории: {preprocessed_dir}')
        process_directory(ReceptiLidlHrExtractor, preprocessed_dir)
        return

    print(f'Директория не найдена: {preprocessed_dir}')
    print('Использование: python recepti_lidl_hr.py')


if __name__ == '__main__':
    main()
