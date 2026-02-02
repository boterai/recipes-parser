"""
Экстрактор данных рецептов для сайта rodzunka.com.ua
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class RodzunkaComUaExtractor(BaseRecipeExtractor):
    """Экстрактор для rodzunka.com.ua"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        entry_content = self.soup.find('div', class_='entry-content')
        h1 = self.soup.find('h1', class_='entry-title')
        
        # Проверяем H1 - если это короткое название рецепта (не статья), используем его
        if h1:
            h1_text = self.clean_text(h1.get_text())
            # Убираем эмодзи и суффиксы
            h1_clean = re.sub(r'[🎃🍫💚🌱🍇🍓🍌🍑🍒❖🥬🌶️]', '', h1_text)
            h1_clean = re.sub(r':\s*(рецепт|приготування|простий рецепт|секрети).*$', '', h1_clean, flags=re.IGNORECASE)
            h1_clean = self.clean_text(h1_clean)
            
            # Если H1 достаточно короткий и не содержит "як" или "секрети" (признак статьи),
            # то это название рецепта
            if h1_clean and len(h1_clean) < 60 and 'як' not in h1_clean.lower():
                return h1_clean
        
        # Для статей с несколькими рецептами ищем первый H3 заголовок в content
        # (например, "Компот із винограду", "Маринований виноград" и т.д.)
        if entry_content:
            first_h3 = entry_content.find('h3')
            if first_h3:
                dish_name = self.clean_text(first_h3.get_text())
                # Убираем эмодзи
                dish_name = re.sub(r'[🎃🍫💚🌱🍇🍓🍌🍑🍒❖🥬🌶️]', '', dish_name)
                # Не используем H3, если это "Приготування..." (это заголовок инструкций)
                if dish_name and len(dish_name) > 5 and not dish_name.lower().startswith('приготування'):
                    return dish_name
        
        # Fallback на H1 если ничего не нашли
        if h1:
            return h1_clean if h1_clean else self.clean_text(h1.get_text())
        
        # Альтернативно - из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
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
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Примеры:
        - "150 г. борошна" -> {name: "борошно", amount: 150, units: "г"}
        - "темний шоколад – 170 г" -> {name: "темний шоколад", amount: 170, units: "г"}
        - "цукор – одна столова ложка" -> {name: "цукор", amount: 1, units: "столова ложка"}
        - "2 ст. ложки олії" -> {name: "олія", amount: 2, units: "ст. ложки"}
        - "2 яйця" -> {name: "яйця", amount: 2, units: null}
        """
        if not ingredient_text:
            return None
        
        # Убираем точку с запятой в конце
        ingredient_text = ingredient_text.rstrip(';').strip()
        
        # Словарь для текстовых чисел (украинский)
        text_numbers = {
            'одна': 1, 'один': 1, 'одне': 1,
            'дві': 2, 'два': 2,
            'три': 3, 'три': 3,
            'чотири': 4, 'чотири': 4,
            "п'ять": 5, 'пять': 5,
            'півтора': 1.5, 'полтора': 1.5
        }
        
        # Паттерн: название – текстовое число + единица (e.g., "цукор – одна столова ложка")
        text_number_pattern = r'^(.+?)\s*[–-]\s*(' + '|'.join(text_numbers.keys()) + r')\s+(.+)$'
        match = re.match(text_number_pattern, ingredient_text, re.IGNORECASE)
        if match:
            name, text_num, unit = match.groups()
            amount = text_numbers.get(text_num.lower(), 1)
            return {
                "name": self.clean_text(name),
                "amount": amount,
                "units": self.clean_text(unit)
            }
        
        # Паттерн: название – количество единица (rodzunka style)
        # Примеры: "темний шоколад (опис) – 170 г", "вершки – 180 мл"
        dash_pattern = r'^(.+?)\s*[–-]\s*(\d+(?:[.,]\d+)?(?:-\d+(?:[.,]\d+)?)?)\s*(г\.?|мл\.?|кг\.?|л\.?|ст\.\s*лож[а-я]+|столов[а-я]*\s*лож[а-я]+|чайн[іи][х]?\s*лож[а-я]+|ч\.л\.|шт\.?)?\s*\.?$'
        match = re.match(dash_pattern, ingredient_text, re.IGNORECASE)
        if match:
            name, amount, unit = match.groups()
            # Убираем описание в скобках из названия
            name = re.sub(r'\s*\([^)]+\)\s*', ' ', name).strip()
            # Убираем "від 30%" и подобные дополнения из названия
            name = re.sub(r'\s+від\s+\d+%', '', name).strip()
            # Преобразуем количество
            amount_str = amount.replace(',', '.')
            # Если диапазон (2.5-3), берем первое значение
            if '-' in amount_str:
                amount_str = amount_str.split('-')[0]
            try:
                amount = int(float(amount_str)) if float(amount_str).is_integer() else float(amount_str)
            except:
                amount = amount_str
            
            return {
                "name": self.clean_text(name),
                "amount": amount,
                "units": self.clean_text(unit) if unit else None
            }
        
        # Паттерн: количество + единица + название (старый стиль)
        patterns = [
            # Число + единица (г, мл, кг) + название
            r'^(\d+(?:[.,]\d+)?)\s*(г\.?|мл\.?|кг\.?|л\.?)\s+(.+)$',
            # Число + сложная единица (ст. ложки, чайні ложки) + название
            r'^(\d+)\s+(ст\.\s*лож[а-я]+|чайн[іи][х]?\s*лож[а-я]+|ч\.л\.)\s+(.+)$',
            # Число + название (без единиц)
            r'^(\d+)\s+(.+)$',
            # Только название (без количества)
            r'^(.+)$'
        ]
        
        for pattern in patterns:
            match = re.match(pattern, ingredient_text, re.IGNORECASE)
            if match:
                groups = match.groups()
                
                if len(groups) == 3:
                    # Есть количество, единица и название
                    amount, unit, name = groups
                    # Преобразуем запятую в точку для чисел
                    amount = amount.replace(',', '.')
                    # Пытаемся преобразовать в число
                    try:
                        amount = int(float(amount)) if float(amount).is_integer() else float(amount)
                    except:
                        pass
                    return {
                        "name": self.clean_text(name),
                        "amount": amount,
                        "units": self.clean_text(unit) if unit else None
                    }
                elif len(groups) == 2:
                    # Есть количество и название (без единиц)
                    amount, name = groups
                    try:
                        amount = int(amount)
                    except:
                        pass
                    return {
                        "name": self.clean_text(name),
                        "amount": amount,
                        "units": None
                    }
                else:
                    # Только название (редкий случай)
                    name = groups[0]
                    return {
                        "name": self.clean_text(name),
                        "amount": None,
                        "units": None
                    }
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем заголовок "Інгредієнти" или "Складники"
        for heading in entry_content.find_all(['h3', 'h2', 'p', 'strong']):
            heading_text = heading.get_text().strip()
            if 'нгредієнт' in heading_text or 'кладник' in heading_text:
                # Ищем следующий ul после этого заголовка
                next_el = heading.find_next_sibling()
                while next_el:
                    if next_el.name == 'ul':
                        # Нашли список ингредиентов
                        for li in next_el.find_all('li'):
                            ingredient_text = self.clean_text(li.get_text())
                            if ingredient_text:
                                parsed = self.parse_ingredient(ingredient_text)
                                if parsed:
                                    ingredients.append(parsed)
                        # Продолжаем искать следующие списки (например, маринад)
                        next_el = next_el.find_next_sibling()
                        continue
                    elif next_el.name == 'p':
                        # Проверяем, не специи ли это (например, "Спеції: ...")
                        text = next_el.get_text().strip()
                        if text.startswith('Спеці') or text.startswith('Маринад'):
                            # Парсим специи из текста параграфа
                            # Формат: "Спеції: лавровий лист – 3 шт., перець – 5 шт."
                            if ':' in text:
                                spices_text = text.split(':', 1)[1].strip()
                                # Разбиваем по запятым
                                for spice in spices_text.split(','):
                                    spice = spice.strip().rstrip('.')
                                    if spice:
                                        parsed = self.parse_ingredient(spice)
                                        if parsed:
                                            ingredients.append(parsed)
                        next_el = next_el.find_next_sibling()
                        continue
                    elif next_el.name in ['h2', 'h3', 'h4']:
                        # Новый заголовок - прекращаем поиск
                        break
                    next_el = next_el.find_next_sibling()
                
                if ingredients:
                    break
        
        # Если не нашли по заголовку, ищем в тексте (для таких как компот из винограда)
        # где ингредиенты упоминаются в тексте инструкций
        if not ingredients:
            # Ищем упоминания сиропа, сахара и т.д. в тексте
            for p in entry_content.find_all('p'):
                text = p.get_text()
                # Ищем упоминания типа "550 г цукру на 1 л води"
                sugar_match = re.search(r'(\d+)\s*г\s+цукр[уа]', text)
                water_match = re.search(r'(\d+)\s*л\s+вод[иі]', text)
                
                if sugar_match or water_match:
                    # Это похоже на рецепт компота
                    # Добавляем виноград (если в тексте есть)
                    if 'виноград' in text.lower():
                        ingredients.append({
                            "name": "виноград",
                            "amount": None,
                            "units": None
                        })
                    if sugar_match:
                        ingredients.append({
                            "name": "цукор",
                            "amount": int(sugar_match.group(1)),
                            "units": "г"
                        })
                    if water_match:
                        ingredients.append({
                            "name": "вода",
                            "amount": int(water_match.group(1)),
                            "units": "л"
                        })
                    if ingredients:
                        break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions = []
        
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Стратегия 1: Ищем заголовок "Покроковий рецепт" или "Приготування" ПОСЛЕ списка ингредиентов
        ul = entry_content.find('ul')  # Находим список ингредиентов
        found_instructions_section = False
        
        if ul:
            # Ищем заголовок ПОСЛЕ списка ингредиентов
            current = ul.find_next_sibling()
            while current:
                if current.name in ['h3', 'h2', 'h4']:
                    heading_text = current.get_text().strip().lower()
                    # Ищем заголовок с ключевыми словами
                    if 'покроков' in heading_text or 'приготування' in heading_text:
                        # Собираем все параграфы после этого заголовка
                        next_el = current.find_next_sibling()
                        while next_el:
                            if next_el.name == 'p':
                                text = self.clean_text(next_el.get_text())
                                if text and len(text) > 15 and 'читати також' not in text.lower():
                                    if not (len(text) < 100 and any(emoji in text for emoji in ['🎄', '👼', '🍑', '🍌', '🍒', '🍇', '🍓', '🌱'])):
                                        instructions.append(text)
                            elif next_el.name in ['h2', 'h3', 'h4']:
                                break
                            elif next_el.name == 'ol':
                                for li in next_el.find_all('li'):
                                    text = self.clean_text(li.get_text())
                                    if text:
                                        instructions.append(text)
                            next_el = next_el.find_next_sibling()
                        
                        found_instructions_section = True
                        break
                current = current.find_next_sibling()
        
        # Стратегия 2: Если нет заголовка "Покроковий", ищем параграфы с описанием процесса
        # Для страниц типа "компот из винограда", где инструкции идут сразу в тексте
        if not found_instructions_section:
            # Ищем первый H3 заголовок (название рецепта) и берем параграфы после него
            first_h3 = entry_content.find('h3')
            if first_h3:
                next_el = first_h3.find_next_sibling()
                while next_el:
                    if next_el.name == 'p':
                        text = self.clean_text(next_el.get_text())
                        # Берем параграфы с инструкциями (достаточно длинные)
                        if text and len(text) > 30 and 'читати також' not in text.lower():
                            # Пропускаем параграфы типа "Сезон приготування"
                            if not text.startswith('Сезон') and not (len(text) < 100 and any(emoji in text for emoji in ['🎄', '👼', '🍑', '🍌', '🍒', '🍇', '🍓', '🌱'])):
                                # Проверяем, что это действительно инструкция (содержит глаголы действия)
                                if any(verb in text.lower() for verb in ['миють', 'миют', 'дають', 'укладають', 'заливають', 'кип\'ятять', 'додають', 'закупорюють', 'стерилізують', 'насікти', 'очистити', 'натерти', 'складіть', 'змішайте', 'закип\'ятіть', 'залийте', 'покладіть', 'варити', 'нарізати', 'приготувати', 'збити', 'випікати']):
                                    # Если параграф начинается с "Для приготування компоту...", 
                                    # извлекаем только часть начиная с основного действия
                                    if text.startswith('Для приготування'):
                                        # Ищем первое упоминание действия с ингредиентом
                                        for verb in ['Виноград миють', 'Капусту', 'М\'ясо']:
                                            if verb in text:
                                                # Извлекаем текст начиная с этого действия
                                                idx = text.index(verb)
                                                text = text[idx:]
                                                break
                                    instructions.append(text)
                    elif next_el.name in ['h2', 'h3', 'h4']:
                        # Следующий рецепт - прекращаем
                        break
                    elif next_el.name == 'ul':
                        # Пропускаем списки (это не инструкции)
                        pass
                    next_el = next_el.find_next_sibling()
            
            # Если всё ещё не нашли, берем параграфы после UL
            if not instructions and ul:
                next_el = ul.find_next_sibling()
                while next_el:
                    if next_el.name == 'p':
                        text = self.clean_text(next_el.get_text())
                        if text and len(text) > 15 and 'читати також' not in text.lower():
                            if not (len(text) < 100 and any(emoji in text for emoji in ['🎄', '👼', '🍑', '🍌', '🍒', '🍇', '🍓', '🌱'])):
                                instructions.append(text)
                    elif next_el.name in ['h2', 'h3', 'h4']:
                        break
                    elif next_el.name == 'ol':
                        for li in next_el.find_all('li'):
                            text = self.clean_text(li.get_text())
                            if text:
                                instructions.append(text)
                    next_el = next_el.find_next_sibling()
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Ищем articleSection в BlogPosting
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BlogPosting' and 'articleSection' in item:
                            section = item['articleSection']
                            # Берем первую категорию из списка
                            if isinstance(section, str):
                                categories = [s.strip() for s in section.split(',')]
                                # Ищем категорию "Dessert" или переводим украинские
                                for cat in categories:
                                    if cat.lower() in ['смаколики', 'десерт', 'десерти']:
                                        return 'Dessert'
                                    elif cat.lower() in ['салат', 'салати']:
                                        return 'Salad'
                                    elif cat.lower() in ['закуск', 'страв']:
                                        return 'Main Course'
                                # Возвращаем первую категорию
                                return categories[0] if categories else None
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из cat-links
        cat_links = self.soup.find('span', class_='cat-links')
        if cat_links:
            links = cat_links.find_all('a', rel=lambda x: x and 'category' in x)
            if links:
                category = self.clean_text(links[0].get_text())
                # Переводим на английский
                if category.lower() in ['смаколики', 'десерт', 'десерти']:
                    return 'Dessert'
                return category
        
        return None
    
    def extract_time_from_text(self, text: str, time_type: str) -> Optional[str]:
        """
        Извлечение времени из текста инструкций
        
        Args:
            text: текст рецепта
            time_type: 'prep', 'cook', или 'total'
        """
        if not text:
            return None
        
        # Паттерны для времени приготовления
        prep_patterns = [
            r'приблизно\s+(\d+)\s+хвилин',  # "приблизно 20 хвилин"
        ]
        
        cook_patterns = [
            r'(?:варити|випікати|готувати|смажити).*?(\d+)[–-](\d+)\s+хвилин',  # "випікати 25-35 хвилин"
            r'(?:варити|випікати|готувати).*?(\d+)\s+хвилин',  # "варити 20 хвилин"
        ]
        
        total_patterns = [
            r'загальний\s+час.*?(\d+)\s+хвилин',
        ]
        
        patterns = {
            'prep': prep_patterns,
            'cook': cook_patterns,
            'total': total_patterns
        }
        
        for pattern in patterns.get(time_type, []):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                if len(match.groups()) == 2:
                    # Диапазон времени - берем максимум
                    return f"{match.group(2)} minutes"
                else:
                    return f"{match.group(1)} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        instructions = self.extract_instructions()
        if instructions:
            return self.extract_time_from_text(instructions, 'prep')
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        instructions = self.extract_instructions()
        if instructions:
            return self.extract_time_from_text(instructions, 'cook')
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Можем попытаться вычислить из prep + cook
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep and cook:
            try:
                prep_mins = int(re.search(r'(\d+)', prep).group(1))
                cook_mins = int(re.search(r'(\d+)', cook).group(1))
                return f"{prep_mins + cook_mins} minutes"
            except:
                pass
        
        # Или из текста
        instructions = self.extract_instructions()
        if instructions:
            result = self.extract_time_from_text(instructions, 'total')
            if result:
                return result
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок к рецепту"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Заметки обычно идут после основных инструкций
        # Ищем параграфы после UL (ингредиенты)
        ul = entry_content.find('ul')
        if ul:
            next_el = ul.find_next_sibling()
            paragraphs = []
            
            # Собираем все параграфы после UL
            while next_el:
                if next_el.name == 'p':
                    text = self.clean_text(next_el.get_text())
                    if text and 'читати також' not in text.lower():
                        paragraphs.append(text)
                elif next_el.name in ['h2', 'h3', 'h4']:
                    break
                next_el = next_el.find_next_sibling()
            
            # Заметки обычно содержат ключевые слова и имеют определенную длину
            for para in paragraphs:
                # Заметки: средней длины (50-300 символов) и содержат ключевые слова
                if 50 < len(para) < 350:
                    keywords = ['охолоджений', 'можна', 'при потребі', 'втрачає', 'краще брати', 
                                'надає', 'тримати в холодильнику', 'зберігати', 'для компотів']
                    if any(keyword in para.lower() for keyword in keywords):
                        # Но НЕ "за бажанням добавити" (это часть инструкции)
                        if 'за бажанням добав' not in para.lower():
                            return para
        
        # Альтернативный поиск: между ингредиентами и инструкциями
        found_ingredients = False
        found_recipe_section = False
        
        for elem in entry_content.find_all(['h2', 'h3', 'p'], recursive=False):
            if elem.name in ['h2', 'h3']:
                text = elem.get_text().lower()
                if 'нгредієнт' in text:
                    found_ingredients = True
                elif 'рецепт' in text or 'покроков' in text:
                    found_recipe_section = True
            
            # Между ингредиентами и рецептом
            if found_ingredients and not found_recipe_section and elem.name == 'p':
                text = self.clean_text(elem.get_text())
                if text and 20 < len(text) < 250:
                    if any(phrase in text.lower() for phrase in ['за бажанням', 'можна додати', 'порада', 'совет']):
                        return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта"""
        # Пытаемся извлечь из JSON-LD articleSection, но берем только короткие релевантные теги
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Ищем articleSection в BlogPosting
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BlogPosting' and 'articleSection' in item:
                            section = item['articleSection']
                            if isinstance(section, str):
                                # Разбиваем на теги
                                all_tags = [self.clean_text(s) for s in section.split(',')]
                                
                                # Фильтруем: оставляем только короткие релевантные теги
                                # Пропускаем: категории, длинные фразы, повторы
                                filtered_tags = []
                                skip_patterns = [
                                    'смаколики', 'цікаве та корисне', 'страви',
                                    'для подтеков', 'для прослойки', 'для прошарку', 
                                    'під мастику', 'под мастику', 'пошаговий рецепт',
                                    'рецепт приготування', 'для украшения'
                                ]
                                
                                seen = set()
                                for tag in all_tags:
                                    tag_lower = tag.lower()
                                    # Берем короткие теги (1-2 слова, не более 20 символов)
                                    words = tag.split()
                                    if 1 <= len(words) <= 2 and len(tag) <= 20:
                                        # Пропускаем стоп-фразы
                                        if not any(skip in tag_lower for skip in skip_patterns):
                                            # Извлекаем ключевые слова из тега
                                            # Например, из "ганаш рецепт" берем "ганаш"
                                            # из "шоколадний ганаш" берем оба слова
                                            key_words = []
                                            for word in words:
                                                if word.lower() not in ['рецепт', 'приготування', 'для', 'на', 'з', 'с']:
                                                    key_words.append(word.lower())
                                            
                                            for kw in key_words:
                                                if kw not in seen and len(kw) > 2:
                                                    filtered_tags.append(kw)
                                                    seen.add(kw)
                                
                                if filtered_tags:
                                    return ', '.join(filtered_tags[:8])  # Максимум 8 тегов
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        image_urls = []
        
        # Ищем изображения в entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            images = entry_content.find_all('img')
            for img in images:
                src = img.get('src') or img.get('data-src')
                if src and src.startswith('http'):
                    # Избегаем дубликатов
                    if src not in image_urls:
                        image_urls.append(src)
        
        # Также проверяем JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BlogPosting' and 'image' in item:
                            img_data = item['image']
                            if isinstance(img_data, dict) and 'url' in img_data:
                                url = img_data['url']
                                if url and url not in image_urls:
                                    image_urls.append(url)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return ','.join(image_urls) if image_urls else None
    
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
    # Обрабатываем папку preprocessed/rodzunka_com_ua
    recipes_dir = os.path.join("preprocessed", "rodzunka_com_ua")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(RodzunkaComUaExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python rodzunka_com_ua.py")


if __name__ == "__main__":
    main()
