"""
Экстрактор данных рецептов для сайта taffel.se
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TaffelExtractor(BaseRecipeExtractor):
    """Экстрактор для taffel.se"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1 с классом wp-block-post-title
        title = self.soup.find('h1', class_='wp-block-post-title')
        if title:
            return self.clean_text(title.get_text())
        
        # Альтернативно - из обычного h1
        title = self.soup.find('h1')
        if title:
            return self.clean_text(title.get_text())
        
        # Из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title_text = og_title['content']
            # Убираем суффикс " – Taffel" если есть
            title_text = re.sub(r'\s+[–-]\s+Taffel\s*$', '', title_text, flags=re.IGNORECASE)
            return self.clean_text(title_text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем параграф после поля времени (recept_tid)
        time_p = self.soup.find('p', class_='recept_tid')
        if time_p:
            # Ищем первый обычный параграф после времени (без служебных классов)
            next_p = time_p.find_next('p')
            while next_p:
                classes = next_p.get('class', [])
                # Пропускаем параграфы с служебными классами
                if not classes or not any('recept_' in str(c) for c in classes):
                    text = self.clean_text(next_p.get_text())
                    if text and len(text) > 20:
                        # Берем только первое предложение
                        sentences = text.split('. ')
                        if sentences:
                            return sentences[0] + ('.' if not sentences[0].endswith('.') else '')
                    break
                next_p = next_p.find_next('p')
        
        # Если не нашли, проверяем meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            if len(desc) > 20 and not desc.startswith('Taffel'):
                return self.clean_text(desc)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента на шведском языке в структурированный формат
        
        Args:
            ingredient_text: Строка вида "50 g smör" или "3 ägg"
            
        Returns:
            dict: {"name": "smör", "amount": "50", "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).strip()
        
        # Пропускаем пустые строки и заголовки разделов (обычно заканчиваются на ':')
        if not text or text.endswith(':'):
            return None
        
        # Заменяем дроби на десятичные числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "50 g smör", "3 ägg", "1 dl mjölk", "2 1/2 dl socker"
        # Шведские единицы: g, kg, ml, dl, l, msk (matsked), tsk (tesked), krm (kryddmått), st (styck), stång, nypa
        # Важно: используем границы слов \b чтобы избежать ложных срабатываний
        pattern = r'^([\d\s/.,+-]+)?\s*(g(?!\w)|kg(?!\w)|ml(?!\w)|dl(?!\w)|l(?!\w)|msk(?!\w)|tsk(?!\w)|krm(?!\w)|st(?!\w)|styck|matsked|tesked|kryddmått|stång|stänger|nypa)?\s*(.+)'
        
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
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2" или "2 1/2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                amount = str(total) if total != int(total) else str(int(total))
            else:
                # Обработка диапазонов типа "2-3"
                if '-' in amount_str or '+' in amount_str:
                    # Берем первое число из диапазона
                    amount = re.search(r'(\d+(?:[.,]\d+)?)', amount_str)
                    if amount:
                        amount = amount.group(1).replace(',', '.')
                else:
                    amount = amount_str.replace(',', '.')
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем дополнительные пояснения после запятой (например ", helst nystött", ", gärna smaksatt")
        name = re.sub(r',\s+.*$', '', name)
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
        
        # Ищем список ингредиентов по классу recept_ingrediens
        ingredient_list = self.soup.find('ul', class_='recept_ingrediens')
        
        if ingredient_list:
            items = ingredient_list.find_all('li')
            
            for item in items:
                # Пропускаем заголовки разделов (например, "Till servering:")
                # и все элементы после них (обычно это дополнительные опциональные ингредиенты)
                item_classes = item.get('class', [])
                if 'recept_ingrediens_mellanrubrik' in item_classes:
                    # Встретили заголовок раздела - прекращаем парсинг
                    break
                
                # Извлекаем текст ингредиента
                # Иногда текст в <span class="Ingredients"> с <br/> тегами внутри
                span = item.find('span', class_='Ingredients')
                if span:
                    # Используем '\n' как разделитель для <br/> тегов
                    ingredient_text = span.get_text(separator='\n', strip=True)
                else:
                    ingredient_text = item.get_text(separator='\n', strip=True)
                
                # Разбиваем по переносам строк (из-за <br/> тегов)
                lines = ingredient_text.split('\n')
                
                for line in lines:
                    line = line.strip()
                    if line:
                        # Парсим в структурированный формат
                        parsed = self.parse_ingredient(line)
                        if parsed:
                            ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        # Ищем упорядоченный список шагов - сначала с классом
        steps_list = self.soup.find('ol', class_='recept_steg')
        
        # Если не нашли с классом, ищем любой ol
        if not steps_list:
            steps_list = self.soup.find('ol')
        
        if steps_list:
            steps = []
            items = steps_list.find_all('li')
            
            for item in items:
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    steps.append(step_text)
            
            # Объединяем шаги в одну строку через пробел
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в мета-тегах
        meta_category = self.soup.find('meta', property='article:section')
        if meta_category and meta_category.get('content'):
            return self.clean_text(meta_category['content'])
        
        # Ищем в meta keywords или tags
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Берем первое слово как категорию
            first_keyword = keywords.split(',')[0].strip()
            if first_keyword:
                return self.clean_text(first_keyword)
        
        # Ищем в breadcrumbs или навигации
        breadcrumb = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumb:
            links = breadcrumb.find_all('a')
            if len(links) > 1:
                # Берем предпоследнюю ссылку (последняя обычно - сам рецепт)
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def parse_time_swedish_to_english(self, time_text: str) -> Optional[str]:
        """
        Конвертирует шведское время в английский формат
        
        Args:
            time_text: "30 minuter", "1 timme", "15 minuter+3 timmar i kyl"
            
        Returns:
            "30 minutes", "1 hour", "15 minutes+3 hours in fridge"
        """
        if not time_text:
            return None
        
        # Словарь замен
        replacements = {
            'minuter': 'minutes',
            'minut': 'minute',
            'timmar': 'hours',
            'timme': 'hour',
            'i kyl': 'in fridge',
            'ugn': 'oven'
        }
        
        result = time_text
        for swedish, english in replacements.items():
            result = re.sub(r'\b' + swedish + r'\b', english, result, flags=re.IGNORECASE)
        
        return result
    
    def extract_time_from_field(self) -> dict:
        """
        Извлечение времени из поля recept_tid
        Формат: "Tid: 30 minuter" или "Tid: 15 minuter+3 timmar i kyl"
        
        Returns:
            dict: {"prep_time": ..., "cook_time": ..., "total_time": ...}
        """
        time_elem = self.soup.find('p', class_='recept_tid')
        
        result = {
            "prep_time": None,
            "cook_time": None,
            "total_time": None
        }
        
        if not time_elem:
            return result
        
        time_text = time_elem.get_text(strip=True)
        # Убираем "Tid: " в начале
        time_text = re.sub(r'^Tid:\s*', '', time_text, flags=re.IGNORECASE)
        
        # Конвертируем в английский формат
        time_english = self.parse_time_swedish_to_english(time_text)
        
        # Если есть разделение на части (например, "15 minuter+3 timmar i kyl")
        if '+' in time_text:
            parts = time_text.split('+')
            # Первая часть - обычно время готовки
            cook_part = self.clean_text(parts[0])
            if cook_part:
                result["cook_time"] = self.parse_time_swedish_to_english(cook_part)
            
            # Суммируем для total_time
            result["total_time"] = time_english
        else:
            # Если только одно значение - считаем его total_time
            result["total_time"] = time_english
        
        return result
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        times = self.extract_time_from_field()
        return times.get("prep_time")
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        times = self.extract_time_from_field()
        return times.get("cook_time")
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        times = self.extract_time_from_field()
        return times.get("total_time")
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем параграфы после поля времени (recept_tid)
        time_p = self.soup.find('p', class_='recept_tid')
        if not time_p:
            return None
        
        # Собираем все обычные параграфы после времени
        paragraphs = []
        next_p = time_p.find_next('p')
        while next_p:
            classes = next_p.get('class', [])
            # Пропускаем параграфы с служебными классами
            if not classes or not any('recept_' in str(c) for c in classes):
                text = self.clean_text(next_p.get_text())
                if text and len(text) > 10:
                    paragraphs.append(text)
            next_p = next_p.find_next('p')
        
        if not paragraphs:
            return None
        
        # Стратегия извлечения заметок:
        # 1. Если есть второй параграф, берем его (часто это заметки)
        if len(paragraphs) >= 2:
            return paragraphs[1]
        
        # 2. Если только один параграф, берем все предложения кроме первого
        if len(paragraphs) == 1:
            sentences = paragraphs[0].split('. ')
            if len(sentences) > 1:
                # Объединяем остальные предложения
                notes = '. '.join(sentences[1:])
                notes = notes.strip()
                if notes and len(notes) > 10:
                    return notes
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Очищаем и форматируем
            tags = [self.clean_text(tag) for tag in keywords.split(',')]
            tags = [tag for tag in tags if tag and len(tag) > 2]
            if tags:
                return ', '.join(tags)
        
        # Ищем в article:tag meta
        article_tags = self.soup.find_all('meta', property='article:tag')
        if article_tags:
            tags = []
            for tag_meta in article_tags:
                tag = tag_meta.get('content')
                if tag:
                    tags.append(self.clean_text(tag))
            if tags:
                return ', '.join(tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем featured image в WordPress
        featured_img = self.soup.find('figure', class_='wp-block-post-featured-image')
        if featured_img:
            img = featured_img.find('img')
            if img and img.get('src'):
                urls.append(img['src'])
        
        # 2. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Ищем основное изображение рецепта с классом wp-post-image
        main_img = self.soup.find('img', class_='wp-post-image')
        if main_img and main_img.get('src'):
            urls.append(main_img['src'])
        
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
            Словарь с данными рецепта в формате, совместимом с базой данных
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    """
    Точка входа для обработки директории с HTML файлами taffel.se
    """
    import os
    
    # Путь к директории с примерами
    preprocessed_dir = os.path.join("preprocessed", "taffel_se")
    
    # Проверяем существование директории
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(TaffelExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python taffel_se.py")


if __name__ == "__main__":
    main()
