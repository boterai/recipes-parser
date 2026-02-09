"""
Экстрактор данных рецептов для сайта tradicionalnirecepti.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TradicionalnireceptiExtractor(BaseRecipeExtractor):
    """Экстрактор для tradicionalnirecepti.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в h1.entry-title
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            text = h1.get_text(strip=True)
            
            # Сложная логика извлечения короткого названия:
            # 1. Если есть двоеточие, берем часть до него
            if ':' in text:
                text = text.split(':', 1)[0]
            
            # 2. Если есть тире с пробелами вокруг, берем часть до него
            if ' – ' in text:
                text = text.split(' – ')[0]
            elif ' - ' in text:
                text = text.split(' - ')[0]
            
            # 3. Убираем префиксы типа "NAJMEKŠE", "NAJLAKŠI", etc.
            text = re.sub(r'^(NAJMEKŠE|NAJLAKŠI|NAJBOLJI|NAJUKUSNIJI)\s+', '', text, flags=re.IGNORECASE)
            
            # 4. Извлекаем ключевое слово
            # Ищем название рецепта - обычно это существительное
            # Примеры: "kiflice na svetu" -> "kiflice", "ČIZKEJK NA NAJLAKŠI NAČIN" -> "ČIZKEJK"
            # Убираем предлоги и берем первое значимое слово или словосочетание
            words = text.split()
            
            # Если первое слово не предлог, берем его (может быть с прилагательным)
            if words and words[0].lower() not in ['na', 'sa', 'od', 'u', 'za']:
                # Если второе слово тоже не предлог, берем два слова
                if len(words) > 1 and words[1].lower() not in ['na', 'sa', 'od', 'u', 'za']:
                    text = ' '.join(words[:2])
                else:
                    text = words[0]
            elif len(words) > 1:
                # Первое слово - предлог, ищем следующее значимое
                for i in range(1, len(words)):
                    if words[i].lower() not in ['na', 'sa', 'od', 'u', 'za']:
                        text = words[i]
                        break
            
            return self.clean_text(text)
        
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
    
    def parse_ingredient_line(self, line: str) -> Optional[Dict[str, any]]:
        """
        Парсинг строки ингредиента
        Примеры:
        - "krem sir 450g" -> {name: "krem sir", amount: 450, units: "g"}
        - "pavlaka 2 kom" -> {name: "pavlaka", amount: 2, units: "kom"}
        - "Žuti luk (1 komad)" -> {name: "Žuti luk", amount: 1, units: "komad"}
        - "Maslac za prženje" -> {name: "Maslac za prženje", amount: None, units: None}
        """
        if not line:
            return None
        
        line = self.clean_text(line)
        
        # Убираем маркеры начала списка
        line = re.sub(r'^[-•▪]\s*', '', line)
        
        # Убираем дескрипторы после "–" (например, "– male", "– opcionalno")
        if '–' in line:
            line = line.split('–')[0].strip()
        
        # Паттерны для извлечения количества и единицы
        # Паттерн 1: "название количествоединица" (e.g., "krem sir 450g")
        pattern1 = r'^(.+?)\s+([\d\.,/\-]+)([a-zA-Zčćžšđ]+)$'
        # Паттерн 2: "название количество единица" (e.g., "pavlaka 2 kom", "ekstrakt vanile 1 kašika")
        pattern2 = r'^(.+?)\s+([\d\.,/\-]+)\s+([a-zA-Zčćžšđ]+(?:e|a|i)?)$'
        # Паттерн 3: "название (количество единица)" (e.g., "Žuti luk (1 komad)")
        pattern3 = r'^(.+?)\s*\(([\d\.,/\-]+)\s+([^)]+)\)$'
        # Паттерн 4: "количество единица название" (e.g., "900 g brašna")
        pattern4 = r'^([\d\.,/\-]+)\s+([a-zA-Zčćžšđ]+)\s+(.+)$'
        
        # Пробуем паттерн 2 (с пробелом между числом и единицей)
        match = re.match(pattern2, line, re.IGNORECASE)
        if match:
            name, amount, unit = match.groups()
            # Преобразуем amount в число
            try:
                amount_num = float(amount.replace(',', '.'))
                # Если это целое число, возвращаем как int
                if amount_num.is_integer():
                    amount_num = int(amount_num)
            except:
                amount_num = amount.replace(',', '.')
            
            return {
                "name": self.clean_text(name),
                "amount": amount_num,
                "units": unit
            }
        
        # Пробуем паттерн 1 (без пробела между числом и единицей)
        match = re.match(pattern1, line, re.IGNORECASE)
        if match:
            name, amount, unit = match.groups()
            try:
                amount_num = float(amount.replace(',', '.'))
                if amount_num.is_integer():
                    amount_num = int(amount_num)
            except:
                amount_num = amount.replace(',', '.')
            
            return {
                "name": self.clean_text(name),
                "amount": amount_num,
                "units": unit
            }
        
        # Пробуем паттерн 3 (в скобках)
        match = re.match(pattern3, line, re.IGNORECASE)
        if match:
            name, amount, unit = match.groups()
            try:
                amount_num = float(amount.replace(',', '.'))
                if amount_num.is_integer():
                    amount_num = int(amount_num)
            except:
                amount_num = amount.replace(',', '.')
            
            return {
                "name": self.clean_text(name),
                "amount": amount_num,
                "units": unit
            }
        
        # Пробуем паттерн 4 (количество в начале)
        match = re.match(pattern4, line, re.IGNORECASE)
        if match:
            amount, unit, name = match.groups()
            try:
                amount_num = float(amount.replace(',', '.'))
                if amount_num.is_integer():
                    amount_num = int(amount_num)
            except:
                amount_num = amount.replace(',', '.')
            
            return {
                "name": self.clean_text(name),
                "amount": amount_num,
                "units": unit
            }
        
        # Если ничего не совпало, возвращаем только название
        return {
            "name": self.clean_text(line),
            "amount": None,
            "units": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов - поддержка как <p>, так и <li> тегов"""
        ingredients = []
        
        # Ищем все параграфы и списки в entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Сначала пробуем найти в параграфах (как в cizkejk и pamuk kiflice)
        paragraphs = entry_content.find_all('p')
        
        for p in paragraphs:
            text = p.get_text(strip=True)
            
            # Ищем параграф с "Sastojci" который содержит <br> (список ингредиентов)
            if re.match(r'Sastojci', text, re.IGNORECASE) and '<br' in str(p):
                # Это параграф с ингредиентами
                html_content = str(p)
                parts = re.split(r'<br\s*/?>', html_content)
                
                for part in parts:
                    clean = re.sub(r'<[^>]+>', '', part).strip()
                    
                    # Пропускаем заголовок "Sastojci..."
                    if re.match(r'^Sastojci', clean, re.IGNORECASE):
                        continue
                    
                    # Пропускаем пустые строки
                    if not clean or len(clean) < 3:
                        continue
                    
                    # Парсим ингредиент
                    ingredient = self.parse_ingredient_line(clean)
                    if ingredient and ingredient['name']:
                        # Проверяем что это похоже на ингредиент
                        if len(ingredient['name']) < 80:
                            ingredients.append(ingredient)
                
                # Если нашли ингредиенты, возвращаем их
                if ingredients:
                    return json.dumps(ingredients, ensure_ascii=False)
        
        # Если не нашли в одном параграфе, пробуем старый метод (несколько параграфов)
        in_ingredients = False
        ingredients = []
        
        for p in paragraphs:
            text = p.get_text(strip=True)
            
            # Проверяем, начинается ли секция ингредиентов
            if re.match(r'Sastojci', text, re.IGNORECASE):
                in_ingredients = True
                continue
            
            # Если мы в секции ингредиентов
            if in_ingredients:
                # Проверяем, не закончилась ли секция
                if any(keyword in text.lower() for keyword in ['priprema:', 'postupak:', 'način pripreme:', 'fil se sprema', 'se sprema ovako', 'pomešati', 'da bi', 'pravilno', 'nauljena']):
                    # Обрабатываем текст до этого маркера, если он в том же параграфе
                    if '<br' in str(p):
                        html_content = str(p)
                        parts = re.split(r'<br\s*/?>', html_content)
                        
                        for part in parts:
                            clean = re.sub(r'<[^>]+>', '', part).strip()
                            if any(kw in clean.lower() for kw in ['pomešati', 'fil se sprema', 'priprema:', 'postupak:', 'da bi', 'pravilno']):
                                break
                            if not clean or re.match(r'^(Sastojci|Za\s+\w+):?$', clean, re.IGNORECASE):
                                continue
                            ingredient = self.parse_ingredient_line(clean)
                            if ingredient and ingredient['name'] and len(ingredient['name']) > 3:
                                ingredients.append(ingredient)
                    break
                
                # Обрабатываем строки ингредиентов через <br>
                if '<br' in str(p):
                    html_content = str(p)
                    parts = re.split(r'<br\s*/?>', html_content)
                    
                    for part in parts:
                        clean = re.sub(r'<[^>]+>', '', part).strip()
                        if not clean or re.match(r'^(Sastojci|Za\s+\w+):?$', clean, re.IGNORECASE):
                            continue
                        ingredient = self.parse_ingredient_line(clean)
                        if ingredient and ingredient['name']:
                            if len(ingredient['name']) > 3 and not re.match(r'^(Za|Po|Sadržaj|Saveti|Da bi)\s+', ingredient['name'], re.IGNORECASE):
                                if len(ingredient['name']) < 100:
                                    ingredients.append(ingredient)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления - поддержка <p> и <li> тегов"""
        steps = []
        
        # Ищем все параграфы и элементы списков в entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Пробуем сначала извлечь из параграфов
        paragraphs = entry_content.find_all('p')
        in_instructions = False
        found_ingredients = False
        
        for p in paragraphs:
            text = p.get_text(strip=True)
            
            # Отслеживаем, что мы прошли секцию ингредиентов
            if re.match(r'Sastojci', text, re.IGNORECASE):
                found_ingredients = True
                continue
            
            # Проверяем начало секции инструкций
            if found_ingredients and not in_instructions:
                if any(keyword in text.lower() for keyword in ['priprema:', 'postupak:', 'način pripreme:', 'fil se sprema', 'se sprema ovako']):
                    in_instructions = True
                    if ':' in text:
                        remainder = text.split(':', 1)[1].strip()
                        if remainder and len(remainder) > 20:
                            steps.append(self.clean_text(remainder))
                    continue
                elif any(text.lower().startswith(verb) for verb in ['mikserom', 'pomešati', 'dodavati', 'mutiti', 'staviti', 'ostaviti', 'služiti', 'pržiti', 'sipati']):
                    in_instructions = True
            
            # Если мы в секции инструкций, собираем шаги
            if in_instructions:
                clean_text = self.clean_text(text)
                
                if not clean_text or len(clean_text) < 15:
                    continue
                
                if re.match(r'^(Napomena|Serviramo|Savjet|Tip|U videu|Izvor):', clean_text, re.IGNORECASE):
                    break
                
                if not any(clean_text.lower().startswith(word) for word in ['mikserom', 'pomešati', 'dodavati', 'mutiti', 'staviti', 'ostaviti', 'služiti', 'pržiti', 'sipati', 'u veću']) and len(steps) == 0:
                    continue
                
                steps.append(clean_text)
        
        # Если инструкции не найдены в параграфах, ищем в элементах списков
        if not steps:
            all_items = entry_content.find_all(['li', 'ol', 'ul'])
            
            for item in all_items:
                # Если это список, ищем внутри элементы
                if item.name in ['ol', 'ul']:
                    list_items = item.find_all('li')
                    for li in list_items:
                        text = li.get_text(strip=True)
                        
                        # Извлекаем инструкции из элементов списка
                        # Обычно они содержат глаголы действия
                        if any(verb in text.lower() for verb in ['sipajte', 'dodajte', 'umutite', 'pomešajte', 'ostavite', 'stavite', 'pečete']):
                            # Может быть несколько шагов в одном li через <br>
                            if '<br' in str(li):
                                parts = re.split(r'<br\s*/?>', str(li))
                                for part in parts:
                                    clean = re.sub(r'<[^>]+>', '', part).strip()
                                    clean = self.clean_text(clean)
                                    if clean and len(clean) > 20:
                                        # Пропускаем заголовки
                                        if not re.match(r'^(Priprema|Sastojci|Za|Saveti)', clean, re.IGNORECASE):
                                            steps.append(clean)
                            else:
                                clean = self.clean_text(text)
                                if clean and len(clean) > 20:
                                    steps.append(clean)
                elif item.name == 'li':
                    text = item.get_text(strip=True)
                    if any(verb in text.lower() for verb in ['sipajte', 'dodajte', 'umutite', 'pomešajte', 'ostavite', 'stavite', 'pečete']):
                        if '<br' in str(item):
                            parts = re.split(r'<br\s*/?>', str(item))
                            for part in parts:
                                clean = re.sub(r'<[^>]+>', '', part).strip()
                                clean = self.clean_text(clean)
                                if clean and len(clean) > 20:
                                    if not re.match(r'^(Priprema|Sastojci|Za|Saveti)', clean, re.IGNORECASE):
                                        steps.append(clean)
                        else:
                            clean = self.clean_text(text)
                            if clean and len(clean) > 20:
                                steps.append(clean)
        
        if steps:
            # Нумеруем шаги, если они еще не пронумерованы
            numbered_steps = []
            for idx, step in enumerate(steps, 1):
                if not re.match(r'^\d+\.', step):
                    numbered_steps.append(f"{idx}. {step}")
                else:
                    numbered_steps.append(step)
            return ' '.join(numbered_steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории с мапингом на стандартные категории"""
        # Маппинг категорий сайта на стандартные категории
        category_mapping = {
            'kuhanje': 'Dessert',  # По умолчанию для этого сайта
            'desert': 'Dessert',
            'slatkiši': 'Dessert',
            'kolači': 'Dessert',
            'glavna jela': 'Main Course',
            'glavno jelo': 'Main Course',
            'predjela': 'Appetizer',
            'salate': 'Salad',
        }
        
        # Ищем ссылку с rel="category tag"
        category_link = self.soup.find('a', rel='category tag')
        if category_link:
            category_text = self.clean_text(category_link.get_text()).lower()
            # Пытаемся найти маппинг
            return category_mapping.get(category_text, 'Dessert')  # По умолчанию Dessert
        
        # Альтернативно - ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                category_text = self.clean_text(links[-1].get_text()).lower()
                return category_mapping.get(category_text, 'Dessert')
        
        return 'Dessert'  # По умолчанию
    
    def extract_time_from_text(self, text: str, time_type: str) -> Optional[str]:
        """
        Извлечение времени из текста
        time_type: 'prep', 'cook', 'total'
        """
        if not text:
            return None
        
        # Паттерны для поиска времени
        # "sat vremena" = час времени, "minuta" = минут
        time_patterns = {
            'hour': r'(\d+)\s*sat(?:a)?\s*vremena',
            'minutes': r'(\d+)\s*minut(?:a)?',
            'range': r'(\d+)-(\d+)\s*minut(?:a)?',
            'hours_minutes': r'(\d+)\s*sat(?:a)?\s*(?:i\s*)?(\d+)?\s*minut(?:a)?'
        }
        
        # Ищем диапазон времени
        match = re.search(time_patterns['range'], text, re.IGNORECASE)
        if match:
            return f"{match.group(1)}-{match.group(2)} minutes"
        
        # Ищем часы и минуты
        match = re.search(time_patterns['hours_minutes'], text, re.IGNORECASE)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2)) if match.group(2) else 0
            total_minutes = hours * 60 + minutes
            if minutes > 0:
                return f"{hours} hour {minutes} minutes" if hours == 1 else f"{hours} hours {minutes} minutes"
            else:
                return f"{hours} hour" if hours == 1 else f"{hours} hours"
        
        # Ищем только часы
        match = re.search(time_patterns['hour'], text, re.IGNORECASE)
        if match:
            hours = int(match.group(1))
            return f"{hours} hour" if hours == 1 else f"{hours} hours"
        
        # Ищем только минуты
        match = re.search(time_patterns['minutes'], text, re.IGNORECASE)
        if match:
            return f"{match.group(1)} minutes"
        
        return None
    
    def extract_times(self) -> Dict[str, Optional[str]]:
        """Извлечение всех временных полей из текста рецепта"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return {'prep_time': None, 'cook_time': None, 'total_time': None}
        
        full_text = entry_content.get_text()
        
        prep_time = None
        cook_time = None
        total_time = None
        
        # Ищем время готовки в духовке (peče, pečenje)
        # Примеры: "160 stepeni sat vremena" = 1 час = 60 минут
        cook_patterns = [
            r'peč(?:e|i|enje)[^.]*?(?:\d+)\s*(?:stepeni|C)[^.]*?sat(?:a)?\s+vremena',  # "peče 160 stepeni sat vremena"
            r'(\d+)\s*sat(?:a)?\s+vremena',  # "sat vremena" = 1 час
            r'(\d+)-(\d+)\s*minut(?:a)?',  # "40-45 minuta"
        ]
        
        for pattern in cook_patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                if 'sat' in match.group(0).lower():
                    # Это час времени
                    cook_time = "60 minutes"
                    break
                elif '-' in pattern:  # Диапазон минут
                    cook_time = f"{match.group(1)}-{match.group(2)} minutes"
                    break
        
        # Ищем общее время охлаждения/отдыха (hladi X sata, počiva)
        # Примеры: "hladi 4 sata" = 4 часа, "počiva 90 minuta" = 90 минут
        total_patterns = [
            r'hladi\s+(\d+)\s*sat(?:a|i)',  # "hladi 4 sata"
            r'počiva\s+(\d+)\s*minut(?:a)?',  # "počiva 90 minuta"
        ]
        
        for pattern in total_patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                hours = int(match.group(1))
                if 'sat' in pattern:
                    total_time = f"{hours} hours" if hours != 1 else f"{hours} hour"
                else:  # минуты
                    total_time = f"{hours} minutes"
                break
        
        # Ищем prep_time (время подготовки)
        prep_patterns = [
            r'priprem(?:a|i)\s+(\d+)\s*minut(?:a)?',
        ]
        
        for pattern in prep_patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                prep_time = f"{match.group(1)} minutes"
                break
        
        return {
            'prep_time': prep_time,
            'cook_time': cook_time,
            'total_time': total_time
        }
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем заметки в параграфах
        paragraphs = entry_content.find_all('p')
        notes = []
        
        for p in paragraphs:
            text = p.get_text(strip=True)
            
            # Проверяем наличие ключевых слов для заметок
            if any(keyword in text.lower() for keyword in ['napomena:', 'savjet:', 'tip:', 'u videu', 'možete pogledati']):
                clean = self.clean_text(text)
                clean = re.sub(r'^(Napomena|Savjet|Tip):\s*', '', clean, flags=re.IGNORECASE)
                clean = re.sub(r':+$', '', clean)
                clean = re.sub(r'\.$', '', clean)
                if clean:
                    notes.append(clean)
            
            # Ищем параграфы с советами (например, "Toplo mleko, nikako vrelo")
            # Эти параграфы часто содержат <br> и несколько советов
            # НО пропускаем параграф с ингредиентами
            if '<br' in str(p) and 'sastojci' not in text.lower():
                if any(word in text.lower() for word in ['toplo mleko', 'pravilno mesenje', 'strpljenje']):
                    # Разбираем по <br> и берем первые несколько советов
                    parts = re.split(r'<br\s*/?>', str(p))
                    for part in parts[:3]:  # Берем первые 3 совета
                        clean = re.sub(r'<[^>]+>', '', part).strip()
                        clean = self.clean_text(clean)
                        # Пропускаем длинные параграфы и заголовки
                        if clean and 20 < len(clean) < 150:
                            if not clean.lower().startswith(('načini', 'pamuk kiflice', 'evo nekoliko', 'sastojci')):
                                notes.append(clean)
        
        # Также ищем в элементах списка
        if not notes:
            list_items = entry_content.find_all('li')
            for li in list_items:
                text = li.get_text(strip=True)
                # Ищем "Послужите" в тексте (обычно в конце инструкций)
                if 'poslužite' in text.lower() or 'servirajte' in text.lower():
                    # Извлекаем часть с рекомендацией сервировки
                    match = re.search(r'poslužite\s+(.*?)(?:\.|$)', text, re.IGNORECASE)
                    if match:
                        note = match.group(1).strip()
                        if note:
                            notes.append(f"Poslužite {note}")
        
        if notes:
            result = '. '.join(notes)
            if not result.endswith('.'):
                result += '.'
            return result
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем теги в футере записи
        entry_footer = self.soup.find('footer', class_='entry-footer')
        if entry_footer:
            # Ищем ссылки с rel="tag"
            tag_links = entry_footer.find_all('a', rel='tag')
            if tag_links:
                tags = [self.clean_text(link.get_text()) for link in tag_links]
                return ','.join(tags).lower()
        
        # Альтернативно - из meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content']).lower()
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем featured image (wp-post-image)
        featured_img = self.soup.find('img', class_='wp-post-image')
        if featured_img and featured_img.get('src'):
            urls.append(featured_img['src'])
        
        # 2. Ищем в meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 3. Ищем в meta twitter:image
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
        times = self.extract_times()
        
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_instructions(),
            "category": self.extract_category(),
            "prep_time": times['prep_time'],
            "cook_time": times['cook_time'],
            "total_time": times['total_time'],
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/tradicionalnirecepti_com
    recipes_dir = os.path.join("preprocessed", "tradicionalnirecepti_com")
    
    # Проверяем абсолютный путь
    if not os.path.isabs(recipes_dir):
        # Ищем от корня репозитория
        current_dir = Path(__file__).parent.parent
        recipes_dir = current_dir / "preprocessed" / "tradicionalnirecepti_com"
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(TradicionalnireceptiExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python tradicionalnirecepti_com.py")


if __name__ == "__main__":
    main()
