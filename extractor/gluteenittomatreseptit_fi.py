"""
Экстрактор данных рецептов для сайта gluteenittomatreseptit.fi
"""

import sys
import re
import json
import logging
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Finnish units recognized during ingredient parsing
_FINNISH_UNITS = r'(?:tl|rkl|dl|cl|ml|l|kg|g|kpl|prk|rs|pss?|annosta|palaa?)'

# Finnish Unicode fractions → fraction string (for regex matching as "N/M")
_FRACTION_MAP = {
    '½': '1/2',
    '¼': '1/4',
    '¾': '3/4',
    '⅓': '1/3',
    '⅔': '2/3',
    '⅛': '1/8',
}

# Base URL used to make relative image paths absolute
_BASE_URL = 'https://gluteenittomatreseptit.fi'


class GluteenittomatreseptitFiExtractor(BaseRecipeExtractor):
    """Экстрактор для gluteenittomatreseptit.fi"""

    # ------------------------------------------------------------------
    # Helper: iterate entry-content children, stop before sharing divs
    # ------------------------------------------------------------------
    def _entry_content_children(self):
        """Yield direct children of div.entry-content, excluding sharing/related divs."""
        entry = self.soup.find('div', class_='entry-content')
        if not entry:
            return
        stop_classes = {'sharedaddy', 'jp-relatedposts'}
        for child in entry.children:
            if not hasattr(child, 'name') or not child.name:
                continue
            cls = set(child.get('class') or [])
            if cls & stop_classes:
                break
            yield child

    # ------------------------------------------------------------------
    # Ingredient parser
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_amount(amount_str: str) -> str:
        """Normalize amount string: convert fractions to decimal, comma to dot."""
        result = amount_str.strip()
        # Convert Finnish decimal comma to dot
        result = re.sub(r'(\d),(\d)', r'\1.\2', result)
        # Convert fraction notation to decimal for clean amounts
        # Handle mixed fractions: "1 1/2" → "1.5"
        def _replace_mixed(m):
            whole = float(m.group(1))
            num, den = float(m.group(2)), float(m.group(3))
            total = whole + num / den
            return str(int(total)) if total == int(total) else str(round(total, 4)).rstrip('0').rstrip('.')
        result = re.sub(r'(\d+)\s+(\d+)/(\d+)', _replace_mixed, result)
        # Handle plain fractions: "1/2" → "0.5"
        def _replace_frac(m):
            val = float(m.group(1)) / float(m.group(2))
            return str(int(val)) if val == int(val) else str(round(val, 4)).rstrip('0').rstrip('.')
        result = re.sub(r'(\d+)/(\d+)', _replace_frac, result)
        return result

    def _parse_finnish_ingredient(self, text: str) -> Optional[dict]:
        """Parse a Finnish ingredient line such as '250 g kidesokeria'.

        Returns a dict with keys: name, amount, unit.
        Returns None when the text is empty or looks like a section header.
        """
        text = self.clean_text(text)
        if not text:
            return None
        # Skip subsection headers (e.g. "Marenki:", "Pohja:")
        if text.endswith(':'):
            return None

        # If the entire text is wrapped in parentheses (optional ingredient), strip them
        if text.startswith('(') and text.endswith(')'):
            text = text[1:-1].strip()
            if not text:
                return None

        # Normalise Unicode fractions to "N/M" notation before matching
        for frac, frac_str in _FRACTION_MAP.items():
            text = text.replace(frac, frac_str)

        # Build the amount pattern – supports:
        #   integers: 4
        #   decimals: 0.5 / 0,5  (Finnish comma)
        #   plain fractions: 1/4  (after symbol conversion)
        #   mixed fractions: 1 1/4 / 1 1/2
        #   ranges: 2-3 / 1/2-1
        # IMPORTANT: fraction alt must come before plain integer to avoid
        # "1/2" being parsed as just "1" followed by "/2..." name.
        _num = r'(?:\d+/\d+|\d+(?:[.,]\d+)?)'  # fraction first, then int/decimal
        _amount_pat = (
            r'(?:'
            r'\d+\s+\d+/\d+'               # mixed fraction  e.g. "1 1/4"
            r'|{n}(?:\s*[-–]\s*{n})?'      # fraction/int/decimal with optional range
            r')'
        ).format(n=_num)

        pattern = re.compile(
            r'^(?P<amount>' + _amount_pat + r')?\s*'
            r'(?P<unit>' + _FINNISH_UNITS + r')?\s*'
            r'(?P<name>.+)$',
            re.IGNORECASE,
        )
        m = pattern.match(text)
        if not m:
            return {'name': text, 'amount': None, 'unit': None}

        amount_raw = m.group('amount')
        unit = m.group('unit')
        name = m.group('name').strip() if m.group('name') else None

        if not name:
            return None

        # Normalise amount
        amount = self._normalize_amount(amount_raw) if amount_raw else None
        unit = unit.strip().lower() if unit else None

        # Clean name:
        # 1. Remove leading compound amount fragment: "+ 2 rkl" in "0,5 dl + 2 rkl name"
        name = re.sub(
            r'^\+\s*\d+(?:[.,]\d+)?\s*' + _FINNISH_UNITS + r'\s*',
            '',
            name,
            flags=re.IGNORECASE,
        )
        # 2. Remove leading parenthetical weight annotation: "(200 g)" or "(noin 120 g)"
        name = re.sub(r'^\([^)]*\d[^)]*\)\s*', '', name)
        # 3. Remove stray unit abbreviation at start left by parenthetical removal
        name = re.sub(r'^' + _FINNISH_UNITS + r'\s+', '', name, flags=re.IGNORECASE)
        # 4. Remove trailing commas/semicolons and extra whitespace
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()

        if not name:
            return None

        return {'name': name, 'amount': amount, 'unit': unit}

    # ------------------------------------------------------------------
    # Field extractors
    # ------------------------------------------------------------------
    def extract_dish_name(self) -> Optional[str]:
        """Extract recipe title from h1.entry-title."""
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            return self.clean_text(h1.get_text())
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        logger.warning('dish_name not found in %s', self.html_path)
        return None

    def extract_description(self) -> Optional[str]:
        """Extract description from meta[name=description]."""
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        logger.warning('description not found in %s', self.html_path)
        return None

    def extract_ingredients(self) -> Optional[str]:
        """Extract ingredients from ul elements in entry-content."""
        ingredients = []
        for child in self._entry_content_children():
            if child.name != 'ul':
                continue
            for li in child.find_all('li'):
                item_text = self.clean_text(li.get_text(separator=' ', strip=True))
                if not item_text:
                    continue
                parsed = self._parse_finnish_ingredient(item_text)
                if parsed:
                    ingredients.append(parsed)

        if not ingredients:
            logger.warning('ingredients not found in %s', self.html_path)
            return None
        return json.dumps(ingredients, ensure_ascii=False)

    def extract_steps(self) -> Optional[str]:
        """Extract instructions from ol elements in entry-content.

        Section labels (p tags ending with ':' immediately before an ol) are
        prepended to each section's steps to preserve context.
        """
        steps = []
        last_section_label: Optional[str] = None

        for child in self._entry_content_children():
            if child.name == 'p':
                p_text = child.get_text(strip=True)
                if p_text.endswith(':'):
                    last_section_label = p_text[:-1]
                else:
                    last_section_label = None
            elif child.name == 'ol':
                li_items = child.find_all('li')
                if last_section_label and len(li_items) > 0:
                    # Add section header once before the numbered steps
                    steps.append(f'{last_section_label}:')
                for idx, li in enumerate(li_items, 1):
                    step_text = self.clean_text(li.get_text(separator=' ', strip=True))
                    if step_text:
                        steps.append(f'{idx}. {step_text}')
                last_section_label = None
            else:
                # Non-p, non-ol tag resets the label
                if child.name not in ('ul',):
                    last_section_label = None

        if not steps:
            logger.warning('instructions not found in %s', self.html_path)
            return None
        return ' '.join(steps)

    def extract_category(self) -> Optional[str]:
        """Extract post category from span.cat-links inside the main article."""
        # The main article element contains the post's own metadata
        article = self.soup.find('article')
        if article:
            cat_span = article.find('span', class_='cat-links')
            if cat_span:
                link = cat_span.find('a', rel=lambda x: x and 'category' in x)
                if link:
                    return self.clean_text(link.get_text())
        # Fallback: first category link site-wide
        for a in self.soup.find_all('a'):
            rel = a.get('rel') or []
            if 'category' in rel and '/category/' in (a.get('href') or ''):
                return self.clean_text(a.get_text())
        logger.warning('category not found in %s', self.html_path)
        return None

    def extract_tags(self) -> Optional[str]:
        """Extract post tags from a[rel='tag'] links (not category+tag)."""
        tags = []
        seen: set = set()
        # Look only within the main article to avoid related-posts links
        article = self.soup.find('article')
        search_root = article if article else self.soup
        for a in search_root.find_all('a'):
            rel = a.get('rel') or []
            # Pure tag only (WordPress rel="tag"), not rel="category tag"
            if rel == ['tag']:
                text = self.clean_text(a.get_text())
                if text and text not in seen:
                    seen.add(text)
                    tags.append(text)
        if not tags:
            logger.warning('tags not found in %s', self.html_path)
            return None
        return ','.join(tags)

    # ------------------------------------------------------------------
    # Time extraction
    # ------------------------------------------------------------------
    def _extract_cook_time_from_instructions(self, instructions_text: str) -> Optional[str]:
        """Find the primary baking/cooking time in instruction text (Finnish)."""
        if not instructions_text:
            return None

        # Finnish word for one hour
        if re.search(r'yhden\s+tunnin', instructions_text, re.IGNORECASE):
            return '1 hour'

        # Look for a numeric duration near baking/cooking keywords
        cooking_context = re.search(
            r'(?:paista|kypsennä|hauduta|kiehauta|lämmitä)[^.]*?'
            r'(?:noin\s+)?(\d+(?:[.,]\d+)?)\s*(min\w*|h\b|tunt\w*)',
            instructions_text,
            re.IGNORECASE,
        )
        if cooking_context:
            return self._format_time(cooking_context.group(1), cooking_context.group(2))

        # Fallback: first standalone time with "min" or "h/tunti"
        fallback = re.search(
            r'(?:noin\s+)?(\d+(?:[.,]\d+)?)\s*(min\w*|h\b|tunt\w*)',
            instructions_text,
            re.IGNORECASE,
        )
        if fallback:
            return self._format_time(fallback.group(1), fallback.group(2))

        return None

    @staticmethod
    def _format_time(value_str: str, unit_str: str) -> str:
        """Format a numeric value + Finnish time unit into a readable string."""
        value_str = value_str.replace(',', '.')
        try:
            value = float(value_str)
        except ValueError:
            return f'{value_str} minutes'
        unit_lower = unit_str.lower()
        if unit_lower.startswith('h') or unit_lower.startswith('tunt'):
            total_min = int(value * 60)
            if total_min == 60:
                return '1 hour'
            if total_min % 60 == 0:
                return f'{total_min // 60} hours'
            return f'{total_min} minutes'
        # minutes
        total_min = int(value)
        return f'{total_min} minutes'

    def extract_cook_time(self) -> Optional[str]:
        """Extract cooking time from instruction text."""
        instructions = self.extract_steps()
        return self._extract_cook_time_from_instructions(instructions)

    def extract_prep_time(self) -> Optional[str]:
        """Prep time is not available on this site."""
        return None

    def extract_total_time(self) -> Optional[str]:
        """Total time is not available on this site."""
        return None

    def extract_notes(self) -> Optional[str]:
        """Notes are not present in a dedicated section on this site."""
        return None

    def extract_image_urls(self) -> Optional[str]:
        """Extract image URLs from og:image meta tag."""
        urls = []

        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content'].strip()
            if url.startswith('/'):
                url = _BASE_URL + url
            if url:
                urls.append(url)

        # Also check twitter:image as a secondary source
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content'].strip()
            if url.startswith('/'):
                url = _BASE_URL + url
            if url and url not in urls:
                urls.append(url)

        if not urls:
            logger.warning('image_urls not found in %s', self.html_path)
            return None
        return ','.join(urls)

    # ------------------------------------------------------------------
    # Main extraction method
    # ------------------------------------------------------------------
    def extract_all(self) -> dict:
        """Extract all recipe data from the HTML page.

        Returns:
            dict with keys: dish_name, description, ingredients, instructions,
            category, prep_time, cook_time, total_time, notes, image_urls, tags.
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()

        return {
            'dish_name': dish_name.lower() if dish_name else None,
            'description': description.lower() if description else None,
            'ingredients': ingredients,
            'instructions': instructions.lower() if instructions else None,
            'category': category.lower() if category else None,
            'prep_time': self.extract_prep_time(),
            'cook_time': self.extract_cook_time(),
            'total_time': self.extract_total_time(),
            'notes': notes.lower() if notes else None,
            'tags': tags,
            'image_urls': self.extract_image_urls(),
        }


def main():
    import os
    recipes_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'preprocessed',
        'gluteenittomatreseptit_fi',
    )
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(GluteenittomatreseptitFiExtractor, recipes_dir)
        return
    print(f'Директория не найдена: {recipes_dir}')
    print('Использование: python gluteenittomatreseptit_fi.py')


if __name__ == '__main__':
    main()
