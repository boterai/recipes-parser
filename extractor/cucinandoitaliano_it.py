"""
Экстрактор данных рецептов для сайта cucinandoitaliano.it
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CucinandoItalianoExtractor(BaseRecipeExtractor):
    """Экстрактор для cucinandoitaliano.it"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1', class_='postitle')
        if not h1:
            h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - Cucinando Italiano"
            title = re.sub(r'\s*-\s*Cucinando Italiano.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # На cucinandoitaliano.it обычно нет отдельного описания
        # Мета-описание содержит смесь категории и ингредиентов, что не подходит
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "Salmone affumicato 300 g" или "Aneto q.b."
            
        Returns:
            dict: {"name": "Salmone affumicato", "units": "g", "amount": 300} или None
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
        
        # Паттерн для итальянских единиц измерения и q.b. (quanto basta - по вкусу)
        # Примеры: "Farina 200 g", "Latte 100 ml", "Sale q.b.", "Uova 2"
        pattern = r'^(.+?)\s+([\d\s/.,]+)?\s*(g|kg|ml|l|gr|grammi?|litri?|cucchiai[oa]?|cucchiaini?|q\.?b\.?|pizzico?|fetta|fette|spicchio|spicchi)?$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "units": None,
                "amount": None
            }
        
        name, amount_str, unit = match.groups()
        
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
                try:
                    # Преобразуем в число (int или float)
                    amount_str = amount_str.replace(',', '.')
                    amount = float(amount_str)
                    # Если это целое число, возвращаем int
                    if amount.is_integer():
                        amount = int(amount)
                except ValueError:
                    amount = None
        
        # Очистка названия
        name = name.strip()
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "units": unit,
            "amount": amount
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем контент
        content = self.soup.find('div', class_='single_post_content')
        if not content:
            content = self.soup
        
        # Ищем список ингредиентов (обычно в <ul>)
        # На cucinandoitaliano.it ингредиенты могут быть в нескольких <ul> списках
        ul_lists = content.find_all('ul')
        
        for ul in ul_lists:
            # Извлекаем элементы списка
            items = ul.find_all('li')
            
            for item in items:
                # Извлекаем текст ингредиента
                ingredient_text = item.get_text(separator=' ', strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                # Пропускаем заголовки секций и слишком длинные тексты (это скорее инструкции)
                if ingredient_text and len(ingredient_text) < 100:
                    # Парсим в структурированный формат
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # На cucinandoitaliano.it инструкции обычно в параграфах
        # Ищем основной контент
        content = self.soup.find('div', class_='single_post_content')
        if not content:
            content = self.soup.find('div', class_='entry-content')
        if not content:
            content = self.soup.find('div', class_='post-content')
        
        if not content:
            return None
        
        # Ищем все параграфы
        paragraphs = content.find_all('p')
        
        # Определяем, какие параграфы - это инструкции
        # Инструкции обычно начинаются с "Per preparare" и идут до заметок
        instructions_text = []
        notes_started = False
        
        for p in paragraphs:
            text = p.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            
            # Пропускаем параграфы с категорией
            if text and text.startswith('Categoria:'):
                continue
            
            # Проверяем, не начались ли заметки
            if text and (text.startswith('Consigliamo') or text.startswith('Si consiglia') or 
                        text.startswith('E\' possibile') or text.startswith('È possibile') or
                        text.startswith("E' possibile") or  # вариант без обратного слеша
                        text.startswith('Al posto') or text.startswith('Se amate') or
                        text.startswith('Conservazione:')):
                notes_started = True
                continue
            
            # Если заметки еще не начались и текст достаточно длинный - это инструкция
            if not notes_started and text and len(text) > 50:
                instructions_text.append(text)
        
        # Объединяем в единую строку
        if instructions_text:
            return ' '.join(instructions_text)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в тексте "Categoria: <название>"
        content = self.soup.find('div', class_='single_post_content')
        if not content:
            content = self.soup.find('div', class_='entry-content')
        if not content:
            content = self.soup.find('div', class_='post-content')
        
        if content:
            # Ищем параграф с категорией
            paragraphs = content.find_all('p')
            for p in paragraphs:
                text = p.get_text(strip=True)
                if text.startswith('Categoria:'):
                    # Извлекаем название категории
                    category = text.replace('Categoria:', '').strip()
                    return self.clean_text(category)
        
        # Альтернативно - из мета-тегов или классов
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_time_from_text(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени из текста страницы
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # На cucinandoitaliano.it время часто указано в тексте инструкций
        # Паттерны для поиска времени
        patterns = {
            'prep': [r'preparazione[:\s]+(\d+)\s*(minut[oi]|ore?|h)', r'prep[:\s]+(\d+)\s*(minut[oi]|ore?|h)'],
            'cook': [
                r'cottura[:\s]+(\d+)\s*(minut[oi]|secondi|ore?|h)',
                r'cuocere[:\s]+(\d+)\s*(minut[oi]|secondi|ore?|h)', 
                r'(\d+)\s*minut[oi]\s*di\s*cottura',
                # Специальный паттерн для "X secondi ... altri X secondi" (должен быть ПЕРЕД простым паттерном)
                r'(\d+)\s*secondi[^.]*altri\s*(\d+)\s*secondi',
                r'per\s*circa\s*(\d+)\s*(minut[oi]|secondi)',
                r'per\s*(\d+)\s*(minut[oi]|secondi)',
                r'(\d+)\s*secondi'  # Простой паттерн как fallback
            ],
            'total': [r'tempo\s+totale[:\s]+(\d+)\s*(minut[oi]|ore?|h)', r'totale[:\s]+(\d+)\s*(minut[oi]|ore?|h)']
        }
        
        # Получаем весь текст страницы
        page_text = self.soup.get_text()
        
        for pattern in patterns.get(time_type, []):
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                # Специальная обработка для паттерна "X secondi ... altri X secondi"
                if len(match.groups()) >= 2 and match.group(2) and match.group(2).isdigit():
                    time1 = int(match.group(1))
                    time2 = int(match.group(2))
                    total_seconds = time1 + time2
                    minutes = round(total_seconds / 60)
                    return f"{max(1, minutes)} minutes"
                
                time_value = match.group(1)
                time_unit = match.group(2) if len(match.groups()) > 1 else 'minuti'
                
                # Конвертируем в минуты если нужно
                if 'ore' in time_unit or time_unit == 'h':
                    time_value = str(int(time_value) * 60)
                elif 'second' in time_unit:
                    # Конвертируем секунды в минуты, округляем
                    seconds = int(time_value)
                    minutes = round(seconds / 60)
                    time_value = str(max(1, minutes))  # минимум 1 минута
                
                return f"{time_value} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time_from_text('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time_from_text('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time_from_text('total')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # На cucinandoitaliano.it заметки обычно в конце, начинаются с определенных фраз
        content = self.soup.find('div', class_='single_post_content')
        if not content:
            content = self.soup.find('div', class_='entry-content')
        if not content:
            content = self.soup.find('div', class_='post-content')
        
        if not content:
            return None
        
        paragraphs = content.find_all('p')
        
        # Ищем параграфы с советами (начинаются с "Consigliamo", "Si consiglia", "E' possibile", и т.д.)
        notes = []
        for p in paragraphs:
            text = p.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            
            # Проверяем различные паттерны для заметок
            if text and (text.startswith('Consigliamo') or text.startswith('Si consiglia') or 
                        text.startswith('E\' possibile') or text.startswith('È possibile') or
                        text.startswith("E' possibile") or  # вариант без обратного слеша
                        text.startswith('Al posto') or text.startswith('Se amate') or
                        'conservare' in text.lower()[:50] or 'conservazione' in text.lower()[:50]):
                notes.append(text)
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем теги в мета-тегах или keywords
        keywords_meta = self.soup.find('meta', {'name': 'keywords'})
        if keywords_meta and keywords_meta.get('content'):
            return keywords_meta['content']
        
        # Можно также искать в JSON-LD или других местах
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
                        # BlogPosting с image
                        elif item.get('@type') == 'BlogPosting' and 'image' in item:
                            img = item['image']
                            if isinstance(img, dict) and 'url' in img:
                                urls.append(img['url'])
                            elif isinstance(img, str):
                                urls.append(img)
            
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 3. Ищем изображения в контенте
        content = self.soup.find('div', class_='entry-content')
        if content:
            images = content.find_all('img')
            for img in images[:3]:  # Берем первые 3
                src = img.get('src') or img.get('data-src')
                if src and 'http' in src:
                    urls.append(src)
        
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
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_steps()
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
    """Обработка файлов из preprocessed/cucinandoitaliano_it"""
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join("preprocessed", "cucinandoitaliano_it")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(CucinandoItalianoExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python cucinandoitaliano_it.py")


if __name__ == "__main__":
    main()
