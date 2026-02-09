"""
Экстрактор данных рецептов для сайта bonapeti.rs
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


# Serbian units pattern for ingredient parsing (non-capturing group)
SERBIAN_UNITS_PATTERN = (
    r'(?:g|gr|grama|kg|kilograma|ml|mililitara|l|litara|dl|decilitara|'
    r'kašika|kašike|kašičica|kašičice|'
    r'čaša|čaše|šolja|šolje|'
    r'komad|komada|kom|'
    r'pakovanje|paket|kesica|kesice|'
    r'glavica|glavice|čen|čena|'
    r'prstohvat|štipka|'
    r'cup|cups|tbsp|tsp|tablespoon|teaspoon|pound|lb|oz|ounce)'
)


class BonapetiRsExtractor(BaseRecipeExtractor):
    """Экстрактор для bonapeti.rs"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Пробуем найти в JSON-LD
        json_ld = self._extract_json_ld()
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " | BonApeti", " - Bonapeti"
            title = re.sub(r'\s+[\|\-]\s+(BonApeti|Bonapeti).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            title = re.sub(r'\s+[\|\-]\s+(BonApeti|Bonapeti).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Пробуем извлечь из JSON-LD
        json_ld = self._extract_json_ld()
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
        
        # Ищем описание в div/p с классами типа intro, description, summary
        for class_name in ['recipe-intro', 'intro', 'description', 'summary', 'excerpt']:
            elem = self.soup.find(['div', 'p'], class_=re.compile(class_name, re.I))
            if elem:
                return self.clean_text(elem.get_text())
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Пробуем извлечь из JSON-LD
        json_ld = self._extract_json_ld()
        if json_ld and 'recipeIngredient' in json_ld:
            ing_list = json_ld['recipeIngredient']
            if isinstance(ing_list, list):
                for ing_text in ing_list:
                    parsed = self.parse_ingredient(ing_text)
                    if parsed:
                        ingredients.append(parsed)
                if ingredients:
                    return json.dumps(ingredients, ensure_ascii=False)
        
        # Ищем список ингредиентов в HTML
        # Пробуем различные селекторы
        ingredient_containers = [
            self.soup.find('ul', class_=re.compile(r'ingredient', re.I)),
            self.soup.find('div', class_=re.compile(r'ingredient', re.I)),
            self.soup.find('ul', attrs={'itemprop': 'recipeIngredient'}),
        ]
        
        # Также ищем по заголовкам (Sastojci, Ingredients, Namirnice)
        for header_text in ['Sastojci', 'Ingredients', 'Namirnice', 'Sastojci:']:
            header = self.soup.find(lambda tag: tag.name in ['h2', 'h3', 'h4', 'strong', 'b'] and header_text.lower() in tag.get_text().lower())
            if header:
                # Ищем список после заголовка
                next_ul = header.find_next('ul')
                if next_ul:
                    ingredient_containers.append(next_ul)
                    break
        
        for container in ingredient_containers:
            if not container:
                continue
                
            # Извлекаем элементы списка
            items = container.find_all('li')
            if not items:
                items = container.find_all('p')
            
            for item in items:
                # Извлекаем текст ингредиента
                ingredient_text = item.get_text(separator=' ', strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                # Пропускаем заголовки секций (часто содержат двоеточие)
                if ingredient_text and not ingredient_text.endswith(':'):
                    # Парсим в структурированный формат
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
            
            if ingredients:
                break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld = self._extract_json_ld()
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        steps.append(f"{idx}. {self.clean_text(step['text'])}")
                    elif isinstance(step, str):
                        steps.append(f"{idx}. {self.clean_text(step)}")
            elif isinstance(instructions, str):
                return self.clean_text(instructions)
            
            if steps:
                return ' '.join(steps)
        
        # Если JSON-LD не помог, ищем в HTML
        instructions_containers = [
            self.soup.find('ol', class_=re.compile(r'instruction', re.I)),
            self.soup.find('div', class_=re.compile(r'instruction', re.I)),
            self.soup.find('ol', attrs={'itemprop': 'recipeInstructions'}),
        ]
        
        # Также ищем по заголовкам (Priprema, Instructions, Način pripreme)
        for header_text in ['Priprema', 'Instructions', 'Način pripreme', 'Priprema:']:
            header = self.soup.find(lambda tag: tag.name in ['h2', 'h3', 'h4', 'strong', 'b'] and header_text.lower() in tag.get_text().lower())
            if header:
                # Ищем список после заголовка
                next_ol = header.find_next(['ol', 'ul'])
                if next_ol:
                    instructions_containers.append(next_ol)
                    break
        
        for container in instructions_containers:
            if not container:
                continue
            
            # Извлекаем шаги
            step_items = container.find_all('li')
            if not step_items:
                step_items = container.find_all('p')
            
            for item in step_items:
                # Извлекаем текст инструкции
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    steps.append(step_text)
            
            if steps:
                break
        
        # Если нумерация не была в HTML, добавляем её
        if steps and not re.match(r'^\d+\.', steps[0]):
            steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Пробуем извлечь из JSON-LD
        json_ld = self._extract_json_ld()
        if json_ld:
            if 'recipeCategory' in json_ld:
                return self.clean_text(json_ld['recipeCategory'])
            if 'recipeCuisine' in json_ld:
                return self.clean_text(json_ld['recipeCuisine'])
        
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if not breadcrumbs:
            breadcrumbs = self.soup.find('div', class_=re.compile(r'breadcrumb', re.I))
        
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:  # Берем последнюю категорию перед самим рецептом
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self._extract_time('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self._extract_time('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self._extract_time('total')
    
    def _extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Сначала пробуем извлечь из JSON-LD
        json_ld = self._extract_json_ld()
        if json_ld:
            time_keys = {
                'prep': 'prepTime',
                'cook': 'cookTime',
                'total': 'totalTime'
            }
            
            key = time_keys.get(time_type)
            if key and key in json_ld:
                iso_time = json_ld[key]
                return self._parse_iso_duration(iso_time)
        
        # Если JSON-LD не помог, ищем в HTML
        time_patterns = {
            'prep': ['prep.*time', 'preparation', 'priprema', 'vreme.*pripreme'],
            'cook': ['cook.*time', 'cooking', 'pečenje', 'kuvanje'],
            'total': ['total.*time', 'ready.*in', 'ukupno.*vreme']
        }
        
        patterns = time_patterns.get(time_type, [])
        
        for pattern in patterns:
            # Ищем элемент с временем
            time_elem = self.soup.find(class_=re.compile(pattern, re.I))
            if not time_elem:
                time_elem = self.soup.find(attrs={'itemprop': re.compile(pattern, re.I)})
            
            if time_elem:
                time_text = time_elem.get_text(strip=True)
                return self.clean_text(time_text)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями/советами
        for class_pattern in ['note', 'tip', 'saveti', 'napomene']:
            notes_section = self.soup.find(class_=re.compile(class_pattern, re.I))
            
            if notes_section:
                # Сначала пробуем найти параграф внутри (без заголовка)
                p = notes_section.find('p')
                if p:
                    text = self.clean_text(p.get_text())
                    return text if text else None
                
                # Если нет параграфа, берем весь текст
                text = notes_section.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Пробуем извлечь из JSON-LD
        json_ld = self._extract_json_ld()
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if isinstance(keywords, str):
                tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            elif isinstance(keywords, list):
                tags_list = [str(tag).strip() for tag in keywords if tag]
        
        # Если не нашли в JSON-LD, ищем в meta keywords
        if not tags_list:
            meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                tags_string = meta_keywords['content']
                tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        # Ищем в meta parsely-tags
        if not tags_list:
            parsely_meta = self.soup.find('meta', attrs={'name': 'parsely-tags'})
            if parsely_meta and parsely_meta.get('content'):
                tags_string = parsely_meta['content']
                tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        # Ищем теги в article:tag мета-тегах
        if not tags_list:
            tag_metas = self.soup.find_all('meta', property='article:tag')
            if tag_metas:
                tags_list = [meta['content'].strip() for meta in tag_metas if meta.get('content')]
        
        if not tags_list:
            return None
        
        # Фильтрация и очистка
        filtered_tags = []
        stopwords = {'recipe', 'recipes', 'bonapeti', 'recept', 'recepti'}
        
        for tag in tags_list:
            tag = tag.lower().strip()
            # Пропускаем стоп-слова и короткие теги
            if tag not in stopwords and len(tag) >= 3:
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
        
        # 1. Пробуем извлечь из JSON-LD
        json_ld = self._extract_json_ld()
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
        
        # 2. Ищем в мета-тегах
        if not urls:
            # og:image - обычно главное изображение
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
            
            # twitter:image
            twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
            if twitter_image and twitter_image.get('content'):
                urls.append(twitter_image['content'])
        
        # 3. Ищем в HTML - изображения рецепта
        if not urls:
            # Ищем изображения с itemprop="image"
            img_with_itemprop = self.soup.find('img', attrs={'itemprop': 'image'})
            if img_with_itemprop and img_with_itemprop.get('src'):
                urls.append(img_with_itemprop['src'])
            
            # Ищем изображения в блоке рецепта
            recipe_container = self.soup.find(['div', 'article'], class_=re.compile(r'recipe', re.I))
            if recipe_container:
                images = recipe_container.find_all('img')
                for img in images[:3]:  # Берем первые 3
                    if img.get('src'):
                        urls.append(img['src'])
        
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
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "200 g brašna" или "2 jaja"
            
        Returns:
            dict: {"name": "brašno", "amount": "200", "unit": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).strip()
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "200 g brašna", "2 jaja", "1 kašičica soli", "1/2 šolje mleka"
        pattern = r'^([\d\s/.,\-]+)?\s*(' + SERBIAN_UNITS_PATTERN + r')?\s*(.+)'
        
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
                        fraction_parts = part.split('/')
                        if len(fraction_parts) == 2:
                            try:
                                num, denom = fraction_parts
                                total += float(num) / float(denom)
                            except (ValueError, ZeroDivisionError):
                                # Skip malformed fractions
                                pass
                    else:
                        try:
                            total += float(part)
                        except ValueError:
                            pass
                amount = str(total) if total != int(total) else str(int(total))
            else:
                amount = amount_str.replace(',', '.')
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "po ukusu", "po želji", "opciono"
        name = re.sub(r'\b(po ukusu|po želji|opciono|optional|as needed|to taste)\b', '', name, flags=re.IGNORECASE)
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
    
    def _extract_json_ld(self) -> Optional[dict]:
        """Извлечение данных из JSON-LD"""
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
                
                # Ищем рецепт в данных
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if is_recipe(item):
                            recipe_data = item
                            break
                elif isinstance(data, dict):
                    if is_recipe(data):
                        recipe_data = data
                    elif '@graph' in data:
                        for item in data['@graph']:
                            if is_recipe(item):
                                recipe_data = item
                                break
                
                if recipe_data:
                    return recipe_data
                    
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах, например "90 minutes"
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
            return f"{total_minutes} minutes"
        
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
    Основная функция для обработки HTML файлов из директории preprocessed/bonapeti_rs
    """
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join("preprocessed", "bonapeti_rs")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(BonapetiRsExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python bonapeti_rs.py")
    print("Убедитесь, что директория 'preprocessed/bonapeti_rs' существует и содержит HTML файлы.")


if __name__ == "__main__":
    main()
