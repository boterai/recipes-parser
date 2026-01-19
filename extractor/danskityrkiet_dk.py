"""
Экстрактор данных рецептов для сайта danskityrkiet.dk
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class DanskiTyrkietExtractor(BaseRecipeExtractor):
    """Экстрактор для danskityrkiet.dk"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке страницы
        title = self.soup.find('title')
        if title:
            title_text = title.get_text()
            # Удаляем суффиксы типа " - Dansk i Tyrkiet", " opskrift"
            title_text = re.sub(r'\s*-\s*Dansk i Tyrkiet.*$', '', title_text, flags=re.IGNORECASE)
            title_text = re.sub(r'\s+opskrift.*$', '', title_text, flags=re.IGNORECASE)
            return self.clean_text(title_text)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title_text = og_title['content']
            title_text = re.sub(r'\s*-\s*Dansk i Tyrkiet.*$', '', title_text, flags=re.IGNORECASE)
            title_text = re.sub(r'\s+opskrift.*$', '', title_text, flags=re.IGNORECASE)
            return self.clean_text(title_text)
        
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
        """Извлечение ингредиентов в формате JSON"""
        ingredients = []
        
        # Ищем entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Находим параграфы между "Ingredienser" и "Fremgangsmåde"
        all_paragraphs = entry_content.find_all('p')
        
        # Сначала пробуем найти секцию с заголовком "Ingredienser"
        in_ingredients_section = False
        found_ingredients_header = False
        
        for p in all_paragraphs:
            text = p.get_text(strip=True)
            
            # Проверяем начало секции ингредиентов
            if text.lower() == 'ingredienser' or (p.find(['strong', 'b']) and 'ingredienser' in text.lower()):
                in_ingredients_section = True
                found_ingredients_header = True
                continue
            
            # Проверяем конец секции ингредиентов
            if in_ingredients_section and (text.lower() == 'fremgangsmåde' or 
                                          (p.find(['strong', 'b']) and 'fremgangsmåde' in text.lower())):
                break
            
            # Если мы в секции ингредиентов, парсим ингредиент
            if in_ingredients_section and text:
                parsed = self.parse_ingredient(text)
                if parsed:
                    ingredients.append(parsed)
        
        # Если не нашли секцию с заголовком, пытаемся найти ингредиенты по паттерну
        if not found_ingredients_header or not ingredients:
            # Ищем параграфы, которые выглядят как ингредиенты
            # (короткие строки, начинающиеся с чисел или содержащие единицы измерения)
            ingredient_pattern = re.compile(r'^\d+.*?(gram|ml|dl|tsk|spsk|bundt|stykker|større|håndfuld|æg|kartofler|løg|spiseskefulde)', re.IGNORECASE)
            
            for i, p in enumerate(all_paragraphs):
                text = p.get_text(strip=True)
                
                # Пропускаем длинные параграфы (вероятно, инструкции или описание)
                if len(text) > 150:
                    continue
                
                # Пропускаем нумерованные инструкции (начинаются с "1.", "2.", и т.д.)
                if re.match(r'^\d+\.\s+', text):
                    continue
                
                # Проверяем, подходит ли под паттерн ингредиента
                if ingredient_pattern.search(text):
                    parsed = self.parse_ingredient(text)
                    if parsed and parsed.get('name'):
                        # Проверяем, что это не дубликат
                        if not any(ing['name'] == parsed['name'] for ing in ingredients):
                            ingredients.append(parsed)
                
                # Также проверяем паттерн "Salt og peber"
                elif len(text) < 50 and any(word in text.lower() for word in ['salt', 'peber', 'olie', 'smør', 'mel', 'vand', 'sukker']):
                    parsed = self.parse_ingredient(text)
                    if parsed and parsed.get('name'):
                        if not any(ing['name'] == parsed['name'] for ing in ingredients):
                            ingredients.append(parsed)
        
        # Если ингредиенты все еще не найдены, ищем упоминания в тексте с количествами
        # Например: "1,5-2 spiseskefulde te"
        if not ingredients:
            for p in all_paragraphs:
                text = p.get_text(strip=True)
                # Ищем паттерны типа "X spiseskefulde Y" в тексте
                matches = re.findall(r'([\d,.\-]+)\s+(spiseskefulde|gram|ml|dl|tsk|spsk)\s+(\w+)', text, re.IGNORECASE)
                for match in matches:
                    amount, unit, name = match
                    ingredients.append({
                        "name": name,
                        "amount": amount.replace(',', '.'),
                        "units": unit
                    })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "500 gram fetaost" или "1 bundt bredbladet persille"
            
        Returns:
            dict: {"name": "fetaost", "amount": "500", "units": "gram"} или None
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
        # Примеры: "500 gram fetaost", "1 bundt persille", "3 æg"
        # Датские единицы: gram, ml, dl, tsk (чайная ложка), spsk (столовая ложка), bundt (пучок), stykker (штуки)
        pattern = r'^([\d\s/.,\-]+)?\s*(gram|ml|dl|liter|tsk|spsk|spiseskefulde|bundt|bundte|stykker|større|håndfuld|håndfulde|kg|g|l)?\.?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, units, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2" или "1 1/2" и диапазонов "1-2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                amount = str(total)
            else:
                # Просто сохраняем как есть (может быть "1.5-2" или "8-10")
                amount = amount_str.replace(',', '.')
        
        # Обработка единицы измерения
        units = units.strip() if units else None
        
        # Очистка названия
        # Удаляем фразы в скобках
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы типа "til pensling", "eller filodej"
        name = re.sub(r'\btil\s+pensling\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        
        # Удаляем leading слова типа "bløde", "store" если они перед основным названием
        # Но сохраняем их если они важны
        if name.startswith('bløde '):
            name = name.replace('bløde ', '', 1)
        elif name.startswith('store '):
            # Для "store kartofler" оставляем как "større" в units
            if not units:
                units = 'større'
            name = name.replace('store ', '', 1)
        elif name.startswith('stor '):
            if not units:
                units = 'stor'
            name = name.replace('stor ', '', 1)
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions = []
        
        # Ищем entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Находим параграфы после "Fremgangsmåde"
        all_paragraphs = entry_content.find_all('p')
        
        in_instructions_section = False
        found_instructions_header = False
        
        for p in all_paragraphs:
            text = p.get_text(strip=True)
            
            # Проверяем начало секции инструкций
            if text.lower() == 'fremgangsmåde' or (p.find(['strong', 'b']) and 'fremgangsmåde' in text.lower()):
                in_instructions_section = True
                found_instructions_header = True
                continue
            
            # Если мы в секции инструкций, добавляем текст
            if in_instructions_section and text:
                # Пропускаем заголовки (содержат только bold текст и короткие)
                if p.find(['strong', 'b']) and len(text) < 40:
                    continue
                
                # Очищаем текст
                clean = self.clean_text(text)
                if clean:
                    instructions.append(clean)
        
        # Если не нашли секцию с заголовком, ищем параграфы, которые выглядят как инструкции
        if not found_instructions_header or not instructions:
            # Ищем нумерованные шаги (1. ... 2. ... 3. ...)
            numbered_steps = []
            for p in all_paragraphs:
                text = p.get_text(strip=True)
                # Проверяем, начинается ли с номера
                if re.match(r'^\d+\.\s+', text):
                    # Убираем номер
                    clean_text = re.sub(r'^\d+\.\s+', '', text)
                    clean = self.clean_text(clean_text)
                    if clean and len(clean) > 20:  # Достаточно длинный, чтобы быть инструкцией
                        numbered_steps.append(clean)
            
            if numbered_steps:
                # Добавляем номера обратно для единообразия
                for i, step in enumerate(numbered_steps, 1):
                    instructions.append(f"{i}. {step}")
            else:
                # Ищем параграфы, которые начинаются с глаголов действия
                instruction_starters = [
                    'start med', 'bland', 'hæld', 'bag', 'server', 'riv', 'skræl',
                    'kom', 'pensl', 'pisk', 'fordel', 'fyld', 'læg', 'sæt', 'putte',
                    'kør', 'skru', 'tag'
                ]
                
                for p in all_paragraphs:
                    text = p.get_text(strip=True)
                    
                    # Пропускаем короткие строки (вероятно, ингредиенты)
                    if len(text) < 50:
                        continue
                    
                    # Проверяем, начинается ли с глагола действия
                    text_lower = text.lower()
                    if any(text_lower.startswith(starter) for starter in instruction_starters):
                        clean = self.clean_text(text)
                        if clean and clean not in instructions:
                            instructions.append(clean)
        
        if not instructions:
            return None
        
        # Объединяем все инструкции в одну строку
        return ' '.join(instructions)
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Проверяем, есть ли в тексте упоминания категорий
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            text = entry_content.get_text().lower()
            # Проверяем ключевые слова для определения категории
            if any(word in text for word in ['hovedret', 'main course', 'main dish']):
                return 'Main Course'
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем информацию о времени в entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем параграфы с информацией о времени
        # Обычно формат: "(6-8 personer, 75 minutter)"
        all_paragraphs = entry_content.find_all('p')
        
        for p in all_paragraphs:
            text = p.get_text(strip=True)
            # Ищем паттерн с минутами в скобках
            match = re.search(r'\(.*?(\d+)\s*minutter?\)', text, re.IGNORECASE)
            if match:
                minutes = match.group(1)
                return f"{minutes} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем упоминания времени приготовления в инструкциях
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        text = entry_content.get_text()
        
        # Ищем паттерны типа "i 20 minutter", "ca. 10-15 min"
        patterns = [
            r'i\s+(\d+(?:-\d+)?)\s*minutter?',
            r'ca\.?\s+(\d+(?:-\d+)?)\s*min',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                time_value = match.group(1)
                return f"{time_value} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # На этом сайте total_time обычно не указывается отдельно
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем параграфы с "OBS!" или "Bemærk" или "TIP:"
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        all_paragraphs = entry_content.find_all('p')
        
        for p in all_paragraphs:
            text = p.get_text(strip=True)
            
            # Проверяем, начинается ли с "OBS!", "Bemærk" или "TIP:"
            if text.startswith('OBS!') or text.startswith('Bemærk') or text.startswith('TIP:'):
                # Убираем префиксы
                text = re.sub(r'^(OBS!|TIP:)', '', text)
                text = re.sub(r'^Bemærk\s+at\s+', '', text, flags=re.IGNORECASE)
                text = self.clean_text(text)
                return text if text else None
        
        # Ищем параграфы, которые явно являются советами (короткие с "kan også")
        for p in all_paragraphs:
            text = p.get_text(strip=True)
            if len(text) < 150 and ('kan også' in text.lower() or 'kan sagtens' in text.lower()):
                # Проверяем, что в параграфе есть bold текст (часто заметки выделены)
                if p.find(['strong', 'b']) or text.startswith('Den kan'):
                    return self.clean_text(text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем теги в meta keywords или в тексте
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Очищаем и возвращаем теги
            tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            return ', '.join(tags) if tags else None
        
        # Ищем теги в тексте изображений (caption)
        og_image = self.soup.find('meta', property='og:image')
        if og_image:
            # Ищем JSON-LD с изображением
            scripts = self.soup.find_all('script', type='application/ld+json')
            for script in scripts:
                if script.string:
                    try:
                        data = json.loads(script.string)
                        if '@graph' in data:
                            for item in data['@graph']:
                                if item.get('@type') == 'ImageObject' and 'caption' in item:
                                    caption = item['caption']
                                    # Парсим теги из caption (обычно через запятую)
                                    tags = [tag.strip() for tag in caption.split(',') 
                                           if tag.strip() and len(tag.strip()) > 2]
                                    # Убираем общие слова
                                    tags = [tag for tag in tags if tag.lower() not in 
                                           ['dansk i tyrkiet', 'alanya blogger', 'alanya blog', 
                                            'tyrkiet blogger', 'tyrkiet blog', 'opskrift', 'opskrifter']]
                                    if tags:
                                        # Берем первые несколько значимых тегов
                                        return ', '.join(tags[:5])
                    except:
                        pass
        
        # Если не нашли теги, пытаемся извлечь из заголовка
        title = self.extract_dish_name()
        if title:
            # Извлекаем ключевые слова из заголовка
            keywords = []
            # Убираем общие слова
            words = title.lower().split()
            stopwords = ['opskrift', 'på', 'med', 'og', 'i', 'til', 'for', 'af', 'en', 'et']
            for word in words:
                if word not in stopwords and len(word) > 2:
                    keywords.append(word)
            return ', '.join(keywords[:3]) if keywords else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if script.string:
                try:
                    data = json.loads(script.string)
                    
                    # Если есть @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            # ImageObject
                            if item.get('@type') == 'ImageObject':
                                if 'url' in item:
                                    urls.append(item['url'])
                                elif 'contentUrl' in item:
                                    urls.append(item['contentUrl'])
                except:
                    pass
        
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
    # Обрабатываем папку preprocessed/danskityrkiet_dk
    preprocessed_dir = os.path.join("preprocessed", "danskityrkiet_dk")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(DanskiTyrkietExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python danskityrkiet_dk.py")


if __name__ == "__main__":
    main()
