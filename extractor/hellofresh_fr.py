"""
Экстрактор данных рецептов для сайта hellofresh.fr
"""

import logging
import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Boilerplate sentence that appears in every recipe's first step
_BOILERPLATE = re.compile(
    r"Veillez à bien respecter les quantités indiquées à gauche pour préparer votre recette\s*[!.]\s*",
    re.IGNORECASE,
)

# Note markers embedded in instruction steps
_CONSEIL_RE = re.compile(r"CONSEIL\s*:\s*", re.IGNORECASE)
_SAVIEZ_RE = re.compile(r"LE\s+SAVIEZ-VOUS\s*\?\s*", re.IGNORECASE)


class HelloFreshFrExtractor(BaseRecipeExtractor):
    """Экстрактор для hellofresh.fr"""

    def __init__(self, html_path: str):
        super().__init__(html_path)
        self._notes_cache: Optional[list] = None

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Return the Recipe JSON-LD data block, if present."""
        for script in self.soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, dict) and data.get("@type") == "Recipe":
                    return data
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """Convert ISO 8601 duration (e.g. 'PT40M', 'PT1H30M') to '40 minutes'."""
        if not duration or not duration.startswith("PT"):
            return None
        hours = 0
        minutes = 0
        h_match = re.search(r"(\d+)H", duration)
        if h_match:
            hours = int(h_match.group(1))
        m_match = re.search(r"(\d+)M", duration)
        if m_match:
            minutes = int(m_match.group(1))
        total = hours * 60 + minutes
        return f"{total} minutes" if total > 0 else None

    @staticmethod
    def _parse_amount_unit(text: str):
        """
        Split an amount+unit string such as '90 g', '½ pièce(s)', 'selon le goût'
        into (amount, unit).

        Returns:
            (amount_str, unit_str | None)
        """
        text = text.strip()
        # Match optional leading number/fraction then optional unit text
        m = re.match(
            r"^([½¼¾⅓⅔⅛⅜⅝⅞]|\d+[.,]?\d*(?:\s+\d+/\d+)?|\d+/\d+)\s*(.*)",
            text,
        )
        if m:
            amount = m.group(1).strip()
            unit = m.group(2).strip() or None
            return amount, unit
        # Everything is the "amount" descriptor (e.g. "selon le goût")
        return text, None

    def _extract_step_notes(self, step_el) -> list:
        """
        Return a list of note strings (CONSEIL / LE SAVIEZ-VOUS) found inside
        a single instruction-step element.
        """
        notes = []
        # <p> tags that contain the note text sit at the same level as the <ul>
        for p in step_el.find_all("p"):
            # Use empty separator to avoid phantom spaces from nested spans
            raw = self.clean_text(p.get_text(separator="", strip=False))
            if _CONSEIL_RE.search(raw):
                note = _CONSEIL_RE.sub("", raw).strip()
                if note:
                    notes.append(note)
            elif _SAVIEZ_RE.search(raw):
                note = _SAVIEZ_RE.sub("", raw).strip()
                if note:
                    notes.append(note)
        return notes

    def _step_instruction_text(self, step_el) -> str:
        """
        Return the plain instruction text for one step, with:
        - step number stripped
        - boilerplate first sentence stripped
        - CONSEIL / LE SAVIEZ-VOUS blocks stripped (those go to notes)
        """
        # Collect <li> texts (the actual instructions)
        li_texts = []
        for li in step_el.find_all("li"):
            # Use empty separator to avoid phantom spaces from split spans
            txt = self.clean_text(li.get_text(separator="", strip=False))
            if not txt:
                continue
            # Skip the universal boilerplate
            if _BOILERPLATE.match(txt):
                continue
            li_texts.append(txt)
        return " ".join(li_texts)

    # ------------------------------------------------------------------ #
    #  Public extract_* methods                                            #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда."""
        el = self.soup.find(attrs={"data-test-id": "recipe-name"})
        if el:
            return self.clean_text(el.get_text())

        h1 = self.soup.find("h1")
        if h1:
            return self.clean_text(h1.get_text())

        og_title = self.soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return self.clean_text(og_title["content"])

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение краткого описания рецепта."""
        og_desc = self.soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            return self.clean_text(og_desc["content"])

        meta_desc = self.soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            return self.clean_text(meta_desc["content"])

        recipe_data = self._get_recipe_json_ld()
        if recipe_data and recipe_data.get("description"):
            return self.clean_text(recipe_data["description"])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из блока ingredient-item-*.
        Каждый элемент возвращается как {'name', 'amount', 'unit'}.
        """
        ingredients = []

        items = self.soup.find_all(
            attrs={"data-test-id": lambda v: v and v.startswith("ingredient-item-")}
        )

        for item in items:
            ps = [p.get_text(strip=True) for p in item.find_all("p") if p.get_text(strip=True)]
            if len(ps) < 2:
                logger.debug("Skipping ingredient item with unexpected structure: %s", ps)
                continue

            amount_unit_text = ps[0]
            name = self.clean_text(ps[1])

            if not name:
                continue

            amount, unit = self._parse_amount_unit(amount_unit_text)
            ingredients.append({"name": name, "unit": unit, "amount": amount})

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        # Fallback: JSON-LD recipeIngredient strings
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and recipe_data.get("recipeIngredient"):
            for raw in recipe_data["recipeIngredient"]:
                # Format: "90 g Spaghetti" or "½ pièce(s) Pâte à pizza"
                m = re.match(
                    r"^([½¼¾⅓⅔⅛⅜⅝⅞]|\d+[.,]?\d*)\s+([^\s].+?)\s+(.+)$", raw.strip()
                )
                if m:
                    amount_str, unit_str, name_str = m.groups()
                    ingredients.append(
                        {
                            "name": self.clean_text(name_str),
                            "unit": unit_str.strip() or None,
                            "amount": amount_str,
                        }
                    )
                else:
                    ingredients.append({"name": self.clean_text(raw), "unit": None, "amount": None})

            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

        return None

    def extract_steps(self) -> Optional[str]:
        """
        Извлечение шагов приготовления из блоков instruction-step.
        Заодно кэширует найденные заметки (CONSEIL / LE SAVIEZ-VOUS).
        """
        steps = []
        notes: list = []

        step_els = self.soup.find_all(attrs={"data-test-id": "instruction-step"})

        for step_el in step_els:
            notes.extend(self._extract_step_notes(step_el))
            txt = self._step_instruction_text(step_el)
            if txt:
                steps.append(txt)

        self._notes_cache = notes

        if steps:
            return " ".join(steps)

        # Fallback: JSON-LD recipeInstructions
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and recipe_data.get("recipeInstructions"):
            from bs4 import BeautifulSoup as _BS

            fallback_steps = []
            for instruction in recipe_data["recipeInstructions"]:
                if isinstance(instruction, dict):
                    raw_html = instruction.get("text", "")
                    if raw_html:
                        step_parsed = _BS(raw_html, "lxml")
                        for li in step_parsed.find_all("li"):
                            txt = self.clean_text(li.get_text(separator="", strip=False))
                            if txt and not _BOILERPLATE.match(txt):
                                fallback_steps.append(txt)
                elif isinstance(instruction, str):
                    fallback_steps.append(self.clean_text(instruction))
            self._notes_cache = self._notes_cache or []
            return " ".join(fallback_steps) if fallback_steps else None

        return None

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок: CONSEIL и LE SAVIEZ-VOUS из шагов приготовления,
        а также аллерген-примечания из JSON-LD описания.
        """
        if self._notes_cache is None:
            self.extract_steps()

        notes = list(self._notes_cache or [])

        # Allergen/special notes sometimes appended to JSON-LD description
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and recipe_data.get("description"):
            desc = recipe_data["description"]
            # Pattern: text like "Gaamoth ! Le fromage utilisé dans ce plat contient..."
            allergen_match = re.search(r"[Gg]aamoth[^!]*!\s*(.+)", desc, re.DOTALL)
            if allergen_match:
                note = self.clean_text(allergen_match.group(1))
                if note and note not in notes:
                    notes.append(note)

        combined = " ".join(notes).strip() if notes else None
        return combined if combined else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из JSON-LD recipeCategory."""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data:
            category = recipe_data.get("recipeCategory")
            if category:
                return self.clean_text(str(category))
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки — не публикуется на hellofresh.fr."""
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Время готовки — не публикуется отдельно на hellofresh.fr."""
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени из JSON-LD totalTime."""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and recipe_data.get("totalTime"):
            return self._parse_iso_duration(recipe_data["totalTime"])
        return None

    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов из data-test-id='item-tag-text' и уровня сложности.
        """
        tags = []
        seen = set()

        for el in self.soup.find_all(attrs={"data-test-id": "item-tag-text"}):
            text = el.get_text(strip=True)
            if text and text.lower() not in seen:
                tags.append(text)
                seen.add(text.lower())

        # Difficulty label: find the span with text "Difficulty" then get the value
        # from the same row div (sibling span, not the ":" one)
        diff_label = self.soup.find("span", string=re.compile(r"^Difficulty$"))
        if diff_label:
            row_div = diff_label.parent  # the row container div
            for span in row_div.find_all("span"):
                t = span.get_text(strip=True)
                if t and t != "Difficulty" and t != ":" and t.lower() not in seen:
                    tags.append(t)
                    seen.add(t.lower())
                    break  # Only one difficulty value expected

        return ", ".join(tags) if tags else None

    def extract_image_urls(self) -> Optional[str]:
        """
        Извлечение URL изображений: главное фото (JSON-LD / og:image) и
        пошаговые фото из instruction-step.
        """
        urls = []
        seen: set = set()

        def _add(url: str):
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        # 1. JSON-LD recipe image (highest quality)
        recipe_data = self._get_recipe_json_ld()
        if recipe_data:
            img = recipe_data.get("image")
            if isinstance(img, str):
                _add(img)
            elif isinstance(img, dict):
                _add(img.get("url") or img.get("contentUrl", ""))
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        _add(item)
                    elif isinstance(item, dict):
                        _add(item.get("url") or item.get("contentUrl", ""))

        # 2. og:image as fallback for main image
        og_image = self.soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            _add(og_image["content"])

        # 3. Step images from instruction-step blocks
        for step_el in self.soup.find_all(attrs={"data-test-id": "instruction-step"}):
            img_tag = step_el.find("img")
            if img_tag:
                src = img_tag.get("src", "")
                if src and src.startswith("http"):
                    _add(src)

        return ",".join(urls) if urls else None

    # ------------------------------------------------------------------ #
    #  Main entry point                                                    #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта в едином формате проекта.
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        instructions = self.extract_steps()  # also populates _notes_cache
        notes = self.extract_notes()
        ingredients = self.extract_ingredients()
        category = self.extract_category()
        tags = self.extract_tags()

        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "image_urls": self.extract_image_urls(),
            "tags": tags,
        }


def main():
    import os

    recipes_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "preprocessed",
        "hellofresh_fr",
    )
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(HelloFreshFrExtractor, recipes_dir)
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python hellofresh_fr.py")


if __name__ == "__main__":
    main()
