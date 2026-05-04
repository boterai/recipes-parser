"""
Экстрактор данных рецептов для сайта bosch-home.co.id
"""

import logging
import html as _html
import sys
import json
import copy as _copy
import re
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class BoschHomeCoIdExtractor(BaseRecipeExtractor):
    """Экстрактор для bosch-home.co.id"""

    # Units that may appear immediately after amount (no space)
    _COMPACT_UNITS = re.compile(
        r'^(g|ml|l|kg|pcs?|pc)(?=\s|$)',
        re.IGNORECASE,
    )

    # Units that are separated from the amount by a space
    _WORD_UNITS = re.compile(
        r'^(tablespoons?|teaspoons?|tbsps?|tsps?|cups?|stalks?|slices?|no\.s|pcs?|g|ml|l|kg|pieces?|heads?)(?=\s|$)',
        re.IGNORECASE,
    )

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    def _get_guten_appetit_section(self):
        """Return the 'Guten Appetit' teaser div or None."""
        for h2 in self.soup.find_all('h2'):
            if 'guten appetit' in h2.get_text(strip=True).lower():
                return h2.parent
        return None

    def _get_js_content(self):
        """Return the main recipe content div (class='js-content')."""
        # There are two js-content divs in the page; we want the one that
        # contains the Ingredients section.
        for div in self.soup.find_all('div', class_='js-content'):
            if div.find('h2', string=re.compile(r'Ingredients', re.I)) or \
               div.find('h4', string=re.compile(r'Ingredients', re.I)):
                return div
            # also check for div.g-layout-full containing an Ingredients heading
            for layout in div.find_all('div', class_='g-layout-full', recursive=False):
                text = layout.get_text(strip=True)
                if text.startswith('Ingredients'):
                    return div
        return None

    def _normalize_amount(self, amount_str: str) -> Optional[str]:
        """
        Return the amount string as-is (preserving Unicode fractions like ½).
        Only strips surrounding whitespace.
        """
        if not amount_str:
            return None
        return amount_str.strip() or None

    @staticmethod
    def _clean_ingredient_name(name: str) -> str:
        """
        Clean up an ingredient name by removing preparation notes.

        Rules:
          - Strip trailing " - preparation text" (e.g. " - Peeled and Deseeded")
          - Remove "(optional)" marker (case insensitive)
        """
        if not name:
            return name
        # Strip " - preparation note" suffix
        name = re.sub(r'\s+-\s+.+$', '', name).strip()
        # Strip "(optional)" specifically (not other parenthetical descriptors)
        name = re.sub(r'\s*\(\s*optional\s*\)', '', name, flags=re.IGNORECASE).strip()
        return name

    def _parse_bosch_ingredient(self, text: str) -> Optional[dict]:
        """
        Parse a Bosch-style ingredient string into {name, amount, unit}.

        Supported formats:
            "2 Tsps Cocoa Powder"
            "½ Cup Almond Milk"
            "30g Pumpkin Seeds (Deshelled)"
            "2pcs Large Mangoes - Peeled and Deseeded"
            "1 Banana (Sliced)"
            "2-3 Stalks Parsley"
            "400ml Whipping Cream"
        """
        if not text:
            return None
        text = self.clean_text(text)
        if not text:
            return None

        # Pattern: optional leading amount (integer/fraction/range), then unit+name
        # Step 1: extract leading amount token(s)
        amount_pattern = re.compile(
            r'^([¼½¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘\d]+(?:\.\d+)?(?:[-–]\d+)?)',
        )
        m = amount_pattern.match(text)
        if not m:
            return {"name": text, "amount": None, "unit": None}

        amount_raw = m.group(1)
        remainder = text[m.end():]  # everything after the amount token

        # Step 2: check for compact unit (immediately after amount, no space)
        compact_match = self._COMPACT_UNITS.match(remainder)
        if compact_match:
            unit = compact_match.group(1)
            name = self._clean_ingredient_name(remainder[compact_match.end():].strip())
            return {
                "name": name if name else None,
                "unit": unit,
                "amount": self._normalize_amount(amount_raw),
            }

        # Step 3: skip whitespace, then check for word unit
        rest = remainder.lstrip()
        word_match = self._WORD_UNITS.match(rest)
        if word_match:
            unit = word_match.group(1)
            name = self._clean_ingredient_name(rest[word_match.end():].strip())
            return {
                "name": name if name else None,
                "unit": unit,
                "amount": self._normalize_amount(amount_raw),
            }

        # Step 4: no unit found; everything after the amount is the name
        name = self._clean_ingredient_name(rest.strip())
        return {
            "name": name if name else None,
            "unit": None,
            "amount": self._normalize_amount(amount_raw),
        }

    # ------------------------------------------------------------------ #
    #  Public extraction methods
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Extract the recipe title from the h1 in the page-title div."""
        pagetitle = self.soup.find('div', class_='m-pagetitle')
        if pagetitle:
            h1 = pagetitle.find('h1')
            if h1:
                return self.clean_text(h1.get_text())

        # Fallback: any h1 on the page
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        # Fallback: meta title
        meta_title = self.soup.find('meta', attrs={'name': 'title'})
        if meta_title and meta_title.get('content'):
            title = meta_title['content']
            title = re.sub(r'\s+Recipe\s*$', '', title, flags=re.IGNORECASE).strip()
            return self.clean_text(title) or None

        return None

    def extract_description(self) -> Optional[str]:
        """Extract description from meta description tag."""
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content']) or None

        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content']) or None

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Extract ingredients from the Ingredients table/list inside js-content.

        The site uses either <li> elements (single-column list in a <table>)
        or multi-column <td> elements (no wrapping <ul>).
        Prefer <li> when available; fall back to <td>.
        """
        js_content = self._get_js_content()
        if not js_content:
            logger.warning("js-content div not found in %s", self.html_path)
            return None

        # Find the g-layout-full that starts with 'Ingredients'
        ing_layout = None
        for layout in js_content.find_all('div', class_='g-layout-full', recursive=False):
            text = layout.get_text(strip=True)
            if text.startswith('Ingredients'):
                ing_layout = layout
                break

        if not ing_layout:
            # try h2/h4 with text 'Ingredients'
            for heading in js_content.find_all(['h2', 'h4']):
                if heading.get_text(strip=True).lower() == 'ingredients':
                    # Take the enclosing g-layout-full ancestor
                    parent = heading.parent
                    while parent and parent != js_content:
                        if 'g-layout-full' in (parent.get('class') or []):
                            ing_layout = parent
                            break
                        parent = parent.parent
                    break

        if not ing_layout:
            logger.warning("Ingredients section not found in %s", self.html_path)
            return None

        # Prefer <li> items
        li_items = ing_layout.find_all('li')
        raw_items: list[str] = []
        if li_items:
            for li in li_items:
                text = self.clean_text(li.get_text(separator=' ', strip=True))
                if text:
                    raw_items.append(text)
        else:
            # Fall back to <td> elements
            for td in ing_layout.find_all('td'):
                text = self.clean_text(td.get_text(separator=' ', strip=True))
                if text:
                    raw_items.append(text)

        if not raw_items:
            return None

        ingredients = []
        for raw in raw_items:
            parsed = self._parse_bosch_ingredient(raw)
            if parsed and parsed.get('name'):
                ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def _get_methods_section(self):
        """
        Return a tuple (kind, data) describing where the recipe steps live.

        kind == 'divs'    → data is a list of m-contenttextmedia divs
        kind == 'content' → data is a div.content (or div with content class)
                            that contains alternating <strong>Step N.</strong>
                            and text paragraphs (kale-style)
        kind == None      → steps not found
        """
        js_content = self._get_js_content()
        if not js_content:
            return None, None

        children = [c for c in js_content.children if hasattr(c, 'name') and c.name]

        in_methods = False
        step_divs: list = []
        methods_layout = None

        for child in children:
            cls = child.get('class') or []
            child_text = child.get_text(strip=True)

            # Detect Methods header section
            if not in_methods:
                if (
                    'methods' in child_text.lower()[:20]
                    and (
                        'g-layout-full' in cls
                        or 'm-contenttextmediabig' in cls
                        or 'g-col' in cls
                    )
                ):
                    in_methods = True
                    methods_layout = child
                    continue

            if in_methods:
                # Stop at 'Recommended Products' or 'Related Recipes'
                if 'g-layout-full' in cls and (
                    'recommended' in child_text.lower()
                    or 'related' in child_text.lower()
                ):
                    break

                if 'm-contenttextmedia' in cls:
                    step_divs.append(child)

        if step_divs:
            return 'divs', step_divs

        # Fallback: kale-style – steps embedded inside the Methods g-layout-full
        if methods_layout is not None:
            content_div = methods_layout.find('div', class_='content')
            if content_div:
                return 'content', content_div

        return None, None

    def extract_steps(self) -> Optional[str]:
        """
        Extract instructions text.

        Handles three structural variants found on bosch-home.co.id:
        1. Separate m-contenttextmedia divs per step (chocolate-smoothie, mango,
           healthy-smoothie-fruit-bowl).
        2. Single div.content block with <strong>Step N.</strong> markers
           interleaved with text paragraphs (kale, green-juice pages).
        3. Step text in h3.a-heading inside div.heading (mango step 9, where
           content-inner is empty).

        Strips step-number prefixes and tip text (<i> tags).
        Returns all steps joined by a space.
        """
        kind, data = self._get_methods_section()
        steps: list[str] = []

        if kind == 'divs':
            for div in data:
                # --- variant 3: text in h3 inside div.heading (empty content-inner) ---
                ci = div.find('div', class_='content-inner')
                if ci and not ci.get_text(strip=True):
                    # content-inner is empty; check for h3 in div.heading
                    heading_div = div.find('div', class_='heading')
                    if heading_div:
                        h3 = heading_div.find('h3')
                        if h3:
                            text = self.clean_text(h3.get_text(strip=True))
                            if text:
                                steps.append(text)
                    continue

                if not ci:
                    continue

                text_div = ci.find('div', class_='text')
                source = text_div if text_div else ci

                # Gather text from each <p>, skipping pure-tip paragraphs
                for p in source.find_all('p'):
                    children_tags = [
                        t for t in p.children if hasattr(t, 'name') and t.name
                    ]
                    # Pure-tip paragraph: single <i> child
                    if len(children_tags) == 1 and children_tags[0].name == 'i':
                        continue

                    # Remove <i> tip sub-elements in-place on a copy
                    p_copy = _copy.copy(p)
                    for i_tag in p_copy.find_all('i'):
                        i_tag.decompose()

                    text = self.clean_text(p_copy.get_text(separator=' ', strip=True))
                    # Strip "N. " or "Step N." prefix
                    text = re.sub(
                        r'^(?:Step\s+)?\d+\.\s*', '', text, flags=re.IGNORECASE
                    ).strip()
                    if text:
                        steps.append(text)

        elif kind == 'content':
            # kale-style: paragraphs inside div.content
            # structure: <p><strong>Step N.</strong></p> <p/> <p>instruction</p> …
            paras = data.find_all('p')
            skip_next_empty = False
            for p in paras:
                # Is this a step-number paragraph?
                strong = p.find('strong')
                if strong and re.match(
                    r'Step\s+\d+', strong.get_text(strip=True), re.IGNORECASE
                ):
                    skip_next_empty = True
                    continue

                text = self.clean_text(p.get_text(strip=True))
                if not text:
                    continue  # skip blank divider paragraphs

                # Skip the blank spacer after a step header
                if skip_next_empty:
                    skip_next_empty = False
                    # This is the actual step text
                    steps.append(text)
                else:
                    steps.append(text)

        return ' '.join(steps) if steps else None

    def extract_notes(self) -> Optional[str]:
        """
        Collect all 'Tip:' italic text from the recipe steps section.
        """
        kind, data = self._get_methods_section()
        if kind != 'divs' or not data:
            return None

        tips: list[str] = []
        seen: set[str] = set()

        for div in data:
            ci = div.find('div', class_='content-inner')
            if not ci:
                continue
            for i_tag in ci.find_all('i'):
                tip_text = self.clean_text(i_tag.get_text(strip=True))
                if tip_text and tip_text not in seen:
                    seen.add(tip_text)
                    tips.append(tip_text)

        return ' '.join(tips) if tips else None

    def extract_category(self) -> Optional[str]:
        """
        Extract category from the header breadcrumb navigation.
        Returns the last breadcrumb link (excluding generic entries like
        'Experience Bosch', 'Living with Bosch', 'Cookbook').
        """
        skip = {
            'home', 'experience bosch', 'living with bosch', 'cookbook',
            'tentang bosch',  # Indonesian
        }

        breadcrumb_div = self.soup.find('div', class_='header-breadcrumb')
        if breadcrumb_div:
            links = breadcrumb_div.find_all('a', class_='a-link')
            categories = []
            for a in links:
                # Breadcrumb text can contain double-encoded entities (e.g. &amp;amp;)
                raw = a.get_text(strip=True)
                text = self.clean_text(_html.unescape(raw))
                if text and text.lower() not in skip:
                    categories.append(text)
            if categories:
                return categories[-1]  # last meaningful category

        # Fallback: JSON-LD BreadcrumbList
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'BreadcrumbList':
                    items = data.get('itemListElement', [])
                    # Remove generic navigation items from the tail
                    for item in reversed(items):
                        name = item.get('name', '')
                        if name.lower() not in skip | {'home'}:
                            return self.clean_text(name) or None
            except (json.JSONDecodeError, AttributeError):
                continue

        return None

    def _parse_time_value(self, text: str) -> Optional[str]:
        """
        Extract the time value string from a Guten Appetit paragraph.

        Handles:
            "Preparation Time: 25 mins"             → "25 mins"
            "Cooking Time: 0 mins"                  → "0 mins"
            "Preparation Time: 300 mins (includes…)"→ "300 mins"
        """
        match = re.search(r':\s*(.+)', text)
        if not match:
            return None
        value = match.group(1).strip()
        # Strip parenthetical notes
        value = re.sub(r'\s*\(.*?\)', '', value).strip()
        return value if value else None

    def extract_prep_time(self) -> Optional[str]:
        """Extract preparation time from the Guten Appetit section."""
        section = self._get_guten_appetit_section()
        if not section:
            return None
        for p in section.find_all('p'):
            text = p.get_text(strip=True)
            if 'preparation time' in text.lower():
                return self._parse_time_value(text)
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Extract cooking time from the Guten Appetit section."""
        section = self._get_guten_appetit_section()
        if not section:
            return None
        for p in section.find_all('p'):
            text = p.get_text(strip=True)
            if 'cooking time' in text.lower():
                return self._parse_time_value(text)
        return None

    def extract_total_time(self) -> Optional[str]:
        """Extract total time from the Guten Appetit section (if present)."""
        section = self._get_guten_appetit_section()
        if not section:
            return None
        for p in section.find_all('p'):
            text = p.get_text(strip=True)
            if 'total time' in text.lower():
                return self._parse_time_value(text)
        return None

    def extract_tags(self) -> Optional[str]:
        """
        Tags are not explicitly available in the bosch-home.co.id HTML.
        Returns None.
        """
        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Extract recipe image URLs from <img> tags.

        Prefers images hosted on media3.bosch-home.com / bosch-home.com,
        de-duplicates, and returns all URLs joined by commas.
        """
        urls: list[str] = []
        seen: set[str] = set()

        for img in self.soup.find_all('img'):
            src = img.get('src') or img.get('data-src') or ''
            if not src:
                continue
            # Normalise protocol-relative URLs
            if src.startswith('//'):
                src = 'https:' + src

            # Only recipe-related images from Bosch media host
            if 'bosch-home.com' not in src.lower() and 'bosch-home' not in src.lower():
                continue
            # Exclude tiny icons / logos (heuristic: path contains no image filename)
            if not re.search(r'\.(jpg|jpeg|png|webp|gif)', src, re.IGNORECASE):
                continue

            if src not in seen:
                seen.add(src)
                urls.append(src)

        if not urls:
            # Fallback: og:image
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                return og_image['content']

        return ','.join(urls) if urls else None

    # ------------------------------------------------------------------ #
    #  Main entry point
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """
        Extract all recipe data and return as a dict.

        All fields are always present; missing values are None.
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception as e:
            logger.error("Error extracting dish_name from %s: %s", self.html_path, e)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as e:
            logger.error("Error extracting description from %s: %s", self.html_path, e)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as e:
            logger.error("Error extracting ingredients from %s: %s", self.html_path, e)
            ingredients = None

        try:
            instructions = self.extract_steps()
        except Exception as e:
            logger.error("Error extracting instructions from %s: %s", self.html_path, e)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as e:
            logger.error("Error extracting category from %s: %s", self.html_path, e)
            category = None

        try:
            notes = self.extract_notes()
        except Exception as e:
            logger.error("Error extracting notes from %s: %s", self.html_path, e)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as e:
            logger.error("Error extracting tags from %s: %s", self.html_path, e)
            tags = None

        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": self.extract_image_urls(),
        }


def main():
    """Process all HTML files in preprocessed/bosch-home_co_id/."""
    import os
    recipes_dir = os.path.join("preprocessed", "bosch-home_co_id")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(BoschHomeCoIdExtractor, str(recipes_dir))
        return
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python bosch-home_co_id.py [путь_к_директории]")


if __name__ == "__main__":
    main()
