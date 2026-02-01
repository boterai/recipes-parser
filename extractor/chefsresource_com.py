"""
Экстрактор данных рецептов для сайта chefsresource.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ChefsResourceExtractor(BaseRecipeExtractor):
    """Экстрактор для chefsresource.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в h1 заголовке
        h1 = self.soup.find('h1')
        if h1:
            title = h1.get_text(strip=True)
            # Убираем суффикс " Recipe"
            title = re.sub(r'\s+Recipe\s*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s+(Recipe|Chef.*Resource).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала ищем описание в параграфах контента
        # (более точное описание, чем в мета-тегах)
        paragraphs = self.soup.find_all('p')
        for p in paragraphs:
            text = p.get_text(strip=True)
            # Ищем параграф с описанием рецепта (длина 50-300 символов)
            # Исключаем технические тексты
            if (50 < len(text) < 400 and 
                not text.startswith('Save my name') and
                not text.startswith('Your personal data') and
                not 'cookie' in text.lower()[:50]):
                # Проверяем, что это похоже на описание рецепта
                if any(word in text.lower() for word in ['recipe', 'dish', 'dessert', 'flavor', 
                                                          'perfect', 'delicious', 'rich', 'salad',
                                                          'cocktail', 'entree']):
                    return self.clean_text(text)
        
        # Если не нашли в параграфах, ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Очищаем от лишнего текста
            desc = re.sub(r'Discover how to make a delicious\s+', '', desc, flags=re.IGNORECASE)
            desc = re.sub(r'\.\s*This easy-to-follow recipe.*$', '.', desc, flags=re.IGNORECASE)
            desc = re.sub(r'\.\s*Get the full.*$', '.', desc, flags=re.IGNORECASE)
            return self.clean_text(desc)
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "3 fluid ounces hot strong coffee"
            
        Returns:
            dict: {"name": "hot strong coffee", "amount": 3, "units": "fluid ounces"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Обрабатываем дроби в Unicode
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения amount, units и name
        # Сначала пробуем паттерн с "x" (например, "4 x chicken breast")
        pattern_x = r'^(\d+(?:\.\d+)?)\s*x\s+(.+)'
        match_x = re.match(pattern_x, text, re.IGNORECASE)
        
        if match_x:
            amount_str, name = match_x.groups()
            amount = float(amount_str) if '.' in amount_str else int(float(amount_str))
            # Для "x" формата используем "pieces" как единицу измерения
            units = "pieces"
        else:
            # Обычный паттерн с единицами измерения
            # Handles complex patterns like "1 1/2 teaspoons", "3 tablespoons", "12 squares"
            pattern = r'^([\d\s/.,]+)\s+(fluid\s+ounces?|fluid\s+ounce|ounces?|oz|tablespoons?|tbsps?|teaspoons?|tsps?|cups?|pounds?|lbs?|grams?|g|kilograms?|kg|milliliters?|ml|liters?|l|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|squares?|sheets?|rounds?|units?|pieces?|whole|halves?|quarters?|percent|head|heads)(?:\s+|,\s*|$)(.+)?'
            
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
            if amount_str:
                amount_str = amount_str.strip()
                # Обработка дробей типа "1/2" или "1 1/2"
                if '/' in amount_str:
                    parts = amount_str.split()
                    total = 0.0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            total += float(part)
                    # Округляем до 2 знаков после запятой
                    amount = round(total, 2) if total != int(total) else int(total)
                else:
                    amount_val = float(amount_str.replace(',', '.'))
                    amount = amount_val if amount_val != int(amount_val) else int(amount_val)
            else:
                amount = None
            
            # Обработка единицы измерения
            units = units.strip() if units else None
            
            # Обработка имени - если None или пусто, используем текст без первой части
            if not name or not name.strip():
                # Попробуем извлечь из исходного текста, убрав количество и единицу
                name = text
                # Убираем количество и единицу
                name = re.sub(r'^[\d\s/.,]+\s+' + re.escape(units) + r'\s*', '', name, flags=re.IGNORECASE)
        
        # Очистка названия от необязательных частей
        # Удаляем скобки с содержимым (например, "(such as Kahlua)" или "(6 full sheets)")
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|softened)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние запятые и пробелы
        name = re.sub(r'[,;]+\s*$', '', name)
        name = re.sub(r'^\s*[,;]+\s*', '', name)
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
        
        # На сайте chefsresource.com ингредиенты находятся в UL списках без классов
        # Может быть несколько UL для разных секций ингредиентов
        uls = self.soup.find_all('ul', class_=lambda x: not x or x == [])
        
        for ul in uls:
            lis = ul.find_all('li', recursive=False)
            if not lis:
                continue
            
            # Проверяем, является ли это списком ингредиентов
            # (не временем, не меню навигации, не nutrition facts)
            first_text = lis[0].get_text(strip=True)
            
            # Пропускаем списки с временем/сервировками/навигацией/nutrition
            skip_keywords = ['Prep Time:', 'Cook Time:', 'Total Time:', 'Ready In:',
                           'Servings:', 'Yield:', 'Difficulty:', 'Ingredients:',
                           'Homepage', 'Recipes', 'FAQ',
                           'Summary:', 'Calories:', 'Fat:', 'Carbohydrates:', 'Protein:',
                           'Personalised', 'Store and/or access', 'cookie', 'FCCDCF']
            
            if any(keyword in first_text for keyword in skip_keywords):
                continue
            
            # Проверяем, что первый элемент похож на ингредиент
            # (содержит числа и/или единицы измерения или паттерн "X x")
            if (re.search(r'\d+', first_text) and 
                (re.search(r'\d+\s+(fluid\s+)?ounce|cup|tablespoon|teaspoon|pound|gram|ml|oz|lb|slice|piece|clove|square|round|sheet', first_text, re.IGNORECASE) or
                 re.search(r'\d+\s*x\s+', first_text, re.IGNORECASE))):
                
                for li in lis:
                    ingredient_text = li.get_text(strip=True)
                    ingredient_text = self.clean_text(ingredient_text)
                    
                    if ingredient_text:
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
                
                # Продолжаем искать в других UL (не break!)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Инструкции находятся в OL (ordered list)
        ol = self.soup.find('ol')
        if ol:
            lis = ol.find_all('li', recursive=False)
            for li in lis:
                step_text = li.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                if step_text:
                    steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Пытаемся определить категорию из контента
        # 1. Ищем в заголовках h2/h3 (например, "Creamy, Dreamy Wintertime Dessert Cocktail")
        for heading in self.soup.find_all(['h2', 'h3']):
            text = heading.get_text(strip=True)
            # Ищем ключевые слова категорий
            if 'Cocktail' in text and 'Recipe' not in text.split()[-1]:
                return 'Cocktail'
            elif 'Dessert' in text and 'Recipe' not in text.split()[-1]:
                return 'Dessert'
            elif re.search(r'\bMain\s+Course\b', text, re.I):
                return 'Main Course'
            elif re.search(r'\bAppetizer\b', text, re.I):
                return 'Appetizer'
            elif re.search(r'\bBreakfast\b', text, re.I):
                return 'Breakfast'
            elif re.search(r'\bSalad\b', text, re.I):
                return 'Salad'
        
        # 2. Ищем в первом параграфе описания
        for p in self.soup.find_all('p'):
            text = p.get_text(strip=True)
            if 50 < len(text) < 400:
                # Ищем ключевые слова в описании
                if re.search(r'\bdessert\s+cocktail\b', text, re.I):
                    return 'Cocktail'
                elif re.search(r'\bperfect\s+entree\b', text, re.I):
                    return 'Main Course'
                elif re.search(r'\bclassic\s+dessert\b', text, re.I):
                    return 'Dessert'
                elif re.search(r'\bmain\s+course\b', text, re.I):
                    return 'Main Course'
                break
        
        # 3. Ищем в метаданных article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            sections = meta_section['content']
            # Если это "Recipes", то это не категория блюда
            if sections and sections.lower() != 'recipes':
                return self.clean_text(sections)
        
        # 4. Ищем в хлебных крошках
        breadcrumb = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if not breadcrumb:
            breadcrumb = self.soup.find('ol', class_=re.compile(r'breadcrumb', re.I))
        
        if breadcrumb:
            links = breadcrumb.find_all('a')
            # Берем последнюю категорию перед рецептом (обычно это тип блюда)
            if len(links) > 1:
                # Пропускаем Homepage и общие категории
                for link in reversed(links):
                    cat_text = link.get_text(strip=True)
                    if cat_text and cat_text.lower() not in ['homepage', 'home', 'recipes']:
                        return self.clean_text(cat_text)
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # На chefsresource.com время находится в первом UL без класса
        # В формате: "Prep Time: 5 minutes", "Cook Time: 20 minutes", "Total Time: 3 hours 55 minutes"
        # Также может быть "Ready In:" вместо "Total Time:"
        
        time_labels = {
            'prep': ['Prep Time:'],
            'cook': ['Cook Time:'],
            'total': ['Total Time:', 'Ready In:']
        }
        
        labels = time_labels.get(time_type, [])
        if not labels:
            return None
        
        # Ищем в UL без классов
        uls = self.soup.find_all('ul', class_=lambda x: not x or x == [])
        
        for ul in uls:
            lis = ul.find_all('li', recursive=False)
            for li in lis:
                text = li.get_text(strip=True)
                for label in labels:
                    if label in text:
                        # Извлекаем время после метки
                        time_value = text.replace(label, '').strip()
                        return self.clean_text(time_value)
        
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
        # Ищем секцию с заметками/советами
        # На chefsresource.com это может быть в параграфах после инструкций
        
        # Ищем заголовки с "Notes", "Tips", "Chef's Note"
        notes_headers = self.soup.find_all(['h2', 'h3', 'h4', 'strong'], 
                                           string=re.compile(r'Note|Tip|Chef', re.I))
        
        for header in notes_headers:
            # Берем следующий элемент после заголовка
            next_elem = header.find_next_sibling()
            if next_elem and next_elem.name in ['p', 'div', 'ul']:
                text = next_elem.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                if text and len(text) > 10:
                    return text
        
        # Если не нашли по заголовкам, ищем параграфы с ключевыми словами
        for p in self.soup.find_all('p'):
            text = p.get_text(strip=True)
            # Проверяем, что это похоже на совет (начинается с определенных слов)
            if re.match(r'^(To|For|Consider|Make sure|Tip:|Note:)', text, re.I):
                # Проверяем, что это не слишком длинный текст (вероятно, это не заметка)
                if len(text) > 30 and len(text) < 500:
                    return self.clean_text(text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # 1. Ищем article:tag мета-теги
        tag_metas = self.soup.find_all('meta', property='article:tag')
        if tag_metas:
            for tag_meta in tag_metas:
                tag_value = tag_meta.get('content', '').strip()
                if tag_value:
                    tags_list.append(tag_value.lower())
        
        # 2. Если не нашли в мета-тегах, ищем в keywords
        if not tags_list:
            keywords_meta = self.soup.find('meta', {'name': 'keywords'})
            if keywords_meta and keywords_meta.get('content'):
                keywords = keywords_meta['content']
                tags_list = [tag.strip().lower() for tag in keywords.split(',') if tag.strip()]
        
        # 3. Если все еще не нашли, пытаемся извлечь из контента
        if not tags_list:
            # Извлекаем из названия блюда и категории
            dish_name = self.extract_dish_name()
            category = self.extract_category()
            
            if dish_name:
                # Извлекаем ключевые слова из названия
                words = dish_name.lower().split()
                # Добавляем значимые слова (длиннее 4 символов)
                for word in words:
                    if len(word) > 4 and word not in tags_list:
                        tags_list.append(word)
            
            if category:
                tags_list.append(category.lower())
            
            # Ищем в описании
            description = self.extract_description()
            if description:
                # Извлекаем ключевые слова из описания
                desc_lower = description.lower()
                # Ищем типичные теги блюд
                food_keywords = ['salad', 'chicken', 'cocktail', 'dessert', 'pie', 'banana', 
                               'cream', 'winter', 'vietnamese', 'main', 'dish', 'entree']
                for keyword in food_keywords:
                    if keyword in desc_lower and keyword not in tags_list:
                        tags_list.append(keyword)
        
        # Фильтруем общие стоп-слова
        stopwords = {
            'recipe', 'recipes', 'how to make', 'how to', 'easy', 'cooking', 'quick',
            'chefsresource', 'food', 'chef\'s resource', 'kitchen', 'simple', 'best',
            'make', 'ingredients', 'video', 'meal', 'prep', 'ideas', 'tips', 'home',
            'main', 'dish', 'white', 'fresh'
        }
        
        filtered_tags = [tag for tag in tags_list 
                        if tag not in stopwords and len(tag) >= 3]
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in filtered_tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        # Ограничиваем до разумного количества тегов (максимум 6)
        unique_tags = unique_tags[:6]
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Ищем в JSON-LD Article/WebPage
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                # Если есть @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        # Ищем изображения в Article
                        if item.get('@type') == 'Article' and 'image' in item:
                            img = item['image']
                            if isinstance(img, str):
                                urls.append(img)
                            elif isinstance(img, list):
                                urls.extend([i for i in img if isinstance(i, str)])
                        
                        # Ищем в WebPage
                        elif item.get('@type') == 'WebPage' and 'image' in item:
                            img = item['image']
                            if isinstance(img, str):
                                urls.append(img)
                            elif isinstance(img, list):
                                urls.extend([i for i in img if isinstance(i, str)])
                        
                        # Ищем в ImageObject
                        elif item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
            
            except (json.JSONDecodeError, KeyError):
                continue
        
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Точка входа для тестирования парсера"""
    import os
    
    # Обрабатываем папку preprocessed/chefsresource_com
    recipes_dir = os.path.join("preprocessed", "chefsresource_com")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(ChefsResourceExtractor, recipes_dir)
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python chefsresource_com.py")


if __name__ == "__main__":
    main()
