"""
Экстрактор данных рецептов для сайта bakin-mix.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


# Unicode fraction map
_FRACTIONS = {
    '½': '1/2', '¼': '1/4', '¾': '3/4',
    '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
}

# Known ASCII / short units (always identifiable regardless of encoding)
_ASCII_UNITS = {'ml', 'dl', 'g', 'kg', 'dag', 'l', 'kom', 'komad', 'pakiranje', 'pakiranja', 'paket'}

# Word-amounts that appear at the start of an ingredient instead of a number
_WORD_AMOUNTS = {'malo', 'prstohvat', 'nešto', 'po'}


def _token_is_unit(token: str) -> bool:
    """
    Determine whether a token is likely a unit of measurement.
    Handles both correct Croatian and the double-encoded forms stored in these HTML files.
    """
    lower = token.lower()

    # Known ASCII units
    if lower in _ASCII_UNITS:
        return True

    # Croatian tablespoon/teaspoon words: žlica/žlice/žličica/žličice and their garbled variants.
    # The garbled forms retain ASCII letters around the non-ASCII mojibake characters.
    # Strip all non-ASCII chars and check if the result starts with 'lica', 'lice', or 'zlica', 'zlice'
    ascii_only = re.sub(r'[^\x00-\x7F]', '', lower)
    # Handles: "zÌŒlice"→"zlice", "Å¾liÄice"→"liice" (lic subsequence), "zÌŒlicÌŒica"→"zlicica"
    # "žličice" garbles to have "l","i","i","c","e" in ASCII portion.
    # Use a fuzzy check: the token's ASCII letters should contain 'l','i','c' in sequence.
    if re.search(r'l[ie]?i?c', ascii_only):
        return True

    # Fully-correct Croatian forms (in case some pages are properly encoded)
    if lower in {'žlica', 'žlice', 'žličica', 'žličice', 'žlicom', 'žličicom', 'šalica', 'šalice'}:
        return True

    return False


class BakinMixComExtractor(BaseRecipeExtractor):
    """Экстрактор для bakin-mix.com"""

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _is_recipe_page(self) -> bool:
        """Returns True when the HTML is a dedicated recipe post."""
        body = self.soup.find('body')
        if body:
            classes = body.get('class', [])
            return 'single-recipe' in classes
        return False

    def _is_blog_post(self) -> bool:
        """Returns True when the HTML is a generic blog / adventure post."""
        body = self.soup.find('body')
        if body:
            classes = body.get('class', [])
            return 'single-post' in classes
        return False

    def _parse_ingredient(self, raw: str) -> Optional[dict]:
        """
        Parse a Croatian ingredient string into {name, amount, unit}.

        Examples:
            "2 jaja"                    -> {name:"jaja", amount:"2", unit:None}
            "360 ml mlijeka"            -> {name:"mlijeko", amount:"360", unit:"ml"}
            "2 žlice šećera"            -> {name:"šecer", amount:"2", unit:"žlice"}
            "prstohvat soli"            -> {name:"sol", amount:"prstohvat", unit:None}
            "malo maslaca"              -> {name:"maslac", amount:"malo", unit:None}
            "1 pakiranje mješavine"     -> {name:"mješavine", amount:"1", unit:"pakiranje"}
            "ribana korica 1 naranče"   -> {name:"ribana korica naranče", amount:"1", unit:None}
        """
        if not raw:
            return None

        text = raw.strip()

        # Replace unicode fraction characters ONLY when they appear standalone
        # (not as part of garbled non-ASCII encoding such as Å¾lice where ¾ is part of 'ž')
        for frac, rep in _FRACTIONS.items():
            # Only replace when the fraction is adjacent to a digit or whitespace/start,
            # i.e. not surrounded by ASCII letters (which would indicate it's inside a word)
            text = re.sub(
                r'(?<![A-Za-z])' + re.escape(frac) + r'(?![A-Za-z])',
                rep,
                text,
            )

        # Strip text for parsing (without parenthetical notes)
        text_parse = re.sub(r'\s*\([^)]*\)', '', text).strip() or text

        tokens = text_parse.split()
        if not tokens:
            return {'name': self.clean_text(text), 'amount': None, 'unit': None}

        amount: Optional[str] = None
        unit: Optional[str] = None
        name_start = 0

        first = tokens[0]

        # Case A: leading numeric amount  (e.g. "2", "1/2", "360", "2.5")
        if re.match(r'^[\d.,/]+$', first):
            amount = first
            name_start = 1
            # Next token might be a unit
            if name_start < len(tokens) and _token_is_unit(tokens[name_start]):
                unit = tokens[name_start]
                name_start += 1

        # Case B: leading word amount  (e.g. "malo", "prstohvat")
        elif first.lower() in _WORD_AMOUNTS:
            amount = first
            name_start = 1

        # Case C: text starts with name words, but a number appears somewhere later
        # e.g. "ribana korica 1 naranče" -> amount=1 extracted from middle
        else:
            for idx, tok in enumerate(tokens):
                if re.match(r'^[\d.,/]+$', tok):
                    amount = tok
                    # Rebuild name without that number token
                    name_tokens = tokens[:idx] + tokens[idx + 1:]
                    name_val = self.clean_text(' '.join(name_tokens))
                    return {'name': name_val or self.clean_text(text), 'amount': amount, 'unit': None}
            # No number found at all
            name_start = 0

        # Build name from remaining original tokens (preserving parenthetical notes)
        # re-split from original text to keep parenthetical content
        orig_tokens = text.split()
        name_tokens = orig_tokens[name_start:]
        name = self.clean_text(' '.join(name_tokens)) if name_tokens else self.clean_text(text)

        return {
            'name': name,
            'amount': amount,
            'unit': unit,
        }

    # ------------------------------------------------------------------
    # dish_name
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Extract recipe title."""
        # og:title is most reliable – strip " - Bakini proizvodi - Bakin' Mix" suffix
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*[-–|]\s*Bakini proizvodi.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r"\s*[-–|]\s*Bakin'?\s*Mix.*$", '', title, flags=re.IGNORECASE)
            return self.clean_text(title) or None

        # Fallback: second h1 (first is always "Peci s bakom" site-wide header)
        h1_tags = self.soup.find_all('h1')
        for h1 in h1_tags:
            text = self.clean_text(h1.get_text())
            if text and text.lower() not in ('peci s bakom',):
                return text
        return None

    # ------------------------------------------------------------------
    # description
    # ------------------------------------------------------------------

    def extract_description(self) -> Optional[str]:
        """Extract recipe description."""
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content']) or None

        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content']) or None

        return None

    # ------------------------------------------------------------------
    # ingredients
    # ------------------------------------------------------------------

    def extract_ingredients(self) -> Optional[str]:
        """Extract ingredients list as JSON string."""
        ingredients = []

        if self._is_recipe_page():
            ingredients = self._extract_recipe_page_ingredients()
        elif self._is_blog_post():
            ingredients = self._extract_blog_post_ingredients()

        if not ingredients:
            # Universal fallback: look for any ul after Sastojci heading
            ingredients = self._extract_sastojci_fallback()

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def _extract_recipe_page_ingredients(self) -> list:
        """Ingredients from dedicated recipe pages (div.o-bake-article-ingred)."""
        result = []
        container = self.soup.find('div', class_='o-bake-article-ingred')
        if not container:
            return result

        # Items are in the first item-block (second block is a product carousel)
        item_block = container.find('div', class_='o-bake-article-ingred__item')
        if not item_block:
            return result

        ul = item_block.find('ul', class_='o-list')
        if not ul:
            return result

        for li in ul.find_all('li', class_='o-list__item'):
            raw = self.clean_text(li.get_text(separator=' ', strip=True))
            if raw:
                parsed = self._parse_ingredient(raw)
                if parsed:
                    result.append(parsed)
        return result

    def _extract_blog_post_ingredients(self) -> list:
        """Ingredients from blog-post pages (inside div.c-preformat)."""
        result = []
        content = self.soup.find('div', class_='c-preformat')
        if not content:
            return result

        # Look for a <p><strong>Sastojci...</strong></p> or similar heading,
        # then grab the first following <ul>
        for el in content.find_all(['p', 'h3', 'h4']):
            text = el.get_text(strip=True).lower()
            if 'sastojci' in text:
                ul = el.find_next_sibling('ul')
                if ul:
                    for li in ul.find_all('li'):
                        raw = self.clean_text(li.get_text(separator=' ', strip=True))
                        if raw:
                            parsed = self._parse_ingredient(raw)
                            if parsed:
                                result.append(parsed)
                break
        return result

    def _extract_sastojci_fallback(self) -> list:
        """Generic fallback: find 'Sastojci' heading and grab following ul."""
        result = []
        for el in self.soup.find_all(string=lambda t: t and 'Sastojci' in t):
            parent = el.parent
            # Travel up to find a sibling or ancestor with a list
            ul = None
            # Try next sibling
            for sib in parent.find_next_siblings():
                if sib.name == 'ul':
                    ul = sib
                    break
                if sib.name in ('h2', 'h3', 'h4', 'div'):
                    break
            if ul:
                for li in ul.find_all('li'):
                    raw = self.clean_text(li.get_text(separator=' ', strip=True))
                    if raw:
                        parsed = self._parse_ingredient(raw)
                        if parsed:
                            result.append(parsed)
                if result:
                    break
        return result

    # ------------------------------------------------------------------
    # instructions
    # ------------------------------------------------------------------

    def extract_steps(self) -> Optional[str]:
        """Extract preparation steps."""
        steps = []

        if self._is_recipe_page():
            steps = self._extract_recipe_page_steps()
        elif self._is_blog_post():
            steps = self._extract_blog_post_steps()

        if not steps:
            steps = self._extract_priprema_fallback()

        return ' '.join(steps) if steps else None

    def _extract_recipe_page_steps(self) -> list:
        """Steps from div.my-5 > ol on recipe pages."""
        steps = []
        prep_div = self.soup.find('div', class_='my-5')
        if not prep_div:
            return steps
        ol = prep_div.find('ol')
        if ol:
            for idx, li in enumerate(ol.find_all('li'), 1):
                text = self.clean_text(li.get_text(separator=' ', strip=True))
                if text:
                    steps.append(f'{idx}. {text}')
        return steps

    def _extract_blog_post_steps(self) -> list:
        """Steps from the first <ol> in div.c-preformat on blog post pages."""
        steps = []
        content = self.soup.find('div', class_='c-preformat')
        if not content:
            return steps
        ol = content.find('ol')
        if ol:
            for idx, li in enumerate(ol.find_all('li'), 1):
                text = self.clean_text(li.get_text(separator=' ', strip=True))
                if text:
                    steps.append(f'{idx}. {text}')
        return steps

    def _extract_priprema_fallback(self) -> list:
        """Generic fallback: find 'Priprema' heading and grab following ol/ul."""
        steps = []
        for el in self.soup.find_all(string=lambda t: t and 'Priprema' in t):
            parent = el.parent
            ol = None
            for sib in parent.find_next_siblings():
                if sib.name in ('ol', 'ul'):
                    ol = sib
                    break
                if sib.name in ('h2', 'h3', 'h4'):
                    break
            if ol:
                for idx, li in enumerate(ol.find_all('li'), 1):
                    text = self.clean_text(li.get_text(separator=' ', strip=True))
                    if text:
                        steps.append(f'{idx}. {text}')
                if steps:
                    break
        return steps

    # ------------------------------------------------------------------
    # category
    # ------------------------------------------------------------------

    def extract_category(self) -> Optional[str]:
        """Extract recipe category."""
        # Recipe pages: inside div.my-4.py-2, label "Kategorija:"
        kat_label = self.soup.find(
            string=lambda t: t and 'Kategorija' in t
        )
        if kat_label:
            kat_container = kat_label.parent.parent  # div.my-4.py-2
            if kat_container:
                link = kat_container.find('a')
                if link:
                    return self.clean_text(link.get_text()) or None

        # Blog posts: article:section meta tag
        section_meta = self.soup.find('meta', property='article:section')
        if section_meta and section_meta.get('content'):
            return self.clean_text(section_meta['content']) or None

        return None

    # ------------------------------------------------------------------
    # times
    # ------------------------------------------------------------------

    def _extract_time_from_table(self, label_text: str) -> Optional[str]:
        """
        Find time from the recipe metadata table (div.col-md-4).
        label_text: Croatian label substring, e.g. 'Vrijeme pripreme'
        """
        table = self.soup.find('table')
        if not table:
            return None
        for row in table.find_all('tr'):
            label_el = row.find(string=lambda t: t and label_text in t)
            if label_el:
                spans = row.find_all('span')
                for span in spans:
                    text = self.clean_text(span.get_text())
                    if re.search(r'\d', text):
                        return text
        return None

    def extract_prep_time(self) -> Optional[str]:
        return self._extract_time_from_table('Vrijeme pripreme')

    def extract_cook_time(self) -> Optional[str]:
        return self._extract_time_from_table('Vrijeme kuhanja')

    def extract_total_time(self) -> Optional[str]:
        return self._extract_time_from_table('Ukupno')

    # ------------------------------------------------------------------
    # notes
    # ------------------------------------------------------------------

    def extract_notes(self) -> Optional[str]:
        """Extract notes / tips."""
        # Recipe pages: look for a div or p with Napomena / Savjet heading
        for label in ('Napomena', 'Savjet', 'napomena', 'savjet'):
            el = self.soup.find(string=lambda t, lbl=label: t and lbl in t)
            if el:
                parent = el.parent
                # Get sibling or following text
                note_text = ''
                for sib in parent.find_next_siblings():
                    if sib.name in ('p', 'div', 'span'):
                        note_text = self.clean_text(sib.get_text())
                        if note_text:
                            break
                if note_text:
                    return note_text
        return None

    # ------------------------------------------------------------------
    # tags
    # ------------------------------------------------------------------

    def extract_tags(self) -> Optional[str]:
        """Extract tags."""
        tags = []

        # Blog posts and recipe posts: article:tag meta properties
        for meta in self.soup.find_all('meta', property='article:tag'):
            content = meta.get('content', '').strip()
            if content:
                tags.append(content)

        if tags:
            return ', '.join(tags)

        return None

    # ------------------------------------------------------------------
    # images
    # ------------------------------------------------------------------

    def extract_image_urls(self) -> Optional[str]:
        """Extract image URLs."""
        urls = []

        # Recipe pages: slider thumbnails via data-src
        slider = self.soup.find('div', class_='o-thumb-slider')
        if slider:
            for thumb in slider.find_all('div', class_='js-thumb-image'):
                src = thumb.get('data-src')
                if src and src not in urls:
                    urls.append(src)

        # og:image (main image for all page types)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            src = og_image['content']
            if src not in urls:
                urls.append(src)

        # Blog post content images
        content = self.soup.find('div', class_='c-preformat')
        if content:
            for img in content.find_all('img'):
                src = img.get('src') or img.get('data-src')
                if src and src not in urls:
                    urls.append(src)

        if not urls:
            return None
        return ','.join(urls)

    # ------------------------------------------------------------------
    # extract_all
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """
        Extract all recipe data.

        Returns:
            dict with recipe data fields
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()

        return {
            'dish_name': dish_name,
            'description': description,
            'ingredients': ingredients,
            'instructions': instructions,
            'category': category,
            'prep_time': self.extract_prep_time(),
            'cook_time': self.extract_cook_time(),
            'total_time': self.extract_total_time(),
            'notes': notes,
            'image_urls': self.extract_image_urls(),
            'tags': tags,
        }


def main():
    # Process the preprocessed/bakin-mix_com directory relative to the repo root
    repo_root = Path(__file__).parent.parent
    recipes_dir = repo_root / 'preprocessed' / 'bakin-mix_com'
    if recipes_dir.exists() and recipes_dir.is_dir():
        process_directory(BakinMixComExtractor, str(recipes_dir))
        return

    print(f'Directory not found: {recipes_dir}')
    print('Usage: python extractor/bakin-mix_com.py')


if __name__ == '__main__':
    main()
