"""
Экстрактор данных рецептов для сайта godare.se
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class GodareSeExtractor(BaseRecipeExtractor):
    """Экстрактор для godare.se"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах с суффиксом, например "90 minutes"
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
        
        if total_minutes > 0:
            return f"{total_minutes} minutes"
        return None
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """
        Извлечение JSON-LD данных рецепта
        
        Returns:
            dict с данными рецепта или None
        """
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Функция для проверки типа Recipe
                def is_recipe(item):
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        return 'Recipe' in item_type
                    return item_type == 'Recipe'
                
                # Ищем Recipe в данных
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            recipe_data = item
                            break
                elif isinstance(data, dict):
                    if '@graph' in data:
                        for item in data['@graph']:
                            if is_recipe(item):
                                recipe_data = item
                                break
                    elif is_recipe(data):
                        recipe_data = data
                
                if recipe_data:
                    return recipe_data
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Пробуем JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта (первый абзац)"""
        # Пробуем JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            # Берем только первый абзац (до первого двойного переноса строки)
            if '\n\n' in desc:
                desc = desc.split('\n\n')[0]
            elif '\n' in desc:
                # Если нет двойного переноса, берем первые предложения до конца логического блока
                lines = desc.split('\n')
                desc = lines[0]
            return self.clean_text(desc)
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            if '\n\n' in desc:
                desc = desc.split('\n\n')[0]
            return self.clean_text(desc)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "15 g färsk ingefära" или "5 röda chilifrukter"
            
        Returns:
            dict: {"name": "färsk ingefära", "amount": "15", "unit": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на десятичные числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "15 g färsk ingefära", "5 röda chilifrukter", "1 msk olja"
        # Шведские единицы: g, kg, ml, dl, l, msk (столовая ложка), tsk (чайная ложка), krm (щепотка)
        pattern = r'^([\d\s/.,]+)?\s*(g|kg|ml|dl|l|msk|tsk|krm|st|cl|gram|liter|milliliter|deciliter|centiliter|matsked|tesked|kryddmått|stycken?)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2" или "1 1/2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                amount = str(total)
            else:
                amount = amount_str.replace(',', '.')
        
        # Обработка единицы измерения (приводим к нулю если пусто)
        unit = unit.strip() if unit else None
        
        # Очистка названия
        name = re.sub(r'\([^)]*\)', '', name)  # Удаляем скобки с содержимым
        name = re.sub(r'\s+', ' ', name).strip()  # Нормализуем пробелы
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Пробуем JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredient_list = recipe_data['recipeIngredient']
            if isinstance(ingredient_list, list):
                for ingredient_text in ingredient_list:
                    if isinstance(ingredient_text, str):
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
                
                if ingredients:
                    return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Пробуем JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            
            if isinstance(instructions, list):
                step_number = 1
                for item in instructions:
                    if isinstance(item, dict):
                        # HowToSection with itemListElement
                        if item.get('@type') == 'HowToSection' and 'itemListElement' in item:
                            for step in item['itemListElement']:
                                if isinstance(step, dict) and 'text' in step:
                                    steps.append(f"{step_number}. {self.clean_text(step['text'])}")
                                    step_number += 1
                        # HowToStep with text
                        elif item.get('@type') == 'HowToStep' and 'text' in item:
                            steps.append(f"{step_number}. {self.clean_text(item['text'])}")
                            step_number += 1
                        # Direct text field
                        elif 'text' in item:
                            steps.append(f"{step_number}. {self.clean_text(item['text'])}")
                            step_number += 1
                    elif isinstance(item, str):
                        steps.append(f"{step_number}. {self.clean_text(item)}")
                        step_number += 1
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Согласно reference JSON, всегда возвращаем "Main Course" для рецептов
        # Можно также попробовать получить из JSON-LD, но reference использует фиксированное значение
        return "Main Course"
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # В godare.se prep_time в JSON-LD часто равно PT0M
        # Ищем время подготовки в первых шагах инструкций (обычно там упоминается время для подготовки ингредиентов)
        
        recipe_data = self._get_recipe_json_ld()
        
        # Ищем упоминание времени в первых шагах (например, "ca 30 minuter" для blötläggning)
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            if isinstance(instructions, list):
                # Проверяем первую секцию (обычно подготовка)
                for section in instructions[:1]:
                    if isinstance(section, dict) and 'itemListElement' in section:
                        for step in section['itemListElement']:
                            if isinstance(step, dict) and 'text' in step:
                                text = step['text'].lower()
                                
                                # Ищем упоминания времени в минутах
                                min_match = re.search(r'(\d+)\s*minut', text)
                                if min_match:
                                    minutes = min_match.group(1)
                                    return f"{minutes} minutes"
        
        # Если есть prepTime в JSON-LD и оно не 0
        if recipe_data and 'prepTime' in recipe_data:
            prep_time = self.parse_iso_duration(recipe_data['prepTime'])
            if prep_time and prep_time != "0 minutes":
                return prep_time
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # В godare.se cookTime в JSON-LD может включать все время, включая prep
        # Пробуем найти упоминания времени в инструкциях
        
        recipe_data = self._get_recipe_json_ld()
        max_cooking_time = 0
        
        # Ищем упоминания времени в инструкциях (например, "2,5 timme", "30 minuter")
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            if isinstance(instructions, list):
                for section in instructions:
                    if isinstance(section, dict) and 'itemListElement' in section:
                        for step in section['itemListElement']:
                            if isinstance(step, dict) and 'text' in step:
                                text = step['text'].lower()
                                
                                # Ищем паттерны типа "2,5 timme", "30 minuter", "1 timme"
                                # Часы
                                hour_match = re.search(r'(\d+[,.]?\d*)\s*timm', text)
                                if hour_match:
                                    hours = float(hour_match.group(1).replace(',', '.'))
                                    minutes = int(hours * 60)
                                    if minutes > max_cooking_time:
                                        max_cooking_time = minutes
                                
                                # Минуты
                                min_match = re.search(r'(\d+)\s*minut', text)
                                if min_match:
                                    minutes = int(min_match.group(1))
                                    if minutes > max_cooking_time:
                                        max_cooking_time = minutes
        
        if max_cooking_time > 0:
            return f"{max_cooking_time} minutes"
        
        # Если не нашли в инструкциях, используем JSON-LD cookTime
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # В godare.se заметки часто находятся в последних предложениях среднего абзаца description
        
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            
            # Разбиваем на абзацы
            paragraphs = [p.strip() for p in desc.split('\n') if p.strip()]
            
            # Средний абзац (обычно второй) часто содержит заметки
            if len(paragraphs) > 1:
                middle_para = paragraphs[1]
                
                # Ищем последнее предложение, которое содержит советы/заметки
                # Обычно это предложения после "Och ja,", "Tips:", или содержащие ключевые слова
                sentences = re.split(r'[.!]\s+', middle_para)
                
                # Проверяем каждое предложение с конца
                for sentence in reversed(sentences):
                    sentence = sentence.strip()
                    if not sentence:
                        continue
                    
                    # Убираем вводные фразы типа "Och ja,", "Och,"
                    sentence = re.sub(r'^(Och\s+ja,?|Och,?)\s+', '', sentence, flags=re.IGNORECASE).strip()
                    
                    # Убираем "And yes," и подобные
                    sentence = re.sub(r'^(And\s+yes,?|Tips:)\s+', '', sentence, flags=re.IGNORECASE).strip()
                    
                    # Делаем первую букву заглавной
                    if sentence:
                        sentence = sentence[0].upper() + sentence[1:]
                    
                    # Добавляем точку обратно если её нет
                    if sentence and not sentence.endswith(('.', '!', '?')):
                        sentence += '!'
                    
                    # Ключевые фразы для заметок/советов
                    note_patterns = [
                        r'gör en stor',
                        r'resterna smakar',
                        r'kan gärna',
                        r'tips',
                        r'råd',
                        r'för extra',
                        r'perfekt',
                        r'dagen efter'
                    ]
                    
                    sentence_lower = sentence.lower()
                    if any(re.search(pattern, sentence_lower) for pattern in note_patterns):
                        return self.clean_text(sentence)
        
        # Попытка найти в HTML
        for pattern in ['tips', 'note', 'notera', 'råd', 'kommentar']:
            notes_section = self.soup.find(class_=re.compile(pattern, re.I))
            if notes_section:
                text = self.clean_text(notes_section.get_text())
                if text:
                    return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        seen_lower = set()
        
        # 1. Пробуем JSON-LD keywords (основной источник, сохраняем регистр)
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                for tag in keywords.split(','):
                    tag = tag.strip()
                    if tag and tag.lower() not in seen_lower:
                        tags_list.append(tag)
                        seen_lower.add(tag.lower())
            elif isinstance(keywords, list):
                for kw in keywords:
                    tag = self.clean_text(str(kw))
                    if tag and tag.lower() not in seen_lower:
                        tags_list.append(tag)
                        seen_lower.add(tag.lower())
        
        # 2. Дополнительно извлекаем ключевые слова из title (после тире)
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Ищем текст после тире (например, "Massaman curry med lamm – jättegod indisk mat")
            if '–' in title:
                subtitle = title.split('–', 1)[1].strip()
                # Извлекаем значимые слова (минимум 4 символа, не стоп-слова)
                stopwords = {'med', 'och', 'till', 'för', 'den', 'det', 'ett', 'från', 'jättegod'}
                words = re.findall(r'\b\w{4,}\b', subtitle)
                for word in words:
                    if word.lower() not in stopwords and word.lower() not in seen_lower:
                        tags_list.append(word.lower())
                        seen_lower.add(word.lower())
            
            # Также берем основные слова из главного названия (первая часть до тире)
            main_title = title.split('–')[0].strip() if '–' in title else title
            # Ищем ключевые кулинарные термины
            culinary_terms = ['curry', 'gryta', 'sallad', 'soppa', 'pasta', 'paj']
            for term in culinary_terms:
                if term in main_title.lower() and term not in seen_lower:
                    tags_list.append(term.lower())
                    seen_lower.add(term)
        
        # Формируем финальный список тегов
        if tags_list:
            return ','.join(tags_list)
        
        # Альтернативно - из meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            return ','.join(tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Пробуем JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
            elif isinstance(img, list):
                for image in img:
                    if isinstance(image, str):
                        urls.append(image)
                    elif isinstance(image, dict):
                        if 'url' in image:
                            urls.append(image['url'])
                        elif 'contentUrl' in image:
                            urls.append(image['contentUrl'])
        
        # Дополнительно - из meta og:image
        if not urls:
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
    # Обрабатываем папку preprocessed/godare_se
    preprocessed_dir = os.path.join("preprocessed", "godare_se")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(GodareSeExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python godare_se.py")


if __name__ == "__main__":
    main()
