"""
Экстрактор данных рецептов для сайта szajtatva.blogspot.com

Блог на платформе Blogger (blogspot.com) с рецептами на венгерском языке.
Поддерживает два формата вёрстки:
  1. Формат MS Word (div.MsoNormal) — каждая строка в отдельном div
  2. Плоский формат (span+br) — строки разделены тегами <br>
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

# Венгерские единицы измерения (строчные ключи)
_HU_UNITS: Dict[str, str] = {
    # weight
    "dkg": "dkg", "dekagramm": "dkg", "dekagram": "dkg",
    "kg": "kg", "kilogramm": "kg",
    "g": "g", "gramm": "g",
    # volume
    "dl": "dl", "deciliter": "dl",
    "ml": "ml", "milliliter": "ml",
    "l": "l", "liter": "l",
    # cooking spoons
    "evőkanál": "evőkanál", "evőkanálnyi": "evőkanál",
    "teáskanál": "teáskanál", "teáskanálnyi": "teáskanál",
    "kanálnyi": "kanálnyi", "kanál": "kanál",
    # countable
    "db": "db", "darab": "db",
    "fej": "fej",
    "szál": "szál",
    "szelet": "szelet",
    "gerezd": "gerezd",
    "cső": "cső",
    "csomag": "csomag",
    "csokor": "csokor",
    "csipet": "csipet",
    "tenyérnyi": "tenyérnyi",
    "rúd": "rúd",
    "marék": "marék",
    "közepes": "közepes",
    "nagy": "nagy",
    "kis": "kis",
}

# Regex for recognising a unit token
_UNIT_PATTERN = "|".join(re.escape(u) for u in sorted(_HU_UNITS.keys(), key=len, reverse=True))

# Венгерские числительные, используемые в рецептах
_HU_NUMBERS: Dict[str, str] = {
    "egy": "1",
    "két": "2",
    "három": "3",
    "négy": "4",
    "öt": "5",
    "hat": "6",
    "hét": "7",
    "nyolc": "8",
    "kilenc": "9",
    "tíz": "10",
    "fél": "0.5",
    "negyed": "0.25",
    "félcsomag": "0.5",
}


class SzajtatvaBlogspotComExtractor(BaseRecipeExtractor):
    """Экстрактор для szajtatva.blogspot.com (венгерский кулинарный блог на Blogger)."""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_post_body(self):
        """Return the main post-body div or None."""
        return self.soup.find("div", class_="post-body")

    def _get_text_lines(self) -> List[str]:
        """
        Extract ordered text lines from the post body.

        Supports two layouts:
        - MsoNormal (Word-pasted): each div.MsoNormal is one line.
        - Flat (span+br): br tags act as line separators.
        """
        post_body = self._get_post_body()
        if not post_body:
            logger.warning("post-body div not found")
            return []

        # Try MsoNormal layout first
        mso_divs = post_body.find_all("div", class_="MsoNormal")
        if mso_divs:
            lines = []
            for div in mso_divs:
                text = div.get_text(separator=" ", strip=True)
                text = re.sub(r"\s+", " ", text).strip()
                if text:
                    lines.append(text)
            return lines

        # Flat layout: replace <br> with newlines, then parse text
        raw_html = str(post_body)
        raw_html = re.sub(r"<br\s*/?>", "\n", raw_html, flags=re.IGNORECASE)
        from bs4 import BeautifulSoup as _BS
        flat_soup = _BS(raw_html, "lxml")
        full_text = flat_soup.get_text(separator="\n")
        lines = []
        for line in full_text.split("\n"):
            line = re.sub(r"\s+", " ", line).strip()
            if line:
                lines.append(line)
        return lines

    @staticmethod
    def _is_section_header(line: str) -> bool:
        """True if *line* is a known recipe section header (Hozzávalók / Elkészítés)."""
        normalized = line.strip().rstrip(":").strip().lower()
        return any(
            normalized.startswith(kw)
            for kw in ("hozzávaló", "elkészítés", "megjegyzés", "tipp")
        )

    @staticmethod
    def _is_ingredients_header(line: str) -> bool:
        return line.strip().lower().startswith("hozzávaló")

    @staticmethod
    def _is_instructions_header(line: str) -> bool:
        return line.strip().lower().startswith("elkészítés")

    @staticmethod
    def _is_notes_header(line: str) -> bool:
        normalized = line.strip().lower()
        return normalized.startswith("megjegyzés") or normalized.startswith("tipp")

    @staticmethod
    def _is_numbered_step(line: str) -> bool:
        """True if line looks like a numbered instruction step (e.g. '1. ...')."""
        return bool(re.match(r"^\d+\.\s+\S", line))

    @staticmethod
    def _is_ingredient_line(line: str) -> bool:
        """Heuristic: short lines (≤100 chars) that are NOT numbered steps or section headers."""
        if SzajtatvaBlogspotComExtractor._is_section_header(line):
            return False
        if SzajtatvaBlogspotComExtractor._is_numbered_step(line):
            return False
        return len(line) <= 100

    # ------------------------------------------------------------------
    # Ingredient parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_hu_amount(text: str) -> str:
        """Replace Hungarian number words with digits and normalise whitespace."""
        text = text.strip()
        # Replace nbsp and extra spaces
        text = re.sub(r"[\xa0\u202f]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        lower = text.lower()
        # Handle "egy fél" = one half = 0.5 before replacing individual words
        lower = re.sub(r"\begy\s+fél\b", "0.5", lower)
        for word, digit in _HU_NUMBERS.items():
            # word-boundary replacement
            lower = re.sub(r"\b" + re.escape(word) + r"\b", digit, lower)
        # Collapse "1 0.5" style artefacts back to "0.5" if it still appears
        lower = re.sub(r"\b1\s+0\.5\b", "0.5", lower)
        # remove leading "kb." / "kb " (approximately)
        lower = re.sub(r"^kb\.?\s*", "", lower).strip()
        return lower

    @staticmethod
    def _parse_ingredient(line: str) -> Optional[Dict[str, Any]]:
        """
        Parse a single ingredient line into {name, amount, unit}.

        Supports two main formats:
          A) "name (amount unit)"  — kimchi-style
          B) "amount unit name"    — kolumbiai-style / mákos-style
        """
        line = re.sub(r"[\xa0\u202f]", " ", line)
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            return None

        # ---- Format A: "name (...amount unit...)" ----
        # Look for the LAST parenthesised group at the end of the line
        paren_match = re.search(
            r"^(.+?)\s*\(([^()]+)\)\s*$",
            line,
            re.UNICODE,
        )
        if paren_match:
            name_part = paren_match.group(1).strip().rstrip(",").strip()
            inside = paren_match.group(2).strip()
            # Inside may look like "20-25 dkg" or "kb. 1 tenyérnyi" or "csilipaprikakrém"
            # Require at least one digit in the amount (avoid matching stray ".")
            unit_match = re.search(
                r"(\d[\d.,/\-]*(?:\s\d[\d.,/\-]*)*)\s*(" + _UNIT_PATTERN + r")\b",
                inside,
                re.IGNORECASE | re.UNICODE,
            )
            if unit_match:
                amount = SzajtatvaBlogspotComExtractor._normalize_hu_amount(
                    unit_match.group(1)
                )
                # Keep the original unit string as found in the text (not normalised)
                unit = unit_match.group(2)
                return {"name": name_part, "amount": amount or None, "unit": unit}
            # Check for Hungarian number word + unit inside parens
            hu_unit_match = re.search(
                r"([a-záéíóöőúüű\d.,/\-\s]+?)\s+(" + _UNIT_PATTERN + r")\b",
                inside,
                re.IGNORECASE | re.UNICODE,
            )
            if hu_unit_match:
                raw_amount = SzajtatvaBlogspotComExtractor._normalize_hu_amount(
                    hu_unit_match.group(1)
                )
                unit = hu_unit_match.group(2)
                return {"name": name_part, "amount": raw_amount or None, "unit": unit}
            # Inside parens might just be extra description (e.g. "koreaiul: dubu")
            # Fall through to format B for this line

        # ---- Format B: "amount unit name" ----
        # Try digit + optional decimal/range + unit + name
        # Require at least one leading digit
        digit_unit_re = re.compile(
            r"^(\d[\d.,/\-]*(?:[–\-]\d[\d.,/\-]*)?)\s*(" + _UNIT_PATTERN + r")\b\s*(.*)",
            re.IGNORECASE | re.UNICODE,
        )
        m = digit_unit_re.match(line)
        if m:
            amount = SzajtatvaBlogspotComExtractor._normalize_hu_amount(m.group(1))
            unit = m.group(2)
            name = m.group(3).strip()
            return {"name": name, "amount": amount or None, "unit": unit}

        # Try Hungarian number word + unit + name
        hu_amount_re = re.compile(
            r"^((?:" + "|".join(re.escape(k) for k in sorted(_HU_NUMBERS.keys(), key=len, reverse=True))
            + r")(?:\s+(?:" + "|".join(re.escape(k) for k in sorted(_HU_NUMBERS.keys(), key=len, reverse=True))
            + r"))?)\s+(" + _UNIT_PATTERN + r")\b\s*(.*)",
            re.IGNORECASE | re.UNICODE,
        )
        m2 = hu_amount_re.match(line)
        if m2:
            amount = SzajtatvaBlogspotComExtractor._normalize_hu_amount(m2.group(1))
            unit = m2.group(2)
            name = m2.group(3).strip()
            return {"name": name, "amount": amount or None, "unit": unit}

        # Try digit + name (no unit)
        digit_name_re = re.compile(
            r"^(\d[\d.,/\-]*(?:[–\-]\d[\d.,/\-]*)?)\s+(.*)",
            re.UNICODE,
        )
        m3 = digit_name_re.match(line)
        if m3:
            amount = SzajtatvaBlogspotComExtractor._normalize_hu_amount(m3.group(1))
            name = m3.group(2).strip()
            if name:
                return {"name": name, "amount": amount or None, "unit": None}

        # Try Hungarian number word + name (no unit)
        hu_nounit_re = re.compile(
            r"^((?:" + "|".join(re.escape(k) for k in sorted(_HU_NUMBERS.keys(), key=len, reverse=True))
            + r")(?:\s+(?:" + "|".join(re.escape(k) for k in sorted(_HU_NUMBERS.keys(), key=len, reverse=True))
            + r"))?)\s+(.*)",
            re.IGNORECASE | re.UNICODE,
        )
        m4 = hu_nounit_re.match(line)
        if m4:
            amount = SzajtatvaBlogspotComExtractor._normalize_hu_amount(m4.group(1))
            name = m4.group(2).strip()
            if name and len(name) > 1:
                return {"name": name, "amount": amount or None, "unit": None}

        # Name only (e.g. "só", "bors")
        return {"name": line.strip().rstrip(",").strip(), "amount": None, "unit": None}

    # ------------------------------------------------------------------
    # Section partitioning
    # ------------------------------------------------------------------

    # Minimum character length for a line to be considered an instruction paragraph
    _INSTRUCTION_MIN_LEN = 130

    def _partition_content(
        self,
    ) -> Tuple[str, List[str], List[str], List[str]]:
        """
        Split text lines into (description, ingredient_lines, instruction_lines, note_lines).

        Handles three layouts:
        - Explicit headers ("Hozzávalók:" and "Elkészítés:") — kimchi style
        - Ingredients followed by numbered steps — kolumbiai style
        - Ingredients followed by plain paragraphs (no explicit instruction header) — mákos style
        """
        lines = self._get_text_lines()
        if not lines:
            return ("", [], [], [])

        description_parts: List[str] = []
        ingredient_lines: List[str] = []
        instruction_lines: List[str] = []
        note_lines: List[str] = []
        # Buffer for post-ingredient ambiguous lines (no Elkészítés: header)
        post_ingr_buffer: List[str] = []

        STATE_DESC = "desc"
        STATE_INGR = "ingr"
        STATE_INST = "inst"
        STATE_NOTES = "notes"
        STATE_POST_INGR = "post_ingr"  # long lines after ingredients (no explicit header)

        state = STATE_DESC

        for line in lines:
            if self._is_ingredients_header(line):
                state = STATE_INGR
                continue
            if self._is_instructions_header(line):
                # Flush post_ingr_buffer as notes (they were before the header)
                note_lines.extend(post_ingr_buffer)
                post_ingr_buffer = []
                state = STATE_INST
                continue
            if self._is_notes_header(line):
                state = STATE_NOTES
                continue

            if state == STATE_DESC:
                description_parts.append(line)

            elif state == STATE_INGR:
                if self._is_numbered_step(line):
                    # Numbered steps immediately follow ingredients → instructions
                    state = STATE_INST
                    instruction_lines.append(line)
                elif self._is_ingredient_line(line):
                    ingredient_lines.append(line)
                else:
                    # Line is too long to be an ingredient; collect for later classification
                    post_ingr_buffer.append(line)
                    state = STATE_POST_INGR

            elif state == STATE_POST_INGR:
                # Accumulate all post-ingredient content; classify at the end
                post_ingr_buffer.append(line)

            elif state == STATE_INST:
                instruction_lines.append(line)

            elif state == STATE_NOTES:
                note_lines.append(line)

        # Classify post_ingr_buffer: short paragraphs are notes; long ones are instructions
        if post_ingr_buffer and not instruction_lines:
            # Find the first long instruction paragraph
            first_inst_idx = -1
            for i, buf_line in enumerate(post_ingr_buffer):
                if len(buf_line) >= self._INSTRUCTION_MIN_LEN:
                    first_inst_idx = i
                    break
            if first_inst_idx >= 0:
                note_lines.extend(post_ingr_buffer[:first_inst_idx])
                instruction_lines.extend(post_ingr_buffer[first_inst_idx:])
            else:
                # All short — treat all as notes
                note_lines.extend(post_ingr_buffer)
        elif post_ingr_buffer:
            # We already have explicit instructions; short buffer lines go to notes
            for buf_line in post_ingr_buffer:
                if len(buf_line) < self._INSTRUCTION_MIN_LEN:
                    note_lines.append(buf_line)
                else:
                    instruction_lines.append(buf_line)

        # If we never saw a Hozzávalók header but found numbered steps in description,
        # separate them out
        if not ingredient_lines and not instruction_lines:
            new_desc: List[str] = []
            for line in description_parts:
                if self._is_numbered_step(line):
                    instruction_lines.append(line)
                else:
                    new_desc.append(line)
            description_parts = new_desc

        description = " ".join(description_parts).strip()
        description = re.sub(r"\s+", " ", description).strip()

        return description, ingredient_lines, instruction_lines, note_lines

    # ------------------------------------------------------------------
    # Public extraction methods
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Extract dish name from h3.post-title or page <title>."""
        try:
            # Blogger post title
            h3 = self.soup.find("h3", class_="post-title")
            if h3:
                return self.clean_text(h3.get_text())

            h1 = self.soup.find("h1", class_="post-title")
            if h1:
                return self.clean_text(h1.get_text())

            # Fall back to <title> tag (remove blog name)
            title_tag = self.soup.find("title")
            if title_tag:
                title = title_tag.get_text(strip=True)
                # Strip common Blogger suffixes like " - Szájtátva"
                title = re.sub(r"\s*[-–|]\s*[^-–|]+$", "", title).strip()
                if title:
                    return self.clean_text(title)
        except Exception as exc:
            logger.warning("Error extracting dish name: %s", exc)
        return None

    def extract_description(self) -> Optional[str]:
        """Extract recipe intro/description (first paragraph before Hozzávalók)."""
        try:
            # Prefer og:description if it's not truncated
            og_desc = self.soup.find("meta", property="og:description")
            if og_desc and og_desc.get("content"):
                text = self.clean_text(og_desc["content"])
                # Blogger og:description is often truncated with "..."
                # Use it only if it doesn't end with an ellipsis
                if text and not text.endswith("..."):
                    return text

            description, _, _, _ = self._partition_content()
            if description:
                return self.clean_text(description)
        except Exception as exc:
            logger.warning("Error extracting description: %s", exc)
        return None

    def extract_ingredients(self) -> Optional[str]:
        """Extract and parse ingredient list as JSON string."""
        try:
            _, ingredient_lines, _, _ = self._partition_content()
            if not ingredient_lines:
                return None

            ingredients: List[Dict[str, Any]] = []
            # In MsoNormal layout some lines span multiple display-lines joined by '\n'.
            # We join them before parsing.
            for raw_line in ingredient_lines:
                # Normalise internal newlines (MsoNormal multi-line names)
                line = re.sub(r"\s*\n\s*", " ", raw_line)
                line = re.sub(r"\s+", " ", line).strip()
                if not line:
                    continue
                parsed = self._parse_ingredient(line)
                if parsed and parsed.get("name"):
                    # Clean name
                    parsed["name"] = self.clean_text(parsed["name"])
                    ingredients.append(parsed)

            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
        except Exception as exc:
            logger.warning("Error extracting ingredients: %s", exc)
        return None

    def extract_steps(self) -> Optional[str]:
        """Extract cooking instructions as a single formatted string."""
        try:
            _, _, instruction_lines, _ = self._partition_content()
            if not instruction_lines:
                return None

            # Patterns to skip: Blogger image captions, social CTAs, etc.
            skip_patterns = re.compile(
                r"^(felirat hozzáadása|jó étvágyat|bon provecho|kövess|like|follow|"
                r"forrás:|source:)",
                re.IGNORECASE,
            )

            steps: List[str] = []
            for line in instruction_lines:
                text = re.sub(r"\s+", " ", line).strip()
                if text and not skip_patterns.match(text):
                    steps.append(text)

            if not steps:
                return None

            # If steps are already numbered ("1. ..."), join with newline
            if self._is_numbered_step(steps[0]):
                return "\n".join(steps)

            # Otherwise number them
            numbered = [f"{i}. {s}" for i, s in enumerate(steps, 1)]
            return "\n".join(numbered)
        except Exception as exc:
            logger.warning("Error extracting steps: %s", exc)
        return None

    def extract_category(self) -> Optional[str]:
        """Category is not available in the raw HTML of this blog."""
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Prep time is not available in the raw HTML of this blog."""
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Extract cook time from instruction text using Hungarian time patterns."""
        try:
            _, _, instruction_lines, _ = self._partition_content()
            instructions_text = " ".join(instruction_lines)
            return self._extract_time_from_text(instructions_text)
        except Exception as exc:
            logger.warning("Error extracting cook time: %s", exc)
        return None

    def extract_total_time(self) -> Optional[str]:
        """Total time is not available in the raw HTML of this blog."""
        return None

    def extract_notes(self) -> Optional[str]:
        """Extract notes/tips that appear between ingredients and instructions."""
        try:
            _, _, _, note_lines = self._partition_content()
            if not note_lines:
                return None

            # Filter out obviously non-note lines (captions, social CTAs, etc.)
            ignored_patterns = re.compile(
                r"^(felirat hozzáadása|jó étvágyat|bon provecho|kövess|like|follow)",
                re.IGNORECASE,
            )
            filtered = [
                line for line in note_lines
                if not ignored_patterns.match(line.strip())
            ]
            if not filtered:
                return None

            return self.clean_text(" ".join(filtered))
        except Exception as exc:
            logger.warning("Error extracting notes: %s", exc)
        return None

    def extract_tags(self) -> Optional[str]:
        """Extract Blogger post labels as comma-separated tags."""
        try:
            label_links = self.soup.find_all("a", rel="tag")
            if not label_links:
                return None
            tags = [self.clean_text(a.get_text()) for a in label_links if a.get_text(strip=True)]
            tags = [t for t in tags if t]
            return ", ".join(tags) if tags else None
        except Exception as exc:
            logger.warning("Error extracting tags: %s", exc)
        return None

    def extract_image_urls(self) -> Optional[str]:
        """Extract image URLs from the post body (Blogger CDN images)."""
        try:
            post_body = self._get_post_body()
            if not post_body:
                return None

            # Normalise a blogger image URL to a canonical form for deduplication
            def _canonical(url: str) -> str:
                # Strip size suffix like /sXXX/ or /wXXX-hYYY-p-k-no-nu/ to get base ID
                return re.sub(r"/[swh]\d+[^/]*/([^/]+)$", r"/\1", url)

            seen_canonical: set = set()
            urls: List[str] = []

            def _add_url(url: str) -> None:
                if not url or "blogger.googleusercontent.com" not in url:
                    return
                # Prefer high-res (s1600)
                hires = re.sub(r"/s\d+/", "/s1600/", url)
                canon = _canonical(hires)
                if canon not in seen_canonical:
                    seen_canonical.add(canon)
                    urls.append(hires)

            for img in post_body.find_all("img"):
                src = img.get("src") or img.get("data-src") or ""
                _add_url(src)

            # Also pull from JSON-LD BlogPosting image
            for script in self.soup.find_all("script", type="application/ld+json"):
                try:
                    if not script.string:
                        continue
                    data = json.loads(script.string)
                    img_data = data.get("image")
                    if isinstance(img_data, dict):
                        url = img_data.get("url", "")
                    elif isinstance(img_data, str):
                        url = img_data
                    else:
                        url = ""
                    _add_url(url)
                except (json.JSONDecodeError, AttributeError):
                    continue

            return ",".join(urls) if urls else None
        except Exception as exc:
            logger.warning("Error extracting image_urls: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Time helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_time_from_text(text: str) -> Optional[str]:
        """
        Find the most prominent cooking time mention in *text*.

        Patterns handled (Hungarian):
          - "50-55 perc alatt"
          - "40 percig"
          - "negyedóráig" (= 15 minutes)
          - "7 percig"
        Returns e.g. "50-55 minutes", "40 minutes".
        """
        if not text:
            return None

        # Named time mentions (negyedóra = quarter hour, háromnegyed = 45 min)
        named = {
            r"negyedóra": "15",
            r"háromnegyed\s*óra": "45",
            r"félóra": "30",
        }
        for pattern, minutes in named.items():
            if re.search(pattern, text, re.IGNORECASE):
                return f"{minutes} minutes"

        # Numeric patterns: "X perc" / "X-Y perc"
        matches = re.findall(
            r"(\d+(?:[–\-]\d+)?)\s*perc",
            text,
            re.IGNORECASE,
        )
        if not matches:
            return None

        # If a range like "50-55" is found, return it as-is
        for m in matches:
            if re.search(r"\d+[–\-]\d+", m):
                return f"{m} minutes"

        # Otherwise return the largest single value (main cooking step)
        values = [int(m) for m in matches if m.isdigit()]
        if values:
            return f"{max(values)} minutes"

        return None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """Extract all recipe data from the HTML page."""
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags(),
        }


def main() -> None:
    """Entry point: process all HTML files in preprocessed/szajtatva_blogspot_com."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "szajtatva_blogspot_com")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(SzajtatvaBlogspotComExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python szajtatva_blogspot_com.py")


if __name__ == "__main__":
    main()
