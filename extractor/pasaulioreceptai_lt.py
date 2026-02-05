"""
Экстрактор данных рецептов для сайта pasaulioreceptai.lt
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class PasaulioreceptaiExtractor(BaseRecipeExtractor):
    """Экстрактор для pasaulioreceptai.lt"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала проверяем WPRM recipe name
        recipe_container = self.soup.find('div', class_=lambda x: x and 'wprm-recipe-container' in x)
        if recipe_container:
            recipe_name = recipe_container.find('h2', class_='wprm-recipe-name')
            if recipe_name:
                return self.clean_text(recipe_name.get_text(strip=True))
        
        # Ищем в заголовке h1
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            title = h1.get_text(strip=True)
            # Убираем суффиксы типа "• Tik viena kulinarijos knyga", "- Pasaulio receptai", "receptas"
            title = re.sub(r'[•·\-–—]\s*(Tik viena kulinarijos knyga|Pasaulio receptai|Just One Cookbook).*$', '', title, flags=re.IGNORECASE)
            # Убираем японские символы в конце
            title = re.sub(r'\s*[ァ-ヾ]+\s*$', '', title)
            # Убираем слово "receptas" в конце
            title = re.sub(r'\s+receptas\s*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Альтернативно - из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'[•·\-–—]\s*(Tik viena kulinarijos knyga|Pasaulio receptai|Just One Cookbook).*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*[ァ-ヾ]+\s*$', '', title)
            title = re.sub(r'\s+receptas\s*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в recipe container summary
        recipe_container = self.soup.find('div', class_=lambda x: x and 'wprm-recipe-container' in x)
        if recipe_container:
            summary = recipe_container.find('div', class_='wprm-recipe-summary')
            if summary:
                desc_text = summary.get_text(strip=True)
                # Проверяем что это реальное описание, а не служебный текст
                if (desc_text and len(desc_text) > 20 and 
                    all(word not in desc_text.lower() for word in ['email', 'el. paštu', 'recepto akcentai', 'read more'])):
                    return self.clean_text(desc_text)
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Фильтруем плохие описания
            if (all(word not in desc.lower() for word in ['email', 'subscribe', 'recepto akcentai', 'read more']) and 
                len(desc) > 50 and 'recipe' not in desc[:50].lower()):
                return self.clean_text(desc)
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            if (all(word not in desc.lower() for word in ['email', 'subscribe', 'recepto akcentai', 'read more']) and 
                len(desc) > 50 and 'recipe' not in desc[:50].lower()):
                return self.clean_text(desc)
        
        # Если не нашли подходящего описания, возвращаем None
        # (reference JSONs могут иметь manually curated descriptions)
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем найти в WPRM recipe container
        recipe_container = self.soup.find('div', class_=lambda x: x and 'wprm-recipe-container' in x)
        if recipe_container:
            ingredients_section = recipe_container.find('div', class_=lambda x: x and 'wprm-recipe-ingredients-container' in x)
            if ingredients_section:
                groups = ingredients_section.find_all('div', class_='wprm-recipe-ingredient-group')
                for group in groups:
                    items = group.find_all('li', class_='wprm-recipe-ingredient')
                    for item in items:
                        amount_elem = item.find('span', class_='wprm-recipe-ingredient-amount')
                        unit_elem = item.find('span', class_='wprm-recipe-ingredient-unit')
                        name_elem = item.find('span', class_='wprm-recipe-ingredient-name')
                        
                        amount = amount_elem.get_text(strip=True) if amount_elem else None
                        unit = unit_elem.get_text(strip=True) if unit_elem else None
                        name = name_elem.get_text(strip=True) if name_elem else None
                        
                        if name:
                            # Очищаем имя от лишних пояснений
                            name = self.clean_ingredient_name(name)
                            ingredients.append({
                                "name": name,
                                "amount": amount,
                                "unit": unit
                            })
        
        # Если не нашли в WPRM, ищем в wp-block-list перед инструкциями
        if not ingredients:
            # Ищем список ингредиентов - обычно идет перед ordered list (инструкциями)
            # Ищем заголовок с "ingredient" или подходящий ul список
            entry_content = self.soup.find('div', class_='entry-content')
            if entry_content:
                # Ищем заголовок с ингредиентами
                for h2 in entry_content.find_all('h2', class_='wp-block-heading'):
                    heading_text = h2.get_text(strip=True).lower()
                    # Проверяем на литовское слово "ingredientai" или "ingredients"
                    if 'ingredient' in heading_text:
                        # Берем следующий ul список
                        next_list = h2.find_next_sibling('ul', class_='wp-block-list')
                        if next_list:
                            items = next_list.find_all('li')
                            for item in items:
                                ingredient_text = item.get_text(strip=True)
                                ingredient_text = self.clean_text(ingredient_text)
                                if ingredient_text:
                                    # Парсим ингредиент
                                    parsed = self.parse_ingredient(ingredient_text)
                                    if parsed:
                                        ingredients.append(parsed)
                            break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def clean_ingredient_name(self, name: str) -> str:
        """Очистка имени ингредиента от лишних пояснений"""
        if not name:
            return name
        
        # Удаляем пояснения в скобках
        name = re.sub(r'\([^)]*\)', '', name)
        
        # Удаляем пояснения после EN DASH (–), EM DASH (—), или обычного дефиса
        # Разбиваем по этим символам и берем только первую часть
        for separator in ['\u2013', '\u2014', ' - ', ' — ']:
            if separator in name:
                name = name.split(separator)[0].strip()
                break
        
        # Удаляем фразы типа "use X", "not Y" после запятой
        name = re.sub(r',\s*(use|not|naudokite|ne)\s+.+$', '', name, flags=re.IGNORECASE)
        
        # Очищаем от лишних пробелов
        name = re.sub(r'\s+', ' ', name).strip()
        
        return name
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 šaukštas cukraus" или "2 kiaušiniai"
            
        Returns:
            dict: {"name": "cukraus", "amount": "1", "unit": "šaukštas"} или None
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
        
        # Литовские единицы измерения (расширенный список)
        units_pattern = (
            r'(puodelių?|puodelio?|puodelis?|'
            r'šaukštų?|šaukšto?|šaukštas?|šaukštelis?|šaukštelių?|'
            r'arbatinių?\s+šaukštelių?|arbatinio?\s+šaukštelio?|'
            r'valgomuosius?\s+šaukštus?|valgomojo?\s+šaukšto?|'
            r'svarų?|svaro?|svaras?|uncijų?|uncijos?|uncija?|'
            r'gramų?|gramo?|gramas?|kilogramų?|kilogramo?|kilogramas?|'
            r'mililitrų?|militro?|militras?|litrų?|litro?|litras?|'
            r'žiupsnelis?|žiupsnelių?|žiupsnio?|'
            r'gabalų?|gabalo?|gabalas?|gabalėlių?|gabalėlio?|'
            r'kiaušinių?|kiaušinio?|kiaušinis?|'
            r'skiltelių?|skiltelio?|skiltelė?|'
            r'pėdų?|pėdos?|pėda?|colio?|colių?|'
            r'g|kg|ml|l|oz|lb|lbs?|'
            r'cups?|tablespoons?|teaspoons?|tbsps?|tsps?|'
            r'pounds?|ounces?|grams?|kilograms?|'
            r'milliliters?|liters?|'
            r'pinch(?:es)?|dash(?:es)?|'
            r'packages?|cans?|jars?|bottles?|'
            r'inch(?:es)?|slices?|cloves?|bunches?|sprigs?|'
            r'whole|halves?|quarters?|pieces?|head|heads)'
        )
        
        # Паттерн для извлечения количества, единицы и названия
        pattern = rf'^([\d\s/.,]+)?\s*{units_pattern}?\s*(.+)'
        
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
        name = self.clean_ingredient_name(name)
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем найти в WPRM recipe container
        recipe_container = self.soup.find('div', class_=lambda x: x and 'wprm-recipe-container' in x)
        if recipe_container:
            instructions_section = recipe_container.find('div', class_=lambda x: x and 'wprm-recipe-instructions-container' in x)
            if instructions_section:
                groups = instructions_section.find_all('div', class_='wprm-recipe-instruction-group')
                for group in groups:
                    items = group.find_all('li', class_='wprm-recipe-instruction')
                    for item in items:
                        text_div = item.find('div', class_='wprm-recipe-instruction-text')
                        if text_div:
                            step_text = text_div.get_text(separator=' ', strip=True)
                            step_text = self.clean_instruction_step(step_text)
                            if step_text:
                                steps.append(step_text)
        
        # Если не нашли в WPRM, ищем в wp-block-list (ordered list)
        if not steps:
            entry_content = self.soup.find('div', class_='entry-content')
            if entry_content:
                # Ищем заголовок с инструкциями
                for h2 in entry_content.find_all('h2', class_='wp-block-heading'):
                    heading_text = h2.get_text(strip=True).lower()
                    # Проверяем на "instructions" или "kaip"
                    if 'instruction' in heading_text or 'kaip' in heading_text or 'how to' in heading_text:
                        # Берем следующий ol список
                        next_list = h2.find_next_sibling('ol', class_='wp-block-list')
                        if next_list:
                            items = next_list.find_all('li', recursive=False)
                            for item in items:
                                step_text = item.get_text(separator=' ', strip=True)
                                step_text = self.clean_instruction_step(step_text)
                                if step_text:
                                    steps.append(step_text)
                            break
                
                # Если не нашли по заголовку, берем первый ordered list
                if not steps:
                    first_ol = entry_content.find('ol', class_='wp-block-list')
                    if first_ol:
                        items = first_ol.find_all('li', recursive=False)
                        for item in items:
                            step_text = item.get_text(separator=' ', strip=True)
                            step_text = self.clean_instruction_step(step_text)
                            if step_text:
                                steps.append(step_text)
        
        # Добавляем нумерацию если её нет
        # Проверяем первый шаг - если у него нет номера, добавляем ко всем
        if steps and not re.match(r'^\d+\.', steps[0]):
            steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
        
        return ' '.join(steps) if steps else None
    
    def clean_instruction_step(self, text: str) -> str:
        """Очистка текста инструкции от заголовков и лишнего"""
        if not text:
            return text
        
        text = self.clean_text(text)
        
        # Удаляем заголовки шагов которые заканчиваются точкой и пробелом
        # Паттерн: слова с заглавной буквы, заканчивающиеся точкой, затем пробел и остальной текст
        # Например: "Sumaišykite ingredientus. Į nedidelį dubenį..." -> "Į nedidelį dubenį..."
        # Проверяем, что после первой точки есть еще текст
        if '.' in text:
            parts = text.split('.', 1)
            if len(parts) == 2 and len(parts[0]) < 50 and len(parts[1].strip()) > 20:
                # Первая часть короткая (вероятно заголовок), вторая длинная (сам текст)
                # Проверяем что первая часть начинается с заглавной
                if parts[0] and parts[0][0].isupper():
                    return parts[1].strip()
        
        return text
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                # Обрабатываем @graph структуру
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list) and sections:
                                return self.clean_text(sections[0])
                            elif isinstance(sections, str):
                                return self.clean_text(sections)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', attrs={'aria-label': 'Breadcrumb'})
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            # Берем последнюю категорию перед рецептом (обычно предпоследняя ссылка)
            if len(links) > 1:
                category_link = links[-1]
                category = category_link.get_text(strip=True)
                if category and category.lower() not in ['home', 'pradžia', 'pagrindinis']:
                    return self.clean_text(category)
        
        # Ищем в классах article
        article = self.soup.find('article')
        if article and article.get('class'):
            for cls in article['class']:
                if cls.startswith('category-'):
                    category = cls.replace('category-', '').replace('-', ' ')
                    return self.clean_text(category)
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Ищем в WPRM recipe container
        recipe_container = self.soup.find('div', class_=lambda x: x and 'wprm-recipe-container' in x)
        if recipe_container:
            class_map = {
                'prep': 'wprm-recipe-prep_time',
                'cook': 'wprm-recipe-cook_time',
                'total': 'wprm-recipe-total_time'
            }
            
            class_name = class_map.get(time_type)
            if class_name:
                time_elem = recipe_container.find('span', class_=class_name)
                if time_elem:
                    time_text = time_elem.get_text(strip=True)
                    return self.clean_text(time_text)
        
        # Если не нашли, пробуем в meta данных
        # Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            time_keys = {
                                'prep': 'prepTime',
                                'cook': 'cookTime',
                                'total': 'totalTime'
                            }
                            key = time_keys.get(time_type)
                            if key and key in item:
                                # Конвертируем ISO duration в минуты
                                iso_time = item[key]
                                return self.parse_iso_duration(iso_time)
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
            Время в читаемом формате, например "1 hour 30 minutes" или "90 minutes"
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
        
        # Форматируем результат с правильной грамматикой
        parts = []
        if hours > 0:
            hour_word = "hour" if hours == 1 else "hours"
            parts.append(f"{hours} {hour_word}")
        if minutes > 0:
            minute_word = "minute" if minutes == 1 else "minutes"
            parts.append(f"{minutes} {minute_word}")
        
        return ' '.join(parts) if parts else None
    
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
        notes = []
        
        # Ищем в WPRM recipe container
        recipe_container = self.soup.find('div', class_=lambda x: x and 'wprm-recipe-container' in x)
        if recipe_container:
            notes_section = recipe_container.find('div', class_='wprm-recipe-notes-container')
            if notes_section:
                notes_text = notes_section.get_text(separator=' ', strip=True)
                if notes_text:
                    return self.clean_text(notes_text)
        
        # Ищем секцию с советами в основном контенте
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            # Ищем секцию "Recipe Tips" или "Patarimai"
            for section in entry_content.find_all('div', class_='mainsection'):
                heading = section.find(['h2', 'h3'])
                if heading:
                    heading_text = heading.get_text(strip=True).lower()
                    if 'patarima' in heading_text or 'tip' in heading_text:
                        # Извлекаем все списки в этой секции
                        lists = section.find_all('ul', class_='wp-block-list')
                        for lst in lists:
                            items = lst.find_all('li')
                            for item in items:
                                tip_text = item.get_text(separator=' ', strip=True)
                                # Берем только заголовок (до первой точки после заголовка)
                                tip_text = self.clean_text(tip_text)
                                if tip_text:
                                    # Разбиваем по точкам и берем первое предложение
                                    first_part = tip_text.split('.')[0]
                                    if first_part and len(first_part) > 10:
                                        notes.append(first_part)
                        
                        # Ограничиваем до 3 советов
                        if notes:
                            return '. '.join(notes[:3]) + '.'
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'keywords' in item:
                            keywords = item['keywords']
                            if isinstance(keywords, list):
                                tags.extend([self.clean_text(k) for k in keywords if k])
                            elif isinstance(keywords, str):
                                # Разделяем по запятым
                                tags.extend([self.clean_text(k.strip()) for k in keywords.split(',') if k.strip()])
                            break
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если не нашли в JSON-LD, ищем в meta keywords
        if not tags:
            meta_keywords = self.soup.find('meta', {'name': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                keywords = meta_keywords['content']
                tags = [self.clean_text(k.strip()) for k in keywords.split(',') if k.strip()]
        
        # Ищем теги в классах article
        if not tags:
            article = self.soup.find('article')
            if article and article.get('class'):
                for cls in article['class']:
                    if cls.startswith('tag-'):
                        tag = cls.replace('tag-', '').replace('-', ' ')
                        tags.append(self.clean_text(tag))
        
        # Удаляем дубликаты
        if tags:
            seen = set()
            unique_tags = []
            for tag in tags:
                tag_lower = tag.lower()
                if tag_lower not in seen:
                    seen.add(tag_lower)
                    unique_tags.append(tag)
            
            return ', '.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
                        # Article с primaryImageOfPage
                        elif item.get('@type') == 'Article' and 'primaryImageOfPage' in item:
                            img = item['primaryImageOfPage']
                            if isinstance(img, dict) and 'url' in img:
                                urls.append(img['url'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 3. Ищем featured image в контенте
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            # Ищем wp-post-image
            post_image = entry_content.find('img', class_='wp-post-image')
            if post_image and post_image.get('src'):
                urls.append(post_image['src'])
            
            # Ищем первые изображения в wp-block-image
            image_blocks = entry_content.find_all('figure', class_='wp-block-image', limit=3)
            for block in image_blocks:
                img = block.find('img')
                if img and img.get('src'):
                    urls.append(img['src'])
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
                    if len(unique_urls) >= 3:  # Ограничиваем до 3 изображений
                        break
            
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
            "instructions": self.extract_steps(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Обработка директории с HTML файлами для pasaulioreceptai.lt"""
    import os
    
    # Определяем путь к директории с примерами
    base_dir = Path(__file__).parent.parent
    preprocessed_dir = base_dir / "preprocessed" / "pasaulioreceptai_lt"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обрабатываем директорию: {preprocessed_dir}")
        process_directory(PasaulioreceptaiExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python pasaulioreceptai_lt.py")


if __name__ == "__main__":
    main()
