"""
Recipe data extractor for bucataria-cu-gust.ro
"""

import copy
import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


# Romanian units mapping: normalized form → canonical abbreviation
_ROMANIAN_UNITS = [
    r'lingurițe', r'linguriță', r'linguri', r'lingură',
    r'pachet(?:e)?', r'bucăți', r'bucată', r'buc',
    r'tijă', r'tije', r'căpățână', r'capete', r'cap',
    r'legătură', r'legaturi', r'boabe', r'felii', r'felie',
    r'ml', r'kg', r'dl', r'cl', r'l\b', r'g\b',
]
_UNIT_RE = re.compile(
    r'^(?P<amount>(?:aprox\.?\s+)?[\d,.\-]+(?:\s*/\s*[\d,.\-]+)?)\s*'
    r'(?P<unit>' + '|'.join(_ROMANIAN_UNITS) + r')\.?\s+'
    r'(?P<name>.+)$',
    re.IGNORECASE | re.UNICODE,
)
# Pattern for "AMOUNT UNIT NAME" with a space between amount and unit
_UNIT_SPACE_RE = re.compile(
    r'^(?P<amount>(?:aprox\.?\s+)?[\d,.\-]+(?:\s*/\s*[\d,.\-]+)?)\s+'
    r'(?P<unit>' + '|'.join(_ROMANIAN_UNITS) + r')\.?\s+'
    r'(?P<name>.+)$',
    re.IGNORECASE | re.UNICODE,
)
# Pattern for amount-only (no unit): "2 Morcovi" or "1 Ceapă"
_AMOUNT_ONLY_RE = re.compile(
    r'^(?P<amount>[\d,.\-]+(?:\s*/\s*[\d,.\-]+)?)\s+'
    r'(?P<name>[^\d].*)$',
    re.UNICODE,
)


class BucatariaCuGustRoExtractor(BaseRecipeExtractor):
    """Extractor for bucataria-cu-gust.ro"""

    # ------------------------------------------------------------------ #
    # ISO 8601 duration helper                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """Convert ISO 8601 duration string (e.g. 'PT40M') to 'N minutes'."""
        if not duration or not duration.startswith('PT'):
            return None
        duration = duration[2:]
        hours, minutes = 0, 0
        h_match = re.search(r'(\d+)H', duration)
        m_match = re.search(r'(\d+)M', duration)
        if h_match:
            hours = int(h_match.group(1))
        if m_match:
            minutes = int(m_match.group(1))
        total = hours * 60 + minutes
        return f"{total} minutes" if total > 0 else None

    # ------------------------------------------------------------------ #
    # Ingredient parsing helpers                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_ingredient_text(text: str) -> Optional[dict]:
        """
        Parse a Romanian ingredient string into {name, amount, unit}.

        Handles formats:
          - "300-400g Afumătură ..."  → amount=300-400, unit=g
          - "2-3 linguri Ulei"         → amount=2-3, unit=linguri
          - "1 kg Cartofi ..."         → amount=1, unit=kg
          - "aprox 100g Făină"         → amount=100, unit=g
          - "2 Morcovi mari"           → amount=2, unit=None
          - "Sare"                     → amount=None, unit=None
        """
        if not text:
            return None

        text = text.strip()

        # Try "AMOUNT[UNIT]NAME" (no space between amount and unit)
        m = _UNIT_RE.match(text)
        if m:
            amount_raw = re.sub(r'(?i)aprox\.?\s*', '', m.group('amount')).strip()
            return {
                "name": m.group('name').strip(),
                "amount": amount_raw,
                "unit": m.group('unit').strip(),
            }

        # Try "AMOUNT UNIT NAME" (space between amount and unit)
        m = _UNIT_SPACE_RE.match(text)
        if m:
            amount_raw = re.sub(r'(?i)aprox\.?\s*', '', m.group('amount')).strip()
            return {
                "name": m.group('name').strip(),
                "amount": amount_raw,
                "unit": m.group('unit').strip(),
            }

        # Try "AMOUNT NAME" (no unit)
        m = _AMOUNT_ONLY_RE.match(text)
        if m:
            return {
                "name": m.group('name').strip(),
                "amount": m.group('amount').strip(),
                "unit": None,
            }

        # No amount/unit detectable
        return {
            "name": text,
            "amount": None,
            "unit": None,
        }

    # ------------------------------------------------------------------ #
    # JSON-LD helpers                                                     #
    # ------------------------------------------------------------------ #

    def _get_recipe_jsonld(self) -> Optional[dict]:
        """Return the first JSON-LD object with @type == 'Recipe', or None."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
            except (json.JSONDecodeError, TypeError):
                continue

            if isinstance(data, dict):
                if data.get('@type') == 'Recipe':
                    return data
                for item in data.get('@graph', []):
                    if isinstance(item, dict) and item.get('@type') == 'Recipe':
                        return item
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get('@type') == 'Recipe':
                        return item
        return None

    def _get_blogposting_jsonld(self) -> Optional[dict]:
        """Return the first JSON-LD BlogPosting object, or None."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
            except (json.JSONDecodeError, TypeError):
                continue

            if isinstance(data, dict):
                if data.get('@type') == 'BlogPosting':
                    return data
                for item in data.get('@graph', []):
                    if isinstance(item, dict) and item.get('@type') == 'BlogPosting':
                        return item
        return None

    # ------------------------------------------------------------------ #
    # Field extractors                                                    #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Extract recipe title, preferring the concise h2.bg-recipe-title."""
        try:
            # Primary: h2.bg-recipe-title — cleaner version without SEO suffixes
            h2 = self.soup.find('h2', class_='bg-recipe-title')
            if h2:
                return self.clean_text(h2.get_text())

            # Fallback: h1 (full page title)
            h1 = self.soup.find('h1')
            if h1:
                return self.clean_text(h1.get_text())

            # Last resort: og:title stripped of site suffix
            og_title = self.soup.find('meta', property='og:title')
            if og_title and og_title.get('content'):
                title = og_title['content']
                title = re.sub(r'\s*[-–|]\s*Buc[ăa]t[ăa]ria cu Gust.*$', '', title, flags=re.I)
                return self.clean_text(title)
        except Exception as e:
            logger.warning(f"Error extracting dish_name: {e}")
        return None

    def extract_description(self) -> Optional[str]:
        """Extract recipe description from bg-desc paragraph or meta description."""
        try:
            # Primary: p.bg-desc inside the recipe card
            bg_desc = self.soup.find('p', class_='bg-desc')
            if bg_desc:
                return self.clean_text(bg_desc.get_text())

            # Fallback: meta description
            meta_desc = self.soup.find('meta', attrs={'name': 'description'})
            if meta_desc and meta_desc.get('content'):
                return self.clean_text(meta_desc['content'])

            # Fallback: og:description
            og_desc = self.soup.find('meta', property='og:description')
            if og_desc and og_desc.get('content'):
                return self.clean_text(og_desc['content'])
        except Exception as e:
            logger.warning(f"Error extracting description: {e}")
        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Extract ingredients from ul.ingredients-list.

        Each li is parsed as 'amount unit name'.
        Section-header li elements (containing only a <strong> child) are skipped.
        Items combined with ' + ' are split into individual ingredients.
        """
        try:
            ingr_ul = self.soup.find('ul', class_='ingredients-list')
            if not ingr_ul:
                logger.warning("ingredients-list not found")
                return None

            ingredients = []
            for li in ingr_ul.find_all('li'):
                # Skip section headers: li whose only non-empty child is a <strong>
                children = [c for c in li.children if str(c).strip()]
                if (
                    len(children) == 1
                    and hasattr(children[0], 'name')
                    and children[0].name == 'strong'
                ):
                    continue

                # Remove <strong> section-label children before extracting text
                text = li.get_text(' ', strip=True)
                # Remove content from strong sub-headers (e.g. "Tăiței: ")
                for strong in li.find_all('strong'):
                    label = strong.get_text().strip()
                    if label.endswith(':'):
                        text = text.replace(label, '').strip()

                text = self.clean_text(text)
                if not text:
                    continue

                # Split items combined with ' + ' (e.g. "1 Morcov + 1 Păstârnac")
                parts = re.split(r'\s*\+\s*', text)
                for part in parts:
                    part = part.strip()
                    if part:
                        parsed = self._parse_ingredient_text(part)
                        if parsed:
                            ingredients.append(parsed)

            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
        except Exception as e:
            logger.warning(f"Error extracting ingredients: {e}")
        return None

    def extract_instructions(self) -> Optional[str]:
        """
        Extract cooking instructions from ol.instructions-list.

        Each li contains a <strong> section title and the step body text.
        Returns all step texts joined with a space, without the section titles.
        """
        try:
            inst_ol = self.soup.find('ol', class_='instructions-list')
            if not inst_ol:
                logger.warning("instructions-list not found")
                return None

            steps = []
            for li in inst_ol.find_all('li'):
                # Remove the <strong> title node so we get only the body text
                clone = copy.copy(li)
                for strong in clone.find_all('strong'):
                    strong.decompose()
                step_text = self.clean_text(clone.get_text(' ', strip=True))
                if step_text:
                    steps.append(step_text)

            return ' '.join(steps) if steps else None
        except Exception as e:
            logger.warning(f"Error extracting instructions: {e}")
        return None

    def extract_category(self) -> Optional[str]:
        """
        Extract category from breadcrumbs (div.bg-breadcrumbs) or
        JSON-LD articleSection / recipeCategory.
        """
        try:
            # Primary: breadcrumb div
            breadcrumb = self.soup.find(class_='bg-breadcrumbs')
            if breadcrumb:
                text = breadcrumb.get_text(separator='›', strip=True)
                parts = [p.strip() for p in text.split('›') if p.strip()]
                # Parts: ['Acasă', 'Category', 'Recipe name']
                # Return the middle part(s), skip 'Acasă' and last item (current page)
                if len(parts) >= 3:
                    return self.clean_text(parts[1])
                if len(parts) == 2:
                    return self.clean_text(parts[0])

            # Fallback 1: JSON-LD Recipe.recipeCategory
            recipe_ld = self._get_recipe_jsonld()
            if recipe_ld and recipe_ld.get('recipeCategory'):
                return self.clean_text(recipe_ld['recipeCategory'])

            # Fallback 2: JSON-LD BlogPosting.articleSection
            blog_ld = self._get_blogposting_jsonld()
            if blog_ld and blog_ld.get('articleSection'):
                section = blog_ld['articleSection']
                # May be "Feluri Principale, Paste" — return first token
                return self.clean_text(section.split(',')[0].strip())
        except Exception as e:
            logger.warning(f"Error extracting category: {e}")
        return None

    def _extract_meta_time(self, label_ro: str) -> Optional[str]:
        """
        Extract a time value from div.bg-recipe-meta by Romanian label.

        Args:
            label_ro: Romanian label text, e.g. 'Pregătire' or 'Gătire'

        Returns:
            Time string like '40 minutes', or None.
        """
        meta_div = self.soup.find(class_='bg-recipe-meta')
        if not meta_div:
            return None
        for item in meta_div.find_all('div', class_='meta-item'):
            strong = item.find('strong')
            # Get only the text outside the <strong> tag (the label)
            if strong:
                label_text = item.get_text(' ', strip=True).replace(
                    strong.get_text(' ', strip=True), '', 1
                ).strip()
            else:
                label_text = item.get_text(' ', strip=True)
            if label_ro.lower() == label_text.lower():
                if strong:
                    value = self.clean_text(strong.get_text())
                    # Normalize "40 min" → "40 minutes"
                    value = re.sub(r'\bmin\b', 'minutes', value, flags=re.I)
                    return value
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Extract preparation time."""
        try:
            # Primary: HTML meta section
            t = self._extract_meta_time('Pregătire')
            if t:
                return t

            # Fallback: JSON-LD prepTime
            recipe_ld = self._get_recipe_jsonld()
            if recipe_ld and recipe_ld.get('prepTime'):
                return self._parse_iso_duration(recipe_ld['prepTime'])
        except Exception as e:
            logger.warning(f"Error extracting prep_time: {e}")
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Extract cooking time."""
        try:
            t = self._extract_meta_time('Gătire')
            if t:
                return t

            recipe_ld = self._get_recipe_jsonld()
            if recipe_ld and recipe_ld.get('cookTime'):
                return self._parse_iso_duration(recipe_ld['cookTime'])
        except Exception as e:
            logger.warning(f"Error extracting cook_time: {e}")
        return None

    def extract_total_time(self) -> Optional[str]:
        """Extract total time."""
        try:
            t = self._extract_meta_time('Total')
            if t:
                return t

            recipe_ld = self._get_recipe_jsonld()
            if recipe_ld and recipe_ld.get('totalTime'):
                return self._parse_iso_duration(recipe_ld['totalTime'])
        except Exception as e:
            logger.warning(f"Error extracting total_time: {e}")
        return None

    def extract_notes(self) -> Optional[str]:
        """
        Extract tips/notes from the recipe outro section.

        Handles two HTML variants observed on the site:
          - ``aside.bg-outro-box``  (with h3.bg-tips-title headers)
          - ``div.bg-outro-container`` (with h3.bg-outro-h3 headers)

        Concatenates all <p> paragraphs, excluding CTA divs / paragraphs.
        Also strips markdown bold markers (**text**).
        """
        try:
            outro = (
                self.soup.find('aside', class_='bg-outro-box')
                or self.soup.find(class_='bg-outro-container')
            )
            if not outro:
                return None

            parts = []
            for p in outro.find_all('p'):
                text = self.clean_text(p.get_text())
                if not text:
                    continue
                # Skip CTA paragraph
                if re.search(r'ți-a plăcut|comentariu|lasă-ne|poftă bună|instagram|facebook', text, re.I):
                    continue
                # Strip markdown bold markers
                text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
                parts.append(text)

            return ' '.join(parts) if parts else None
        except Exception as e:
            logger.warning(f"Error extracting notes: {e}")
        return None

    def extract_tags(self) -> Optional[str]:
        """
        Extract tags from JSON-LD keywords or articleSection.

        Returns a comma-separated string or None if no tags found.
        HTML entities in the source values are decoded automatically.
        """
        try:
            # Primary: JSON-LD Recipe.keywords
            recipe_ld = self._get_recipe_jsonld()
            if recipe_ld and recipe_ld.get('keywords'):
                return self.clean_text(recipe_ld['keywords'])

            # Fallback: JSON-LD BlogPosting.articleSection as tags
            blog_ld = self._get_blogposting_jsonld()
            if blog_ld and blog_ld.get('articleSection'):
                section = self.clean_text(blog_ld['articleSection'])
                tags = [t.strip() for t in section.split(',') if t.strip()]
                return ', '.join(tags) if tags else None
        except Exception as e:
            logger.warning(f"Error extracting tags: {e}")
        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Extract recipe image URLs.

        Priority: og:image → wp-post-image (img with that class).
        Returns a comma-separated string of unique URLs.
        """
        try:
            urls = []

            # 1. og:image
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])

            # 2. img.wp-post-image (featured image)
            for img in self.soup.find_all('img', class_=re.compile(r'wp-post-image')):
                src = img.get('src', '')
                if src and not src.endswith(('.png', '.ico', '.svg')):
                    urls.append(src)

            # Deduplicate preserving order
            seen: set = set()
            unique: list = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique.append(url)

            return ','.join(unique) if unique else None
        except Exception as e:
            logger.warning(f"Error extracting image_urls: {e}")
        return None

    # ------------------------------------------------------------------ #
    # Main entry point                                                    #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """Extract all recipe data and return as a dict."""
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
            "tags": self.extract_tags(),
        }


def main():
    preprocessed_dir = Path(__file__).parent.parent / "preprocessed" / "bucataria-cu-gust_ro"
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        process_directory(BucatariaCuGustRoExtractor, str(preprocessed_dir))
        return
    print(f"Directory not found: {preprocessed_dir}")


if __name__ == "__main__":
    main()
