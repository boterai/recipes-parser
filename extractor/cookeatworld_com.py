"""
Экстрактор данных рецептов для сайта cookeatworld.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CookeatWorldExtractor(BaseRecipeExtractor):
    """Экстрактор для cookeatworld.com"""
    
    # Список единиц измерения для ингредиентов
    MEASUREMENT_UNITS = [
        'cups?', 'tablespoons?', 'teaspoons?', 'tbsps?', 'tsps?', 'tbsp', 'tsp',
        'pounds?', 'ounces?', 'lbs?', 'oz', 'grams?', 'kilograms?', 'kg',
        'milliliters?', 'liters?', 'ml', 'pinch(?:es)?', 'dash(?:es)?',
        'packages?', 'cans?', 'jars?', 'bottles?', 'inch(?:es)?', 'slices?',
        'cloves?', 'bunches?', 'sprigs?', 'whole', 'halves?', 'quarters?',
        'pieces?', 'head|heads', 'g', 'l'
    ]
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в читаемом формате, например "90 minutes" или "1 hour 30 minutes"
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
        
        # Форматируем в читаемый вид
        if hours > 0 and minutes > 0:
            hour_str = "hour" if hours == 1 else "hours"
            return f"{hours} {hour_str} {minutes} minutes"
        elif hours > 0:
            hour_str = "hour" if hours == 1 else "hours"
            return f"{hours} {hour_str}"
        elif minutes > 0:
            return f"{minutes} minutes"
        
        return None
    
    def get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение Recipe из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                # Проверяем наличие @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                
                # Проверяем напрямую
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " | cookeatworld.com"
            title = re.sub(r'\s*\|.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self.get_recipe_json_ld()
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
    
    def parse_ingredient_string(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 tbsp ghee or oil" или "4 eggs ((beaten))"
            
        Returns:
            dict: {"name": "ghee or oil", "amount": 1, "units": "tbsp"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст от HTML entities
        text = self.clean_text(ingredient_text)
        
        # Убираем все содержимое в скобках
        # Используем простой подход - удаляем все что в скобках, включая вложенные
        max_iterations = 10
        iteration = 0
        while '(' in text and iteration < max_iterations:
            # Убираем самые внутренние скобки (те, что не содержат других скобок)
            old_text = text
            text = re.sub(r'\([^()]*\)', '', text)
            if old_text == text:
                # Если ничего не изменилось, выходим
                break
            iteration += 1
        
        text = text.strip()
        
        # Переводим в нижний регистр
        text = text.lower()
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Сначала пробуем паттерн с единицей измерения
        units_pattern = '|'.join(self.MEASUREMENT_UNITS)
        pattern_with_unit = rf'^([\d\s/.,]+)\s+({units_pattern})\b\s*(.+)'
        
        match = re.match(pattern_with_unit, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
        else:
            # Пробуем паттерн без единицы измерения (просто число + название)
            pattern_without_unit = r'^([\d\s/.,]+)\s+(.+)'
            match = re.match(pattern_without_unit, text)
            if match:
                amount_str, name = match.groups()
                unit = None
            else:
                # Если ничего не совпало, возвращаем весь текст как название
                return {
                    "name": text,
                    "amount": None,
                    "units": None
                }
        
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
                # Возвращаем как число (int или float)
                amount = int(total) if isinstance(total, float) and total.is_integer() else total
            else:
                amount_str = amount_str.replace(',', '.')
                try:
                    amount_val = float(amount_str)
                    # Возвращаем как число (int или float)
                    amount = int(amount_val) if amount_val.is_integer() else amount_val
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения - если нет явной единицы, используем "pieces"
        if unit:
            unit = unit.strip()
        elif amount is not None:
            # Если есть количество но нет единицы, используем "pieces"
            unit = "pieces"
        else:
            unit = None
        
        # Очистка названия
        name = re.sub(r'\([^)]*\)', '', name)
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|cut into wedges)\b', '', name, flags=re.IGNORECASE)
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
        recipe_data = self.get_recipe_json_ld()
        ingredients = []
        
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredient_list = recipe_data['recipeIngredient']
            if isinstance(ingredient_list, list):
                for ingredient_text in ingredient_list:
                    parsed = self.parse_ingredient_string(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        # Разбиваем длинный текст на отдельные предложения
                        # Используем точку с заглавной буквой как разделитель
                        sentences = re.split(r'\.(?=[A-Z])', step_text)
                        for sentence in sentences:
                            sentence = sentence.strip()
                            if sentence:
                                # Добавляем точку если её нет
                                if not sentence.endswith('.'):
                                    sentence += '.'
                                steps.append(sentence)
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        if step_text:
                            steps.append(step_text)
            
            # Возвращаем как JSON список
            return json.dumps(steps, ensure_ascii=False) if steps else None
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности в формате: 202 kcal; 2/11/27"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'nutrition' in recipe_data:
            nutrition = recipe_data['nutrition']
            
            # Извлекаем калории
            calories = None
            if 'calories' in nutrition:
                cal_text = nutrition['calories']
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
            
            # Форматируем: "202 kcal; 2/11/27"
            if calories and protein and fat and carbs:
                return f"{calories} kcal; {protein}/{fat}/{carbs}"
            elif calories:
                return f"{calories} kcal"
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            categories = recipe_data['recipeCategory']
            if isinstance(categories, list):
                return ', '.join(categories)
            elif isinstance(categories, str):
                return categories
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем в HTML секцию с классом wprm-recipe-notes
        notes_container = self.soup.find(class_=re.compile(r'wprm-recipe-notes', re.I))
        
        if notes_container:
            # Ищем параграфы или текст внутри
            paragraphs = notes_container.find_all(['p', 'div'], class_=lambda x: x and 'wprm-recipe-notes' in x)
            if paragraphs:
                text_parts = []
                for p in paragraphs:
                    text = p.get_text(separator=' ', strip=True)
                    text = self.clean_text(text)
                    if text:
                        text_parts.append(text)
                if text_parts:
                    return ' '.join(text_parts)
            else:
                # Если нет параграфов, берем весь текст
                text = notes_container.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                # Убираем заголовки типа "Notes:", "Tips:"
                text = re.sub(r'^(Notes?|Tips?|Advice):?\s*', '', text, flags=re.IGNORECASE)
                return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        recipe_data = self.get_recipe_json_ld()
        tags = []
        
        # Извлекаем из keywords в JSON-LD
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Разделяем по запятой
                tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            elif isinstance(keywords, list):
                tags = [str(tag).strip() for tag in keywords if tag]
        
        # Также можно добавить recipeCuisine
        if recipe_data and 'recipeCuisine' in recipe_data:
            cuisine = recipe_data['recipeCuisine']
            if isinstance(cuisine, list):
                tags.extend([str(c).strip() for c in cuisine if c])
            elif isinstance(cuisine, str):
                tags.append(cuisine.strip())
        
        # Убираем дубликаты
        if tags:
            seen = set()
            unique_tags = []
            for tag in tags:
                tag_lower = tag.lower()
                if tag_lower not in seen:
                    seen.add(tag_lower)
                    unique_tags.append(tag)
            return ', '.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений (до 3 изображений)"""
        urls = []
        recipe_data = self.get_recipe_json_ld()
        
        # Извлекаем из JSON-LD
        if recipe_data and 'image' in recipe_data:
            images = recipe_data['image']
            if isinstance(images, str):
                urls.append(images)
            elif isinstance(images, list):
                urls.extend([img for img in images if isinstance(img, str)])
        
        # Добавляем из мета-тегов если нужно
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
        
        # Убираем дубликаты, берем первые 3
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
                    if len(unique_urls) >= 3:
                        break
            # Note: URLs are joined without space after comma to match expected format
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
            "instructions": self.extract_steps(),
            "nutrition_info": self.extract_nutrition_info(),
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
    # По умолчанию обрабатываем папку preprocessed/cookeatworld_com
    recipes_dir = os.path.join("preprocessed", "cookeatworld_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(CookeatWorldExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python cookeatworld_com.py [путь_к_файлу_или_директории]")


if __name__ == "__main__":
    main()
