"""
Экстрактор данных рецептов для сайта cuisinersansgluten.com
Сайт использует WP Recipe Maker (WPRM), данные доступны через JSON-LD и WPRM-классы.
"""

import logging
import os
import re
import sys
import json
from pathlib import Path
from typing import Optional, List

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class CuisinersansGlutenComExtractor(BaseRecipeExtractor):
    """Экстрактор для cuisinersansgluten.com (WordPress + WP Recipe Maker)"""

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _get_recipe_jsonld(self) -> Optional[dict]:
        """Возвращает первый объект @type=Recipe из JSON-LD, или None."""
        for script in self.soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue

            # @graph wrapper (Yoast SEO style)
            if isinstance(data, dict) and "@graph" in data:
                for item in data["@graph"]:
                    if isinstance(item, dict) and item.get("@type") == "Recipe":
                        return item

            # Flat Recipe object
            if isinstance(data, dict) and data.get("@type") == "Recipe":
                return data

            # Array of objects
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "Recipe":
                        return item

        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат.

        PT2M      → "2 minutes"
        PT135M    → "2 hours 15 minutes"
        PT1H30M   → "1 hour 30 minutes"
        """
        if not duration or not duration.startswith("PT"):
            return None

        body = duration[2:]  # strip "PT"

        hours = 0
        minutes = 0

        hour_match = re.search(r"(\d+)H", body)
        if hour_match:
            hours = int(hour_match.group(1))

        min_match = re.search(r"(\d+)M", body)
        if min_match:
            minutes = int(min_match.group(1))

        total_minutes = hours * 60 + minutes
        if total_minutes == 0:
            return None

        h, m = divmod(total_minutes, 60)
        if h and m:
            return f"{h} hour{'s' if h > 1 else ''} {m} minute{'s' if m > 1 else ''}"
        if h:
            return f"{h} hour{'s' if h > 1 else ''}"
        return f"{m} minute{'s' if m > 1 else ''}"

    @staticmethod
    def _strip_french_particle(name: str) -> str:
        """
        WPRM often prepends French prepositions/articles to ingredient names.
        e.g. "de Flocons de Riz" → "Flocons de Riz"
             "d'Amandes"          → "Amandes"
        """
        return re.sub(r"^d[e'][\s\u00a0]+", "", name, flags=re.IGNORECASE).strip()

    @staticmethod
    def _normalize_amount(amount: str) -> str:
        """Normalize comma-decimal (1,5 → 1.5) and strip stray whitespace."""
        return amount.replace(",", ".").strip()

    # ------------------------------------------------------------------ #
    # Field extractors                                                     #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Название блюда."""
        # 1. JSON-LD
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get("name"):
            return self.clean_text(recipe["name"])

        # 2. Page h1
        h1 = self.soup.find("h1")
        if h1:
            return self.clean_text(h1.get_text())

        # 3. og:title
        og = self.soup.find("meta", property="og:title")
        if og and og.get("content"):
            return self.clean_text(og["content"])

        return None

    def extract_description(self) -> Optional[str]:
        """Краткое описание рецепта."""
        # 1. WPRM summary block (most natural, human-written text)
        summary = self.soup.find(
            "div",
            class_=lambda c: c and "wprm-recipe-summary" in c,
        )
        if summary:
            text = self.clean_text(summary.get_text(separator=" ", strip=True))
            if text:
                return text

        # 2. og:description (short SEO snippet)
        og_desc = self.soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            return self.clean_text(og_desc["content"])

        # 3. JSON-LD description
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get("description"):
            return self.clean_text(recipe["description"])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Ингредиенты из WPRM HTML-спанов (amount / unit / name).
        Возвращает JSON-строку списка словарей.
        """
        ingredient_items = self.soup.find_all(
            "li",
            class_=lambda c: c and "wprm-recipe-ingredient" in c,
        )

        if not ingredient_items:
            # Fallback: JSON-LD recipeIngredient strings
            recipe = self._get_recipe_jsonld()
            if recipe and recipe.get("recipeIngredient"):
                ingredients = []
                for raw in recipe["recipeIngredient"]:
                    parsed = self._parse_ingredient_string(raw)
                    if parsed:
                        ingredients.append(parsed)
                return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
            return None

        ingredients: List[dict] = []
        for li in ingredient_items:
            amount_span = li.find(
                "span", class_=lambda c: c and "wprm-recipe-ingredient-amount" in c
            )
            unit_span = li.find(
                "span", class_=lambda c: c and "wprm-recipe-ingredient-unit" in c
            )
            name_span = li.find(
                "span", class_=lambda c: c and "wprm-recipe-ingredient-name" in c
            )

            if not name_span:
                continue

            name = self._strip_french_particle(
                self.clean_text(name_span.get_text(separator=" ", strip=True))
            )
            if not name:
                continue

            amount = (
                self._normalize_amount(
                    self.clean_text(amount_span.get_text(strip=True))
                )
                if amount_span
                else None
            )
            unit = (
                self.clean_text(unit_span.get_text(strip=True))
                if unit_span
                else None
            )

            # Empty strings → None
            amount = amount or None
            unit = unit or None

            ingredients.append({"name": name, "amount": amount, "unit": unit})

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def _parse_ingredient_string(self, text: str) -> Optional[dict]:
        """
        Fallback parser for plain-text ingredient strings from JSON-LD.
        e.g. "40 g de Flocons de Riz"
        """
        text = self.clean_text(text)
        if not text:
            return None

        # Pattern: optional number(s) + optional unit + rest-as-name
        pattern = (
            r"^([\d\s/.,½¼¾⅓⅔⅛]+)?\s*"
            r"(g|kg|ml|cl|l|c\.\s?à\s?soupe|c\.\s?à\s?café|c\.\s?à\s?thé|"
            r"cuill?ères?\s?à\s?soupe|cuill?ères?\s?à\s?café|"
            r"poignée|pincée|sachet|tablette|feuill?e?s?|gousses?|"
            r"carrés?|pieces?|tranches?|unit)?\s*"
            r"(?:de\s|d')?\s*(.+)"
        )
        match = re.match(pattern, text, re.IGNORECASE)
        if not match:
            return {"name": text, "amount": None, "unit": None}

        amount_str, unit, name = match.groups()
        amount = self._normalize_amount(amount_str.strip()) if amount_str and amount_str.strip() else None
        unit = unit.strip() if unit else None
        name = self.clean_text(name) if name else None

        if not name:
            return {"name": text, "amount": None, "unit": None}

        return {"name": name, "amount": amount, "unit": unit}

    def extract_instructions(self) -> Optional[str]:
        """Шаги приготовления."""
        # 1. WPRM instruction items
        step_items = self.soup.find_all(
            "li",
            class_=lambda c: c and "wprm-recipe-instruction" in c,
        )

        steps = []
        for li in step_items:
            text_div = li.find(
                "div",
                class_=lambda c: c and "wprm-recipe-instruction-text" in c,
            )
            if text_div:
                step_text = self.clean_text(
                    text_div.get_text(separator=" ", strip=True)
                )
            else:
                step_text = self.clean_text(li.get_text(separator=" ", strip=True))

            if step_text:
                steps.append(step_text)

        if steps:
            numbered = [f"{i}. {s}" for i, s in enumerate(steps, 1)]
            return " ".join(numbered)

        # 2. JSON-LD recipeInstructions
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get("recipeInstructions"):
            instructions = recipe["recipeInstructions"]
            result_steps = []
            for idx, step in enumerate(instructions, 1):
                if isinstance(step, dict) and "text" in step:
                    text = self.clean_text(step["text"])
                elif isinstance(step, str):
                    text = self.clean_text(step)
                else:
                    continue
                if text:
                    result_steps.append(f"{idx}. {text}")
            if result_steps:
                return " ".join(result_steps)

        return None

    def extract_category(self) -> Optional[str]:
        """Категория рецепта."""
        recipe = self._get_recipe_jsonld()
        if recipe:
            categories = recipe.get("recipeCategory", [])
            if isinstance(categories, list) and categories:
                return ", ".join(self.clean_text(c) for c in categories if c)
            if isinstance(categories, str) and categories:
                return self.clean_text(categories)

        # Fallback: WPRM course span
        course_span = self.soup.find(
            "span",
            class_=lambda c: c and "wprm-recipe-course" in c,
        )
        if course_span:
            return self.clean_text(course_span.get_text(strip=True))

        return None

    def _extract_time_from_jsonld(self, time_key: str) -> Optional[str]:
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get(time_key):
            return self._parse_iso_duration(recipe[time_key])
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки."""
        return self._extract_time_from_jsonld("prepTime")

    def extract_cook_time(self) -> Optional[str]:
        """Время готовки."""
        return self._extract_time_from_jsonld("cookTime")

    def extract_total_time(self) -> Optional[str]:
        """Общее время."""
        return self._extract_time_from_jsonld("totalTime")

    def extract_notes(self) -> Optional[str]:
        """Заметки/советы к рецепту из блока WPRM notes."""
        notes_div = self.soup.find(
            "div",
            class_=lambda c: c and "wprm-recipe-notes" in c,
        )
        if not notes_div:
            return None

        text = self.clean_text(notes_div.get_text(separator=" ", strip=True))
        # Strip the generic promotional call-to-action that appears on every page
        text = re.sub(
            r"VOUS\s+R[ÉE]ALISEZ\s+CETTE\s+RECETTE.*",
            "",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        ).strip()
        # Also strip the label "LE PETIT PLUS" often used as a heading
        text = re.sub(r"^LE PETIT PLUS\s*", "", text, flags=re.IGNORECASE).strip()
        return text if text else None

    def extract_tags(self) -> Optional[str]:
        """Теги рецепта из JSON-LD keywords."""
        recipe = self._get_recipe_jsonld()
        if recipe:
            keywords = recipe.get("keywords")
            if keywords and isinstance(keywords, str):
                return keywords.strip()
            if keywords and isinstance(keywords, list):
                return ", ".join(k.strip() for k in keywords if k.strip())

        return None

    def extract_image_urls(self) -> Optional[str]:
        """URL изображений рецепта."""
        urls: List[str] = []
        seen: set = set()

        def _add(url: str) -> None:
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        # 1. JSON-LD Recipe.image (list of sizes or strings)
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get("image"):
            img = recipe["image"]
            if isinstance(img, str):
                _add(img)
            elif isinstance(img, list):
                for i in img:
                    if isinstance(i, str):
                        _add(i)
                    elif isinstance(i, dict):
                        _add(i.get("url") or i.get("contentUrl", ""))
            elif isinstance(img, dict):
                _add(img.get("url") or img.get("contentUrl", ""))

        # 2. og:image fallback
        og_img = self.soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            _add(og_img["content"])

        return ",".join(urls) if urls else None

    # ------------------------------------------------------------------ #
    # Main public method                                                   #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта."""
        try:
            dish_name = self.extract_dish_name()
        except Exception as e:
            logger.warning("Error extracting dish_name: %s", e)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as e:
            logger.warning("Error extracting description: %s", e)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as e:
            logger.warning("Error extracting ingredients: %s", e)
            ingredients = None

        try:
            instructions = self.extract_instructions()
        except Exception as e:
            logger.warning("Error extracting instructions: %s", e)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as e:
            logger.warning("Error extracting category: %s", e)
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception as e:
            logger.warning("Error extracting prep_time: %s", e)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception as e:
            logger.warning("Error extracting cook_time: %s", e)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception as e:
            logger.warning("Error extracting total_time: %s", e)
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception as e:
            logger.warning("Error extracting notes: %s", e)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as e:
            logger.warning("Error extracting tags: %s", e)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as e:
            logger.warning("Error extracting image_urls: %s", e)
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
    """Точка входа для обработки HTML файлов cuisinersansgluten.com"""
    preprocessed_dir = os.path.join("preprocessed", "cuisinersansgluten_com")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка файлов из директории: {preprocessed_dir}")
        process_directory(CuisinersansGlutenComExtractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python cuisinersansgluten_com.py")


if __name__ == "__main__":
    main()
