"""
Экстрактор данных рецептов для сайта lamaistas.lt
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class LamaistasLtExtractor(BaseRecipeExtractor):
    """Экстрактор для lamaistas.lt"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'name' in data:
                    return self.clean_text(data['name'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Или из title
        title = self.soup.find('title')
        if title:
            title_text = title.get_text()
            # Убираем суффиксы типа " - receptas | La Maistas"
            title_text = re.sub(r'\s+-\s+receptas.*$', '', title_text, flags=re.IGNORECASE)
            return self.clean_text(title_text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из meta description (более короткое описание)
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            
            # Удаляем языковые пометки типа "(angl. overnight )"
            desc = re.sub(r'\s*\([^)]*angl\.[^)]*\)\s*', ' ', desc)
            desc = re.sub(r'\s+', ' ', desc).strip()
            
            # Разделяем на предложения
            sentences = re.split(r'\.(\s+|$)', desc)
            # Фильтруем пустые элементы и объединяем предложения
            actual_sentences = []
            for i in range(0, len(sentences), 2):
                if sentences[i].strip():
                    actual_sentences.append(sentences[i].strip())
            
            if actual_sentences:
                # Если первое предложение очень короткое (< 50 символов), берем два предложения
                if len(actual_sentences) > 1 and len(actual_sentences[0]) < 50:
                    return actual_sentences[0] + '. ' + actual_sentences[1] + '.'
                else:
                    # Иначе берем первое предложение
                    return actual_sentences[0] + '.'
        
        # Или из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = self.clean_text(og_desc['content'])
            desc = re.sub(r'\s*\([^)]*angl\.[^)]*\)\s*', ' ', desc)
            desc = re.sub(r'\s+', ' ', desc).strip()
            sentences = re.split(r'\.(\s+|$)', desc)
            actual_sentences = []
            for i in range(0, len(sentences), 2):
                if sentences[i].strip():
                    actual_sentences.append(sentences[i].strip())
            if actual_sentences:
                if len(actual_sentences) > 1 and len(actual_sentences[0]) < 50:
                    return actual_sentences[0] + '. ' + actual_sentences[1] + '.'
                else:
                    return actual_sentences[0] + '.'
        
        # Альтернативно - из JSON-LD (может быть длиннее)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'description' in data:
                    return self.clean_text(data['description'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def parse_ingredient_text(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "100 gramų avižinių dribsnių (paprastų, ne greito paruošimo)"
            
        Returns:
            dict: {"name": "avižinių dribsnių", "amount": "100", "unit": "gramų"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Удаляем скобки с содержимым (дополнительные пояснения)
        text_without_notes = re.sub(r'\([^)]*\)', '', text).strip()
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "100 gramų avižinių dribsnių", "2 šaukštai citrinų sulčių", "1 žiupsnelis druskos"
        pattern = r'^([\d\s/.,]+)?\s*(gramų|mililitrų|šaukštai|šaukštas|šaukštelis|šaukštelio|žiupsnelis|riekės|lapai|vienetai|vienetas)?\s*(.+)'
        
        match = re.match(pattern, text_without_notes, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text_without_notes,
                "units": None,
                "amount": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2" или "0.5"
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
                amount_str = amount_str.replace(',', '.')
                try:
                    amount = float(amount_str) if '.' in amount_str else int(amount_str)
                except ValueError:
                    amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        name = name.strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "units": unit,
            "amount": amount
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD"""
        ingredients = []
        
        # Сначала пробуем извлечь из JSON-LD (самый надежный способ для структурированных данных)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if data.get('@type') == 'Recipe' and 'recipeIngredient' in data:
                    recipe_ingredients = data['recipeIngredient']
                    
                    for ingredient_text in recipe_ingredients:
                        # Парсим каждый ингредиент в структурированный формат
                        parsed = self.parse_ingredient_text(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
                    
                    if ingredients:
                        return json.dumps(ingredients, ensure_ascii=False)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        # Пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if data.get('@type') == 'Recipe' and 'recipeInstructions' in data:
                    instructions_text = data['recipeInstructions']
                    
                    # Очищаем HTML entities и теги
                    import html
                    instructions_text = html.unescape(instructions_text)
                    instructions_text = re.sub(r'<[^>]+>', '', instructions_text)
                    instructions_text = self.clean_text(instructions_text)
                    
                    # Разделяем на шаги
                    # Шаги разделены числами с точками, например: "1.текст2.текст3.текст"
                    steps = re.split(r'(?<=\.)(?=\d+\.)', instructions_text)
                    
                    # Добавляем пробелы после номеров шагов, если их нет
                    formatted_steps = []
                    for step in steps:
                        step = step.strip()
                        if step:
                            # Проверяем, есть ли уже пробел после номера
                            step = re.sub(r'^(\d+\.)(?!\s)', r'\1 ', step)
                            formatted_steps.append(step)
                    
                    return ' '.join(formatted_steps) if formatted_steps else instructions_text
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности (может отсутствовать на этом сайте)"""
        # На lamaistas.lt обычно нет информации о питательности
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'recipeCategory' in data:
                    category = data['recipeCategory']
                    # Может быть строка с несколькими категориями через запятую
                    if isinstance(category, str):
                        categories = [cat.strip() for cat in category.split(',')]
                        
                        # Приоритет категорий:
                        # 1. Desertai (десерты) - возвращаем Dessert
                        for cat in categories:
                            if 'desert' in cat.lower():
                                return 'Dessert'
                        
                        # 2. Специфичные категории блюд
                        for cat in categories:
                            cat_lower = cat.lower()
                            if 'sumuštin' in cat_lower:
                                return 'Sumuštiniai'
                            elif 'košė' in cat_lower or 'košė' in cat_lower:
                                # Košės (porridge) обычно pusryčiai (breakfast)
                                return 'Pusryčiai'
                            elif 'sriuba' in cat_lower or 'sriubo' in cat_lower:
                                return 'Soup'
                            elif 'salot' in cat_lower:
                                return 'Salad'
                        
                        # 3. Pusryčiai (breakfast) как fallback
                        for cat in categories:
                            if 'pusryč' in cat.lower():
                                return 'Pusryčiai'
                        
                        # 4. Если ничего не нашли, берем вторую категорию если есть
                        if len(categories) >= 2:
                            second_cat = categories[1].strip()
                            if second_cat:
                                return second_cat[0].upper() + second_cat[1:]
                        
                        # 5. Иначе первую
                        if categories:
                            first_cat = categories[0].strip()
                            if first_cat:
                                return first_cat[0].upper() + first_cat[1:]
                    
                    return category
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def parse_iso_duration(self, duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT30M" или "PT1H30M"
            
        Returns:
            Время в формате "30 minutes" или "1 hour 30 minutes"
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
        if hours > 0 and minutes > 0:
            return f"{hours * 60 + minutes} minutes"
        elif hours > 0:
            return f"{hours * 60} minutes"
        elif minutes > 0:
            return f"{minutes} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На lamaistas.lt totalTime используется как prep_time
        return self.extract_total_time()
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления (может отсутствовать на этом сайте)"""
        # На lamaistas.lt обычно есть только totalTime
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени (внутренний метод для получения времени из JSON-LD)"""
        # Пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'totalTime' in data:
                    iso_time = data['totalTime']
                    return self.parse_iso_duration(iso_time)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок (может отсутствовать на этом сайте)"""
        # На lamaistas.lt обычно нет отдельных заметок
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Ищем секцию с ключевыми словами (Raktažodžiai)
        guidelines_segment = self.soup.find('div', class_='guidelinesSegment')
        
        if guidelines_segment:
            # Извлекаем все ссылки в этой секции
            links = guidelines_segment.find_all('a')
            for link in links:
                tag_text = link.get_text(strip=True)
                if tag_text:
                    tags_list.append(self.clean_text(tag_text))
        
        # Возвращаем как строку через запятую
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if data.get('@type') == 'Recipe' and 'image' in data:
                    img = data['image']
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
        # Get time from JSON-LD once
        time_value = self.extract_total_time()
        
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_instructions(),
            "nutrition_info": self.extract_nutrition_info(),
            "category": self.extract_category(),
            "prep_time": time_value,  # Используем totalTime как prep_time
            "cook_time": self.extract_cook_time(),
            "total_time": time_value,  # И также как total_time
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # Обрабатываем директорию preprocessed/lamaistas_lt
    preprocessed_dir = os.path.join("preprocessed", "lamaistas_lt")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(LamaistasLtExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python lamaistas_lt.py")


if __name__ == "__main__":
    main()
