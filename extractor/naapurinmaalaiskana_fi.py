"""
Экстрактор данных рецептов для сайта naapurinmaalaiskana.fi
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class NaapurinMaalaisKanaExtractor(BaseRecipeExtractor):
    """Экстрактор для naapurinmaalaiskana.fi"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
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
                
                # Ищем название в данных
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
        
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            name = h1.get_text(strip=True)
            if name:
                return self.clean_text(name)
        
        # Альтернативно - из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффикс с названием сайта
            title = re.sub(r'\s*[-|]\s*naapurin.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                def is_recipe(item):
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        return 'Recipe' in item_type
                    return item_type == 'Recipe'
                
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
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "450 g jauhoja" или "1 tl suolaa"
            
        Returns:
            dict: {"name": "jauhoja", "amount": "450", "unit": "g"} или None
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
        
        # Паттерн для финских рецептов: количество + единица + название
        # Примеры: "450 g jauhoja", "1 tl suolaa", "4,5 dl piimää"
        pattern = r'^([\d\s,.\-]+)?\s*(g|kg|ml|dl|l|tl|rkl|kpl|pussi|prk|pkt|viipale|viipaleina)?\.?\s*(.+)'
        
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
            amount = amount_str.strip()
            # Заменяем запятую на точку для десятичных чисел
            amount = amount.replace(',', '.')
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем текст в скобках
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "maun mukaan", "tarpeen mukaan"
        name = re.sub(r'\b(maun mukaan|tarpeen mukaan|tai|vaihtoehtoisesti)\b', '', name, flags=re.IGNORECASE)
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
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                def is_recipe(item):
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        return 'Recipe' in item_type
                    return item_type == 'Recipe'
                
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            recipe_data = item
                            break
                elif isinstance(data, dict) and is_recipe(data):
                    recipe_data = data
                
                if recipe_data and 'recipeIngredient' in recipe_data:
                    for ingredient_text in recipe_data['recipeIngredient']:
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
                    
                    if ingredients:
                        return json.dumps(ingredients, ensure_ascii=False)
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, ищем в HTML
        # Ищем список ингредиентов по различным возможным селекторам
        ingredient_containers = [
            self.soup.find('ul', class_=re.compile(r'ingredient', re.I)),
            self.soup.find('div', class_=re.compile(r'ingredient', re.I)),
            self.soup.find('section', class_=re.compile(r'ingredient', re.I)),
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
                if ingredient_text and ':' not in ingredient_text:
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
            
            if ingredients:
                break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                def is_recipe(item):
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        return 'Recipe' in item_type
                    return item_type == 'Recipe'
                
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
                                steps.append(f"{idx}. {step['text']}")
                            elif isinstance(step, str):
                                steps.append(f"{idx}. {step}")
                    elif isinstance(instructions, str):
                        steps.append(instructions)
                
                if steps:
                    return ' '.join(steps)
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, ищем в HTML
        instructions_containers = [
            self.soup.find('ol', class_=re.compile(r'instruction', re.I)),
            self.soup.find('div', class_=re.compile(r'instruction', re.I)),
            self.soup.find('section', class_=re.compile(r'instruction', re.I)),
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
        
        # Если нумерация не была в HTML, добавляем её
        if steps and not re.match(r'^\d+\.', steps[0]):
            steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                def is_recipe(item):
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        return 'Recipe' in item_type
                    return item_type == 'Recipe'
                
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            recipe_data = item
                            break
                elif isinstance(data, dict) and is_recipe(data):
                    recipe_data = data
                
                if recipe_data and 'recipeCategory' in recipe_data:
                    category = recipe_data['recipeCategory']
                    if isinstance(category, list):
                        return self.clean_text(category[0]) if category else None
                    return self.clean_text(category)
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())
        
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def parse_iso_duration(self, duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах, например "90 minutes"
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
                
                def is_recipe(item):
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        return 'Recipe' in item_type
                    return item_type == 'Recipe'
                
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
        # Финские термины для времени
        time_patterns = {
            'prep': ['valmistusaika', 'esivalmistelu'],
            'cook': ['kypsennysaika', 'paisto'],
            'total': ['kokonaisaika', 'yhteensä']
        }
        
        patterns = time_patterns.get(time_type, [])
        
        for pattern in patterns:
            # Ищем элемент с временем
            time_elem = self.soup.find(text=re.compile(pattern, re.I))
            if time_elem:
                # Ищем число минут поблизости
                parent = time_elem.parent
                if parent:
                    time_text = parent.get_text(strip=True)
                    time_match = re.search(r'(\d+)\s*(min|minuutt)', time_text, re.I)
                    if time_match:
                        return f"{time_match.group(1)} minutes"
        
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
        notes_patterns = [
            re.compile(r'notes?', re.I),
            re.compile(r'tips?', re.I),
            re.compile(r'vinkit', re.I),
            re.compile(r'huomio', re.I),
        ]
        
        for pattern in notes_patterns:
            notes_section = self.soup.find(class_=pattern)
            if notes_section:
                text = notes_section.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                # Убираем заголовки типа "Vinkit", "Tips", "Notes"
                text = re.sub(r'^(Vinkit|Tips?|Notes?|Huomio)\s*:?\s*', '', text, flags=re.IGNORECASE)
                return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                def is_recipe(item):
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        return 'Recipe' in item_type
                    return item_type == 'Recipe'
                
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
                    
                    if tags_list:
                        return ', '.join(tags_list)
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            if tags_list:
                return ', '.join(tags_list)
        
        # Ищем теги в HTML (ссылки или span элементы)
        tags_container = self.soup.find(class_=re.compile(r'tags?', re.I))
        if tags_container:
            tag_links = tags_container.find_all('a')
            if not tag_links:
                tag_links = tags_container.find_all('span')
            
            for tag in tag_links:
                tag_text = tag.get_text(strip=True)
                if tag_text:
                    tags_list.append(tag_text)
        
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                def is_recipe(item):
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        return 'Recipe' in item_type
                    return item_type == 'Recipe'
                
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
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Обработка HTML файлов из preprocessed/naapurinmaalaiskana_fi"""
    import os
    
    # Определяем путь к директории с HTML файлами
    base_dir = Path(__file__).parent.parent
    preprocessed_dir = base_dir / "preprocessed" / "naapurinmaalaiskana_fi"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        process_directory(NaapurinMaalaisKanaExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Создайте директорию и поместите в неё HTML файлы рецептов с сайта naapurinmaalaiskana.fi")


if __name__ == "__main__":
    main()
