"""
Экстрактор данных рецептов для сайта recipes-for-life.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class RecipesForLifeExtractor(BaseRecipeExtractor):
    """Экстрактор для recipes-for-life.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах, например "90 minutes"
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
    
    def get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение Recipe данных из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
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
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "2 cups all-purpose flour"
            
        Returns:
            dict: {"name": "flour", "amount": 2, "units": "cups"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на текстовые дроби (чтобы не ломать парсинг)
        # "1½" → "1 1/2", "½" → "1/2"
        fraction_map = {
            '½': ' 1/2', '¼': ' 1/4', '¾': ' 3/4',
            '⅓': ' 1/3', '⅔': ' 2/3', '⅛': ' 1/8',
            '⅜': ' 3/8', '⅝': ' 5/8', '⅞': ' 7/8',
            '⅕': ' 1/5', '⅖': ' 2/5', '⅗': ' 3/5', '⅘': ' 4/5'
        }
        
        for fraction, replacement in fraction_map.items():
            # Заменяем дробь, добавляя пробел только если он нужен
            if text.startswith(fraction):
                text = replacement.strip() + text[len(fraction):]
            else:
                text = text.replace(' ' + fraction, replacement)
                text = text.replace(fraction, replacement)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "2 cups flour", "1 tablespoon oil", "3 pounds chicken", "4 large eggs"
        # НЕ включаем large/medium/small в units, так как они являются частью названия ингредиента
        # Используем \b для word boundary чтобы "l" не матчился в "large"
        pattern = r'^([\d\s/.,]+)?\s*(?:(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|kg|milliliters?|liters?|ml|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|heads?|g|l)\b\s+)?(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Специальная обработка: если есть количество но нет единицы,
        # и name начинается с large/medium/small, то единица = pieces
        if amount_str and not unit and name:
            size_match = re.match(r'^(large|medium|small)\s+', name, re.IGNORECASE)
            if size_match:
                unit = 'pieces'
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2" или "1 1/2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                amount = total
            else:
                try:
                    amount = float(amount_str.replace(',', '.'))
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия - удаляем только явные инструкции по приготовлению
        # Удаляем скобки с содержимым в конце
        name = re.sub(r'\s*\([^)]*\)\s*$', '', name)
        # Удаляем запятую и всё после неё (обычно уточнения типа "diced", "minced")
        name = re.sub(r',.*$', '', name)
        # Удаляем конкретные фразы-инструкции
        name = re.sub(r'\s+(at room temperature|softened|drained|melted)$', '', name, flags=re.IGNORECASE)
        # Удаляем "such as X" в конце
        name = re.sub(r'\s+such as\s+.*$', '', name, flags=re.IGNORECASE)
        # Удаляем "for decoration" но оставляем "for frosting" (если это часть имени)
        name = re.sub(r'\s+for decoration$', '', name, flags=re.IGNORECASE)
        
        # Удаляем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        recipe_data = self.get_recipe_json_ld()
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredients = []
        raw_ingredients = recipe_data['recipeIngredient']
        
        for ingredient_text in raw_ingredients:
            parsed = self.parse_ingredient(ingredient_text)
            if parsed:
                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self.get_recipe_json_ld()
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        steps = []
        
        if isinstance(instructions, list):
            for idx, step in enumerate(instructions, 1):
                if isinstance(step, dict) and 'text' in step:
                    steps.append(f"{idx}. {step['text']}")
                elif isinstance(step, str):
                    steps.append(f"{idx}. {step}")
        elif isinstance(instructions, str):
            steps.append(instructions)
        
        return ' '.join(steps) if steps else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # На сайте recipes-for-life.com nutrition info не представлена в JSON-LD
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'recipeCategory' in recipe_data:
            return self.clean_text(recipe_data['recipeCategory'])
        
        # Альтернативно - из article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем параграфы с текстом, содержащим "For optimal" или другие ключевые слова
        keywords = ['for optimal', 'tip:', 'note:', 'important:']
        
        all_paragraphs = self.soup.find_all('p')
        for p in all_paragraphs:
            text = p.get_text(strip=True)
            text_lower = text.lower()
            
            # Проверяем наличие ключевых слов
            for keyword in keywords:
                if keyword in text_lower:
                    # Берем только первое предложение
                    sentences = text.split('.')
                    if sentences:
                        first_sentence = sentences[0].strip() + '.'
                        return self.clean_text(first_sentence)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Получаем категорию и keywords из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        tags = []
        
        if recipe_data:
            # Добавляем keywords если есть
            if 'keywords' in recipe_data:
                keywords = recipe_data['keywords']
                if isinstance(keywords, str):
                    # Разделяем по запятым
                    tags.extend([k.strip().lower() for k in keywords.split(',') if k.strip()])
                elif isinstance(keywords, list):
                    tags.extend([str(k).strip().lower() for k in keywords if k])
            
            # Добавляем категорию
            if 'recipeCategory' in recipe_data:
                category = recipe_data['recipeCategory'].lower()
                if category and category not in tags:
                    tags.append(category)
        
        # Также проверяем article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            section = meta_section['content'].lower()
            if section and section not in tags:
                tags.append(section)
        
        # Если нет тегов из JSON-LD, пытаемся извлечь из названия
        if not tags and recipe_data and 'name' in recipe_data:
            # Извлекаем ключевые слова из названия (простой подход)
            name = recipe_data['name'].lower()
            # Удаляем распространенные слова
            stopwords = {'recipe', 'the', 'a', 'an', 'and', 'or', 'with', 'for'}
            words = [w for w in name.split() if w not in stopwords and len(w) > 3]
            tags.extend(words[:4])  # Берем первые 4 значимых слова
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        recipe_data = self.get_recipe_json_ld()
        if not recipe_data or 'image' not in recipe_data:
            return None
        
        image_data = recipe_data['image']
        urls = []
        
        if isinstance(image_data, str):
            urls.append(image_data)
        elif isinstance(image_data, list):
            for img in image_data:
                if isinstance(img, str):
                    urls.append(img)
                elif isinstance(img, dict):
                    if 'url' in img:
                        urls.append(img['url'])
                    elif 'contentUrl' in img:
                        urls.append(img['contentUrl'])
        elif isinstance(image_data, dict):
            if 'url' in image_data:
                urls.append(image_data['url'])
            elif 'contentUrl' in image_data:
                urls.append(image_data['contentUrl'])
        
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
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Ищем директорию с HTML-страницами
    recipes_dir = os.path.join("preprocessed", "recipes-for-life_com")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(RecipesForLifeExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python recipes-for-life_com.py")


if __name__ == "__main__":
    main()
