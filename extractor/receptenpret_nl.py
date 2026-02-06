"""
Экстрактор данных рецептов для сайта receptenpret.nl
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ReceptenpretNlExtractor(BaseRecipeExtractor):
    """Экстрактор для receptenpret.nl"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT140M"
            
        Returns:
            Время в формате "20 minutes", "1 hour and 30 minutes", "2 hours and 20 minutes"
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
        
        # Если только минуты и их больше 60, конвертируем в часы
        if hours == 0 and minutes >= 60:
            hours = minutes // 60
            minutes = minutes % 60
        
        # Форматируем в читаемый вид
        result_parts = []
        if hours > 0:
            result_parts.append(f"{hours} hour" + ("s" if hours > 1 else ""))
        if minutes > 0:
            result_parts.append(f"{minutes} minute" + ("s" if minutes > 1 else ""))
        
        if result_parts:
            return " and ".join(result_parts)
        
        return None
    
    def parse_ingredient_string(self, ingredient_str: str) -> dict:
        """
        Парсит строку ингредиента вида "250 ml Romige pindakaas"
        
        Args:
            ingredient_str: строка ингредиента из JSON-LD
            
        Returns:
            dict с полями name, amount, units
        """
        if not ingredient_str:
            return {"name": None, "amount": None, "units": None}
        
        # Чистим текст
        text = self.clean_text(ingredient_str)
        
        # Паттерн: "количество единица название"
        # Примеры: "250 ml Romige pindakaas", "115 gram Ongezouten roomboter"
        pattern = r'^(\d+(?:[.,]\d+)?)\s+(ml|gram|liter|kg|g|l|st|stuks?|tbsp|tsp|cup|eetlepels?|theelepels?|kop(?:jes)?|snufje)\s+(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str = match.group(1).replace(',', '.')
            # Конвертируем в int если это целое число, иначе float
            try:
                amount = int(amount_str) if '.' not in amount_str else float(amount_str)
            except ValueError:
                amount = amount_str
            
            units = match.group(2).lower()
            name = match.group(3)
            
            return {
                "name": name,
                "units": units,
                "amount": amount
            }
        
        # Если паттерн не совпал, пробуем упрощенный вариант
        # Только количество в начале
        simple_pattern = r'^(\d+(?:[.,]\d+)?)\s+(.+)$'
        simple_match = re.match(simple_pattern, text)
        
        if simple_match:
            amount_str = simple_match.group(1).replace(',', '.')
            try:
                amount = int(amount_str) if '.' not in amount_str else float(amount_str)
            except ValueError:
                amount = amount_str
            
            return {
                "name": simple_match.group(2),
                "units": None,
                "amount": amount
            }
        
        # Если совсем не распарсилось, возвращаем только название
        return {
            "name": text,
            "units": None,
            "amount": None
        }
    
    def extract_from_json_ld(self) -> Optional[dict]:
        """
        Извлечение данных из JSON-LD
        
        Returns:
            dict с данными рецепта из JSON-LD или None
        """
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в @graph или напрямую
                recipe_data = None
                
                if isinstance(data, dict):
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and item.get('@type') == 'Recipe':
                                recipe_data = item
                                break
                    elif data.get('@type') == 'Recipe':
                        recipe_data = data
                
                if recipe_data:
                    return recipe_data
                    
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self, recipe_data: Optional[dict] = None) -> Optional[str]:
        """Извлечение названия блюда"""
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Fallback: meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s*[-–:]\s*Recepten Pret$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*Recept.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self, recipe_data: Optional[dict] = None) -> Optional[str]:
        """Извлечение описания рецепта"""
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Fallback: meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def extract_ingredients(self, recipe_data: Optional[dict] = None) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients_list = []
        
        # Сначала пробуем из JSON-LD
        if recipe_data and 'recipeIngredient' in recipe_data:
            for ingredient_str in recipe_data['recipeIngredient']:
                parsed = self.parse_ingredient_string(ingredient_str)
                if parsed and parsed.get('name'):
                    ingredients_list.append(parsed)
            
            if ingredients_list:
                return json.dumps(ingredients_list, ensure_ascii=False)
        
        # Fallback: ищем в HTML под заголовком "Ingrediënten"
        # Ищем заголовок с текстом "Ingrediënten"
        for heading in self.soup.find_all(['h2', 'h3']):
            heading_text = heading.get_text(strip=True)
            if 'ingrediënt' in heading_text.lower():
                # Ищем следующий <ul> список после заголовка
                next_element = heading.find_next_sibling()
                while next_element:
                    if next_element.name == 'ul':
                        # Нашли список ингредиентов
                        for li in next_element.find_all('li'):
                            ingredient_text = self.clean_text(li.get_text(strip=True))
                            if ingredient_text:
                                # Парсим ингредиент
                                parsed = self.parse_ingredient_string(ingredient_text)
                                if parsed and parsed.get('name'):
                                    ingredients_list.append(parsed)
                        break
                    elif next_element.name in ['h2', 'h3', 'h4']:
                        # Дошли до следующего заголовка - прекращаем поиск
                        break
                    next_element = next_element.find_next_sibling()
                
                if ingredients_list:
                    break
        
        if ingredients_list:
            return json.dumps(ingredients_list, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self, recipe_data: Optional[dict] = None) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions_list = []
        
        # Сначала пробуем из JSON-LD
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict):
                        # HowToStep с полем text или name
                        text = step.get('text') or step.get('name')
                        if text:
                            instructions_list.append(self.clean_text(text))
                    elif isinstance(step, str):
                        instructions_list.append(self.clean_text(step))
            elif isinstance(instructions, str):
                instructions_list.append(self.clean_text(instructions))
            
            if instructions_list:
                # Форматируем с номерами шагов если их нет
                formatted_steps = []
                for idx, step in enumerate(instructions_list, 1):
                    # Проверяем, есть ли уже номер в начале
                    if not re.match(r'^(Stap\s+)?\d+[\.:)]', step, re.IGNORECASE):
                        formatted_steps.append(f"Stap {idx}: {step}")
                    else:
                        formatted_steps.append(step)
                
                return ' '.join(formatted_steps)
        
        # Fallback: ищем в HTML под заголовком "Bereiding"
        # Ищем заголовок с текстом "Bereiding"
        for heading in self.soup.find_all(['h2', 'h3']):
            heading_text = heading.get_text(strip=True)
            if 'bereiding' in heading_text.lower():
                # Ищем все подзаголовки h3 с "Stap" после основного заголовка
                current = heading.find_next_sibling()
                while current:
                    if current.name == 'h3':
                        step_heading = self.clean_text(current.get_text(strip=True))
                        # Проверяем, начинается ли с "Stap"
                        if step_heading.lower().startswith('stap'):
                            # Ищем следующий параграф с текстом шага
                            next_p = current.find_next_sibling('p')
                            if next_p:
                                step_text = self.clean_text(next_p.get_text(strip=True))
                                # Комбинируем заголовок и текст
                                instructions_list.append(f"{step_heading}")
                    elif current.name == 'h2':
                        # Дошли до следующего основного заголовка - прекращаем
                        break
                    current = current.find_next_sibling()
                
                if instructions_list:
                    break
        
        if instructions_list:
            return ' '.join(instructions_list)
        
        return None
    
    def extract_category(self, recipe_data: Optional[dict] = None) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в meta article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            category = self.clean_text(meta_section['content'])
            # Переводим общие категории на английский
            category_map = {
                'ijs en desserts': 'Dessert',
                'dessert': 'Dessert',
                'hoofdgerecht': 'Main Course',
                'main course': 'Main Course',
                'voorgerecht': 'Appetizer',
                'bijgerecht': 'Side Dish'
            }
            return category_map.get(category.lower(), category)
        
        # Альтернативно из JSON-LD recipeCategory
        if recipe_data and 'recipeCategory' in recipe_data:
            return self.clean_text(recipe_data['recipeCategory'])
        
        return None
    
    def extract_prep_time(self, recipe_data: Optional[dict] = None) -> Optional[str]:
        """Извлечение времени подготовки"""
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self, recipe_data: Optional[dict] = None) -> Optional[str]:
        """Извлечение времени готовки"""
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self, recipe_data: Optional[dict] = None) -> Optional[str]:
        """Извлечение общего времени"""
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем элементы с классами, содержащими "note", "tip", "advice"
        notes_candidates = self.soup.find_all(class_=re.compile(r'(note|tip|advice|opmerking)', re.I))
        
        for candidate in notes_candidates:
            text = candidate.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            # Удаляем префиксы типа "Notes", "Tips", "Note:"
            text = re.sub(r'^(Notes?|Tips?|Opmerking(?:en)?|Advies)\s*[:–-]?\s*', '', text, flags=re.IGNORECASE)
            if text and len(text) > 20:  # Минимальная длина для заметки
                return text
        
        # Ищем параграфы после определенных заголовков
        for heading in self.soup.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text(strip=True).lower()
            if any(keyword in heading_text for keyword in ['tip', 'note', 'opmerking', 'advies', 'bewaar']):
                # Ищем следующий параграф
                next_p = heading.find_next('p')
                if next_p:
                    text = self.clean_text(next_p.get_text(separator=' ', strip=True))
                    # Удаляем префиксы
                    text = re.sub(r'^(Notes?|Tips?|Opmerking(?:en)?|Advies)\s*[:–-]?\s*', '', text, flags=re.IGNORECASE)
                    if text and len(text) > 20:
                        return text
        
        return None
    
    def extract_tags(self, recipe_data: Optional[dict] = None) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Из meta article:tag
        meta_tags = self.soup.find_all('meta', property='article:tag')
        for tag in meta_tags:
            if tag.get('content'):
                tag_text = self.clean_text(tag['content']).lower()
                if tag_text and tag_text not in tags_list:
                    tags_list.append(tag_text)
        
        # Из JSON-LD keywords
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Разделяем по запятой
                for keyword in keywords.split(','):
                    keyword = self.clean_text(keyword).lower()
                    if keyword and keyword not in tags_list:
                        tags_list.append(keyword)
            elif isinstance(keywords, list):
                for keyword in keywords:
                    keyword = self.clean_text(str(keyword)).lower()
                    if keyword and keyword not in tags_list:
                        tags_list.append(keyword)
        
        if tags_list:
            return ', '.join(tags_list)
        
        return None
    
    def extract_image_urls(self, recipe_data: Optional[dict] = None) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Из JSON-LD image
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                # Берем только первое изображение (обычно самое качественное)
                for image_item in img[:1]:
                    if isinstance(image_item, str):
                        urls.append(image_item)
                    elif isinstance(image_item, dict) and 'url' in image_item:
                        urls.append(image_item['url'])
            elif isinstance(img, dict) and 'url' in img:
                urls.append(img['url'])
        
        # Fallback: og:image
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
        
        if urls:
            # Убираем дубликаты
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
        # Сначала извлекаем JSON-LD данные
        recipe_data = self.extract_from_json_ld()
        
        # Извлекаем все поля
        dish_name = self.extract_dish_name(recipe_data)
        description = self.extract_description(recipe_data)
        ingredients = self.extract_ingredients(recipe_data)
        instructions = self.extract_instructions(recipe_data)
        category = self.extract_category(recipe_data)
        prep_time = self.extract_prep_time(recipe_data)
        cook_time = self.extract_cook_time(recipe_data)
        total_time = self.extract_total_time(recipe_data)
        notes = self.extract_notes()
        tags = self.extract_tags(recipe_data)
        image_urls = self.extract_image_urls(recipe_data)
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "notes": notes,
            "tags": tags,
            "image_urls": image_urls
        }


def main():
    """Точка входа для тестирования парсера"""
    import os
    
    # Обрабатываем папку preprocessed/receptenpret_nl
    preprocessed_dir = os.path.join("preprocessed", "receptenpret_nl")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ReceptenpretNlExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python receptenpret_nl.py")


if __name__ == "__main__":
    main()
