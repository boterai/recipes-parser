"""
Экстрактор данных рецептов для сайта dobredrinki.pl
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class DobredrinkiPlExtractor(BaseRecipeExtractor):
    """Экстрактор для dobredrinki.pl"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в мета-тегах og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " – przepis na drinka...", " • Dobre Drinki"
            title = re.sub(r'\s+[–—-]\s+przepis.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s+[•·]\s+Dobre Drinki.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Альтернативно - из заголовка h1 или h3
        for tag in ['h1', 'h3', 'h2']:
            header = self.soup.find(tag)
            if header:
                title = header.get_text()
                # Убираем суффиксы
                title = re.sub(r'\s+[–—-]\s+przepis.*$', '', title, flags=re.IGNORECASE)
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
        
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем @graph структуру
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict):
                            # BlogPosting или Article
                            if item.get('@type') in ['BlogPosting', 'Article'] and 'description' in item:
                                return self.clean_text(item['description'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Стратегия 1: Ищем заголовок со словами "składnik" или "przepis podstawowy"
        ingredient_heading = None
        for tag in self.soup.find_all(['h2', 'h3', 'h4']):
            heading_text = tag.get_text().lower()
            if 'składnik' in heading_text or ('przepis' in heading_text and 'podstawowy' in heading_text):
                ingredient_heading = tag
                break
        
        # Если нашли заголовок, ищем следующий список
        if ingredient_heading:
            el = ingredient_heading.find_next_sibling()
            while el:
                if el.name == 'ul' and 'wp-block-list' in el.get('class', []):
                    for item in el.find_all('li'):
                        ingredient_text = item.get_text(separator=' ', strip=True)
                        ingredient_text = self.clean_text(ingredient_text)
                        ingredient_text = re.sub(r'[,.]$', '', ingredient_text)
                        
                        if not ingredient_text:
                            continue
                        
                        parsed = self.parse_ingredient_pl(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
                    
                    break
                elif el.name in ['h2', 'h3', 'h4']:
                    break
                el = el.find_next_sibling()
        
        # Стратегия 2 (fallback): Берем первый список
        if not ingredients:
            ingredient_lists = self.soup.find_all('ul', class_='wp-block-list')
            if ingredient_lists:
                for item in ingredient_lists[0].find_all('li'):
                    ingredient_text = item.get_text(separator=' ', strip=True)
                    ingredient_text = self.clean_text(ingredient_text)
                    ingredient_text = re.sub(r'[,.]$', '', ingredient_text)
                    
                    if not ingredient_text:
                        continue
                    
                    parsed = self.parse_ingredient_pl(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient_pl(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат для польского языка
        
        Args:
            ingredient_text: Строка вида "wódka (40 ml)" или "250 ml spirytusu"
            
        Returns:
            dict: {"name": "wódka", "amount": 40, "units": "ml"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн 1: "название (количество единица)" - например "wódka (40 ml)"
        pattern1 = r'^([^(]+)\s*\((\d+(?:[.,]\d+)?)\s*([a-zA-Ząćęłńóśźż]+)\)'
        match1 = re.match(pattern1, text, re.IGNORECASE)
        
        if match1:
            name = match1.group(1).strip()
            amount = match1.group(2).replace(',', '.')
            unit = match1.group(3).strip()
            
            return {
                "name": name,
                "amount": int(float(amount)) if float(amount).is_integer() else float(amount),
                "units": unit
            }
        
        # Паттерн 2: "количество единица название" - например "250 ml spirytusu"
        pattern2 = r'^(\d+(?:[.,]\d+)?)\s*([a-zA-Ząćęłńóśźż]+)\s+(.+)'
        match2 = re.match(pattern2, text, re.IGNORECASE)
        
        if match2:
            amount = match2.group(1).replace(',', '.')
            unit = match2.group(2).strip()
            name = match2.group(3).strip()
            
            return {
                "name": name,
                "amount": int(float(amount)) if float(amount).is_integer() else float(amount),
                "units": unit
            }
        
        # Паттерн 3: "количество название" - например "1 połówka limonki"
        pattern3 = r'^(\d+(?:[.,]\d+)?)\s+(.+)'
        match3 = re.match(pattern3, text, re.IGNORECASE)
        
        if match3:
            amount = match3.group(1).replace(',', '.')
            name = match3.group(2).strip()
            
            return {
                "name": name,
                "amount": int(float(amount)) if float(amount).is_integer() else float(amount),
                "units": None
            }
        
        # Если ничего не совпало, возвращаем просто название
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions_text = []
        
        # Стратегия 1: Ищем заголовок "Jak przygotować", "Jak przygotujesz", "Przygotowanie"
        instruction_heading = None
        for tag in self.soup.find_all(['h2', 'h3', 'h4']):
            heading_text = tag.get_text().lower()
            if any(keyword in heading_text for keyword in ['jak przygot', 'przygotowanie', 'wykonanie', 'sposób przygot']):
                instruction_heading = tag
                break
        
        # Если нашли заголовок инструкций
        if instruction_heading:
            el = instruction_heading.find_next_sibling()
            
            while el:
                if el.name == 'p':
                    text = self.clean_text(el.get_text())
                    if text and len(text) > 20:
                        # Проверяем, что это инструкция (содержит глаголы)
                        if any(word in text.lower() for word in ['weź', 'wlej', 'dodaj', 'wymieszaj', 'zaparz', 'odstaw', 'przelej', 'podgrzej', 'wrzuć', 'zasyp', 'ugniataj', 'zamieszaj', 'przygotuj']):
                            instructions_text.append(text)
                elif el.name == 'ul' and 'wp-block-list' in el.get('class', []):
                    # Инструкции в виде списка
                    for item in el.find_all('li'):
                        text = self.clean_text(item.get_text())
                        text = re.sub(r'[,.]$', '', text).strip()
                        if text:
                            instructions_text.append(text)
                    if instructions_text:
                        break
                elif el.name in ['h2', 'h3', 'h4']:
                    break
                
                el = el.find_next_sibling()
        
        # Стратегия 2: Ищем заголовок с "przepis" и второй список (инструкции)
        if not instructions_text:
            recipe_heading = None
            for tag in self.soup.find_all(['h2', 'h3', 'h4']):
                heading_text = tag.get_text().lower()
                if 'przepis' in heading_text:
                    recipe_heading = tag
                    break
            
            if recipe_heading:
                el = recipe_heading.find_next_sibling()
                found_first_list = False
                
                while el:
                    if el.name == 'ul' and 'wp-block-list' in el.get('class', []):
                        if not found_first_list:
                            # Первый список - скорее всего ингредиенты
                            found_first_list = True
                        else:
                            # Второй список - инструкции
                            for item in el.find_all('li'):
                                text = self.clean_text(item.get_text())
                                text = re.sub(r'[,.]$', '', text).strip()
                                if text:
                                    instructions_text.append(text)
                            break
                    elif el.name == 'p' and found_first_list:
                        # Параграф между списками, может содержать инструкции
                        text = self.clean_text(el.get_text())
                        if text and len(text) > 20:
                            if any(word in text.lower() for word in ['weź', 'wlej', 'dodaj', 'wymieszaj', 'zaparz', 'odstaw', 'przelej', 'podgrzej', 'wrzuć', 'zasyp', 'ugniataj', 'zamieszaj']):
                                sentences = re.split(r'[.!?]\s+', text)
                                for sentence in sentences:
                                    if any(word in sentence.lower() for word in ['weź', 'wlej', 'dodaj', 'wymieszaj', 'zaparz', 'odstaw', 'przelej', 'podgrzej', 'wrzuć', 'zasyp', 'ugniataj', 'zamieszaj']):
                                        instructions_text.append(sentence.strip())
                                # Не прерываем, продолжаем искать второй список
                    elif el.name in ['h2', 'h3', 'h4']:
                        break
                    
                    el = el.find_next_sibling()
        
        # Стратегия 3: Ищем любой параграф с глаголами действия
        if not instructions_text:
            paragraphs = self.soup.find_all('p')
            for p in paragraphs:
                text = self.clean_text(p.get_text())
                if text and len(text) > 30:
                    if any(word in text.lower() for word in ['weź', 'wlej', 'dodaj', 'wymieszaj', 'zaparz', 'odstaw', 'przelej', 'podgrzej', 'wrzuć', 'zasyp', 'ugniataj', 'zamieszaj']):
                        instructions_text.append(text)
                        break
        
        # Объединяем в одну строку
        if instructions_text:
            normalized = []
            for text in instructions_text:
                text = text.strip()
                # Capitalize first letter
                if text:
                    text = text[0].upper() + text[1:] if len(text) > 1 else text.upper()
                if text and not text.endswith('.'):
                    text += '.'
                if text:
                    normalized.append(text)
            
            result = ' '.join(normalized)
            # Убираем вводные фразы
            result = re.sub(r'^[^.]*?\b(jest|to|może)\b[^.]*?\.\s*', '', result, flags=re.IGNORECASE)
            return result.strip() if result.strip() else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в метаданных article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем @graph структуру
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict):
                            # BlogPosting с articleSection
                            if item.get('@type') == 'BlogPosting' and 'articleSection' in item:
                                return self.clean_text(item['articleSection'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Этот сайт обычно не указывает время подготовки отдельно
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Этот сайт обычно не указывает время готовки отдельно
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в тексте упоминания времени
        # Например: "24 godziny", "30 minut", "1 godzina"
        
        # Ищем в описании или заметках
        text_blocks = []
        
        # Проверяем параграфы после списков
        for p in self.soup.find_all('p'):
            text = p.get_text().lower()
            # Ищем паттерны времени
            time_pattern = r'(\d+)\s*(godzin[yaę]|minut[yaę]?|sekund[yaę]?|dni|dzień|tydzień|tygodni)'
            if re.search(time_pattern, text):
                text_blocks.append(text)
        
        # Ищем в первом блоке с временем
        for text in text_blocks:
            # Извлекаем время
            time_match = re.search(r'(\d+)\s*(godzin[yaę]|minut[yaę]?|sekund[yaę]?|dni|dzień)', text, re.IGNORECASE)
            if time_match:
                number = time_match.group(1)
                unit = time_match.group(2)
                
                # Преобразуем в английский формат
                if 'godzin' in unit:
                    return f"{number} hours"
                elif 'minut' in unit:
                    return f"{number} minutes"
                elif 'dni' in unit or 'dzień' in unit:
                    return f"{number} days"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем заголовки типа "Na jakie modyfikacje", "Uwagi", "Wskazówki"
        for tag in self.soup.find_all(['h2', 'h3', 'h4']):
            heading_text = tag.get_text().lower()
            if any(keyword in heading_text for keyword in ['modyfikacj', 'uwag', 'wskazówk', 'porad', 'zastosowanie', 'wykorzyst']):
                # Ищем следующие параграфы
                sibling = tag.find_next_sibling()
                while sibling:
                    if sibling.name == 'p':
                        text = self.clean_text(sibling.get_text())
                        if text and len(text) > 20:
                            # Ищем предложения с "Możesz", "możesz"
                            sentences = re.split(r'[.!?]\s+', text)
                            for sentence in sentences:
                                if 'możesz' in sentence.lower() or 'można' in sentence.lower():
                                    # Это совет/заметка
                                    if not sentence.endswith('.'):
                                        sentence += '.'
                                    notes.append(sentence.strip())
                    elif sibling.name in ['h2', 'h3', 'h4', 'ul']:
                        break
                    sibling = sibling.find_next_sibling()
                
                if notes:
                    break
        
        # Если не нашли по заголовкам, ищем параграфы с ключевыми словами
        if not notes:
            all_paragraphs = self.soup.find_all('p')
            for p in all_paragraphs:
                text = self.clean_text(p.get_text())
                if text and len(text) > 30:
                    # Ищем советы
                    sentences = re.split(r'[.!?]\s+', text)
                    for sentence in sentences:
                        if any(keyword in sentence.lower() for keyword in ['możesz poszerzyć', 'możesz dodać', 'można wykorzystać', 'idealny', 'doskonały']):
                            if not sentence.endswith('.'):
                                sentence += '.'
                            notes.append(sentence.strip())
                            break
                    
                    if notes:
                        break
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Ищем в JSON-LD keywords
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем @graph структуру
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict):
                            # BlogPosting с keywords
                            if item.get('@type') == 'BlogPosting' and 'keywords' in item:
                                keywords = item['keywords']
                                if isinstance(keywords, str):
                                    # Разделяем по запятой
                                    tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                                elif isinstance(keywords, list):
                                    tags_list = [str(tag).strip() for tag in keywords if tag]
                                
                                if tags_list:
                                    break
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в meta keywords (если есть)
        if not tags_list:
            meta_keywords = self.soup.find('meta', {'name': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                tags_list = [tag.strip() for tag in meta_keywords['content'].split(',') if tag.strip()]
        
        # Возвращаем как строку через запятую с пробелом
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах og:image (главное изображение)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем @graph структуру
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict):
                            # ImageObject
                            if item.get('@type') == 'ImageObject' and 'url' in item:
                                urls.append(item['url'])
                            # BlogPosting/Article с primaryImageOfPage
                            elif item.get('@type') in ['BlogPosting', 'Article']:
                                if 'primaryImageOfPage' in item:
                                    img_ref = item['primaryImageOfPage']
                                    if isinstance(img_ref, dict) and '@id' in img_ref:
                                        # Ищем ImageObject с этим @id
                                        for img_item in data['@graph']:
                                            if isinstance(img_item, dict) and img_item.get('@id') == img_ref['@id']:
                                                if 'url' in img_item:
                                                    urls.append(img_item['url'])
                                elif 'image' in item:
                                    img = item['image']
                                    if isinstance(img, str):
                                        urls.append(img)
                                    elif isinstance(img, dict) and 'url' in img:
                                        urls.append(img['url'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 3. Ищем в img тегах в content
        content_images = self.soup.find_all('img', class_=re.compile(r'wp-image', re.I))
        for img in content_images[:3]:  # Берем первые 3
            if img.get('src'):
                # Фильтруем маленькие изображения (иконки, логотипы)
                src = img['src']
                if 'logo' not in src.lower() and 'icon' not in src.lower():
                    urls.append(src)
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            # Возвращаем как строку через запятую без пробелов
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
    
    # Обрабатываем папку preprocessed/dobredrinki_pl
    preprocessed_dir = os.path.join("preprocessed", "dobredrinki_pl")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(DobredrinkiPlExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python dobredrinki_pl.py")


if __name__ == "__main__":
    main()
