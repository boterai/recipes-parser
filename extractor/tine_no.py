"""
Экстрактор данных рецептов для сайта tine.no
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


class TineNoExtractor(BaseRecipeExtractor):
    """Экстрактор для tine.no"""

    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных Recipe JSON-LD из страницы"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                # Поддержка как словаря, так и списка
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and self._is_recipe(item):
                            return item
                elif isinstance(data, dict):
                    if self._is_recipe(data):
                        return data
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and self._is_recipe(item):
                                return item
            except (json.JSONDecodeError, AttributeError) as exc:
                logger.debug("Ошибка при разборе JSON-LD: %s", exc)
        return None

    @staticmethod
    def _is_recipe(item: dict) -> bool:
        """Проверка, является ли JSON-LD объект рецептом"""
        item_type = item.get('@type', '')
        if isinstance(item_type, list):
            return 'Recipe' in item_type
        return item_type == 'Recipe'

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в строку вида «N min»

        Args:
            duration: строка вида «PT15M» или «PT1H30M»

        Returns:
            Время в минутах, например «15 min», или None
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
        return f"{total} min" if total > 0 else None

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Предпочитаем JSON-LD как наиболее надёжный источник
        data = self._get_json_ld_data()
        if data and data.get('name'):
            return self.clean_text(data['name'])

        # Резервный вариант — h1 на странице (первый не-placeholder)
        for h1 in self.soup.find_all('h1'):
            text = self.clean_text(h1.get_text())
            if text and text.lower() != 'laster...':
                return text

        # og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # JSON-LD
        data = self._get_json_ld_data()
        if data and data.get('description'):
            return self.clean_text(data['description'])

        # og:description / meta description
        for attr in ({'property': 'og:description'}, {'name': 'description'}):
            meta = self.soup.find('meta', attr)
            if meta and meta.get('content'):
                return self.clean_text(meta['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из HTML.

        tine.no отображает ингредиенты в виде:
            <li class="flex text-xs leading-tight">
              <span ...>AMOUNT<!-- --> UNIT <!-- -->NAME_PART1 <!-- -->NAME_PART2</span>
            </li>
        NavigableString-узлы (кроме Comment) идут в порядке:
            [0] amount, [1] unit (с пробелами), [2..] части названия
        """
        from bs4 import Comment

        ingredients: list[dict] = []

        lis = self.soup.find_all(
            'li',
            class_=lambda c: c and 'flex' in c and 'text-xs' in c and 'leading-tight' in c
        )

        if lis:
            for li in lis:
                span = li.find('span')
                if not span:
                    continue

                # Собираем все NavigableString-узлы (не Comment)
                parts = [
                    str(ch).strip()
                    for ch in span.children
                    if not isinstance(ch, Comment) and str(ch).strip()
                ]

                if len(parts) < 2:
                    # Слишком мало частей — пробуем разобрать как строку
                    raw = self.clean_text(span.get_text())
                    parsed = self._parse_ingredient_string(raw)
                    if parsed:
                        ingredients.append(parsed)
                    continue

                amount = parts[0]
                unit = parts[1].strip()
                name = ' '.join(parts[2:]).strip() if len(parts) > 2 else ''

                if not name:
                    # Резервный вариант: всё кроме amount — название
                    name = unit
                    unit = ''

                ingredients.append({
                    'name': self.clean_text(name),
                    'amount': amount,
                    'unit': unit if unit else None,
                })

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        # Резервный вариант — берём recipeIngredient из JSON-LD
        data = self._get_json_ld_data()
        if data and data.get('recipeIngredient'):
            fallback: list[dict] = []
            for raw in data['recipeIngredient']:
                parsed = self._parse_ingredient_string(self.clean_text(str(raw)))
                if parsed:
                    fallback.append(parsed)
            return json.dumps(fallback, ensure_ascii=False) if fallback else None

        return None

    def _parse_ingredient_string(self, text: str) -> Optional[dict]:
        """
        Разбор строки ингредиента «AMOUNT UNIT NAME» в словарь.
        Формат tine.no: «6 dl Biola® Blåbær», «frosne 2 dl blåbær» и т.п.
        """
        if not text:
            return None

        # Единицы измерения, типичные для норвежских рецептов
        units = (
            r'dl|cl|ml|l|liter|kg|g|gram|ts|teskje|ss|spiseskje|stk|stykk|stykker|'
            r'pk|pakke|boks|glass|neve|klype|skive|fedd|kvast|bunke|deig'
        )

        # Образец: [необязательное слово] ЧИСЛО ЕДИНИЦА НАЗВАНИЕ
        pattern = (
            r'^(?:\S+\s+)?'            # необязательный префикс (напр. «frosne»)
            r'([\d.,/]+)'              # количество
            r'\s+(' + units + r')\s+'  # единица
            r'(.+)$'                   # название
        )
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            amount, unit, name = match.groups()
            prefix_match = re.match(r'^(\S+)\s+[\d.,/]+', text)
            prefix = prefix_match.group(1) if prefix_match else None
            if prefix and not re.match(r'^[\d.,/]+$', prefix):
                name = f"{prefix} {name}".strip()
            return {
                'name': self.clean_text(name),
                'amount': amount.strip(),
                'unit': unit.strip(),
            }

        # Если ничего не подошло — возвращаем как название без количества
        return {'name': text, 'amount': None, 'unit': None}

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Предпочитаем JSON-LD — данные там чистые
        data = self._get_json_ld_data()
        if data and data.get('recipeInstructions'):
            steps = []
            for idx, step in enumerate(data['recipeInstructions'], 1):
                if isinstance(step, dict) and step.get('text'):
                    steps.append(f"{idx}. {self.clean_text(step['text'])}")
                elif isinstance(step, str):
                    steps.append(f"{idx}. {self.clean_text(step)}")
            if steps:
                return ' '.join(steps)

        # Резервный вариант — li.flex.gap-1.5 (compact version)
        steps = self._extract_steps_from_li()
        return ' '.join(steps) if steps else None

    def _extract_steps_from_li(self) -> list:
        """Извлечение шагов из li.flex.gap-1.5 с числовым кружком"""
        steps = []

        for li in self.soup.find_all(
            'li',
            class_=lambda c: c and 'flex' in c and 'gap-1.5' in c
        ):
            # Текст инструкции — первый div.text-xs.leading-normal внутри li
            text_div = li.find(
                'div',
                class_=lambda c: c and 'text-xs' in c and 'leading-normal' in c
            )
            if text_div:
                text = self.clean_text(text_div.get_text())
                if text:
                    steps.append(text)

        if steps:
            return [f"{i}. {s}" for i, s in enumerate(steps, 1)]
        return []

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок/советов.
        На tine.no подсказки (Tips) встроены в шаги рецепта:
            div.flex.items-start.gap-1 → span.font-bold «Tips» + div.pt-1 с текстом
        """
        notes_parts = []

        for container in self.soup.find_all(
            'div',
            class_=lambda c: c and 'flex' in c and 'items-start' in c and 'gap-1' in c
        ):
            # Проверяем, что это контейнер Tips
            label = container.find(
                'span',
                class_=lambda c: c and 'font-bold' in c
            )
            if not label:
                continue
            if 'tips' not in label.get_text(strip=True).lower():
                continue

            # Текст заметки находится в div.pt-1 внутри контейнера
            text_div = container.find('div', class_=lambda c: c and 'pt-1' in c)
            if text_div:
                text = self.clean_text(text_div.get_text())
                if text and text not in notes_parts:
                    notes_parts.append(text)

        if not notes_parts:
            return None

        combined = ' '.join(notes_parts)
        return combined if combined else None

    def extract_category(self) -> Optional[str]:
        """
        Извлечение категории блюда.
        Берём второй элемент хлебных крошек (страница раздела).
        """
        breadcrumb_items = self.soup.find_all(
            'li',
            class_=lambda c: c and 'last:hidden' in c
        )
        # breadcrumb: Forsiden → Category → Recipe name
        if len(breadcrumb_items) >= 2:
            category = self.clean_text(breadcrumb_items[1].get_text())
            if category:
                return category.lower()

        # Резервный вариант — последняя категория из JSON-LD
        data = self._get_json_ld_data()
        if data and data.get('recipeCategory'):
            cats = data['recipeCategory']
            if isinstance(cats, list) and cats:
                return self.clean_text(cats[-1]).lower()
            if isinstance(cats, str):
                return self.clean_text(cats).lower()

        return None

    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов.
        Используем recipeCategory из JSON-LD, отфильтровывая составные значения
        (содержащие дефис), так как они являются slug-идентификаторами разделов.
        """
        data = self._get_json_ld_data()
        if data and data.get('recipeCategory'):
            cats = data['recipeCategory']
            if isinstance(cats, list):
                tags = [self.clean_text(c) for c in cats if '-' not in c and self.clean_text(c)]
                return ','.join(tags) if tags else None
            if isinstance(cats, str):
                return self.clean_text(cats) or None

        return None

    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени приготовления.

        Логика tine.no:
        - prepTime в JSON-LD обычно пустой; displayed time = cookTime.
        - Если prepTime пустой, используем displayed HTML-время как prep_time,
          а cook_time не дублируем (возвращаем None).
        - Если prepTime явно задан — используем prepTime/cookTime раздельно.

        Args:
            time_type: «prep», «cook» или «total»
        """
        data = self._get_json_ld_data()

        if time_type == 'prep':
            if data:
                raw = data.get('prepTime', '')
                if raw:
                    parsed = self._parse_iso_duration(raw)
                    if parsed:
                        return parsed
            # prepTime пустой — берём отображаемое время со страницы
            return self._extract_displayed_time()

        if time_type == 'cook':
            if data:
                prep_raw = data.get('prepTime', '')
                cook_raw = data.get('cookTime', '')
                # Возвращаем cook_time только когда оба времени явно заданы,
                # иначе cookTime уже отображается как prep_time
                if prep_raw and cook_raw:
                    return self._parse_iso_duration(cook_raw)
            return None

        if time_type == 'total':
            if data:
                raw = data.get('totalTime', '')
                if raw:
                    return self._parse_iso_duration(raw)
            return None

        return None

    def _extract_displayed_time(self) -> Optional[str]:
        """
        Извлечение отображаемого времени из HTML.
        На tine.no есть элемент вида «Enkel • 15 min • 4 personer».
        """
        time_span = self.soup.find('span', string=re.compile(r'\d+\s*min', re.I))
        if time_span:
            return self.clean_text(time_span.get_text())
        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls: list[str] = []

        # 1. JSON-LD image
        data = self._get_json_ld_data()
        if data and data.get('image'):
            img = data['image']
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

        # 2. og:image (может быть другой размер/кадрировка)
        og_img = self.soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            urls.append(og_img['content'])

        # Дедупликация с сохранением порядка
        seen: set = set()
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
            Словарь с полями рецепта. Отсутствующие данные → None.
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception as exc:
            logger.warning("Ошибка извлечения dish_name: %s", exc)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as exc:
            logger.warning("Ошибка извлечения description: %s", exc)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as exc:
            logger.warning("Ошибка извлечения ingredients: %s", exc)
            ingredients = None

        try:
            instructions = self.extract_steps()
        except Exception as exc:
            logger.warning("Ошибка извлечения instructions: %s", exc)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as exc:
            logger.warning("Ошибка извлечения category: %s", exc)
            category = None

        try:
            notes = self.extract_notes()
        except Exception as exc:
            logger.warning("Ошибка извлечения notes: %s", exc)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as exc:
            logger.warning("Ошибка извлечения tags: %s", exc)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as exc:
            logger.warning("Ошибка извлечения image_urls: %s", exc)
            image_urls = None

        try:
            prep_time = self.extract_time('prep')
        except Exception as exc:
            logger.warning("Ошибка извлечения prep_time: %s", exc)
            prep_time = None

        try:
            cook_time = self.extract_time('cook')
        except Exception as exc:
            logger.warning("Ошибка извлечения cook_time: %s", exc)
            cook_time = None

        try:
            total_time = self.extract_time('total')
        except Exception as exc:
            logger.warning("Ошибка извлечения total_time: %s", exc)
            total_time = None

        return {
            'dish_name': dish_name,
            'description': description,
            'ingredients': ingredients,
            'instructions': instructions,
            'category': category,
            'prep_time': prep_time,
            'cook_time': cook_time,
            'total_time': total_time,
            'notes': notes,
            'image_urls': image_urls,
            'tags': tags,
        }


def main() -> None:
    import os
    recipes_dir = os.path.join("preprocessed", "tine_no")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(TineNoExtractor, str(recipes_dir))
        return
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python tine_no.py")


if __name__ == "__main__":
    main()
