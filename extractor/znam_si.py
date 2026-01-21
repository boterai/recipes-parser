"""
Экстрактор данных рецептов для сайта znam.si
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ZnamSiExtractor(BaseRecipeExtractor):
    """Экстрактор для znam.si"""
    
    def _get_recipe_data(self) -> Optional[dict]:
        """
        Извлечение данных рецепта из JSON-LD
        
        Returns:
            dict с данными рецепта или None
        """
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                # Если data содержит @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            return item
                
                # Если Recipe напрямую
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                
                # Если data - это список
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
            
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
        
        # Форматируем результат
        result_parts = []
        if hours > 0:
            result_parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            result_parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(result_parts) if result_parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self._get_recipe_data()
        
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self._get_recipe_data()
        
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "500 g mehke bele moke" или "1 večja čebula"
            
        Returns:
            dict: {"name": "mehka bela moka", "amount": "500", "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "500 g mehke bele moke", "1 večja čebula", "1/2 čajne žličke popra"
        pattern = r'^([\d\s/.,]+)?\s*(g|kg|ml|l|žlica|žlice|žlic|žlička|žličke|žličk|čajna žlička|čajne žličke|čajnih žličk|srednje velika|večja|večji|manjša|manjši)?\s*(.+)'
        
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
            # Обработка дробей типа "1/2"
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
                amount = amount_str.replace(',', '.')
                try:
                    amount = float(amount)
                except:
                    amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым (например "(tip 400)")
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "po želji", "neobvezno"
        name = re.sub(r'\b(po želji|neobvezno|malo)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
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
        recipe_data = self._get_recipe_data()
        
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredients_list = recipe_data['recipeIngredient']
            
            parsed_ingredients = []
            for ingredient in ingredients_list:
                parsed = self.parse_ingredient(ingredient)
                if parsed:
                    parsed_ingredients.append(parsed)
            
            return json.dumps(parsed_ingredients, ensure_ascii=False) if parsed_ingredients else None
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self._get_recipe_data()
        
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        steps.append(f"{idx}. {step['text']}")
                    elif isinstance(step, str):
                        steps.append(f"{idx}. {step}")
            elif isinstance(instructions, str):
                steps.append(instructions)
            
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self._get_recipe_data()
        
        if recipe_data:
            # Пробуем recipeCategory
            if 'recipeCategory' in recipe_data:
                category = recipe_data['recipeCategory']
                if category:
                    # Переводим на английский стандартные категории
                    category_map = {
                        'Glavna jed': 'Main Course',
                        'Predjed': 'Appetizer',
                        'Sladica': 'Dessert',
                        'Juha': 'Soup',
                        'Solata': 'Salad'
                    }
                    return category_map.get(category, category)
            
            # Альтернативно - recipeCuisine
            if 'recipeCuisine' in recipe_data:
                return recipe_data['recipeCuisine']
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_recipe_data()
        
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self._get_recipe_data()
        
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_recipe_data()
        
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями в HTML
        # Обычно они находятся после рецепта или в специальных блоках
        
        # Пробуем найти блоки с классами содержащими "note", "tip", "napotki"
        notes_containers = self.soup.find_all(class_=re.compile(r'note|tip|napotki', re.I))
        
        if notes_containers:
            notes_text = []
            for container in notes_containers:
                text = self.clean_text(container.get_text())
                # Игнорируем очень короткие тексты и социальные кнопки
                if text and len(text) > 20 and 'Facebook' not in text and 'Twitter' not in text:
                    notes_text.append(text)
            
            return ' '.join(notes_text) if notes_text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        recipe_data = self._get_recipe_data()
        
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            # keywords - это строка через запятую
            if keywords:
                # Разбиваем по запятым и очищаем
                tags_list = [self.clean_text(tag) for tag in keywords.split(',') if tag.strip()]
                # Возвращаем как строку через запятую
                return ', '.join(tags_list) if tags_list else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        recipe_data = self._get_recipe_data()
        
        # 1. Из JSON-LD Recipe.image
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict) and 'url' in img:
                urls.append(img['url'])
        
        # 2. Из meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 3. Из JSON-LD @graph ImageObject
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'ImageObject' and 'url' in item:
                            urls.append(item['url'])
            except:
                continue
        
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
    # По умолчанию обрабатываем папку preprocessed/znam_si
    preprocessed_dir = os.path.join("preprocessed", "znam_si")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ZnamSiExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python znam_si.py [путь_к_файлу_или_директории]")


if __name__ == "__main__":
    main()
