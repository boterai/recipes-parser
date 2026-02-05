"""
Экстрактор данных рецептов для сайта receitas.globo.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ReceitasGloboExtractor(BaseRecipeExtractor):
    """Экстрактор для receitas.globo.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в meta теге itemprop="name"
        meta_name = self.soup.find('meta', attrs={'itemprop': 'name'})
        if meta_name and meta_name.get('content'):
            return self.clean_text(meta_name['content'])
        
        # Ищем в заголовке h1
        h1 = self.soup.find('h1', class_='content-head__title')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из title тега
        title = self.soup.find('title')
        if title:
            title_text = title.get_text()
            # Убираем суффикс " | Receitas"
            title_text = re.sub(r'\s+\|\s+Receitas.*$', '', title_text)
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
    
    def parse_ingredient_text(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "500g de udon" или "2 litros de água"
            
        Returns:
            dict: {"name": "udon", "amount": 500, "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
        # Паттерн 1: "600g" в конце строки (например, "1 copa-lombo de porco de aprox. 600g")
        amount_at_end = re.search(r'(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l)\s*$', text)
        if amount_at_end:
            # Извлекаем количество и единицу в конце
            amount_str = amount_at_end.group(1)
            unit_str = amount_at_end.group(2)
            
            # Убираем количество и единицу из названия
            name = text[:amount_at_end.start()].strip()
            # Убираем "de aprox.", "aprox.", "cerca de" и т.д.
            name = re.sub(r'\b(de\s+)?aprox\.?|cerca\s+de\b', '', name, flags=re.IGNORECASE).strip()
            # Убираем начальное количество если есть (например, "1 copa-lombo")
            name = re.sub(r'^\d+\s+', '', name).strip()
            
            # Обработка количества
            amount_str = amount_str.replace(',', '.')
            try:
                if '.' in amount_str:
                    amount = float(amount_str)
                else:
                    amount = int(amount_str)
            except ValueError:
                amount = None
            
            return {
                "name": name,
                "amount": amount,
                "units": unit_str
            }
        
        # Паттерн 2: Стандартный формат "500g de udon", "2 litros de água", "4 gramas de kanten"
        # Сначала пробуем с "de"
        pattern1 = r'^(\d+(?:[.,]\d+)?)\s*(g|kg|ml|gramas?|quilogramas?|mililitros?|litros?|xícaras?|colheres?\s+de\s+(?:sopa|chá)|dentes?|molhos?)\s+de\s+(.+)$'
        match = re.match(pattern1, text, re.IGNORECASE)
        
        if not match:
            # Пробуем без "de" - для случаев типа "4 ovos de gema mole"
            pattern2 = r'^(\d+(?:[.,]\d+)?)\s+(ovos?|pimentas?)\s+(.+)$'
            match = re.match(pattern2, text, re.IGNORECASE)
            
            if match:
                # Для этих случаев объединяем единицу с названием
                amount_str, unit_str, rest_name = match.groups()
                
                # Обработка количества
                amount_str = amount_str.replace(',', '.')
                try:
                    if '.' in amount_str:
                        amount = float(amount_str)
                    else:
                        amount = int(amount_str)
                except ValueError:
                    amount = None
                
                # Объединяем единицу с названием
                name = f"{unit_str} {rest_name}"
                
                # Очистка названия
                name = re.sub(r'\([^)]*\)', '', name)  # Удаляем скобки
                name = re.sub(r'\b(a gosto|opcional|para decorar|se necessário)\b', '', name, flags=re.IGNORECASE)
                name = re.sub(r'[,;]+$', '', name)  # Удаляем запятые в конце
                name = re.sub(r'\s+', ' ', name).strip()  # Нормализуем пробелы
                
                if not name or len(name) < 2:
                    return None
                
                return {
                    "name": name,
                    "amount": amount,
                    "units": None
                }
        
        if not match:
            # Пробуем без "de" для других случаев
            pattern3 = r'^(\d+(?:[.,]\d+)?)\s*(g|kg|ml|gramas?|quilogramas?|mililitros?|litros?|xícaras?|colheres?\s+de\s+(?:sopa|chá)|dentes?|molhos?)\s+(.+)$'
            match = re.match(pattern3, text, re.IGNORECASE)
        
        if match:
            amount_str, unit_str, name = match.groups()
            
            # Обработка количества
            amount_str = amount_str.replace(',', '.')
            try:
                if '.' in amount_str:
                    amount = float(amount_str)
                else:
                    amount = int(amount_str)
            except ValueError:
                amount = None
            
            # Нормализация единицы измерения
            unit_str = unit_str.strip().lower() if unit_str else None
            
            # Словарь для преобразования португальских единиц
            unit_mapping = {
                'g': 'g',
                'grama': 'grams',
                'gramas': 'grams',
                'kg': 'kg',
                'quilograma': 'kilograms',
                'quilogramas': 'kilograms',
                'ml': 'ml',
                'mililitro': 'milliliters',
                'mililitros': 'milliliters',
                'litro': 'liters',
                'litros': 'liters',
                'l': 'liters',
                'xícara': 'xícara',
                'xícaras': 'xícara',
                'colher de sopa': 'colheres de sopa',
                'colheres de sopa': 'colheres de sopa',
                'colher de chá': 'colheres de chá',
                'colheres de chá': 'colheres de chá',
                'dente': 'dentes',
                'dentes': 'dentes',
                'molho': 'molho',
                'molhos': 'molho',
            }
            
            # Преобразуем единицу
            units = unit_mapping.get(unit_str, unit_str)
            
            # Очистка названия
            name = re.sub(r'\([^)]*\)', '', name)  # Удаляем скобки
            name = re.sub(r'\b(a gosto|opcional|para decorar|se necessário|pode usar.*)\b', '', name, flags=re.IGNORECASE)
            name = re.sub(r'[,;]+$', '', name)  # Удаляем запятые в конце
            name = re.sub(r'\s+', ' ', name).strip()  # Нормализуем пробелы
            
            if not name or len(name) < 2:
                return None
            
            return {
                "name": name,
                "amount": amount,
                "units": units
            }
        
        # Паттерн 3: Ингредиенты без количества (например, "sal e pimenta a gosto")
        if 'a gosto' in text or 'opcional' in text or 'para decorar' in text:
            # Убираем фразы "a gosto", "opcional" и т.д.
            name = re.sub(r'\b(a gosto|opcional|para decorar|se necessário)\b', '', text, flags=re.IGNORECASE)
            name = name.strip()
            return {
                "name": name if name else text,
                "amount": None,
                "units": None
            }
        
        # Возвращаем только название
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем все элементы с itemprop="recipeIngredient"
        ingredient_items = self.soup.find_all('li', attrs={'itemprop': 'recipeIngredient'})
        
        for item in ingredient_items:
            ingredient_text = item.get_text(strip=True)
            
            # Парсим ингредиент
            parsed = self.parse_ingredient_text(ingredient_text)
            if parsed:
                ingredients.append(parsed)
        
        # Также проверяем subtitle (например, "1 copa-lombo de porco de aprox. 600g")
        # но пропускаем секционные заголовки
        subtitles = self.soup.find_all('h2', class_='content-subtitle__title')
        
        for subtitle in subtitles:
            subtitle_text = subtitle.get_text(strip=True)
            # Пропускаем заголовки секций (начинаются с "Para")
            if not subtitle_text or subtitle_text.lower().startswith('para'):
                continue
            
            # Пропускаем другие типовые заголовки
            section_headers = [
                'ingredientes', 'modo de preparo', 'modo de fazer',
                'massa', 'recheio', 'cobertura'
            ]
            if subtitle_text.lower() in section_headers:
                continue
            
            # Парсим как ингредиент
            parsed = self.parse_ingredient_text(subtitle_text)
            if parsed and parsed['name']:
                # Вставляем в начало, так как это обычно основной ингредиент
                ingredients.insert(0, parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем все элементы с itemprop="recipeInstructions"
        instruction_items = self.soup.find_all('li', class_='recipeInstruction')
        
        for item in instruction_items:
            # Извлекаем текст инструкции
            text_span = item.find('span', class_='recipeInstruction__text')
            index_span = item.find('span', class_='recipeInstruction__index')
            
            if text_span:
                step_text = self.clean_text(text_span.get_text())
                index = index_span.get_text() if index_span else str(len(steps) + 1)
                
                if step_text:
                    steps.append(f"{index}. {step_text}")
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Проверяем JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                # Ищем recipeCategory
                if isinstance(data, dict):
                    if 'recipeCategory' in data:
                        return self.clean_text(data['recipeCategory'])
                    
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and 'recipeCategory' in item:
                                return self.clean_text(item['recipeCategory'])
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в span с классом recipe-description-details-info
        time_spans = self.soup.find_all('span', class_='recipe-description-details-info')
        
        for span in time_spans:
            text = span.get_text(strip=True)
            # Проверяем, содержит ли текст время (например, "1h30min", "30min")
            if re.search(r'\d+[hm]', text, re.IGNORECASE):
                # Преобразуем формат "1h30min" в "1h30min" (оставляем как есть)
                return self.clean_text(text)
        
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict):
                    # Ищем cookTime или totalTime
                    if 'cookTime' in data:
                        return self.parse_iso_duration(data['cookTime'])
                    if 'totalTime' in data:
                        return self.parse_iso_duration(data['totalTime'])
                    
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict):
                                if 'cookTime' in item:
                                    return self.parse_iso_duration(item['cookTime'])
                                if 'totalTime' in item:
                                    return self.parse_iso_duration(item['totalTime'])
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def parse_iso_duration(self, duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в формат "Xh Ymin" или "Ymin"
        
        Args:
            duration: строка вида "PT1H30M" или "PT30M"
            
        Returns:
            Время в формате "1h30min" или "30min"
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
        
        # Форматируем результат
        if hours > 0 and minutes > 0:
            return f"{hours}h{minutes}min"
        elif hours > 0:
            return f"{hours}h"
        elif minutes > 0:
            return f"{minutes}min"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict):
                    if 'prepTime' in data:
                        return self.parse_iso_duration(data['prepTime'])
                    
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and 'prepTime' in item:
                                return self.parse_iso_duration(item['prepTime'])
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict):
                    if 'totalTime' in data:
                        return self.parse_iso_duration(data['totalTime'])
                    
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and 'totalTime' in item:
                                return self.parse_iso_duration(item['totalTime'])
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # На receitas.globo.com нет явных заметок в примерах
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в keywords meta тегах
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Убираем лишние пробелы и возвращаем
            tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            return ', '.join(tags) if tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', property='twitter:image')
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if url not in urls:
                urls.append(url)
        
        itemprop_image = self.soup.find('meta', attrs={'itemprop': 'image'})
        if itemprop_image and itemprop_image.get('content'):
            url = itemprop_image['content']
            if url not in urls:
                urls.append(url)
        
        # 2. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                # Функция для извлечения изображений из объекта
                def extract_images(obj):
                    if isinstance(obj, dict):
                        if 'image' in obj:
                            img = obj['image']
                            if isinstance(img, str):
                                return [img]
                            elif isinstance(img, list):
                                return [i for i in img if isinstance(i, str)]
                            elif isinstance(img, dict):
                                if 'url' in img:
                                    return [img['url']]
                                elif 'contentUrl' in img:
                                    return [img['contentUrl']]
                    return []
                
                if isinstance(data, dict):
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            for img_url in extract_images(item):
                                if img_url not in urls:
                                    urls.append(img_url)
                    else:
                        for img_url in extract_images(data):
                            if img_url not in urls:
                                urls.append(img_url)
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ограничиваем до первых 3 уникальных изображений
        unique_urls = []
        for url in urls:
            if url and url not in unique_urls:
                unique_urls.append(url)
                if len(unique_urls) >= 3:
                    break
        
        return ','.join(unique_urls) if unique_urls else None
    
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
    """Обработка всех HTML файлов в preprocessed/receitas_globo_com"""
    import os
    
    # Путь к директории с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "receitas_globo_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ReceitasGloboExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python receitas_globo_com.py")


if __name__ == "__main__":
    main()
