"""
Экстрактор данных рецептов для сайта foodandmood.blog
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class FoodAndMoodExtractor(BaseRecipeExtractor):
    """Экстрактор для foodandmood.blog"""
    
    def _get_json_ld_recipe(self) -> Optional[dict]:
        """
        Извлечение данных рецепта из JSON-LD
        
        Returns:
            dict: Данные рецепта из JSON-LD или None
        """
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
                
                # Ищем рецепт в данных
                recipe_data = None
                
                # Проверяем @graph (Yoast SEO)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if is_recipe(item):
                            recipe_data = item
                            break
                # Проверяем список
                elif isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            recipe_data = item
                            break
                # Проверяем прямой объект
                elif isinstance(data, dict) and is_recipe(data):
                    recipe_data = data
                
                if recipe_data:
                    return recipe_data
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из HTML (WP Recipe Maker)
        recipe_name = self.soup.find('h2', class_='wprm-recipe-name')
        if recipe_name:
            return self.clean_text(recipe_name.get_text())
        
        # Альтернативно - из JSON-LD
        json_ld = self._get_json_ld_recipe()
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в HTML (WP Recipe Maker)
        summary = self.soup.find('div', class_='wprm-recipe-summary')
        if summary:
            return self.clean_text(summary.get_text())
        
        # Альтернативно - из JSON-LD
        json_ld = self._get_json_ld_recipe()
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов с разбором на name, amount, unit
        Использует HTML WP Recipe Maker для структурированных данных
        """
        ingredients = []
        
        # Ищем контейнер с ингредиентами (WP Recipe Maker)
        ingredients_container = self.soup.find('div', class_='wprm-recipe-ingredients-container')
        
        if ingredients_container:
            # Находим все элементы ингредиентов
            ingredient_items = ingredients_container.find_all('li', class_='wprm-recipe-ingredient')
            
            for item in ingredient_items:
                # Извлекаем структурированные данные
                amount_elem = item.find('span', class_='wprm-recipe-ingredient-amount')
                unit_elem = item.find('span', class_='wprm-recipe-ingredient-unit')
                name_elem = item.find('span', class_='wprm-recipe-ingredient-name')
                
                # Получаем значения
                amount = self.clean_text(amount_elem.get_text()) if amount_elem else None
                unit = self.clean_text(unit_elem.get_text()) if unit_elem else None
                name = self.clean_text(name_elem.get_text()) if name_elem else None
                
                # Пропускаем пустые элементы
                if not name:
                    continue
                
                # Создаем словарь ингредиента
                ingredient_dict = {
                    "name": name,
                    "units": unit if unit else None,
                    "amount": amount if amount else None
                }
                
                ingredients.append(ingredient_dict)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем HTML (WP Recipe Maker)
        instructions_container = self.soup.find('div', class_='wprm-recipe-instructions-container')
        
        if instructions_container:
            # Находим все шаги
            step_items = instructions_container.find_all('li', class_='wprm-recipe-instruction')
            
            for item in step_items:
                # Извлекаем текст инструкции
                text_elem = item.find('div', class_='wprm-recipe-instruction-text')
                if text_elem:
                    step_text = self.clean_text(text_elem.get_text())
                    if step_text:
                        steps.append(step_text)
        
        # Если HTML не помог, пробуем JSON-LD
        if not steps:
            json_ld = self._get_json_ld_recipe()
            if json_ld and 'recipeInstructions' in json_ld:
                instructions = json_ld['recipeInstructions']
                if isinstance(instructions, list):
                    for step in instructions:
                        if isinstance(step, dict) and 'text' in step:
                            steps.append(self.clean_text(step['text']))
                        elif isinstance(step, str):
                            steps.append(self.clean_text(step))
        
        if steps:
            # Добавляем нумерацию если её нет
            if not re.match(r'^\d+\.', steps[0]):
                steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
            return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем из JSON-LD
        json_ld = self._get_json_ld_recipe()
        if json_ld and 'recipeCategory' in json_ld:
            category = json_ld['recipeCategory']
            if isinstance(category, list):
                return ', '.join(category)
            return self.clean_text(str(category))
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты или читаемый формат
        
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
        
        # Форматируем вывод
        result = []
        if hours > 0:
            result.append(f"{hours} hour" + ("s" if hours > 1 else ""))
        if minutes > 0:
            result.append(f"{minutes} minute" + ("s" if minutes > 1 else ""))
        
        return ' '.join(result) if result else None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Маппинг типов времени
        time_classes = {
            'prep': 'wprm-recipe-prep_time',
            'cook': 'wprm-recipe-cook_time',
            'total': 'wprm-recipe-total_time'
        }
        
        # Сначала пробуем HTML
        time_class = time_classes.get(time_type)
        if time_class:
            time_elem = self.soup.find('span', class_=time_class)
            if time_elem:
                time_text = self.clean_text(time_elem.get_text())
                if time_text:
                    return time_text
        
        # Альтернативно - из JSON-LD
        json_ld = self._get_json_ld_recipe()
        if json_ld:
            time_keys = {
                'prep': 'prepTime',
                'cook': 'cookTime',
                'total': 'totalTime'
            }
            
            key = time_keys.get(time_type)
            if key and key in json_ld:
                iso_time = json_ld[key]
                return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('total')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с заметками (WP Recipe Maker)
        notes_container = self.soup.find('div', class_='wprm-recipe-notes-container')
        
        if notes_container:
            # Извлекаем текст без заголовка
            notes_div = notes_container.find('div', class_='wprm-recipe-notes')
            if notes_div:
                # Проверяем, есть ли список заметок
                note_items = notes_div.find_all('li')
                if note_items:
                    # Объединяем элементы списка
                    notes = []
                    for item in note_items:
                        note_text = self.clean_text(item.get_text())
                        if note_text:
                            notes.append(note_text)
                    return ' '.join(notes) if notes else None
                else:
                    # Просто текст
                    text = self.clean_text(notes_div.get_text())
                    return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Пробуем из JSON-LD
        json_ld = self._get_json_ld_recipe()
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if isinstance(keywords, str):
                # Разделяем по запятой
                tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            elif isinstance(keywords, list):
                tags = keywords
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Сначала пробуем из HTML (WP Recipe Maker)
        recipe_image = self.soup.find('div', class_='wprm-recipe-image')
        if recipe_image:
            img = recipe_image.find('img')
            if img and img.get('src'):
                urls.append(img['src'])
        
        # Дополнительно из JSON-LD
        json_ld = self._get_json_ld_recipe()
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                if img not in urls:
                    urls.append(img)
            elif isinstance(img, list):
                for url in img:
                    if isinstance(url, str) and url not in urls:
                        urls.append(url)
            elif isinstance(img, dict):
                if 'url' in img and img['url'] not in urls:
                    urls.append(img['url'])
                elif 'contentUrl' in img and img['contentUrl'] not in urls:
                    urls.append(img['contentUrl'])
        
        # Также проверяем meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)
        
        return ','.join(urls) if urls else None
    
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
            "instructions": self.extract_steps(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """
    Точка входа для обработки HTML файлов foodandmood.blog
    """
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join("preprocessed", "foodandmood_blog")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(FoodAndMoodExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python foodandmood_blog.py")


if __name__ == "__main__":
    main()
