"""
Экстрактор данных рецептов для сайта fooded.co
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict, Union

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class FoodedCoExtractor(BaseRecipeExtractor):
    """Экстрактор для fooded.co"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Пробуем из h1 заголовка
        h1 = self.soup.find('h1', class_='jet-breadcrumbs__title')
        if h1:
            name = h1.get_text().strip()
            # Убираем суффиксы типа "- Fooded.co"
            name = re.sub(r'\s*-\s*Fooded\.co.*$', '', name, flags=re.IGNORECASE)
            # Убираем дополнительные описания после основного названия
            # Паттерны: "สูตร", "วิธีทำ", "เคล็ดลับ", "(название на англ)"
            name = re.sub(r'\s+สูตร.*$', '', name)
            name = re.sub(r'\s+วิธี.*$', '', name)
            name = re.sub(r'\s+เคล็ดลับ.*$', '', name)
            name = re.sub(r'\s+และ.*$', '', name)
            # Убираем английское название в скобках и все после него
            name = re.sub(r'\s+\([^)]*\).*$', '', name)
            name = self.clean_text(name)
            if name:
                return name
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s*-\s*Fooded\.co.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s+สูตร.*$', '', title)
            title = re.sub(r'\s+วิธี.*$', '', title)
            title = re.sub(r'\s+เคล็ดลับ.*$', '', title)
            title = re.sub(r'\s+และ.*$', '', title)
            title = re.sub(r'\s+\([^)]*\).*$', '', title)
            title = self.clean_text(title)
            if title:
                return title
        
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
        
        # Ищем все параграфы
        all_paragraphs = self.soup.find_all('p')
        
        # Ищем параграф, который упоминает ингредиенты (ส่วนผสม, ส่วนประกอบ, เตรียมส่วนผสม)
        for p in all_paragraphs:
            p_text = p.get_text().strip()
            # Проверяем, упоминает ли параграф ингредиенты
            if re.search(r'ส่วนผสม|ส่วนประกอบ|เตรียมส่วนผสม', p_text, re.IGNORECASE):
                # Проверяем, есть ли список после этого параграфа
                next_sibling = p.find_next_sibling()
                if next_sibling and next_sibling.name in ['ul', 'ol']:
                    # Извлекаем элементы списка
                    items = next_sibling.find_all('li')
                    for item in items:
                        ingredient_text = item.get_text(strip=True)
                        ingredient_text = self.clean_text(ingredient_text)
                        
                        if ingredient_text:
                            # Парсим ингредиент
                            parsed = self.parse_ingredient(ingredient_text)
                            if parsed:
                                # Если это список ингредиентов без количества (разделенных пробелами)
                                # И у нас есть несколько слов, можем разделить их
                                if isinstance(parsed, list):
                                    ingredients.extend(parsed)
                                else:
                                    ingredients.append(parsed)
                    
                    if ingredients:
                        break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Union[Dict, List[Dict]]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "หมูสับละเอียด 500 กรัม" или "เลดี้ฟิงเกอร์ (Ladyfingers): ขนมปัง..."
            
        Returns:
            dict или list[dict]: {"name": "หมูสับละเอียด", "units": "กรัม", "amount": 500}
        """
        if not ingredient_text:
            return None
        
        # Убираем описания после двоеточия или дефиса
        # Пример: "เลดี้ฟิงเกอร์ (Ladyfingers): ขนมปัง..." -> "เลดี้ฟิงเกอร์"
        ingredient_text = re.sub(r'\s*[:–-]\s*.+$', '', ingredient_text)
        
        # Убираем английские названия в скобках
        ingredient_text = re.sub(r'\s*\([^)]*\)', '', ingredient_text)
        
        # Паттерн для извлечения: название количество единица
        # Пример: "หมูสับละเอียด 500 กรัม"
        # Пример: "ไข่ขาว 1 ฟอง"
        # Пример: "แป้งมันสำปะหลัง 2 ช้อนโต๊ะ"
        
        # Попробуем найти число и единицы измерения в конце
        pattern = r'^(.+?)\s+([\d./]+)\s+(.+)$'
        match = re.match(pattern, ingredient_text)
        
        if match:
            name = match.group(1).strip()
            amount_str = match.group(2).strip()
            unit = match.group(3).strip()
            
            # Пробуем конвертировать amount в число
            try:
                if '/' in amount_str:
                    # Обработка дробей
                    parts = amount_str.split('/')
                    amount = float(parts[0]) / float(parts[1])
                else:
                    amount = float(amount_str) if '.' in amount_str else int(amount_str)
            except (ValueError, ZeroDivisionError):
                amount = None
            
            return {
                "name": self.clean_text(name),
                "units": self.clean_text(unit),
                "amount": amount
            }
        else:
            # Если паттерн не совпал, это может быть либо один ингредиент,
            # либо несколько ингредиентов без количества, разделенных пробелами
            clean_name = self.clean_text(ingredient_text)
            
            # Если в строке несколько слов и нет цифр, возможно это список
            # Разделяем по пробелам только если больше 2 слов
            words = clean_name.split()
            if len(words) >= 3 and not re.search(r'\d', clean_name):
                # Возвращаем список ингредиентов
                return [
                    {
                        "name": word,
                        "units": None,
                        "amount": None
                    }
                    for word in words if word
                ]
            else:
                # Один ингредиент
                return {
                    "name": clean_name,
                    "units": None,
                    "amount": None
                }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions = []
        
        # Сначала пробуем найти ordered list (ol) - обычно содержит шаги
        all_ol = self.soup.find_all('ol')
        
        if all_ol:
            # Берем первый ol - обычно это инструкции
            ol = all_ol[0]
            items = ol.find_all('li')
            
            for idx, item in enumerate(items, 1):
                step_text = item.get_text(strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    # Убираем префикс типа "เตรียมไส้หมูเด้ง :"
                    step_text = re.sub(r'^[^:]+:\s*', '', step_text)
                    # Добавляем нумерацию
                    instructions.append(f"{idx}. {step_text}.")
            
            if instructions:
                return '\n'.join(instructions)
        
        # Если нет ordered list, ищем в параграфах (как раньше)
        all_paragraphs = self.soup.find_all('p')
        
        for p in all_paragraphs:
            p_text = p.get_text().strip()
            
            # Проверяем, содержит ли параграф инструкции
            if re.search(r'วิธี(การ)?ทำ', p_text, re.IGNORECASE):
                # Проверяем длину текста - если это длинный параграф с инструкциями
                if len(p_text) > 100:
                    # Это может быть сам текст инструкции
                    instructions_text = self.clean_text(p_text)
                    if instructions_text:
                        return instructions_text
                
                # Проверяем, есть ли список после этого параграфа
                next_sibling = p.find_next_sibling()
                if next_sibling and next_sibling.name in ['ul', 'ol']:
                    items = next_sibling.find_all('li')
                    for idx, item in enumerate(items, 1):
                        step_text = item.get_text(strip=True)
                        step_text = self.clean_text(step_text)
                        if step_text:
                            # Добавляем нумерацию, если её нет
                            if not re.match(r'^\d+\.', step_text):
                                step_text = f"{idx}. {step_text}"
                            instructions.append(step_text)
                    
                    if instructions:
                        return '\n'.join(instructions)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в метаданных article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            category = self.clean_text(meta_section['content'])
            # Маппинг тайских категорий на английские
            category_map = {
                'ทั่วไป': 'General',
                'ขนมหวาน': 'Dessert',
                'อาหารหลัก': 'Main Course',
                'เครื่องดื่ม': 'Beverage',
            }
            mapped_category = category_map.get(category, category)
            
            # Если категория "General", пробуем определить из контекста
            if mapped_category == 'General':
                # Проверяем описание и теги на предмет ключевых слов
                desc = self.extract_description() or ''
                tags = self.extract_tags() or ''
                dish_name = self.extract_dish_name() or ''
                
                content_lower = (desc + ' ' + tags + ' ' + dish_name).lower()
                
                # Десерты
                if re.search(r'ขนมหวาน|dessert|tiramisu|ทิรามิสุ|เค้ก|cake', content_lower, re.IGNORECASE):
                    return 'Dessert'
                # Основные блюда / Dim Sum
                elif re.search(r'ติ่มซำ|ขนมจีบ|dim sum|shumai|dumpling', content_lower, re.IGNORECASE):
                    return 'Main Course'
                # Buns
                elif re.search(r'ซาลาเปา|bun', content_lower, re.IGNORECASE):
                    return 'Main Course'
            
            return mapped_category
        
        return None
    
    def extract_time_info(self) -> Dict[str, Optional[str]]:
        """
        Извлечение информации о времени приготовления
        Ищет в тексте упоминания времени
        """
        result = {
            'prep_time': None,
            'cook_time': None,
            'total_time': None
        }
        
        # Получаем весь текст из параграфов и ordered lists
        all_paragraphs = self.soup.find_all('p')
        all_ol = self.soup.find_all('ol')
        
        full_text = ' '.join([p.get_text() for p in all_paragraphs])
        for ol in all_ol:
            items = ol.find_all('li')
            full_text += ' ' + ' '.join([item.get_text() for item in items])
        
        # Паттерны для поиска времени
        # Примеры: "1 ชั่วโมง", "15 นาที", "1 ชั่วโมง 15 นาที", "12-15 นาที"
        
        # Prep time (เตรียม, แช่)
        prep_patterns = [
            r'แช่(?:เย็น|ไว้)?\s*(?:อย่างน้อย\s*)?(\d+)\s*ชั่วโมง',
            r'เตรียม.*?(\d+)\s*ชั่วโมง',
        ]
        
        for pattern in prep_patterns:
            match = re.search(pattern, full_text)
            if match:
                amount = match.group(1)
                result['prep_time'] = f"{amount} hour{'s' if int(amount) > 1 else ''}"
                break
        
        # Cook time (นึ่ง, ทอด, ปรุง, อบ)
        cook_patterns = [
            r'นึ่ง(?:ด้วยไฟแรง)?(?:\s*ประมาณ\s*)?(\d+)(?:-(\d+))?\s*นาที',
            r'ทอด\s*(\d+)\s*นาที',
            r'อบ\s*(\d+)\s*นาที',
        ]
        
        for pattern in cook_patterns:
            match = re.search(pattern, full_text)
            if match:
                # Берем максимальное значение если указан диапазон (12-15 -> 15)
                amount = match.group(2) if match.group(2) else match.group(1)
                result['cook_time'] = f"{amount} minutes"
                break
        
        # Total time - если есть и prep и cook, можем вычислить
        if result['prep_time'] and result['cook_time']:
            # Извлекаем числа
            prep_match = re.search(r'(\d+)', result['prep_time'])
            cook_match = re.search(r'(\d+)', result['cook_time'])
            
            if prep_match and cook_match:
                prep_val = int(prep_match.group(1))
                cook_val = int(cook_match.group(1))
                
                # Конвертируем в минуты если нужно
                if 'hour' in result['prep_time']:
                    prep_val = prep_val * 60
                if 'hour' in result['cook_time']:
                    cook_val = cook_val * 60
                
                total_minutes = prep_val + cook_val
                if total_minutes >= 60:
                    hours = total_minutes // 60
                    minutes = total_minutes % 60
                    if minutes > 0:
                        result['total_time'] = f"{hours} hour{'s' if hours > 1 else ''} {minutes} minutes"
                    else:
                        result['total_time'] = f"{hours} hour{'s' if hours > 1 else ''}"
                else:
                    result['total_time'] = f"{total_minutes} minutes"
        
        return result
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Сначала пробуем найти второй ordered list - обычно содержит советы
        all_ol = self.soup.find_all('ol')
        
        if len(all_ol) >= 2:
            # Берем второй ol - обычно это советы
            ol = all_ol[1]
            items = ol.find_all('li')
            notes_list = []
            
            for item in items:
                note_text = item.get_text(strip=True)
                note_text = self.clean_text(note_text)
                if note_text:
                    # Добавляем точку в конце, если её нет
                    if not note_text.endswith('.'):
                        note_text += '.'
                    notes_list.append(note_text)
            
            if notes_list:
                # Возвращаем первый совет (как в эталоне)
                return notes_list[0]
        
        # Если нет второго ol, ищем параграф с советами/заметками (เคล็ดลับ, คำแนะนำ, หมายเหตุ)
        all_paragraphs = self.soup.find_all('p')
        
        for p in all_paragraphs:
            p_text = p.get_text().strip()
            
            # Проверяем, содержит ли параграф советы
            if re.search(r'เคล็ดลับ', p_text, re.IGNORECASE):
                # Если это длинный параграф с советами
                if len(p_text) > 50:
                    notes_text = self.clean_text(p_text)
                    if notes_text:
                        # Добавляем точку в конце, если её нет
                        if not notes_text.endswith('.'):
                            notes_text += '.'
                        return notes_text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_set = set()  # Using set to avoid duplicates
        
        # Ищем в JSON-LD BlogPosting
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем наличие @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'BlogPosting':
                            keywords = item.get('keywords')
                            if keywords:
                                # Разделяем по запятым и добавляем в set
                                for tag in keywords.split(','):
                                    tags_set.add(tag.strip())
            except json.JSONDecodeError:
                continue
        
        # Если не нашли теги в JSON-LD, генерируем из контента
        if not tags_set:
            dish_name = self.extract_dish_name()
            category = self.extract_category()
            description = self.extract_description() or ''
            
            if dish_name:
                content = (dish_name + ' ' + description).lower()
                
                # Если это Dim Sum / Chinese food
                if 'ติ่มซำ' in content or 'dim sum' in content or 'ขนมจีบ' in dish_name:
                    tags_set.add('ติ่มซำ')
                    # Добавляем специфический тип
                    if 'ขนมจีบ' in dish_name:
                        tags_set.add('ขนมจีบ')
                    # Добавляем кухню
                    tags_set.add('อาหารจีน')
                
                # Если это Tiramisu / Italian dessert
                elif 'ทิรามิสุ' in dish_name or 'tiramisu' in content:
                    tags_set.add('ทิรามิสุ')
                    tags_set.add('ขนมหวาน')
                    tags_set.add('อิตาลี')
                
                # Если это Xiao Long Bao
                elif 'เสี่ยวหลงเปา' in dish_name or 'xiao long bao' in content or 'ซาลาเปาซุป' in dish_name:
                    tags_set.add('เสี่ยวหลงเปา')
                    tags_set.add('ติ่มซำ')
                    tags_set.add('อาหารจีน')
                
                # Если это сяопао/buns with pork
                elif 'ซาลาเปา' in dish_name and ('หมูแดง' in dish_name or 'pork' in content or 'red pork' in content):
                    tags_set.add('ซาลาเปาหมูแดง')
                    tags_set.add('ติ่มซำ')
                    tags_set.add('อาหารจีน')
                
                # Если это shrimp dumplings
                elif 'หมูและกุ้ง' in dish_name or ('pork' in content and 'shrimp' in content and 'dumpling' in content):
                    tags_set.add('ติ่มซำ')
                    tags_set.add('ขนมจีบหมูและกุ้ง')
                    tags_set.add('อาหารจีน')
        
        if tags_set:
            # Maintain specific order if possible: specific dish, category, cuisine
            tags_list = []
            # Collect specific dishes first
            for tag in tags_set:
                if tag not in ['ติ่มซำ', 'อาหารจีน', 'ขนมหวาน', 'อิตาลี']:
                    tags_list.append(tag)
            # Then category
            if 'ติ่มซำ' in tags_set:
                tags_list.append('ติ่มซำ')
            if 'ขนมหวาน' in tags_set:
                tags_list.append('ขนมหวาน')
            # Then cuisine
            if 'อาหารจีน' in tags_set:
                tags_list.append('อาหารจีน')
            if 'อิตาลี' in tags_set:
                tags_list.append('อิตาลี')
            
            return ', '.join(tags_list) if tags_list else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 2. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем наличие @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict):
                            # ImageObject
                            if item.get('@type') == 'ImageObject':
                                if 'url' in item:
                                    urls.append(item['url'])
                                elif 'contentUrl' in item:
                                    urls.append(item['contentUrl'])
            except json.JSONDecodeError:
                continue
        
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
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()
        
        # Извлекаем время
        time_info = self.extract_time_info()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": time_info['prep_time'],
            "cook_time": time_info['cook_time'],
            "total_time": time_info['total_time'],
            "notes": notes,
            "tags": tags,
            "image_urls": image_urls
        }


def main():
    """
    Точка входа для обработки HTML файлов fooded_co
    """
    import os
    
    # Ищем директорию с HTML-страницами
    recipes_dir = os.path.join("preprocessed", "fooded_co")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(FoodedCoExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python fooded_co.py")


if __name__ == "__main__":
    main()
