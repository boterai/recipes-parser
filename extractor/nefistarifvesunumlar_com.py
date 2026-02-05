"""
Экстрактор данных рецептов для сайта nefistarifvesunumlar.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class NefistarifvesunumlarExtractor(BaseRecipeExtractor):
    """Экстрактор для nefistarifvesunumlar.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта h1 с классом article-title или entry-title
        recipe_header = self.soup.find('h1', class_=re.compile(r'(article-title|entry-title)', re.I))
        if recipe_header:
            title = self.clean_text(recipe_header.get_text())
            # Удаляем "Tarifi" (рецепт) из названия если есть
            title = re.sub(r'\s+Tarifi\s*$', '', title, flags=re.IGNORECASE)
            return title
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " Tarifi", " - Nefis Tarif ve Sunumlar"
            title = re.sub(r'\s+(Tarifi|Nefis.*Sunumlar).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в мета-тегах
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        # Также можем проверить JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BlogPosting' and 'description' in item:
                            return self.clean_text(item['description'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем заголовок "Malzemeler" (Ингредиенты)
        malzemeler_header = None
        for heading in self.soup.find_all(['h2', 'h3', 'h4'], class_=re.compile(r'wp-block-heading', re.I)):
            heading_text = self.clean_text(heading.get_text())
            if re.search(r'Malzemeler', heading_text, re.IGNORECASE):
                malzemeler_header = heading
                break
        
        if malzemeler_header:
            # Ищем следующие элементы после заголовка
            current = malzemeler_header.find_next_sibling()
            while current:
                # Если нашли список - извлекаем все ингредиенты
                if current.name == 'ul' and 'wp-block-list' in current.get('class', []):
                    items = current.find_all('li')
                    for item in items:
                        ingredient_text = self.clean_text(item.get_text())
                        if ingredient_text:
                            parsed = self.parse_ingredient(ingredient_text)
                            if parsed:
                                ingredients.append(parsed)
                # Если нашли параграф с подзаголовком (например "İç Harcı İçin"), пропускаем
                elif current.name == 'p':
                    pass  # Просто пропускаем, продолжаем искать списки
                # Если нашли новый основной заголовок - прекращаем поиск
                elif current.name in ['h2', 'h3', 'h4']:
                    break
                    
                current = current.find_next_sibling()
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 su bardağı un" или "2 yumurta"
            
        Returns:
            dict: {"name": "un", "amount": "1", "unit": "su bardağı"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
        # Заменяем турецкие слова для дробей и количеств
        text = text.replace('yarım', '0.5')  # половина
        text = text.replace('bir buçuk', '1.5')  # полтора
        
        # Заменяем дроби
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Турецкие единицы измерения
        # su bardağı = стакан воды, çay bardağı = чайная чашка
        # tatlı kaşığı = десертная ложка, yemek kaşığı = столовая ложка, çay kaşığı = чайная ложка
        # paket = пакет, adet = штук
        pattern = r'^([\d\s/.,]+)?\s*(su\s+bardağı|çay\s+bardağı|bardak|tatlı\s+kaşığı|yemek\s+kaşığı|çay\s+kaşığı|kaşık|paket|adet|gram|gr|kg|kilogram|litre|ml|dilim|diş|demet|tutam|pieces?|cups?|tbsp|tsp|g|l)?\s*(.+)'
        
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
                amount_str = amount_str.replace(',', '.')
                amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        name = re.sub(r'\([^)]*\)', '', name)  # Удаляем скобки
        name = re.sub(r'\b(tercihe göre|isteğe bağlı|arzuya göre)\b', '', name, flags=re.IGNORECASE)
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
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
        
        # Ищем заголовок "Nasıl Yapılır" (Как приготовить)
        nasil_yapilar_header = None
        for heading in self.soup.find_all(['h2', 'h3', 'h4'], class_=re.compile(r'wp-block-heading', re.I)):
            heading_text = self.clean_text(heading.get_text())
            if re.search(r'Nasıl\s+Yapılır', heading_text, re.IGNORECASE):
                nasil_yapilar_header = heading
                break
        
        if nasil_yapilar_header:
            # Ищем следующие элементы после заголовка
            current = nasil_yapilar_header.find_next_sibling()
            while current:
                # Если нашли список ol или ul
                if current.name in ['ol', 'ul']:
                    items = current.find_all('li')
                    for item in items:
                        step_text = self.clean_text(item.get_text())
                        if step_text:
                            steps.append(step_text)
                    # Продолжаем искать дальше, могут быть еще параграфы
                # Если нашли параграф с текстом
                elif current.name == 'p':
                    step_text = self.clean_text(current.get_text())
                    # Добавляем параграф если он не пустой
                    if step_text and len(step_text) > 5:
                        # Пропускаем типичные заключительные фразы и ссылки на другие рецепты
                        skip_phrases = ['afiyet', 'deneyenlere', 'tavsiye ederim', 'incelemek için', 
                                      'tıklayınız', 'teşekkür ederiz', 'kanalına', 'tarifi için']
                        if not any(phrase in step_text.lower() for phrase in skip_phrases):
                            steps.append(step_text)
                # Если нашли новый заголовок - прекращаем поиск
                elif current.name in ['h2', 'h3', 'h4']:
                    break
                
                current = current.find_next_sibling()
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BlogPosting' and 'articleSection' in item:
                            return self.clean_text(item['articleSection'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из meta тега
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Из хлебных крошек в JSON-LD
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BreadcrumbList' and 'itemListElement' in item:
                            items = item['itemListElement']
                            # Берем предпоследний элемент (последний - сам рецепт)
                            if len(items) >= 2:
                                category_item = items[-2]
                                if 'item' in category_item and 'name' in category_item['item']:
                                    return self.clean_text(category_item['item']['name'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На сайте nefistarifvesunumlar.com обычно не указывается
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # На сайте nefistarifvesunumlar.com обычно не указывается
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # На сайте nefistarifvesunumlar.com обычно не указывается
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем типичные заключительные фразы типа "Deneyenlere şimdiden afiyet olsun"
        # (Желаем приятного аппетита тем, кто попробует)
        
        # Ищем после секции с инструкциями
        nasil_yapilar_header = None
        for heading in self.soup.find_all(['h2', 'h3', 'h4'], class_=re.compile(r'wp-block-heading', re.I)):
            heading_text = self.clean_text(heading.get_text())
            if re.search(r'Nasıl\s+Yapılır', heading_text, re.IGNORECASE):
                nasil_yapilar_header = heading
                break
        
        if nasil_yapilar_header:
            # Ищем параграфы после секции инструкций
            current = nasil_yapilar_header
            found_instructions = False
            
            while current:
                current = current.find_next_sibling()
                if not current:
                    break
                
                # Пропускаем до конца инструкций
                if current.name in ['ol', 'ul', 'p'] and not found_instructions:
                    if current.name == 'p' and len(self.clean_text(current.get_text())) > 50:
                        found_instructions = True
                    continue
                
                # Ищем заметки
                if found_instructions and current.name == 'p':
                    text = self.clean_text(current.get_text())
                    # Типичные фразы для заметок
                    if text and any(phrase in text.lower() for phrase in ['afiyet', 'deneyenlere', 'tavsiye', 'not', 'ipucu']):
                        return text
                
                # Если нашли новый заголовок - прекращаем
                if current.name in ['h2', 'h3', 'h4']:
                    break
        
        # Альтернативный поиск - ищем в конце страницы
        all_paragraphs = self.soup.find_all('p')
        for p in reversed(all_paragraphs[-5:]):  # Проверяем последние 5 параграфов
            text = self.clean_text(p.get_text())
            if text and any(phrase in text.lower() for phrase in ['afiyet', 'deneyenlere']):
                return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # 1. Из meta тега article:tag
        article_tag = self.soup.find('meta', property='article:tag')
        if article_tag and article_tag.get('content'):
            tag = self.clean_text(article_tag['content'])
            # Удаляем " Tarifi" из тега
            tag = re.sub(r'\s+Tarifi\s*$', '', tag, flags=re.IGNORECASE)
            tags_list.append(tag)
        
        # 2. Из JSON-LD keywords
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BlogPosting' and 'keywords' in item:
                            keywords = item['keywords']
                            keyword = self.clean_text(keywords)
                            # Удаляем " Tarifi" из ключевых слов
                            keyword = re.sub(r'\s+Tarifi\s*$', '', keyword, flags=re.IGNORECASE)
                            if keyword and keyword not in tags_list:
                                tags_list.append(keyword)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 3. Добавляем категорию как тег, если есть
        category = self.extract_category()
        if category and category not in tags_list:
            tags_list.append(category)
        
        # Возвращаем как строку через запятую
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Из meta тега og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject' and 'url' in item:
                            urls.append(item['url'])
                        # BlogPosting с image
                        elif item.get('@type') == 'BlogPosting' and 'image' in item:
                            img = item['image']
                            if isinstance(img, dict) and '@id' in img:
                                # Это ссылка на ImageObject, ищем его
                                continue
                            elif isinstance(img, str):
                                urls.append(img)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 3. Из twitter:image
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
    """Точка входа для обработки HTML файлов"""
    import os
    
    # Обрабатываем папку preprocessed/nefistarifvesunumlar_com
    preprocessed_dir = os.path.join("preprocessed", "nefistarifvesunumlar_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(NefistarifvesunumlarExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python nefistarifvesunumlar_com.py")


if __name__ == "__main__":
    main()
