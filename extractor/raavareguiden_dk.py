"""
Экстрактор данных рецептов для сайта raavareguiden.dk

Сайт использует Breakdance builder (WordPress). Контент рецепта находится в
div.bde-rich-text. JSON-LD доступен только для некоторых страниц (тип Recipe).
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


class RaavareGuidenDkExtractor(BaseRecipeExtractor):
    """Экстрактор для raavareguiden.dk"""

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _get_recipe_json_ld(self) -> Optional[Dict[str, Any]]:
        """Return the Recipe-type JSON-LD block, if present."""
        for script in self.soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, dict) and data.get("@type") == "Recipe":
                    return data
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    def _get_article_json_ld(self) -> Optional[Dict[str, Any]]:
        """Return the Article item from a @graph JSON-LD block, if present."""
        for script in self.soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, dict) and "@graph" in data:
                    for item in data["@graph"]:
                        if isinstance(item, dict) and item.get("@type") == "Article":
                            return item
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    def _get_rich_text_div(self):
        """Return the main content div (Breakdance rich-text block)."""
        return self.soup.find("div", class_=re.compile(r"bde-rich-text"))

    def _rich_text_children(self) -> List:
        """Return element children of the rich-text div (no NavigableStrings)."""
        div = self._get_rich_text_div()
        if div is None:
            return []
        return [c for c in div.children if hasattr(c, "name") and c.name]

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """Convert ISO 8601 duration string (e.g. 'PT1H30M') to readable form."""
        if not duration or not duration.startswith("PT"):
            return None
        body = duration[2:]
        hours = 0
        minutes = 0
        h_match = re.search(r"(\d+)H", body)
        if h_match:
            hours = int(h_match.group(1))
        m_match = re.search(r"(\d+)M", body)
        if m_match:
            minutes = int(m_match.group(1))
        total = hours * 60 + minutes
        if total == 0:
            return None
        if hours > 0 and minutes > 0:
            return f"{hours} hours {minutes} minutes"
        if hours > 0:
            return f"{hours} hours"
        return f"{total} minutes"

    # ------------------------------------------------------------------ #
    # Ingredient parsing                                                   #
    # ------------------------------------------------------------------ #

    # Danish/English unit tokens (order matters: longest first to avoid
    # partial matches, e.g. "teskeed" before "tsk")
    _UNIT_TOKENS = (
        r"tablespoons?",
        r"teaspoons?",
        r"teskefuld(?:e)?",
        r"teskeed",
        r"spsk",
        r"tsk",
        r"dl",
        r"ml",
        r"liter",
        r"ounces?",
        r"pund",
        r"blade?",
        r"store?\s+fed",
        r"stor(?:e)?",
        r"kop(?:per)?",
        r"fed",
        r"stk",
        r"dåse(?:\s*\([^)]*\))?",
        r"kg",
        r"g",
        r"l",
    )
    _UNIT_PAT = "(?:" + "|".join(_UNIT_TOKENS) + ")"

    # Amount: plain integer/decimal, unicode fractions, ranges like
    # "4 til 8", "2-3", "4½", "1 ½"
    _FRAC_CHARS = r"[½¼¾⅓⅔⅛⅜⅝⅞]"
    _NUM = r"[\d]+(?:[.,][\d]+)?"
    _AMOUNT_PAT = (
        r"(?:"
        r"(?:{num})\s*{frac}?"  # number optionally followed by fraction char
        r"|{frac}"  # lone fraction char
        r")"
        r"(?:\s*(?:til|-)\s*{num})?"  # optional range suffix
    ).format(num=_NUM, frac=_FRAC_CHARS)

    _INGREDIENT_RE = re.compile(
        rf"^({_AMOUNT_PAT})\s+(?:({_UNIT_PAT})\s+)?(.+)$",
        re.IGNORECASE,
    )

    # Keywords that identify a notes / serving section heading
    _NOTES_KEYWORDS = ("servering", "nydelse", "tip", "råd", "bemærk")

    def _parse_ingredient(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Parse one ingredient line into ``{"name", "amount", "unit"}``.

        Handles formats like:
          * "500 g friske jordbær"
          * "¼ kop ekstra virgin olivenolie"
          * "4 til 8 ansjosfileter"
          * "Mynte – til pynt"  (no amount/unit)
        """
        text = self.clean_text(text)
        if not text:
            return None

        match = self._INGREDIENT_RE.match(text)
        if match:
            amount_raw = match.group(1).strip()
            unit = match.group(2).strip() if match.group(2) else None
            name = match.group(3).strip()

            if not name:
                return None

            return {"name": name, "amount": amount_raw, "unit": unit}

        # No leading amount — treat whole string as name
        return {"name": text, "amount": None, "unit": None}

    # ------------------------------------------------------------------ #
    # Public extraction methods                                            #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Extract dish name, stripping the 'Den X opskrift på' prefix."""
        h1 = self.soup.find("h1")
        title = self.clean_text(h1.get_text()) if h1 else None

        if not title:
            og = self.soup.find("meta", property="og:title")
            if og and og.get("content"):
                title = self.clean_text(og["content"])
                # Remove site name suffix
                title = re.sub(r"\s*-\s*Råvareguiden.*$", "", title, flags=re.IGNORECASE)

        if not title:
            return None

        # Strip "Den bedste/perfekte/... opskrift på/paa <name>"
        stripped = re.sub(
            r"^Den\s+\w+\s+opskrift\s+p[åa]\s+",
            "",
            title,
            flags=re.IGNORECASE,
        )
        return stripped.strip() or title.strip() or None

    def extract_description(self) -> Optional[str]:
        """Return description from Recipe JSON-LD or og:description."""
        recipe_ld = self._get_recipe_json_ld()
        if recipe_ld and recipe_ld.get("description"):
            return self.clean_text(recipe_ld["description"])

        og = self.soup.find("meta", property="og:description")
        if og and og.get("content"):
            return self.clean_text(og["content"])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Return JSON string with list of {name, amount, unit} dicts."""
        ingredients: List[Dict[str, Any]] = []

        # 1. Prefer Recipe JSON-LD recipeIngredient (already structured)
        recipe_ld = self._get_recipe_json_ld()
        if recipe_ld and recipe_ld.get("recipeIngredient"):
            for item in recipe_ld["recipeIngredient"]:
                parsed = self._parse_ingredient(str(item))
                if parsed:
                    ingredients.append(parsed)
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        # 2. Parse from HTML: find heading with "ingredi", get the following <ul>
        rich_div = self._get_rich_text_div()
        if rich_div:
            for heading in rich_div.find_all(["h2", "h3"]):
                if "ingredi" in heading.get_text(strip=True).lower():
                    ul = heading.find_next_sibling("ul")
                    if ul:
                        for li in ul.find_all("li"):
                            parsed = self._parse_ingredient(li.get_text(strip=True))
                            if parsed:
                                ingredients.append(parsed)
                    break

        if not ingredients:
            logger.warning("No ingredients found in %s", self.html_path)
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def _collect_steps_from_html(self) -> List[str]:
        """
        Fallback instruction extraction from the rich-text div.

        Collects all <p>/<ul>/<ol> content that appears *after* the
        ingredients <ul> and *before* the first notes/serving heading.
        Sub-headings inside the instruction area are skipped (not added
        as step text).
        """
        children = self._rich_text_children()
        steps: List[str] = []

        # Locate the ingredients <ul>
        ingr_ul = None
        rich_div = self._get_rich_text_div()
        if rich_div:
            for h in rich_div.find_all(["h2", "h3"]):
                if "ingredi" in h.get_text(strip=True).lower():
                    ingr_ul = h.find_next_sibling("ul")
                    break

        if ingr_ul is None:
            return steps

        collecting = False
        for elem in children:
            if elem == ingr_ul:
                collecting = True
                continue
            if not collecting:
                continue

            txt_lower = elem.get_text(strip=True).lower()
            if elem.name in ("h2", "h3"):
                if any(kw in txt_lower for kw in self._NOTES_KEYWORDS):
                    break  # reached notes section
                continue   # skip instruction sub-headings
            if elem.name == "p":
                t = self.clean_text(elem.get_text())
                if t:
                    steps.append(t)
            elif elem.name in ("ul", "ol"):
                for li in elem.find_all("li"):
                    t = self.clean_text(li.get_text())
                    if t:
                        steps.append(t)

        return steps

    def extract_instructions(self) -> Optional[str]:
        """Return all cooking steps as a single string."""
        # 1. Recipe JSON-LD
        recipe_ld = self._get_recipe_json_ld()
        if recipe_ld and recipe_ld.get("recipeInstructions"):
            parts: List[str] = []
            for step in recipe_ld["recipeInstructions"]:
                if isinstance(step, dict):
                    t = step.get("text", "")
                    if t:
                        parts.append(self.clean_text(t))
                elif isinstance(step, str):
                    parts.append(self.clean_text(step))
            if parts:
                return " ".join(parts)

        # 2. HTML fallback
        steps = self._collect_steps_from_html()
        if not steps:
            logger.warning("No instructions found in %s", self.html_path)
        return " ".join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Return recipe category from JSON-LD or article section."""
        recipe_ld = self._get_recipe_json_ld()
        if recipe_ld:
            cat = recipe_ld.get("recipeCategory") or recipe_ld.get("recipeCuisine")
            if cat:
                return self.clean_text(cat)

        article_ld = self._get_article_json_ld()
        if article_ld:
            section = article_ld.get("articleSection")
            if section:
                if isinstance(section, list) and section:
                    return self.clean_text(section[0])
                if isinstance(section, str):
                    return self.clean_text(section)

        return None

    def _extract_time(self, key: str) -> Optional[str]:
        """Return human-readable time from Recipe JSON-LD for the given key."""
        recipe_ld = self._get_recipe_json_ld()
        if recipe_ld:
            iso = recipe_ld.get(key)
            if iso:
                return self._parse_iso_duration(iso)
        return None

    def extract_prep_time(self) -> Optional[str]:
        return self._extract_time("prepTime")

    def extract_cook_time(self) -> Optional[str]:
        return self._extract_time("cookTime")

    def extract_total_time(self) -> Optional[str]:
        return self._extract_time("totalTime")

    def extract_notes(self) -> Optional[str]:
        """Return notes from 'Servering'/'Tips' section of the rich-text div."""
        rich_div = self._get_rich_text_div()
        if rich_div is None:
            return None

        for heading in rich_div.find_all(["h2", "h3"]):
            if any(kw in heading.get_text(strip=True).lower() for kw in self._NOTES_KEYWORDS):
                parts: List[str] = []
                for sibling in heading.find_next_siblings():
                    if sibling.name in ("h2", "h3"):
                        break
                    if sibling.name == "p":
                        t = self.clean_text(sibling.get_text())
                        if t:
                            parts.append(t)
                if parts:
                    return " ".join(parts)

        return None

    def extract_tags(self) -> Optional[str]:
        """Return tags from Recipe JSON-LD keywords."""
        recipe_ld = self._get_recipe_json_ld()
        if recipe_ld and recipe_ld.get("keywords"):
            return self.clean_text(recipe_ld["keywords"])
        return None

    def extract_image_urls(self) -> Optional[str]:
        """Return comma-separated image URLs (no spaces)."""
        urls: List[str] = []

        # 1. og:image (main image)
        og = self.soup.find("meta", property="og:image")
        if og and og.get("content"):
            urls.append(og["content"])

        # 2. thumbnailUrl / image from JSON-LD blocks
        for script in self.soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, AttributeError):
                continue

            def _collect(item: Dict[str, Any]) -> None:
                thumb = item.get("thumbnailUrl")
                if isinstance(thumb, str) and thumb:
                    urls.append(thumb)
                img = item.get("image")
                if isinstance(img, str):
                    urls.append(img)
                elif isinstance(img, list):
                    for i in img:
                        if isinstance(i, str):
                            urls.append(i)
                        elif isinstance(i, dict):
                            urls.append(i.get("url") or i.get("contentUrl") or "")

            if isinstance(data, dict):
                if "@graph" in data:
                    for item in data["@graph"]:
                        if isinstance(item, dict):
                            _collect(item)
                else:
                    _collect(data)

        # Deduplicate, drop empty / placeholder URLs
        seen: set = set()
        unique: List[str] = []
        for url in urls:
            if url and url not in seen and "example.com" not in url:
                seen.add(url)
                unique.append(url)

        return ",".join(unique) if unique else None

    # ------------------------------------------------------------------ #
    # Main entry point                                                     #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """Extract all recipe data and return as a dict."""
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()

        return {
            "dish_name": dish_name.lower() if dish_name else None,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": self.extract_image_urls(),
        }


def main() -> None:
    """Process all HTML files in preprocessed/raavareguiden_dk."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "raavareguiden_dk")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(RaavareGuidenDkExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python raavareguiden_dk.py")


if __name__ == "__main__":
    main()
