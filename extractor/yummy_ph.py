"""
Экстрактор данных рецептов для сайта yummy.ph
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class YummyPhExtractor(BaseRecipeExtractor):
    """Экстрактор для yummy.ph"""
    
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
        
        # Форматируем в читаемый вид
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
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
                        if is_recipe(item):
                            return item
                elif isinstance(data, dict):
                    if is_recipe(data):
                        return data
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if is_recipe(item):
                                return item
                                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Пробуем из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld and 'name' in json_ld:
            name = json_ld['name']
            # Убираем суффикс " Recipe" если есть
            name = re.sub(r'\s+Recipe$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        # Ищем в HTML
        title_elem = self.soup.find('h1', class_='wprm-recipe-title')
        if title_elem:
            return self.clean_text(title_elem.get_text())
        
        # Из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            name = og_title['content']
            name = re.sub(r'\s+Recipe.*$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Пробуем из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Пробуем из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
        # Ищем в HTML блок с описанием
        desc_elem = self.soup.find('div', class_='wprm-recipe-summary')
        if desc_elem:
            return self.clean_text(desc_elem.get_text())
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из структурированного HTML"""
        ingredients = []
        
        # Ищем контейнер с ингредиентами
        ingredients_container = self.soup.find('div', class_='wprm-recipe-ingredients-container')
        
        if ingredients_container:
            # Находим все элементы ингредиентов
            ingredient_items = ingredients_container.find_all('li', class_='wprm-recipe-ingredient')
            
            for item in ingredient_items:
                # Извлекаем структурированные данные
                amount_elem = item.find('span', class_='wprm-recipe-ingredient-amount')
                unit_elem = item.find('span', class_='wprm-recipe-ingredient-unit')
                name_elem = item.find('span', class_='wprm-recipe-ingredient-name')
                notes_elem = item.find('span', class_='wprm-recipe-ingredient-notes')
                
                # Собираем данные
                amount = self.clean_text(amount_elem.get_text()) if amount_elem else None
                unit = self.clean_text(unit_elem.get_text()) if unit_elem else None
                name = self.clean_text(name_elem.get_text()) if name_elem else None
                notes = self.clean_text(notes_elem.get_text()) if notes_elem else None
                
                # Если есть notes но нет unit, notes становится unit (например "to taste", "for garnish")
                if notes and not unit:
                    unit = notes
                
                # Добавляем ингредиент
                if name:
                    ingredient_dict = {
                        "name": name,
                        "units": unit,
                        "amount": amount
                    }
                    ingredients.append(ingredient_dict)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions = []
        
        # Пробуем из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld and 'recipeInstructions' in json_ld:
            recipe_instructions = json_ld['recipeInstructions']
            if isinstance(recipe_instructions, list):
                for step in recipe_instructions:
                    if isinstance(step, dict) and 'text' in step:
                        instructions.append(self.clean_text(step['text']))
                    elif isinstance(step, str):
                        instructions.append(self.clean_text(step))
        
        # Если не нашли в JSON-LD, ищем в HTML
        if not instructions:
            instructions_container = self.soup.find('div', class_='wprm-recipe-instructions-container')
            
            if instructions_container:
                instruction_items = instructions_container.find_all('li', class_='wprm-recipe-instruction')
                
                for item in instruction_items:
                    text_elem = item.find('div', class_='wprm-recipe-instruction-text')
                    if text_elem:
                        text = self.clean_text(text_elem.get_text())
                        if text:
                            instructions.append(text)
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        categories = []
        
        # Пробуем из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld:
            # recipeCategory
            if 'recipeCategory' in json_ld:
                recipe_category = json_ld['recipeCategory']
                if isinstance(recipe_category, list):
                    categories.extend(recipe_category)
                elif isinstance(recipe_category, str):
                    categories.append(recipe_category)
        
        return ', '.join(categories) if categories else None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Пробуем из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        # Ищем в HTML
        prep_time_elem = self.soup.find('span', class_='wprm-recipe-prep_time')
        if prep_time_elem:
            minutes = self.clean_text(prep_time_elem.get_text())
            if minutes:
                return f"{minutes} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Пробуем из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        # Ищем в HTML
        cook_time_elem = self.soup.find('span', class_='wprm-recipe-cook_time')
        if cook_time_elem:
            minutes = self.clean_text(cook_time_elem.get_text())
            if minutes:
                return f"{minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Пробуем из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        # Ищем в HTML
        total_time_elem = self.soup.find('span', class_='wprm-recipe-total_time')
        if total_time_elem:
            minutes = self.clean_text(total_time_elem.get_text())
            if minutes:
                return f"{minutes} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем блок с заметками
        notes_elem = self.soup.find('div', class_='wprm-recipe-notes')
        if notes_elem:
            text = self.clean_text(notes_elem.get_text())
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Пробуем из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld:
            # recipeCuisine
            if 'recipeCuisine' in json_ld:
                cuisine = json_ld['recipeCuisine']
                if isinstance(cuisine, list):
                    tags.extend(cuisine)
                elif isinstance(cuisine, str):
                    tags.append(cuisine)
            
            # keywords
            if 'keywords' in json_ld:
                keywords = json_ld['keywords']
                if isinstance(keywords, str):
                    # Разбиваем по запятой
                    keywords_list = [k.strip() for k in keywords.split(',') if k.strip()]
                    tags.extend(keywords_list)
                elif isinstance(keywords, list):
                    tags.extend(keywords)
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags:
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen.add(tag_lower)
                unique_tags.append(tag_lower)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Пробуем из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld and 'image' in json_ld:
            images = json_ld['image']
            if isinstance(images, str):
                urls.append(images)
            elif isinstance(images, list):
                urls.extend([img for img in images if isinstance(img, str)])
            elif isinstance(images, dict):
                if 'url' in images:
                    urls.append(images['url'])
                elif '@id' in images:
                    urls.append(images['@id'])
        
        # Если не нашли в JSON-LD, ищем в meta тегах
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
    """Точка входа для тестирования"""
    import os
    
    # Обрабатываем папку preprocessed/yummy_ph
    preprocessed_dir = os.path.join("preprocessed", "yummy_ph")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(YummyPhExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python yummy_ph.py")


if __name__ == "__main__":
    main()
