"""
Экстрактор данных рецептов для сайта bljesak.info
"""

import sys
from pathlib import Path
import json
import logging
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Croatian measurement units
_CROATIAN_UNITS = (
    r'kg|kilograma?|kilogram[ai]?'
    r'|g|gram[ai]?|grama'
    r'|dag|dekagram[ai]?'
    r'|ml|mililitar[ai]?|mililitara?'
    r'|dl|decilitar[ai]?|decilitara?'
    r'|cl|centilitar[ai]?'
    r'|l|litar[ai]?|litr[ae]?'
    r'|žlice?|žličice?|žlica|žličica'
    r'|šalice?|šalica'
    r'|kom(?:ad(?:a)?)?'
    r'|kos(?:a)?'
    r'|vezice?|vezica'
    r'|prstohvat[ai]?'
    r'|grančice?|grančica'
    r'|lista?|listić[ai]?'
    r'|paketic[ae]?|paket[ai]?'
    r'|konzerv[ae]?'
    r'|kap(?:i|ljica)?'
    r'|vrećice?|vrećica'
    r'|šaka|šake'
    r'|zrno|zrna'
)

_UNIT_RE = re.compile(
    r'\b(' + _CROATIAN_UNITS + r')\b',
    re.IGNORECASE,
)

_AMOUNT_RE = re.compile(
    r'^(\d+(?:[.,]\d+)?(?:\s+do\s+\d+(?:[.,]\d+)?)?'
    r'(?:\s+\d+/\d+)?'
    r'|\d+/\d+)',
    re.IGNORECASE,
)


class BljesakInfoExtractor(BaseRecipeExtractor):
    """Экстрактор для bljesak.info"""

    # ------------------------------------------------------------------ #
    # Internal helpers                                                      #
    # ------------------------------------------------------------------ #

    def _content_div(self):
        """Return the main article body div (class ContentPhotos)."""
        return self.soup.find('div', class_='ContentPhotos')

    def _h3_sections(self):
        """
        Return a list of (h3_text, sibling_elements) pairs from the
        ContentPhotos div, where sibling_elements are the direct siblings
        until the next h3 tag.
        """
        content = self._content_div()
        if not content:
            return []

        sections = []
        h3_tags = content.find_all('h3')
        for h3 in h3_tags:
            siblings = []
            sib = h3.find_next_sibling()
            while sib:
                if getattr(sib, 'name', None) == 'h3':
                    break
                siblings.append(sib)
                sib = sib.find_next_sibling()
            sections.append((h3.get_text(strip=True), siblings))
        return sections

    @staticmethod
    def _is_ingredients_header(text: str) -> bool:
        return bool(re.search(r'\bsastojc', text, re.I))

    @staticmethod
    def _is_instructions_header(text: str) -> bool:
        return bool(re.search(r'\b(postupak|priprema)\b', text, re.I))

    # ------------------------------------------------------------------ #
    # Ingredient parsing                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_ingredient_line(raw: str) -> Optional[dict]:
        """
        Parse a single ingredient line (Croatian) into
        {"name": str, "amount": str|int|float|None, "unit": str|None}.

        Supported formats:
          "tikvice 400 g"               → name=tikvice, amount=400, unit=g
          "1 kg glatkog brašna"         → name=glatkog brašna, amount=1, unit=kg
          "4 jaja"                      → name=jaja, amount=4, unit=None
          "• 150 grama sitnih pahuljica"→ name=sitnih pahuljica, amount=150, unit=grama
          "Prstohvat soli"              → name=soli, amount=None, unit=Prstohvat
          "sol"                         → name=sol, amount=None, unit=None
        """
        text = raw.strip()
        # Remove bullet characters and leading/trailing commas/dots
        text = re.sub(r'^[•·\-–—*]+\s*', '', text)
        text = re.sub(r'[,.]$', '', text).strip()
        if not text:
            return None

        amount: Optional[str] = None
        unit: Optional[str] = None
        name: str = text

        # ---- Case 1: starts with a number  --------------------------------
        m_amount = _AMOUNT_RE.match(text)
        if m_amount:
            amount_raw = m_amount.group(1)
            remainder = text[m_amount.end():].strip()

            # Check if next token is a unit
            m_unit = _UNIT_RE.match(remainder)
            if m_unit:
                unit = m_unit.group(1)
                name = remainder[m_unit.end():].strip()
            else:
                name = remainder

            # Normalise amount string to a number when possible
            amount = amount_raw.strip()
            # Handle "X do Y" ranges – take the larger value
            range_m = re.match(r'(\d+(?:[.,]\d+)?)\s+do\s+(\d+(?:[.,]\d+)?)', amount)
            if range_m:
                amount = range_m.group(2).replace(',', '.')
            else:
                amount = amount.replace(',', '.')
            # Try to cast to int/float
            try:
                float_val = float(amount)
                amount = int(float_val) if float_val == int(float_val) else float_val
            except ValueError:
                pass

        # ---- Case 1b: starts with a unit word (e.g. "Prstohvat soli") ----
        else:
            m_unit_first = _UNIT_RE.match(text)
            if m_unit_first:
                unit = m_unit_first.group(1)
                name = text[m_unit_first.end():].strip()
                # amount remains None

            # ---- Case 2: ends with  "number unit"  or just "number" ----------
            elif re.search(r'\d', text):
                # Try pattern: <name> <amount> <unit>  e.g. "tikvice 400 g"
                trailing = re.search(
                    r'\s+(\d+(?:[.,]\d+)?)\s+(' + _CROATIAN_UNITS + r')\s*$',
                    text,
                    re.IGNORECASE,
                )
                if trailing:
                    name = text[:trailing.start()].strip()
                    amount_raw = trailing.group(1).replace(',', '.')
                    try:
                        float_val = float(amount_raw)
                        amount = int(float_val) if float_val == int(float_val) else float_val
                    except ValueError:
                        amount = amount_raw
                    unit = trailing.group(2)
                else:
                    # Try pattern: <name> <amount> (no unit) e.g. "jaja 2"
                    trailing_num = re.search(r'\s+(\d+(?:[.,]\d+)?)\s*$', text)
                    if trailing_num:
                        name = text[:trailing_num.start()].strip()
                        amount_raw = trailing_num.group(1).replace(',', '.')
                        try:
                            float_val = float(amount_raw)
                            amount = int(float_val) if float_val == int(float_val) else float_val
                        except ValueError:
                            amount = amount_raw

        # Clean name
        # Remove parenthetical weight annotations like "(40g)"
        name = re.sub(r'\(\s*\d+\s*[a-zA-Z]+\s*\)', '', name).strip()
        # Remove trailing comma/period
        name = re.sub(r'[,.]$', '', name).strip()

        if not name:
            return None

        return {"name": name, "amount": amount, "unit": unit}

    def _collect_ingredients(self, siblings) -> list:
        """
        Extract ingredient items from the sibling elements of a
        "Sastojci" heading. Handles <p>, <ul>/<li>, and mixed formats.
        """
        items = []

        for sib in siblings:
            tag = getattr(sib, 'name', None)
            if tag is None:
                continue
            if tag in ('div',) and not sib.get_text(strip=True):
                # Ad placeholder divs
                continue

            if tag == 'ul':
                # List items
                for li in sib.find_all('li'):
                    raw = li.get_text(separator=' ', strip=True)
                    raw = self.clean_text(raw)
                    # A single li may contain comma-separated items without quantities
                    # e.g. "Sol, papar, bosiljak, origano" – split them
                    parsed_items = self._parse_ingredient_entry(raw)
                    items.extend(parsed_items)
            elif tag == 'p':
                raw = sib.get_text(separator=' ', strip=True)
                raw = self.clean_text(raw)
                if not raw:
                    continue
                # Skip sub-section labels like "Za podlogu od tikvica:"
                if raw.endswith(':'):
                    continue
                parsed_items = self._parse_ingredient_entry(raw)
                items.extend(parsed_items)

        return items

    def _parse_ingredient_entry(self, raw: str) -> list:
        """
        Parse one raw ingredient entry, potentially returning multiple items
        when the entry contains comma-separated items without quantities
        (e.g. "Sol, papar, bosiljak, origano").
        """
        if not raw:
            return []

        # Strip bullet prefix first
        cleaned = re.sub(r'^[•·\-–—*]+\s*', '', raw).strip()
        cleaned = re.sub(r'[,.]$', '', cleaned).strip()

        if not cleaned:
            return []

        # Check whether the text contains a number (quantity)
        has_number = bool(re.search(r'\d', cleaned))

        if not has_number:
            # Do not split if the text describes a collection with a dash
            # e.g. "Dodaci po ukusu - jaje, avokado, klice..."
            # or if it contains "po ukusu"/"po želji" (qualifier phrases)
            if ' - ' in cleaned or re.search(r'\bpo\s+(ukusu|želji)\b', cleaned, re.I):
                parsed = self._parse_ingredient_line(raw)
                return [parsed] if parsed else []

            # May be a comma-separated list of ingredients without quantities
            # Split on comma and treat each part as a separate ingredient
            parts = [p.strip() for p in cleaned.split(',') if p.strip()]
            if len(parts) > 1:
                items = []
                for part in parts:
                    part = re.sub(r'[,.]$', '', part).strip()
                    if part:
                        items.append({"name": part, "amount": None, "unit": None})
                return items
            # Single item without quantity
            parsed = self._parse_ingredient_line(raw)
            return [parsed] if parsed else []

        # Has a number – parse as a single structured ingredient
        parsed = self._parse_ingredient_line(raw)
        return [parsed] if parsed else []

    # ------------------------------------------------------------------ #
    # Extraction methods                                                    #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Extract the recipe title from the <h1> tag."""
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        # Fallback: og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        logger.warning("Could not find dish name in %s", self.html_path)
        return None

    def extract_description(self) -> Optional[str]:
        """
        Extract the short description/subtitle. The subtitle is
        rendered as the first <div> sibling after the <h1>.
        Falls back to og:description.
        """
        try:
            h1 = self.soup.find('h1')
            if h1:
                sib = h1.find_next_sibling()
                if sib and sib.name == 'div':
                    text = self.clean_text(sib.get_text())
                    # Replace trailing ellipsis ("..." 2+ dots) with a single period
                    text = re.sub(r'\.{2,}\s*$', '.', text).strip()
                    if text:
                        return text
        except Exception as exc:
            logger.warning("Error extracting description: %s", exc)

        # Fallback: og:description
        for meta_name in [{'property': 'og:description'}, {'name': 'description'}]:
            meta = self.soup.find('meta', meta_name)
            if meta and meta.get('content'):
                return self.clean_text(meta['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Extract ingredients from the "Sastojci" section.
        Returns a JSON-encoded list of dicts, or None.
        """
        content = self._content_div()
        if not content:
            logger.warning("ContentPhotos div not found in %s", self.html_path)
            return None

        # First try h3-based sections
        sections = self._h3_sections()
        for heading, siblings in sections:
            if self._is_ingredients_header(heading):
                items = self._collect_ingredients(siblings)
                if items:
                    return json.dumps(items, ensure_ascii=False)

        # Fallback: look for <p> "Sastojci:" pattern (zobena-type structure)
        # where the header is inside a <p> (with or without <strong>)
        ing_header_p = None
        for p in content.find_all('p'):
            raw = p.get_text(strip=True)
            if self._is_ingredients_header(raw) and len(raw) < 80:
                ing_header_p = p
                break

        if ing_header_p:
            items = []
            sib = ing_header_p.find_next_sibling()
            while sib:
                tag = getattr(sib, 'name', None)
                if tag is None:
                    sib = sib.find_next_sibling()
                    continue
                raw_text = sib.get_text(strip=True)
                # Stop at instruction header
                if tag == 'p' and self._is_instructions_header(raw_text) and len(raw_text) < 80:
                    break
                if tag == 'h3' and self._is_instructions_header(raw_text):
                    break
                if tag in ('p', 'ul'):
                    batch = self._collect_ingredients([sib])
                    items.extend(batch)
                sib = sib.find_next_sibling()
            if items:
                return json.dumps(items, ensure_ascii=False)

        logger.warning("No ingredients found in %s", self.html_path)
        return None

    def extract_steps(self) -> Optional[str]:
        """
        Extract the preparation instructions from the "Postupak"/"Priprema" section.
        Returns a single concatenated string of all steps.
        """
        content = self._content_div()
        if not content:
            return None

        # Try h3-based sections
        sections = self._h3_sections()
        for heading, siblings in sections:
            if self._is_instructions_header(heading):
                steps = self._collect_instruction_steps(siblings)
                if steps:
                    return ' '.join(steps)

        # Fallback: <p> "priprema" marker
        instr_header_p = None
        for p in content.find_all('p'):
            raw = p.get_text(strip=True)
            if self._is_instructions_header(raw) and len(raw) < 80:
                instr_header_p = p
                break

        if instr_header_p:
            steps = []
            sib = instr_header_p.find_next_sibling()
            while sib:
                tag = getattr(sib, 'name', None)
                if tag is None:
                    sib = sib.find_next_sibling()
                    continue
                raw_text = sib.get_text(strip=True)
                # Stop at "Pročitajte još" or similar
                if tag == 'h3' or (tag == 'p' and re.search(r'pročitajte', raw_text, re.I)):
                    break
                if tag in ('p', 'ol', 'ul'):
                    for item in sib.find_all('li') if sib.find_all('li') else [sib]:
                        step_text = self.clean_text(item.get_text(separator=' ', strip=True))
                        if step_text:
                            steps.append(step_text)
                sib = sib.find_next_sibling()
            if steps:
                return ' '.join(steps)

        logger.warning("No instructions found in %s", self.html_path)
        return None

    @staticmethod
    def _collect_instruction_steps(siblings) -> list:
        """Collect step texts from instruction siblings."""
        steps = []
        for sib in siblings:
            tag = getattr(sib, 'name', None)
            if tag is None:
                continue
            raw_text = sib.get_text(strip=True)
            if not raw_text:
                continue
            # Stop at next major heading
            if tag == 'h3':
                # "Pročitajte još" headings mark the end of recipe steps
                if re.search(r'pročitajte', raw_text, re.I):
                    break
                # Any other h3 that is not a sub-step also ends the section
                break
            # Skip "Pročitajte još" inline blocks (div, aside, etc.)
            if re.search(r'pročitajte', raw_text, re.I) and tag not in ('p', 'ol', 'ul'):
                continue
            # Stop before notes/tip sections
            if tag == 'p' and re.match(r'savjet\s*:|napomena\s*:', raw_text, re.I):
                break
            if tag in ('p', 'ol', 'ul'):
                # Collect li items if list, else paragraph text
                li_items = sib.find_all('li')
                if li_items:
                    for li in li_items:
                        step_text = li.get_text(separator=' ', strip=True).strip()
                        if step_text:
                            steps.append(step_text)
                else:
                    step_text = sib.get_text(separator=' ', strip=True)
                    # Clean HTML tags residue
                    step_text = re.sub(r'\s+', ' ', step_text).strip()
                    if step_text:
                        steps.append(step_text)
        return steps

    def extract_category(self) -> Optional[str]:
        """
        bljesak.info does not expose structured recipe categories in HTML.
        Returns None.
        """
        return None

    def extract_prep_time(self) -> Optional[str]:
        """
        Try to extract preparation time from the article text.
        Looks for mentions of time in the introductory paragraphs
        (before SASTOJCI).
        Returns e.g. "20 minutes" or None.
        """
        content = self._content_div()
        if not content:
            return None

        # Collect text from all paragraphs that appear before the first
        # ingredient/instruction heading (h3 or p-based marker).
        pre_recipe_texts = []
        for elem in content.find_all(['p', 'h3']):
            raw_text = elem.get_text(strip=True)
            if elem.name == 'h3' and (
                self._is_ingredients_header(raw_text)
                or self._is_instructions_header(raw_text)
            ):
                break
            if elem.name == 'p' and (
                self._is_ingredients_header(raw_text)
                or self._is_instructions_header(raw_text)
            ) and len(raw_text) < 80:
                break
            if elem.name == 'p':
                pre_recipe_texts.append(raw_text)

        full_intro = ' '.join(pre_recipe_texts)
        return self._extract_time_from_text(full_intro)

    def extract_cook_time(self, _prep_time_result: Optional[str] = None) -> Optional[str]:
        """
        Try to extract cooking time from the instructions section.
        Returns e.g. "45 minutes" or None.

        If a prep_time was already extracted from the intro text (the overall
        recipe time), cook_time is returned as None to avoid double-counting.

        Args:
            _prep_time_result: pass the already-computed prep_time to avoid
                               redundant re-parsing (used by extract_all).
        """
        # If prep_time was already found in the intro, skip cook_time
        if _prep_time_result is None:
            try:
                _prep_time_result = self.extract_prep_time()
            except Exception:
                pass
        if _prep_time_result is not None:
            return None

        content = self._content_div()
        if not content:
            return None

        # Try h3-based sections first
        sections = self._h3_sections()
        for heading, siblings in sections:
            if self._is_instructions_header(heading):
                parts = []
                for sib in siblings:
                    if getattr(sib, 'name', None) in ('p', 'ol', 'ul'):
                        parts.append(sib.get_text(separator=' ', strip=True))
                instr_text = ' '.join(parts)
                result = self._extract_time_from_text(instr_text)
                if result:
                    return result

        # Fallback: find p-based instruction header (zobena-type)
        instr_header_p = None
        for p in content.find_all('p'):
            raw = p.get_text(strip=True)
            if self._is_instructions_header(raw) and len(raw) < 80:
                instr_header_p = p
                break

        if instr_header_p:
            parts = []
            sib = instr_header_p.find_next_sibling()
            while sib:
                tag = getattr(sib, 'name', None)
                if tag == 'h3' or (
                    tag == 'p'
                    and self._is_ingredients_header(sib.get_text(strip=True))
                ):
                    break
                if tag in ('p', 'ol', 'ul'):
                    parts.append(sib.get_text(separator=' ', strip=True))
                sib = sib.find_next_sibling()
            instr_text = ' '.join(parts)
            return self._extract_time_from_text(instr_text)

        return None

    @staticmethod
    def _extract_time_from_text(text: str) -> Optional[str]:
        """
        Extract a time duration (minutes) mentioned in a text.
        Returns the largest plausible value as "X minutes".
        """
        if not text:
            return None

        # Patterns: "45 minuta", "20 minuta", "oko 30 minuta"
        matches = re.findall(r'(\d+)\s*(?:do\s+(\d+)\s*)?minut', text, re.IGNORECASE)
        times = []
        for m in matches:
            for val in m:
                if val:
                    n = int(val)
                    if 1 <= n <= 480:  # reasonable cook time range
                        times.append(n)

        if times:
            return f"{max(times)} minutes"
        return None

    def extract_total_time(self) -> Optional[str]:
        """bljesak.info does not have a total time field. Returns None."""
        return None

    def extract_notes(self) -> Optional[str]:
        """
        Extract recipe notes/tips. Looks for:
        1. Paragraphs starting with "Savjet:" in the content.
        2. Any paragraph containing "Napomena" or similar.
        Returns None if nothing found.
        """
        content = self._content_div()
        if not content:
            return None

        for p in content.find_all('p'):
            text = p.get_text(separator=' ', strip=True)
            # "Savjet:" is the most common tip marker
            if re.match(r'savjet\s*:', text, re.I):
                note = re.sub(r'^savjet\s*:\s*', '', text, flags=re.I).strip()
                return self.clean_text(note) if note else None
            # "Napomena:"
            if re.match(r'napomena\s*:', text, re.I):
                note = re.sub(r'^napomena\s*:\s*', '', text, flags=re.I).strip()
                return self.clean_text(note) if note else None
            # "Napominjemo" / "Napomene"
            if re.match(r'napominjemo|napomene?\s*:', text, re.I):
                return self.clean_text(text)

        return None

    def extract_tags(self) -> Optional[str]:
        """
        Extract tags from the <meta name="keywords"> tag.
        Returns a comma-separated string (preserving original formatting).
        """
        meta_kw = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_kw and meta_kw.get('content'):
            return self.clean_text(meta_kw['content'])
        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Extract image URLs. Collects og:image and twitter:image meta tags,
        returns them as a comma-separated string without spaces.
        """
        urls = []

        og_image = self.soup.find('meta', attrs={'property': 'og:image'})
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            img_url = twitter_image['content']
            if img_url not in urls:
                urls.append(img_url)

        if not urls:
            return None
        return ','.join(urls)

    # ------------------------------------------------------------------ #
    # Public API                                                            #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """
        Extract all recipe data from the HTML page.

        Returns:
            dict with keys: dish_name, description, ingredients,
            instructions, category, prep_time, cook_time, total_time,
            notes, image_urls, tags.
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception as exc:
            logger.warning("extract_dish_name failed: %s", exc)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as exc:
            logger.warning("extract_description failed: %s", exc)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as exc:
            logger.warning("extract_ingredients failed: %s", exc)
            ingredients = None

        try:
            instructions = self.extract_steps()
        except Exception as exc:
            logger.warning("extract_steps failed: %s", exc)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as exc:
            logger.warning("extract_category failed: %s", exc)
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception as exc:
            logger.warning("extract_prep_time failed: %s", exc)
            prep_time = None

        try:
            cook_time = self.extract_cook_time(_prep_time_result=prep_time)
        except Exception as exc:
            logger.warning("extract_cook_time failed: %s", exc)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception as exc:
            logger.warning("extract_total_time failed: %s", exc)
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception as exc:
            logger.warning("extract_notes failed: %s", exc)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as exc:
            logger.warning("extract_tags failed: %s", exc)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as exc:
            logger.warning("extract_image_urls failed: %s", exc)
            image_urls = None

        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "notes": notes,
            "image_urls": image_urls,
            "tags": tags,
        }


def main():
    """Process all HTML files in the preprocessed/bljesak_info directory."""
    import os

    repo_root = Path(__file__).parent.parent
    recipes_dir = repo_root / "preprocessed" / "bljesak_info"

    if recipes_dir.exists() and recipes_dir.is_dir():
        process_directory(BljesakInfoExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python bljesak_info.py")


if __name__ == "__main__":
    main()
