"""
Экстрактор данных рецептов для сайта miljuschka.nl
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MiljuschkaNlExtractor(BaseRecipeExtractor):
    """Экстрактор для miljuschka.nl"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT240M"
            
        Returns:
            Время в минутах, например "90"
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
        
        return str(total_minutes) if total_minutes > 0 else None
    
    def get_recipe_data_from_jsonld(self) -> Optional[Dict[str, Any]]:
        """Извлекает данные рецепта из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            return item
                
                # Проверяем прямой объект Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                
                # Проверяем список
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                            
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self.get_recipe_data_from_jsonld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из заголовка страницы
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self.get_recipe_data_from_jsonld()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Dict[str, Any]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "210 g roomboter (op kamertemperatuur)"
            
        Returns:
            dict: {"name": "roomboter", "amount": 210, "units": "g"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "210 g roomboter", "1,5 gelatineblaadjes", "200 g eieren (4 stuks)"
        pattern = r'^(\d+(?:[.,]\d+)?)\s*(\w+)?\s+(.+)$'
        
        match = re.match(pattern, text)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества - конвертируем запятую в точку и в число
        amount = None
        if amount_str:
            amount_str = amount_str.replace(',', '.')
            try:
                # Пробуем преобразовать в число
                amount_float = float(amount_str)
                # Если это целое число, оставляем как int
                if amount_float.is_integer():
                    amount = int(amount_float)
                else:
                    amount = amount_float
            except ValueError:
                amount = amount_str
        
        # Очистка названия - удаляем содержимое в скобках
        name = re.sub(r'\([^)]*\)', '', name).strip()
        
        # Удаляем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit if unit else None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        recipe_data = self.get_recipe_data_from_jsonld()
        
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredients = []
            for ing_text in recipe_data['recipeIngredient']:
                parsed = self.parse_ingredient(ing_text)
                if parsed:
                    ingredients.append(parsed)
            
            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
        
        return None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self.get_recipe_data_from_jsonld()
        
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            steps = []
            step_number = 1
            
            for instruction in instructions:
                if isinstance(instruction, dict):
                    # Обработка HowToStep
                    if instruction.get('@type') == 'HowToStep' and 'text' in instruction:
                        step_text = self.clean_text(instruction['text'])
                        steps.append(f"{step_number}. {step_text}")
                        step_number += 1
                    
                    # Обработка HowToSection с вложенными шагами
                    elif instruction.get('@type') == 'HowToSection' and 'itemListElement' in instruction:
                        for sub_step in instruction['itemListElement']:
                            if isinstance(sub_step, dict) and 'text' in sub_step:
                                step_text = self.clean_text(sub_step['text'])
                                steps.append(f"{step_number}. {step_text}")
                                step_number += 1
                
                elif isinstance(instruction, str):
                    step_text = self.clean_text(instruction)
                    steps.append(f"{step_number}. {step_text}")
                    step_number += 1
            
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности в формате: 202 kcal; 2/11/27"""
        recipe_data = self.get_recipe_data_from_jsonld()
        
        if recipe_data and 'nutrition' in recipe_data:
            nutrition = recipe_data['nutrition']
            
            # Извлекаем калории
            calories = None
            if 'calories' in nutrition:
                cal_text = nutrition['calories']
                cal_match = re.search(r'(\d+)', str(cal_text))
                if cal_match:
                    calories = cal_match.group(1)
            
            # Извлекаем БЖУ (белки/жиры/углеводы)
            protein = None
            fat = None
            carbs = None
            
            if 'proteinContent' in nutrition:
                prot_text = nutrition['proteinContent']
                prot_match = re.search(r'(\d+)', str(prot_text))
                if prot_match:
                    protein = prot_match.group(1)
            
            if 'fatContent' in nutrition:
                fat_text = nutrition['fatContent']
                fat_match = re.search(r'(\d+)', str(fat_text))
                if fat_match:
                    fat = fat_match.group(1)
            
            if 'carbohydrateContent' in nutrition:
                carb_text = nutrition['carbohydrateContent']
                carb_match = re.search(r'(\d+)', str(carb_text))
                if carb_match:
                    carbs = carb_match.group(1)
            
            # Форматируем: "202 kcal; 2/11/27"
            if calories and protein and fat and carbs:
                return f"{calories} kcal; {protein}/{fat}/{carbs}"
            elif calories:
                return f"{calories} kcal"
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self.get_recipe_data_from_jsonld()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            if isinstance(category, list):
                # Берем первую категорию
                if category:
                    return self.clean_text(category[0])
            elif isinstance(category, str):
                return self.clean_text(category)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.get_recipe_data_from_jsonld()
        
        if recipe_data and 'prepTime' in recipe_data:
            iso_time = recipe_data['prepTime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self.get_recipe_data_from_jsonld()
        
        if recipe_data and 'cookTime' in recipe_data:
            iso_time = recipe_data['cookTime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.get_recipe_data_from_jsonld()
        
        if recipe_data and 'totalTime' in recipe_data:
            iso_time = recipe_data['totalTime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_difficulty_level(self) -> Optional[str]:
        """Извлечение уровня сложности"""
        # На miljuschka.nl нет явного указания сложности
        # Определяем на основе общего времени
        total_time_str = self.extract_total_time()
        
        if total_time_str:
            try:
                # Время возвращается как строка с числом минут
                minutes = int(total_time_str)
                if minutes <= 30:
                    return "Easy"
                elif minutes <= 90:
                    return "Medium"
                else:
                    return "Hard"
            except (ValueError, TypeError):
                pass
        
        return "Medium"  # По умолчанию
    
    def extract_rating(self) -> Optional[float]:
        """Извлечение рейтинга рецепта"""
        recipe_data = self.get_recipe_data_from_jsonld()
        
        if recipe_data and 'aggregateRating' in recipe_data:
            rating_data = recipe_data['aggregateRating']
            if isinstance(rating_data, dict) and 'ratingValue' in rating_data:
                try:
                    return float(rating_data['ratingValue'])
                except (ValueError, TypeError):
                    pass
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # На miljuschka.nl заметки могут быть в конце описания или в специальных секциях
        # Попробуем найти секции с классом wprm-recipe-notes
        notes_section = self.soup.find(class_=lambda x: x and 'wprm-recipe-notes' in x)
        
        if notes_section:
            text = notes_section.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        # Альтернативно - ищем параграфы после рецепта с советами
        # Обычно они содержат слова "tip", "note", "let op" и т.д.
        for p in self.soup.find_all('p'):
            text = p.get_text(strip=True).lower()
            if any(keyword in text for keyword in ['tip:', 'opmerking:', 'let op:', 'zorg ervoor']):
                return self.clean_text(p.get_text())
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Очищаем и возвращаем
            return self.clean_text(keywords)
        
        # Альтернативно - извлекаем из классов тегов article
        article = self.soup.find('article')
        if article:
            tag_classes = article.get('class', [])
            # Извлекаем теги из классов (tag-...)
            tags = []
            for cls in tag_classes:
                if cls.startswith('tag-'):
                    tag = cls[4:].replace('-', ' ')
                    tags.append(tag)
            
            if tags:
                return ', '.join(tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Извлекаем из JSON-LD
        recipe_data = self.get_recipe_data_from_jsonld()
        if recipe_data and 'image' in recipe_data:
            images = recipe_data['image']
            if isinstance(images, str):
                urls.append(images)
            elif isinstance(images, list):
                urls.extend([img for img in images if isinstance(img, str)])
            elif isinstance(images, dict):
                if 'url' in images:
                    urls.append(images['url'])
                elif 'contentUrl' in images:
                    urls.append(images['contentUrl'])
        
        # 2. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
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
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        step_by_step = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredient": ingredients,
            "step_by_step": step_by_step,
            "nutrition_info": self.extract_nutrition_info(),
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "difficulty_level": self.extract_difficulty_level(),
            "rating": self.extract_rating(),
            "notes": notes,
            "image_urls": self.extract_image_urls(),
            "tags": tags
        }


def main():
    import os
    # Обрабатываем папку preprocessed/miljuschka_nl
    recipes_dir = os.path.join("preprocessed", "miljuschka_nl")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(MiljuschkaNlExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python miljuschka_nl.py")


if __name__ == "__main__":
    main()
