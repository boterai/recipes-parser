"""
Экстрактор данных рецептов для сайта arla.dk
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ArlaDkExtractor(BaseRecipeExtractor):
    """Экстрактор для arla.dk"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Данные могут быть списком или словарем
                if isinstance(data, list):
                    # Ищем Recipe в списке
                    for item in data:
                        if isinstance(item, dict):
                            item_type = item.get('@type', '')
                            if isinstance(item_type, list) and 'Recipe' in item_type:
                                return item
                            elif item_type == 'Recipe':
                                return item
                elif isinstance(data, dict):
                    item_type = data.get('@type', '')
                    if isinstance(item_type, list) and 'Recipe' in item_type:
                        return data
                    elif item_type == 'Recipe':
                        return data
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "20 minutes" или "1 hour 30 minutes"
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
        
        # Если общее время 0, возвращаем None
        if hours == 0 and minutes == 0:
            return None
        
        # Форматируем результат
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s+-\s+.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'description' in json_ld:
            description = json_ld['description']
            # Удаляем фразы типа "Enkelt og godt!" и советы по подаче
            # Разделяем по предложениям
            sentences = re.split(r'(?<=[.!?])\s+', description)
            
            # Фильтруем предложения
            description_sentences = []
            for sent in sentences:
                sent_lower = sent.lower()
                # Пропускаем короткие восклицательные фразы и советы
                if sent.strip() in ['Enkelt og godt!', 'Enkelt og godt']:
                    continue
                # Если предложение содержит совет, прекращаем
                if any(word in sent_lower for word in ['server', 'servér']) or \
                   ('evt.' in sent_lower and any(w in sent_lower for w in ['salat', 'buffet', 'picnic'])):
                    break
                description_sentences.append(sent)
            
            if description_sentences:
                description = ' '.join(description_sentences)
            
            return self.clean_text(description)
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "120 g hvedemel (ca. 2 dl)"
            
        Returns:
            dict: {"name": "Hvedemel", "units": "g", "amount": 120} или None
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
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "120 g hvedemel", "½ tsk groft salt", "3 æg"
        pattern = r'^([\d\s/.,]+)?\s*(g|kg|ml|l|dl|tsk|spsk|tsp|tbsp|pcs|stk|liter)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text.capitalize(),
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
                        total += float(part)
                amount = int(total) if total == int(total) else total
            else:
                try:
                    val = float(amount_str.replace(',', '.'))
                    amount = int(val) if val == int(val) else val
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        # Capitalize first letter
        if name:
            name = name[0].upper() + name[1:] if len(name) > 1 else name.upper()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "units": unit,
            "amount": amount
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeIngredient' in json_ld:
            ingredients = []
            for ingredient_text in json_ld['recipeIngredient']:
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
            
            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
        
        return None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeInstructions' in json_ld:
            steps = []
            instructions = json_ld['recipeInstructions']
            
            if isinstance(instructions, list):
                for item in instructions:
                    if isinstance(item, dict):
                        # Может быть HowToSection с itemListElement
                        if item.get('@type') == 'HowToSection' and 'itemListElement' in item:
                            for step in item['itemListElement']:
                                if isinstance(step, dict) and 'text' in step:
                                    steps.append(step['text'])
                        # Или просто HowToStep с text
                        elif 'text' in item:
                            steps.append(item['text'])
                    elif isinstance(item, str):
                        steps.append(item)
            elif isinstance(instructions, str):
                steps.append(instructions)
            
            if steps:
                # Объединяем все шаги в одну строку
                return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Пробуем извлечь recipeMealType из gtmData
        scripts = self.soup.find_all('script')
        for script in scripts:
            if script.string and 'recipeMealType' in script.string:
                match = re.search(r'"recipeMealType"\s*:\s*"([^"]+)"', script.string)
                if match:
                    meal_type = match.group(1)
                    # Мапим на стандартные категории
                    meal_type_lower = meal_type.lower()
                    if any(word in meal_type_lower for word in ['frokost', 'madpakke', 'hovedret', 'aftensmad']):
                        return "Main Course"
                    elif any(word in meal_type_lower for word in ['dessert', 'kage', 'bagværk']):
                        return "Dessert"
                    elif any(word in meal_type_lower for word in ['forret', 'snack']):
                        return "Appetizer"
                    # Если не удалось сопоставить, возвращаем None
                    return None
        
        # Альтернативно из JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'recipeCategory' in json_ld:
            category = json_ld['recipeCategory']
            if isinstance(category, list):
                return ', '.join(category)
            return self.clean_text(str(category))
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_data()
        
        # Сначала пробуем из JSON-LD
        if json_ld and 'cookTime' in json_ld:
            cook_time = self.parse_iso_duration(json_ld['cookTime'])
            if cook_time:
                return cook_time
        
        # Если в JSON-LD нет времени готовки (или оно 0), ищем в инструкциях
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            # Ищем упоминания времени вида "ca. 35 min" или "i ca. 35 min"
            # Нам нужно последнее время выпекания (основное, не предварительное)
            time_pattern = r'(?:ca\.|i ca\.)\s*(\d+)\s*min'
            cooking_times = []
            
            if isinstance(instructions, list):
                for item in instructions:
                    if isinstance(item, dict):
                        if item.get('@type') == 'HowToSection' and 'itemListElement' in item:
                            for step in item['itemListElement']:
                                if isinstance(step, dict) and 'text' in step:
                                    # Ищем шаги с выпеканием
                                    if 'bag' in step['text'].lower():
                                        match = re.search(time_pattern, step['text'], re.IGNORECASE)
                                        if match:
                                            minutes = int(match.group(1))
                                            # Пропускаем время предварительной выпечки (обычно < 20 мин)
                                            # и берем основное время
                                            cooking_times.append(minutes)
                        elif 'text' in item:
                            if 'bag' in item['text'].lower():
                                match = re.search(time_pattern, item['text'], re.IGNORECASE)
                                if match:
                                    minutes = int(match.group(1))
                                    cooking_times.append(minutes)
            
            # Берем максимальное время (основная выпечка обычно дольше предварительной)
            if cooking_times:
                max_time = max(cooking_times)
                return f"{max_time} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        json_ld = self._get_json_ld_data()
        
        # Берем заметки из описания, если они есть после основного текста
        if json_ld and 'description' in json_ld:
            description = json_ld['description']
            # Разделяем по предложениям (с сохранением знаков препинания)
            sentences = re.split(r'(?<=[.!?])\s+', description)
            
            # Ищем предложения с советами
            note_sentences = []
            for sent in sentences:
                sent_lower = sent.lower()
                if any(word in sent_lower for word in ['server', 'servér', 'kan', 'tip', 'i stedet', 'evt.', 'buffet', 'picnic']):
                    note_sentences.append(sent)
            
            if note_sentences:
                return self.clean_text(' '.join(note_sentences))
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Словарь для перевода датских тегов на английский
        translation_map = {
            'vegetar': 'vegetarian',
            'grøntsager': 'vegetables',
            'broccoli': 'broccoli',
            'tærter': 'tart',
            'madtærter': 'tart',
            'æg': 'egg',
            'porrer': 'leek',
            'vegetarisk': 'vegetarian',
            'hovedret': 'main course',
            'kød': 'meat',
            'fisk': 'fish',
            'fjerkræ': 'poultry'
        }
        
        # Извлекаем из gtmData (recipeMainIngredient и recipeType)
        scripts = self.soup.find_all('script')
        for script in scripts:
            if script.string and 'recipeMainIngredient' in script.string:
                # Извлекаем recipeMainIngredient
                match = re.search(r'"recipeMainIngredient"\s*:\s*"([^"]+)"', script.string)
                if match:
                    ingredients = match.group(1).split(', ')
                    for ing in ingredients:
                        ing_lower = ing.strip().lower()
                        if ing_lower in translation_map:
                            tags.append(translation_map[ing_lower])
                        else:
                            tags.append(ing_lower)
                
                # Извлекаем recipeType
                match = re.search(r'"recipeType"\s*:\s*"([^"]+)"', script.string)
                if match:
                    types = match.group(1).split(', ')
                    for t in types:
                        t_lower = t.strip().lower()
                        if t_lower in translation_map:
                            if translation_map[t_lower] not in tags:
                                tags.append(translation_map[t_lower])
                        elif t_lower not in tags:
                            tags.append(t_lower)
                
                break
        
        # Если не нашли в gtmData, пробуем из JSON-LD
        if not tags:
            json_ld = self._get_json_ld_data()
            if json_ld and 'keywords' in json_ld:
                keywords = json_ld['keywords']
                if isinstance(keywords, str):
                    return keywords.lower()
                elif isinstance(keywords, list):
                    tags = [k.lower() for k in keywords]
        
        if tags:
            # Убираем дубликаты, сохраняя порядок
            seen = set()
            unique_tags = []
            for tag in tags:
                if tag not in seen:
                    seen.add(tag)
                    unique_tags.append(tag)
            return ', '.join(unique_tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
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
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_steps(),
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
    Обрабатывает все HTML файлы из директории preprocessed/arla_dk
    """
    import os
    
    # По умолчанию обрабатываем папку preprocessed/arla_dk
    recipes_dir = os.path.join("preprocessed", "arla_dk")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(ArlaDkExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python arla_dk.py")


if __name__ == "__main__":
    main()
