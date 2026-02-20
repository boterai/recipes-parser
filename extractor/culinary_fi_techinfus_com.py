"""
Экстрактор данных рецептов для сайта culinary-fi.techinfus.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CulinaryFiExtractor(BaseRecipeExtractor):
    """Экстрактор для culinary-fi.techinfus.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта h1.entry-title
        recipe_header = self.soup.find('h1', class_='entry-title')
        if recipe_header:
            return self.clean_text(recipe_header.get_text())
        
        # Альтернативно - из meta itemprop="name"
        meta_name = self.soup.find('meta', itemprop='name')
        if meta_name and meta_name.get('content'):
            return self.clean_text(meta_name['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из meta itemprop="description"
        meta_desc = self.soup.find('meta', itemprop='description')
        if meta_desc and meta_desc.get('content'):
            content = meta_desc['content']
            # Берем только первое предложение (до первой точки с последующим пробелом)
            first_sentence = re.split(r'\.\s+', content)[0]
            if first_sentence:
                return self.clean_text(first_sentence + '.')
        
        # Альтернативно - из meta name="description"
        meta_desc2 = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc2 and meta_desc2.get('content'):
            content = meta_desc2['content']
            # Берем только первое предложение
            first_sentence = re.split(r'\.\s+', content)[0]
            if first_sentence:
                return self.clean_text(first_sentence + '.')
        
        # Или из первого параграфа в entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            first_p = entry_content.find('p')
            if first_p:
                text = first_p.get_text(strip=True)
                # Берем только первое предложение
                first_sentence = re.split(r'\.\s+', text)[0]
                if first_sentence:
                    return self.clean_text(first_sentence + '.')
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем список ингредиентов
        ingredients_list = self.soup.find('ul', class_='ingredients-list')
        
        if ingredients_list:
            # Извлекаем каждый ингредиент
            items = ingredients_list.find_all('li', class_='ingredient')
            
            for item in items:
                # Извлекаем название
                name_elem = item.find('span', class_='ingredients__name')
                name = self.clean_text(name_elem.get_text()) if name_elem else None
                
                # Извлекаем количество и единицу
                count_container = item.find('span', class_='ingredients__count')
                amount = None
                unit = None
                
                if count_container:
                    # Извлекаем количество (из span.value или data-count)
                    count_elem = count_container.find('span', class_='value')
                    if count_elem:
                        amount_text = count_elem.get('data-count') or count_elem.get_text(strip=True)
                        if amount_text and amount_text.strip():
                            try:
                                amount = float(amount_text) if '.' in amount_text else int(amount_text)
                            except (ValueError, TypeError):
                                amount = None
                    
                    # Извлекаем единицу измерения
                    unit_elem = count_container.find('span', class_='type')
                    if unit_elem:
                        unit_text = unit_elem.get_text(strip=True)
                        # Убираем скобки, если есть
                        unit = re.sub(r'[()]', '', unit_text).strip()
                        if not unit:
                            unit = None
                
                if name:
                    ingredient = {
                        "name": name,
                        "amount": amount,
                        "units": unit  # Используем "units" согласно примеру JSON
                    }
                    ingredients.append(ingredient)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем список инструкций
        instructions_container = self.soup.find('ol', itemprop='recipeInstructions')
        
        if instructions_container:
            # Извлекаем шаги
            step_items = instructions_container.find_all('li', class_='instruction')
            
            for item in step_items:
                # Извлекаем текст инструкции из div.recipe-steps__text
                step_text_elem = item.find('div', class_='recipe-steps__text')
                if step_text_elem:
                    step_text = step_text_elem.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    
                    if step_text:
                        steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем из meta itemprop="recipeCategory"
        meta_category = self.soup.find('meta', itemprop='recipeCategory')
        if meta_category and meta_category.get('content'):
            return self.clean_text(meta_category['content'])
        
        # Или из meta itemprop="recipeCuisine"
        meta_cuisine = self.soup.find('meta', itemprop='recipeCuisine')
        if meta_cuisine and meta_cuisine.get('content'):
            return self.clean_text(meta_cuisine['content'])
        
        # Или из breadcrumbs (последний элемент перед рецептом)
        breadcrumbs = self.soup.find('div', class_='breadcrumb')
        if breadcrumbs:
            items = breadcrumbs.find_all('span', itemprop='name')
            if len(items) > 1:  # Берем последний элемент (не "Koti")
                return self.clean_text(items[-1].get_text())
        
        return None
    
    def extract_time_from_meta(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени из meta-тегов или HTML
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Ищем в meta-тегах
        if time_type == 'total':
            # Ищем itemprop="totalTime"
            time_elem = self.soup.find(itemprop='totalTime')
            if time_elem:
                # Может быть в атрибуте content или в тексте
                time_value = time_elem.get('content') or time_elem.get_text(strip=True)
                if time_value:
                    # Конвертируем из ISO формата (PT140M) в минуты
                    if time_value.startswith('PT'):
                        return self.parse_iso_duration(time_value)
                    return self.clean_text(time_value)
        
        # Ищем в meta-cooking-time span
        cooking_time_spans = self.soup.find_all('span', class_='meta-cooking-time')
        for span in cooking_time_spans:
            time_elem = span.find(itemprop='totalTime')
            if time_elem:
                time_value = time_elem.get('content') or time_elem.get_text(strip=True)
                if time_value:
                    if time_value.startswith('PT'):
                        return self.parse_iso_duration(time_value)
                    return self.clean_text(time_value)
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах с текстом, например "90 minutes"
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
        
        # Конвертируем все в минуты
        total_minutes = hours * 60 + minutes
        
        if total_minutes > 0:
            return f"{total_minutes} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки
        
        Note: Данный сайт не предоставляет отдельное prep_time в HTML,
        возвращаем None согласно требованиям (если не найдено, должно быть None)
        """
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # На этом сайте cook_time = total_time
        return self.extract_time_from_meta('total')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time_from_meta('total')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # На этом сайте нет явной секции с заметками
        # Можно попробовать найти специальные блоки, но пока возвращаем None
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из классов article или meta-тегов"""
        tags_list = []
        
        # Ищем article элемент
        article = self.soup.find('article')
        if article and article.get('class'):
            classes = article['class']
            
            # Извлекаем классы ingredients-* (это ингредиенты-теги)
            for cls in classes:
                if isinstance(cls, str) and cls.startswith('ingredients-'):
                    # Убираем префикс "ingredients-"
                    tag = cls.replace('ingredients-', '').replace('-', ' ')
                    if tag and len(tag) > 2:
                        tags_list.append(tag)
        
        # Также добавляем категорию как тег
        category = self.extract_category()
        if category:
            # Переводим категорию в английский формат для совместимости
            category_lower = category.lower()
            if 'toiset kurssit' in category_lower or 'second' in category_lower:
                tags_list.insert(0, 'main course')
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags_list:
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen.add(tag_lower)
                unique_tags.append(tag_lower)
        
        # Возвращаем как строку через запятую с пробелом
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем главное изображение результата (result_photo_image)
        main_img = self.soup.find('img', class_='result_photo_image')
        if main_img and main_img.get('src'):
            urls.append(main_img['src'])
        
        # 2. Ищем изображения в шагах рецепта (опционально, первые несколько)
        steps_container = self.soup.find('ol', itemprop='recipeInstructions')
        if steps_container:
            step_images = steps_container.find_all('img', class_='photo', limit=3)
            for img in step_images:
                # Берем полноразмерное изображение из родительской ссылки
                parent_link = img.find_parent('a')
                if parent_link and parent_link.get('href'):
                    img_url = parent_link['href']
                    if img_url not in urls:
                        urls.append(img_url)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        # Возвращаем как строку через запятую без пробелов
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
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """
    Точка входа для обработки HTML-файлов из директории preprocessed/culinary-fi_techinfus_com
    """
    import os
    
    # Определяем путь к директории с HTML-файлами
    repo_root = Path(__file__).parent.parent
    preprocessed_dir = repo_root / "preprocessed" / "culinary-fi_techinfus_com"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(CulinaryFiExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python culinary-fi_techinfus_com.py")


if __name__ == "__main__":
    main()
