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
                    ingredients.append(ingredient_text)
            
            if ingredients:
                break
        
        return ', '.join(ingredients) if ingredients else None
    
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
    
    def extract_servings(self) -> Optional[str]:
        """Извлечение количества порций"""
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
                
                # Ищем recipeYield в данных
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            recipe_data = item
                            break
                elif isinstance(data, dict) and is_recipe(data):
                    recipe_data = data
                
                if recipe_data and 'recipeYield' in recipe_data:
                    yield_value = recipe_data['recipeYield']
                    # Может быть строкой, числом или списком
                    if isinstance(yield_value, list):
                        # Берем первый элемент списка (обычно это число порций)
                        return str(yield_value[0]) if yield_value else None
                    return str(yield_value)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, ищем в HTML
        servings_elem = self.soup.find(class_=re.compile(r'servings?|yield', re.I))
        if not servings_elem:
            servings_elem = self.soup.find(attrs={'data-test-id': re.compile(r'servings?', re.I)})
        
        if servings_elem:
            text = servings_elem.get_text(strip=True)
            # Извлекаем только число или число с единицей
            match = re.search(r'\d+(?:\s*servings?)?', text, re.I)
            if match:
                return match.group(0)
        
        return None
    
    def extract_difficulty_level(self) -> Optional[str]:
        """Извлечение уровня сложности"""
        # На allrecipes обычно нет явного указания сложности
        # Можно попробовать определить по времени или оставить как "Easy"
        return "N/A"
    
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
    
    def extract_rating(self) -> Optional[float]:
        """Извлечение рейтинга рецепта"""
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
                
                # Ищем aggregateRating в данных
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            recipe_data = item
                            break
                elif isinstance(data, dict) and is_recipe(data):
                    recipe_data = data
                
                if recipe_data and 'aggregateRating' in recipe_data:
                    rating_data = recipe_data['aggregateRating']
                    if 'ratingValue' in rating_data:
                        return float(rating_data['ratingValue'])
                        
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
        
        return None
    
    def extract_ingredients_names(self) -> Optional[str]:
        """
        Извлечение только названий ингредиентов без количества
        
        Returns:
            Строка с названиями ингредиентов через запятую или None
        """
        import re
        
        names = []
        
        # Сначала пробуем извлечь из структурированных данных HTML
        # Ищем элементы с атрибутом data-ingredient-name
        ingredient_items = self.soup.find_all(attrs={'data-ingredient-name': True})
        
        if ingredient_items:
            for item in ingredient_items:
                name = item.get_text(strip=True)
                if name:
                    # Убираем "(Optional)" и другие уточнения в скобках
                    name = re.sub(r'\s*\([^)]*\)', '', name)
                    name = name.strip()
                    if name:
                        names.append(name)
            
            if names:
                return ', '.join(names)
        
        # Если структурированные данные не найдены, используем fallback метод
        ingredients_raw = self.extract_ingredients()
        if not ingredients_raw:
            return None
        
        lines = ingredients_raw.split('\n')
        names = []
        
        for line in lines:
            # Удаляем Unicode дроби
            line = line.replace('½', '').replace('¼', '').replace('¾', '').replace('⅓', '').replace('⅔', '')
            line = line.replace('⅛', '').replace('⅜', '').replace('⅝', '').replace('⅞', '')
            
            # Удаляем числа и дроби в начале строки (количество)
            line = re.sub(r'^[\d\s/.,]+', '', line)
            
            # Удаляем единицы измерения с учетом множественного числа
            units_pattern = r'\b(?:' + '|'.join([
                'cups?', 'tablespoons?', 'teaspoons?', 'tbsp', 'tsp',
                'pounds?', 'ounces?', 'lbs?', 'oz',
                'grams?', 'kilograms?', 'g', 'kg',
                'milliliters?', 'liters?', 'ml', 'l',
                'pinch(?:es)?', 'dash(?:es)?', 'packages?', 'cans?', 'jars?', 'bottles?',
                'inch(?:es)?', 'slices?', 'cloves?', 'bunches?', 'sprigs?',
                'whole', 'halves?', 'quarters?', 'pieces?',
                'to taste', 'as needed', 'or more', 'if needed', 'optional'
            ]) + r')\b'
            
            line = re.sub(units_pattern, '', line, flags=re.IGNORECASE)
            
            # Удаляем скобки с содержимым (уточнения типа "(such as Granny Smith)")
            line = re.sub(r'\([^)]*\)', '', line)
            
            # Удаляем лишние символы и пробелы
            line = re.sub(r'[,;]+$', '', line)  # запятые/точки с запятой в конце
            line = re.sub(r'\s+', ' ', line).strip()
            
            if line and len(line) > 1:  # пропускаем пустые и одиночные символы
                names.append(line.lower())
        
        return json.dumps(names) if names else None
    
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта
        
        Returns:
            Словарь с данными рецепта
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        ingredients_names = self.extract_ingredients_names()
        step_by_step = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name.lower() if dish_name else None,
            "description": description.lower() if description else None,
            "ingredients": ingredients.lower() if ingredients else None,
            "ingredients_names": ingredients_names.lower() if ingredients_names else None,
            "step_by_step": step_by_step.lower() if step_by_step else None,
            "nutrition_info": self.extract_nutrition_info(),
            "category": category.lower() if category else None,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "servings": self.extract_servings(),
            "difficulty_level": self.extract_difficulty_level(),
            "rating": self.extract_rating(),
            "notes": notes.lower() if notes else None,
            "tags": tags
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
