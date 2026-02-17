"""
Экстрактор данных рецептов для сайта akispetretzikis.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class AkisPetretzikisExtractor(BaseRecipeExtractor):
    """Экстрактор для akispetretzikis.com"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение JSON-LD данных из HTML"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем, что это Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "20 minutes", "90 minutes" и т.д.
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
            return f"{total_minutes} minutes"
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Dict[str, any]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "200 γρ. πουτίγκα πρωτεΐνης" или "2 αυγά"
            
        Returns:
            dict: {"name": "πουτίγκα πρωτεΐνης", "amount": 200, "units": "γρ."} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).strip()
        
        if not text:
            return None
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "200 γρ. πουτίγκα πρωτεΐνης", "2 αυγά", "1 πρέζα αλάτι"
        # Формат: [количество] [единица] [название]
        pattern = r'^([\d,]+(?:\.\d+)?)\s*(γρ\.|κ\.σ\.|κ\.γ\.|τμχ\.|τεμ\.|πρέζα|ml|λτ\.|kg|φλ\.)?\s*(.+?)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                # Заменяем запятую на точку для чисел
                amount_str = amount_str.replace(',', '.')
                try:
                    # Пытаемся преобразовать в число
                    amount_float = float(amount_str)
                    # Если это целое число, возвращаем int
                    if amount_float.is_integer():
                        amount = int(amount_float)
                    else:
                        amount = amount_float
                except ValueError:
                    amount = amount_str
            
            # Обработка единицы измерения
            unit = unit.strip() if unit else None
            
            # Очистка названия
            name = name.strip() if name else text
            
            return {
                "name": name,
                "units": unit,
                "amount": amount
            }
        
        # Если паттерн не совпал, возвращаем только название
        return {
            "name": text,
            "units": None,
            "amount": None
        }
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Или из тега title
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем суффиксы типа " - Akis Petretzikis"
            title = re.sub(r'\s*[-|]\s*Akis.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'description' in json_ld:
            desc = json_ld['description']
            if desc:
                return self.clean_text(desc)
        
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
        """Извлечение ингредиентов"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeIngredient' in json_ld:
            ingredients_list = json_ld['recipeIngredient']
            
            if isinstance(ingredients_list, list):
                parsed_ingredients = []
                
                for ingredient_text in ingredients_list:
                    if isinstance(ingredient_text, str):
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            parsed_ingredients.append(parsed)
                
                if parsed_ingredients:
                    return json.dumps(parsed_ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            
            if isinstance(instructions, list):
                steps = []
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        steps.append(step['text'])
                    elif isinstance(step, str):
                        steps.append(step)
                
                if steps:
                    # Объединяем все шаги в одну строку
                    full_text = ' '.join(steps)
                    return self.clean_text(full_text)
            elif isinstance(instructions, str):
                return self.clean_text(instructions)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Для akispetretzikis.com категория не извлекается из JSON-LD
        # recipeCategory содержит только числовой ID, а recipeCuisine ("Greek") не подходит
        # Возвращаем None для соответствия эталонным данным
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        
        # Сначала пробуем извлечь из JSON-LD
        if json_ld and 'totalTime' in json_ld:
            total = self.parse_iso_duration(json_ld['totalTime'])
            if total:
                return total
        
        # Если totalTime нет, вычисляем из prep + cook
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep and cook:
            # Извлекаем числа из строк вида "20 minutes"
            prep_match = re.search(r'(\d+)', prep)
            cook_match = re.search(r'(\d+)', cook)
            
            if prep_match and cook_match:
                total_minutes = int(prep_match.group(1)) + int(cook_match.group(1))
                return f"{total_minutes} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Для akispetretzikis.com заметок обычно нет в JSON-LD
        # Можно добавить логику парсинга HTML, если будет нужно
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Для akispetretzikis.com теги в JSON-LD keywords содержат только слова из названия
        # Это не семантические теги, поэтому не извлекаем их
        # В эталонных JSON теги либо None, либо вручную проставлены
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'image' in json_ld:
            image_data = json_ld['image']
            
            if isinstance(image_data, str):
                urls.append(image_data)
            elif isinstance(image_data, list):
                for img in image_data:
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, dict):
                        if 'url' in img:
                            urls.append(img['url'])
                        elif 'contentUrl' in img:
                            urls.append(img['contentUrl'])
            elif isinstance(image_data, dict):
                if 'url' in image_data:
                    urls.append(image_data['url'])
                elif 'contentUrl' in image_data:
                    urls.append(image_data['contentUrl'])
        
        # Также пробуем из meta-тегов
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
    """Обработка всех HTML файлов из директории preprocessed/akispetretzikis_com"""
    import os
    
    # Путь к директории с preprocessed файлами
    preprocessed_dir = os.path.join(
        Path(__file__).parent.parent,
        "preprocessed",
        "akispetretzikis_com"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(AkisPetretzikisExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python akispetretzikis_com.py")


if __name__ == "__main__":
    main()
