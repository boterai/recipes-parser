"""
Экстрактор данных рецептов для сайта recepti.index.hr
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ReceptiIndexHrExtractor(BaseRecipeExtractor):
    """Экстрактор для recepti.index.hr"""
    
    def _get_recipe_json_ld(self) -> Optional[Dict]:
        """
        Извлечение данных рецепта из JSON-LD
        
        Returns:
            Словарь с данными рецепта из JSON-LD или None
        """
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
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
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "P0DT15M" или "P0DT1H30M"
            
        Returns:
            Время в формате "15 minutes", "1 hour", "1 hour 10 minutes" или None
        """
        if not duration:
            return None
        
        # Извлекаем минуты и часы
        hours = 0
        minutes = 0
        
        # Формат: P0DT15M или P0DT1H30M
        hour_match = re.search(r'(\d+)H', duration)
        if hour_match:
            hours = int(hour_match.group(1))
        
        min_match = re.search(r'(\d+)M', duration)
        if min_match:
            minutes = int(min_match.group(1))
        
        # Форматируем время
        parts = []
        if hours > 0:
            if hours == 1:
                parts.append("1 hour")
            else:
                parts.append(f"{hours} hours")
        
        if minutes > 0:
            parts.append(f"{minutes} minutes")
        
        if parts:
            return " ".join(parts)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "500 g brašna" или "1 vrećica suhog kvasca"
            
        Returns:
            dict: {"name": "brašna", "amount": 500, "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).strip()
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "500 g brašna", "1 vrećica suhog kvasca", "200 ml mlijeka"
        # Поддерживаем разные варианты единиц измерения
        pattern = r'^(\d+(?:[.,]\d+)?)\s+(g|ml|kg|l|vrećica|žličica|prstohvat|kom|komad|komada|paket|čaša|žlica|šalica|kašika|kašičica)\s+(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount_str = amount_str.replace(',', '.')
            try:
                # Пытаемся преобразовать в число
                amount_float = float(amount_str)
                # Если это целое число, преобразуем в int
                if amount_float.is_integer():
                    amount = int(amount_float)
                else:
                    amount = amount_float
            except ValueError:
                amount = amount_str
            
            # Очистка названия
            name = name.strip()
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        
        # Если паттерн не совпал, пробуем без единиц измерения
        # Формат: "1 jaje" или "2 jabuke"
        pattern_simple = r'^(\d+(?:[.,]\d+)?)\s+(.+)$'
        match_simple = re.match(pattern_simple, text, re.IGNORECASE)
        
        if match_simple:
            amount_str, name = match_simple.groups()
            
            # Обработка количества
            amount_str = amount_str.replace(',', '.')
            try:
                amount_float = float(amount_str)
                if amount_float.is_integer():
                    amount = int(amount_float)
                else:
                    amount = amount_float
            except ValueError:
                amount = amount_str
            
            return {
                "name": name.strip(),
                "amount": amount,
                "units": None
            }
        
        # Если не удалось распарсить, возвращаем весь текст как название
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredients = []
        for ingredient_text in recipe_data['recipeIngredient']:
            parsed = self.parse_ingredient(ingredient_text)
            if parsed:
                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        steps = []
        
        if isinstance(instructions, list):
            for idx, step in enumerate(instructions, 1):
                if isinstance(step, dict):
                    # Извлекаем название шага и текст
                    step_name = step.get('name', '').strip()
                    step_text = step.get('text', '')
                    
                    if step_name and step_text:
                        # Формат: "1. Название шага. Текст шага"
                        steps.append(f"{idx}. {step_name}. {step_text}")
                    elif step_text:
                        steps.append(f"{idx}. {step_text}")
                    elif step_name:
                        steps.append(f"{idx}. {step_name}")
                elif isinstance(step, str):
                    steps.append(f"{idx}. {step}")
        
        return ' '.join(steps) if steps else None
    
    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок из последнего шага инструкции
        
        Заметки обычно находятся в конце последнего шага инструкции
        и начинаются после точки
        """
        recipe_data = self._get_recipe_json_ld()
        
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        
        if not isinstance(instructions, list) or len(instructions) == 0:
            return None
        
        # Берем последний шаг
        last_step = instructions[-1]
        
        if isinstance(last_step, dict):
            step_text = last_step.get('text', '')
            
            if step_text:
                # Ищем последнее предложение после точки
                # Обычно заметки начинаются с новой мысли после основной инструкции
                sentences = step_text.split('. ')
                
                # Если есть несколько предложений, последнее может быть заметкой
                if len(sentences) >= 2:
                    # Проверяем, является ли последнее предложение заметкой
                    # Обычно заметки содержат советы: "Pojedite što prije", "Savjet:", "Napomena:" и т.д.
                    last_sentence = sentences[-1].strip()
                    
                    # Удаляем точку в конце если есть
                    last_sentence = last_sentence.rstrip('.')
                    
                    # Проверяем, что это не пустая строка и не часть основной инструкции
                    if last_sentence and len(last_sentence) > 20:
                        # Проверяем ключевые слова для заметок
                        note_keywords = ['pojedite', 'savjet', 'napomena', 'možete', 'preporučuje se']
                        if any(keyword in last_sentence.lower() for keyword in note_keywords):
                            return last_sentence
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if not recipe_data or 'recipeCategory' not in recipe_data:
            return None
        
        categories = recipe_data['recipeCategory']
        
        # recipeCategory может быть списком или строкой
        if isinstance(categories, list):
            return ', '.join(categories) if categories else None
        elif isinstance(categories, str):
            return categories
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if not recipe_data:
            return None
        
        # Теги могут быть в поле keywords
        if 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Разделяем по запятой и очищаем
                tags = [self.clean_text(tag) for tag in keywords.split(',')]
                tags = [tag for tag in tags if tag]
                return ', '.join(tags) if tags else None
            elif isinstance(keywords, list):
                tags = [self.clean_text(tag) for tag in keywords]
                tags = [tag for tag in tags if tag]
                return ', '.join(tags) if tags else None
        
        # Альтернативно можно попробовать recipeCategory
        if 'recipeCategory' in recipe_data:
            categories = recipe_data['recipeCategory']
            if isinstance(categories, list):
                tags = [self.clean_text(cat).lower() for cat in categories]
                return ', '.join(tags) if tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if not recipe_data or 'image' not in recipe_data:
            return None
        
        image = recipe_data['image']
        urls = []
        
        if isinstance(image, str):
            urls.append(image)
        elif isinstance(image, list):
            for img in image:
                if isinstance(img, str):
                    urls.append(img)
                elif isinstance(img, dict):
                    if 'url' in img:
                        urls.append(img['url'])
                    elif 'contentUrl' in img:
                        urls.append(img['contentUrl'])
        elif isinstance(image, dict):
            if 'url' in image:
                urls.append(image['url'])
            elif 'contentUrl' in image:
                urls.append(image['contentUrl'])
        
        # Возвращаем как строку через запятую без пробелов
        return ','.join(urls) if urls else None
    
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """
    Точка входа для обработки директории с HTML-страницами recepti.index.hr
    """
    import os
    
    # Путь к директории с предобработанными HTML-файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "preprocessed",
        "recepti_index_hr"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(ReceptiIndexHrExtractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python recepti_index_hr.py")


if __name__ == "__main__":
    main()
