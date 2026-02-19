"""
Экстрактор данных рецептов для сайта mcooker-nlm.tomathouse.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class McookerNlmExtractor(BaseRecipeExtractor):
    """Экстрактор для mcooker-nlm.tomathouse.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта h2.fn внутри div.recipehp
        recipe_header = self.soup.find('h2', class_='fn')
        if recipe_header:
            return self.clean_text(recipe_header.get_text())
        
        # Альтернативно - из title
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем суффиксы типа " - recept met foto op Mcooker: beste recepten"
            title = re.sub(r'\s*-\s*recept.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из itemprop="description"
        itemprop_desc = self.soup.find('meta', itemprop='description')
        if itemprop_desc and itemprop_desc.get('content'):
            return self.clean_text(itemprop_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем таблицу с ингредиентами
        ingredients_table = self.soup.find('table', class_='ingredients')
        if not ingredients_table:
            return None
        
        # Извлекаем все строки с itemprop="recipeIngredient"
        ingredient_rows = ingredients_table.find_all('tr', itemprop='recipeIngredient')
        
        for row in ingredient_rows:
            # Ищем название и количество в td элементах
            name_cell = row.find('td', class_='name')
            amount_cell = row.find('td', class_='amount')
            
            if not name_cell:
                continue
            
            name = self.clean_text(name_cell.get_text())
            amount_text = self.clean_text(amount_cell.get_text()) if amount_cell else None
            
            if not name:
                continue
            
            # Пропускаем заголовки секций (они в italic) и разделители
            if name_cell.find('i') or all(c in '- ' for c in name):
                continue
            
            # Парсим количество и единицы из amount_text
            amount = None
            unit = None
            
            if amount_text:
                # Паттерн для извлечения числа и единицы измерения
                # Примеры: "500 g", "250 ml", "1 theelepel", "300-400 g", "smaak"
                match = re.match(r'([\d\-\.]+)\s*(.+)', amount_text)
                if match:
                    amount_str, unit_str = match.groups()
                    # Пытаемся преобразовать в число, если это одно число
                    if '-' not in amount_str and '.' not in amount_str:
                        try:
                            amount = int(amount_str)
                        except ValueError:
                            amount = amount_str.strip()
                    else:
                        # Для диапазонов (300-400) или дробей оставляем как строку
                        # но для одного числа с точкой - пытаемся сделать float
                        if '-' not in amount_str:
                            try:
                                amount = float(amount_str)
                                # Если это целое число, конвертируем в int
                                if amount.is_integer():
                                    amount = int(amount)
                            except ValueError:
                                amount = amount_str.strip()
                        else:
                            # Для диапазонов берем первое значение как int
                            try:
                                first_num = amount_str.split('-')[0].strip()
                                amount = int(first_num)
                            except ValueError:
                                amount = amount_str.strip()
                    unit = unit_str.strip()
                elif amount_text.lower() in ['smaak', 'naar smaak']:
                    # Если просто "по вкусу", записываем как unit
                    unit = 'naar smaak'
                else:
                    # Если не удалось распарсить, записываем все в unit
                    unit = amount_text
            
            ingredients.append({
                "name": name,
                "units": unit,
                "amount": amount
            })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        instructions = []
        
        # Ищем контейнер инструкций с itemprop="recipeInstructions"
        # Может быть <ul> или <div>
        instructions_container = self.soup.find(itemprop='recipeInstructions')
        if not instructions_container:
            return None
        
        # Проверяем структуру: <ul> с <li> или <div> с nested divs
        if instructions_container.name == 'ul':
            # Извлекаем все элементы li с классом instruction
            instruction_items = instructions_container.find_all('li', class_='instruction')
        else:
            # Для div контейнера, ищем div.instruction или div.step
            instruction_items = instructions_container.find_all('div', class_='instruction')
            if not instruction_items:
                # Альтернативно ищем div.step
                instruction_items = instructions_container.find_all('div', class_='step')
        
        for item in instruction_items:
            # Извлекаем текст, игнорируя изображения
            # Создаем копию для безопасного изменения
            from copy import copy
            item_copy = copy(item)
            
            # Удаляем все img и a теги с изображениями
            for img in item_copy.find_all('img'):
                img.decompose()
            for link in item_copy.find_all('a'):
                if link.find('img') or 'photo' in link.get('class', []):
                    link.decompose()
            
            # Удаляем div с дополнительным текстом (например "Koken is niet moeilijk...")
            for div in item_copy.find_all('div', style=lambda x: x and 'text-align:center' in x):
                div.decompose()
            
            instruction_text = self.clean_text(item_copy.get_text())
            
            if instruction_text:
                instructions.append(instruction_text)
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в span с itemprop="recipeCategory"
        category_span = self.soup.find('span', itemprop='recipeCategory')
        if category_span:
            return self.clean_text(category_span.get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На этом сайте prep_time указан в div.coo с текстом "Tijd voor voorbereiding:"
        coo_divs = self.soup.find_all('div', class_='coo')
        for div in coo_divs:
            h3 = div.find('h3')
            if h3 and 'voorbereiding' in h3.get_text().lower():
                # Ищем span с временем
                time_span = div.find('span', itemprop='cookTime')
                if time_span:
                    return self.clean_text(time_span.get_text())
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Извлекаем из notes или описания если упоминается время готовки
        # Например "30-40 minuten in de oven"
        instructions = self.extract_instructions()
        if instructions:
            # Ищем паттерны типа "30-40 minuten", "45 minutes"
            match = re.search(r'(\d+(?:-\d+)?)\s*(?:minuten|minutes)', instructions)
            if match:
                return f"{match.group(1)} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени приготовления"""
        # Складываем prep_time и cook_time если есть
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        
        if prep_time and cook_time:
            return f"{prep_time} {cook_time}"
        elif prep_time:
            return prep_time
        elif cook_time:
            return cook_time
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем в div.prim с заголовком "Opmerking"
        prim_div = self.soup.find('div', class_='prim')
        if prim_div:
            # Ищем div.post1 внутри prim
            post_div = prim_div.find('div', class_='post1')
            if post_div:
                # Извлекаем текст, заменяя <br> на пробелы
                text = post_div.get_text(separator=' ', strip=True)
                return self.clean_text(text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', itemprop='keywords')
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Фильтруем общие слова
            stopwords = {
                'recept', 'foto', 'stap voor stap', 'klassiek', 'huisgemaakt',
                'heerlijk', 'eenvoudig', 'rijzen', 'uitrollen', 'maximaal', 
                'dun', 'invetten', 'gesmolten', 'margarine', 'groente', 
                'vouwen', 'make', 'ingredients', 'video'
            }
            
            tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            # Фильтруем
            filtered_tags = []
            for tag in tags_list:
                tag_lower = tag.lower()
                if tag_lower not in stopwords and len(tag) >= 3:
                    # Берем только первые несколько осмысленных тегов
                    if not any(sw in tag_lower for sw in stopwords):
                        filtered_tags.append(tag)
            
            if filtered_tags:
                return ', '.join(filtered_tags[:10])  # Ограничиваем до 10 тегов
        
        # Альтернативно - берем cuisine type
        cuisine = self.soup.find('span', itemprop='recipeCuisine')
        if cuisine:
            cuisine_text = self.clean_text(cuisine.get_text())
            if cuisine_text:
                return cuisine_text
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Главное изображение - result-photo
        main_photo = self.soup.find('img', class_='result-photo')
        if main_photo and main_photo.get('src'):
            urls.append(main_photo['src'])
        
        # 2. Изображения из инструкций
        instructions_list = self.soup.find('ul', itemprop='recipeInstructions')
        if instructions_list:
            # Ищем все изображения в инструкциях
            for img in instructions_list.find_all('img', class_='photo'):
                src = img.get('src')
                if src and src not in urls:
                    urls.append(src)
        
        # Убираем дубликаты и возвращаем
        if urls:
            return ','.join(urls)
        
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
    # Обрабатываем папку preprocessed/mcooker-nlm_tomathouse_com
    preprocessed_dir = os.path.join("preprocessed", "mcooker-nlm_tomathouse_com")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(McookerNlmExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python mcooker-nlm_tomathouse_com.py")


if __name__ == "__main__":
    main()
