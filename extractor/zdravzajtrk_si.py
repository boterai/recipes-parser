"""
Extractor for zdravzajtrk.si recipes
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ZdravZajtrkExtractor(BaseRecipeExtractor):
    """Extractor for zdravzajtrk.si"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Extract dish name from page"""
        # Look for h1 tag
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Alternative: from meta tag og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Remove site suffix
            title = re.sub(r'\s+-\s+Zdrav zajtrk.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Extract recipe description"""
        # First try to find the first paragraph in entry-content
        entry_content = self.soup.find('div', class_=re.compile(r'entry-content|post-content'))
        if entry_content:
            paragraphs = entry_content.find_all('p')
            for p in paragraphs:
                text = self.clean_text(p.get_text())
                # Skip very short paragraphs and those that look like notices
                if text and len(text) > 50 and 'politiko zasebnosti' not in text.lower():
                    # Extract first 2-3 sentences for description
                    sentences = text.split('. ')
                    if len(sentences) >= 2:
                        # Return first 2 sentences
                        desc = sentences[0] + '. ' + sentences[1] + '.'
                        return desc
                    elif sentences:
                        # Return what we have
                        return text if text.endswith('.') else text + '.'
        
        # Fallback: Look for meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            # Extract first 2 sentences
            sentences = desc.split('. ')
            if len(sentences) >= 2:
                return sentences[0] + '. ' + sentences[1] + '.'
            return sentences[0] + '.' if sentences else desc
        
        # Alternative: from og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = self.clean_text(og_desc['content'])
            sentences = desc.split('. ')
            if len(sentences) >= 2:
                return sentences[0] + '. ' + sentences[1] + '.'
            return sentences[0] + '.' if sentences else desc
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Extract ingredients in structured format"""
        ingredients = []
        
        # Find the "Sestavine" (ingredients) heading
        sestavine_heading = None
        for heading in self.soup.find_all(['h2', 'h3', 'h4']):
            if 'Sestavine' in heading.get_text():
                sestavine_heading = heading
                break
        
        if sestavine_heading:
            # Find the next lists after "Sestavine" heading
            # Usually there are 2 lists: one for main ingredients, one for sauce
            current_element = sestavine_heading.find_next_sibling()
            ingredient_lists = []
            
            while current_element and len(ingredient_lists) < 3:
                if current_element.name in ['h2', 'h3', 'h4']:
                    # Stop if we hit another heading
                    break
                if current_element.name == 'ul' and 'wp-block-list' in current_element.get('class', []):
                    ingredient_lists.append(current_element)
                current_element = current_element.find_next_sibling()
            
            # Parse ingredients from these lists
            for ul in ingredient_lists:
                items = ul.find_all('li')
                for item in items:
                    text = self.clean_text(item.get_text())
                    if text and len(text) > 2:
                        parsed = self.parse_ingredient(text)
                        if parsed:
                            ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, text: str) -> Optional[dict]:
        """
        Parse ingredient text into structured format
        Expected format: amount unit name or amount adjective name
        Examples: "4 velika jajca", "2 žlici belega kisa", "1 skodelica ovsenih kosmičev"
        """
        if not text:
            return None
        
        # Clean text
        text = self.clean_text(text).strip()
        
        # Replace fractions
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875'
        }
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Common units in Slovenian recipes (lowercase)
        common_units = {'skodelica', 'skodelice', 'skodelico', 'žlica', 'žlice', 'žlico', 'žlici', 
                       'gram', 'grama', 'gramov', 'g', 'kg', 'ml', 'l', 'kom', 'kos', 'kosa', 'kosov',
                       'ščepec', 'rezina', 'rezine', 'rezino', 'strok', 'stroki', 'strokov'}
        
        # Common adjectives that should NOT be treated as units
        adjectives = {'velika', 'veliki', 'veliko', 'malo', 'mala', 'mali', 'srednja', 'srednje', 'srednjih',
                     'angleška', 'angleški', 'angleške', 'svež', 'sveža', 'sveže', 'svežih'}
        
        # Try pattern: number word rest
        pattern = r'^([\d\s/.,]+)\s+(\S+)\s*(.*)$'
        match = re.match(pattern, text)
        
        if match:
            amount_str, second_word, rest = match.groups()
            
            # Process amount
            amount = None
            if amount_str:
                amount_str = amount_str.strip()
                # Handle fractions like "1/2"
                if '/' in amount_str:
                    parts = amount_str.split()
                    total = 0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            total += float(part)
                    amount = int(total) if total == int(total) else total
                else:
                    try:
                        val = float(amount_str.replace(',', '.'))
                        amount = int(val) if val == int(val) else val
                    except (ValueError, TypeError):
                        amount = None
            
            # Determine if second_word is a unit or part of name
            second_lower = second_word.lower()
            unit = None
            name = None
            
            if second_lower in common_units:
                # It's a unit
                unit = second_word
                name = rest.strip() if rest else second_word
            elif second_lower in adjectives or second_word[0].isupper():
                # It's an adjective or proper name - part of ingredient name
                name = (second_word + ' ' + rest).strip()
            else:
                # Check if it might be a unit we didn't list or part of name
                # If rest exists and second_word is short, treat as unit
                if rest and len(second_word) <= 10:
                    # Might be a unit
                    unit = second_word
                    name = rest.strip()
                else:
                    # Treat as part of name
                    name = (second_word + ' ' + rest).strip() if rest else second_word
            
            # Clean name - remove parentheses, optional markers, preparation instructions
            if name:
                name = re.sub(r'\([^)]*\)', '', name)
                name = re.sub(r'\b(po želji|neobvezno|optional|or more|if needed)\b', '', name, flags=re.IGNORECASE)
                name = re.sub(r',\s*narezane?\s+na\s+.*$', '', name, flags=re.IGNORECASE)
                name = re.sub(r',\s*prerezana\s+na\s+.*$', '', name, flags=re.IGNORECASE)
                name = re.sub(r',\s*stopljenega\s*$', '', name, flags=re.IGNORECASE)
                name = re.sub(r'\s*\(lahko.*?\)', '', name, flags=re.IGNORECASE)
                name = re.sub(r'[,;]+$', '', name)
                name = re.sub(r'\s+', ' ', name).strip()
                
                if name and len(name) > 1:
                    return {
                        "name": name,
                        "units": unit,
                        "amount": amount
                    }
        
        # If no number at start, return whole text as name
        clean_name = re.sub(r'\([^)]*\)', '', text)
        clean_name = re.sub(r'\b(po želji|neobvezno)\b', '', clean_name, flags=re.IGNORECASE)
        clean_name = clean_name.strip()
        
        if clean_name:
            return {
                "name": clean_name,
                "units": None,
                "amount": None
            }
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Extract cooking instructions"""
        # Find the "Navodila" (instructions) heading
        navodila_heading = None
        for heading in self.soup.find_all(['h2', 'h3', 'h4']):
            if 'Navodila' in heading.get_text():
                navodila_heading = heading
                break
        
        if navodila_heading:
            # Find the next ordered list after "Navodila" heading
            ol = navodila_heading.find_next('ol', class_='wp-block-list')
            if ol:
                steps = []
                items = ol.find_all('li')
                for item in items:
                    step_text = self.clean_text(item.get_text())
                    if step_text:
                        steps.append(step_text)
                
                return ' '.join(steps) if steps else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Extract recipe category"""
        # Look in JSON-LD for article section
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Navigate through @graph if present
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict):
                            if item.get('@type') == 'BlogPosting' and 'articleSection' in item:
                                section = item['articleSection']
                                # Clean up category
                                if isinstance(section, str):
                                    # Remove "Recept" as it's generic
                                    categories = [c.strip() for c in section.split(',')]
                                    categories = [c for c in categories if c.lower() != 'recept']
                                    return ', '.join(categories) if categories else None
            except json.JSONDecodeError:
                continue
        
        return None
    
    def extract_time(self, time_label: str) -> Optional[str]:
        """
        Extract time values from lists or paragraphs
        time_label: 'Priprava', 'Kuhanje', 'Skupno', or similar
        """
        # Method 1: Look in headings and next paragraph
        for heading in self.soup.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text().strip()
            if time_label.lower() in heading_text.lower():
                # Check if there's a number in the heading itself
                match = re.search(r'(\d+)\s*(minut|minute|minutes)', heading_text, re.IGNORECASE)
                if match:
                    minutes = match.group(1)
                    return f"{minutes} minutes"
                
                # Check next sibling (could be p or list item)
                next_elem = heading.find_next_sibling()
                if next_elem:
                    text = next_elem.get_text().strip()
                    match = re.search(r'(\d+)\s*(minut|minute|minutes)', text, re.IGNORECASE)
                    if match:
                        minutes = match.group(1)
                        return f"{minutes} minutes"
        
        # Method 2: Look in lists
        lists = self.soup.find_all('ul', class_='wp-block-list')
        
        for ul in lists:
            items = ul.find_all('li')
            for item in items:
                text = item.get_text().strip()
                # Look for the time label
                if time_label in text:
                    # Extract the time value
                    # Format: "Priprava: 15 minut" or "Kuhanje: 20 minut"
                    match = re.search(rf'{time_label}:\s*(\d+)\s*(minut|minute|minutes)', text, re.IGNORECASE)
                    if match:
                        minutes = match.group(1)
                        return f"{minutes} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Extract preparation time"""
        # Try multiple labels
        for label in ['Priprava', 'priprav', 'Čas priprave']:
            result = self.extract_time(label)
            if result:
                return result
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Extract cooking time"""
        # Try multiple labels
        for label in ['Kuhanje', 'kuhanj', 'Čas kuhanja']:
            result = self.extract_time(label)
            if result:
                return result
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Extract total time"""
        # Try multiple labels
        for label in ['Skupno', 'skupn', 'Skupni čas']:
            result = self.extract_time(label)
            if result:
                return result
        
        # Calculate from prep + cook if available
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep and cook:
            # Extract numbers
            prep_match = re.search(r'(\d+)', prep)
            cook_match = re.search(r'(\d+)', cook)
            if prep_match and cook_match:
                total = int(prep_match.group(1)) + int(cook_match.group(1))
                return f"{total} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Extract recipe notes/tips"""
        # Find the "Nasveti" (tips) heading
        nasveti_heading = None
        for heading in self.soup.find_all(['h2', 'h3', 'h4']):
            if 'Nasveti' in heading.get_text():
                nasveti_heading = heading
                break
        
        if nasveti_heading:
            # Find the next list after "Nasveti" heading
            ul = nasveti_heading.find_next('ul', class_='wp-block-list')
            if ul:
                notes = []
                items = ul.find_all('li')
                for item in items:
                    note_text = self.clean_text(item.get_text())
                    if note_text:
                        notes.append(note_text)
                
                return ' '.join(notes) if notes else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Extract recipe tags"""
        # Look in JSON-LD for keywords
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Navigate through @graph if present
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict):
                            if item.get('@type') == 'BlogPosting' and 'keywords' in item:
                                keywords = item['keywords']
                                if isinstance(keywords, str):
                                    return keywords
                                elif isinstance(keywords, list):
                                    return ', '.join(keywords)
            except json.JSONDecodeError:
                continue
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Extract image URLs"""
        urls = []
        
        # Look in meta tags
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # Look in JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Navigate through @graph if present
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict):
                            # ImageObject
                            if item.get('@type') == 'ImageObject':
                                if 'url' in item and item['url'] not in urls:
                                    urls.append(item['url'])
                            # BlogPosting with image
                            elif item.get('@type') == 'BlogPosting' and 'image' in item:
                                img = item['image']
                                if isinstance(img, dict) and '@id' in img:
                                    img_url = img['@id']
                                    if img_url not in urls:
                                        urls.append(img_url)
                                elif isinstance(img, str) and img not in urls:
                                    urls.append(img)
            except json.JSONDecodeError:
                continue
        
        # Remove duplicates while preserving order
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
                if len(unique_urls) >= 3:  # Limit to 3 images
                    break
        
        return ','.join(unique_urls) if unique_urls else None
    
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
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # Process the preprocessed directory for zdravzajtrk_si
    preprocessed_dir = os.path.join("preprocessed", "zdravzajtrk_si")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ZdravZajtrkExtractor, str(preprocessed_dir))
        return
    
    print(f"Directory not found: {preprocessed_dir}")
    print("Usage: python zdravzajtrk_si.py")


if __name__ == "__main__":
    main()
