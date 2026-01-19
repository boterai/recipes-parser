"""
Экстрактор данных рецептов для сайта coupdepouce.com
"""

import sys
import html as html_module
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CoupDePouceExtractor(BaseRecipeExtractor):
    """Экстрактор для coupdepouce.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты с текстом
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "20 minutes" или "90 minutes"
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
        
        if total_minutes > 0:
            return f"{total_minutes} minutes"
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe' and 'name' in item:
                            return self.clean_text(item['name'])
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe' and 'description' in item:
                            desc = item['description']
                            if desc and desc.strip():
                                # Декодируем HTML entities
                                desc = html_module.unescape(desc)
                                return self.clean_text(desc)
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "3 lb (1,5 kg) de pommes de terre"
            
        Returns:
            dict: {"name": "pommes de terre", "amount": "3", "units": "lb"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерны для извлечения количества и единиц
        # Примеры: "3 lb (1,5 kg) de pommes de terre", "1/2 tasse (125 ml) de mayonnaise"
        
        # Паттерн 1: Число + единица в начале
        # Примеры: "3 lb", "1/2 tasse", "1 c. à soupe"
        pattern1 = r'^([\d\s/.,]+)\s+(lb|kg|g|mg|ml|l|tasse|tasses|c\.\s*à\s*soupe|c\.\s*à\s*thé|brins?|gousse|gousses|petit|petite|gros|grosse|de grosseur moyenne)\s*(?:\([^)]*\))?\s*(?:de|d\'|pour)?\s*(.+)'
        
        match = re.match(pattern1, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                amount_str = amount_str.strip()
                # Обработка дробей типа "1/2"
                if '/' in amount_str:
                    parts = amount_str.split()
                    total = 0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            total += float(part)
                    # Форматируем как дробь если возможно
                    if total == int(total):
                        amount = str(int(total))
                    elif total == 0.5:
                        amount = "1/2"
                    elif total == 0.25:
                        amount = "1/4"
                    elif total == 0.75:
                        amount = "3/4"
                    elif total == 0.33 or total == 1/3:
                        amount = "1/3"
                    else:
                        amount = amount_str
                else:
                    amount = amount_str.replace(',', '.')
            
            # Обработка единицы измерения
            unit = unit.strip() if unit else None
            
            # Очистка названия
            name = re.sub(r'\([^)]*\)', '', name)
            name = re.sub(r'\b(facultatif|au goût|pour la cuisson|pour badigeonner)\b', '', name, flags=re.IGNORECASE)
            name = re.sub(r'[,;]+$', '', name)
            name = re.sub(r'\s+', ' ', name).strip()
            
            if not name or len(name) < 2:
                return None
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        
        # Паттерн 2: Только число в начале (без единицы)
        # Примеры: "6 gros oeufs", "1 petit oignon"
        pattern2 = r'^([\d\s/.,]+)\s+(.+)'
        
        match2 = re.match(pattern2, text, re.IGNORECASE)
        
        if match2:
            amount_str, name = match2.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                amount_str = amount_str.strip()
                if '/' in amount_str:
                    parts = amount_str.split()
                    total = 0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            total += float(part)
                    amount = str(int(total)) if total == int(total) else amount_str
                else:
                    amount = amount_str.replace(',', '.')
            
            # Очистка названия
            name = re.sub(r'\([^)]*\)', '', name)
            name = re.sub(r'\b(facultatif|au goût|pour la cuisson|pour badigeonner)\b', '', name, flags=re.IGNORECASE)
            name = re.sub(r'[,;]+$', '', name)
            name = re.sub(r'\s+', ' ', name).strip()
            
            if not name or len(name) < 2:
                return None
            
            return {
                "name": name,
                "amount": amount,
                "units": None
            }
        
        # Если паттерн не совпал, возвращаем только название
        name = re.sub(r'\([^)]*\)', '', text)
        name = re.sub(r'\b(facultatif|au goût|pour la cuisson|pour badigeonner)\b', '', name, flags=re.IGNORECASE)
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        return {
            "name": name,
            "amount": None,
            "units": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe' and 'recipeIngredient' in item:
                            for ingredient_text in item['recipeIngredient']:
                                # Декодируем HTML entities
                                ingredient_text = html_module.unescape(ingredient_text)
                                parsed = self.parse_ingredient(ingredient_text)
                                if parsed:
                                    ingredients.append(parsed)
                            
                            if ingredients:
                                return json.dumps(ingredients, ensure_ascii=False)
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe' and 'recipeInstructions' in item:
                            instructions = item['recipeInstructions']
                            if isinstance(instructions, list):
                                for step in instructions:
                                    if isinstance(step, dict) and 'text' in step:
                                        # Декодируем HTML entities и удаляем HTML теги
                                        text = html_module.unescape(step['text'])
                                        # Удаляем HTML теги
                                        text = re.sub(r'<[^>]+>', '', text)
                                        text = self.clean_text(text)
                                        if text:
                                            steps.append(text)
                                    elif isinstance(step, str):
                                        text = self.clean_text(step)
                                        if text:
                                            steps.append(text)
                            
                            if steps:
                                return ' '.join(steps)
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории из хлебных крошек"""
        # Извлекаем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BreadcrumbList' and 'itemListElement' in item:
                            elements = item['itemListElement']
                            # Берем последний элемент (не считая сам рецепт)
                            # Обычно это категория типа "Entrées et accompagnements"
                            if len(elements) >= 3:
                                category_item = elements[-1]
                                if 'name' in category_item:
                                    category = category_item['name']
                                    # Переводим на английский для консистентности
                                    category_map = {
                                        'Entrées et accompagnements': 'Side Dish',
                                        'Plat principal': 'Main Course',
                                        'Plats principaux': 'Main Course',
                                        'Desserts': 'Dessert',
                                        'Petit-déjeuner': 'Breakfast',
                                        'Ingrédients': 'Main Course',  # Если последняя - ингредиент (как яйца)
                                        'Oeufs': 'Main Course'
                                    }
                                    return category_map.get(category, category)
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe' and 'prepTime' in item:
                            return self.parse_iso_duration(item['prepTime'])
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe' and 'cookTime' in item:
                            return self.parse_iso_duration(item['cookTime'])
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe' and 'totalTime' in item:
                            return self.parse_iso_duration(item['totalTime'])
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок (notes не найдены в JSON-LD для coupdepouce.com)"""
        # На сайте coupdepouce.com не обнаружено поле с заметками в доступных примерах
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов (если доступны)"""
        # В примерах есть только в одном файле, где теги заданы вручную
        # Попробуем извлечь из meta keywords или других источников
        # Но в HTML примерах таких данных нет, поэтому возвращаем None
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Извлекаем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe' and 'image' in item:
                            images = item['image']
                            if isinstance(images, list):
                                urls.extend(images)
                            elif isinstance(images, str):
                                urls.append(images)
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            # Возвращаем как строку через запятую
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
            "tags": self.extract_tags()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/coupdepouce_com
    recipes_dir = os.path.join("preprocessed", "coupdepouce_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(CoupDePouceExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python coupdepouce_com.py")


if __name__ == "__main__":
    main()
