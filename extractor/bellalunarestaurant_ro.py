"""
Recipe data extractor for bellalunarestaurant.ro
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Romanian ingredient unit patterns
# ---------------------------------------------------------------------------
_ROMANIAN_UNITS = [
    r'lingurițe', r'linguriță', r'linguri', r'lingură',
    r'căței', r'cățel',
    r'bucăți', r'bucată',
    r'pachet(?:e)?',
    r'felii', r'felie',
    r'ml', r'kg', r'dl', r'cl',
    r'l\b',
    r'g\b',
]

_UNIT_RE = re.compile(
    r'^(?P<amount>[\d,.\-]+(?:[-–][\d,.\-]+)?)\s+'
    r'(?P<unit>' + '|'.join(_ROMANIAN_UNITS) + r')\.?\s+'
    r'(?:de\s+)?(?P<name>.+)$',
    re.IGNORECASE | re.UNICODE,
)

# "1 ardei iute" / "6-8 roșii" — number before noun (no explicit unit)
_AMOUNT_ONLY_RE = re.compile(
    r'^(?P<amount>[\d,.\-]+(?:[-–][\d,.\-]+)?)\s+(?P<name>[^\d].+)$',
    re.UNICODE,
)

# "un strop de X" / "o lingură de Y"
_INFORMAL_AMOUNT_RE = re.compile(
    r'^(?P<amount>un strop(?:\s+de)?|o linguriță de|câteva|puțin(?:ă)?)\s+(?P<name>.+)$',
    re.IGNORECASE | re.UNICODE,
)

# Instruction section headings
_INSTRUCTION_RE = re.compile(
    r'(mod de preparare|preparare|așa o gătim|cum se gătesc|cum se face'
    r'|cum se prepară|pas cu pas|etape|pași de preparare)',
    re.IGNORECASE,
)

# Ingredient section headings
_INGREDIENT_RE = re.compile(r'ingrediente?|ingredient', re.IGNORECASE)

# FAQ / notes section headings
_FAQ_RE = re.compile(r'(întrebări frecvente|faq|tips?|sfaturi)', re.IGNORECASE)


class BellalunarestaurantRoExtractor(BaseRecipeExtractor):
    """Extractor for bellalunarestaurant.ro recipe pages."""

    # ------------------------------------------------------------------ #
    # JSON-LD helpers                                                      #
    # ------------------------------------------------------------------ #

    def _get_blog_posting(self) -> Optional[dict]:
        """Extract the BlogPosting entry from JSON-LD @graph."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'BlogPosting':
                            return item
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.debug("Failed to parse JSON-LD script: %s", exc)
        return None

    def _get_json_ld_image_urls(self) -> List[str]:
        """Extract image URLs from ImageObject entries in JSON-LD @graph."""
        urls: List[str] = []
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'ImageObject':
                            url = item.get('url') or item.get('contentUrl')
                            if url:
                                urls.append(url)
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.debug("Failed to parse JSON-LD script: %s", exc)
        return urls

    # ------------------------------------------------------------------ #
    # Content area helper                                                  #
    # ------------------------------------------------------------------ #

    def _get_content_area(self):
        """Return the main article blog-post_content div."""
        row_div = self.soup.find('div', class_='sidebar_right')
        if row_div:
            main_col = row_div.find('div', class_='wgl_col-9')
            if main_col:
                article = main_col.find('article')
                if article:
                    bpc = article.find('div', class_='blog-post_content')
                    if bpc:
                        return bpc
        # Fallback: first blog-post_content in the page
        return self.soup.find('div', class_='blog-post_content')

    # ------------------------------------------------------------------ #
    # Ingredient text parser                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_ingredient_text(raw: str) -> Optional[dict]:
        """
        Parse a Romanian ingredient string into {name, amount, unit}.

        Handles formats:
        - "200 g de creveți decorticați (de preferat proaspeți)"
        - "2 linguri de unt"
        - "6-8 roșii cherry tăiate pe jumătate"
        - "1 ardei iute mic (pepperoncino) – opțional"
        - "Un strop de sare și mult suflet"
        - "Năut– baza chifteluțelor, hidratat și mărunțit"
        """
        if not raw:
            return None

        text = raw.strip()

        # Strip em-dash / hyphen descriptions: "Ingredient – description"
        # Only strip when there is a space before the dash to avoid stripping ranges like "6-8"
        text = re.sub(r'\s+[–-]\s+.+$', '', text).strip()

        # Remove only advisory parenthetical notes (not ingredient identifiers like "(pepperoncino)")
        text = re.sub(
            r'\s*\(\s*(?:de preferat|dacă|sau mai|opțional)[^)]*\)',
            '', text, flags=re.IGNORECASE,
        ).strip()

        # Remove trailing qualifiers like "după gust", "pentru servire", "opțional"
        text = re.sub(
            r',?\s*(după gust|pentru servire|opțional|sau mai mult|sau mai puțin).*$',
            '', text, flags=re.IGNORECASE,
        ).strip()

        # Remove "și mult suflet" style filler appended after ingredient name
        text = re.sub(r'\s+și mult suflet.*$', '', text, flags=re.IGNORECASE).strip()

        if not text:
            return None

        # "un strop de X" / informal amounts
        m = _INFORMAL_AMOUNT_RE.match(text)
        if m:
            name = m.group('name').strip()
            # Strip "și X" conjunctions at end
            name = re.sub(r'\s+și\s+.*$', '', name, flags=re.IGNORECASE).strip()
            return {
                'name': name,
                'amount': m.group('amount').strip().lower(),
                'unit': None,
            }

        # "N unit de name" — explicit Romanian unit
        m = _UNIT_RE.match(text)
        if m:
            name = m.group('name').strip()
            # Strip advisory trailing content after comma
            name = re.sub(
                r',\s*(de preferat|sau |dacă).+$',
                '', name, flags=re.IGNORECASE,
            ).strip()
            return {
                'name': name,
                'amount': m.group('amount').strip(),
                'unit': m.group('unit').strip(),
            }

        # "N name" (bare number before noun — infer unit from quantity)
        m = _AMOUNT_ONLY_RE.match(text)
        if m:
            amount_str = m.group('amount').strip()
            name = m.group('name').strip()
            # Strip advisory trailing content after comma
            name = re.sub(
                r',\s*(de preferat|dacă).+$',
                '', name, flags=re.IGNORECASE,
            ).strip()

            # Infer unit: "1" → bucată, range or >1 → bucăți
            unit: Optional[str] = None
            if re.match(r'^1$', amount_str):
                unit = 'bucată'
            elif re.search(r'[-–]', amount_str) or (amount_str.isdigit() and int(amount_str) > 1):
                unit = 'bucăți'

            return {'name': name, 'amount': amount_str, 'unit': unit}

        # Plain name only
        return {'name': text, 'amount': None, 'unit': None}

    # ------------------------------------------------------------------ #
    # Extraction methods                                                   #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Extract dish name from H1 tag, stripping subtitle if present."""
        h1 = self.soup.find('h1')
        if h1:
            text = self.clean_text(h1.get_text())
            # Pattern 1: "Rețeta de X care..." → extract X as the dish name
            m = re.match(
                r'^Rețeta\s+(?:de\s+|pentru\s+)?(.+?)\s+(?:care|ce)\b',
                text, re.IGNORECASE,
            )
            if m:
                name = m.group(1).strip()
                # Capitalize first letter
                return name[0].upper() + name[1:] if name else None
            # Pattern 2: "DishName – subtitle" → strip subtitle after em-dash/hyphen
            text = re.sub(r'\s*[–-]\s+\S.+$', '', text).strip()
            return text or None

        blog_posting = self._get_blog_posting()
        if blog_posting:
            name = blog_posting.get('name') or blog_posting.get('headline', '')
            # Strip site name suffix "– BellaLuna Restaurant"
            name = re.sub(r'\s*[-–]\s*BellaLuna.+$', '', name, flags=re.IGNORECASE)
            # Strip trailing "–Rețeta" type suffix
            name = re.sub(r'\s*[-–]\s*Rețeta.*$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name) or None

        return None

    def extract_description(self) -> Optional[str]:
        """Extract recipe description from JSON-LD BlogPosting or og:description."""
        blog_posting = self._get_blog_posting()
        if blog_posting and blog_posting.get('description'):
            return self.clean_text(blog_posting['description'])

        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        content = self._get_content_area()
        if content:
            p = content.find('p')
            if p:
                return self.clean_text(p.get_text())

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Extract ingredients as a JSON-serialised list of {name, amount, unit}."""
        content = self._get_content_area()
        if not content:
            logger.warning("No content area found for ingredients extraction.")
            return None

        ingredients: List[dict] = []
        in_section = False

        elements = content.find_all(['h2', 'h3', 'h4', 'ul', 'p'])
        for elem in elements:
            if elem.name in ('h2', 'h3', 'h4'):
                heading_text = elem.get_text(strip=True)
                if _INGREDIENT_RE.search(heading_text):
                    in_section = True
                elif in_section and elem.name == 'h2':
                    # A new top-level H2 ends the ingredient block
                    break
                # H3/H4 sub-headings within the ingredient section are fine
            elif in_section and elem.name == 'ul':
                for li in elem.find_all('li', recursive=False):
                    raw = self.clean_text(li.get_text(separator=' ', strip=True))
                    if not raw:
                        continue
                    parsed = self._parse_ingredient_text(raw)
                    if parsed:
                        ingredients.append(parsed)

        if not ingredients:
            logger.info("No ingredients found via heading detection for %s", self.html_path)
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_instructions(self) -> Optional[str]:
        """Extract cooking instructions as a single combined string."""
        content = self._get_content_area()
        if not content:
            logger.warning("No content area found for instructions extraction.")
            return None

        steps: List[str] = []
        # Track normalised step texts to avoid duplicates (e.g. UL item + P duplicate)
        seen_steps: set = set()
        in_section = False

        elements = content.find_all(['h2', 'h3', 'h4', 'ul', 'ol', 'p'])
        for elem in elements:
            if elem.name in ('h2', 'h3', 'h4'):
                heading_text = elem.get_text(strip=True)
                if _INSTRUCTION_RE.search(heading_text):
                    in_section = True
                    continue  # Don't add the heading itself
                elif in_section and elem.name == 'h2':
                    break  # Next top-level section ends instructions
                # H3/H4 numbered step titles (e.g. "1. Fierbe pastele") — skip as labels
            elif in_section and elem.name in ('ul', 'ol'):
                for li in elem.find_all('li', recursive=False):
                    raw = self.clean_text(li.get_text(separator=' ', strip=True))
                    if raw:
                        key = re.sub(r'\s+', ' ', raw).lower()[:60]
                        if key not in seen_steps:
                            seen_steps.add(key)
                            steps.append(raw)
            elif in_section and elem.name == 'p':
                raw = self.clean_text(elem.get_text(separator=' ', strip=True))
                if raw:
                    # Skip social media / promo paragraphs
                    if re.search(r'(TikTok|instagram|facebook|youtube|video|social)', raw, re.IGNORECASE):
                        continue
                    # Include only if it looks like an instruction:
                    # - starts with a step number, OR
                    # - is a meaningful sentence (longer than 15 chars)
                    if re.match(r'^\d+[\.\)]\s', raw) or len(raw) > 15:
                        # Strip leading step number prefix for cleaner output
                        raw_clean = re.sub(r'^\d+[\.\)]\s*', '', raw)
                        key = re.sub(r'\s+', ' ', raw_clean).lower()[:60]
                        if key not in seen_steps:
                            seen_steps.add(key)
                            steps.append(raw_clean)

        if not steps:
            logger.info("No instructions found for %s", self.html_path)
        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Extract recipe category from JSON-LD or category link."""
        blog_posting = self._get_blog_posting()
        if blog_posting and blog_posting.get('articleSection'):
            return self.clean_text(str(blog_posting['articleSection']))

        # From /category/ link
        for a in self.soup.find_all('a', href=True):
            href = a.get('href', '')
            if '/category/' in href:
                cat_text = self.clean_text(a.get_text())
                if cat_text:
                    return cat_text

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Prep time — not available as structured data on this site."""
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Cook time — not available as structured data on this site."""
        return None

    def extract_total_time(self) -> Optional[str]:
        """Total time — not available as structured data on this site."""
        return None

    def extract_notes(self) -> Optional[str]:
        """Extract notes from the FAQ (Întrebări frecvente) section."""
        content = self._get_content_area()
        if not content:
            return None

        notes_parts: List[str] = []
        in_section = False

        elements = content.find_all(['h2', 'h3', 'h4', 'ul', 'ol', 'p'])
        for elem in elements:
            if elem.name in ('h2', 'h3', 'h4'):
                if _FAQ_RE.search(elem.get_text(strip=True)):
                    in_section = True
                elif in_section and elem.name == 'h2':
                    break  # Next top-level section ends notes
            elif in_section and elem.name in ('ul', 'ol'):
                for li in elem.find_all('li', recursive=False):
                    raw = self.clean_text(li.get_text(separator=' ', strip=True))
                    if raw:
                        notes_parts.append(raw)
            elif in_section and elem.name == 'p':
                raw = self.clean_text(elem.get_text(strip=True))
                if raw:
                    notes_parts.append(raw)

        return ' '.join(notes_parts) if notes_parts else None

    def extract_tags(self) -> Optional[str]:
        """Extract tags from JSON-LD BlogPosting keywords."""
        blog_posting = self._get_blog_posting()
        if blog_posting and blog_posting.get('keywords'):
            kw = blog_posting['keywords']
            if isinstance(kw, list):
                tags = ', '.join(k.strip() for k in kw if k.strip())
                return tags or None
            if isinstance(kw, str) and kw.strip():
                return kw.strip()

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Extract image URLs from JSON-LD ImageObject entries and og:image."""
        urls: List[str] = []

        # From JSON-LD @graph ImageObject entries (exclude logo-sized images)
        for url in self._get_json_ld_image_urls():
            if url and 'logo' not in url.lower():
                urls.append(url)

        # og:image as fallback / supplement
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # Deduplicate, preserving order
        seen: set = set()
        unique_urls: List[str] = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ','.join(unique_urls) if unique_urls else None

    def extract_all(self) -> dict:
        """Extract all recipe data and return as a dict."""
        try:
            dish_name = self.extract_dish_name()
            description = self.extract_description()
            ingredients = self.extract_ingredients()
            instructions = self.extract_instructions()
            category = self.extract_category()
            notes = self.extract_notes()
            tags = self.extract_tags()
        except Exception as exc:
            logger.error("Unexpected error during extraction for %s: %s", self.html_path, exc, exc_info=True)
            dish_name = description = ingredients = instructions = category = notes = tags = None

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


def main() -> None:
    """Entry point: process all HTML files in preprocessed/bellalunarestaurant_ro."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "bellalunarestaurant_ro")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(BellalunarestaurantRoExtractor, preprocessed_dir)
        return

    print(f"Directory not found: {preprocessed_dir}")
    print("Usage: python extractor/bellalunarestaurant_ro.py")


if __name__ == "__main__":
    main()
