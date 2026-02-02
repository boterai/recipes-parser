"""
Экстрактор данных рецептов для сайта cookiemadness.net
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CookieMadnessExtractor(BaseRecipeExtractor):
    """Экстрактор для cookiemadness.net"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в текстовое представление
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в текстовом виде, например "20 minutes" или "1 hour 30 minutes"
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
        
        # Если только минуты и >= 60, конвертируем в часы
        if hours == 0 and minutes >= 60:
            hours = minutes // 60
            minutes = minutes % 60
        
        # Формируем текстовое представление
        result = []
        if hours > 0:
            result.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            result.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(result) if result else None
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение объекта Recipe из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            return item
                
                # Если Recipe напрямую
                if data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour" или "2 pounds chicken"
            
        Returns:
            dict: {"name": "flour", "amount": "1", "unit": "cup"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Удаляем содержимое в скобках (граммы, примечания)
        text = re.sub(r'\([^)]*\)', '', text)
        # Удаляем оставшиеся скобки
        text = re.sub(r'[()]', '', text)
        text = text.strip()
        
        # Заменяем Unicode дроби на обычные дроби
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5'
        }
        
        for fraction, replacement in fraction_map.items():
            text = text.replace(fraction, replacement)
        
        # Паттерн для извлечения количества, единицы и названия
        # Поддерживает форматы: "1 cup flour", "2 tablespoons butter", "1/2 teaspoon salt", "1 1/2 cups flour"
        pattern = r'^([\d\s/]+)?\s*(cup|cups|tablespoon|tablespoons|teaspoon|teaspoons|tbsp|tsp|pound|pounds|ounce|ounces|lb|lbs|oz|gram|grams|kilogram|kilograms|g|kg|milliliter|milliliters|liter|liters|ml|l|pinch|pinches|dash|dashes|package|packages|can|cans|jar|jars|bottle|bottles|inch|inches|slice|slices|clove|cloves|bunch|bunches|sprig|sprigs|whole|half|halves|quarter|quarters|piece|pieces|head|heads|stick|sticks|unit)s?\s+(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, пробуем без единиц измерения
            # Формат: "1 egg", "2 apples"
            pattern_no_unit = r'^([\d\s/]+)\s+(.+)'
            match_no_unit = re.match(pattern_no_unit, text, re.IGNORECASE)
            
            if match_no_unit:
                amount_str, name = match_no_unit.groups()
                return {
                    "name": name.strip(),
                    "amount": amount_str.strip(),
                    "unit": None
                }
            
            # Если совсем не совпало, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount = amount_str.strip()
        
        # Обработка единицы измерения - приводим к единообразному виду
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем запятые в конце
        name = re.sub(r',\s*$', '', name)
        name = name.strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        recipe_data = self._get_recipe_json_ld()
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredients_list = recipe_data['recipeIngredient']
        if not isinstance(ingredients_list, list):
            return None
        
        parsed_ingredients = []
        for ingredient_text in ingredients_list:
            if isinstance(ingredient_text, str):
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    parsed_ingredients.append(parsed)
        
        return json.dumps(parsed_ingredients, ensure_ascii=False) if parsed_ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self._get_recipe_json_ld()
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        if not isinstance(instructions, list):
            return None
        
        steps = []
        for step in instructions:
            if isinstance(step, dict) and 'text' in step:
                steps.append(step['text'])
            elif isinstance(step, str):
                steps.append(step)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self._get_recipe_json_ld()
        if not recipe_data:
            return None
        
        # Проверяем recipeCategory
        if 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            if isinstance(category, list):
                # Берем первую категорию
                return self.clean_text(category[0]) if category else None
            elif isinstance(category, str):
                return self.clean_text(category)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
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
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями в HTML
        notes_section = self.soup.find('div', class_='wprm-recipe-notes')
        
        if notes_section:
            # Извлекаем текст
            text = notes_section.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Если keywords уже строка с разделителями
                # Нормализуем разделители: заменяем запятую с пробелом на ", "
                keywords = keywords.replace(',', ', ')
                # Убираем множественные пробелы
                keywords = re.sub(r'\s+', ' ', keywords)
                return keywords.strip()
            elif isinstance(keywords, list):
                # Если keywords - это список
                return ', '.join(keywords)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        recipe_data = self._get_recipe_json_ld()
        if not recipe_data or 'image' not in recipe_data:
            return None
        
        images = recipe_data['image']
        urls = []
        
        if isinstance(images, str):
            urls.append(images)
        elif isinstance(images, list):
            for img in images:
                if isinstance(img, str):
                    urls.append(img)
                elif isinstance(img, dict):
                    if 'url' in img:
                        urls.append(img['url'])
                    elif 'contentUrl' in img:
                        urls.append(img['contentUrl'])
        elif isinstance(images, dict):
            if 'url' in images:
                urls.append(images['url'])
            elif 'contentUrl' in images:
                urls.append(images['contentUrl'])
        
        # Возвращаем URL через запятую без пробелов
        return ','.join(urls) if urls else None
    
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
    import os
    # Обрабатываем папку preprocessed/cookiemadness_net
    preprocessed_dir = os.path.join("preprocessed", "cookiemadness_net")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(CookieMadnessExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python cookiemadness_net.py")


if __name__ == "__main__":
    main()
