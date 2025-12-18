"""
Экстрактор данных рецептов для сайта allrecipes.com (site_id = 1)
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory
# Добавление корневой директории в PYTHONPATH


class AllRecipesExtractor(BaseRecipeExtractor):
    """Экстрактор для allrecipes.com"""
    
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
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта
        recipe_header = self.soup.find('h1', class_='article-heading')
        if recipe_header:
            return self.clean_text(recipe_header.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " Recipe", " - Allrecipes"
            title = re.sub(r'\s+(Recipe|Allrecipes).*$', '', title, flags=re.IGNORECASE)
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
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем список ингредиентов через различные возможные классы
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
                # Извлекаем текст ингредиента
                ingredient_text = item.get_text(separator=' ', strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                # Пропускаем заголовки секций (часто содержат двоеточие)
                if ingredient_text and not ingredient_text.endswith(':'):
                    # Парсим в структурированный формат
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
            
            if ingredients:
                break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем извлечь из JSON-LD (самый надежный способ)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Функция для проверки типа (может быть строкой или списком)
                def is_recipe(item):
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        return 'Recipe' in item_type
                    return item_type == 'Recipe'
                
                # Ищем recipeInstructions в данных
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            recipe_data = item
                            break
                elif isinstance(data, dict) and is_recipe(data):
                    recipe_data = data
                
                if recipe_data and 'recipeInstructions' in recipe_data:
                    instructions = recipe_data['recipeInstructions']
                    if isinstance(instructions, list):
                        for idx, step in enumerate(instructions, 1):
                            if isinstance(step, dict) and 'text' in step:
                                steps.append(f"{idx}. {step['text']}")
                            elif isinstance(step, str):
                                steps.append(f"{idx}. {step}")
                
                if steps:
                    return ' '.join(steps)
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, ищем в HTML
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
            
            for item in step_items:
                # Извлекаем текст инструкции
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    steps.append(step_text)
            
            if steps:
                break
        
        # Если нумерация не была в HTML, добавляем её
        if steps and not re.match(r'^\d+\.', steps[0]):
            steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
        
        return ' '.join(steps) if steps else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности в формате: 202 kcal; 2/11/27"""
        
        # Сначала пробуем извлечь из JSON-LD
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
                
                # Ищем nutrition в данных
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            recipe_data = item
                            break
                elif isinstance(data, dict) and is_recipe(data):
                    recipe_data = data
                
                if recipe_data and 'nutrition' in recipe_data:
                    nutrition = recipe_data['nutrition']
                    
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
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:  # Берем последнюю категорию перед самим рецептом
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Сначала пробуем извлечь из JSON-LD
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
                
                # Ищем время в данных
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            recipe_data = item
                            break
                elif isinstance(data, dict) and is_recipe(data):
                    recipe_data = data
                
                if recipe_data:
                    # Маппинг типов времени на ключи JSON-LD
                    time_keys = {
                        'prep': 'prepTime',
                        'cook': 'cookTime',
                        'total': 'totalTime'
                    }
                    
                    key = time_keys.get(time_type)
                    if key and key in recipe_data:
                        iso_time = recipe_data[key]
                        return self.parse_iso_duration(iso_time)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, ищем в HTML
        time_patterns = {
            'prep': ['prep.*time', 'preparation'],
            'cook': ['cook.*time', 'cooking'],
            'total': ['total.*time', 'ready.*in']
        }
        
        patterns = time_patterns.get(time_type, [])
        
        for pattern in patterns:
            # Ищем элемент с временем
            time_elem = self.soup.find(class_=re.compile(pattern, re.I))
            if not time_elem:
                time_elem = self.soup.find(attrs={'data-test-id': re.compile(pattern, re.I)})
            
            if time_elem:
                time_text = time_elem.get_text(strip=True)
                return self.clean_text(time_text)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('total')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями/советами (специфичные классы для AllRecipes)
        notes_section = self.soup.find(class_=re.compile(r'cooksnote', re.I))
        
        if notes_section:
            # Сначала пробуем найти параграф внутри (без заголовка)
            p = notes_section.find('p')
            if p:
                text = self.clean_text(p.get_text())
                return text if text else None
            
            # Если нет параграфа, берем весь текст и убираем заголовок
            text = notes_section.get_text(separator=' ', strip=True)
            text = re.sub(r"^Cook'?s\s+Note\s*", '', text, flags=re.I)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из meta-тега parsely-tags или JavaScript кода"""
        # Список общих слов и фраз без смысловой нагрузки для фильтрации
        stopwords = {
            'recipe', 'recipes', 'how to make', 'how to', 'easy', 'cooking', 'quick',
            'allrecipes', 'food', 'allrecipes.com', 'kitchen', 'simple', 'best',
            'make', 'ingredients', 'video', 'meal', 'prep', 'ideas', 'tips',
            'tricks', 'hacks', 'home', 'family', 'what to make', 'dinner party',
            'prepare', 'friends', 'homemade', 'dish', 'perfect', 'favorite',
            'delicious', 'tutorial', 'demo', 'how', 'to', 'you can cook that',
            'ar', '16x9', 'td', '3play_asr', 'amazon ar batch 001', '5 star',
            'best rated', 'fresh', 'chewy', 'soft', 'moist', 'community recipes',
            'allrecipes allstar recipes', 'special collections', 'more meal ideas'
        }
        
        tags_list = []
        
        # 1. Сначала пробуем извлечь из мета-тега parsely-tags (приоритет)
        parsely_meta = self.soup.find('meta', attrs={'name': 'parsely-tags'})
        if parsely_meta and parsely_meta.get('content'):
            tags_string = parsely_meta['content']
            tags_list = [tag.strip().lower() for tag in tags_string.split(',') if tag.strip()]
        
        # 2. Если не нашли в parsely-tags, ищем в JavaScript коде
        if not tags_list:
            scripts = self.soup.find_all('script', type='text/javascript')
            
            for script in scripts:
                if not script.string:
                    continue
                
                # Ищем строку с тегами в формате: custParams += '&tags=' + encodeURIComponent("...")
                match = re.search(r"custParams\s*\+=\s*['\"]&tags=['\"]\s*\+\s*encodeURIComponent\([\"']([^\"']+)[\"']\)", script.string)
                if match:
                    tags_string = match.group(1)
                    tags_list = [tag.strip().lower() for tag in tags_string.split(',') if tag.strip()]
                    break
        
        if not tags_list:
            return None
        
        # Фильтрация тегов
        filtered_tags = []
        for tag in tags_list:
            # Пропускаем точные совпадения со стоп-словами
            if tag in stopwords:
                continue
            
            # Пропускаем теги короче 3 символов
            if len(tag) < 3:
                continue
            
            filtered_tags.append(tag)
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in filtered_tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        # Возвращаем как строку через запятую
        return ', '.join(unique_tags) if unique_tags else None
    

    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour" или "2 pounds chicken"
            
        Returns:
            dict: {"name": "flour", "amount": "1", "unit": "cup"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
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
        # Примеры: "1 cup flour", "2 tablespoons butter", "1/2 teaspoon salt"
        pattern = r'^([\d\s/.,]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads)?\s*(.+)'
        
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
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish)\b', '', name, flags=re.IGNORECASE)
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
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений (первые 3 + большое изображение)"""
        urls = []
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение (большое)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # twitter:image - часто другой размер/вариант
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Если data - это список, обрабатываем каждый элемент
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe' and 'image' in item:
                            img = item['image']
                            if isinstance(img, str):
                                urls.append(img)
                            elif isinstance(img, list):
                                urls.extend([i for i in img if isinstance(i, str)])
                            elif isinstance(img, dict):
                                if 'url' in img:
                                    urls.append(img['url'])
                                elif 'contentUrl' in img:
                                    urls.append(img['contentUrl'])
                    continue
                
                # Если есть @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
                        # Recipe с image
                        elif item.get('@type') == 'Recipe' and 'image' in item:
                            img = item['image']
                            if isinstance(img, str):
                                urls.append(img)
                            elif isinstance(img, list):
                                urls.extend([i for i in img if isinstance(i, str)])
                            elif isinstance(img, dict):
                                if 'url' in img:
                                    urls.append(img['url'])
                                elif 'contentUrl' in img:
                                    urls.append(img['contentUrl'])
                
                # Если Recipe напрямую
                elif data.get('@type') == 'Recipe' and 'image' in data:
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
            
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Убираем дубликаты, сохраняя порядок, берем первые 3
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
                    if len(unique_urls) >= 3:  # Ограничиваем до 3 изображений
                        break
            return ', '.join(unique_urls) if unique_urls else None
        
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
        instructions = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name.lower() if dish_name else None,
            "description": description.lower() if description else None,
            "ingredients": ingredients,
            "instructions": instructions.lower() if instructions else None,
            "nutrition_info": self.extract_nutrition_info(),
            "category": category.lower() if category else None,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes.lower() if notes else None,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }

def main():
    import os
    # По умолчанию обрабатываем папку recipes/site_1
    recipes_dir = os.path.join("recipes", "allrecipes_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(AllRecipesExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python site_1.py [путь_к_файлу_или_директории]")


if __name__ == "__main__":
    main()
