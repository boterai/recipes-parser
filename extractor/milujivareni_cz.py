"""
Экстрактор данных рецептов для сайта milujivareni.cz
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MilujivareniCzExtractor(BaseRecipeExtractor):
    """Экстрактор для milujivareni.cz"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем, является ли это Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
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
            Время в минутах с единицей, например "90 min."
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
        
        return f"{total_minutes} min." if total_minutes > 0 else None
    
    @staticmethod
    def parse_ingredient(ingredient_text: str) -> Optional[Dict[str, Any]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1000 gramů Krůtí prsa" или "1 špetka Sůl"
            
        Returns:
            dict: {"name": "Krůtí prsa", "amount": 1000, "units": "gramů"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = ingredient_text.strip()
        
        # Известные единицы измерения
        # Паттерн: [количество] [единица (одно слово)] [название (остальное)]
        # Примеры: "1000 gramů Krůtí prsa", "50 mililitrů Citronová šťáva"
        pattern = r'^([\d.,]+)\s+(\S+)\s+(.+)$'
        
        match = re.match(pattern, text)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, units, name = match.groups()
        
        # Обработка количества - конвертируем в число
        try:
            # Заменяем запятую на точку для чисел с дробной частью
            amount_str = amount_str.replace(',', '.')
            # Пробуем преобразовать в int, если не получается - в float
            if '.' in amount_str:
                amount = float(amount_str)
            else:
                amount = int(amount_str)
        except ValueError:
            amount = None
        
        # Очистка названия
        name = name.strip()
        
        return {
            "name": name,
            "amount": amount,
            "units": units.strip()
        }
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_data()
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Fallback к meta тегам
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " | MilujiVaření.cz"
            title = re.sub(r'\s*\|.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        json_ld = self._get_json_ld_data()
        if json_ld and 'description' in json_ld:
            desc = json_ld['description']
            if desc and desc.strip():
                return self.clean_text(desc)
        
        # Fallback к meta тегам
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        json_ld = self._get_json_ld_data()
        if not json_ld or 'recipeIngredient' not in json_ld:
            return None
        
        ingredients_raw = json_ld['recipeIngredient']
        if not isinstance(ingredients_raw, list):
            return None
        
        ingredients = []
        for ingredient_text in ingredients_raw:
            parsed = self.parse_ingredient(ingredient_text)
            if parsed:
                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        if not json_ld or 'recipeInstructions' not in json_ld:
            return None
        
        instructions = json_ld['recipeInstructions']
        
        if isinstance(instructions, str):
            return self.clean_text(instructions)
        elif isinstance(instructions, list):
            steps = []
            for idx, step in enumerate(instructions, 1):
                if isinstance(step, dict) and 'text' in step:
                    step_text = step['text']
                elif isinstance(step, str):
                    step_text = step
                else:
                    continue
                
                # Очищаем текст от \r и лишних пробелов
                step_text = self.clean_text(step_text)
                if step_text:
                    # Добавляем нумерацию если её нет
                    if not re.match(r'^\d+\.', step_text):
                        steps.append(f"{idx}. {step_text}")
                    else:
                        steps.append(step_text)
            
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        json_ld = self._get_json_ld_data()
        if json_ld and 'recipeCategory' in json_ld:
            category = json_ld['recipeCategory']
            if category:
                return self.clean_text(category)
        
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
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Для milujivareni.cz нет специального поля notes в JSON-LD
        # Можно попробовать извлечь из description или других полей
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        json_ld = self._get_json_ld_data()
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if keywords and keywords.strip():
                # Если keywords - это строка с разделителями
                if isinstance(keywords, str):
                    # Разделяем по запятым и очищаем
                    tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                    return ', '.join(tags) if tags else None
                elif isinstance(keywords, list):
                    return ', '.join([str(k).strip() for k in keywords if k])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        json_ld = self._get_json_ld_data()
        if json_ld and 'image' in json_ld:
            img_data = json_ld['image']
            if isinstance(img_data, str):
                urls.append(img_data)
            elif isinstance(img_data, list):
                urls.extend([img for img in img_data if isinstance(img, str)])
            elif isinstance(img_data, dict):
                if 'url' in img_data:
                    urls.append(img_data['url'])
                elif 'contentUrl' in img_data:
                    urls.append(img_data['contentUrl'])
        
        # Также проверяем meta теги
        if not urls:
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
    """Обработка всех HTML файлов из директории preprocessed/milujivareni_cz"""
    import os
    
    # Путь к директории с HTML-файлами примеров
    preprocessed_dir = os.path.join("preprocessed", "milujivareni_cz")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обрабатываем директорию: {preprocessed_dir}")
        process_directory(MilujivareniCzExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print(f"Текущая директория: {os.getcwd()}")


if __name__ == "__main__":
    main()
