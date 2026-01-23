"""
Экстрактор данных рецептов для сайта madebykristina.cz
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MadeByKristinaExtractor(BaseRecipeExtractor):
    """Экстрактор для madebykristina.cz"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в meta itemprop="name"
        name_meta = self.soup.find('meta', itemprop='name')
        if name_meta and name_meta.get('content'):
            name = name_meta['content']
            # Убираем символ # в начале, если есть
            name = name.strip('#').strip()
            return self.clean_text(name)
        
        # Альтернативно - из title тега
        title = self.soup.find('title')
        if title:
            title_text = title.get_text()
            # Убираем суффиксы
            title_text = re.sub(r'\s*\|.*$', '', title_text)
            title_text = title_text.strip('#').strip()
            return self.clean_text(title_text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем описание в div с классом 'popis-kika'
        desc_div = self.soup.find('div', class_='popis-kika')
        if desc_div:
            # Ищем параграф внутри
            p = desc_div.find('p')
            if p:
                text = p.get_text(strip=True)
                return self.clean_text(text) if text else None
        
        # Если не нашли в popis-kika, берем из meta description
        meta_desc = self.soup.find('meta', property='og:description')
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient_text(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            text: Строка вида "200 g cukru krystal" или "1 vejce"
            
        Returns:
            dict: {"name": "cukru krystal", "amount": 200, "unit": "g"}
        """
        if not text:
            return None
        
        text = self.clean_text(text).lower()
        
        # Убираем комментарии в скобках в конце
        text = re.sub(r'\([^)]*\)$', '', text).strip()
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "200 g cukru", "1 lžíce vanilky", "4 vejce"
        # Поддерживаем дроби: "1-2 mrkve", "½ kg"
        # ВАЖНО: Длинные единицы (lžíce) должны идти перед короткими (l), чтобы избежать частичного совпадения
        pattern = r'^([\d\s/.,\-½¼¾⅓⅔]+)?\s*(lžíce|lžíci|lžící|lžička|lžičku|lžiček|lžic|stroužky?|stroužek|snítky?|snítek|kg|ml|g|l|ks|kus|kusy|láhev|hrst|svazek|pcs)?\s*(.+)$'
        
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
            # Заменяем дроби
            amount_str = amount_str.replace('½', '0.5').replace('¼', '0.25').replace('¾', '0.75')
            amount_str = amount_str.replace('⅓', '0.33').replace('⅔', '0.67')
            
            # Если есть дефис (диапазон), оставляем как строку
            if '-' in amount_str and '/' not in amount_str:
                amount = amount_str.replace(',', '.')
            elif '/' in amount_str:
                # Обработка дробей типа "1/2"
                try:
                    num, denom = amount_str.split('/')
                    amount = float(num.strip()) / float(denom.strip())
                except:
                    amount = amount_str
            else:
                try:
                    amount = float(amount_str.replace(',', '.'))
                    # Если целое число, преобразуем в int
                    if amount == int(amount):
                        amount = int(amount)
                except:
                    amount = amount_str
        
        # Обработка единицы измерения - нормализация к базовой форме
        if unit:
            unit = unit.strip().lower()
            # Нормализация единиц измерения
            unit_map = {
                'lžíci': 'lžíce',
                'lžící': 'lžíce',
                'lžička': 'lžíce',
                'lžičku': 'lžíce',
                'stroužek': 'stroužky',
                'snítek': 'snítky',
                'kus': 'ks',
                'kusy': 'ks',
            }
            unit = unit_map.get(unit, unit)
        
        # Очистка названия
        name = name.strip()
        # Убираем лишние слова в конце
        name = re.sub(r'\b(nebo.*|případně.*|volitelně.*|podle chuti)$', '', name, flags=re.IGNORECASE).strip()
        
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
        
        # Ищем заголовок "Suroviny"
        h2_suroviny = self.soup.find('h2', string=lambda s: s and 'Suroviny' in s)
        
        if h2_suroviny:
            # Собираем все элементы списка между этим h2 и следующим h2
            current = h2_suroviny
            while current:
                current = current.find_next_sibling()
                if current and current.name == 'h2':
                    break  # Дошли до следующей секции
                
                if current and current.name in ['div', 'ul']:
                    # Находим все li внутри
                    items = current.find_all('li')
                    for item in items:
                        ingredient_text = item.get_text(strip=True)
                        ingredient_text = self.clean_text(ingredient_text)
                        
                        if ingredient_text:
                            parsed = self.parse_ingredient_text(ingredient_text)
                            if parsed and parsed['name']:
                                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем div с классом "recept-postup"
        postup_div = self.soup.find('div', class_='recept-postup')
        
        if postup_div:
            # Ищем заголовок "Postup"
            h2_postup = postup_div.find('h2', string=lambda s: s and 'Postup' in s)
            
            if h2_postup:
                # Вариант 1: Инструкции в div после h2
                next_div = h2_postup.find_next_sibling('div')
                if next_div:
                    div_text = next_div.get_text(strip=True)
                    # Проверяем, не является ли это div с советами или другим контентом
                    if div_text and 'Můj tip' not in div_text and 'Buďte první' not in div_text and 'plus-gallery' not in str(next_div.get('class')):
                        # Это div с инструкциями - извлекаем все параграфы
                        paragraphs = next_div.find_all('p')
                        for p in paragraphs:
                            step_text = p.get_text(separator=' ', strip=True)
                            step_text = self.clean_text(step_text)
                            
                            if step_text and not step_text.startswith('Buďte první') and not step_text.startswith('Dobrou chuť'):
                                steps.append(step_text)
                
                # Вариант 2: Инструкции в параграфах/списках напрямую после h2
                if not steps:
                    # Собираем все p, ul элементы после h2 до первого div с классом или h3
                    current = h2_postup
                    while current:
                        current = current.find_next_sibling()
                        if not current:
                            break
                        
                        # Останавливаемся если встретили div с советами или секцией галереи
                        if current.name == 'div':
                            div_class = current.get('class', [])
                            if any(cls in ['banner-tip', 'plus-gallery-wrap', 'rec-bye', 'tab-pane'] for cls in div_class):
                                break
                        
                        if current.name == 'p':
                            step_text = current.get_text(separator=' ', strip=True)
                            step_text = self.clean_text(step_text)
                            if step_text:
                                steps.append(step_text)
                        elif current.name == 'ul':
                            # Иногда инструкции в списке
                            items = current.find_all('li')
                            for item in items:
                                step_text = item.get_text(separator=' ', strip=True)
                                step_text = self.clean_text(step_text)
                                if step_text:
                                    steps.append(step_text)
        
        # Объединяем все шаги в одну строку
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Пытаемся извлечь из JSON в dataLayer
        scripts = self.soup.find_all('script')
        for script in scripts:
            if script.string and 'currentCategory' in script.string:
                # Ищем currentCategory в JavaScript
                match = re.search(r'"currentCategory"\s*:\s*"([^"]+)"', script.string)
                if match:
                    category = match.group(1)
                    # Пропускаем общую категорию "Recepty"
                    if category and category != 'Recepty':
                        return self.clean_text(category)
        
        # Если не нашли специфическую категорию, возвращаем None
        # (в примерах категории определены вручную: Dessert, Main Course, Salát)
        return None
    
    def extract_time_from_text(self, text: str) -> Optional[str]:
        """Извлечение времени из текста инструкций"""
        if not text:
            return None
        
        # Ищем паттерны времени в тексте
        # Примеры: "45 minut", "3 až 3,5 hodiny", "60 minut"
        time_patterns = [
            r'(\d+(?:[,\.]\d+)?)\s*(?:až|-)?\s*(\d+(?:[,\.]\d+)?)?\s*hodin[yu]?',  # часы
            r'(\d+)\s*minut',  # минуты
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # В madebykristina нет явных меток для prep_time
        # Время может быть указано в тексте инструкций или отсутствовать
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте инструкций упоминания о времени готовки
        instructions = self.extract_instructions()
        if instructions:
            # Ищем фразы типа "peču ... 45 minut" или "vařím 60 minut"
            time_match = re.search(r'(?:peču|vařím|peču|pečení|vaření).*?(\d+(?:[,\.]\d+)?(?:\s*až\s*\d+(?:[,\.]\d+)?)?\s*(?:hodin[yu]?|minut))', instructions, re.IGNORECASE)
            if time_match:
                return time_match.group(1)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Можно попробовать найти в инструкциях
        # или вычислить из prep_time + cook_time
        instructions = self.extract_instructions()
        if instructions:
            # Ищем упоминания общего времени
            # Например: "minimálně 2 hodiny"
            time_match = re.search(r'(?:celkem|minimálně|přibližně)\s*(\d+(?:[,\.]\d+)?(?:\s*až\s*\d+(?:[,\.]\d+)?)?\s*(?:hodin[yu]?|minut))', instructions, re.IGNORECASE)
            if time_match:
                return time_match.group(1)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию после инструкций или специальные блоки с заметками
        postup_div = self.soup.find('div', class_='recept-postup')
        
        if postup_div:
            # Ищем div с классом 'banner-tip' или 'tip-kika'
            tip_div = postup_div.find('div', class_=['banner-tip', 'tip-kika', 'tip-text'])
            if tip_div:
                # Извлекаем текст из этого div
                text = tip_div.get_text(strip=True)
                # Убираем заголовок "Můj tip"
                text = re.sub(r'^Můj tip\s*', '', text, flags=re.IGNORECASE)
                # Убираем служебные фразы
                text = re.sub(r'Dobrou chuť.*$', '', text, flags=re.IGNORECASE)
                text = self.clean_text(text)
                if text:
                    return text
            
            # Альтернативный вариант: ищем div, который содержит "Můj tip"
            for div in postup_div.find_all('div'):
                div_text = div.get_text(strip=True)
                if 'Můj tip' in div_text:
                    # Нашли div с советами
                    # Извлекаем все параграфы из этого div
                    notes = []
                    paragraphs = div.find_all('p')
                    for p in paragraphs:
                        text = p.get_text(strip=True)
                        # Пропускаем служебные параграфы и заголовок
                        if text and not text.startswith('Můj tip') and not text.startswith('Buďte první') and not text.startswith('Dobrou chuť') and 'Výpis hodnocení' not in text:
                            notes.append(self.clean_text(text))
                    
                    if notes:
                        return ' '.join(notes)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags.extend([k.strip() for k in keywords.split(',') if k.strip()])
        
        # Также проверяем JavaScript dataLayer на наличие тегов
        scripts = self.soup.find_all('script')
        for script in scripts:
            if script.string and 'dataLayer' in script.string:
                # Ищем возможные теги в структуре данных
                pass  # В текущих примерах тегов в dataLayer нет
        
        # Если теги не найдены, возвращаем None
        # (в примерах теги определены вручную или из других источников)
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в meta itemprop="image"
        img_meta = self.soup.find('meta', itemprop='image')
        if img_meta and img_meta.get('content'):
            urls.append(img_meta['content'])
        
        # 2. Ищем в og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)
        
        # 3. Ищем img теги в контенте рецепта
        recipe_content = self.soup.find('div', class_='p-detail')
        if recipe_content:
            images = recipe_content.find_all('img', src=True)
            for img in images[:3]:  # Ограничиваем до 3 изображений
                src = img.get('src')
                # Пропускаем маленькие иконки и лого
                if src and 'logo' not in src.lower() and 'icon' not in src.lower():
                    # Добавляем полный URL если нужно
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        src = 'https://www.madebykristina.cz' + src
                    
                    if src not in urls:
                        urls.append(src)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        # Возвращаем как строку через запятую
        return ','.join(unique_urls) if unique_urls else None
    
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта
        
        Returns:
            Словарь с данными рецепта
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
    import os
    # Обрабатываем папку preprocessed/madebykristina_cz
    recipes_dir = os.path.join("preprocessed", "madebykristina_cz")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(MadeByKristinaExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python madebykristina_cz.py")


if __name__ == "__main__":
    main()
