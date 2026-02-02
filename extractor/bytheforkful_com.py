"""
Экстрактор данных рецептов для сайта bytheforkful.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ByTheForkfulExtractor(BaseRecipeExtractor):
    """Экстрактор для bytheforkful.com"""
    
    def _find_recipe_json_ld(self) -> Optional[dict]:
        """Поиск и извлечение Recipe из JSON-LD структуры"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                
                # Проверяем прямо в data
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                
                # Проверяем список
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты с текстом
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "45 minutes"
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
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пытаемся из JSON-LD
        recipe_data = self._find_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            name = self.clean_text(recipe_data['name'])
            # Убираем суффикс "Recipe"
            name = re.sub(r'\s+Recipe\s*$', '', name, flags=re.IGNORECASE)
            return name
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " Recipe", " | Vegan", " | Under 30 Minutes"
            title = re.sub(r'\s+\|.*$', '', title)
            title = re.sub(r'\s+Recipe.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            title = re.sub(r'\s+\|.*$', '', title)
            title = re.sub(r'\s+Recipe.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала из JSON-LD
        recipe_data = self._find_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD в структурированном формате"""
        ingredients = []
        
        # Приоритет - JSON-LD, так как там структурированные данные
        recipe_data = self._find_recipe_json_ld()
        if recipe_data and 'recipeIngredient' in recipe_data:
            # В JSON-LD ингредиенты обычно в виде списка строк
            recipe_ingredients = recipe_data['recipeIngredient']
            
            if isinstance(recipe_ingredients, list):
                for ingredient_text in recipe_ingredients:
                    if isinstance(ingredient_text, str):
                        # Парсим каждый ингредиент
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
        
        # Если JSON-LD не помог, пытаемся из HTML
        if not ingredients:
            # Ищем секцию с ингредиентами
            ingredients_section = self.soup.find(class_='mv-create-ingredients')
            
            if ingredients_section:
                # Извлекаем элементы списка
                items = ingredients_section.find_all('li')
                
                for item in items:
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
            ingredient_text: Строка вида "200 g flour" или "2 tablespoons butter"
            
        Returns:
            dict: {"name": "flour", "amount": 200, "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅙': '0.166',
            '⅛': '0.125', '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "200 g flour", "2 tablespoons butter", "1/2 teaspoon salt", "2 cloves of garlic", "1 green chilli"
        # Две версии: одна требует число перед короткими единицами (g, ml, kg, l), другая для всех остальных
        
        # Сначала пробуем паттерн с короткими единицами (требуют число)
        short_unit_pattern = r'^([\d\s/.,]+)\s*(g|kg|ml|l)\s+(.+)'
        match = re.match(short_unit_pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
        else:
            # Пробуем общий паттерн для остальных единиц
            pattern = r'^([\d\s/.,]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|milliliters?|liters?|pinch(?:es)?|dash(?:es)?|packages?|pkg|cans?|tins?|tinned|jars?|bottles?|inch(?:es)?|slices?|slice|cloves?|clove|bunches?|sprigs?|whole|halves?|half|quarters?|pieces?|head|heads|can|diced|minced|juiced|zest|sticks?|stick)?\s*(?:of\s+)?(.+)'
            
            match = re.match(pattern, text, re.IGNORECASE)
            
            if not match:
                # Если паттерн не совпал, возвращаем только название
                return {
                    "name": text.lower(),
                    "amount": None,
                    "units": None
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
                amount = total
            else:
                try:
                    amount = float(amount_str.replace(',', '.'))
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|approximately|grated or paste|add more for extra spice)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name.lower(),
            "amount": amount,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions_text = []
        
        # Сначала пробуем из JSON-LD
        recipe_data = self._find_recipe_json_ld()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict):
                        # HowToStep с text полем
                        if 'text' in step:
                            instructions_text.append(self.clean_text(step['text']))
                        elif 'itemListElement' in step:
                            # HowToSection с подшагами
                            for substep in step['itemListElement']:
                                if isinstance(substep, dict) and 'text' in substep:
                                    instructions_text.append(self.clean_text(substep['text']))
                    elif isinstance(step, str):
                        instructions_text.append(self.clean_text(step))
            elif isinstance(instructions, str):
                instructions_text.append(self.clean_text(instructions))
        
        # Если JSON-LD не помог, пробуем из HTML
        if not instructions_text:
            instructions_section = self.soup.find(class_='mv-create-instructions')
            
            if instructions_section:
                # Извлекаем элементы списка
                items = instructions_section.find_all('li')
                
                for item in items:
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    
                    if step_text:
                        instructions_text.append(step_text)
        
        if instructions_text:
            # Соединяем шаги с нумерацией
            numbered_steps = [f"{i+1}) {step}" for i, step in enumerate(instructions_text)]
            return ' '.join(numbered_steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Из JSON-LD
        recipe_data = self._find_recipe_json_ld()
        if recipe_data:
            # Пробуем recipeCategory
            if 'recipeCategory' in recipe_data:
                category = recipe_data['recipeCategory']
                if isinstance(category, list):
                    return self.clean_text(', '.join(category))
                elif isinstance(category, str):
                    return self.clean_text(category)
            
            # Пробуем recipeCuisine как альтернативу
            if 'recipeCuisine' in recipe_data:
                cuisine = recipe_data['recipeCuisine']
                if isinstance(cuisine, str):
                    return self.clean_text(cuisine)
        
        # Из мета-тега article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Из JSON-LD
        recipe_data = self._find_recipe_json_ld()
        if recipe_data:
            # Маппинг типов времени на ключи JSON-LD
            time_keys = {
                'prep': ['prepTime', 'performTime'],  # performTime используется как альтернатива prepTime
                'cook': ['cookTime'],
                'total': ['totalTime']
            }
            
            keys = time_keys.get(time_type, [])
            for key in keys:
                if key in recipe_data:
                    iso_time = recipe_data[key]
                    return self.parse_iso_duration(iso_time)
        
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
        # Ищем секцию с заметками в HTML
        notes_section = self.soup.find(class_='mv-create-notes')
        
        if notes_section:
            # Извлекаем текст, пропуская заголовки
            paragraphs = notes_section.find_all('p')
            notes_texts = []
            
            for p in paragraphs:
                text = self.clean_text(p.get_text())
                if text:
                    notes_texts.append(text)
            
            if notes_texts:
                return ' '.join(notes_texts)
            
            # Если нет параграфов, берем весь текст
            text = self.clean_text(notes_section.get_text(separator=' ', strip=True))
            # Убираем заголовок "Notes:" если есть
            text = re.sub(r'^Notes?\s*:?\s*', '', text, flags=re.IGNORECASE)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Из JSON-LD
        recipe_data = self._find_recipe_json_ld()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            
            if isinstance(keywords, str):
                # Если строка, разбиваем по запятой
                tags = [tag.strip().lower() for tag in keywords.split(',') if tag.strip()]
                return ', '.join(tags) if tags else None
            elif isinstance(keywords, list):
                # Если список, объединяем
                tags = [str(tag).strip().lower() for tag in keywords if tag]
                return ', '.join(tags) if tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Из meta тегов
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content') and twitter_image['content'] not in urls:
            urls.append(twitter_image['content'])
        
        # 2. Из JSON-LD
        recipe_data = self._find_recipe_json_ld()
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            
            if isinstance(img, str):
                if img not in urls:
                    urls.append(img)
            elif isinstance(img, list):
                for image in img:
                    if isinstance(image, str) and image not in urls:
                        urls.append(image)
                    elif isinstance(image, dict):
                        if 'url' in image and image['url'] not in urls:
                            urls.append(image['url'])
                        elif 'contentUrl' in image and image['contentUrl'] not in urls:
                            urls.append(image['contentUrl'])
            elif isinstance(img, dict):
                if 'url' in img and img['url'] not in urls:
                    urls.append(img['url'])
                elif 'contentUrl' in img and img['contentUrl'] not in urls:
                    urls.append(img['contentUrl'])
        
        # Возвращаем как строку через запятую без пробелов
        return ','.join(urls) if urls else None
    
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
    """Точка входа для обработки HTML файлов"""
    import os
    
    # Директория с примерами HTML для bytheforkful.com
    preprocessed_dir = os.path.join("preprocessed", "bytheforkful_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка файлов из {preprocessed_dir}")
        process_directory(ByTheForkfulExtractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python bytheforkful_com.py")


if __name__ == "__main__":
    main()
