"""
Экстрактор данных рецептов для сайта hurtigmums.dk
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class HurtigmumsDkExtractor(BaseRecipeExtractor):
    """Экстрактор для hurtigmums.dk"""
    
    def extract_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            return item
                
                # Или напрямую если это Recipe
                if data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self.extract_json_ld_recipe()
        
        name = None
        
        # Сначала пробуем из JSON-LD
        if recipe_data and 'name' in recipe_data:
            name = recipe_data['name']
        else:
            # Если JSON-LD нет (например, в print версии), ищем в WPRM HTML
            wprm_name = self.soup.find('h2', class_='wprm-recipe-name')
            if wprm_name:
                name = wprm_name.get_text(strip=True)
        
        if name:
            # Убираем префиксы и суффиксы
            # "Traditionel burger opskrift" -> "Burger"
            # "Opskrift: Dadelkugler med kokos" -> "Dadelkugler"
            # "Gammeldags oksesteg – langtidsstegt..." -> "Gammeldags oksesteg"
            
            # Убираем "Opskrift:" в начале
            name = re.sub(r'^Opskrift\s*:\s*', '', name, flags=re.IGNORECASE)
            # Убираем " opskrift" в конце
            name = re.sub(r'\s+opskrift\s*$', '', name, flags=re.IGNORECASE)
            # Убираем все после " – " или " med " или " - "
            name = re.sub(r'\s+[–-]\s+.*$', '', name)
            name = re.sub(r'\s+med\s+.*$', '', name, flags=re.IGNORECASE)
            # Убираем прилагательные в начале (Traditionel, Hjemmelavet и т.д.)
            name = re.sub(r'^(Traditionel|Hjemmelavet|Klassisk)\s+', '', name, flags=re.IGNORECASE)
            
            name = self.clean_text(name)
            # Capitalize first letter
            if name:
                name = name[0].upper() + name[1:] if len(name) > 1 else name.upper()
            
            return name
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self.extract_json_ld_recipe()
        
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из WPRM HTML разметки.
        Возвращает JSON-строку с массивом объектов {name, amount, unit}.
        Извлекает только ингредиенты из первой группы (основной рецепт).
        """
        ingredients = []
        
        # Ищем первую группу ингредиентов (основной рецепт)
        first_group = self.soup.find('div', class_='wprm-recipe-ingredient-group')
        
        if first_group:
            ingredient_items = first_group.find_all('li', class_='wprm-recipe-ingredient')
        else:
            # Если групп нет, берем все ингредиенты
            ingredient_items = self.soup.find_all('li', class_='wprm-recipe-ingredient')
        
        for item in ingredient_items:
            # Извлекаем структурированные данные из WPRM
            amount_elem = item.find('span', class_='wprm-recipe-ingredient-amount')
            unit_elem = item.find('span', class_='wprm-recipe-ingredient-unit')
            name_elem = item.find('span', class_='wprm-recipe-ingredient-name')
            
            if name_elem:
                name = self.clean_text(name_elem.get_text())
                amount = self.clean_text(amount_elem.get_text()) if amount_elem else None
                unit = self.clean_text(unit_elem.get_text()) if unit_elem else None
                
                # Конвертируем пустые строки в None
                if amount == '':
                    amount = None
                if unit == '':
                    unit = None
                
                # Удаляем дополнительные примечания из названия (после " – " или " - ")
                if name:
                    name = re.sub(r'\s+[–-]\s+.*$', '', name)
                    name = self.clean_text(name)
                
                # Конвертируем amount в правильный формат (число без строк)
                if amount:
                    # Если это число, конвертируем в int/float
                    try:
                        if ',' in amount or '.' in amount or '½' in amount or '¼' in amount:
                            # Оставляем как строку если есть дроби или десятичные
                            pass
                        else:
                            # Пробуем конвертировать в int
                            amount = int(amount)
                    except ValueError:
                        pass  # Оставляем как строку
                
                ingredient = {
                    "name": name,
                    "amount": amount,
                    "units": unit  # Используем "units" как в эталонном JSON
                }
                
                ingredients.append(ingredient)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self.extract_json_ld_recipe()
        steps = []
        
        # Сначала пробуем из JSON-LD
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            
            for step in instructions:
                if isinstance(step, dict) and 'text' in step:
                    step_text = step['text']
                    
                    # Упрощаем текст: берем только первое предложение до точки или " – "
                    # Это удалит дополнительные пояснения и детали
                    sentences = re.split(r'[.–]', step_text)
                    if sentences:
                        main_sentence = sentences[0].strip()
                        # Если предложение не заканчивается естественно, добавляем точку
                        if main_sentence and not main_sentence.endswith('.'):
                            main_sentence += '.'
                        step_text = main_sentence
                    
                    # Убираем смайлики и дополнительный whitespace
                    step_text = re.sub(r':\-?\)', '', step_text)
                    step_text = self.clean_text(step_text)
                    
                    # Убираем точку в конце для объединения
                    step_text = re.sub(r'\.\s*$', '', step_text)
                    
                    if step_text:
                        steps.append(step_text)
                elif isinstance(step, str):
                    steps.append(self.clean_text(step))
        else:
            # Если JSON-LD нет (например, в print версии), ищем в WPRM HTML
            instructions_container = self.soup.find('div', class_='wprm-recipe-instructions-container')
            if instructions_container:
                instruction_items = instructions_container.find_all('li', class_='wprm-recipe-instruction')
                for item in instruction_items:
                    # Получаем текст инструкции
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    if step_text:
                        steps.append(step_text)
        
        # Объединяем все шаги в одну строку
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self.extract_json_ld_recipe()
        
        if recipe_data:
            category = recipe_data.get('recipeCategory')
            if category:
                if isinstance(category, list):
                    # Берем первую категорию
                    return self.clean_text(category[0]) if category else None
                return self.clean_text(category)
        
        return None
    
    def parse_iso_duration(self, duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в виде "20 minutes" или "1 hour 30 minutes"
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
            parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
        if minutes > 0:
            parts.append(f"{minutes} minute" if minutes == 1 else f"{minutes} minutes")
        
        return ' '.join(parts) if parts else None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки из WPRM HTML"""
        # Ищем в WPRM HTML разметке
        prep_time_elem = self.soup.find('span', class_='wprm-recipe-prep_time-minutes')
        
        if prep_time_elem:
            time_text = self.clean_text(prep_time_elem.get_text())
            # Удаляем лишние слова "minutter" и оставляем только число
            time_text = re.sub(r'\s*minutter\s*', '', time_text)
            # Добавляем " minutes" в конце
            if time_text and 'minute' not in time_text.lower():
                time_text = f"{time_text} minutes"
            return self.clean_text(time_text)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления из WPRM HTML"""
        # Ищем в WPRM HTML разметке
        cook_time_elem = self.soup.find('span', class_='wprm-recipe-cook_time-minutes')
        
        if cook_time_elem:
            time_text = self.clean_text(cook_time_elem.get_text())
            # Удаляем лишние слова "minutter" и оставляем только число
            time_text = re.sub(r'\s*minutter\s*', '', time_text)
            # Добавляем " minutes" в конце
            if time_text and 'minute' not in time_text.lower():
                time_text = f"{time_text} minutes"
            return self.clean_text(time_text)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.extract_json_ld_recipe()
        
        if recipe_data and 'totalTime' in recipe_data:
            iso_time = recipe_data['totalTime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов из WPRM или описания"""
        # Сначала пробуем найти в WPRM notes container
        notes_container = self.soup.find('div', class_='wprm-recipe-notes-container')
        
        if notes_container:
            # Ищем текст внутри контейнера
            notes_text = notes_container.get_text(separator=' ', strip=True)
            # Убираем заголовок "Noter" если есть
            notes_text = re.sub(r'^Noter\s*:?\s*', '', notes_text, flags=re.IGNORECASE)
            notes_text = self.clean_text(notes_text)
            if notes_text:
                return notes_text
        
        # Если в WPRM нет, ищем подсказки в описании
        # Например: "Har du tid og overskud laver du selvfølgelig dine egne hjemmelavede burgerboller."
        recipe_data = self.extract_json_ld_recipe()
        if recipe_data and 'description' in recipe_data:
            description = recipe_data['description']
            # Ищем предложения с советами (обычно начинаются с "Har du", "Du kan", etc.)
            match = re.search(r'((?:Har du|Du kan)[^.]+\.)', description, re.IGNORECASE)
            if match:
                note = self.clean_text(match.group(1))
                return note
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из dish_name, category и cuisine"""
        tags = []
        
        # Добавляем упрощенное имя блюда
        dish_name = self.extract_dish_name()
        if dish_name:
            tags.append(dish_name.lower())
        
        # Добавляем категорию
        category = self.extract_category()
        if category:
            tags.append(category.lower())
        
        # Добавляем кухню/cuisine
        recipe_data = self.extract_json_ld_recipe()
        if recipe_data and 'recipeCuisine' in recipe_data:
            cuisine = recipe_data['recipeCuisine']
            if isinstance(cuisine, list):
                for c in cuisine:
                    if c:
                        tags.append(self.clean_text(c).lower())
            elif cuisine:
                tags.append(self.clean_text(cuisine).lower())
        
        # Возвращаем уникальные теги через запятую с пробелом
        unique_tags = []
        seen = set()
        for tag in tags:
            if tag and tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        recipe_data = self.extract_json_ld_recipe()
        
        if recipe_data and 'image' in recipe_data:
            images = recipe_data['image']
            urls = []
            
            if isinstance(images, list):
                for img in images:
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, dict) and 'url' in img:
                        urls.append(img['url'])
            elif isinstance(images, str):
                urls.append(images)
            elif isinstance(images, dict) and 'url' in images:
                urls.append(images['url'])
            
            # Возвращаем как строку через запятую (без пробелов)
            return ','.join(urls) if urls else None
        
        return None
    
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта
        
        Returns:
            Словарь с данными рецепта
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        total_time = self.extract_total_time()
        notes = self.extract_notes()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "notes": notes,
            "tags": tags,
            "image_urls": image_urls
        }


def main():
    """
    Точка входа для обработки HTML-файлов из директории preprocessed/hurtigmums_dk
    """
    import os
    
    # Путь к директории с HTML-файлами
    preprocessed_dir = os.path.join("preprocessed", "hurtigmums_dk")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка файлов из директории: {preprocessed_dir}")
        process_directory(HurtigmumsDkExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python hurtigmums_dk.py")


if __name__ == "__main__":
    main()
