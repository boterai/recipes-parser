"""
Экстрактор данных рецептов для сайта bosanskikuhar.ba
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class BosanskikuharExtractor(BaseRecipeExtractor):
    """Экстрактор для bosanskikuhar.ba"""
    
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
        # Сначала пробуем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Из meta title
        title = self.soup.find('title')
        if title:
            text = title.get_text()
            # Убираем суффиксы
            text = re.sub(r'\s*\|.*$', '', text)
            text = re.sub(r'\s+-\s+.*$', '', text)
            text = re.sub(r'\s+[Rr]ecept.*$', '', text)
            return self.clean_text(text)
        
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
        
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        # Ищем первый параграф после заголовка
        h1 = self.soup.find('h1')
        if h1:
            # Ищем следующий параграф после h1
            next_p = h1.find_next('p')
            if next_p:
                return self.clean_text(next_p.get_text())
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "500g brašna" или "2 kašike ulja"
            
        Returns:
            dict: {"name": "brašno", "amount": "500", "unit": "g"}
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
        # Поддержка боснийских единиц: kašika, čaša, gram, kilogram, litar, mililitar, etc.
        # glavica, komad - это счетные единицы, которые идут вместе с названием ингредиента
        # Сначала пробуем паттерн с единицами (с пробелом и без)
        pattern = r'^([\d\s/.,]+)?\s*(kašik[ae]|kašičic[ae]|čaš[ae]|šoljic[ae]|gram[a]?|kilogram[a]?|kg|g|litar[a]?|mililitar[a]?|ml|l|prstohvat[a]?|pakovanje|pakovanja|konzerv[ae]|konzervi)\s+(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        # Если не совпало, пробуем паттерн где единица слита с числом (например "500g")
        if not match:
            pattern2 = r'^([\d\s/.,]+)(kašik[ae]|kašičic[ae]|čaš[ae]|šoljic[ae]|gram[a]?|kilogram[a]?|kg|g|litar[a]?|mililitar[a]?|ml|l|prstohvat[a]?|pakovanje|pakovanja|konzerv[ae]|konzervi)\s+(.+)'
            match = re.match(pattern2, text, re.IGNORECASE)
        
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
                amount = str(int(total)) if total % 1 == 0 else str(total)
            else:
                try:
                    val = float(amount_str.replace(',', '.'))
                    amount = str(int(val)) if val % 1 == 0 else str(val)
                except (ValueError, TypeError):
                    amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "po ukusu", "po želji", "opciono"
        name = re.sub(r'\b(po ukusu|po želji|opciono|opcionalno|ako želite|po potrebi)\b', '', name, flags=re.IGNORECASE)
        # Удаляем специфичные суффиксы
        name = re.sub(r',\s*(isjeckan[oi]?|ribana?|narezana?|sitno|krupno).*$', '', name, flags=re.IGNORECASE)
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
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'recipeIngredient' in json_ld:
            for ingredient_text in json_ld['recipeIngredient']:
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
            
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)
        
        # Если JSON-LD не помог, ищем в HTML
        # Вариант 1: Список ингредиентов в ul/ol с классом
        ingredient_list = self.soup.find('ul', class_=re.compile(r'(ingredient|sastojci)', re.I))
        if not ingredient_list:
            ingredient_list = self.soup.find('ol', class_=re.compile(r'(ingredient|sastojci)', re.I))
        if not ingredient_list:
            # Ищем div/section с классом, содержащим ingredient/sastojci
            container = self.soup.find(['div', 'section'], class_=re.compile(r'(ingredient|sastojci)', re.I))
            if container:
                # Ищем список внутри контейнера
                ingredient_list = container.find('ul')
                if not ingredient_list:
                    ingredient_list = container.find('ol')
        
        if ingredient_list:
            # Извлекаем элементы списка
            items = ingredient_list.find_all('li')
            if not items:
                items = ingredient_list.find_all('p')
            
            for item in items:
                ingredient_text = item.get_text(separator=' ', strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                # Пропускаем заголовки секций
                if ingredient_text and not ingredient_text.endswith(':') and len(ingredient_text) > 3:
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления (instructions)"""
        steps = []
        
        # Сначала пробуем JSON-LD
        json_ld = self._get_json_ld_data()
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
            
            if steps:
                return ' '.join(steps)
        
        # Если JSON-LD не помог, ищем в HTML
        # Вариант 1: Список с классом
        instruction_list = self.soup.find('ol', class_=re.compile(r'(instruction|priprema|koraci|upute)', re.I))
        if not instruction_list:
            instruction_list = self.soup.find('ul', class_=re.compile(r'(instruction|priprema|koraci|upute)', re.I))
        if not instruction_list:
            # Вариант 2: Ищем section/div с инструкциями, затем список внутри
            container = self.soup.find(['div', 'section'], class_=re.compile(r'(instruction|priprema|koraci|upute)', re.I))
            if container:
                instruction_list = container.find('ol')
                if not instruction_list:
                    instruction_list = container.find('ul')
        
        if instruction_list:
            # Извлекаем шаги
            step_items = instruction_list.find_all('li')
            if not step_items:
                step_items = instruction_list.find_all('p')
            
            for idx, item in enumerate(step_items, 1):
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text and len(step_text) > 3:
                    # Добавляем нумерацию, если её нет
                    if not re.match(r'^\d+\.', step_text):
                        step_text = f"{idx}. {step_text}"
                    steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld:
            # Пробуем recipeCategory
            if 'recipeCategory' in json_ld:
                category = json_ld['recipeCategory']
                if isinstance(category, list):
                    return ', '.join(category)
                return str(category)
            
            # Пробуем recipeCuisine
            if 'recipeCuisine' in json_ld:
                cuisine = json_ld['recipeCuisine']
                if isinstance(cuisine, list):
                    return ', '.join(cuisine)
                return str(cuisine)
        
        # Из meta тегов
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Из breadcrumbs
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if not breadcrumbs:
            breadcrumbs = self.soup.find('div', class_=re.compile(r'breadcrumb', re.I))
        
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:  # Берем последнюю категорию перед самим рецептом
                for link in reversed(links):
                    text = self.clean_text(link.get_text())
                    if text and text.lower() not in ['početna', 'home', 'naslovna']:
                        return text
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        # Ищем в HTML
        prep_time_elem = self.soup.find(class_=re.compile(r'prep.*time', re.I))
        if prep_time_elem:
            time_text = prep_time_elem.get_text(strip=True)
            return self.clean_text(time_text)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        # Ищем в HTML
        cook_time_elem = self.soup.find(class_=re.compile(r'cook.*time', re.I))
        if cook_time_elem:
            time_text = cook_time_elem.get_text(strip=True)
            return self.clean_text(time_text)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        # Ищем в HTML
        total_time_elem = self.soup.find(class_=re.compile(r'total.*time', re.I))
        if total_time_elem:
            time_text = total_time_elem.get_text(strip=True)
            return self.clean_text(time_text)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями/советами
        notes_section = self.soup.find(class_=re.compile(r'(note|napomena|savjet|tip)', re.I))
        
        if notes_section:
            # Сначала пробуем найти параграф внутри
            p = notes_section.find('p')
            if p:
                text = self.clean_text(p.get_text())
                return text if text else None
            
            # Если нет параграфа, берем весь текст
            text = notes_section.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        # Ищем параграфы, которые содержат ключевые слова
        note_keywords = ['savjet', 'napomena', 'možete', 'preporuka', 'tip']
        all_paragraphs = self.soup.find_all('p')
        for p in all_paragraphs:
            text = p.get_text(strip=True).lower()
            for keyword in note_keywords:
                if keyword in text:
                    cleaned_text = self.clean_text(p.get_text())
                    if len(cleaned_text) > 20:  # Пропускаем слишком короткие
                        return cleaned_text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Список стоп-слов для фильтрации
        stopwords = {
            'recept', 'recepti', 'bosanski', 'kuhar', 'bosanskikuhar',
            'lako', 'brzo', 'jednostavno', 'najbolji'
        }
        
        tags_list = []
        
        # 1. Из мета-тега keywords
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        # 2. Из мета-тега parsely-tags (если есть)
        if not tags_list:
            parsely_meta = self.soup.find('meta', attrs={'name': 'parsely-tags'})
            if parsely_meta and parsely_meta.get('content'):
                tags_string = parsely_meta['content']
                tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        # 3. Из тегов на странице (обычно в div с классом tags или tagovi)
        if not tags_list:
            tags_section = self.soup.find('div', class_=re.compile(r'(tag|oznaka)', re.I))
            if tags_section:
                tag_links = tags_section.find_all('a')
                tags_list = [self.clean_text(link.get_text()) for link in tag_links]
        
        if not tags_list:
            return None
        
        # Фильтрация тегов
        filtered_tags = []
        for tag in tags_list:
            tag_lower = tag.lower()
            
            # Пропускаем стоп-слова
            if tag_lower in stopwords:
                continue
            
            # Пропускаем слишком короткие теги
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
        
        # Возвращаем как строку через запятую с пробелом
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Сначала пробуем JSON-LD
        json_ld = self._get_json_ld_data()
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
        
        # 2. Из мета-тегов
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Из основного изображения рецепта
        # Ищем изображение в контейнере рецепта
        recipe_img = self.soup.find('img', class_=re.compile(r'(recipe|recept)', re.I))
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
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "bosanskikuhar_ba")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(BosanskikuharExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python bosanskikuhar_ba.py")


if __name__ == "__main__":
    main()
