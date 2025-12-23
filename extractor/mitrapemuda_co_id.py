"""
Экстрактор данных рецептов для сайта mitrapemuda.co.id
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MitrapemudaExtractor(BaseRecipeExtractor):
    """Экстрактор для mitrapemuda.co.id"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта
        title = self.soup.find('h1', class_='entry-title')
        if title:
            dish_name = self.clean_text(title.get_text())
            # Убираем общие префиксы типа "Resep ..."
            dish_name = re.sub(r'^(Resep\s+)', '', dish_name, flags=re.IGNORECASE)
            # Убираем все после двоеточия
            if ':' in dish_name:
                dish_name = dish_name.split(':')[0].strip()
            # Убираем общие суффиксы
            dish_name = re.sub(r'\s+(Lezat|Mudah|Autentik|yang|dan).*$', '', dish_name, flags=re.IGNORECASE)
            return dish_name
        
        # Альтернативно - из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'WebPage' and 'name' in item:
                            name = item['name']
                            name = re.sub(r'^(Resep\s+)', '', name, flags=re.IGNORECASE)
                            if ':' in name:
                                name = name.split(':')[0].strip()
                            name = re.sub(r'\s+(Lezat|Mudah|Autentik|yang|dan).*$', '', name, flags=re.IGNORECASE)
                            return self.clean_text(name)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'WebPage' and 'description' in item:
                            return self.clean_text(item['description'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - первый параграф в основном контенте
        main_content = self.soup.find('div', class_='entry-content')
        if main_content:
            first_p = main_content.find('p')
            if first_p:
                desc = first_p.get_text(strip=True)
                return self.clean_text(desc)
        
        return None
    
    def parse_ingredient_text(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "10 buah ampela ayam" или "2 sendok makan kecap manis"
            
        Returns:
            dict: {"name": "ampela ayam", "amount": 10, "units": "buah"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Удаляем описания в скобках и после запятой (дополнительные инструкции)
        text = re.sub(r'\([^)]*\)', '', text)
        text = re.sub(r',.*$', '', text)
        text = text.strip()
        
        if not text or len(text) < 2:
            return None
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "10 buah ampela ayam", "2 sendok makan kecap manis", "1/2 sendok teh garam"
        # Индонезийские единицы измерения
        units_pattern = r'(?:buah|lembar|batang|siung|butir|sendok makan|sendok teh|ml|gram|cm|ekor|secukupnya)'
        
        # Попробуем сначала найти шаблон: число + единица + название
        pattern = r'^([\d\s/.,]+)?\s*(' + units_pattern + r')?\s*(.+)$'
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, units, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2"
            if '/' in amount_str:
                try:
                    parts = amount_str.split('/')
                    if len(parts) == 2:
                        amount = float(parts[0]) / float(parts[1])
                except:
                    pass
            else:
                try:
                    amount = float(amount_str.replace(',', '.'))
                    # Если это целое число, преобразуем в int
                    if amount.is_integer():
                        amount = int(amount)
                except:
                    pass
        
        # Обработка единицы измерения
        units = units.strip() if units else None
        
        # Очистка названия
        name = name.strip()
        
        # Если в названии есть "secukupnya" (достаточно) - это единица измерения
        if 'secukupnya' in name.lower():
            if not units:
                units = 'secukupnya'
            name = re.sub(r'\bsecukupnya\b', '', name, flags=re.IGNORECASE).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        main_content = self.soup.find('div', class_='entry-content')
        if not main_content:
            return None
        
        # Находим секцию с ингредиентами по заголовку
        # Ищем все заголовки с "bahan" до заголовка "Cara"
        ingredient_sections = []
        cara_reached = False
        
        for heading in main_content.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text().strip().lower()
            
            # Если встретили "Cara", прекращаем сбор ингредиентов
            if 'cara' in heading_text:
                cara_reached = True
                break
            
            # Если в заголовке есть "bahan" или это подзаголовок (заканчивается на ":")
            if 'bahan' in heading_text or heading_text.endswith(':'):
                # Собираем все <li> после этого заголовка до следующего заголовка
                current = heading.find_next_sibling()
                while current and current.name not in ['h2', 'h3', 'h4']:
                    if current.name == 'ul' or current.name == 'ol':
                        ingredient_sections.append(current)
                    elif current.name == 'li':
                        # Добавляем родительский список, если еще не добавлен
                        if current.parent not in ingredient_sections:
                            ingredient_sections.append(current.parent)
                    current = current.find_next_sibling()
        
        # Извлекаем ингредиенты из найденных секций
        for section in ingredient_sections:
            items = section.find_all('li')
            for item in items:
                ingredient_text = item.get_text(separator=' ', strip=True)
                parsed = self.parse_ingredient_text(ingredient_text)
                if parsed and parsed['name']:
                    # Проверяем, что это не заголовок секции (обычно заканчивается на ':')
                    if not ingredient_text.strip().endswith(':'):
                        ingredients.append(parsed)
        
        # Если ингредиенты не найдены, пробуем взять первые списки в контенте (до "Cara")
        if not ingredients:
            for lst in main_content.find_all(['ul', 'ol']):
                # Проверяем, что список идет до секции с инструкциями
                # Ищем ближайший заголовок перед списком
                prev_heading = None
                for h in main_content.find_all(['h2', 'h3', 'h4']):
                    if h.sourceline < lst.sourceline:
                        prev_heading = h
                    else:
                        break
                
                if prev_heading and 'cara' not in prev_heading.get_text().strip().lower():
                    items = lst.find_all('li')
                    for item in items:
                        ingredient_text = item.get_text(separator=' ', strip=True)
                        if not ingredient_text.strip().endswith(':'):
                            parsed = self.parse_ingredient_text(ingredient_text)
                            if parsed and parsed['name']:
                                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions = []
        
        main_content = self.soup.find('div', class_='entry-content')
        if not main_content:
            return None
        
        # Находим секцию с инструкциями по заголовку (Cara Membuat)
        instruction_started = False
        for heading in main_content.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text().strip().lower()
            if 'cara' in heading_text or 'langkah' in heading_text:
                instruction_started = True
                # Собираем все подзаголовки с номерами
                current = heading.find_next_sibling()
                while current:
                    if current.name in ['h2', 'h3', 'h4']:
                        subheading_text = current.get_text().strip()
                        # Если это нумерованный шаг (начинается с цифры)
                        if re.match(r'^\d+\.', subheading_text):
                            # Извлекаем заголовок шага (без номера)
                            step_title = re.sub(r'^\d+\.\s*', '', subheading_text)
                            
                            # Собираем текст из следующего списка
                            step_texts = []
                            next_ul = current.find_next_sibling('ul')
                            if next_ul:
                                # Берем все элементы списка
                                for li in next_ul.find_all('li'):
                                    text = li.get_text(strip=True)
                                    # Берем только первое предложение
                                    first_sentence = text.split('.')[0]
                                    if first_sentence and len(first_sentence) > 10:
                                        step_texts.append(first_sentence)
                            
                            # Формируем шаг: заголовок + объединенные предложения из списка
                            if step_texts:
                                step = f"{step_title}: {'. '.join(step_texts)}"
                            else:
                                step = step_title
                            
                            instructions.append(self.clean_text(step))
                        else:
                            # Если заголовок не нумерованный, возможно закончились инструкции
                            if any(keyword in subheading_text.lower() for keyword in ['tips', 'catatan', 'saran', 'variasi', 'manfaat', 'nilai gizi']):
                                break
                    current = current.find_next_sibling()
                break
        
        # Форматируем с нумерацией
        if instructions:
            formatted_instructions = [f"{i+1}. {instr}" for i, instr in enumerate(instructions)]
            return ' '.join(formatted_instructions)
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        main_content = self.soup.find('div', class_='entry-content')
        if not main_content:
            return None
        
        # Ищем секции с заголовками о питательности/пользе
        headings = main_content.find_all(['h2', 'h3', 'h4'])
        for i, heading in enumerate(headings):
            heading_text = heading.get_text().strip().lower()
            if any(keyword in heading_text for keyword in ['manfaat', 'nilai gizi', 'nutrisi', 'nutrition']) and not heading_text.startswith(('1.', '2.', '3.')):
                # Это главный заголовок секции, ищем первый нумерованный подзаголовок
                for j in range(i+1, len(headings)):
                    sub_h = headings[j]
                    sub_text = sub_h.get_text().strip()
                    if sub_text.startswith('1.'):
                        # Берем первое предложение из следующего параграфа
                        next_p = sub_h.find_next_sibling('p')
                        if next_p:
                            text = next_p.get_text(strip=True)
                            # Берем только первое предложение
                            first_sentence = text.split('.')[0] + '.'
                            return self.clean_text(first_sentence)
                    elif not sub_text.startswith(('2.', '3.', '4.')):
                        # Если не нумерованный заголовок, выходим
                        break
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # По умолчанию для индонезийских рецептов - Main Course
        # Можно попробовать определить по тегам или тексту
        return "Main Course"
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        main_content = self.soup.find('div', class_='entry-content')
        if not main_content:
            return None
        
        # Ищем в тексте упоминания времени подготовки
        text = main_content.get_text()
        
        # Паттерны для индонезийских рецептов
        patterns = [
            r'waktu\s+persiapan[:\s]+(\d+[-\s]*\d*\s*(?:menit|minutes?))',
            r'persiapan[:\s]+(\d+[-\s]*\d*\s*(?:menit|minutes?))',
            r'rebus.*?selama\s+(\d+[-\s]*\d*\s*(?:menit|minutes?))',
            r'diamkan\s+selama\s+(\d+[-\s]*\d*\s*(?:menit|minutes?))',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                time_str = self.clean_text(match.group(1))
                # Конвертируем "menit" в "minutes"
                time_str = time_str.replace('menit', 'minutes')
                return time_str
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        main_content = self.soup.find('div', class_='entry-content')
        if not main_content:
            return None
        
        # Ищем в тексте упоминания времени приготовления
        text = main_content.get_text()
        
        patterns = [
            r'waktu\s+memasak[:\s]+(\d+[-\s]*\d*\s*(?:menit|minutes?))',
            r'memasak[:\s]+(\d+[-\s]*\d*\s*(?:menit|minutes?))',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                time_str = self.clean_text(match.group(1))
                time_str = time_str.replace('menit', 'minutes')
                return time_str
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        main_content = self.soup.find('div', class_='entry-content')
        if not main_content:
            return None
        
        # Ищем в тексте упоминания общего времени
        text = main_content.get_text()
        
        patterns = [
            r'total\s+waktu[:\s]+(\d+[-\s]*\d*\s*(?:menit|minutes?))',
            r'waktu\s+total[:\s]+(\d+[-\s]*\d*\s*(?:menit|minutes?))',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                time_str = self.clean_text(match.group(1))
                time_str = time_str.replace('menit', 'minutes')
                return time_str
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        main_content = self.soup.find('div', class_='entry-content')
        if not main_content:
            return None
        
        # Ищем секции с заголовками о советах/примечаниях
        headings = main_content.find_all(['h2', 'h3', 'h4'])
        notes_texts = []
        
        for i, heading in enumerate(headings):
            heading_text = heading.get_text().strip().lower()
            # Ищем главный заголовок секции с tips
            if any(keyword in heading_text for keyword in ['tips', 'catatan', 'saran', 'note']) and not heading_text.startswith(('1.', '2.', '3.')):
                # Собираем первые 2 нумерованных совета
                for j in range(i+1, len(headings)):
                    sub_h = headings[j]
                    sub_text = sub_h.get_text().strip()
                    if sub_text.startswith(('1.', '2.')):
                        # Берем первое предложение из параграфа
                        next_p = sub_h.find_next_sibling('p')
                        if next_p:
                            text = next_p.get_text(strip=True)
                            first_sentence = text.split('.')[0]
                            if first_sentence and len(first_sentence) > 10:
                                notes_texts.append(first_sentence)
                        
                        if len(notes_texts) >= 2:
                            break
                    elif not sub_text.startswith(('3.', '4.')):
                        # Если не нумерованный заголовок, выходим
                        break
                
                if notes_texts:
                    break
        
        if notes_texts:
            return self.clean_text('. '.join(notes_texts))
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Пытаемся извлечь теги из мета-данных или категорий
        tags = []
        
        # Ищем в мета-тегах keywords
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            tags_str = meta_keywords['content']
            tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
        
        # Если не нашли в мета-тегах, попробуем определить по тексту заголовка и описания
        if not tags:
            title = self.extract_dish_name()
            if title:
                # Извлекаем ключевые слова из названия
                words = title.split()
                # Фильтруем общие слова
                stopwords = {'resep', 'yang', 'dan', 'dengan', 'untuk', 'cara', 'membuat', 'lezat', 'enak'}
                tags = [word.strip().title() for word in words if word.lower() not in stopwords]
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 2. Ищем основное изображение статьи
        main_image = self.soup.find('img', class_='wp-post-image')
        if main_image and main_image.get('src'):
            urls.append(main_image['src'])
        
        # 3. Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
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
            "nutrition_info": self.extract_nutrition_info(),
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
    # Обрабатываем папку preprocessed/mitrapemuda_co_id
    recipes_dir = os.path.join("preprocessed", "mitrapemuda_co_id")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(MitrapemudaExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python mitrapemuda_co_id.py")


if __name__ == "__main__":
    main()
