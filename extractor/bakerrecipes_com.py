"""
Экстрактор данных рецептов для сайта bakerrecipes.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class BakerRecipesExtractor(BaseRecipeExtractor):
    """Экстрактор для bakerrecipes.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            name = self.clean_text(h1.get_text())
            # Убираем суффикс "Recipe" если есть
            name = re.sub(r'\s+Recipe\s*$', '', name, flags=re.IGNORECASE)
            return name
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            name = og_title['content']
            name = re.sub(r'\s+Recipe\s*$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем первый параграф в entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            # Находим первый параграф
            first_p = entry_content.find('p')
            if first_p:
                return self.clean_text(first_p.get_text())
        
        # Альтернатива - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате списка словарей"""
        ingredients = []
        
        # Ищем секцию с ингредиентами
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем все font теги
        font_tags = entry_content.find_all('font')
        
        # Ингредиенты обычно в font теге с size="2" который содержит единицы измерения
        # и находится ПОСЛЕ заголовка "Ingredients & Directions"
        ingredients_font = None
        found_header = False
        
        for font in font_tags:
            text = font.get_text()
            
            # Пропускаем заголовок "Ingredients & Directions"
            if 'Ingredients' in text and 'Directions' in text:
                found_header = True
                continue
            
            # После заголовка ищем font с ингредиентами
            if found_header and font.get('size') == '2':
                # Проверяем, что это font с ингредиентами (содержит характерные сокращения)
                if any(unit in text for unit in ['tb', 'ts', 'c ', ' c', 'oz', 'lb']):
                    ingredients_font = font
                    break
        
        if not ingredients_font:
            return None
        
        # Извлекаем текст с \n в качестве разделителя для <br> тегов
        ingredients_text = ingredients_font.get_text(separator='\n', strip=True)
        
        # Разбиваем по строкам
        lines = ingredients_text.split('\n')
        
        # Собираем многострочные ингредиенты
        # Если строка начинается с числа - это новый ингредиент
        # Иначе - продолжение предыдущего
        processed_lines = []
        current_line = ""
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Проверяем, начинается ли строка с числа (или дроби)
            if re.match(r'^\d+(?:/\d+)?\s+', line):
                # Это новый ингредиент
                if current_line:
                    processed_lines.append(current_line)
                current_line = line
            else:
                # Продолжение предыдущего ингредиента
                if current_line:
                    current_line += ' ' + line
                else:
                    # Строка без числа в начале - возможно, это часть названия
                    current_line = line
        
        # Добавляем последний ингредиент
        if current_line:
            processed_lines.append(current_line)
        
        # Парсим каждый ингредиент
        for line in processed_lines:
            if len(line) < 3:
                continue
            
            parsed = self.parse_ingredient(line)
            if parsed:
                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 tb Plain gelatin" или "1/4 ts Salt"
            
        Returns:
            dict: {"name": "Plain gelatin", "amount": "1", "units": "tb"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на обычные дроби
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5'
        }
        
        for fraction, replacement in fraction_map.items():
            text = text.replace(fraction, replacement)
        
        # Паттерн для извлечения количества, единицы и названия
        # Формат: "количество единица название"
        # Примеры: "1 tb Plain gelatin", "1/4 ts Salt", "4 Eggs,separated"
        pattern = r'^([\d\s/]+)?\s*(tb|ts|c|oz|lb|g|kg|ml|l|cup|cups|tablespoon|tablespoons|teaspoon|teaspoons|pound|pounds|ounce|ounces|gram|grams|liter|liters|″|inch|inches|clove|cloves|can|cans)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества - оставляем как строку (с дробями)
        amount = None
        if amount_str:
            amount = amount_str.strip()
        
        # Обработка единицы измерения
        units = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем запятые и все что после них в некоторых случаях
        # Но сохраняем важные части (например, "Eggs,separated" -> "Eggs, separated")
        name = name.strip()
        # Заменяем запятые без пробелов на запятые с пробелами
        name = re.sub(r',(?!\s)', ', ', name)
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Ищем секцию с инструкциями
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем все font теги
        font_tags = entry_content.find_all('font')
        
        # Инструкции обычно во втором font теге (после ингредиентов)
        # Ищем font тег с size="2", который содержит длинный текст с глаголами
        instructions_font = None
        found_ingredients = False
        
        for font in font_tags:
            text = font.get_text()
            
            # Пропускаем заголовки
            if 'Ingredients' in text and 'Directions' in text:
                continue
            
            # Отмечаем, что нашли ингредиенты (по характерным единицам измерения)
            if not found_ingredients and font.get('size') == '2':
                if 'Plain gelatin' in text or ('tb' in text and 'ts' in text):
                    found_ingredients = True
                    continue
            
            # После ингредиентов ищем инструкции
            if found_ingredients and font.get('size') == '2':
                # Проверяем, что это инструкции (содержит глаголы действия и достаточно длинный текст)
                if len(text) > 100 and any(verb in text for verb in ['Mix', 'Beat', 'Add', 'Stir', 'Cook', 'Pour', 'Bake', 'Fold', 'Remove', 'Chill']):
                    instructions_font = font
                    break
        
        if not instructions_font:
            return None
        
        # Извлекаем текст с пробелами между элементами (чтобы <br> стали пробелами)
        instructions_text = instructions_font.get_text(separator=' ', strip=True)
        
        # Очищаем текст
        cleaned = self.clean_text(instructions_text)
        # Добавляем пробел после точки перед заглавной буквой
        cleaned = re.sub(r'\.([A-Z])', r'. \1', cleaned)
        # Добавляем пробел после запятой перед словом (если его нет)
        cleaned = re.sub(r',([a-z])', r', \1', cleaned)
        # Добавляем пробел после точки с запятой перед словом (если его нет)
        cleaned = re.sub(r';([a-z])', r'; \1', cleaned)
        # Удаляем лишние пробелы
        cleaned = re.sub(r'\s+', ' ', cleaned)
        
        return cleaned if cleaned else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в cat-links div
        cat_links = self.soup.find('div', class_='cat-links')
        if cat_links:
            link = cat_links.find('a', rel='category tag')
            if link:
                return self.clean_text(link.get_text())
        
        # Альтернатива - из JSON-LD Article schema
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Article':
                    if 'articleSection' in data:
                        section = data['articleSection']
                        if isinstance(section, list) and section:
                            return section[0]
                        elif isinstance(section, str):
                            return section
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Ищем в tagcloud div
        tagcloud = self.soup.find('div', class_='tagcloud')
        if tagcloud:
            tag_links = tagcloud.find_all('a', rel='tag')
            for link in tag_links:
                tag = self.clean_text(link.get_text())
                if tag and len(tag) >= 3:
                    tags_list.append(tag.lower())
        
        # Альтернатива - из JSON-LD Article schema
        if not tags_list:
            json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
            for script in json_ld_scripts:
                try:
                    if not script.string:
                        continue
                    data = json.loads(script.string)
                    
                    if isinstance(data, dict) and data.get('@type') == 'Article':
                        if 'keywords' in data:
                            keywords = data['keywords']
                            if isinstance(keywords, list):
                                tags_list.extend([kw.lower() for kw in keywords if len(kw) >= 3])
                            elif isinstance(keywords, str):
                                # Может быть строка с разделителями
                                tags_list.extend([kw.strip().lower() for kw in keywords.split(',') if len(kw.strip()) >= 3])
                except (json.JSONDecodeError, KeyError):
                    continue
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags_list:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        # Возвращаем как строку через запятую с пробелом
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем изображение с классом wp-post-image
        img = self.soup.find('img', class_='wp-post-image')
        if img and img.get('src'):
            urls.append(img['src'])
        
        # Дополнительно ищем в meta тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # Ищем в JSON-LD Article schema
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Article':
                    if 'image' in data:
                        img_data = data['image']
                        if isinstance(img_data, str):
                            urls.append(img_data)
                        elif isinstance(img_data, dict) and 'url' in img_data:
                            urls.append(img_data['url'])
                        elif isinstance(img_data, list):
                            for item in img_data:
                                if isinstance(item, str):
                                    urls.append(item)
                                elif isinstance(item, dict) and 'url' in item:
                                    urls.append(item['url'])
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
            "prep_time": None,  # Не доступно на bakerrecipes.com
            "cook_time": None,  # Не доступно на bakerrecipes.com
            "total_time": None,  # Не доступно на bakerrecipes.com
            "notes": None,  # Не доступно на bakerrecipes.com
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "bakerrecipes_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(BakerRecipesExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python bakerrecipes_com.py")


if __name__ == "__main__":
    main()
