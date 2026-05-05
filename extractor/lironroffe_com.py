"""
Recipe data extractor for lironroffe.com
Hebrew recipe blog (WordPress-based, no WPRM plugin).
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hebrew unit → English mapping (longest match first to avoid partial hits)
# ---------------------------------------------------------------------------
_HE_UNIT_MAP: Dict[str, str] = {
    'קילוגרמים': 'kg',
    'קילוגרם': 'kg',
    'ק"ג': 'kg',
    'קג': 'kg',
    'מיליליטרים': 'ml',
    'מיליליטר': 'ml',
    'מ"ל': 'ml',
    'ליטרים': 'liter',
    'ליטר': 'liter',
    'כוסות': 'cups',
    'כוס': 'cup',
    'כפיות': 'teaspoons',
    'כפית': 'teaspoon',
    'כפות': 'tablespoons',
    'כף': 'tablespoon',
    'גרמים': 'g',
    'גרם': 'g',
    'מיכלים': 'containers',
    'מיכל': 'container',
    'חבילות': 'packages',
    'חבילה': 'package',
    'יחידות': 'units',
    'יחידה': 'unit',
}

# Sorted by descending length for greedy matching
_HE_UNITS_SORTED = sorted(_HE_UNIT_MAP.keys(), key=len, reverse=True)

# Hebrew fraction/number words → float
_HE_FRACTIONS: Dict[str, float] = {
    'שלוש רבעים': 0.75,
    'שלושת רבעי': 0.75,
    'שני שלישים': 2 / 3,
    'שתי שלישיות': 2 / 3,
    'חצי': 0.5,
    'שליש': 1 / 3,
    'רבע': 0.25,
}

# Keywords identifying the ingredients section heading.
# Only applied when the heading text is short (≤ _HEADING_MAX_LEN chars).
_INGREDIENT_KEYWORDS = ['מצרכים', 'רכיבים', 'מרכיבים', 'חומרים']

# Keywords identifying the instructions section heading
_INSTRUCTION_KEYWORDS = [
    'הוראות הכנה',
    'אופן הכנה',
    'אופן ההכנה',
    'הוראות',
    'הכנה',
]

# Keywords identifying the notes section heading
_NOTES_KEYWORDS = [
    'דגשים',
    'נקודות חשובות',
    'חשוב לדעת',
    'חשוב לשים לב',
    'טיפים',
    'הערות',
    'לסיום',
    'לסיכום',
    'תוספות',
    'מומלץ',
    'אילו',
]

# Maximum character length for a heading to be considered a section title
_HEADING_MAX_LEN = 50

# Category mapping: Hebrew section keyword → English category
_CATEGORY_MAP = [
    ('קינוח', 'Dessert'),
    ('עוגה', 'Dessert'),
    ('מאפה', 'Pastry'),
    ('לחם', 'Bread'),
    ('מנה עיקרית', 'Main Course'),
    ('ארוחת ערב', 'Dinner'),
    ('ארוחת בוקר', 'Breakfast'),
    ('סלט', 'Salad'),
    ('מרק', 'Soup'),
    ('רוטב', 'Sauce'),
    ('שתייה', 'Drink'),
]


class LironroffeComExtractor(BaseRecipeExtractor):
    """Extractor for lironroffe.com (Hebrew WordPress recipe blog)."""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_post_content(self):
        """Return the main post-content div (or entry-content fallback)."""
        return (
            self.soup.find('div', class_='post-content')
            or self.soup.find('div', class_='entry-content')
        )

    def _get_json_ld_graph(self) -> List[Dict[str, Any]]:
        """Parse all @graph items from JSON-LD scripts on the page."""
        items: List[Dict[str, Any]] = []
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
                if isinstance(data, dict) and '@graph' in data:
                    items.extend(data['@graph'])
                elif isinstance(data, list):
                    items.extend(data)
                elif isinstance(data, dict):
                    items.append(data)
            except Exception:
                pass
        return items

    def _iter_content_children(self, content):
        """Yield actual element children of the content node."""
        for child in content.children:
            if hasattr(child, 'name') and child.name:
                yield child

    def _is_section_heading(self, child, keywords: List[str]) -> bool:
        """
        Return True if *child* is a short paragraph acting as a section heading
        and its text contains one of the given keywords.
        Excludes long descriptive paragraphs that happen to contain a keyword.
        """
        child_text = child.get_text().strip()
        # Must be short enough to be a heading
        if len(child_text) > _HEADING_MAX_LEN:
            return False
        return any(kw in child_text for kw in keywords)

    def _parse_ingredient(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Parse a single ingredient line into {name, amount, unit}.

        Handles patterns:
          - "250 גרם שוקולד חלב" → amount=250, unit=g, name=שוקולד חלב
          - "2 מיכלים של שמנת מתוקה" → amount=2, unit=containers, name=שמנת מתוקה
          - "4 ביצים" → amount=4, unit=None, name=ביצים
          - "כוס סוכר" → amount=1, unit=cup, name=סוכר
          - "חצי כוס שמנת" → amount=0.5, unit=cup, name=שמנת
          - "כוס פחות 2 כפות שוקולית" → amount≈0.875, unit=cup, name=שוקולית
          - "דובוני גומי" → amount=None, unit=None, name=דובוני גומי
        """
        text = self.clean_text(text)
        if not text:
            return None

        amount: Optional[str] = None
        unit: Optional[str] = None
        name: str = text

        # --- 1. Try leading Arabic numeral ---
        m = re.match(r'^(\d+(?:[./]\d+)?)\s+(.+)$', text)
        if m:
            raw_num, rest = m.group(1), m.group(2).strip()
            amount = self._parse_number(raw_num)
            unit, name = self._split_unit_name(rest)
            # If no unit was found, the word itself is the ingredient (e.g. "4 ביצים")
            # and it is a countable discrete item → unit = "units"
            if unit is None:
                unit = 'units'
            # Special: "כוס פחות 2 כפות X" handled separately below
        else:
            # --- 2. Try Hebrew fraction word ---
            found_frac = False
            for frac_str, frac_val in sorted(
                _HE_FRACTIONS.items(), key=lambda x: -len(x[0])
            ):
                if text.startswith(frac_str + ' ') or text == frac_str:
                    amount = self._fmt_float(frac_val)
                    rest = text[len(frac_str):].strip()
                    unit, name = self._split_unit_name(rest)
                    found_frac = True
                    break

            if not found_frac:
                # --- 3. Try leading Hebrew unit word (e.g. "כוס סוכר") ---
                found_unit = False
                for he_unit in _HE_UNITS_SORTED:
                    if text.startswith(he_unit + ' ') or text == he_unit:
                        amount = '1'
                        unit = _HE_UNIT_MAP[he_unit]
                        name_part = text[len(he_unit):].strip()
                        name_part = re.sub(r'^של\s+', '', name_part)
                        name = name_part if name_part else he_unit
                        found_unit = True
                        # Handle "כוס פחות X כפות Y"
                        # Assumes US customary: 1 cup = 16 tablespoons
                        if unit in ('cup', 'cups') and name.startswith('פחות'):
                            m2 = re.match(r'פחות\s+(\d+)\s+(?:כפות?|כפיות?)\s+(.+)', name)
                            if m2:
                                subtract_tbsp = int(m2.group(1))
                                # 1 cup = 16 tablespoons
                                adjusted = float(amount) - subtract_tbsp / 16
                                amount = self._fmt_float(adjusted)
                                name = self.clean_text(m2.group(2))
                        break
                # If nothing matched, name stays as full text

        return {'name': name.strip(), 'amount': amount, 'unit': unit}

    def _parse_number(self, raw: str) -> str:
        """Convert '1/2', '0.5', '2' etc. to string representation."""
        if '/' in raw:
            parts = raw.split('/')
            try:
                return self._fmt_float(float(parts[0]) / float(parts[1]))
            except ZeroDivisionError:
                return raw
        return raw

    def _fmt_float(self, val: float) -> str:
        """Format float, removing trailing zeros."""
        s = f'{val:.4f}'.rstrip('0').rstrip('.')
        return s if s else '0'

    def _split_unit_name(self, text: str) -> Tuple[Optional[str], str]:
        """
        Try to extract a leading unit and return (unit_en, name_rest).
        Strips 'של' particle after unit.
        """
        for he_unit in _HE_UNITS_SORTED:
            if text.startswith(he_unit + ' ') or text == he_unit:
                unit = _HE_UNIT_MAP[he_unit]
                rest = text[len(he_unit):].strip()
                rest = re.sub(r'^של\s+', '', rest)
                # Normalize slash-separated alternatives "X / Y" → "X/Y"
                rest = re.sub(r'\s*/\s*', '/', rest)
                return unit, rest if rest else text
        return None, text

    # ------------------------------------------------------------------
    # Field extractors
    # ------------------------------------------------------------------

    def _extract_dish_name(self) -> Optional[str]:
        """Extract dish name from h1 tag, falling back to og:title."""
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Remove site name suffix "| Site Name"
            title = re.sub(r'\s*\|.*$', '', title).strip()
            return self.clean_text(title)

        return None

    def _extract_description(self) -> Optional[str]:
        """Extract description from og:description or meta description."""
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        return None

    def _extract_ingredients(self) -> Optional[str]:
        """
        Extract ingredients list from the post content.

        Looks for a paragraph containing an ingredient keyword (e.g. 'מצרכים')
        followed by a <ul> element.
        """
        content = self._get_post_content()
        if not content:
            logger.warning('lironroffe: no post-content found')
            return None

        children = list(self._iter_content_children(content))
        ingredients: List[Dict[str, Any]] = []

        for i, child in enumerate(children):
            if not self._is_section_heading(child, _INGREDIENT_KEYWORDS):
                continue

            # Found ingredient heading — look forward for a <ul>
            for j in range(i + 1, len(children)):
                sibling = children[j]
                if sibling.name == 'ul':
                    for li in sibling.find_all('li'):
                        raw = self.clean_text(li.get_text(separator=' ', strip=True))
                        if raw:
                            parsed = self._parse_ingredient(raw)
                            if parsed and parsed['name']:
                                ingredients.append(parsed)
                    break
                # Stop if we hit another section heading or numbered list
                if sibling.name in ('ol', 'h2', 'h3'):
                    break
                # Skip divs/figures (e.g. inline images) between heading and list

            if ingredients:
                break

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def _extract_instructions(self) -> Optional[str]:
        """
        Extract cooking instructions from the <ol> after an instruction heading.
        """
        content = self._get_post_content()
        if not content:
            return None

        children = list(self._iter_content_children(content))
        steps: List[str] = []

        for i, child in enumerate(children):
            if not self._is_section_heading(child, _INSTRUCTION_KEYWORDS):
                continue

            # Found instruction heading — look forward for an <ol>
            for j in range(i + 1, len(children)):
                sibling = children[j]
                if sibling.name == 'ol':
                    for idx, li in enumerate(sibling.find_all('li'), 1):
                        raw = self.clean_text(li.get_text(separator=' ', strip=True))
                        if raw:
                            steps.append(f'{idx}. {raw}')
                    break
                if sibling.name in ('h2', 'h3'):
                    break
                # Skip divs/figures between heading and list

            if steps:
                break

        return ' '.join(steps) if steps else None

    def _extract_category(self) -> Optional[str]:
        """
        Extract category from JSON-LD Article.articleSection or the post-categories
        anchor links, then map to English via _CATEGORY_MAP.
        """
        # Collect section names from JSON-LD and post category links
        section_names: List[str] = []

        for item in self._get_json_ld_graph():
            if item.get('@type') == 'Article':
                section_names.extend(item.get('articleSection', []))

        # Also check post-categories HTML element for extra category data
        post_cat_div = self.soup.find(class_=re.compile(r'^post-cat(egories)?$'))
        if post_cat_div:
            for a in post_cat_div.find_all('a', rel='category'):
                name = self.clean_text(a.get_text())
                if name and name not in section_names:
                    section_names.append(name)

        for section in section_names:
            for keyword, category in _CATEGORY_MAP:
                if keyword in section:
                    return category

        # Return the first section name if no mapping matches
        if section_names:
            return section_names[0]

        return None

    def _extract_times(self) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Extract prep, cook, and total times by scanning the page text.

        Strategy:
          - prep_time:  "X דקות הכנה/עבודה" patterns anywhere in content
          - cook_time:  hours or baking minutes in the OL instructions
          - total_time: sum of prep+cook, or resting/setting time when prep exists
        """
        content = self._get_post_content()
        if not content:
            return None, None, None

        full_text = content.get_text(separator=' ', strip=True)

        # --- Prep time ---
        prep_minutes: Optional[int] = None
        prep_patterns = [
            r'(\d+)\s*דקות?\s+(?:עבודה|הכנה)',
            r'ב-?(\d+)\s*דקות?\s+הכנה',
            r'מתכון\s+\S+\s+ב-?(\d+)\s*דקות?',
        ]
        for pat in prep_patterns:
            m = re.search(pat, full_text)
            if m:
                prep_minutes = int(m.group(1))
                break

        # --- Cook / resting time from OL instructions ---
        cook_minutes: Optional[int] = None
        resting_minutes: Optional[int] = None

        ol = content.find('ol', class_=re.compile('wp-block-list', re.I)) or content.find('ol')
        if ol:
            ol_text = ol.get_text(separator=' ', strip=True)

            # 1. "שעתיים" = 2 hours
            if 'שעתיים' in ol_text:
                cook_minutes = 120

            # 2. "X שעות" = X * 60 minutes
            elif re.search(r'(\d+)\s+שעות', ol_text):
                m_h = re.search(r'(\d+)\s+שעות', ol_text)
                cook_minutes = int(m_h.group(1)) * 60  # type: ignore[union-attr]

            # 3. Explicit baking/cooking minutes: "ל-X דקות" (e.g. "ל-45 דקות")
            elif re.search(r'ל-?(\d+)\s*דקות', ol_text):
                m_min = re.search(r'ל-?(\d+)\s*דקות', ol_text)
                cook_minutes = int(m_min.group(1))  # type: ignore[union-attr]

            # 4. Resting/setting time: "כחצי שעה" / "חצי שעה" (checked before bare "שעה")
            elif 'כחצי שעה' in ol_text or re.search(r'(?<!\w)חצי שעה', ol_text):
                resting_minutes = 30

            # 5. Standalone "שעה" (not preceded by "חצי")
            elif re.search(r'(?<!חצי )(?<!\w)שעה(?!\w)', ol_text):
                cook_minutes = 60

        # Also check "שעתיים" anywhere if OL didn't capture it
        if cook_minutes is None and 'שעתיים' in full_text:
            cook_minutes = 120

        # --- Decide total ---
        total_minutes: Optional[int] = None
        if prep_minutes is not None and cook_minutes is not None:
            total_minutes = prep_minutes + cook_minutes
        elif prep_minutes is not None and resting_minutes is not None:
            # e.g. file #2: prep=5min + resting=30min → total=30min (resting dominates)
            total_minutes = resting_minutes
        elif resting_minutes is not None and prep_minutes is None:
            # No explicit prep, treat resting as cook
            cook_minutes = resting_minutes

        prep = self._fmt_minutes(prep_minutes)
        cook = self._fmt_minutes(cook_minutes)
        total = self._fmt_minutes(total_minutes)
        return prep, cook, total

    def _fmt_minutes(self, minutes: Optional[int]) -> Optional[str]:
        """Format an integer minute count to a human-readable string."""
        if minutes is None:
            return None
        if minutes >= 60 and minutes % 60 == 0:
            h = minutes // 60
            return f'{h} {"hour" if h == 1 else "hours"}'
        if minutes >= 60:
            h = minutes // 60
            m = minutes % 60
            return f'{h} hour{"s" if h > 1 else ""} {m} minutes'
        return f'{minutes} minutes'

    def _extract_notes(self) -> Optional[str]:
        """
        Extract recipe notes/tips from the <ul> following a notes heading.
        Falls back to the first <ul> after the instructions <ol> if no notes
        heading is found.
        """
        content = self._get_post_content()
        if not content:
            return None

        children = list(self._iter_content_children(content))
        notes_items: List[str] = []

        # Primary: look for a recognized notes heading followed by a <ul>
        for i, child in enumerate(children):
            child_text = child.get_text().strip()
            if not any(kw in child_text for kw in _NOTES_KEYWORDS):
                continue

            for j in range(i + 1, len(children)):
                sibling = children[j]
                if sibling.name == 'ul':
                    for li in sibling.find_all('li'):
                        raw = self.clean_text(li.get_text(separator=' ', strip=True))
                        if raw:
                            notes_items.append(raw)
                    break
                if sibling.name in ('ol', 'h2', 'h3'):
                    break
                # Skip divs/figures between heading and list

            if notes_items:
                break

        # Fallback: first <ul> that comes after the instructions <ol>
        # (handles pages where notes follow instructions without a dedicated heading)
        if not notes_items:
            found_ol = False
            for child in children:
                if child.name == 'ol':
                    found_ol = True
                    continue
                if found_ol and child.name == 'ul':
                    for li in child.find_all('li'):
                        raw = self.clean_text(li.get_text(separator=' ', strip=True))
                        if raw:
                            notes_items.append(raw)
                    break

        return ' '.join(notes_items) if notes_items else None

    def _extract_tags(self) -> Optional[str]:
        """
        Extract tags from JSON-LD Article.keywords, post-tags div, or rel=tag links.
        """
        # Priority 1: JSON-LD Article keywords
        for item in self._get_json_ld_graph():
            if item.get('@type') == 'Article':
                keywords = item.get('keywords', [])
                if keywords:
                    return ', '.join(self.clean_text(k) for k in keywords)

        # Priority 2: post-tags div (WordPress tag links with href /tag/)
        post_tags_div = self.soup.find(class_='post-tags')
        if post_tags_div:
            tags = [
                self.clean_text(a.get_text())
                for a in post_tags_div.find_all('a', rel='tag')
            ]
            tags = [t for t in tags if t]
            if tags:
                return ', '.join(tags)

        return None

    def _extract_image_urls(self) -> Optional[str]:
        """
        Collect image URLs from og:image, JSON-LD ImageObject/thumbnailUrl,
        and lazy-loaded inline content images.
        """
        urls: List[str] = []

        # 1. og:image
        og_img = self.soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            urls.append(og_img['content'])

        # 2. JSON-LD: ImageObject.url, Article/WebPage.thumbnailUrl
        for item in self._get_json_ld_graph():
            t = item.get('@type', '')
            if t == 'ImageObject':
                url = item.get('url') or item.get('contentUrl')
                if url and 'gravatar.com' not in url:
                    urls.append(url)
            elif t in ('Article', 'WebPage'):
                thumb = item.get('thumbnailUrl')
                if thumb:
                    urls.append(thumb)

        # 3. Inline images in post content (lazy-loaded)
        content = self._get_post_content()
        if content:
            for img in content.find_all('img'):
                src = (
                    img.get('data-lazy-src')
                    or img.get('data-src')
                    or img.get('src')
                )
                if src and not src.startswith('data:'):
                    # Only include images hosted on the recipe site itself
                    try:
                        from urllib.parse import urlparse
                        parsed = urlparse(src)
                        if parsed.netloc in ('lironroffe.com', 'www.lironroffe.com'):
                            urls.append(src)
                    except Exception:
                        pass

        if not urls:
            return None

        # Deduplicate preserving order
        seen: set = set()
        unique: List[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """Extract all recipe data from the HTML page."""
        result: Dict[str, Any] = {
            'dish_name': None,
            'description': None,
            'ingredients': None,
            'instructions': None,
            'category': None,
            'prep_time': None,
            'cook_time': None,
            'total_time': None,
            'notes': None,
            'image_urls': None,
            'tags': None,
        }

        for field, extractor in [
            ('dish_name', self._extract_dish_name),
            ('description', self._extract_description),
            ('ingredients', self._extract_ingredients),
            ('instructions', self._extract_instructions),
            ('category', self._extract_category),
            ('notes', self._extract_notes),
            ('tags', self._extract_tags),
            ('image_urls', self._extract_image_urls),
        ]:
            try:
                result[field] = extractor()
            except Exception as exc:
                logger.warning('lironroffe: error extracting %s: %s', field, exc)

        try:
            prep, cook, total = self._extract_times()
            result['prep_time'] = prep
            result['cook_time'] = cook
            result['total_time'] = total
        except Exception as exc:
            logger.warning('lironroffe: error extracting times: %s', exc)

        return result


def main() -> None:
    import os

    recipes_dir = os.path.join('preprocessed', 'lironroffe_com')
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(LironroffeComExtractor, str(recipes_dir))
        return

    print(f'Directory not found: {recipes_dir}')


if __name__ == '__main__':
    main()
