"""
Экстрактор данных рецептов для сайта thuongbep.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ThuongbepExtractor(BaseRecipeExtractor):
    """Экстрактор для thuongbep.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1 с классом post-title
        h1 = self.soup.find('h1', class_='post-title')
        if h1:
            name = self.clean_text(h1.get_text())
            
            if name:
                # Убираем дополнительные описания после тире, двоеточия
                name = re.split(r'\s*[–—-]\s*', name)[0]
                name = re.split(r'\s*:\s*', name)[0]
                
                # Убираем лишние слова в конце типа "NGON", "SẼ KHIẾN BẠN..."
                # Оставляем только основное название
                words = name.split()
                # Если название слишком длинное, обрезаем до разумного
                if len(words) > 5:
                    # Ищем ключевые слова, после которых обрезаем
                    stop_words = ['ngon', 'sẽ', 'khiến', 'để', 'cho', 'cách', 'làm', 'với']
                    for i, word in enumerate(words):
                        if word.lower() in stop_words:
                            name = ' '.join(words[:i])
                            break
                
                # Нормализуем капитализацию
                # Если все в верхнем регистре, делаем только первую букву заглавной для каждого слова,
                # НО сохраняем строчные для остальных букв (не title case)
                if name.isupper():
                    # Делаем все строчными, потом первую букву заглавной
                    name = name.lower()
                    # Делаем первую букву заглавной
                    if name:
                        name = name[0].upper() + name[1:]
                
                return name if name else None
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = self.clean_text(og_title['content'])
            # Убираем дополнительные слова
            title = re.split(r'\s*[–—-]\s*', title)[0]
            return title
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем первый значимый параграф в контенте
        content_div = self.soup.find('div', class_='inner-post-entry')
        if content_div:
            # Пропускаем параграфы с "Nội dung bài viết" и другие служебные
            for p in content_div.find_all('p'):
                text = self.clean_text(p.get_text())
                # Пропускаем короткие и служебные параграфы
                if text and len(text) > 20:
                    # Пропускаем если это "Nội dung bài viết" или начинается с заголовка
                    if 'nội dung bài viết' not in text.lower() and not text.startswith('Bước'):
                        # Берем только первое предложение для краткости
                        sentences = text.split('.')
                        if sentences:
                            first_sentence = sentences[0].strip()
                            if first_sentence and len(first_sentence) > 20:
                                return first_sentence + ('.' if not first_sentence.endswith('.') else '')
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате JSON"""
        ingredients = []
        
        # Ищем блок ингредиентов - может быть после h2 или h3 с "Thành phần" или "Nguyên liệu"
        content_div = self.soup.find('div', class_='inner-post-entry')
        if not content_div:
            return None
        
        # Ищем h2 и h3 заголовки
        headers = content_div.find_all(['h2', 'h3'])
        
        for header in headers:
            header_text = self.clean_text(header.get_text()).lower()
            
            # Проверяем, что это заголовок ингредиентов
            if 'thành phần' in header_text or 'nguyên liệu' in header_text:
                # Ищем все ul после этого заголовка до следующего h2/h3
                next_elem = header.find_next_sibling()
                
                while next_elem:
                    # Останавливаемся на следующем заголовке (не включая h4)
                    if next_elem.name in ['h2', 'h3']:
                        break
                    
                    # Если нашли ul, извлекаем ингредиенты
                    if next_elem.name == 'ul':
                        items = next_elem.find_all('li')
                        
                        for item in items:
                            ingredient_text = item.get_text(separator=' ', strip=True)
                            ingredient_text = self.clean_text(ingredient_text)
                            
                            # Пропускаем слишком короткие или явно не являющиеся ингредиентами строки
                            if ingredient_text and len(ingredient_text) > 1:
                                # Парсим ингредиент
                                parsed = self.parse_ingredient(ingredient_text)
                                if parsed:
                                    ingredients.append(parsed)
                    
                    next_elem = next_elem.find_next_sibling()
                
                if ingredients:
                    break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1.5 pound khoai tây nhỏ" или "Muối"
            
        Returns:
            dict: {"name": "khoai tây nhỏ", "amount": "1.5", "unit": "pound"} или None
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
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1.5 pound khoai tây", "2 thìa canh dầu", "Muối"
        pattern = r'^([\d\s/.,\-]+)?\s*(pound|pounds|thìa\s+cà\s+phê|thìa\s+canh|quả|cup|cups|gram|grams|g|kg|ml|l|slices?|stalks?|pieces?|stick|cloves?|small|teaspoons?|tablespoons?|thia\s+ca\s+phe|thia\s+canh)?\s*(.+)'
        
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
            # Обработка дробей типа "1/2" или "1-2" (диапазоны)
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                amount = str(total) if total != int(total) else str(int(total))
            elif '-' in amount_str and len(amount_str) < 6:
                # Диапазон типа "1-2" или "2-3" - оставляем как есть
                amount = amount_str
            else:
                try:
                    amount_float = float(amount_str.replace(',', '.'))
                    amount = str(amount_float) if amount_float != int(amount_float) else str(int(amount_float))
                except ValueError:
                    amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        name = name.strip() if name else text
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем все параграфы с "Bước"
        content_div = self.soup.find('div', class_='inner-post-entry')
        if not content_div:
            return None
        
        # Ищем все параграфы, которые начинаются с "Bước"
        all_p = content_div.find_all('p')
        
        for p in all_p:
            text = p.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            
            # Проверяем, начинается ли с "Bước"
            if text and re.match(r'^Bước\s+\d+', text, re.IGNORECASE):
                # Нормализуем форматирование: убираем лишние пробелы перед двоеточием
                text = re.sub(r'\s+:', ':', text)
                # Убираем пробел после двоеточия в "Bước N :"
                text = re.sub(r'^(Bước\s+\d+)\s+:', r'\1:', text)
                steps.append(text)
        
        return ' '.join(steps) if steps else None
    
    def extract_time_from_table(self, column_index: int) -> Optional[str]:
        """
        Извлечение времени из таблицы
        
        Args:
            column_index: Индекс колонки (0 - prep, 1 - cook, 2 - total)
        """
        # Ищем все таблицы (первая обычно nutrition, вторая - время)
        tables = self.soup.find_all('figure', class_='wp-block-table')
        
        # Проверяем каждую таблицу на наличие информации о времени
        for table in tables:
            tbody = table.find('tbody')
            if not tbody:
                tbody = table.find('table')
            
            if tbody:
                rows = tbody.find_all('tr')
                if len(rows) >= 2:  # Должно быть минимум 2 строки (заголовок + данные)
                    # Проверяем первую строку на ключевые слова времени
                    header_row = rows[0]
                    header_text = header_row.get_text().lower()
                    
                    if 'thời gian' in header_text or 'chuẩn bị' in header_text or 'nấu' in header_text:
                        # Это таблица с временем
                        data_row = rows[1]
                        cells = data_row.find_all('td')
                        
                        if len(cells) > column_index:
                            time_text = self.clean_text(cells[column_index].get_text())
                            # Нормализуем формат времени
                            time_text = re.sub(r'[Pp]hút', 'minutes', time_text, flags=re.IGNORECASE)
                            return time_text if time_text else None
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time_from_table(0)
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Проверяем структуру таблицы
        tables = self.soup.find_all('figure', class_='wp-block-table')
        
        for table in tables:
            tbody = table.find('tbody') or table.find('table')
            if tbody:
                rows = tbody.find_all('tr')
                if len(rows) >= 2:
                    header_row = rows[0]
                    header_text = header_row.get_text().lower()
                    
                    if 'thời gian' in header_text:
                        header_cells = header_row.find_all('td')
                        
                        # Если есть отдельная колонка "Thời gian nấu", используем её
                        for i, cell in enumerate(header_cells):
                            cell_text = cell.get_text().lower()
                            if 'nấu' in cell_text and 'tổng' not in cell_text:
                                data_row = rows[1]
                                data_cells = data_row.find_all('td')
                                if len(data_cells) > i:
                                    time_text = self.clean_text(data_cells[i].get_text())
                                    time_text = re.sub(r'[Pp]hút', 'minutes', time_text, flags=re.IGNORECASE)
                                    return time_text if time_text else None
                        
                        # Если только 2 колонки: "chuẩn bị" и "tổng thời gian"
                        # то "tổng thời gian" трактуется как cook_time
                        if len(header_cells) == 2:
                            col0_text = header_cells[0].get_text().lower()
                            col1_text = header_cells[1].get_text().lower()
                            
                            if 'chuẩn bị' in col0_text and 'tổng' in col1_text:
                                # Это случай, когда "Tổng thời gian" = cook_time
                                data_row = rows[1]
                                data_cells = data_row.find_all('td')
                                if len(data_cells) > 1:
                                    time_text = self.clean_text(data_cells[1].get_text())
                                    time_text = re.sub(r'[Pp]hút', 'minutes', time_text, flags=re.IGNORECASE)
                                    return time_text if time_text else None
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Сначала проверяем, есть ли явная колонка "tổng thời gian" в таблице с 3+ колонками
        tables = self.soup.find_all('figure', class_='wp-block-table')
        
        for table in tables:
            tbody = table.find('tbody') or table.find('table')
            if tbody:
                rows = tbody.find_all('tr')
                if len(rows) >= 2:
                    header_row = rows[0]
                    header_text = header_row.get_text().lower()
                    
                    if 'thời gian' in header_text:
                        header_cells = header_row.find_all('td')
                        
                        # Если 3+ колонки, ищем "tổng thời gian"
                        if len(header_cells) >= 3:
                            for i, cell in enumerate(header_cells):
                                if 'tổng' in cell.get_text().lower():
                                    data_row = rows[1]
                                    data_cells = data_row.find_all('td')
                                    if len(data_cells) > i:
                                        time_text = self.clean_text(data_cells[i].get_text())
                                        time_text = re.sub(r'[Pp]hút', 'minutes', time_text, flags=re.IGNORECASE)
                                        return time_text if time_text else None
                        
                        # Если только 2 колонки, вычисляем: prep + cook
                        elif len(header_cells) == 2:
                            prep = self.extract_prep_time()
                            cook = self.extract_cook_time()
                            
                            if prep and cook:
                                # Извлекаем числа из строк
                                prep_num = int(re.search(r'\d+', prep).group()) if re.search(r'\d+', prep) else 0
                                cook_num = int(re.search(r'\d+', cook).group()) if re.search(r'\d+', cook) else 0
                                
                                total = prep_num + cook_num
                                return f"{total} minutes"
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории из breadcrumbs"""
        # Ищем breadcrumbs
        breadcrumb = self.soup.find('div', class_='penci-breadcrumb')
        if not breadcrumb:
            return None
        
        # Ищем все ссылки
        links = breadcrumb.find_all('a', class_='crumb')
        
        # Берем последнюю категорию (обычно самая специфичная)
        if links and len(links) > 1:
            # Пропускаем первую ссылку (обычно "Trang chủ" - главная)
            for link in reversed(links[1:]):
                category = self.clean_text(link.get_text())
                if category and category.lower() not in ['trang chủ', 'home']:
                    return category
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем параграфы, начинающиеся с "Lưu ý:", "Mẹo:", "Ghi chú:" и т.д.
        content_div = self.soup.find('div', class_='inner-post-entry')
        if content_div:
            for p in content_div.find_all('p'):
                text = p.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                
                # Проверяем, начинается ли с ключевых слов для заметок
                if text and any(text.lower().startswith(keyword) for keyword in ['lưu ý:', 'mẹo:', 'ghi chú:', 'chú ý:']):
                    # Убираем префикс "Lưu ý:" и т.д.
                    for keyword in ['lưu ý:', 'mẹo:', 'ghi chú:', 'chú ý:']:
                        if text.lower().startswith(keyword):
                            text = text[len(keyword):].strip()
                            break
                    
                    # Пропускаем стандартные заметки о питательности
                    if 'thông tin' not in text.lower() or 'dinh dưỡng' not in text.lower():
                        if text and len(text) > 15:
                            notes.append(text)
            
            # Также ищем в blockquotes, которые содержат "Mẹo"
            blockquotes = content_div.find_all('blockquote', class_='wp-block-quote')
            for bq in blockquotes:
                text = bq.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                
                # Берем только те, что начинаются с "Mẹo" и не являются ссылками
                if text and text.lower().startswith('mẹo'):
                    # Пропускаем ссылки на другие рецепты
                    if not any(skip in text.lower() for skip in ['tham khảo thêm', 'bạn có thể quan tâm', 'xem thêm']):
                        # Убираем "Mẹo đơn giản:" или "Mẹo:"
                        text = re.sub(r'^mẹo[^:]*:\s*', '', text, flags=re.IGNORECASE)
                        if text and len(text) > 20:
                            notes.append(text)
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем теги в метаданных или в разметке страницы
        tags_list = []
        
        # Проверяем meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        # Если не нашли в meta, ищем в разметке тегов статьи
        if not tags_list:
            tag_links = self.soup.find_all('a', rel='tag')
            if tag_links:
                tags_list = [self.clean_text(tag.get_text()) for tag in tag_links if tag.get_text()]
        
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем изображения в контенте статьи
        content_div = self.soup.find('div', class_='inner-post-entry')
        if content_div:
            # Ищем все изображения в фигурах
            figures = content_div.find_all('figure', class_='wp-block-image')
            for figure in figures[:3]:  # Берем максимум 3 изображения
                img = figure.find('img')
                if img and img.get('src'):
                    urls.append(img['src'])
            
            # Если в фигурах не нашли, ищем просто img
            if not urls:
                imgs = content_div.find_all('img')
                for img in imgs[:3]:
                    if img.get('src'):
                        url = img['src']
                        # Пропускаем маленькие иконки и служебные изображения
                        if 'icon' not in url.lower() and 'logo' not in url.lower():
                            urls.append(url)
        
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/thuongbep_com
    recipes_dir = os.path.join("preprocessed", "thuongbep_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(ThuongbepExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python thuongbep_com.py")


if __name__ == "__main__":
    main()
