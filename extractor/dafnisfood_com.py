"""
Экстрактор данных рецептов для сайта dafnisfood.com
"""

import sys
from pathlib import Path
import json
import re
import logging
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class DafnisFoodExtractor(BaseRecipeExtractor):
    """Экстрактор для dafnisfood.com"""

    # Keywords that indicate an ingredient-list section header
    _INGREDIENT_HEADER_KW = ['צריך', 'נזדקק', 'מרכיבים', 'מצרכים']

    # Keywords that indicate an instruction/method section header
    _INSTRUCTION_HEADER_KW = ['מכינים', 'אופן ההכנה', 'אופן', 'הכנת הרטבים', 'הכנת ה']

    # Hebrew units (singular and plural forms) – ordered longest first
    _HEBREW_UNITS = [
        'כפיות', 'כפית',
        'כפות', 'כף',
        'כוסות', 'כוס',
        'קילוגרם', "ק\"ג", 'קילו',
        'גרם',
        "מ\"ל", "מיליליטר",
        'ליטר',
        'חבילות', 'חבילה',
        'יחידות', 'יחידה',
        'פרוסות', 'פרוסה',
        'צרורות', 'צרור',
        'ענפים', 'ענף',
        'שיני', 'שן',
        'עלים', 'עלה',
        'רבעים', 'רבע',
        'חצאים', 'חצי',
    ]

    # Hebrew adjectives that can follow a unit (e.g. "כפות גדושות") – strip from name
    _UNIT_ADJECTIVES = ['גדושות', 'גדוש', 'שטוחות', 'שטוח', 'מלאות', 'מלא', 'קטנות', 'קטן']

    # Category slug → English label mapping
    _CATEGORY_MAP = {
        'main-course': 'Main Course',
        'meat': 'Main Course',
        'chicken': 'Main Course',
        'fish': 'Main Course',
        'vegetarian': 'Main Course',
        'vegan': 'Main Course',
        'asia': 'Main Course',
        'one-pot-meal': 'Main Course',
        'pasta': 'Main Course',
        'salad': 'Salad',
        'soup': 'Soup',
        'cakes-dessert': 'Dessert',
        'cream-cake': 'Dessert',
        'yeast-cake': 'Dessert',
        'cookies': 'Dessert',
        'chocolate': 'Dessert',
        'breakfast': 'Breakfast',
        'bread': 'Bread',
        'appetizer': 'Appetizer',
        'side-dish': 'Side Dish',
    }

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _get_pf_content(self):
        """Return the main post-content div."""
        return self.soup.find('div', class_='pf-content')

    def _is_ingredient_line(self, text: str) -> bool:
        """Return True if the text looks like an ingredient line."""
        # Starts with a digit, Unicode fraction, or slash-fraction
        return bool(re.match(r'^[\d½¼¾⅓⅔⅛⅜⅝⅞/]', text))

    def _classify_header(self, p, paragraphs, idx: int) -> Optional[str]:
        """
        If paragraph *p* is a section header (has a <strong> child), return
        'ingredients', 'instructions', or None (non-header).
        Uses lookahead when the header type is ambiguous.
        """
        if not p.find('strong'):
            return None

        text = p.get_text().strip()

        # Must end with ':' or '?' to count as a section header
        if not (text.endswith(':') or text.endswith('?')):
            return None

        if any(kw in text for kw in self._INGREDIENT_HEADER_KW):
            return 'ingredients'

        if any(kw in text for kw in self._INSTRUCTION_HEADER_KW):
            return 'instructions'

        # Ambiguous header – only switch to 'ingredients' if next line looks like an ingredient.
        # Otherwise keep current state (return None).
        for j in range(idx + 1, min(idx + 5, len(paragraphs))):
            next_text = paragraphs[j].get_text().strip()
            if next_text:
                return 'ingredients' if self._is_ingredient_line(next_text) else None

        return None

    def _parse_content_sections(self):
        """
        Walk the pf-content paragraphs and classify them into
        description, ingredient lines, and instruction steps.

        Returns:
            (description_parts, ingredient_lines, instruction_steps) as lists of str
        """
        pf_content = self._get_pf_content()
        if not pf_content:
            return [], [], []

        paragraphs = pf_content.find_all('p')

        state = 'description'
        description_parts: list = []
        ingredient_lines: list = []
        instruction_steps: list = []

        for idx, p in enumerate(paragraphs):
            text = p.get_text().strip()
            if not text:
                continue

            # Check if this paragraph is a section header
            section = self._classify_header(p, paragraphs, idx)
            if section is not None:
                state = section
                continue  # don't add the header text itself

            if state == 'description':
                # If we encounter an ingredient-looking line without a prior header,
                # switch to ingredients mode
                if self._is_ingredient_line(text):
                    state = 'ingredients'
                    ingredient_lines.append(text)
                else:
                    description_parts.append(text)

            elif state == 'ingredients':
                # A long sentence ending with a full stop signals an instruction
                # that started without an explicit header
                if len(text) > 60 and text.endswith('.'):
                    state = 'instructions'
                    instruction_steps.append(text)
                else:
                    ingredient_lines.append(text)

            elif state == 'instructions':
                # Skip inline sub-headers (strong text ending with ':')
                if p.find('strong') and text.endswith(':') and len(text) < 40:
                    continue
                instruction_steps.append(text)

        return description_parts, ingredient_lines, instruction_steps

    # ------------------------------------------------------------------ #
    #  Ingredient parser                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _replace_unicode_fractions(text: str) -> str:
        """Replace Unicode fraction chars with decimal equivalents."""
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
        }
        for char, decimal in fraction_map.items():
            text = text.replace(char, decimal)
        return text

    def _parse_ingredient(self, raw: str) -> Optional[dict]:
        """
        Parse a Hebrew ingredient line into {name, amount, units}.

        Expected format: [amount] [units] ingredient_name [optional notes]
        e.g. "2 כוסות קמח" → {name: "קמח", amount: 2, units: "כוסות"}
             "מלח ופלפל"   → {name: "מלח ופלפל", amount: None, units: None}
        """
        if not raw:
            return None

        text = self.clean_text(raw)
        text = self._replace_unicode_fractions(text)

        # Remove parenthetical notes
        text_no_parens = re.sub(r'\([^)]*\)', '', text).strip()
        if not text_no_parens:
            return None

        # Build unit alternation for regex (longest first to avoid partial matches)
        units_sorted = sorted(self._HEBREW_UNITS, key=len, reverse=True)
        unit_pattern = '|'.join(re.escape(u) for u in units_sorted)

        # Pattern: optional_amount  optional_unit  ingredient_name
        pattern = (
            r'^([\d]+(?:[.,/]\d+)?(?:\s+[\d]+(?:[.,/]\d+)?)?)?'  # amount
            r'\s*'
            r'(' + unit_pattern + r')?'                            # unit
            r'\s*'
            r'(.+)$'                                                # name
        )

        m = re.match(pattern, text_no_parens.strip(), re.UNICODE)
        if not m:
            return {'name': text_no_parens, 'amount': None, 'units': None}

        amount_str, unit, name = m.group(1), m.group(2), m.group(3)

        # Parse amount
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            try:
                if '/' in amount_str:
                    parts = amount_str.split()
                    total = 0.0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            total += float(part)
                    amount = int(total) if total == int(total) else total
                else:
                    val = float(amount_str.replace(',', '.'))
                    amount = int(val) if val == int(val) else val
            except (ValueError, ZeroDivisionError):
                amount = amount_str

        # Strip leading unit-adjectives from name (e.g. "גדושות ממרח ..." → "ממרח ...")
        adj_pat = '|'.join(re.escape(a) for a in self._UNIT_ADJECTIVES)
        name = re.sub(r'^(?:' + adj_pat + r')\s+', '', name, flags=re.UNICODE)

        # Clean name
        name = re.sub(r'\s+', ' ', name).strip().rstrip(',;')
        if not name:
            return None

        return {
            'name': name,
            'amount': amount,
            'units': unit.strip() if unit else None,
        }

    # ------------------------------------------------------------------ #
    #  Public extract_* methods                                            #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Extract the recipe dish name."""
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        h1 = self.soup.find('h1', class_='post_title')
        if not h1:
            h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def extract_description(self) -> Optional[str]:
        """Extract the recipe description."""
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        description_parts, _, _ = self._parse_content_sections()
        if description_parts:
            return self.clean_text(' '.join(description_parts[:2]))

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Extract ingredients as a JSON string of {name, amount, units} dicts."""
        _, ingredient_lines, _ = self._parse_content_sections()

        if not ingredient_lines:
            return None

        ingredients = []
        for line in ingredient_lines:
            parsed = self._parse_ingredient(line)
            if parsed and parsed.get('name'):
                ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """Extract cooking instructions as a single string."""
        _, _, instruction_steps = self._parse_content_sections()

        if not instruction_steps:
            return None

        return ' '.join(instruction_steps)

    def extract_category(self) -> Optional[str]:
        """Extract category from article CSS classes or breadcrumb links."""
        article = self.soup.find('article')
        if article:
            classes = article.get('class', [])
            for cls in classes:
                # e.g. "category-main-course"
                if cls.startswith('category-'):
                    slug = cls[len('category-'):]
                    label = self._CATEGORY_MAP.get(slug)
                    if label:
                        return label

        # Fall back to the Hebrew category links
        single_cat = self.soup.find('div', class_='single_cat')
        if single_cat:
            cats = [a.get_text().strip() for a in single_cat.find_all('a') if a.get_text().strip()]
            if cats:
                return cats[-1]

        return None

    def _extract_time_from_text(self) -> dict:
        """
        Attempt to extract prep/cook/total times from the pf-content text.
        Returns a dict with keys 'prep_time', 'cook_time', 'total_time'.
        Values are human-readable strings or None.
        """
        pf_content = self._get_pf_content()
        if not pf_content:
            return {'prep_time': None, 'cook_time': None, 'total_time': None}

        text = pf_content.get_text(' ', strip=True)

        times = {'prep_time': None, 'cook_time': None, 'total_time': None}

        # Soaking / marinating → prep_time
        soak_m = re.search(r'(?:משרים|להשרות|להשריה)[^.]{0,80}?(\d+(?:-\d+)?)\s*(שעות|שעה|דקות|דקה)', text)
        if soak_m:
            val, unit = soak_m.group(1), soak_m.group(2)
            unit_en = 'hours' if 'שעה' in unit or 'שעות' in unit else 'minutes'
            times['prep_time'] = f"{val} {unit_en}"

        # Total cooking time – last time mention of hours
        cook_patterns = [
            r'(?:מבשלים|בישול|לבשל)[^.]{0,100}?(\d+(?:[.,]\d+)?)\s*(שעות|שעה)',
            r'(\d+(?:[.,]\d+)?)\s*שעות\s*(?:בישול)',
        ]
        for pat in cook_patterns:
            m = re.search(pat, text)
            if m:
                val = m.group(1).replace(',', '.')
                try:
                    fval = float(val)
                    times['cook_time'] = f"{fval} hours"
                except ValueError:
                    times['cook_time'] = f"{val} hours"
                break

        # Minutes cook time (if no hours found)
        if not times['cook_time']:
            m = re.search(r'(?:מבשלים|לבשל|טיגון|לטגן)[^.]{0,80}?(\d+)\s*דקות', text)
            if m:
                times['cook_time'] = f"{m.group(1)} minutes"

        # Total time – look for explicit "total X hours" or the cooling/chilling time
        total_patterns = [
            r'(?:סה\"כ|סך הכל|בסך הכל)[^.]{0,60}?(\d+(?:[.,]\d+)?)\s*(שעות|שעה|דקות|דקה)',
            r'קירור\s+(?:של\s+)?(\d+(?:[.,]\d+)?|שלוש|שתי|שתיים|ארבע|חמש)\s*(שעות|שעה|דקות|דקה)',
            r'לאחר\s+(\d+(?:[.,]\d+)?)\s*(שעות|שעה)',
        ]
        word_nums = {'שלוש': 3, 'שתי': 2, 'שתיים': 2, 'ארבע': 4, 'חמש': 5}
        for pat in total_patterns:
            m = re.search(pat, text)
            if m:
                raw_val = m.group(1)
                unit = m.group(2)
                unit_en = 'hours' if 'שעה' in unit or 'שעות' in unit else 'minutes'
                if raw_val in word_nums:
                    val = str(word_nums[raw_val])
                else:
                    val = raw_val.replace(',', '.')
                times['total_time'] = f"{val} {unit_en}"
                break

        return times

    def extract_prep_time(self) -> Optional[str]:
        return self._extract_time_from_text()['prep_time']

    def extract_cook_time(self) -> Optional[str]:
        return self._extract_time_from_text()['cook_time']

    def extract_total_time(self) -> Optional[str]:
        return self._extract_time_from_text()['total_time']

    def extract_notes(self) -> Optional[str]:
        """Extract serving suggestions / tips from pf-content."""
        pf_content = self._get_pf_content()
        if not pf_content:
            return None

        paragraphs = [p.get_text().strip() for p in pf_content.find_all('p') if p.get_text().strip()]

        # Explicit serving/note patterns (must not start with a cooking action verb)
        serving_patterns = [
            r'(?:רצוי|מומלץ|ניתן|כדאי).{0,20}(?:להגיש|לאכול|לשדרג)',
            r'להגיש\s+(?:עם|לצד|יחד)',
            r'(?:טיפ|הערה)\s*:',
            r'ניתן\s+לשמור',
            r'ניתן\s+להכין\s+מראש',
            r'אפשר\s+להחליף',
            r'ניתן\s+להחליף',
        ]
        # Cooking action verb prefixes to exclude (these are instruction steps, not notes)
        action_prefixes = re.compile(
            r'^(?:מכניסים|מחממים|מוסיפים|מטגנים|מבשלים|מערבבים|מניחים|חותכים|קולפים|מסירים)',
            re.UNICODE,
        )

        for para in paragraphs:
            if action_prefixes.match(para):
                continue
            for pat in serving_patterns:
                if re.search(pat, para, re.UNICODE):
                    return self.clean_text(para)

        return None

    def extract_tags(self) -> Optional[str]:
        """Extract tags from category links in the post header."""
        single_cat = self.soup.find('div', class_='single_cat')
        if not single_cat:
            return None

        tags = [a.get_text().strip() for a in single_cat.find_all('a') if a.get_text().strip()]
        return ', '.join(tags) if tags else None

    def extract_image_urls(self) -> Optional[str]:
        """Collect all recipe-related image URLs."""
        urls: list = []
        seen: set = set()

        def add_url(url: str) -> None:
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        # 1. og:image
        og_img = self.soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            add_url(og_img['content'])

        # 2. Featured post image
        article = self.soup.find('article')
        if article:
            post_featured = article.find('div', class_='post_featured')
            if post_featured:
                for img in post_featured.find_all('img'):
                    add_url(img.get('src', ''))

        # 3. Images inside pf-content (step photos etc.)
        pf_content = self._get_pf_content()
        if pf_content:
            for img in pf_content.find_all('img'):
                src = img.get('src', '')
                # Skip tiny icons / buttons
                if src and not any(skip in src for skip in ['button', 'icon', 'logo', 'printfriendly']):
                    add_url(src)

        return ','.join(urls) if urls else None

    # ------------------------------------------------------------------ #
    #  extract_all                                                         #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """Extract all recipe data and return as a dict."""
        try:
            dish_name = self.extract_dish_name()
            description = self.extract_description()
            ingredients = self.extract_ingredients()
            instructions = self.extract_steps()
            category = self.extract_category()
            notes = self.extract_notes()
            tags = self.extract_tags()
            image_urls = self.extract_image_urls()
            times = self._extract_time_from_text()

            return {
                'dish_name': dish_name,
                'description': description,
                'ingredients': ingredients,
                'instructions': instructions,
                'category': category,
                'prep_time': times['prep_time'],
                'cook_time': times['cook_time'],
                'total_time': times['total_time'],
                'notes': notes,
                'tags': tags,
                'image_urls': image_urls,
            }
        except Exception as e:
            logger.error("Error extracting recipe data: %s", e, exc_info=True)
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
                'image_urls': None,
            }


def main():
    """Entry point: process all HTML files in preprocessed/dafnisfood_com."""
    import os

    preprocessed_dir = os.path.join('preprocessed', 'dafnisfood_com')

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(DafnisFoodExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python dafnisfood_com.py")


if __name__ == '__main__':
    main()
