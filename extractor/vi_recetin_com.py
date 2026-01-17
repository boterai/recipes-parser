"""
Extractor for vi.recetin.com recipe pages.
Extracts recipe data from HTML files in the expected format.
"""
import sys
from pathlib import Path
import json
import logging
import os
import re
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class ViRecetinComExtractor(BaseRecipeExtractor):
    """Extract recipe data from vi.recetin.com HTML pages."""

    def extract_all(self) -> Dict[str, Any]:
        """
        Extract all recipe data from the HTML page.
        
        Returns:
            dict: Recipe data with all required fields
        """
        try:
            # Use the soup that was already created by base class
            soup = self.soup
            
            # Extract all fields
            dish_name = self._extract_dish_name(soup)
            description = self._extract_description(soup)
            ingredients = self._extract_ingredients(soup)
            instructions = self._extract_instructions(soup)
            category = self._extract_category(soup)
            prep_time = self._extract_prep_time(soup)
            cook_time = self._extract_cook_time(soup)
            total_time = self._extract_total_time(soup)
            notes = self._extract_notes(soup)
            tags = self._extract_tags(soup)
            image_urls = self._extract_image_urls(soup)
            
            return {
                'dish_name': dish_name,
                'description': description,
                'ingredients': ingredients,
                'instructions': instructions,
                'category': category,
                'prep_time': prep_time,
                'cook_time': cook_time,
                'total_time': total_time,
                'notes': notes,
                'tags': tags,
                'image_urls': image_urls
            }
            
        except Exception as e:
            logger.error(f"Error extracting recipe data: {e}")
            return self._get_empty_recipe()
    
    def _get_empty_recipe(self) -> Dict[str, Any]:
        """Return empty recipe structure with all required fields set to None."""
        return {
            'dish_name': None,
            'description': None,
            'ingredients': None,
            'instructions': None,
            'category': None,
            'prep_time': None,
            'cook_time': None,
            'total_time': None,
            'notes': None,
            'tags': None,
            'image_urls': None
        }
    
    def _extract_dish_name(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract the dish name."""
        try:
            # Try h1 with class post-title
            title_elem = soup.find('h1', class_='post-title')
            if title_elem:
                return self.clean_text(title_elem.get_text())
            
            # Try any h1
            h1 = soup.find('h1')
            if h1:
                return self.clean_text(h1.get_text())
                
        except Exception as e:
            logger.warning(f"Error extracting dish name: {e}")
        
        return None
    
    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract the recipe description."""
        try:
            # Try meta description
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            if meta_desc and meta_desc.get('content'):
                return self.clean_text(meta_desc['content'])
            
            # Try meta og:description
            og_desc = soup.find('meta', attrs={'property': 'og:description'})
            if og_desc and og_desc.get('content'):
                return self.clean_text(og_desc['content'])
                
        except Exception as e:
            logger.warning(f"Error extracting description: {e}")
        
        return None
    
    def _extract_ingredients(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract ingredients from the recipe.
        Returns a JSON string representation of ingredient list.
        """
        try:
            # Find ingredients section
            ingredients_section = soup.find('div', class_='abn-recipes-ingredients')
            if not ingredients_section:
                return None
            
            ingredients_list = []
            
            # Find all list items with ingredients
            items = ingredients_section.find_all('li')
            
            for item in items:
                text = self.clean_text(item.get_text())
                if not text:
                    continue
                
                # Parse ingredient text to extract name, amount, units
                ingredient_data = self._parse_ingredient_text(text)
                if ingredient_data:
                    ingredients_list.append(ingredient_data)
            
            if ingredients_list:
                # Return as JSON string to match expected format
                return json.dumps(ingredients_list, ensure_ascii=False)
                
        except Exception as e:
            logger.warning(f"Error extracting ingredients: {e}")
        
        return None
    
    def _parse_ingredient_text(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Parse ingredient text to extract name, amount, and units.
        Example: "2 ức gà" -> {name: "ức gà", units: "pieces", amount: 2}
        Format matches reference: name, units, amount (with amount as numeric when possible)
        """
        try:
            # Pattern to match number at the beginning
            # Examples: "2 ức gà", "60 gr. bởi Maizena", "1 muỗng cà phê muối"
            
            # Try to find amount at the beginning (integer or decimal)
            amount_match = re.match(r'^(\d+(?:[,.]\\d+)?)\s+', text, re.IGNORECASE)
            
            if amount_match:
                amount_str = amount_match.group(1).replace(',', '.')
                # Try to convert to integer if possible, otherwise float
                try:
                    amount = int(amount_str) if '.' not in amount_str else float(amount_str)
                except ValueError:
                    amount = None
                
                # Get the rest of the text after the amount
                rest = text[amount_match.end():].strip()
                
                # Try to identify and remove unit from beginning of rest
                units, name = self._extract_unit_and_name(rest)
                
                return {
                    'name': name,
                    'units': units,
                    'amount': amount
                }
            else:
                # No amount found, just ingredient name
                return {
                    'name': text,
                    'units': None,
                    'amount': None
                }
                
        except Exception as e:
            logger.warning(f"Error parsing ingredient text '{text}': {e}")
            return {
                'name': text,
                'units': None,
                'amount': None
            }
    
    def _extract_unit_and_name(self, text: str) -> tuple:
        """
        Extract unit and ingredient name from text.
        Returns (units, name) tuple.
        Example: "gr. bởi Maizena" -> ("grams", "Maizena")
        Example: "ức gà" -> ("pieces", "gà")
        """
        text_lower = text.lower()
        
        # Map Vietnamese units to standard units with their regex patterns
        unit_patterns = [
            (r'^gr\.?\s+(?:bởi|của)?\s*', 'grams'),
            (r'^ml\.?\s+(?:bởi|của)?\s*', 'ml'),
            (r'^thìa\s+cà\s+phê\s+', 'teaspoon'),
            (r'^thìa\s+', 'tablespoons'),
            (r'^muỗng\s+cà\s+phê\s+', 'teaspoon'),
            (r'^muỗng\s+', 'tablespoons'),
            (r'^quả\s+', 'pieces'),
            (r'^ức\s+', 'pieces'),  # chicken breast
            (r'^lát\s+', 'slices'),
            (r'^cup\s+', 'cup'),
            (r'^kg\.?\s+(?:bởi|của)?\s*', 'kg'),
        ]
        
        for pattern, unit in unit_patterns:
            match = re.match(pattern, text_lower, re.IGNORECASE)
            if match:
                # Remove the unit and common words from the beginning
                name = text[match.end():].strip()
                # Remove common Vietnamese prep words and clean up
                name = re.sub(r'^(?:bởi|của)\s+', '', name, flags=re.IGNORECASE).strip()
                # Remove trailing comma and extra text after comma
                name = name.split(',')[0].strip()
                return (unit, name)
        
        # No unit found
        # Still clean up the name
        name = text.split(',')[0].strip()
        return (None, name)
    
    def _extract_instructions(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract cooking instructions."""
        try:
            # Find instructions section
            instructions_section = soup.find('div', class_='abn-recipes-instructions')
            if not instructions_section:
                return None
            
            # Get all text from list items
            items = instructions_section.find_all('li')
            
            if items:
                instructions_text = ' '.join([
                    self.clean_text(item.get_text()) for item in items if item.get_text().strip()
                ])
                return instructions_text if instructions_text else None
                
        except Exception as e:
            logger.warning(f"Error extracting instructions: {e}")
        
        return None
    
    def _extract_category(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract recipe category."""
        try:
            # Look for category in recipe info
            info_items = soup.find_all('li')
            
            for item in info_items:
                text = item.get_text()
                if 'Loại công thức:' in text or 'Loại:' in text:
                    # Extract category after the colon
                    parts = text.split(':')
                    if len(parts) > 1:
                        category = self.clean_text(parts[1])
                        if category:
                            return category
                            
        except Exception as e:
            logger.warning(f"Error extracting category: {e}")
        
        return None
    
    def _extract_prep_time(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract preparation time."""
        # Not readily available in the sample HTML
        return None
    
    def _extract_cook_time(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract cooking time."""
        # Not readily available in the sample HTML
        return None
    
    def _extract_total_time(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract total time."""
        # Not readily available in the sample HTML
        return None
    
    def _extract_notes(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract additional notes."""
        # Not readily available in the sample HTML
        return None
    
    def _extract_tags(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract recipe tags."""
        # Not readily available in the sample HTML
        return None
    
    def _extract_image_urls(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract image URLs from the recipe.
        Returns comma-separated URLs as a string.
        """
        try:
            image_urls = []
            
            # Try to find images in the post content
            post_content = soup.find('div', class_='post-content')
            if post_content:
                images = post_content.find_all('img')
                for img in images:
                    src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                    if src and 'http' in src:
                        # Clean up the URL
                        if src not in image_urls:
                            image_urls.append(src)
            
            # Try og:image meta tag
            og_image = soup.find('meta', attrs={'property': 'og:image'})
            if og_image and og_image.get('content'):
                url = og_image['content']
                if url not in image_urls:
                    image_urls.append(url)
            
            if image_urls:
                return ','.join(image_urls)
                
        except Exception as e:
            logger.warning(f"Error extracting image URLs: {e}")
        
        return None


def main():
    """
    Main entry point for testing the extractor.
    Processes all HTML files in preprocessed/vi_recetin_com directory.
    """
    # Get the repository root directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(current_dir)
    
    # Path to preprocessed directory
    preprocessed_dir = os.path.join(repo_root, 'preprocessed', 'vi_recetin_com')
    
    if os.path.exists(preprocessed_dir):
        print(f"Processing directory: {preprocessed_dir}")
        process_directory(ViRecetinComExtractor, preprocessed_dir)
    else:
        print(f"Directory not found: {preprocessed_dir}")


if __name__ == '__main__':
    main()
