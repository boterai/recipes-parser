"""
Экстрактор данных рецептов для сайта vmgonline.lt
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class VmgonlineLtExtractor(BaseRecipeExtractor):
    """Экстрактор для vmgonline.lt"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в читаемом формате, например "90 minutes" или "1 hour 30 minutes"
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
        
        # Форматируем в читаемый вид
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
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем, является ли это Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'name' in recipe_data:
            name = recipe_data['name']
            # Убираем префиксы типа "#Bemėsos. "
            name = re.sub(r'^#[^\s.]+\.\s*', '', name)
            # Убираем суффиксы типа " (Receptas)"
            name = re.sub(r'\s*\(Receptas\)\s*$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        # Fallback: извлекаем из H1 или title
        h1 = self.soup.find('h1')
        if h1:
            name = h1.get_text()
            # Убираем суффиксы типа " (Receptas)"
            name = re.sub(r'\s*\(Receptas\)\s*$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        title = self.soup.find('title')
        if title:
            name = title.get_text()
            # Убираем суффиксы и префиксы
            name = re.sub(r'\s*\(Receptas\)\s*.*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\s*VMGonline\s*$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Fallback: извлекаем из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Убираем длинные суффиксы после точки если есть
            parts = desc.split('.')
            if len(parts) > 2:
                # Берем первые 2 предложения
                desc = '. '.join(parts[:2]) + '.'
            return self.clean_text(desc)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "500 g lašišos filė" или "10–12 savojinių kopūstų lapų"
            
        Returns:
            dict: {"name": "...", "amount": "...", "units": "..."} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: 
        # "500 g lašišos filė" -> amount=500, unit=g, name=lašišos filė
        # "10–12 savojinių kopūstų lapų" -> amount=10–12, unit=None, name=savojinių kopūstų lapų
        # "2 šaukštų smulkintų krapų" -> amount=2, unit=šaukštų, name=smulkintų krapų
        # "Žiupsnelio tarkuotos citrinos žievelės" -> amount=žiupsnelio, unit=None, name=tarkuotos citrinos žievelės
        
        # Список известных единиц измерения
        known_units = {
            'g', 'ml', 'l', 'kg', 'tbsp', 'tsp', 'pcs', 'vnt', 'vnt.',
            'šaukštų', 'šaukšto', 'šaukštelis', 'šaukštas', 'valgomųjų', 'arbatinių', 'puodelių', 'puodelio'
        }
        
        # Сначала пробуем паттерн с текстовым количеством в начале (Žiupsnelio, Šlakelio)
        pattern_text_amount = r'^([A-ZĄČĘĖĮŠŲŪŽ][^\s]+o)\s+(.+)$'
        match = re.match(pattern_text_amount, text)
        
        if match:
            amount_word, name = match.groups()
            # Проверяем, что это действительно количественное слово (заканчивается на -io или -elio)
            if amount_word.lower() in ['žiupsnelio', 'šlakelio', 'saujos']:
                return {
                    "name": name.strip(),
                    "units": None,
                    "amount": amount_word.lower()
                }
        
        # Затем пробуем паттерн с числовым количеством и единицей
        pattern_with_unit = r'^([\d\s\-–—½¼¾⅓⅔.,]+)\s+(\S+)\s+(.+)$'
        match = re.match(pattern_with_unit, text, re.IGNORECASE)
        
        if match:
            amount_str, potential_unit, name = match.groups()
            
            # Проверяем, является ли это известной единицей измерения
            if potential_unit.lower() in known_units:
                # Конвертируем amount в число если возможно
                amount = self._convert_amount(amount_str)
                return {
                    "name": name.strip(),
                    "units": potential_unit.strip(),
                    "amount": amount
                }
            else:
                # Если не известная единица, то это часть названия
                amount = self._convert_amount(amount_str)
                return {
                    "name": (potential_unit + ' ' + name).strip(),
                    "units": None,
                    "amount": amount
                }
        
        # Пробуем только число в начале без единицы
        pattern_number = r'^([\d\s\-–—½¼¾⅓⅔.,]+)\s+(.+)$'
        match = re.match(pattern_number, text)
        
        if match:
            amount_str, name = match.groups()
            amount = self._convert_amount(amount_str)
            return {
                "name": name.strip(),
                "units": None,
                "amount": amount
            }
        
        # Если ничего не совпало, возвращаем весь текст как название
        return {
            "name": text,
            "units": None,
            "amount": None
        }
    
    def _convert_amount(self, amount_str: str) -> any:
        """Конвертирует строку количества в число если возможно"""
        if not amount_str:
            return None
        
        amount_str = amount_str.strip()
        
        # Если содержит диапазон (–, -, —), оставляем как строку
        if '–' in amount_str or '—' in amount_str:
            return amount_str
        
        # Если содержит дробь (½, ¼, etc), оставляем как строку
        if any(c in amount_str for c in '½¼¾⅓⅔'):
            return amount_str
        
        # Пробуем конвертировать в float/int
        try:
            # Заменяем запятую на точку для десятичных чисел
            normalized = amount_str.replace(',', '.')
            
            # Пробуем float
            num = float(normalized)
            
            # Если это целое число, возвращаем int
            if num.is_integer():
                return int(num)
            
            return num
        except (ValueError, AttributeError):
            # Если не удалось конвертировать, возвращаем строку
            return amount_str
    
    def _extract_ingredients_from_html(self) -> Optional[str]:
        """Извлечение ингредиентов из HTML текста (fallback)"""
        text = self.soup.get_text()
        
        # Паттерны для поиска начала секции ингредиентов
        patterns = [
            r'Įdarytiems grybams pagaminti reikia:',
            r'Kokosų ir vištienos sriubai paruošti reikia:',
            r'pagaminti reikia:',
            r'paruošti reikia:',
            r'Reikės:',
            r'reikia:'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                # Найдем текст после этого паттерна
                start_idx = match.end()
                
                # Найдем конец списка ингредиентов (обычно начинается с заглавной буквы инструкции)
                # Ищем первое предложение, которое начинается с глагола в повелительном наклонении
                remaining_text = text[start_idx:start_idx+1500]
                
                # Ищем конец ингредиентов - обычно это первое предложение с глаголом
                # Типичные начала инструкций: Išskobkite, Kepkite, Sudėkite, Supilkite, Citrinžolę
                instruction_pattern = r'(?<!\d\s)([A-ZĄČĘĖĮŠŲŪŽ][a-ząčęėįšųūž]+(?:kite|inkite|ykite|okite|ėkite))'
                inst_match = re.search(instruction_pattern, remaining_text)
                
                if inst_match:
                    ingredient_text = remaining_text[:inst_match.start()].strip()
                else:
                    # Если не нашли, берем первые 500 символов
                    ingredient_text = remaining_text[:500].strip()
                
                # Парсим ингредиенты из текста
                ingredients = self._parse_ingredient_list_from_text(ingredient_text)
                
                if ingredients:
                    return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def _parse_ingredient_list_from_text(self, text: str) -> list:
        """Парсинг списка ингредиентов из сплошного текста"""
        ingredients = []
        
        # Заменяем неразрывные пробелы на переносы строк для разделения
        text = text.replace('\xa0', '\n').replace('\u00a0', '\n')
        
        # Разделяем по переносам строк (если есть)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        # Если получилось разделить на строки, обрабатываем каждую
        if len(lines) > 1:
            for line in lines:
                parsed = self.parse_ingredient(line)
                if parsed and parsed.get('name') and len(parsed.get('name', '')) > 1:
                    ingredients.append(parsed)
        else:
            # Если разделения не произошло, текст слит воедино
            # Вставляем пробелы перед числами, которые идут сразу после букв
            text = re.sub(r'([a-ząčęėįšųūž])(\d)', r'\1 \2', text)
            
            # Разделяем по паттерну: число (или число-диапазон) + пробел + текст
            parts = re.split(r'(?=\d+(?:\s*[-–—]\s*\d+)?\s+[a-ząčęėįšųūž])', text)
            
            for part in parts:
                part = part.strip()
                if not part or len(part) < 3:
                    continue
                
                # Парсим ингредиент
                parsed = self.parse_ingredient(part)
                if parsed and parsed.get('name') and len(parsed.get('name', '')) > 1:
                    ingredients.append(parsed)
        
        return ingredients
    
    def _extract_instructions_from_html(self) -> Optional[str]:
        """Извлечение инструкций из HTML текста (fallback)"""
        text = self.soup.get_text()
        
        # Сначала ищем нумерованные инструкции (1. 2. 3. и т.д.)
        numbered_pattern = r'(\d+\.\s+[A-ZĄČĘĖĮŠŲŪŽ][^.]+\.)'
        numbered_matches = re.findall(numbered_pattern, text, re.DOTALL)
        
        if numbered_matches and len(numbered_matches) >= 2:
            # Нашли нумерованные инструкции
            # Объединяем их и очищаем
            instructions_text = ' '.join(numbered_matches)
            
            # Убираем нумерацию (опционально, в зависимости от требований)
            # instructions_text = re.sub(r'^\d+\.\s+', '', instructions_text, flags=re.MULTILINE)
            
            # Очищаем от лишнего
            end_patterns = [
                r'Gardžių atradimų',
                r'Žymės:',
                r'peržiūros',
                r'Susiję įrašai'
            ]
            
            for end_pattern in end_patterns:
                end_match = re.search(end_pattern, instructions_text)
                if end_match:
                    instructions_text = instructions_text[:end_match.start()]
            
            instructions_text = self.clean_text(instructions_text)
            return instructions_text if instructions_text else None
        
        # Если нумерованных не нашли, ищем паттерны для ненумерованных инструкций
        instruction_patterns = [
            r'Išskobkite pievagrybių kepurėles',
            r'Citrinžolę pamuškite',
            r'(?:^|\n)([A-ZĄČĘĖĮŠŲŪŽ][a-ząčęėįšųūž]+(?:kite|inkite|ykite|okite|ėkite))'
        ]
        
        for pattern in instruction_patterns:
            match = re.search(pattern, text)
            if match:
                start_idx = match.start()
                
                # Берем текст от начала инструкций
                remaining_text = text[start_idx:start_idx+2000]
                
                # Ищем конец инструкций
                end_patterns = [
                    r'Gardžių atradimų',
                    r'Žymės:',
                    r'peržiūros',
                    r'Susiję įrašai'
                ]
                
                end_idx = len(remaining_text)
                for end_pattern in end_patterns:
                    end_match = re.search(end_pattern, remaining_text)
                    if end_match:
                        end_idx = min(end_idx, end_match.start())
                
                instructions_text = remaining_text[:end_idx].strip()
                instructions_text = self.clean_text(instructions_text)
                
                return instructions_text if instructions_text else None
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredient_list = recipe_data['recipeIngredient']
            
            if isinstance(ingredient_list, list):
                ingredients = []
                for ingredient_text in ingredient_list:
                    if isinstance(ingredient_text, str):
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
                
                return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
        
        # Fallback: извлечение из HTML текста
        return self._extract_ingredients_from_html()
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            
            if isinstance(instructions, list):
                steps = []
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        steps.append(step['text'])
                    elif isinstance(step, str):
                        steps.append(step)
                
                if steps:
                    # Объединяем шаги через пробел
                    return ' '.join(steps)
            elif isinstance(instructions, str):
                return self.clean_text(instructions)
        
        # Fallback: извлечение из HTML текста
        return self._extract_instructions_from_html()
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            return self.clean_text(recipe_data['recipeCategory'])
        
        # Можно попробовать извлечь из keywords или других полей
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'prepTime' in recipe_data:
            iso_time = recipe_data['prepTime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'cookTime' in recipe_data:
            iso_time = recipe_data['cookTime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'totalTime' in recipe_data:
            iso_time = recipe_data['totalTime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # В vmgonline.lt нет явного поля для заметок в JSON-LD
        # Можно попробовать найти в HTML или вернуть None
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Разделяем по запятой и очищаем
                tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                return ', '.join(tags) if tags else None
            elif isinstance(keywords, list):
                return ', '.join([str(k) for k in keywords if k])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        recipe_data = self._get_recipe_json_ld()
        
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
    """
    Обработка всех HTML файлов в директории preprocessed/vmgonline_lt
    """
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join("preprocessed", "vmgonline_lt")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(VmgonlineLtExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python vmgonline_lt.py")


if __name__ == "__main__":
    main()
