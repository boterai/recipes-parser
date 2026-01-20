"""
Экстрактор данных рецептов для сайта schlemmenjetzt.de
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class SchlemmenjentztDeExtractor(BaseRecipeExtractor):
    """Экстрактор для schlemmenjetzt.de"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат (всегда в минутах)
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "20 minutes" или "105 minutes"
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
        
        # Переводим все в минуты
        total_minutes = hours * 60 + minutes
        
        if total_minutes == 0:
            return None
        
        return f"{total_minutes} minute{'s' if total_minutes != 1 else ''}"
    
    def get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем тип Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            name = self.clean_text(recipe_data['name'])
            # Убираем субтитры после тире с пробелами или двоеточия
            name = re.sub(r'\s+[–—]\s+.*$', '', name)
            name = re.sub(r'\s*:\s*.*$', '', name)
            return name
        
        # Альтернативно - из заголовка страницы
        h1 = self.soup.find('h1')
        if h1:
            name = self.clean_text(h1.get_text())
            # Убираем субтитры
            name = re.sub(r'\s+[–—]\s+.*$', '', name)
            name = re.sub(r'\s*:\s*.*$', '', name)
            return name
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем первый параграф после заголовка в содержимом статьи
        # Обычно это первый <p> в entry-content или article
        entry_content = self.soup.find('div', class_=re.compile(r'entry-content|article-content', re.I))
        if entry_content:
            # Находим первый параграф
            first_p = entry_content.find('p')
            if first_p:
                # Берем только первое предложение
                text = first_p.get_text(strip=True)
                # Находим первое предложение (до первой точки с пробелом после)
                match = re.search(r'^[^.]+\.', text)
                if match:
                    return self.clean_text(match.group(0))
                return self.clean_text(text)
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient_string(self, ingredient_str: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_str: Строка вида "500 g Kartoffeln, geschält und gewürfelt"
            
        Returns:
            dict: {"name": "Kartoffeln", "amount": 500, "units": "g"}
        """
        if not ingredient_str:
            return None
        
        # Очищаем текст
        text = self.clean_text(ingredient_str)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "500 g Kartoffeln", "1 kleine Zwiebel", "2 EL frische Petersilie"
        pattern = r'^([\d\s/.,]+)?\s*(g|kg|ml|l|TL|EL|Pck\.|Prise|kleine?|große?|mittelgroße?|for\s+\w+|zum\s+\w+)?\s*(.+?)(?:,.*)?$'
        
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
            # Обработка дробей типа "1/2"
            if '/' in amount_str:
                parts = amount_str.split('/')
                if len(parts) == 2:
                    try:
                        val = float(parts[0]) / float(parts[1])
                        # Преобразуем в int если это целое число
                        if val == int(val):
                            amount = int(val)
                        else:
                            amount = val
                    except ValueError:
                        amount = amount_str
            else:
                try:
                    val = float(amount_str.replace(',', '.'))
                    # Преобразуем в int если это целое число
                    if val == int(val):
                        amount = int(val)
                    else:
                        amount = val
                except ValueError:
                    amount = amount_str
        
        # Обработка единицы измерения - переводим некоторые на английский
        if unit:
            unit = unit.strip()
            # Переводим "kleine" -> "small", "große" -> "large", etc.
            unit_translations = {
                'kleine': 'small',
                'kleiner': 'small',
                'große': 'large',
                'großer': 'large',
                'mittelgroße': 'medium',
                'zum bestreichen': 'for brushing',
            }
            unit_lower = unit.lower()
            for de_unit, en_unit in unit_translations.items():
                if de_unit in unit_lower:
                    unit = en_unit
                    break
        
        # Очистка названия - убираем описания в скобках и после запятой
        name = re.sub(r'\([^)]*\)', '', name)
        name = re.sub(r',.*$', '', name)
        name = self.clean_text(name)
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате JSON-строки"""
        ingredients = []
        
        # Извлекаем из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'recipeIngredient' in recipe_data:
            for ing_str in recipe_data['recipeIngredient']:
                parsed = self.parse_ingredient_string(ing_str)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций как единой строки"""
        steps = []
        
        # Извлекаем из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        if step_text:
                            steps.append(step_text)
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        if step_text:
                            steps.append(step_text)
            elif isinstance(instructions, str):
                return self.clean_text(instructions)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в метаданных article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'recipeCategory' in recipe_data:
            return self.clean_text(recipe_data['recipeCategory'])
        
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
        """Извлечение заметок"""
        # Ищем секцию с примечаниями - обычно это div с классом tasty-recipes-notes
        notes_div = self.soup.find('div', class_=re.compile(r'tasty-recipes-notes', re.I))
        if notes_div:
            # Находим тело заметок
            notes_body = notes_div.find('div', class_=re.compile(r'tasty-recipes-notes-body', re.I))
            if notes_body:
                # Собираем все параграфы
                notes_parts = []
                for p in notes_body.find_all('p'):
                    text = self.clean_text(p.get_text())
                    if text:
                        notes_parts.append(text)
                
                if notes_parts:
                    return ' '.join(notes_parts)
        
        # Альтернативный поиск - по заголовкам
        notes_keywords = ['hinweise', 'tipps', 'notizen', 'anmerkungen', 'notes', 'tips']
        
        for keyword in notes_keywords:
            heading = self.soup.find(['h2', 'h3', 'h4'], string=re.compile(keyword, re.IGNORECASE))
            if heading:
                # Собираем текст после заголовка
                notes_parts = []
                for sibling in heading.find_next_siblings():
                    if sibling.name in ['h2', 'h3', 'h4']:
                        break
                    if sibling.name == 'p':
                        text = self.clean_text(sibling.get_text())
                        if text:
                            notes_parts.append(text)
                    elif sibling.name == 'ul':
                        for li in sibling.find_all('li'):
                            text = self.clean_text(li.get_text())
                            if text:
                                notes_parts.append(text)
                
                if notes_parts:
                    return ' '.join(notes_parts)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Ищем в JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            elif isinstance(keywords, list):
                tags_list = [str(tag).strip() for tag in keywords if tag]
        
        # Ищем в meta keywords
        if not tags_list:
            meta_keywords = self.soup.find('meta', {'name': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                tags_list = [tag.strip() for tag in meta_keywords['content'].split(',') if tag.strip()]
        
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Извлекаем из JSON-LD
        recipe_data = self.get_recipe_json_ld()
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
        
        # Дополнительно ищем в meta og:image
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
        
        # Убираем дубликаты
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
    # Обрабатываем папку preprocessed/schlemmenjetzt_de
    recipes_dir = os.path.join("preprocessed", "schlemmenjetzt_de")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(SchlemmenjentztDeExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python schlemmenjetzt_de.py")


if __name__ == "__main__":
    main()
