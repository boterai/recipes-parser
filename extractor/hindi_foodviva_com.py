"""
Экстрактор данных рецептов для сайта hindi.foodviva.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class HindiFoodvivaExtractor(BaseRecipeExtractor):
    """Экстрактор для hindi.foodviva.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты с Hindi suffix
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате строки, например "90 मिनट" (Hindi format)
        """
        if not duration or not duration.startswith('PT'):
            return None
        
        duration = duration[2:]  # Убираем "PT"
        
        hours = 0
        minutes = 0
        
        # Извлекаем часы
        hour_match = re.search(r'(\d+)H', duration)
        if hour_match:
            hours = int(hour_match.group(1))
        
        # Извлекаем минуты
        min_match = re.search(r'(\d+)M', duration)
        if min_match:
            minutes = int(min_match.group(1))
        
        # Конвертируем все в минуты
        total_minutes = hours * 60 + minutes
        
        if total_minutes > 0:
            return f"{total_minutes} मिनट"
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в h1 с itemprop="name"
        name_elem = self.soup.find('span', itemprop='name')
        if name_elem:
            name = self.clean_text(name_elem.get_text())
            # Удаляем суффиксы "रेसिपी", "Recipe"
            name = re.sub(r'\s+(रेसिपी|Recipe).*$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        # Альтернативно - из h1.entry-title
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            name = self.clean_text(h1.get_text())
            # Удаляем суффиксы "रेसिपी", "Recipe"
            name = re.sub(r'\s+(रेसिपी|Recipe).*$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        # Или из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            name = self.clean_text(og_title['content'])
            # Удаляем суффиксы "रेसिपी", "Recipe"
            name = re.sub(r'\s+(रेसिपी|Recipe).*$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description или og:description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            # Берем только первое предложение (до первой точки или перевода строки)
            if desc:
                # Ищем первую точку с учетом что после нее может быть пробел
                match = re.search(r'^([^।\.]+[।\.])', desc)
                if match:
                    return self.clean_text(match.group(1))
                return desc
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = self.clean_text(og_desc['content'])
            # Берем только первое предложение
            if desc:
                match = re.search(r'^([^।\.]+[।\.])', desc)
                if match:
                    return self.clean_text(match.group(1))
                return desc
        
        # Ищем в div с id="css_fv_recipe_desc" и itemprop="description"
        desc_elem = self.soup.find('div', id='css_fv_recipe_desc')
        if desc_elem:
            desc = self.clean_text(desc_elem.get_text())
            # Берем только первое предложение
            if desc:
                match = re.search(r'^([^।\.]+[।\.])', desc)
                if match:
                    return self.clean_text(match.group(1))
                return desc
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем таблицу ингредиентов
        ingredient_table = self.soup.find('table', class_='css_fv_recipe_table')
        if not ingredient_table:
            ingredient_table = self.soup.find('div', id='css_fv_recipe_table')
        
        if ingredient_table:
            # Извлекаем все span с itemprop="recipeIngredient"
            ingredient_spans = ingredient_table.find_all('span', itemprop='recipeIngredient')
            
            for span in ingredient_spans:
                # Получаем текст ингредиента
                ingredient_text = self.clean_text(span.get_text())
                
                if ingredient_text:
                    # Парсим в структурированный формат
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка ингредиента
            
        Returns:
            dict: {"name": "...", "amount": "...", "units": "..."} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "3/4 कप रवा", "1 टीस्पून राई", "2 हरी मिर्च"
        # Единицы измерения: поддерживаем Hindi, English и Russian (смешанный контент на сайте)
        units_pattern = r'(?:कप|टीस्पून|टेबलस्पून|ग्राम|किलोग्राम|मिलीलीटर|लीटर|चुटकी|टहनिया|मध्यम|बड़ा|छोटा|इंच|कलियाँ|pieces|шт\.|большой|средний|स्वादानुसार)'
        
        # Паттерн: количество + единица + название
        pattern = r'^([\d\s/.,+-]+)?\s*(' + units_pattern + r')?\s*(.+)'
        
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
            # Убираем пробелы и лишние символы
            amount_str = re.sub(r'\s+', ' ', amount_str).strip()
            amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        name = name.strip() if name else text
        
        # Удаляем фразы "по вкусу", "to taste", etc.
        name = re.sub(r'\b(to taste|по вкусу|स्वादानुसार|as needed|optional)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions = []
        
        # Ищем контейнер с инструкциями
        method_container = self.soup.find('div', id='css_fv_recipe_method')
        
        if method_container:
            # Ищем все li с div.step_desc
            step_items = method_container.find_all('li')
            
            for item in step_items:
                # Ищем div с itemprop="recipeInstructions"
                step_desc = item.find('div', class_='step_desc')
                if step_desc:
                    step_text = self.clean_text(step_desc.get_text())
                    if step_text:
                        instructions.append(step_text)
        
        # Если не нашли через step_desc, попробуем просто текст из li
        if not instructions and method_container:
            step_items = method_container.find_all('li')
            for item in step_items:
                step_text = self.clean_text(item.get_text())
                if step_text:
                    instructions.append(step_text)
        
        if instructions:
            # Объединяем все шаги в одну строку
            return ' '.join(instructions)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в div.entry-categories
        categories_div = self.soup.find('div', class_='entry-categories')
        if categories_div:
            # Извлекаем все ссылки
            links = categories_div.find_all('a')
            if links:
                # Берем первую категорию
                return self.clean_text(links[0].get_text())
        
        # Альтернативно - из meta article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем meta с itemprop="prepTime"
        prep_meta = self.soup.find('meta', itemprop='prepTime')
        if prep_meta and prep_meta.get('content'):
            iso_time = prep_meta['content']
            parsed_time = self.parse_iso_duration(iso_time)
            if parsed_time:
                return parsed_time
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем meta с itemprop="cookTime"
        cook_meta = self.soup.find('meta', itemprop='cookTime')
        if cook_meta and cook_meta.get('content'):
            iso_time = cook_meta['content']
            parsed_time = self.parse_iso_duration(iso_time)
            if parsed_time:
                return parsed_time
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем meta с itemprop="totalTime"
        total_meta = self.soup.find('meta', itemprop='totalTime')
        if total_meta and total_meta.get('content'):
            iso_time = total_meta['content']
            parsed_time = self.parse_iso_duration(iso_time)
            if parsed_time:
                return parsed_time
        
        # Если нет totalTime, пробуем вычислить из prep + cook
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        
        if prep_time and cook_time:
            # Извлекаем числа из строк (поддержка разных форматов)
            prep_match = re.search(r'(\d+)', prep_time)
            cook_match = re.search(r'(\d+)', cook_time)
            
            if prep_match and cook_match:
                total_minutes = int(prep_match.group(1)) + int(cook_match.group(1))
                return f"{total_minutes} मिनट"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с советами
        tips_section = self.soup.find('div', id='css_fv_recipe_tips')
        
        if tips_section:
            # Извлекаем текст из всех li
            tips = []
            li_items = tips_section.find_all('li')
            for li in li_items:
                tip_text = self.clean_text(li.get_text())
                if tip_text:
                    tips.append(tip_text)
            
            if tips:
                return ' '.join(tips)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Извлекаем категории как теги
        categories_div = self.soup.find('div', class_='entry-categories')
        if categories_div:
            links = categories_div.find_all('a')
            for link in links:
                tag = self.clean_text(link.get_text())
                if tag and tag not in tags:
                    tags.append(tag)
        
        # Возвращаем теги через запятую
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем изображение с itemprop="image"
        img_elem = self.soup.find('img', itemprop='image')
        if img_elem:
            # Проверяем data-original (для lazy loading)
            if img_elem.get('data-original'):
                urls.append(img_elem['data-original'])
            elif img_elem.get('src'):
                urls.append(img_elem['src'])
        
        # 2. Ищем в meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 3. Ищем в meta twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
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
    # Обрабатываем папку preprocessed/hindi_foodviva_com
    recipes_dir = os.path.join("preprocessed", "hindi_foodviva_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(HindiFoodvivaExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python hindi_foodviva_com.py")


if __name__ == "__main__":
    main()
