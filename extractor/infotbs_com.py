"""
Экстрактор данных рецептов для сайта infotbs.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class InfotbsExtractor(BaseRecipeExtractor):
    """Экстрактор для infotbs.com"""
    
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
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict):
                                item_type = item.get('@type', '')
                                if isinstance(item_type, list) and 'Recipe' in item_type:
                                    return item
                                elif item_type == 'Recipe':
                                    return item
                    # Проверяем сам объект
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
            Время в формате "20 minutes" или "1 hour 30 minutes"
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
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Альтернатива - из заголовка страницы
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Из meta title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s*\|.*$', '', title)
            title = re.sub(r'\s+Recipe.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
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
        
        # og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате списка словарей"""
        json_ld = self._get_json_ld_data()
        
        ingredients = []
        
        # Сначала пробуем JSON-LD
        if json_ld and 'recipeIngredient' in json_ld:
            for ingredient_text in json_ld['recipeIngredient']:
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        # Если не нашли в JSON-LD, ищем в HTML
        if not ingredients:
            # Ищем элементы с атрибутами itemprop (microdata)
            ingredient_items = self.soup.find_all(attrs={'itemprop': 'recipeIngredient'})
            if not ingredient_items:
                ingredient_items = self.soup.find_all(attrs={'itemprop': 'ingredients'})
            
            for item in ingredient_items:
                ingredient_text = item.get_text(strip=True)
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        # Если все еще не нашли, ищем по классам
        if not ingredients:
            ingredient_containers = [
                self.soup.find('ul', class_=re.compile(r'ingredient.*list', re.I)),
                self.soup.find('div', class_=re.compile(r'ingredient', re.I))
            ]
            
            for container in ingredient_containers:
                if not container:
                    continue
                    
                # Извлекаем элементы списка
                items = container.find_all('li')
                if not items:
                    items = container.find_all('p')
                
                for item in items:
                    ingredient_text = item.get_text(separator=' ', strip=True)
                    ingredient_text = self.clean_text(ingredient_text)
                    
                    # Пропускаем заголовки секций
                    if ingredient_text and not ingredient_text.endswith(':'):
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
                
                if ingredients:
                    break
        
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
        
        # Список возможных единиц измерения
        units = (
            r'cups?|tablespoons?|teaspoons?|tbsps?|tsps?|'
            r'pounds?|ounces?|lbs?|oz|'
            r'grams?|kilograms?|g|kg|'
            r'milliliters?|liters?|ml|liter|'
            r'pinch(?:es)?|dash(?:es)?|'
            r'packages?|packs?|cans?|jars?|bottles?|'
            r'inch(?:es)?|slices?|cloves?|bunches?|sprigs?|'
            r'whole|halves?|quarters?|pieces?|heads?'
        )
        
        # Паттерн для извлечения количества, единицы и названия
        # Формат: [количество] [единица] название
        pattern_with_unit = rf'^([\d\s/.,]+)?\s*\b({units})\b\s*(.+)'
        
        match = re.match(pattern_with_unit, text, re.IGNORECASE)
        
        # Если не совпало с единицами, пробуем простой паттерн: количество + название
        if not match:
            pattern_simple = r'^([\d\s/.,]+)?\s*(.+)'
            match = re.match(pattern_simple, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
        
        # Обработка результатов паттерна
        if len(match.groups()) == 3:
            # Паттерн с единицами измерения: amount, unit, name
            amount_str, unit, name = match.groups()
        else:
            # Простой паттерн: amount, name (без единиц)
            amount_str, name = match.groups()
            unit = None
        
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
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|for serving)\b', '', name, flags=re.IGNORECASE)
        # Удаляем специфичные суффиксы
        name = re.sub(r',\s*(drained|grated|sliced|chopped|minced|crushed|fresh|frozen|dried).*$', '', name, flags=re.IGNORECASE)
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
        
        steps = []
        
        # Сначала пробуем JSON-LD
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            
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
        # Проверяем microdata
        instruction_items = self.soup.find_all(attrs={'itemprop': 'recipeInstructions'})
        if instruction_items:
            for idx, item in enumerate(instruction_items, 1):
                step_text = self.clean_text(item.get_text())
                if step_text:
                    steps.append(f"{idx}. {step_text}")
        
        if steps:
            return ' '.join(steps)
        
        # Ищем по классам
        instructions_containers = [
            self.soup.find('ol', class_=re.compile(r'instruction.*list', re.I)),
            self.soup.find('div', class_=re.compile(r'instruction', re.I))
        ]
        
        for container in instructions_containers:
            if not container:
                continue
            
            # Извлекаем шаги
            step_items = container.find_all('li')
            if not step_items:
                step_items = container.find_all('p')
            
            for idx, item in enumerate(step_items, 1):
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    # Добавляем нумерацию если её нет
                    if not re.match(r'^\d+\.', step_text):
                        steps.append(f"{idx}. {step_text}")
                    else:
                        steps.append(step_text)
            
            if steps:
                break
        
        return ' '.join(steps) if steps else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности в формате: 202 kcal; 2/11/27"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'nutrition' in json_ld:
            nutrition = json_ld['nutrition']
            
            # Извлекаем калории
            calories = None
            if 'calories' in nutrition:
                cal_text = nutrition['calories']
                # Извлекаем только число
                cal_match = re.search(r'(\d+)', str(cal_text))
                if cal_match:
                    calories = cal_match.group(1)
            
            # Извлекаем БЖУ (белки/жиры/углеводы)
            protein = None
            fat = None
            carbs = None
            
            if 'proteinContent' in nutrition:
                prot_text = nutrition['proteinContent']
                prot_match = re.search(r'(\d+)', str(prot_text))
                if prot_match:
                    protein = prot_match.group(1)
            
            if 'fatContent' in nutrition:
                fat_text = nutrition['fatContent']
                fat_match = re.search(r'(\d+)', str(fat_text))
                if fat_match:
                    fat = fat_match.group(1)
            
            if 'carbohydrateContent' in nutrition:
                carb_text = nutrition['carbohydrateContent']
                carb_match = re.search(r'(\d+)', str(carb_text))
                if carb_match:
                    carbs = carb_match.group(1)
            
            # Форматируем: "202 kcal; 2/11/27"
            if calories and protein and fat and carbs:
                return f"{calories} kcal; {protein}/{fat}/{carbs}"
            elif calories:
                return f"{calories} kcal"
        
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
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        # Ищем в microdata
        prep_time = self.soup.find(attrs={'itemprop': 'prepTime'})
        if prep_time:
            # Проверяем атрибут datetime
            if prep_time.get('datetime'):
                return self.parse_iso_duration(prep_time['datetime'])
            # Иначе берем текст
            return self.clean_text(prep_time.get_text())
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        # Ищем в microdata
        cook_time = self.soup.find(attrs={'itemprop': 'cookTime'})
        if cook_time:
            # Проверяем атрибут datetime
            if cook_time.get('datetime'):
                return self.parse_iso_duration(cook_time['datetime'])
            # Иначе берем текст
            return self.clean_text(cook_time.get_text())
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        # Ищем в microdata
        total_time = self.soup.find(attrs={'itemprop': 'totalTime'})
        if total_time:
            # Проверяем атрибут datetime
            if total_time.get('datetime'):
                return self.parse_iso_duration(total_time['datetime'])
            # Иначе берем текст
            return self.clean_text(total_time.get_text())
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секции с примечаниями/советами (более специфичные паттерны)
        notes_patterns = [
            r'\bchef.*note\b', r'\bcook.*note\b', 
            r'\beditor.*note\b', r'\brecipe.*note\b',
            r'\btip\b', r'\bnote\b'
        ]
        
        for pattern in notes_patterns:
            notes_section = self.soup.find(class_=re.compile(pattern, re.I))
            
            if notes_section:
                # Сначала пробуем найти параграф внутри
                p = notes_section.find('p')
                if p:
                    text = self.clean_text(p.get_text())
                    return text if text else None
                
                # Если нет параграфа, берем весь текст
                text = notes_section.get_text(separator=' ', strip=True)
                # Убираем заголовок
                text = re.sub(r"^(Note|Tip|Chef'?s\s+Note|Cook'?s\s+Note)\s*:?\s*", '', text, flags=re.I)
                text = self.clean_text(text)
                return text if text else None
        
        # Ищем в параграфах с ключевыми словами
        note_keywords = [
            'feel free to substitute', 'you can substitute',
            'feel free to', 'keep in mind', 'freezes well', 
            'can be served', 'serve this', 'optional', 
            'for best results', 'tip:', 'note:'
        ]
        
        paragraphs = self.soup.find_all('p')
        for p in paragraphs:
            text = p.get_text(strip=True)
            for keyword in note_keywords:
                if keyword in text.lower():
                    cleaned_text = self.clean_text(text)
                    # Извлекаем первое предложение
                    sentences = re.split(r'(?<=[.!?])\s+', cleaned_text)
                    if sentences:
                        return sentences[0]
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из meta-тега или keywords"""
        # Список общих слов без смысловой нагрузки для фильтрации
        stopwords = {
            'recipe', 'recipes', 'how to make', 'how to', 'easy', 'cooking', 'quick',
            'food', 'kitchen', 'simple', 'best', 'make', 'ingredients', 'video',
            'meal', 'prep', 'ideas', 'tips', 'tricks', 'hacks', 'home', 'family',
            'prepare', 'homemade', 'dish', 'perfect', 'favorite', 'delicious'
        }
        
        tags_list = []
        
        # 1. Ищем в parsely-tags
        parsely_meta = self.soup.find('meta', attrs={'name': 'parsely-tags'})
        if parsely_meta and parsely_meta.get('content'):
            tags_string = parsely_meta['content']
            tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        # 2. Если не нашли, ищем в keywords
        if not tags_list:
            keywords_meta = self.soup.find('meta', attrs={'name': 'keywords'})
            if keywords_meta and keywords_meta.get('content'):
                tags_string = keywords_meta['content']
                tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        # 3. Если не нашли, ищем в article:tag
        if not tags_list:
            article_tags = self.soup.find_all('meta', property='article:tag')
            for tag_meta in article_tags:
                if tag_meta.get('content'):
                    tags_list.append(tag_meta['content'])
        
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
        
        json_ld = self._get_json_ld_data()
        
        # 1. Ищем в JSON-LD
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
        
        # 2. Ищем в meta тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Ищем в microdata
        image_items = self.soup.find_all(attrs={'itemprop': 'image'})
        for item in image_items:
            # Может быть img тег
            if item.name == 'img' and item.get('src'):
                urls.append(item['src'])
            # Может быть meta тег
            elif item.name == 'meta' and item.get('content'):
                urls.append(item['content'])
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            # Возвращаем через запятую без пробелов
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
    preprocessed_dir = os.path.join("preprocessed", "infotbs_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(InfotbsExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python infotbs_com.py")


if __name__ == "__main__":
    main()
