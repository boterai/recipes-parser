"""
Экстрактор данных рецептов для сайта eatthis.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class EatThisExtractor(BaseRecipeExtractor):
    """Экстрактор для eatthis.com"""
    
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
        """Извлечение Recipe из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return None
    
    def get_parsely_metadata(self) -> Optional[dict]:
        """Извлечение метаданных из wp-parsely-metadata"""
        script = self.soup.find('script', type='application/ld+json', class_='wp-parsely-metadata')
        if script:
            try:
                return json.loads(script.string)
            except (json.JSONDecodeError, AttributeError):
                pass
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            name = recipe_data['name']
            # Убираем типичные суффиксы
            name = re.sub(r'\s+(Recipe|Eat This Not That).*$', '', name, flags=re.IGNORECASE)
            # Убираем начальные фразы типа "A 10-Minute"
            name = re.sub(r'^(A\s+)?\d+(-|\s+)?Minute\s+', '', name, flags=re.IGNORECASE)
            name = re.sub(r'^(Healthy\s+)?', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Пробуем извлечь из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из JSON-LD Recipe
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            # Обрезаем "..." если есть
            if desc.endswith('...'):
                desc = desc[:-3]
            return self.clean_text(desc)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour" или "2 pounds chicken"
            
        Returns:
            dict: {"name": "flour", "amount": 1, "units": "cup"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на обычные
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5',
            '⁄': '/'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Расширяем pattern для поиска "(X oz.) bag" и подобных конструкций
        pattern = r'^([\d\s/.,]+)?\s*(?:\([\d\s.,]+\s*(?:oz|g|kg|lb|ml|l)\.\?\s*\))?\s*(Tbsp|tbsp|Tsp|tsp|cups?|tablespoons?|teaspoons?|pounds?|ounces?|lbs?|lb|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|pinch|dash(?:es)?|packages?|pkg|cans?|can|jars?|bottles?|inch(?:es)?|slices?|slice|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|piece|head|heads|bag|bags|units?|unit)?\s*(.+)'
        
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
            # Обработка дробей типа "1/2" или "1 1/2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0.0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                # Возвращаем как int если целое число, иначе как float
                amount = int(total) if total.is_integer() else total
            else:
                # Пробуем преобразовать в число
                try:
                    val = float(amount_str.replace(',', '.'))
                    amount = int(val) if val.is_integer() else val
                except ValueError:
                    amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия - убираем размеры в скобках
        # Удаляем скобки с содержимым типа (10 oz.)
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish)\b', '', name, flags=re.IGNORECASE)
        # Убираем "of" в начале (например "of salt" -> "salt")
        name = re.sub(r'^of\s+', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        # Если в названии есть "X eggs", добавляем "unit" как units
        if not unit and re.match(r'^eggs?$', name, re.IGNORECASE):
            unit = "unit"
        
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
        if not recipe_data:
            return None
        
        ingredients = []
        
        # Используем recipeIngredient из JSON-LD
        if 'recipeIngredient' in recipe_data:
            raw_ingredients = recipe_data['recipeIngredient']
            
            # Фильтруем и собираем ингредиенты (пропускаем "chopped", "sliced" и т.д.)
            skip_words = ['chopped', 'sliced', 'diced', 'minced', 'thawed', 'beaten', 'peeled', 
                         'halved', 'quartered', 'grated', 'shredded', 'crushed']
            skip_phrases = ['split and lightly toasted', 'cut into thin strips', 'lightly toasted']
            
            i = 0
            while i < len(raw_ingredients):
                ing_text = self.clean_text(raw_ingredients[i])
                
                # Пропускаем слова-действия
                if ing_text.lower() in skip_words:
                    i += 1
                    continue
                
                # Пропускаем фразы-действия
                if any(phrase in ing_text.lower() for phrase in skip_phrases):
                    i += 1
                    continue
                
                # Если это "cut into thin strips X" где X - дробь, то X относится к следующему ингредиенту
                if ing_text.lower().startswith('cut into'):
                    # Извлекаем дробь из конца
                    match = re.search(r'([\d⁄/]+)\s*$', ing_text)
                    if match and i + 1 < len(raw_ingredients):
                        fraction = match.group(1)
                        next_text = self.clean_text(raw_ingredients[i + 1])
                        # Объединяем дробь со следующим элементом
                        full_text = fraction + " " + next_text
                        i += 2  # Пропускаем оба элемента
                    else:
                        i += 1
                        continue
                # Если строка начинается со скобки типа "(10 oz.) bag...", это продолжение
                elif ing_text.startswith('('):
                    # Пропускаем, так как это уже должно быть обработано
                    i += 1
                    continue
                else:
                    full_text = ing_text
                    i += 1
                
                # Разбиваем "salt and pepper" на два отдельных ингредиента
                if ' and ' in full_text.lower() and 'to taste' in full_text.lower():
                    # Убираем "to taste" и разбиваем
                    full_text = re.sub(r'\s+to taste', '', full_text, flags=re.IGNORECASE)
                    parts = re.split(r'\s+and\s+', full_text, flags=re.IGNORECASE)
                    for part in parts:
                        part = part.strip().lower()  # Lowercase for consistency
                        parsed = self.parse_ingredient(part)
                        if parsed:
                            ingredients.append(parsed)
                else:
                    parsed = self.parse_ingredient(full_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self.get_recipe_json_ld()
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        
        if isinstance(instructions, list) and len(instructions) > 0:
            # Берем первый элемент (обычно это единственный шаг со всем текстом)
            if isinstance(instructions[0], dict) and 'text' in instructions[0]:
                text = instructions[0]['text']
                return self.clean_text(text)
            elif isinstance(instructions[0], str):
                return self.clean_text(instructions[0])
        elif isinstance(instructions, str):
            return self.clean_text(instructions)
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # Сначала пробуем из articleBody в parsely metadata (там есть полная информация)
        parsely_data = self.get_parsely_metadata()
        if parsely_data and 'articleBody' in parsely_data:
            article_body = parsely_data['articleBody']
            
            # Ищем паттерн с калориями и жирами
            # Пример: "150 calories, 9 g fat (2.5 g saturated), 560 mg sodium"
            pattern = r'(\d+)\s*calories[,\s]+(\d+\.?\d*)\s*g\s*fat\s*\(([^)]+)\)[,\s]+(\d+)\s*mg\s*sodium'
            match = re.search(pattern, article_body, re.IGNORECASE)
            if match:
                calories = match.group(1)
                fat = match.group(2)
                saturated = match.group(3)
                sodium = match.group(4)
                return f"{calories} calories, {fat} g fat ({saturated}), {sodium} mg sodium"
            
            # Альтернативный паттерн без натрия
            pattern2 = r'(\d+)\s*calories[,\s]+(\d+\.?\d*)\s*g\s*fat\s*\(([^)]+)\)[,\s]+(\d+\.?\d*)\s*g\s*sugar'
            match2 = re.search(pattern2, article_body, re.IGNORECASE)
            if match2:
                calories = match2.group(1)
                fat = match2.group(2)
                saturated = match2.group(3)
                sugar = match2.group(4)
                return f"{calories} calories, {fat} g fat ({saturated}), {sugar} g sugar"
        
        # Если не нашли в articleBody, пробуем из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'nutrition' in recipe_data:
            nutrition = recipe_data['nutrition']
            if 'calories' in nutrition:
                calories = nutrition['calories']
                # Извлекаем только число
                cal_match = re.search(r'(\d+)', str(calories))
                if cal_match:
                    return f"{cal_match.group(1)} calories"
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'recipeCategory' in recipe_data:
            return self.clean_text(recipe_data['recipeCategory'])
        
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
        if recipe_data and 'totalTime' in recipe_data and recipe_data['totalTime']:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        # Если totalTime нет, но есть prep и cook time, суммируем их
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        
        if prep_time and cook_time:
            # Извлекаем числа из строк вида "10 minutes"
            prep_match = re.search(r'(\d+)', prep_time)
            cook_match = re.search(r'(\d+)', cook_time)
            
            if prep_match and cook_match:
                total_minutes = int(prep_match.group(1)) + int(cook_match.group(1))
                return f"{total_minutes} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        parsely_data = self.get_parsely_metadata()
        if not parsely_data or 'articleBody' not in parsely_data:
            return None
        
        article_body = parsely_data['articleBody']
        
        # Ищем секцию "Eat This Tip" или похожие
        tip_pattern = r'Eat This Tip\s+(.+?)(?:\n\n|\Z)'
        match = re.search(tip_pattern, article_body, re.DOTALL | re.IGNORECASE)
        
        if match:
            tip_text = match.group(1)
            
            # Убираем части типа "(or just use it..." и далее
            tip_text = re.sub(r'\s*\([^)]*as possible', ' as possible', tip_text)
            
            # Останавливаемся перед фразами типа "Invent at will"
            tip_text = re.split(r'(?:Invent at will|Here are|Try these|For example)', tip_text, flags=re.IGNORECASE)[0]
            
            # Очищаем от списков
            lines = tip_text.split('\n')
            result_lines = []
            for line in lines:
                line = line.strip()
                # Если строка начинается с табуляции, это список - пропускаем
                if line.startswith('\t') or not line:
                    continue
                result_lines.append(line)
            
            if result_lines:
                tip_text = ' '.join(result_lines)
                tip_text = self.clean_text(tip_text)
                # Убираем концовки типа ", but take these ideas for inspiration:"
                tip_text = re.sub(r',?\s*but take these ideas.*$', '', tip_text, flags=re.IGNORECASE)
                tip_text = re.sub(r'\s*\(or just use.*$', '', tip_text, flags=re.IGNORECASE)
                tip_text = tip_text.rstrip('.:,')
                return tip_text if tip_text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Сначала пробуем из parsely metadata (приоритет)
        parsely_data = self.get_parsely_metadata()
        if parsely_data and 'keywords' in parsely_data:
            keywords = parsely_data['keywords']
            if isinstance(keywords, list):
                # Capitalize first letter of each word in each tag
                formatted_tags = []
                for tag in keywords:
                    # Capitalize first letter of each word
                    words = tag.split()
                    formatted_tag = ' '.join([word.capitalize() for word in words])
                    formatted_tags.append(formatted_tag)
                return ', '.join(formatted_tags)
        
        # Альтернативно из Recipe JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Разделяем по запятой и очищаем
                tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                return ', '.join(tags)
            elif isinstance(keywords, list):
                return ', '.join(keywords)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Из og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # Из JSON-LD Recipe
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'image' in recipe_data:
            image = recipe_data['image']
            if isinstance(image, dict):
                if 'url' in image:
                    urls.append(image['url'])
                elif 'contentUrl' in image:
                    urls.append(image['contentUrl'])
            elif isinstance(image, str):
                urls.append(image)
            elif isinstance(image, list):
                for img in image:
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, dict) and 'url' in img:
                        urls.append(img['url'])
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                # Декодируем HTML entities в URL (&#038; -> &)
                url = url.replace('&#038;', '&')
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
    import os
    # По умолчанию обрабатываем папку preprocessed/eatthis_com
    preprocessed_dir = os.path.join("preprocessed", "eatthis_com")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(EatThisExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python eatthis_com.py [путь_к_файлу_или_директории]")


if __name__ == "__main__":
    main()
