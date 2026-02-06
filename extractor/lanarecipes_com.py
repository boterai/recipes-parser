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
    
    # Стоп-слова для фильтрации тегов
    TAG_STOPWORDS = {'recipe', 'recipes', 'easy', 'homemade'}
    
    # Единицы измерения для парсинга ингредиентов
    UNITS_PATTERN = (
        r'cups?|cup|tablespoons?|teaspoons?|tbsps?|tsps?|tbsp|tsp|'
        r'pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|'
        r'milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|'
        r'packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|'
        r'cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|'
        r'head|heads|unit'
    )
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "X minutes" (например, "90 minutes")
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
        
        # Fallback: extract from meta tags
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Remove suffixes like " - Easy Cooking, Endless Joy"
            title = re.sub(r'\s*[-–—]\s*.+$', '', title)
            return self.clean_text(title)
        
        # Fallback: extract from title tag
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Remove suffixes
            title = re.sub(r'\s*[-–—]\s*.+$', '', title)
            return self.clean_text(title)
        
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
        
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredients_list = []
            for ingredient_text in recipe_data['recipeIngredient']:
                # Парсим каждый ингредиент
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients_list.append(parsed)
            
            if ingredients_list:
                return json.dumps(ingredients_list, ensure_ascii=False)
        
        # Fallback: extract from HTML content
        # Look for list items containing ingredient information
        ingredients_list = []
        
        # First, try to extract from instruction steps that mention ingredients with quantities
        ingredients_list = self.extract_ingredients_from_instructions()
        
        # If no detailed ingredients found, try to extract names from paragraphs
        if not ingredients_list:
            for p in self.soup.find_all('p'):
                text = p.get_text()
                # Look for paragraphs mentioning "ingredients:" or "you'll need"
                if re.search(r'(ingredients?:|you\'ll need|basic ingredients?)', text, re.I):
                    # Extract ingredient names from the text
                    ingredient_names = self.extract_ingredient_names_from_text(text)
                    for name in ingredient_names:
                        ingredients_list.append({
                            "name": name,
                            "units": None,
                            "amount": None
                        })
                    break
        
        # If still no ingredients, try to find ingredients in list items with quantities
        if not ingredients_list:
            for list_elem in self.soup.find_all(['ol', 'ul'], class_=re.compile(r'wp-block-list', re.I)):
                # Check if this list contains ingredients (not instructions)
                first_li = list_elem.find('li')
                if first_li:
                    first_text = first_li.get_text()
                    # Skip if it looks like an instruction (starts with bold action word)
                    if re.search(r'<strong>(?:Mix|Whisk|Cook|Heat|Pour|Combine|Stir|Add|Bake|Serve)', str(first_li), re.I):
                        continue
                
                for li in list_elem.find_all('li'):
                    text = li.get_text()
                    # Look for patterns like "1 cup of flour", "2 eggs", etc.
                    if re.search(r'\d+.*(?:cup|tablespoon|teaspoon|gram|egg|milk|flour|oil|salt|powder)', text, re.I):
                        parsed = self.parse_ingredient_from_text(text)
                        if parsed:
                            ingredients_list.append(parsed)
                
                if ingredients_list:
                    break
        
        return json.dumps(ingredients_list, ensure_ascii=False) if ingredients_list else None
    
    def extract_ingredients_from_instructions(self) -> list:
        """Extract ingredients mentioned in instruction steps with quantities"""
        ingredients_map = {}
        
        # Find instruction list items
        for list_elem in self.soup.find_all(['ol', 'ul'], class_=re.compile(r'wp-block-list', re.I)):
            for li in list_elem.find_all('li'):
                text = li.get_text()
                
                # Look for ingredient mentions with quantities in instructions
                # Pattern: "1 cup of whole wheat flour", "1/2 cup of wheat germ", "two eggs", "2 tablespoons of oil"
                patterns = [
                    r'(\d+(?:\s*/\s*\d+)?)\s+(cups?|tablespoons?|teaspoons?|tbsps?|tsps?)\s+(?:of\s+)?([a-z\s]+?)(?:[,.]|\s+and\s)',
                    r'(a|one|two|three|four|five)\s+(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pinch(?:es)?)\s+(?:of\s+)?([a-z\s]+?)(?:[,.]|\s+and\s)',
                    r'(\d+(?:\s*/\s*\d+)?)\s+(cups?)\s+(?:of\s+)?([a-z\s]+)',
                    r'(two|one)\s+(eggs?)',
                ]
                
                for pattern in patterns:
                    matches = re.finditer(pattern, text, re.I)
                    for match in matches:
                        if len(match.groups()) == 3:
                            amount_str, unit, name = match.groups()
                        elif len(match.groups()) == 2:
                            amount_str, name = match.groups()
                            unit = None
                        else:
                            continue
                        
                        # Convert word numbers to digits
                        word_to_num = {'a': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5}
                        amount = word_to_num.get(amount_str.lower(), amount_str)
                        
                        # Handle fractions
                        if isinstance(amount, str) and '/' in amount:
                            parts = amount.split('/')
                            if len(parts) == 2:
                                try:
                                    amount = float(parts[0]) / float(parts[1])
                                except:
                                    pass
                        
                        # Clean up name
                        name = name.strip().lower()
                        name = re.sub(r'\s+', ' ', name)
                        
                        # Filter out non-ingredient phrases
                        if any(skip in name for skip in ['for each', 'per serving', 'if needed', 'as needed']):
                            continue
                        
                        # Store or update ingredient
                        if name and len(name) > 2:
                            # Use name as key to avoid duplicates
                            if name not in ingredients_map:
                                ingredients_map[name] = {
                                    "name": name,
                                    "units": unit.lower() if unit else None,
                                    "amount": amount
                                }
        
        return list(ingredients_map.values())
    
    def parse_ingredient_from_text(self, text: str) -> Optional[dict]:
        """Extract ingredient from descriptive text like '1 cup of whole wheat flour'"""
        text = self.clean_text(text)
        
        # Pattern to match quantity + unit + ingredient
        # Example: "1 cup of whole wheat flour" or "1/2 cup of wheat germ"
        pattern = r'([\d\s/.,½¼¾⅓⅔⅛⅜⅝⅞]+)\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|tbsp|tsp|pinch(?:es)?|pounds?|ounces?|lbs?|oz|grams?|g|kg)?\s*(?:of\s+)?(.+?)(?:\.|,|$)'
        
        match = re.search(pattern, text, re.I)
        if match:
            amount_str, unit, name = match.groups()
            
            # Clean up amount
            amount = None
            if amount_str:
                amount_str = amount_str.strip()
                # Handle fractions
                for fraction, decimal in {'½': '0.5', '¼': '0.25', '¾': '0.75', '⅓': '0.33', '⅔': '0.67'}.items():
                    amount_str = amount_str.replace(fraction, decimal)
                
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
                    try:
                        amount = float(amount_str.replace(',', '.'))
                    except ValueError:
                        amount = None
            
            # Clean up name
            if name:
                name = re.sub(r'\([^)]*\)', '', name)
                name = re.sub(r'\b(to taste|as needed|or more|if needed|optional)\b', '', name, flags=re.IGNORECASE)
                name = name.strip(' ,;.')
            
            if name and len(name) > 1:
                return {
                    "name": name.lower(),
                    "units": unit.lower() if unit else None,
                    "amount": amount
                }
        
        return None
    
    def extract_ingredient_names_from_text(self, text: str) -> list:
        """Extract ingredient names from a sentence like 'whole wheat flour, wheat germ, eggs, milk, and oil'"""
        # Find the part after "ingredients:" or "you'll need"
        match = re.search(r'(?:ingredients?:|you\'ll need|basic ingredients?)[:\s]+(.+?)(?:\.|For|$)', text, re.I | re.DOTALL)
        if not match:
            return []
        
        ingredient_text = match.group(1)
        
        # Split by commas and "and"
        # Example: "whole wheat flour, wheat germ, eggs, milk, and a touch of oil"
        parts = re.split(r',\s*(?:and\s+)?|,?\s+and\s+', ingredient_text)
        
        ingredients = []
        for part in parts:
            # Clean up
            part = re.sub(r'^(a\s+)?(?:touch\s+of\s+|some\s+)?', '', part, flags=re.I)
            part = re.sub(r'\([^)]*\)', '', part)
            part = part.strip(' ,;.')
            
            if part and len(part) > 2:
                ingredients.append(part.lower())
        
        return ingredients
    
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
        pattern = rf'^([\d\s/.,]+)?\s*({self.UNITS_PATTERN})?\s*(.+)'
        
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
        
        if recipe_data and 'recipeInstructions' in recipe_data:
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
            
            if steps:
                return ' '.join(steps)
        
        # Fallback: extract from HTML content
        steps = []
        
        # Try to find instructions in ordered/unordered lists
        for list_elem in self.soup.find_all(['ol', 'ul'], class_=re.compile(r'wp-block-list', re.I)):
            found_instructions = False
            for li in list_elem.find_all('li'):
                text = li.get_text()
                # Check if this looks like an instruction (starts with bold action word or contains cooking verbs)
                if re.search(r'<strong>[A-Z]|(?:Mix|Whisk|Cook|Heat|Pour|Combine|Stir|Add|Bake|Serve)', str(li), re.I):
                    found_instructions = True
                    # Remove the bold tags and get clean text
                    step_text = self.clean_text(text)
                    if step_text and len(step_text) > 10:
                        steps.append(step_text)
            
            if found_instructions:
                break
        
        # If we found steps, number them if they're not already numbered
        if steps:
            numbered_steps = []
            for idx, step in enumerate(steps, 1):
                if re.match(r'^\d+\.', step):
                    numbered_steps.append(step)
                else:
                    numbered_steps.append(f"{idx}. {step}")
            return ' '.join(numbered_steps)
        
        return None
    
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
                # Ищем категории (обычно категории начинаются с большой буквы)
                valid_categories = {'dessert', 'breakfast', 'lunch', 'dinner', 'appetizer', 'snack', 'main course'}
                for k in keywords:
                    if k.lower() in valid_categories:
                        return k
        
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
                
                for tag in keywords:
                    tag_lower = tag.lower()
                    if tag_lower not in self.TAG_STOPWORDS and len(tag_lower) >= 3:
                        filtered_tags.append(tag_lower)
                
                return ', '.join(filtered_tags) if filtered_tags else None
            
            # Если keywords - это строка с запятыми
            elif isinstance(keywords, str):
                tags = [tag.strip().lower() for tag in keywords.split(',')]
                filtered_tags = [tag for tag in tags if tag not in self.TAG_STOPWORDS and len(tag) >= 3]
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
                                
                                for tag in keywords:
                                    tag_lower = tag.lower()
                                    if tag_lower not in self.TAG_STOPWORDS and len(tag_lower) >= 3:
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
