"""
Экстрактор данных рецептов для сайта recepttar.kiskegyed.hu
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class RecepttarKiskegyedHuExtractor(BaseRecipeExtractor):
    """Экстрактор для recepttar.kiskegyed.hu"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe' and 'name' in data:
                    name = data['name']
                    # Убираем суффиксы типа " hagyományosan", " - sütés nélkül" и т.д.
                    name = re.sub(r'\s+(hagyományosan|recept|receptje)$', '', name, flags=re.IGNORECASE)
                    name = re.sub(r'\s+-\s+sütés\s+nélkül$', '', name, flags=re.IGNORECASE)
                    return self.clean_text(name)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из h1
        h1 = self.soup.find('h1')
        if h1:
            name = h1.get_text()
            name = re.sub(r'\s+-\s+sütés\s+nélkül$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\s+(hagyományosan|recept|receptje)$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        # Из meta тега
        meta_name = self.soup.find('meta', itemprop='name')
        if meta_name and meta_name.get('content'):
            return self.clean_text(meta_name['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Description часто отсутствует в HTML, возвращаем None
        # (в эталонных JSON это поле содержит вручную добавленные описания)
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 kg burgonya" или "2 db tojás"
            
        Returns:
            dict: {"name": "burgonya", "amount": 1, "units": "kg"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1 kg burgonya", "2 db tojás", "25 dkg rétesliszt"
        # Hungarian units: kg, dkg, g, l, dl, ml, db (darab/piece), ek. (evőkanál/tablespoon), tk. (teáskanál/teaspoon), csomag, etc.
        pattern = r'^([\d\s/.,]+)?\s*(kg|dkg|g|l|dl|ml|db|darab|ek\.|tk\.|evőkanál|teáskanál|csomag|csomagok|pcs|pieces?|cup|cups?|teaspoon|tablespoon)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, units, name = match.groups()
        
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
                amount = total
            else:
                amount_str = amount_str.replace(',', '.')
                try:
                    amount = float(amount_str)
                    # If it's a whole number, convert to int
                    if amount == int(amount):
                        amount = int(amount)
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения
        units = units.strip() if units else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
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
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем секцию с ингредиентами (div.column_left с заголовком "Hozzávalók")
        column_left = self.soup.find('div', class_='column_left')
        
        if column_left:
            # Проверяем, что это действительно секция с ингредиентами
            # Может быть h4 или первый параграф
            has_ingredients_header = False
            
            h4 = column_left.find('h4')
            if h4:
                h4_text = h4.get_text().lower()
                if 'hozz' in h4_text and 'val' in h4_text:  # More robust check for "hozzávalók"
                    has_ingredients_header = True
            
            # Если нет h4, проверяем первый параграф
            if not has_ingredients_header:
                first_p = column_left.find('p')
                if first_p:
                    p_text = first_p.get_text().lower()
                    if 'hozz' in p_text and 'val' in p_text:
                        has_ingredients_header = True
            
            if has_ingredients_header:
                # Извлекаем все параграфы с ингредиентами
                for p in column_left.find_all('p'):
                    ingredient_text = p.get_text(separator=' ', strip=True)
                    ingredient_text = self.clean_text(ingredient_text)
                    
                    # Пропускаем заголовки секций (содержат "Hozzávalók", "Az alaphoz:", "A krémhez:" и т.д.)
                    if not ingredient_text:
                        continue
                    
                    text_lower = ingredient_text.lower()
                    if 'hozz' in text_lower and 'val' in text_lower:
                        continue
                    if ingredient_text.endswith(':') and len(ingredient_text) < 30:
                        continue
                    
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем секцию с инструкциями (div.column_right с заголовком "Elkészítés")
        # Обычно это первый div.column_right (второй может быть категории)
        column_rights = self.soup.find_all('div', class_='column_right')
        
        for column_right in column_rights:
            # Проверяем, что это действительно секция с инструкциями
            has_instructions_header = False
            
            h4 = column_right.find('h4')
            if h4:
                h4_text = h4.get_text().lower()
                if 'elk' in h4_text and 'sz' in h4_text:  # More robust check for "elkészítés"
                    has_instructions_header = True
            
            # Если нет h4, проверяем первый параграф
            if not has_instructions_header:
                first_p = column_right.find('p')
                if first_p:
                    p_text = first_p.get_text().lower()
                    if 'elk' in p_text and 'sz' in p_text:
                        has_instructions_header = True
            
            if has_instructions_header:
                # Извлекаем все параграфы с шагами
                for p in column_right.find_all('p'):
                    step_text = p.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    
                    # Пропускаем заголовок "Elkészítés" и "Elkészítési idő:"
                    if step_text:
                        text_lower = step_text.lower()
                        # Пропускаем короткий текст с "elkészítés"
                        if 'elk' in text_lower and 'sz' in text_lower and len(step_text) < 20:
                            continue
                        # Пропускаем строки типа "Elkészítési idő: 60 perc"
                        if text_lower.startswith('elk') and 'id' in text_lower and ':' in step_text:
                            continue
                        steps.append(step_text)
                
                # Если нашли инструкции, выходим
                if steps:
                    break
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Пробуем извлечь из секции категорий на странице
        categories_section = self.soup.find('div', class_='categories')
        if categories_section:
            # Ищем все ссылки
            links = categories_section.find_all('a')
            if links:
                # Ищем категорию, которая соответствует основным типам блюд
                category_keywords = {
                    'desszert': 'Dessert',
                    'leves': 'Soup',
                    'előétel': 'Appetizer',
                    'saláta': 'Salad',
                    'főétel': 'Main Course',
                    'második': 'Main Course',
                    'krumplis': 'Main Course',
                }
                
                for link in links:
                    cat_text = link.get_text().strip().lower()
                    for keyword, english in category_keywords.items():
                        if keyword in cat_text:
                            return english
                
                # Если не нашли по ключевым словам, берем первую не служебную категорию
                for link in links:
                    cat_text = self.clean_text(link.get_text())
                    # Пропускаем временные и общие категории
                    if cat_text and 'perc alatt' not in cat_text.lower() and 'ételek' not in cat_text.lower():
                        if len(cat_text) < 50:
                            return cat_text
        
        # Альтернативно - из JSON-LD (recipeCuisine)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'recipeCuisine' in data:
                        cuisine = data['recipeCuisine']
                        # Map Hungarian categories to English
                        category_map = {
                            'magyaros receptek': 'Main Course',
                            'desszert': 'Dessert',
                            'előétel': 'Appetizer',
                            'leves': 'Soup',
                            'saláta': 'Salad',
                        }
                        cuisine_lower = cuisine.lower()
                        if cuisine_lower in category_map:
                            return category_map[cuisine_lower]
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    # Маппинг типов времени на ключи JSON-LD
                    time_keys = {
                        'prep': 'prepTime',
                        'cook': 'cookTime',
                        'total': 'totalTime'
                    }
                    
                    key = time_keys.get(time_type)
                    if key and key in data:
                        time_value = data[key]
                        # Проверяем формат: может быть "60 perc alatt elkészülő ételek" или ISO формат
                        if 'perc' in time_value.lower():
                            # Извлекаем числа
                            match = re.search(r'(\d+)\s*perc', time_value, re.IGNORECASE)
                            if match:
                                minutes = match.group(1)
                                return f"{minutes} minutes"
                        return self.clean_text(time_value)
            except (json.JSONDecodeError, KeyError):
                continue
        
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
        # Заметки обычно находятся в первом <p> тегу в секции detail
        detail_section = self.soup.find('section', class_='detail')
        
        if detail_section:
            # Ищем первый <p> tag на верхнем уровне (не внутри column_left/column_right)
            first_p = detail_section.find('p', recursive=False)
            if first_p:
                text = self.clean_text(first_p.get_text())
                # Проверяем, что это не служебный текст
                if text and len(text) > 10 and 'hozzávalók' not in text.lower():
                    return text
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            text = self.clean_text(meta_desc['content'])
            # Пропускаем служебные описания
            if text and len(text) > 20 and 'receptje' not in text.lower() and 'recepttár' not in text.lower():
                return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Сначала пробуем извлечь из meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        # Если не нашли, пробуем из JSON-LD
        if not tags_list:
            json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
            
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and data.get('@type') == 'Recipe' and 'keywords' in data:
                        keywords = data['keywords']
                        if isinstance(keywords, list):
                            tags_list = [self.clean_text(kw).lower() for kw in keywords if kw]
                        elif isinstance(keywords, str):
                            tags_list = [tag.strip().lower() for tag in keywords.split(',') if tag.strip()]
                        break
                except (json.JSONDecodeError, KeyError):
                    continue
        
        if not tags_list:
            return None
        
        # Фильтрация: убираем слишком длинные теги (больше 50 символов)
        filtered_tags = []
        for tag in tags_list:
            tag = tag.lower().strip()
            if len(tag) > 50:
                continue
            # Пропускаем служебные теги
            if tag in ['recept', 'receptek', 'ételek']:
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
        
        # 1. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe' and 'image' in data:
                    img = data['image']
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, dict):
                        if 'url' in img:
                            urls.append(img['url'])
                        elif 'contentUrl' in img:
                            urls.append(img['contentUrl'])
                    elif isinstance(img, list):
                        urls.extend([i for i in img if isinstance(i, str)])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 2. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 3. Ищем itemprop="image"
        meta_image = self.soup.find('meta', itemprop='image')
        if meta_image and meta_image.get('content'):
            urls.append(meta_image['content'])
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            # Возвращаем первую или все через запятую (в зависимости от требований)
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
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Ищем директорию с HTML-страницами относительно корня репозитория
    repo_root = Path(__file__).parent.parent
    recipes_dir = repo_root / "preprocessed" / "recepttar_kiskegyed_hu"
    
    if recipes_dir.exists() and recipes_dir.is_dir():
        print(f"Обработка директории: {recipes_dir}")
        process_directory(RecepttarKiskegyedHuExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python recepttar_kiskegyed_hu.py")


if __name__ == "__main__":
    main()
