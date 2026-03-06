"""
Экстрактор данных рецептов для сайта godt.no
"""

import logging
import sys
import json
import re
from pathlib import Path
from typing import Optional, Union
from bs4 import Comment, NavigableString

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class GodtNoExtractor(BaseRecipeExtractor):
    """Экстрактор для godt.no"""

    # ------------------------------------------------------------------ #
    #  Вспомогательные методы                                             #
    # ------------------------------------------------------------------ #

    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлекает первый объект типа Recipe из JSON-LD скриптов."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict) and item.get('@type') == 'Recipe':
                        return item
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в строку вида "N min".

        Args:
            duration: строка вида "PT20M" или "PT1H30M"

        Returns:
            Время в минутах, например "15 min", или None
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

        total_minutes = hours * 60 + minutes
        return f"{total_minutes} min" if total_minutes > 0 else None

    @staticmethod
    def _parse_amount(text: str) -> Optional[Union[int, float]]:
        """
        Пробует разобрать строку как число (int или float).

        "8 - 10" → 8 (берём первое число)
        "0.5"    → 0.5
        "2"      → 2
        ""       → None
        """
        if not text:
            return None
        # Берём первое число из строки вида "8 - 10" или "8-10"
        match = re.search(r'\d+[.,]?\d*', text.strip())
        if not match:
            return None
        raw = match.group(0).replace(',', '.')
        try:
            value = float(raw)
            return int(value) if value == int(value) else value
        except ValueError:
            return None

    # ------------------------------------------------------------------ #
    #  Извлечение отдельных полей                                         #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из JSON-LD."""
        recipe = self._get_recipe_json_ld()
        if recipe:
            name = recipe.get('name')
            if name:
                # Убираем суффикс типа " - En god start på dagen"
                name = re.split(r'\s*[-–]\s*', name)[0]
                return self.clean_text(name)

        # Запасной вариант — из <h1>
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        return None

    def extract_description(self) -> Optional[str]:
        """
        Извлечение описания рецепта из HTML-элемента p.on.

        Логика:
        - Если p.on содержит теги <br>: первая часть до <br><br> — описание.
        - Если <br> нет и JSON-LD инструкции содержат шаг «Tips:»:
          берём первое предложение p.on как описание.
        - Иначе: описание отсутствует (None).
        """
        p = self.soup.find('p', class_='on')
        if not p:
            return None

        has_br = bool(p.find('br'))

        if has_br:
            # Собираем текстовый контент фрагментами, используя <br> как разделитель
            parts = []
            current = []
            for child in p.children:
                if getattr(child, 'name', None) == 'br':
                    part = self.clean_text(' '.join(current))
                    if part:
                        parts.append(part)
                    current = []
                elif isinstance(child, NavigableString) and not isinstance(child, Comment):
                    token = child.strip()
                    if token:
                        current.append(token)
            if current:
                part = self.clean_text(' '.join(current))
                if part:
                    parts.append(part)

            return parts[0] if parts else None

        # Нет <br> — проверяем наличие Tips: в инструкциях
        recipe = self._get_recipe_json_ld()
        if recipe:
            for step in recipe.get('recipeInstructions', []):
                text = step.get('text', '') if isinstance(step, dict) else ''
                if text.startswith('Tips:'):
                    # Есть шаг-подсказка → p.on содержит описание
                    raw = self.clean_text(p.get_text())
                    if raw:
                        # Берём первое предложение
                        first_sentence = re.split(r'(?<=[.!?])\s+', raw)[0]
                        return first_sentence
                    return None

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из HTML-структуры.

        Формат каждого элемента <li>:
          <strong>{amount} {unit}</strong> <!-- -->{name}<!-- -->[, qualifier]

        Возвращает JSON-строку со списком словарей:
          [{"name": ..., "amount": ..., "unit": ...}, ...]
        """
        ingredients = []

        # Находим секцию ингредиентов по id="ingredienser"
        heading = self.soup.find(id='ingredienser')
        if heading is None:
            logger.warning("Секция ингредиентов (id='ingredienser') не найдена")
            return None

        # Ищем все контейнеры div.sc после заголовка
        section = heading.parent  # <a class="oN">
        if section is None:
            return None

        # Ищем родителя секции ингредиентов, в котором находятся все div.sc
        container = section.parent
        if container is None:
            return None

        sc_divs = container.find_all('div', class_='sc')

        for sc_div in sc_divs:
            for li in sc_div.find_all('li'):
                strong = li.find('strong')
                if strong is None:
                    continue

                amount_unit_text = self.clean_text(strong.get_text())

                # Парсим amount и unit из строки вида "300 g", "8 - 10 stk", ""
                if amount_unit_text:
                    au_parts = amount_unit_text.split(None, 1)
                    if len(au_parts) >= 2:
                        # Может быть "8 - 10 stk" → amount_str="8 - 10", unit="stk"
                        # Но также просто "300 g" → amount_str="300", unit="g"
                        # Проверяем, не является ли второй токен числом (диапазон)
                        if re.match(r'^[\d.,\-\s]+$', au_parts[0]) and not re.match(r'^\d', au_parts[1].lstrip('- ')):
                            amount_str = au_parts[0]
                            unit = au_parts[1]
                        else:
                            # Попробуем по-другому: последний токен = единица
                            tokens = amount_unit_text.split()
                            unit = tokens[-1]
                            amount_str = ' '.join(tokens[:-1])
                    else:
                        # Только одно слово — либо только amount (без unit), либо только unit
                        # Пробуем как число
                        if re.match(r'^[\d.,]+$', au_parts[0]):
                            amount_str = au_parts[0]
                            unit = None
                        else:
                            amount_str = ''
                            unit = au_parts[0]
                    amount = self._parse_amount(amount_str)
                    unit = self.clean_text(unit) if unit else None
                else:
                    amount = None
                    unit = None

                # Извлекаем название: первый непустой NavigableString после <strong>
                name_parts = []
                found_strong = False
                for child in li.children:
                    if getattr(child, 'name', None) == 'strong':
                        found_strong = True
                        continue
                    if not found_strong:
                        continue
                    if isinstance(child, Comment):
                        continue
                    if isinstance(child, NavigableString):
                        token = str(child).strip()
                        if token:
                            name_parts.append(token)
                            break  # Берём только первый фрагмент имени

                if not name_parts:
                    # Запасной вариант — весь текст li минус strong
                    full_text = li.get_text().strip()
                    au_clean = amount_unit_text.strip()
                    name_candidate = full_text.replace(au_clean, '').strip().lstrip(',').strip()
                    if name_candidate:
                        name_parts = [name_candidate]

                if not name_parts:
                    continue

                name = self.clean_text(name_parts[0])
                if not name:
                    continue

                ingredients.append({
                    "name": name,
                    "amount": amount,
                    "unit": unit,
                })

        if not ingredients:
            # Запасной вариант: используем JSON-LD recipeIngredient
            logger.warning("Ингредиенты не найдены в HTML, используем JSON-LD")
            recipe = self._get_recipe_json_ld()
            if recipe:
                for raw_ing in recipe.get('recipeIngredient', []):
                    parsed = self._parse_ingredient_string(raw_ing)
                    if parsed:
                        ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def _parse_ingredient_string(self, text: str) -> Optional[dict]:
        """
        Запасной парсинг строки ингредиента вида "2 dl blåbær".

        Returns:
            {"name": ..., "amount": ..., "unit": ...} или None
        """
        if not text:
            return None
        text = self.clean_text(text)
        match = re.match(r'^([\d.,\s\-]+)?\s*(\S+)?\s+(.+)$', text)
        if match:
            amount_str, unit, name = match.groups()
            amount = self._parse_amount(amount_str or '')
            return {
                "name": name.strip(),
                "amount": amount,
                "unit": unit.strip() if unit else None,
            }
        return {"name": text, "amount": None, "unit": None}

    def extract_instructions(self) -> Optional[str]:
        """
        Извлечение шагов приготовления из JSON-LD.

        Все шаги (в том числе начинающиеся с «Tips:») включаются в инструкции.
        """
        recipe = self._get_recipe_json_ld()
        if not recipe:
            return None

        steps = []
        for step in recipe.get('recipeInstructions', []):
            text = step.get('text', '').strip() if isinstance(step, dict) else str(step).strip()
            if text:
                steps.append(self.clean_text(text))

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта из JSON-LD."""
        recipe = self._get_recipe_json_ld()
        if recipe:
            category = recipe.get('recipeCategory')
            if category:
                # "frokost, lunsj" → "Frokost" (первый элемент, с заглавной буквы)
                first = category.split(',')[0].strip()
                return first.capitalize() if first else None

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки из JSON-LD performTime."""
        recipe = self._get_recipe_json_ld()
        if recipe:
            for key in ('performTime', 'prepTime'):
                value = recipe.get(key)
                if value:
                    return self._parse_iso_duration(value)
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки из JSON-LD cookTime."""
        recipe = self._get_recipe_json_ld()
        if recipe:
            value = recipe.get('cookTime')
            if value:
                return self._parse_iso_duration(value)
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени из JSON-LD totalTime."""
        recipe = self._get_recipe_json_ld()
        if not recipe:
            return None
        value = recipe.get('totalTime')
        if not value:
            return None
        # Если totalTime совпадает с performTime/prepTime, не дублируем
        for key in ('performTime', 'prepTime'):
            if recipe.get(key) == value:
                return None
        return self._parse_iso_duration(value)

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок/советов.

        Логика:
        - Если p.on содержит <br>: всё после первого <br> — заметки.
        - Если p.on без <br> и в инструкциях есть шаг «Tips:»:
          заметки — текст после «Tips: » (первое предложение).
        - Если p.on без <br> и нет Tips: в инструкциях:
          весь текст p.on — заметки.
        """
        p = self.soup.find('p', class_='on')
        if not p:
            return None

        has_br = bool(p.find('br'))

        if has_br:
            # Собираем части, разделённые <br>
            parts = []
            current = []
            for child in p.children:
                if getattr(child, 'name', None) == 'br':
                    part = self.clean_text(' '.join(current))
                    if part:
                        parts.append(part)
                    current = []
                elif isinstance(child, NavigableString) and not isinstance(child, Comment):
                    token = child.strip()
                    if token:
                        current.append(token)
            if current:
                part = self.clean_text(' '.join(current))
                if part:
                    parts.append(part)

            # Всё, кроме первой части — заметки
            if len(parts) > 1:
                return ' '.join(parts[1:])
            return None

        # Нет <br>
        recipe = self._get_recipe_json_ld()
        if recipe:
            for step in recipe.get('recipeInstructions', []):
                text = step.get('text', '') if isinstance(step, dict) else ''
                if text.startswith('Tips:'):
                    # Берём первое предложение после «Tips: »
                    tips_body = re.sub(r'^Tips:\s*', '', text)
                    first_sentence = re.split(r'(?<=[.!?])\s+', tips_body)[0]
                    return self.clean_text(first_sentence) or None

        # Нет Tips: → весь p.on — заметки
        raw = self.clean_text(p.get_text())
        return raw or None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords."""
        recipe = self._get_recipe_json_ld()
        if recipe:
            keywords = recipe.get('keywords')
            if keywords:
                return self.clean_text(keywords)
        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Извлечение URL изображений: основное фото и фото из шагов рецепта.

        Возвращает URL через запятую без пробелов или None.
        """
        urls = []
        seen: set[str] = set()

        def _add(url: str) -> None:
            url = url.strip()
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        # og:image — главное фото
        og = self.soup.find('meta', property='og:image')
        if og and og.get('content'):
            _add(og['content'])

        # JSON-LD: recipe image + step images
        recipe = self._get_recipe_json_ld()
        if recipe:
            img = recipe.get('image')
            if isinstance(img, list):
                for i in img:
                    if isinstance(i, str):
                        _add(i)
            elif isinstance(img, str):
                _add(img)

            for step in recipe.get('recipeInstructions', []):
                if not isinstance(step, dict):
                    continue
                step_img = step.get('image')
                if isinstance(step_img, list):
                    for i in step_img:
                        if isinstance(i, str):
                            _add(i)
                elif isinstance(step_img, str):
                    _add(step_img)

        return ','.join(urls) if urls else None

    # ------------------------------------------------------------------ #
    #  Основной метод                                                      #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с полями: dish_name, description, ingredients, instructions,
            category, prep_time, cook_time, total_time, notes, tags, image_urls.
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception as e:
            logger.error("Ошибка при извлечении dish_name: %s", e)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as e:
            logger.error("Ошибка при извлечении description: %s", e)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as e:
            logger.error("Ошибка при извлечении ingredients: %s", e)
            ingredients = None

        try:
            instructions = self.extract_instructions()
        except Exception as e:
            logger.error("Ошибка при извлечении instructions: %s", e)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as e:
            logger.error("Ошибка при извлечении category: %s", e)
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception as e:
            logger.error("Ошибка при извлечении prep_time: %s", e)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception as e:
            logger.error("Ошибка при извлечении cook_time: %s", e)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception as e:
            logger.error("Ошибка при извлечении total_time: %s", e)
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception as e:
            logger.error("Ошибка при извлечении notes: %s", e)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as e:
            logger.error("Ошибка при извлечении tags: %s", e)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as e:
            logger.error("Ошибка при извлечении image_urls: %s", e)
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
            "tags": tags,
            "image_urls": image_urls,
        }


def main() -> None:
    import os
    recipes_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'preprocessed', 'godt_no'
    )
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(GodtNoExtractor, recipes_dir)
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Убедитесь, что директория preprocessed/godt_no существует.")


if __name__ == "__main__":
    main()
