"""
Экстрактор данных рецептов для сайта pipingpotcurry.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class PipingPotCurryExtractor(BaseRecipeExtractor):
    """Экстрактор для pipingpotcurry.com"""
    
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
        
        # Если минут больше 60 и нет часов, конвертируем в часы и минуты
        if minutes >= 60 and hours == 0:
            hours = minutes // 60
            minutes = minutes % 60
        
        # Форматируем результат
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Альтернатива - из заголовка страницы
        h1 = self.soup.find('h1', class_=re.compile(r'entry-title|post-title|recipe-title', re.I))
        if h1:
            return self.clean_text(h1.get_text())
        
        # Просто первый h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Из meta title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            text = og_title['content']
            # Убираем суффиксы
            text = re.sub(r'\s*\|.*$', '', text)
            text = re.sub(r'\s+Recipe.*$', '', text, flags=re.IGNORECASE)
            return self.clean_text(text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
        # Альтернатива - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате JSON строки"""
        json_ld = self._get_json_ld_data()
        
        ingredients = []
        
        # Сначала пробуем извлечь из JSON-LD
        if json_ld and 'recipeIngredient' in json_ld:
            for ingredient_text in json_ld['recipeIngredient']:
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        # Если не нашли в JSON-LD, ищем в HTML
        if not ingredients:
            # Ищем список ингредиентов в HTML
            ingredient_list = self.soup.find('ul', class_=re.compile(r'ingredient', re.I))
            if not ingredient_list:
                ingredient_list = self.soup.find('div', class_=re.compile(r'ingredient', re.I))
            
            if ingredient_list:
                items = ingredient_list.find_all('li')
                for item in items:
                    # Проверяем структуру для более детального парсинга
                    # Иногда сайты разделяют name, amount, unit в отдельные элементы
                    name_elem = item.find(class_=re.compile(r'ingredient.*name', re.I))
                    amount_elem = item.find(class_=re.compile(r'ingredient.*amount', re.I))
                    unit_elem = item.find(class_=re.compile(r'ingredient.*unit', re.I))
                    
                    if name_elem and amount_elem:
                        # Структурированный формат
                        parsed = {
                            "name": self.clean_text(name_elem.get_text()),
                            "amount": self.clean_text(amount_elem.get_text()) if amount_elem.get_text() else None,
                            "units": self.clean_text(unit_elem.get_text()) if unit_elem and unit_elem.get_text() else None
                        }
                        if parsed["name"]:
                            ingredients.append(parsed)
                    else:
                        # Неструктурированный формат - парсим текст
                        ingredient_text = item.get_text(separator=' ', strip=True)
                        ingredient_text = self.clean_text(ingredient_text)
                        
                        # Пропускаем заголовки секций
                        if ingredient_text and not ingredient_text.endswith(':'):
                            parsed = self.parse_ingredient(ingredient_text)
                            if parsed:
                                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour"
            
        Returns:
            dict: {"name": "flour", "amount": "1", "units": "cup"}
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
        # Примеры: "1 cup flour", "2 tablespoons butter", "1/2 teaspoon salt", "1 large onion"
        # Используем \b для word boundary, чтобы избежать частичных совпадений
        # Сначала проверяем на наличие количества и размера (large, small, medium)
        size_pattern = r'^([\d\s/.,]+)?\s*\b(large|medium|small)\b\s+(.+)'
        size_match = re.match(size_pattern, text, re.IGNORECASE)
        
        if size_match:
            amount_str, size, name = size_match.groups()
            # Обработка количества
            amount = None
            if amount_str:
                amount_str = amount_str.strip()
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
            
            # Добавляем размер к названию
            name = f"{size} {name}"
            
            # Очистка названия
            name = re.sub(r'\([^)]*\)', '', name)
            name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|for serving)\b', '', name, flags=re.IGNORECASE)
            name = re.sub(r',\s*(drained|grated|sliced|chopped|minced|crushed|fresh|frozen|diced).*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'[,;]+$', '', name)
            name = re.sub(r'\s+', ' ', name).strip()
            
            if name and len(name) >= 2:
                return {
                    "name": name,
                    "amount": amount,
                    "units": None
                }
        
        # Обычный паттерн для ингредиентов с единицами измерения
        pattern = r'^([\d\s/.,]+)?\s*\b(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|kg|milliliters?|liters?|ml|pinch(?:es)?|dash(?:es)?|packages?|packs?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads)\b\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
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
        units = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|for serving)\b', '', name, flags=re.IGNORECASE)
        # Удаляем специфичные суффиксы
        name = re.sub(r',\s*(drained|grated|sliced|chopped|minced|crushed|fresh|frozen|diced).*$', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
        steps = []
        
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        steps.append(f"{idx}. {step_text}")
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        steps.append(f"{idx}. {step_text}")
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
        
        # Если не нашли в JSON-LD, ищем в HTML
        if not steps:
            instructions_list = self.soup.find('ol', class_=re.compile(r'instruction', re.I))
            if not instructions_list:
                instructions_list = self.soup.find('div', class_=re.compile(r'instruction', re.I))
            
            if instructions_list:
                step_items = instructions_list.find_all('li')
                for idx, item in enumerate(step_items, 1):
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    
                    if step_text:
                        # Добавляем номер, если его нет
                        if not re.match(r'^\d+\.', step_text):
                            steps.append(f"{idx}. {step_text}")
                        else:
                            steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        json_ld = self._get_json_ld_data()
        
        if json_ld:
            # Пробуем recipeCategory
            if 'recipeCategory' in json_ld:
                category = json_ld['recipeCategory']
                if isinstance(category, list):
                    return ', '.join(str(c) for c in category)
                return str(category)
            
            # Пробуем recipeCuisine
            if 'recipeCuisine' in json_ld:
                cuisine = json_ld['recipeCuisine']
                if isinstance(cuisine, list):
                    return ', '.join(str(c) for c in cuisine)
                return str(cuisine)
        
        # Альтернатива - из meta тегов
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Из хлебных крошек
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
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
        
        # Альтернатива - из HTML
        time_elem = self.soup.find(class_=re.compile(r'prep.*time', re.I))
        if time_elem:
            return self.clean_text(time_elem.get_text())
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        # Альтернатива - из HTML
        time_elem = self.soup.find(class_=re.compile(r'cook.*time', re.I))
        if time_elem:
            return self.clean_text(time_elem.get_text())
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        # Альтернатива - из HTML
        time_elem = self.soup.find(class_=re.compile(r'total.*time', re.I))
        if time_elem:
            return self.clean_text(time_elem.get_text())
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        json_ld = self._get_json_ld_data()
        
        # Иногда заметки могут быть в JSON-LD
        if json_ld:
            # Проверяем различные возможные поля
            for field in ['notes', 'recipeTips', 'cookingNotes']:
                if field in json_ld:
                    notes = json_ld[field]
                    if isinstance(notes, str):
                        return self.clean_text(notes)
                    elif isinstance(notes, list):
                        return ' '.join(self.clean_text(str(n)) for n in notes)
        
        # Ищем в HTML
        notes_section = self.soup.find(class_=re.compile(r'note|tip|advice', re.I))
        if notes_section:
            # Ищем параграф внутри
            p = notes_section.find('p')
            if p:
                text = self.clean_text(p.get_text())
                return text if text else None
            
            # Берем весь текст
            text = notes_section.get_text(separator=' ', strip=True)
            # Убираем заголовки секций
            text = re.sub(r"^(Note|Notes|Tip|Tips|Cook'?s\s+Note)\s*:?\s*", '', text, flags=re.I)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Список общих слов для фильтрации
        stopwords = {
            'recipe', 'recipes', 'how to make', 'how to', 'easy', 'cooking', 'quick',
            'pipingpotcurry', 'food', 'pipingpotcurry.com', 'piping pot curry'
        }
        
        # 1. Пробуем из мета-тегов
        keywords_meta = self.soup.find('meta', {'name': 'keywords'})
        if keywords_meta and keywords_meta.get('content'):
            keywords = keywords_meta['content']
            tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        # 2. Пробуем из parsely-tags
        if not tags_list:
            parsely_meta = self.soup.find('meta', {'name': 'parsely-tags'})
            if parsely_meta and parsely_meta.get('content'):
                tags_string = parsely_meta['content']
                tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        # 3. Пробуем из article:tag
        if not tags_list:
            article_tags = self.soup.find_all('meta', property='article:tag')
            if article_tags:
                tags_list = [tag.get('content').strip() for tag in article_tags if tag.get('content')]
        
        # 4. Пробуем из JSON-LD keywords
        if not tags_list:
            json_ld = self._get_json_ld_data()
            if json_ld and 'keywords' in json_ld:
                keywords = json_ld['keywords']
                if isinstance(keywords, str):
                    tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                elif isinstance(keywords, list):
                    tags_list = [str(tag).strip() for tag in keywords]
        
        if not tags_list:
            return None
        
        # Фильтрация тегов
        filtered_tags = []
        for tag in tags_list:
            tag_lower = tag.lower()
            
            # Пропускаем стоп-слова
            if tag_lower in stopwords:
                continue
            
            # Пропускаем короткие теги
            if len(tag) < 3:
                continue
            
            filtered_tags.append(tag)
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in filtered_tags:
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen.add(tag_lower)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        json_ld = self._get_json_ld_data()
        
        # 1. Из JSON-LD
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        if 'url' in item:
                            urls.append(item['url'])
                        elif 'contentUrl' in item:
                            urls.append(item['contentUrl'])
        
        # 2. Из meta тегов
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Из основного изображения рецепта
        recipe_image = self.soup.find('img', class_=re.compile(r'recipe.*image|featured.*image', re.I))
        if recipe_image and recipe_image.get('src'):
            src = recipe_image['src']
            # Проверяем, что это не маленькая иконка
            if not re.search(r'\d+x\d+', src) or re.search(r'[5-9]\d{2,}x[5-9]\d{2,}', src):
                urls.append(src)
        
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
            Словарь с данными рецепта со всеми обязательными полями
        """
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_steps(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "pipingpotcurry_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(PipingPotCurryExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python pipingpotcurry_com.py")


if __name__ == "__main__":
    main()
