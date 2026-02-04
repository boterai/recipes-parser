"""
Экстрактор данных рецептов для сайта detglutenfrieverksted.no
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class DetGlutenfrieVerkstedExtractor(BaseRecipeExtractor):
    """Экстрактор для detglutenfrieverksted.no"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
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
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_norwegian_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента на норвежском языке
        
        Args:
            ingredient_text: Строка вида "225 g Monicas Ekornbrød" или "½ ts vaniljepulver"
            
        Returns:
            dict: {"name": "...", "amount": ..., "unit": "..."} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Специальная обработка для формата "½ pose (225 g) название"
        # Извлекаем значение из скобок, если оно более специфично
        parentheses_match = re.search(r'\((\d+(?:[.,]\d+)?)\s*(g|ml|ts|ss|dl|l|kg)\)', text, re.IGNORECASE)
        if parentheses_match:
            # Используем значение из скобок
            amount_in_parens = parentheses_match.group(1).replace(',', '.')
            unit_in_parens = parentheses_match.group(2)
            # Удаляем всё до скобок включительно
            name_part = re.sub(r'^.*?\(\d+(?:[.,]\d+)?\s*(?:g|ml|ts|ss|dl|l|kg)\)\s*', '', text, flags=re.IGNORECASE)
            # Удаляем "fra Det Glutenfrie Verksted"
            name_part = re.sub(r'\bfra\s+Det\s+Glutenfrie\s+Verksted\b', '', name_part, flags=re.IGNORECASE)
            name_part = re.sub(r'\s+', ' ', name_part).strip()
            
            return {
                "name": name_part,
                "amount": float(amount_in_parens),
                "units": unit_in_parens  # Changed from "unit" to "units"
            }
        
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
        # Норвежские единицы: g, ml, ts (teskje/teaspoon), ss (spiseskje/tablespoon), 
        # dl (deciliter), l (liter), pose (package/bag), stk (piece)
        # Также обрабатываем случаи без единиц (например, "3 egg")
        pattern = r'^([\d\s/.,]+)?\s*(g|ml|ts|ss|dl|l|pose|poses|stk|kg|gram|milliliter|liter|deciliter)?\s*(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None  # Changed from "unit" to "units"
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
                amount = float(amount_str.replace(',', '.'))
        
        # Обработка единицы измерения
        units = unit.strip() if unit else None  # Changed variable name from "unit" to "units"
        
        # Очистка названия
        # Удаляем скобки с содержимым только если это комментарии, а не основное название
        # Сохраняем скобки типа "(vekt uten stein)" 
        name_clean = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы вроде "fra Det Glutenfrie Verksted"
        name_clean = re.sub(r'\bfra\s+Det\s+Glutenfrie\s+Verksted\b', '', name_clean, flags=re.IGNORECASE)
        # НЕ удаляем "eller" варианты - они важны!
        # name_clean = re.sub(r'\beller\s+\w+.*$', '', name_clean, flags=re.IGNORECASE)
        # Удаляем дополнительные описания типа ", romtemperert"
        name_clean = re.sub(r',\s*romtemperert', '', name_clean, flags=re.IGNORECASE)
        # Удаляем лишние пробелы
        name_clean = re.sub(r'\s+', ' ', name_clean).strip()
        
        if not name_clean or len(name_clean) < 2:
            name_clean = name.strip()
        
        return {
            "name": name_clean,
            "amount": amount,
            "units": units  # Changed from "unit" to "units"
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем <ul> внутри div с классами 'bodytext' и 'contentText'
        # Это основной контент рецепта
        content_divs = self.soup.find_all('div', class_='contentText')
        
        for content_div in content_divs:
            # Ищем ul внутри этого div
            for ul in content_div.find_all('ul'):
                # Проверяем, что это не список из cookie dialog
                # (у cookie dialog есть специфичные классы)
                if ul.get('class') and 'Cookiebot' in str(ul.get('class')):
                    continue
                
                # Ищем все <li> в этом списке
                for li in ul.find_all('li'):
                    text = li.get_text().strip()
                    
                    # Проверяем, что это похоже на ингредиент:
                    # 1. Содержит единицы измерения (учитываем Unicode дроби)
                    # 2. ИЛИ начинается с числа и затем слово (для ингредиентов без единиц, например "3 egg")
                    has_units = bool(re.search(r'[½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘\d]+\s*(g|ml|ts|ss|dl|l|pose|stk|kg)', text, re.IGNORECASE))
                    has_number = bool(re.match(r'^[\d½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘\s/.,]+\s+[a-zA-ZæøåÆØÅ]', text))
                    
                    if has_units or has_number:
                        # Фильтруем cookie/служебный текст
                        if not any(skip in text.lower() for skip in ['cookie', 'nødvendig', 'cloudflare', 'amazon', 'lær mer', 'leverandøren']):
                            parsed = self.parse_norwegian_ingredient(text)
                            if parsed:
                                ingredients.append(parsed)
                
                # После основного списка ингредиентов могут быть дополнительные в <p>
                # Например, "Topping:" с ингредиентами в следующих параграфах
                # Проверяем следующие siblings после ul
                for sibling in ul.find_next_siblings(['p']):
                    text = sibling.get_text().strip()
                    
                    # Если это заголовок (типа "Topping:" или "Dette gjør du:"), пропускаем
                    if text.endswith(':') and len(text) < 20:
                        continue
                    
                    # Если начинается с номера - это инструкции, прекращаем
                    if re.match(r'^\d+\.', text):
                        break
                    
                    # Проверяем, что это ингредиент
                    # Учитываем Unicode дроби и ингредиенты без единиц
                    has_units = bool(re.search(r'^[½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘\d]+\s*(g|ml|ts|ss|dl|l|pose|stk|kg)', text, re.IGNORECASE))
                    has_number = bool(re.match(r'^[\d½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘\s/.,]+\s+[a-zA-ZæøåÆØÅ]', text))
                    
                    if has_units or has_number:
                        if not any(skip in text.lower() for skip in ['cookie', 'nødvendig', 'cloudflare', 'amazon', 'lær mer', 'leverandøren']):
                            parsed = self.parse_norwegian_ingredient(text)
                            if parsed:
                                ingredients.append(parsed)
        
        # Если ничего не найдено через <li>, пробуем другие варианты
        if not ingredients:
            # Ищем в параграфах с измерениями
            for p in self.soup.find_all('p'):
                text = p.get_text().strip()
                if re.search(r'\d+\s*(g|ml|ts|ss|dl|l)', text, re.IGNORECASE):
                    lines = text.split('\n')
                    for line in lines:
                        if re.search(r'\d+\s*(g|ml|ts|ss|dl|l)', line, re.IGNORECASE):
                            parsed = self.parse_norwegian_ingredient(line)
                            if parsed:
                                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем все параграфы, начинающиеся с номера (1., 2., 3., ...)
        for p in self.soup.find_all('p'):
            text = p.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            
            # Проверяем, начинается ли с номера
            if re.match(r'^\d+\.', text):
                steps.append(text)
        
        # Если не нашли пронумерованные шаги, ищем в списке <ol>
        if not steps:
            for ol in self.soup.find_all('ol'):
                items = ol.find_all('li')
                for idx, item in enumerate(items, 1):
                    text = item.get_text(separator=' ', strip=True)
                    text = self.clean_text(text)
                    if text:
                        # Добавляем нумерацию, если её нет
                        if not re.match(r'^\d+\.', text):
                            text = f"{idx}. {text}"
                        steps.append(text)
                
                if steps:
                    break
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Известные категории на сайте
        categories = ['Dessert', 'Frokost', 'Middag', 'Kaker', 'Brød', 'Gjærbakst', 
                     'Frokost og lunsj', 'Søt bakst', 'Surdeig', 'Høytider']
        
        # Ищем в ссылках навигации
        for link in self.soup.find_all('a'):
            link_text = link.get_text().strip()
            if link_text in categories:
                # Проверяем, что это активная категория (например, имеет класс active)
                # или находится в breadcrumb
                parent = link.parent
                if parent and (parent.get('class') and 'active' in parent.get('class', [])):
                    return link_text
        
        # Если не нашли активную, ищем в мета-тегах
        meta_category = self.soup.find('meta', property='article:section')
        if meta_category and meta_category.get('content'):
            return self.clean_text(meta_category['content'])
        
        # Проверяем текст рядом с названием рецепта
        # Иногда категория указана рядом с заголовком
        h1 = self.soup.find('h1')
        if h1:
            # Проверяем предыдущие и следующие элементы
            for sibling in list(h1.find_previous_siblings())[:3] + list(h1.find_next_siblings())[:3]:
                text = sibling.get_text().strip()
                if text in categories:
                    return text
        
        return None
    
    def extract_time_from_text(self, text: str, time_type: str) -> Optional[str]:
        """
        Извлечение времени из текста инструкций
        
        Args:
            text: Текст для поиска
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        if not text:
            return None
        
        # Паттерны для поиска времени в норвежском тексте
        # Ищем фразы вроде "i 30 minutter", "ca. 20 minutter", "i ca. 1 time"
        patterns = [
            r'(?:i\s+)?(?:ca\.?\s+)?(\d+)\s*minut',  # "i 30 minutter" или "ca. 20 minutter"
            r'(?:i\s+)?(?:ca\.?\s+)?(\d+)\s*time',   # "i 1 time"
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                # Берем первое найденное значение
                time_val = matches[0]
                if 'minut' in pattern:
                    return f"{time_val} minutes"
                elif 'time' in pattern:
                    # Конвертируем часы в минуты
                    hours = int(time_val)
                    return f"{hours * 60} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в тексте инструкций упоминания о времени подготовки
        instructions_text = ""
        
        # Собираем весь текст из инструкций
        for p in self.soup.find_all('p'):
            text = p.get_text()
            if 'forvarm' in text.lower() or 'varm' in text.lower() or 'klargjør' in text.lower():
                time_val = self.extract_time_from_text(text, 'prep')
                if time_val:
                    return time_val
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте инструкций упоминания о времени готовки/выпекания
        for p in self.soup.find_all('p'):
            text = p.get_text()
            if any(word in text.lower() for word in ['stek', 'kok', 'bak', 'tilbered']):
                time_val = self.extract_time_from_text(text, 'cook')
                if time_val:
                    return time_val
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Если есть prep_time и cook_time, суммируем их
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep and cook:
            # Извлекаем числа
            prep_mins = int(re.search(r'(\d+)', prep).group(1)) if re.search(r'(\d+)', prep) else 0
            cook_mins = int(re.search(r'(\d+)', cook).group(1)) if re.search(r'(\d+)', cook) else 0
            total = prep_mins + cook_mins
            return f"{total} minutes" if total > 0 else None
        elif prep:
            return prep
        elif cook:
            return cook
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем текст с ключевыми словами
        keywords = ['oppbevar', 'server', 'tips', 'hint', 'merk', 'note']
        
        # Проверяем все параграфы и div-ы
        for tag in self.soup.find_all(['p', 'div', 'span']):
            text = tag.get_text(separator=' ', strip=True)
            text_lower = text.lower()
            
            # Проверяем наличие ключевых слов
            if any(keyword in text_lower for keyword in keywords):
                # Фильтруем слишком короткие и слишком длинные тексты
                if 20 < len(text) < 500:
                    # Убеждаемся, что это не часть инструкции (не начинается с номера)
                    if not re.match(r'^\d+\.', text):
                        # Исключаем служебный текст
                        if not any(skip in text_lower for skip in ['cookie', 'cloudflare', 'registers']):
                            return self.clean_text(text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в мета-тегах
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        # Ищем в article:tag
        tags = []
        for meta_tag in self.soup.find_all('meta', property='article:tag'):
            if meta_tag.get('content'):
                tags.append(meta_tag['content'])
        
        if tags:
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
            urls.append(twitter_image['content'])
        
        # 2. Ищем img теги в контенте рецепта
        # Ищем изображения рядом с заголовком или в основном контенте
        h1 = self.soup.find('h1')
        if h1:
            # Ищем в родительском контейнере
            parent = h1.find_parent(['div', 'article', 'section'])
            if parent:
                for img in parent.find_all('img')[:3]:  # Берем до 3 изображений
                    src = img.get('src') or img.get('data-src')
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
    """Обработка всех HTML файлов в директории preprocessed/detglutenfrieverksted_no"""
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join("preprocessed", "detglutenfrieverksted_no")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(DetGlutenfrieVerkstedExtractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Убедитесь, что вы запускаете скрипт из корня репозитория")


if __name__ == "__main__":
    main()
