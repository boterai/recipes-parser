"""
Экстрактор данных рецептов для сайта recipe.ajinomoto.co.th

Этот модуль реализует парсер для извлечения структурированных данных рецептов
с тайского кулинарного сайта recipe.ajinomoto.co.th.

Стратегия извлечения данных:
1. JSON-LD (schema.org Recipe) - для базовой структуры (название, категория, изображения)
2. HTML <p> теги - для полного списка ингредиентов (JSON-LD часто содержит неполный список)
3. HTML <ol>/<li> - для инструкций по приготовлению

Особенности реализации:
- Поддержка тайских единиц измерения (กรัม, มิลลิลิตร, ช้อนชา, ช้อนโต๊ะ)
- Парсинг дробных количеств (1 1/2, 1/2)
- Извлечение всех ингредиентов из HTML для полноты данных
- Возвращает JSON-строку для поля ingredients (список словарей с name/units/amount)

Использование:
    extractor = RecipeAjinomotoCoThExtractor('path/to/recipe.html')
    data = extractor.extract_all()  # Возвращает словарь с 11 обязательными полями
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class RecipeAjinomotoCoThExtractor(BaseRecipeExtractor):
    """Экстрактор для recipe.ajinomoto.co.th"""
    
    def __init__(self, html_path: str):
        super().__init__(html_path)
        self.json_ld_data = self._extract_json_ld()
    
    def _extract_json_ld(self) -> Optional[dict]:
        """Извлечение JSON-LD структурированных данных"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, AttributeError):
                continue
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пытаемся из JSON-LD
        if self.json_ld_data and 'name' in self.json_ld_data:
            name = self.json_ld_data['name']
            if name:
                return self.clean_text(name)
        
        # Альтернативно - из заголовка страницы
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        dish_name = self.extract_dish_name()
        
        # Из meta description (приоритет - обычно более развернутое)
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            if desc and desc != dish_name:
                return desc
        
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = self.clean_text(og_desc['content'])
            if desc and desc != dish_name:
                return desc
        
        # Из JSON-LD (последний приоритет, часто дублирует название)
        if self.json_ld_data and 'description' in self.json_ld_data:
            desc = self.json_ld_data['description']
            if desc and desc != dish_name:
                return self.clean_text(desc)
        
        return None
    
    def parse_ingredient_string(self, ingredient_str: str) -> Dict[str, any]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_str: строка вида "น้ำ  250 มิลลิลิตร" или "ผงชูรส อายิโนะโมะโต๊ะ  1 1/2 ช้อนชา"
        
        Returns:
            Словарь с полями name, amount, units
        """
        ingredient_str = self.clean_text(ingredient_str)
        
        # Паттерн для извлечения: название, количество, единицы
        # Количество может быть: число, дробь, число с дробью (1 1/2), десятичное
        pattern = r'^(.+?)\s+([0-9.\/\s]+)\s+(.+)$'
        match = re.match(pattern, ingredient_str)
        
        if match:
            name = self.clean_text(match.group(1))
            amount_str = self.clean_text(match.group(2))
            units = self.clean_text(match.group(3))
            
            # Конвертируем amount в число
            amount = self._parse_amount(amount_str)
            
            return {
                "name": name,
                "units": units,
                "amount": amount
            }
        
        # Если не удалось распарсить, возвращаем как есть
        return {
            "name": ingredient_str,
            "units": "",
            "amount": 0
        }
    
    def _parse_amount(self, amount_str: str) -> float:
        """Парсинг количества (поддержка дробей типа '1 1/2')"""
        amount_str = amount_str.strip()
        
        # Проверяем на дробь с целой частью (1 1/2)
        mixed_fraction = re.match(r'(\d+)\s+(\d+)/(\d+)', amount_str)
        if mixed_fraction:
            whole = int(mixed_fraction.group(1))
            numerator = int(mixed_fraction.group(2))
            denominator = int(mixed_fraction.group(3))
            return whole + (numerator / denominator)
        
        # Простая дробь (1/2)
        simple_fraction = re.match(r'(\d+)/(\d+)', amount_str)
        if simple_fraction:
            numerator = int(simple_fraction.group(1))
            denominator = int(simple_fraction.group(2))
            return numerator / denominator
        
        # Десятичное число или целое
        try:
            return float(amount_str)
        except ValueError:
            return 0
    
    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов
        
        Returns:
            JSON-строка со списком ингредиентов
        """
        ingredients = []
        ingredients_text_set = set()  # Для избежания дубликатов
        
        # Стратегия 1: Извлекаем из JSON-LD (обычно неполный список)
        if self.json_ld_data and 'recipeIngredient' in self.json_ld_data:
            raw_ingredients = self.json_ld_data['recipeIngredient']
            
            for ingredient_str in raw_ingredients:
                parsed = self.parse_ingredient_string(ingredient_str)
                # Добавляем только если еще не было
                if parsed['name'] not in ingredients_text_set:
                    ingredients.append(parsed)
                    ingredients_text_set.add(parsed['name'])
        
        # Стратегия 2: Ищем в HTML <p> тегах (часто полный список)
        # Паттерн: текст с числом и единицей измерения
        p_tags = self.soup.find_all('p')
        for p in p_tags:
            text = p.get_text(strip=True)
            # Проверяем, соответствует ли паттерну ингредиента
            # (текст + число + тайская единица измерения)
            if re.search(r'.+\s+\d+(?:\s+\d+/\d+)?\s+(กรัม|มิลลิลิตร|ช้อนชา|ช้อนโต๊ะ|เม็ด|ลิตร)', text):
                parsed = self.parse_ingredient_string(text)
                # Добавляем только если еще не было
                if parsed['name'] not in ingredients_text_set:
                    ingredients.append(parsed)
                    ingredients_text_set.add(parsed['name'])
        
        if ingredients:
            # Возвращаем как JSON-строку
            return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        instructions = []
        
        # Ищем в JSON-LD
        if self.json_ld_data and 'recipeInstructions' in self.json_ld_data:
            recipe_instructions = self.json_ld_data['recipeInstructions']
            
            # recipeInstructions может быть строкой или списком
            if isinstance(recipe_instructions, str):
                instructions.append(self.clean_text(recipe_instructions))
            elif isinstance(recipe_instructions, list):
                for instruction in recipe_instructions:
                    if isinstance(instruction, str):
                        instructions.append(self.clean_text(instruction))
                    elif isinstance(instruction, dict):
                        # HowToStep или HowToSection
                        if 'text' in instruction:
                            instructions.append(self.clean_text(instruction['text']))
        
        # Альтернативно ищем в HTML
        if not instructions:
            # Ищем списки с инструкциями (как ol, так и ul)
            instruction_lists = self.soup.find_all(['ol', 'ul'])
            for lst in instruction_lists:
                items = lst.find_all('li', recursive=False)
                if items:
                    # Проверяем, похожи ли элементы на инструкции
                    # (начинаются с числа или содержат кулинарные глаголы)
                    potential_instructions = []
                    for item in items:
                        text = self.clean_text(item.get_text())
                        if text:
                            # Проверяем, начинается ли с номера шага (1., 2., и т.д.)
                            if re.match(r'^\d+\.', text):
                                potential_instructions.append(text)
                            # Или содержит тайские кулинарные глаголы
                            elif any(verb in text for verb in ['ต้ม', 'ตั้ง', 'ตัก', 'ใส่', 'ผัด', 'หั่น', 'คน', 'เติม']):
                                potential_instructions.append(text)
                    
                    # Если нашли хотя бы 2 инструкции, считаем это списком инструкций
                    if len(potential_instructions) >= 2:
                        instructions = potential_instructions
                        break  # Берем только первый подходящий список
        
        if instructions:
            # Объединяем шаги в одну строку
            # Проверяем, есть ли уже нумерация в первой инструкции
            if instructions and re.match(r'^\d+\.', instructions[0]):
                # Уже есть нумерация, просто объединяем
                return ' '.join(instructions)
            else:
                # Добавляем нумерацию
                return ' '.join(f"{i+1}. {instr}" for i, instr in enumerate(instructions))
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Из JSON-LD
        if self.json_ld_data:
            # Проверяем recipeCategory
            if 'recipeCategory' in self.json_ld_data:
                category = self.json_ld_data['recipeCategory']
                if category:
                    # Убираем префикс "เมนู " (меню)
                    category = re.sub(r'^เมนู\s+', '', category)
                    return self.clean_text(category)
            
            # Проверяем recipeCuisine
            if 'recipeCuisine' in self.json_ld_data:
                cuisine = self.json_ld_data['recipeCuisine']
                if cuisine:
                    cuisine = re.sub(r'^เมนู\s+', '', cuisine)
                    return self.clean_text(cuisine)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        if self.json_ld_data and 'prepTime' in self.json_ld_data:
            prep_time = self.json_ld_data['prepTime']
            if prep_time:
                return self.clean_text(prep_time)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        if self.json_ld_data and 'cookTime' in self.json_ld_data:
            cook_time = self.json_ld_data['cookTime']
            if cook_time:
                return self.clean_text(cook_time)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        if self.json_ld_data and 'totalTime' in self.json_ld_data:
            total_time = self.json_ld_data['totalTime']
            if total_time:
                return self.clean_text(total_time)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок к рецепту"""
        # В данном сайте нет явных заметок в примерах
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта"""
        # Используем category как тег
        category = self.extract_category()
        if category:
            return category
        
        # Альтернативно - из keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Из JSON-LD
        if self.json_ld_data and 'image' in self.json_ld_data:
            image_data = self.json_ld_data['image']
            
            if isinstance(image_data, str):
                urls.append(image_data)
            elif isinstance(image_data, list):
                urls.extend(image_data)
            elif isinstance(image_data, dict):
                if 'url' in image_data:
                    urls.append(image_data['url'])
        
        # Дополнительно ищем og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)
        
        # Убираем дубликаты
        unique_urls = []
        seen = set()
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        if unique_urls:
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
    """Обработка директории с примерами"""
    import os
    
    # Путь к директории с примерами
    recipes_dir = os.path.join("preprocessed", "recipe_ajinomoto_co_th")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(RecipeAjinomotoCoThExtractor, recipes_dir)
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python recipe_ajinomoto_co_th.py")


if __name__ == "__main__":
    main()
