"""
Экстрактор данных рецептов для сайта food.ndtv.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class FoodNdtvComExtractor(BaseRecipeExtractor):
    """Экстрактор для food.ndtv.com"""
    
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
                            if isinstance(item, dict):
                                item_type = item.get('@type', '')
                                if isinstance(item_type, list) and 'Recipe' in item_type:
                                    return item
                                elif item_type == 'Recipe':
                                    return item
                    
                    # Проверяем сам объект
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
        
        # Конвертируем все в минуты
        total_minutes = hours * 60 + minutes
        
        if total_minutes > 0:
            if hours > 0 and minutes > 0:
                return f"{hours} hour{'s' if hours > 1 else ''} {minutes} minute{'s' if minutes > 1 else ''}"
            elif hours > 0:
                return f"{hours} hour{'s' if hours > 1 else ''}"
            else:
                return f"{minutes} minute{'s' if minutes > 1 else ''}"
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'name' in json_ld:
            name = self.clean_text(json_ld['name'])
            if name:
                return name
        
        # Альтернатива - из заголовка H1
        h1 = self.soup.find('h1')
        if h1:
            name = self.clean_text(h1.get_text())
            # Убираем слово "Recipe" если есть
            name = re.sub(r'\s+Recipe\s*$', '', name, flags=re.IGNORECASE)
            if name:
                return name
        
        # Из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            name = self.clean_text(og_title['content'])
            # Убираем суффиксы
            name = re.sub(r'\s+Recipe.*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\s*\|.*$', '', name)
            if name:
                return name
        
        # Из title
        title = self.soup.find('title')
        if title:
            name = self.clean_text(title.get_text())
            name = re.sub(r'\s+Recipe.*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\s*\|.*$', '', name)
            if name:
                return name
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала из JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'description' in json_ld:
            desc = self.clean_text(json_ld['description'])
            if desc:
                return desc
        
        # Из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            if desc:
                return desc
        
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = self.clean_text(og_desc['content'])
            if desc:
                return desc
        
        # Ищем первый параграф в основном контенте
        article = self.soup.find('article')
        if not article:
            article = self.soup.find('div', class_=re.compile(r'recipe.*content|content.*recipe', re.I))
        
        if article:
            # Ищем первый параграф с текстом
            paragraphs = article.find_all('p')
            for p in paragraphs:
                text = self.clean_text(p.get_text())
                if text and len(text) > 20:  # Минимальная длина описания
                    return text
        
        return None
    
    def extract_ingredients(self) -> Optional[list]:
        """Извлечение ингредиентов в формате списка словарей"""
        ingredients = []
        
        # Сначала пробуем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'recipeIngredient' in json_ld:
            for ingredient_text in json_ld['recipeIngredient']:
                if isinstance(ingredient_text, str):
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        # Если JSON-LD не дал результата, ищем в HTML
        if not ingredients:
            # Ищем секцию с ингредиентами по разным паттернам
            ingredient_containers = [
                self.soup.find('ul', class_=re.compile(r'ingredient', re.I)),
                self.soup.find('div', class_=re.compile(r'ingredient', re.I)),
                self.soup.find('section', class_=re.compile(r'ingredient', re.I)),
            ]
            
            # Также ищем по заголовку "Ingredients"
            for heading in self.soup.find_all(['h2', 'h3']):
                if re.search(r'ingredient', heading.get_text(), re.I):
                    container = heading.find_next_sibling(['ul', 'div'])
                    if container:
                        ingredient_containers.append(container)
            
            for container in ingredient_containers:
                if not container:
                    continue
                
                # Извлекаем элементы списка
                items = container.find_all('li')
                if not items:
                    items = container.find_all('p')
                
                temp_ingredients = []
                for item in items:
                    ingredient_text = self.clean_text(item.get_text())
                    
                    # Пропускаем заголовки секций
                    if ingredient_text and not ingredient_text.endswith(':'):
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            temp_ingredients.append(parsed)
                
                if temp_ingredients:
                    ingredients = temp_ingredients
                    break
        
        return ingredients if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour"
            
        Returns:
            dict: {"name": "flour", "amount": "1", "unit": "cup"}
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
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1 cup flour", "2 tablespoons butter", "1/2 teaspoon salt"
        pattern = r'^([\d\s/.,]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads|to taste)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
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
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
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
        
        # Сначала пробуем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        if step_text:
                            steps.append(step_text)
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        if step_text:
                            steps.append(step_text)
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
        
        # Если JSON-LD не помог, ищем в HTML
        if not steps:
            # Ищем секцию с инструкциями по разным паттернам
            instruction_containers = [
                self.soup.find('ol', class_=re.compile(r'instruction|step|method|direction', re.I)),
                self.soup.find('div', class_=re.compile(r'instruction|step|method|direction', re.I)),
                self.soup.find('section', class_=re.compile(r'instruction|step|method|direction', re.I)),
            ]
            
            # Также ищем по заголовку
            for heading in self.soup.find_all(['h2', 'h3']):
                heading_text = heading.get_text()
                if re.search(r'instruction|method|direction|how to|preparation', heading_text, re.I):
                    container = heading.find_next_sibling(['ol', 'div', 'ul'])
                    if container:
                        instruction_containers.append(container)
            
            for container in instruction_containers:
                if not container:
                    continue
                
                # Извлекаем шаги
                step_items = container.find_all('li')
                if not step_items:
                    step_items = container.find_all('p')
                
                temp_steps = []
                for item in step_items:
                    step_text = self.clean_text(item.get_text())
                    if step_text:
                        temp_steps.append(step_text)
                
                if temp_steps:
                    steps = temp_steps
                    break
        
        # Форматируем шаги в одну строку
        if steps:
            # Проверяем, есть ли уже нумерация
            if not re.match(r'^\d+\.', steps[0]):
                # Добавляем нумерацию
                steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
            
            return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала из JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld:
            # Проверяем recipeCategory
            if 'recipeCategory' in json_ld:
                category = json_ld['recipeCategory']
                if isinstance(category, list):
                    return ', '.join([self.clean_text(c) for c in category if c])
                elif isinstance(category, str):
                    return self.clean_text(category)
            
            # Проверяем recipeCuisine
            if 'recipeCuisine' in json_ld:
                cuisine = json_ld['recipeCuisine']
                if isinstance(cuisine, list):
                    return ', '.join([self.clean_text(c) for c in cuisine if c])
                elif isinstance(cuisine, str):
                    return self.clean_text(cuisine)
        
        # Ищем в мета-тегах
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if not breadcrumbs:
            breadcrumbs = self.soup.find('ol', class_=re.compile(r'breadcrumb', re.I))
        
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                # Берем последнюю категорию перед самим рецептом
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Сначала пробуем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld:
            # Маппинг типов времени на ключи JSON-LD
            time_keys = {
                'prep': 'prepTime',
                'cook': 'cookTime',
                'total': 'totalTime'
            }
            
            key = time_keys.get(time_type)
            if key and key in json_ld:
                iso_time = json_ld[key]
                return self.parse_iso_duration(iso_time)
        
        # Если JSON-LD не помог, ищем в HTML
        time_patterns = {
            'prep': ['prep.*time', 'preparation'],
            'cook': ['cook.*time', 'cooking'],
            'total': ['total.*time', 'ready.*in']
        }
        
        patterns = time_patterns.get(time_type, [])
        
        for pattern in patterns:
            # Ищем элемент с временем
            time_elem = self.soup.find(class_=re.compile(pattern, re.I))
            if not time_elem:
                time_elem = self.soup.find(attrs={'data-test-id': re.compile(pattern, re.I)})
            if not time_elem:
                # Ищем по тексту в span/div
                for elem in self.soup.find_all(['span', 'div', 'li']):
                    if re.search(pattern, elem.get_text(), re.I):
                        time_elem = elem
                        break
            
            if time_elem:
                time_text = self.clean_text(time_elem.get_text())
                # Извлекаем только время из текста
                time_match = re.search(r'(\d+\s*(?:hour|hr|minute|min)s?(?:\s*\d+\s*(?:minute|min)s?)?)', time_text, re.I)
                if time_match:
                    return time_match.group(1)
                return time_text
        
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
        # Ищем секцию с примечаниями/советами
        notes_containers = [
            self.soup.find(class_=re.compile(r'note|tip|advice', re.I)),
            self.soup.find('section', class_=re.compile(r'note|tip|advice', re.I)),
        ]
        
        # Также ищем по заголовку
        for heading in self.soup.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text()
            if re.search(r'note|tip|advice|chef.*note', heading_text, re.I):
                container = heading.find_next_sibling(['div', 'p', 'ul'])
                if container:
                    notes_containers.append(container)
        
        for container in notes_containers:
            if not container:
                continue
            
            # Извлекаем текст
            text = self.clean_text(container.get_text())
            # Убираем заголовок, если он есть в тексте
            text = re.sub(r"^(?:Note|Tip|Chef'?s?\s+Note|Advice)\s*:?\s*", '', text, flags=re.I)
            if text:
                return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Список общих слов для фильтрации
        stopwords = {
            'recipe', 'recipes', 'how to make', 'how to', 'easy', 'cooking', 'quick',
            'food', 'kitchen', 'simple', 'best', 'make', 'ingredients', 'video',
            'meal', 'prep', 'ideas', 'tips', 'tricks', 'home', 'family',
            'prepare', 'homemade', 'dish', 'perfect', 'favorite', 'delicious',
            'ndtv', 'ndtv food'
        }
        
        # 1. Из meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags_list = [tag.strip().lower() for tag in keywords.split(',') if tag.strip()]
        
        # 2. Из article:tag meta
        if not tags_list:
            article_tags = self.soup.find_all('meta', property='article:tag')
            for tag_meta in article_tags:
                if tag_meta.get('content'):
                    tags_list.append(tag_meta['content'].strip().lower())
        
        # 3. Из JSON-LD keywords
        if not tags_list:
            json_ld = self._get_json_ld_data()
            if json_ld and 'keywords' in json_ld:
                keywords = json_ld['keywords']
                if isinstance(keywords, str):
                    tags_list = [tag.strip().lower() for tag in keywords.split(',') if tag.strip()]
                elif isinstance(keywords, list):
                    tags_list = [tag.strip().lower() for tag in keywords if tag]
        
        if not tags_list:
            return None
        
        # Фильтрация тегов
        filtered_tags = []
        for tag in tags_list:
            # Пропускаем точные совпадения со стоп-словами
            if tag in stopwords:
                continue
            
            # Пропускаем теги короче 3 символов
            if len(tag) < 3:
                continue
            
            filtered_tags.append(tag)
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in filtered_tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        # Возвращаем как строку через запятую с пробелом
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Из JSON-LD
        json_ld = self._get_json_ld_data()
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
        
        # 2. Из мета-тегов
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Из основного изображения рецепта
        recipe_img = self.soup.find('img', class_=re.compile(r'recipe.*image|featured.*image', re.I))
        if recipe_img and recipe_img.get('src'):
            urls.append(recipe_img['src'])
        
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
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        total_time = self.extract_total_time()
        notes = self.extract_notes()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": json.dumps(ingredients, ensure_ascii=False) if ingredients else None,
            "instructions": instructions,
            "category": category,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "notes": notes,
            "tags": tags,
            "image_urls": image_urls
        }


def main():
    """Точка входа для тестирования парсера"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "food_ndtv_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(FoodNdtvComExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python food_ndtv_com.py")
    print(f"Текущая директория: {os.getcwd()}")
    
    # Показываем доступные директории
    if os.path.exists("preprocessed"):
        dirs = [d for d in os.listdir("preprocessed") if os.path.isdir(os.path.join("preprocessed", d))]
        print(f"\nДоступные директории в preprocessed/:")
        for d in sorted(dirs):
            print(f"  - {d}")


if __name__ == "__main__":
    main()
