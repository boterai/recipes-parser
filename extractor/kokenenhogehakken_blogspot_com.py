"""
Экстрактор данных рецептов для сайта kokenenhogehakken.blogspot.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KokenenhogehakkenExtractor(BaseRecipeExtractor):
    """Экстрактор для kokenenhogehakken.blogspot.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке поста
        post_title = self.soup.find('h3', class_='post-title entry-title')
        if post_title:
            return self.clean_text(post_title.get_text())
        
        # Альтернативно - из тега title
        title_tag = self.soup.find('title')
        if title_tag:
            return self.clean_text(title_tag.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в post-body - описание идет до секции "Wat hebben we nodig"
        post_body = self.soup.find('div', class_=lambda x: x and 'post-body' in x and 'entry-content' in x)
        if not post_body:
            return None
        
        # Получаем весь текст из post_body до секции ингредиентов
        # Находим заголовок ингредиентов
        ingredients_header = post_body.find('span', string=re.compile(r'Wat hebben we nodig', re.I))
        
        if not ingredients_header:
            return None
        
        # Получаем весь текст до заголовка
        full_text = post_body.get_text(separator=' ', strip=True)
        
        # Находим позицию начала секции ингредиентов
        ing_marker = 'Wat hebben we nodig'
        ing_pos = full_text.find(ing_marker)
        
        if ing_pos > 0:
            # Берем текст до ингредиентов
            intro_text = full_text[:ing_pos].strip()
        else:
            intro_text = full_text
        
        # Разбиваем на предложения
        sentences = re.split(r'[.!?]\s+', intro_text)
        
        # Ищем предложение с описанием блюда
        dish_name = self.extract_dish_name()
        description = None
        
        for sentence in sentences:
            sentence = sentence.strip()
            # Ищем предложение которое содержит ключевые слова описания
            if (dish_name and dish_name.lower() in sentence.lower()) or \
               sentence.lower().startswith('deze ') or \
               'introductie' in sentence.lower():
                # Находим первое подходящее предложение
                if len(sentence) > 30:  # Достаточно длинное для описания
                    description = sentence
                    break
        
        # Если не нашли специфическое описание, возвращаем None
        if description:
            # Добавляем точку в конец если её нет
            if not description.endswith(('.', '!', '?')):
                description += '.'
            return self.clean_text(description)
        
        return None
    
    def parse_ingredient_item(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "400 ml water" или "1 sjalotje, gepeld"
            
        Returns:
            dict: {"name": "water", "amount": "400", "unit": "ml"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "400 ml water", "20 gr boter", "1 sjalotje"
        pattern = r'^([\d\s/.,]+)?\s*(ml|gr|g|kg|l|stuk|stuks|el|tl|theelepel|eetlepel|snufje)?\.?\s*(.+)'
        
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
                amount = int(total) if total == int(total) else total
            else:
                amount_str = amount_str.replace(',', '.')
                try:
                    amount_val = float(amount_str)
                    amount = int(amount_val) if amount_val == int(amount_val) else amount_val
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения
        units = unit.strip() if unit else None
        
        # Очистка названия - удаляем описания в скобках и после запятой
        # Например: "1 sjalotje, gepeld en fijngesnipperd" -> "sjalotje"
        if ',' in name:
            name = name.split(',')[0]
        
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем секцию с ингредиентами
        post_body = self.soup.find('div', class_=lambda x: x and 'post-body' in x and 'entry-content' in x)
        if not post_body:
            return None
        
        # Находим заголовок "Wat hebben we nodig:"
        ingredients_header = post_body.find('span', string=re.compile(r'Wat hebben we nodig', re.I))
        
        if ingredients_header:
            # Ищем следующий <ul> после заголовка
            ul_element = ingredients_header.find_next('ul')
            
            if ul_element:
                # Извлекаем элементы списка
                items = ul_element.find_all('li')
                
                for item in items:
                    ingredient_text = item.get_text(strip=True)
                    ingredient_text = self.clean_text(ingredient_text)
                    
                    if ingredient_text:
                        # Парсим в структурированный формат
                        parsed = self.parse_ingredient_item(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions = []
        
        # Ищем секцию с инструкциями
        post_body = self.soup.find('div', class_=lambda x: x and 'post-body' in x and 'entry-content' in x)
        if not post_body:
            return None
        
        # Находим заголовок "Hoe gaan we te werk:"
        instructions_header = post_body.find('span', string=re.compile(r'Hoe gaan we te werk', re.I))
        
        if instructions_header:
            # Ищем следующий <ul> после заголовка
            ul_element = instructions_header.find_next('ul')
            
            if ul_element:
                # Извлекаем элементы списка
                items = ul_element.find_all('li')
                
                for item in items:
                    instruction_text = item.get_text(separator=' ', strip=True)
                    instruction_text = self.clean_text(instruction_text)
                    
                    if instruction_text:
                        instructions.append(instruction_text)
        
        return ' '.join(instructions) if instructions else None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с советами
        post_body = self.soup.find('div', class_=lambda x: x and 'post-body' in x and 'entry-content' in x)
        if not post_body:
            return None
        
        # Находим заголовок "TIP:"
        tip_header = post_body.find('b', string=re.compile(r'TIP', re.I))
        
        if tip_header:
            # Собираем текст после заголовка до конца секции
            notes_parts = []
            
            # Идем по следующим элементам после <b>TIP:</b>
            current = tip_header.next_sibling
            
            while current:
                # Останавливаемся на конце div
                if hasattr(current, 'name') and current.name == 'div':
                    break
                
                # Извлекаем текст
                if isinstance(current, str):
                    text = current.strip()
                    if text and text not in ['<br>', '<br/>', '<br />']:
                        notes_parts.append(text)
                elif hasattr(current, 'get_text'):
                    if current.name == 'br':
                        # Пропускаем br теги
                        pass
                    else:
                        text = current.get_text(strip=True)
                        if text:
                            notes_parts.append(text)
                
                current = current.next_sibling
            
            if notes_parts:
                # Объединяем части заметок
                notes = ' '.join(notes_parts)
                return self.clean_text(notes)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем image в данных
                if isinstance(data, dict) and 'image' in data:
                    img = data['image']
                    if isinstance(img, dict) and 'url' in img:
                        urls.append(img['url'])
                    elif isinstance(img, str):
                        urls.append(img)
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 2. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 3. Ищем изображения в post-body
        post_body = self.soup.find('div', class_=lambda x: x and 'post-body' in x and 'entry-content' in x)
        if post_body:
            # Ищем изображения в таблице с классом tr-caption-container
            img_tables = post_body.find_all('table', class_='tr-caption-container')
            for table in img_tables:
                img = table.find('img')
                if img and img.get('src'):
                    src = img['src']
                    # Пытаемся получить URL большого изображения из ссылки
                    link = table.find('a', href=True)
                    if link:
                        href = link['href']
                        if 's1600' in href:  # Это полноразмерное изображение
                            urls.append(href)
                        elif src not in urls:
                            urls.append(src)
                    elif src not in urls:
                        urls.append(src)
            
            # Также ищем все img теги
            images = post_body.find_all('img')
            for img in images:
                if img.get('src'):
                    src = img['src']
                    if src not in urls:
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
        instructions = self.extract_instructions()
        notes = self.extract_notes()
        image_urls = self.extract_image_urls()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": None,  # Не присутствует на этом сайте
            "prep_time": None,  # Не присутствует на этом сайте
            "cook_time": None,  # Не присутствует на этом сайте
            "total_time": None,  # Не присутствует на этом сайте
            "notes": notes,
            "tags": None,  # Не присутствует на этом сайте
            "image_urls": image_urls
        }


def main():
    import os
    # Обрабатываем папку preprocessed/kokenenhogehakken_blogspot_com
    preprocessed_dir = os.path.join("preprocessed", "kokenenhogehakken_blogspot_com")
    
    # Также проверяем абсолютный путь
    if not os.path.exists(preprocessed_dir):
        preprocessed_dir = os.path.join(
            "/home/runner/work/recipes-parser/recipes-parser",
            "preprocessed",
            "kokenenhogehakken_blogspot_com"
        )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(KokenenhogehakkenExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python kokenenhogehakken_blogspot_com.py")


if __name__ == "__main__":
    main()
