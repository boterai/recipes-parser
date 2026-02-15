"""
Екстрактор данных рецептов для сайта fayni-recepty.com.ua
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class FayniReceptyExtractor(BaseRecipeExtractor):
    """Екстрактор для fayni-recepty.com.ua"""
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение Recipe данных из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT5M"
            
        Returns:
            Время в читаемом формате, например "20 minutes" или "1 hours 30 minutes"
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
        
        # Форматируем результат
        if hours > 0 and minutes > 0:
            return f"{hours} hours {minutes} minutes"
        elif hours > 0:
            return f"{hours} hours"
        elif minutes > 0:
            return f"{minutes} minutes"
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "150 g нарізаних печериць" или "4 яйця"
            
        Returns:
            dict: {"name": "...", "amount": ..., "units": "..."} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "150 g нарізаних печериць", "4 шматочки бекону", "1 бляшанка квасолі..."
        pattern = r'^(\d+(?:[.,]\d+)?)\s*(g|ml|kg|l|tsp|tbsp|cup|cups|бляшанка|шматочки|скибочки|великі)?\s*(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества - конвертируем в число
        amount = None
        if amount_str:
            amount_str = amount_str.replace(',', '.')
            try:
                # Пытаемся конвертировать в int, если возможно
                if '.' in amount_str:
                    amount = float(amount_str)
                else:
                    amount = int(amount_str)
            except ValueError:
                amount = None
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия от лишних слов
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Или из заголовка страницы
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Или из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredients_list = []
        
        for ingredient_text in recipe_data['recipeIngredient']:
            parsed = self.parse_ingredient(ingredient_text)
            if parsed:
                ingredients_list.append(parsed)
        
        return json.dumps(ingredients_list, ensure_ascii=False) if ingredients_list else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        recipe_data = self._get_recipe_json_ld()
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        steps = []
        
        def extract_steps_from_item(item):
            """Рекурсивно извлекаем шаги из элемента"""
            if isinstance(item, dict):
                # HowToStep с текстом
                if item.get('@type') == 'HowToStep' and 'text' in item:
                    step_text = self.clean_text(item['text'])
                    if step_text:
                        steps.append(step_text)
                # HowToSection с вложенными шагами
                elif item.get('@type') == 'HowToSection' and 'itemListElement' in item:
                    for sub_item in item['itemListElement']:
                        extract_steps_from_item(sub_item)
                # Просто dict с text
                elif 'text' in item:
                    step_text = self.clean_text(item['text'])
                    if step_text:
                        steps.append(step_text)
            elif isinstance(item, str):
                step_text = self.clean_text(item)
                if step_text:
                    steps.append(step_text)
        
        if isinstance(instructions, list):
            for item in instructions:
                extract_steps_from_item(item)
        elif isinstance(instructions, str):
            return self.clean_text(instructions)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Ищем в Yoast JSON-LD @graph
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list):
                                # Берем первую категорию или объединяем все
                                return sections[0] if sections else None
                            elif isinstance(sections, str):
                                return sections
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/примечаний к рецепту"""
        # Ищем блоки с классами, которые могут содержать примечания
        notes_patterns = [
            re.compile(r'note', re.I),
            re.compile(r'tip', re.I),
            re.compile(r'примітк', re.I),
            re.compile(r'порад', re.I)
        ]
        
        for pattern in notes_patterns:
            notes_elem = self.soup.find(class_=pattern)
            if notes_elem:
                text = self.clean_text(notes_elem.get_text())
                if text and len(text) > 10:  # Минимальная длина
                    return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта"""
        # Ищем в WordPress Recipe Maker cuisine field
        cuisine_elem = self.soup.find(class_='wprm-recipe-cuisine')
        if cuisine_elem:
            cuisine = self.clean_text(cuisine_elem.get_text())
            if cuisine:
                return f"Кухня: {cuisine}"
        
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        # Или в специальных блоках тегов
        tags_elem = self.soup.find(class_=re.compile(r'tag', re.I))
        if tags_elem:
            tags_text = self.clean_text(tags_elem.get_text())
            if tags_text:
                return tags_text
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Из Recipe JSON-LD
        recipe_data = self._get_recipe_json_ld()
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
        
        # 2. Из meta og:image
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
    # Обрабатываем папку preprocessed/fayni-recepty_com_ua
    preprocessed_dir = os.path.join("preprocessed", "fayni-recepty_com_ua")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(FayniReceptyExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python fayni-recepty_com_ua.py")


if __name__ == "__main__":
    main()
