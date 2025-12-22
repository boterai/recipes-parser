"""
Экстрактор данных рецептов для сайта italiannosh.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ItalianNoshExtractor(BaseRecipeExtractor):
    """Экстрактор для italiannosh.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'headline' in item:
                            return self.clean_text(item['headline'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем параграфы с ключевыми фразами описания
        # Обычно это короткий описательный параграф с ключевыми словами
        all_ps = self.soup.find_all('p')
        
        for p in all_ps:
            text = p.get_text(strip=True)
            # Ищем параграф с характерными фразами описания рецепта
            if len(text) > 40 and len(text) < 300:  # Описание обычно короткое
                # Проверяем ключевые слова, указывающие на описание
                description_keywords = [
                    'delight', 'capture', 'combine', 'comforting', 'festive', 
                    'transform', 'layered with', 'rich', 'creamy', 'velvety',
                    'bursting with', 'essence of'
                ]
                if any(keyword in text.lower() for keyword in description_keywords):
                    # Проверяем, что это не начинается с общих вводных фраз
                    if not text.startswith(('Ah,', 'Picture', 'Imagine', 'To recreate', 'Creating', 'Elevate')):
                        return self.clean_text(text)
        
        # Fallback: ищем в meta description
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
            ingredient_text: Строка вида "1 cup all-purpose flour" или "2 pounds chicken"
            
        Returns:
            dict: {"name": "flour", "amount": "1", "units": "cup"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        pattern = r'^([\d\s/.,]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads|small|medium|large|can)?\s*(.+)'
        
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
                amount = total
            else:
                try:
                    amount = float(amount_str.replace(',', '.'))
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional", "for garnish", etc.
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|for dusting|at room temperature)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем заголовок "Ingredients"
        ingredients_heading = self.soup.find('h2', string=lambda text: 'Ingredients' in text if text else False)
        
        if ingredients_heading:
            # Находим следующий ul после заголовка
            next_ul = ingredients_heading.find_next('ul')
            if next_ul:
                items = next_ul.find_all('li', recursive=False)
                
                for item in items:
                    # Извлекаем текст ингредиента
                    ingredient_text = item.get_text(separator=' ', strip=True)
                    ingredient_text = self.clean_text(ingredient_text)
                    
                    # Парсим в структурированный формат
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем заголовок "Instructions"
        instructions_heading = self.soup.find('h2', string=lambda text: 'Instructions' in text if text else False)
        
        if instructions_heading:
            # Находим следующий ol после заголовка
            next_ol = instructions_heading.find_next('ol')
            if next_ol:
                step_items = next_ol.find_all('li', recursive=False)
                
                for idx, item in enumerate(step_items, 1):
                    # Извлекаем текст инструкции
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    
                    if step_text:
                        # Удаляем заголовки в bold (например "Brew the coffee:")
                        # Заменяем на более простой формат
                        step_text = re.sub(r'^([^:]+):\s*', '', step_text)
                        
                        # Добавляем нумерацию
                        step_text = f"{idx}. {step_text}"
                        steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # Ищем секцию с nutrition информацией
        # На italiannosh.com такой информации обычно нет, но проверим
        nutrition_section = self.soup.find(class_=re.compile(r'nutrition', re.I))
        
        if nutrition_section:
            # Пытаемся извлечь данные
            text = nutrition_section.get_text(strip=True)
            # Ищем калории и БЖУ в тексте
            cal_match = re.search(r'(\d+)\s*kcal', text, re.I)
            if cal_match:
                return f"{cal_match.group(1)} kcal"
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list) and sections:
                                # Убираем " Recipes" из категории
                                category = sections[0].replace(' Recipes', '')
                                return self.clean_text(category)
                            elif isinstance(sections, str):
                                category = sections.replace(' Recipes', '')
                                return self.clean_text(category)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из breadcrumbs
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                category = links[-1].get_text()
                category = category.replace(' Recipes', '')
                return self.clean_text(category)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в content различные паттерны prep time
        content = self.soup.find(class_=re.compile(r'entry-content|post-content', re.I))
        if content:
            text = content.get_text()
            
            # Паттерн 1: "prep time: X minutes" или "preparation: X minutes"
            prep_match = re.search(r'prep(?:aration)?\s*(?:time)?[:\s]+(\d+)\s*(minutes?|mins?|hours?|hrs?)', text, re.I)
            if prep_match:
                value = prep_match.group(1)
                unit = prep_match.group(2)
                if 'min' in unit.lower():
                    return f"{value} minutes"
                elif 'hour' in unit.lower() or 'hr' in unit.lower():
                    return f"{value} hours"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        # Проверяем в content
        content = self.soup.find(class_=re.compile(r'entry-content|post-content', re.I))
        if content:
            text = content.get_text()
            
            # Ищем паттерны типа "bake for X minutes", "cook for X minutes", "simmer for X minutes"
            cook_patterns = [
                r'(?:bake|cook|simmer)\s+for\s+(?:about\s+)?(?:[\d\-]+)\s*(?:to\s+)?(\d+)\s*(minutes?|mins?|hours?|hrs?)',
                r'cook(?:ing)?\s*(?:time)?[:\s]+(\d+)\s*(minutes?|mins?|hours?|hrs?)',
            ]
            
            for pattern in cook_patterns:
                cook_match = re.search(pattern, text, re.I)
                if cook_match:
                    value = cook_match.group(1)
                    unit = cook_match.group(2)
                    if 'min' in unit.lower():
                        return f"{value} minutes"
                    elif 'hour' in unit.lower() or 'hr' in unit.lower():
                        return f"{value} hours"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Проверяем в content для специфических паттернов
        content = self.soup.find(class_=re.compile(r'entry-content|post-content', re.I))
        if content:
            text = content.get_text()
            
            # Ищем паттерны типа "at least X hours/minutes", "for at least X", "refrigerate for X"
            total_patterns = [
                r'(?:refrigerate|chill)\s+for\s+(?:at\s+least\s+)?(\d+)\s*(minutes?|mins?|hours?|hrs?)',
                r'(?:at\s+least|for\s+about)\s+(\d+)\s*(minutes?|mins?|hours?|hrs?)',
                r'total\s*(?:time)?[:\s]+(\d+)\s*(minutes?|mins?|hours?|hrs?)',
            ]
            
            for pattern in total_patterns:
                total_match = re.search(pattern, text, re.I)
                if total_match:
                    value = total_match.group(1)
                    unit = total_match.group(2)
                    if 'min' in unit.lower():
                        return f"{value} minutes"
                    elif 'hour' in unit.lower() or 'hr' in unit.lower():
                        return f"{value} hours"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем секции с вариациями или заметками
        # Обычно это заголовки типа "Tweaks and Additions", "Variations", "Tips", etc.
        headings = self.soup.find_all('h2', string=lambda text: text and any(
            keyword in text.lower() for keyword in ['tweak', 'addition', 'variation', 'tip', 'note', 'substitution']
        ))
        
        for heading in headings:
            # Собираем содержимое из ul/ol после заголовка
            next_elem = heading.find_next_sibling()
            
            while next_elem and next_elem.name != 'h2':
                if next_elem.name == 'ul':
                    # Собираем все элементы списка
                    items = next_elem.find_all('li', recursive=False)
                    for item in items:
                        text = item.get_text(separator=' ', strip=True)
                        # Удаляем заголовки в bold
                        text = re.sub(r'^[^:]+:\s*', '', text)
                        if text:
                            notes.append(text)
                elif next_elem.name == 'p':
                    text = next_elem.get_text(separator=' ', strip=True)
                    if text:
                        notes.append(text)
                
                next_elem = next_elem.find_next_sibling()
        
        if notes:
            return self.clean_text(' '.join(notes))
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем в JSON-LD keywords
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article':
                            # Keywords
                            if 'keywords' in item:
                                keywords = item['keywords']
                                if isinstance(keywords, list):
                                    tags.extend(keywords)
                                elif isinstance(keywords, str):
                                    tags.extend([k.strip() for k in keywords.split(',')])
                            
                            # Article section (category)
                            if 'articleSection' in item:
                                sections = item['articleSection']
                                if isinstance(sections, list):
                                    for section in sections:
                                        # Убираем " Recipes" и добавляем категорию как тег
                                        clean_section = section.replace(' Recipes', '')
                                        tags.append(clean_section)
                                elif isinstance(sections, str):
                                    clean_section = sections.replace(' Recipes', '')
                                    tags.append(clean_section)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Также ищем в мета-тегах
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags.extend([k.strip() for k in keywords.split(',')])
        
        if tags:
            # Удаляем дубликаты, сохраняя порядок
            unique_tags = []
            seen = set()
            for tag in tags:
                tag_clean = self.clean_text(tag)
                tag_lower = tag_clean.lower()
                if tag_lower and tag_lower not in seen:
                    seen.add(tag_lower)
                    unique_tags.append(tag_clean)
            
            return ', '.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
                        # Article with thumbnailUrl
                        elif item.get('@type') == 'Article' and 'thumbnailUrl' in item:
                            urls.append(item['thumbnailUrl'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 2. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
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
            "instructions": self.extract_steps(),
            "nutrition_info": self.extract_nutrition_info(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Точка входа для обработки директории с HTML-файлами"""
    import os
    
    # Путь к директории с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "italiannosh_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ItalianNoshExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python italiannosh_com.py")


if __name__ == "__main__":
    main()
