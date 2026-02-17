"""
Экстрактор данных рецептов для сайта mummum.dk
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MummumDkExtractor(BaseRecipeExtractor):
    """Экстрактор для mummum.dk"""
    
    def __init__(self, html_path: str):
        """
        Args:
            html_path: Путь к HTML файлу
        """
        super().__init__(html_path)
        # Кешируем JSON-LD данные для избежания повторного парсинга
        self._json_ld_cache = None
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы (с кешированием)"""
        if self._json_ld_cache is not None:
            return self._json_ld_cache
        
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Проверяем что это Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    self._json_ld_cache = data
                    return data
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        self._json_ld_cache = {}  # Кешируем пустой результат
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
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
        
        # Форматируем результат
        if hours > 0 and minutes > 0:
            hour_text = "hour" if hours == 1 else "hours"
            minute_text = "minute" if minutes == 1 else "minutes"
            return f"{hours} {hour_text} and {minutes} {minute_text}"
        elif hours > 0:
            hour_text = "hour" if hours == 1 else "hours"
            return f"{hours} {hour_text}"
        elif minutes > 0:
            minute_text = "minute" if minutes == 1 else "minutes"
            return f"{minutes} {minute_text}"
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Альтернатива - из заголовка страницы
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
        # Альтернатива - из div с классом recipe-description
        desc_div = self.soup.find('div', class_='recipe-description')
        if desc_div:
            p = desc_div.find('p')
            if p:
                return self.clean_text(p.get_text())
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате списка словарей"""
        ingredients = []
        
        # Ищем ингредиенты в HTML структуре (более детальная информация чем в JSON-LD)
        # В mummum.dk ингредиенты находятся в <li class="components"> с тремя <span>
        ingredient_items = self.soup.find_all('li', class_='components')
        
        for item in ingredient_items:
            # Пропускаем заголовки секций (например "Dej", "Glasur")
            h4 = item.find('h4')
            if h4:
                continue
            
            # Извлекаем три span элемента: amount, unit, name
            spans = item.find_all('span')
            if len(spans) >= 3:
                amount = self.clean_text(spans[0].get_text())
                unit = self.clean_text(spans[1].get_text())
                name = self.clean_text(spans[2].get_text())
                
                # Очищаем единицу измерения от точки в конце
                if unit and unit.endswith('.'):
                    unit = unit[:-1]
                
                # Конвертируем amount в число или оставляем строку
                amount_value = None
                if amount:
                    try:
                        # Заменяем запятую на точку для европейских чисел
                        amount_normalized = amount.replace(',', '.')
                        amount_float = float(amount_normalized)
                        # Если это целое число, возвращаем int
                        amount_value = int(amount_float) if amount_float.is_integer() else amount_float
                    except ValueError:
                        # Если не удалось преобразовать, оставляем как есть
                        amount_value = amount
                
                ingredients.append({
                    "name": name,
                    "units": unit if unit else None,
                    "amount": amount_value
                })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            
            # В JSON-LD mummum.dk инструкции идут как одна строка с переносами
            if isinstance(instructions, str):
                # Разбиваем на шаги по переносу строки
                steps = [s.strip() for s in instructions.split('\n') if s.strip()]
                # Объединяем обратно в одну строку через пробел
                return ' '.join(steps)
            elif isinstance(instructions, list):
                steps = []
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        steps.append(self.clean_text(step['text']))
                    elif isinstance(step, str):
                        steps.append(self.clean_text(step))
                return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeCategory' in json_ld:
            category = json_ld['recipeCategory']
            # В mummum.dk категория часто на датском, переводим основные
            category_map = {
                'Søde sager': 'Dessert',
                'Forretter': 'Appetizer',
                'Hovedretter': 'Main Course',
                'Drikkevarer': 'Beverage',
                'Tilbehør': 'Side Dish',
                'Salater': 'Salad',
            }
            return category_map.get(category, category)
        
        # Альтернатива - из breadcrumbs
        breadcrumbs = self.soup.find('p', class_='breadcrumbs')
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            # Берем предпоследнюю ссылку (последняя это сам рецепт)
            if len(links) >= 2:
                category = self.clean_text(links[-1].get_text())
                category_map = {
                    'Søde sager': 'Dessert',
                    'Muffins': 'Dessert',
                    'Forretter': 'Appetizer',
                    'Hovedretter': 'Main Course',
                }
                return category_map.get(category, 'Dessert')
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # В mummum.dk заметки могут не всегда присутствовать в HTML
        # или могут быть добавлены вручную в базу данных
        # Поэтому возвращаем None если не находим явных заметок
        
        # Ищем параграфы с заметками (обычно содержат советы)
        note_keywords = [
            'kan erstattes', 'giver et ekstra', 'tip:', 'note:', 
            'husk at', 'kan også', 'anbefales', 'bemærk'
        ]
        
        # Извлекаем описание один раз для сравнения
        description = self.extract_description()
        
        # Ищем все параграфы в recipe-wrapper
        recipe_wrapper = self.soup.find('div', class_='recipe-wrapper')
        if recipe_wrapper:
            paragraphs = recipe_wrapper.find_all('p')
            for p in paragraphs:
                text = p.get_text(strip=True)
                # Проверяем если параграф содержит ключевые слова и это не описание
                for keyword in note_keywords:
                    if keyword.lower() in text.lower() and len(text) < 300:
                        cleaned_text = self.clean_text(text)
                        # Убеждаемся что это не описание рецепта
                        if description and cleaned_text != description:
                            return cleaned_text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из классов article"""
        tags = []
        
        # В mummum.dk теги закодированы в классах article элемента
        article = self.soup.find('article', class_='entry-container')
        if article:
            classes = article.get('class', [])
            
            for cls in classes:
                # Извлекаем теги из классов типа "diaeter-vegetar", "saeson-efteraar"
                if cls.startswith('diaeter-'):
                    tag = cls.replace('diaeter-', '')
                    # Переводим основные теги на английский
                    tag_map = {
                        'vegetar': 'vegetarian',
                        'veganer': 'vegan',
                    }
                    tags.append(tag_map.get(tag, tag))
                elif cls.startswith('saeson-'):
                    tag = cls.replace('saeson-', '')
                    tags.append(tag)
                elif cls.startswith('ingredienser-') and not cls.startswith('ingredienser-andet'):
                    # Игнорируем слишком детальные ингредиенты
                    continue
        
        # Также добавляем категории из breadcrumbs если есть
        breadcrumbs = self.soup.find('p', class_='breadcrumbs')
        if breadcrumbs:
            # Извлекаем все ссылки кроме "Forside" и "Opskrifter"
            links = breadcrumbs.find_all('a')
            for link in links:
                text = self.clean_text(link.get_text())
                if text and text not in ['Forside', 'Opskrifter']:
                    # Преобразуем в нижний регистр и добавляем
                    tag = text.lower()
                    if tag not in tags:
                        tags.append(tag)
        
        # Возвращаем как строку через запятую
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в JSON-LD
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
        
        # 2. Ищем в meta тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 3. Ищем главное изображение рецепта
        recipe_img = self.soup.find('img', class_=re.compile(r'recipe.*image', re.I))
        if recipe_img and recipe_img.get('src'):
            urls.append(recipe_img['src'])
        
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
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "mummum_dk")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(MummumDkExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python mummum_dk.py")


if __name__ == "__main__":
    main()
