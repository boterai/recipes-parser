"""
Экстрактор данных рецептов для сайта lanarecipes.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class LanaRecipesExtractor(BaseRecipeExtractor):
    """Экстрактор для lanarecipes.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "X minutes" или "X hours Y minutes"
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
        
        # Форматируем результат
        if hours > 0 and minutes > 0:
            return f"{hours * 60 + minutes} minutes"
        elif hours > 0:
            return f"{hours * 60} minutes"
        elif minutes > 0:
            return f"{minutes} minutes"
        
        return None
    
    def get_recipe_data(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            return item
                
                # Ищем Recipe напрямую
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                
                # Ищем в массиве
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                            
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self.get_recipe_data()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self.get_recipe_data()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        recipe_data = self.get_recipe_data()
        
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredients_list = []
        for ingredient_text in recipe_data['recipeIngredient']:
            # Парсим каждый ингредиент
            parsed = self.parse_ingredient(ingredient_text)
            if parsed:
                ingredients_list.append(parsed)
        
        return json.dumps(ingredients_list, ensure_ascii=False) if ingredients_list else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "4 cups whole milk" или "2 tbsp white vinegar (Lemon juice...)"
            
        Returns:
            dict: {"name": "whole milk", "amount": 4, "units": "cups"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст от комментариев в скобках
        text = re.sub(r'\([^)]*\)', '', ingredient_text)
        text = self.clean_text(text).lower()
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        pattern = r'^([\d\s/.,]+)?\s*(cups?|cup|tablespoons?|teaspoons?|tbsps?|tsps?|tbsp|tsp|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads|unit)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "units": None,
                "amount": None
            }
        
        amount_str, units, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
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
                amount = total
            else:
                amount = float(amount_str.replace(',', '.'))
        
        # Очистка единицы измерения
        units = units.strip() if units else None
        
        # Очистка названия
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish)\b', '', name, flags=re.IGNORECASE)
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "units": units,
            "amount": amount
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self.get_recipe_data()
        
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        steps = []
        
        if isinstance(instructions, list):
            for idx, step in enumerate(instructions, 1):
                if isinstance(step, dict) and 'text' in step:
                    step_text = self.clean_text(step['text'])
                    # Если текст уже начинается с шага (напр. "1. Heat..."), используем как есть
                    if re.match(r'^\d+\.', step_text):
                        steps.append(step_text)
                    else:
                        steps.append(f"{idx}. {step_text}")
                elif isinstance(step, str):
                    step_text = self.clean_text(step)
                    if re.match(r'^\d+\.', step_text):
                        steps.append(step_text)
                    else:
                        steps.append(f"{idx}. {step_text}")
        elif isinstance(instructions, str):
            steps.append(self.clean_text(instructions))
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self.get_recipe_data()
        
        # Проверяем в recipeCategory
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            if isinstance(category, list):
                return ', '.join(category)
            return self.clean_text(category)
        
        # Проверяем в keywords (если есть категории типа Dessert, Breakfast)
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, list):
                # Ищем категории (обычно с большой буквы: Dessert, Breakfast, etc.)
                categories = [k for k in keywords if k and k[0].isupper() and k.lower() in ['dessert', 'breakfast', 'lunch', 'dinner', 'appetizer', 'snack', 'main course']]
                if categories:
                    return categories[0]
        
        # Проверяем articleSection в @graph
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list) and sections:
                                # Фильтруем общие категории типа "All Recipes"
                                filtered = [s for s in sections if s.lower() not in ['all recipes', 'recipes']]
                                if filtered:
                                    return filtered[0]
                                return sections[0]
                            return sections
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.get_recipe_data()
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        recipe_data = self.get_recipe_data()
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.get_recipe_data()
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        # Если totalTime отсутствует, можно вычислить из prep + cook
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        
        if prep_time and cook_time:
            # Извлекаем числа из строк типа "24 minutes"
            prep_match = re.search(r'(\d+)', prep_time)
            cook_match = re.search(r'(\d+)', cook_time)
            if prep_match and cook_match:
                total = int(prep_match.group(1)) + int(cook_match.group(1))
                return f"{total} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем секцию с классом wprm-recipe-notes (WordPress Recipe Maker)
        notes_container = self.soup.find('div', class_='wprm-recipe-notes')
        
        if notes_container:
            # Извлекаем все span элементы с текстом
            spans = notes_container.find_all('span')
            
            for span in spans:
                text = self.clean_text(span.get_text())
                # Ищем секцию с "Tips for Success" или похожими паттернами
                if text and ('tips for success' in text.lower() or 
                           'important' in text.lower() or
                           text.lower().startswith('tip')):
                    # Убираем префикс "Tips for Success:"
                    text = re.sub(r'^tips for success:?\s*', '', text, flags=re.IGNORECASE)
                    if text and len(text) > 10:
                        return text
                # Если нашли просто хорошую заметку без специального префикса
                elif text and len(text) > 20 and not text.lower().startswith(('substitution', 'storage', 'faq')):
                    return text
        
        # Альтернативный поиск по паттернам
        notes_patterns = [
            re.compile(r'note', re.I),
            re.compile(r'tip', re.I),
            re.compile(r'hint', re.I),
            re.compile(r'advice', re.I)
        ]
        
        for pattern in notes_patterns:
            note_elem = self.soup.find(class_=pattern)
            if note_elem:
                text = self.clean_text(note_elem.get_text())
                # Убираем заголовки типа "Notes:", "Tips:", etc.
                text = re.sub(r'^(notes?|tips?|hints?|advice):?\s*', '', text, flags=re.IGNORECASE)
                if text and len(text) > 10:
                    return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Сначала проверяем keywords в Recipe
        recipe_data = self.get_recipe_data()
        
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            
            # Если keywords - это список
            if isinstance(keywords, list) and keywords:
                # Фильтруем стоп-слова
                filtered_tags = []
                stopwords = {'recipe', 'recipes', 'easy', 'homemade'}
                
                for tag in keywords:
                    tag_lower = tag.lower()
                    if tag_lower not in stopwords and len(tag_lower) >= 3:
                        filtered_tags.append(tag_lower)
                
                return ', '.join(filtered_tags) if filtered_tags else None
            
            # Если keywords - это строка с запятыми
            elif isinstance(keywords, str):
                tags = [tag.strip().lower() for tag in keywords.split(',')]
                stopwords = {'recipe', 'recipes', 'easy', 'homemade'}
                filtered_tags = [tag for tag in tags if tag not in stopwords and len(tag) >= 3]
                return ', '.join(filtered_tags) if filtered_tags else None
        
        # Если не нашли в Recipe, ищем в Article
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'keywords' in item:
                            keywords = item['keywords']
                            if isinstance(keywords, list) and keywords:
                                # Фильтруем стоп-слова
                                filtered_tags = []
                                stopwords = {'recipe', 'recipes', 'easy', 'homemade'}
                                
                                for tag in keywords:
                                    tag_lower = tag.lower()
                                    if tag_lower not in stopwords and len(tag_lower) >= 3:
                                        filtered_tags.append(tag_lower)
                                
                                return ', '.join(filtered_tags) if filtered_tags else None
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        recipe_data = self.get_recipe_data()
        
        if not recipe_data or 'image' not in recipe_data:
            return None
        
        image_data = recipe_data['image']
        urls = []
        
        # Если image - это список
        if isinstance(image_data, list):
            for img in image_data:
                if isinstance(img, str):
                    urls.append(img)
                elif isinstance(img, dict):
                    if 'url' in img:
                        urls.append(img['url'])
                    elif 'contentUrl' in img:
                        urls.append(img['contentUrl'])
        
        # Если image - это словарь
        elif isinstance(image_data, dict):
            if 'url' in image_data:
                urls.append(image_data['url'])
            elif 'contentUrl' in image_data:
                urls.append(image_data['contentUrl'])
        
        # Если image - это строка
        elif isinstance(image_data, str):
            urls.append(image_data)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        return ','.join(unique_urls) if unique_urls else None
    
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
    """Точка входа для обработки HTML файлов"""
    import os
    
    # Обрабатываем папку preprocessed/lanarecipes_com
    recipes_dir = os.path.join("preprocessed", "lanarecipes_com")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(LanaRecipesExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python lanarecipes_com.py")


if __name__ == "__main__":
    main()
