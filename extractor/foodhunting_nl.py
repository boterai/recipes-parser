"""
Экстрактор данных рецептов для сайта foodhunting.nl
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class FoodhuntingNlExtractor(BaseRecipeExtractor):
    """Экстрактор для foodhunting.nl"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT100M"
            
        Returns:
            Время в формате "X hour(s) Y minutes" или "X minutes"
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
        
        # Если только минуты больше 60, конвертируем в часы и минуты
        if hours == 0 and minutes >= 60:
            hours = minutes // 60
            minutes = minutes % 60
        
        # Форматируем результат
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
        if minutes > 0:
            parts.append(f"{minutes} minutes")
        
        return " ".join(parts) if parts else None
    
    def get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение Recipe данных из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в @graph
                if '@graph' in data and isinstance(data['@graph'], list):
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            return item
                
                # Или напрямую Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из HTML h1
        recipe_header = self.soup.find('h1')
        if recipe_header:
            return self.clean_text(recipe_header.get_text())
        
        # Пробуем из WPRM recipe name (для print-версий)
        wprm_name = self.soup.find(class_='wprm-recipe-name')
        if wprm_name:
            return self.clean_text(wprm_name.get_text())
        
        # Последний вариант - из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            title_text = self.clean_text(title_tag.get_text())
            # Убираем суффикс сайта из title
            if ' - ' in title_text:
                title_text = title_text.split(' - ')[0].strip()
            return title_text
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Альтернативно из meta тегов
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из WPRM структуры"""
        ingredients = []
        
        # Ищем ингредиенты в WPRM структуре (приоритет, т.к. структурированные данные)
        ingredient_items = self.soup.find_all('li', class_='wprm-recipe-ingredient')
        
        for item in ingredient_items:
            # Извлекаем структурированные данные
            amount_span = item.find('span', class_='wprm-recipe-ingredient-amount')
            unit_span = item.find('span', class_='wprm-recipe-ingredient-unit')
            name_span = item.find('span', class_='wprm-recipe-ingredient-name')
            
            if name_span:
                name = self.clean_text(name_span.get_text())
                
                # Извлекаем количество
                amount = None
                if amount_span:
                    amount_text = self.clean_text(amount_span.get_text())
                    if amount_text:
                        # Пробуем преобразовать в число
                        try:
                            # Заменяем дроби
                            amount_text = amount_text.replace('½', '0.5').replace('¼', '0.25').replace('¾', '0.75')
                            amount = float(amount_text) if '.' in amount_text else int(float(amount_text))
                        except ValueError:
                            amount = None
                
                # Извлекаем единицу измерения
                unit = None
                if unit_span:
                    unit_text = self.clean_text(unit_span.get_text())
                    if unit_text:
                        unit = unit_text
                
                ingredients.append({
                    "name": name,
                    "units": unit,
                    "amount": amount
                })
        
        # Если не нашли в WPRM, пробуем из JSON-LD
        if not ingredients:
            recipe_data = self.get_recipe_json_ld()
            if recipe_data and 'recipeIngredient' in recipe_data:
                for ing_text in recipe_data['recipeIngredient']:
                    parsed = self.parse_ingredient(ing_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "500 gram gehakt" или "1 ui"
            
        Returns:
            dict: {"name": "gehakt", "amount": 500, "units": "gram"} или None
        """
        if not ingredient_text:
            return None
        
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        pattern = r'^([\d\s/.,]+)?\s*(gram|ml|eetlepels?|theelepels?|stuk|stuks?|teentjes?|snufje|liter|kg|pieces?|grams?|cloves?|teaspoons?|ball)?\s*(.+)'
        
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
            try:
                # Убираем пробелы и пробуем преобразовать
                amount_str = amount_str.replace(' ', '')
                amount = float(amount_str) if '.' in amount_str or ',' in amount_str else int(float(amount_str.replace(',', '.')))
            except ValueError:
                amount = None
        
        # Обработка единицы измерения
        if unit:
            unit = unit.strip()
        
        # Обработка названия
        if name:
            name = name.strip()
            # Убираем из названия информацию в скобках (часто это дополнительные заметки)
            name = re.sub(r'\([^)]*\)', '', name).strip()
        
        return {
            "name": name if name else text,
            "amount": amount,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            if isinstance(instructions, list):
                for step in instructions:
                    # Обрабатываем HowToSection (может содержать itemListElement)
                    if isinstance(step, dict):
                        if step.get('@type') == 'HowToSection' and 'itemListElement' in step:
                            # Извлекаем шаги из секции
                            for idx, substep in enumerate(step['itemListElement'], 1):
                                if isinstance(substep, dict) and 'text' in substep:
                                    step_text = self.clean_text(substep['text'])
                                    if step_text:
                                        # Добавляем номер для шагов в секциях
                                        steps.append(f"{len(steps) + 1}. {step_text}")
                        elif 'text' in step:
                            step_text = self.clean_text(step['text'])
                            if step_text:
                                steps.append(step_text)
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        if step_text:
                            steps.append(step_text)
        
        # Если не нашли в JSON-LD, ищем в HTML
        if not steps:
            instruction_items = self.soup.find_all('li', class_='wprm-recipe-instruction')
            for item in instruction_items:
                text_div = item.find('div', class_='wprm-recipe-instruction-text')
                if text_div:
                    step_text = self.clean_text(text_div.get_text())
                    if step_text:
                        steps.append(step_text)
        
        # Возвращаем шаги как есть (без дополнительной нумерации)
        return " ".join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data:
            # Пробуем recipeCategory
            if 'recipeCategory' in recipe_data:
                category = recipe_data['recipeCategory']
                if isinstance(category, list):
                    return ', '.join(category) if category else None
                elif isinstance(category, str):
                    return self.clean_text(category)
            
            # Пробуем recipeCuisine
            if 'recipeCuisine' in recipe_data:
                cuisine = recipe_data['recipeCuisine']
                if isinstance(cuisine, list):
                    return ', '.join(cuisine) if cuisine else None
                elif isinstance(cuisine, str):
                    return self.clean_text(cuisine)
        
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
        """Извлечение заметок"""
        # Ищем секцию с заметками в WPRM
        notes_section = self.soup.find('div', class_='wprm-recipe-notes')
        
        if notes_section:
            # Извлекаем текст, пропуская заголовок
            paragraphs = notes_section.find_all('p')
            if paragraphs:
                notes_texts = [self.clean_text(p.get_text()) for p in paragraphs]
                notes_texts = [t for t in notes_texts if t]
                return ' '.join(notes_texts) if notes_texts else None
            
            # Если нет параграфов, берем весь текст
            text = notes_section.get_text(separator=' ', strip=True)
            # Убираем возможный заголовок "Notes:" или "Opmerkingen:"
            text = re.sub(r'^(Notes?|Opmerkingen?)\s*:?\s*', '', text, flags=re.I)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Из JSON-LD keywords
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Уже строка с разделителями
                return self.clean_text(keywords)
            elif isinstance(keywords, list):
                return ', '.join(keywords)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        image_urls = []
        
        # Сначала из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'image' in recipe_data:
            images = recipe_data['image']
            if isinstance(images, list):
                # Берем только первое изображение (основное)
                if images and isinstance(images[0], str):
                    image_urls.append(images[0])
            elif isinstance(images, str):
                image_urls.append(images)
        
        # Дополнительно из meta og:image
        if not image_urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                image_urls.append(og_image['content'])
        
        # Возвращаем как строку через запятую без пробелов
        return ','.join(image_urls) if image_urls else None
    
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
    """Обработка всех HTML файлов в директории preprocessed/foodhunting_nl"""
    import os
    
    # Ищем директорию с примерами
    preprocessed_dir = Path(__file__).parent.parent / "preprocessed" / "foodhunting_nl"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обработка файлов из: {preprocessed_dir}")
        process_directory(FoodhuntingNlExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Создайте директорию preprocessed/foodhunting_nl с HTML файлами")


if __name__ == "__main__":
    main()
