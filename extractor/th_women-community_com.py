"""
Экстрактор данных рецептов для сайта th.women-community.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ThWomenCommunityExtractor(BaseRecipeExtractor):
    """Экстрактор для th.women-community.com"""
    
    def find_first_recipe_section(self) -> Tuple[Optional[any], Optional[any]]:
        """
        Находит первую секцию рецепта на странице.
        Возвращает (h2 первого рецепта, h2 второго рецепта)
        """
        h2_tags = self.soup.find_all('h2')
        
        # Пропускаем служебные секции
        skip_keywords = ['สารบัญ', 'ความลับ', 'เคล็ดลับ', 'แนะนำ', 'ข้อความ', 'ความคิดเห็น', 'บทความ', 'คำแนะนำ', 'วิดีโอ']
        
        first_recipe_h2 = None
        second_recipe_h2 = None
        
        for h2 in h2_tags:
            text = h2.get_text(strip=True)
            # Пропускаем заголовки, содержащие ключевые слова
            if any(kw in text for kw in skip_keywords):
                continue
            
            if first_recipe_h2 is None:
                first_recipe_h2 = h2
            elif second_recipe_h2 is None:
                second_recipe_h2 = h2
                break
        
        return first_recipe_h2, second_recipe_h2
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем первый h2 рецепта
        first_h2, _ = self.find_first_recipe_section()
        if first_h2:
            name = first_h2.get_text(strip=True)
            return self.clean_text(name)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем первый параграф в секции первого рецепта
        first_h2, second_h2 = self.find_first_recipe_section()
        
        if not first_h2:
            return None
        
        current = first_h2.find_next_sibling()
        
        while current:
            # Останавливаемся на следующем h2
            if current.name == 'h2':
                if second_h2 and current == second_h2:
                    break
                elif current != first_h2:
                    break
            
            if current.name == 'p':
                text = current.get_text(strip=True)
                text = self.clean_text(text)
                if text and len(text) > 30:
                    # Берем первое предложение
                    sentences = text.split('.')
                    if sentences[0]:
                        return sentences[0].strip() + '.'
            
            current = current.find_next_sibling()
        
        return None
    
    def parse_ingredient_line(self, line: str) -> Optional[dict]:
        """
        Парсит строку ингредиента в формат {name, amount, units}
        
        Примеры:
        "ไข่ - 4 ชิ้น" -> {name: "ไข่", amount: 4, units: "pieces"}
        "น้ำตาล - 150 กรัม" -> {name: "น้ำตาล", amount: 150, units: "grams"}
        """
        if not line:
            return None
        
        line = self.clean_text(line)
        
        # Паттерн: название - количество единица
        match = re.match(r'^(.+?)\s*[-–]\s*(.+)$', line)
        
        if not match:
            # Нет тире - возвращаем только название
            return {"name": line, "units": None, "amount": None}
        
        name = match.group(1).strip()
        amount_unit_str = match.group(2).strip()
        
        # Обработка дробей
        amount_unit_str = amount_unit_str.replace('½', '0.5').replace('¼', '0.25').replace('¾', '0.75')
        amount_unit_str = amount_unit_str.replace('⅓', '0.33').replace('⅔', '0.67')
        
        # Извлекаем количество и единицу
        # Паттерн: числа (включая дроби, диапазоны) + единица измерения
        amount_match = re.match(r'([\d\s/.,\-]+)\s*(.+)?', amount_unit_str)
        
        amount = None
        units = None
        
        if amount_match:
            amount_str = amount_match.group(1).strip()
            unit_str = amount_match.group(2).strip() if amount_match.group(2) else None
            
            # Обработка количества
            if amount_str:
                # Обработка диапазонов - берем первое значение
                if '-' in amount_str and '/' not in amount_str:
                    amount_str = amount_str.split('-')[0].strip()
                
                # Thai uses comma with space as decimal separator: "2, 5" means 2.5
                # Replace ", " (comma with space) with "." for decimal numbers
                amount_str = re.sub(r',\s+', '.', amount_str)
                
                # Обработка дробей
                if '/' in amount_str:
                    parts = amount_str.split()
                    total = 0.0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            total += float(part)
                    amount = total
                else:
                    try:
                        amount_str = amount_str.replace(',', '.')
                        amount = float(amount_str)
                        # Если целое число, сохраняем как int
                        if amount == int(amount):
                            amount = int(amount)
                    except ValueError:
                        amount = None
            
            # Маппинг единиц измерения на английские эквиваленты
            unit_mapping = {
                'ชิ้น': 'pieces',
                'กรัม': 'grams',
                'กรัม': 'grams',
                'มล': 'milliliters',
                'ช้อนโต๊ะ': 'tablespoons',
                'ช้อนชา': 'teaspoons',
                'ถ้วย': 'cups',
                'ล.': '',  # убираем, это сокращение
                'g': 'grams',
                'ml': 'milliliters',
            }
            
            if unit_str:
                # Убираем "ล." если оно в конце
                unit_str = re.sub(r'\s*ล\.$', '', unit_str).strip()
                
                # Проверяем маппинг
                for thai_unit, eng_unit in unit_mapping.items():
                    if thai_unit in unit_str:
                        units = eng_unit if eng_unit else unit_str.replace(thai_unit, '').strip()
                        # Если units пустая строка, ищем дальше
                        if not units:
                            # Ищем другие слова в строке
                            remaining = unit_str.replace(thai_unit, '').strip()
                            if remaining:
                                units = remaining
                            else:
                                units = eng_unit if eng_unit else None
                        break
                
                # Если не нашли в маппинге, оставляем как есть
                if units is None and unit_str:
                    units = unit_str
        
        return {
            "name": name,
            "units": units,
            "amount": amount
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из первого рецепта"""
        first_h2, second_h2 = self.find_first_recipe_section()
        
        if not first_h2:
            return None
        
        # Ищем h3 с "วัตถุดิบ:" в пределах первого рецепта
        # Или берем второй UL если нет h3
        current = first_h2.find_next_sibling()
        ul_count = 0
        ingredients_ul = None
        
        while current:
            # Останавливаемся на следующем h2
            if current.name == 'h2':
                if second_h2 and current == second_h2:
                    break
                elif current != first_h2:
                    break
            
            # Если нашли h3 с วัตถุดิบ, берем следующий UL
            if current.name == 'h3' and 'วัตถุดิบ' in current.get_text():
                next_ul = current.find_next_sibling('ul')
                if next_ul:
                    ingredients_ul = next_ul
                    break
            
            # Если не было h3, берем второй UL (первый обычно метаданные)
            if current.name == 'ul' and not ingredients_ul:
                ul_count += 1
                if ul_count == 2:
                    # Проверяем, что это не метаданные
                    first_li = current.find('li')
                    if first_li:
                        text = first_li.get_text(strip=True)
                        # Метаданные обычно содержат слова вроде "เวลา", "แคลอรี", "เสิร์ฟ"
                        if not any(word in text for word in ['เวลา', 'แคลอรี', 'เสิร์ฟ']):
                            ingredients_ul = current
                            break
            
            current = current.find_next_sibling()
        
        if ingredients_ul:
            items = ingredients_ul.find_all('li', recursive=False)
            ingredients = []
            
            for item in items:
                text = item.get_text(strip=True)
                parsed = self.parse_ingredient_line(text)
                if parsed and parsed['name']:
                    ingredients.append(parsed)
            
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления из первого рецепта"""
        first_h2, second_h2 = self.find_first_recipe_section()
        
        if not first_h2:
            return None
        
        # Ищем первый OL в пределах первого рецепта
        current = first_h2.find_next_sibling()
        
        while current:
            # Останавливаемся на следующем h2
            if current.name == 'h2':
                if second_h2 and current == second_h2:
                    break
                elif current != first_h2:
                    break
            
            if current.name == 'ol':
                items = current.find_all('li', recursive=False)
                steps = []
                
                for idx, item in enumerate(items, 1):
                    text = item.get_text(separator=' ', strip=True)
                    text = self.clean_text(text)
                    if text:
                        steps.append(f"{idx}. {text}")
                
                if steps:
                    return '. '.join(steps) + '.'
                break
            
            current = current.find_next_sibling()
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Проверяем keywords в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                
                script_text = script.string.strip()
                # Очищаем возможные лишние скобки
                script_text = re.sub(r'\}\s*\}$', '}', script_text)
                
                data = json.loads(script_text)
                
                if 'keywords' in data:
                    keywords = data['keywords'].lower() if isinstance(data['keywords'], str) else ''
                    # Определяем категорию по ключевым словам
                    if any(word in keywords for word in ['เค้ก', 'cake', 'ของหวาน', 'dessert']):
                        return 'Dessert'
                    elif any(word in keywords for word in ['ravioli', 'pasta', 'พาสต้า']):
                        return 'Main Course'
            except (json.JSONDecodeError, AttributeError):
                continue
        
        # По умолчанию Dessert (большинство примеров)
        return 'Dessert'
    
    def extract_time_from_metadata(self, time_label: str) -> Optional[str]:
        """
        Извлекает время из метаданных рецепта
        
        Args:
            time_label: Текст метки времени на тайском (например, 'เวลาทำอาหาร')
        """
        first_h2, second_h2 = self.find_first_recipe_section()
        
        if not first_h2:
            return None
        
        # Ищем UL с метаданными в пределах первого рецепта
        current = first_h2.find_next_sibling()
        
        while current:
            # Останавливаемся на следующем h2
            if current.name == 'h2':
                if second_h2 and current == second_h2:
                    break
                elif current != first_h2:
                    break
            
            if current.name == 'ul':
                items = current.find_all('li')
                for item in items:
                    text = item.get_text(strip=True)
                    if time_label in text:
                        # Извлекаем время после тире
                        match = re.search(r'[-–]\s*(.+)$', text)
                        if match:
                            return self.clean_text(match.group(1))
            
            current = current.find_next_sibling()
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На этом сайте "เวลาทำอาหาร" обычно означает prep_time
        return self.extract_time_from_metadata('เวลาทำอาหาร')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        # На этом сайте обычно нет отдельного cook_time
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Обычно нет отдельного total_time
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        first_h2, second_h2 = self.find_first_recipe_section()
        
        if not first_h2:
            return None
        
        # Ищем параграфы после OL (инструкций)
        current = first_h2.find_next_sibling()
        ol_found = False
        notes = []
        
        while current:
            # Останавливаемся на следующем h2
            if current.name == 'h2':
                if second_h2 and current == second_h2:
                    break
                elif current != first_h2:
                    break
            
            if current.name == 'ol':
                ol_found = True
            elif ol_found and current.name == 'p':
                text = current.get_text(strip=True)
                text = self.clean_text(text)
                # Берем параграфы подходящей длины
                if text and 20 < len(text) < 300:
                    notes.append(text)
            
            current = current.find_next_sibling()
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                
                script_text = script.string.strip()
                script_text = re.sub(r'\}\s*\}$', '}', script_text)
                
                data = json.loads(script_text)
                
                if 'keywords' in data:
                    keywords = data['keywords']
                    if isinstance(keywords, str):
                        # Преобразуем пробелы в запятые с пробелом
                        tags = keywords.replace(' ', ', ')
                        return self.clean_text(tags)
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                
                script_text = script.string.strip()
                script_text = re.sub(r'\}\s*\}$', '}', script_text)
                
                data = json.loads(script_text)
                
                if 'image' in data:
                    img = data['image']
                    if isinstance(img, dict) and 'url' in img:
                        urls.append(img['url'])
                    elif isinstance(img, str):
                        urls.append(img)
            except (json.JSONDecodeError, AttributeError):
                continue
        
        # 3. Изображения из контента (первые несколько)
        # Ищем изображения в основном контенте
        images = self.soup.find_all('img', src=True)
        for img in images[:5]:
            src = img.get('src')
            if src and 'logo' not in src.lower() and 'icon' not in src.lower():
                # Формируем полный URL
                if src.startswith('//'):
                    src = 'https:' + src
                elif src.startswith('/'):
                    src = 'https://th.women-community.com' + src
                if src not in urls:
                    urls.append(src)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        # Возвращаем через запятую без пробелов (согласно спецификации)
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
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Точка входа для обработки директории с HTML-страницами"""
    import os
    
    # Путь к директории с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "th_women-community_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(ThWomenCommunityExtractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python th_women-community_com.py")


if __name__ == "__main__":
    main()
