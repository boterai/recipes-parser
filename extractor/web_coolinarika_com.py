"""
Экстрактор данных рецептов для сайта web.coolinarika.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class WebCoolnarikaExtractor(BaseRecipeExtractor):
    """Экстрактор для web.coolinarika.com"""
    
    def _get_next_data(self) -> Optional[dict]:
        """
        Извлечение данных из __NEXT_DATA__ скрипта
        
        Returns:
            Словарь с данными рецепта или None
        """
        next_data_script = self.soup.find('script', {'id': '__NEXT_DATA__'})
        if not next_data_script:
            return None
        
        try:
            data = json.loads(next_data_script.string)
            
            # Навигация к данным рецепта
            queries = data.get('props', {}).get('pageProps', {}).get('dehydratedState', {}).get('queries', [])
            
            # Ищем запрос с данными рецепта (обычно первый)
            for query in queries:
                query_key = query.get('queryKey', [])
                # Ищем запрос типа ['one', 'combined', 'feed', 'recept', ...]
                if isinstance(query_key, list) and len(query_key) > 3 and query_key[3] == 'recept':
                    recipe_data = query.get('state', {}).get('data', {})
                    if recipe_data and 'title' in recipe_data:
                        return recipe_data
            
        except (json.JSONDecodeError, KeyError) as e:
            return None
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self._get_next_data()
        
        if recipe_data and 'title' in recipe_data:
            return self.clean_text(recipe_data['title'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self._get_next_data()
        
        if recipe_data and 'lead' in recipe_data:
            # lead может содержать HTML-теги типа <para>
            lead = recipe_data['lead']
            if lead:
                # Убираем HTML-теги
                soup_desc = BeautifulSoup(lead, 'lxml')
                text = soup_desc.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                
                # Берем только первое предложение
                first_sentence = text.split('.')[0]
                if first_sentence:
                    if not first_sentence.endswith('.'):
                        first_sentence += '.'
                    return first_sentence
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате JSON"""
        recipe_data = self._get_next_data()
        
        if not recipe_data or 'ingredients' not in recipe_data:
            return None
        
        ingredients_list = []
        
        for ingredient in recipe_data['ingredients']:
            # Извлекаем данные ингредиента
            name = ingredient.get('name', '')
            quantity = ingredient.get('quantity', '')
            
            # Парсим количество и единицы измерения
            amount = None
            unit = None
            
            if quantity:
                # Пытаемся разделить количество на число и единицы
                # Примеры: "350-400g", "50g", "0.5l", "2 kom"
                match = re.match(r'^([\d.,\-]+)\s*([a-zA-Zščćžđ]+)?$', quantity.strip())
                if match:
                    amount = match.group(1)
                    unit = match.group(2) if match.group(2) else None
                else:
                    # Если не удалось разделить, считаем все количеством
                    amount = quantity
            
            ingredients_list.append({
                "name": name,
                "units": unit,
                "amount": amount
            })
        
        return json.dumps(ingredients_list, ensure_ascii=False) if ingredients_list else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        recipe_data = self._get_next_data()
        
        if not recipe_data or 'preparation_steps' not in recipe_data:
            return None
        
        steps = []
        
        for idx, step in enumerate(recipe_data['preparation_steps'], 1):
            # description может содержать HTML
            description = step.get('description', '')
            if description:
                # Парсим HTML для извлечения заголовков шагов
                soup_step = BeautifulSoup(description, 'lxml')
                
                # Ищем заголовок в <strong> тегах
                strong_tag = soup_step.find('strong')
                if strong_tag:
                    title = strong_tag.get_text(strip=True)
                    title = self.clean_text(title)
                    
                    # Убираем префиксы типа "prvo-", "drugo-", "cetvrto-", и двоеточия
                    title = re.sub(r'^[a-z]+\s*-\s*', '', title, flags=re.I)
                    title = title.rstrip(':')
                    
                    # Убираем "opet" (again) из названий
                    title = re.sub(r'\bopet\s+', '', title, flags=re.I)
                    
                    if title:
                        # Форматируем: первая буква заглавная, остальные строчные
                        title = title.capitalize()
                        # Добавляем точку в конец
                        if not title.endswith('.'):
                            title += '.'
                        steps.append(f"{idx}. {title}")
                else:
                    # Если нет заголовка, пропускаем этот шаг (например, ps.)
                    pass
        
        return ' '.join(steps) if steps else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """
        Извлечение информации о питательности
        Формат: "130 kkal; 10/12/20" (калории; белки/жиры/углеводы)
        """
        # В данных web.coolinarika.com обычно нет информации о питательности
        # Возвращаем None
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        recipe_data = self._get_next_data()
        
        if not recipe_data or 'taxons' not in recipe_data:
            return None
        
        taxons = recipe_data['taxons']
        
        # Ищем в taxons категорию типа блюда (meal-type)
        if isinstance(taxons, dict):
            # Ищем в coolinarika-recipe-meal-type
            meal_types = taxons.get('coolinarika-recipe-meal-type', [])
            if meal_types and isinstance(meal_types, list) and len(meal_types) > 0:
                # Берем первую категорию
                category_title = meal_types[0].get('title', '')
                if category_title:
                    # Переводим на английский основные категории
                    category_map = {
                        'glavna jela': 'Main Course',
                        'predjela': 'Appetizer',
                        'deserti': 'Dessert',
                        'salate': 'Salad',
                        'juhe': 'Soup',
                        'pekarski proizvodi': 'Bakery',
                    }
                    
                    category_lower = category_title.lower()
                    return category_map.get(category_lower, category_title)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_next_data()
        
        if not recipe_data or 'preparation_time' not in recipe_data:
            return None
        
        prep_time = recipe_data['preparation_time']
        
        if prep_time:
            # prep_time обычно в минутах (число или строка с числом)
            if isinstance(prep_time, (int, float)):
                minutes = int(prep_time)
                return f"{minutes} minutes"
            elif isinstance(prep_time, str):
                # Проверяем, является ли строка числом
                if prep_time.isdigit():
                    return f"{prep_time} minutes"
                else:
                    return prep_time
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # В web.coolinarika.com нет отдельного cook_time
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени приготовления"""
        # В web.coolinarika.com нет отдельного total_time
        # preparation_time используется как prep_time
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение дополнительных заметок"""
        recipe_data = self._get_next_data()
        
        if not recipe_data:
            return None
        
        # Проверяем последний шаг приготовления - он может содержать заметки
        if 'preparation_steps' in recipe_data and recipe_data['preparation_steps']:
            last_step = recipe_data['preparation_steps'][-1]
            description = last_step.get('description', '')
            
            if description:
                soup_step = BeautifulSoup(description, 'lxml')
                text = soup_step.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                
                # Проверяем, является ли это заметкой (начинается с ps., p.s., napomena и т.д.)
                if re.match(r'^(ps\.|p\.s\.|napomena|savjet|tip|važno|note)', text.lower()):
                    # Убираем префикс "ps." или подобные
                    text = re.sub(r'^(ps\.|p\.s\.)\s*', '', text, flags=re.I)
                    # Берем первые 2-3 предложения как заметки
                    sentences = re.split(r'\.\s+', text)[:3]
                    note_text = '. '.join(sentences)
                    if not note_text.endswith('.'):
                        note_text += '.'
                    return note_text.capitalize()
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта"""
        recipe_data = self._get_next_data()
        
        if not recipe_data or 'taxons' not in recipe_data:
            return None
        
        taxons = recipe_data['taxons']
        tags_set = set()  # Используем множество для избежания дубликатов
        
        if isinstance(taxons, dict):
            # Ищем в coolinarika-content-tags
            content_tags = taxons.get('coolinarika-content-tags', [])
            if content_tags and isinstance(content_tags, list):
                for tag in content_tags[:5]:  # Ограничиваем количество тегов
                    tag_title = tag.get('title', '')
                    if tag_title:
                        # Нормализуем тег (нижний регистр)
                        tag_normalized = tag_title.lower().strip()
                        tags_set.add(tag_normalized)
        
        # Преобразуем множество в отсортированный список
        tags_list = sorted(tags_set)
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        recipe_data = self._get_next_data()
        
        if not recipe_data:
            return None
        
        image_urls = []
        
        # Ищем основное изображение
        if 'image' in recipe_data and recipe_data['image']:
            image_data = recipe_data['image']
            if isinstance(image_data, dict) and 'id' in image_data:
                # ID изображения, но нужен URL
                # В web.coolinarika.com изображения обычно хранятся как ID
                # URL строится по шаблону
                image_id = image_data['id']
                # Пример URL: https://static.cdn.coolinarika.net/images/{id}/...
                # Но точный формат неизвестен, поэтому пропускаем
                pass
        
        # Ищем в списке изображений
        if 'images' in recipe_data and recipe_data['images']:
            images = recipe_data['images']
            if isinstance(images, list):
                for img in images[:3]:  # Берем до 3 изображений
                    if isinstance(img, dict) and 'id' in img:
                        # Аналогично, нужен URL, но есть только ID
                        pass
        
        # Так как точный URL неизвестен, возвращаем None
        # В реальной ситуации нужно было бы исследовать, как формируются URL
        return None
    
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
            "nutrition_info": self.extract_nutrition_info(),
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    """
    Точка входа для обработки HTML файлов из preprocessed/web_coolinarika_com
    """
    import os
    
    # Ищем директорию с HTML-страницами
    base_dir = Path(__file__).parent.parent
    recipes_dir = base_dir / "preprocessed" / "web_coolinarika_com"
    
    if recipes_dir.exists() and recipes_dir.is_dir():
        process_directory(WebCoolnarikaExtractor, str(recipes_dir))
    else:
        print(f"Директория не найдена: {recipes_dir}")


if __name__ == "__main__":
    main()
