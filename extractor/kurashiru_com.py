"""
Экстрактор данных рецептов для сайта kurashiru.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KurashiruExtractor(BaseRecipeExtractor):
    """Экстрактор для kurashiru.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах, например "20 minutes"
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
        
        if total_minutes == 0:
            return None
        
        return f"{total_minutes} minutes"
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " 作り方・レシピ | クラシル"
            title = re.sub(r'\s+(作り方・レシピ|レシピ).*$', '', title)
            return self.clean_text(title)
        
        # Альтернативно - из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            title = re.sub(r'\s+(作り方・レシピ|レシピ).*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Сначала пробуем извлечь из JSON-LD для получения структурированных данных
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем тип Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    # Извлекаем ингредиенты из recipeIngredient
                    if 'recipeIngredient' in data:
                        recipe_ingredients = data['recipeIngredient']
                        if isinstance(recipe_ingredients, list):
                            for ingredient_str in recipe_ingredients:
                                # Парсим строку ингредиента
                                parsed = self.parse_kurashiru_ingredient(ingredient_str)
                                if parsed:
                                    ingredients.append(parsed)
                            
                            if ingredients:
                                return json.dumps(ingredients, ensure_ascii=False)
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, ищем в HTML
        # Ищем список ингредиентов по классу App-ingredients
        ingredient_list = self.soup.find('ul', class_=re.compile(r'App-ingredients', re.I))
        
        if ingredient_list:
            items = ingredient_list.find_all('li', class_=re.compile(r'App-ingredient', re.I))
            
            for item in items:
                # Извлекаем название ингредиента из App-ingredientTitle
                name_elem = item.find('div', class_=re.compile(r'App-ingredientTitle', re.I))
                
                # Извлекаем количество из App-ingredientQuantityAmount
                quantity_elem = item.find('div', class_=re.compile(r'App-ingredientQuantityAmount', re.I))
                
                if name_elem:
                    name = self.clean_text(name_elem.get_text())
                    quantity_text = self.clean_text(quantity_elem.get_text()) if quantity_elem else None
                    
                    # Пропускаем пустые элементы
                    if not name:
                        continue
                    
                    # Парсим количество и единицу
                    amount, unit = self.parse_quantity(quantity_text) if quantity_text else (None, None)
                    
                    ingredients.append({
                        "name": name,
                        "amount": amount,
                        "units": unit
                    })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_kurashiru_ingredient(self, ingredient_str: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента kurashiru в структурированный формат
        
        Args:
            ingredient_str: Строка вида "ホットケーキミックス 150g" или "卵 1個"
            
        Returns:
            dict: {"name": "...", "amount": "...", "units": "..."} или None
        """
        if not ingredient_str:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_str)
        
        # Паттерн для японских ингредиентов: название + количество + единица
        # Примеры: "ホットケーキミックス 150g", "卵 1個", "砂糖 大さじ1"
        
        # Сначала пробуем найти количество с единицей в конце
        pattern = r'^(.+?)\s+([\d.]+\s*[gmlкгмл個大さじ小さじ適量カップ本枚]+|適量)$'
        match = re.match(pattern, text)
        
        if match:
            name = match.group(1).strip()
            quantity_str = match.group(2).strip()
            
            # Парсим количество и единицу
            amount, unit = self.parse_quantity(quantity_str)
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        else:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
    
    def parse_quantity(self, quantity_str: str) -> tuple:
        """
        Парсинг строки количества в amount и unit
        
        Args:
            quantity_str: "150g", "1個", "大さじ1", "適量"
            
        Returns:
            (amount, unit) where amount is int/float/None
        """
        if not quantity_str:
            return (None, None)
        
        # Проверяем на "適量" (по вкусу/по необходимости)
        if '適量' in quantity_str:
            return (None, '適量')
        
        # Извлекаем число
        number_match = re.search(r'[\d.]+', quantity_str)
        if number_match:
            amount_str = number_match.group()
            # Конвертируем в число
            amount_float = float(amount_str)
            # Если это целое число, возвращаем как int
            amount = int(amount_float) if amount_float.is_integer() else amount_float
            
            # Извлекаем единицу (все, что после числа)
            unit = quantity_str.replace(amount_str, '').strip()
            return (amount, unit if unit else None)
        else:
            # Если числа нет, вся строка - единица
            return (None, quantity_str)
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'recipeInstructions' in data:
                        instructions = data['recipeInstructions']
                        if isinstance(instructions, list):
                            for step in instructions:
                                if isinstance(step, dict):
                                    # HowToStep объект
                                    if 'text' in step:
                                        steps.append(step['text'])
                                elif isinstance(step, str):
                                    steps.append(step)
                        
                        if steps:
                            # Нумеруем шаги
                            numbered_steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
                            return '\n'.join(numbered_steps)
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, ищем в HTML
        # Ищем список инструкций по классу App-instructions
        instruction_list = self.soup.find('ol', class_=re.compile(r'App-instructions', re.I))
        
        if instruction_list:
            items = instruction_list.find_all('li', class_=re.compile(r'App-instruction\b', re.I))
            
            for item in items:
                # Извлекаем текст шага
                body_elem = item.find('div', class_=re.compile(r'App-instructionBody', re.I))
                
                if body_elem:
                    step_text = self.clean_text(body_elem.get_text())
                    if step_text:
                        steps.append(step_text)
        else:
            # Если нет ol, ищем напрямую все App-instructionBody
            body_elems = self.soup.find_all('div', class_=re.compile(r'App-instructionBody', re.I))
            for body_elem in body_elems:
                step_text = self.clean_text(body_elem.get_text())
                if step_text:
                    steps.append(step_text)
        
        if steps:
            # Нумеруем шаги
            numbered_steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
            return '\n'.join(numbered_steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'recipeCategory' in data:
                        category = data['recipeCategory']
                        if isinstance(category, str):
                            # Берем первую категорию
                            first_category = category.split(',')[0].strip() if category else None
                            return self.clean_text(first_category) if first_category else None
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из хлебных крошек
        breadcrumb = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumb:
            links = breadcrumb.find_all('a')
            if len(links) > 1:  # Берем последнюю категорию перед рецептом
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Извлекаем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    # Маппинг типов времени на ключи JSON-LD
                    time_keys = {
                        'prep': 'prepTime',
                        'cook': 'cookTime',
                        'total': 'totalTime'
                    }
                    
                    key = time_keys.get(time_type)
                    if key and key in data:
                        iso_time = data[key]
                        return self.parse_iso_duration(iso_time)
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('total')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями (App-memo или memo class)
        memo_elem = self.soup.find('div', class_=re.compile(r'App-memo', re.I))
        
        if memo_elem:
            text = self.clean_text(memo_elem.get_text())
            # Убираем <br> теги, заменяя их на пробелы
            return text if text else None
        
        # Альтернативно - ищем section с классом memo
        notes_section = self.soup.find('section', class_=re.compile(r'memo', re.I))
        
        if notes_section:
            # Ищем содержимое
            content_elem = notes_section.find('p', class_=re.compile(r'memo.*content', re.I))
            if content_elem:
                text = self.clean_text(content_elem.get_text())
                return text if text else None
            
            # Если нет параграфа с классом, берем все параграфы
            paragraphs = notes_section.find_all('p')
            if paragraphs:
                texts = [self.clean_text(p.get_text()) for p in paragraphs]
                texts = [t for t in texts if t and not t.startswith('コツ・ポイント')]
                return ' '.join(texts) if texts else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из recipeCategory"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'recipeCategory' in data:
                        category = data['recipeCategory']
                        if isinstance(category, str):
                            # Разделяем по запятой и очищаем
                            tags = [self.clean_text(tag) for tag in category.split(',')]
                            tags = [tag for tag in tags if tag]
                            return ', '.join(tags) if tags else None
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # thumbnail meta
        thumbnail = self.soup.find('meta', attrs={'name': 'thumbnail'})
        if thumbnail and thumbnail.get('content'):
            urls.append(thumbnail['content'])
        
        # 2. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    # Извлекаем изображение из image поля
                    if 'image' in data:
                        img = data['image']
                        if isinstance(img, str):
                            urls.append(img)
                        elif isinstance(img, list):
                            urls.extend([i for i in img if isinstance(i, str)])
                        elif isinstance(img, dict):
                            if 'url' in img:
                                urls.append(img['url'])
                            elif 'contentUrl' in img:
                                urls.append(img['contentUrl'])
                    
                    # Извлекаем из видео thumbnail
                    if 'video' in data and isinstance(data['video'], dict):
                        video = data['video']
                        if 'thumbnail' in video:
                            thumb = video['thumbnail']
                            if isinstance(thumb, str):
                                urls.append(thumb)
                            elif isinstance(thumb, dict) and 'url' in thumb:
                                urls.append(thumb['url'])
                
            except (json.JSONDecodeError, KeyError):
                continue
        
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
    import os
    # Обрабатываем папку preprocessed/kurashiru_com
    recipes_dir = os.path.join("preprocessed", "kurashiru_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(KurashiruExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python kurashiru_com.py")


if __name__ == "__main__":
    main()
