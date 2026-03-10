"""
Экстрактор данных рецептов для сайта 101cookingfortwo.com
Сайт использует WordPress с плагином WP Recipe Maker (WPRM) и JSON-LD structured data.
"""

import sys
from pathlib import Path
import json
import re
import logging
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class OneTwoOneCookingForTwoExtractor(BaseRecipeExtractor):
    """Экстрактор для 101cookingfortwo.com"""

    def _get_json_ld_recipe(self) -> Optional[dict]:
        """
        Извлечение данных Recipe из JSON-LD на странице.
        Сайт использует @graph с объектом типа Recipe.

        Returns:
            dict с данными Recipe или None
        """
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')

        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue

                data = json.loads(script.string)

                # Проверяем формат @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict):
                            item_type = item.get('@type', '')
                            if item_type == 'Recipe' or (isinstance(item_type, list) and 'Recipe' in item_type):
                                return item

                # Проверяем прямой объект Recipe
                if isinstance(data, dict):
                    item_type = data.get('@type', '')
                    if item_type == 'Recipe' or (isinstance(item_type, list) and 'Recipe' in item_type):
                        return data

                # Проверяем список
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            item_type = item.get('@type', '')
                            if item_type == 'Recipe' or (isinstance(item_type, list) and 'Recipe' in item_type):
                                return item

            except (json.JSONDecodeError, KeyError) as e:
                logger.debug("Ошибка при парсинге JSON-LD: %s", e)
                continue

        return None

    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат.

        Args:
            duration: строка вида "PT30M" или "PT8H" или "PT8H30M"

        Returns:
            Время в формате "30 minutes", "8 hours", "8 hours 30 minutes"
        """
        if not duration or not duration.startswith('PT'):
            return None

        duration = duration[2:]  # Убираем "PT"

        hours = 0
        minutes = 0

        # Извлекаем часы
        hour_match = re.search(r'(\d+)H', duration)
        if hour_match:
            hours = int(hour_match.group(1))

        # Извлекаем минуты
        min_match = re.search(r'(\d+)M', duration)
        if min_match:
            minutes = int(min_match.group(1))

        # Нормализуем: переводим лишние минуты в часы
        if minutes >= 60:
            hours += minutes // 60
            minutes = minutes % 60

        # Форматируем результат в полных словах
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")

        return ' '.join(parts) if parts else None

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_recipe()

        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])

        # Альтернатива — из тега h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        # Из meta title
        title = self.soup.find('title')
        if title:
            text = title.get_text()
            text = re.sub(r'\s*[-|].*$', '', text)
            return self.clean_text(text)

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        json_ld = self._get_json_ld_recipe()

        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])

        # Альтернатива — из meta og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        # Из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        return None

    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат.

        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour" или "2 tablespoons butter"

        Returns:
            dict: {"name": "flour", "amount": "1", "unit": "cup"} или None
        """
        if not ingredient_text:
            return None

        text = self.clean_text(ingredient_text)

        # Паттерн для извлечения количества, единицы и названия.
        # Unicode дроби (½, ¼ и т.д.) допустимы в поле количества.
        pattern = (
            r'^([\d\s/.,–\-½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘]+)?\s*'
            r'(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|'
            r'grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|'
            r'pinch(?:es)?|dash(?:es)?|packages?|packs?|cans?|jars?|bottles?|'
            r'inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|'
            r'pieces?|head|heads|stalks?|leaves?|leaf|medium|large|small|units?)?\s*'
            r'(.+)'
        )

        match = re.match(pattern, text, re.IGNORECASE)

        if not match:
            return {
                "name": text,
                "amount": None,
                "unit": None
            }

        amount_str, unit, name = match.groups()

        # Обработка количества — сохраняем как строку (включая диапазоны "1–1½" и дроби)
        amount = None
        if amount_str:
            amount = amount_str.strip()
            if not amount:
                amount = None

        # Единица измерения
        unit = unit.strip() if unit else None

        # Очистка названия — удаляем содержимое скобок, в том числе вложенных
        prev = None
        while prev != name:
            prev = name
            name = re.sub(r'\([^()]*\)', '', name)
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|for serving)\b', '', name, flags=re.IGNORECASE)
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()

        if not name or len(name) < 2:
            return None

        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD recipeIngredient"""
        json_ld = self._get_json_ld_recipe()

        ingredients = []

        if json_ld and 'recipeIngredient' in json_ld:
            for ingredient_text in json_ld['recipeIngredient']:
                if not ingredient_text or not ingredient_text.strip():
                    continue
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        # Запасной вариант: ищем в HTML (WPRM плагин)
        ingredient_container = self.soup.find(class_=re.compile(r'wprm-recipe-ingredients-container', re.I))
        if ingredient_container:
            for item in ingredient_container.find_all('li', class_=re.compile(r'wprm-recipe-ingredient$', re.I)):
                text = item.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                if text:
                    parsed = self.parse_ingredient(text)
                    if parsed:
                        ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления из JSON-LD recipeInstructions.
        Поддерживает HowToSection (с itemListElement) и HowToStep."""
        json_ld = self._get_json_ld_recipe()

        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            steps = []
            step_idx = 1

            def collect_steps(items: list) -> None:
                nonlocal step_idx
                for item in items:
                    if not isinstance(item, dict):
                        if isinstance(item, str):
                            text = self.clean_text(item)
                            if text:
                                steps.append(f"{step_idx}. {text}")
                                step_idx += 1
                        continue

                    item_type = item.get('@type', '')

                    if item_type == 'HowToSection':
                        # Секция содержит подшаги
                        sub_items = item.get('itemListElement', [])
                        collect_steps(sub_items)
                    elif item_type == 'HowToStep':
                        text = self.clean_text(item.get('text', ''))
                        if text:
                            steps.append(f"{step_idx}. {text}")
                            step_idx += 1
                    else:
                        # Обобщённый шаг
                        text = item.get('text', '') or item.get('name', '')
                        text = self.clean_text(text)
                        if text:
                            steps.append(f"{step_idx}. {text}")
                            step_idx += 1

            if isinstance(instructions, list):
                collect_steps(instructions)
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))

            return ' '.join(steps) if steps else None

        # Запасной вариант: ищем в HTML (WPRM плагин)
        instructions_container = self.soup.find(class_=re.compile(r'wprm-recipe-instructions-container', re.I))
        if instructions_container:
            steps = []
            for idx, item in enumerate(
                instructions_container.find_all('li', class_=re.compile(r'wprm-recipe-instruction$', re.I)), 1
            ):
                text = item.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                if text:
                    steps.append(f"{idx}. {text}")
            return ' '.join(steps) if steps else None

        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда из JSON-LD recipeCategory"""
        json_ld = self._get_json_ld_recipe()

        if json_ld:
            if 'recipeCategory' in json_ld:
                category = json_ld['recipeCategory']
                if isinstance(category, list):
                    return ', '.join(str(c) for c in category if c)
                return str(category)

            if 'recipeCuisine' in json_ld:
                cuisine = json_ld['recipeCuisine']
                if isinstance(cuisine, list):
                    return ', '.join(str(c) for c in cuisine if c)
                return str(cuisine)

        # Альтернатива — из мета-тега article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self._get_json_ld_recipe()

        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])

        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_recipe()

        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])

        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_recipe()

        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])

        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов из блока WPRM wprm-recipe-notes-container"""
        notes_container = self.soup.find(class_='wprm-recipe-notes-container')
        if not notes_container:
            # Запасной поиск по широкому паттерну
            notes_container = self.soup.find(class_=re.compile(r'wprm.*notes', re.I))

        if notes_container:
            # Убираем заголовки типа "Recipe Notes", "Pro Tips" из начала текста
            text = notes_container.get_text(separator=' ', strip=True)
            # Убираем любые комбинации заголовков в начале строки
            text = re.sub(r'^(Recipe\s+Notes?\s*:?\s*|Pro\s+Tips?\s*:?\s*)+', '', text, flags=re.IGNORECASE)
            text = self.clean_text(text)
            return text if text else None

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords"""
        json_ld = self._get_json_ld_recipe()

        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if isinstance(keywords, str):
                # Ключевые слова могут быть разделены запятыми или точками с запятой
                tags = re.split(r'[;,]', keywords)
                tags = [t.strip() for t in tags if t.strip()]
                return ', '.join(tags) if tags else None
            elif isinstance(keywords, list):
                tags = [str(k).strip() for k in keywords if k]
                return ', '.join(tags) if tags else None

        # Запасной вариант: из HTML WPRM keyword block
        keyword_elem = self.soup.find(class_=re.compile(r'wprm-recipe-keyword$', re.I))
        if keyword_elem:
            text = keyword_elem.get_text(separator=', ', strip=True)
            # WPRM разделяет ключевые слова точкой с запятой
            tags = re.split(r'[;,]', text)
            tags = [t.strip() for t in tags if t.strip()]
            return ', '.join(tags) if tags else None

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из JSON-LD и мета-тегов"""
        urls = []

        json_ld = self._get_json_ld_recipe()

        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                url = img.get('url') or img.get('contentUrl')
                if url:
                    urls.append(url)
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        url = item.get('url') or item.get('contentUrl')
                        if url:
                            urls.append(url)

        # Дополняем из og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # Дополняем из twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])

        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)

            return ','.join(unique_urls) if unique_urls else None

        return None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта
        """
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_steps(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls(),
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os

    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "101cookingfortwo_com")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(OneTwoOneCookingForTwoExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python 101cookingfortwo_com.py")


if __name__ == "__main__":
    main()
