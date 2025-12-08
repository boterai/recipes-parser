"""
Экстрактор данных рецептов для сайта recipe.sgethai.com (Thai recipes)
Наследует структуру от AllRecipesExtractor
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class RecipeSgethaiExtractor(BaseRecipeExtractor):
    """Экстрактор для recipe.sgethai.com (Thai cuisine)"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в формат 'X นาที' (минуты на тайском)
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "X นาที", например "90 นาที"
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
        
        return f"{total_minutes} นาที" if total_minutes > 0 else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из HTML"""
        # Ищем в JSON-LD (самый надежный способ)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            name = item.get('name')
                            if name:
                                # Убираем префиксы типа "วิธีทำ " из названия
                                name = re.sub(r'^วิธีทำ\s+', '', name)
                                # Убираем суффиксы
                                name = re.sub(r'\s+เมนูอาหาร.*$', '', name)
                                return self.clean_text(name)
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        # Альтернативно - из H1
        h1 = self.soup.find('h1')
        if h1:
            title = h1.get_text()
            # Убираем префиксы и суффиксы
            title = re.sub(r'^วิธีทำ\s+', '', title)
            title = re.sub(r'\s+เมนูอาหาร.*$', '', title)
            return self.clean_text(title)
        
        # Из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'^วิธีทำ\s+', '', title)
            title = re.sub(r'\s+เมนูอาหาร.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            desc = item.get('description')
                            if desc:
                                return self.clean_text(desc)
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        # Из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD"""
        # Ищем в JSON-LD (основной источник)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            recipe_ingredients = item.get('recipeIngredient')
                            if recipe_ingredients and isinstance(recipe_ingredients, list):
                                # Парсим каждый ингредиент
                                ingredients = []
                                for ing_text in recipe_ingredients:
                                    parsed = self.parse_ingredient(ing_text)
                                    if parsed:
                                        ingredients.append(parsed)
                                
                                if ingredients:
                                    return json.dumps(ingredients, ensure_ascii=False)
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        # Если JSON-LD не дал результата, ищем в HTML
        ingredients = []
        ingredient_list = self.soup.find('ul', class_=re.compile(r'fusion-checklist.*', re.I))
        
        if ingredient_list:
            items = ingredient_list.find_all('li')
            for item in items:
                content_div = item.find('div', class_='fusion-li-item-content')
                if content_div:
                    ing_text = content_div.get_text(strip=True)
                    parsed = self.parse_ingredient(ing_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления из JSON-LD"""
        steps = []
        
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            instructions = item.get('recipeInstructions')
                            if instructions and isinstance(instructions, list):
                                step_num = 1
                                for section in instructions:
                                    if isinstance(section, dict) and section.get('@type') == 'HowToSection':
                                        # Обрабатываем секцию
                                        item_list = section.get('itemListElement', [])
                                        for step_item in item_list:
                                            if isinstance(step_item, dict) and step_item.get('@type') == 'HowtoStep':
                                                step_text = step_item.get('text')
                                                if step_text:
                                                    steps.append(f"{step_num}. {step_text}")
                                                    step_num += 1
                                
                                if steps:
                                    return ' '.join(steps)
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        # Если JSON-LD не дал результата, ищем в HTML
        step_list = self.soup.find('ul', class_=re.compile(r'fusion-checklist.*type-numbered', re.I))
        
        if step_list:
            items = step_list.find_all('li')
            for idx, item in enumerate(items, 1):
                content_div = item.find('div', class_='fusion-li-item-content')
                if content_div:
                    step_text = content_div.get_text(strip=True)
                    steps.append(f"{idx}. {step_text}")
        
        return ' '.join(steps) if steps else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            nutrition = item.get('nutrition')
                            if nutrition and isinstance(nutrition, dict):
                                calories = nutrition.get('calories')
                                if calories:
                                    # Извлекаем только число из калорий
                                    cal_match = re.search(r'([\d,]+)', str(calories))
                                    if cal_match:
                                        return f"แคลอรี่: {cal_match.group(1)}"
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        # Если JSON-LD не дал результата, ищем в HTML
        nutrition_list = self.soup.find_all('ul', class_=re.compile(r'fusion-checklist', re.I))
        
        for ul in nutrition_list:
            items = ul.find_all('li')
            nutrition_parts = []
            
            for item in items:
                content = item.find('div', class_='fusion-li-item-content')
                if content:
                    text = content.get_text(strip=True)
                    # Ищем питательные элементы
                    if any(keyword in text for keyword in ['แคลอรี่', 'คาร์โบไฮเดรต', 'ไขมัน', 'โปรตีน']):
                        nutrition_parts.append(text)
            
            if nutrition_parts:
                return ', '.join(nutrition_parts)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов - не поддерживается на recipe.sgethai.com"""
        # На сайте recipe.sgethai.com нет структуры тегов
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            category = item.get('recipeCategory')
                            if category:
                                return self.clean_text(category)
                            
                            # Альтернативно - из cuisine
                            cuisine = item.get('recipeCuisine')
                            if cuisine:
                                return self.clean_text(cuisine)
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        # Из breadcrumbs
        breadcrumbs = self.soup.find('nav', class_='fusion-breadcrumbs')
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                # Берем последнюю категорию
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            prep_time = item.get('prepTime')
                            if prep_time:
                                return self.parse_iso_duration(prep_time)
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        # Ищем в HTML по паттерну "เวลาเตรียม"
        checklist = self.soup.find('ul', class_=re.compile(r'fusion-checklist', re.I))
        if checklist:
            items = checklist.find_all('li')
            for item in items:
                content = item.find('div', class_='fusion-li-item-content')
                if content:
                    text = content.get_text(strip=True)
                    if 'เวลาเตรียม' in text:
                        # Извлекаем время
                        time_match = re.search(r'(\d+)\s*นาที', text)
                        if time_match:
                            return f"{time_match.group(1)} นาที"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            cook_time = item.get('cookTime')
                            if cook_time:
                                return self.parse_iso_duration(cook_time)
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        # Ищем в HTML по паттерну "เวลาปรุง"
        checklist = self.soup.find('ul', class_=re.compile(r'fusion-checklist', re.I))
        if checklist:
            items = checklist.find_all('li')
            for item in items:
                content = item.find('div', class_='fusion-li-item-content')
                if content:
                    text = content.get_text(strip=True)
                    if 'เวลาปรุง' in text:
                        time_match = re.search(r'(\d+)\s*นาที', text)
                        if time_match:
                            return f"{time_match.group(1)} นาที"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            total_time = item.get('totalTime')
                            if total_time:
                                return self.parse_iso_duration(total_time)
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        # Ищем в HTML по паттерну "เวลารวม"
        checklist = self.soup.find('ul', class_=re.compile(r'fusion-checklist', re.I))
        if checklist:
            items = checklist.find_all('li')
            for item in items:
                content = item.find('div', class_='fusion-li-item-content')
                if content:
                    text = content.get_text(strip=True)
                    if 'เวลารวม' in text:
                        time_match = re.search(r'(\d+)\s*นาที', text)
                        if time_match:
                            return f"{time_match.group(1)} นาที"
        
        return None
    
    def extract_servings(self) -> Optional[str]:
        """Извлечение количества порций"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            servings = item.get('recipeYield')
                            if servings:
                                # Извлекаем число
                                servings_match = re.search(r'(\d+)', str(servings))
                                if servings_match:
                                    return servings_match.group(1)
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        # Ищем в HTML по паттерну "สำหรับ" или "เสิร์ฟ"
        checklist = self.soup.find('ul', class_=re.compile(r'fusion-checklist', re.I))
        if checklist:
            items = checklist.find_all('li')
            for item in items:
                content = item.find('div', class_='fusion-li-item-content')
                if content:
                    text = content.get_text(strip=True)
                    if 'สำหรับ' in text or 'เสิร์ฟ' in text:
                        servings_match = re.search(r'(\d+)', text)
                        if servings_match:
                            return servings_match.group(1)
        
        return None
    
    def extract_difficulty_level(self) -> Optional[str]:
        """Извлечение уровня сложности - для тайских рецептов обычно Easy"""
        # Для тайского сайта обычно простые рецепты
        return "Easy"
    
    def extract_rating(self) -> Optional[str]:
        """Извлечение рейтинга"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            review = item.get('review')
                            if review and isinstance(review, dict):
                                review_rating = review.get('reviewRating')
                                if review_rating and isinstance(review_rating, dict):
                                    rating_value = review_rating.get('ratingValue')
                                    if rating_value:
                                        return str(rating_value)
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение примечаний/советов"""
        # Ищем секцию TIPS в HTML
        tips_heading = self.soup.find('h3', string=re.compile(r'TIPS', re.I))
        
        if tips_heading:
            # Ищем следующий элемент после заголовка
            next_elem = tips_heading.find_next('div', class_='fusion-text')
            if next_elem:
                tips_list = next_elem.find('ul')
                if tips_list:
                    tips = []
                    items = tips_list.find_all('li')
                    for item in items:
                        tip_text = item.get_text(strip=True)
                        if tip_text:
                            tips.append(tip_text)
                    
                    if tips:
                        return ' '.join(tips)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка с ингредиентом на тайском
            
        Returns:
            dict: {"name": "название", "amount": "количество", "unit": "единица"} или None
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
        
        # Тайские единицы измерения и общие единицы
        # Примеры: "1 ช้อนโต๊ะ", "500 กรัม", "2 cups"
        pattern = r'^([\d\s/.,]+)?\s*(ช้อนโต๊ะ|ช้อนชา|กรัม|กิโลกรัม|ลิตร|มิลลิลิตร|ถ้วย|ชิ้น|หัว|ฟอง|เม็ด|แผ่น|cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|g|kg|ml|l|pieces?)?\s*(.+)'
        
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
                amount = str(total)
            else:
                amount = amount_str.replace(',', '.')
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений (первые 3)"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Если есть @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if isinstance(item, dict) and item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
                        # Recipe с image
                        elif isinstance(item, dict) and item.get('@type') == 'Recipe' and 'image' in item:
                            img = item['image']
                            if isinstance(img, str):
                                urls.append(img)
                            elif isinstance(img, list):
                                urls.extend([i for i in img if isinstance(i, str)])
                            elif isinstance(img, dict):
                                if 'url' in img:
                                    urls.append(img['url'])
                                elif 'contentUrl' in img:
                                    urls.append(img['contentUrl'])
                
                # Если Recipe напрямую
                elif isinstance(data, dict) and data.get('@type') == 'Recipe' and 'image' in data:
                    img = data['image']
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, list):
                        urls.extend([i for i in img if isinstance(i, str)])
                    elif isinstance(img, dict):
                        if 'url' in img:
                            urls.append(img['url'])
                        elif 'contentUrl' in img:
                            urls.append(img['contentUrl'])
            
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Убираем дубликаты, сохраняя порядок, берем первые 3
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
                    if len(unique_urls) >= 3:
                        break
            return ', '.join(unique_urls) if unique_urls else None
        
        return None
    
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта
        
        Returns:
            Словарь с данными рецепта
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        step_by_step = self.extract_steps()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name.lower() if dish_name else None,
            "description": description.lower() if description else None,
            "ingredient": ingredients,
            "step_by_step": step_by_step,
            "nutrition_info": self.extract_nutrition_info(),
            "category": None,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "servings": self.extract_servings(),
            "difficulty_level": self.extract_difficulty_level(),
            "rating": self.extract_rating(),
            "notes": notes.lower() if notes else None,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # По умолчанию обрабатываем папку recipes/recipe_sgethai_com
    recipes_dir = os.path.join("recipes", "recipe_sgethai_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(RecipeSgethaiExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python recipe_sgethai_com.py [путь_к_файлу_или_директории]")


if __name__ == "__main__":
    main()
