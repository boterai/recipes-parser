"""
Экстрактор данных рецептов для сайта forkandroots.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ForkAndRootsExtractor(BaseRecipeExtractor):
    """Экстрактор для forkandroots.com"""
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """
        Извлечение данных рецепта из JSON-LD
        
        Returns:
            dict с данными рецепта из JSON-LD или None
        """
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            if not script.string:
                continue
                
            try:
                data = json.loads(script.string)
                
                # Функция для проверки типа Recipe
                def is_recipe(item):
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        return 'Recipe' in item_type
                    return item_type == 'Recipe'
                
                # Ищем Recipe в данных
                recipe_data = None
                
                # Проверяем @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and is_recipe(item):
                            recipe_data = item
                            break
                # Проверяем список
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and is_recipe(item):
                            recipe_data = item
                            break
                # Проверяем сам объект
                elif isinstance(data, dict) and is_recipe(data):
                    recipe_data = data
                
                if recipe_data:
                    return recipe_data
                    
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s+(Recipe|Fork.*Roots).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Из тега title
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            title = re.sub(r'\s+(Recipe|Fork.*Roots).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            # Удаляем информацию о времени, если она есть в конце
            desc = re.sub(r'\s*Prep Time:.*$', '', desc, flags=re.IGNORECASE | re.DOTALL)
            return self.clean_text(desc)
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredients_list = []
        recipe_ingredients = recipe_data['recipeIngredient']
        
        if not isinstance(recipe_ingredients, list):
            return None
        
        for ingredient_text in recipe_ingredients:
            if not ingredient_text:
                continue
            
            # Специальная обработка для "Salt and pepper"
            if re.match(r'^salt\s+and\s+pepper', ingredient_text.lower()):
                # Разделяем на два отдельных ингредиента
                ingredients_list.append({"name": "salt", "amount": None, "units": None})
                ingredients_list.append({"name": "pepper", "amount": None, "units": None})
                continue
            
            # Парсим каждый ингредиент
            parsed = self.parse_ingredient(ingredient_text)
            if parsed:
                ingredients_list.append(parsed)
        
        return json.dumps(ingredients_list, ensure_ascii=False) if ingredients_list else None
    
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
        
        # Убираем комментарии в скобках для более точного парсинга
        text_for_parsing = re.sub(r'\([^)]*\)', '', text).strip()
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text_for_parsing = text_for_parsing.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        pattern = r'^([\d\s/.,]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|tbsp|tsp|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|can|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads|large|medium|small|unit)?\s*(.+)'
        
        match = re.match(pattern, text_for_parsing, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text_for_parsing,
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
        # Удаляем фразы "to taste", "as needed", "optional" но НЕ "diced"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|minced|grated|chopped|sliced|drained|rinsed|and)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r',+', '', name)  # Убираем запятые
        name = re.sub(r'\s+', ' ', name).strip()
        # Убираем артикли в начале
        name = re.sub(r'^(a|an|the)\s+', '', name, flags=re.IGNORECASE)
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления - упрощенная версия из HTML"""
        steps = []
        
        # Ищем список инструкций в HTML (тег <ol> внутри блока инструкций)
        instructions_div = self.soup.find('div', class_=re.compile(r'tasty-recipes-instructions', re.I))
        
        if instructions_div:
            # Ищем основной список шагов (первый <ol>)
            ol_elem = instructions_div.find('ol')
            if ol_elem:
                # Извлекаем все <li> элементы
                li_elements = ol_elem.find_all('li', recursive=False)
                
                for li in li_elements:
                    # Получаем текст, игнорируя теги
                    step_text = li.get_text(separator=' ', strip=True)
                    # Очищаем текст
                    step_text = self.clean_text(step_text)
                    
                    if step_text and len(step_text) > 10:
                        # Упрощаем текст - убираем лишние детали
                        # Убираем вводные фразы типа "The aroma should be", "Don't rush", "Your kitchen should smell"
                        step_text = re.sub(r'\.\s+(The|This|It|Your|Don\'t|You).*?\.', '.', step_text)
                        # Убираем финальные описательные фразы
                        step_text = re.sub(r'[—\-]\s*.*$', '', step_text)
                        
                        step_text = self.clean_text(step_text)
                        steps.append(step_text)
        
        # Если не нашли в HTML, пробуем JSON-LD с фильтрацией
        if not steps:
            recipe_data = self._get_recipe_json_ld()
            if recipe_data and 'recipeInstructions' in recipe_data:
                instructions = recipe_data['recipeInstructions']
                
                # Паттерны для фильтрации нерелевантных шагов
                skip_patterns = [
                    r'^calories?\s*\d+',
                    r'^carbohydrates?\s*\d+',
                    r'^protein\s*\d+',
                    r'^fat\s*\d+',
                    r'^fiber\s*\d+',
                    r'^iron\s*\d+',
                    r'^folate\s*\d+',
                    r'^potassium\s*\d+',
                    r'^fresh spices',
                    r'^full-fat coconut',
                    r'^gentle simmering',
                    r'^taste and adjust',
                    r'^flavors improve',
                    r'^refrigerate for',
                    r'^freezes beautifully',
                    r'^reheat gently',
                    r'^traditional style',
                    r'^grain bowl',
                    r'^with fresh additions',
                    r'^complete the feast',
                    r'^\d+%?\s*dv',
                    r'^serve over',
                    r'^add roasted',
                    r'^pour over',
                    r'^top with'
                ]
                
                if isinstance(instructions, list):
                    for step in instructions:
                        if isinstance(step, dict):
                            step_text = []
                            if 'name' in step and step['name']:
                                step_name = step['name']
                                skip = False
                                for pattern in skip_patterns:
                                    if re.match(pattern, step_name.lower()):
                                        skip = True
                                        break
                                if not skip:
                                    step_text.append(step_name)
                            
                            if 'text' in step and step['text']:
                                step_text.append(step['text'])
                            
                            if step_text:
                                combined = ' '.join(step_text)
                                cleaned = self.clean_text(combined)
                                skip = False
                                for pattern in skip_patterns:
                                    if re.match(pattern, cleaned.lower()):
                                        skip = True
                                        break
                                if not skip and len(cleaned) > 10:
                                    steps.append(cleaned)
                        elif isinstance(step, str):
                            cleaned = self.clean_text(step)
                            skip = False
                            for pattern in skip_patterns:
                                if re.match(pattern, cleaned.lower()):
                                    skip = True
                                    break
                            if not skip and len(cleaned) > 10:
                                steps.append(cleaned)
                elif isinstance(instructions, str):
                    steps.append(self.clean_text(instructions))
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем из JSON-LD @graph Article
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            if not script.string:
                continue
                
            try:
                data = json.loads(script.string)
                
                # Проверяем @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Article':
                            if 'articleSection' in item:
                                sections = item['articleSection']
                                if isinstance(sections, list):
                                    category = ', '.join(sections)
                                elif isinstance(sections, str):
                                    category = self.clean_text(sections)
                                else:
                                    continue
                                
                                # Маппинг категорий к стандартным названиям
                                category_mapping = {
                                    'dinner': 'Main Course',
                                    'lunch': 'Main Course',
                                    'breakfast': 'Breakfast',
                                    'dessert': 'Dessert',
                                    'appetizer': 'Appetizer',
                                    'snack': 'Snack'
                                }
                                
                                category_lower = category.lower()
                                if category_lower in category_mapping:
                                    return category_mapping[category_lower]
                                
                                return category
                                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            category = self.clean_text(meta_section['content'])
            # Применяем тот же маппинг
            category_mapping = {
                'dinner': 'Main Course',
                'lunch': 'Main Course',
                'breakfast': 'Breakfast',
                'dessert': 'Dessert',
                'appetizer': 'Appetizer',
                'snack': 'Snack'
            }
            category_lower = category.lower()
            if category_lower in category_mapping:
                return category_mapping[category_lower]
            return category
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в description JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            # Ищем "Prep Time: 15 minutes"
            match = re.search(r'Prep Time:\s*([^|]+)', desc)
            if match:
                return self.clean_text(match.group(1))
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в description JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            # Ищем "Cook Time: 30 minutes"
            match = re.search(r'Cook Time:\s*([^|]+)', desc)
            if match:
                return self.clean_text(match.group(1))
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в description JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            # Ищем "Total Time: 45 minutes"
            match = re.search(r'Total Time:\s*([^|]+)', desc)
            if match:
                return self.clean_text(match.group(1))
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        notes = []
        
        # Ищем шаги, которые выглядят как заметки (содержат ключевые слова)
        note_keywords = [
            'don\'t skip',
            'use full-fat',
            'this tastes',
            'make it ahead',
            'the curry will',
            'fresh spices',
            'full-fat coconut',
            'gentle simmering',
            'canned version',
            'just add a splash'
        ]
        
        # Исключаем определенные фразы
        exclude_keywords = [
            'taste and adjust',
            'adjust seasoning'
        ]
        
        if isinstance(instructions, list):
            for step in instructions:
                if isinstance(step, dict):
                    # Проверяем name и text
                    step_name = step.get('name', '').lower()
                    step_text = step.get('text', '').lower()
                    
                    # Проверяем исключения
                    is_excluded = False
                    for exclude_kw in exclude_keywords:
                        if exclude_kw in step_name or exclude_kw in step_text:
                            is_excluded = True
                            break
                    
                    if is_excluded:
                        continue
                    
                    # Ищем ключевые слова для заметок
                    for keyword in note_keywords:
                        if keyword in step_name or keyword in step_text:
                            # Это заметка - берем name и/или text
                            note_parts = []
                            if 'name' in step and step['name']:
                                note_text = step['name']
                                # Убираем части после "—" если есть
                                note_text = re.sub(r'—.*$', '', note_text).strip()
                                note_parts.append(self.clean_text(note_text))
                            if 'text' in step and step['text']:
                                note_parts.append(self.clean_text(step['text']))
                            
                            if note_parts:
                                notes.append(' '.join(note_parts))
                            break
        
        if notes:
            # Объединяем заметки
            result = ' '.join(notes)
            # Убираем дублирующиеся точки
            result = re.sub(r'\.+', '.', result)
            return result
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords - упрощенная версия"""
        recipe_data = self._get_recipe_json_ld()
        if not recipe_data or 'keywords' not in recipe_data:
            return None
        
        keywords = recipe_data['keywords']
        tags = []
        
        if isinstance(keywords, str):
            # Разбиваем по запятым
            raw_tags = [tag.strip() for tag in keywords.split(',')]
        elif isinstance(keywords, list):
            raw_tags = [str(tag).strip() for tag in keywords]
        else:
            return None
        
        # Упрощаем теги - извлекаем ключевые слова
        seen = set()
        for tag in raw_tags:
            if not tag or len(tag) < 3:
                continue
            
            tag_lower = tag.lower()
            
            # Проп ускаем очень длинные теги (вероятно фразы) и берем основные слова
            if len(tag) > 30:
                # Извлекаем ключевые слова из длинной фразы
                words = tag.split()
                for word in words:
                    word = word.strip(',-.')
                    word_lower = word.lower()
                    if len(word) >= 4 and word_lower not in seen:
                        # Пропускаем стоп-слова
                        if word_lower not in ['with', 'from', 'this', 'that', 'recipe', 'food', 'based']:
                            seen.add(word_lower)
                            tags.append(word)
                            if len(tags) >= 5:
                                break
            else:
                # Короткий тег - берем как есть
                if tag_lower not in seen:
                    seen.add(tag_lower)
                    tags.append(tag)
            
            if len(tags) >= 5:
                break
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        if not recipe_data or 'image' not in recipe_data:
            return None
        
        urls = []
        images = recipe_data['image']
        
        if isinstance(images, str):
            urls.append(images)
        elif isinstance(images, list):
            for img in images:
                if isinstance(img, str):
                    urls.append(img)
                elif isinstance(img, dict):
                    if 'url' in img:
                        urls.append(img['url'])
                    elif 'contentUrl' in img:
                        urls.append(img['contentUrl'])
        elif isinstance(images, dict):
            if 'url' in images:
                urls.append(images['url'])
            elif 'contentUrl' in images:
                urls.append(images['contentUrl'])
        
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
    """
    Обработка всех HTML файлов из директории preprocessed/forkandroots_com
    """
    import os
    
    # Путь к директории с HTML файлами
    base_dir = Path(__file__).parent.parent
    recipes_dir = base_dir / "preprocessed" / "forkandroots_com"
    
    if recipes_dir.exists() and recipes_dir.is_dir():
        process_directory(ForkAndRootsExtractor, str(recipes_dir))
    else:
        print(f"Директория не найдена: {recipes_dir}")
        print("Использование: python forkandroots_com.py")


if __name__ == "__main__":
    main()
