"""
Экстрактор данных рецептов для сайта smachnoho.com.ua
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class SmachnohoExtractor(BaseRecipeExtractor):
    """Экстрактор для smachnoho.com.ua"""
    
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
        
        # Если минут больше 60 и нет часов, конвертируем в часы и минуты
        if minutes >= 60 and hours == 0:
            hours = minutes // 60
            minutes = minutes % 60
        
        # Форматируем результат
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем по microdata itemprop="name"
        name_elem = self.soup.find(attrs={'itemprop': 'name'})
        if name_elem:
            return self.clean_text(name_elem.get_text())
        
        # Альтернативно - из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Альтернативно - из заголовка h1
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем по microdata itemprop="description"
        desc_elem = self.soup.find(attrs={'itemprop': 'description'})
        if desc_elem and desc_elem.get('content'):
            return self.clean_text(desc_elem['content'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем все элементы с itemprop="recipeIngredient"
        ingredient_items = self.soup.find_all(attrs={'itemprop': 'recipeIngredient'})
        
        for item in ingredient_items:
            # Извлекаем имя ингредиента
            name_elem = item.find(class_='ingredients__name')
            name = None
            if name_elem:
                # Берем текст из ссылки или всего элемента
                link = name_elem.find('a')
                if link:
                    name = self.clean_text(link.get_text())
                else:
                    name = self.clean_text(name_elem.get_text())
            
            # Извлекаем количество и единицы
            count_elem = item.find(class_='ingredients__count')
            amount = None
            unit = None
            
            if count_elem:
                # Ищем элемент с data-count (число)
                data_count = count_elem.find(class_='js-ingredient-count')
                if data_count and data_count.get('data-count'):
                    amount = data_count.get('data-count')
                
                # Получаем весь текст и извлекаем единицы измерения
                count_text = self.clean_text(count_elem.get_text())
                
                # Убираем число из текста, чтобы получить единицы
                if amount:
                    unit_text = count_text.replace(amount, '').strip()
                    # Очищаем от nbsp и прочих символов
                    unit_text = unit_text.replace('\xa0', ' ').strip()
                    if unit_text:
                        unit = unit_text
                else:
                    # Если не нашли числовое значение, возможно это описательное количество
                    # типа "по вкусу" или "щепотка"
                    amount = count_text
                    unit = None
            
            # Если имя найдено, добавляем ингредиент
            if name:
                # Конвертируем amount в число, если это возможно
                amount_value = amount
                if amount and amount.isdigit():
                    amount_value = int(amount)
                elif amount:
                    try:
                        amount_value = float(amount)
                    except (ValueError, AttributeError):
                        pass  # Оставляем как строку
                
                ingredient_dict = {
                    "name": name,
                    "units": unit,  # используем "units" вместо "unit" как в примерах
                    "amount": amount_value
                }
                ingredients.append(ingredient_dict)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем все элементы с itemprop="recipeInstructions"
        instruction_items = self.soup.find_all(attrs={'itemprop': 'recipeInstructions'})
        
        for idx, item in enumerate(instruction_items, 1):
            # Ищем текст шага
            step_text_elem = item.find(class_='recipe-steps__text')
            if step_text_elem:
                step_text = self.clean_text(step_text_elem.get_text())
                if step_text:
                    # Добавляем нумерацию, если её нет
                    if not re.match(r'^\d+\.', step_text):
                        step_text = f"{idx}. {step_text}"
                    steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем по microdata itemprop="recipeCategory"
        cat_elem = self.soup.find(attrs={'itemprop': 'recipeCategory'})
        if cat_elem and cat_elem.get('content'):
            return self.clean_text(cat_elem['content'])
        
        # Альтернативно - из мета тега
        meta_cat = self.soup.find('meta', attrs={'itemprop': 'recipeCategory'})
        if meta_cat and meta_cat.get('content'):
            return self.clean_text(meta_cat['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На smachnoho.com.ua обычно только totalTime
        prep_elem = self.soup.find(attrs={'itemprop': 'prepTime'})
        if prep_elem and prep_elem.get('content'):
            iso_time = prep_elem.get('content')
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # На smachnoho.com.ua обычно только totalTime
        cook_elem = self.soup.find(attrs={'itemprop': 'cookTime'})
        if cook_elem and cook_elem.get('content'):
            iso_time = cook_elem.get('content')
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем по microdata itemprop="totalTime"
        time_elem = self.soup.find(attrs={'itemprop': 'totalTime'})
        if time_elem and time_elem.get('content'):
            iso_time = time_elem.get('content')
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями/советами
        # На smachnoho.com.ua обычно нет отдельных заметок
        notes_section = self.soup.find(class_=re.compile(r'notes?|tips?', re.I))
        
        if notes_section:
            text = self.clean_text(notes_section.get_text())
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Ищем по microdata itemprop="keywords"
        keywords_elem = self.soup.find(attrs={'itemprop': 'keywords'})
        if keywords_elem and keywords_elem.get('content'):
            keywords = keywords_elem.get('content')
            # Разделяем по запятой
            tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        # Альтернативно - из мета тега
        if not tags_list:
            meta_keywords = self.soup.find('meta', attrs={'itemprop': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                keywords = meta_keywords.get('content')
                tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем основное изображение в meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем изображения по microdata itemprop="image"
        image_elems = self.soup.find_all(attrs={'itemprop': 'image'})
        for img_elem in image_elems:
            # Может быть img тег
            if img_elem.name == 'img' and img_elem.get('src'):
                urls.append(img_elem['src'])
            # Или meta тег с content
            elif img_elem.get('content'):
                urls.append(img_elem['content'])
        
        # 3. Ищем изображения в шагах рецепта
        step_images = self.soup.find_all(class_='recipe-steps__photo')
        for step_img_div in step_images:
            img = step_img_div.find('img')
            if img and img.get('src'):
                src = img['src']
                # Пропускаем миниатюры, ищем полные изображения
                if 'http' in src and not any(x in src for x in ['-150x', '-300x', 'thumbnail']):
                    urls.append(src)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
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
            "nutrition_info": None,  # Добавляем поле nutrition_info (на smachnoho.com.ua обычно отсутствует)
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags()
        }


def main():
    """Обработка всех HTML файлов в директории preprocessed/smachnoho_com_ua"""
    import os
    
    # Определяем путь к директории с HTML файлами
    repo_root = Path(__file__).parent.parent
    preprocessed_dir = repo_root / "preprocessed" / "smachnoho_com_ua"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обработка файлов из директории: {preprocessed_dir}")
        process_directory(SmachnohoExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python smachnoho_com_ua.py")


if __name__ == "__main__":
    main()
