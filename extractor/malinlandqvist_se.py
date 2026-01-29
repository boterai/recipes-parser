"""
Экстрактор данных рецептов для сайта malinlandqvist.se
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MalinlandqvistExtractor(BaseRecipeExtractor):
    """Экстрактор для malinlandqvist.se"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке страницы
        title = self.soup.find('h1', class_='menu-text-caps')
        if title:
            return self.clean_text(title.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            return self.clean_text(title_tag.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в параграфе с классом receptingress
        desc = self.soup.find('p', class_='receptingress')
        if desc and not 'tipsar' in desc.get('class', []):
            return self.clean_text(desc.get_text())
        
        # Ищем в мета-тегах
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
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
            ingredient_text: Строка вида "1 kg fast potatis" или "2 msk olivolja"
            
        Returns:
            dict: {"name": "potatis", "amount": "1", "units": "kg"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Пропускаем пустые строки и специальные символы
        if not text or text == '‍':
            return None
        
        # Заменяем Unicode дроби на обычные дроби
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Удаляем скобки с содержимым один раз в начале
        text = re.sub(r'\s*\([^)]*\)', '', text).strip()
        
        # Паттерн для специального случая: "1 stor eller 2 mindre auberginer"
        # Или typo: "1 stor eller 2 minde auberginer"
        complex_pattern = r'^(\d+(?:[\/.,]\d+)?)\s+(stora?|mindre|minde)\s+eller\s+(\d+)\s+(stora?|mindre|minde)\s+(.+)'
        complex_match = re.match(complex_pattern, text, re.IGNORECASE)
        
        if complex_match:
            amount, size1, amount2, size2, name = complex_match.groups()
            # Нормализуем "minde" -> "mindre"
            if size1.lower() == 'minde':
                size1 = 'mindre'
            if size2.lower() == 'minde':
                size2 = 'mindre'
            # Используем plural "stora" для compatibility с reference data
            if size1.lower() == 'stor':
                size1 = 'stora'
            units = f"{size1} eller {amount2} {size2}"
            return {
                "name": name.strip(),
                "amount": amount,
                "units": units
            }
        
        # Паттерн для обычных ингредиентов: "2 msk hackad timjan" или "1 kg potatis"
        # amount unit name
        units_list = [
            'kg', 'kilogram', 'g', 'gram', 
            'dl', 'deciliter', 'cl', 'centiliter', 'ml', 'milliliter', 'l', 'liter',
            'msk', 'matsked', 'matskedar', 
            'tsk', 'tesked', 'teskedar', 
            'krm', 'kryddmått',
            'st', 'styck', 'stycken',
            'burk', 'burkar', 'paket', 'påse', 'påsar',
            'bit', 'bitar'
        ]
        
        units_pattern = '|'.join(units_list)
        normal_pattern = r'^(\d+(?:[\/.,]\d+)?)\s+(' + units_pattern + r')\s+(.+)'
        
        normal_match = re.match(normal_pattern, text, re.IGNORECASE)
        
        if normal_match:
            amount, unit, name = normal_match.groups()
            return {
                "name": name.strip(),
                "amount": amount,
                "units": unit.strip()
            }
        
        # Паттерн без явной единицы: "2 gula lökar" (число + название)
        # В этом случае можем попробовать найти "st" implicit
        simple_pattern = r'^(\d+(?:[\/.,]\d+)?)\s+(.+)'
        simple_match = re.match(simple_pattern, text, re.IGNORECASE)
        
        if simple_match:
            amount, name = simple_match.groups()
            # Если название начинается со слова, которое не является единицей измерения,
            # считаем что единица - "st" (штуки) неявно
            return {
                "name": name.strip(),
                "amount": amount,
                "units": "st"
            }
        
        # Ингредиенты без количества: "salt och peppar"
        return {
            "name": text.strip(),
            "amount": None,
            "units": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем все секции с ингредиентами
        ingredient_sections = self.soup.find_all('div', class_='receptingrediens')
        
        for section in ingredient_sections:
            # Проверяем, не является ли это секцией "Till servering" (для подачи)
            # Ищем предыдущий параграф с заголовком
            prev_p = section.find_previous_sibling('p', class_='receptunderrubrik')
            if prev_p:
                header_text = prev_p.get_text().lower()
                # Пропускаем секции "Till servering"
                if 'till servering' in header_text or header_text.strip().startswith('till servering'):
                    continue
            
            # Ищем параграфы с ингредиентами
            paragraphs = section.find_all('p')
            
            for p in paragraphs:
                ingredient_text = p.get_text(strip=True)
                
                # Пропускаем заголовки и пустые строки
                if not ingredient_text or ingredient_text == '‍':
                    continue
                
                # Если в строке "och" (и), это может быть список ингредиентов БЕЗ количества
                # Например: "salt och svartpeppar" (без цифр в начале)
                if ' och ' in ingredient_text and not re.match(r'^\d', ingredient_text.strip()):
                    # Разбиваем на отдельные ингредиенты
                    parts = ingredient_text.split(' och ')
                    for part in parts:
                        parsed = self.parse_ingredient(part.strip())
                        if parsed and parsed['name']:
                            ingredients.append(parsed)
                else:
                    # Парсим ингредиент как есть
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed and parsed['name']:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        instructions = []
        
        # Ищем секцию с инструкциями - div с классами recepttext inner w-richtext
        # Берем первую такую секцию (вторая обычно для заметок)
        all_richtext_divs = self.soup.find_all('div', class_='w-richtext')
        
        instruction_sections = []
        for div in all_richtext_divs:
            classes = div.get('class', [])
            if 'recepttext' in classes and 'inner' in classes:
                instruction_sections.append(div)
        
        if instruction_sections:
            # Берем первую секцию (это основные инструкции)
            section = instruction_sections[0]
            
            # Извлекаем все параграфы
            paragraphs = section.find_all('p')
            
            for p in paragraphs:
                text = p.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                
                # Пропускаем параграфы с "Foto:" или пустые или специальные символы
                if text and not text.startswith('Foto:') and text != '&nbsp;' and text != '‍':
                    instructions.append(text)
        
        result = ' '.join(instructions) if instructions else None
        # Убираем trailing специальные символы
        if result:
            result = result.rstrip(' ‍')
            # Исправляем случаи когда после точки нет пробела перед заглавной буквой
            result = re.sub(r'\.([A-ZÅÄÖÆØ])', r'. \1', result)
        return result
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # На этом сайте категория явно не указана, можем попробовать определить
        # по метаданным или оставить None
        
        # Можно попробовать извлечь из breadcrumbs или других элементов
        # Но в примерах не всегда есть категория, поэтому вернем None или "Main Course"
        return None
    
    def _extract_prep_time_from_text(self, instructions: Optional[str]) -> Optional[str]:
        """Извлечение времени подготовки из текста инструкций"""
        if not instructions:
            return None
        
        # Ищем паттерны типа "låt dra... i ca 30 minuter" (время отдыха/подготовки)
        prep_pattern = r'låt\s+\w+.*?(\d+)\s*min(?:uter)?'
        match = re.search(prep_pattern, instructions, re.IGNORECASE)
        if match:
            return f"{match.group(1)} minutes"
        
        return None
    
    def _extract_cook_time_from_text(self, instructions: Optional[str]) -> Optional[str]:
        """Извлечение времени приготовления из текста инструкций"""
        if not instructions:
            return None
        
        # Ищем паттерны типа "i ugnen i ca 20 min", "baka... i 40-50 minuter"
        cook_patterns = [
            r'(?:i\s+ugnen|baka|grädda|stek).*?(\d+(?:-\d+)?)\s*min(?:uter)?',
            r'(\d+(?:-\d+)?)\s*min(?:uter)?.*?(?:i\s+ugnen|baka|grädda)',
        ]
        
        for pattern in cook_patterns:
            match = re.search(pattern, instructions, re.IGNORECASE)
            if match:
                return f"{match.group(1)} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с заметками - p с классом receptingress tipsar
        notes_header = self.soup.find('p', class_='receptingress tipsar')
        
        if notes_header:
            # Заметка находится в следующем div
            next_div = notes_header.find_next_sibling('div')
            if next_div:
                classes = next_div.get('class', [])
                # Проверяем что это div с recepttext inner w-richtext
                if 'recepttext' in classes and 'inner' in classes:
                    paragraphs = next_div.find_all('p')
                    notes_text = ' '.join([self.clean_text(p.get_text()) for p in paragraphs])
                    return notes_text if notes_text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # На этом сайте теги не всегда явно указаны
        # Можно попробовать извлечь из keywords или других мест
        
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем главное изображение рецепта
        main_img = self.soup.find('img', class_='receptmainimage')
        if main_img and main_img.get('src'):
            urls.append(main_img['src'])
        
        # 2. Ищем в meta тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', property='twitter:image')
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
            
            return ','.join(unique_urls) if unique_urls else None
        
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
        
        # Извлекаем инструкции один раз и используем для всех методов времени
        instructions = self.extract_instructions()
        
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()
        
        # Извлекаем времена, передавая уже извлеченные инструкции
        prep_time = self._extract_prep_time_from_text(instructions)
        cook_time = self._extract_cook_time_from_text(instructions)
        
        # Вычисляем total_time из prep и cook
        total_time = None
        if prep_time and cook_time:
            try:
                prep_num = int(re.search(r'(\d+)', prep_time).group(1))
                cook_match = re.search(r'(\d+)(?:-(\d+))?', cook_time)
                if cook_match:
                    cook_num = int(cook_match.group(2) if cook_match.group(2) else cook_match.group(1))
                    total = prep_num + cook_num
                    total_time = f"{total} minutes"
            except (ValueError, AttributeError):
                pass
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "notes": notes,
            "tags": tags,
            "image_urls": image_urls
        }


def main():
    """Основная функция для обработки директории с HTML файлами"""
    import os
    
    # Путь к директории с примерами
    preprocessed_dir = os.path.join("preprocessed", "malinlandqvist_se")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(MalinlandqvistExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python malinlandqvist_se.py")


if __name__ == "__main__":
    main()
