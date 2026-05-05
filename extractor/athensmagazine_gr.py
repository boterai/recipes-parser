"""
Экстрактор данных рецептов для сайта athensmagazine.gr
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class AthensmagazineGrExtractor(BaseRecipeExtractor):
    """Экстрактор для athensmagazine.gr"""

    # Keywords that identify ingredient section headers (lowercase, with/without accents)
    INGREDIENT_KEYWORDS = ['υλικά', 'υλικα', 'συστατικά', 'συστατικα']

    # Keywords that identify instruction section headers (lowercase, with/without accents)
    INSTRUCTION_KEYWORDS = [
        'εκτέλεση', 'εκτελεση', 'διαδικασία', 'διαδικασια',
        'οδηγίες', 'οδηγιες', 'παρασκευή', 'παρασκευη',
        'μέθοδος', 'μεθοδος', 'βήματα', 'βηματα',
    ]

    # Greek measurement units — multi-word entries first, then single-word
    GREEK_UNITS = [
        r'κουταλάκι\s+του\s+γλυκού',
        r'κουτ\.\s+σούπας',
        r'κουτ\.',
        r'κ\.σ\.',
        r'κ\.γ\.',
        r'φλ\.',
        r'γραμμάρια',
        r'γραμμ\.',
        r'γραμ\.',
        r'γρ\.',
        r'γρ',
        r'κιλά',
        r'κιλό',
        r'κιλ\.',
        r'λίτρα',
        r'λίτρο',
        r'λίτρ\.',
        r'ml',
        r'l',
        r'kg',
        r'mg',
        r'g',
        r'φλιτζάνια',
        r'φλιτζάνι',
        r'κούπες',
        r'κούπα',
        r'κουταλιές',
        r'κουταλιά',
        r'κουταλάκια',
        r'κουταλάκι',
        r'φύλλα',
        r'φύλλο',
        r'κομμάτια',
        r'κομμάτι',
        r'τεμάχια',
        r'τεμάχιο',
        r'πρέζες',
        r'πρέζα',
        r'πακέτα',
        r'πακέτο',
        r'ποτήρια',
        r'ποτήρι',
        r'μεγάλες',
        r'μεγάλα',
        r'μεγάλο',
        r'μεγάλης',
        r'εκ\.',
        r'cm',
    ]

    # ---------------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------------

    def _get_article_para(self):
        """Return the main ``div.paragraph`` inside the article element."""
        article = self.soup.find('article')
        if not article:
            return None
        return article.find('div', class_='paragraph')

    def _is_ingredient_header(self, element) -> bool:
        """Return True if *element* is any form of ingredient-section header."""
        if not hasattr(element, 'name') or element.name != 'p':
            return False
        text = element.get_text(strip=True).lower()
        return any(
            text == kw
            or text == kw + ':'
            or text.startswith(kw + ' ')
            or text.startswith(kw + ':')
            for kw in self.INGREDIENT_KEYWORDS
        )

    def _is_clean_ingredient_header(self, element) -> bool:
        """Return True if *element* is **only** an ingredient keyword (no prose)."""
        if not hasattr(element, 'name') or element.name != 'p':
            return False
        text = element.get_text(strip=True).lower()
        return any(text == kw or text == kw + ':' for kw in self.INGREDIENT_KEYWORDS)

    def _is_instruction_header(self, element) -> bool:
        """Return True if *element* is any form of instruction-section header."""
        if not hasattr(element, 'name') or element.name != 'p':
            return False
        text = element.get_text(strip=True).lower()
        return any(
            text == kw
            or text == kw + ':'
            or text.startswith(kw + ' ')
            or text.startswith(kw + ':')
            for kw in self.INSTRUCTION_KEYWORDS
        )

    def _is_noise_paragraph(self, text: str) -> bool:
        """Return True if *text* is navigational/promo noise, not recipe content."""
        text_lower = text.lower()
        noise_patterns = [
            r'^δείτε\s+',
            r'^να\s+σας\s+θυμίσουμε',
            r'^περισσότερα:',
            r'^διαβάστε\s+επίσης',
            r'^related\s+',
        ]
        return any(re.match(p, text_lower) for p in noise_patterns)

    def _extract_lines_from_element(self, element) -> List[str]:
        """
        Extract individual text lines from a ``<p>`` (splitting on ``<br/>``)
        or all ``<li>`` items from a ``<ul>``, without modifying the BeautifulSoup
        tree.
        """
        lines: List[str] = []
        if element.name == 'ul':
            for li in element.find_all('li'):
                text = self.clean_text(li.get_text())
                if text:
                    lines.append(text)
        elif element.name == 'p':
            # Split the raw HTML on <br> tags to preserve line boundaries
            html_str = str(element)
            parts = re.split(r'<br\s*/?>', html_str, flags=re.IGNORECASE)
            for part in parts:
                # Strip remaining HTML tags
                clean = re.sub(r'<[^>]+>', '', part)
                text = self.clean_text(clean)
                if text:
                    lines.append(text)
        return lines

    # ---------------------------------------------------------------------------
    # Ingredient line parser
    # ---------------------------------------------------------------------------

    def parse_ingredient_line(self, line: str) -> Optional[Dict[str, Any]]:
        """
        Parse a single ingredient text line into ``{name, amount, unit}``.

        Handles Greek measurement units, Unicode fractions, mixed numbers and
        the no-space "50γρ." format.

        Args:
            line: Raw ingredient string, e.g. "170 γραμμ. ανάλατο βούτυρο"

        Returns:
            dict with keys ``name``, ``amount``, ``unit``, or ``None`` if line
            is empty.
        """
        text = self.clean_text(line)
        if not text or len(text) < 2:
            return None

        # Replace Unicode fractions with ASCII equivalents
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
        }
        for frac, val in fraction_map.items():
            text = text.replace(frac, val)

        units_pattern = '|'.join(self.GREEK_UNITS)

        # Numeric amount: integer, decimal, fraction, mixed, or N+N
        amount_pattern = (
            r'(\d+(?:[.,]\d+)?'         # integer or decimal
            r'(?:\s*/\s*\d+)?'          # optional /M
            r'(?:\s*\+\s*\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?)?'  # optional +N or +N/M
            r'(?:\s+\d+/\d+)?)'         # mixed "N N/M"
        )

        # Pattern 1: amount glued to unit — e.g. "50γρ. φέτα"
        nospace_pat = (
            r'^(\d+(?:[.,]\d+)?)\s*(' + units_pattern + r')\s+(.+)$'
        )
        m = re.match(nospace_pat, text, re.IGNORECASE)
        if m:
            amount_str, unit, name = m.groups()
            return {
                'name': self.clean_text(name),
                'amount': amount_str.strip(),
                'unit': unit.strip(),
            }

        # Pattern 2: amount + space + unit + space + name
        with_unit_pat = (
            r'^' + amount_pattern + r'\s+(' + units_pattern + r')\s+(.+)$'
        )
        m = re.match(with_unit_pat, text, re.IGNORECASE)
        if m:
            amount_str, unit, name = m.groups()
            return {
                'name': self.clean_text(name),
                'amount': amount_str.strip(),
                'unit': unit.strip(),
            }

        # Pattern 3: amount + name, no recognised unit
        amount_only_pat = r'^' + amount_pattern + r'\s+(.+)$'
        m = re.match(amount_only_pat, text)
        if m:
            amount_str, name = m.groups()
            return {
                'name': self.clean_text(name),
                'amount': amount_str.strip(),
                'unit': None,
            }

        # No numeric amount — plain name
        return {'name': text, 'amount': None, 'unit': None}

    # ---------------------------------------------------------------------------
    # Field extractors
    # ---------------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Extract the recipe title from the ``<h1>`` heading."""
        try:
            article = self.soup.find('article')
            if article:
                h1 = article.find('h1', class_='single_article__title')
                if h1:
                    return self.clean_text(h1.get_text())
            # Fallback: any h1
            h1 = self.soup.find('h1')
            if h1:
                return self.clean_text(h1.get_text())
            # Fallback: og:title
            og_title = self.soup.find('meta', property='og:title')
            if og_title and og_title.get('content'):
                title = og_title['content']
                title = re.sub(r'\s*\|\s*Athens Magazine.*$', '', title, flags=re.IGNORECASE)
                return self.clean_text(title)
        except Exception as e:
            logger.warning('Error extracting dish_name: %s', e)
        return None

    def extract_description(self) -> Optional[str]:
        """
        Extract the recipe description.

        Primary source: ``<meta name="description">``.
        Fallback: first meaningful paragraph in the article body.
        """
        try:
            meta_desc = self.soup.find('meta', {'name': 'description'})
            if meta_desc and meta_desc.get('content'):
                return self.clean_text(meta_desc['content'])
            # Fallback: first non-header paragraph
            para_div = self._get_article_para()
            if para_div:
                for child in para_div.children:
                    if not hasattr(child, 'name') or child.name != 'p':
                        continue
                    if self._is_ingredient_header(child) or self._is_instruction_header(child):
                        continue
                    text = self.clean_text(child.get_text())
                    if text and len(text) > 20:
                        return text
        except Exception as e:
            logger.warning('Error extracting description: %s', e)
        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Extract the ingredient list from the article body.

        Looks for the first *clean* ingredient section header
        (a ``<p>`` whose text is exactly one of the ingredient keywords) then
        collects ``<ul>`` items or ``<p>`` elements whose ``<br/>``-separated
        lines are individual ingredients.

        Returns:
            JSON-encoded list of ``{name, amount, unit}`` dicts, or ``None``.
        """
        try:
            para_div = self._get_article_para()
            if not para_div:
                return None

            children = list(para_div.children)

            # Locate ingredient-section headers
            ingr_indices = [
                i for i, c in enumerate(children)
                if self._is_ingredient_header(c)
            ]
            if not ingr_indices:
                return None

            # Prefer the first "clean" header (keyword alone); fall back to
            # the first header overall
            clean_indices = [
                i for i in ingr_indices
                if self._is_clean_ingredient_header(children[i])
            ]
            start_idx = (clean_indices[0] if clean_indices else ingr_indices[0]) + 1

            ingredients: List[Dict[str, Any]] = []

            for j in range(start_idx, len(children)):
                child = children[j]
                if not hasattr(child, 'name'):
                    continue

                # Stop at the instruction header or a new major heading
                if self._is_instruction_header(child):
                    break
                if child.name in ('h2', 'h3'):
                    break

                # Only collect from <ul> or <p> with explicit <br/> separators
                if child.name not in ('ul', 'p'):
                    continue

                has_br = bool(child.find('br')) if child.name == 'p' else False
                is_ul = child.name == 'ul'
                if not (is_ul or has_br):
                    continue

                for line in self._extract_lines_from_element(child):
                    # Stop if we hit an instruction keyword within the element
                    line_lower = line.lower()
                    if any(
                        line_lower == kw or line_lower.startswith(kw + ':')
                        for kw in self.INSTRUCTION_KEYWORDS
                    ):
                        break
                    parsed = self.parse_ingredient_line(line)
                    if parsed:
                        ingredients.append(parsed)

            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
        except Exception as e:
            logger.warning('Error extracting ingredients: %s', e)
        return None

    def extract_instructions(self) -> Optional[str]:
        """
        Extract the cooking instructions from the article body.

        Finds the instruction-section header that follows the ingredient section,
        then collects all ``<p>`` paragraphs (skipping ad ``<div>`` blocks and
        obvious noise) until the next ``<h2>``/``<h3>`` heading.

        Returns:
            All instruction text joined with spaces, or ``None``.
        """
        try:
            para_div = self._get_article_para()
            if not para_div:
                return None

            children = list(para_div.children)

            # Determine the reference ingredient-section index
            ingr_indices = [
                i for i, c in enumerate(children)
                if self._is_ingredient_header(c)
            ]
            clean_ingr = [
                i for i in ingr_indices
                if self._is_clean_ingredient_header(children[i])
            ]
            last_ingr_idx = (clean_ingr[0] if clean_ingr
                             else (ingr_indices[0] if ingr_indices else 0))

            # Find all instruction-section headers
            instr_indices = [
                i for i, c in enumerate(children)
                if self._is_instruction_header(c)
            ]
            if not instr_indices:
                return None

            # Prefer the first instruction header that comes after the
            # ingredient header
            relevant = [i for i in instr_indices if i > last_ingr_idx]
            start_idx = (relevant[0] if relevant else instr_indices[0]) + 1

            instruction_parts: List[str] = []

            for j in range(start_idx, len(children)):
                child = children[j]
                if not hasattr(child, 'name'):
                    continue

                # Stop at the next major heading (indicates a different recipe)
                if child.name in ('h2', 'h3'):
                    break

                # Skip ad / viral-content divs
                if child.name == 'div':
                    continue

                if child.name == 'p':
                    text = self.clean_text(child.get_text(separator=' '))
                    if not text or len(text) < 10:
                        continue
                    if self._is_noise_paragraph(text):
                        continue
                    instruction_parts.append(text)

            return ' '.join(instruction_parts) if instruction_parts else None
        except Exception as e:
            logger.warning('Error extracting instructions: %s', e)
        return None

    def extract_category(self) -> Optional[str]:
        """Extract the most specific breadcrumb category."""
        try:
            article = self.soup.find('article')
            if not article:
                return None
            breadcrumb = article.find('div', class_='single_article__breadcrumb')
            if not breadcrumb:
                return None
            links = breadcrumb.find_all('a')
            if links:
                return self.clean_text(links[-1].get_text())
        except Exception as e:
            logger.warning('Error extracting category: %s', e)
        return None

    def extract_tags(self) -> Optional[str]:
        """Extract article tags from the footer tag container."""
        try:
            article = self.soup.find('article')
            if not article:
                return None
            footer = article.find('footer')
            if not footer:
                return None
            tags_div = footer.find('div', class_='article__tags_container')
            if not tags_div:
                return None
            tags: List[str] = []
            for a in tags_div.find_all('a'):
                tag = self.clean_text(a.get_text()).strip()
                if tag and tag.lower() not in ('tags:', 'tags', ''):
                    tags.append(tag.lower())
            return ', '.join(tags) if tags else None
        except Exception as e:
            logger.warning('Error extracting tags: %s', e)
        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Collect image URLs for the article.

        Sources (in priority order):
        1. Main article image from ``<header><figure><img>``.
        2. ``<meta property="og:image">``.

        Returns:
            Comma-separated URL string, or ``None``.
        """
        try:
            urls: List[str] = []
            article = self.soup.find('article')
            if article:
                header = article.find('header')
                if header:
                    figure = header.find('figure')
                    if figure:
                        img = figure.find('img')
                        if img:
                            src = img.get('src') or img.get('data-src', '')
                            if src and src not in urls:
                                urls.append(src)
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                url = og_image['content']
                if url and url not in urls:
                    urls.append(url)
            return ','.join(urls) if urls else None
        except Exception as e:
            logger.warning('Error extracting image_urls: %s', e)
        return None

    # ---------------------------------------------------------------------------
    # Main extraction entry point
    # ---------------------------------------------------------------------------

    def extract_all(self) -> dict:
        """
        Extract all recipe fields from the HTML page.

        Returns:
            dict with keys: ``dish_name``, ``description``, ``ingredients``,
            ``instructions``, ``category``, ``prep_time``, ``cook_time``,
            ``total_time``, ``notes``, ``image_urls``, ``tags``.
        """
        return {
            'dish_name': self.extract_dish_name(),
            'description': self.extract_description(),
            'ingredients': self.extract_ingredients(),
            'instructions': self.extract_instructions(),
            'category': self.extract_category(),
            'prep_time': None,
            'cook_time': None,
            'total_time': None,
            'notes': None,
            'image_urls': self.extract_image_urls(),
            'tags': self.extract_tags(),
        }


def main() -> None:
    """
    Entry point: process all HTML files in ``preprocessed/athensmagazine_gr``.
    """
    import os

    preprocessed_dir = os.path.join('preprocessed', 'athensmagazine_gr')
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(AthensmagazineGrExtractor, preprocessed_dir)
        return

    print(f'Директория не найдена: {preprocessed_dir}')
    print('Использование: python athensmagazine_gr.py')


if __name__ == '__main__':
    main()
