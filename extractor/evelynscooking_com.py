"""
Экстрактор данных рецептов для сайта evelynscooking.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class EvelynsCookingExtractor(BaseRecipeExtractor):
    """Экстрактор для evelynscooking.com"""
    
    # Compile regex pattern for ingredient parsing at class level for better performance
    INGREDIENT_PATTERN = re.compile(
        r'^([\d\s/.,]+)?\s*((?:cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads|tube|tubes?)(?:\s*\([^)]+\))?)\s*(.+)',
        re.IGNORECASE
    )
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пытаемся извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в данных
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'name' in data:
                        name = self.clean_text(data['name'])
                        # Убираем суффикс " Recipe"
                        name = re.sub(r'\s+Recipe$', '', name, flags=re.IGNORECASE)
                        return name
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " Recipe"
            title = re.sub(r'\s+(Recipe|-).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Попытка из H1
        h1 = self.soup.find('h1')
        if h1:
            name = self.clean_text(h1.get_text())
            name = re.sub(r'\s+Recipe$', '', name, flags=re.IGNORECASE)
            return name
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пытаемся извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в данных
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'description' in data:
                        desc = self.clean_text(data['description'])
                        # Берем только первое предложение
                        first_sentence = desc.split('.')[0] + '.'
                        return first_sentence
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            first_sentence = desc.split('.')[0] + '.'
            return first_sentence
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = self.clean_text(og_desc['content'])
            first_sentence = desc.split('.')[0] + '.'
            return first_sentence
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пытаемся извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в данных
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'recipeIngredient' in data:
                        recipe_ingredients = data['recipeIngredient']
                        if isinstance(recipe_ingredients, list):
                            for ing_text in recipe_ingredients:
                                parsed = self.parse_ingredient(ing_text)
                                if parsed:
                                    ingredients.append(parsed)
                            
                            if ingredients:
                                return json.dumps(ingredients, ensure_ascii=False)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, пытаемся найти в HTML
        # Ищем список ингредиентов
        ingredient_containers = [
            self.soup.find('ul', class_=re.compile(r'ingredient', re.I)),
            self.soup.find('div', class_=re.compile(r'ingredient', re.I))
        ]
        
        for container in ingredient_containers:
            if not container:
                continue
                
            items = container.find_all('li')
            if not items:
                items = container.find_all('p')
            
            for item in items:
                ingredient_text = item.get_text(separator=' ', strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                if ingredient_text and not ingredient_text.endswith(':'):
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
            
            if ingredients:
                break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
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
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Use pre-compiled regex pattern
        match = self.INGREDIENT_PATTERN.match(text)
        
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
                try:
                    amount = float(amount_str.replace(',', '.'))
                except ValueError:
                    amount = amount_str
        
        # Обработка единицы измерения (уже включает скобки если они есть)
        units = units.strip() if units else None
        
        # Очистка названия
        # Не удаляем скобки из названия, так как они должны быть в units
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish)\b', '', name, flags=re.IGNORECASE)
        # Удаляем запятые и следующий текст (например, ", crumbled")
        name = re.sub(r',.*$', '', name)
        # Удаляем лишние пробелы
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
        steps = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в данных
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'recipeInstructions' in data:
                        instructions = data['recipeInstructions']
                        if isinstance(instructions, list):
                            for idx, step in enumerate(instructions, 1):
                                if isinstance(step, dict) and 'text' in step:
                                    steps.append(f"{idx}. {step['text']}")
                                elif isinstance(step, str):
                                    steps.append(f"{idx}. {step}")
                        
                        if steps:
                            return ' '.join(steps)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, ищем в HTML
        instructions_containers = [
            self.soup.find('ol', class_=re.compile(r'instruction', re.I)),
            self.soup.find('div', class_=re.compile(r'instruction', re.I))
        ]
        
        for container in instructions_containers:
            if not container:
                continue
            
            step_items = container.find_all('li')
            if not step_items:
                step_items = container.find_all('p')
            
            for item in step_items:
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    steps.append(step_text)
            
            if steps:
                break
        
        # Если нумерация не была в HTML, добавляем её
        if steps and not re.match(r'^\d+\.', steps[0]):
            steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пытаемся извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в данных
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'recipeCategory' in data:
                        return self.clean_text(data['recipeCategory'])
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Сначала пытаемся извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в данных
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'prepTime' in data:
                        iso_time = data['prepTime']
                        return self.parse_iso_duration(iso_time)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Сначала пытаемся извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в данных
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'cookTime' in data:
                        iso_time = data['cookTime']
                        return self.parse_iso_duration(iso_time)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Сначала пытаемся извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в данных
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'totalTime' in data:
                        iso_time = data['totalTime']
                        return self.parse_iso_duration(iso_time)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в читаемом формате, например "20 minutes" или "1 hour 30 minutes"
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
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию notes в tasty-recipes
        notes_body = self.soup.find(class_='tasty-recipes-notes-body')
        if notes_body:
            # Извлекаем все элементы списка
            items = notes_body.find_all('li')
            if items:
                notes_list = [self.clean_text(item.get_text()) for item in items]
                return ' '.join(notes_list)
        
        # Альтернативно - ищем в HTML секцию с примечаниями
        notes_patterns = [
            re.compile(r'notes?', re.I),
            re.compile(r'tips?', re.I),
            re.compile(r'suggestions?', re.I)
        ]
        
        for pattern in notes_patterns:
            notes_section = self.soup.find(class_=pattern)
            
            if notes_section:
                # Удаляем заголовок "Notes"
                for h_tag in notes_section.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                    h_tag.decompose()
                
                text = notes_section.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Сначала пытаемся извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в данных
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'keywords' in data:
                        keywords = data['keywords']
                        if isinstance(keywords, str):
                            return keywords
                        elif isinstance(keywords, list):
                            return ', '.join(keywords)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Сначала пытаемся извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в данных
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'image' in data:
                        img = data['image']
                        if isinstance(img, str):
                            urls.append(img)
                        elif isinstance(img, list):
                            # Берем только уникальные URL
                            for url in img:
                                if isinstance(url, str) and url not in urls:
                                    urls.append(url)
                        elif isinstance(img, dict):
                            if 'url' in img and img['url'] not in urls:
                                urls.append(img['url'])
                            elif 'contentUrl' in img and img['contentUrl'] not in urls:
                                urls.append(img['contentUrl'])
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если есть URL, берем только оригинальное изображение (последнее в списке обычно самое большое)
        if urls:
            # Берем последнее изображение, которое обычно самое большое разрешение
            return urls[-1] if urls else None
        
        # Альтернативно - из meta тегов
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            return og_image['content']
        
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
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
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
    # По умолчанию обрабатываем папку preprocessed/evelynscooking_com
    recipes_dir = os.path.join("preprocessed", "evelynscooking_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(EvelynsCookingExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python evelynscooking_com.py [путь_к_файлу_или_директории]")


if __name__ == "__main__":
    main()
