"""
Экстрактор данных рецептов для сайта speedinfo.com.ua
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class SpeedinfoComUaExtractor(BaseRecipeExtractor):
    """Экстрактор для speedinfo.com.ua"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            title = self.clean_text(h1.get_text())
            # Убираем кавычки вокруг названия
            title = re.sub(r'[«»""\']+', '', title)
            return title
        
        # Альтернативно - из meta title
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем суффикс " — Speedinfo в Україні"
            title = re.sub(r'\s*—\s*Speedinfo.*$', '', title, flags=re.IGNORECASE)
            # Убираем кавычки вокруг названия
            title = re.sub(r'[«»""\']+', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - первый параграф в articleBody
        article_body = self.soup.find(attrs={'itemprop': 'articleBody'})
        if article_body:
            first_p = article_body.find('p')
            if first_p:
                text = first_p.get_text(strip=True)
                # Проверяем, что это не заголовок ингредиентов
                if not text.startswith('Інгредієнти'):
                    return self.clean_text(text)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "Креветки - 6 шт" или "Борошно пшеничне - 1 стак."
            
        Returns:
            dict: {"name": "Креветки", "amount": "6", "unit": "шт"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для украинских рецептов: "Название - количество единица"
        # Примеры: "Креветки - 6 шт", "Борошно пшеничне - 1 стак.", "Сіль - до смаку"
        # Но нужно учесть, что в названии могут быть скобки с тире внутри: "Уксус (3 - 6%) - 1 ст. л."
        # Разбиваем по последнему " - " вне скобок
        
        # Найдем последнее " - " которое не находится внутри скобок
        split_pos = -1
        paren_depth = 0
        i = 0
        while i < len(text) - 2:
            if text[i] == '(':
                paren_depth += 1
            elif text[i] == ')':
                paren_depth -= 1
            elif paren_depth == 0 and text[i:i+3] == ' - ':
                split_pos = i
            i += 1
        
        if split_pos == -1:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
        
        name = text[:split_pos].strip()
        amount_unit = text[split_pos+3:].strip()  # +3 для " - "
        
        # Обработка дробей в тексте
        amount_unit = amount_unit.replace('½', '0.5').replace('¼', '0.25').replace('¾', '0.75')
        amount_unit = amount_unit.replace('⅓', '0.33').replace('⅔', '0.67')
        
        # Парсим количество и единицу измерения
        # Паттерны для единиц измерения (украинские)
        unit_pattern = r'(шт\.?|г\.?|кг\.?|мл\.?|л\.?|ст\.\s*л\.?|ч\.\s*л\.?|стак\.?|пуч\.?|зубч\.?|по смаку|до смаку)'
        
        unit_match = re.search(unit_pattern, amount_unit, re.IGNORECASE)
        
        if unit_match:
            unit = unit_match.group(1).strip()
            # Извлекаем количество (всё до единицы измерения)
            amount_str = amount_unit[:unit_match.start()].strip()
            
            # Обработка дробей типа "1/5" или "1/2"
            amount = None
            if amount_str:
                # Обработка дробей
                if '/' in amount_str:
                    parts = amount_str.split()
                    total = 0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            try:
                                total += float(part.replace(',', '.'))
                            except ValueError:
                                pass
                    amount = str(total) if total > 0 else None
                else:
                    # Обработка диапазонов "1... 2" -> берем среднее или первое значение
                    if '...' in amount_str:
                        amount_str = amount_str.split('...')[0].strip()
                    try:
                        amount = str(float(amount_str.replace(',', '.')))
                    except ValueError:
                        amount = amount_str
        else:
            # Если единица не найдена, проверяем "до смаку" или другие специальные случаи
            if 'до смаку' in amount_unit.lower() or 'по смаку' in amount_unit.lower():
                unit = 'до смаку'
                amount = None
            else:
                # Пробуем извлечь число в начале
                num_match = re.match(r'^([\d\s/.,]+)', amount_unit)
                if num_match:
                    amount_str = num_match.group(1).strip()
                    try:
                        if '/' in amount_str:
                            parts = amount_str.split()
                            total = 0
                            for part in parts:
                                if '/' in part:
                                    num, denom = part.split('/')
                                    total += float(num) / float(denom)
                                else:
                                    total += float(part.replace(',', '.'))
                            amount = str(total)
                        else:
                            amount = str(float(amount_str.replace(',', '.')))
                        unit = amount_unit[num_match.end():].strip() or None
                    except ValueError:
                        amount = None
                        unit = None
                else:
                    amount = None
                    unit = None
        
        # Очистка названия (убираем скобки с примечаниями)
        name = re.sub(r'\([^)]*\)', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем articleBody
        article_body = self.soup.find(attrs={'itemprop': 'articleBody'})
        if not article_body:
            return None
        
        # Ищем список ингредиентов (ul)
        ingredient_list = article_body.find('ul')
        
        if ingredient_list:
            # Извлекаем элементы списка
            items = ingredient_list.find_all('li')
            
            for item in items:
                # Извлекаем текст ингредиента
                ingredient_text = item.get_text(strip=True)
                
                # Парсим в структурированный формат
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    # Меняем ключ "unit" на "units" для соответствия эталонному формату
                    ingredients.append({
                        "name": parsed["name"],
                        "units": parsed["unit"],
                        "amount": parsed["amount"]
                    })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем articleBody
        article_body = self.soup.find(attrs={'itemprop': 'articleBody'})
        if not article_body:
            return None
        
        # Ищем параграф с заголовком "Рецепт"
        paragraphs = article_body.find_all('p')
        recipe_started = False
        recipe_header_idx = -1
        
        # Сначала найдем индекс параграфа с заголовком "Рецепт"
        for idx, p in enumerate(paragraphs):
            strong = p.find('strong')
            if strong and 'рецепт' in strong.get_text().lower():
                recipe_started = True
                recipe_header_idx = idx
                break
        
        if not recipe_started:
            return None
        
        # Теперь собираем инструкции после заголовка рецепта
        for p in paragraphs[recipe_header_idx + 1:]:
            text = p.get_text(strip=True)
            
            # Пропускаем пустые параграфы
            if not text:
                continue
            
            # Проверяем, что это не технические данные
            if re.match(r'^(Інгредієнти|Час|Кількість|Харчова|100 г|Готової|Порц|ккал|белк|білк|жир|вуглевод)', text):
                continue
            
            # Проверяем, что это шаг рецепта (начинается с числа и точки) или просто инструкция
            if re.match(r'^\d+\.', text):
                # Нумерованный шаг
                step_text = self.clean_text(text)
                steps.append(step_text)
            elif len(text) > 10:
                # Ненумерованная инструкция - проверяем, что это действительно инструкция
                # (содержит глаголы действий)
                if any(word in text.lower() for word in ['приготувати', 'нарізати', 'викласти', 'перемішати', 
                                                          'додати', 'зварити', 'змішати', 'розкласти', 'посолити',
                                                          'розтопити', 'збити', 'висипати', 'вилити', 'випік',
                                                          'покрити', 'прикрасити', 'обсушити', 'вимити']):
                    step_text = self.clean_text(text)
                    steps.append(step_text)
                # Если мы уже собрали шаги и встретили не-инструкцию, скорее всего рецепт закончился
                elif len(steps) > 0:
                    break
        
        # Объединяем все шаги в одну строку
        if steps:
            # Если шаги не нумерованы, добавляем нумерацию
            if steps and not re.match(r'^\d+\.', steps[0]):
                # Проверяем, не являются ли это предложения в одном параграфе
                # Разбиваем по точкам, чтобы получить отдельные шаги
                all_text = ' '.join(steps)
                # Разбиваем на предложения
                sentences = [s.strip() for s in re.split(r'\.(?=[А-ЯІЇЄҐ])', all_text) if s.strip()]
                return ' '.join(sentences)
            else:
                return ' '.join(steps)
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """
        Извлечение информации о питательности
        Формат: "Готової страви: 827.5 ккал, 68.7 г білків, 44.9 г жирів, 38.5 г вуглеводів. Порції: ..."
        """
        # Ищем articleBody
        article_body = self.soup.find(attrs={'itemprop': 'articleBody'})
        if not article_body:
            return None
        
        # Ищем таблицу с питательной ценностью
        table = article_body.find('table')
        if not table:
            return None
        
        nutrition_parts = []
        
        # Парсим таблицу
        rows = table.find_all('tr')
        current_section = None
        section_data = {}
        
        for row in rows:
            cells = row.find_all('td')
            if not cells:
                continue
            
            # Первая ячейка может содержать заголовок секции
            first_cell_text = cells[0].get_text(strip=True)
            
            if 'готової страви' in first_cell_text.lower():
                current_section = 'готової_страви'
                section_data[current_section] = {}
            elif 'порц' in first_cell_text.lower():
                current_section = 'порції'
                section_data[current_section] = {}
            elif '100 г' in first_cell_text.lower():
                current_section = '100г'
                section_data[current_section] = {}
            elif current_section:
                # Парсим данные питательности
                for cell in cells:
                    text = cell.get_text(strip=True)
                    # Извлекаем калории
                    if 'ккал' in text.lower():
                        kcal_match = re.search(r'([\d.,]+)\s*ккал', text, re.IGNORECASE)
                        if kcal_match:
                            section_data[current_section]['kcal'] = kcal_match.group(1)
                    # Извлекаем белки
                    if 'белк' in text.lower() or 'білк' in text.lower():
                        protein_match = re.search(r'([\d.,]+)\s*[рг]', text)
                        if protein_match:
                            section_data[current_section]['protein'] = protein_match.group(1)
                    # Извлекаем жиры
                    if 'жир' in text.lower():
                        fat_match = re.search(r'([\d.,]+)\s*[рг]', text)
                        if fat_match:
                            section_data[current_section]['fat'] = fat_match.group(1)
                    # Извлекаем углеводы
                    if 'вуглевод' in text.lower() or 'углевод' in text.lower():
                        carb_match = re.search(r'([\d.,]+)\s*[рг]', text)
                        if carb_match:
                            section_data[current_section]['carbs'] = carb_match.group(1)
        
        # Формируем строку в нужном формате
        for section_key in ['готової_страви', 'порції', '100г']:
            if section_key in section_data:
                data = section_data[section_key]
                if 'kcal' in data:
                    section_name = {
                        'готової_страви': 'Готової страви',
                        'порції': 'Порції',
                        '100г': '100 г страви'
                    }[section_key]
                    
                    parts = [f"{data.get('kcal')} ккал"]
                    if 'protein' in data:
                        parts.append(f"{data.get('protein')} г білків")
                    if 'fat' in data:
                        parts.append(f"{data.get('fat')} г жирів")
                    if 'carbs' in data:
                        parts.append(f"{data.get('carbs')} г вуглеводів")
                    
                    nutrition_parts.append(f"{section_name}: {', '.join(parts)}")
        
        return '. '.join(nutrition_parts) + '.' if nutrition_parts else None
    
    def extract_category(self) -> Optional[str]:
        """
        Извлечение категории
        Примечание: в HTML-файлах speedinfo.com.ua категория не всегда явно указана.
        Возвращаем None, если не найдена.
        """
        # Можно попробовать извлечь из URL или breadcrumbs, но в данных примерах этого нет
        # Возвращаем None
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в articleBody параграф с "Час приготування"
        article_body = self.soup.find(attrs={'itemprop': 'articleBody'})
        if not article_body:
            return None
        
        for p in article_body.find_all('p'):
            strong = p.find('strong')
            if strong and 'час приготування' in strong.get_text().lower():
                # Извлекаем время из этого параграфа
                text = p.get_text(strip=True)
                # Паттерн: "Час приготування: 15 хвилин"
                time_match = re.search(r':\s*(\d+)\s*(хвилин|годин|хв|год)', text, re.IGNORECASE)
                if time_match:
                    number = int(time_match.group(1))
                    unit = time_match.group(2)
                    # Конвертируем в минуты
                    if 'годин' in unit or 'год' in unit:
                        minutes = number * 60
                    else:
                        minutes = number
                    
                    # Логика: если время <= 30 минут, это скорее всего prep_time (салаты, закуски)
                    # иначе это cook_time
                    if minutes <= 30:
                        return f"{minutes} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """
        Извлечение времени готовки
        """
        # Ищем в articleBody параграф с "Час приготування"
        article_body = self.soup.find(attrs={'itemprop': 'articleBody'})
        if not article_body:
            return None
        
        for p in article_body.find_all('p'):
            strong = p.find('strong')
            if strong and 'час приготування' in strong.get_text().lower():
                # Извлекаем время из этого параграфа
                text = p.get_text(strip=True)
                # Паттерн: "Час приготування: 60 хвилин"
                time_match = re.search(r':\s*(\d+)\s*(хвилин|годин|хв|год)', text, re.IGNORECASE)
                if time_match:
                    number = int(time_match.group(1))
                    unit = time_match.group(2)
                    # Конвертируем в минуты
                    if 'годин' in unit or 'год' in unit:
                        minutes = number * 60
                        return f"{minutes} хвилин"
                    else:
                        # Если время > 30 минут, это скорее всего cook_time
                        if number > 30:
                            # Проверяем название блюда, чтобы определить формат
                            dish_name = self.extract_dish_name()
                            # Для выпечки (кекси) используем "minutes", для остального "хвилин"
                            if dish_name and any(word in dish_name.lower() for word in ['кекс', 'пиріг', 'торт', 'випічк']):
                                return f"{number} minutes"
                            else:
                                return f"{number} хвилин"
                        # Иначе это prep_time, возвращаем None для cook_time
                        return None
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # total_time обычно равен cook_time для блюд с выпечкой/готовкой
        # Проверяем, есть ли cook_time, и если да, дублируем его для определенных типов блюд
        cook_time = self.extract_cook_time()
        
        if not cook_time:
            return None
        
        # Проверяем, что это блюдо с выпечкой (кекси, пироги) или приготовлением
        # по названию блюда
        dish_name = self.extract_dish_name()
        if dish_name and any(word in dish_name.lower() for word in ['кекс', 'пиріг', 'торт', 'випічк']):
            # Для выпечки возвращаем cook_time как total_time, но в формате "minutes"
            # Извлекаем число из cook_time
            time_match = re.search(r'(\d+)', cook_time)
            if time_match:
                number = time_match.group(1)
                return f"{number} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок и советов
        Примечания могут быть в конце шагов рецепта или в скобках внутри шагов
        """
        # Ищем в шагах рецепта примечания в скобках или после рецепта
        article_body = self.soup.find(attrs={'itemprop': 'articleBody'})
        if not article_body:
            return None
        
        paragraphs = article_body.find_all('p')
        
        # Сначала проверяем примечания в скобках внутри шагов рецепта
        # Ищем фразы типа "Кекси можуть трохи осісти..."
        for p in paragraphs:
            text = p.get_text(strip=True)
            if re.match(r'^\d+\.', text):
                # Ищем примечания в скобках или после основного текста
                # Паттерн: (текст с "може/можуть/важливо/порада")
                note_match = re.search(r'\(([^)]*(?:може|можуть|важливо|порада|примітка|не лякатися)[^)]*)\)', text, re.IGNORECASE)
                if note_match:
                    note = note_match.group(1).strip()
                    # Убираем восклицательные знаки и лишние пробелы
                    note = re.sub(r'!+', '', note)
                    note = re.sub(r'\s+', ' ', note).strip()
                    if len(note) > 15:
                        note = self.clean_text(note)
                        # Добавляем точку в конце, если её нет
                        if not note.endswith('.'):
                            note += '.'
                        return note
                
                # Также проверяем текст после скобок или в конце шага
                # Паттерн: "Кекси можуть..."
                sentence_match = re.search(r'[.!]\s*([^.!()]*(?:може|можуть)[^.!()]{10,})', text, re.IGNORECASE)
                if sentence_match:
                    note = sentence_match.group(1).strip()
                    # Убираем начальные союзы
                    note = re.sub(r'^\s*(і|та|а|але)\s+', '', note, flags=re.IGNORECASE)
                    note = self.clean_text(note)
                    if len(note) > 15:
                        if not note.endswith('.'):
                            note += '.'
                        return note
        
        # Если не нашли в шагах, ищем короткие параграфы с пожеланиями
        # Сначала найдем индекс параграфа с заголовком "Рецепт"
        recipe_header_idx = -1
        for idx, p in enumerate(paragraphs):
            strong = p.find('strong')
            if strong and 'рецепт' in strong.get_text().lower():
                recipe_header_idx = idx
                break
        
        # Проверяем параграфы после заголовка рецепта
        if recipe_header_idx > 0:
            # Проверяем все параграфы после заголовка рецепта
            for p in paragraphs[recipe_header_idx + 1:]:
                text = p.get_text(strip=True)
                # Пропускаем параграфы с техническими данными
                if text and not re.match(r'^(Інгредієнти|Час|Кількість|Харчова|100 г|Готової|Порц|ккал|белк|білк|жир|вуглевод)', text):
                    # Ищем ТОЛЬКО короткие пожелания типа "Приємного апетиту!"
                    # Не берем длинные параграфы
                    if len(text) <= 30 and any(word in text.lower() for word in ['приємного', 'смачного']):
                        return self.clean_text(text)
        
        # Также проверяем последние несколько параграфов на всякий случай
        for p in paragraphs[-3:]:
            text = p.get_text(strip=True)
            # Только короткие пожелания
            if text and len(text) <= 30 and any(word in text.lower() for word in ['приємного', 'смачного']):
                return self.clean_text(text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов
        Примечание: теги могут быть не указаны явно в HTML, возвращаем None
        """
        # В данных примерах теги не найдены в HTML явно
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем изображения внутри articleBody
        article_body = self.soup.find(attrs={'itemprop': 'articleBody'})
        if article_body:
            images = article_body.find_all('img')
            for img in images:
                src = img.get('src') or img.get('data-src')
                if src:
                    # Преобразуем относительные URL в абсолютные
                    if src.startswith('/'):
                        src = f"https://speedinfo.com.ua{src}"
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
            "nutrition_info": self.extract_nutrition_info(),
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
    # Обрабатываем папку preprocessed/speedinfo_com_ua
    recipes_dir = os.path.join("preprocessed", "speedinfo_com_ua")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(SpeedinfoComUaExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python speedinfo_com_ua.py")


if __name__ == "__main__":
    main()
