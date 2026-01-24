"""
Экстрактор данных рецептов для сайта sallysbakingaddiction.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class SallysBakingAddictionExtractor(BaseRecipeExtractor):
    """Экстрактор для sallysbakingaddiction.com"""
    
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
            if hours == 1:
                parts.append("1 hour")
            else:
                parts.append(f"{hours} hours")
        
        if minutes > 0:
            if minutes == 1:
                parts.append("1 minute")
            else:
                parts.append(f"{minutes} minutes")
        
        return " ".join(parts) if parts else None
    
    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение Recipe данных из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Функция для проверки типа Recipe
                def is_recipe(item):
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        return 'Recipe' in item_type
                    return item_type == 'Recipe'
                
                # Ищем Recipe в данных
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and is_recipe(item):
                            return item
                elif isinstance(data, dict):
                    if is_recipe(data):
                        return data
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and is_recipe(item):
                                return item
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из заголовка страницы
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "2 cups (250g) all-purpose flour" 
            
        Returns:
            dict: {"name": "all-purpose flour", "amount": "2", "unit": "cups"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Нормализуем пробелы (включая non-breaking spaces)
        text = text.replace('\xa0', ' ').replace('\u00a0', ' ')
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Удаляем содержимое скобок (обычно граммы или примечания)
        text_without_parens = re.sub(r'\([^)]*\)', '', text).strip()
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "2 cups flour", "1/2 teaspoon salt", "1 and 1/2 cups sugar", "1 large egg"
        # Стандартные единицы измерения (без large/medium/small, чтобы они остались в названии)
        # Для g, kg, ml, l требуем точное совпадение границ слова или в конце строки
        # Улучшенная обработка "X and Y/Z" формата
        pattern = r'^((?:[\d\s/.,]+\s+and\s+)?[\d\s/.,]+)\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|tablespoon|teaspoon|pounds?|ounces?|lbs?|oz|grams?|kilograms?|milliliters?|liters?|kg\b|ml\b|g\b|l\b|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads)?\s*(.+)'
        
        match = re.match(pattern, text_without_parens, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text_without_parens,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка "and" (например, "1 and 1/2")
            if ' and ' in amount_str:
                parts = amount_str.split(' and ')
                total = 0
                for part in parts:
                    part = part.strip()
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                amount = total
            # Обработка дробей типа "1/2" или "1 1/2"
            elif '/' in amount_str:
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
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем фразы "to taste", "as needed", "optional" и т.д.
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|plus more for.*|divided|frozen)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые в конце
        name = re.sub(r'\s*[,;]+\s*$', '', name)
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
        ingredients = []
        
        # Сначала пробуем из JSON-LD (самый надежный способ)
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'recipeIngredient' in recipe_data:
            recipe_ingredients = recipe_data['recipeIngredient']
            if isinstance(recipe_ingredients, list):
                for ing_text in recipe_ingredients:
                    parsed = self.parse_ingredient(ing_text)
                    if parsed:
                        ingredients.append(parsed)
                
                if ingredients:
                    return json.dumps(ingredients, ensure_ascii=False)
        
        # Если JSON-LD не помог, ищем в HTML
        # Ищем класс tasty-recipes или другие варианты
        ingredient_containers = [
            self.soup.find('div', class_=re.compile(r'tasty-recipes-ingredients', re.I)),
            self.soup.find('ul', class_=re.compile(r'ingredient.*list', re.I)),
            self.soup.find('div', class_=re.compile(r'ingredient', re.I))
        ]
        
        for container in ingredient_containers:
            if not container:
                continue
                
            # Извлекаем элементы списка
            items = container.find_all('li')
            if not items:
                items = container.find_all('p')
            
            for item in items:
                # Извлекаем текст ингредиента
                ingredient_text = item.get_text(separator=' ', strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                # Пропускаем заголовки секций
                if ingredient_text and not ingredient_text.endswith(':'):
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
            
            if ingredients:
                break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict):
                        if 'text' in step:
                            steps.append(step['text'])
                        elif 'itemListElement' in step:
                            # Nested structure
                            for sub_step in step['itemListElement']:
                                if isinstance(sub_step, dict) and 'text' in sub_step:
                                    steps.append(sub_step['text'])
                    elif isinstance(step, str):
                        steps.append(step)
                
                if steps:
                    # Добавляем нумерацию если её нет
                    if steps and not re.match(r'^\d+\.', steps[0]):
                        steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
                    return ' '.join(steps)
        
        # Если JSON-LD не помог, ищем в HTML
        instructions_containers = [
            self.soup.find('div', class_=re.compile(r'tasty-recipes-instructions', re.I)),
            self.soup.find('ol', class_=re.compile(r'instruction.*list', re.I)),
            self.soup.find('div', class_=re.compile(r'instruction', re.I))
        ]
        
        for container in instructions_containers:
            if not container:
                continue
            
            # Извлекаем шаги
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
        
        # Добавляем нумерацию если её нет
        if steps and not re.match(r'^\d+\.', steps[0]):
            steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            if isinstance(category, list):
                return ', '.join(category)
            return self.clean_text(category)
        
        # Из метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем в HTML структуре
        notes_containers = [
            self.soup.find('div', class_=re.compile(r'tasty-recipes-notes', re.I)),
            self.soup.find('div', class_=re.compile(r'recipe-notes', re.I)),
            self.soup.find('section', class_=re.compile(r'notes', re.I))
        ]
        
        for container in notes_containers:
            if container:
                # Убираем заголовок "Notes:" если есть
                text = container.get_text(separator=' ', strip=True)
                text = re.sub(r"^Notes?\s*:?\s*", '', text, flags=re.I)
                text = self.clean_text(text)
                return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            elif isinstance(keywords, list):
                tags_list = keywords
        
        # Из meta keywords
        if not tags_list:
            meta_keywords = self.soup.find('meta', {'name': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                tags_list = [tag.strip() for tag in meta_keywords['content'].split(',') if tag.strip()]
        
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'image' in recipe_data:
            images = recipe_data['image']
            if isinstance(images, str):
                urls.append(images)
            elif isinstance(images, list):
                for img in images:
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, dict):
                        if 'url' in img:
                            urls.append(img['url'])
                        elif 'contentUrl' in img:
                            urls.append(img['contentUrl'])
        
        # Из meta og:image
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
        
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
    # Обрабатываем папку preprocessed/sallysbakingaddiction_com
    preprocessed_dir = os.path.join("preprocessed", "sallysbakingaddiction_com")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(SallysBakingAddictionExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")


if __name__ == "__main__":
    main()
