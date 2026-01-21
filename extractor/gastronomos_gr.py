"""
Recipe data extractor for gastronomos.gr website
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class GastronomosExtractor(BaseRecipeExtractor):
    """Extractor for gastronomos.gr"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Extract JSON-LD data from the page"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Данные могут быть списком или словарем
                if isinstance(data, list):
                    # Ищем Recipe в списке
                    for item in data:
                        if isinstance(item, dict):
                            item_type = item.get('@type', '')
                            if isinstance(item_type, list) and 'Recipe' in item_type:
                                return item
                            elif item_type == 'Recipe':
                                return item
                elif isinstance(data, dict):
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict):
                                item_type = item.get('@type', '')
                                if isinstance(item_type, list) and 'Recipe' in item_type:
                                    return item
                                elif item_type == 'Recipe':
                                    return item
                    
                    # Проверяем напрямую
                    item_type = data.get('@type', '')
                    if isinstance(item_type, list) and 'Recipe' in item_type:
                        return data
                    elif item_type == 'Recipe':
                        return data
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Convert ISO 8601 duration to readable format
        
        Args:
            duration: string like "PT20M" or "PT1H30M"
            
        Returns:
            Time in format "20 minutes" or "1 hour 30 minutes"
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
        
        # Форматируем результат
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Extract dish name"""
        # Сначала пробуем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффикс типа " - Gastronomos"
            title = re.sub(r'\s+[-|]\s+(Gastronomos|ΓΑΣΤΡΟΝΟΜΟΣ).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Extract recipe description"""
        # Сначала пробуем JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def _parse_ingredient_line(self, line: str) -> Optional[Dict]:
        """
        Parse ingredient line into structured format
        
        Examples (Greek):
        "500 γρ. αλεύρι" -> {"name": "αλεύρι", "unit": "g", "amount": "500"}
        "2 αυγά" -> {"name": "αυγά", "unit": null, "amount": "2"}
        "αλάτι" -> {"name": "αλάτι", "unit": null, "amount": null}
        """
        if not line:
            return None
        
        line = self.clean_text(line)
        
        # Greek unit mapping dictionary
        unit_mapping = {
            'γρ.': 'g',
            'γρ': 'g',
            'gr': 'g',
            'γραμμάρια': 'g',
            'ml': 'ml',
            'λίτρο': 'l',
            'λίτρα': 'l',
            'κ.σ.': 'tbsp',
            'κουτ. σούπας': 'tbsp',
            'κ.γ.': 'tsp',
            'κουτ. γλυκού': 'tsp',
            'ματσάκι': 'bunch',
            'φλιτζάνι': 'cup',
            'φλ.': 'cup',
        }
        
        # Pattern: amount + unit + name
        # Examples: "500 γρ. мука", "2 αυγά", "1/2 ματσάκι άνηθος"
        pattern = r'^([\d./,\s]+)\s*([α-ωά-ώa-z.]+)?\s+(.+)$'
        match = re.match(pattern, line, re.IGNORECASE | re.UNICODE)
        
        if match:
            amount_str, unit_str, name = match.groups()
            
            # Process amount (can be fraction like "1/2")
            amount = None
            if amount_str:
                amount_str = amount_str.strip()
                if '/' in amount_str:
                    parts = amount_str.split('/')
                    if len(parts) == 2:
                        try:
                            amount = str(float(parts[0]) / float(parts[1]))
                        except ValueError:
                            amount = amount_str
                else:
                    try:
                        amount = amount_str.replace(',', '.')
                    except (ValueError, AttributeError):
                        amount = amount_str
            
            # Process unit of measurement
            unit = None
            if unit_str:
                unit_str = unit_str.strip()
                # Check if this is a unit of measurement
                if unit_str in unit_mapping:
                    unit = unit_mapping[unit_str]
                else:
                    # Check known patterns
                    for key, value in unit_mapping.items():
                        if unit_str.lower().startswith(key.lower().rstrip('.')):
                            unit = value
                            break
                    
                    # If unit not found, add to name
                    if not unit:
                        name = f"{unit_str} {name}"
            
            # Clean name
            name = self.clean_text(name)
            # Remove descriptions in parentheses
            name = re.sub(r'\([^)]*\)', '', name)
            # Remove additional explanations
            name = re.sub(r'\s+(τριμμένο|ψιλοκομμένο|κομμένο|κομμένη|λιωμένο).*$', '', name, flags=re.IGNORECASE | re.UNICODE)
            name = name.strip()
            
            if not name or len(name) < 2:
                return None
            
            return {
                "name": name,
                "amount": amount,
                "unit": unit
            }
        else:
            # If pattern didn't match, return name only
            return {
                "name": line,
                "amount": None,
                "unit": None
            }
    
    def extract_ingredients(self) -> Optional[str]:
        """Extract ingredients"""
        ingredients = []
        
        # Try JSON-LD first
        json_ld = self._get_json_ld_data()
        if json_ld and 'recipeIngredient' in json_ld:
            ingredient_list = json_ld['recipeIngredient']
            if isinstance(ingredient_list, list):
                for ingredient in ingredient_list:
                    if isinstance(ingredient, str):
                        parsed = self._parse_ingredient_line(ingredient)
                        if parsed:
                            ingredients.append(parsed)
                
                if ingredients:
                    return json.dumps(ingredients, ensure_ascii=False)
        
        # If JSON-LD didn't work, search in HTML
        # Look for ingredient list
        ingredient_containers = [
            self.soup.find('ul', class_=re.compile(r'ingredient', re.I)),
            self.soup.find('div', class_=re.compile(r'ingredient', re.I)),
            self.soup.find('div', id=re.compile(r'ingredient', re.I)),
        ]
        
        for container in ingredient_containers:
            if not container:
                continue
                
            # Extract list items
            items = container.find_all('li')
            if not items:
                items = container.find_all('p')
            
            for item in items:
                # Extract ingredient text
                ingredient_text = item.get_text(separator=' ', strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                # Skip section headers
                if ingredient_text and not ingredient_text.endswith(':'):
                    parsed = self._parse_ingredient_line(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
            
            if ingredients:
                break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Extract cooking steps"""
        steps = []
        
        # Try JSON-LD first
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        steps.append(f"{idx}. {step_text}")
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        steps.append(f"{idx}. {step_text}")
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            
            if steps:
                return ' '.join(steps)
        
        # If JSON-LD didn't work, search in HTML
        instructions_containers = [
            self.soup.find('ol', class_=re.compile(r'instruction', re.I)),
            self.soup.find('div', class_=re.compile(r'instruction', re.I)),
            self.soup.find('div', id=re.compile(r'instruction', re.I)),
        ]
        
        for container in instructions_containers:
            if not container:
                continue
            
            # Extract steps
            step_items = container.find_all('li')
            if not step_items:
                step_items = container.find_all('p')
            
            for idx, item in enumerate(step_items, 1):
                # Extract instruction text
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    # If numbering already exists, use as is
                    if re.match(r'^\d+\.', step_text):
                        steps.append(step_text)
                    else:
                        steps.append(f"{idx}. {step_text}")
            
            if steps:
                break
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Extract category"""
        # Try JSON-LD first
        json_ld = self._get_json_ld_data()
        
        if json_ld:
            # Try recipeCategory
            if 'recipeCategory' in json_ld:
                category = json_ld['recipeCategory']
                if isinstance(category, list):
                    return ', '.join(category)
                return str(category)
            
            # Try recipeCuisine
            if 'recipeCuisine' in json_ld:
                cuisine = json_ld['recipeCuisine']
                if isinstance(cuisine, list):
                    return ', '.join(cuisine)
                return str(cuisine)
        
        # Alternative - from meta tags
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Look in breadcrumbs
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:  # Get last category
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Extract preparation time"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Extract cooking time"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Extract total time"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Extract notes and tips"""
        # Look for notes/tips section
        notes_section = self.soup.find(class_=re.compile(r'(note|tip|hint)', re.I))
        
        if notes_section:
            # Try to find paragraph inside first
            p = notes_section.find('p')
            if p:
                text = self.clean_text(p.get_text())
                return text if text else None
            
            # If no paragraph, get all text
            text = notes_section.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Extract tags"""
        tags_list = []
        
        # Try JSON-LD first
        json_ld = self._get_json_ld_data()
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if isinstance(keywords, str):
                tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            elif isinstance(keywords, list):
                tags_list = [str(tag).strip() for tag in keywords if tag]
        
        # If not found in JSON-LD, search in meta tags
        if not tags_list:
            # parsely-tags
            parsely_meta = self.soup.find('meta', attrs={'name': 'parsely-tags'})
            if parsely_meta and parsely_meta.get('content'):
                tags_string = parsely_meta['content']
                tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        # Look in meta keywords
        if not tags_list:
            keywords_meta = self.soup.find('meta', attrs={'name': 'keywords'})
            if keywords_meta and keywords_meta.get('content'):
                tags_string = keywords_meta['content']
                tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        # Filter - remove very short tags
        filtered_tags = [tag for tag in tags_list if len(tag) >= 3]
        
        # Return as comma-separated string with space
        return ', '.join(filtered_tags) if filtered_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Extract image URLs"""
        urls = []
        
        # Try JSON-LD first
        json_ld = self._get_json_ld_data()
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
        # Look in meta tags
        if not urls:
            # og:image
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
            
            # twitter:image
            twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
            if twitter_image and twitter_image.get('content'):
                urls.append(twitter_image['content'])
        
        # Remove duplicates, keeping order
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            # Return as comma-separated string without spaces
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
            "instructions": self.extract_steps(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Entry point for testing the extractor"""
    import os
    
    # Process preprocessed/gastronomos_gr directory by default
    preprocessed_dir = os.path.join("preprocessed", "gastronomos_gr")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Processing directory: {preprocessed_dir}")
        process_directory(GastronomosExtractor, str(preprocessed_dir))
        return
    
    print(f"Directory not found: {preprocessed_dir}")
    print("Create a directory with recipe HTML files for testing.")
    print("Usage: python gastronomos_gr.py")


if __name__ == "__main__":
    main()
