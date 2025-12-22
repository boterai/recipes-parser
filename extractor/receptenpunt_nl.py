"""
Экстрактор данных рецептов для сайта receptenpunt.nl
Извлекает данные рецептов из HTML-страниц сайта https://receptenpunt.nl/
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ReceptenpuntNlExtractor(BaseRecipeExtractor):
    """
    Экстрактор для receptenpunt.nl
    
    Извлекает данные рецептов с голландского сайта receptenpunt.nl,
    используя JSON-LD структурированные данные и HTML-парсинг.
    """
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Проверяем @graph структуру
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                
                # Данные могут быть списком
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            item_type = item.get('@type', '')
                            if isinstance(item_type, list) and 'Recipe' in item_type:
                                return item
                            elif item_type == 'Recipe':
                                return item
                
                # Или прямой объект Recipe
                elif isinstance(data, dict):
                    item_type = data.get('@type', '')
                    if isinstance(item_type, list) and 'Recipe' in item_type:
                        return data
                    elif item_type == 'Recipe':
                        return data
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT2H30M"
            
        Returns:
            Время в формате "{total_minutes} minutes", например "30 minutes" или "150 minutes"
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
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "600 gram rundergehakt" или "2 wortels"
            
        Returns:
            dict: {"name": "rundergehakt", "amount": 600, "unit": "gram"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Удаляем HTML entities
        text = re.sub(r'&amp;', '&', text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "600 gram rundergehakt", "2 wortels", "1,5 kilo uien"
        pattern = r'^([\d\s/.,]+)?\s*(gram|kilo|kg|ml|liter|l|eetlepels?|theelepels?|eetlepel|theelepel|takjes?|stokjes?|stuk|stuks)?(?:\s+)?(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Заменяем запятую на точку для чисел
            amount_str = amount_str.replace(',', '.')
            
            # Пытаемся конвертировать в число (int или float)
            try:
                # Пробуем сначала int
                if '.' not in amount_str:
                    amount = int(amount_str)
                else:
                    # Если есть точка, используем float, но если дробная часть .0, то int
                    float_val = float(amount_str)
                    if float_val.is_integer():
                        amount = int(float_val)
                    else:
                        amount = float_val
            except ValueError:
                # Если не получилось конвертировать, оставляем как строку
                amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        if name:
            # Удаляем содержимое в скобках
            name = re.sub(r'\([^)]*\)', '', name)
            # Удаляем лишние пробелы
            name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из HTML структуры"""
        ingredients = []
        
        # Ищем список ингредиентов
        ingredient_section = self.soup.find('div', class_='tasty-recipes-ingredients')
        
        if ingredient_section:
            # Извлекаем элементы списка
            items = ingredient_section.find_all('li')
            
            for item in items:
                # Извлекаем текст ингредиента (пропускаем checkbox)
                # Убираем checkbox элементы
                checkbox_span = item.find('span', class_='tr-ingredient-checkbox-container')
                if checkbox_span:
                    checkbox_span.decompose()
                
                ingredient_text = item.get_text(strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                # Парсим в структурированный формат
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    # Используем формат: name, units, amount (как в эталонных JSON)
                    ingredients.append({
                        "name": parsed["name"],
                        "units": parsed["unit"],
                        "amount": parsed["amount"]
                    })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        if step_text:
                            steps.append(step_text)
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        if step_text:
                            steps.append(step_text)
            
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # receptenpunt.nl обычно не предоставляет nutrition info в JSON-LD
        # Можно попробовать поискать в HTML, но пока вернем None
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        json_ld = self._get_json_ld_data()
        
        if json_ld:
            # Проверяем recipeCategory
            if 'recipeCategory' in json_ld:
                category = json_ld['recipeCategory']
                if category:
                    return self.clean_text(category)
            
            # Альтернативно проверяем recipeCuisine
            if 'recipeCuisine' in json_ld:
                cuisine = json_ld['recipeCuisine']
                if cuisine:
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
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями
        notes_section = self.soup.find('div', class_='tasty-recipes-notes-body')
        
        if notes_section:
            # Извлекаем текст
            text = notes_section.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if keywords:
                # keywords могут быть строкой с разделителями
                if isinstance(keywords, str):
                    # Разделяем по запятой и очищаем
                    tags = [self.clean_text(tag) for tag in keywords.split(',')]
                    tags = [tag for tag in tags if tag]
                    return ', '.join(tags)
                elif isinstance(keywords, list):
                    tags = [self.clean_text(tag) for tag in keywords]
                    tags = [tag for tag in tags if tag]
                    return ', '.join(tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'image' in json_ld:
            images = json_ld['image']
            urls = []
            
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
            "instructions": self.extract_steps(),
            "nutrition_info": self.extract_nutrition_info(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Точка входа для обработки директории receptenpunt_nl"""
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join("preprocessed", "receptenpunt_nl")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ReceptenpuntNlExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python receptenpunt_nl.py")


if __name__ == "__main__":
    main()
