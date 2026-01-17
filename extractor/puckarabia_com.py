"""
Экстрактор данных рецептов для сайта puckarabia.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class PuckarabiaExtractor(BaseRecipeExtractor):
    """Экстрактор для puckarabia.com"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Данные могут быть списком или словарем
                if isinstance(data, list):
                    # Ищем Recipe в списке
                    for item in data:
                        if isinstance(item, dict):
                            item_type = item.get('@type', '')
                            if isinstance(item_type, list) and 'Recipe' in item_type:
                                return item
                            elif item_type == 'Recipe':
                                return item
                elif isinstance(data, dict):
                    item_type = data.get('@type', '')
                    if isinstance(item_type, list) and 'Recipe' in item_type:
                        return data
                    elif item_type == 'Recipe':
                        return data
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "20 mins" или "1 hr 5 mins"
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
        
        # Форматируем результат
        parts = []
        if hours > 0:
            parts.append(f"{hours} hr{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} min{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Альтернатива - из заголовка страницы
        h1 = self.soup.find('h1', class_=re.compile(r'recipe-title', re.I))
        if not h1:
            h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Из meta title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        title = self.soup.find('title')
        if title:
            text = title.get_text()
            # Убираем суффиксы
            text = re.sub(r'\s*\|.*$', '', text)
            text = re.sub(r'\s+Recipe.*$', '', text, flags=re.IGNORECASE)
            return self.clean_text(text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
        # Альтернатива - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        # Из класса recipe-description
        desc_elem = self.soup.find(class_=re.compile(r'recipe-description', re.I))
        if desc_elem:
            return self.clean_text(desc_elem.get_text())
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате списка словарей"""
        ingredients = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeIngredient' in json_ld:
            for ingredient_text in json_ld['recipeIngredient']:
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
            
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)
        
        # Если в JSON-LD нет, пробуем извлечь из HTML с data-атрибутами
        ingredient_items = self.soup.find_all('li', attrs={'data-ingredient-name': True})
        
        for item in ingredient_items:
            name = item.get('data-ingredient-name', '').strip()
            amount = item.get('data-ingredient-amount', '').strip()
            unit = item.get('data-ingredient-unit', '').strip()
            
            if name:
                ingredients.append({
                    "name": name,
                    "amount": amount if amount else None,
                    "unit": unit if unit else None
                })
        
        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)
        
        # Если data-атрибутов нет, пробуем обычный парсинг списка
        ingredient_container = self.soup.find('ul', class_=re.compile(r'ingredients-list', re.I))
        if not ingredient_container:
            ingredient_container = self.soup.find('section', class_=re.compile(r'ingredients', re.I))
        
        if ingredient_container:
            items = ingredient_container.find_all('li')
            
            for item in items:
                ingredient_text = item.get_text(strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                if ingredient_text:
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour"
            
        Returns:
            dict: {"name": "flour", "amount": "1", "unit": "cup"}
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
        
        # Паттерн для извлечения количества, единицы и названия (арабские и английские единицы)
        # Важно: более длинные варианты (множественное число) должны быть в начале
        pattern = r'^([\d\s/.,]+|نصف|ربع|ثلثي|ثلاثة أرباع|حسب الذوق)?\s*(كيلوغرام|ملعقة كبيرة|ملعقة صغيرة|ميلليتر|milliliters?|tablespoons?|teaspoons?|كيلو|أكواب|كوب|فصوص|فص|حبات|حبة|جرام|غرام|لتر|رشة|cups?|tbsps?|tsps?|pounds?|ounces?|liters?|lbs?|oz|kg|pinch(?:es)?|dash(?:es)?|packages?|packs?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads|grams?|g\b|ml\b|l\b|مل\b|غ\b|ج\b)?\s*(.+)'
        
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
                        try:
                            total += float(part)
                        except:
                            pass
                amount = str(total) if total > 0 else amount_str
            else:
                # Сохраняем amount_str как есть (включая "حسب الذوق", "نصف" и т.д.)
                amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Сначала, если amount пусто, проверяем есть ли "حسب الذوق" или "to taste" в name
        # и извлекаем его как amount
        if not amount:
            # Проверяем на "حسب الذوق" или "to taste"
            taste_match = re.search(r'\b(حسب الذوق|to taste|as needed)\b', name, re.IGNORECASE)
            if taste_match:
                amount = taste_match.group(1)
        
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|for serving|حسب الذوق|اختياري)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
        # Сначала пробуем из JSON-LD
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        steps.append(f"{idx}. {step_text}")
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        steps.append(f"{idx}. {step_text}")
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            
            if steps:
                return ' '.join(steps)
        
        # Если JSON-LD не помог, ищем в HTML
        steps_container = self.soup.find('ol', class_=re.compile(r'steps-list', re.I))
        if not steps_container:
            steps_container = self.soup.find('section', class_=re.compile(r'instructions', re.I))
            if steps_container:
                steps_container = steps_container.find('ol')
        
        if steps_container:
            step_items = steps_container.find_all('li')
            steps = []
            
            for idx, item in enumerate(step_items, 1):
                step_text = item.get_text(strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    # Добавляем нумерацию если её нет
                    if not re.match(r'^\d+\.', step_text):
                        steps.append(f"{idx}. {step_text}")
                    else:
                        steps.append(step_text)
            
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        json_ld = self._get_json_ld_data()
        
        if json_ld:
            # Пробуем recipeCategory
            if 'recipeCategory' in json_ld:
                category = json_ld['recipeCategory']
                if isinstance(category, list):
                    return ', '.join(category)
                return str(category)
            
            # Пробуем recipeCuisine
            if 'recipeCuisine' in json_ld:
                cuisine = json_ld['recipeCuisine']
                if isinstance(cuisine, list):
                    return ', '.join(cuisine)
                return str(cuisine)
        
        # Альтернатива - из meta тегов
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        # Альтернатива - из HTML
        prep_time_elem = self.soup.find(class_=re.compile(r'prep-time', re.I))
        if prep_time_elem:
            text = prep_time_elem.get_text(strip=True)
            # Извлекаем число минут
            match = re.search(r'(\d+)\s*(دقيقة|دقائق|minutes?|mins?)', text, re.IGNORECASE)
            if match:
                return f"{match.group(1)} mins"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        # Альтернатива - из HTML
        cook_time_elem = self.soup.find(class_=re.compile(r'cook-time', re.I))
        if cook_time_elem:
            text = cook_time_elem.get_text(strip=True)
            # Извлекаем число минут
            match = re.search(r'(\d+)\s*(دقيقة|دقائق|minutes?|mins?)', text, re.IGNORECASE)
            if match:
                return f"{match.group(1)} mins"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        # Альтернатива - из HTML
        total_time_elem = self.soup.find(class_=re.compile(r'total-time', re.I))
        if total_time_elem:
            text = total_time_elem.get_text(strip=True)
            # Извлекаем число минут
            match = re.search(r'(\d+)\s*(دقيقة|دقائق|minutes?|mins?)', text, re.IGNORECASE)
            if match:
                return f"{match.group(1)} mins"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с заметками
        notes_section = self.soup.find('section', class_=re.compile(r'recipe-notes', re.I))
        
        if notes_section:
            # Ищем параграф внутри
            p = notes_section.find('p')
            if p:
                text = self.clean_text(p.get_text())
                return text if text else None
            
            # Если нет параграфа, берем весь текст и убираем заголовок
            text = notes_section.get_text(separator=' ', strip=True)
            # Убираем заголовок "ملاحظات" или "Notes"
            text = re.sub(r'^(ملاحظات|Notes)\s*', '', text, flags=re.IGNORECASE)
            text = self.clean_text(text)
            return text if text else None
        
        # Альтернативный поиск
        notes_elem = self.soup.find(class_=re.compile(r'notes', re.I))
        if notes_elem:
            text = self.clean_text(notes_elem.get_text())
            text = re.sub(r'^(ملاحظات|Notes)\s*', '', text, flags=re.IGNORECASE)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Список общих слов и фраз без смысловой нагрузки для фильтрации
        stopwords = {
            'recipe', 'recipes', 'puck arabia', 'puckarabia', 'easy', 'quick',
            'وصفة', 'وصفات', 'food', 'cooking'
        }
        
        tags_list = []
        
        # Сначала пробуем извлечь из мета-тега parsely-tags
        parsely_meta = self.soup.find('meta', attrs={'name': 'parsely-tags'})
        if parsely_meta and parsely_meta.get('content'):
            tags_string = parsely_meta['content']
            tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        # Если не нашли, пробуем из JSON-LD
        if not tags_list:
            json_ld = self._get_json_ld_data()
            if json_ld and 'keywords' in json_ld:
                keywords = json_ld['keywords']
                if isinstance(keywords, str):
                    tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                elif isinstance(keywords, list):
                    tags_list = keywords
        
        if not tags_list:
            return None
        
        # Фильтрация тегов
        filtered_tags = []
        for tag in tags_list:
            tag_lower = tag.lower()
            
            # Пропускаем точные совпадения со стоп-словами
            if tag_lower in stopwords:
                continue
            
            # Пропускаем теги короче 3 символов
            if len(tag) < 3:
                continue
            
            filtered_tags.append(tag)
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in filtered_tags:
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen.add(tag_lower)
                unique_tags.append(tag)
        
        # Возвращаем как строку через запятую с пробелом
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Сначала пробуем из JSON-LD
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        if 'url' in item:
                            urls.append(item['url'])
                        elif 'contentUrl' in item:
                            urls.append(item['contentUrl'])
        
        # Дополнительно ищем в meta тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # Ищем в теге img внутри recipe-image
        recipe_image = self.soup.find('div', class_=re.compile(r'recipe-image', re.I))
        if recipe_image:
            img_tag = recipe_image.find('img')
            if img_tag and img_tag.get('src'):
                urls.append(img_tag['src'])
        
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
            "instructions": self.extract_steps(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "puckarabia_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(PuckarabiaExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python puckarabia_com.py")


if __name__ == "__main__":
    main()
