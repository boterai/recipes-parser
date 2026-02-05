"""
Экстрактор данных рецептов для сайта ovkuse.ru
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class OvkuseRuExtractor(BaseRecipeExtractor):
    """Экстрактор для ovkuse.ru"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах, например "30 minutes" или "90 minutes"
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
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Получение данных рецепта из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
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
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s+\d+\s+ккал.*$', '', title)
            title = re.sub(r'\s+-\s+Овкусе\.ру$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            # Убираем хештеги из описания
            desc = re.sub(r'\s*#\S+', '', desc)
            return self.clean_text(desc)
        
        # Альтернативно из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            desc = re.sub(r'\s*#\S+', '', desc)
            return self.clean_text(desc)
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Извлекаем из HTML (более детально чем JSON-LD)
        ingredient_items = self.soup.find_all('li', itemprop='recipeIngredient')
        
        for item in ingredient_items:
            text = item.get_text(strip=True)
            span = item.find('span')
            
            if span:
                # Есть количество и единица измерения
                amount_unit_text = span.get_text(strip=True)
                name = text.replace(amount_unit_text, '').strip()
                
                # Парсим количество и единицу
                amount, unit = self._parse_amount_unit(amount_unit_text)
                
                ingredients.append({
                    "name": self.clean_text(name),
                    "units": unit,
                    "amount": amount
                })
            else:
                # Только название без количества
                ingredients.append({
                    "name": self.clean_text(text),
                    "units": None,
                    "amount": None
                })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def _parse_amount_unit(self, amount_unit_text: str) -> tuple:
        """
        Парсинг строки с количеством и единицей измерения
        
        Args:
            amount_unit_text: Строка вида "1 кг" или "2-3 ст. л."
            
        Returns:
            tuple: (amount, unit)
        """
        amount_unit_text = amount_unit_text.strip()
        
        # Паттерны для единиц измерения
        units_pattern = r'(кг|г|мл|л|ст\.\s*л\.|ч\.\s*л\.|шт\.|зуб\.|по\s+вкусу)'
        
        match = re.search(units_pattern, amount_unit_text, re.IGNORECASE)
        
        if match:
            unit = match.group(1).strip()
            amount = amount_unit_text[:match.start()].strip()
            # Заменяем запятые на точки и убираем лишние пробелы
            amount = amount.replace(',', '.').strip() if amount else None
            return (amount, unit)
        
        # Если единицы нет, все это количество
        amount = amount_unit_text.replace(',', '.').strip()
        return (amount, None)
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            
            if isinstance(instructions, list):
                # Собираем текст из всех шагов
                all_text = []
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        text = step['text']
                        # Очищаем от лишних фраз
                        text = re.sub(r'\s*Приятного аппетита!?\s*$', '', text, flags=re.IGNORECASE)
                        text = re.sub(r'\s*Подробнее смотрите в моём видеоролике\s*$', '', text, flags=re.IGNORECASE)
                        all_text.append(text)
                    elif isinstance(step, str):
                        all_text.append(step)
                
                if all_text:
                    result = ' '.join(all_text)
                    return self.clean_text(result)
        
        # Если JSON-LD не помог, ищем в HTML
        instructions_div = self.soup.find('div', itemprop='recipeInstructions')
        if instructions_div:
            text = instructions_div.get_text(separator=' ', strip=True)
            text = re.sub(r'\s*Приятного аппетита!?\s*$', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\s*Подробнее смотрите в моём видеоролике\s*$', '', text, flags=re.IGNORECASE)
            return self.clean_text(text)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Извлекаем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            if isinstance(category, list):
                return ', '.join(category)
            return str(category)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'cookTime' in recipe_data:
            cook_time = self.parse_iso_duration(recipe_data['cookTime'])
            
            # Иногда в инструкциях указано более точное время
            instructions = self.extract_instructions()
            if instructions:
                # Ищем паттерны типа "30-35 минут"
                time_match = re.search(r'(\d+[-–]\d+)\s*(?:минут|мин)', instructions)
                if time_match:
                    return f"{time_match.group(1)} minutes"
            
            return cook_time
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        # Если totalTime нет, но есть prepTime и cookTime, суммируем
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep and cook:
            try:
                prep_mins = int(re.search(r'\d+', prep).group())
                cook_mins = int(re.search(r'\d+', cook).group())
                return f"{prep_mins + cook_mins} minutes"
            except:
                pass
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем фразу "Приятного аппетита" в сыром тексте инструкций из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        text = step['text']
                        match = re.search(r'(Приятного аппетита!?)', text, re.IGNORECASE)
                        if match:
                            return match.group(1)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем хештеги в описании JSON-LD
        recipe_data = self._get_recipe_json_ld()
        
        tags = []
        
        if recipe_data:
            # Ищем в описании
            if 'description' in recipe_data:
                desc = recipe_data['description']
                hashtags = re.findall(r'#(\S+)', desc)
                tags.extend(hashtags)
            
            # Также добавляем категории как теги
            if 'recipeCategory' in recipe_data:
                categories = recipe_data['recipeCategory']
                if isinstance(categories, list):
                    tags.extend([cat.lower() for cat in categories])
                else:
                    tags.append(str(categories).lower())
        
        # Убираем дубликаты
        seen = set()
        unique_tags = []
        for tag in tags:
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen.add(tag_lower)
                unique_tags.append(tag_lower)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Извлекаем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'image' in recipe_data:
            images = recipe_data['image']
            if isinstance(images, list):
                urls.extend(images)
            elif isinstance(images, str):
                urls.append(images)
        
        # Также пробуем из meta тегов
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)
        
        twitter_image = self.soup.find('meta', property='twitter:image')
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if url not in urls:
                urls.append(url)
        
        # Убираем дубликаты
        unique_urls = []
        seen = set()
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        return ','.join(unique_urls) if unique_urls else None
    
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
    # Обрабатываем папку preprocessed/ovkuse_ru
    recipes_dir = os.path.join("preprocessed", "ovkuse_ru")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(OvkuseRuExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python ovkuse_ru.py")


if __name__ == "__main__":
    main()
