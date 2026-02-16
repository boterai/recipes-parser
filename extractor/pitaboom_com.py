"""
Экстрактор данных рецептов для сайта pitaboom.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class PitaboomExtractor(BaseRecipeExtractor):
    """Экстрактор для pitaboom.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "20 minuta" или "1h 30 minuta"
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
        result = []
        if hours > 0:
            result.append(f"{hours}h")
        if minutes > 0:
            result.append(f"{minutes} minuta")
        
        return ' '.join(result) if result else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Обработка массива
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe' and 'name' in item:
                            return self.clean_text(item['name'])
                # Обработка одиночного объекта
                elif isinstance(data, dict):
                    if data.get('@type') == 'Recipe' and 'name' in data:
                        return self.clean_text(data['name'])
                    # Обработка @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if item.get('@type') == 'Recipe' and 'name' in item:
                                return self.clean_text(item['name'])
                                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из h1
        recipe_header = self.soup.find('h1', class_='elementor-heading-title')
        if recipe_header:
            return self.clean_text(recipe_header.get_text())
        
        # Из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " | Pitaboom"
            title = re.sub(r'\s+\|\s+Pitaboom.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD"""
        ingredients = []
        
        # Сначала пробуем извлечь из JSON-LD (самый надежный способ для pitaboom.com)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Функция для извлечения ингредиентов из объекта Recipe
                def extract_from_recipe(recipe_data):
                    if not isinstance(recipe_data, dict):
                        return []
                    
                    if recipe_data.get('@type') != 'Recipe':
                        return []
                    
                    if 'recipeIngredient' not in recipe_data:
                        return []
                    
                    ingredients_list = []
                    for ingredient_str in recipe_data['recipeIngredient']:
                        parsed = self.parse_ingredient_from_string(ingredient_str)
                        if parsed:
                            ingredients_list.append(parsed)
                    
                    return ingredients_list
                
                # Обработка массива
                if isinstance(data, list):
                    for item in data:
                        result = extract_from_recipe(item)
                        if result:
                            ingredients = result
                            break
                # Обработка одиночного объекта
                elif isinstance(data, dict):
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            result = extract_from_recipe(item)
                            if result:
                                ingredients = result
                                break
                    else:
                        ingredients = extract_from_recipe(data)
                
                if ingredients:
                    break
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, пробуем таблицу #sastojciTabela
        if not ingredients:
            table = self.soup.find('table', id='sastojciTabela')
            if table:
                rows = table.find_all('tr')
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 2:
                        # Первая ячейка содержит количество и единицу
                        quantity_unit_text = self.clean_text(cells[0].get_text())
                        # Вторая ячейка содержит название
                        name_text = self.clean_text(cells[1].get_text())
                        
                        # Парсим количество и единицу
                        amount, unit = self.parse_quantity_unit(quantity_unit_text)
                        
                        if name_text:
                            ingredients.append({
                                "name": name_text,
                                "units": unit,
                                "amount": amount
                            })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient_from_string(self, ingredient_str: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента из JSON-LD
        
        Args:
            ingredient_str: Строка вида "500 g Domaćih tankih kora" или "6 kom Jaja" или "3 jaja"
            
        Returns:
            dict: {"name": "...", "units": "...", "amount": ...}
        """
        if not ingredient_str:
            return None
        
        ingredient_str = self.clean_text(ingredient_str)
        
        # Паттерн 1: количество + единица + название
        # Примеры: "500 g Domaćih tankih kora", "6 kom Jaja", "100 ml Jogurta"
        pattern1 = r'^(\d+(?:[.,]\d+)?)\s+(g|kg|ml|l|kom|tbsp|tsp)\s+(.+)$'
        
        match = re.match(pattern1, ingredient_str, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Конвертируем количество
            amount = None
            if amount_str:
                try:
                    # Заменяем запятую на точку для правильного парсинга
                    amount_str = amount_str.replace(',', '.')
                    amount = float(amount_str) if '.' in amount_str else int(amount_str)
                except ValueError:
                    amount = None
            
            return {
                "name": self.clean_text(name),
                "units": unit.strip() if unit else None,
                "amount": amount
            }
        
        # Паттерн 2: количество + название (без единицы)
        # Примеры: "3 jaja", "1 prašak za pecivo"
        pattern2 = r'^(\d+(?:[.,]\d+)?)\s+(.+)$'
        match2 = re.match(pattern2, ingredient_str, re.IGNORECASE)
        
        if match2:
            amount_str, name = match2.groups()
            
            # Конвертируем количество
            amount = None
            if amount_str:
                try:
                    amount_str = amount_str.replace(',', '.')
                    amount = float(amount_str) if '.' in amount_str else int(amount_str)
                except ValueError:
                    amount = None
            
            return {
                "name": self.clean_text(name),
                "units": "kom",  # По умолчанию "kom" для штучных ингредиентов
                "amount": amount
            }
        
        # Паттерн 3: название + "po ukusu" (без количества)
        # Примеры: "So po ukusu", "Prstohvat soli"
        pattern3 = r'^(.+?)\s+(po ukusu)$'
        match3 = re.match(pattern3, ingredient_str, re.IGNORECASE)
        
        if match3:
            name, unit = match3.groups()
            return {
                "name": self.clean_text(name),
                "units": unit.strip() if unit else None,
                "amount": None
            }
        
        # Паттерн 4: "Prstohvat ..." (щепотка)
        if ingredient_str.lower().startswith('prstohvat'):
            return {
                "name": self.clean_text(re.sub(r'^prstohvat\s+', '', ingredient_str, flags=re.IGNORECASE)),
                "units": "po ukusu",
                "amount": None
            }
        
        # Если ничего не совпало, возвращаем только название
        return {
            "name": self.clean_text(ingredient_str),
            "units": None,
            "amount": None
        }
    
    def parse_quantity_unit(self, text: str) -> tuple:
        """
        Парсинг строки с количеством и единицей
        
        Args:
            text: Строка вида "500 g" или "6 kom"
            
        Returns:
            tuple: (amount, unit)
        """
        if not text:
            return (None, None)
        
        text = self.clean_text(text)
        
        # Паттерн для извлечения количества и единицы
        pattern = r'^(\d+(?:[.,]\d+)?)\s*(.+)?$'
        match = re.match(pattern, text)
        
        if match:
            amount_str, unit = match.groups()
            
            # Конвертируем количество
            amount = None
            if amount_str:
                try:
                    amount_str = amount_str.replace(',', '.')
                    amount = float(amount_str) if '.' in amount_str else int(amount_str)
                except ValueError:
                    amount = None
            
            return (amount, unit.strip() if unit else None)
        
        return (None, None)
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления из JSON-LD"""
        steps = []
        
        # Извлекаем из JSON-LD (самый надежный способ для pitaboom.com)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Функция для извлечения инструкций из объекта Recipe
                def extract_from_recipe(recipe_data):
                    if not isinstance(recipe_data, dict):
                        return []
                    
                    if recipe_data.get('@type') != 'Recipe':
                        return []
                    
                    if 'recipeInstructions' not in recipe_data:
                        return []
                    
                    instructions = recipe_data['recipeInstructions']
                    steps_list = []
                    
                    if isinstance(instructions, list):
                        for step in instructions:
                            if isinstance(step, dict):
                                # HowToStep формат
                                if step.get('@type') == 'HowToStep':
                                    step_name = step.get('name', '')
                                    step_text = step.get('text', '')
                                    
                                    # Комбинируем имя и текст
                                    if step_name and step_text:
                                        steps_list.append(f"{step_name}: {step_text}")
                                    elif step_text:
                                        steps_list.append(step_text)
                                    elif step_name:
                                        steps_list.append(step_name)
                                # Обычный объект с текстом
                                elif 'text' in step:
                                    steps_list.append(step['text'])
                            elif isinstance(step, str):
                                steps_list.append(step)
                    
                    return steps_list
                
                # Обработка массива
                if isinstance(data, list):
                    for item in data:
                        result = extract_from_recipe(item)
                        if result:
                            steps = result
                            break
                # Обработка одиночного объекта
                elif isinstance(data, dict):
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            result = extract_from_recipe(item)
                            if result:
                                steps = result
                                break
                    else:
                        steps = extract_from_recipe(data)
                
                if steps:
                    break
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return ' '.join(steps) if steps else None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки из JSON-LD"""
        return self.extract_time_from_json_ld('prepTime')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления из JSON-LD"""
        return self.extract_time_from_json_ld('cookTime')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени из JSON-LD"""
        return self.extract_time_from_json_ld('totalTime')
    
    def extract_time_from_json_ld(self, time_key: str) -> Optional[str]:
        """
        Извлечение времени из JSON-LD
        
        Args:
            time_key: Ключ времени ('prepTime', 'cookTime', 'totalTime')
        """
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Функция для извлечения времени из объекта Recipe
                def extract_from_recipe(recipe_data):
                    if not isinstance(recipe_data, dict):
                        return None
                    
                    if recipe_data.get('@type') != 'Recipe':
                        return None
                    
                    if time_key in recipe_data:
                        iso_time = recipe_data[time_key]
                        return self.parse_iso_duration(iso_time)
                    
                    return None
                
                # Обработка массива
                if isinstance(data, list):
                    for item in data:
                        result = extract_from_recipe(item)
                        if result:
                            return result
                # Обработка одиночного объекта
                elif isinstance(data, dict):
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            result = extract_from_recipe(item)
                            if result:
                                return result
                    else:
                        result = extract_from_recipe(data)
                        if result:
                            return result
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Функция для извлечения категории из объекта Recipe
                def extract_from_recipe(recipe_data):
                    if not isinstance(recipe_data, dict):
                        return None
                    
                    if recipe_data.get('@type') != 'Recipe':
                        return None
                    
                    # Приоритет: recipeCategory, потом recipeCuisine
                    if 'recipeCategory' in recipe_data:
                        category = recipe_data['recipeCategory']
                        # Категория может быть строкой или списком
                        if isinstance(category, list):
                            return ', '.join([self.clean_text(c) for c in category if c])
                        else:
                            return self.clean_text(category)
                    elif 'recipeCuisine' in recipe_data:
                        cuisine = recipe_data['recipeCuisine']
                        # Cuisine также может быть списком
                        if isinstance(cuisine, list):
                            return ', '.join([self.clean_text(c) for c in cuisine if c])
                        else:
                            return self.clean_text(cuisine)
                    
                    return None
                
                # Обработка массива
                if isinstance(data, list):
                    for item in data:
                        result = extract_from_recipe(item)
                        if result:
                            return result
                # Обработка одиночного объекта
                elif isinstance(data, dict):
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            result = extract_from_recipe(item)
                            if result:
                                return result
                    else:
                        result = extract_from_recipe(data)
                        if result:
                            return result
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем элементы с текстом "Napomena" или подобным
        # В HTML pitaboom.com заметки могут быть в параграфах с ключевыми словами
        
        # Поиск по заголовкам
        headers = self.soup.find_all(['h2', 'h3', 'h4', 'p', 'strong', 'b'])
        
        for header in headers:
            header_text = self.clean_text(header.get_text())
            
            # Проверяем, содержит ли заголовок слово "napomena" или подобные
            if re.search(r'\bnapomena\b', header_text, re.IGNORECASE):
                # Ищем следующий элемент с текстом
                next_elem = header.find_next_sibling()
                
                if next_elem:
                    note_text = self.clean_text(next_elem.get_text())
                    if note_text and len(note_text) > 10:
                        return note_text
                
                # Если нет следующего элемента, возможно текст в том же элементе
                # Убираем слово "Napomena:" из текста
                note_text = re.sub(r'\bnapomena\s*:\s*', '', header_text, flags=re.IGNORECASE)
                if note_text and len(note_text) > 10:
                    return note_text
        
        # Альтернативный поиск - по содержимому текста
        paragraphs = self.soup.find_all('p')
        for p in paragraphs:
            text = self.clean_text(p.get_text())
            if text and len(text) > 50:
                # Проверяем, содержит ли параграф ключевые слова заметок
                if re.search(r'\b(napomena|savet|tip|važno|preporuka)\b', text, re.IGNORECASE):
                    # Убираем префикс "Napomena:"
                    text = re.sub(r'^\s*(napomena|savet|tip|važno|preporuka)\s*:\s*', '', text, flags=re.IGNORECASE)
                    if text:
                        return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Функция для извлечения тегов из объекта Recipe
                def extract_from_recipe(recipe_data):
                    if not isinstance(recipe_data, dict):
                        return None
                    
                    if recipe_data.get('@type') != 'Recipe':
                        return None
                    
                    if 'keywords' in recipe_data:
                        keywords = recipe_data['keywords']
                        # keywords может быть строкой с разделителями или списком
                        if isinstance(keywords, str):
                            return self.clean_text(keywords)
                        elif isinstance(keywords, list):
                            return ', '.join([self.clean_text(k) for k in keywords if k])
                    
                    return None
                
                # Обработка массива
                if isinstance(data, list):
                    for item in data:
                        result = extract_from_recipe(item)
                        if result:
                            return result
                # Обработка одиночного объекта
                elif isinstance(data, dict):
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            result = extract_from_recipe(item)
                            if result:
                                return result
                    else:
                        result = extract_from_recipe(data)
                        if result:
                            return result
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах (главное изображение)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Функция для извлечения изображений из объекта Recipe
                def extract_from_recipe(recipe_data):
                    if not isinstance(recipe_data, dict):
                        return []
                    
                    if recipe_data.get('@type') != 'Recipe':
                        return []
                    
                    img_urls = []
                    
                    # Основное изображение
                    if 'image' in recipe_data:
                        img = recipe_data['image']
                        if isinstance(img, str):
                            img_urls.append(img)
                        elif isinstance(img, list):
                            img_urls.extend([i for i in img if isinstance(i, str)])
                        elif isinstance(img, dict):
                            if 'url' in img:
                                img_urls.append(img['url'])
                            elif 'contentUrl' in img:
                                img_urls.append(img['contentUrl'])
                    
                    # Изображения из шагов
                    if 'recipeInstructions' in recipe_data:
                        instructions = recipe_data['recipeInstructions']
                        if isinstance(instructions, list):
                            for step in instructions:
                                if isinstance(step, dict) and 'image' in step:
                                    step_img = step['image']
                                    if isinstance(step_img, str):
                                        img_urls.append(step_img)
                                    elif isinstance(step_img, list):
                                        img_urls.extend([i for i in step_img if isinstance(i, str)])
                    
                    return img_urls
                
                # Обработка массива
                if isinstance(data, list):
                    for item in data:
                        result = extract_from_recipe(item)
                        if result:
                            urls.extend(result)
                            break
                # Обработка одиночного объекта
                elif isinstance(data, dict):
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            result = extract_from_recipe(item)
                            if result:
                                urls.extend(result)
                                break
                    else:
                        result = extract_from_recipe(data)
                        if result:
                            urls.extend(result)
                
                if urls:
                    break
                    
            except (json.JSONDecodeError, KeyError):
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
    # Обрабатываем папку preprocessed/pitaboom_com
    preprocessed_dir = os.path.join("preprocessed", "pitaboom_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(PitaboomExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python pitaboom_com.py")


if __name__ == "__main__":
    main()
