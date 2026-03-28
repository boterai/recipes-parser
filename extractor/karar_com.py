"""
Экстрактор данных рецептов для сайта karar.com
"""

import logging
import sys
import json
import re
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Turkish unit words used for ingredient parsing
TURKISH_UNITS = [
    "yemek kaşığı", "çay kaşığı", "su bardağı", "çay bardağı",
    "kilogram", "gram", "mililitre", "litre",
    "kg", "ml", "lt",
    "adet", "diş", "demet", "tutam", "dal", "dilim",
    "kutu", "paket", "avuç", "bağ", "tane", "kase",
    "çimdik", "fiske",
]

# Turkish number words → numeric values
TURKISH_NUMBER_WORDS = {
    "bir": "1", "iki": "2", "üç": "3", "dört": "4", "beş": "5",
    "altı": "6", "yedi": "7", "sekiz": "8", "dokuz": "9", "on": "10",
    "yarım": "0.5", "çeyrek": "0.25",
}

# Keywords that signal the ingredients section (normalized to Python .lower() output)
INGREDIENT_KEYWORDS = [
    "malzemeler", "malzeme", "gerekli malzeme", "gerekli malzemeler",
    "ingredients",
]

# Keywords that signal the instructions section (normalized to Python .lower() output)
# Note: Turkish I (U+0049) → i (U+0069) in Python .lower(), so use 'i' not 'ı'
INSTRUCTION_KEYWORDS = [
    "hazirlanişi", "hazirlanis", "hazirlanisi",
    "yapilişi", "yapilis",
    "adim adim", "adimlar",
    "nasil yapilir", "pisirme",
    "instructions",
]

# Keywords that signal the notes section
NOTES_KEYWORDS = [
    "püf noktas", "puf noktas",
    "ipucu", "ipuclari", "ipuçları",
    "not:", "notlar", "öneriler", "tavsiyeler",
    "tips",
]


class KararComExtractor(BaseRecipeExtractor):
    """Экстрактор для karar.com"""

    # ------------------------------------------------------------------ helpers

    def _is_gallery_page(self) -> bool:
        """Проверяет, является ли страница галерейного типа (slideshow)."""
        gallery = self.soup.find(class_="gallery-list")
        if gallery and gallery.find("figure"):
            return True
        return False

    def _get_json_ld(self) -> list:
        """Возвращает список всех JSON-LD объектов со страницы."""
        result = []
        for script in self.soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    result.extend(data)
                elif isinstance(data, dict):
                    # unwrap @graph if present
                    if "@graph" in data:
                        result.extend(data["@graph"])
                    else:
                        result.append(data)
            except (json.JSONDecodeError, TypeError):
                pass
        return result

    def _get_gallery_figures(self):
        """Возвращает список figure элементов галереи (только для gallery-type)."""
        gallery = self.soup.find(class_="gallery-list")
        if gallery:
            return gallery.find_all("figure")
        return []

    def _get_article_text_content(self):
        """Возвращает div.text-content для статейного типа страницы."""
        return self.soup.find(class_="text-content")

    @staticmethod
    def _normalize_tr(text: str) -> str:
        """
        Нормализует турецкий текст для регистронезависимого сравнения.
        Конвертирует спец. символы к ASCII-эквивалентам.
        """
        return (
            text.lower()
            .replace("ı", "i")   # Turkish dotless i → i
            .replace("İ", "i")   # Turkish dotted capital I → i
            .replace("ğ", "g")
            .replace("Ğ", "g")
            .replace("ş", "s")
            .replace("Ş", "s")
            .replace("ç", "c")
            .replace("Ç", "c")
            .replace("ö", "o")
            .replace("Ö", "o")
            .replace("ü", "u")
            .replace("Ü", "u")
        )

    @staticmethod
    def _heading_matches(heading_text: str, keywords: list) -> bool:
        """Проверяет, содержит ли текст заголовка хотя бы одно ключевое слово."""
        lower = heading_text.lower()
        return any(kw in lower for kw in keywords)

    # ------------------------------------------------------------- dish name

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда."""
        # 1. content-title div
        ct = self.soup.find(class_="content-title")
        if ct:
            text = self.clean_text(ct.get_text())
            if text:
                return text

        # 2. h1 tag
        h1 = self.soup.find("h1")
        if h1:
            text = self.clean_text(h1.get_text())
            if text:
                return text

        # 3. og:title meta
        og_title = self.soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return self.clean_text(og_title["content"])

        return None

    # ----------------------------------------------------------- description

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта."""
        # 1. content-description div
        cd = self.soup.find(class_="content-description")
        if cd:
            text = self.clean_text(cd.get_text())
            if text:
                return text

        # 2. meta description
        meta_desc = self.soup.find("meta", {"name": "description"})
        if meta_desc and meta_desc.get("content"):
            return self.clean_text(meta_desc["content"])

        # 3. og:description meta
        og_desc = self.soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            return self.clean_text(og_desc["content"])

        return None

    # ------------------------------------------------------------ ingredients

    def _parse_ingredient_line(self, text: str) -> list:
        """
        Парсит строку ингредиента в структурированный формат.

        Returns:
            Список из одного или более dict {"name", "amount", "unit"}.
        """
        if not text:
            return []

        text = self.clean_text(text)
        # Remove trailing parenthetical notes like "(İnce doğranmış)" → put in name
        # Keep them because they describe the ingredient state

        # Normalize number words to digits
        normalized = text
        for word, digit in TURKISH_NUMBER_WORDS.items():
            normalized = re.sub(
                rf"\b{re.escape(word)}\b", digit, normalized, flags=re.IGNORECASE
            )

        # Build regex for Turkish units (longest first to avoid partial matches)
        units_sorted = sorted(TURKISH_UNITS, key=len, reverse=True)
        unit_pattern = "|".join(re.escape(u) for u in units_sorted)

        # Pattern: optional_amount unit name
        # e.g. "2 adet büyük boy yumurta", "125 gram tereyağı"
        pattern = re.compile(
            rf"""^
            (?P<amount>[\d]+(?:[,./]\d+)?(?:\s*-\s*[\d]+(?:[,./]\d+)?)?)  # numeric amount, optional range
            \s+
            (?P<unit>{unit_pattern})                                         # Turkish unit
            \s+
            (?P<name>.+)                                                    # ingredient name
            $""",
            re.VERBOSE | re.IGNORECASE,
        )

        # Special case: "1 kutu (400 gr) name" → amount="1 kutu", unit="400 gr", name=name
        kutu_pattern = re.compile(
            r"^(\d+)\s+kutu\s+\(([^)]+)\)\s+(.+)$", re.IGNORECASE
        )
        kutu_match = kutu_pattern.match(text)
        if kutu_match:
            return [
                {
                    "name": self.clean_text(kutu_match.group(3)),
                    "amount": f"{kutu_match.group(1)} kutu",
                    "unit": self.clean_text(kutu_match.group(2)),
                }
            ]

        # Check "X veya Y unit name" → two entries
        veya_amount = re.match(
            rf"^(\d+)\s+veya\s+(\d+)\s+({unit_pattern})\s+(.+)$",
            normalized,
            re.IGNORECASE,
        )
        if veya_amount:
            unit = veya_amount.group(3)
            name = self.clean_text(veya_amount.group(4))
            # remove trailing parenthetical from name
            name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
            return [
                {"name": name, "amount": veya_amount.group(1), "unit": unit},
                {"name": name, "amount": veya_amount.group(2), "unit": unit},
            ]

        # Try standard pattern
        m = pattern.match(normalized)
        if m:
            amount = m.group("amount").strip()
            unit = m.group("unit").strip()
            name = self.clean_text(m.group("name"))
            # Strip trailing parenthetical from name for cleanliness
            # but keep as part of name if it's a flavor/state descriptor
            name = re.sub(r"\s*\(isteğe bağlı[^)]*\)\s*", "", name, flags=re.IGNORECASE).strip()
            name = re.sub(r"\s*\(damak tadına göre[^)]*\)\s*", "", name, flags=re.IGNORECASE).strip()
            name = re.sub(r"\s*\(servis için[^)]*\)\s*", "", name, flags=re.IGNORECASE).strip()
            # normalize amount
            amount = re.sub(r"\s+", "", amount)  # remove spaces in amount range
            return [{"name": name if name else text, "amount": amount, "unit": unit}]

        # Pattern: "bir tutam X ve Y" or "bir tutam X"
        tutam_match = re.match(
            r"^(bir\s+tutam|bir\s+fiske|bir\s+çimdik)\s+(.+)$",
            normalized, re.IGNORECASE
        )
        if tutam_match:
            amount_str = tutam_match.group(1)
            rest = tutam_match.group(2)
            # Split on " ve " to get multiple items
            parts = re.split(r"\s+ve\s+", rest, flags=re.IGNORECASE)
            results = []
            for part in parts:
                part = self.clean_text(part)
                if part:
                    results.append({"name": part, "amount": amount_str, "unit": None})
            return results if results else [{"name": text, "amount": None, "unit": None}]

        # Fallback: check if line contains " ve " (and) → split into multiple ingredients
        # Only split if there's no numeric amount and no unit (pure ingredient list)
        if " ve " in text.lower() and not re.match(r"^\d", normalized):
            parts = re.split(r"\s+ve\s+", text, flags=re.IGNORECASE)
            if len(parts) >= 2:
                results = []
                for part in parts:
                    part = self.clean_text(part)
                    # Remove trailing parenthetical
                    part = re.sub(r"\s*\([^)]*\)\s*$", "", part).strip()
                    if part:
                        results.append({"name": part, "amount": None, "unit": None})
                return results if results else [{"name": text, "amount": None, "unit": None}]

        # No amount found: entire text is ingredient name
        name = self.clean_text(text)
        # Remove trailing notes
        name = re.sub(r"\s*\(isteğe bağlı[^)]*\)\s*$", "", name, flags=re.IGNORECASE).strip()
        name = re.sub(r"\s*\(damak tadına göre[^)]*\)\s*$", "", name, flags=re.IGNORECASE).strip()
        return [{"name": name if name else text, "amount": None, "unit": None}]

    def _extract_ingredients_from_container(self, container) -> list:
        """Извлекает список ингредиентов из HTML-контейнера."""
        ingredients = []
        if not container:
            return ingredients

        # Try ul > li structure first
        items = container.find_all("li")
        if items:
            for item in items:
                text = self.clean_text(item.get_text(separator=" ", strip=True))
                if text:
                    parsed = self._parse_ingredient_line(text)
                    ingredients.extend(parsed)
            return ingredients

        # Fallback: p tags
        for p in container.find_all("p"):
            text = self.clean_text(p.get_text(separator=" ", strip=True))
            if not text:
                continue
            # Skip lines that look like headings
            if text.isupper() or re.match(r"^[A-ZÇĞİÖŞÜa-zçğışöüñ\s]+:$", text):
                continue
            # Skip lines that are section headings (all caps Turkish)
            if re.match(r"^[A-ZÇĞİÖŞÜ\s\(\)/-]+$", text) and len(text) < 50:
                continue
            parsed = self._parse_ingredient_line(text)
            ingredients.extend(parsed)
        return ingredients

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов."""
        ingredients = []

        if self._is_gallery_page():
            ingredients = self._extract_ingredients_gallery()
        else:
            ingredients = self._extract_ingredients_article()

        if not ingredients:
            logger.warning("No ingredients found in %s", self.html_path)
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def _extract_ingredients_gallery(self) -> list:
        """Извлечение ингредиентов из галерейного формата страницы."""
        figures = self._get_gallery_figures()
        for fig in figures:
            tc = fig.find(class_="text-content")
            if not tc:
                continue
            # Check if this slide is the ingredients slide
            headings = tc.find_all(["h2", "h3", "h4", "strong"])
            for h in headings:
                h_text = self._normalize_tr(h.get_text(strip=True))
                if any(kw in h_text for kw in INGREDIENT_KEYWORDS):
                    # Extract from blockquote or the text-content directly
                    bq = tc.find("blockquote")
                    container = bq if bq else tc
                    return self._extract_ingredients_from_container(container)
        return []

    def _extract_ingredients_article(self) -> list:
        """Извлечение ингредиентов из статейного формата страницы."""
        tc = self._get_article_text_content()
        if not tc:
            return []

        # Find blockquote with ingredient heading
        for bq in tc.find_all("blockquote"):
            headings = bq.find_all(["h2", "h3", "h4", "strong", "p"])
            for h in headings:
                h_text = self._normalize_tr(h.get_text(strip=True))
                if any(kw in h_text for kw in INGREDIENT_KEYWORDS):
                    return self._extract_ingredients_from_container(bq)

        # Fallback: look for any heading with ingredient keyword, collect what follows
        for heading in tc.find_all(["h2", "h3", "h4"]):
            h_text = self._normalize_tr(heading.get_text(strip=True))
            if any(kw in h_text for kw in INGREDIENT_KEYWORDS):
                # Collect sibling elements until next heading
                items = []
                for sib in heading.find_next_siblings():
                    if sib.name in ("h2", "h3", "h4"):
                        break
                    items_in_sib = sib.find_all("li")
                    if items_in_sib:
                        items.extend(items_in_sib)
                    else:
                        text = self.clean_text(sib.get_text(separator=" ", strip=True))
                        if text and len(text) < 200:
                            items.append(sib)
                result = []
                for item in items:
                    text = self.clean_text(item.get_text(separator=" ", strip=True))
                    if text:
                        result.extend(self._parse_ingredient_line(text))
                return result

        return []

    # ---------------------------------------------------------- instructions

    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления."""
        if self._is_gallery_page():
            return self._extract_instructions_gallery()
        else:
            return self._extract_instructions_article()

    def _extract_instructions_gallery(self) -> Optional[str]:
        """Извлечение инструкций из галерейного формата."""
        figures = self._get_gallery_figures()
        steps = []
        collecting = False

        for fig in figures:
            tc = fig.find(class_="text-content")
            if not tc:
                continue

            # Check headings to detect the instructions slide
            headings = tc.find_all(["h2", "h3", "h4", "strong"])
            for h in headings:
                h_text = self._normalize_tr(h.get_text(strip=True))
                if any(kw in h_text for kw in INSTRUCTION_KEYWORDS):
                    collecting = True
                    break

            if not collecting:
                continue

            # Collect step text from this slide onwards
            slide_steps = []
            # Try <ul>/<ol> items
            list_items = tc.find_all("li")
            if list_items:
                for li in list_items:
                    text = self.clean_text(li.get_text(separator=" ", strip=True))
                    if text and self._normalize_tr(text) != "afiyet olsun!":
                        slide_steps.append(text)
            else:
                # Fallback: collect <p> that are not headings or "AFİYET OLSUN!"
                for p in tc.find_all("p"):
                    text = self.clean_text(p.get_text(separator=" ", strip=True))
                    if text and self._normalize_tr(text) != "afiyet olsun!":
                        slide_steps.append(text)

            steps.extend(slide_steps)

        if not steps:
            return None

        # Add step numbering if not already numbered
        numbered = []
        step_num = 1
        for step in steps:
            if re.match(r"^\d+\.", step):
                numbered.append(step)
            else:
                numbered.append(f"{step_num}. {step}")
                step_num += 1

        return "\n".join(numbered)

    def _extract_instructions_article(self) -> Optional[str]:
        """Извлечение инструкций из статейного формата."""
        tc = self._get_article_text_content()
        if not tc:
            return None

        steps = []

        # Look for <ol> lists (numbered steps)
        ol = tc.find("ol")
        if ol:
            items = ol.find_all("li")
            for item in items:
                # Remove ads from inside li
                for ad in item.find_all("div"):
                    ad.decompose()
                text = self.clean_text(item.get_text(separator=" ", strip=True))
                if text:
                    steps.append(text)

        if steps:
            # Add numbering
            numbered = []
            for i, step in enumerate(steps, 1):
                numbered.append(f"{i}. {step}")
            return "\n".join(numbered)

        # Fallback: look for heading with instruction keyword, collect following content
        for heading in tc.find_all(["h2", "h3", "h4"]):
            h_text = self._normalize_tr(heading.get_text(strip=True))
            if any(kw in h_text for kw in INSTRUCTION_KEYWORDS):
                collected_steps = []
                for sib in heading.find_next_siblings():
                    if sib.name in ("h2", "h3", "h4"):
                        # Stop at next heading that is NOT a step heading
                        sib_text = self._normalize_tr(sib.get_text(strip=True))
                        if not any(kw in sib_text for kw in INSTRUCTION_KEYWORDS):
                            break
                    # Gather <li> items
                    list_items = sib.find_all("li")
                    if list_items:
                        for li in list_items:
                            text = self.clean_text(li.get_text(separator=" ", strip=True))
                            if text:
                                collected_steps.append(text)
                    elif sib.name == "p":
                        text = self.clean_text(sib.get_text(separator=" ", strip=True))
                        if text and not sib.get("class"):
                            collected_steps.append(text)
                steps = collected_steps
                break

        # Murtağa-style: numbered bold paragraphs followed by explanation paragraphs
        if not steps:
            steps = self._extract_instructions_from_bold_paragraphs(tc)

        if not steps:
            return None

        # Re-check / add numbering
        numbered = []
        step_num = 1
        for step in steps:
            if re.match(r"^\d+\.", step):
                numbered.append(step)
            else:
                numbered.append(f"{step_num}. {step}")
                step_num += 1

        return "\n".join(numbered)

    def _extract_instructions_from_bold_paragraphs(self, tc) -> list:
        """
        Извлечение шагов из формата: <p><strong>N. ЗАГОЛОВОК:</strong></p><p>текст</p>
        Характерно для страниц типа murtağa.
        """
        steps = []
        all_paragraphs = tc.find_all("p")
        i = 0
        while i < len(all_paragraphs):
            p = all_paragraphs[i]
            # Check if paragraph is a step heading: starts with "N. " or "N."
            text = self.clean_text(p.get_text(separator=" ", strip=True))
            strong = p.find("strong")
            if strong and re.match(r"^\d+\.", text):
                # This is a step heading; collect the next paragraph(s) as the step body
                step_title = text.rstrip(":")
                body_parts = [step_title]
                j = i + 1
                while j < len(all_paragraphs):
                    next_p = all_paragraphs[j]
                    next_text = self.clean_text(next_p.get_text(separator=" ", strip=True))
                    next_strong = next_p.find("strong")
                    # Stop if next paragraph is also a step heading
                    if next_strong and re.match(r"^\d+\.", next_text):
                        break
                    if next_text and not next_p.get("class"):
                        body_parts.append(next_text)
                    j += 1
                steps.append(" ".join(body_parts))
                i = j
            else:
                i += 1
        return steps

    # --------------------------------------------------------------- category

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из хлебных крошек или JSON-LD."""
        # From JSON-LD BreadcrumbList
        for item in self._get_json_ld():
            if item.get("@type") == "BreadcrumbList":
                elements = item.get("itemListElement", [])
                # Return the second item (first is homepage)
                for el in elements:
                    if el.get("position") == 2:
                        name = el.get("name", "")
                        if name and name.lower() not in ("anasayfa", "home"):
                            return self.clean_text(name)

        # From breadcrumbs div: skip first (home) and last (current page)
        bc = self.soup.find(class_="breadcrumbs")
        if bc:
            links = bc.find_all("a")
            # links: [home, category, ..., current]
            if len(links) >= 2:
                # Second link is usually the section
                cat = self.clean_text(links[1].get_text())
                if cat and cat.lower() not in ("anasayfa", "home"):
                    return cat

        return None

    # --------------------------------------------------------------- time helpers

    @staticmethod
    def _extract_time_from_text(text: str) -> Optional[str]:
        """
        Пытается извлечь время из текста.
        Примеры: "15 dakika", "12-15 dakika", "1 saat 30 dakika".
        """
        if not text:
            return None
        # Pattern: number(s) + dakika/saat
        m = re.search(
            r"(\d+(?:\s*-\s*\d+)?)\s*(dakika|saat|minute|hour)",
            text,
            re.IGNORECASE,
        )
        if m:
            value = re.sub(r"\s+", "", m.group(1))  # compress spaces in range
            unit = m.group(2).lower()
            return f"{value} {unit}"
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки."""
        # Look in description for "hazırlık X dakika" or "X dakikada hazır"
        desc = self.extract_description() or ""
        prep_patterns = [
            r"hazırlık\s+süresi[:\s]+([^\.,\n]+dakika)",
            r"hazırlaması\s+yalnızca\s+(\d+(?:\s*-\s*\d+)?\s*dakika)",
            r"hazırlanması\s+yalnızca\s+(\d+(?:\s*-\s*\d+)?\s*dakika)",
        ]
        for pat in prep_patterns:
            m = re.search(pat, desc, re.IGNORECASE)
            if m:
                return self.clean_text(m.group(1))
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления."""
        # From article format: look for heading "HAZIRLANIŞI YAKLAŞIK X DAKİKA"
        tc = self._get_article_text_content()
        if tc:
            for heading in tc.find_all(["h2", "h3", "h4"]):
                h_text = heading.get_text(strip=True)
                h_norm = self._normalize_tr(h_text)
                if any(kw in h_norm for kw in INSTRUCTION_KEYWORDS):
                    t = self._extract_time_from_text(h_text)
                    if t:
                        return t

        # From gallery: look in all text-content for time near cook-related words
        if self._is_gallery_page():
            figures = self._get_gallery_figures()
            for fig in figures:
                tc_fig = fig.find(class_="text-content")
                if not tc_fig:
                    continue
                text = tc_fig.get_text(" ", strip=True)
                # Look for cook time patterns
                patterns = [
                    r"fırında\s+yaklaşık\s+(\d+(?:\s*-\s*\d+)?\s*dakika)",
                    r"pişirin[^.]*(\d+(?:\s*-\s*\d+)?\s*dakika)",
                    r"(\d+(?:\s*-\s*\d+)?\s*dakika)\s+(?:daha\s+)?pişirin",
                ]
                for pat in patterns:
                    m = re.search(pat, text, re.IGNORECASE)
                    if m:
                        return self.clean_text(m.group(1))

        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени приготовления."""
        # From description: "toplamda X dakika" or "X dakikada hazır"
        desc = self.extract_description() or ""
        total_patterns = [
            r"toplamda\s+(?:sadece\s+)?(\d+(?:\s*-\s*\d+)?\s*dakikayı\b|\d+(?:\s*-\s*\d+)?\s*dakika\b)",
            r"yalnızca\s+(\d+(?:\s*-\s*\d+)?\s*dakika)",
            r"(\d+(?:\s*-\s*\d+)?\s*dakikada(?:\s+hazır)?)",
        ]
        for pat in total_patterns:
            m = re.search(pat, desc, re.IGNORECASE)
            if m:
                raw = m.group(1)
                # Extract number + dakika
                t = self._extract_time_from_text(raw)
                return t if t else self.clean_text(raw)

        # Also check in the recipe title heading inside text-content
        tc = self._get_article_text_content()
        if tc:
            for heading in tc.find_all(["h2", "h3", "h4"]):
                h_text = heading.get_text(strip=True)
                m = re.match(r"^(\d+)\s*DAKİKADA\b", h_text, re.IGNORECASE)
                if m:
                    return f"{m.group(1)} dakika"
        return None

    # --------------------------------------------------------------- notes

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов."""
        tc = self._get_article_text_content()
        if not tc:
            # For gallery pages, check last figures
            if self._is_gallery_page():
                return self._extract_notes_gallery()
            return None

        # Look for notes heading in article
        for heading in tc.find_all(["h2", "h3", "h4"]):
            h_text = self._normalize_tr(heading.get_text(strip=True))
            if any(kw in h_text for kw in NOTES_KEYWORDS):
                parts = []
                for sib in heading.find_next_siblings():
                    if sib.name in ("h2", "h3", "h4"):
                        break
                    text = self.clean_text(sib.get_text(separator=" ", strip=True))
                    if text:
                        parts.append(text)
                if parts:
                    return " ".join(parts)

        return None

    def _extract_notes_gallery(self) -> Optional[str]:
        """Извлечение заметок из галерейного формата (если есть)."""
        figures = self._get_gallery_figures()
        for fig in figures:
            tc = fig.find(class_="text-content")
            if not tc:
                continue
            text_norm = self._normalize_tr(tc.get_text(" ", strip=True))
            for kw in NOTES_KEYWORDS:
                if kw in text_norm:
                    return self.clean_text(tc.get_text(separator=" ", strip=True))
        return None

    # --------------------------------------------------------------- tags

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов."""
        tl = self.soup.find(class_="tag-list")
        if tl:
            links = tl.find_all("a")
            tags = [self.clean_text(a.get_text()) for a in links if a.get_text(strip=True)]
            if tags:
                return ", ".join(tags)

        # Fallback: article:tag meta
        tag_metas = self.soup.find_all("meta", property="article:tag")
        if tag_metas:
            tags = [
                self.clean_text(m.get("content", ""))
                for m in tag_metas
                if m.get("content")
            ]
            if tags:
                return ", ".join(tags)

        return None

    # --------------------------------------------------------------- images

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта."""
        urls = []

        if self._is_gallery_page():
            # Extract from each figure's image
            for fig in self._get_gallery_figures():
                img_div = fig.find(class_="i")
                if img_div:
                    img = img_div.find("img")
                    if img:
                        src = img.get("src") or img.get("data-src", "")
                        if src and src.startswith("http"):
                            urls.append(src)
        else:
            # Extract from text-content images (skip thumbnail/related images)
            tc = self._get_article_text_content()
            if tc:
                for img in tc.find_all("img"):
                    src = img.get("src") or img.get("data-src", "")
                    if src and src.startswith("http"):
                        # Skip small thumbnails (news_t/ path)
                        if "/news_t/" not in src:
                            urls.append(src)

        # Always include og:image as a fallback / primary
        og_image = self.soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            og_url = og_image["content"]
            if og_url not in urls:
                urls.insert(0, og_url)

        # Deduplicate preserving order
        seen: set = set()
        unique: list = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ",".join(unique) if unique else None

    # --------------------------------------------------------------- extract_all

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта.
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception as e:
            logger.error("Error extracting dish_name: %s", e)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as e:
            logger.error("Error extracting description: %s", e)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as e:
            logger.error("Error extracting ingredients: %s", e)
            ingredients = None

        try:
            instructions = self.extract_instructions()
        except Exception as e:
            logger.error("Error extracting instructions: %s", e)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as e:
            logger.error("Error extracting category: %s", e)
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception as e:
            logger.error("Error extracting prep_time: %s", e)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception as e:
            logger.error("Error extracting cook_time: %s", e)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception as e:
            logger.error("Error extracting total_time: %s", e)
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception as e:
            logger.error("Error extracting notes: %s", e)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as e:
            logger.error("Error extracting tags: %s", e)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as e:
            logger.error("Error extracting image_urls: %s", e)
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


def main():
    import os

    recipes_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "preprocessed",
        "karar_com",
    )
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(KararComExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python karar_com.py")


if __name__ == "__main__":
    main()
