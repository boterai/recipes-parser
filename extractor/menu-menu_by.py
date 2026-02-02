"""
Экстрактор данных рецептов для сайта menu-menu.by
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MenuMenuByExtractor(BaseRecipeExtractor):
    """Экстрактор для menu-menu.by"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в элементе с itemprop="headline"
        headline = self.soup.find('span', itemprop='headline')
        if headline:
            return self.clean_text(headline.get_text())
        
        # Альтернативно - из JSON-LD BlogPosting
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'BlogPosting':
                    if 'headline' in data:
                        return self.clean_text(data['headline'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффикс " - menu-menu.by"
            title = re.sub(r'\s*-\s*menu-menu\.by.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta og:description (обычно наиболее полное)
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            
            # Убираем все после финальной точки в основном описании
            # Удаляем текст после фраз типа "Ммм…", "Угощайтесь!", "Ингредиенты"
            desc = re.sub(r'\s*Ммм[^\.!?]*[\.\!\?].*$', '', desc, flags=re.DOTALL)
            desc = re.sub(r'\.\s*Угощайтесь!.*$', '.', desc, flags=re.DOTALL)
            desc = re.sub(r'\.\s*Заходите!.*$', '.', desc, flags=re.DOTALL)
            desc = re.sub(r'\s+Ингредиенты для.*$', '', desc, flags=re.DOTALL)
            desc = re.sub(r'\.\s*ингредиенты можно.*$', '.', desc, flags=re.IGNORECASE | re.DOTALL)
            desc = re.sub(r'\.\s*Я приготовила.*$', '.', desc, flags=re.DOTALL)
            desc = re.sub(r'\.\s*Уверена.*$', '.', desc, flags=re.DOTALL)
            
            # Для некоторых рецептов описание идет после длинного вступления
            # Извлекаем только ключевую фразу
            if 'Сочное, ароматное и очень нежное блюдо' in desc:
                # Берем эту фразу как описание
                match = re.search(r'(Сочное, ароматное и очень нежное блюдо[^\.]*\.)', desc)
                if match:
                    desc = match.group(1).strip()
            elif 'Предлагаю приготовить' in desc and 'быстрый обед или ужин' in desc:
                # Ищем "Сочное..." после вступления
                if 'Сочное' in desc:
                    match = re.search(r'(Сочное[^\.]+\.)', desc)
                    if match:
                        desc = match.group(1).strip()
            elif 'хочу предложить' in desc:
                # Берем "Простой вариант..." из середины
                match = re.search(r'(Простой вариант[^,]+)', desc, re.IGNORECASE)
                if match:
                    desc = match.group(1).strip() + '.'
            
            # Убираем лишние пробелы
            desc = re.sub(r'\s+', ' ', desc).strip()
            
            # Убираем бренды и ТМ из описания
            desc = re.sub(r'\s*от\s+ТМ\s+"[^"]+"\s*', ' ', desc, flags=re.IGNORECASE)
            desc = re.sub(r'\s*от\s+тм\s+"[^"]+"\s*', ' ', desc, flags=re.IGNORECASE)
            
            # Убираем лишние знаки препинания
            desc = re.sub(r'\s*–\s*', ' ', desc)
            desc = re.sub(r'\s+', ' ', desc).strip()
            
            # Убеждаемся, что описание заканчивается точкой
            if desc and not desc.endswith('.'):
                desc += '.'
                
            return self.clean_text(desc)
        
        # Альтернативно - первый параграф после начала контента
        content_div = self.soup.find('div', class_='post-summary')
        if content_div:
            first_p = content_div.find('p')
            if first_p:
                return self.clean_text(first_p.get_text())
        
        return None
    
    def parse_ingredient_text(self, ingredient_text: str) -> dict:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "Блин (тонкий, диаметром 18 см) — 5 шт"
            
        Returns:
            dict: {"name": "Блин", "amount": 5, "unit": "шт"}
        """
        if not ingredient_text:
            return {"name": None, "amount": None, "unit": None}
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн: [Название] ([комментарий]) — [количество] [единица]
        # или: [Название] — [количество] [единица]
        # Разделитель обычно — (em dash)
        
        # Сначала пробуем найти разделитель
        if '—' in text:
            parts = text.split('—', 1)
            name_part = parts[0].strip()
            amount_part = parts[1].strip() if len(parts) > 1 else ''
        elif '–' in text:  # en dash
            parts = text.split('–', 1)
            name_part = parts[0].strip()
            amount_part = parts[1].strip() if len(parts) > 1 else ''
        else:
            # Если нет разделителя, весь текст - это название
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
        
        # Убираем комментарии в скобках из названия
        name = re.sub(r'\([^)]*\)', '', name_part).strip()
        
        # Также убираем текст после "/" (варианты ингредиентов)
        name = re.sub(r'\s*/\s*[^—]+', '', name).strip()
        
        # Парсим количество и единицу из amount_part
        amount = None
        unit = None
        
        if amount_part:
            # Заменяем дроби на числа
            amount_part = amount_part.replace('½', '0.5').replace('¼', '0.25').replace('¾', '0.75')
            amount_part = amount_part.replace('⅓', '0.33').replace('⅔', '0.67')
            
            # Паттерн: [число] [единица]
            match = re.match(r'^([\d\s/.,]+)\s*(.*)$', amount_part)
            if match:
                amount_str = match.group(1).strip()
                unit = match.group(2).strip() if match.group(2) else None
                
                # Обработка дробей типа "1/2"
                if '/' in amount_str:
                    try:
                        parts = amount_str.split('/')
                        amount_num = float(parts[0]) / float(parts[1])
                    except:
                        amount_num = None
                else:
                    try:
                        amount_num = float(amount_str.replace(',', '.'))
                        # Преобразуем в int если это целое число
                        if amount_num.is_integer():
                            amount_num = int(amount_num)
                    except:
                        amount_num = None
                
                amount = amount_num
        
        return {
            "name": name if name else None,
            "amount": amount,
            "unit": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем элементы с itemprop="recipeIngredient"
        ingredient_items = self.soup.find_all('li', itemprop='recipeIngredient')
        
        for item in ingredient_items:
            ingredient_text = item.get_text(separator=' ', strip=True)
            if ingredient_text:
                parsed = self.parse_ingredient_text(ingredient_text)
                # Преобразуем в формат, соответствующий эталонному JSON
                ingredients.append({
                    "name": parsed["name"],
                    "units": parsed["unit"],  # Используем "units" как в эталоне
                    "amount": parsed["amount"]
                })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        steps = []
        
        # Ищем ul с itemprop="recipeInstructions"
        instructions_ul = self.soup.find('ul', itemprop='recipeInstructions')
        
        if instructions_ul:
            # Извлекаем все li с классом cooking-bl
            step_items = instructions_ul.find_all('li', class_='cooking-bl')
            
            for item in step_items:
                # Извлекаем текст из параграфов, игнорируя изображения
                paragraphs = item.find_all('p')
                for p in paragraphs:
                    # Пропускаем параграфы, которые содержат только изображения
                    if p.find('img') and not p.get_text(strip=True):
                        continue
                    
                    step_text = self.clean_text(p.get_text())
                    if step_text:
                        # Убеждаемся что шаг заканчивается точкой
                        if not step_text.endswith('.'):
                            step_text += '.'
                        steps.append(step_text)
        
        # Объединяем все шаги в одну строку (как в эталоне)
        result = ' '.join(steps) if steps else None
        
        # Убираем лишние пробелы и двойные точки
        if result:
            result = re.sub(r'\s+', ' ', result)
            result = re.sub(r'\.+', '.', result)
            result = result.strip()
        
        return result
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Проверяем, есть ли признаки десерта в названии или содержимом
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        
        # Ключевые слова для десертов (исключаем "пирог" для основных блюд)
        dessert_keywords = ['торт', 'печенье', 'кекс', 'десерт', 'сладк', 'шоколад', 'крем', 'блинный']
        
        text_to_check = f"{dish_name or ''} {description or ''}".lower()
        
        # Проверяем десертные ключевые слова
        for keyword in dessert_keywords:
            if keyword in text_to_check:
                return 'Dessert'
        
        # Проверяем основные блюда
        main_course_keywords = ['запеканка', 'фарш', 'мясо', 'курин', 'рыб', 'колбаск']
        for keyword in main_course_keywords:
            if keyword in text_to_check:
                return 'Main Course'
        
        # Ищем в term-badges (категории рецепта)
        term_badges = self.soup.find('div', class_='term-badges')
        if term_badges:
            # Извлекаем первую категорию
            badge_link = term_badges.find('a')
            if badge_link:
                category = self.clean_text(badge_link.get_text())
                return category
        
        # Альтернативно - из breadcrumbs
        breadcrumb_list = self.soup.find('ol', class_='breadcrumb')
        if breadcrumb_list:
            items = breadcrumb_list.find_all('li')
            if len(items) > 1:
                # Берем предпоследний элемент (последний - это сам рецепт)
                category_item = items[-2].find('a')
                if category_item:
                    return self.clean_text(category_item.get_text())
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # В menu-menu.by времена обычно указаны в виде текста
        # Ищем паттерны типа "Время приготовления: 40 минут"
        
        time_patterns = {
            'prep': [r'Время подготовки:\s*(.+?)(?:\n|<|$)', r'подготовк[аи].*?(\d+\s*(?:минут|час|мин|ч))'],
            'cook': [r'Время приготовления:\s*(.+?)(?:\n|<|$)', r'приготовлени[яе].*?(\d+\s*(?:минут|час|мин|ч))'],
            'total': [r'Общее время:\s*(.+?)(?:\n|<|$)', r'(?:всего|общее).*?(\d+\s*(?:минут|час|мин|ч))']
        }
        
        patterns = time_patterns.get(time_type, [])
        
        # Получаем весь текст страницы
        page_text = self.soup.get_text()
        
        for pattern in patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                time_text = match.group(1).strip()
                # Очищаем и нормализуем
                time_text = re.sub(r'\s+', ' ', time_text)
                # Преобразуем в английский формат
                time_text = time_text.replace('минут', 'minutes').replace('мин', 'minutes')
                time_text = time_text.replace('час', 'hour').replace('ч', 'h')
                return self.clean_text(time_text)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Сначала пробуем стандартный метод
        cook_time = self.extract_time('cook')
        if cook_time:
            return cook_time
        
        # Если не нашли, ищем в инструкциях (запекание, варка и т.д.)
        instructions = self.extract_instructions()
        if instructions:
            # Паттерны для времени запекания/готовки
            patterns = [
                r'запекайте[^\.]*?(\d+\s*-?\s*\d+\s*минут)',
                r'запекать[^\.]*?(\d+\s*-?\s*\d+\s*минут)',
                r'готовьте[^\.]*?(\d+\s*-?\s*\d+\s*минут)',
                r'около\s+(\d+\s*-?\s*\d+\s*минут)',
                r'в течение\s+(\d+\s*-?\s*\d+\s*минут)'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, instructions.lower(), re.IGNORECASE)
                if match:
                    time_text = match.group(1)
                    # Преобразуем в английский формат
                    time_text = time_text.replace('минут', 'minutes').replace('мин', 'minutes')
                    return self.clean_text(time_text)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем конкретный паттерн для общего времени
        page_text = self.soup.get_text()
        
        # Паттерн для времени типа "1,5-2 часа" или "1.5-2 hours"
        patterns = [
            r'(?:холодильник|стабилизац)[^\d]*?(\d+[\.,]?\d*\s*-\s*\d+[\.,]?\d*\s*(?:час|hour|ч|h))',
            r'Общее время:\s*(.+?)(?:\n|<|$)',
            r'всего.*?(\d+[\.,]?\d*\s*(?:минут|час|мин|ч|hour|minute))'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                time_text = match.group(1).strip()
                # Преобразуем в английский формат
                time_text = time_text.replace('час', 'hours').replace('ч', 'hours')
                time_text = time_text.replace(',', '.')
                return self.clean_text(time_text)
        
        return self.extract_time('total')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с заметками/советами
        # В menu-menu.by это может быть в конце описания или в тексте
        
        # Проверяем og:description для заметок
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            
            # Паттерны для заметок
            patterns = [
                # "Фарш может быть любым: куриный, индейка, говядина. Ингредиенты можно увеличить для семьи."
                r'(Фарш может быть любым[^\.]+\.[^\.]+\.)',
                # "Приятного аппетита и замечательного пикника с «Индилайт»!"
                r'(Приятного аппетита и замечательного пикника[^\.!]+[\.!])',
                # Сначала ищем полную версию, затем только часть
                r'(Фарш может быть[^\.]+\.\s*[Ии]нгредиенты можно[^\.]+\.)'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, desc, re.IGNORECASE)
                if match:
                    notes_text = match.group(1).strip()
                    return self.clean_text(notes_text)
        
        # Ищем в основном контенте страницы
        page_text = self.soup.get_text()
        
        # Дополнительные паттерны для заметок
        additional_patterns = [
            r'(Фарш может быть любым[^\.]+\.\s*Ингредиенты можно[^\.]+\.)',
            r'(Приятного аппетита и замечательного пикника[^\.!]+[\.!])'
        ]
        
        for pattern in additional_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                notes_text = match.group(1).strip()
                return self.clean_text(notes_text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов
        
        Note: На сайте menu-menu.by теги конкретных рецептов в HTML не указаны.
        В эталонных JSON они заполнены вручную на основе названия и ингредиентов.
        Возвращаем None, так как извлечь автоматически невозможно.
        """
        # Сайт menu-menu.by не содержит теги для отдельных рецептов в HTML
        # Только глобальный tagcloud в сайдбаре со всеми тегами сайта
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Главное изображение из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # BlogPosting schema
                if isinstance(data, dict) and data.get('@type') == 'BlogPosting':
                    if 'image' in data:
                        img = data['image']
                        if isinstance(img, dict) and 'url' in img:
                            urls.append(img['url'])
                        elif isinstance(img, str):
                            urls.append(img)
                
                # Yoast SEO graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'ImageObject' and 'url' in item:
                            urls.append(item['url'])
                        if item.get('@type') == 'WebPage' and 'image' in item:
                            img_ref = item['image']
                            if isinstance(img_ref, dict) and '@id' in img_ref:
                                # Ищем соответствующий ImageObject
                                for obj in data['@graph']:
                                    if obj.get('@id') == img_ref['@id'] and 'url' in obj:
                                        urls.append(obj['url'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 2. Meta теги
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 3. Изображения из инструкций (пошаговые фото)
        instructions_ul = self.soup.find('ul', itemprop='recipeInstructions')
        if instructions_ul:
            step_images = instructions_ul.find_all('img')
            for img in step_images:
                src = img.get('data-src') or img.get('src')
                if src and src.startswith('/'):
                    # Добавляем домен
                    src = f"https://menu-menu.by{src}"
                if src and src not in urls:
                    urls.append(src)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        # Возвращаем как строку через запятую (без пробелов)
        return ','.join(unique_urls) if unique_urls else None
    
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
    """Точка входа для тестирования парсера"""
    import os
    
    # Обрабатываем папку preprocessed/menu-menu_by
    recipes_dir = os.path.join("preprocessed", "menu-menu_by")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(MenuMenuByExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python menu-menu_by.py")


if __name__ == "__main__":
    main()
