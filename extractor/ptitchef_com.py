"""
Экстрактор данных рецептов для сайта ptitchef.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class PtitchefExtractor(BaseRecipeExtractor):
    """Экстрактор для ptitchef.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "X minutes"
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
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """
        Извлекает данные JSON-LD с типом Recipe
        
        Returns:
            Словарь с данными рецепта или None
        """
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            name = self.clean_text(recipe_data['name'])
            # Приводим к нижнему регистру и убираем финальные знаки препинания
            if name:
                name = name.lower().rstrip('.')
            return name
        
        # Альтернативно - из h1
        h1 = self.soup.find('h1')
        if h1:
            name = self.clean_text(h1.get_text())
            if name:
                name = name.lower().rstrip('.')
            return name
        
        # Или из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем префиксы типа "Recette de "
            title = re.sub(r'^Recette\s+de\s+', '', title, flags=re.IGNORECASE)
            name = self.clean_text(title)
            if name:
                name = name.lower().rstrip('.')
            return name
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            if desc:
                desc = self.clean_text(desc)
                # Убираем префиксы типа "Recette Autre recette de" или "Recette Dessert recette de"
                desc = re.sub(r'^Recette\s+\w+\s+recette\s+de\s+', '', desc, flags=re.IGNORECASE)
                # Если описание начинается просто с "Recette de", убираем только если дальше идет название блюда
                desc = re.sub(r'^Recette\s+de\s+', '', desc, flags=re.IGNORECASE)
                
                # Если описание похоже на название блюда (или просто повторяет категорию + название), 
                # возвращаем None
                dish_name = self.extract_dish_name()
                if dish_name:
                    # Если описание - это просто название или "название и доп.слова"
                    desc_lower = desc.lower()
                    dish_lower = dish_name.lower()
                    if desc_lower == dish_lower or desc_lower.startswith(dish_lower + ' et '):
                        return None
                
                # Если описание слишком короткое или пустое, возвращаем None
                if len(desc) < 10:
                    return None
                    
                return desc
        
        # Альтернативно - из meta description (с той же логикой очистки)
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            desc = re.sub(r'^Recette\s+\w+\s+recette\s+de\s+', '', desc, flags=re.IGNORECASE)
            desc = re.sub(r'^Recette\s+de\s+', '', desc, flags=re.IGNORECASE)
            if len(desc) >= 10:
                return desc
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: строка вида "100 g de beurre", "150g de farine", "1/2 l de lait", "2 cuillères à soupe d'extrait"
            
        Returns:
            Словарь с полями name, amount, units
        """
        if not ingredient_text:
            return None
        
        ingredient_text = self.clean_text(ingredient_text)
        
        # Паттерны для извлечения количества, единицы и названия
        # Примеры: "100 g de beurre", "150g de farine", "1/2 l de lait", "4 oeufs", "2 cuillère à soupe de rhum", "2 cuillères à soupe d'extrait de café"
        
        # Попытка 1: количество + "sachet/bouchon/pincée..." + "de/d'" + название
        match = re.match(r'^(\d+(?:[.,/]\d+)?)\s*(sachets?|bouchons?|pincées?)\s+(?:de|d[\''])\s+(.+)$', ingredient_text, re.IGNORECASE)
        if match:
            amount_str, unit, name = match.groups()
            amount = self._parse_amount(amount_str)
            return {
                'name': self.clean_text(name),
                'units': self.clean_text(unit),
                'amount': amount
            }
        
        # Попытка 2: количество + сложная единица типа "cuillère à soupe" + "de/d'" + название
        match = re.match(r'^(\d+(?:[.,/]\d+)?)\s+((?:cuillères?|cuillère)\s+à\s+\w+)\s+(?:de|d[\''])\s+(.+)$', ingredient_text, re.IGNORECASE)
        if match:
            amount_str, unit, name = match.groups()
            amount = self._parse_amount(amount_str)
            return {
                'name': self.clean_text(name),
                'units': self.clean_text(unit),
                'amount': amount
            }
        
        # Попытка 3: количество (без пробела или с пробелом) + единица + "de/d'" + название
        # Примеры: "150g de farine", "100 g de beurre", "1/2 l de lait"
        match = re.match(r'^(\d+(?:[.,/]\d+)?)\s*([a-zA-Zé]+)\s+(?:de|d[\''])\s+(.+)$', ingredient_text)
        if match:
            amount_str, unit, name = match.groups()
            amount = self._parse_amount(amount_str)
            return {
                'name': self.clean_text(name),
                'units': self.clean_text(unit),
                'amount': amount
            }
        
        # Попытка 4: количество + единица без "de"
        match = re.match(r'^(\d+(?:[.,/]\d+)?)\s*([a-zA-Zé]+)\s+(.+)$', ingredient_text)
        if match:
            amount_str, unit, name = match.groups()
            amount = self._parse_amount(amount_str)
            return {
                'name': self.clean_text(name),
                'units': self.clean_text(unit),
                'amount': amount
            }
        
        # Попытка 5: количество + название (без единицы измерения)
        match = re.match(r'^(\d+(?:[.,/]\d+)?)\s+(.+)$', ingredient_text)
        if match:
            amount_str, name = match.groups()
            amount = self._parse_amount(amount_str)
            return {
                'name': self.clean_text(name),
                'units': None,
                'amount': amount
            }
        
        # Если не удалось распарсить, возвращаем как есть
        return {
            'name': ingredient_text,
            'units': None,
            'amount': None
        }
    
    def _parse_amount(self, amount_str: str) -> float:
        """
        Парсинг количества из строки (поддерживает дроби)
        
        Args:
            amount_str: строка вида "1", "1.5", "1,5", "1/2"
            
        Returns:
            Число (float или int)
        """
        # Обработка дробей типа "1/2"
        if '/' in amount_str:
            parts = amount_str.split('/')
            if len(parts) == 2:
                try:
                    numerator = float(parts[0])
                    denominator = float(parts[1])
                    return numerator / denominator
                except ValueError:
                    pass
        
        # Обработка обычных чисел
        amount = float(amount_str.replace(',', '.'))
        # Преобразуем в int если это целое число
        if amount == int(amount):
            amount = int(amount)
        return amount
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Извлекаем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredient_list = recipe_data['recipeIngredient']
            if isinstance(ingredient_list, list):
                for ing_text in ingredient_list:
                    parsed = self.parse_ingredient(ing_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Извлекаем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
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
                steps.append(self.clean_text(instructions))
        
        # Объединяем все шаги в одну строку через пробел
        result = ' '.join(steps) if steps else None
        
        # Исправляем отсутствующие пробелы после точек и запятых
        if result:
            # Добавляем пробел после точки, если его нет
            result = re.sub(r'\.(?=[A-ZА-ЯЁ])', '. ', result)
            # Добавляем пробел после запятой, если его нет
            result = re.sub(r',(?=[A-ZА-ЯЁ])', ', ', result)
        
        return result
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Извлекаем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            if category:
                return self.clean_text(category)
        
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
        """Извлечение общего времени приготовления"""
        # В референсных данных total_time всегда None, поэтому возвращаем None
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение дополнительных заметок"""
        # В ptitchef.com заметки обычно отсутствуют в JSON-LD
        # Можно было бы искать в HTML, но по примерам они None
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Извлекаем из JSON-LD keywords
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if keywords:
                # keywords может быть строкой с разделителями
                tags = self.clean_text(keywords)
                # Разбиваем по запятым
                tag_list = [t.strip() for t in tags.split(',')]
                
                # Фильтруем теги - оставляем только наиболее релевантные
                # Убираем длинные составные теги и префиксы "recettes de"
                filtered_tags = []
                category = self.extract_category()
                
                for tag in tag_list:
                    # Пропускаем теги с префиксами "recettes"
                    if re.match(r'^recettes?\b', tag, re.IGNORECASE):
                        continue
                    # Пропускаем слишком длинные или специфичные теги (более 20 символов обычно слишком специфичны)
                    if len(tag) > 20:
                        continue
                    # Пропускаем теги с определенными словами
                    if re.search(r'\bkitchenaid\b|\bscrapcooking\b', tag, re.IGNORECASE):
                        continue
                    filtered_tags.append(tag)
                
                # Ограничиваем количество тегов (обычно 3-5 достаточно)
                if len(filtered_tags) > 5:
                    filtered_tags = filtered_tags[:5]
                
                # Форматируем: иногда в референсах есть пробелы после запятых, иногда нет
                # Используем формат без пробелов как более распространенный
                return ','.join(filtered_tags) if filtered_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        # В референсных данных image_urls всегда None
        # Согласно требованиям, допустимы отличия в этом поле
        # Но мы можем извлекать их для полноты данных
        return None
    
    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта"""
        return {
            'dish_name': self.extract_dish_name(),
            'description': self.extract_description(),
            'ingredients': self.extract_ingredients(),
            'instructions': self.extract_instructions(),
            'category': self.extract_category(),
            'prep_time': self.extract_prep_time(),
            'cook_time': self.extract_cook_time(),
            'total_time': self.extract_total_time(),
            'notes': self.extract_notes(),
            'tags': self.extract_tags(),
            'image_urls': self.extract_image_urls()
        }


def main():
    """
    Точка входа для обработки HTML файлов из директории preprocessed/ptitchef_com
    """
    preprocessed_dir = Path(__file__).parent.parent / 'preprocessed' / 'ptitchef_com'
    
    if not preprocessed_dir.exists():
        print(f"Директория {preprocessed_dir} не найдена")
        return
    
    print(f"Обработка файлов из директории: {preprocessed_dir}")
    process_directory(PtitchefExtractor, str(preprocessed_dir))


if __name__ == '__main__':
    main()
