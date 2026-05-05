"""
Экстрактор данных рецептов для сайта edithetsacuisine.fr
WordPress + WP Recipe Maker (WPRM) plugin with JSON-LD @graph Recipe schema.
"""

import html as html_module
import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# French measurement units that may appear at the start of a WPRM ingredient name
# when WPRM omits the unit field (name contains "unit [de/d'] ingredient")
_FRENCH_UNITS = [
    "cuillerées à soupe",
    "cuillerée à soupe",
    "cuillerées à café",
    "cuillerée à café",
    "cuillères à soupe",
    "cuillère à soupe",
    "cuillères à café",
    "cuillère à café",
    "cuillères",
    "cuillère",
    "pincées",
    "pincée",
    "sachets",
    "sachet",
    "bains",
    "bain",
    "verres",
    "verre",
    "tasses",
    "tasse",
    "poignées",
    "poignée",
    "filets",
    "filet",
    "noisettes",
    "noisette",
    "noix",
    "gousses",
    "gousse",
    "branches",
    "branche",
    "tiges",
    "tige",
    "bottes",
    "botte",
    "tranches",
    "tranche",
    "morceaux",
    "morceau",
    "portions",
    "portion",
    "zestes",
    "zeste",
    "feuilles",
    "feuille",
    "carrés",
    "carré",
    "pièces",
    "pièce",
]

# Sorted longest-first so multi-word units match before shorter substrings
_FRENCH_UNITS_SORTED = sorted(_FRENCH_UNITS, key=len, reverse=True)

# Unicode fraction → decimal string
_FRACTION_MAP = {
    "½": "0.5",
    "¼": "0.25",
    "¾": "0.75",
    "⅓": "0.33",
    "⅔": "0.67",
    "⅛": "0.125",
    "⅜": "0.375",
    "⅝": "0.625",
    "⅞": "0.875",
}


class EdithetsacuisineFrExtractor(BaseRecipeExtractor):
    """Экстрактор для edithetsacuisine.fr (WordPress + WP Recipe Maker)"""

    # ------------------------------------------------------------------ helpers

    def _get_recipe_jsonld(self) -> Optional[dict]:
        """Return the first Recipe node from a JSON-LD @graph, or None."""
        for script in self.soup.find_all("script", type="application/ld+json"):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    # Yoast-style @graph
                    if "@graph" in data:
                        for item in data["@graph"]:
                            if isinstance(item, dict) and item.get("@type") == "Recipe":
                                return item
                    # Bare Recipe object
                    if data.get("@type") == "Recipe":
                        return data
            except (json.JSONDecodeError, AttributeError):
                logger.debug("Failed to parse JSON-LD script")
        return None

    def _get_main_recipe_card(self):
        """
        Return the main WPRM recipe card: a div.wprm-recipe that is NOT a
        snippet/roundup and DOES contain ingredient items.
        """
        for card in self.soup.find_all(class_="wprm-recipe"):
            classes_str = " ".join(card.get("class", []))
            if "snippet" in classes_str or "roundup" in classes_str:
                continue
            if card.find_all("li", class_=lambda c: c and "wprm-recipe-ingredient" in c):
                return card
        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Convert ISO 8601 duration (e.g. "PT25M", "PT1H30M", "PT115M") to a
        human-readable French-style string (e.g. "25 minutes", "1 heure 30 minutes").
        """
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
        # Normalise excess minutes into hours (handles e.g. PT115M → 1h55m)
        if hours == 0 and minutes >= 60:
            hours = minutes // 60
            minutes = minutes % 60
        if hours == 0 and minutes == 0:
            return None
        if hours > 0 and minutes > 0:
            h_label = "heure" if hours == 1 else "heures"
            m_label = "minute" if minutes == 1 else "minutes"
            return f"{hours} {h_label} {minutes} {m_label}"
        if hours > 0:
            label = "heure" if hours == 1 else "heures"
            return f"{hours} {label}"
        label = "minute" if minutes == 1 else "minutes"
        return f"{minutes} {label}"

    @staticmethod
    def _normalize_amount(raw: Optional[str]) -> Optional[str]:
        """Replace Unicode fractions with decimal strings."""
        if not raw:
            return raw
        text = raw.strip()
        for frac, dec in _FRACTION_MAP.items():
            text = text.replace(frac, dec)
        return text.strip() or None

    @staticmethod
    def _clean_name(name: str) -> str:
        """Strip leading French prepositions ('de ', "d'") from ingredient name."""
        name = name.strip()
        # "de beurre" → "beurre"
        name = re.sub(r"^de\s+", "", name, flags=re.IGNORECASE)
        # "d'eau" → "eau", "d'huile" → "huile" (apostrophe immediately before word)
        name = re.sub(r"^d['\u2019](?=\S)", "", name, flags=re.IGNORECASE)
        return name.strip()

    @classmethod
    def _extract_unit_from_name(cls, name: str) -> tuple:
        """
        When WPRM leaves the unit field empty, the name may start with the unit.
        Returns (cleaned_name, extracted_unit_or_None).
        """
        for unit in _FRENCH_UNITS_SORTED:
            pattern = rf"^({re.escape(unit)})\s+(?:de\s+|d[e\u2019']\s*)(.+)$"
            m = re.match(pattern, name, re.IGNORECASE)
            if m:
                return cls._clean_name(m.group(2)), m.group(1)
        return name, None

    # ---------------------------------------------------------------- extractors

    def extract_dish_name(self) -> Optional[str]:
        """Extract dish name from the page H1, stripping subtitle patterns."""
        h1 = self.soup.find("h1")
        if h1:
            text = self.clean_text(h1.get_text())
            # Strip " - subtitle", ", subtitle", " : subtitle"
            text = re.sub(r"\s*[-,]\s+.+$", "", text)
            text = re.sub(r"\s+:\s+.+$", "", text)
            if text:
                return text
        # Fallback: og:title
        og = self.soup.find("meta", property="og:title")
        if og and og.get("content"):
            text = self.clean_text(og["content"])
            text = re.sub(r"\s*[-,]\s+.+$", "", text)
            text = re.sub(r"\s+:\s+.+$", "", text)
            return text or None
        return None

    def extract_description(self) -> Optional[str]:
        """Extract description from og:description meta tag."""
        og = self.soup.find("meta", property="og:description")
        if og and og.get("content"):
            return self.clean_text(og["content"])
        # Fallback: WebPage.description from JSON-LD @graph
        for script in self.soup.find_all("script", type="application/ld+json"):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and "@graph" in data:
                    for item in data["@graph"]:
                        if item.get("@type") == "WebPage" and item.get("description"):
                            return self.clean_text(item["description"])
            except (json.JSONDecodeError, AttributeError):
                pass
        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Extract ingredients from the main WPRM card.
        Each ingredient is returned as {"name": str, "amount": str|None, "unit": str|None}.
        Falls back to JSON-LD recipeIngredient strings when no WPRM card is found.
        """
        card = self._get_main_recipe_card()
        ingredients = []

        if card:
            for li in card.find_all(
                "li", class_=lambda c: c and "wprm-recipe-ingredient" in c
            ):
                # Skip group/section headers
                li_classes = " ".join(li.get("class", []))
                if "group" in li_classes:
                    continue

                amount_span = li.find("span", class_="wprm-recipe-ingredient-amount")
                unit_span = li.find("span", class_="wprm-recipe-ingredient-unit")
                name_span = li.find("span", class_="wprm-recipe-ingredient-name")

                if not name_span:
                    continue

                raw_amount = self.clean_text(amount_span.get_text()) if amount_span else None
                raw_unit = self.clean_text(unit_span.get_text()) if unit_span else None
                raw_name = self.clean_text(name_span.get_text())

                # Normalize amount (fractions → decimals)
                amount = self._normalize_amount(raw_amount)
                unit = raw_unit if raw_unit else None

                # Clean name: strip "de "/"d'" prefix
                name = self._clean_name(raw_name)

                # When unit is absent, it may be encoded at the start of the name
                if not unit:
                    name, unit = self._extract_unit_from_name(name)

                if name:
                    ingredients.append({"name": name, "unit": unit, "amount": amount})

        if not ingredients:
            # Fallback: parse JSON-LD recipeIngredient plain strings
            recipe = self._get_recipe_jsonld()
            if recipe and "recipeIngredient" in recipe:
                for ing_str in recipe["recipeIngredient"]:
                    text = self.clean_text(html_module.unescape(str(ing_str)))
                    if text:
                        parsed = self._parse_ingredient_string(text)
                        if parsed:
                            ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def _parse_ingredient_string(self, text: str) -> Optional[dict]:
        """
        Best-effort parse of a plain-text ingredient string such as
        "400 gr de chair de butternut" → {"name": "chair de butternut", "amount": "400", "unit": "gr"}.
        """
        text = text.strip()
        # Normalize fractions
        for frac, dec in _FRACTION_MAP.items():
            text = text.replace(frac, dec)

        pattern = (
            r"^([\d\s./,]+)?\s*"
            r"(gr|g|kg|cl|ml|l|litre|litres|cuillère à soupe|cuillères à soupe|"
            r"cuillère à café|cuillères à café|pincée|pincées|sachet|sachets|"
            r"bain|bains|verre|verres|tasse|tasses|pièce|pièces|unit|unité)?\s*"
            r"(?:de\s+|d[e\u2019']\s*)?(.+)"
        )
        m = re.match(pattern, text, re.IGNORECASE)
        if not m:
            return {"name": text, "amount": None, "unit": None}

        amount_str, unit, name = m.groups()
        amount = (amount_str or "").strip() or None
        unit = (unit or "").strip() or None
        name = self._clean_name((name or "").strip())

        return {"name": name, "amount": amount, "unit": unit} if name else None

    def extract_instructions(self) -> Optional[str]:
        """
        Extract cooking instructions from the WPRM card.
        Falls back to JSON-LD recipeInstructions HowToStep items.
        """
        card = self._get_main_recipe_card()
        steps = []

        if card:
            for li in card.find_all(
                "li", class_=lambda c: c and "wprm-recipe-instruction" in c
            ):
                li_classes = " ".join(li.get("class", []))
                if "group" in li_classes:
                    continue
                text_elem = li.find(
                    class_=lambda c: c and "wprm-recipe-instruction-text" in c
                )
                if text_elem:
                    step_text = self.clean_text(text_elem.get_text(separator=" "))
                    if step_text:
                        steps.append(step_text)

        if not steps:
            recipe = self._get_recipe_jsonld()
            if recipe and "recipeInstructions" in recipe:
                steps = self._collect_instruction_steps(recipe["recipeInstructions"])

        return " ".join(steps) if steps else None

    @staticmethod
    def _collect_instruction_steps(instructions) -> list:
        """Recursively collect text from HowToSection / HowToStep structures."""
        steps = []
        if not isinstance(instructions, list):
            instructions = [instructions]
        for item in instructions:
            if not isinstance(item, dict):
                if isinstance(item, str):
                    steps.append(html_module.unescape(item).strip())
                continue
            item_type = item.get("@type", "")
            if item_type == "HowToSection":
                steps.extend(
                    EdithetsacuisineFrExtractor._collect_instruction_steps(
                        item.get("itemListElement", [])
                    )
                )
            elif item_type == "HowToStep":
                text = html_module.unescape(item.get("text", "")).strip()
                if text:
                    steps.append(text)
        return steps

    def extract_category(self) -> Optional[str]:
        """Extract category from WPRM course span or JSON-LD recipeCategory."""
        card = self._get_main_recipe_card()
        if card:
            course = card.find("span", class_="wprm-recipe-course")
            if course:
                text = self.clean_text(course.get_text())
                if text:
                    return text
        recipe = self._get_recipe_jsonld()
        if recipe and "recipeCategory" in recipe:
            cats = recipe["recipeCategory"]
            if isinstance(cats, list):
                return ", ".join(cats) or None
            return str(cats) or None
        return None

    def _extract_time(self, time_type: str) -> Optional[str]:
        """
        Extract a time value (prep/cook/total) from JSON-LD ISO 8601 first,
        then fall back to WPRM card HTML spans.
        """
        iso_keys = {"prep": "prepTime", "cook": "cookTime", "total": "totalTime"}
        recipe = self._get_recipe_jsonld()
        if recipe:
            key = iso_keys.get(time_type)
            if key and recipe.get(key):
                result = self._parse_iso_duration(recipe[key])
                if result:
                    return result

        # Fallback: read numeric values from WPRM HTML spans
        card = self._get_main_recipe_card()
        if not card:
            return None
        cls_prefix = {
            "prep": "wprm-recipe-prep_time",
            "cook": "wprm-recipe-cook_time",
            "total": "wprm-recipe-total_time",
        }.get(time_type)
        if not cls_prefix:
            return None

        hours_span = card.find(class_=f"{cls_prefix}-hours")
        minutes_span = card.find(class_=f"{cls_prefix}-minutes")

        def _get_num(span) -> int:
            if not span:
                return 0
            # The span may contain a child sr-only span with unit text; get only
            # the direct text node (first NavigableString).
            from bs4 import NavigableString
            for child in span.children:
                if isinstance(child, NavigableString):
                    txt = str(child).strip()
                    if txt.isdigit():
                        return int(txt)
            return 0

        hours = _get_num(hours_span)
        minutes = _get_num(minutes_span)
        if hours == 0 and minutes == 0:
            return None

        if hours > 0 and minutes > 0:
            h_label = "heure" if hours == 1 else "heures"
            m_label = "minute" if minutes == 1 else "minutes"
            return f"{hours} {h_label} {minutes} {m_label}"
        if hours > 0:
            label = "heure" if hours == 1 else "heures"
            return f"{hours} {label}"
        label = "minute" if minutes == 1 else "minutes"
        return f"{minutes} {label}"

    def extract_prep_time(self) -> Optional[str]:
        return self._extract_time("prep")

    def extract_cook_time(self) -> Optional[str]:
        return self._extract_time("cook")

    def extract_total_time(self) -> Optional[str]:
        return self._extract_time("total")

    def extract_notes(self) -> Optional[str]:
        """
        Extract notes/tips from:
        1. WPRM recipe card notes container (preferred)
        2. Article body headings with conseil/variante/astuce keywords
        """
        card = self._get_main_recipe_card()
        if card:
            notes_container = card.find(class_="wprm-recipe-notes-container")
            if notes_container:
                # Remove the decorative section header inside the container
                for header in notes_container.find_all(
                    class_=re.compile(r"wprm-recipe-notes-header", re.I)
                ):
                    header.extract()
                text = self.clean_text(notes_container.get_text(separator=" "))
                if text:
                    return text

        # Fallback: article body section with conseil/variante/astuce heading
        content = self.soup.find("div", class_="entry-content")
        if content:
            note_keywords = ("conseil", "variante", "astuce", "note")
            for heading in content.find_all(["h2", "h3", "h4"]):
                heading_text = heading.get_text(strip=True).lower()
                if any(kw in heading_text for kw in note_keywords):
                    parts = []
                    sibling = heading.find_next_sibling()
                    while sibling and sibling.name not in ("h2", "h3", "h4"):
                        if sibling.name in ("p", "ul", "ol"):
                            parts.append(sibling.get_text(separator=" ", strip=True))
                        sibling = sibling.find_next_sibling()
                    if parts:
                        return self.clean_text(" ".join(parts))
        return None

    def extract_tags(self) -> Optional[str]:
        """
        Build a tag string from JSON-LD recipeCategory, recipeCuisine, and keywords.
        """
        recipe = self._get_recipe_jsonld()
        if not recipe:
            return None

        tags: list = []

        def _add(value):
            """Add a tag if it's non-empty and not already present (case-insensitive)."""
            lower_tags = [t.lower() for t in tags]
            if isinstance(value, list):
                for v in value:
                    v_str = str(v).strip()
                    if v_str and v_str.lower() not in lower_tags:
                        tags.append(v_str)
                        lower_tags.append(v_str.lower())
            elif value:
                v_str = str(value).strip()
                if v_str and v_str.lower() not in lower_tags:
                    tags.append(v_str)

        _add(recipe.get("recipeCategory"))
        _add(recipe.get("recipeCuisine"))

        keywords = recipe.get("keywords")
        if keywords:
            if isinstance(keywords, list):
                for kw in keywords:
                    for part in str(kw).split(","):
                        _add(part.strip())
            else:
                for part in str(keywords).split(","):
                    _add(part.strip())

        return ", ".join(tags) if tags else None

    def extract_image_urls(self) -> Optional[str]:
        """Extract recipe image URLs from JSON-LD Recipe.image list."""
        recipe = self._get_recipe_jsonld()
        urls = []
        if recipe and "image" in recipe:
            images = recipe["image"]
            if isinstance(images, list):
                for img in images:
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, dict):
                        url = img.get("url") or img.get("contentUrl")
                        if url:
                            urls.append(url)
            elif isinstance(images, str):
                urls.append(images)
            elif isinstance(images, dict):
                url = images.get("url") or images.get("contentUrl")
                if url:
                    urls.append(url)

        # Deduplicate while preserving order
        seen: set = set()
        unique: list = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ",".join(unique) if unique else None

    # ---------------------------------------------------------------- main entry

    def extract_all(self) -> dict:
        """Extract all recipe data and return as a dict with all required fields."""
        try:
            dish_name = self.extract_dish_name()
        except Exception as e:
            logger.warning("Failed to extract dish_name: %s", e)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as e:
            logger.warning("Failed to extract description: %s", e)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as e:
            logger.warning("Failed to extract ingredients: %s", e)
            ingredients = None

        try:
            instructions = self.extract_instructions()
        except Exception as e:
            logger.warning("Failed to extract instructions: %s", e)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as e:
            logger.warning("Failed to extract category: %s", e)
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception as e:
            logger.warning("Failed to extract prep_time: %s", e)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception as e:
            logger.warning("Failed to extract cook_time: %s", e)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception as e:
            logger.warning("Failed to extract total_time: %s", e)
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception as e:
            logger.warning("Failed to extract notes: %s", e)
            notes = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as e:
            logger.warning("Failed to extract image_urls: %s", e)
            image_urls = None

        try:
            tags = self.extract_tags()
        except Exception as e:
            logger.warning("Failed to extract tags: %s", e)
            tags = None

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
    """Entry point: process all HTML files in preprocessed/edithetsacuisine_fr."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "edithetsacuisine_fr")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(EdithetsacuisineFrExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python edithetsacuisine_fr.py")


if __name__ == "__main__":
    main()
