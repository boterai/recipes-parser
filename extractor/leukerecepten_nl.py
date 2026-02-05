"""
Recipe data extractor for leukerecepten.nl website
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class LeukereceptenExtractor(BaseRecipeExtractor):
    """Extractor for leukerecepten.nl"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Convert ISO 8601 duration to minutes
        
        Args:
            duration: string like "PT20M" or "PT1H30M" or "PT0H25M"
            
        Returns:
            Time in format "X minutes" or "X hour Y minutes"
        """
        if not duration or not duration.startswith('PT'):
            return None
        
        duration = duration[2:]  # Remove "PT"
        
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
        
        # Форматируем время
        if hours > 0 and minutes > 0:
            return f"{hours} hour {minutes} minutes"
        elif hours > 0:
            return f"{hours} hour"
        elif minutes > 0:
            return f"{minutes} minutes"
        
        return None
    
    def extract_json_ld_recipe(self) -> Optional[dict]:
        """Extract Recipe from JSON-LD"""
        # First try standard method
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            if not script.string:
                continue
            
            try:
                # Очищаем строку от управляющих символов
                script_text = ''.join(char for char in script.string if ord(char) >= 32 or char in '\n\r\t')
                
                data = json.loads(script_text)
                
                # Проверяем, является ли это Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                
                # Если есть @graph, ищем в нем
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        
        # Альтернативный подход - извлекаем из HTML напрямую, минуя JSON парсинг
        # Ищем скрипт с Recipe вручную
        html_content = str(self.soup)
        
        # Паттерн для поиска Recipe в JSON-LD
        recipe_pattern = r'<script type="application/ld\+json">\s*\{[^{]*"@type"\s*:\s*"Recipe".*?</script>'
        matches = re.findall(recipe_pattern, html_content, re.DOTALL | re.IGNORECASE)
        
        for match in matches:
            # Извлекаем содержимое между тегами
            json_start = match.find('{')
            json_end = match.rfind('}') + 1
            json_content = match[json_start:json_end]
            
            # Clean and parse
            try:
                # Use a simpler approach - extract needed fields directly
                # instead of full JSON parsing
                return self._parse_recipe_from_html()
            except Exception:
                continue
        
        return None
    
    def _parse_recipe_from_html(self) -> Optional[dict]:
        """Extract recipe fields directly from HTML"""
        html_content = str(self.soup)
        
        result = {}
        
        # Ищем Recipe JSON-LD блок
        recipe_start = html_content.find('"@type": "Recipe"')
        if recipe_start < 0:
            recipe_start = html_content.find('"@type":"Recipe"')
        
        if recipe_start < 0:
            return None
        
        # Берем фрагмент от Recipe до конца скрипта
        recipe_end = html_content.find('</script>', recipe_start)
        recipe_fragment = html_content[recipe_start:recipe_end]
        
        # Извлекаем поля с помощью регулярных выражений из фрагмента Recipe
        # name - ищем после блока author, чтобы не взять имя автора
        # Сначала удаляем блок author
        author_start = recipe_fragment.find('"author"')
        if author_start >= 0:
            author_end = recipe_fragment.find('}', author_start) + 1
            # Ищем name после author
            name_match = re.search(r'"name"\s*:\s*"([^"]+)"', recipe_fragment[author_end:])
            if name_match:
                result['name'] = name_match.group(1)
        else:
            # Если нет author, берем первый name
            name_match = re.search(r'"name"\s*:\s*"([^"]+)"', recipe_fragment)
            if name_match:
                result['name'] = name_match.group(1)
        
        # description
        desc_match = re.search(r'"description"\s*:\s*"([^"]+)"', recipe_fragment)
        if desc_match:
            result['description'] = desc_match.group(1)
        
        # recipeIngredient
        ing_match = re.search(r'"recipeIngredient"\s*:\s*\[(.*?)\]', recipe_fragment, re.DOTALL)
        if ing_match:
            ing_text = ing_match.group(1)
            # Извлекаем все строки в кавычках
            ingredients = re.findall(r'"([^"]+)"', ing_text)
            result['recipeIngredient'] = ingredients
        
        # recipeInstructions - более точный паттерн
        inst_match = re.search(r'"recipeInstructions"\s*:\s*\[(.*?)\](?=\s*,\s*"aggregateRating")', recipe_fragment, re.DOTALL)
        if inst_match:
            inst_text = inst_match.group(1)
            # Извлекаем все "text" поля, учитывая что значение может содержать экранированные кавычки
            # Используем более точный паттерн
            texts = []
            for text_match in re.finditer(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,', inst_text):
                text = text_match.group(1)
                # Декодируем экранированные символы
                text = text.replace('\\n', ' ').replace('\\t', ' ').replace('\\"', '"')
                text = re.sub(r'\s+', ' ', text).strip()
                if text:
                    texts.append(text)
            
            # Формируем список instructions
            if texts:
                result['recipeInstructions'] = [{'text': t} for t in texts]
        
        # prepTime, cookTime, totalTime
        for time_field in ['prepTime', 'cookTime', 'totalTime']:
            time_match = re.search(rf'"{time_field}"\s*:\s*"([^"]+)"', recipe_fragment)
            if time_match:
                result[time_field] = time_match.group(1)
        
        # recipeCategory
        cat_match = re.search(r'"recipeCategory"\s*:\s*"([^"]+)"', recipe_fragment)
        if cat_match:
            result['recipeCategory'] = cat_match.group(1)
        
        # recipeCuisine
        cuisine_match = re.search(r'"recipeCuisine"\s*:\s*"([^"]+)"', recipe_fragment)
        if cuisine_match:
            result['recipeCuisine'] = cuisine_match.group(1)
        
        # keywords
        keywords_match = re.search(r'"keywords"\s*:\s*"([^"]*)"', recipe_fragment)
        if keywords_match:
            result['keywords'] = keywords_match.group(1)
        
        # image
        image_match = re.search(r'"image"\s*:\s*\[(.*?)\]', recipe_fragment, re.DOTALL)
        if image_match:
            img_text = image_match.group(1)
            images = re.findall(r'"(https?://[^"]+)"', img_text)
            result['image'] = images
        
        return result if result else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        recipe_data = self.extract_json_ld_recipe()
        if recipe_data and 'name' in recipe_data:
            name = recipe_data['name']
            # Убираем суффиксы
            name = re.sub(r':\s*.+$', '', name)  # Убираем "Title: subtitle"
            return self.clean_text(name)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r':\s*.+$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD - берем полное описание
        recipe_data = self.extract_json_ld_recipe()
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            # Берем первые два предложения
            sentences = re.split(r'\.\s+', desc)
            if sentences and len(sentences) >= 2:
                # Берем два первых предложения
                return self.clean_text(sentences[0] + '. ' + sentences[1] + '.')
            elif sentences and len(sentences) == 1:
                return self.clean_text(sentences[0] + '.')
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient_string(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "400 gr spaghetti" или "3 eieren"
            
        Returns:
            dict: {"name": "spaghetti", "amount": 400, "units": "gr"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "400 gr spaghetti", "3 eieren", "snuf peper en zout"
        # Сначала пробуем с единицей измерения
        pattern_with_unit = r'^(\d+(?:[.,]\d+)?)\s+(gr|gram|kg|kilogram|ml|liter|l|el|tl|eetlepel|theelepel|stuks?)\s+(.+)$'
        match = re.match(pattern_with_unit, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            amount = amount_str.replace(',', '.')
            # Пробуем конвертировать в число
            try:
                amount = int(amount) if '.' not in amount else float(amount)
            except ValueError:
                pass
            
            # Убираем текст в скобках из названия
            name = re.sub(r'\s*\([^)]+\)\s*', ' ', name).strip()
            
            return {
                "name": name,
                "units": unit,  # units перед amount для соответствия reference
                "amount": amount
            }
        
        # Пробуем без единицы измерения
        pattern_without_unit = r'^(\d+(?:[.,]\d+)?)\s+(.+)$'
        match = re.match(pattern_without_unit, text, re.IGNORECASE)
        
        if match:
            amount_str, name = match.groups()
            amount = amount_str.replace(',', '.')
            try:
                amount = int(amount) if '.' not in amount else float(amount)
            except ValueError:
                pass
            
            # Убираем текст в скобках
            name = re.sub(r'\s*\([^)]+\)\s*', ' ', name).strip()
            
            return {
                "name": name,
                "units": None,
                "amount": amount
            }
        
        # Если паттерн не совпал (например, "snuf peper en zout")
        # Проверяем на "snuf"
        if text.startswith('snuf '):
            return {
                "name": text[5:],  # Убираем "snuf "
                "units": None,
                "amount": "snuf"
            }
        
        # Возвращаем только название
        return {
            "name": text,
            "units": None,
            "amount": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем из JSON-LD
        recipe_data = self.extract_json_ld_recipe()
        if recipe_data and 'recipeIngredient' in recipe_data:
            for ingredient_text in recipe_data['recipeIngredient']:
                parsed = self.parse_ingredient_string(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем из JSON-LD
        recipe_data = self.extract_json_ld_recipe()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            
            if isinstance(instructions, list):
                for item in instructions:
                    if isinstance(item, dict):
                        # HowToSection с itemListElement
                        if item.get('@type') == 'HowToSection' and 'itemListElement' in item:
                            for step in item['itemListElement']:
                                if isinstance(step, dict) and 'text' in step:
                                    text = step['text'].strip()
                                    # Убираем лишние переносы строк и пробелы
                                    text = re.sub(r'\s+', ' ', text)
                                    # Проверяем, не является ли это советом (содержит "tip:")
                                    # Также исключаем строки, которые похожи на советы
                                    if text and 'tip:' not in text.lower() and not text.lower().startswith('sandra'):
                                        # Убираем &nbsp;
                                        text = text.replace('&nbsp;', ' ')
                                        text = re.sub(r'\s+', ' ', text).strip()
                                        if text and len(text) > 10:  # Пропускаем очень короткие строки
                                            steps.append(text)
                        # HowToStep напрямую
                        elif 'text' in item:
                            text = item['text'].strip()
                            text = re.sub(r'\s+', ' ', text)
                            if text and 'tip:' not in text.lower() and not text.lower().startswith('sandra'):
                                text = text.replace('&nbsp;', ' ')
                                text = re.sub(r'\s+', ' ', text).strip()
                                if text and len(text) > 10:
                                    steps.append(text)
                    elif isinstance(item, str):
                        text = item.strip()
                        text = re.sub(r'\s+', ' ', text)
                        if text and 'tip:' not in text.lower() and not text.lower().startswith('sandra'):
                            text = text.replace('&nbsp;', ' ')
                            text = re.sub(r'\s+', ' ', text).strip()
                            if text and len(text) > 10:
                                steps.append(text)
        
        if steps:
            # Объединяем все шаги в одну строку
            return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем из JSON-LD
        recipe_data = self.extract_json_ld_recipe()
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            # Преобразуем на английский
            if category == 'Hoofdgerechten':
                return 'Main Course'
            elif category == 'Voorgerechten':
                return 'Appetizer'
            elif category == 'Desserts':
                return 'Dessert'
            elif category == 'Bijgerechten':
                return 'Side Dish'
            elif category == 'Soepen':
                return 'Soup'
            else:
                return category
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.extract_json_ld_recipe()
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self.extract_json_ld_recipe()
        if recipe_data and 'cookTime' in recipe_data:
            parsed_time = self.parse_iso_duration(recipe_data['cookTime'])
            # Если время равно 0 или None, пробуем извлечь из инструкций
            if parsed_time and parsed_time != '0 minutes':
                return parsed_time
        
        # Пробуем найти в инструкциях упоминание времени приготовления
        instructions = self.extract_instructions()
        if instructions:
            # Ищем паттерны типа "10 min", "1 hour", "30 minutes"
            time_match = re.search(r'(\d+)\s*(?:min(?:utes?)?|uur|hours?)', instructions.lower())
            if time_match:
                minutes = int(time_match.group(1))
                # Проверяем, упоминается ли "час/hour"
                if 'hour' in time_match.group(0) or 'uur' in time_match.group(0):
                    return f"{minutes} hour"
                else:
                    return f"{minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.extract_json_ld_recipe()
        if recipe_data and 'totalTime' in recipe_data:
            total = self.parse_iso_duration(recipe_data['totalTime'])
            # Если totalTime равно 0, пробуем посчитать prep + cook
            if not total or total == '0 minutes':
                prep = self.extract_prep_time()
                cook = self.extract_cook_time()
                
                # Извлекаем числа из строк
                prep_mins = 0
                cook_mins = 0
                
                if prep:
                    prep_match = re.search(r'(\d+)\s*hour', prep)
                    if prep_match:
                        prep_mins += int(prep_match.group(1)) * 60
                    prep_match = re.search(r'(\d+)\s*minute', prep)
                    if prep_match:
                        prep_mins += int(prep_match.group(1))
                
                if cook:
                    cook_match = re.search(r'(\d+)\s*hour', cook)
                    if cook_match:
                        cook_mins += int(cook_match.group(1)) * 60
                    cook_match = re.search(r'(\d+)\s*minute', cook)
                    if cook_match:
                        cook_mins += int(cook_match.group(1))
                
                total_mins = prep_mins + cook_mins
                if total_mins > 0:
                    hours = total_mins // 60
                    mins = total_mins % 60
                    if hours > 0 and mins > 0:
                        return f"{hours} hour {mins} minutes"
                    elif hours > 0:
                        return f"{hours} hour"
                    else:
                        return f"{mins} minutes"
            
            return total
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        tips = []
        
        # Ищем в инструкциях строки с "tip:" или начинающиеся с Sandra
        recipe_data = self.extract_json_ld_recipe()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            
            if isinstance(instructions, list):
                for item in instructions:
                    if isinstance(item, dict) and 'text' in item:
                        text = item['text'].strip()
                        # Ищем советы - строки с "tip:" (с разными апострофами) или начинающиеся с Sandra
                        is_tip = False
                        text_lower = text.lower()
                        
                        # Проверяем на разные варианты "tip:"
                        if 'tip:' in text or 'tip:' in text or 'tip:' in text:
                            is_tip = True
                        # Проверяем на начало с Sandra
                        if text_lower.startswith('sandra'):
                            is_tip = True
                        
                        if is_tip:
                            # Убираем префикс "Sandra's tip:" и т.п. с разными апострофами
                            text = re.sub(r'^.+?tip:\s*', '', text, flags=re.IGNORECASE)
                            text = re.sub(r'^.+?tip:\s*', '', text, flags=re.IGNORECASE)
                            text = re.sub(r'^.+?tip:\s*', '', text, flags=re.IGNORECASE)
                            text = re.sub(r'\s+', ' ', text)
                            text = text.replace('&nbsp;', ' ')
                            text = re.sub(r'\s+', ' ', text).strip()
                            # Capitalize first letter
                            if text:
                                text = text[0].upper() + text[1:] if len(text) > 1 else text.upper()
                                tips.append(text)
        
        if tips:
            return ' '.join(tips)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Из JSON-LD берем keywords
        recipe_data = self.extract_json_ld_recipe()
        if recipe_data:
            # Если есть keywords, используем их
            if 'keywords' in recipe_data and recipe_data['keywords']:
                keywords = recipe_data['keywords']
                if keywords:
                    # Разбиваем по запятой
                    return ', '.join([tag.strip() for tag in keywords.split(',') if tag.strip()])
            
            # Если нет keywords, формируем из разных источников
            # 1. Извлекаем ключевые слова из названия блюда
            dish_name = self.extract_dish_name()
            if dish_name:
                # Берем первые 2 слова из названия (основной ингредиент и тип)
                name_words = dish_name.lower().replace(':', '').split()
                for i, word in enumerate(name_words[:2]):  # Берем первые 2 слова
                    if word not in ['recept', 'klassiek', 'perfecte', 'de', 'het', 'een']:
                        tags.append(word)
            
            # 2. Из cuisine (Italiaanse recepten -> Italiaans)
            if 'recipeCuisine' in recipe_data and recipe_data['recipeCuisine']:
                cuisine = recipe_data['recipeCuisine']
                cuisine = cuisine.replace(' recepten', '').replace(' gerechten', '')
                if cuisine.endswith('e'):
                    cuisine = cuisine[:-1]  # Italiaanse -> Italiaans
                tags.append(cuisine)
            
            # 3. Из category (Hoofdgerechten -> hoofdgerecht)
            if 'recipeCategory' in recipe_data and recipe_data['recipeCategory']:
                category = recipe_data['recipeCategory']
                if category == 'Hoofdgerechten':
                    tags.append('hoofdgerecht')
                elif category.endswith('en'):
                    tags.append(category[:-2])  # Desserts -> Dessert не нужно
                else:
                    tags.append(category.lower())
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Из JSON-LD
        recipe_data = self.extract_json_ld_recipe()
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            if isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
        # Из og:image
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
        Extract all recipe data
        
        Returns:
            Dictionary with recipe data
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
    # By default process folder preprocessed/leukerecepten_nl
    preprocessed_dir = os.path.join("preprocessed", "leukerecepten_nl")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(LeukereceptenExtractor, str(preprocessed_dir))
        return
    
    print(f"Directory not found: {preprocessed_dir}")
    print("Usage: python leukerecepten_nl.py")


if __name__ == "__main__":
    main()
