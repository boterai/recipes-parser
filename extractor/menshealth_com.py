"""
Экстрактор данных рецептов для сайта menshealth.com
"""

import sys
import logging
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Italian measurement units (sorted by length descending for correct alternation priority)
_IT_UNITS = [
    'cucchiaini', 'cucchiaino', 'cucchiai', 'cucchiaio',
    'grammi', 'grammo',
    'litri', 'litro',
    'porzioni', 'porzione',
    'mazzetti', 'mazzetto',
    'bicchieri', 'bicchiere',
    'bustine', 'bustina',
    'pizzichi', 'pizzico',
    'rametti', 'rametto',
    'foglie', 'foglia',
    'spicchi', 'spicchio',
    'fette', 'fetta',
    'pezzi', 'pezzo',
    'tazze', 'tazza',
    'fili', 'filo',
    'ml', 'dl', 'cl', 'kg', 'g', 'l',
]

_IT_UNIT_PATTERN = (
    r'(?:'
    + '|'.join(re.escape(u) for u in sorted(_IT_UNITS, key=len, reverse=True))
    + r')(?=\s|$)'
)

# Unicode fraction normalisation
_FRACTION_MAP: dict = {
    '\u00bd': '1/2', '\u00bc': '1/4', '\u00be': '3/4',
    '\u2153': '1/3', '\u2154': '2/3', '\u215b': '1/8',
    '\u215c': '3/8', '\u215d': '5/8', '\u215e': '7/8',
}

# Italian prepositions to strip from the start of ingredient names
_IT_PREP_RE = re.compile(
    r"^(?:di\s+|d['\u2019]\s*|del\s+|della\s+|degli\s+|delle\s+|dello\s+|"
    r"al\s+|alla\s+|allo\s+|agli\s+|alle\s+)",
    re.IGNORECASE,
)

# Non-food words that signal descriptive/explanatory text (not ingredient names)
_DESC_WORDS_RE = re.compile(
    r'^\s*(?:meglio|anche|tipicamente|che|scegli|evita|per\s+chi|come(?!\s+noto))',
    re.IGNORECASE,
)

# H2 keywords that mark navigation / sidebar / footer sections
_STOP_H2_KEYWORDS = [
    'leggi anche', 'related stories', 'ricette',
    'couscous gourmet', 'olio extravergine', 'mozzarella di bufala',
]

# Amount pattern: integers, decimals, fractions ("1/2"), ranges ("2-3")
_AMT_PAT = (
    r'((?:\d+\s*/\s*\d+|\d+[.,]\d+|\d+)'
    r'(?:\s*[-\u2013]\s*(?:\d+\s*/\s*\d+|\d+[.,]\d+|\d+))?)'
)

# Optional Italian preposition after unit
_IT_PREP_OPT = (
    r"(?:di\s+|d['\u2019]\s*|del\s+|della\s+|degli\s+|delle\s+|dello\s+|"
    r"al\s+|alla\s+|allo\s+|agli\s+|alle\s+)?"
)


class MenshealthComExtractor(BaseRecipeExtractor):
    """Экстрактор для menshealth.com"""

    # ────────────────────────────────── internal helpers ──────────────────────────

    def _get_main(self):
        """Return <main> element or fall back to <body>."""
        return self.soup.find('main') or self.soup.find('body')

    def _get_news_ld(self) -> Optional[dict]:
        """Return first NewsArticle / Article JSON-LD dict found on the page."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
                for item in (data if isinstance(data, list) else [data]):
                    if not isinstance(item, dict):
                        continue
                    raw_type = item.get('@type', '')
                    types = raw_type if isinstance(raw_type, list) else [raw_type]
                    if any(t in ('NewsArticle', 'Article') for t in types):
                        return item
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    def _section_elements(self, h2_el):
        """
        Yield <p>, <ul>, <ol> direct siblings of *h2_el* until the next <h2>.
        Empty <div>s and other non-content elements are skipped silently.
        """
        sib = h2_el.find_next_sibling()
        while sib and sib.name != 'h2':
            if sib.name in ('p', 'ul', 'ol'):
                yield sib
            sib = sib.find_next_sibling()

    def _is_stop_section(self, h2_text: str) -> bool:
        """Return True if this H2 marks a navigation / footer block."""
        t = h2_text.lower().strip()
        return any(kw in t for kw in _STOP_H2_KEYWORDS)

    @staticmethod
    def _normalise_fractions(text: str) -> str:
        for k, v in _FRACTION_MAP.items():
            text = text.replace(k, v)
        return text

    @staticmethod
    def _is_footer_para(text: str) -> bool:
        t = text.lower()
        return 'scritto da' in t or 'tradotto da' in t or 'collaboratori' in t

    # ─────────────────────────────── ingredient parsing ───────────────────────────

    def _parse_ingredient_it(self, raw: str) -> Optional[dict]:
        """
        Parse one Italian ingredient line into {name, amount, unit}.

        Examples::

            "2 cucchiai di yogurt greco"  → {name:"yogurt greco", amount:"2", unit:"cucchiai"}
            "1/2 cucchiaio di burro"      → {name:"burro", amount:"1/2", unit:"cucchiaio"}
            "2 uova grandi"               → {name:"uova grandi", amount:"2", unit:None}
            "Sale kosher"                 → {name:"sale kosher", amount:None, unit:None}
        """
        if not raw:
            return None
        text = self._normalise_fractions(self.clean_text(raw.strip()))
        if not text or len(text) < 2:
            return None

        # ── Case 1: amount + unit + [prep] + name ─────────────────────────────
        m = re.match(
            rf'^{_AMT_PAT}\s+({_IT_UNIT_PATTERN})\s+{_IT_PREP_OPT}(.+)$',
            text,
            re.IGNORECASE,
        )
        if m:
            amount_str = m.group(1).strip()
            unit = m.group(2).lower()
            name = m.group(3).strip()
            name = _IT_PREP_RE.sub('', name).strip().rstrip(',;:.')
            name = self.clean_text(name)
            if name:
                return {"name": name.lower(), "amount": amount_str, "unit": unit}

        # ── Case 2: amount + [possible unit at start] + name ─────────────────
        m = re.match(rf'^{_AMT_PAT}\s+(.+)$', text, re.IGNORECASE)
        if m:
            amount_str = m.group(1).strip()
            rest = m.group(2).strip()
            unit_m = re.match(rf'^({_IT_UNIT_PATTERN})\s*', rest, re.IGNORECASE)
            if unit_m:
                unit = unit_m.group(1).lower()
                name = rest[unit_m.end():].strip()
                name = _IT_PREP_RE.sub('', name).strip().rstrip(',;:.')
            else:
                unit = None
                name = rest.rstrip(',;:.')
            name = self.clean_text(name)
            if name:
                return {"name": name.lower(), "amount": amount_str, "unit": unit}

        # ── Case 3: no amount — just ingredient name ─────────────────────────
        name = self.clean_text(text).rstrip(',;:.')
        if name and len(name) > 1:
            return {"name": name.lower(), "amount": None, "unit": None}
        return None

    def _parse_li_ingredients(self, li_text: str) -> list:
        """
        Parse a list-item that may contain multiple ingredients.

        E.g. "Verdure: pomodorini, zucchine grigliate, peperoni"
        →  [{"name":"pomodorini",...}, {"name":"zucchine grigliate",...}, ...]

        For category-style items like "Pasta: meglio se corta e robusta, come fusilli..."
        the method tries to extract the "come X, Y" part as examples, or returns just
        the category name as the ingredient.
        """
        if not li_text:
            return []

        items = []
        if ':' in li_text:
            category, rest = li_text.split(':', 1)
            category = category.strip()

            # Trim long explanatory tails after the first full stop
            if '.' in rest and len(rest) > 60:
                rest = rest.split('.')[0]

            # Protect commas inside parentheses from splitting
            def _protect_parens(s: str) -> str:
                result = []
                depth = 0
                for ch in s:
                    if ch == '(':
                        depth += 1
                    elif ch == ')':
                        depth = max(0, depth - 1)
                    if ch == ',' and depth > 0:
                        result.append('\x00')  # placeholder
                    else:
                        result.append(ch)
                return ''.join(result)

            # Check if the rest starts with descriptive text (not a food list)
            if _DESC_WORDS_RE.match(rest.strip()):
                # Try to find a "come X, Y, Z" sublist
                come_m = re.search(r'\bcome\s+(.+)$', rest, re.IGNORECASE)
                if come_m:
                    rest = come_m.group(1)
                else:
                    # Use the category name as the sole ingredient
                    p = self._parse_ingredient_it(category)
                    if p:
                        items.append(p)
                    return items

            # Split on ", " connectors only (protect commas in parens)
            protected = _protect_parens(rest)
            parts = re.split(r',\s*', protected)
            for part in parts:
                # Restore placeholder commas
                part = part.replace('\x00', ',')
                # Treat as single item (do NOT split on " o " — often indicates
                # variant forms of the same ingredient, e.g. "olive nere o verdi")
                part = part.strip().rstrip('.')
                if len(part) > 2 and not _DESC_WORDS_RE.match(part):
                    p = self._parse_ingredient_it(part)
                    if p:
                        items.append(p)
        else:
            p = self._parse_ingredient_it(li_text.rstrip('.'))
            if p:
                items.append(p)
        return items

    def _extract_amounts_from_prose(self, text: str) -> list:
        """
        Extract ingredients with explicit amounts from prose text.

        Handles patterns like:
        - "circa 100 grammi di mozzarella"
        - "un cucchiaino d'olio extravergine"
        - "un paio di pomodori"
        """
        results = []
        if not text:
            return results

        _PROSE_AMT = r'(?:circa\s+)?(\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?)'
        _NAME_PROSE = (
            r'([A-Za-z\u00c0-\u00ff][A-Za-z\u00c0-\u00ff\s\'\u2019()-]+?)'
            r'(?=[,;.]|$|\s+e\s+|\s+o\s+|\s+per\s+|\s+a\s+)'
        )

        # Non-ingredient words to skip in prose results
        _NON_INGRED = {'ingredienti', 'ingrediente', 'calorie', 'proteine', 'grassi',
                       'carboidrati', 'nutrienti', 'porzione', 'porzioni', 'fibra', 'fibre'}

        # Pattern 1: "N unit [prep] name"
        for m in re.finditer(
            rf'{_PROSE_AMT}\s+({_IT_UNIT_PATTERN})\s+{_IT_PREP_OPT}{_NAME_PROSE}',
            text,
            re.IGNORECASE,
        ):
            amount_str = m.group(1)
            unit = m.group(2).lower()
            name = m.group(3).strip().rstrip(',;:.')
            name = _IT_PREP_RE.sub('', name).strip()
            name = self.clean_text(name)
            if name and len(name) > 1 and name.lower() not in _NON_INGRED:
                results.append({"name": name.lower(), "amount": amount_str, "unit": unit})

        # Pattern 2: "un paio / qualche / un filo [di] name"
        for m in re.finditer(
            r'(un\s+paio|qualche|un\s+filo(?:\s+generoso)?)\s+'
            r"(?:di\s+|d['\u2019]\s*)?"
            r'([A-Za-z\u00c0-\u00ff][A-Za-z\u00c0-\u00ff\s\'\u2019-]+?)'
            r'(?=[,;.]|$|\s+e\s+)',
            text,
            re.IGNORECASE,
        ):
            amount_phrase = m.group(1).strip()
            name = m.group(2).strip().rstrip(',;:.')
            name = _IT_PREP_RE.sub('', name).strip()
            name = self.clean_text(name)
            if name and len(name) > 2 and name.lower() not in _NON_INGRED:
                results.append({"name": name.lower(), "amount": amount_phrase, "unit": None})

        return results

    # ─────────────────────────────── public extract methods ───────────────────────

    def extract_dish_name(self) -> Optional[str]:
        """Extract dish name from H1 (strips subtitle after ':')."""
        h1 = self.soup.find('h1')
        if h1:
            name = h1.get_text(strip=True)
            # Strip subtitle after ':'
            name = re.sub(r'\s*:\s*.+$', '', name)
            name = self.clean_text(name)
            if name:
                return name

        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(
                r"\s*[-|]\s*Men'?s\s*Health.*$", '', title, flags=re.IGNORECASE
            )
            return self.clean_text(title) or None
        return None

    def extract_description(self) -> Optional[str]:
        """Extract description from meta og:description or meta description."""
        for prop, name in [('og:description', None), (None, 'description')]:
            attrs = {'property': prop} if prop else {'name': name}
            tag = self.soup.find('meta', attrs)
            if tag and tag.get('content'):
                return self.clean_text(tag['content'])
        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Extract ingredient list.

        Strategy:
            1. Structured recipe card (H2 "INGREDIENTI:") — direct <p> extraction.
            2. Article with <ul> list under an "ingredienti" H2.
            3. Article with prose — extract from "Ingredienti principali"
               and "Valori nutrizionali" / "porzioni" sections.
        """
        main = self._get_main()
        if not main:
            return None

        all_h2 = main.find_all('h2')

        # ── Strategy 1: Structured recipe card ────────────────────────────────
        for h2 in all_h2:
            h2_text = h2.get_text(strip=True)
            if re.match(r'^INGREDIENTI\s*:', h2_text, re.IGNORECASE):
                ingredients = []
                for el in self._section_elements(h2):
                    if el.name == 'p':
                        text = self.clean_text(el.get_text(separator=' ', strip=True))
                        if text:
                            parsed = self._parse_ingredient_it(text)
                            if parsed:
                                ingredients.append(parsed)
                if ingredients:
                    logger.debug("menshealth: used structured INGREDIENTI section")
                    return json.dumps(ingredients, ensure_ascii=False)

        # ── Strategy 2: Article-based with <ul> ───────────────────────────────
        for h2 in all_h2:
            h2_text = h2.get_text(strip=True)
            if self._is_stop_section(h2_text):
                continue
            if 'ingredienti' not in h2_text.lower():
                continue
            ingredients = []
            for el in self._section_elements(h2):
                if el.name == 'ul':
                    for li in el.find_all('li', recursive=False):
                        li_text = self.clean_text(
                            li.get_text(separator=' ', strip=True)
                        )
                        if li_text:
                            items = self._parse_li_ingredients(li_text)
                            ingredients.extend(items)
            if ingredients:
                logger.debug("menshealth: used article UL ingredienti section")
                return json.dumps(ingredients, ensure_ascii=False)

        # ── Strategy 3: Prose extraction ──────────────────────────────────────
        ingred_items: list = []
        amount_items: list = []

        for h2 in all_h2:
            h2_text = h2.get_text(strip=True)
            if self._is_stop_section(h2_text):
                continue
            h2_low = h2_text.lower()

            if 'ingredienti' in h2_low:
                # Extract comma-list nouns from "X, Y e Z sono tra gli ortaggi..." pattern
                for el in self._section_elements(h2):
                    if el.name == 'p':
                        p_text = el.get_text(separator=' ', strip=True)
                        m = re.match(
                            r'^([A-Z\u00c0-\u00df][a-zA-Z\u00c0-\u00ff\s,]+?\s+e\s+'
                            r'[a-zA-Z\u00c0-\u00ff\s]+?)\s+(?:sono|è)\b',
                            p_text,
                        )
                        if m:
                            parts = re.split(r',\s*|\s+e\s+', m.group(1))
                            for part in parts:
                                part = part.strip()
                                if part and len(part) > 2:
                                    ingred_items.append(
                                        {"name": part.lower(), "amount": None, "unit": None}
                                    )

            if 'valori nutrizionali' in h2_low or 'porzioni' in h2_low:
                for el in self._section_elements(h2):
                    if el.name == 'p':
                        p_text = el.get_text(separator=' ', strip=True)
                        found = self._extract_amounts_from_prose(p_text)
                        amount_items.extend(found)

        combined = amount_items + ingred_items
        if combined:
            seen: set = set()
            unique = []
            for item in combined:
                n = item['name']
                if n not in seen:
                    seen.add(n)
                    unique.append(item)
            logger.debug("menshealth: used prose ingredient extraction")
            return json.dumps(unique, ensure_ascii=False)

        return None

    def extract_steps(self) -> Optional[str]:
        """
        Extract cooking instructions.

        Strategy:
            1. Structured card with H2 "PREPARAZIONE" — collect <p>s, skip "Fase N" labels.
            2. Article with H2 matching "la ricetta" / "Procedimento".
        """
        main = self._get_main()
        if not main:
            return None

        all_h2 = main.find_all('h2')

        # ── Strategy 1: Structured ────────────────────────────────────────────
        for h2 in all_h2:
            if re.match(r'^PREPARAZIONE', h2.get_text(strip=True), re.IGNORECASE):
                steps = []
                for el in self._section_elements(h2):
                    if el.name == 'p':
                        text = self.clean_text(el.get_text(separator=' ', strip=True))
                        if not text or self._is_footer_para(text):
                            continue
                        # Skip "Fase N" step-header labels
                        if re.match(r'^[Ff]ase\s+\d+$', text):
                            continue
                        steps.append(text)
                if steps:
                    return ' '.join(steps)

        # ── Strategy 2: Article-based ─────────────────────────────────────────
        for h2 in all_h2:
            h2_text = h2.get_text(strip=True)
            if self._is_stop_section(h2_text):
                continue
            if re.search(
                r'(procedimento|la\s+ricetta\b|\bricetta\b)', h2_text, re.IGNORECASE
            ):
                steps = []
                step_n = 1
                for el in self._section_elements(h2):
                    if el.name == 'p':
                        text = self.clean_text(el.get_text(separator=' ', strip=True))
                        if not text or self._is_footer_para(text) or len(text) < 15:
                            continue
                        steps.append(f'{step_n}. {text}')
                        step_n += 1
                    elif el.name == 'ol':
                        for li in el.find_all('li'):
                            text = self.clean_text(
                                li.get_text(separator=' ', strip=True)
                            )
                            if text:
                                steps.append(f'{step_n}. {text}')
                                step_n += 1
                if steps:
                    return ' '.join(steps)

        return None

    def extract_category(self) -> Optional[str]:
        """Extract recipe category from article:section meta or JSON-LD."""
        meta = self.soup.find('meta', property='article:section')
        if meta and meta.get('content'):
            return self.clean_text(meta['content'])
        ld = self._get_news_ld()
        if ld:
            for key in ('articleSection', 'recipeCategory'):
                val = ld.get(key)
                if val:
                    return self.clean_text(
                        str(val) if not isinstance(val, str) else val
                    )
        return None

    def _parse_it_time(self, raw: str) -> Optional[str]:
        """Convert Italian time string (e.g. "5 minuti") to "N minutes"."""
        if not raw:
            return None
        raw = raw.strip()
        hrs = 0
        mins = 0
        h_m = re.search(r'(\d+)\s*(?:ora|ore|h\.?)\b', raw, re.IGNORECASE)
        m_m = re.search(r'(\d+)\s*(?:minuto|minuti|min\.?)\b', raw, re.IGNORECASE)
        if h_m:
            hrs = int(h_m.group(1))
        if m_m:
            mins = int(m_m.group(1))
        total = hrs * 60 + mins
        return f'{total} minutes' if total else raw

    def _extract_structured_time(self, heading_pattern: str) -> Optional[str]:
        """Find H2 matching *heading_pattern* and return parsed time from next <p>."""
        main = self._get_main()
        if not main:
            return None
        for h2 in main.find_all('h2'):
            if re.search(heading_pattern, h2.get_text(strip=True), re.IGNORECASE):
                for el in self._section_elements(h2):
                    if el.name == 'p':
                        text = el.get_text(strip=True)
                        if text:
                            return self._parse_it_time(text)
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Extract preparation time from "TEMPO DI PREPARAZIONE" H2."""
        return self._extract_structured_time(r'TEMPO\s+DI\s+PREPARAZIONE')

    def extract_cook_time(self) -> Optional[str]:
        """Extract cooking time from "TEMPO DI COTTURA" H2."""
        return self._extract_structured_time(r'TEMPO\s+DI\s+COTTURA')

    def extract_total_time(self) -> Optional[str]:
        """Extract total time from "TEMPO TOTALE" H2."""
        return self._extract_structured_time(r'TEMPO\s+TOTALE')

    def extract_notes(self) -> Optional[str]:
        """
        Extract notes / tips.

        Looks for:
        1. Explicit NOTE / CONSIGLI / SUGGERIMENTI H2 sections.
        2. Sentences containing tip keywords (puoi, varianti, si consiglia…)
           inside the recipe / preparation section.
        """
        main = self._get_main()
        if not main:
            return None

        all_h2 = main.find_all('h2')

        # Explicit notes sections
        for h2 in all_h2:
            h2_low = h2.get_text(strip=True).lower()
            if any(kw in h2_low for kw in ('note', 'consigli', 'suggerimenti', 'tips')):
                parts = []
                for el in self._section_elements(h2):
                    if el.name == 'p':
                        t = self.clean_text(el.get_text(separator=' ', strip=True))
                        if t and not self._is_footer_para(t):
                            parts.append(t)
                if parts:
                    return ' '.join(parts)

        # Extract tip sentences from recipe / preparation sections
        for h2 in all_h2:
            h2_text = h2.get_text(strip=True)
            if self._is_stop_section(h2_text):
                continue
            if not re.search(
                r'(procedimento|la\s+ricetta\b|\bricetta\b|PREPARAZIONE)',
                h2_text,
                re.IGNORECASE,
            ):
                continue
            tips = []
            for el in self._section_elements(h2):
                if el.name == 'p':
                    t = self.clean_text(el.get_text(separator=' ', strip=True))
                    if not t or self._is_footer_para(t):
                        continue
                    for sent in re.split(r'(?<=[.!?])\s+', t):
                        sent = sent.strip()
                        if len(sent) > 20 and re.search(
                            r'\b(puoi|si consiglia|è consigliato|varianti?|'
                            r'alternativa|in alternativa|opzionali?|si pu[o\u00f2])\b',
                            sent,
                            re.IGNORECASE,
                        ):
                            tips.append(sent)
            if tips:
                return ' '.join(tips)

        return None

    def extract_tags(self) -> Optional[str]:
        """Extract tags from meta keywords, filtering 'seo' and short tokens."""
        kw = self.soup.find('meta', {'name': 'keywords'})
        if kw and kw.get('content'):
            tags = [t.strip().lower() for t in kw['content'].split(',') if t.strip()]
            filtered = [t for t in tags if len(t) > 2 and t not in ('seo',)]
            seen: set = set()
            unique = [t for t in filtered if not (t in seen or seen.add(t))]  # type: ignore[func-returns-value]
            return ', '.join(unique) if unique else None
        return None

    def extract_image_urls(self) -> Optional[str]:
        """Extract up to 3 image URLs: og:image first, then JSON-LD images."""
        urls: list = []

        og = self.soup.find('meta', property='og:image')
        if og and og.get('content'):
            urls.append(og['content'])

        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
                for item in (data if isinstance(data, list) else [data]):
                    if not isinstance(item, dict):
                        continue
                    for url in self._iter_image_urls(item.get('image', [])):
                        if url and url not in urls:
                            urls.append(url)
            except (json.JSONDecodeError, TypeError):
                pass

        seen: set = set()
        unique = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)
                if len(unique) >= 3:
                    break
        return ','.join(unique) if unique else None

    @staticmethod
    def _iter_image_urls(images):
        """Yield URL strings from various JSON-LD image representations."""
        if isinstance(images, str):
            yield images
        elif isinstance(images, dict):
            yield images.get('url') or images.get('contentUrl')
        elif isinstance(images, list):
            for img in images:
                if isinstance(img, str):
                    yield img
                elif isinstance(img, dict):
                    yield img.get('url') or img.get('contentUrl')

    def extract_all(self) -> dict:
        """Return full recipe data dict extracted from the HTML page."""
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()

        return {
            "dish_name": dish_name.lower() if dish_name else None,
            "description": description.lower() if description else None,
            "ingredients": ingredients,
            "instructions": instructions.lower() if instructions else None,
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes.lower() if notes else None,
            "tags": tags,
            "image_urls": self.extract_image_urls(),
        }


def main():
    preprocessed_dir = str(
        Path(__file__).parent.parent / 'preprocessed' / 'menshealth_com'
    )
    if Path(preprocessed_dir).exists():
        process_directory(MenshealthComExtractor, preprocessed_dir)
        return
    print(f"Директория не найдена: {preprocessed_dir}")


if __name__ == "__main__":
    main()
