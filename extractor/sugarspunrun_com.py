"""
Экстрактор данных рецептов для сайта sugarspunrun.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class SugarSpunRunExtractor(BaseRecipeExtractor):
    """Экстрактор для sugarspunrun.com"""
    
    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Проверяем наличие @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                
                # Проверяем если Recipe напрямую
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                
                # Если data - список
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                            
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT60M"
            
        Returns:
            Время в формате "20 minutes" или "1 hour 30 minutes" или "1 hour"
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
        
        # Если только минуты и они кратны 60, конвертируем в часы
        if hours == 0 and minutes > 0 and minutes % 60 == 0:
            hours = minutes // 60
            minutes = 0
        
        # Форматируем результат
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        # Если есть часы и минуты кратны 60, не показываем минуты
        if minutes > 0 and not (hours > 0 and minutes == 0):
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    @staticmethod
    def parse_ingredient_string(ingredient_str: str) -> Dict[str, any]:
        """
        Парсит строку ингредиента в структурированный формат
        
        Args:
            ingredient_str: Строка типа "3 cups all-purpose flour"
            
        Returns:
            dict с ключами name, amount, units
        """
        if not ingredient_str:
            return {"name": None, "amount": None, "units": None}
        
        # Очищаем строку и нормализуем пробелы
        ingredient_str = ingredient_str.strip()
        ingredient_str = re.sub(r'\s+', ' ', ingredient_str)  # Убираем двойные пробелы
        
        # Заменяем Unicode дроби на десятичные для парсинга
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        # Создаем версию для парсинга с замененными дробями
        parse_str = ingredient_str
        for fraction, decimal in fraction_map.items():
            parse_str = parse_str.replace(fraction, ' ' + decimal + ' ')
        
        # Нормализуем пробелы после замены
        parse_str = re.sub(r'\s+', ' ', parse_str).strip()
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "3 cups flour", "1 0.5 cups sugar", "2 Tablespoons butter", "4 large eggs"
        # Используем \b для границ слов, чтобы "l" в "large" не матчилось как "l" (liter)
        pattern = r'^([\d\s/.,]+)?\s*\b(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz\b|grams?|kilograms?|g\b|kg\b|milliliters?|liters?|ml\b|l\b|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads|batch(?:es)?|serving)\b\s*(.+)'
        
        match = re.match(pattern, parse_str, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал (например "4 large eggs" без единиц),
            # пробуем извлечь только количество и название
            simple_pattern = r'^([\d\s/.,]+)\s+(.+)'
            simple_match = re.match(simple_pattern, parse_str)
            
            if simple_match:
                amount_str, name = simple_match.groups()
                unit = None
            else:
                # Если и это не совпало, возвращаем только название
                return {
                    "name": ingredient_str,
                    "amount": None,
                    "units": None
                }
        else:
            amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            
            # Обработка дробей типа "1/2" или "1 1/2" или "1 0.5" или просто "0.5"
            if '/' in amount_str or ' ' in amount_str:
                parts = amount_str.split()
                total = 0.0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        try:
                            total += float(part)
                        except ValueError:
                            pass
                amount = total if total > 0 else None
            else:
                try:
                    # Заменяем запятые на точки и конвертируем
                    amount = float(amount_str.replace(',', '.'))
                except ValueError:
                    amount = None
            
            # Конвертируем в int если это целое число
            if amount is not None and amount == int(amount):
                amount = int(amount)
        
        # Обработка единицы измерения - сохраняем оригинальную форму
        if unit:
            unit = unit.strip()
            # Сохраняем оригинальный регистр и форму
        
        # Очистка названия - удаляем скобки с содержимым и лишние фразы
        # Удаляем вложенные скобки сначала
        while '(' in name and ')' in name:
            name = re.sub(r'\([^()]*\)', '', name)
        
        # Удаляем множественные опции типа ", vegetable, or avocado"
        name = re.sub(r',\s+\w+,\s+or\s+\w+', '', name)
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|see note|preferred|room temperature preferred|softened and cut into \d+ pieces|fresh-squeezed preferred|zest lemons before squeezing)\b', '', name, flags=re.IGNORECASE)
        name = re.sub(r'[,;)]+$', '', name)  # Удаляем лишние символы в конце
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            name = None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_recipe()
        
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        json_ld = self._get_json_ld_recipe()
        
        if json_ld and 'description' in json_ld:
            desc = self.clean_text(json_ld['description'])
            # Удаляем фразы типа "Recipe includes a how-to video!"
            desc = re.sub(r'\s*Recipe includes a how-to video!?\s*', '', desc, flags=re.IGNORECASE)
            desc = re.sub(r'\s*Includes a video tutorial!?\s*', '', desc, flags=re.IGNORECASE)
            return desc if desc else None
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients_list = []
        
        # Сначала пытаемся извлечь из JSON-LD
        json_ld = self._get_json_ld_recipe()
        
        if json_ld and 'recipeIngredient' in json_ld:
            for ingredient_str in json_ld['recipeIngredient']:
                if ingredient_str:
                    parsed = self.parse_ingredient_string(ingredient_str)
                    if parsed and parsed.get('name'):
                        ingredients_list.append(parsed)
        
        # Если JSON-LD не дал результата, пробуем HTML
        if not ingredients_list:
            ingredient_items = self.soup.find_all('li', class_='wprm-recipe-ingredient')
            
            for item in ingredient_items:
                amount_elem = item.find('span', class_='wprm-recipe-ingredient-amount')
                unit_elem = item.find('span', class_='wprm-recipe-ingredient-unit')
                name_elem = item.find('span', class_='wprm-recipe-ingredient-name')
                
                amount = None
                if amount_elem:
                    amount_text = amount_elem.get_text(strip=True)
                    # Конвертируем дроби
                    fraction_map = {
                        '½': '0.5', '¼': '0.25', '¾': '0.75',
                        '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
                    }
                    for fraction, decimal in fraction_map.items():
                        amount_text = amount_text.replace(fraction, decimal)
                    
                    if '/' in amount_text:
                        parts = amount_text.split()
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
                            amount = float(amount_text.replace(',', '.'))
                        except ValueError:
                            amount = None
                
                unit = unit_elem.get_text(strip=True) if unit_elem else None
                name = name_elem.get_text(strip=True) if name_elem else None
                
                if name:
                    ingredients_list.append({
                        "name": name,
                        "amount": amount,
                        "units": unit
                    })
        
        return json.dumps(ingredients_list, ensure_ascii=False) if ingredients_list else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пытаемся извлечь из JSON-LD
        json_ld = self._get_json_ld_recipe()
        
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        text = self.clean_text(step['text'])
                        # Убираем фразы "Set aside." в конце шагов
                        text = re.sub(r'\s*Set aside\.\s*$', '', text, flags=re.IGNORECASE)
                        # Убираем длинные пояснения в скобках
                        text = re.sub(r'\s*\(if your oven[^)]+\)\s*\.?', '', text, flags=re.IGNORECASE)
                        text = re.sub(r'\s*\(or preferred[^)]+\)\s*\.?', '', text, flags=re.IGNORECASE)
                        text = re.sub(r'\s*\(note that[^)]+\)\s*\.?', '', text, flags=re.IGNORECASE)
                        # Убираем фразы типа "The mixture will appear..."
                        text = re.sub(r'\s*The mixture will appear [^.]+\.\s*', ' ', text)
                        # Нормализуем пробелы
                        text = re.sub(r'\s+', ' ', text).strip()
                        if text:
                            steps.append(text)
                    elif isinstance(step, str):
                        text = self.clean_text(step)
                        if text:
                            steps.append(text)
        
        # Если JSON-LD не дал результата, пробуем HTML
        if not steps:
            instruction_items = self.soup.find_all('li', class_='wprm-recipe-instruction')
            
            for item in instruction_items:
                text_elem = item.find('div', class_='wprm-recipe-instruction-text')
                if text_elem:
                    step_text = text_elem.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    if step_text:
                        steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        json_ld = self._get_json_ld_recipe()
        
        if json_ld and 'recipeCategory' in json_ld:
            category = json_ld['recipeCategory']
            if isinstance(category, list):
                # Берем последнюю (обычно более специфичную) категорию
                return category[-1] if category else None
            return str(category)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self._get_json_ld_recipe()
        
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_recipe()
        
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_recipe()
        
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем в HTML
        notes_container = self.soup.find('div', class_='wprm-recipe-notes-container')
        
        if notes_container:
            notes_div = notes_container.find('div', class_='wprm-recipe-notes')
            if notes_div:
                # Собираем текст из всех span элементов с style attribute
                # Эти span содержат основной текст заметок
                paragraphs = []
                
                for span in notes_div.find_all('span', style=True):
                    text = span.get_text(strip=True)
                    text = self.clean_text(text)
                    if text and len(text) > 20:  # Минимальная длина для значимого текста
                        paragraphs.append(text)
                
                if not paragraphs:
                    return None
                
                # Объединяем и упрощаем текст
                result = ' '.join(paragraphs)
                
                # Преобразуем "I prefer to use fresh X but in a pinch frozen X will work" -> "X can be fresh or frozen"
                result = re.sub(
                    r'I prefer to use fresh (\w+) but in a pinch frozen \1 will work instead\.',
                    r'\1 can be fresh or frozen.',
                    result,
                    flags=re.IGNORECASE
                )
                
                # Удаляем детальные пояснения
                result = re.sub(r'\s*You do not need[^.]+\.', '', result, flags=re.IGNORECASE)
                result = re.sub(r'\s*Note that[^.]+\.', '', result, flags=re.IGNORECASE)
                result = re.sub(r'\s*\([^)]+\)', '', result)  # Удаляем все скобки с содержимым
                result = re.sub(r'[()]+', '', result)  # Удаляем оставшиеся скобки
                
                # Нормализуем пробелы и точки
                result = re.sub(r'\s+', ' ', result).strip()
                result = re.sub(r'\s+([.,;!?])', r'\1', result)  # Убираем пробелы перед знаками препинания
                result = re.sub(r'\.\s*\.', '.', result)
                
                # Добавляем точку в конце если её нет
                if result and not result.endswith('.'):
                    result += '.'
                
                # Если первая буква строчная, делаем заглавной
                if result and result[0].islower():
                    result = result[0].upper() + result[1:]
                
                return result if result else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        json_ld = self._get_json_ld_recipe()
        
        tags = []
        
        # Извлекаем keywords и разбиваем на отдельные слова
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if isinstance(keywords, str):
                # Разделяем по пробелам, чтобы получить отдельные слова
                words = keywords.lower().split()
                tags.extend([w.strip() for w in words if w.strip() and len(w.strip()) > 2])
            elif isinstance(keywords, list):
                for kw in keywords:
                    words = str(kw).lower().split()
                    tags.extend([w.strip() for w in words if w.strip() and len(w.strip()) > 2])
        
        # Добавляем категорию в теги
        if json_ld and 'recipeCategory' in json_ld:
            category = json_ld['recipeCategory']
            if isinstance(category, list):
                for c in category:
                    # Разделяем категории по запятым (например "Cookies, Dessert")
                    parts = str(c).split(',')
                    for part in parts:
                        tag = part.strip().lower()
                        if tag and len(tag) > 2:
                            tags.append(tag)
            elif isinstance(category, str):
                parts = category.split(',')
                for part in parts:
                    tag = part.strip().lower()
                    if tag and len(tag) > 2:
                        tags.append(tag)
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags:
            if tag and tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Извлекаем из JSON-LD
        json_ld = self._get_json_ld_recipe()
        
        if json_ld and 'image' in json_ld:
            images = json_ld['image']
            
            if isinstance(images, str):
                urls.append(images)
            elif isinstance(images, list):
                # Берем только первое изображение (обычно самое большое)
                if images:
                    urls.append(images[0])
            elif isinstance(images, dict):
                if 'url' in images:
                    urls.append(images['url'])
                elif 'contentUrl' in images:
                    urls.append(images['contentUrl'])
        
        # Если не нашли в JSON-LD, ищем в meta-тегах
        if not urls:
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Обработка HTML файлов из директории preprocessed/sugarspunrun_com"""
    import os
    
    # Определяем путь к директории с HTML файлами
    repo_root = Path(__file__).parent.parent
    preprocessed_dir = repo_root / "preprocessed" / "sugarspunrun_com"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(SugarSpunRunExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python sugarspunrun_com.py")


if __name__ == "__main__":
    main()
