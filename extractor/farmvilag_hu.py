"""
Экстрактор данных рецептов для сайта farmvilag.hu
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class FarmvilagExtractor(BaseRecipeExtractor):
    """Экстрактор для farmvilag.hu"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из h1.entry-title
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - FarmVilág"
            title = re.sub(r'\s*-\s*FarmVilág.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Еще один вариант - из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                # Обрабатываем @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'headline' in item:
                            headline = item['headline']
                            # Убираем суффиксы
                            headline = re.sub(r'\s*-\s*FarmVilág.*$', '', headline, flags=re.IGNORECASE)
                            return self.clean_text(headline)
            except (json.JSONDecodeError, KeyError):
                continue
        
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
        
        # Ищем секцию с заголовком "Hozzávalók" (Ingredients)
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем все h3 заголовки
        h3_tags = entry_content.find_all('h3')
        for h3 in h3_tags:
            h3_text = h3.get_text(strip=True)
            # Ищем заголовок ингредиентов
            if 'hozzávalók' in h3_text.lower() or 'ingredients' in h3_text.lower():
                # Следующий элемент после h3 должен быть ul или ol
                next_sibling = h3.find_next_sibling()
                while next_sibling:
                    if next_sibling.name in ['ul', 'ol']:
                        # Извлекаем li элементы
                        items = next_sibling.find_all('li')
                        for item in items:
                            ingredient_text = item.get_text(strip=True)
                            ingredient_text = self.clean_text(ingredient_text)
                            
                            if ingredient_text:
                                # Парсим ингредиент
                                parsed = self.parse_ingredient(ingredient_text)
                                if parsed:
                                    ingredients.append(parsed)
                        break
                    elif next_sibling.name in ['h2', 'h3', 'h4']:
                        # Если встретился новый заголовок - останавливаемся
                        break
                    next_sibling = next_sibling.find_next_sibling()
                
                if ingredients:
                    break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "500 g sima búzaliszt" или "1 teáskanál só"
            
        Returns:
            dict: {"name": "sima búzaliszt", "amount": "500", "unit": "g"} или None
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
        
        # Паттерн для извлечения количества (включая диапазоны), единицы и названия
        # Примеры: "500 g liszt", "1 teáskanál só", "350-400 ml vajtej"
        pattern = r'^([\d\s/.,\-]+)?\s*(g|kg|ml|l|dkg|dl|teáskanál|evőkanál|csipet|darab|csepp|gerezd|gramm|liter|milliliter|kilogramm|db|tk|ek)?\s*(.+)'
        
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
            # Обработка диапазонов типа "350-400"
            if '-' in amount_str and not amount_str.startswith('-'):
                # Берем первое значение из диапазона
                parts = amount_str.split('-')
                if parts and parts[0].strip():
                    amount_str = parts[0].strip()
            
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
                amount = total
            else:
                amount = amount_str.replace(',', '.')
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "ízlés szerint", "opcionális" и т.д.
        name = re.sub(r'\b(ízlés szerint|opcionális|optional|tetszés szerint)\b', '', name, flags=re.IGNORECASE)
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
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем секцию с заголовком "Elkészítés" (Preparation)
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем все h3 заголовки
        h3_tags = entry_content.find_all('h3')
        for h3 in h3_tags:
            h3_text = h3.get_text(strip=True)
            # Ищем заголовок инструкций
            if 'elkészítés' in h3_text.lower() or 'instructions' in h3_text.lower() or 'preparation' in h3_text.lower():
                # Следующий элемент после h3 должен быть ol или ul
                next_sibling = h3.find_next_sibling()
                while next_sibling:
                    if next_sibling.name in ['ol', 'ul']:
                        # Извлекаем li элементы
                        items = next_sibling.find_all('li')
                        for idx, item in enumerate(items, 1):
                            # Извлекаем текст инструкции
                            step_text = item.get_text(separator=' ', strip=True)
                            step_text = self.clean_text(step_text)
                            
                            if step_text:
                                # Добавляем номер, если его нет
                                if not re.match(r'^\d+\.', step_text):
                                    steps.append(f"{idx}. {step_text}")
                                else:
                                    steps.append(step_text)
                        break
                    elif next_sibling.name in ['h2', 'h3', 'h4']:
                        # Если встретился новый заголовок - останавливаемся
                        break
                    next_sibling = next_sibling.find_next_sibling()
                
                if steps:
                    break
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в div.mag-post-category
        category_div = self.soup.find('div', class_='mag-post-category')
        if category_div:
            link = category_div.find('a')
            if link:
                return self.clean_text(link.get_text())
        
        # Альтернативно - из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                # Обрабатываем @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list) and sections:
                                return self.clean_text(sections[0])
                            elif isinstance(sections, str):
                                return self.clean_text(sections)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_time_from_content(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени из текста контента
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Сначала пытаемся найти в заголовке страницы
        title = self.soup.find('title')
        if title:
            title_text = title.get_text()
            # Ищем "40 perc alatt" или подобные паттерны
            match = re.search(r'(\d+)\s*perc\s+alatt', title_text, re.IGNORECASE)
            if match and time_type == 'total':
                return f"{match.group(1)} minutes"
        
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Паттерны для поиска времени
        patterns = {
            'prep': [
                r'előkészítési?\s+idő[:\s]+(\d+(?:-\d+)?)\s*(perc|óra|minutes?|hours?)',
                r'prep(?:aration)?\s+time[:\s]+(\d+(?:-\d+)?)\s*(perc|óra|minutes?|hours?)',
            ],
            'cook': [
                r'sütési?\s+idő[:\s]+(\d+(?:-\d+)?)\s*(perc|óra|minutes?|hours?)',
                r'főzési?\s+idő[:\s]+(\d+(?:-\d+)?)\s*(perc|óra|minutes?|hours?)',
                r'cook(?:ing)?\s+time[:\s]+(\d+(?:-\d+)?)\s*(perc|óra|minutes?|hours?)',
                r'süsd?\s+(?:kb\.?\s*)?(\d+(?:-\d+)?)\s*(perc|óra|minutes?|hours?)',
            ],
            'total': [
                r'összes\s+idő[:\s]+(\d+(?:-\d+)?)\s*(perc|óra|minutes?|hours?)',
                r'teljes\s+idő[:\s]+(\d+(?:-\d+)?)\s*(perc|óra|minutes?|hours?)',
                r'total\s+time[:\s]+(\d+(?:-\d+)?)\s*(perc|óra|minutes?|hours?)',
                r'(\d+(?:-\d+)?)\s*(perc|óra|minutes?|hours?)\s+alatt\s+kész',
            ]
        }
        
        text = entry_content.get_text()
        time_patterns = patterns.get(time_type, [])
        
        for pattern in time_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                amount = match.group(1)
                unit = match.group(2).lower()
                
                # Нормализуем единицы
                if unit in ['perc', 'minutes', 'minute']:
                    unit = 'minutes'
                elif unit in ['óra', 'hours', 'hour']:
                    unit = 'hours'
                
                return f"{amount} {unit}"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time_from_content('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time_from_content('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time_from_content('total')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с заголовком "Megjegyzés", "Tipp", "Notes" и т.д.
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем все h3/h4 заголовки
        headers = entry_content.find_all(['h3', 'h4'])
        for header in headers:
            header_text = header.get_text(strip=True).lower()
            # Ищем заголовки заметок
            if any(keyword in header_text for keyword in ['megjegyzés', 'tipp', 'notes', 'tanács', 'hint']):
                # Собираем текст после заголовка до следующего заголовка
                notes_parts = []
                next_sibling = header.find_next_sibling()
                while next_sibling:
                    if next_sibling.name in ['h2', 'h3', 'h4']:
                        break
                    if next_sibling.name == 'p':
                        text = self.clean_text(next_sibling.get_text())
                        if text:
                            notes_parts.append(text)
                    next_sibling = next_sibling.find_next_sibling()
                
                if notes_parts:
                    return ' '.join(notes_parts)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Сначала пробуем извлечь из JSON-LD keywords
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                # Обрабатываем @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'keywords' in item:
                            keywords = item['keywords']
                            if isinstance(keywords, list):
                                tags_list.extend([str(k).strip() for k in keywords])
                            elif isinstance(keywords, str):
                                tags_list.extend([k.strip() for k in keywords.split(',')])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если не нашли в JSON-LD, ищем в HTML
        if not tags_list:
            tags_span = self.soup.find('span', class_='tags-links')
            if tags_span:
                tag_links = tags_span.find_all('a', rel='tag')
                for link in tag_links:
                    tag_text = self.clean_text(link.get_text())
                    if tag_text:
                        tags_list.append(tag_text)
        
        if not tags_list:
            return None
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags_list:
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen.add(tag_lower)
                unique_tags.append(tag)
        
        # Возвращаем как строку через запятую
        return ', '.join(unique_tags) if unique_tags else None
    
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
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                # Обрабатываем @graph
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
        
        # 3. Ищем в content изображения
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            images = entry_content.find_all('img', src=True)
            for img in images[:3]:  # Берем первые 3 изображения
                src = img.get('src')
                if src and not src.startswith('data:'):
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
    """Обработка всех HTML файлов в директории preprocessed/farmvilag_hu"""
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "preprocessed",
        "farmvilag_hu"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(FarmvilagExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python farmvilag_hu.py")


if __name__ == "__main__":
    main()
