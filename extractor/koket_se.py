"""
Экстрактор данных рецептов для сайта koket.se
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KoketSeExtractor(BaseRecipeExtractor):
    """Экстрактор для koket.se"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        if item.get('@type') == 'Recipe' and 'name' in item:
                            return self.clean_text(item['name'])
                elif isinstance(data, dict) and data.get('@type') == 'Recipe' and 'name' in data:
                    return self.clean_text(data['name'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из h1 заголовка
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        if item.get('@type') == 'Recipe' and 'description' in item:
                            return self.clean_text(item['description'])
                elif isinstance(data, dict) and data.get('@type') == 'Recipe' and 'description' in data:
                    return self.clean_text(data['description'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient_text(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат для koket.se
        
        Args:
            ingredient_text: Строка вида "30 g jäst" или "0,5 dl strösocker"
            
        Returns:
            dict: {"name": "jäst", "amount": 30, "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Пропускаем заголовки секций (обычно короткие слова без чисел и единиц измерения)
        # Примеры: "Surdeg", "Degen", "Filling", "För servering" etc.
        # Они обычно не содержат чисел и единиц измерения
        has_number = bool(re.search(r'\d', text))
        has_unit = bool(re.search(r'\b(g|kg|ml|dl|l|tsk|msk|krm|st|stycken)\b', text, re.I))
        
        # Если нет ни числа, ни единицы измерения, и текст короткий - скорее всего это заголовок
        if not has_number and not has_unit and len(text) < 20:
            return None
        
        # Пропускаем сложные инструкции-ингредиенты (содержат инструктивные слова)
        instruction_words = ['allt', 'utom', 'enligt', 'efter', 'smak', 'behov']
        if any(word in text.lower() for word in instruction_words):
            return None
        
        # Удаляем префиксы типа "ca", "cirka", "ungefär"
        text = re.sub(r'^(ca|cirka|ungefär)\s+', '', text, flags=re.I)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "30 g jäst", "0,5 dl strösocker", "1 ägg"
        # Сначала пробуем с единицей измерения
        pattern = r'^([\d,.\s/]+)\s*(g|kg|ml|dl|l|tsk|msk|krm|st|stycken|unit)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества - конвертируем запятую в точку для float
        amount = None
        if amount_str:
            amount_str = amount_str.strip().replace(',', '.')
            try:
                # Проверяем, можно ли преобразовать в число
                amount_float = float(amount_str)
                # Если это целое число, возвращаем как int, иначе как string
                if amount_float.is_integer():
                    amount = int(amount_float)
                else:
                    amount = amount_str
            except ValueError:
                amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем фразы в скобках (обычно комментарии типа "(ca 50 g)")
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем квадратные скобки (комментарии)
        name = re.sub(r'\[[^\]]*\]', '', name)
        # Удаляем запятые и лишнее в конце (например, ", smält", ", till fyllning")
        name_parts = name.split(',')
        name = name_parts[0].strip()
        # Удаляем лишние пробелы
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
        
        # Сначала пробуем извлечь из JSON-LD (самый надежный способ)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                recipe_data = None
                
                if isinstance(data, list):
                    for item in data:
                        if item.get('@type') == 'Recipe':
                            recipe_data = item
                            break
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    recipe_data = data
                
                if recipe_data and 'recipeIngredient' in recipe_data:
                    for ing_text in recipe_data['recipeIngredient']:
                        parsed = self.parse_ingredient_text(ing_text)
                        if parsed:
                            ingredients.append(parsed)
                    
                    if ingredients:
                        return json.dumps(ingredients, ensure_ascii=False)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, ищем в HTML
        ing_items = self.soup.find_all('li', class_=re.compile('ingredient', re.I))
        
        for item in ing_items:
            ingredient_text = item.get_text(strip=True)
            parsed = self.parse_ingredient_text(ingredient_text)
            if parsed:
                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        steps = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                recipe_data = None
                
                if isinstance(data, list):
                    for item in data:
                        if item.get('@type') == 'Recipe':
                            recipe_data = item
                            break
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    recipe_data = data
                
                if recipe_data and 'recipeInstructions' in recipe_data:
                    instructions = recipe_data['recipeInstructions']
                    if isinstance(instructions, list):
                        for step in instructions:
                            if isinstance(step, dict) and 'text' in step:
                                step_text = self.clean_text(step['text'])
                                if step_text:
                                    steps.append(step_text)
                            elif isinstance(step, str):
                                step_text = self.clean_text(step)
                                if step_text:
                                    steps.append(step_text)
                    
                    if steps:
                        return ' '.join(steps)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, ищем в HTML
        instruction_items = self.soup.find_all(['li', 'p', 'div'], class_=re.compile('instruction|step', re.I))
        
        for item in instruction_items:
            step_text = item.get_text(strip=True)
            step_text = self.clean_text(step_text)
            if step_text and len(step_text) > 10:  # Фильтруем короткие фрагменты
                steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                recipe_data = None
                
                if isinstance(data, list):
                    for item in data:
                        if item.get('@type') == 'Recipe':
                            recipe_data = item
                            break
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    recipe_data = data
                
                if recipe_data:
                    # Приоритет: keywords > recipeCategory > recipeCuisine
                    # Проверяем keywords (часто содержит более точную категорию)
                    if 'keywords' in recipe_data:
                        keywords = recipe_data['keywords']
                        if isinstance(keywords, list) and keywords:
                            return self.clean_text(keywords[0])
                        elif isinstance(keywords, str) and keywords:
                            return self.clean_text(keywords)
                    
                    # Проверяем recipeCategory
                    if 'recipeCategory' in recipe_data:
                        category = recipe_data['recipeCategory']
                        if isinstance(category, list) and category:
                            return self.clean_text(category[0])
                        elif isinstance(category, str) and category:
                            return self.clean_text(category)
                    
                    # Проверяем recipeCuisine
                    if 'recipeCuisine' in recipe_data:
                        cuisine = recipe_data['recipeCuisine']
                        if isinstance(cuisine, list) and cuisine:
                            return self.clean_text(cuisine[0])
                        elif isinstance(cuisine, str) and cuisine:
                            return self.clean_text(cuisine)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def parse_time_from_jsonld(self, time_str: str) -> Optional[str]:
        """
        Парсинг времени из JSON-LD формата ISO 8601 или текстового формата
        
        Args:
            time_str: Строка времени (например, "PT30M", "PT1H30M", или текст)
            
        Returns:
            Время в формате строки, например "30 minutes" или "1 hour 30 minutes"
        """
        if not time_str:
            return None
        
        # Если это уже текстовый формат, возвращаем как есть
        if not time_str.startswith('PT'):
            return self.clean_text(time_str)
        
        # Парсим ISO 8601 duration (PT30M, PT1H30M, и т.д.)
        time_str = time_str[2:]  # Убираем "PT"
        
        hours = 0
        minutes = 0
        
        # Извлекаем часы
        hour_match = re.search(r'(\d+)H', time_str)
        if hour_match:
            hours = int(hour_match.group(1))
        
        # Извлекаем минуты
        min_match = re.search(r'(\d+)M', time_str)
        if min_match:
            minutes = int(min_match.group(1))
        
        # Форматируем результат
        if hours > 0 and minutes > 0:
            return f"{hours} hour{'s' if hours > 1 else ''} {minutes} minutes"
        elif hours > 0:
            return f"{hours} hour{'s' if hours > 1 else ''}"
        elif minutes > 0:
            return f"{minutes} minutes"
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                recipe_data = None
                
                if isinstance(data, list):
                    for item in data:
                        if item.get('@type') == 'Recipe':
                            recipe_data = item
                            break
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    recipe_data = data
                
                if recipe_data:
                    # Маппинг типов времени на ключи JSON-LD
                    time_keys = {
                        'prep': 'prepTime',
                        'cook': 'cookTime',
                        'total': 'totalTime'
                    }
                    
                    key = time_keys.get(time_type)
                    if key and key in recipe_data:
                        time_value = recipe_data[key]
                        if time_value:  # Проверяем, что значение не пустое
                            return self.parse_time_from_jsonld(time_value)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('total')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем в HTML элементы с классами, содержащими 'note', 'tip', 'comment'
        # Но избегаем sponsor/ad элементов
        notes_elements = self.soup.find_all(
            ['div', 'p', 'section'], 
            class_=re.compile(r'(note|tip|comment|advice)(?!.*sponsor|.*ad)', re.I)
        )
        
        for elem in notes_elements:
            # Пропускаем элементы с признаками рекламы
            elem_text = elem.get_text(strip=True).lower()
            if any(word in elem_text for word in ['sponsrat', 'läs mer', 'annons', 'reklam']):
                continue
            
            text = elem.get_text(strip=True)
            text = self.clean_text(text)
            if text and len(text) > 10:
                return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                recipe_data = None
                
                if isinstance(data, list):
                    for item in data:
                        if item.get('@type') == 'Recipe':
                            recipe_data = item
                            break
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    recipe_data = data
                
                if recipe_data:
                    # Собираем теги из различных полей
                    # 1. keywords
                    if 'keywords' in recipe_data:
                        keywords = recipe_data['keywords']
                        if isinstance(keywords, list):
                            tags_list.extend([str(k).lower() for k in keywords])
                        elif isinstance(keywords, str):
                            # Разделяем по запятой если это строка
                            tags_list.extend([k.strip().lower() for k in keywords.split(',')])
                    
                    # 2. recipeCategory
                    if 'recipeCategory' in recipe_data:
                        category = recipe_data['recipeCategory']
                        if isinstance(category, list):
                            tags_list.extend([str(c).lower() for c in category])
                        elif isinstance(category, str):
                            tags_list.append(category.lower())
                    
                    # 3. recipeCuisine
                    if 'recipeCuisine' in recipe_data:
                        cuisine = recipe_data['recipeCuisine']
                        if isinstance(cuisine, list):
                            tags_list.extend([str(c).lower() for c in cuisine])
                        elif isinstance(cuisine, str):
                            tags_list.append(cuisine.lower())
            except (json.JSONDecodeError, KeyError):
                continue
        
        if not tags_list:
            return None
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags_list:
            tag = self.clean_text(tag)
            if tag and tag not in seen and len(tag) > 2:
                seen.add(tag)
                unique_tags.append(tag)
        
        # Возвращаем как строку через запятую с пробелом
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                recipe_data = None
                
                if isinstance(data, list):
                    for item in data:
                        if item.get('@type') == 'Recipe':
                            recipe_data = item
                            break
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    recipe_data = data
                
                if recipe_data and 'image' in recipe_data:
                    img = recipe_data['image']
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, list):
                        urls.extend([i for i in img if isinstance(i, str)])
                    elif isinstance(img, dict):
                        if 'url' in img:
                            urls.append(img['url'])
                        elif 'contentUrl' in img:
                            urls.append(img['contentUrl'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 2. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 3. Ищем в основном контенте рецепта
        recipe_images = self.soup.find_all('img', class_=re.compile(r'recipe.*image|main.*image', re.I))
        for img in recipe_images[:3]:  # Берем максимум 3 изображения
            if img.get('src'):
                urls.append(img['src'])
            elif img.get('data-src'):
                urls.append(img['data-src'])
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            # Возвращаем как строку через запятую (без пробелов)
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/koket_se
    preprocessed_dir = os.path.join("preprocessed", "koket_se")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(KoketSeExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python koket_se.py")


if __name__ == "__main__":
    main()
