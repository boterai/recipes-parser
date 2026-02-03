"""
Экстрактор данных рецептов для сайта recepty.eu
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ReceptyEuExtractor(BaseRecipeExtractor):
    """Экстрактор для recepty.eu"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT24H"
            
        Returns:
            Время в читаемом формате, например "1 hour", "20 minutes", "24 hours"
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
            parts.append(f"{hours} hour" + ("s" if hours > 1 else ""))
        if minutes > 0:
            parts.append(f"{minutes} minute" + ("s" if minutes > 1 else ""))
        
        return " ".join(parts) if parts else None
    
    def is_search_results_page(self) -> bool:
        """Проверка, является ли страница страницей поиска/списка рецептов"""
        # Проверяем наличие полноценного рецепта (JSON-LD Recipe или itemprop ingredients)
        has_full_recipe = False
        
        # Проверяем JSON-LD Recipe
        recipe_data = self.get_json_ld_recipe()
        if recipe_data:
            has_full_recipe = True
        
        # Проверяем itemprop="recipeIngredient"
        if not has_full_recipe:
            ingredients = self.soup.find_all('li', itemprop='recipeIngredient')
            if ingredients:
                has_full_recipe = True
        
        # Если есть полноценный рецепт, это не страница поиска
        if has_full_recipe:
            return False
        
        # Если нет полноценного рецепта, но есть recipe-box, это страница поиска
        recipe_boxes = self.soup.find_all('div', class_='recipe-box')
        return len(recipe_boxes) > 0
    
    def extract_ingredients_from_text(self, text: str) -> Optional[str]:
        """
        Извлечение ингредиентов из текста инструкций (для поисковых страниц)
        
        Args:
            text: Текст с упоминанием ингредиентов
            
        Returns:
            JSON строка с ингредиентами или None
        """
        if not text:
            return None
        
        ingredients = []
        
        # Паттерны для извлечения ингредиентов с количеством
        # Пример: "150 ml vody" -> voda: 150 ml
        # Используем \w для букв (включает латиницу и unicode буквы)
        pattern_with_amount = r'(\d+(?:[.,]\d+)?)\s*(ml|g|kg|l|dl|lžic|lžíce|lžička|lžiček|stroužky|stroužek|svazek|plát)\s+([\wáčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]+)'
        matches = re.finditer(pattern_with_amount, text, re.IGNORECASE)
        
        found_ingredients = set()
        for match in matches:
            amount = match.group(1)
            unit = match.group(2)
            name = match.group(3)
            
            # Нормализуем название (родительный падеж -> именительный)
            # vody -> voda, víno остается víno
            if name.endswith('y'):
                name = name[:-1] + 'a'
            
            ingredient_key = name.lower()
            if ingredient_key not in found_ingredients:
                found_ingredients.add(ingredient_key)
                ingredients.append({
                    "name": name,
                    "amount": amount,
                    "units": unit
                })
        
        # Ищем упоминания ингредиентов без количества
        # Паттерны глаголов с ингредиентами: "osolíme" (мы солим) -> sůl (соль)
        verb_to_ingredient = {
            r'osol[íi]me': ('sůl', None, None),  # солим -> соль
            r'op[eě]p[rř][íi]me': ('pepř', None, None),  # перчим -> перец
        }
        
        for verb_pattern, (ingredient_name, amount, unit) in verb_to_ingredient.items():
            if re.search(verb_pattern, text, re.IGNORECASE):
                if ingredient_name.lower() not in found_ingredients:
                    found_ingredients.add(ingredient_name.lower())
                    ingredients.append({
                        "name": ingredient_name,
                        "amount": amount,
                        "units": unit
                    })
        
        # Ищем общие упоминания ингредиентов
        # Например: "kuřecí prsíčka", "víno"
        common_ingredients = [
            r'ku[rř]ec[ií]\s+prs[ií][čc]ka',  # куриные грудки
            r'v[ií]no',  # вино
            r'olej',  # масло
            r'cibul[ek]',  # лук
            r'česnek',  # чеснок
        ]
        
        for pattern in common_ingredients:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                ingredient_text = match.group(0)
                ingredient_key = ingredient_text.lower()
                if ingredient_key not in found_ingredients:
                    found_ingredients.add(ingredient_key)
                    ingredients.append({
                        "name": ingredient_text,
                        "amount": None,
                        "units": None
                    })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_first_recipe_from_search(self) -> dict:
        """Извлечение данных первого рецепта из страницы поиска"""
        recipe_boxes = self.soup.find_all('div', class_='recipe-box')
        if not recipe_boxes:
            return self._empty_recipe()
        
        first_recipe = recipe_boxes[0]
        
        # Извлекаем название
        dish_name = None
        h4 = first_recipe.find('h4')
        if h4:
            link = h4.find('a')
            if link:
                dish_name = self.clean_text(link.get_text())
        
        # Извлекаем описание/превью инструкций
        description = None
        instructions = None
        preview_p = first_recipe.find('p', class_='mt-4')
        if preview_p:
            text = self.clean_text(preview_p.get_text())
            # Убираем подсвеченные фрагменты
            text = re.sub(r'\s+', ' ', text)
            instructions = text
        
        # Извлекаем категорию из тега (берем первый непустой тег)
        category = None
        tag_links = first_recipe.find_all('a', class_='tag')
        for tag_link in tag_links:
            cat_text = tag_link.get_text(strip=True)
            cat_text = re.sub(r'^#', '', cat_text)
            cat_text = self.clean_text(cat_text)
            if cat_text:  # Берем первый непустой тег
                category = cat_text
                break
        
        # Извлекаем изображение
        image_urls = None
        img = first_recipe.find('img', class_='image')
        if img and img.get('src'):
            image_urls = img['src']
        
        # Извлекаем теги (все теги на странице могут быть связаны)
        tags = self.extract_tags()
        
        # Пытаемся извлечь ингредиенты из текста инструкций
        ingredients = None
        if instructions:
            ingredients = self.extract_ingredients_from_text(instructions)
        
        return {
            "dish_name": dish_name,
            "description": None,  # На странице поиска нет полного описания
            "ingredients": ingredients,  # Извлекаем из текста инструкций
            "instructions": instructions,
            "category": category,
            "prep_time": None,
            "cook_time": None,
            "total_time": None,
            "notes": None,
            "tags": tags,
            "image_urls": image_urls
        }
    
    def _empty_recipe(self) -> dict:
        """Возвращает пустой словарь рецепта"""
        return {
            "dish_name": None,
            "description": None,
            "ingredients": None,
            "instructions": None,
            "category": None,
            "prep_time": None,
            "cook_time": None,
            "total_time": None,
            "notes": None,
            "tags": None,
            "image_urls": None
        }
    
    def get_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение данных из JSON-LD Recipe schema"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                # Проверяем, есть ли Recipe в данных
                if isinstance(data, dict):
                    if data.get('@type') == 'Recipe':
                        return data
                    # Проверяем в @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and item.get('@type') == 'Recipe':
                                return item
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " recepty - recepty.eu"
            title = re.sub(r'\s*(-|–)\s*recepty\.eu.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'^.*?\s*Nejlepší\s+', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s+recepty\s*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Ищем в breadcrumb
        breadcrumb = self.soup.find('span', itemprop='name')
        if breadcrumb:
            return self.clean_text(breadcrumb.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала проверяем JSON-LD - иногда в начале recipeInstructions есть описание
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            # Если инструкции обрезаны (...), вероятно это описание
            if isinstance(instructions, str) and len(instructions) < 200:
                # Убираем многоточие
                desc = re.sub(r'…$', '', instructions)
                return self.clean_text(desc)
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', property='og:description')
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Убираем шаблонный текст "Doporučené recepty:"
            desc = re.sub(r'^Doporučené recepty:.*?-\s*', '', desc, flags=re.IGNORECASE)
            # Убираем список рецептов в конце
            desc = re.sub(r'\s*☑️.*$', '', desc)
            if desc and len(desc) > 50:
                return None  # Это не описание, а мета-описание страницы
        
        # Ищем первый параграф в инструкциях, если он описательный
        instructions_ol = self.soup.find('ol', class_='mb-3')
        if instructions_ol:
            first_li = instructions_ol.find('li')
            if first_li:
                text = self.clean_text(first_li.get_text())
                # Если первый шаг начинается как описание (более 50 символов и не начинается с действия)
                if len(text) > 50 and not re.match(r'^(Naře|Nakrá|Smíchá|Uvař|Opečeme|Přidá)', text):
                    return text
        
        return None
    
    def parse_ingredient_text(self, ingredient_text: str) -> dict:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "vepřové maso (kotleta)" или "5 lžic tmavé sójové omáčky"
            
        Returns:
            dict: {"name": "...", "amount": "...", "units": "..."}
        """
        if not ingredient_text:
            return {"name": None, "amount": None, "units": None}
        
        text = self.clean_text(ingredient_text)
        
        # Czech units patterns
        # Паттерн для извлечения количества и единицы измерения в начале строки
        # Примеры: "5 lžic", "450 g", "1 svazek", "2 stroužky", "150 ml"
        amount = None
        units = None
        name = text
        
        # Пробуем извлечь количество и единицу в начале
        # Паттерн: число (может быть с дробью или десятичной точкой) + опциональная единица
        # Используем \w для букв (включает латиницу и unicode буквы)
        pattern = r'^(\d+(?:[.,/]\d+)?)\s*([\wáčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]+)?\s+(.+)$'
        match = re.match(pattern, text)
        
        if match:
            amount_str = match.group(1)
            unit_str = match.group(2)
            name_str = match.group(3)
            
            # Преобразуем amount (заменяем запятую на точку для дробей)
            amount_str = amount_str.replace(',', '.')
            
            # Проверяем, является ли "единица" действительно единицей измерения
            # или это часть названия ингредиента
            if unit_str and unit_str.lower() in [
                'g', 'kg', 'ml', 'l', 'dl', 'cl',
                'lžic', 'lžíce', 'lžička', 'lžiček', 'lžičky',
                'hrnek', 'hrnků', 'hrneček',
                'stroužek', 'stroužky', 'stroužků',
                'svazek', 'svazků',
                'plát', 'pláty', 'plátků',
                'kus', 'kusy', 'kusů',
                'velký', 'velké', 'velká', 'malý', 'malé', 'malá',
                'tenký', 'tenké', 'tenká'
            ]:
                amount = amount_str
                units = unit_str
                name = name_str
            else:
                # "Единица" - это часть названия
                name = text
        
        # Обрабатываем скобки в названии
        # Пример: "vepřové maso (kotleta)" -> name="vepřové maso (kotleta)"
        # Сохраняем скобки как есть
        
        return {
            "name": name if name else None,
            "amount": amount,
            "units": units
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем из HTML (более детальная информация)
        ingredient_items = self.soup.find_all('li', itemprop='recipeIngredient')
        
        if ingredient_items:
            for item in ingredient_items:
                ingredient_text = item.get_text(strip=True)
                if ingredient_text:
                    parsed = self.parse_ingredient_text(ingredient_text)
                    if parsed and parsed['name']:
                        ingredients.append(parsed)
        
        # Если не нашли в HTML, пробуем из JSON-LD
        if not ingredients:
            recipe_data = self.get_json_ld_recipe()
            if recipe_data and 'recipeIngredient' in recipe_data:
                for ingredient_text in recipe_data['recipeIngredient']:
                    if ingredient_text:
                        parsed = self.parse_ingredient_text(ingredient_text)
                        if parsed and parsed['name']:
                            ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем в HTML - в <ol class="mb-3">
        instructions_ol = self.soup.find('ol', class_='mb-3')
        
        if instructions_ol:
            step_items = instructions_ol.find_all('li')
            
            for item in step_items:
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    steps.append(step_text)
        
        # Если не нашли в HTML, пробуем из JSON-LD (но там часто обрезано)
        if not steps:
            recipe_data = self.get_json_ld_recipe()
            if recipe_data and 'recipeInstructions' in recipe_data:
                instructions = recipe_data['recipeInstructions']
                if isinstance(instructions, str):
                    # Убираем многоточие если есть
                    instructions = re.sub(r'…$', '', instructions)
                    steps.append(instructions)
        
        # Объединяем шаги в одну строку
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем из JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'recipeCategory' in recipe_data:
            return self.clean_text(recipe_data['recipeCategory'])
        
        # Альтернативно - из breadcrumb (первая категория)
        breadcrumbs = self.soup.find_all('li', itemtype='http://schema.org/ListItem')
        if breadcrumbs and len(breadcrumbs) > 0:
            # Берем первый элемент breadcrumb (обычно это категория)
            first_crumb = breadcrumbs[0]
            name_span = first_crumb.find('span', itemprop='name')
            if name_span:
                return self.clean_text(name_span.get_text())
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Сначала пробуем из JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'totalTime' in recipe_data:
            iso_time = recipe_data['totalTime']
            return self.parse_iso_duration(iso_time)
        
        # Альтернативно - из HTML meta тега
        time_meta = self.soup.find('meta', itemprop='totalTime')
        if time_meta and time_meta.get('content'):
            return self.parse_iso_duration(time_meta['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Для recepty.eu обычно нет отдельного prep_time
        # Проверяем в JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'prepTime' in recipe_data:
            iso_time = recipe_data['prepTime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Для recepty.eu обычно есть только totalTime
        # Но иногда может быть указано в тексте
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'cookTime' in recipe_data:
            iso_time = recipe_data['cookTime']
            return self.parse_iso_duration(iso_time)
        
        # Если есть только total_time, используем его как cook_time
        return self.extract_total_time()
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # В recepty.eu обычно нет отдельной секции с заметками
        # Проверяем, есть ли какие-то дополнительные секции
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем теги в ссылках с классом "tag"
        # Но избегаем ссылок типа "Další recepty jako..."
        tag_links = self.soup.find_all('a', class_='tag')
        
        for link in tag_links:
            href = link.get('href', '')
            # Пропускаем ссылки на поиск похожих рецептов
            if 'recepty+' in href:
                continue
            
            # Извлекаем текст тега
            text = link.get_text(strip=True)
            # Убираем символ # если есть
            text = re.sub(r'^#', '', text)
            text = self.clean_text(text)
            
            if text and len(text) > 2:
                tags.append(text.lower())
        
        # Удаляем дубликаты
        seen = set()
        unique_tags = []
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            if isinstance(img, dict) and 'url' in img:
                urls.append(img['url'])
            elif isinstance(img, str):
                urls.append(img)
        
        # 2. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
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
        # Проверяем, является ли это страницей поиска
        if self.is_search_results_page():
            return self.extract_first_recipe_from_search()
        
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
    """Обработка всех HTML файлов в preprocessed/recepty_eu"""
    import os
    
    # Путь к директории с preprocessed файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), 
        "preprocessed", 
        "recepty_eu"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ReceptyEuExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python recepty_eu.py")


if __name__ == "__main__":
    main()
