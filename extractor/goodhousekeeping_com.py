"""
Экстрактор данных рецептов для сайта goodhousekeeping.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class GoodHousekeepingExtractor(BaseRecipeExtractor):
    """Экстрактор для goodhousekeeping.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT50M"
            
        Returns:
            Время в формате "20 mins", "1 hour 30 mins" и т.д.
        """
        if not duration or not duration.startswith('PT'):
            return None
        
        duration = duration[2:]  # Убираем "PT"
        
        # Если это PT0S (0 секунд), возвращаем None
        if duration == '0S':
            return None
        
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
        
        # Формируем читаемую строку - используем "mins" для соответствия reference
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} mins")
        
        return ' '.join(parts) if parts else None
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Может быть массивом или единичным объектом
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        recipe = self._get_recipe_json_ld()
        if recipe and 'name' in recipe:
            name = recipe['name']
            # Убираем длинные описательные части после запятой
            if ', ' in name and len(name) > 50:
                name = name.split(',')[0]
            return self.clean_text(name)
        
        # Альтернативно - из h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s+Recipe.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        recipe = self._get_recipe_json_ld()
        if recipe and 'description' in recipe:
            desc = recipe['description']
            if desc:
                return self.clean_text(desc)
        
        # Из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour" или "2 tbsp. butter"
            
        Returns:
            dict: {"name": "flour", "amount": "1", "unit": "cup"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
        # Заменяем Unicode дроби на обычные дроби
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5'
        }
        
        for fraction, replacement in fraction_map.items():
            text = text.replace(fraction, replacement)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1 c. flour", "2 tbsp. butter", "1/2 tsp. salt", "1 1/4 cups flour"
        # Порядок важен: сначала проверяем полные слова, потом сокращения с точками
        pattern = r'^([\d\s/]+)?\s*(cups?|tablespoons?|teaspoons?|pounds?|ounces?|grams?|kilograms?|milliliters?|liters?|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|heads?|c\.|tbsps?\.?|tsps?\.?|lbs?\.?|oz\.?|g\.?|kg\.?|ml\.?)\s*(.+)'
        
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
            # Обработка смешанных дробей типа "1 1/2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                # Форматируем обратно в дробь для сохранения оригинального формата
                if total == int(total):
                    amount = str(int(total))
                else:
                    # Пытаемся представить в виде дроби
                    if total == 0.5:
                        amount = "1/2"
                    elif total == 0.25:
                        amount = "1/4"
                    elif total == 0.75:
                        amount = "3/4"
                    elif total == 1.25:
                        amount = "1 1/4"
                    elif total == 1.5:
                        amount = "1 1/2"
                    elif total == 2.5:
                        amount = "2 1/2"
                    else:
                        amount = amount_str  # Оставляем как есть
            else:
                amount = amount_str
        
        # Обработка единицы измерения - убираем точки и нормализуем
        if unit:
            unit = unit.strip().rstrip('.')
            # Нормализация сокращений - сохраняем оригинальный формат из reference
            unit_map = {
                'c': 'cup',
                'cups': 'cups',  # Множественное число остается
                'cup': 'cup',
                'tbsp': 'Tbsp.',
                'tbsps': 'Tbsp.',
                'tablespoon': 'Tbsp.',
                'tablespoons': 'Tbsp.',
                'tsp': 'tsp.',
                'tsps': 'tsp.',
                'teaspoon': 'tsp.',
                'teaspoons': 'tsp.',
                'oz': 'oz.',
                'lb': 'lb.',
                'lbs': 'lb.',
                'pound': 'lb.',
                'pounds': 'lb.',
                'g': 'g',
                'kg': 'kg',
                'ml': 'ml',
                'l': 'l'
            }
            unit = unit_map.get(unit.lower(), unit)
        
        # Очистка названия
        # Не удаляем скобки - они могут содержать важную информацию
        # Удаляем фразы "to taste", "as needed", "optional", "plus more"
        name = re.sub(r',?\s*\b(to taste|as needed|or more|if needed|optional|for garnish|plus more for serving|plus more for dusting)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые в конце
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        # Reference JSON uses "units" before "amount"
        return {
            "name": name,
            "units": unit,
            "amount": amount
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        # Извлекаем из JSON-LD
        recipe = self._get_recipe_json_ld()
        if recipe and 'recipeIngredient' in recipe:
            ingredients = []
            for ing_text in recipe['recipeIngredient']:
                parsed = self.parse_ingredient(ing_text)
                if parsed:
                    ingredients.append(parsed)
            
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        # Извлекаем из JSON-LD
        recipe = self._get_recipe_json_ld()
        if recipe and 'recipeInstructions' in recipe:
            instructions = recipe['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict):
                        # Может быть HowToStep с полем text или name
                        text = step.get('text') or step.get('name', '')
                        if text:
                            # Применяем clean_text для нормализации пробелов
                            text = self.clean_text(text)
                            # Убираем существующую нумерацию если есть
                            text = re.sub(r'^\d+\.\s*', '', text)
                            steps.append(f"Step {idx}: {text}")
                    elif isinstance(step, str):
                        text = self.clean_text(step)
                        text = re.sub(r'^\d+\.\s*', '', text)
                        steps.append(f"Step {idx}: {text}")
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            
            if steps:
                return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Сначала из JSON-LD recipeCategory
        recipe = self._get_recipe_json_ld()
        if recipe and 'recipeCategory' in recipe:
            category = recipe['recipeCategory']
            if isinstance(category, list):
                # Берем только первую категорию и капитализируем первую букву
                if category:
                    return category[0].capitalize()
            elif isinstance(category, str):
                return self.clean_text(category).capitalize()
        
        # Из meta article:section
        article_section = self.soup.find('meta', property='article:section')
        if article_section and article_section.get('content'):
            return self.clean_text(article_section['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe = self._get_recipe_json_ld()
        if recipe and 'prepTime' in recipe:
            return self.parse_iso_duration(recipe['prepTime'])
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe = self._get_recipe_json_ld()
        if recipe and 'cookTime' in recipe:
            return self.parse_iso_duration(recipe['cookTime'])
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe = self._get_recipe_json_ld()
        if recipe and 'totalTime' in recipe:
            return self.parse_iso_duration(recipe['totalTime'])
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Сначала проверяем элемент с data-testid="EditorNote"
        editor_note = self.soup.find(attrs={'data-testid': 'EditorNote'})
        if editor_note:
            # Ищем параграф внутри
            p = editor_note.find('p')
            if p:
                text = self.clean_text(p.get_text())
                return text if text else None
            # Или берем весь текст
            text = editor_note.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        # Ищем в HTML элементы с классом, содержащим "note" или "tip"
        notes_elem = self.soup.find(class_=re.compile(r'(note|tip)', re.I))
        
        if notes_elem:
            # Ищем параграф внутри
            p = notes_elem.find('p')
            if p:
                text = self.clean_text(p.get_text())
                return text if text else None
            
            # Или берем весь текст
            text = notes_elem.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Из JSON-LD keywords
        recipe = self._get_recipe_json_ld()
        if recipe and 'keywords' in recipe:
            keywords = recipe['keywords']
            
            tags_list = []
            
            if isinstance(keywords, list):
                for keyword in keywords:
                    # Извлекаем только конкретные теги из категорий
                    if isinstance(keyword, str):
                        # Ищем основной список тегов - обычно строка с запятыми без префиксов
                        if ',' in keyword and not any(prefix in keyword for prefix in ['content-type:', 'locale:', 'displayType:', 'shortTitle:', 'contentId:', 'collection:']):
                            # Проверяем, что это не служебные метаданные
                            if not keyword.startswith('NUTRITION:') and not keyword.startswith('CATEGORY:') and not keyword.startswith('TOTALTIME:') and not keyword.startswith('FILTERTIME:'):
                                # Это основной список тегов
                                tags_list = [t.strip() for t in keyword.split(',') if t.strip()]
                                break  # Берем только первый подходящий список
            elif isinstance(keywords, str):
                tags_list = [t.strip() for t in keywords.split(',') if t.strip()]
            
            # Возвращаем как есть, без дополнительной фильтрации
            if tags_list:
                return ', '.join(tags_list)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Из JSON-LD
        recipe = self._get_recipe_json_ld()
        if recipe and 'image' in recipe:
            images = recipe['image']
            
            if isinstance(images, list):
                for img in images:
                    if isinstance(img, dict):
                        url = img.get('url') or img.get('contentUrl')
                        if url:
                            urls.append(url)
                    elif isinstance(img, str):
                        urls.append(img)
            elif isinstance(images, dict):
                url = images.get('url') or images.get('contentUrl')
                if url:
                    urls.append(url)
            elif isinstance(images, str):
                urls.append(images)
        
        # Также из meta tags
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # Удаляем дубликаты
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
    
    # Путь к директории с preprocessed файлами
    preprocessed_dir = os.path.join("preprocessed", "goodhousekeeping_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(GoodHousekeepingExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python goodhousekeeping_com.py")


if __name__ == "__main__":
    main()
