"""
Экстрактор данных рецептов для сайта coop.se
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CoopSeExtractor(BaseRecipeExtractor):
    """Экстрактор для coop.se"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "P0Y0M0DT0H35M0S" или "PT35M"
            
        Returns:
            Время в формате "35 min", "1 h 30 min", etc.
        """
        if not duration:
            return None
        
        # Extract time portion after T
        if 'T' in duration:
            time_part = duration.split('T')[1]
        else:
            return None
        
        hours = 0
        minutes = 0
        
        # Извлекаем часы
        hour_match = re.search(r'(\d+)H', time_part)
        if hour_match:
            hours = int(hour_match.group(1))
        
        # Извлекаем минуты
        min_match = re.search(r'(\d+)M', time_part)
        if min_match:
            minutes = int(min_match.group(1))
        
        # Формируем строку в формате "X minutes" или "X min"
        # (оба формата встречаются в reference)
        total_minutes = hours * 60 + minutes
        
        if total_minutes > 0:
            return f"{total_minutes} minutes"
        
        return None
    
    def get_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала из JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно из title
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем суффиксы " | Recept - Coop"
            title = re.sub(r'\s*\|\s*Recept.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала из JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Альтернативно из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient_string(self, ingredient_str: str) -> dict:
        """
        Парсинг строки ингредиента из JSON-LD в структурированный формат
        
        Args:
            ingredient_str: Строка вида "600 g kycklinglårfilé" или "2 msk olivolja"
            
        Returns:
            dict: {"name": "kycklinglårfilé", "amount": "600", "unit": "g"}
        """
        if not ingredient_str:
            return {"name": None, "amount": None, "unit": None}
        
        # Чистим текст
        text = self.clean_text(ingredient_str).strip()
        
        # Паттерн 1: количество + единица + название
        # Пример: "600 g kycklinglårfilé", "2 msk olivolja"
        pattern_with_unit = r'^([\d\s/.,]+)?\s*\b(g|kg|ml|dl|l|msk|matsked|matskedar|tsk|tesked|teskedar|st|krm)\b\.?\s+(.+)$'
        match = re.match(pattern_with_unit, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount = self._parse_amount(amount_str)
            
            # Обработка единицы измерения - НЕ нормализуем, оставляем как есть
            unit = unit.strip() if unit else None
            
            # Очистка названия - НЕ удаляем описания после запятой
            name = re.sub(r'\s+', ' ', name).strip()
            
            if name and len(name) >= 2:
                return {
                    "name": name,
                    "amount": amount,
                    "unit": unit
                }
        
        # Паттерн 2: количество + название (без единицы)
        # Пример: "1  gul lök, finhackad", "2  morötter, grovt rivna"
        pattern_no_unit = r'^([\d\s/.,]+)\s+(.+)$'
        match = re.match(pattern_no_unit, text, re.IGNORECASE)
        
        if match:
            amount_str, name = match.groups()
            
            # Проверяем, что название не начинается с единицы измерения
            # (чтобы не матчить "250 g nötfärs" как "250" + "g nötfärs")
            name_words = name.split()
            if name_words and name_words[0].lower() not in ['g', 'kg', 'ml', 'dl', 'l', 'msk', 'matsked', 'matskedar', 'tsk', 'tesked', 'teskedar', 'st', 'krm']:
                amount = self._parse_amount(amount_str)
                name = re.sub(r'\s+', ' ', name).strip()
                
                if name and len(name) >= 2:
                    return {
                        "name": name,
                        "amount": amount,
                        "unit": None
                    }
        
        # Если ничего не совпало, возвращаем только название
        return {
            "name": text,
            "amount": None,
            "unit": None
        }
    
    def _parse_amount(self, amount_str: str) -> Optional[float]:
        """Helper to parse amount string to number"""
        if not amount_str:
            return None
        
        amount_clean = amount_str.strip().replace(',', '.')
        # Handle fractions like "1/2" or " 1/2"
        if '/' in amount_clean:
            parts = amount_clean.strip().split()
            total = 0.0
            for part in parts:
                part = part.strip()
                if '/' in part:
                    num, denom = part.split('/')
                    total += float(num) / float(denom)
                elif part:
                    total += float(part)
            return total if total != int(total) else int(total)
        else:
            try:
                # Try to parse as int first
                if '.' not in amount_clean:
                    return int(amount_clean)
                else:
                    # Parse as float
                    val = float(amount_clean)
                    return val if val != int(val) else int(val)
            except ValueError:
                # If parsing fails, return None
                return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        # Извлекаем из JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredients_list = recipe_data['recipeIngredient']
            
            # Парсим каждый ингредиент
            parsed_ingredients = []
            for ingredient_str in ingredients_list:
                parsed = self.parse_ingredient_string(ingredient_str)
                if parsed and parsed.get('name'):
                    # Используем формат из примера: units вместо unit
                    parsed_ingredients.append({
                        "name": parsed['name'],
                        "units": parsed['unit'],
                        "amount": parsed['amount']
                    })
            
            if parsed_ingredients:
                return json.dumps(parsed_ingredients, ensure_ascii=False)
        
        # Fallback: ищем в HTML (список с классом List--section)
        ingredient_list = self.soup.find('ul', class_=lambda c: c and 'List--section' in c)
        if ingredient_list:
            items = ingredient_list.find_all('li')
            parsed_ingredients = []
            
            for item in items:
                text = item.get_text(strip=True)
                parsed = self.parse_ingredient_string(text)
                if parsed and parsed.get('name'):
                    parsed_ingredients.append({
                        "name": parsed['name'],
                        "units": parsed['unit'],
                        "amount": parsed['amount']
                    })
            
            if parsed_ingredients:
                return json.dumps(parsed_ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Извлекаем из JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions_data = recipe_data['recipeInstructions']
            
            steps = []
            
            # Обрабатываем структуру HowToSection
            if isinstance(instructions_data, list):
                for section in instructions_data:
                    if isinstance(section, dict):
                        # Если это HowToSection с itemListElement
                        if section.get('@type') == 'HowToSection' and 'itemListElement' in section:
                            for step in section['itemListElement']:
                                if isinstance(step, dict) and 'text' in step:
                                    steps.append(self.clean_text(step['text']))
                        # Если это напрямую HowToStep
                        elif section.get('@type') == 'HowToStep' and 'text' in section:
                            steps.append(self.clean_text(section['text']))
                        # Если это просто текст
                        elif 'text' in section:
                            steps.append(self.clean_text(section['text']))
                    elif isinstance(section, str):
                        steps.append(self.clean_text(section))
            
            if steps:
                return ' '.join(steps)
        
        # Fallback: ищем в HTML (списки с классом List--orderedRecipe)
        instruction_lists = self.soup.find_all('ol', class_=lambda c: c and 'List--orderedRecipe' in c)
        if instruction_lists:
            steps = []
            for lst in instruction_lists:
                items = lst.find_all('li')
                for item in items:
                    text = self.clean_text(item.get_text())
                    if text:
                        steps.append(text)
            
            if steps:
                return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # В reference JSON категория не используется для coop.se
        # Возвращаем None, как в примерах
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'totalTime' in recipe_data:
            total = self.parse_iso_duration(recipe_data['totalTime'])
            # Возвращаем total_time как есть из JSON-LD
            # (референсы показывают, что иногда total_time = cook_time)
            return total
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # coop.se обычно не имеет отдельной секции заметок в JSON-LD
        # Можно искать в HTML, но в примерах не видно
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # В примерах нет тегов
        # Можно попробовать извлечь keywords из meta
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Из JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            if isinstance(img, str):
                # Убедимся, что URL полный (добавим https: если нужно)
                if img.startswith('//'):
                    img = 'https:' + img
                urls.append(img)
            elif isinstance(img, list):
                for i in img:
                    if isinstance(i, str):
                        if i.startswith('//'):
                            i = 'https:' + i
                        urls.append(i)
            elif isinstance(img, dict):
                if 'url' in img:
                    url = img['url']
                    if url.startswith('//'):
                        url = 'https:' + url
                    urls.append(url)
        
        # Из meta og:image
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
    import os
    # Обрабатываем папку preprocessed/coop_se
    recipes_dir = os.path.join("preprocessed", "coop_se")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(CoopSeExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python coop_se.py")


if __name__ == "__main__":
    main()
