"""
Экстрактор данных рецептов для сайта hellofresh.nl
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class HelloFreshExtractor(BaseRecipeExtractor):
    """Экстрактор для hellofresh.nl"""
    
    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Получить данные рецепта из JSON-LD"""
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
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из H1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта (первые 2 предложения)"""
        description = None
        
        # Из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'description' in recipe_data:
            description = recipe_data['description']
        
        # Альтернативно - из meta description
        if not description:
            meta_desc = self.soup.find('meta', {'name': 'description'})
            if meta_desc and meta_desc.get('content'):
                description = meta_desc['content']
        
        if description:
            # Берем только первые 2 предложения
            sentences = description.split('. ')
            if len(sentences) >= 2:
                description = '. '.join(sentences[:2]) + '.'
            
            return self.clean_text(description)
        
        return None
    
    def parse_ingredient_string(self, ingredient_str: str, keep_fractions: bool = False) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_str: Строка вида "50 ml Kokosmelk" или "½ stuk(s) Knoflookteen"
            keep_fractions: Сохранять ли дроби как есть (True) или преобразовать в десятичные (False)
            
        Returns:
            dict: {"name": "Kokosmelk", "amount": "50", "units": "ml"}
        """
        if not ingredient_str:
            return None
        
        text = self.clean_text(ingredient_str)
        
        # Маппинг дробей для преобразования (если нужно)
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        # Сохраняем оригинальные дроби для amount
        original_text = text
        
        # Паттерн: количество + единица + название
        # Примеры: "50 ml Kokosmelk", "½ stuk(s) Knoflookteen", "1.5 tl Kerriepoeder"
        pattern = r'^([\d\s/.,½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘]+)?\s*(ml|gram|g|kg|tl|el|l|head|stuk\(s\)|takje\(s\)|snufje\(s\)|blik\(ken\)|zakje\(s\)|teen\(tjes\)|naar smaak)?\s*(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, units, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            
            # Если keep_fractions=True, оставляем дроби как есть
            if keep_fractions:
                amount = amount_str
            else:
                # Заменяем дроби на десятичные
                for fraction, decimal in fraction_map.items():
                    amount_str = amount_str.replace(fraction, decimal)
                
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
                    amount = str(total)
                else:
                    amount = amount_str.replace(',', '.')
        
        # Обработка единицы измерения
        units = units.strip() if units else None
        
        # Очистка названия (удаляем инфо об аллергенах в скобках)
        if name:
            # Удаляем части типа "(Bevat: ...)"
            name = re.sub(r'\(Bevat:.*?\)', '', name, flags=re.IGNORECASE)
            name = name.strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
    def extract_ingredients(self) -> Optional[list]:
        """Извлечение ингредиентов из HTML (shipped и not-shipped items)"""
        ingredients = []
        
        # Извлекаем ингредиенты из HTML элементов (для 1 персоны с дробями)
        # Shipped ingredients
        ing_items_shipped = self.soup.find_all(attrs={'data-test-id': 'ingredient-item-shipped'})
        for item in ing_items_shipped:
            text = item.get_text(separator=' ', strip=True)
            # Удаляем информацию об аллергенах в скобках
            text = re.sub(r'\(Bevat:.*?\)', '', text, flags=re.IGNORECASE).strip()
            parsed = self.parse_ingredient_string(text, keep_fractions=True)
            if parsed:
                ingredients.append(parsed)
        
        # Not-shipped ingredients (pantry items)
        ing_items_not_shipped = self.soup.find_all(attrs={'data-test-id': 'ingredient-item-not-shipped'})
        for item in ing_items_not_shipped:
            text = item.get_text(separator=' ', strip=True)
            text = re.sub(r'\(Bevat:.*?\)', '', text, flags=re.IGNORECASE).strip()
            parsed = self.parse_ingredient_string(text, keep_fractions=True)
            if parsed:
                ingredients.append(parsed)
        
        # Если не нашли в HTML, пробуем из JSON-LD (но делим на 2 для 1 персоны)
        if not ingredients:
            recipe_data = self._get_json_ld_recipe()
            if recipe_data and 'recipeIngredient' in recipe_data:
                for ingredient_str in recipe_data['recipeIngredient']:
                    parsed = self.parse_ingredient_string(ingredient_str, keep_fractions=False)
                    if parsed and parsed.get('amount'):
                        # Делим количество на 2 (для 1 персоны)
                        try:
                            amount = float(parsed['amount']) / 2
                            parsed['amount'] = str(amount)
                        except:
                            pass
                    if parsed:
                        ingredients.append(parsed)
        
        return ingredients if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        steps = []
        
        # Из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        steps.append(f"{idx}. {step['text']}")
                    elif isinstance(step, str):
                        steps.append(f"{idx}. {step}")
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Проверяем теги на наличие специфичных категорий
        tag_elements = self.soup.find_all(attrs={'data-test-id': 'item-tag-text'})
        if tag_elements:
            tags = [self.clean_text(elem.get_text()).lower() for elem in tag_elements]
            
            # Если есть "soup" в тегах или в названии рецепта
            dish_name = self.extract_dish_name()
            if dish_name:
                dish_name_lower = dish_name.lower()
                if 'soep' in dish_name_lower or 'soup' in dish_name_lower:
                    return "Soup"
        
        # По умолчанию возвращаем "Main Course"
        return "Main Course"
    
    def parse_iso_duration(self, duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT40M"
            
        Returns:
            Время в формате "40 minutes"
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
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # В HTML нет отдельного prep_time, только total_time
        # Возвращаем None, так как в данных это поле заполняется вручную
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # В HTML нет отдельного cook_time, только total_time
        # Пробуем использовать total_time как cook_time, если оно есть
        total_time = self.extract_total_time()
        if total_time:
            return total_time
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'totalTime' in recipe_data:
            total_time_str = recipe_data['totalTime']
            # Может быть в формате "PT40M" или "35m"
            if total_time_str.startswith('PT'):
                return self.parse_iso_duration(total_time_str)
            else:
                # Формат "35m" - преобразуем в "35 minutes"
                match = re.search(r'(\d+)m', total_time_str)
                if match:
                    minutes = match.group(1)
                    return f"{minutes} minutes"
        
        # Ищем в HTML текст с "minuten"
        text_elems = self.soup.find_all(string=lambda text: text and 'minuten' in text.lower())
        for elem in text_elems:
            text = elem.strip()
            if text and len(text) < 20:  # Короткий текст типа "40 minuten"
                match = re.search(r'(\d+)\s*minuten', text, re.IGNORECASE)
                if match:
                    minutes = match.group(1)
                    return f"{minutes} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок (информация об аллергенах и т.д.)"""
        notes = []
        
        # Ищем элементы с allergen или note в data-test-id
        note_elements = self.soup.find_all(attrs={'data-test-id': lambda x: x and ('allergen' in x.lower() or 'note' in x.lower() or 'tip' in x.lower()) if x else False})
        
        for elem in note_elements:
            text = self.clean_text(elem.get_text())
            if text and len(text) > 10:  # Минимальная длина для заметки
                notes.append(text)
        
        # Ищем также текст, который может содержать заметки (обычно начинается с "TIP:", "LET OP:" и т.д.)
        for pattern in ['tip:', 'let op:', 'opmerking:', 'note:', 'weetje:']:
            elements = self.soup.find_all(string=lambda text: text and pattern in text.lower())
            for elem in elements:
                text = self.clean_text(elem.strip())
                if text and len(text) > 10:
                    notes.append(text)
        
        if notes:
            # Убираем дубликаты
            unique_notes = []
            seen = set()
            for note in notes:
                note_lower = note.lower()
                if note_lower not in seen:
                    seen.add(note_lower)
                    unique_notes.append(note)
            
            return ' '.join(unique_notes[:3])  # Берем первые 3 заметки
        
        # По умолчанию возвращаем стандартное предупреждение об аллергенах
        return "Kan sporen van allergenen bevatten."
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из названия рецепта и описания"""
        tags = []
        
        # Получаем название и описание
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        
        # Ключевые слова для тегов
        tag_keywords = {
            'vegetarisch': ['veggie', 'vegetarisch', 'plantaardig'],
            'vegan': ['vegan'],
            'burger': ['burger'],
            'soep': ['soep', 'soup'],
            'curry': ['curry'],
            'pasta': ['pasta'],
            'pizza': ['pizza'],
            'salade': ['salade', 'salad'],
            'vis': ['vis', 'zalm', 'tonijn', 'kabeljauw'],
            'kip': ['kip', 'chicken'],
            'rundvlees': ['rundvlees', 'beef'],
            'varkensvlees': ['varkensvlees', 'pork'],
            'rijst': ['rijst', 'rice'],
            'noodles': ['noodles', 'noedels'],
            'linzen': ['linzen', 'lentils'],
            'makkelijk': ['makkelijk', 'easy'],
            'snel': ['snel', 'quick'],
            'Indiaas': ['indiaas', 'indian'],
            'Aziatisch': ['aziatisch', 'asian'],
            'Italiaans': ['italiaans', 'italian'],
            'Mexicaans': ['mexicaans', 'mexican'],
            'Frans': ['frans', 'french']
        }
        
        # Объединяем название и описание
        combined_text = ''
        if dish_name:
            combined_text += dish_name.lower() + ' '
        if description:
            combined_text += description.lower()
        
        # Ищем ключевые слова
        for tag, keywords in tag_keywords.items():
            for keyword in keywords:
                if keyword in combined_text:
                    tags.append(tag.lower())
                    break
        
        # Также добавляем теги из HTML (если они осмысленные)
        tag_elements = self.soup.find_all(attrs={'data-test-id': 'item-tag-text'})
        for elem in tag_elements:
            tag_text = self.clean_text(elem.get_text()).lower()
            # Преобразуем "Chef's Choice" -> "chef's choice", "Veggie" -> "vegetarisch"
            if 'veggie' in tag_text and 'vegetarisch' not in tags:
                tags.append('vegetarisch')
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags:
            if tag not in seen and tag:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags[:5]) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data:
            # image field
            if 'image' in recipe_data:
                img = recipe_data['image']
                if isinstance(img, str):
                    urls.append(img)
                elif isinstance(img, list):
                    urls.extend([i for i in img if isinstance(i, str)])
            
            # thumbnailUrl field
            if 'thumbnailUrl' in recipe_data:
                thumb = recipe_data['thumbnailUrl']
                if isinstance(thumb, str):
                    urls.append(thumb)
        
        # Из meta og:image
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
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": json.dumps(ingredients, ensure_ascii=False) if ingredients else None,
            "instructions": instructions,
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/hellofresh_nl
    preprocessed_dir = os.path.join("preprocessed", "hellofresh_nl")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(HelloFreshExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python hellofresh_nl.py")


if __name__ == "__main__":
    main()
