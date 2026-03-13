"""
Экстрактор данных рецептов для сайта naminhapanela.com
Сайт использует WordPress с плагином WP Recipe Maker (WPRM)
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

# Единицы измерения, принятые в бразильской кулинарии (для парсинга из имени ингредиента)
_PT_UNITS = [
    'colher de sopa',
    'colheres de sopa',
    'colher de chá',
    'colheres de chá',
    'xícara',
    'xícaras',
    'pote',
    'potes',
    'copo',
    'copos',
    'litro',
    'litros',
    'ml',
    'kg',
    'g',
    'l',
    'pitada',
    'pitadas',
    'dente',
    'dentes',
    'fatia',
    'fatias',
    'folha',
    'folhas',
    'ramo',
    'ramos',
    'unidade',
    'unidades',
]

# Сортируем по убыванию длины, чтобы длинные единицы (colher de sopa) проверялись раньше коротких (g)
_PT_UNITS_SORTED = sorted(_PT_UNITS, key=len, reverse=True)


class NaMinhaPanelaComExtractor(BaseRecipeExtractor):
    """Экстрактор для naminhapanela.com (WP Recipe Maker)"""

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _get_recipe_jsonld(self) -> Optional[dict]:
        """Возвращает первый объект с @type == 'Recipe' из JSON-LD скриптов."""
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                # Может быть прямой объект или @graph
                items = data if isinstance(data, list) else data.get('@graph', [data])
                for item in items:
                    if isinstance(item, dict) and item.get('@type') == 'Recipe':
                        return item
            except (json.JSONDecodeError, ValueError):
                continue
        return None

    def _get_article_jsonld(self) -> Optional[dict]:
        """Возвращает первый объект с @type == 'Article' из JSON-LD скриптов."""
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else data.get('@graph', [data])
                for item in items:
                    if isinstance(item, dict) and item.get('@type') == 'Article':
                        return item
            except (json.JSONDecodeError, ValueError):
                continue
        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в человекочитаемую строку.

        Args:
            duration: строка вида "PT20M" или "PT1H30M"

        Returns:
            Время в формате "20 minutes" или "1 hour 30 minutes"
        """
        if not duration or not duration.startswith('PT'):
            return None

        remainder = duration[2:]  # убираем "PT"

        hours = 0
        minutes = 0

        hour_match = re.search(r'(\d+)H', remainder)
        if hour_match:
            hours = int(hour_match.group(1))

        min_match = re.search(r'(\d+)M', remainder)
        if min_match:
            minutes = int(min_match.group(1))

        total_minutes = hours * 60 + minutes
        if total_minutes == 0:
            return None

        # Конвертируем в часы и минуты
        h = total_minutes // 60
        m = total_minutes % 60

        parts = []
        if h == 1:
            parts.append('1 hour')
        elif h > 1:
            parts.append(f'{h} hours')

        if m == 1:
            parts.append('1 minute')
        elif m > 1:
            parts.append(f'{m} minutes')

        return ' '.join(parts) if parts else None

    @staticmethod
    def _clean_ingredient_name(name: str) -> str:
        """Очищает строку названия ингредиента от лишних символов."""
        # Убираем trailing пунктуацию (;, ., *)
        name = re.sub(r'[;.*]+$', '', name)
        # Убираем leading "de "
        name = re.sub(r'^de\s+', '', name, flags=re.IGNORECASE)
        # Убираем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        return name

    @staticmethod
    def _extract_unit_from_name(name: str) -> tuple:
        """
        Пытается извлечь единицу измерения из начала строки названия ингредиента.

        Примеры:
            "colher de sopa de azeite" -> ("colher de sopa", "azeite")
            "xícara de coentro"        -> ("xícara", "coentro")
            "abacate pequeno maduro"   -> (None, "abacate pequeno maduro")

        Returns:
            Кортеж (unit, cleaned_name)
        """
        for unit in _PT_UNITS_SORTED:
            # Ищем единицу в начале строки с "de " после неё
            pattern = rf'^{re.escape(unit)}\s+de\s+(.+)$'
            m = re.match(pattern, name, re.IGNORECASE)
            if m:
                return unit, m.group(1).strip()
            # Или просто единица в начале без "de"
            pattern2 = rf'^{re.escape(unit)}\s+(.+)$'
            m2 = re.match(pattern2, name, re.IGNORECASE)
            if m2:
                return unit, m2.group(1).strip()
        return None, name

    # ------------------------------------------------------------------
    # Методы извлечения данных
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из h1 или JSON-LD."""
        # 1. h1 на странице (самый надёжный)
        h1 = self.soup.find('h1')
        if h1:
            name = self.clean_text(h1.get_text())
            # Убираем информационные префиксы
            name = re.sub(r'^(Como fazer|Receita de)\s+', '', name, flags=re.IGNORECASE)
            return name.strip() if name.strip() else None

        # 2. Из JSON-LD Recipe
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('name'):
            name = recipe['name']
            # Убираем "Como fazer " или "Receita de " префиксы
            name = re.sub(r'^(Como fazer|Receita de)\s+', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)

        # 3. og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        logger.warning("Не удалось найти название блюда: %s", self.html_path)
        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта."""
        # 1. Из WPRM summary блока
        summary = self.soup.find(class_='wprm-recipe-summary')
        if summary:
            text = self.clean_text(summary.get_text(separator=' ', strip=True))
            if text:
                return text

        # 2. Из JSON-LD Recipe
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('description'):
            return self.clean_text(recipe['description'])

        # 3. meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        logger.warning("Не удалось найти описание рецепта: %s", self.html_path)
        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из WPRM HTML (приоритет) или JSON-LD."""
        ingredients = []

        # 1. WPRM HTML — наиболее структурированный источник
        ing_items = self.soup.find_all('li', class_='wprm-recipe-ingredient')
        for item in ing_items:
            amount_el = item.find(class_='wprm-recipe-ingredient-amount')
            unit_el = item.find(class_='wprm-recipe-ingredient-unit')
            name_el = item.find(class_='wprm-recipe-ingredient-name')

            if not name_el:
                continue

            amount = self.clean_text(amount_el.get_text(strip=True)) if amount_el else None
            unit = self.clean_text(unit_el.get_text(strip=True)) if unit_el else None
            raw_name = self.clean_text(name_el.get_text(strip=True))

            # Убираем trailing пунктуацию из имени
            cleaned_name = self._clean_ingredient_name(raw_name)

            # Если единицы нет в span, пробуем извлечь из имени
            if not unit and cleaned_name:
                extracted_unit, cleaned_name = self._extract_unit_from_name(cleaned_name)
                if extracted_unit:
                    unit = extracted_unit

            if not amount:
                amount = None
            if not unit:
                unit = None

            if cleaned_name:
                ingredients.append({
                    "name": cleaned_name,
                    "amount": amount if amount else None,
                    "unit": unit,
                })

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        # 2. Fallback: JSON-LD recipeIngredient (текстовые строки)
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('recipeIngredient'):
            for ing_text in recipe['recipeIngredient']:
                text = self.clean_text(str(ing_text)).rstrip(';.')
                if text:
                    ingredients.append({"name": text, "amount": None, "unit": None})
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        logger.warning("Не удалось найти ингредиенты: %s", self.html_path)
        return None

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления из JSON-LD или WPRM HTML."""
        steps = []

        # 1. JSON-LD recipeInstructions
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('recipeInstructions'):
            instructions = recipe['recipeInstructions']
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and step.get('text'):
                        text = self.clean_text(step['text'])
                        if text:
                            steps.append(text)
                    elif isinstance(step, str):
                        text = self.clean_text(step)
                        if text:
                            steps.append(text)
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))

            if steps:
                return ' '.join(steps)

        # 2. WPRM HTML — шаги приготовления
        instruction_items = self.soup.find_all(class_='wprm-recipe-instruction-text')
        for item in instruction_items:
            text = self.clean_text(item.get_text(separator=' ', strip=True))
            if text:
                steps.append(text)

        if steps:
            return ' '.join(steps)

        logger.warning("Не удалось найти шаги приготовления: %s", self.html_path)
        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из JSON-LD."""
        recipe = self._get_recipe_jsonld()
        if recipe:
            category = recipe.get('recipeCategory')
            if isinstance(category, list) and category:
                return self.clean_text(category[0])
            elif isinstance(category, str) and category:
                return self.clean_text(category)

        # Fallback: articleSection из Article JSON-LD
        article = self._get_article_jsonld()
        if article:
            section = article.get('articleSection')
            if isinstance(section, list) and section:
                return self.clean_text(section[0])
            elif isinstance(section, str) and section:
                return self.clean_text(section)

        logger.warning("Не удалось найти категорию: %s", self.html_path)
        return None

    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени приготовления.

        Args:
            time_type: 'prep', 'cook' или 'total'
        """
        time_keys = {
            'prep': 'prepTime',
            'cook': 'cookTime',
            'total': 'totalTime',
        }
        key = time_keys.get(time_type)
        if not key:
            return None

        # 1. Из JSON-LD Recipe
        recipe = self._get_recipe_jsonld()
        if recipe and key in recipe:
            return self._parse_iso_duration(recipe[key])

        # 2. Из WPRM HTML spans
        wprm_class = f'wprm-recipe-{time_type}_time-minutes'
        time_span = self.soup.find(class_=wprm_class)
        if time_span:
            # Берём только числовое значение (первый text node, без screen-reader-text)
            for child in time_span.children:
                if hasattr(child, 'get_text'):
                    # Проверяем, что это не hidden span
                    if 'screen-reader-text' in child.get('class', []):
                        continue
                    val = self.clean_text(child.get_text(strip=True))
                    if val and val.isdigit():
                        return f"{val} minutes"
                else:
                    val = str(child).strip()
                    if val and val.isdigit():
                        return f"{val} minutes"

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
        """Извлечение заметок из блока WPRM notes."""
        notes_container = self.soup.find(class_=re.compile(r'wprm-recipe-notes', re.I))
        if notes_container:
            # Убираем заголовок секции
            header = notes_container.find(class_='wprm-recipe-header')
            if header:
                header.decompose()
            text = self.clean_text(notes_container.get_text(separator=' ', strip=True))
            # Убираем ведущий символ "* " если есть
            text = re.sub(r'^\*\s*', '', text)
            text = text.strip()
            if text:
                return text

        logger.debug("Заметки не найдены: %s", self.html_path)
        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords."""
        # 1. Из JSON-LD Recipe keywords
        recipe = self._get_recipe_jsonld()
        if recipe:
            keywords = recipe.get('keywords')
            if isinstance(keywords, str) and keywords.strip():
                return keywords.strip()
            elif isinstance(keywords, list) and keywords:
                return ', '.join(str(k).strip() for k in keywords if k)

        # 2. Из Article JSON-LD keywords
        article = self._get_article_jsonld()
        if article:
            keywords = article.get('keywords')
            if isinstance(keywords, list) and keywords:
                return ', '.join(str(k).strip() for k in keywords if k)
            elif isinstance(keywords, str) and keywords.strip():
                return keywords.strip()

        logger.debug("Теги не найдены: %s", self.html_path)
        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из JSON-LD Recipe."""
        urls = []

        # 1. Из JSON-LD Recipe image
        recipe = self._get_recipe_jsonld()
        if recipe and 'image' in recipe:
            img = recipe['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                url = img.get('url') or img.get('contentUrl')
                if url:
                    urls.append(url)

        # 2. og:image как fallback
        if not urls:
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

    # ------------------------------------------------------------------
    # Основной метод
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта в едином формате проекта.
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()

        return {
            "dish_name": dish_name.lower() if dish_name else None,
            "description": description if description else None,
            "ingredients": ingredients,
            "instructions": instructions if instructions else None,
            "category": category if category else None,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes if notes else None,
            "tags": tags,
            "image_urls": self.extract_image_urls(),
        }


def main():
    import os
    recipes_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'preprocessed',
        'naminhapanela_com',
    )
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(NaMinhaPanelaComExtractor, recipes_dir)
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python naminhapanela_com.py")


if __name__ == "__main__":
    main()
