"""
Экстрактор данных рецептов для сайта mr-m.co.il
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MrMExtractor(BaseRecipeExtractor):
    """Экстрактор для mr-m.co.il"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в мета-теге og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Альтернативно - из JSON-LD Article
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'headline' in item:
                            # Декодируем HTML entities
                            import html
                            headline = html.unescape(item['headline'])
                            return self.clean_text(headline)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # В крайнем случае - из title
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем суффиксы сайта
            title = re.sub(r'\s*[-–—]\s*MR-M.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем все элементы с классом jet-listing-dynamic-field__content
        ingredient_elements = self.soup.find_all('span', class_='jet-listing-dynamic-field__content')
        
        for elem in ingredient_elements:
            ingredient_text = elem.get_text(strip=True)
            ingredient_text = self.clean_text(ingredient_text)
            
            if ingredient_text:
                # Парсим ингредиент в структурированный формат
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "8 גזרים" или "כף גדושה מלח"
            
        Returns:
            dict: {"name": "...", "amount": "...", "units": "..."} или None
        """
        if not ingredient_text:
            return None
        
        text = self.clean_text(ingredient_text)
        
        # Сначала проверяем специальные случаи с единицами в начале (например "כף גדושה מלח")
        # Важно: проверяем ДО того, как будем искать числа, чтобы избежать ложных совпадений
        unit_patterns = {
            r'^(כפות)\s+': 'tablespoon',
            r'^(כף)\s+': 'tablespoon',
            r'^(כפית)\s+': 'teaspoon',
            r'^(כפיות)\s+': 'teaspoon',
        }
        
        for pattern, unit_en in unit_patterns.items():
            match = re.match(pattern, text)
            if match:
                name = text[match.end():].strip()
                # Убираем слова типа "גדושה" (полная/heaping)
                name = re.sub(r'^(גדושה|גדוש|שטוחה|שטוח)\s+', '', name)
                
                # Проверяем, есть ли количество в названии (например "כף 200 גרם מרגרינה")
                num_in_name = re.search(r'^([\d\.\,\/]+)\s+', name)
                if num_in_name:
                    amount = num_in_name.group(1)
                    name = name[num_in_name.end():].strip()
                else:
                    amount = 1  # По умолчанию 1, если не указано
                
                return {
                    "name": name,
                    "amount": amount,
                    "units": unit_en
                }
        
        # Паттерн для извлечения количества в начале
        pattern_with_number = r'^([\d\.\,\/\u00BC-\u00BE\u2150-\u215E]+)\s+(.+)$'
        match = re.match(pattern_with_number, text)
        
        if match:
            amount_str, rest = match.groups()
            amount = amount_str.strip()
            
            # Обработка дробей
            if '/' in amount:
                parts = amount.split('/')
                if len(parts) == 2:
                    try:
                        amount = float(parts[0]) / float(parts[1])
                    except:
                        pass
            
            # Теперь ищем единицы измерения в остатке
            # Используем более специфичные паттерны, чтобы избежать ложных совпадений
            units_patterns = [
                (r'\s+ק[״"]ג\b', 'kg'),  # ק"ג или ק״ג
                (r'\s+קג\b', 'kg'),
                (r'\s+כוסות\b', 'cups'),
                (r'\s+כוס\b', 'cups'),
                (r'\s+גביעים\b', 'cups'),
                (r'\s+גביע\b', 'cups'),
                (r'\s+גרם\b', 'grams'),
                (r'\s+ליטר\b', 'liters'),
                (r'\s+מ[״"]ל\b', 'ml'),
                (r'\s+מל\b', 'ml'),
                (r'\bcups?\b', 'cups'),
                (r'\btablespoons?\b', 'tablespoon'),
                (r'\bteaspoons?\b', 'teaspoon'),
                (r'\bgrams?\b', 'grams'),
                (r'\bkg\b', 'kg'),
            ]
            
            unit = None
            name = rest
            
            for pattern, unit_en in units_patterns:
                if re.search(pattern, rest, re.IGNORECASE):
                    unit = unit_en
                    name = re.sub(pattern, '', rest, flags=re.IGNORECASE).strip()
                    break
            
            # Очистка названия от дополнительной информации в скобках
            name = re.sub(r'\([^)]*\)', '', name).strip()
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        
        # Если паттерн не совпал, возвращаем как есть
        # Пропускаем секции-заголовки (обычно заканчиваются двоеточием)
        if text.endswith(':'):
            return None
        
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions = []
        
        # Ищем заголовок "אופן הכנה" (способ приготовления)
        prep_heading = self.soup.find('h2', id=re.compile(r'h-אופן-הכנה', re.I))
        if not prep_heading:
            prep_heading = self.soup.find('h2', string=re.compile(r'אופן הכנה', re.I))
        
        if prep_heading:
            # Ищем следующий элемент после заголовка
            current = prep_heading.find_next_sibling()
            
            while current:
                # Если встретили следующий заголовок, прекращаем
                if current.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                    break
                
                # Извлекаем текст из параграфов и списков
                if current.name == 'p':
                    text = current.get_text(separator=' ', strip=True)
                    text = self.clean_text(text)
                    if text:
                        instructions.append(text)
                elif current.name in ['ul', 'ol']:
                    items = current.find_all('li')
                    for item in items:
                        text = item.get_text(separator=' ', strip=True)
                        text = self.clean_text(text)
                        if text:
                            instructions.append(text)
                
                current = current.find_next_sibling()
        
        # Если не нашли через заголовок, пробуем найти в основном контенте
        if not instructions:
            # Ищем элементы с классом elementor-text-editor
            content_divs = self.soup.find_all('div', class_='elementor-text-editor')
            for div in content_divs:
                paragraphs = div.find_all('p')
                for p in paragraphs:
                    text = p.get_text(separator=' ', strip=True)
                    text = self.clean_text(text)
                    # Фильтруем слишком короткие строки
                    if text and len(text) > 20:
                        instructions.append(text)
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в JSON-LD Article
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list) and sections:
                                # Берем первую категорию
                                return self.clean_text(sections[0])
                            elif isinstance(sections, str):
                                return self.clean_text(sections)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из хлебных крошек
        breadcrumbs = self.soup.find('nav', class_='woocommerce-breadcrumb')
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:  # Берем вторую ссылку (первая - главная)
                return self.clean_text(links[1].get_text())
        
        return None
    
    def extract_time_from_icon_list(self, time_label: str) -> Optional[str]:
        """
        Извлечение времени из элементов icon list
        
        Args:
            time_label: Метка времени ('הכנה', 'בישול' и т.д.)
        """
        # Ищем все элементы с временем
        time_elements = self.soup.find_all('span', class_='elementor-icon-list-text')
        
        for elem in time_elements:
            text = elem.get_text(strip=True)
            # Проверяем, содержит ли текст нужную метку
            if time_label in text and 'דקות' in text:
                # Извлекаем число минут
                match = re.search(r'(\d+)\s*דקות', text)
                if match:
                    minutes = match.group(1)
                    return f"{minutes} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time_from_icon_list('הכנה')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time_from_icon_list('בישול')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time_from_icon_list('סה״כ')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем все параграфы на странице
        all_paragraphs = self.soup.find_all('p')
        
        for p in all_paragraphs:
            text = p.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            
            # Проверяем, похож ли текст на заметку
            # Заметки часто содержат упоминания о рецепте, советы и т.д.
            if text and len(text) > 30:
                # Заметки часто начинаются со слов типа "זוכרים" (помните), "טיפ" (совет) и т.д.
                # или содержат вопросительные предложения
                if any(keyword in text for keyword in ['זוכרים', 'טיפ', 'שימו לב', 'חשוב', 'המלצה', '?', 'אז קבלו']):
                    # Проверяем, что это не инструкция (инструкции обычно короче и более директивные)
                    # и не начинаются с глаголов в повелительном наклонении типа "מחממים", "חותכים"
                    instruction_verbs = ['מחממים', 'חותכים', 'מפזרים', 'מערבבים', 'מניחים', 'מכניסים', 
                                       'מוציאים', 'מורידים', 'מחזירים', 'מגבירים', 'מסובבים', 'מכבים']
                    if not any(text.startswith(verb) for verb in instruction_verbs):
                        notes.append(text)
        
        # Если нашли заметки, возвращаем первую (обычно самая релевантная)
        return notes[0] if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в JSON-LD Article
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'keywords' in item:
                            keywords = item['keywords']
                            if isinstance(keywords, list):
                                # Фильтруем и очищаем теги
                                tags = [self.clean_text(tag) for tag in keywords if tag]
                                return ', '.join(tags) if tags else None
                            elif isinstance(keywords, str):
                                return self.clean_text(keywords)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в meta og:image (обычно главное изображение)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if '@graph' in data:
                    for item in data['@graph']:
                        # Ищем ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 3. Ищем в галерее (e-gallery-item)
        gallery_items = self.soup.find_all('a', class_='e-gallery-item')
        for item in gallery_items[:5]:  # Ограничиваем количество
            if item.get('href'):
                urls.append(item['href'])
        
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
    """Обработка директории с HTML файлами mr-m.co.il"""
    import os
    
    # Путь к директории с примерами
    preprocessed_dir = os.path.join("preprocessed", "mr-m_co_il")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(MrMExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python mr-m_co_il.py")


if __name__ == "__main__":
    main()
