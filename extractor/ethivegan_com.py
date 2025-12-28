"""
Экстрактор данных рецептов для сайта ethivegan.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class EthiveganExtractor(BaseRecipeExtractor):
    """Экстрактор для ethivegan.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем извлечь из JSON-LD recipe schema
        json_ld_scripts = self.soup.find_all('script', class_='penci-recipe-schema')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'name' in data:
                    return self.clean_text(data['name'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - ищем в HTML
        recipe_title = self.soup.find('h2', class_='recipe-title-nooverlay')
        if recipe_title:
            return self.clean_text(recipe_title.get_text())
        
        # Ищем в заголовке страницы
        h1 = self.soup.find('h1', class_='single-post-title')
        if h1:
            return self.clean_text(h1.get_text())
        
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
    
    def parse_ingredient_text(self, ingredient_text: str) -> dict:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "160g almonds, ground" или "½ tsp almond extract"
            
        Returns:
            dict: {"name": "almonds", "amount": "160", "unit": "g"}
        """
        if not ingredient_text:
            return {"name": None, "amount": None, "unit": None}
        
        # Очистка текста
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
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "160g almonds", "0.5 tsp almond extract", "Pinch of cream of tartar"
        pattern = r'^([\d\s/.,]+)?\s*(g|kg|ml|l|tsp|tbsp|tbs|tablespoon|teaspoon|cup|cups|pinch|bunch|cloves?|inch|medium size|small|large|for dusting)?(?:\s+of)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем всю строку как название
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
            # Обработка дробей типа "1/2"
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
                    amount = amount_str.strip()
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем запятые в начале
        name = re.sub(r'^,\s*', '', name)
        # Удаляем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем извлечь из JSON-LD recipe schema
        json_ld_scripts = self.soup.find_all('script', class_='penci-recipe-schema')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'recipeIngredient' in data:
                    for ingredient_text in data['recipeIngredient']:
                        parsed = self.parse_ingredient_text(ingredient_text)
                        if parsed and parsed.get('name'):
                            ingredients.append(parsed)
                    
                    if ingredients:
                        return json.dumps(ingredients, ensure_ascii=False)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем извлечь из JSON-LD recipe schema
        json_ld_scripts = self.soup.find_all('script', class_='penci-recipe-schema')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'recipeInstructions' in data:
                    instructions = data['recipeInstructions']
                    if isinstance(instructions, list):
                        for step in instructions:
                            if isinstance(step, dict) and 'text' in step:
                                steps.append(step['text'])
                            elif isinstance(step, str):
                                steps.append(step)
                    elif isinstance(instructions, str):
                        return self.clean_text(instructions)
                    
                    if steps:
                        return ' '.join(steps)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности в формате: 202 kcal; 2/11/27"""
        
        # Сначала пробуем извлечь из JSON-LD recipe schema
        json_ld_scripts = self.soup.find_all('script', class_='penci-recipe-schema')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'nutrition' in data:
                    nutrition = data['nutrition']
                    
                    # Извлекаем калории и жиры
                    calories = None
                    fat = None
                    
                    if 'calories' in nutrition:
                        cal_text = str(nutrition['calories'])
                        # Извлекаем только число
                        cal_match = re.search(r'(\d+)', cal_text)
                        if cal_match:
                            calories = cal_match.group(1)
                    
                    if 'fatContent' in nutrition:
                        fat_text = str(nutrition['fatContent'])
                        fat_match = re.search(r'(\d+)', fat_text)
                        if fat_match:
                            fat = fat_match.group(1)
                    
                    # Форматируем результат
                    if calories and fat:
                        return f"{calories} calories, {fat} grams fat"
                    elif calories:
                        return f"{calories} calories"
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', class_='penci-recipe-schema')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'recipeCategory' in data:
                    category = self.clean_text(data['recipeCategory'])
                    # Если это "Recipes", пробуем найти более специфичную категорию
                    if category and category.lower() != 'recipes':
                        return category
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из категорий на странице
        cat_links = self.soup.find_all('a', class_='penci-cat-name')
        if cat_links:
            # Ищем первую категорию, которая не "Recipes"
            for link in cat_links:
                cat_text = self.clean_text(link.get_text())
                if cat_text and cat_text.lower() != 'recipes':
                    return cat_text
            # Если все категории "Recipes", берем первую
            return self.clean_text(cat_links[0].get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', class_='penci-recipe-schema')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'prepTime' in data:
                    # prepTime может быть в формате ISO 8601 "PT25M" или пустым "PT"
                    prep_time = data['prepTime']
                    if prep_time and prep_time != 'PT':
                        # Конвертируем ISO в читаемый формат
                        return self.parse_iso_duration(prep_time)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из HTML
        prep_time_elem = self.soup.find('span', class_='remeta-item', string=re.compile(r'Prep Time', re.I))
        if prep_time_elem and prep_time_elem.find_next('time'):
            time_elem = prep_time_elem.find_next('time')
            return self.clean_text(time_elem.get_text())
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', class_='penci-recipe-schema')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'cookTime' in data:
                    cook_time = data['cookTime']
                    if cook_time and cook_time != 'PT':
                        return self.parse_iso_duration(cook_time)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из HTML
        cook_time_elem = self.soup.find('span', class_='remeta-item', string=re.compile(r'Cooking Time', re.I))
        if cook_time_elem and cook_time_elem.find_next('time'):
            time_elem = cook_time_elem.find_next('time')
            return self.clean_text(time_elem.get_text())
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', class_='penci-recipe-schema')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'totalTime' in data:
                    total_time = data['totalTime']
                    if total_time and total_time != 'PT':
                        return self.parse_iso_duration(total_time)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если нет в JSON-LD, пробуем посчитать из prep_time + cook_time
        prep_time_str = self.extract_prep_time()
        cook_time_str = self.extract_cook_time()
        
        if prep_time_str and cook_time_str:
            # Парсим минуты из строк вида "25 mins" или "1 hour 30 mins"
            prep_mins = self._parse_time_to_minutes(prep_time_str)
            cook_mins = self._parse_time_to_minutes(cook_time_str)
            
            if prep_mins is not None and cook_mins is not None:
                total_mins = prep_mins + cook_mins
                return self._minutes_to_time_str(total_mins)
        
        return None
    
    @staticmethod
    def _parse_time_to_minutes(time_str: str) -> Optional[int]:
        """Парсит строку времени в минуты"""
        if not time_str:
            return None
        
        total_minutes = 0
        
        # Извлекаем часы
        hour_match = re.search(r'(\d+)\s*hour', time_str, re.IGNORECASE)
        if hour_match:
            total_minutes += int(hour_match.group(1)) * 60
        
        # Извлекаем минуты
        min_match = re.search(r'(\d+)\s*mins?', time_str, re.IGNORECASE)
        if min_match:
            total_minutes += int(min_match.group(1))
        
        return total_minutes if total_minutes > 0 else None
    
    @staticmethod
    def _minutes_to_time_str(minutes: int) -> str:
        """Конвертирует минуты в строку времени"""
        hours = minutes // 60
        mins = minutes % 60
        
        if hours > 0 and mins > 0:
            return f"{hours} hour {mins} mins"
        elif hours > 0:
            return f"{hours} hour"
        else:
            return f"{mins} mins"
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "20 mins" или "1 hour 30 mins"
        """
        if not duration or not duration.startswith('PT'):
            return None
        
        duration = duration[2:]  # Убираем "PT"
        
        if not duration:
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
        
        # Форматируем результат
        if hours > 0 and minutes > 0:
            return f"{hours} hour {minutes} mins"
        elif hours > 0:
            return f"{hours} hour"
        elif minutes > 0:
            return f"{minutes} mins"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем в тексте статьи параграфы, которые могут содержать заметки
        # Обычно это текст с информацией о вегане/безглютене и ингредиентах
        
        notes_texts = []
        paragraphs = self.soup.find_all('p')
        
        for p in paragraphs:
            text = p.get_text(strip=True)
            
            # Ищем короткие заметки о свойствах рецепта
            if re.search(r'is vegan and gluten-free', text, re.IGNORECASE):
                notes_texts.append(self.clean_text(text))
            # Ищем информацию о ингредиентах
            elif re.search(r'you can purchase at your local', text, re.IGNORECASE):
                notes_texts.append(self.clean_text(text))
        
        if notes_texts:
            return ' '.join(notes_texts)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Извлекаем теги из категорий на странице
        cat_links = self.soup.find_all('a', class_='penci-cat-name')
        if cat_links:
            tags = []
            # Пропускаем слишком общие категории
            generic_categories = {'recipes', 'world cuisines', 'vegan recipes'}
            
            for link in cat_links:
                cat_text = self.clean_text(link.get_text())
                if cat_text and cat_text.lower() not in generic_categories:
                    tags.append(cat_text)
            
            if tags:
                # Удаляем дубликаты
                unique_tags = []
                seen = set()
                for tag in tags:
                    tag_lower = tag.lower()
                    if tag_lower not in seen:
                        seen.add(tag_lower)
                        unique_tags.append(tag)
                return ', '.join(unique_tags)
        
        # Если категорий нет или все generic, возвращаем None
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в JSON-LD recipe schema
        json_ld_scripts = self.soup.find_all('script', class_='penci-recipe-schema')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe' and 'image' in data:
                    img = data['image']
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, list):
                        urls.extend([i for i in img if isinstance(i, str)])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 2. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
                    if len(unique_urls) >= 3:  # Ограничиваем до 3 изображений
                        break
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
    # Обрабатываем папку preprocessed/ethivegan_com
    recipes_dir = os.path.join("preprocessed", "ethivegan_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(EthiveganExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python ethivegan_com.py")


if __name__ == "__main__":
    main()
