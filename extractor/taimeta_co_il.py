"""
Экстрактор данных рецептов для сайта taimeta.co.il
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TaimetaExtractor(BaseRecipeExtractor):
    """Экстрактор для taimeta.co.il"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке H1
        h1 = self.soup.find('h1', class_=re.compile(r'gb-headline'))
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффикс сайта
            title = re.sub(r'\s*\|\s*טעימתא\s*$', '', title)
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
        
        return None
    
    def parse_ingredient_item(self, item_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            item_text: Строка вида "פילה בקר טרי ונקי מגידים – 850 גרם"
            
        Returns:
            dict: {"name": "פילה בקר", "amount": 850, "units": "grams"} или None
        """
        if not item_text:
            return None
        
        # Чистим текст
        text = self.clean_text(item_text)
        
        # Паттерн: name – amount unit (description)
        # Примеры: 
        # "פילה בקר טרי ונקי מגידים – 850 גרם"
        # "שמן זית כתית מעולה – 2 כפות"
        # "ענף רוזמרין טרי – 1"
        # "3 שיני שום טריות, קלופות וכתושות" (начинается с числа)
        
        # Разделяем по тире или двоеточию
        if '–' in text:
            parts = text.split('–', 1)
        elif '-' in text:
            parts = text.split('-', 1)
        elif ':' in text:
            parts = text.split(':', 1)
        else:
            # Нет разделителя, но может начинаться с числа
            # Паттерн: "3 שיני שום..."
            num_start_match = re.match(r'^(\d+(?:[.,/]\d+)?)\s+(.+)', text)
            if num_start_match:
                amount_str = num_start_match.group(1)
                name_part = num_start_match.group(2)
                
                # Обрабатываем число
                amount = self._normalize_amount(amount_str)
                
                return {
                    "name": name_part,
                    "amount": amount,
                    "units": None
                }
            
            # Совсем нет количества
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        if len(parts) != 2:
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        name_part = parts[0].strip()
        quantity_part = parts[1].strip()
        
        # Извлекаем количество и единицу измерения из второй части
        # Паттерн для чисел (включая дроби и десятичные)
        number_pattern = r'^([\d\s/.,½¼¾⅓⅔⅛⅜⅝⅞]+)'
        
        # Словарь единиц измерения на иврите
        unit_map = {
            'גרם': 'grams',
            'גרמים': 'grams',
            'ג\'': 'grams',
            'גר\'': 'grams',
            'קילוגרם': 'kilograms',
            'ק"ג': 'kilograms',
            'מ"ל': 'ml',
            'מיליליטר': 'ml',
            'ליטר': 'liter',
            'כפות': 'tablespoons',
            'כפית': 'teaspoons',
            'כפיות': 'teaspoons',
            'כף': 'tablespoon',
            'כוס': 'cup',
            'כוסות': 'cups',
            'יחידה': 'unit',
            'יחידות': 'units',
            'פרוס': 'slice',
            'פרוסות': 'slices',
            'שיני': 'cloves',
            'שן': 'clove'
        }
        
        # Удаляем текст в скобках из названия ингредиента
        name_part = re.sub(r'\([^)]*\)', '', name_part).strip()
        
        # Пытаемся найти число
        amount = None
        unit = None
        
        # Сначала проверяем паттерн "unit word-number" (например, "כף אחת")
        unit_word_pattern = r'^(' + '|'.join(unit_map.keys()) + r')\s+(אחת|אחד|שתיים|שתי|שלוש|שלושה|ארבע|ארבעה|חמש|חמישה)'
        unit_word_match = re.match(unit_word_pattern, quantity_part)
        
        if unit_word_match:
            hebrew_unit = unit_word_match.group(1)
            word_num = unit_word_match.group(2)
            
            unit = unit_map.get(hebrew_unit)
            
            word_to_num = {
                'אחת': 1, 'אחד': 1,
                'שתיים': 2, 'שתי': 2,
                'שלוש': 3, 'שלושה': 3,
                'ארבע': 4, 'ארבעה': 4,
                'חמש': 5, 'חמישה': 5
            }
            amount = word_to_num.get(word_num, 1)
            
            # Для amount=1 используем единственное число
            if amount == 1 and unit and unit.endswith('s'):
                unit = unit[:-1]
        
        # Ищем число в начале строки количества
        elif re.match(number_pattern, quantity_part):
            match = re.match(number_pattern, quantity_part)
            amount_str = match.group(1).strip()
            
            # Нормализуем количество
            amount = self._normalize_amount(amount_str)
            
            # Извлекаем единицу измерения после числа
            remaining = quantity_part[match.end():].strip()
            
            # Ищем единицу измерения в оставшемся тексте
            for hebrew_unit, eng_unit in unit_map.items():
                if remaining.startswith(hebrew_unit):
                    unit = eng_unit
                    # Преобразуем множественное в единственное для amount=1
                    if amount == 1 and unit.endswith('s'):
                        unit = unit[:-1]
                    break
        else:
            # Число не найдено - может быть слово вроде "אחת" (одна)
            # Или просто описание без количества
            if quantity_part:
                # Ищем слова "אחת", "אחד" в начале
                word_number_match = re.match(r'^(אחת|אחד|שתיים|שתי|שלוש)\s+(.+)', quantity_part)
                if word_number_match:
                    word_num = word_number_match.group(1)
                    remaining = word_number_match.group(2)
                    
                    word_to_num = {
                        'אחת': 1, 'אחד': 1,
                        'שתיים': 2, 'שתי': 2,
                        'שלוש': 3
                    }
                    amount = word_to_num.get(word_num)
                    
                    # Ищем единицу
                    for hebrew_unit, eng_unit in unit_map.items():
                        if remaining.startswith(hebrew_unit):
                            unit = eng_unit
                            # Для amount=1 используем единственное число
                            if amount == 1 and unit.endswith('s'):
                                unit = unit[:-1]
                            break
        
        return {
            "name": name_part,
            "amount": amount,
            "units": unit
        }
    
    def _normalize_amount(self, amount_str: str) -> any:
        """
        Нормализация строки количества в число
        
        Args:
            amount_str: Строка с количеством, например "1.5", "1/2", "850"
            
        Returns:
            int или float в зависимости от значения
        """
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875'
        }
        
        for fraction, decimal in fraction_map.items():
            amount_str = amount_str.replace(fraction, decimal)
        
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
            
            # Возвращаем int если целое, иначе float
            return int(total) if total == int(total) else total
        else:
            amount_str = amount_str.replace(',', '.')
            try:
                amount_float = float(amount_str)
                # Если это целое число, возвращаем int
                if amount_float == int(amount_float):
                    return int(amount_float)
                else:
                    return amount_float
            except ValueError:
                return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем заголовок "רשימת מצרכים" и следующий за ним список
        headers = self.soup.find_all(['h2', 'h3'], string=re.compile(r'רשימת מצרכים|מצרכים|רכיבים'))
        
        for header in headers:
            # Ищем следующий <ul> после заголовка
            ul = header.find_next_sibling('ul')
            if not ul:
                # Может быть параграф между заголовком и списком
                ul = header.find_next('ul')
            
            if ul:
                items = ul.find_all('li')
                for item in items:
                    ingredient_text = item.get_text(separator=' ', strip=True)
                    ingredient_text = self.clean_text(ingredient_text)
                    
                    if ingredient_text:
                        parsed = self.parse_ingredient_item(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
                
                if ingredients:
                    break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем заголовок "אופן ההכנה" и следующий за ним список
        headers = self.soup.find_all(['h2', 'h3'], string=re.compile(r'אופן ההכנה|הוראות הכנה|הכנה'))
        
        for header in headers:
            # Ищем следующий <ol> после заголовка
            ol = header.find_next_sibling('ol')
            if not ol:
                # Может быть параграф между заголовком и списком
                ol = header.find_next('ol')
            
            if ol:
                items = ol.find_all('li')
                for item in items:
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    
                    if step_text:
                        steps.append(step_text)
                
                if steps:
                    break
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в метаданных article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в хлебных крошках через JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BreadcrumbList':
                            items = item.get('itemListElement', [])
                            # Берем предпоследний элемент (категория перед рецептом)
                            if len(items) >= 2:
                                category_item = items[-2]
                                if 'item' in category_item and 'name' in category_item['item']:
                                    return self.clean_text(category_item['item']['name'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_time_info(self) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Извлечение информации о времени приготовления
        
        Returns:
            Tuple (prep_time, cook_time, total_time)
        """
        prep_time = None
        cook_time = None
        total_time = None
        
        # Ищем div с классом gb-headline, содержащие информацию о времени
        time_divs = self.soup.find_all('div', class_=re.compile(r'gb-headline'))
        
        for div in time_divs:
            text_span = div.find('span', class_='gb-headline-text')
            if not text_span:
                continue
            
            text = text_span.get_text(strip=True)
            text = self.clean_text(text)
            
            # Ищем паттерны времени
            # "זמן עבודה: 20 דק'" или "זמן בישול: 15 דקות"
            if 'זמן עבודה' in text or 'זמן הכנה' in text:
                # Это prep_time
                time_match = re.search(r'(\d+)\s*דק', text)
                if time_match:
                    prep_time = f"{time_match.group(1)} minutes"
            
            elif 'זמן בישול' in text or 'זמן טיגון' in text or 'זמן צלייה' in text:
                # Это cook_time
                time_match = re.search(r'(\d+)\s*דק', text)
                if time_match:
                    cook_time = f"{time_match.group(1)} minutes"
            
            elif 'זמן כולל' in text or 'סה"כ' in text:
                # Это total_time
                time_match = re.search(r'(\d+)\s*דק', text)
                if time_match:
                    total_time = f"{time_match.group(1)} minutes"
        
        # Также ищем в тексте "על המתכון"
        about_headers = self.soup.find_all(['h2', 'h3'], string=re.compile(r'על המתכון'))
        for header in about_headers:
            # Ищем следующие параграфы
            next_p = header.find_next('p')
            if next_p:
                text = next_p.get_text()
                
                # Паттерны: "כ־20 דקות של הכנה", "15 דקות של בישול"
                prep_match = re.search(r'כ?[־-]?(\d+)\s*דק(?:ות)?\s+(?:של\s+)?הכנה', text)
                if prep_match and not prep_time:
                    prep_time = f"{prep_match.group(1)} minutes"
                
                cook_match = re.search(r'כ?[־-]?(\d+)\s*דק(?:ות)?\s+(?:של\s+)?(?:בישול|צלייה|טיגון)', text)
                if cook_match and not cook_time:
                    cook_time = f"{cook_match.group(1)} minutes"
                
                total_match = re.search(r'סה["\']כ\s+כ?[־-]?(\d+)\s*דק(?:ות)?', text)
                if total_match and not total_time:
                    total_time = f"{total_match.group(1)} minutes"
        
        return prep_time, cook_time, total_time
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        prep, _, _ = self.extract_time_info()
        return prep
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        _, cook, _ = self.extract_time_info()
        return cook
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        prep, cook, total = self.extract_time_info()
        
        # Если total_time не найден явно, но есть prep и cook - вычисляем
        if not total and prep and cook:
            try:
                prep_mins = int(re.search(r'(\d+)', prep).group(1))
                cook_mins = int(re.search(r'(\d+)', cook).group(1))
                total = f"{prep_mins + cook_mins} minutes"
            except (AttributeError, ValueError):
                pass
        
        return total
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем секцию "טיפים והמלצות"
        headers = self.soup.find_all(['h2', 'h3'], string=re.compile(r'טיפים והמלצות|טיפים|המלצות|הערות'))
        
        for header in headers:
            # Собираем все параграфы после заголовка до следующего заголовка
            current = header.find_next_sibling()
            
            while current:
                if current.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                    # Достигли следующего заголовка
                    break
                
                if current.name == 'p':
                    text = current.get_text(separator=' ', strip=True)
                    text = self.clean_text(text)
                    
                    # Пропускаем параграфы со ссылками на другие рецепты
                    # Такие параграфы часто содержат фразы типа "אולי תאהבו גם"
                    if text and not any(phrase in text for phrase in ['אולי תאהבו', 'מתכונים נוספים', 'קראו גם']):
                        # Также фильтруем параграфы с большим количеством ссылок
                        links = current.find_all('a')
                        if len(links) <= 2:  # Разрешаем максимум 2 ссылки в параграфе заметок
                            notes.append(text)
                
                current = current.find_next_sibling()
            
            if notes:
                break
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                if '@graph' in data:
                    for item in data['@graph']:
                        # Ищем BlogPosting или Article
                        if item.get('@type') in ['BlogPosting', 'Article']:
                            # Проверяем keywords
                            if 'keywords' in item:
                                keywords = item['keywords']
                                if isinstance(keywords, list):
                                    tags.extend(keywords)
                                elif isinstance(keywords, str):
                                    tags.extend([k.strip() for k in keywords.split(',')])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если не нашли в JSON-LD, пробуем из category
        if not tags:
            category = self.extract_category()
            if category:
                tags.append(category)
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
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
        
        # 3. Ищем основное изображение рецепта в контенте
        # Ищем первое изображение в блоке рецепта
        recipe_container = self.soup.find('div', class_=re.compile(r'ak-recipe-page|recipe'))
        if recipe_container:
            img = recipe_container.find('img', class_=re.compile(r'gb-image'))
            if img and img.get('src'):
                urls.append(img['src'])
        
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
    import os
    # Обрабатываем папку preprocessed/taimeta_co_il
    preprocessed_dir = os.path.join("preprocessed", "taimeta_co_il")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(TaimetaExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python taimeta_co_il.py")


if __name__ == "__main__":
    main()
