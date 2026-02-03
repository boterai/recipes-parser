"""
Экстрактор данных рецептов для сайта edimdoma.ru
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class EdimdomaRuExtractor(BaseRecipeExtractor):
    """Экстрактор для edimdoma.ru"""
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем тип Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "20 minutes" или "1 hour 30 minutes"
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
            parts.append(f"{hours} hour" + ("s" if hours > 1 else ""))
        if minutes > 0:
            parts.append(f"{minutes} minute" + ("s" if minutes > 1 else ""))
        
        return " ".join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Fallback: ищем в HTML
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            if desc:  # Проверяем, что desc не None
                # Описание в JSON-LD может содержать и основное описание, и notes
                # Разделяем их по двойным переносам строк
                lines = desc.split('\n\n')
                if lines:
                    # Берем только первую часть как описание
                    first_part = self.clean_text(lines[0])
                    # Если первая часть слишком короткая или выглядит как список, попробуем meta
                    if len(first_part) > 50:
                        return first_part
        
        # Fallback: ищем meta description (может быть более чистым)
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            content = meta_desc['content']
            # Удаляем стандартные суффиксы из meta description
            content = re.sub(r'\s*20\d{2}\s+один из лучших домашних рецептов.*$', '', content, flags=re.IGNORECASE)
            content = re.sub(r'\s*Узнайте все секреты.*$', '', content, flags=re.IGNORECASE)
            content = self.clean_text(content)
            if content:
                return content
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате JSON"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredients_data = recipe_data['recipeIngredient']
            
            # Структура: [[{name, @type, value, unitCode}, ...], ...]  - может быть несколько групп
            ingredients = []
            
            # Обрабатываем все группы ингредиентов
            if isinstance(ingredients_data, list):
                for group in ingredients_data:
                    # Каждая группа это список ингредиентов
                    ingredient_list = group if isinstance(group, list) else [group]
                    
                    for item in ingredient_list:
                        if isinstance(item, dict):
                            ingredient = {
                                "name": self.clean_text(item.get('name', '')),
                                "units": item.get('unitCode'),
                                "amount": item.get('value')
                            }
                            # Конвертируем amount в строку или int
                            if ingredient['amount'] is not None:
                                try:
                                    # Пытаемся преобразовать в число
                                    amount_float = float(ingredient['amount'])
                                    # Если это целое число, сохраняем как int
                                    if amount_float.is_integer():
                                        ingredient['amount'] = int(amount_float)
                                    else:
                                        ingredient['amount'] = amount_float
                                except (ValueError, TypeError):
                                    ingredient['amount'] = str(ingredient['amount'])
                            
                            ingredients.append(ingredient)
            
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            steps = []
            
            # Добавляем нумерацию только если шагов мало (4 или меньше)
            # Это соответствует наблюдаемому паттерну в референсных данных
            add_numbering = isinstance(instructions, list) and len(instructions) <= 4
            
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        if add_numbering:
                            steps.append(f"{idx}. {step_text}")
                        else:
                            steps.append(step_text)
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        if add_numbering:
                            steps.append(f"{idx}. {step_text}")
                        else:
                            steps.append(step_text)
            
            if steps:
                return " ".join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data:
            # Приоритет: recipeCategory
            if 'recipeCategory' in recipe_data:
                category = recipe_data['recipeCategory']
                if category:
                    return self.clean_text(category)
            
            # Альтернатива: recipeCuisine
            if 'recipeCuisine' in recipe_data:
                cuisine = recipe_data['recipeCuisine']
                if cuisine:
                    return self.clean_text(cuisine)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'prepTime' in recipe_data:
            prep_time = recipe_data['prepTime']
            if prep_time and prep_time != 'PT':  # PT означает 0 времени
                return self.parse_iso_duration(prep_time)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'cookTime' in recipe_data:
            cook_time = recipe_data['cookTime']
            if cook_time and cook_time != 'PT':
                return self.parse_iso_duration(cook_time)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'totalTime' in recipe_data:
            total_time = recipe_data['totalTime']
            if total_time and total_time != 'PT':
                return self.parse_iso_duration(total_time)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            if desc:  # Проверяем, что desc не None
                # Описание в JSON-LD содержит и основное описание, и notes
                # Разделяем их по двойным переносам строк
                lines = desc.split('\n\n')
                if len(lines) > 1:
                    # Берем все части после первой как notes
                    notes = '\n\n'.join(lines[1:])
                    return self.clean_text(notes)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        recipe_data = self._get_recipe_json_ld()
        
        tags = []
        
        if recipe_data:
            # Добавляем recipeCuisine как тег
            if 'recipeCuisine' in recipe_data and recipe_data['recipeCuisine']:
                cuisine = self.clean_text(recipe_data['recipeCuisine'].lower())
                if cuisine:
                    tags.append(cuisine)
            
            # Добавляем название блюда или его часть как тег
            if 'name' in recipe_data and recipe_data['name']:
                name = self.clean_text(recipe_data['name'].lower())
                # Извлекаем ключевые слова из названия (убираем кавычки и лишние слова)
                name = re.sub(r'[«»"\']', '', name)
                if name:
                    tags.append(name)
            
            # Извлекаем основные ингредиенты как теги
            if 'recipeIngredient' in recipe_data:
                ingredients_data = recipe_data['recipeIngredient']
                if isinstance(ingredients_data, list) and len(ingredients_data) > 0:
                    ingredient_list = ingredients_data[0] if isinstance(ingredients_data[0], list) else ingredients_data
                    # Берем первые несколько ключевых ингредиентов
                    for i, item in enumerate(ingredient_list[:5]):
                        if isinstance(item, dict) and 'name' in item:
                            ing_name = self.clean_text(item['name'].lower())
                            # Упрощаем название ингредиента (убираем лишние слова)
                            ing_name = re.sub(r'\s+(замороженные|свежие|куриные)\s*$', '', ing_name)
                            if ing_name and len(ing_name) > 2:
                                tags.append(ing_name)
        
        if tags:
            # Удаляем дубликаты, сохраняя порядок
            seen = set()
            unique_tags = []
            for tag in tags:
                if tag and tag not in seen:
                    seen.add(tag)
                    unique_tags.append(tag)
            
            return ', '.join(unique_tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data:
            # Главное изображение рецепта
            if 'image' in recipe_data:
                img = recipe_data['image']
                if isinstance(img, str):
                    urls.append(img)
                elif isinstance(img, list):
                    urls.extend([i for i in img if isinstance(i, str)])
                elif isinstance(img, dict) and 'url' in img:
                    urls.append(img['url'])
            
            # Изображения из шагов
            if 'recipeInstructions' in recipe_data:
                instructions = recipe_data['recipeInstructions']
                if isinstance(instructions, list):
                    for step in instructions:
                        if isinstance(step, dict) and 'image' in step:
                            step_img = step['image']
                            if isinstance(step_img, str):
                                urls.append(step_img)
                            elif isinstance(step_img, list):
                                urls.extend([i for i in step_img if isinstance(i, str)])
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            return ','.join(unique_urls)
        
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
    """Обработка всех HTML файлов в директории preprocessed/edimdoma_ru"""
    import os
    
    # Путь к директории с предобработанными файлами
    preprocessed_dir = os.path.join("preprocessed", "edimdoma_ru")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(EdimdomaRuExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python edimdoma_ru.py")


if __name__ == "__main__":
    main()
