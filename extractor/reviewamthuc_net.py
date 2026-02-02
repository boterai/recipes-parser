"""
Экстрактор данных рецептов для сайта reviewamthuc.net
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ReviewamthucNetExtractor(BaseRecipeExtractor):
    """Экстрактор для reviewamthuc.net"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в основном заголовке статьи
        title = self.soup.find('h1', class_='jeg_post_title')
        if title:
            text = self.clean_text(title.get_text())
            # Убираем вводные фразы типа "Vào bếp với cách làm"
            text = re.sub(r'^.*?cách làm\s+', '', text, flags=re.IGNORECASE)
            # Убираем описательные фразы в конце
            text = re.sub(r'\s+(thanh tịnh|ngon ngất ngây|thơm ngon|hấp dẫn|dễ làm).*$', '', text, flags=re.IGNORECASE)
            return self.clean_text(text) if text else None
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            text = og_title['content']
            text = re.sub(r'^.*?cách làm\s+', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\s+(thanh tịnh|ngon ngất ngây|thơm ngon|hấp dẫn|dễ làm).*$', '', text, flags=re.IGNORECASE)
            return self.clean_text(text) if text else None
        
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
        
        # Ищем первый параграф в контенте статьи
        content_div = self.soup.find('div', class_='content-inner')
        if content_div:
            first_p = content_div.find('p')
            if first_p:
                return self.clean_text(first_p.get_text())
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "2 miếng đậu hũ chiên" или "250ml nước cốt dừa"
            
        Returns:
            dict: {"name": "đậu hũ chiên", "amount": "2", "units": "miếng"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "2 miếng đậu hũ", "250ml nước cốt dừa", "1 củ hành tím"
        # Единицы измерения для вьетнамских рецептов
        units_pattern = r'(ml|g|kg|l|miếng|quả|củ|muỗng canh|muỗng cà phê|con|cọng|lá|nhánh|vài nhánh|gram|lít|kg|gói|hộp|thìa|chén|bát)'
        
        # Попытка 1: Число + единица (склеенные или разделенные) + название
        # Примеры: "250ml nước cốt dừa", "2 miếng đậu hũ"
        # Используем non-capturing groups для альтернатив внутри units_pattern
        pattern1 = rf'^(\d+(?:[.,]\d+)?)\s*(?:ml|g|kg|l|miếng|quả|củ|muỗng canh|muỗng cà phê|con|cọng|lá|nhánh|vài nhánh|gram|lít|kg|gói|hộp|thìa|chén|bát)\s+(.+)$'
        match = re.match(pattern1, text, re.IGNORECASE)
        
        if match:
            groups = match.groups()
            amount = groups[0]
            # Извлекаем units из совпадения вручную
            units_match = re.search(rf'\d+(?:[.,]\d+)?\s*(ml|g|kg|l|miếng|quả|củ|muỗng canh|muỗng cà phê|con|cọng|lá|nhánh|vài nhánh|gram|lít|kg|gói|hộp|thìa|chén|bát)', text, re.IGNORECASE)
            units = units_match.group(1).lower() if units_match else None
            name = groups[1] if len(groups) > 1 else ''
            return {
                "name": self.clean_text(name),
                "amount": amount.replace(',', '.'),
                "units": units
            }
        
        # Попытка 2: Число + название (без единицы, или единица в скобках/в конце)
        # Примеры: "1 con (khoảng 1.5 – 2kg)", "2 quả cà chua"
        pattern2 = rf'^(\d+(?:[.,]\d+)?)\s+(.+?)(?:\s+\(.*?\))?$'
        match = re.match(pattern2, text, re.IGNORECASE)
        
        if match:
            amount, name_with_unit = match.groups()
            # Попытка извлечь единицу из конца названия
            unit_in_name = re.search(rf'\s+({units_pattern})$', name_with_unit, re.IGNORECASE)
            if unit_in_name:
                units = unit_in_name.group(1).lower()
                name = name_with_unit[:unit_in_name.start()].strip()
                # Проверяем, есть ли дополнительная информация в скобках в оригинальном тексте
                extra_info = re.search(r'\(([^)]+)\)', text)
                if extra_info:
                    units = f"{units} ({extra_info.group(1)})"
                return {
                    "name": self.clean_text(name),
                    "amount": amount.replace(',', '.'),
                    "units": units
                }
            else:
                # Нет единицы, только количество и название
                return {
                    "name": self.clean_text(name_with_unit),
                    "amount": amount.replace(',', '.'),
                    "units": None
                }
        
        # Попытка 3: Только название (без количества и единицы)
        # Примеры: "Khoai lang", "Hành tây", "Dầu ăn"
        # Проверяем, нет ли в начале числа
        if not re.match(r'^\d', text):
            return {
                "name": self.clean_text(text),
                "amount": None,
                "units": None
            }
        
        # Если ничего не совпало, возвращаем как есть
        return {
            "name": self.clean_text(text),
            "amount": None,
            "units": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем заголовок с ингредиентами
        # В reviewamthuc.net часто используется заголовок типа "Nguyên liệu" или похожий
        headings = self.soup.find_all(['h2', 'h3', 'h4'], string=re.compile(r'nguyên liệu|Nguyên liệu|NGUYÊN LIỆU', re.IGNORECASE))
        
        for heading in headings:
            # Ищем следующий за заголовком список <ul>
            next_elem = heading.find_next_sibling()
            while next_elem:
                if next_elem.name == 'ul':
                    # Извлекаем элементы списка
                    items = next_elem.find_all('li', recursive=False)
                    for item in items:
                        ingredient_text = item.get_text(separator=' ', strip=True)
                        ingredient_text = self.clean_text(ingredient_text)
                        
                        if ingredient_text:
                            # Проверяем, содержит ли строка несколько ингредиентов через запятую
                            # Если есть количество и единица в начале, это один ингредиент
                            # Иначе - может быть список через запятую
                            if re.match(r'^\d+', ingredient_text):
                                # Начинается с числа - один ингредиент
                                parsed = self.parse_ingredient(ingredient_text)
                                if parsed:
                                    ingredients.append(parsed)
                            else:
                                # Может быть список через запятую
                                # Проверяем, есть ли запятые
                                if ',' in ingredient_text:
                                    # Разделяем по запятым
                                    parts = ingredient_text.split(',')
                                    for part in parts:
                                        part = part.strip()
                                        if part:
                                            parsed = self.parse_ingredient(part)
                                            if parsed:
                                                ingredients.append(parsed)
                                else:
                                    # Один ингредиент без запятых
                                    parsed = self.parse_ingredient(ingredient_text)
                                    if parsed:
                                        ingredients.append(parsed)
                    # Не break - продолжаем искать другие списки после этого заголовка
                elif next_elem.name in ['h2', 'h3', 'h4']:
                    # Если встретили другой заголовок, прекращаем поиск
                    break
                next_elem = next_elem.find_next_sibling()
            
            if ingredients:
                break
        
        # Если не нашли через заголовки, ищем списки ингредиентов по классам или другим признакам
        if not ingredients:
            # Ищем все списки в контенте
            content_div = self.soup.find('div', class_='content-inner')
            if content_div:
                all_lists = content_div.find_all('ul')
                # Обычно первый список - это ингредиенты
                for ul in all_lists[:2]:  # Проверяем первые 2 списка
                    items = ul.find_all('li', recursive=False)
                    temp_ingredients = []
                    for item in items:
                        ingredient_text = item.get_text(separator=' ', strip=True)
                        ingredient_text = self.clean_text(ingredient_text)
                        if ingredient_text:
                            # Проверяем, содержит ли строка несколько ингредиентов через запятую
                            if re.match(r'^\d+', ingredient_text):
                                parsed = self.parse_ingredient(ingredient_text)
                                if parsed:
                                    temp_ingredients.append(parsed)
                            else:
                                if ',' in ingredient_text:
                                    parts = ingredient_text.split(',')
                                    for part in parts:
                                        part = part.strip()
                                        if part:
                                            parsed = self.parse_ingredient(part)
                                            if parsed:
                                                temp_ingredients.append(parsed)
                                else:
                                    parsed = self.parse_ingredient(ingredient_text)
                                    if parsed:
                                        temp_ingredients.append(parsed)
                    
                    # Если нашли достаточно элементов, считаем это списком ингредиентов
                    if len(temp_ingredients) >= 3:
                        ingredients = temp_ingredients
                        break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions = []
        
        # Ищем заголовки с номерами шагов (Bước 1, Bước 2, и т.д.)
        step_headings = self.soup.find_all(['h4', 'h3', 'h2'], 
                                           string=re.compile(r'Bước\s+\d+', re.IGNORECASE))
        
        if step_headings:
            for step_heading in step_headings:
                # Извлекаем номер шага
                step_match = re.search(r'Bước\s+(\d+)', step_heading.get_text(), re.IGNORECASE)
                if step_match:
                    step_num = step_match.group(1)
                    
                    # Извлекаем содержимое после заголовка
                    step_text_parts = []
                    
                    # Проверяем, есть ли текст в самом заголовке после "Bước X:"
                    heading_text = step_heading.get_text()
                    after_colon = re.sub(r'^.*?Bước\s+\d+\s*:\s*', '', heading_text, flags=re.IGNORECASE)
                    if after_colon and after_colon != heading_text:
                        step_text_parts.append(after_colon)
                    
                    # Ищем следующие элементы (параграфы, списки)
                    next_elem = step_heading.find_next_sibling()
                    while next_elem:
                        if next_elem.name in ['h2', 'h3', 'h4']:
                            # Если встретили другой заголовок, прекращаем
                            break
                        elif next_elem.name == 'p':
                            text = self.clean_text(next_elem.get_text())
                            if text:
                                step_text_parts.append(text)
                        elif next_elem.name == 'ul':
                            # Если есть список, извлекаем элементы
                            items = next_elem.find_all('li', recursive=False)
                            for item in items:
                                text = self.clean_text(item.get_text())
                                if text:
                                    step_text_parts.append(text)
                        next_elem = next_elem.find_next_sibling()
                    
                    # Объединяем части шага
                    if step_text_parts:
                        step_text = ' '.join(step_text_parts)
                        instructions.append(f"{step_num}. {step_text}")
        
        # Если не нашли через заголовки Bước, ищем пронумерованный список
        if not instructions:
            content_div = self.soup.find('div', class_='content-inner')
            if content_div:
                # Ищем упорядоченный список <ol>
                ols = content_div.find_all('ol')
                for ol in ols:
                    items = ol.find_all('li', recursive=False)
                    # Проверяем, не является ли это оглавлением (обычно короткие фразы)
                    # Шаги рецепта обычно длиннее 50 символов
                    if items and len(items) >= 3:
                        avg_length = sum(len(item.get_text()) for item in items) / len(items)
                        if avg_length > 50:  # Вероятно, это шаги рецепта, а не оглавление
                            for idx, item in enumerate(items, 1):
                                step_text = self.clean_text(item.get_text())
                                if step_text:
                                    instructions.append(f"{idx}. {step_text}")
                            break
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в meta article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BlogPosting' and 'articleSection' in item:
                            return self.clean_text(item['articleSection'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('div', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в контенте упоминания времени подготовки
        content = self.soup.find('div', class_='content-inner')
        if content:
            text = content.get_text()
            # Поиск паттернов типа "Thời gian chuẩn bị: 15 phút"
            prep_match = re.search(r'(?:thời gian chuẩn bị|chuẩn bị)[\s:]+(\d+)\s*(?:phút|minutes?)', text, re.IGNORECASE)
            if prep_match:
                minutes = prep_match.group(1)
                return f"{minutes} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в контенте упоминания времени приготовления
        content = self.soup.find('div', class_='content-inner')
        if content:
            text = content.get_text()
            # Поиск паттернов типа "Thời gian nấu: 40 phút"
            cook_match = re.search(r'(?:thời gian nấu|nấu)[\s:]+(\d+)\s*(?:phút|minutes?)', text, re.IGNORECASE)
            if cook_match:
                minutes = cook_match.group(1)
                return f"{minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в контенте упоминания общего времени
        content = self.soup.find('div', class_='content-inner')
        if content:
            text = content.get_text()
            # Поиск паттернов типа "Tổng thời gian: 55 phút"
            total_match = re.search(r'(?:tổng thời gian|tổng cộng)[\s:]+(\d+)\s*(?:phút|minutes?)', text, re.IGNORECASE)
            if total_match:
                minutes = total_match.group(1)
                return f"{minutes} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями/советами
        # Обычно помечены заголовками типа "Lưu ý", "Ghi chú", "Tips"
        note_headings = self.soup.find_all(['h2', 'h3', 'h4'], 
                                           string=re.compile(r'lưu ý|ghi chú|tips|note', re.IGNORECASE))
        
        for heading in note_headings:
            notes_parts = []
            next_elem = heading.find_next_sibling()
            while next_elem:
                if next_elem.name in ['h2', 'h3', 'h4']:
                    break
                elif next_elem.name == 'p':
                    text = self.clean_text(next_elem.get_text())
                    if text:
                        notes_parts.append(text)
                elif next_elem.name == 'ul':
                    items = next_elem.find_all('li', recursive=False)
                    for item in items:
                        text = self.clean_text(item.get_text())
                        if text:
                            notes_parts.append(text)
                next_elem = next_elem.find_next_sibling()
            
            if notes_parts:
                return ' '.join(notes_parts)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # 1. Ищем в meta keywords
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        # 2. Ищем в JSON-LD
        if not tags_list:
            json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and '@graph' in data:
                        for item in data['@graph']:
                            if item.get('@type') == 'BlogPosting' and 'keywords' in item:
                                keywords = item['keywords']
                                if isinstance(keywords, str):
                                    tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                                elif isinstance(keywords, list):
                                    tags_list = keywords
                                break
                except (json.JSONDecodeError, KeyError):
                    continue
        
        # Возвращаем как строку через запятую
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'ImageObject' and 'url' in item:
                            urls.append(item['url'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 3. Ищем изображения в контенте статьи
        content_div = self.soup.find('div', class_='content-inner')
        if content_div:
            # Ищем img с data-lazy-src или src
            images = content_div.find_all('img')
            for img in images[:5]:  # Ограничиваем до 5 изображений
                img_url = img.get('data-lazy-src') or img.get('src')
                if img_url and img_url.startswith('http'):
                    urls.append(img_url)
        
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
    # Обрабатываем папку preprocessed/reviewamthuc_net
    preprocessed_dir = os.path.join("preprocessed", "reviewamthuc_net")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ReviewamthucNetExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python reviewamthuc_net.py")


if __name__ == "__main__":
    main()
