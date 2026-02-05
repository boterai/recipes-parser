"""
Recipe data extractor for mevashelet.com website
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MevashelatExtractor(BaseRecipeExtractor):
    """Extractor for mevashelet.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Extract dish name"""
        # Ищем в meta теге og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Альтернативно - из заголовка h2
        h2_title = self.soup.find('h2')
        if h2_title:
            link = h2_title.find('a')
            if link:
                return self.clean_text(link.get_text())
            return self.clean_text(h2_title.get_text())
        
        # Из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем суффиксы типа "פשוט מבשלת »"
            title = re.sub(r'^[^»]*»\s*', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Extract recipe description"""
        # Ищем в мета-теге og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        # Альтернативно - первый абзац в контенте до "המצרכים"
        content_div = self.soup.find('div', class_='the_content')
        if content_div:
            # Ищем текст до "המצרכים" (ingredients header)
            content_text = content_div.get_text(separator=' ', strip=True)
            # Берем текст до ключевого слова "המצרכים"
            if 'המצרכים' in content_text:
                desc = content_text.split('המצרכים')[0].strip()
                if desc and len(desc) > 10:
                    return self.clean_text(desc)
        
        return None
    
    def parse_ingredient_line(self, line: str) -> Optional[dict]:
        """
        Parse ingredient line into structured format
        
        Args:
            line: Line like "3 חלבונים" or "1/2 כוס סוכר"
            
        Returns:
            dict: {"name": "חלבונים", "amount": 3, "units": None} or None
        """
        if not line:
            return None
        
        line = self.clean_text(line)
        
        # Skip section headers (contain colon at the end)
        if line.endswith(':') or line.startswith('ל'):  # "לרוטב", "למילוי" etc.
            return None
        
        # Pattern for extracting amount, unit and name
        # Examples: "3 חלבונים", "1/2 כוס סוכר", "125 גרם orכמניות"
        
        # First try with units
        # List of possible Hebrew units (using (?:...) for non-capturing group)
        units_pattern = r'(?:כוס|כפות|כפית|כפיות|גרם|ק"ג|ליטר|מ"ל|יחידות|פרוסות|שן|שיניים|ג\'|מ"ג|ק"ג)'
        
        # Pattern: [number/fraction] [unit] [name]
        pattern_with_unit = rf'^([\d\s/.,½¼¾⅓⅔⅛⅜⅝⅞]+)\s*({units_pattern})\s+(.+)$'
        match = re.match(pattern_with_unit, line, re.IGNORECASE)
        
        if match:
            groups = match.groups()
            if len(groups) == 3:
                amount_str, unit, name = groups
            else:
                # If for some reason there are more groups, take first 3
                amount_str, unit, name = groups[0], groups[1], groups[2]
            
            # Process amount
            amount = self._parse_amount(amount_str)
            
            # Clean name from comments in parentheses
            name = re.sub(r'\([^)]*\)', '', name)
            name = self.clean_text(name)
            
            return {
                "name": name,
                "units": unit,
                "amount": amount
            }
        
        # Паттерн without units: [number] [name]
        pattern_no_unit = r'^([\d\s/.,½¼¾⅓⅔⅛⅜⅝⅞]+)\s+(.+)$'
        match = re.match(pattern_no_unit, line, re.IGNORECASE)
        
        if match:
            amount_str, name = match.groups()
            
            # Process amount
            amount = self._parse_amount(amount_str)
            
            # Clean name from comments in parentheses
            name = re.sub(r'\([^)]*\)', '', name)
            name = self.clean_text(name)
            
            return {
                "name": name,
                "units": None,
                "amount": amount
            }
        
        # Если не удалось распарсить, возвращаем просто name
        return {
            "name": line,
            "units": None,
            "amount": None
        }
    
    def _parse_amount(self, amount_str: str) -> Optional[float]:
        """Parse amount from string"""
        if not amount_str:
            return None
        
        amount_str = amount_str.strip()
        
        # Замена дробей на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            amount_str = amount_str.replace(fraction, decimal)
        
        # Обработка дробей типа "1/2" or "1 1/2"
        if '/' in amount_str:
            parts = amount_str.split()
            total = 0.0
            for part in parts:
                if '/' in part:
                    num, denom = part.split('/')
                    total += float(num) / float(denom)
                else:
                    total += float(part)
            return total
        
        # Простое number
        try:
            return float(amount_str.replace(',', '.'))
        except ValueError:
            return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Extract ingredients"""
        ingredients = []
        
        # Ищем контент-div
        content_div = self.soup.find('div', class_='the_content')
        if not content_div:
            return None
        
        # Получаем HTML контента
        html_content = str(content_div)
        
        # Ищем секцию с ингредиентами между "המצרכים" и "orפן ההכנה"
        # Используем регулярное выражение для извлечения (поддержка <strong> и <b>)
        ingredients_pattern = r'<(?:strong|b)>המצרכים</(?:strong|b)>:(.*?)<(?:strong|b)>orפן ההכנה'
        match = re.search(ingredients_pattern, html_content, re.DOTALL | re.IGNORECASE)
        
        if match:
            ingredients_html = match.group(1)
            
            # Разбиваем по <br> тегам
            lines = re.split(r'<br\s*/?>', ingredients_html)
            
            for line in lines:
                # Убираем HTML теги
                line_text = re.sub(r'<[^>]+>', '', line)
                line_text = self.clean_text(line_text)
                
                if line_text and len(line_text) > 2:
                    parsed = self.parse_ingredient_line(line_text)
                    if parsed and parsed.get('name'):
                        # Пропускаем строки-заголовки подсекций (начинаются с 'ל' or заканчиваются ':')
                        if not (line_text.startswith('ל') and line_text.endswith(':')):
                            ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Extract cooking instructions"""
        # Ищем контент-div
        content_div = self.soup.find('div', class_='the_content')
        if not content_div:
            return None
        
        # Получаем HTML контента
        html_content = str(content_div)
        
        # Ищем секцию с инструкциями после "orפן ההכנה"
        instructions_pattern = r'<(?:strong|b)>orפן ההכנה</(?:strong|b)>:(.*?)</p>'
        match = re.search(instructions_pattern, html_content, re.DOTALL | re.IGNORECASE)
        
        if match:
            instructions_html = match.group(1)
            
            # Разбиваем по <br> тегам
            lines = re.split(r'<br\s*/?>', instructions_html)
            
            # Убираем HTML теги и объединяем
            steps = []
            for line in lines:
                line_text = re.sub(r'<[^>]+>', '', line)
                line_text = self.clean_text(line_text)
                
                if line_text and len(line_text) > 5:
                    steps.append(line_text)
            
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Extract category"""
        # Ищем категории в postmeta
        category_li = self.soup.find('li', class_='category')
        if category_li:
            # Берем ссылки на категории
            links = category_li.find_all('a')
            if links:
                # Ищем категорию, которая не является тегом праздника
                # Предпочитаем категорию типа блюда (последняя перед праздниками)
                # Праздники обычно: חגים, פסח, ראש השנה etc.
                holiday_tags = ['חגים', 'פסח', 'ראש השנה', 'חנוכה', 'פורים']
                for link in reversed(links):
                    cat_text = self.clean_text(link.get_text())
                    if cat_text not in holiday_tags:
                        return cat_text
                # Если все категории - праздники, возвращаем первую
                return self.clean_text(links[0].get_text())
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Extract cooking time from recipe text"""
        # Ищем в инструкциях упоминания времени
        instructions = self.extract_instructions()
        if not instructions:
            return None
        
        # Паттерны для поиска времени на иврите
        # "שעתיים" = 2 часа, "120 מעלות" (температура, не время)
        # "10-20 דקות" = 10-20 минут
        
        # Ищем упоминания часов
        hours_match = re.search(r'(\d+)\s*שע(?:ות|ה)', instructions)
        if hours_match:
            hours = int(hours_match.group(1))
            return f"{hours * 60} minutes"
        
        # Ищем слово "שעתיים" (два часа)
        if 'שעתיים' in instructions:
            return "120 minutes"
        
        # Ищем упоминания минут
        minutes_match = re.search(r'(\d+(?:-\d+)?)\s*דק(?:ות|ה)', instructions)
        if minutes_match:
            minutes_str = minutes_match.group(1)
            # Если диапазон, берем максимум
            if '-' in minutes_str:
                minutes = minutes_str.split('-')[-1]
            else:
                minutes = minutes_str
            return f"{minutes} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Extract notes"""
        # В данном сайте заметки могут быть в описании с ключевыми словами
        # "החלפתי" (I replaced), "הערה" (note), "טיפ" (tip)
        
        # Ищем в описании
        content_div = self.soup.find('div', class_='the_content')
        if not content_div:
            return None
        
        # Получаем первый параграф (description)
        first_p = content_div.find('p')
        if first_p:
            desc_text = first_p.get_text(separator=' ', strip=True)
            
            # Ищем предложения с ключевыми словами
            if 'החלפתי' in desc_text:
                # Находим предложение с "החלפתי"
                sentences = desc_text.split('.')
                for sentence in sentences:
                    if 'החלפתי' in sentence:
                        note = sentence.strip()
                        # Добавляем точку если её нет
                        if not note.endswith('.'):
                            note += '.'
                        return self.clean_text(note)
            
            # Ищем другие паттерны примечаний
            note_patterns = [r'(?:הערה|טיפ|שימו לב)[^.]*\.']
            for pattern in note_patterns:
                match = re.search(pattern, desc_text)
                if match:
                    return self.clean_text(match.group(0))
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Extract tags"""
        tags = []
        
        # Ищем категории - они могут служить как теги
        category_li = self.soup.find('li', class_='category')
        if category_li:
            links = category_li.find_all('a')
            for link in links:
                tag_text = self.clean_text(link.get_text())
                if tag_text and tag_text not in tags:
                    tags.append(tag_text)
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Extract image URLs"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем изображения в контенте
        content_div = self.soup.find('div', class_='the_content')
        if content_div:
            images = content_div.find_all('img')
            for img in images:
                src = img.get('src')
                if src and src not in urls:
                    urls.append(src)
        
        # Убираем дубликаты и возвращаем как строку через запятую
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
        Extract all recipe data
        
        Returns:
            Dictionary with recipe data
        """
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_instructions(),
            "category": self.extract_category(),
            "prep_time": None,  # Сайт не предоставляет prep_time отдельно
            "cook_time": self.extract_cook_time(),
            "total_time": None,  # Сайт не предоставляет total_time отдельно
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Entry point for processing directory with HTML files"""
    import os
    
    # Process preprocessed/mevashelet_com directory
    preprocessed_dir = os.path.join("preprocessed", "mevashelet_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(MevashelatExtractor, preprocessed_dir)
        return
    
    print(f"Directory not found: {preprocessed_dir}")
    print("Usage: python mevashelet_com.py")


if __name__ == "__main__":
    main()
