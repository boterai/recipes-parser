"""
Экстрактор данных рецептов для сайта kokitjapotit.fi
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


class KokitJaPotitExtractor(BaseRecipeExtractor):
    """Экстрактор для kokitjapotit.fi (сайт на WordPress с плагином WP Recipe Maker)"""

    def _get_graph_data(self) -> list:
        """Извлечение данных из JSON-LD @graph"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    return data['@graph']
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, KeyError):
                continue
        return []

    def _get_recipe_ld(self) -> Optional[dict]:
        """Извлечение данных типа Recipe из JSON-LD @graph"""
        for item in self._get_graph_data():
            if isinstance(item, dict) and item.get('@type') == 'Recipe':
                return item
        return None

    def _get_article_ld(self) -> Optional[dict]:
        """Извлечение данных типа Article из JSON-LD @graph"""
        for item in self._get_graph_data():
            if isinstance(item, dict) and item.get('@type') == 'Article':
                return item
        return None

    def _get_webpage_ld(self) -> Optional[dict]:
        """Извлечение данных типа WebPage из JSON-LD @graph"""
        for item in self._get_graph_data():
            if isinstance(item, dict) and item.get('@type') == 'WebPage':
                return item
        return None

    @staticmethod
    def _format_time(total_minutes: int) -> Optional[str]:
        """
        Форматирует время из минут в читаемый формат.

        Args:
            total_minutes: Общее количество минут

        Returns:
            Строка вида "30 minutes" или "2 hours 30 minutes"
        """
        if total_minutes <= 0:
            return None
        hours = total_minutes // 60
        minutes = total_minutes % 60
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        return ' '.join(parts) if parts else None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[int]:
        """
        Конвертирует ISO 8601 duration в минуты.

        Args:
            duration: строка вида "PT20M" или "PT1H30M"

        Returns:
            Количество минут или None
        """
        if not duration or not duration.startswith('PT'):
            return None
        duration = duration[2:]
        hours = 0
        minutes = 0
        hour_match = re.search(r'(\d+)H', duration)
        if hour_match:
            hours = int(hour_match.group(1))
        min_match = re.search(r'(\d+)M', duration)
        if min_match:
            minutes = int(min_match.group(1))
        total = hours * 60 + minutes
        return total if total > 0 else None

    def _parse_wprm_time_container(self, container) -> int:
        """
        Извлекает время из WPRM-контейнера времени в минутах.

        Args:
            container: BeautifulSoup элемент с классом wprm-recipe-time-container

        Returns:
            Время в минутах
        """
        total = 0
        hours_span = container.find(class_=re.compile(r'wprm-recipe-details-hours'))
        if hours_span:
            # Берём только первый прямой текстовый узел (без дочерних sr-only элементов)
            direct_text = next(hours_span.strings, None)
            try:
                total += int(str(direct_text).strip()) * 60
            except (ValueError, TypeError):
                pass
        minutes_span = container.find(class_=re.compile(r'wprm-recipe-details-minutes'))
        if minutes_span:
            direct_text = next(minutes_span.strings, None)
            try:
                total += int(str(direct_text).strip())
            except (ValueError, TypeError):
                pass
        return total

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_ld = self._get_recipe_ld()
        if recipe_ld and 'name' in recipe_ld:
            return self.clean_text(recipe_ld['name'])

        # Из заголовка H1 страницы
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            name = self.clean_text(h1.get_text())
            # Убираем суффикс после " – " (например: "Tikka masala – subtitle")
            if ' – ' in name:
                name = name.split(' – ')[0].strip()
            return name

        h1 = self.soup.find('h1')
        if h1:
            name = self.clean_text(h1.get_text())
            if ' – ' in name:
                name = name.split(' – ')[0].strip()
            return name

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Приоритет - описание WebPage (более подробное, чем Recipe-описание)
        webpage_ld = self._get_webpage_ld()
        if webpage_ld and 'description' in webpage_ld:
            return self.clean_text(webpage_ld['description'])

        # Из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из WPRM HTML-элементов.
        Возвращает JSON-строку со списком словарей {name, amount, units}.
        """
        ingredients = []

        # Ищем WPRM-элементы ингредиентов в HTML
        items = self.soup.find_all('li', class_='wprm-recipe-ingredient')
        if items:
            for item in items:
                name_span = item.find(class_='wprm-recipe-ingredient-name')
                amount_span = item.find(class_='wprm-recipe-ingredient-amount')
                unit_span = item.find(class_='wprm-recipe-ingredient-unit')

                name = self.clean_text(name_span.get_text()) if name_span else None
                if not name:
                    continue

                amount_text = self.clean_text(amount_span.get_text()) if amount_span else None
                unit_text = self.clean_text(unit_span.get_text()) if unit_span else None

                amount = self._parse_amount(amount_text)
                units = unit_text if unit_text else None

                ingredients.append({
                    "name": name,
                    "units": units,
                    "amount": amount
                })
        else:
            # Запасной вариант: из Recipe JSON-LD recipeIngredient
            recipe_ld = self._get_recipe_ld()
            if recipe_ld and 'recipeIngredient' in recipe_ld:
                for ingredient_text in recipe_ld['recipeIngredient']:
                    parsed = self._parse_ingredient_text(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
            else:
                # Запасной вариант для старых страниц без WPRM:
                # Парсим параграфы в .entry-content
                ingredients = self._extract_ingredients_from_paragraphs()

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def _extract_ingredients_from_paragraphs(self) -> list:
        """
        Парсит ингредиенты из параграфов .entry-content для старых страниц без WPRM.
        Ищет параграфы с паттернами количество + ед.изм + название.
        """
        ingredients = []
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return ingredients

        # Паттерн для ингредиента: начинается с цифры или буквенно-цифровой единицы
        ingredient_pattern = re.compile(
            r'^(\d[\d\s,.–\-]*\s+(?:dl|rkl|tl|g|kg|ml|l|kpl|pkt|pss?|rs?)\s+.+|'
            r'\d[\d\s,.–\-]*\s+.{3,}|'
            r'(?:noin\s+)?\d[\d,.–\-]+\s*.+)',
            re.IGNORECASE
        )

        paragraphs = entry_content.find_all('p')
        for p in paragraphs:
            # Пропускаем параграфы с ссылками как основным содержимым
            if p.find('a') and len(p.get_text(strip=True)) < 50:
                continue
            text = p.get_text(separator=' ', strip=True)
            text = re.sub(r'\s+', ' ', text).strip()
            if not text:
                continue
            # Если параграф выглядит как ингредиент (короткий, начинается с цифры)
            if len(text) < 80 and ingredient_pattern.match(text):
                parsed = self._parse_ingredient_text(text)
                if parsed:
                    ingredients.append(parsed)

        return ingredients

    @staticmethod
    def _parse_amount(amount_text: Optional[str]):
        """
        Преобразует строку количества в число или строку.

        Args:
            amount_text: Строка с количеством (напр. "1", "1–2", "noin 2")

        Returns:
            int, float или строка, или None если пусто
        """
        if not amount_text:
            return None
        text = amount_text.strip()
        if not text:
            return None
        # Заменяем Unicode тире на обычный дефис
        text = text.replace('\u2013', '-').replace('\u2014', '-')
        # Пробуем преобразовать в число
        try:
            val = float(text.replace(',', '.'))
            return int(val) if val == int(val) else val
        except ValueError:
            pass
        # Возвращаем строку как есть (напр. "1-2", "noin 2")
        return text

    def _parse_ingredient_text(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный словарь.
        Используется как запасной вариант при отсутствии WPRM HTML-элементов.

        Args:
            text: строка вида "1 dl tamarinditahnaa"

        Returns:
            dict с полями name, amount, units
        """
        if not text:
            return None
        text = self.clean_text(text)
        # Убираем скобки
        text = re.sub(r'\([^)]*\)', '', text).strip()
        text = re.sub(r'\s+', ' ', text).strip()

        # Пробуем разобрать "количество единица название"
        # Finnish units: dl, rkl, tl, g, kg, ml, l, kpl, pkt
        unit_pattern = (
            r'^([\d\s,.–\-]+)?\s*'
            r'(dl|rkl|tl|g|kg|ml|l|kpl|pkt|ps|rs)\s+'
            r'(.+)$'
        )
        match = re.match(unit_pattern, text, re.IGNORECASE)
        if match:
            amount_str, unit, name = match.groups()
            return {
                "name": name.strip(),
                "units": unit.strip() if unit else None,
                "amount": self._parse_amount(amount_str.strip() if amount_str else None)
            }

        # Пробуем разобрать "количество название" (без единицы)
        simple_match = re.match(r'^([\d\s,.–\-]+)\s+(.+)$', text)
        if simple_match:
            amount_str, name = simple_match.groups()
            return {
                "name": name.strip(),
                "units": None,
                "amount": self._parse_amount(amount_str.strip())
            }

        return {"name": text, "units": None, "amount": None}

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_ld = self._get_recipe_ld()
        if recipe_ld and 'recipeInstructions' in recipe_ld:
            instructions = recipe_ld['recipeInstructions']
            steps = []
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        steps.append(self.clean_text(step['text']))
                    elif isinstance(step, str):
                        steps.append(self.clean_text(step))
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            return ' '.join(steps) if steps else None

        # Запасной вариант: ищем шаги в WPRM HTML
        instruction_items = self.soup.find_all('li', class_='wprm-recipe-instruction')
        if instruction_items:
            steps = [self.clean_text(item.get_text(separator=' ')) for item in instruction_items if item.get_text(strip=True)]
            return ' '.join(steps) if steps else None

        # Ещё один запасной вариант: ищем параграфы в .entry-content
        # (для старых постов без WPRM)
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            # Стараемся найти параграфы с инструкциями (после раздела "Resepti")
            paragraphs = entry_content.find_all('p')
            instruction_texts = []
            in_instructions = False
            for p in paragraphs:
                text = p.get_text(strip=True)
                if not text:
                    continue
                # Пропускаем короткие абзацы и заголовки
                if len(text) < 20:
                    continue
                # Ищем начало раздела с инструкциями
                if re.search(r'Kuori|Lisää|Sekoita|Paista|Keitä|Hienonna|Kuullota|Ota|Ripottele|Tarjoa', text):
                    in_instructions = True
                if in_instructions:
                    # Пропускаем строки, которые являются именами или ссылками
                    if '<a href' in str(p) and len(text) < 50:
                        continue
                    instruction_texts.append(text)
            return ' '.join(instruction_texts) if instruction_texts else None

        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из articleSection или хлебных крошек"""
        article_ld = self._get_article_ld()
        if article_ld and 'articleSection' in article_ld:
            sections = article_ld['articleSection']
            if isinstance(sections, list) and sections:
                return sections[0]
            elif isinstance(sections, str):
                return sections

        # Из хлебных крошек
        breadcrumbs = self.soup.find('nav', id='kadence-breadcrumbs')
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            # Последняя ссылка в хлебных крошках (не считая Home)
            for link in reversed(links):
                text = self.clean_text(link.get_text())
                if text and text.lower() not in ('koti', 'home'):
                    return text

        # Из мета-тегов категорий
        category_links = self.soup.find('span', class_='category-links')
        if category_links:
            first_link = category_links.find('a')
            if first_link:
                return self.clean_text(first_link.get_text())

        return None

    def _extract_time_minutes(self, time_type: str) -> Optional[int]:
        """
        Извлечение времени из WPRM HTML-элементов.

        Args:
            time_type: 'prep', 'cook' или 'total'

        Returns:
            Время в минутах или None
        """
        # Сначала пробуем WPRM HTML-элементы
        container_class = {
            'prep': 'wprm-recipe-prep-time-container',
            'cook': 'wprm-recipe-cook-time-container',
        }.get(time_type)

        if container_class:
            container = self.soup.find(class_=container_class)
            if container:
                minutes = self._parse_wprm_time_container(container)
                if minutes:
                    return minutes

        # Для total time - суммируем prep + cook + custom
        if time_type == 'total':
            total = 0
            for container in self.soup.find_all(class_='wprm-recipe-time-container'):
                total += self._parse_wprm_time_container(container)
            if total:
                return total

        # Запасной вариант - из Recipe JSON-LD
        recipe_ld = self._get_recipe_ld()
        if recipe_ld:
            key = {'prep': 'prepTime', 'cook': 'cookTime', 'total': 'totalTime'}.get(time_type)
            if key and key in recipe_ld:
                return self._parse_iso_duration(recipe_ld[key])

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        minutes = self._extract_time_minutes('prep')
        return self._format_time(minutes) if minutes else None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        minutes = self._extract_time_minutes('cook')
        return self._format_time(minutes) if minutes else None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        minutes = self._extract_time_minutes('total')
        return self._format_time(minutes) if minutes else None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок из WPRM-блока заметок"""
        notes_container = self.soup.find(class_='wprm-recipe-notes-container')
        if notes_container:
            notes_div = notes_container.find(class_='wprm-recipe-notes')
            if notes_div:
                text = self.clean_text(notes_div.get_text(separator=' '))
                # Убираем * в начале (часто встречается как маркер)
                text = re.sub(r'^\*+\s*', '', text)
                return text if text else None
            # Берём весь текст контейнера без заголовка
            header = notes_container.find(class_='wprm-recipe-notes-header')
            text = notes_container.get_text(separator=' ')
            if header:
                text = text.replace(header.get_text(), '', 1)
            text = re.sub(r'^\*+\s*', '', self.clean_text(text))
            return text if text else None

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из Article JSON-LD keywords или .entry-tags"""
        tags = []

        # Из Article JSON-LD keywords
        article_ld = self._get_article_ld()
        if article_ld and 'keywords' in article_ld:
            kws = article_ld['keywords']
            if isinstance(kws, list):
                tags.extend([k for k in kws if k])
            elif isinstance(kws, str):
                tags.append(kws)

        # Из HTML тегов (entry-tags)
        tag_links = self.soup.find_all('a', class_='tag-link')
        for link in tag_links:
            text = self.clean_text(link.get_text())
            # Убираем # перед тегом
            text = text.lstrip('#').strip()
            if text and text not in tags:
                tags.append(text)

        if not tags:
            return None

        # Убираем дубликаты с сохранением порядка
        seen = set()
        unique = []
        for tag in tags:
            key = tag.lower()
            if key not in seen:
                seen.add(key)
                unique.append(tag)

        return ', '.join(unique)

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls = []

        # Из Recipe JSON-LD
        recipe_ld = self._get_recipe_ld()
        if recipe_ld and 'image' in recipe_ld:
            img = recipe_ld['image']
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

        # Из og:image мета-тега
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # Из ImageObject в JSON-LD
        for item in self._get_graph_data():
            if isinstance(item, dict) and item.get('@type') == 'ImageObject':
                url = item.get('url') or item.get('contentUrl')
                if url:
                    urls.append(url)

        # Убираем дубликаты
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ','.join(unique_urls) if unique_urls else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception as e:
            logger.warning("Ошибка при извлечении dish_name: %s", e)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as e:
            logger.warning("Ошибка при извлечении description: %s", e)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as e:
            logger.warning("Ошибка при извлечении ingredients: %s", e)
            ingredients = None

        try:
            instructions = self.extract_steps()
        except Exception as e:
            logger.warning("Ошибка при извлечении instructions: %s", e)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as e:
            logger.warning("Ошибка при извлечении category: %s", e)
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception as e:
            logger.warning("Ошибка при извлечении prep_time: %s", e)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception as e:
            logger.warning("Ошибка при извлечении cook_time: %s", e)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception as e:
            logger.warning("Ошибка при извлечении total_time: %s", e)
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception as e:
            logger.warning("Ошибка при извлечении notes: %s", e)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as e:
            logger.warning("Ошибка при извлечении tags: %s", e)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as e:
            logger.warning("Ошибка при извлечении image_urls: %s", e)
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


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "kokitjapotit_fi")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(KokitJaPotitExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python kokitjapotit_fi.py")


if __name__ == "__main__":
    main()
