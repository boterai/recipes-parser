"""
Recipe data extractor for pofta-buna.com

The site uses an EasyRecipe WordPress plugin card for structured data
(dish name, description, ingredients, timing). Instructions and notes
are extracted from the article body.
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Romanian measurement units recognised on pofta-buna.com
_RO_UNITS = [
    r'lingurițe?',
    r'linguriță',
    r'linguri',
    r'lingură',
    r'cești?',
    r'ceașcă',
    r'pahare?',
    r'pahar',
    r'pachet(?:e)?',
    r'bucăți',
    r'bucată',
    r'buc\.',
    r'cutie',
    r'cutii',
    r'felii',
    r'felie',
    r'ml',
    r'dl',
    r'cl',
    r'l\b',
    r'kg',
    r'g\b',
    r'cm',
    r'mm',
]
_UNIT_PAT = '|'.join(_RO_UNITS)

# AMOUNT[UNIT][de ]NAME  (e.g. "500g de mascarpone", "1-2 linguri de cacao")
_ING_UNIT_RE = re.compile(
    r'^(?P<amount>(?:aprox\.?\s+)?[\d,.]+(?:\s*[-–]\s*[\d,.]+)?)\s*'
    r'(?P<unit>' + _UNIT_PAT + r')\.?\s*'
    r'(?:de\s+)?'
    r'(?P<name>.+)$',
    re.IGNORECASE | re.UNICODE,
)

# AMOUNT NAME  (counted items without a unit, e.g. "6 ouă proaspete")
_ING_AMOUNT_RE = re.compile(
    r'^(?P<amount>[\d,.]+(?:\s*[-–]\s*[\d,.]+)?)\s+'
    r'(?P<name>[^\d].+)$',
    re.UNICODE,
)

# Keywords that identify the beginning of the instructions section
_INSTR_KEYWORDS = [
    'cum se face', 'cum se prepara', 'cum preparam', 'cum preparăm',
    'mod de preparare', 'cum se gatesc', 'cum se gătesc',
    'cum prepari', 'cum se prepară',
]

# Keywords that identify tips / notes sections
_NOTES_KEYWORDS = [
    'sfaturi', 'truc', 'trucuri', 'posibile defectiuni',
    'posibile defecțiuni', 'remedieri',
]

# Paragraphs that signal end-of-recipe content (not instructions)
_END_PATTERNS = re.compile(
    r'^(?:pofta\s+bun[aă]|poftă\s+bun[aă]|va\s+invit|vă\s+invit|'
    r'bibliografie|surse\s*:|mai\s+multe\s+retete)',
    re.IGNORECASE,
)


class PoftaBunaComExtractor(BaseRecipeExtractor):
    """Extractor for pofta-buna.com (EasyRecipe plugin + article body)."""

    # ------------------------------------------------------------------ #
    # Duration helpers                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """Convert ISO 8601 duration (PT30M, PT1H30M) to a human-readable string."""
        if not duration or not duration.upper().startswith('PT'):
            return None
        s = duration[2:]
        h_match = re.search(r'(\d+)H', s, re.IGNORECASE)
        m_match = re.search(r'(\d+)M', s, re.IGNORECASE)
        hours = int(h_match.group(1)) if h_match else 0
        minutes = int(m_match.group(1)) if m_match else 0
        if hours == 0 and minutes == 0:
            return None
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        return ' '.join(parts)

    # ------------------------------------------------------------------ #
    # JSON-LD helpers                                                     #
    # ------------------------------------------------------------------ #

    def _get_recipe_jsonld(self) -> Optional[dict]:
        """Return the first JSON-LD Recipe object found on the page."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get('@type') == 'Recipe':
                        return item
            elif isinstance(data, dict):
                if data.get('@type') == 'Recipe':
                    return data
                for item in data.get('@graph', []):
                    if isinstance(item, dict) and item.get('@type') == 'Recipe':
                        return item
        return None

    def _get_breadcrumb_jsonld(self) -> Optional[dict]:
        """Return the first BreadcrumbList JSON-LD object found on the page."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get('@type') == 'BreadcrumbList':
                        return item
            elif isinstance(data, dict):
                if data.get('@type') == 'BreadcrumbList':
                    return data
        return None

    # ------------------------------------------------------------------ #
    # DOM helpers                                                         #
    # ------------------------------------------------------------------ #

    def _get_recipe_card(self):
        """Return the EasyRecipe card element (div.easyrecipe), or None."""
        return self.soup.find('div', class_='easyrecipe')

    def _get_entry_content(self):
        """Return the article entry-content element, or None."""
        article = self.soup.find('article')
        if article:
            ec = article.find(class_='entry-content')
            if ec:
                return ec
        return self.soup.find(class_='entry-content')

    # ------------------------------------------------------------------ #
    # Ingredient parsing                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_single_ingredient(text: str) -> Optional[dict]:
        """
        Parse one ingredient text into {name, amount, unit}.

        Handles formats such as:
          "500 g de mascarpone (la temperatura camerei)"
          "1-2 linguri de cacao naturală, neîndulcită"
          "-100 g unt + inca 1 lingurita"
          "6 ouă proaspete"
          "nucsoara"
        """
        if not text:
            return None
        text = text.strip()

        # Try AMOUNT UNIT [de] NAME
        m = _ING_UNIT_RE.match(text)
        if m:
            amount = m.group('amount').strip().replace(',', '.')
            unit = m.group('unit').strip()
            name = m.group('name').strip()
            # Drop extra info after " + " (e.g. "unt + inca 1 lingurita" → "unt")
            name = re.split(r'\s+\+\s+', name)[0].strip()
            # Strip a secondary "cu N unit " prefix in the name
            # (e.g. "1 cutie cu 500 g foi de lasagna" → name was "cu 500 g foi de lasagna")
            name = re.sub(
                r'^cu\s+[\d,.]+(?:\s*[-–]\s*[\d,.]+)?\s*(?:' + _UNIT_PAT + r')\.?\s*(?:de\s+)?',
                '', name, flags=re.IGNORECASE | re.UNICODE,
            ).strip()
            return {'name': name, 'amount': amount, 'unit': unit}

        # Try AMOUNT NAME (no unit)
        m = _ING_AMOUNT_RE.match(text)
        if m:
            return {
                'name': m.group('name').strip(),
                'amount': m.group('amount').strip().replace(',', '.'),
                'unit': None,
            }

        # Name only (no amount, no unit)
        return {'name': text, 'amount': None, 'unit': None}

    def _parse_ingredient_line(self, text: str) -> list:
        """
        Parse an ingredient line into a list of ingredient dicts.

        Lines with no amount/unit that contain commas are split (e.g.
        "sare, piper, 1 frunza de dafin" → three separate ingredients).
        """
        text = self.clean_text(text)
        if not text:
            return []

        # Strip leading dashes / hyphens (common on this site)
        text = re.sub(r'^[-–\s]+', '', text).strip()
        if not text:
            return []

        # Skip section header lines like "Pentru sosul bechamel"
        if re.match(r'^pentru\b', text, re.IGNORECASE):
            return []

        result = self._parse_single_ingredient(text)

        # If we found amount or unit, return as-is (comma is part of name)
        if result and (result.get('amount') is not None or result.get('unit') is not None):
            return [result]

        # No amount/unit – attempt comma-split into multiple simple ingredients
        if ',' in text:
            parts = [p.strip() for p in text.split(',')]
            # Only split if all parts are short (likely individual ingredient words)
            if len(parts) > 1 and all(p and len(p.split()) <= 5 for p in parts):
                parsed = [self._parse_single_ingredient(p) for p in parts if p]
                parsed = [p for p in parsed if p]
                if len(parsed) > 1:
                    return parsed

        return [result] if result else []

    # ------------------------------------------------------------------ #
    # Section-type helpers                                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_instruction_heading(text: str) -> bool:
        """Return True if the heading text marks an instructions section."""
        lower = text.lower().strip()
        return any(kw in lower for kw in _INSTR_KEYWORDS)

    @staticmethod
    def _is_notes_heading(text: str) -> bool:
        """Return True if the heading text marks a tips/notes section."""
        lower = text.lower().strip()
        return any(kw in lower for kw in _NOTES_KEYWORDS)

    # ------------------------------------------------------------------ #
    # Field extractors                                                    #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """
        Extract recipe title.

        Both JSON-LD and the EasyRecipe card are checked.  When the JSON-LD
        name starts with the card name (i.e. the card name is a clean prefix),
        the shorter card name is preferred to avoid SEO suffixes.  Otherwise
        the JSON-LD name is used as it may carry additional detail.
        """
        try:
            recipe_ld = self._get_recipe_jsonld()
            jsonld_name = self.clean_text(recipe_ld['name']) if (
                recipe_ld and recipe_ld.get('name')
            ) else None

            card = self._get_recipe_card()
            card_name = None
            if card:
                name_div = card.find(class_='ERSName')
                if name_div:
                    card_name = self.clean_text(name_div.get_text())

            if jsonld_name and card_name:
                # If the JSON-LD title is just the card title with extra SEO words
                # appended, use the shorter card title.
                if jsonld_name.lower().startswith(card_name.lower()):
                    return card_name
                return jsonld_name

            if jsonld_name:
                return jsonld_name
            if card_name:
                return card_name

            h1 = self.soup.find('h1')
            if h1:
                return self.clean_text(h1.get_text())

            og = self.soup.find('meta', property='og:title')
            if og and og.get('content'):
                title = og['content']
                title = re.sub(
                    r'\s*[-–|]\s*(?:Pofta Buna|Rețete cu Gina Bradea).*$',
                    '', title, flags=re.IGNORECASE,
                )
                return self.clean_text(title)
        except Exception as exc:
            logger.warning("Error extracting dish_name: %s", exc)
        return None

    def extract_description(self) -> Optional[str]:
        """Extract description from EasyRecipe summary or meta tags."""
        try:
            card = self._get_recipe_card()
            if card:
                summary = card.find(class_='ERSSummary')
                if summary:
                    return self.clean_text(summary.get_text())

            recipe_ld = self._get_recipe_jsonld()
            if recipe_ld and recipe_ld.get('description'):
                return self.clean_text(recipe_ld['description'])

            og = self.soup.find('meta', property='og:description')
            if og and og.get('content'):
                return self.clean_text(og['content'])

            meta = self.soup.find('meta', attrs={'name': 'description'})
            if meta and meta.get('content'):
                return self.clean_text(meta['content'])
        except Exception as exc:
            logger.warning("Error extracting description: %s", exc)
        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Extract ingredients from the EasyRecipe card.

        For some older recipes the card contains only part of the ingredient
        list; the rest is written as plain paragraphs in the article body
        (between the card and the first instructions heading).  Both sources
        are merged.
        """
        try:
            ingredients: list = []

            # ---- 1. EasyRecipe card ----
            card = self._get_recipe_card()
            if card:
                ing_div = card.find(class_='ERSIngredients')
                if ing_div:
                    for li in ing_div.find_all('li', class_='ingredient'):
                        text = self.clean_text(li.get_text())
                        ingredients.extend(self._parse_ingredient_line(text))

            # ---- 2. Extra paragraph ingredients in article body ----
            entry_content = self._get_entry_content()
            if entry_content and card:
                past_card = False
                for elem in entry_content.children:
                    # NavigableString nodes have name == None
                    if getattr(elem, 'name', None) is None:
                        continue

                    if elem is card:
                        past_card = True
                        continue

                    if not past_card:
                        continue

                    # Stop at the instructions heading
                    if elem.name in ('h2', 'h3', 'h4'):
                        if self._is_instruction_heading(elem.get_text(strip=True)):
                            break
                        continue

                    # Collect paragraph lines that look like ingredients
                    if elem.name == 'p':
                        text = self.clean_text(elem.get_text())
                        if not text:
                            continue
                        # Ingredient paragraph: starts with dash or digit
                        if re.match(r'^[-–]|\d', text):
                            parsed = self._parse_ingredient_line(text)
                            for ing in parsed:
                                if ing not in ingredients:
                                    ingredients.append(ing)

            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
        except Exception as exc:
            logger.warning("Error extracting ingredients: %s", exc)
        return None

    def extract_steps(self) -> Optional[str]:
        """
        Extract instructions from the article body.

        Collects paragraph content that follows the instructions heading
        (h2/h3 containing "cum se face", "mod de preparare", etc.) and
        stops before the notes/tips heading or the next major h2 section.
        """
        try:
            entry_content = self._get_entry_content()
            if not entry_content:
                return None

            elements = list(entry_content.children)

            # Find the first instructions heading
            instr_start = -1
            for i, elem in enumerate(elements):
                if getattr(elem, 'name', None) not in ('h2', 'h3', 'h4'):
                    continue
                if self._is_instruction_heading(elem.get_text(strip=True)):
                    instr_start = i
                    break

            if instr_start == -1:
                return None

            steps: list = []
            for elem in elements[instr_start + 1:]:
                if getattr(elem, 'name', None) is None:
                    continue

                if elem.name in ('h2', 'h3', 'h4'):
                    heading_text = elem.get_text(strip=True)
                    # Stop at notes heading
                    if self._is_notes_heading(heading_text):
                        break
                    # Stop at the next major h2 that is not an instruction sub-section
                    if elem.name == 'h2' and not self._is_instruction_heading(heading_text):
                        break
                    # h3/h4 sub-sections stay inside the instructions block
                    continue

                if elem.name == 'p':
                    text = self.clean_text(elem.get_text())
                    if not text:
                        continue
                    # Skip introductory "read the written recipe or watch the video" lines
                    if re.match(
                        r'^puteți?\s+citi|^puteti\s+citi|^puteți?\s+urmări|^puteti\s+urmari',
                        text, re.IGNORECASE,
                    ):
                        continue
                    # Stop at typical end-of-article markers
                    if _END_PATTERNS.match(text):
                        break
                    steps.append(text)

                elif elem.name in ('ul', 'ol'):
                    for li in elem.find_all('li'):
                        text = self.clean_text(li.get_text())
                        if text:
                            steps.append(text)

                # Skip div wrappers (ads, embeds, share boxes)

            if not steps:
                return None

            numbered = [f"{i + 1}. {step}" for i, step in enumerate(steps)]
            return '\n'.join(numbered)
        except Exception as exc:
            logger.warning("Error extracting steps: %s", exc)
        return None

    def _extract_time_from_card(self, heading_keywords: list) -> Optional[str]:
        """
        Extract a time value from the EasyRecipe card's ERSTimes section.

        Matches the ERSTimeHeading text against *heading_keywords* and
        returns the parsed duration string.
        """
        try:
            card = self._get_recipe_card()
            if not card:
                return None
            times_div = card.find(class_='ERSTimes')
            if not times_div:
                return None

            for block in times_div.find_all(class_='ERSTime'):
                heading = block.find(class_='ERSTimeHeading')
                if not heading:
                    continue
                heading_text = heading.get_text(strip=True).lower()
                if any(kw in heading_text for kw in heading_keywords):
                    time_tag = block.find('time')
                    if time_tag:
                        dt = time_tag.get('datetime', '')
                        if dt and dt.upper().startswith('PT'):
                            return self._parse_iso_duration(dt)
                        return self.clean_text(time_tag.get_text())
        except Exception as exc:
            logger.warning("Error extracting time: %s", exc)
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Extract preparation time from EasyRecipe card."""
        return self._extract_time_from_card(['preg', 'preparare'])

    def extract_cook_time(self) -> Optional[str]:
        """Extract cooking time from EasyRecipe card."""
        return self._extract_time_from_card(['gatit', 'gătit', 'coacere'])

    def extract_total_time(self) -> Optional[str]:
        """Extract total time from EasyRecipe card."""
        return self._extract_time_from_card(['total'])

    def extract_category(self) -> Optional[str]:
        """
        Extract category from BreadcrumbList JSON-LD (position 2 item)
        or from the article element's category-* CSS classes.
        """
        try:
            bc = self._get_breadcrumb_jsonld()
            if bc:
                items = bc.get('itemListElement', [])
                # Collect names of intermediate breadcrumb items (skip root and last)
                names = [
                    it['item']['name']
                    for it in items
                    if isinstance(it.get('item'), dict) and 'name' in it['item']
                ]
                if len(names) >= 2:
                    return self.clean_text(names[1])

            # Fallback: article category-* classes
            article = self.soup.find('article')
            if article:
                skip_generic = {'retete', 'mancare', 'retete-rapide', 'retete-simple'}
                cats = [
                    c[9:] for c in article.get('class', [])
                    if c.startswith('category-') and c[9:] not in skip_generic
                ]
                if cats:
                    return cats[0].replace('-', ' ').title()
        except Exception as exc:
            logger.warning("Error extracting category: %s", exc)
        return None

    def extract_notes(self) -> Optional[str]:
        """
        Extract notes / tips from the article body.

        Looks for a heading that contains keywords like "sfaturi", "truc",
        or "posibile defectiuni" and collects the list items (or paragraphs)
        that immediately follow.
        """
        try:
            entry_content = self._get_entry_content()
            if not entry_content:
                return None

            elements = list(entry_content.children)

            notes_start = -1
            for i, elem in enumerate(elements):
                if getattr(elem, 'name', None) not in ('h2', 'h3', 'h4'):
                    continue
                if self._is_notes_heading(elem.get_text(strip=True)):
                    notes_start = i
                    break

            if notes_start == -1:
                return None

            note_texts: list = []
            for elem in elements[notes_start + 1:]:
                if getattr(elem, 'name', None) is None:
                    continue

                if elem.name in ('h2', 'h3', 'h4'):
                    if note_texts:
                        break  # Stop at the next heading once we have content
                    continue  # Skip headings before the first content

                if elem.name == 'ul':
                    for li in elem.find_all('li'):
                        text = self.clean_text(li.get_text())
                        if text:
                            note_texts.append(text)
                    if note_texts:
                        break  # One list is enough

                elif elem.name == 'p':
                    text = self.clean_text(elem.get_text())
                    if text:
                        note_texts.append(text)

            return ' '.join(note_texts) if note_texts else None
        except Exception as exc:
            logger.warning("Error extracting notes: %s", exc)
        return None

    def extract_tags(self) -> Optional[str]:
        """
        Extract tags from JSON-LD Recipe keywords or article tag-* CSS classes.
        """
        try:
            recipe_ld = self._get_recipe_jsonld()
            if recipe_ld and recipe_ld.get('keywords'):
                raw = recipe_ld['keywords']
                tags = [t.strip() for t in raw.split(',') if t.strip()]
                if tags:
                    return ', '.join(tags)

            article = self.soup.find('article')
            if article:
                tags = [
                    c[4:].replace('-', ' ')
                    for c in article.get('class', [])
                    if c.startswith('tag-')
                ]
                if tags:
                    return ', '.join(tags)
        except Exception as exc:
            logger.warning("Error extracting tags: %s", exc)
        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Extract image URLs from JSON-LD Recipe image, og:image meta tag,
        and the EasyRecipe card thumbnail.
        """
        try:
            urls: list = []

            recipe_ld = self._get_recipe_jsonld()
            if recipe_ld and recipe_ld.get('image'):
                img = recipe_ld['image']
                if isinstance(img, str):
                    urls.append(img)
                elif isinstance(img, dict):
                    url = img.get('url') or img.get('contentUrl', '')
                    if url:
                        urls.append(url)
                elif isinstance(img, list):
                    for item in img:
                        if isinstance(item, str):
                            urls.append(item)
                        elif isinstance(item, dict):
                            url = item.get('url') or item.get('contentUrl', '')
                            if url:
                                urls.append(url)

            og_img = self.soup.find('meta', property='og:image')
            if og_img and og_img.get('content'):
                urls.append(og_img['content'])

            card = self._get_recipe_card()
            if card:
                top_right = card.find(class_='ERSTopRight')
                if top_right:
                    img_tag = top_right.find('img')
                    if img_tag:
                        src = img_tag.get('data-src') or img_tag.get('src', '')
                        if src and not src.startswith('data:'):
                            urls.append(src)

            # Deduplicate while preserving insertion order
            seen: set = set()
            unique: list = []
            for url in urls:
                url = url.strip()
                if url and url not in seen:
                    seen.add(url)
                    unique.append(url)

            return ','.join(unique) if unique else None
        except Exception as exc:
            logger.warning("Error extracting image_urls: %s", exc)
        return None

    # ------------------------------------------------------------------ #
    # Main extraction entry point                                         #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """Extract all recipe data and return a JSON-compatible dict."""
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
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls(),
        }


def main():
    """Entry point: process all HTML files in preprocessed/pofta-buna_com."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "pofta-buna_com")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(PoftaBunaComExtractor, preprocessed_dir)
        return

    print(f"Directory not found: {preprocessed_dir}")
    print("Usage: python pofta-buna_com.py")


if __name__ == "__main__":
    main()
