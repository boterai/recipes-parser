"""
Экстрактор данных рецептов для сайта jadilaper.com

Структура страниц:
- WordPress-сайт (Twenty Twenty-Five тема), без WPRM/JSON-LD рецептов
- dish_name из h1.wp-block-post-title
- description из meta[name=description] или первого параграфа entry-content
- ingredients из UL.wp-block-list под h2/h3 «Bahan...» ИЛИ параграф с «–» разделителями
- instructions из OL.wp-block-list ИЛИ параграф с нумерованными шагами «1. … 2. …»
- category из CSS-класса body category-* или None
- tags из a[rel=tag]
- image_urls из img.wp-post-image
"""

import sys
import re
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Индонезийские единицы измерения, от длинных к коротким
_UNIT_PATTERN = (
    r'(?:'
    r'gram|kg|gr|liter|ml|mL'
    r'|sdm|sdt'
    r'|siung|butir|buah|ruas|porsi|mangkuk'
    r'|sachet|batang|lembar|biji|ikat|genggam|cangkir'
    r'|lbr|btg|bh'
    r'|g(?=\s|$)|l(?=\s|$)'   # single-letter only at word boundary
    r')'
)

# Ingredient line pattern: optional amount, optional unit, name
# Handles: "½ kg daging ayam", "10 siung bawang putih", "Garam secukupnya", "2–3 sdm kimchi"
_INGR_RE = re.compile(
    r'^'
    r'(?P<amount>[\d\s/.,½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘]+(?:\s*[–\-]\s*[\d½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘]+)?)?'
    r'\s*'
    r'(?P<unit>' + _UNIT_PATTERN + r')?\s*'
    r'(?P<name>.+)?$',
    re.IGNORECASE,
)

# Unicode fraction map
_FRACTIONS = {
    '½': '1/2', '¼': '1/4', '¾': '3/4',
    '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
    '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
    '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5',
}

# Keywords for heading detection (lowercase)
_BAHAN_KW = ('bahan', 'ingredient', 'material')
_CARA_KW = ('cara membuat', 'cara memasak', 'langkah', 'petunjuk', 'step', 'method',
             'instruksi', 'pembuatan')
_NOTES_KW = ('catatan', 'tips', 'note', 'kiat', 'saran', 'info', 'penting',
              'perhatian', 'tambahan')

# Closing-paragraph noise patterns (skip these for notes)
_CLOSING_NOISE = re.compile(
    r'^(itulah|bagaimana|nah|demikian|baca juga|yuk|selamat|semoga|simak|jangan lupa'
    r'|langsung\b)',
    re.IGNORECASE,
)


class JadilaperComExtractor(BaseRecipeExtractor):
    """Экстрактор для jadilaper.com"""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_fractions(text: str) -> str:
        """Replace unicode fraction chars with ASCII equivalents."""
        for frac, repl in _FRACTIONS.items():
            text = text.replace(frac, repl)
        return text

    def _get_entry_content(self):
        """Return the main entry-content div (cached)."""
        if not hasattr(self, '_entry'):
            self._entry = self.soup.find(class_='entry-content') or self.soup.find(
                class_='wp-block-post-content'
            )
        return self._entry

    # ------------------------------------------------------------------
    # dish_name
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из h1."""
        h1 = self.soup.find('h1', class_='wp-block-post-title')
        if not h1:
            h1 = self.soup.find('h1')
        if not h1:
            # fallback: og:title
            og = self.soup.find('meta', property='og:title')
            if og and og.get('content'):
                return self.clean_text(og['content'])
            return None

        title = self.clean_text(h1.get_text())
        # Strip leading "Resep " prefix (case-insensitive)
        title = re.sub(r'^Resep\s+', '', title, flags=re.IGNORECASE)
        # Strip subtitle after first ", " e.g. "Bibimbap, Nasi Campur..." → "Bibimbap"
        if ', ' in title:
            title = title.split(', ')[0].strip()
        # Strip " yang/yg [descriptive clause]" at the end
        title = re.sub(
            r'\s+(?:yang|yg)\s+.+$', '', title, flags=re.IGNORECASE
        ).strip()
        # Strip trailing punctuation
        title = title.rstrip('!?.').strip()
        return title if title else None

    # ------------------------------------------------------------------
    # description
    # ------------------------------------------------------------------

    def extract_description(self) -> Optional[str]:
        """Извлечение краткого описания."""
        # 1. meta[name=description]
        meta = self.soup.find('meta', attrs={'name': 'description'})
        if meta and meta.get('content'):
            return self.clean_text(meta['content'])

        # 2. og:description
        og = self.soup.find('meta', property='og:description')
        if og and og.get('content'):
            return self.clean_text(og['content'])

        # 3. First non-empty paragraph in entry-content
        entry = self._get_entry_content()
        if entry:
            for p in entry.find_all('p'):
                txt = self.clean_text(p.get_text())
                if txt and len(txt) > 30:
                    return txt

        return None

    # ------------------------------------------------------------------
    # Ingredient parsing helpers
    # ------------------------------------------------------------------

    def _parse_ingredient_text(self, raw: str) -> Optional[Dict[str, Any]]:
        """
        Parse a single ingredient string into {name, amount, unit}.

        Handles formats:
          - "½ kg daging ayam, disarankan bagian paha"
          - "10 siung bawang putih, tak perlu dikupas"
          - "Garam secukupnya"
          - "2–3 sdm kimchi"
        """
        raw = self.clean_text(raw)
        raw = self._normalize_fractions(raw)

        # Skip empty / header-like lines
        if not raw or len(raw) < 2:
            return None
        # Skip lines that look like section headers (e.g. "Bahan utama:")
        if raw.endswith(':') and len(raw) < 50:
            return None

        # Handle "secukupnya" (to taste / as needed) - it's often at the end
        secukupnya_re = re.compile(r'\bsecukupnya\b', re.I)

        m = _INGR_RE.match(raw)
        if not m:
            # Try to extract secukupnya as amount
            if secukupnya_re.search(raw):
                name = secukupnya_re.sub('', raw).strip().rstrip(',').strip()
                return {'name': name or raw, 'amount': 'secukupnya', 'unit': None}
            return {'name': raw, 'amount': None, 'unit': None}

        amount_raw = (m.group('amount') or '').strip()
        unit = (m.group('unit') or '').strip().lower() or None
        name = (m.group('name') or '').strip()

        # If secukupnya is in the name part, move it to amount
        if not amount_raw and name and secukupnya_re.search(name):
            name = secukupnya_re.sub('', name).strip().rstrip(',').strip()
            amount_raw = 'secukupnya'

        # If entire text contains only secukupnya with a name
        if secukupnya_re.search(raw) and not amount_raw:
            amount_raw = 'secukupnya'
            name_candidate = secukupnya_re.sub('', raw).strip().rstrip(',').strip()
            if name_candidate:
                name = name_candidate

        # Clean name: remove trailing preparation description after comma
        # e.g. "daging ayam, disarankan bagian paha" → "daging ayam"
        if name and ',' in name:
            parts = name.split(',', 1)
            qualifier = parts[1].strip()
            # Strip qualifier if it's clearly a prep note (verb-first)
            prep_qualifiers = re.compile(
                r'^(disarankan|potong|iris|cincang|sangrai|haluskan|kupas|bersih'
                r'|kocok|parut|rebus|goreng|tambahkan|boleh|tak perlu|jika|untuk'
                r'|dicuci|dipotong|dihaluskan|dicincang|disangrai)',
                re.IGNORECASE,
            )
            if prep_qualifiers.match(qualifier) or len(qualifier) > 35:
                name = parts[0].strip()

        # Normalize amount: handle ranges "2–3" → keep as "2–3"
        amount = amount_raw if amount_raw else None

        if not name or len(name) < 2:
            # Whole string is the name
            return {'name': raw, 'amount': None, 'unit': None}

        return {
            'name': name,
            'amount': amount if amount else None,
            'unit': unit,
        }

    def _parse_dash_paragraph(self, text: str) -> List[Dict[str, Any]]:
        """
        Parse a paragraph where ingredients are separated by '–' (en-dash).

        Example: "– 2 dada ayam tanpa tulang, potong dadu– 2 siung bawang putih..."
        """
        # Split on '–' or '—' that appears inline (not at line start) or at line start
        parts = re.split(r'[–—]', text)
        ingredients = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            parsed = self._parse_ingredient_text(part)
            if parsed:
                ingredients.append(parsed)
        return ingredients

    def _split_compound_ingredient(self, text: str) -> List[str]:
        """
        Split compound ingredient lines joined with commas and "dan" (and).

        E.g. "Garam, lada bubuk, dan gula secukupnya"
             → ["Garam secukupnya", "lada bubuk secukupnya", "gula secukupnya"]

        Only splits if all parts share a common qualifier like "secukupnya".
        """
        # Check for trailing qualifier
        qualifier_re = re.compile(r'\b(secukupnya|opsional|optional|to taste)\s*$', re.I)
        m = qualifier_re.search(text)
        qualifier = m.group(0).strip() if m else None

        if not qualifier:
            return [text]

        # Strip qualifier from end
        base = qualifier_re.sub('', text).strip().rstrip(',').strip()

        # Split on ", " and " dan " (Indonesian "and")
        parts = re.split(r',\s*(?:dan\s+)?|(?:\bdan\s+)', base)
        parts = [p.strip() for p in parts if p.strip()]

        if len(parts) <= 1:
            return [text]

        # Rebuild each part with the qualifier
        return [f'{p} {qualifier}' for p in parts]

    # ------------------------------------------------------------------
    # ingredients
    # ------------------------------------------------------------------

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов.

        Два формата:
        1. UL.wp-block-list под h2/h3 «Bahan…»
        2. <p> с «–» разделителями под h2/h3 «Bahan…»
        """
        entry = self._get_entry_content()
        if not entry:
            logger.warning('No entry-content found for %s', self.html_path)
            return None

        ingredients: List[Dict[str, Any]] = []

        # Collect all headings that indicate an ingredient section
        headings = entry.find_all(['h2', 'h3'])
        for heading in headings:
            h_text = heading.get_text().strip().lower()
            if not any(kw in h_text for kw in _BAHAN_KW):
                continue

            # Determine section label for disambiguation (e.g. "bumbu marinasi")
            section_label = self._extract_section_label(heading.get_text())

            # Track names seen so far to detect duplicates needing section label
            seen_names_before = {i['name'].lower() for i in ingredients}

            # Gather siblings until the next h2/h3
            sib = heading.find_next_sibling()
            section_ingredients: List[Dict[str, Any]] = []
            while sib:
                if sib.name in ('h2', 'h3'):
                    break
                if sib.name == 'ul':
                    # Format 1: UL list
                    for li in sib.find_all('li'):
                        raw = self.clean_text(li.get_text(separator=' ', strip=True))
                        if not raw:
                            continue
                        # Handle compound items like "Garam, lada bubuk, dan gula secukupnya"
                        parts = self._split_compound_ingredient(raw)
                        for part in parts:
                            parsed = self._parse_ingredient_text(part)
                            if parsed:
                                section_ingredients.append(parsed)
                elif sib.name == 'p':
                    p_text = self.clean_text(sib.get_text(separator='', strip=True))
                    if p_text and '–' in p_text:
                        # Format 2: dash-separated paragraph
                        parsed_list = self._parse_dash_paragraph(p_text)
                        section_ingredients.extend(parsed_list)
                sib = sib.find_next_sibling()

            # Add section label to names that conflict with earlier sections
            for item in section_ingredients:
                name_lower = item['name'].lower()
                if name_lower in seen_names_before and section_label:
                    item['name'] = f"{item['name']} ({section_label})"
                ingredients.append(item)

        if not ingredients:
            logger.warning('No ingredients found in %s', self.html_path)
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    @staticmethod
    def _extract_section_label(heading_text: str) -> Optional[str]:
        """
        Extract a meaningful label from a 'Bahan ...' heading.
        E.g. "Bahan bumbu marinasi" → "bumbu marinasi"
             "Bahan-bahan" → None
             "Bahan untuk membuat saus" → "saus"
        """
        text = re.sub(r'^Bahan[\s\-]+', '', heading_text, flags=re.IGNORECASE).strip()
        # Strip generic words
        text = re.sub(r'^(utama|untuk membuat|bahan\b)', '', text, flags=re.IGNORECASE).strip()
        # Shorten: keep last noun if "untuk X" or "membuat X"
        m = re.search(r'\b(saus|kuah|bumbu|marinasi|isian|topping|pelengkap|sambal)\b', text, re.I)
        if m:
            # take from this keyword to the end
            label = text[m.start():].strip()
            return label if label and len(label) < 30 else None
        return text if text and len(text) < 30 else None

    # ------------------------------------------------------------------
    # instructions
    # ------------------------------------------------------------------

    def extract_instructions(self) -> Optional[str]:
        """
        Извлечение инструкций.

        Два формата:
        1. OL.wp-block-list под h2/h3 «Cara membuat…»
        2. <p> с нумерованными шагами «1. … 2. …» под тем же заголовком
        """
        entry = self._get_entry_content()
        if not entry:
            return None

        steps: List[str] = []

        # Try to find an instruction heading
        instruction_heading = None
        for heading in entry.find_all(['h2', 'h3']):
            h_text = heading.get_text().strip().lower()
            if any(kw in h_text for kw in _CARA_KW):
                instruction_heading = heading
                break

        # If we found a heading, gather content under it
        if instruction_heading:
            sib = instruction_heading.find_next_sibling()
            while sib:
                if sib.name in ('h2', 'h3'):
                    break
                if sib.name == 'ol':
                    # Format 1: ordered list
                    for li in sib.find_all('li'):
                        txt = self.clean_text(li.get_text(separator=' ', strip=True))
                        txt = txt.rstrip('\\').strip()
                        if txt:
                            steps.append(txt)
                elif sib.name == 'p':
                    p_text = self.clean_text(sib.get_text(separator=' ', strip=True))
                    if not p_text:
                        sib = sib.find_next_sibling()
                        continue

                    # Format 2: numbered paragraph "1. Step 2. Step …"
                    numbered = re.split(r'(?=\d+\.\s)', p_text)
                    numbered = [s.strip() for s in numbered if s.strip()]
                    if len(numbered) > 1 or re.match(r'^\d+\.', p_text):
                        for step in numbered:
                            # Strip leading "N. "
                            step = re.sub(r'^\d+\.\s*', '', step).strip()
                            if step:
                                steps.append(step)
                    # Skip non-step paragraphs (captions, intro text)
                sib = sib.find_next_sibling()

        # Fallback: first OL in entry-content
        if not steps:
            for ol in entry.find_all('ol', class_='wp-block-list'):
                for li in ol.find_all('li'):
                    txt = self.clean_text(li.get_text(separator=' ', strip=True))
                    txt = txt.rstrip('\\').strip()
                    if txt:
                        steps.append(txt)
                if steps:
                    break

        if not steps:
            logger.warning('No instructions found in %s', self.html_path)
            return None

        # Join steps into one string
        return ' '.join(steps)

    # ------------------------------------------------------------------
    # category
    # ------------------------------------------------------------------

    def extract_category(self) -> Optional[str]:
        """
        Извлечение категории из классов body (category-*) или wp-block-post-terms.
        Returns None for generic "resep" (recipe) category.
        """
        body = self.soup.find('body')
        if body:
            for cls in body.get('class', []):
                if cls.startswith('category-'):
                    cat = cls[len('category-'):].replace('-', ' ')
                    # Skip generic categories
                    if cat.lower() not in ('resep', 'recipe', 'recipes', 'uncategorized'):
                        return cat.title()

        # Try wp-block-post-terms (taxonomy-category)
        terms = self.soup.find_all(class_='taxonomy-category')
        for t in terms:
            links = t.find_all('a')
            for link in links:
                txt = self.clean_text(link.get_text())
                if txt and txt.lower() not in ('resep', 'recipe', 'recipes', 'uncategorized'):
                    return txt

        return None

    # ------------------------------------------------------------------
    # times
    # ------------------------------------------------------------------

    def _extract_time_from_text(self, text: str, keyword: str) -> Optional[str]:
        """
        Search for time patterns near a keyword in a block of text.

        Patterns:
          - "selama N menit"
          - "N menit" in context of keyword
          - "N jam N menit"
        """
        # Normalize
        text = text.lower()

        # Full time patterns: "selama N menit", "± N menit", "kurang lebih N menit"
        pattern = re.compile(
            r'(?:selama|kurang\s+lebih|sekitar|±|kira-kira)?\s*'
            r'(\d+(?:[.,]\d+)?)\s*'
            r'(?:jam\s+(\d+)\s*menit|jam|menit)',
            re.IGNORECASE,
        )
        for m in pattern.finditer(text):
            hours_str = None
            # Check what was matched
            match_text = m.group(0)
            if 'jam' in match_text and 'menit' in match_text:
                hours = int(m.group(1))
                mins = int(m.group(2))
                total = hours * 60 + mins
                return f'{total} minutes'
            elif 'jam' in match_text:
                hours = int(m.group(1))
                return f'{hours * 60} minutes'
            else:
                mins = int(m.group(1))
                return f'{mins} minutes'

        return None

    def _get_instruction_text(self) -> str:
        """Return full instruction text as a single string."""
        entry = self._get_entry_content()
        if not entry:
            return ''
        # Grab all OL and instruction paragraphs
        parts = []
        for ol in entry.find_all('ol', class_='wp-block-list'):
            parts.append(ol.get_text(' ', strip=True))
        # Also grab numbered paragraphs
        for p in entry.find_all('p'):
            txt = p.get_text(' ', strip=True)
            if re.match(r'\d+\.', txt):
                parts.append(txt)
        return ' '.join(parts)

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки из текста инструкций."""
        instr = self._get_instruction_text()
        # Look for "marinasi/diamkan … N menit" (rest/marinade time)
        # Handle range "N sampai M menit" → take the lower bound
        pattern = re.compile(
            r'(?:marinasi|diamkan|rendam|istirahatkan|didiamkan)'
            r'[^.]{0,60}?'
            r'(\d+)\s*(?:sampai|hingga|–|-)\s*(\d+)\s*menit'
            r'|'
            r'(?:marinasi|diamkan|rendam|istirahatkan|didiamkan)'
            r'[^.]{0,60}?'
            r'(\d+)\s*menit',
            re.IGNORECASE,
        )
        m = pattern.search(instr)
        if m:
            if m.group(1):  # range "N sampai M menit"
                return f'{m.group(1)} minutes'
            elif m.group(3):  # single "N menit"
                return f'{m.group(3)} minutes'
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления из текста инструкций."""
        instr = self._get_instruction_text()
        # Look for cooking verbs followed closely by a time
        pattern = re.compile(
            r'(?:masak|goreng|tumis|panggang|rebus|kukus|bakar|didihkan)'
            r'[^.]{0,60}?'
            r'(\d+)\s*(?:sampai|hingga|–|-)\s*(\d+)\s*menit'
            r'|'
            r'(?:masak|goreng|tumis|panggang|rebus|kukus|bakar|didihkan)'
            r'[^.]{0,40}?'
            r'selama\s+(\d+)\s*menit',
            re.IGNORECASE,
        )
        m = pattern.search(instr)
        if m:
            if m.group(1):  # range
                return f'{m.group(1)} minutes'
            elif m.group(3):
                return f'{m.group(3)} minutes'
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени (только если известны и prep, и cook)."""
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()

        def to_min(t: Optional[str]) -> Optional[int]:
            if not t:
                return None
            m = re.search(r'(\d+)', t)
            return int(m.group(1)) if m else None

        p = to_min(prep)
        c = to_min(cook)
        if p and c:
            return f'{p + c} minutes'
        # Only return total if both are known
        return None

    # ------------------------------------------------------------------
    # notes
    # ------------------------------------------------------------------

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок/советов.

        Приоритет:
        1. Параграф под h2/h3 с ключевыми словами (catatan/tips/…)
        2. Примечания из скобок в ингредиентах (boleh diganti X, opsional) — если есть
        3. Параграф между последним OL/UL и HR-разделителем (не шумовые)
        4. Закрывающий параграф после HR — только значимые предложения
        """
        entry = self._get_entry_content()
        if not entry:
            return None

        # 1. Dedicated notes/tips heading
        for heading in entry.find_all(['h2', 'h3']):
            h_text = heading.get_text().strip().lower()
            if any(kw in h_text for kw in _NOTES_KW):
                sib = heading.find_next_sibling()
                parts = []
                while sib and sib.name not in ('h2', 'h3', 'hr'):
                    if sib.name in ('p', 'li'):
                        txt = self.clean_text(sib.get_text())
                        if txt:
                            parts.append(txt)
                    elif sib.name in ('ul', 'ol'):
                        for item in sib.find_all('li'):
                            txt = self.clean_text(item.get_text())
                            if txt:
                                parts.append(txt)
                    sib = sib.find_next_sibling()
                if parts:
                    return ' '.join(parts)

        # 2. Ingredient annotations (explicit tips like "boleh diganti X", "opsional")
        notes_from_ingr = self._extract_ingredient_notes(entry)
        if notes_from_ingr:
            return notes_from_ingr

        # 3. Paragraph after last instruction block and before HR
        last_instr = None
        for ol in entry.find_all('ol', class_='wp-block-list'):
            last_instr = ol
        if last_instr is None:
            # fallback: numbered paragraph
            for p in entry.find_all('p'):
                if re.match(r'\d+\.', p.get_text(strip=True)):
                    last_instr = p

        if last_instr:
            sib = last_instr.find_next_sibling()
            while sib:
                if sib.name == 'hr':
                    break
                if sib.name == 'p':
                    txt = self.clean_text(sib.get_text())
                    if txt and len(txt) > 15:
                        if not _CLOSING_NOISE.match(txt):
                            return txt
                        # Try to extract meaningful sentences from noise paragraph
                        meaningful = self._extract_meaningful_sentences(txt)
                        if meaningful and not self._is_generic_closing(meaningful):
                            return meaningful
                sib = sib.find_next_sibling()

        # 4. Closing paragraphs after HR — extract meaningful sentences
        hr = entry.find('hr')
        if hr:
            for sib in hr.next_siblings:
                if not hasattr(sib, 'name') or not sib.name:
                    continue
                if sib.name == 'p':
                    txt = self.clean_text(sib.get_text())
                    if txt and len(txt) > 15:
                        if not _CLOSING_NOISE.match(txt):
                            return txt
                        meaningful = self._extract_meaningful_sentences(txt)
                        if meaningful and not self._is_generic_closing(meaningful):
                            return meaningful

        return None

    @staticmethod
    def _is_generic_closing(text: str) -> bool:
        """Check if text is a generic closing statement without useful info."""
        generic_re = re.compile(
            r'\b(mudah\b.*\bkan|cara membuatnya|tidak begitu banyak|tidak sulit|tunggu apalagi'
            r'|resep roti|roti kopi|bahan sederhana)\b',
            re.IGNORECASE,
        )
        return bool(generic_re.search(text)) and len(text) < 200

    @staticmethod
    def _extract_meaningful_sentences(text: str) -> Optional[str]:
        """
        Extract meaningful (non-noise) sentences from a paragraph.
        Splits on sentence boundaries and filters out intro/noise sentences.
        """
        sentences = re.split(r'(?<=[.!?])\s+', text)
        noise_re = re.compile(
            r'^(itulah|bagaimana|nah\b|demikian|baca juga|yuk\b|selamat|semoga'
            r'|simak|jangan lupa|jadi\b|langsung\b)',
            re.IGNORECASE,
        )
        meaningful = []
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            # Skip if the whole sentence starts with noise
            if noise_re.match(s):
                continue
            # Skip very short fragments that are likely noise
            if len(s) < 10:
                continue
            meaningful.append(s)
        return ' '.join(meaningful) if meaningful else None

    def _extract_ingredient_notes(self, entry) -> Optional[str]:
        """Extract notes from parenthetical annotations in ingredient lines."""
        note_phrases = []
        # Match any meaningful annotation in parentheses
        annotation_re = re.compile(
            r'\(([^)]+(?:boleh|opsional|optional|bisa|diganti|dapat)[^)]*)\)',
            re.IGNORECASE,
        )
        optional_standalone_re = re.compile(r'^\(opsional\)$', re.IGNORECASE)

        def _clean_name(txt: str, annotation_start: int) -> str:
            name_part = txt[:annotation_start].strip().rstrip(',').strip()
            return re.sub(
                r'^[\d\s/.,½¼¾⅓⅔⅛–\-]+'
                r'(?:kg|gram|gr|liter|ml|sdm|sdt|siung|butir|buah|ruas|porsi|mangkuk|g|l)?\s*',
                '', name_part, flags=re.IGNORECASE
            ).strip()

        def _items_from_text(text: str) -> List[str]:
            """Split text into ingredient lines."""
            # UL-style: each li text
            # P-style: split on '–'
            if '–' in text:
                return [p.strip() for p in re.split(r'[–—]', text) if p.strip()]
            return [text]

        # Check UL items
        for ul in entry.find_all('ul', class_='wp-block-list'):
            for li in ul.find_all('li'):
                txt = li.get_text().strip()
                m = annotation_re.search(txt)
                if m:
                    name = _clean_name(txt, m.start())
                    annotation = m.group(1).strip()
                    if name:
                        note_phrases.append(f'{name} ({annotation})')

        # Check P elements with dash format
        for p in entry.find_all('p'):
            p_txt = p.get_text()
            if '–' not in p_txt:
                continue
            for part in re.split(r'[–—]', p_txt):
                part = part.strip()
                m = annotation_re.search(part)
                if m:
                    name = _clean_name(part, m.start())
                    annotation = m.group(1).strip()
                    if name and f'{name} ({annotation})' not in note_phrases:
                        note_phrases.append(f'{name} ({annotation})')

        # Also capture standalone "(opsional)" without other annotation keywords
        # by checking for items with "(opsional)" that weren't captured above
        opsional_re = re.compile(r'\(opsional\)', re.IGNORECASE)
        for ul in entry.find_all('ul', class_='wp-block-list'):
            for li in ul.find_all('li'):
                txt = li.get_text().strip()
                if opsional_re.search(txt) and not annotation_re.search(txt):
                    name = _clean_name(txt, opsional_re.search(txt).start())
                    if name:
                        note_phrases.append(f'{name} (opsional)')
        for p in entry.find_all('p'):
            p_txt = p.get_text()
            if '–' not in p_txt:
                continue
            for part in re.split(r'[–—]', p_txt):
                part = part.strip()
                if opsional_re.search(part) and not annotation_re.search(part):
                    m2 = opsional_re.search(part)
                    name = _clean_name(part, m2.start())
                    note = f'{name} (opsional)'
                    if name and note not in note_phrases:
                        note_phrases.append(note)

        return '. '.join(note_phrases) + '.' if note_phrases else None

    # ------------------------------------------------------------------
    # tags
    # ------------------------------------------------------------------

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из a[rel=tag] и wp-block-post-terms."""
        tags: List[str] = []

        # 1. a[rel=tag] links
        tag_links = self.soup.find_all('a', rel='tag')
        for link in tag_links:
            txt = self.clean_text(link.get_text())
            if txt and txt not in tags:
                tags.append(txt)

        # 2. wp-block-post-terms for any taxonomy (tags/categories)
        for terms_div in self.soup.find_all(class_=re.compile(r'taxonomy|post-terms', re.I)):
            for a in terms_div.find_all('a'):
                txt = self.clean_text(a.get_text())
                if txt and txt not in tags:
                    tags.append(txt)

        return ', '.join(tags) if tags else None

    # ------------------------------------------------------------------
    # image_urls
    # ------------------------------------------------------------------

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта."""
        urls: List[str] = []

        # 1. Featured image (wp-post-image) — highest quality from srcset
        wp_img = self.soup.find('img', class_='wp-post-image')
        if wp_img:
            src = self._best_srcset_url(wp_img) or wp_img.get('src')
            if src:
                urls.append(src)

        # 2. og:image meta tag
        og = self.soup.find('meta', property='og:image')
        if og and og.get('content') and og['content'] not in urls:
            urls.append(og['content'])

        # 3. Images inside entry-content figures (step images)
        entry = self._get_entry_content()
        if entry:
            for figure in entry.find_all('figure', class_=re.compile(r'wp-block-image', re.I)):
                img = figure.find('img')
                if img:
                    src = self._best_srcset_url(img) or img.get('src')
                    if src and src not in urls and self._is_recipe_image(src):
                        urls.append(src)

        # Deduplicate, keep first 10
        seen: set = set()
        unique: List[str] = []
        for u in urls:
            if u and u not in seen:
                seen.add(u)
                unique.append(u)
                if len(unique) >= 10:
                    break

        return ','.join(unique) if unique else None

    @staticmethod
    def _best_srcset_url(img_tag) -> Optional[str]:
        """Extract the largest URL from a srcset attribute."""
        srcset = img_tag.get('srcset', '')
        if not srcset:
            return None
        # "url1 300w, url2 700w" → pick largest width
        candidates = []
        for part in srcset.split(','):
            part = part.strip()
            if not part:
                continue
            tokens = part.split()
            if len(tokens) >= 2:
                url = tokens[0]
                try:
                    width = int(tokens[1].replace('w', ''))
                    candidates.append((width, url))
                except ValueError:
                    candidates.append((0, url))
            elif tokens:
                candidates.append((0, tokens[0]))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]
        return None

    @staticmethod
    def _is_recipe_image(url: str) -> bool:
        """Heuristic: skip logos / icons, keep recipe/food images."""
        # Skip common non-food image paths
        skip_patterns = re.compile(
            r'(logo|icon|avatar|gravatar|banner|cropped|spinner|placeholder)',
            re.IGNORECASE,
        )
        return not skip_patterns.search(url)

    # ------------------------------------------------------------------
    # extract_all
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта."""
        try:
            dish_name = self.extract_dish_name()
        except Exception as e:
            logger.error('extract_dish_name failed: %s', e)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as e:
            logger.error('extract_description failed: %s', e)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as e:
            logger.error('extract_ingredients failed: %s', e)
            ingredients = None

        try:
            instructions = self.extract_instructions()
        except Exception as e:
            logger.error('extract_instructions failed: %s', e)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as e:
            logger.error('extract_category failed: %s', e)
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception as e:
            logger.error('extract_prep_time failed: %s', e)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception as e:
            logger.error('extract_cook_time failed: %s', e)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception as e:
            logger.error('extract_total_time failed: %s', e)
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception as e:
            logger.error('extract_notes failed: %s', e)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as e:
            logger.error('extract_tags failed: %s', e)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as e:
            logger.error('extract_image_urls failed: %s', e)
            image_urls = None

        return {
            'dish_name': dish_name,
            'description': description,
            'ingredients': ingredients,
            'instructions': instructions,
            'category': category,
            'prep_time': prep_time,
            'cook_time': cook_time,
            'total_time': total_time,
            'notes': notes,
            'tags': tags,
            'image_urls': image_urls,
        }


def main():
    import os
    recipes_dir = os.path.join('preprocessed', 'jadilaper_com')
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(JadilaperComExtractor, str(recipes_dir))
        return

    print(f'Директория не найдена: {recipes_dir}')
    print('Использование: python jadilaper_com.py [путь_к_файлу_или_директории]')


if __name__ == '__main__':
    main()
