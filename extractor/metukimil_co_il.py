"""
Экстрактор данных рецептов для сайта metukimil.co.il
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MetukimilExtractor(BaseRecipeExtractor):
    """Экстрактор для metukimil.co.il"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'name' in data:
                    return self.clean_text(data['name'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - מתכונים מתוקים"
            title = re.sub(r'\s*[||-].*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        description = None
        dish_name = None
        
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe':
                    if 'description' in data:
                        description = self.clean_text(data['description'])
                    if 'name' in data:
                        dish_name = self.clean_text(data['name'])
                    if description:
                        break
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если description не начинается с названия блюда, добавляем первые 2 слова названия
        if description and dish_name:
            # Берем первые 2 слова названия блюда
            dish_words = dish_name.split()
            if len(dish_words) >= 2:
                dish_prefix = ' '.join(dish_words[:2])
                # Проверяем, не начинается ли уже с этого префикса
                if not description.startswith(dish_prefix):
                    description = f"{dish_prefix} {description}"
        
        if description:
            return description
        
        # Пробуем из WPRM summary
        summary = self.soup.find(class_=lambda x: x and 'wprm-recipe-summary' in x)
        if summary:
            text = summary.get_text(strip=True)
            if text:
                return self.clean_text(text)
        
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
        """Извлечение ингредиентов из WPRM или JSON-LD"""
        ingredients = []
        
        # Сначала пробуем из WPRM HTML (более структурированный)
        ing_list = self.soup.find(class_='wprm-recipe-ingredients')
        if ing_list:
            items = ing_list.find_all('li', class_='wprm-recipe-ingredient')
            
            for item in items:
                # Извлекаем структурированные данные
                amount_elem = item.find(class_='wprm-recipe-ingredient-amount')
                unit_elem = item.find(class_='wprm-recipe-ingredient-unit')
                name_elem = item.find(class_='wprm-recipe-ingredient-name')
                
                amount = self.clean_text(amount_elem.get_text(strip=True)) if amount_elem else None
                unit = self.clean_text(unit_elem.get_text(strip=True)) if unit_elem else None
                name = self.clean_text(name_elem.get_text(strip=True)) if name_elem else None
                
                # Если нет данных, пропускаем
                if not name:
                    continue
                
                # Формируем структуру ингредиента
                ingredient = {
                    "name": name if name else None,
                    "amount": amount if amount else None,
                    "unit": unit if unit else None
                }
                
                ingredients.append(ingredient)
        
        # Если WPRM не дал результатов, пробуем JSON-LD
        if not ingredients:
            json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
            
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    if data.get('@type') == 'Recipe' and 'recipeIngredient' in data:
                        for ing_text in data['recipeIngredient']:
                            # Парсим текст ингредиента
                            parsed = self.parse_ingredient(ing_text)
                            if parsed:
                                ingredients.append(parsed)
                        break
                except (json.JSONDecodeError, KeyError):
                    continue
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "¾ כוס שמן" или "3 ביצים"
            
        Returns:
            dict: {"name": "שמן", "amount": "¾", "unit": "כוס"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Формат: [количество] [единица] название
        # Примеры: "¾ כוס שמן", "1 גביע שמנת חמוצה", "3 ביצים"
        
        # Попробуем разделить по пробелам
        parts = text.split(None, 2)  # Максимум 3 части
        
        amount = None
        unit = None
        name = text  # По умолчанию все - название
        
        if len(parts) >= 3:
            # Возможно: количество единица название
            potential_amount = parts[0]
            potential_unit = parts[1]
            potential_name = parts[2]
            
            # Проверяем, является ли первая часть количеством
            if self._is_amount(potential_amount):
                amount = potential_amount
                unit = potential_unit
                name = potential_name
        elif len(parts) == 2:
            # Возможно: количество название (без единицы)
            potential_amount = parts[0]
            potential_name = parts[1]
            
            if self._is_amount(potential_amount):
                amount = potential_amount
                name = potential_name
        
        # Удаляем примечания в скобках из названия
        if name:
            name = re.sub(r'\([^)]*\)', '', name).strip()
        
        return {
            "name": name if name else None,
            "amount": amount if amount else None,
            "unit": unit if unit else None
        }
    
    def _is_amount(self, text: str) -> bool:
        """Проверка, является ли текст количеством"""
        # Проверяем на числа, дроби, смешанные числа
        # Примеры: "1", "¾", "1 ¼", "2.5"
        pattern = r'^[\d\s.,¼½¾⅓⅔⅛⅜⅝⅞]+$'
        return bool(re.match(pattern, text))
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if data.get('@type') == 'Recipe' and 'recipeInstructions' in data:
                    instructions = data['recipeInstructions']
                    if isinstance(instructions, list):
                        for step in instructions:
                            if isinstance(step, dict) and 'text' in step:
                                steps.append(self.clean_text(step['text']))
                            elif isinstance(step, str):
                                steps.append(self.clean_text(step))
                    
                    if steps:
                        return ' '.join(steps)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, ищем в WPRM HTML
        inst_list = self.soup.find(class_='wprm-recipe-instructions')
        if inst_list:
            items = inst_list.find_all('li', class_='wprm-recipe-instruction')
            
            for item in items:
                text_elem = item.find(class_='wprm-recipe-instruction-text')
                if text_elem:
                    step_text = self.clean_text(text_elem.get_text(strip=True))
                else:
                    step_text = self.clean_text(item.get_text(strip=True))
                
                if step_text:
                    steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Пробуем из WPRM
        course = self.soup.find(class_=lambda x: x and 'wprm-recipe-course' in x)
        if course:
            return self.clean_text(course.get_text(strip=True))
        
        # Пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe':
                    if 'recipeCategory' in data:
                        return self.clean_text(data['recipeCategory'])
                    elif 'recipeCuisine' in data:
                        return self.clean_text(data['recipeCuisine'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в хлебных крошках (последняя категория перед рецептом)
        breadcrumbs = self.soup.find('nav', class_=lambda x: x and 'breadcrumb' in x.lower())
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            # Берем последнюю ссылку (не Home и не сам рецепт)
            for link in reversed(links):
                text = self.clean_text(link.get_text())
                # Пропускаем "Home" и другие общие ссылки
                if text and text not in ['Home', 'home', 'Главная']:
                    # Map Hebrew categories to English for consistency
                    category_map = {
                        'מתכונים קלים': 'Dessert',
                        'עוגות': 'Dessert',
                        'קינוחים': 'Dessert',
                        'מאפים': 'Baked Goods',
                        'ארוחות ערב': 'Dinner'
                    }
                    return category_map.get(text, text)
        
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_time(self, time_field: str) -> Optional[str]:
        """
        Извлечение времени из JSON-LD или WPRM
        
        Args:
            time_field: 'prepTime', 'cookTime', или 'totalTime'
        """
        # Пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and time_field in data:
                    iso_time = data[time_field]
                    return self.parse_iso_duration(iso_time)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Пробуем из WPRM HTML
        time_map = {
            'prepTime': 'prep-time',
            'cookTime': 'cook-time',
            'totalTime': 'total-time'
        }
        
        class_name = time_map.get(time_field)
        if class_name:
            time_elem = self.soup.find(class_=lambda x: x and class_name in x)
            if time_elem:
                return self.clean_text(time_elem.get_text(strip=True))
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах, например "90"
        """
        if not duration or not duration.startswith('PT'):
            return None
        
        duration = duration[2:]  # Убираем "PT"
        
        hours = 0
        minutes = 0
        
        # Извлекаем часы
        hour_match = re.search(r'(\d+)H', duration)
        if hour_match:
            hours = int(hour_match.group(1))
        
        # Извлекаем минуты
        min_match = re.search(r'(\d+)M', duration)
        if min_match:
            minutes = int(min_match.group(1))
        
        # Конвертируем все в минуты
        total_minutes = hours * 60 + minutes
        
        return str(total_minutes) if total_minutes > 0 else None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prepTime')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('cookTime')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('totalTime')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Пробуем из WPRM notes
        notes_section = self.soup.find(class_=lambda x: x and 'wprm-recipe-notes' in x)
        
        if notes_section:
            text = notes_section.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            # Убираем заголовок "הערות" если есть
            text = re.sub(r'^הערות\s*:?\s*', '', text, flags=re.I)
            return text if text else None
        
        # Альтернативно - из последнего шага инструкций, который может быть примечанием
        # Ищем шаг с ключевыми словами примечания
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if data.get('@type') == 'Recipe' and 'recipeInstructions' in data:
                    instructions = data['recipeInstructions']
                    if isinstance(instructions, list) and len(instructions) > 0:
                        # Проверяем последний шаг
                        last_step = instructions[-1]
                        if isinstance(last_step, dict) and 'text' in last_step:
                            text = last_step['text']
                            # Проверяем, похоже ли это на примечание
                            note_keywords = ['אם רוצים', 'התערובת מספיקה', 'הערה', 'טיפ', 'שימו לב']
                            for keyword in note_keywords:
                                if keyword in text:
                                    # Если ключевое слово - "אם רוצים", ищем его после запятой
                                    if keyword == 'אם רוצים':
                                        # Ищем запятую перед ключевым словом
                                        pos = text.find(keyword)
                                        comma_pos = text.rfind(',', 0, pos)
                                        if comma_pos != -1:
                                            # Извлекаем после запятой
                                            note_text = text[comma_pos + 1:].strip()
                                            return self.clean_text(note_text)
                                    
                                    # Для других ключевых слов, если они в начале - возвращаем весь текст
                                    if text.startswith(keyword):
                                        return self.clean_text(text)
                                    
                                    # Иначе извлекаем от начала предложения с ключевым словом
                                    pos = text.find(keyword)
                                    if pos > 0:
                                        # Ищем начало предложения (после точки)
                                        start = text.rfind('.', 0, pos)
                                        if start != -1:
                                            note_text = text[start + 1:].strip()
                                            return self.clean_text(note_text)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Пробуем из WPRM keywords
        keywords_elem = self.soup.find(class_=lambda x: x and 'wprm-recipe-keyword' in x)
        if keywords_elem:
            keywords_text = keywords_elem.get_text(strip=True)
            if keywords_text:
                # Разделяем по запятой
                tags = [self.clean_text(tag) for tag in keywords_text.split(',') if tag.strip()]
        
        # Если не нашли в WPRM, пробуем из JSON-LD
        if not tags:
            json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
            
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    if data.get('@type') == 'Recipe' and 'keywords' in data:
                        keywords = data['keywords']
                        if isinstance(keywords, str):
                            tags = [self.clean_text(tag) for tag in keywords.split(',') if tag.strip()]
                        elif isinstance(keywords, list):
                            tags = [self.clean_text(tag) for tag in keywords if tag]
                        break
                except (json.JSONDecodeError, KeyError):
                    continue
        
        # Если не нашли теги, генерируем из dish_name и category
        if not tags:
            # Получаем название блюда (первые 1-2 слова)
            dish_name = self.extract_dish_name()
            if dish_name:
                # Берем первые 2 слова как основной тег
                words = dish_name.split()
                if len(words) >= 2:
                    tags.append(' '.join(words[:2]))
                elif words:
                    tags.append(words[0])
            
            # Добавляем "מתכון" (рецепт)
            tags.append('מתכון')
            
            # Добавляем категорию на иврите
            category = self.extract_category()
            if category:
                # Обратный маппинг категорий
                reverse_category_map = {
                    'Dessert': 'קינוח',
                    'Baked Goods': 'מאפים',
                    'Dinner': 'ארוחות ערב'
                }
                hebrew_category = reverse_category_map.get(category, category)
                if hebrew_category and hebrew_category not in tags:
                    tags.append(hebrew_category)
        
        # Если не нашли теги, пробуем из meta keywords
        if not tags:
            meta_keywords = self.soup.find('meta', {'name': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                tags = [self.clean_text(tag) for tag in meta_keywords['content'].split(',') if tag.strip()]
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if data.get('@type') == 'Recipe' and 'image' in data:
                    img = data['image']
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, list):
                        urls.extend([i for i in img if isinstance(i, str)])
                    elif isinstance(img, dict):
                        if 'url' in img:
                            urls.append(img['url'])
                        elif 'contentUrl' in img:
                            urls.append(img['contentUrl'])
                    break
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не дал результатов, пробуем meta теги
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
            
            twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
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
    import os
    # По умолчанию обрабатываем папку preprocessed/metukimil_co_il
    preprocessed_dir = os.path.join("preprocessed", "metukimil_co_il")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(MetukimilExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python metukimil_co_il.py")


if __name__ == "__main__":
    main()
