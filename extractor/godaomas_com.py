"""
Экстрактор данных рецептов для сайта godaomas.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class GodaomasExtractor(BaseRecipeExtractor):
    """Экстрактор для godaomas.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта
        recipe_header = self.soup.find('h1', class_='entry-title')
        if recipe_header:
            title = self.clean_text(recipe_header.get_text())
            # Убираем суффиксы "-recepten" для одного блюда
            title = re.sub(r'-recepten$', '', title, flags=re.IGNORECASE)
            return title
        
        # Альтернативно - из первого h3 в контенте с рецептом
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            first_h3 = entry_content.find('h3')
            if first_h3:
                title = self.clean_text(first_h3.get_text())
                # Убираем emoji и префиксы
                title = re.sub(r'^[⭐🍴👨‍🍳🧑‍🍳👩‍🍳🛒⏲️\s]+', '', title)
                # Убираем текст после двоеточия (описание)
                title = re.sub(r'\s*[:–]\s*.*$', '', title)
                # Убираем "-recept" и "-recepten"
                title = re.sub(r'-(recept|recepten)$', '', title, flags=re.IGNORECASE)
                return self.clean_text(title)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - Goda Oma's Recipten & Tips"
            title = re.sub(r'\s*-\s*Goda Oma.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'-recepten$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала проверяем meta description
        meta_desc = self.soup.find('meta', property='og:description')
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Убираем emoji и лишние символы
            desc = re.sub(r'[⭐🍴👨‍🍳🧑‍🍳👩‍🍳🛒⏲️]+', '', desc)
            # Убираем префиксы типа "Börek-recept:"
            desc = re.sub(r'^[^:]+:\s*', '', desc)
            # Ищем первое предложение до символа! или .
            match = re.match(r'^([^!.]+[!.])', desc)
            if match:
                return self.clean_text(match.group(1))
            # Или берем до многоточия или специальных символов
            match = re.match(r'^([^…⏲️]+?)(?:\s*[…⏲️]|$)', desc)
            if match:
                sent = match.group(1).strip()
                # Добавляем точку если нет
                if not sent.endswith(('.', '!', '?')):
                    sent += '.'
                return self.clean_text(sent)
        
        # Альтернативно - ищем описание после заголовка "Introductie"
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            intro_heading = entry_content.find('h3', string=re.compile(r'Introductie', re.I))
            if intro_heading:
                next_p = intro_heading.find_next_sibling('p')
                if next_p:
                    text = self.clean_text(next_p.get_text())
                    # Берем только первое предложение
                    sentences = re.split(r'[.!?]', text)
                    if sentences:
                        return sentences[0].strip() + '.'
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем секцию с ингредиентами
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем заголовок "Ingrediënten" - нужно искать через get_text() так как текст может быть в <strong>
        ingredients_heading = None
        for h3 in entry_content.find_all('h3'):
            if 'Ingrediënten' in h3.get_text():
                ingredients_heading = h3
                break
        
        if not ingredients_heading:
            return None
        
        # Берем следующий список <ul> после заголовка
        ingredients_list = ingredients_heading.find_next_sibling('ul')
        if not ingredients_list:
            return None
        
        # Извлекаем каждый ингредиент
        for item in ingredients_list.find_all('li'):
            ingredient_text = self.clean_text(item.get_text())
            if ingredient_text:
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "300 g groene asperges" или "2 eetlepels honing"
            
        Returns:
            dict: {"name": "groene asperges", "amount": "300", "unit": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = ingredient_text.strip()
        
        # Удаляем emoji в начале строки (распространенный паттерн на godaomas.com)
        # Включаем вариационные селекторы (FE00-FEFF) и расширенные emoji диапазоны
        text = re.sub(r'^[\U0001F000-\U0001FFFF\U00002000-\U00002BFF\U0000FE00-\U0000FEFF\s]+', '', text)
        
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
        # Примеры: "300 g groene asperges", "2 eetlepels honing", "120 g brie"
        # Добавлены сокращения: el (eetlepel), tl (theelepel)
        pattern = r'^([\d\s/.,]+)?\s*(g|kg|ml|l|eetlepels?|eetlepel|theelepels?|theelepel|stuks?|stuk|plakken|snufje|takjes?|takje|blaadjes?|blaad|teentjes?|teen|el|tl|middelgrote)?\s*(.+)'
        
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
                        total += float(part)
                amount = str(total)
            else:
                amount = amount_str.replace(',', '.')
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "naar smaak", "optioneel" и т.д.
        name = re.sub(r'\b(naar smaak|optioneel|indien nodig|voor garnering)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        # Конвертируем amount в число если возможно
        amount_value = None
        if amount:
            try:
                # Пробуем конвертировать в float и проверяем, целое ли число
                float_val = float(amount)
                if float_val == int(float_val):
                    amount_value = int(float_val)
                else:
                    amount_value = amount  # Оставляем как строку если есть дробная часть
            except ValueError:
                amount_value = amount
        
        return {
            "name": name,
            "amount": amount_value,
            "units": unit  # Используем "units" вместо "unit" как в эталоне
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Ищем секцию с инструкциями
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем заголовок "Bereidingswijze" или "Bereiding" или "instructies"
        # Нужно искать через get_text() так как текст может быть в <strong>
        instructions_heading = None
        for h3 in entry_content.find_all('h3'):
            h3_text = h3.get_text()
            if re.search(r'Bereidingswijze|Bereiding|instructies', h3_text, re.I):
                instructions_heading = h3
                break
        
        if not instructions_heading:
            return None
        
        # Собираем все шаги инструкций
        steps = []
        
        # Проверяем структуру: если сразу после заголовка h4, то это сложная структура
        # В противном случае это может быть простой список
        next_elem = instructions_heading.find_next_sibling()
        has_h4_structure = next_elem and next_elem.name == 'h4'
        
        if not has_h4_structure:
            # Простая структура: попробуем найти список
            instructions_list = instructions_heading.find_next_sibling(['ol', 'ul'])
            if instructions_list and instructions_list.find_all('li'):
                # Проверяем, что это действительно список с инструкциями, а не просто один элемент
                items = instructions_list.find_all('li')
                if len(items) > 1:  # Больше одного элемента = вероятно это полный список инструкций
                    for item in items:
                        step_text = self.clean_text(item.get_text())
                        if step_text:
                            steps.append(step_text)
                    return ' '.join(steps) if steps else None
        
        # Сложная структура или простой список не найден: собираем все до следующего h3
        current = instructions_heading.find_next_sibling()
        while current and current.name != 'h3':
            if current.name == 'h4':
                # Это подзаголовок этапа (например, "Stap 1: Maak de vulling")
                step_text = self.clean_text(current.get_text())
                if step_text:
                    steps.append(step_text)
            elif current.name == 'p':
                # Это описание шага
                step_text = self.clean_text(current.get_text())
                if step_text and not step_text.isspace():
                    steps.append(step_text)
            elif current.name in ['ul', 'ol']:
                # Список внутри шагов
                for item in current.find_all('li'):
                    step_text = self.clean_text(item.get_text())
                    if step_text:
                        steps.append(step_text)
            
            current = current.find_next_sibling()
        
        # Объединяем шаги в одну строку
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в тексте описания или introduction блюда
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем в первых параграфах и заголовках ключевые слова категорий
        elements = entry_content.find_all(['p', 'h3'], limit=10)
        category_patterns = {
            'Bijgerecht': r'\bbijgerecht\b',
            'Hoofdgerecht': r'\bhoofdgerecht\b|main course',
            'Voorgerecht': r'\bvoorgerecht\b',
            'Dessert': r'\bdessert\b',
            'Snack': r'\bsnack',
            'Main Course': r'main course',
            'Breakfast': r'\bbreakfast\b|\bontbijt\b',
            'Lunch': r'\blunch\b',
            'Dinner': r'\bdinner\b|\bavondeten\b'
        }
        
        for elem in elements:
            elem_text = self.clean_text(elem.get_text()).lower()
            for category, pattern in category_patterns.items():
                if re.search(pattern, elem_text, re.I):
                    return category
        
        return None
    
    def extract_time_from_list(self, time_pattern: str) -> Optional[str]:
        """
        Общий метод для извлечения времени из списка информации о рецепте
        
        Args:
            time_pattern: Регулярное выражение для поиска времени
        """
        # Сначала проверяем список "Receptinformatie"
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            info_heading = entry_content.find('h3', string=re.compile(r'Receptinformatie', re.I))
            if info_heading:
                info_list = info_heading.find_next_sibling('ul')
                if info_list:
                    for item in info_list.find_all('li'):
                        item_text = self.clean_text(item.get_text())
                        if re.search(time_pattern, item_text, re.I):
                            # Извлекаем значение после двоеточия
                            parts = item_text.split(':', 1)
                            if len(parts) > 1:
                                time_str = self.clean_text(parts[1])
                                # Конвертируем "minuten" в "minutes"
                                if time_str:
                                    time_str = time_str.replace('minuten', 'minutes')
                                    time_str = time_str.replace('minuut', 'minute')
                                return time_str
        
        # Если не нашли в списке, ищем в первых параграфах (альтернативный формат)
        if entry_content:
            paragraphs = entry_content.find_all('p', limit=3)
            for p in paragraphs:
                p_text = p.get_text()
                # Ищем паттерн времени в тексте
                match = re.search(time_pattern + r':\s*(\d+\s*\w+)', p_text, re.I)
                if match:
                    time_str = self.clean_text(match.group(1))
                    # Конвертируем "minuten" в "minutes"
                    if time_str:
                        time_str = time_str.replace('minuten', 'minutes')
                        time_str = time_str.replace('minuut', 'minute')
                    return time_str
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем именно "Voorbereidingstijd" (не "Bereidingstijd")
        result = self.extract_time_from_list(r'voorbereidingstijd')
        if result:
            return result
        
        # Дополнительная проверка в параграфах для альтернативного формата
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            paragraphs = entry_content.find_all('p', limit=5)
            for p in paragraphs:
                p_text = p.get_text()
                # Ищем "Bereidingstijd" (в некоторых рецептах это prep time)
                # Учитываем emoji и другие символы после числа
                match = re.search(r'bereidingstijd:\s*(\d+)\s*minuten', p_text, re.I)
                if match:
                    # Проверяем, есть ли также "Baktijd" в том же параграфе
                    has_baktijd = re.search(r'baktijd:', p_text, re.I)
                    if has_baktijd:
                        # Если есть и Bereidingstijd и Baktijd, значит Bereidingstijd - это prep
                        time_num = match.group(1)
                        return f"{time_num} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Сначала пробуем найти "Baktijd" (время выпечки/приготовления)
        result = self.extract_time_from_list(r'baktijd')
        if result:
            return result
        # Если нет, ищем "Bereidingstijd" (но НЕ "Voorbereidingstijd")
        # Это нужно чтобы отличить от prep_time
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            # Проверяем список "Receptinformatie"
            info_heading = entry_content.find('h3', string=re.compile(r'Receptinformatie', re.I))
            if info_heading:
                info_list = info_heading.find_next_sibling('ul')
                if info_list:
                    for item in info_list.find_all('li'):
                        item_text = self.clean_text(item.get_text())
                        # Ищем "Bereidingstijd" но не "Voorbereidingstijd"
                        if re.search(r'^bereidingstijd:', item_text, re.I) and not re.search(r'voorbereiding', item_text, re.I):
                            parts = item_text.split(':', 1)
                            if len(parts) > 1:
                                time_str = self.clean_text(parts[1])
                                if time_str:
                                    time_str = time_str.replace('minuten', 'minutes')
                                    time_str = time_str.replace('minuut', 'minute')
                                return time_str
            
            # Альтернативный формат в параграфах
            paragraphs = entry_content.find_all('p', limit=3)
            for p in paragraphs:
                p_text = p.get_text()
                # Ищем только "Baktijd" в параграфах (более специфично)
                match = re.search(r'baktijd:\s*(\d+\s*\w+)', p_text, re.I)
                if match:
                    time_str = self.clean_text(match.group(1))
                    if time_str:
                        time_str = time_str.replace('minuten', 'minutes')
                        time_str = time_str.replace('minuut', 'minute')
                    return time_str
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        result = self.extract_time_from_list(r'totale tijd')
        if result:
            return result
        
        # Если total_time не указано явно, вычисляем из prep_time + cook_time
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep and cook:
            # Извлекаем числа из строк времени
            prep_match = re.search(r'(\d+)', prep)
            cook_match = re.search(r'(\d+)', cook)
            
            if prep_match and cook_match:
                prep_num = int(prep_match.group(1))
                cook_num = int(cook_match.group(1))
                total_num = prep_num + cook_num
                
                return f"{total_num} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем секцию "Bewaren" (хранение) - приоритетная заметка
        bewaren_heading = entry_content.find('h3', string=re.compile(r'Bewaren', re.I))
        if bewaren_heading:
            next_elem = bewaren_heading.find_next_sibling(['p', 'ul', 'ol'])
            if next_elem:
                text = self.clean_text(next_elem.get_text())
                if text:
                    return text
        
        # Ищем секцию "Serveertips en opslag" (serving tips and storage)
        # Heading может содержать текст внутри тегов strong
        for heading in entry_content.find_all('h3'):
            heading_text = self.clean_text(heading.get_text())
            if re.search(r'Serveertips en opslag', heading_text, re.I):
                next_elem = heading.find_next_sibling(['p', 'ul', 'ol'])
                if next_elem:
                    # Если это список, объединяем нужные элементы
                    if next_elem.name in ['ul', 'ol']:
                        notes_items = []
                        for li in next_elem.find_all('li', recursive=False):  # Только прямые дочерние элементы
                            li_text = self.clean_text(li.get_text())
                            # Фильтруем заголовки и пустые строки
                            if li_text:
                                # Пропускаем элементы которые являются только заголовками (в жирном шрифте и заканчиваются на ":")
                                strong_tag = li.find('strong')
                                # Если весь текст li состоит только из strong и заканчивается на ":", пропускаем
                                if strong_tag and strong_tag.get_text().strip() == li_text.strip() and li_text.endswith(':'):
                                    continue
                                notes_items.append(li_text)
                                # Ограничиваем до 2 пунктов (один для serving, один для storage)
                                if len(notes_items) >= 2:
                                    break
                        if notes_items:
                            return ' '.join(notes_items)
                    else:
                        text = self.clean_text(next_elem.get_text())
                        if text:
                            return text
                break
        
        # Если не найдено, ищем другие секции с заметками
        note_patterns = [
            r'Tips',
            r'Opmerking',
            r'Variaties',
            r'Serveertips'
        ]
        
        notes_parts = []
        for pattern in note_patterns:
            heading = entry_content.find('h3', string=re.compile(pattern, re.I))
            if heading:
                next_elem = heading.find_next_sibling(['p', 'ul', 'ol'])
                if next_elem:
                    text = self.clean_text(next_elem.get_text())
                    if text:
                        notes_parts.append(text)
        
        return ' '.join(notes_parts) if notes_parts else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Извлекаем теги из ключевых слов в тексте описания и названия
        dish_name = self.extract_dish_name()
        if dish_name:
            # Извлекаем значимые слова из названия
            name_words = re.findall(r'\b\w{4,}\b', dish_name.lower())
            # Фильтруем стоп-слова
            stopwords = {'met', 'van', 'voor', 'een', 'het', 'de', 'recepten', 'recept'}
            name_tags = [w for w in name_words if w not in stopwords]
            tags.extend(name_tags[:3])  # Берем первые 3 значимых слова
        
        # Добавляем категорию как тег
        category = self.extract_category()
        if category:
            tags.append(category.lower())
        
        # Ищем дополнительные теги в первых параграфах
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            # Ищем ключевые слова в описании
            paragraphs = entry_content.find_all('p', limit=5)
            combined_text = ' '.join([p.get_text() for p in paragraphs]).lower()
            
            # Ключевые слова для тегов
            tag_keywords = [
                'vegetarisch', 'vegan', 'glutenvrij', 'lactosevrij',
                'turkse', 'italiaanse', 'franse', 'griekse', 'spaanse',
                'gezond', 'snel', 'makkelijk', 'traditioneel'
            ]
            
            for keyword in tag_keywords:
                if keyword in combined_text and keyword not in tags:
                    tags.append(keyword)
        
        # Убираем дубликаты
        seen = set()
        unique_tags = []
        for tag in tags:
            if tag and tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            # Преобразуем http в https если нужно
            url = url.replace('http://', 'https://')
            urls.append(url)
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Если data - это словарь с @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                url = item['url'].replace('http://', 'https://')
                                urls.append(url)
                            elif 'contentUrl' in item:
                                url = item['contentUrl'].replace('http://', 'https://')
                                urls.append(url)
            
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 3. Ищем изображения в контенте
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            # Ищем все img теги
            images = entry_content.find_all('img')
            for img in images[:3]:  # Берем первые 3 изображения
                src = img.get('src') or img.get('data-src')
                if src and 'wp-content/uploads' in src:
                    src = src.replace('http://', 'https://')
                    if src not in urls:
                        urls.append(src)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        return ','.join(unique_urls) if unique_urls else None
    
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
    # Обрабатываем папку preprocessed/godaomas_com
    recipes_dir = os.path.join("preprocessed", "godaomas_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(GodaomasExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python godaomas_com.py")


if __name__ == "__main__":
    main()
