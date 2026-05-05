"""
Экстрактор данных рецептов для сайта lifehacker.ru

Структура HTML страницы lifehacker.ru:
 - JSON-LD (type="application/ld+json", data-hid="recipe_schema"): поля name, description,
   recipeIngredient, recipeInstructions, totalTime/cookTime/prepTime, recipeCategory,
   recipeCuisine, keywords, image
 - Ингредиенты: <section class="base-list base-list--"> > h2.base-list__title("Ингредиенты")
     каждый элемент: div.base-list__item-name + div.base-list__item-count ("amount unit")
 - Шаги: <section class="cooking-steps"> > ol.cooking-steps__items > li.cooking-steps__item
     текст шага в div.cooking-steps__item-content > p
     примечания в div.wp-block-lh-bb-recipe-note > span.recipe-note-block__content
 - Время: <section class="base-list"> с p.base-list__title("Время приготовления")
     "Общее" -> total_time, "Активное" -> prep_time
 - Категории: div.the-recipe__categories-wrapper > a.recipe-category-link
 - Изображения: JSON-LD image + meta og:image
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


class LifehackerRuExtractor(BaseRecipeExtractor):
    """Экстрактор для lifehacker.ru"""

    def _get_recipe_jsonld(self) -> Optional[dict]:
        """Получение данных рецепта из JSON-LD (тип Recipe)"""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                # Прямой тип Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                # @graph со вложенным Recipe
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                # Массив объектов
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат на английском.

        Args:
            duration: строка вида "PT20M", "PT1H30M", "PT2H"

        Returns:
            Строка вида "15 minutes", "1 hour 30 minutes", "2 hours" или None
        """
        if not duration or not duration.startswith('PT'):
            return None

        rest = duration[2:]  # Убираем "PT"
        hours = 0
        minutes = 0

        h_match = re.search(r'(\d+)H', rest)
        if h_match:
            hours = int(h_match.group(1))

        m_match = re.search(r'(\d+)M', rest)
        if m_match:
            minutes = int(m_match.group(1))

        if not hours and not minutes:
            return None

        parts = []
        if hours == 1:
            parts.append("1 hour")
        elif hours > 1:
            parts.append(f"{hours} hours")
        if minutes == 1:
            parts.append("1 minute")
        elif minutes > 1:
            parts.append(f"{minutes} minutes")

        return ' '.join(parts) if parts else None

    @staticmethod
    def _parse_ru_time(time_str: str) -> Optional[str]:
        """
        Конвертирует русскую строку времени в читаемый формат на английском.

        Args:
            time_str: строка вида "1 ч. 30 мин.", "15 мин.", "2 ч."

        Returns:
            Строка вида "1 hour 30 minutes", "15 minutes", "2 hours" или None
        """
        if not time_str:
            return None

        hours = 0
        minutes = 0

        h_match = re.search(r'(\d+)\s*ч', time_str)
        if h_match:
            hours = int(h_match.group(1))

        m_match = re.search(r'(\d+)\s*мин', time_str)
        if m_match:
            minutes = int(m_match.group(1))

        if not hours and not minutes:
            return None

        parts = []
        if hours == 1:
            parts.append("1 hour")
        elif hours > 1:
            parts.append(f"{hours} hours")
        if minutes == 1:
            parts.append("1 minute")
        elif minutes > 1:
            parts.append(f"{minutes} minutes")

        return ' '.join(parts) if parts else None

    @staticmethod
    def _parse_ingredient_count(count_str: str) -> tuple:
        """
        Разбирает строку "количество единица" на (amount, unit).

        Примеры:
            "1 штука"               -> ("1", "штука")
            "2–3 пучка"             -> ("2–3", "пучка")
            "180 мл"                -> ("180", "мл")
            "2 ст. ложки + ..."     -> ("2", "ст. ложки + ...")
            "½ ч. ложки"            -> ("½", "ч. ложки")
            "по вкусу"              -> ("по вкусу", None)
        """
        count_str = count_str.strip()
        if not count_str:
            return None, None

        # Специальные случаи — "по вкусу" и подобные
        lower = count_str.lower()
        if lower.startswith('по вкусу') or lower.startswith('по желанию') or \
                lower in ('для украшения', 'для жарки', 'для смазывания'):
            return count_str, None

        # Числовой паттерн: целое / диапазон с en-dash или дефисом / Unicode дробь
        amount_re = (
            r'^('
            r'[\d]+(?:[.,]\d+)?'                      # integer or decimal
            r'(?:\s*[–—\-]\s*[\d]+(?:[.,]\d+)?)?'    # optional range
            r'|[½¼¾⅓⅔⅛⅜⅝⅞]'                          # single unicode fraction
            r')\s*(.*)'
        )
        m = re.match(amount_re, count_str, re.UNICODE)
        if m:
            amount = m.group(1).strip()
            unit = m.group(2).strip() or None
            return amount, unit

        # Не удалось разобрать — возвращаем всё как amount
        return count_str, None

    # ------------------------------------------------------------------
    # Основные методы извлечения
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self._get_recipe_jsonld()
        if recipe_data and recipe_data.get('name'):
            return self.clean_text(recipe_data['name'])

        # Fallback: og:title (убираем суффикс " — Лайфхакер")
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*[—–\-]+\s*Лайфхакер\s*$', '', title)
            return self.clean_text(title)

        # Fallback: первый h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Первичный источник: HTML блок recipe-description (текст, показываемый на странице)
        desc_block = self.soup.find(class_='recipe-description')
        if desc_block:
            text = self.clean_text(desc_block.get_text(separator=' ', strip=True))
            if text:
                return text

        # Fallback: из JSON-LD Recipe
        recipe_data = self._get_recipe_jsonld()
        if recipe_data and recipe_data.get('description'):
            return self.clean_text(recipe_data['description'])

        # Fallback: og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из HTML секции "Ингредиенты".

        Возвращает JSON-строку списка словарей вида:
            [{"name": "Лук", "amount": "1", "unit": "штука"}, ...]
        или None.
        """
        ingredients = []

        # Ищем секцию base-list с заголовком "Ингредиенты"
        ingredient_section = None
        for section in self.soup.find_all(class_='base-list'):
            title_el = section.find(class_='base-list__title')
            if title_el and 'Ингредиент' in title_el.get_text():
                ingredient_section = section
                break

        if ingredient_section:
            for item in ingredient_section.find_all(class_='base-list__item'):
                name_el = item.find(class_='base-list__item-name')
                count_el = item.find(class_='base-list__item-count')

                if not name_el:
                    continue

                # Используем только прямые текстовые узлы name_el (не вложенные теги)
                direct_texts = [
                    child.get_text(strip=True) if hasattr(child, 'get_text')
                    else str(child).strip()
                    for child in name_el.children
                    if not (hasattr(child, 'name') and child.name == 'p')
                ]
                name = self.clean_text(' '.join(t for t in direct_texts if t))

                amount = None
                unit = None
                if count_el:
                    count_str = self.clean_text(count_el.get_text(strip=True))
                    if count_str:
                        amount, unit = self._parse_ingredient_count(count_str)

                if name:
                    ingredients.append({
                        "name": name,
                        "unit": unit,
                        "amount": amount
                    })

            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        # Fallback: из JSON-LD recipeIngredient (строки "Название Количество Единица")
        recipe_data = self._get_recipe_jsonld()
        if recipe_data and 'recipeIngredient' in recipe_data:
            for ing_str in recipe_data['recipeIngredient']:
                ing_str = self.clean_text(str(ing_str))
                if not ing_str:
                    continue

                # Сначала ищем "по вкусу" / "по желанию"
                m_special = re.match(
                    r'^(.+?)\s+(по вкусу|по желанию)$', ing_str, re.IGNORECASE
                )
                if m_special:
                    ingredients.append({
                        "name": m_special.group(1).strip(),
                        "unit": None,
                        "amount": m_special.group(2).strip(),
                    })
                    continue

                # Ищем позицию первой цифры / Unicode дроби
                m_num = re.match(
                    r'^(.+?)\s+([\d½¼¾⅓⅔⅛⅜⅝⅞].*)$', ing_str
                )
                if m_num:
                    name = m_num.group(1).strip()
                    rest = m_num.group(2).strip()
                    amount, unit = self._parse_ingredient_count(rest)
                    ingredients.append({"name": name, "unit": unit, "amount": amount})
                else:
                    ingredients.append({"name": ing_str, "unit": None, "amount": None})

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def _extract_steps_and_notes(self) -> tuple:
        """
        Извлечение шагов приготовления и примечаний.

        Returns:
            (steps: list[str], notes: list[str])
        """
        if hasattr(self, '_cached_steps_notes'):
            return self._cached_steps_notes

        steps = []
        notes = []

        cooking_section = self.soup.find(class_='cooking-steps__items')
        if cooking_section:
            for item in cooking_section.find_all('li', class_='cooking-steps__item'):
                content = item.find(class_='cooking-steps__item-content')
                if not content:
                    continue

                # Собираем примечания (wp-block-lh-bb-recipe-note)
                for note_block in content.find_all(class_='wp-block-lh-bb-recipe-note'):
                    note_span = note_block.find(class_='recipe-note-block__content')
                    if note_span:
                        note_text = self.clean_text(note_span.get_text(strip=True))
                        if note_text:
                            notes.append(note_text)

                # Собираем текст шага: параграфы, не являющиеся вложенными в note-блоки
                step_parts = []
                for p in content.find_all('p'):
                    if p.find_parent(class_='wp-block-lh-bb-recipe-note'):
                        continue
                    p_text = self.clean_text(p.get_text(strip=True))
                    if p_text:
                        step_parts.append(p_text)

                if step_parts:
                    steps.append(' '.join(step_parts))

        if not steps:
            # Fallback: из JSON-LD recipeInstructions
            recipe_data = self._get_recipe_jsonld()
            if recipe_data and 'recipeInstructions' in recipe_data:
                for idx, instruction in enumerate(recipe_data['recipeInstructions'], 1):
                    if isinstance(instruction, dict):
                        text = instruction.get('text', '')
                    elif isinstance(instruction, str):
                        text = instruction
                    else:
                        continue

                    # Примечание может быть встроено после "\n\n\n"
                    parts = text.split('\n\n\n', 1)
                    step_text = self.clean_text(parts[0])
                    if len(parts) > 1:
                        note_text = self.clean_text(parts[1])
                        if note_text:
                            notes.append(note_text)

                    if step_text:
                        steps.append(f"{idx}. {step_text}")

        self._cached_steps_notes = (steps, notes)
        return steps, notes

    def extract_steps(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению (все шаги в одной строке)"""
        steps, _ = self._extract_steps_and_notes()
        if not steps:
            return None
        return ' '.join(steps)

    def extract_notes(self) -> Optional[str]:
        """Извлечение примечаний / советов из шагов рецепта"""
        _, notes = self._extract_steps_and_notes()
        if not notes:
            return None
        return ' '.join(notes)

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда"""
        # Из HTML блока категорий рецепта
        categories_wrapper = self.soup.find(class_='the-recipe__categories-wrapper')
        if categories_wrapper:
            links = categories_wrapper.find_all('a', class_='recipe-category-link')
            cats = [self.clean_text(link.get_text()) for link in links
                    if link.get_text(strip=True)]
            if cats:
                # Первая ссылка — тип блюда; остальные — кухни
                return cats[0]

        # Fallback: из JSON-LD recipeCategory
        recipe_data = self._get_recipe_jsonld()
        if recipe_data and recipe_data.get('recipeCategory'):
            return self.clean_text(str(recipe_data['recipeCategory']))

        return None

    def _extract_time_from_html(self) -> dict:
        """
        Извлечение времени из HTML секции "Время приготовления".

        Returns:
            {"active": str|None, "total": str|None}
        """
        times = {'active': None, 'total': None}

        for title_el in self.soup.find_all(class_='base-list__title'):
            if 'Время приготовления' not in title_el.get_text():
                continue

            # Находим родительскую секцию
            section = title_el.find_parent('section') or title_el.parent

            for item in section.find_all(class_='base-list__item'):
                name_el = item.find(class_='base-list__item-name')
                count_el = item.find(class_='base-list__item-count')

                if not name_el or not count_el:
                    continue

                name_text = name_el.get_text(separator=' ', strip=True).lower()
                count_text = count_el.get_text(strip=True)

                if 'общ' in name_text:
                    times['total'] = self._parse_ru_time(count_text)
                elif 'актив' in name_text:
                    times['active'] = self._parse_ru_time(count_text)

            break

        return times

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение активного времени приготовления (prep_time)"""
        times = self._extract_time_from_html()
        if times['active']:
            return times['active']

        # Fallback: JSON-LD cookTime (на lifehacker.ru соответствует "Активному" времени)
        recipe_data = self._get_recipe_jsonld()
        if recipe_data and recipe_data.get('cookTime'):
            return self._parse_iso_duration(recipe_data['cookTime'])

        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления (cook_time)"""
        # На lifehacker.ru нет явного поля для времени готовки в HTML.
        # Страница показывает только "Активное" (prep) и "Общее" (total).
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени приготовления"""
        times = self._extract_time_from_html()
        if times['total']:
            return times['total']

        # Fallback: JSON-LD totalTime
        recipe_data = self._get_recipe_jsonld()
        if recipe_data and recipe_data.get('totalTime'):
            return self._parse_iso_duration(recipe_data['totalTime'])

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords"""
        recipe_data = self._get_recipe_jsonld()
        if not recipe_data:
            return None

        keywords = recipe_data.get('keywords')
        if not keywords:
            return None

        if isinstance(keywords, str) and keywords.strip():
            tags = [t.strip() for t in re.split(r'[,;]', keywords) if t.strip()]
            return ', '.join(tags) if tags else None

        if isinstance(keywords, list):
            tags = [str(k).strip() for k in keywords if str(k).strip()]
            return ', '.join(tags) if tags else None

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls = []
        seen: set = set()

        def add_url(url: Optional[str]) -> None:
            if url and url.startswith('http') and url not in seen:
                seen.add(url)
                urls.append(url)

        # 1. Из JSON-LD Recipe.image
        recipe_data = self._get_recipe_jsonld()
        if recipe_data:
            img = recipe_data.get('image')
            if isinstance(img, str):
                add_url(img)
            elif isinstance(img, list):
                for i in img:
                    if isinstance(i, str):
                        add_url(i)
                    elif isinstance(i, dict):
                        add_url(i.get('url') or i.get('contentUrl'))
            elif isinstance(img, dict):
                add_url(img.get('url') or img.get('contentUrl'))

        # 2. Из og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            add_url(og_image['content'])

        # 3. Из шагов приготовления (пошаговые фото)
        cooking_section = self.soup.find(class_='cooking-steps__items')
        if cooking_section:
            for fig in cooking_section.find_all('figure'):
                img_tag = fig.find('img')
                if img_tag:
                    src = img_tag.get('src') or img_tag.get('data-src')
                    add_url(src)

        return ','.join(urls) if urls else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с полями: dish_name, description, ingredients, instructions,
            category, prep_time, cook_time, total_time, notes, image_urls, tags
        """
        instructions = self.extract_steps()
        notes = self.extract_notes()

        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": instructions,
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags(),
        }


def main():
    import os
    recipes_dir = os.path.join("preprocessed", "lifehacker_ru")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(LifehackerRuExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python lifehacker_ru.py [путь_к_директории]")


if __name__ == "__main__":
    main()
