"""
Экстрактор данных рецептов для сайта momflavours.co.il
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MomflavoursExtractor(BaseRecipeExtractor):
    """Экстрактор для momflavours.co.il"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1 - берем только основное название до первого дополнительного описания
        h1 = self.soup.find('h1')
        if h1:
            text = h1.get_text()
            # Убираем описательные части
            # Паттерны для разделения:
            # 1. "מתכון" и все после него
            # 2. Тире с описанием
            # 3. Скобки с описанием
            
            # Убираем скобки и их содержимое
            text = re.sub(r'\([^)]+\)', '', text)
            # Убираем "מתכון" и все после
            text = re.split(r'\s+מתכון', text)[0]
            # Убираем описание после тире
            text = re.split(r'\s*[–—]\s*', text)[0]
            
            return self.clean_text(text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Используем полный заголовок из og:title или h1 как описание
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Альтернативно - из h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def parse_ingredient_line(self, line: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            line: Строка вида "3 חצילים" или "500 גרם בשר בקר טחון"
            
        Returns:
            dict: {"name": "חצילים", "amount": "3", "unit": "pieces"} или None
        """
        if not line:
            return None
        
        line = self.clean_text(line)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "3 חצילים", "500 גרם בשר", "1/2 כפית מלח", "2-3 כפות שמן"
        
        # Словарь единиц измерения на иврите
        units_map = {
            'גרם': 'grams',
            'ק״ג': 'kg',
            'קילו': 'kg',
            'כוס': 'cup',
            'כוסות': 'cups',
            'כפית': 'teaspoon',
            'כפיות': 'teaspoons',
            'כף': 'tablespoon',
            'כפות': 'tablespoons',
            'מ״ל': 'ml',
            'ליטר': 'liter',
            'פרוסה': 'slice',
            'פרוסות': 'slices',
            'שן': 'clove',
            'שיני': 'cloves',
            'שיניים': 'cloves',
            'ביצה': 'piece',
            'ביצים': 'pieces',
            'חבילה': 'package',
            'חבילות': 'packages',
            'קופסה': 'can',
            'קופסת': 'can',
            'צרור': 'bunch',
            'צרורים': 'bunches',
            'גביע': 'cup',
            'גביעים': 'cups',
        }
        
        # Паттерн для количества: число, дробь или диапазон
        amount_pattern = r'(\d+(?:[/.,]\d+)?(?:\s*[-–]\s*\d+)?)'
        
        # Пытаемся найти количество в начале строки
        match = re.match(r'^\s*' + amount_pattern + r'\s+(.+)$', line)
        
        if match:
            amount_str = match.group(1)
            rest = match.group(2)
            
            # Нормализуем количество
            amount = amount_str.strip()
            if '/' in amount:
                # Обработка дробей
                parts = amount.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part.replace(',', '.'))
                amount = str(total)
            else:
                amount = amount.replace(',', '.')
            
            # Ищем единицу измерения в начале оставшейся строки
            unit = None
            name = rest
            
            for heb_unit, eng_unit in units_map.items():
                if rest.startswith(heb_unit):
                    unit = eng_unit
                    name = rest[len(heb_unit):].strip()
                    break
            
            # Если не нашли точное совпадение, ищем единицу в любом месте
            if unit is None:
                for heb_unit, eng_unit in units_map.items():
                    if heb_unit in rest:
                        unit = eng_unit
                        name = rest.replace(heb_unit, '').strip()
                        break
            
            # Если единица не найдена, но есть слова типа "גדול", "בינוני" и т.д.
            # это обычно означает "piece"
            if unit is None:
                size_words = ['גדול', 'בינוני', 'קטן', 'בינונית', 'גדולה', 'קטנה']
                if any(word in name for word in size_words):
                    unit = 'piece'
            
            return {
                "name": name.strip(),
                "amount": amount,
                "units": unit
            }
        else:
            # Нет количества - просто название
            # Но проверяем на наличие слов вроде "קורט" (щепотка)
            if any(word in line for word in ['קורט', 'קורטים', 'לפי הטעם', 'לפי טעם']):
                name = line
                for word in ['קורט', 'קורטים', 'לפי הטעם', 'לפי טעם']:
                    name = name.replace(word, '').strip()
                return {
                    "name": name.strip() if name.strip() else line,
                    "amount": "a pinch",
                    "units": None
                }
            
            return {
                "name": line,
                "amount": None,
                "units": None
            }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients_list = []
        
        # Ищем контент-див
        content_div = self.soup.find('div', class_='dynamic-entry-content')
        if not content_div:
            return None
        
        # Ищем заголовок "רשימת מרכיבים" или похожие
        ingredients_header_found = False
        collecting = False
        
        for child in content_div.children:
            if hasattr(child, 'name') and child.name:
                if child.name in ['h2', 'h3']:
                    if 'מרכיב' in child.get_text():
                        collecting = True
                        ingredients_header_found = True
                    elif collecting:
                        # Дошли до следующего заголовка, останавливаемся
                        break
                elif collecting and child.name == 'ul':
                    # Извлекаем ингредиенты из этого списка
                    items = child.find_all('li', recursive=False)
                    for item in items:
                        text = item.get_text().strip()
                        # Пропускаем пустые строки
                        if not text:
                            continue
                        # Пропускаем заголовки секций (заканчиваются на ":")
                        if text.endswith(':'):
                            continue
                        # Пропускаем секционные заголовки (начинаются с "ל" и содержат ":")
                        if text.startswith('ל') and ':' in text:
                            continue
                        
                        parsed = self.parse_ingredient_line(text)
                        if parsed and parsed.get('name'):
                            ingredients_list.append(parsed)
        
        return json.dumps(ingredients_list, ensure_ascii=False) if ingredients_list else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        steps = []
        
        # Ищем контент-див
        content_div = self.soup.find('div', class_='dynamic-entry-content')
        if not content_div:
            return None
        
        # Ищем заголовок "אופן ההכנה" или похожие
        instructions_header_found = False
        collecting = False
        
        for child in content_div.children:
            if hasattr(child, 'name') and child.name:
                if child.name in ['h2', 'h3']:
                    text = child.get_text()
                    if 'הכנה' in text or 'אופן' in text:
                        collecting = True
                        instructions_header_found = True
                    elif collecting and instructions_header_found:
                        # Дошли до следующего заголовка, останавливаемся
                        break
                elif collecting and child.name == 'p':
                    # Извлекаем текст шага
                    step_text = child.get_text()
                    step_text = self.clean_text(step_text)
                    if step_text:
                        steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Проверяем метаданные
        content_div = self.soup.find('div', class_='dynamic-entry-content')
        if content_div:
            # Ищем в тексте упоминания категорий
            text = content_div.get_text()
            if 'מנה עיקרית' in text or 'בשר' in text:
                return "Main Course"
        
        # По умолчанию для большинства рецептов на этом сайте
        return "Main Course"
    
    @staticmethod
    def format_time(minutes: int) -> str:
        """
        Форматирует время в минутах в удобочитаемую строку
        
        Args:
            minutes: Время в минутах
            
        Returns:
            Строка вида "25 minutes", "1 hour 30 minutes", "3 hours"
        """
        # Для времени меньше 2 часов используем только минуты
        if minutes < 120:
            return f"{minutes} minutes"
        
        hours = minutes // 60
        remaining_mins = minutes % 60
        
        if hours == 1:
            hour_str = "1 hour"
        else:
            hour_str = f"{hours} hours"
        
        if remaining_mins == 0:
            return hour_str
        else:
            return f"{hour_str} {remaining_mins} minutes"
    
    def extract_time_info(self) -> dict:
        """
        Извлечение информации о времени приготовления
        
        Returns:
            dict с ключами prep_time, cook_time, total_time
        """
        times = {
            'prep_time': None,
            'cook_time': None,
            'total_time': None
        }
        
        # Ищем контейнер с метаданными
        # Обычно это gb-container с текстом вроде "זמן עבודה: 35 דק'"
        containers = self.soup.find_all('div', class_=lambda c: c and 'gb-container' in c)
        
        for container in containers:
            text = container.get_text()
            
            # Ищем "זמן עבודה" (prep time - рабочее время)
            prep_match = re.search(r'זמן עבודה:\s*(\d+)\s*דק', text)
            if prep_match:
                times['prep_time'] = f"{prep_match.group(1)} minutes"
            
            # Ищем "משך הכנה" (cook time - длительность приготовления)
            # Может быть в формате "X שעות ו-Y דק'", "שעה ו-Y דק'", "X שעות", "שעה", или "Y דק'"
            cook_match = re.search(r'משך הכנה:\s*([^\n]+?)(?:\s{2,}|\s*כשרות|$)', text)
            if cook_match:
                time_str = cook_match.group(1).strip()
                
                # Парсим формат "X שעות ו-Y דק'" (X часов и Y минут)
                hours_mins_match = re.search(r'(\d+)\s*שעות?\s+ו-?(\d+)\s*דק', time_str)
                if hours_mins_match:
                    hours = int(hours_mins_match.group(1))
                    mins = int(hours_mins_match.group(2))
                    total_minutes = hours * 60 + mins
                    times['cook_time'] = self.format_time(total_minutes)
                else:
                    # Парсим формат "שעה ו-X דק'" (1 час и X минут)
                    hour_min_match = re.search(r'שעה\s+ו-?(\d+)\s*דק', time_str)
                    if hour_min_match:
                        minutes = 60 + int(hour_min_match.group(1))
                        times['cook_time'] = self.format_time(minutes)
                    else:
                        # Парсим формат "X שעות" (X часов)
                        hours_match = re.search(r'(\d+)\s*שעות?(?:\s|$)', time_str)
                        if hours_match:
                            hours = int(hours_match.group(1))
                            times['cook_time'] = self.format_time(hours * 60)
                        else:
                            # Парсим формат "שעה" (1 час)
                            if re.search(r'^\s*שעה\s*$', time_str):
                                times['cook_time'] = self.format_time(60)
                            else:
                                # Парсим формат "X דק'" (X минут)
                                min_match = re.search(r'(\d+)\s*דק', time_str)
                                if min_match:
                                    times['cook_time'] = self.format_time(int(min_match.group(1)))
        
        # Вычисляем total_time если есть prep и cook
        if times['prep_time'] and times['cook_time']:
            # Извлекаем минуты из форматированных строк
            prep_mins = 0
            cook_mins = 0
            
            # Parse prep_time
            prep_parts = times['prep_time'].split()
            if 'hour' in times['prep_time']:
                prep_mins = int(prep_parts[0]) * 60
                if len(prep_parts) > 2:
                    prep_mins += int(prep_parts[2])
            else:
                prep_mins = int(prep_parts[0])
            
            # Parse cook_time
            cook_parts = times['cook_time'].split()
            if 'hour' in times['cook_time']:
                cook_mins = int(cook_parts[0]) * 60
                if len(cook_parts) > 2:
                    cook_mins += int(cook_parts[2])
            else:
                cook_mins = int(cook_parts[0])
            
            total_mins = prep_mins + cook_mins
            
            # Round to nearest hour if close (within 10 minutes)
            if total_mins >= 120:
                hours = total_mins / 60
                rounded_hours = round(hours)
                if abs(hours - rounded_hours) * 60 <= 10:
                    total_mins = rounded_hours * 60
            
            times['total_time'] = self.format_time(total_mins)
        
        return times
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time_info()['prep_time']
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time_info()['cook_time']
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time_info()['total_time']
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем контент-див
        content_div = self.soup.find('div', class_='dynamic-entry-content')
        if not content_div:
            return None
        
        # Ищем секцию с заголовком "הערות" или "שדרוגים"
        collecting = False
        for child in content_div.children:
            if hasattr(child, 'name') and child.name:
                if child.name in ['h2', 'h3']:
                    text = child.get_text()
                    if 'הערות' in text or 'שדרוג' in text:
                        collecting = True
                    elif collecting:
                        # Дошли до следующего заголовка
                        break
                elif collecting and child.name == 'p':
                    # Берем первый параграф
                    note_text = child.get_text()
                    note_text = self.clean_text(note_text)
                    if note_text:
                        # Убираем префикс вроде "איך להפוך ליותר "בריא":"
                        note_text = re.sub(r'^[^:]+:\s*', '', note_text)
                        # Берем только первые 2 предложения
                        sentences = note_text.split('.')
                        notes.append('.'.join(sentences[:2]).strip() + '.')
                        break
                elif collecting and child.name == 'ul':
                    # Заметки могут быть в списке - берем первые 2 элемента
                    items = child.find_all('li', recursive=False)
                    for item in items[:2]:
                        note_text = item.get_text()
                        note_text = self.clean_text(note_text)
                        if note_text:
                            # Убираем префикс и берем только первое предложение
                            note_text = re.sub(r'^[^:]+:\s*', '', note_text)
                            first_sentence = note_text.split('.')[0].strip()
                            if first_sentence:
                                notes.append(first_sentence + '.')
                    break
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Для momflavours.co.il можем извлечь из различных источников
        tags = []
        
        # 1. Из названия блюда (первое слово обычно название блюда)
        dish_name = self.extract_dish_name()
        if dish_name:
            tags.append(dish_name.split()[0])
        
        # 2. Общие теги
        tags.append('מתכון קל')
        tags.append('אוכל ביתי')
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if url not in urls:
                urls.append(url)
        
        # Возвращаем как строку через запятую
        return ','.join(urls) if urls else None
    
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
    """Обработка всех HTML файлов в директории preprocessed/momflavours_co_il"""
    import os
    
    # Находим директорию с HTML-страницами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "preprocessed",
        "momflavours_co_il"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(MomflavoursExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python momflavours_co_il.py")


if __name__ == "__main__":
    main()
