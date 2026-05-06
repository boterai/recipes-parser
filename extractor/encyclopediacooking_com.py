"""
Экстрактор данных рецептов для сайта encyclopediacooking.com
Поддерживает три варианта вёрстки:
  1. font-layout — контент разбит на <font>-теги в <center>
  2. b-layout    — весь контент в одном <b>-теге в <center>
  3. p-layout    — контент в <p>-тегах с маркерами «•» и «(N)»
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Arabic unit vocabulary (sorted longest first for greedy matching)
# ---------------------------------------------------------------------------
_ARABIC_UNITS: List[str] = sorted([
    'ملعقة كبيرة', 'ملاعق كبيرة', 'ملعقة طعام', 'ملاعق طعام',
    'ملعقة صغيرة', 'ملاعق صغيرة', 'ملعقة شاي', 'ملاعق شاي',
    'كيلوجرام', 'كيلوغرام', 'ملليتر', 'ملاعق', 'ملعقه',
    'ملعقة', 'غرام', 'جرام', 'كيلو', 'أكواب', 'اكواب',
    'حبات', 'قطع', 'فصوص', 'وحده', 'وحدة', 'لتر', 'ليتر',
    'باكيت', 'كوب', 'حبة', 'قطعة', 'فص', 'م ك', 'م ص', 'مل',
    'ماي', 'م',
], key=len, reverse=True)

_UNITS_RE = '|'.join(re.escape(u) for u in _ARABIC_UNITS)

# Arabic numeric words mapped to decimal strings
_ARABIC_NUM_WORDS = {
    'نصف': '0.5', 'نص': '0.5',
    'ربع': '0.25',
    'ثلث': '0.33',
    'ثلاثة أرباع': '0.75',
}

# Arabic time words
_HOUR_WORDS = r'ساعات?|ساعتين|ساع[ةه]'
_MIN_WORDS = r'دقائق|دقيقة|دقيقه|دقايق|دقيقتين'

# Section-header keywords (Arabic) — used to detect ingredient/instruction blocks
_INGREDIENTS_MARKERS = re.compile(
    r'المقادير|مقادير|مكونات|المكونات|الوصفة|لعمل\s', re.IGNORECASE
)
_INSTRUCTIONS_MARKERS = re.compile(
    r'الطريق[ةه]|طريق[ةه]\s+العمل|طريق[ةه]\s+التحضير|طريق[ةه]\s+الإعداد|'
    r'خطوات|الخطوات|التحضير|الإعداد',
    re.IGNORECASE,
)
_NOTES_MARKERS = re.compile(
    r'ملاحظ[ةه]|ملاحظات|فوائد|نصائح|تلميح|تلميحات|اختياري',
    re.IGNORECASE,
)

# Arabic cooking verbs that introduce ingredient objects in narrative text
_COOKING_VERB_RE = re.compile(
    r'(?:^|(?<=[\s،,]))'
    r'(?:نسلق|نضيف|أضيفي|اضيف|ونضيف|يضاف|نحضر|نقطع|'
    r'نتبلها?|ونتبلها?|نحمس|أحمس|اسلق|أسلق|احمس|نخلط|'
    r'نرش|ونرش|احط|نصب|نقدم|وتقدم|نقدمه?\s+مع)'
    r'(?:\s+(?:له\b|لها?\b))?'
    r'\s+',
    re.IGNORECASE,
)

# Patterns that end an ingredient object extracted from a narrative line
_OBJ_CUT_RE = re.compile(
    r'\s+(?:واترك[ه]?|ويترك|ويقلى|ويقلب|ويقدم|حتى\s|على\s+النار|'
    r'تقريبا|ثم\s|ونقلب|وبعد\s|ولما\s|انا(?:\s|$)|تالي\s|واصفيه|ولحين)',
    re.IGNORECASE,
)


class EncyclopediacookingComExtractor(BaseRecipeExtractor):
    """Экстрактор для encyclopediacooking.com"""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_content_area(self):
        """Return tuple of (main content element, layout type string).

        Layout types:
          'font'    — <center> with direct <font> children
          'b'       — <center> with a direct <b> child
          'p'       — no <center>, but a <p> inside data div
          'center'  — <center> without recognised child structure
          'unknown' — no data div found
        """
        data_div = self.soup.find('div', class_='data')
        if not data_div:
            return None, 'unknown'

        center = data_div.find('center')
        if center:
            # Distinguish layout by DIRECT children only (avoid deep search confusion)
            direct_fonts = [c for c in center.children
                            if hasattr(c, 'name') and c.name == 'font']
            direct_b = [c for c in center.children
                        if hasattr(c, 'name') and c.name == 'b']

            if direct_fonts:
                return center, 'font'
            if direct_b:
                return direct_b[0], 'b'
            return center, 'center'

        # p-layout: no center, but <p> with bullet content
        p_tag = data_div.find('p')
        if p_tag and p_tag.get_text().strip():
            return p_tag, 'p'

        return data_div, 'unknown'

    @staticmethod
    def _split_lines(text: str) -> List[str]:
        """Split text into non-empty trimmed lines."""
        return [line.strip() for line in text.splitlines() if line.strip()]

    def _clean_ingredient_line(self, line: str) -> str:
        """Remove leading bullets, dashes, special chars from an ingredient line."""
        line = re.sub(r'^[\-–•*\uf020\uf0b7\uf020]+\s*', '', line).strip()
        # Remove trailing period
        line = re.sub(r'\s*\.\s*$', '', line).strip()
        return line

    def _parse_ingredient(self, raw_line: str) -> Optional[dict]:
        """
        Parse a single ingredient line into {name, amount, unit}.
        Returns None for section headers or empty lines.
        """
        line = self._clean_ingredient_line(self.clean_text(raw_line))
        if not line:
            return None

        # Skip obvious section headers (no digits, ends with ':')
        if line.endswith(':'):
            return None
        # Single Arabic word with the definite article 'ال' + plural suffix '-ات'
        # is likely a section header: "البهارات", "الخضروات", "المكسرات"
        # BUT do NOT filter bare words like "بهارات" (spices) or "خضروات" (vegetables)
        # which are valid ingredients.
        words = line.split()
        if len(words) == 1 and not any(ch.isdigit() for ch in line) \
                and re.match(r'^ال[\u0600-\u06FF]+ات$', line) \
                and line not in _ARABIC_UNITS:
            return None

        # Skip narrative lines that are clearly not ingredients
        if re.match(r'^(?:وتقدروا|يمكن\s+إضافة|يمكن\s+اضافة|كما\s+يمكن|أو\s+يمكن)', line):
            return None

        # Clean up trailing noise like "<<<..." or ">>>" or bracketed suffixes
        line = re.sub(r'<<<.*$', '', line).strip()
        line = re.sub(r'>>>.*$', '', line).strip()

        # 1) Pattern: [amount] [unit] [name]
        #    e.g. "4 م ك بودرة فلفل حار"
        m = re.match(
            rf'^([\d\./]+(?:\s*[-–]\s*[\d\./]+)?)\s+({_UNITS_RE})\s+(.*)',
            line,
        )
        if m:
            return {'name': m.group(3).strip(), 'amount': m.group(1).strip(), 'unit': m.group(2).strip()}

        # 2) Pattern: [amount] [name]  (no explicit unit)
        #    e.g. "2 ملفوف أو خس"
        m = re.match(r'^([\d\./]+(?:\s*[-–]\s*[\d\./]+)?)\s+(.*)', line)
        if m:
            return {'name': m.group(2).strip(), 'amount': m.group(1).strip(), 'unit': None}

        # 3) Arabic numeric word at start: "نصف بصله", "ربع كوب"
        for word, val in _ARABIC_NUM_WORDS.items():
            if line.startswith(word):
                rest = line[len(word):].strip()
                # Check if next word is a unit
                mu = re.match(rf'^({_UNITS_RE})\s+(.*)', rest)
                if mu:
                    return {'name': mu.group(2).strip(), 'amount': val, 'unit': mu.group(1).strip()}
                if rest:
                    return {'name': rest, 'amount': val, 'unit': None}

        # 4) Amount+unit at END of line: "ملح لايقل عن 100 غرام"
        m = re.search(
            rf'(?:(?:لايقل\s+عن|حوالي|تقريبا)\s+)?([\d\./]+)\s*({_UNITS_RE})\s*$',
            line,
        )
        if m:
            name = line[: m.start()].strip()
            name = re.sub(r'\s+(?:لايقل\s+عن|حوالي|تقريبا)\s*$', '', name).strip()
            return {'name': name, 'amount': m.group(1).strip(), 'unit': m.group(2).strip()}

        # 5) Fallback: whole line = name
        return {'name': line, 'amount': None, 'unit': None}

    # ------------------------------------------------------------------
    # Extraction methods
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Extract dish name."""
        # Primary: dedicated title div
        title_div = self.soup.find('div', class_=re.compile(r'\badd\b'))
        if title_div:
            # The div with class "col-md-5 ... add" contains the dish name
            parent = self.soup.find('div', class_=lambda c: c and 'add' in c and 'col-md-5' in c)
            if parent:
                text = self.clean_text(parent.get_text())
                if text:
                    return self._strip_name_prefixes(text)

        # Fallback: first text node inside center (the recipe header)
        data_div = self.soup.find('div', class_='data')
        if data_div:
            center = data_div.find('center')
            if center:
                from bs4 import NavigableString
                for child in center.children:
                    if isinstance(child, NavigableString):
                        txt = self.clean_text(str(child))
                        if txt and len(txt) > 3:
                            return self._strip_name_prefixes(txt)

        # Fallback: page <title>
        title_tag = self.soup.find('title')
        if title_tag:
            title = self.clean_text(title_tag.get_text())
            return self._strip_name_prefixes(title)

        return None

    @staticmethod
    def _strip_name_prefixes(text: str) -> str:
        """Strip common Arabic prefixes from a dish name."""
        prefixes = [
            r'^طريق[ةه]\s+عمل\s+واعداد\s+وتحضير\s+',
            r'^طريق[ةه]\s+عمل\s+وتحضير\s+',
            r'^طريق[ةه]\s+عمل\s+',
            r'^طريق[ةه]\s+تحضير\s+',
            r'^طريق[ةه]\s+إعداد\s+',
            r'^طريق[ةه]\s+',
            r'^طريقه\s+عمل\s+',
            r'^وصف[ةه]\s+',
            r'^كيفي[ةه]\s+عمل\s+',
            r'^عمل\s+',
        ]
        for p in prefixes:
            text = re.sub(p, '', text, flags=re.IGNORECASE).strip()
        return text

    def extract_description(self) -> Optional[str]:
        """Extract recipe description (intro text before ingredients)."""
        content, layout = self._get_content_area()
        if content is None:
            return None

        try:
            if layout == 'font':
                return self._description_font(content)
            elif layout in ('b', 'center'):
                return self._description_b(content)
            elif layout == 'p':
                return self._description_p(content)
        except Exception as e:
            logger.warning('extract_description error: %s', e)
        return None

    def _description_font(self, center) -> Optional[str]:
        """For font layout: text nodes before the ingredients section."""
        from bs4 import NavigableString
        paragraphs = []
        for child in center.children:
            if isinstance(child, NavigableString):
                txt = self.clean_text(str(child))
                if not txt:
                    continue
                # Stop when we reach the recipe title repeated or ingredients marker
                if _INGREDIENTS_MARKERS.search(txt):
                    break
                # Skip the title (usually the first text node)
                if len(paragraphs) == 0 and len(txt) < 120:
                    continue
                paragraphs.append(txt)
            elif hasattr(child, 'name') and child.name == 'font':
                font_txt = self.clean_text(child.get_text())
                if _INGREDIENTS_MARKERS.search(font_txt):
                    break
        if paragraphs:
            return ' '.join(paragraphs[:3])  # first ~3 desc paragraphs
        return None

    def _description_b(self, b_tag) -> Optional[str]:
        """For b-tag layout: use the 'لعمل X' line as description."""
        text = b_tag.get_text()
        lines = self._split_lines(text)
        if not lines:
            return None
        # The pattern is: title → 'لعمل X :' → steps
        # Use the 'لعمل X' line (stripped of the prefix) as description
        for line in lines:
            line = self.clean_text(line)
            if not line:
                continue
            m = re.search(r'لعمل\s+(.+?)(?:\s*:)?$', line)
            if m:
                desc = m.group(1).strip().rstrip(':').strip()
                if desc and len(desc) > 5:
                    return desc
        # Fallback: first non-title line
        skip_title = True
        for line in lines:
            line = self.clean_text(line)
            if not line:
                continue
            if skip_title:
                skip_title = False
                continue
            if _INGREDIENTS_MARKERS.search(line) or _INSTRUCTIONS_MARKERS.search(line):
                break
            if len(line) > 10:
                return line
        return None

    def _description_p(self, p_tag) -> Optional[str]:
        """For p-layout: text before the ingredients marker."""
        text = p_tag.get_text()
        lines = self._split_lines(text)
        desc_parts = []
        for line in lines:
            line = self._clean_ingredient_line(self.clean_text(line))
            if not line:
                continue
            if _INGREDIENTS_MARKERS.search(line):
                break
            if len(line) > 10:
                desc_parts.append(line)
        if desc_parts:
            return ' '.join(desc_parts[:2])
        return None

    def extract_ingredients(self) -> Optional[str]:
        """Extract ingredients as JSON string."""
        content, layout = self._get_content_area()
        if content is None:
            return None

        try:
            if layout == 'font':
                raw_lines = self._ingredients_font(content)
            elif layout in ('b', 'center'):
                raw_lines = self._ingredients_b(content)
            elif layout == 'p':
                raw_lines = self._ingredients_p(content)
            else:
                return None

            ingredients = []
            for line in raw_lines:
                # Handle parenthesized lists: "(item1, item2, item3)"
                paren_m = re.match(r'^\(([^)]+)\)\s*$', line.strip())
                if paren_m:
                    items = [i.strip() for i in paren_m.group(1).split(',') if i.strip()]
                    for item in items:
                        parsed = self._parse_ingredient(item)
                        if parsed and parsed.get('name'):
                            ingredients.append(parsed)
                    continue

                parsed = self._parse_ingredient(line)
                if parsed and parsed.get('name'):
                    ingredients.append(parsed)

            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
        except Exception as e:
            logger.warning('extract_ingredients error: %s', e)
        return None

    def _ingredients_font(self, center) -> List[str]:
        """Font layout: text in font tag right after the 'المقادير' font."""
        fonts = center.find_all('font')
        lines: List[str] = []
        capture = False
        for font in fonts:
            txt = self.clean_text(font.get_text())
            if not txt:
                continue
            if _INGREDIENTS_MARKERS.search(txt) and len(txt) < 30:
                capture = True
                continue
            if capture:
                if _INSTRUCTIONS_MARKERS.search(txt) and len(txt) < 30:
                    break
                lines.extend(self._split_lines(font.get_text()))
                break  # usually only one font block for ingredients
        return lines

    def _ingredients_b(self, b_tag) -> List[str]:
        """
        B-tag layout: lines between 'لعمل' and 'الطريقة' marker.
        Falls back to extracting ingredients from the instruction narrative
        when no explicit ingredient list is found.
        """
        text = b_tag.get_text()
        lines = self._split_lines(text)
        result: List[str] = []
        in_section = False
        for line in lines:
            line = self.clean_text(line)
            if not line:
                continue
            # A line with 'لعمل' triggers ingredient section start
            m = re.search(r'لعمل\s', line)
            if m:
                # If line ends with ':' there is no separate ingredient list
                if line.rstrip().endswith(':') or line.rstrip().endswith('،'):
                    break
                in_section = True
                continue
            if in_section:
                if _INSTRUCTIONS_MARKERS.search(line) and len(line) < 40:
                    break
                # Lines that look like ingredient entries (short, no verb prefix)
                if len(line) <= 80 and not re.match(
                    r'^(?:نسلق|نضيف|يضاف|يترك|نترك|نحضر|نقدم|اضيف|اسلق|ادهن|احمص|احمس|ونضيف)',
                    line,
                ):
                    result.append(line)

        # Whenever no explicit ingredient list was found, fall back to narrative
        if not result:
            return self._extract_ingredients_from_b_narrative(b_tag)
        return result

    def _extract_ingredients_from_b_narrative(self, b_tag) -> List[str]:
        """
        For b-layout pages where ingredients are embedded in instruction steps:
        scan every line for Arabic cooking verbs and extract the objects that follow.
        """
        text = b_tag.get_text()
        lines = self._split_lines(text)
        candidates: List[str] = []

        for line in lines:
            line = self.clean_text(line)
            if not line or len(line) < 3:
                continue
            # Skip notes / section headers
            if _NOTES_MARKERS.search(line) and len(line) < 25:
                continue

            # Find ALL cooking verb occurrences in this line
            verb_matches = list(_COOKING_VERB_RE.finditer(line))
            if not verb_matches:
                continue

            for i, vm in enumerate(verb_matches):
                obj_start = vm.end()
                # Object ends at next verb occurrence or end of line
                obj_end = verb_matches[i + 1].start() if i + 1 < len(verb_matches) else len(line)
                obj_str = line[obj_start:obj_end].strip()

                # Cut at stop markers (cooking modifiers that follow the ingredients)
                stop_m = _OBJ_CUT_RE.search(obj_str)
                if stop_m:
                    obj_str = obj_str[:stop_m.start()].strip()

                if obj_str:
                    candidates.extend(self._split_ingredient_list(obj_str))

        # Deduplicate while preserving order; skip very short tokens
        seen: set = set()
        result: List[str] = []
        for item in candidates:
            item = item.strip()
            if not item or len(item) < 2:
                continue
            key = re.sub(r'\s+', ' ', item.lower())
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    @staticmethod
    def _split_ingredient_list(text: str) -> List[str]:
        """
        Split a raw Arabic ingredient string on commas and the conjunction و.
        Splits on و only when all resulting sub-parts are ≤ 50 chars, to avoid
        splitting compound word phrases like 'وحده' (alone/one).
        """
        if not text or len(text) < 2:
            return []
        # Split on Arabic comma / Western comma first
        comma_parts = re.split(r'[،,]\s*', text)
        result: List[str] = []
        for part in comma_parts:
            part = part.strip()
            if not part:
                continue
            # Try splitting on ' و ' (with spaces on both sides)
            # Split on Arabic conjunction و: it's written without a following space
            # (e.g. "ملح وفلفل" → و is attached to فلفل). Use lookahead for non-space.
            sub_parts = re.split(r'\s+و(?=\S)', part)
            if len(sub_parts) > 1 and all(len(sp.strip()) <= 50 for sp in sub_parts):
                result.extend(sp.strip() for sp in sub_parts if sp.strip())
            else:
                result.append(part)
        return [r for r in result if r and len(r) > 2]


    def _ingredients_p(self, p_tag) -> List[str]:
        """P-layout: lines prefixed with bullet char (•, ُ, ف020, etc.)."""
        text = p_tag.get_text()
        lines = self._split_lines(text)
        result: List[str] = []
        in_ingredients = False
        for line in lines:
            line = self.clean_text(line)
            if not line:
                continue
            if _INGREDIENTS_MARKERS.search(line):
                in_ingredients = True
                continue
            if in_ingredients:
                if _INSTRUCTIONS_MARKERS.search(line):
                    break
                # Keep bullet lines
                if re.match(r'^[\uf020\uf0b7•\-–*]', line) or line[0].isdigit():
                    clean = re.sub(r'^[\uf020\uf0b7•\-–*\s]+', '', line).strip()
                    if clean:
                        result.append(clean)
        return result

    def extract_instructions(self) -> Optional[str]:
        """Extract cooking instructions as a numbered string."""
        content, layout = self._get_content_area()
        if content is None:
            return None

        try:
            if layout == 'font':
                steps = self._instructions_font(content)
            elif layout in ('b', 'center'):
                steps = self._instructions_b(content)
            elif layout == 'p':
                steps = self._instructions_p(content)
            else:
                return None

            if not steps:
                return None
            # Ensure numbered
            if steps and not re.match(r'^\d+[\.\)]', steps[0]):
                steps = [f'{i}. {s}' for i, s in enumerate(steps, 1)]
            return '\n'.join(steps)
        except Exception as e:
            logger.warning('extract_instructions error: %s', e)
        return None

    def _instructions_font(self, center) -> List[str]:
        """Font layout: text in font tag right after the 'الطريقة' font."""
        fonts = center.find_all('font')
        steps: List[str] = []
        capture = False
        for font in fonts:
            txt = self.clean_text(font.get_text())
            if not txt:
                continue
            if _INSTRUCTIONS_MARKERS.search(txt) and len(txt) < 30:
                capture = True
                continue
            if capture:
                if _NOTES_MARKERS.search(txt) and len(txt) < 30:
                    break
                raw_lines = self._split_lines(font.get_text())
                for line in raw_lines:
                    line = re.sub(r'^[-–\s]+', '', self.clean_text(line)).strip()
                    if line:
                        steps.append(line)
                break
        return steps

    def _instructions_b(self, b_tag) -> List[str]:
        """B-tag layout: all non-empty lines after instructions marker or after ingredient block."""
        text = b_tag.get_text()
        lines = self._split_lines(text)
        steps: List[str] = []
        in_instructions = False
        for line in lines:
            line = self.clean_text(line)
            if not line:
                continue
            if _INSTRUCTIONS_MARKERS.search(line) and len(line) < 40:
                in_instructions = True
                continue
            if in_instructions:
                if _NOTES_MARKERS.search(line) and len(line) < 30:
                    break
                steps.append(line)
        # If no explicit instruction marker, take all lines after 'لعمل' line
        if not steps:
            capture = False
            for line in lines:
                line = self.clean_text(line)
                if not line:
                    continue
                if re.search(r'لعمل\s', line):
                    capture = True
                    continue
                if capture:
                    if _NOTES_MARKERS.search(line) and len(line) < 30:
                        break
                    steps.append(line)
        return steps

    def _instructions_p(self, p_tag) -> List[str]:
        """P-layout: lines prefixed with (N) or numbered step markers."""
        text = p_tag.get_text()
        lines = self._split_lines(text)
        steps: List[str] = []
        in_instructions = False
        for line in lines:
            line = self.clean_text(line)
            if not line:
                continue
            if _INSTRUCTIONS_MARKERS.search(line):
                in_instructions = True
                continue
            if in_instructions:
                # numbered: (1) or 1. or digits at start
                clean = re.sub(r'^\([0-9]+\)\s*', '', line).strip()
                clean = re.sub(r'^\s*\.\s*$', '', clean).strip()
                if clean:
                    steps.append(clean)
        return steps

    def extract_category(self) -> Optional[str]:
        """Extract category from breadcrumbs (second crumb after home)."""
        breads = self.soup.find('div', class_='breads')
        if not breads:
            return None
        links = breads.find_all('a')
        # links[0] = موسوعة الطبخ (home), links[1] = category, links[2] = sub-category
        if len(links) >= 2:
            # Return the last meaningful breadcrumb (sub-category preferred)
            for link in reversed(links[1:]):
                txt = self.clean_text(link.get_text())
                if txt:
                    return txt
        return None

    def _extract_time_from_text(self, text: str) -> Optional[str]:
        """
        Extract the most prominent time mention from Arabic text.
        Returns a human-readable string like '2 hours', '30 minutes', '1 hour 10 minutes'.
        """
        if not text:
            return None
        total_minutes = 0
        found = False

        # "نص ساعة" = exactly 30 minutes — check FIRST before generic hour match
        if re.search(r'نص\s+ساع[ةه]?', text):
            total_minutes += 30
            found = True
            # Also check for additional minutes in same context (e.g. "نص ساعة و10 دقائق")
            m2 = re.search(rf'(\d+)\s*(?:{_MIN_WORDS})', text)
            if m2:
                total_minutes += int(m2.group(1))
            hours, mins = divmod(total_minutes, 60)
            parts = []
            if hours:
                parts.append(f'{hours} hour{"s" if hours > 1 else ""}')
            if mins:
                parts.append(f'{mins} minute{"s" if mins > 1 else ""}')
            return ' '.join(parts) if parts else None

        # "ساعتين" = 2 hours
        if re.search(r'ساعتين', text):
            total_minutes += 120
            found = True

        if not found:
            # "N ساعات/ساعة/ساعه" – digits before hour word
            m = re.search(rf'(\d+)\s*(?:{_HOUR_WORDS})', text)
            if m:
                total_minutes += int(m.group(1)) * 60
                found = True
            elif re.search(r'ساع[ةه]', text):
                # Plain "ساعة" without preceding digit = 1 hour
                total_minutes += 60
                found = True

        # "N دقيقة/دقائق/دقايق/دقيقتين"
        if re.search(r'دقيقتين', text) and not re.search(rf'\d+\s*(?:{_MIN_WORDS})', text):
            total_minutes += 2
            found = True
        else:
            m2 = re.search(rf'(\d+)\s*(?:{_MIN_WORDS})', text)
            if m2:
                total_minutes += int(m2.group(1))
                found = True

        if not found or total_minutes == 0:
            return None

        hours, mins = divmod(total_minutes, 60)
        parts = []
        if hours:
            parts.append(f'{hours} hour{"s" if hours > 1 else ""}')
        if mins:
            parts.append(f'{mins} minute{"s" if mins > 1 else ""}')
        return ' '.join(parts) if parts else None

    def extract_prep_time(self) -> Optional[str]:
        """Extract prep time from text patterns related to preparation."""
        data_div = self.soup.find('div', class_='data')
        if not data_div:
            return None
        text = data_div.get_text()
        # Look for prep-related keywords
        prep_patterns = [
            r'(?:تترك|يترك|نتركه?|للنقع|نقع|ينقع|تنقع)[\s\S]{0,60}(?:' + _HOUR_WORDS + r'|' + _MIN_WORDS + r')',
            r'(?:تتبيل|التتبيل|التتبل|للتتبيل)[\s\S]{0,60}(?:' + _HOUR_WORDS + r'|' + _MIN_WORDS + r')',
        ]
        for pat in prep_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                snippet = m.group(0)
                t = self._extract_time_from_text(snippet)
                if t:
                    return t
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Extract cook time from text patterns related to cooking."""
        data_div = self.soup.find('div', class_='data')
        if not data_div:
            return None
        text = data_div.get_text()

        # Patterns: only within a single line (no cross-line matching)
        cook_patterns = [
            # "على النار ساعة" or "على النار N دقيقة" — limited to single line
            r'على\s+النار[^\n]{0,60}(?:' + _HOUR_WORDS + r'|' + _MIN_WORDS + r')',
            r'في\s+الفرن[^\n]{0,60}(?:' + _HOUR_WORDS + r'|' + _MIN_WORDS + r')',
            r'(?:يغلي|يطبخ|نطبخ|يُطبخ)[^\n]{0,60}(?:' + _HOUR_WORDS + r'|' + _MIN_WORDS + r')',
            # "يستوي اللحم" with preceding time
            r'(?:' + _HOUR_WORDS + r')[^\n]{0,60}(?:ينضج|يستوي)',
            r'(?:لمدة|ل)\s*\d+\s*(?:' + _HOUR_WORDS + r')',
        ]
        best_minutes = 0
        best_str = None
        for pat in cook_patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                snippet = m.group(0)
                t = self._extract_time_from_text(snippet)
                if t:
                    mins = self._time_str_to_minutes(t)
                    if mins > best_minutes:
                        best_minutes = mins
                        best_str = t
        return best_str

    @staticmethod
    def _time_str_to_minutes(t: str) -> int:
        """Convert '1 hour 10 minutes' style string back to total minutes."""
        total = 0
        m = re.search(r'(\d+)\s+hour', t)
        if m:
            total += int(m.group(1)) * 60
        m = re.search(r'(\d+)\s+minute', t)
        if m:
            total += int(m.group(1))
        return total

    def extract_total_time(self) -> Optional[str]:
        """Total time is usually not specified on this site."""
        return None

    def extract_notes(self) -> Optional[str]:
        """Extract notes / tips that appear after instructions."""
        content, layout = self._get_content_area()
        if content is None:
            return None

        try:
            if layout == 'font':
                return self._notes_font(content)
            elif layout in ('b', 'center'):
                return self._notes_b(content)
        except Exception as e:
            logger.warning('extract_notes error: %s', e)
        return None

    def _notes_font(self, center) -> Optional[str]:
        """Font layout: content of fonts after notes marker."""
        fonts = center.find_all('font')
        notes_parts: List[str] = []
        capture = False
        for font in fonts:
            txt = self.clean_text(font.get_text())
            if not txt:
                continue
            if _NOTES_MARKERS.search(txt) and len(txt) < 30:
                capture = True
                continue
            if capture:
                notes_parts.append(txt)
        return ' '.join(notes_parts) if notes_parts else None

    def _notes_b(self, b_tag) -> Optional[str]:
        """B-tag layout: lines after 'ملاحظه' marker."""
        text = b_tag.get_text()
        lines = self._split_lines(text)
        notes: List[str] = []
        capture = False
        for line in lines:
            line = self.clean_text(line)
            if not line:
                continue
            if _NOTES_MARKERS.search(line) and len(line) < 30:
                capture = True
                continue
            if capture:
                notes.append(line)
        return ' '.join(notes) if notes else None

    def extract_tags(self) -> Optional[str]:
        """Extract tags from meta keywords, filtered to meaningful ones."""
        # Try meta keywords
        kw_meta = self.soup.find('meta', attrs={'name': 'keywords'})
        if kw_meta and kw_meta.get('content'):
            raw = kw_meta['content']
            # The site uses generic site-wide keywords — filter them out
            generic = {
                'سعودي', 'طبخ', 'مطبخ', 'وصفة', 'وصفات', 'اكلات',
                'شركة اغذية', 'مطاعم', 'السعودية', 'مطعم',
                'saudi arabia', 'uae', 'الامارات العربية المتحدة',
                'arabic recipes', 'recipes of food in arabic',
                'united arab emirates',
            }
            # Split on comma or Arabic comma
            tags = [t.strip() for t in re.split(r'[,،]', raw) if t.strip()]
            filtered = [t for t in tags if t.lower() not in generic and len(t) > 2]
            if filtered:
                return ', '.join(filtered)

        # Fallback: use breadcrumb categories as tags
        breads = self.soup.find('div', class_='breads')
        if breads:
            links = breads.find_all('a')
            crumb_tags = [self.clean_text(a.get_text()) for a in links[1:] if self.clean_text(a.get_text())]
            if crumb_tags:
                return ', '.join(crumb_tags)

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Extract image URLs from the recipe content area."""
        content, _ = self._get_content_area()
        if content is None:
            return None

        urls = []
        for img in content.find_all('img'):
            # On encyclopediacooking.com the alt attribute often mirrors the src URL
            src = img.get('src', '') or ''
            if not src.startswith('http'):
                # Fallback: check alt only if it looks like an absolute URL
                alt = img.get('alt', '') or ''
                if alt.startswith('http'):
                    src = alt
            if src.startswith('http') and 'encyclopediacooking' in src:
                if src not in urls:
                    urls.append(src)

        # Also check og:image
        og = self.soup.find('meta', property='og:image')
        if og and og.get('content') and og['content'] not in urls:
            urls.append(og['content'])

        return ','.join(urls) if urls else None

    # ------------------------------------------------------------------
    # Main extraction method
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """Extract all recipe data and return as dict."""
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

        return {
            'dish_name': dish_name.lower() if dish_name else None,
            'description': description.lower() if description else None,
            'ingredients': ingredients,
            'instructions': instructions.lower() if instructions else None,
            'category': category.lower() if category else None,
            'prep_time': prep_time,
            'cook_time': cook_time,
            'total_time': total_time,
            'notes': notes.lower() if notes else None,
            'tags': tags,
            'image_urls': image_urls,
        }


def main():
    import os
    directory = os.path.join('preprocessed', 'encyclopediacooking_com')
    if os.path.exists(directory) and os.path.isdir(directory):
        process_directory(EncyclopediacookingComExtractor, directory)
        return
    print(f'Директория не найдена: {directory}')


if __name__ == '__main__':
    main()
