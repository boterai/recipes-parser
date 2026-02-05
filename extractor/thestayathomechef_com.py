"""
Экстрактор данных рецептов для сайта thestayathomechef.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TheStayAtHomeChefExtractor(BaseRecipeExtractor):
    """Экстрактор для thestayathomechef.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в читаемом формате, например "1 hour 30 minutes"
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
        
        # Конвертируем в читаемый формат с учетом часов и минут
        total_minutes = hours * 60 + minutes
        
        if total_minutes == 0:
            return None
        
        # Если меньше 60 минут, возвращаем только минуты
        if total_minutes < 60:
            return f"{total_minutes} minute" + ("s" if total_minutes != 1 else "")
        
        # Если кратно 60, возвращаем только часы
        if total_minutes % 60 == 0:
            hrs = total_minutes // 60
            return f"{hrs} hour" + ("s" if hrs != 1 else "")
        
        # Иначе возвращаем часы и минуты
        hrs = total_minutes // 60
        mins = total_minutes % 60
        return f"{hrs} hour" + ("s" if hrs != 1 else "") + f" {mins} minute" + ("s" if mins != 1 else "")
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            return item
                
                # Проверяем прямой Recipe
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
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Ищем в заголовке
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
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
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Сначала пробуем JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeIngredient' in recipe_data:
            for ingredient_text in recipe_data['recipeIngredient']:
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
            ingredient_text: Строка вида "1 cup all-purpose flour" или "2 pounds chicken"
            
        Returns:
            dict: {"name": "flour", "amount": "1", "units": "cup"} или None
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
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1 cup flour", "2 tablespoons butter", "1/2 teaspoon salt"
        # Используем \b для границ слов, чтобы не захватывать часть слова
        pattern = r'^([\d\s/.,]+)?\s*(\(?\d*\s*(?:ounce|oz|pound|lb|gram|g|kilogram|kg)\s*(?:can|cans|package|packages)?\)?|cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads|large|medium|small)\b\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
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
        # Убираем скобки из единиц (например "(28 ounce can)" -> "28 ounce can")
        if unit:
            unit = unit.strip('()')
        
        # Очистка названия
        # Удаляем скобки с содержимым в конце
        name = re.sub(r'\([^)]*\)\s*$', '', name)
        # Удаляем скобки в начале
        name = re.sub(r'^\s*\(?\)?\s*', '', name)
        # Удаляем фразы "to taste", "as needed", "optional" и т.д.
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|or to taste)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        # Сначала пробуем JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        if step_text:
                            steps.append(step_text)
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        if step_text:
                            steps.append(step_text)
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data:
            # Проверяем recipeCategory
            if 'recipeCategory' in recipe_data:
                category = recipe_data['recipeCategory']
                if isinstance(category, list):
                    return self.clean_text(category[0]) if category else None
                return self.clean_text(category)
            
            # Проверяем recipeCuisine
            if 'recipeCuisine' in recipe_data:
                cuisine = recipe_data['recipeCuisine']
                if isinstance(cuisine, list):
                    return self.clean_text(cuisine[0]) if cuisine else None
                return self.clean_text(cuisine)
        
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'prepTime' in recipe_data:
            iso_time = recipe_data['prepTime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'cookTime' in recipe_data:
            iso_time = recipe_data['cookTime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'totalTime' in recipe_data:
            iso_time = recipe_data['totalTime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок к рецепту"""
        # Ищем секцию с заметками в HTML
        # Обычно это div с классом wprm-recipe-notes
        notes_section = self.soup.find('div', class_='wprm-recipe-notes')
        
        if notes_section:
            # Собираем текст из всех элементов списка или параграфов
            notes = []
            
            # Ищем список
            ul = notes_section.find('ul')
            if ul:
                for li in ul.find_all('li'):
                    text = self.clean_text(li.get_text())
                    if text:
                        notes.append(text)
            else:
                # Если нет списка, берем весь текст
                text = self.clean_text(notes_section.get_text(separator=' '))
                if text:
                    notes.append(text)
            
            return ' '.join(notes) if notes else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Сначала пробуем JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data:
            # Проверяем keywords (может быть строкой через запятую или списком)
            if 'keywords' in recipe_data:
                keywords = recipe_data['keywords']
                if isinstance(keywords, str):
                    # Разбиваем по запятой
                    tags_list.extend([tag.strip() for tag in keywords.split(',') if tag.strip()])
                elif isinstance(keywords, list):
                    tags_list.extend([tag.strip() for tag in keywords if tag.strip()])
            
            # Добавляем recipeCategory если еще нет тегов
            if 'recipeCategory' in recipe_data:
                category = recipe_data['recipeCategory']
                if isinstance(category, list):
                    tags_list.extend(category)
                elif category:
                    tags_list.append(category)
            
            # Добавляем recipeCuisine
            if 'recipeCuisine' in recipe_data:
                cuisine = recipe_data['recipeCuisine']
                if isinstance(cuisine, list):
                    tags_list.extend(cuisine)
                elif cuisine:
                    tags_list.append(cuisine)
        
        # Очищаем и форматируем теги
        if tags_list:
            # Убираем пустые и дублирующиеся теги
            cleaned_tags = []
            seen = set()
            for tag in tags_list:
                tag = self.clean_text(tag)
                if tag:
                    tag_lower = tag.lower()
                    if tag_lower not in seen:
                        seen.add(tag_lower)
                        cleaned_tags.append(tag)
            
            return ', '.join(cleaned_tags) if cleaned_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Сначала пробуем JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'image' in recipe_data:
            images = recipe_data['image']
            
            if isinstance(images, str):
                urls.append(images)
            elif isinstance(images, list):
                for img in images:
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, dict):
                        if 'url' in img:
                            urls.append(img['url'])
                        elif 'contentUrl' in img:
                            urls.append(img['contentUrl'])
            elif isinstance(images, dict):
                if 'url' in images:
                    urls.append(images['url'])
                elif 'contentUrl' in images:
                    urls.append(images['contentUrl'])
        
        # Если нет в JSON-LD, пробуем meta теги
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Обработка директории с HTML файлами"""
    import os
    
    # Путь к директории с примерами
    recipes_dir = os.path.join("preprocessed", "thestayathomechef_com")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(TheStayAtHomeChefExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python thestayathomechef_com.py")


if __name__ == "__main__":
    main()
