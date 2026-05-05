"""
Extractor for naine50pluss.ee recipe pages.
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

# Estonian measurement units (full forms → canonical abbreviation)
_ET_UNITS: dict[str, str] = {
    "supilusikatäit": "sl",
    "supilusikatäied": "sl",
    "supilusikat": "sl",
    "supilusika": "sl",
    "spl": "sl",
    "sl": "sl",
    "tl": "tl",
    "teelusikatäit": "tl",
    "teelusikatäied": "tl",
    "teelusikat": "tl",
    "g": "g",
    "grammi": "g",
    "gramm": "g",
    "kg": "kg",
    "kilogrammi": "kg",
    "dl": "dl",
    "ml": "ml",
    "l": "l",
    "liitrit": "l",
    "liiter": "l",
    "tk": "tk",
    "tükki": "tk",
    "tükk": "tk",
    "tükist": "tk",
    "tk.": "tk",
    "cm": "cm",
    "mm": "mm",
    "pakk": "pakk",
    "pakki": "pakk",
    "pakist": "pakk",
    "purk": "purk",
    "purki": "purk",
    "purgist": "purk",
    "punt": "punt",
    "kl": "kl",  # glass / cup (klaas)
    "klaasi": "kl",
    "klaas": "kl",
    "viilu": "viilu",  # slice
    "viil": "viilu",
    "noaotsatäis": "noaotsatäis",
    "noaotsaga": "noaotsatäis",
}

# Regex built from _ET_UNITS keys (longest first to avoid partial matches)
_ET_UNIT_KEYS = sorted(_ET_UNITS.keys(), key=len, reverse=True)
_ET_UNIT_PATTERN = re.compile(
    r"^([\d\s/.,\u2013-]+)\s*(" + "|".join(re.escape(u) for u in _ET_UNIT_KEYS) + r")\b\s*(.+)?$",
    re.IGNORECASE,
)

# Simple number + name (no explicit unit)
_SIMPLE_AMOUNT_PATTERN = re.compile(
    r"^([\d][\d\s/.,\u2013-]*)\s+(.+)$",
)

# Patterns that indicate optional / tip items rather than core ingredients
_OPT_PREFIXES = re.compile(
    r"^(võid\b|soovitan\b|soovi korral\b|valikuline\b|proovi\b|lisa ka\b)",
    re.IGNORECASE,
)

# Unicode fraction substitutions
_FRACTION_MAP: dict[str, str] = {
    "\u00bd": "0.5",   # ½
    "\u00bc": "0.25",  # ¼
    "\u00be": "0.75",  # ¾
    "\u2153": "0.33",  # ⅓
    "\u2154": "0.67",  # ⅔
    "\u215b": "0.125", # ⅛
    "\u215c": "0.375", # ⅜
    "\u215d": "0.625", # ⅝
    "\u215e": "0.875", # ⅞
    "\u2155": "0.2",   # ⅕
    "\u2156": "0.4",   # ⅖
    "\u2157": "0.6",   # ⅗
    "\u2158": "0.8",   # ⅘
}

# Sections that indicate notes/tips rather than instructions
_NOTES_SECTION_KW = re.compile(
    r"küpsetusnipp|küpsetusnipid|variatsioon|nipid|näpunäide|soovitus|nõuanded",
    re.IGNORECASE,
)

# Sections that indicate the instructions are over
_STOP_H3_PATTERNS = re.compile(
    r"^(sama|miks|millal|küpsetusnipp|variatsioon|nipid|näpunäide|soovitus)",
    re.IGNORECASE,
)


class Naine50PlusEeExtractor(BaseRecipeExtractor):
    """Extractor for naine50pluss.ee recipe pages (WordPress / Gutenberg)."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_json_ld_graph(self) -> list:
        """Return all items from the JSON-LD @graph array, if present."""
        for script in self.soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and "@graph" in data:
                graph = data["@graph"]
                if isinstance(graph, list):
                    return graph
        return []

    def _get_blog_posting(self) -> Optional[dict]:
        """Return the BlogPosting JSON-LD item, if present."""
        for item in self._get_json_ld_graph():
            if isinstance(item, dict) and item.get("@type") == "BlogPosting":
                return item
        return None

    def _get_breadcrumb_items(self) -> list:
        """Return breadcrumb list items (each a dict with position/name)."""
        for item in self._get_json_ld_graph():
            if isinstance(item, dict) and item.get("@type") == "BreadcrumbList":
                return item.get("itemListElement", [])
        return []

    def _entry_content(self):
        """Return the main content element."""
        return self.soup.find(class_="entry-content")

    @staticmethod
    def _is_embedded_blockquote(tag) -> bool:
        """True if blockquote is an embedded post preview (not a note)."""
        classes = tag.get("class", [])
        return "wp-embedded-content" in classes

    @staticmethod
    def _normalize_ingredient_text(text: str) -> str:
        """Replace unicode fractions and normalize comma decimal separators."""
        for frac, val in _FRACTION_MAP.items():
            text = text.replace(frac, val)
        # "0,8" -> "0.8" (only digit,digit)
        text = re.sub(r"(\d),(\d)", r"\1.\2", text)
        return text

    # ------------------------------------------------------------------
    # dish_name
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Extract recipe name.

        Priority:
        1. H3 with 'retsept' keyword inside entry-content (recipe card heading).
        2. og:title stripped of site/subtitle suffixes.
        3. H1 tag stripped of subtitle.
        """
        entry = self._entry_content()
        if entry:
            for h3 in entry.find_all("h3"):
                text = h3.get_text(strip=True)
                if re.search(r"\bretsept\b", text, re.IGNORECASE):
                    # Strip trailing " retsept" if the name ends with it
                    name = re.sub(r"\s+retsept$", "", text, flags=re.IGNORECASE)
                    # Strip trailing punctuation
                    name = name.rstrip(".,;:-–—")
                    name = self.clean_text(name)
                    if name:
                        return name

        # Fallback: og:title
        og_title = self.soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"]
            # Strip site name
            title = re.sub(r"\s*[-–]\s*Naine\s*50\s*pluss\s*$", "", title, flags=re.IGNORECASE)
            # Strip `, lihtne retsept` and similar
            title = re.sub(r",?\s*lihtne\s+retsept\b.*$", "", title, flags=re.IGNORECASE)
            # Strip subtitle after " - " or " – "
            title = re.sub(r"\s*[-–]\s*.+$", "", title)
            title = title.rstrip(".,;:-")
            name = self.clean_text(title)
            if name:
                return name

        # Fallback: H1
        h1 = self.soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)
            title = re.sub(r"\s*[-–]\s*.+$", "", title)
            return self.clean_text(title) or None

        return None

    # ------------------------------------------------------------------
    # description
    # ------------------------------------------------------------------

    def extract_description(self) -> Optional[str]:
        """Extract recipe description from meta tags."""
        for selector in [
            lambda: self.soup.find("meta", property="og:description"),
            lambda: self.soup.find("meta", {"name": "description"}),
        ]:
            tag = selector()
            if tag and tag.get("content"):
                return self.clean_text(tag["content"])
        return None

    # ------------------------------------------------------------------
    # Ingredient parsing
    # ------------------------------------------------------------------

    def _parse_ingredient(self, raw: str) -> Optional[dict]:
        """Parse a single ingredient line into {name, amount, unit}."""
        text = self.clean_text(raw)
        if not text:
            return None

        # Normalize unicode fractions and comma decimals first
        text = self._normalize_ingredient_text(text)

        # Mark optional items (check before any stripping)
        is_optional = bool(_OPT_PREFIXES.match(text))
        opt_suffix = " (valikuline)" if is_optional else ""

        if is_optional:
            # Strip the leading optional phrase and filler words
            text = _OPT_PREFIXES.sub("", text).strip()
            # Strip intermediate words like "lisada ka", "prooviks lisada", "proovida ja", "ka"
            text = re.sub(
                r"^(lisada\s+ka\s+|lisada\s+|prooviks?\s+lisada\s+|proovida\s+ja\s+|ka\s+)",
                "",
                text,
                flags=re.IGNORECASE,
            ).strip()
            if not text:
                return None

        # Try structured pattern: amount + unit + name
        m = _ET_UNIT_PATTERN.match(text)
        if m:
            amount_str = m.group(1).strip().rstrip(".,")
            unit_raw = m.group(2).strip()
            unit = _ET_UNITS.get(unit_raw.lower(), unit_raw)
            name_part = (m.group(3) or "").strip()
            # Remove trailing parenthetical notes without digits from name
            name_part = re.sub(r"\s*\([^)0-9]+\)\s*$", "", name_part)
            name_part = re.sub(r"\s*\.\s*$", "", name_part).strip()
            if name_part and len(name_part) >= 2:
                # Truncate name at trailing tip/comment phrases
                name_part = re.sub(
                    r"\s*[.(]\s*(soovitan|v\u00f5id|sobivad)\b.+$",
                    "",
                    name_part,
                    flags=re.IGNORECASE,
                ).strip()
                name_part = name_part.rstrip(".,;").strip()
                amount = self._normalise_amount(amount_str)
                return {
                    "name": self.clean_text(name_part + opt_suffix),
                    "amount": amount,
                    "unit": unit,
                }
            # unit matched but no name — fall through

        # Handle "Suur punt värskeid karulaugu lehti" style
        punt_match = re.match(r"^(\w+\s+punt)\s+(.+)$", text, re.IGNORECASE)
        if punt_match:
            return {
                "name": self.clean_text(punt_match.group(2) + opt_suffix),
                "amount": punt_match.group(1),
                "unit": None,
            }

        # Handle inline parenthetical amount: "varianti vähese tšilliga (1/4 tšillikaunast)"
        paren_match = re.search(r"\((\d[\d/.,–-]*\s*\S+)\)\s*$", text)
        if paren_match:
            paren_content = paren_match.group(1).strip()
            parts = paren_content.split(None, 1)
            if len(parts) == 2:
                p_amount = self._normalise_amount(parts[0].rstrip(".,"))
                p_unit = _ET_UNITS.get(parts[1].lower(), parts[1])
                # Derive name from last significant word before the parenthetical
                before_paren = text[: paren_match.start()].strip()
                words = [w.rstrip("ga") for w in before_paren.split() if len(w) > 3]
                name_hint = words[-1] if words else before_paren
                if name_hint and len(name_hint) >= 2:
                    return {
                        "name": self.clean_text(name_hint + opt_suffix),
                        "amount": p_amount,
                        "unit": p_unit,
                    }

        # Try simple number + name (no explicit unit):
        # e.g. "1 punane paprika", "4 küüslaugu küünt"
        sm = _SIMPLE_AMOUNT_PATTERN.match(text)
        if sm:
            amount_str = sm.group(1).strip().rstrip(".,")
            name_part = sm.group(2).strip()
            # Remove trailing parenthetical notes without digits
            name_part = re.sub(r"\s*\([^)0-9]+\)\s*$", "", name_part)
            name_part = name_part.rstrip(".,;").strip()
            if name_part and len(name_part) >= 2:
                amount = self._normalise_amount(amount_str)
                return {
                    "name": self.clean_text(name_part + opt_suffix),
                    "amount": amount,
                    "unit": None,
                }

        # No amount/unit detected – whole text is the name
        # Strip trailing period before paren removal, then remove paren notes
        name = text.rstrip(".,;")
        name = re.sub(r"\s*\([^)0-9]+\)\s*$", "", name).strip()
        name = name.rstrip(".,;")
        if not name or len(name) < 2:
            return None
        return {
            "name": self.clean_text(name + opt_suffix),
            "amount": None,
            "unit": None,
        }

    @staticmethod
    def _normalise_amount(amount_str: str) -> Optional[str]:
        """Normalise amount string: strip whitespace, handle ranges."""
        if not amount_str:
            return None
        amount = amount_str.strip()
        # Replace en-dash in ranges with hyphen
        amount = amount.replace("–", "-")
        return amount if amount else None

    def extract_ingredients(self) -> Optional[str]:
        """Extract structured ingredients list as JSON string."""
        entry = self._entry_content()
        if not entry:
            return None

        ingredients: list[dict] = []
        seen_names: set[str] = set()

        # Find all ingredient section headings
        ingredient_headings = []
        for tag in entry.find_all(["h2", "h3", "h4"]):
            text = tag.get_text(strip=True).lower()
            if re.search(r"koostisosad|koostisained", text):
                ingredient_headings.append(tag)

        if not ingredient_headings:
            # Fallback: look for the first wp-block-list before any "valmistamine" heading
            for tag in entry.find_all(["h2", "h3", "h4"]):
                if re.search(r"valmistamine", tag.get_text(strip=True), re.IGNORECASE):
                    ingredient_headings = [tag.find_previous_sibling(["h2", "h3", "h4"])]
                    break

        for heading in ingredient_headings:
            if heading is None:
                continue
            # Collect all wp-block-list ULs up to the next same-level-or-higher heading
            sib = heading.find_next_sibling()
            while sib:
                tag_name = sib.name
                # Stop at h2 (or h3 if heading was h3 and not a sub-heading)
                if tag_name == "h2":
                    break
                if tag_name in ("h3", "h4") and heading.name in ("h2", "h3"):
                    # Only stop if it's a different-section heading (not a sub-ingredient group)
                    text = sib.get_text(strip=True).lower()
                    if re.search(r"valmistamine|sisukord|share", text):
                        break

                # Collect from ULs
                if tag_name == "ul":
                    ul_classes = " ".join(sib.get("class", []))
                    # Skip related-posts and navigation lists
                    if "latest-posts" in ul_classes or "block-latest" in ul_classes:
                        sib = sib.find_next_sibling()
                        continue
                    for li in sib.find_all("li"):
                        raw = li.get_text(separator=" ", strip=True)
                        # Handle comma-separated items in one li (e.g. "oil, salt, pepper")
                        # Only split if the line contains generic items without amounts
                        items = self._split_ingredient_line(raw)
                        for item_text in items:
                            parsed = self._parse_ingredient(item_text)
                            if parsed and parsed["name"].lower() not in seen_names:
                                seen_names.add(parsed["name"].lower())
                                ingredients.append(parsed)

                sib = sib.find_next_sibling()

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    @staticmethod
    def _split_ingredient_line(text: str) -> list[str]:
        """Split a li text into individual ingredient lines if comma-separated.

        Only splits when ALL parts start without a digit, and there are no
        parentheses (to avoid breaking "salsa (vürtsist, magusast)").
        """
        if "," not in text or "(" in text:
            return [text]
        parts = [p.strip() for p in text.split(",")]
        # If any part starts with a digit → treat whole item as one
        if any(re.match(r"^\d", p) for p in parts):
            return [text]
        # All parts non-digit → split into separate ingredients
        return [p for p in parts if p]

    # ------------------------------------------------------------------
    # Instructions
    # ------------------------------------------------------------------

    def extract_instructions(self) -> Optional[str]:
        """Extract cooking instructions as a single joined string."""
        entry = self._entry_content()
        if not entry:
            return None

        steps: list[str] = []

        # Find the instruction section heading
        instr_heading = None
        for tag in entry.find_all(["h2", "h3", "h4"]):
            if re.search(r"valmistamine", tag.get_text(strip=True), re.IGNORECASE):
                instr_heading = tag
                break

        if not instr_heading:
            return None

        heading_level = instr_heading.name  # h2 or h3

        sib = instr_heading.find_next_sibling()
        while sib:
            tag_name = sib.name

            # Hard stop on h2
            if tag_name == "h2":
                break

            # For h3/h4 siblings: stop if it indicates notes or new sections
            if tag_name in ("h3", "h4"):
                text = sib.get_text(strip=True)

                # Numbered step heading (e.g. "1. Kuumuta ahi") – skip heading,
                # continue collecting the following paragraphs
                if re.match(r"^\d+\.", text):
                    sib = sib.find_next_sibling()
                    continue

                if _STOP_H3_PATTERNS.search(text):
                    break
                # If the next sibling of THIS h3 is a blockquote (notes), stop
                next_of_h3 = sib.find_next_sibling()
                if next_of_h3 and next_of_h3.name == "blockquote" and not self._is_embedded_blockquote(next_of_h3):
                    break
                # Stop if followed by figure or hr (decorative section boundary)
                if next_of_h3 and next_of_h3.name in ("figure", "hr"):
                    break
                # Skip h3 that has a following paragraph (it's just a step heading)
                if next_of_h3 and next_of_h3.name == "p":
                    sib = sib.find_next_sibling()
                    continue
                # Include h3 text as an instruction step (e.g., storage conclusion)
                step_text = self.clean_text(text)
                if step_text and step_text not in steps:
                    steps.append(step_text)
                sib = sib.find_next_sibling()
                continue

            # Skip blockquotes (notes) and social sharing, TOC
            if tag_name == "blockquote":
                break
            if tag_name == "div":
                cls_list = sib.get("class", [])
                cls_str = " ".join(cls_list)
                if "rank-math-toc" in cls_str or "sharedaddy" in cls_str:
                    break
                # wp-block-media-text contains instruction UL
                if "wp-block-media-text" in cls_str:
                    for li in sib.find_all("li"):
                        step = self.clean_text(li.get_text(separator=" ", strip=True))
                        if step:
                            steps.append(step)
                    sib = sib.find_next_sibling()
                    continue
                # Otherwise skip the div
                sib = sib.find_next_sibling()
                continue

            # Paragraph → instruction step
            if tag_name == "p":
                text = self.clean_text(sib.get_text(separator=" ", strip=True))
                if text and not self._is_promo_text(text):
                    steps.append(text)

            # OL/UL → numbered steps
            if tag_name in ("ol", "ul"):
                for li in sib.find_all("li"):
                    step = self.clean_text(li.get_text(separator=" ", strip=True))
                    if step and not self._is_promo_text(step):
                        steps.append(step)

            sib = sib.find_next_sibling()

        if not steps:
            return None

        return " ".join(steps)

    @staticmethod
    def _is_promo_text(text: str) -> bool:
        """Return True if the text is a promo/link-out text, not an instruction."""
        promo_patterns = [
            r"leiad siit",
            r"e-raamat",
            r"minu (uue|uhiuue|maitsvate|uhiuue)",
            r"retsepti leiad",
            r"vaata siit",
            r"vaata\s+\w+\s+(retsept|koogi|tordi|k\u00fcpse)",
            r"ostunimekirjaga",
            r"tellimuse kinnituse",
            r"veel ideesid",
            r"pidulikke retsepte minu",
        ]
        tl = text.lower()
        return any(re.search(p, tl) for p in promo_patterns)

    # ------------------------------------------------------------------
    # Category
    # ------------------------------------------------------------------

    def extract_category(self) -> Optional[str]:
        """Extract category from BreadcrumbList (3rd crumb when 4+ crumbs exist)."""
        crumbs = self._get_breadcrumb_items()
        if len(crumbs) < 4:
            # Only Home → Retseptid → PageTitle → no subcategory
            return None
        # crumbs[2] is position 3 (the sub-category)
        third = crumbs[2]
        name = third.get("item", {}).get("name") or third.get("name")
        if name:
            return self.clean_text(name) or None
        return None

    # ------------------------------------------------------------------
    # Times
    # ------------------------------------------------------------------

    def _extract_time_from_text(self) -> Optional[str]:
        """Look for 'Valmistamise aeg X min' pattern in content."""
        entry = self._entry_content()
        if not entry:
            return None
        # Time pattern with en-dash (U+2013) for ranges like "25–30"
        time_re = re.compile(
            r"valmistamise\s+aeg\s+([\d\s.,/\u2013-]+\s*(?:minut|min|tunni?|tund)(?:it|i)?)",
            re.IGNORECASE,
        )
        for p in entry.find_all("p"):
            text = p.get_text(strip=True)
            m = time_re.search(text)
            if m:
                return self._normalise_time(m.group(1))
        return None

    def _extract_time_from_title(self) -> Optional[str]:
        """Look for 'X min retsept' in H1 or og:title."""
        title_re = re.compile(r"([\d\s.,/\u2013-]+)\s*min\b", re.IGNORECASE)
        for tag in [
            self.soup.find("h1"),
            self.soup.find("meta", property="og:title"),
        ]:
            if tag is None:
                continue
            text = tag.get_text(strip=True) if tag.name != "meta" else tag.get("content", "")
            m = title_re.search(text)
            if m:
                return self._normalise_time(m.group(1) + " min")
        return None

    def _extract_cook_time_from_instructions(self) -> Optional[str]:
        """Look for 'Küpseta ... X minutit' in instructions text."""
        entry = self._entry_content()
        if not entry:
            return None
        # Pattern: küpseta ... digits (en-dash/hyphen) ... minut
        # Use non-raw string so \u00fc and \u2013 are actual Unicode chars
        cook_re = re.compile(
            "k\u00fcpseta[^.]*?(\\d[\\d.,/\u2013-]+)\\s*(?:minut|min)",
            re.IGNORECASE,
        )
        for p in entry.find_all("p"):
            text = p.get_text(strip=True)
            m = cook_re.search(text)
            if m:
                return self._normalise_time(m.group(1) + " minutit")
        return None

    @staticmethod
    def _normalise_time(raw: str) -> Optional[str]:
        """Normalise a time string to 'X minutes' or 'X-Y minutes'."""
        raw = raw.strip()
        # Replace en-dash (U+2013) ranges with hyphen
        raw = raw.replace("\u2013", "-")
        # Check for hours
        h_match = re.search(r"(\d+)\s*(?:tunni?|tund|h)\b", raw, re.IGNORECASE)
        m_match = re.search(r"([\d.,-]+)\s*min", raw, re.IGNORECASE)
        if h_match and m_match:
            hours = int(h_match.group(1))
            mins_str = m_match.group(1).strip()
            try:
                mins = int(mins_str)
                total = hours * 60 + mins
                return f"{total} minutes"
            except ValueError:
                pass
        if h_match and not m_match:
            hours = int(h_match.group(1))
            return f"{hours * 60} minutes"
        if m_match:
            mins_str = m_match.group(1).strip().rstrip(".,")
            # Range like "25-30"
            if "-" in mins_str:
                return f"{mins_str} minutes"
            try:
                mins = int(float(mins_str.replace(",", ".")))
                return f"{mins} minutes"
            except ValueError:
                return f"{mins_str} minutes"
        # Just a number
        num = re.search(r"(\d+)", raw)
        if num:
            return f"{num.group(1)} minutes"
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Extract cook/preparation time."""
        return (
            self._extract_time_from_text()
            or self._extract_cook_time_from_instructions()
            or self._extract_time_from_title()
        )

    def extract_prep_time(self) -> Optional[str]:
        """Prep time – not separately available on this site."""
        return None

    def extract_total_time(self) -> Optional[str]:
        """Total time – same as cook time when no prep time."""
        cook = self.extract_cook_time()
        return cook  # total == cook when no separate prep time

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------

    def extract_notes(self) -> Optional[str]:
        """Extract tips, notes, and variations."""
        entry = self._entry_content()
        if not entry:
            return None

        note_parts: list[str] = []
        seen_notes: set[str] = set()

        def _add_note(text: str) -> None:
            t = self.clean_text(text)
            if not t:
                return
            # Filter out tag-cloud paragraphs (very long, no sentence endings)
            if len(t) > 300 and "." not in t:
                return
            key = t[:80].lower()
            if key not in seen_notes and not self._is_promo_text(t):
                seen_notes.add(key)
                note_parts.append(t)

        # 1. Blockquotes that directly follow STOP-type h3 headings
        # (e.g. h3 "Sama pestot saab valmistada..." → NB! blockquote after it)
        for heading in entry.find_all(["h3", "h4"]):
            h_text = heading.get_text(strip=True)
            if not (_STOP_H3_PATTERNS.search(h_text)
                    or re.search(r"\bsama\b", h_text, re.IGNORECASE)):
                continue
            next_sib = heading.find_next_sibling()
            if (next_sib and next_sib.name == "blockquote"
                    and not self._is_embedded_blockquote(next_sib)):
                text = next_sib.get_text(separator=" ", strip=True)
                text = re.sub(r"^NB!\s*", "", text).strip()
                _add_note(text)

        # 2. h2 sections with nipp/variatsioon/soovitus keywords
        # (only h2 to avoid promotional h3 sub-sections)
        for heading in entry.find_all("h2"):
            h_text = heading.get_text(strip=True)
            if not _NOTES_SECTION_KW.search(h_text):
                continue
            sib = heading.find_next_sibling()
            while sib:
                if sib.name in ("h2", "h3"):
                    break
                if sib.name in ("ul", "ol"):
                    ul_classes = " ".join(sib.get("class", []))
                    # Skip related-posts / navigation lists
                    if "latest-posts" in ul_classes or "block-latest" in ul_classes:
                        sib = sib.find_next_sibling()
                        continue
                    for li in sib.find_all("li"):
                        _add_note(li.get_text(separator=" ", strip=True))
                elif sib.name == "p":
                    _add_note(sib.get_text(separator=" ", strip=True))
                elif sib.name == "blockquote" and not self._is_embedded_blockquote(sib):
                    text = sib.get_text(separator=" ", strip=True)
                    text = re.sub(r"^NB!\s*", "", text).strip()
                    _add_note(text)
                sib = sib.find_next_sibling()

        if not note_parts:
            return None

        return ". ".join(note_parts).rstrip(".") + "."

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def extract_tags(self) -> Optional[str]:
        """Extract tags from BlogPosting.keywords in JSON-LD."""
        blog = self._get_blog_posting()
        if not blog:
            return None
        keywords = blog.get("keywords")
        if not keywords:
            return None
        # keywords may be comma-separated string
        tags = [t.strip().lower() for t in str(keywords).split(",") if t.strip()]
        return ", ".join(tags) if tags else None

    # ------------------------------------------------------------------
    # Image URLs
    # ------------------------------------------------------------------

    def extract_image_urls(self) -> Optional[str]:
        """Extract image URLs from og:image and JSON-LD ImageObject."""
        urls: list[str] = []

        og_image = self.soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            urls.append(og_image["content"])

        for item in self._get_json_ld_graph():
            if not isinstance(item, dict):
                continue
            if item.get("@type") == "ImageObject":
                url = item.get("url") or item.get("@id") or ""
                # Strip HTML entities
                url = url.replace("&amp;", "&")
                if url and url not in urls:
                    urls.append(url)

        if not urls:
            return None

        # Deduplicate preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                unique.append(u)

        return ",".join(unique)

    # ------------------------------------------------------------------
    # extract_all
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """Extract all recipe fields and return as a dict."""
        try:
            dish_name = self.extract_dish_name()
        except Exception:
            logger.exception("Error extracting dish_name from %s", self.html_path)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception:
            logger.exception("Error extracting description from %s", self.html_path)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception:
            logger.exception("Error extracting ingredients from %s", self.html_path)
            ingredients = None

        try:
            instructions = self.extract_instructions()
        except Exception:
            logger.exception("Error extracting instructions from %s", self.html_path)
            instructions = None

        try:
            category = self.extract_category()
        except Exception:
            logger.exception("Error extracting category from %s", self.html_path)
            category = None

        try:
            notes = self.extract_notes()
        except Exception:
            logger.exception("Error extracting notes from %s", self.html_path)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception:
            logger.exception("Error extracting tags from %s", self.html_path)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception:
            logger.exception("Error extracting image_urls from %s", self.html_path)
            image_urls = None

        try:
            prep_time = self.extract_prep_time()
        except Exception:
            logger.exception("Error extracting prep_time from %s", self.html_path)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception:
            logger.exception("Error extracting cook_time from %s", self.html_path)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception:
            logger.exception("Error extracting total_time from %s", self.html_path)
            total_time = None

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


def main() -> None:
    """Process all HTML files in the preprocessed/naine50pluss_ee directory."""
    import os

    repo_root = Path(__file__).parent.parent
    recipes_dir = repo_root / "preprocessed" / "naine50pluss_ee"

    if recipes_dir.exists() and recipes_dir.is_dir():
        process_directory(Naine50PlusEeExtractor, str(recipes_dir))
    else:
        print(f"Directory not found: {recipes_dir}")
        print("Usage: python extractor/naine50pluss_ee.py")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
