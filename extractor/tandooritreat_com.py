"""
Экстрактор данных рецептов для сайта tandooritreat.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TandooriTreatExtractor(BaseRecipeExtractor):
    """Экстрактор для tandooritreat.com"""
    
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
        
        # Если минут больше 60 и нет часов, конвертируем в часы и минуты
        if minutes >= 60 and hours == 0:
            hours = minutes // 60
            minutes = minutes % 60
        
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
            name = self.clean_text(json_ld['name'])
            # Убираем суффикс "Recipe" если есть
            name = re.sub(r'\s+Recipe$', '', name, flags=re.IGNORECASE)
            return name
        
        # Fallback: ищем в h1
        h1 = self.soup.find('h1')
        if h1:
            name = self.clean_text(h1.get_text())
            name = re.sub(r'\s+Recipe$', '', name, flags=re.IGNORECASE)
            return name
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем первый значимый параграф после заголовка
        article = self.soup.find('article') or self.soup.find('main') or self.soup.body
        if article:
            h1 = article.find('h1')
            if h1:
                # Ищем первый параграф после h1 с достаточным текстом
                next_p = h1.find_next('p')
                count = 0
                while next_p and count < 10:
                    text = next_p.get_text(strip=True)
                    # Пропускаем параграфы с техническими деталями, оборудованием и ингредиентами
                    if (text and len(text) > 40 and 
                        not text.startswith('Equipment') and 
                        'tbsp' not in text and 
                        'tsp' not in text and
                        not text.startswith('Serves') and
                        not text.startswith('Prep time')):
                        # Берем первое предложение или до точки
                        sentences = text.split('.')
                        if sentences:
                            desc = sentences[0].strip() + '.'
                            return self.clean_text(desc)
                    next_p = next_p.find_next('p')
                    count += 1
        
        # Fallback: JSON-LD description
        json_ld = self._get_json_ld_data()
        if json_ld and 'description' in json_ld:
            desc = self.clean_text(json_ld['description'])
            # Убираем шаблонную фразу "My favourite ... recipe"
            desc = re.sub(r'^My favourite?\s+.*?\s+recipe\s*', '', desc, flags=re.IGNORECASE)
            if desc and len(desc) > 10:
                return desc
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "2 tbsp neutral oil (vegetable or canola)"
            
        Returns:
            dict: {"name": "neutral oil", "amount": 2, "units": "tbsp"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Удаляем скобки с содержимым
        text = re.sub(r'\([^)]*\)', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.3333333333333333', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн: [количество] [единица] [остальное]
        # Количество может быть числом или текстом типа "small bunch", "pinch"
        # Единица может быть tbsp, cup, etc. или отсутствовать
        
        # Сначала пробуем извлечь числовое количество и единицу
        pattern = r'^([\d\s/.,]+)\s+(tbsp|tsp|tablespoon|tablespoons|teaspoon|teaspoons|cup|cups|oz|ounce|ounces|pound|pounds|lb|lbs|gram|grams|kg|kilogram|kilograms|ml|milliliter|milliliters|liter|liters|can|cans|jar|jars|slice|slices|medium|large|small)\s+(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                amount_str = amount_str.strip()
                if '/' in amount_str:
                    parts = amount_str.split()
                    total = 0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            total += float(part)
                    amount = total
                else:
                    try:
                        amount = float(amount_str.replace(',', '.'))
                    except ValueError:
                        amount = amount_str
            
            # Обработка имени и units
            # Проверяем, есть ли запятая в имени (модификатор)
            if ',' in name:
                name_parts = name.split(',')
                name = name_parts[0].strip()
                # Все что после запятой - модификаторы
                modifiers = ', '.join([p.strip() for p in name_parts[1:]])
                units = f"{unit}, {modifiers}"
            # Проверяем, есть ли "or" вариант (например, "lime juice or juice of 1 lime")
            elif ' or ' in name:
                # Разделяем по "or"
                name_parts = name.split(' or ', 1)
                name = name_parts[0].strip()
                alternative = name_parts[1].strip()
                units = f"{unit} or {alternative}"
            else:
                # Проверяем, есть ли слова типа "grated", "chopped" в начале имени
                prep_words = ['grated', 'chopped', 'minced', 'diced', 'sliced', 'shredded', 'crushed']
                words = name.split()
                if words and words[0].lower() in prep_words:
                    # Это метод приготовления, добавляем к unit
                    prep = words[0]
                    name = ' '.join(words[1:])
                    units = f"{unit}, {prep}"
                else:
                    # Слова типа "ground", "fresh", "whole" - это часть названия ингредиента
                    name = name.strip()
                    units = unit
            
            # Удаляем фразы "or more", "adjust to taste" и т.д.
            name = re.sub(r'\b(or more|if needed|optional|optonal|adjust to taste|to taste|as needed)\b', '', name, flags=re.IGNORECASE)
            # Очистка "or" в конце
            name = re.sub(r'\s+or\s*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'[,;]+$', '', name).strip()
            
            return {
                "name": name,
                "amount": amount,
                "units": units
            }
        
        # Если не нашли числовое количество с единицей, пробуем другие паттерны
        # Например: "small bunch fresh cilantro, chopped" или "pinch of salt"
        size_words = r'^(small|medium|large|tiny|big|whole|half|quarter)\s+(bunch|pinch|handful|dash|sprinkle|piece|pieces|clove|cloves)\s+(.+)$'
        match2 = re.match(size_words, text, re.IGNORECASE)
        
        if match2:
            size, unit_word, name = match2.groups()
            amount = f"{size} {unit_word}"
            
            # Проверяем запятую
            if ',' in name:
                name_parts = name.split(',')
                name = name_parts[0].strip()
                modifiers = ', '.join([p.strip() for p in name_parts[1:]])
                units = modifiers
            else:
                name = name.strip()
                units = None
            
            # Удаляем "or" варианты
            name = re.sub(r'\s+or\s+.+$', '', name)
            
            return {
                "name": name,
                "amount": amount,
                "units": units
            }
        
        # Еще один паттерн: "3 garlic cloves, minced" (число без единицы, но с предметом)
        pattern3 = r'^([\d\s/.,]+)\s+([a-z\s]+?),\s*(.+)$'
        match3 = re.match(pattern3, text, re.IGNORECASE)
        
        if match3:
            amount_str, name, modifier = match3.groups()
            
            amount = None
            if amount_str:
                amount_str = amount_str.strip()
                if '/' in amount_str:
                    parts = amount_str.split()
                    total = 0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            total += float(part)
                    amount = total
                else:
                    try:
                        amount = float(amount_str.replace(',', '.'))
                    except ValueError:
                        amount = amount_str
            
            return {
                "name": name.strip(),
                "amount": amount,
                "units": modifier.strip()
            }
        
        # Последний паттерн: просто "число название" без модификаторов
        pattern4 = r'^([\d\s/.,]+)\s+(.+)$'
        match4 = re.match(pattern4, text)
        
        if match4:
            amount_str, name = match4.groups()
            
            amount = None
            if amount_str:
                amount_str = amount_str.strip()
                if '/' in amount_str:
                    parts = amount_str.split()
                    total = 0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            total += float(part)
                    amount = total
                else:
                    try:
                        amount = float(amount_str.replace(',', '.'))
                    except ValueError:
                        amount = amount_str
            
            return {
                "name": name.strip(),
                "amount": amount,
                "units": None
            }
        
        # Если ничего не подошло, возвращаем как есть
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeIngredient' in json_ld:
            ingredients_list = json_ld['recipeIngredient']
            
            if isinstance(ingredients_list, list):
                parsed_ingredients = []
                
                for ingredient_text in ingredients_list:
                    if isinstance(ingredient_text, str):
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            parsed_ingredients.append(parsed)
                
                if parsed_ingredients:
                    return json.dumps(parsed_ingredients, ensure_ascii=False)
        
        return None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
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
            
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности в формате: 202 kcal; 2/11/27"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'nutrition' in json_ld:
            nutrition = json_ld['nutrition']
            
            # Извлекаем калории
            calories = None
            if 'calories' in nutrition:
                cal_text = nutrition['calories']
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
            # Проверяем recipeCategory
            if 'recipeCategory' in json_ld:
                category = json_ld['recipeCategory']
                if isinstance(category, list):
                    return self.clean_text(', '.join(category))
                elif isinstance(category, str):
                    return self.clean_text(category)
            
            # Пробуем определить категорию по ключевым словам и тегам
            keywords = json_ld.get('keywords', '').lower()
            dish_name = json_ld.get('name', '').lower()
            
            # Проверяем на десерты
            if any(word in keywords or word in dish_name for word in ['dessert', 'ice cream', 'cake', 'cookie', 'sweet']):
                return 'Dessert'
            
            # Проверяем на основные блюда
            if any(word in keywords or word in dish_name for word in ['curry', 'main', 'dinner', 'entree']):
                return 'Main Course'
            
            # Проверяем на закуски
            if any(word in keywords or word in dish_name for word in ['appetizer', 'snack', 'starter']):
                return 'Appetizer'
            
            # Проверяем на завтрак
            if any(word in keywords or word in dish_name for word in ['breakfast', 'brunch']):
                return 'Breakfast'
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        # Fallback: ищем в тексте "ready in X minutes" или "in X minutes"
        # Look in the instructions or first few paragraphs
        text_to_search = []
        
        # Check instructions last step
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            if isinstance(instructions, list) and instructions:
                last_step = instructions[-1]
                if isinstance(last_step, dict) and 'text' in last_step:
                    text_to_search.append(last_step['text'])
        
        # Check first few paragraphs
        for p in self.soup.find_all('p', limit=5):
            text_to_search.append(p.get_text())
        
        # Search for time patterns
        for text in text_to_search:
            # Pattern: "ready in about 30 minutes", "in 30 minutes", "takes 20 minutes"
            match = re.search(r'(?:ready in|in|takes?)\s+(?:about\s+)?(\d+)\s+minute', text, re.IGNORECASE)
            if match:
                minutes = match.group(1)
                return f"{minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с заметками в HTML
        # Приоритет: краткие практические советы из "Pro Tips" или "Notes"
        
        notes_text = []
        
        # Ищем заголовки "Notes", "Tips", "Pro Tips", "Substitutions"
        for heading in self.soup.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text(strip=True).lower()
            
            # Приоритет: Pro Tips или Notes (короткие практические советы)
            if 'pro tip' in heading_text or (('note' in heading_text or 'tip' in heading_text) and 'substitution' not in heading_text):
                next_elem = heading.find_next_sibling()
                
                # Берем первые 1-2 совета
                count = 0
                while next_elem and count < 2 and next_elem.name not in ['h1', 'h2', 'h3', 'h4', 'div']:
                    if next_elem.name == 'p':
                        text = self.clean_text(next_elem.get_text())
                        # Убираем номерацию типа "1. "
                        text = re.sub(r'^\d+\.\s*', '', text)
                        if text and len(text) > 20:
                            notes_text.append(text)
                            count += 1
                    elif next_elem.name == 'ul':
                        items = next_elem.find_all('li')
                        for item in items[:2]:  # Берем первые 2 пункта
                            text = self.clean_text(item.get_text())
                            if text and len(text) > 20:
                                notes_text.append(text)
                                count += 1
                                if count >= 2:
                                    break
                    
                    next_elem = next_elem.find_next_sibling()
                
                if notes_text:
                    return ' '.join(notes_text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        json_ld = self._get_json_ld_data()
        tags = []
        
        if json_ld:
            keywords = json_ld.get('keywords', '')
            dish_name = json_ld.get('name', '')
            
            if isinstance(keywords, str) and keywords:
                # Извлекаем теги из keywords и названия блюда
                keywords_lower = keywords.lower()
                dish_name_lower = dish_name.lower()
                
                # Удаляем "recipe" из keywords
                keywords_clean = re.sub(r'\brecipe\b', '', keywords_lower)
                
                # Разбиваем на слова
                words = re.findall(r'\b\w+\b', keywords_clean)
                
                # Список ключевых дескрипторов, которые полезны как теги
                key_descriptors = {
                    'vegan', 'vegetarian', 'healthy', 'easy', 'quick', 'simple', 
                    'dessert', 'curry', 'ice', 'cream', 'yogurt', 'greek', 
                    'mushrooms', 'garlic', 'toast', 'cheese', 'sandwiches',
                    'main', 'breakfast', 'lunch', 'dinner', 'snack', 'appetizer',
                    'baked', 'fried', 'grilled', 'roasted', 'gluten', 'free',
                    'dairy', 'keto', 'paleo', 'whole', 'grain', 'spicy', 'mild',
                    'creamy', 'crunchy', 'soft', 'fresh', 'frozen', 'homemade',
                    'traditional', 'classic', 'modern', 'fusion'
                }
                
                # Фильтруем стоп-слова и короткие слова
                stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'my', 'favourite', 'favorite'}
                meaningful_words = []
                
                for word in words:
                    if len(word) >= 3 and word not in stopwords:
                        # Добавляем ключевые дескрипторы
                        if word in key_descriptors:
                            if word not in meaningful_words:
                                meaningful_words.append(word)
                        # Или слова, которые не являются частью названия блюда
                        elif word not in dish_name_lower:
                            if word not in meaningful_words:
                                meaningful_words.append(word)
                
                tags = meaningful_words[:10]  # Ограничиваем количество тегов
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
        # 2. Ищем в мета-тегах
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
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "nutrition_info": self.extract_nutrition_info(),
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/tandooritreat_com
    preprocessed_dir = os.path.join("preprocessed", "tandooritreat_com")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(TandooriTreatExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python tandooritreat_com.py")


if __name__ == "__main__":
    main()
