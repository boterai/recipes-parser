"""
Экстрактор данных рецептов для сайта drinkownia.pl
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class DrinkowniaExtractor(BaseRecipeExtractor):
    """Экстрактор для drinkownia.pl"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала проверяем, есть ли в статье рецепт с h3 "Składniki"
        # (это может быть статья с несколькими рецептами)
        h3_skladniki = self.soup.find('h3', string=re.compile(r'Składniki', re.I))
        if h3_skladniki:
            # Ищем h2 перед этим h3
            h2 = h3_skladniki.find_previous('h2')
            if h2:
                title = h2.get_text()
                # Убираем "Przepis:" в начале
                title = re.sub(r'^Przepis:\s*', '', title, flags=re.I)
                # Убираем описательную часть после тире
                title = re.sub(r'\s*[—–]\s*.*$', '', title)
                # Убираем части в скобках
                title = re.sub(r'\s*\([^)]*\)\s*$', '', title)
                return self.clean_text(title)
        
        # Если нет h3 "Składniki", пробуем из JSON-LD (Article)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Article' and data.get('headline'):
                    headline = data['headline']
                    # Убираем лишние части типа "– описание (N składniki)"
                    headline = re.sub(r'\s*–[^(]*\([^)]*\)\s*$', '', headline)
                    headline = re.sub(r'\s*–.*$', '', headline)
                    return self.clean_text(headline)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*–[^(]*\([^)]*\)\s*$', '', title)
            title = re.sub(r'\s*–.*$', '', title)
            return self.clean_text(title)
        
        # Или из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            title = re.sub(r'\s*–[^(]*\([^)]*\)\s*$', '', title)
            title = re.sub(r'\s*–.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала проверяем, есть ли recipe-specific описание (для статей с несколькими рецептами)
        h3_skladniki = self.soup.find('h3', string=re.compile(r'Składniki', re.I))
        if h3_skladniki:
            # Ищем h2 перед h3 Składniki
            h2 = h3_skladniki.find_previous('h2')
            if h2:
                # Ищем первый параграф после h2 и до h3 Składniki
                p = h2.find_next('p')
                if p and p.find_previous('h3') != h3_skladniki:
                    desc_text = p.get_text(strip=True)
                    # Берем только первое предложение
                    first_sentence = desc_text.split('.')[0]
                    if first_sentence and len(first_sentence) > 10:
                        return self.clean_text(first_sentence + '.')
        
        # Пробуем из JSON-LD (Article)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Article' and data.get('description'):
                    return self.clean_text(data['description'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Или из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "60 ml wódki" или "1-2 ćwiartki limonki"
            
        Returns:
            dict: {"name": "wódki", "amount": "60", "units": "ml"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "60 ml wódki", "30 ml (1 uncja) Kahluy", "1–2 ćwiartki limonki"
        # Обрабатываем разные форматы количества: "60", "40-50", "40–50", "1-2"
        pattern = r'^([\d\s/.,–-]+)?\s*(ml|g|kg|l|uncj[ae]|uncji|ćwiartki|ćwiartka|kostki?|do\s+dopełnienia|sztuk[ia]?)?\s*(\([^)]*\))?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, parenthetical, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Заменяем тире на дефис
            amount_str = amount_str.replace('–', '-')
            amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем фразы в скобках (они уже извлечены)
        name = re.sub(r'\([^)]*\)', '', name)
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
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем h3 "Składniki" (для статей с несколькими рецептами)
        h3_skladniki = self.soup.find('h3', string=re.compile(r'Składniki', re.I))
        
        if h3_skladniki:
            # Получаем следующий ul элемент
            ul = h3_skladniki.find_next('ul')
            
            if ul:
                # Извлекаем элементы списка
                items = ul.find_all('li')
                
                for item in items:
                    ingredient_text = item.get_text(strip=True)
                    ingredient_text = self.clean_text(ingredient_text)
                    
                    # Пропускаем рекламные вставки
                    if 'reklam' in ingredient_text.lower() or 'personalizowane' in ingredient_text.lower():
                        continue
                    
                    if ingredient_text:
                        # Парсим в структурированный формат
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
        
        # Если не нашли через h3, пробуем h2 "Składniki"
        if not ingredients:
            h2_skladniki = self.soup.find('h2', string=re.compile(r'Składniki', re.I))
            
            if h2_skladniki:
                # Получаем следующий ul элемент
                ul = h2_skladniki.find_next('ul')
                
                if ul:
                    # Извлекаем элементы списка
                    items = ul.find_all('li')
                    
                    for item in items:
                        ingredient_text = item.get_text(strip=True)
                        ingredient_text = self.clean_text(ingredient_text)
                        
                        if ingredient_text:
                            # Парсим в структурированный формат
                            parsed = self.parse_ingredient(ingredient_text)
                            if parsed:
                                ingredients.append(parsed)
        
        # Если не нашли через h2/h3, пробуем извлечь из articleBody
        if not ingredients:
            json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
            
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    if data.get('@type') == 'Article' and data.get('articleBody'):
                        article_body = data['articleBody']
                        
                        # Ищем секцию ингредиентов
                        if 'Składniki' in article_body:
                            start = article_body.find('Składniki')
                            end = article_body.find('Jak przygotować', start)
                            
                            if end == -1:
                                end = start + 500
                            
                            ingredients_section = article_body[start:end]
                            
                            # Разбиваем на строки и парсим
                            lines = ingredients_section.split('\n')
                            for line in lines[1:]:  # Пропускаем заголовок
                                line = line.strip()
                                if line and not line.startswith('Jak'):
                                    parsed = self.parse_ingredient(line)
                                    if parsed and parsed['name']:
                                        ingredients.append(parsed)
                                        
                        if ingredients:
                            break
                except (json.JSONDecodeError, KeyError):
                    continue
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions = []
        
        # Сначала пробуем h3 "Przygotowanie" (для статей с несколькими рецептами)
        h3_instructions = self.soup.find('h3', string=re.compile(r'Przygotowanie', re.I))
        
        if h3_instructions:
            # Получаем следующий ol или p элемент
            next_elem = h3_instructions.find_next(['ol', 'p'])
            
            if next_elem and next_elem.name == 'ol':
                # Извлекаем шаги из списка
                items = next_elem.find_all('li')
                for item in items:
                    step_text = item.get_text(strip=True)
                    step_text = self.clean_text(step_text)
                    if step_text:
                        instructions.append(step_text)
            elif next_elem and next_elem.name == 'p':
                # Если это параграф, берем его текст
                step_text = next_elem.get_text(strip=True)
                step_text = self.clean_text(step_text)
                if step_text:
                    instructions.append(step_text)
        
        # Если не нашли через h3, пробуем h2 "Sposób przygotowania" или "Jak przygotować"
        if not instructions:
            h2_instructions = self.soup.find('h2', string=re.compile(r'Sposób przygotowania|Jak przygotować', re.I))
            
            if h2_instructions:
                # Получаем следующий ol или p элемент
                next_elem = h2_instructions.find_next(['ol', 'p', 'div'])
                
                if next_elem and next_elem.name == 'ol':
                    # Извлекаем шаги из списка
                    items = next_elem.find_all('li')
                    for item in items:
                        step_text = item.get_text(strip=True)
                        step_text = self.clean_text(step_text)
                        if step_text:
                            instructions.append(step_text)
                elif next_elem and next_elem.name == 'p':
                    # Если это параграф, берем его текст
                    step_text = next_elem.get_text(strip=True)
                    step_text = self.clean_text(step_text)
                    if step_text:
                        instructions.append(step_text)
        
        # Если не нашли через h2/h3, пробуем извлечь из articleBody
        if not instructions:
            json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
            
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    if data.get('@type') == 'Article' and data.get('articleBody'):
                        article_body = data['articleBody']
                        
                        # Ищем секцию инструкций между "Jak przygotować" и следующим заголовком
                        if 'Jak przygotować' in article_body:
                            start = article_body.find('Jak przygotować')
                            # Находим конец секции - следующий заголовок с большой буквы или двоеточием
                            # Чаще всего это "Proporcje", "Triki", или конец статьи
                            possible_ends = []
                            for marker in ['Proporcje', 'Triki', 'Wariacje', 'Porady', 'FAQ']:
                                idx = article_body.find(marker, start + 50)
                                if idx != -1:
                                    possible_ends.append(idx)
                            
                            if possible_ends:
                                end = min(possible_ends)
                            else:
                                # Если маркеров нет, берем 600 символов
                                end = start + 600
                            
                            instructions_section = article_body[start:end]
                            
                            # Убираем заголовок
                            instructions_section = re.sub(r'^Jak przygotować[^?]*\?\s*', '', instructions_section)
                            
                            # Убираем лишние пробелы
                            instructions_section = re.sub(r'\s+', ' ', instructions_section).strip()
                            
                            if instructions_section and len(instructions_section) > 20:
                                return self.clean_text(instructions_section)
                            
                except (json.JSONDecodeError, KeyError):
                    continue
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Пробуем из JSON-LD (articleSection)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Article' and data.get('articleSection'):
                    return self.clean_text(data['articleSection'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Сначала пробуем найти в параграфе между h2 и h3 Składniki (для статей с несколькими рецептами)
        h3_skladniki = self.soup.find('h3', string=re.compile(r'Składniki', re.I))
        if h3_skladniki:
            h2 = h3_skladniki.find_previous('h2')
            if h2:
                # Ищем параграф с временем между h2 и h3
                for p in h2.find_all_next('p'):
                    if p.find_previous('h3') == h3_skladniki:
                        break
                    text = p.get_text()
                    if 'Czas przygotowania' in text or 'przygotowania' in text.lower():
                        # Извлекаем время
                        match = re.search(r'Czas przygotowania:\s*(\d+[–-]?\d*)\s*(minut[ya]?|min)', text, re.I)
                        if match:
                            return f"{match.group(1)} {match.group(2)}"
        
        # Ищем в articleBody или HTML
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Article' and data.get('articleBody'):
                    article_body = data['articleBody']
                    
                    # Ищем паттерны времени
                    time_patterns = [
                        r'Czas przygotowania:\s*(?:ok\.\s*)?(\d+[–-]\d+|\d+)\s*(minut[ya]?|min|godzin[ya]?|h)',
                        r'przygotowania:\s*(?:ok\.\s*)?(\d+[–-]\d+|\d+)\s*(minut[ya]?|min|godzin[ya]?|h)'
                    ]
                    
                    for pattern in time_patterns:
                        match = re.search(pattern, article_body, re.I)
                        if match:
                            time_val = match.group(1)
                            time_unit = match.group(2)
                            return f"{time_val} {time_unit}"
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        # Для drinkownia.pl обычно нет времени готовки (это напитки)
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Для drinkownia.pl обычно нет общего времени
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Сначала пробуем h3 "Triki i wariacje" (для статей с несколькими рецептами)
        h3_triki = self.soup.find('h3', string=re.compile(r'Triki|wariacje', re.I))
        
        if h3_triki:
            # Получаем следующий ul или p элемент
            next_elem = h3_triki.find_next(['ul', 'p'])
            
            if next_elem and next_elem.name == 'ul':
                # Извлекаем первый пункт списка
                li = next_elem.find('li')
                if li:
                    note_text = li.get_text(strip=True)
                    return self.clean_text(note_text)
            elif next_elem and next_elem.name == 'p':
                note_text = next_elem.get_text(strip=True)
                return self.clean_text(note_text)
        
        # Пробуем h2 "Podawanie" или "Wariacje"
        for pattern in [r'Podawanie', r'Wariacje', r'Triki']:
            h2 = self.soup.find('h2', string=re.compile(pattern, re.I))
            if h2:
                # Получаем следующий p элемент
                p = h2.find_next('p')
                if p:
                    note_text = p.get_text(strip=True)
                    return self.clean_text(note_text)
        
        # Ищем секции с советами в articleBody
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Article' and data.get('articleBody'):
                    article_body = data['articleBody']
                    
                    # Ищем секцию "Proporcje" - берем текст после заголовка до следующего раздела
                    if 'Proporcje' in article_body:
                        start = article_body.find('Proporcje')
                        # Находим конец секции
                        possible_ends = []
                        for marker in ['Kiedy', 'FAQ', 'Wariacje', 'Triki']:
                            idx = article_body.find(marker, start + 50)
                            if idx != -1:
                                possible_ends.append(idx)
                        
                        if possible_ends:
                            end = min(possible_ends)
                        else:
                            end = start + 400
                        
                        notes_section = article_body[start:end]
                        
                        # Убираем заголовок
                        notes_section = re.sub(r'^Proporcje[^:]*:\s*', '', notes_section)
                        
                        # Берем первое предложение
                        sentences = notes_section.split('.')
                        if sentences and len(sentences[0]) > 10:
                            return self.clean_text(sentences[0].strip() + '.')
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Пробуем из JSON-LD (keywords)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Article' and data.get('keywords'):
                    keywords = data['keywords']
                    # Заменяем запятые на запятые с пробелами для единообразия
                    keywords = re.sub(r',\s*', ', ', keywords)
                    return keywords
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Article' and data.get('image'):
                    img = data['image']
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, list):
                        urls.extend([i for i in img if isinstance(i, str)])
                    elif isinstance(img, dict):
                        if 'url' in img:
                            urls.append(img['url'])
                        elif 'contentUrl' in img:
                            urls.append(img['contentUrl'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 2. Из meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)
        
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
        dish_name = self.extract_dish_name()
        # Capitalize first letter
        if dish_name:
            dish_name = dish_name[0].upper() + dish_name[1:] if len(dish_name) > 0 else dish_name
        
        return {
            "dish_name": dish_name,
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
    # По умолчанию обрабатываем папку preprocessed/drinkownia_pl
    recipes_dir = os.path.join("preprocessed", "drinkownia_pl")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(DrinkowniaExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python drinkownia_pl.py")


if __name__ == "__main__":
    main()
