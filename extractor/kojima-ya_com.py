"""
Экстрактор данных рецептов для сайта kojima-ya.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KojimaYaExtractor(BaseRecipeExtractor):
    """Экстрактор для kojima-ya.com"""
    
    def extract_json_ld(self) -> Optional[dict]:
        """Извлечение данных из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                json_str = script.string
                if not json_str:
                    continue
                
                # Очищаем JavaScript комментарии построчно
                # Ищем // только после закрывающей кавычки, запятой, числа, true/false, или }
                lines = []
                for line in json_str.split('\n'):
                    # Паттерн: найти //, которому предшествует ", или , или цифра, или true/false/null, или }
                    match = re.search(r'(["\,\d\}]|true|false|null)\s*//.*$', line)
                    if match:
                        # Обрезаем строку до //
                        line = line[:match.end(1)]
                    lines.append(line)
                
                json_str = '\n'.join(lines)
                
                # Парсим с strict=False для разрешения управляющих символов
                data = json.loads(json_str, strict=False)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, KeyError, AttributeError) as e:
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из h1 на странице
        h1_title = self.soup.find('h1', class_='recipe_sg__tit')
        if h1_title:
            return self.clean_text(h1_title.get_text())
        
        # Альтернативно - из JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Или из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s+(作り方・レシピ|小島屋).*$', '', title)
            return self.clean_text(title)
        
        # Или из тега title
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            title = re.sub(r'\s+(作り方・レシピ|小島屋).*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из p.recipe_sg__subtit на странице
        subtitle = self.soup.find('p', class_='recipe_sg__subtit')
        if subtitle:
            text = self.clean_text(subtitle.get_text())
            # Убираем восклицательные знаки в конце и добавляем то, что из h1
            text = re.sub(r'[！!]+$', '', text)
            
            # Добавляем уточнение из названия блюда если есть
            h1_title = self.soup.find('h1', class_='recipe_sg__tit')
            if h1_title:
                dish_name = self.clean_text(h1_title.get_text())
                # Формируем описание с упоминанием блюда
                text = f"{text}の簡単な{dish_name}。"
            else:
                text = f"{text}。"
            
            return text
        
        # Альтернативно из JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'description' in json_ld:
            desc = json_ld['description']
            # Убираем префикс магазина
            desc = re.sub(r'^【.*?】\s*', '', desc)
            return self.clean_text(desc)
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Убираем префикс магазина
            desc = re.sub(r'^【.*?】\s*', '', desc)
            return self.clean_text(desc)
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            desc = re.sub(r'^【.*?】\s*', '', desc)
            return self.clean_text(desc)
        
        return None
    
    def parse_ingredient_text(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        Примеры: "ワイルドブルーベリー 130ｇ", "卵　1個", "レモン汁　少々(大さじ1程度)", "薄力粉　大さじ2", "バター(又はマーガリン)　50g"
        """
        if not ingredient_text:
            return None
        
        text = self.clean_text(ingredient_text)
        
        name = text
        amount = None
        unit = None
        
        # Паттерны для единиц измерения с числом
        patterns_with_number = [
            (r'([\d\.]+)\s*(ｇ|g|グラム)', 'g'),
            (r'([\d\.]+)\s*(cc|ml|ミリリットル)', 'cc'),
            (r'([\d\.]+)\s*(個)', '個'),
            (r'大さじ\s*([\d\.]+)', '大さじ'),
            (r'小さじ\s*([\d\.]+)', '小さじ'),
        ]
        
        # Проверяем паттерны с числом
        found = False
        for pattern, unit_norm in patterns_with_number:
            match = re.search(pattern, text)
            if match:
                amount = match.group(1)
                unit = unit_norm
                # Убираем количество и единицу из названия
                name = re.sub(pattern, '', text).strip()
                found = True
                break
        
        # Если не нашли паттерн с числом, проверяем без числа (少々, 適量, etc.)
        if not found:
            patterns_without_number = [
                (r'少々\([^)]*\)', '大さじ'),  # 少々(大さじ1程度) -> units=大さじ, amount=null
                (r'少々', '少々'),
                (r'適量', '適量'),
                (r'お好み量', 'お好み量'),
            ]
            
            for pattern, unit_val in patterns_without_number:
                match = re.search(pattern, text)
                if match:
                    unit = unit_val
                    name = re.sub(pattern, '', text).strip()
                    # Извлекаем число из скобок если есть (например, "大さじ1")
                    if unit == '大さじ':
                        paren_match = re.search(r'大さじ\s*([\d\.]+)', match.group(0))
                        if not paren_match:
                            # Если в скобках нет числа, оставляем amount=null
                            amount = None
                    found = True
                    break
        
        # Очистка названия
        # Убираем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        
        # Убираем символы разделители в начале/конце
        name = name.strip('　、，,')
        
        if not name:
            return None
        
        # Преобразуем amount в int если возможно, иначе оставляем как строку или None
        if amount is not None:
            try:
                # Пробуем сконвертировать в int
                amount_int = int(float(amount))
                if float(amount) == amount_int:
                    amount = amount_int
                else:
                    amount = float(amount)
            except ValueError:
                pass  # Оставляем как строку
        
        return {
            "name": name,
            "units": unit,
            "amount": amount
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # В JSON-LD kojima-ya.com ingredients находятся в recipeInstructions (они перепутаны)
        json_ld = self.extract_json_ld()
        if json_ld and 'recipeInstructions' in json_ld:
            instructions_data = json_ld['recipeInstructions']
            if isinstance(instructions_data, list):
                for item in instructions_data:
                    if isinstance(item, str):
                        parsed = self.parse_ingredient_text(item)
                        if parsed:
                            ingredients.append(parsed)
        
        # Если JSON-LD не помог, ищем в HTML
        if not ingredients:
            ingredient_list = self.soup.find('ul', class_='recipe_sg__material_list')
            if ingredient_list:
                items = ingredient_list.find_all('li', class_='recipe_sg__material_item')
                for item in items:
                    ingredient_text = item.get_text(strip=True)
                    parsed = self.parse_ingredient_text(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # В JSON-LD kojima-ya.com инструкции находятся в recipeingredient (они перепутаны)
        json_ld = self.extract_json_ld()
        if json_ld and 'recipeingredient' in json_ld:
            ingredients_data = json_ld['recipeingredient']
            if isinstance(ingredients_data, list):
                # Объединяем все шаги
                steps = []
                for item in ingredients_data:
                    if isinstance(item, str):
                        # Очищаем от HTML тегов
                        step = re.sub(r'<br\s*/?>', '\n', item)
                        step = re.sub(r'<[^>]+>', '', step)
                        step = self.clean_text(step)
                        if step:
                            steps.append(step)
                
                if steps:
                    return '\n'.join(steps)
        
        # Если JSON-LD не помог, ищем в HTML
        instructions_section = self.soup.find('div', class_='recipe_sg__process')
        if instructions_section:
            # Ищем все параграфы с инструкциями
            steps = []
            for p in instructions_section.find_all('p', class_='recipe_sg__process_txt'):
                step_text = p.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                if step_text:
                    steps.append(step_text)
            
            if steps:
                return '\n'.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        json_ld = self.extract_json_ld()
        if json_ld and 'recipeCategory' in json_ld:
            category = json_ld['recipeCategory']
            # Берем первую категорию, обычно "お菓子" (Dessert)
            if isinstance(category, str):
                categories = [cat.strip() for cat in category.split(',')]
                if categories:
                    # Преобразуем японские категории в английские
                    first_cat = categories[0]
                    if first_cat == 'お菓子':
                        return 'Dessert'
                    elif first_cat in ['メインディッシュ', 'メイン']:
                        return 'Main Course'
                    elif first_cat == '前菜':
                        return 'Appetizer'
                    elif first_cat == 'サラダ':
                        return 'Salad'
                    elif first_cat == 'スープ':
                        return 'Soup'
                    else:
                        return first_cat
        
        return None
    
    def parse_iso_duration(self, duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PTM" (пустое)
            
        Returns:
            Время, например "20 minutes" или "1 hour 30 minutes"
        """
        if not duration or duration == 'PTM' or not duration.startswith('PT'):
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
        
        if hours == 0 and minutes == 0:
            return None
        
        # Форматируем результат
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
        if minutes > 0:
            parts.append(f"{minutes} minute" if minutes == 1 else f"{minutes} minutes")
        
        return ' '.join(parts) if parts else None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        json_ld = self.extract_json_ld()
        if not json_ld:
            return None
        
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
        # Ищем секцию с примечаниями
        notes_section = self.soup.find('div', class_='recipe_sg__point')
        if notes_section:
            # Ищем текст примечаний
            note_text = notes_section.find('p', class_='recipe_sg__point_txt')
            if note_text:
                text = self.clean_text(note_text.get_text())
                return text if text else None
        
        # Также проверяем инструкции на наличие примечаний
        instructions_section = self.soup.find('div', class_='recipe_sg__process')
        if instructions_section:
            # Ищем примечания в тексте (обычно начинаются с ※)
            notes = []
            for p in instructions_section.find_all('p'):
                text = p.get_text(strip=True)
                if '※' in text:
                    # Извлекаем текст после ※
                    note = re.sub(r'^.*?※\s*', '', text)
                    note = self.clean_text(note)
                    if note:
                        notes.append(note)
            
            if notes:
                return ' '.join(notes)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Извлекаем из recipeCategory в JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'recipeCategory' in json_ld:
            category = json_ld['recipeCategory']
            if isinstance(category, str):
                category_tags = [tag.strip() for tag in category.split(',') if tag.strip()]
                # Фильтруем "お菓子" но добавляем переведенные версии
                for tag in category_tags:
                    if tag == 'お菓子':
                        tags.append('デザート')
                    elif tag not in ['旬のレシピ']:  # Пропускаем generic теги
                        tags.append(tag)
        
        # Извлекаем ключевые слова из названия блюда
        h1_title = self.soup.find('h1', class_='recipe_sg__tit')
        if h1_title:
            title = self.clean_text(h1_title.get_text())
            # Извлекаем типы блюд из названия
            dish_types = {
                'チーズケーキ': 'チーズケーキ',
                'ケーキ': 'ケーキ',
                'スコーン': 'スコーン',
                'クッキー': 'クッキー',
                'マドレーヌ': 'マドレーヌ',
            }
            
            for pattern, tag_name in dish_types.items():
                if pattern in title:
                    if tag_name not in tags:
                        tags.append(tag_name)
                    break  # Берем только первый найденный
            
            # Извлекаем ингредиенты из названия
            ingredients_patterns = {
                'ブルーベリー': 'ブルーベリー',
                'レモン': 'レモン',
                'かぼちゃ': 'かぼちゃ',
                'りんご': 'りんご',
                'いちご': 'いちご',
                'チョコレート': 'チョコレート',
                'バナナ': 'バナナ',
            }
            
            for pattern, tag_name in ingredients_patterns.items():
                if pattern in title and tag_name not in tags:
                    tags.append(tag_name)
        
        # Удаляем дубликаты, сохраняя порядок
        if tags:
            seen = set()
            unique_tags = []
            for tag in tags:
                if tag and tag not in seen:
                    seen.add(tag)
                    unique_tags.append(tag)
            
            return ', '.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем в JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
            elif isinstance(img, str):
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
        
        # Ищем в meta тегах
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
    import os
    # Обрабатываем папку preprocessed/kojima-ya_com
    recipes_dir = os.path.join("preprocessed", "kojima-ya_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(KojimaYaExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python kojima-ya_com.py")


if __name__ == "__main__":
    main()
