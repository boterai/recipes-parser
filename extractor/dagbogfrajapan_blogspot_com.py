"""
Экстрактор данных рецептов для сайта dagbogfrajapan.blogspot.com

Датский Blogger-блог о жизни в Японии с рецептами японской и другой кухни.
Страницы бывают двух типов:
 - Структурированные: заголовки h2/h3 «Opskriften på…» (ингредиенты)
   и «Fremgangsmåde.»/«Fremgangsmetode.» (инструкции).
 - Плоские: всё содержимое — единый текстовый блок, разделённый <br>.
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Headings that mark the start of the ingredients list
_INGREDIENT_HEADING_RE = re.compile(r'opskrift', re.IGNORECASE)

# Headings that mark the start of the instructions
_INSTRUCTION_HEADING_RE = re.compile(r'fremgang', re.IGNORECASE)

# Danish time pattern: "i ca 15 minutter", "i cirka 30 min.", "15 minutter", etc.
_TIME_RE = re.compile(
    r'(?:ca\.?\s*|cirka\s*)?(\d+)\s*(?:minutter?|min\.?)\b',
    re.IGNORECASE,
)

# Danish known measurement units (lower-case)
_DANISH_UNITS = frozenset({
    'g', 'kg', 'ml', 'dl', 'l',
    'tsk', 'spsk',
    'kop', 'kopper',
    'stk',
    'fed',
    'nip', 'knivspids',
    'bundt', 'pose', 'dåse', 'flaske',
    'skive', 'skiver',
    'håndfuld', 'klump',
    'liter',
})

# Preparation-description suffixes to strip from ingredient names
_PREP_SUFFIX_RE = re.compile(
    r'\s+(?:skåret|hakket|finthakket|revet|snittede?|i\s+\w+(?:\s+\w+)?'
    r'|på\s+skrå|i\s+grove\s+stykker|i\s+store\s+stykker|i\s+tern|i\s+stave'
    r'|i\s+stykker|i\s+skiver|i\s+ringe|til\s+garnish)\b.*$',
    re.IGNORECASE,
)

# Unicode fractions → ASCII
_FRACTION_MAP = {
    '½': '1/2', '¼': '1/4', '¾': '3/4',
    '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
    '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
}


class DagbogfrajapanBlogspotComExtractor(BaseRecipeExtractor):
    """Extractor for dagbogfrajapan.blogspot.com (Danish Blogger recipe blog)."""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_entry_content(self):
        """Return the main post-body / entry-content div."""
        el = self.soup.find('div', class_='entry-content')
        if el is None:
            el = self.soup.find('div', class_='post-body')
        return el

    def _find_heading(self, container, pattern: re.Pattern):
        """Find first h2/h3 inside *container* whose text matches *pattern*."""
        for tag_name in ('h2', 'h3'):
            for el in container.find_all(tag_name):
                if pattern.search(el.get_text(strip=True)):
                    return el
        return None

    @staticmethod
    def _clean_line(text: str) -> str:
        """Strip whitespace and HTML-comment artefacts from a single line."""
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
        return re.sub(r'\s+', ' ', text).strip()

    # ------------------------------------------------------------------
    # Ingredient line parser
    # ------------------------------------------------------------------

    def _parse_ingredient_line(self, raw: str) -> Optional[dict]:
        """
        Parse a Danish ingredient line such as
          "500 g velfermanteret kimchi"
          "1 løg i skiver"
          "sesamolie"
          "1/4 kop grøntsagsboullion"
        into {"name": …, "amount": …, "unit": …}.
        """
        # Replace Unicode fractions
        for uf, af in _FRACTION_MAP.items():
            raw = raw.replace(uf, af)

        line = self.clean_text(raw)
        if not line or line.endswith(':') or len(line) < 2:
            return None

        # Unit alternatives with mandatory word-boundary so that "l" does not
        # match the start of "løg", and "g" does not match the start of "gulerod".
        units_alt = r'(?:' + r'|'.join(re.escape(u) for u in sorted(_DANISH_UNITS, key=len, reverse=True)) + r')\b'

        # Try to match: [amount] [unit] name
        m = re.match(
            r'^(\d+(?:\s*/\s*\d+)?(?:\s+\d+(?:\s*/\s*\d+)?)?)\s+'   # amount
            r'(' + units_alt + r')?\s*'                               # optional unit (word-bounded)
            r'(.+)',
            line,
            re.IGNORECASE,
        )

        if not m:
            # No amount detected – whole line is the name
            return {'name': line, 'amount': None, 'unit': None}

        amount_raw, unit, rest = m.group(1), m.group(2), m.group(3)

        amount = amount_raw.strip() if amount_raw else None
        unit = unit.strip() if unit else None
        name = rest.strip() if rest else ''

        # Normalise amount: collapse internal spaces in fractions "1 / 2" → "1/2"
        if amount:
            amount = re.sub(r'\s*/\s*', '/', amount)
            amount = re.sub(r'\s+', ' ', amount).strip()

        # Strip trailing prep-description suffixes from ingredient name
        name = _PREP_SUFFIX_RE.sub('', name).strip()
        # Remove leading conjunctions left over from list parsing
        name = re.sub(r'^(?:og|med)\s+', '', name, flags=re.IGNORECASE).strip()
        # Normalise spaces around parentheses: "foo ( bar )" → "foo (bar)"
        name = re.sub(r'\(\s+', '(', name)
        name = re.sub(r'\s+\)', ')', name)
        name = re.sub(r'\s+', ' ', name).strip()

        if not name or len(name) < 2:
            return None

        return {'name': name, 'amount': amount, 'unit': unit}

    # ------------------------------------------------------------------
    # Public extraction methods
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Extract dish name from h3.post-title.entry-title.

        Strips subtitle clauses after ' - ' (e.g. "Kimchi-jjigae - koreansk kimchi stew…"
        becomes "Kimchi-jjigae") and trailing punctuation.
        """
        title_el = self.soup.find('h3', class_='entry-title')
        if title_el is None:
            title_el = self.soup.find(class_='entry-title')
        if title_el:
            text = self.clean_text(title_el.get_text())
            # Strip subtitle after ' - ' separator
            text = re.sub(r'\s+-\s+.+$', '', text)
            text = text.rstrip('. ')
            return text if text else None

        # Fallback: og:title, strip subtitle after " - "
        og = self.soup.find('meta', property='og:title')
        if og and og.get('content'):
            text = re.sub(r'\s*[-–]\s*.+$', '', og['content'])
            text = text.rstrip('. ')
            return self.clean_text(text) or None

        return None

    def extract_description(self) -> Optional[str]:
        """
        Extract recipe description.
        - Structured pages: first h2 in entry-content (often a one-line summary).
        - Flat pages: first substantial text block from the prose.
        """
        content = self._get_entry_content()
        if content is None:
            return None

        # Structured pages have a prominent h2 as their intro/summary
        h2 = content.find('h2')
        if h2:
            text = self.clean_text(h2.get_text())
            if text and len(text) > 15:
                return text

        # Flat page: walk children collecting text until we hit 2 lines or a recipe-like pattern
        parts: list[str] = []
        for child in content.children:
            if not hasattr(child, 'name') or not child.name:
                # NavigableString
                text = self._clean_line(str(child))
                if text and len(text) > 20:
                    parts.append(text)
            elif child.name == 'a':
                continue
            elif child.name == 'br':
                continue
            elif child.name in ('div', 'p'):
                # Skip completely empty elements (e.g. clear:both divs)
                text = child.get_text(separator=' ', strip=True)
                text = self._clean_line(text)
                if text and len(text) > 20:
                    parts.append(text)
            if len(parts) >= 2:
                break

        return self.clean_text(' '.join(parts)) or None

    def extract_ingredients(self) -> Optional[str]:
        """
        Extract ingredients.
        Structured pages: from divs/p-tags after the 'opskrift' heading.
        Flat pages: regex-based extraction of "amount unit name" patterns.
        """
        content = self._get_entry_content()
        if content is None:
            return None

        # --- Structured: find "Opskrift…" heading ---
        heading = self._find_heading(content, _INGREDIENT_HEADING_RE)
        if heading:
            items = []
            for sibling in heading.next_siblings:
                if not hasattr(sibling, 'name') or not sibling.name:
                    continue
                # Stop at any subsequent heading (instructions or other)
                if sibling.name in ('h2', 'h3', 'h4'):
                    break
                if sibling.name in ('div', 'p'):
                    raw = sibling.get_text(separator=' ', strip=True)
                    raw = self._clean_line(raw)
                    if not raw:
                        continue
                    # Split compound items joined with " og " that have no amount/unit,
                    # e.g. "salt og peber" → [{"name": "salt"}, {"name": "peber"}]
                    parsed = self._parse_ingredient_line(raw)
                    if parsed:
                        if (parsed['amount'] is None and parsed['unit'] is None
                                and ' og ' in parsed['name'].lower()):
                            parts = re.split(r'\s+og\s+', parsed['name'], flags=re.IGNORECASE)
                            for part in parts:
                                part = part.strip()
                                if part and len(part) >= 2:
                                    items.append({'name': part, 'amount': None, 'unit': None})
                        else:
                            items.append(parsed)
            if items:
                return json.dumps(items, ensure_ascii=False)

        # --- Flat page: regex scan for "NUMBER UNIT WORD" patterns ---
        # Word-boundary (\b) after unit prevents matching single-char units
        # inside longer words (e.g. "g" in "gulerod", "l" in "løg").
        logger.info('No structured ingredient section found; attempting regex extraction in %s', self.html_path)
        unit_alt = r'(?:' + r'|'.join(re.escape(u) for u in sorted(_DANISH_UNITS, key=len, reverse=True)) + r')\b'
        # Capture only the first word after the unit to avoid run-on matches.
        flat_re = re.compile(
            r'(?<!\w)(\d+(?:\s*/\s*\d+)?)\s+(' + unit_alt + r')\s+([A-Za-zæøåÆØÅ][A-Za-zæøåÆØÅ-]*)',
            re.IGNORECASE,
        )
        body_text = content.get_text(separator=' ', strip=True)
        items = []
        seen_names: set[str] = set()
        for m in flat_re.finditer(body_text):
            amount, unit, name = m.group(1), m.group(2), m.group(3).strip()
            name_key = name.lower()
            if name_key not in seen_names and len(name) >= 2:
                seen_names.add(name_key)
                items.append({'name': name, 'amount': amount, 'unit': unit})

        # Additional flat-page patterns for ingredients without standard amount+unit format.

        # Pattern: "skal af NUMBER FRUIT_WORDS" → FRUITskal, N, stk
        # Danish idiom for citrus zest: "revne skal af 1 appelsin"
        # Captures multi-word fruit names (e.g., "grøn citron").
        skal_re = re.compile(
            r'\bskal\s+af\s+(\d+)\s+([A-Za-zæøåÆØÅ][A-Za-zæøåÆØÅ\s-]*?)(?=\s+(?:og|med|i|til|,|\.|$))',
            re.IGNORECASE,
        )
        for m in skal_re.finditer(body_text):
            amount = m.group(1)
            fruit = re.sub(r'\s+', ' ', m.group(2)).strip().lower()
            # Strip leading/trailing conjunction leftovers
            fruit = re.sub(r'\s+(?:og|med|i|til)$', '', fruit).strip()
            if not fruit:
                continue
            name = fruit + 'skal'
            name_key = name.lower()
            if name_key not in seen_names:
                seen_names.add(name_key)
                items.append({'name': name, 'amount': amount, 'unit': 'stk'})

        # Pattern: action verb + "med INGREDIENT" for items used without a quantity.
        # e.g. "Pensel med æggehvider", "drys med tesukker", "bland med flydende honning".
        # Captures multi-word ingredient names, stopping at conjunctions / punctuation.
        action_med_re = re.compile(
            r'\b(?:pensel?|drys|strø|dryp|bestøv|overhæld|vend|bland|dæk)\s+med\s+'
            r'([A-Za-zæøåÆØÅ][A-Za-zæøåÆØÅ\s-]*?)(?=\s+og\b|\s*[,.;]|\s*$)',
            re.IGNORECASE,
        )
        for m in action_med_re.finditer(body_text):
            name = re.sub(r'\s+', ' ', m.group(1)).strip()
            name_key = name.lower()
            if name_key not in seen_names and len(name) >= 3:
                seen_names.add(name_key)
                items.append({'name': name, 'amount': None, 'unit': None})

        if items:
            return json.dumps(items, ensure_ascii=False)

        logger.warning('No ingredients found in %s', self.html_path)
        return None

    def extract_instructions(self) -> Optional[str]:
        """
        Extract cooking instructions.
        Structured: text from 'fremgang' section (first p block, before notes).
        Flat: attempt to collect the main prose recipe text.
        """
        content = self._get_entry_content()
        if content is None:
            return None

        heading = self._find_heading(content, _INSTRUCTION_HEADING_RE)
        if heading:
            texts: list[str] = []

            def _collect_from(container):
                """Walk direct children of *container* until a h3/h2 is hit."""
                for child in container.children:
                    if not hasattr(child, 'name') or not child.name:
                        continue
                    if child.name in ('h2', 'h3'):
                        return  # stop at notes headings
                    if child.name in ('p', 'div'):
                        text = self._clean_line(child.get_text(separator=' ', strip=True))
                        if text and len(text) > 10:
                            texts.append(text)
                            return  # only first instruction block

            for sibling in heading.next_siblings:
                if not hasattr(sibling, 'name') or not sibling.name:
                    continue
                if sibling.name in ('h2', 'h3'):
                    break
                if sibling.name == 'div':
                    _collect_from(sibling)
                    if texts:
                        break
                elif sibling.name == 'p':
                    text = self._clean_line(sibling.get_text(separator=' ', strip=True))
                    if text and len(text) > 10:
                        texts.append(text)
                        break

            if texts:
                return ' '.join(texts)

        # Flat fallback: the body text excluding the very first lines (description)
        raw_lines = [
            self._clean_line(line)
            for line in content.get_text(separator='\n').split('\n')
        ]
        instruction_lines = [
            ln for ln in raw_lines
            if ln and not ln.startswith('<!--') and len(ln) > 10
        ]
        # Skip first 2 lines (likely the description prose) and return the rest
        if len(instruction_lines) > 2:
            return ' '.join(instruction_lines[2:])

        return ' '.join(instruction_lines) or None

    def extract_category(self) -> Optional[str]:
        """
        Extract category.
        Looks for explicit "kategorien X" in the description, e.g.
        "hører til i kategorien fast food i Japan".
        Strips trailing location phrases like " i Japan".
        """
        desc = self.extract_description()
        if desc:
            m = re.search(
                r'kategorien\s+([^,.]+)',
                desc,
                re.IGNORECASE,
            )
            if m:
                cat = m.group(1).strip().rstrip('.')
                # Strip location qualifier: "fast food i Japan" → "fast food"
                cat = re.sub(r'\s+i\s+\w+.*$', '', cat, flags=re.IGNORECASE).strip()
                if cat:
                    return cat
        return None

    def extract_cook_time(self) -> Optional[str]:
        """
        Extract cook time from the instruction text.
        Sums all minute-values found; suitable for simple recipes.
        """
        content = self._get_entry_content()
        if content is None:
            return None

        # Prefer instruction section text only
        heading = self._find_heading(content, _INSTRUCTION_HEADING_RE)
        if heading:
            instr_text = ''
            for sibling in heading.next_siblings:
                if not hasattr(sibling, 'name') or not sibling.name:
                    continue
                if sibling.name in ('h2', 'h3'):
                    break
                if sibling.name in ('div', 'p'):
                    # Only take text before any nested h3 (notes boundary)
                    instr_text = sibling.get_text(separator=' ', strip=True)
                    if instr_text:
                        break
            if instr_text:
                minutes = [int(m.group(1)) for m in _TIME_RE.finditer(instr_text)]
                if minutes:
                    total = sum(minutes)
                    return f'{total} minutes'

        # Fallback: scan entire body
        body = content.get_text(separator=' ', strip=True)
        minutes = [int(m.group(1)) for m in _TIME_RE.finditer(body)]
        if minutes:
            total = sum(minutes)
            return f'{total} minutes'

        return None

    def extract_notes(self) -> Optional[str]:
        """
        Extract notes / tips from extra sections after the instructions.
        For structured pages these are h3-separated extra paragraphs inside
        the wrapper div that follows 'Fremgangsmåde'.
        For nudler-style pages they are the extra p-tags after the first
        instruction paragraph.
        """
        content = self._get_entry_content()
        if content is None:
            return None

        heading = self._find_heading(content, _INSTRUCTION_HEADING_RE)
        if heading is None:
            return None

        notes_parts: list[str] = []

        def _collect_notes_from(container):
            """Collect text after the first h3 inside *container*."""
            past_first_p = False
            past_first_h3 = False
            for child in container.children:
                if not hasattr(child, 'name') or not child.name:
                    continue
                if child.name in ('p', 'div') and not past_first_p:
                    # First real content block = instructions (skip it)
                    text = self._clean_line(child.get_text(separator=' ', strip=True))
                    if text and len(text) > 10:
                        past_first_p = True
                    continue
                if child.name in ('h3', 'h2'):
                    past_first_h3 = True
                    continue
                if past_first_h3 and child.name in ('p', 'div'):
                    text = self._clean_line(child.get_text(separator=' ', strip=True))
                    if text and len(text) > 10:
                        notes_parts.append(text)

        def _collect_notes_flat(start_heading):
            """Collect extra p-tags after the first instruction paragraph."""
            seen_first = False
            for sibling in start_heading.next_siblings:
                if not hasattr(sibling, 'name') or not sibling.name:
                    continue
                if sibling.name in ('h2', 'h3', 'h4'):
                    break
                if sibling.name == 'div':
                    _collect_notes_from(sibling)
                    return
                if sibling.name == 'p':
                    text = self._clean_line(sibling.get_text(separator=' ', strip=True))
                    if not text or len(text) < 5:
                        continue
                    if not seen_first:
                        seen_first = True
                        continue  # skip first p (instructions)
                    # Skip closing greetings
                    if re.match(r'^velbekomme', text, re.IGNORECASE):
                        continue
                    notes_parts.append(text)

        _collect_notes_flat(heading)

        if notes_parts:
            return ' '.join(notes_parts)
        return None

    def extract_tags(self) -> Optional[str]:
        """Extract tags from Blogger post labels (a[rel='tag'])."""
        labels = self.soup.find_all('a', rel='tag')
        tags: list[str] = []
        for label in labels:
            text = self.clean_text(label.get_text()).rstrip('. ')
            if text:
                tags.append(text)
        return ', '.join(tags) if tags else None

    def extract_image_urls(self) -> Optional[str]:
        """
        Extract image URLs from Blogger CDN images inside entry-content.
        Prefers the href of a parent anchor (full-size image link) over
        the thumbnail src.
        """
        content = self._get_entry_content()
        if content is None:
            return None

        urls: list[str] = []
        seen: set[str] = set()

        def _is_blogger_cdn(url: str) -> bool:
            """Return True only if the URL's hostname is the Blogger CDN domain."""
            try:
                return urlparse(url).hostname == 'blogger.googleusercontent.com'
            except Exception:
                return False

        for img in content.find_all('img'):
            # Try parent anchor first (full-size image)
            parent = img.parent
            if hasattr(parent, 'name') and parent.name == 'a':
                href = parent.get('href', '')
                if href and _is_blogger_cdn(href) and href not in seen:
                    seen.add(href)
                    urls.append(href)
                    continue
            # Fallback: img src (thumbnail)
            src = img.get('src', '')
            if src and _is_blogger_cdn(src) and src not in seen:
                seen.add(src)
                urls.append(src)

        return ','.join(urls) if urls else None

    # ------------------------------------------------------------------
    # Main extraction entry point
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """Extract all recipe data and return as a JSON-compatible dict."""
        result: dict = {
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

        fields = {
            'dish_name': self.extract_dish_name,
            'description': self.extract_description,
            'ingredients': self.extract_ingredients,
            'instructions': self.extract_instructions,
            'category': self.extract_category,
            'cook_time': self.extract_cook_time,
            'notes': self.extract_notes,
            'tags': self.extract_tags,
            'image_urls': self.extract_image_urls,
        }

        for field, extractor in fields.items():
            try:
                result[field] = extractor()
            except Exception as exc:
                logger.warning('Error extracting %s from %s: %s', field, self.html_path, exc)

        return result


def main() -> None:
    import os
    directory = os.path.join('preprocessed', 'dagbogfrajapan_blogspot_com')
    if os.path.exists(directory) and os.path.isdir(directory):
        process_directory(DagbogfrajapanBlogspotComExtractor, directory)
        return
    print(f'Directory not found: {directory}')
    print('Usage: python extractor/dagbogfrajapan_blogspot_com.py')


if __name__ == '__main__':
    main()
