"""
Экстрактор данных рецептов для сайта gezondweekmenu.nl
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class GezondWeekmenuExtractor(BaseRecipeExtractor):
    """Экстрактор для gezondweekmenu.nl"""
    
    def __init__(self, html_path: str):
        """Инициализация с кешированием данных"""
        super().__init__(html_path)
        self._json_ld_cache = None
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы с кешированием"""
        if self._json_ld_cache is not None:
            return self._json_ld_cache
        
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Проверяем @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            self._json_ld_cache = item
                            return item
                
                # Данные могут быть списком или словарем
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            self._json_ld_cache = item
                            return item
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    self._json_ld_cache = data
                    return data
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        self._json_ld_cache = {}
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "P0DT0H15M"
            
        Returns:
            Время в формате "20 minutes" или "1 hour 30 minutes"
        """
        if not duration:
            return None
        
        # Убираем "P" и разбиваем по "T"
        duration = duration.replace('P', '')
        
        # Обрабатываем формат P0DT0H15M (дни + время)
        if 'D' in duration:
            parts = duration.split('T')
            if len(parts) == 2:
                duration = parts[1]  # Берем только часть после T
            else:
                duration = duration.replace('D', '')
        
        if duration.startswith('T'):
            duration = duration[1:]  # Убираем "T"
        
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
            return f"{hours} hour {minutes} minutes" if hours == 1 else f"{hours} hours {minutes} minutes"
        elif hours > 0:
            return f"{hours} hour" if hours == 1 else f"{hours} hours"
        elif minutes > 0:
            return f"{minutes} minutes"
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self._get_json_ld_data()
        
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Fallback: ищем в заголовке
        title = self.soup.find('h1', class_='entry-title')
        if title:
            return self.clean_text(title.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self._get_json_ld_data()
        
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            if desc:
                return self.clean_text(desc)
        
        # Fallback: meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient_text(self, ingredient_text: str) -> dict:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "40 gram havermout" или "1 ei"
            
        Returns:
            dict: {"name": "havermout", "amount": 40, "unit": "gram"}
        """
        if not ingredient_text:
            return {"name": None, "amount": None, "units": None}
        
        text = self.clean_text(ingredient_text).strip()
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "40 gram havermout", "1 ei", "150 g pancetta", "3 grote eieren"
        pattern = r'^([\d\s.,/]+)?\s*(gram|g|ml|l|eetlepel|theelepel|stuk|stuks|el|tl|kg|kilo)?\s*(.+?)$'
        
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
            amount_str = amount_str.strip().replace(',', '.')
            try:
                # Обработка дробей типа "1/2"
                if '/' in amount_str:
                    parts = amount_str.split('/')
                    amount = float(parts[0]) / float(parts[1])
                else:
                    amount = float(amount_str) if '.' in amount_str else int(float(amount_str))
            except ValueError:
                amount = None
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        name = name.strip()
        # Удаляем фразы "naar smaak", "optioneel", и подобные
        name = re.sub(r'\b(naar smaak|optioneel|voor het koken van|voor garnering)\b', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\s+', ' ', name).strip()
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Сначала пробуем извлечь из HTML (более точно)
        ingredients_div = self.soup.find('div', class_='mv-create-ingredients')
        
        if ingredients_div:
            # Находим все элементы списка ингредиентов
            ingredient_items = ingredients_div.find_all('li')
            
            for item in ingredient_items:
                # Извлекаем текст, игнорируя спонсорские элементы
                text = item.get_text(separator=' ', strip=True)
                
                # Убираем бренды в скобках (например, "(Quaker)")
                text = re.sub(r'\s*\([^)]+\)\s*$', '', text)
                
                if text and len(text) > 1:
                    parsed = self.parse_ingredient_text(text)
                    if parsed['name']:
                        ingredients.append(parsed)
        
        # Если не нашли в HTML, пробуем JSON-LD (fallback)
        if not ingredients:
            recipe_data = self._get_json_ld_data()
            if recipe_data and 'recipeIngredient' in recipe_data:
                for ing_text in recipe_data['recipeIngredient']:
                    if ing_text:
                        parsed = self.parse_ingredient_text(ing_text)
                        if parsed['name']:
                            ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self._get_json_ld_data()
        
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        if step_text:
                            steps.append(f"{idx}. {step_text}")
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        if step_text:
                            steps.append(f"{idx}. {step_text}")
            elif isinstance(instructions, str):
                return self.clean_text(instructions)
            
            if steps:
                return ' '.join(steps)
        
        # Fallback: ищем в HTML
        instructions_div = self.soup.find('ol', class_='mv-create-instructions')
        if instructions_div:
            steps = []
            for idx, li in enumerate(instructions_div.find_all('li'), 1):
                text = self.clean_text(li.get_text())
                if text:
                    steps.append(f"{idx}. {text}")
            if steps:
                return ' '.join(steps)
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """
        Извлечение информации о питательности
        Формат: "330 kcal; 10/20/30" (калории; белки/жиры/углеводы)
        """
        recipe_data = self._get_json_ld_data()
        
        if recipe_data and 'nutrition' in recipe_data:
            nutrition = recipe_data['nutrition']
            
            if isinstance(nutrition, dict):
                # Извлекаем калории
                calories = None
                if 'calories' in nutrition:
                    cal_text = str(nutrition['calories'])
                    cal_match = re.search(r'(\d+)', cal_text)
                    if cal_match:
                        calories = cal_match.group(1)
                
                # Извлекаем БЖУ
                protein = None
                fat = None
                carbs = None
                
                if 'proteinContent' in nutrition:
                    prot_text = str(nutrition['proteinContent'])
                    prot_match = re.search(r'(\d+)', prot_text)
                    if prot_match:
                        protein = prot_match.group(1)
                
                if 'fatContent' in nutrition:
                    fat_text = str(nutrition['fatContent'])
                    fat_match = re.search(r'(\d+)', fat_text)
                    if fat_match:
                        fat = fat_match.group(1)
                
                if 'carbohydrateContent' in nutrition:
                    carb_text = str(nutrition['carbohydrateContent'])
                    carb_match = re.search(r'(\d+)', carb_text)
                    if carb_match:
                        carbs = carb_match.group(1)
                
                # Форматируем результат
                if calories:
                    if protein and fat and carbs:
                        return f"{calories} kcal; {protein}/{fat}/{carbs}"
                    else:
                        return f"{calories} kcal"
        
        # Fallback: ищем в тексте страницы
        # Поиск фраз типа "Deze bananenpannenkoek bevat zo'n 330 kcal"
        text_content = self.soup.get_text()
        cal_match = re.search(r'(\d+)\s*kcal', text_content, re.IGNORECASE)
        if cal_match:
            calories = cal_match.group(1)
            return f"Deze bananenpannenkoek bevat zo'n {calories} kcal."
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self._get_json_ld_data()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            if category:
                # Преобразуем "Recepten" в более понятную категорию
                if category.lower() == 'recepten':
                    # Пробуем определить категорию по тегам или контексту
                    keywords = recipe_data.get('keywords', '')
                    if 'ontbijt' in keywords.lower():
                        return 'Breakfast'
                    elif any(word in keywords.lower() for word in ['hoofdgerecht', 'lunch', 'diner']):
                        return 'Main Course'
                    elif 'dessert' in keywords.lower():
                        return 'Dessert'
                    else:
                        return 'Breakfast'  # По умолчанию
                return self.clean_text(category)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_json_ld_data()
        
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self._get_json_ld_data()
        
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_json_ld_data()
        
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем секцию с заметками/советами после рецепта
        notes_sections = self.soup.find_all(['p', 'div'], class_=re.compile(r'note|tip|variatie', re.I))
        
        if notes_sections:
            for section in notes_sections:
                text = self.clean_text(section.get_text())
                # Ищем фразы с вариациями
                if text and ('variëren' in text.lower() or 'variatie' in text.lower() or 'tip' in text.lower()):
                    return text
        
        # Ищем в тексте страницы фразы о вариациях
        paragraphs = self.soup.find_all('p')
        for p in paragraphs:
            text = self.clean_text(p.get_text())
            if text and ('variëren' in text.lower() or 'kun je' in text.lower()):
                # Если фраза короткая и содержит полезную информацию
                if 50 < len(text) < 300:
                    return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        recipe_data = self._get_json_ld_data()
        
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if keywords:
                # keywords может быть строкой с разделителями
                if isinstance(keywords, str):
                    # Разбиваем по запятым и очищаем
                    tags = [self.clean_text(tag) for tag in keywords.split(',')]
                    tags = [tag for tag in tags if tag and len(tag) > 2]
                    # Оставляем только первые 5-6 наиболее релевантных тегов
                    # Фильтруем очень длинные теги (вероятно, это фразы)
                    tags = [tag for tag in tags if len(tag) < 50][:6]
                    if tags:
                        return ', '.join(tags)
        
        # Fallback: ищем meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        recipe_data = self._get_json_ld_data()
        
        if recipe_data and 'image' in recipe_data:
            images = recipe_data['image']
            if isinstance(images, list):
                # Берем первые 3 изображения
                for img in images[:3]:
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, dict) and 'url' in img:
                        urls.append(img['url'])
            elif isinstance(images, str):
                urls.append(images)
        
        # Дополнительно: ищем og:image
        if len(urls) < 3:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                img_url = og_image['content']
                if img_url not in urls:
                    urls.append(img_url)
        
        if urls:
            return ','.join(urls)
        
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
    # Обрабатываем папку preprocessed/gezondweekmenu_nl
    recipes_dir = os.path.join("preprocessed", "gezondweekmenu_nl")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(GezondWeekmenuExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python gezondweekmenu_nl.py")


if __name__ == "__main__":
    main()
