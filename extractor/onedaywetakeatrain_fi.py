"""
Экстрактор данных рецептов для сайта onedaywetakeatrain.fi
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class OnedaywetakeatrainFiExtractor(BaseRecipeExtractor):
    """Экстрактор для onedaywetakeatrain.fi"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1 внутри body div
        body_div = self.soup.find('div', id='body')
        if body_div:
            h1_tags = body_div.find_all('h1')
            # Ищем непустой h1
            for h1 in h1_tags:
                name = h1.get_text(strip=True)
                if name and name != '\xa0' and name.strip():
                    return self.clean_text(name)
        
        # Альтернативно - из title тега
        title = self.soup.find('title')
        if title:
            return self.clean_text(title.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в мета-теге description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def _parse_ingredient_line(self, line: str) -> Optional[dict]:
        """
        Парсинг строки с ингредиентом в структурированный формат
        
        Args:
            line: Строка вида "2 viipaleina pakastettua, kypsää banaania" или "250 g rasvatonta maitorahkaa"
            
        Returns:
            dict: {"name": "...", "amount": "...", "units": "..."} или None
        """
        if not line or len(line.strip()) < 3:
            return None
        
        # Убираем скобки из строки (они часто указывают на опциональные ингредиенты)
        # но сохраняем содержимое
        line_clean = re.sub(r'[()]', '', line)
        line_clean = self.clean_text(line_clean).strip()
        
        # Пропускаем строки, которые похожи на заголовки или примечания
        if any(x in line_clean.lower() for x in ['ainekset', 'valmistus', 'resepti', 'ohje', 'lisäksi']):
            return None
        
        # Заменяем дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            line_clean = line_clean.replace(fraction, decimal)
        
        # Паттерн для парсинга финских ингредиентов
        # Поддерживаем:
        # - "2 viipaleina pakastettua" (число + специальная единица)
        # - "250 g rasvatonta" (число + стандартная единица)
        # - "1 kukkurallinen rkl maapähkinävoita" (число + модификатор + единица)
        # - "kourallinen tuoretta" (специальная единица без числа)
        # - "4 mustapippuria" (число без единицы - штучный товар)
        # - "½ vaniljatanko" (дробь без единицы)
        
        # Сначала попробуем паттерн с модификатором (kukkurallinen, pieni, suuri и т.д.)
        pattern_with_modifier = r'^([0-9.,\-]+)\s+(kukkurallinen|pieni|suuri|iso|vähän|paljon)\s*(dl|g|kg|l|ml|rkl|tl|kpl)\s+(.+)$'
        match = re.match(pattern_with_modifier, line_clean, re.IGNORECASE)
        
        if match:
            amount_str, modifier, unit, name = match.groups()
            
            # Обработка количества
            amount = amount_str.strip().replace(',', '.')
            
            # Обработка единицы (включаем модификатор в количество или игнорируем)
            unit = unit.strip() if unit else None
            
            # Очистка названия
            name = name.strip()
            name = re.sub(r'\b(tai maun mukaan|maun mukaan|tai tarpeen mukaan)\b', '', name, flags=re.IGNORECASE)
            name = name.strip()
            
            if not name or len(name) < 2:
                return None
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        
        # Паттерн: количество + единица измерения + название
        pattern = r'^([0-9.,\-]+)\s*(dl|g|kg|l|ml|rkl|tl|kpl|viipaleina)?\s+(.+)$'
        
        match = re.match(pattern, line_clean, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount = amount_str.strip().replace(',', '.')
            
            # Обработка единицы измерения
            unit = unit.strip() if unit else None
            
            # Очистка названия
            name = name.strip()
            # Убираем скобки и содержимое
            name = re.sub(r'\([^)]*\)', '', name)
            name = re.sub(r'\b(tai maun mukaan|maun mukaan|tai tarpeen mukaan)\b', '', name, flags=re.IGNORECASE)
            name = name.strip()
            
            if not name or len(name) < 2:
                return None
            
            # Если единицы нет, но есть число - это штучный товар, используем "kpl" как единицу
            if not unit and amount:
                unit = "kpl"
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        else:
            # Если паттерн не совпал, попробуем без количества
            # Например: "kourallinen tuoretta nokkosta", "hieman raastettua pähkinää"
            pattern_no_amount = r'^(kourallinen|hyppysellinen|ripaus|tilkka|hieman|vähän)\s+(.+)$'
            match_no_amount = re.match(pattern_no_amount, line_clean, re.IGNORECASE)
            
            if match_no_amount:
                unit, name = match_no_amount.groups()
                name = name.strip()
                name = re.sub(r'\b(tai maun mukaan|maun mukaan)\b', '', name, flags=re.IGNORECASE)
                name = name.strip()
                
                return {
                    "name": name,
                    "amount": unit,  # "kourallinen", "hieman" etc as amount
                    "units": None
                }
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        all_ingredients = []
        
        # Ищем главную секцию с контентом
        body_div = self.soup.find('div', id='body')
        if not body_div:
            return None
        
        # Получаем все параграфы
        paragraphs = body_div.find_all('p')
        
        # Ингредиенты обычно находятся в параграфах, которые содержат много <br> тегов
        # и имеют паттерны типа "число + единица измерения"
        # Собираем ингредиенты из ВСЕХ подходящих параграфов (может быть несколько секций)
        for p in paragraphs:
            # Получаем текст с сохранением переносов строк
            html_content = str(p)
            
            # Разбиваем по <br> тегам
            lines = []
            if '<br>' in html_content or '<br/>' in html_content:
                # Получаем текст и разбиваем по переносам
                text_parts = p.get_text(separator='|||BR|||').split('|||BR|||')
                lines = [line.strip() for line in text_parts if line.strip()]
            
            # Проверяем, есть ли в этих строках паттерны ингредиентов
            ingredient_count = 0
            temp_ingredients = []
            
            for line in lines:
                # Убираем скобки для проверки длины и паттернов
                line_no_parens = re.sub(r'\([^)]*\)', '', line)
                line_no_parens = line_no_parens.strip()
                
                # Пропускаем строки, которые явно являются заголовками или заметками
                # Увеличен лимит до 150 для строк с описаниями в скобках
                if len(line_no_parens) > 150:  # Слишком длинная для ингредиента
                    continue
                
                # Пропускаем строки, которые начинаются с заглавной буквы и содержат глаголы
                # (это инструкции)
                if re.match(r'^[A-ZÄÖÅ]', line_no_parens) and any(verb in line_no_parens.lower() for verb in ['laita', 'sekoita', 'lisää', 'kaada', 'anna', 'valmista', 'mittaa', 'perkaa', 'viillä']):
                    continue
                
                # Проверяем наличие паттерна количества с учетом различных вариантов
                # 1. Стандартные единицы измерения
                # 2. Специальные слова как "viipaleina", "kourallinen" и т.д.
                # 3. Дополнительные слова как "kukkurallinen" перед единицей
                
                has_ingredient_pattern = False
                
                # Проверка 1: стандартные единицы
                if re.search(r'\d+[,.]?\d*\s*(dl|g|kg|l|ml|rkl|tl|kpl)', line_no_parens, re.IGNORECASE):
                    has_ingredient_pattern = True
                # Проверка 2: специальные единицы (в начале или после числа)
                elif re.search(r'(^|\d+\s+)(viipaleina|kourallinen|hyppysellinen)', line_no_parens, re.IGNORECASE):
                    has_ingredient_pattern = True
                # Проверка 3: дроби с единицами (½ tl, ¼ dl и т.д.)
                elif re.search(r'[½¼¾⅓⅔⅛⅜⅝⅞]\s*(dl|g|kg|l|ml|rkl|tl|kpl)', line_no_parens, re.IGNORECASE):
                    has_ingredient_pattern = True
                # Проверка 4: модификаторы с единицами (kukkurallinen rkl, pieni dl и т.д.)
                elif re.search(r'\d+\s+(kukkurallinen|pieni|suuri|iso)\s+(dl|g|kg|l|ml|rkl|tl|kpl)', line_no_parens, re.IGNORECASE):
                    has_ingredient_pattern = True
                # Проверка 5: просто число + название (штучные ингредиенты типа "4 mustapippuria", "1 tähtianis")
                elif re.search(r'^\d+\s+[a-zäöå]', line_no_parens, re.IGNORECASE) and len(line_no_parens.split()) <= 5:
                    has_ingredient_pattern = True
                # Проверка 6: дробь + название ("½ vaniljatanko")
                elif re.search(r'^[½¼¾⅓⅔⅛⅜⅝⅞]\s+[a-zäöå]', line_no_parens, re.IGNORECASE) and len(line_no_parens.split()) <= 4:
                    has_ingredient_pattern = True
                # Проверка 7: специальные слова количества ("hieman raastettua...")
                elif re.search(r'^(hieman|vähän|ripaus)\s+[a-zäöå]', line_no_parens, re.IGNORECASE):
                    has_ingredient_pattern = True
                
                if has_ingredient_pattern:
                    ingredient_count += 1
                    parsed = self._parse_ingredient_line(line)
                    if parsed:
                        temp_ingredients.append(parsed)
            
            # Если нашли хотя бы 3 ингредиента в параграфе, добавляем их
            if ingredient_count >= 3:
                all_ingredients.extend(temp_ingredients)
        
        return json.dumps(all_ingredients, ensure_ascii=False) if all_ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение инструкций приготовления на основе структуры HTML"""
        # Ищем главную секцию с контентом
        body_div = self.soup.find('div', id='body')
        if not body_div:
            return None
        
        # Получаем все параграфы
        paragraphs = body_div.find_all('p')
        
        all_instructions = []
        
        # Определяем индекс последнего параграфа с ингредиентами
        # Ингредиенты обычно содержат числа с единицами измерения и <br> теги
        last_ingredient_index = -1
        
        for i, p in enumerate(paragraphs):
            html_content = str(p)
            text = p.get_text(strip=True)
            
            # Проверяем признаки ингредиентов
            has_br = '<br>' in html_content or '<br/>' in html_content
            has_units = bool(re.search(r'\d+[,.\-]?\d*\s*(dl|g|kg|l|ml|rkl|tl|kpl|viipaleina)', text, re.IGNORECASE))
            has_measure_words = bool(re.search(r'\b(kourallinen|hyppysellinen|ripaus|tilkka|hieman|vähän)\b', text, re.IGNORECASE))
            
            # Если параграф содержит признаки ингредиентов, запоминаем его индекс
            if (has_br and has_units) or has_measure_words:
                last_ingredient_index = i
            
            # Пропускаем очень короткие параграфы, которые являются заголовками
            # Например: "Lisäksi", "4 annosta"
            if len(text) < 15 and not has_units:
                continue
        
        # Теперь извлекаем инструкции из параграфов ПОСЛЕ ингредиентов
        # Стратегия 1: Параграфы с тегами <strong> после ингредиентов
        for i, p in enumerate(paragraphs):
            # Пропускаем параграфы до и включая последний с ингредиентами
            if i <= last_ingredient_index:
                continue
            
            strong_tags = p.find_all('strong')
            text = p.get_text(separator=' ', strip=True)
            
            # Пропускаем параграфы с примечаниями о рецепте
            if 'resepti on matkakertomuksesta' in text.lower() or 'resepti on artikkelista' in text.lower():
                break
            
            # Пропускаем слишком короткие параграфы (вероятно, пустые или заметки)
            if len(text) < 10:
                continue
            
            # Если параграф содержит теги <strong>, это скорее всего инструкция
            if strong_tags and len(strong_tags) > 0:
                # Проверяем, что это не заголовок раздела
                # Заголовки обычно: очень короткие, полностью в strong, содержат слова типа "Lisäksi", "Ainekset"
                strong_text = strong_tags[0].get_text(strip=True).lower()
                
                # Список слов, которые указывают на заголовки разделов (не инструкции)
                section_headers = ['lisäksi', 'ainekset', 'valmistus', 'ohje', 'resepti', 'annosta']
                
                # Если strong содержит только заголовок раздела - пропускаем
                if any(header in strong_text for header in section_headers) and len(text) < 30:
                    continue
                
                # Это инструкция
                full_text = re.sub(r'\s+', ' ', text)
                all_instructions.append(self.clean_text(full_text))
        
        # Стратегия 2: Если не нашли инструкции с тегами strong,
        # пробуем найти их в параграфах с <br> (старый формат - всё в одном параграфе)
        if not all_instructions:
            for p in paragraphs:
                html_content = str(p)
                
                # Ищем параграф с ингредиентами и инструкциями (длинный параграф с <br>)
                if '<br>' in html_content or '<br/>' in html_content:
                    # Разбиваем по <br>
                    text_parts = p.get_text(separator='|||BR|||').split('|||BR|||')
                    lines = [line.strip() for line in text_parts if line.strip()]
                    
                    # Если слишком мало строк, это не комбинированный параграф
                    if len(lines) < 5:
                        continue
                    
                    # Ищем начало инструкций (обычно после ингредиентов)
                    instruction_lines = []
                    found_ingredients = False
                    in_instructions = False
                    
                    for line in lines:
                        # Если нашли строку с количеством, это ингредиенты
                        if re.search(r'\d+[,.]?\d*\s*(dl|g|kg|l|ml|rkl|tl|kpl)', line, re.IGNORECASE) or \
                           re.search(r'^(kourallinen|hyppysellinen)', line, re.IGNORECASE):
                            found_ingredients = True
                            in_instructions = False
                        # Проверяем начало инструкций: предложение с заглавной буквы после ингредиентов
                        elif found_ingredients and not in_instructions:
                            # Инструкции обычно начинаются с заглавной буквы и достаточно длинные
                            if re.match(r'^[A-ZÄÖÅ]', line) and len(line) > 15:
                                in_instructions = True
                                instruction_lines.append(line)
                        # Продолжение инструкций
                        elif in_instructions:
                            # Если строка слишком короткая или это примечание - останавливаемся
                            if len(line) < 10:
                                break
                            instruction_lines.append(line)
                    
                    if instruction_lines:
                        all_instructions.extend(instruction_lines)
                        break  # Нашли параграф с инструкциями, больше не ищем
        
        # Возвращаем все инструкции как одну строку
        if all_instructions:
            return ' '.join(all_instructions)
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # На сайте onedaywetakeatrain.fi нет структурированной информации о питании
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Категория часто указана в пути URL
        # Например: /index.php/frontpage/reseptit/aamiaiset/ -> "aamiaiset"
        
        # Получаем title или URL из мета-тегов
        title = self.soup.find('title')
        if title:
            # Проверяем навигацию
            nav = self.soup.find('ul', class_='nav')
            if nav:
                selected = nav.find('li', class_='nav-path-selected')
                if selected:
                    # Это "Reseptit", но нам нужна подкатегория
                    pass
        
        # Попробуем извлечь из имени файла HTML
        # Имя файла обычно содержит путь: index.php_frontpage_reseptit_CATEGORY_...
        if hasattr(self, 'html_path'):
            filename = Path(self.html_path).name
            # Парсим имя файла
            parts = filename.split('_')
            if len(parts) > 3 and parts[2] == 'reseptit':
                category = parts[3]
                # Переводим финские категории
                category_map = {
                    'aamiaiset': 'Aamiainen',
                    'lounas': 'Lounas',
                    'illallinen': 'Illallinen',
                    'välipala': 'Välipala',
                    'jälkiruoka': 'Jälkiruoka'
                }
                return category_map.get(category, category.capitalize())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На сайте нет структурированной информации о времени
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # На сайте нет структурированной информации о времени
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # На сайте нет структурированной информации о времени
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Заметки обычно находятся в параграфе перед ингредиентами
        # или в строках внутри параграфа с ингредиентами, которые не являются ингредиентами
        
        body_div = self.soup.find('div', id='body')
        if not body_div:
            return None
        
        paragraphs = body_div.find_all('p')
        
        # Ищем параграф с ингредиентами
        for p in paragraphs:
            html_content = str(p)
            
            if '<br>' in html_content or '<br/>' in html_content:
                # Разбиваем по <br>
                text_parts = p.get_text(separator='|||BR|||').split('|||BR|||')
                lines = [line.strip() for line in text_parts if line.strip()]
                
                note_lines = []
                
                for line in lines:
                    # Ищем строки перед ингредиентами, которые содержат заметки
                    # Заметки обычно содержат ключевые слова и не являются ингредиентами
                    
                    # Пропускаем ингредиенты
                    if re.search(r'\d+[,.]?\d*\s*(dl|g|kg|l|ml|rkl|tl|kpl)', line, re.IGNORECASE):
                        continue
                    if re.search(r'^(kourallinen|hyppysellinen)', line, re.IGNORECASE):
                        continue
                    # Пропускаем инструкции
                    if re.match(r'^[A-ZÄÖÅ][a-zäöå]+', line) and any(verb in line.lower() for verb in ['laita', 'sekoita', 'lisää', 'kaada', 'anna', 'valmista']):
                        continue
                    # Пропускаем строки с информацией о количестве порций
                    if re.search(r'(dl|l)\s+(valmista|smoothie)', line, re.IGNORECASE):
                        continue
                    
                    # Ищем строки с заметками (содержат ключевые слова)
                    note_keywords = ['saa', 'edullisesti', 'esimerkiksi', 'muista', 'pitää', 'kannattaa', 'oltava']
                    
                    if any(keyword in line.lower() for keyword in note_keywords) and len(line) > 20 and len(line) < 300:
                        note_lines.append(line)
                
                if note_lines:
                    # Объединяем заметки
                    notes = ' '.join(note_lines)
                    return self.clean_text(notes)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Парсим и очищаем теги
            tags = [tag.strip().lower() for tag in keywords.split(',') if tag.strip()]
            
            # Фильтруем и упрощаем теги
            filtered_tags = []
            seen_words = set()
            
            for tag in tags:
                # Извлекаем ключевые слова из длинных тегов
                # Например: "banaani-nokkossmoothie" -> берем основные слова
                words = re.split(r'[-\s]+', tag)
                
                # Берем основные слова (не слишком длинные фразы)
                if len(words) <= 3:
                    # Пропускаем общие слова
                    if tag not in {'resepti', 'recipe'}:
                        filtered_tags.append(tag)
                else:
                    # Для длинных фраз берем ключевые слова
                    for word in words:
                        if len(word) >= 4 and word not in seen_words and word not in {'recipe', 'resepti', 'smoothie'}:
                            seen_words.add(word)
            
            # Удаляем дубликаты, сохраняя порядок
            seen = set()
            unique_tags = []
            for tag in filtered_tags:
                if tag not in seen:
                    seen.add(tag)
                    unique_tags.append(tag)
            
            # Возвращаем первые 5 тегов
            if unique_tags:
                return ', '.join(unique_tags[:5])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем изображения в body div
        body_div = self.soup.find('div', id='body')
        if body_div:
            # Ищем все img теги
            images = body_div.find_all('img')
            
            for img in images:
                src = img.get('src')
                if src:
                    # Пропускаем маленькие изображения и иконки
                    width = img.get('width')
                    height = img.get('height')
                    
                    # Добавляем только изображения с разумными размерами
                    if width and height:
                        try:
                            w = int(width)
                            h = int(height)
                            if w > 100 and h > 100:
                                # Преобразуем относительные URL в абсолютные
                                if src.startswith('/'):
                                    src = 'https://onedaywetakeatrain.fi' + src
                                urls.append(src)
                        except ValueError:
                            pass
        
        # Удаляем дубликаты
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url not in seen:
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
        instructions = self.extract_steps()
        nutrition_info = self.extract_nutrition_info()
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
            "nutrition_info": nutrition_info,
            "category": category,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "notes": notes,
            "tags": tags,
            "image_urls": image_urls
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "onedaywetakeatrain_fi")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(OnedaywetakeatrainFiExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python onedaywetakeatrain_fi.py")


if __name__ == "__main__":
    main()
