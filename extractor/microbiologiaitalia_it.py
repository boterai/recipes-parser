"""
Экстрактор данных рецептов для сайта microbiologiaitalia.it
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MicrobiologiaItaliaItExtractor(BaseRecipeExtractor):
    """Экстрактор для microbiologiaitalia.it"""
    
    @staticmethod
    def clean_ingredient_name(name: str) -> str:
        """
        Очистка названия ингредиента от дополнительных примечаний
        
        Args:
            name: название ингредиента
            
        Returns:
            Очищенное название
        """
        # Убираем комментарии в скобках
        name = re.sub(r'\s*\([^)]*\)', '', name).strip()
        
        # Убираем приставки типа "La ", "Il ", "Un ", "Una "
        name = re.sub(r'^(La|Il|Un|Una|Gli|Le|I)\s+', '', name, flags=re.IGNORECASE)
        
        # Убираем заметки о подготовке (после запятой или "a temperatura ambiente" и т.п.)
        name = re.split(r'\s*,\s*', name)[0]
        name = re.split(r'\s+a\s+temperatura\s+ambiente', name, flags=re.IGNORECASE)[0]
        name = re.split(r'\s+per\s+(decorare|spolverare|guarnire)', name, flags=re.IGNORECASE)[0]
        
        return name.strip()
    
    @staticmethod
    def parse_ingredient(ingredient_text: str) -> dict:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: строка вида "Mele: 3" или "Farina 00: 250 g" или "4 mele" или "Una presa di sale"
            
        Returns:
            Словарь с полями name, amount, unit
        """
        ingredient_text = ingredient_text.strip()
        
        # Специальная обработка для "Una presa di ...", "Un pizzico di ..."
        pinch_pattern = r'^(Una?\s+)?(?:presa|pizzico)\s+di\s+(.+)$'
        pinch_match = re.match(pinch_pattern, ingredient_text, re.IGNORECASE)
        if pinch_match:
            name = MicrobiologiaItaliaItExtractor.clean_ingredient_name(pinch_match.group(2))
            return {
                "name": name,
                "amount": "1",
                "unit": "pinch"
            }
        
        # Специальная обработка для "La scorza di N limoni", "2 uova grandi", etc.
        # Паттерн: [артикль] название di количество продукт
        di_pattern = r'^(?:La|Il|Un|Una|Gli|Le|I)?\s*(.+?)\s+di\s+(\d+(?:[.,/]\d+)?)\s+(.+)$'
        di_match = re.match(di_pattern, ingredient_text, re.IGNORECASE)
        if di_match:
            name_part = di_match.group(1).strip()
            amount = di_match.group(2).replace(',', '.')
            product = di_match.group(3).strip()
            
            # Объединяем название (например "scorza grattugiata" + "limoni")
            name = f"{name_part} di {product}"
            name = MicrobiologiaItaliaItExtractor.clean_ingredient_name(name)
            
            return {
                "name": name,
                "amount": amount,
                "unit": None
            }
        
        # Паттерн 1: "Name: amount unit" format (используется на microbiologiaitalia.it)
        # Примеры: "Mele: 3", "Farina 00: 250 g", "Burro: 80 g (a temperatura ambiente)"
        colon_pattern = r'^(.+?):\s*(\d+(?:[.,/]\d+)?)\s*(.*)$'
        colon_match = re.match(colon_pattern, ingredient_text, re.IGNORECASE)
        
        if colon_match:
            name = colon_match.group(1).strip()
            amount = colon_match.group(2).replace(',', '.')
            rest = colon_match.group(3).strip()
            
            # Очищаем название
            name = MicrobiologiaItaliaItExtractor.clean_ingredient_name(name)
            rest = re.sub(r'\s*\([^)]*\)', '', rest).strip()
            
            # Извлекаем единицу измерения из остатка
            unit = None
            if rest:
                # Единица измерения - это первое слово после количества
                unit_match = re.match(r'^([a-zA-Z]+)', rest)
                if unit_match:
                    unit = unit_match.group(1)
            
            return {
                "name": name,
                "amount": amount,
                "unit": unit
            }
        
        # Паттерн 2: "amount unit name" format
        # Примеры: "200 g farina", "1 tazza di farina", "1/2 tazza di burro"
        # Список известных единиц измерения
        known_units = ['g', 'kg', 'ml', 'l', 'tazza', 'tazze', 'cucchiaio', 'cucchiaini', 'cucchiaino', 
                       'cup', 'tbsp', 'tsp', 'oz', 'lb']
        
        pattern = r'^(\d+(?:[.,/]\d+)?)\s+([a-zA-Z]+)\s+(?:di\s+)?(.+)$'
        match = re.match(pattern, ingredient_text, re.IGNORECASE)
        
        if match:
            amount = match.group(1).replace(',', '.')
            potential_unit = match.group(2)
            rest = match.group(3).strip()
            
            # Проверяем, является ли второе слово единицей измерения
            if potential_unit.lower() in known_units:
                unit = potential_unit
                name = rest
            else:
                # Если не единица измерения, то это часть названия
                unit = None
                name = f"{potential_unit} {rest}".strip()
            
            # Очищаем название
            name = MicrobiologiaItaliaItExtractor.clean_ingredient_name(name)
            
            return {
                "name": name,
                "amount": amount,
                "unit": unit
            }
        
        # Паттерн 3: "amount name" без единицы измерения
        # Например: "4 mele", "2 limoni"
        pattern2 = r'^(\d+(?:[.,/]\d+)?)\s+(.+)$'
        match2 = re.match(pattern2, ingredient_text, re.IGNORECASE)
        
        if match2:
            amount = match2.group(1).replace(',', '.')
            name = match2.group(2).strip()
            name = MicrobiologiaItaliaItExtractor.clean_ingredient_name(name)
            
            return {
                "name": name,
                "amount": amount,
                "unit": None
            }
        
        # Если ничего не подошло, возвращаем весь текст как название
        # Например: "Salt to taste", "Q.b. (quanto basta)"
        name = MicrobiologiaItaliaItExtractor.clean_ingredient_name(ingredient_text)
        return {
            "name": name,
            "amount": None,
            "unit": None
        }
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            title = self.clean_text(h1.get_text())
            # Убираем подзаголовки типа ": Un Delizioso..."
            title = re.split(r'[:\–\-]\s*', title)[0].strip()
            return title
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.split(r'[:\–\-]\s*', title)[0].strip()
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
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Способ 1: Ищем заголовок с "Ingredienti"
        ingredienti_heading = None
        for heading in entry_content.find_all(['h2', 'h3', 'h4']):
            if 'ingredienti' in heading.get_text().lower():
                ingredienti_heading = heading
                break
        
        # Ищем следующий ul после заголовка
        ul = None
        if ingredienti_heading:
            ul = ingredienti_heading.find_next('ul')
        
        # Способ 2: Если не нашли через заголовок, ищем параграф с "Ingredienti:"
        if not ul:
            for p in entry_content.find_all('p'):
                p_text = p.get_text().strip()
                if p_text.lower() == 'ingredienti' or p_text.lower() == 'ingredienti:':
                    # Ищем следующий ul как sibling (а не просто следующий в документе)
                    next_elem = p.find_next_sibling()
                    while next_elem:
                        if next_elem.name == 'ul':
                            ul = next_elem
                            break
                        elif next_elem.name in ['h2', 'h3', 'h4', 'ol']:
                            # Дошли до другого раздела или списка
                            break
                        next_elem = next_elem.find_next_sibling()
                    if ul:
                        break
        
        if not ul:
            return None
        
        # Извлекаем элементы списка
        items = ul.find_all('li')
        for item in items:
            text = self.clean_text(item.get_text())
            if text:
                parsed = self.parse_ingredient(text)
                # Переименовываем unit в units для совместимости с форматом
                # Конвертируем название в lowercase
                ingredient_dict = {
                    "name": parsed["name"].lower() if parsed["name"] else None,
                    "units": parsed["unit"],
                    "amount": parsed["amount"]
                }
                ingredients.append(ingredient_dict)
        
        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        # Ищем entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Способ 1: Ищем заголовок с "Istruzioni" или "Procedimento" или "Preparazione"
        istruzioni_heading = None
        for heading in entry_content.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text().lower()
            if any(keyword in heading_text for keyword in ['istruzioni', 'procedimento', 'preparazione']):
                istruzioni_heading = heading
                break
        
        # Ищем следующий ol/ul после заголовка
        instructions_list = None
        if istruzioni_heading:
            instructions_list = istruzioni_heading.find_next(['ol', 'ul'])
        
        # Способ 2: Если не нашли через заголовок, ищем параграф с "Preparazione:" или "Istruzioni:"
        if not instructions_list:
            for p in entry_content.find_all('p'):
                p_text = p.get_text().strip().lower()
                if p_text in ['preparazione', 'preparazione:', 'istruzioni', 'istruzioni:']:
                    # Ищем следующий ol/ul как sibling
                    next_elem = p.find_next_sibling()
                    while next_elem:
                        if next_elem.name in ['ol', 'ul']:
                            instructions_list = next_elem
                            break
                        elif next_elem.name in ['h2', 'h3', 'h4']:
                            # Дошли до другого раздела
                            break
                        next_elem = next_elem.find_next_sibling()
                    if instructions_list:
                        break
        
        if instructions_list:
            items = instructions_list.find_all('li')
            steps = []
            for i, item in enumerate(items, 1):
                text = self.clean_text(item.get_text())
                if text:
                    steps.append(f"{i}. {text}")
            
            if steps:
                return ' '.join(steps)
        
        # Если ol/ul не найден, ищем текст после заголовка до следующего заголовка
        if istruzioni_heading:
            instructions_text = []
            next_sibling = istruzioni_heading.find_next_sibling()
            while next_sibling and next_sibling.name not in ['h2', 'h3', 'h4']:
                if next_sibling.name == 'p':
                    text = self.clean_text(next_sibling.get_text())
                    if text and text.lower() not in ['preparazione', 'preparazione:', 'istruzioni', 'istruzioni:']:
                        instructions_text.append(text)
                elif next_sibling.name == 'ul':
                    items = next_sibling.find_all('li')
                    for item in items:
                        text = self.clean_text(item.get_text())
                        if text:
                            instructions_text.append(text)
                elif next_sibling.name == 'ol':
                    items = next_sibling.find_all('li')
                    for i, item in enumerate(items, 1):
                        text = self.clean_text(item.get_text())
                        if text:
                            instructions_text.append(f"{i}. {text}")
                next_sibling = next_sibling.find_next_sibling()
            
            if instructions_text:
                return ' '.join(instructions_text)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Пытаемся найти категорию в различных местах
        
        # 1. Проверяем article:section meta tag
        article_section = self.soup.find('meta', property='article:section')
        if article_section and article_section.get('content'):
            return self.clean_text(article_section['content'])
        
        # 2. Проверяем breadcrumbs или категории
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) >= 2:
                # Берем предпоследнюю категорию (последняя обычно сама страница)
                return self.clean_text(links[-2].get_text())
        
        # 3. По умолчанию определяем по ключевым словам в заголовке
        h1 = self.soup.find('h1')
        if h1:
            text = h1.get_text().lower()
            if any(word in text for word in ['torta', 'biscotti', 'dolce', 'dessert', 'cake']):
                return "Dessert"
            elif any(word in text for word in ['pasta', 'risotto', 'pizza']):
                return "Main Course"
            elif any(word in text for word in ['insalata', 'salad']):
                return "Salad"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в тексте упоминания времени подготовки
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            # Ищем паттерны типа "Tempo di preparazione: 15 minuti"
            text = entry_content.get_text()
            patterns = [
                r'tempo\s+di\s+preparazione[:\s]+(\d+)\s*(?:minuti|minutes)',
                r'preparazione[:\s]+(\d+)\s*(?:minuti|minutes)',
                r'prep\s+time[:\s]+(\d+)\s*(?:minuti|minutes)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return f"{match.group(1)} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        # Ищем в тексте упоминания времени готовки
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            # Ищем паттерны типа "Tempo di cottura: 40 minuti" или "40-45 minuti"
            text = entry_content.get_text()
            patterns = [
                r'tempo\s+di\s+cottura[:\s]+(\d+(?:-\d+)?)\s*(?:minuti|minutes)',
                r'cottura[:\s]+(\d+(?:-\d+)?)\s*(?:minuti|minutes)',
                r'cook\s+time[:\s]+(\d+(?:-\d+)?)\s*(?:minuti|minutes)',
                r'cuoci.*?per\s+(?:circa\s+)?(\d+(?:-\d+)?)\s*(?:minuti|minutes)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return f"{match.group(1)} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в тексте упоминания общего времени
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            text = entry_content.get_text()
            patterns = [
                r'tempo\s+totale[:\s]+(\d+)\s*(?:minuti|minutes)',
                r'total\s+time[:\s]+(\d+)\s*(?:minuti|minutes)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return f"{match.group(1)} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов"""
        notes = []
        
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем заголовки с ключевыми словами
        keywords = ['consigli', 'note', 'suggerimenti', 'tips', 'varianti', 'conservazione']
        
        for heading in entry_content.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text().lower()
            if any(keyword in heading_text for keyword in keywords):
                # Собираем текст до следующего заголовка
                note_parts = []
                next_sibling = heading.find_next_sibling()
                while next_sibling and next_sibling.name not in ['h2', 'h3', 'h4']:
                    if next_sibling.name == 'p':
                        text = self.clean_text(next_sibling.get_text())
                        if text:
                            note_parts.append(text)
                    elif next_sibling.name in ['ul', 'ol']:
                        items = next_sibling.find_all('li')
                        for item in items:
                            text = self.clean_text(item.get_text())
                            if text:
                                note_parts.append(text)
                    next_sibling = next_sibling.find_next_sibling()
                
                if note_parts:
                    notes.append(' '.join(note_parts))
        
        if notes:
            return ' '.join(notes)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # 1. Проверяем meta keywords
        keywords_meta = self.soup.find('meta', {'name': 'keywords'})
        if keywords_meta and keywords_meta.get('content'):
            content = keywords_meta['content']
            # Разделяем по запятой
            tags.extend([tag.strip() for tag in content.split(',') if tag.strip()])
        
        # 2. Проверяем article:tag meta tags
        article_tags = self.soup.find_all('meta', property='article:tag')
        for tag_meta in article_tags:
            if tag_meta.get('content'):
                tags.append(tag_meta['content'].strip())
        
        # 3. Если тегов нет, пытаемся определить по категории и заголовку
        if not tags:
            h1 = self.soup.find('h1')
            if h1:
                text = h1.get_text().lower()
                if 'torta' in text or 'cake' in text:
                    tags.append('dessert')
                if 'biscotti' in text or 'cookies' in text:
                    tags.extend(['cookies', 'dessert'])
                if 'mele' in text or 'apple' in text:
                    tags.append('apple')
                if 'limone' in text or 'lemon' in text:
                    tags.append('lemon')
                if 'mandorle' in text or 'almond' in text:
                    tags.append('almond')
        
        if tags:
            # Убираем дубликаты
            unique_tags = []
            seen = set()
            for tag in tags:
                tag_lower = tag.lower()
                if tag_lower not in seen:
                    seen.add(tag_lower)
                    unique_tags.append(tag)
            return ', '.join(unique_tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Проверяем og:image meta tag
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем изображения в content
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            images = entry_content.find_all('img')
            for img in images:
                src = img.get('src') or img.get('data-src')
                if src and src.startswith('http'):
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
    """Обработка всех HTML файлов в директории preprocessed/microbiologiaitalia_it"""
    import os
    
    # Путь к директории с HTML-страницами
    recipes_dir = os.path.join("preprocessed", "microbiologiaitalia_it")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(MicrobiologiaItaliaItExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python microbiologiaitalia_it.py")


if __name__ == "__main__":
    main()
