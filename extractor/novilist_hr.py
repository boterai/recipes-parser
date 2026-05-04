"""
Экстрактор данных рецептов для сайта novilist.hr
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

# Croatian unit keywords (ordered: multi-word first, then single-word).
# Each pattern is anchored by the outer regex and must match the full token.
_UNIT_PATTERNS: List[str] = [
    # Multi-word units (must come before single-word matches)
    r'čajn(?:a|e|ih?)\s+žličic(?:a|e|u|i)',  # čajna žličica / čajne žličice
    # Single-word units — Croatian nouns appear in different case forms
    r'žlic(?:a|e|u|i)',          # žlica, žlice (tablespoon)
    r'žličic(?:a|e|u|i)',        # žličica, žličice (teaspoon)
    r'šalic(?:a|e|u|i)',         # šalica, šalice (cup)
    r'litr(?:a|e|u|i)|litar(?:a)?',  # litra, litre, litru, litri, litar, litara
    r'kilogram(?:a|e|u|i)?',     # kilogram, kilograma
    r'miligram(?:a|e|u|i)?',     # miligram, miligrama
    r'dkg\b',
    r'dl\b',
    r'ml\b',
    r'kg\b',
    r'g\b',
    r'l\b',
    r'oz\b',
    r'komad(?:a|i|u)?',          # komad, komada, komadi (piece)
    r'kom\b',
    r'grančic(?:a|e|u|i)',       # grančica, grančice (sprig)
    r'kriš(?:k(?:a|e|u|i)|ki)',  # kriška, kriške, kriški (slice)
    r'češanj|češnja',             # češanj, češnja (clove)
    r'list(?:a|u|ova)?',         # list, lista, listova (leaf)
    r'pakiran(?:je|ja)',          # pakiranje, pakiranja (package)
    r'paket(?:a|u|i)?',           # paket, paketa (packet)
    r'stabljik(?:a|e|u|i)',      # stabljika, stabljike (stalk)
    r'glavic(?:a|e|u|i)',        # glavica, glavice (head)
]

# Compiled unit regex — matches a SINGLE token (word or multi-word unit)
_UNIT_RE = re.compile(
    r'^(?:' + '|'.join(_UNIT_PATTERNS) + r')$',
    re.IGNORECASE | re.UNICODE,
)

# Fraction replacements
_FRACTION_MAP: Dict[str, str] = {
    '½': '0.5', '¼': '0.25', '¾': '0.75',
    '⅓': '0.333', '⅔': '0.667', '⅛': '0.125',
    '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
    '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8',
    '1⁄2': '0.5', '1⁄4': '0.25', '3⁄4': '0.75',
}

# Keywords for identifying ingredient headings (Croatian)
_INGREDIENT_HEADING_RE = re.compile(
    r'sastojci|potrebno\s+vam|za\s+\d+\s+porcij|za\s+pripremu\s+trebaš|što\s+trebaš',
    re.IGNORECASE,
)

# Keywords for identifying instruction headings (Croatian)
_INSTRUCTION_HEADING_RE = re.compile(
    r'\bpriprema\b|\bpripremu\b|\bupute\b|\bpostupak\b',
    re.IGNORECASE,
)

# Pattern to truncate article titles at Croatian relative/adverbial clauses
# and other decorative phrases that follow the core recipe name.
_TITLE_STOP_PATTERN = re.compile(
    r'\s+(?:koji(?:mu|j|h)?|koja|koje|što|jer|postat\s+(?:će|ce)'
    r'|je\s+(?:desert|jelo|juha|kolač|recept|savršen|ukusan|idealan|popularan)'
    r'|sa\s+samo\s+\d)',
    re.IGNORECASE,
)


def _normalize_fractions(text: str) -> str:
    """Replace Unicode fractions and slash-fractions with decimal equivalents."""
    for frac, dec in _FRACTION_MAP.items():
        text = text.replace(frac, dec)
    # Replace ASCII fractions like "1/2" that weren't already replaced
    text = re.sub(
        r'(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)',
        lambda m: str(round(int(m.group(1)) / int(m.group(2)), 3)),
        text,
    )
    return text


def _parse_ingredient_line(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse a single ingredient line such as:
      "4 žlice maslaca"           -> {name: "maslaca", amount: "4", unit: "žlice"}
      "2 čajne žličice soli"      -> {name: "soli", amount: "2", unit: "čajne žličice"}
      "sol i papar"               -> {name: "sol i papar", amount: None, unit: None}

    Args:
        text: Raw ingredient line.

    Returns:
        Dict with keys name, amount, unit, or None if the line is empty/invalid.
    """
    if not text:
        return None

    text = text.strip()
    # Normalize fractions before any processing
    text = _normalize_fractions(text)

    # Remove parenthetical quantity hints like "(oko 3 šalice)"
    # but keep parenthetical descriptions that are part of the name
    text = re.sub(r'\s*\(oko\s+[\d.,]+\s+\w+\)', '', text)

    # Try to extract a leading numeric amount (integer or decimal)
    # Covers: "4", "1.5", "0.125", "2 ½" (after fraction replacement), "1 ½"
    amount_match = re.match(
        r'^(\d+(?:[.,]\d+)?(?:\s+\d+(?:[.,]\d+)?)?)\s+(.+)$',
        text,
    )

    if not amount_match:
        # No leading number — no amount/unit
        return {"name": text, "amount": None, "unit": None}

    amount_str = amount_match.group(1).strip()
    rest = amount_match.group(2).strip()

    # Normalize amount: replace comma decimal separator, combine mixed numbers
    amount_str = amount_str.replace(',', '.')
    parts = amount_str.split()
    if len(parts) == 2:
        try:
            amount_str = str(float(parts[0]) + float(parts[1]))
        except ValueError:
            pass
    # Strip trailing zeros from amount string for cleanliness
    try:
        num = float(amount_str)
        amount_str = str(int(num)) if num == int(num) else str(num)
    except ValueError:
        pass

    # Try to match a unit (possibly multi-word: "čajne žličice")
    # Attempt 2-word unit match first, then 1-word
    words = rest.split()
    unit: Optional[str] = None
    name_words: List[str] = words

    # Try two-word unit (e.g. "čajne žličice")
    if len(words) >= 2:
        candidate_2 = f"{words[0]} {words[1]}"
        if _UNIT_RE.match(candidate_2):
            unit = candidate_2
            name_words = words[2:]

    # Try one-word unit
    if unit is None and words:
        if _UNIT_RE.match(words[0]):
            unit = words[0]
            name_words = words[1:]

    name = ' '.join(name_words).strip() if name_words else rest

    # Strip trailing descriptors after comma (e.g. ", sitno nasjeckana")
    # but keep content inside parentheses which are usually part of the name
    name = re.sub(r',\s+[a-zčćžšđA-ZČĆŽŠĐ].+$', '', name).strip()

    return {
        "name": name if name else rest,
        "amount": amount_str,
        "unit": unit,
    }


class NovilistHrExtractor(BaseRecipeExtractor):
    """Экстрактор для novilist.hr"""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _user_content(self):
        """Return the main article content div."""
        return self.soup.find('div', class_='user-content')

    def _iter_content_children(self):
        """Iterate over meaningful direct children of user-content."""
        uc = self._user_content()
        if not uc:
            return
        for child in uc.children:
            if not hasattr(child, 'name') or not child.name:
                continue
            yield child

    def _find_heading_index(self, pattern: re.Pattern) -> Optional[int]:
        """
        Return the position (0-based) of the first heading (h2/h3) in
        user-content whose text matches *pattern*.
        """
        for idx, tag in enumerate(self._iter_content_children()):
            if tag.name in ('h2', 'h3') and pattern.search(tag.get_text(strip=True)):
                return idx
        return None

    def _collect_items_after_heading(self, heading_idx: int) -> List[str]:
        """
        Collect text items (li elements from UL, or paragraph texts) that
        immediately follow the heading at *heading_idx* and precede the next
        heading.

        Returns:
            List of non-empty text strings.
        """
        children = list(self._iter_content_children())
        items: List[str] = []
        collecting = False

        for idx, tag in enumerate(children):
            if idx == heading_idx:
                collecting = True
                continue

            if not collecting:
                continue

            # Stop at the next heading at the same level or higher
            if tag.name in ('h2', 'h3', 'h4', 'h5'):
                break

            # Collect list items
            if tag.name == 'ul':
                for li in tag.find_all('li'):
                    text = self.clean_text(li.get_text(separator=' ', strip=True))
                    if text:
                        items.append(text)
                # After a UL we consider the ingredient block done
                break

            # Collect paragraph texts
            if tag.name == 'p':
                text = self.clean_text(tag.get_text(separator=' ', strip=True))
                if text:
                    items.append(text)

        return items

    def _collect_paragraphs_after_heading(self, heading_idx: int) -> List[str]:
        """
        Collect paragraph texts after heading at *heading_idx* until the
        next heading.
        """
        children = list(self._iter_content_children())
        paragraphs: List[str] = []
        collecting = False

        for idx, tag in enumerate(children):
            if idx == heading_idx:
                collecting = True
                continue

            if not collecting:
                continue

            if tag.name in ('h2', 'h3', 'h4', 'h5'):
                break

            if tag.name == 'p':
                text = self.clean_text(tag.get_text(separator=' ', strip=True))
                if text:
                    paragraphs.append(text)

        return paragraphs

    # ------------------------------------------------------------------
    # Extraction methods
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Extract the recipe title from h1.article-title.

        The article title on novilist.hr usually starts with the actual recipe
        name followed by additional descriptive text (relative clauses, prepositional
        phrases, or a colon-separated subtitle).  We strip the decorative tail to
        return only the core recipe name.
        """
        try:
            h1 = self.soup.find('h1', class_='article-title')
            raw = h1.get_text() if h1 else None

            if not raw:
                # Fallback: og:title (strip site suffix)
                og_title = self.soup.find('meta', property='og:title')
                if og_title and og_title.get('content'):
                    raw = re.sub(
                        r'\s*[-–|]\s*Novi\s+list.*$', '', og_title['content'],
                        flags=re.IGNORECASE,
                    )

            if not raw:
                return None

            title = self.clean_text(raw)

            # Strip subtitle after a colon  (e.g. "Toskanska juha: kremasti klasik…")
            title = re.split(r'\s*:\s+', title)[0].strip()

            # Truncate at the first Croatian relative/adverbial clause that
            # introduces a description rather than being part of the recipe name.
            stop_match = _TITLE_STOP_PATTERN.search(title)
            if stop_match:
                title = title[:stop_match.start()].strip()

            return title if title else self.clean_text(raw)

        except Exception as exc:
            logger.warning("extract_dish_name failed: %s", exc)
        return None

    def extract_description(self) -> Optional[str]:
        """Extract article description from og:description or meta description."""
        try:
            og_desc = self.soup.find('meta', property='og:description')
            if og_desc and og_desc.get('content'):
                return self.clean_text(og_desc['content'])

            meta_desc = self.soup.find('meta', {'name': 'description'})
            if meta_desc and meta_desc.get('content'):
                return self.clean_text(meta_desc['content'])
        except Exception as exc:
            logger.warning("extract_description failed: %s", exc)
        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Extract ingredients from the article.

        Supports two HTML layouts:
          1. h2 "Sastojci" followed by <ul><li> items
          2. h2 "Sastojci" followed by <p> paragraphs (one per ingredient)
        """
        try:
            children = list(self._iter_content_children())

            # Find ingredient heading
            ingr_idx: Optional[int] = None
            for idx, tag in enumerate(children):
                if tag.name in ('h2', 'h3') and _INGREDIENT_HEADING_RE.search(
                    tag.get_text(strip=True)
                ):
                    ingr_idx = idx
                    break

            if ingr_idx is None:
                logger.warning("No ingredient heading found in %s", self.html_path)
                return None

            raw_lines = self._collect_items_after_heading(ingr_idx)
            if not raw_lines:
                return None

            parsed = []
            for line in raw_lines:
                result = _parse_ingredient_line(line)
                if result and result.get('name'):
                    parsed.append(result)

            return json.dumps(parsed, ensure_ascii=False) if parsed else None

        except Exception as exc:
            logger.warning("extract_ingredients failed: %s", exc)
            return None

    def extract_instructions(self) -> Optional[str]:
        """
        Extract preparation instructions.

        Supports two layouts:
          1. h2 "Priprema" followed by <p> paragraphs
          2. No explicit "Priprema" heading — collect paragraphs after
             ingredient section until end of article.
        """
        try:
            children = list(self._iter_content_children())

            # Try explicit "Priprema" heading
            instr_idx = self._find_heading_index(_INSTRUCTION_HEADING_RE)
            if instr_idx is not None:
                paragraphs = self._collect_paragraphs_after_heading(instr_idx)
                if paragraphs:
                    return ' '.join(paragraphs)

            # Fallback: collect everything after the ingredient UL/section
            ingr_idx: Optional[int] = None
            for idx, tag in enumerate(children):
                if tag.name in ('h2', 'h3') and _INGREDIENT_HEADING_RE.search(
                    tag.get_text(strip=True)
                ):
                    ingr_idx = idx
                    break

            if ingr_idx is None:
                return None

            # Skip past the ingredient section (UL or consecutive p tags)
            paragraphs: List[str] = []
            past_ingredients = False
            for idx, tag in enumerate(children):
                if idx <= ingr_idx:
                    continue
                # The ingredient section ends at the first UL
                if not past_ingredients:
                    if tag.name == 'ul':
                        past_ingredients = True
                    continue

                if tag.name in ('h2', 'h3'):
                    break

                if tag.name == 'p':
                    text = self.clean_text(tag.get_text(separator=' ', strip=True))
                    if text:
                        paragraphs.append(text)

            return ' '.join(paragraphs) if paragraphs else None

        except Exception as exc:
            logger.warning("extract_instructions failed: %s", exc)
            return None

    def extract_category(self) -> Optional[str]:
        """Category is not structured in novilist.hr HTML — returns None."""
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Preparation time is not structured in novilist.hr HTML — returns None."""
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Cook time is not structured in novilist.hr HTML — returns None."""
        return None

    def extract_total_time(self) -> Optional[str]:
        """Total time is not structured in novilist.hr HTML — returns None."""
        return None

    def extract_notes(self) -> Optional[str]:
        """
        Extract notes from explicit h2/h3 sections that follow the
        "Priprema" (instructions) section.
        """
        try:
            children = list(self._iter_content_children())

            # Find the instruction section index
            instr_idx = self._find_heading_index(_INSTRUCTION_HEADING_RE)

            # Scan for any h2/h3 AFTER instruction section that is not an
            # ingredient/instruction heading
            notes_parts: List[str] = []
            in_notes = False

            for idx, tag in enumerate(children):
                if instr_idx is not None and idx <= instr_idx:
                    continue

                if tag.name in ('h2', 'h3'):
                    heading_text = tag.get_text(strip=True)
                    is_known = (
                        _INGREDIENT_HEADING_RE.search(heading_text)
                        or _INSTRUCTION_HEADING_RE.search(heading_text)
                    )
                    if not is_known:
                        # This looks like a notes section
                        in_notes = True
                        continue
                    else:
                        # Another recipe section — stop
                        break

                if in_notes and tag.name == 'p':
                    text = self.clean_text(tag.get_text(separator=' ', strip=True))
                    if text:
                        notes_parts.append(text)

            return ' '.join(notes_parts) if notes_parts else None

        except Exception as exc:
            logger.warning("extract_notes failed: %s", exc)
            return None

    def extract_tags(self) -> Optional[str]:
        """Tags are not structured in novilist.hr HTML — returns None."""
        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Extract image URLs from:
          1. og:image meta tag (primary recipe image)
          2. <img> tags inside user-content div
        """
        try:
            urls: List[str] = []
            seen: set = set()

            def _add(url: str) -> None:
                if url and url not in seen and url.startswith('http'):
                    seen.add(url)
                    urls.append(url)

            # 1. og:image
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                _add(og_image['content'])

            # 2. Images inside user-content
            uc = self._user_content()
            if uc:
                for img in uc.find_all('img'):
                    # Prefer original src over small thumbnails
                    src = img.get('src') or ''
                    # Skip Instagram/external embed images (contain instagram.com)
                    if 'instagram.com' in src or 'gravatar.com' in src:
                        continue
                    if src.startswith('http'):
                        _add(src)

            return ','.join(urls) if urls else None

        except Exception as exc:
            logger.warning("extract_image_urls failed: %s", exc)
            return None

    def extract_all(self) -> dict:
        """
        Extract all recipe data and return a JSON-compatible dict.

        Returns:
            dict with keys: dish_name, description, ingredients, instructions,
            category, prep_time, cook_time, total_time, notes, tags, image_urls.
        """
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
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls(),
        }


def main() -> None:
    """Process all HTML files in the preprocessed/novilist_hr directory."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "novilist_hr")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(NovilistHrExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python novilist_hr.py")


if __name__ == "__main__":
    main()
