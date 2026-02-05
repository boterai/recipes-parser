"""
Экстрактор данных рецептов для сайта theperfectloaf.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ThePerfectLoafExtractor(BaseRecipeExtractor):
    """Экстрактор для theperfectloaf.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Собираем варианты заголовков
        h1 = self.soup.find('h1')
        h1_text = None
        if h1:
            h1_text = self.clean_text(h1.get_text())
            h1_text = re.sub(r'^How\s+to\s+(Make\s+)?', '', h1_text, flags=re.IGNORECASE)
            h1_text = re.sub(r'\s*\([^)]+\)\s*$', '', h1_text)
        
        # Tasty Recipes заголовок
        recipe_title = self.soup.find('h2', class_='tasty-recipes-title')
        h2_text = None
        if recipe_title:
            h2_text = self.clean_text(recipe_title.get_text())
            h2_text = re.sub(r'^How\s+to\s+(Make\s+)?', '', h2_text, flags=re.IGNORECASE)
        
        # Выбираем более полный вариант: если H1 длиннее H2 на 20% или более, используем H1
        # Иначе используем H2 (он обычно чище)
        if h2_text and h1_text:
            if len(h1_text) > len(h2_text) * 1.2:
                return h1_text
            else:
                return h2_text
        elif h2_text:
            return h2_text
        elif h1_text:
            return h1_text
        
        # Пробуем JSON-LD
        json_ld_data = self.extract_json_ld()
        if json_ld_data and 'name' in json_ld_data:
            name = self.clean_text(json_ld_data['name'])
            name = re.sub(r'^How\s+to\s+(Make\s+)?', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\s*\([^)]+\)\s*$', '', name)
            return name
        
        # Из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*\|\s*The Perfect Loaf.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'^How\s+to\s+(Make\s+)?', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*\([^)]+\)\s*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем JSON-LD
        json_ld_data = self.extract_json_ld()
        if json_ld_data and 'description' in json_ld_data:
            return self.clean_text(json_ld_data['description'])
        
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
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld_data = self.extract_json_ld()
        if json_ld_data and 'recipeIngredient' in json_ld_data:
            recipe_ingredients = json_ld_data['recipeIngredient']
            if isinstance(recipe_ingredients, list):
                for ing_text in recipe_ingredients:
                    parsed = self.parse_ingredient_from_text(ing_text)
                    if parsed:
                        ingredients.append(parsed)
                
                if ingredients:
                    return json.dumps(ingredients, ensure_ascii=False)
        
        # Если JSON-LD не помог, ищем в HTML с data-атрибутами
        ingredients_container = self.soup.find('div', class_='tasty-recipes-ingredients')
        if ingredients_container:
            ingredient_items = ingredients_container.find_all('li')
            
            for item in ingredient_items:
                # Ищем span с data-amount и data-unit
                amount_span = item.find('span', attrs={'data-amount': True})
                
                if amount_span:
                    amount = amount_span.get('data-amount')
                    unit = amount_span.get('data-unit', '')
                    
                    # Извлекаем название ингредиента (текст после span)
                    # Получаем весь текст элемента
                    full_text = item.get_text(separator=' ', strip=True)
                    # Удаляем часть с количеством из начала
                    amount_text = amount_span.get_text(strip=True)
                    name = full_text.replace(amount_text, '', 1).strip()
                    
                    ingredients.append({
                        "name": self.clean_text(name),
                        "units": unit if unit else None,
                        "amount": amount
                    })
                else:
                    # Если нет data-атрибутов, парсим текст
                    ing_text = item.get_text(separator=' ', strip=True)
                    parsed = self.parse_ingredient_from_text(ing_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient_from_text(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "475g whole milk" или "1 vanilla bean"
            
        Returns:
            dict: {"name": "whole milk", "amount": "475", "unit": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "475g whole milk", "1 vanilla bean", "0.25 teaspoon sea salt"
        pattern = r'^([\d\s/.,]+)?\s*(g|grams?|kg|kilograms?|mg|oz|ounces?|lbs?|pounds?|cups?|tablespoons?|teaspoons?|tbsps?|tsps?|ml|milliliters?|l|liters?|teaspoon|tablespoon|cup|pound|ounce)?\s*(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "units": None,
                "amount": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip().replace(',', '.')
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
                amount = str(total) if total != int(total) else str(int(total))
            else:
                try:
                    amount_float = float(amount_str)
                    amount = str(amount_float) if amount_float != int(amount_float) else str(int(amount_float))
                except ValueError:
                    amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        name = self.clean_text(name)
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "units": unit,
            "amount": amount
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        # Сначала пробуем JSON-LD
        json_ld_data = self.extract_json_ld()
        if json_ld_data and 'recipeInstructions' in json_ld_data:
            instructions = json_ld_data['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                for instruction in instructions:
                    if isinstance(instruction, dict):
                        if '@type' in instruction and instruction['@type'] == 'HowToSection':
                            # Секция с подшагами
                            if 'itemListElement' in instruction:
                                for step in instruction['itemListElement']:
                                    if isinstance(step, dict) and 'text' in step:
                                        steps.append(self.clean_text(step['text']))
                        elif 'text' in instruction:
                            steps.append(self.clean_text(instruction['text']))
                    elif isinstance(instruction, str):
                        steps.append(self.clean_text(instruction))
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            
            if steps:
                return ' '.join(steps)
        
        # Если JSON-LD не помог, ищем в HTML
        instructions_container = self.soup.find('div', class_='tasty-recipes-instructions')
        if instructions_container:
            step_items = instructions_container.find_all('li')
            steps = []
            
            for item in step_items:
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                if step_text:
                    steps.append(step_text)
            
            if steps:
                return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в HTML (Tasty Recipes category) - приоритет
        category_elem = self.soup.find(class_='tasty-recipes-category')
        if category_elem:
            category_text = self.clean_text(category_elem.get_text())
            # Если категория содержит несколько значений через запятую, берем первое
            # которое часто является основной категорией
            if ',' in category_text:
                categories = [c.strip() for c in category_text.split(',')]
                # Приоритет: Dessert > другие
                if 'Dessert' in categories:
                    return 'Dessert'
                return categories[0]
            return category_text
        
        # Сначала пробуем JSON-LD
        json_ld_data = self.extract_json_ld()
        if json_ld_data:
            # Проверяем поле recipeCategory
            if 'recipeCategory' in json_ld_data and json_ld_data['recipeCategory']:
                category = json_ld_data['recipeCategory']
                if isinstance(category, list):
                    return self.clean_text(', '.join(category))
                return self.clean_text(category)
        
        # Если не нашли категорию, возвращаем None (не используем cuisine как fallback)
        # Cuisine != Category в большинстве случаев
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Сначала пробуем JSON-LD
        json_ld_data = self.extract_json_ld()
        if json_ld_data and 'prepTime' in json_ld_data:
            iso_time = json_ld_data['prepTime']
            return self.parse_iso_duration(iso_time)
        
        # Ищем в HTML
        prep_time_elem = self.soup.find(class_='tasty-recipes-prep-time')
        if prep_time_elem:
            return self.clean_text(prep_time_elem.get_text())
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Сначала пробуем JSON-LD
        json_ld_data = self.extract_json_ld()
        if json_ld_data and 'cookTime' in json_ld_data:
            iso_time = json_ld_data['cookTime']
            return self.parse_iso_duration(iso_time)
        
        # Ищем в HTML
        cook_time_elem = self.soup.find(class_='tasty-recipes-cook-time')
        if cook_time_elem:
            return self.clean_text(cook_time_elem.get_text())
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Сначала пробуем JSON-LD
        json_ld_data = self.extract_json_ld()
        if json_ld_data and 'totalTime' in json_ld_data:
            iso_time = json_ld_data['totalTime']
            return self.parse_iso_duration(iso_time)
        
        # Ищем в HTML
        total_time_elem = self.soup.find(class_='tasty-recipes-total-time')
        if total_time_elem:
            return self.clean_text(total_time_elem.get_text())
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M", "PT1H30M", "P2D"
            
        Returns:
            Время в читаемом формате, например "1 hour 30 minutes", "2 days"
        """
        if not duration or not duration.startswith('P'):
            return None
        
        # Удаляем 'P' в начале
        duration = duration[1:]
        
        days = 0
        hours = 0
        minutes = 0
        
        # Извлекаем дни (до 'T')
        if 'T' in duration:
            day_part, time_part = duration.split('T')
            if day_part:
                day_match = re.search(r'(\d+)D', day_part)
                if day_match:
                    days = int(day_match.group(1))
            duration = time_part
        else:
            # Только дни
            day_match = re.search(r'(\d+)D', duration)
            if day_match:
                days = int(day_match.group(1))
                duration = ''
        
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
        if days > 0:
            parts.append(f"{days} day{'s' if days > 1 else ''}")
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем секцию с примечаниями в Tasty Recipes
        notes_section = self.soup.find('div', class_='tasty-recipes-notes')
        if notes_section:
            # Извлекаем текст, исключая заголовок
            paragraphs = notes_section.find_all('p')
            if paragraphs:
                notes_text = ' '.join([p.get_text(strip=True) for p in paragraphs])
                return self.clean_text(notes_text) if notes_text else None
            
            # Если нет параграфов, берем весь текст
            text = notes_section.get_text(separator=' ', strip=True)
            # Убираем заголовок "Notes"
            text = re.sub(r'^Notes\s*:?\s*', '', text, flags=re.IGNORECASE)
            return self.clean_text(text) if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Пробуем извлечь из JSON-LD keywords
        json_ld_data = self.extract_json_ld()
        if json_ld_data and 'keywords' in json_ld_data:
            keywords = json_ld_data['keywords']
            if isinstance(keywords, str):
                # Разделяем по запятой
                tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            elif isinstance(keywords, list):
                tags = keywords
        
        # Если не нашли в JSON-LD, ищем в мета-тегах
        if not tags:
            meta_keywords = self.soup.find('meta', {'name': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                tags = [tag.strip() for tag in meta_keywords['content'].split(',') if tag.strip()]
        
        # Возвращаем как строку через запятую с пробелом
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Пробуем из JSON-LD
        json_ld_data = self.extract_json_ld()
        if json_ld_data and 'image' in json_ld_data:
            img = json_ld_data['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif '@id' in img:
                    urls.append(img['@id'])
        
        # 2. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Ищем в Tasty Recipes image
        recipe_image = self.soup.find('div', class_='tasty-recipes-image')
        if recipe_image:
            img_tag = recipe_image.find('img')
            if img_tag and img_tag.get('src'):
                urls.append(img_tag['src'])
        
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
    
    def extract_json_ld(self) -> Optional[dict]:
        """Извлечение JSON-LD данных рецепта"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Функция для проверки типа Recipe
                def is_recipe(item):
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        return 'Recipe' in item_type
                    return item_type == 'Recipe'
                
                # Ищем Recipe в данных
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and is_recipe(item):
                            return item
                elif isinstance(data, dict):
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and is_recipe(item):
                                return item
                    # Проверяем сам объект
                    elif is_recipe(data):
                        return data
                        
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
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
    Точка входа для обработки HTML-файлов theperfectloaf.com
    """
    import os
    
    # Путь к директории с preprocessed файлами
    base_dir = Path(__file__).parent.parent
    preprocessed_dir = base_dir / "preprocessed" / "theperfectloaf_com"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обработка файлов из: {preprocessed_dir}")
        process_directory(ThePerfectLoafExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python theperfectloaf_com.py")


if __name__ == "__main__":
    main()
