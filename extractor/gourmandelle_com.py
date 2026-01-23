"""
Экстрактор данных рецептов для сайта gourmandelle.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class GourmandelleExtractor(BaseRecipeExtractor):
    """Экстрактор для gourmandelle.com"""
    
    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Функция для проверки типа Recipe
                def is_recipe(item):
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        return 'Recipe' in item_type
                    return item_type == 'Recipe'
                
                # Проверяем различные форматы JSON-LD
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and is_recipe(item):
                            return item
                elif isinstance(data, dict):
                    if '@graph' in data:
                        for item in data['@graph']:
                            if is_recipe(item):
                                return item
                    elif is_recipe(data):
                        return data
                        
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Пробуем JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Пробуем WPRM HTML
        name_elem = self.soup.find(class_='wprm-recipe-name')
        if name_elem:
            return self.clean_text(name_elem.get_text())
        
        # Пробуем h1/h2
        title_elem = self.soup.find(['h1', 'h2'], class_=re.compile(r'recipe.*name|title', re.I))
        if title_elem:
            return self.clean_text(title_elem.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Пробуем JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Пробуем WPRM HTML
        summary_elem = self.soup.find(class_='wprm-recipe-summary')
        if summary_elem:
            return self.clean_text(summary_elem.get_text())
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Пробуем JSON-LD (приоритет, т.к. там более структурированные данные)
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredient_strings = recipe_data['recipeIngredient']
            if isinstance(ingredient_strings, list):
                for ing_str in ingredient_strings:
                    parsed = self._parse_ingredient_string(ing_str)
                    if parsed:
                        ingredients.append(parsed)
        
        # Если JSON-LD не помог, пробуем WPRM HTML (там есть отдельные поля)
        if not ingredients:
            ingredient_items = self.soup.find_all(class_='wprm-recipe-ingredient')
            for item in ingredient_items:
                # WPRM разбивает ингредиенты на amount, unit, name
                amount_elem = item.find(class_='wprm-recipe-ingredient-amount')
                unit_elem = item.find(class_='wprm-recipe-ingredient-unit')
                name_elem = item.find(class_='wprm-recipe-ingredient-name')
                
                if name_elem:
                    name = self.clean_text(name_elem.get_text())
                    amount = self.clean_text(amount_elem.get_text()) if amount_elem else None
                    unit = self.clean_text(unit_elem.get_text()) if unit_elem else None
                    
                    if name:
                        ingredients.append({
                            "name": name,
                            "amount": amount,
                            "units": unit  # Используем "units" как в эталонном JSON
                        })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def _parse_ingredient_string(self, ingredient_str: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_str: Строка вида "1 ½ cups flour" или "2 Tbsps olive oil"
            
        Returns:
            dict: {"name": "flour", "amount": "1 ½", "units": "cups"} или None
        """
        if not ingredient_str:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_str)
        
        # Паттерн для извлечения количества, единицы и названия
        # Поддерживаем дроби вида "1 ½", числа с точкой/запятой, диапазоны
        pattern = r'^([\d\s/.,½¼¾⅓⅔⅛⅜⅝⅞-]+)?\s*(cups?|tbsps?|tsps?|tablespoons?|teaspoons?|pounds?|ounces?|lbs?|oz|grams?|g|kg|ml|liters?|l|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|cloves?|sprigs?|unit|to taste)?\s*(.+)?$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем всю строку как название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount = amount_str.strip()
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        if name:
            name = name.strip()
            # Удаляем все содержимое в скобках (включая описания)
            name = re.sub(r'\([^)]*\)', '', name)
            # Удаляем одиночные скобки
            name = re.sub(r'[()]', '', name)
            # Удаляем фразы типа "diced", "minced", "ground", "sliced", "chopped" в конце
            name = re.sub(r',?\s+\b(diced|minced|ground|sliced|chopped|grated|shredded|frozen or fresh|fresh or frozen)\b.*$', '', name, flags=re.IGNORECASE)
            # Удаляем фразы "to taste", "as needed", "optional"
            name = re.sub(r',?\s*\b(to taste|as needed|or more|if needed|optional|for garnish)\s*$', '', name, flags=re.IGNORECASE)
            name = name.strip()
        
        if not name:
            name = text  # Если не смогли выделить название, берем всю строку
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        steps = []
        
        # Пробуем JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            if isinstance(instructions, list):
                step_num = 0
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                    else:
                        continue
                    
                    # Пропускаем заголовки секций (обычно заканчиваются на ':')
                    if step_text.endswith(':'):
                        continue
                    
                    if step_text:
                        step_num += 1
                        steps.append(f"{step_num}. {step_text}")
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
        
        # Если JSON-LD не помог, пробуем WPRM HTML
        if not steps:
            instruction_items = self.soup.find_all(class_='wprm-recipe-instruction')
            for idx, item in enumerate(instruction_items, 1):
                text_elem = item.find(class_='wprm-recipe-instruction-text')
                if text_elem:
                    step_text = self.clean_text(text_elem.get_text())
                    if step_text:
                        steps.append(f"{idx}. {step_text}")
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Пробуем JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data:
            # recipeCategory
            if 'recipeCategory' in recipe_data:
                category = recipe_data['recipeCategory']
                if isinstance(category, list):
                    return ', '.join([self.clean_text(c) for c in category])
                return self.clean_text(category)
            
            # recipeCuisine как альтернатива
            if 'recipeCuisine' in recipe_data:
                cuisine = recipe_data['recipeCuisine']
                if isinstance(cuisine, list):
                    return ', '.join([self.clean_text(c) for c in cuisine])
                return self.clean_text(cuisine)
        
        # Пробуем мета-тег article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_time(self, time_key: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_key: Ключ времени ('prepTime', 'cookTime', 'totalTime')
        """
        # Пробуем JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and time_key in recipe_data:
            iso_time = recipe_data[time_key]
            # Конвертируем ISO 8601 duration в минуты
            minutes = self._parse_iso_duration(iso_time)
            if minutes:
                return f"{minutes} minutes"
        
        # Пробуем WPRM HTML
        class_map = {
            'prepTime': 'wprm-recipe-prep-time-container',
            'cookTime': 'wprm-recipe-cook-time-container',
            'totalTime': 'wprm-recipe-total-time-container'
        }
        
        container_class = class_map.get(time_key)
        if container_class:
            time_container = self.soup.find(class_=container_class)
            if time_container:
                # Ищем значение времени
                time_value = time_container.find(class_=re.compile(r'recipe-details-minutes'))
                if time_value:
                    minutes = self.clean_text(time_value.get_text())
                    if minutes and minutes.isdigit():
                        return f"{minutes} minutes"
        
        return None
    
    def _parse_iso_duration(self, duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах, например "90"
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
        
        return str(total_minutes) if total_minutes > 0 else None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prepTime')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('cookTime')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('totalTime')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Пробуем WPRM notes
        notes_section = self.soup.find(class_='wprm-recipe-notes')
        if notes_section:
            # Убираем заголовок "Notes:" если есть
            text = notes_section.get_text(separator=' ', strip=True)
            text = re.sub(r'^Notes?\s*:?\s*', '', text, flags=re.I)
            text = self.clean_text(text)
            return text if text else None
        
        # Альтернативно ищем в JSON-LD (некоторые сайты используют custom поля)
        recipe_data = self._get_json_ld_recipe()
        if recipe_data:
            # Некоторые сайты используют 'recipeNotes' или просто notes
            for key in ['recipeNotes', 'notes', 'cookingNotes']:
                if key in recipe_data:
                    notes = recipe_data[key]
                    if isinstance(notes, str):
                        return self.clean_text(notes)
                    elif isinstance(notes, list):
                        return ' '.join([self.clean_text(n) for n in notes if isinstance(n, str)])
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Пробуем JSON-LD keywords
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Уже строка с разделителями
                return self.clean_text(keywords)
            elif isinstance(keywords, list):
                # Список тегов - объединяем через запятую
                return ', '.join([self.clean_text(k) for k in keywords])
        
        # Альтернативно из meta keywords
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Пробуем JSON-LD
        recipe_data = self._get_json_ld_recipe()
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
        
        # Добавляем og:image если еще нет
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
            
            # Возвращаем как строку через запятую (без пробелов)
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
    """Основная функция для обработки директории с HTML-страницами"""
    import os
    
    # Путь к директории с примерами
    preprocessed_dir = os.path.join("preprocessed", "gourmandelle_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(GourmandelleExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print(f"Текущая директория: {os.getcwd()}")


if __name__ == "__main__":
    main()
