"""
Экстрактор данных рецептов для сайта toprecepty.cz
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TopreceptyExtractor(BaseRecipeExtractor):
    """Экстрактор для toprecepty.cz"""
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Получение данных Recipe из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем если это Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Пробуем получить из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            name = self.clean_text(recipe_data['name'])
            # Убираем текст в скобках (часто это пометки типа "i pro začátečníky")
            name = re.sub(r'\s*\([^)]*\)\s*', '', name)
            return name.strip()
        
        # Альтернативно - из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - Toprecepty.cz"
            title = re.sub(r'\s*[-–]\s*Toprecepty\.cz.*$', '', title, flags=re.IGNORECASE)
            # Убираем текст в скобках
            title = re.sub(r'\s*\([^)]*\)\s*', '', title)
            return self.clean_text(title).strip()
        
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            name = self.clean_text(h1.get_text())
            # Убираем текст в скобках
            name = re.sub(r'\s*\([^)]*\)\s*', '', name)
            return name.strip()
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем описание в HTML (b-recipe-info__content)
        content_div = self.soup.find('div', class_='b-recipe-info__content')
        if content_div:
            p = content_div.find('p')
            if p:
                text = p.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                # Берем только вторую часть после первой точки
                sentences = text.split('. ')
                if len(sentences) > 1:
                    # Берем второе предложение (основное описание)
                    description = sentences[1]
                    # Если в этом предложении есть еще точка или запятая перед "ale" или "но"
                    # убираем эту часть (она обычно о гарнирах)
                    if ', ale' in description or ', но' in description:
                        description = description.split(', ale')[0].split(', но')[0]
                    if not description.endswith('.'):
                        description += '.'
                    return description
                return text
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc_text = meta_desc['content']
            # Убираем "..." в конце
            desc_text = re.sub(r'…$', '', desc_text)
            # Берем вторую часть после точки
            sentences = desc_text.split('. ')
            if len(sentences) > 1:
                description = sentences[1]
                # Убираем часть после запятой с "ale"
                if ', ale' in description:
                    description = description.split(', ale')[0]
                if not description.endswith('.'):
                    description += '.'
                return self.clean_text(description)
            return self.clean_text(desc_text)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        Формат Czech: "500 g kuřecího masa", "1 lžíce sladké papriky"
        
        Returns:
            dict: {"name": "...", "amount": "...", "units": "..."}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).strip()
        
        # Пропускаем заголовки секций (они заканчиваются на ":")
        if text.endswith(':'):
            return None
        
        # Убираем скобки с пометками
        text = re.sub(r'\([^)]*\)', '', text)
        
        # Паттерн для чешских единиц измерения и количества
        # Примеры: "500 g kuřecího masa", "1-2 lžíce mouky", "200 ml smetany"
        pattern = r'^([\d\-.,/]+)?\s*(g|kg|ml|l|ks|kus|lžíce|lžíc|lžička|lžiček|tablespoon|tablespoons|teaspoon|hrnek|hrnky|hrnku|špetka|bunch)?\s*(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                amount = amount_str.strip()
            
            # Обработка единицы измерения
            if unit:
                unit = unit.strip().lower()
                # Нормализация единиц
                unit_mapping = {
                    'lžíc': 'tablespoons',
                    'lžíce': 'tablespoon',
                    'lžička': 'teaspoon',
                    'lžiček': 'teaspoon',
                    'hrnku': 'hrnku',
                    'hrnky': 'hrnky',
                }
                unit = unit_mapping.get(unit, unit)
            else:
                unit = None
            
            # Очистка названия
            name = name.strip() if name else text
            
            # Удаляем фразы типа "dle potřeby", "podle chuti"
            name = re.sub(r'\b(dle potřeby|podle chuti|nebo|nebo ke šlehání)\b', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\s+', ' ', name).strip()
            
            if not name or len(name) < 2:
                name = text
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        
        # Если паттерн не совпал, возвращаем как есть
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов в формате JSON строки
        Структура: [{"name": "...", "amount": "...", "units": "..."}]
        """
        ingredients = []
        
        # Пробуем получить из JSON-LD (самый надежный источник)
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeIngredient' in recipe_data:
            for ingredient_text in recipe_data['recipeIngredient']:
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
            
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)
        
        # Альтернативно - из HTML (если JSON-LD не сработал)
        ingredients_div = self.soup.find('div', id='ingredients')
        if ingredients_div:
            # Ищем все элементы ингредиентов
            ingredient_items = ingredients_div.find_all('p', class_='b-ingredients__item')
            
            for item in ingredient_items:
                # Получаем текст ингредиента
                text = item.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                
                if text:
                    parsed = self.parse_ingredient(text)
                    if parsed:
                        ingredients.append(parsed)
        
        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        instructions = []
        
        # Пробуем получить из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeInstructions' in recipe_data:
            recipe_instructions = recipe_data['recipeInstructions']
            
            if isinstance(recipe_instructions, list):
                for step in recipe_instructions:
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        if step_text:
                            instructions.append(step_text)
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        if step_text:
                            instructions.append(step_text)
            elif isinstance(recipe_instructions, str):
                instructions.append(self.clean_text(recipe_instructions))
            
            if instructions:
                return ' '.join(instructions)
        
        # Альтернативно - из HTML
        instructions_div = self.soup.find('div', class_='b-procedure')
        if instructions_div:
            # Ищем все шаги
            steps = instructions_div.find_all('div', class_='b-procedure__step')
            
            for step in steps:
                # Извлекаем текст шага
                step_text_div = step.find('div', class_='b-procedure__text')
                if step_text_div:
                    text = step_text_div.get_text(separator=' ', strip=True)
                    text = self.clean_text(text)
                    if text:
                        instructions.append(text)
        
        if instructions:
            return ' '.join(instructions)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            category_cleaned = self.clean_text(category)
            
            # Маппинг чешских категорий на английские
            category_mapping = {
                'drůbeží maso': 'Main Course',
                'kuřecí maso': 'Main Course',
                'hovězí maso': 'Main Course',
                'vepřové maso': 'Main Course',
                'ryby a mořské plody': 'Main Course',
                'moučníky': 'Dessert',
                'dezerty': 'Dessert',
                'předkrmy': 'Appetizer',
                'polévky': 'Soup',
                'saláty': 'Salad',
            }
            
            # Проверяем точное совпадение (case-insensitive)
            for cz_cat, en_cat in category_mapping.items():
                if category_cleaned.lower() == cz_cat.lower():
                    return en_cat
            
            # Если не нашли точного совпадения, проверяем частичное
            for cz_cat, en_cat in category_mapping.items():
                if cz_cat.lower() in category_cleaned.lower():
                    return en_cat
        
        # Ищем в breadcrumb
        breadcrumb_script = self.soup.find_all('script', type='application/ld+json')
        for script in breadcrumb_script:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'BreadcrumbList':
                    items = data.get('itemListElement', [])
                    # Берем предпоследний элемент (последний - это сам рецепт)
                    if len(items) >= 2:
                        category_item = items[-2]
                        category_name = category_item.get('item', {}).get('name', None)
                        if category_name:
                            return self.clean_text(category_name)
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return "Main Course"
    
    def _parse_iso_duration(self, duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT1H35M"
            
        Returns:
            Время в формате "X minutes"
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
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'prepTime' in recipe_data:
            return self._parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'cookTime' in recipe_data:
            return self._parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'totalTime' in recipe_data:
            return self._parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем последний шаг инструкций, который часто содержит заметку
        # В JSON-LD это обычно последний элемент recipeInstructions
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeInstructions' in recipe_data:
            recipe_instructions = recipe_data['recipeInstructions']
            
            if isinstance(recipe_instructions, list) and len(recipe_instructions) > 0:
                # Берем последний шаг
                last_step = recipe_instructions[-1]
                if isinstance(last_step, dict) and 'text' in last_step:
                    step_text = self.clean_text(last_step['text'])
                    # Проверяем, что этот шаг содержит заметку (упоминание о гарнире, подаче и т.д.)
                    note_keywords = ['příloha', 'podáv', 'tip', 'poznámk', 'hodí se', 'můžete', 
                                    'doporuč', 'varianta', 'hrnek =']
                    if any(keyword in step_text.lower() for keyword in note_keywords):
                        return step_text
        
        # Альтернативно - ищем в HTML в секции после инструкций
        procedure_div = self.soup.find('div', class_='b-procedure')
        if procedure_div:
            # Ищем последний шаг
            steps = procedure_div.find_all('div', class_='b-procedure__step')
            if steps:
                last_step = steps[-1]
                step_text_div = last_step.find('div', class_='b-procedure__text')
                if step_text_div:
                    text = step_text_div.get_text(separator=' ', strip=True)
                    text = self.clean_text(text)
                    # Проверяем, что это заметка
                    note_keywords = ['příloha', 'podáv', 'tip', 'poznámk', 'hodí se', 'můžete',
                                    'doporuč', 'varianta', 'hrnek =']
                    if any(keyword in text.lower() for keyword in note_keywords):
                        return text
        
        # Ищем секцию с заметками после инструкций
        tip_section = self.soup.find('div', class_=re.compile(r'tip|note|poznamk', re.I))
        if tip_section:
            text = tip_section.get_text(separator=' ', strip=True)
            return self.clean_text(text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Из JSON-LD keywords
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Разделяем по запятой
                tag_list = [tag.strip().lower() for tag in keywords.split(',') if tag.strip()]
                tags.extend(tag_list)
            elif isinstance(keywords, list):
                tags.extend([tag.lower() for tag in keywords if tag])
        
        if tags:
            return ', '.join(tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data:
            # Основное изображение
            if 'image' in recipe_data:
                img_data = recipe_data['image']
                if isinstance(img_data, dict) and 'url' in img_data:
                    urls.append(img_data['url'])
                elif isinstance(img_data, str):
                    urls.append(img_data)
            
            # Галерея изображений
            if 'hasPart' in recipe_data:
                has_part = recipe_data['hasPart']
                if isinstance(has_part, dict) and has_part.get('@type') == 'ImageGallery':
                    images = has_part.get('image', [])
                    if isinstance(images, list):
                        for img in images:
                            if isinstance(img, dict) and 'url' in img:
                                urls.append(img['url'])
                            elif isinstance(img, str):
                                urls.append(img)
        
        # Альтернативно - из meta og:image
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
    """
    Точка входа для обработки HTML файлов из preprocessed/toprecepty_cz
    """
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), 
        "preprocessed", 
        "toprecepty_cz"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка файлов из: {preprocessed_dir}")
        process_directory(TopreceptyExtractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python toprecepty_cz.py")


if __name__ == "__main__":
    main()
