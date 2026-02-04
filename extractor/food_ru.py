"""
Экстрактор данных рецептов для сайта food.ru
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class FoodRuExtractor(BaseRecipeExtractor):
    """Экстрактор для food.ru"""
    
    def __init__(self, html_path: str):
        """
        Args:
            html_path: Путь к HTML файлу
        """
        super().__init__(html_path)
        self._recipe_data = None
        self._load_recipe_data()
    
    def _load_recipe_data(self):
        """Загрузка данных рецепта из __NEXT_DATA__"""
        try:
            # Ищем скрипт с __NEXT_DATA__
            next_data_script = self.soup.find('script', id='__NEXT_DATA__')
            if not next_data_script:
                return
            
            # Парсим JSON
            next_data = json.loads(next_data_script.string)
            
            # Получаем Effector state
            effector = next_data.get('props', {}).get('pageProps', {}).get('__EFFECTOR_NEXTJS_INITIAL_STATE__', {})
            
            # Ищем объект рецепта (содержит title, main_ingredients_block, cooking, tags и т.д.)
            for key, val in effector.items():
                if isinstance(val, dict) and 'title' in val and 'main_ingredients_block' in val:
                    self._recipe_data = val
                    break
                    
        except Exception as e:
            print(f"Ошибка при загрузке данных рецепта: {e}")
            self._recipe_data = None
    
    @staticmethod
    def _extract_text_from_document(doc) -> str:
        """
        Извлечение текста из структуры document (используемой в food.ru)
        
        Args:
            doc: Словарь с полями type, children, content
            
        Returns:
            Извлеченный текст
        """
        if not isinstance(doc, dict):
            return str(doc)
        
        if doc.get('type') == 'text':
            return doc.get('content', '')
        
        if 'children' in doc:
            texts = []
            for child in doc['children']:
                text = FoodRuExtractor._extract_text_from_document(child)
                if text:
                    texts.append(text)
            return ' '.join(texts)
        
        return ''
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        if self._recipe_data and 'title' in self._recipe_data:
            return self.clean_text(self._recipe_data['title'])
        
        # Fallback: ищем в h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Используем seo_title как описание
        if self._recipe_data and 'seo_title' in self._recipe_data:
            seo_title = self._recipe_data['seo_title']
            if seo_title:
                description = self.clean_text(seo_title)
                # Добавляем точку в конце, если её нет
                if description and not description.endswith('.'):
                    description += '.'
                return description
        
        # Fallback: meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            description = self.clean_text(meta_desc['content'])
            if description and not description.endswith('.'):
                description += '.'
            return description
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов
        
        Returns:
            JSON-строка с массивом ингредиентов в формате 
            [{"name": "...", "units": "...", "amount": ...}, ...]
        """
        if not self._recipe_data:
            return None
        
        ingredients = []
        
        # Извлекаем основные ингредиенты
        main_block = self._recipe_data.get('main_ingredients_block', {})
        if main_block and 'products' in main_block:
            for product in main_block['products']:
                ingredient = {
                    'name': product.get('title', ''),
                    'units': product.get('custom_measure', ''),
                    'amount': product.get('custom_measure_count', 0)
                }
                ingredients.append(ingredient)
        
        # Извлекаем опциональные ингредиенты (если есть)
        optional_blocks = self._recipe_data.get('optional_ingredients_blocks', [])
        if optional_blocks:
            for block in optional_blocks:
                if 'products' in block:
                    for product in block['products']:
                        ingredient = {
                            'name': product.get('title', ''),
                            'units': product.get('custom_measure', ''),
                            'amount': product.get('custom_measure_count', 0)
                        }
                        ingredients.append(ingredient)
        
        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        if not self._recipe_data:
            return None
        
        instructions = []
        
        # Сначала добавляем preparation шаг (если есть)
        preparation = self._recipe_data.get('preparation', [])
        if preparation:
            for step in preparation:
                if 'description' in step:
                    text = self._extract_text_from_document(step['description'])
                    if text:
                        instructions.append(text)
        
        # Затем добавляем cooking шаги
        cooking = self._recipe_data.get('cooking', [])
        if cooking:
            for step in cooking:
                if 'description' in step:
                    text = self._extract_text_from_document(step['description'])
                    if text:
                        instructions.append(text)
        
        # Добавляем impression шаги (финальная подача)
        impression = self._recipe_data.get('impression', [])
        if impression:
            for step in impression:
                if 'description' in step:
                    text = self._extract_text_from_document(step['description'])
                    if text:
                        instructions.append(text)
        
        # Форматируем как пронумерованный список
        if instructions:
            numbered = [f"{i+1}. {text}" for i, text in enumerate(instructions)]
            return ' '.join(numbered)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        if not self._recipe_data:
            return None
        
        # Проверяем поле dishes
        dishes = self._recipe_data.get('dishes', [])
        if dishes and isinstance(dishes, list) and len(dishes) > 0:
            if isinstance(dishes[0], dict):
                return dishes[0].get('title', None)
            return str(dishes[0])
        
        # Проверяем breadcrumbs (самый надежный источник категории)
        breadcrumbs = self._recipe_data.get('breadcrumbs', [])
        if breadcrumbs and isinstance(breadcrumbs, list):
            # Берем последний элемент (самая специфичная категория)
            last_crumb = breadcrumbs[-1]
            if isinstance(last_crumb, dict):
                title = last_crumb.get('title', '')
                if title:
                    # Первая буква заглавная
                    return title.capitalize()
        
        # Fallback: проверяем tags на предмет категорий
        tags = self._recipe_data.get('tags', [])
        if tags and isinstance(tags, list):
            # Ищем теги с короткими названиями (вероятно категории)
            for tag in tags:
                if isinstance(tag, dict):
                    title = tag.get('title', '')
                    # Простая эвристика: короткие теги часто являются категориями
                    if title and len(title) < 30 and not title.startswith('в «'):
                        # Проверяем, что это не временной тег или служебный
                        if not any(word in title.lower() for word in ['минут', 'партнерск', 'вкус']):
                            # Возвращаем первый подходящий
                            return title.capitalize()
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # food.ru не разделяет prep_time и cook_time, используется active_cooking_time
        # Возвращаем None, так как отдельного prep_time нет
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        if not self._recipe_data:
            return None
        
        # Используем active_cooking_time
        active_time = self._recipe_data.get('active_cooking_time')
        if active_time:
            return f"{active_time} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        if not self._recipe_data:
            return None
        
        # Используем total_cooking_time
        total_time = self._recipe_data.get('total_cooking_time')
        if total_time:
            return f"{total_time} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение дополнительных заметок"""
        if not self._recipe_data:
            return None
        
        # Используем more_healthy как notes
        more_healthy = self._recipe_data.get('more_healthy')
        if more_healthy:
            text = self._extract_text_from_document(more_healthy)
            if text:
                return self.clean_text(text)
        
        # Также можно использовать more_varied
        more_varied = self._recipe_data.get('more_varied')
        if more_varied:
            text = self._extract_text_from_document(more_varied)
            if text:
                return self.clean_text(text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        if not self._recipe_data:
            return None
        
        tags = self._recipe_data.get('tags', [])
        if tags:
            tag_titles = []
            for tag in tags:
                if isinstance(tag, dict):
                    title = tag.get('title', '')
                    if title:
                        tag_titles.append(title)
            
            if tag_titles:
                # Фильтруем теги (убираем партнерские проекты)
                filtered_tags = [t for t in tag_titles if not any(
                    keyword in t.lower() 
                    for keyword in ['перекр', 'пятёрочк', 'партнерск', 'в «']
                )]
                
                # Если после фильтрации осталось мало тегов, возвращаем все
                if len(filtered_tags) < 3:
                    filtered_tags = tag_titles
                
                return ', '.join(filtered_tags[:10])  # Ограничиваем количество тегов
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        if not self._recipe_data:
            return None
        
        image_urls = []
        base_url = "https://food.ru/"
        
        # Добавляем обложку
        cover = self._recipe_data.get('cover', {})
        if cover and 'image_path' in cover:
            image_path = cover['image_path']
            if image_path:
                # Формируем полный URL
                if not image_path.startswith('http'):
                    image_path = base_url + image_path
                image_urls.append(image_path)
        
        # Добавляем изображения из preparation
        preparation = self._recipe_data.get('preparation', [])
        for step in preparation:
            if 'image_path' in step and step['image_path']:
                image_path = step['image_path']
                if not image_path.startswith('http'):
                    image_path = base_url + image_path
                if image_path not in image_urls:
                    image_urls.append(image_path)
        
        # Добавляем изображения из cooking
        cooking = self._recipe_data.get('cooking', [])
        for step in cooking:
            if 'image_path' in step and step['image_path']:
                image_path = step['image_path']
                if not image_path.startswith('http'):
                    image_path = base_url + image_path
                if image_path not in image_urls:
                    image_urls.append(image_path)
        
        # Добавляем изображения из impression
        impression = self._recipe_data.get('impression', [])
        for step in impression:
            if 'image_path' in step and step['image_path']:
                image_path = step['image_path']
                if not image_path.startswith('http'):
                    image_path = base_url + image_path
                if image_path not in image_urls:
                    image_urls.append(image_path)
        
        if image_urls:
            return ','.join(image_urls)
        
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
    """Точка входа для обработки HTML-страниц food.ru"""
    import os
    
    # Ищем директорию с preprocessed данными
    preprocessed_dir = os.path.join("preprocessed", "food_ru")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(FoodRuExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python food_ru.py")


if __name__ == "__main__":
    main()
