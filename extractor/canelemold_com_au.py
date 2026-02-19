"""
Экстрактор данных рецептов для сайта canelemold.com.au
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CaneleMoldExtractor(BaseRecipeExtractor):
    """Экстрактор для canelemold.com.au"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT25H45M"
            
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
        
        # Форматируем результат
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # 1. Проверяем JSON-LD Recipe schema
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в JSON-LD
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'name' in data:
                        return self.clean_text(data['name'])
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 2. Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # 3. Ищем в meta тегах
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s+\|.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # 1. Проверяем JSON-LD Recipe schema
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'description' in data:
                        return self.clean_text(data['description'])
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 2. Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # 3. Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # 1. ПРИОРИТЕТ: Ищем в HTML таблице (более точные данные)
        # Ищем таблицу с заголовком "Ingredients"
        tables = self.soup.find_all('table')
        for table in tables:
            # Проверяем, есть ли заголовок "Ingredients"
            header = table.find('h2')
            if header and 'ingredient' in header.get_text().lower():
                # Извлекаем строки таблицы
                rows = table.find_all('tr')
                for row in rows:
                    # Пропускаем строку с заголовком
                    if row.find('h2'):
                        continue
                    
                    # Проверяем <th> элементы (в этой таблице ингредиенты в <th>)
                    cells = row.find_all('th')
                    if not cells:
                        cells = row.find_all('td')
                    
                    for cell in cells:
                        ingredient_text = cell.get_text(separator=' ', strip=True)
                        ingredient_text = self.clean_text(ingredient_text)
                        
                        if ingredient_text and len(ingredient_text) > 3:
                            # Парсим строку вида "500g of whole milk"
                            parsed = self.parse_ingredient_html_format(ingredient_text)
                            if parsed:
                                ingredients.append(parsed)
                
                if ingredients:
                    return json.dumps(ingredients, ensure_ascii=False)
        
        # 2. Fallback: Проверяем JSON-LD Recipe schema
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'recipeIngredient' in data:
                        recipe_ingredients = data['recipeIngredient']
                        if isinstance(recipe_ingredients, list):
                            for ingredient_text in recipe_ingredients:
                                parsed = self.parse_ingredient(ingredient_text)
                                if parsed:
                                    ingredients.append(parsed)
                        
                        if ingredients:
                            return json.dumps(ingredients, ensure_ascii=False)
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 3. Ищем список ингредиентов (last resort)
        ingredient_containers = self.soup.find_all(['ul', 'div'], class_=re.compile(r'ingredient', re.I))
        
        for container in ingredient_containers:
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
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        steps = []
        
        # 1. ПРИОРИТЕТ: Ищем в HTML - ищем списки (ol/ul) с инструкциями
        # Находим все нумерованные списки
        for ol in self.soup.find_all('ol'):
            items = ol.find_all('li', recursive=False)
            
            # Проверяем предыдущий элемент - заголовок
            prev_elem = ol.find_previous(['h2', 'h3', 'h4'])
            is_instructions = False
            if prev_elem:
                header_text = prev_elem.get_text().lower()
                # Инструкции обычно имеют заголовки типа "Preparation", "Instructions", "Method", "Steps"
                if any(word in header_text for word in ['preparation', 'instruction', 'method', 'step', 'procedure']):
                    is_instructions = True
                # Пропускаем советы/заметки
                if any(word in header_text for word in ['tip', 'note', 'advice']):
                    is_instructions = False
                    continue
            
            # Если не нашли заголовок, проверяем содержимое
            if not is_instructions and len(items) > 0:
                # Проверяем первые элементы на наличие глаголов действия
                action_verbs = ['begin', 'heat', 'pour', 'mix', 'whisk', 'add', 'stir', 
                               'bake', 'cook', 'preheat', 'place', 'remove', 'transfer',
                               'combine', 'fold', 'melt', 'prepare']
                
                for item in items[:3]:
                    text = item.get_text(separator=' ', strip=True).lower()
                    if any(verb in text[:50] for verb in action_verbs):
                        is_instructions = True
                        break
            
            if is_instructions:
                temp_steps = []
                for item in items:
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    
                    # Пропускаем очень короткие строки
                    if step_text and len(step_text) > 15:
                        temp_steps.append(step_text)
                
                # Если нашли достаточно шагов (минимум 3), используем их
                if len(temp_steps) >= 3:
                    steps = temp_steps
                    break
        
        if steps:
            return ' '.join(steps)
        
        # 2. Fallback: Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'recipeInstructions' in data:
                        instructions = data['recipeInstructions']
                        if isinstance(instructions, list):
                            for step in instructions:
                                if isinstance(step, dict) and 'text' in step:
                                    steps.append(self.clean_text(step['text']))
                                elif isinstance(step, str):
                                    steps.append(self.clean_text(step))
                        
                        if steps:
                            return ' '.join(steps)
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # 1. Проверяем JSON-LD Recipe schema
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'recipeCategory' in data:
                        return self.clean_text(data['recipeCategory'])
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 2. Ищем в meta-тегах
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Проверяем JSON-LD Recipe schema
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    # Маппинг типов времени на ключи JSON-LD
                    time_keys = {
                        'prep': 'prepTime',
                        'cook': 'cookTime',
                        'total': 'totalTime'
                    }
                    
                    key = time_keys.get(time_type)
                    if key and key in data:
                        iso_time = data[key]
                        return self.parse_iso_duration(iso_time)
                
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
        notes = []
        
        # Ищем списки с советами - обычно находятся в ordered list <ol>
        # Часто имеют заголовок типа "Pro Tips", "Tips", "Notes"
        for ol in self.soup.find_all('ol'):
            items = ol.find_all('li')
            
            # Проверяем предыдущий элемент - должен быть заголовок с "Tips" или "Notes"
            prev_elem = ol.find_previous(['h2', 'h3', 'h4'])
            has_tips_header = False
            if prev_elem:
                header_text = prev_elem.get_text().lower()
                if any(word in header_text for word in ['tip', 'note', 'advice']):
                    has_tips_header = True
                # Пропускаем инструкции
                if any(word in header_text for word in ['preparation', 'instruction', 'method', 'step']):
                    continue
            
            # Пропускаем, если это не похоже на советы
            if not has_tips_header:
                continue
            
            temp_notes = []
            for item in items:
                text = item.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                
                # Убираем заголовки вроде "Chocolate Selection:" в начале
                # Ищем двоеточие в первых 50 символах и удаляем все до него
                colon_match = re.match(r'^[^:]{1,50}:\s*(.+)', text)
                if colon_match:
                    text = colon_match.group(1)
                
                if text and len(text) > 10:
                    temp_notes.append(text)
            
            # Если нашли заметки, используем их
            if len(temp_notes) >= 2:
                notes = temp_notes
                break
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # 1. Проверяем JSON-LD Recipe schema
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'keywords' in data:
                        keywords = data['keywords']
                        if isinstance(keywords, str):
                            # Уже в формате строки с разделителями
                            return self.clean_text(keywords)
                        elif isinstance(keywords, list):
                            # Преобразуем список в строку
                            return ', '.join([str(k) for k in keywords])
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Проверяем JSON-LD Recipe schema
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'image' in data:
                        img = data['image']
                        if isinstance(img, str):
                            urls.append(img)
                        elif isinstance(img, list):
                            urls.extend([i for i in img if isinstance(i, str)])
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 2. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 3. Ищем изображения в контенте страницы
        # Ищем основное изображение рецепта
        main_images = self.soup.find_all('img', class_=re.compile(r'attachment|wp-image', re.I))
        for img in main_images[:3]:  # Берем первые 3
            src = img.get('src') or img.get('data-src')
            if src and 'http' in src:
                urls.append(src)
        
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
    
    def parse_ingredient_html_format(self, ingredient_text: str) -> Optional[Dict]:
        """
        Парсинг строки ингредиента из HTML таблицы
        Формат: "500g of whole milk" или "2 large egg yolks"
        
        Args:
            ingredient_text: Строка вида "500g of whole milk"
            
        Returns:
            dict: {"name": "whole milk", "amount": 500, "units": "g"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
        # Убираем "of" из паттерна "500g of milk"
        text = re.sub(r'\s+of\s+', ' ', text)
        
        # Паттерн для извлечения: количество + единица + название
        # Примеры: "500g whole milk", "2 large eggs", "65g semi-salted butter"
        pattern = r'^([\d\s/.,]+)\s*([a-z]*)\s+(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
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
            try:
                float_val = float(amount_str)
                amount = int(float_val) if float_val.is_integer() else float_val
            except ValueError:
                amount = None
        
        # Обработка единицы
        # Если единица пустая или похожа на прилагательное (large, small и т.д.), включаем ее в название
        descriptors = ['large', 'small', 'medium', 'whole', 'fresh', 'dried', 'chopped']
        if not unit or unit in descriptors:
            if unit:
                name = f"{unit} {name}"
            unit = None
        
        # Очистка названия
        name = re.sub(r'\([^)]*\)', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        return {
            "name": name,
            "amount": amount,
            "units": unit if unit else None
        }
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "500 ml whole milk" или "2 large eggs"
            
        Returns:
            dict: {"name": "whole milk", "amount": "500", "unit": "ml"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
        # Заменяем Unicode дроби на десятичные числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Используем word boundaries (\b) для точного совпадения единиц измерения
        pattern = r'^([\d\s/.,]+)?\s*\b(ml|liter|liters|g|gram|grams|kg|kilogram|kilograms|cup|cups|tablespoon|tablespoons|teaspoon|teaspoons|tbsp|tsp|oz|ounce|ounces|pound|pounds|lb|lbs|pinch|dash|unit|units|piece|pieces|clove|cloves)\b\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Попробуем паттерн для количества без единицы (например, "2 large eggs")
            simple_pattern = r'^([\d\s/.,]+)\s+(.+)'
            simple_match = re.match(simple_pattern, text)
            
            if simple_match:
                amount_str, name = simple_match.groups()
                # Обработка количества
                amount = amount_str.strip()
                if '/' in amount:
                    parts = amount.split()
                    total = 0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            total += float(part)
                    amount = str(int(total) if total.is_integer() else total)
                else:
                    try:
                        float_val = float(amount)
                        amount = str(int(float_val) if float_val.is_integer() else float_val)
                    except ValueError:
                        pass
                
                return {
                    "name": name.strip(),
                    "amount": amount,
                    "unit": None
                }
            
            # Если оба паттерна не совпали, возвращаем только название
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
            # Обработка дробей
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                amount = str(int(total) if total.is_integer() else total)
            else:
                amount = amount_str.replace(',', '.')
                # Преобразуем в int если возможно
                try:
                    float_val = float(amount)
                    amount = str(int(float_val) if float_val.is_integer() else float_val)
                except ValueError:
                    pass
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        name = re.sub(r'\([^)]*\)', '', name)  # Удаляем скобки
        name = re.sub(r'\b(to taste|as needed|or more|optional|for garnish)\b', '', name, flags=re.IGNORECASE)
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
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
    """
    Точка входа для обработки HTML файлов из директории preprocessed/canelemold_com_au
    """
    import os
    
    # Путь к директории с HTML файлами
    repo_root = Path(__file__).parent.parent
    preprocessed_dir = repo_root / "preprocessed" / "canelemold_com_au"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обработка файлов из: {preprocessed_dir}")
        process_directory(CaneleMoldExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python canelemold_com_au.py")


if __name__ == "__main__":
    main()
