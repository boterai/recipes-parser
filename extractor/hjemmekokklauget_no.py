"""
Экстрактор данных рецептов для сайта hjemmekokklauget.no
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class HjemmekokklaugetExtractor(BaseRecipeExtractor):
    """Экстрактор для hjemmekokklauget.no"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Извлекаем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # JSON-LD может быть списком
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            name = item.get('name')
                            if name:
                                return self.clean_text(name)
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    name = data.get('name')
                    if name:
                        return self.clean_text(name)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернатива - из мета-тегов
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Или из h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            desc = item.get('description')
                            if desc:
                                return self.clean_text(desc)
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    desc = data.get('description')
                    if desc:
                        return self.clean_text(desc)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернатива - из мета-тегов
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient_text(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            text: Строка вида "4 stk egg" или "200 gram hvetemel"
            
        Returns:
            dict: {"name": "egg", "amount": 4, "unit": "stk"} или None
        """
        if not text:
            return None
        
        # Чистим текст
        text = self.clean_text(text).strip()
        if not text:
            return None
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "4 stk egg", "200 gram hvetemel", "Kaldt vann"
        pattern = r'^([\d\s,./\-]+)?\s*(stk|gram|grams|g|kg|ml|dl|l|liter|ss|ts|kopper|kopper|zubchika|ст\.\s*ложки|шт\.|ts|ss)?\s*(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text.lower(),
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip().replace(',', '.')
            # Обрабатываем диапазоны типа "2-3" или "1-2"
            if '-' in amount_str:
                # Берем первое значение из диапазона
                amount_str = amount_str.split('-')[0].strip()
            try:
                # Пробуем преобразовать в число
                if '.' in amount_str:
                    amount = float(amount_str)
                else:
                    amount = int(amount_str)
            except ValueError:
                # Если не получилось, оставляем как строку
                amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы вроде "по вкусу", "til justering"
        name = re.sub(r'\b(по вкусу|til justering av konsistens|if needed|optional)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        name = name.lower()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из параграфов"""
        ingredients = []
        
        # Ищем все div с классом fusion-li-item-content
        # Ингредиенты находятся именно там, в виде простых <p> тегов
        fusion_items = self.soup.find_all('div', class_='fusion-li-item-content')
        
        # Паттерн для ингредиентов: начинается с числа или содержит единицы измерения
        # но НЕ содержит двоеточие (что отличает от метаданных типа "Kjøkken:")
        ingredient_pattern = r'^\d+.*\b(stk|gram|grams|g|kg|ml|dl|l|ss|ts|kopper|зубчика|ст\.\s*ложки|шт\.)\b'
        
        for item in fusion_items:
            text = item.get_text(strip=True)
            
            # Пропускаем элементы с двоеточием (метаданные)
            if ':' in text:
                continue
            
            # Пропускаем слишком длинные тексты (вероятно инструкции)
            # Ингредиенты обычно короче 80 символов
            if len(text) > 80:
                continue
            
            # Проверяем, похоже ли это на ингредиент
            if re.match(ingredient_pattern, text, re.IGNORECASE):
                parsed = self.parse_ingredient_text(text)
                if parsed and parsed['name']:
                    # Проверяем, что это не дубликат
                    if not any(ing['name'] == parsed['name'] for ing in ingredients):
                        ingredients.append(parsed)
            # Также добавляем ингредиенты без количества (например, "Kaldt vann")
            # Но только если они действительно короткие и содержат ключевые слова
            elif len(text) < 60 and any(word in text.lower() for word in 
                ['vann', 'salt', 'sukker', 'nori', 'wasabi', 'soyasaus', 'agurk', 'avokado', 'sesamfrø']):
                parsed = self.parse_ingredient_text(text)
                if parsed and parsed['name']:
                    if not any(ing['name'] == parsed['name'] for ing in ingredients):
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем в fusion-li-item-content - инструкции там длиннее ингредиентов
        fusion_items = self.soup.find_all('div', class_='fusion-li-item-content')
        
        for item in fusion_items:
            text = item.get_text(strip=True)
            
            # Пропускаем элементы с двоеточием (метаданные)
            if ':' in text:
                continue
            
            # Пропускаем короткие тексты (вероятно ингредиенты)
            if len(text) < 60:
                continue
            
            # Инструкции содержат глаголы действия
            if any(word in text.lower() for word in 
                ['bland', 'ha', 'kjør', 'pakk', 'kjevle', 'kok', 'steg', 'rør', 'skjær', 'hell', 
                 'bløtlegg', 'kast', 'mat', 'del', 'fortsett', 'skyll', 'skog', 'plasser', 'rull', 'вымойте', 'нарежьте']):
                # Очищаем текст
                cleaned = self.clean_text(text)
                # Убираем фразы типа "NB! har du..." и комментарии в предложениях
                cleaned = re.sub(r'\s*NB!.*?\.', '.', cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r'Har du.*?гangen\.', '', cleaned, flags=re.IGNORECASE)
                # Убираем лишние пробелы
                cleaned = re.sub(r'\s+', ' ', cleaned).strip()
                # Убираем двойные точки
                cleaned = re.sub(r'\.+', '.', cleaned)
                if cleaned and cleaned not in steps:
                    steps.append(cleaned)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в fusion-li-item-content divs
        fusion_items = self.soup.find_all('div', class_='fusion-li-item-content')
        
        for item in fusion_items:
            text = item.get_text(strip=True)
            # Ищем "Måltidstype:" или похожие маркеры
            if text.startswith('Måltidstype:'):
                # Извлекаем значение после двоеточия
                category = text.replace('Måltidstype:', '').strip()
                # Берем первое значение из списка (разделенного запятыми)
                if ',' in category:
                    category = category.split(',')[0].strip()
                return self.clean_text(category)
        
        # Альтернативно ищем в keywords из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            keywords = item.get('keywords', '')
                            if keywords:
                                # Берем первое ключевое слово
                                first_keyword = keywords.split(',')[0].strip()
                                if first_keyword:
                                    return self.clean_text(first_keyword)
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    keywords = data.get('keywords', '')
                    if keywords:
                        first_keyword = keywords.split(',')[0].strip()
                        if first_keyword:
                            return self.clean_text(first_keyword)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_time_from_text(self, text: str) -> Optional[str]:
        """Извлечение времени из текста"""
        if not text:
            return None
        
        # Ищем паттерны времени в тексте
        # Примеры: "10 minutter", "1 time", "2 timer", "1,5 timer"
        time_patterns = [
            r'(\d+(?:[,.]\d+)?)\s*(minutter|minutes|mins?)',
            r'(\d+(?:[,.]\d+)?)\s*(timer|hours?|hrs?)',
            r'(\d+)\s*-\s*(\d+)\s*(timer|hours?|minutter|minutes)',
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return self.clean_text(match.group(0))
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в fusion-li-item-content с префиксом "Forberedelser:"
        fusion_items = self.soup.find_all('div', class_='fusion-li-item-content')
        
        for item in fusion_items:
            text = item.get_text(strip=True)
            if text.startswith('Forberedelser:'):
                # Извлекаем значение после двоеточия
                time_str = text.replace('Forberedelser:', '').strip()
                # Нормализуем формат: "10 min" -> "10 minutes"
                time_str = re.sub(r'\b(\d+)\s*min\b', r'\1 minutes', time_str, flags=re.IGNORECASE)
                return self.clean_text(time_str)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в fusion-li-item-content с префиксом "Tilberedning:"
        fusion_items = self.soup.find_all('div', class_='fusion-li-item-content')
        
        for item in fusion_items:
            text = item.get_text(strip=True)
            if text.startswith('Tilberedning:'):
                # Извлекаем значение после двоеточия
                time_str = text.replace('Tilberedning:', '').strip()
                # Убираем комментарии в скобках
                time_str = re.sub(r'\([^)]*\)', '', time_str)
                # Нормализуем формат: "60 min" -> "60 minutes"
                time_str = re.sub(r'\b(\d+)\s*min\b', r'\1 minutes', time_str, flags=re.IGNORECASE)
                return self.clean_text(time_str)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в fusion-li-item-content с префиксом "Total tid:"
        fusion_items = self.soup.find_all('div', class_='fusion-li-item-content')
        
        for item in fusion_items:
            text = item.get_text(strip=True)
            if text.startswith('Total tid:'):
                # Извлекаем значение после двоеточия
                time_str = text.replace('Total tid:', '').strip()
                # Нормализуем формат: "70 min" -> "70 minutes"
                time_str = re.sub(r'\b(\d+)\s*min\b', r'\1 minutes', time_str, flags=re.IGNORECASE)
                return self.clean_text(time_str)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем текстовые блоки, которые начинаются с "NB!", "Husk", "Tips", etc.
        # Но избегаем включения их в инструкции
        fusion_texts = self.soup.find_all('div', class_=re.compile(r'fusion-text'))
        for div in fusion_texts:
            paragraphs = div.find_all('p')
            for p in paragraphs:
                text = p.get_text(strip=True)
                # Проверяем на маркеры заметок
                if any(text.lower().startswith(marker) for marker in 
                    ['nb!', 'husk', 'tips:', 'obs:', 'merk:', 'важно:', 'примечание:', 'note:']):
                    cleaned = self.clean_text(text)
                    # Убираем префикс "NB!" в начале
                    cleaned = re.sub(r'^NB!\s*', '', cleaned, flags=re.IGNORECASE)
                    if cleaned and cleaned not in notes:
                        notes.append(cleaned)
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в fusion-li-item-content с "Stikkord:"
        fusion_items = self.soup.find_all('div', class_='fusion-li-item-content')
        
        for item in fusion_items:
            text = item.get_text(strip=True)
            if text.startswith('Stikkord:'):
                # Извлекаем значение после двоеточия
                tags = text.replace('Stikkord:', '').strip()
                return self.clean_text(tags)
        
        # Альтернативно из JSON-LD keywords
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            keywords = item.get('keywords', '')
                            if keywords:
                                # Очищаем от лишних запятых и пробелов
                                keywords = re.sub(r'\s*,\s*', ', ', keywords)
                                return self.clean_text(keywords)
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    keywords = data.get('keywords', '')
                    if keywords:
                        keywords = re.sub(r'\s*,\s*', ', ', keywords)
                        return self.clean_text(keywords)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Извлекаем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            recipe_data = item
                            break
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    recipe_data = data
                
                if recipe_data and 'image' in recipe_data:
                    images = recipe_data['image']
                    if isinstance(images, list):
                        for img in images:
                            if isinstance(img, dict):
                                url = img.get('url')
                                if url:
                                    urls.append(url)
                            elif isinstance(img, str):
                                urls.append(img)
                    elif isinstance(images, dict):
                        url = images.get('url')
                        if url:
                            urls.append(url)
                    elif isinstance(images, str):
                        urls.append(images)
                    
                    if urls:
                        break
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Также проверяем мета-теги
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
            
            # Возвращаем как строку через запятую
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
    """Обработка HTML файлов из директории preprocessed/hjemmekokklauget_no"""
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join("preprocessed", "hjemmekokklauget_no")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(HjemmekokklaugetExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python hjemmekokklauget_no.py")


if __name__ == "__main__":
    main()
