"""
Экстрактор данных рецептов для сайта ricardocuisine.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional
sys.path.insert(0, str(Path(__file__).parent.parent))

from extractor.base import BaseRecipeExtractor, process_directory


class RicardoCuisineExtractor(BaseRecipeExtractor):
    
    def extract_from_json_ld(self) -> dict:
        """Извлечение данных из JSON-LD схемы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                script_content = script.string
                if not script_content:
                    continue
                
                data = json.loads(script_content.strip())
                
                # Проверяем, что это рецепт
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except json.JSONDecodeError:
                continue
        
        return {}
    
    def extract_dish_name(self) -> str:
        """Извлечение названия блюда"""
        # Сначала пробуем JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'name' in json_data:
            return json_data['name'].strip()
        
        # Резервный вариант - из заголовка
        title = self.soup.find('h1', class_='c-recipe__title')
        if title:
            return title.get_text(strip=True)
        
        return ""
    
    def extract_description(self) -> str:
        """Извлечение описания рецепта"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'description' in json_data:
            return json_data['description'].strip()
        
        # Резервный вариант
        description = self.soup.find('div', class_='c-recipe__description')
        if description:
            return description.get_text(strip=True)
        
        return ""
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """Парсинг строки ингредиента для извлечения названия, количества и единицы измерения (французские единицы)"""
        if not ingredient_text:
            return None
        
        text = ingredient_text.strip()
        
        # Убираем примечания в скобках
        text_without_parens = re.sub(r'\([^)]+\)', '', text).strip()
        
        # Паттерн 1: "количество единица de название"
        # Примеры: "125 ml de bouillon", "2 c. à soupe de beurre", "340 g de chocolat"
        pattern1 = r'^([\d.,/]+(?:\s+[\d/]+)?)\s*(ml|l|g|kg|lb|oz|tasse|tasses|c\.?\s*à\s*(?:soupe|thé)|c\.à\.s\.|c\.à\.c\.)\s+(?:de\s+|d[\'\'])(.+)$'
        match = re.match(pattern1, text_without_parens, re.IGNORECASE)
        
        if match:
            amount_str = match.group(1).strip()
            unit = match.group(2).strip().lower()
            name = match.group(3).strip()
            
            # Конвертируем дроби
            amount = self._convert_fraction_to_number(amount_str)
            
            # Нормализация единиц
            unit = self._normalize_french_unit(unit)
            
            # Очистка названия
            name = name.strip().rstrip(',.')
            # Убираем дополнительные описания после запятой
            name = re.split(r',', name)[0].strip()
            
            return {
                "name": name.lower(),
                "amount": str(amount) if amount else None,
                "unit": unit
            }
        
        # Паттерн 2: "количество de название" (без явной единицы)
        # Примеры: "2 de carottes", "3 de pommes"
        pattern2 = r'^([\d.,/]+(?:\s+[\d/]+)?)\s+(?:de\s+|d[\'\'])(.+)$'
        match = re.match(pattern2, text_without_parens, re.IGNORECASE)
        
        if match:
            amount_str = match.group(1).strip()
            name = match.group(2).strip()
            
            amount = self._convert_fraction_to_number(amount_str)
            
            name = name.strip().rstrip(',.')
            name = re.split(r',', name)[0].strip()
            
            return {
                "name": name.lower(),
                "amount": str(amount) if amount else None,
                "unit": None
            }
        
        # Паттерн 3: "количество единица название" (без "de")
        # Примеры: "250 ml lait", "100 g farine"
        pattern3 = r'^([\d.,/]+(?:\s+[\d/]+)?)\s*(ml|l|g|kg|lb|oz|tasse|tasses|c\.?\s*à\s*(?:soupe|thé)|c\.à\.s\.|c\.à\.c\.)\s+(.+)$'
        match = re.match(pattern3, text_without_parens, re.IGNORECASE)
        
        if match:
            amount_str = match.group(1).strip()
            unit = match.group(2).strip().lower()
            name = match.group(3).strip()
            
            amount = self._convert_fraction_to_number(amount_str)
            unit = self._normalize_french_unit(unit)
            
            name = name.strip().rstrip(',.')
            name = re.split(r',', name)[0].strip()
            
            return {
                "name": name.lower(),
                "amount": str(amount) if amount else None,
                "unit": unit
            }
        
        # Паттерн 4: просто название (без количества)
        # Примеры: "Sel et poivre", "Au goût"
        if text_without_parens:
            # Проверяем специальные случаи
            if re.search(r'\bau\s+goût\b', text_without_parens, re.IGNORECASE):
                name = re.sub(r',?\s*au\s+goût', '', text_without_parens, flags=re.IGNORECASE).strip()
                if not name:
                    name = text_without_parens
                return {
                    "name": name.lower(),
                    "amount": None,
                    "unit": "au goût"
                }
            
            # Просто название без количества
            return {
                "name": text_without_parens.lower(),
                "amount": None,
                "unit": None
            }
        
        return None
    
    def _convert_fraction_to_number(self, fraction_str: str) -> Optional[float]:
        """Конвертирует дроби и смешанные числа в десятичные"""
        if not fraction_str:
            return None
        
        try:
            # Заменяем запятую на точку
            fraction_str = fraction_str.replace(',', '.')
            
            # Обработка смешанных чисел: "1 1/2" -> 1.5
            mixed_match = re.match(r'^([\d.]+)\s+([\d.]+)/([\d.]+)$', fraction_str)
            if mixed_match:
                whole = float(mixed_match.group(1))
                numerator = float(mixed_match.group(2))
                denominator = float(mixed_match.group(3))
                return whole + (numerator / denominator)
            
            # Обработка простых дробей: "1/2" -> 0.5
            fraction_match = re.match(r'^([\d.]+)/([\d.]+)$', fraction_str)
            if fraction_match:
                numerator = float(fraction_match.group(1))
                denominator = float(fraction_match.group(2))
                return numerator / denominator
            
            # Простое число
            return float(fraction_str)
        
        except (ValueError, ZeroDivisionError):
            return None
    
    def _normalize_french_unit(self, unit: str) -> str:
        """Нормализация французских единиц измерения"""
        unit = unit.lower().strip()
        
        # Mapping французских единиц
        unit_map = {
            'c. à soupe': 'c.à.s.',
            'c.à soupe': 'c.à.s.',
            'c à soupe': 'c.à.s.',
            'c. à thé': 'c.à.c.',
            'c.à thé': 'c.à.c.',
            'c à thé': 'c.à.c.',
            'tasses': 'tasse',
        }
        
        return unit_map.get(unit, unit)
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в нормализованном JSON формате"""
        ingredient_items = []
        
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'recipeIngredient' in json_data:
            ingredients_list = json_data['recipeIngredient']
            
            for ing in ingredients_list:
                # Удаляем лишние пробелы и табуляции
                cleaned_ing = ' '.join(ing.split()).strip()
                
                # Парсим ингредиент
                parsed = self.parse_ingredient(cleaned_ing)
                if parsed:
                    ingredient_items.append(parsed)
            
            if ingredient_items:
                return json.dumps(ingredient_items, ensure_ascii=False)
        
        return None
    

    def extract_step_by_step(self) -> str:
        """Извлечение пошаговых инструкций"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'recipeInstructions' in json_data:
            instructions = json_data['recipeInstructions']
            steps = []
            
            for section in instructions:
                if isinstance(section, dict) and section.get('@type') == 'HowToSection':
                    # Получаем шаги из секции
                    for step in section.get('itemListElement', []):
                        if isinstance(step, dict) and step.get('@type') == 'HowToStep':
                            text = step.get('text', '').strip()
                            # Удаляем HTML теги если есть
                            text = re.sub(r'<[^>]+>', '', text)
                            # Нормализуем пробелы
                            text = ' '.join(text.split())
                            if text:
                                steps.append(text)
            
            return ' '.join(steps)
        
        return ""
    
    def extract_rating(self) -> Optional[float]:
        """Извлечение рейтинга"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'aggregateRating' in json_data:
            rating_data = json_data['aggregateRating']
            if 'ratingValue' in rating_data:
                try:
                    return float(rating_data['ratingValue'])
                except (ValueError, TypeError):
                    pass
        
        return None
    
    def extract_category(self) -> str:
        """Извлечение категории рецепта"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'recipeCategory' in json_data:
            return json_data['recipeCategory'].strip()
        
        return ""
    
    def extract_prep_time(self) -> str:
        """Извлечение времени подготовки"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'prepTime' in json_data:
            # Конвертируем ISO 8601 duration в человекочитаемый формат
            time_str = json_data['prepTime']
            return self._convert_iso_duration(time_str)
        
        return ""
    
    def extract_cook_time(self) -> str:
        """Извлечение времени приготовления"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'cookTime' in json_data:
            time_str = json_data['cookTime']
            return self._convert_iso_duration(time_str)
        
        return ""
    
    def extract_total_time(self) -> str:
        """Извлечение общего времени"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'totalTime' in json_data:
            time_str = json_data['totalTime']
            return self._convert_iso_duration(time_str)
        
        return ""
    
    def _convert_iso_duration(self, duration: str) -> str:
        """Конвертирует ISO 8601 duration (PT30M) в минуты (30)"""
        if not duration:
            return ""
        
        # Парсим формат PT30M, PT1H30M и т.д.
        hours = 0
        minutes = 0
        
        # Извлекаем часы
        h_match = re.search(r'(\d+)H', duration)
        if h_match:
            hours = int(h_match.group(1))
        
        # Извлекаем минуты
        m_match = re.search(r'(\d+)M', duration)
        if m_match:
            minutes = int(m_match.group(1))
        
        # Переводим все в минуты
        total_minutes = hours * 60 + minutes
        
        return str(total_minutes) if total_minutes > 0 else ""
    
    def extract_servings(self) -> str:
        """Извлечение количества порций"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'recipeYield' in json_data:
            yield_str = json_data['recipeYield']
            # Извлекаем число из строки типа "4 portion(s)"
            match = re.search(r'(\d+)', yield_str)
            if match:
                return match.group(1)
        
        return ""
    
    def extract_difficulty_level(self) -> str:
        """Извлечение уровня сложности"""
        # На ricardocuisine.com обычно нет явного уровня сложности
        # Можно попробовать определить по времени
        total_time = self.extract_total_time()
        if total_time:
            try:
                total_minutes = int(total_time)
                if total_minutes <= 30:
                    return "Easy"
                elif total_minutes <= 60:
                    return "Medium"
                else:
                    return "Hard"
            except (ValueError, TypeError):
                pass
        
        return "Medium"
    
    def extract_notes(self) -> str:
        """Извлечение заметок и примечаний"""
        # Ищем примечания от команды Ricardo в HTML
        note_article = self.soup.find('article', class_='c-recipe-note')
        if note_article:
            # Проверяем, что это не персональная заметка
            if 'c-recipe-note--personal' not in note_article.get('class', []):
                note_body = note_article.find('div', class_='c-recipe-note__body')
                if note_body:
                    # Извлекаем текст и очищаем HTML entities
                    notes = note_body.get_text(strip=True)
                    # Убираем &nbsp; и другие HTML entities
                    notes = notes.replace('\xa0', ' ')
                    return notes.strip()
        
        # Резервный вариант - ищем в общей секции notes
        notes_section = self.soup.find('section', class_='c-recipe-notes')
        if notes_section:
            note_body = notes_section.find('div', class_='c-recipe-note__body')
            if note_body:
                notes = note_body.get_text(strip=True)
                notes = notes.replace('\xa0', ' ')
                return notes.strip()
        
        return ""
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о пищевой ценности"""
        # На ricardocuisine.com обычно нет информации о калориях в явном виде
        # Пытаемся найти в JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'nutrition' in json_data:
            nutrition = json_data['nutrition']
            if isinstance(nutrition, dict):
                # Формируем строку из доступных данных
                parts = []
                if 'calories' in nutrition:
                    parts.append(f"{nutrition['calories']} kcal")
                if 'proteinContent' in nutrition:
                    parts.append(f"protein: {nutrition['proteinContent']}")
                if 'fatContent' in nutrition:
                    parts.append(f"fat: {nutrition['fatContent']}")
                if 'carbohydrateContent' in nutrition:
                    parts.append(f"carbs: {nutrition['carbohydrateContent']}")
                
                if parts:
                    return '; '.join(parts)
        
        # Ищем в HTML
        nutrition_section = self.soup.find('div', class_='nutrition-info')
        if nutrition_section:
            return nutrition_section.get_text(strip=True)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах (og:image, twitter:image:src)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image:src'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Если есть @graph, ищем ImageObject и Recipe
                if '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
                        # Recipe с image
                        elif item.get('@type') == 'Recipe' and 'image' in item:
                            img = item['image']
                            if isinstance(img, str):
                                urls.append(img)
                            elif isinstance(img, dict):
                                if 'url' in img:
                                    urls.append(img['url'])
                                elif 'contentUrl' in img:
                                    urls.append(img['contentUrl'])
                            elif isinstance(img, list):
                                for img_item in img:
                                    if isinstance(img_item, str):
                                        urls.append(img_item)
                                    elif isinstance(img_item, dict):
                                        if 'url' in img_item:
                                            urls.append(img_item['url'])
                                        elif 'contentUrl' in img_item:
                                            urls.append(img_item['contentUrl'])
                
                # Если Recipe напрямую (без @graph)
                elif data.get('@type') == 'Recipe' and 'image' in data:
                    img = data['image']
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, dict):
                        if 'url' in img:
                            urls.append(img['url'])
                        elif 'contentUrl' in img:
                            urls.append(img['contentUrl'])
                    elif isinstance(img, list):
                        for img_item in img:
                            if isinstance(img_item, str):
                                urls.append(img_item)
                            elif isinstance(img_item, dict):
                                if 'url' in img_item:
                                    urls.append(img_item['url'])
                                elif 'contentUrl' in img_item:
                                    urls.append(img_item['contentUrl'])
            
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            return ', '.join(unique_urls) if unique_urls else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data:
            # Основная категория
            if 'recipeCategory' in json_data:
                tags.append(json_data['recipeCategory'].strip().lower())
            
            # Подкатегории
            if 'recipeSubCategories' in json_data:
                for cat in json_data['recipeSubCategories']:
                    tags.append(cat.strip().lower())
            
            # Ключевые слова
            if 'keywords' in json_data:
                keywords = json_data['keywords']
                if isinstance(keywords, str):
                    for kw in keywords.split(','):
                        tags.append(kw.strip().lower())
        
        # Убираем дубликаты, сохраняя порядок
        if tags:
            seen = set()
            unique_tags = []
            for tag in tags:
                if tag and tag not in seen:
                    seen.add(tag)
                    unique_tags.append(tag)
            return ', '.join(unique_tags) if unique_tags else None
        
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
        step_by_step = self.extract_step_by_step()
        rating = self.extract_rating()
        category = self.extract_category()
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        total_time = self.extract_total_time()
        servings = self.extract_servings()
        difficulty_level = self.extract_difficulty_level()
        notes = self.extract_notes()
        nutrition_info = self.extract_nutrition_info()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name.lower() if dish_name else None,
            "description": description.lower() if description else None,
            "ingredients": ingredients,
            "step_by_step": step_by_step.lower() if step_by_step else None,
            "rating": rating,
            "category": category.lower() if category else None,
            "prep_time": prep_time if prep_time else None,
            "cook_time": cook_time if cook_time else None,
            "total_time": total_time if total_time else None,
            "servings": servings if servings else None,
            "difficulty_level": difficulty_level.lower() if difficulty_level else None,
            "notes": notes.lower() if notes else None,
            "nutrition_info": nutrition_info,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    """Основная функция для обработки файлов"""
    import sys
    
    if len(sys.argv) < 2:
        print("Использование: python ricardocuisine_com.py <путь_к_директории>")
        sys.exit(1)
    
    directory = sys.argv[1]
    process_directory(RicardoCuisineExtractor, directory)


if __name__ == "__main__":
    main()
