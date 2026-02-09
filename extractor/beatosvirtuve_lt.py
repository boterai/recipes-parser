"""
Экстрактор данных рецептов для сайта beatosvirtuve.lt
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class BeatosvirtuveLtExtractor(BaseRecipeExtractor):
    """Экстрактор для beatosvirtuve.lt"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'name' in data:
                    return self.clean_text(data['name'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем извлечь из специального блока recipe--text
        recipe_text = self.soup.find('div', class_='recipe--text')
        if recipe_text:
            p = recipe_text.find('p')
            if p:
                full_text = self.clean_text(p.get_text(strip=True))
                # Разделяем на предложения и берем первые 1-2 предложения как описание
                sentences = re.split(r'(?<=[.!?])\s+', full_text)
                if len(sentences) >= 2:
                    # Берем первые 2 предложения
                    return ' '.join(sentences[:2])
                elif sentences:
                    return sentences[0]
        
        # Альтернативно - из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'description' in data:
                    return self.clean_text(data['description'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient_from_text(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "800 g kiaulienos nugarinės" или "2 svogūnų"
            
        Returns:
            dict: {"name": "...", "amount": ..., "units": "..."} или None
        """
        if not ingredient_text:
            return None
        
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "800 g kiaulienos", "2 svogūnų", "1 šaukšto balzaminio acto"
        # Ищем число (может быть с дробной частью), затем опциональную единицу, затем название
        
        # Словарь для преобразования литовских единиц в стандартные английские
        unit_mapping = {
            'g': 'g',
            'kg': 'kg',
            'ml': 'ml',
            'l': 'liters',
            'šaukšto': 'tablespoon',
            'šaukštų': 'tablespoons',
            'šaukštas': 'tablespoon',
            'arbatinio šaukštelio': 'teaspoon',
            'arbatinių šaukštelių': 'teaspoons',
            'arbatinis šaukštelis': 'teaspoon',
            'saujos': 'handful',
            'saują': 'handful',
            'riekių': 'slices',
            'riekelių': 'slices',
            'riekė': 'slice',
            'gabalėlių': 'pieces',
            'gabalėlis': 'piece',
            'vnt': 'pcs',
            'vnt.': 'pcs',
        }
        
        # Попытка извлечь количество в начале строки
        # Паттерн: число (может быть с дробью типа 0.5 или 1-1,5) + опциональная единица
        pattern = r'^([\d,./-]+)\s*([a-zščžąęėįųū]+\.?)?\s*(.+)$'
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                # Нормализуем: заменяем запятую на точку, обрабатываем диапазоны
                amount_str = amount_str.strip()
                # Если это диапазон (например, "1-1.5" или "2-3"), берем среднее или максимум
                if '-' in amount_str:
                    parts = amount_str.split('-')
                    try:
                        # Берем максимальное значение из диапазона
                        amount = max([float(p.replace(',', '.')) for p in parts])
                    except ValueError:
                        amount = amount_str
                else:
                    try:
                        amount = float(amount_str.replace(',', '.'))
                    except ValueError:
                        amount = amount_str
            
            # Обработка единицы измерения
            unit_normalized = None
            if unit:
                unit = unit.strip().lower()
                unit_normalized = unit_mapping.get(unit, unit)
            
            # Очистка названия
            name = name.strip() if name else text
            
            return {
                "name": name,
                "amount": amount,
                "units": unit_normalized
            }
        
        # Если паттерн не совпал, возвращаем только название
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате JSON"""
        ingredients = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'recipeIngredient' in data:
                    recipe_ingredients = data['recipeIngredient']
                    if isinstance(recipe_ingredients, list):
                        for ingredient_text in recipe_ingredients:
                            if isinstance(ingredient_text, str):
                                parsed = self.parse_ingredient_from_text(ingredient_text)
                                if parsed:
                                    ingredients.append(parsed)
                    
                    if ingredients:
                        return json.dumps(ingredients, ensure_ascii=False)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, ищем в HTML
        # Ищем ul или ol с ингредиентами
        ingredient_lists = self.soup.find_all(['ul', 'ol'], class_=re.compile(r'ingredient', re.I))
        
        for ingredient_list in ingredient_lists:
            items = ingredient_list.find_all('li')
            for item in items:
                ingredient_text = item.get_text(separator=' ', strip=True)
                parsed = self.parse_ingredient_from_text(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
            
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        steps = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'recipeInstructions' in data:
                    instructions = data['recipeInstructions']
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
                        # Объединяем все шаги в одну строку
                        return ' '.join(steps)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, ищем в HTML
        instructions_list = self.soup.find('ol', class_=re.compile(r'instruction', re.I))
        if not instructions_list:
            instructions_list = self.soup.find('div', class_=re.compile(r'instruction', re.I))
        
        if instructions_list:
            items = instructions_list.find_all('li')
            if not items:
                items = instructions_list.find_all('p')
            
            for item in items:
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                if step_text:
                    steps.append(step_text)
            
            if steps:
                return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'recipeCategory' in data:
                    return self.clean_text(data['recipeCategory'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'prepTime' in data:
                    # Преобразуем ISO duration в понятный формат
                    iso_time = data['prepTime']
                    return self.parse_iso_duration(iso_time)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe':
                    # Проверяем разные возможные поля
                    if 'cookTime' in data:
                        iso_time = data['cookTime']
                        return self.parse_iso_duration(iso_time)
                    elif 'totalTime' in data:
                        # Иногда общее время указано вместо времени готовки
                        iso_time = data['totalTime']
                        return self.parse_iso_duration(iso_time)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если не нашли в JSON-LD, пробуем извлечь из текста инструкций
        # Ищем паттерны типа "45 minutes", "1 hour", "30 минут" и т.д.
        instructions_text = self.extract_instructions()
        if instructions_text:
            # Паттерн для поиска времени
            time_pattern = r'(?:apie\s+)?(\d+)\s*(minut|minutes?|hours?|valand)'
            match = re.search(time_pattern, instructions_text, re.IGNORECASE)
            if match:
                number = match.group(1)
                unit = match.group(2).lower()
                if 'minut' in unit:
                    return f"{number} minutes"
                elif 'hour' in unit or 'valand' in unit:
                    return f"{number} hours"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
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
    
    def parse_iso_duration(self, duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты или человеко-читаемый формат
        
        Args:
            duration: строка вида "PT45M" или "PT1H30M"
            
        Returns:
            Время в формате "45 minutes" или None
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
            return f"{hours} hours {minutes} minutes"
        elif hours > 0:
            return f"{hours} hours"
        elif minutes > 0:
            return f"{minutes} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Сначала ищем в специальном блоке recipe--text
        # Обычно последнее предложение содержит советы или примечания
        recipe_text = self.soup.find('div', class_='recipe--text')
        if recipe_text:
            p = recipe_text.find('p')
            if p:
                full_text = self.clean_text(p.get_text(strip=True))
                # Разделяем на предложения
                sentences = re.split(r'(?<=[.!?…])\s+', full_text)
                if len(sentences) > 2:
                    # Берем последнее предложение как заметку, если оно начинается с определенных слов
                    last_sentence = sentences[-1].strip()
                    # Проверяем, похоже ли это на совет/примечание
                    note_indicators = ['prie', 'tik', 'svarbu', 'patarimas', 'galima', 'nebūtinai', 'rekomenduoju']
                    if any(last_sentence.lower().startswith(ind) for ind in note_indicators):
                        return last_sentence
                    # Или если предпоследнее предложение - совет
                    if len(sentences) > 1:
                        penultimate = sentences[-2].strip()
                        if any(penultimate.lower().startswith(ind) for ind in note_indicators):
                            return penultimate
        
        # Пробуем найти в JSON-LD (если есть дополнительные поля)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe':
                    # Проверяем возможные поля с заметками
                    if 'recipeNotes' in data:
                        return self.clean_text(data['recipeNotes'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в HTML специфичные секции для заметок
        notes_section = self.soup.find(class_=re.compile(r'note|tip|advice', re.I))
        if notes_section:
            text = notes_section.get_text(separator=' ', strip=True)
            return self.clean_text(text) if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта"""
        # Пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'keywords' in data:
                    keywords = data['keywords']
                    if isinstance(keywords, str):
                        return self.clean_text(keywords)
                    elif isinstance(keywords, list):
                        return ', '.join([self.clean_text(k) for k in keywords if k])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в meta-тегах
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Пробуем извлечь из JSON-LD
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
    """Точка входа для обработки директории с HTML-файлами"""
    import os
    
    # Путь к директории с HTML-файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "preprocessed",
        "beatosvirtuve_lt"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(BeatosvirtuveLtExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python beatosvirtuve_lt.py")


if __name__ == "__main__":
    main()
