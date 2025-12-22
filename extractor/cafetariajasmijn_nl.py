"""
Экстрактор данных рецептов для сайта cafetariajasmijn.nl
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CafetariajasmijnNlExtractor(BaseRecipeExtractor):
    """Экстрактор для cafetariajasmijn.nl"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в title тега сначала (там обычно чище название)
        title_tag = self.soup.find('title')
        if title_tag:
            title_text = self.clean_text(title_tag.get_text())
            # Убираем суффиксы сайта
            title_text = re.sub(r'\s*[»|]\s*Cafetaria.*$', '', title_text, flags=re.IGNORECASE)
            # Убираем "Recept" и слова после двоеточия
            title_text = re.sub(r'\s+Recept\s*:.*$', '', title_text, flags=re.IGNORECASE)
            title_text = re.sub(r'\s*:.*$', '', title_text)
            return title_text
        
        # Альтернативно - из заголовка h1 с классом post-title
        title = self.soup.find('h1', class_='post-title')
        if title:
            dish_name = self.clean_text(title.get_text())
            # Убираем подзаголовки после двоеточия
            if ':' in dish_name:
                # Берем первую часть (обычно это название блюда)
                parts = dish_name.split(':', 1)
                dish_name = parts[0].strip()
            return dish_name
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в мета-тегах
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            if desc:
                return desc
        
        # Ищем в og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = self.clean_text(og_desc['content'])
            if desc:
                return desc
        
        # Если нет в мета-тегах, ищем первый абзац после заголовка
        content = self.soup.find('div', class_='post-content')
        if content:
            # Ищем первый параграф перед заголовками h2/h3
            for elem in content.children:
                if hasattr(elem, 'name'):
                    if elem.name == 'p':
                        desc = self.clean_text(elem.get_text())
                        if desc and len(desc) > 20:
                            return desc
                    elif elem.name in ['h2', 'h3']:
                        break
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "500 gram bloem" или "350 ml water (lauwwarm)"
            
        Returns:
            dict: {"name": "bloem", "amount": "500", "unit": "gram"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Удаляем текст в скобках (уточнения)
        text_clean = re.sub(r'\([^)]*\)', '', text).strip()
        
        # Паттерн для извлечения: количество + единица + название
        # Примеры: "500 gram bloem", "350 ml water", "10 gram verse gist"
        pattern = r'^(\d+(?:[.,]\d+)?)\s+(gram|ml|liter|l|kg|kilogram|tbsp|tsp|tablespoon|teaspoon|cup|stuks?|st|eetlepels?|theelepels?|el|tl)\s+(.+)'
        
        match = re.match(pattern, text_clean, re.IGNORECASE)
        
        if match:
            amount, unit, name = match.groups()
            
            # Нормализация единиц измерения
            unit_map = {
                'gram': 'gram',
                'ml': 'ml',
                'liter': 'ml',
                'l': 'ml',
                'kg': 'gram',
                'kilogram': 'gram',
                'eetlepel': 'tbsp',
                'eetlepels': 'tbsp',
                'el': 'tbsp',
                'theelepel': 'tsp',
                'theelepels': 'tsp',
                'tl': 'tsp',
                'tbsp': 'tbsp',
                'tsp': 'tsp',
                'tablespoon': 'tbsp',
                'teaspoon': 'tsp',
                'cup': 'cup',
                'stuk': None,
                'stuks': None,
                'st': None
            }
            
            unit_normalized = unit_map.get(unit.lower(), unit)
            
            # Конвертация kg в граммы
            if unit.lower() in ['kg', 'kilogram']:
                amount = str(float(amount.replace(',', '.')) * 1000)
                unit_normalized = 'gram'
            
            # Конвертация литров в мл
            if unit.lower() in ['liter', 'l']:
                amount = str(float(amount.replace(',', '.')) * 1000)
                unit_normalized = 'ml'
            
            # Очистка названия
            name = name.strip()
            
            # Конвертация amount в int если возможно, иначе float
            try:
                amount_value = float(amount.replace(',', '.'))
                if amount_value.is_integer():
                    amount_value = int(amount_value)
            except:
                amount_value = amount.replace(',', '.')
            
            return {
                "name": name,
                "units": unit_normalized,  # Используем "units" как в эталонном JSON
                "amount": amount_value
            }
        else:
            # Если паттерн не совпал, возвращаем только название
            # Проверяем, нет ли просто названия без количества
            return {
                "name": text_clean,
                "units": None,
                "amount": None
            }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем секцию с ингредиентами
        content = self.soup.find('div', class_='post-content')
        if not content:
            return None
        
        # Ищем заголовок "Ingrediënten:"
        h3s = content.find_all('h3')
        for h3 in h3s:
            if re.search(r'Ingredi[eë]nt', h3.get_text(), re.IGNORECASE):
                # Нашли заголовок, ищем следующий ul
                next_ul = h3.find_next('ul')
                if next_ul:
                    items = next_ul.find_all('li')
                    for item in items:
                        ingredient_text = item.get_text(strip=True)
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
                    break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем секцию с инструкциями
        content = self.soup.find('div', class_='post-content')
        if not content:
            return None
        
        # Ищем заголовок "Bereiding:"
        h3s = content.find_all('h3')
        for h3 in h3s:
            if re.search(r'Bereiding', h3.get_text(), re.IGNORECASE):
                # Нашли заголовок, ищем следующий ol
                next_ol = h3.find_next('ol')
                if next_ol:
                    items = next_ol.find_all('li')
                    for idx, item in enumerate(items, 1):
                        step_text = self.clean_text(item.get_text())
                        if step_text:
                            # Добавляем номер шага, если его нет
                            if not re.match(r'^\d+\.', step_text):
                                step_text = f"{idx}. {step_text}"
                            steps.append(step_text)
                    break
        
        return '\n'.join(steps) if steps else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # Ищем секцию с информацией о питательности
        content = self.soup.find('div', class_='post-content')
        if not content:
            return None
        
        # Ищем параграфы или списки, которые упоминают питательные вещества
        # Обычно это информация о калориях, белках, жирах, углеводах
        nutrition_keywords = [
            'voedingswaarde', 'nutritie', 'calorie', 'calorieën', 'kcal',
            'eiwitten', 'vetten', 'koolhydraten', 'vezels', 'vitaminen'
        ]
        
        paragraphs = content.find_all('p')
        for p in paragraphs:
            text = p.get_text().lower()
            if any(keyword in text for keyword in nutrition_keywords):
                nutrition_text = self.clean_text(p.get_text())
                if nutrition_text:
                    return nutrition_text
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в хлебных крошках или мета-тегах
        breadcrumbs = self.soup.find('div', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                # Берем предпоследнюю категорию (перед самим рецептом)
                return self.clean_text(links[-1].get_text())
        
        # Пробуем найти категорию в контенте
        # Обычно рецепты хлеба - "Bread", основные блюда - "Main Course" и т.д.
        # Анализируем теги и контент
        content = self.soup.find('div', class_='post-content')
        if content:
            text = content.get_text().lower()
            # Простая эвристика на основе ключевых слов
            if any(word in text for word in ['brood', 'bol', 'bakken']):
                return 'Bread'
            elif any(word in text for word in ['hoofdgerecht', 'lasagne', 'pasta']):
                return 'Main Course'
            elif any(word in text for word in ['dessert', 'taart', 'gebak']):
                return 'Dessert'
        
        return None
    
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        content = self.soup.find('div', class_='post-content')
        if not content:
            return None
        
        # Ищем инструкции
        h3s = content.find_all('h3')
        instructions_text = ''
        for h3 in h3s:
            if re.search(r'Bereiding', h3.get_text(), re.IGNORECASE):
                next_ol = h3.find_next('ol')
                if next_ol:
                    instructions_text = next_ol.get_text()
                    break
        
        # Время подготовки/замешивания - обычно в первых шагах
        # Ищем "kneden ... 10-15 minuten" - берем верхнюю границу
        pattern = r'(?:kneden|deegbereiding).*?(\d+)[-–](\d+)\s*minut'
        match = re.search(pattern, instructions_text, re.IGNORECASE)
        if match:
            time_value = match.group(2)  # Берем верхнюю границу
            return f"{time_value} minutes"
        
        # Если нет диапазона, ищем одно число
        pattern2 = r'(?:kneden|deegbereiding).*?(\d+)\s*minut'
        match2 = re.search(pattern2, instructions_text, re.IGNORECASE)
        if match2:
            time_value = match2.group(1)
            return f"{time_value} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        content = self.soup.find('div', class_='post-content')
        if not content:
            return None
        
        # Ищем инструкции
        h3s = content.find_all('h3')
        instructions_text = ''
        for h3 in h3s:
            if re.search(r'Bereiding', h3.get_text(), re.IGNORECASE):
                next_ol = h3.find_next('ol')
                if next_ol:
                    instructions_text = next_ol.get_text()
                    break
        
        # Время готовки/выпекания - ищем "bakken ... 20-25 minuten"
        # Используем word boundary чтобы не совпадало с "bakplaat"
        pattern = r'\bBakken:.*?(\d+)[-–](\d+)\s*minut'
        match = re.search(pattern, instructions_text, re.IGNORECASE)
        if match:
            time_value = match.group(2)  # Берем верхнюю границу
            return f"{time_value} minutes"
        
        # Альтернативный паттерн
        pattern2 = r'(?:^|\s)bakken\s.*?(\d+)[-–](\d+)\s*minut'
        match2 = re.search(pattern2, instructions_text, re.IGNORECASE | re.MULTILINE)
        if match2:
            time_value = match2.group(2)
            return f"{time_value} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Общее время - суммируем prep и cook если возможно
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep and cook:
            # Извлекаем числа
            prep_mins = int(re.search(r'(\d+)', prep).group(1))
            cook_mins = int(re.search(r'(\d+)', cook).group(1))
            total = prep_mins + cook_mins
            return f"{total} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        content = self.soup.find('div', class_='post-content')
        if not content:
            return None
        
        # Ищем секции с советами или примечаниями
        notes_keywords = ['tips', 'variaties', 'let op', 'opmerking', 'advies']
        
        # Ищем заголовки, содержащие ключевые слова
        headers = content.find_all(['h2', 'h3'])
        for header in headers:
            header_text = header.get_text().lower()
            if any(keyword in header_text for keyword in notes_keywords):
                # Собираем текст после этого заголовка до следующего заголовка
                notes = []
                for sibling in header.find_next_siblings():
                    if sibling.name in ['h2', 'h3']:
                        break
                    if sibling.name == 'p':
                        note_text = self.clean_text(sibling.get_text())
                        if note_text:
                            notes.append(note_text)
                    elif sibling.name == 'ul':
                        items = sibling.find_all('li')
                        for item in items:
                            note_text = self.clean_text(item.get_text())
                            if note_text:
                                notes.append(note_text)
                
                if notes:
                    return ' '.join(notes)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем в мета-тегах
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        # Если нет мета-тегов, анализируем контент и заголовок
        if not tags:
            title = self.extract_dish_name()
            content = self.soup.find('div', class_='post-content')
            
            # Извлекаем ключевые слова из заголовка и контента
            text = ''
            if title:
                text += title.lower() + ' '
            if content:
                text += content.get_text().lower()
            
            # Простая эвристика для тегов
            tag_keywords = {
                'brood': 'brood',
                'italiaans': 'Italiaans',
                'lasagne': 'lasagne',
                'pasta': 'pasta',
                'bakken': 'zelf bakken',
                'hoofdgerecht': 'hoofdgerecht',
                'comfortfood': 'comfortfood',
                'vegetarisch': 'vegetarisch',
                'vegan': 'vegan'
            }
            
            for keyword, tag in tag_keywords.items():
                if keyword in text and tag not in tags:
                    tags.append(tag)
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Ищем изображения в контенте
        content = self.soup.find('div', class_='post-content')
        if content:
            imgs = content.find_all('img')
            for img in imgs:
                src = img.get('src') or img.get('data-src')
                if src and src not in urls:
                    # Пропускаем маленькие изображения и иконки
                    if not any(skip in src for skip in ['icon', 'logo', 'avatar', 'emoji']):
                        urls.append(src)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        # Возвращаем как строку через запятую без пробелов
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
            "instructions": self.extract_steps(),
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
    # Обрабатываем папку preprocessed/cafetariajasmijn_nl
    preprocessed_dir = os.path.join("preprocessed", "cafetariajasmijn_nl")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(CafetariajasmijnNlExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python cafetariajasmijn_nl.py")


if __name__ == "__main__":
    main()
