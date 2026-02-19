"""
Экстрактор данных рецептов для сайта nogetiovnen.dk
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class NogetiovnenExtractor(BaseRecipeExtractor):
    """Экстрактор для nogetiovnen.dk"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT450M"
            
        Returns:
            Время в формате "20 minutes", "1 hour 30 minutes" и т.д.
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
        
        # Если минут больше 60 и нет часов, конвертируем в часы и минуты
        if minutes >= 60 and hours == 0:
            hours = minutes // 60
            minutes = minutes % 60
        
        # Форматируем в читаемый вид
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour" + ("s" if hours > 1 else ""))
        if minutes > 0:
            parts.append(f"{minutes} minute" + ("s" if minutes > 1 else ""))
        
        return " ".join(parts) if parts else None
    
    def get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение данных Recipe из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем, является ли это Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            name = recipe_data['name']
            # Убираем суффиксы типа " - opskrift", " opskrift"
            name = re.sub(r'\s*-?\s*opskrift\s*$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s*-?\s*(opskrift|•|nogetiovnen\.dk).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Убираем "Få opskriften her" и подобные фразы
            desc = re.sub(r'\s*(Få opskriften her|opskrift).*$', '', desc, flags=re.IGNORECASE)
            return self.clean_text(desc)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1.2-1,5 kg oksesteg" или "320 gram perleløg"
            
        Returns:
            dict: {"name": "oksesteg", "amount": "1.2-1.5", "units": "kg"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Обработка дробей: "2½" должно стать "2.5", а "½" должно стать "0.5"
        # Сначала обрабатываем случаи "число + дробь"
        for fraction, decimal in [('½', '0.5'), ('¼', '0.25'), ('¾', '0.75'), ('⅓', '0.33'), ('⅔', '0.67')]:
            # Ищем "цифра + дробь"
            text = re.sub(r'(\d+)' + re.escape(fraction), lambda m: str(float(m.group(1)) + float(decimal)), text)
        
        # Теперь заменяем оставшиеся одиночные дроби
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Заменяем запятую на точку в числах
        text = re.sub(r'(\d),(\d)', r'\1.\2', text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1.2-1.5 kg oksesteg", "320 gram perleløg", "2.5 dl fløde"
        # Датские единицы: kg, gram, liter, dl, spsk (столовая ложка), tsk (чайная ложка)
        pattern = r'^([\d\s/.,\-]+)?\s*(kg|kilogram|gram|g|liter|ltr|l|dl|deciliter|ml|milliliter|spsk|spiseskefuld|spiseskefulde|tsk|teskefuld|teskefulde|stk|styk|styks|stykker|dåse|dåser|pose|poser)?\s*(.+)'
        
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
            amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "til stegning", "efter smag", но НЕ удаляем "eller bouillon"
        # Ищем "til X" в конце, но сохраняем "eller X" как часть названия
        name = re.sub(r'\s+(til\s+\w+|efter\s+smag|evt\.?|ca\.?|gerne)\s*$', '', name, flags=re.IGNORECASE)
        # Удаляем лишние знаки в конце
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit  # Note: используем "units" как в примере
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredient_list = recipe_data['recipeIngredient']
            
            for ingredient_text in ingredient_list:
                # Проверяем, есть ли "/" в тексте (например, "salt/peber")
                # Если это простой текст без чисел, разделяем на отдельные ингредиенты
                if '/' in ingredient_text and not any(c.isdigit() for c in ingredient_text.split('/')[0]):
                    # Разделяем по /
                    parts = ingredient_text.split('/')
                    for part in parts:
                        parsed = self.parse_ingredient(part.strip())
                        if parsed:
                            ingredients.append(parsed)
                else:
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
            
            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Извлекаем из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict):
                        # HowToStep или HowToSection
                        if step.get('@type') == 'HowToStep' and 'text' in step:
                            steps.append(step['text'])
                        elif step.get('@type') == 'HowToSection' and 'itemListElement' in step:
                            # Для секций извлекаем все подшаги
                            for substep in step['itemListElement']:
                                if isinstance(substep, dict) and 'text' in substep:
                                    steps.append(substep['text'])
                    elif isinstance(step, str):
                        steps.append(step)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data:
            # Пробуем recipeCuisine (это более подходящее поле для категории)
            if 'recipeCuisine' in recipe_data:
                cuisine = recipe_data['recipeCuisine']
                if isinstance(cuisine, list) and len(cuisine) > 0:
                    return self.clean_text(cuisine[0])
                elif isinstance(cuisine, str):
                    return self.clean_text(cuisine)
            
            # Альтернативно - recipeCategory
            if 'recipeCategory' in recipe_data:
                category = recipe_data['recipeCategory']
                if isinstance(category, list) and len(category) > 0:
                    # Пропускаем, если это просто название рецепта
                    cat_text = category[0]
                    if 'opskrift' not in cat_text.lower():
                        return self.clean_text(cat_text)
                elif isinstance(category, str) and 'opskrift' not in category.lower():
                    return self.clean_text(category)
        
        # Из breadcrumbs в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BreadcrumbList' and 'itemListElement' in item:
                            items = item['itemListElement']
                            # Берем предпоследний элемент (перед самим рецептом)
                            if len(items) >= 2:
                                category_item = items[-2]
                                if 'name' in category_item:
                                    return self.clean_text(category_item['name'])
            except:
                continue
        
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
        # Ищем div с классом wprm-recipe-notes-container
        notes_div = self.soup.find('div', class_='wprm-recipe-notes-container')
        if notes_div:
            # Убираем заголовок "Noter" если есть
            header = notes_div.find(class_=re.compile(r'notes.*header', re.I))
            if header:
                header.decompose()
            
            # Извлекаем текст
            text = notes_div.get_text(separator=' ', strip=True)
            # Убираем оставшиеся заголовки типа "Notes:", "Noter:"
            text = re.sub(r'^(Notes?|Noter):?\s*', '', text, flags=re.I)
            text = self.clean_text(text)
            return text if text else None
        
        # Альтернативный поиск
        notes_section = self.soup.find(class_=re.compile(r'recipe.*notes(?!.*ingredient)', re.I))
        if notes_section and 'ingredient' not in ' '.join(notes_section.get('class', [])).lower():
            text = notes_section.get_text(separator=' ', strip=True)
            text = re.sub(r'^(Notes?|Noter):?\s*', '', text, flags=re.I)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                return keywords
            elif isinstance(keywords, list):
                return ', '.join(keywords)
        
        # Из meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return meta_keywords['content']
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Из JSON-LD (наиболее надежный источник)
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'image' in recipe_data:
            images = recipe_data['image']
            if isinstance(images, list):
                urls.extend(images)
            elif isinstance(images, str):
                urls.append(images)
        
        # Из meta тегов (дополнительно)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)
        
        # Возвращаем через запятую без пробелов (как в требованиях)
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
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """
    Точка входа для обработки директории с HTML файлами
    """
    import os
    
    # Путь к директории с предобработанными HTML файлами
    preprocessed_dir = os.path.join("preprocessed", "nogetiovnen_dk")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(NogetiovnenExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python extractor/nogetiovnen_dk.py")


if __name__ == "__main__":
    main()
