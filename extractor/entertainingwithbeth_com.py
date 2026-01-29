"""
Экстрактор данных рецептов для сайта entertainingwithbeth.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class EntertainingWithBethExtractor(BaseRecipeExtractor):
    """Экстрактор для entertainingwithbeth.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M", "PT1H30M", "P1DT1H45M"
            
        Returns:
            Время в читаемом формате, например "24 hours 40 minutes"
        """
        if not duration or not duration.startswith('P'):
            return None
        
        # Извлекаем компоненты
        days = 0
        hours = 0
        minutes = 0
        
        # Разделяем на день и время
        parts = duration[1:].split('T')
        
        # Обрабатываем день
        if len(parts) >= 1 and parts[0]:
            day_match = re.search(r'(\d+)D', parts[0])
            if day_match:
                days = int(day_match.group(1))
        
        # Обрабатываем время
        if len(parts) >= 2:
            time_part = parts[1]
            
            # Извлекаем часы
            hour_match = re.search(r'(\d+)H', time_part)
            if hour_match:
                hours = int(hour_match.group(1))
            
            # Извлекаем минуты
            min_match = re.search(r'(\d+)M', time_part)
            if min_match:
                minutes = int(min_match.group(1))
        
        # Конвертируем дни в часы
        total_hours = days * 24 + hours
        
        # Формируем строку
        result_parts = []
        if total_hours > 0:
            result_parts.append(f"{total_hours} {'hour' if total_hours == 1 else 'hours'}")
        if minutes > 0:
            result_parts.append(f"{minutes} {'minute' if minutes == 1 else 'minutes'}")
        
        return ' '.join(result_parts) if result_parts else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "2 cups (475ml) milk" или "1 vanilla bean"
            
        Returns:
            dict: {"name": "milk", "amount": "2", "unit": "cups"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Удаляем содержимое в скобках (обычно альтернативные измерения)
        text = re.sub(r'\([^)]*\)', '', text).strip()
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        pattern = r'^([\d\s/.,]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|tbs|tbsp?|tsp|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads|bean|beans|jumbo|units?)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Конвертируем в число если возможно
            if '/' in amount_str:
                # Дробь
                amount = amount_str
            else:
                try:
                    # Пробуем преобразовать в целое
                    amount = int(amount_str)
                except ValueError:
                    try:
                        # Пробуем в float
                        amount = float(amount_str)
                    except ValueError:
                        # Оставляем как строку
                        amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|use salted.*|increase to.*)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;.]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_recipe_from_json_ld(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем прямой тип Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                
                # Проверяем в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                
                # Проверяем список
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self, recipe_data: dict) -> Optional[str]:
        """Извлечение названия блюда из JSON-LD"""
        if not recipe_data:
            return None
        
        name = recipe_data.get('name')
        if name:
            # Убираем суффиксы типа " Recipe"
            name = re.sub(r'\s+Recipe$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта из HTML"""
        # Ищем первый параграф с описанием рецепта перед рецептом
        # Обычно это параграф, содержащий текст о рецепте
        paragraphs = self.soup.find_all('p')
        
        for p in paragraphs:
            text = p.get_text(strip=True)
            # Ищем параграф с ключевыми фразами о рецепте
            if text and len(text) > 50:
                # Проверяем, что это не часть рецепта (не содержит "Jump to Recipe" и т.п.)
                if 'Jump to Recipe' not in text and 'Subscribe' not in text:
                    # Проверяем, что содержит слово "recipe" (регистронезависимо)
                    if re.search(r'\brecipe\b', text, re.IGNORECASE):
                        return self.clean_text(text)
        
        return None
    
    def extract_ingredients(self, recipe_data: dict) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD"""
        if not recipe_data:
            return None
        
        recipe_ingredients = recipe_data.get('recipeIngredient', [])
        if not recipe_ingredients:
            return None
        
        ingredients = []
        for ingredient_text in recipe_ingredients:
            parsed = self.parse_ingredient(ingredient_text)
            if parsed:
                # Преобразуем в формат с 'units' вместо 'unit'
                ingredients.append({
                    "name": parsed["name"],
                    "units": parsed["unit"],
                    "amount": parsed["amount"]
                })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self, recipe_data: dict) -> Optional[str]:
        """Извлечение шагов приготовления из JSON-LD"""
        if not recipe_data:
            return None
        
        instructions = recipe_data.get('recipeInstructions', [])
        if not instructions:
            return None
        
        steps = []
        for step in instructions:
            if isinstance(step, dict) and 'text' in step:
                steps.append(step['text'])
            elif isinstance(step, str):
                steps.append(step)
        
        if steps:
            # Объединяем все шаги в один текст
            return ' '.join(steps)
        
        return None
    
    def extract_category(self, recipe_data: dict) -> Optional[str]:
        """Извлечение категории из JSON-LD"""
        if not recipe_data:
            return None
        
        # Пробуем recipeCategory
        category = recipe_data.get('recipeCategory')
        if category:
            # Убираем окончание 's' для единственного числа (Desserts -> Dessert)
            category = self.clean_text(category)
            if category.endswith('s') and category not in ['Desserts']:
                # Проверяем стандартные категории
                category = category.rstrip('s')
            elif category == 'Desserts':
                category = 'Dessert'
            return category
        
        # Если нет, пробуем recipeCuisine
        cuisine = recipe_data.get('recipeCuisine')
        if cuisine:
            return self.clean_text(cuisine)
        
        return None
    
    def extract_prep_time(self, recipe_data: dict) -> Optional[str]:
        """Извлечение времени подготовки из JSON-LD"""
        if not recipe_data:
            return None
        
        prep_time = recipe_data.get('prepTime')
        if prep_time:
            return self.parse_iso_duration(prep_time)
        
        return None
    
    def extract_cook_time(self, recipe_data: dict) -> Optional[str]:
        """Извлечение времени приготовления из JSON-LD"""
        if not recipe_data:
            return None
        
        cook_time = recipe_data.get('cookTime')
        if cook_time:
            return self.parse_iso_duration(cook_time)
        
        return None
    
    def extract_total_time(self, recipe_data: dict) -> Optional[str]:
        """Извлечение общего времени из JSON-LD"""
        if not recipe_data:
            return None
        
        total_time = recipe_data.get('totalTime')
        if total_time:
            return self.parse_iso_duration(total_time)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок из HTML"""
        notes_list = []
        
        # Ищем mv-create-notes-content (приоритет)
        notes_section = self.soup.find('div', class_='mv-create-notes-content')
        
        if notes_section:
            # Извлекаем первые два пункта списка
            list_items = notes_section.find_all('li')
            if list_items:
                for i, li in enumerate(list_items[:2]):  # Берем первые 2
                    text = li.get_text(separator=' ', strip=True)
                    text = self.clean_text(text)
                    if text:
                        notes_list.append(text)
        
        # Если не нашли, пробуем wprm-recipe-notes
        if not notes_list:
            wprm_notes = self.soup.find('div', class_='wprm-recipe-notes')
            if wprm_notes:
                text = wprm_notes.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                if text:
                    notes_list.append(text)
        
        return ' '.join(notes_list) if notes_list else None
    
    def extract_tags(self, recipe_data: dict) -> Optional[str]:
        """Извлечение тегов из JSON-LD"""
        if not recipe_data:
            return None
        
        tags = []
        
        # Добавляем кухню (приоритет)
        cuisine = recipe_data.get('recipeCuisine')
        if cuisine:
            tags.append(cuisine)
        
        # Добавляем категорию (без 's' в конце, lowercase)
        category = recipe_data.get('recipeCategory')
        if category:
            category = category.lower()
            if category == 'desserts':
                category = 'dessert'
            tags.append(category)
        
        # Извлекаем keywords (только если они простые и релевантные)
        keywords = recipe_data.get('keywords', '')
        if keywords:
            # Разделяем по запятой
            keyword_list = [k.strip() for k in keywords.split(',') if k.strip()]
            # Фильтруем keywords - берем только простые слова (не содержат "how to", рецепт и т.п.)
            for kw in keyword_list:
                kw_lower = kw.lower()
                if ('how to' not in kw_lower and 
                    'recipe' not in kw_lower and
                    len(kw) < 20):  # Короткие теги
                    tags.append(kw_lower)
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags:
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen.add(tag_lower)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self, recipe_data: dict) -> Optional[str]:
        """Извлечение URL изображений из JSON-LD"""
        if not recipe_data:
            return None
        
        urls = []
        
        image = recipe_data.get('image')
        if image:
            if isinstance(image, str):
                urls.append(image)
            elif isinstance(image, list):
                # Берем первые несколько изображений
                for img in image[:3]:
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, dict):
                        if 'url' in img:
                            urls.append(img['url'])
                        elif 'contentUrl' in img:
                            urls.append(img['contentUrl'])
            elif isinstance(image, dict):
                if 'url' in image:
                    urls.append(image['url'])
                elif 'contentUrl' in image:
                    urls.append(image['contentUrl'])
        
        return ','.join(urls) if urls else None
    
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта
        
        Returns:
            Словарь с данными рецепта
        """
        # Извлекаем данные из JSON-LD
        recipe_data = self.extract_recipe_from_json_ld()
        
        # Извлекаем все поля
        dish_name = self.extract_dish_name(recipe_data)
        description = self.extract_description()  # Из HTML
        ingredients = self.extract_ingredients(recipe_data)
        instructions = self.extract_instructions(recipe_data)
        category = self.extract_category(recipe_data)
        prep_time = self.extract_prep_time(recipe_data)
        cook_time = self.extract_cook_time(recipe_data)
        total_time = self.extract_total_time(recipe_data)
        notes = self.extract_notes()  # Из HTML
        tags = self.extract_tags(recipe_data)
        image_urls = self.extract_image_urls(recipe_data)
        
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
            "image_urls": image_urls
        }


def main():
    import os
    # Обрабатываем папку preprocessed/entertainingwithbeth_com
    preprocessed_dir = os.path.join("preprocessed", "entertainingwithbeth_com")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(EntertainingWithBethExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python entertainingwithbeth_com.py")


if __name__ == "__main__":
    main()
