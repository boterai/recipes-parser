"""
Экстрактор данных рецептов для сайта aniagotuje.pl
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class AniagotujeExtractor(BaseRecipeExtractor):
    """Экстрактор для aniagotuje.pl"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "X minutes" (например, "90 minutes")
            
        Note:
            Этот формат отличается от allrecipes_com (который возвращает просто число),
            но соответствует ожидаемому формату для aniagotuje.pl согласно эталонным JSON.
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
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в h1 с itemprop="name"
        h1 = self.soup.find('h1', attrs={'itemprop': 'name'})
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "600 g świeżych lub mrożonych grzybów"
            
        Returns:
            dict: {"name": "świeże lub mrożone grzyby", "amount": 600, "unit": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Список единиц измерения для польского языка
        units_list = [
            'g', 'kg', 'mg', 'ml', 'l', 'litr', 'litra', 'litry',
            'łyżka', 'łyżki', 'łyżek', 'łyżeczka', 'łyżeczki', 'łyżeczek',
            'sztuka', 'sztuki', 'sztuk', 'szklanka', 'szklanki', 'szklanek',
            'ząbek', 'ząbki', 'ząbków', 'garść', 'garści', 'szczypcie', 'szczypt',
            'pieces?', 'tablespoons?', 'tbsp', 'teaspoons?', 'tsp', 'cups?', 'piece'
        ]
        units_pattern = '|'.join(units_list)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "600 g грибов", "1 litr bulionu", "2 średnie marchewki - 220 g"
        pattern = rf'^([\d.,/\s-]+)?\s*({units_pattern})?\s+(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Убираем тире и лишние пробелы
            amount_str = re.sub(r'\s*-\s*', '', amount_str).strip()
            # Обработка дробей типа "1/2" или "1 1/2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        try:
                            total += float(part.replace(',', '.'))
                        except ValueError:
                            pass
                amount = total if total > 0 else None
            else:
                try:
                    # Заменяем запятые на точки
                    amount_str = amount_str.replace(',', '.')
                    amount = float(amount_str) if amount_str else None
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения  
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Если есть дополнительная информация о весе после тире, используем её
        weight_match = re.search(r'-\s*(\d+)\s*g\s*$', name)
        if weight_match and not amount:
            # Если есть вес в конце и нет amount, используем его
            amount = float(weight_match.group(1))
            unit = 'g'
            name = re.sub(r'\s*-\s*\d+\s*g\s*$', '', name)
        elif weight_match:
            # Если есть вес в конце, удаляем его из имени
            name = re.sub(r'\s*-\s*\d+\s*g\s*$', '', name)
        
        # Удаляем информацию в скобках
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы типа "lub też", "np.", "około"
        name = re.sub(r'\s+(lub też|np\.|około)\s+.*$', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем все элементы с itemprop="recipeIngredient"
        ingredient_elems = self.soup.find_all(attrs={'itemprop': 'recipeIngredient'})
        
        for elem in ingredient_elems:
            ingredient_text = elem.get_text(separator=' ', strip=True)
            ingredient_text = self.clean_text(ingredient_text)
            
            if ingredient_text:
                # Парсим в структурированный формат
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    # Адаптируем формат к ожидаемому (units вместо unit)
                    ingredients.append({
                        "name": parsed["name"],
                        "amount": parsed["amount"],
                        "units": parsed["units"]
                    })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Минимальная длина текста для определения блока с инструкциями
        MIN_INSTRUCTION_TEXT_LENGTH = 1000
        
        # Ищем элемент с itemprop="recipeInstructions"
        instructions_elem = self.soup.find(attrs={'itemprop': 'recipeInstructions'})
        
        if instructions_elem:
            # Ищем div без класса, который содержит основной контент и инструкции
            content_divs = instructions_elem.find_all('div', recursive=False, class_=lambda x: x is None or x == [])
            
            for div in content_divs:
                text = div.get_text(strip=True)
                # Ищем div с инструкциями (обычно длинный и содержит ключевые слова)
                # Проверяем наличие типичных глаголов в инструкциях
                instruction_keywords = ['zacznij', 'nagrzewać', 'dodaj', 'umieść', 'gotuj']
                has_keywords = any(keyword in text.lower() for keyword in instruction_keywords)
                
                if len(text) > MIN_INSTRUCTION_TEXT_LENGTH and has_keywords:
                    # Извлекаем текст построчно
                    lines = []
                    for child in div.descendants:
                        # Собираем текстовые узлы
                        if isinstance(child, str):
                            cleaned = self.clean_text(child)
                            if cleaned and len(cleaned) > 20:
                                lines.append(cleaned)
                    
                    # Объединяем lines
                    full_text = ' '.join(lines)
                    
                    # Пытаемся найти начало инструкций
                    # Инструкции обычно начинаются с глаголов типа "Zacznij", "Dodaj", etc.
                    instruction_patterns = [
                        'Zacznij nagrzewać',
                        'W garnku',
                        'Na patelni',
                        'Umieść'
                    ]
                    
                    start_idx = -1
                    for pattern in instruction_patterns:
                        idx = full_text.find(pattern)
                        if idx != -1 and (start_idx == -1 or idx < start_idx):
                            start_idx = idx
                    
                    if start_idx != -1:
                        full_text = full_text[start_idx:]
                    
                    return full_text if full_text else None
            
            # Если не нашли специальный div, берем весь текст
            text = instructions_elem.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в meta itemprop="recipeCategory"
        category_meta = self.soup.find('meta', attrs={'itemprop': 'recipeCategory'})
        if category_meta and category_meta.get('content'):
            category = self.clean_text(category_meta['content'])
            # Нормализуем: "zupy" -> "Zupa", удаляя множественное число если нужно
            if category and category.lower() == 'zupy':
                return 'Zupa'
            return category.capitalize() if category else None
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prepTime', 'cookTime', 'totalTime')
        """
        # Ищем в meta itemprop
        time_meta = self.soup.find('meta', attrs={'itemprop': time_type})
        if time_meta and time_meta.get('content'):
            iso_time = time_meta['content']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prepTime')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('cookTime')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('totalTime')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Для aniagotuje.pl заметки обычно находятся в конце статьи
        # или в специальных блоках с советами
        # Это может быть сложно извлечь точно, попробуем найти параграфы после инструкций
        
        # Ищем блок с заметками/советами (если есть специальный класс)
        notes_section = self.soup.find(class_=re.compile(r'note|tip|hint', re.I))
        
        if notes_section:
            text = notes_section.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        # Если нет специального блока, можем попробовать найти параграфы 
        # после recipeInstructions, но это ненадежно
        # Для первой версии можем оставить None если нет явного блока
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из meta-тега keywords"""
        # Ищем в meta itemprop="keywords"
        keywords_meta = self.soup.find('meta', attrs={'itemprop': 'keywords'})
        if keywords_meta and keywords_meta.get('content'):
            tags_string = keywords_meta['content']
            # Разбиваем по запятым и очищаем
            tags = [self.clean_text(tag.strip()) for tag in tags_string.split(',') if tag.strip()]
            # Фильтруем и оставляем только осмысленные теги
            filtered_tags = []
            for tag in tags:
                tag_lower = tag.lower()
                # Пропускаем слишком длинные теги (обычно это названия блюд)
                if len(tag_lower) < 50:
                    filtered_tags.append(tag_lower)
            
            # Возвращаем как строку через запятую с пробелом
            return ', '.join(filtered_tags) if filtered_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в meta itemprop="image"
        image_meta = self.soup.find('meta', attrs={'itemprop': 'image'})
        if image_meta and image_meta.get('content'):
            urls.append(image_meta['content'])
        
        # 2. Ищем в og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 3. Ищем в twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
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
    """Обработка директории с HTML-файлами aniagotuje.pl"""
    import os
    
    # Путь к директории с HTML-файлами
    preprocessed_dir = os.path.join("preprocessed", "aniagotuje_pl")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(AniagotujeExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python aniagotuje_pl.py")


if __name__ == "__main__":
    main()
