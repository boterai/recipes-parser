"""
Экстрактор данных рецептов для сайта gagalog.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class GagalogExtractor(BaseRecipeExtractor):
    """Экстрактор для gagalog.com"""
    
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
                    # Проверяем прямо в корне
                    item_type = data.get('@type', '')
                    if isinstance(item_type, list) and 'Recipe' in item_type:
                        return data
                    elif item_type == 'Recipe':
                        return data
                    # Проверяем в @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict):
                                item_type = item.get('@type', '')
                                if isinstance(item_type, list) and 'Recipe' in item_type:
                                    return item
                                elif item_type == 'Recipe':
                                    return item
                        
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
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Ищем в заголовке h1
        h1_tags = self.soup.find_all('h1')
        for h1 in h1_tags:
            # Пропускаем заголовки, которые явно не название рецепта
            text = h1.get_text(strip=True)
            if text and len(text) > 3:
                return self.clean_text(text)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Из meta тега title
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем суффиксы типа " | Site Name"
            title = re.sub(r'\s*[|•-]\s*\w+.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        # Ищем в HTML - часто это первый параграф или div с классом description
        desc_container = self.soup.find(class_=re.compile(r'description|intro|summary', re.I))
        if desc_container:
            text = desc_container.get_text(separator=' ', strip=True)
            return self.clean_text(text)
        
        return None
    
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
        if not text:
            return None
        
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
        # Поддерживаем различные единицы измерения
        pattern = r'^([\d\s/.,]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads)?\s*(.+)'
        
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
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Сначала пробуем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'recipeIngredient' in json_ld:
            ingredient_list = json_ld['recipeIngredient']
            if isinstance(ingredient_list, list):
                for ingredient_text in ingredient_list:
                    if isinstance(ingredient_text, str):
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
                
                if ingredients:
                    return json.dumps(ingredients, ensure_ascii=False)
        
        # Если JSON-LD не помог, ищем в HTML
        # Ищем различные варианты контейнеров с ингредиентами
        ingredient_containers = [
            self.soup.find('ul', class_=re.compile(r'ingredient', re.I)),
            self.soup.find('div', class_=re.compile(r'ingredient', re.I)),
            self.soup.find('div', {'itemprop': 'recipeIngredient'}),
        ]
        
        for container in ingredient_containers:
            if not container:
                continue
                
            # Извлекаем элементы списка
            items = container.find_all('li')
            if not items:
                items = container.find_all('p')
            if not items:
                # Пробуем найти элементы с itemprop
                items = container.find_all(attrs={'itemprop': 'recipeIngredient'})
            
            for item in items:
                # Извлекаем текст ингредиента
                ingredient_text = item.get_text(separator=' ', strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                # Пропускаем заголовки секций
                if ingredient_text and not ingredient_text.endswith(':') and len(ingredient_text) > 2:
                    # Парсим в структурированный формат
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
            
            if ingredients:
                break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        steps = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict):
                        if 'text' in step:
                            steps.append(f"{idx}. {step['text']}")
                        elif 'itemListElement' in step:
                            # HowToSection с подшагами
                            for substep in step['itemListElement']:
                                if isinstance(substep, dict) and 'text' in substep:
                                    steps.append(f"{len(steps) + 1}. {substep['text']}")
                    elif isinstance(step, str):
                        steps.append(f"{idx}. {step}")
            elif isinstance(instructions, str):
                steps.append(instructions)
            
            if steps:
                return ' '.join(steps)
        
        # Если JSON-LD не помог, ищем в HTML
        instructions_containers = [
            self.soup.find('ol', class_=re.compile(r'instruction|direction|step|method', re.I)),
            self.soup.find('div', class_=re.compile(r'instruction|direction|step|method', re.I)),
            self.soup.find('div', {'itemprop': 'recipeInstructions'}),
        ]
        
        for container in instructions_containers:
            if not container:
                continue
            
            # Извлекаем шаги
            step_items = container.find_all('li')
            if not step_items:
                step_items = container.find_all('p')
            if not step_items:
                # Пробуем найти элементы с itemprop
                step_items = container.find_all(attrs={'itemprop': 'step'})
            
            for idx, item in enumerate(step_items, 1):
                # Извлекаем текст инструкции
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text and len(step_text) > 5:
                    # Если уже есть нумерация, используем как есть
                    if re.match(r'^\d+\.', step_text):
                        steps.append(step_text)
                    else:
                        steps.append(f"{idx}. {step_text}")
            
            if steps:
                break
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Пробуем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld:
            # Проверяем recipeCategory
            if 'recipeCategory' in json_ld:
                category = json_ld['recipeCategory']
                if isinstance(category, list):
                    return ', '.join(category)
                return self.clean_text(str(category))
            
            # Проверяем recipeCuisine
            if 'recipeCuisine' in json_ld:
                cuisine = json_ld['recipeCuisine']
                if isinstance(cuisine, list):
                    return ', '.join(cuisine)
                return self.clean_text(str(cuisine))
        
        # Ищем в метаданных
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
                # Берем предпоследнюю категорию (последняя часто сам рецепт)
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Пробуем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        # Ищем в HTML
        prep_time_elem = self.soup.find(attrs={'itemprop': 'prepTime'})
        if prep_time_elem:
            # Проверяем атрибут datetime
            if prep_time_elem.get('datetime'):
                return self.parse_iso_duration(prep_time_elem['datetime'])
            # Или берем текст
            text = prep_time_elem.get_text(strip=True)
            return self.clean_text(text)
        
        # Ищем по классам
        prep_elem = self.soup.find(class_=re.compile(r'prep.*time', re.I))
        if prep_elem:
            text = prep_elem.get_text(strip=True)
            return self.clean_text(text)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Пробуем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        # Ищем в HTML
        cook_time_elem = self.soup.find(attrs={'itemprop': 'cookTime'})
        if cook_time_elem:
            # Проверяем атрибут datetime
            if cook_time_elem.get('datetime'):
                return self.parse_iso_duration(cook_time_elem['datetime'])
            # Или берем текст
            text = cook_time_elem.get_text(strip=True)
            return self.clean_text(text)
        
        # Ищем по классам
        cook_elem = self.soup.find(class_=re.compile(r'cook.*time', re.I))
        if cook_elem:
            text = cook_elem.get_text(strip=True)
            return self.clean_text(text)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Пробуем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        # Ищем в HTML
        total_time_elem = self.soup.find(attrs={'itemprop': 'totalTime'})
        if total_time_elem:
            # Проверяем атрибут datetime
            if total_time_elem.get('datetime'):
                return self.parse_iso_duration(total_time_elem['datetime'])
            # Или берем текст
            text = total_time_elem.get_text(strip=True)
            return self.clean_text(text)
        
        # Ищем по классам
        total_elem = self.soup.find(class_=re.compile(r'total.*time', re.I))
        if total_elem:
            text = total_elem.get_text(strip=True)
            return self.clean_text(text)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и примечаний"""
        # Ищем секцию с примечаниями
        notes_containers = [
            self.soup.find(class_=re.compile(r'note|tip|hint|advice', re.I)),
            self.soup.find('div', {'itemprop': 'comment'}),
        ]
        
        for container in notes_containers:
            if not container:
                continue
            
            # Извлекаем текст
            text = container.get_text(separator=' ', strip=True)
            # Убираем заголовки типа "Notes:", "Tips:"
            text = re.sub(r'^(notes?|tips?|hints?|advice)\s*:?\s*', '', text, flags=re.I)
            text = self.clean_text(text)
            
            if text and len(text) > 5:
                return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта"""
        tags_list = []
        
        # Пробуем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if isinstance(keywords, str):
                tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            elif isinstance(keywords, list):
                tags_list = [str(tag).strip() for tag in keywords if tag]
        
        # Ищем в meta keywords
        if not tags_list:
            meta_keywords = self.soup.find('meta', {'name': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                tags_list = [tag.strip() for tag in meta_keywords['content'].split(',') if tag.strip()]
        
        # Ищем в meta article:tag
        if not tags_list:
            meta_tags = self.soup.find_all('meta', property='article:tag')
            for meta_tag in meta_tags:
                if meta_tag.get('content'):
                    tags_list.append(meta_tag['content'])
        
        # Фильтрация и форматирование
        if tags_list:
            # Убираем дубликаты, сохраняя порядок
            seen = set()
            unique_tags = []
            for tag in tags_list:
                tag_lower = tag.lower()
                if tag_lower not in seen and len(tag_lower) >= 3:
                    seen.add(tag_lower)
                    unique_tags.append(tag_lower)
            
            # Возвращаем как строку через запятую с пробелом
            return ', '.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Пробуем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                for i in img:
                    if isinstance(i, str):
                        urls.append(i)
                    elif isinstance(i, dict):
                        if 'url' in i:
                            urls.append(i['url'])
                        elif 'contentUrl' in i:
                            urls.append(i['contentUrl'])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
        # 2. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Ищем в HTML изображения с itemprop
        img_tags = self.soup.find_all('img', attrs={'itemprop': 'image'})
        for img_tag in img_tags:
            if img_tag.get('src'):
                urls.append(img_tag['src'])
            elif img_tag.get('data-src'):
                urls.append(img_tag['data-src'])
        
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
            Словарь с данными рецепта со всеми обязательными полями
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
    """
    Точка входа для обработки HTML файлов gagalog.com
    Ищет директорию preprocessed/gagalog_com и обрабатывает все HTML файлы
    """
    import os
    
    # Путь к директории с preprocessed HTML файлами
    preprocessed_dir = os.path.join("preprocessed", "gagalog_com")
    
    # Проверяем существование директории
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка файлов из директории: {preprocessed_dir}")
        process_directory(GagalogExtractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Создайте директорию и поместите в неё HTML файлы для обработки")
        print("\nИспользование:")
        print("  1. Создайте директорию: mkdir -p preprocessed/gagalog_com")
        print("  2. Поместите HTML файлы в директорию")
        print("  3. Запустите: python extractor/gagalog_com.py")


if __name__ == "__main__":
    main()
