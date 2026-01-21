"""
Экстрактор данных рецептов для сайта ritzyrecipes.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class RitzyRecipesExtractor(BaseRecipeExtractor):
    """Экстрактор для ritzyrecipes.com"""
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение Recipe из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем наличие @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            return item
                
                # Проверяем прямой тип Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
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
        
        # Формируем читаемую строку
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'name' in recipe_data:
            name = recipe_data['name']
            # Убираем суффиксы вроде "Recipe:", ": Soft, Fluffy" и т.д.
            name = re.sub(r':\s*.+$', '', name)
            name = re.sub(r'\s+Recipe\s*$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r':\s*.+$', '', title)
            title = re.sub(r'\s+Recipe\s*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour" или "2 tablespoons butter"
            
        Returns:
            dict: {"name": "flour", "amount": "1", "unit": "cup"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Пример: "5 ½ to 6 cups (744g) all-purpose flour"
        # Сначала извлекаем основные компоненты
        
        # Удаляем информацию в скобках (вес в граммах и т.д.)
        text_clean = re.sub(r'\([^)]*\)', '', text).strip()
        
        # Паттерн для количества (включая диапазоны и дроби)
        amount_pattern = r'^([\d\s/.,½¼¾⅓⅔⅛⅜⅝⅞]+(?:\s+to\s+[\d\s/.,½¼¾⅓⅔⅛⅜⅝⅞]+)?)'
        
        # Список единиц измерения
        units = r'(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|packets?|cans?|jars?|bottles?|slices?|cloves?|bunches?|sprigs?|whole|head|heads)'
        
        # Пытаемся извлечь amount + unit + name
        pattern = rf'{amount_pattern}\s*{units}?\s+(.+)'
        match = re.match(pattern, text_clean, re.IGNORECASE)
        
        if match:
            amount_str = match.group(1).strip() if match.group(1) else None
            unit = match.group(2).strip() if match.group(2) else None
            name = match.group(3).strip() if match.group(3) else text_clean
        else:
            # Если паттерн не совпал, пробуем только unit + name
            pattern_no_amount = rf'{units}\s+(.+)'
            match_no_amount = re.match(pattern_no_amount, text_clean, re.IGNORECASE)
            if match_no_amount:
                amount_str = None
                unit = match_no_amount.group(1).strip()
                name = match_no_amount.group(2).strip()
            else:
                # Совсем простой случай - только название
                amount_str = None
                unit = None
                name = text_clean
        
        # Очистка названия от лишних слов
        name = re.sub(r'\b(or more|if needed|optional|for garnish|to taste|as needed)\b', '', name, flags=re.IGNORECASE)
        name = re.sub(r'[,;]+$', '', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "units": unit,
            "amount": amount_str
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredients_list = recipe_data['recipeIngredient']
            
            # Парсим каждый ингредиент в структурированный формат
            parsed_ingredients = []
            for ingredient_text in ingredients_list:
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    parsed_ingredients.append(parsed)
            
            return json.dumps(parsed_ingredients, ensure_ascii=False) if parsed_ingredients else None
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            steps = []
            step_number = 1
            
            for item in instructions:
                if isinstance(item, dict):
                    # HowToStep
                    if item.get('@type') == 'HowToStep' and 'text' in item:
                        steps.append(f"{step_number}. {self.clean_text(item['text'])}")
                        step_number += 1
                    # HowToSection
                    elif item.get('@type') == 'HowToSection':
                        # Добавляем название секции, если есть
                        section_name = item.get('name', '')
                        if section_name and not section_name.startswith(str(step_number)):
                            # Если название секции уже содержит номер, используем его
                            if re.match(r'^\d+\.', section_name):
                                section_name_clean = re.sub(r'^\d+\.\s*', '', section_name)
                                steps.append(f"{step_number}. {section_name_clean}")
                                step_number += 1
                            else:
                                steps.append(f"{step_number}. {section_name}")
                                step_number += 1
                        
                        # Обрабатываем шаги внутри секции
                        if 'itemListElement' in item:
                            for sub_item in item['itemListElement']:
                                if sub_item.get('@type') == 'HowToStep' and 'text' in sub_item:
                                    steps.append(f"{step_number}. {self.clean_text(sub_item['text'])}")
                                    step_number += 1
                elif isinstance(item, str):
                    steps.append(f"{step_number}. {self.clean_text(item)}")
                    step_number += 1
            
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            return self.clean_text(recipe_data['recipeCategory'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями в HTML
        notes_section = self.soup.find(class_='tasty-recipes-notes-body')
        
        if notes_section:
            # Извлекаем текст, очищаем от заголовков
            text = notes_section.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            # keywords могут быть строкой с тегами через запятую
            if isinstance(keywords, str):
                # Разбиваем по запятой, очищаем и возвращаем
                tags = [self.clean_text(tag) for tag in keywords.split(',')]
                tags = [tag for tag in tags if tag]  # Убираем пустые
                return ', '.join(tags) if tags else None
            elif isinstance(keywords, list):
                tags = [self.clean_text(tag) for tag in keywords]
                tags = [tag for tag in tags if tag]
                return ', '.join(tags) if tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'image' in recipe_data:
            images = recipe_data['image']
            
            if isinstance(images, str):
                urls.append(images)
            elif isinstance(images, list):
                # Берем все уникальные URL
                for img in images:
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, dict):
                        if 'url' in img:
                            urls.append(img['url'])
                        elif 'contentUrl' in img:
                            urls.append(img['contentUrl'])
        
        # Дополнительно ищем в мета-тегах
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
    # Обрабатываем папку preprocessed/ritzyrecipes_com
    recipes_dir = os.path.join("preprocessed", "ritzyrecipes_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(RitzyRecipesExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python ritzyrecipes_com.py")


if __name__ == "__main__":
    main()
