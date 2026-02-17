"""
Экстрактор данных рецептов для сайта superbrugsenspentrup.dk
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class SuperbrugsenspentrupExtractor(BaseRecipeExtractor):
    """Экстрактор для superbrugsenspentrup.dk"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала попробуем найти заголовок h2/h3 с "Opskrift:" в начале (это более надежный источник)
        headers = self.soup.find_all(['h2', 'h3'])
        for h in headers:
            text = h.get_text().strip()
            if text.lower().startswith('opskrift:') and ':' in text:
                # Извлекаем название после "Opskrift:"
                parts = text.split(':', 1)
                if len(parts) > 1:
                    dish_name = parts[1].strip()
                    # Убираем дополнительные суффиксы в скобках
                    dish_name = re.sub(r'\s*\(.*\)$', '', dish_name)
                    return self.clean_text(dish_name)
        
        # Если не нашли с "Opskrift:" в начале, ищем заголовок содержащий "Opskrift:" где угодно
        for h in headers:
            text = h.get_text().strip()
            if 'opskrift:' in text.lower() and ':' in text:
                # Извлекаем название после последнего ":"
                parts = text.split(':')
                if len(parts) > 1:
                    dish_name = parts[-1].strip()
                    # Убираем дополнительные суффиксы в скобках
                    dish_name = re.sub(r'\s*\(.*\)$', '', dish_name)
                    return self.clean_text(dish_name)
        
        # Если не нашли через "Opskrift:", ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            title = h1.get_text().strip()
            # Очищаем от лишних фраз типа ": Guide og opskrift"
            title = re.sub(r':\s*(Guide|Opskrift|Din\s+guide).*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*\|\s*Superbrugsen.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Альтернативно - из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s*\|\s*Superbrugsen.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r':\s*(Guide|Opskrift).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
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
    
    def parse_ingredient_item(self, item_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            item_text: Строка вида "150 g sushiris" или "2,5 eller 5 stykker nori-tang"
            
        Returns:
            dict: {"name": "sushiris", "amount": "150", "unit": "g"} или None
        """
        if not item_text:
            return None
        
        # Чистим текст
        text = self.clean_text(item_text).strip()
        
        # Заменяем запятую на точку для чисел (датский формат)
        text = re.sub(r'(\d),(\d)', r'\1.\2', text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "150 g sushiris", "2 dl vand", "2,5 eller 5 stykker nori-tang"
        # Более сложные: "1/2 pakke flødeost naturel", "Et godt nip salt"
        
        # Сначала попробуем паттерн с числами и единицами
        pattern = r'^([\d\s/.,]+(?:\s+eller\s+[\d\s/.,]+)?)\s*(g|kg|dl|l|ml|cm|mm|spsk|tsk|pakke|pakker|stykker?|stk\.?|ds\.?)?\s*(.+)$'
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                amount_str = amount_str.strip()
                # Обработка "eller" (или) - берем первое значение
                if 'eller' in amount_str:
                    amount_str = amount_str.split('eller')[0].strip()
                
                # Обработка дробей
                if '/' in amount_str:
                    parts = amount_str.split()
                    total = 0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            total += float(part)
                    amount = str(total) if total != int(total) else str(int(total))
                else:
                    amount = amount_str.replace(',', '.')
            
            # Обработка единицы измерения
            if unit:
                # Нормализация единиц
                unit = unit.strip().lower()
                # Замена датских сокращений
                unit_map = {
                    'tsk': 'tsp',
                    'tsk.': 'tsp',
                    'spsk': 'tbsp',
                    'ds': 'ds',
                    'ds.': 'ds',
                    'stykker': 'stykker',
                    'stykke': 'stykker',
                    'stk': 'stykker',
                    'stk.': 'stykker',
                    'pakker': 'pakke',
                }
                unit = unit_map.get(unit, unit)
            
            # Очистка названия
            name = re.sub(r'\([^)]*\)', '', name)  # Удаляем скобки
            name = re.sub(r'\b(valgfrit|til\s+[\w\s]+|i\s+små\s+tern)\b.*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r',\s*skyllet\s+grundigt.*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'^[.,;\s]+', '', name)  # Удаляем leading пунктуацию
            name = re.sub(r'[,;]+$', '', name)  # Удаляем trailing пунктуацию
            name = re.sub(r'\s+', ' ', name).strip()
            
            if name and len(name) >= 2:
                return {
                    "name": name,
                    "amount": amount,
                    "unit": unit
                }
        
        # Если паттерн не сработал, попробуем обработать случаи без чисел
        # Например: "Et godt nip salt" -> {"name": "salt", "amount": None, "unit": None}
        # Или "Salt og peber" -> {"name": "salt og peber", "amount": None, "unit": None}
        if any(word in text.lower() for word in ['nip', 'dash', 'pinch', 'lidt']):
            # Убираем описательные слова
            name = re.sub(r'^(et\s+godt\s+)?nip\s+', '', text, flags=re.IGNORECASE)
            name = re.sub(r'^(a\s+)?dash\s+', '', text, flags=re.IGNORECASE)
            name = re.sub(r'^lidt\s+', '', text, flags=re.IGNORECASE)
            name = self.clean_text(name)
            if name:
                return {
                    "name": name,
                    "amount": None,
                    "unit": None
                }
        
        # Если ничего не подошло, возвращаем весь текст как название
        return {
            "name": text,
            "amount": None,
            "unit": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала попробуем найти секцию "Opskrift" и затем "Ingredienser" рядом с ней
        headers = self.soup.find_all(['h2', 'h3', 'h4'])
        opskrift_found = False
        
        for i, header in enumerate(headers):
            header_text = header.get_text().strip().lower()
            
            # Отмечаем, когда нашли секцию Opskrift
            if 'opskrift:' in header_text or (header.name == 'h2' and 'opskrift' in header_text):
                opskrift_found = True
                continue
            
            # Если уже нашли Opskrift, ищем Ingredienser
            if opskrift_found and 'ingrediens' in header_text:
                # Ищем ВСЕ списки после заголовка до следующего h2
                current = header.find_next_sibling()
                while current:
                    if current.name == 'h2':  # stop at next h2
                        break
                    if current.name in ['ul', 'ol']:
                        items = current.find_all('li')
                        for item in items:
                            ingredient_text = item.get_text(separator=' ', strip=True)
                            ingredient_text = self.clean_text(ingredient_text)
                            
                            # Пропускаем слишком длинные описательные элементы (вероятно, не ингредиенты)
                            if len(ingredient_text) > 200:
                                continue
                            
                            if ingredient_text:
                                parsed = self.parse_ingredient_item(ingredient_text)
                                if parsed:
                                    ingredients.append({
                                        "name": parsed["name"],
                                        "amount": parsed["amount"],
                                        "units": parsed["unit"]
                                    })
                    # Проверяем также вложенные списки в div
                    elif current.name == 'div':
                        nested_lists = current.find_all(['ul', 'ol'])
                        for lst in nested_lists:
                            items = lst.find_all('li')
                            for item in items:
                                ingredient_text = item.get_text(separator=' ', strip=True)
                                ingredient_text = self.clean_text(ingredient_text)
                                
                                if len(ingredient_text) > 200:
                                    continue
                                
                                if ingredient_text:
                                    parsed = self.parse_ingredient_item(ingredient_text)
                                    if parsed:
                                        ingredients.append({
                                            "name": parsed["name"],
                                            "amount": parsed["amount"],
                                            "units": parsed["unit"]
                                        })
                    current = current.find_next_sibling()
                
                if ingredients:
                    break
        
        # Если не нашли через опциальный путь, пробуем просто найти "Ingredienser"
        if not ingredients:
            for header in headers:
                header_text = header.get_text().strip().lower()
                if 'ingrediens' in header_text and header.name == 'h3':
                    # Ищем ВСЕ списки после заголовка до следующего h2
                    current = header.find_next_sibling()
                    while current:
                        if current.name == 'h2':
                            break
                        if current.name in ['ul', 'ol']:
                            items = current.find_all('li')
                            for item in items:
                                ingredient_text = item.get_text(separator=' ', strip=True)
                                ingredient_text = self.clean_text(ingredient_text)
                                
                                # Пропускаем описательные элементы
                                if ':' in ingredient_text and len(ingredient_text) > 100:
                                    continue
                                
                                if ingredient_text:
                                    parsed = self.parse_ingredient_item(ingredient_text)
                                    if parsed:
                                        ingredients.append({
                                            "name": parsed["name"],
                                            "amount": parsed["amount"],
                                            "units": parsed["unit"]
                                        })
                        current = current.find_next_sibling()
                    
                    if ingredients:
                        break
        
        # Если все еще не нашли, ищем списки с числовыми значениями
        if not ingredients:
            lists = self.soup.find_all(['ul', 'ol'])
            
            for lst in lists:
                items = lst.find_all('li')
                if not items:
                    continue
                
                # Проверяем, есть ли в первом элементе числа
                first_item_text = items[0].get_text().strip()
                if not re.search(r'\d', first_item_text):
                    continue
                
                # Проверяем, что это не шаги инструкций
                if re.match(r'^\d+\.\s+[A-ZÆØÅ]', first_item_text):
                    continue
                
                # Проверяем, что это не список месяцев/дат
                if re.search(r'(januar|februar|marts|april|maj|juni|juli|august|september|oktober|november|december)\s+20\d{2}', first_item_text, re.IGNORECASE):
                    continue
                
                # Проверяем, что это не описательный список
                if ':' in first_item_text and len(first_item_text) > 100:
                    continue
                
                # Это похоже на список ингредиентов
                temp_ingredients = []
                for item in items:
                    ingredient_text = item.get_text(separator=' ', strip=True)
                    ingredient_text = self.clean_text(ingredient_text)
                    
                    if ingredient_text:
                        parsed = self.parse_ingredient_item(ingredient_text)
                        if parsed:
                            temp_ingredients.append({
                                "name": parsed["name"],
                                "amount": parsed["amount"],
                                "units": parsed["unit"]
                            })
                
                # Берем только если нашли достаточно разумных ингредиентов
                if temp_ingredients and len(temp_ingredients) >= 3:
                    ingredients = temp_ingredients
                    break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем заголовок "Fremgangsmåde" или похожие
        headers = self.soup.find_all(['h2', 'h3', 'h4'])
        
        for header in headers:
            header_text = header.get_text().strip().lower()
            if 'fremgangsmåde' in header_text or 'vejledning' in header_text or 'tilberedning' in header_text:
                # Ищем следующий упорядоченный список или параграфы с инструкциями
                current = header.find_next_sibling()
                instruction_paragraphs = []
                step_number = 1
                
                while current:
                    if current.name == 'ol':
                        # Нашли упорядоченный список
                        items = current.find_all('li', recursive=False)
                        for idx, item in enumerate(items, 1):
                            step_text = item.get_text(separator=' ', strip=True)
                            step_text = self.clean_text(step_text)
                            if step_text:
                                steps.append(f"{idx}. {step_text}")
                        break
                    elif current.name == 'div':
                        # Проверяем вложенные списки в div
                        nested_ol = current.find('ol')
                        if nested_ol:
                            items = nested_ol.find_all('li', recursive=False)
                            for idx, item in enumerate(items, 1):
                                step_text = item.get_text(separator=' ', strip=True)
                                step_text = self.clean_text(step_text)
                                if step_text:
                                    steps.append(f"{idx}. {step_text}")
                            break
                    elif current.name == 'p':
                        # Собираем параграфы как шаги
                        step_text = current.get_text(separator=' ', strip=True)
                        step_text = self.clean_text(step_text)
                        # Пропускаем очень короткие или пустые параграфы
                        if step_text and len(step_text) > 15:
                            instruction_paragraphs.append(step_text)
                    elif current.name == 'h4':
                        # Подзаголовок в инструкциях - добавляем как контекст
                        h4_text = current.get_text().strip()
                        # Не добавляем подзаголовок, а просто продолжаем
                        pass
                    elif current.name == 'h2':
                        # Достигли следующего основного заголовка
                        break
                    
                    current = current.find_next_sibling()
                
                # Если нашли упорядоченный список, используем его
                if steps:
                    break
                
                # Если нашли параграфы, нумеруем их
                if instruction_paragraphs:
                    for idx, para in enumerate(instruction_paragraphs, 1):
                        steps.append(f"{idx}. {para}")
                    break
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в метаданных article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            category = meta_section['content']
            # Преобразуем датские категории в общие
            category_map = {
                'opskrifter': 'Recipe',
                'forret': 'Appetizer',
                'hovedret': 'Main Course',
                'dessert': 'Dessert',
                'snack': 'Snack',
                'tilbehør': 'Side Dish'
            }
            category_lower = category.lower()
            return category_map.get(category_lower, 'Main Course')
        
        # Если нет метаданных, пытаемся определить по тегам или содержанию
        return 'Main Course'
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в тексте паттерны времени подготовки
        # Датский: "Forberedelsestid: 15 minutter"
        text = self.soup.get_text()
        
        patterns = [
            r'forberedelsestid:\s*(\d+)\s*minutter?',
            r'prep\s*time:\s*(\d+)\s*minutes?',
            r'klargøring:\s*(\d+)\s*minutter?'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return f"{match.group(1)} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте паттерны времени приготовления
        text = self.soup.get_text()
        
        patterns = [
            r'tilberedningstid:\s*(\d+)\s*minutter?',
            r'cook\s*time:\s*(\d+)\s*minutes?',
            r'kogetid:\s*(\d+)\s*minutter?',
            r'stegning:\s*(\d+[-–]?\d*)\s*(?:sekunder?|minutter?)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                time_value = match.group(1)
                # Если это диапазон (например "10-20"), берем среднее
                if '-' in time_value or '–' in time_value:
                    parts = re.split(r'[-–]', time_value)
                    avg = (int(parts[0]) + int(parts[1])) / 2
                    return f"{int(avg)} seconds" if 'sekund' in match.group(0).lower() else f"{int(avg)} minutes"
                return f"{time_value} seconds" if 'sekund' in match.group(0).lower() else f"{time_value} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в тексте паттерны общего времени
        text = self.soup.get_text()
        
        patterns = [
            r'samlet\s*tid:\s*(\d+)\s*minutter?',
            r'total\s*time:\s*(\d+)\s*minutes?',
            r'tid\s*i\s*alt:\s*(\d+)\s*minutter?'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return f"{match.group(1)} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секции с заметками/советами
        headers = self.soup.find_all(['h2', 'h3', 'h4'])
        
        for header in headers:
            header_text = header.get_text().strip().lower()
            if any(word in header_text for word in ['noter', 'tips', 'råd', 'bemærk', 'vigtigt']):
                # Собираем текст после заголовка до следующего заголовка
                notes_parts = []
                current = header.find_next_sibling()
                while current:
                    if current.name in ['h2', 'h3', 'h4']:
                        break
                    if current.name == 'p':
                        text = current.get_text(separator=' ', strip=True)
                        text = self.clean_text(text)
                        if text:
                            notes_parts.append(text)
                    current = current.find_next_sibling()
                
                if notes_parts:
                    return ' '.join(notes_parts)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Попробуем извлечь из keywords meta тега
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags = [tag.strip().lower() for tag in keywords.split(',') if tag.strip()]
        
        # Если нет keywords, попробуем определить по категории и названию
        if not tags:
            dish_name = self.extract_dish_name()
            if dish_name:
                # Извлекаем ключевые слова из названия
                words = dish_name.lower().split()
                # Убираем общие слова
                stopwords = {'med', 'og', 'til', 'i', 'en', 'et', 'af', 'for', 'på'}
                tags = [word for word in words if word not in stopwords and len(word) > 2]
        
        return ', '.join(tags[:5]) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if url not in urls:
                urls.append(url)
        
        # 3. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Обрабатываем @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict):
                            # ImageObject
                            if item.get('@type') == 'ImageObject' and 'url' in item:
                                url = item['url']
                                if url not in urls:
                                    urls.append(url)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        
        # Возвращаем первые 3 изображения через запятую
        if urls:
            unique_urls = []
            for url in urls:
                if url and url not in unique_urls:
                    unique_urls.append(url)
                    if len(unique_urls) >= 3:
                        break
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
    # Обрабатываем папку preprocessed/superbrugsenspentrup_dk
    preprocessed_dir = os.path.join("preprocessed", "superbrugsenspentrup_dk")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(SuperbrugsenspentrupExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python superbrugsenspentrup_dk.py")


if __name__ == "__main__":
    main()
