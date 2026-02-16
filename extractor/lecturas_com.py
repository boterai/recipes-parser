"""
Экстрактор данных рецептов для сайта lecturas.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class LecturasExtractor(BaseRecipeExtractor):
    """Экстрактор для lecturas.com"""
    
    def get_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                
                # Check if it's a Recipe type
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
                # Check in list
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                            
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Try JSON-LD first
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Try og:title meta tag
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Remove suffixes like ", receta de..."
            title = re.sub(r',\s*receta.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Try h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Try JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Try meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Try og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Try JSON-LD first (most reliable)
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'recipeIngredient' in recipe_data:
            recipe_ingredients = recipe_data['recipeIngredient']
            if isinstance(recipe_ingredients, list):
                for ingredient_text in recipe_ingredients:
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "400 gramos de costilla de cerdo troceada"
            
        Returns:
            dict: {"name": "costilla de cerdo troceada", "amount": 400, "unit": "grams"}
        """
        if not ingredient_text:
            return None
        
        # Clean text
        text = self.clean_text(ingredient_text).lower()
        
        # Replace Unicode fractions
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Pattern for Spanish ingredients: "400 gramos de costilla de cerdo"
        # Match: number + unit + "de" + name
        pattern = r'^([\d\s/.,]+)?\s*(gramos?|kilos?|kg|g|litros?|l|ml|mililitros?|cucharadas?|cucharaditas?|tazas?|unidades?|dientes?|hojas?|pizca|pizcas?|tablespoon|liter|tbsp|tsp)?\s*(?:de\s+)?(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # If no pattern match, return just the name
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Process amount
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Handle fractions like "1/2" or "1 1/2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                amount = total
            else:
                amount_str = amount_str.replace(',', '.')
                try:
                    amount = float(amount_str) if '.' in amount_str else int(amount_str)
                except ValueError:
                    amount = None
        
        # Process unit - map Spanish units to English equivalents
        unit_mapping = {
            'gramos': 'grams',
            'gramo': 'grams',
            'g': 'grams',
            'kilos': 'grams',
            'kilo': 'grams',
            'kg': 'grams',
            'litros': 'liter',
            'litro': 'liter',
            'l': 'liter',
            'mililitros': 'ml',
            'mililitro': 'ml',
            'ml': 'ml',
            'cucharadas': 'tablespoon',
            'cucharada': 'tablespoon',
            'cucharaditas': 'teaspoon',
            'cucharadita': 'teaspoon',
            'tazas': 'cup',
            'taza': 'cup',
            'dientes': None,
            'diente': None,
            'hojas': None,
            'hoja': None,
            'unidades': None,
            'unidad': None,
            'pizca': None,
            'pizcas': None,
        }
        
        if unit:
            unit = unit.strip().lower()
            unit = unit_mapping.get(unit, unit)
            # Convert kg to grams
            if unit == 'grams' and amount and amount_str and ('kilo' in amount_str or 'kg' in amount_str):
                amount = amount * 1000
        
        # Clean name
        name = re.sub(r'\([^)]*\)', '', name)  # Remove parentheses
        name = re.sub(r'\b(al gusto|opcional|si se desea)\b', '', name, flags=re.IGNORECASE)
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Try JSON-LD first
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        steps.append(f"{idx}. {step_text}")
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        steps.append(f"{idx}. {step_text}")
        
        if steps:
            return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Try JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'recipeCategory' in recipe_data:
            return self.clean_text(recipe_data['recipeCategory'])
        
        # Try meta tags
        meta_section = self.soup.find('meta', property='mrf:tags')
        if meta_section and meta_section.get('content'):
            content = meta_section['content']
            # Extract "Tipo Plato:..." from tags
            match = re.search(r'Tipo Plato:([^;]+)', content)
            if match:
                return self.clean_text(match.group(1))
        
        return None
    
    def parse_iso_duration(self, duration: str) -> Optional[str]:
        """
        Convert ISO 8601 duration to minutes
        
        Args:
            duration: string like "PT20M" or "PT1H30M"
            
        Returns:
            Time in format like "20 minutes"
        """
        if not duration or not duration.startswith('PT'):
            return None
        
        duration = duration[2:]  # Remove "PT"
        
        hours = 0
        minutes = 0
        
        # Extract hours
        hour_match = re.search(r'(\d+)H', duration)
        if hour_match:
            hours = int(hour_match.group(1))
        
        # Extract minutes
        min_match = re.search(r'(\d+)M', duration)
        if min_match:
            minutes = int(min_match.group(1))
        
        # Convert to total minutes
        total_minutes = hours * 60 + minutes
        
        if total_minutes > 0:
            return f"{total_minutes} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Try JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Try JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Try JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # For lecturas.com, notes are not in JSON-LD but might be in the article body
        # We could look for specific sections, but for now return None
        # as the reference JSONs seem to have custom notes
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Try JSON-LD keywords
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Split by comma
                tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        if tags_list:
            return ', '.join(tags_list)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Try og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # Try JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'image' in recipe_data:
            images = recipe_data['image']
            if isinstance(images, list):
                for img in images:
                    if isinstance(img, dict) and 'url' in img:
                        urls.append(img['url'])
                    elif isinstance(img, str):
                        urls.append(img)
            elif isinstance(images, str):
                urls.append(images)
            elif isinstance(images, dict) and 'url' in images:
                urls.append(images['url'])
        
        # Remove duplicates while preserving order
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    import os
    # Process preprocessed/lecturas_com directory
    preprocessed_dir = os.path.join("preprocessed", "lecturas_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(LecturasExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python lecturas_com.py")


if __name__ == "__main__":
    main()
