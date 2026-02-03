"""
Экстрактор данных рецептов для сайта mindmegette.hu
"""

import sys
import os
import re
from pathlib import Path
import json
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MindmegetteExtractor(BaseRecipeExtractor):
    """Экстрактор для mindmegette.hu"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "X minutes"
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
        
        return f"{total_minutes} minutes" if total_minutes > 0 else None
    
    def get_recipe_from_json_ld(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD"""
        script = self.soup.find('script', class_='structured-data')
        if not script or not script.string:
            return None
        
        try:
            data = json.loads(script.string)
            if '@graph' in data:
                for item in data['@graph']:
                    if item.get('@type') == 'Recipe':
                        return item
            elif data.get('@type') == 'Recipe':
                return data
        except (json.JSONDecodeError, KeyError):
            pass
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self.get_recipe_from_json_ld()
        if recipe_data and 'name' in recipe_data:
            name = recipe_data['name']
            # Убираем суффиксы " | Mindmegette.hu" и " - Mindmegette.hu"
            name = re.sub(r'\s*[|\-]\s*Mindmegette\.hu$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы " | Mindmegette.hu" и " - Mindmegette.hu"
            title = re.sub(r'\s*[|\-]\s*Mindmegette\.hu$', '', title, flags=re.IGNORECASE)
            # Также убираем длинные описательные суффиксы через запятую
            title = re.sub(r',\s*amihez.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self.get_recipe_from_json_ld()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Или og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient_text(self, ingredient_text: str) -> dict:
        """
        Парсинг строки ингредиента в структурированный формат
        Пример: "2 fej Vöröshagyma" -> {"name": "vöröshagyma", "amount": 2, "units": "fej"}
        
        Args:
            ingredient_text: Строка ингредиента из JSON-LD
            
        Returns:
            dict с полями name, amount, units
        """
        if not ingredient_text:
            return {"name": None, "amount": None, "units": None}
        
        text = self.clean_text(ingredient_text)
        
        # Паттерн: "количество единица название" или "количество название" или "название"
        # Примеры: "2 fej Vöröshagyma", "Olaj", "1 tk Pirospaprika", "1/2 tk só"
        # Поддерживаем дроби: 1/2, 0,75 и т.д.
        pattern = r'^(\d+(?:[.,/]\d+)?)\s*([a-záéíóöőúüű]+\.?)?\s*(.+)$'
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Конвертируем количество (включая дроби)
            amount = None
            if amount_str:
                try:
                    if '/' in amount_str:
                        # Обработка дробей типа "1/2"
                        parts = amount_str.split('/')
                        if len(parts) == 2:
                            amount = float(parts[0]) / float(parts[1])
                    else:
                        amount = int(amount_str) if '.' not in amount_str and ',' not in amount_str else float(amount_str.replace(',', '.'))
                except (ValueError, ZeroDivisionError):
                    amount = None
            
            # Очистка названия - переводим в нижний регистр
            name = name.strip().lower() if name else None
            unit = unit.strip() if unit else None
            
            return {
                "name": name,
                "units": unit,
                "amount": amount
            }
        else:
            # Если паттерн не совпал, это просто название без количества
            return {
                "name": text.lower(),
                "units": None,
                "amount": None
            }
    
    def extract_ingredients_from_html(self) -> Optional[list]:
        """Извлечение ингредиентов из HTML структуры"""
        ingredients = []
        
        # Вариант 1: Ищем контейнер с ингредиентами (для Recipe страниц)
        ing_wrapper = self.soup.find('div', class_='ingredients')
        if ing_wrapper:
            # Находим все элементы ингредиентов
            ing_items = ing_wrapper.find_all('div', class_='ingredients-meta')
            
            for item in ing_items:
                amount = None
                unit = None
                name = None
                
                # Ищем элементы внутри
                for child in item.children:
                    if child.name == 'strong':
                        # Количество
                        amount_text = child.get_text().strip()
                        try:
                            amount = int(amount_text) if '.' not in amount_text and ',' not in amount_text else float(amount_text.replace(',', '.'))
                        except ValueError:
                            amount = None
                    elif child.name == 'a':
                        # Название ингредиента
                        name = self.clean_text(child.get_text()).lower()
                    elif child.string and child.string.strip():
                        # Единица измерения (текстовый узел между strong и a)
                        unit_text = child.string.strip()
                        if unit_text:
                            unit = unit_text
                
                # Если название найдено, добавляем ингредиент
                if name:
                    ingredients.append({
                        "name": name,
                        "units": unit,
                        "amount": amount
                    })
            
            return ingredients if ingredients else None
        
        # Вариант 2: Ищем список после заголовка "Hozzávalók:" (для NewsArticle страниц)
        h2_hozzavalok = self.soup.find('h2', string=lambda t: t and 'Hozzávalók' in t)
        if h2_hozzavalok:
            # Ищем ul после h2
            ul = h2_hozzavalok.find_next_sibling('ul')
            if ul:
                for li in ul.find_all('li'):
                    ing_text = self.clean_text(li.get_text())
                    if ing_text:
                        parsed = self.parse_ingredient_text(ing_text)
                        ingredients.append(parsed)
                
                return ingredients if ingredients else None
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Сначала пробуем из JSON-LD (более полные данные)
        recipe_data = self.get_recipe_from_json_ld()
        if recipe_data and 'recipeIngredient' in recipe_data:
            for ing_text in recipe_data['recipeIngredient']:
                parsed = self.parse_ingredient_text(ing_text)
                ingredients.append(parsed)
        
        # Если не нашли в JSON-LD, пробуем из HTML
        if not ingredients:
            ingredients = self.extract_ingredients_from_html()
        
        # Возвращаем как JSON строку
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self.get_recipe_from_json_ld()
        
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        steps.append(step['text'])
                    elif isinstance(step, str):
                        steps.append(step)
            elif isinstance(instructions, str):
                steps.append(instructions)
            
            if steps:
                # Объединяем все шаги в одну строку
                return ' '.join(steps)
        
        # Если не нашли в JSON-LD, ищем в HTML после заголовка "Elkészítés:"
        h2_elkeszites = self.soup.find('h2', string=lambda t: t and 'Elkészítés' in t)
        if h2_elkeszites:
            # Ищем ol или p после h2
            ol = h2_elkeszites.find_next_sibling('ol')
            if ol:
                steps = []
                for li in ol.find_all('li'):
                    step_text = self.clean_text(li.get_text())
                    if step_text:
                        steps.append(step_text)
                
                if steps:
                    return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self.get_recipe_from_json_ld()
        
        if recipe_data:
            # Сначала проверяем recipeCategory (более специфичная)
            if 'recipeCategory' in recipe_data:
                category = recipe_data['recipeCategory']
                if category:
                    # Мапим категории
                    category_map = {
                        'desszert': 'Dessert',
                        'desszertek': 'Dessert',
                        'alapételek': 'Alapételek',
                        'alapanyagtípus': 'Main Course',
                        'előétel': 'Appetizer',
                        'előételek': 'Appetizer',
                        'leves': 'Soup',
                        'levesek': 'Soup',
                        'főétel': 'Main Course',
                        'főételek': 'Main Course',
                    }
                    mapped = category_map.get(category.lower())
                    if mapped:
                        return mapped
                    # Если нет маппинга, возвращаем как есть
                    return category
            
            # Если recipeCategory не найдена, проверяем recipeCuisine
            if 'recipeCuisine' in recipe_data:
                cuisine = recipe_data['recipeCuisine']
                if cuisine:
                    # Мапим венгерские названия кухонь на Main Course по умолчанию
                    cuisine_map = {
                        'mexikói': 'Main Course',
                        'magyar': 'Main Course',
                        'olasz': 'Main Course',
                        'francia': 'Main Course',
                        'kínai': 'Main Course',
                        'indiai': 'Main Course',
                    }
                    mapped = cuisine_map.get(cuisine.lower())
                    if mapped:
                        return mapped
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.get_recipe_from_json_ld()
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self.get_recipe_from_json_ld()
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.get_recipe_from_json_ld()
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с информацией/советами
        info_box = self.soup.find('div', class_='info-box-description')
        if info_box:
            text = self.clean_text(info_box.get_text())
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Сначала пробуем из JSON-LD keywords
        recipe_data = self.get_recipe_from_json_ld()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, list):
                tags.extend([k.lower() for k in keywords if k])
            elif isinstance(keywords, str):
                # Разбиваем по запятым если это строка
                tags.extend([k.strip().lower() for k in keywords.split(',') if k.strip()])
        
        # Также ищем теги в HTML (элементы с классом 'tag')
        tag_elements = self.soup.find_all('a', class_='tag')
        for tag_elem in tag_elements:
            tag_text = self.clean_text(tag_elem.get_text()).lower()
            if tag_text and tag_text not in tags:
                tags.append(tag_text)
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        # Возвращаем как строку через запятую с пробелом
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в JSON-LD
        recipe_data = self.get_recipe_from_json_ld()
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
        # 2. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)
        
        # Также проверяем primaryImageOfPage в JSON-LD
        if recipe_data:
            # Ищем в @graph объект WebPage с primaryImageOfPage
            script = self.soup.find('script', class_='structured-data')
            if script and script.string:
                try:
                    data = json.loads(script.string)
                    if '@graph' in data:
                        for item in data['@graph']:
                            if item.get('@type') == 'WebPage' and 'primaryImageOfPage' in item:
                                img_obj = item['primaryImageOfPage']
                                if isinstance(img_obj, dict):
                                    for key in ['url', 'contentUrl', '@id']:
                                        if key in img_obj:
                                            img_url = img_obj[key]
                                            if img_url and img_url not in urls:
                                                urls.append(img_url)
                                                break
                except:
                    pass
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        # Возвращаем как строку через запятую без пробелов
        return ','.join(unique_urls) if unique_urls else None
    
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
    """Обработка всех HTML файлов из директории preprocessed/mindmegette_hu"""
    # Определяем путь к директории с HTML файлами
    base_dir = Path(__file__).parent.parent
    preprocessed_dir = base_dir / "preprocessed" / "mindmegette_hu"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        process_directory(MindmegetteExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python mindmegette_hu.py")


if __name__ == "__main__":
    main()
