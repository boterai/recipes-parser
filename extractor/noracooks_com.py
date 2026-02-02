"""
Экстрактор данных рецептов для сайта noracooks.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class NoraCooksExtractor(BaseRecipeExtractor):
    """Экстрактор для noracooks.com"""
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение данных Recipe из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем @graph структуру
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            return item
                
                # Проверяем прямую структуру
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                
                # Проверяем список
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                            
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Из h1 заголовка
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Пробуем извлечь из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredient_texts = recipe_data['recipeIngredient']
            if isinstance(ingredient_texts, list):
                for ingredient_text in ingredient_texts:
                    # Обрабатываем сложные ингредиенты вида "optional: A (1-2 tsp), B (1/4 cup)"
                    if ingredient_text.lower().startswith('optional:'):
                        # Убираем "optional:" и разбиваем по запятой
                        text = ingredient_text[9:].strip()
                        # Разбиваем на отдельные ингредиенты по запятой с учетом скобок
                        parts = []
                        current = ""
                        paren_count = 0
                        for char in text:
                            if char == '(':
                                paren_count += 1
                            elif char == ')':
                                paren_count -= 1
                            elif char == ',' and paren_count == 0:
                                parts.append(current.strip())
                                current = ""
                                continue
                            current += char
                        if current.strip():
                            parts.append(current.strip())
                        
                        # Обрабатываем каждую часть
                        for part in parts:
                            parsed = self.parse_ingredient(part)
                            if parsed:
                                ingredients.append(parsed)
                    else:
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
        
        # Если не нашли в JSON-LD, пробуем в HTML
        if not ingredients:
            # Ищем список ингредиентов через различные возможные классы
            ingredient_containers = self.soup.find_all('li', class_=re.compile(r'wprm-recipe-ingredient', re.I))
            
            for item in ingredient_containers:
                ingredient_text = item.get_text(separator=' ', strip=True)
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
            ingredient_text: Строка ингредиента
            
        Returns:
            dict: {"name": "flour", "amount": 1, "units": "cup"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Обрабатываем ингредиенты вида "optional: ... , ..." - разбиваем на отдельные
        if text.lower().startswith('optional:'):
            # Убираем "optional:" и разбиваем по запятой
            text = text[9:].strip()
            # Возвращаем только первый ингредиент из списка
            parts = text.split(',')
            if parts:
                text = parts[0].strip()
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': ' 1/2', '¼': ' 1/4', '¾': ' 3/4',
            '⅓': ' 1/3', '⅔': ' 2/3', '⅛': ' 1/8',
            '⅜': ' 3/8', '⅝': ' 5/8', '⅞': ' 7/8',
            '⅕': ' 1/5', '⅖': ' 2/5', '⅗': ' 3/5', '⅘': ' 4/5'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1 cup flour", "2 tablespoons butter", "1/2 teaspoon salt", "1-2 cloves garlic"
        pattern = r'^([\d\s/.\-]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|heads?|medium|large|small|unit)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Если количество/единица не найдены в начале, проверяем в скобках в имени
        if not amount_str or not unit:
            # Ищем паттерн в скобках: "(1-2 teaspoons)" или "(1/4 cup, ...)"
            paren_match = re.search(r'\(([^)]+)\)', name)
            if paren_match:
                paren_content = paren_match.group(1)
                # Пробуем распарсить содержимое скобок
                paren_pattern = r'^([\d\s/.\-]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?)'
                paren_result = re.match(paren_pattern, paren_content, re.IGNORECASE)
                if paren_result and not amount_str:
                    amount_str = paren_result.group(1)
                    if not unit:
                        unit = paren_result.group(2)
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2" или "1 1/2" или диапазонов "1-2"
            if '-' in amount_str and '/' not in amount_str:
                # Диапазон типа "1-2" - берем первое значение
                parts = amount_str.split('-')
                amount_str = parts[0].strip()
            
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
                        except ValueError:
                            pass
                amount = total
            else:
                # Убираем запятые
                amount_str = amount_str.replace(',', '.')
                try:
                    amount = float(amount_str)
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения - множественное число для units
        if unit:
            unit = unit.strip().lower()
            # Преобразуем в множественное число если нужно
            if not unit.endswith('s') and unit not in ['oz', 'g', 'kg', 'ml', 'l', 'medium', 'large', 'small', 'unit']:
                # Добавляем 's' для множественного числа
                if unit.endswith('h'):
                    unit = unit + 'es'  # inch -> inches
                elif unit == 'clove':
                    unit = 'cloves'
                else:
                    unit = unit + 's'
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional", "for cheesy flavor"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|for cheesy flavor)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit if unit else None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Пробуем извлечь из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        steps.append(f"{idx}. {step_text}")
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        steps.append(f"{idx}. {step_text}")
        
        # Если не нашли в JSON-LD, пробуем в HTML
        if not steps:
            instruction_items = self.soup.find_all('li', class_=re.compile(r'wprm-recipe-instruction', re.I))
            
            for idx, item in enumerate(instruction_items, 1):
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    # Если уже есть нумерация, не добавляем
                    if re.match(r'^\d+\.', step_text):
                        steps.append(step_text)
                    else:
                        steps.append(f"{idx}. {step_text}")
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем из Article articleSection в @graph
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list):
                                # Ищем категорию типа блюда - обычно содержит определенные ключевые слова
                                # Приоритет: ищем секции с типами блюд
                                dish_type_keywords = ['sauce', 'dressing', 'main', 'dessert', 'appetizer', 
                                                     'breakfast', 'lunch', 'dinner', 'snack', 'side', 'soup', 'salad']
                                
                                for section in sections:
                                    section_clean = self.clean_text(section)
                                    section_lower = section_clean.lower()
                                    # Проверяем, содержит ли секция ключевые слова типов блюд
                                    if any(keyword in section_lower for keyword in dish_type_keywords):
                                        return section_clean
                                
                                # Если не нашли по ключевым словам, берем первую не-общую категорию
                                skip_categories = ['meal type', 'special dietary needs', 'vegan ingredients', 
                                                  'gluten free', 'oil free', 'nut free', 'dairy free']
                                for section in sections:
                                    section_clean = self.clean_text(section)
                                    if section_clean.lower() not in skip_categories:
                                        return section_clean
                                        
                            elif isinstance(sections, str):
                                return self.clean_text(sections)
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        # Из хлебных крошек в @graph
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BreadcrumbList' and 'itemListElement' in item:
                            breadcrumbs = item['itemListElement']
                            if len(breadcrumbs) > 2:
                                # Берем предпоследний элемент (последний - это сам рецепт)
                                category_item = breadcrumbs[-2]
                                if 'name' in category_item:
                                    return self.clean_text(category_item['name'])
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        # Пробуем из Recipe JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data:
            # Проверяем recipeCategory
            if 'recipeCategory' in recipe_data:
                category = recipe_data['recipeCategory']
                if isinstance(category, list) and category:
                    return self.clean_text(category[0])
                elif isinstance(category, str):
                    return self.clean_text(category)
        
        return None
    
    def parse_iso_duration(self, duration: str) -> Optional[str]:
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
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self._get_recipe_json_ld()
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
        # Ищем секцию с примечаниями в HTML
        notes_section = self.soup.find('div', class_=re.compile(r'wprm-recipe-notes\b', re.I))
        
        if notes_section:
            # Извлекаем текст
            text = notes_section.get_text(separator=' ', strip=True)
            # Убираем возможный заголовок "Notes:"
            text = re.sub(r'^Notes?\s*:?\s*', '', text, flags=re.IGNORECASE)
            text = self.clean_text(text)
            
            # Берем только первые 2-3 предложения (как в эталоне)
            # Разбиваем по точкам с пробелом
            sentences = re.split(r'\.\s+', text)
            if sentences:
                # Берем первые 2 предложения
                result = '. '.join(sentences[:2])
                if result and not result.endswith('.'):
                    result += '.'
                return result if result else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Сначала проверяем в Recipe keywords
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Разделяем по запятой
                tags = [self.clean_text(tag.strip().lower()) for tag in keywords.split(',') if tag.strip()]
            elif isinstance(keywords, list):
                tags = [self.clean_text(tag.lower()) for tag in keywords if tag]
        
        # Если не нашли в Recipe, проверяем в Article
        if not tags:
            json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and '@graph' in data:
                        for item in data['@graph']:
                            if item.get('@type') == 'Article' and 'keywords' in item:
                                keywords = item['keywords']
                                if isinstance(keywords, list):
                                    for keyword in keywords:
                                        tag = self.clean_text(keyword.lower())
                                        if tag and tag not in tags:
                                            tags.append(tag)
                except (json.JSONDecodeError, KeyError, AttributeError):
                    continue
        
        # Добавляем общие теги из описания или категории если есть
        # Например, "vegan", "dairy-free" и т.д.
        # Проверим description на наличие таких слов
        description = self.extract_description()
        if description and not tags:
            desc_lower = description.lower()
            common_tags = ['vegan', 'dairy-free', 'gluten-free', 'oil-free', 'nut-free']
            for tag in common_tags:
                if tag in desc_lower and tag not in tags:
                    tags.append(tag)
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Сначала из JSON-LD Recipe
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                for image in img:
                    if isinstance(image, str):
                        urls.append(image)
                    elif isinstance(image, dict):
                        if 'url' in image:
                            urls.append(image['url'])
                        elif 'contentUrl' in image:
                            urls.append(image['contentUrl'])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
        # Из meta тегов
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Точка входа для обработки HTML страниц noracooks.com"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "noracooks_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(NoraCooksExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python noracooks_com.py")


if __name__ == "__main__":
    main()
