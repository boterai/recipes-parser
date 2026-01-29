"""
Экстрактор данных рецептов для сайта minimalistbaker.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MinimalistBakerExtractor(BaseRecipeExtractor):
    """Экстрактор для minimalistbaker.com"""
    
    # Единицы измерения для парсинга ингредиентов
    INGREDIENT_UNITS = (
        r'cups?|tablespoons?|teaspoons?|tbsp|tsp|pounds?|ounces?|lbs?|oz|'
        r'grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|'
        r'pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|'
        r'inch(?:es)?|slices?|cloves?|bunches?|sprigs?|'
        r'whole|halves?|quarters?|pieces?|heads?|package|can|jar|bottle'
    )
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT6H15M" или "PT375M"
            
        Returns:
            Время в формате "20 minutes" или "1 hour 30 minutes" или "6 hours 15 minutes"
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
        
        # Если минут >= 60, конвертируем в часы и минуты
        if minutes >= 60:
            hours += minutes // 60
            minutes = minutes % 60
        
        # Формируем строку
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение данных Recipe из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            if not script.string:
                continue
                
            try:
                data = json.loads(script.string)
                
                # Проверяем наличие @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            return item
                
                # Проверяем, если Recipe на верхнем уровне
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                
                # Проверяем, если это список
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                            
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'name' in recipe_data:
            name = recipe_data['name']
            # Убираем суффиксы типа " (Vegan + GF)"
            name = re.sub(r'\s*\([^)]+\)\s*$', '', name)
            return self.clean_text(name)
        
        # Альтернативно - из заголовка страницы
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            # Берем только до первой точки, восклицательного или вопросительного знака (первое предложение)
            match = re.search(r'^([^.!?]+[.!?])', desc)
            if match:
                desc = match.group(1)
            return self.clean_text(desc)
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Dict[str, Optional[str]]]:
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
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на обычные
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5'
        }
        
        for fraction, replacement in fraction_map.items():
            text = text.replace(fraction, replacement)
        
        # Удаляем примечания в скобках
        text = re.sub(r'\s*\([^)]*\)', '', text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1 cup flour", "2 tablespoons butter", "1/2 teaspoon salt"
        pattern = rf'^([\d\s/.,\u2013\-]+)?\s*({self.INGREDIENT_UNITS})?\s*(.+)'
        
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
            # Очищаем от дефисов и en-dash (диапазоны) - берем первое значение
            amount_str = re.split(r'[\u2013\-]', amount_str)[0].strip()
            amount = amount_str
        
        # Обработка единицы измерения
        if unit:
            unit = unit.strip()
        
        # Очистка названия
        name = name.strip()
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|divided|plus more)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние запятые, звездочки, скобки и пробелы
        name = re.sub(r'[,;*]+$', '', name)
        name = re.sub(r'\*+\)', '', name)  # Удаляем *) в конце
        name = re.sub(r'\)+$', '', name)  # Удаляем ) в конце
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredients_list = []
            for ing_text in recipe_data['recipeIngredient']:
                parsed = self.parse_ingredient(ing_text)
                if parsed:
                    # Меняем "unit" на "units" для совместимости с ожидаемым форматом
                    ingredients_list.append({
                        "name": parsed["name"],
                        "amount": parsed["amount"],
                        "units": parsed["unit"]
                    })
            
            return json.dumps(ingredients_list, ensure_ascii=False) if ingredients_list else None
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        text = self.clean_text(step['text'])
                        # Удаляем префиксы типа "CAKE: " или "TOPPING: " или "For the cake:"
                        text = re.sub(r'^[A-Za-z\s]+:\s*', '', text)
                        steps.append(text)
                    elif isinstance(step, str):
                        text = self.clean_text(step)
                        text = re.sub(r'^[A-Za-z\s]+:\s*', '', text)
                        steps.append(text)
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            if isinstance(category, list):
                return ', '.join(category)
            return str(category)
        
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
        # Ищем секцию с примечаниями в HTML
        # Minimalist Baker использует wprm-recipe-notes-container
        
        # Ищем div с классом recipe-notes или похожим
        notes_div = self.soup.find('div', class_=re.compile(r'recipe.*notes', re.I))
        if notes_div:
            # Ищем вложенный div с текстом заметок
            content_div = notes_div.find('div', class_=re.compile(r'text', re.I))
            if content_div:
                text = content_div.get_text(separator=' ', strip=True)
            else:
                # Получаем весь текст, пропуская заголовок
                text = notes_div.get_text(separator=' ', strip=True)
                # Удаляем заголовок "Notes"
                text = re.sub(r'^Notes\s*', '', text, flags=re.IGNORECASE)
            
            # Разбиваем по звездочкам (bullet points)
            notes_items = [item.strip() for item in text.split('*') if item.strip() and len(item.strip()) > 10]
            # Берем первый пункт (как в эталонном JSON)
            if notes_items:
                text = notes_items[0]
                text = self.clean_text(text)
                if text and len(text) > 10:
                    return text
        
        # Пробуем найти в различных вариантах
        notes_patterns = [
            r'recipe\s*notes?',
            r'notes?',
            r'tips?',
            r'cook\'?s?\s*notes?'
        ]
        
        for pattern in notes_patterns:
            # Ищем заголовок с примечаниями
            heading = self.soup.find(['h2', 'h3', 'h4', 'strong', 'b'], 
                                     string=re.compile(pattern, re.IGNORECASE))
            
            if heading:
                # Получаем следующий элемент после заголовка
                next_elem = heading.find_next(['p', 'div', 'ul', 'ol'])
                if next_elem:
                    text = next_elem.get_text(separator=' ', strip=True)
                    text = self.clean_text(text)
                    # Удаляем ведущие звездочки
                    text = re.sub(r'^\*+\s*', '', text)
                    if text and len(text) > 10:
                        # Берем только до первой звездочки (первый пункт)
                        text = text.split('*')[0].strip()
                        return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Разделяем по запятой и очищаем
                tags = [tag.strip().lower() for tag in keywords.split(',') if tag.strip()]
                return ', '.join(tags) if tags else None
            elif isinstance(keywords, list):
                tags = [str(tag).strip().lower() for tag in keywords if tag]
                return ', '.join(tags) if tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'image' in recipe_data:
            image = recipe_data['image']
            
            if isinstance(image, str):
                urls.append(image)
            elif isinstance(image, list):
                for img in image:
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, dict):
                        if 'url' in img:
                            urls.append(img['url'])
                        elif 'contentUrl' in img:
                            urls.append(img['contentUrl'])
            elif isinstance(image, dict):
                if 'url' in image:
                    urls.append(image['url'])
                elif 'contentUrl' in image:
                    urls.append(image['contentUrl'])
        
        # Дополнительно - из meta тегов
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
    """
    Точка входа для обработки HTML файлов minimalistbaker.com
    
    Ищет директорию preprocessed/minimalistbaker_com и обрабатывает все HTML файлы в ней,
    извлекая данные рецептов и сохраняя их в JSON формате.
    """
    import os
    
    # Обрабатываем папку preprocessed/minimalistbaker_com
    recipes_dir = os.path.join("preprocessed", "minimalistbaker_com")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(MinimalistBakerExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python minimalistbaker_com.py")


if __name__ == "__main__":
    main()
