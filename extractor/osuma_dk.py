"""
Экстрактор данных рецептов для сайта osuma.dk
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class OsumaDkExtractor(BaseRecipeExtractor):
    """Экстрактор для osuma.dk"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке
        title = self.soup.find('h1', class_='recipe-title')
        if not title:
            title = self.soup.find('h1')
        if title:
            return self.clean_text(title.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title_text = og_title['content']
            # Убираем суффиксы типа " opskrift", " - Osuma"
            title_text = re.sub(r'\s+(opskrift|osuma).*$', '', title_text, flags=re.IGNORECASE)
            return self.clean_text(title_text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
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
            ingredient_text: Строка вида "1,5 liter hønsebouillon" или "400 g ramen-nudler"
            
        Returns:
            dict: {"name": "hønsebouillon", "amount": 1.5, "unit": "liter"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия (Danish units)
        # Danish uses comma for decimals
        pattern = r'^([\d,]+)?\s*(liter|litre|ml|dl|cl|g|kg|mg|spsk|tsk|fed|stk|stykke|pund|lb|oz|cups?|tablespoons?|teaspoons?|tbsp|tsp)?\s+(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            # Удаляем префиксы типа "Evt.", "Lidt"
            name = re.sub(r'^(evt\.|lidt)\s+', '', text, flags=re.IGNORECASE).strip()
            # Удаляем содержимое скобок
            name = re.sub(r'\([^)]*\)', '', name).strip()
            # Убираем описания после запятой, но не "eller" (it's part of ingredient name like "chiliolie eller sambal oelek")
            name = name.split(',')[0].strip()
            # Remove suffixes like "efter smag", "i strimler", "til stegning"
            name = re.sub(r'\s+(efter smag|i strimler|til stegning)$', '', name, flags=re.IGNORECASE).strip()
            
            return {
                "name": name,
                "amount": None,
                "unit": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества (Danish uses comma for decimals)
        amount = None
        if amount_str:
            # Replace comma with dot and convert to number
            try:
                amount = float(amount_str.replace(',', '.'))
                # If it's a whole number, convert to int
                if amount == int(amount):
                    amount = int(amount)
            except ValueError:
                amount = None
        
        # Обработка единицы измерения
        unit = unit if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name).strip()
        # Удаляем описания после запятой
        name = name.split(',')[0].strip()
        # Remove suffixes like "til stegning"
        name = re.sub(r'\s+til stegning$', '', name, flags=re.IGNORECASE).strip()
        # But keep "eller" in name for ingredients like "babyspinat eller pak choi"
        # Only remove "eller X" if it's at the end and seems like an alternative description
        # Keep it as-is for now to match reference better
        
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
        
        # Ищем ингредиенты через microdata атрибут itemprop="recipeIngredient"
        ingredient_items = self.soup.find_all(attrs={'itemprop': 'recipeIngredient'})
        
        for item in ingredient_items:
            ingredient_text = item.get_text(separator=' ', strip=True)
            ingredient_text = self.clean_text(ingredient_text)
            
            # Парсим в структурированный формат
            parsed = self.parse_ingredient(ingredient_text)
            if parsed:
                # Convert to format matching the expected JSON: "units" instead of "unit"
                ingredients.append({
                    "name": parsed["name"],
                    "units": parsed["unit"],
                    "amount": parsed["amount"]
                })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем шаги через microdata атрибут itemprop="recipeInstructions"
        instruction_items = self.soup.find_all(attrs={'itemprop': 'recipeInstructions'})
        
        for idx, item in enumerate(instruction_items, 1):
            step_text = item.get_text(separator=' ', strip=True)
            step_text = self.clean_text(step_text)
            
            if step_text:
                # Добавляем нумерацию
                steps.append(f"{idx}. {step_text}")
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Mapping of Danish categories to English
        category_mapping = {
            'aftensmad': 'Main Course',
            'forret': 'Appetizer', 
            'dessert': 'Dessert',
            'morgenmad': 'Breakfast',
            'frokost': 'Lunch',
            'snack': 'Snack',
            'bagværk': 'Baking',
            'drikkevarer': 'Drinks',
            'opskrifter': None  # Generic "recipes" - skip
        }
        
        # Ищем категории через rel="category tag"
        categories = self.soup.find_all('a', rel='category tag')
        if categories:
            for cat in categories:
                cat_text = self.clean_text(cat.get_text()).lower()
                # Try to map to English
                mapped = category_mapping.get(cat_text)
                if mapped:  # Skip None values
                    return mapped
                # If no mapping, return as-is (capitalized)
                if cat_text not in category_mapping:
                    return cat_text.capitalize()
        
        # Альтернативно - из article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            sections = meta_section['content']
            # Может быть список через запятую или массив
            if isinstance(sections, str):
                sections = sections.split(',')
                for section in sections:
                    section_lower = section.strip().lower()
                    mapped = category_mapping.get(section_lower)
                    if mapped:
                        return mapped
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prepTime', 'cookTime', 'totalTime')
        """
        # Ищем время через microdata атрибут itemprop
        time_elem = self.soup.find(attrs={'itemprop': time_type})
        
        if time_elem:
            # Проверяем атрибут content (может быть ISO duration)
            content = time_elem.get('content')
            if content:
                # Пытаемся парсить ISO duration
                if content.startswith('PT'):
                    return self.parse_iso_duration(content)
            
            # Иначе берем текстовое содержимое
            time_text = time_elem.get_text(strip=True)
            if time_text:
                return self.clean_text(time_text)
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах с указанием единицы, например "90 minutes"
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
        
        return f"{total_minutes} minutes" if total_minutes > 0 else None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prepTime')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('cookTime')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('totalTime')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes_parts = []
        
        # Ищем секцию с заголовком "Tips" или подобным
        h2_tags = self.soup.find_all('h2')
        for h2 in h2_tags:
            h2_text = h2.get_text().strip().lower()
            if 'tip' in h2_text or 'note' in h2_text or 'råd' in h2_text:
                # Собираем все параграфы после этого заголовка до следующего h2
                current = h2.find_next_sibling()
                while current and current.name != 'h2':
                    if current.name == 'p':
                        text = self.clean_text(current.get_text())
                        if text:
                            notes_parts.append(text)
                    current = current.find_next_sibling()
                break
        
        # Ищем секцию с классом, содержащим "recipe-note" или "notes" или "tips"
        notes_section = self.soup.find(class_=re.compile(r'recipe-note|notes|tips', re.I))
        
        if notes_section and not notes_parts:
            # Извлекаем текст
            text = notes_section.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            if text:
                notes_parts.append(text)
        
        # Альтернативно - ищем через itemprop
        if not notes_parts:
            notes_elem = self.soup.find(attrs={'itemprop': re.compile(r'recipeNote|note', re.I)})
            if notes_elem:
                text = notes_elem.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                if text:
                    notes_parts.append(text)
        
        return ' '.join(notes_parts) if notes_parts else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # 1. Ищем категории через rel="tag"
        tag_links = self.soup.find_all('a', rel='tag')
        for tag in tag_links:
            tag_text = self.clean_text(tag.get_text()).lower()
            if tag_text and len(tag_text) >= 2:
                tags_list.append(tag_text)
        
        # 2. Альтернативно - из meta keywords
        if not tags_list:
            meta_keywords = self.soup.find('meta', {'name': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                keywords = meta_keywords['content']
                tags_list = [k.strip().lower() for k in keywords.split(',') if k.strip()]
        
        if not tags_list:
            return None
        
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
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 2. Ищем изображения в контенте рецепта
        recipe_article = self.soup.find('article', class_='recipe')
        if recipe_article:
            # Ищем все img в статье рецепта
            images = recipe_article.find_all('img')
            for img in images:
                src = img.get('src') or img.get('data-src')
                if src and src.startswith('http'):
                    urls.append(src)
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
                    if len(unique_urls) >= 3:  # Ограничиваем до 3 изображений
                        break
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
    """Точка входа для обработки директории с HTML-файлами osuma.dk"""
    import os
    
    # Обрабатываем папку preprocessed/osuma_dk
    recipes_dir = os.path.join("preprocessed", "osuma_dk")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(OsumaDkExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python osuma_dk.py")


if __name__ == "__main__":
    main()
