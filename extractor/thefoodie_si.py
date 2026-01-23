"""
Экстрактор данных рецептов для сайта thefoodie.si
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TheFoodieSiExtractor(BaseRecipeExtractor):
    """Экстрактор для thefoodie.si"""
    
    # Константы для поддерживаемых единиц измерения
    SUPPORTED_UNITS = ['g', 'kg', 'ml', 'dl', 'l', 'tbsp', 'tsp', 'cup', 'cups', 
                       'žlica', 'žlice', 'skodelica', 'skodelice']
    
    # Максимальное количество параграфов инструкций
    MAX_INSTRUCTION_PARAGRAPHS = 5
    
    # Максимальное количество изображений
    MAX_IMAGES = 3
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h3
        h3 = self.soup.find('h3')
        if h3:
            return self.clean_text(h3.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем первый параграф после заголовка
        post_header = self.soup.find('div', class_='post_header')
        if post_header:
            next_p = post_header.find_next('p')
            if next_p:
                text = next_p.get_text(strip=True)
                # Проверяем, что это не секция ингредиентов или инструкций
                if text and not re.match(r'^(SESTAVINE|POSTOPEK)', text, re.I):
                    return self.clean_text(text)
        
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
            ingredient_text: Строка вида "500 g listov vlečenega testa" или "2 veliki čebuli"
            
        Returns:
            dict: {"name": "...", "amount": "...", "units": "..."} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "500 g testo", "2 veliki čebuli", "paprika, po okusu"
        # Поддерживаем как цифры, так и дроби
        units_pattern = '|'.join(self.SUPPORTED_UNITS)
        pattern = rf'^([\d\s/.,]+)?\s*({units_pattern})?\s*(.+)'
        
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
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                amount = total
            else:
                # Заменяем запятую на точку для десятичных чисел
                amount = amount_str.replace(',', '.')
                try:
                    # Пробуем конвертировать в число
                    amount = float(amount) if '.' in amount else int(amount)
                except (ValueError, TypeError):
                    amount = amount_str
        
        # Нормализация единиц измерения
        # Конвертируем kg -> g и dl -> ml для стандартизации
        if unit:
            unit_lower = unit.lower()
            if unit_lower == 'kg' and amount:
                # Конвертируем kg в g
                amount = amount * 1000
                unit = 'g'
            elif unit_lower == 'dl' and amount:
                # Конвертируем dl в ml
                amount = amount * 100
                unit = 'ml'
            else:
                unit = unit.strip()
        
        # Обработка единицы измерения
        # Если "po okusu" или "po potrebi" в тексте, это считается единицей измерения
        if not unit and ('po okusu' in name.lower() or 'po potrebi' in name.lower()):
            if 'po okusu' in name.lower():
                unit = 'po okusu'
                name = re.sub(r',?\s*po okusu\s*$', '', name, flags=re.IGNORECASE)
            elif 'po potrebi' in name.lower():
                unit = 'po potrebi'
                name = re.sub(r',?\s*po potrebi\s*$', '', name, flags=re.IGNORECASE)
        
        # Очистка названия - НЕ удаляем части до запятой или "in"
        # Только удаляем скобки в конце если нужно
        name = name.strip()
        
        # Удаляем лишние пробелы
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
        
        # Метод 1: Ищем секцию SESTAVINE в <strong> теге (для полных рецептов)
        sestavine_strong = self.soup.find('strong', string=re.compile('SESTAVINE', re.I))
        if sestavine_strong:
            # Находим следующий список ul
            ul = sestavine_strong.find_next('ul')
            if ul:
                items = ul.find_all('li', recursive=False)
                
                for item in items:
                    ingredient_text = item.get_text(strip=True)
                    ingredient_text = self.clean_text(ingredient_text)
                    
                    if ingredient_text:
                        # Проверяем, нет ли в строке "X in Y" (X and Y) - это два ингредиента
                        # Например: "sol in poper, po okusu"
                        if re.search(r'\bin\b', ingredient_text) and ',' in ingredient_text:
                            # Разделяем на части
                            parts = re.split(r'\bin\b', ingredient_text)
                            if len(parts) == 2:
                                # Первый ингредиент
                                first_part = parts[0].strip()
                                # Второй ингредиент - берем часть до запятой
                                second_match = re.match(r'([^,]+)(.*)', parts[1].strip())
                                if second_match:
                                    second_part = second_match.group(1).strip()
                                    suffix = second_match.group(2).strip()  # ", po okusu"
                                    
                                    # Парсим первый ингредиент (с суффиксом если есть)
                                    parsed1 = self.parse_ingredient(first_part + suffix)
                                    if parsed1:
                                        ingredients.append(parsed1)
                                    
                                    # Парсим второй ингредиент (с суффиксом)
                                    parsed2 = self.parse_ingredient(second_part + suffix)
                                    if parsed2:
                                        ingredients.append(parsed2)
                                    
                                    continue
                        
                        # Обычный парсинг
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
        
        # Метод 2: Если не нашли через <strong>, ищем как plain text (для excerpt страниц)
        if not ingredients:
            # Ищем параграф с текстом "SESTAVINE:"
            for p in self.soup.find_all('p'):
                text = p.get_text()
                if 'SESTAVINE:' in text:
                    # Извлекаем секцию между SESTAVINE: и POSTOPEK:
                    parts = text.split('SESTAVINE:')
                    if len(parts) > 1:
                        ingredients_text = parts[1].split('POSTOPEK:')[0] if 'POSTOPEK:' in parts[1] else parts[1]
                        ingredients_text = self.clean_text(ingredients_text).strip()
                        
                        # Простой подход: разбиваем по числам (каждый ингредиент с количеством начинается с числа)
                        # Используем negative lookbehind, чтобы не разбивать внутри чисел
                        parts_by_number = re.split(r'(?<!\d)(?=\d+\s+[a-zčšžA-ZČŠŽ])', ingredients_text)
                        
                        for part in parts_by_number:
                            part = part.strip()
                            if len(part) < 3:
                                continue
                            
                            # Каждая часть - это ингредиент с количеством + возможно еще ингредиенты без количества
                            # Пример: "500 g listov..." или "2 stroka česna paprika v prahu, po okusu"
                            
                            # Извлекаем первый ингредиент (с количеством)
                            # Паттерн: число [единица] название
                            # Название заканчивается перед следующим словом, которое может быть новым ингредиентом
                            
                            # Ищем, где заканчивается первый ингредиент
                            # Это либо перед словом после скобки ") слово", либо перед "слово слово" без запятых/скобок
                            
                            # Упрощенно: ищем паттерны нового ингредиента:
                            # - после ") " идет слово (новый ингредиент)
                            # - после ", " идет слово, не "po" и не "ali" (новый ингредиент)
                            
                            # Разбиваем по этим паттернам
                            # сначала по ") слово"
                            sub_parts = re.split(r'\)\s+(?=[a-zčšž])', part)
                            
                            final_parts = []
                            for sp in sub_parts:
                                # Добавляем закрывающую скобку обратно
                                if sp and ')' not in sp and len(sub_parts) > 1 and sub_parts.index(sp) < len(sub_parts) - 1:
                                    sp = sp + ')'
                                
                                # Теперь разбиваем по ", слово" (но не ", po" и не ", ali")
                                comma_parts = []
                                last_pos = 0
                                for match in re.finditer(r',\s+(?=[a-zčšž]+)', sp):
                                    # Проверяем, что после запятой не "po" и не "ali"
                                    word_after = sp[match.end():match.end()+3]
                                    if word_after not in ['po ', 'ali', 'in ']:
                                        comma_parts.append(sp[last_pos:match.start()].strip())
                                        last_pos = match.end()
                                
                                # Добавляем остаток
                                if last_pos < len(sp):
                                    comma_parts.append(sp[last_pos:].strip())
                                
                                final_parts.extend(comma_parts if comma_parts else [sp])
                            
                            # Парсим каждую финальную часть
                            for fp in final_parts:
                                fp = fp.strip()
                                if len(fp) < 2:
                                    continue
                                
                                # Проверяем на "X in Y"
                                if ' in ' in fp:
                                    in_parts = fp.split(' in ')
                                    if len(in_parts) == 2:
                                        # Извлекаем suffix из второй части
                                        suffix = ''
                                        second = in_parts[1]
                                        if ',' in second:
                                            second, suffix = second.split(',', 1)
                                            suffix = ',' + suffix
                                        
                                        parsed1 = self.parse_ingredient(in_parts[0].strip() + suffix)
                                        if parsed1:
                                            ingredients.append(parsed1)
                                        
                                        parsed2 = self.parse_ingredient(second.strip() + suffix)
                                        if parsed2:
                                            ingredients.append(parsed2)
                                        continue
                                
                                parsed = self.parse_ingredient(fp)
                                if parsed:
                                    ingredients.append(parsed)
                    
                    break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions = []
        
        # Метод 1: Ищем секцию POSTOPEK в <strong> теге (для полных рецептов)
        postopek_strong = self.soup.find('strong', string=re.compile('POSTOPEK', re.I))
        if postopek_strong:
            # Получаем родительский параграф
            parent = postopek_strong.parent
            
            # Собираем все следующие параграфы до конца или до следующей секции
            current = parent.next_sibling
            para_count = 0
            while current and para_count < self.MAX_INSTRUCTION_PARAGRAPHS:
                if hasattr(current, 'name'):
                    if current.name == 'p':
                        # Используем get_text() без strip, затем применяем clean_text
                        text = current.get_text()
                        text = self.clean_text(text)
                        
                        # Останавливаемся на определенных маркерах
                        if text and not any(marker in text for marker in ['NAJ TUDI', 'PERSONALIZIRANI', 'Iščeš darilo']):
                            instructions.append(text)
                            para_count += 1
                        else:
                            break
                    # Останавливаемся, если встретили новую секцию
                    elif current.name in ['h2', 'h3', 'h4', 'hr']:
                        break
                
                current = current.next_sibling
        
        # Метод 2: Если не нашли через <strong>, ищем как plain text (для excerpt страниц)
        if not instructions:
            # Ищем параграф с текстом "POSTOPEK:"
            for p in self.soup.find_all('p'):
                text = p.get_text()
                if 'POSTOPEK:' in text:
                    # Извлекаем секцию после POSTOPEK:
                    parts = text.split('POSTOPEK:')
                    if len(parts) > 1:
                        instructions_text = parts[1]
                        # Очищаем текст, но останавливаемся на маркерах окончания
                        # Например: "Read more", "Išči:", etc.
                        end_markers = ['Read more', 'Išči:', 'Spremljajte nas:', '…']
                        for marker in end_markers:
                            if marker in instructions_text:
                                instructions_text = instructions_text.split(marker)[0]
                        
                        instructions_text = self.clean_text(instructions_text)
                        if instructions_text:
                            instructions.append(instructions_text)
                    break
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Извлекаем из классов article
        article = self.soup.find('article')
        if article:
            classes = article.get('class', [])
            categories = [c.replace('category-', '').replace('-', ' ').title() 
                         for c in classes if c.startswith('category-')]
            if categories:
                # Возвращаем первую категорию или объединяем их
                return categories[0] if len(categories) == 1 else ' / '.join(categories)
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Для этого сайта времена обычно упоминаются в тексте инструкций
        # Ищем паттерны вида "30-40 minut" или "10 min"
        
        # Получаем весь текст после секции POSTOPEK
        postopek_strong = self.soup.find('strong', string=re.compile('POSTOPEK', re.I))
        if postopek_strong:
            # Получаем текст следующих нескольких параграфов
            parent = postopek_strong.parent
            text_parts = []
            current = parent.next_sibling
            count = 0
            while current and count < 5:
                if hasattr(current, 'name') and current.name == 'p':
                    text_parts.append(current.get_text())
                    count += 1
                current = current.next_sibling
            
            full_text = ' '.join(text_parts)
            
            # Ищем время приготовления (обычно "pečemo X minut" или "X-Y minut")
            if time_type == 'cook':
                # Ищем паттерны времени приготовления
                patterns = [
                    r'pečemo[^.]*?(\d+[-–]\d+)\s*minut',
                    r'pečemo[^.]*?(\d+)\s*minut',
                    r'kuhamo[^.]*?(\d+[-–]\d+)\s*minut',
                    r'kuhamo[^.]*?(\d+)\s*minut',
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, full_text, re.I)
                    if match:
                        time_value = match.group(1)
                        return f"{time_value} minutes"
        
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
        # На этом сайте обычно нет отдельной секции заметок
        # Можно попробовать найти секции с советами или примечаниями
        
        # Ищем возможные маркеры заметок
        notes_markers = ['OPOMBA', 'NASVET', 'TIP', 'NAMIG']
        
        for marker in notes_markers:
            note_section = self.soup.find('strong', string=re.compile(marker, re.I))
            if note_section:
                parent = note_section.parent
                if parent:
                    next_p = parent.find_next('p')
                    if next_p:
                        text = self.clean_text(next_p.get_text())
                        return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из классов article"""
        article = self.soup.find('article')
        if article:
            classes = article.get('class', [])
            tags = [c.replace('tag-', '').replace('-', ' ') 
                   for c in classes if c.startswith('tag-')]
            
            if tags:
                # Возвращаем как строку через запятую
                return ', '.join(tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if url not in urls:
                urls.append(url)
        
        # 2. Ищем изображения в контенте статьи
        article = self.soup.find('article')
        if article:
            # Находим основное изображение в контенте
            images = article.find_all('img', src=True)
            for img in images[:self.MAX_IMAGES]:  # Берем первые MAX_IMAGES изображений
                src = img.get('src')
                # Пропускаем маленькие изображения (иконки, аватары)
                if src and 'avatar' not in src and src not in urls:
                    # Проверяем, что это полный URL
                    if src.startswith('http'):
                        urls.append(src)
                    elif src.startswith('//'):
                        urls.append('https:' + src)
                    elif src.startswith('/'):
                        # Относительный URL - добавляем домен
                        urls.append('https://www.thefoodie.si' + src)
        
        # Убираем дубликаты, сохраняя порядок
        unique_urls = []
        seen = set()
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        # Возвращаем как строку через запятую
        return ','.join(unique_urls) if unique_urls else None
    
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
            "dish_name": dish_name,
            "description": description,
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
    import os
    # Обрабатываем папку preprocessed/thefoodie_si
    recipes_dir = os.path.join("preprocessed", "thefoodie_si")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(TheFoodieSiExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python thefoodie_si.py")


if __name__ == "__main__":
    main()
