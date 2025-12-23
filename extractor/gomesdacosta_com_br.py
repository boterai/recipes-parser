"""
Экстрактор данных рецептов для сайта gomesdacosta.com.br
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class GomesDaCostaExtractor(BaseRecipeExtractor):
    """Экстрактор для gomesdacosta.com.br"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Данные могут быть списком или словарем
                if isinstance(data, list):
                    # Ищем Recipe в списке
                    for item in data:
                        if isinstance(item, dict):
                            item_type = item.get('@type', '')
                            if isinstance(item_type, list) and 'Recipe' in item_type:
                                return item
                            elif item_type == 'Recipe':
                                return item
                elif isinstance(data, dict):
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and item.get('@type') == 'Recipe':
                                return item
                    
                    # Проверяем прямой тип
                    item_type = data.get('@type', '')
                    if isinstance(item_type, list) and 'Recipe' in item_type:
                        return data
                    elif item_type == 'Recipe':
                        return data
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "20 minutes" или "1 hour 30 minutes"
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
        
        # Форматируем результат
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "500g rigattoni" или "1 cebola média picada"
            
        Returns:
            dict: {"name": "rigattoni", "amount": 500, "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Специальная обработка для "a gosto" - если фраза заканчивается на "a gosto"
        # Примеры: "Sal a gosto", "Pimenta do reino a gosto"
        a_gosto_match = re.search(r'^(.+?)\s+(a gosto)$', text, re.IGNORECASE)
        if a_gosto_match:
            name = a_gosto_match.group(1).strip()
            return {
                "name": name,
                "amount": None,
                "units": "a gosto"
            }
        
        # Паттерн для извлечения количества в начале строки
        # Примеры: "500g rigattoni", "1 cebola média", "2 dentes de alho"
        # Сначала пробуем паттерн с единицами сразу после числа (500g, 2kg)
        # Обрабатываем "500 g de linguini" специально
        pattern_g_de = r'^(\d+(?:[.,]\d+)?)\s*(g|kg|mg|ml|l)\s+de\s+(.+)$'
        match = re.match(pattern_g_de, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            # Преобразуем количество
            amount_float = float(amount_str.replace(',', '.'))
            amount = int(amount_float) if amount_float == int(amount_float) else str(amount_float)
            name = name.strip() if name else ""
            
            return {
                "name": name,
                "amount": amount,
                "units": unit.lower()
            }
        
        # Паттерн для единиц сразу после числа (500g, 2kg)
        pattern1 = r'^(\d+(?:[.,]\d+)?)(g|kg|mg|ml|l)(?:\s+(.+))?$'
        match = re.match(pattern1, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            # Преобразуем количество
            amount_float = float(amount_str.replace(',', '.'))
            amount = int(amount_float) if amount_float == int(amount_float) else str(amount_float)
            name = name.strip() if name else ""
            
            return {
                "name": name,
                "amount": amount,
                "units": unit.lower()
            }
        
        # Паттерн для чисел с единицами после пробела
        # "1 xícara (chá) de ervilha", "2 latas de Atum", "4 colheres de sopa de Azeite"
        # Также обрабатываем "1 pacote de espaguete ou 500 gramas"
        pattern2 = r'^([\d\s/.,]+)?\s*(pacotes?|xícaras?(?:\s*\([^)]+\))?|colheres?(?:\s+de\s+(?:sopa|chá|sobremesa))?|latas?|unidades?|dentes?|folhas?|maços?|ramos?|pitadas?|fatias?|talos?)\s+(?:de\s+)?(.+)'
        match = re.match(pattern2, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                amount_str = amount_str.strip()
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
                    # Конвертируем в int если целое число, иначе строка
                    amount = int(total) if total == int(total) else str(total)
                else:
                    # Преобразуем в число
                    amount_str = amount_str.replace(',', '.')
                    try:
                        amount_float = float(amount_str)
                        amount = int(amount_float) if amount_float == int(amount_float) else str(amount_float)
                    except ValueError:
                        amount = None
            
            # Обработка единицы измерения
            unit = unit.strip() if unit else None
            
            # Очистка названия
            # Удаляем лишние пробелы
            name = re.sub(r'\s+', ' ', name).strip()
            
            # Убираем альтернативные варианты после "ou" (например, "espaguete ou 500 gramas")
            if ' ou ' in name.lower():
                name = name.split(' ou ')[0].strip()
            
            # Удаляем лишнюю информацию о весе в конце (например "170g")
            name = re.sub(r'\s+\d+g$', '', name, re.IGNORECASE)
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        
        # Паттерн для ингредиентов без явных единиц: "1 cebola média", "2 dentes de alho"
        pattern3 = r'^(\d+(?:[.,]\d+)?)\s+(.+)'
        match = re.match(pattern3, text, re.IGNORECASE)
        
        if match:
            amount_str, name = match.groups()
            # Преобразуем количество
            amount_float = float(amount_str.replace(',', '.'))
            amount = int(amount_float) if amount_float == int(amount_float) else str(amount_float)
            
            # Проверяем, есть ли "dentes de" в начале названия - это единица
            unit = None
            if name.startswith('dentes de ') or name.startswith('dentes '):
                unit = 'unidade'
                # Оставляем "dentes de alho" как есть в имени
            
            # Очистка названия - удаляем лишние пробелы
            name = re.sub(r'\s+', ' ', name).strip()
            
            # Если не нашли единицу, используем "unidade"
            if not unit:
                unit = "unidade"
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        
        # Если ничего не подошло, возвращаем как есть
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Альтернативный поиск в HTML
        title_tag = self.soup.find('h1')
        if title_tag:
            return self.clean_text(title_tag.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'description' in json_ld:
            desc = self.clean_text(json_ld['description'])
            if desc:
                return desc
        
        # Альтернативный поиск в meta тегах
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeIngredient' in json_ld:
            ingredients_list = json_ld['recipeIngredient']
            
            if not ingredients_list:
                return None
            
            parsed_ingredients = []
            for ingredient_text in ingredients_list:
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    parsed_ingredients.append(parsed)
            
            return json.dumps(parsed_ingredients, ensure_ascii=False) if parsed_ingredients else None
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            
            if not instructions:
                return None
            
            steps = []
            if isinstance(instructions, list):
                for item in instructions:
                    if isinstance(item, dict) and 'text' in item:
                        steps.append(self.clean_text(item['text']))
                    elif isinstance(item, str):
                        steps.append(self.clean_text(item))
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            
            if steps:
                return ' '.join(steps)
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности в формате: 202 kcal; 2/11/27"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'nutrition' in json_ld:
            nutrition = json_ld['nutrition']
            
            # Извлекаем калории
            calories = None
            if 'calories' in nutrition:
                cal_text = nutrition['calories']
                # Извлекаем только число
                cal_match = re.search(r'(\d+)', str(cal_text))
                if cal_match:
                    calories = cal_match.group(1)
            
            # Извлекаем БЖУ (белки/жиры/углеводы)
            protein = None
            fat = None
            carbs = None
            
            if 'proteinContent' in nutrition:
                prot_text = nutrition['proteinContent']
                prot_match = re.search(r'(\d+)', str(prot_text))
                if prot_match:
                    protein = prot_match.group(1)
            
            if 'fatContent' in nutrition:
                fat_text = nutrition['fatContent']
                fat_match = re.search(r'(\d+)', str(fat_text))
                if fat_match:
                    fat = fat_match.group(1)
            
            if 'carbohydrateContent' in nutrition:
                carb_text = nutrition['carbohydrateContent']
                carb_match = re.search(r'(\d+)', str(carb_text))
                if carb_match:
                    carbs = carb_match.group(1)
            
            # Форматируем: "202 kcal; 2/11/27"
            if calories and protein and fat and carbs:
                return f"{calories} kcal; {protein}/{fat}/{carbs}"
            elif calories:
                return f"{calories} kcal"
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeCategory' in json_ld:
            category = json_ld['recipeCategory']
            # Может быть строкой с несколькими категориями через запятую
            if isinstance(category, str):
                return self.clean_text(category)
            elif isinstance(category, list):
                return ', '.join([self.clean_text(c) for c in category if c])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # На сайте gomesdacosta.com.br нет специального поля для заметок в JSON-LD
        # Можно попробовать найти в HTML, но в примерах его нет
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if keywords and isinstance(keywords, str):
                # Очищаем и возвращаем
                return self.clean_text(keywords)
            elif keywords and isinstance(keywords, list):
                return ', '.join([self.clean_text(k) for k in keywords if k])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        json_ld = self._get_json_ld_data()
        
        urls = []
        
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
        # Также проверяем meta теги
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)
        
        if urls:
            # Удаляем дубликаты, сохраняя порядок
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
            "nutrition_info": self.extract_nutrition_info(),
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
    # Обрабатываем папку preprocessed/gomesdacosta_com_br
    preprocessed_dir = os.path.join("preprocessed", "gomesdacosta_com_br")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(GomesDaCostaExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python gomesdacosta_com_br.py")


if __name__ == "__main__":
    main()
