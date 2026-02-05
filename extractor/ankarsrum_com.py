"""
Экстрактор данных рецептов для сайта ankarsrum.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class AnkarsrumExtractor(BaseRecipeExtractor):
    """Экстрактор для ankarsrum.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из microdata
        name_elem = self.soup.find(attrs={'itemprop': 'name'})
        if name_elem:
            return self.clean_text(name_elem.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем через microdata
        desc_elem = self.soup.find(attrs={'itemprop': 'description'})
        if desc_elem:
            return self.clean_text(desc_elem.get_text())
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Dict[str, Any]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: текст ингредиента, например "500 g durumvehnäjauhoja"
            
        Returns:
            Словарь с полями name, units, amount (порядок важен для совместимости)
        """
        # Паттерн для парсинга: количество + единица + название
        # Примеры:
        # "500 g durumvehnäjauhoja"
        # "7 kananmunaa"
        # "3,5 rkl neutraalia öljyä"
        
        ingredient_text = ingredient_text.strip()
        if not ingredient_text:
            return None
        
        # Паттерн: число (с возможной запятой/точкой) + пробел + единица измерения (опционально) + название
        pattern = r'^([\d,.½]+)\s*([a-zA-ZäöüÄÖÜ]*)\s+(.+)$'
        match = re.match(pattern, ingredient_text)
        
        if match:
            amount_str = match.group(1).replace(',', '.')  # Заменяем запятую на точку
            # Handle ½ character
            if '½' in amount_str:
                amount_str = amount_str.replace('½', '0.5')
            
            unit = match.group(2) if match.group(2) else None
            name = match.group(3).strip()
            
            # Преобразуем количество в число, если возможно
            try:
                amount = float(amount_str) if '.' in amount_str else int(amount_str)
            except (ValueError, AttributeError):
                amount = amount_str
            
            # Нормализуем единицы измерения
            unit_map = {
                'g': 'g',
                'kg': 'kg',
                'ml': 'ml',
                'l': 'liter',
                'dl': 'dl',
                'rkl': 'tablespoons',
                'tl': 'teaspoons',
                'teaspoon': 'teaspoon',
                'teaspoons': 'teaspoons',
                'tablespoon': 'tablespoon',
                'tablespoons': 'tablespoons',
                'pcs': 'pcs',
                'pieces': 'pieces',
                'mm': 'mm',
                'grams': 'grams',
                'liter': 'liter',
            }
            
            if unit:
                unit = unit_map.get(unit.lower(), unit)
            
            # Return in specific order: name, units, amount
            return {
                "name": name,
                "units": unit,
                "amount": amount
            }
        else:
            # Если паттерн не подошел, возвращаем как есть без количества и единиц
            return {
                "name": ingredient_text,
                "units": None,
                "amount": None
            }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем элементы с microdata itemprop="recipeIngredient"
        ingredient_elements = self.soup.find_all(attrs={'itemprop': 'recipeIngredient'})
        
        for elem in ingredient_elements:
            ingredient_text = elem.get_text(separator=' ', strip=True)
            ingredient_text = self.clean_text(ingredient_text)
            
            if ingredient_text:
                # Парсим в структурированный формат
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        # Если не нашли через microdata, ищем через класс
        if not ingredients:
            ingredients_div = self.soup.find('div', class_='recipe-ingredients')
            if ingredients_div:
                items = ingredients_div.find_all(['li', 'p'])
                for item in items:
                    ingredient_text = item.get_text(separator=' ', strip=True)
                    ingredient_text = self.clean_text(ingredient_text)
                    
                    if ingredient_text:
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        instructions = []
        
        # Сначала пробуем извлечь из microdata
        instruction_elements = self.soup.find_all(attrs={'itemprop': 'recipeInstructions'})
        
        for elem in instruction_elements:
            text = elem.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            if text and text not in instructions:
                instructions.append(text)
        
        # Если не нашли через microdata, ищем через класс
        if not instructions:
            instructions_div = self.soup.find('div', class_='recipe-instructions')
            if instructions_div:
                # Ищем все элементы step
                steps = instructions_div.find_all(attrs={'itemprop': 'step'})
                for step in steps:
                    text = step.get_text(separator=' ', strip=True)
                    text = self.clean_text(text)
                    if text and text not in instructions:
                        instructions.append(text)
        
        # Объединяем все инструкции в одну строку
        if instructions:
            # Удаляем дубликаты, сохраняя порядок
            seen = set()
            unique_instructions = []
            for instr in instructions:
                if instr not in seen:
                    seen.add(instr)
                    unique_instructions.append(instr)
            return ' '.join(unique_instructions)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Ищем через microdata
        category_elem = self.soup.find(attrs={'itemprop': 'recipeCategory'})
        if category_elem:
            category = self.clean_text(category_elem.get_text())
            # Нормализуем категорию (переводим финские названия на английский)
            category_map = {
                'pasta': 'Main Course',
                'ruoat': 'Main Course',  # Finnish: "Foods"
                'pääruoat': 'Main Course',  # Finnish: "Main Dishes"
            }
            if category:
                normalized = category_map.get(category.lower())
                if normalized:
                    return normalized
                return category
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """
        Извлечение времени подготовки
        
        На сайте ankarsrum.com время может быть не указано явно в HTML,
        но есть в инструкциях. Ищем паттерны типа "30 minuuttia" в тексте.
        """
        # Ищем через microdata
        prep_time_elem = self.soup.find(attrs={'itemprop': 'prepTime'})
        if prep_time_elem:
            content = prep_time_elem.get('content')
            if content:
                # Парсим ISO duration
                return self._parse_iso_duration(content)
            text = prep_time_elem.get_text().strip()
            if text:
                return text
        
        # Если не нашли, попробуем найти в инструкциях
        instructions = self.extract_instructions()
        if instructions:
            # Ищем паттерны типа "levätä 30 minuuttia" или "vähintään 30 minuuttia"
            # Это обычно время подготовки/отдыха теста
            prep_pattern = r'(?:lev\u00e4t\u00e4)\s+.*?(\d+)\s*min'
            matches = re.findall(prep_pattern, instructions, re.IGNORECASE)
            if matches:
                # Берем максимальное значение (обычно самое длинное время отдыха)
                max_time = max(int(m) for m in matches)
                return f"{max_time} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем через microdata
        cook_time_elem = self.soup.find(attrs={'itemprop': 'cookTime'})
        if cook_time_elem:
            content = cook_time_elem.get('content')
            if content:
                return self._parse_iso_duration(content)
            text = cook_time_elem.get_text().strip()
            if text:
                return text
        
        # Если не нашли, попробуем найти в инструкциях последнее упоминание времени готовки
        instructions = self.extract_instructions()
        if instructions:
            # Ищем паттерны типа "20–25 minuuttia" или "8 minuuttia" или "30 sekuntia"
            # Ищем последние упоминания (ближе к концу текста)
            cook_patterns = [
                (r'[Pp]aista.*?(\d+)(?:[–-](\d+))?\s*min', 'minutes'),  # Paista 20-25 minuuttia
                (r'[Kk]eit\u00e4.*?(\d+)(?:[–-](\d+))?\s*min', 'minutes'),  # Keitä 5 minuuttia
                (r'[Kk]eit\u00e4.*?(\d+)\s*sek', 'seconds'),  # Keitä 30 sekuntia
                (r'[Hh]\u00f6yryt\u00e4.*?(\d+)\s*min', 'minutes'),  # Höyrytä 8 minuuttia
            ]
            
            all_matches = []
            for pattern, unit in cook_patterns:
                for match in re.finditer(pattern, instructions):
                    # Get position and time value
                    pos = match.start()
                    time1 = int(match.group(1))
                    time2 = int(match.group(2)) if match.lastindex >= 2 and match.group(2) else None
                    # Use the higher value for ranges
                    time = time2 if time2 else time1
                    all_matches.append((pos, time, unit))
            
            if all_matches:
                # Sort by position and take the last one (usually the final cooking step)
                all_matches.sort(key=lambda x: x[0])
                _, time, unit = all_matches[-1]
                
                if unit == 'minutes':
                    return f"{time} minutes"
                else:
                    return f"{time} {unit}"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем через microdata
        total_time_elem = self.soup.find(attrs={'itemprop': 'totalTime'})
        if total_time_elem:
            content = total_time_elem.get('content')
            if content:
                return self._parse_iso_duration(content)
            text = total_time_elem.get_text().strip()
            if text:
                return text
        
        # Если есть prep_time и cook_time, можем вычислить total_time
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        
        if prep_time and cook_time:
            # Извлекаем числа из строк
            prep_match = re.search(r'\d+', prep_time)
            cook_match = re.search(r'\d+', cook_time)
            
            if prep_match and cook_match:
                prep_num = int(prep_match.group())
                cook_num = int(cook_match.group())
                total = prep_num + cook_num
                return f"{total} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок к рецепту"""
        # На ankarsrum.com обычно нет отдельного поля для заметок
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта"""
        # Ищем meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords.get('content')
            return self.clean_text(keywords)
        
        # Альтернативно - из названия блюда и категории можем сформировать теги
        dish_name = self.extract_dish_name()
        category = self.extract_category()
        
        tags = []
        if dish_name:
            # Извлекаем ключевые слова из названия
            words = dish_name.lower().split()
            # Фильтруем короткие слова
            keywords_from_name = [w for w in words if len(w) > 3]
            tags.extend(keywords_from_name[:3])  # Берем до 3 ключевых слов
        
        if category and category not in tags:
            tags.append(category.lower())
        
        # Если ничего не нашли, возвращаем None
        if not tags:
            return None
        
        return ', '.join(tags)
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        images = []
        
        # Ищем через microdata
        image_elements = self.soup.find_all(attrs={'itemprop': 'image'})
        
        for elem in image_elements:
            # Проверяем разные атрибуты
            img_url = elem.get('src') or elem.get('content') or elem.get('href')
            if img_url and img_url not in images:
                # Пропускаем data: URLs
                if not img_url.startswith('data:'):
                    images.append(img_url)
        
        # Если не нашли через microdata, ищем img теги в основном контейнере рецепта
        if not images:
            recipe_container = self.soup.find('div', class_='recipe-main-container')
            if recipe_container:
                img_tags = recipe_container.find_all('img')
                for img in img_tags:
                    img_url = img.get('src') or img.get('data-src')
                    if img_url and img_url not in images:
                        if not img_url.startswith('data:'):
                            images.append(img_url)
        
        if images:
            return ','.join(images)
        
        return None
    
    def _parse_iso_duration(self, duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах, например "90 minutes"
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
        
        return f"{total_minutes} minutes" if total_minutes > 0 else None
    
    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта"""
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
            "image_urls": self.extract_image_urls(),
        }


def main():
    """
    Точка входа для обработки директории с HTML файлами ankarsrum.com
    """
    # Путь к директории с preprocessed файлами
    preprocessed_dir = Path(__file__).parent.parent / 'preprocessed' / 'ankarsrum_com'
    
    if preprocessed_dir.exists():
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(AnkarsrumExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")


if __name__ == '__main__':
    main()
