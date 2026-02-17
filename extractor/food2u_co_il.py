"""
Recipe data extractor for the food2u.co.il website
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class Food2uExtractor(BaseRecipeExtractor):
    """Extractor for food2u.co.il"""
    
    # Maximum number of images to extract from content
    MAX_CONTENT_IMAGES = 3
    
    def extract_dish_name(self) -> Optional[str]:
        """Extract dish name"""
        # Look for meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            text = og_title['content']
            # Remove suffixes like " - Food2U", "מתכון ל...", "» פוד טו יו"
            text = re.sub(r'\s*[-–»]\s*(Food2U|פוד טו יו).*$', '', text, flags=re.IGNORECASE)
            text = re.sub(r'^מתכון\s+(ל|להכנת|להכנה\s*של)\s*', '', text)
            text = re.sub(r'^הכנת\s+', '', text)
            text = re.sub(r'^הכנה\s*של\s+', '', text)
            return self.clean_text(text)
        
        # Look for h1 heading
        h1 = self.soup.find('h1')
        if h1:
            text = self.clean_text(h1.get_text())
            if text:
                text = re.sub(r'^מתכון\s+(ל|להכנת|להכנה\s*של)\s*', '', text)
                text = re.sub(r'^הכנת\s+', '', text)
                text = re.sub(r'^הכנה\s*של\s+', '', text)
                return text
        
        # Alternatively - from title tag
        title = self.soup.find('title')
        if title:
            text = title.get_text()
            text = re.sub(r'\s*[-–»]\s*(Food2U|פוד טו יו).*$', '', text, flags=re.IGNORECASE)
            text = re.sub(r'^מתכון\s+(ל|להכנת|להכנה\s*של)\s*', '', text)
            text = re.sub(r'^הכנת\s+', '', text)
            text = re.sub(r'^הכנה\s*של\s+', '', text)
            text = self.clean_text(text)
            if text:
                return text
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Extract recipe description"""
        # Look for meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Alternatively - from og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        # Look for first paragraph after heading
        content_div = self.soup.find('div', class_=re.compile(r'post-content|entry-content|elementor-widget-theme-post-content', re.I))
        if content_div:
            # Look for first paragraph that is not a heading
            paragraphs = content_div.find_all('p')
            for p in paragraphs:
                text = self.clean_text(p.get_text())
                # Check that this is not too short text and not a heading
                if text and len(text) > 20 and not text.endswith(':'):
                    return text
        
        return None
    
    def parse_ingredient_text(self, ingredient_text: str) -> Optional[dict]:
        """
        Parse ingredient string into structured format for Hebrew text
        
        Args:
            ingredient_text: String like "2 כוסות קוסקוס" or "500 גרם בשר טחון"
            
        Returns:
            dict: {"name": "קוסקוס", "amount": 2, "units": "כוסות"} or None
        """
        if not ingredient_text:
            return None
        
        # Clean text
        text = self.clean_text(ingredient_text)
        
        # Pattern for extracting amount, unit and name
        # Format: [number] [unit] [name] (for Hebrew)
        # Examples: "2 כוסות קוסקוס", "500 גרם בשר", "מלח לפי הטעם"
        
        # First try to extract number at the beginning
        number_match = re.match(r'^([\d.,/]+)\s+(.+)$', text)
        
        if number_match:
            amount_str = number_match.group(1)
            rest = number_match.group(2)
            
            # Processing fractions like "1/2"
            if '/' in amount_str:
                parts = amount_str.split('/')
                if len(parts) == 2:
                    try:
                        amount = float(parts[0]) / float(parts[1])
                    except (ValueError, ZeroDivisionError):
                        amount = amount_str
                else:
                    amount = amount_str
            else:
                try:
                    # Try to convert to number
                    if '.' in amount_str or ',' in amount_str:
                        amount = float(amount_str.replace(',', '.'))
                    else:
                        amount_num = int(amount_str)
                        # Keep as int if it's a whole number
                        amount = amount_num
                except ValueError:
                    amount = amount_str
            
            # Now try to extract unit of measurement
            # Common Hebrew units: כוסות, כפות, כף, גרם, ק"ג, ליטר, מ"ל, יחידה, יחידות, חופן
            unit_patterns = [
                r'^(כוסות|כוס|כפות|כף|כפית|כפיות|גרם|ק"ג|קילוגרם|ליטר|מ"ל|מיליליטר|יחידה|יחידות|חופן|חופנים)\s+(.+)$',
            ]
            
            unit = None
            name = rest
            
            for pattern in unit_patterns:
                unit_match = re.match(pattern, rest)
                if unit_match:
                    unit = unit_match.group(1)
                    name = unit_match.group(2)
                    break
            
            # Clean name from phrases "לפי הטעם", "(אופציונלי)" и т.д.
            name = re.sub(r'\s*\(אופציונלי\)', '', name)
            name = re.sub(r'\s*(לפי הטעם|לפי הצורך|אופציונלי|לקישוט)$', '', name)
            name = self.clean_text(name)
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        else:
            # If there's no number at the beginning, it could be "מלח לפי הטעם"
            # Check if there is "לפי הטעם" в конце
            if 'לפי הטעם' in text:
                # Extract name without "לפי הטעם"
                name = re.sub(r'\s*לפי הטעם\s*', '', text)
                name = self.clean_text(name)
                return {
                    "name": name,
                    "amount": None,
                    "units": "לפי הטעם"
                }
            
            # Look for unit without amount
            unit_patterns = [
                r'^(כוסות|כוס|כפות|כף|כפית|כפיות|גרם|ק"ג|קילוגרם|ליטר|מ"ל|מיליליטר|יחידה|יחידות|חופן|חופנים)\s+(.+)$',
            ]
            
            for pattern in unit_patterns:
                unit_match = re.match(pattern, text)
                if unit_match:
                    unit_or_phrase = unit_match.group(1)
                    name = unit_match.group(2)
                    name = re.sub(r'\s*\(אופציונלי\)', '', name)
                    name = self.clean_text(name)
                    return {
                        "name": name,
                        "amount": None,
                        "units": unit_or_phrase
                    }
            
            # If nothing matched, return only name
            name = re.sub(r'\s*\(אופציונלי\)', '', text)
            name = self.clean_text(name)
            return {
                "name": name,
                "amount": None,
                "units": None
            }
    
    def extract_ingredients(self) -> Optional[str]:
        """Extract ingredients"""
        ingredients = []
        
        # Look for heading "מרכיבים:" (Ингредиенты)
        content_div = self.soup.find('div', class_=re.compile(r'post-content|entry-content|elementor-widget-theme-post-content', re.I))
        
        if content_div:
            # Look for all h2/h3 headings and paragraphs
            headers = content_div.find_all(['h2', 'h3'])
            
            for header in headers:
                header_text = self.clean_text(header.get_text())
                
                # Check that this is ingredients heading
                if header_text and ('מרכיבים' in header_text or 'מצרכים' in header_text):
                    # Look for next ul or ol list after heading
                    next_elem = header.find_next_sibling()
                    
                    while next_elem:
                        if next_elem.name in ['ul', 'ol']:
                            # Found ingredients list
                            items = next_elem.find_all('li')
                            
                            for item in items:
                                ingredient_text = self.clean_text(item.get_text())
                                
                                if ingredient_text:
                                    parsed = self.parse_ingredient_text(ingredient_text)
                                    if parsed:
                                        ingredients.append(parsed)
                            
                            break
                        elif next_elem.name == 'p':
                            # Check if there's "מצרכים:" in paragraph or list with <br>
                            p_text = next_elem.get_text()
                            if 'מצרכים:' in p_text:
                                # Extract ingredients from paragraph separated by <br>
                                # Split by <br> tags
                                lines = []
                                for content in next_elem.children:
                                    if content.name == 'br':
                                        continue
                                    elif isinstance(content, str):
                                        lines.append(content.strip())
                                
                                # Join lines separated by br
                                full_text = str(next_elem).replace('<br>', '\n').replace('<br/>', '\n')
                                temp_soup = BeautifulSoup(full_text, 'lxml')
                                text = temp_soup.get_text()
                                
                                # Split by newlines
                                lines = text.split('\n')
                                
                                # Skip first line if it's "מצרכים:"
                                for line in lines:
                                    line = self.clean_text(line)
                                    if line and line != 'מצרכים:' and len(line) > 3:
                                        parsed = self.parse_ingredient_text(line)
                                        if parsed:
                                            ingredients.append(parsed)
                                
                                break
                            next_elem = next_elem.find_next_sibling()
                        elif next_elem.name in ['h2', 'h3']:
                            # Reached next heading, stop search
                            break
                        else:
                            next_elem = next_elem.find_next_sibling()
                    
                    # If found ingredients, exit
                    if ingredients:
                        break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Extract cooking instructions"""
        instructions = []
        
        # Look for heading "הוראות הכנה:" или подобный
        content_div = self.soup.find('div', class_=re.compile(r'post-content|entry-content|elementor-widget-theme-post-content', re.I))
        
        if content_div:
            # First check if there's paragraph with "אופן ההכנה:" directly (as in lasagna)
            all_paragraphs = content_div.find_all('p')
            for p in all_paragraphs:
                p_text = p.get_text()
                if 'אופן ההכנה:' in p_text or ('הוראות' in p_text and ':' in p_text):
                    # Extract instructions from paragraph separated by <br>
                    full_text = str(p).replace('<br>', '\n').replace('<br/>', '\n')
                    temp_soup = BeautifulSoup(full_text, 'lxml')
                    text = temp_soup.get_text()
                    
                    # Remove heading "אופן ההכנה:" если есть
                    text = re.sub(r'^אופן ההכנה:\s*', '', text)
                    text = re.sub(r'^הוראות הכנה:\s*', '', text)
                    
                    # Take text as one instruction
                    text = self.clean_text(text)
                    if text and len(text) > 10:
                        instructions.append(text)
                    
                    # Found, exit
                    if instructions:
                        return ' '.join(instructions) if instructions else None
            
            # If not found directly, look for all headings h2/h3
            headers = content_div.find_all(['h2', 'h3'])
            
            for header in headers:
                header_text = self.clean_text(header.get_text())
                
                # Check that this is instructions heading
                if header_text and ('הוראות' in header_text or 'הכנה' in header_text):
                    # Collect all paragraphs after heading until next h2/h3
                    next_elem = header.find_next_sibling()
                    step_num = 1
                    
                    while next_elem:
                        if next_elem.name == 'p':
                            text = self.clean_text(next_elem.get_text())
                            
                            if text and len(text) > 10:
                                # Remove bold text of step heading if present
                                # For example: "<strong>הכנת הקוסקוס:</strong> מעבירים..."
                                text = re.sub(r'^[^:]+:\s*', '', text)
                                
                                # Add numbering if not present
                                if not re.match(r'^\d+\.', text):
                                    text = f"{step_num}. {text}"
                                    step_num += 1
                                
                                instructions.append(text)
                        
                        elif next_elem.name in ['ol', 'ul']:
                            # If instructions as list
                            items = next_elem.find_all('li')
                            for item in items:
                                text = self.clean_text(item.get_text())
                                if text:
                                    if not re.match(r'^\d+\.', text):
                                        text = f"{step_num}. {text}"
                                        step_num += 1
                                    instructions.append(text)
                        
                        elif next_elem.name in ['h2', 'h3']:
                            # Reached next heading
                            break
                        
                        next_elem = next_elem.find_next_sibling()
                    
                    # If found instructions, exit
                    if instructions:
                        break
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Extract category"""
        # Look for meta article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Look for breadcrumbs (breadcrumbs)
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                # Take second to last category
                return self.clean_text(links[-2].get_text())
        
        # Look for category classes
        content = self.soup.find('div', class_=re.compile(r'category-'))
        if content:
            classes = content.get('class', [])
            for cls in classes:
                if cls.startswith('category-') and cls != 'category-food':
                    # Extract category name from class
                    cat_name = cls.replace('category-', '').replace('-', ' ')
                    return self.clean_text(cat_name)
        
        return None
    
    def extract_time_from_text(self, time_type: str) -> Optional[str]:
        """
        Extract time from instruction text
        
        Args:
            time_type: 'prep', 'cook', or 'total'
        """
        # Look for time in instructions text
        content_div = self.soup.find('div', class_=re.compile(r'post-content|entry-content|elementor-widget-theme-post-content', re.I))
        
        if not content_div:
            return None
        
        # Get all content text
        text = content_div.get_text()
        
        # Patterns for searching time in minutes
        # Examples: "5-10 דקות", "35 דקות", "כ-35 דקות"
        time_patterns = [
            r'(\d+)-(\d+)\s*דקות',  # "5-10 דקות"
            r'כ-(\d+)\s*דקות',      # "כ-35 דקות" (около X минут)
            r'(\d+)\s*דקות',        # "35 דקות"
        ]
        
        for pattern in time_patterns:
            matches = re.findall(pattern, text)
            if matches:
                # Take first match
                match = matches[0]
                if isinstance(match, tuple):
                    # For patterns with range or "около"
                    if len(match) == 2:
                        # Take average value for range
                        try:
                            avg = (int(match[0]) + int(match[1])) / 2
                            return f"{int(avg)} minutes"
                        except ValueError:
                            pass
                    elif len(match) == 1:
                        return f"{match[0]} minutes"
                else:
                    return f"{match} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Extract preparation time"""
        return self.extract_time_from_text('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Extract cooking time"""
        return self.extract_time_from_text('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Extract total time"""
        return self.extract_time_from_text('total')
    
    def extract_notes(self) -> Optional[str]:
        """Extract notes and tips"""
        # Look for paragraphs with tips after main instructions
        content_div = self.soup.find('div', class_=re.compile(r'post-content|entry-content|elementor-widget-theme-post-content', re.I))
        
        if content_div:
            # Look for heading инструкций
            headers = content_div.find_all(['h2', 'h3'])
            found_instructions = False
            
            for header in headers:
                header_text = self.clean_text(header.get_text())
                
                if header_text and ('הוראות' in header_text or 'הכנה' in header_text):
                    found_instructions = True
                    # Look for paragraphs after instructions that could be notes
                    next_elem = header.find_next_sibling()
                    paragraphs_after_instructions = []
                    
                    while next_elem:
                        if next_elem.name == 'p':
                            paragraphs_after_instructions.append(next_elem)
                        elif next_elem.name in ['h2', 'h3']:
                            break
                        next_elem = next_elem.find_next_sibling()
                    
                    # Take last paragraph after instructions as note
                    if paragraphs_after_instructions:
                        for p in reversed(paragraphs_after_instructions):
                            text = self.clean_text(p.get_text())
                            # Check that this is not an instruction step
                            if text and len(text) > 20 and not re.match(r'^\d+\.', text):
                                # Check that paragraph contains tips/recommendations
                                if any(word in text for word in ['כדי', 'ניתן', 'מומלץ', 'טיפ', 'שדרג']):
                                    return text
                    
                    break
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Extract tags"""
        # Look for meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        # Look for category classes and tags
        tags = []
        
        # Check article:tag meta tags
        article_tags = self.soup.find_all('meta', property='article:tag')
        for tag in article_tags:
            if tag.get('content'):
                tags.append(self.clean_text(tag['content']))
        
        if tags:
            return ', '.join(tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Extract image URLs"""
        urls = []
        
        # 1. Ищем в meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в meta twitter:image
        twitter_image = self.soup.find('meta', {'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Look for images in content
        content_div = self.soup.find('div', class_=re.compile(r'post-content|entry-content|elementor-widget-theme-post-content', re.I))
        if content_div:
            images = content_div.find_all('img')
            for img in images[:self.MAX_CONTENT_IMAGES]:  # Take first N images from content
                src = img.get('src') or img.get('data-src')
                if src and src.startswith('http'):
                    urls.append(src)
        
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Process all HTML files in the preprocessed/food2u_co_il directory"""
    import os
    
    # Path to directory with preprocessed files
    preprocessed_dir = os.path.join("preprocessed", "food2u_co_il")
    
    # Check directory existence
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(Food2uExtractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python food2u_co_il.py")


if __name__ == "__main__":
    main()
