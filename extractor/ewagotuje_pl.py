"""
Экстрактор данных рецептов для сайта ewagotuje.pl
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class EwaGotujeExtractor(BaseRecipeExtractor):
    """Экстрактор для ewagotuje.pl"""
    
    def _find_recipe_json_ld(self) -> Optional[dict]:
        """
        Найти JSON-LD с данными рецепта
        
        Returns:
            Словарь с данными рецепта из JSON-LD или None
        """
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем, является ли это Recipe
                if isinstance(data, dict):
                    item_type = data.get('@type', '')
                    if item_type == 'Recipe':
                        return data
                    # Проверяем в @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if item.get('@type') == 'Recipe':
                                return item
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT50M" или "PT1H50M"
            
        Returns:
            Время в формате "50 minutes" или "1 hour 50 minutes"
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
        
        # Форматируем результат - всегда используем "minutes" для единообразия
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
        if minutes > 0:
            parts.append(f"{minutes} minutes")
        
        return ' '.join(parts) if parts else None
    
    def parse_ingredient_string(self, ingredient_text: str) -> Optional[Dict[str, any]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1,5 kg cebuli - Składniki na zupę cebulową"
            
        Returns:
            dict: {"name": "cebuli", "amount": 1.5, "units": "kg"} або None
        """
        if not ingredient_text:
            return None
        
        # Убираем описание после дефиса (категория ингредиента)
        text = ingredient_text.split(' - ')[0].strip()
        text = self.clean_text(text)
        
        # Замена дробных символов на текст перед парсингом
        text = text.replace('½', '0.5')
        text = text.replace('¼', '0.25')
        text = text.replace('¾', '0.75')
        text = text.replace('⅓', '0.33')
        text = text.replace('⅔', '0.67')
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1,5 kg cebuli", "2 łyżki oliwy", "3 ząbki czosnku"
        # Учитываем польские единицы: kg, g, l, ml, łyżki, łyżeczki, ząbki, szt., szczypty и т.д.
        # ВАЖНО: единица должна быть отделена пробелом от названия, чтобы "3 liście" не парсилось как "3 l iście"
        pattern = r'^([\d\s/.,]+)?\s*(kg|g|ml|l(?=\s|$)|łyżki|łyżka|łyżeczki|łyżeczka|ząbki|ząbek|szt\.|szt|szczypty|szczypta|ziarna|ziarno)?\s*(.+)'
        
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
            amount_str = amount_str.strip().replace(',', '.')
            # Обработка дробей типа "1/2" или "1 1/2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                amount = total
            else:
                try:
                    amount = float(amount_str)
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        name = name.strip()
        # Удаляем информацию в скобках (например "(tortowa, typ 450)")
        name = re.sub(r'\s*\([^)]*\)', '', name)
        # Удаляем лишние запятые и пробелы в конце
        name = re.sub(r'[,;]+$', '', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self._find_recipe_json_ld()
        
        if recipe_data and 'name' in recipe_data:
            name = recipe_data['name']
            # Убираем суффиксы типа " - najlepszy przepis"
            name = re.sub(r'\s*-\s*najlepszy przepis', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\s*-\s*przepis.*$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*-\s*najlepszy przepis', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*-\s*przepis.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self._find_recipe_json_ld()
        
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        recipe_data = self._find_recipe_json_ld()
        
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredients = []
        ingredient_strings = recipe_data['recipeIngredient']
        
        if isinstance(ingredient_strings, list):
            for ingredient_text in ingredient_strings:
                parsed = self.parse_ingredient_string(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self._find_recipe_json_ld()
        
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        steps = []
        
        if isinstance(instructions, list):
            step_counter = 1
            for item in instructions:
                if isinstance(item, dict):
                    # Если это HowToSection с вложенными шагами
                    if item.get('@type') == 'HowToSection' and 'itemListElement' in item:
                        for step in item['itemListElement']:
                            if isinstance(step, dict) and 'text' in step:
                                steps.append(f"{step_counter}. {step['text']}")
                                step_counter += 1
                    # Если это прямой HowToStep
                    elif item.get('@type') == 'HowToStep' and 'text' in item:
                        steps.append(f"{step_counter}. {item['text']}")
                        step_counter += 1
                    # Если это просто объект с текстом
                    elif 'text' in item:
                        steps.append(f"{step_counter}. {item['text']}")
                        step_counter += 1
                elif isinstance(item, str):
                    steps.append(f"{step_counter}. {item}")
                    step_counter += 1
        elif isinstance(instructions, str):
            return self.clean_text(instructions)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self._find_recipe_json_ld()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            return self.clean_text(recipe_data['recipeCategory'])
        
        # Можем также попробовать recipeCuisine
        if recipe_data and 'recipeCuisine' in recipe_data:
            return self.clean_text(recipe_data['recipeCuisine'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._find_recipe_json_ld()
        
        if recipe_data and 'prepTime' in recipe_data:
            iso_time = recipe_data['prepTime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self._find_recipe_json_ld()
        
        if recipe_data and 'cookTime' in recipe_data:
            iso_time = recipe_data['cookTime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._find_recipe_json_ld()
        
        if recipe_data and 'totalTime' in recipe_data:
            iso_time = recipe_data['totalTime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # В JSON-LD ewagotuje.pl нет специального поля для notes
        # Попробуем найти в HTML
        
        # Ищем секцию с примечаниями/советами
        notes_section = self.soup.find(class_=re.compile(r'note|tip|uwaga', re.I))
        
        if notes_section:
            text = notes_section.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        recipe_data = self._find_recipe_json_ld()
        
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            # keywords уже в формате строки через запятую
            if isinstance(keywords, str):
                # Убираем слово "przepis" из тегов
                tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                tags = [tag for tag in tags if tag.lower() != 'przepis']
                return ', '.join(tags) if tags else None
            elif isinstance(keywords, list):
                tags = [tag.strip() for tag in keywords if tag.strip() and tag.lower() != 'przepis']
                return ', '.join(tags) if tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Сначала пробуем из JSON-LD
        recipe_data = self._find_recipe_json_ld()
        
        if recipe_data and 'image' in recipe_data:
            image = recipe_data['image']
            if isinstance(image, str):
                urls.append(image)
            elif isinstance(image, list):
                urls.extend([img for img in image if isinstance(img, str)])
            elif isinstance(image, dict):
                if 'url' in image:
                    urls.append(image['url'])
                elif 'contentUrl' in image:
                    urls.append(image['contentUrl'])
        
        # Дополнительно ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if url not in urls:
                urls.append(url)
        
        # Возвращаем как строку через запятую (без пробелов)
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
    import os
    # Обрабатываем папку preprocessed/ewagotuje_pl
    recipes_dir = os.path.join("preprocessed", "ewagotuje_pl")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(EwaGotujeExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python ewagotuje_pl.py")


if __name__ == "__main__":
    main()
