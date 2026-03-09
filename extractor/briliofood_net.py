"""
Экстрактор данных рецептов для сайта briliofood.net
"""

import logging
import sys
from pathlib import Path
import json
import re
from typing import Optional

from bs4 import NavigableString

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Indonesian unit words used on briliofood.net
INDONESIAN_UNITS = {
    # Metric / international
    'kg', 'gram', 'gr', 'g', 'ml', 'liter', 'l',
    # Indonesian spoon measurements
    'sdm', 'sdt', 'sendok makan', 'sendok teh',
    'makan', 'teh',
    # Count-based
    'buah', 'butir', 'lembar', 'batang', 'siung', 'bungkus',
    'sachet', 'helai', 'ikat', 'tangkai', 'potong',
    'loyang', 'mangkuk', 'gelas', 'cup', 'slice', 'cubit',
    'ruas', 'genggam', 'lembar', 'keping', 'kotak', 'kaleng',
    'biji',
}

# Indonesian quantity words (adverbs used as amounts)
QUANTITY_WORDS = {
    'sejumput', 'secukupnya', 'sesuai selera', 'opsional',
    'sedikit', 'secukup',
}

# Words indicating purpose / description (treated as unit text)
PURPOSE_PREFIXES = ('untuk ', 'sebagai ', 'sebagai bahan ')


class BriliofoodNetExtractor(BaseRecipeExtractor):
    """Экстрактор для briliofood.net"""

    # ------------------------------------------------------------------ helpers

    def _get_detail_box(self):
        """Return the main content div (detail__box) or None."""
        return self.soup.find('div', class_='detail__box')

    def _get_kly_gtm(self) -> Optional[dict]:
        """Extract window.kly.gtm data from inline <script>."""
        for script in self.soup.find_all('script'):
            text = script.string or ''
            if 'window.kly.gtm' not in text:
                continue
            try:
                m = re.search(r'window\.kly\.gtm\s*=\s*(\{.*?\});', text, re.S)
                if m:
                    raw = m.group(1)
                    # strip JS trailing commas before closing braces/brackets
                    raw = re.sub(r',(\s*[}\]])', r'\1', raw)
                    return json.loads(raw)
            except Exception as exc:
                logger.debug('Failed to parse window.kly.gtm: %s', exc)
        return None

    # ------------------------------------------------------------------ name

    def extract_dish_name(self) -> Optional[str]:
        """Extract recipe title from H1."""
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        # Fallback: og:title
        og = self.soup.find('meta', property='og:title')
        if og and og.get('content'):
            return self.clean_text(og['content'])
        return None

    # ------------------------------------------------------------------ description

    def extract_description(self) -> Optional[str]:
        """Extract article description from the first content paragraph."""
        detail_box = self._get_detail_box()
        if not detail_box:
            return None

        skip_patterns = re.compile(
            r'^foto:|^yuk\s+(ikutan|cobain)\s+bareng|^\(brl/',
            re.I
        )
        attribution_pattern = re.compile(
            r'[^.]*\b(Dilansir|Cara bikinnya|dari akun\s+\S+)[^.]*\.',
            re.I
        )

        for p in detail_box.find_all('p'):
            raw = p.get_text(separator=' ', strip=True)
            if not raw or skip_patterns.match(raw):
                continue

            # Remove "Brilio.net -" prefix
            raw = re.sub(r'^Brilio\.net\s*[-–—]\s*', '', raw)

            # Remove source attribution phrases
            raw = attribution_pattern.sub('', raw)
            # Normalize spaces around punctuation (from separator=' ' in get_text)
            raw = re.sub(r'\s+([.,!?;:])', r'\1', raw)
            raw = self.clean_text(raw)

            if raw and len(raw) > 20:
                return raw

        return None

    # ------------------------------------------------------------------ ingredients

    @staticmethod
    def _split_ingredient_items(text: str) -> list:
        """
        Split a raw ingredient paragraph into individual item strings.

        Handles both:
          "Bahan:- item1- item2..."   (old inline format)
          "- item1- item2..."         (standard format, possibly with ". " or just "-")
        """
        # Remove common section label prefixes that may appear at the start
        text = re.sub(
            r'^(Bahan[^:]*:)\s*',
            '',
            text.strip(),
            flags=re.I
        )
        # Split on "- " boundaries; items may be separated by just "-"
        # We normalise: replace "- " with "\n- " to split cleanly
        text = re.sub(r'(?<!\n)-\s+', '\n', text)
        items = []
        for part in text.split('\n'):
            part = part.strip().lstrip('-').strip()
            # Remove trailing period / comma
            part = part.rstrip('.,')
            if part:
                items.append(part)
        return items

    def _parse_ingredient(self, raw: str) -> Optional[dict]:
        """
        Parse one raw Indonesian ingredient string into
        {"name": ..., "amount": ..., "unit": ...}.

        Examples:
          "4 buah pisang Ambon putih matang" -> amount="4", unit="buah", name="..."
          "Sejumput garam"                   -> amount="sejumput", unit=None, name="garam"
          "Pasta vanila secukupnya"          -> amount="secukupnya", unit=None, name="pasta vanila"
          "Margarin untuk olesan"            -> amount=None, unit="untuk olesan", name="margarin"
          "Maple sirup atau madu"            -> amount=None, unit=None, name="..."
        """
        text = self.clean_text(raw)
        if not text:
            return None

        # ---- Handle "name untuk/sebagai purpose" ----
        for prefix in PURPOSE_PREFIXES:
            idx = text.lower().find(prefix)
            if idx > 0:
                name = self.clean_text(text[:idx])
                unit = self.clean_text(text[idx:])
                return {"name": name, "amount": None, "unit": unit}

        # ---- Handle "quantity_word name" at the start ----
        for qw in sorted(QUANTITY_WORDS, key=len, reverse=True):
            if text.lower().startswith(qw):
                name = self.clean_text(text[len(qw):])
                if name:
                    return {"name": name, "amount": qw, "unit": None}

        # ---- Handle "name quantity_word" at the end ----
        for qw in sorted(QUANTITY_WORDS, key=len, reverse=True):
            if text.lower().endswith(qw):
                name = self.clean_text(text[: -len(qw)])
                if name:
                    return {"name": name, "amount": qw, "unit": None}

        # ---- Numeric amount (possibly with range or fraction) at the start ----
        # Matches: "4", "1/2", "10-12", "5-6", "250", "1.5"
        num_pattern = re.compile(
            r'^([\d]+(?:[./\-][\d]+)*(?:\s+[\d]+/[\d]+)?)\s+(.+)'
        )
        m = num_pattern.match(text)
        if m:
            amount_str = m.group(1).strip()
            rest = m.group(2).strip()

            # Check if the next token is a known unit
            unit = None
            name = rest
            for u in sorted(INDONESIAN_UNITS, key=len, reverse=True):
                pattern = re.compile(
                    r'^' + re.escape(u) + r'(?:\s|$)',
                    re.I
                )
                if pattern.match(rest):
                    unit = u
                    name = self.clean_text(rest[len(u):])
                    break

            if not name:
                name = rest
            return {"name": name, "amount": amount_str, "unit": unit}

        # ---- No pattern matched → plain name ----
        return {"name": text, "amount": None, "unit": None}

    def _collect_ingredient_paragraphs(self):
        """
        Return a list of raw ingredient paragraphs from the detail__box.

        Handles two layouts:
          1. h2 elements with "Bahan" → following <p> element
          2. <p> elements whose text starts with "Bahan:" label
          3. Older format: single <p> with "Bahan:- item1- item2..."
        """
        detail_box = self._get_detail_box()
        if not detail_box:
            return []

        bahan_paras = []
        elements = list(detail_box.children)

        i = 0
        while i < len(elements):
            el = elements[i]
            if not hasattr(el, 'get_text'):
                i += 1
                continue

            tag_name = el.name
            text = el.get_text(separator=' ', strip=True)

            # --- h2 that starts with "Bahan" (exact ingredient section) ---
            if tag_name == 'h2' and re.match(r'^Bahan\b', text, re.I):
                # Look ahead for the next <p>
                j = i + 1
                while j < len(elements):
                    nxt = elements[j]
                    if hasattr(nxt, 'name') and nxt.name == 'p':
                        bahan_paras.append(nxt.get_text(separator='', strip=True))
                        break
                    j += 1

            # --- <p> that starts with "Bahan:" label ---
            elif tag_name == 'p' and re.match(r'^Bahan\b', text, re.I):
                # Check if the paragraph itself contains items (old format)
                if '- ' in text or '-' in text:
                    bahan_paras.append(text)
                else:
                    # The label is alone; ingredients are in the next <p>
                    j = i + 1
                    while j < len(elements):
                        nxt = elements[j]
                        if hasattr(nxt, 'name') and nxt.name == 'p':
                            bahan_paras.append(nxt.get_text(separator='', strip=True))
                            break
                        j += 1

            i += 1

        return bahan_paras

    def extract_ingredients(self) -> Optional[str]:
        """Extract and parse all ingredients from the page."""
        raw_paragraphs = self._collect_ingredient_paragraphs()
        if not raw_paragraphs:
            return None

        ingredients = []
        for para in raw_paragraphs:
            items = self._split_ingredient_items(para)
            for item in items:
                parsed = self._parse_ingredient(item)
                if parsed and parsed.get('name'):
                    ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    # ------------------------------------------------------------------ instructions

    def _collect_instruction_paragraphs(self):
        """
        Return a list of step text strings from the page.

        Handles:
          1. h2 "Cara ..." followed by one or more numbered <p>
          2. <p> starting with "Cara ..." label (old format)
        """
        detail_box = self._get_detail_box()
        if not detail_box:
            return []

        step_paras = []
        elements = list(detail_box.children)

        def is_cara_header(name, text):
            if name in ('h2', 'h3', 'h4'):
                return bool(re.search(r'\bCara\b', text, re.I))
            elif name == 'p':
                # Only match "Cara" at the very start, followed by a word and colon
                # e.g. "Cara Membuat:", "Cara membuat:1. ..."
                return bool(re.match(r'^Cara\s+\w+\s*:', text, re.I))
            return False

        def is_step_paragraph(text):
            return bool(re.match(r'^\d+[\.\)]\s', text))

        i = 0
        while i < len(elements):
            el = elements[i]
            if not hasattr(el, 'get_text'):
                i += 1
                continue

            tag_name = el.name
            text = el.get_text(separator=' ', strip=True)
            if tag_name in ('h2', 'h3') and is_cara_header(tag_name, text):
                j = i + 1
                while j < len(elements):
                    nxt = elements[j]
                    if not hasattr(nxt, 'get_text'):
                        j += 1
                        continue
                    nxt_text = nxt.get_text(strip=True)
                    # Collect paragraphs that look like steps
                    if nxt.name == 'p' and is_step_paragraph(nxt_text):
                        step_paras.append(nxt_text)
                    elif nxt.name in ('h2', 'h3', 'h4'):
                        break  # new section
                    j += 1
                # If no individual step paragraphs found, get the first <p>
                if not step_paras:
                    j = i + 1
                    while j < len(elements):
                        nxt = elements[j]
                        if hasattr(nxt, 'name') and nxt.name == 'p':
                            step_paras.append(nxt.get_text(strip=True))
                            break
                        j += 1

            # --- <p> starting with "Cara" label ---
            elif tag_name == 'p' and is_cara_header(tag_name, text):
                if is_step_paragraph(text) or re.search(r'\d+\.', text):
                    step_paras.append(text)
                else:
                    # Label alone; look ahead for step paragraphs
                    j = i + 1
                    while j < len(elements):
                        nxt = elements[j]
                        if not hasattr(nxt, 'get_text'):
                            j += 1
                            continue
                        nxt_text = nxt.get_text(strip=True)
                        if nxt.name == 'p' and is_step_paragraph(nxt_text):
                            step_paras.append(nxt_text)
                        elif nxt.name in ('h2', 'h3', 'h4'):
                            break  # reached next section
                        elif nxt.name == 'p' and nxt_text:
                            if step_paras:
                                break  # already have steps, stop at non-step para
                            else:
                                # No steps yet; may be combined paragraph
                                step_paras.append(nxt_text)
                                break
                        j += 1

            i += 1

        return step_paras

    @staticmethod
    def _clean_step_text(text: str) -> str:
        """Remove leading step number (e.g. '1. ') and clean text."""
        text = re.sub(r'^\d+[\.\)]\s*', '', text)
        return text.strip()

    def _parse_combined_steps(self, text: str) -> list:
        """
        Split a single paragraph that contains multiple numbered steps
        like "1. Do A. 2. Do B. 3. Do C."
        """
        # First, split on patterns like "1. " at start (if already separate lines)
        if re.match(r'^\d+[\.\)]\s', text):
            # Split on boundaries between step numbers
            parts = re.split(r'(?=\d+[\.\)]\s)', text)
            return [self._clean_step_text(p) for p in parts if p.strip()]
        return [text]

    def extract_steps(self) -> Optional[str]:
        """Extract instructions and return as a single string."""
        raw_paras = self._collect_instruction_paragraphs()
        if not raw_paras:
            return None

        all_steps = []
        for para in raw_paras:
            para = self.clean_text(para)
            # Remove a "Cara membuat:" / "Cara Memasak:" prefix that may be inline
            para = re.sub(r'^Cara\s+\w+\s*:\s*', '', para, flags=re.I)
            steps = self._parse_combined_steps(para)
            all_steps.extend(steps)

        # Join all steps into a single string
        text = ' '.join(s for s in all_steps if s)
        return text if text else None

    # ------------------------------------------------------------------ category

    def extract_category(self) -> Optional[str]:
        """
        Try to extract category from the first paragraph prefix
        (text before the first hyperlink, appearing just after "Brilio.net -").
        Falls back to None.
        """
        detail_box = self._get_detail_box()
        if not detail_box:
            return None

        skip_patterns = re.compile(r'^foto:|^yuk\s+(ikutan|cobain)\s+bareng', re.I)

        for p in detail_box.find_all('p'):
            raw = p.get_text(separator=' ', strip=True)
            if not raw or skip_patterns.match(raw):
                continue

            # Only look at paragraphs with "Brilio.net -" prefix
            if not re.match(r'^\s*Brilio\.net\s*[-–—]', raw):
                break  # first real paragraph without the prefix → no category

            # Get text nodes before first <a> tag
            text_before_link = ''
            for child in p.children:
                if isinstance(child, NavigableString):
                    chunk = str(child).strip()
                    # Remove the "Brilio.net -" part if present
                    chunk = re.sub(r'^Brilio\.net\s*[-–—]\s*', '', chunk)
                    if chunk:
                        text_before_link += ' ' + chunk
                elif child.name in ('b', 'strong'):
                    continue  # skip bold "Brilio.net -" tag
                elif child.name == 'a':
                    break  # stop at first hyperlink

            text_before_link = self.clean_text(text_before_link)
            words = text_before_link.split()
            # Only use as category if it's 1–4 words (avoids full sentences)
            if 1 <= len(words) <= 4:
                return text_before_link

            break

        return None

    # ------------------------------------------------------------------ times

    def _extract_durasi_text(self) -> Optional[str]:
        """Return text content of the 'Durasi:' paragraph if present."""
        detail_box = self._get_detail_box()
        if not detail_box:
            return None
        for p in detail_box.find_all('p'):
            t = p.get_text(strip=True)
            if re.match(r'^Durasi\s*:', t, re.I):
                return self.clean_text(re.sub(r'^Durasi\s*:\s*', '', t, flags=re.I))
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Extract preparation time (returns None when not explicit in HTML)."""
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Extract cook time from 'Durasi:' paragraph if present."""
        return self._extract_durasi_text()

    def extract_total_time(self) -> Optional[str]:
        """Extract total time (returns None when not explicit in HTML)."""
        return None

    # ------------------------------------------------------------------ notes

    def extract_notes(self) -> Optional[str]:
        """
        Extract notes/tips from h2 sections containing 'Rahasia', 'Catatan'
        or 'Tips' keywords (excluding generic preparation/equipment sections).
        """
        detail_box = self._get_detail_box()
        if not detail_box:
            return None

        # Patterns that indicate genuine recipe notes/tips
        notes_section_pattern = re.compile(r'\b(Rahasia|Catatan|Kiat)\b', re.I)
        # "Tips Membuat" or "Tips Memasak" but NOT "Tips Mempersiapkan" (prep steps)
        tips_section_pattern = re.compile(r'\bTips\b(?!.*\bMempersiapkan\b)', re.I)
        # Patterns to skip junk lines in notes
        junk_pattern = re.compile(r'^yuk\s+(ikutan|cobain)\s+bareng|^\(brl/', re.I)

        elements = list(detail_box.children)

        def collect_section_texts(start_idx):
            texts = []
            j = start_idx
            while j < len(elements):
                nxt = elements[j]
                if not hasattr(nxt, 'get_text'):
                    j += 1
                    continue
                if nxt.name in ('h2', 'h3', 'h4'):
                    break
                nxt_text = self.clean_text(nxt.get_text(strip=True))
                if nxt.name == 'p' and nxt_text and not junk_pattern.match(nxt_text):
                    texts.append(nxt_text)
                j += 1
            return texts

        # First pass: look for dedicated Rahasia/Catatan/Kiat sections
        for i, el in enumerate(elements):
            if not hasattr(el, 'get_text'):
                continue
            tag_name = el.name
            text = el.get_text(separator=' ', strip=True)
            if tag_name in ('h2', 'h3') and notes_section_pattern.search(text):
                texts = collect_section_texts(i + 1)
                if texts:
                    return ' '.join(texts)

        # Second pass: look for Tips sections (if no Rahasia found)
        for i, el in enumerate(elements):
            if not hasattr(el, 'get_text'):
                continue
            tag_name = el.name
            text = el.get_text(separator=' ', strip=True)
            if tag_name in ('h2', 'h3') and tips_section_pattern.search(text):
                texts = collect_section_texts(i + 1)
                if texts:
                    return ' '.join(texts)

        return None

    # ------------------------------------------------------------------ tags

    def extract_tags(self) -> Optional[str]:
        """Extract tags from window.kly.gtm.tag (pipe-separated in JS)."""
        # Try JS variable first
        for script in self.soup.find_all('script'):
            text = script.string or ''
            m = re.search(r'"tag"\s*:\s*"([^"]+)"', text)
            if m:
                raw_tags = m.group(1)
                tags = [t.strip() for t in raw_tags.split('|') if t.strip()]
                if tags:
                    return ', '.join(tags)

        # Fallback: keywords in JSON-LD
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict) and 'keywords' in item:
                        kw = item['keywords']
                        if isinstance(kw, list):
                            return ', '.join(kw)
                        if isinstance(kw, str) and kw:
                            return kw
            except Exception:
                continue

        return None

    # ------------------------------------------------------------------ images

    def extract_image_urls(self) -> Optional[str]:
        """Collect all recipe image URLs from the detail__box."""
        urls = []
        seen: set = set()

        def is_valid_recipe_image(url: str) -> bool:
            """Filter out site assets, placeholders, and non-recipe images."""
            if not url or not url.startswith('http'):
                return False
            # Skip site asset images (logos, icons, placeholders)
            if '/production-assets/' in url:
                return False
            if 'blank.png' in url or 'blank.jpg' in url:
                return False
            return True

        detail_box = self._get_detail_box()
        if detail_box:
            for img in detail_box.find_all('img'):
                for attr in ('src', 'data-src'):
                    url = img.get(attr, '').strip()
                    if is_valid_recipe_image(url) and url not in seen:
                        seen.add(url)
                        urls.append(url)

        # Also capture the primary og:image
        og_img = self.soup.find('meta', property='og:image')
        if og_img:
            url = og_img.get('content', '').strip()
            if is_valid_recipe_image(url) and url not in seen:
                seen.add(url)
                urls.append(url)

        return ','.join(urls) if urls else None

    # ------------------------------------------------------------------ extract_all

    def extract_all(self) -> dict:
        """
        Extract all recipe data and return as a dict.

        Returns:
            dict with keys: dish_name, description, ingredients, instructions,
            category, prep_time, cook_time, total_time, notes, image_urls, tags.
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception as exc:
            logger.warning('extract_dish_name failed: %s', exc)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as exc:
            logger.warning('extract_description failed: %s', exc)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as exc:
            logger.warning('extract_ingredients failed: %s', exc)
            ingredients = None

        try:
            instructions = self.extract_steps()
        except Exception as exc:
            logger.warning('extract_steps failed: %s', exc)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as exc:
            logger.warning('extract_category failed: %s', exc)
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception as exc:
            logger.warning('extract_prep_time failed: %s', exc)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception as exc:
            logger.warning('extract_cook_time failed: %s', exc)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception as exc:
            logger.warning('extract_total_time failed: %s', exc)
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception as exc:
            logger.warning('extract_notes failed: %s', exc)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as exc:
            logger.warning('extract_tags failed: %s', exc)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as exc:
            logger.warning('extract_image_urls failed: %s', exc)
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
    """Entry point: process all HTML files in preprocessed/briliofood_net/."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "briliofood_net")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(BriliofoodNetExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python extractor/briliofood_net.py")


if __name__ == "__main__":
    main()
