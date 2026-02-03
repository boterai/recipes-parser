"""
Экстрактор данных рецептов для сайта punkufer.dnevnik.hr
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class PunkuferExtractor(BaseRecipeExtractor):
    """Экстрактор для punkufer.dnevnik.hr"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах, например "90 minutes"
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
    
    def get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение Recipe JSON-LD из страницы"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                # Проверяем @type
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def get_news_article_json_ld(self) -> Optional[dict]:
        """Извлечение NewsArticle JSON-LD из страницы"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                # Проверяем @type
                if isinstance(data, dict) and data.get('@type') == 'NewsArticle':
                    return data
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r':\s+.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из NewsArticle
        news_data = self.get_news_article_json_ld()
        if news_data and 'description' in news_data:
            return self.clean_text(news_data['description'])
        
        # Затем из Recipe
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient_string(self, ingredient_str: str) -> dict:
        """
        Парсинг строки ингредиента из JSON-LD в структурированный формат
        
        Args:
            ingredient_str: Строка вида "2 žlice crvenog miso umaka"
            
        Returns:
            dict: {"name": "crveni miso umak", "amount": "2", "unit": "žlice"}
        """
        if not ingredient_str:
            return {"name": None, "amount": None, "unit": None}
        
        # Чистим текст
        text = self.clean_text(ingredient_str).strip()
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Список единиц измерения (хорватский язык)
        # Порядок важен - более длинные единицы должны идти первыми
        units_list = [
            'čajne žličice', 'čajnih žličica', 'čajna žličica',
            'žličice', 'žličica', 'žlice', 'žlica',
            'šalice', 'šalica', 'šalicu',
            'kilograma', 'kilogram', 'grama', 'gram',
            'litre', 'litra',
            'mililitara', 'mililitra',
            'komada', 'komad',
            'listova', 'lista', 'list',
            'prstohvata', 'prstohvat',
            'tablespoons', 'tablespoon', 'teaspoons', 'teaspoon',
            'cups', 'cup', 'pounds', 'pound', 'ounces', 'ounce',
            'tbsp', 'tsp', 'cloves', 'clove',
            'kg', 'ml', 'oz', 'lb', 'g', 'l',
            'kom',
        ]
        
        # Первый проход - ищем количество в начале
        amount_pattern = r'^([\d\s/.,]+)\s+'
        amount_match = re.match(amount_pattern, text)
        
        if not amount_match:
            # Нет количества в начале
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
        
        amount_str = amount_match.group(1).strip()
        rest = text[amount_match.end():]
        
        # Обработка количества
        amount = None
        if amount_str:
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
                amount = str(total) if total != int(total) else str(int(total))
            else:
                amount_str = amount_str.replace(',', '.')
                try:
                    amount_val = float(amount_str)
                    amount = str(amount_val) if amount_val != int(amount_val) else str(int(amount_val))
                except ValueError:
                    amount = amount_str
        
        # Проверяем, есть ли сразу после количества единица измерения
        unit = None
        name = rest
        
        for unit_candidate in units_list:
            # Проверяем, начинается ли остаток с этой единицы (case-insensitive)
            if rest.lower().startswith(unit_candidate.lower()):
                # Убеждаемся, что после единицы идет пробел или конец строки
                unit_len = len(unit_candidate)
                if unit_len == len(rest) or rest[unit_len].isspace():
                    unit = unit_candidate
                    name = rest[unit_len:].strip()
                    break
        
        # Очистка названия
        if name:
            # Удаляем скобки с содержимым в конце
            name = re.sub(r'\([^)]*\)\s*$', '', name)
            name = re.sub(r'\[[^\]]*\]\s*$', '', name)
            # Удаляем запятые и текст после них (часто это примечания)
            name = re.sub(r',.*$', '', name)
            # Удаляем лишние пробелы
            name = re.sub(r'\s+', ' ', name).strip()
        
        return {
            "name": name if name else None,
            "amount": amount,
            "unit": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        recipe_data = self.get_recipe_json_ld()
        
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredients = []
        recipe_ingredients = recipe_data['recipeIngredient']
        
        if isinstance(recipe_ingredients, list):
            for ingredient_str in recipe_ingredients:
                if isinstance(ingredient_str, str) and ingredient_str.strip():
                    parsed = self.parse_ingredient_string(ingredient_str)
                    # Переименовываем unit в units для соответствия формату
                    if parsed:
                        ingredients.append({
                            "name": parsed["name"],
                            "amount": parsed["amount"],
                            "units": parsed["unit"]
                        })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self.get_recipe_json_ld()
        
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        steps = []
        
        if isinstance(instructions, list):
            for step in instructions:
                if isinstance(step, dict) and 'text' in step:
                    text = self.clean_text(step['text'])
                    if text:
                        steps.append(text)
                elif isinstance(step, str):
                    text = self.clean_text(step)
                    if text:
                        steps.append(text)
        elif isinstance(instructions, str):
            return self.clean_text(instructions)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            # Конвертируем на английский (glavno jelo -> Main Course)
            category_map = {
                'glavno jelo': 'Main Course',
                'desert': 'Dessert',
                'predjelo': 'Appetizer',
                'juha': 'Soup',
                'salata': 'Salad',
                'prilog': 'Side Dish',
            }
            category_clean = self.clean_text(category).lower()
            return category_map.get(category_clean, category_clean.title())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Извлекаем из NewsArticle.articleBody как дополнительный контекст
        news_data = self.get_news_article_json_ld()
        
        if news_data and 'articleBody' in news_data:
            article_body = self.clean_text(news_data['articleBody'])
            # Ограничиваем длину, берем первое предложение как заметку
            if article_body:
                # Извлекаем первое или второе предложение как заметку
                sentences = article_body.split('. ')
                if len(sentences) > 1:
                    # Берем предложение, которое содержит полезную информацию
                    for sent in sentences:
                        if len(sent) > 30 and not sent.startswith('Fileti'):
                            return sent + '.'
                    return sentences[0] + '.' if sentences[0] else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Сначала пробуем из NewsArticle.keywords
        news_data = self.get_news_article_json_ld()
        if news_data and 'keywords' in news_data:
            keywords = news_data['keywords']
            if isinstance(keywords, str):
                tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        # Если не нашли, пробуем из Recipe.keywords
        if not tags_list:
            recipe_data = self.get_recipe_json_ld()
            if recipe_data and 'keywords' in recipe_data:
                keywords = recipe_data['keywords']
                if isinstance(keywords, str):
                    tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        if not tags_list:
            return None
        
        # Фильтруем общие слова
        stopwords = {'recepti', 'što kuhati', 'recept'}
        filtered_tags = [tag for tag in tags_list if tag.lower() not in stopwords]
        
        return ', '.join(filtered_tags) if filtered_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'image' in recipe_data:
            images = recipe_data['image']
            
            if isinstance(images, str):
                urls.append(images)
            elif isinstance(images, list):
                urls.extend([img for img in images if isinstance(img, str)])
        
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
    import os
    # Обрабатываем папку preprocessed/punkufer_dnevnik_hr
    recipes_dir = os.path.join("preprocessed", "punkufer_dnevnik_hr")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(PunkuferExtractor, recipes_dir)
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python punkufer_dnevnik_hr.py")


if __name__ == "__main__":
    main()
