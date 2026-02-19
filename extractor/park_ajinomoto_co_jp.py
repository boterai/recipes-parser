"""
Экстрактор данных рецептов для сайта park.ajinomoto.co.jp
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ParkAjinomotoCoJpExtractor(BaseRecipeExtractor):
    """Экстрактор для park.ajinomoto.co.jp"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах с единицей измерения, например "90 minutes"
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
    
    def get_json_ld_data(self) -> Optional[dict]:
        """Извлечение JSON-LD данных рецепта"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe тип
                if isinstance(data, dict):
                    recipe_type = data.get('@type', '')
                    if recipe_type == 'recipe' or recipe_type == 'Recipe':
                        return data
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа "のレシピ・作り方・献立｜レシピ大百科"
            title = re.sub(r'のレシピ.*$', '', title)
            title = re.sub(r'\s*:\s*.*$', '', title)
            return self.clean_text(title)
        
        # Ищем в title теге
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            title = re.sub(r'のレシピ.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld and 'description' in json_ld:
            desc = json_ld['description']
            # Удаляем стандартный суффикс с рекламой сайта
            desc = re.sub(r'たべたい、つくりたい.*$', '', desc)
            desc = self.clean_text(desc)
            if desc:
                return desc
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            desc = re.sub(r'たべたい、つくりたい.*$', '', desc)
            return self.clean_text(desc)
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            desc = re.sub(r'たべたい、つくりたい.*$', '', desc)
            return self.clean_text(desc)
        
        return None
    
    def parse_ingredient_text(self, ingredient_text: str) -> Dict[str, Optional[str]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "ごぼう 1本（150g）" или "片栗粉 大さじ1"
            
        Returns:
            dict: {"name": "ごぼう", "amount": "1", "unit": "本（150g）"}
        """
        if not ingredient_text:
            return {"name": None, "amount": None, "unit": None}
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Убираем префиксы типа "A" для групп ингредиентов
        text = re.sub(r'^[A-Z]', '', text).strip()
        
        # Паттерн: название + пробел + количество + единица
        # Примеры: "ごぼう 1本（150g）", "片栗粉 大さじ1", "牛乳 130ml"
        
        # Разделяем по последнему пробелу (название от количества)
        parts = text.rsplit(None, 1)  # rsplit with maxsplit=1
        
        if len(parts) == 2:
            name = parts[0]
            quantity_part = parts[1]
            
            # Пытаемся разделить количество на amount и unit
            # Паттерны: "1本（150g）", "大さじ1", "130ml", "少々", "適量"
            
            # Если количество начинается с цифры
            amount_match = re.match(r'^([\d./]+)\s*(.*)$', quantity_part)
            if amount_match:
                amount = amount_match.group(1)
                unit = amount_match.group(2) if amount_match.group(2) else None
                return {"name": name, "amount": amount, "unit": unit}
            
            # Если это текстовое количество типа "大さじ1", "小さじ2"
            measure_match = re.match(r'^(大さじ|小さじ|カップ)([\d./]+)\s*(.*)$', quantity_part)
            if measure_match:
                unit = measure_match.group(1)
                amount = measure_match.group(2)
                extra = measure_match.group(3) if measure_match.group(3) else None
                if extra:
                    unit = f"{unit}{extra}" if unit else extra
                return {"name": name, "amount": amount, "unit": unit}
            
            # Если это только единица без числа ("少々", "適量")
            return {"name": name, "amount": quantity_part, "unit": None}
        
        # Если не удалось разделить, возвращаем все как название
        return {"name": text, "amount": None, "unit": None}
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Приоритет 1: HTML структура с раздельными name/quantity (обычная версия)
        ingredient_list = self.soup.find('ul', class_='recipeIngredients__list')
        if not ingredient_list:
            # Приоритет 2: Версия для печати
            ingredient_list = self.soup.find('ul', class_='printIngredients__list')
        
        if ingredient_list:
            # Для обычной версии
            items = ingredient_list.find_all('li', class_='recipeIngredients__list-item')
            if not items:
                # Для версии печати
                items = ingredient_list.find_all('li', class_='printIngredients__list-item')
            
            for item in items:
                # Обычная версия
                name_elem = item.find('span', class_='recipeIngredients__name')
                quantity_elem = item.find('span', class_='recipeIngredients__quantity')
                
                # Версия для печати
                if not name_elem:
                    name_elem = item.find('div', class_='printIngredients__name')
                if not quantity_elem:
                    quantity_elem = item.find('span', class_='printIngredients__quantity')
                
                if name_elem and quantity_elem:
                    name = self.clean_text(name_elem.get_text())
                    # Убираем префиксы A, B, C для групп
                    name = re.sub(r'^[A-Z]', '', name).strip()
                    quantity = self.clean_text(quantity_elem.get_text())
                    
                    # Парсим количество на amount и unit
                    amount = None
                    unit = None
                    
                    # Если количество начинается с цифры
                    amount_match = re.match(r'^([\d./]+)\s*(.*)$', quantity)
                    if amount_match:
                        amount = amount_match.group(1)
                        unit = amount_match.group(2) if amount_match.group(2) else None
                    else:
                        # Если это текстовое количество типа "大さじ1", "小さじ2"
                        measure_match = re.match(r'^(大さじ|小さじ|カップ)([\d./]+)\s*(.*)$', quantity)
                        if measure_match:
                            unit = measure_match.group(1)
                            amount = measure_match.group(2)
                            extra = measure_match.group(3) if measure_match.group(3) else None
                            if extra:
                                unit = f"{unit}{extra}" if unit else extra
                        else:
                            # Если это только единица без числа ("少々", "適量")
                            amount = quantity
                            unit = None
                    
                    ingredients.append({
                        "name": name,
                        "amount": amount,
                        "unit": unit
                    })
        
        # Если не нашли в HTML, пробуем JSON-LD
        if not ingredients:
            json_ld = self.get_json_ld_data()
            if json_ld and 'recipeIngredient' in json_ld:
                for ing_text in json_ld['recipeIngredient']:
                    parsed = self.parse_ingredient_text(ing_text)
                    if parsed['name']:
                        ingredients.append({
                            "name": parsed['name'],
                            "amount": parsed['amount'],
                            "unit": parsed['unit']
                        })
        
        # Возвращаем как JSON строку
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        steps = []
        
        # Сначала пробуем JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, str):
                        # Удаляем HTML теги и японские маркеры типа "（１）"
                        step_text = re.sub(r'<br\s*/?>', ' ', step)
                        step_text = re.sub(r'<[^>]+>', '', step_text)
                        step_text = re.sub(r'^[（(]?\d+[）)]?\s*', '', step_text)
                        step_text = self.clean_text(step_text)
                        if step_text:
                            steps.append(f"{idx}. {step_text}")
        
        # Если не нашли в JSON-LD, пробуем HTML (обычная версия)
        if not steps:
            process_list = self.soup.find_all('li', class_='recipeProcess')
            if not process_list:
                # Версия для печати
                process_list = self.soup.find_all('li', class_='PrintProcesses__list-item')
            
            for idx, process_item in enumerate(process_list, 1):
                # Обычная версия
                content = process_item.find('div', class_='recipeProcess__content')
                if not content:
                    # Версия для печати
                    content = process_item.find('div', class_='PrintProcesses__content')
                
                if content:
                    # Извлекаем текст, пропуская номер шага
                    step_text = content.get_text(separator=' ', strip=True)
                    # Убираем номер в начале
                    step_text = re.sub(r'^\d+\s+', '', step_text)
                    step_text = self.clean_text(step_text)
                    if step_text:
                        steps.append(f"{idx}. {step_text}")
        
        return '\n'.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld and 'recipeCuisine' in json_ld:
            return self.clean_text(json_ld['recipeCuisine'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # В этом сайте обычно только totalTime, но проверим prepTime
        json_ld = self.get_json_ld_data()
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self.get_json_ld_data()
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        # Из HTML версии для печати
        required_time = self.soup.find('div', class_='requiredTime__main')
        if required_time:
            time_text = required_time.get_text(strip=True)
            # Формат: "15分" -> "15 minutes"
            time_match = re.search(r'(\d+)', time_text)
            if time_match:
                minutes = time_match.group(1)
                return f"{minutes} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями в конце инструкций
        # Иногда есть текст после основных шагов, начинающийся с "*" или "＊"
        json_ld = self.get_json_ld_data()
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, str):
                        # Ищем строки, начинающиеся с * или ＊
                        if step.strip().startswith('*') or step.strip().startswith('＊'):
                            note = re.sub(r'^[*＊]\s*', '', step)
                            note = re.sub(r'<br\s*/?>', ' ', note)
                            note = re.sub(r'<[^>]+>', '', note)
                            return self.clean_text(note)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем в JavaScript переменной s.recipeHashTags
        scripts = self.soup.find_all('script', type='text/javascript')
        for script in scripts:
            if not script.string:
                continue
            
            # Ищем строку: s.recipeHashTags = '...'
            match = re.search(r"s\.recipeHashTags\s*=\s*['\"]([^'\"]+)['\"]", script.string)
            if match:
                tags_string = match.group(1)
                tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
                return ', '.join(tags_list)
        
        # Альтернативно: из HTML
        tags_list = self.soup.find('ul', class_='recipeCardKeyWordHashTags__list')
        if tags_list:
            tag_items = tags_list.find_all('li', class_='recipeCardKeyWordHashTags__list-item')
            for tag_item in tag_items:
                tag_name = tag_item.find('span', class_='hashTag__Name')
                if tag_name:
                    tag_text = self.clean_text(tag_name.get_text())
                    # Убираем символ # в начале
                    tag_text = re.sub(r'^[#＃]\s*', '', tag_text)
                    if tag_text:
                        tags.append(tag_text)
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Из og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Из JSON-LD
        json_ld = self.get_json_ld_data()
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                if img not in urls:
                    urls.append(img)
            elif isinstance(img, list):
                for i in img:
                    if isinstance(i, str) and i not in urls:
                        urls.append(i)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
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
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()  # Already returns JSON string
        instructions = self.extract_instructions()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,  # Already JSON string from extract_ingredients()
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
    # Обрабатываем папку preprocessed/park_ajinomoto_co_jp
    preprocessed_dir = os.path.join("preprocessed", "park_ajinomoto_co_jp")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ParkAjinomotoCoJpExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python park_ajinomoto_co_jp.py")


if __name__ == "__main__":
    main()
