"""
Экстрактор данных рецептов для сайта theveganatlas.com
Сайт использует WordPress с плагином MV Create для рецептов.
Основной источник данных — JSON-LD Recipe schema, дополнительный — HTML карточка рецепта.
"""

import html as html_module
import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional, Set

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class TheVeganAtlasComExtractor(BaseRecipeExtractor):
    """Экстрактор для theveganatlas.com"""

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в человекочитаемый формат (например, "30 minutes").

        Args:
            duration: строка вида "PT20M" или "PT1H30M"

        Returns:
            Строка вида "N minutes" или None
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
        if total_minutes <= 0:
            return None

        return f"{total_minutes} minutes"

    def _get_recipe_jsonld(self) -> Optional[dict]:
        """Возвращает первый JSON-LD объект с @type == 'Recipe', или None."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
            except (json.JSONDecodeError, ValueError):
                continue

            # Прямой Recipe объект
            if isinstance(data, dict):
                if data.get('@type') == 'Recipe':
                    return data
                # @graph — список объектов
                for item in data.get('@graph', []):
                    if isinstance(item, dict) and item.get('@type') == 'Recipe':
                        return item

            # Массив на верхнем уровне
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get('@type') == 'Recipe':
                        return item

        return None

    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат.

        Поддерживает форматы:
          "10 to 12 ounces linguine or spaghetti"
          "1 medium or 2 small zucchini, sliced"
          "1/4 cup bottled teriyaki marinade"
          "14-ounce tub extra-firm tofu"
          "Salt and freshly ground pepper to taste"

        Returns:
            dict {"name": str, "amount": str|None, "unit": str|None} или None
        """
        if not ingredient_text:
            return None

        text = self.clean_text(ingredient_text)

        # Заменяем Unicode дроби
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5',
        }
        for frac, repl in fraction_map.items():
            text = text.replace(frac, repl)

        # Убираем невидимые Unicode разделители строк и т.п.
        text = re.sub(r'[\u2028\u2029\u00a0]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        if not text:
            return None

        # Единицы измерения (и нестандартные вроде "tub", "stick")
        units_pattern = (
            r'cups?|tablespoons?|teaspoons?|tbsps?|tsps?'
            r'|pounds?|ounces?|oz|lbs?'
            r'|grams?|kilograms?|g|kg'
            r'|milliliters?|liters?|ml|l'
            r'|pinch(?:es)?|dash(?:es)?'
            r'|packages?|pkgs?|cans?|jars?|bottles?'
            r'|slices?|cloves?|bunches?|sprigs?|pieces?|heads?'
            r'|tubs?|sticks?|handfuls?|quarts?|pints?'
        )

        # Паттерн: [число/диапазон] [единица] [название]
        # Диапазон: "1 to 2", "2 to 3", "10 to 12"
        # Смешанная дробь: "1 1/2", "2 1/4"
        number_re = r'\d+(?:\s*/\s*\d+)?(?:\s+\d+/\d+)?'
        range_re = rf'(?:{number_re})(?:\s+to\s+(?:{number_re}))?'

        pattern = (
            rf'^({range_re})'                      # группа 1: количество (или диапазон)
            rf'(?:\s*[-\u2013]?\s*({units_pattern}))?' # группа 2: единица (опционально)
            rf'[\s-]*(.+)'                          # группа 3: название
        )

        match = re.match(pattern, text, re.IGNORECASE)

        if not match:
            # Если нет числа в начале — считаем весь текст названием
            name = self._clean_ingredient_name(text)
            return {"name": name, "amount": None, "unit": None} if name else None

        raw_amount, unit, name = match.group(1), match.group(2), match.group(3)

        amount = raw_amount.strip() if raw_amount else None
        unit = unit.strip() if unit else None
        name = self._clean_ingredient_name(name) if name else None

        if not name or len(name) < 2:
            return None

        return {"name": name, "amount": amount, "unit": unit}

    @staticmethod
    def _clean_ingredient_name(name: str) -> str:
        """Очищает название ингредиента от лишних фраз."""
        # Убираем описания в скобках
        name = re.sub(r'\([^)]*\)', '', name)

        # Убираем бытовые пояснения после запятой (применяем несколько раз для вложенных)
        desc_pattern = re.compile(
            r',\s*(thinly sliced|sliced|diced|chopped|minced|trimmed|halved'
            r'|quartered|grated|shredded|peeled|cleaned|stemmed|optional.*'
            r'|cut into[^,]*|any variety[^,]*|any color[^,]*)$',
            re.IGNORECASE
        )
        for _ in range(3):  # максимум 3 прохода для удаления нескольких суффиксов
            new = desc_pattern.sub('', name)
            if new == name:
                break
            name = new

        # Убираем "to taste", "optional", "for garnish", "or so", "plus more", и т.п.
        name = re.sub(
            r'\b(to taste|as needed|or more|if needed|optional|for garnish'
            r'|more or less to taste|plus more\s*[^,]*|or so'
            r'|to your liking|if desired)\b',
            '', name, flags=re.IGNORECASE
        )
        # Убираем префикс "or so " в начале
        name = re.sub(r'^or so\s+', '', name, flags=re.IGNORECASE)
        # Убираем висящий "or" или "and" в конце строки (после чисток выше)
        name = re.sub(r'\s+(or|and)\s*$', '', name, flags=re.IGNORECASE)
        # Убираем повторяющиеся/лишние запятые (", ,", ",," и т.п.)
        name = re.sub(r'(\s*,\s*){2,}', ', ', name)
        name = re.sub(r'\s+', ' ', name).strip()
        # Убираем trailing пунктуацию (запятые, точки с запятой, двоеточия)
        name = name.rstrip(',.;:')
        return name.strip()

    # --------------------------------------------------------------- extractors

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда."""
        # Приоритет: h1.entry-title → JSON-LD name → og:title
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            return self.clean_text(h1.get_text())

        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('name'):
            return self.clean_text(html_module.unescape(recipe['name']))

        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*[-|]\s*The Vegan Atlas\s*$', '', title, flags=re.I)
            return self.clean_text(title)

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта."""
        # Приоритет: JSON-LD description → mv-create-desc → meta description
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('description'):
            desc = self.clean_text(html_module.unescape(recipe['description']))
            if desc:
                return desc

        desc_div = self.soup.find(class_='mv-create-desc')
        if desc_div:
            desc = self.clean_text(desc_div.get_text())
            if desc:
                return desc

        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из HTML-карточки рецепта (MV Create)."""
        ingredients = []

        # Основной источник: div.mv-create-ingredients ul li
        ing_section = self.soup.find(class_='mv-create-ingredients')
        if ing_section:
            items = ing_section.find_all('li')
            for item in items:
                raw = self.clean_text(item.get_text(separator=' '))
                if not raw:
                    continue
                parsed = self.parse_ingredient(raw)
                if parsed:
                    ingredients.append(parsed)

        # Запасной вариант: JSON-LD recipeIngredient
        if not ingredients:
            recipe = self._get_recipe_jsonld()
            if recipe:
                for raw in recipe.get('recipeIngredient', []):
                    # Убираем невидимые разделители
                    raw = re.sub(r'[\u2028\u2029\u00a0]', ' ', raw).strip()
                    parsed = self.parse_ingredient(raw)
                    if parsed:
                        ingredients.append(parsed)

        if not ingredients:
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций (шагов) из JSON-LD или HTML."""
        steps = []

        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('recipeInstructions'):
            for step in recipe['recipeInstructions']:
                if isinstance(step, dict):
                    step_text = step.get('text', '') or step.get('name', '')
                elif isinstance(step, str):
                    step_text = step
                else:
                    continue
                step_text = self.clean_text(html_module.unescape(step_text))
                if step_text:
                    steps.append(step_text)

        if steps:
            return ' '.join(steps)

        # Запасной вариант: HTML div.mv-create-instructions
        instructions_section = self.soup.find(class_='mv-create-instructions')
        if instructions_section:
            for item in instructions_section.find_all('li'):
                text = self.clean_text(item.get_text(separator=' '))
                if text:
                    steps.append(text)

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда."""
        # Приоритет: JSON-LD recipeCategory → mv-create-category
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('recipeCategory'):
            cat = recipe['recipeCategory']
            if isinstance(cat, list):
                cat = cat[0] if cat else None
            if cat:
                return self.clean_text(html_module.unescape(cat))

        cat_elem = self.soup.find(class_='mv-create-category')
        if cat_elem:
            text = self.clean_text(cat_elem.get_text())
            # Убираем префикс "Category: "
            text = re.sub(r'^Category:\s*', '', text, flags=re.I)
            if text:
                return text

        return None

    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total).

        Args:
            time_type: 'prep', 'cook', или 'total'

        Returns:
            Строка вида "N minutes" или None
        """
        jsonld_key_map = {
            'prep': 'prepTime',
            'cook': 'cookTime',
            'total': 'totalTime',
        }
        html_class_map = {
            'prep': 'mv-create-time-prep',
            'cook': 'mv-create-time-active',
            'total': 'mv-create-time-total',
        }

        # Сначала пробуем JSON-LD
        recipe = self._get_recipe_jsonld()
        if recipe:
            key = jsonld_key_map.get(time_type)
            if key and recipe.get(key):
                result = self._parse_iso_duration(recipe[key])
                if result:
                    return result

        # Запасной вариант: HTML карточка
        css_class = html_class_map.get(time_type)
        if css_class:
            time_block = self.soup.find(class_=css_class)
            if time_block:
                fmt = time_block.find(class_='mv-create-time-format')
                if fmt:
                    return self.clean_text(fmt.get_text())
                # Берём весь текст блока, убирая метку
                text = self.clean_text(time_block.get_text(separator=' '))
                text = re.sub(r'^(Prep|Cook|Active|Total)\s+Time\s*', '', text, flags=re.I)
                if text:
                    return text

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки."""
        return self.extract_time('prep')

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления."""
        return self.extract_time('cook')

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени."""
        return self.extract_time('total')

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов к рецепту."""
        notes_content = self.soup.find(class_='mv-create-notes-content')
        if notes_content:
            text = self.clean_text(notes_content.get_text(separator=' '))
            # Убираем пробел перед знаками препинания (артефакт get_text с separator)
            text = re.sub(r'\s+([.,;:!?])', r'\1', text)
            text = text.strip()
            if text:
                return text

        # Запасной вариант: вся секция заметок
        notes_section = self.soup.find(class_='mv-create-notes')
        if notes_section:
            # Убираем заголовок "Notes"
            title = notes_section.find(class_='mv-create-notes-title')
            if title:
                title.decompose()
            text = self.clean_text(notes_section.get_text(separator=' '))
            text = re.sub(r'\s+([.,;:!?])', r'\1', text)
            text = text.strip()
            if text:
                return text

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из ссылок <a rel='tag'>."""
        tags = []
        for tag_link in self.soup.find_all('a', rel='tag'):
            tag_text = self.clean_text(tag_link.get_text())
            if tag_text:
                tags.append(tag_text.lower())

        # Удаляем дубликаты, сохраняя порядок
        seen: Set[str] = set()
        unique_tags = []
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)

        return ', '.join(unique_tags) if unique_tags else None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из JSON-LD и мета-тегов."""
        urls = []

        # JSON-LD Recipe image (список или строка)
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
                        urls.append(i.get('url') or i.get('contentUrl', ''))

        # og:image — запасной источник
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # Убираем дубликаты, сохраняя порядок
        seen: Set[str] = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ','.join(unique_urls) if unique_urls else None

    # --------------------------------------------------------------- main entry

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта в стандартном формате проекта.
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception:
            logger.exception("Ошибка при извлечении dish_name из %s", self.html_path)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception:
            logger.exception("Ошибка при извлечении description из %s", self.html_path)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception:
            logger.exception("Ошибка при извлечении ingredients из %s", self.html_path)
            ingredients = None

        try:
            instructions = self.extract_instructions()
        except Exception:
            logger.exception("Ошибка при извлечении instructions из %s", self.html_path)
            instructions = None

        try:
            category = self.extract_category()
        except Exception:
            logger.exception("Ошибка при извлечении category из %s", self.html_path)
            category = None

        try:
            notes = self.extract_notes()
        except Exception:
            logger.exception("Ошибка при извлечении notes из %s", self.html_path)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception:
            logger.exception("Ошибка при извлечении tags из %s", self.html_path)
            tags = None

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


def main() -> None:
    """
    Точка входа модуля.
    Обрабатывает все HTML-файлы из директории preprocessed/theveganatlas_com.
    """
    import os

    recipes_dir = os.path.join("preprocessed", "theveganatlas_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(TheVeganAtlasComExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Убедитесь, что скрипт запускается из корня репозитория.")


if __name__ == "__main__":
    main()
