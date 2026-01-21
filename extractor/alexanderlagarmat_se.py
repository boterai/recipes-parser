"""
Экстрактор данных рецептов для сайта alexanderlagarmat.se
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class AlexanderLagarmatSeExtractor(BaseRecipeExtractor):
    """Экстрактор для alexanderlagarmat.se"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате строки, например "20 minutes"
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
        
        # Формируем строку
        if hours > 0 and minutes > 0:
            return f"{hours * 60 + minutes} minutes"
        elif hours > 0:
            return f"{hours * 60} minutes"
        elif minutes > 0:
            return f"{minutes} minutes"
        
        return None
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлекает JSON-LD данные рецепта из HTML"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            return item
                
                # Ищем Recipe напрямую
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем извлечь из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - Recept"
            title = re.sub(r'\s*-\s*Recept.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем извлечь из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD в структурированном формате"""
        recipe_data = self._get_recipe_json_ld()
        
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredients_list = []
        ingredient_strings = recipe_data['recipeIngredient']
        
        for ingredient_text in ingredient_strings:
            parsed = self.parse_ingredient(ingredient_text)
            if parsed:
                ingredients_list.append(parsed)
        
        return json.dumps(ingredients_list, ensure_ascii=False) if ingredients_list else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "4,5 dl vetemjöl" или "120 gram smör"
            
        Returns:
            dict: {"name": "vetemjöl", "amount": 4.5, "units": "dl"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
        # Заменяем запятую на точку для чисел
        text = re.sub(r'(\d),(\d)', r'\1.\2', text)
        
        # Паттерн для извлечения: число (включая дроби) + единица + название
        # Примеры: "4.5 dl vetemjöl", "120 gram smör", "2 ägg", "1/2 tsk salt"
        pattern = r'^([\d./]+)\s+(dl|l|ml|gram|g|kg|tsk|msk|krm|stora?|st|stycken?|pinch)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название (без количества)
            # Убираем возможные начальные числа и единицы
            cleaned_name = re.sub(r'^[\d./]+\s*(?:dl|l|ml|gram|g|kg|tsk|msk|krm|stora?|st|stycken?|pinch)?\s*', '', text)
            if not cleaned_name:
                cleaned_name = text
            
            return {
                "name": self.clean_text(cleaned_name),
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества (включая дроби)
        amount = None
        if amount_str:
            try:
                # Обработка дробей типа "1/2"
                if '/' in amount_str:
                    parts = amount_str.split('/')
                    if len(parts) == 2:
                        amount = float(parts[0]) / float(parts[1])
                else:
                    amount = float(amount_str)
            except (ValueError, ZeroDivisionError):
                amount = None
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": self.clean_text(name),
            "amount": amount,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self._get_recipe_json_ld()
        
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        steps = []
        instructions = recipe_data['recipeInstructions']
        
        if isinstance(instructions, list):
            for idx, step in enumerate(instructions, 1):
                if isinstance(step, dict) and 'text' in step:
                    step_text = self.clean_text(step['text'])
                    steps.append(f"{idx}. {step_text}")
                elif isinstance(step, str):
                    step_text = self.clean_text(step)
                    steps.append(f"{idx}. {step_text}")
        elif isinstance(instructions, str):
            steps.append(self.clean_text(instructions))
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            if isinstance(category, list):
                return ', '.join(category) if category else None
            elif isinstance(category, str):
                return self.clean_text(category)
        
        # Альтернативно - из breadcrumbs в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BreadcrumbList':
                            items = item.get('itemListElement', [])
                            # Берем предпоследний элемент (последний - это название рецепта)
                            if len(items) >= 2:
                                return self.clean_text(items[-2].get('name', ''))
                            
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем блоки с классами wprm-recipe-notes
        notes_section = self.soup.find(class_=re.compile(r'wprm-recipe-notes', re.I))
        
        if notes_section:
            # Извлекаем текст без заголовка
            text = notes_section.get_text(separator=' ', strip=True)
            # Убираем заголовки типа "Notes:", "Notiser:", и т.д.
            text = re.sub(r"^(?:Notes?|Notiser?)[\s:]*", '', text, flags=re.I)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                return self.clean_text(keywords)
            elif isinstance(keywords, list):
                return ', '.join(keywords)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Извлекаем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        
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
        
        # 2. Ищем в мета-тегах как fallback
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
    """Обработка HTML файлов из директории preprocessed/alexanderlagarmat_se"""
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join("preprocessed", "alexanderlagarmat_se")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(AlexanderLagarmatSeExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python alexanderlagarmat_se.py")


if __name__ == "__main__":
    main()
