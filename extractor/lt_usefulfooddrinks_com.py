"""
Экстрактор данных рецептов для сайта lt.usefulfooddrinks.com
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Mapping of Lithuanian category names to English equivalents
LT_CATEGORY_MAP = {
    'desertai': 'Dessert',
    'desertas': 'Dessert',
    'pagrindinis patiekalas': 'Main Course',
    'pagrindiniai patiekalai': 'Main Course',
    'populiarūs receptai': 'Main Course',
    'geriausi receptai': 'Main Course',
    'salotos': 'Salad',
    'salota': 'Salad',
    'sriubos': 'Soup',
    'sriuba': 'Soup',
    'gėrimai': 'Drinks',
    'gėrimas': 'Drinks',
    'vynai ir spiritiniai gėrimai': 'Drinks',
    'sveikas maistas': 'Healthy Food',
    'maisto gaminimo patarimai': 'Cooking Tips',
    'šokoladas': 'Dessert',
    'kava': 'Drinks',
    'arbata': 'Drinks',
    'namų alaus darykla': 'Drinks',
    'mažai kalorijų turintis maistas': 'Healthy Food',
}

# Lithuanian unit names (long forms must come before short ones)
LT_UNITS_LONG = [
    (r'arbatiniai\s+šaukšteliai', 'šaukštelis'),
    (r'arbatinis\s+šaukštelis', 'šaukštelis'),
    (r'valgomieji\s+šaukštai', 'šaukštas'),
    (r'valgomasis\s+šaukštas', 'šaukštas'),
    (r'valg\.\s*l\.', 'šaukštas'),
    (r'arb\.\s*l\.', 'šaukštelis'),
    (r'arb\.\s*šaukšteliai', 'šaukštelis'),
    (r'valg\.\s*šaukštai', 'šaukštas'),
]

LT_UNITS_SHORT_PATTERN = (
    r'stiklinė|stiklinės|stiklinių|stiklinei|stiklinę|'
    r'puodelis|puodelio|puodeliai|puodelių|puodelį|'
    r'vnt\.|vnt|'
    r'šaukštas|šaukšto|šaukštai|šaukštų|šaukšteliai|šaukštelis|šaukštelio|šaukštelių|'
    r'kg|g|ml|l\b'
)


class LtUsefulfooddrinksComExtractor(BaseRecipeExtractor):
    """Экстрактор для lt.usefulfooddrinks.com"""

    def _get_article_body(self):
        """Return the main article body div."""
        return self.soup.find('div', id='dom_article_body')

    def _is_toc_list(self, ul_elem) -> bool:
        """Return True if the UL is a table-of-contents list (all items are anchor links)."""
        items = ul_elem.find_all('li', recursive=False)
        if not items:
            return False
        anchor_only = all(
            li.find('a') and li.get_text(strip=True) == li.find('a').get_text(strip=True)
            for li in items
        )
        return anchor_only

    def _get_elements(self):
        """
        Return a flat list of relevant block-level Tag elements from the article body.
        Filters out NavigableString whitespace nodes.
        """
        from bs4 import Tag
        article_body = self._get_article_body()
        if not article_body:
            return []
        return [
            c for c in article_body.descendants
            if isinstance(c, Tag) and c.name in ('h2', 'h3', 'p', 'ul', 'ol')
        ]

    def _find_recipe_section_idx(self, elements) -> Optional[int]:
        """
        Return the index (in *elements*) of the h2/h3 that starts the primary
        recipe section, or None if not found.

        A recipe section is identified by:
        1. An h2/h3 whose text contains "receptas" (case-insensitive), OR
        2. The first h2/h3 that is closely followed by a non-TOC UL.
        """
        # Strategy 1: heading contains "receptas"
        for i, elem in enumerate(elements):
            if elem.name in ('h2', 'h3'):
                if re.search(r'receptas', elem.get_text(strip=True), re.IGNORECASE):
                    return i

        # Strategy 2: first heading followed by a non-TOC UL within the next 8 elements
        for i, elem in enumerate(elements):
            if elem.name in ('h2', 'h3'):
                for j in range(i + 1, min(i + 9, len(elements))):
                    if elements[j].name == 'ul' and not self._is_toc_list(elements[j]):
                        return i
                    if elements[j].name in ('h2', 'h3'):
                        break  # New section started – stop looking

        return None

    def _get_recipe_section_elements(self, elements=None):
        """
        Return only the elements that belong to the primary recipe section
        (from the section heading up to – but not including – the next same-level heading).
        Falls back to all elements if no recipe section is detected.
        """
        if elements is None:
            elements = self._get_elements()

        start = self._find_recipe_section_idx(elements)
        if start is None:
            return elements

        heading_name = elements[start].name
        end = len(elements)
        for i in range(start + 1, len(elements)):
            if elements[i].name == heading_name:
                end = i
                break

        return elements[start:end]

    def _get_recipe_section_heading_text(self, elements=None) -> Optional[str]:
        """Return the text of the recipe section heading, if any."""
        if elements is None:
            elements = self._get_elements()
        start = self._find_recipe_section_idx(elements)
        if start is not None:
            return self.clean_text(elements[start].get_text())
        return None

    def extract_dish_name(self) -> Optional[str]:
        """Extract the recipe dish name from the page title."""
        h1 = self.soup.find('h1', class_='entry-title')
        h1_text = self.clean_text(h1.get_text()) if h1 else None

        # If the h1 is a generic "recipes" page title (plural "receptai"),
        # prefer the first recipe section heading as the dish name.
        if h1_text and re.search(r'\breceptai\b', h1_text.lower()):
            recipe_heading = self._get_recipe_section_heading_text()
            if recipe_heading:
                return recipe_heading

        if h1_text:
            return h1_text

        # Fallback: itemprop="name" inside article
        article = self.soup.find('article')
        if article:
            name_meta = article.find('meta', itemprop='name')
            if name_meta and name_meta.get('content'):
                return self.clean_text(name_meta['content'])

        # Fallback: og:title (strip site suffix)
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*-\s*[^-]+$', '', title).strip()
            return self.clean_text(title)

        return None

    def extract_description(self) -> Optional[str]:
        """Extract the recipe description."""
        # itemprop="description" inside article (most specific)
        article = self.soup.find('article')
        if article:
            desc_meta = article.find('meta', itemprop='description')
            if desc_meta and desc_meta.get('content'):
                return self.clean_text(desc_meta['content'])

        # Generic meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        # og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def _parse_ingredient_text(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Parse a single ingredient line into a structured dict.

        Handles several formats encountered on this site:
        - "4-5 kiaušiniai"              → amount="4-5", unit=None,        name="kiaušiniai"
        - "1 stiklinė cukraus"           → amount="1",   unit="stiklinė",  name="cukraus"
        - "140 g cukraus"                → amount="140", unit="g",         name="cukraus"
        - "180g sviesto"                 → amount="180", unit="g",         name="sviesto"
        - "kepimo milteliai"             → amount=None,  unit=None,        name="kepimo milteliai"
        - "kiaušinis - 2 vnt."           → amount="2",   unit="vnt.",      name="kiaušinis"

        Returns:
            {'name': str, 'amount': str|None, 'unit': str|None} or None
        """
        if not text:
            return None

        # Strip trailing punctuation
        text = text.rstrip(';.,').strip()
        if not text:
            return None

        # Normalise Lithuanian decimal notation: "0, 5" → "0.5", "0,5" → "0.5"
        text = re.sub(r'(\d),\s*(\d)', r'\1.\2', text)

        # ── Reversed format: "name - amount [unit]" ────────────────────────────
        rev = re.match(
            r'^(.+?)\s*[-–]\s*(\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?)'
            r'\s*(' + LT_UNITS_SHORT_PATTERN + r')?\s*$',
            text, re.IGNORECASE
        )
        if rev:
            r_name = rev.group(1).strip()
            r_amount = re.sub(r'\s*[-–]\s*', '-', rev.group(2).strip())
            r_unit = rev.group(3).strip() if rev.group(3) else None
            if r_name:
                return {'name': r_name, 'amount': r_amount, 'unit': r_unit}

        # Amount pattern: integer, decimal, range with - or –
        amount_pat = r'(\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?)'

        # ── Amount+unit concatenated (no space): "180g sviesto" ────────────────
        m_concat = re.match(
            r'^' + amount_pat + r'(' + LT_UNITS_SHORT_PATTERN + r')\s+(.*)',
            text, re.IGNORECASE
        )
        if m_concat:
            concat_amount = re.sub(r'\s*[-–]\s*', '-', m_concat.group(1).strip())
            return {
                'name': m_concat.group(3).rstrip(';.,').strip(),
                'amount': concat_amount,
                'unit': m_concat.group(2).strip(),
            }

        # ── Standard: "amount [unit] name" ─────────────────────────────────────
        match = re.match(r'^' + amount_pat + r'\s+(.*)', text)
        if not match:
            # No leading number → ingredient with no amount
            # Strip common qualifiers before returning
            name = self._strip_lt_qualifiers(text)
            return {'name': name, 'amount': None, 'unit': None} if name else None

        amount_str = match.group(1).strip()
        # Normalise spaces around range dash: "500 - 700" → "500-700"
        amount_str = re.sub(r'\s*[-–]\s*', '-', amount_str)
        rest = match.group(2).strip()

        # Try long unit names first
        unit = None
        name = rest
        for unit_pat, unit_norm in LT_UNITS_LONG:
            m = re.match(r'^(' + unit_pat + r')\s+(.*)', rest, re.IGNORECASE)
            if m:
                unit = unit_norm
                name = m.group(2).strip()
                break

        # Try short unit names
        if unit is None:
            m = re.match(r'^(' + LT_UNITS_SHORT_PATTERN + r')\s+(.*)', rest, re.IGNORECASE)
            if m:
                unit = m.group(1).strip()
                name = m.group(2).strip()

        # Strip trailing punctuation and Lithuanian qualifiers from name
        name = name.rstrip(';.,').strip()
        name = self._strip_lt_qualifiers(name)

        if not name:
            return None

        return {'name': name, 'amount': amount_str, 'unit': unit}

    @staticmethod
    def _strip_lt_qualifiers(name: str) -> str:
        """Remove common Lithuanian parenthetical qualifiers from an ingredient name."""
        # ", priklausomai nuo ..." (depending on …)
        name = re.sub(r',\s*priklausomai\s+nuo\s+.*$', '', name, flags=re.IGNORECASE)
        # ", pagal skonį" (to taste)
        name = re.sub(r',?\s*pagal\s+skon[įi]\s*$', '', name, flags=re.IGNORECASE)
        return name.strip()

    def _extract_ingredients_from_section(self, section_elements) -> List[Dict[str, Any]]:
        """Extract ingredients from ALL non-TOC UL elements in *section_elements*."""
        ingredients: List[Dict[str, Any]] = []
        for elem in section_elements:
            if elem.name != 'ul':
                continue
            if self._is_toc_list(elem):
                continue
            for li in elem.find_all('li', recursive=False):
                raw = li.get_text(separator=' ', strip=True)
                raw = self.clean_text(raw)
                parsed = self._parse_ingredient_text(raw)
                if parsed:
                    ingredients.append(parsed)
        return ingredients

    def extract_ingredients(self) -> Optional[str]:
        """Extract ingredients from ALL ULs in the primary recipe section."""
        try:
            elements = self._get_elements()
            section_elements = self._get_recipe_section_elements(elements)
            ingredients = self._extract_ingredients_from_section(section_elements)

            # Fallback: use entire article body
            if not ingredients:
                ingredients = self._extract_ingredients_from_section(elements)

            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

        except Exception as e:
            logger.error("Error extracting ingredients from %s: %s", self.html_path, e)
            return None

    def extract_instructions(self) -> Optional[str]:
        """
        Extract cooking instructions from the primary recipe section.

        Priority order within the section:
        1. OL (ordered list) elements
        2. Numbered paragraphs (starting with "1.", "2.", …) that follow the
           ingredients UL
        3. Regular paragraphs that follow the ingredients UL (Charlotte-style)
        """
        try:
            elements = self._get_elements()
            section_elements = self._get_recipe_section_elements(elements)
            steps: List[str] = []

            # ── 1. OL elements within recipe section ──────────────────────────
            for elem in section_elements:
                if elem.name == 'ol':
                    for idx, li in enumerate(elem.find_all('li'), 1):
                        text = self.clean_text(li.get_text(separator=' ', strip=True))
                        if text:
                            steps.append(f"{idx}. {text}")
                    if steps:
                        break  # Use only the first OL found

            # ── 2 & 3. Paragraphs after the first non-TOC UL in the section ──
            if not steps:
                ul_passed = False
                for elem in section_elements:
                    if elem.name == 'ul' and not self._is_toc_list(elem):
                        ul_passed = True
                        continue
                    if ul_passed and elem.name == 'p':
                        text = elem.get_text(strip=True)
                        clean = self.clean_text(text)
                        if clean and not re.search(
                            r'rekomenduojamas|populiarūs|skelbimai', clean, re.IGNORECASE
                        ):
                            steps.append(clean)
                    elif ul_passed and elem.name in ('h2', 'h3'):
                        break  # Left the recipe section

            return '\n'.join(steps) if steps else None

        except Exception as e:
            logger.error("Error extracting instructions from %s: %s", self.html_path, e)
            return None

    def extract_category(self) -> Optional[str]:
        """Extract recipe category and map to English."""
        # itemprop="articleSection" inside article
        article = self.soup.find('article')
        if article:
            section_meta = article.find('meta', itemprop='articleSection')
            if section_meta and section_meta.get('content'):
                return self._map_category(self.clean_text(section_meta['content']))

        # Breadcrumb navigation
        breadcrumb = self.soup.find('nav', itemtype=re.compile(r'BreadcrumbList', re.I))
        if breadcrumb:
            links = breadcrumb.find_all('a')
            if len(links) > 1:
                last_cat = self.clean_text(links[-1].get_text())
                return self._map_category(last_cat)

        return None

    def _map_category(self, lt_category: str) -> Optional[str]:
        """Map a Lithuanian category name to a standardized English label."""
        if not lt_category:
            return None
        lt_lower = lt_category.lower()
        for key, value in LT_CATEGORY_MAP.items():
            if key in lt_lower:
                return value
        # Return the original if no mapping found
        return lt_category

    def extract_cook_time(self) -> Optional[str]:
        """Extract cooking time from text in the article body."""
        article_body = self._get_article_body()
        if not article_body:
            return None

        try:
            text = article_body.get_text()

            # Patterns for Lithuanian time expressions near baking/cooking context
            time_patterns = [
                # "35-40 minučių", "20-25 minutes", "40 minučių"
                (r'(\d+\s*[-–]\s*\d+)\s*(?:minučių|minut\w*|min\.?)', r'\1 minutes'),
                (r'(\d+)\s*(?:minučių|minut\w*|min\.?)', r'\1 minutes'),
                # Hours
                (r'(\d+)\s*(?:valand\w*|hour\w*)', r'\1 hours'),
            ]

            for pattern, fmt_template in time_patterns:
                for m in re.finditer(pattern, text, re.IGNORECASE):
                    # Check that the match is near a cooking-context keyword
                    start = max(0, m.start() - 80)
                    context = text[start:m.end() + 20].lower()
                    if re.search(r'kep|virk|trosk|laikas|kepimo\s+laikas|minutes?|pašauk', context):
                        time_val = m.group(1).strip()
                        # Normalise spaces in range (e.g. "35 - 40" → "35-40")
                        time_val = re.sub(r'\s*[-–]\s*', '-', time_val)
                        return f"{time_val} minutes"

        except Exception as e:
            logger.error("Error extracting cook time from %s: %s", self.html_path, e)

        return None

    def extract_notes(self) -> Optional[str]:
        """
        Extract tips and notes.

        Strategy:
        1. Numbered tip paragraphs ("1. …", "2. …") that appear *before* the
           primary recipe section heading.
        2. Plain paragraphs that follow the last OL inside the recipe section.
        """
        try:
            elements = self._get_elements()
            recipe_start_idx = self._find_recipe_section_idx(elements)
            notes_parts: List[str] = []

            # ── Strategy 1: numbered tips before the recipe section heading ──
            pre_section = elements[:recipe_start_idx] if recipe_start_idx is not None else []
            for elem in pre_section:
                if elem.name == 'p':
                    text = elem.get_text(strip=True)
                    if re.match(r'^\d+\.', text):
                        clean = self.clean_text(re.sub(r'^\d+\.\s*', '', text))
                        if clean:
                            notes_parts.append(clean)

            # ── Strategy 2: paragraphs after the first OL in the recipe section ──
            section_elements = self._get_recipe_section_elements(elements)
            all_ols = [e for e in section_elements if e.name == 'ol']
            if all_ols:
                first_ol = all_ols[0]
                after_first_ol = False
                for elem in section_elements:
                    if elem is first_ol:
                        after_first_ol = True
                        continue
                    if after_first_ol:
                        if elem.name in ('h2', 'h3', 'ol'):
                            break
                        if elem.name == 'p':
                            text = self.clean_text(elem.get_text(separator=' ', strip=True))
                            if text and len(text) > 20 and not re.search(
                                r'rekomenduojamas|populiarūs|skelbimai|widget',
                                text, re.IGNORECASE
                            ):
                                notes_parts.append(text)

            return ' '.join(notes_parts) if notes_parts else None

        except Exception as e:
            logger.error("Error extracting notes from %s: %s", self.html_path, e)

        return None

    def extract_tags(self) -> Optional[str]:
        """Extract tags from the keywords meta tag."""
        keywords_text: Optional[str] = None

        # itemprop="keywords" inside article
        article = self.soup.find('article')
        if article:
            kw_meta = article.find('meta', itemprop='keywords')
            if kw_meta and kw_meta.get('content'):
                keywords_text = kw_meta['content']

        # Fallback: JSON-LD keywords
        if not keywords_text:
            for script in self.soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script.string or '')
                    if isinstance(data, dict) and 'keywords' in data:
                        keywords_text = data['keywords']
                        break
                except (json.JSONDecodeError, TypeError):
                    continue

        if not keywords_text:
            return None

        keywords_text = self.clean_text(keywords_text)

        # Split by spaces; deduplicate; filter stopwords and short tokens
        stop_words = {
            'su', 'ir', 'kaip', 'iš', 'bei', 'receptas', 'receptai',
            'nuotrauka', 'foto', 'žingsnis', 'po', 'žingsnio', 'paprasta',
            'greitai', 'namuose',
        }

        words = re.split(r'\s+', keywords_text.lower())
        seen: set = set()
        unique: List[str] = []
        for word in words:
            w = word.strip('.,;:!?()')
            if w and len(w) > 3 and w not in stop_words and w not in seen:
                seen.add(w)
                unique.append(w)

        return ', '.join(unique[:8]) if unique else None

    def extract_image_urls(self) -> Optional[str]:
        """Extract image URLs from the article body (itemprop=contentUrl images)."""
        article_body = self._get_article_body()
        urls: List[str] = []

        if article_body:
            for img in article_body.find_all('img', itemprop='contentUrl'):
                src = img.get('src', '').strip()
                if src:
                    urls.append(src)

        # Fallback: og:image
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])

        # Deduplicate, preserving order
        seen: set = set()
        unique: List[str] = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    def extract_all(self) -> dict:
        """Extract all recipe data and return as a dict."""
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        cook_time = self.extract_cook_time()
        notes = self.extract_notes()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()

        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": None,
            "cook_time": cook_time,
            "total_time": None,
            "notes": notes,
            "image_urls": image_urls,
            "tags": tags,
        }


def main():
    import os
    preprocessed_dir = os.path.join(
        str(Path(__file__).parent.parent),
        'preprocessed',
        'lt_usefulfooddrinks_com',
    )
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(LtUsefulfooddrinksComExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python lt_usefulfooddrinks_com.py")


if __name__ == "__main__":
    main()
