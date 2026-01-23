"""
Экстрактор данных рецептов для сайта polishfeast.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class PolishFeastExtractor(BaseRecipeExtractor):
    """Экстрактор для polishfeast.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "P1D" или "P1DT50M" или "PT24H50M"
            
        Returns:
            Время в читаемом формате, например "20 minutes" или "1 day 50 minutes"
        """
        if not duration:
            return None
        
        # Обрабатываем дни
        days = 0
        day_match = re.search(r'P(\d+)D', duration)
        if day_match:
            days = int(day_match.group(1))
        
        # Обрабатываем время после "T"
        hours = 0
        minutes = 0
        
        if 'T' in duration:
            time_part = duration.split('T')[1]
            
            # Извлекаем часы
            hour_match = re.search(r'(\d+)H', time_part)
            if hour_match:
                hours = int(hour_match.group(1))
            
            # Извлекаем минуты
            min_match = re.search(r'(\d+)M', time_part)
            if min_match:
                minutes = int(min_match.group(1))
        
        # Конвертируем большое количество часов в дни (24+ hours)
        if hours >= 24 and days == 0:
            days = hours // 24
            hours = hours % 24
        
        # Конвертируем дни в часы для prep_time (когда нет других компонентов)
        # Если есть дни но нет часов/минут, показываем в часах (24 hours вместо 1 day)
        if days > 0 and hours == 0 and minutes == 0:
            total_hours = days * 24
            return f"{total_hours} hours" if total_hours > 1 else f"{total_hours} hour"
        
        # Формируем строку
        result_parts = []
        if days > 0:
            result_parts.append(f"{days} day" if days == 1 else f"{days} days")
        if hours > 0:
            result_parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
        if minutes > 0:
            result_parts.append(f"{minutes} minute" if minutes == 1 else f"{minutes} minutes")
        
        return ' '.join(result_parts) if result_parts else None
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение Recipe данных из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                # Проверяем тип Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'name' in recipe_data:
            name = recipe_data['name']
            # Убираем суффиксы типа " Recipe", " - PolishFeast"
            name = re.sub(r'\s+(Recipe|PolishFeast).*$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour" или "2 pounds chicken"
            
        Returns:
            dict: {"name": "flour", "amount": 1, "units": "cup"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
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
        # Примеры: "1 cup flour", "2 tablespoons butter", "1/2 teaspoon salt"
        pattern = r'^([\d\s/.,]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|piece|head|heads|tsp|tbsp|unit)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2" или "1 1/2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0.0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                amount = int(total) if total == int(total) else total
            else:
                try:
                    val = float(amount_str.replace(',', '.'))
                    amount = int(val) if val == int(val) else val
                except:
                    amount = None
        
        # Обработка единицы измерения - нормализация
        unit_clean = None
        if unit:
            unit_lower = unit.lower().strip()
            
            # Маппинг сокращений к полным формам
            unit_mapping = {
                'tsp': 'teaspoon',
                'tsps': 'teaspoon',
                'teaspoons': 'teaspoon',
                'tbsp': 'tablespoon',
                'tbsps': 'tablespoon',
                'tablespoons': 'tablespoon',
                'lb': 'pound',
                'lbs': 'pounds',
                'pound': 'pounds',
                'oz': 'ounce',
                'ounce': 'ounces',
                'gram': 'grams',
                'g': 'grams',
                'kilogram': 'kilograms',
                'kg': 'kilograms',
                'milliliter': 'ml',
                'milliliters': 'ml',
                'liter': 'l',
                'liters': 'l',
                'cup': 'cups' if amount and amount > 1 else 'cup',
                'cups': 'cups',
                'slice': 'slices' if amount and amount > 1 else 'slices',
                'slices': 'slices',
                'piece': 'piece',
                'pieces': 'piece',
                'pinch': 'pinch',
                'pinches': 'pinch',
                'unit': 'piece',  # "1 medium sugar pumpkin" -> unit: piece
            }
            
            unit_clean = unit_mapping.get(unit_lower, unit_lower)
        elif amount is not None:
            # If we have an amount but no unit detected, assume "piece"
            # This handles cases like "1 medium sugar pumpkin"
            unit_clean = 'piece'
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional", "peeled and cubed"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|peeled and cubed|cubed|peeled|, about .+|about \d+.+)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+\s*$', '', name)
        name = re.sub(r'^\s*[,;]+', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit_clean
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        recipe_data = self._get_recipe_json_ld()
        
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredients = []
        for ingredient_text in recipe_data['recipeIngredient']:
            parsed = self.parse_ingredient(ingredient_text)
            if parsed:
                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self._get_recipe_json_ld()
        
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        steps = []
        
        if isinstance(instructions, list):
            for step in instructions:
                if isinstance(step, dict):
                    # Формат HowToStep
                    step_name = step.get('name', '')
                    step_text = step.get('text', '')
                    
                    if step_name and step_text:
                        steps.append(f"{step_name}: {step_text}")
                    elif step_text:
                        steps.append(step_text)
                    elif step_name:
                        steps.append(step_name)
                elif isinstance(step, str):
                    steps.append(step)
        elif isinstance(instructions, str):
            steps.append(instructions)
        
        # Join without numbering (reference doesn't have numbers)
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            return self.clean_text(recipe_data['recipeCategory'])
        
        # Fallback: try to get from BlogPosting articleSection
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BlogPosting' and 'articleSection' in item:
                            # Extract from articleSection and simplify
                            # "Soups & Broths" -> "Soup", "Breads & Pastries" -> "Bread"
                            section = item['articleSection']
                            # Remove HTML entities
                            import html
                            section = html.unescape(section)
                            
                            # Simple mapping
                            if 'Soup' in section:
                                return 'Soup'
                            elif 'Bread' in section:
                                return 'Bread'
                            else:
                                # Return first word
                                return section.split()[0] if section else None
                                
            except (json.JSONDecodeError, KeyError):
                continue
        
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
        notes_section = self.soup.find(class_='tasty-recipes-notes-body')
        
        if notes_section:
            # Получаем весь текст из параграфов
            paragraphs = notes_section.find_all('p')
            if paragraphs:
                notes_texts = [self.clean_text(p.get_text()) for p in paragraphs]
                # Remove bullet points and join with space
                cleaned_notes = []
                for note in notes_texts:
                    # Remove leading bullet characters
                    note = re.sub(r'^[•●○■▪▫\-\*]+\s*', '', note)
                    cleaned_notes.append(note)
                return ' '.join(cleaned_notes) if cleaned_notes else None
            else:
                # Если нет параграфов, берем весь текст
                text = self.clean_text(notes_section.get_text())
                # Remove bullet points
                text = re.sub(r'^[•●○■▪▫\-\*]+\s*', '', text)
                return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        article_section = None
        blog_keywords = None
        recipe_keywords = None
        recipe_name = None
        
        # Get data from JSON-LD
        for script in json_ld_scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                if data.get('@type') == 'Recipe':
                    if 'keywords' in data:
                        recipe_keywords = data['keywords']
                    if 'name' in data:
                        recipe_name = data['name']
                
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BlogPosting':
                            import html
                            if 'articleSection' in item:
                                article_section = html.unescape(item['articleSection'])
                            if 'keywords' in item:
                                blog_keywords = item['keywords']
                            
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Strategy:
        # If blog_keywords are generic food category terms (not the recipe name),
        # split them by spaces and potentially add "Polish"
        # Otherwise, use articleSection + Traditional Polish
        
        use_article_section = True
        
        if blog_keywords and len(blog_keywords.split()) <= 4:
            # Check if blog_keywords look like category terms vs recipe name
            # Category terms: "Sourdough Rye Bread", "Traditional Polish Soup"
            # Recipe names: "Polish Pumpkin Soup", "Polish Sourdough Rye Bread Recipe"
            
            # If blog_keywords don't contain the recipe name (simplified), use them as tags
            if recipe_name:
                # Simplify both for comparison
                blog_simple = blog_keywords.lower().replace(' recipe', '').strip()
                recipe_simple = recipe_name.lower().replace(' recipe', '').replace(' (zupa z dyni)', '').strip()
                
                # If blog is a subset of recipe, blog_keywords are category terms
                # Example: "sourdough rye bread" ⊂ "polish sourdough rye bread"
                if blog_simple in recipe_simple and blog_simple != recipe_simple:
                    use_article_section = False
                    parts = blog_keywords.split()
                    
                    # Check if we need to add "Polish" from recipe keywords
                    if recipe_keywords and 'polish' in recipe_keywords.lower():
                        if not any('polish' in p.lower() for p in parts):
                            tags_list = ['Polish'] + parts
                        else:
                            tags_list = parts
                    else:
                        tags_list = parts
        
        if use_article_section and article_section:
            # Use articleSection
            tags_list = [article_section]
            
            # Add "Traditional Polish" for Polish recipe site
            tags_list.append('Traditional Polish')
        
        return ', '.join(tags_list) if tags_list else None
    
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
            urls.extend([img for img in images if isinstance(img, str)])
        
        # Возвращаем как строку через запятую
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
    # Обрабатываем папку preprocessed/polishfeast_com
    preprocessed_dir = os.path.join("preprocessed", "polishfeast_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(PolishFeastExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python polishfeast_com.py")


if __name__ == "__main__":
    main()
