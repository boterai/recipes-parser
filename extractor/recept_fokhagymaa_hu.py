"""
Экстрактор данных рецептов для сайта recept.fokhagymaa.hu
"""

import sys
from pathlib import Path
import json
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ReceptFokhagymaExtractor(BaseRecipeExtractor):
    """Экстрактор для recept.fokhagymaa.hu"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем элемент с классом wprm-recipe-name
        dish_name = self.soup.find(class_='wprm-recipe-name')
        if dish_name:
            return self.clean_text(dish_name.get_text())
        
        # Альтернативно - в h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала извлекаем название блюда для использования в паттернах
        dish_name = self.extract_dish_name()
        
        # Проверяем og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc_text = og_desc['content']
            import re
            
            # Вариант 1: Есть "–" (тире)
            # "Házi croissant recept – Francia péksütemény... Croissant recept hozzávalók"
            # Извлекаем все до повторного упоминания названия блюда + "recept hozzávalók"
            if ' – ' in desc_text:
                parts = desc_text.split(' – ', 1)
                prefix = parts[0]  # "Házi croissant recept"
                rest = parts[1]     # "Francia... Croissant recept hozzávalók"
                
                # Используем название блюда для точного определения конца описания
                if dish_name:
                    pattern = fr'(.+?)\s+{re.escape(dish_name)}\s+recept\s+hozzávalók'
                    match = re.search(pattern, rest, re.IGNORECASE)
                    if match:
                        desc_part = match.group(1).strip()
                        return self.clean_text(f"{prefix} – {desc_part}.")
                
                # Если не получилось с именем блюда, просто берем до " recept hozzávalók"
                match = re.search(r'(.+?)\s+recept\s+hozzávalók', rest, re.IGNORECASE)
                if match:
                    desc_part = match.group(1).strip()
                    return self.clean_text(f"{prefix} – {desc_part}.")
            
            # Вариант 2: Нет тире, описание начинается сразу
            # "Puha, ízes... Gazdag ír szódás kenyér recept hozzávalók"
            # Используем название блюда если есть
            if dish_name:
                pattern = fr'^(.+?)\s+{re.escape(dish_name)}\s+recept\s+hozzávalók'
                match = re.search(pattern, desc_text, re.IGNORECASE)
                if match:
                    return self.clean_text(match.group(1) + '.')
            
            # Берем все до "recept hozzávalók"
            match = re.search(r'^(.+?)\s+recept\s+hozzávalók', desc_text, re.IGNORECASE)
            if match:
                return self.clean_text(match.group(1) + '.')
        
        # Альтернативно - ищем в summary
        summary = self.soup.find('div', class_='wprm-recipe-summary')
        if summary:
            return self.clean_text(summary.get_text())
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем список ингредиентов с классом wprm-recipe-ingredient
        ingredient_items = self.soup.find_all('li', class_='wprm-recipe-ingredient')
        
        for item in ingredient_items:
            # Извлекаем amount, unit, name из span элементов
            amount_span = item.find('span', class_='wprm-recipe-ingredient-amount')
            unit_span = item.find('span', class_='wprm-recipe-ingredient-unit')
            name_span = item.find('span', class_='wprm-recipe-ingredient-name')
            
            # Извлекаем значения
            amount = None
            if amount_span:
                amount_text = self.clean_text(amount_span.get_text())
                # Преобразуем в число если возможно
                try:
                    amount = float(amount_text.replace(',', '.'))
                    # Если это целое число, конвертируем в int
                    if amount.is_integer():
                        amount = int(amount)
                except (ValueError, AttributeError):
                    amount = amount_text if amount_text else None
            
            unit = None
            if unit_span:
                unit = self.clean_text(unit_span.get_text())
            
            name = None
            if name_span:
                name = self.clean_text(name_span.get_text())
            
            # Проверяем наличие примечания в атрибуте data-notes
            note = item.get('data-notes')
            
            # Формируем объект ингредиента
            ingredient_obj = {
                "name": name,
                "units": unit,  # Используем 'units' как в эталонном JSON
                "amount": amount
            }
            
            # Добавляем примечание если есть
            if note:
                ingredient_obj["note"] = self.clean_text(note)
            
            # Добавляем только если есть хотя бы name
            if name:
                ingredients.append(ingredient_obj)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions = []
        
        # Ищем все div с классом wprm-recipe-instruction-text
        instruction_divs = self.soup.find_all('div', class_='wprm-recipe-instruction-text')
        
        for div in instruction_divs:
            text = self.clean_text(div.get_text())
            if text:
                instructions.append(text)
        
        # Объединяем все инструкции в одну строку с пробелами
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем span с классом wprm-recipe-course
        course = self.soup.find('span', class_='wprm-recipe-course')
        if course:
            return self.clean_text(course.get_text())
        
        return None
    
    def extract_time(self, time_class: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_class: Класс элемента времени ('wprm-recipe-prep_time', etc.)
        """
        time_elem = self.soup.find('span', class_=time_class)
        if time_elem:
            return self.clean_text(time_elem.get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('wprm-recipe-prep_time')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('wprm-recipe-cook_time')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('wprm-recipe-total_time')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем div с классом wprm-recipe-notes
        notes_section = self.soup.find('div', class_='wprm-recipe-notes')
        
        if notes_section:
            text = self.clean_text(notes_section.get_text())
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов (keywords)"""
        # Ищем span с классом wprm-recipe-keyword
        keywords = self.soup.find('span', class_='wprm-recipe-keyword')
        
        if keywords:
            # Получаем текст и разбиваем по запятым
            tags_text = self.clean_text(keywords.get_text())
            if tags_text:
                # Разбиваем по запятым, очищаем и фильтруем
                tags_list = [tag.strip() for tag in tags_text.split(',')]
                tags_list = [tag for tag in tags_list if tag]
                
                # Возвращаем как строку через запятую с пробелом
                return ', '.join(tags_list)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем изображение рецепта в div с классом wprm-recipe-image
        recipe_image_div = self.soup.find('div', class_='wprm-recipe-image')
        if recipe_image_div:
            img_tag = recipe_image_div.find('img')
            if img_tag and img_tag.get('src'):
                urls.append(img_tag['src'])
        
        # 2. Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            # Возвращаем как строку через запятую без пробелов
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
    # Обрабатываем папку preprocessed/recept_fokhagymaa_hu
    recipes_dir = os.path.join("preprocessed", "recept_fokhagymaa_hu")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(ReceptFokhagymaExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python recept_fokhagymaa_hu.py")


if __name__ == "__main__":
    main()
