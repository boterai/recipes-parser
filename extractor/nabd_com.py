"""
Экстрактор данных рецептов для сайта nabd.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class NabdExtractor(BaseRecipeExtractor):
    """Экстрактор для nabd.com"""
    
    def _get_recipe_paragraph(self):
        """Извлечение параграфа с рецептом из HTML"""
        # Ищем параграфы с рецептом (обычно содержат слова "مقادير" или "طريقة")
        paragraphs = self.soup.find_all('p', dir='rtl')
        
        for p in paragraphs:
            text = p.get_text()
            # Параграф с рецептом содержит слова "مقادير" и "طريقة تحضير"
            if 'مقادير' in text and 'طريقة تحضير' in text:
                return p  # Возвращаем элемент BeautifulSoup, а не текст
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Пробуем извлечь из og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем префикс сайта (например, "مرايتي |")
            title = re.sub(r'^[^|]+\|\s*', '', title)
            # Убираем суффиксы типа "طريقة عمل", "طريقة", ".."
            title = re.sub(r'(طريقة\s+عمل\s+|طريقة\s+|\.\.)', '', title)
            title = self.clean_text(title)
            return title if title else None
        
        # Альтернативно из тега title
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            title = re.sub(r'^[^|]+\|\s*', '', title)
            title = re.sub(r'(طريقة\s+عمل\s+|طريقة\s+|\.\.)', '', title)
            title = self.clean_text(title)
            return title if title else None
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Убираем префиксы типа "...."
            desc = re.sub(r'^\.+\s*', '', desc)
            desc = self.clean_text(desc)
            return desc if desc else None
        
        # Альтернативно из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            desc = re.sub(r'^\.+\s*', '', desc)
            desc = self.clean_text(desc)
            return desc if desc else None
        
        # Если не нашли в метатегах, попробуем найти в первом параграфе
        paragraphs = self.soup.find_all('p', dir='rtl')
        for p in paragraphs:
            text = p.get_text()
            # Берем первый параграф который не содержит "مقادير"
            if 'مقادير' not in text and len(text) > 30:
                text = self.clean_text(text)
                # Убираем лишние точки и пробелы
                text = re.sub(r'^\.+\s*', '', text)
                return text if text else None
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        recipe_paragraph = self._get_recipe_paragraph()
        if not recipe_paragraph:
            return None
        
        ingredients = []
        
        # Получаем HTML-строку параграфа
        recipe_html = str(recipe_paragraph)
        
        # Паттерн для извлечения ингредиентов
        # Ищем текст между "مقادير" и "طريقة тحضير"
        match = re.search(r'مقادير[^<]*?(.*?)طريقة تحضير', recipe_html, re.DOTALL)
        if not match:
            return None
        
        ingredients_text = match.group(1)
        
        # Разбиваем по <br><br> или <br/><br/>
        items = re.split(r'<br\s*/?>\s*<br\s*/?>', ingredients_text)
        
        for idx, item in enumerate(items):
            # Очищаем HTML теги
            item = re.sub(r'<[^>]+>', '', item)
            item = self.clean_text(item)
            
            if not item or len(item) < 2:
                continue
            
            # Первая строка может содержать название блюда перед первым ингредиентом
            # Например: "دونتس بحشو الشوكولاتة 3 كوب دقيق"
            # Нужно извлечь только "3 كوب دقيق"
            if idx == 0:
                # Ищем паттерн "количество единица название" в конце строки
                match_first = re.search(r'(\d+\s+(?:كوب|ملعقة كبيرة|ملعقة صغيرة|جرام|جم)\s+\S+)$', item)
                if match_first:
                    item = match_first.group(1)
            
            # Парсим ингредиент
            parsed = self.parse_ingredient(item)
            if parsed:
                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "3 كوب دقيق" или "سمك فيليه"
            
        Returns:
            dict: {"name": "دقيق", "amount": 3, "units": "كوب"} или None
        """
        if not ingredient_text:
            return None
        
        text = self.clean_text(ingredient_text)
        
        # Паттерны для единиц измерения на арабском
        units_pattern = r'(?:كوب|أكواب|ملعقة كبيرة|ملعقة صغيرة|ملعقة|جرام|جم|كيلو|كيلوجرام|لتر|مليلتر|رشة|عدد|فص|حبة|حبات|للعجن|للقلي|للحشو|للوجه|للتزيين)'
        
        # Паттерн: количество + единица + название
        # Например: "3 كوب دقيق"
        pattern1 = rf'^(\d+(?:\.\d+)?)\s+({units_pattern})\s+(.+)$'
        match = re.match(pattern1, text)
        
        if match:
            amount = match.group(1)
            unit = match.group(2)
            name = match.group(3)
            
            # Очищаем имя от лишних слов
            name = self._clean_ingredient_name(name)
            
            return {
                "name": name,
                "amount": int(float(amount)) if '.' not in amount else float(amount),
                "units": unit
            }
        
        # Паттерн: количество + название (без единицы)
        # Например: "1 بيضة"
        pattern2 = r'^(\d+(?:\.\d+)?)\s+(.+)$'
        match = re.match(pattern2, text)
        
        if match:
            amount = match.group(1)
            name = match.group(2)
            name = self._clean_ingredient_name(name)
            
            return {
                "name": name,
                "amount": int(float(amount)) if '.' not in amount else float(amount),
                "units": None
            }
        
        
        # Паттерн для "رشة" + название (рشة - это указание на малое количество)
        # Например: "رشة ملح"
        if text.startswith('رشة '):
            name = text[len('رشة '):].strip()
            name = self._clean_ingredient_name(name)
            return {
                "name": name,
                "amount": None,
                "units": None
            }
        
        # Паттерн: название + единица (для ингредиентов вроде "زيت للقلي")
        # Например: "زيت للقلي"
        pattern3 = rf'^(.+?)\s+({units_pattern})$'
        match = re.match(pattern3, text)
        
        if match:
            name = match.group(1)
            unit = match.group(2)
            name = self._clean_ingredient_name(name)
            
            return {
                "name": name,
                "amount": None,
                "units": unit
            }
        
        # Если не совпало ни с одним паттерном, возвращаем только название
        name = self._clean_ingredient_name(text)
        return {
            "name": name,
            "amount": None,
            "units": None
        }
    
    def _clean_ingredient_name(self, name: str) -> str:
        """Очистка названия ингредиента"""
        # Убираем слова "رشة", "حسب الرغبة" и т.п.
        name = re.sub(r'\b(رشة|حسب الرغبة|اختياري|للتزيين)\b', '', name)
        name = self.clean_text(name)
        return name
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        recipe_paragraph = self._get_recipe_paragraph()
        if not recipe_paragraph:
            return None
        
        # Ищем текст после "طريقة تحضير"
        # Получаем HTML-строку параграфа
        recipe_html = str(recipe_paragraph)

        match = re.search(r'طريقة تحضير[^<]*?(.*?)(?:لقراءة المقال|$)', recipe_html, re.DOTALL)
        if not match:
            return None
        
        instructions_text = match.group(1)
        
        # Убираем HTML теги
        instructions_text = re.sub(r'<[^>]+>', ' ', instructions_text)
        
        # Очищаем текст
        instructions_text = self.clean_text(instructions_text)
        
        # Убираем суффиксы типа "تضاف....." или "...."
        instructions_text = re.sub(r'\.{2,}.*$', '', instructions_text)
        
        return instructions_text if instructions_text else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # В примерах категория указана как "Dessert" в JSON
        # Попробуем определить по ключевым словам
        
        keywords_meta = self.soup.find('meta', {'name': 'keywords'})
        if keywords_meta and keywords_meta.get('content'):
            keywords = keywords_meta['content']
            
            # Проверяем на десерты
            if any(word in keywords for word in ['حلويات', 'كيك', 'دونتس', 'شوكولاتة']):
                return 'Dessert'
        
        # Проверяем в названии блюда
        dish_name = self.extract_dish_name()
        if dish_name:
            if any(word in dish_name for word in ['دونتس', 'كيك', 'حلوى', 'شوكولاتة']):
                return 'Dessert'
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # В примерах нет времени подготовки
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # В примерах нет времени приготовления
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # В примерах нет общего времени
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # В примерах нет заметок
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        keywords_meta = self.soup.find('meta', {'name': 'keywords'})
        if not keywords_meta or not keywords_meta.get('content'):
            return None
        
        keywords = keywords_meta['content']
        
        # Разбиваем по запятым
        tags_list = [tag.strip() for tag in keywords.split(',')]
        
        # Фильтруем общие/нерелевантные теги
        stopwords = {
            'تطبيق نبض للكمبيوتر', 'تطبيق نبض للويندوز', 'موقع نبض',
            'أخبار عاجلة', 'نبض', 'مرأة ومنوعات', 'nabd', 'nabd.com'
        }
        
        filtered_tags = [tag for tag in tags_list if tag and tag not in stopwords]
        
        # Возвращаем как строку через запятую с пробелом
        return ', '.join(filtered_tags) if filtered_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в twitter:image
        twitter_image = self.soup.find('meta', {'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            # Возвращаем как строку через запятую без пробелов
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
            "image_urls": image_urls
        }


def main():
    """
    Точка входа для обработки директории с HTML файлами nabd.com
    """
    import os
    
    # Ищем директорию preprocessed/nabd_com относительно корня репозитория
    repo_root = Path(__file__).parent.parent
    nabd_dir = repo_root / "preprocessed" / "nabd_com"
    
    if nabd_dir.exists() and nabd_dir.is_dir():
        print(f"Обработка директории: {nabd_dir}")
        process_directory(NabdExtractor, str(nabd_dir))
    else:
        print(f"Директория не найдена: {nabd_dir}")
        print("Использование: python nabd_com.py")


if __name__ == "__main__":
    main()
