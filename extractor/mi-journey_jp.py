"""
Экстрактор данных рецептов для сайта mi-journey.jp
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MiJourneyExtractor(BaseRecipeExtractor):
    """Экстрактор для mi-journey.jp"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем тип Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'name' in data:
                        name = data['name']
                        # Убираем суффиксы
                        name = re.sub(r'\s*[|｜].*$', '', name)
                        name = re.sub(r'【.*?】', '', name)
                        name = re.sub(r'\s*(プロのレシピ|簡単レシピ|レシピ).*$', '', name)
                        return self.clean_text(name)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s*[|｜].*$', '', title)
            title = re.sub(r'【.*?】', '', title)
            return self.clean_text(title)
        
        # Из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            title = re.sub(r'\s*[|｜].*$', '', title)
            title = re.sub(r'【.*?】', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'description' in data and data['description']:
                        return self.clean_text(data['description'])
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient_from_text(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента из recipeIngredient
        
        Args:
            text: Строка вида "薄力粉…200g" или "卵…2個"
            
        Returns:
            dict: {"name": "薄力粉", "amount": "200", "unit": "g"} или None
        """
        if not text:
            return None
        
        text = self.clean_text(text)
        
        # Паттерн для извлечения: название…количество+единица
        # Примеры: "薄力粉…200g", "卵…2個", "塩…小さじ1"
        pattern = r'^(.+?)…(.+)$'
        match = re.match(pattern, text)
        
        if not match:
            # Если нет разделителя …, пробуем другие разделители
            pattern = r'^(.+?)[:\s]+(.+)$'
            match = re.match(pattern, text)
        
        if not match:
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
        
        name, amount_unit = match.groups()
        name = name.strip()
        amount_unit = amount_unit.strip()
        
        # Извлекаем количество и единицу из amount_unit
        # Паттерны единиц измерения (японские и общие)
        units_pattern = r'(g|kg|ml|l|個|本|枚|片|缶|パック|大さじ|小さじ|合|カップ|杯|cm|mm|適量|少々)'
        
        # Ищем числовое значение и единицу
        # Примеры: "200g", "2個", "1/2個", "大さじ1"
        amount_match = re.search(r'([0-9０-９./]+)\s*(' + units_pattern + ')', amount_unit)
        
        if amount_match:
            amount = amount_match.group(1)
            unit = amount_match.group(2)
            
            # Конвертируем полноширинные числа в полуширинные
            amount = amount.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
            
            return {
                "name": name,
                "amount": amount,
                "unit": unit
            }
        
        # Если единица в начале (например "大さじ1")
        unit_first_match = re.search(r'^(' + units_pattern + r')\s*([0-9０-９./]+)', amount_unit)
        if unit_first_match:
            unit = unit_first_match.group(1)
            amount = unit_first_match.group(2)
            amount = amount.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
            
            return {
                "name": name,
                "amount": amount,
                "unit": unit
            }
        
        # Если только количество без единицы
        amount_only = re.search(r'([0-9０-９./]+)', amount_unit)
        if amount_only:
            amount = amount_only.group(1)
            amount = amount.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
            return {
                "name": name,
                "amount": amount,
                "unit": None
            }
        
        # Если ничего не распарсилось, возвращаем как есть
        return {
            "name": name,
            "amount": None,
            "unit": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'recipeIngredient' in data and data['recipeIngredient']:
                        ingredient_text = data['recipeIngredient']
                        
                        # Проверяем, содержит ли текст "【材料と作り方】" (это комбинированный формат)
                        # В этом случае извлекаем ингредиенты из текста внутри этих секций
                        if '【材料と作り方】' in ingredient_text:
                            # Извлекаем ингредиенты из текста после "【材料と作り方】"
                            # Паттерн: после "【材料と作り方】" идет текст с ингредиентами
                            parts = re.split(r'【材料と作り方】', ingredient_text)
                            
                            for part in parts[1:]:  # Пропускаем первую часть (до первого разделителя)
                                # Берем текст до первой точки или до конца
                                # Это обычно содержит ингредиенты
                                # Извлекаем ингредиенты, упомянутые с количеством
                                ingredient_matches = re.findall(r'([^、。]+[0-9０-９]+(?:[~/～]?[0-9０-９]+)?[a-zA-Zぁ-んァ-ン一-龯]+)', part)
                                
                                for match in ingredient_matches:
                                    parsed = self.parse_ingredient_from_text(match.strip())
                                    if parsed and parsed['name']:
                                        ingredient = {
                                            "name": parsed['name'],
                                            "units": parsed['unit'],
                                            "amount": parsed['amount']
                                        }
                                        ingredients.append(ingredient)
                            
                            if ingredients:
                                return json.dumps(ingredients, ensure_ascii=False)
                            else:
                                # Если не удалось извлечь, возвращаем None (будем искать в HTML)
                                continue
                        
                        # Стандартный формат
                        # Разбиваем по переводам строк и другим разделителям
                        lines = re.split(r'[\r\n]+', ingredient_text)
                        
                        for line in lines:
                            line = line.strip()
                            
                            # Пропускаем заголовки секций в квадратных скобках или с двоеточием
                            if re.match(r'^【.*?】', line) or re.match(r'^\[.*?\]', line):
                                continue
                            
                            if not line or line.endswith(':') or line.endswith('：'):
                                continue
                            
                            # Парсим ингредиент
                            parsed = self.parse_ingredient_from_text(line)
                            if parsed and parsed['name']:
                                # Меняем ключ units на unit для совместимости
                                if 'unit' in parsed:
                                    ingredient = {
                                        "name": parsed['name'],
                                        "units": parsed['unit'],
                                        "amount": parsed['amount']
                                    }
                                    ingredients.append(ingredient)
                        
                        if ingredients:
                            return json.dumps(ingredients, ensure_ascii=False)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог или пустой, ищем в HTML
        # Ищем заголовок с "材料" (материалы/ингредиенты)
        headings = self.soup.find_all(['h3', 'h4'])
        
        for heading in headings:
            heading_text = heading.get_text()
            if '材料' in heading_text and '作り方' not in heading_text:
                # Ищем следующий список <ul> после заголовка
                next_ul = heading.find_next('ul')
                if next_ul:
                    # Извлекаем элементы списка
                    items = next_ul.find_all('li')
                    for item in items:
                        ingredient_text = item.get_text(strip=True)
                        parsed = self.parse_ingredient_from_text(ingredient_text)
                        if parsed and parsed['name']:
                            ingredient = {
                                "name": parsed['name'],
                                "units": parsed['unit'],
                                "amount": parsed['amount']
                            }
                            ingredients.append(ingredient)
                    
                    if ingredients:
                        return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    # Проверяем recipeInstructions
                    if 'recipeInstructions' in data:
                        instructions = data['recipeInstructions']
                        
                        if isinstance(instructions, list) and len(instructions) > 0:
                            for step in instructions:
                                if isinstance(step, str):
                                    step_text = self.clean_text(step)
                                    # Убираем лидирующие переносы строк и номера
                                    step_text = re.sub(r'^[\r\n]+', '', step_text)
                                    step_text = re.sub(r'^\d+\.\s*', '', step_text)
                                    if step_text:
                                        steps.append(step_text)
                        
                        if steps:
                            # Форматируем с номерами
                            formatted_steps = [f"{i}. {step}" for i, step in enumerate(steps, 1)]
                            return ' '.join(formatted_steps)
                    
                    # Проверяем recipeIngredient на случай комбинированного формата
                    if 'recipeIngredient' in data and data['recipeIngredient']:
                        ingredient_text = data['recipeIngredient']
                        
                        # Если содержит "【材料と作り方】", извлекаем инструкции
                        if '【材料と作り方】' in ingredient_text:
                            # Извлекаем текст после "【材料と作り方】"
                            # Разбиваем по этому паттерну и берем части с инструкциями
                            parts = re.split(r'【材料と作り方】', ingredient_text)
                            
                            instruction_text = ''
                            for part in parts:
                                if part.strip():
                                    # Извлекаем только текст инструкций (без названий секций)
                                    # Убираем названия секций типа "ぶりしゃぶ鍋「スープ」のレシピ"
                                    # Оставляем только текст после "【材料と作り方】"
                                    cleaned = re.sub(r'^[^。]+のレシピ\s*', '', part.strip())
                                    if cleaned and not cleaned.startswith('「'):
                                        instruction_text += cleaned + ' '
                            
                            if instruction_text.strip():
                                return self.clean_text(instruction_text.strip())
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог или пустой, ищем в HTML
        # Ищем заголовок с "作り方" (способ приготовления)
        headings = self.soup.find_all(['h3', 'h4'])
        
        for heading in headings:
            heading_text = heading.get_text()
            if '作り方' in heading_text:
                # Ищем все следующие h4 заголовки (шаги) до следующего h2/h3
                current = heading.find_next_sibling()
                
                while current:
                    # Останавливаемся на следующем h2 или h3
                    if current.name in ['h2', 'h3']:
                        break
                    
                    # Ищем h4 заголовки с номерами шагов
                    if current.name == 'h4':
                        step_text = current.get_text(strip=True)
                        # Убираем номер в начале (например "1.　")
                        step_text = re.sub(r'^\d+[.．　\s]+', '', step_text)
                        if step_text:
                            steps.append(step_text)
                    
                    current = current.find_next_sibling()
                
                if steps:
                    # Форматируем с номерами
                    formatted_steps = [f"{i}. {step}" for i, step in enumerate(steps, 1)]
                    return ' '.join(formatted_steps)
                
                # Если нет h4, пробуем найти список ol после заголовка
                next_ol = heading.find_next('ol')
                if next_ol:
                    items = next_ol.find_all('li')
                    for item in items:
                        step_text = item.get_text(separator=' ', strip=True)
                        step_text = self.clean_text(step_text)
                        if step_text:
                            steps.append(step_text)
                    
                    if steps:
                        formatted_steps = [f"{i}. {step}" for i, step in enumerate(steps, 1)]
                        return ' '.join(formatted_steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Для японского сайта используем стандартную категорию
        # Можно попробовать извлечь из JSON-LD recipeCuisine
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'recipeCuisine' in data and data['recipeCuisine']:
                        cuisine = data['recipeCuisine']
                        # Конвертируем японскую кухню в английскую категорию
                        if 'イタリア' in cuisine:
                            return 'Main Course'
                        else:
                            return 'Main Course'
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # По умолчанию возвращаем Main Course
        return 'Main Course'
    
    def extract_time_from_text(self, time_text: str) -> Optional[str]:
        """
        Извлечение времени из текста
        
        Args:
            time_text: Текст с временем, например "60分" или "1時間30分"
            
        Returns:
            Время в формате "60 minutes"
        """
        if not time_text:
            return None
        
        time_text = self.clean_text(time_text)
        
        # Извлекаем часы и минуты
        hours = 0
        minutes = 0
        
        # Ищем часы (時間)
        hour_match = re.search(r'(\d+)\s*時間', time_text)
        if hour_match:
            hours = int(hour_match.group(1))
        
        # Ищем минуты (分)
        min_match = re.search(r'(\d+)\s*分', time_text)
        if min_match:
            minutes = int(min_match.group(1))
        
        # Конвертируем в минуты
        total_minutes = hours * 60 + minutes
        
        if total_minutes > 0:
            return f"{total_minutes} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Для mi-journey.jp время часто указано в контексте рецепта
        # Пробуем найти упоминания времени в тексте
        
        # Ищем в параграфах текст с временем подготовки
        paragraphs = self.soup.find_all('p')
        
        for p in paragraphs:
            text = p.get_text()
            # Ищем упоминания времени подготовки/замешивания
            if 'こねる' in text or '寝かせる' in text:
                # Ищем время в минутах или часах
                time_match = re.search(r'(\d+)\s*時間', text)
                if time_match:
                    hours = int(time_match.group(1))
                    return f"{hours * 60} minutes"
                
                time_match = re.search(r'(\d+)\s*分', text)
                if time_match:
                    minutes = int(time_match.group(1))
                    return f"{minutes} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем упоминания времени готовки/варки/запекания
        paragraphs = self.soup.find_all('p')
        headings = self.soup.find_all(['h3', 'h4'])
        
        all_elements = paragraphs + headings
        
        for elem in all_elements:
            text = elem.get_text()
            # Ищем упоминания времени готовки
            if '焼' in text or '煮込' in text or '炊' in text:
                # Ищем время в минутах
                time_match = re.search(r'(\d+)\s*分', text)
                if time_match:
                    minutes = int(time_match.group(1))
                    # Берем первое найденное значение как cook_time
                    return f"{minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'totalTime' in data and data['totalTime']:
                        # totalTime может быть пустой строкой
                        pass
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если у нас есть prep и cook, вычисляем total
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep and cook:
            prep_min = int(re.search(r'(\d+)', prep).group(1))
            cook_min = int(re.search(r'(\d+)', cook).group(1))
            return f"{prep_min + cook_min} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секции с заметками или советами
        # Обычно это секции с заголовками типа "市販の...で代用する場合"
        
        # Ищем заголовок с "代用" (замена/альтернатива)
        h2_tags = self.soup.find_all(['h2', 'h3', 'h4'])
        
        for tag in h2_tags:
            text = tag.get_text()
            if '代用' in text or '市販' in text:
                # Ищем следующий параграф после заголовка
                next_p = tag.find_next('p')
                if next_p:
                    note_text = next_p.get_text(separator=' ', strip=True)
                    return self.clean_text(note_text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # 1. Пробуем извлечь из recipeCuisine в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'recipeCuisine' in data and data['recipeCuisine']:
                        cuisine = data['recipeCuisine']
                        if cuisine:
                            tags.append(cuisine)
                    
                    # Добавляем название блюда как тег (упрощенная версия)
                    if 'name' in data and data['name']:
                        name = data['name']
                        # Извлекаем ключевые слова из названия
                        # Убираем служебные слова
                        name_clean = re.sub(r'【.*?】', '', name)
                        name_clean = re.sub(r'\s*(プロのレシピ|簡単レシピ|レシピ|作り方).*$', '', name_clean)
                        if name_clean:
                            # Извлекаем основное слово (обычно название блюда в кавычках или в конце)
                            dish_match = re.search(r'「(.+?)」', name_clean)
                            if dish_match:
                                tags.append(dish_match.group(1))
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 2. Добавляем стандартную категорию как тег
        tags.append('メインディッシュ')
        
        # Убираем дубликаты
        seen = set()
        unique_tags = []
        for tag in tags:
            if tag and tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # article:image
        article_image = self.soup.find('meta', {'name': 'article-image'})
        if article_image and article_image.get('content'):
            urls.append(article_image['content'])
        
        # 2. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'image' in data:
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
                
                # Проверяем @graph для ImageObject
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
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
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        total_time = self.extract_total_time()
        notes = self.extract_notes()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "notes": notes,
            "tags": tags,
            "image_urls": image_urls
        }


def main():
    import os
    # Обрабатываем папку preprocessed/mi-journey_jp
    recipes_dir = os.path.join("preprocessed", "mi-journey_jp")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(MiJourneyExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python mi-journey_jp.py")


if __name__ == "__main__":
    main()
