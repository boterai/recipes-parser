"""
Экстрактор данных рецептов для сайта videorecepti.domashnakunyasdani.com

Структура HTML страниц:
- Название блюда: h1.entry-title
- Описание: <p> после первого вводного h2 (с emoji 🌿/🥔/etc), либо meta description
- Ингредиенты: <ul> после h2/h3 с "Необходими продукти" / "Съставки"
- Инструкции: h3-шаги + <ol> под h2 "Начин на приготвяне"
- Таблица обобщения: h2 "Обобщение" → <table> с полями (Подготовка, Готвене, Общо, Тип ястие)
- Заметки: <p> после h2 "Малък трик" или "Съвети"
- Теги: span.entry-meta-tags в первой (главной) статье
- Изображения: og:image + img[src*=wp-content/uploads] в entry-content
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class VideoReceptiDomashnakunyasdaniComExtractor(BaseRecipeExtractor):
    """Экстрактор для videorecepti.domashnakunyasdani.com"""

    # ------------------------------------------------------------------ helpers

    def _get_entry_content(self):
        """Return the main entry-content div."""
        return self.soup.find("div", class_="entry-content")

    def _get_summary_table(self) -> Dict[str, str]:
        """
        Parse the summary table (📋 Обобщение на рецептата) and return its
        rows as {Показател: Стойност} dict.
        """
        entry = self._get_entry_content()
        if not entry:
            return {}

        # Locate the summary section by h2 heading
        for h2 in entry.find_all("h2"):
            text = h2.get_text(strip=True)
            if "обобщение" in text.lower() or "📋" in text:
                next_el = h2.find_next_sibling()
                while next_el:
                    if next_el.name == "table":
                        rows: Dict[str, str] = {}
                        for row in next_el.find_all("tr"):
                            cells = [
                                self.clean_text(td.get_text())
                                for td in row.find_all(["td", "th"])
                            ]
                            if len(cells) == 2 and cells[0] and cells[1]:
                                rows[cells[0]] = cells[1]
                        return rows
                    if next_el.name == "h2":
                        break
                    next_el = next_el.find_next_sibling()

        # Fallback: any table that contains timing keywords
        if entry:
            for table in entry.find_all("table"):
                rows = {}
                for row in table.find_all("tr"):
                    cells = [
                        self.clean_text(td.get_text())
                        for td in row.find_all(["td", "th"])
                    ]
                    if len(cells) == 2 and cells[0] and cells[1]:
                        rows[cells[0]] = cells[1]
                if "Подготовка" in rows or "Готвене" in rows or "Общо" in rows:
                    return rows

        return {}

    # --------------------------------------------------------- ingredient parsing

    # Known Bulgarian units (longest first for greedy matching)
    _UNITS_PATTERN = (
        r"(?:"
        r"с\.?\s*л\."          # с. л. / с.л. (tablespoon)
        r"|ч\.?\s*л\."         # ч. л. / ч.л. (teaspoon)
        r"|бр\.?"              # бр. / бр (pieces)
        r"|глав[аи]"           # глава / глави (head)
        r"|цял[аое]"           # цяло (whole)
        r"|мл"                 # мл (ml)
        r"|кг"                 # кг (kg)
        r"|гр?\.?"             # г / гр (g)
        r"|л(?=\s|$)"          # л (litre) — only when followed by space/end
        r"|ml|kg|g|l"          # Latin equivalents
        r")"
    )

    def _parse_amount_unit(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse 'amount unit' from a fragment like '400 г', '3 с.л.', 'на вкус',
        'около 500 мл', '1 глава'.

        Returns (amount_str, unit_str) – either may be None.
        """
        text = text.strip()
        if not text:
            return None, None

        # "на вкус" → treat as special unit
        if re.match(r"^на\s+вкус$", text, re.I):
            return None, "на вкус"

        # Optional 'около' prefix, then number, then optional unit
        match = re.match(
            r"^(?:около\s+|~\s*)?"
            r"([\d][\d\s.,/–-]*)?"
            r"\s*(.+)?$",
            text,
            re.I,
        )
        if not match:
            return None, text or None

        amount_raw = (match.group(1) or "").strip()
        unit_raw = (match.group(2) or "").strip() or None

        amount: Optional[str] = None
        if amount_raw:
            amount = amount_raw.rstrip("-–").strip()
            if not re.search(r"\d", amount):
                unit_raw = (amount + " " + (unit_raw or "")).strip() or None
                amount = None

        return amount or None, unit_raw or None

    def _parse_ingredient_text(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Convert a raw ingredient line to {name, amount, unit}.

        Handles Bulgarian formats:
          1. "Name – amount unit"   e.g. "Лапад – 400 г"
          2. "amount unit name"     e.g. "100 г разтопено масло", "1 ч. л. захар"
          3. "amount name"          e.g. "2 белтъка", "1 цяло яйце"
          4. Plain name             e.g. "Брашно за разточване"
        """
        if not text:
            return None

        text = self.clean_text(text)
        if not text:
            return None

        # Strip parenthetical qualifiers
        clean = re.sub(r"\([^)]*\)", "", text).strip()
        # Remove alternative after "или" only at end of string
        clean = re.sub(r"\s+или\s+\d.*$", "", clean).strip()

        # ── Format 1: "NAME – AMOUNT UNIT" ────────────────────────────────────
        # The name must start with a letter (not a digit)
        dash_match = re.match(
            r"^([А-яA-Za-z].+?)\s*[–—]\s*(?:около\s+)?(.*)\s*$", clean
        )
        if dash_match:
            name_part = dash_match.group(1).strip()
            amount_unit_part = dash_match.group(2).strip()
            if name_part and amount_unit_part:
                amount, unit = self._parse_amount_unit(amount_unit_part)
                return {"name": name_part, "amount": amount, "unit": unit}
            elif name_part and not amount_unit_part:
                # Dash without amount (e.g. "Брашно – колкото поеме")
                return {"name": name_part, "amount": None, "unit": None}

        # ── Format 2: "AMOUNT UNIT NAME" ──────────────────────────────────────
        # Try to match with known unit pattern
        unit_first_match = re.match(
            r"^([\d][–\d\s.,/]*)"          # amount (possibly range like 2–3)
            r"\s+"
            r"(" + self._UNITS_PATTERN + r")"   # unit
            r"\s+"
            r"(.+)$",                            # name
            clean,
            re.I,
        )
        if unit_first_match:
            amount_str = unit_first_match.group(1).strip().rstrip("–-").strip()
            unit_str = unit_first_match.group(2).strip()
            name_str = unit_first_match.group(3).strip()
            return {"name": name_str, "amount": amount_str, "unit": unit_str}

        # ── Format 3: "NUMBER NAME" (no explicit unit) ────────────────────────
        num_name = re.match(r"^([\d][–\d.,/]*)\s+(.+)$", clean)
        if num_name:
            return {
                "name": num_name.group(2).strip(),
                "amount": num_name.group(1).strip().rstrip("–-").strip(),
                "unit": None,
            }

        # ── Fallback: just a name ──────────────────────────────────────────────
        return {"name": clean, "amount": None, "unit": None}

    # ---------------------------------------------------------- public extractors

    def extract_dish_name(self) -> Optional[str]:
        """
        Название блюда.

        Предпочтительный источник – первый вводный h2 в entry-content
        (до заголовков ингредиентов / инструкций).  Из него берётся часть
        до тире «–», очищенная от emoji.  Если такого h2 нет, используется h1.
        """
        # Ключевые слова «функциональных» заголовков
        _FUNC = {
            "продукт", "съставки", "необход",
            "приготвяне", "начин", "стъпки",
            "обобщение", "енергийни", "вариации",
            "въпроси", "съвети", "трик",
        }

        entry = self._get_entry_content()
        if entry:
            for h2 in entry.find_all("h2"):
                text = h2.get_text(strip=True)
                text_lower = text.lower()
                if any(kw in text_lower for kw in _FUNC):
                    # Hit a functional heading before finding an intro → stop
                    break
                if text:
                    # Strip leading emoji / non-letter characters
                    name = re.sub(r"^[^\w\u0400-\u04FF]+", "", text).strip()
                    # Keep only the part before " – " or " — "
                    name = re.split(r"\s*[–—]\s*", name)[0].strip()
                    if name:
                        return self.clean_text(name)

        # Fallback: h1 (strip descriptive suffix after " – ")
        h1 = self.soup.find("h1", class_="entry-title")
        if h1:
            title = self.clean_text(h1.get_text())
            # Remove suffix after em-dash/en-dash (often a tagline, not the dish name)
            title = re.split(r"\s*[–—]\s*", title)[0].strip()
            return title if title else None

        # Last resort: og:title without site suffix
        og_title = self.soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"]
            title = re.sub(r"\s*[-–|]\s*[^–|-]+$", "", title)
            return self.clean_text(title)

        return None

    def extract_description(self) -> Optional[str]:
        """
        Описание рецепта – первый <p> после вводного h2, либо meta description.
        """
        entry = self._get_entry_content()
        if entry:
            for h2 in entry.find_all("h2"):
                h2_text = h2.get_text(strip=True).lower()
                # Skip headings that are clearly not intro titles
                if any(
                    kw in h2_text
                    for kw in ["продукт", "съставки", "приготвяне", "начин",
                               "обобщение", "енергийни", "вариации", "въпроси",
                               "съвети"]
                ):
                    continue
                # Look for a <p> sibling right after this h2
                next_el = h2.find_next_sibling()
                while next_el:
                    if next_el.name == "p":
                        desc = self.clean_text(next_el.get_text())
                        if desc and len(desc) > 10:
                            return desc
                    # Stop search if we hit another structural element
                    if next_el.name in ("h2", "h3", "ul", "ol", "table", "hr"):
                        break
                    next_el = next_el.find_next_sibling()

        # Fallback: meta description
        meta_desc = self.soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            return self.clean_text(meta_desc["content"])

        og_desc = self.soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            return self.clean_text(og_desc["content"])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Ингредиенты из <ul> / <ol> после заголовка "Необходими продукти" / "Съставки".
        """
        entry = self._get_entry_content()
        if not entry:
            return None

        # Find the ingredients heading (h2 or h3)
        ingr_heading = None
        for heading in entry.find_all(["h2", "h3"]):
            text = heading.get_text(strip=True).lower()
            if any(kw in text for kw in ["продукт", "съставки", "необход"]):
                ingr_heading = heading
                break

        if not ingr_heading:
            logger.warning("Ingredients heading not found in %s", self.html_path)
            return None

        ingredients: List[Dict[str, Any]] = []

        # Collect all list items until the next h2
        next_el = ingr_heading.find_next_sibling()
        while next_el:
            if next_el.name == "h2":
                break
            if next_el.name in ("ul", "ol"):
                for li in next_el.find_all("li", recursive=False):
                    # Also handle <p> inside <li>
                    li_text = li.get_text(separator=" ", strip=True)
                    if li_text:
                        parsed = self._parse_ingredient_text(li_text)
                        if parsed and parsed.get("name"):
                            ingredients.append(parsed)
            next_el = next_el.find_next_sibling()

        if not ingredients:
            logger.warning("No ingredients parsed from %s", self.html_path)
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def extract_instructions(self) -> Optional[str]:
        """
        Инструкции из h3-шагов + <ol> под h2 "Начин на приготвяне".
        """
        entry = self._get_entry_content()
        if not entry:
            return None

        # Find the instructions heading
        instructions_heading = None
        for h2 in entry.find_all("h2"):
            text = h2.get_text(strip=True).lower()
            if "приготвяне" in text or "начин" in text or "стъпки" in text:
                instructions_heading = h2
                break

        if not instructions_heading:
            logger.warning("Instructions heading not found in %s", self.html_path)
            return None

        # Notes-section keywords — stop instructions before these headings
        _NOTES_KW = {"трик", "съвет", "💡", "🧠", "📝"}

        # Collect all direct siblings up to the next h2 or notes-h3
        siblings = []
        next_el = instructions_heading.find_next_sibling()
        while next_el:
            if next_el.name == "h2":
                break
            if next_el.name == "h3":
                h3_text = next_el.get_text(strip=True).lower()
                if any(kw in h3_text for kw in _NOTES_KW):
                    break  # reached notes section
            siblings.append(next_el)
            next_el = next_el.find_next_sibling()

        parts: List[str] = []
        skip_next_ol = False  # flag to avoid double-processing OLs paired with h3s

        for i, el in enumerate(siblings):
            if skip_next_ol:
                skip_next_ol = False
                continue

            if el.name == "h3":
                step_name = self.clean_text(el.get_text())
                # Look ahead for the immediately following OL
                if i + 1 < len(siblings) and siblings[i + 1].name == "ol":
                    ol_el = siblings[i + 1]
                    steps = [
                        self.clean_text(li.get_text())
                        for li in ol_el.find_all("li")
                    ]
                    steps = [s for s in steps if s]
                    if steps:
                        parts.append(f"{step_name}: {' '.join(steps)}")
                    skip_next_ol = True
                else:
                    # h3 with no OL – include just the heading text
                    if step_name:
                        parts.append(step_name)

            elif el.name == "ol":
                # Bare OL without an h3 header
                steps = [
                    self.clean_text(li.get_text())
                    for li in el.find_all("li")
                ]
                for step in steps:
                    if step:
                        parts.append(step)

        if not parts:
            logger.warning("No instructions parsed from %s", self.html_path)
            return None

        return " ".join(parts)

    def extract_category(self) -> Optional[str]:
        """Категория из строки «Тип ястие» в сводной таблице."""
        summary = self._get_summary_table()
        for key, value in summary.items():
            if "тип" in key.lower():
                return value

        # Fallback: breadcrumbs
        breadcrumb = self.soup.find("nav", class_=re.compile(r"breadcrumb", re.I))
        if breadcrumb:
            links = breadcrumb.find_all("a")
            if links:
                return self.clean_text(links[-1].get_text())

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки из сводной таблицы."""
        summary = self._get_summary_table()
        for key, value in summary.items():
            if "подготовка" in key.lower():
                return value
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Время готовки из сводной таблицы."""
        summary = self._get_summary_table()
        for key, value in summary.items():
            if "готвене" in key.lower():
                return value
        return None

    def extract_total_time(self) -> Optional[str]:
        """Общее время из сводной таблицы."""
        summary = self._get_summary_table()
        for key, value in summary.items():
            if "общо" in key.lower():
                return value
        return None

    def extract_notes(self) -> Optional[str]:
        """
        Заметки / советы из секций «Малък трик», «Съвети за перфектен резултат»
        (поддерживаются как h2, так и h3 заголовки).
        """
        entry = self._get_entry_content()
        if not entry:
            return None

        _NOTES_KW = {"трик", "съвет", "💡", "🧠", "📝"}

        notes_parts: List[str] = []

        for heading in entry.find_all(["h2", "h3"]):
            text = heading.get_text(strip=True).lower()
            if not any(kw in text for kw in _NOTES_KW):
                continue

            next_el = heading.find_next_sibling()
            while next_el:
                if next_el.name in ("h2", "h3", "h4", "h5", "h6", "div"):
                    break
                if next_el.name == "p":
                    note = self.clean_text(next_el.get_text())
                    if note:
                        notes_parts.append(note)
                elif next_el.name in ("ul", "ol"):
                    for li in next_el.find_all("li"):
                        note = self.clean_text(li.get_text())
                        if note:
                            notes_parts.append(note)
                next_el = next_el.find_next_sibling()

        return " ".join(notes_parts) if notes_parts else None

    def extract_tags(self) -> Optional[str]:
        """
        Теги из span.entry-meta-tags внутри основной (первой) статьи.

        BeautifulSoup плохо обрабатывает вложенные <article>, поэтому
        работаем напрямую со строкой HTML основной статьи.
        """
        main_article = self.soup.find("article")
        if not main_article:
            return None

        article_id = main_article.get("id", "")
        if not article_id:
            return None

        html_str = str(self.soup)

        # Find the start of the main article
        article_start = html_str.find(f'id="{article_id}"')
        if article_start < 0:
            return None

        # Find where the next <article starts (to delimit scope)
        next_article_pos = html_str.find("<article", article_start + len(article_id))
        main_article_html = (
            html_str[article_start:next_article_pos]
            if next_article_pos > 0
            else html_str[article_start:]
        )

        article_soup = BeautifulSoup(main_article_html, "lxml")
        tag_span = article_soup.find("span", class_="entry-meta-tags")
        if not tag_span:
            return None

        tags = [a.get_text(strip=True) for a in tag_span.find_all("a")]
        return ", ".join(tags) if tags else None

    def extract_image_urls(self) -> Optional[str]:
        """
        URL изображений:
          1. og:image
          2. img[src*=wp-content/uploads] в entry-content (исключая миниатюры)
        """
        urls: List[str] = []

        # Primary: OG image
        og_image = self.soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            urls.append(og_image["content"])

        # Secondary: full-size images inside the article entry-content
        entry = self._get_entry_content()
        if entry:
            for img in entry.find_all("img"):
                src = img.get("src") or img.get("data-src") or ""
                if "wp-content/uploads" not in src:
                    continue
                # Skip resized thumbnails (e.g. image-240x180.jpg)
                if re.search(r"-\d+x\d+\.\w+$", src):
                    continue
                if src not in urls:
                    urls.append(src)

        # Deduplicate (preserve order)
        seen: set = set()
        unique: List[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ",".join(unique) if unique else None

    # ----------------------------------------------------------------- main API

    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта из HTML-страницы."""
        try:
            dish_name = self.extract_dish_name()
            description = self.extract_description()
            ingredients = self.extract_ingredients()
            instructions = self.extract_instructions()
            category = self.extract_category()
            prep_time = self.extract_prep_time()
            cook_time = self.extract_cook_time()
            total_time = self.extract_total_time()
            notes = self.extract_notes()
            tags = self.extract_tags()
            image_urls = self.extract_image_urls()
        except Exception as exc:  # broad catch: prefer returning partial None data over crashing
            logger.error("Unexpected error extracting %s: %s", self.html_path, exc)
            return {
                "dish_name": None,
                "description": None,
                "ingredients": None,
                "instructions": None,
                "category": None,
                "prep_time": None,
                "cook_time": None,
                "total_time": None,
                "notes": None,
                "tags": None,
                "image_urls": None,
            }

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
    import os

    recipes_dir = os.path.join("preprocessed", "videorecepti_domashnakunyasdani_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(VideoReceptiDomashnakunyasdaniComExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python videorecepti_domashnakunyasdani_com.py")


if __name__ == "__main__":
    main()
