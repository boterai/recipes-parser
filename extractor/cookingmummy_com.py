"""
Экстрактор данных рецептов для сайта cookingmummy.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CookingmummyExtractor(BaseRecipeExtractor):
    """Экстрактор для cookingmummy.com"""
    
    # Карта Unicode дробей для парсинга ингредиентов
    FRACTION_MAP = {
        '½': '0.5', '¼': '0.25', '¾': '0.75',
        '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
        '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
        '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
    }
    
    # Паттерн для парсинга ингредиентов
    # Включаем Unicode дроби в числовую часть
    INGREDIENT_PATTERN = re.compile(
        r'^([\d\s/.,½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘]+)?\s*(tablespoons?|teaspoons?|tbsps?|tsps?|cups?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|kg|milliliters?|liters?|ml|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|pcs?|head|heads)?\s*(.+)',
        re.IGNORECASE
    )
    
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
        
        # Форматируем в читаемый вид
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD"""
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
                    # Проверяем напрямую
                    elif is_recipe(data):
                        return data
                        
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Пробуем из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Ищем в h1 заголовке
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Из title
        title = self.soup.find('title')
        if title:
            text = title.get_text()
            # Убираем суффиксы сайта
            text = re.sub(r'\s*[-|]\s*(CookingMummy|Recipe).*$', '', text, flags=re.IGNORECASE)
            return self.clean_text(text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Пробуем из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате JSON"""
        ingredients = []
        
        # Пробуем из JSON-LD (приоритет)
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredient_list = recipe_data['recipeIngredient']
            if isinstance(ingredient_list, list):
                for ingredient_text in ingredient_list:
                    if isinstance(ingredient_text, str):
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
        
        # Если из JSON-LD не получилось, ищем в HTML
        if not ingredients:
            # Ищем по различным возможным селекторам
            ingredient_containers = [
                self.soup.find('ul', class_=re.compile(r'ingredient', re.I)),
                self.soup.find('div', class_=re.compile(r'ingredient', re.I)),
                self.soup.find('ul', attrs={'itemprop': 'recipeIngredient'}),
            ]
            
            for container in ingredient_containers:
                if not container:
                    continue
                    
                # Извлекаем элементы списка
                items = container.find_all('li')
                if not items:
                    items = container.find_all('p')
                
                for item in items:
                    # Проверяем структурированные данные (name, amount, unit отдельно)
                    name_elem = item.find(attrs={'itemprop': 'name'}) or item.find(class_=re.compile(r'name', re.I))
                    amount_elem = item.find(attrs={'itemprop': 'amount'}) or item.find(class_=re.compile(r'amount|quantity', re.I))
                    unit_elem = item.find(attrs={'itemprop': 'unit'}) or item.find(class_=re.compile(r'unit', re.I))
                    
                    if name_elem:
                        # Если структура разделена
                        name = self.clean_text(name_elem.get_text())
                        amount = self.clean_text(amount_elem.get_text()) if amount_elem else None
                        unit = self.clean_text(unit_elem.get_text()) if unit_elem else None
                        
                        if name:
                            ingredients.append({
                                "name": name,
                                "amount": amount,
                                "unit": unit
                            })
                    else:
                        # Если текст одной строкой
                        ingredient_text = item.get_text(separator=' ', strip=True)
                        ingredient_text = self.clean_text(ingredient_text)
                        
                        if ingredient_text and not ingredient_text.endswith(':'):
                            parsed = self.parse_ingredient(ingredient_text)
                            if parsed:
                                ingredients.append(parsed)
                
                if ingredients:
                    break
        
        # Если ничего не найдено, ищем любой список UL в странице
        if not ingredients:
            all_lists = self.soup.find_all('ul')
            for ul_list in all_lists:
                items = ul_list.find_all('li')
                temp_ingredients = []
                for item in items:
                    ingredient_text = item.get_text(separator=' ', strip=True)
                    ingredient_text = self.clean_text(ingredient_text)
                    
                    if ingredient_text and len(ingredient_text) > 2 and not ingredient_text.endswith(':'):
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            temp_ingredients.append(parsed)
                
                # Если нашли хотя бы 2 ингредиента, считаем это списком ингредиентов
                if len(temp_ingredients) >= 2:
                    ingredients = temp_ingredients
                    break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour" или "2 pounds chicken"
            
        Returns:
            dict: {"name": "flour", "amount": "1", "unit": "cup"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Используем предкомпилированный паттерн
        match = self.INGREDIENT_PATTERN.match(text)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            
            # Заменяем Unicode дроби на десятичные числа с пробелом перед
            # Например "1½" -> "1 0.5", чтобы потом правильно распарсить
            for fraction, decimal in self.FRACTION_MAP.items():
                if fraction in amount_str:
                    # Проверяем, идет ли дробь сразу после цифры
                    amount_str = re.sub(r'(\d)' + re.escape(fraction), r'\1 ' + decimal, amount_str)
                    # Заменяем оставшиеся дроби
                    amount_str = amount_str.replace(fraction, decimal)
            
            # Обработка обычных дробей типа "1/2" или "1 1/2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        try:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        except (ValueError, ZeroDivisionError):
                            pass
                    else:
                        try:
                            total += float(part.replace(',', '.'))
                        except ValueError:
                            pass
                amount = str(total) if total > 0 else None
            else:
                # Суммируем все числа (для случаев типа "1 0.5" после замены дробей)
                parts = amount_str.split()
                total = 0
                for part in parts:
                    try:
                        total += float(part.replace(',', '.'))
                    except ValueError:
                        pass
                amount = str(total) if total > 0 else None
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        name = re.sub(r'\([^)]*\)', '', name)  # Удаляем скобки
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish)\b', '', name, flags=re.IGNORECASE)
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        steps = []
        
        # Пробуем из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        steps.append(step['text'])
                    elif isinstance(step, str):
                        steps.append(step)
            elif isinstance(instructions, str):
                steps.append(instructions)
        
        # Если из JSON-LD не получилось, ищем в HTML
        if not steps:
            instructions_containers = [
                self.soup.find('ol', class_=re.compile(r'instruction', re.I)),
                self.soup.find('div', class_=re.compile(r'instruction|step|method', re.I)),
                self.soup.find('ol', attrs={'itemprop': 'recipeInstructions'}),
            ]
            
            for container in instructions_containers:
                if not container:
                    continue
                
                # Извлекаем шаги
                step_items = container.find_all('li')
                if not step_items:
                    step_items = container.find_all('p')
                if not step_items:
                    step_items = container.find_all(class_=re.compile(r'step', re.I))
                
                for item in step_items:
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    
                    if step_text and not step_text.endswith(':'):
                        steps.append(step_text)
                
                if steps:
                    break
        
        # Если ничего не найдено, ищем параграфы с текстом инструкций
        if not steps:
            # Ищем все параграфы в body
            all_paragraphs = self.soup.find_all('p')
            for p in all_paragraphs:
                text = p.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                
                # Проверяем, что это похоже на инструкцию (не слишком короткое, содержит глаголы действия)
                if text and len(text) > 10:
                    # Проверяем на ключевые слова инструкций
                    instruction_keywords = ['mix', 'add', 'cook', 'bake', 'serve', 'heat', 'combine', 
                                           'place', 'pour', 'stir', 'blend', 'prepare', 'preheat',
                                           'whisk', 'beat', 'fold', 'spread', 'cut', 'chop', 'slice']
                    text_lower = text.lower()
                    
                    # Если содержит хотя бы одно ключевое слово или выглядит как инструкция
                    if any(keyword in text_lower for keyword in instruction_keywords) or '.' in text:
                        steps.append(text)
        
        # Добавляем нумерацию если её нет ни в одном шаге
        if steps:
            # Проверяем, есть ли хотя бы один шаг с нумерацией
            has_numbering = any(re.match(r'^\d+\.', step) for step in steps)
            if not has_numbering:
                steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Пробуем из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data:
            # Проверяем recipeCategory
            if 'recipeCategory' in recipe_data:
                category = recipe_data['recipeCategory']
                if isinstance(category, list):
                    return ', '.join(category)
                return self.clean_text(str(category))
            # Проверяем recipeCuisine
            if 'recipeCuisine' in recipe_data:
                cuisine = recipe_data['recipeCuisine']
                if isinstance(cuisine, list):
                    return ', '.join(cuisine)
                return self.clean_text(str(cuisine))
        
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Пробуем из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data:
            time_keys = {
                'prep': 'prepTime',
                'cook': 'cookTime',
                'total': 'totalTime'
            }
            
            key = time_keys.get(time_type)
            if key and key in recipe_data:
                iso_time = recipe_data[key]
                return self.parse_iso_duration(iso_time)
        
        # Ищем в HTML
        time_patterns = {
            'prep': ['prep.*time', 'preparation'],
            'cook': ['cook.*time', 'cooking'],
            'total': ['total.*time', 'ready.*in']
        }
        
        patterns = time_patterns.get(time_type, [])
        
        for pattern in patterns:
            time_elem = self.soup.find(class_=re.compile(pattern, re.I))
            if not time_elem:
                time_elem = self.soup.find(attrs={'itemprop': pattern.replace('.*', '')})
            
            if time_elem:
                time_text = time_elem.get_text(strip=True)
                # Извлекаем только числа и текст времени
                time_match = re.search(r'(\d+)\s*(hour|hr|minute|min|h|m)s?', time_text, re.I)
                if time_match:
                    return self.clean_text(time_text)
        
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
        # Ищем секции с примечаниями
        notes_patterns = [
            re.compile(r'note', re.I),
            re.compile(r'tip', re.I),
            re.compile(r'advice', re.I),
        ]
        
        for pattern in notes_patterns:
            notes_section = self.soup.find(class_=pattern)
            if notes_section:
                # Ищем параграф внутри (убираем заголовок)
                p = notes_section.find('p')
                if p:
                    text = self.clean_text(p.get_text())
                    if text:
                        return text
                
                # Если нет параграфа, берем весь текст и убираем заголовок
                text = notes_section.get_text(separator=' ', strip=True)
                text = re.sub(r'^(Note|Notes|Tip|Tips|Advice)\s*:?\s*', '', text, flags=re.I)
                text = self.clean_text(text)
                if text:
                    return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Пробуем из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, list):
                tags_list = [str(k).strip() for k in keywords if k]
            elif isinstance(keywords, str):
                tags_list = [k.strip() for k in keywords.split(',') if k.strip()]
        
        # Ищем в meta keywords
        if not tags_list:
            meta_keywords = self.soup.find('meta', {'name': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                tags_list = [k.strip() for k in meta_keywords['content'].split(',') if k.strip()]
        
        # Ищем теги в HTML
        if not tags_list:
            tags_container = self.soup.find(class_=re.compile(r'tag', re.I))
            if tags_container:
                tag_links = tags_container.find_all('a')
                tags_list = [self.clean_text(a.get_text()) for a in tag_links]
        
        if tags_list:
            # Фильтруем короткие теги
            tags_list = [tag for tag in tags_list if len(tag) >= 3]
            # Убираем дубликаты
            seen = set()
            unique_tags = []
            for tag in tags_list:
                tag_lower = tag.lower()
                if tag_lower not in seen:
                    seen.add(tag_lower)
                    unique_tags.append(tag)
            
            return ', '.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Пробуем из JSON-LD
        recipe_data = self._get_json_ld_recipe()
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
        
        # Ищем в meta тегах
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
            
            twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
            if twitter_image and twitter_image.get('content'):
                urls.append(twitter_image['content'])
        
        # Ищем изображения в HTML
        if not urls:
            # Ищем изображения рецепта по классам
            img_patterns = [
                re.compile(r'recipe.*image', re.I),
                re.compile(r'featured.*image', re.I),
            ]
            
            for pattern in img_patterns:
                img_elem = self.soup.find('img', class_=pattern)
                if img_elem and img_elem.get('src'):
                    urls.append(img_elem['src'])
                    break
        
        # Убираем дубликаты
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Обработка директории с HTML файлами cookingmummy.com"""
    import os
    
    # Директория с HTML страницами
    recipes_dir = os.path.join("preprocessed", "cookingmummy_com")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(CookingmummyExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python cookingmummy_com.py")


if __name__ == "__main__":
    main()
