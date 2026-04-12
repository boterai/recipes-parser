"""
Экстрактор данных рецептов для сайта flavordrecipes.com
Сайт построен на WordPress + WP Recipe Maker (WPRM).
Основной источник данных — JSON-LD (@graph → Recipe), HTML-элементы WPRM используются как резервный источник.
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


class FlavordrecipesComExtractor(BaseRecipeExtractor):
    """Экстрактор для flavordrecipes.com (WordPress + WP Recipe Maker)"""

    # ------------------------------------------------------------------ #
    # Вспомогательные методы                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_iso_duration(duration: Optional[str]) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в строку вида «X minutes».

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
        if total == 0:
            return '0 minutes'
        return f"{total} minute{'s' if total != 1 else ''}"

    def _get_recipe_json_ld(self) -> Optional[dict]:
        """
        Возвращает словарь типа Recipe из JSON-LD (первый найденный).
        Поддерживает формат { @graph: [...] } и прямой объект.
        """
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
            except json.JSONDecodeError:
                continue

            # Формат { @graph: [...] }
            if isinstance(data, dict) and '@graph' in data:
                for node in data['@graph']:
                    if isinstance(node, dict) and node.get('@type') == 'Recipe':
                        return node
                    # Бывают вложенные списки внутри @graph
                    if isinstance(node, list):
                        for sub in node:
                            if isinstance(sub, dict) and sub.get('@type') == 'Recipe':
                                return sub

            # Прямой объект или список
            if isinstance(data, dict):
                item_type = data.get('@type', '')
                if item_type == 'Recipe' or (isinstance(item_type, list) and 'Recipe' in item_type):
                    return data
            elif isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get('@type', '')
                    if item_type == 'Recipe' or (isinstance(item_type, list) and 'Recipe' in item_type):
                        return item

        return None

    # ------------------------------------------------------------------ #
    # Методы извлечения полей                                              #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Приоритет 1: элемент WPRM
        elem = self.soup.find(class_='wprm-recipe-name')
        if elem:
            return self.clean_text(elem.get_text())

        # Приоритет 2: JSON-LD
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('name'):
            return self.clean_text(recipe['name'])

        # Приоритет 3: h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        # Приоритет 4: og:title (обычно заголовок статьи, а не рецепта)
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение краткого описания рецепта"""
        # Приоритет 1: элемент WPRM (краткое описание рецепта)
        elem = self.soup.find(class_='wprm-recipe-summary')
        if elem:
            text = self.clean_text(elem.get_text())
            # Убираем метку «Recipe Description:» в начале
            text = re.sub(r'^Recipe\s+Description[\s:]*', '', text, flags=re.I).strip()
            if text:
                return text

        # Приоритет 2: JSON-LD description
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('description'):
            return self.clean_text(recipe['description'])

        # Приоритет 3: meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        return None

    def _parse_ingredient_text(self, text: str) -> Optional[dict]:
        """
        Парсит строку ингредиента в структурированный формат.

        Примеры входных строк:
          «1 lb smoked chicken sausage (sliced)»
          «1¾ cups fresh-squeezed lime juice»
          «Salt and pepper to taste»

        Returns:
            dict {"name": ..., "amount": ..., "unit": ...} или None
        """
        if not text:
            return None

        # Убираем ведущие тире / маркеры списка
        text = re.sub(r'^[\-–—•*]\s*', '', text).strip()
        if not text:
            return None

        # Удаляем скобки с содержимым (примечания в скобках)
        text_clean = re.sub(r'\([^)]*\)', '', text).strip()
        text_clean = re.sub(r'\[[^\]]*\]', '', text_clean).strip()

        # Заменяем Unicode дроби на ASCII представления
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5',
        }
        for frac, repl in fraction_map.items():
            text_clean = text_clean.replace(frac, repl)

        units = (
            r'cups?|tablespoons?|teaspoons?|tbsps?|tsps?|'
            r'pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|'
            r'milliliters?|liters?|ml|l|'
            r'pinch(?:es)?|dash(?:es)?|packages?|packets?|cans?|'
            r'jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|'
            r'sprigs?|whole|halves?|quarters?|pieces?|heads?|'
            r'small|medium|large|sticks?|strips?'
        )

        pattern = (
            r'^([\d\s/.,¼½¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘–-]+(?:\s+[\d/]+)?)?'
            r'\s*(' + units + r')?\s*'
            r'(.+)$'
        )

        match = re.match(pattern, text_clean, re.IGNORECASE)
        if not match:
            name = re.sub(r'\s+', ' ', text_clean).strip()
            return {'name': name, 'amount': None, 'unit': None} if name else None

        raw_amount, unit, name = match.groups()

        # Нормализация количества
        amount: Optional[str] = None
        if raw_amount:
            raw_amount = raw_amount.strip().rstrip('–-').strip()
            if raw_amount:
                # Обработка смешанных дробей вида «1 1/2»
                parts = raw_amount.split()
                total = 0.0
                valid = True
                for part in parts:
                    part = part.strip('.,')
                    if not part:
                        continue
                    if '/' in part:
                        try:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        except (ValueError, ZeroDivisionError):
                            valid = False
                            break
                    else:
                        try:
                            total += float(part.replace(',', '.'))
                        except ValueError:
                            valid = False
                            break
                if valid and total > 0:
                    # Возвращаем как строку без лишних нулей
                    amount = str(int(total)) if total == int(total) else str(round(total, 4))
                else:
                    amount = raw_amount if raw_amount else None

        # Нормализация единицы
        unit_str = unit.strip() if unit else None

        # Очистка названия
        name = re.sub(r'\s+', ' ', name).strip()
        name = re.sub(r'[,;.]+$', '', name).strip()
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|for serving)\b', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\s+', ' ', name).strip()

        if not name or len(name) < 2:
            return None

        return {'name': name, 'amount': amount, 'unit': unit_str}

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов.

        Стратегия:
        1. WPRM HTML-элементы с отдельными span для amount/unit/name.
        2. JSON-LD recipeIngredient (текстовые строки) с парсингом.
        """
        ingredients: list[dict] = []

        # ---- Стратегия 1: WPRM structured spans ----
        wprm_items = self.soup.find_all('li', class_='wprm-recipe-ingredient')
        if wprm_items:
            for item in wprm_items:
                amount_elem = item.find(class_='wprm-recipe-ingredient-amount')
                unit_elem = item.find(class_='wprm-recipe-ingredient-unit')
                name_elem = item.find(class_='wprm-recipe-ingredient-name')

                if not name_elem:
                    continue

                name_text = self.clean_text(name_elem.get_text())

                # Пропускаем заголовки секций / пустые строки
                if not name_text:
                    continue
                # Заголовки вида "Ingredients:", "For the Ceviche:", "For the Leche de Tigre"
                if name_text.endswith(':') or re.match(r'^(Ingredients|For\s+the\b)', name_text, re.I):
                    continue
                if name_text.lower().startswith('ingredient'):
                    continue

                # Если amount/unit не заполнены — пробуем разобрать name как полную строку
                if not amount_elem and not unit_elem:
                    parsed = self._parse_ingredient_text(name_text)
                    if parsed:
                        ingredients.append(parsed)
                    continue

                amount = self.clean_text(amount_elem.get_text()) if amount_elem else None
                unit_text = self.clean_text(unit_elem.get_text()) if unit_elem else None

                # Специальный случай: name начинается с «–NUMBER UNIT …»
                # Пример: amount="1", name="–2 tablespoons ají amarillo paste"
                # → amount="1–2", unit="tablespoons", name="ají amarillo paste"
                range_match_with_unit = re.match(
                    r'^[–\-]\s*(\d[\d/.,]*)\s+'
                    r'(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|g|kg|ml|l|pieces?|cloves?)\s+(.+)',
                    name_text, re.IGNORECASE
                )
                # Случай без единицы: «–3 fresh serrano chiles» (amount="2")
                range_match_no_unit = re.match(
                    r'^[–\-]\s*(\d[\d/.,]*)\s+(.+)',
                    name_text, re.IGNORECASE
                )

                if range_match_with_unit and amount:
                    range_end, unit_text, name_text = range_match_with_unit.groups()
                    amount = f"{amount}–{range_end}"
                elif range_match_no_unit and amount and not unit_text:
                    range_end, name_text = range_match_no_unit.groups()
                    amount = f"{amount}–{range_end}"

                # Дополнительная очистка имени
                name_text = re.sub(r'\([^)]*\)', '', name_text).strip()
                name_text = re.sub(r'\s+', ' ', name_text).strip()
                name_text = re.sub(r'[,;.]+$', '', name_text).strip()

                if name_text and len(name_text) >= 2:
                    ingredients.append({
                        'name': name_text,
                        'amount': amount if amount else None,
                        'unit': unit_text if unit_text else None,
                    })

        # ---- Стратегия 2: JSON-LD recipeIngredient (fallback) ----
        if not ingredients:
            recipe = self._get_recipe_json_ld()
            if recipe:
                for ing_text in recipe.get('recipeIngredient', []):
                    if not isinstance(ing_text, str):
                        continue
                    text = self.clean_text(ing_text)
                    if not text or text.endswith(':'):
                        continue
                    parsed = self._parse_ingredient_text(text)
                    if parsed:
                        ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps: list[str] = []

        # Приоритет 1: JSON-LD recipeInstructions
        recipe = self._get_recipe_json_ld()
        if recipe:
            instructions = recipe.get('recipeInstructions', [])
            if isinstance(instructions, list):
                # Метки-заголовки, при обнаружении которых начинается раздел метаданных
                _metadata_start = re.compile(
                    r'^(Preparation\s+Time|Cooking\s+Time|Total\s+Time|'
                    r'Serving\s+Size|Yield|Cuisine|Course|Nutrition\s+Info(?:rmation)?)\s*:',
                    re.I
                )
                # Псевдо-шаги, которые нужно просто пропустить
                _skip_labels = re.compile(r'^instructions?\s*:?\s*$', re.I)
                reached_metadata = False
                for step in instructions:
                    if isinstance(step, dict):
                        text = (step.get('text') or '').strip()
                    elif isinstance(step, str):
                        text = step.strip()
                    else:
                        continue
                    if not text:
                        continue
                    # Начало раздела метаданных — прекращаем сбор шагов
                    if _metadata_start.match(text):
                        reached_metadata = True
                        continue
                    if reached_metadata:
                        continue
                    # Просто пропускаем одиночный ярлык «Instructions:»
                    if _skip_labels.match(text):
                        continue
                    steps.append(text)
            elif isinstance(instructions, str) and instructions.strip():
                return self.clean_text(instructions)

        if steps:
            return ' '.join(steps)

        # Приоритет 2: WPRM HTML
        step_items = self.soup.find_all(
            'div', class_=re.compile(r'wprm-recipe-instruction-text', re.I)
        )
        if step_items:
            for item in step_items:
                text = self.clean_text(item.get_text(separator=' ', strip=True))
                if text:
                    steps.append(text)

        if steps:
            return ' '.join(steps)

        # Приоритет 3: общие ol/ul с инструкциями
        for container in [
            self.soup.find('ol', class_=re.compile(r'instruction', re.I)),
            self.soup.find('div', class_=re.compile(r'instruction', re.I)),
        ]:
            if not container:
                continue
            items = container.find_all('li') or container.find_all('p')
            for item in items:
                text = self.clean_text(item.get_text(separator=' ', strip=True))
                if text:
                    steps.append(text)
            if steps:
                break

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории / курса блюда"""
        # Приоритет 1: JSON-LD recipeCategory
        recipe = self._get_recipe_json_ld()
        if recipe:
            cat = recipe.get('recipeCategory')
            if isinstance(cat, list):
                # Фильтруем мусорные значения («or Dinner», etc.)
                parts = [c.strip() for c in cat if isinstance(c, str) and len(c.strip()) > 2 and not re.match(r'^or\b', c.strip(), re.I)]
                if parts:
                    return ', '.join(parts)
            elif isinstance(cat, str) and cat.strip():
                return self.clean_text(cat)

        # Приоритет 2: WPRM HTML
        course_elem = self.soup.find(class_='wprm-recipe-course-container')
        if course_elem:
            text = course_elem.get_text(separator=', ', strip=True)
            # Убираем метку «Course»
            text = re.sub(r'^Course[\s:,]*', '', text, flags=re.I).strip()
            if text:
                return self.clean_text(text)

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe = self._get_recipe_json_ld()
        if recipe:
            return self._parse_iso_duration(recipe.get('prepTime'))
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        recipe = self._get_recipe_json_ld()
        if recipe:
            result = self._parse_iso_duration(recipe.get('cookTime'))
            if result is not None:
                return result
            # Ищем в pseudo-шагах инструкций вида «Cooking Time: 0 minutes»
            instructions = recipe.get('recipeInstructions', [])
            if isinstance(instructions, list):
                for i, step in enumerate(instructions):
                    text = ''
                    if isinstance(step, dict):
                        text = (step.get('text') or '').strip()
                    elif isinstance(step, str):
                        text = step.strip()
                    if re.match(r'^Cooking\s+Time\s*:', text, re.I):
                        # Значение может быть в следующем шаге
                        if i + 1 < len(instructions):
                            next_step = instructions[i + 1]
                            val = ''
                            if isinstance(next_step, dict):
                                val = (next_step.get('text') or '').strip()
                            elif isinstance(next_step, str):
                                val = next_step.strip()
                            if val:
                                # Нормализуем
                                val = re.sub(r'\(.*\)', '', val).strip()
                                return val if val else None
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe = self._get_recipe_json_ld()
        if recipe:
            return self._parse_iso_duration(recipe.get('totalTime'))
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов из WPRM-блока"""
        container = self.soup.find(class_='wprm-recipe-notes-container')
        if not container:
            return None

        text = container.get_text(separator='\n', strip=True)
        # Убираем метку «Notes» в начале
        text = re.sub(r'^Notes[\s:]*', '', text, flags=re.I).strip()
        # Убираем шорткод [/wprm-recipe-notes]
        text = re.sub(r'\[/?wprm[^\]]*\]', '', text, flags=re.I).strip()
        # Убираем «Additional Notes:» — избыточная метка
        text = re.sub(r'^Additional Notes[\s:]*', '', text, flags=re.I).strip()
        # Нормализуем пробелы
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = self.clean_text(text)
        return text if text else None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords"""
        recipe = self._get_recipe_json_ld()
        if recipe:
            keywords = recipe.get('keywords')
            if isinstance(keywords, str) and keywords.strip():
                return keywords.strip()
            if isinstance(keywords, list):
                return ', '.join(k.strip() for k in keywords if isinstance(k, str) and k.strip())

        # Запасной вариант: meta keywords
        meta_kw = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_kw and meta_kw.get('content'):
            return self.clean_text(meta_kw['content'])

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls: list[str] = []

        # 1. JSON-LD image (приоритет)
        recipe = self._get_recipe_json_ld()
        if recipe:
            img = recipe.get('image')
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                for i in img:
                    if isinstance(i, str):
                        urls.append(i)
                    elif isinstance(i, dict):
                        for key in ('url', 'contentUrl'):
                            if i.get(key):
                                urls.append(i[key])
                                break
            elif isinstance(img, dict):
                for key in ('url', 'contentUrl'):
                    if img.get(key):
                        urls.append(img[key])
                        break

        # 2. og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # 3. twitter:image
        tw_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if tw_image and tw_image.get('content'):
            urls.append(tw_image['content'])

        # Дедупликация с сохранением порядка
        seen: set[str] = set()
        unique: list[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    # ------------------------------------------------------------------ #
    # Главный метод                                                        #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта
        """
        try:
            dish_name = self.extract_dish_name()
            description = self.extract_description()
            ingredients = self.extract_ingredients()
            instructions = self.extract_steps()
            category = self.extract_category()
            notes = self.extract_notes()
            tags = self.extract_tags()

            return {
                'dish_name': dish_name if dish_name else None,
                'description': description if description else None,
                'ingredients': ingredients,
                'instructions': instructions if instructions else None,
                'category': category if category else None,
                'prep_time': self.extract_prep_time(),
                'cook_time': self.extract_cook_time(),
                'total_time': self.extract_total_time(),
                'notes': notes if notes else None,
                'tags': tags,
                'image_urls': self.extract_image_urls(),
            }
        except Exception as exc:
            logger.error('Ошибка при извлечении данных из %s: %s', self.html_path, exc)
            return {
                'dish_name': None,
                'description': None,
                'ingredients': None,
                'instructions': None,
                'category': None,
                'prep_time': None,
                'cook_time': None,
                'total_time': None,
                'notes': None,
                'tags': None,
                'image_urls': None,
            }


def main() -> None:
    """Точка входа: обрабатывает директорию preprocessed/flavordrecipes_com."""
    import os

    base_dir = Path(__file__).parent.parent
    recipes_dir = base_dir / 'preprocessed' / 'flavordrecipes_com'

    if recipes_dir.exists() and recipes_dir.is_dir():
        process_directory(FlavordrecipesComExtractor, str(recipes_dir))
    else:
        print(f'Директория не найдена: {recipes_dir}')
        print('Использование: python flavordrecipes_com.py')


if __name__ == '__main__':
    main()
