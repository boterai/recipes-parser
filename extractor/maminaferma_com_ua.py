"""
Экстрактор данных рецептов для сайта maminaferma.com.ua
"""

import json
import logging
import re
import sys
from copy import copy as _shallow_copy
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ukrainian unit normalization helpers
# ---------------------------------------------------------------------------

# Map verbose Ukrainian units to short canonical forms
_UA_UNIT_MAP: dict[str, str] = {
    "кілограм": "кг",
    "кілограми": "кг",
    "кілограмів": "кг",
    "грам": "г",
    "грами": "г",
    "грамів": "г",
    "мілілітр": "мл",
    "мілілітри": "мл",
    "мілілітрів": "мл",
    "літр": "л",
    "літри": "л",
    "літрів": "л",
    "штук": "шт",
    "штуки": "шт",
    "чайна ложка": "ч. л.",
    "чайних ложки": "ч. л.",
    "чайних ложок": "ч. л.",
    "чайної ложки": "ч. л.",
    "столова ложка": "ст. л.",
    "столових ложок": "ст. л.",
    "столових ложки": "ст. л.",
    "столової ложки": "ст. л.",
}

# Short unit tokens recognised in "amount unit" substrings
_UA_SHORT_UNITS = (
    "кг", "г", "гр", "мл", "л", "шт", "уп",
    "ч. л.", "ч.л.", "ст. л.", "ст.л.",
    "листочків", "зубчиків", "зубців",
    "м", "см", "мм",
)


def _normalize_unit(raw: str) -> str:
    """Return canonical unit string or the original value."""
    stripped = raw.strip()
    key_exact = stripped.lower()
    # Exact match in map
    if key_exact in _UA_UNIT_MAP:
        return _UA_UNIT_MAP[key_exact]
    # Match without trailing single dot (e.g. "кг." → lookup "кг")
    key_nodot = key_exact.rstrip(".")
    if key_nodot in _UA_UNIT_MAP:
        return _UA_UNIT_MAP[key_nodot]
    # No map match — return the stripped value.
    # Preserve multi-part abbreviations like "ч. л." (multiple dots) as-is.
    if stripped.endswith(".") and stripped.count(".") <= 1:
        return stripped[:-1]
    return stripped


def _parse_amount_unit(qty_text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Split a quantity string like "1 кг." or "0.5 ч. л." into (amount, unit).

    Returns (amount_str, unit_str) or (qty_text, None) when parsing fails.
    """
    qty_text = qty_text.strip()

    # Strip parenthetical annotations from the end (e.g. "1 шт (можна купити ...)")
    qty_text = re.sub(r"\s*\([^)]*\)\s*$", "", qty_text).strip()

    # Replace Unicode dash / en-dash between numbers as range separator
    qty_text = re.sub(r"(\d)\s*[–—]\s*(\d)", r"\1-\2", qty_text)
    # Normalise decimal comma
    qty_text = qty_text.replace(",", ".")

    # Try to match: optional number (int / decimal / range) followed by optional unit
    m = re.match(
        r"^([\d][.\d/-]*(?:\s*-\s*[\d][.\d]*)?)?\s*(.*)$",
        qty_text,
    )
    if not m:
        return qty_text, None

    raw_amount = (m.group(1) or "").strip()
    raw_unit = (m.group(2) or "").strip()

    amount = raw_amount if raw_amount else None
    unit = _normalize_unit(raw_unit) if raw_unit else None

    # If the "unit" looks like no real unit and there's no amount,
    # treat the whole string as amount (e.g. "за смаком")
    if not amount and raw_unit:
        return raw_unit, None

    return amount, unit


def _li_clean_text(li_tag) -> str:
    """
    Return clean text of an ingredient <li> tag.
    Removes <a> link text (promotional/navigation links) and strips extra whitespace.
    """
    tag = _shallow_copy(li_tag)
    # Remove anchor tags (keep their text only for now — strip the surrounding context)
    for a in tag.find_all("a"):
        a.decompose()
    text = tag.get_text(separator=" ", strip=True)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_article_ingredient(text: str) -> Optional[dict]:
    """
    Parse an ingredient string from the article body.

    Typical formats:
      "свинина — 1,5 кг"
      "часник — 6–8 зубчиків"
      "лід — за смаком"
      "200 грам пшеничного борошна вищого сорту;"
    """
    text = text.strip().rstrip(";").strip()
    if not text:
        return None

    # --- Format 1: "name — amount unit" (dash separator) ---
    for sep in (" — ", " - ", " – "):
        if sep in text:
            parts = text.split(sep, 1)
            name = parts[0].strip()
            amount_unit = parts[1].strip()
            amount, unit = _parse_amount_unit(amount_unit)
            return {"name": name, "amount": amount, "unit": unit}

    # --- Format 2: leading amount followed by unit and then name ---
    # e.g. "200 грам пшеничного борошна", "1 яйце"
    unit_pattern = r"(?:" + "|".join(re.escape(u) for u in _UA_SHORT_UNITS) + r")"
    verbose_units = "|".join(re.escape(k) for k in sorted(_UA_UNIT_MAP.keys(), key=len, reverse=True))

    m = re.match(
        r"^([\d][.\d/-]*(?:\s*-\s*[\d][.\d]*)?|[\d]+(?:[,.][\d]+)?)\s+"
        r"(" + verbose_units + r"|" + unit_pattern + r")\s+"
        r"(.+)$",
        text,
        re.IGNORECASE,
    )
    if m:
        amount = m.group(1).strip().replace(",", ".")
        unit = _normalize_unit(m.group(2))
        name = m.group(3).strip()
        return {"name": name, "amount": amount, "unit": unit}

    # --- Format 3: "amount unit name" with half-amount like "пів чайної ложки солі" ---
    # Not handled precisely; just return name=text, amount=None, unit=None
    return {"name": text, "amount": None, "unit": None}


class MaminafermaComUaExtractor(BaseRecipeExtractor):
    """Экстрактор для maminaferma.com.ua"""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Return the first JSON-LD Recipe object found in the page, or None."""
        for script in self.soup.find_all("script", type="application/ld+json"):
            if not script.string:
                continue
            # Remove control characters that sometimes appear in this site's JSON-LD
            raw = re.sub(r"[\x00-\x1f\x7f]", " ", script.string)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if isinstance(data, dict) and data.get("@type") == "Recipe":
                return data
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "Recipe":
                        return item
        return None

    def _get_cooking_body(self):
        """Return the content div inside the bottom cooking section."""
        cooking_section = self.soup.find("div", class_="single-recipe__bottom-cooking")
        if not cooking_section:
            return None
        for child in cooking_section.children:
            if not hasattr(child, "name") or child.name != "div":
                continue
            classes = child.get("class") or []
            if "recipe__bottom-cooking__title" not in classes:
                return child
        return None

    @staticmethod
    def _parse_iso_duration(iso: str) -> Optional[str]:
        """Convert ISO 8601 duration like 'PT45M' or 'PT1H30M' to minutes string."""
        if not iso or not iso.startswith("PT"):
            return None
        body = iso[2:]
        hours = int(m.group(1)) if (m := re.search(r"(\d+)H", body)) else 0
        minutes = int(m.group(1)) if (m := re.search(r"(\d+)M", body)) else 0
        total = hours * 60 + minutes
        return str(total) if total > 0 else None

    # ------------------------------------------------------------------
    # Field extractors
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Extract the recipe dish name from the page title or breadcrumbs."""
        title_tag = self.soup.find("title")
        if title_tag:
            raw = self.clean_text(title_tag.get_text())
            # Strip site suffix after " - "
            raw = re.sub(r"\s+-\s+[^:]+$", "", raw).strip()
            # Take the part before the first ":"
            if ":" in raw:
                candidate = raw.split(":")[0].strip()
            else:
                candidate = raw.strip()

            # If the title starts with an action word (Як, Де, Чи…), fall back to breadcrumb
            if not re.match(r"^(як|де|чи|чому|коли|що)\b", candidate, re.IGNORECASE):
                return candidate

        # Fallback: last breadcrumb item (strip " рецепт" suffix)
        breadcrumb = self.soup.find("ul", class_="breadcrumbs__list")
        if breadcrumb:
            items = breadcrumb.find_all("li")
            if items:
                name = self.clean_text(items[-1].get_text())
                name = re.sub(r"\s+рецепт\b.*$", "", name, flags=re.IGNORECASE).strip()
                if name:
                    return name

        return None

    def _get_top_description_body(self):
        """Return the content div inside recipe__top-description (without the title div)."""
        wrapper = self.soup.find("div", class_="recipe__top-description")
        if not wrapper:
            return None
        for child in wrapper.children:
            if not hasattr(child, "name") or child.name != "div":
                continue
            classes = child.get("class") or []
            if "recipe__top-description__title" not in classes:
                return child
        return None

    def extract_description(self) -> Optional[str]:
        """Extract the first paragraph from the recipe top-description section."""
        body = self._get_top_description_body()
        if body:
            # Return the text of the very first <p> tag (the recipe intro)
            first_p = body.find("p")
            if first_p:
                text = self.clean_text(first_p.get_text())
                if text:
                    return text
            # Fallback: first direct text child
            for child in body.children:
                if hasattr(child, "name") and child.name == "p":
                    text = self.clean_text(child.get_text())
                    if text:
                        return text
        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Extract ingredients from multiple sources:
        1. Article text — UL items near "Список інгредієнтів" keywords in the
           description body (recipe__top-description) and the cooking body.
        2. Product-catalog items — div.recipe__center-item (used as fallback or
           supplement when no article-text ingredients are found).
        Returns JSON-encoded list of {name, amount, unit} dicts, or None.
        """
        ingredients: list[dict] = []
        seen_names: set[str] = set()

        def add_ingredient(ing: Optional[dict]) -> None:
            if not ing:
                return
            key = ing["name"].lower().strip()
            if key and key not in seen_names:
                seen_names.add(key)
                ingredients.append(ing)

        ingredient_signal = re.compile(
            r"(інгредієнт|список|потрібно|склад\b)", re.IGNORECASE
        )

        def _extract_uls_from_section(section) -> None:
            """Collect ingredient ULs from a BeautifulSoup element."""
            if section is None:
                return
            all_elements = list(section.find_all(["h2", "h3", "p", "ul", "ol"]))
            for idx, el in enumerate(all_elements):
                if el.name not in ("p", "h2", "h3"):
                    continue
                txt = el.get_text(strip=True)
                if not ingredient_signal.search(txt):
                    continue
                # Look ahead for a UL/OL, skipping blank paragraphs
                for offset in range(1, 5):
                    nxt_idx = idx + offset
                    if nxt_idx >= len(all_elements):
                        break
                    nxt = all_elements[nxt_idx]
                    if nxt.name in ("ul", "ol"):
                        for li in nxt.find_all("li"):
                            text = self.clean_text(_li_clean_text(li))
                            add_ingredient(_parse_article_ingredient(text))
                        break
                    # Skip blank paragraphs, continue looking
                    if nxt.name == "p" and not nxt.get_text(strip=True):
                        continue
                    # Non-blank p or another heading — stop looking
                    break

        # --- Source 1a: description body (recipe__top-description content div) ---
        _extract_uls_from_section(self._get_top_description_body())

        # --- Source 1b: cooking body (article instructions section) ---
        _extract_uls_from_section(self._get_cooking_body())

        article_ingredients_found = bool(ingredients)

        # --- Source 2: product-catalog items (recipe__center-item) ---
        # Only include if no article-text ingredients were found, to avoid
        # cluttering recipe ingredients with shop product names.
        if not article_ingredients_found:
            center_items_section = self.soup.find("div", class_="recipe__center-items")
            if center_items_section:
                for item in center_items_section.find_all(
                    "div", class_="recipe__center-item"
                ):
                    label = item.find("label", class_="custom__checkbox-label")
                    qty_div = item.find("div", class_="recipes__center-item__quantity")
                    if not label or not qty_div:
                        continue

                    # Extract the product name from text nodes before the input tag
                    label_text_parts: list[str] = []
                    for node in label.children:
                        if hasattr(node, "name"):
                            break  # stop at first tag (the hidden input)
                        part = str(node).strip()
                        if part:
                            label_text_parts.append(part)
                    name = self.clean_text(" ".join(label_text_parts))
                    if not name:
                        name = self.clean_text(label.get_text(separator=" ", strip=True))
                        qty_raw = self.clean_text(qty_div.get_text(strip=True))
                        if qty_raw and name.endswith(qty_raw):
                            name = name[: -len(qty_raw)].strip()

                    qty_text = self.clean_text(qty_div.get_text(strip=True))
                    amount, unit = _parse_amount_unit(qty_text)

                    # Skip summary/total row
                    if name.lower().startswith("всього"):
                        continue

                    add_ingredient({"name": name, "amount": amount, "unit": unit})

        if not ingredients:
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def extract_steps(self) -> Optional[str]:
        """
        Extract cooking instructions from the bottom cooking section.

        Collects <li> items from ULs that follow instruction signal
        paragraphs/headings.  Ingredient ULs (detected by ";" suffix on items)
        and notes/tips sections are skipped.
        """
        cooking_body = self._get_cooking_body()
        if not cooking_body:
            return None

        # Pattern that signals the UL following it contains instructions
        instruction_signal = re.compile(
            r"(приготу|покрок|рецепт|готу|спекти|зробити|приступати|виконання)",
            re.IGNORECASE,
        )
        # Pattern for notes/tips section headings — stop collecting
        notes_heading = re.compile(
            r"(секрет|порад|рекомендац|зберіган|подач)", re.IGNORECASE
        )

        step_texts: list[str] = []
        in_notes = False
        encountered_notes_section = False   # once we enter notes we disable instruction sub-headings
        step_counter = 0
        next_ul_is_instruction: bool = False
        pending_heading: Optional[str] = None   # buffered section header

        all_elements = list(
            cooking_body.find_all(["h2", "h3", "p", "ul", "ol"])
        )

        for el in all_elements:
            if el.name in ("h2", "h3"):
                txt = el.get_text(strip=True)
                if notes_heading.search(txt):
                    in_notes = True
                    encountered_notes_section = True
                    next_ul_is_instruction = False
                    pending_heading = None
                    continue
                in_notes = False
                if instruction_signal.search(txt):
                    next_ul_is_instruction = True
                    if encountered_notes_section:
                        encountered_notes_section = False
                    # Buffer the heading — only add it once we actually collect steps
                    if step_counter > 0:
                        pending_heading = self.clean_text(txt)
                continue

            if in_notes:
                continue

            if el.name == "p":
                if instruction_signal.search(el.get_text(strip=True)):
                    next_ul_is_instruction = True
                continue

            if el.name in ("ul", "ol"):
                if not next_ul_is_instruction:
                    continue

                # Heuristic: if first li ends with ";" it's likely an ingredient list
                first_li = el.find("li")
                if first_li and first_li.get_text(strip=True).endswith(";"):
                    # Skip ingredient-style UL but keep looking for instructions
                    continue

                # Flush the pending sub-heading before adding the new steps
                if pending_heading is not None:
                    step_texts.append(pending_heading)
                    step_counter = 0
                    pending_heading = None

                for li in el.find_all("li"):
                    li_text = self.clean_text(li.get_text(separator=" ", strip=True))
                    if not li_text:
                        continue
                    step_counter += 1
                    step_texts.append(f"{step_counter}. {li_text}")

                # Collected one instruction UL; need new signal for next UL
                next_ul_is_instruction = False

        if not step_texts:
            return None

        return "\n".join(step_texts)

    def extract_category(self) -> Optional[str]:
        """Extract recipe category from the top-info section or JSON-LD."""
        # HTML: recipe__top-info__item containing "Тип рецепту:"
        for item in self.soup.find_all("div", class_="recipe__top-info__item"):
            text = item.get_text(separator="\n", strip=True)
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            for i, line in enumerate(lines):
                if "тип рецепту" in line.lower():
                    # Category is either on the same line after ":" or the next line
                    after_colon = line.split(":", 1)[-1].strip()
                    if after_colon:
                        return self.clean_text(after_colon)
                    if i + 1 < len(lines):
                        return self.clean_text(lines[i + 1])

        # Fallback: JSON-LD recipeCategory
        ld = self._get_json_ld_recipe()
        if ld:
            cat = ld.get("recipeCategory")
            if cat:
                return self.clean_text(str(cat))

        return None

    def extract_total_time(self) -> Optional[str]:
        """
        Extract total cooking time from the "Приготування:" info item.
        Returns formatted string like "200 minutes".
        """
        for item in self.soup.find_all("div", class_="recipe__top-info__item"):
            text = item.get_text(separator="\n", strip=True)
            if "приготування" not in text.lower():
                continue
            # Extract the number of minutes
            m = re.search(r"(\d+)", text)
            if m:
                return f"{m.group(1)} minutes"

        # Fallback: cookTime from JSON-LD
        ld = self._get_json_ld_recipe()
        if ld:
            cook = ld.get("cookTime")
            if cook:
                mins = self._parse_iso_duration(str(cook))
                if mins:
                    return f"{mins} minutes"

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Extract preparation time (not available in standard HTML; returns None)."""
        ld = self._get_json_ld_recipe()
        if ld:
            prep = ld.get("prepTime")
            if prep:
                mins = self._parse_iso_duration(str(prep))
                if mins:
                    return f"{mins} minutes"
        return None

    def extract_cook_time(self) -> Optional[str]:
        """
        Extract active cooking time from JSON-LD cookTime.
        If the JSON-LD cookTime equals the total time from the info block,
        prefer None to avoid duplication (the site uses one field for total).
        """
        ld = self._get_json_ld_recipe()
        if not ld:
            return None
        raw = ld.get("cookTime")
        if not raw:
            return None
        mins = self._parse_iso_duration(str(raw))
        if not mins:
            return None
        total = self.extract_total_time()
        # If JSON-LD cookTime == the displayed total time, don't duplicate
        if total and total == f"{mins} minutes":
            return None
        return f"{mins} minutes"

    def extract_notes(self) -> Optional[str]:
        """
        Extract tips / secrets / serving notes from the cooking body.
        Collects <li> bullet-point items from ULs that appear under headings
        containing "Секрети", "Поради", "Рекомендації", etc.
        """
        cooking_body = self._get_cooking_body()
        if not cooking_body:
            return None

        notes_parts: list[str] = []
        in_notes = False
        notes_keywords = re.compile(
            r"(секрет|порад|рекомендац|зберіган|подач)", re.IGNORECASE
        )
        # Signal that following UL is a bullet list of tips
        tips_ul_signal = re.compile(
            r"(рекомендац|секрет|порад|ключ|лайфхак)", re.IGNORECASE
        )
        collect_next_ul = False

        all_elements = list(
            cooking_body.find_all(["h2", "h3", "p", "ul", "ol"])
        )

        for el in all_elements:
            if el.name in ("h2", "h3"):
                txt = el.get_text(strip=True)
                if notes_keywords.search(txt):
                    in_notes = True
                    collect_next_ul = True
                else:
                    in_notes = False
                    collect_next_ul = False
                continue

            if not in_notes:
                continue

            if el.name == "p":
                # A paragraph inside the notes section that signals the next UL has tips
                if tips_ul_signal.search(el.get_text(strip=True)):
                    collect_next_ul = True
                continue

            if el.name in ("ul", "ol"):
                if not collect_next_ul:
                    continue
                for li in el.find_all("li"):
                    txt = self.clean_text(li.get_text(separator=" ", strip=True))
                    if txt:
                        notes_parts.append(txt)
                collect_next_ul = False

        return " ".join(notes_parts) if notes_parts else None

    def extract_tags(self) -> Optional[str]:
        """Extract tags from JSON-LD keywords or meta keywords."""
        ld = self._get_json_ld_recipe()
        if ld:
            kw = ld.get("keywords")
            if kw and str(kw).strip():
                tags = [t.strip() for t in str(kw).split(",") if t.strip()]
                if tags:
                    return ", ".join(tags)

        meta_kw = self.soup.find("meta", attrs={"name": "keywords"})
        if meta_kw and meta_kw.get("content", "").strip():
            return self.clean_text(meta_kw["content"])

        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Extract recipe image URLs.
        Primary source: picture.big-recipe__image img src.
        Also includes any recipe-body images.
        """
        urls: list[str] = []

        # Main recipe banner image
        big_pic = self.soup.find("picture", class_="big-recipe__image")
        if big_pic:
            img = big_pic.find("img")
            if img:
                src = img.get("src") or img.get("data-src", "")
                if src and src not in urls:
                    urls.append(src)

        # Images inside the cooking/instructions body
        cooking_body = self._get_cooking_body()
        if cooking_body:
            for img in cooking_body.find_all("img"):
                src = img.get("src") or img.get("data-src", "")
                if src and src not in urls:
                    urls.append(src)

        # JSON-LD image as fallback
        ld = self._get_json_ld_recipe()
        if ld:
            img_data = ld.get("image")
            if isinstance(img_data, str) and img_data not in urls:
                urls.append(img_data)
            elif isinstance(img_data, list):
                for entry in img_data:
                    if isinstance(entry, str) and entry not in urls:
                        urls.append(entry)
                    elif isinstance(entry, dict):
                        src = entry.get("url") or entry.get("contentUrl", "")
                        if src and src not in urls:
                            urls.append(src)

        return ",".join(urls) if urls else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """Extract all recipe data and return as a dict."""
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
            cook_time = self.extract_cook_time()
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
            "tags": tags,
            "image_urls": image_urls,
        }


def main() -> None:
    """Entry point: process all HTML files in preprocessed/maminaferma_com_ua."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "maminaferma_com_ua")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(MaminafermaComUaExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python maminaferma_com_ua.py")


if __name__ == "__main__":
    main()
