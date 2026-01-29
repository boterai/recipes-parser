"""
Экстрактор данных рецептов для сайта forktospoon.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ForkToSpoonExtractor(BaseRecipeExtractor):
    """Экстрактор для forktospoon.com"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """
        Извлечение данных из JSON-LD (@graph)
        
        Returns:
            Словарь с полным @graph или None
        """
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Если есть @graph, возвращаем весь объект
                if isinstance(data, dict) and '@graph' in data:
                    return data
                    
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def _get_recipe_data(self) -> Optional[dict]:
        """
        Извлечение данных Recipe из JSON-LD
        
        Returns:
            Словарь с данными рецепта или None
        """
        data = self._get_json_ld_data()
        if not data or '@graph' not in data:
            return None
        
        # Функция для проверки типа Recipe
        def is_recipe(item):
            item_type = item.get('@type', '')
            if isinstance(item_type, list):
                return 'Recipe' in item_type
            return item_type == 'Recipe'
        
        # Ищем Recipe в @graph
        for item in data['@graph']:
            if is_recipe(item):
                return item
        
        return None
    
    def _get_article_data(self) -> Optional[dict]:
        """
        Извлечение данных Article из JSON-LD
        
        Returns:
            Словарь с данными статьи или None
        """
        data = self._get_json_ld_data()
        if not data or '@graph' not in data:
            return None
        
        # Ищем Article в @graph
        for item in data['@graph']:
            if item.get('@type') == 'Article':
                return item
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "X minutes"
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
        recipe_data = self._get_recipe_data()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self._get_recipe_data()
        if recipe_data and 'description' in recipe_data:
            desc = self.clean_text(recipe_data['description'])
            # Remove prefix like "Recipe Name -- " if present
            desc = re.sub(r'^.+?\s*--\s*', '', desc)
            return desc
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', property='og:description')
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            desc = re.sub(r'^.+?\s*--\s*', '', desc)
            return desc
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "3 tablespoons butter (melted)"
            
        Returns:
            dict: {"name": "butter", "amount": "3", "unit": "tablespoons"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "3 tablespoons butter", "2 cups flour", "1/2 teaspoon salt"
        # Important: Match whole words only to avoid "large" matching as "l" (liters)
        pattern = r'^([\d\s/.,]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|ounce|grams?|kilograms?|kg|milliliters?|liters?|ml|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|inch|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|piece|head|heads|small|medium|large|crust)\s+(.+)'
        
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
                        try:
                            total += float(num) / float(denom)
                        except (ValueError, ZeroDivisionError):
                            pass
                    else:
                        try:
                            total += float(part)
                        except ValueError:
                            pass
                if total > 0:
                    # Format as fraction if it's a simple fraction
                    if amount_str.count('/') == 1 and ' ' not in amount_str:
                        amount = amount_str  # Keep as fraction string
                    elif total == int(total):
                        amount = int(total)  # Convert to int if whole number
                    else:
                        amount = str(total)
            else:
                # Try to convert to number
                try:
                    num_val = float(amount_str.replace(',', '.'))
                    # Use int if it's a whole number, otherwise keep as string
                    amount = int(num_val) if num_val == int(num_val) else amount_str
                except ValueError:
                    amount = amount_str
        
        # Обработка единицы измерения (используем units вместо unit для соответствия эталону)
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|melted|chopped|diced|minced|packed|shredded)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit  # Using "units" to match reference format
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        recipe_data = self._get_recipe_data()
        
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredients = []
            for ingredient_text in recipe_data['recipeIngredient']:
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
            
            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        recipe_data = self._get_recipe_data()
        
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        steps.append(step['text'])
                    elif isinstance(step, str):
                        steps.append(step)
            elif isinstance(instructions, str):
                steps.append(instructions)
            
            if steps:
                # Join all steps into a single string with spaces
                return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self._get_recipe_data()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            if isinstance(category, list):
                return category[0] if category else None
            return category
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_recipe_data()
        
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self._get_recipe_data()
        
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_recipe_data()
        
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # В forktospoon.com заметки находятся в секциях "Pro Tips", "Notes", "Pro Tips/Notes"
        # Извлекаем содержимое из списков (ul/ol) после этих заголовков
        
        notes = []
        
        # Ищем заголовки h2 с ключевыми словами
        h2_tags = self.soup.find_all('h2', class_='wp-block-heading')
        
        for h2 in h2_tags:
            heading_text = h2.get_text().strip().lower()
            
            # Проверяем заголовки - приоритет: "Pro Tips" или "Notes"
            if 'pro tip' in heading_text or ('note' in heading_text and 'tip' in heading_text):
                # Ищем следующий список (ul/ol), пропуская параграфы-введения
                next_elem = h2.find_next_sibling()
                while next_elem:
                    if next_elem.name in ['ul', 'ol']:
                        # Нашли список, извлекаем из него
                        for li in next_elem.find_all('li'):
                            text = self.clean_text(li.get_text())
                            if text:
                                notes.append(text)
                        if notes:
                            return ' '.join(notes)
                    elif next_elem.name in ['h1', 'h2', 'h3']:
                        # Дошли до следующего заголовка
                        break
                    next_elem = next_elem.find_next_sibling()
        
        # Если не нашли Pro Tips, ищем FAQ
        for h2 in h2_tags:
            heading_text = h2.get_text().strip().lower()
            if 'faq' in heading_text:
                # Для FAQ берем только ответы (параграфы, не вопросы)
                next_elem = h2.find_next_sibling()
                count = 0
                while next_elem and next_elem.name == 'p' and count < 10:
                    text = self.clean_text(next_elem.get_text())
                    # Берем только ответы (не вопросы, которые обычно заканчиваются на "?")
                    if text and not text.endswith('?'):
                        notes.append(text)
                        count += 1
                    next_elem = next_elem.find_next_sibling()
                    if next_elem and next_elem.name in ['h1', 'h2', 'h3']:
                        break
                
                if notes:
                    return ' '.join(notes)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Теги берем из Article keywords в JSON-LD
        article_data = self._get_article_data()
        
        if article_data and 'keywords' in article_data:
            keywords = article_data['keywords']
            if isinstance(keywords, list):
                # Объединяем список в строку через ", "
                tags = ', '.join(str(k).lower() for k in keywords)
                return tags
            elif isinstance(keywords, str):
                return keywords.lower()
        
        # Альтернативно - из Recipe keywords
        recipe_data = self._get_recipe_data()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                return keywords.lower()
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        recipe_data = self._get_recipe_data()
        
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
        
        # Также ищем в og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)
        
        if urls:
            # Убираем дубликаты, сохраняя порядок
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            # Возвращаем как строку через запятую без пробелов
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
    import os
    # Обрабатываем папку preprocessed/forktospoon_com
    preprocessed_dir = os.path.join("preprocessed", "forktospoon_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ForkToSpoonExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python forktospoon_com.py")


if __name__ == "__main__":
    main()
