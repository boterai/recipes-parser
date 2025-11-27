"""
Экстрактор данных рецептов для сайта gastronom.ru
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional
from bs4 import BeautifulSoup
from extractor.base import BaseRecipeExtractor, process_directory
# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))


class GastronomRuExtractor(BaseRecipeExtractor):
    
    def extract_from_json_ld(self) -> dict:
        """Извлечение данных из JSON-LD схемы (наиболее надежный способ)"""
        # Ищем script с type="application/ld+json"
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                script_content = script.string
                if not script_content:
                    continue
                
                # На gastronom.ru может быть несколько JSON объектов склеенных вместе
                # Пробуем разделить их по закрывающей скобке + открывающей
                json_objects = []
                
                # Ищем паттерн }{ который указывает на склеенные JSON
                if '}{' in script_content:
                    # Разделяем склеенные JSON
                    parts = script_content.split('}{')
                    for i, part in enumerate(parts):
                        if i == 0:
                            json_objects.append(part + '}')
                        elif i == len(parts) - 1:
                            json_objects.append('{' + part)
                        else:
                            json_objects.append('{' + part + '}')
                else:
                    json_objects.append(script_content)
                
                # Парсим каждый JSON объект
                for json_str in json_objects:
                    try:
                        data = json.loads(json_str.strip())
                        
                        # Проверяем, это ли Recipe schema
                        if isinstance(data, dict) and data.get('@type') == 'Recipe':
                            return data
                    except json.JSONDecodeError:
                        continue
                        
            except (AttributeError, Exception):
                continue
        
        return {}
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        json_ld = self.extract_from_json_ld()
        if json_ld.get('name'):
            return self.clean_text(json_ld['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r',\s*пошаговый рецепт.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Из JSON-LD
        json_ld = self.extract_from_json_ld()
        if json_ld.get('description'):
            return self.clean_text(json_ld['description'])
        
        # Из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Убираем шаблонные фразы
            desc = re.sub(r'\.\s*Вкусный рецепт приготовления.*$', '', desc)
            return self.clean_text(desc)
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredient_items = []
        
        # Ищем элементы с itemprop="recipeIngredient" - они уже содержат название + количество
        ingredients = self.soup.find_all(attrs={'itemprop': 'recipeIngredient'})
        
        if ingredients:
            for ing in ingredients:
                # Полный текст уже содержит название и количество
                text = self.clean_text(ing.get_text())
                if text:
                    ingredient_items.append(text)
        
        if ingredient_items:
            return ', '.join(ingredient_items)
        
        return None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Из JSON-LD
        json_ld = self.extract_from_json_ld()
        if json_ld.get('recipeInstructions'):
            instructions = json_ld['recipeInstructions']
            
            for idx, step in enumerate(instructions, 1):
                # Очищаем HTML теги если есть
                step_text = re.sub(r'<[^>]+>', '', step)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    # Добавляем нумерацию если её нет
                    if not step_text.startswith(f'Шаг {idx}'):
                        step_text = f"Шаг {idx}: {step_text}"
                    steps.append(step_text)
            
            return ' '.join(steps)
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # Из JSON-LD
        json_ld = self.extract_from_json_ld()
        nutrition = json_ld.get('nutrition', {})
        
        if nutrition:
            # Формируем строку с питательной информацией
            parts = []
            
            if nutrition.get('calories'):
                parts.append(nutrition['calories'])
            
            # Белки/Жиры/Углеводы
            protein = nutrition.get('proteinContent', '').replace(' г.', ' г')
            fat = nutrition.get('fatContent', '').replace(' г.', ' г')
            carbs = nutrition.get('carbohydrateContent', '').replace(' г.', ' г')
            
            if protein or fat or carbs:
                bzu = f"Б/Ж/У: {protein}/{fat}/{carbs}"
                parts.append(bzu)
            
            if parts:
                return ', '.join(parts)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Из JSON-LD
        json_ld = self.extract_from_json_ld()
        category = json_ld.get('recipeCategory')
        
        if category:
            # Переводим на английский для унификации
            category_map = {
                'Второе блюдо': 'Main Course',
                'Закуска': 'Appetizer',
                'Салат': 'Salad',
                'Суп': 'Soup',
                'Десерт': 'Dessert',
                'Выпечка': 'Baking',
                'Напиток': 'Beverage'
            }
            return category_map.get(category, category)
        
        return None
    
    def parse_time(self, iso_duration: str) -> Optional[str]:
        """
        Парсинг ISO 8601 duration в читаемый формат
        
        Args:
            iso_duration: Строка вида "PT2H30M" или "PT30M"
        
        Returns:
            Строка вида "2 hours 30 minutes" или "30 minutes"
        """
        if not iso_duration or iso_duration == 'PT':
            return None
        
        # Парсим ISO duration
        match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?', iso_duration)
        if not match:
            return None
        
        hours, minutes = match.groups()
        
        parts = []
        if hours:
            parts.append(f"{hours} hour{'s' if int(hours) > 1 else ''}")
        if minutes:
            parts.append(f"{minutes} minute{'s' if int(minutes) > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self.extract_from_json_ld()
        prep_time = json_ld.get('prepTime')
        
        if prep_time:
            return self.parse_time(prep_time)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self.extract_from_json_ld()
        cook_time = json_ld.get('cookTime')
        
        if cook_time:
            return self.parse_time(cook_time)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self.extract_from_json_ld()
        total_time = json_ld.get('totalTime')
        
        if total_time:
            return self.parse_time(total_time)
        
        return None
    
    def extract_servings(self) -> Optional[str]:
        """Извлечение количества порций"""
        json_ld = self.extract_from_json_ld()
        servings = json_ld.get('recipeYield')
        
        if servings:
            return str(servings)
        
        return None
    
    def extract_difficulty_level(self) -> Optional[str]:
        """Извлечение уровня сложности"""
        # На gastronom.ru сложность можно попробовать определить по времени
        total_time = self.extract_total_time()
        
        if not total_time:
            return "Medium"
        
        # Простая эвристика на основе времени
        if 'hour' in total_time:
            # Извлекаем количество часов
            hours_match = re.search(r'(\d+)\s*hour', total_time)
            if hours_match:
                hours = int(hours_match.group(1))
                if hours >= 2:
                    return "Hard"
                elif hours >= 1:
                    return "Medium"
        
        return "Easy"
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию "Особенности рецепта" или "Совет"
        notes_section = self.soup.find(id='advice')
        
        if notes_section:
            # Извлекаем текст
            note_text = notes_section.get_text(separator=' ', strip=True)
            note_text = self.clean_text(note_text)
            
            # Убираем заголовки секций
            note_text = re.sub(r'^(Особенности рецепта|Совет)[:.]?\s*', '', note_text, flags=re.IGNORECASE)
            
            if note_text:
                return note_text
        
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
            "step_by_step": self.extract_steps(),
            "nutrition_info": self.extract_nutrition_info(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "servings": self.extract_servings(),
            "difficulty_level": self.extract_difficulty_level(),
            "notes": self.extract_notes()
        }


def main():
    import os

    recipes_dir = os.path.join("recipes", "gastronom_ru")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(GastronomRuExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python gastronom_ru.py [путь_к_файлу_или_директории]")


if __name__ == "__main__":
    main()
