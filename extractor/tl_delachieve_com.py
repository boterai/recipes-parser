"""
Экстрактор данных рецептов для сайта tl.delachieve.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TlDelachieveExtractor(BaseRecipeExtractor):
    """Экстрактор для tl.delachieve.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1_tag = self.soup.find('h1', class_='mvp-post-title')
        if h1_tag:
            return self.clean_text(h1_tag.get_text())
        
        # Альтернативно - из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем суффиксы типа " - Site Name"
            title = re.sub(r'\s*[-|]\s*.+$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - первый параграф после заголовка
        content_div = self.soup.find('div', id='mvp-post-content')
        if content_div:
            # Ищем первый параграф с текстом
            for p in content_div.find_all('p'):
                text = self.clean_text(p.get_text())
                if text and len(text) > 20 and 'ingredient' not in text.lower():
                    return text
        
        return None
    
    def parse_ingredient_text(self, ingredient_text: str) -> Optional[List[Dict]]:
        """
        Парсинг строки ингредиента в структурированный формат
        Может вернуть несколько ингредиентов, если они перечислены через запятую
        
        Формат: "ingredient name - amount unit" или "ingredient name - amount"
        Примеры:
        - "makapal na non-acidic smetana- 250 g"
        - "adjika acute - 5 malaking kutsara"
        - "asin, pulang matamis paminta - upang tikman" -> разбивается на отдельные ингредиенты
        
        Args:
            ingredient_text: Строка с ингредиентом
            
        Returns:
            list of dict: [{"name": "...", "amount": ..., "units": "..."}, ...] или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Убираем примечания в скобках и концевые точки/запятые
        text = re.sub(r'\([^)]*\)', '', text)
        text = re.sub(r'[;.,]+$', '', text).strip()
        
        # Паттерн: название - количество единица
        # Примеры: "smetana - 250 g", "adjika - 5 malaking kutsara", "manok - 10 mga PC"
        # Важно: ищем дефис с пробелами вокруг, чтобы не путать с дефисами в словах
        # Пытаемся найти последний дефис с пробелом перед ним (или без пробела если за ним идет число)
        # Сначала проверяем, есть ли "upang tikman" в тексте
        tikman_pattern = r'^(.+?)\s*-\s*(upang tikman|to taste|as needed).*$'
        tikman_match = re.match(tikman_pattern, text, re.IGNORECASE)
        
        if tikman_match:
            # Это может быть список ингредиентов через запятую, все "to taste"
            name = tikman_match.group(1).strip()
            # Разбиваем название на отдельные ингредиенты
            ingredients = []
            parts = re.split(r',\s*|\s+at\s+', name)
            for part in parts:
                part = part.strip()
                if part:
                    ingredients.append({
                        "name": part,
                        "amount": None,
                        "units": None
                    })
            return ingredients if ingredients else [{
                "name": name,
                "amount": None,
                "units": None
            }]
        
        # Паттерн для количественных ингредиентов: все до последнего " - " или "-\d" 
        pattern = r'^(.+?)\s*-\s*(\d.+)$'
        match = re.match(pattern, text)
        
        if not match:
            # Если нет дефиса с количеством, возвращаем только название
            return [{
                "name": text,
                "amount": None,
                "units": None
            }]
        
        name = match.group(1).strip()
        quantity_part = match.group(2).strip()
        
        # Пытаемся извлечь количество и единицу
        # Паттерн: число (возможно с дробью или диапазоном) + единица измерения
        qty_pattern = r'^(\d+(?:[.,/-]\d+)?)\s*(.+)?$'
        qty_match = re.match(qty_pattern, quantity_part)
        
        if qty_match:
            amount_str = qty_match.group(1).strip()
            unit = qty_match.group(2).strip() if qty_match.group(2) else None
            
            # Пробуем конвертировать amount в число
            try:
                # Заменяем запятую на точку и проверяем диапазоны
                if '-' in amount_str and not amount_str.startswith('-'):
                    # Диапазон вида "300-400"
                    amount = amount_str  # Оставляем как строку
                else:
                    amount_str = amount_str.replace(',', '.')
                    # Пробуем сделать int или float
                    if '.' in amount_str:
                        amount = float(amount_str)
                    else:
                        amount = int(amount_str)
            except (ValueError, AttributeError):
                amount = amount_str
            
            # Нормализация единиц измерения
            if unit:
                unit = unit.lower()
                # Убираем точки в конце
                unit = re.sub(r'\.$', '', unit)
                
                # Проверяем, есть ли в unit фраза "ng bawat uri" (of each type)
                # Это указывает на то, что нужно разбить на отдельные ингредиенты
                if 'ng bawat' in unit or 'ng bawat uri' in unit:
                    # Разбиваем name на части
                    parts = re.split(r',\s*|\s+at\s+', name)
                    # Убираем фразу из unit
                    unit = re.sub(r'\s*ng bawat.*$', '', unit).strip()
                    
                    ingredients = []
                    for part in parts:
                        part = part.strip()
                        if part:
                            ingredients.append({
                                "name": part,
                                "amount": amount,
                                "units": unit if unit else None
                            })
                    return ingredients if ingredients else None
                
                # Маппинг общих единиц
                unit_mapping = {
                    'pcs': 'pcs',
                    'pc': 'pc',
                    'mga pc': 'pcs',
                    'piraso': 'pcs',
                    'kutsara': 'tbsp',
                    'kutsarita': 'tsp',
                    'malaking kutsara': 'large tablespoons',
                    'spoons': 'spoons',
                    'pinches': 'pinches',
                    'ulo': 'head',
                    'kilo': 'kilo',
                    'gramo': 'grams',
                    'grams': 'grams',
                    'bundle': 'bundle',
                    'cloves': 'cloves',
                    'ng prutas': 'fruit',
                    'fruit': 'fruit',
                    'medium-sized': 'medium-sized',
                    'tablespoons': 'tablespoons',
                    'tablespoon': 'tablespoon'
                }
                unit = unit_mapping.get(unit, unit)
            
            return [{
                "name": name,
                "amount": amount,
                "units": unit
            }]
        else:
            # Не удалось разобрать количество, возвращаем как есть
            return [{
                "name": name,
                "amount": quantity_part if quantity_part else None,
                "units": None
            }]
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем все списки ингредиентов (могут быть несколько рецептов на странице)
        # Ищем маркер "Kinakailangang ingredients:"
        content_div = self.soup.find('div', id='mvp-post-content')
        if not content_div:
            return None
        
        # Ищем все <ul> списки, которые идут после маркеров ингредиентов
        for elem in content_div.find_all(['em', 'p', 'ul']):
            text = elem.get_text()
            
            # Проверяем, является ли это маркером ингредиентов
            if elem.name in ['em', 'p'] and 'ingredient' in text.lower():
                # Следующий элемент должен быть списком
                next_sibling = elem.find_next_sibling()
                while next_sibling and next_sibling.name != 'ul':
                    next_sibling = next_sibling.find_next_sibling()
                
                if next_sibling and next_sibling.name == 'ul':
                    # Извлекаем ингредиенты из списка
                    for li in next_sibling.find_all('li'):
                        ingredient_text = li.get_text(strip=True)
                        parsed_list = self.parse_ingredient_text(ingredient_text)
                        if parsed_list:
                            for parsed in parsed_list:
                                if parsed and parsed['name']:
                                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions = []
        
        content_div = self.soup.find('div', id='mvp-post-content')
        if not content_div:
            return None
        
        # Собираем все параграфы с текстом
        # Пропускаем параграфы с маркерами ингредиентов
        for p in content_div.find_all('p'):
            text = self.clean_text(p.get_text())
            
            # Пропускаем маркеры ингредиентов и короткие тексты
            if not text or len(text) < 20:
                continue
            if 'ingredient' in text.lower():
                continue
            
            # Добавляем текст как часть инструкций
            instructions.append(text)
        
        if not instructions:
            return None
        
        # Объединяем все инструкции и пытаемся разбить на шаги
        full_text = ' '.join(instructions)
        
        # Пытаемся найти предложения, которые описывают действия
        sentences = re.split(r'[.!?]\s+', full_text)
        
        # Фильтруем и нумеруем шаги
        steps = []
        step_num = 1
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence and len(sentence) > 15:
                # Проверяем, не является ли это уже нумерованным шагом
                if not re.match(r'^\d+\.', sentence):
                    steps.append(f"{step_num}. {sentence}")
                    step_num += 1
                else:
                    steps.append(sentence)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем категорию в ссылках
        cat_link = self.soup.find('a', class_='mvp-post-cat-link')
        if cat_link:
            cat_span = cat_link.find('span', class_='mvp-post-cat')
            if cat_span:
                return self.clean_text(cat_span.get_text())
        
        # Альтернативный поиск
        cat_elem = self.soup.find('span', class_='mvp-post-cat')
        if cat_elem:
            return self.clean_text(cat_elem.get_text())
        
        return None
    
    def extract_time_from_text(self, text: str, time_type: str = 'any') -> Optional[str]:
        """
        Извлечение времени из текста
        
        Args:
            text: Текст для поиска
            time_type: Тип времени ('prep', 'cook', 'total', 'any')
        """
        if not text:
            return None
        
        # Паттерны для поиска времени
        # Примеры: "60-90 minuto", "35 minuto", "tungkol sa 35 minuto"
        patterns = [
            r'(\d+(?:-\d+)?)\s*minuto',  # 60-90 minuto, 35 minuto
            r'(\d+(?:-\d+)?)\s*minute',  # 60 minute, 90 minutes
            r'(\d+(?:-\d+)?)\s*min',     # 60 min
            r'tungkol sa\s*(\d+)\s*minuto',  # about 35 minutes
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                time_value = match.group(1)
                return f"{time_value} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        content_div = self.soup.find('div', id='mvp-post-content')
        if not content_div:
            return None
        
        # Ищем время подготовки в тексте
        # Обычно упоминается как "marinate" или "mag-atsara"
        for p in content_div.find_all('p'):
            text = p.get_text()
            if 'atsara' in text.lower() or 'marinate' in text.lower():
                time = self.extract_time_from_text(text)
                if time:
                    return time
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        content_div = self.soup.find('div', id='mvp-post-content')
        if not content_div:
            return None
        
        # Ищем время готовки в тексте
        # Обычно упоминается как "maghurno" (bake) или "magluto" (cook)
        for p in content_div.find_all('p'):
            text = p.get_text()
            if 'maghurno' in text.lower() or 'hurno' in text.lower() or 'bake' in text.lower():
                time = self.extract_time_from_text(text)
                if time:
                    return time
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Пытаемся вычислить из prep + cook
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep and cook:
            # Извлекаем числа
            prep_nums = re.findall(r'\d+', prep)
            cook_nums = re.findall(r'\d+', cook)
            
            if prep_nums and cook_nums:
                # Берем максимальные значения, если есть диапазон
                prep_max = max([int(n) for n in prep_nums])
                cook_max = max([int(n) for n in cook_nums])
                total = prep_max + cook_max
                return f"{total} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        content_div = self.soup.find('div', id='mvp-post-content')
        if not content_div:
            return None
        
        # Ищем последний параграф, который может содержать заметки
        # Обычно это рекомендации по подаче или вариации
        paragraphs = content_div.find_all('p')
        if paragraphs:
            # Проверяем последние параграфы
            for p in reversed(paragraphs):
                text = self.clean_text(p.get_text())
                if text and len(text) > 20:
                    # Ищем ключевые слова для заметок
                    if any(word in text.lower() for word in ['serve', 'magsilbi', 'maaari', 'dapat']):
                        return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Извлекаем из категорий
        cat_links = self.soup.find_all('a', class_='mvp-post-cat-link')
        for link in cat_links:
            cat_span = link.find('span', class_='mvp-post-cat')
            if cat_span:
                tag = self.clean_text(cat_span.get_text()).lower()
                if tag and tag not in tags:
                    tags.append(tag)
        
        # Извлекаем из заголовка (основные ключевые слова)
        dish_name = self.extract_dish_name()
        if dish_name:
            # Добавляем ключевые слова из названия
            keywords = dish_name.lower().split()
            for word in keywords:
                word = word.strip('.,;:')
                if len(word) > 3 and word not in tags:
                    # Добавляем только значимые слова
                    if word not in ['the', 'and', 'with', 'for', 'mga', 'ang', 'para']:
                        tags.append(word)
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в meta-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем amp-img теги (AMP страницы)
        amp_images = self.soup.find_all('amp-img')
        for img in amp_images:
            src = img.get('src')
            if src and src.startswith('http'):
                urls.append(src)
        
        # 3. Обычные img теги
        images = self.soup.find_all('img')
        for img in images:
            src = img.get('src')
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
            
            # Возвращаем как строку через запятую
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
    # Обрабатываем папку preprocessed/tl_delachieve_com
    recipes_dir = os.path.join("preprocessed", "tl_delachieve_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(TlDelachieveExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python tl_delachieve_com.py")


if __name__ == "__main__":
    main()
