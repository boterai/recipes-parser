"""
Экстрактор данных рецептов для сайта cucinareok.it
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CucinareokExtractor(BaseRecipeExtractor):
    """Экстрактор для cucinareok.it"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке H1
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            title = self.clean_text(h1.get_text())
            # Убираем вопросительные префиксы и лишний текст
            title = re.sub(r'^¿\s*', '', title)  # Убираем ¿ в начале
            title = re.sub(r'\?\s*.*$', '', title)  # Убираем ? и все после него
            # Убираем распространенные префиксы
            title = re.sub(r'^(Ricetta|Recipe|Delizioso|Delicious)\s+', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - cucinareok"
            title = re.sub(r'\s+-\s+cucinareok.*$', '', title, flags=re.IGNORECASE)
            # Убираем вопросительные префиксы
            title = re.sub(r'^¿\s*', '', title)
            title = re.sub(r'\?\s*.*$', '', title)
            title = re.sub(r'^(Ricetta|Recipe|Delizioso|Delicious)\s+', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
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
        
        # Попробуем взять первый параграф из entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            paragraphs = entry_content.find_all('p')
            for p in paragraphs:
                text = self.clean_text(p.get_text())
                # Пропускаем пустые параграфы и параграфы с изображениями
                if text and len(text) > 30 and not p.find('img'):
                    return text
        
        return None
    
    def extract_ingredients(self) -> Optional[list]:
        """Извлечение ингредиентов"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        ingredients = []
        
        # Стратегия 1: Ищем заголовок с ключевыми словами "Ingredienti"
        headings = entry_content.find_all(['h2', 'h3', 'h4'])
        ingredient_heading = None
        
        for h in headings:
            text = h.get_text().strip().lower()
            if any(keyword in text for keyword in ['ingredienti', 'ingredients', 'ingrediente']):
                ingredient_heading = h
                break
        
        if ingredient_heading:
            # Ищем следующий UL список после этого заголовка
            current = ingredient_heading.find_next_sibling()
            while current:
                if current.name == 'ul':
                    items = current.find_all('li')
                    for item in items:
                        ingredient_text = item.get_text(separator=' ', strip=True)
                        ingredient_text = self.clean_text(ingredient_text)
                        if ingredient_text:
                            parsed = self.parse_ingredient(ingredient_text)
                            if parsed:
                                ingredients.append(parsed)
                    break
                # Если встретили следующий заголовок, прекращаем поиск
                elif current.name in ['h2', 'h3', 'h4']:
                    break
                current = current.find_next_sibling()
        
        # Стратегия 2: Если не нашли по заголовку, берем последний UL список
        if not ingredients:
            all_ul = entry_content.find_all('ul')
            if all_ul:
                # Берем последний или предпоследний UL (обычно последний - это ингредиенты)
                for ul in reversed(all_ul):
                    items = ul.find_all('li')
                    temp_ingredients = []
                    for item in items:
                        ingredient_text = item.get_text(separator=' ', strip=True)
                        ingredient_text = self.clean_text(ingredient_text)
                        if ingredient_text:
                            parsed = self.parse_ingredient(ingredient_text)
                            if parsed:
                                temp_ingredients.append(parsed)
                    
                    # Если нашли ингредиенты (обычно больше 2 элементов), возвращаем
                    if len(temp_ingredients) >= 2:
                        ingredients = temp_ingredients
                        break
        
        return ingredients if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "2 chili di carne macinata" или "1 confezione di zuppa"
            
        Returns:
            dict: {"name": "carne macinata", "amount": "2", "unit": "pounds"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
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
        # Примеры: "2 libbre di carne", "1 1/2 tazze di pangrattato"
        # Единицы измерения на итальянском и английском
        unit_pattern = (
            r'(?:tazz[ae]|tazza|cucchiai[oa]|cucchiaino|cucchiai|'
            r'libbre?|libra|chili|chilogramm[io]|gramm[io]|kg|g|'
            r'confezione|confezioni|pack|pezz[io]|pezzo|'
            r'barretta|barrette|bar|'
            r'uov[ao]|uova|unit[aà]|'
            r'cups?|tablespoons?|teaspoons?|tbsps?|tsps?|'
            r'pounds?|ounces?|lbs?|oz|grams?|kilograms?|'
            r'milliliters?|liters?|ml|l|'
            r'pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?)'
        )
        
        pattern = rf'^([\d\s/.,]+)?\s*({unit_pattern})?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "unit": None
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
        
        # Обработка единицы измерения - нормализация итальянских единиц
        if unit:
            unit = unit.strip().lower()
            # Нормализуем к более стандартным единицам
            unit_map = {
                'tazza': 'cups',
                'tazze': 'cups',
                'cucchiaio': 'tablespoon',
                'cucchiai': 'tablespoon',
                'cucchiaino': 'teaspoon',
                'libbre': 'pounds',
                'libra': 'pounds',
                'libbra': 'pounds',
                'chili': 'pounds',
                'grammi': 'g',
                'grammo': 'g',
                'chilogrammi': 'kg',
                'chilogrammo': 'kg',
                'confezione': 'pack',
                'confezioni': 'pack',
                'pezzo': 'units',
                'pezzi': 'units',
                'barretta': 'bar',
                'barrette': 'bar',
                'uovo': 'units',
                'uova': 'units',
                'unità': 'units',
                'l': 'liters',  # Литры
                'ml': 'ml',  # Миллилитры
            }
            unit = unit_map.get(unit, unit)
        
        # Очистка названия
        # Удаляем предлоги типа "di" в начале
        name = re.sub(r'^(di|d\'|de|del|della|dei|degli)\s+', '', name)
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "a piacere", "q.b.", "opzionale"
        name = re.sub(r'\b(a piacere|q\.?b\.?|opzionale|facoltativo|to taste|as needed|optional)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        steps = []
        
        # Стратегия 1: Ищем заголовки, связанные с инструкциями
        headings = entry_content.find_all(['h2', 'h3', 'h4'])
        instruction_keywords = ['procedimento', 'preparazione', 'istruzioni', 'instructions', 'directions', 'come preparare', 'procedura']
        
        for h in headings:
            heading_text = h.get_text().strip().lower()
            
            # Проверяем, содержит ли заголовок ключевое слово инструкций
            if any(keyword in heading_text for keyword in instruction_keywords):
                # Ищем следующий OL или UL список после этого заголовка
                current = h.find_next_sibling()
                while current:
                    if current.name in ['ol', 'ul']:
                        items = current.find_all('li')
                        for idx, item in enumerate(items, 1):
                            step_text = item.get_text(separator=' ', strip=True)
                            step_text = self.clean_text(step_text)
                            if step_text:
                                # Если шаг уже начинается с номера, оставляем как есть
                                if re.match(r'^\d+\.', step_text):
                                    steps.append(step_text)
                                else:
                                    steps.append(f"{idx}. {step_text}")
                        break
                    # Если встретили следующий заголовок, прекращаем поиск
                    elif current.name in ['h2', 'h3', 'h4']:
                        break
                    current = current.find_next_sibling()
                
                if steps:
                    break
        
        # Стратегия 2: Если не нашли по заголовку, берем последний OL список
        if not steps:
            all_ol = entry_content.find_all('ol')
            if all_ol:
                # Берем последний OL (обычно это инструкции)
                ol = all_ol[-1]
                items = ol.find_all('li')
                for idx, item in enumerate(items, 1):
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    if step_text:
                        # Если шаг уже начинается с номера, оставляем как есть
                        if re.match(r'^\d+\.', step_text):
                            steps.append(step_text)
                        else:
                            steps.append(f"{idx}. {step_text}")
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в breadcrumbs (хлебные крошки)
        breadcrumb_list = self.soup.find('script', type='application/ld+json')
        if breadcrumb_list:
            try:
                data = json.loads(breadcrumb_list.string)
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BreadcrumbList':
                            items = item.get('itemListElement', [])
                            # Берем предпоследний элемент (категория перед самим рецептом)
                            if len(items) >= 2:
                                category_item = items[-2]
                                if 'item' in category_item and 'name' in category_item['item']:
                                    return self.clean_text(category_item['item']['name'])
            except (json.JSONDecodeError, KeyError):
                pass
        
        # Альтернативно - ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_time_from_text(self, text: str) -> Optional[str]:
        """
        Извлекает время из текста
        
        Args:
            text: Текст, содержащий информацию о времени
            
        Returns:
            Время в формате "X minutes" или "X hours Y minutes"
        """
        if not text:
            return None
        
        # Паттерны для извлечения времени
        # Примеры: "10 minuti", "1 ora", "1 ora e 30 minuti", "60 minutes", "1 hour"
        
        # Часы
        hour_pattern = r'(\d+)\s*(ora|ore|hour|hours)'
        # Минуты
        minute_pattern = r'(\d+)\s*(minut[io]|minutes?)'
        
        hours = 0
        minutes = 0
        
        hour_match = re.search(hour_pattern, text, re.IGNORECASE)
        if hour_match:
            hours = int(hour_match.group(1))
        
        minute_match = re.search(minute_pattern, text, re.IGNORECASE)
        if minute_match:
            minutes = int(minute_match.group(1))
        
        if hours > 0 and minutes > 0:
            return f"{hours * 60 + minutes} minutes"
        elif hours > 0:
            return f"{hours * 60} minutes"
        elif minutes > 0:
            return f"{minutes} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем текст с временем подготовки
        text_content = entry_content.get_text()
        
        # Паттерны для поиска времени подготовки
        patterns = [
            r'tempo di preparazione[:\s]+([^\.]+)',
            r'prep time[:\s]+([^\.]+)',
            r'preparazione[:\s]+([^\.]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                time_text = match.group(1)
                extracted_time = self.extract_time_from_text(time_text)
                if extracted_time:
                    return extracted_time
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем текст с временем приготовления
        text_content = entry_content.get_text()
        
        # Паттерны для поиска времени приготовления
        patterns = [
            r'tempo di cottura[:\s]+([^\.]+)',
            r'cook time[:\s]+([^\.]+)',
            r'cottura[:\s]+([^\.]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                time_text = match.group(1)
                extracted_time = self.extract_time_from_text(time_text)
                if extracted_time:
                    return extracted_time
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем текст с общим временем
        text_content = entry_content.get_text()
        
        # Паттерны для поиска общего времени
        patterns = [
            r'tempo totale[:\s]+([^\.]+)',
            r'total time[:\s]+([^\.]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                time_text = match.group(1)
                extracted_time = self.extract_time_from_text(time_text)
                if extracted_time:
                    return extracted_time
        
        # Если не нашли, попробуем сложить prep_time и cook_time
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        
        if prep_time and cook_time:
            prep_match = re.search(r'(\d+)', prep_time)
            cook_match = re.search(r'(\d+)', cook_time)
            if prep_match and cook_match:
                prep_minutes = int(prep_match.group(1))
                cook_minutes = int(cook_match.group(1))
                total_minutes = prep_minutes + cook_minutes
                return f"{total_minutes} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем параграфы или секции с примечаниями
        # Обычно заметки находятся после инструкций
        headings = entry_content.find_all(['h2', 'h3', 'h4'])
        
        for h in headings:
            heading_text = h.get_text().strip().lower()
            # Ключевые слова для заметок
            if any(keyword in heading_text for keyword in ['note', 'consigli', 'suggerimenti', 'tips', 'tricks']):
                # Собираем текст из параграфов после этого заголовка
                notes_parts = []
                current = h.find_next_sibling()
                while current:
                    if current.name == 'p':
                        text = self.clean_text(current.get_text())
                        if text:
                            notes_parts.append(text)
                    elif current.name in ['h2', 'h3', 'h4']:
                        break
                    current = current.find_next_sibling()
                
                if notes_parts:
                    return ' '.join(notes_parts)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags.extend([tag.strip() for tag in keywords.split(',') if tag.strip()])
        
        # Ищем в article:tag
        article_tags = self.soup.find_all('meta', property='article:tag')
        for tag_meta in article_tags:
            if tag_meta.get('content'):
                tags.append(tag_meta['content'].strip())
        
        if tags:
            # Удаляем дубликаты, сохраняя порядок
            seen = set()
            unique_tags = []
            for tag in tags:
                tag_lower = tag.lower()
                if tag_lower not in seen:
                    seen.add(tag_lower)
                    unique_tags.append(tag_lower)
            
            return ', '.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                if '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 3. Ищем изображения в entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            images = entry_content.find_all('img', src=True)
            for img in images[:5]:  # Ограничиваем количество
                src = img.get('src')
                if src and 'http' in src:  # Только полные URL
                    urls.append(src)
        
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
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        total_time = self.extract_total_time()
        notes = self.extract_notes()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()
        
        # Форматируем ingredients как JSON-строку
        ingredients_json = None
        if ingredients:
            ingredients_json = json.dumps(ingredients, ensure_ascii=False)
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients_json,
            "instructions": instructions,
            "category": category,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "notes": notes,
            "tags": tags,
            "image_urls": image_urls
        }


def main():
    import os
    # Обрабатываем папку preprocessed/cucinareok_it
    recipes_dir = os.path.join("preprocessed", "cucinareok_it")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(CucinareokExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python cucinareok_it.py")


if __name__ == "__main__":
    main()
