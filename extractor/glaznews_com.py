"""
Экстрактор данных рецептов для сайта glaznews.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class GlaznewsExtractor(BaseRecipeExtractor):
    """Экстрактор для glaznews.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из заголовка страницы
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем суффиксы после первого " – " (длинный дефис) или ": "
            title = re.split(r'\s*[–—:]\s*', title)[0]
            # Также убираем суффиксы после " - " (обычный дефис с пробелами)
            title = re.split(r'\s+-\s+', title)[0]
            return self.clean_text(title)
        
        # Альтернатива - из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.split(r'\s*[–—:]\s*', title)[0]
            title = re.split(r'\s+-\s+', title)[0]
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
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате списка словарей"""
        ingredients = []
        
        # Ищем заголовок "Інгредієнти" или "Інгредиєнти"
        content_div = self.soup.find('div', class_='entry-content')
        if not content_div:
            return None
        
        # Ищем заголовок с ингредиентами (может быть h3, h2, или p)
        ingredient_heading = None
        for elem in content_div.find_all(['h3', 'h2', 'p', 'strong']):
            heading_text = elem.get_text(strip=True)
            if 'нгредієнт' in heading_text or 'нгредиєнт' in heading_text:
                # Если это strong внутри p, берем родительский p
                if elem.name == 'strong':
                    ingredient_heading = elem.parent
                else:
                    ingredient_heading = elem
                break
        
        if not ingredient_heading:
            return None
        
        # Находим следующий список после заголовка
        ingredient_list = ingredient_heading.find_next(['ol', 'ul'], class_='wp-block-list')
        if not ingredient_list:
            # Если список не найден, пробуем найти его как следующий sibling
            ingredient_list = ingredient_heading.find_next(['ol', 'ul'])
        
        if not ingredient_list:
            return None
        
        # Извлекаем элементы списка
        for li in ingredient_list.find_all('li', recursive=False):
            # Получаем HTML контент элемента
            li_html = str(li)
            
            # Разбиваем по <br> тегам, чтобы получить отдельные строки ингредиентов
            lines = re.split(r'<br\s*/?>', li_html)
            
            for line in lines:
                # Удаляем HTML теги и получаем текст
                from bs4 import BeautifulSoup
                line_soup = BeautifulSoup(line, 'lxml')
                ingredient_text = line_soup.get_text(strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                # Пропускаем пустые строки
                if not ingredient_text:
                    continue
                
                # Пропускаем заголовки секций (содержат "Для" и заканчиваются на ":")
                if re.match(r'^Для\s+.*:$', ingredient_text):
                    continue
                
                # Пропускаем строки, которые заканчиваются на ":" (другие заголовки)
                if ingredient_text.endswith(':'):
                    continue
                
                # Парсим ингредиент
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "— вершкове масло, 100 г;" или "Масло вершкове — 75 г"
            
        Returns:
            dict: {"name": "вершкове масло", "amount": "100", "units": "г"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Убираем начальные символы вроде "—", "•", "*"
        text = re.sub(r'^[—–\-•*\s]+', '', text)
        
        # Убираем точку с запятой и точку в конце
        text = re.sub(r'[;.]+$', '', text)
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн 1: "название, количество единица" (— вершкове масло, 100 г)
        pattern1 = r'^([^,]+),\s*([\d\s/.,–\-]+)\s*([а-яА-ЯіїєґІЇЄҐa-zA-Z.]+)?'
        match1 = re.match(pattern1, text)
        
        if match1:
            name = match1.group(1).strip()
            amount = match1.group(2).strip()
            units = match1.group(3).strip() if match1.group(3) else None
            
            # Обрабатываем диапазоны вроде "150–200"
            amount = re.sub(r'\s+', '', amount)  # Убираем пробелы
            
            return {
                "name": name,
                "amount": amount if amount else None,
                "units": units
            }
        
        # Паттерн 2: "название — количество единица" (Масло вершкове — 75 г)
        pattern2 = r'^([^—–\-]+)[—–\-]\s*([\d\s/.,–\-]+)\s*([а-яА-ЯіїєґІЇЄҐa-zA-Z.]+)?'
        match2 = re.match(pattern2, text)
        
        if match2:
            name = match2.group(1).strip()
            amount = match2.group(2).strip()
            units = match2.group(3).strip() if match2.group(3) else None
            
            # Обрабатываем диапазоны
            amount = re.sub(r'\s+', '', amount)
            
            return {
                "name": name,
                "amount": amount if amount else None,
                "units": units
            }
        
        # Паттерн 3: "количество единица название"
        pattern3 = r'^([\d\s/.,–\-]+)\s*([а-яА-ЯіїєґІЇЄҐa-zA-Z.]+)\s+(.+)'
        match3 = re.match(pattern3, text)
        
        if match3:
            amount = match3.group(1).strip()
            units = match3.group(2).strip()
            name = match3.group(3).strip()
            
            # Обрабатываем диапазоны
            amount = re.sub(r'\s+', '', amount)
            
            return {
                "name": name,
                "amount": amount if amount else None,
                "units": units
            }
        
        # Если ничего не совпало, возвращаем только название
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем заголовок "Приготування" или похожий
        content_div = self.soup.find('div', class_='entry-content')
        if not content_div:
            return None
        
        # Ищем заголовок с инструкциями (может быть h3, h2, p, или strong)
        instruction_heading = None
        for elem in content_div.find_all(['h3', 'h2', 'p', 'strong']):
            heading_text = elem.get_text(strip=True)
            if 'риготування' in heading_text or 'пособ приготування' in heading_text:
                # Если это strong внутри p, берем родительский p
                if elem.name == 'strong':
                    instruction_heading = elem.parent
                else:
                    instruction_heading = elem
                break
        
        if instruction_heading:
            # Находим следующий список после заголовка
            instruction_list = instruction_heading.find_next(['ol', 'ul'], class_='wp-block-list')
            if not instruction_list:
                # Если список не найден, пробуем найти его как следующий sibling
                instruction_list = instruction_heading.find_next(['ol', 'ul'])
            
            if instruction_list:
                # Извлекаем шаги из списка (без вложенных заголовков)
                step_num = 1
                for li in instruction_list.find_all('li', recursive=False):
                    # Получаем все вложенные ul/ol списки
                    nested_lists = li.find_all(['ul', 'ol'])
                    
                    # Если есть вложенные списки, извлекаем текст только из них
                    if nested_lists:
                        for nested_list in nested_lists:
                            for nested_li in nested_list.find_all('li', recursive=False):
                                step_text = nested_li.get_text(separator=' ', strip=True)
                                step_text = self.clean_text(step_text)
                                
                                if step_text:
                                    steps.append(f"{step_num}. {step_text}")
                                    step_num += 1
                    else:
                        # Нет вложенных списков, берем текст напрямую
                        step_text = li.get_text(separator=' ', strip=True)
                        step_text = self.clean_text(step_text)
                        
                        # Пропускаем заголовки (заканчиваются на ":")
                        if step_text and not step_text.endswith(':'):
                            steps.append(f"{step_num}. {step_text}")
                            step_num += 1
        
        # Объединяем все шаги в одну строку
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            category = self.clean_text(meta_section['content'])
            # Преобразуем "Кулінарія" в "Dessert" или аналогичное
            if category == 'Кулінарія':
                return 'Dessert'
            return category
        
        return 'Dessert'  # По умолчанию для glaznews
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На glaznews.com время обычно не структурировано
        # Ищем в тексте упоминания времени подготовки
        content_div = self.soup.find('div', class_='entry-content')
        if not content_div:
            return None
        
        text = content_div.get_text()
        
        # Паттерны для поиска времени подготовки
        prep_patterns = [
            r'підготовка[:\s]*(\d+\s*(?:хв|хвилин|годин|год))',
            r'час\s+підготовки[:\s]*(\d+\s*(?:хв|хвилин|годин|год))',
        ]
        
        for pattern in prep_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                time_str = match.group(1)
                # Преобразуем в стандартный формат
                time_str = re.sub(r'хв(илин)?', 'minutes', time_str)
                time_str = re.sub(r'год(ин)?', 'hours', time_str)
                return time_str.strip()
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        content_div = self.soup.find('div', class_='entry-content')
        if not content_div:
            return None
        
        text = content_div.get_text()
        
        # Паттерны для поиска времени приготовления
        cook_patterns = [
            r'готування[:\s]*(\d+\s*(?:хв|хвилин|годин|год))',
            r'випік[а-я]*[:\s]*(\d+\s*(?:хв|хвилин|годин|год))',
            r'час\s+готування[:\s]*(\d+\s*(?:хв|хвилин|годин|год))',
        ]
        
        for pattern in cook_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                time_str = match.group(1)
                # Преобразуем в стандартный формат
                time_str = re.sub(r'хв(илин)?', 'minutes', time_str)
                time_str = re.sub(r'год(ин)?', 'hours', time_str)
                return time_str.strip()
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        content_div = self.soup.find('div', class_='entry-content')
        if not content_div:
            return None
        
        text = content_div.get_text()
        
        # Паттерны для поиска общего времени
        total_patterns = [
            r'загальний\s+час[:\s]*(\d+\s*(?:хв|хвилин|годин|год))',
            r'час\s+приготування[:\s]*(\d+\s*(?:хв|хвилин|годин|год))',
        ]
        
        for pattern in total_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                time_str = match.group(1)
                # Преобразуем в стандартный формат
                time_str = re.sub(r'хв(илин)?', 'minutes', time_str)
                time_str = re.sub(r'год(ин)?', 'hours', time_str)
                return time_str.strip()
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию "Поради" (Советы)
        content_div = self.soup.find('div', class_='entry-content')
        if not content_div:
            return None
        
        # Ищем заголовок с советами
        for h3 in content_div.find_all(['h3', 'h2']):
            heading_text = h3.get_text(strip=True)
            if 'оради' in heading_text or 'овіт' in heading_text:
                # Находим следующий список или параграф
                notes_list = h3.find_next(['ul', 'ol', 'p'])
                if notes_list:
                    if notes_list.name in ['ul', 'ol']:
                        # Извлекаем только первый элемент списка
                        first_li = notes_list.find('li')
                        if first_li:
                            note_text = first_li.get_text(separator=' ', strip=True)
                            return self.clean_text(note_text) if note_text else None
                    else:
                        # Это параграф
                        note_text = notes_list.get_text(separator=' ', strip=True)
                        return self.clean_text(note_text) if note_text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # 1. Ищем в entry-tags
        entry_tags = self.soup.find('p', class_='entry-tags')
        if entry_tags:
            tag_links = entry_tags.find_all('a', class_='entry-tag')
            for tag_link in tag_links:
                tag_text = tag_link.get_text(strip=True)
                if tag_text:
                    tags.append(tag_text)
        
        # 2. Если не нашли, ищем в meta тегах article:tag
        if not tags:
            article_tags = self.soup.find_all('meta', property='article:tag')
            for meta_tag in article_tags:
                tag_content = meta_tag.get('content')
                if tag_content:
                    tags.append(tag_content)
        
        # Удаляем дубликаты, сохраняя порядок
        if tags:
            seen = set()
            unique_tags = []
            for tag in tags:
                tag_lower = tag.lower()
                if tag_lower not in seen:
                    seen.add(tag_lower)
                    unique_tags.append(tag)
            
            return ', '.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в meta og:image (главное изображение)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в entry-featured-media
        featured_media = self.soup.find('div', class_='entry-featured-media')
        if featured_media:
            img = featured_media.find('img')
            if img and img.get('src'):
                urls.append(img['src'])
        
        # 3. Ищем изображения в контенте
        content_div = self.soup.find('div', class_='entry-content')
        if content_div:
            content_images = content_div.find_all('img', limit=3)
            for img in content_images:
                src = img.get('src')
                if src and 'wp-content/uploads' in src:
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
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "glaznews_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(GlaznewsExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python glaznews_com.py")


if __name__ == "__main__":
    main()
