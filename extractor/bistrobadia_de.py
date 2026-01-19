"""
Экстрактор данных рецептов для сайта bistrobadia.de
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class BistroBadiaExtractor(BaseRecipeExtractor):
    """Экстрактор для bistrobadia.de"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Данные могут быть в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                
                # Или напрямую как Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
                # Или в списке
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                        
            except (json.JSONDecodeError, KeyError):
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
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Fallback: ищем в HTML
        title_tag = self.soup.find('h1')
        if title_tag:
            return self.clean_text(title_tag.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
        # Fallback: ищем в мета-тегах
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        json_ld = self._get_json_ld_data()
        
        if not json_ld or 'recipeIngredient' not in json_ld:
            return None
        
        ingredients_list = []
        raw_ingredients = json_ld['recipeIngredient']
        
        if not isinstance(raw_ingredients, list):
            return None
        
        for ingredient_str in raw_ingredients:
            if not ingredient_str:
                continue
            
            # Парсим строку ингредиента
            parsed = self.parse_ingredient(ingredient_str)
            if parsed:
                ingredients_list.append(parsed)
        
        return json.dumps(ingredients_list, ensure_ascii=False) if ingredients_list else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "50 g Butter" или "1 Zwiebel"
            
        Returns:
            dict: {"name": "Butter", "amount": "50", "unit": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "50 g Butter", "100 ml Vollmilch", "1 Ei (M)", "Salz, Pfeffer"
        # Количество может быть: "50", "1", "1-2", "10 "
        pattern = r'^([\d\s/.,\-]+)?\s*(g|kg|ml|l|Esslöffel|Teelöffel|Tasse|M|Prise|Stück|Scheibe|Zehe)?\s*(.+)'
        
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
            # Обрабатываем диапазоны типа "1-2"
            if '-' in amount_str and not amount_str.startswith('-'):
                # Берем первое значение из диапазона
                amount = amount_str.split('-')[0].strip()
            else:
                amount = amount_str.replace(',', '.')
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым (например, "(M)", "(10% Fett)")
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем лишние запятые и пробелы
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount if amount else None,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
        if not json_ld or 'recipeInstructions' not in json_ld:
            return None
        
        instructions = json_ld['recipeInstructions']
        steps = []
        step_counter = 1
        
        if isinstance(instructions, list):
            for item in instructions:
                if isinstance(item, dict):
                    # Может быть HowToSection с itemListElement
                    if item.get('@type') == 'HowToSection' and 'itemListElement' in item:
                        for step in item['itemListElement']:
                            if isinstance(step, dict) and 'text' in step:
                                step_text = self.clean_text(step['text'])
                                if step_text:
                                    steps.append(f"{step_counter}. {step_text}")
                                    step_counter += 1
                    # Или просто HowToStep
                    elif item.get('@type') == 'HowToStep' and 'text' in item:
                        step_text = self.clean_text(item['text'])
                        if step_text:
                            steps.append(f"{step_counter}. {step_text}")
                            step_counter += 1
                    # Или у элемента есть просто text
                    elif 'text' in item:
                        step_text = self.clean_text(item['text'])
                        if step_text:
                            steps.append(f"{step_counter}. {step_text}")
                            step_counter += 1
                elif isinstance(item, str):
                    step_text = self.clean_text(item)
                    if step_text:
                        steps.append(f"{step_counter}. {step_text}")
                        step_counter += 1
        elif isinstance(instructions, str):
            return self.clean_text(instructions)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        json_ld = self._get_json_ld_data()
        
        if not json_ld:
            return None
        
        # Проверяем recipeCategory
        if 'recipeCategory' in json_ld:
            category = json_ld['recipeCategory']
            if isinstance(category, list):
                # Берем первую категорию или объединяем
                return category[0] if category else None
            elif isinstance(category, str):
                return self.clean_text(category)
        
        # Проверяем recipeCuisine как альтернативу
        if 'recipeCuisine' in json_ld:
            cuisine = json_ld['recipeCuisine']
            if isinstance(cuisine, list):
                return cuisine[0] if cuisine else None
            elif isinstance(cuisine, str):
                return self.clean_text(cuisine)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        # Если totalTime нет, вычисляем как сумму prep + cook
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep and cook:
            # Извлекаем минуты из строк
            prep_mins = self._extract_minutes(prep)
            cook_mins = self._extract_minutes(cook)
            
            if prep_mins is not None and cook_mins is not None:
                total_mins = prep_mins + cook_mins
                hours = total_mins // 60
                minutes = total_mins % 60
                
                parts = []
                if hours > 0:
                    parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
                if minutes > 0:
                    parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
                
                return ' '.join(parts) if parts else None
        
        return None
    
    def _extract_minutes(self, time_str: str) -> Optional[int]:
        """Извлекает общее количество минут из строки времени"""
        if not time_str:
            return None
        
        total_minutes = 0
        
        # Извлекаем часы
        hour_match = re.search(r'(\d+)\s*hour', time_str)
        if hour_match:
            total_minutes += int(hour_match.group(1)) * 60
        
        # Извлекаем минуты
        min_match = re.search(r'(\d+)\s*minute', time_str)
        if min_match:
            total_minutes += int(min_match.group(1))
        
        return total_minutes if total_minutes > 0 else None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # На bistrobadia.de notes обычно нет в JSON-LD
        # Можно попробовать поискать в HTML, но для соответствия примерам вернем None
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if isinstance(keywords, str):
                return self.clean_text(keywords)
            elif isinstance(keywords, list):
                return ', '.join([self.clean_text(k) for k in keywords if k])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        json_ld = self._get_json_ld_data()
        
        urls = []
        
        if json_ld and 'image' in json_ld:
            images = json_ld['image']
            
            if isinstance(images, str):
                urls.append(images)
            elif isinstance(images, list):
                for img in images:
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, dict):
                        if 'url' in img:
                            urls.append(img['url'])
                        elif 'contentUrl' in img:
                            urls.append(img['contentUrl'])
            elif isinstance(images, dict):
                if 'url' in images:
                    urls.append(images['url'])
                elif 'contentUrl' in images:
                    urls.append(images['contentUrl'])
        
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
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "bistrobadia_de")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(BistroBadiaExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python bistrobadia_de.py")


if __name__ == "__main__":
    main()
