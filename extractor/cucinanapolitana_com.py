"""
Экстрактор данных рецептов для сайта cucinanapolitana.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CucinaNapolitanaExtractor(BaseRecipeExtractor):
    """Экстрактор для cucinanapolitana.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в читаемом формате, например "20 minutes" или "1 hour and 30 minutes"
        """
        if not duration or not duration.startswith('PT'):
            return None
        
        # Убираем "PT" и проверяем на корректность
        duration = duration[2:]
        
        # Проверяем на некорректные значения (например, отрицательные)
        if '-' in duration:
            return None
        
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
        
        # Формируем читаемую строку
        if hours > 0 and minutes > 0:
            return f"{hours} hour{'s' if hours > 1 else ''} and {minutes} minute{'s' if minutes != 1 else ''}"
        elif hours > 0:
            return f"{hours} hour{'s' if hours > 1 else ''}"
        elif minutes > 0:
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        
        return None
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлекает данные рецепта из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Функция для проверки типа Recipe
                def is_recipe(item):
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        return 'Recipe' in item_type
                    return item_type == 'Recipe'
                
                # Ищем Recipe в данных
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            return item
                elif isinstance(data, dict):
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if is_recipe(item):
                                return item
                    elif is_recipe(data):
                        return data
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            name = recipe_data['name']
            # Убираем длинные суффиксы после двоеточия
            if ':' in name:
                name = name.split(':')[0].strip()
            return self.clean_text(name)
        
        # Альтернативно - из заголовка страницы
        h1 = self.soup.find('h1')
        if h1:
            name = h1.get_text()
            if ':' in name:
                name = name.split(':')[0].strip()
            return self.clean_text(name)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Пробуем из JSON-LD Recipe
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data and recipe_data['description']:
            return self.clean_text(recipe_data['description'])
        
        # Пробуем из BlogPosting в @graph
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BlogPosting' and 'description' in item:
                            desc = item['description']
                            # Часто описание обрезано, берем только первое предложение
                            if '. ' in desc:
                                desc = desc.split('. ')[0] + '.'
                            return self.clean_text(desc)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            if '. ' in desc:
                desc = desc.split('. ')[0] + '.'
            return self.clean_text(desc)
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredient_list = recipe_data['recipeIngredient']
            if isinstance(ingredient_list, list):
                for ingredient_text in ingredient_list:
                    if isinstance(ingredient_text, str):
                        # Проверяем на составные ингредиенты типа "Sale e pepe q.b."
                        import html as html_module
                        ingredient_text = html_module.unescape(ingredient_text)
                        ingredient_text = self.clean_text(ingredient_text)
                        
                        # Удаляем префиксы
                        ingredient_text = re.sub(r'^[–\-—]+\s*', '', ingredient_text)
                        
                        # Проверяем на " e " (and) в конце без количества - разделяем
                        if ' e ' in ingredient_text.lower() and ('q.b.' in ingredient_text.lower() or 'opzionale' in ingredient_text.lower()):
                            # Это "Sale e pepe q.b." - разделяем на два
                            parts = re.split(r'\s+e\s+', ingredient_text, maxsplit=1, flags=re.IGNORECASE)
                            for part in parts:
                                parsed = self.parse_ingredient(part)
                                if parsed:
                                    ingredients.append(parsed)
                        else:
                            parsed = self.parse_ingredient(ingredient_text)
                            if parsed:
                                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "– 500 g di carne macinata" или "&#8211; 1 cipolla"
            
        Returns:
            dict: {"name": "carne macinata", "amount": 500, "units": "g"}
        """
        if not ingredient_text:
            return None
        
        # Декодируем HTML entities и чистим текст
        import html
        text = html.unescape(ingredient_text)
        text = self.clean_text(text)
        
        # Удаляем префиксы типа "–" или "-"
        text = re.sub(r'^[–\-—]+\s*', '', text)
        
        # Удаляем текст в скобках (например, "(pasta)" или "(opzionale)")
        text_without_parens = re.sub(r'\s*\([^)]*\)', '', text)
        
        # Паттерн для итальянского формата: "500 g di carne macinata"
        # Используем \b для границ слов, чтобы "g" не совпадало с началом "gambo"
        pattern = r'^(\d+(?:[.,]\d+)?)\s*\b(g|ml|kg|l|cucchiai|cucchiaio|spicchi|spicchio)\b\s*(?:di\s+)?(.+)$'
        
        match = re.match(pattern, text_without_parens, re.IGNORECASE)
        
        if match:
            amount_str, units, name = match.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                # Заменяем запятую на точку для числа
                amount_str = amount_str.replace(',', '.')
                try:
                    amount = float(amount_str) if '.' in amount_str else int(amount_str)
                except ValueError:
                    amount = None
            
            # Очистка названия - удаляем "di" в начале если осталось
            name = name.strip() if name else text_without_parens
            name = re.sub(r'^di\s+', '', name, flags=re.IGNORECASE)
            
            return {
                "name": name,
                "units": units if units else None,
                "amount": amount
            }
        
        # Паттерн без единиц измерения: просто число и название (например, "1 cipolla", "2 carote")
        pattern_no_unit = r'^(\d+(?:[.,]\d+)?)\s+(.+)$'
        match_no_unit = re.match(pattern_no_unit, text_without_parens)
        
        if match_no_unit:
            amount_str, name = match_no_unit.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                amount_str = amount_str.replace(',', '.')
                try:
                    amount = float(amount_str) if '.' in amount_str else int(amount_str)
                except ValueError:
                    amount = None
            
            # Удаляем "di" в начале названия если есть
            name = re.sub(r'^di\s+', '', name, flags=re.IGNORECASE)
            
            return {
                "name": name,
                "units": None,
                "amount": amount
            }
        
        # Паттерн без количества: просто название (например, "Sale e pepe q.b.")
        # Проверяем на "q.b." (quanto basta = по вкусу)
        if 'q.b.' in text_without_parens.lower() or 'opzionale' in text_without_parens.lower():
            # Удаляем q.b. и опциональное
            name = re.sub(r'\s*q\.b\.?', '', text_without_parens, flags=re.IGNORECASE)
            name = re.sub(r'\s*opzionale', '', name, flags=re.IGNORECASE)
            name = name.strip()
            
            return {
                "name": name if name else text_without_parens,
                "units": None,
                "amount": None
            }
        
        # Если паттерн не совпал, возвращаем только название
        return {
            "name": text_without_parens if text_without_parens else text,
            "units": None,
            "amount": None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        import html as html_module
        steps = []
        
        # Пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            if isinstance(instructions, list):
                step_num = 0
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        step_text = html_module.unescape(step['text'])
                        step_text = self.clean_text(step_text)
                        
                        # Удаляем HTML артефакты
                        # Удаляем id= атрибуты (поддерживаем разные кавычки: ", ', ″, ″)
                        step_text = re.sub(r'\s*id\s*=\s*["\'\u201c\u201d\u2033][^\s>]*["\'\u201c\u201d\u2033][^>]*>', '', step_text)
                        # Удаляем id= без кавычек
                        step_text = re.sub(r'\s*id\s*=\s*[^\s>]+\s*>', '', step_text)
                        # Удаляем одиночные "<" или ">" в конце/начале
                        step_text = re.sub(r'\s*[<>]+\s*$', '', step_text)
                        step_text = re.sub(r'^[<>]+\s*', '', step_text)
                        # Удаляем начальные теги типа "p" (с пробелом или без)
                        step_text = re.sub(r'^p\s*', '', step_text)
                        step_text = step_text.strip()
                        
                        # Пропускаем пустые или слишком короткие шаги
                        if len(step_text) < 10:
                            continue
                        
                        # Проверяем, не начинается ли шаг уже с номера
                        step_match = re.match(r'^(\d+)\.\s*(.+)', step_text, re.DOTALL)
                        if step_match:
                            # Уже пронумерован, берем номер
                            step_num = int(step_match.group(1))
                            step_text = step_match.group(2).strip()
                            formatted_step = f"{step_num}. {step_text}"
                        else:
                            # Добавляем номер
                            step_num += 1
                            formatted_step = f"{step_num}. {step_text}"
                        
                        steps.append(formatted_step)
                    elif isinstance(step, str):
                        step_text = html_module.unescape(step)
                        step_text = self.clean_text(step_text)
                        
                        # Удаляем HTML артефакты
                        step_text = re.sub(r'<[^>]*>', '', step_text)
                        step_text = step_text.strip()
                        
                        if len(step_text) >= 10:
                            step_num += 1
                            if not re.match(r'^\d+\.', step_text):
                                step_text = f"{step_num}. {step_text}"
                            steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            if isinstance(category, list):
                return ', '.join(category)
            return self.clean_text(category)
        
        # Пробуем из хлебных крошек
        breadcrumb_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in breadcrumb_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем @graph на BreadcrumbList
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BreadcrumbList':
                            items = item.get('itemListElement', [])
                            # Берем предпоследний элемент (перед самим рецептом)
                            if len(items) >= 2:
                                category_item = items[-2]
                                if 'item' in category_item and 'name' in category_item['item']:
                                    return self.clean_text(category_item['item']['name'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data:
            # Маппинг типов времени на ключи JSON-LD
            time_keys = {
                'prep': 'prepTime',
                'cook': 'cookTime',
                'total': 'totalTime'
            }
            
            key = time_keys.get(time_type)
            if key and key in recipe_data:
                iso_time = recipe_data[key]
                # Проверяем, что значение не пустое и корректное
                if iso_time and isinstance(iso_time, str) and iso_time.strip():
                    parsed_time = self.parse_iso_duration(iso_time)
                    if parsed_time:
                        return parsed_time
        
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
        import html as html_module
        
        # Ищем в HTML-тексте первый совет после фразы "considera questi utili suggerimenti"
        # или прямо по ключевой фразе "Usa Ingredienti di Qualità"
        html_text = str(self.soup)
        
        # Паттерн для поиска советов - ищем до точки или <br>
        patterns = [
            r'[–\-—]\s*Usa Ingredienti[^<]*?:[^<]+?\.',
            r'suggerimenti[^<]*:<br>[–\-—]\s*([^<]+?\.[^<]*?\.)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html_text, re.IGNORECASE | re.DOTALL)
            if match:
                # Берем либо всю группу, либо первую группу захвата
                if match.groups():
                    note_text = match.group(1)
                else:
                    note_text = match.group(0)
                
                # Декодируем HTML entities
                note_text = html_module.unescape(note_text)
                # Удаляем HTML теги
                note_text = re.sub(r'<[^>]+>', '', note_text)
                # Удаляем префиксы "–"
                note_text = re.sub(r'^[–\-—\s]+', '', note_text)
                # Чистим
                note_text = self.clean_text(note_text)
                
                if note_text and len(note_text) > 20:
                    return note_text
        
        # Альтернативный способ: ищем все параграфы с советами
        paragraphs = self.soup.find_all('p')
        for p in paragraphs:
            text = p.get_text()
            if 'Usa Ingredienti' in text or 'suggerimenti' in text.lower():
                # Извлекаем первый совет с ":" 
                sentences = text.split('–')
                for sentence in sentences:
                    if ':' in sentence and 'Usa Ingredienti' in sentence:
                        # Берем весь совет до следующего "–"
                        note_text = sentence.strip()
                        # Берем до конца предложения
                        if '.' in note_text:
                            # Находим первую законченную мысль (до второй точки после ":")
                            colon_idx = note_text.find(':')
                            if colon_idx > 0:
                                after_colon = note_text[colon_idx+1:]
                                # Берем первое и второе предложение
                                sentences_parts = after_colon.split('.')
                                if len(sentences_parts) >= 2:
                                    note_text = note_text[:colon_idx] + ': ' + sentences_parts[0].strip() + '.'
                        
                        note_text = self.clean_text(note_text)
                        if note_text and len(note_text) > 20:
                            return note_text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data:
            # Проверяем keywords
            if 'keywords' in recipe_data:
                keywords = recipe_data['keywords']
                if isinstance(keywords, str):
                    return keywords
                elif isinstance(keywords, list):
                    return ', '.join(keywords)
            
            # Проверяем tags
            if 'tags' in recipe_data:
                tags = recipe_data['tags']
                if isinstance(tags, str):
                    return tags
                elif isinstance(tags, list):
                    return ', '.join(tags)
        
        # Пробуем из meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Пробуем из JSON-LD
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
        
        # Также ищем в @graph для ImageObject
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'ImageObject' and 'url' in item:
                            urls.append(item['url'])
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
    """Точка входа для обработки директории с HTML-файлами"""
    import os
    
    # Определяем путь к директории с preprocessed файлами
    base_dir = Path(__file__).parent.parent
    recipes_dir = base_dir / "preprocessed" / "cucinanapolitana_com"
    
    if recipes_dir.exists() and recipes_dir.is_dir():
        process_directory(CucinaNapolitanaExtractor, str(recipes_dir))
    else:
        print(f"Директория не найдена: {recipes_dir}")
        print("Использование: python cucinanapolitana_com.py")


if __name__ == "__main__":
    main()
