"""
Экстрактор данных рецептов для сайта neverthoughtaboutthat.com
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


class NeverthoughtaboutthatComExtractor(BaseRecipeExtractor):
    """Экстрактор для neverthoughtaboutthat.com"""

    # Known measurement units in the languages used on this site
    # (Dutch, German, Hungarian, English) — lowercase
    KNOWN_UNITS = {
        # English
        "teaspoon", "teaspoons", "tsp", "tablespoon", "tablespoons", "tbsp",
        "cup", "cups", "pound", "pounds", "lb", "lbs", "ounce", "ounces", "oz",
        "gram", "grams", "g", "kilogram", "kilograms", "kg",
        "milliliter", "milliliters", "ml", "liter", "liters", "l",
        "package", "packages", "pkg", "piece", "pieces", "slice", "slices",
        "clove", "cloves", "bunch", "bunches", "sprig", "sprigs",
        # Dutch
        "theelepel", "theelepels", "eetlepel", "eetlepels",
        "kop", "kopjes", "pond", "pak", "pakje", "pakken",
        "stukje", "stuk", "stuks", "dl", "liter",
        # German
        "teelöffel", "esslöffel", "tasse", "tassen",
        "pfund", "packung", "packungen", "stück", "scheibe", "scheiben",
        "bund", "zehe", "zehen", "prise", "prisen",
        # Hungarian
        "teáskanál", "evőkanál", "csésze", "font", "csomag",
        "darab", "szelet", "csokor", "gerezd", "szál", "dkg",
        # Generic
        "pinch", "dash", "drop", "handful", "can", "jar",
    }

    # ---------------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------------

    def _find_recipe_card(self):
        """
        Locate the recipe card div inside div.post-content.

        The recipe card is the top-level child div of div.post-content that
        contains instruction list items (li[style*='decimal']).
        """
        content = self.soup.find("div", class_="post-content")
        if not content:
            logger.warning("Could not find div.post-content")
            return None

        for div in content.find_all("div", recursive=False):
            if div.find("li", style=lambda s: s and "decimal" in s):
                return div

        logger.warning("Could not locate recipe card in div.post-content")
        return None

    def _find_time_divs(self):
        """
        Return the inner bordered divs that contain time labels.

        The time block has the structure:
            <div style="border-width: 1px; border-style: solid; ...">
                <div style="border-width: 1px; border-style: solid; ...">Bereidingstijd10 min</div>
                <div style="border-width: 1px; border-style: solid; ...">Kooktijd35 min</div>
            </div>
        """
        card = self._find_recipe_card()
        if not card:
            return []

        for div in card.find_all("div"):
            style = div.get("style", "")
            if "border-width" in style and "border-style: solid" in style:
                inner = div.find_all(
                    "div",
                    style=lambda s: s and "border-width" in s and "border-style: solid" in s,
                    recursive=False,
                )
                if inner:
                    return inner

        return []

    @staticmethod
    def _parse_time_text(text: str) -> Optional[str]:
        """
        Extract a duration from a localised label string.

        Examples:
          "Bereidingstijd10 min"  -> "10 minutes"
          "Kochzeit35 Min."       -> "35 minutes"
        """
        if not text:
            return None
        text = text.strip()
        match = re.search(
            r"(\d+)\s*(min(?:utes?|uten?|\.)?|uur|hours?|h(?:rs?)?|stunden?|percig?|perc|óra)",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        amount = match.group(1)
        unit = match.group(2).lower()
        if re.match(r"min|perc", unit):
            return f"{amount} minutes"
        if re.match(r"uur|hour|^h$|^hr|stunde|óra", unit):
            return f"{amount} hours"
        return None

    def _normalize_amount(self, amount_str: str) -> Optional[str]:
        """Convert a fraction / mixed-number string to a decimal string."""
        if not amount_str:
            return None
        amount_str = amount_str.strip()

        # Mixed number: "1 1/2"
        mixed = re.match(r"^(\d+)\s+(\d+)\s*/\s*(\d+)$", amount_str)
        if mixed:
            whole = int(mixed.group(1))
            num = int(mixed.group(2))
            denom = int(mixed.group(3))
            result = whole + num / denom
            return str(int(result)) if result == int(result) else str(result)

        # Simple fraction: "1/2"
        frac = re.match(r"^(\d+)\s*/\s*(\d+)$", amount_str)
        if frac:
            num = int(frac.group(1))
            denom = int(frac.group(2))
            result = num / denom
            return str(int(result)) if result == int(result) else str(result)

        # Regular decimal / integer
        return amount_str.replace(",", ".")

    def _parse_ingredient(self, text: str) -> Optional[dict]:
        """
        Parse a localised ingredient string into a structured dict.

        The format on the site is: "<amount> <unit> <name>"
        Examples (Dutch):
          "2 theelepels geroosterde sesamolie"
          "1/2 eetlepel doenjang"
          "Vers geroosterde sesamzaadjes (optioneel)"
        """
        if not text:
            return None

        text = self.clean_text(text).lower()

        # Normalise unicode fractions
        fraction_map = {
            "½": "1/2",
            "¼": "1/4",
            "¾": "3/4",
            "⅓": "1/3",
            "⅔": "2/3",
            "⅛": "1/8",
        }
        for frac, repl in fraction_map.items():
            text = text.replace(frac, repl)

        # Number pattern: integer, decimal, fraction or mixed
        number_pat = r"(\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?(?:\s+\d+/\d+)?)"

        # Pattern 1: <number> <unit_word> <name>  (unit must be a known measurement word)
        match = re.match(rf"^{number_pat}\s+(\S+)\s+(.+)$", text)
        if match:
            amount_str, candidate_unit, name = match.groups()
            if candidate_unit.rstrip(".") in self.KNOWN_UNITS:
                return {
                    "name": self.clean_text(name),
                    "amount": self._normalize_amount(amount_str),
                    "unit": candidate_unit,
                }
            # Unknown second word → treat entire remainder as name
            full_name = f"{candidate_unit} {name}"
            return {
                "name": self.clean_text(full_name),
                "amount": self._normalize_amount(amount_str),
                "unit": None,
            }

        # Pattern 2: <number> <name>  (no unit)
        match = re.match(rf"^{number_pat}\s+(.+)$", text)
        if match:
            amount_str, name = match.groups()
            return {
                "name": self.clean_text(name),
                "amount": self._normalize_amount(amount_str),
                "unit": None,
            }

        # Pattern 3: no number — plain name
        return {
            "name": text,
            "amount": None,
            "unit": None,
        }

    # ---------------------------------------------------------------------------
    # Field extractors
    # ---------------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        card = self._find_recipe_card()
        if card:
            h2 = card.find("h2")
            if h2:
                return self.clean_text(h2.get_text())

        # Fallback: first h1 on the page
        h1 = self.soup.find("h1")
        if h1:
            return self.clean_text(h1.get_text())

        # Fallback: <title>
        title_tag = self.soup.find("title")
        if title_tag:
            text = self.clean_text(title_tag.get_text())
            text = re.sub(r"\s*\|\s*Never thought about that.*$", "", text, flags=re.IGNORECASE)
            return text.strip() or None

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        card = self._find_recipe_card()
        if not card:
            return None

        h2 = card.find("h2")
        if not h2:
            return None

        # Walk siblings of h2 looking for the first non-spacer div
        current = h2.find_next_sibling()
        while current:
            if hasattr(current, "name") and current.name == "div":
                style = current.get("style", "")
                if "height: 5px" in style:
                    current = current.find_next_sibling()
                    continue
                text = self.clean_text(current.get_text())
                if text:
                    return text
            current = current.find_next_sibling()

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки (первый блок)"""
        time_divs = self._find_time_divs()
        if time_divs:
            return self._parse_time_text(time_divs[0].get_text())
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления (второй блок)"""
        time_divs = self._find_time_divs()
        if len(time_divs) >= 2:
            return self._parse_time_text(time_divs[1].get_text())
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени (третий блок, если есть)"""
        time_divs = self._find_time_divs()
        if len(time_divs) >= 3:
            return self._parse_time_text(time_divs[2].get_text())
        return None

    def extract_category(self) -> Optional[str]:
        """
        Извлечение категории (Course/Kurs/Gang/Cuisine) из карточки рецепта.

        Patterns found on the site:
          Dutch:   "Course: Aperitief, Diner, Bijgerecht, Soep"
          German:  "Kurs: Vorspeise, Abendessen, Beilage, Suppe"
          Hungarian: "Cuisine: Appetizer, Vacsora, Side, Leves"
        """
        card = self._find_recipe_card()
        if not card:
            return None

        for div in card.find_all("div"):
            # Only consider leaf divs (no child divs) to avoid matching parent containers
            if div.find("div"):
                continue
            text = div.get_text(separator=" ", strip=True)
            match = re.match(
                r"^(?:Course|Kurs|Gang|Cuisine|Fogás|Yemek)\s*:\s*(.+)$",
                text,
                re.IGNORECASE,
            )
            if match:
                value = match.group(1).strip()
                # Skip malformed entries such as "Cuisine: Cuisine:  2"
                if re.match(r"^(?:Course|Kurs|Gang|Cuisine|Fogás)\s*:", value, re.IGNORECASE):
                    continue
                return self.clean_text(value)

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из disc-стиля списков в карточке рецепта"""
        card = self._find_recipe_card()
        if not card:
            return None

        ingredients = []
        for li in card.find_all("li", style=lambda s: s and "disc" in s):
            text = self.clean_text(li.get_text())
            if not text:
                continue
            parsed = self._parse_ingredient(text)
            if parsed:
                ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций из decimal-стиля списка в карточке рецепта"""
        card = self._find_recipe_card()
        if not card:
            return None

        steps = []
        for li in card.find_all("li", style=lambda s: s and "decimal" in s):
            text = self.clean_text(li.get_text())
            if text:
                steps.append(text)

        return " ".join(steps) if steps else None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок / примечаний"""
        note_keywords = {"noten", "notes", "anmerkungen", "megjegyzések", "megjegyzés", "note", "jegyzetek"}

        # 1. Look inside the recipe card first
        card = self._find_recipe_card()
        if card:
            for h3 in card.find_all("h3"):
                if h3.get_text(strip=True).lower() in note_keywords:
                    sibling = h3.find_next_sibling()
                    while sibling:
                        if hasattr(sibling, "name") and sibling.name == "div":
                            text = self.clean_text(sibling.get_text())
                            if text:
                                return text
                        sibling = sibling.find_next_sibling()

        # 2. Fall back: look in post-content siblings of the recipe card
        content = self.soup.find("div", class_="post-content")
        if content:
            for div in content.find_all("div", recursive=False):
                h3 = div.find("h3")
                if h3 and h3.get_text(strip=True).lower() in note_keywords:
                    # Extract text excluding the header
                    full_text = self.clean_text(div.get_text())
                    header_text = self.clean_text(h3.get_text())
                    text = full_text.replace(header_text, "", 1).strip()
                    return text if text else None

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из ссылок с rel='category tag'"""
        generic = {"articles", "artikel", "cikkek", "recipes", "rezepte"}
        tags = []
        for link in self.soup.find_all("a", rel=lambda r: r and "tag" in r):
            text = self.clean_text(link.get_text())
            if text and text.lower() not in generic:
                tags.append(text)
        return ", ".join(tags) if tags else None

    def extract_image_urls(self) -> Optional[str]:
        """
        Извлечение URL изображений из div.post-content и JSON-LD.

        Фильтруются миниатюры (150×150), иконки и аватары.
        """
        urls = []
        seen: set = set()

        # 1. JSON-LD Article image (highest quality / canonical)
        for script in self.soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                graph = data.get("@graph", [])
                for item in graph:
                    if item.get("@type") == "Article" and "image" in item:
                        img = item["image"]
                        url = None
                        if isinstance(img, str):
                            url = img
                        elif isinstance(img, dict):
                            url = img.get("url") or img.get("contentUrl")
                        if url and url not in seen:
                            seen.add(url)
                            urls.append(url)
            except (json.JSONDecodeError, AttributeError, TypeError):
                continue

        # 2. Images in div.post-content
        content = self.soup.find("div", class_="post-content")
        if content:
            for img in content.find_all("img"):
                src = img.get("src", "")
                if not src:
                    continue
                # Skip thumbnails, icons and social avatars
                if any(
                    skip in src
                    for skip in ("gravatar", "share", "icon", "-150x150", "-100x100")
                ):
                    continue
                if src not in seen:
                    seen.add(src)
                    urls.append(src)

        return ",".join(urls) if urls else None

    # ---------------------------------------------------------------------------
    # Main entry point
    # ---------------------------------------------------------------------------

    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта"""

        def _safe(fn):
            try:
                return fn()
            except Exception as exc:
                logger.warning("Error in %s: %s", fn.__name__, exc)
                return None

        return {
            "dish_name": _safe(self.extract_dish_name),
            "description": _safe(self.extract_description),
            "ingredients": _safe(self.extract_ingredients),
            "instructions": _safe(self.extract_instructions),
            "category": _safe(self.extract_category),
            "prep_time": _safe(self.extract_prep_time),
            "cook_time": _safe(self.extract_cook_time),
            "total_time": _safe(self.extract_total_time),
            "notes": _safe(self.extract_notes),
            "tags": _safe(self.extract_tags),
            "image_urls": _safe(self.extract_image_urls),
        }


def main():
    import os

    recipes_dir = os.path.join("preprocessed", "neverthoughtaboutthat_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(NeverthoughtaboutthatComExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python neverthoughtaboutthat_com.py [путь_к_директории]")


if __name__ == "__main__":
    main()
