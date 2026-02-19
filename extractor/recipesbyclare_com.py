"""
Экстрактор данных рецептов для сайта recipesbyclare.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class RecipesbyclareComExtractor(BaseRecipeExtractor):
    """Экстрактор для recipesbyclare.com"""
    
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
        
        # Конвертируем минуты в часы если >= 60
        if minutes >= 60:
            hours += minutes // 60
            minutes = minutes % 60
        
        # Форматируем результат
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Может быть список объектов
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            if 'name' in item:
                                return self.clean_text(item['name'])
                # Или просто объект
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'name' in data:
                        return self.clean_text(data['name'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из HTML
        recipe_title = self.soup.find('h2', class_='recipe__title')
        if recipe_title:
            return self.clean_text(recipe_title.get_text())
        
        landing_title = self.soup.find('h1', class_='landing__title')
        if landing_title:
            return self.clean_text(landing_title.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            if 'description' in item:
                                return self.clean_text(item['description'])
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'description' in data:
                        return self.clean_text(data['description'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из HTML
        tldr = self.soup.find('div', class_='landing__tldr')
        if tldr:
            return self.clean_text(tldr.get_text())
        
        return None
    
    def parse_ingredient_text(self, ingredient_text: str) -> dict:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour." или "2 large eggs."
            
        Returns:
            dict: {"name": "flour", "amount": "1", "unit": "cup"}
        """
        if not ingredient_text:
            return {"name": None, "units": None, "amount": None}
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        # Убираем точку в конце
        text = text.rstrip('.')
        
        # Заменяем Unicode дроби на дроби
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5'
        }
        
        for fraction, text_fraction in fraction_map.items():
            text = text.replace(fraction, text_fraction)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1 cup flour", "2 tablespoons butter", "1/2 teaspoon salt", "1 large egg"
        pattern = r'^([\d\s/.,]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads|units?|drops?)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "units": None,
                "amount": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            
            # Обработка смешанных дробей типа "1 1/2" (целое + дробь)
            if ' ' in amount_str and '/' in amount_str:
                parts = amount_str.split()
                total = 0.0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                amount = total
            # Если это простая дробь (содержит /), оставляем как строку
            elif '/' in amount_str:
                amount = amount_str
            else:
                # Пытаемся преобразовать в число
                try:
                    # Сначала пробуем как целое
                    if '.' not in amount_str and ',' not in amount_str:
                        amount = int(amount_str)
                    else:
                        # Иначе как float
                        amount = float(amount_str.replace(',', '.'))
                except ValueError:
                    # Если не получилось, оставляем как строку
                    amount = amount_str
        
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
        
        if not name or len(name) < 2:
            return {"name": ingredient_text, "units": None, "amount": None}
        
        return {
            "name": name,
            "units": unit,
            "amount": amount
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем из JSON-LD (приоритет, т.к. там структура чище)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            recipe_data = item
                            break
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    recipe_data = data
                
                if recipe_data and 'recipeIngredient' in recipe_data:
                    ingredient_list = recipe_data['recipeIngredient']
                    for ing_text in ingredient_list:
                        parsed = self.parse_ingredient_text(ing_text)
                        if parsed:
                            ingredients.append(parsed)
                    
                    if ingredients:
                        return json.dumps(ingredients, ensure_ascii=False)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, ищем в HTML
        ingredients_container = self.soup.find('div', id='recipe-ingredients')
        if ingredients_container:
            # Ищем все элементы с содержимым ингредиентов
            ingredient_contents = ingredients_container.find_all('span', class_='recipe__interact-list-content')
            
            for content in ingredient_contents:
                ing_text = content.get_text(strip=True)
                parsed = self.parse_ingredient_text(ing_text)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            recipe_data = item
                            break
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    recipe_data = data
                
                if recipe_data and 'recipeInstructions' in recipe_data:
                    instructions = recipe_data['recipeInstructions']
                    if isinstance(instructions, list):
                        for idx, step in enumerate(instructions, 1):
                            if isinstance(step, dict):
                                # Формат: "Step 01: текст"
                                step_num = f"Step {idx:02d}"
                                step_text = step.get('text', '')
                                if step_text:
                                    steps.append(f"{step_num}: {step_text}")
                            elif isinstance(step, str):
                                steps.append(f"Step {idx:02d}: {step}")
                    
                    if steps:
                        return ' '.join(steps)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, ищем в HTML
        instructions_container = self.soup.find('div', id='recipe-instructions')
        if instructions_container:
            # Ищем все шаги
            instruction_divs = instructions_container.find_all('div', id=re.compile(r'^instruction-\d+$'))
            
            for inst_div in instruction_divs:
                # Номер шага
                num_span = inst_div.find('span', class_='recipe__interact-list-number')
                # Текст шага
                content_p = inst_div.find('p', class_='recipe__interact-list-content')
                
                if num_span and content_p:
                    step_num = self.clean_text(num_span.get_text())
                    step_text = self.clean_text(content_p.get_text())
                    steps.append(f"{step_num}: {step_text}")
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            recipe_data = item
                            break
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    recipe_data = data
                
                if recipe_data and 'recipeCategory' in recipe_data:
                    return self.clean_text(recipe_data['recipeCategory'])
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            recipe_data = item
                            break
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    recipe_data = data
                
                if recipe_data and 'prepTime' in recipe_data:
                    return self.parse_iso_duration(recipe_data['prepTime'])
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            recipe_data = item
                            break
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    recipe_data = data
                
                if recipe_data and 'cookTime' in recipe_data:
                    return self.parse_iso_duration(recipe_data['cookTime'])
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            recipe_data = item
                            break
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    recipe_data = data
                
                if recipe_data and 'totalTime' in recipe_data:
                    return self.parse_iso_duration(recipe_data['totalTime'])
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями
        notes_section = self.soup.find('ol', id='recipe-notes')
        
        if notes_section:
            notes = []
            for li in notes_section.find_all('li'):
                note_text = self.clean_text(li.get_text())
                if note_text:
                    notes.append(note_text)
            
            return ' '.join(notes) if notes else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            recipe_data = item
                            break
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    recipe_data = data
                
                if recipe_data and 'keywords' in recipe_data:
                    keywords = recipe_data['keywords']
                    # Если это строка с запятыми, оставляем как есть
                    if isinstance(keywords, str):
                        # Нормализуем: lowercase и убираем лишние пробелы
                        tags = [tag.strip().lower() for tag in keywords.split(',')]
                        return ', '.join(tags)
                    # Если это список
                    elif isinstance(keywords, list):
                        tags = [str(tag).strip().lower() for tag in keywords]
                        return ', '.join(tags)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            recipe_data = item
                            break
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    recipe_data = data
                
                if recipe_data and 'image' in recipe_data:
                    img = recipe_data['image']
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, list):
                        # Берем оригинальное изображение (первое в списке)
                        if img:
                            urls.append(img[0])
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Убираем дубликаты
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
    import os
    # Обрабатываем папку preprocessed/recipesbyclare_com
    preprocessed_dir = os.path.join("preprocessed", "recipesbyclare_com")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(RecipesbyclareComExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python recipesbyclare_com.py")


if __name__ == "__main__":
    main()
