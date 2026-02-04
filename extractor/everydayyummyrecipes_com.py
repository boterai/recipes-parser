"""
Экстрактор данных рецептов для сайта everydayyummyrecipes.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class EverydayYummyRecipesExtractor(BaseRecipeExtractor):
    """Экстрактор для everydayyummyrecipes.com"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных из JSON-LD структурированных данных"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Функция для проверки типа Recipe
                def is_recipe(item):
                    if not isinstance(item, dict):
                        return False
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        return 'Recipe' in item_type
                    return item_type == 'Recipe'
                
                # Ищем Recipe в данных
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            return item
                elif isinstance(data, dict):
                    if is_recipe(data):
                        return data
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if is_recipe(item):
                                return item
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "20 minutes" или "1 hour 30 minutes" или "1 hour 1 minute"
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
        
        # Форматируем в читаемый вид
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour" + ("" if hours == 1 else "s"))
        if minutes > 0:
            parts.append(f"{minutes} minute" + ("" if minutes == 1 else "s"))
        
        return " ".join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self._get_json_ld_data()
        
        if recipe_data and 'name' in recipe_data:
            name = self.clean_text(recipe_data['name'])
            # Убираем распространенные суффиксы из названия
            # Убираем всё после тире/двоеточия, если там есть дополнительные слова
            name = re.sub(r'\s*[–—:-]\s*(Recipe|Easy|Quick|Simple|Perfect|Best|Homemade|Ready|The|A).*$', '', name, flags=re.IGNORECASE)
            # Убираем слово "Recipe" в конце
            name = re.sub(r'\s+Recipe\s*$', '', name, flags=re.IGNORECASE)
            return name
        
        # Fallback: ищем в HTML
        recipe_name = self.soup.find('h2', class_='wprm-recipe-name')
        if recipe_name:
            name = self.clean_text(recipe_name.get_text())
            name = re.sub(r'\s*[–—:-]\s*(Recipe|Easy|Quick|Simple|Perfect|Best|Homemade|Ready|The|A).*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\s+Recipe\s*$', '', name, flags=re.IGNORECASE)
            return name
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self._get_json_ld_data()
        
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Fallback: meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup unsalted butter, cold" or "1 ¼  cups   (175g) all-purpose flour ((or gluten-free))"
            
        Returns:
            dict: {"name": "unsalted butter", "amount": "1", "units": "cup"}
        """
        if not ingredient_text:
            return None
        
        # Удаляем все в скобках (включая вложенные) ПЕРЕД очисткой
        # Многократно применяем regex пока есть что удалять
        text = ingredient_text
        while '(' in text:
            new_text = re.sub(r'\([^()]*\)', '', text)
            if new_text == text:  # Если ничего не изменилось, выходим
                break
            text = new_text
        
        # Чистим текст
        text = self.clean_text(text)
        
        # Заменяем Unicode дроби на их дробное представление для парсинга
        fraction_map = {
            '½': ' 1/2', '¼': ' 1/4', '¾': ' 3/4',
            '⅓': ' 1/3', '⅔': ' 2/3', '⅛': ' 1/8',
            '⅜': ' 3/8', '⅝': ' 5/8', '⅞': ' 7/8',
            '⅕': ' 1/5', '⅖': ' 2/5', '⅗': ' 3/5', '⅘': ' 4/5',
            '⅙': ' 1/6', '⅚': ' 5/6'
        }
        
        for fraction, replacement in fraction_map.items():
            text = text.replace(fraction, replacement)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1 cup flour", "2 tablespoons butter", "1 1/2 teaspoon salt"
        pattern = r'^([\d\s/.,]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|lb|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads|large|medium|small)?\s*(.+)'
        
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
                # Форматируем: целое число без .0, дробное - как есть
                amount = str(total) if total != int(total) else str(int(total))
            else:
                # Простое число
                amount_float = float(amount_str.replace(',', '.'))
                amount = str(amount_float) if amount_float != int(amount_float) else str(int(amount_float))
        
        # Обработка единицы измерения
        if unit:
            # Нормализация единиц измерения
            unit = unit.strip().lower()
            unit_map = {
                'tablespoon': 'tbsp',
                'tablespoons': 'tbsp',
                'teaspoon': 'tsp',
                'teaspoons': 'tsp',
                'pound': 'lb',
                'pounds': 'lb',
                'ounce': 'oz',
                'ounces': 'oz',
                'gram': 'g',
                'grams': 'g',
                'kilogram': 'kg',
                'kilograms': 'kg',
                'milliliter': 'ml',
                'milliliters': 'ml',
                'liter': 'l',
                'liters': 'l',
            }
            
            # Сохраняем plural для cups, inches и т.д.
            if unit not in unit_map:
                # Не меняем cups, inches, slices и т.д.
                pass
            else:
                unit = unit_map[unit]
            
            # Special case: если unit is "large", "medium", "small" - это часть названия
            if unit in ['large', 'medium', 'small']:
                name = unit + ' ' + name
                unit = None
        
        # Очистка названия
        # Удаляем фразы "to taste", "as needed", "optional", etc.
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|chopped|diced|minced|sliced|peeled|divided|cold|softened|room temperature)\b', '', name, flags=re.IGNORECASE)
        # Удаляем дополнительные описания после запятой
        name = re.sub(r',.*$', '', name)
        # Удаляем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit  # Используем "units" как в примерах JSON
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        recipe_data = self._get_json_ld_data()
        
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredients_list = recipe_data['recipeIngredient']
            parsed_ingredients = []
            
            for ingredient_text in ingredients_list:
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    parsed_ingredients.append(parsed)
            
            return json.dumps(parsed_ingredients, ensure_ascii=False) if parsed_ingredients else None
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self._get_json_ld_data()
        
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                for item in instructions:
                    if isinstance(item, dict):
                        # HowToSection format
                        if item.get('@type') == 'HowToSection':
                            if 'itemListElement' in item:
                                for step in item['itemListElement']:
                                    if isinstance(step, dict) and 'text' in step:
                                        steps.append(self.clean_text(step['text']))
                        # HowToStep format
                        elif item.get('@type') == 'HowToStep':
                            if 'text' in item:
                                steps.append(self.clean_text(item['text']))
                        # Simple dict with text
                        elif 'text' in item:
                            steps.append(self.clean_text(item['text']))
                    elif isinstance(item, str):
                        steps.append(self.clean_text(item))
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            
            # Add numbering to steps
            if steps:
                numbered_steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
                return ' '.join(numbered_steps)
            
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self._get_json_ld_data()
        
        # Проверяем recipeCategory в JSON-LD
        if recipe_data:
            if 'recipeCategory' in recipe_data:
                category = recipe_data['recipeCategory']
                if isinstance(category, list):
                    return self.clean_text(', '.join(category))
                return self.clean_text(category)
        
        # Fallback: meta article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_json_ld_data()
        
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        recipe_data = self._get_json_ld_data()
        
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_json_ld_data()
        
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями в HTML
        # WP Recipe Maker может использовать различные классы для заметок
        notes_candidates = [
            self.soup.find('div', class_=re.compile(r'wprm.*note', re.I)),
            self.soup.find('div', class_=re.compile(r'recipe.*note', re.I)),
        ]
        
        for notes_section in notes_candidates:
            if notes_section:
                text = notes_section.get_text(separator=' ', strip=True)
                # Убираем заголовки типа "Notes:", "Chef's Note:", etc.
                text = re.sub(r'^(Notes?|Tips?|Chef\'?s\s+Notes?)\s*:?\s*', '', text, flags=re.I)
                text = self.clean_text(text)
                return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        recipe_data = self._get_json_ld_data()
        
        # Проверяем keywords в JSON-LD
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Уже строка с тегами, разделёнными запятыми
                return self.clean_text(keywords)
            elif isinstance(keywords, list):
                # Список тегов - соединяем через запятую
                return ', '.join([self.clean_text(tag) for tag in keywords if tag])
        
        # Fallback: meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        recipe_data = self._get_json_ld_data()
        
        # Извлекаем из JSON-LD
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
        
        # Fallback: og:image
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
    """Обработка HTML файлов из директории preprocessed/everydayyummyrecipes_com"""
    preprocessed_dir = Path(__file__).parent.parent / "preprocessed" / "everydayyummyrecipes_com"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        process_directory(EverydayYummyRecipesExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Убедитесь, что директория preprocessed/everydayyummyrecipes_com существует")


if __name__ == "__main__":
    main()
