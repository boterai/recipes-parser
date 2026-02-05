"""
Экстрактор данных рецептов для сайта bakingtaste.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class BakingTasteExtractor(BaseRecipeExtractor):
    """Экстрактор для bakingtaste.com"""
    
    def _get_recipe_data_from_json_ld(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем, есть ли @graph
                if isinstance(data, dict) and '@graph' in data:
                    graph = data['@graph']
                    if isinstance(graph, list):
                        for item in graph:
                            if isinstance(item, dict) and item.get('@type') == 'Recipe':
                                return item
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем JSON-LD
        recipe_data = self._get_recipe_data_from_json_ld()
        if recipe_data and 'name' in recipe_data:
            name = recipe_data['name']
            name = self._clean_dish_name(name)
            return self.clean_text(name)
        
        # Fallback: ищем в HTML
        name_elem = self.soup.find('h2', class_='wprm-recipe-name')
        if not name_elem:
            name_elem = self.soup.find('h1', class_='wprm-recipe-name')
        
        if name_elem:
            name = name_elem.get_text()
            name = self._clean_dish_name(name)
            return self.clean_text(name)
        
        return None
    
    def _clean_dish_name(self, name: str) -> str:
        """Очистка названия блюда от лишних слов"""
        # Убираем суффикс с описанием (после двоеточия)
        name = re.sub(r':\s*.+$', '', name)
        # Убираем префиксы типа "How to Make the Best ... Ever (Super Easy!)"
        name = re.sub(r'^(How to Make (the )?|The )?(Best|Perfect|Ultimate|Easy|Quick|Homemade)\s+', '', name, flags=re.IGNORECASE)
        # Убираем суффиксы в скобках
        name = re.sub(r'\s*\([^)]*\)\s*$', '', name)
        # Убираем " Ever" в конце
        name = re.sub(r'\s+Ever\s*$', '', name, flags=re.IGNORECASE)
        # Убираем типичные суффиксы после названия рецепта (с учетом разных апострофов)
        name = re.sub(r'\s+(You[\'\'\`]ll|You Will|You[\'\'\`]re Going To Love)\s+.*$', '', name, flags=re.IGNORECASE)
        
        return name
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем JSON-LD
        recipe_data = self._get_recipe_data_from_json_ld()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Fallback: ищем в HTML
        desc_elem = self.soup.find('div', class_='wprm-recipe-summary')
        if desc_elem:
            # Извлекаем текст из h3 или всего блока
            h3 = desc_elem.find('h3')
            if h3:
                return self.clean_text(h3.get_text())
            return self.clean_text(desc_elem.get_text())
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Сначала пытаемся извлечь из HTML (более детальная структура)
        ingredient_items = self.soup.find_all('li', class_='wprm-recipe-ingredient')
        
        for item in ingredient_items:
            # Ищем структурированные элементы
            amount_elem = item.find('span', class_='wprm-recipe-ingredient-amount')
            unit_elem = item.find('span', class_='wprm-recipe-ingredient-unit')
            name_elem = item.find('span', class_='wprm-recipe-ingredient-name')
            
            if name_elem:
                amount = None
                units = None
                
                if amount_elem:
                    amount_text = self.clean_text(amount_elem.get_text())
                    # Преобразуем дроби в десятичные числа
                    amount_text = self._convert_fractions(amount_text)
                    # Преобразуем в число
                    try:
                        amount = float(amount_text) if amount_text else None
                    except ValueError:
                        amount = amount_text
                
                if unit_elem:
                    unit_text = self.clean_text(unit_elem.get_text())
                    units = unit_text if unit_text else None
                
                name = self.clean_text(name_elem.get_text())
                # Удаляем метрические измерения из названия (например, "150g ", "60ml ")
                name = re.sub(r'^\d+\.?\d*\s*(g|ml|kg|l|oz|lb)\s+', '', name)
                
                if name:
                    ingredients.append({
                        "name": name,
                        "units": units,
                        "amount": amount
                    })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def _convert_fractions(self, text: str) -> str:
        """Конвертирует Unicode дроби в десятичные числа"""
        if not text:
            return text
        
        fraction_map = {
            '½': 1/2, '¼': 1/4, '¾': 3/4,
            '⅓': 1/3, '⅔': 2/3, '⅛': 1/8,
            '⅜': 3/8, '⅝': 5/8, '⅞': 7/8,
            '⅕': 1/5, '⅖': 2/5, '⅗': 3/5, '⅘': 4/5
        }
        
        # Обработка смешанных чисел (например, "1 ¾")
        parts = text.strip().split()
        total = 0.0
        
        for part in parts:
            if part in fraction_map:
                total += fraction_map[part]
            else:
                try:
                    total += float(part)
                except ValueError:
                    # Если не число, возвращаем как есть
                    return text
        
        return str(total)
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        # Сначала пробуем JSON-LD
        recipe_data = self._get_recipe_data_from_json_ld()
        
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    step_text = None
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                    
                    if step_text:
                        steps.append(f"{idx}. {step_text}")
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            
            if steps:
                return ' '.join(steps)
        
        # Fallback: ищем в HTML
        instructions_container = self.soup.find('ul', class_='wprm-recipe-instructions')
        if not instructions_container:
            instructions_container = self.soup.find('ol', class_='wprm-recipe-instructions')
        
        if instructions_container:
            steps = []
            instruction_items = instructions_container.find_all('li', class_='wprm-recipe-instruction')
            
            for item in instruction_items:
                # Ищем текст инструкции
                text_elem = item.find('div', class_='wprm-recipe-instruction-text')
                if text_elem:
                    step_text = self.clean_text(text_elem.get_text())
                    if step_text:
                        steps.append(step_text)
            
            if steps:
                return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем JSON-LD
        recipe_data = self._get_recipe_data_from_json_ld()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            if isinstance(category, list):
                return self.clean_text(category[0]) if category else None
            elif isinstance(category, str):
                return self.clean_text(category)
        
        # Fallback: ищем в HTML
        category_elem = self.soup.find('span', class_='wprm-recipe-course')
        if category_elem:
            return self.clean_text(category_elem.get_text())
        
        return None
    
    def _parse_iso_duration(self, duration: str) -> Optional[str]:
        """Конвертирует ISO 8601 duration в читаемый формат"""
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
        
        # Формируем строку
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Сначала пробуем JSON-LD
        recipe_data = self._get_recipe_data_from_json_ld()
        
        if recipe_data and 'prepTime' in recipe_data:
            return self._parse_iso_duration(recipe_data['prepTime'])
        
        # Fallback: ищем в HTML
        time_elem = self.soup.find('span', class_='wprm-recipe-prep_time-minutes')
        if time_elem:
            text = self.clean_text(time_elem.get_text())
            # Извлекаем только число
            match = re.search(r'(\d+)', text)
            if match:
                minutes = match.group(1)
                return f"{minutes} minute{'s' if int(minutes) > 1 else ''}"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Сначала пробуем JSON-LD
        recipe_data = self._get_recipe_data_from_json_ld()
        
        if recipe_data and 'cookTime' in recipe_data:
            return self._parse_iso_duration(recipe_data['cookTime'])
        
        # Fallback: ищем в HTML
        time_elem = self.soup.find('span', class_='wprm-recipe-cook_time-minutes')
        if time_elem:
            text = self.clean_text(time_elem.get_text())
            # Извлекаем только число
            match = re.search(r'(\d+)', text)
            if match:
                minutes = match.group(1)
                return f"{minutes} minute{'s' if int(minutes) > 1 else ''}"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Сначала пробуем JSON-LD
        recipe_data = self._get_recipe_data_from_json_ld()
        
        if recipe_data and 'totalTime' in recipe_data:
            return self._parse_iso_duration(recipe_data['totalTime'])
        
        # Fallback: ищем в HTML
        time_elem = self.soup.find('span', class_='wprm-recipe-total_time-minutes')
        if time_elem:
            text = self.clean_text(time_elem.get_text())
            # Извлекаем только число
            match = re.search(r'(\d+)', text)
            if match:
                minutes = match.group(1)
                return f"{minutes} minute{'s' if int(minutes) > 1 else ''}"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок к рецепту"""
        # Ищем контейнер с заметками
        notes_container = self.soup.find('div', class_='wprm-recipe-notes-container')
        
        if notes_container:
            # Извлекаем весь текст из списков и параграфов
            notes_text = []
            
            # Ищем списки
            for ul in notes_container.find_all('ul'):
                for li in ul.find_all('li'):
                    text = self.clean_text(li.get_text())
                    if text:
                        notes_text.append(text)
            
            # Ищем параграфы
            for p in notes_container.find_all('p'):
                text = self.clean_text(p.get_text())
                if text:
                    notes_text.append(text)
            
            # Если ничего не нашли в списках/параграфах, берем весь текст
            if not notes_text:
                text = self.clean_text(notes_container.get_text())
                if text:
                    notes_text.append(text)
            
            return ' '.join(notes_text) if notes_text else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        recipe_data = self._get_recipe_data_from_json_ld()
        
        if recipe_data and 'image' in recipe_data:
            image = recipe_data['image']
            if isinstance(image, list):
                urls.extend([img for img in image if isinstance(img, str)])
            elif isinstance(image, str):
                urls.append(image)
        
        # Удаляем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            return ','.join(unique_urls) if unique_urls else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Сначала пробуем JSON-LD
        recipe_data = self._get_recipe_data_from_json_ld()
        
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Преобразуем в нужный формат (теги через запятую с пробелом)
                tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                return ', '.join(tags) if tags else None
        
        # Fallback: ищем в HTML
        tag_elems = self.soup.find_all('span', class_='wprm-recipe-keyword')
        if tag_elems:
            tags = [self.clean_text(tag.get_text()) for tag in tag_elems if tag.get_text().strip()]
            return ', '.join(tags) if tags else None
        
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
    """Тестирование экстрактора на примерах из preprocessed/bakingtaste_com"""
    import os
    
    # Путь к директории с примерами
    preprocessed_dir = os.path.join("preprocessed", "bakingtaste_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(BakingTasteExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python bakingtaste_com.py")


if __name__ == "__main__":
    main()
