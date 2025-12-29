"""
Экстрактор данных рецептов для сайта delish.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class DelishExtractor(BaseRecipeExtractor):
    """Экстрактор для delish.com"""
    
    @staticmethod
    def format_amount(amount_str: str) -> Optional[str]:
        """
        Форматирует количество, преобразуя в число и удаляя .0 для целых чисел
        
        Args:
            amount_str: строка с количеством
            
        Returns:
            Отформатированное количество
        """
        if not amount_str:
            return None
        
        try:
            amount_val = float(amount_str)
            return str(amount_val) if amount_val != int(amount_val) else str(int(amount_val))
        except ValueError:
            return amount_str
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в удобочитаемый формат
        
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
        
        # Форматируем результат
        parts = []
        if hours > 0:
            parts.append(f"{hours} {'hour' if hours == 1 else 'hours'}")
        if minutes > 0:
            parts.append(f"{minutes} {'minute' if minutes == 1 else 'minutes'}")
        
        return ' '.join(parts) if parts else None
    
    def get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение Recipe из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем если это список
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                # Проверяем если это сразу Recipe
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe = self.get_recipe_json_ld()
        if recipe and 'name' in recipe:
            return self.clean_text(recipe['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " Recipe", " - Delish"
            title = re.sub(r'\s+(Recipe|Delish).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe = self.get_recipe_json_ld()
        if recipe and 'description' in recipe:
            return self.clean_text(recipe['description'])
        
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
        text = self.clean_text(ingredient_text).lower()
        
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
        # Note: Allow optional period after unit abbreviation
        pattern = r'^([\d\s/.,]+)?\s*(cups?|c\.|tablespoons?|teaspoons?|tbsps?|tsps?|tbsp\.?|tsp\.?|pounds?|ounces?|lbs?\.?|lb\.?|oz\.?|grams?|kilograms?|g\.?|kg\.?|milliliters?|ml\.?|liters?|l\.|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads|bunch)?\.?\s*(.+)'
        
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
                amount = self.format_amount(str(total))
            else:
                amount_str = amount_str.replace(',', '.')
                amount = self.format_amount(amount_str)
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        # Убираем точку в начале (артефакт парсинга)
        name = name.lstrip('.')
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
        ingredients = []
        
        recipe = self.get_recipe_json_ld()
        if recipe and 'recipeIngredient' in recipe:
            for ingredient_text in recipe['recipeIngredient']:
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    # Используем формат из примеров: units вместо unit
                    ingredients.append({
                        "name": parsed["name"],
                        "amount": parsed["amount"],
                        "units": parsed["unit"]
                    })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        recipe = self.get_recipe_json_ld()
        if recipe and 'recipeInstructions' in recipe:
            instructions = recipe['recipeInstructions']
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        text = step['text']
                        # Убираем &nbsp; и другие HTML entities
                        text = text.replace('&nbsp;', ' ')
                        text = self.clean_text(text)
                        steps.append(f"{idx}. {text}")
                    elif isinstance(step, str):
                        text = step.replace('&nbsp;', ' ')
                        text = self.clean_text(text)
                        steps.append(f"{idx}. {text}")
        
        if steps:
            return ' '.join(steps)
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        recipe = self.get_recipe_json_ld()
        if recipe and 'nutrition' in recipe:
            nutrition = recipe['nutrition']
            
            # Извлекаем калории
            calories = None
            if 'calories' in nutrition:
                cal_text = nutrition['calories']
                # Извлекаем только число
                cal_match = re.search(r'(\d+)', str(cal_text))
                if cal_match:
                    calories = cal_match.group(1)
            
            # Извлекаем БЖУ (белки/жиры/углеводы)
            protein = None
            fat = None
            carbs = None
            
            if 'proteinContent' in nutrition:
                prot_text = nutrition['proteinContent']
                prot_match = re.search(r'(\d+)', str(prot_text))
                if prot_match:
                    protein = prot_match.group(1)
            
            if 'fatContent' in nutrition:
                fat_text = nutrition['fatContent']
                fat_match = re.search(r'(\d+)', str(fat_text))
                if fat_match:
                    fat = fat_match.group(1)
            
            if 'carbohydrateContent' in nutrition:
                carb_text = nutrition['carbohydrateContent']
                carb_match = re.search(r'(\d+)', str(carb_text))
                if carb_match:
                    carbs = carb_match.group(1)
            
            # Форматируем согласно примерам: "171 calories per serving" или с БЖУ если есть
            if calories:
                if protein and fat and carbs:
                    return f"{calories} kcal; {protein}/{fat}/{carbs}"
                else:
                    return f"{calories} calories per serving"
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe = self.get_recipe_json_ld()
        if recipe and 'recipeCategory' in recipe:
            categories = recipe['recipeCategory']
            if isinstance(categories, list) and categories:
                # Берем основную категорию (обычно "Main Course", "Breakfast" и т.д.)
                # Ищем категории типа breakfast, brunch, main course и т.д.
                main_categories = ['breakfast', 'brunch', 'lunch', 'dinner', 'main course', 
                                 'appetizer', 'dessert', 'side dish', 'snack']
                for cat in categories:
                    if cat.lower() in main_categories:
                        return cat.title()
                # Если не нашли основную, берем первую
                return categories[0].title()
            elif isinstance(categories, str):
                return categories.title()
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe = self.get_recipe_json_ld()
        if recipe and 'prepTime' in recipe:
            return self.parse_iso_duration(recipe['prepTime'])
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe = self.get_recipe_json_ld()
        if recipe and 'cookTime' in recipe:
            cook_time_str = recipe['cookTime']
            cook_time = self.parse_iso_duration(cook_time_str)
            
            # Если cookTime = PT0S (0 секунд), вычисляем из total - prep
            if not cook_time or cook_time_str == 'PT0S':
                total_time_str = recipe.get('totalTime')
                prep_time_str = recipe.get('prepTime')
                
                if total_time_str and prep_time_str:
                    # Извлекаем минуты из total и prep
                    total_match = re.search(r'PT(?:(\d+)H)?(?:(\d+)M)?', total_time_str)
                    prep_match = re.search(r'PT(?:(\d+)H)?(?:(\d+)M)?', prep_time_str)
                    
                    if total_match and prep_match:
                        total_h, total_m = total_match.groups()
                        prep_h, prep_m = prep_match.groups()
                        
                        total_minutes = (int(total_h) if total_h else 0) * 60 + (int(total_m) if total_m else 0)
                        prep_minutes = (int(prep_h) if prep_h else 0) * 60 + (int(prep_m) if prep_m else 0)
                        
                        cook_minutes = total_minutes - prep_minutes
                        if cook_minutes > 0:
                            hours = cook_minutes // 60
                            mins = cook_minutes % 60
                            parts = []
                            if hours > 0:
                                parts.append(f"{hours} {'hour' if hours == 1 else 'hours'}")
                            if mins > 0:
                                parts.append(f"{mins} {'minute' if mins == 1 else 'minutes'}")
                            return ' '.join(parts) if parts else None
                
                # Если не получилось вычислить, ищем в инструкциях
                instructions = self.extract_steps()
                if instructions:
                    # Ищем паттерны типа "20-30 minutes", "45 to 55 minutes"
                    time_match = re.search(r'(\d+(?:\s+to\s+\d+)?)\s+minutes?', instructions, re.I)
                    if time_match:
                        return time_match.group(1) + ' minutes'
            else:
                return cook_time
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe = self.get_recipe_json_ld()
        if recipe and 'totalTime' in recipe:
            return self.parse_iso_duration(recipe['totalTime'])
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # В delish.com заметки могут быть в разных местах
        # Проверяем секции с классами типа "notes", "tips", "editor-note"
        notes_section = self.soup.find(class_=re.compile(r'(note|tip|editor.*note)', re.I))
        
        if notes_section:
            text = notes_section.get_text(separator=' ', strip=True)
            # Убираем возможные заголовки
            text = re.sub(r"^(Note|Tip|Editor'?s?\s+Note)\s*:?\s*", '', text, flags=re.I)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта"""
        tags_list = []
        
        recipe = self.get_recipe_json_ld()
        if recipe and 'keywords' in recipe:
            keywords = recipe['keywords']
            
            # keywords может быть либо строкой, либо списком
            if isinstance(keywords, list):
                # Если это список, объединяем его элементы
                keywords_str = ', '.join(keywords)
            else:
                keywords_str = keywords
            
            # Теперь парсим строку
            tags_raw = []
            for item in keywords_str.split(','):
                item = item.strip()
                # Пропускаем служебные теги с двоеточием
                if ':' in item:
                    continue
                # Пропускаем очень короткие теги
                if len(item) < 3:
                    continue
                tags_raw.append(item.lower())
            
            # Фильтруем служебные теги и стоп-слова
            stopwords = {
                'recipe', 'recipes', 'us', 'content-type', 'locale', 'displaytype',
                'shorttitle', 'contentid', 'nutrition', 'occasion', 'category',
                'totaltime', 'filtertime'
            }
            
            for tag in tags_raw:
                # Пропускаем стоп-слова
                if tag in stopwords:
                    continue
                tags_list.append(tag)
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags_list:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        # Возвращаем как строку через запятую с пробелом
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        recipe = self.get_recipe_json_ld()
        if recipe and 'image' in recipe:
            img = recipe['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                for image in img:
                    if isinstance(image, str):
                        urls.append(image)
                    elif isinstance(image, dict) and 'url' in image:
                        urls.append(image['url'])
            elif isinstance(img, dict) and 'url' in img:
                urls.append(img['url'])
        
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
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "nutrition_info": self.extract_nutrition_info(),
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # По умолчанию обрабатываем папку preprocessed/delish_com
    recipes_dir = os.path.join("preprocessed", "delish_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(DelishExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python delish_com.py")


if __name__ == "__main__":
    main()
