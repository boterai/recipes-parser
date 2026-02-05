"""
Экстрактор данных рецептов для сайта resepmasakanlafancy.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ResepMasakanLaFancyExtractor(BaseRecipeExtractor):
    """Экстрактор для resepmasakanlafancy.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем найти в h1.entry-title
        entry_title = self.soup.find('h1', class_='entry-title')
        if entry_title:
            title = self.clean_text(entry_title.get_text())
            # Убираем префиксы типа "Inspirasi Masakan: Resep"
            title = re.sub(r'^(?:Inspirasi\s+Masakan:\s*)?Resep\s+', '', title, flags=re.IGNORECASE)
            # Убираем суффиксы типа "ala La Fancy yang Menggoda"
            title = re.sub(r'\s+ala\s+La\s+Fancy.*$', '', title, flags=re.IGNORECASE)
            # Убираем длинные суффиксы через запятую
            if ',' in title:
                title = title.split(',')[0].strip()
            return title
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - Resep Masakan La Fancy"
            title = re.sub(r'\s+-\s+Resep\s+Masakan.*$', '', title, flags=re.IGNORECASE)
            # Убираем префиксы
            title = re.sub(r'^(?:Inspirasi\s+Masakan:\s*)?Resep\s+', '', title, flags=re.IGNORECASE)
            # Убираем "ala La Fancy"
            title = re.sub(r'\s+ala\s+La\s+Fancy.*$', '', title, flags=re.IGNORECASE)
            # Убираем длинные суффиксы через запятую
            if ',' in title:
                title = title.split(',')[0].strip()
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
    
    def parse_ingredient_text(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            text: Строка вида "300 gram ayam cincang" или "1 buah wortel"
            
        Returns:
            dict: {"name": "ayam cincang", "amount": "300", "unit": "gram"} или None
        """
        if not text:
            return None
        
        # Чистим текст
        text = self.clean_text(text).lower()
        
        # Удаляем HTML entities и лишние символы
        text = re.sub(r'&nbsp;', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "300 gram ayam cincang", "1 buah wortel", "20 lembar kulit shumai"
        # Индонезийские единицы: gram, buah, lembar, sdt, sdm, butir, batang, siung, ml, dll.
        pattern = r'^([\d\s/.,]+)?\s*(gram|buah|lembar|sdt|sdm|butir|batang|siung|ml|liter|kg|potong|iris|sendok\s+teh|sendok\s+makan)?\s*(.+?)(?:\s*,.*)?$'
        
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
            # Обработка дробей типа "1/2"
            if '/' in amount_str:
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
                # Конвертируем в число (int или float)
                try:
                    amount_float = float(amount_str.replace(',', '.'))
                    # Если это целое число, возвращаем int
                    if amount_float.is_integer():
                        amount = int(amount_float)
                    else:
                        amount = amount_float
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения
        units = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем всё после запятой (обычно там примечания)
        name = name.split(',')[0].strip()
        # Удаляем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        
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
        
        # Ищем все списки ингредиентов (ul.wp-block-list)
        post_content = self.soup.find(class_='post-content')
        if not post_content:
            return None
        
        # Находим все ul.wp-block-list до первого ol.wp-block-list (инструкции)
        for element in post_content.find_all(['ul', 'ol'], class_='wp-block-list'):
            # Останавливаемся, когда дошли до инструкций (ol)
            if element.name == 'ol':
                break
            
            # Обрабатываем ul (ингредиенты)
            if element.name == 'ul':
                items = element.find_all('li', recursive=False)
                for item in items:
                    ingredient_text = item.get_text(separator=' ', strip=True)
                    ingredient_text = self.clean_text(ingredient_text)
                    
                    # Пропускаем заголовки секций (обычно содержат двоеточие или выделены жирным)
                    if ':' in ingredient_text or len(ingredient_text) < 5:
                        continue
                    
                    # Парсим в структурированный формат
                    parsed = self.parse_ingredient_text(ingredient_text)
                    if parsed and parsed['name']:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем ol.wp-block-list (инструкции)
        post_content = self.soup.find(class_='post-content')
        if not post_content:
            return None
        
        # Находим все ol.wp-block-list
        instruction_lists = post_content.find_all('ol', class_='wp-block-list')
        
        for ol in instruction_lists:
            # Проверяем, что это инструкции приготовления, а не советы
            # (советы обычно идут после заголовка "Tips")
            prev_heading = None
            for prev in ol.find_all_previous(['h2', 'h3']):
                if 'tips' in prev.get_text().lower() or 'fun fact' in prev.get_text().lower():
                    prev_heading = prev
                    break
            
            # Если предыдущий заголовок - это Tips, пропускаем этот список
            if prev_heading and ol in prev_heading.find_all_next('ol'):
                continue
            
            items = ol.find_all('li', recursive=False)
            for item in items:
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем категории в post-meta (ссылки с rel="tag")
        post_meta = self.soup.find(class_='post-meta')
        if post_meta:
            # Ищем ссылки на категории (обычно "/kategori/...")
            category_links = post_meta.find_all('a', href=re.compile(r'/kategori/'))
            if category_links:
                # Берем самую специфичную категорию (обычно последняя перед тегами)
                for link in category_links:
                    category_text = self.clean_text(link.get_text())
                    # Пропускаем общие категории
                    if category_text and category_text not in ['Artikel', 'Jenis Masakan', 'Kategori Resep']:
                        return category_text
                
                # Если все категории общие, берем последнюю
                if category_links:
                    return self.clean_text(category_links[-1].get_text())
        
        return None
    
    def extract_time_from_text(self, text: str, time_type: str) -> Optional[str]:
        """
        Извлечение времени из текста инструкций
        
        Args:
            text: Текст для поиска
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        if not text:
            return None
        
        # Паттерны для поиска времени в тексте
        # Примеры: "25-30 menit", "10 menit", "1 jam"
        time_patterns = [
            r'(\d+(?:-\d+)?)\s*menit',  # "25-30 menit" или "10 menit"
            r'(\d+)\s*jam',  # "1 jam"
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, text.lower())
            if match:
                time_value = match.group(1)
                if 'jam' in match.group(0):
                    # Конвертируем часы в минуты
                    return f"{int(time_value) * 60} minutes"
                else:
                    return f"{time_value} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На этом сайте время обычно не разделено, попробуем найти в инструкциях
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем время приготовления в инструкциях
        post_content = self.soup.find(class_='post-content')
        if post_content:
            text = post_content.get_text()
            
            # Ищем все упоминания времени и выбираем самое длинное
            all_times = []
            
            # Поиск времени в часах
            hour_pattern = r'(?:kukus|goreng|rebus|masak|didihkan|presto|pressure cooker).*?(?:selama|kurang lebih|sekitar)?\s*(\d+(?:-\d+)?)\s*jam'
            for match in re.finditer(hour_pattern, text.lower()):
                time_value = match.group(1)
                if '-' in time_value:
                    times = time_value.split('-')
                    time_value = times[-1]
                all_times.append((int(time_value) * 60, f"{int(time_value)} hours"))
            
            # Поиск времени в минутах
            min_pattern = r'(?:kukus|goreng|rebus|masak|didihkan|presto|pressure cooker).*?(?:selama|kurang lebih|sekitar)?\s*(\d+(?:-\d+)?)\s*menit'
            for match in re.finditer(min_pattern, text.lower()):
                time_value = match.group(1)
                if '-' in time_value:
                    times = time_value.split('-')
                    time_value = times[-1]
                all_times.append((int(time_value), f"{time_value} minutes"))
            
            # Возвращаем самое длинное время (обычно это основное время приготовления)
            if all_times:
                all_times.sort(reverse=True)
                return all_times[0][1]
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # На этом сайте обычно не указано отдельно
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes_list = []
        
        # Ищем секцию с советами/tips
        post_content = self.soup.find(class_='post-content')
        if not post_content:
            return None
        
        # Находим заголовок "Tips"
        for heading in post_content.find_all(['h2', 'h3']):
            heading_text = heading.get_text()
            if re.search(r'Tips.*Sukses', heading_text, re.IGNORECASE):
                # Находим все следующие элементы до следующего заголовка
                current = heading.find_next_sibling()
                while current and current.name not in ['h2', 'h3']:
                    # Ищем списки с советами
                    if current.name in ['ol', 'ul'] and 'wp-block-list' in current.get('class', []):
                        items = current.find_all('li', recursive=False)
                        for item in items:
                            tip_text = item.get_text(separator=' ', strip=True)
                            tip_text = self.clean_text(tip_text)
                            # Убираем нумерацию в начале (если есть)
                            tip_text = re.sub(r'^\d+\.\s*', '', tip_text)
                            if tip_text and len(tip_text) > 10:
                                notes_list.append(tip_text)
                    current = current.find_next_sibling()
                break
        
        return ' '.join(notes_list) if notes_list else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Ищем теги в классах article (tag-*)
        article = self.soup.find('article')
        if article:
            classes = article.get('class', [])
            for cls in classes:
                if cls.startswith('tag-'):
                    # Убираем префикс "tag-" и заменяем дефисы на пробелы
                    tag_name = cls[4:].replace('-', ' ')
                    # Пропускаем слишком длинные теги (обычно это технические классы)
                    if len(tag_name) > 30:
                        continue
                    tags_list.append(tag_name.title())
        
        # Удаляем дубликаты и сортируем
        if tags_list:
            seen = set()
            unique_tags = []
            for tag in tags_list:
                tag_lower = tag.lower()
                if tag_lower not in seen:
                    seen.add(tag_lower)
                    # Форматируем для читаемости
                    formatted_tag = tag.replace('Resep ', '').replace('resep ', '')
                    # Удаляем повторяющиеся слова
                    words = formatted_tag.split()
                    if len(words) >= 2 and words[0].lower() == words[1].lower():
                        formatted_tag = ' '.join(words[1:])
                    unique_tags.append(formatted_tag)
            
            return ', '.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Главное изображение из og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Изображение из post-thumbnail
        post_thumbnail = self.soup.find('div', class_='post-thumbnail')
        if post_thumbnail:
            img = post_thumbnail.find('img')
            if img and img.get('src'):
                urls.append(img['src'])
        
        # 3. Изображения из контента (figure.wp-block-image)
        post_content = self.soup.find(class_='post-content')
        if post_content:
            figures = post_content.find_all('figure', class_='wp-block-image')
            for figure in figures:
                img = figure.find('img')
                if img and img.get('src'):
                    urls.append(img['src'])
        
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
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    """Обработка HTML файлов из директории preprocessed/resepmasakanlafancy_com"""
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "preprocessed",
        "resepmasakanlafancy_com"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ResepMasakanLaFancyExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python resepmasakanlafancy_com.py")


if __name__ == "__main__":
    main()
