"""
Экстрактор данных рецептов для сайта travelshelper.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TravelshelperExtractor(BaseRecipeExtractor):
    """Экстрактор для travelshelper.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в формат "X minutes"
        
        Args:
            duration: строка вида "PT10M" или "PT1H10M"
            
        Returns:
            Время в формате "10 minutes" или "70 minutes"
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
        
        # Конвертируем всё в минуты
        total_minutes = hours * 60 + minutes
        
        if total_minutes > 0:
            return f"{total_minutes} minutes"
        
        return None
    
    def get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение Recipe данных из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Если есть @graph, ищем в нём
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                
                # Если Recipe напрямую
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                
                # Если список, ищем Recipe в нём
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                            
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Из тега title
        title_tag = self.soup.find('title')
        if title_tag:
            return self.clean_text(title_tag.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        recipe_data = self.get_recipe_json_ld()
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
    
    def extract_ingredients(self) -> Optional[List[Dict[str, any]]]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Сначала пробуем из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredient_list = recipe_data['recipeIngredient']
            
            for ingredient_text in ingredient_list:
                if isinstance(ingredient_text, str):
                    # Парсим строку ингредиента
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return ingredients if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Dict[str, any]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "2 pounds potatoes" или "½ cup olive oil"
            
        Returns:
            dict: {"name": "potatoes", "amount": "2", "unit": "pounds"} или None
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
        # Примеры: "2 pounds potatoes", "½ cup olive oil", "3-4 cloves garlic"
        # Улучшенный паттерн чтобы не захватывать одну букву как единицу
        pattern = r'^([\d\s/.,\-–—]+)?\s*(pounds?|cups?|tablespoons?|teaspoons?|tbsps?|tsps?|lbs?|oz|ounces?|grams?|kilograms?|kg|milliliters?|liters?|ml|pinch(?:es)?|dash(?:es)?|cloves?|bunches?|sprigs?|pieces?|slices?|whole|halves?|quarters?|inch(?:es)?|servings?|packages?|cans?|jars?|bottles?|head(?:s)?)\s+(.+)'
        
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
            # Убираем диапазоны (2-3 -> 2.5)
            if '–' in amount_str or '—' in amount_str or '-' in amount_str:
                # Берём первое число из диапазона
                amount_str = re.split(r'[-–—]', amount_str)[0].strip()
            
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
        # Удаляем скобки с содержимым (дополнительные пояснения)
        name = re.sub(r'\([^)]*\)', '', name)
        name = re.sub(r'\[[^\]]*\]', '', name)
        # Удаляем всё после точки с запятой (обычно дополнительные пояснения)
        if ';' in name:
            name = name.split(';')[0]
        # Удаляем всё после точки (обычно дополнительные пояснения)
        name = re.sub(r'\..*$', '', name)
        # Удаляем всё после запятой и тире (описания)
        if ',' in name:
            name = name.split(',')[0]
        # Удаляем фразы "optional", "to taste", etc
        name = re.sub(r'\b(optional|to taste|as needed|or more|if needed|for garnish|about)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        steps = []
        
        # Сначала пробуем из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict):
                        # HowToStep
                        if 'text' in step:
                            step_text = self.clean_text(step['text'])
                            if step_text:
                                steps.append(f"{idx}. {step_text}")
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        if step_text:
                            steps.append(f"{idx}. {step_text}")
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Сначала пробуем из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data:
            # recipeCategory может быть списком или строкой
            if 'recipeCategory' in recipe_data:
                category = recipe_data['recipeCategory']
                if isinstance(category, list) and len(category) > 0:
                    return self.clean_text(category[0])
                elif isinstance(category, str):
                    return self.clean_text(category)
            
            # Альтернативно - recipeCuisine
            if 'recipeCuisine' in recipe_data:
                cuisine = recipe_data['recipeCuisine']
                if isinstance(cuisine, list) and len(cuisine) > 0:
                    return self.clean_text(cuisine[0])
                elif isinstance(cuisine, str):
                    return self.clean_text(cuisine)
        
        # Из meta article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем в HTML секцию с заметками
        # Обычно это может быть в конце рецепта или в специальном блоке
        
        # Ищем элементы с классами содержащими "note" или "tip"
        notes_elem = self.soup.find(class_=re.compile(r'(note|tip|hint)', re.I))
        if notes_elem:
            text = notes_elem.get_text(separator=' ', strip=True)
            return self.clean_text(text) if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Сначала пробуем из JSON-LD keywords
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, list):
                tags = [self.clean_text(kw) for kw in keywords if kw]
            elif isinstance(keywords, str):
                # Разделяем по запятой
                tags = [self.clean_text(kw.strip()) for kw in keywords.split(',') if kw.strip()]
        
        # Если не нашли, ищем в meta keywords
        if not tags:
            meta_keywords = self.soup.find('meta', {'name': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                keywords_str = meta_keywords['content']
                tags = [self.clean_text(kw.strip()) for kw in keywords_str.split(',') if kw.strip()]
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Сначала пробуем из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
        # Если не нашли в JSON-LD, ищем в meta тегах
        if not urls:
            # og:image
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
            
            # twitter:image
            twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
            if twitter_image and twitter_image.get('content'):
                urls.append(twitter_image['content'])
        
        # Убираем дубликаты
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
        # Извлекаем ингредиенты как список словарей
        ingredients = self.extract_ingredients()
        
        # Конвертируем в JSON строку, если есть данные
        ingredients_json = None
        if ingredients:
            ingredients_json = json.dumps(ingredients, ensure_ascii=False)
        
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": ingredients_json,
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
    import os
    
    # Ищем директорию с HTML-файлами
    preprocessed_dir = os.path.join("preprocessed", "travelshelper_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(TravelshelperExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python travelshelper_com.py")


if __name__ == "__main__":
    main()
