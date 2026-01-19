"""
Recipe data extractor for mesrecettes.info website
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MesRecettesExtractor(BaseRecipeExtractor):
    """Extractor for mesrecettes.info website"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Extract recipe name"""
        # Ищем в мета-теге og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Альтернативно - в title
        title_tag = self.soup.find('title')
        if title_tag:
            return self.clean_text(title_tag.get_text())
        
        # Ищем h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Extract recipe description"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient_line(self, line: str) -> Optional[dict]:
        """
        Parse ingredient line into structured format
        
        Args:
            line: String like "1 kg de pommes de terre" or "Sel"
            
        Returns:
            dict: {"name": "pommes de terre", "amount": "1", "units": "kg"} or None
        """
        if not line:
            return None
        
        # Чистим текст
        text = self.clean_text(line).strip()
        
        # Пропускаем пустые строки
        if not text or len(text) < 2:
            return None
        
        # Сокращения единиц измерения
        unit_map = {
            'càs': 'càs',  # cuillère à soupe
            'càc': 'càc',  # cuillère à café
            'tasse': 'tasse',
            'tasses': 'tasse',
            'kg': 'kg',
            'g': 'g',
            'ml': 'ml',
            'l': 'l',
            'c.': 'càs',
            'cc': 'càc',
        }
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1 kg de pommes de terre", "1/3 tasse d'huile d'olive", "1,5 càc d'origan séché"
        pattern = r'^([\d\s/.,]+)\s*(kg|g|ml|l|tasse|tasses|càs|càc|c\.|cc)?\s*(?:de|d\'|d\')?\s*(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название без количества и единиц
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Handle amount - preserve simple fractions as strings
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # For fractions, preserve the original format, but normalize mixed fractions
            if '/' in amount_str:
                # If it's a mixed fraction like "1 1/2", convert to decimal
                parts = amount_str.split()
                if len(parts) > 1:
                    # Mixed fraction - convert to decimal
                    total = 0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            try:
                                if int(denom) == 0:
                                    # Skip invalid fraction
                                    continue
                                total += float(num) / float(denom)
                            except (ValueError, ZeroDivisionError):
                                continue
                        else:
                            try:
                                total += float(part.replace(',', '.'))
                            except ValueError:
                                continue
                    # Format with one decimal place
                    if total == int(total):
                        amount = str(int(total))
                    else:
                        amount = str(round(total, 1))
                else:
                    # Simple fraction - keep as is
                    amount = amount_str
            else:
                # Replace comma with dot for decimal numbers
                amount = amount_str.replace(',', '.')
        
        # Обработка единицы измерения
        if unit:
            unit = unit.strip().lower()
            unit = unit_map.get(unit, unit)
        
        # Очистка названия от предлогов "de", "d'"
        if name:
            # Убираем начальные "d'" или "de " в начале (включая разные типы апострофов)
            # U+2019 - right single quotation mark
            name = re.sub(r"^d['''\u2019\`´]?\s*", '', name)
            name = re.sub(r'^de\s+', '', name)
            # Убираем оставшиеся одиночные апострофы в начале
            name = re.sub(r"^['''\u2019\`´]\s*", '', name)
        
        
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Extract ingredients list"""
        ingredients = []
        
        # Ищем заголовок "Ingrédients"
        ingredients_heading = self.soup.find('h2', id='ingredients')
        if not ingredients_heading:
            ingredients_heading = self.soup.find('h2', string=re.compile(r'Ingr[ée]dients?', re.I))
        
        if ingredients_heading:
            # Ищем следующий параграф после заголовка
            next_elem = ingredients_heading.find_next_sibling('p')
            if next_elem:
                # Получаем текст, заменяя <br> на разделитель
                # Используем get_text с separator для корректной обработки <br>
                for br in next_elem.find_all('br'):
                    br.replace_with('|||')  # Временный разделитель
                
                full_text = next_elem.get_text()
                lines = full_text.split('|||')
                
                # Парсим каждую строку ингредиента
                for line in lines:
                    line = self.clean_text(line)
                    if line:
                        parsed = self.parse_ingredient_line(line)
                        if parsed:
                            ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Extract preparation instructions"""
        instructions = []
        
        # Look for "Préparation" or "Comment faire" heading
        prep_heading = self.soup.find('h2', id='preparation')
        if not prep_heading:
            prep_heading = self.soup.find('h2', string=re.compile(r'Pr[ée]paration', re.I))
        
        # Also look for "Comment faire..." heading
        comment_heading = self.soup.find('h2', string=re.compile(r'Comment faire', re.I))
        
        # Use whichever heading comes first in the document
        start_heading = None
        if prep_heading and comment_heading:
            # Check which comes first in the document
            all_h2 = self.soup.find_all('h2')
            prep_idx = all_h2.index(prep_heading) if prep_heading in all_h2 else float('inf')
            comment_idx = all_h2.index(comment_heading) if comment_heading in all_h2 else float('inf')
            start_heading = prep_heading if prep_idx < comment_idx else comment_heading
        elif prep_heading:
            start_heading = prep_heading
        elif comment_heading:
            start_heading = comment_heading
        
        if start_heading:
            # Collect all paragraphs after the heading
            current = start_heading.find_next_sibling()
            while current:
                # Stop at the next major section (WordPress uses wp-block-group class for section wrappers)
                if current.name in ['h1', 'div'] and 'wp-block-group' in current.get('class', []):
                    break
                
                # Skip intermediate h2 headings
                if current.name == 'h2':
                    current = current.find_next_sibling()
                    continue
                
                if current.name == 'p':
                    text = self.clean_text(current.get_text())
                    if text and len(text) > 5:  # Skip very short paragraphs
                        instructions.append(text)
                
                # Check for content end marker (WordPress comment indicating content boundary)
                if current.name == 'div' or (isinstance(current, str) and 'CONTENT END' in str(current)):
                    break
                
                current = current.find_next_sibling()
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Extract recipe category"""
        # Ищем в JSON-LD breadcrumb
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Обработка @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BreadcrumbList':
                            items = item.get('itemListElement', [])
                            # Берем последний элемент хлебных крошек (обычно категория)
                            if items and len(items) > 1:
                                last_item = items[-1]
                                category = last_item.get('name')
                                if category:
                                    return self.clean_text(category)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно ищем в ссылках категорий
        cat_div = self.soup.find('div', class_='taxonomy-category')
        if cat_div:
            links = cat_div.find_all('a')
            if links:
                # Берем первую категорию
                return self.clean_text(links[0].get_text())
        
        return None
    
    def extract_time_info(self) -> tuple:
        """
        Extract time information
        
        Returns:
            Кортеж (prep_time, cook_time, total_time)
        """
        prep_time = None
        cook_time = None
        total_time = None
        
        # Ищем параграф с временем
        # Формат: "Préparation: 10 minutes<br>Cuisson: 45 minutes<br>..."
        # Обычно идет ПЕРЕД заголовком "Ingrédients"
        paragraphs = self.soup.find_all('p')
        
        for p in paragraphs:
            text = p.get_text()
            
            # Проверяем, содержит ли параграф информацию о времени
            if re.search(r'Pr[ée]paration\s*:', text, re.I) or re.search(r'Cuisson\s*:', text, re.I):
                # Заменяем <br> на разделитель
                for br in p.find_all('br'):
                    br.replace_with('|||')
                
                full_text = p.get_text()
                lines = full_text.split('|||')
                
                for line in lines:
                    line = self.clean_text(line)
                    
                    # Préparation: 10 minutes
                    prep_match = re.search(r'Pr[ée]paration\s*:\s*(\d+\s*(?:minutes?|heures?))', line, re.I)
                    if prep_match:
                        prep_time = self.clean_text(prep_match.group(1))
                    
                    # Cuisson: 45 minutes или Cuisson: environ 40 minutes
                    cook_match = re.search(r'Cuisson\s*:\s*(?:environ\s*)?(\d+\s*(?:minutes?|heures?))', line, re.I)
                    if cook_match:
                        cook_time = self.clean_text(cook_match.group(1))
                    
                    # Total: 55 minutes
                    total_match = re.search(r'Total\s*:\s*(\d+\s*(?:minutes?|heures?))', line, re.I)
                    if total_match:
                        total_time = self.clean_text(total_match.group(1))
                
                # Если нашли хотя бы одно значение, прерываем поиск
                if prep_time or cook_time or total_time:
                    break
        
        # If total_time not found but have prep_time and cook_time, calculate it
        if not total_time and prep_time and cook_time:
            try:
                prep_match = re.search(r'(\d+)', prep_time)
                cook_match = re.search(r'(\d+)', cook_time)
                if prep_match and cook_match:
                    prep_mins = int(prep_match.group(1))
                    cook_mins = int(cook_match.group(1))
                    total_time = f"{prep_mins + cook_mins} minutes"
            except (ValueError, AttributeError):
                # If parsing fails, leave total_time as None
                pass
        
        return prep_time, cook_time, total_time
    
    def extract_notes(self) -> Optional[str]:
        """Extract notes and tips"""
        # Для этого сайта заметки обычно отсутствуют
        # Можно искать секции типа "Conseil", "Astuce", "Note" и т.д.
        notes_keywords = ['conseil', 'astuce', 'note', 'remarque']
        
        for keyword in notes_keywords:
            heading = self.soup.find(['h2', 'h3', 'h4'], string=re.compile(keyword, re.I))
            if heading:
                # Собираем текст из следующих параграфов
                notes_parts = []
                current = heading.find_next_sibling()
                while current and current.name == 'p':
                    text = self.clean_text(current.get_text())
                    if text:
                        notes_parts.append(text)
                    current = current.find_next_sibling()
                
                if notes_parts:
                    return ' '.join(notes_parts)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Extract recipe tags"""
        # На этом сайте теги обычно отсутствуют в HTML
        # Можно попробовать извлечь из категорий или ключевых слов
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Extract image URLs"""
        urls = []
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Обработка @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
            except (json.JSONDecodeError, KeyError):
                continue
        
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
        Extract all recipe data
        
        Returns:
            Словарь с данными рецепта
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        prep_time, cook_time, total_time = self.extract_time_info()
        notes = self.extract_notes()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()
        
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
    """
    Entry point for testing the parser
    """
    import os
    
    # Обрабатываем папку preprocessed/mesrecettes_info
    recipes_dir = os.path.join("preprocessed", "mesrecettes_info")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(MesRecettesExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python mesrecettes_info.py")


if __name__ == "__main__":
    main()
