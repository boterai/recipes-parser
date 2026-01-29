"""
Экстрактор данных рецептов для сайта momlovesbaking.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MomLovesBakingExtractor(BaseRecipeExtractor):
    """Экстрактор для momlovesbaking.com"""
    
    def __init__(self, html_path: str):
        """
        Args:
            html_path: Путь к HTML файлу
        """
        super().__init__(html_path)
        self._json_ld_recipe_cache = None  # Кэш для JSON-LD данных
    
    @staticmethod
    def convert_fractions_to_decimal(text: str) -> str:
        """
        Конвертирует Unicode дроби в десятичные числа
        Корректно обрабатывает смешанные числа (например, "1½" -> "1.5")
        """
        if not text:
            return text
        
        # Маппинг дробей
        fraction_map = {
            '½': ' 0.5', '¼': ' 0.25', '¾': ' 0.75',
            '⅓': ' 0.33', '⅔': ' 0.67', '⅛': ' 0.125',
            '⅜': ' 0.375', '⅝': ' 0.625', '⅞': ' 0.875'
        }
        
        # Заменяем каждую дробь на пробел + десятичное число
        # Пробел нужен чтобы "1½" превратилось в "1 0.5", а не "10.5"
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Если получили несколько чисел через пробел, суммируем их
        parts = text.split()
        try:
            total = sum(float(p) for p in parts if p.replace('.', '').replace('-', '').isdigit())
            return str(total) if total != 0 else text
        except (ValueError, AttributeError):
            return text
    
    @staticmethod
    def parse_number(text: str) -> any:
        """
        Парсит текст в число (int или float)
        """
        if not text:
            return None
        
        try:
            # Пытаемся преобразовать в float
            num = float(text)
            # Если это целое число, возвращаем int
            return int(num) if num.is_integer() else num
        except (ValueError, AttributeError):
            return text
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в читаемом формате, например "1 hour 20 minutes"
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
        
        # Формируем читаемую строку
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour" + ("s" if hours > 1 else ""))
        if minutes > 0:
            parts.append(f"{minutes} minute" + ("s" if minutes > 1 else ""))
        
        return " ".join(parts) if parts else None
    
    def get_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD (с кэшированием)"""
        # Если уже есть в кэше, возвращаем
        if self._json_ld_recipe_cache is not None:
            return self._json_ld_recipe_cache if self._json_ld_recipe_cache != {} else None
        
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем тип
                def is_recipe(item):
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        return 'Recipe' in item_type
                    return item_type == 'Recipe'
                
                # Ищем Recipe в данных
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            self._json_ld_recipe_cache = item
                            return item
                elif isinstance(data, dict):
                    if is_recipe(data):
                        self._json_ld_recipe_cache = data
                        return data
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if is_recipe(item):
                                self._json_ld_recipe_cache = item
                                return item
                                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Сохраняем пустой dict в кэш чтобы не искать повторно
        self._json_ld_recipe_cache = {}
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Затем ищем в HTML
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Затем ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем контейнер ингредиентов (может содержать несколько групп)
        ingredient_container = self.soup.find('div', class_=re.compile(r'wprm-recipe-ingredients-container'))
        
        if ingredient_container:
            # Ищем все группы ингредиентов
            ingredient_groups = ingredient_container.find_all('div', class_='wprm-recipe-ingredient-group')
            
            # Если нет групп, ищем напрямую ul.wprm-recipe-ingredients
            if not ingredient_groups:
                ingredient_groups = [ingredient_container]
            
            for group in ingredient_groups:
                # Ищем список ингредиентов в группе
                ingredient_list = group.find('ul', class_='wprm-recipe-ingredients')
                if not ingredient_list:
                    continue
                
                items = ingredient_list.find_all('li', class_='wprm-recipe-ingredient')
                
                for item in items:
                    # Извлекаем структурированные данные
                    amount_elem = item.find('span', class_='wprm-recipe-ingredient-amount')
                    unit_elem = item.find('span', class_='wprm-recipe-ingredient-unit')
                    name_elem = item.find('span', class_='wprm-recipe-ingredient-name')
                    
                    if name_elem:
                        ingredient = {
                            "name": self.clean_text(name_elem.get_text()),
                            "amount": None,
                            "unit": None
                        }
                        
                        if amount_elem:
                            amount_text = self.clean_text(amount_elem.get_text())
                            # Конвертируем дроби используя общий метод
                            amount_text = self.convert_fractions_to_decimal(amount_text)
                            ingredient["amount"] = self.parse_number(amount_text)
                        
                        if unit_elem:
                            ingredient["unit"] = self.clean_text(unit_elem.get_text())
                        
                        ingredients.append(ingredient)
        
        # Если не нашли в HTML, пробуем JSON-LD
        if not ingredients:
            recipe_data = self.get_json_ld_recipe()
            if recipe_data and 'recipeIngredient' in recipe_data:
                for ing_text in recipe_data['recipeIngredient']:
                    if ing_text:
                        # Простой парсинг строки ингредиента
                        parsed = self.parse_ingredient_text(ing_text)
                        if parsed:
                            ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient_text(self, text: str) -> Optional[dict]:
        """Парсинг текстовой строки ингредиента"""
        if not text:
            return None
        
        text = self.clean_text(text)
        
        # Простой паттерн: количество единица название
        # Исключаем size descriptors из units (large, medium, small, etc.)
        pattern = r'^([\d\s/.,½¼¾⅓⅔]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|g|milliliters?|ml)?\s*(.+)$'
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            amount = None
            if amount_str:
                amount_str = self.convert_fractions_to_decimal(amount_str.strip())
                amount = self.parse_number(amount_str)
            
            return {
                "name": self.clean_text(name) if name else text,
                "amount": amount,
                "unit": self.clean_text(unit) if unit else None
            }
        
        return {
            "name": text,
            "amount": None,
            "unit": None
        }
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
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
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
        
        # Если не нашли в JSON-LD, пробуем HTML
        if not steps:
            # Ищем контейнер инструкций (может содержать несколько групп)
            instructions_container = self.soup.find('div', class_=re.compile(r'wprm-recipe-instructions-container'))
            
            if instructions_container:
                # Ищем все группы инструкций
                instruction_groups = instructions_container.find_all('div', class_='wprm-recipe-instruction-group')
                
                # Если нет групп, ищем напрямую ul.wprm-recipe-instructions
                if not instruction_groups:
                    instruction_groups = [instructions_container]
                
                for group in instruction_groups:
                    # Ищем список инструкций в группе
                    instructions_list = group.find('ul', class_='wprm-recipe-instructions')
                    if not instructions_list:
                        instructions_list = group.find('ol', class_='wprm-recipe-instructions')
                    
                    if not instructions_list:
                        continue
                    
                    items = instructions_list.find_all('li', class_='wprm-recipe-instruction')
                    for item in items:
                        text_div = item.find('div', class_='wprm-recipe-instruction-text')
                        if text_div:
                            step_text = self.clean_text(text_div.get_text())
                            # Пропускаем примечания, которые полностью в скобках
                            if step_text and not (step_text.startswith('(') and step_text.endswith(')')):
                                steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            if isinstance(category, list):
                return ', '.join(category)
            return self.clean_text(str(category))
        
        # Затем пробуем извлечь из классов article
        article = self.soup.find('article')
        if article and article.get('class'):
            classes = article['class']
            categories = []
            for cls in classes:
                if cls.startswith('category-'):
                    cat_name = cls.replace('category-', '').replace('-', ' ')
                    categories.append(cat_name)
            
            if categories:
                # Берем первую основную категорию
                return categories[0].title() if categories else None
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Сначала пробуем JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        # Затем ищем в HTML
        prep_time_elem = self.soup.find('div', class_='wprm-recipe-prep-time-container')
        if prep_time_elem:
            minutes_elem = prep_time_elem.find('span', class_='wprm-recipe-prep_time-minutes')
            if minutes_elem:
                minutes_text = self.clean_text(minutes_elem.get_text())
                # Извлекаем только число
                minutes_match = re.search(r'(\d+)', minutes_text)
                if minutes_match:
                    minutes = int(minutes_match.group(1))
                    return f"{minutes} minute" + ("s" if minutes != 1 else "")
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Сначала пробуем JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        # Затем ищем в HTML (может быть в custom time)
        cook_time_elem = self.soup.find('div', class_='wprm-recipe-cook-time-container')
        if not cook_time_elem:
            # Может быть помечено как "Inactive Time" или "Custom Time"
            cook_time_elem = self.soup.find('div', class_='wprm-recipe-custom-time-container')
        
        if cook_time_elem:
            hours_elem = cook_time_elem.find('span', class_=re.compile(r'wprm-recipe-.*-hours'))
            minutes_elem = cook_time_elem.find('span', class_=re.compile(r'wprm-recipe-.*-minutes'))
            
            parts = []
            if hours_elem:
                hours_text = self.clean_text(hours_elem.get_text())
                # Извлекаем только число
                hours_match = re.search(r'(\d+)', hours_text)
                if hours_match:
                    hours = hours_match.group(1)
                    if hours and hours != '0':
                        parts.append(f"{hours} hour" + ("s" if int(hours) > 1 else ""))
            if minutes_elem:
                minutes_text = self.clean_text(minutes_elem.get_text())
                # Извлекаем только число
                minutes_match = re.search(r'(\d+)', minutes_text)
                if minutes_match:
                    minutes = minutes_match.group(1)
                    if minutes and minutes != '0':
                        parts.append(f"{minutes} minute" + ("s" if int(minutes) > 1 else ""))
            
            if parts:
                return " ".join(parts)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Сначала пробуем JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        # Затем ищем в HTML
        total_time_elem = self.soup.find('div', class_='wprm-recipe-total-time-container')
        if total_time_elem:
            hours_elem = total_time_elem.find('span', class_='wprm-recipe-total_time-hours')
            minutes_elem = total_time_elem.find('span', class_='wprm-recipe-total_time-minutes')
            
            parts = []
            if hours_elem:
                hours_text = self.clean_text(hours_elem.get_text())
                # Извлекаем только число
                hours_match = re.search(r'(\d+)', hours_text)
                if hours_match:
                    hours = hours_match.group(1)
                    if hours and hours != '0':
                        parts.append(f"{hours} hour" + ("s" if int(hours) > 1 else ""))
            if minutes_elem:
                minutes_text = self.clean_text(minutes_elem.get_text())
                # Извлекаем только число
                minutes_match = re.search(r'(\d+)', minutes_text)
                if minutes_match:
                    minutes = minutes_match.group(1)
                    if minutes and minutes != '0':
                        parts.append(f"{minutes} minute" + ("s" if int(minutes) > 1 else ""))
            
            if parts:
                return " ".join(parts)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем секцию с примечаниями
        notes_section = self.soup.find('div', class_='wprm-recipe-notes-container')
        if notes_section:
            # Ищем текст внутри
            text = self.clean_text(notes_section.get_text())
            # Убираем заголовок "Notes" если есть
            text = re.sub(r'^Notes\s*', '', text, flags=re.IGNORECASE)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Извлекаем из классов article
        article = self.soup.find('article')
        if article and article.get('class'):
            classes = article['class']
            tags = []
            for cls in classes:
                if cls.startswith('tag-'):
                    tag_name = cls.replace('tag-', '').replace('-', ' ')
                    tags.append(tag_name)
            
            if tags:
                # Возвращаем первые 10 тегов (ограничение для предотвращения избыточности)
                return ', '.join(tags[:10])
        
        # Пробуем JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                return keywords
            elif isinstance(keywords, list):
                return ', '.join(keywords)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Сначала пробуем JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif '@url' in img:
                    urls.append(img['@url'])
        
        # Затем пробуем meta теги
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
        
        # Убираем дубликаты
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
    
    # Путь к директории с preprocessed файлами
    preprocessed_dir = os.path.join(
        Path(__file__).parent.parent,
        "preprocessed",
        "momlovesbaking_com"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(MomLovesBakingExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Убедитесь, что директория preprocessed/momlovesbaking_com существует")


if __name__ == "__main__":
    main()
