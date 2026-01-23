"""
Экстрактор данных рецептов для сайта foodlife.gr
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class FoodlifeGrExtractor(BaseRecipeExtractor):
    """Экстрактор для foodlife.gr"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1 внутри post-header
        header = self.soup.find('header', class_='post-header')
        if header:
            h1 = header.find('h1')
            if h1:
                full_title = self.clean_text(h1.get_text())
                
                # Удаляем финальную часть после тире (обычно дополнительное описание)
                if ' – ' in full_title or ' - ' in full_title:
                    full_title = re.split(r'\s+[–-]\s+', full_title)[0]
                
                # Паттерн 3: "συνταγή για το Название που..." → "Название" (проверяем сначала)
                match = re.search(r'για το\s+([^π]+?)(?:\s+που|\s+–|\s+-|$)', full_title, re.IGNORECASE)
                if match:
                    return match.group(1).strip()
                
                # Паттерны 1 и 2: Есть двоеточие
                if ':' in full_title:
                    parts = full_title.split(':', 1)
                    dish_part = parts[1].strip()
                    # Удаляем модификаторы (χωρίς, που)
                    # "με" не удаляем, так как это часть названия (μακαρονάδες με θαλασσινά)
                    modifiers = r'\s+(χωρίς|που)\s+'
                    match = re.search(modifiers, dish_part, re.IGNORECASE)
                    if match:
                        dish_name = dish_part[:match.start()].strip()
                        if dish_name:
                            return dish_name
                    return dish_part
                
                # Паттерн 4: Просто название - возвращаем как есть
                return full_title
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - Foodlife.gr"
            title = re.sub(r'\s+-\s+Foodlife\.gr.*$', '', title, flags=re.IGNORECASE)
            if ':' in title:
                dish_name = title.split(':', 1)[1].strip()
                return dish_name
            return title
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала ищем первый параграф в div.thecontent - это обычно описание
        content_div = self.soup.find('div', class_='thecontent')
        if content_div:
            first_p = content_div.find('p')
            if first_p:
                desc = self.clean_text(first_p.get_text())
                # Проверяем, что это не заголовок типа "Υλικά" или "Εκτέλεση"
                if desc and len(desc) > 20 and not desc.endswith(':'):
                    return desc
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "100g βιολογικό βούτυρο" или "4 αυγά"
            
        Returns:
            dict: {"name": "βούτυρο", "amount": "100", "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Греческие единицы: g, kg, ml, l, κ.σ. (столовая ложка), κ.γ. (чайная ложка)
        pattern = r'^([\d\s/.,]+)?\s*(g|kg|ml|l|κ\.σ\.|κ\.γ\.|σκελίδα|φλιτζάνι|φλιτζάνια|φλ\.|κούπα|κούπες|κιλό|γραμμάρια|φέτες?|φέτα|κομμάτια?)?\.?\s*(.+)$'
        
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
                # Return as int if whole number, otherwise as float
                amount = int(total) if total == int(total) else total
            else:
                # Заменяем запятую на точку для чисел
                amount_str = amount_str.replace(',', '.')
                try:
                    amount_val = float(amount_str)
                    # Return as int if whole number, otherwise as float
                    amount = int(amount_val) if amount_val == int(amount_val) else amount_val
                except ValueError:
                    amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        name = name.strip()
        
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
        
        # Ищем div с классом thecontent
        content_div = self.soup.find('div', class_='thecontent')
        if content_div:
            # Ищем ul список внутри
            ul_list = content_div.find('ul')
            if ul_list:
                items = ul_list.find_all('li')
                
                for item in items:
                    # Извлекаем текст ингредиента
                    ingredient_text = item.get_text(strip=True)
                    ingredient_text = self.clean_text(ingredient_text)
                    
                    if ingredient_text:
                        # Парсим в структурированный формат
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем div с классом thecontent
        content_div = self.soup.find('div', class_='thecontent')
        if content_div:
            # Ищем ol список (упорядоченный список шагов)
            ol_list = content_div.find('ol')
            if ol_list:
                items = ol_list.find_all('li')
                
                for item in items:
                    # Извлекаем текст инструкции
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    
                    if step_text:
                        steps.append(step_text)
            
            # Если нет ol, пробуем найти параграфы с инструкциями
            if not steps:
                paragraphs = content_div.find_all('p')
                for p in paragraphs:
                    text = self.clean_text(p.get_text())
                    if text and len(text) > 20:  # Только достаточно длинные параграфы
                        steps.append(text)
        
        # Объединяем шаги в одну строку через пробел
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем определить категорию по содержимому
        dish_name = self.extract_dish_name()
        
        # Простая эвристика для определения категории
        if dish_name:
            dish_lower = dish_name.lower()
            # Десерты
            if any(word in dish_lower for word in ['πίτα', 'πιτα', 'cheesecake', 'γλυκ', 'κανταϊφ', 'τούρτα', 'κέικ']):
                return 'Dessert'
            # Основные блюда
            if any(word in dish_lower for word in ['μακαρον', 'ψάρι', 'κρέας', 'θαλασσιν']):
                return 'Main Course'
        
        # Если не смогли определить по названию, оставляем None
        # (как в эталоне для некоторых рецептов)
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления из текста инструкций"""
        instructions = self.extract_instructions()
        if not instructions:
            return None
        
        # Ищем паттерны времени в инструкциях
        # Примеры: "ψήσε για 40'", "για 40 λεπτά", "12 λεπτά", "12 minutes"
        patterns = [
            r'ψήσε για\s+(\d+)',  # ψήσε για 40 (χωρίς ')
            r'για\s+(\d+)\s*[\'΄]',  # για 40'
            r'για\s+(\d+)\s+λεπτ[άα]',  # για 40 λεπτά
            r'(\d+)\s+λεπτ[άα]',  # 40 λεπτά
            r'(\d+)\s+minutes?',  # 40 minutes
            r'(\d+)\s*min',  # 40 min
        ]
        
        for pattern in patterns:
            match = re.search(pattern, instructions, re.IGNORECASE)
            if match:
                minutes = match.group(1)
                return f"{minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        instructions = self.extract_instructions()
        if not instructions:
            return None
        
        # Ищем паттерны для более длительного времени
        # Примеры: "για 5 ώρες", "για ένα βράδυ", "5 hours"
        patterns = [
            r'για\s+(\d+)\s+[ώω]ρες?',  # για 5 ώρες
            r'(\d+)\s+[ώω]ρες?',  # 5 ώρες
            r'(\d+)\s+hours?',  # 5 hours
            r'τουλάχιστον\s+(\d+)\s+[ώω]ρες?',  # τουλάχιστον 5 ώρες
        ]
        
        for pattern in patterns:
            match = re.search(pattern, instructions, re.IGNORECASE)
            if match:
                hours = match.group(1)
                return f"{hours} hours"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки (обычно не указано)"""
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок (обычно не указано в примерах)"""
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Ищем div с классом bottom-tags или post-tags
        tags_div = self.soup.find('div', class_=lambda x: x and any(cls in str(x) for cls in ['bottom-tags', 'post-tags']))
        if tags_div:
            # Ищем ul с классом urltags, затем все ссылки внутри
            ul = tags_div.find('ul', class_='urltags')
            if ul:
                tag_links = ul.find_all('a')
                for link in tag_links:
                    tag_text = self.clean_text(link.get_text())
                    if tag_text:
                        tags_list.append(tag_text.lower())
        
        # Также попробуем извлечь из JSON-LD если не нашли в HTML
        if not tags_list:
            json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
            
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    
                    if isinstance(data, dict) and '@graph' in data:
                        for item in data['@graph']:
                            if item.get('@type') == 'Article' and 'keywords' in item:
                                keywords = item['keywords']
                                if isinstance(keywords, list):
                                    tags_list.extend([k.lower() for k in keywords])
                                elif isinstance(keywords, str):
                                    # Разделяем по запятым
                                    tags_list.extend([k.strip().lower() for k in keywords.split(',')])
                                    
                except (json.JSONDecodeError, KeyError):
                    continue
        
        # Возвращаем как строку через запятую без пробела (как в эталоне)
        return ','.join(tags_list) if tags_list else None
    
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
        
        # 2. Ищем в figure с классом mainpost-image
        main_image = self.soup.find('figure', class_='mainpost-image')
        if main_image:
            img = main_image.find('img')
            if img and img.get('src'):
                urls.append(img['src'])
        
        # 3. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
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
                            if isinstance(img, str):
                                urls.append(img)
                            elif isinstance(img, dict):
                                if 'url' in img:
                                    urls.append(img['url'])
                                elif '@id' in img:
                                    # Это ссылка на другой объект в графе
                                    pass
            
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
    # Обрабатываем папку preprocessed/foodlife_gr
    preprocessed_dir = os.path.join("preprocessed", "foodlife_gr")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(FoodlifeGrExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python foodlife_gr.py")


if __name__ == "__main__":
    main()
