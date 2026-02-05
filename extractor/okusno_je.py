"""
Экстрактор данных рецептов для сайта okusno.je
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class OkusnoJeExtractor(BaseRecipeExtractor):
    """Экстрактор для okusno.je"""
    
    # Минимальная длина для заметки
    MIN_NOTE_LENGTH = 20
    
    # Поддерживаемые единицы измерения
    SUPPORTED_UNITS = (
        'g', 'kg', 'ml', 'l', 'dl', 'žličke', 'žlički', 'žlica', 'žlice',
        'vrečka', 'vrečke', 'cm', 'mm', 'kos', 'kosi', 'list', 'listi',
        'šop', 'šopi'
    )
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в h1 заголовке
        h1 = self.soup.find('h1', class_=re.compile(r'font-bold.*text-secondary', re.I))
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - любой h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe' and 'name' in data:
                    return self.clean_text(data['name'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем первый параграф с описанием после заголовка
        p = self.soup.find('p', class_=re.compile(r'text-18.*leading-7', re.I))
        if p:
            return self.clean_text(p.get_text())
        
        # Альтернативно - ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe' and 'description' in data:
                    return self.clean_text(data['description'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем извлечь из JSON-LD (самый надежный способ)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe' and 'recipeIngredient' in data:
                    recipe_ingredients = data['recipeIngredient']
                    if isinstance(recipe_ingredients, list):
                        for ing in recipe_ingredients:
                            parsed = self.parse_ingredient_from_text(ing)
                            if parsed:
                                ingredients.append(parsed)
                        if ingredients:
                            return json.dumps(ingredients, ensure_ascii=False)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, парсим HTML
        # Ищем все блоки с ингредиентами
        ingredient_blocks = self.soup.find_all('div', class_=re.compile(r'border.*border-l-0.*border-r-0', re.I))
        
        for block in ingredient_blocks:
            # Ищем количество
            quantity_span = block.find('span', class_='ingredientQuantity')
            if not quantity_span:
                continue
            
            amount = self.clean_text(quantity_span.get_text())
            
            # Ищем единицу измерения (следующий span после количества)
            unit = None
            next_span = quantity_span.find_next_sibling('span')
            if next_span:
                unit_text = self.clean_text(next_span.get_text())
                # Убираем пробелы в начале
                unit = unit_text.strip()
            
            # Ищем название ингредиента
            name_div = block.find('div', class_=re.compile(r'w-2/3', re.I))
            if name_div:
                name = self.clean_text(name_div.get_text())
                
                # Формируем словарь
                ingredient = {
                    "name": name if name else None,
                    "units": unit if unit else None,
                    "amount": amount if amount else None
                }
                ingredients.append(ingredient)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient_from_text(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента из JSON-LD в структурированный формат
        
        Args:
            text: Строка вида "250 g gladke moke"
            
        Returns:
            dict: {"name": "gladke moke", "amount": "250", "units": "g"}
        """
        if not text:
            return None
        
        text = self.clean_text(text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Используем поддерживаемые единицы измерения
        units_pattern = '|'.join(self.SUPPORTED_UNITS)
        pattern = rf'^([\d\s/.,]+)?\s*({units_pattern})?(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            return {"name": text, "amount": None, "units": None}
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount = amount_str.strip().replace(',', '.')
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        name = name.strip() if name else None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe' and 'recipeInstructions' in data:
                    instructions = data['recipeInstructions']
                    if isinstance(instructions, str):
                        # Может содержать HTML теги, очищаем
                        text_soup = BeautifulSoup(instructions, 'lxml')
                        return self.clean_text(text_soup.get_text(separator=' ', strip=True))
                    elif isinstance(instructions, list):
                        for step in instructions:
                            if isinstance(step, dict) and 'text' in step:
                                # Очищаем от HTML тегов
                                text_soup = BeautifulSoup(step['text'], 'lxml')
                                step_text = self.clean_text(text_soup.get_text(separator=' ', strip=True))
                                steps.append(step_text)
                            elif isinstance(step, str):
                                # Очищаем от HTML тегов
                                text_soup = BeautifulSoup(step, 'lxml')
                                step_text = self.clean_text(text_soup.get_text(separator=' ', strip=True))
                                steps.append(step_text)
                        if steps:
                            return ' '.join(steps)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если JSON-LD не помог, парсим HTML
        # Ищем блоки с инструкциями
        instruction_blocks = self.soup.find_all('div', class_=re.compile(r'flex relative p-16.*transition', re.I))
        
        for block in instruction_blocks:
            # Ищем текст инструкции в параграфе
            p = block.find('p')
            if p:
                # Используем get_text() для извлечения чистого текста без тегов
                step_text = self.clean_text(p.get_text(separator=' ', strip=True))
                if step_text:
                    steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe' and 'prepTime' in data:
                    return self.parse_iso_duration(data['prepTime'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Парсим из HTML
        prep_div = self.soup.find('div', id='recipe-preparation-time')
        if prep_div:
            # Извлекаем текст и убираем заголовок
            text = prep_div.get_text(separator=' ', strip=True)
            # Убираем слово PRIPRAVA
            text = re.sub(r'PRIPRAVA', '', text, flags=re.IGNORECASE)
            time_text = self.clean_text(text)
            if time_text:
                return self.format_time(time_text)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe' and 'cookTime' in data:
                    return self.parse_iso_duration(data['cookTime'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Парсим из HTML
        cook_div = self.soup.find('div', id='recipe-cooking-time')
        if cook_div:
            text = cook_div.get_text(separator=' ', strip=True)
            # Убираем слово KUHANJE
            text = re.sub(r'KUHANJE', '', text, flags=re.IGNORECASE)
            time_text = self.clean_text(text)
            if time_text:
                return self.format_time(time_text)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe' and 'totalTime' in data:
                    return self.parse_iso_duration(data['totalTime'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Парсим из HTML
        total_div = self.soup.find('div', id='recipe-combined-time')
        if total_div:
            text = total_div.get_text(separator=' ', strip=True)
            # Убираем слово SKUPAJ
            text = re.sub(r'SKUPAJ', '', text, flags=re.IGNORECASE)
            time_text = self.clean_text(text)
            if time_text:
                return self.format_time(time_text)
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в формат "X minutes" или "X hour Y minutes"
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT90M"
            
        Returns:
            Время в формате "20 minutes" или "1 hour 30 minutes"
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
        
        # Конвертируем минуты в часы, если >= 60
        if minutes >= 60 and hours == 0:
            hours = minutes // 60
            minutes = minutes % 60
        
        # Форматируем результат
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
        if minutes > 0:
            parts.append(f"{minutes} minute" if minutes == 1 else f"{minutes} minutes")
        
        return ' '.join(parts) if parts else None
    
    @staticmethod
    def format_time(time_text: str) -> Optional[str]:
        """
        Форматирует время из формата "40 min" или "1 h 10 min" в стандартный формат
        
        Args:
            time_text: строка вида "40 min" или "1 h 10 min"
            
        Returns:
            Время в формате "40 minutes" или "1 hour 10 minutes"
        """
        if not time_text:
            return None
        
        # Извлекаем часы
        hours = 0
        hour_match = re.search(r'(\d+)\s*h', time_text, re.IGNORECASE)
        if hour_match:
            hours = int(hour_match.group(1))
        
        # Извлекаем минуты
        minutes = 0
        min_match = re.search(r'(\d+)\s*min', time_text, re.IGNORECASE)
        if min_match:
            minutes = int(min_match.group(1))
        
        # Форматируем результат
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
        if minutes > 0:
            parts.append(f"{minutes} minute" if minutes == 1 else f"{minutes} minutes")
        
        return ' '.join(parts) if parts else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем метку с категорией
        label = self.soup.find('span', class_=re.compile(r'label.*bg-primary', re.I))
        if label:
            return self.clean_text(label.get_text())
        
        # Альтернативно - из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe' and 'recipeCategory' in data:
                    return self.clean_text(data['recipeCategory'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем ссылки с тегами (главные составляющие)
        tag_links = self.soup.find_all('a', href=re.compile(r'/iskanje\?q=', re.I))
        
        for link in tag_links:
            tag_text = self.clean_text(link.get_text())
            if tag_text and len(tag_text) > 2:
                tags.append(tag_text.lower())
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию "Dodatni nasvet" (дополнительный совет)
        # Это оранжевый блок с советами
        dodatni_header = self.soup.find(string=re.compile(r'Dodatni nasvet', re.I))
        if dodatni_header:
            parent = dodatni_header.find_parent()
            if parent:
                # Ищем следующий div с текстом
                content_div = parent.find_next_sibling('div', class_=re.compile(r'text-orange', re.I))
                if content_div:
                    p = content_div.find('p')
                    if p:
                        notes_text = self.clean_text(p.get_text(separator=' ', strip=True))
                        if notes_text:
                            return notes_text
        
        # Альтернативно - ищем italic параграф в конце страницы
        italic_p = self.soup.find_all('p', class_=re.compile(r'italic', re.I))
        if italic_p:
            # Берем последний найденный
            notes_text = self.clean_text(italic_p[-1].get_text(separator=' ', strip=True))
            if notes_text and len(notes_text) > self.MIN_NOTE_LENGTH:
                return notes_text
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Сначала пробуем из JSON-LD (самый надежный)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe' and 'image' in data:
                    img = data['image']
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, list):
                        urls.extend([i for i in img if isinstance(i, str)])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если не нашли в JSON-LD, ищем в HTML
        if not urls:
            # Ищем главное изображение
            img_tag = self.soup.find('img', class_='w-full', alt=True)
            if img_tag and img_tag.get('src'):
                urls.append(img_tag['src'])
            
            # Ищем в picture/source тегах
            sources = self.soup.find_all('source', srcset=True)
            for source in sources[:3]:  # Берем первые 3
                srcset = source.get('srcset')
                if srcset:
                    urls.append(srcset)
        
        # Убираем дубликаты
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/okusno_je
    recipes_dir = os.path.join("preprocessed", "okusno_je")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(OkusnoJeExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python okusno_je.py")


if __name__ == "__main__":
    main()
