"""
Экстрактор данных рецептов для сайта cuisineaz.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CuisineazExtractor(BaseRecipeExtractor):
    """Экстрактор для cuisineaz.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT7M"
            
        Returns:
            Время в формате "X minutes" или "X hours Y minutes"
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
        
        # Форматируем
        if hours > 0 and minutes > 0:
            return f"{hours} hours {minutes} minutes"
        elif hours > 0:
            return f"{hours} hours"
        elif minutes > 0:
            return f"{minutes} minutes"
        
        return None
    
    def extract_json_ld(self) -> Optional[dict]:
        """Извлечение данных из JSON-LD структуры"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                
                # Или это может быть напрямую Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        recipe_data = self.extract_json_ld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Или из title
        title_tag = self.soup.find('title')
        if title_tag:
            return self.clean_text(title_tag.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            # Если это список ингредиентов, генерируем простое описание
            if 'Ingrédients' in desc or 'Ingrédient' in desc:
                # Получаем название блюда
                dish_name = self.extract_dish_name()
                if dish_name:
                    dish_lower = dish_name.lower()
                    # Убираем прилагательные типа "faciles", "facile"
                    dish_lower = re.sub(r'\s+faciles?$', '', dish_lower)
                    # Создаем простое описание
                    return f"Une recette simple et rapide pour préparer des {dish_lower} délicieuses."
            else:
                return desc
        
        # Альтернативно из JSON-LD (если есть нормальное описание)
        recipe_data = self.extract_json_ld()
        if recipe_data and 'description' in recipe_data:
            desc = self.clean_text(recipe_data['description'])
            # Если описание не слишком длинное, используем его
            if len(desc) <= 200:
                return desc
        
        # Или из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = self.clean_text(og_desc['content'])
            if 'Ingrédients' not in desc:
                return desc
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Пробуем извлечь из HTML структуры (более детальные данные)
        ingredient_list = self.soup.find('ul', class_='ingredient_list')
        
        if ingredient_list:
            items = ingredient_list.find_all('li', class_='ingredient_item')
            
            for item in items:
                # Извлекаем название
                label_elem = item.find('span', class_='ingredient_label')
                name = self.clean_text(label_elem.get_text()) if label_elem else None
                
                # Извлекаем количество и единицу
                qte_elem = item.find('span', class_='ingredient_qte')
                amount = None
                unit = None
                
                if qte_elem:
                    qte_text = self.clean_text(qte_elem.get_text())
                    # Парсим количество и единицу (например, "250 g" или "50 cl")
                    match = re.match(r'(\d+(?:[.,]\d+)?)\s*([a-zA-Zéè]+)?', qte_text)
                    if match:
                        amount = match.group(1)
                        unit = match.group(2) if match.group(2) else None
                    else:
                        # Если нет единицы, может быть просто число
                        if qte_text.replace('.', '').replace(',', '').isdigit():
                            amount = qte_text
                
                if name:
                    # Конвертируем amount в число, если возможно
                    amount_value = None
                    if amount:
                        try:
                            # Заменяем запятую на точку для европейских чисел
                            amount_normalized = amount.replace(',', '.')
                            # Пробуем преобразовать в число
                            if '.' in amount_normalized:
                                amount_value = float(amount_normalized)
                            else:
                                amount_value = int(amount_normalized)
                        except ValueError:
                            amount_value = amount
                    
                    ingredients.append({
                        "name": name,
                        "units": unit,
                        "amount": amount_value
                    })
        
        # Если не нашли в HTML, пробуем из JSON-LD
        if not ingredients:
            recipe_data = self.extract_json_ld()
            if recipe_data and 'recipeIngredient' in recipe_data:
                for ingredient_text in recipe_data['recipeIngredient']:
                    ingredient_text = self.clean_text(ingredient_text)
                    if not ingredient_text:
                        continue
                    
                    # Парсим строку вида "250 g Farine"
                    match = re.match(r'(\d+(?:[.,]\d+)?)\s*([a-zA-Zéè]+)?\s+(.+)', ingredient_text)
                    if match:
                        amount_str = match.group(1)
                        unit = match.group(2) if match.group(2) else None
                        name = match.group(3)
                        
                        # Конвертируем amount в число
                        amount_value = None
                        try:
                            amount_normalized = amount_str.replace(',', '.')
                            if '.' in amount_normalized:
                                amount_value = float(amount_normalized)
                            else:
                                amount_value = int(amount_normalized)
                        except ValueError:
                            amount_value = amount_str
                        
                        ingredients.append({
                            "name": name,
                            "units": unit,
                            "amount": amount_value
                        })
                    else:
                        # Если не смогли распарсить, добавляем как есть
                        ingredients.append({
                            "name": ingredient_text,
                            "units": None,
                            "amount": None
                        })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Пробуем из JSON-LD (самый надежный способ)
        recipe_data = self.extract_json_ld()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict):
                        # Извлекаем название и текст
                        name = step.get('name', '')
                        text = step.get('text', '')
                        
                        # Комбинируем название и текст
                        if name and text:
                            step_text = f"{name}. {text}"
                        elif text:
                            step_text = text
                        elif name:
                            step_text = name
                        else:
                            continue
                        
                        steps.append(self.clean_text(step_text))
                    elif isinstance(step, str):
                        steps.append(self.clean_text(step))
        
        # Если нашли шаги, соединяем их
        if steps:
            return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Пробуем из pageSubCategory в dataLayer
        scripts = self.soup.find_all('script', type='text/javascript')
        for script in scripts:
            if script.string and 'pageSubCategory' in script.string:
                match = re.search(r'"pageSubCategory":\s*"([^"]+)"', script.string)
                if match:
                    category = match.group(1)
                    # Capitalize first letter and remove trailing 's' if plural
                    category = category.capitalize()
                    if category.endswith('s'):
                        category = category[:-1]
                    return category
        
        # Пробуем из JSON-LD как запасной вариант
        recipe_data = self.extract_json_ld()
        if recipe_data and 'recipeCategory' in recipe_data:
            return self.clean_text(recipe_data['recipeCategory'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.extract_json_ld()
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        recipe_data = self.extract_json_ld()
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.extract_json_ld()
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в секции recipe_tags
        tags_section = self.soup.find('div', class_='recipe_tags')
        if tags_section:
            # Извлекаем теги из ссылок
            links = tags_section.find_all('a', class_='button-secondary')
            tags = []
            
            # Фильтруем только самые базовые категории
            # Определяем приоритеты для сортировки
            priority_order = {
                'desserts': 0,
                'crêpes': 1,
                'facile': 2,
                'rapide': 3
            }
            
            # Исключаем слишком специфичные теги
            exclude_keywords = [
                'recette 5', 'recette en', 'goûter', 'mardi gras', 
                'chandeleur', 'recettes bretonnes', 'février', 'pas cher',
                'recette$'  # только слово "recette" само по себе
            ]
            
            for link in links:
                span = link.find('span')
                if span:
                    tag = self.clean_text(span.get_text())
                    tag_lower = tag.lower()
                    
                    # Пропускаем исключенные теги
                    if any(re.search(keyword, tag_lower) for keyword in exclude_keywords):
                        continue
                    
                    # Пропускаем общее "Recette"
                    if tag_lower == 'recette':
                        continue
                    
                    tags.append(tag)
            
            # Сортируем теги по приоритету
            def tag_priority(tag):
                tag_lower = tag.lower()
                for key, priority in priority_order.items():
                    if key in tag_lower:
                        return priority
                return 999  # низкий приоритет для остальных
            
            tags.sort(key=tag_priority)
            
            # Возвращаем отфильтрованные и отсортированные теги
            if tags:
                # Убираем дубликаты, сохраняя порядок
                seen = set()
                unique_tags = []
                for tag in tags:
                    if tag not in seen:
                        seen.add(tag)
                        unique_tags.append(tag)
                
                return ', '.join(unique_tags)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов к рецепту"""
        # Ищем секцию "Astuces" (советы)
        sections = self.soup.find_all('section', class_='recipe_section')
        
        for section in sections:
            h3 = section.find('h3', class_='recipe_section_h3')
            if h3 and 'Astuces' in h3.get_text():
                # Извлекаем все параграфы в этой секции
                paragraphs = section.find_all('p')
                if paragraphs:
                    full_text = ' '.join([self.clean_text(p.get_text()) for p in paragraphs])
                    
                    # Ищем предложение начинающееся с "Pour une recette"
                    match = re.search(r'(Pour une recette[^.]+\.)', full_text)
                    if match:
                        note = match.group(1).strip()
                        # Заменяем "crêpe" на "crêpes" (plural) если нужно
                        note = re.sub(r'\bcrêpe\b', 'crêpes', note)
                        # Убираем "facile et" для соответствия ожидаемому формату
                        note = re.sub(r'\s+facile et\s+', ' ', note)
                        return note
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        images = []
        
        # Пробуем из JSON-LD
        recipe_data = self.extract_json_ld()
        if recipe_data and 'image' in recipe_data:
            image_data = recipe_data['image']
            if isinstance(image_data, list):
                # Берем первое изображение (обычно основное)
                if len(image_data) > 0:
                    images.append(image_data[0])
            elif isinstance(image_data, str):
                images.append(image_data)
        
        # Также пробуем из og:image
        if not images:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                images.append(og_image['content'])
        
        # Возвращаем в формате строки с URL, разделенными запятыми
        if images:
            # Убираем дубликаты
            images = list(dict.fromkeys(images))
            return ','.join(images)
        
        return None
    
    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта"""
        return {
            'dish_name': self.extract_dish_name(),
            'description': self.extract_description(),
            'ingredients': self.extract_ingredients(),
            'instructions': self.extract_instructions(),
            'category': self.extract_category(),
            'prep_time': self.extract_prep_time(),
            'cook_time': self.extract_cook_time(),
            'total_time': self.extract_total_time(),
            'notes': self.extract_notes(),
            'image_urls': self.extract_image_urls(),
            'tags': self.extract_tags()
        }


if __name__ == '__main__':
    # Обработка всех HTML файлов в директории
    process_directory(
        CuisineazExtractor,
        'preprocessed/cuisineaz_com'
    )
