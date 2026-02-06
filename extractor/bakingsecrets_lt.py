"""
Экстрактор данных рецептов для сайта bakingsecrets.lt
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class BakingSecretsExtractor(BaseRecipeExtractor):
    """Экстрактор для bakingsecrets.lt"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в элементе с id="zlrecipe-title" и itemprop="name"
        # На сайте обычно два заголовка: литовский и английский
        recipe_titles = self.soup.find_all(id='zlrecipe-title')
        
        if recipe_titles:
            titles = []
            for title_elem in recipe_titles:
                # Извлекаем span с большим шрифтом
                span = title_elem.find('span', style=re.compile(r'font-size:\s*x-large', re.I))
                if span:
                    title_text = self.clean_text(span.get_text())
                    if title_text and title_text not in titles:
                        titles.append(title_text)
            
            if titles:
                # Объединяем литовский и английский заголовки через " | "
                return ' | '.join(titles)
        
        # Альтернативно - из заголовка title
        title = self.soup.find('title')
        if title:
            title_text = title.get_text()
            # Убираем "Baking Secrets:" префикс
            title_text = re.sub(r'^Baking Secrets:\s*', '', title_text, flags=re.IGNORECASE)
            return self.clean_text(title_text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем текстовые параграфы в post-body перед ингредиентами
        post_body = self.soup.find(class_='post-body')
        if not post_body:
            return None
        
        # Первая часть описания часто в courier new font  
        first_part = None
        second_part = None
        
        # Ищем span элементы
        spans = post_body.find_all('span', style=re.compile(r'font-family', re.I))
        
        for span in spans:
            text = self.clean_text(span.get_text())
            
            # Пропускаем пустые
            if not text or len(text) < 15:
                continue
            
            # Останавливаемся на секции ингредиентов
            if 'Ingredientai' in text or 'Ingredients' in text:
                break
            
            # Пропускаем заголовки, инструкции и системный текст
            if (text.endswith(':') or 
                'Gaminimo eiga' in text or
                'Patarimai' in text or
                'pastebėjimai' in text or
                'Sudėtingumas' in text or
                'Mano recepto' in text or
                re.match(r'^\d+\s*(g|ml|šaukšt)', text)):
                continue
            
            # Ищем короткое вводное описание (обычно в courier new)
            if not first_part and len(text) < 100 and text.endswith('.'):
                first_part = text
                continue
            
            # Ищем более длинное описание с качествами блюда
            if first_part and not second_part:
                # Извлекаем фрагмент с описанием качеств
                # Обычно содержит прилагательные: skanūs, skalsūs и т.д.
                sentences = re.split(r'[.!]\s+', text)
                for sent in sentences:
                    if ('skan' in sent.lower() or 'skal' in sent.lower() or 
                        'rupesn' in sent.lower() or 'tekstūr' in sent.lower()):
                        second_part = sent + '.'
                        break
                
                if second_part:
                    break
        
        # Объединяем части описания
        if first_part and second_part:
            return f"{first_part} {second_part}"
        elif first_part:
            return first_part
        elif second_part:
            return second_part
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем секцию с ингредиентами (после "Ingredientai")
        post_body = self.soup.find(class_='post-body')
        if not post_body:
            return None
        
        # Найдем все span элементы, которые содержат ингредиенты
        # Ингредиенты находятся между "Ingredientai" и "Gaminimo eiga"
        all_spans = post_body.find_all('span', style=re.compile(r'font-family.*georgia', re.I))
        
        in_ingredients_section = False
        for span in all_spans:
            text = self.clean_text(span.get_text())
            
            # Начало секции ингредиентов
            if text == 'Ingredientai' or 'Ingredients' in text:
                in_ingredients_section = True
                continue
            
            # Конец секции ингредиентов
            if in_ingredients_section and ('Gaminimo eiga' in text or 'Instructions' in text):
                break
            
            # Извлекаем ингредиенты
            if in_ingredients_section and text and len(text) > 2:
                # Пропускаем пустые строки и заголовки
                if text.endswith(':') or len(text) < 3:
                    continue
                
                # Парсим ингредиент
                parsed = self.parse_ingredient_lt(text)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient_lt(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг литовского ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "65 g miltų" или "1 šaukštas cukraus"
            
        Returns:
            dict: {"name": "miltų", "amount": 65, "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "65 g miltų", "1 šaukštas cukraus", "1/2 šaukštelio sodos"
        # Учитываем разные формы: šaukštas/šaukštelis (именительный), šaukšto/šaukštelio (родительный)
        pattern = r'^([\d\s/.,]+)?\s*(g|ml|kg|l|šaukštas|šaukštai|šaukštų|šaukšto|šaukštelis|šaukšteliai|šaukštelių|šaukštelio|stiklinė|stiklinės|puodelis|puodeliai|puodelių)?\s*(.+)'
        
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
            # Обработка дробей типа "1/2"
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
                # Конвертируем в число (int или float)
                amount_cleaned = amount_str.replace(',', '.')
                try:
                    # Пробуем int, если не получится - float
                    if '.' in amount_cleaned:
                        amount = float(amount_cleaned)
                    else:
                        amount = int(amount_cleaned)
                except ValueError:
                    amount = None
        
        # Нормализация единицы измерения (переводим в именительный падеж)
        unit_normalized = None
        if unit:
            unit_lower = unit.lower()
            if unit_lower in ['šaukštelio', 'šaukšteliai', 'šaukštelių']:
                unit_normalized = 'šaukštelis'
            elif unit_lower in ['šaukštas', 'šaukšto']:
                unit_normalized = 'šaukštas'
            elif unit_lower in ['šaukštai', 'šaukštų']:
                unit_normalized = 'šaukštai'
            else:
                unit_normalized = unit
        
        # Очистка названия
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit_normalized
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем секцию с инструкциями (ordered list после "Gaminimo eiga")
        post_body = self.soup.find(class_='post-body')
        if not post_body:
            return None
        
        # Найдем ordered list с инструкциями (литовские инструкции идут первыми)
        ordered_lists = post_body.find_all('ol')
        
        # Берем первый список (литовские инструкции)
        if ordered_lists:
            ol = ordered_lists[0]
            step_items = ol.find_all('li')
            
            for item in step_items:
                # Извлекаем текст инструкции
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в post-labels (теги) - ищем категорию типа Breakfast, Dessert и т.д.
        post_labels = self.soup.find(class_='post-labels')
        if post_labels:
            # Берем все метки
            labels = post_labels.find_all('a', rel='tag')
            for label in labels:
                tag_text = self.clean_text(label.get_text())
                # Ищем категорию на английском (Breakfast, Dessert, etc.)
                if tag_text in ['Breakfast', 'Dessert', 'Main Course', 'Appetizer', 'Salad', 'Soup', 'Snack']:
                    return tag_text
            
            # Если не нашли стандартную категорию, берем первую метку
            if labels:
                return self.clean_text(labels[0].get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Не представлено на сайте bakingsecrets.lt
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Не представлено на сайте bakingsecrets.lt
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Не представлено на сайте bakingsecrets.lt
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с "Patarimai, pastebėjimai"
        post_body = self.soup.find(class_='post-body')
        if not post_body:
            return None
        
        # Ищем span с текстом "Patarimai, pastebėjimai" (курсив)
        all_spans = post_body.find_all('span')
        
        found_patarimai = False
        notes_parts = []
        
        for span in all_spans:
            text = self.clean_text(span.get_text())
            
            # Начало секции заметок
            if not found_patarimai and 'Patarimai' in text and 'pastebėjimai' in text:
                found_patarimai = True
                continue
            
            # Собираем заметки после заголовка
            if found_patarimai:
                # Останавливаемся на следующей секции
                if ('Sudėtingumas' in text or 
                    'Mano recepto' in text or
                    'skonio vertinimas' in text):
                    break
                
                # Проверяем, что это span с контентом (не пустой)
                if text and len(text) > 10:
                    # Пропускаем только явно описательные части (не советы по приготовлению)
                    if not ('Kuku' in text or 'blynukai. Šįkart' in text or 
                           'medučiu man patiko' in text or
                           'skanūs, skalsūs' in text):
                        # Проверяем стиль - должен быть georgia font (не italic)
                        style = span.get('style', '')
                        if 'georgia' in style.lower() and 'italic' not in style.lower():
                            notes_parts.append(text)
        
        if notes_parts:
            # Объединяем и очищаем
            result = ' '.join(notes_parts)
            # Убираем повторяющиеся части если есть
            result = self.clean_text(result)
            return result
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Ищем в post-labels
        post_labels = self.soup.find(class_='post-labels')
        if post_labels:
            labels = post_labels.find_all('a', rel='tag')
            for label in labels:
                tag = self.clean_text(label.get_text())
                if tag and tag not in tags_list:
                    tags_list.append(tag)
        
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем изображения в post-body
        post_body = self.soup.find(class_='post-body')
        if post_body:
            # Ищем все изображения
            images = post_body.find_all('img')
            for img in images:
                src = img.get('src')
                if src and 'blogger.googleusercontent.com' in src:
                    # Берем оригинальный URL (без размеров)
                    # Удаляем размеры типа /s640-rw/ или /s1600/
                    src = re.sub(r'/s\d+-\w+/', '/s1600/', src)
                    if src not in urls:
                        urls.append(src)
        
        return ','.join(urls) if urls else None
    
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
    # Обрабатываем папку preprocessed/bakingsecrets_lt
    recipes_dir = os.path.join("preprocessed", "bakingsecrets_lt")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(BakingSecretsExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python bakingsecrets_lt.py [путь_к_файлу_или_директории]")


if __name__ == "__main__":
    main()
