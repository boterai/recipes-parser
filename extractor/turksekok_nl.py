"""
Экстрактор данных рецептов для сайта turksekok.nl
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TurksekokExtractor(BaseRecipeExtractor):
    """Экстрактор для turksekok.nl"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке страницы
        title = self.soup.find('title')
        if title:
            title_text = title.get_text()
            # Удаляем суффиксы типа " RECEPT", " tarifi", " nasil yapilir"
            title_text = re.sub(r'\s+(RECEPT|tarifi|nasil yapilir).*$', '', title_text, flags=re.IGNORECASE)
            # Удаляем скобки с содержимым
            title_text = re.sub(r'\s*\([^)]*\)', '', title_text)
            return self.clean_text(title_text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала ищем в контенте рецепта (более полное описание)
        content = self.soup.find('div', class_='qa-q-view-content')
        if content:
            # Ищем первый параграф с тегом <em> или просто текстовый параграф
            paragraphs = content.find_all('p', recursive=False)
            for p in paragraphs:
                # Пропускаем параграфы с изображениями
                if p.find('img'):
                    continue
                # Пропускаем параграфы с <strong> (это обычно заголовки)
                if p.find('strong'):
                    continue
                
                text = p.get_text(strip=True)
                if text and len(text) > 20:
                    # Это описание
                    return self.clean_text(text)
        
        # Если не нашли в контенте, ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Удаляем префиксы типа "Название Recept | Название Tarifi Nasil Yapilir |"
            desc = re.sub(r'^[^|]+\|[^|]+\|\s*', '', desc)
            # Удаляем многоточие в конце
            desc = re.sub(r'\s*\.\.\.$', '', desc)
            return self.clean_text(desc)
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем все секции с ингредиентами (они начинаются с "Ingrediënten voor")
        # Находим все теги <p> с <strong>, содержащие "Ingrediënten"
        ingredient_headers = self.soup.find_all('p')
        
        for header in ingredient_headers:
            strong_tag = header.find('strong')
            if not strong_tag:
                continue
            
            header_text = strong_tag.get_text(strip=True)
            if 'Ingrediënten' not in header_text:
                continue
            
            # Находим следующий список <ul> после этого заголовка
            next_ul = header.find_next_sibling('ul')
            if not next_ul:
                continue
            
            # Извлекаем элементы списка
            items = next_ul.find_all('li')
            for item in items:
                # Получаем текст ингредиента
                ingredient_text = item.get_text(separator=' ', strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                # Если есть звездочка и после нее идет объяснение, разделяем
                # Паттерн: "1 theelepel suiker* *Lactose-intolerant..."
                if '*' in ingredient_text:
                    # Разделяем по звездочке и берем первую часть
                    parts = ingredient_text.split('*')
                    if len(parts) > 1:
                        # Первая часть - это сам ингредиент
                        ingredient_text = parts[0].strip()
                        # Остальное игнорируем (это notes, они будут извлечены отдельно)
                
                # Парсим ингредиент
                if ingredient_text:
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "250 gram spinazie" или "3 eieren"
            
        Returns:
            dict: {"name": "spinazie", "amount": "250", "unit": "gram"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Пропускаем примечания (обычно содержат * или начинаются с маленькой буквы после точки)
        if text.startswith('*') or re.match(r'^[a-z]', text):
            return None
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "250 gram spinazie", "3 eieren", "half bosje peterselie"
        # Единицы измерения в голландском: gram, ml, milliliter, liter, theelepel, eetlepel, stuks, bosje
        pattern = r'^([\d\s/.,]+|half|halve)?\s*(gram|g|ml|milliliter|liter|l|theelepels?|eetlepels?|stuks?|bosjes?|blokjes?|pakjes?|zakjes?)?\s*(.+?)(?:\s*\([^)]*\))?$'
        
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
            if amount_str.lower() in ['half', 'halve']:
                amount = "half"
            elif '/' in amount_str:
                # Обработка дробей типа "1/2"
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                amount = str(int(total)) if total == int(total) else str(total)
            else:
                # Простое число
                try:
                    num = float(amount_str.replace(',', '.'))
                    amount = str(int(num)) if num == int(num) else str(num)
                except ValueError:
                    amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем ссылки и скобки из названия
        name = re.sub(r'\([^)]*\)', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions = []
        
        # Ищем секции с инструкциями (они начинаются с "Bereiding" или содержат "bereiding")
        instruction_headers = self.soup.find_all('p')
        
        for header in instruction_headers:
            strong_tag = header.find('strong')
            if not strong_tag:
                continue
            
            header_text = strong_tag.get_text(strip=True)
            if 'bereiding' not in header_text.lower():
                continue
            
            # Находим все списки <ul> после этого заголовка (до следующего заголовка)
            # Инструкции могут быть разбиты на несколько <ul> с изображениями между ними
            current = header.find_next_sibling()
            
            while current:
                # Если встретили новый заголовок с "Ingrediënten" или другой заголовок секции, останавливаемся
                if current.name == 'p':
                    strong = current.find('strong')
                    if strong and ('Ingrediënten' in strong.get_text() or 
                                  strong.get_text().strip().endswith(':')):
                        break
                
                # Если это список <ul>, извлекаем инструкции
                if current.name == 'ul':
                    items = current.find_all('li', recursive=False)
                    for item in items:
                        # Получаем текст инструкции (без изображений)
                        step_text = item.get_text(separator=' ', strip=True)
                        step_text = self.clean_text(step_text)
                        
                        # Удаляем двоеточие в конце, если оно есть
                        if step_text.endswith(':'):
                            step_text = step_text[:-1]
                        
                        # Убеждаемся, что шаг заканчивается точкой (если её еще нет)
                        if step_text and not step_text.endswith('.'):
                            step_text += '.'
                        
                        if step_text and len(step_text) > 3:
                            instructions.append(step_text)
                
                current = current.find_next_sibling()
        
        # Объединяем все инструкции в одну строку
        result = ' '.join(instructions)
        
        # Удаляем двойные точки, если они есть
        result = result.replace('..', '.')
        
        return result if result else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в meta keywords - первое значение обычно категория
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Берем первое значение до запятой
            category = keywords.split(',')[0].strip()
            return self.clean_text(category) if category else None
        
        # Альтернативно - ищем в span с itemprop="recipeCategory"
        recipe_category = self.soup.find('span', itemprop='recipeCategory')
        if recipe_category:
            return self.clean_text(recipe_category.get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в тексте страницы фразы типа "laat het rijzen voor 30 minuten"
        page_text = self.soup.get_text()
        
        # Ищем паттерн "rijzen voor X minuten" (rise for X minutes)
        rise_match = re.search(r'rijzen voor\s*(\d+)\s*minuten', page_text, re.IGNORECASE)
        if rise_match:
            minutes = rise_match.group(1)
            return f"{minutes} minutes"
        
        # Иначе используем время из meta keywords (но это обычно total time)
        # Не используем его для prep_time, так как это может быть общее время
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте страницы различные паттерны времени готовки
        page_text = self.soup.get_text()
        
        # Паттерны для поиска времени готовки:
        # 1. "Dit duurt ongeveer X minuten" (This takes about X minutes)
        # 2. "voor (ongeveer) X minuten" в контексте духовки
        # 3. "op X graden voor Y minuten"
        
        # Паттерн 1: "Dit duurt ongeveer X minuten"
        duration_match = re.search(r'Dit duurt ongeveer\s*(\d+)\s*minuten', page_text, re.IGNORECASE)
        if duration_match:
            minutes = duration_match.group(1)
            return f"{minutes} minutes"
        
        # Паттерн 2: "voor (ongeveer) X minuten" в контексте духовки/приготовления
        oven_match = re.search(r'oven.*?voor\s*\(?ongeveer\)?\s*(\d+)\s*minuten', page_text, re.IGNORECASE)
        if oven_match:
            minutes = oven_match.group(1)
            return f"{minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в meta keywords - это обычно общее время
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Ищем паттерн типа "60 min" или "90 min"
            time_match = re.search(r'(\d+)\s*min', keywords)
            if time_match:
                minutes = time_match.group(1)
                return f"{minutes} minutes"
        
        # Если не нашли, пытаемся вычислить из prep_time + cook_time
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        
        if prep_time and cook_time:
            # Извлекаем числа из строк
            prep_match = re.search(r'(\d+)', prep_time)
            cook_match = re.search(r'(\d+)', cook_time)
            
            if prep_match and cook_match:
                total = int(prep_match.group(1)) + int(cook_match.group(1))
                return f"{total} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        notes = []
        
        # Ищем примечания в ингредиентах (обычно со звездочкой *)
        # Также ищем в любых <li> элементах, которые содержат "*" в начале текста после первой звездочки
        
        ingredient_headers = self.soup.find_all('p')
        for header in ingredient_headers:
            strong_tag = header.find('strong')
            if not strong_tag:
                continue
            
            header_text = strong_tag.get_text(strip=True)
            if 'Ingrediënten' not in header_text:
                continue
            
            # Находим следующий список <ul> после этого заголовка
            next_ul = header.find_next_sibling('ul')
            if not next_ul:
                continue
            
            # Ищем элементы списка с примечаниями
            items = next_ul.find_all('li')
            for item in items:
                item_text = item.get_text(separator=' ', strip=True)
                
                # Если есть звездочка и после нее идет текст объяснения
                if '*' in item_text:
                    parts = item_text.split('*')
                    # Ищем части, которые начинаются с текста (не с цифр)
                    for part in parts[1:]:  # Пропускаем первую часть (это сам ингредиент)
                        part = part.strip()
                        # Если это длинный текст и не начинается с цифры, это примечание
                        if part and len(part) > 10 and not part[0].isdigit():
                            note_text = self.clean_text(part)
                            if note_text and note_text not in notes:
                                notes.append(note_text)
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Разделяем по запятым
            tags = [tag.strip() for tag in keywords.split(',')]
            
            # Фильтруем теги - удаляем временные метки и количество персон
            filtered_tags = []
            for tag in tags:
                # Пропускаем паттерны типа "60 min", "10 personen"
                if re.match(r'\d+\s*(min|personen)', tag):
                    continue
                filtered_tags.append(tag)
            
            return ', '.join(filtered_tags) if filtered_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем все изображения в контенте рецепта
        # На turksekok.nl изображения обычно размещены в тексте инструкций
        
        # Ищем изображения в контейнере с рецептом
        recipe_content = self.soup.find('div', class_=re.compile(r'qa-q-view', re.I))
        if recipe_content:
            images = recipe_content.find_all('img')
            for img in images:
                src = img.get('src')
                if src and 'photobucket.com' in src:
                    # Это изображение рецепта
                    urls.append(src)
        
        # Удаляем дубликаты, сохраняя порядок
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
    """
    Точка входа для обработки HTML файлов turksekok.nl
    """
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "preprocessed",
        "turksekok_nl"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка файлов из директории: {preprocessed_dir}")
        process_directory(TurksekokExtractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python turksekok_nl.py")


if __name__ == "__main__":
    main()
