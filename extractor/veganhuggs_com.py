"""
Экстрактор данных рецептов для сайта veganhuggs.com
"""

import sys
import os
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class VeganhuggsExtractor(BaseRecipeExtractor):
    """Экстрактор для veganhuggs.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str, total_time: bool = False) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT260M"
            total_time: если True, используем формат с hours для больших значений
            
        Returns:
            Время в читаемом формате, например "90 minutes" или "4 hours 20 minutes"
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
        
        # Для total_time, если минут больше 60, конвертируем в часы
        if total_time and hours == 0 and minutes >= 60:
            hours = minutes // 60
            minutes = minutes % 60
        
        # Формируем строку
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour" + ("s" if hours > 1 else ""))
        if minutes > 0:
            parts.append(f"{minutes} minute" + ("s" if minutes > 1 else ""))
        
        return " ".join(parts) if parts else None
    
    def get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение Recipe данных из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем есть ли @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            return item
                
                # Если Recipe напрямую
                elif data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            name = self.clean_text(recipe_data['name'])
            # Убираем суффиксы типа " Recipe"
            name = re.sub(r'\s+Recipe\s*$', '', name, flags=re.IGNORECASE)
            # Убираем текст в скобках в конце
            name = re.sub(r'\s*\([^)]*\)\s*$', '', name)
            return name
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        recipe_data = self.get_recipe_json_ld()
        
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredients = []
        for ingredient_text in recipe_data['recipeIngredient']:
            parsed = self.parse_ingredient(ingredient_text)
            if parsed:
                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour" или "2 pounds chicken"
            
        Returns:
            dict: {"name": "flour", "amount": "1", "units": "cup"} или None
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
        # Список единиц измерения
        units_list = [
            'cups?', 'tablespoons?', 'teaspoons?', 'tbsps?', 'tsps?',
            'pounds?', 'ounces?', 'lbs?', 'oz',
            'grams?', 'kilograms?', 'g', 'kg',
            'milliliters?', 'liters?', 'ml', 'l',
            'pinch(?:es)?', 'dash(?:es)?',
            'packages?', 'cans?', 'jars?', 'bottles?',
            'inch(?:es)?', 'slices?', 'cloves?', 'bunches?', 'sprigs?',
            'whole', 'halves?', 'quarters?', 'pieces?', 'head', 'heads',
            'small', 'medium', 'large'
        ]
        units_pattern = '|'.join(units_list)
        pattern = rf'^([\d\s/.,+-]+)?\s*({units_pattern})?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, units, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2" или "1 1/2" или диапазонов "1-2"
            if '/' in amount_str or '-' in amount_str:
                # Если есть диапазон (1-2), берем просто как есть
                if '-' in amount_str and '/' not in amount_str:
                    amount = amount_str
                # Если есть дробь с возможным диапазоном, пробуем разобрать
                elif '/' in amount_str:
                    try:
                        parts = amount_str.split()
                        total = 0
                        for part in parts:
                            # Пропускаем части с диапазонами после дробей (например, "1/2-")
                            if part.endswith('-'):
                                part = part[:-1]
                            
                            if '/' in part:
                                frac_parts = part.split('/')
                                if len(frac_parts) == 2:
                                    num = frac_parts[0].strip()
                                    denom = frac_parts[1].strip()
                                    # Проверяем, что можем конвертировать в число
                                    try:
                                        total += float(num) / float(denom)
                                    except (ValueError, ZeroDivisionError):
                                        pass
                            else:
                                try:
                                    total += float(part)
                                except ValueError:
                                    pass
                        amount = str(total) if total > 0 else amount_str
                    except (ValueError, ZeroDivisionError):
                        # Если не получилось распарсить, оставляем как есть
                        amount = amount_str
                else:
                    amount = amount_str
            else:
                amount = amount_str.replace(',', '.')
        
        # Обработка единицы измерения
        units = units.strip() if units else None
        
        # Очистка названия - убираем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем лишние скобки, запятые и символы в начале
        name = re.sub(r'^[\s,\(\)]+', '', name)
        name = re.sub(r'[\s,\(\)]+$', '', name)
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|plus more)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self.get_recipe_json_ld()
        
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        steps = []
        
        if isinstance(instructions, list):
            for idx, step in enumerate(instructions, 1):
                if isinstance(step, dict) and 'text' in step:
                    step_text = self.clean_text(step['text'])
                    steps.append(f"{idx}. {step_text}")
                elif isinstance(step, str):
                    step_text = self.clean_text(step)
                    steps.append(f"{idx}. {step_text}")
        elif isinstance(instructions, str):
            steps.append(self.clean_text(instructions))
        
        return ' '.join(steps) if steps else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        recipe_data = self.get_recipe_json_ld()
        
        if not recipe_data or 'nutrition' not in recipe_data:
            return None
        
        nutrition = recipe_data['nutrition']
        
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
        
        # Формат для полной информации (для справки, может быть полезно)
        full_nutrition_parts = []
        if calories:
            full_nutrition_parts.append(f"Calories: {calories} kcal")
        if carbs:
            full_nutrition_parts.append(f"Carbohydrates: {carbs} g")
        if protein:
            full_nutrition_parts.append(f"Protein: {protein} g")
        if fat:
            full_nutrition_parts.append(f"Fat: {fat} g")
        
        # Добавляем дополнительные поля если есть
        optional_fields = {
            'saturatedFatContent': 'Saturated Fat',
            'sodiumContent': 'Sodium',
            'fiberContent': 'Fiber',
            'sugarContent': 'Sugar',
            'potassiumContent': 'Potassium',
            'vitaminAContent': 'Vitamin A',
            'vitaminCContent': 'Vitamin C',
            'calciumContent': 'Calcium',
            'ironContent': 'Iron'
        }
        
        for field, label in optional_fields.items():
            if field in nutrition:
                value = nutrition[field]
                # Извлекаем значение
                match = re.search(r'([\d.]+)\s*(\w+)?', str(value))
                if match:
                    num = match.group(1)
                    unit = match.group(2) if match.group(2) else ''
                    if unit:
                        full_nutrition_parts.append(f"{label}: {num} {unit}")
                    else:
                        full_nutrition_parts.append(f"{label}: {num}")
        
        return ', '.join(full_nutrition_parts) if full_nutrition_parts else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self.get_recipe_json_ld()
        
        if not recipe_data:
            return None
        
        categories = []
        
        # Проверяем recipeCategory
        if 'recipeCategory' in recipe_data:
            cat = recipe_data['recipeCategory']
            if isinstance(cat, list):
                categories.extend([self.clean_text(c) for c in cat])
            elif isinstance(cat, str):
                categories.append(self.clean_text(cat))
        
        # Проверяем recipeCuisine
        if 'recipeCuisine' in recipe_data:
            cuisine = recipe_data['recipeCuisine']
            if isinstance(cuisine, list):
                categories.extend([self.clean_text(c) for c in cuisine])
            elif isinstance(cuisine, str):
                categories.append(self.clean_text(cuisine))
        
        return ', '.join(categories) if categories else None
    
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
            return self.parse_iso_duration(recipe_data['totalTime'], total_time=True)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем в основном контенте страницы (entry-content)
        # Это где находятся важные заметки о рецепте
        entry_content = self.soup.find(class_='entry-content')
        if entry_content:
            # Ищем ul/li элементы с полезными советами
            for ul in entry_content.find_all('ul'):
                # Пропускаем списки внутри recipe card
                if ul.find_parent(class_=re.compile(r'wprm-recipe')):
                    continue
                
                # Проверяем первый элемент списка
                first_li = ul.find('li')
                if not first_li:
                    continue
                
                first_text = self.clean_text(first_li.get_text())
                
                # Пропускаем списки ингредиентов и инструкций по характерным признакам
                if not first_text:
                    continue
                
                # Пропускаем если начинается с цифры и тире (это инструкции)
                if re.match(r'^\d+[\s-]', first_text):
                    continue
                
                # Пропускаем навигационные элементы и меню
                if any(word in first_text.lower() for word in ['with a big bowl of', 'jump to', 'recipe', 'print']):
                    continue
                
                # Это должен быть список с советами, если содержит ключевые слова
                has_tip_keywords = any(keyword in first_text.lower() for keyword in 
                                      ['make sure', 'use', 'let', 'you can', 'should', 'best', 'store', 'freeze'])
                
                if has_tip_keywords:
                    # Собираем все элементы этого списка
                    for li in ul.find_all('li', recursive=False):
                        text = self.clean_text(li.get_text())
                        if text and len(text) < 500:  # Разумная длина для заметки
                            notes.append(text)
                    
                    # Если нашли подходящий список, выходим
                    if notes:
                        break
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        recipe_data = self.get_recipe_json_ld()
        
        if not recipe_data:
            return None
        
        # Проверяем поле keywords
        if 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Разделяем по запятой и очищаем
                tags = [self.clean_text(tag.strip()) for tag in keywords.split(',') if tag.strip()]
                return ', '.join(tags) if tags else None
            elif isinstance(keywords, list):
                tags = [self.clean_text(tag) for tag in keywords if tag]
                return ', '.join(tags) if tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        recipe_data = self.get_recipe_json_ld()
        
        if not recipe_data or 'image' not in recipe_data:
            return None
        
        urls = []
        img = recipe_data['image']
        
        if isinstance(img, str):
            urls.append(img)
        elif isinstance(img, list):
            for item in img:
                if isinstance(item, str):
                    urls.append(item)
                elif isinstance(item, dict):
                    if 'url' in item:
                        urls.append(item['url'])
                    elif 'contentUrl' in item:
                        urls.append(item['contentUrl'])
        elif isinstance(img, dict):
            if 'url' in img:
                urls.append(img['url'])
            elif 'contentUrl' in img:
                urls.append(img['contentUrl'])
        
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
    # Обрабатываем папку preprocessed/veganhuggs_com
    preprocessed_dir = os.path.join("preprocessed", "veganhuggs_com")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(VeganhuggsExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python veganhuggs_com.py")


if __name__ == "__main__":
    main()
