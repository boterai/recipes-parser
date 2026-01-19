"""
Экстрактор данных рецептов для сайта copymethat.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CopyMeThatExtractor(BaseRecipeExtractor):
    """Экстрактор для copymethat.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта с itemprop="name"
        recipe_header = self.soup.find('div', {'itemprop': 'name', 'class': 'recipe_title'})
        if recipe_header:
            return self.clean_text(recipe_header.get_text())
        
        # Альтернативно - из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            return self.clean_text(title_tag.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            return desc if desc else None
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = self.clean_text(og_desc['content'])
            return desc if desc else None
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1/4 cup reduced-sodium soy sauce" или "2 bell peppers"
            
        Returns:
            dict: {"name": "reduced-sodium soy sauce", "amount": "1/4", "units": "cup"} или None
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
        # Примеры: "1/4 cup soy sauce", "2 Tbsp. butter", "1 lb. steak", "2 bell peppers"
        # Важно: единицы должны быть ПОСЛЕ числа, чтобы избежать ложных срабатываний
        # "Sliced" не должно парситься как "Slice" + "d", "garlic" не должно быть "g" + "arlic"
        # Поэтому требуем, чтобы единица была либо после числа, либо была полным словом с границами
        pattern = r'^([\d\s/.,]+)\s+(cups?|tablespoons?|teaspoons?|tbsps?\.?|tsps?\.?|pounds?|ounces?|lbs?\.?|oz\.?|grams?|kilograms?|milliliters?|liters?|cloves?|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|heads?|ml|kg|g|l)\s+(.+)|^([\d\s/.,]+)\s+(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, очищаем название и возвращаем его
            name = text
            # Удаляем описательные фразы в конце
            name = re.sub(r',\s*(to serve|for garnish|as needed|optional|divided|cut into.*|thinly sliced|chopped|minced|diced)$', '', name, flags=re.IGNORECASE)
            # Удаляем скобки с содержимым
            name = re.sub(r'\([^)]*\)', '', name)
            # Удаляем лишние пробелы и запятые
            name = re.sub(r'[,;]+$', '', name)
            name = re.sub(r'\s+', ' ', name).strip()
            
            return {
                "name": name.lower(),
                "amount": None,
                "units": None
            }
        
        # Проверяем, какая группа совпала
        if match.group(1):  # С единицей измерения
            amount_str = match.group(1)
            unit = match.group(2)
            name = match.group(3)
        else:  # Без единицы измерения (только число и название)
            amount_str = match.group(4)
            unit = None
            name = match.group(5)
        
        # Обработка количества
        amount = None
        if amount_str:
            amount = amount_str.strip()
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем описательные фразы в конце
        name = re.sub(r',\s*(to serve|for garnish|as needed|optional|divided|cut into.*|thinly sliced|chopped|minced|diced)$', '', name, flags=re.IGNORECASE)
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name.lower(),
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем все ингредиенты с itemprop="recipeIngredient"
        ingredient_divs = self.soup.find_all('div', {'itemprop': 'recipeIngredient'})
        
        for ing_div in ingredient_divs:
            # Извлекаем текст из span с aria-hidden="true" (основной текст)
            span = ing_div.find('span', {'aria-hidden': 'true'})
            if not span:
                # Если нет, берем из всего div
                span = ing_div
            
            ingredient_text = span.get_text(separator=' ', strip=True)
            ingredient_text = self.clean_text(ingredient_text)
            
            if ingredient_text:
                # Проверяем, содержит ли строка "and" между двумя ингредиентами
                # Например: "Sliced green onion and sesame seeds, for garnish"
                # Паттерн: текст + "and" + текст + ", for garnish/to serve"
                split_pattern = r'^(.+?)\s+and\s+(.+?),?\s*(for garnish|to serve|as needed|optional)?$'
                match = re.match(split_pattern, ingredient_text, re.IGNORECASE)
                
                if match:
                    # Разделяем на два ингредиента
                    first_part = match.group(1).strip()
                    second_part = match.group(2).strip()
                    
                    # Парсим каждый отдельно
                    parsed1 = self.parse_ingredient(first_part)
                    if parsed1:
                        ingredients.append(parsed1)
                    
                    parsed2 = self.parse_ingredient(second_part)
                    if parsed2:
                        ingredients.append(parsed2)
                else:
                    # Парсим как обычно
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        # На copymethat.com инструкции могут быть внешней ссылкой
        # Ищем ссылку на оригинальные инструкции
        directions_link = self.soup.find('div', class_='directions_src_link')
        if directions_link:
            link_text = self.clean_text(directions_link.get_text())
            return link_text if link_text else None
        
        # Если есть шаги на самой странице, ищем их
        steps = []
        steps_container = self.soup.find('div', {'id': 'steps_anchor'})
        if steps_container:
            # Ищем шаги после заголовка
            parent = steps_container.find_parent()
            if parent:
                step_items = parent.find_all('li', class_=re.compile(r'step', re.I))
                for item in step_items:
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    if step_text:
                        steps.append(step_text)
        
        if steps:
            # Добавляем нумерацию если её нет
            if not re.match(r'^\d+\.', steps[0]):
                steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
            return ' '.join(steps)
        
        # Если не нашли ничего, возвращаем текст из directions_src_link
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем элемент со временем подготовки
        prep_time_elem = self.soup.find(class_=re.compile(r'prep.*time', re.I))
        if prep_time_elem:
            time_text = prep_time_elem.get_text(strip=True)
            return self.clean_text(time_text)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем элемент со временем приготовления
        cook_time_elem = self.soup.find(class_=re.compile(r'cook.*time', re.I))
        if cook_time_elem:
            time_text = cook_time_elem.get_text(strip=True)
            return self.clean_text(time_text)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем элемент с общим временем
        total_time_elem = self.soup.find(class_=re.compile(r'total.*time', re.I))
        if total_time_elem:
            time_text = total_time_elem.get_text(strip=True)
            return self.clean_text(time_text)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями
        notes_section = self.soup.find(class_=re.compile(r'notes?|tips?|remarks?', re.I))
        
        if notes_section:
            text = notes_section.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем теги в meta-теге keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Фильтруем и очищаем теги
            tags_list = [tag.strip() for tag in keywords.split() if tag.strip()]
            # Убираем стандартные слова
            stopwords = {'copy', 'me', 'that', 'copymethat', 'meal', 'planner', 'recipe', 
                        'manager', 'clipper', 'shopping', 'list', 'add', 'organize', 'recipes'}
            filtered_tags = [tag for tag in tags_list if tag.lower() not in stopwords]
            
            if filtered_tags:
                return ', '.join(filtered_tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем изображения с itemprop="image"
        itemprop_images = self.soup.find_all('img', {'itemprop': 'image'})
        for img in itemprop_images:
            if img.get('src'):
                urls.append(img['src'])
        
        # 3. Ищем основное изображение рецепта по id
        recipe_img = self.soup.find('img', {'id': 'recipe_image'})
        if recipe_img and recipe_img.get('src'):
            urls.append(recipe_img['src'])
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                # Нормализуем URL
                url = url.strip()
                # Пропускаем placeholder и очень маленькие изображения
                if url and url not in seen and 'placeholder' not in url.lower():
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
    # Обрабатываем папку preprocessed/copymethat_com
    recipes_dir = os.path.join("preprocessed", "copymethat_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(CopyMeThatExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python copymethat_com.py")


if __name__ == "__main__":
    main()
