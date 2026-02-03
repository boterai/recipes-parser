"""
Экстрактор данных рецептов для сайта lekkerturkseten.nl
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class LekkerturksetenNlExtractor(BaseRecipeExtractor):
    """Экстрактор для lekkerturkseten.nl"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке H1
        h1 = self.soup.find('h1')
        if h1:
            title = self.clean_text(h1.get_text())
            # Убираем суффиксы типа " - Lekker Turks Eten"
            title = re.sub(r'\s+-\s+Lekker Turks Eten.*$', '', title, flags=re.IGNORECASE)
            # Убираем подзаголовки после запятой (например, ", Knapperige Borek...")
            # Но только если это длинное пояснение
            if ',' in title:
                parts = title.split(',', 1)
                # Если после запятой идет длинный текст (больше 3 слов), убираем его
                if len(parts[1].strip().split()) > 3:
                    title = parts[0]
            return title
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s+-\s+Lekker Turks Eten.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Приоритет 1: Ищем первый параграф в entry-content с описанием рецепта
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            paragraphs = entry_content.find_all('p')
            for p in paragraphs:
                text = p.get_text(strip=True)
                # Пропускаем навигацию и пустые параграфы
                if text and not text.startswith('Home »') and len(text) > 50:
                    # Убираем все виды кавычек в начале (включая Unicode quotes)
                    while text and ord(text[0]) in [34, 39, 8220, 8221, 8216, 8217]:  # ", ', ", ", ', '
                        text = text[1:]
                    # Берем первые 2 предложения
                    sentences = re.split(r'\.\s+', text)
                    if sentences and len(sentences) >= 2:
                        # Формируем описание из первых 2 предложений
                        description = sentences[0] + '. ' + sentences[1] + '.'
                        description = self.clean_text(description)
                        return description
                    elif sentences and len(sentences) == 1:
                        description = sentences[0]
                        if not description.endswith('.'):
                            description += '.'
                        return self.clean_text(description)
        
        # Приоритет 2: Ищем в og:description после заголовка
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            # Убираем навигацию "Home » category » title"
            desc = re.sub(r'^Home\s*»[^»]*»\s*[^"]*\s*', '', desc)
            # Убираем все виды кавычек в начале
            while desc and ord(desc[0]) in [34, 39, 8220, 8221, 8216, 8217]:
                desc = desc[1:]
            # Берем текст до конца или до определенного количества предложений
            sentences = re.split(r'\.\s+', desc)
            if len(sentences) >= 2:
                result = sentences[0] + '. ' + sentences[1] + '.'
            elif len(sentences) == 1:
                result = sentences[0]
                if not result.endswith('.'):
                    result += '.'
            else:
                result = desc
            result = self.clean_text(result)
            return result
        
        # Приоритет 3: meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Dict[str, any]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "500 g baklava filodeeg" или "2 eetlepels olijfolie"
            
        Returns:
            dict: {"name": "baklava filodeeg", "amount": 500, "units": "g"} или None
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
        # Примеры: "500 g baklava filodeeg", "2 eetlepels olijfolie", "3 lente uien"
        pattern = r'^([\d\s/.,]+)?\s*(g\.?|gr\.?|kg|ml\.?|l\.?|eetlepels?|theelepels?|laagjes?|bladeren?|stuks?)?\s*(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip().replace(',', '.')
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
                try:
                    amount = float(amount_str) if '.' in amount_str else int(amount_str)
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем комментарии в скобках и после запятой
        name = re.sub(r'\([^)]*\)', '', name)
        name = re.sub(r',.*$', '', name)
        # Удаляем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем заголовок "Ingrediënten"
        ingredients_heading = self.soup.find('h2', string=lambda x: x and 'ingredi' in x.lower())
        
        if ingredients_heading:
            # Ищем все ul после заголовка до следующего h2/h3
            current = ingredients_heading.find_next_sibling()
            
            while current and current.name not in ['h2']:
                if current.name == 'ul':
                    # Извлекаем элементы списка
                    items = current.find_all('li')
                    
                    for item in items:
                        ingredient_text = item.get_text(separator=' ', strip=True)
                        ingredient_text = self.clean_text(ingredient_text)
                        
                        if ingredient_text:
                            # Парсим в структурированный формат
                            parsed = self.parse_ingredient(ingredient_text)
                            if parsed:
                                ingredients.append(parsed)
                
                # Также проверяем h3 для подсекций (например, "Voor Saus", "Om te smeren")
                elif current.name == 'h3':
                    # Продолжаем искать ul после h3
                    pass
                    
                current = current.find_next_sibling()
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем заголовок "Bereidingsinstructies"
        instructions_heading = self.soup.find('h2', string=lambda x: x and 'bereiding' in x.lower())
        
        if instructions_heading:
            # Ищем ol после заголовка
            ol = instructions_heading.find_next('ol')
            
            if ol:
                # Извлекаем шаги
                step_items = ol.find_all('li')
                
                for item in step_items:
                    # Извлекаем текст инструкции
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    
                    if step_text:
                        steps.append(step_text)
        
        # Объединяем шаги в одну строку через пробел
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем заголовок "Categorie"
        cat_heading = self.soup.find('h4', string=lambda x: x and 'categorie' in x.lower())
        if not cat_heading:
            cat_heading = self.soup.find('h3', string=lambda x: x and 'categorie' in x.lower())
        
        if cat_heading:
            # Ищем следующий параграф
            p = cat_heading.find_next('p')
            if p:
                # Извлекаем текст из ссылок и обычного текста
                links = p.find_all('a')
                if links:
                    categories = [self.clean_text(link.get_text()) for link in links]
                    return ', '.join(categories)
                # Если нет ссылок, берем весь текст
                category_text = p.get_text(strip=True)
                category_text = self.clean_text(category_text)
                # Убираем лишние запятые
                category_text = re.sub(r',\s*,', ',', category_text)
                category_text = re.sub(r',\s*$', '', category_text)
                return category_text
        
        # Альтернативно - из article sections в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list):
                                return ', '.join(sections[:2])  # Берем первые 2 категории
                            return sections
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Маппинг типов на ключевые слова на голландском
        time_keywords = {
            'prep': ['voorbereidingstijd', 'voorbereidings'],
            'cook': ['kooktijd'],
            'total': ['totale bereidingstijd', 'totale tijd']
        }
        
        keywords = time_keywords.get(time_type, [])
        
        for keyword in keywords:
            # Ищем заголовок с ключевым словом
            heading = self.soup.find(['h4', 'h3'], string=lambda x: x and keyword in x.lower())
            
            if heading:
                # Ищем следующий параграф
                p = heading.find_next('p')
                if p:
                    time_text = p.get_text(strip=True)
                    # Очищаем и форматируем
                    time_text = self.clean_text(time_text)
                    # Конвертируем "minuten" в "minutes"
                    time_text = re.sub(r'\bminuten\b', 'minutes', time_text, flags=re.I)
                    # Добавляем "minutes" если отсутствует
                    if time_text and not re.search(r'(minutes|uur|hours)', time_text, re.I):
                        time_text += ' minutes'
                    return time_text
        
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
        # Ищем заголовок "Tips"
        tips_heading = self.soup.find('h2', string=lambda x: x and 'tip' in x.lower())
        
        if tips_heading:
            notes = []
            # Ищем ul после заголовка
            ul = tips_heading.find_next('ul')
            
            if ul:
                # Извлекаем элементы списка
                items = ul.find_all('li')
                
                for item in items:
                    text = item.get_text(separator=' ', strip=True)
                    # Убираем ссылки и лишние пробелы
                    text = re.sub(r'\s+', ' ', text)
                    text = self.clean_text(text)
                    if text:
                        notes.append(text)
            
            if notes:
                # Берем только первую заметку из списка советов, обрезаем до первого предложения с точкой
                first_note = notes[0]
                # Найти первое предложение (до первой точки)
                sentences = re.split(r'\.\s+', first_note)
                if len(sentences) > 0:
                    # Возвращаем первое предложение с точкой
                    result = sentences[0]
                    if not result.endswith('.'):
                        result += '.'
                    return result
                return first_note
        
        # Альтернативный поиск: ищем в FAQ секциях параграфы с ключевыми словами
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            # Ищем параграфы после h3 заголовков FAQ
            h3_headings = entry_content.find_all('h3')
            for heading in h3_headings:
                heading_text = heading.get_text().lower()
                # Проверяем, является ли это вопрос о простоте приготовления
                if 'makkelijk' in heading_text and 'maken' in heading_text:
                    # Берем следующий параграф
                    p = heading.find_next('p')
                    if p:
                        text = p.get_text(strip=True)
                        # Берем первые 3 предложения (до точки)
                        sentences = re.split(r'\.\s+', text)
                        if len(sentences) >= 3:
                            result = sentences[0] + '. ' + sentences[1] + '. ' + sentences[2] + '.'
                            return self.clean_text(result)
                        elif len(sentences) == 2:
                            result = sentences[0] + '. ' + sentences[1] + '.'
                            return self.clean_text(result)
                        elif len(sentences) == 1:
                            result = sentences[0]
                            if not result.endswith('.'):
                                result += '.'
                            return self.clean_text(result)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # 1. Извлекаем ключевые слова из названия блюда (ингредиенты и основные слова)
        dish_name = self.extract_dish_name()
        if dish_name:
            # Убираем стоп-слова и берем ключевые слова
            stopwords = {'met', 'en', 'de', 'het', 'een', 'van', 'voor', 'in', 'op', 'te', 'recept', 
                        'heerlijke', 'knapperige', 'turkse', 'recepten'}
            words = dish_name.lower().split()
            for word in words:
                # Убираем пунктуацию
                word = re.sub(r'[,.]', '', word)
                if word not in stopwords and len(word) > 2:
                    # Добавляем только существенные слова
                    if word not in tags:
                        tags.append(word)
        
        # 2. Добавляем кухню (Keuken) - всегда с заглавной буквы
        keuken_heading = self.soup.find(['h3', 'h4'], string=lambda x: x and 'keuken' in x.lower())
        if keuken_heading:
            p = keuken_heading.find_next('p')
            if p:
                keuken = self.clean_text(p.get_text())
                # Капитализируем первую букву
                if keuken and keuken.lower() not in [t.lower() for t in tags]:
                    tags.append(keuken.capitalize())
        
        # 3. Добавляем релевантные категории
        category = self.extract_category()
        if category:
            cat_parts = [c.strip() for c in category.split(',')]
            for cat in cat_parts:
                # Добавляем категории, которые относятся к типу блюда
                cat_lower = cat.lower()
                if cat_lower in ['vegetarisch', 'snack', 'hoofdgerecht', 'bijgerecht', 'lunch', 'ontbijt', 
                          'dessert', 'voorgerecht']:
                    if cat_lower not in [t.lower() for t in tags]:
                        tags.append(cat_lower)
        
        # 4. Проверяем описание на ключевые слова
        description = self.extract_description()
        if description:
            desc_lower = description.lower()
            # Ищем ключевые слова, которые часто встречаются в тегах
            keywords = ['snack', 'hoofdgerecht', 'bijgerecht', 'streetfood', 'street food']
            for keyword in keywords:
                if keyword in desc_lower and keyword not in [t.lower() for t in tags]:
                    tags.append(keyword)
        
        # Форматируем теги
        formatted_tags = []
        for tag in tags[:5]:  # Ограничиваем до 5 тегов
            # Специальные случаи
            if tag.lower() in ['börek', 'borek']:
                formatted_tags.append('börek' if 'ö' in tag else tag)
            elif tag == 'turks' or tag == 'Turks':
                formatted_tags.append('Turks')  # Всегда с заглавной
            else:
                formatted_tags.append(tag)
        
        # Возвращаем как строку через запятую
        return ', '.join(formatted_tags) if formatted_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Если есть @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
                        # Article с image
                        elif item.get('@type') == 'Article' and 'image' in item:
                            img = item['image']
                            if isinstance(img, dict) and '@id' in img:
                                # Ищем этот ImageObject в графе
                                img_id = img['@id']
                                for obj in data['@graph']:
                                    if obj.get('@id') == img_id and obj.get('@type') == 'ImageObject':
                                        if 'url' in obj:
                                            urls.append(obj['url'])
                                        elif 'contentUrl' in obj:
                                            urls.append(obj['contentUrl'])
            
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
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/lekkerturkseten_nl
    preprocessed_dir = os.path.join("preprocessed", "lekkerturkseten_nl")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(LekkerturksetenNlExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python lekkerturkseten_nl.py")


if __name__ == "__main__":
    main()
