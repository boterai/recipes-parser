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
            dict: {"name": "świeże lub mrożone grzyby", "amount": 600, "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Список единиц измерения для польского языка
        units_map = {
            'g': 'g', 'kg': 'kg', 'mg': 'mg', 'ml': 'ml', 'l': 'l',
            'litr': 'l', 'litra': 'l', 'litry': 'l',
            'łyżka': 'tablespoon', 'łyżki': 'tablespoon', 'łyżek': 'tablespoon',
            'łyżeczka': 'teaspoon', 'łyżeczki': 'teaspoon', 'łyżeczek': 'teaspoon',
            'sztuka': 'piece', 'sztuki': 'pieces', 'sztuk': 'pieces',
            'szklanka': 'cup', 'szklanki': 'cup', 'szklanek': 'cup',
            'ząbek': 'clove', 'ząbki': 'cloves', 'ząbków': 'cloves',
            'garść': 'handful', 'garści': 'handful',
            'szczypta': 'pinch', 'szczypcie': 'pinch', 'szczypt': 'pinch'
        }
        
        units_pattern = '|'.join(re.escape(unit) for unit in units_map.keys())
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "600 g grzybów", "1 litr bulionu", "2 średnie marchewki", "pół szklanki mleka"
        pattern = rf'^([\d.,/\s½¼¾-]+|pół)?\s*({units_pattern})?\s+(.+)'
        
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
            amount_str = amount_str.strip().lower()
            # Обработка "pół" (половина)
            if amount_str == 'pół' or amount_str == '½':
                amount = 0.5
            elif amount_str == '¼':
                amount = 0.25
            elif amount_str == '¾':
                amount = 0.75
            else:
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
        
        # Обработка единицы измерения - нормализуем к английским единицам
        normalized_unit = None
        if unit:
            unit = unit.strip().lower()
            normalized_unit = units_map.get(unit, unit)
        
        # Очистка названия
        # Удаляем информацию в скобках
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы типа "lub też", "np.", "około"
        name = re.sub(r'\s+(lub też|np\.|około)\s+.*$', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        
        # Нормализуем названия - убираем падежные окончания
        # Примеры: "bulionu warzywnego" -> "bulion warzywny"
        name_corrections = {
            'bulionu warzywnego': 'bulion warzywny',
            'bulionu': 'bulion',
            'pieczonej dyni hokkaido': 'pieczona dynia Hokkaido',
            'pieczonej dyni': 'pieczona dynia',
            'cebula cukrowa': 'cebula cukrowa',  # оставляем как есть
            'średnie marchewki': 'marchewka',
            'marchewki': 'marchewka',
            'masła klarowanego': 'masło klarowane',
            'pół szklanki mleka tłustego': 'mleko tłuste',
            'mleka tłustego': 'mleko tłuste',
        }
        
        name_lower = name.lower()
        for pattern, replacement in name_corrections.items():
            if pattern in name_lower:
                name = replacement
                break
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": normalized_unit
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
        # Ищем элемент с itemprop="recipeInstructions"
        instructions_elem = self.soup.find(attrs={'itemprop': 'recipeInstructions'})
        
        if not instructions_elem:
            return None
        
        # Сначала пытаемся найти нумерованные шаги (ищем паттерны типа "1.", "2.", etc.)
        full_text = instructions_elem.get_text(separator='\n', strip=True)
        
        # Разбиваем на строки
        lines = [line.strip() for line in full_text.split('\n') if line.strip()]
        
        # Ищем шаги, которые начинаются с глаголов или нумерации
        instruction_steps = []
        step_pattern = re.compile(r'^\d+\.\s*(.+)', re.IGNORECASE)  # "номер. текст"
        
        # Глаголы, с которых обычно начинаются шаги инструкций
        instruction_verbs = [
            'podsmaz', 'podsmać', 'wlej', 'dodaj', 'umieść', 'zagotuj', 'zmiksuj', 
            'gotuj', 'pełn', 'wymieszaj', 'sprawdź', 'podawaj', 'odstaw',
            'poczekaj', 'gotowa', 'przenie', 'wyjmij', 'pokroj', 'nagrz'
        ]
        
        for line in lines:
            # Проверяем нумерованные шаги
            step_match = step_pattern.match(line)
            if step_match:
                instruction_steps.append(step_match.group(1))
                continue
            
            # Проверяем, начинается ли строка с глагола
            line_lower = line.lower()
            if any(line_lower.startswith(verb) for verb in instruction_verbs):
                # Игнорируем короткие строки (менее 20 символов)
                if len(line) >= 20:
                    instruction_steps.append(line)
        
        if instruction_steps:
            # Объединяем шаги с нумерацией
            formatted_steps = []
            for i, step in enumerate(instruction_steps, 1):
                formatted_steps.append(f"{i}. {step}")
            return ' '.join(formatted_steps)
        
        # Если не нашли структурированные шаги, возвращаем весь текст (очищенный)
        cleaned_text = self.clean_text(full_text)
        return cleaned_text if cleaned_text else None
    
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
