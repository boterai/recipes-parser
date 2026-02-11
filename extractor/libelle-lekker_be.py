"""
Экстрактор данных рецептов для сайта libelle-lekker.be
"""

import sys
from pathlib import Path
import json
import re
import html as html_module
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class LibelleLekkerExtractor(BaseRecipeExtractor):
    """Экстрактор для libelle-lekker.be"""
    
    def _get_rmg_recipe_data(self) -> Optional[dict]:
        """Извлечение данных из JavaScript переменной rmg_recipe_data"""
        scripts = self.soup.find_all('script')
        
        for script in scripts:
            if not script.string:
                continue
            
            # Ищем var rmg_recipe_data = {...}
            match = re.search(r'var\s+rmg_recipe_data\s*=\s*({[^;]+})', script.string)
            if match:
                try:
                    data = json.loads(match.group(1))
                    return data
                except json.JSONDecodeError:
                    continue
        
        return None
    
    def _get_data_attribute_ingredients(self) -> Optional[list]:
        """Извлечение ингредиентов из data-ingredient-groups атрибута"""
        ingredient_div = self.soup.find('div', id='react-recipe-ingredients')
        if not ingredient_div:
            return None
        
        data_attr = ingredient_div.get('data-ingredient-groups')
        if not data_attr:
            return None
        
        try:
            # Декодируем HTML entities
            decoded = html_module.unescape(data_attr)
            # Парсим JSON
            ingredient_groups = json.loads(decoded)
            
            ingredients = []
            for group in ingredient_groups:
                if 'ingredients' not in group:
                    continue
                
                for item in group['ingredients']:
                    # Извлекаем название ингредиента
                    name = None
                    if 'ingredientName' in item:
                        name = item['ingredientName']
                    elif 'ingredient' in item and 'nameDisplay' in item['ingredient']:
                        name = item['ingredient']['nameDisplay']
                    elif 'ingredient' in item and 'nameSelect' in item['ingredient']:
                        name = item['ingredient']['nameSelect']
                    
                    # Извлекаем количество
                    amount = None
                    if 'quantity' in item:
                        qty = item['quantity']
                        try:
                            # Преобразуем в число и убираем .00
                            qty_float = float(qty)
                            if qty_float == 0:
                                amount = None
                            elif qty_float == int(qty_float):
                                amount = int(qty_float)
                            else:
                                amount = qty_float
                        except (ValueError, TypeError):
                            amount = qty
                    
                    # Извлекаем единицу измерения
                    unit = None
                    if 'unitName' in item:
                        unit = item['unitName'] if item['unitName'] else None
                    elif 'unit' in item:
                        unit_data = item['unit']
                        if isinstance(unit_data, dict):
                            unit = unit_data.get('name') or unit_data.get('namePlural')
                            if not unit:
                                unit = None
                    
                    # Добавляем info если есть
                    if name:
                        # Если есть дополнительная информация (info), добавляем к названию
                        if 'info' in item and item['info']:
                            name = f"{name} ({item['info']})"
                        
                        ingredients.append({
                            "name": name,
                            "amount": amount,
                            "units": unit
                        })
            
            return ingredients if ingredients else None
            
        except (json.JSONDecodeError, KeyError) as e:
            return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в мета-теге og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s*-\s*Libelle Lekker.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Альтернативно - из заголовка страницы
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            title = re.sub(r'\s*-\s*Libelle Lekker.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в мета-теге og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            # Убираем HTML теги если есть
            desc = re.sub(r'<[^>]+>', '', desc)
            desc = self.clean_text(desc)
            # Проверяем что это не общее описание сайта
            if desc and 'libelle' not in desc.lower() and len(desc) > 10:
                return desc
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            desc = re.sub(r'<[^>]+>', '', desc)
            desc = self.clean_text(desc)
            if desc and 'libelle' not in desc.lower() and len(desc) > 10:
                return desc
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из data-атрибута"""
        ingredients = self._get_data_attribute_ingredients()
        
        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем секцию preparation
        prep_section = self.soup.find('div', class_='recipe-detail__preparation')
        if prep_section:
            # Ищем список шагов
            step_items = prep_section.find_all('li')
            
            for idx, item in enumerate(step_items, 1):
                # Извлекаем текст шага (пропускаем step-number)
                step_text = ''
                for elem in item.find_all(['p']):
                    if 'step-number' not in elem.get('class', []):
                        text = elem.get_text(separator=' ', strip=True)
                        if text:
                            step_text += ' ' + text
                
                step_text = self.clean_text(step_text.strip())
                if step_text:
                    steps.append(f"{idx}. {step_text}")
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Извлекаем из rmg_recipe_data
        recipe_data = self._get_rmg_recipe_data()
        if recipe_data:
            # Берем courses (основная категория)
            if 'courses' in recipe_data and recipe_data['courses']:
                return recipe_data['courses'][0]
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На этом сайте нет явного разделения prep/cook time
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Пытаемся извлечь из инструкций (часто упоминается время выпечки/готовки)
        instructions = self.extract_instructions()
        if instructions:
            # Ищем паттерны времени в инструкциях
            # Сначала пробуем найти "X uur en Y minuten" (X hours and Y minutes)
            hour_min_match = re.search(r'(\d+)\s*uur\s+en\s+(\d+)\s*minuten', instructions, re.IGNORECASE)
            if hour_min_match:
                hours = int(hour_min_match.group(1))
                minutes = int(hour_min_match.group(2))
                total_minutes = hours * 60 + minutes
                return f"{total_minutes} minutes"
            
            # Ищем только часы
            hour_match = re.search(r'(\d+)\s*uur', instructions, re.IGNORECASE)
            if hour_match:
                hours = int(hour_match.group(1))
                return f"{hours * 60} minutes"
            
            # Ищем только минуты
            time_match = re.search(r'(\d+)\s*(minuten|minutes|min)', instructions, re.IGNORECASE)
            if time_match:
                minutes = time_match.group(1)
                return f"{minutes} minutes"
        
        # Альтернативно - из секции meta
        meta_section = self.soup.find('div', class_='recipe-detail__meta')
        if meta_section:
            text = meta_section.get_text()
            # Ищем паттерны времени
            time_match = re.search(r'(\d+)\s*(minuten|minutes|min)', text, re.IGNORECASE)
            if time_match:
                minutes = time_match.group(1)
                return f"{minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # На этом сайте нет явного указания total time
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # На этом сайте нет явной секции notes
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Извлекаем из rmg_recipe_data
        recipe_data = self._get_rmg_recipe_data()
        if recipe_data:
            # Собираем теги из разных полей
            if 'cuisines' in recipe_data and recipe_data['cuisines']:
                tags_list.extend(recipe_data['cuisines'])
            
            if 'courses' in recipe_data and recipe_data['courses']:
                tags_list.extend(recipe_data['courses'])
            
            if 'families' in recipe_data and recipe_data['families']:
                tags_list.extend(recipe_data['families'])
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags_list:
            if tag and tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ','.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
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
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/libelle-lekker_be
    preprocessed_dir = os.path.join("preprocessed", "libelle-lekker_be")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(LibelleLekkerExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python libelle-lekker_be.py")


if __name__ == "__main__":
    main()
