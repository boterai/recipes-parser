"""
Экстрактор данных рецептов для сайта lezzet.com.tr
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class LezzetComTrExtractor(BaseRecipeExtractor):
    """Экстрактор для lezzet.com.tr"""
    
    def extract_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение JSON-LD Recipe данных"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                # Проверяем на наличие Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        recipe_data = self.extract_json_ld_recipe()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из мета-тегов
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы "| Lezzet"
            title = re.sub(r'\s*\|\s*Lezzet.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'Lezzetli Tarifler:\s*', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        recipe_data = self.extract_json_ld_recipe()
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            # Очищаем описание от технических деталей о времени
            desc = re.sub(r'\d+Dk\s+Hazırlama.*?Tarifimizde Görün\.', '', desc, flags=re.IGNORECASE)
            desc = self.clean_text(desc)
            if desc:
                return desc
        
        # Альтернативно - из мета description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            desc = re.sub(r'\d+Dk\s+Hazırlama.*?Tarifimizde Görün\.', '', desc, flags=re.IGNORECASE)
            desc = self.clean_text(desc)
            if desc:
                return desc
        
        return None
    
    def parse_ingredient_text(self, ingredient_text: str) -> dict:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "2 kabak" или "500 ml süt"
            
        Returns:
            dict: {"name": "kabak", "amount": "2", "unit": None}
        """
        if not ingredient_text:
            return {"name": None, "amount": None, "unit": None}
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
        # Заменяем HTML entities
        text = text.replace('&uuml;', 'ü')
        text = text.replace('&ccedil;', 'ç')
        text = text.replace('&ouml;', 'ö')
        text = text.replace('&Uuml;', 'ü')
        text = text.replace('&Ccedil;', 'ç')
        text = text.replace('&Ouml;', 'ö')
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "2 kabak", "500 ml süt", "1 yemek kaşığı un"
        
        # Сначала пробуем извлечь число в начале
        number_match = re.match(r'^([\d.,/]+)\s*(.*)$', text)
        
        if number_match:
            amount = number_match.group(1).strip()
            rest = number_match.group(2).strip()
            
            # Попробуем найти единицу измерения в начале оставшейся строки
            unit_pattern = r'^(g|gr|grams?|kg|kilograms?|ml|milliliters?|l|liters?|cups?|tablespoons?|teaspoons?|yemek kaşığı|tatlı kaşığı|çay bardağı|su bardağı|demet|bunch|pieces?|paket|package)\s+(.+)$'
            unit_match = re.match(unit_pattern, rest, re.IGNORECASE)
            
            if unit_match:
                unit = unit_match.group(1).strip()
                name = unit_match.group(2).strip()
            else:
                unit = None
                name = rest
        else:
            # Если нет числа в начале, проверяем фразы типа "Yarım demet"
            if re.match(r'^(yarım|bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on)\s+', text, re.IGNORECASE):
                # Попробуем найти единицу измерения
                unit_pattern = r'^(yarım|bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on)\s+(g|gr|grams?|kg|kilograms?|ml|milliliters?|l|liters?|cups?|tablespoons?|teaspoons?|yemek kaşığı|tatlı kaşığı|çay bardağı|su bardağı|demet|bunch|pieces?|paket|package)\s+(.+)$'
                unit_match = re.match(unit_pattern, text, re.IGNORECASE)
                
                if unit_match:
                    amount = unit_match.group(1).strip()
                    unit = unit_match.group(2).strip()
                    name = unit_match.group(3).strip()
                else:
                    amount = None
                    unit = None
                    name = text
            else:
                amount = None
                unit = None
                name = text
        
        # Очистка названия от лишних фраз
        if name:
            name = re.sub(r'\(.*?\)', '', name)  # Удаляем скобки
            name = re.sub(r'\s+', ' ', name).strip()
        
        return {
            "name": name if name else None,
            "amount": amount if amount else None,
            "unit": unit if unit else None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        recipe_data = self.extract_json_ld_recipe()
        
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredients_list = recipe_data['recipeIngredient']
        
        if not isinstance(ingredients_list, list):
            return None
        
        parsed_ingredients = []
        for ingredient_text in ingredients_list:
            if isinstance(ingredient_text, str):
                parsed = self.parse_ingredient_text(ingredient_text)
                if parsed['name']:
                    parsed_ingredients.append(parsed)
        
        return json.dumps(parsed_ingredients, ensure_ascii=False) if parsed_ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        recipe_data = self.extract_json_ld_recipe()
        
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        steps = []
        
        if isinstance(instructions, list):
            for item in instructions:
                if isinstance(item, str):
                    # Простая строка
                    text = self.clean_text(item)
                    # Убираем нумерацию в начале строки
                    text = re.sub(r'^\d+\.\s*', '', text)
                    if text:
                        steps.append(text)
                elif isinstance(item, dict):
                    # Объект HowToSection
                    if item.get('@type') == 'HowToSection':
                        item_list = item.get('itemListElement', [])
                        for step_item in item_list:
                            if isinstance(step_item, dict) and 'text' in step_item:
                                text = self.clean_text(step_item['text'])
                                # Убираем нумерацию в начале строки
                                text = re.sub(r'^\d+\.\s*', '', text)
                                if text:
                                    steps.append(text)
                    # Объект HowToStep
                    elif item.get('@type') == 'HowToStep' and 'text' in item:
                        text = self.clean_text(item['text'])
                        # Убираем нумерацию в начале строки
                        text = re.sub(r'^\d+\.\s*', '', text)
                        if text:
                            steps.append(text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self.extract_json_ld_recipe()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            return self.clean_text(recipe_data['recipeCategory'])
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT15M" или "PT1H30M"
            
        Returns:
            Время в минутах с единицами, например "15 minutes"
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
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.extract_json_ld_recipe()
        
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self.extract_json_ld_recipe()
        
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.extract_json_ld_recipe()
        
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем секцию "Püf Noktası" (Tips/Notes)
        # Ищем элемент, содержащий текст "Püf Noktası" (с учетом пробелов)
        all_puf = self.soup.find_all(string=lambda text: text and 'Püf Noktası' in text.strip() and len(text.strip()) < 30)
        
        for notes_header in all_puf:
            parent = notes_header.parent
            if not parent:
                continue
            
            # Ищем следующий элемент после заголовка
            next_sibling = parent.find_next_sibling()
            if next_sibling:
                ul_element = next_sibling.find('ul')
                if ul_element:
                    # Извлекаем все элементы списка
                    notes_items = []
                    for li in ul_element.find_all('li'):
                        text = self.clean_text(li.get_text())
                        if text:
                            notes_items.append(text)
                    
                    if notes_items:
                        return ' '.join(notes_items)
            
            # Альтернативный способ: ищем в родительском контейнере
            container = parent.parent
            if container:
                ul_element = container.find('ul')
                if ul_element:
                    notes_items = []
                    for li in ul_element.find_all('li'):
                        text = self.clean_text(li.get_text())
                        if text:
                            notes_items.append(text)
                    
                    if notes_items:
                        return ' '.join(notes_items)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        recipe_data = self.extract_json_ld_recipe()
        
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Разделяем по запятой и очищаем
                tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                return ', '.join(tags_list) if tags_list else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Сначала из JSON-LD
        recipe_data = self.extract_json_ld_recipe()
        
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
        
        # Также проверяем og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            img_url = og_image['content']
            if img_url not in urls:
                urls.append(img_url)
        
        # Убираем дубликаты и возвращаем как строку через запятую
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
    """Точка входа для обработки директории с примерами"""
    import os
    
    # Ищем директорию preprocessed/lezzet_com_tr относительно корня проекта
    project_root = Path(__file__).parent.parent
    preprocessed_dir = project_root / "preprocessed" / "lezzet_com_tr"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(LezzetComTrExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python lezzet_com_tr.py")


if __name__ == "__main__":
    main()
