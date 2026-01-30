"""
Экстрактор данных рецептов для сайта bs.usefulfooddrinks.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class BsUsefulfooddrinksComExtractor(BaseRecipeExtractor):
    """Экстрактор для bs.usefulfooddrinks.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта
        recipe_header = self.soup.find('h1', class_='entry-title')
        if recipe_header:
            title = recipe_header.get_text(strip=True)
            # Убираем суффиксы типа ": sastojci, recept, dekoracija"
            title = re.sub(r':\s*(sastojci|recept|dekoracija|priprema|ingredients|recipe).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Альтернативно - из meta тега
        meta_title = self.soup.find('meta', property='og:title')
        if meta_title and meta_title.get('content'):
            title = meta_title['content']
            title = re.sub(r':\s*(sastojci|recept|dekoracija|priprema|ingredients|recipe).*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*-\s*[^-]*$', '', title)  # Убираем " - Deserti" и подобное
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Сокращаем описание до первого предложения или до определенной длины
            sentences = re.split(r'[.!?]\s+', desc)
            if sentences:
                return self.clean_text(sentences[0] + '.')
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            sentences = re.split(r'[.!?]\s+', desc)
            if sentences:
                return self.clean_text(sentences[0] + '.')
        
        return None
    
    def parse_ingredient_text(self, text: str) -> Optional[Dict]:
        """
        Парсинг строки ингредиента на структурированные данные
        
        Args:
            text: Строка вида "200 grama smeđeg šećera" или "jedan gotov keks"
            
        Returns:
            dict: {"name": "...", "amount": ..., "units": "..."}
        """
        if not text:
            return None
        
        # Очищаем текст
        text = self.clean_text(text)
        # Удаляем точку с запятой в конце
        text = text.rstrip(';').rstrip('.').strip()
        
        if not text:
            return None
        
        # Словарь для числительных
        number_words = {
            'jedan': '1', 'jedna': '1', 'jedno': '1',
            'dva': '2', 'dvije': '2', 'dvjesto': '200', 'dvesto': '200',
            'tri': '3', 'tristo': '300',
            'četiri': '4', 'četristo': '400',
            'pet': '5', 'petsto': '500',
            'šest': '6', 'sedam': '7', 'osam': '8', 'devet': '9', 'deset': '10',
            'sto': '100', 'stotinu': '100',
            'pola': '0.5', 'pol': '0.5',
            'prstohvat': 'pinch'
        }
        
        # Словарь для единиц измерения
        unit_mapping = {
            'grama': 'grams', 'gram': 'grams', 'g': 'grams',
            'kilograma': 'kilograms', 'kilogram': 'kilograms', 'kg': 'kilograms',
            'ml': 'ml', 'milliliters': 'milliliters', 'mililitara': 'milliliters',
            'l': 'liters', 'litara': 'liters',
            'kašika': 'tablespoons', 'kašike': 'tablespoons', 'kašiku': 'tablespoons',
            'supena kašika': 'tablespoons', 'supene kašike': 'tablespoons', 'supenih kašika': 'tablespoons',
            'supenu kašiku': 'tablespoons',
            'kašičica': 'teaspoon', 'kašičice': 'teaspoon', 'kašičicu': 'teaspoon',
            'čajna kašičica': 'teaspoon', 'čajne kašičice': 'teaspoon', 'čajnih kašičica': 'teaspoon',
            'šolja': 'cup', 'šolje': 'cup', 'šoljica': 'cup',
            'komad': 'piece', 'komada': 'pieces', 'kom': 'piece',
            'vrećica': 'packet', 'vrećice': 'packet',
            'pakovanje': 'package', 'pakovanja': 'package',
            'prstohvat': 'pinch',
            'šaka': 'handful', 'šake': 'handful',
            'ljušture': 'pieces', 'ljuštura': 'pieces',
            'bjelanjak': 'pieces', 'bjelanjci': 'pieces', 'bjelanjaka': 'pieces',
            'žumanjak': 'pieces', 'žumanjci': 'pieces', 'žumanjaka': 'pieces',
            'jaje': 'pieces', 'jaja': 'pieces',
            'vjeverica': 'pieces', 'vjeverice': 'pieces',
            'tbsp': 'tablespoons', 'tsp': 'teaspoon'
        }
        
        # Словарь для нормализации имен (родительный падеж -> именительный)
        name_normalization = {
            'smeđeg šećera': 'smeđi šećer',
            'bijelog': 'bijeli šećer',
            'koliko bijelog': 'bijeli šećer',  # "same amount of white"
            'agar-agara': 'agar-agar',
            'putera': 'puter',
            'vode': 'voda',
            'limunovog soka': 'limunov sok',
            'kondenzovanog mleka': 'kondenzovano mleko',
            'krema': 'krema',
            'želatine': 'želatina',
            'tamne čokolade': 'tamna čokolada',
            'šećera': 'šećer',
            'brašna': 'brašno',
            'mlijeka': 'mlijeko',
            'gotov keks': 'gotov keks',
            'bjelanjci': 'bjelanjci',
            'bjelanjaka': 'bjelanjci',
        }
        
        # Словарь для определения единиц по названию продукта
        product_to_unit = {
            'keks': 'piece',
            'jaje': 'pieces',
            'jaja': 'pieces',
            'bjelanjak': 'pieces',
            'bjelanjci': 'pieces',
            'žumanjak': 'pieces',
            'žumanjci': 'pieces',
            'vjeverica': 'pieces',
            'vjeverice': 'pieces',
        }
        
        # Паттерн для извлечения количества, единицы и названия
        text_lower = text.lower()
        
        amount = None
        unit = None
        name = text
        
        # Специальная обработка формата "150ml vode" или "50ml krema"
        combined_pattern = re.match(r'^(\d+)(ml|g|kg|l)\s+(.+)$', text_lower)
        if combined_pattern:
            amount = combined_pattern.group(1)
            unit_text = combined_pattern.group(2)
            name = combined_pattern.group(3)
            unit = unit_mapping.get(unit_text, unit_text)
        else:
            # Пытаемся найти число в начале
            number_match = re.match(r'^([\d.,/-]+)\s+', text_lower)
            if number_match:
                amount_str = number_match.group(1)
                # Обработка дробей и диапазонов
                if '/' in amount_str:
                    parts = amount_str.split('/')
                    if len(parts) == 2:
                        amount = str(float(parts[0]) / float(parts[1]))
                elif '-' in amount_str:
                    amount = amount_str  # Сохраняем диапазон как есть
                else:
                    amount = amount_str.replace(',', '.')
                
                # Удаляем число из текста для дальнейшей обработки
                text_lower = text_lower[number_match.end():].strip()
                name = text[number_match.end():].strip()
            
            # Если не нашли число, ищем слово-числительное
            if amount is None:
                for word, num in number_words.items():
                    if text_lower.startswith(word + ' ') or text_lower == word:
                        if num == 'pinch':
                            amount = '1'
                            unit = 'pinch'
                        else:
                            amount = num
                        # Удаляем слово из текста
                        text_lower = text_lower[len(word):].strip()
                        name = text[len(word):].strip()
                        break
            
            # Ищем единицу измерения
            # Сначала проверяем, не начинается ли строка с единицы (например "kašičica limunovog soka")
            unit_found_first = False
            for unit_text, unit_name in unit_mapping.items():
                pattern = r'^' + re.escape(unit_text) + r'\s+'
                if re.match(pattern, text_lower):
                    unit = unit_name
                    # Удаляем единицу из начала и устанавливаем amount = 1 если не было
                    name = re.sub(r'^' + re.escape(unit_text) + r'\s*', '', name, flags=re.IGNORECASE).strip()
                    text_lower = re.sub(pattern, '', text_lower)
                    if not amount:
                        amount = '1'
                    unit_found_first = True
                    break
            
            # Если единицу нашли в начале, не ищем ее после
            if not unit_found_first:
                for unit_text, unit_name in unit_mapping.items():
                    # Проверяем, есть ли единица в начале оставшегося текста (после числа)
                    pattern = r'^' + re.escape(unit_text) + r'\b'
                    if re.match(pattern, text_lower):
                        unit = unit_name
                        # Удаляем единицу из названия
                        name = re.sub(r'^' + re.escape(unit_text) + r'\s*', '', name, flags=re.IGNORECASE).strip()
                        break
        
        # Нормализуем имя из родительного падежа
        name_lower = name.lower().strip()
        name_lower = re.sub(r'[;.,]$', '', name_lower)  # Удаляем знаки препинания
        
        # Проверяем прямое соответствие
        if name_lower in name_normalization:
            name = name_normalization[name_lower]
        else:
            # Удаляем общие родительные окончания
            name = re.sub(r'(eg|og|ih|nih|enog|nog)\s+', ' ', name, flags=re.IGNORECASE)
            name = self.clean_text(name)
        
        # Если единица не определена, проверяем по названию продукта
        if not unit:
            for product_key, product_unit in product_to_unit.items():
                if product_key in name_lower:
                    unit = product_unit
                    break
        
        if not name or len(name) < 2:
            return None
        
        # Конвертируем числовые значения
        if amount:
            try:
                # Если это целое число, конвертируем в int
                if '.' not in str(amount) and '-' not in str(amount):
                    amount = int(float(amount))
                elif '-' not in str(amount):
                    amount = float(amount)
            except:
                pass  # Оставляем как строку
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Находим div.entry-content - основной контент статьи
        article_body = self.soup.find('div', class_='entry-content')
        if not article_body:
            return None
        
        # Ищем первый H2 заголовок с рецептом и его ингредиенты
        # Обычно первый рецепт - основной
        first_recipe_h2_found = False
        stop_collecting = False
        pending_ref = None  # Для обработки "koliko bijelog" и подобных
        
        for elem in article_body.find_all(['h2', 'ul']):
            if elem.name == 'h2':
                header_text = elem.get_text(strip=True).lower()
                
                # Если это первый рецепт (содержит упоминание о блюде/рецепте)
                if not first_recipe_h2_found:
                    first_recipe_h2_found = True
                elif 'preporuč' in header_text or 'dodatn' in header_text or 'uvjet' in header_text:
                    # Закончились рецепты, начались рекомендации
                    stop_collecting = True
                    break
                elif any(keyword in header_text for keyword in ['torta', 'hleb', 'kolač', 'desert', 'recept']):
                    # Начался новый рецепт - прекращаем собирать ингредиенты
                    break
            
            elif elem.name == 'ul' and first_recipe_h2_found and not stop_collecting:
                # Пропускаем навигационные меню и оглавления
                if elem.get('class') or elem.find('a'):
                    continue
                
                items = elem.find_all('li', recursive=False)
                
                # Проверяем, похоже ли это на список ингредиентов
                is_ingredients = False
                for item in items[:3]:
                    text = item.get_text(strip=True).lower()
                    if re.search(r'\d+|jedan|dva|tri|četiri|pet|grama|kašik|ml', text):
                        is_ingredients = True
                        break
                
                if not is_ingredients:
                    continue
                
                # Извлекаем ингредиенты
                for item in items:
                    ingredient_text = item.get_text(strip=True)
                    
                    if not ingredient_text:
                        continue
                    
                    # Специальная обработка для "koliko bijelog" и подобных
                    # Это означает "такое же количество белого (сахара)" - берем из предыдущего
                    if 'koliko' in ingredient_text.lower() and pending_ref:
                        # Используем количество и единицу из предыдущего ингредиента
                        parsed = {
                            "name": "bijeli šećer",
                            "amount": pending_ref.get('amount'),
                            "units": pending_ref.get('units')
                        }
                        pending_ref = None
                    else:
                        parsed = self.parse_ingredient_text(ingredient_text)
                    
                    if parsed and parsed['name']:
                        ingredients.append(parsed)
                        # Сохраняем как потенциальную ссылку для следующего
                        if parsed.get('amount') and 'šećer' in parsed['name'].lower():
                            pending_ref = parsed
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Находим div.entry-content
        article_body = self.soup.find('div', class_='entry-content')
        if not article_body:
            return None
        
        # Собираем инструкции только из первого рецепта
        # Инструкции идут после первого H2 с заголовком рецепта
        instruction_started = False
        first_recipe_section = False
        new_recipe_started = False
        
        for elem in article_body.find_all(['h2', 'p']):
            if elem.name == 'h2':
                header_text = elem.get_text(strip=True).lower()
                
                # Проверяем, начинается ли секция первого рецепта
                if not first_recipe_section:
                    first_recipe_section = True
                    instruction_started = False
                # Проверяем, начинается ли секция инструкций
                elif any(keyword in header_text for keyword in ['kako napraviti', 'priprema', 'pripremiti', 'napravi']) and not new_recipe_started:
                    instruction_started = True
                # Проверяем, начался ли новый рецепт или рекомендации
                elif any(keyword in header_text for keyword in ['preporuč', 'uvjet', 'proizvodnja', 'salata']) or (instruction_started and any(keyword in header_text for keyword in ['torta', 'hleb', 'kolač', 'desert'])):
                    # Закончился первый рецепт
                    new_recipe_started = True
                    break
            elif elem.name == 'p' and first_recipe_section and not new_recipe_started:
                text = elem.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                
                # Пропускаем очень короткие параграфы и мета-информацию
                if len(text) < 30 or 'autor:' in text.lower():
                    continue
                
                # Если уже начали собирать инструкции
                if instruction_started:
                    steps.append(text)
                # Или если параграф содержит глаголы действия (даже без заголовка)
                elif any(verb in text.lower() for verb in ['izreži', 'prelij', 'umuti', 'zagrij', 'dodaj', 'sipa', 'stavi', 'peci', 'pobrašni', 'pomeša', 'postavite', 'promešati']):
                    if not instruction_started:
                        instruction_started = True
                    steps.append(text)
                # Ограничиваем количество шагов для первого рецепта
                if len(steps) >= 15:
                    break
        
        if not steps:
            return None
        
        # Объединяем шаги и нумеруем их
        numbered_steps = []
        for i, step in enumerate(steps, 1):
            # Если шаг уже пронумерован, оставляем как есть
            if re.match(r'^\d+\.', step):
                numbered_steps.append(step)
            else:
                numbered_steps.append(f"{i}. {step}")
        
        return ' '.join(numbered_steps) if numbered_steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', itemtype='https://schema.org/BreadcrumbList')
        if breadcrumbs:
            # Ищем второй элемент в хлебных крошках (первый - главная страница)
            links = breadcrumbs.find_all('a')
            if len(links) >= 2:
                category = links[1].get_text(strip=True)
                # Мапим на английские категории
                category_map = {
                    'Deserti': 'Dessert',
                    'Čokolada': 'Chocolate',
                    'Coffee': 'Coffee',
                    'Glavno jelo': 'Main Course',
                    'Salate': 'Salad',
                    'Supe': 'Soup',
                    'Drinks': 'Drinks',
                    'Najbolji recepti': 'Best Recipes',  # Может содержать разные типы
                }
                mapped_category = category_map.get(category, category)
                
                # Если категория общая (Najbolji recepti), пытаемся определить по заголовку
                if mapped_category in ['Best Recipes', 'Popularni recepti', 'Zdrava hrana']:
                    title = self.extract_dish_name()
                    if title:
                        title_lower = title.lower()
                        if any(word in title_lower for word in ['hleb', 'bread', 'soda bread']):
                            return 'Bread'
                        elif any(word in title_lower for word in ['torta', 'kolač', 'cake']):
                            return 'Dessert'
                
                return mapped_category
        
        # Альтернативно ищем в meta
        meta_section = self.soup.find('meta', itemprop='articleSection')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Время обычно не указано явно в HTML, возвращаем None
        # В референсных JSON оно есть, но в HTML мы его не нашли
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Пытаемся найти время в тексте статьи
        article_body = self.soup.find('div', class_='entry-content')
        if article_body:
            text = article_body.get_text()
            # Ищем паттерны времени
            time_patterns = [
                r'peci(?:te)?\s+(?:hleb|kolač|tortu)?\s*(?:četrdeset|trideset|dvadeset|pedeset)?\s*(\d+)\s+minut',  # "pecite 40 minuta"
                r'(\d+)\s+minut[ae]?\s+(?:pec|kuv)',  # "40 minuta pecenja"
                r'pec(?:i|enje)\s+.*?(\d+)\s+minut',  # "pecenje 40 minuta"
                r'kuva(?:ti|nje)\s+.*?(\d+)\s+minut',  # "kuvanje 30 minuta"
                r'temperatura.*?(\d+)\s+minut',  # после упоминания температуры
            ]
            
            for pattern in time_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    minutes = match.group(1)
                    return f"{minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # В HTML не указано явно
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем параграфы с примечаниями после основной части рецепта
        article_body = self.soup.find('div', class_='entry-content')
        if not article_body:
            return None
        
        # Ищем заголовки типа "Napomena", "Savjet" или параграфы с советами
        note_section_started = False
        notes = []
        
        for elem in article_body.find_all(['h2', 'h3', 'p']):
            if elem.name in ['h2', 'h3']:
                header_text = elem.get_text(strip=True).lower()
                # Проверяем, начинается ли секция примечаний
                if any(keyword in header_text for keyword in ['napomena', 'savjet', 'preporuč', 'tip', 'varijacija']):
                    note_section_started = True
                elif note_section_started:
                    # Закончилась секция примечаний
                    break
            elif elem.name == 'p':
                text = elem.get_text(strip=True)
                text_lower = text.lower()
                
                # Пропускаем мета-информацию и очень длинные параграфы
                if 'autor:' in text_lower or len(text) < 20:
                    continue
                
                # Если в секции примечаний
                if note_section_started:
                    notes.append(self.clean_text(text))
                    # Берем только первое примечание
                    break
                # Или если параграф содержит совет (только в конце статьи)
                elif any(keyword in text_lower for keyword in ['možete koristiti', 'može se', 'preporuč', 'umesto', 'umjesto', 'dodajte', 'opcija']) and len(notes) == 0:
                    # Проверяем, что это ближе к концу статьи (не в середине инструкций)
                    # Ищем параграфы с советами, которые не содержат глаголы готовки
                    if not any(verb in text_lower for verb in ['zagrijte', 'pomeš', 'stavite', 'pecite', 'izrež']):
                        return self.clean_text(text)
        
        return notes[0] if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Очищаем и форматируем
            keywords = self.clean_text(keywords)
            # Разбиваем на отдельные теги и убираем дубликаты
            tags = []
            for tag in keywords.split():
                tag = tag.strip()
                if tag and tag not in tags:
                    tags.append(tag)
            
            # Если тегов слишком много, берем ключевые слова
            if len(' '.join(tags)) > 100:
                # Извлекаем только уникальные значимые слова
                unique_tags = []
                seen = set()
                for word in keywords.split():
                    word = word.strip().lower()
                    if word and word not in seen and len(word) > 3:
                        seen.add(word)
                        unique_tags.append(word)
                        if len(unique_tags) >= 5:
                            break
                if unique_tags:
                    return ', '.join(unique_tags)
            
            return keywords if keywords else None
        
        # Альтернативно извлекаем из заголовка или категории
        title = self.extract_dish_name()
        category = self.extract_category()
        
        tags = []
        if category:
            tags.append(category.lower())
        if title:
            # Извлекаем ключевые слова из названия
            words = title.lower().split()
            for word in words[:3]:  # Берем первые 3 значимых слова
                if len(word) > 3 and word not in tags:
                    tags.append(word)
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем изображения в статье с itemprop="contentUrl"
        article_images = self.soup.find_all('img', itemprop='contentUrl')
        for img in article_images:
            src = img.get('src')
            if src and src not in urls:
                urls.append(src)
        
        # 3. Если не нашли, ищем любые изображения в article body
        if not urls:
            article_body = self.soup.find('div', class_='entry-content')
            if article_body:
                images = article_body.find_all('img')
                for img in images:
                    src = img.get('src')
                    if src and 'usefulfooddrinks.com/images' in src and src not in urls:
                        urls.append(src)
        
        # Возвращаем как строку, разделенную запятыми
        return ','.join(urls) if urls else None
    
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
    """Обработка HTML файлов из директории preprocessed/bs_usefulfooddrinks_com"""
    import os
    
    # Определяем путь к директории с HTML файлами
    base_dir = Path(__file__).parent.parent
    preprocessed_dir = base_dir / "preprocessed" / "bs_usefulfooddrinks_com"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обработка файлов из: {preprocessed_dir}")
        process_directory(BsUsefulfooddrinksComExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python bs_usefulfooddrinks_com.py")


if __name__ == "__main__":
    main()
