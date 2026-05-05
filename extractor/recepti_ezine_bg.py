"""
Экстрактор данных рецептов для сайта recepti.ezine.bg
"""

import sys
import logging
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class ReceptiEzineBgExtractor(BaseRecipeExtractor):
    """Экстрактор для recepti.ezine.bg"""

    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Получение данных рецепта из JSON-LD (тип Recipe)"""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, AttributeError, TypeError):
                continue
        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в строку вида 'N minutes'

        Args:
            duration: строка вида 'PT20M' или 'PT1H30M'

        Returns:
            Строка вида '20 minutes' или None
        """
        if not duration or not duration.startswith('PT'):
            return None

        duration_body = duration[2:]  # убираем 'PT'

        hours = 0
        minutes = 0

        hour_match = re.search(r'(\d+)H', duration_body)
        if hour_match:
            hours = int(hour_match.group(1))

        min_match = re.search(r'(\d+)M', duration_body)
        if min_match:
            minutes = int(min_match.group(1))

        total = hours * 60 + minutes
        return f"{total} minutes" if total > 0 else None

    # Болгарские слова-количества (не числа), за которыми может следовать единица измерения
    _BG_QUANTITY_WORD_PREFIXES = ('няколко', 'малко', 'доста', 'много')

    def _parse_ingredient_str(self, name: str, quantity_str: str) -> dict:
        """
        Разбирает строку с количеством и единицей измерения ингредиента.

        Args:
            name: Название ингредиента
            quantity_str: Строка вида '150 грама', '1 с.л.', '3-4 с.л.', 'на вкус', 'няколко листа'

        Returns:
            Словарь {'name': ..., 'amount': ..., 'unit': ...}
        """
        quantity_str = quantity_str.strip()

        if not quantity_str:
            return {"name": name, "amount": None, "unit": None}

        # Если строка не начинается с цифры — 'на вкус', 'няколко листа' и т.п.
        if not re.match(r'^\d', quantity_str):
            # Проверяем, начинается ли со слова-количества, за которым идёт единица
            lower_qty = quantity_str.lower()
            for prefix in self._BG_QUANTITY_WORD_PREFIXES:
                if lower_qty.startswith(prefix):
                    rest = quantity_str[len(prefix):].strip()
                    if rest:
                        # Убираем суффиксы типа 'за гарниране'
                        rest = re.sub(r'\s+за\s+\w+$', '', rest, flags=re.IGNORECASE).strip()
                        return {"name": name, "amount": prefix, "unit": rest or None}
            # Выражение целиком — количество (на вкус, по вкус и т.п.)
            return {"name": name, "amount": quantity_str, "unit": None}

        # Диапазон типа '3  -  4 с.л.' или '3-4 с.л.'
        range_match = re.match(r'^(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)\s+(.*)', quantity_str)
        if range_match:
            amount = f"{range_match.group(1)}-{range_match.group(2)}"
            unit = range_match.group(3).strip() or None
            return {"name": name, "amount": amount, "unit": unit}

        # Стандартный формат: число + единица ('150 грама', '1 с.л.')
        std_match = re.match(r'^(\d+(?:[.,/]\d+)?)\s*(.*)', quantity_str)
        if std_match:
            amount = std_match.group(1).replace(',', '.')
            unit = std_match.group(2).strip() or None
            return {"name": name, "amount": amount, "unit": unit}

        return {"name": name, "amount": quantity_str, "unit": None}

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Основной источник: JSON-LD Recipe.name
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('name'):
            return self.clean_text(recipe['name'])

        # Запасной вариант: тег h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Предпочтительный источник: div.description (чистый текст без промо-суффикса)
        desc_div = self.soup.find('div', class_='description')
        if desc_div:
            text = self.clean_text(desc_div.get_text())
            if text:
                return text

        # Запасной вариант: JSON-LD Recipe.description
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('description'):
            return self.clean_text(recipe['description'])

        # Последний резерв: meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из секции продуктов"""
        ingredients = []

        # Основной источник: section.products ul li с выделенным названием в <b>
        # Формат: <li><b>название</b> -  количество единица</li>
        products_section = self.soup.find('section', class_='products')
        if products_section:
            for li in products_section.find_all('li'):
                b_tag = li.find('b')
                if not b_tag:
                    continue

                name = self.clean_text(b_tag.get_text())
                if not name:
                    continue

                # Текст после названия: ' -  количество единица'
                full_text = li.get_text()
                name_end = len(name)
                remainder = full_text[name_end:]
                sep_match = re.search(r'\s*-{1,2}\s+(.*)', remainder)
                if sep_match:
                    quantity_str = self.clean_text(sep_match.group(1))
                    ingredient = self._parse_ingredient_str(name, quantity_str)
                else:
                    ingredient = {"name": name, "amount": None, "unit": None}

                ingredients.append(ingredient)

        if not ingredients:
            # Запасной вариант: JSON-LD recipeIngredient (строки вида 'название - количество единица')
            recipe = self._get_recipe_json_ld()
            if recipe and recipe.get('recipeIngredient'):
                for ing_str in recipe['recipeIngredient']:
                    ing_str = self.clean_text(ing_str)
                    sep_match = re.match(r'^(.+?)\s*-{1,2}\s+(.+)$', ing_str)
                    if sep_match:
                        name = sep_match.group(1).strip()
                        quantity_str = sep_match.group(2).strip()
                        ingredient = self._parse_ingredient_str(name, quantity_str)
                    else:
                        ingredient = {"name": ing_str, "amount": None, "unit": None}
                    ingredients.append(ingredient)

        if not ingredients:
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        # Основной источник: JSON-LD recipeInstructions (HowToStep)
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('recipeInstructions'):
            steps = []
            for step in recipe['recipeInstructions']:
                if isinstance(step, dict):
                    text = self.clean_text(step.get('text', ''))
                elif isinstance(step, str):
                    text = self.clean_text(step)
                else:
                    continue
                if text:
                    steps.append(text)
            if steps:
                return ' '.join(steps)

        # Запасной вариант: p.desc в div.text
        text_div = self.soup.find('div', class_='text')
        if text_div:
            steps = [
                self.clean_text(p.get_text())
                for p in text_div.find_all('p')
                if p.get_text().strip()
            ]
            if steps:
                return ' '.join(steps)

        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда"""
        # Основной источник: JSON-LD Recipe.recipeCategory
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('recipeCategory'):
            categories = recipe['recipeCategory']
            if isinstance(categories, list):
                # Берём первую категорию как основную
                return categories[0] if categories else None
            elif isinstance(categories, str):
                return categories

        # Запасной вариант: BreadcrumbList — предпоследний элемент (категория)
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'BreadcrumbList':
                    items = sorted(
                        data.get('itemListElement', []),
                        key=lambda x: x.get('position', 0)
                    )
                    # Пропускаем позиции 1 (сайт) и 2 (Рецепти) и последнюю (сам рецепт)
                    category_items = [
                        item for item in items
                        if item.get('position', 0) not in (1, 2)
                        and item.get('position', 0) < len(items)
                    ]
                    if category_items:
                        return category_items[0].get('name')
            except (json.JSONDecodeError, AttributeError, KeyError):
                continue

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Основной источник: JSON-LD prepTime (ISO 8601)
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('prepTime'):
            return self._parse_iso_duration(recipe['prepTime'])

        # Запасной вариант: HTML div.indi — первый div.icb-prep с меткой 'Приготвяне'
        indi = self.soup.find('div', class_='indi')
        if indi:
            for div in indi.find_all('div', class_='icb-prep'):
                inner = div.find('div')
                if inner and 'Приготвяне' in inner.get_text():
                    time_text = div.get_text()
                    time_text = re.sub(r'Приготвяне', '', time_text).strip()
                    m = re.search(r'(\d+)', time_text)
                    if m:
                        return f"{m.group(1)} minutes"

        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Основной источник: JSON-LD cookTime (ISO 8601)
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('cookTime'):
            return self._parse_iso_duration(recipe['cookTime'])

        # Запасной вариант: HTML div.indi — div.icb-prep с меткой 'Готвене'
        indi = self.soup.find('div', class_='indi')
        if indi:
            for div in indi.find_all('div', class_='icb-prep'):
                inner = div.find('div')
                if inner and 'Готвене' in inner.get_text():
                    time_text = div.get_text()
                    time_text = re.sub(r'Готвене', '', time_text).strip()
                    m = re.search(r'(\d+)', time_text)
                    if m:
                        return f"{m.group(1)} minutes"

        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени приготовления"""
        # Основной источник: JSON-LD totalTime (ISO 8601)
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('totalTime'):
            return self._parse_iso_duration(recipe['totalTime'])

        # Запасной вариант: HTML div.indi — div.icb-tot
        indi = self.soup.find('div', class_='indi')
        if indi:
            tot_div = indi.find('div', class_='icb-tot')
            if tot_div:
                time_text = tot_div.get_text()
                time_text = re.sub(r'Общо', '', time_text).strip()
                m = re.search(r'(\d+)', time_text)
                if m:
                    return f"{m.group(1)} minutes"

        return None

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок и советов.

        Стратегия: параграфы в div.text, выходящие за пределы количества шагов в JSON-LD,
        считаются заметками (например, 'Вижте също...' / 'Опитайте също...' и т.п.).
        """
        text_div = self.soup.find('div', class_='text')
        if not text_div:
            return None

        p_tags = text_div.find_all('p')
        if not p_tags:
            return None

        # Считаем количество шагов из JSON-LD
        recipe = self._get_recipe_json_ld()
        num_steps = 0
        if recipe and recipe.get('recipeInstructions'):
            num_steps = len(recipe['recipeInstructions'])

        # Параграфы после шагов — это заметки
        extra_ps = p_tags[num_steps:]
        if extra_ps:
            notes_parts = [
                self.clean_text(p.get_text())
                for p in extra_ps
                if p.get_text().strip()
            ]
            if notes_parts:
                return ' '.join(notes_parts)

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта"""
        # Основной источник: JSON-LD Recipe.keywords
        recipe = self._get_recipe_json_ld()
        if recipe:
            keywords = recipe.get('keywords')
            if isinstance(keywords, list):
                joined = ', '.join(k.strip() for k in keywords if k.strip())
                return joined if joined else None
            elif isinstance(keywords, str) and keywords.strip():
                return keywords.strip()

        # Запасной вариант: meta[name=keywords]
        meta_kw = self.soup.find('meta', {'name': 'keywords'})
        if meta_kw and meta_kw.get('content'):
            content = meta_kw['content'].strip()
            return content if content else None

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта из JSON-LD"""
        urls = []

        # Основной источник: JSON-LD Recipe.image (список ImageObject)
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('image'):
            images = recipe['image']
            if isinstance(images, list):
                for img in images:
                    if isinstance(img, dict):
                        url = img.get('url') or img.get('contentUrl')
                        if url:
                            urls.append(url)
                    elif isinstance(img, str):
                        urls.append(img)
            elif isinstance(images, dict):
                url = images.get('url') or images.get('contentUrl')
                if url:
                    urls.append(url)
            elif isinstance(images, str):
                urls.append(images)

        if not urls:
            # Запасной вариант: meta og:image
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])

        # Убираем дубликаты, сохраняя порядок
        seen: set = set()
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
            Словарь с полями рецепта
        """
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_instructions(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls(),
        }


def main():
    """Точка входа для обработки директории с HTML файлами recepti.ezine.bg"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "recepti_ezine_bg")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ReceptiEzineBgExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python recepti_ezine_bg.py")


if __name__ == "__main__":
    main()
