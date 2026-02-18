"""
Экстрактор данных рецептов для сайта syntagesmou.gr
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class SyntagesmouGrExtractor(BaseRecipeExtractor):
    """Экстрактор для syntagesmou.gr"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Альтернативно - из h1
        h1_title = self.soup.find('h1', class_='post-title')
        if h1_title:
            return self.clean_text(h1_title.get_text())
        
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
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем секцию с заголовком "Υλικά" (Ingredients)
        post_body = self.soup.find('div', class_='post-body')
        if not post_body:
            return None
        
        # Ищем все заголовки h2
        headers = post_body.find_all('h2')
        for header in headers:
            header_text = header.get_text(strip=True)
            # Проверяем, является ли это заголовком ингредиентов
            if re.match(r'Υλικά', header_text, re.IGNORECASE):
                # Ищем следующий ul после заголовка
                next_element = header.find_next_sibling()
                while next_element:
                    if next_element.name == 'ul':
                        # Нашли список ингредиентов
                        items = next_element.find_all('li')
                        for item in items:
                            ingredient_text = item.get_text(strip=True)
                            ingredient_text = self.clean_text(ingredient_text)
                            
                            if ingredient_text:
                                parsed = self.parse_ingredient(ingredient_text)
                                if parsed:
                                    ingredients.append(parsed)
                        break
                    elif next_element.name in ['h2', 'h3', 'hr']:
                        # Достигли следующей секции
                        break
                    next_element = next_element.find_next_sibling()
                break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 κεσεδάκι γιαούρτι στραγγιστό (200 γρ.)"
            
        Returns:
            dict: {"name": "γιαούρτι στραγγιστό", "amount": "1", "units": "κεσεδάκι"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
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
        
        # Извлекаем информацию в скобках (обычно там вес в граммах)
        extra_info = None
        paren_match = re.search(r'\(([^)]+)\)', text)
        if paren_match:
            extra_info = paren_match.group(1)
            # Убираем скобки из основного текста
            text = re.sub(r'\([^)]*\)', '', text).strip()
        
        # Паттерн для извлечения количества, единицы и названия
        # Греческие единицы измерения: κεσεδάκι(α), κουταλιά, φακελάκι, γρ., κιλό, ml, etc.
        pattern = r'^([\d\s/.,]+)?\s*(κεσεδάκι[αο]?|κεσεδάκια|κουταλι[άέ]ς?|κουταλιές|κουταλιά|φακελάκι[οα]?|γρ\.?|κιλ[όο]ά?|ml|l|λίτρ[οα]|χούφτα|φλιτζάνι[αο]?|φέτες?|κομμάτι[αο]?|φύλλ[οα]|ματσάκι|πρέζα|τεμάχι[αο]?|cups?|tablespoons?|teaspoons?|tbsps?|tsps?|grams?|kilograms?|g|kg|milliliters?|liters?|oz|pounds?|lbs?)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "unit": None
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
                amount = str(total) if total > 0 else None
            else:
                amount = amount_str.replace(',', '.')
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем фразы "προαιρετικά" (optional), и т.д.
        name = re.sub(r'\b(προαιρετικ[άήό]ς?|ή|για την επικάλυψη|για το γλάσο)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        # Если есть дополнительная информация (из скобок), можем добавить в название или в unit
        # Например, "(200 γρ.)" можно использовать для amount/unit если основных нет
        if extra_info and not amount:
            # Пробуем извлечь количество из скобок
            extra_match = re.match(r'([\d.,]+)\s*(γρ\.?|g|κιλό|kg|ml|l)?', extra_info, re.IGNORECASE)
            if extra_match:
                amount = extra_match.group(1).replace(',', '.')
                if extra_match.group(2) and not unit:
                    unit = extra_match.group(2)
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount if amount else None,
            "unit": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем секцию с заголовком "Εκτέλεση" (Instructions/Execution)
        post_body = self.soup.find('div', class_='post-body')
        if not post_body:
            return None
        
        # Ищем все заголовки h2
        headers = post_body.find_all('h2')
        for header in headers:
            header_text = header.get_text(strip=True)
            # Проверяем, является ли это заголовком инструкций
            if re.match(r'Εκτέλεση|Οδηγίες|Παρασκευή', header_text, re.IGNORECASE):
                # Ищем следующий ol после заголовка
                next_element = header.find_next_sibling()
                while next_element:
                    if next_element.name == 'ol':
                        # Нашли список инструкций
                        items = next_element.find_all('li')
                        for item in items:
                            step_text = item.get_text(separator=' ', strip=True)
                            step_text = self.clean_text(step_text)
                            if step_text:
                                steps.append(step_text)
                        break
                    elif next_element.name in ['h2', 'h3', 'hr']:
                        # Достигли следующей секции
                        break
                    next_element = next_element.find_next_sibling()
                break
        
        return ' '.join(steps) if steps else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем секцию с метками (labels)
        post_labels = self.soup.find('div', class_='post-labels')
        if post_labels:
            # Ищем все ссылки на метки
            label_links = post_labels.find_all('a', class_='label-link')
            for link in label_links:
                tag = link.get_text(strip=True)
                tag = self.clean_text(tag)
                if tag:
                    tags.append(tag)
        
        return ', '.join(tags) if tags else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории из тегов"""
        # Получаем первый тег как категорию
        tags = self.extract_tags()
        if tags:
            # Берем первый тег
            first_tag = tags.split(',')[0].strip()
            return first_tag
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки из инструкций"""
        # Время часто указывается в тексте инструкций
        instructions_text = self.extract_instructions()
        if not instructions_text:
            return None
        
        # Ищем паттерны времени
        # Примеры: "40–45 λεπτά", "για 45 λεπτά", "1 ώρα"
        time_patterns = [
            r'(?:για\s+)?(\d+(?:–|-)\d+)\s*(?:λεπτ[άό]|minutes?)',
            r'(?:για\s+)?(\d+)\s*(?:λεπτ[άό]|minutes?)',
            r'(?:για\s+)?(\d+)\s*(?:[ώω]ρ(?:α|ες))',
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, instructions_text, re.IGNORECASE)
            if match:
                time_value = match.group(1)
                # Определяем единицу измерения
                if 'λεπτ' in match.group(0) or 'minute' in match.group(0):
                    return f"{time_value} minutes"
                elif 'ώρ' in match.group(0) or 'ωρ' in match.group(0):
                    return f"{time_value} hours"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # В syntagesmou.gr обычно нет отдельного prep_time
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # В syntagesmou.gr обычно нет отдельного total_time
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes_sections = []
        
        # Ищем только секцию "Συμβουλές για τέλειο αποτέλεσμα" (основные советы)
        post_body = self.soup.find('div', class_='post-body')
        if not post_body:
            return None
        
        # Заголовки секций с заметками (только основные советы)
        note_headers = [
            'Συμβουλές για τέλειο αποτέλεσμα',
            'Συμβουλές',
            'Σημειώσεις',
            'Tips',
            'Notes'
        ]
        
        headers = post_body.find_all('h2')
        for header in headers:
            header_text = header.get_text(strip=True)
            
            # Проверяем, является ли это секцией с основными советами
            if any(note_header in header_text for note_header in note_headers):
                # Собираем текст после заголовка до следующего h2 или hr
                next_element = header.find_next_sibling()
                section_text = []
                
                while next_element:
                    if next_element.name in ['h2', 'h3', 'hr']:
                        # Достигли следующей секции или разделителя
                        break
                    elif next_element.name in ['p', 'ul', 'ol']:
                        text = next_element.get_text(separator=' ', strip=True)
                        text = self.clean_text(text)
                        if text:
                            section_text.append(text)
                    
                    next_element = next_element.find_next_sibling()
                
                if section_text:
                    notes_sections.append(' '.join(section_text))
                break  # Берем только первую секцию с советами
        
        return ' '.join(notes_sections) if notes_sections else None
    

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем изображения в теле поста
        post_body = self.soup.find('div', class_='post-body')
        if post_body:
            # Ищем изображения в div с классом separator
            separators = post_body.find_all('div', class_='separator')
            for separator in separators:
                img = separator.find('img')
                if img and img.get('src'):
                    src = img['src']
                    # Проверяем, что это не дубликат
                    if src not in urls:
                        urls.append(src)
        
        # Убираем дубликаты и ограничиваем до 3 изображений
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
                if len(unique_urls) >= 3:
                    break
        
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
            "category": category,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "notes": notes,
            "tags": tags,
            "image_urls": image_urls
        }


def main():
    """Точка входа для обработки директории с HTML-страницами"""
    import os
    
    # Определяем путь к директории с HTML-страницами
    # Используем относительный путь от корня репозитория
    current_file = Path(__file__)
    repo_root = current_file.parent.parent
    preprocessed_dir = repo_root / "preprocessed" / "syntagesmou_gr"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(SyntagesmouGrExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python syntagesmou_gr.py")


if __name__ == "__main__":
    main()
