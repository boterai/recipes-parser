"""
Экстрактор данных рецептов для сайта maggi.ph
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MaggiPhExtractor(BaseRecipeExtractor):
    """Экстрактор для maggi.ph"""
    
    def get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных из JSON-LD schema"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            return item
                
                # Или напрямую Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def parse_iso_duration(self, duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT30S"
            
        Returns:
            Время в формате "20 minutes" или "1 hour 30 minutes"
        """
        if not duration or not duration.startswith('PT'):
            return None
        
        duration = duration[2:]  # Убираем "PT"
        
        hours = 0
        minutes = 0
        seconds = 0
        
        # Извлекаем часы
        hour_match = re.search(r'(\d+)H', duration)
        if hour_match:
            hours = int(hour_match.group(1))
        
        # Извлекаем минуты
        min_match = re.search(r'(\d+)M', duration)
        if min_match:
            minutes = int(min_match.group(1))
        
        # Извлекаем секунды
        sec_match = re.search(r'(\d+)S', duration)
        if sec_match:
            seconds = int(sec_match.group(1))
        
        # Конвертируем секунды в минуты (если больше или равно 60)
        if seconds >= 60:
            minutes += seconds // 60
            seconds = seconds % 60
        elif seconds > 0 and hours == 0 and minutes == 0:
            # Если есть только секунды, конвертируем в минуты
            minutes = 1  # Округляем вверх до 1 минуты
        
        # Формируем строку
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour" + ("s" if hours > 1 else ""))
        if minutes > 0:
            parts.append(f"{minutes} minute" + ("s" if minutes > 1 else ""))
        
        return " ".join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self.get_json_ld_data()
        
        if recipe_data and 'name' in recipe_data:
            name = recipe_data['name']
            # Убираем суффикс "Recipe"
            name = re.sub(r'\s+Recipe\s*$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s+Recipe\s*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self.get_json_ld_data()
        
        if recipe_data and 'description' in recipe_data:
            description = recipe_data['description']
            # Берем только первое предложение или первые 200 символов
            sentences = re.split(r'(?<=[.!?])\s+', description)
            if sentences:
                return self.clean_text(sentences[0])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "2 tbsp vegetable oil" или "4 cloves garlic crushed"
            
        Returns:
            dict: {"name": "vegetable oil", "amount": "2", "unit": "tbsp"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).strip()
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅜': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5'
        }
        
        for fraction, replacement in fraction_map.items():
            text = text.replace(fraction, replacement)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "2 tbsp vegetable oil", "4 cloves garlic crushed", "1/4 kg ampalaya sliced"
        pattern = r'^([\d\s/.,]+)?\s*(tbsp|tsp|tablespoons?|teaspoons?|cups?|kg|kilograms?|g|grams?|ml|milliliters?|l|liters?|oz|ounces?|lb|lbs|pounds?|cloves?|pcs?|pieces?|pc|can|cans|sachets?|sachet)?\s*(.+)'
        
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
            amount = amount_str
        
        # Обработка единицы измерения
        if unit:
            unit = unit.strip().lower()
            # Нормализация единиц
            unit_map = {
                'tbsp': 'tablespoons',
                'tsp': 'teaspoons',
                'pc': 'piece',
                'pcs': 'pieces',
                'kg': 'kilograms',
                'g': 'grams',
                'ml': 'milliliters',
                'l': 'liters',
                'lb': 'pounds',
                'lbs': 'pounds',
                'oz': 'ounces',
            }
            unit = unit_map.get(unit, unit)
        
        # Очистка названия
        # Удаляем инструкции типа "crushed", "diced", "sliced", "beaten"
        name = re.sub(r'\b(crushed|diced|sliced|chopped|beaten|minced|peeled|rinsed well|well|and)\b', '', name, flags=re.IGNORECASE)
        # Удаляем запятые и лишние пробелы
        name = re.sub(r'[,;]+', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        recipe_data = self.get_json_ld_data()
        
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredients_list = recipe_data['recipeIngredient']
            
            parsed_ingredients = []
            for ingredient_text in ingredients_list:
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    # Переименовываем поле unit в units для соответствия эталону
                    parsed_dict = {
                        "name": parsed["name"],
                        "units": parsed["unit"],
                        "amount": parsed["amount"]
                    }
                    parsed_ingredients.append(parsed_dict)
            
            return json.dumps(parsed_ingredients, ensure_ascii=False) if parsed_ingredients else None
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self.get_json_ld_data()
        
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        steps.append(f"{idx}. {self.clean_text(step['text'])}")
                    elif isinstance(step, str):
                        steps.append(f"{idx}. {self.clean_text(step)}")
            
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self.get_json_ld_data()
        
        # Пробуем recipeCuisine (Filipino, Italian, etc.)
        if recipe_data:
            if 'recipeCuisine' in recipe_data:
                return self.clean_text(recipe_data['recipeCuisine'])
            
            # Альтернативно - recipeCategory
            if 'recipeCategory' in recipe_data:
                return self.clean_text(recipe_data['recipeCategory'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.get_json_ld_data()
        
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self.get_json_ld_data()
        
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.get_json_ld_data()
        
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем секцию с заголовком содержащим "TIP"
        titles = self.soup.find_all('div', class_=re.compile(r'field-c-title'))
        for title in titles:
            title_text = title.get_text().strip().upper()
            if 'TIP' in title_text:
                # Ищем field-c-text в том же родителе
                parent = title.parent
                if parent:
                    notes_div = parent.find('div', class_=re.compile(r'field-c-text'))
                    if notes_div:
                        p = notes_div.find('p')
                        if p:
                            text = self.clean_text(p.get_text())
                            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        recipe_data = self.get_json_ld_data()
        
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            # keywords - это строка с тегами через запятую
            # Фильтруем и очищаем
            tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            
            # Фильтрация: убираем слишком длинные теги и служебные слова
            filtered_tags = []
            stopwords = {
                'recipe', 'recipes', 'receta de sopa sencilla',
                'other', 'top dish', 'from the pan'
            }
            
            for tag in tags_list:
                tag_lower = tag.lower()
                # Пропускаем стоп-слова и слишком длинные фразы (>30 символов)
                if tag_lower in stopwords or len(tag) > 30:
                    continue
                filtered_tags.append(tag)
            
            # Возвращаем как строку через запятую с пробелом
            return ', '.join(filtered_tags) if filtered_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Из JSON-LD
        recipe_data = self.get_json_ld_data()
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
        # 2. Из meta тегов
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        og_image_url = self.soup.find('meta', property='og:image:url')
        if og_image_url and og_image_url.get('content'):
            urls.append(og_image_url['content'])
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            # Возвращаем как строку через запятую без пробелов
            return ','.join(unique_urls) if unique_urls else None
        
        return None
    
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта
        
        Returns:
            Словарь с данными рецепта
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        total_time = self.extract_total_time()
        notes = self.extract_notes()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()
        
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
    """Обработка директории с HTML-файлами maggi.ph"""
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join("preprocessed", "maggi_ph")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(MaggiPhExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python maggi_ph.py")


if __name__ == "__main__":
    main()
