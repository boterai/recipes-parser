"""
Recipe data extractor for foodiepedia.co.il
"""

import logging
import sys
from pathlib import Path
import json
import re
from bs4 import BeautifulSoup
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class FoodiepediaExtractor(BaseRecipeExtractor):
    """Extractor for foodiepedia.co.il"""

    def _get_json_ld_data(self) -> Optional[dict]:
        """Extract Recipe JSON-LD data from the page"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')

        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue

                data = json.loads(script.string)

                if isinstance(data, dict):
                    if data.get('@type') == 'Recipe':
                        return data
                    # Check inside @graph
                    for item in data.get('@graph', []):
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item

                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item

            except (json.JSONDecodeError, KeyError):
                logger.debug("Failed to parse JSON-LD script", exc_info=True)
                continue

        return None

    @staticmethod
    def _parse_time_value(value: Optional[str]) -> Optional[str]:
        """
        Convert a time value to a human-readable format.

        Handles:
        - Plain integer strings: "15" -> "15 minutes"
        - ISO 8601 duration: "PT30M" -> "30 minutes", "PT1H30M" -> "90 minutes"
        - Malformed ISO: "PT15M10M" -> parsed best-effort
        """
        if not value:
            return None

        value = str(value).strip()

        # Plain integer (minutes)
        if re.match(r'^\d+$', value):
            minutes = int(value)
            return f"{minutes} minutes" if minutes > 0 else None

        # ISO 8601 duration (PT...)
        if value.upper().startswith('PT'):
            duration = value[2:]
            hours = 0
            minutes = 0

            hour_match = re.search(r'(\d+)H', duration, re.IGNORECASE)
            if hour_match:
                hours = int(hour_match.group(1))

            # Find all minute values and sum them (handles malformed "PT15M10M")
            min_matches = re.findall(r'(\d+)M', duration, re.IGNORECASE)
            for m in min_matches:
                minutes += int(m)

            total_minutes = hours * 60 + minutes
            return f"{total_minutes} minutes" if total_minutes > 0 else None

        return None

    def extract_dish_name(self) -> Optional[str]:
        """Extract dish name"""
        json_ld = self._get_json_ld_data()

        if json_ld and json_ld.get('name'):
            return self.clean_text(json_ld['name'])

        # Fallback: H1 heading
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        # Fallback: og:title meta
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        return None

    def extract_description(self) -> Optional[str]:
        """Extract recipe description"""
        json_ld = self._get_json_ld_data()

        if json_ld and json_ld.get('description'):
            return self.clean_text(json_ld['description'])

        # Fallback: meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        # Fallback: og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    # Known Hebrew unit strings (longer forms first to avoid partial matches)
    _HEBREW_UNITS = [
        'כוסות', 'כוס', 'כפות', 'כף', 'כפיות', 'כפית',
        'ק"ג', 'גרם', 'מ"ל', 'מיליליטר', 'ליטר',
        'יחידות', 'יחידה', 'ענפים', 'ענף', 'שיניים', 'שן',
        'חבילות', 'חבילה', 'קופסאות', 'קופסה',
        'פרוסות', 'פרוסה', 'חתיכות', 'חתיכה',
        'כדורים', 'כדור', 'עלים', 'עלה', 'ראשים', 'ראש',
    ]

    def _parse_hebrew_ingredient(self, text: str) -> Optional[dict]:
        """
        Parse a Hebrew ingredient string into structured format.

        Handles patterns like:
            "1 כוס קמח לבן"              -> amount=1,   units="כוס",   name="קמח לבן"
            "חצי כפית מלח"               -> amount=0.5, units="כפית",  name="מלח"
            "רבע כוס אגוזים"             -> amount=0.25,units="כוס",   name="אגוזים"
            "1 וחצי כוסות שוקולד"        -> amount=1.5, units="כוסות", name="שוקולד"
            "כוס וחצי קמח לבן"           -> amount=1.5, units="כוס",   name="קמח לבן"
            "כפית אבקת סודה לשתייה"      -> amount=1,   units="כפית",  name="אבקת סודה לשתייה"
            "ביצה גדולה"                  -> amount=None, units=None,  name="ביצה גדולה"
        """
        if not text:
            return None

        text = self.clean_text(text)

        # Replace unicode fractions
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8',
        }
        for frac, dec in fraction_map.items():
            text = text.replace(frac, dec)

        # Remove optional suffix before parsing
        text = re.sub(r'\s*\([^)]*(?:אופציונלי|לא\s+חובה|אופציה)[^)]*\)\s*$', '', text).strip()

        # ---- Amount extraction ----
        amount: Optional[float] = None
        remaining = text

        # Pattern: "N וחצי ..." (e.g. "1 וחצי")
        m = re.match(r'^([\d.,/]+)\s+וחצי\s+(.*)', remaining)
        if m:
            try:
                base = self._to_float(m.group(1))
                if base is not None:
                    amount = base + 0.5
                    remaining = m.group(2).strip()
            except (ValueError, TypeError):
                pass

        if amount is None:
            # Pattern: plain number at start
            m = re.match(r'^([\d.,/]+)\s+(.*)', remaining)
            if m:
                val = self._to_float(m.group(1))
                if val is not None:
                    amount = val
                    remaining = m.group(2).strip()

        if amount is None:
            # Hebrew number words
            hebrew_halves = {
                r'^חצי\s+': 0.5,
                r'^רבע\s+': 0.25,
                r'^שלושה\s+רבעי\s+': 0.75,
                r'^שני\s+שליש\s+': 0.67,
            }
            for pattern, val in hebrew_halves.items():
                m = re.match(pattern, remaining)
                if m:
                    amount = val
                    remaining = remaining[m.end():]
                    break

        # ---- Unit extraction ----
        units: Optional[str] = None
        unit_pattern = '|'.join(re.escape(u) for u in self._HEBREW_UNITS)

        # Unit followed by "וחצי" (e.g. "כוס וחצי")
        m = re.match(r'^(' + unit_pattern + r')\s+וחצי\s+(.*)', remaining, re.IGNORECASE)
        if m:
            units = m.group(1)
            base_amount = amount if amount is not None else 1.0
            amount = base_amount + 0.5
            remaining = m.group(2).strip()
        else:
            # Plain unit
            m = re.match(r'^(' + unit_pattern + r')\s+(.*)', remaining, re.IGNORECASE)
            if m:
                units = m.group(1)
                remaining = m.group(2).strip()
                # When unit present but no numeric amount found, default to 1
                if amount is None:
                    amount = 1

        # ---- Name cleanup ----
        name = remaining
        name = re.sub(r'\([^)]*\)', '', name)
        name = re.sub(r'\s+', ' ', name).strip()

        if not name or len(name) < 2:
            return None

        # Convert float to int when it's a whole number
        if isinstance(amount, float) and amount == int(amount):
            amount = int(amount)

        return {"name": name, "amount": amount, "units": units}

    @staticmethod
    def _to_float(s: str) -> Optional[float]:
        """Convert a numeric string (possibly a fraction) to float"""
        s = s.strip().replace(',', '.')
        if '/' in s:
            parts = s.split()
            total = 0.0
            for part in parts:
                if '/' in part:
                    try:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    except (ValueError, ZeroDivisionError):
                        return None
                else:
                    try:
                        total += float(part)
                    except ValueError:
                        return None
            return total
        try:
            return float(s)
        except ValueError:
            return None

    def extract_ingredients(self) -> Optional[str]:
        """Extract ingredients list as JSON string"""
        ingredients = []

        json_ld = self._get_json_ld_data()

        if json_ld and json_ld.get('recipeIngredient'):
            for ingredient_text in json_ld['recipeIngredient']:
                parsed = self._parse_hebrew_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        # Fallback: parse from HTML ingredient list
        ingr_list = self.soup.find('ul', class_=re.compile(r'ingredient', re.I))
        if ingr_list:
            for li in ingr_list.find_all('li'):
                text = self.clean_text(li.get_text())
                parsed = self._parse_hebrew_ingredient(text)
                if parsed:
                    ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """Extract cooking instructions"""
        json_ld = self._get_json_ld_data()

        steps = []

        if json_ld and json_ld.get('recipeInstructions'):
            instructions = json_ld['recipeInstructions']
            step_num = 1

            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict):
                        raw_text = step.get('text', '')
                    elif isinstance(step, str):
                        raw_text = step
                    else:
                        continue

                    # Strip HTML tags from step text
                    step_soup = BeautifulSoup(raw_text, 'lxml')
                    step_text = self.clean_text(step_soup.get_text())

                    # Remove inline step labels like "שלב 1:", "Step 1:"
                    step_text = re.sub(r'^שלב\s+\d+[:\s]*', '', step_text).strip()
                    step_text = re.sub(r'^Step\s+\d+[:\s]*', '', step_text, flags=re.IGNORECASE).strip()

                    if step_text:
                        steps.append(f"{step_num}. {step_text}")
                        step_num += 1

            elif isinstance(instructions, str):
                text = self.clean_text(BeautifulSoup(instructions, 'lxml').get_text())
                if text:
                    steps.append(text)

        if steps:
            return ' '.join(steps)

        # Fallback: parse from HTML
        instructions_section = self.soup.find(['ol', 'div'], class_=re.compile(r'instruction|step', re.I))
        if instructions_section:
            items = instructions_section.find_all('li') or instructions_section.find_all('p')
            for idx, item in enumerate(items, 1):
                text = self.clean_text(item.get_text())
                if text:
                    steps.append(f"{idx}. {text}")

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Extract recipe category"""
        json_ld = self._get_json_ld_data()

        if json_ld:
            category = json_ld.get('recipeCategory')
            if category:
                if isinstance(category, list):
                    return ', '.join(str(c) for c in category)
                return self.clean_text(str(category))

            cuisine = json_ld.get('recipeCuisine')
            if cuisine:
                if isinstance(cuisine, list):
                    return ', '.join(str(c) for c in cuisine)
                return self.clean_text(str(cuisine))

        # Fallback: breadcrumb
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Extract preparation time"""
        json_ld = self._get_json_ld_data()

        if json_ld and json_ld.get('prepTime'):
            return self._parse_time_value(json_ld['prepTime'])

        return None

    def extract_cook_time(self) -> Optional[str]:
        """Extract cooking time"""
        json_ld = self._get_json_ld_data()

        if json_ld and json_ld.get('cookTime'):
            return self._parse_time_value(json_ld['cookTime'])

        return None

    def extract_total_time(self) -> Optional[str]:
        """Extract total time; computes from prep+cook if JSON-LD totalTime is unreliable"""
        json_ld = self._get_json_ld_data()

        if json_ld:
            total = self._parse_time_value(json_ld.get('totalTime'))
            if total:
                return total

            # Compute from prep + cook
            prep_raw = json_ld.get('prepTime')
            cook_raw = json_ld.get('cookTime')

            prep_min = self._extract_minutes(prep_raw)
            cook_min = self._extract_minutes(cook_raw)

            if prep_min is not None or cook_min is not None:
                total_min = (prep_min or 0) + (cook_min or 0)
                if total_min > 0:
                    return f"{total_min} minutes"

        return None

    @staticmethod
    def _extract_minutes(value: Optional[str]) -> Optional[int]:
        """Extract number of minutes from a time string or plain number"""
        if not value:
            return None

        value = str(value).strip()

        # Plain integer
        if re.match(r'^\d+$', value):
            return int(value)

        # ISO duration
        if value.upper().startswith('PT'):
            duration = value[2:]
            hours = 0
            minutes = 0
            hour_match = re.search(r'(\d+)H', duration, re.IGNORECASE)
            if hour_match:
                hours = int(hour_match.group(1))
            min_matches = re.findall(r'(\d+)M', duration, re.IGNORECASE)
            for m in min_matches:
                minutes += int(m)
            return hours * 60 + minutes

        return None

    def extract_notes(self) -> Optional[str]:
        """Extract notes from the 'תוספות ושדרוגים' (additions/upgrades) section"""
        # Look for a heading that mentions tips/additions
        note_heading_patterns = [
            'תוספות',   # additions
            'שדרוגים',  # upgrades
            'טיפים',    # tips
            'הערות',    # notes/remarks
            'הע',       # note (abbreviated)
        ]

        for heading in self.soup.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text(strip=True)
            if any(kw in heading_text for kw in note_heading_patterns):
                # Collect text from following siblings until next heading
                parts = []
                sibling = heading.find_next_sibling()
                while sibling and sibling.name not in ['h2', 'h3', 'h4']:
                    text = self.clean_text(sibling.get_text(separator=' '))
                    if text:
                        parts.append(text)
                    sibling = sibling.find_next_sibling()

                if parts:
                    return ' '.join(parts)

                # Alternatively, try the parent container
                parent = heading.parent
                if parent:
                    all_text = parent.get_text(separator=' ')
                    # Remove the heading itself
                    all_text = all_text.replace(heading_text, '', 1)
                    cleaned = self.clean_text(all_text)
                    if cleaned:
                        return cleaned

        return None

    def extract_tags(self) -> Optional[str]:
        """Extract tags from recipeCategory in JSON-LD or HTML tag links"""
        json_ld = self._get_json_ld_data()

        tags = []

        if json_ld:
            for field in ('recipeCategory', 'recipeCuisine', 'cookingMethod'):
                value = json_ld.get(field)
                if not value:
                    continue
                if isinstance(value, list):
                    tags.extend(str(v).strip() for v in value if v)
                elif value:
                    tags.append(str(value).strip())

        # Fallback / supplement: HTML tag links (rel="tag")
        if not tags:
            for link in self.soup.find_all('a', rel=re.compile(r'\btag\b', re.I)):
                text = link.get_text(strip=True)
                if text:
                    tags.append(text)

        if not tags:
            return None

        # Deduplicate preserving order
        seen: set = set()
        unique_tags = []
        for tag in tags:
            key = tag.strip()
            if key and key not in seen:
                seen.add(key)
                unique_tags.append(key)

        return ', '.join(unique_tags) if unique_tags else None

    def extract_image_urls(self) -> Optional[str]:
        """Extract image URLs"""
        urls = []

        json_ld = self._get_json_ld_data()

        if json_ld and json_ld.get('image'):
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                url = img.get('url') or img.get('contentUrl')
                if url:
                    urls.append(url)
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        url = item.get('url') or item.get('contentUrl')
                        if url:
                            urls.append(url)

        # Also check @graph for ImageObject
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                graph = data.get('@graph', []) if isinstance(data, dict) else []
                for item in graph:
                    if isinstance(item, dict) and item.get('@type') == 'ImageObject':
                        url = item.get('url') or item.get('contentUrl')
                        if url:
                            urls.append(url)
            except (json.JSONDecodeError, KeyError):
                continue

        # Fallback: meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # Fallback: twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])

        if not urls:
            return None

        # Deduplicate preserving order
        seen: set = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ','.join(unique_urls) if unique_urls else None

    def extract_all(self) -> dict:
        """
        Extract all recipe data.

        Returns:
            dict with recipe data fields
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
            "tags": self.extract_tags(),
        }


def main():
    """Entry point: process HTML files in preprocessed/foodiepedia_co_il"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "foodiepedia_co_il")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(FoodiepediaExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python foodiepedia_co_il.py")


if __name__ == "__main__":
    main()
