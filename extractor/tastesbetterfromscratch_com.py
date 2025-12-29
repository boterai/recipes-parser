"""
Экстрактор данных рецептов для сайта tastesbetterfromscratch.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TastesBetterFromScratchExtractor(BaseRecipeExtractor):
    """Экстрактор для tastesbetterfromscratch.com"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Данные могут быть списком или словарем
                if isinstance(data, list):
                    # Ищем Recipe в списке
                    for item in data:
                        if isinstance(item, dict):
                            item_type = item.get('@type', '')
                            if isinstance(item_type, list) and 'Recipe' in item_type:
                                return item
                            elif item_type == 'Recipe':
                                return item
                elif isinstance(data, dict):
                    # Проверяем наличие @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and item.get('@type') == 'Recipe':
                                return item
                    
                    # Проверяем напрямую
                    item_type = data.get('@type', '')
                    if isinstance(item_type, list) and 'Recipe' in item_type:
                        return data
                    elif item_type == 'Recipe':
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
        
        # Конвертируем все в минуты для компактного формата
        total_minutes = hours * 60 + minutes
        
        if total_minutes == 0:
            return None
        
        # Форматируем результат
        # Если меньше 60 минут - просто минуты
        if total_minutes < 60:
            return f"{total_minutes} minutes"
        # Если кратно часам - только часы
        elif total_minutes % 60 == 0:
            hrs = total_minutes // 60
            return f"{hrs} hour{'s' if hrs > 1 else ''}"
        # Иначе - часы и минуты
        else:
            hrs = total_minutes // 60
            mins = total_minutes % 60
            return f"{hrs} hour{'s' if hrs > 1 else ''} {mins} minutes"
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Альтернатива - из заголовка страницы
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Из meta title
        title = self.soup.find('title')
        if title:
            text = title.get_text()
            # Убираем суффиксы
            text = re.sub(r'\s*-.*$', '', text)
            text = re.sub(r'\s+Recipe.*$', '', text, flags=re.IGNORECASE)
            return self.clean_text(text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
        # Альтернатива - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате списка словарей"""
        ingredients = []
        
        # Сначала пробуем извлечь из структурированных HTML элементов (WPRM plugin)
        ingredient_lis = self.soup.find_all('li', class_=re.compile(r'wprm-recipe-ingredient'))
        
        if ingredient_lis:
            for li in ingredient_lis:
                # Извлекаем amount, unit, name из структурированных элементов
                amount_elem = li.find(class_='wprm-recipe-ingredient-amount')
                unit_elem = li.find(class_='wprm-recipe-ingredient-unit')
                name_elem = li.find(class_='wprm-recipe-ingredient-name')
                
                amount = amount_elem.get_text(strip=True) if amount_elem else None
                unit = unit_elem.get_text(strip=True) if unit_elem else None
                name = name_elem.get_text(strip=True) if name_elem else None
                
                if name:
                    # Очищаем название
                    name = self.clean_text(name)
                    
                    ingredients.append({
                        "name": name,
                        "amount": amount,
                        "units": unit
                    })
        
        # Если не нашли в WPRM, пробуем JSON-LD
        if not ingredients:
            json_ld = self._get_json_ld_data()
            
            if json_ld and 'recipeIngredient' in json_ld:
                for ingredient_text in json_ld['recipeIngredient']:
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour"
            
        Returns:
            dict: {"name": "flour", "amount": "1", "units": "cup"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Список единиц измерения
        units = [
            'cups?', 'tablespoons?', 'teaspoons?', 'tbsps?', 'tsps?',
            'pounds?', 'ounces?', 'lbs?', 'oz',
            'grams?', 'kilograms?', 'g', 'kg',
            'milliliters?', 'liters?', 'ml', 'l',
            'pinch(?:es)?', 'dash(?:es)?',
            'packages?', 'packs?', 'cans?', 'jars?', 'bottles?',
            'inch(?:es)?', 'slices?', 'cloves?', 'bunches?', 'sprigs?',
            'whole', 'halves?', 'quarters?', 'pieces?',
            'head', 'heads', 'batch(?:es)?', 'batches?'
        ]
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1 cup flour", "2 tablespoons butter", "1/2 teaspoon salt"
        units_pattern = '|'.join(units)
        pattern = rf'^([\d\s/.,–-]+)?\s*({units_pattern})?\s*(.+)'
        
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
            amount_str = amount_str.strip().replace('–', '-')
            # Если есть диапазон (например "3 ¾ – 4" или "3 3/4-4")
            if '-' in amount_str and not amount_str.startswith('-'):
                # Проверяем, это диапазон или просто дробь
                # Если после дефиса идет только число (не дробь), это диапазон
                if re.search(r'-\s*\d+\s*$', amount_str):
                    # Диапазон - возвращаем как есть
                    amount = amount_str
                else:
                    # Это может быть "3/4-4" что означает диапазон от 3/4 до 4
                    # Или "3 3/4-4" что означает от 3 3/4 до 4
                    # Возвращаем как есть
                    amount = amount_str
            # Обработка дробей типа "1/2" или "1 1/2"
            elif '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        # Проверяем, что это действительная дробь
                        frac_parts = part.split('/')
                        if len(frac_parts) == 2:
                            try:
                                num = float(frac_parts[0])
                                denom = float(frac_parts[1])
                                total += num / denom
                            except ValueError:
                                # Не можем парсить - возвращаем как есть
                                amount = amount_str
                                break
                    else:
                        try:
                            total += float(part)
                        except ValueError:
                            amount = amount_str
                            break
                else:
                    # Возвращаем как строку, возможно с дробью
                    if total == int(total):
                        amount = str(int(total))
                    else:
                        amount = str(total)
            else:
                try:
                    val = float(amount_str.replace(',', '.'))
                    # Возвращаем как строку
                    amount = str(int(val)) if val == int(val) else str(val)
                except (ValueError, TypeError):
                    amount = amount_str
        
        # Обработка единицы измерения
        units = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|for serving|homemade|store-bought)\b', '', name, flags=re.IGNORECASE)
        # Удаляем специфичные суффиксы вроде ", drained", ", grated" и т.д.
        name = re.sub(r',\s*(drained|grated|sliced|chopped|minced|crushed|fresh or frozen|my recipe makes.*|or store-bought).*$', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;:]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                step_num = 1
                for item in instructions:
                    if isinstance(item, dict):
                        # Check if it's a HowToSection with itemListElement
                        if item.get('@type') == 'HowToSection' and 'itemListElement' in item:
                            # Process each step in the section
                            for substep in item['itemListElement']:
                                if isinstance(substep, dict) and 'text' in substep:
                                    step_text = self.clean_text(substep['text'])
                                    steps.append(f"{step_num}. {step_text}")
                                    step_num += 1
                        # Regular HowToStep
                        elif 'text' in item:
                            step_text = self.clean_text(item['text'])
                            steps.append(f"{step_num}. {step_text}")
                            step_num += 1
                    elif isinstance(item, str):
                        step_text = self.clean_text(item)
                        steps.append(f"{step_num}. {step_text}")
                        step_num += 1
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'nutrition' in json_ld:
            nutrition = json_ld['nutrition']
            
            # Извлекаем все доступные данные о питательности
            parts = []
            
            # Калории
            if 'calories' in nutrition:
                cal_text = str(nutrition['calories'])
                # Извлекаем только число
                cal_match = re.search(r'(\d+)', cal_text)
                if cal_match:
                    calories = cal_match.group(1)
                    parts.append(f"Calories: {calories} kcal")
            
            # Углеводы
            if 'carbohydrateContent' in nutrition:
                carb_text = str(nutrition['carbohydrateContent'])
                carb_match = re.search(r'([\d.]+)\s*g', carb_text)
                if carb_match:
                    val = carb_match.group(1)
                    # Удаляем .0 если есть
                    if '.' in val and float(val) == int(float(val)):
                        val = str(int(float(val)))
                    parts.append(f"Carbohydrates: {val} g")
            
            # Белки
            if 'proteinContent' in nutrition:
                prot_text = str(nutrition['proteinContent'])
                prot_match = re.search(r'([\d.]+)\s*g', prot_text)
                if prot_match:
                    val = prot_match.group(1)
                    if '.' in val and float(val) == int(float(val)):
                        val = str(int(float(val)))
                    parts.append(f"Protein: {val} g")
            
            # Жиры
            if 'fatContent' in nutrition:
                fat_text = str(nutrition['fatContent'])
                fat_match = re.search(r'([\d.]+)\s*g', fat_text)
                if fat_match:
                    val = fat_match.group(1)
                    if '.' in val and float(val) == int(float(val)):
                        val = str(int(float(val)))
                    parts.append(f"Fat: {val} g")
            
            # Насыщенные жиры
            if 'saturatedFatContent' in nutrition:
                sat_fat_text = str(nutrition['saturatedFatContent'])
                sat_fat_match = re.search(r'([\d.]+)\s*g', sat_fat_text)
                if sat_fat_match:
                    val = sat_fat_match.group(1)
                    if '.' in val and float(val) == int(float(val)):
                        val = str(int(float(val)))
                    parts.append(f"Saturated Fat: {val} g")
            
            # Холестерин
            if 'cholesterolContent' in nutrition:
                chol_text = str(nutrition['cholesterolContent'])
                chol_match = re.search(r'([\d.]+)\s*mg', chol_text)
                if chol_match:
                    val = chol_match.group(1)
                    if '.' in val and float(val) == int(float(val)):
                        val = str(int(float(val)))
                    parts.append(f"Cholesterol: {val} mg")
            
            # Натрий
            if 'sodiumContent' in nutrition:
                sodium_text = str(nutrition['sodiumContent'])
                sodium_match = re.search(r'([\d.]+)\s*mg', sodium_text)
                if sodium_match:
                    val = sodium_match.group(1)
                    if '.' in val and float(val) == int(float(val)):
                        val = str(int(float(val)))
                    parts.append(f"Sodium: {val} mg")
            
            # Калий
            if 'potassiumContent' in nutrition:
                potassium_text = str(nutrition['potassiumContent'])
                potassium_match = re.search(r'([\d.]+)\s*mg', potassium_text)
                if potassium_match:
                    val = potassium_match.group(1)
                    if '.' in val and float(val) == int(float(val)):
                        val = str(int(float(val)))
                    parts.append(f"Potassium: {val} mg")
            
            # Клетчатка
            if 'fiberContent' in nutrition:
                fiber_text = str(nutrition['fiberContent'])
                fiber_match = re.search(r'([\d.]+)\s*g', fiber_text)
                if fiber_match:
                    val = fiber_match.group(1)
                    if '.' in val and float(val) == int(float(val)):
                        val = str(int(float(val)))
                    parts.append(f"Fiber: {val} g")
            
            # Сахар
            if 'sugarContent' in nutrition:
                sugar_text = str(nutrition['sugarContent'])
                sugar_match = re.search(r'([\d.]+)\s*g', sugar_text)
                if sugar_match:
                    val = sugar_match.group(1)
                    if '.' in val and float(val) == int(float(val)):
                        val = str(int(float(val)))
                    parts.append(f"Sugar: {val} g")
            
            # Возвращаем все части через запятую и пробел
            return ', '.join(parts) if parts else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        json_ld = self._get_json_ld_data()
        
        if json_ld:
            # Пробуем recipeCategory
            if 'recipeCategory' in json_ld:
                category = json_ld['recipeCategory']
                if isinstance(category, list):
                    return ', '.join(category)
                return str(category)
            
            # Пробуем recipeCuisine
            if 'recipeCuisine' in json_ld:
                cuisine = json_ld['recipeCuisine']
                if isinstance(cuisine, list):
                    return ', '.join(cuisine)
                return str(cuisine)
        
        # Альтернатива - из meta тегов
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов из параграфов статьи"""
        # Поищем в параграфах после рецепта
        # Обычно заметки содержат ключевые фразы
        note_keywords = [
            'if it\'s your first time',
            'you can use',
            'feel free to',
            'you can also',
            'tip:',
            'note:',
            'variations include',
            'you can substitute',
            'store-bought',
            'homemade'
        ]
        
        # Ищем параграфы на странице
        paragraphs = self.soup.find_all('p')
        for p in paragraphs:
            text = p.get_text(strip=True)
            text_lower = text.lower()
            
            for keyword in note_keywords:
                if keyword in text_lower:
                    cleaned_text = self.clean_text(text)
                    # Ограничиваем длину заметки
                    if len(cleaned_text) > 500:
                        # Берем первые несколько предложений
                        sentences = re.split(r'(?<=[.!?])\s+', cleaned_text)
                        result = []
                        length = 0
                        for sentence in sentences:
                            if length + len(sentence) <= 500:
                                result.append(sentence)
                                length += len(sentence)
                            else:
                                break
                        return ' '.join(result) if result else cleaned_text[:500]
                    return cleaned_text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        json_ld = self._get_json_ld_data()
        
        tags_set = set()
        
        # Из JSON-LD keywords
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if isinstance(keywords, str):
                # Разбиваем по запятой
                for tag in keywords.split(','):
                    tag = tag.strip().lower()
                    if tag and len(tag) >= 3:
                        tags_set.add(tag)
            elif isinstance(keywords, list):
                for tag in keywords:
                    tag = str(tag).strip().lower()
                    if tag and len(tag) >= 3:
                        tags_set.add(tag)
        
        # Также пробуем из категорий
        if json_ld and 'recipeCategory' in json_ld:
            category = json_ld['recipeCategory']
            if isinstance(category, list):
                for cat in category:
                    cat = str(cat).strip().lower()
                    if cat and len(cat) >= 3:
                        tags_set.add(cat)
            elif isinstance(category, str):
                cat = category.strip().lower()
                if cat and len(cat) >= 3:
                    tags_set.add(cat)
        
        # Фильтрация стоп-слов
        stopwords = {'recipe', 'recipes', 'easy', 'quick', 'simple', 'best', 'homemade'}
        tags_set = {tag for tag in tags_set if tag not in stopwords}
        
        # Возвращаем как строку через запятую с пробелом
        return ', '.join(sorted(tags_set)) if tags_set else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        if 'url' in item:
                            urls.append(item['url'])
                        elif 'contentUrl' in item:
                            urls.append(item['contentUrl'])
        
        # Дополнительно ищем в meta тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
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
    preprocessed_dir = os.path.join("preprocessed", "tastesbetterfromscratch_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(TastesBetterFromScratchExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python tastesbetterfromscratch_com.py")


if __name__ == "__main__":
    main()
