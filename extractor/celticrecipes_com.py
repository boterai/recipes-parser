"""
Экстрактор данных рецептов для сайта celticrecipes.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CelticRecipesExtractor(BaseRecipeExtractor):
    """Экстрактор для celticrecipes.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1', class_='post-title')
        if not h1:
            h1 = self.soup.find('h1', class_='is-title')
        
        if h1:
            title = self.clean_text(h1.get_text())
            # Убираем суффиксы вроде ": A Tasty Twist!" или "! - CelticRecipes"
            title = re.sub(r'[:\-!]\s*[A-Z][^!\-:]*[!\-:]?\s*$', '', title)
            title = re.sub(r'\s*-\s*CelticRecipes\s*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффикс сайта и подзаголовки
            title = re.sub(r'[:\-!]\s*[A-Z][^!\-:]*[!\-:]?\s*$', '', title)
            title = re.sub(r'\s*-\s*CelticRecipes\s*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Приоритет: параграф с ключевым описанием рецепта (начинается с "These" или содержит название)
        content = self.soup.find('div', class_=re.compile(r'post-content|entry-content'))
        if content:
            # Ищем параграфы
            paragraphs = content.find_all('p')
            for p in paragraphs:
                text = self.clean_text(p.get_text())
                # Ищем параграф, который начинается с "These" или "This" и содержит название блюда
                if text and len(text) > 50:
                    # Если начинается с "These/This [Dish Name]" - это основное описание
                    if re.match(r'^(These|This)\s+\S+', text, re.I):
                        # Извлекаем до первого маркера (обычно точка или дефис перед дополнительным текстом)
                        # Ищем первое предложение
                        sentences = re.split(r'[.!?]\s+', text)
                        if sentences:
                            first_sentence = sentences[0]
                            # Если первое предложение достаточно длинное, используем его
                            if len(first_sentence) > 80:
                                return first_sentence + '.'
                            # Иначе первые два предложения
                            elif len(sentences) > 1:
                                return sentences[0] + '. ' + sentences[1] + ('.' if not sentences[1].endswith('.') else '')
        
        # Альтернативно - из meta description  
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате JSON строки"""
        ingredients_list = []
        
        # Ищем контейнер с ингредиентами
        # Вариант 1: <div class="recipe-ingredients">
        ingredients_container = self.soup.find('div', class_=re.compile(r'recipe-ingredients'))
        
        if not ingredients_container:
            # Вариант 2: ищем по ul с классом ingredients-list
            ingredients_container = self.soup.find('ul', class_=re.compile(r'ingredients-list'))
        
        if not ingredients_container:
            # Вариант 3: ищем заголовок с "Ingredients" и берем следующий ul
            ing_header = self.soup.find(['h2', 'h3', 'h4'], string=re.compile(r'Ingredients?|Gather.*Ingredients', re.I))
            if ing_header:
                # Ищем следующий ul после заголовка
                sibling = ing_header.find_next_sibling()
                while sibling:
                    if sibling.name == 'ul':
                        ingredients_container = sibling
                        break
                    sibling = sibling.find_next_sibling()
        
        if ingredients_container:
            # Извлекаем список ингредиентов
            items = ingredients_container.find_all('li')
            
            for item in items:
                # Извлекаем текст ингредиента
                ingredient_text = item.get_text(separator=' ', strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                # Пропускаем пустые и заголовки секций
                if not ingredient_text or ingredient_text.endswith(':'):
                    continue
                
                # Парсим в структурированный формат
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients_list.append(parsed)
        
        if ingredients_list:
            return json.dumps(ingredients_list, ensure_ascii=False)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "2 cups kale" или "4 medium Potatoes"
            
        Returns:
            dict: {"name": "kale", "amount": 2, "units": "cups"} или None
        
        Note: Поле называется "units", не "unit" (по примеру из JSON)
        """
        if not ingredient_text:
            return None
        
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
        # Примеры: "2 cups kale", "4 medium potatoes", "1 tbsp butter"
        pattern = r'^([\d\s/.,]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads|wrappers?|medium|large|small|sprig)?\s*(.+)'
        
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
                # Преобразуем в int если это целое число
                amount = int(total) if total == int(total) else total
            else:
                try:
                    val = float(amount_str.replace(',', '.'))
                    amount = int(val) if val == int(val) else val
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения (units)
        units = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем leading/trailing разделители и пробелы
        name = re.sub(r'^[,:\-\s]+|[,:\-\s]+$', '', name)
        # Удаляем фразы "to taste", "as needed", "optional" только в конце
        name = re.sub(r',?\s*(to taste|as needed|or more|if needed|for frying|for garnish)\s*$', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        
        # Убираем "optional" из units если оно там оказалось, и переместим в конец name
        if units and re.search(r'optional', units, re.I):
            units = None
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions_paragraphs = []
        
        # Ищем только в основном контенте
        content = self.soup.find('div', class_=re.compile(r'post-content|entry-content'))
        if not content:
            return None
        
        # Ищем секцию с инструкциями по заголовку в контенте
        inst_header = content.find(['h2', 'h3'], string=re.compile(r'Step.*Guide|Instructions?|Method|Directions?', re.I))
        
        if inst_header:
            # Проверяем следующий элемент - может быть div с параграфами
            next_elem = inst_header.find_next_sibling()
            
            # Если следующий элемент - div, ищем параграфы внутри
            if next_elem and next_elem.name == 'div':
                paragraphs = next_elem.find_all('p')
                for p in paragraphs:
                    text = self.clean_text(p.get_text())
                    if text and len(text) > 20:
                        # Пропускаем заключительные параграфы
                        if re.match(r'^And there you have it|^Enjoy|^Happy cooking|Sláinte', text, re.I):
                            break
                        # Пропускаем вводные параграфы об ингредиентах
                        if not re.search(r'^To whip up|^To gather|^You\'ll need|^Check your', text, re.I):
                            instructions_paragraphs.append(text)
            else:
                # Иначе собираем siblings как раньше
                current = next_elem
                while current:
                    # Останавливаемся при следующем заголовке h2/h3
                    if current.name in ['h2', 'h3']:
                        break
                    
                    if current.name == 'p':
                        text = self.clean_text(current.get_text())
                        
                        if text and len(text) > 20:
                            # Пропускаем заключительные параграфы
                            if re.match(r'^And there you have it|^Enjoy|^Happy cooking|Sláinte', text, re.I):
                                break
                            # Пропускаем вводные параграфы об ингредиентах
                            if not re.search(r'^To whip up|^To gather|^You\'ll need|^Check your', text, re.I):
                                instructions_paragraphs.append(text)
                    
                    elif current.name in ['ol', 'ul']:
                        # Нумерованный или маркированный список инструкций
                        for idx, li in enumerate(current.find_all('li'), 1):
                            text = self.clean_text(li.get_text())
                            if text:
                                # Добавляем номер если его нет
                                if not re.match(r'^\d+\.', text):
                                    text = f"{idx}. {text}"
                                instructions_paragraphs.append(text)
                    
                    current = current.find_next_sibling()
        
        if instructions_paragraphs:
            return ' '.join(instructions_paragraphs)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Сначала пытаемся определить категорию по контексту
        content_text = ""
        content = self.soup.find('div', class_=re.compile(r'post-content|entry-content'))
        if content:
            content_text = content.get_text().lower()
        
        dish_name = self.extract_dish_name()
        if dish_name:
            dish_name = dish_name.lower()
        else:
            dish_name = ""
        
        # Определяем тип блюда по ключевым словам
        # Приоритет: bread > appetizer > main course > dessert
        if re.search(r'\b(bread|soda bread|baguette|loaf)\b', dish_name + " " + content_text):
            return "Bread"
        elif re.search(r'\b(appetizer|starter|spring rolls|snack|bite|canapé)\b', content_text):
            return "Appetizer"
        elif re.search(r'\b(dessert|cake|pudding|tart|pie|sweet)\b', dish_name + " " + content_text):
            return "Dessert"
        elif re.search(r'\b(main course|main dish|stew|coddle|casserole|roast|entre)\b', content_text):
            return "Main Course"
        
        # Если не удалось определить, используем JSON-LD category
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем @graph структуру
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list) and sections:
                                section = self.clean_text(sections[0])
                                # Извлекаем основной тип (до &)
                                section = re.sub(r'\s*&amp;\s*.*$', '', section)
                                section = re.sub(r'\s*&\s*.*$', '', section)
                                return section
                            elif isinstance(sections, str):
                                section = self.clean_text(sections)
                                section = re.sub(r'\s*&amp;\s*.*$', '', section)
                                section = re.sub(r'\s*&\s*.*$', '', section)
                                return section
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_time_from_text(self, text: str, time_type: str) -> Optional[str]:
        """
        Извлечение времени из текста
        
        Args:
            text: Текст для поиска
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        if not text:
            return None
        
        # Паттерны для разных типов времени
        patterns = {
            'prep': [
                r'prep(?:aration)?\s*(?:time)?[:\s]+(\d+(?:\s*-\s*\d+)?)\s*(minutes?|mins?|hours?|hrs?)',
            ],
            'cook': [
                r'cook(?:ing)?\s*(?:time)?[:\s]+(\d+(?:\s*-\s*\d+)?)\s*(minutes?|mins?|hours?|hrs?)',
                r'bake\s+for\s+(\d+(?:\s*-\s*\d+)?)\s*(minutes?|mins?|hours?|hrs?)',
            ],
            'total': [
                r'total\s*(?:time)?[:\s]+(\d+(?:\s*-\s*\d+)?)\s*(minutes?|mins?|hours?|hrs?)',
            ]
        }
        
        for pattern in patterns.get(time_type, []):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                amount = match.group(1)
                unit = match.group(2)
                return f"{amount} {unit}"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в тексте статьи и заголовках
        content = self.soup.find('div', class_=re.compile(r'post-content|entry-content'))
        if content:
            # Проверяем заголовки и следующие за ними параграфы
            for header in content.find_all(['h2', 'h3', 'h4', 'p']):
                text = header.get_text()
                prep_time = self.extract_time_from_text(text, 'prep')
                if prep_time:
                    return prep_time
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте статьи
        content = self.soup.find('div', class_=re.compile(r'post-content|entry-content'))
        if content:
            for header in content.find_all(['h2', 'h3', 'h4', 'p']):
                text = header.get_text()
                cook_time = self.extract_time_from_text(text, 'cook')
                if cook_time:
                    return cook_time
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в тексте статьи
        content = self.soup.find('div', class_=re.compile(r'post-content|entry-content'))
        if content:
            for header in content.find_all(['h2', 'h3', 'h4', 'p']):
                text = header.get_text()
                total_time = self.extract_time_from_text(text, 'total')
                if total_time:
                    return total_time
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с заметками только в основном контенте
        content = self.soup.find('div', class_=re.compile(r'post-content|entry-content'))
        if not content:
            return None
        
        # Вариант 1: ищем по заголовку "Notes" или "Tips"
        notes_header = content.find(['h2', 'h3', 'h4'], string=re.compile(r'Notes?|Tips?|Variations?|Substitutions?', re.I))
        
        if notes_header:
            # Собираем текст до следующего заголовка
            notes_text = []
            current = notes_header.find_next_sibling()
            while current:
                if current.name in ['h2', 'h3', 'h4']:
                    break
                
                if current.name == 'p':
                    text = self.clean_text(current.get_text())
                    if text:
                        notes_text.append(text)
                
                current = current.find_next_sibling()
            
            if notes_text:
                return ' '.join(notes_text)
        
        # Вариант 2: последние параграфы могут содержать заметки
        all_p = content.find_all('p')
        if all_p:
            # Проверяем последние несколько параграфов
            for p in reversed(all_p[-7:]):
                text = self.clean_text(p.get_text())
                # Ищем признаки заметок
                if text and len(text) > 40:
                    # Если начинается с "These" и содержит ключевые слова о пользе/особенностях рецепта
                    if re.match(r'^(These|This)\s+\w+\s+(is|are|make)', text, re.I):
                        if re.search(r'(not only.*but also|versatile|perfect (for|appetizer|side dish)|ready in|can (be )?substitute|you can|if you don\'?t have|healthier option)', text, re.I):
                            return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # В celticrecipes теги могут быть в meta keywords или в структуре статьи
        
        # Вариант 1: meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return meta_keywords['content']
        
        # Вариант 2: ищем теги в footer или sidebar
        tags_container = self.soup.find('div', class_=re.compile(r'tag|post-tag', re.I))
        if tags_container:
            tag_links = tags_container.find_all('a', rel='tag')
            if tag_links:
                tags = [self.clean_text(link.get_text()) for link in tag_links]
                return ', '.join(tags)
        
        # Вариант 3: категория может служить основным тегом
        category = self.extract_category()
        if category:
            # Добавляем базовые теги на основе категории и ключевых слов
            tags = [category]
            
            # Добавляем "Irish" если в названии или описании
            dish_name = self.extract_dish_name()
            if dish_name and 'irish' in dish_name.lower():
                tags.append('Irish')
            
            return ', '.join(tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            # Фильтруем SVG placeholders
            if not url.startswith('data:image/svg'):
                urls.append(url)
        
        # twitter:image
        twitter_image = self.soup.find('meta', {'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if not url.startswith('data:image/svg'):
                urls.append(url)
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем @graph структуру
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                url = item['url']
                                if not url.startswith('data:image/svg'):
                                    urls.append(url)
                            elif 'contentUrl' in item:
                                url = item['contentUrl']
                                if not url.startswith('data:image/svg'):
                                    urls.append(url)
                        
                        # Article с thumbnailUrl
                        elif item.get('@type') == 'Article' and 'thumbnailUrl' in item:
                            url = item['thumbnailUrl']
                            if not url.startswith('data:image/svg'):
                                urls.append(url)
                        
                        # Article с image
                        elif item.get('@type') == 'Article' and 'image' in item:
                            img = item['image']
                            if isinstance(img, dict):
                                if '@id' in img:
                                    # Ссылка на другой элемент в @graph
                                    continue
                                elif 'url' in img:
                                    url = img['url']
                                    if not url.startswith('data:image/svg'):
                                        urls.append(url)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 3. Ищем главное изображение в content
        content = self.soup.find('div', class_=re.compile(r'post-content|entry-content'))
        if content:
            # Ищем первое большое изображение
            img = content.find('img')
            if img and img.get('src'):
                src = img['src']
                # Проверяем, что это не маленькая иконка и не SVG placeholder
                if not re.search(r'icon|avatar|logo', src, re.I) and not src.startswith('data:image/svg'):
                    urls.append(src)
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            # Возвращаем как строку через запятую
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
    """Обработка директории с HTML файлами celticrecipes.com"""
    import os
    
    # Ищем директорию preprocessed/celticrecipes_com
    base_dir = Path(__file__).parent.parent
    recipes_dir = base_dir / "preprocessed" / "celticrecipes_com"
    
    if recipes_dir.exists() and recipes_dir.is_dir():
        print(f"Обработка директории: {recipes_dir}")
        process_directory(CelticRecipesExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python celticrecipes_com.py")


if __name__ == "__main__":
    main()
