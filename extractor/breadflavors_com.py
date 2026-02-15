"""
Экстрактор данных рецептов для сайта breadflavors.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class BreadFlavorsExtractor(BaseRecipeExtractor):
    """Экстрактор для breadflavors.com"""
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """
        Извлечение Recipe данных из JSON-LD
        
        Returns:
            Словарь с данными рецепта из JSON-LD или None
        """
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Данные могут быть в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                
                # Или напрямую в списке
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                
                # Или как единственный объект
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT65M"
            
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
            # Убираем суффикс " Recipe" если есть
            name = re.sub(r'\s+Recipe\s*$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
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
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном виде"""
        recipe_data = self._get_recipe_json_ld()
        ingredients = []
        
        if recipe_data and 'recipeIngredient' in recipe_data:
            # В JSON-LD ингредиенты - это список строк
            for ingredient_text in recipe_data['recipeIngredient']:
                if not ingredient_text:
                    continue
                
                # Парсим строку в структурированный формат
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "½ cup (100grams) light or dark brown sugar"
            
        Returns:
            dict: {"name": "light or dark brown sugar", "amount": "½", "units": "cup"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Удаляем информацию в скобках с граммами/миллилитрами (необязательное)
        text_for_parsing = re.sub(r'\([^)]*grams?\)', '', text)
        text_for_parsing = re.sub(r'\([^)]*ml\)', '', text)
        text_for_parsing = text_for_parsing.strip()
        
        # Паттерн для извлечения количества, единицы и названия
        # Улучшенный паттерн для обработки "1 and ½ teaspoon" как единого количества
        # Также обрабатываем случаи с множественными пробелами
        pattern = r'^([\d\s/.,½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘]+(?:\s+and\s+[\d\s/.,½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘]+)?)?\s+(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads)\s+(.+)'
        
        match = re.match(pattern, text_for_parsing, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, пробуем без единицы измерения (например "2 eggs")
            pattern_no_unit = r'^([\d\s/.,½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘]+(?:\s+and\s+[\d\s/.,½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘]+)?)\s+(.+)'
            match_no_unit = re.match(pattern_no_unit, text_for_parsing, re.IGNORECASE)
            
            if match_no_unit:
                amount_str, name = match_no_unit.groups()
                return {
                    "name": self.clean_text(name),
                    "amount": amount_str.strip() if amount_str else None,
                    "units": None
                }
            
            # Если и это не сработало, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества - убираем лишние пробелы
        amount = None
        if amount_str:
            amount = re.sub(r'\s+', ' ', amount_str.strip())
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем фразы "at room temperature", "to taste", etc.
        name = re.sub(r',?\s*at room temperature\s*', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
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
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            if isinstance(category, list):
                # Берем первую категорию или объединяем через запятую
                return self.clean_text(category[0]) if category else None
            else:
                return self.clean_text(category)
        
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
        """Извлечение заметок к рецепту"""
        # Ищем секцию с заметками на странице
        # Специфично для breadflavors.com используется wprm-recipe-notes
        notes_section = self.soup.find('div', class_='wprm-recipe-notes')
        
        if notes_section:
            # Извлекаем все span блоки с текстом заметок
            spans = notes_section.find_all('span', style='display: block;')
            if spans:
                notes_parts = []
                for span in spans:
                    # Извлекаем текст, убирая HTML теги
                    text = span.get_text(separator=' ', strip=True)
                    text = self.clean_text(text)
                    if text:
                        notes_parts.append(text)
                
                if notes_parts:
                    return ' '.join(notes_parts)
            
            # Если нет span блоков, берем весь текст
            text = notes_section.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            if text:
                return text
        
        # Альтернативный поиск для других сайтов
        notes_patterns = [
            re.compile(r'wprm-recipe-notes', re.I),
            re.compile(r'recipe.*note', re.I),
            re.compile(r'note', re.I),
        ]
        
        for pattern in notes_patterns:
            notes_section = self.soup.find(class_=pattern)
            if notes_section:
                text = notes_section.get_text(separator=' ', strip=True)
                # Убираем возможный заголовок "Notes:" или "Recipe Notes:"
                text = re.sub(r'^(Recipe\s+)?Notes?\s*:?\s*', '', text, flags=re.I)
                text = self.clean_text(text)
                if text:
                    return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из keywords"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            
            if isinstance(keywords, str):
                # Теги уже в строковом формате через запятую
                # Очищаем и нормализуем
                tags = [self.clean_text(tag) for tag in keywords.split(',') if tag.strip()]
                return ', '.join(tags) if tags else None
            elif isinstance(keywords, list):
                # Теги в виде списка
                tags = [self.clean_text(tag) for tag in keywords if tag]
                return ', '.join(tags) if tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        recipe_data = self._get_recipe_json_ld()
        urls = []
        
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                # Берем все URL из списка
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        if 'url' in item:
                            urls.append(item['url'])
                        elif 'contentUrl' in item:
                            urls.append(item['contentUrl'])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
        # Также проверяем og:image как запасной вариант
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
        
        # Удаляем дубликаты, сохраняя порядок
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
    """
    Точка входа для обработки HTML файлов breadflavors.com
    """
    import os
    
    # Путь к директории с preprocessed файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "preprocessed",
        "breadflavors_com"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(BreadFlavorsExtractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python breadflavors_com.py")


if __name__ == "__main__":
    main()
