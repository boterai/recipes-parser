"""
Экстрактор данных рецептов для сайта food2u.co.il
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class Food2uExtractor(BaseRecipeExtractor):
    """Экстрактор для food2u.co.il"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            text = og_title['content']
            # Убираем суффиксы типа " - Food2U", "מתכון ל...", "» פוד טו יו"
            text = re.sub(r'\s*[-–»]\s*(Food2U|פוד טו יו).*$', '', text, flags=re.IGNORECASE)
            text = re.sub(r'^מתכון\s+(ל|להכנת|להכנה\s*של)\s*', '', text)
            text = re.sub(r'^הכנת\s+', '', text)
            text = re.sub(r'^הכנה\s*של\s+', '', text)
            return self.clean_text(text)
        
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            text = self.clean_text(h1.get_text())
            if text:
                text = re.sub(r'^מתכון\s+(ל|להכנת|להכנה\s*של)\s*', '', text)
                text = re.sub(r'^הכנת\s+', '', text)
                text = re.sub(r'^הכנה\s*של\s+', '', text)
                return text
        
        # Альтернативно - из title тега
        title = self.soup.find('title')
        if title:
            text = title.get_text()
            text = re.sub(r'\s*[-–»]\s*(Food2U|פוד טו יו).*$', '', text, flags=re.IGNORECASE)
            text = re.sub(r'^מתכון\s+(ל|להכנת|להכנה\s*של)\s*', '', text)
            text = re.sub(r'^הכנת\s+', '', text)
            text = re.sub(r'^הכנה\s*של\s+', '', text)
            text = self.clean_text(text)
            if text:
                return text
        
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
        
        # Ищем первый параграф после заголовка
        content_div = self.soup.find('div', class_=re.compile(r'post-content|entry-content|elementor-widget-theme-post-content', re.I))
        if content_div:
            # Ищем первый параграф, который не является заголовком
            paragraphs = content_div.find_all('p')
            for p in paragraphs:
                text = self.clean_text(p.get_text())
                # Проверяем, что это не слишком короткий текст и не заголовок
                if text and len(text) > 20 and not text.endswith(':'):
                    return text
        
        return None
    
    def parse_ingredient_text(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат для Hebrew text
        
        Args:
            ingredient_text: Строка вида "2 כוסות קוסקוס" или "500 גרם בשר טחון"
            
        Returns:
            dict: {"name": "קוסקוס", "amount": 2, "unit": "כוסות"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Формат: [число] [единица] [название] (для иврита)
        # Примеры: "2 כוסות קוסקוס", "500 גרם בשר", "מלח לפי הטעם"
        
        # Сначала пробуем извлечь число в начале
        number_match = re.match(r'^([\d.,/]+)\s+(.+)$', text)
        
        if number_match:
            amount_str = number_match.group(1)
            rest = number_match.group(2)
            
            # Обработка дробей типа "1/2"
            if '/' in amount_str:
                parts = amount_str.split('/')
                if len(parts) == 2:
                    try:
                        amount = float(parts[0]) / float(parts[1])
                    except (ValueError, ZeroDivisionError):
                        amount = amount_str
                else:
                    amount = amount_str
            else:
                try:
                    # Пробуем конвертировать в число
                    if '.' in amount_str or ',' in amount_str:
                        amount = float(amount_str.replace(',', '.'))
                    else:
                        amount_num = int(amount_str)
                        # Сохраняем как int, если это целое число
                        amount = amount_num
                except ValueError:
                    amount = amount_str
            
            # Теперь пытаемся извлечь единицу измерения
            # Общие Hebrew единицы: כוסות, כפות, כף, גרם, ק"ג, ליטר, מ"ל, יחידה, יחידות, חופן
            unit_patterns = [
                r'^(כוסות|כוס|כפות|כף|כפית|כפיות|גרם|ק"ג|קילוגרם|ליטר|מ"ל|מיליליטר|יחידה|יחידות|חופן|חופנים)\s+(.+)$',
            ]
            
            unit = None
            name = rest
            
            for pattern in unit_patterns:
                unit_match = re.match(pattern, rest)
                if unit_match:
                    unit = unit_match.group(1)
                    name = unit_match.group(2)
                    break
            
            # Очистка названия от фраз "לפי הטעם", "(אופציונלי)" и т.д.
            name = re.sub(r'\s*\(אופציונלי\)', '', name)
            name = re.sub(r'\s*(לפי הטעם|לפי הצורך|אופציונלי|לקישוט)$', '', name)
            name = self.clean_text(name)
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        else:
            # Если нет числа в начале, это может быть "מלח לפי הטעם"
            # Проверяем, есть ли "לפי הטעם" в конце
            if 'לפי הטעם' in text:
                # Извлекаем название без "לפי הטעם"
                name = re.sub(r'\s*לפי הטעם\s*', '', text)
                name = self.clean_text(name)
                return {
                    "name": name,
                    "amount": None,
                    "units": "לפי הטעם"
                }
            
            # Ищем единицу без количества
            unit_patterns = [
                r'^(כוסות|כוס|כפות|כף|כפית|כפיות|גרם|ק"ג|קילוגרם|ליטר|מ"ל|מיליליטר|יחידה|יחידות|חופן|חופנים)\s+(.+)$',
            ]
            
            for pattern in unit_patterns:
                unit_match = re.match(pattern, text)
                if unit_match:
                    unit_or_phrase = unit_match.group(1)
                    name = unit_match.group(2)
                    name = re.sub(r'\s*\(אופציונלי\)', '', name)
                    name = self.clean_text(name)
                    return {
                        "name": name,
                        "amount": None,
                        "units": unit_or_phrase
                    }
            
            # Если ничего не подошло, возвращаем только название
            name = re.sub(r'\s*\(אופציונלי\)', '', text)
            name = self.clean_text(name)
            return {
                "name": name,
                "amount": None,
                "units": None
            }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем заголовок "מרכיבים:" (Ингредиенты)
        content_div = self.soup.find('div', class_=re.compile(r'post-content|entry-content|elementor-widget-theme-post-content', re.I))
        
        if content_div:
            # Ищем все заголовки h2/h3 и параграфы
            headers = content_div.find_all(['h2', 'h3'])
            
            for header in headers:
                header_text = self.clean_text(header.get_text())
                
                # Проверяем, что это заголовок ингредиентов
                if header_text and ('מרכיבים' in header_text or 'מצרכים' in header_text):
                    # Ищем следующий ul или ol список после заголовка
                    next_elem = header.find_next_sibling()
                    
                    while next_elem:
                        if next_elem.name in ['ul', 'ol']:
                            # Нашли список ингредиентов
                            items = next_elem.find_all('li')
                            
                            for item in items:
                                ingredient_text = self.clean_text(item.get_text())
                                
                                if ingredient_text:
                                    parsed = self.parse_ingredient_text(ingredient_text)
                                    if parsed:
                                        ingredients.append(parsed)
                            
                            break
                        elif next_elem.name == 'p':
                            # Проверяем, есть ли в параграфе "מצרכים:" или список с <br>
                            p_text = next_elem.get_text()
                            if 'מצרכים:' in p_text:
                                # Извлекаем ингредиенты из параграфа, разделенного <br>
                                # Разбиваем по <br> тегам
                                lines = []
                                for content in next_elem.children:
                                    if content.name == 'br':
                                        continue
                                    elif isinstance(content, str):
                                        lines.append(content.strip())
                                
                                # Объединяем строки, разделенные br
                                full_text = str(next_elem).replace('<br>', '\n').replace('<br/>', '\n')
                                from bs4 import BeautifulSoup
                                temp_soup = BeautifulSoup(full_text, 'lxml')
                                text = temp_soup.get_text()
                                
                                # Разбиваем по переносам строк
                                lines = text.split('\n')
                                
                                # Пропускаем первую строку если это "מצרכים:"
                                for line in lines:
                                    line = self.clean_text(line)
                                    if line and line != 'מצרכים:' and len(line) > 3:
                                        parsed = self.parse_ingredient_text(line)
                                        if parsed:
                                            ingredients.append(parsed)
                                
                                break
                            next_elem = next_elem.find_next_sibling()
                        elif next_elem.name in ['h2', 'h3']:
                            # Дошли до следующего заголовка, прекращаем поиск
                            break
                        else:
                            next_elem = next_elem.find_next_sibling()
                    
                    # Если нашли ингредиенты, выходим
                    if ingredients:
                        break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        instructions = []
        
        # Ищем заголовок "הוראות הכנה:" или подобный
        content_div = self.soup.find('div', class_=re.compile(r'post-content|entry-content|elementor-widget-theme-post-content', re.I))
        
        if content_div:
            # Сначала проверяем, есть ли параграф с "אופן ההכנה:" напрямую (как в lasagna)
            all_paragraphs = content_div.find_all('p')
            for p in all_paragraphs:
                p_text = p.get_text()
                if 'אופן ההכנה:' in p_text or ('הוראות' in p_text and ':' in p_text):
                    # Извлекаем инструкции из параграфа, разделенного <br>
                    full_text = str(p).replace('<br>', '\n').replace('<br/>', '\n')
                    from bs4 import BeautifulSoup
                    temp_soup = BeautifulSoup(full_text, 'lxml')
                    text = temp_soup.get_text()
                    
                    # Убираем заголовок "אופן ההכנה:" если есть
                    text = re.sub(r'^אופן ההכנה:\s*', '', text)
                    text = re.sub(r'^הוראות הכנה:\s*', '', text)
                    
                    # Берем текст как одну инструкцию
                    text = self.clean_text(text)
                    if text and len(text) > 10:
                        instructions.append(text)
                    
                    # Найдено, выходим
                    if instructions:
                        return ' '.join(instructions) if instructions else None
            
            # Если не нашли напрямую, ищем все заголовки h2/h3
            headers = content_div.find_all(['h2', 'h3'])
            
            for header in headers:
                header_text = self.clean_text(header.get_text())
                
                # Проверяем, что это заголовок инструкций
                if header_text and ('הוראות' in header_text or 'הכנה' in header_text):
                    # Собираем все параграфы после заголовка до следующего h2/h3
                    next_elem = header.find_next_sibling()
                    step_num = 1
                    
                    while next_elem:
                        if next_elem.name == 'p':
                            text = self.clean_text(next_elem.get_text())
                            
                            if text and len(text) > 10:
                                # Убираем жирный текст заголовка шага, если есть
                                # Например: "<strong>הכנת הקוסקוס:</strong> מעבירים..."
                                text = re.sub(r'^[^:]+:\s*', '', text)
                                
                                # Добавляем нумерацию, если её нет
                                if not re.match(r'^\d+\.', text):
                                    text = f"{step_num}. {text}"
                                    step_num += 1
                                
                                instructions.append(text)
                        
                        elif next_elem.name in ['ol', 'ul']:
                            # Если инструкции в виде списка
                            items = next_elem.find_all('li')
                            for item in items:
                                text = self.clean_text(item.get_text())
                                if text:
                                    if not re.match(r'^\d+\.', text):
                                        text = f"{step_num}. {text}"
                                        step_num += 1
                                    instructions.append(text)
                        
                        elif next_elem.name in ['h2', 'h3']:
                            # Дошли до следующего заголовка
                            break
                        
                        next_elem = next_elem.find_next_sibling()
                    
                    # Если нашли инструкции, выходим
                    if instructions:
                        break
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в meta article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в хлебных крошках (breadcrumbs)
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                # Берем предпоследнюю категорию
                return self.clean_text(links[-2].get_text())
        
        # Ищем в классах категорий
        content = self.soup.find('div', class_=re.compile(r'category-'))
        if content:
            classes = content.get('class', [])
            for cls in classes:
                if cls.startswith('category-') and cls != 'category-food':
                    # Извлекаем название категории из класса
                    cat_name = cls.replace('category-', '').replace('-', ' ')
                    return self.clean_text(cat_name)
        
        return None
    
    def extract_time_from_text(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени из текста инструкций
        
        Args:
            time_type: 'prep', 'cook', or 'total'
        """
        # Ищем время в тексте инструкций
        content_div = self.soup.find('div', class_=re.compile(r'post-content|entry-content|elementor-widget-theme-post-content', re.I))
        
        if not content_div:
            return None
        
        # Получаем весь текст контента
        text = content_div.get_text()
        
        # Паттерны для поиска времени в минутах
        # Примеры: "5-10 דקות", "35 דקות", "כ-35 דקות"
        time_patterns = [
            r'(\d+)-(\d+)\s*דקות',  # "5-10 דקות"
            r'כ-(\d+)\s*דקות',      # "כ-35 דקות" (около X минут)
            r'(\d+)\s*דקות',        # "35 דקות"
        ]
        
        for pattern in time_patterns:
            matches = re.findall(pattern, text)
            if matches:
                # Берем первое совпадение
                match = matches[0]
                if isinstance(match, tuple):
                    # Для паттернов с диапазоном или "около"
                    if len(match) == 2:
                        # Берем среднее значение для диапазона
                        try:
                            avg = (int(match[0]) + int(match[1])) / 2
                            return f"{int(avg)} minutes"
                        except ValueError:
                            pass
                    elif len(match) == 1:
                        return f"{match[0]} minutes"
                else:
                    return f"{match} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time_from_text('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time_from_text('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time_from_text('total')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем параграфы с советами после основных инструкций
        content_div = self.soup.find('div', class_=re.compile(r'post-content|entry-content|elementor-widget-theme-post-content', re.I))
        
        if content_div:
            # Ищем заголовок инструкций
            headers = content_div.find_all(['h2', 'h3'])
            found_instructions = False
            
            for header in headers:
                header_text = self.clean_text(header.get_text())
                
                if header_text and ('הוראות' in header_text or 'הכנה' in header_text):
                    found_instructions = True
                    # Ищем параграфы после инструкций, которые могут быть заметками
                    next_elem = header.find_next_sibling()
                    paragraphs_after_instructions = []
                    
                    while next_elem:
                        if next_elem.name == 'p':
                            paragraphs_after_instructions.append(next_elem)
                        elif next_elem.name in ['h2', 'h3']:
                            break
                        next_elem = next_elem.find_next_sibling()
                    
                    # Берем последний параграф после инструкций как заметку
                    if paragraphs_after_instructions:
                        for p in reversed(paragraphs_after_instructions):
                            text = self.clean_text(p.get_text())
                            # Проверяем, что это не шаг инструкции
                            if text and len(text) > 20 and not re.match(r'^\d+\.', text):
                                # Проверяем, что параграф содержит советы/рекомендации
                                if any(word in text for word in ['כדי', 'ניתן', 'מומלץ', 'טיפ', 'שדרג']):
                                    return text
                    
                    break
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        # Ищем в классах категорий и тегах
        tags = []
        
        # Проверяем article:tag meta теги
        article_tags = self.soup.find_all('meta', property='article:tag')
        for tag in article_tags:
            if tag.get('content'):
                tags.append(self.clean_text(tag['content']))
        
        if tags:
            return ', '.join(tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в meta twitter:image
        twitter_image = self.soup.find('meta', {'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Ищем изображения в контенте
        content_div = self.soup.find('div', class_=re.compile(r'post-content|entry-content|elementor-widget-theme-post-content', re.I))
        if content_div:
            images = content_div.find_all('img')
            for img in images[:3]:  # Берем первые 3 изображения из контента
                src = img.get('src') or img.get('data-src')
                if src and src.startswith('http'):
                    urls.append(src)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        return ','.join(unique_urls) if unique_urls else None
    
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
    """Обработка всех HTML файлов в директории preprocessed/food2u_co_il"""
    import os
    
    # Путь к директории с preprocessed файлами
    preprocessed_dir = os.path.join("preprocessed", "food2u_co_il")
    
    # Проверяем существование директории
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(Food2uExtractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python food2u_co_il.py")


if __name__ == "__main__":
    main()
