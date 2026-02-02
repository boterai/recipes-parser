"""
Экстрактор данных рецептов для сайта delamaris.hr
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class DelamarisHrExtractor(BaseRecipeExtractor):
    """Экстрактор для delamaris.hr"""
    
    @staticmethod
    def clean_text(text: str) -> str:
        """Переопределение clean_text для удаления мягких переносов"""
        if not text:
            return text
        
        # Сначала применяем базовую очистку
        text = BaseRecipeExtractor.clean_text(text)
        
        # Удаляем мягкие переносы (soft hyphens)
        text = text.replace('\xad', '')
        
        return text
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "X minutes" или "X min"
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
            # Используем формат "X min" для коротких времён, "X minutes" для длинных
            if total_minutes < 60:
                return f"{total_minutes} min"
            else:
                return f"{total_minutes} minutes"
        
        return None
    
    def get_json_ld_recipe(self) -> Optional[dict]:
        """
        Извлечение данных Recipe из JSON-LD
        
        Returns:
            Словарь с данными Recipe или None
        """
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            if not script.string:
                continue
                
            try:
                # Пытаемся распарсить JSON как есть
                data = json.loads(script.string)
            except json.JSONDecodeError:
                # Если не получилось, пробуем очистить от управляющих символов
                try:
                    # Используем strict=False для более мягкой обработки
                    import ast
                    # Очищаем управляющие символы и пробуем снова
                    cleaned = script.string.encode('utf-8', 'ignore').decode('utf-8')
                    data = json.loads(cleaned, strict=False)
                except:
                    # Если и это не помогло, пропускаем этот скрипт
                    continue
            except (KeyError, AttributeError, TypeError):
                continue
            
            try:
                # Функция для проверки типа Recipe
                def is_recipe(item):
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        return 'Recipe' in item_type
                    return item_type == 'Recipe'
                
                # Ищем Recipe в данных
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            return item
                elif isinstance(data, dict):
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if is_recipe(item):
                                return item
                    # Или сам объект
                    elif is_recipe(data):
                        return data
                        
            except (KeyError, AttributeError, TypeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффикс " - Delamaris"
            title = re.sub(r'\s*-\s*Delamaris.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Или из title
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем суффикс " - Delamaris"
            title = re.sub(r'\s*-\s*Delamaris.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            if desc:
                # Очищаем от HTML тегов если они есть
                from bs4 import BeautifulSoup
                desc_soup = BeautifulSoup(desc, 'lxml')
                desc_text = desc_soup.get_text(separator=' ', strip=True)
                return self.clean_text(desc_text)
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> dict:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "2 x 80 g pašteta od tune premium" или "200 g nemasne skute"
            
        Returns:
            dict: {"name": "...", "amount": "...", "unit": "..."}
        """
        if not ingredient_text:
            return {"name": None, "amount": None, "units": None}
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерны для извлечения количества и единицы
        # Примеры: "2 x 80 g паштета", "200 g скуте", "4 žlice майонезы"
        
        # Сначала пробуем паттерн с "x" (например, "2 x 80 g")
        pattern_with_x = r'^(\d+)\s*x\s*(\d+)\s*([a-zA-Zščćžđ]+)\s+(.+)$'
        match = re.match(pattern_with_x, text, re.IGNORECASE)
        
        if match:
            # Количество пакетов, вес одного пакета, единица, название
            count, weight, unit, name = match.groups()
            return {
                "name": name.strip(),
                "amount": count.strip(),
                "units": f"x {weight} {unit}".strip()
            }
        
        # Паттерн обычного количества с единицей
        pattern_normal = r'^(\d+(?:[.,]\d+)?)\s*([a-zA-Zščćžđ]+)\s+(.+)$'
        match = re.match(pattern_normal, text, re.IGNORECASE)
        
        if match:
            amount, unit, name = match.groups()
            return {
                "name": name.strip(),
                "amount": amount.strip(),
                "units": unit.strip()
            }
        
        # Если паттерны не совпали - только название (без количества и единицы)
        return {
            "name": text.strip(),
            "amount": None,
            "units": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD"""
        recipe_data = self.get_json_ld_recipe()
        
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredients_list = recipe_data['recipeIngredient']
        
        if not isinstance(ingredients_list, list):
            return None
        
        # Парсим каждый ингредиент
        parsed_ingredients = []
        for ingredient_text in ingredients_list:
            if isinstance(ingredient_text, str):
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    parsed_ingredients.append(parsed)
        
        return json.dumps(parsed_ingredients, ensure_ascii=False) if parsed_ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций из JSON-LD"""
        recipe_data = self.get_json_ld_recipe()
        
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        
        # Если это список объектов HowToStep
        if isinstance(instructions, list):
            steps = []
            for step in instructions:
                if isinstance(step, dict) and 'text' in step:
                    steps.append(step['text'])
                elif isinstance(step, str):
                    steps.append(step)
            
            return ' '.join(steps) if steps else None
        
        # Если это просто строка
        elif isinstance(instructions, str):
            return instructions
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории (для delamaris.hr обычно отсутствует)"""
        recipe_data = self.get_json_ld_recipe()
        
        if recipe_data:
            # Пробуем recipeCategory
            if 'recipeCategory' in recipe_data:
                category = recipe_data['recipeCategory']
                if category:
                    return self.clean_text(category) if isinstance(category, str) else None
            
            # Пробуем recipeCuisine
            if 'recipeCuisine' in recipe_data:
                cuisine = recipe_data['recipeCuisine']
                if cuisine:
                    return self.clean_text(cuisine) if isinstance(cuisine, str) else None
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.get_json_ld_recipe()
        
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        recipe_data = self.get_json_ld_recipe()
        
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.get_json_ld_recipe()
        
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок (для delamaris.hr обычно отсутствует)"""
        # Пробуем найти в JSON-LD (если есть поле для заметок)
        recipe_data = self.get_json_ld_recipe()
        
        if recipe_data and 'recipeNotes' in recipe_data:
            notes = recipe_data['recipeNotes']
            if notes:
                return self.clean_text(notes) if isinstance(notes, str) else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов (для delamaris.hr обычно отсутствует)"""
        # Пробуем keywords из JSON-LD
        recipe_data = self.get_json_ld_recipe()
        
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if keywords:
                if isinstance(keywords, list):
                    return ', '.join(keywords)
                elif isinstance(keywords, str):
                    return keywords
        
        # Пробуем meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Сначала из JSON-LD
        recipe_data = self.get_json_ld_recipe()
        
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
        
        # 2. Из meta тегов
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
    Точка входа для обработки HTML файлов из preprocessed/delamaris_hr
    """
    import os
    
    # Определяем путь к директории относительно корня репозитория
    repo_root = Path(__file__).parent.parent
    preprocessed_dir = repo_root / "preprocessed" / "delamaris_hr"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(DelamarisHrExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python delamaris_hr.py")


if __name__ == "__main__":
    main()
