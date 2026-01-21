"""
Экстрактор данных рецептов для сайта gatesc.ro
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class GatescRoExtractor(BaseRecipeExtractor):
    """Экстрактор для gatesc.ro"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в читаемом формате, например "20 minutes" или "1 hour 30 minutes"
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
        parts = []
        if hours > 0:
            if hours == 1:
                parts.append("1 ora")
            else:
                parts.append(f"{hours} ore")
        
        if minutes > 0:
            if minutes == 1:
                parts.append("1 minut")
            else:
                parts.append(f"{minutes} minute")
        
        return ' '.join(parts) if parts else None
    
    def get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение данных из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно из заголовка
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Приоритет: meta description (краткое описание)
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            return desc if desc else None
        
        # Альтернативно из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            desc = self.clean_text(recipe_data['description'])
            # Убираем переносы строк
            desc = re.sub(r'\s+', ' ', desc)
            return desc if desc else None
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        seen_names = set()  # Track ingredient names to avoid duplicates
        
        # Ищем контейнер с ингредиентами
        ing_container = self.soup.find(class_='recipe-ingredients')
        
        if ing_container:
            # Проверяем, есть ли секции ингредиентов (component-name)
            component_names = self.soup.find_all(class_='component-name')
            
            if component_names:
                # Если есть секции, обрабатываем каждую отдельно
                for idx, comp_name in enumerate(component_names):
                    section_name = self.clean_text(comp_name.get_text())
                    
                    # Находим следующий ul с ингредиентами для этой секции
                    next_ul = comp_name.find_next_sibling('ul')
                    
                    if next_ul:
                        items = next_ul.find_all('li')
                        
                        # Только для ПЕРВОЙ секции добавляем название секции как ингредиент
                        if idx == 0 and items:
                            # Берем количество и единицу из первого элемента
                            first_item = items[0]
                            spans = first_item.find_all('span')
                            if len(spans) >= 2:
                                amount_unit_text = self.clean_text(spans[0].get_text())
                                amount, unit = self.parse_amount_unit(amount_unit_text)
                                
                                # Добавляем название секции как первый ингредиент
                                if unit and unit.strip():
                                    ingredients.append({
                                        "name": section_name,
                                        "amount": amount,
                                        "units": unit
                                    })
                                    seen_names.add(section_name.lower())
                        
                        # Добавляем остальные ингредиенты этой секции
                        for item in items:
                            spans = item.find_all('span')
                            
                            if len(spans) >= 2:
                                amount_unit_text = self.clean_text(spans[0].get_text())
                                name_text = self.clean_text(spans[1].get_text())
                                
                                if name_text and amount_unit_text:
                                    amount, unit = self.parse_amount_unit(amount_unit_text)
                                    
                                    # Фильтруем плохие записи (только цифры без единиц)
                                    if unit and unit.strip():
                                        # Проверяем, не видели ли мы уже этот ингредиент
                                        # Исключение: "sare" (соль) может повторяться с разными количествами
                                        name_lower = name_text.lower()
                                        if name_lower not in seen_names or name_lower == 'sare':
                                            ingredients.append({
                                                "name": name_text,
                                                "amount": amount,
                                                "units": unit
                                            })
                                            seen_names.add(name_lower)
            else:
                # Если секций нет, обрабатываем как обычно
                items = ing_container.find_all('li')
                
                for item in items:
                    spans = item.find_all('span')
                    
                    if len(spans) >= 2:
                        amount_unit_text = self.clean_text(spans[0].get_text())
                        name_text = self.clean_text(spans[1].get_text())
                        
                        if name_text and amount_unit_text:
                            amount, unit = self.parse_amount_unit(amount_unit_text)
                            
                            if unit and unit.strip():
                                ingredients.append({
                                    "name": name_text,
                                    "amount": amount,
                                    "units": unit
                                })
                    elif len(spans) == 1:
                        name_text = self.clean_text(spans[0].get_text())
                        if name_text:
                            ingredients.append({
                                "name": name_text,
                                "amount": None,
                                "units": None
                            })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_amount_unit(self, text: str) -> tuple:
        """
        Парсинг строки с количеством и единицей измерения
        
        Args:
            text: Строка вида "200 ml" или "1 lingura"
            
        Returns:
            Кортеж (количество, единица)
        """
        if not text:
            return (None, None)
        
        # Паттерн для извлечения числа и единицы
        # Примеры: "200 ml", "1 lingura", "2 linguri"
        pattern = r'^([\d.,]+)\s*(.*)$'
        match = re.match(pattern, text.strip())
        
        if match:
            amount_str = match.group(1).strip()
            unit_str = match.group(2).strip()
            
            # Преобразуем количество в число (int или float)
            amount = None
            try:
                # Заменяем запятую на точку для десятичных чисел
                amount_normalized = amount_str.replace(',', '.')
                # Пробуем преобразовать в число
                amount_float = float(amount_normalized)
                # Если это целое число, возвращаем int
                if amount_float == int(amount_float):
                    amount = int(amount_float)
                else:
                    amount = amount_float
            except ValueError:
                # Если не число, оставляем как строку
                amount = amount_str
            
            return (amount if amount else None, unit_str if unit_str else None)
        
        # Если паттерн не совпал, возможно это только текст
        return (None, text.strip() if text.strip() else None)
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        # Сначала из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            
            if isinstance(instructions, dict) and 'text' in instructions:
                text = self.clean_text(instructions['text'])
                # Разбиваем на шаги и форматируем
                return self.format_instructions(text)
            elif isinstance(instructions, str):
                text = self.clean_text(instructions)
                return self.format_instructions(text)
        
        # Альтернативно ищем в HTML
        # Ищем секцию с инструкциями
        inst_container = self.soup.find(class_=lambda x: x and 'instruction' in str(x).lower())
        
        if inst_container:
            # Извлекаем шаги
            steps = []
            
            # Пробуем найти список
            step_items = inst_container.find_all('li')
            if not step_items:
                step_items = inst_container.find_all('p')
            
            for item in step_items:
                step_text = self.clean_text(item.get_text())
                if step_text:
                    steps.append(step_text)
            
            if steps:
                return self.format_instructions(' '.join(steps))
        
        return None
    
    def format_instructions(self, text: str) -> str:
        """
        Форматирование инструкций в пронумерованный список
        
        Args:
            text: Текст инструкций
            
        Returns:
            Отформатированный текст
        """
        if not text:
            return text
        
        # Убираем префиксы типа "Aluat Paste:" в начале
        text = re.sub(r'^[^:]+:\s*', '', text, count=1)
        
        # Разбиваем по точкам с запятой или переносам строк
        # Сначала нормализуем переносы
        text = re.sub(r'\r\n', '\n', text)
        
        # Разбиваем на шаги
        # Ищем разделители: ". ", ",\n", "\n"
        steps = []
        
        # Если уже есть "Pasul N:" - это готовые шаги
        if re.search(r'Pasul\s+\d+:', text, re.IGNORECASE):
            # Разбиваем по "Pasul N:"
            parts = re.split(r'Pasul\s+\d+:\s*', text, flags=re.IGNORECASE)
            for part in parts:
                part = part.strip()
                if part:
                    steps.append(part)
        else:
            # Разбиваем по переносам строк и точкам с запятой
            parts = re.split(r'[;\n]+', text)
            for part in parts:
                part = part.strip()
                if part and len(part) > 10:  # Игнорируем слишком короткие фрагменты
                    steps.append(part)
        
        if not steps:
            return text
        
        # Форматируем с нумерацией
        formatted = []
        for i, step in enumerate(steps, 1):
            # Убираем точку в конце, если есть
            step = re.sub(r'\.$', '', step.strip())
            formatted.append(f"Pasul {i}: {step}.")
        
        return ' '.join(formatted)
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            
            if isinstance(category, str):
                # Разбиваем на категории через запятую
                categories = [c.strip() for c in category.split(',')]
                
                # Определяем типы категорий:
                # - Dish types (приоритет): Garnituri, Deserturi, etc.
                # - Cuisine types: Italiana, Frantuzeasca, etc.
                # - Generic: Bucatarie internationala, Europeana
                
                dish_types = ['Garnituri', 'Deserturi', 'Aperitive', 'Feluri principale', 
                             'Salate', 'Supe', 'Sosuri']
                
                # Сначала ищем dish type
                for cat in categories:
                    if cat in dish_types:
                        return cat
                
                # Если нет dish type, берем "Bucatarie internationala" если есть
                if 'Bucatarie internationala' in categories:
                    return 'Bucatarie internationala'
                
                # Иначе берем первую не-Europeana категорию
                for cat in categories:
                    if cat != 'Europeana':
                        return cat
                
                # В крайнем случае, любую первую
                return categories[0] if categories else None
            elif isinstance(category, list):
                return category[0] if category else None
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'performTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['performTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Сначала проверяем r-description для полного текста описания
        desc_div = self.soup.find(class_='r-description')
        if desc_div:
            full_text = self.clean_text(desc_div.get_text())
            
            # Ищем предложение, начинающееся с "Servite" - обычно это заметки
            # Или берем последнее предложение, если оно содержит полезную информацию
            sentences = re.split(r'\.\s+', full_text)
            
            for sentence in sentences:
                if sentence.strip().startswith('Servite'):
                    note = sentence.strip()
                    # Добавляем точку только если её нет
                    return note if note.endswith('.') else note + '.'
            
            # Если не нашли "Servite", проверяем последнее предложение
            if sentences and len(sentences) > 1:
                last_sentence = sentences[-1].strip()
                # Если последнее предложение содержит ключевые слова о сервировке
                if any(word in last_sentence.lower() for word in ['servit', 'pahar', 'vin', 'ideal', 'perfecta']):
                    return last_sentence if last_sentence.endswith('.') else last_sentence + '.'
        
        # Альтернативно ищем секцию с примечаниями/советами
        notes_section = self.soup.find(class_=lambda x: x and ('note' in str(x).lower() or 'tip' in str(x).lower()))
        
        if notes_section:
            text = self.clean_text(notes_section.get_text())
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            tags = self.clean_text(meta_keywords['content'])
            return tags if tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Из JSON-LD
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict) and 'url' in img:
                urls.append(img['url'])
        
        # 2. Из мета-тегов
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
    """Точка входа для обработки директории с HTML-страницами"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "gatesc_ro")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(GatescRoExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python gatesc_ro.py")


if __name__ == "__main__":
    main()
