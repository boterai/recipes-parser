"""
Экстрактор данных рецептов для сайта th.women-community.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ThWomenCommunityExtractor(BaseRecipeExtractor):
    """Экстрактор для th.women-community.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала попробуем извлечь из первого h2 рецепта
        first_recipe_h2, _ = self.get_first_recipe_section()
        if first_recipe_h2:
            # Берем текст из h2 первого рецепта
            dish_name = first_recipe_h2.get_text(strip=True)
            return self.clean_text(dish_name)
        
        # Fallback: из og:title, но убираем лишнее
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем всё после двоеточия или вертикальной черты
            title = re.sub(r'\s*[:|].+$', '', title)
            return self.clean_text(title)
        
        # Альтернативно - из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            title = re.sub(r'\s*[:|].+$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Пытаемся найти описание в первом параграфе после первого h2 рецепта
        first_recipe_h2, next_recipe_h2 = self.get_first_recipe_section()
        
        if first_recipe_h2:
            current = first_recipe_h2.find_next_sibling()
            
            while current and current != next_recipe_h2:
                if current.name == 'h2':
                    break
                
                if current.name == 'p':
                    text = current.get_text(strip=True)
                    text = self.clean_text(text)
                    # Берем первое предложение
                    if text and len(text) > 30:
                        sentences = text.split('.')
                        if sentences and sentences[0]:
                            return sentences[0].strip() + '.'
                
                current = current.find_next_sibling()
        
        # Fallback: ищем в meta description, берем первое предложение
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            first_sentence = desc.split('.')[0]
            if first_sentence:
                return self.clean_text(first_sentence + '.')
            return self.clean_text(desc)
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            first_sentence = desc.split('.')[0]
            if first_sentence:
                return self.clean_text(first_sentence + '.')
            return self.clean_text(desc)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "ไข่ - 4 ชิ้น" или "น้ำตาล - 150 กรัม"
            
        Returns:
            dict: {"name": "ไข่", "amount": 4, "units": "pieces"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн: "название - количество единица"
        # Пример: "ไข่ - 4 ชิ้น", "น้ำตาล - 150 กรัม"
        match = re.match(r'^(.+?)\s*[-–]\s*(.+)$', text)
        
        if not match:
            # Если нет тире, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        name, amount_unit = match.groups()
        name = name.strip()
        amount_unit = amount_unit.strip()
        
        # Извлекаем количество и единицу измерения
        # Сначала обрабатываем дроби
        amount_unit = amount_unit.replace('½', '0.5').replace('¼', '0.25').replace('¾', '0.75')
        amount_unit = amount_unit.replace('⅓', '0.33').replace('⅔', '0.67')
        
        # Паттерн для количества и единицы
        # Поддерживаем дроби вида "3/4", числа, диапазоны "150-170"
        amount_pattern = r'([\d\s/.,\-]+)\s*(.+)?'
        amount_match = re.match(amount_pattern, amount_unit)
        
        if not amount_match:
            return {
                "name": name,
                "amount": None,
                "units": None
            }
        
        amount_str, unit = amount_match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            
            # Обрабатываем диапазоны - берем первое значение
            if '-' in amount_str and '/' not in amount_str:
                parts = amount_str.split('-')
                amount_str = parts[0].strip()
            
            # Обработка дробей типа "3/4"
            if '/' in amount_str:
                # Может быть "1 1/2" или просто "1/2"
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
                # Обычное число
                amount_str = amount_str.replace(',', '.')
                try:
                    amount = float(amount_str)
                    # Если целое число, преобразуем в int
                    if amount == int(amount):
                        amount = int(amount)
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Маппинг единиц на английские эквиваленты
        unit_mapping = {
            'ชิ้น': 'pieces',
            'กรัม': 'grams',
            'มล': 'milliliters',
            'ช้อนโต๊ะ': 'tablespoons',
            'ช้อนชา': 'teaspoons',
            'ถ้วย': 'cups',
            'ล.': 'tablespoons',  # сокращение от ช้อนโต๊ะ
            'g': 'grams',
            'ml': 'milliliters',
        }
        
        if unit:
            # Убираем "ล." из единицы (часто идет в конце)
            unit = re.sub(r'\s*ล\.$', '', unit)
            # Ищем в маппинге
            for thai_unit, eng_unit in unit_mapping.items():
                if thai_unit in unit:
                    unit = eng_unit
                    break
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def get_first_recipe_section(self):
        """Находит границы первой секции рецепта на странице"""
        h2_tags = self.soup.find_all('h2')
        
        # Ищем первый h2, который является рецептом (не оглавление и не введение)
        first_recipe_h2 = None
        next_recipe_h2 = None
        
        # Паттерны для пропуска (оглавление и служебные секции)
        skip_patterns = ['สารบัญ', 'แนะนำ', 'ข้อความ', 'ความคิดเห็น', 'บทความ', 'คำแนะนำ', 'สูตรวิดีโอ']
        
        for i, h2 in enumerate(h2_tags):
            text = h2.get_text(strip=True)
            # Пропускаем оглавление и служебные секции
            # Но НЕ пропускаем разделы с советами, которые могут быть частью рецепта
            if not any(pattern in text for pattern in skip_patterns):
                if first_recipe_h2 is None:
                    first_recipe_h2 = h2
                elif next_recipe_h2 is None:
                    next_recipe_h2 = h2
                    break
        
        return first_recipe_h2, next_recipe_h2
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов только из первого рецепта"""
        first_recipe_h2, next_recipe_h2 = self.get_first_recipe_section()
        
        if not first_recipe_h2:
            return None
        
        # Ищем ul с ингредиентами в пределах первого рецепта
        current = first_recipe_h2.find_next_sibling()
        ingredients_ul = None
        
        while current and current != next_recipe_h2:
            if current.name == 'h2':
                break
            
            # Ищем ul после h3 с "วัตถุดิบ:"
            if current.name == 'h3' and 'วัตถุดิบ' in current.get_text():
                # Следующий элемент должен быть ul с ингредиентами
                next_elem = current.find_next_sibling()
                while next_elem and next_elem.name not in ['ul', 'h2', 'h3']:
                    next_elem = next_elem.find_next_sibling()
                
                if next_elem and next_elem.name == 'ul':
                    ingredients_ul = next_elem
                    break
            
            # Если нет h3 с "วัตถุดิบ:", просто ищем второй ul (первый - метаданные)
            if current.name == 'ul' and ingredients_ul is None:
                # Проверяем, не является ли это списком метаданных
                first_li = current.find('li')
                if first_li and ('เวลา' in first_li.get_text() or 'แคลอรี' in first_li.get_text() or 'เสิร์ฟ' in first_li.get_text()):
                    # Это метаданные, продолжаем поиск
                    pass
                else:
                    # Это список ингредиентов
                    ingredients_ul = current
                    break
            
            current = current.find_next_sibling()
        
        if not ingredients_ul:
            return None
        
        # Извлекаем ингредиенты
        all_ingredients = []
        items = ingredients_ul.find_all('li', recursive=False)
        
        for item in items:
            ingredient_text = item.get_text(strip=True)
            parsed = self.parse_ingredient(ingredient_text)
            if parsed and parsed['name']:
                all_ingredients.append(parsed)
        
        if all_ingredients:
            return json.dumps(all_ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления только из первого рецепта"""
        first_recipe_h2, next_recipe_h2 = self.get_first_recipe_section()
        
        if not first_recipe_h2:
            return None
        
        # Ищем ol в пределах первого рецепта
        current = first_recipe_h2.find_next_sibling()
        
        while current and current != next_recipe_h2:
            if current.name == 'h2':
                break
            
            if current.name == 'ol':
                items = current.find_all('li', recursive=False)
                steps = []
                for idx, item in enumerate(items, 1):
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    if step_text:
                        steps.append(f"{idx}. {step_text}")
                
                return '. '.join(steps) + '.' if steps else None
            
            current = current.find_next_sibling()
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Пробуем извлечь из JSON-LD keywords
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                # Очищаем строку от лишних символов
                script_text = script.string.strip() if script.string else ""
                # Иногда в конце может быть закрывающая скобка от другого блока
                script_text = re.sub(r'\}\s*\}$', '}', script_text)
                
                data = json.loads(script_text)
                
                # Пытаемся определить категорию по keywords
                if 'keywords' in data:
                    keywords = data['keywords']
                    # Если это десерт/выпечка
                    if any(word in keywords.lower() for word in ['cake', 'เค้ก', 'ของหวาน', 'dessert']):
                        return 'Dessert'
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        # По умолчанию возвращаем Dessert, так как большинство примеров - десерты
        return 'Dessert'
    
    def extract_time_from_metadata(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени из метаданных списка
        
        Args:
            time_type: 'prep', 'cook', или 'total'
        """
        first_recipe_h2, next_recipe_h2 = self.get_first_recipe_section()
        
        if not first_recipe_h2:
            return None
        
        # Ищем список с метаданными в пределах первого рецепта
        current = first_recipe_h2.find_next_sibling()
        
        while current and current != next_recipe_h2:
            if current.name == 'h2':
                break
            
            if current.name == 'ul':
                items = current.find_all('li')
                for item in items:
                    text = item.get_text(strip=True)
                    
                    # เวลาทำอาหาร - время приготовления
                    # Для этого сайта "เวลาทำอาหาร" обычно означает prep_time
                    if time_type == 'prep' and 'เวลาทำอาหาร' in text:
                        time_match = re.search(r'[-–]\s*(.+)$', text)
                        if time_match:
                            return self.clean_text(time_match.group(1))
                    
                    elif time_type == 'total' and 'เวลาทำอาหาร' in text:
                        time_match = re.search(r'[-–]\s*(.+)$', text)
                        if time_match:
                            return self.clean_text(time_match.group(1))
            
            current = current.find_next_sibling()
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time_from_metadata('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return None  # На этом сайте обычно нет отдельного cook_time
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time_from_metadata('total')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        first_recipe_h2, next_recipe_h2 = self.get_first_recipe_section()
        
        if not first_recipe_h2:
            return None
        
        # Ищем параграфы после инструкций (ol) в пределах первого рецепта
        current = first_recipe_h2.find_next_sibling()
        ol_found = False
        notes = []
        
        while current and current != next_recipe_h2:
            if current.name == 'h2':
                break
            
            if current.name == 'ol':
                ol_found = True
            elif ol_found and current.name == 'p':
                text = current.get_text(strip=True)
                text = self.clean_text(text)
                # Берем параграфы средней длины (не слишком короткие и не слишком длинные)
                if text and 20 < len(text) < 200:
                    notes.append(text)
            
            current = current.find_next_sibling()
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Извлекаем из JSON-LD keywords
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                script_text = script.string.strip() if script.string else ""
                script_text = re.sub(r'\}\s*\}$', '}', script_text)
                
                data = json.loads(script_text)
                
                if 'keywords' in data:
                    keywords = data['keywords']
                    # Преобразуем в список, разделяя по пробелам или запятым
                    if isinstance(keywords, str):
                        # Разделяем по пробелам, сохраняя запятые
                        tags = keywords.replace(' ', ', ')
                        return self.clean_text(tags)
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                script_text = script.string.strip() if script.string else ""
                script_text = re.sub(r'\}\s*\}$', '}', script_text)
                
                data = json.loads(script_text)
                
                if 'image' in data:
                    img = data['image']
                    if isinstance(img, dict) and 'url' in img:
                        urls.append(img['url'])
                    elif isinstance(img, str):
                        urls.append(img)
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        # 3. Ищем изображения в контенте статьи
        # Ищем все img теги внутри основного контента
        content_images = self.soup.find_all('img', src=True)
        for img in content_images[:5]:  # Берем не более 5 изображений
            src = img.get('src')
            # Игнорируем логотипы и иконки
            if src and 'logo' not in src.lower() and 'icon' not in src.lower():
                # Формируем полный URL если нужно
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
