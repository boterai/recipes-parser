"""
Экстрактор данных рецептов для сайта malinika.ru
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MalinikaExtractor(BaseRecipeExtractor):
    """Экстрактор для malinika.ru"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Данные могут быть в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'WebPage':
                            return item
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            title = self.clean_text(h1.get_text())
            # Убираем длинные суффиксы с тире
            title = re.sub(r'\s*[–-]\s*.*$', '', title)
            return title
        
        # Альтернатива - из JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'name' in json_ld:
            title = self.clean_text(json_ld['name'])
            title = re.sub(r'\s*[–-]\s*.*$', '', title)
            return title
        
        # Из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = self.clean_text(og_title['content'])
            title = re.sub(r'\s*[–-]\s*.*$', '', title)
            return title
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала проверяем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
        # Ищем в мета-тегах
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернатива - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате списка словарей"""
        ingredients = []
        
        # Ищем все списки ингредиентов в entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем ul списки после заголовка "Ингредиенты"
        # Также ищем параграфы с паттернами количество + ингредиент
        
        # Способ 1: Ищем ul после параграфа с "Ингредиенты:"
        paragraphs = entry_content.find_all('p')
        for i, p in enumerate(paragraphs):
            text = p.get_text(strip=True)
            if re.match(r'^Ингредиенты:?\s*$', text, re.IGNORECASE):
                # Проверяем следующий элемент - это может быть ul
                next_sibling = p.find_next_sibling()
                if next_sibling and next_sibling.name == 'ul':
                    items = next_sibling.find_all('li')
                    for item in items:
                        ingredient_text = self.clean_text(item.get_text())
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
                    if ingredients:
                        break
        
        # Способ 2: Если не нашли, ищем параграфы с паттерном "количество ингредиент"
        if not ingredients:
            # Ищем заголовки с id="ingredienty" или похожие
            ing_heading = entry_content.find(['h2', 'h3'], id=re.compile(r'ingredien', re.I))
            if ing_heading:
                # Собираем все следующие параграфы до следующего заголовка
                current = ing_heading.find_next_sibling()
                while current and current.name not in ['h1', 'h2', 'h3']:
                    if current.name == 'p':
                        text = self.clean_text(current.get_text())
                        # Паттерн: "200 г лапши" или "1 кг муки"
                        if re.match(r'^\d+', text) or re.match(r'^[А-Яа-я\d\s,.\-/]+$', text):
                            parsed = self.parse_ingredient(text)
                            if parsed:
                                ingredients.append(parsed)
                    current = current.find_next_sibling()
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    @staticmethod
    def normalize_ingredient_name(name: str) -> str:
        """
        Преобразует название ингредиента из родительного падежа в именительный
        
        Args:
            name: Название ингредиента (может быть в родительном падеже)
            
        Returns:
            Нормализованное название в именительном падеже
        """
        if not name:
            return name
        
        # Словарь распространенных преобразований (родительный -> именительный)
        genitive_to_nominative = {
            'лапши': 'лапша',
            'мака': 'мак',
            'чернослива': 'чернослив',
            'меда': 'мед',
            'муки': 'мука',
            'сахара': 'сахар',
            'масла': 'масло',
            'молока': 'молоко',
            'яиц': 'яйца',
            'желтков': 'желтки',
            'белков': 'белки',
            'сливок': 'сливки',
            'воды': 'вода',
            'соли': 'соль',
            'перца': 'перец',
            'ванили': 'ваниль',
            'корицы': 'корица',
            'изюма': 'изюм',
            'орехов': 'орехи',
            'яблок': 'яблоки',
            'ягод': 'ягоды',
            'сливочного масла': 'сливочное масло',
            'растительного масла': 'растительное масло',
        }
        
        # Проверяем прямое совпадение
        name_lower = name.lower()
        if name_lower in genitive_to_nominative:
            return genitive_to_nominative[name_lower]
        
        # Проверяем частичное совпадение (для составных названий)
        for gen, nom in genitive_to_nominative.items():
            if name_lower.endswith(' ' + gen):
                return name_lower.replace(' ' + gen, ' ' + nom)
            if name_lower.startswith(gen + ' '):
                return name_lower.replace(gen + ' ', nom + ' ', 1)
        
        # Простые правила для окончаний (не всегда точные, но покрывают частые случаи)
        # -и/-ы -> -а/-я (мука из муки)
        if name_lower.endswith('ки') and len(name) > 3:
            return name[:-1] + 'а'  # муки -> мука
        
        return name
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "200 г лапши" или "2 столовые ложки меда"
            
        Returns:
            dict: {"name": "лапша", "amount": "200", "unit": "г"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "200 г лапши", "2 столовые ложки меда", "По вкусу – изюм"
        
        # Сначала пробуем паттерн с явным количеством
        pattern = r'^(\d+[\d\s/.,]*)\s*(г|кг|мл|л|мг|шт\.?|штук[иа]?|столов[ыа-я]*\s*лож[а-я]*|чайн[ыа-я]*\s*лож[а-я]*|стакан[а-я]*|щепотк[а-я]*|зубч[а-я]*|по\s+вкусу)?\s*[–-]?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                amount = amount_str.strip()
            
            # Обработка единицы измерения
            if unit:
                unit = unit.strip()
            else:
                unit = None
            
            # Очистка названия
            name = name.strip() if name else text
            # Убираем "из" в начале
            name = re.sub(r'^из\s+', '', name, flags=re.IGNORECASE)
            # Нормализуем название (родительный падеж -> именительный)
            name = self.normalize_ingredient_name(name)
            
            if not name or len(name) < 2:
                return None
            
            return {
                "name": name,
                "amount": int(amount) if amount and '.' not in amount else amount,
                "units": unit
            }
        
        # Паттерн "По вкусу – изюм"
        pattern2 = r'^По\s+вкусу\s*[–-]?\s*(.+)$'
        match2 = re.match(pattern2, text, re.IGNORECASE)
        
        if match2:
            name = match2.group(1).strip()
            return {
                "name": name,
                "amount": None,
                "units": "по вкусу"
            }
        
        # Если паттерны не совпали, пробуем просто текст как название
        # Но проверяем, что это не заголовок
        if not text.endswith(':') and len(text) > 2:
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions = []
        
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Способ 1: Ищем ol после "Приготовление:"
        paragraphs = entry_content.find_all('p')
        for p in paragraphs:
            text = p.get_text(strip=True)
            if re.match(r'^Приготовление:?\s*$', text, re.IGNORECASE):
                # Проверяем следующий элемент
                next_sibling = p.find_next_sibling()
                if next_sibling and next_sibling.name == 'ol':
                    items = next_sibling.find_all('li')
                    for idx, item in enumerate(items, 1):
                        step_text = self.clean_text(item.get_text())
                        if step_text:
                            instructions.append(f"{idx}. {step_text}")
                    if instructions:
                        return ' '.join(instructions)
        
        # Способ 2: Ищем заголовки с id="prigotovlenie"
        prep_heading = entry_content.find(['h2', 'h3'], id=re.compile(r'prigotov', re.I))
        if prep_heading:
            # Ищем ol список после заголовка
            current = prep_heading.find_next_sibling()
            while current and current.name not in ['h1', 'h2']:
                if current.name == 'ol':
                    items = current.find_all('li')
                    for idx, item in enumerate(items, 1):
                        step_text = self.clean_text(item.get_text())
                        if step_text:
                            instructions.append(f"{idx}. {step_text}")
                    if instructions:
                        return ' '.join(instructions)
                current = current.find_next_sibling()
        
        # Способ 3: Ищем все ol в content
        if not instructions:
            ol_lists = entry_content.find_all('ol')
            for ol in ol_lists:
                items = ol.find_all('li')
                # Проверяем, что это похоже на инструкции (больше 3 пунктов)
                if len(items) >= 3:
                    temp_instructions = []
                    for idx, item in enumerate(items, 1):
                        step_text = self.clean_text(item.get_text())
                        if step_text:
                            temp_instructions.append(f"{idx}. {step_text}")
                    if temp_instructions:
                        instructions = temp_instructions
                        break
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Проверяем классы article
        article = self.soup.find('article')
        if article:
            classes = article.get('class', [])
            for cls in classes:
                if cls.startswith('category-'):
                    category = cls.replace('category-', '')
                    # Преобразуем в читаемый формат
                    if category == 'recipies':
                        return 'Recipes'
                    elif category == 'poleznoe':
                        return 'Useful'
                    elif category == 'deserty':
                        return 'Dessert'
                    return category.title()
        
        # Альтернатива - из breadcrumbs
        breadcrumb = self.soup.find('div', class_='breadcrumb')
        if breadcrumb:
            links = breadcrumb.find_all('a')
            if len(links) > 1:
                # Берем предпоследнюю категорию
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в тексте паттерны времени
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            text = entry_content.get_text()
            # Паттерны для времени подготовки
            patterns = [
                r'Время\s+подготовки[:\s]*(\d+)\s*(минут|мин|час)',
                r'Подготовка[:\s]*(\d+)\s*(минут|мин|час)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    amount = match.group(1)
                    unit = match.group(2)
                    if 'час' in unit:
                        return f"{amount} hours"
                    else:
                        return f"{amount} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте паттерны времени приготовления
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            text = entry_content.get_text()
            # Паттерны для времени приготовления
            patterns = [
                r'Время\s+приготовления[:\s]*(\d+)\s*(минут|мин|час)',
                r'Готовка[:\s]*(\d+)\s*(минут|мин|час)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    amount = match.group(1)
                    unit = match.group(2)
                    if 'час' in unit:
                        return f"{amount} hours"
                    else:
                        return f"{amount} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в тексте паттерны общего времени
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            text = entry_content.get_text()
            # Паттерны для общего времени
            patterns = [
                r'Общее\s+время[:\s]*(\d+)\s*(минут|мин|час)',
                r'Всего[:\s]*(\d+)\s*(минут|мин|час)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    amount = match.group(1)
                    unit = match.group(2)
                    if 'час' in unit:
                        return f"{amount} hours"
                    else:
                        return f"{amount} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем секции с примечаниями/советами
        notes_patterns = [
            r'Примечани[ея]',
            r'Совет[ы]?',
            r'Заметк[аи]',
        ]
        
        # Ищем параграфы или секции с такими заголовками
        for pattern in notes_patterns:
            heading = entry_content.find(['h2', 'h3', 'h4', 'p'], 
                                        string=re.compile(pattern, re.I))
            if heading:
                # Берем текст из следующего элемента
                next_elem = heading.find_next_sibling()
                if next_elem:
                    text = self.clean_text(next_elem.get_text())
                    if text and len(text) > 10:
                        return text
        
        # Альтернатива: ищем параграфы с ключевыми словами
        paragraphs = entry_content.find_all('p')
        for p in paragraphs:
            text = p.get_text(strip=True)
            if re.search(r'(можно|рекомендуется|совет|подсказка)', text, re.IGNORECASE):
                cleaned = self.clean_text(text)
                if cleaned and 20 < len(cleaned) < 200:
                    return cleaned
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем мета-теги с ключевыми словами
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Разделяем по запятой и очищаем
            tags = [self.clean_text(tag) for tag in keywords.split(',') if tag.strip()]
            return ', '.join(tags) if tags else None
        
        # Альтернатива - из article:tag
        article_tags = self.soup.find_all('meta', property='article:tag')
        if article_tags:
            tags = []
            for tag in article_tags:
                content = tag.get('content')
                if content:
                    tags.append(self.clean_text(content))
            return ', '.join(tags) if tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Главное изображение из og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Изображения из JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'thumbnailUrl' in json_ld:
            thumbnail = json_ld['thumbnailUrl']
            if thumbnail and thumbnail not in urls:
                urls.append(thumbnail)
        
        # 3. Изображения из контента
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            images = entry_content.find_all('img', src=True)
            for img in images:
                src = img.get('src')
                if src and src.startswith('http') and src not in urls:
                    urls.append(src)
                    if len(urls) >= 5:  # Ограничиваем количество
                        break
        
        return ','.join(urls) if urls else None
    
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
    """Точка входа для обработки HTML файлов malinika.ru"""
    import os
    
    # Путь к директории с препроцессированными файлами
    preprocessed_dir = os.path.join("preprocessed", "malinika_ru")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(MalinikaExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python malinika_ru.py")


if __name__ == "__main__":
    main()
