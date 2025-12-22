"""
Экстрактор данных рецептов для сайта 24kitchen.nl
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class Kitchen24Extractor(BaseRecipeExtractor):
    """Экстрактор для 24kitchen.nl"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Проверяем @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                
                # Данные могут быть списком или словарем
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "P0DT0H15M"
            
        Returns:
            Время в формате "20 minutes" или "1 hour 30 minutes"
        """
        if not duration:
            return None
        
        # Убираем "P" и разбиваем по "T"
        duration = duration.replace('P', '')
        
        # Обрабатываем формат P0DT0H15M (дни + время)
        if 'D' in duration:
            parts = duration.split('T')
            if len(parts) == 2:
                duration = parts[1]  # Берем только часть после T
            else:
                duration = duration.replace('D', '')
        
        if duration.startswith('T'):
            duration = duration[1:]  # Убираем "T"
        
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
        if hours > 0 and minutes > 0:
            return f"{hours * 60 + minutes} minutes"
        elif hours > 0:
            return f"{hours * 60} minutes"
        elif minutes > 0:
            return f"{minutes} minutes"
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'name' in json_ld:
            name = self.clean_text(json_ld['name'])
            # Убираем суффикс " recept" если есть
            name = re.sub(r'\s+recept\s*$', '', name, flags=re.IGNORECASE)
            return name
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            name = self.clean_text(og_title['content'])
            name = re.sub(r'\s+recept\s*$', '', name, flags=re.IGNORECASE)
            return name
        
        # Из h1
        h1 = self.soup.find('h1')
        if h1:
            name = self.clean_text(h1.get_text())
            name = re.sub(r'\s+recept\s*$', '', name, flags=re.IGNORECASE)
            return name
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Сначала пробуем извлечь из HTML (более структурировано)
        # Ищем все списки ингредиентов
        ing_lists = self.soup.find_all('ul', class_='list-recipe-ingredients')
        
        if ing_lists:
            for ing_list in ing_lists:
                # Проверяем заголовок секции - пропускаем "Extra nodig" (оборудование)
                prev_h3 = None
                prev_sibling = ing_list.find_previous_sibling()
                while prev_sibling:
                    if prev_sibling.name == 'h3':
                        prev_h3 = self.clean_text(prev_sibling.get_text()).lower()
                        break
                    prev_sibling = prev_sibling.find_previous_sibling()
                
                # Пропускаем секции с оборудованием
                if prev_h3 and 'extra nodig' in prev_h3:
                    continue
                
                items = ing_list.find_all('li', class_='recipe-ingredient')
                
                for item in items:
                    amount_elem = item.find('span', class_='amount')
                    unit_elem = item.find('span', class_='unit')
                    ing_elem = item.find('span', class_='ingredient')
                    
                    if ing_elem:
                        name = self.clean_text(ing_elem.get_text())
                        amount = None
                        unit = None
                        
                        if amount_elem:
                            amount_text = amount_elem.get_text().strip()
                            # Преобразуем в число, если возможно
                            try:
                                amount = float(amount_text) if '.' in amount_text else int(amount_text)
                            except ValueError:
                                amount = amount_text
                        
                        if unit_elem:
                            unit_text = self.clean_text(unit_elem.get_text())
                            unit = unit_text if unit_text else None
                        
                        if name:
                            # Убираем утварь/оборудование
                            if not any(keyword in name.lower() for keyword in ['vorm', 'satéprikker', 'bakpapier', 'pan', 'keukentouw', 'braadslee', 'thermometer']):
                                ingredients.append({
                                    "name": name,
                                    "units": unit,
                                    "amount": amount
                                })
        
        # Если не нашли в HTML, пробуем JSON-LD
        if not ingredients:
            json_ld = self._get_json_ld_data()
            if json_ld and 'recipeIngredient' in json_ld:
                for ing_text in json_ld['recipeIngredient']:
                    # Парсим строку ингредиента
                    parsed = self.parse_ingredient_text(ing_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient_text(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента из JSON-LD
        
        Args:
            text: строка вида "150 g bloem" или "2 eieren"
            
        Returns:
            dict с полями name, units, amount
        """
        if not text:
            return None
        
        text = self.clean_text(text)
        
        # Пропускаем утварь/оборудование
        if any(keyword in text.lower() for keyword in ['vorm', 'satéprikker', 'bakpapier', 'pan']):
            return None
        
        # Паттерн: количество + единица + название
        # Примеры: "150 g bloem", "2 tl bakpoeder", "3 rijpe bananen"
        pattern = r'^(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l|tl|el|snufje|piece|stuks?|stuk)?(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Преобразуем количество
            amount = None
            if amount_str:
                amount_str = amount_str.replace(',', '.')
                try:
                    amount = float(amount_str) if '.' in amount_str else int(amount_str)
                except ValueError:
                    amount = amount_str
            
            # Очищаем название
            name = name.strip() if name else text
            unit = unit.strip() if unit else None
            
            return {
                "name": name,
                "units": unit,
                "amount": amount
            }
        
        # Если паттерн не совпал, возвращаем только название
        return {
            "name": text,
            "units": None,
            "amount": None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            
            if isinstance(instructions, list):
                # Объединяем все шаги в одну строку
                steps = []
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        steps.append(step['text'])
                    elif isinstance(step, str):
                        steps.append(step)
                
                return self.clean_text(' '.join(steps))
            elif isinstance(instructions, str):
                return self.clean_text(instructions)
        
        # Альтернативно - из HTML
        instructions_section = self.soup.find('div', class_=re.compile(r'recipe.*instructions?', re.I))
        if instructions_section:
            steps = []
            step_items = instructions_section.find_all(['li', 'p'])
            
            for item in step_items:
                step_text = self.clean_text(item.get_text())
                if step_text:
                    steps.append(step_text)
            
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'nutrition' in json_ld:
            nutrition = json_ld['nutrition']
            
            # Извлекаем калории
            calories = None
            if 'calories' in nutrition:
                cal_text = nutrition['calories']
                cal_match = re.search(r'(\d+)', str(cal_text))
                if cal_match:
                    calories = cal_match.group(1)
            
            # Извлекаем БЖУ
            protein = None
            fat = None
            carbs = None
            
            if 'proteinContent' in nutrition:
                prot_match = re.search(r'(\d+)', str(nutrition['proteinContent']))
                if prot_match:
                    protein = prot_match.group(1)
            
            if 'fatContent' in nutrition:
                fat_match = re.search(r'(\d+)', str(nutrition['fatContent']))
                if fat_match:
                    fat = fat_match.group(1)
            
            if 'carbohydrateContent' in nutrition:
                carb_match = re.search(r'(\d+)', str(nutrition['carbohydrateContent']))
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
            
            if isinstance(category, list):
                # Берем первую или основную категорию
                return self.clean_text(category[0]) if category else None
            elif isinstance(category, str):
                return self.clean_text(category)
        
        # Альтернативно - из хлебных крошек
        breadcrumbs = self.soup.find('nav', attrs={'aria-label': 'breadcrumb'})
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())
        
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
        
        # Если нет cookTime в JSON-LD, пробуем найти в инструкциях
        # Ищем фразы типа "bak 45 minuten", "in de oven voor 60 minuten", "1 uur in de oven"
        instructions = self.extract_instructions()
        if instructions:
            # Паттерны для поиска времени приготовления в духовке
            # Сначала проверяем часы
            hour_pattern = r'(?:in de oven|zet|bak|gaar)(?:[^.]{0,30}?)(\d+)\s*(?:uur|u\b)'
            match = re.search(hour_pattern, instructions.lower())
            if match:
                hours = int(match.group(1))
                minutes = hours * 60
                return f"{minutes} minutes"
            
            # Затем минуты
            minute_patterns = [
                r'(?:in de oven|bak|gaar)(?:[^.]{0,30}?)(\d+)\s*(?:minuten|minuut)',
                r'(?:bak|gaar)(?:[^.]{0,30}?)(\d+)\s*min(?:uten)?'
            ]
            
            for pattern in minute_patterns:
                match = re.search(pattern, instructions.lower())
                if match:
                    minutes = int(match.group(1))
                    # Проверяем, что это разумное время для приготовления (не prep time)
                    if minutes >= 15:  # Минимум 15 минут для cook time
                        return f"{minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Сначала пытаемся вычислить из prep_time и cook_time
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        
        if prep_time and cook_time:
            # Извлекаем минуты из строк
            prep_match = re.search(r'(\d+)', prep_time)
            cook_match = re.search(r'(\d+)', cook_time)
            
            if prep_match and cook_match:
                prep_minutes = int(prep_match.group(1))
                cook_minutes = int(cook_match.group(1))
                
                total = prep_minutes + cook_minutes
                if total > 0:
                    return f"{total} minutes"
        
        # Если не удалось вычислить, проверяем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'totalTime' in json_ld:
            total_from_ld = self.parse_iso_duration(json_ld['totalTime'])
            if total_from_ld:
                return total_from_ld
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем параграфы с конкретными советами/примечаниями
        # Сначала пробуем найти параграф начинающийся с ключевых слов
        text_sections = self.soup.find_all('div', class_='text-formatted')
        
        best_candidate = None
        best_score = 0
        
        for section in text_sections:
            # Пропускаем секции с видео-плеером
            if any('jw-' in str(c) for c in section.get('class', [])):
                continue
            
            # Ищем параграфы внутри
            paragraphs = section.find_all('p')
            for p in paragraphs:
                text = self.clean_text(p.get_text())
                
                # Фильтруем по длине
                if not text or not (20 <= len(text) <= 300):
                    continue
                
                # Пропускаем служебные фразы
                skip_phrases = [
                    'met een account',
                    'log in',
                    'favorieten',
                    'bewaarde recepten',
                    'meldt je aan',
                    'profiter',
                    'beoordelen'
                ]
                
                if any(phrase in text.lower() for phrase in skip_phrases):
                    continue
                
                # Считаем score - параграфы с советами обычно содержат эти слова
                score = 0
                tip_keywords = [
                    ('gebruik', 5),  # "Gebruik altijd...", "Gebruik overrijpe..."
                    ('voor', 3),     # "Voor smeuïg...", "Voor een..."
                    ('tip', 10),     # "Tip: ..."
                    ('altijd', 5),
                    ('voeg', 3),
                    ('smeuïg', 5),
                    ('romig', 5),
                    ('kernthermometer', 10),
                    ('overrijpe', 5),
                    ('uitdroging', 5)
                ]
                
                for keyword, weight in tip_keywords:
                    if keyword in text.lower():
                        score += weight
                
                # Приоритет параграфам, начинающимся с ключевых слов
                if text.lower().startswith(('gebruik', 'voor', 'tip', 'voeg')):
                    score += 10
                
                if score > best_score:
                    best_score = score
                    best_candidate = text
        
        return best_candidate if best_score >= 5 else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем теги в ссылках с классом 'tag'
        tag_links = self.soup.find_all('a', class_=lambda x: x and any('tag' in str(c).lower() for c in (x if isinstance(x, list) else [x])))
        
        for tag_link in tag_links:
            # Проверяем, что это не социальная ссылка
            classes = tag_link.get('class', [])
            if any('socials' in str(c).lower() for c in classes):
                continue
            
            tag_text = self.clean_text(tag_link.get_text())
            
            # Пропускаем служебные теги и "externe link"
            if tag_text and tag_text.lower() not in tags:
                if 'externe link' not in tag_text.lower() and 'instagram' not in tag_text.lower():
                    tags.append(tag_text.lower())
        
        # Если не нашли теги, пробуем извлечь из diet info в JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and not tags:
            # Проверяем suitableForDiet
            if 'suitableForDiet' in json_ld:
                diet = json_ld['suitableForDiet']
                if 'vegetarian' in diet.lower():
                    tags.append('vegetarisch')
            
            # Добавляем категории как теги
            if 'recipeCategory' in json_ld:
                categories = json_ld['recipeCategory']
                if isinstance(categories, list):
                    for cat in categories:
                        cat_clean = self.clean_text(cat).lower()
                        if cat_clean and cat_clean not in tags:
                            tags.append(cat_clean)
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Извлекаем из JSON-LD
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            
            if isinstance(img, dict) and 'url' in img:
                urls.append(img['url'])
            elif isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, dict) and 'url' in item:
                        urls.append(item['url'])
                    elif isinstance(item, str):
                        urls.append(item)
        
        # Также ищем в meta тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)
        
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
    """Точка входа для обработки HTML файлов 24kitchen.nl"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "24kitchen_nl")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка файлов из директории: {preprocessed_dir}")
        process_directory(Kitchen24Extractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python 24kitchen_nl.py")


if __name__ == "__main__":
    main()
