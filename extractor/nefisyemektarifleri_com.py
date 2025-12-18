"""
Экстрактор данных рецептов для сайта nefisyemektarifleri.com (site_id = 6)
Турецкий сайт рецептов
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class NefisYemekTarifleriExtractor(BaseRecipeExtractor):
    """Экстрактор для nefisyemektarifleri.com"""
    
    def __init__(self, html_path: str):
        """
        Инициализация экстрактора для nefisyemektarifleri.com
        
        Args:
            html_path: Путь к HTML файлу
        """
        super().__init__(html_path)
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Извлекаем из HTML
        recipe_header = self.soup.find('h1', class_='recipe-name')
        if recipe_header:
            return self.clean_text(recipe_header.get_text())
        
        # Альтернатива - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффикс " - Nefis Yemek Tarifleri"
            title = re.sub(r'\s+-\s+Nefis.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Извлекаем из HTML meta tags
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате JSON из HTML"""
        # Ищем ингредиенты в HTML
        ingredients_ul = self.soup.find('ul', class_='recipe-materials')
        if ingredients_ul:
            ingredients = []
            for li in ingredients_ul.find_all('li', itemprop='recipeIngredient'):
                ingredient_text = self.clean_text(li.get_text())
                if ingredient_text:
                    ingredients.append({
                        'name': ingredient_text,
                        'amount': None,
                        'unit': None
                    })
            
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления из HTML"""
        # Ищем инструкции в HTML
        instructions_ol = self.soup.find('ol', class_='recipe-instructions')
        if instructions_ol:
            steps = []
            for idx, li in enumerate(instructions_ol.find_all('li'), 1):
                step_text = self.clean_text(li.get_text())
                if step_text:
                    # Удаляем переносы строк и заменяем на пробелы
                    step_text = step_text.replace('\n', ' ').strip()
                    steps.append(f"{idx}. {step_text}")
            
            if steps:
                return ' '.join(steps)
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта из HTML"""
        # Извлекаем из breadcrumbs
        breadcrumb = self.soup.find('div', id='breadcrumb')
        if breadcrumb:
            items = breadcrumb.find_all('span', itemprop='name')
            if len(items) > 1:  # Берем предпоследний элемент (последний - название рецепта)
                return self.clean_text(items[-2].get_text())
        
        # Альтернатива: ищем в тегах
        tags_div = self.soup.find('div', class_='tags')
        if tags_div:
            tag_links = tags_div.find_all('a', class_='tag')
            if tag_links:
                return self.clean_text(tag_links[0].get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта из HTML"""
        # Ищем теги в div.tags
        tags_div = self.soup.find('div', class_='tags')
        if tags_div:
            tag_links = tags_div.find_all('a', class_='tag')
            if tag_links:
                tag_list = [self.clean_text(link.get_text()) for link in tag_links]
                return ', '.join(tag_list)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем в meta-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # Убираем дубликаты, берем первые 3
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
                    if len(unique_urls) >= 3:
                        break
            return ', '.join(unique_urls) if unique_urls else None
        
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
        instructions = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name.lower() if dish_name else None,
            "description": description.lower() if description else None,
            "ingredients": ingredients,
            "instructions": instructions.lower() if instructions else None,
            "nutrition_info": self.extract_nutrition_info(),
            "category": category.lower() if category else None,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes.lower() if notes else None,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }



def main():
    import os
    # По умолчанию обрабатываем папку recipes/nefisyemektarifleri_com
    recipes_dir = os.path.join("recipes", "nefisyemektarifleri_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(NefisYemekTarifleriExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python nefisyemektarifleri_com.py [путь_к_файлу_или_директории]")


if __name__ == "__main__":
    main()
