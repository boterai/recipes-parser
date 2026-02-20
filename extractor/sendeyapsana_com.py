"""
Экстрактор данных рецептов для сайта sendeyapsana.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class SendeyapsanaExtractor(BaseRecipeExtractor):
    """Экстрактор для sendeyapsana.com"""
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение Recipe объекта из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                # Проверка в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                
                # Проверка напрямую
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                
                # Проверка в списке
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
            
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT50M"
            
        Returns:
            Время в формате "20 minutes", "1 hour 30 minutes", "50 minutes"
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
        
        # Формируем строку
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'name' in recipe_data:
            # Убираем суффикс вида " Tarifi", " - ", и другое
            name = recipe_data['name']
            name = re.sub(r'\s*-\s*.*$', '', name)  # Убираем все после тире
            name = re.sub(r'\s+Tarifi\s*$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*-\s*.*$', '', title)
            title = re.sub(r'\s+Tarifi\s*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "-150 gram tereyağı" или "-2 tane yumurta sarısı"
            
        Returns:
            dict: {"name": "tereyağı", "amount": "150", "units": "gram"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст и убираем начальный тире
        text = self.clean_text(ingredient_text).strip()
        text = text.lstrip('-').strip()
        
        if not text:
            return None
        
        # Обрабатываем "Yarım" (половина) и другие текстовые числа
        text_numbers = {
            'yarım': '0.5',
            'yarim': '0.5',
            'bir': '1',
            'iki': '2',
            'üç': '3',
            'dört': '4',
            'beş': '5'
        }
        
        # Проверяем начало строки на текстовое число
        for word, number in text_numbers.items():
            if text.lower().startswith(word + ' '):
                text = number + text[len(word):]
                break
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "150 gram tereyağı", "2 tane yumurta sarısı", "1 su bardağı pudra şekeri"
        # Общий паттерн: [количество] [единица] [название]
        pattern = r'^([\d.,/]+(?:\s*-\s*[\d.,/]+)?)\s+((?:su\s+)?(?:bardağı|bardak|gram|tane|paket|yemek\s+kaşığı|tatlı\s+kaşığı|çay\s+kaşığı|kaşık|kase|tutam|adet))\s+(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount = amount_str.strip()
            # Заменяем запятые на точки
            amount = amount.replace(',', '.')
            
            # Обработка единицы измерения
            unit = unit.strip()
            
            # Очистка названия
            name = name.strip()
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        
        # Если паттерн не совпал, пробуем без единиц измерения
        # Паттерн: [количество] [название]
        pattern_no_unit = r'^([\d.,/]+(?:\s*-\s*[\d.,/]+)?)\s+(.+)$'
        match_no_unit = re.match(pattern_no_unit, text, re.IGNORECASE)
        
        if match_no_unit:
            amount_str, name = match_no_unit.groups()
            amount = amount_str.strip().replace(',', '.')
            
            return {
                "name": name.strip(),
                "amount": amount,
                "units": None
            }
        
        # Если ничего не совпало, возвращаем только название
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD или HTML"""
        recipe_data = self._get_recipe_json_ld()
        
        # Пробуем извлечь из JSON-LD
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredient_list = recipe_data['recipeIngredient']
            
            if isinstance(ingredient_list, list):
                parsed_ingredients = []
                for ingredient_text in ingredient_list:
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        parsed_ingredients.append(parsed)
                
                if parsed_ingredients:
                    return json.dumps(parsed_ingredients, ensure_ascii=False)
        
        # Fallback: извлечение из HTML (если JSON-LD не содержит ингредиентов)
        # Ищем параграфы с ингредиентами (начинаются с дефиса)
        parsed_ingredients = []
        for p in self.soup.find_all('p'):
            text = p.get_text().strip()
            if text.startswith('-') and len(text) > 2:
                # Убираем начальный дефис и парсим
                ingredient_text = text.lstrip('-').strip()
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    parsed_ingredients.append(parsed)
        
        return json.dumps(parsed_ingredients, ensure_ascii=False) if parsed_ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления из JSON-LD или HTML"""
        recipe_data = self._get_recipe_json_ld()
        
        # Пробуем извлечь из JSON-LD
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions_data = recipe_data['recipeInstructions']
            
            if isinstance(instructions_data, list):
                # Собираем только основные шаги приготовления (первая секция обычно)
                # Пропускаем секции с калориями и пюф-нотами
                all_steps = []
                
                for section in instructions_data:
                    if not isinstance(section, dict):
                        continue
                    
                    section_name = section.get('name', '')
                    
                    # Пропускаем секции с калориями и пюф-нотами
                    if 'калори' in section_name.lower() or 'kaç kalori' in section_name.lower():
                        continue
                    if 'püf' in section_name.lower() or 'пюф' in section_name.lower():
                        continue
                    
                    # Извлекаем шаги из секции
                    item_list = section.get('itemListElement', [])
                    for item in item_list:
                        if isinstance(item, dict) and 'text' in item:
                            text = self.clean_text(item['text'])
                            if text:
                                all_steps.append(text)
                
                if all_steps:
                    return ' '.join(all_steps)
        
        # Fallback: извлечение из HTML
        # Ищем параграф с инструкциями (обычно содержит текст приготовления)
        # Характерные фразы для инструкций
        instruction_keywords = ['kesiyoruz', 'koyalım', 'dökelim', 'alım', 'pişir']
        
        for p in self.soup.find_all('p'):
            text = p.get_text().strip()
            # Проверяем, что это не ингредиент (не начинается с дефиса)
            # и содержит ключевые слова инструкций
            if not text.startswith('-') and len(text) > 50:
                # Проверяем наличие хотя бы одного ключевого слова
                if any(keyword in text.lower() for keyword in instruction_keywords):
                    return self.clean_text(text)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            return self.clean_text(recipe_data['recipeCategory'])
        
        # Альтернативно - из meta article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
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
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов из секции с пюф-нотами в recipeInstructions"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions_data = recipe_data['recipeInstructions']
            
            if not isinstance(instructions_data, list):
                return None
            
            # Ищем секцию с пюф-нотами
            for section in instructions_data:
                if not isinstance(section, dict):
                    continue
                
                section_name = section.get('name', '')
                
                # Ищем секцию с "Püf Noktaları" или "Püf Noktası"
                if 'püf' in section_name.lower():
                    item_list = section.get('itemListElement', [])
                    notes = []
                    for item in item_list:
                        if isinstance(item, dict) and 'text' in item:
                            text = self.clean_text(item['text'])
                            if text:
                                notes.append(text)
                    
                    return ' '.join(notes) if notes else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            
            # keywords может быть строкой с разделителями
            if isinstance(keywords, str):
                # Разделяем по запятой
                tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                # Возвращаем как строку через ", " (с пробелом после запятой)
                return ', '.join(tags) if tags else None
            
            # Если это список
            elif isinstance(keywords, list):
                tags = [str(tag).strip() for tag in keywords if tag]
                return ', '.join(tags) if tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из JSON-LD"""
        urls = []
        
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'image' in recipe_data:
            image_data = recipe_data['image']
            
            # Если это строка (URL)
            if isinstance(image_data, str):
                urls.append(image_data)
            
            # Если это словарь с @id или url
            elif isinstance(image_data, dict):
                if '@id' in image_data:
                    # @id может быть URL или ссылкой на ImageObject
                    img_id = image_data['@id']
                    if img_id.startswith('http'):
                        urls.append(img_id)
                elif 'url' in image_data:
                    urls.append(image_data['url'])
                elif 'contentUrl' in image_data:
                    urls.append(image_data['contentUrl'])
            
            # Если это список
            elif isinstance(image_data, list):
                for img in image_data:
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, dict):
                        if 'url' in img:
                            urls.append(img['url'])
                        elif 'contentUrl' in img:
                            urls.append(img['contentUrl'])
        
        # Также ищем в @graph ImageObject'ы
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
            
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        
        # Также пробуем из meta тегов
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
            
            # Возвращаем как строку через запятую без пробелов
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
    # Обрабатываем папку preprocessed/sendeyapsana_com
    recipes_dir = os.path.join("preprocessed", "sendeyapsana_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(SendeyapsanaExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python sendeyapsana_com.py")


if __name__ == "__main__":
    main()
