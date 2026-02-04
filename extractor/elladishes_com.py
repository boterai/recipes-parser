"""
Экстрактор данных рецептов для сайта elladishes.com

Особенности сайта:
- Использует JSON-LD structured data для рецептов (Schema.org Recipe)
- Формат времени: ISO 8601 (PT15M, PT1H30M)
- Ингредиенты могут содержать "and" в количестве (1 and 1/2 cups)
- Изображения доступны в нескольких размерах в JSON-LD
- Теги/keywords хранятся в JSON-LD
- Заметки могут быть в секции tasty-recipes-notes

Стратегия парсинга:
1. Приоритет - JSON-LD structured data (наиболее надежный источник)
2. Fallback - HTML разметка и meta-теги
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ElladishesExtractor(BaseRecipeExtractor):
    """Экстрактор для elladishes.com"""
    
    # Константы для парсинга ингредиентов
    FRACTION_MAP = {
        '½': '1/2', '¼': '1/4', '¾': '3/4',
        '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
        '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
        '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5'
    }
    
    UNIT_PATTERNS = [
        'cups?', 'tablespoons?', 'teaspoons?', 'tbsps?', 'tsps?',
        'pounds?', 'ounces?', 'lbs?', 'oz', 'grams?', 'kilograms?',
        'g', 'kg', 'milliliters?', 'liters?', 'ml', 'pinch(?:es)?',
        'dash(?:es)?', 'packages?', 'cans?', 'jars?', 'bottles?',
        'inch(?:es)?', 'slices?', 'cloves?', 'bunches?', 'sprigs?',
        'whole', 'halves?', 'quarters?', 'pieces?', 'head', 'heads',
        'tsp', 'tbsp'
    ]
    
    @staticmethod
    def _parse_amount_string(amount_str: str) -> float:
        """
        Парсинг строки с количеством, включая дроби
        
        Args:
            amount_str: Строка вида "1", "1/2", "1 1/2"
            
        Returns:
            Числовое значение количества
        """
        if not amount_str:
            return 0
        
        amount_str = amount_str.strip()
        
        # Обработка дробей типа "1/2" или "1 1/2"
        if '/' in amount_str:
            parts = amount_str.split()
            total = 0
            for part in parts:
                if '/' in part:
                    num, denom = part.split('/')
                    total += float(num) / float(denom)
                else:
                    total += float(part)
            return total
        else:
            try:
                return float(amount_str.replace(',', '.'))
            except ValueError:
                return 0
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение JSON-LD данных рецепта"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            if not script.string:
                continue
                
            try:
                data = json.loads(script.string)
                
                # Функция для проверки типа Recipe
                def is_recipe(item):
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        return 'Recipe' in item_type
                    return item_type == 'Recipe'
                
                # Ищем Recipe в данных
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and is_recipe(item):
                            return item
                elif isinstance(data, dict) and is_recipe(data):
                    return data
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "20 minutes" или "1 hour 30 minutes"
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
        
        # Форматируем вывод
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "3 ripe bananas, mashed" или "1/2 cup granulated sugar"
            
        Returns:
            dict: {"name": "ripe bananas", "amount": "3", "unit": "pieces"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем "and" в числах на пробел для правильного парсинга
        # "1 and 1/2" -> "1 1/2"
        text = re.sub(r'(\d+)\s+and\s+(\d)', r'\1 \2', text)
        
        # Заменяем Unicode дроби на числа
        for fraction, decimal in self.FRACTION_MAP.items():
            text = text.replace(fraction, decimal)
        
        # Строим паттерн из списка единиц измерения
        unit_pattern = '|'.join(self.UNIT_PATTERNS)
        
        # Паттерн для извлечения количества, единицы и названия
        # Важно: unit должен быть обязательным для правильного парсинга
        pattern = rf'^([\d\s/.,]+)\s+({unit_pattern})\s+(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            # Паттерн совпал - есть количество, единица и название
            amount_str, unit, name = match.groups()
            
            # Обработка количества с помощью вспомогательного метода
            amount = self._parse_amount_string(amount_str)
            
            # Обработка единицы измерения
            unit = unit.strip() if unit else None
        else:
            # Паттерн не совпал - пробуем найти только количество в начале
            # Это для случаев типа "3 ripe bananas" или "2 large eggs"
            simple_pattern = r'^([\d\s/.,]+)\s+(.+)'
            simple_match = re.match(simple_pattern, text)
            
            if simple_match:
                amount_str, name = simple_match.groups()
                
                # Обработка количества с помощью вспомогательного метода
                amount = self._parse_amount_string(amount_str)
                
                # Единица измерения - по умолчанию "pieces" для элементов без явной единицы
                unit = "pieces"
            else:
                # Совсем не удалось распарсить - возвращаем как есть
                return {
                    "name": text,
                    "amount": 0,
                    "units": None
                }
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем описательные фразы после запятой
        if ',' in name:
            # Берем только первую часть до запятой
            name = name.split(',')[0]
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|softened|melted|mashed)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeIngredient' in recipe_data:
            recipe_ingredients = recipe_data['recipeIngredient']
            if isinstance(recipe_ingredients, list):
                for ingredient_text in recipe_ingredients:
                    if isinstance(ingredient_text, str):
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций"""
        instructions = []
        
        # Сначала из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeInstructions' in recipe_data:
            recipe_instructions = recipe_data['recipeInstructions']
            if isinstance(recipe_instructions, list):
                for step in recipe_instructions:
                    if isinstance(step, dict) and 'text' in step:
                        instructions.append(self.clean_text(step['text']))
                    elif isinstance(step, str):
                        instructions.append(self.clean_text(step))
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeCategory' in recipe_data:
            return self.clean_text(recipe_data['recipeCategory'])
        
        # Альтернативно - из meta тега
        meta_category = self.soup.find('meta', property='article:section')
        if meta_category and meta_category.get('content'):
            return self.clean_text(meta_category['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем секцию с заметками в HTML
        # На elladishes.com заметки могут быть в разных местах
        
        # Попробуем найти секцию tasty-recipes-notes
        notes_section = self.soup.find('div', class_=re.compile(r'tasty-recipes-notes', re.I))
        if notes_section:
            # Удаляем заголовок
            for heading in notes_section.find_all(['h3', 'h4']):
                heading.decompose()
            
            text = notes_section.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Сначала из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Разделяем по запятой
                tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            elif isinstance(keywords, list):
                tags_list = [str(tag).strip() for tag in keywords if tag]
        
        # Возвращаем как строку через запятую с пробелом
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Сначала из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'image' in recipe_data:
            images = recipe_data['image']
            if isinstance(images, str):
                urls.append(images)
            elif isinstance(images, list):
                urls.extend([img for img in images if isinstance(img, str)])
            elif isinstance(images, dict):
                if 'url' in images:
                    urls.append(images['url'])
                elif 'contentUrl' in images:
                    urls.append(images['contentUrl'])
        
        # Дополнительно из meta тегов
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
        
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
        Извлечение всех данных рецепта
        
        Returns:
            Словарь с данными рецепта
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
            "image_urls": self.extract_image_urls()
        }


def main():
    """Основная функция для обработки директории с HTML файлами"""
    import os
    from pathlib import Path
    
    # Путь к preprocessed директории относительно корня репозитория
    repo_root = Path(__file__).parent.parent
    preprocessed_dir = repo_root / "preprocessed" / "elladishes_com"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(ElladishesExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python elladishes_com.py")


if __name__ == "__main__":
    main()
