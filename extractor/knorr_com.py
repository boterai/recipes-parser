"""
Экстрактор данных рецептов для сайта knorr.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KnorrComExtractor(BaseRecipeExtractor):
    """Экстрактор для knorr.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Пробуем извлечь из JSON-LD
        json_ld_data = self._get_json_ld_recipe()
        if json_ld_data and 'name' in json_ld_data:
            return self.clean_text(json_ld_data['name'])
        
        # Альтернативно - из мета-тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Еще один вариант - из H1 заголовка
        h1_title = self.soup.find('h1')
        if h1_title:
            return self.clean_text(h1_title.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Пробуем извлечь из JSON-LD
        json_ld_data = self._get_json_ld_recipe()
        if json_ld_data and 'description' in json_ld_data:
            return self.clean_text(json_ld_data['description'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Пробуем извлечь из JSON-LD
        json_ld_data = self._get_json_ld_recipe()
        if json_ld_data and 'recipeIngredient' in json_ld_data:
            # В JSON-LD knorr.com ингредиенты в виде списка строк
            # Нужно распарсить каждую строку
            for ingredient_text in json_ld_data['recipeIngredient']:
                parsed = self.parse_ingredient_knorr(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient_knorr(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат для knorr.com
        Пример: "1 paket Knorr domatesli makarna sosu"
        
        Args:
            ingredient_text: Строка ингредиента
            
        Returns:
            dict: {"name": "...", "amount": "...", "unit": "..."}
        """
        if not ingredient_text:
            return None
        
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1 paket ...", "250 gram ...", "1 çorba kaşığı ..."
        pattern = r'^([\d\s/.,]+)?\s*(paket|gram|ml|su|diş|çay\s+bardağı|çorba\s+kaşığı|yemek\s+kaşığı|adet|şт|kg|litre|l)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Преобразуем в число
            try:
                # Обработка дробей
                if '/' in amount_str:
                    parts = amount_str.split()
                    total = 0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            total += float(part)
                    amount = int(total) if total == int(total) else total
                else:
                    amount = int(float(amount_str.replace(',', '.')))
            except:
                amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        name = name.strip()
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Пробуем извлечь из JSON-LD
        json_ld_data = self._get_json_ld_recipe()
        if json_ld_data and 'recipeInstructions' in json_ld_data:
            instructions = json_ld_data['recipeInstructions']
            
            # Обработка HowToSection
            if isinstance(instructions, list):
                for instruction_item in instructions:
                    if isinstance(instruction_item, dict):
                        # HowToSection со списком шагов
                        if '@type' in instruction_item and instruction_item['@type'] == 'HowToSection':
                            if 'itemListElement' in instruction_item:
                                for step in instruction_item['itemListElement']:
                                    if isinstance(step, dict) and 'text' in step:
                                        steps.append(step['text'])
                        # Прямой HowToStep
                        elif 'text' in instruction_item:
                            steps.append(instruction_item['text'])
                    elif isinstance(instruction_item, str):
                        steps.append(instruction_item)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Пробуем извлечь из JSON-LD
        json_ld_data = self._get_json_ld_recipe()
        if json_ld_data and 'recipeCategory' in json_ld_data:
            return self.clean_text(json_ld_data['recipeCategory'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld_data = self._get_json_ld_recipe()
        if json_ld_data and 'prepTime' in json_ld_data:
            iso_time = json_ld_data['prepTime']
            return self._parse_iso_duration_to_minutes(iso_time)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld_data = self._get_json_ld_recipe()
        if json_ld_data and 'cookTime' in json_ld_data:
            iso_time = json_ld_data['cookTime']
            return self._parse_iso_duration_to_minutes(iso_time)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld_data = self._get_json_ld_recipe()
        if json_ld_data and 'totalTime' in json_ld_data:
            iso_time = json_ld_data['totalTime']
            return self._parse_iso_duration_to_minutes(iso_time)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # На knorr.com обычно нет отдельных заметок
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Пробуем извлечь из JSON-LD keywords
        json_ld_data = self._get_json_ld_recipe()
        if json_ld_data and 'keywords' in json_ld_data:
            keywords = json_ld_data['keywords']
            # keywords может быть строкой с разделителями
            if isinstance(keywords, str):
                # Преобразуем в формат с запятыми
                tags = [tag.strip().lower() for tag in keywords.split(',') if tag.strip()]
                return ', '.join(tags) if tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Пробуем извлечь из JSON-LD
        json_ld_data = self._get_json_ld_recipe()
        if json_ld_data and 'image' in json_ld_data:
            img = json_ld_data['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
        
        # Дополнительно - из og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)
        
        # Возвращаем строку с URL через запятую
        return ','.join(urls) if urls else None
    
    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Получение JSON-LD данных рецепта"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем тип Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return None
    
    def _parse_iso_duration_to_minutes(self, duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты с текстом
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "20 dakika" или "1 saat 30 dakika"
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
        if hours and minutes:
            return f"{hours} saat {minutes} dakika"
        elif hours:
            return f"{hours} saat"
        elif minutes:
            return f"{minutes} dakika"
        
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
    """Точка входа для обработки директории с HTML-страницами knorr.com"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "knorr_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(KnorrComExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python knorr_com.py")


if __name__ == "__main__":
    main()
