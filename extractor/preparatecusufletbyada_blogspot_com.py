"""
Recipe data extractor for preparatecusufletbyada.blogspot.com

A Romanian food blog (Blogger platform) with a simple, flat HTML structure:
- Post title in h1.post-title / h1.entry-title
- Post body in div.post-body containing text nodes separated by <br> tags
- Ingredients section delimited by "Ingrediente:" header
- Instructions section delimited by "Mod de preparare" header
- End of recipe marked by "Poftă bună!" / "Pofta buna!"
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bs4 import NavigableString

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


# Romanian measurement units (sorted longest-first to ensure greedy matching)
_ROMANIAN_UNITS: List[str] = sorted(
    [
        "kilograme", "kilogram",
        "mililitri", "mililitru",
        "lingurițe", "lingurite", "linguriță",
        "linguri", "lingura", "lingură",
        "cubulete", "cubuleț",
        "bucăți", "bucata", "bucată",
        "plicuri", "plic",
        "fiole", "fiolă", "fiola",
        "cani", "cana",
        "grame", "gram",
        "litri", "litru",
        "kg", "gr", "ml", "dl",
        "g", "l",
    ],
    key=len,
    reverse=True,
)

# Pre-compiled ingredient patterns
_UNITS_PAT = "(?:" + "|".join(re.escape(u) for u in _ROMANIAN_UNITS) + ")"

# "NUMBERunit NAME" or "NUMBER unit NAME" (unit may be directly attached to number)
_RE_NUM_UNIT_NAME = re.compile(
    rf"^([\d.,/\-]+)\s*({_UNITS_PAT})\s+(.+)$", re.IGNORECASE
)
# "(number unit)" at end: "apa (5-6 l)"
_RE_PAREN_NUM_UNIT = re.compile(
    rf"^([\d.,/\-]+)\s*({_UNITS_PAT})$", re.IGNORECASE
)
# "NUMBER NAME" (no explicit unit)
_RE_NUM_NAME = re.compile(r"^([\d.,/\-]+)\s+(.+)$")
# NUMBER directly attached to name, e.g. "1ou"
_RE_NUM_ATTACHED = re.compile(r"^(\d+)([^\d\s].+)$")
# Romanian text-number + optional unit + name, e.g. "o linguriță zahăr"
_RE_RO_AMT_UNIT_NAME = re.compile(
    rf"^(un|una|o|doi|doua|două|trei|patru|cinci)\s+({_UNITS_PAT})\s+(.+)$",
    re.IGNORECASE,
)
# Romanian text-number + name (no unit), e.g. "Un praf de sare"
_RE_RO_AMT_NAME = re.compile(
    r"^(un|una|o|doi|doua|două|trei|patru|cinci)\s+(.+)$", re.IGNORECASE
)
# Name followed by number+unit at end, e.g. "rasol de porc aprox 1 kg"
_RE_NAME_NUM_UNIT = re.compile(
    rf"^(.+?)\s+([\d.,/\-]+)\s*({_UNITS_PAT})\s*$", re.IGNORECASE
)

# Romanian text-numbers used in time extraction
_RO_TIME_NUMS: Dict[str, int] = {
    "un": 1, "una": 1, "o": 1,
    "doi": 2, "doua": 2, "două": 2,
    "trei": 3, "patru": 4, "cinci": 5,
    "sase": 6, "șase": 6, "sapte": 7, "șapte": 7,
    "opt": 8, "noua": 9, "nouă": 9, "zece": 10,
}


class PreparatecusufletbyadaBlogspotComExtractor(BaseRecipeExtractor):
    """Extractor for preparatecusufletbyada.blogspot.com"""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_text_nodes(self) -> List[str]:
        """Return all meaningful text nodes from div.post-body."""
        body = self.soup.find(class_="post-body")
        if not body:
            logger.warning("post-body not found in %s", self.html_path)
            return []

        nodes: List[str] = []
        for elem in body.descendants:
            if isinstance(elem, NavigableString):
                text = str(elem).replace("\xa0", " ").strip()
                if text:
                    nodes.append(text)
        return nodes

    def _split_sections(self) -> Tuple[List[str], List[str]]:
        """Split post-body text nodes into ingredient and instruction sections.

        Returns:
            (ingredient_nodes, instruction_nodes)
        """
        nodes = self._get_text_nodes()

        ingredient_start = -1
        instruction_start = -1
        end_idx = len(nodes)

        for i, text in enumerate(nodes):
            tl = text.strip()
            # Ingredient section header: "Ingrediente:" (the top-level one)
            if ingredient_start == -1 and re.match(
                r"^ingrediente\s*[:\.\s]*$", tl, re.IGNORECASE
            ):
                ingredient_start = i + 1
                continue

            # Instruction section header: "Mod de preparare" (with optional trailing colon)
            if re.match(
                r"^mod\s+de\s+preparare\s*[:\.\s]*$", tl, re.IGNORECASE
            ):
                instruction_start = i + 1
                continue

            # End of recipe
            if re.match(r"^poft[ăa]\s+bun[ăa]!?\s*$", tl, re.IGNORECASE):
                end_idx = i
                break

        if ingredient_start == -1:
            ingredient_start = 0
        if instruction_start == -1:
            instruction_start = end_idx

        ingredient_nodes = nodes[ingredient_start : instruction_start - 1]
        instruction_nodes = nodes[instruction_start:end_idx]
        return ingredient_nodes, instruction_nodes

    @staticmethod
    def _is_section_header(text: str) -> bool:
        """Return True if text is an ingredient sub-section header."""
        return bool(re.match(r"ingrediente", text, re.IGNORECASE)) and ":" in text

    @staticmethod
    def _split_compound(text: str) -> List[str]:
        """Split compound ingredients joined with '+', e.g. '1 ou+o linguriță zahăr'."""
        parts = [p.strip() for p in text.split("+")]
        return [p for p in parts if p] if len(parts) > 1 else [text]

    @staticmethod
    def _parse_ingredient(text: str) -> Optional[Dict[str, Any]]:
        """Parse a single Romanian ingredient string into {name, amount, unit}."""
        text = text.strip()
        if not text:
            return None

        # Handle trailing parenthetical: "name(unit)", "name (unit)", "name (amount unit)"
        paren_m = re.match(r"^(.+?)\s*\(([^)]+)\)\s*$", text)
        main = paren_m.group(1).strip() if paren_m else text
        paren = paren_m.group(2).strip() if paren_m else None

        # If paren contains a numeric amount + unit, e.g. "(5-6 l)"
        if paren:
            pu_m = _RE_PAREN_NUM_UNIT.match(paren)
            if pu_m:
                return {
                    "name": main,
                    "amount": pu_m.group(1).strip(),
                    "unit": pu_m.group(2).strip(),
                }

        # Pattern 1: NUMBER(unit)NAME  or  NUMBER unit NAME
        m = _RE_NUM_UNIT_NAME.match(main)
        if m:
            return {
                "name": m.group(3).strip(),
                "amount": m.group(1).strip(),
                "unit": m.group(2).strip(),
            }

        # Pattern 2: NUMBER NAME (no unit)
        m = _RE_NUM_NAME.match(main)
        if m:
            return {
                "name": m.group(2).strip(),
                "amount": m.group(1).strip(),
                "unit": paren,
            }

        # Pattern 3: NUMBER directly attached to name (e.g. "1ou")
        m = _RE_NUM_ATTACHED.match(main)
        if m:
            return {
                "name": m.group(2).strip(),
                "amount": m.group(1).strip(),
                "unit": paren,
            }

        # Pattern 4: Romanian text-amount + unit + name ("o linguriță zahăr")
        m = _RE_RO_AMT_UNIT_NAME.match(main)
        if m:
            return {
                "name": m.group(3).strip(),
                "amount": m.group(1).strip(),
                "unit": m.group(2).strip(),
            }

        # Pattern 5: Romanian text-amount + name, no unit ("Un praf de sare")
        m = _RE_RO_AMT_NAME.match(main)
        if m:
            return {
                "name": m.group(2).strip(),
                "amount": m.group(1).strip(),
                "unit": paren,
            }

        # Pattern 6: NAME ... NUMBER UNIT (amount at end, e.g. "rasol de porc aprox 1 kg")
        m = _RE_NAME_NUM_UNIT.match(main)
        if m:
            return {
                "name": m.group(1).strip(),
                "amount": m.group(2).strip(),
                "unit": m.group(3).strip(),
            }

        # Default: just the name (e.g. "sare", "piper boabe", "Nuttela(pt interior)")
        return {
            "name": main,
            "amount": None,
            "unit": paren,
        }

    # ------------------------------------------------------------------
    # Time extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_cook_time(text: str) -> Optional[str]:
        """Extract oven/cooking time from instruction text.

        Searches for time mentions in the immediate vicinity of oven keywords
        (``cuptor``, ``coapte``, ``preîncălzit``) to avoid false positives from
        mixing / resting times earlier in the instructions.
        """
        # Search within a window around each "cuptor" / oven mention
        for oven_m in re.finditer(
            r"cuptor|preîncălzit|coapte", text, re.IGNORECASE
        ):
            ctx_start = max(0, oven_m.start() - 250)
            ctx_end = min(len(text), oven_m.end() + 250)
            ctx = text[ctx_start:ctx_end]

            # Time range: "16-20minute"
            tm = re.search(r"([\d]+[-–][\d]+)\s*minute", ctx, re.IGNORECASE)
            if tm:
                return f"{tm.group(1)} minutes"

            # "aproximativ N minute"
            tm = re.search(r"aproximativ\s+([\d]+)\s*minute", ctx, re.IGNORECASE)
            if tm:
                return f"{tm.group(1)} minutes"

            # Generic "N minute"
            tm = re.search(r"([\d]+)\s*minute", ctx, re.IGNORECASE)
            if tm:
                return f"{tm.group(1)} minutes"

        # Duration in hours (digit): "4 ore", "2 ore"
        m = re.search(r"([\d]+)\s*(?:de\s+)?ore", text, re.IGNORECASE)
        if m:
            return f"{m.group(1)} hours"

        # Duration in hours (word): "patru ore", "trei ore si jumatate"
        ro_words = "|".join(_RO_TIME_NUMS.keys())
        m = re.search(rf"\b({ro_words})\s+ore\b", text, re.IGNORECASE)
        if m:
            word = m.group(1).lower()
            num = _RO_TIME_NUMS.get(word, word)
            return f"{num} hours"

        return None

    @staticmethod
    def _extract_prep_time(text: str) -> Optional[str]:
        """Extract the most significant preparation/resting time from instruction text.

        Collects all time mentions not in an oven context and returns the
        largest value (most likely the dominant preparation step).
        """
        candidates: List[Tuple[int, str]] = []

        def _in_oven_context(pos: int) -> bool:
            ctx = text[max(0, pos - 200) : min(len(text), pos + 200)]
            return bool(
                re.search(r"cuptor|preîncălzit|grade|coapte", ctx, re.IGNORECASE)
            )

        # Time ranges "N-M minute"
        for m in re.finditer(
            r"([\d]+)[-–]([\d]+)\s*(?:de\s+)?minute", text, re.IGNORECASE
        ):
            if not _in_oven_context(m.start()):
                upper = int(m.group(2))
                val_str = f"{m.group(1)}-{m.group(2)}"
                candidates.append((upper, val_str))

        # "pentru N (de) minute"
        for m in re.finditer(
            r"pentru\s+([\d]+)\s*(?:de\s+)?minute", text, re.IGNORECASE
        ):
            if not _in_oven_context(m.start()):
                val = int(m.group(1))
                candidates.append((val, m.group(1)))

        # Generic "N minute" (e.g. "5 minute")
        for m in re.finditer(r"\b([\d]+)\s+minute\b", text, re.IGNORECASE):
            if not _in_oven_context(m.start()):
                val = int(m.group(1))
                if val >= 5:  # ignore very short incidental mentions
                    candidates.append((val, m.group(1)))

        if not candidates:
            return None

        # Return the largest (most significant) prep duration
        candidates.sort(key=lambda x: x[0], reverse=True)
        return f"{candidates[0][1]} minutes"

    # ------------------------------------------------------------------
    # Public extraction methods
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Extract dish name from h1.post-title or og:title."""
        # Prefer h1 with post-title / entry-title class
        for h1 in self.soup.find_all("h1"):
            classes = h1.get("class") or []
            if "post-title" in classes or "entry-title" in classes:
                text = self.clean_text(h1.get_text())
                if text:
                    return text

        # Fallback: og:title
        og_title = self.soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return self.clean_text(og_title["content"])

        return None

    def extract_description(self) -> Optional[str]:
        """Description is not present in a usable form in this blog's HTML."""
        return None

    def extract_ingredients(self) -> Optional[str]:
        """Extract and parse ingredients from post-body."""
        ingredient_nodes, _ = self._split_sections()
        ingredients: List[Dict[str, Any]] = []

        for node in ingredient_nodes:
            node = node.strip()
            if not node:
                continue

            # Skip section sub-headers ("Ingrediente aluat:", "Ingrediente sirop:", …)
            if self._is_section_header(node):
                continue

            # Split compound ingredients (e.g. "1 ou+o linguriță zahăr")
            for part in self._split_compound(node):
                parsed = self._parse_ingredient(part)
                if parsed:
                    ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_instructions(self) -> Optional[str]:
        """Extract instructions from post-body as a single string."""
        _, instruction_nodes = self._split_sections()
        if not instruction_nodes:
            return None

        # Handle "Pasul N" step labels: prepend to the first following sentence
        parts: List[str] = []
        pending_label: Optional[str] = None

        for node in instruction_nodes:
            node = node.strip()
            if not node:
                continue

            if re.match(r"^Pasul\s+\d+", node, re.IGNORECASE):
                pending_label = node
            else:
                if pending_label:
                    parts.append(f"{pending_label}: {node}")
                    pending_label = None
                else:
                    parts.append(node)

        return " ".join(parts) if parts else None

    def extract_category(self) -> Optional[str]:
        """Category is not present in this blog's HTML."""
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Extract preparation time from instruction text."""
        _, instruction_nodes = self._split_sections()
        full_text = " ".join(instruction_nodes)
        return self._extract_prep_time(full_text)

    def extract_cook_time(self) -> Optional[str]:
        """Extract cooking time from instruction text."""
        _, instruction_nodes = self._split_sections()
        full_text = " ".join(instruction_nodes)
        return self._extract_cook_time(full_text)

    def extract_total_time(self) -> Optional[str]:
        """Total time is not explicitly stated in this blog's HTML."""
        return None

    def extract_notes(self) -> Optional[str]:
        """Extract notes: INFO!!! and Atentie lines from instruction text."""
        _, instruction_nodes = self._split_sections()
        notes: List[str] = []
        for node in instruction_nodes:
            node = node.strip()
            if re.match(r"^(INFO!!!|Atentie\b)", node, re.IGNORECASE):
                notes.append(node)
        return " ".join(notes) if notes else None

    def extract_tags(self) -> Optional[str]:
        """Tags/labels – this blog's label section is typically empty."""
        labels_elem = self.soup.find("span", class_="post-labels")
        if labels_elem:
            tag_links = labels_elem.find_all("a")
            if tag_links:
                tags = [self.clean_text(link.get_text()) for link in tag_links]
                return ", ".join(t for t in tags if t)
        return None

    def extract_image_urls(self) -> Optional[str]:
        """Extract image URLs: og:image + images inside post-body."""
        urls: List[str] = []

        # og:image (main featured image)
        og_image = self.soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            urls.append(og_image["content"])

        # Images embedded in the post body
        body = self.soup.find(class_="post-body")
        if body:
            for img in body.find_all("img"):
                src = img.get("src") or img.get("data-src") or ""
                src = src.strip()
                if src and src not in urls:
                    urls.append(src)

        seen: set = set()
        unique: List[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ",".join(unique) if unique else None

    def extract_all(self) -> dict:
        """Extract all recipe data and return as a dict."""
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
            "tags": tags,
            "image_urls": image_urls,
        }


def main() -> None:
    """Process all HTML files in the preprocessed directory for this site."""
    import os

    recipes_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "preprocessed",
        "preparatecusufletbyada_blogspot_com",
    )
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(PreparatecusufletbyadaBlogspotComExtractor, recipes_dir)
        return

    print(f"Directory not found: {recipes_dir}")


if __name__ == "__main__":
    main()
