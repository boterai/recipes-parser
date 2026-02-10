"""
Экстрактор данных рецептов для сайта happykitchen.co.il
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class HappyKitchenExtractor(BaseRecipeExtractor):
    """Экстрактор для happykitchen.co.il"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe' and 'name' in item:
                            return self.clean_text(item['name'])
                
                # Проверяем напрямую
                elif data.get('@type') == 'Recipe' and 'name' in data:
                    return self.clean_text(data['name'])
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - ищем в HTML
        recipe_name = self.soup.find('h2', class_='wprm-recipe-name')
        if recipe_name:
            return self.clean_text(recipe_name.get_text())
        
        # Из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        # Ищем в HTML
        recipe_summary = self.soup.find('div', class_='wprm-recipe-summary')
        if recipe_summary:
            return self.clean_text(recipe_summary.get_text())
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем структурированные ингредиенты с классом wprm-recipe-ingredient
        ingredient_items = self.soup.find_all(class_='wprm-recipe-ingredient')
        
        for item in ingredient_items:
            # Извлекаем структурированные данные
            amount_elem = item.find(class_='wprm-recipe-ingredient-amount')
            unit_elem = item.find(class_='wprm-recipe-ingredient-unit')
            name_elem = item.find(class_='wprm-recipe-ingredient-name')
            
            # Получаем значения
            amount = None
            unit = None
            name = None
            
            if amount_elem:
                amount_text = self.clean_text(amount_elem.get_text())
                # Попытка преобразовать в число
                try:
                    # Удаляем пробелы и заменяем запятую на точку
                    amount_clean = amount_text.replace(' ', '').replace(',', '.')
                    # Если это диапазон вида "2-4", оставляем как строку
                    if '-' in amount_clean or '/' in amount_clean:
                        amount = amount_text
                    else:
                        # Пробуем преобразовать в число
                        amount_num = float(amount_clean)
                        # Если это целое число, возвращаем int
                        if amount_num.is_integer():
                            amount = int(amount_num)
                        else:
                            amount = amount_num
                except (ValueError, AttributeError):
                    amount = amount_text if amount_text else None
            elif unit_elem:
                # Если есть единица измерения но нет количества, подразумеваем 1
                amount = 1
            
            if unit_elem:
                unit = self.clean_text(unit_elem.get_text())
            
            if name_elem:
                name = self.clean_text(name_elem.get_text())
            
            # Добавляем ингредиент в список
            if name:  # Название обязательно должно быть
                ingredients.append({
                    "name": name,
                    "units": unit,
                    "amount": amount
                })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем @graph
                recipe_data = None
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            recipe_data = item
                            break
                elif data.get('@type') == 'Recipe':
                    recipe_data = data
                
                if recipe_data and 'recipeInstructions' in recipe_data:
                    recipe_instructions = recipe_data['recipeInstructions']
                    
                    # Обработка инструкций
                    if isinstance(recipe_instructions, list):
                        for section in recipe_instructions:
                            if isinstance(section, dict):
                                # HowToSection со списком шагов
                                if section.get('@type') == 'HowToSection':
                                    steps_list = section.get('itemListElement', [])
                                    for step in steps_list:
                                        if isinstance(step, dict) and 'text' in step:
                                            instructions.append(self.clean_text(step['text']))
                                # HowToStep напрямую
                                elif section.get('@type') == 'HowToStep' and 'text' in section:
                                    instructions.append(self.clean_text(section['text']))
                            elif isinstance(section, str):
                                instructions.append(self.clean_text(section))
                    
                    if instructions:
                        return ' '.join(instructions)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, ищем в HTML
        instruction_containers = self.soup.find_all(class_='wprm-recipe-instruction-text')
        
        for container in instruction_containers:
            text = container.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            if text:
                instructions.append(text)
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в HTML
        course_elem = self.soup.find('span', class_='wprm-recipe-course')
        if course_elem:
            return self.clean_text(course_elem.get_text())
        
        # Ищем в meta-тегах
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в category links
        category_links = self.soup.find_all('a', rel='category tag')
        if category_links:
            # Проверяем есть ли категория, связанная с десертами
            categories = [self.clean_text(link.get_text()) for link in category_links]
            # Для сайта happykitchen основные категории - если есть "עוגיות" значит это Dessert
            if any('עוגיות' in cat for cat in categories):
                return 'Dessert'
        
        # По умолчанию возвращаем "Dessert" для десертов (можно определить по тегам)
        tags = self.extract_tags()
        if tags and any(word in tags for word in ['עוגיות', 'cookie', 'dessert', 'десерт']):
            return 'Dessert'
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                recipe_data = None
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            recipe_data = item
                            break
                elif data.get('@type') == 'Recipe':
                    recipe_data = data
                
                if recipe_data:
                    # Маппинг типов времени
                    time_keys = {
                        'prep': 'prepTime',
                        'cook': 'cookTime',
                        'total': 'totalTime'
                    }
                    
                    key = time_keys.get(time_type)
                    if key and key in recipe_data:
                        iso_time = recipe_data[key]
                        # Парсим ISO 8601 duration (например, "PT1H" или "PT30M")
                        return self.parse_iso_duration(iso_time)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в HTML
        time_class = f'wprm-recipe-{time_type}_time-minutes'
        time_elem = self.soup.find('span', class_=time_class)
        if time_elem:
            minutes = self.clean_text(time_elem.get_text())
            if minutes:
                return f"{minutes} minutes"
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "X minutes"
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
        
        return f"{total_minutes} minutes" if total_minutes > 0 else None
    
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
        """Извлечение заметок"""
        # Ищем в HTML
        notes_container = self.soup.find('div', class_='wprm-recipe-notes')
        if notes_container:
            text = notes_container.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в HTML (anchor elements with rel="tag")
        tag_links = self.soup.find_all('a', rel='tag')
        if tag_links:
            # Извлекаем текст тегов
            tags_list = []
            for link in tag_links:
                tag_text = self.clean_text(link.get_text())
                if tag_text and tag_text not in tags_list:
                    tags_list.append(tag_text)
            
            # Возвращаем через запятую с пробелом
            if tags_list:
                return ', '.join(tags_list)
        
        # Ищем в wprm-recipe-keyword
        keywords_elem = self.soup.find('span', class_='wprm-recipe-keyword')
        if keywords_elem:
            text = self.clean_text(keywords_elem.get_text())
            return text if text else None
        
        # Ищем в meta-тегах
        keywords_meta = self.soup.find('meta', {'name': 'keywords'})
        if keywords_meta and keywords_meta.get('content'):
            return self.clean_text(keywords_meta['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                recipe_data = None
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            recipe_data = item
                            break
                elif data.get('@type') == 'Recipe':
                    recipe_data = data
                
                if recipe_data and 'image' in recipe_data:
                    images = recipe_data['image']
                    if isinstance(images, list):
                        urls.extend([img for img in images if isinstance(img, str)])
                    elif isinstance(images, str):
                        urls.append(images)
                    elif isinstance(images, dict):
                        if 'url' in images:
                            urls.append(images['url'])
                        elif 'contentUrl' in images:
                            urls.append(images['contentUrl'])
                    
                    # Если уже нашли изображения, выходим
                    if urls:
                        break
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если не нашли в JSON-LD, ищем в meta-тегах
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
    """Обработка директории с HTML-файлами"""
    import os
    
    # Обрабатываем папку preprocessed/happykitchen_co_il
    recipes_dir = os.path.join("preprocessed", "happykitchen_co_il")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(HappyKitchenExtractor, recipes_dir)
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python happykitchen_co_il.py")


if __name__ == "__main__":
    main()
