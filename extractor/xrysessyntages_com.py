"""
Экстрактор данных рецептов для сайта xrysessyntages.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class XrysessyntagesExtractor(BaseRecipeExtractor):
    """Экстрактор для xrysessyntages.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта
        recipe_header = self.soup.find('h1', class_='tdb-title-text')
        if recipe_header:
            return self.clean_text(recipe_header.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем суффикс " | Απλές και νόστιμες συνταγές"
            title = re.sub(r'\s*\|.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в блоке с описанием после заголовка
        # Часто находится в параграфе перед "ΥΛΙΚΑ"
        content_div = self.soup.find('div', class_=re.compile(r'tdb-block-inner'))
        
        if content_div:
            paragraphs = content_div.find_all('p')
            for p in paragraphs:
                text = p.get_text(strip=True)
                # Ищем параграф, который не содержит "ΥΛΙΚΑ" или "ΕΚΤΕΛΕΣΗ"
                if text and 'ΥΛΙΚΑ' not in text and 'ΕΚΤΕΛΕΣΗ' not in text:
                    # Если параграф не начинается с числа или специальных символов
                    # и содержит достаточно текста для описания
                    if len(text) > 20 and not re.match(r'^\d', text):
                        cleaned = self.clean_text(text)
                        # Проверяем, что это не часть ингредиентов
                        if cleaned and not any(word in cleaned.lower() for word in ['κουταλιά', 'γρ.', 'κουταλάκι']):
                            return cleaned
        
        # Альтернативно - из meta description (но может содержать ингредиенты)
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Если в meta description есть только ингредиенты, пропускаем
            if 'ΥΛΙΚΑ' in desc or len(desc) > 200:
                return None
            return self.clean_text(desc)
        
        return None
    
    def parse_ingredient_line(self, line: str) -> Optional[Dict[str, any]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            line: Строка вида "1 κουταλиά µπιζέλια" или "½ µέτρια πατάτα"
            
        Returns:
            dict: {"name": "μπιζέλια", "units": "κουταλιά", "amount": 1} или None
        """
        if not line or len(line.strip()) < 2:
            return None
        
        line = self.clean_text(line).strip()
        
        # Заменяем Unicode дроби на числа ПЕРЕД нормализацией
        # (так как NFKC превращает ½ в 1⁄2, что усложняет парсинг)
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            line = line.replace(fraction, decimal)
        
        # Нормализуем Unicode (например, µ -> μ)
        import unicodedata
        line = unicodedata.normalize('NFKC', line)
        
        # Пропускаем заголовки секций
        if line.endswith(':') or 'Για τη' in line or 'Για το' in line:
            return None
        
        # Паттерн для греческих единиц измерения
        # Ищем количество (число или дробь), затем единицу, затем название
        pattern = r'^([\d\s/.,]+)?\s*(κουταλιά|κουταλάκι|κουταλιές|κουταλάκια|γρ\.?|γραμμάρια?|κιλό|λίτρο|ml|λίτρα|φλιτζάνι|φλιτζάνια|μέτρια|μεγάλη|μεγάλο|μικρή|μικρό|κομμάτι|κομμάτια|φέτες?|σκελίδες?|δέσμη|δέσμες|ολόκληρη|ολόκληρο|μισή|μισό|τεταρτημόρι|τεμάχι|τεμάχια)?\s*(.+)?$'
        
        match = re.match(pattern, line, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            # Но проверяем, что это не пустая строка
            if line and len(line) > 1:
                return {
                    "name": line,
                    "units": None,
                    "amount": None
                }
            return None
        
        amount_str, units, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2" или "1/4"
            if '/' in amount_str:
                try:
                    parts = amount_str.split()
                    total = 0.0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            total += float(part.replace(',', '.'))
                    # Конвертируем в int если это целое число
                    amount = int(total) if total.is_integer() else total
                except (ValueError, ZeroDivisionError):
                    amount = None
            else:
                try:
                    val = float(amount_str.replace(',', '.'))
                    # Конвертируем в int если это целое число
                    amount = int(val) if val.is_integer() else val
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения
        units = units.strip() if units else None
        
        # Очистка названия
        if name:
            name = name.strip()
            # Удаляем скобки с содержимым
            name = re.sub(r'\([^)]*\)', '', name)
            # Удаляем фразы "για το τηγάνισµα", "για την εξυπηρέτηση" и т.д.
            name = re.sub(r'\bγια το\b.*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\bγια την\b.*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\bγια τη\b.*$', '', name, flags=re.IGNORECASE)
            # Удаляем лишние пробелы
            name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        # Возвращаем в правильном порядке: name, units, amount
        return {
            "name": name,
            "units": units,
            "amount": amount
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате JSON"""
        ingredients = []
        
        # Ищем параграф с "ΥΛΙΚΑ" во всех параграфах
        paragraphs = self.soup.find_all('p')
        
        for p in paragraphs:
            # Проверяем, содержит ли параграф "ΥΛΙΚΑ"
            if 'ΥΛΙΚΑ' in p.get_text():
                # Извлекаем текст и разбиваем по <br> тегам
                # Используем separator для сохранения структуры
                html_content = str(p)
                # Заменяем <br> на специальный маркер
                html_content = html_content.replace('<br>', '\n')
                html_content = html_content.replace('<br/>', '\n')
                html_content = html_content.replace('<br />', '\n')
                
                # Парсим обратно через BeautifulSoup чтобы удалить теги
                from bs4 import BeautifulSoup
                temp_soup = BeautifulSoup(html_content, 'lxml')
                text = temp_soup.get_text()
                
                # Разбиваем по новым строкам
                lines = text.split('\n')
                
                for line in lines:
                    line = line.strip()
                    if line and 'ΥΛΙΚΑ' not in line:
                        # Парсим ингредиент
                        parsed = self.parse_ingredient_line(line)
                        if parsed:
                            ingredients.append(parsed)
                
                if ingredients:
                    break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        # Ищем параграф с "ΕΚΤΕΛΕΣΗ" или инструкциями
        paragraphs = self.soup.find_all('p')
        
        for i, p in enumerate(paragraphs):
            text = p.get_text(separator=' ', strip=True)
            
            # Ищем параграф с "ΕΚΤΕΛΕΣΗ"
            if 'ΕΚΤΕΛΕΣΗ' in text:
                # Убираем "ΕΚΤΕΛΕΣΗ" и возвращаем остаток
                instructions_text = re.sub(r'ΕΚΤΕΛΕΣΗ\s*', '', text, flags=re.IGNORECASE)
                instructions_text = self.clean_text(instructions_text)
                
                if instructions_text and len(instructions_text) > 20:
                    return instructions_text
        
        # Если не нашли по "ΕΚΤΕΛΕΣΗ", ищем параграф после ингредиентов
        # который достаточно длинный
        found_ingredients = False
        for p in paragraphs:
            p_text = p.get_text()
            
            if 'ΥΛΙΚΑ' in p_text:
                found_ingredients = True
                continue
            
            if found_ingredients:
                text = p.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                # Проверяем, что это инструкции (длинный текст)
                # и не содержит копирайт или другую служебную информацию
                if (text and len(text) > 50 and 
                    not any(word in text.lower() for word in ['copyright', 'powered by', 'γρ.', 'κουταλιά']) and
                    not text.startswith('TAYTOTHTA')):
                    return text
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в ссылке с классом tdb-entry-category
        category_link = self.soup.find('a', class_='tdb-entry-category')
        if category_link:
            category = category_link.get_text(strip=True)
            # Переводим греческие категории на английский
            category_map = {
                'ΦΑΓΗΤΑ': 'Main Course',
                'ΓΛΥΚΑ': 'Dessert',
                'ΣΑΛΑΤΕΣ': 'Salad',
                'ΟΡΕΚΤΙΚΑ': 'Appetizer',
                'ΣΟΥΠΕΣ': 'Soup',
                'ΠΟΤΑ': 'Drink',
                'ΖΥΜΑΡΙΚΑ': 'Pasta'
            }
            return category_map.get(category.upper(), category)
        
        # Альтернативно - из URL структуры
        # URL вида: /syntages/fagita/dish-name/
        breadcrumbs = self.soup.find('div', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                category = links[-1].get_text(strip=True)
                return self.clean_text(category)
        
        return None
    
    def extract_time_field(self, field_name: str) -> Optional[str]:
        """
        Извлечение временных полей
        На сайте xrysessyntages.com время обычно не указано в структурированном виде
        """
        # Ищем в тексте упоминания времени
        content_div = self.soup.find('div', class_=re.compile(r'tdb-block-inner'))
        
        if content_div:
            text = content_div.get_text()
            
            # Паттерны для поиска времени
            time_patterns = {
                'cook_time': [
                    r'ψήνουμε.*?(\d+)\s*(λεπτά|minutes|λεπτό)',
                    r'μαγειρεύουμε.*?(\d+)\s*(λεπτά|minutes|λεπτό)',
                    r'για\s*(\d+)\s*(λεπτά|minutes|λεπτό)'
                ],
                'prep_time': [
                    r'προετοιμασία.*?(\d+)\s*(λεπτά|minutes|λεπτό)'
                ],
                'total_time': [
                    r'συνολικό.*?(\d+)\s*(λεπτά|minutes|λεπτό)'
                ]
            }
            
            if field_name in time_patterns:
                for pattern in time_patterns[field_name]:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        minutes = match.group(1)
                        return f"{minutes} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time_field('prep_time')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time_field('cook_time')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time_field('total_time')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # На сайте xrysessyntages.com обычно нет отдельной секции с заметками
        # Заметки могут быть в конце инструкций или в отдельном параграфе
        
        content_div = self.soup.find('div', class_=re.compile(r'tdb-block-inner'))
        
        if content_div:
            paragraphs = content_div.find_all('p')
            
            # Ищем параграф после инструкций
            found_instructions = False
            for p in paragraphs:
                text = p.get_text(strip=True)
                
                # Проверяем, это инструкции
                if len(text) > 100 and 'Ζεσταίνετε' in text or 'Προσθέτε' in text or 'Ετοιμάζετε' in text:
                    found_instructions = True
                    continue
                
                # Если нашли инструкции, следующий параграф может быть заметками
                if found_instructions and text and len(text) > 20:
                    # Проверяем, что это не социальные кнопки или другая служебная информация
                    if not any(word in text.lower() for word in ['share', 'facebook', 'twitter', 'pinterest']):
                        return self.clean_text(text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем теги в meta keywords или в специальных блоках
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        # Ищем теги в div с классом tags или post-tags
        tags_div = self.soup.find('div', class_=re.compile(r'tag', re.I))
        if tags_div:
            tags = []
            tag_links = tags_div.find_all('a')
            for link in tag_links:
                tag_text = link.get_text(strip=True)
                if tag_text:
                    tags.append(tag_text)
            
            if tags:
                return ', '.join(tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в meta og:image (главное изображение)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем изображения в content
        content_div = self.soup.find('div', class_=re.compile(r'tdb-block-inner'))
        if content_div:
            images = content_div.find_all('img', class_=re.compile(r'entry-thumb|wp-post-image'))
            for img in images:
                # Проверяем src и data-src
                src = img.get('src') or img.get('data-src')
                if src and src.startswith('http'):
                    urls.append(src)
        
        # 3. Ищем в preload link
        preload_link = self.soup.find('link', rel='preload', attrs={'as': 'image'})
        if preload_link and preload_link.get('href'):
            urls.append(preload_link['href'])
        
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
            Словарь с данными рецепта, содержащий все обязательные поля
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
    """
    Точка входа для обработки HTML файлов xrysessyntages.com
    """
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "preprocessed",
        "xrysessyntages_com"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка файлов из директории: {preprocessed_dir}")
        process_directory(XrysessyntagesExtractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python xrysessyntages_com.py")


if __name__ == "__main__":
    main()
