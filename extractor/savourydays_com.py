"""
Экстрактор данных рецептов для сайта savourydays.com
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

# Vietnamese time unit → English mapping
_VN_TIME_MAP = {
    'phút': 'minutes',
    'giây': 'seconds',
    'giờ': 'hours',
}

# Known Vietnamese and international measurement units.
# Order matters: longer / more specific phrases must come first so the
# regex alternation matches them before shorter substrings.
_UNITS = [
    'lòng đỏ', 'lòng trắng',
    'thìa cà phê', 'thìa café', 'thìa cafe', 'thìa canh', 'thìa to', 'thìa lớn',
    'thìa nhỏ', 'thìa',
    'muỗng canh', 'muỗng nhỏ', 'muỗng',
    'tablespoon', 'teaspoon', 'tbsp', 'tsp',
    'kilogram', 'gram',
    'milliliter', 'millilitre', 'ml',
    'liter', 'litre', 'lít',
    'ounce', 'pound',
    'cup', 'cốc',
    'quả', 'trái', 'củ', 'tép', 'lá', 'cây',
    'thanh', 'miếng', 'cái',
    'bó', 'gói', 'hộp', 'lon',
    'oz', 'lb', 'kg', 'g',
]

# Keyword patterns that mark the beginning of the ingredient section
_INGREDIENT_MARKERS = [
    'nguyên liệu',
    'nguyên liêu',          # common typo
    'ingredients',
    '* phần',
    '* công thức',
]

# Keyword patterns that mark the beginning of the instruction section.
# These are matched only when the text is SHORT (header-like), to avoid
# false positives inside longer numbered steps (e.g. "… mình chỉ viết các
# bước làm thôi").
_INSTRUCTION_MARKERS = [
    'cách làm',
    'hướng dẫn làm',
    'cách thực hiện',
    'bước thực hiện',
    'cách nấu',
    'cách chế biến',
]
_INSTRUCTION_MARKERS_MAX_LEN = 60  # ignore marker if paragraph is longer than this

# Keyword patterns that mark note / tips content
_NOTE_MARKERS = [
    'lưu ý', 'ghi chú', 'chú ý', 'mẹo', 'tips', 'note',
]


class SavouryDaysComExtractor(BaseRecipeExtractor):
    """Экстрактор для savourydays.com"""

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _recipe_content_div(self):
        """Return the main recipe content/instructions div."""
        return self.soup.find(itemprop='recipeInstructions')

    @staticmethod
    def _normalize_time_vn(time_text: str) -> Optional[str]:
        """Convert Vietnamese time text to English (e.g. '15 phút' → '15 minutes')."""
        if not time_text:
            return None
        text = time_text.strip()
        for vn, en in _VN_TIME_MAP.items():
            text = re.sub(rf'\b{vn}\b', en, text)
        # Normalise ranges: "25 - 35" → "25-35"
        text = re.sub(r'(\d)\s*[–-]\s*(\d)', r'\1-\2', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text if text else None

    @staticmethod
    def _parse_iso_duration(iso: str) -> Optional[str]:
        """Parse ISO 8601 duration (e.g. 'PT25M') to a minutes string."""
        if not iso or not iso.startswith('PT'):
            return None
        hours = 0
        minutes = 0
        h_m = re.search(r'(\d+)H', iso)
        m_m = re.search(r'(\d+)M', iso)
        if h_m:
            hours = int(h_m.group(1))
        if m_m:
            minutes = int(m_m.group(1))
        total = hours * 60 + minutes
        return f"{total} minutes" if total > 0 else None

    def _parse_ingredient(self, raw: str) -> Optional[dict]:
        """
        Parse a Vietnamese ingredient string into {name, amount, unit}.

        Handles patterns such as:
          "30gram bột ngô (corn starch)"
          "400 ml (1-2/3 cup) sữa tươi không đường"
          "3 quả trứng gà (50 gram/quả không tính vỏ)"
          "½ thìa café cream of tartar"
          "1 nhúm nhỏ muối"
          "Nước khoảng 30 – 40 ml (3 tbsp), đủ ngập đường"
        """
        if not raw:
            return None

        text = raw.replace('\xa0', ' ').strip()

        # Normalize Unicode fractions
        frac_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
        }
        for frac, repl in frac_map.items():
            text = text.replace(frac, repl)

        # Strip conversion parentheticals that contain only measurement terms
        # e.g. "(khoảng 1/3 cup)", "(2/3 - 1 cup)", "(50 gram/quả không tính vỏ)"
        text = re.sub(
            r'\(\s*(?:khoảng\s+)?[\d/.,\s–-]+\s*'
            r'(?:cup|ml|gram|g|kg|oz|lb|tbsp|tsp|thìa|muỗng|litre?|lít)[^)]*\)',
            '',
            text,
            flags=re.IGNORECASE,
        )
        # Strip "(5ml)" style inline notes after unit names in ingredient strings
        text = re.sub(r'\(\s*\d+\s*ml\s*\)', '', text, flags=re.IGNORECASE)

        # Strip trailing preparation notes separated by " – " or ", "
        # e.g. " – đong bằng muỗng/ thìa canh (tbsp)", ", nhiệt độ phòng",
        # "– ở nhiệt độ phòng"
        text = re.sub(r'\s*[–-]\s*đong\s+bằng.*$', '', text)
        text = re.sub(r',?\s*[–-]?\s*(?:ở\s+)?nhiệt\s+độ\s+phòng.*$', '', text, flags=re.IGNORECASE)
        text = re.sub(r',?\s*đun\s+chảy\b.*$', '', text, flags=re.IGNORECASE)

        # Strip size qualifiers like "(L)", "(M)"
        text = re.sub(r'\(\s*[LMXS]\s*\)', '', text)

        # Strip "/ alternative_unit_or_measure" patterns that appear right after
        # an existing unit keyword.  These are measurement alternatives in
        # parenthetical-free notation like "thìa cafe/ teaspoon" or "tsp/ 5 ml".
        # We strip the slash + the single alternative unit/measure only.
        # We do NOT strip slash-separated ingredient name alternatives like
        # "bột mỳ thường/ bột mỳ đa dụng".
        _alt_units = (
            r'tablespoon|teaspoon|tbsps?|tsps?'
            r'|milliliters?|millilitres?|ml'
            r'|liters?|litres?'
            r'|grams?|kilograms?|kg|g'
            r'|ounces?|pounds?|oz|lb'
            r'|cups?'
        )
        # "/teaspoon", "/ teaspoon", "/ 5 ml", "/ tsp" etc.
        # Apply twice so that chained "/ tsp/ 5 ml" is fully stripped.
        # Use (?<!\d) so we don't accidentally strip the "/" inside fractions
        # like "3/4 teaspoon" (would otherwise remove "/4 teaspoon").
        for _ in range(2):
            text = re.sub(
                rf'(?<!\d)\s*/\s*(?:\d+\s*)?(?:{_alt_units})\b',
                '',
                text,
                flags=re.IGNORECASE,
            )

        text = re.sub(r'\s+', ' ', text).strip()

        if not text:
            return None

        units_pat = '|'.join(re.escape(u) for u in _UNITS)

        # ------------------------------------------------------------------
        # Pattern A: "[amount][unit] name"  (no/one space between them)
        # Examples: "30gram bột ngô", "400 ml sữa tươi", "3 quả trứng gà"
        #           "100 - 130gram chocolate chips"
        # ------------------------------------------------------------------
        m = re.match(
            rf'^([\d/.,\s–-]+?)\s*({units_pat})\s+(.+)$',
            text,
            re.IGNORECASE | re.UNICODE,
        )
        if m:
            amount_raw = m.group(1).strip()
            unit = m.group(2).strip()
            name = m.group(3).strip()
            # Normalise range separators in amount
            amount = re.sub(r'\s*[–-]\s*', '-', amount_raw).strip('-').strip()
            # Remove leading/trailing whitespace from name
            name = name.strip()
            return {'name': name, 'amount': amount if amount else None, 'unit': unit}

        # ------------------------------------------------------------------
        # Pattern B: "name khoảng [amount] [unit]" or "name [amount] [unit]"
        # Example: "Nước khoảng 30 – 40 ml (3 tbsp), đủ ngập đường"
        # The name here is a single Vietnamese word (the ingredient name).
        # ------------------------------------------------------------------
        m = re.match(
            rf'^([^\d\s/][^\d/]*?)\s+(?:khoảng\s+)?([\d\s/.,–-]+?)\s*({units_pat})\b.*$',
            text,
            re.IGNORECASE | re.UNICODE,
        )
        if m:
            name_raw = m.group(1).strip()
            # Only use this pattern if name_raw looks like a short ingredient name
            # (not a full sentence / long phrase)
            if len(name_raw.split()) <= 4 and not re.search(r'\d', name_raw):
                amount = re.sub(r'\s*[–-]\s*', '-', m.group(2).strip()).strip('-').strip()
                unit = m.group(3).strip()
                return {'name': name_raw, 'amount': amount if amount else None, 'unit': unit}

        # ------------------------------------------------------------------
        # Special pattern: "1 nhúm nhỏ muối" – non-standard amount description.
        # "[amount_phrase] name" where the second word of the amount phrase is
        # a known Vietnamese non-standard quantity descriptor.
        # ------------------------------------------------------------------
        _non_std_qty = {
            'nhúm', 'nhánh', 'ít', 'nhiều', 'vừa', 'chút',
            'miếng', 'muỗng', 'giọt', 'phần',
        }
        m = re.match(
            r'^(\d+\s+(\S+)(?:\s+\S+)?)\s+(.+)$',
            text,
            re.IGNORECASE | re.UNICODE,
        )
        if m:
            amount_phrase = m.group(1).strip()
            second_word = m.group(2).strip().lower()
            name = m.group(3).strip()
            # Only use this pattern if the second word is a known non-standard
            # quantity descriptor (e.g. "nhúm", "nhánh").  This prevents
            # "3 trứng gà" from being split as amount_phrase="3 trứng" name="gà".
            if second_word in _non_std_qty:
                return {'name': name, 'amount': amount_phrase, 'unit': None}

        # Fallback: return whole text as name, no amount/unit
        return {'name': text, 'amount': None, 'unit': None}

    # ------------------------------------------------------------------ #
    # Public extraction methods
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Extract recipe title from h1."""
        h1 = self.soup.find('h1', class_='title')
        if h1:
            name = self.clean_text(h1.get_text())
            return self._clean_dish_name(name)
        h1 = self.soup.find('h1', itemprop='name')
        if h1:
            name = self.clean_text(h1.get_text())
            return self._clean_dish_name(name)
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            name = self.clean_text(og_title['content'])
            return self._clean_dish_name(name)
        return None

    @staticmethod
    def _clean_dish_name(name: str) -> Optional[str]:
        """Strip common Vietnamese blog-post prefixes from recipe titles."""
        if not name:
            return None
        # "Cách làm ..." → strip "Cách làm " prefix
        name = re.sub(r'^Cách\s+làm\s+', '', name, flags=re.IGNORECASE)
        # Capitalize first letter
        name = name[:1].upper() + name[1:] if name else name
        # Normalize em-dashes to regular hyphens with spaces
        name = re.sub(r'\s*–\s*', ' - ', name)
        # Strip surrounding quotation marks from words
        # e.g. "bất bại" (U+201C/U+201D) → bất bại
        name = re.sub(r'[\u201c\u201d\u0022]([^\u201c\u201d\u0022]+)[\u201c\u201d\u0022]', r'\1', name)
        return name.strip() if name.strip() else None

    def extract_description(self) -> Optional[str]:
        """Extract description from meta description tag."""
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Extract ingredients from the recipe content div.

        The site embeds both ingredient lists and instruction steps inside
        div[itemprop="recipeInstructions"].  Ingredient ULs appear between
        a paragraph that contains an ingredient-section marker ("Nguyên liệu"
        etc.) and a paragraph that starts the instruction section ("Cách làm"
        etc.).
        """
        content_div = self._recipe_content_div()
        if not content_div:
            return None

        ingredients: list = []
        in_ingredient_section = False

        for tag in content_div.children:
            if not hasattr(tag, 'name'):
                continue

            if tag.name in ('p', 'h2', 'h3', 'h4'):
                text = tag.get_text().strip()
                text_lower = text.lower()

                # Start of ingredient section.
                # Use startswith to avoid false positives inside prose paragraphs
                # (e.g. "Tỉ lệ nguyên liệu này cho…").
                if any(text_lower.startswith(m) for m in _INGREDIENT_MARKERS):
                    in_ingredient_section = True
                    continue

                # Start of instruction section → stop collecting ingredients.
                # Use startswith here as well: even a longer "Cách làm kiểu VN…"
                # paragraph signals the end of the ingredient block.
                if any(text_lower.startswith(m) for m in _INSTRUCTION_MARKERS):
                    in_ingredient_section = False

            elif tag.name == 'ul' and in_ingredient_section:
                for li in tag.find_all('li'):
                    # Use empty separator to avoid spurious spaces when tags
                    # split mid-word (e.g. k<em>hông</em> → "không", not "k hông").
                    raw = li.get_text(separator='', strip=True)
                    raw = self.clean_text(raw)
                    if not raw:
                        continue
                    parsed = self._parse_ingredient(raw)
                    if parsed and parsed.get('name'):
                        ingredients.append(parsed)

        if not ingredients:
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def extract_instructions(self) -> Optional[str]:
        """
        Extract cooking instructions (numbered steps) from the recipe content.

        Collects paragraphs that start with a digit followed by '.' after the
        first occurrence of an instruction-section marker ("Cách làm" etc.).
        Only the first instruction block is collected to avoid duplicating
        alternate recipe variants.
        """
        content_div = self._recipe_content_div()
        if not content_div:
            return None

        steps: list = []
        in_instructions = False

        for tag in content_div.children:
            if not hasattr(tag, 'name'):
                continue

            if tag.name in ('p', 'h2', 'h3', 'h4'):
                text = tag.get_text().strip()
                text_lower = text.lower()

                # Detect the start of the instruction section.
                # Only treat as a header if the paragraph is short (not a
                # long numbered step that happens to mention "cách làm").
                if (
                    len(text) <= _INSTRUCTION_MARKERS_MAX_LEN
                    and any(m in text_lower for m in _INSTRUCTION_MARKERS)
                ):
                    if not in_instructions:
                        in_instructions = True
                    continue

                if in_instructions:
                    # Numbered step: "1. ...", "2. ..." etc.
                    if re.match(r'^\d+\.', text):
                        steps.append(self.clean_text(text))

            elif tag.name in ('ol',) and in_instructions:
                # Ordered lists within instruction section
                for li in tag.find_all('li'):
                    step_text = self.clean_text(li.get_text().strip())
                    if step_text:
                        steps.append(step_text)

        if not steps:
            return None

        return '\n'.join(steps)

    def extract_prep_time(self) -> Optional[str]:
        """Extract preparation time."""
        # Prefer the human-readable text in li.preptime > time.value-title
        preptime_li = self.soup.find('li', class_='preptime')
        if preptime_li:
            time_el = preptime_li.find('time', class_='value-title')
            if time_el:
                text = time_el.get_text().strip()
                if text:
                    return self._normalize_time_vn(text)
        # Fallback: ISO 8601 duration in itemprop="prepTime" meta
        meta = self.soup.find('meta', attrs={'itemprop': 'prepTime'})
        if meta and meta.get('content'):
            return self._parse_iso_duration(meta['content'])
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Extract cooking / baking time."""
        cooktime_li = self.soup.find('li', class_='cooktime')
        if cooktime_li:
            time_el = cooktime_li.find('time', class_='value-title')
            if time_el:
                text = time_el.get_text().strip()
                if text:
                    return self._normalize_time_vn(text)
        meta = self.soup.find('meta', attrs={'itemprop': 'cookTime'})
        if meta and meta.get('content'):
            return self._parse_iso_duration(meta['content'])
        return None

    def extract_total_time(self) -> Optional[str]:
        """Extract total time."""
        totaltime_li = self.soup.find('li', class_='totaltime')
        if totaltime_li:
            time_el = totaltime_li.find('time', class_='value-title')
            if time_el:
                text = time_el.get_text().strip()
                if text:
                    return self._normalize_time_vn(text)
        meta = self.soup.find('meta', attrs={'itemprop': 'totalTime'})
        if meta and meta.get('content'):
            return self._parse_iso_duration(meta['content'])
        return None

    def extract_notes(self) -> Optional[str]:
        """
        Extract notes and tips from the recipe content.

        Collects:
        - Paragraphs that start with "(*) Ghi chú" and the OL that follows them.
        - Paragraphs that start with "* Lưu ý" or "Lưu ý:" near the ingredient
          section (preparation tips, substitutions etc.).
        """
        content_div = self._recipe_content_div()
        if not content_div:
            return None

        notes: list = []
        collect_next_ol = False
        in_ingredients = False

        for tag in content_div.children:
            if not hasattr(tag, 'name'):
                continue

            if tag.name in ('p', 'h3'):
                text = tag.get_text().strip()
                text_lower = text.lower()

                # Track ingredient section so we can limit "Lưu ý" collection
                if any(m in text_lower for m in _INGREDIENT_MARKERS):
                    in_ingredients = True

                if any(m in text_lower for m in _INSTRUCTION_MARKERS):
                    in_ingredients = False
                    collect_next_ol = False

                # "(*) Ghi chú:" / "Ghi chú:" → collect note OL
                if 'ghi chú' in text_lower:
                    collect_next_ol = True
                    continue

                # "* Lưu ý:" lines near ingredient section
                if (
                    in_ingredients
                    and any(m in text_lower for m in _NOTE_MARKERS)
                    and text.startswith('*')
                ):
                    # Strip the leading "* Lưu ý:" label
                    note_text = re.sub(r'^\*\s*(?:Lưu ý|Ghi chú)\s*:?\s*', '', text, flags=re.I)
                    note_text = self.clean_text(note_text)
                    if note_text:
                        notes.append(note_text)

            elif tag.name == 'ol' and collect_next_ol:
                for li in tag.find_all('li'):
                    item_text = self.clean_text(li.get_text().strip())
                    if item_text:
                        notes.append(item_text)
                collect_next_ol = False

        if not notes:
            return None

        return ' '.join(notes)

    def extract_category(self) -> Optional[str]:
        """
        Extract recipe category.

        savourydays.com does not embed a per-recipe category in the page HTML
        in a machine-readable way, so this always returns None.
        """
        return None

    def extract_tags(self) -> Optional[str]:
        """
        Extract recipe tags.

        savourydays.com uses a site-wide tag cloud widget rather than per-recipe
        tags in the page HTML, so this always returns None.
        """
        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Extract recipe image URLs.

        Sources (in order of preference):
        1. og:image meta tag
        2. itemprop="image" meta tag (thumbnail)
        3. Main recipe hero image (div.single-img-box img)
        4. Content images from the recipe body (savourydays.com / staticflickr.com)
        """
        urls: list = []

        def _add(url: str) -> None:
            if url and url not in urls:
                urls.append(url)

        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            _add(og_image['content'])

        img_meta = self.soup.find('meta', attrs={'itemprop': 'image'})
        if img_meta and img_meta.get('content'):
            _add(img_meta['content'])

        single_img_div = self.soup.find('div', class_='single-img-box')
        if single_img_div:
            img = single_img_div.find('img')
            if img and img.get('src'):
                _add(img['src'])

        content_div = self._recipe_content_div()
        if content_div:
            for img in content_div.find_all('img'):
                src = img.get('src', '')
                if not src:
                    continue
                # Exclude WordPress admin/UI images
                if 'wp-includes' in src or 'smilies' in src:
                    continue
                if any(
                    domain in src
                    for domain in ('savourydays.com', 'staticflickr.com', 'flickr.com')
                ):
                    _add(src)

        return ','.join(urls) if urls else None

    # ------------------------------------------------------------------ #
    # Main extraction entry point
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """Extract all recipe data and return as a dict."""
        result: dict = {
            'dish_name': None,
            'description': None,
            'ingredients': None,
            'instructions': None,
            'category': None,
            'prep_time': None,
            'cook_time': None,
            'total_time': None,
            'notes': None,
            'tags': None,
            'image_urls': None,
        }

        fields = {
            'dish_name': self.extract_dish_name,
            'description': self.extract_description,
            'ingredients': self.extract_ingredients,
            'instructions': self.extract_instructions,
            'category': self.extract_category,
            'prep_time': self.extract_prep_time,
            'cook_time': self.extract_cook_time,
            'total_time': self.extract_total_time,
            'notes': self.extract_notes,
            'tags': self.extract_tags,
            'image_urls': self.extract_image_urls,
        }

        for field, method in fields.items():
            try:
                result[field] = method()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error extracting %s: %s", field, exc)

        return result


def main() -> None:
    """Process all HTML files in preprocessed/savourydays_com."""
    import os

    preprocessed_dir = os.path.join('preprocessed', 'savourydays_com')

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(SavouryDaysComExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python savourydays_com.py")


if __name__ == '__main__':
    main()
