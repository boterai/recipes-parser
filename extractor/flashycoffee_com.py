"""
Экстрактор данных рецептов для сайта flashycoffee.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class FlashyCoffeeExtractor(BaseRecipeExtractor):
    """Экстрактор для flashycoffee.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в flashy-recipe-image-title
        recipe_title = self.soup.find('h2', class_='flashy-recipe-image-title')
        if recipe_title:
            title = self.clean_text(recipe_title.get_text())
            # Убираем стандартный суффикс "How to Make the Best ... Recipe at Home"
            title = re.sub(r'^How\s+to\s+Make\s+(the\s+Best\s+)?', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s+(Recipe|at\s+Home).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s+(Recipe|Recipe:).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Из h1
        h1 = self.soup.find('h1')
        if h1:
            title = h1.get_text()
            title = re.sub(r'^How\s+to\s+Make\s+(the\s+Best\s+)?', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s+(Recipe|at\s+Home).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем первый параграф с описанием рецепта перед recipe card
        # Обычно это первый абзац после заголовка "Mocha Latte Recipe"
        recipe_heading = self.soup.find('h2', string=re.compile(r'.*Recipe$', re.I))
        if recipe_heading:
            # Ищем следующий параграф
            next_p = recipe_heading.find_next('p')
            if next_p:
                text = self.clean_text(next_p.get_text())
                # Берем только первое предложение
                if text:
                    sentences = text.split('.')
                    if sentences:
                        return sentences[0].strip() + '.'
        
        # Альтернативно - ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из recipe card"""
        ingredients = []
        
        # Ищем секцию с ингредиентами в flashy-recipe-card
        recipe_card = self.soup.find('div', class_='flashy-recipe-card')
        if not recipe_card:
            return None
        
        # Ищем все кнопки ингредиентов
        ingredient_buttons = recipe_card.find_all('a', class_='flashy-item-button')
        
        for button in ingredient_buttons:
            # Проверяем, что это ингредиент, а не оборудование
            # Ингредиенты обычно идут перед секцией Equipment
            parent_section = button.find_parent('div', class_='flashy-items-grid')
            if not parent_section:
                continue
            
            # Проверяем предыдущий заголовок секции
            section_title = parent_section.find_previous_sibling('h3', class_='flashy-section-title')
            if section_title and 'Equipment' in section_title.get_text():
                # Это секция оборудования, пропускаем
                continue
            
            # Извлекаем название ингредиента
            name_elem = button.find('span', class_='flashy-item-name')
            if not name_elem:
                continue
            
            name = self.clean_text(name_elem.get_text())
            
            # Извлекаем количество
            quantity_elem = button.find('span', class_='flashy-item-quantity')
            amount = None
            unit = None
            
            if quantity_elem:
                quantity_text = self.clean_text(quantity_elem.get_text())
                # Парсим количество и единицу измерения
                parsed = self.parse_quantity(quantity_text)
                if parsed:
                    amount = parsed.get('amount')
                    unit = parsed.get('unit')
            
            # Convert amount to number if possible
            amount_value = amount
            if amount:
                try:
                    # Handle fractions like "1/2"
                    if '/' in amount:
                        parts = amount.split('/')
                        if len(parts) == 2:
                            amount_value = float(parts[0]) / float(parts[1])
                    else:
                        amount_value = float(amount)
                except (ValueError, ZeroDivisionError):
                    amount_value = amount
            
            ingredient = {
                "name": name,
                "unit": unit,  # Use "units" plural to match expected format
                "amount": amount_value
            }
            
            ingredients.append(ingredient)
        
        # Если не нашли в recipe card, пробуем альтернативный способ
        if not ingredients:
            ingredient_list = recipe_card.find('ul', class_='wp-block-list')
            if ingredient_list:
                for li in ingredient_list.find_all('li'):
                    text = self.clean_text(li.get_text())
                    parsed = self.parse_ingredient_text(text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_quantity(self, quantity_text: str) -> Optional[dict]:
        """
        Парсинг строки количества вида "1 cup", "2 tablespoons", "1 whole"
        
        Returns:
            dict: {"amount": "1", "unit": "cup"}
        """
        if not quantity_text:
            return None
        
        # Паттерн для извлечения количества и единицы
        # Примеры: "1 cup", "2 tablespoons", "1/2 cup", "1 whole"
        pattern = r'^([\d\s/.,]+)?\s*(.+)?$'
        match = re.match(pattern, quantity_text, re.IGNORECASE)
        
        if not match:
            return None
        
        amount_str, unit_str = match.groups()
        
        amount = None
        if amount_str:
            amount = amount_str.strip()
        
        unit = None
        if unit_str:
            unit = unit_str.strip()
        
        return {
            "amount": amount,
            "unit": unit
        }
    
    def parse_ingredient_text(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента из текста
        
        Args:
            text: Строка вида "1 cup milk" или "2 tablespoons chocolate syrup"
            
        Returns:
            dict: {"name": "milk", "amount": "1", "unit": "cup"}
        """
        if not text:
            return None
        
        # Паттерн для извлечения количества, единицы и названия
        pattern = r'^([\d\s/.,]+)?\s*(cup|cups|tablespoon|tablespoons|teaspoon|teaspoons|tbsp|tsp|shot|shots|whole)?\s*(?:of\s+)?(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
        
        amount_str, unit, name = match.groups()
        
        amount = None
        if amount_str:
            amount = amount_str.strip()
        
        if unit:
            unit = unit.strip()
        
        if name:
            name = name.strip()
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        # Ищем секцию инструкций в flashy-recipe-card
        recipe_card = self.soup.find('div', class_='flashy-recipe-card')
        if not recipe_card:
            return None
        
        # Ищем ordered list с инструкциями
        instructions_div = recipe_card.find('div', class_='flashy-instructions')
        if instructions_div:
            ol = instructions_div.find('ol')
            if ol:
                steps = []
                for li in ol.find_all('li', recursive=False):
                    step_text = self.clean_text(li.get_text())
                    if step_text:
                        steps.append(step_text)
                
                if steps:
                    return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в метаданных article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в JSON-LD BlogPosting
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BlogPosting':
                            if 'articleSection' in item:
                                return self.clean_text(item['articleSection'])
                elif isinstance(data, dict) and data.get('@type') == 'BlogPosting':
                    if 'articleSection' in data:
                        return self.clean_text(data['articleSection'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', class_='rank-math-breadcrumb')
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                # Берем предпоследнюю категорию
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени из trust-bar
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Ищем flashy-trust-bar
        trust_bar = self.soup.find('div', class_='flashy-trust-bar')
        if not trust_bar:
            return None
        
        # Маппинг типов на текст лейблов
        label_map = {
            'prep': 'Prep Time',
            'cook': 'Cook Time',
            'total': 'Total Time'
        }
        
        target_label = label_map.get(time_type)
        if not target_label:
            return None
        
        # Ищем все trust-item
        trust_items = trust_bar.find_all('div', class_='flashy-trust-item')
        for item in trust_items:
            label = item.find('div', class_='flashy-trust-label')
            if label and target_label in label.get_text():
                value = item.find('div', class_='flashy-trust-value')
                if value:
                    return self.clean_text(value.get_text())
        
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
        """Извлечение заметок и советов из Pro Tip"""
        # Ищем flashy-pro-tip-box
        pro_tip = self.soup.find('div', class_='flashy-pro-tip-box')
        if not pro_tip:
            return None
        
        # Извлекаем список советов
        ul = pro_tip.find('ul')
        if ul:
            tips = []
            for li in ul.find_all('li'):
                tip_text = self.clean_text(li.get_text())
                if tip_text:
                    tips.append(tip_text)
            
            if tips:
                return ' '.join(tips)
        
        # Альтернативно - весь текст без заголовка
        text = pro_tip.get_text(separator=' ', strip=True)
        text = re.sub(r'^💡\s*Pro\s+Tip\s*', '', text, flags=re.I)
        text = self.clean_text(text)
        return text if text else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из meta keywords"""
        # Ищем в JSON-LD BlogPosting keywords
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BlogPosting':
                            if 'keywords' in item:
                                keywords = item['keywords']
                                # Обычно это строка через запятую
                                if isinstance(keywords, str):
                                    return self.clean_text(keywords)
                                elif isinstance(keywords, list):
                                    return ', '.join([str(k) for k in keywords])
                elif isinstance(data, dict) and data.get('@type') == 'BlogPosting':
                    if 'keywords' in data:
                        keywords = data['keywords']
                        if isinstance(keywords, str):
                            return self.clean_text(keywords)
                        elif isinstance(keywords, list):
                            return ', '.join([str(k) for k in keywords])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из meta keywords
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Главное изображение из og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Изображение из flashy-recipe-image
        recipe_image = self.soup.find('div', class_='flashy-recipe-image')
        if recipe_image:
            img = recipe_image.find('img')
            if img and img.get('src'):
                urls.append(img['src'])
        
        # 3. Изображения из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'ImageObject':
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
    
    # Обрабатываем папку preprocessed/flashycoffee_com
    preprocessed_dir = os.path.join("preprocessed", "flashycoffee_com")
    
    # Проверяем относительно корня репозитория
    repo_root = Path(__file__).parent.parent
    full_path = repo_root / preprocessed_dir
    
    if full_path.exists() and full_path.is_dir():
        process_directory(FlashyCoffeeExtractor, str(full_path))
        return
    
    print(f"Директория не найдена: {full_path}")
    print("Использование: python flashycoffee_com.py")


if __name__ == "__main__":
    main()
