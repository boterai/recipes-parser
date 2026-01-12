"""
экстрактор данных рецептов для сайта misya.info
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MisyaInfoExtractor(BaseRecipeExtractor):
    """Экстрактор для misya.info"""
    
    # Константа для маппинга Unicode дробей
    FRACTION_MAP = {
        '½': '0.5', '¼': '0.25', '¾': '0.75',
        '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
        '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
        '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
    }
    
    # Константа для итальянских единиц измерения
    ITALIAN_UNITS = (
        r'g|kg|ml|l|cucchiai?|cucchiaini?|bustine?|pizzichi?|'
        r'q\.b\.|litri?|etti?|grammi?|mele?|uova?|costa?'
    )
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах, например "90"
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
        
        return str(total_minutes) if total_minutes > 0 else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем JSON-LD
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
                
                # Ищем name в данных
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            recipe_data = item
                            break
                elif isinstance(data, dict) and is_recipe(data):
                    recipe_data = data
                
                if recipe_data and 'name' in recipe_data:
                    return self.clean_text(recipe_data['name'])
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в заголовке рецепта
        recipe_header = self.soup.find('h1', class_=re.compile(r'recipe.*title', re.I))
        if recipe_header:
            return self.clean_text(recipe_header.get_text())
        
        # Альтернативно просто h1
        h1 = self.soup.find('h1')
        if h1:
            title = h1.get_text()
            # Убираем суффиксы типа " - Ricetta", " - Misya"
            title = re.sub(r'\s+(-|–)\s+(Ricetta|Misya).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - Ricetta", " - Misya"
            title = re.sub(r'\s+(-|–)\s+(Ricetta|Misya).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем JSON-LD
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
                
                # Ищем description в данных
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            recipe_data = item
                            break
                elif isinstance(data, dict) and is_recipe(data):
                    recipe_data = data
                
                if recipe_data and 'description' in recipe_data:
                    return self.clean_text(recipe_data['description'])
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        # Ищем в HTML - intro/description секция
        intro = self.soup.find(class_=re.compile(r'recipe.*intro', re.I))
        if intro:
            p = intro.find('p')
            if p:
                return self.clean_text(p.get_text())
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем извлечь из data-атрибутов (самый структурированный способ)
        ingredient_items = self.soup.find_all('li', attrs={'data-ingredient-name': True})
        
        if ingredient_items:
            for item in ingredient_items:
                name = item.get('data-ingredient-name', '').strip()
                amount = item.get('data-ingredient-amount', '').strip()
                unit = item.get('data-ingredient-unit', '').strip()
                
                if name:
                    ingredients.append({
                        "name": name,
                        "amount": amount if amount else None,
                        "unit": unit if unit else None
                    })
        
        # Если не нашли через data-атрибуты, пробуем JSON-LD
        if not ingredients:
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
                    
                    # Ищем recipeIngredient в данных
                    recipe_data = None
                    if isinstance(data, list):
                        for item in data:
                            if is_recipe(item):
                                recipe_data = item
                                break
                    elif isinstance(data, dict) and is_recipe(data):
                        recipe_data = data
                    
                    if recipe_data and 'recipeIngredient' in recipe_data:
                        ingredient_strings = recipe_data['recipeIngredient']
                        if isinstance(ingredient_strings, list):
                            for ing_str in ingredient_strings:
                                # Парсим строку ингредиента
                                parsed = self.parse_ingredient(ing_str)
                                if parsed:
                                    ingredients.append(parsed)
                        break
                        
                except (json.JSONDecodeError, KeyError):
                    continue
        
        # Если все еще нет, ищем в HTML
        if not ingredients:
            ingredient_containers = [
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
                    
                    # Пропускаем заголовки секций (часто содержат двоеточие)
                    if ingredient_text and not ingredient_text.endswith(':'):
                        # Парсим в структурированный формат
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
            ingredient_text: Строка вида "300g farina 00" или "3 uova"
            
        Returns:
            dict: {"name": "farina 00", "amount": "300", "unit": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
        # Заменяем Unicode дроби на числа
        for fraction, decimal in self.FRACTION_MAP.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для итальянского формата: "300g farina" или "3 uova"
        # Поддержка q.b. (quanto basta - по вкусу)
        pattern = rf'^([\d\s/.,]+)?\s*({self.ITALIAN_UNITS})?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2" или "1 1/2"
            if '/' in amount_str:
                try:
                    parts = amount_str.split()
                    total = 0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            if float(denom) == 0:
                                # Игнорируем некорректные дроби
                                continue
                            total += float(num) / float(denom)
                        else:
                            total += float(part)
                    amount = str(total) if total > 0 else None
                except (ValueError, ZeroDivisionError):
                    # Если не удалось распарсить количество, оставляем как есть
                    amount = amount_str.replace(',', '.')
            else:
                amount = amount_str.replace(',', '.')
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "quanto basta", "a piacere", "facoltativo"
        name = re.sub(r'\b(quanto basta|a piacere|facoltativo|opzionale)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем извлечь из JSON-LD (самый надежный способ)
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
                
                # Ищем recipeInstructions в данных
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            recipe_data = item
                            break
                elif isinstance(data, dict) and is_recipe(data):
                    recipe_data = data
                
                if recipe_data and 'recipeInstructions' in recipe_data:
                    instructions = recipe_data['recipeInstructions']
                    if isinstance(instructions, list):
                        for idx, step in enumerate(instructions, 1):
                            if isinstance(step, dict) and 'text' in step:
                                steps.append(f"{idx}. {self.clean_text(step['text'])}")
                            elif isinstance(step, str):
                                steps.append(f"{idx}. {self.clean_text(step)}")
                
                if steps:
                    return ' '.join(steps)
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, ищем в HTML
        instructions_containers = [
            self.soup.find('ol', class_=re.compile(r'instruction.*list', re.I)),
            self.soup.find('div', class_=re.compile(r'instruction', re.I)),
            self.soup.find('div', class_=re.compile(r'preparazione', re.I))
        ]
        
        for container in instructions_containers:
            if not container:
                continue
            
            # Извлекаем шаги
            step_items = container.find_all('li')
            if not step_items:
                step_items = container.find_all('p')
            
            for idx, item in enumerate(step_items, 1):
                # Извлекаем текст инструкции
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    # Если уже есть нумерация, оставляем как есть
                    if re.match(r'^\d+\.', step_text):
                        steps.append(step_text)
                    else:
                        steps.append(f"{idx}. {step_text}")
            
            if steps:
                break
        
        return ' '.join(steps) if steps else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности в формате: 280 kcal; 5/12/38"""
        
        # Сначала пробуем извлечь из JSON-LD
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
                
                # Ищем nutrition в данных
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            recipe_data = item
                            break
                elif isinstance(data, dict) and is_recipe(data):
                    recipe_data = data
                
                if recipe_data and 'nutrition' in recipe_data:
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
                    
                    # Форматируем: "280 kcal; 5/12/38"
                    if calories and protein and fat and carbs:
                        return f"{calories} kcal; {protein}/{fat}/{carbs}"
                    elif calories:
                        return f"{calories} kcal"
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, ищем в HTML
        nutrition_section = self.soup.find(class_=re.compile(r'nutrition', re.I))
        if nutrition_section:
            text = nutrition_section.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            # Паттерн для формата "280 kcal; 5/12/38" или "280 kcal"
            pattern = r'(\d+)\s*kcal(?:\s*;\s*(\d+)/(\d+)/(\d+))?'
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                calories = match.group(1)
                protein = match.group(2)
                fat = match.group(3)
                carbs = match.group(4)
                if protein and fat and carbs:
                    return f"{calories} kcal; {protein}/{fat}/{carbs}"
                else:
                    return f"{calories} kcal"
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем JSON-LD
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
                
                # Ищем recipeCategory в данных
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            recipe_data = item
                            break
                elif isinstance(data, dict) and is_recipe(data):
                    recipe_data = data
                
                if recipe_data and 'recipeCategory' in recipe_data:
                    return self.clean_text(recipe_data['recipeCategory'])
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в HTML - класс category
        category_elem = self.soup.find(class_='category')
        if category_elem:
            return self.clean_text(category_elem.get_text())
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:  # Берем последнюю категорию перед самим рецептом
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Сначала пробуем извлечь из JSON-LD
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
                
                # Ищем время в данных
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            recipe_data = item
                            break
                elif isinstance(data, dict) and is_recipe(data):
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
                        iso_time = recipe_data[key]
                        return self.parse_iso_duration(iso_time)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, ищем в HTML
        time_patterns = {
            'prep': ['preparazione', 'prep.*time'],
            'cook': ['cottura', 'cook.*time'],
            'total': ['tempo.*totale', 'total.*time']
        }
        
        patterns = time_patterns.get(time_type, [])
        
        for pattern in patterns:
            # Ищем элемент с временем
            time_elem = self.soup.find(class_=re.compile(pattern, re.I))
            if not time_elem:
                # Ищем по тексту label
                time_label = self.soup.find(string=re.compile(pattern, re.I))
                if time_label and time_label.parent:
                    time_elem = time_label.parent.parent
            
            if time_elem:
                time_text = time_elem.get_text(strip=True)
                # Извлекаем числа из текста
                time_match = re.search(r'(\d+)\s*(minuti?|ore?|hours?|minutes?)', time_text, re.IGNORECASE)
                if time_match:
                    value = int(time_match.group(1))
                    unit = time_match.group(2).lower()
                    # Конвертируем в минуты
                    if 'ora' in unit or 'hour' in unit:
                        value = value * 60
                    return str(value)
        
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
        # Ищем секцию с примечаниями/советами
        notes_section = self.soup.find(class_=re.compile(r'note', re.I))
        
        if notes_section:
            # Сначала пробуем найти параграф внутри (без заголовка)
            p = notes_section.find('p')
            if p:
                text = self.clean_text(p.get_text())
                return text if text else None
            
            # Если нет параграфа, берем весь текст и убираем заголовок
            text = notes_section.get_text(separator=' ', strip=True)
            # Убираем заголовок "Note:" или "Nota:"
            text = re.sub(r'^Note?\s*:?\s*', '', text, flags=re.IGNORECASE)
            text = self.clean_text(text)
            return text if text else None
        
        # Альтернативно ищем h3 с текстом "Note" и следующий параграф
        note_heading = self.soup.find(['h2', 'h3', 'h4'], string=re.compile(r'Note?', re.I))
        if note_heading:
            next_sibling = note_heading.find_next_sibling('p')
            if next_sibling:
                text = self.clean_text(next_sibling.get_text())
                return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Сначала пробуем извлечь из JSON-LD
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
                
                # Ищем keywords в данных
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            recipe_data = item
                            break
                elif isinstance(data, dict) and is_recipe(data):
                    recipe_data = data
                
                if recipe_data and 'keywords' in recipe_data:
                    keywords = recipe_data['keywords']
                    if isinstance(keywords, str):
                        tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                    elif isinstance(keywords, list):
                        tags_list = [str(tag).strip() for tag in keywords if tag]
                    break
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если не нашли в JSON-LD, ищем в HTML
        if not tags_list:
            tags_container = self.soup.find(class_=re.compile(r'recipe.*tags?', re.I))
            if tags_container:
                tag_elements = tags_container.find_all(class_='tag')
                if tag_elements:
                    tags_list = [self.clean_text(tag.get_text()) for tag in tag_elements]
        
        # Если все еще нет, ищем мета-теги
        if not tags_list:
            meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                tags_string = meta_keywords['content']
                tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        if not tags_list:
            return None
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags_list:
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen.add(tag_lower)
                unique_tags.append(tag_lower)
        
        # Возвращаем как строку через запятую с пробелом
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Сначала пробуем извлечь из JSON-LD
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
                
                # Ищем image в данных
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            recipe_data = item
                            break
                elif isinstance(data, dict) and is_recipe(data):
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
                    break
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если не нашли в JSON-LD, ищем в meta-тегах
        if not urls:
            # og:image - обычно главное изображение
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
            
            # twitter:image
            twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
            if twitter_image and twitter_image.get('content'):
                urls.append(twitter_image['content'])
        
        # Если все еще нет, ищем изображения в recipe-image классе
        if not urls:
            recipe_images = self.soup.find_all(class_=re.compile(r'recipe.*image', re.I))
            for img_container in recipe_images:
                img = img_container.find('img')
                if img and img.get('src'):
                    urls.append(img['src'])
        
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
        instructions = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name.lower() if dish_name else None,
            "description": description.lower() if description else None,
            "ingredients": ingredients,
            "instructions": instructions.lower() if instructions else None,
            "nutrition_info": self.extract_nutrition_info(),
            "category": category.lower() if category else None,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes.lower() if notes else None,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    """Точка входа для обработки preprocessed/misya_info"""
    import os
    
    # Путь к директории с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "misya_info")
    
    # Проверяем существование директории
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(MisyaInfoExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python misya_info.py")


if __name__ == "__main__":
    main()
