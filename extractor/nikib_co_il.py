"""
Экстрактор данных рецептов для сайта nikib.co.il
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class NikibExtractor(BaseRecipeExtractor):
    """Экстрактор для nikib.co.il"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[list]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем div с id="ingredients"
        ingredients_div = self.soup.find('div', id='ingredients')
        if not ingredients_div:
            return None
        
        # Извлекаем параграфы с ингредиентами
        # Вариант 1: параграфы с data-start атрибутом
        p_tags = ingredients_div.find_all('p', attrs={'data-start': True})
        
        # Вариант 2: обычные параграфы (если нет data-start)
        if not p_tags:
            p_tags = ingredients_div.find_all('p')
        
        if not p_tags:
            return None
        
        # Берем параграф с ингредиентами
        # Ингредиенты разделены тегами <br>
        for p_tag in p_tags:
            # Проверяем, есть ли ингредиенты в этом параграфе
            # Пропускаем параграфы с заголовками
            text_preview = p_tag.get_text()[:50]
            if 'מרכיבים' in text_preview or '✿' in text_preview:
                continue
            
            # Разделяем по <br> тегам
            # Используем str.split на HTML строке
            html_str = str(p_tag)
            # Разделяем по <br> и <br/> тегам (с любыми атрибутами или без)
            parts_html = re.split(r'<br\s*[^>]*/?>', html_str)
            
            for part_html in parts_html:
                # Парсим каждую часть как HTML чтобы извлечь текст
                part_soup = BeautifulSoup(part_html, 'lxml')
                # Получаем чистый текст (объединяя текст из всех тегов)
                line = part_soup.get_text()
                line = self.clean_text(line)
                
                # Пропускаем пустые строки и теги (<p>, </p>)
                if not line or len(line) < 2 or line.startswith('<'):
                    continue
                
                # Парсим ингредиент
                parsed = self.parse_ingredient(line)
                if parsed:
                    ingredients.append(parsed)
            
            # Если нашли ингредиенты в этом параграфе, прекращаем поиск
            if ingredients:
                break
        
        return ingredients if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка с ингредиентом (на иврите)
            
        Returns:
            dict: {"name": "...", "amount": "...", "unit": "..."} или None
        """
        if not ingredient_text:
            return None
        
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на десятичные числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Обработка обычных дробей типа "1/4"
        # Заменяем на десятичные
        fraction_pattern = r'(\d+)/(\d+)'
        def replace_fraction(match):
            num = float(match.group(1))
            denom = float(match.group(2))
            return str(num / denom)
        
        text = re.sub(fraction_pattern, replace_fraction, text)
        
        # Паттерн для извлечения количества в начале строки
        # Примеры: "2 כוסות מים", "כוס אורז", "½ כפית מלח"
        
        # Словарь единиц измерения (иврит) - сортируем по длине (длинные первыми)
        units_map = {
            'כפיות שטוחות': 'teaspoons',  # level teaspoons
            'כפות גדושות': 'heaped tablespoons',  # heaped tablespoons
            'כוסות': 'cups',
            'כפיות': 'teaspoons',
            'כפות': 'tablespoons',
            'חבילות': 'packages',
            'יחידות': 'units',
            'כוס': 'cup',
            'כפית': 'teaspoon',
            'כף': 'tablespoon',
            'גרם': 'g',
            'ק"ג': 'kg',
            'קילו': 'kg',
            'ליטר': 'l',
            'מ"ל': 'ml',
            'יחידה': 'unit',
            'חבילה': 'package',
            'פחית': 'can',
        }
        
        # Сортируем по длине (длинные первыми) для корректного матчинга
        sorted_units = sorted(units_map.keys(), key=len, reverse=True)
        
        # Попытка извлечь количество и единицу измерения
        # Паттерн: [число] [единица] [название]
        pattern = r'^([\d.,½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘]+)?\s*(' + '|'.join(re.escape(u) for u in sorted_units) + r')?\s*(.+)$'
        
        match = re.match(pattern, text)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
        
        amount_str, unit_he, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip().replace(',', '.')
            try:
                amount = float(amount_str)
            except ValueError:
                amount = None
        elif unit_he:
            # Если есть единица измерения, но нет количества, подразумевается 1
            amount = 1.0
        
        # Обработка единицы измерения
        unit = None
        if unit_he:
            unit = units_map.get(unit_he.strip())
        
        # Очистка названия
        name = name.strip() if name else text
        
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        name = self.clean_text(name)
        
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
        
        # Вариант 1: Ищем параграфы с нумерованными шагами с data-start
        all_p = self.soup.find_all('p', attrs={'data-start': True})
        
        for p in all_p:
            text = self.clean_text(p.get_text())
            # Проверяем, начинается ли текст с номера
            if re.match(r'^\d+\.', text):
                steps.append(text)
        
        # Вариант 2: Если не нашли с data-start, ищем обычные p в recipe div
        if not steps:
            recipe_div = self.soup.find('div', id='recipe')
            if recipe_div:
                all_p = recipe_div.find_all('p')
                
                for p in all_p:
                    text = self.clean_text(p.get_text())
                    # Проверяем, начинается ли текст с номера
                    if re.match(r'^\d+\.', text):
                        steps.append(text)
        
        # Сортируем шаги по номеру
        def get_step_number(step_text):
            match = re.match(r'^(\d+)\.', step_text)
            return int(match.group(1)) if match else 0
        
        steps.sort(key=get_step_number)
        
        # Объединяем шаги в одну строку
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем ссылки на категории в контенте
        # Категории обычно содержат 'tosafot', 'category' в URL
        category_keywords = ['tosafot', 'vegetarian', 'rice', 'vegan-recipes']
        
        all_links = self.soup.find_all('a', href=True)
        categories = []
        
        for a in all_links:
            href = a.get('href', '')
            text = self.clean_text(a.get_text())
            
            # Проверяем, содержит ли ссылка категорию
            if any(keyword in href for keyword in category_keywords):
                # Фильтруем по длине текста (не слишком длинный)
                if text and 3 < len(text) < 50:
                    # Проверяем, что это не навигационная ссылка
                    if 'בית' not in text and 'home' not in text.lower():
                        categories.append(text)
        
        # Возвращаем самую специфичную категорию (обычно последняя в списке)
        if categories:
            # Удаляем дубликаты
            unique_cats = []
            seen = set()
            for cat in categories:
                if cat not in seen:
                    seen.add(cat)
                    unique_cats.append(cat)
            
            # Приоритизируем специфичные категории
            for cat in unique_cats:
                if 'תוספות' in cat or 'לארוחה' in cat:
                    return cat
                if 'vegetarian' in cat or 'צמחוני' in cat:
                    return cat
                if 'rice' in cat or 'אורז' in cat:
                    return cat
            
            # Если не нашли специфичную, возвращаем первую
            return unique_cats[0] if unique_cats else None
        
        # Альтернативно - из мета-данных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # nikib.co.il не всегда имеет явное разделение на prep/cook time
        # Ищем маленькие времена в начале инструкций (обычно prep)
        
        instructions_text = ""
        
        # Вариант 1: с data-start
        all_p = self.soup.find_all('p', attrs={'data-start': True})
        
        # Вариант 2: обычные p в recipe div
        if not all_p:
            recipe_div = self.soup.find('div', id='recipe')
            if recipe_div:
                all_p = recipe_div.find_all('p')
        
        # Берем только первые несколько шагов
        step_count = 0
        for p in all_p:
            text = p.get_text()
            if re.match(r'^[12]\.', text):  # Первые 2 шага
                instructions_text += " " + text
                step_count += 1
                if step_count >= 2:
                    break
        
        # Ищем маленькие времена (до 15 минут - обычно prep)
        pattern = r'(\d+)\s*דקות'
        matches = re.findall(pattern, instructions_text)
        
        for match in matches:
            try:
                minutes = int(match)
                if minutes <= 15:  # Маленькое время - вероятно prep
                    return f"{minutes} minutes"
            except ValueError:
                continue
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем паттерны времени в тексте инструкций
        # Примеры: "30 דקות", "כ-30 דקות", "45 minutes"
        
        # Ищем в инструкциях упоминания времени
        instructions_text = ""
        
        # Вариант 1: с data-start
        all_p = self.soup.find_all('p', attrs={'data-start': True})
        
        # Вариант 2: обычные p в recipe div
        if not all_p:
            recipe_div = self.soup.find('div', id='recipe')
            if recipe_div:
                all_p = recipe_div.find_all('p')
        
        for p in all_p:
            text = p.get_text()
            if re.match(r'^\d+\.', text):  # Это шаг инструкции
                instructions_text += " " + text
        
        # Паттерны для времени (иврит) - порядок важен!
        time_patterns = [
            (r'רבע\s*שעה', 15),  # четверть часа
            (r'חצי\s*שעה', 30),  # полчаса
            (r'(\d+)\s*שעות', 60),  # X часов (конвертируем в минуты)
            (r'כ[־-]?(\d+)\s*דקות', 1),  # около X минут
            (r'(\d+)\s*דקות', 1),  # X минут
        ]
        
        max_time = 0
        for pattern, multiplier in time_patterns:
            matches = re.findall(pattern, instructions_text)
            for match in matches:
                try:
                    if isinstance(match, tuple):
                        match = match[0] if match[0] else match
                    
                    if isinstance(match, str) and match.isdigit():
                        minutes = int(match) * multiplier
                    else:
                        minutes = multiplier  # Для паттернов без числа
                    
                    # Берем максимальное время (обычно это время приготовления)
                    # но игнорируем очень маленькие времена (< 10 минут - обычно prep)
                    if minutes >= 10 and minutes > max_time:
                        max_time = minutes
                except (ValueError, TypeError, IndexError):
                    continue
        
        if max_time > 0:
            return f"{max_time} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Если есть prep_time и cook_time, суммируем их
        # Иначе ищем в инструкциях
        
        # Попробуем найти все упоминания времени и взять сумму
        instructions_text = ""
        
        # Вариант 1: с data-start
        all_p = self.soup.find_all('p', attrs={'data-start': True})
        
        # Вариант 2: обычные p в recipe div
        if not all_p:
            recipe_div = self.soup.find('div', id='recipe')
            if recipe_div:
                all_p = recipe_div.find_all('p')
        
        for p in all_p:
            text = p.get_text()
            if re.match(r'^\d+\.', text):  # Это шаг инструкции
                instructions_text += " " + text
        
        # Паттерны для времени
        time_patterns = [
            (r'כ[־-]?(\d+)\s*דקות', 1),
            (r'(\d+)\s*דקות', 1),
            (r'(\d+)\s*שעות', 60),
            (r'רבע\s*שעה', 15),  # четверть часа
        ]
        
        total_minutes = 0
        found_times = []
        
        for pattern, multiplier in time_patterns:
            matches = re.findall(pattern, instructions_text)
            for match in matches:
                try:
                    if isinstance(match, str) and match.isdigit():
                        minutes = int(match) * multiplier
                    else:
                        minutes = multiplier
                    
                    found_times.append(minutes)
                except (ValueError, TypeError):
                    continue
        
        # Если нашли несколько упоминаний времени, берем сумму уникальных
        # (но не дублируем одинаковые значения)
        if found_times:
            # Берем максимальное + небольшие времена (например, prep)
            found_times.sort(reverse=True)
            if len(found_times) >= 2:
                # Суммируем самое большое и остальные маленькие
                total_minutes = found_times[0]
                for time in found_times[1:]:
                    if time < 20:  # Маленькое время - скорее всего prep
                        total_minutes += time
                        break
            else:
                total_minutes = found_times[0]
        
        if total_minutes > 0:
            return f"{total_minutes} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем секцию с советами/заметками
        # Обычно под заголовком "טיפים" (советы)
        strong_tips = self.soup.find('strong', string=re.compile(r'טיפ', re.I))
        
        if strong_tips:
            # Находим родительский элемент
            parent = strong_tips.find_parent()
            if parent:
                # Ищем следующий UL с советами
                ul = parent.find_next_sibling('ul')
                if ul:
                    li_items = ul.find_all('li')
                    for li in li_items:
                        tip_text = self.clean_text(li.get_text())
                        if tip_text:
                            notes.append(tip_text)
        
        # Альтернативный вариант: ищем в recipe div параграфы с советами
        if not notes:
            recipe_div = self.soup.find('div', id='recipe')
            if recipe_div:
                # Ищем параграфы после инструкций, которые начинаются с определенных слов
                all_p = recipe_div.find_all('p')
                for p in all_p:
                    text = self.clean_text(p.get_text())
                    # Советы часто начинаются с "כדאי", "אפשר", "מומלץ"
                    if text and any(keyword in text[:20] for keyword in ['כדאי', 'אפשר', 'מומלץ', 'ניתן']):
                        # Проверяем, что это не инструкция
                        if not re.match(r'^\d+\.', text):
                            notes.append(text)
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Ищем div с классом post-tags
        post_tags = self.soup.find('div', class_='post-tags')
        if post_tags:
            # Извлекаем теги из ссылок
            tag_links = post_tags.find_all('a')
            for link in tag_links:
                tag_text = self.clean_text(link.get_text())
                if tag_text:
                    tags_list.append(tag_text)
        
        # Альтернативно - из мета-тегов
        if not tags_list:
            meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                keywords = meta_keywords['content']
                tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем изображения в контенте рецепта
        # Ищем img теги с src, содержащим nikib.co.il/uploads
        img_tags = self.soup.find_all('img', src=True)
        for img in img_tags:
            src = img.get('src', '')
            # Фильтруем только изображения рецептов
            if 'nikib.co.il/wp-content/uploads' in src:
                # Убираем query параметры для нормализации
                clean_src = re.sub(r'\?.*$', '', src)
                if clean_src not in urls:
                    urls.append(clean_src)
        
        # Ограничиваем до 3 изображений
        urls = urls[:3]
        
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
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        total_time = self.extract_total_time()
        notes = self.extract_notes()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()
        
        # Форматируем ingredients как JSON строку, если они есть
        ingredients_json = None
        if ingredients:
            ingredients_json = json.dumps(ingredients, ensure_ascii=False)
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients_json,
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
    """Точка входа для обработки HTML файлов nikib.co.il"""
    import os
    
    # Ищем директорию с примерами
    preprocessed_dir = os.path.join("preprocessed", "nikib_co_il")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка файлов из директории: {preprocessed_dir}")
        process_directory(NikibExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python nikib_co_il.py")


if __name__ == "__main__":
    main()
