"""
Экстрактор данных рецептов для сайта domacirecepti.net
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class DomaciReceptiExtractor(BaseRecipeExtractor):
    """Экстрактор для domacirecepti.net"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в JSON-LD BlogPosting
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'BlogPosting' and 'headline' in data:
                    headline = data['headline']
                    # Удаляем HTML entities и лишние слова
                    headline = headline.replace('&#8211;', '-')
                    headline = re.sub(r'\s+za\s+\d+\s+minuta?', '', headline, flags=re.IGNORECASE)
                    headline = re.sub(r'\s*-\s*recept\s*$', '', headline, flags=re.IGNORECASE)
                    return self.clean_text(headline)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернатива - из заголовка статьи
        h1 = self.soup.find('h1', class_='post-title')
        if h1:
            title = h1.get_text()
            title = re.sub(r'\s+za\s+\d+\s+minuta?', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*-\s*recept\s*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в JSON-LD BlogPosting
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'BlogPosting' and 'description' in data:
                    description = data['description']
                    # Берем только первые два предложения (до второй точки)
                    sentences = description.split('.')
                    if len(sentences) >= 2:
                        description = sentences[0] + '.' + sentences[1] + '.'
                    elif sentences:
                        description = sentences[0] + '.'
                    # Удаляем лишние части
                    description = re.sub(r'Sva mudorst je u.*$', '', description, flags=re.IGNORECASE)
                    description = re.sub(r'Jedan jeftin.*$', '', description, flags=re.IGNORECASE)
                    return self.clean_text(description)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернатива - первый параграф entry-content
        entry_content = self.soup.find(class_=lambda x: x and 'entry-content' in str(x).lower() if x else False)
        if entry_content:
            first_p = entry_content.find('p')
            if first_p:
                text = first_p.get_text()
                # Берем только первое предложение
                sentences = text.split('.')
                if sentences:
                    return self.clean_text(sentences[0] + '.')
        
        return None
    
    def parse_ingredient_line(self, line: str, is_posip: bool = False) -> Optional[Dict[str, any]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            line: Строка вида "3 jaja", "100ml ulja", "7 kašika šećera"
            is_posip: True если это ингредиент из секции "Posip"
            
        Returns:
            dict: {"name": "...", "units": "...", "amount": ...} или None
        """
        if not line or len(line.strip()) < 2:
            return None
        
        line = self.clean_text(line).strip()
        
        # Удаляем маркеры типа "opciono", "po ukusu"  
        line = re.sub(r'\s*\(.*?\)\s*', ' ', line)
        line = re.sub(r'\s*(opciono|po ukusu|po želji)\s*', '', line, flags=re.IGNORECASE)
        line = line.strip()
        
        if not line:
            return None
        
        # Специальная обработка для строк с "jednog", "pola"
        # "korica od jednog limuna" -> извлекаем 1
        # "sok od pola limuna" -> извлекаем 0.5
        word_to_num = {
            'jednog': ('1', 'pieces'),
            'jedne': ('1', 'pieces'),
            'jednu': ('1', 'pieces'),
            'pola': ('0.5', 'pieces'),
            'dva': ('2', 'pieces'),
            'dve': ('2', 'pieces'),
            'tri': ('3', 'pieces'),
            'četiri': ('4', 'pieces'),
        }
        
        for word, (num, unit_default) in word_to_num.items():
            if word in line.lower():
                # Удаляем слово из строки
                name = re.sub(rf'\b{word}\b', '', line, flags=re.IGNORECASE).strip()
                # Убираем лишние "od"
                name = re.sub(r'\bod\b', '', name, flags=re.IGNORECASE).strip()
                # Убираем множественные пробелы
                name = re.sub(r'\s+', ' ', name).strip()
                # Добавляем (posip) если нужно
                if is_posip:
                    name = f"{name} (posip)"
                return {
                    "name": name,
                    "units": unit_default,
                    "amount": float(num) if '.' in num else int(num)
                }
        
        # Паттерн для извлечения: количество + единица + название
        # Примеры: "3 jaja", "100ml ulja", "7 kašika šećera", "10g praška", "500gr mesa"
        pattern = r'^([\d.,/]+)\s*(gr|g|kg|ml|l|kašika|kašike|kašiku|kašičica|kašičice|komada?|pieces?|glavica?|glavice|šoljica?|mala šoljica|srednje glavice|manja glavica)?\s*(.+)$'
        
        match = re.match(pattern, line, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount = amount_str.strip().replace(',', '.')
            # Конвертируем дроби
            if '/' in amount:
                parts = amount.split('/')
                if len(parts) == 2:
                    try:
                        amount = float(parts[0]) / float(parts[1])
                    except:
                        pass
            else:
                # Конвертируем в число
                try:
                    if '.' in amount:
                        amount = float(amount)
                    else:
                        amount = int(amount)
                except:
                    pass
            
            # Нормализация единиц
            if unit:
                unit = unit.strip().lower()
                # Маппинг единиц
                unit_map = {
                    'kašika': 'tablespoons',
                    'kašike': 'tablespoons',
                    'kašiku': 'tablespoons',
                    'kašičica': 'teaspoons',
                    'kašičice': 'teaspoons',
                    'g': 'g',
                    'gr': 'gr',
                    'kg': 'kg',
                    'ml': 'ml',
                    'l': 'l',
                    'komada': 'pieces',
                    'komad': 'pieces',
                    'piece': 'pieces',
                    'pieces': 'pieces',
                    'glavica': 'pieces',
                    'glavice': 'pieces',
                    'šoljica': 'cup',
                    'mala šoljica': 'small cup',
                    'srednje glavice': 'medium pieces',
                    'manja glavica': 'small head'
                }
                unit = unit_map.get(unit, unit)
            else:
                # Если нет единицы но есть количество, предполагаем pieces
                unit = 'pieces'
            
            # Удаляем падежные окончания из названия (генитив)
            # "šećera" -> "šećer", "ulja" -> "ulje", "mleka" -> "mleko"
            name = name.strip()
            name = re.sub(r'(šećer)a$', r'\1', name)
            name = re.sub(r'(ulj)a$', r'\1e', name)
            name = re.sub(r'(mlek)a$', r'\1o', name)
            name = re.sub(r'(brašn)a$', r'\1o', name)
            name = re.sub(r'(maslac)a$', r'\1', name)
            name = re.sub(r'(praš)ka$', r'\1kasta', name)  # "praška" -> "praškasta"
            # Специальная обработка для "mlevenog badema ili oraha"
            name = re.sub(r'mlevenog\s+(badem)a\s+ili\s+(orah)a', r'mleveni \1 ili \2', name)
            name = re.sub(r'(jaj)a$', r'\1a', name)  # jaja остается jaja
            
            # Добавляем (posip) если нужно
            if is_posip:
                name = f"{name} (posip)"
            
            return {
                "name": name,
                "units": unit,
                "amount": amount
            }
        else:
            # Если паттерн не совпал, возвращаем как есть без количества
            name = line
            if is_posip:
                name = f"{name} (posip)"
            return {
                "name": name,
                "units": None,
                "amount": None
            }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        entry_content = self.soup.find(class_=lambda x: x and 'entry-content' in str(x).lower() if x else False)
        if not entry_content:
            return None
        
        paragraphs = entry_content.find_all('p')
        
        # Ищем параграф с "Sastojci:"
        sastojci_found = False
        for p in paragraphs:
            text = p.get_text().strip()
            
            # Начало секции ингредиентов
            if re.match(r'^Sastojci\s*:', text, re.IGNORECASE):
                sastojci_found = True
                
                # Парсим строки из этого же параграфа
                lines = text.split('\n')
                for line in lines[1:]:  # Пропускаем первую строку "Sastojci:"
                    line = line.strip()
                    if line:
                        parsed = self.parse_ingredient_line(line, is_posip=False)
                        if parsed:
                            ingredients.append(parsed)
                
                # Ищем список <ul> или <ol> сразу после параграфа "Sastojci:"
                next_elem = p.find_next_sibling()
                while next_elem:
                    if next_elem.name in ['ul', 'ol']:
                        # Нашли список ингредиентов
                        list_items = next_elem.find_all('li')
                        for item in list_items:
                            line = item.get_text().strip()
                            if line:
                                parsed = self.parse_ingredient_line(line, is_posip=False)
                                if parsed:
                                    ingredients.append(parsed)
                        next_elem = next_elem.find_next_sibling()
                    elif next_elem.name == 'p':
                        text = next_elem.get_text().strip()
                        # Если нашли "Posip:", парсим как posip
                        if re.match(r'^Posip\s*:', text, re.IGNORECASE):
                            lines = text.split('\n')
                            for line in lines[1:]:
                                line = line.strip()
                                if line:
                                    parsed = self.parse_ingredient_line(line, is_posip=True)
                                    if parsed:
                                        ingredients.append(parsed)
                            next_elem = next_elem.find_next_sibling()
                        # Если нашли "Priprema:", прекращаем
                        elif re.match(r'^Priprema\s*:', text, re.IGNORECASE):
                            break
                        # Если пустой параграф, продолжаем
                        elif not text:
                            next_elem = next_elem.find_next_sibling()
                        # Иначе парсим как ингредиент
                        else:
                            lines = text.split('\n')
                            for line in lines:
                                line = line.strip()
                                if line:
                                    parsed = self.parse_ingredient_line(line, is_posip=False)
                                    if parsed:
                                        ingredients.append(parsed)
                            next_elem = next_elem.find_next_sibling()
                    else:
                        # Пропускаем другие элементы (div и т.д.)
                        next_elem = next_elem.find_next_sibling()
                
                break  # Нашли секцию ингредиентов, выходим
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        entry_content = self.soup.find(class_=lambda x: x and 'entry-content' in str(x).lower() if x else False)
        if not entry_content:
            return None
        
        paragraphs = entry_content.find_all('p')
        
        # Ищем параграф с "Priprema:"
        in_preparation_section = False
        for p in paragraphs:
            text = p.get_text().strip()
            
            # Начало секции приготовления
            if re.match(r'^Priprema\s*:', text, re.IGNORECASE):
                in_preparation_section = True
                # Проверяем, есть ли текст после "Priprema:"
                lines = text.split('\n')
                for line in lines[1:]:
                    line = line.strip()
                    if line:
                        steps.append(line)
                continue
            
            # Если мы в секции приготовления
            if in_preparation_section:
                # Проверяем, не пустой ли параграф
                if text and len(text) > 5:
                    # Игнорируем заголовки и призывы
                    if not re.match(r'^(Prijatno|Dobar tek)!?$', text, re.IGNORECASE):
                        steps.append(text)
        
        # Объединяем шаги в одну строку
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в JSON-LD BlogPosting
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'BlogPosting' and 'articleSection' in data:
                    sections = data['articleSection']
                    
                    # Маппинг категорий на английский
                    category_map = {
                        'glavna jela': 'Main Course',
                        'jela sa mesom': 'Main Course',
                        'jela bez mesa': 'Main Course',
                        'kolači': 'Dessert',
                        'brzi kolači': 'Dessert',
                        'razni kolači': 'Dessert',
                        'torte': 'Dessert',
                        'desert': 'Dessert',
                        'deserti': 'Dessert',
                        'predjela': 'Appetizer',
                        'salate': 'Salad',
                        'supe': 'Soup',
                        'čorbe': 'Soup',
                        'hleb': 'Bread',
                        'pecivo': 'Bakery',
                        'prilozi': 'Side Dish',
                        'sosevi': 'Sauce'
                    }
                    
                    # Если sections - это строка
                    if isinstance(sections, str):
                        sections = [s.strip() for s in sections.split(',')]
                    
                    # Ищем первую подходящую категорию
                    for section in sections:
                        section_lower = section.lower()
                        for key, value in category_map.items():
                            if key in section_lower:
                                return value
                    
                    # Если не нашли в маппинге, возвращаем первую секцию
                    if sections:
                        return sections[0] if isinstance(sections, list) else sections
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в JSON-LD BlogPosting
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'BlogPosting' and 'keywords' in data:
                    keywords = data['keywords']
                    if isinstance(keywords, list):
                        tags = ', '.join(keywords)
                    else:
                        tags = keywords
                    # Удаляем точки в конце тегов и нормализуем пробелы
                    tags = re.sub(r'\.\s*,', ', ', tags)
                    tags = re.sub(r',\s*', ', ', tags)  # Нормализуем пробелы после запятых
                    tags = re.sub(r'\.$', '', tags)
                    tags = tags.strip()
                    return tags
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_time_from_text(self) -> Dict[str, Optional[str]]:
        """Извлечение времени из текста описания"""
        times = {
            'prep_time': None,
            'cook_time': None,
            'total_time': None
        }
        
        # Получаем текст из JSON-LD и entry-content
        text = ""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'BlogPosting':
                    description = data.get('description', '')
                    headline = data.get('headline', '')
                    article_body = data.get('articleBody', '')
                    text = headline + " " + description + " " + article_body
                    break
            except:
                continue
        
        # Также получаем текст из entry-content для более полного поиска
        entry_content = self.soup.find(class_=lambda x: x and 'entry-content' in str(x).lower() if x else False)
        if entry_content:
            text += " " + entry_content.get_text()
        
        # Ищем паттерны времени
        # "za 5 minuta" в заголовке или описании - prep time
        prep_patterns = [
            r'(?:napraviti|spremiti)?\s*za\s+(\d+)\s*minut',  # "za 5 minuta"
            r'priprema:?\s*(\d+)\s*minut',  # "priprema: 15 minuta"
        ]
        
        for pattern in prep_patterns:
            prep_match = re.search(pattern, text, re.IGNORECASE)
            if prep_match:
                times['prep_time'] = f"{prep_match.group(1)} minutes"
                break
        
        # "ispeći za 30 minuta", "peče 30 minuta", "kuvati 2h" - cook time
        cook_patterns = [
            r'(?:ispeći|peč[ei]|peku).*?(\d+)ak?\s*minut',  # "ispeći za 30ak minuta"
            r'oko\s+(\d+)\s*minut',  # "oko 30 minuta"
            r'peč[ei].*?(\d+)\s*minut',  # "peče 30 minuta"
            r'(?:kuva|krčka).*?(\d+)\s*h\b',  # "kuvati 2h"
            r'najmanje\s+(\d+)\s*h',  # "najmanje 2h"
            r'(?:kuva|krčka).*?(\d+)\s*sat',  # "kuvati 2 sata"
        ]
        
        for pattern in cook_patterns:
            cook_match = re.search(pattern, text, re.IGNORECASE)
            if cook_match:
                time_val = cook_match.group(1)
                # Проверяем, это часы или минуты
                if 'h' in cook_match.group(0).lower() or 'sat' in cook_match.group(0).lower():
                    # Это часы
                    times['cook_time'] = f"{int(time_val) * 60} minutes"
                else:
                    times['cook_time'] = f"{time_val} minutes"
                break
        
        # Вычисляем total_time если есть оба
        if times['prep_time'] and times['cook_time']:
            prep_mins = int(re.search(r'\d+', times['prep_time']).group())
            cook_mins = int(re.search(r'\d+', times['cook_time']).group())
            times['total_time'] = f"{prep_mins + cook_mins} minutes"
        elif times['cook_time']:
            times['total_time'] = times['cook_time']
        elif times['prep_time']:
            times['total_time'] = times['prep_time']
        
        return times
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        entry_content = self.soup.find(class_=lambda x: x and 'entry-content' in str(x).lower() if x else False)
        if not entry_content:
            return None
        
        paragraphs = entry_content.find_all('p')
        
        # Ищем последние параграфы после секции приготовления
        # Обычно заметки находятся в конце
        all_paragraphs_after_prep = []
        found_preparation = False
        
        for p in paragraphs:
            text = p.get_text().strip()
            
            if re.match(r'^Priprema\s*:', text, re.IGNORECASE):
                found_preparation = True
                continue
            
            # Собираем все параграфы после приготовления
            if found_preparation and text and len(text) > 10:
                # Игнорируем стандартные фразы в конце
                if not re.match(r'^(Prijatno|Dobar tek)!?$', text, re.IGNORECASE):
                    all_paragraphs_after_prep.append(text)
        
        # Берем последний параграф как заметку
        # Обычно это совет или дополнительная информация
        if all_paragraphs_after_prep:
            last_para = all_paragraphs_after_prep[-1]
            # Проверяем, что это действительно заметка (короткий текст с советом)
            if len(last_para) < 300:
                # Если параграф содержит "može da se...", извлекаем именно эту часть с контекстом
                if 'može da se' in last_para.lower():
                    # Ищем предложение с "može da se"
                    # Попытка найти с контекстом "Kolač može da se"
                    match = re.search(r'([^\.,!?]*može da se[^\.!?]*[\.!?])', last_para, re.IGNORECASE)
                    if match:
                        note = match.group(1).strip()
                        # Если не начинается с заглавной буквы, добавляем контекст
                        if not note[0].isupper():
                            # Ищем слово перед "može"
                            full_match = re.search(r'(\w+\s+može da se[^\.!?]*[\.!?])', last_para, re.IGNORECASE)
                            if full_match:
                                note = full_match.group(1).strip()
                                note = note[0].upper() + note[1:]
                        return note
                # Возвращаем как есть если есть ключевые слова
                if any(keyword in last_para.lower() for keyword in ['može', 'možete', 'najbolje', 'opciono', 'savjet', 'napomena', 'tip', 'ili', 'ako']):
                    return last_para
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # На domacirecepti.net обычно нет информации о питательности
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # BlogPosting или Article
                if data.get('@type') in ['BlogPosting', 'Article']:
                    # thumbnailUrl
                    if 'thumbnailUrl' in data:
                        urls.append(data['thumbnailUrl'])
                
                # Ищем в @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') in ['Article', 'BlogPosting', 'WebPage']:
                            if 'thumbnailUrl' in item:
                                urls.append(item['thumbnailUrl'])
                        elif item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
                                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 3. Ищем изображения в entry-content
        entry_content = self.soup.find(class_=lambda x: x and 'entry-content' in str(x).lower() if x else False)
        if entry_content:
            images = entry_content.find_all('img', src=True)
            for img in images[:3]:  # Берем первые 3 изображения
                src = img['src']
                # Игнорируем маленькие изображения и иконки
                if not any(skip in src.lower() for skip in ['icon', 'logo', 'avatar', 'emoji']):
                    urls.append(src)
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
                    if len(unique_urls) >= 3:  # Ограничиваем до 3 изображений
                        break
            return ','.join(unique_urls) if unique_urls else None
        
        return None
    
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта
        
        Returns:
            Словарь с данными рецепта
        """
        times = self.extract_time_from_text()
        
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_steps(),
            "nutrition_info": self.extract_nutrition_info(),
            "category": self.extract_category(),
            "prep_time": times.get('prep_time'),
            "cook_time": times.get('cook_time'),
            "total_time": times.get('total_time'),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # По умолчанию обрабатываем папку preprocessed/domacirecepti_net
    recipes_dir = os.path.join("preprocessed", "domacirecepti_net")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(DomaciReceptiExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python domacirecepti_net.py")


if __name__ == "__main__":
    main()
