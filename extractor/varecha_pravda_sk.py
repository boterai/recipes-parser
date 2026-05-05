"""
Экстрактор данных рецептов для сайта varecha.pravda.sk
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

from bs4 import NavigableString, Tag

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class VarechaPravdaSkExtractor(BaseRecipeExtractor):
    """Экстрактор для varecha.pravda.sk"""

    # Suffixes added by the site to recipe titles that should be stripped.
    _TITLE_SUFFIX_RE = re.compile(
        r"\s*[\(\[]?\s*(?:video|foto)\s*recept\s*[\)\]]?\s*$",
        re.IGNORECASE,
    )

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """Convert ISO 8601 duration string to a human-readable minutes string.

        Returns e.g. ``"30 minutes"`` or ``None`` when the duration is zero /
        not parseable.
        """
        if not duration or not duration.startswith("PT"):
            return None

        body = duration[2:]  # strip leading "PT"

        hours = 0
        minutes = 0

        hour_match = re.search(r"(\d+)H", body)
        if hour_match:
            hours = int(hour_match.group(1))

        min_match = re.search(r"(\d+)M", body)
        if min_match:
            minutes = int(min_match.group(1))

        total = hours * 60 + minutes
        if total <= 0:
            return None

        return f"{total} minutes"

    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Return the first JSON-LD Recipe object found in the page, or None."""
        for script in self.soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue

            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "Recipe":
                        return item
            elif isinstance(data, dict):
                if data.get("@type") == "Recipe":
                    return data
                for item in data.get("@graph", []):
                    if isinstance(item, dict) and item.get("@type") == "Recipe":
                        return item

        return None

    @staticmethod
    def _parse_amount_cell(cell_el) -> tuple:
        """Parse an ingredient amount ``<td>`` element.

        Returns ``(amount, unit, extra)`` where *extra* is additional
        descriptive text that can be appended to the ingredient name.
        """
        # Extra info may appear inside a <span> with parentheses.
        span = cell_el.find("span")
        extra_from_span: Optional[str] = None
        if span:
            raw_span = span.get_text(strip=True).strip("()")
            if raw_span:
                extra_from_span = raw_span

        # Get the text of the cell without the span text.
        full_text = cell_el.get_text(separator=" ").replace("\xa0", " ").strip()
        if span:
            span_text = span.get_text(strip=True)
            full_text = full_text.replace(span_text, "").strip()
        full_text = re.sub(r"\s+", " ", full_text).strip()

        if not full_text:
            return None, None, extra_from_span

        # Handle the "z X unit" Slovak preposition pattern (e.g. "z 1/2 citróna").
        z_prefix = ""
        if re.match(r"^z\s+", full_text, re.IGNORECASE):
            z_prefix = "z "
            full_text = full_text[2:].strip()

        # Match a leading numeric amount (integers, fractions, ranges, decimals).
        m = re.match(
            r"^(\d+(?:[,./]\d+)?(?:\s*-\s*\d+)?)\s*(.*)?$",
            full_text,
            re.UNICODE,
        )
        if m:
            raw_num = m.group(1).replace(",", ".").strip()
            remainder = (m.group(2) or "").strip()
            amount: Optional[str] = (z_prefix + raw_num).strip() if z_prefix else raw_num

            unit: Optional[str] = None
            extra_text: Optional[str] = None
            if remainder:
                tokens = remainder.split()
                unit = tokens[0]
                extra_text = " ".join(tokens[1:]) if len(tokens) > 1 else None

            extra = extra_from_span or extra_text
            return amount, unit, extra

        # No numeric amount found — the whole text is treated as unit info.
        return None, full_text or None, extra_from_span

    @staticmethod
    def _parse_info_number(div_el) -> tuple:
        """Parse a ``div.info-number`` element into ``(value_str, label_str)``.

        Returns e.g. ``("30 minút", "príprava")``.
        """
        strong = div_el.find("strong")
        value_str = strong.get_text(strip=True) if strong else ""
        # The label comes after the <br> tag.
        br = div_el.find("br")
        label_str = ""
        if br and br.next_sibling:
            label_str = str(br.next_sibling).strip()
        return value_str, label_str

    @staticmethod
    def _minutes_from_info_value(value_str: str) -> Optional[str]:
        """Convert a Slovak time string like ``"30 minút"`` to ``"30 minutes"``."""
        if not value_str:
            return None
        total = 0
        h_match = re.search(r"(\d+)\s*hodin", value_str, re.IGNORECASE)
        if h_match:
            total += int(h_match.group(1)) * 60
        m_match = re.search(r"(\d+)\s*min", value_str, re.IGNORECASE)
        if m_match:
            total += int(m_match.group(1))
        if total > 0:
            return f"{total} minutes"
        return None

    # ---------------------------------------------------------------- extractors

    def extract_dish_name(self) -> Optional[str]:
        """Extract dish name from ``h1.header-xl`` or JSON-LD."""
        h1 = self.soup.find("h1", class_="header-xl")
        if h1:
            name = self.clean_text(h1.get_text())
            return self._TITLE_SUFFIX_RE.sub("", name).strip() or None

        # Fallback: plain h1 (print page has no class on h1).
        h1 = self.soup.find("h1")
        if h1:
            name = self.clean_text(h1.get_text())
            return self._TITLE_SUFFIX_RE.sub("", name).strip() or None

        # Last resort: JSON-LD name.
        ld = self._get_json_ld_recipe()
        if ld and ld.get("name"):
            name = self.clean_text(ld["name"])
            return self._TITLE_SUFFIX_RE.sub("", name).strip() or None

        return None

    def extract_description(self) -> Optional[str]:
        """Extract recipe description from JSON-LD, ``div.recipe-description`` or ``p.summary``."""
        # JSON-LD description is usually the cleanest.
        ld = self._get_json_ld_recipe()
        if ld and ld.get("description"):
            # Strip stray asterisks used as footnote markers on the site.
            text = re.sub(r"\*+", "", ld["description"])
            text = self.clean_text(text)
            if text:
                return text

        # Main page: div.recipe-description.
        desc_div = self.soup.find("div", class_="recipe-description")
        if desc_div:
            text = self.clean_text(desc_div.get_text())
            if text:
                return text

        # Print page: p.summary.
        summary = self.soup.find("p", class_="summary")
        if summary:
            text = self.clean_text(summary.get_text())
            if text:
                return text

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Extract ingredients as a JSON-encoded list of dicts."""
        ingredients = []

        # ---- Main page: <table class="table"> with recipe-ingredients__row ----
        table = self.soup.find("table", class_="table")
        if table:
            current_group: Optional[str] = None
            for tr in table.find_all("tr"):
                cls = tr.get("class") or []

                # Group separator row (e.g. "Na obalenie:", "Na vyprážanie:").
                if "ingredients__group" in cls:
                    group_td = tr.find("td", class_="recipe-ingredients__group")
                    if group_td:
                        current_group = self.clean_text(group_td.get_text()).rstrip(":")
                    continue

                if "recipe-ingredients__row" not in cls:
                    continue

                tds = tr.find_all("td")
                if len(tds) < 2:
                    continue

                amount_td = tds[0]
                name_td = tds[1]

                # Name: prefer link text, fall back to label text.
                name_link = name_td.find("a")
                if name_link:
                    base_name = self.clean_text(name_link.get_text())
                else:
                    label = name_td.find("label")
                    base_name = self.clean_text(
                        label.get_text() if label else name_td.get_text()
                    )

                if not base_name:
                    continue

                amount, unit, extra = self._parse_amount_cell(amount_td)

                # Build full name:
                # 1. Append the group label as parenthetical when the ingredient
                #    has no amount/unit (it is a quantity-free group ingredient).
                # 2. Append any extra descriptor from the amount cell.
                parts = [base_name]
                if extra:
                    parts.append(f"({extra})")
                if current_group and amount is None and unit is None:
                    parts.append(f"({current_group.lower()})")
                full_name = " ".join(parts)

                ingredients.append(
                    {"name": full_name, "unit": unit, "amount": amount}
                )

            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        # ---- Print page: <ul class="list-reset"> <li class="ingredient"> ----
        ing_ul = self.soup.find("ul", class_="list-reset")
        if ing_ul:
            for li in ing_ul.find_all("li", class_="ingredient"):
                # Name is in the <a> link.
                name_link = li.find("a")
                if not name_link:
                    continue
                b_tag = name_link.find("b")
                base_name = self.clean_text(
                    b_tag.get_text() if b_tag else name_link.get_text()
                )
                if not base_name:
                    continue

                # Amount+unit: collect text nodes before the <a> tag.
                pre_text = ""
                for node in li.children:
                    if isinstance(node, Tag):
                        if node.name == "a":
                            break
                        # Skip the decorative div.square.
                        if "square" in (node.get("class") or []):
                            continue
                    elif isinstance(node, NavigableString):
                        pre_text += str(node)

                pre_text = pre_text.replace("\xa0", " ").strip()

                amount = None
                unit = None
                extra_text = None

                m = re.match(
                    r"^(z\s+)?(\d+(?:[,./]\d+)?(?:\s*-\s*\d+)?)\s*(.*)?$",
                    pre_text,
                    re.UNICODE,
                )
                if m:
                    z_pfx = (m.group(1) or "").strip()
                    raw_num = m.group(2).replace(",", ".").strip()
                    remainder = (m.group(3) or "").strip()
                    amount = (f"z {raw_num}" if z_pfx else raw_num)

                    if remainder:
                        tokens = remainder.split()
                        unit = tokens[0]
                        extra_text = " ".join(tokens[1:]) if len(tokens) > 1 else None

                full_name = f"{base_name} ({extra_text})" if extra_text else base_name
                ingredients.append(
                    {"name": full_name, "unit": unit, "amount": amount}
                )

            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        # ---- JSON-LD fallback: recipeIngredient string list ----
        ld = self._get_json_ld_recipe()
        if ld and ld.get("recipeIngredient"):
            for raw in ld["recipeIngredient"]:
                raw = self.clean_text(raw)
                if not raw:
                    continue
                # Format: "name, amount unit" or "name , amount unit (extra)"
                m = re.match(r"^(.+?),?\s+(\S+(?:\s*-\s*\S+)?)\s+(\S+)\s*(.*)$", raw)
                if m:
                    name_part = self.clean_text(m.group(1))
                    amt_part = m.group(2).replace(",", ".")
                    unit_part = m.group(3)
                    extra_part = m.group(4).strip("() ") or None
                    full_name = f"{name_part} ({extra_part})" if extra_part else name_part
                    ingredients.append(
                        {"name": full_name, "unit": unit_part, "amount": amt_part}
                    )
                else:
                    ingredients.append({"name": raw, "unit": None, "amount": None})

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_instructions(self) -> Optional[str]:
        """Extract cooking instructions.

        Tries JSON-LD ``recipeInstructions`` first (main page), then falls
        back to the HTML ``ol.recipe-instructions`` or print-page ``ol``.
        """
        # JSON-LD path (main page).
        ld = self._get_json_ld_recipe()
        if ld and ld.get("recipeInstructions"):
            steps = []
            for step in ld["recipeInstructions"]:
                if isinstance(step, dict):
                    text = self.clean_text(step.get("text", ""))
                elif isinstance(step, str):
                    text = self.clean_text(step)
                else:
                    continue
                if text:
                    steps.append(text)
            if steps:
                return " ".join(steps)

        # HTML fallback — works for both main page and print page.
        postup_h2 = self.soup.find(
            lambda tag: tag.name in ("h2", "h3")
            and "Postup" in tag.get_text()
        )
        if postup_h2:
            ol = postup_h2.find_next_sibling("ol")
            if ol:
                steps = []
                for li in ol.find_all("li"):
                    # Main page has a div.recipe-instruction__main inside each li.
                    main_div = li.find("div", class_="recipe-instruction__main")
                    if main_div:
                        text = self.clean_text(main_div.get_text())
                    else:
                        text = self.clean_text(li.get_text())
                    if text:
                        steps.append(text)
                if steps:
                    # Number the steps and join with newlines for the print page;
                    # use spaces for the main page (no JSON-LD should not happen
                    # normally, but keep output readable either way).
                    numbered = [f"{i}. {s}" for i, s in enumerate(steps, 1)]
                    return "\n".join(numbered)

        return None

    def extract_category(self) -> Optional[str]:
        """Extract category from JSON-LD ``recipeCategory``, or ``None``."""
        ld = self._get_json_ld_recipe()
        if ld:
            cat = ld.get("recipeCategory")
            if cat:
                if isinstance(cat, list):
                    return self.clean_text(", ".join(str(c) for c in cat if c))
                return self.clean_text(str(cat))
        return None

    def _extract_time_from_info_summary(self, label_keywords: list) -> Optional[str]:
        """Scan ``div.info-number`` elements for a time matching one of the label keywords."""
        for div in self.soup.find_all("div", class_="info-number"):
            value_str, label_str = self._parse_info_number(div)
            if any(kw in label_str.lower() for kw in label_keywords):
                parsed = self._minutes_from_info_value(value_str)
                if parsed:
                    return parsed
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Extract preparation time."""
        ld = self._get_json_ld_recipe()
        if ld and ld.get("prepTime"):
            result = self._parse_iso_duration(ld["prepTime"])
            if result:
                return result

        return self._extract_time_from_info_summary(["príprava", "priprava"])

    def extract_cook_time(self) -> Optional[str]:
        """Extract cooking time."""
        ld = self._get_json_ld_recipe()
        if ld and ld.get("cookTime"):
            result = self._parse_iso_duration(ld["cookTime"])
            if result:
                return result

        return self._extract_time_from_info_summary(["tepelná", "tepelna", "°", "pečenie", "varenie"])

    def extract_total_time(self) -> Optional[str]:
        """Extract total time from JSON-LD, info-summary, or computed from prep+cook."""
        ld = self._get_json_ld_recipe()
        if ld and ld.get("totalTime"):
            result = self._parse_iso_duration(ld["totalTime"])
            if result:
                return result

        html_total = self._extract_time_from_info_summary(["celkov", "spolu"])
        if html_total:
            return html_total

        # Compute from prep + cook as last resort (for print pages without JSON-LD).
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        if prep and cook:
            prep_m = re.match(r"^(\d+)", prep)
            cook_m = re.match(r"^(\d+)", cook)
            if prep_m and cook_m:
                total_min = int(prep_m.group(1)) + int(cook_m.group(1))
                if total_min > 0:
                    return f"{total_min} minutes"

        return None

    def extract_notes(self) -> Optional[str]:
        """Extract additional notes. Returns ``None`` for this site."""
        return None

    def extract_tags(self) -> Optional[str]:
        """Extract recipe tags from ``div.hashtags``."""
        hashtags_div = self.soup.find("div", class_="hashtags")
        if not hashtags_div:
            return None

        # Each hashtag is either in an <a> tag or as plain text with a leading #.
        tags = []
        for a in hashtags_div.find_all("a"):
            tag = self.clean_text(a.get_text()).lstrip("#")
            if tag:
                tags.append(tag)

        if not tags:
            # Fall back to extracting #word tokens from the raw text.
            raw = hashtags_div.get_text()
            tags = [m.group(1) for m in re.finditer(r"#(\w+)", raw)]

        if tags:
            return ", ".join(tags)

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Extract image URLs from JSON-LD or ``og:image``."""
        urls = []

        ld = self._get_json_ld_recipe()
        if ld and ld.get("image"):
            img = ld["image"]
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        url = item.get("url") or item.get("contentUrl")
                        if url:
                            urls.append(url)
            elif isinstance(img, dict):
                url = img.get("url") or img.get("contentUrl")
                if url:
                    urls.append(url)

        # og:image as fallback / supplement.
        og_image = self.soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            og_url = og_image["content"]
            if og_url not in urls:
                urls.append(og_url)

        if not urls:
            return None

        # Deduplicate and return as comma-separated string.
        seen = set()
        unique = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ",".join(unique) if unique else None

    def extract_all(self) -> dict:
        """Extract all recipe data and return a unified dict."""
        try:
            dish_name = self.extract_dish_name()
        except Exception as exc:
            logger.warning("Failed to extract dish_name: %s", exc)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as exc:
            logger.warning("Failed to extract description: %s", exc)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as exc:
            logger.warning("Failed to extract ingredients: %s", exc)
            ingredients = None

        try:
            instructions = self.extract_instructions()
        except Exception as exc:
            logger.warning("Failed to extract instructions: %s", exc)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as exc:
            logger.warning("Failed to extract category: %s", exc)
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception as exc:
            logger.warning("Failed to extract prep_time: %s", exc)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception as exc:
            logger.warning("Failed to extract cook_time: %s", exc)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception as exc:
            logger.warning("Failed to extract total_time: %s", exc)
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception as exc:
            logger.warning("Failed to extract notes: %s", exc)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as exc:
            logger.warning("Failed to extract tags: %s", exc)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as exc:
            logger.warning("Failed to extract image_urls: %s", exc)
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
    preprocessed_dir = Path(__file__).parent.parent / "preprocessed" / "varecha_pravda_sk"
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        process_directory(VarechaPravdaSkExtractor, str(preprocessed_dir))
        return

    print(f"Directory not found: {preprocessed_dir}")
    print("Usage: python varecha_pravda_sk.py [path_to_html_or_directory]")


if __name__ == "__main__":
    main()
