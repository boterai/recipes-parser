"""
Экстрактор данных рецептов для сайта kfetele.ro
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KfeteleRoExtractor(BaseRecipeExtractor):
    """Экстрактор для kfetele.ro"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT2H"
            
        Returns:
            Время в читаемом формате, например "90 minutes" или "2 hours"
        """
        if not duration or not duration.startswith('PT'):
            return None
        
        duration = duration[2:]  # Убираем "PT"
        
        hours = 0
        minutes = 0
        
        # Извлекаем часы
        hour_match = re.search(r'(\d+)H', duration)
        if hour_match:
            hours = int(hour_match.group(1))
        
        # Извлекаем минуты
        min_match = re.search(r'(\d+)M', duration)
        if min_match:
            minutes = int(min_match.group(1))
        
        # Форматируем результат
        if hours > 0 and minutes > 0:
            return f"{hours * 60 + minutes} minutes"
        elif hours > 0:
            if hours == 1:
                return "1 hour"
            return f"{hours} hours"
        elif minutes > 0:
            return f"{minutes} minutes"
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'name' in data:
                        # Убираем суффиксы типа " - KFetele"
                        name = data['name']
                        name = re.sub(r'\s*[-–]\s*KFetele.*$', '', name, flags=re.IGNORECASE)
                        # Убираем лишние точки и восклицательные знаки в конце
                        name = re.sub(r'[.!]+\s*$', '', name)
                        return self.clean_text(name)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*[-–]\s*KFetele.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'[.!]+\s*$', '', title)
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
                    if 'description' in data:
                        return self.clean_text(data['description'])
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем извлечь из JSON-LD (самый надежный способ)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'recipeIngredient' in data:
                        ingredient_list = data['recipeIngredient']
                        
                        # Если это строка, разбиваем по запятым
                        if isinstance(ingredient_list, str):
                            ingredient_list = [i.strip() for i in ingredient_list.split(',') if i.strip()]
                        
                        # Только если список НЕ пустой
                        if ingredient_list:
                            for ingredient_text in ingredient_list:
                                # Очищаем от лишних символов и пробелов
                                ingredient_text = self.clean_text(ingredient_text)
                                # Удаляем переносы строк
                                ingredient_text = ingredient_text.replace('\r', '').replace('\n', '')
                                
                                # Пропускаем заметки типа "la temperatura camerei"
                                if re.match(r'^(la temperatura camerei|după gust|pentru decor)$', ingredient_text, re.IGNORECASE):
                                    continue
                                
                                if ingredient_text and len(ingredient_text) > 1:
                                    parsed = self.parse_ingredient(ingredient_text)
                                    if parsed:
                                        ingredients.append(parsed)
                            
                            if ingredients:
                                break
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не дал результатов, пробуем извлечь из HTML
        if not ingredients:
            # Ищем секцию с заголовком "Ingrediente"
            # Паттерн: заголовок h2/h3 с текстом "Ingrediente", затем список <li>
            sections = self.soup.find_all(['h2', 'h3', 'h4'])
            
            for section in sections:
                section_text = section.get_text(strip=True)
                if re.search(r'ingrediente', section_text, re.IGNORECASE):
                    # Ищем следующий элемент - обычно это <ul> или <ol>
                    next_elem = section.find_next_sibling()
                    
                    # Иногда список может быть не прямым соседом, ищем все <li> после заголовка
                    # до следующего заголовка
                    li_items = []
                    current = section.find_next()
                    
                    while current and current.name not in ['h2', 'h3', 'h4']:
                        if current.name == 'li':
                            li_items.append(current)
                        current = current.find_next()
                    
                    for li in li_items:
                        ingredient_text = li.get_text(separator=' ', strip=True)
                        ingredient_text = self.clean_text(ingredient_text)
                        
                        if ingredient_text and len(ingredient_text) > 3:
                            parsed = self.parse_ingredient(ingredient_text)
                            if parsed:
                                ingredients.append(parsed)
                    
                    if ingredients:
                        break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "250 g făină" или "3 cepe medii"
            
        Returns:
            dict: {"name": "făină", "amount": 250, "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст (сохраняем регистр для названий)
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
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "250 g făină", "3 linguri de ulei", "O jumătate de linguriță de nucșoară măcinată"
        # Румынские единицы измерения - обновленный паттерн чтобы правильно захватывать "linguri" и т.п.
        pattern = r'^(?:[Oo]\s+jumătate\s+de\s+|[Uu]n\s+praf\s+de\s+|set\s+mic\s+(?:de\s+)?)?'
        pattern += r'([\d\s/.,]+)?\s*'
        # Изменил порядок - более длинные слова первыми чтобы "linguri" захватывалось до "l"
        pattern += r'(linguri(?:ță)?|lingură|kilograme?|mililitri?|litri?|grame?|bucăți|bucată|căței|cană|cani|kg|ml|g|l|pentru\s+decor)?'
        pattern += r'\s*(?:de\s+)?(.+)'
        
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
            # Обработка дробей типа "1/2" или "1 1/2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0.0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                # Преобразуем в int если целое число, иначе float
                amount = int(total) if total == int(total) else total
            else:
                # Преобразуем строку в число
                try:
                    num_str = amount_str.replace(',', '.')
                    num_val = float(num_str)
                    amount = int(num_val) if num_val == int(num_val) else num_val
                except ValueError:
                    amount = None
        
        # Специальная обработка для "O jumătate de"
        if re.search(r'[Oo]\s+jumătate\s+de', text, re.IGNORECASE) and not amount:
            amount = 0.5
        
        # Специальная обработка для "set mic"
        if re.search(r'set\s+mic', text, re.IGNORECASE) and not amount:
            amount = 'set mic'
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # НЕ удаляем "pisați", "tocate", "feliate" - они часть имени
        name = re.sub(r'\b(pentru decor|la temperatura camerei|după gust|dacă doriți)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые в конце
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
        
        # Сначала пробуем извлечь из JSON-LD (самый надежный способ)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'recipeInstructions' in data:
                        instructions = data['recipeInstructions']
                        
                        # Только если список НЕ пустой
                        if instructions:
                            if isinstance(instructions, list):
                                for idx, step in enumerate(instructions, 1):
                                    if isinstance(step, dict) and 'text' in step:
                                        step_text = self.clean_text(step['text'])
                                        steps.append(f"{idx}. {step_text}")
                                    elif isinstance(step, str):
                                        step_text = self.clean_text(step)
                                        steps.append(f"{idx}. {step_text}")
                            
                            if steps:
                                break
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не дал результатов, пробуем извлечь из HTML
        if not steps:
            # Ищем секцию с заголовком "Mod de preparare" или похожим
            sections = self.soup.find_all(['h2', 'h3', 'h4'])
            
            for section in sections:
                section_text = section.get_text(strip=True)
                if re.search(r'mod\s+de\s+preparare|preparare|instruc[tț]iuni', section_text, re.IGNORECASE):
                    # Ищем все <li> после заголовка до следующего заголовка
                    li_items = []
                    current = section.find_next()
                    
                    while current and current.name not in ['h2', 'h3', 'h4']:
                        if current.name == 'li':
                            li_items.append(current)
                        # Также ищем <p> с инструкциями
                        elif current.name == 'p':
                            # Только если параграф содержит достаточно текста
                            text = current.get_text(strip=True)
                            if len(text) > 50:
                                li_items.append(current)
                        current = current.find_next()
                    
                    for idx, li in enumerate(li_items, 1):
                        step_text = li.get_text(separator=' ', strip=True)
                        step_text = self.clean_text(step_text)
                        
                        if step_text and len(step_text) > 10:
                            # Если шаг уже начинается с номера, используем его
                            if re.match(r'^\d+\.', step_text):
                                steps.append(step_text)
                            else:
                                steps.append(f"{idx}. {step_text}")
                    
                    if steps:
                        break
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'recipeCategory' in data:
                        return self.clean_text(data['recipeCategory'])
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из meta тега article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    # Маппинг типов времени на ключи JSON-LD
                    time_keys = {
                        'prep': 'prepTime',
                        'cook': 'cookTime',
                        'total': 'totalTime'
                    }
                    
                    key = time_keys.get(time_type)
                    if key and key in data:
                        iso_time = data[key]
                        return self.parse_iso_duration(iso_time)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('total')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # На kfetele.ro заметки могут быть в теле статьи, после инструкций
        # Ищем параграфы после секции с инструкциями
        
        # Пробуем найти специальные секции с примечаниями
        notes_patterns = [
            re.compile(r'notă', re.I),
            re.compile(r'sfat', re.I),
            re.compile(r'observație', re.I)
        ]
        
        for pattern in notes_patterns:
            notes_section = self.soup.find(class_=pattern)
            if notes_section:
                text = self.clean_text(notes_section.get_text())
                return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из meta-тега keywords или JSON-LD"""
        tags_list = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'keywords' in data:
                        keywords = data['keywords']
                        if isinstance(keywords, str):
                            tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                        elif isinstance(keywords, list):
                            tags_list = [str(tag).strip() for tag in keywords if tag]
                        
                        if tags_list:
                            break
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        if not tags_list:
            # Пробуем извлечь из meta keywords
            meta_keywords = self.soup.find('meta', {'name': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                keywords_string = meta_keywords['content']
                tags_list = [tag.strip() for tag in keywords_string.split(',') if tag.strip()]
        
        # Возвращаем как строку через запятую
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в JSON-LD
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
                            for item in img:
                                if isinstance(item, str):
                                    urls.append(item)
                                elif isinstance(item, dict):
                                    if 'url' in item:
                                        urls.append(item['url'])
                                    elif 'contentUrl' in item:
                                        urls.append(item['contentUrl'])
                        elif isinstance(img, dict):
                            if 'url' in img:
                                urls.append(img['url'])
                            elif 'contentUrl' in img:
                                urls.append(img['contentUrl'])
                    
                    if urls:
                        break
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 2. Если не нашли в JSON-LD, ищем в мета-тегах
        if not urls:
            # og:image - обычно главное изображение
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
            
            # twitter:image
            twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
            if twitter_image and twitter_image.get('content'):
                urls.append(twitter_image['content'])
        
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/kfetele_ro
    recipes_dir = os.path.join("preprocessed", "kfetele_ro")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(KfeteleRoExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python kfetele_ro.py")


if __name__ == "__main__":
    main()
