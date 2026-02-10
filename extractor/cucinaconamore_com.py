"""
Экстрактор данных рецептов для сайта cucinaconamore.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CucinaConAmoreExtractor(BaseRecipeExtractor):
    """Экстрактор для cucinaconamore.com"""
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение JSON-LD данных рецепта"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Если data - это список, обрабатываем каждый элемент
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                # Если data - это объект Recipe
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "20 minutes" или "90 minutes"
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
        
        # Конвертируем все в минуты
        total_minutes = hours * 60 + minutes
        
        return f"{total_minutes} minutes" if total_minutes > 0 else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Извлекаем из meta тега og:title (самый надежный источник для cucinaconamore.com)
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффикс с названием сайта
            title = re.sub(r'\s*-\s*Cucina Con Amore.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*-\s*classico cibo confortante.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Альтернативно - из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            title = re.sub(r'\s*-\s*Cucina Con Amore.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*-\s*classico cibo confortante.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient_text(self, ingredient_text: str) -> Optional[Dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        Примеры: "450g di carne macinata di manzo", "1 cipolla piccola, tritata finemente"
        
        Args:
            ingredient_text: Строка ингредиента
            
        Returns:
            dict: {"name": "...", "amount": ..., "units": "..."}
        """
        if not ingredient_text:
            return None
        
        text = self.clean_text(ingredient_text)
        
        # Удаляем содержимое в скобках для упрощения парсинга
        # Примечание: скобки обычно содержат дополнительные детали приготовления
        # (например, "(per spennellare)" = "для смазывания"), которые не являются
        # частью основного названия ингредиента
        text = re.sub(r'\([^)]*\)', '', text).strip()
        
        # Известные единицы измерения (короткие - г, мл и т.д.)
        metric_units = {
            'g', 'kg', 'ml', 'l', 'cl', 'dl', 'oz', 'lb'
        }
        
        # Единицы измерения (слова - чашка, ложка и т.д.)
        word_units = {
            'tazza', 'tazze', 'cucchiaio', 'cucchiai', 'cucchiaino', 'cucchiaini',
            'cup', 'cups', 'tbsp', 'tsp', 'tablespoon', 'teaspoon',
            'pound', 'pounds', 'ounce', 'ounces',
            'chilo', 'pezzo', 'pezzi'
        }
        
        all_units = metric_units | word_units
        
        # Паттерн для извлечения количества и единицы измерения
        # Примеры: "450g di carne", "120ml di latte", "1 cipolla"
        pattern_with_unit = r'^([\d/.,]+)\s*([a-zA-Z]+)\s+(?:di\s+)?(.+)'
        pattern_count = r'^([\d/.,]+)\s+(.+?)(?:,.*)?$'  # Убираем запятые и все после
        
        match = re.match(pattern_with_unit, text, re.IGNORECASE)
        
        amount = None
        unit = None
        name = text
        # Флаг для определения, нужно ли возвращать количество как число (True) или как строку (False)
        use_numeric_amount = False
        
        if match:
            amount_str, potential_unit, potential_name = match.groups()
            
            # Проверяем, является ли potential_unit настоящей единицей измерения
            if potential_unit.lower() in all_units:
                # Это настоящая единица измерения
                unit = potential_unit
                # Убираем запятые и все после них из названия
                name = re.sub(r',.*$', '', potential_name).strip()
                use_numeric_amount = potential_unit.lower() in metric_units
            else:
                # Это не единица измерения, а часть названия
                # Используем паттерн для подсчета
                match2 = re.match(pattern_count, text)
                if match2:
                    amount_str, name = match2.groups()
                    name = name.strip()
                    unit = "unit"  # Используем "unit" для штучных товаров
                    use_numeric_amount = True  # unit всегда возвращает числовое значение
            
            # Обработка количества
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2"
            if '/' in amount_str:
                # Для числовых значений конвертируем в float
                if use_numeric_amount:
                    parts = amount_str.split('/')
                    if len(parts) == 2:
                        try:
                            amount = float(parts[0]) / float(parts[1])
                        except ValueError:
                            amount = amount_str
                else:
                    # Для текстовых единиц оставляем как строку
                    amount = amount_str
            else:
                # Для числовых значений конвертируем в число
                if use_numeric_amount:
                    try:
                        # Пытаемся преобразовать в число
                        clean_amount = amount_str.replace(',', '.')
                        if '.' in clean_amount:
                            amount = float(clean_amount)
                        else:
                            amount = int(clean_amount)
                    except ValueError:
                        amount = amount_str
                else:
                    # Для текстовых единиц оставляем как строку
                    amount = amount_str
        else:
            # Паттерн с unit не совпал, пробуем паттерн подсчета
            match2 = re.match(pattern_count, text)
            if match2:
                amount_str, name = match2.groups()
                name = name.strip()
                unit = "unit"
                
                # Обработка количества для unit (всегда numeric)
                amount_str = amount_str.strip()
                if '/' in amount_str:
                    parts = amount_str.split('/')
                    if len(parts) == 2:
                        try:
                            amount = float(parts[0]) / float(parts[1])
                        except ValueError:
                            amount = None
                else:
                    try:
                        clean_amount = amount_str.replace(',', '.')
                        if '.' in clean_amount:
                            amount = float(clean_amount)
                        else:
                            amount = int(clean_amount)
                    except ValueError:
                        amount = None
        
        # Очистка названия
        name = name.strip() if name else text
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredients_list = []
        recipe_ingredients = recipe_data['recipeIngredient']
        
        if not isinstance(recipe_ingredients, list):
            return None
        
        for ingredient_text in recipe_ingredients:
            if not isinstance(ingredient_text, str):
                continue
            
            parsed = self.parse_ingredient_text(ingredient_text)
            if parsed:
                ingredients_list.append(parsed)
        
        return json.dumps(ingredients_list, ensure_ascii=False) if ingredients_list else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        
        if not isinstance(instructions, list):
            return None
        
        steps = []
        for idx, step in enumerate(instructions, 1):
            if isinstance(step, dict) and 'text' in step:
                steps.append(f"{idx}. {step['text']}")
            elif isinstance(step, str):
                steps.append(f"{idx}. {step}")
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            return self.clean_text(recipe_data['recipeCategory'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок из HTML секции Note"""
        # Ищем секцию с заголовком "Note"
        notes_header = self.soup.find('h3', class_='recipe__separator', string=re.compile(r'Note', re.I))
        
        if notes_header:
            # Ищем следующий элемент - список с заметками
            notes_list = notes_header.find_next_sibling('ol', id='recipe-notes')
            if notes_list:
                # Извлекаем все элементы списка
                items = notes_list.find_all('li')
                notes_texts = []
                for item in items:
                    text = self.clean_text(item.get_text())
                    if text:
                        notes_texts.append(text)
                
                return ' '.join(notes_texts) if notes_texts else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Убираем лишние пробелы и возвращаем теги через запятую
                tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                return ', '.join(tags) if tags else None
            elif isinstance(keywords, list):
                return ', '.join(keywords)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if not recipe_data or 'image' not in recipe_data:
            return None
        
        images = recipe_data['image']
        urls = []
        
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
        elif isinstance(images, dict):
            if 'url' in images:
                urls.append(images['url'])
            elif 'contentUrl' in images:
                urls.append(images['contentUrl'])
        
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
        instructions = self.extract_instructions()
        category = self.extract_category()
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        total_time = self.extract_total_time()
        notes = self.extract_notes()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "notes": notes,
            "tags": tags,
            "image_urls": image_urls
        }


def main():
    import os
    # Обрабатываем папку preprocessed/cucinaconamore_com
    preprocessed_dir = os.path.join("preprocessed", "cucinaconamore_com")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(CucinaConAmoreExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python cucinaconamore_com.py")


if __name__ == "__main__":
    main()
