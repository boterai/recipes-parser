"""
Экстрактор данных рецептов для сайта 10dakot.co.il
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TenDakotExtractor(BaseRecipeExtractor):
    """Экстрактор для 10dakot.co.il"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "XX minutes"
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
    
    def get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных из JSON-LD"""
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
                        if is_recipe(item):
                            return item
                elif isinstance(data, dict):
                    if '@graph' in data:
                        for item in data['@graph']:
                            if is_recipe(item):
                                return item
                    elif is_recipe(data):
                        return data
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld and 'name' in json_ld:
            name = self.clean_text(json_ld['name'])
            # Удаляем префикс "מתכון ל" если есть
            name = re.sub(r'^מתכון\s+ל\s*', '', name)
            return name
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Из заголовка h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
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
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld and 'recipeIngredient' in json_ld:
            for ingredient_text in json_ld['recipeIngredient']:
                if isinstance(ingredient_text, str):
                    # Парсим в структурированный формат
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        # Если JSON-LD не помог, ищем в HTML
        if not ingredients:
            ingredient_container = self.soup.find(class_=re.compile(r'ingredients.*content', re.I))
            if ingredient_container:
                items = ingredient_container.find_all('li')
                for item in items:
                    ingredient_text = item.get_text(separator=' ', strip=True)
                    ingredient_text = self.clean_text(ingredient_text)
                    
                    if ingredient_text and not ingredient_text.endswith(':'):
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка с ингредиентом
            
        Returns:
            dict: {"name": "...", "amount": ..., "units": "..."} или None
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
        
        # Маппинг Hebrew -> English единиц измерения
        unit_mapping = {
            'כוס': 'cup',
            'כוסות': 'cups',
            'כף': 'tablespoon',
            'כפות': 'tablespoons',
            'כפית': 'teaspoon',
            'כפיות': 'teaspoons',
            'יחידה': 'unit',
            'יחידות': 'unit',
            'שיניים': 'cloves',
            'שן': 'clove',
            'גרם': 'gram',
            'גרמים': 'grams',
            'ק"ג': 'kg',
            'מ"ל': 'ml',
            'ליטר': 'liter',
        }
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "2 כוסות כרובית", "1 בצל", "חצי כוס גריסים"
        pattern = r'^([\d\s/.,\-]+)?\s*(כוס(?:ות)?|כף(?:ות)?|כפית|כפיות|יחידה|יחידות|שיניים|שן|גרם(?:ים)?|ק"ג|מ"ל|ליטר|cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|unit|cloves?)?\s*(.+)'
        
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
            # Обработка дробей типа "1/2" или "1 1/2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        # Удаляем дефисы, которые могут быть разделителями
                        part = part.replace('-', '')
                        if part:
                            try:
                                total += float(part)
                            except ValueError:
                                pass
                if total > 0:
                    # Если это целое число, возвращаем как int
                    amount = int(total) if total == int(total) else total
            else:
                # Удаляем дефисы для диапазонов типа "4-5"
                amount_str = amount_str.replace(',', '.')
                # Берем первое число из диапазона
                amount_match = re.search(r'([\d.]+)', amount_str)
                if amount_match:
                    try:
                        val = float(amount_match.group(1))
                        amount = int(val) if val == int(val) else val
                    except ValueError:
                        pass
        
        # Обработка единицы измерения и перевод на английский
        english_unit = None
        if unit:
            unit = unit.strip()
            # Проверяем маппинг Hebrew -> English
            english_unit = unit_mapping.get(unit, unit)
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        # Если количество и единица не определены, но название предполагает единичный предмет
        # (бצל, גזר, תפוח, etc.), устанавливаем по умолчанию amount=1, units="unit"
        if amount is None and english_unit is None:
            # Список слов, которые обычно подразумевают единичный предмет
            countable_items = ['בצל', 'גזר', 'תפוח', 'גמבה', 'קישוא', 'תפו"א', 'עגבני', 
                             'שן שום', 'גבעול', 'פלפל', 'בטטה', 'דלעת']
            
            # Проверяем, начинается ли название с одного из этих слов
            name_lower = name.lower()
            for item in countable_items:
                if name_lower.startswith(item):
                    amount = 1
                    english_unit = "unit"
                    break
        
        return {
            "name": name,
            "amount": amount,
            "units": english_unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions = []
        
        # Сначала пробуем из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld and 'recipeInstructions' in json_ld:
            recipe_instructions = json_ld['recipeInstructions']
            
            if isinstance(recipe_instructions, list):
                for step in recipe_instructions:
                    if isinstance(step, dict) and 'text' in step:
                        instructions.append(self.clean_text(step['text']))
                    elif isinstance(step, str):
                        instructions.append(self.clean_text(step))
            elif isinstance(recipe_instructions, str):
                instructions.append(self.clean_text(recipe_instructions))
        
        # Если JSON-LD не помог, ищем в HTML
        if not instructions:
            instruction_containers = [
                self.soup.find('ol', class_=re.compile(r'instruction', re.I)),
                self.soup.find('div', class_=re.compile(r'instruction', re.I))
            ]
            
            for container in instruction_containers:
                if not container:
                    continue
                
                step_items = container.find_all('li')
                if not step_items:
                    step_items = container.find_all('p')
                
                for item in step_items:
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    
                    if step_text:
                        instructions.append(step_text)
                
                if instructions:
                    break
        
        # Объединяем все инструкции в одну строку
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld and 'recipeCategory' in json_ld:
            category = json_ld['recipeCategory']
            category_str = category if isinstance(category, str) else ', '.join(category) if isinstance(category, list) else None
            
            if category_str:
                # Проверяем если есть "מרקים" (супы) в категориях
                if 'מרק' in category_str:
                    return "Soup"
                # Можно добавить другие маппинги категорий при необходимости
                # Возвращаем первую категорию из списка
                first_cat = category_str.split(',')[0].strip()
                return self.clean_text(first_cat)
        
        # Ищем в метаданных
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
        # Сначала пробуем из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld:
            # Маппинг типов времени на ключи JSON-LD
            time_keys = {
                'prep': 'prepTime',
                'cook': 'cookTime',
                'total': 'totalTime'
            }
            
            key = time_keys.get(time_type)
            if key and key in json_ld:
                iso_time = json_ld[key]
                return self.parse_iso_duration(iso_time)
        
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
        # Ищем параграфы с советами (обычно начинаются с "1. בחירת" или подобного)
        all_paragraphs = self.soup.find_all('p')
        
        for p in all_paragraphs:
            text = p.get_text(separator=' ', strip=True)
            # Ищем параграфы, которые начинаются с номера и содержат советы
            # Обычно это "1. בחירת הירקות" или подобное
            if re.match(r'^\d+\.\s*בחירת', text) or re.match(r'^\d+\.\s*טיפ', text):
                # Удаляем только номер и слово "בחירת" (не весь заголовок)
                # Ищем первое предложение после "בחירת הירקות"
                # Паттерн: "1. בחירת הירקות " - убираем это
                cleaned = re.sub(r'^\d+\.\s*בחירת\s+[^\s]+\s+', '', text)
                cleaned = self.clean_text(cleaned)
                if cleaned and len(cleaned) > 20:
                    return cleaned
        
        # Альтернативный поиск по ключевым словам в тексте
        for p in all_paragraphs:
            text = p.get_text(separator=' ', strip=True)
            # Ищем параграфы с конкретными паттернами заметок/советов
            if 'השתמשו ב' in text or 'טיפ' in text or 'שימו לב' in text:
                text = self.clean_text(text)
                # Удаляем возможные префиксы с номерами
                text = re.sub(r'^\d+\.\s*[א-ת\s]+\s+', '', text)
                if text and len(text) > 20 and len(text) < 500:
                    return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Приоритет: article:tag мета-теги (они более точные)
        article_tags = self.soup.find_all('meta', property='article:tag')
        for tag in article_tags:
            if tag.get('content'):
                tags_list.append(tag['content'].strip())
        
        # Если не нашли article:tag, ищем в keywords
        if not tags_list:
            meta_keywords = self.soup.find('meta', {'name': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                tags_string = meta_keywords['content']
                tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        # Убираем дубликаты, сохраняя порядок
        if tags_list:
            seen = set()
            unique_tags = []
            for tag in tags_list:
                tag_lower = tag.lower()
                if tag_lower not in seen:
                    seen.add(tag_lower)
                    unique_tags.append(tag)
            
            return ', '.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
        
        # 3. Ищем img теги на странице
        imgs = self.soup.find_all('img', class_=re.compile(r'wp-image', re.I))
        for img in imgs:
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
    # Обрабатываем папку preprocessed/10dakot_co_il
    recipes_dir = os.path.join("preprocessed", "10dakot_co_il")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(TenDakotExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python 10dakot_co_il.py")


if __name__ == "__main__":
    main()
