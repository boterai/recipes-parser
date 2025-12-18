"""
Экстрактор данных рецептов для сайта feed.continente.pt
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class FeedContinentePtExtractor(BaseRecipeExtractor):
    """Экстрактор для feed.continente.pt"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах, например "90 minutes" или None
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
            # Возвращаем в формате "X minutes" или "X min"
            if total_minutes == 1:
                return "1 minute"
            else:
                return f"{total_minutes} minutes"
        
        return None
    
    def get_json_ld_recipe(self) -> Optional[dict]:
        """
        Извлекает данные рецепта из JSON-LD схемы
        
        Returns:
            Словарь с данными рецепта из JSON-LD или None
        """
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            if not script.string:
                continue
                
            try:
                data = json.loads(script.string)
                
                # Проверяем, является ли это рецептом
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self.get_json_ld_recipe()
        
        if recipe_data and 'name' in recipe_data:
            name = recipe_data['name']
            # Убираем HTML entities и лишний текст типа "Yämmi"
            name = self.clean_text(name)
            # Убираем суффикс "Yämmi" если есть
            name = re.sub(r'\s+Y[äa]mmi\s*$', '', name, flags=re.IGNORECASE)
            return name
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s+\|.*$', '', title)
            title = re.sub(r'\s+Y[äa]mmi\s*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self.get_json_ld_recipe()
        
        if recipe_data and 'description' in recipe_data:
            description = recipe_data['description']
            return self.clean_text(description)
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        recipe_data = self.get_json_ld_recipe()
        
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredients_list = recipe_data['recipeIngredient']
        if not isinstance(ingredients_list, list):
            return None
        
        parsed_ingredients = []
        
        for ingredient_text in ingredients_list:
            ingredient_text = self.clean_text(ingredient_text)
            if not ingredient_text:
                continue
            
            # Парсим ингредиент в структурированный формат
            parsed = self.parse_ingredient(ingredient_text)
            if parsed:
                parsed_ingredients.append(parsed)
        
        return json.dumps(parsed_ingredients, ensure_ascii=False) if parsed_ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "400 g de brócolos" или "4 ovos"
            
        Returns:
            dict: {"name": "brócolos", "units": "g", "amount": 400} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = ingredient_text.strip()
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "400 g de brócolos", "10 g de azeite + Azeite para untar", "4 ovos", "1 dente de alho"
        
        # Пробуем паттерн с единицей измерения
        pattern_with_unit = r'^([\d,./]+)\s*(g|kg|ml|l|c\.\s*(?:chá|sobremesa|sopa)|dente|dentes)(?:\s+de)?\s+(.+)$'
        match = re.match(pattern_with_unit, text, re.IGNORECASE)
        
        if match:
            amount_str, units, name = match.groups()
            amount = amount_str.replace(',', '.')
            units = units.strip()
            
            # Очистка названия
            name = re.sub(r'\s*\+.*$', '', name)  # Убираем "+ дополнительно"
            name = re.sub(r'\s*\(.*?\)', '', name)  # Убираем скобки
            name = re.sub(r'\s+(a gosto|opcional|para servir).*$', '', name, flags=re.IGNORECASE)
            name = name.strip()
            
            # Пытаемся конвертировать amount в число
            try:
                if '.' in amount or '/' in amount:
                    amount = float(amount) if '.' in amount else amount
                else:
                    amount = int(amount)
            except:
                pass
            
            return {
                "name": name,
                "units": units,
                "amount": amount
            }
        
        # Пробуем паттерн без единицы измерения
        pattern_without_unit = r'^(\d+)\s+(.+)$'
        match = re.match(pattern_without_unit, text)
        
        if match:
            amount_str, name = match.groups()
            
            # Очистка названия
            name = re.sub(r'\s*\+.*$', '', name)
            name = re.sub(r'\s*\(.*?\)', '', name)
            name = re.sub(r'\s+(a gosto|opcional|para servir).*$', '', name, flags=re.IGNORECASE)
            name = name.strip()
            
            # Конвертируем amount в число
            try:
                amount = int(amount_str)
            except:
                amount = amount_str
            
            return {
                "name": name,
                "units": None,
                "amount": amount
            }
        
        # Если паттерн не совпал, возвращаем только название
        # Очистка
        text = re.sub(r'\s*\(.*?\)', '', text)
        text = re.sub(r'\s+(a gosto|opcional|para servir).*$', '', text, flags=re.IGNORECASE)
        text = text.strip()
        
        return {
            "name": text,
            "units": None,
            "amount": None
        }
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self.get_json_ld_recipe()
        
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        if not isinstance(instructions, list):
            return None
        
        steps = []
        
        for idx, step in enumerate(instructions, 1):
            if isinstance(step, dict) and 'text' in step:
                step_text = self.clean_text(step['text'])
                if step_text:
                    steps.append(f"{idx}. {step_text}")
            elif isinstance(step, str):
                step_text = self.clean_text(step)
                if step_text:
                    steps.append(f"{idx}. {step_text}")
        
        return ' '.join(steps) if steps else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности из HTML таблицы"""
        # Ищем таблицу с питательной информацией
        nutrition_table = self.soup.find('div', class_='recipeNutricionalTable__table')
        
        if not nutrition_table:
            return None
        
        # Извлекаем данные
        nutrition_data = {}
        
        items = nutrition_table.find_all('div', class_='recipeNutricionalTable__table__item')
        for item in items:
            title_elem = item.find('p', class_='itemTitle')
            value_elem = item.find('p', class_='itemValue')
            
            if title_elem and value_elem:
                title = title_elem.get_text(strip=True)
                value_text = value_elem.get_text(strip=True)
                
                # Извлекаем числовое значение
                value_match = re.search(r'([\d,]+)', value_text)
                if value_match:
                    value = value_match.group(1).replace(',', '.')
                    
                    # Извлекаем единицу измерения
                    unit_match = re.search(r'(KCAL|g)', value_text, re.IGNORECASE)
                    unit = unit_match.group(1) if unit_match else ''
                    
                    nutrition_data[title] = f"{value} {unit}".strip()
        
        # Форматируем в требуемый вид: "Valores por porção: Calorias 254 KCAL, ..."
        if nutrition_data:
            parts = []
            for key, value in nutrition_data.items():
                parts.append(f"{key} {value}")
            
            return "Valores por porção: " + ", ".join(parts) + "."
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self.get_json_ld_recipe()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            return self.clean_text(category)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.get_json_ld_recipe()
        
        if recipe_data and 'prepTime' in recipe_data:
            iso_time = recipe_data['prepTime']
            parsed = self.parse_iso_duration(iso_time)
            if parsed:
                # Преобразуем в более короткий формат если это "X minutes"
                parsed = parsed.replace(' minutes', ' min').replace(' minute', ' min')
            return parsed
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self.get_json_ld_recipe()
        
        # На feed.continente.pt обычно нет отдельного cookTime
        if recipe_data and 'cookTime' in recipe_data:
            iso_time = recipe_data['cookTime']
            parsed = self.parse_iso_duration(iso_time)
            if parsed:
                parsed = parsed.replace(' minutes', ' min').replace(' minute', ' min')
            return parsed
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.get_json_ld_recipe()
        
        if recipe_data and 'totalTime' in recipe_data:
            iso_time = recipe_data['totalTime']
            parsed = self.parse_iso_duration(iso_time)
            if parsed:
                parsed = parsed.replace(' minutes', ' min').replace(' minute', ' min')
            return parsed
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию notes
        notes_section = self.soup.find('div', class_='notes__body')
        
        if notes_section:
            # Извлекаем текст, но пропускаем заголовок "Dicas"
            text_format = notes_section.find('div', class_='textFormat')
            if text_format:
                # Пропускаем заголовок
                paragraphs = text_format.find_all(['p', 'div'], class_='font-m')
                texts = []
                for p in paragraphs:
                    # Пропускаем заголовки
                    if p.find('strong') and 'Dicas' in p.get_text():
                        continue
                    text = p.get_text(strip=True)
                    if text and text != 'Dicas':
                        texts.append(text)
                
                if texts:
                    return self.clean_text(' '.join(texts))
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем теги в HTML
        # Теги обычно находятся в элементах с классом "articleTag"
        tag_elements = self.soup.find_all('h3', class_='articleTag')
        
        for tag_elem in tag_elements:
            # Берем текст из ссылки внутри
            link = tag_elem.find('a')
            if link:
                tag_text = link.get_text(strip=True)
                if tag_text:
                    tags.append(tag_text.lower())
        
        # Также попробуем получить из JSON-LD keywords
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Может быть через запятую
                for keyword in keywords.split(','):
                    keyword = keyword.strip().lower()
                    if keyword and keyword not in tags:
                        tags.append(keyword)
        
        # Добавляем категорию как тег
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory'].lower()
            if category and category not in tags:
                tags.append(category)
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        recipe_data = self.get_json_ld_recipe()
        
        if recipe_data and 'image' in recipe_data:
            images = recipe_data['image']
            if isinstance(images, str):
                urls.append(images)
            elif isinstance(images, list):
                urls.extend([img for img in images if isinstance(img, str)])
        
        # Также ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            img_url = og_image['content']
            if img_url not in urls:
                urls.append(img_url)
        
        # Убираем дубликаты
        unique_urls = []
        seen = set()
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
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
            "instructions": self.extract_steps(),
            "nutrition_info": self.extract_nutrition_info(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Точка входа для обработки директории с HTML-страницами"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "feed_continente_pt")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(FeedContinentePtExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python feed_continente_pt.py")


if __name__ == "__main__":
    main()
