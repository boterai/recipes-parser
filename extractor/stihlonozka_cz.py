"""
Экстрактор данных рецептов для сайта stihlonozka.cz
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class StihlonozkaExtractor(BaseRecipeExtractor):
    """Экстрактор для stihlonozka.cz"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в h1 с классом gb-headline
        h1 = self.soup.find('h1', class_=lambda x: x and 'gb-headline' in x)
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " » ŠtíhloNožka.cz"
            title = re.sub(r'\s*[»›]\s*.*$', '', title)
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
    
    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов в формате JSON строки
        Структура: [{"name": "...", "amount": "...", "units": "..."}]
        """
        ingredients = []
        
        # Ищем секцию с ингредиентами в контенте статьи
        article = self.soup.find('article')
        if not article:
            return None
        
        # Ищем списки (ul/ol) которые могут содержать ингредиенты
        content_div = article.find('div', class_=lambda x: x and 'entry-content' in str(x).lower())
        if content_div:
            # Пропускаем первый список - это обычно table of contents
            # Также пропускаем div с id="toc_container"
            toc_div = content_div.find('div', id='toc_container')
            if toc_div:
                toc_div.decompose()  # Удаляем TOC из поиска
            
            # Ищем все списки
            lists = content_div.find_all(['ul', 'ol'])
            
            for lst in lists:
                items = lst.find_all('li', recursive=False)  # Только прямые дочерние элементы
                
                # Пропускаем списки с длинными элементами (вероятно, не ингредиенты)
                if items and len(items) > 0:
                    avg_length = sum(len(item.get_text()) for item in items) / len(items)
                    # Ингредиенты обычно короче 100 символов
                    if avg_length > 150:
                        continue
                
                temp_ingredients = []
                for item in items:
                    text = item.get_text(separator=' ', strip=True)
                    text = self.clean_text(text)
                    
                    # Пропускаем очень длинные строки (не ингредиенты)
                    if text and len(text) > 0 and len(text) < 200:
                        # Парсим ингредиент
                        parsed = self.parse_ingredient(text)
                        if parsed:
                            temp_ingredients.append(parsed)
                
                # Берем первый список с найденными ингредиентами
                if temp_ingredients:
                    ingredients = temp_ingredients
                    break
        
        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def parse_ingredient(self, text: str) -> Optional[Dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        Формат Czech: "300 g Tofu", "1 ks Paprika", "2 lžíce máslo"
        или "Sójové maso – nahrazuje tradiční..."
        
        Returns:
            dict: {"name": "...", "amount": "...", "units": "..."}
        """
        if not text or len(text) < 2:
            return None
        
        # Чистим текст
        text = self.clean_text(text).strip()
        
        # Убираем префиксы типа "•", "-", "*"
        text = re.sub(r'^[•\-\*\+]\s*', '', text)
        
        # Если есть " – " (тире), берем только часть до тире (это название)
        if ' – ' in text or ' - ' in text:
            text = re.split(r'\s+[–\-]\s+', text)[0].strip()
        
        # Если есть ":" в конце (как заголовок), убираем
        text = text.rstrip(':')
        
        # Паттерн для чешских единиц измерения и количества
        # Примеры: "300 g Tofu", "1-2 ks Paprika", "2 lžíce máslo"
        pattern = r'^([\d\-.,/]+)?\s*(g|kg|ml|l|ks|kus|kusy|lžíce|lžička|lžic|lžiček|hrnek|hrnky|špetka)?\s*(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                amount = amount_str.strip()
            
            # Обработка единицы измерения  
            if unit:
                unit = unit.strip().lower()
            else:
                unit = None
            
            # Очистка названия
            name = name.strip() if name else text
            
            # Удаляем фразы типа "podle chuti", "na ozdobu"
            name = re.sub(r'\b(podle chuti|na ozdobu|volitelně|optional)\b', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\s+', ' ', name).strip()
            
            if not name or len(name) < 2:
                name = text
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        
        # Если паттерн не совпал, возвращаем как есть
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        instructions = []
        
        # Ищем в контенте статьи
        article = self.soup.find('article')
        if not article:
            return None
        
        content_div = article.find('div', class_=lambda x: x and 'entry-content' in str(x).lower())
        if not content_div:
            return None
        
        # Удаляем TOC
        toc_div = content_div.find('div', id='toc_container')
        if toc_div:
            toc_div.decompose()
        
        # Ищем параграфы с инструкциями (обычно после заголовков)
        paragraphs = content_div.find_all('p')
        
        # Ищем параграфы, которые содержат пошаговые инструкции
        # Обычно они начинаются с "Nejprve", "Poté", "Nakonec" и т.д.
        instruction_starters = ['nejprve', 'poté', 'pak', 'nakonec', 'následně', 
                               'na začátku', 'krok', 'odpo', 'odpověď']
        
        for p in paragraphs:
            text = p.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            
            # Пропускаем короткие параграфы
            if not text or len(text) < 30:
                continue
            
            text_lower = text.lower()
            
            # Ищем параграфы, которые начинаются с ключевых слов инструкций
            if any(text_lower.startswith(starter) or f' {starter} ' in text_lower 
                   for starter in instruction_starters):
                # Проверяем, что это действительно инструкция (содержит глаголы приготовления)
                cooking_verbs = ['nakrájejte', 'osmažte', 'přidejte', 'restujte', 
                                'smíchejte', 'nechte', 'podávejte', 'vařte', 
                                'opečte', 'zamíchejte', 'marinujte']
                
                if any(verb in text_lower for verb in cooking_verbs):
                    # Убираем префикс "Odpověď:" если есть
                    text = re.sub(r'^Odpov[ěe]ď:\s*', '', text, flags=re.IGNORECASE)
                    instructions.append(text)
                    # Берем только первую найденную инструкцию
                    if len(instructions) >= 1:
                        break
        
        if instructions:
            return ' '.join(instructions)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в breadcrumb navigation
        breadcrumb = self.soup.find('script', type='application/ld+json', class_='rank-math-schema-pro')
        if breadcrumb:
            try:
                data = json.loads(breadcrumb.string)
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BreadcrumbList':
                            items = item.get('itemListElement', [])
                            # Берем последнюю категорию перед самой статьей
                            if len(items) > 1:
                                return items[-2].get('item', {}).get('name', None)
            except:
                pass
        
        # Альтернативно - из meta article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # По умолчанию возвращаем "Main Course" если ничего не найдено
        return "Main Course"
    
    def extract_time_from_text(self, text: str, time_pattern: str) -> Optional[str]:
        """
        Извлечение времени из текста
        
        Args:
            text: Текст для поиска
            time_pattern: Паттерн времени (например, 'příprava', 'vaření')
        """
        # Ищем паттерны типа "30 minut", "45 minutes", "1 hodina"
        pattern = rf'{time_pattern}[:\s]*([\d]+)\s*(minut|minutes|hodina|hodin|h|m)?'
        match = re.search(pattern, text, re.IGNORECASE)
        
        if match:
            number = match.group(1)
            unit = match.group(2)
            
            # Если нет числа, значит паттерн нашел слово но без времени
            if not number:
                return None
            
            # Нормализуем единицы
            if unit:
                unit = unit.lower()
                if 'hodin' in unit or unit == 'h':
                    return f"{int(number) * 60} minutes"
                else:
                    return f"{number} minutes"
            else:
                # По умолчанию считаем минуты
                return f"{number} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в тексте статьи упоминания времени подготовки
        article = self.soup.find('article')
        if article:
            text = article.get_text()
            time = self.extract_time_from_text(text, r'příprav[aěy]')
            if time:
                return time
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте статьи упоминания времени готовки
        article = self.soup.find('article')
        if article:
            text = article.get_text()
            time = self.extract_time_from_text(text, r'var[eě]n[íí]|pečení|smažení')
            if time:
                return time
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в тексте статьи упоминания общего времени
        article = self.soup.find('article')
        if article:
            text = article.get_text()
            time = self.extract_time_from_text(text, r'celkov[ýáé]|total')
            if time:
                return time
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секции с примечаниями/советами
        article = self.soup.find('article')
        if not article:
            return None
        
        content_div = article.find('div', class_=lambda x: x and 'entry-content' in str(x).lower())
        if not content_div:
            return None
        
        # Удаляем TOC
        toc_div = content_div.find('div', id='toc_container')
        if toc_div:
            toc_div.decompose()
        
        # Ищем параграфы, которые начинаются с "Odpověď:" (Ответ:) и содержат совет
        for p in content_div.find_all('p'):
            text = p.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            
            if (text.startswith('Odpověď:') or text.startswith('Odpoved:')) and len(text) > 20:
                # Убираем префикс "Odpověď:"
                note = text.replace('Odpověď:', '').replace('Odpoved:', '').strip()
                
                # Ищем конкретные советы об экспериментах с ингредиентами
                if 'můžete experimentovat' in note.lower() and 'podle toho' in note.lower():
                    # Извлекаем предложение с советом
                    sentences = note.split('.')
                    result_parts = []
                    for sent in sentences:
                        sent = sent.strip()
                        if 'můžete experimentovat' in sent.lower() or 'podle toho' in sent.lower():
                            result_parts.append(sent)
                    if result_parts:
                        return '. '.join(result_parts).rstrip('.') + '.'
        
        # Альтернативный поиск - ищем заголовки с типичными словами для заметок
        note_keywords = ['tip', 'poznámk', 'rada', 'doporuč', 'varianta', 'pozor']
        
        for heading in content_div.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text().lower()
            
            if any(keyword in heading_text for keyword in note_keywords):
                # Берем следующий элемент (обычно параграф)
                next_elem = heading.find_next_sibling('p')
                if next_elem:
                    text = next_elem.get_text(separator=' ', strip=True)
                    return self.clean_text(text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем категории в breadcrumb или мета-тегах
        # Проверяем dynamic-term-class
        term_elements = self.soup.find_all('span', class_='post-term-item')
        for elem in term_elements:
            link = elem.find('a')
            if link:
                tag = link.get_text(strip=True)
                tag = self.clean_text(tag)
                if tag:
                    tags.append(tag.lower())
        
        # Альтернативно - из breadcrumb
        if not tags:
            breadcrumb = self.soup.find('script', type='application/ld+json')
            if breadcrumb:
                try:
                    data = json.loads(breadcrumb.string)
                    if '@graph' in data:
                        for item in data['@graph']:
                            if item.get('@type') == 'BreadcrumbList':
                                items = item.get('itemListElement', [])
                                for breadcrumb_item in items[1:]:  # Skip home
                                    name = breadcrumb_item.get('item', {}).get('name', '')
                                    if name:
                                        tags.append(name.lower())
                except:
                    pass
        
        if tags:
            return ', '.join(tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем изображение в статье (featured image)
        article = self.soup.find('article')
        if article:
            # Ищем главное изображение
            featured_img = article.find('img', class_=lambda x: x and 'gb-image' in str(x))
            if featured_img and featured_img.get('src'):
                src = featured_img['src']
                # Пропускаем data: URLs и SVG placeholders
                if not src.startswith('data:') and 'svg' not in src:
                    urls.append(src)
        
        # Убираем дубликаты
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
    """
    Точка входа для обработки HTML файлов из preprocessed/stihlonozka_cz
    """
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), 
        "preprocessed", 
        "stihlonozka_cz"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка файлов из: {preprocessed_dir}")
        process_directory(StihlonozkaExtractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python stihlonozka_cz.py")


if __name__ == "__main__":
    main()
