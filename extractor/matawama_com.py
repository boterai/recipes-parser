"""
Экстрактор данных рецептов для сайта matawama.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MatawamaExtractor(BaseRecipeExtractor):
    """Экстрактор для matawama.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке с itemprop="name"
        h1_tag = self.soup.find('h1', class_='post-title')
        if h1_tag:
            name_span = h1_tag.find('span', itemprop='name')
            if name_span:
                return self.clean_text(name_span.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " | Matawama.com"
            title = re.sub(r'\s*\|.*$', '', title)
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
    
    def parse_ingredient_amount(self, amount_text: str) -> Dict[str, Optional[str]]:
        """
        Парсит строку с количеством ингредиента
        
        Args:
            amount_text: строка типа "500g", "2 stk", "1 ts"
            
        Returns:
            Словарь с amount и unit
        """
        if not amount_text:
            return {"amount": None, "unit": None}
        
        amount_text = self.clean_text(amount_text)
        
        # Паттерны для разных форматов
        # "500g", "500 g"
        match = re.match(r'^(\d+\.?\d*)\s*([a-zA-Z]+)$', amount_text)
        if match:
            return {"amount": match.group(1), "unit": match.group(2)}
        
        # "2 stk", "4 fedd"
        match = re.match(r'^(\d+\.?\d*)\s+(.+)$', amount_text)
        if match:
            return {"amount": match.group(1), "unit": match.group(2)}
        
        # Только число
        match = re.match(r'^(\d+\.?\d*)$', amount_text)
        if match:
            return {"amount": match.group(1), "unit": None}
        
        # Если не удалось распарсить, возвращаем как есть
        return {"amount": amount_text, "unit": None}
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из таблиц или списков"""
        ingredients = []
        
        # Ищем первую таблицу с ингредиентами
        tables = self.soup.find_all('table')
        
        for table in tables:
            # Проверяем заголовки таблицы
            headers = table.find_all('th')
            if not headers:
                continue
            
            header_texts = [self.clean_text(h.get_text()).lower() for h in headers]
            
            # Проверяем, что это таблица с ингредиентами
            # Ищем "Ingrediens" или "Mengde" в заголовках
            if not any(word in ' '.join(header_texts) for word in ['ingrediens', 'mengde']):
                continue
            
            # Извлекаем строки с ингредиентами
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 2:
                    # Первая ячейка - название ингредиента
                    name = self.clean_text(cells[0].get_text())
                    # Вторая ячейка - количество
                    amount_text = self.clean_text(cells[1].get_text())
                    
                    if name and not name.endswith(':'):
                        parsed_amount = self.parse_ingredient_amount(amount_text)
                        ingredient = {
                            "name": name,
                            "amount": parsed_amount["amount"],
                            "units": parsed_amount["unit"]
                        }
                        ingredients.append(ingredient)
            
            # Если нашли ингредиенты, прекращаем поиск (берем только первую таблицу)
            if ingredients:
                break
        
        # Если не нашли в таблицах, пробуем найти в списках
        if not ingredients:
            # Ищем секцию с ингредиентами по заголовку
            ingredient_section = None
            for h2 in self.soup.find_all(['h2', 'h3']):
                text = self.clean_text(h2.get_text()).lower()
                if 'ingrediens' in text:
                    ingredient_section = h2
                    break
            
            # Ищем следующий <ul> после заголовка с ингредиентами
            if ingredient_section:
                ul = ingredient_section.find_next('ul')
                if ul:
                    items = ul.find_all('li', recursive=False)
                    for item in items:
                        # Извлекаем только прямой текст элемента li (без вложенных элементов)
                        # Удаляем все вложенные теги перед извлечением текста
                        item_copy = item.__copy__()
                        for nested in item_copy.find_all():
                            nested.decompose()
                        text = self.clean_text(item_copy.get_text())
                        
                        # Пропускаем пустые или слишком короткие строки
                        if not text or len(text) < 3:
                            continue
                        
                        # Пытаемся распарсить формат "500 gram kyllingfilet"
                        match = re.match(r'^(\d+\.?\d*)\s+(\w+)\s+(.+)$', text)
                        if match:
                            ingredient = {
                                "name": match.group(3),
                                "amount": match.group(1),
                                "units": match.group(2)
                            }
                            ingredients.append(ingredient)
                        else:
                            # Пытаемся распарсить формат "2 store løk" или "1/2 ts spisskummen"
                            match = re.match(r'^([\d\/\.]+)\s+(.+)$', text)
                            if match:
                                # Проверяем, не является ли второе слово числительным/прилагательным
                                parts = match.group(2).split(None, 1)
                                if len(parts) == 2:
                                    ingredient = {
                                        "name": parts[1],
                                        "amount": match.group(1),
                                        "units": parts[0]
                                    }
                                else:
                                    ingredient = {
                                        "name": match.group(2),
                                        "amount": match.group(1),
                                        "units": None
                                    }
                                ingredients.append(ingredient)
                            else:
                                # Формат типа "Salt etter smak" или "Olje til steking"
                                parts = text.split(None, 1)
                                if len(parts) >= 1:
                                    ingredient = {
                                        "name": parts[0],
                                        "amount": parts[1] if len(parts) > 1 else None,
                                        "units": None
                                    }
                                    ingredients.append(ingredient)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions = []
        
        # Ищем первый упорядоченный список с инструкциями
        ordered_lists = self.soup.find_all('ol')
        
        for ol in ordered_lists:
            items = ol.find_all('li', recursive=False)
            temp_instructions = []
            for item in items:
                text = self.clean_text(item.get_text())
                if text and len(text) > 10:  # Фильтруем слишком короткие строки
                    temp_instructions.append(text)
            
            # Если нашли достаточно инструкций, прекращаем поиск
            if len(temp_instructions) >= 3:
                instructions = temp_instructions
                break
        
        # Объединяем все инструкции в одну строку
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда"""
        # Ищем в meta article:section
        section_meta = self.soup.find('meta', property='article:section')
        if section_meta and section_meta.get('content'):
            section = self.clean_text(section_meta['content']).lower()
            # Игнорируем нерелевантные категории
            if section and section not in ['boller', 'potet oppskrift']:
                return section
        
        # По умолчанию возвращаем Main Course для рецептов
        return "Main Course"
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Matawama.com не всегда имеет отдельное время подготовки
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте упоминания времени приготовления
        # Паттерны: "10-15 minutter", "20-30 minutes", "ca. 20-30 minutter"
        text = self.soup.get_text()
        
        # Ищем паттерны времени
        patterns = [
            r'(\d+-\d+)\s+min(?:ut|ute)(?:s|r|ter)?',
            r'ca\.\s+(\d+-\d+)\s+min(?:ut|ute)(?:s|r|ter)?',
            r'(\d+)\s+min(?:ut|ute)(?:s|r|ter)?'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                time_num = match.group(1)
                # Форматируем в стандартный вид
                return f"{time_num} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Matawama.com не всегда указывает отдельное общее время
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем списки с заметками/советами
        lists = self.soup.find_all('ul')
        
        for ul in lists:
            items = ul.find_all('li')
            for item in items:
                # Извлекаем только прямой текст элемента li (без вложенных элементов)
                item_copy = item.__copy__()
                for nested in item_copy.find_all():
                    nested.decompose()
                text = self.clean_text(item_copy.get_text())
                
                # Проверяем, содержит ли текст ключевые слова для заметок
                if text and any(keyword in text.lower() for keyword in 
                               ['vegetarisk', 'tips', 'justér', 'kan du', 'anbefal', 
                                'erstatte', 'variasjon', 'alternative']):
                    notes.append(text)
        
        # Если не нашли заметки в списках, ищем упоминание о подаче в инструкциях
        if not notes:
            # Ищем последние шаги инструкций, которые могут содержать информацию о подаче
            ordered_lists = self.soup.find_all('ol')
            for ol in ordered_lists:
                items = ol.find_all('li', recursive=False)
                if items and len(items) >= 2:
                    # Проверяем последние 2 шага
                    for step in items[-2:]:
                        step_text = self.clean_text(step.get_text())
                        if step_text and 'server' in step_text.lower() and 'nyt' not in step_text.lower():
                            # Извлекаем часть о подаче
                            # Паттерн: "... server med ris eller naanbrød"
                            match = re.search(r'server\s+(?:den\s+)?(?:deilige\s+)?(?:indiske\s+)?(?:curryen\s+)?med\s+(.+?)\.?$', step_text, re.IGNORECASE)
                            if match:
                                serving_text = match.group(1).strip()
                                # Убираем лишние точки в конце
                                serving_text = serving_text.rstrip('.')
                                if serving_text:
                                    notes.append(f"Serve with {serving_text}.")
                                    break
                if notes:
                    break
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем article:tag meta теги
        tag_metas = self.soup.find_all('meta', property='article:tag')
        
        for meta in tag_metas:
            tag = meta.get('content')
            if tag:
                tag = self.clean_text(tag).lower()
                tags.append(tag)
        
        # Если нет article:tag, возвращаем None
        if not tags:
            return None
        
        # Фильтруем и берем только релевантные теги (макс 5-6 тегов)
        # Приоритет: названия блюд, ингредиенты, кухня
        priority_keywords = ['curry', 'indisk', 'kylling', 'chicken', 'hovedrett']
        priority_tags = [t for t in tags if any(kw in t for kw in priority_keywords)]
        
        # Если есть приоритетные теги, берем их
        if priority_tags:
            # Ограничиваем до 5 тегов
            result_tags = priority_tags[:5]
        else:
            # Иначе берем первые несколько тегов
            result_tags = tags[:5]
        
        # Возвращаем теги через запятую
        return ', '.join(result_tags) if result_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Сначала пробуем из meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # Также twitter:image
        twitter_image = self.soup.find('meta', {'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if url not in urls:
                urls.append(url)
        
        # Ищем изображения в контенте
        images = self.soup.find_all('img', src=True)
        for img in images:
            src = img.get('src')
            # Фильтруем только релевантные изображения (не иконки, не аватары)
            if src and 'http' in src and src not in urls:
                # Пропускаем маленькие изображения и граватары
                if 'gravatar' not in src and 'icon' not in src.lower():
                    urls.append(src)
                    if len(urls) >= 3:  # Ограничиваем до 3 изображений
                        break
        
        return ','.join(urls) if urls else None
    
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
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name.lower() if dish_name else None,
            "description": description,  # Оставляем описание без lower() для читаемости
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    """
    Точка входа для обработки HTML файлов matawama.com
    """
    import os
    
    # Ищем директорию с HTML страницами
    preprocessed_dir = os.path.join("preprocessed", "matawama_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(MatawamaExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python matawama_com.py")


if __name__ == "__main__":
    main()
