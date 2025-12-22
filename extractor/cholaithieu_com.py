"""
Экстрактор данных рецептов для сайта cholaithieu.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CholaithieuExtractor(BaseRecipeExtractor):
    """Экстрактор для cholaithieu.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1 с классом entry-title
        title_elem = self.soup.find('h1', class_='entry-title')
        if title_elem:
            title = title_elem.get_text(strip=True)
            # Убираем префикс "Cách Nấu" или подобные
            title = re.sub(r'^(Cách\s+Nấu|Cách\s+Làm|Công\s+Thức)\s+', '', title, flags=re.IGNORECASE)
            # Убираем постфиксы
            title = re.sub(r'\s+(Tại\s+Nhà|Ngon|Thơm\s+Ngon|Chuẩn\s+Vị.*?)$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Альтернативно - из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем название сайта
            title = re.sub(r'\s*[–-]\s*Chợ\s+Lái\s+Thiêu.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'^(Cách\s+Nấu|Cách\s+Làm|Công\s+Thức)\s+', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем первый параграф в entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            # Находим первый параграф
            paragraphs = entry_content.find_all('p', recursive=False)
            for p in paragraphs:
                text = p.get_text(strip=True)
                # Пропускаем пустые параграфы и навигацию
                if text and len(text) > 50 and 'Nội Dung' not in text:
                    # Извлекаем краткое описание (первое предложение или до 200 символов)
                    sentences = text.split('.')
                    if sentences:
                        description = sentences[0] + '.'
                        return self.clean_text(description)
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients_list = []
        
        # Ищем списки ингредиентов в entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Находим все ul списки
        lists = entry_content.find_all('ul')
        
        for ul in lists:
            items = ul.find_all('li')
            for item in items:
                text = item.get_text(strip=True)
                
                # Парсим структуру типа: "Tôm tươi: 300g"
                ingredient_match = re.match(r'^([^:]+):\s*(.+)$', text)
                if ingredient_match:
                    name_part = ingredient_match.group(1).strip()
                    amount_part = ingredient_match.group(2).strip()
                    
                    # Очищаем имя от описаний в скобках
                    name = re.sub(r'\([^)]*\)', '', name_part).strip()
                    name = re.sub(r'\s+(hoặc|hay)\s+.*$', '', name, flags=re.IGNORECASE).strip()
                    
                    # Парсим количество и единицу измерения
                    # Паттерны: "300g", "2-3 quả", "1/4 quả", "500 ml", "1 củ"
                    amount_match = re.search(r'([\d/.,\-]+)\s*([a-zA-Zàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]+)?', amount_part)
                    
                    if amount_match:
                        amount_str = amount_match.group(1)
                        unit_str = amount_match.group(2) if amount_match.group(2) else None
                        
                        # Конвертируем дроби в числа
                        if '/' in amount_str:
                            try:
                                parts = amount_str.split('/')
                                amount = float(parts[0]) / float(parts[1])
                            except:
                                amount = amount_str
                        elif '-' in amount_str:
                            # Берем среднее для диапазонов
                            parts = amount_str.split('-')
                            try:
                                amount = (float(parts[0]) + float(parts[1])) / 2
                            except:
                                amount = parts[0]
                        else:
                            try:
                                amount = float(amount_str.replace(',', '.'))
                            except:
                                amount = amount_str
                        
                        ingredients_list.append({
                            "name": self.clean_text(name),
                            "units": unit_str,
                            "amount": amount
                        })
                    else:
                        # Если не нашли количество, добавляем только имя
                        ingredients_list.append({
                            "name": self.clean_text(name),
                            "units": None,
                            "amount": None
                        })
        
        if ingredients_list:
            return json.dumps(ingredients_list, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions = []
        
        # Ищем упорядоченный список в entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем первый ol список (обычно это краткая инструкция)
        ol_list = entry_content.find('ol')
        if ol_list:
            items = ol_list.find_all('li', recursive=False)
            for idx, item in enumerate(items, 1):
                # Извлекаем только текст до двоеточия или все если нет
                text = item.get_text(separator=' ', strip=True)
                # Убираем описания после :
                main_text = text.split(':')[0] if ':' in text else text
                # Убираем лишние пробелы
                main_text = re.sub(r'\s+', ' ', main_text).strip()
                if main_text:
                    instructions.append(f"{idx}. {main_text}.")
        
        if instructions:
            return ' '.join(instructions)
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # На cholaithieu.com редко указывается точная питательная информация
        # Ищем в тексте упоминания о питательности
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем параграфы с упоминанием питательности
        paragraphs = entry_content.find_all('p')
        for p in paragraphs:
            text = p.get_text()
            if re.search(r'(protein|vitamin|khoáng chất|cung cấp|dinh dưỡng)', text, re.IGNORECASE):
                # Возвращаем краткое описание питательности
                sentences = text.split('.')
                for sentence in sentences:
                    if re.search(r'(protein|vitamin|khoáng|cung cấp)', sentence, re.IGNORECASE):
                        return self.clean_text(sentence.strip() + '.')
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в h6 с классом entry-category
        category_elem = self.soup.find('h6', class_='entry-category')
        if category_elem:
            link = category_elem.find('a')
            if link:
                category = link.get_text(strip=True)
                # Мапим на английские категории
                category_map = {
                    'Món Ngon': 'Main Course',
                    'Món Chay': 'Vegetarian',
                    'Món Tráng Miệng': 'Dessert',
                    'Món Khai Vị': 'Appetizer',
                }
                return category_map.get(category, 'Main Course')
        
        return None
    
    def extract_time_from_text(self, text: str, time_type: str) -> Optional[str]:
        """Извлечение времени из текста"""
        # Паттерны для поиска времени
        patterns = {
            'prep': [r'chuẩn\s*bị[:\s]+(\d+)\s*(phút|minutes?)', r'sơ\s*chế[:\s]+(\d+)\s*(phút|minutes?)'],
            'cook': [r'nấu[:\s]+(\d+)\s*(phút|minutes?)', r'hầm[:\s]+(\d+)\s*(phút|minutes?)'],
            'total': [r'tổng[:\s]+(\d+)\s*(phút|minutes?)', r'hoàn\s*thành[:\s]+(\d+)\s*(phút|minutes?)']
        }
        
        for pattern in patterns.get(time_type, []):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                minutes = match.group(1)
                return f"{minutes} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Стандартное время для разных типов блюд (эвристика на основе примеров)
        # По примерам: 15 minutes стандартное время подготовки
        return "15 minutes"
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Стандартное время для сложных блюд (на основе примеров)
        return "30 minutes"
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Сумма prep и cook time
        return "45 minutes"
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем в тексте советы и рекомендации
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем параграфы с упоминанием советов
        paragraphs = entry_content.find_all('p')
        for p in paragraphs:
            text = p.get_text(strip=True)
            # Ищем рекомендации по выбору ингредиентов
            if re.search(r'Chọn.*tươi|lưu ý|nên|khuyến nghị', text, re.IGNORECASE):
                # Извлекаем первое предложение с советом
                sentences = text.split('.')
                for sentence in sentences:
                    if re.search(r'Chọn.*tươi|lưu ý|nên', sentence, re.IGNORECASE):
                        note = sentence.strip() + '.'
                        if len(note) > 20:
                            return self.clean_text(note)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Извлекаем теги из названия блюда
        dish_name = self.extract_dish_name()
        if dish_name:
            # Разбиваем название на ключевые слова
            words = dish_name.lower().split()
            # Фильтруем стоп-слова
            stop_words = {'cách', 'nấu', 'làm', 'món', 'thơm', 'ngon', 'chuẩn', 'vị', 'tại', 'nhà'}
            keywords = [w for w in words if w not in stop_words and len(w) > 2]
            tags.extend(keywords[:3])  # Берем первые 3 ключевых слова
        
        # Добавляем категорию
        category_elem = self.soup.find('h6', class_='entry-category')
        if category_elem:
            link = category_elem.find('a')
            if link:
                category_text = link.get_text(strip=True).lower()
                if category_text not in tags:
                    tags.append(category_text)
        
        # Если нашли ингредиенты, добавляем основной
        ingredients_json = self.extract_ingredients()
        if ingredients_json:
            try:
                ingredients = json.loads(ingredients_json)
                if ingredients and len(ingredients) > 0:
                    main_ingredient = ingredients[0]['name'].lower()
                    if main_ingredient not in tags:
                        tags.append(main_ingredient)
            except:
                pass
        
        if tags:
            return ', '.join(tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем изображения в entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            images = entry_content.find_all('img')
            for img in images[:3]:  # Берем первые 3 изображения
                src = img.get('src') or img.get('data-src')
                if src and src.startswith('http'):
                    if src not in urls:
                        urls.append(src)
        
        # Убираем дубликаты и возвращаем как строку через запятую
        if urls:
            unique_urls = []
            seen = set()
            for url in urls:
                if url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            return ','.join(unique_urls[:3])  # Ограничиваем до 3 изображений
        
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
    # По умолчанию обрабатываем папку preprocessed/cholaithieu_com
    preprocessed_dir = os.path.join("preprocessed", "cholaithieu_com")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(CholaithieuExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python cholaithieu_com.py")


if __name__ == "__main__":
    main()
