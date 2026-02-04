"""
Экстрактор данных рецептов для сайта retete.eva.ro
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ReteteEvaRoExtractor(BaseRecipeExtractor):
    """Экстрактор для retete.eva.ro"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из h1"""
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта из meta description"""
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient_text(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            text: Строка вида "125 g de spaghete" или "1 lingură cu ulei"
            
        Returns:
            dict: {"name": "spaghete", "amount": 125, "units": "g"} или None
        """
        if not text:
            return None
        
        text = self.clean_text(text).strip()
        if not text:
            return None
        
        # Pattern: amount + unit + name
        # Try to match fraction or decimal number first
        number_pattern = r'^(\d+(?:[.,/]\d+)?)\s+'
        match = re.match(number_pattern, text)
        
        if match:
            amount_str = match.group(1)
            # Convert fraction to decimal or integer
            if '/' in amount_str:
                parts = amount_str.split('/')
                amount = float(parts[0]) / float(parts[1])
            elif ',' in amount_str or '.' in amount_str:
                amount = float(amount_str.replace(',', '.'))
            else:
                amount = int(amount_str)
            
            rest = text[match.end():].strip()
            
            # Common units in Romanian (ordered by length to match longest first)
            unit_patterns = [
                (r'^(linguriță|lingurite|lingurita)', 'linguriță'),
                (r'^(lingură|linguri|lingura)', 'lingură'),
                (r'^(kilograme?|kg)', 'kg'),
                (r'^(grame?|gr|g)\b', 'g'),
                (r'^(mililitri?|ml)', 'ml'),
                (r'^(litri?|l)\b', 'l'),
                (r'^(tablespoons?)', 'tablespoons'),
                (r'^(teaspoons?)', 'teaspoon'),
                (r'^(bucăți?|bucati?|pieces?)', 'pieces'),
                (r'^(cățel|catei|cloves?)', 'cloves'),
                (r'^(felii?|slices?)', 'slice'),
                (r'^(grams?)', 'grams'),
                (r'^(piece)', 'piece'),
            ]
            
            # Try to match unit
            unit = None
            name = rest
            for pattern, unit_value in unit_patterns:
                unit_match = re.match(pattern, rest, re.I)
                if unit_match:
                    unit = unit_value
                    name = rest[unit_match.end():].strip()
                    # Remove leading "de", "cu", "pentru"
                    name = re.sub(r'^(de|cu|pentru)\s+', '', name, flags=re.I)
                    break
            
            # Clean up name - remove preparation instructions after comma
            if ',' in name:
                name = name.split(',')[0].strip()
            
            # Clean up name further
            if not name:
                name = rest
            
            return {
                'name': name,
                'amount': amount,
                'units': unit
            }
        else:
            # No amount found, just return the name
            return {
                'name': text,
                'amount': None,
                'units': None
            }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients_div = self.soup.find('div', class_='ingredients')
        if not ingredients_div:
            return None
        
        ingredients = []
        
        # First try to get ingredients from div children
        ing_divs = ingredients_div.find_all('div', recursive=False)
        if ing_divs:
            for ing_div in ing_divs:
                text = ing_div.get_text().strip()
                if text:
                    # Check if this ingredient has "și" (and) which might indicate multiple ingredients
                    # But only split if there's no amount at the beginning (otherwise it's a compound name)
                    if ' și ' in text and not re.match(r'^\d+', text):
                        # Split on "și" and remove qualifiers like "după gust", "opțional"
                        parts = text.split(' și ')
                        for part in parts:
                            # Remove trailing qualifiers
                            part = re.sub(r',?\s*(după gust|opțional)\s*$', '', part, flags=re.I).strip()
                            if part:
                                parsed = self.parse_ingredient_text(part)
                                if parsed:
                                    ingredients.append(parsed)
                    else:
                        parsed = self.parse_ingredient_text(text)
                        if parsed:
                            ingredients.append(parsed)
        else:
            # Try to get from p tag (alternative format)
            p_tag = ingredients_div.find('p')
            if p_tag:
                text = p_tag.get_text().strip()
                
                # Check if ingredients are separated by newlines
                if '\n' in text:
                    # Split by newlines (each line is an ingredient)
                    parts = text.split('\n')
                    for part in parts:
                        part = part.strip()
                        if part:
                            parsed = self.parse_ingredient_text(part)
                            if parsed:
                                ingredients.append(parsed)
                else:
                    # Ingredients are run together without newlines
                    # Remove section labels like "Compozitie ravioli:", "Sos ravioli:"
                    text = re.sub(r'[A-Z][a-z]+\s+[a-z]+:\s*', '', text)
                    
                    # Split by pattern:
                    # 1. Space + digit + space + letter (new ingredient with amount)
                    # 2. letter + digit + letter (handles "2linguri" without space)
                    # But not if digit is after dash (range like "6-7")
                    pattern = r'(?:(?<![0-9-])\s+(?=\d+\s+[a-zA-Z])|(?<=[a-z])(?=\d+[a-z]))'
                    
                    parts = re.split(pattern, text)
                    
                    for part in parts:
                        part = part.strip()
                        if part:
                            parsed = self.parse_ingredient_text(part)
                            if parsed:
                                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_div = self.soup.find('div', class_='recipe')
        if not recipe_div:
            return None
        
        # Get all div children (each is a step)
        step_divs = recipe_div.find_all('div', recursive=False)
        if not step_divs:
            # Try to get from p tags
            step_divs = recipe_div.find_all('p')
        
        instructions = []
        for step_div in step_divs:
            text = step_div.get_text().strip()
            # Skip empty and difficulty info
            if text and not text.lower().startswith('dificultate'):
                text = self.clean_text(text)
                if text:
                    instructions.append(text)
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории из breadcrumb"""
        breadcrumb = self.soup.find(class_='breadcrumbs')
        if breadcrumb:
            links = breadcrumb.find_all('a')
            # Get the last link before the recipe name (usually the category)
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления из текста инструкций"""
        recipe_div = self.soup.find('div', class_='recipe')
        if not recipe_div:
            return None
        
        text = recipe_div.get_text()
        
        # Romanian number words to digits
        romanian_numbers = {
            'două': 2, 'doi': 2, 'doua': 2,
            'trei': 3, 
            'patru': 4,
            'cinci': 5,
            'șase': 6, 'sase': 6,
            'șapte': 7, 'sapte': 7,
            'opt': 8,
            'nouă': 9, 'noua': 9,
            'zece': 10
        }
        
        total_time = 0
        
        # Look for patterns like "8 minute" or "2-3 minute"
        time_pattern = r'(\d+(?:-\d+)?)\s*minut[ei]*'
        matches = re.findall(time_pattern, text, re.I)
        
        for match in matches:
            if '-' in match:
                # For ranges, take the minimum (more conservative)
                parts = match.split('-')
                time_val = int(parts[0])
            else:
                time_val = int(match)
            total_time += time_val
        
        # Also look for Romanian number words followed by "minut"
        for word, value in romanian_numbers.items():
            pattern = rf'\b{word}\s+minut[ei]*'
            if re.search(pattern, text, re.I):
                total_time += value
        
        if total_time > 0:
            return f"{total_time} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки - обычно не указано явно"""
        # Not typically available on this site
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени - обычно не указано явно"""
        # Not typically available on this site
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок - обычно не указаны явно"""
        # Look for any special notes section
        # Not typically available on this site
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Check meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords.get('content')
            # Split and clean
            tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            return ', '.join(tags) if tags else None
        
        # Alternative: try to extract from any tags section
        # (not found in examples, but keeping for robustness)
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Try meta tags first
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Try to find recipe images in the page
        # Look for images that are likely recipe images (from retete-gustoase domain)
        images = self.soup.find_all('img', src=True)
        for img in images:
            src = img.get('src', '')
            # Filter for recipe images
            if 'retete-gustoase.ro' in src and 'recipe_article' in src:
                # Get the original/large version if possible
                if src not in urls:
                    urls.append(src)
                    if len(urls) >= 3:
                        break
        
        # Remove duplicates while preserving order
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
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """
    Обработка директории с HTML-файлами retete.eva.ro
    """
    import os
    # Путь к preprocessed/retete_eva_ro относительно корня репозитория
    preprocessed_dir = os.path.join("preprocessed", "retete_eva_ro")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ReteteEvaRoExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python retete_eva_ro.py")


if __name__ == "__main__":
    main()
