"""
Экстрактор данных рецептов для сайта pontosnews.gr
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class PontosnewsGrExtractor(BaseRecipeExtractor):
    """Экстрактор для pontosnews.gr"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта
        recipe_header = self.soup.find('h1', class_='jeg_post_title')
        if recipe_header:
            return self.clean_text(recipe_header.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Еще один вариант - из title тега
        title = self.soup.find('title')
        if title:
            return self.clean_text(title.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Вариант 1: Ищем div с классом "ingredients" (старый формат)
        ingredients_div = self.soup.find('div', class_='ingredients')
        if ingredients_div:
            # Ищем ul список внутри
            ingredient_list = ingredients_div.find('ul')
            if ingredient_list:
                items = ingredient_list.find_all('li')
                
                for item in items:
                    # Извлекаем текст ингредиента
                    ingredient_text = item.get_text(separator=' ', strip=True)
                    ingredient_text = self.clean_text(ingredient_text)
                    
                    if ingredient_text:
                        # Парсим в структурированный формат
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
        
        # Вариант 2: Ищем параграф с "ΥΛΙΚΑ" и таблицу после него (новый формат)
        if not ingredients:
            # Ищем все параграфы с текстом "ΥΛΙΚΑ"
            for p in self.soup.find_all('p'):
                strong = p.find('strong')
                if strong and 'ΥΛΙΚΑ' in strong.get_text():
                    # Нашли заголовок, ищем таблицу после него
                    table = p.find_next('table')
                    if table:
                        # Извлекаем строки таблицы
                        rows = table.find_all('tr')
                        for row in rows:
                            td = row.find('td')
                            if td:
                                ingredient_text = td.get_text(separator=' ', strip=True)
                                ingredient_text = self.clean_text(ingredient_text)
                                
                                if ingredient_text:
                                    # Парсим в структурированный формат
                                    parsed = self.parse_ingredient(ingredient_text)
                                    if parsed:
                                        ingredients.append(parsed)
                        break  # Нашли и обработали таблицу, выходим
        
        # Вариант 3: Если ингредиенты не найдены, пытаемся извлечь из инструкций
        # (для случаев, когда ингредиенты упоминаются только в тексте инструкций)
        if not ingredients:
            # Получаем текст инструкций
            instructions_text = self.extract_instructions()
            if instructions_text:
                # Список общих греческих ингредиентов для распознавания
                common_ingredients = [
                    'μαργαρίνη', 'κρεμμύδι', 'μανιτάρια', 'τόνο', 'τόνος', 'σκόρδο', 
                    'κρασί', 'λεμόνι', 'γάλα', 'μαϊντανό', 'μαϊντανός', 'λαζάνια', 
                    'νερό', 'αλάτι', 'πιπέρι', 'ζάχαρη', 'αλεύρι', 'βούτυρο', 'ελαιόλαδο',
                    'ντομάτα', 'πατάτα', 'κρέας', 'ψάρι', 'κοτόπουλο', 'αυγό', 'τυρί'
                ]
                
                found_ingredients = []
                instructions_lower = instructions_text.lower()
                
                for ingredient in common_ingredients:
                    # Ищем ингредиент в тексте инструкций
                    if ingredient in instructions_lower:
                        # Добавляем только если еще не добавили
                        if ingredient not in found_ingredients:
                            found_ingredients.append(ingredient)
                            ingredients.append({
                                "name": ingredient,
                                "amount": None,
                                "units": None
                            })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "300 γρ. λαζάνια μακριά" или "1 κρεμμύδι ψιλοκομμένο"
            
        Returns:
            dict: {"name": "λαζάνια μακριά", "amount": 300, "units": "γρ."} или None
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
        # Примеры: "300 γρ. λαζάνια", "2 κονσέρβες τόνο", "1 κρεμμύδι"
        # Греческие единицы: γρ. (грамм), κ.σ. (столовая ложка), κονσέρβες (банки), σκελίδες (зубчики), ποτηράκι (стакан)
        pattern = r'^([\d\s/.,]+)?\s*(γρ\.?|κ\.σ\.?|κονσέρβες?|σκελίδες?|ποτηράκι(α)?|κιλό|λίτρο|ml|l|g|kg)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, units, _, name = match.groups()
        
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
                amount = float(amount_str.replace(',', '.'))
        
        # Обработка единицы измерения
        units = units.strip() if units else None
        
        # Очистка названия
        name = name.strip() if name else ""
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем в различных div контейнерах (зависит от версии сайта)
        content_div = self.soup.find('div', class_='content-inner')
        if not content_div:
            content_div = self.soup.find('div', class_='jeg_inner_content')
        if not content_div:
            # Для старого формата ищем div с классом preparation
            content_div = self.soup.find('div', class_='preparation')
        
        if content_div:
            # Ищем ordered list (ol) для инструкций
            instructions_list = content_div.find('ol')
            if instructions_list:
                step_items = instructions_list.find_all('li')
                
                for item in step_items:
                    # Извлекаем текст инструкции
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    
                    if step_text:
                        steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем по классу category в ссылках
        category_link = self.soup.find('a', class_=re.compile(r'category-'))
        if category_link:
            return self.clean_text(category_link.get_text())
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:  # Берем последнюю категорию перед самим рецептом
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На pontosnews.gr обычно не указывается
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # На pontosnews.gr обычно не указывается
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # На pontosnews.gr обычно не указывается
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями после инструкций
        content_div = self.soup.find('div', class_='content-inner')
        if not content_div:
            content_div = self.soup.find('div', class_='jeg_inner_content')
        if not content_div:
            # Для старого формата ищем div с классом preparation
            content_div = self.soup.find('div', class_='preparation')
        
        if content_div:
            # Ищем параграфы после списка инструкций
            paragraphs = content_div.find_all('p')
            for p in paragraphs:
                text = self.clean_text(p.get_text())
                # Фильтруем пустые параграфы и рекламу
                if text and len(text) > 5:
                    # Пропускаем параграфы с ссылками на сайт
                    if 'Pontos-News.Gr' in text or 'pontos-news.gr' in text:
                        continue
                    # Ищем типичные фразы для заметок
                    if 'Καλή σας όρεξη' in text or 'καλή όρεξη' in text.lower():
                        return text
                    # Также ищем другие типичные фразы для заметок
                    if text and len(text) > 10 and not any(word in text.lower() for word in ['advertisement', 'διαφήμιση']):
                        # Проверяем, что это не список ингредиентов
                        if 'γρ.' not in text and 'κ.σ.' not in text:
                            # Если параграф находится после ol списка, это может быть заметка
                            prev_sibling = p.find_previous_sibling()
                            if prev_sibling and prev_sibling.name == 'ol':
                                return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем поле с тегами рецепта (специфично для pontosnews.gr)
        # Класс может быть field-recipe-tags или field field-name-field-recipe-tags
        tags_field = self.soup.find('div', class_=re.compile(r'field.*recipe.*tags'))
        if tags_field:
            # Ищем все ссылки внутри поля тегов
            tag_links = tags_field.find_all('a')
            for link in tag_links:
                tag_text = self.clean_text(link.get_text())
                if tag_text:
                    tags.append(tag_text)
        
        # Если не нашли теги в специальном поле, проверяем JSON-LD
        if not tags:
            json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    
                    # Ищем теги в разных форматах
                    if isinstance(data, dict):
                        # Проверяем @graph
                        if '@graph' in data:
                            for item in data['@graph']:
                                if 'keywords' in item:
                                    keywords = item['keywords']
                                    if isinstance(keywords, str):
                                        return keywords
                                    elif isinstance(keywords, list):
                                        return ', '.join(keywords)
                        
                        # Проверяем напрямую
                        if 'keywords' in data:
                            keywords = data['keywords']
                            if isinstance(keywords, str):
                                return keywords
                            elif isinstance(keywords, list):
                                return ', '.join(keywords)
                                
                except (json.JSONDecodeError, KeyError):
                    continue
        
        # Если не нашли, ищем meta keywords
        if not tags:
            meta_keywords = self.soup.find('meta', {'name': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                return self.clean_text(meta_keywords['content'])
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 2. Ищем featured image в контенте
        featured_img = self.soup.find('div', class_='jeg_featured')
        if featured_img:
            img = featured_img.find('img')
            if img and img.get('src'):
                urls.append(img['src'])
        
        # 3. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем изображения в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
                        # Также проверяем image в других элементах
                        if 'image' in item:
                            img = item['image']
                            if isinstance(img, str):
                                urls.append(img)
                            elif isinstance(img, dict):
                                if 'url' in img:
                                    urls.append(img['url'])
                                elif 'contentUrl' in img:
                                    urls.append(img['contentUrl'])
                            elif isinstance(img, list):
                                for i in img:
                                    if isinstance(i, str):
                                        urls.append(i)
                                    elif isinstance(i, dict):
                                        if 'url' in i:
                                            urls.append(i['url'])
                                        elif 'contentUrl' in i:
                                            urls.append(i['contentUrl'])
                                            
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Убираем дубликаты, сохраняя порядок, и фильтруем аватары
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                # Фильтруем аватары gravatar и другие служебные изображения
                if url and url not in seen and 'gravatar.com' not in url:
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
    """Обработка директории с HTML файлами pontosnews.gr"""
    import os
    
    # Обрабатываем папку preprocessed/pontosnews_gr
    recipes_dir = os.path.join("preprocessed", "pontosnews_gr")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(PontosnewsGrExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python pontosnews_gr.py")


if __name__ == "__main__":
    main()
