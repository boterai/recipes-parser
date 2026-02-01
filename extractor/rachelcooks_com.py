"""
Экстрактор данных рецептов для сайта rachelcooks.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class RachelCooksExtractor(BaseRecipeExtractor):
    """Экстрактор для rachelcooks.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в HTML с классом wprm-recipe-name
        recipe_name = self.soup.find(class_='wprm-recipe-name')
        if recipe_name:
            name = self.clean_text(recipe_name.get_text())
            # Убираем суффиксы типа " Recipe"
            name = re.sub(r'\s+Recipe\s*$', '', name, flags=re.IGNORECASE)
            return name
        
        # Альтернативно - из JSON-LD
        json_ld_data = self._extract_json_ld()
        if json_ld_data and 'name' in json_ld_data:
            name = json_ld_data['name']
            # Убираем суффиксы типа " Recipe"
            name = re.sub(r'\s+Recipe\s*$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в HTML с классом wprm-recipe-summary
        summary = self.soup.find(class_='wprm-recipe-summary')
        if summary:
            return self.clean_text(summary.get_text())
        
        # Альтернативно - из JSON-LD
        json_ld_data = self._extract_json_ld()
        if json_ld_data and 'description' in json_ld_data:
            return self.clean_text(json_ld_data['description'])
        
        return None
    
    def extract_ingredients(self) -> Optional[list]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем контейнер с ингредиентами
        ingredients_container = self.soup.find(class_='wprm-recipe-ingredients-container')
        if ingredients_container:
            # Находим все элементы ингредиентов
            ingredient_items = ingredients_container.find_all(class_='wprm-recipe-ingredient')
            
            for item in ingredient_items:
                # Извлекаем amount, unit и name
                amount_elem = item.find(class_='wprm-recipe-ingredient-amount')
                unit_elem = item.find(class_='wprm-recipe-ingredient-unit')
                name_elem = item.find(class_='wprm-recipe-ingredient-name')
                
                amount = None
                unit = None
                name = None
                
                if amount_elem:
                    amount_text = self.clean_text(amount_elem.get_text())
                    # Конвертируем дроби и обрабатываем числа
                    amount = self._parse_amount(amount_text)
                
                if unit_elem:
                    unit = self.clean_text(unit_elem.get_text())
                
                if name_elem:
                    # Извлекаем только текст, без вложенных ссылок и нот
                    # Убираем элементы с классами wprm-recipe-ingredient-notes
                    name_clone = name_elem.__copy__()
                    for notes in name_clone.find_all(class_='wprm-recipe-ingredient-notes'):
                        notes.decompose()
                    name = self.clean_text(name_clone.get_text())
                
                # Если есть хотя бы название, добавляем ингредиент
                if name:
                    ingredients.append({
                        "name": name,
                        "amount": amount,
                        "units": unit  # Используем "units" как в примере JSON
                    })
        
        return ingredients if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем контейнер с инструкциями
        instructions_container = self.soup.find(class_='wprm-recipe-instructions-container')
        if instructions_container:
            # Находим все шаги
            instruction_items = instructions_container.find_all(class_='wprm-recipe-instruction')
            
            for item in instruction_items:
                # Извлекаем текст шага
                text_elem = item.find(class_='wprm-recipe-instruction-text')
                if text_elem:
                    step_text = self.clean_text(text_elem.get_text())
                    if step_text:
                        steps.append(step_text)
        
        # Объединяем все шаги в одну строку
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Категория обычно в JSON-LD
        json_ld_data = self._extract_json_ld()
        if json_ld_data:
            # Проверяем recipeCategory
            if 'recipeCategory' in json_ld_data:
                category = json_ld_data['recipeCategory']
                if isinstance(category, list) and category:
                    return self.clean_text(category[0])
                elif isinstance(category, str):
                    return self.clean_text(category)
            
            # Альтернативно - recipeCuisine
            if 'recipeCuisine' in json_ld_data:
                cuisine = json_ld_data['recipeCuisine']
                if isinstance(cuisine, list) and cuisine:
                    return self.clean_text(cuisine[0])
                elif isinstance(cuisine, str):
                    return self.clean_text(cuisine)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Сначала пробуем из JSON-LD
        json_ld_data = self._extract_json_ld()
        if json_ld_data and 'prepTime' in json_ld_data:
            return self._parse_iso_duration(json_ld_data['prepTime'])
        
        # Из HTML
        prep_container = self.soup.find(class_='wprm-recipe-prep-time-container')
        if prep_container:
            time_elem = prep_container.find(class_='wprm-recipe-time')
            if time_elem:
                return self.clean_text(time_elem.get_text())
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        # Сначала пробуем из JSON-LD
        json_ld_data = self._extract_json_ld()
        if json_ld_data and 'cookTime' in json_ld_data:
            return self._parse_iso_duration(json_ld_data['cookTime'])
        
        # Из HTML
        cook_container = self.soup.find(class_='wprm-recipe-cook-time-container')
        if cook_container:
            time_elem = cook_container.find(class_='wprm-recipe-time')
            if time_elem:
                return self.clean_text(time_elem.get_text())
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Сначала пробуем из JSON-LD
        json_ld_data = self._extract_json_ld()
        if json_ld_data and 'totalTime' in json_ld_data:
            return self._parse_iso_duration(json_ld_data['totalTime'])
        
        # Из HTML
        total_container = self.soup.find(class_='wprm-recipe-total-time-container')
        if total_container:
            time_elem = total_container.find(class_='wprm-recipe-time')
            if time_elem:
                return self.clean_text(time_elem.get_text())
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем секцию с заметками
        notes_container = self.soup.find(class_='wprm-recipe-notes-container')
        if notes_container:
            # Извлекаем текст заметок
            notes_text = notes_container.get_text(separator=' ', strip=True)
            return self.clean_text(notes_text) if notes_text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем теги в JSON-LD (keywords)
        json_ld_data = self._extract_json_ld()
        if json_ld_data and 'keywords' in json_ld_data:
            keywords = json_ld_data['keywords']
            if isinstance(keywords, str):
                # Уже строка с тегами через запятую
                return self.clean_text(keywords)
            elif isinstance(keywords, list):
                # Список тегов - объединяем через запятую
                return ', '.join([self.clean_text(k) for k in keywords if k])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Из JSON-LD
        json_ld_data = self._extract_json_ld()
        if json_ld_data and 'image' in json_ld_data:
            images = json_ld_data['image']
            if isinstance(images, str):
                urls.append(images)
            elif isinstance(images, list):
                urls.extend([img for img in images if isinstance(img, str)])
        
        # 2. Из HTML - wprm-recipe-image
        image_containers = self.soup.find_all(class_='wprm-recipe-image')
        for container in image_containers:
            img = container.find('img')
            if img and img.get('src'):
                src = img['src']
                # Пропускаем SVG placeholders и data: URLs
                if not src.startswith('data:'):
                    urls.append(src)
        
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
    
    def _extract_json_ld(self) -> Optional[dict]:
        """Извлечение Recipe данных из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в структуре
                if isinstance(data, dict):
                    # Прямой Recipe
                    if data.get('@type') == 'Recipe':
                        return data
                    
                    # Recipe в @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and item.get('@type') == 'Recipe':
                                return item
                
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
            
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def _parse_iso_duration(self, duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT5M" или "PT1H30M"
            
        Returns:
            Время в формате "5 minutes" или "1 hour 30 minutes"
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
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def _parse_amount(self, amount_text: str) -> Optional[float]:
        """
        Парсинг количества с поддержкой дробей
        
        Args:
            amount_text: строка вида "1", "1/2", "1 1/2"
            
        Returns:
            Число или None
        """
        if not amount_text:
            return None
        
        # Замена Unicode дробей на числа
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5'
        }
        
        for fraction, decimal in fraction_map.items():
            amount_text = amount_text.replace(fraction, decimal)
        
        # Обработка дробей типа "1/2" или "1 1/2"
        if '/' in amount_text:
            parts = amount_text.split()
            total = 0
            for part in parts:
                if '/' in part:
                    num, denom = part.split('/')
                    total += float(num) / float(denom)
                else:
                    total += float(part)
            return total
        
        # Простое число
        try:
            return float(amount_text.replace(',', '.'))
        except ValueError:
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
        
        # Конвертируем ingredients в JSON строку, если не None
        ingredients_json = None
        if ingredients:
            ingredients_json = json.dumps(ingredients, ensure_ascii=False)
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients_json,
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
    """Обработка директории preprocessed/rachelcooks_com"""
    import os
    
    # Путь к директории с примерами
    preprocessed_dir = os.path.join("preprocessed", "rachelcooks_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(RachelCooksExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python rachelcooks_com.py")


if __name__ == "__main__":
    main()
