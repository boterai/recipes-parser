"""
Extractor for coupdepouce.com recipes
"""

import sys
from pathlib import Path
import json
import re
import html as html_module
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from extractor.base import BaseRecipeExtractor, process_directory


class CoupDePouceExtractor(BaseRecipeExtractor):
    
    def extract_from_json_ld(self) -> dict:
        """Extract data from JSON-LD schema"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                script_content = script.string
                if not script_content:
                    continue
                
                data = json.loads(script_content.strip())
                
                # Check if it's a Recipe in @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                
                # Check if it's a Recipe directly
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except json.JSONDecodeError:
                continue
        
        return {}
    
    def extract_dish_name(self) -> Optional[str]:
        """Extract dish name"""
        json_data = self.extract_from_json_ld()
        if json_data and 'name' in json_data:
            return self.clean_text(json_data['name'])
        return None
    
    def extract_description(self) -> Optional[str]:
        """Extract description - FIRST SENTENCE ONLY"""
        json_data = self.extract_from_json_ld()
        if json_data and 'description' in json_data:
            desc = json_data['description']
            desc = html_module.unescape(desc)
            desc = ' '.join(desc.split())
            desc = self.clean_text(desc)
            
            # Skip book/source references
            if not desc or 'tirée du livre' in desc.lower() or 'gracieuseté' in desc.lower():
                return None
            
            # Extract first sentence
            match = re.search(r'^(.+?[.!?])(?:\s+[A-Z]|$)', desc)
            if match:
                return match.group(1).strip()
            
            # If short enough, return as-is
            if len(desc) < 250:
                if not desc.endswith(('.', '!', '?')):
                    desc += '.'
                return desc
                
            return None
        return None
    
    def _clean_ingredient_name(self, name: str) -> str:
        """Clean ingredient name"""
        # Remove descriptions in parens first
        name = re.sub(r'\([^)]+\)', '', name)
        
        # Remove common descriptive words
        patterns = [
            r',\s*[^,]+$',  # Remove everything after last comma
            r'\bfrais(che)?s?\b',
            r'\bpelées?\b',
            r'\btranchées?\b',
            r'\bhachées?\b',
            r'\bémincées?\b',
            r'\brâpées?\b',
            r'\bpour\s+(?:la\s+)?cuisson(?:\s+au\s+four)?\b',
            r'\bpour\s+badigeonner\b',
            r'\bde\s+grosseur\s+moyenne\b',
            r'\bau\s+goût\b',
            r'\bfacultati(?:f|ve)s?\b',
            r'\bau\s+choix\b',
            r'\bgros(?:ses?)?\b',
            r'\bpeti(?:t|te)s?\b',
            r'\bsèches?\b',
            r'\blégers?\b',
        ]
        
        for pattern in patterns:
            name = re.sub(pattern, '', name, flags=re.IGNORECASE)
        
        # Clean up spaces and commas
        name = re.sub(r'\s+', ' ', name).strip()
        name = name.strip(',').strip()
        
        return name
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """Parse ingredient string"""
        if not ingredient_text:
            return None
        
        # Normalize spaces
        text = re.sub(r'\s+', ' ', ingredient_text.strip())
        
        # Pattern 1: "amount ml (parens) name" - e.g. "10 ml (2 c. à thé) huile d'olive"
        m = re.match(r'^(\d+(?:[/,]\d+)?)\s+(ml|l|g|kg)\s*\([^)]+\)\s+(.+)$', text, re.I)
        if m:
            return {
                "name": self._clean_ingredient_name(m.group(3)),
                "units": m.group(2),
                "amount": m.group(1)
            }
        
        # Pattern 2: "amount unit (parens) de/d' name" - e.g. "3 lb (1,5 kg) de pommes de terre"
        m = re.match(r'^(\d+(?:[/,]\d+)?)\s+(lb|oz|tasse|c\.\s*à\s*(?:soupe|thé)|brins?)\s*\([^)]+\)\s+(?:de?|d\')\s+(.+)$', text, re.I)
        if m:
            unit = m.group(2).strip()
            unit = re.sub(r'c\.\s*à\s*soupe', 'c. à soupe', unit, flags=re.I)
            unit = re.sub(r'c\.\s*à\s*thé', 'c. à thé', unit, flags=re.I)
            return {
                "name": self._clean_ingredient_name(m.group(3)),
                "units": unit,
                "amount": m.group(1)
            }
        
        # Pattern 3: "amount unit (parens) name" - e.g. "1/3 tasse (75 ml) d' huile"
        m = re.match(r'^(\d+(?:[/,]\d+)?)\s+(tasse|lb|oz|c\.\s*à\s*(?:soupe|thé)|brins?)\s*\([^)]+\)\s+(?:de?|d\')?\s*(.+)$', text, re.I)
        if m:
            unit = m.group(2).strip()
            unit = re.sub(r'c\.\s*à\s*soupe', 'c. à soupe', unit, flags=re.I)
            unit = re.sub(r'c\.\s*à\s*thé', 'c. à thé', unit, flags=re.I)
            return {
                "name": self._clean_ingredient_name(m.group(3)),
                "units": unit,
                "amount": m.group(1)
            }
        
        # Pattern 4: "amount unit de/d' name" - e.g. "3 brins de romarin"
        m = re.match(r'^(\d+(?:[/,]\d+)?)\s+(brins?|tasse|lb|c\.\s*à\s*(?:soupe|thé)|gros)\s+(?:de?|d\')?\s*(.+)$', text, re.I)
        if m:
            unit = m.group(2).strip()
            # Normalize
            unit = re.sub(r'c\.\s*à\s*soupe', 'c. à soupe', unit, flags=re.I)
            unit = re.sub(r'c\.\s*à\s*thé', 'c. à thé', unit, flags=re.I)
            
            # "gros" is not a unit
            if unit.lower() == 'gros':
                return {
                    "name": self._clean_ingredient_name(m.group(3)),
                    "units": None,
                    "amount": m.group(1)
                }
            
            return {
                "name": self._clean_ingredient_name(m.group(3)),
                "units": unit,
                "amount": m.group(1)
            }
        
        # Pattern 5: "amount name" - e.g. "1/2 oignon , haché"
        m = re.match(r'^(\d+(?:[/,]\d+)?)\s+(.+)$', text, re.I)
        if m:
            return {
                "name": self._clean_ingredient_name(m.group(2)),
                "units": None,
                "amount": m.group(1)
            }
        
        # Pattern 6: just name
        return {
            "name": self._clean_ingredient_name(text),
            "units": None,
            "amount": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Extract ingredients as JSON STRING"""
        json_data = self.extract_from_json_ld()
        if json_data and 'recipeIngredient' in json_data:
            ingredients_list = json_data['recipeIngredient']
            
            ingredient_items = []
            for ing in ingredients_list:
                cleaned_ing = html_module.unescape(ing)
                cleaned_ing = ' '.join(cleaned_ing.split()).strip()
                
                parsed = self.parse_ingredient(cleaned_ing)
                if parsed:
                    ingredient_items.append(parsed)
            
            if ingredient_items:
                return json.dumps(ingredient_items, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Extract instructions"""
        json_data = self.extract_from_json_ld()
        if json_data and 'recipeInstructions' in json_data:
            instructions = json_data['recipeInstructions']
            steps = []
            
            for step in instructions:
                if isinstance(step, dict) and step.get('@type') == 'HowToStep':
                    text = step.get('text', '').strip()
                    text = re.sub(r'<[^>]+>', '', text)
                    text = html_module.unescape(text)
                    text = ' '.join(text.split())
                    text = self.clean_text(text)
                    if text:
                        steps.append(text)
            
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Extract category"""
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Extract prep time"""
        json_data = self.extract_from_json_ld()
        if json_data and 'prepTime' in json_data:
            return self._convert_iso_duration(json_data['prepTime'])
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Extract cook time"""
        json_data = self.extract_from_json_ld()
        if json_data and 'cookTime' in json_data:
            return self._convert_iso_duration(json_data['cookTime'])
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Extract total time"""
        json_data = self.extract_from_json_ld()
        if json_data and 'totalTime' in json_data:
            return self._convert_iso_duration(json_data['totalTime'])
        return None
    
    def _convert_iso_duration(self, duration: str) -> Optional[str]:
        """Convert ISO 8601 duration to minutes"""
        if not duration:
            return None
        
        hours = 0
        minutes = 0
        
        h_match = re.search(r'(\d+)H', duration)
        if h_match:
            hours = int(h_match.group(1))
        
        m_match = re.search(r'(\d+)M', duration)
        if m_match:
            minutes = int(m_match.group(1))
        
        total_minutes = hours * 60 + minutes
        
        if total_minutes > 0:
            return f"{total_minutes} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Extract notes"""
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Extract tags"""
        return None
    
    def extract_all(self) -> dict:
        """Extract all recipe data"""
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
            "tags": self.extract_tags()
        }


def main():
    """Main function"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python coupdepouce_com.py <directory_path>")
        sys.exit(1)
    
    directory = sys.argv[1]
    process_directory(CoupDePouceExtractor, directory)


if __name__ == "__main__":
    main()
