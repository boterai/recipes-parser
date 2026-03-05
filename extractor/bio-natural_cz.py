"""
Экстрактор данных рецептов для сайта bio-natural.cz
"""

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class BioNaturalCzExtractor(BaseRecipeExtractor):
    """Экстрактор для bio-natural.cz"""

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _get_article(self):
        """Return the main <article> element."""
        return self.soup.find("article")

    def _get_entry_content(self):
        """Return the dynamic-entry-content div inside the article."""
        article = self._get_article()
        if article:
            return article.find(class_="dynamic-entry-content")
        return None

    @staticmethod
    def _parse_amount_unit(quantity_text: str):
        """
        Parse a Czech/English quantity string such as '250 g', '2 lžíce',
        'Podle chuti', '1/4 šálku' into (amount, unit).

        Returns:
            Tuple (amount, unit) where amount is int/float/str/None and
            unit is str/None.
        """
        text = quantity_text.strip()
        if not text:
            return None, None

        # Try leading number (possibly a fraction like '1/4')
        match = re.match(r"^([\d.,/]+)\s*(.*)$", text)
        if match:
            amount_str = match.group(1).strip()
            unit = match.group(2).strip() or None

            try:
                if "/" in amount_str:
                    parts = amount_str.split("/")
                    amount = float(parts[0]) / float(parts[1])
                elif "," in amount_str:
                    amount = float(amount_str.replace(",", "."))
                else:
                    amount = float(amount_str)

                # Convert to int when whole number
                if amount == int(amount):
                    amount = int(amount)
            except (ValueError, ZeroDivisionError):
                amount = amount_str

            return amount, unit

        # No leading number → descriptive quantity (e.g. "Podle chuti", "hrst")
        return None, text

    # ------------------------------------------------------------------ #
    # Dish name
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Extract recipe title from the main h1 heading in the article.
        Strips the subtitle after ': ' if present."""
        article = self._get_article()
        if article:
            h1 = article.find("h1", class_=re.compile(r"gb-headline", re.I))
            if h1:
                name = self.clean_text(h1.get_text())
                # Strip subtitle after ': '  (e.g. "Veganská Tortilla: Chutný recept" → "Veganská Tortilla")
                if ": " in name:
                    name = name.split(": ", 1)[0].strip()
                return name if name else None

        # Fallback: og:title
        og_title = self.soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"]
            # Strip site name suffix
            title = re.sub(r"\s*»\s*Bio-Natural\.cz.*$", "", title, flags=re.I)
            # Strip subtitle
            if ": " in title:
                title = title.split(": ", 1)[0].strip()
            return self.clean_text(title)

        return None

    # ------------------------------------------------------------------ #
    # Description
    # ------------------------------------------------------------------ #

    def extract_description(self) -> Optional[str]:
        """Extract description from og:description meta tag."""
        og_desc = self.soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            return self.clean_text(og_desc["content"])

        meta_desc = self.soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            return self.clean_text(meta_desc["content"])

        return None

    # ------------------------------------------------------------------ #
    # Ingredients
    # ------------------------------------------------------------------ #

    def _parse_ingredients_from_table(self, table) -> list:
        """
        Parse ingredients from a table that has columns for name and quantity.
        Supports headers: Složka/Množství or Ingredience/Množství.
        """
        ingredients = []
        headers = [th.get_text().strip().lower() for th in table.find_all("th")]

        # Identify column indices
        name_idx = None
        qty_idx = None
        for i, h in enumerate(headers):
            if h in ("složka", "ingredience", "surovina", "suroviny"):
                name_idx = i
            elif h in ("množství",):
                qty_idx = i

        if name_idx is None:
            # Try columns 0 and 1 as fallback when table has exactly 2 columns
            if len(headers) == 2:
                name_idx, qty_idx = 0, 1
            else:
                return ingredients

        for tr in table.find_all("tr")[1:]:  # skip header row
            cells = tr.find_all("td")
            if not cells:
                continue

            name = self.clean_text(cells[name_idx].get_text()) if name_idx < len(cells) else ""
            if not name:
                continue

            amount = None
            unit = None
            if qty_idx is not None and qty_idx < len(cells):
                qty_text = self.clean_text(cells[qty_idx].get_text())
                amount, unit = self._parse_amount_unit(qty_text)

            ingredients.append({"name": name, "amount": amount, "unit": unit})

        return ingredients

    def _parse_ingredients_from_list(self, ul_elem) -> list:
        """
        Parse ingredients from a <ul> element where each <li> has a bolded
        name and may contain quantity info in the text.
        Pattern: '<strong>Name:</strong> description' or
                 '<strong>amount unit name</strong>'
        """
        ingredients = []
        for li in ul_elem.find_all("li", recursive=False):
            # Normalise: sometimes li contains stray <p> siblings inside the ul
            strong = li.find("strong")
            if strong:
                raw = self.clean_text(strong.get_text())
            else:
                raw = self.clean_text(li.get_text())

            if not raw:
                continue

            # Strip trailing colon (used as label: "Hladká mouka:")
            name = raw.rstrip(":")
            amount = None
            unit = None

            # Try to detect leading quantity: "200 g medu", "1/4 lžičky soli"
            qty_match = re.match(
                r"^([\d.,/½¼¾⅓⅔⅛]+)\s*(g|kg|ml|l|lžíce|lžička|lžičky|lžic|šálek|šálků|ks|hrnek|hrnků|konzerva|tablespoons?|teaspoons?|cups?|tbsps?|tsps?|oz|lb)?\s+(.+)$",
                name,
                re.IGNORECASE,
            )
            if qty_match:
                amount_str = qty_match.group(1)
                unit = qty_match.group(2) or None
                name = self.clean_text(qty_match.group(3))

                try:
                    if "/" in amount_str:
                        parts = amount_str.split("/")
                        amount = float(parts[0]) / float(parts[1])
                    else:
                        amount = float(amount_str.replace(",", "."))
                    if amount == int(amount):
                        amount = int(amount)
                except (ValueError, ZeroDivisionError):
                    amount = amount_str

            if name:
                ingredients.append({"name": name, "amount": amount, "unit": unit})

        return ingredients

    def _is_quantified_list(self, ul_elem) -> bool:
        """Return True if more than half the <li> items start with a number."""
        lis = ul_elem.find_all("li")
        if not lis:
            return False
        quantified = 0
        for li in lis:
            strong = li.find("strong")
            text = (strong.get_text() if strong else li.get_text()).strip()
            if re.match(r"^[\d/.,½¼¾⅓⅔⅛]+", text):
                quantified += 1
        return quantified / len(lis) > 0.5

    def extract_ingredients(self) -> Optional[str]:
        """
        Extract ingredients using multiple strategies (in priority order):
        1. Table inside section.ingredient-section (Složka/Množství columns)
        2. Any table in the article with headers "Ingredience"/"Množství"
        3. Any <ul> in the article where the majority of items start with numbers
           (quantified ingredient lists)
        4. <ul> inside "Ingredience"/"Suroviny" heading section
        5. <ul> inside preparation-related heading section
        """
        article = self._get_article()
        if not article:
            return None

        # --- Strategy 1: section.ingredient-section → table ---
        ing_section = article.find("section", class_="ingredient-section")
        if ing_section:
            table = ing_section.find("table")
            if table:
                ingredients = self._parse_ingredients_from_table(table)
                if ingredients:
                    return json.dumps(ingredients, ensure_ascii=False)

            # Fallback: quantified UL inside ingredient section
            ul = ing_section.find("ul")
            if ul:
                ingredients = self._parse_ingredients_from_list(ul)
                if ingredients:
                    return json.dumps(ingredients, ensure_ascii=False)

        # --- Strategy 2: Any article table with Ingredience/Množství ---
        for table in article.find_all("table"):
            headers = [th.get_text().strip().lower() for th in table.find_all("th")]
            if any(h in ("ingredience", "složka") for h in headers) and any(
                h in ("množství",) for h in headers
            ):
                ingredients = self._parse_ingredients_from_table(table)
                if ingredients:
                    return json.dumps(ingredients, ensure_ascii=False)

        # --- Strategy 3: any UL where majority of items are quantified ---
        entry_content = self._get_entry_content()
        if entry_content:
            for ul in entry_content.find_all("ul"):
                if self._is_quantified_list(ul):
                    ingredients = self._parse_ingredients_from_list(ul)
                    if ingredients:
                        return json.dumps(ingredients, ensure_ascii=False)

        # --- Strategy 4: H2/H3 heading "Ingredience" or "Suroviny" → UL ---
        if entry_content:
            for heading in entry_content.find_all(["h2", "h3"]):
                heading_text = heading.get_text().lower()
                if re.search(r"ingredien|surovin", heading_text):
                    sibling = heading.find_next_sibling()
                    while sibling:
                        if sibling.name in ("h2", "h3"):
                            break
                        if sibling.name == "ul":
                            ingredients = self._parse_ingredients_from_list(sibling)
                            if ingredients:
                                return json.dumps(ingredients, ensure_ascii=False)
                        elif sibling.name == "section":
                            ul = sibling.find("ul")
                            if ul:
                                ingredients = self._parse_ingredients_from_list(ul)
                                if ingredients:
                                    return json.dumps(ingredients, ensure_ascii=False)
                        sibling = sibling.find_next_sibling()

        # --- Strategy 5: Preparation section with ingredient list ---
        prep_section = article.find("section", class_="recipe-preparation")
        if prep_section:
            ul = prep_section.find("ul")
            if ul:
                ingredients = self._parse_ingredients_from_list(ul)
                if ingredients:
                    return json.dumps(ingredients, ensure_ascii=False)

        # --- Strategy 6: H2 heading with preparation/suroviny keywords → UL ---
        if entry_content:
            for heading in entry_content.find_all(["h2", "h3"]):
                heading_text = heading.get_text().lower()
                if re.search(r"příprav|postup|surov|co potřebujete|jak připravit", heading_text):
                    sibling = heading.find_next_sibling()
                    while sibling:
                        if sibling.name in ("h2",):
                            break
                        if sibling.name == "ul":
                            ingredients = self._parse_ingredients_from_list(sibling)
                            if ingredients:
                                return json.dumps(ingredients, ensure_ascii=False)
                        sibling = sibling.find_next_sibling()

        return None

    # ------------------------------------------------------------------ #
    # Instructions
    # ------------------------------------------------------------------ #

    # Czech cooking verb patterns used to identify instructional paragraphs
    _COOKING_VERBS_RE = re.compile(
        r"\b(smíchejte|přidejte|zahřejte|nechte|rozmačkejte|marinujte|obalte|osmažte|"
        r"nakrájejte|uvařte|vařte|zapečte|pečte|opečte|rozválejte|vykrajujte|zabalte|"
        r"přiveďte|smažte|fritujte|ochutnejte|přelijte|přeneste|promíchejte|"
        r"rozdělte|vyválejte|odměřte|připravte|začněte|nakrájet|marinovat|obalit|"
        r"osmažit|uvařit|zapéct|přivést|smíchat|přidat|zahřát)\b",
        re.IGNORECASE,
    )

    def extract_steps(self) -> Optional[str]:
        """
        Extract recipe instructions using multiple strategies:
        1. section.recipe-preparation → OL/UL steps + paragraphs
        2. H2 heading "Postup" / "Příprava" / "Krok" → OL, UL, or paragraphs
        3. Paragraphs in the article that contain cooking action verbs
        """
        article = self._get_article()
        if not article:
            return None

        # --- Strategy 1: section.recipe-preparation ---
        prep_section = article.find("section", class_="recipe-preparation")
        if prep_section:
            steps = self._extract_steps_from_container(prep_section)
            if steps:
                return steps

        # --- Strategy 2: H2/H3 heading with postup / příprava / krok keywords
        # but NOT ingredient headings ---
        entry_content = self._get_entry_content()
        if entry_content:
            for heading in entry_content.find_all(["h2", "h3"]):
                heading_text = heading.get_text().lower()
                # Match preparation/step headings, exclude ingredient headings
                if (
                    re.search(r"postup|krok|jak připravit|vaření.*krok|příprav", heading_text)
                    and not re.search(r"surov|ingredien|snadné surov|co potřebuj", heading_text)
                ):
                    container = []
                    sibling = heading.find_next_sibling()
                    while sibling:
                        if sibling.name == heading.name:
                            break
                        container.append(sibling)
                        sibling = sibling.find_next_sibling()

                    # Look for OL inside collected siblings
                    for elem in container:
                        if elem.name == "ol":
                            steps = self._steps_from_ol(elem)
                            if steps:
                                return steps
                        elif elem.name == "section":
                            ol = elem.find("ol")
                            if ol:
                                steps = self._steps_from_ol(ol)
                                if steps:
                                    return steps
                            steps = self._extract_steps_from_container(elem)
                            if steps:
                                return steps

                    # Collect paragraphs that come AFTER any UL (skip intro text)
                    after_list = False
                    texts = []
                    for elem in container:
                        if elem.name in ("ul", "ol"):
                            after_list = True
                        elif elem.name == "p" and after_list:
                            t = self.clean_text(elem.get_text())
                            if t and len(t) > 20:
                                texts.append(t)

                    # If nothing after list, use paragraphs with cooking verbs
                    if not texts:
                        for elem in container:
                            if elem.name == "p":
                                t = self.clean_text(elem.get_text())
                                if t and self._COOKING_VERBS_RE.search(t):
                                    texts.append(t)
                    if texts:
                        return " ".join(texts)

        # --- Strategy 3: any article paragraph with dense cooking verbs ---
        if entry_content:
            candidates = []
            for p in entry_content.find_all("p"):
                t = self.clean_text(p.get_text())
                if not t or len(t) < 50:
                    continue
                verb_count = len(self._COOKING_VERBS_RE.findall(t))
                if verb_count >= 2:
                    candidates.append((verb_count, len(t), t))
            if candidates:
                # Prefer paragraphs with more cooking verbs (and longer if tied)
                candidates.sort(reverse=True)
                return candidates[0][2]

        return None

    def _steps_from_ol(self, ol_elem) -> Optional[str]:
        """Extract numbered steps from an <ol> element."""
        steps = []
        for idx, li in enumerate(ol_elem.find_all("li"), 1):
            text = self.clean_text(li.get_text())
            if text:
                steps.append(f"{idx}. {text}")
        return " ".join(steps) if steps else None

    def _steps_from_ul_as_steps(self, ul_elem) -> Optional[str]:
        """
        Treat a <ul> whose items are labeled steps (e.g. '<strong>Label:</strong> text')
        as an instruction sequence.  Returns None if items look like ingredients.
        """
        lis = ul_elem.find_all("li")
        if not lis:
            return None

        # Skip if this looks like an ingredient list (items start with numbers)
        if self._is_quantified_list(ul_elem):
            return None

        steps = []
        for idx, li in enumerate(lis, 1):
            text = self.clean_text(li.get_text())
            if text:
                steps.append(f"{idx}. {text}")

        return " ".join(steps) if steps else None

    def _extract_steps_from_container(self, container) -> Optional[str]:
        """
        Try to extract instructions from a container by looking for OL, then UL
        as steps, then paragraphs.
        """
        # OL has priority
        ol = container.find("ol")
        if ol:
            steps = self._steps_from_ol(ol)
            if steps:
                return steps

        # UL whose items are labeled steps (not ingredients)
        ul = container.find("ul")
        if ul and not self._is_quantified_list(ul):
            steps = self._steps_from_ul_as_steps(ul)
            if steps:
                return steps

        # Paragraphs (prose instructions)
        texts = []
        for p in container.find_all("p"):
            t = self.clean_text(p.get_text())
            if t and len(t) > 20:
                texts.append(t)
        if texts:
            return " ".join(texts)

        return None

    # ------------------------------------------------------------------ #
    # Category
    # ------------------------------------------------------------------ #

    def extract_category(self) -> Optional[str]:
        """Extract category from article:section meta or post-term elements."""
        # article:section meta (most reliable)
        art_section = self.soup.find("meta", property="article:section")
        if art_section and art_section.get("content"):
            return self.clean_text(art_section["content"])

        # post-term spans in the article
        article = self._get_article()
        if article:
            terms = article.find_all(class_=re.compile(r"post-term", re.I))
            if terms:
                term_texts = [self.clean_text(t.get_text()) for t in terms if t.get_text().strip()]
                term_texts = list(dict.fromkeys(term_texts))  # deduplicate
                if term_texts:
                    return ", ".join(term_texts)

        return None

    # ------------------------------------------------------------------ #
    # Time helpers
    # ------------------------------------------------------------------ #

    def _extract_time_from_text(self) -> dict:
        """
        Attempt to extract prep/cook/total time from article prose.
        Returns dict with keys 'prep', 'cook', 'total'.
        """
        times: dict = {"prep": None, "cook": None, "total": None}

        article = self._get_article()
        if not article:
            return times

        text = article.get_text(" ", strip=True)

        patterns = {
            "prep": [
                r"příprava\s*:?\s*([\d–\-]+(?:\s*(?:hodina?|hodiny|hodin|minut|minuty|minutes?))?(?:\s*(?:a|až)\s*[\d–\-]+(?:\s*minut)?)?)",
                r"odpočívat\s+(?:[^.]*?)([\d]+\s+hodinu?|[\d]+\s+minut)",
            ],
            "cook": [
                # verb + optional context + time (within same sentence fragment)
                r"(?:pečte|pečení|péct|opečte|osmažte|smažte|smažení|vařte)\s+(?:[^.]{0,40}?)\s*([\d–\-]+(?:–[\d]+)?\s*minut)",
                # time + location context
                r"([\d–\-]+(?:–[\d]+)?\s*(?:minut|minuty|minutes?))\s*(?:v mikrovlnné troubě|v troubě|na pánvi|při [\d]+ °C)",
                # oven context + time
                r"(?:troub[aě]|mikrovlnn[aé])\s+(?:[^.]{0,60}?)\s*([\d–\-]+(?:–[\d]+)?\s*(?:minut|minuty|minutes?))",
            ],
            "total": [
                r"celkem\s*:?\s*([\d–\-]+\s*(?:minut|minuty|minutes?|hodina?|hodin))",
                r"celkov[ýá]\s+čas\s*:?\s*([\d–\-]+\s*(?:minut|minuty|minutes?|hodina?|hodin))",
            ],
        }

        for time_type, pats in patterns.items():
            for pat in pats:
                m = re.search(pat, text, re.IGNORECASE)
                if m:
                    matched = self.clean_text(m.group(1))
                    if matched:
                        times[time_type] = matched
                        break

        return times

    def extract_prep_time(self) -> Optional[str]:
        return self._extract_time_from_text().get("prep")

    def extract_cook_time(self) -> Optional[str]:
        return self._extract_time_from_text().get("cook")

    def extract_total_time(self) -> Optional[str]:
        return self._extract_time_from_text().get("total")

    # ------------------------------------------------------------------ #
    # Notes
    # ------------------------------------------------------------------ #

    def extract_notes(self) -> Optional[str]:
        """
        Extract notes from:
        1. 'Závěrečné poznámky' / 'Závěrečné myšlenky' heading section
        2. 'Klíčové Poznatky' heading section
        3. 'tipy-na-servirovani' section
        """
        entry_content = self._get_entry_content()
        if not entry_content:
            return None

        # Strategy 1: "Závěrečné" heading
        for heading in entry_content.find_all(["h2", "h3"]):
            heading_text = heading.get_text().lower()
            if re.search(r"závěrečn|závěr\b", heading_text):
                texts = []
                sibling = heading.find_next_sibling()
                while sibling:
                    if sibling.name in ("h2", "h3"):
                        break
                    if sibling.name == "p":
                        t = self.clean_text(sibling.get_text())
                        if t and len(t) > 10:
                            texts.append(t)
                    sibling = sibling.find_next_sibling()
                if texts:
                    return texts[0]  # First paragraph as note

        # Strategy 2: "Klíčové Poznatky" / "Klíčové" heading
        for heading in entry_content.find_all(["h2", "h3"]):
            heading_text = heading.get_text().lower()
            if re.search(r"klíčov[ée]|poznatk", heading_text):
                texts = []
                sibling = heading.find_next_sibling()
                while sibling:
                    if sibling.name in ("h2", "h3"):
                        break
                    if sibling.name == "p":
                        t = self.clean_text(sibling.get_text())
                        if t and len(t) > 10:
                            texts.append(t)
                    sibling = sibling.find_next_sibling()
                if texts:
                    return texts[0]

        # Strategy 3: section.tipy-na-servirovani
        article = self._get_article()
        if article:
            tipy_section = article.find("section", class_="tipy-na-servirovani")
            if tipy_section:
                p = tipy_section.find("p")
                if p:
                    t = self.clean_text(p.get_text())
                    if t:
                        return t

        return None

    # ------------------------------------------------------------------ #
    # Tags
    # ------------------------------------------------------------------ #

    def extract_tags(self) -> Optional[str]:
        """
        Extract tags from:
        1. meta[name='keywords']
        2. post-term elements in the article
        3. article section meta (fallback)
        """
        # 1. Keywords meta tag
        keywords_meta = self.soup.find("meta", attrs={"name": "keywords"})
        if keywords_meta and keywords_meta.get("content"):
            tags = [t.strip() for t in keywords_meta["content"].split(",") if t.strip()]
            if tags:
                return ", ".join(tags)

        # 2. Post-term spans in the article
        article = self._get_article()
        if article:
            terms = article.find_all(class_=re.compile(r"post-term", re.I))
            if terms:
                tag_texts = [self.clean_text(t.get_text()) for t in terms if t.get_text().strip()]
                tag_texts = list(dict.fromkeys(tag_texts))
                if tag_texts:
                    return ", ".join(tag_texts)

        return None

    # ------------------------------------------------------------------ #
    # Image URLs
    # ------------------------------------------------------------------ #

    def extract_image_urls(self) -> Optional[str]:
        """
        Extract image URLs from og:image, twitter:image, and article images.
        """
        urls = []

        og_image = self.soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            urls.append(og_image["content"])

        twitter_image = self.soup.find("meta", attrs={"name": "twitter:image"})
        if twitter_image and twitter_image.get("content"):
            urls.append(twitter_image["content"])

        # Article images (skip logo/favicon images)
        article = self._get_article()
        if article:
            for img in article.find_all("img"):
                src = (
                    img.get("src")
                    or img.get("data-src")
                    or img.get("data-lazy-src")
                    or ""
                )
                if src and "bio-natural.cz" in src and "favicon" not in src.lower():
                    urls.append(src)

        # Deduplicate, preserve order
        seen: set = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ",".join(unique_urls) if unique_urls else None

    # ------------------------------------------------------------------ #
    # extract_all
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """
        Extract all recipe data and return as a dict.

        Returns:
            Dictionary with keys: dish_name, description, ingredients,
            instructions, category, prep_time, cook_time, total_time,
            notes, image_urls, tags.
        """
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
            instructions = self.extract_steps()
        except Exception as e:
            logger.warning("Failed to extract instructions: %s", e)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as e:
            logger.warning("Failed to extract category: %s", e)
            category = None

        try:
            times = self._extract_time_from_text()
            prep_time = times.get("prep")
            cook_time = times.get("cook")
            total_time = times.get("total")
        except Exception as e:
            logger.warning("Failed to extract times: %s", e)
            prep_time = cook_time = total_time = None

        try:
            notes = self.extract_notes()
        except Exception as e:
            logger.warning("Failed to extract notes: %s", e)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as e:
            logger.warning("Failed to extract tags: %s", e)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as e:
            logger.warning("Failed to extract image_urls: %s", e)
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
    """Entry point: process all HTML files in preprocessed/bio-natural_cz/."""
    preprocessed_dir = os.path.join("preprocessed", "bio-natural_cz")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(BioNaturalCzExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python bio-natural_cz.py")


if __name__ == "__main__":
    main()
