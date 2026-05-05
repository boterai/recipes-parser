"""
Экстрактор данных рецептов для сайта eten-en-drinken.infonu.nl
"""

import logging
import re
import sys
import json
from pathlib import Path
from typing import Optional, List, Dict, Any

from bs4 import BeautifulSoup as _BS, NavigableString

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Compiled pattern for detecting kitchen-equipment strings
_EQUIPMENT_RE = re.compile(
    r'kom\b'           # mengkom, kneedkom, glazen kom
    r'|pan\b'          # koekenpan, bakpan, grillpan, standalone pan
    r'|\bkookpot\b'
    r'|\bwok\b'
    r'|\btheedoek\b'
    r'|\bbakpapier\b'
    r'|\bzeef\b'
    r'|\bweegschaal\b'
    r'|\bblender\b'
    r'|\bmixer\b'
    r'|\bspringvorm\b'
    r'|\btaartvorm\b'
    r'|\bbakplaat\b'
    r'|\bspatel\b'
    r'|\bthermometer\b'
    r'|\bdoorsnede\b'
    r'|cm\s*[ØΩ°]'    # dimensions like "22 cm Ø"
    r'|\bkeukentouw\b'
    r'|\bprikker\b',
    re.IGNORECASE,
)


class EtenEnDrinkenInfonuNlExtractor(BaseRecipeExtractor):
    """Экстрактор для eten-en-drinken.infonu.nl"""

    # Recognised Dutch measurement units (longest first for greedy matching)
    _DUTCH_UNITS: List[str] = [
        'kilogram', 'deciliter', 'centiliter', 'milliliter',
        'eetlepel', 'theelepel', 'handvol', 'scheut',
        'koppen', 'kopje', 'bosje', 'pakje', 'plakje', 'takje', 'snufje', 'zakje',
        'stuks', 'stuk',
        'kilo', 'gram', 'liter',
        'teen',
        'pak', 'kop',
        'snuf', 'plak',
        'dl', 'cl', 'ml', 'kg', 'gr', 'el', 'tl',
        'l', 'g',
    ]

    # Volume (non-metric) units used in the metric-preference heuristic
    _VOLUME_UNITS: List[str] = [
        'koppen', 'kopje', 'kop',
        'eetlepel', 'el',
        'theelepel', 'tl',
        'pakje', 'pak',
        'stuk', 'stuks',
        'teen', 'bosje', 'plakje', 'plak', 'takje', 'scheut', 'snufje', 'snuf',
    ]

    # H2 / strong header keywords that mark an INGREDIENT section
    _INGREDIENT_KEYWORDS: List[str] = [
        'ingrediënten', 'ingredienten', 'ingredient',
        'benodigdheden', 'benodigd',
        'nodig hebt', 'wat je nodig',
    ]

    # H2 header keywords that mark an EQUIPMENT/TOOLS section (skip for ingredients)
    _EQUIPMENT_SECTION_KEYWORDS: List[str] = [
        'materiaallijst', 'materiaal', 'gereedschap',
    ]

    # H2 / strong header keywords that mark an INSTRUCTION section
    _INSTRUCTION_KEYWORDS: List[str] = [
        'bereiding', 'bereidingswijze', 'aan de slag',
        'werkwijze', 'instructies',
    ]

    # H2 header keywords that mark a NOTES / TIPS section
    _NOTES_KEYWORDS: List[str] = [
        'extraatje', 'extra tipsje', 'tipsje', 'aanvulling',
        'opmerking', 'notitie', 'handig om te weten',
    ]

    # ---------------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------------

    def _get_article(self):
        """Return the main <article> element, or None."""
        return self.soup.find('article')

    @staticmethod
    def _normalize_fractions(text: str) -> str:
        """Replace common Unicode fraction chars (incl. combined) with decimals."""
        combined = {
            '1¾': '1.75', '1½': '1.5', '1¼': '1.25',
            '2½': '2.5',  '2¼': '2.25', '2¾': '2.75',
            '3½': '3.5',
        }
        simple = {
            '¾': '0.75', '½': '0.5', '¼': '0.25',
            '⅓': '0.33', '⅔': '0.67',
            '⅛': '0.125', '⅜': '0.375',
            '⅝': '0.625', '⅞': '0.875',
        }
        for frac, dec in {**combined, **simple}.items():
            text = text.replace(frac, dec)
        return text

    def _is_ingredient_header(self, text: str) -> bool:
        t = text.lower()
        if any(k in t for k in self._EQUIPMENT_SECTION_KEYWORDS):
            return False
        return any(k in t for k in self._INGREDIENT_KEYWORDS)

    def _is_equipment_header(self, text: str) -> bool:
        t = text.lower()
        return any(k in t for k in self._EQUIPMENT_SECTION_KEYWORDS)

    def _is_instruction_marker(self, text: str) -> bool:
        t = text.lower()
        return any(k in t for k in self._INSTRUCTION_KEYWORDS)

    def _is_notes_header(self, text: str) -> bool:
        t = text.lower()
        return any(k in t for k in self._NOTES_KEYWORDS)

    def _collect_ul_items(
        self,
        start_tag,
        stop_at_instructions: bool = False,
    ) -> List[str]:
        """
        Walk forward siblings from *start_tag* and collect text from <li> elements
        inside <ul> tags until the next <h2> (or, optionally, the next instruction
        marker such as <strong>Bereiding</strong>).

        TOC lists (every <li> contains only an <a>) are silently skipped.
        """
        items: List[str] = []
        node = start_tag.find_next_sibling()
        while node is not None:
            if node.name == 'h2':
                break
            if stop_at_instructions and node.name in ('strong', 'h3', 'h4'):
                if self._is_instruction_marker(self.clean_text(node.get_text())):
                    break
            if node.name == 'ul':
                li_tags = node.find_all('li', recursive=False)
                # Skip pure-TOC lists (every li is just a link)
                is_toc = all(
                    li.find('a') is not None
                    and self.clean_text(li.get_text()) ==
                        self.clean_text(li.find('a').get_text())
                    for li in li_tags
                ) if li_tags else False
                if not is_toc:
                    for li in li_tags:
                        text = self.clean_text(li.get_text())
                        if text:
                            items.append(text)
            node = node.find_next_sibling()
        return items

    # ---------------------------------------------------------------------------
    # Dutch ingredient parser
    # ---------------------------------------------------------------------------

    def _expand_if_alternative(self, raw_text: str) -> Optional[List[Dict[str, Any]]]:
        """
        Detect lines of the form "N unit ADJ of N unit [ADJ] NOUN" where both
        units belong to the *same* class (both metric or both the same unit),
        and return two separate ingredient dicts.

        Example: "15 gram droge of 30 gram verse gist"
          → [{"name":"droge gist","amount":"15","unit":"gram"},
             {"name":"verse gist","amount":"30","unit":"gram"}]

        When the first unit is a volume unit and the second is a metric unit
        (e.g. "3 koppen of 430 gr bloem"), this method returns None so that the
        normal metric-preference path in _parse_dutch_ingredient is used instead.
        """
        text = self.clean_text(raw_text)
        if not text:
            return None
        text = re.sub(
            r'^(eventueel|optioneel|circa|ca\.?|±)\s+',
            '', text, flags=re.IGNORECASE,
        )
        text = self._normalize_fractions(text)

        units_sorted = sorted(self._DUTCH_UNITS, key=len, reverse=True)
        units_re = '|'.join(re.escape(u) for u in units_sorted)
        metric_units = {
            'gram', 'gr', 'g', 'kg', 'kilogram',
            'ml', 'milliliter', 'dl', 'deciliter', 'liter', 'l',
        }

        # Pattern: "N unit ADJ of N unit REST"
        # (\w+) as adj1 must be present (non-empty adjective between unit and "of")
        m = re.match(
            rf'^([\d.]+)\s+({units_re})\s+(\w+)\s+of\s+([\d.]+)\s+({units_re})\s+(.+)$',
            text, re.IGNORECASE,
        )
        if not m:
            return None

        a1, u1, adj1, a2, u2, rest = m.groups()

        # Only split when both sides use the same unit class
        is_metric_1 = u1.lower() in metric_units
        is_metric_2 = u2.lower() in metric_units
        if is_metric_1 != is_metric_2:
            # Mixed classes → let metric-preference logic handle it
            return None

        # Extract shared noun: the last word of `rest`
        rest_parts = rest.strip().split()
        noun = rest_parts[-1]
        adj2 = ' '.join(rest_parts[:-1]) if len(rest_parts) > 1 else ''

        name1 = self._clean_ingredient_name(f"{adj1} {noun}".strip())
        name2 = self._clean_ingredient_name(
            f"{adj2} {noun}".strip() if adj2 else noun
        )
        if not name1 or not name2:
            return None

        return [
            {'name': name1, 'amount': a1, 'unit': u1},
            {'name': name2, 'amount': a2, 'unit': u2},
        ]

    def _parse_dutch_ingredient(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """
        Parse a single Dutch ingredient string into ``{name, amount, unit}``.

        Returns *None* for empty input or strings that look like kitchen equipment.
        """
        if not raw_text:
            return None
        text = self.clean_text(raw_text)
        if not text or len(text) < 2:
            return None

        # Early-exit for obvious equipment
        if _EQUIPMENT_RE.search(text):
            return None

        # Strip leading optional/approximate modifiers
        text = re.sub(
            r'^(eventueel|optioneel|circa|ca\.?|±)\s+',
            '', text, flags=re.IGNORECASE,
        )

        # When two alternatives are given with "of" and the FIRST uses a
        # non-metric (volume) unit while the SECOND uses a metric unit,
        # prefer the metric variant.
        # E.g. "3 koppen of 430 gr bloem" → "430 gr bloem"
        # N.B. we do NOT apply this when both sides use the same unit class
        # (e.g. "15 gram droge of 30 gram verse gist") — those are kept as-is
        # so that the name-cleaning step can extract the correct shared noun.
        vol_units_re = '|'.join(re.escape(u) for u in sorted(self._VOLUME_UNITS, key=len, reverse=True))
        non_metric_first_re = rf'^[\d½¼¾⅓⅔⅛\s.]+\s*({vol_units_re})\b'
        metric_second_re = (
            r'^.+?\s+of\s+'
            r'([\d½¼¾⅓⅔⅛\s.]+\s*'
            r'(?:gram|gr|g|kg|kilogram|ml|milliliter|dl|deciliter|liter)\s+.+)$'
        )
        if re.match(non_metric_first_re, text, re.IGNORECASE):
            m_metric = re.match(metric_second_re, text, re.IGNORECASE)
            if m_metric:
                text = m_metric.group(1).strip()

        # Normalize Unicode fractions → decimals
        text = self._normalize_fractions(text)

        # Build a units alternation (longest first to avoid partial matches)
        units_sorted = sorted(self._DUTCH_UNITS, key=len, reverse=True)
        units_re = '|'.join(re.escape(u) for u in units_sorted)

        # ── Pattern 1: amount  unit  name ───────────────────────────────────
        m = re.match(
            rf'^([\d.]+(?:\s+tot\s+[\d.]+)?)\s+({units_re})\.?\s+(.+)$',
            text, re.IGNORECASE,
        )
        if m:
            amount = m.group(1).strip()
            unit   = m.group(2).strip()
            name   = m.group(3).strip()
            name   = self._clean_ingredient_name(name)
            if name:
                return {'name': name, 'amount': amount, 'unit': unit}

        # ── Pattern 2: amount  name  (no recognised unit) ───────────────────
        m2 = re.match(r'^([\d.]+)\s+(.+)$', text)
        if m2:
            amount = m2.group(1).strip()
            name   = self._clean_ingredient_name(m2.group(2).strip())
            if name:
                return {'name': name, 'amount': amount, 'unit': None}

        # ── Pattern 3: "een handvol …" / "een scheutje …" ───────────────────
        m3 = re.match(r'^(een\s+\w+)\s+(.+)$', text, re.IGNORECASE)
        if m3:
            name = self._clean_ingredient_name(m3.group(2).strip())
            if name:
                return {'name': name, 'amount': m3.group(1).strip(), 'unit': None}

        # ── Fallback: treat the whole string as the ingredient name ──────────
        name = self._clean_ingredient_name(text)
        if name and not _EQUIPMENT_RE.search(name):
            return {'name': name, 'amount': None, 'unit': None}

        return None

    @staticmethod
    def _clean_ingredient_name(name: str) -> str:
        """
        Apply several clean-up passes to an ingredient name string:
        - Remove purpose clauses: "om te …", "om de … te …", "voor …"
        - Remove second measurement alternative: "droge of 30 gram verse gist"
          → keep first adjective + last shared noun
        - Strip trailing commas/semicolons
        """
        if not name:
            return name

        # Remove purpose clauses: ", om de bolletjes te bestrijken"
        name = re.sub(r',\s*om\b.+', '', name, flags=re.IGNORECASE)
        # Remove " om de ... te ..." inline
        name = re.sub(r'\s+om\b.+', '', name, flags=re.IGNORECASE)
        # Remove " voor ..." descriptions
        name = re.sub(r'\s+voor\b.+', '', name, flags=re.IGNORECASE)
        # Remove " naar smaak"
        name = re.sub(r'\s+naar\s+smaak\b.*', '', name, flags=re.IGNORECASE)

        # "adjective of NUMBER unit adjective noun" → "adjective noun"
        # e.g. "droge of 30 gram verse gist" → "droge gist"
        m_of = re.match(
            r'^(\S+(?:\s+\S+)*?)\s+of\s+[\d.]+\s+\w+\s+(\S+(?:\s+\S+)*\s+)?(\S+)$',
            name, re.IGNORECASE,
        )
        if m_of:
            first_part = m_of.group(1).strip()
            last_word  = m_of.group(3).strip()
            name = f"{first_part} {last_word}"

        # Normalise whitespace around slash (e.g. "en/ of" → "en/of")
        name = re.sub(r'\s*/\s*', '/', name)

        # Strip trailing punctuation and whitespace
        name = re.sub(r'[,;]+$', '', name).strip()
        return name

    # ---------------------------------------------------------------------------
    # Public extraction methods
    # ---------------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из тега <h1> внутри <article>."""
        try:
            article = self._get_article()
            if article:
                h1 = article.find('h1')
                if h1:
                    title = h1.get('title') or h1.get_text()
                    return self.clean_text(title) or None
        except Exception as e:
            logger.warning(f"Error extracting dish_name: {e}")
        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение краткого описания из <b class='inl'>."""
        try:
            article = self._get_article()
            if article:
                intro = article.find('b', class_='inl')
                if intro:
                    return self.clean_text(intro.get_text()) or None
        except Exception as e:
            logger.warning(f"Error extracting description: {e}")
        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов.

        Ищет h2 и <strong> с ключевыми словами ингредиентов, затем собирает
        элементы из следующих <ul>.
        """
        try:
            article = self._get_article()
            if not article:
                return None

            ingredients: List[Dict[str, Any]] = []

            def _add(raw: str) -> None:
                # First try to expand "N unit ADJ of N unit ADJ NOUN" pairs
                expanded = self._expand_if_alternative(raw)
                if expanded:
                    for item in expanded:
                        if item and item.get('name'):
                            ingredients.append(item)
                    return
                parsed = self._parse_dutch_ingredient(raw)
                if parsed and parsed.get('name'):
                    ingredients.append(parsed)

            # 1. h2 headers with ingredient keywords
            for h2 in article.find_all('h2'):
                h2_text = self.clean_text(h2.get_text())
                if not self._is_ingredient_header(h2_text):
                    continue
                for raw in self._collect_ul_items(h2, stop_at_instructions=True):
                    _add(raw)

            # 2. <strong> tags with ingredient keywords
            #    (e.g. <strong>Benodigdheden</strong> on the injera page)
            for strong in article.find_all('strong'):
                strong_text = self.clean_text(strong.get_text())
                if not self._is_ingredient_header(strong_text):
                    continue
                for raw in self._collect_ul_items(strong, stop_at_instructions=True):
                    _add(raw)

            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

        except Exception as e:
            logger.warning(f"Error extracting ingredients: {e}")
            return None

    # ── Instructions ────────────────────────────────────────────────────────

    @staticmethod
    def _join_steps(steps: List[str]) -> str:
        """
        Join instruction steps into a single string.

        If a step does not end with sentence-ending punctuation (`.`, `!`, `?`)
        a `. ` is inserted before the next step; otherwise a plain space is used.
        """
        if not steps:
            return ''
        parts = [steps[0]]
        for step in steps[1:]:
            separator = ' ' if parts[-1][-1] in '.!?' else '. '
            parts.append(separator)
            parts.append(step)
        return ''.join(parts)

    def _extract_olist_steps(self) -> List[str]:
        """
        Extract instruction steps from the custom [OLIST]…[/OLIST] markup
        used on some infonu.nl pages.  Steps are separated by <br> tags.
        """
        try:
            article = self._get_article()
            if not article:
                return []
            article_html = str(article)
            m = re.search(
                r'\[OLIST\](.*?)\[/OLIST\]',
                article_html,
                re.DOTALL | re.IGNORECASE,
            )
            if not m:
                return []
            raw_steps = re.split(r'<br\s*/?>', m.group(1), flags=re.IGNORECASE)
            steps = []
            for raw in raw_steps:
                text = self.clean_text(_BS(raw, 'lxml').get_text())
                if text:
                    steps.append(text)
            return steps
        except Exception as e:
            logger.warning(f"Error extracting [OLIST] steps: {e}")
            return []

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления."""
        try:
            article = self._get_article()
            if not article:
                return None

            steps: List[str] = []

            # 1. [OLIST] custom markup (bolletjes-style pages)
            steps.extend(self._extract_olist_steps())

            # 2. ul/li after instruction markers (h2 or strong)
            for tag in article.find_all(['h2', 'strong']):
                tag_text = self.clean_text(tag.get_text())
                if not self._is_instruction_marker(tag_text):
                    continue
                for raw in self._collect_ul_items(tag, stop_at_instructions=False):
                    text = self.clean_text(raw)
                    if text and text not in steps:
                        steps.append(text)

            return self._join_steps(steps) if steps else None

        except Exception as e:
            logger.warning(f"Error extracting steps: {e}")
            return None

    # ── Category ─────────────────────────────────────────────────────────────

    def extract_category(self) -> Optional[str]:
        """
        Извлечение категории из блока <aside>.
        Предпочитается «Subrubriek», иначе берётся «Rubriek».
        """
        try:
            aside = self.soup.find('aside')
            if not aside:
                return None
            info_div = aside.find('div', id='ainfo')
            if not info_div:
                return None

            # Walk <b> labels inside the info div
            for b_tag in info_div.find_all('b'):
                label = b_tag.get_text(strip=True).lower()
                if 'subrubriek' in label:
                    a = b_tag.find_next_sibling('a') or b_tag.find_next('a')
                    if a:
                        return self.clean_text(a.get_text()) or None

            # Fallback: Rubriek
            for b_tag in info_div.find_all('b'):
                label = b_tag.get_text(strip=True).lower()
                if 'rubriek' in label:
                    a = b_tag.find_next_sibling('a') or b_tag.find_next('a')
                    if a:
                        return self.clean_text(a.get_text()) or None

        except Exception as e:
            logger.warning(f"Error extracting category: {e}")
        return None

    # ── Time helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _translate_dutch_time(amount: str, unit: str) -> str:
        """Convert a Dutch time expression to English, with proper pluralisation."""
        singular = {
            'minuut': 'minute', 'minuten': 'minute',
            'uur': 'hour',      'uren': 'hour',
            'dag': 'day',       'dagen': 'day',
        }
        plural = {
            'minuut': 'minutes', 'minuten': 'minutes',
            'uur': 'hours',      'uren': 'hours',
            'dag': 'days',       'dagen': 'days',
        }
        en_amount = amount.replace(' tot ', ' to ')
        # Determine plurality from the numeric part
        try:
            num = float(en_amount.split()[0].replace(',', '.'))
            is_plural = num != 1.0
        except (ValueError, IndexError):
            is_plural = True  # ranges like "10 to 15" are always plural
        en_unit = (plural if is_plural else singular).get(unit.lower(), unit)
        return f"{en_amount} {en_unit}"

    def _article_text(self) -> str:
        """Return the clean text of the <article> element."""
        article = self._get_article()
        return article.get_text(separator=' ') if article else ''

    def extract_prep_time(self) -> Optional[str]:
        """
        Извлечение времени подготовки.

        Приоритет: выражения с «dag(en)» (брожение/ферментация),
        затем — часы рядом со словами «стоять/подходить».
        """
        try:
            text = self._article_text()

            # Days (fermentation / long rest) — highest priority for prep
            # Put longer alternative first to avoid "dag" matching inside "dagen"
            m_days = re.search(r'([\d]+)\s+(dagen|dag)\b', text, re.IGNORECASE)
            if m_days:
                return self._translate_dutch_time(m_days.group(1), m_days.group(2))

            # Hours associated with rising / resting
            m_hours = re.search(
                r'([\d]+(?:[.,][\d]+)?)\s+(uren|uur)\b'
                r'(?:\s+\w+){0,4}\s*(?:op\s+kamertemperatuur|staan|rusten|rijzen)',
                text, re.IGNORECASE,
            )
            if m_hours:
                return self._translate_dutch_time(m_hours.group(1), m_hours.group(2))

        except Exception as e:
            logger.warning(f"Error extracting prep_time: {e}")
        return None

    def extract_cook_time(self) -> Optional[str]:
        """
        Извлечение времени приготовления.

        Сначала ищем «X minuten bakken/koken/…», затем «X tot Y minuten».
        """
        try:
            text = self._article_text()

            # "X minuten bakken" / "X tot Y minuten bakken"
            m_bake = re.search(
                r'([\d]+(?:\s+tot\s+[\d]+)?)\s+(minuten|minuut)'
                r'(?:\s+\w+){0,4}\s*(?:bak|kook|bra|frite|gar)',
                text, re.IGNORECASE,
            )
            if m_bake:
                return self._translate_dutch_time(m_bake.group(1), m_bake.group(2))

            # "X tot Y minuten" anywhere (fallback for resting-as-cook time)
            m_range = re.search(
                r'([\d]+\s+tot\s+[\d]+)\s+(minuten|minuut)',
                text, re.IGNORECASE,
            )
            if m_range:
                return self._translate_dutch_time(m_range.group(1), m_range.group(2))

        except Exception as e:
            logger.warning(f"Error extracting cook_time: {e}")
        return None

    def extract_total_time(self) -> Optional[str]:
        """Общее время на этом сайте явно не указывается."""
        return None

    # ── Notes ─────────────────────────────────────────────────────────────────

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок/советов.

        Источники (в порядке убывания приоритета):
        1. Элементы <div class="code"> внутри <article>
        2. H2-секции с ключевыми словами «extraatje», «tip» и т.п.
        """
        try:
            article = self._get_article()
            if not article:
                return None

            notes: List[str] = []

            # 1. <div class="code"> blocks
            for div in article.find_all('div', class_='code'):
                text = self.clean_text(div.get_text())
                if text:
                    notes.append(text)

            # 2. h2 sections with notes keywords
            for h2 in article.find_all('h2'):
                h2_text = self.clean_text(h2.get_text())
                if not self._is_notes_header(h2_text):
                    continue
                # Use .next_sibling (not .find_next_sibling) to capture plain
                # text nodes that sit directly after the h2 tag.
                section_parts: List[str] = []
                node = h2.next_sibling
                while node is not None:
                    if hasattr(node, 'name') and node.name == 'h2':
                        break
                    if isinstance(node, NavigableString):
                        t = self.clean_text(str(node))
                        if t:
                            section_parts.append(t)
                    elif hasattr(node, 'get_text'):
                        # Skip bare <br> tags (they contribute no text)
                        if not (hasattr(node, 'name') and node.name == 'br'):
                            t = self.clean_text(node.get_text())
                            if t:
                                section_parts.append(t)
                    node = node.next_sibling
                if section_parts:
                    notes.append(' '.join(section_parts))

            return ' '.join(notes) if notes else None

        except Exception as e:
            logger.warning(f"Error extracting notes: {e}")
            return None

    # ── Tags ──────────────────────────────────────────────────────────────────

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из мета-тега <meta name='keywords'>."""
        try:
            meta = self.soup.find('meta', attrs={'name': 'keywords'})
            if meta and meta.get('content'):
                return self.clean_text(meta['content']) or None
        except Exception as e:
            logger.warning(f"Error extracting tags: {e}")
        return None

    # ── Images ────────────────────────────────────────────────────────────────

    def extract_image_urls(self) -> Optional[str]:
        """
        Извлечение URL изображений.
        Ищет <img> с «infonu.nl» в src внутри <article>,
        затем мета-тег og:image как запасной вариант.
        """
        try:
            urls: List[str] = []
            article = self._get_article()
            if article:
                for img in article.find_all('img'):
                    src = img.get('src') or img.get('data-src') or ''
                    if src.startswith('//'):
                        src = 'https:' + src
                    if 'infonu.nl' in src and ('foto' in src or 'image' in src):
                        urls.append(src)

            # Fallback: og:image
            if not urls:
                og = self.soup.find('meta', property='og:image')
                if og and og.get('content'):
                    urls.append(og['content'])

            # Deduplicate preserving order
            seen: set = set()
            unique: List[str] = []
            for url in urls:
                if url not in seen:
                    seen.add(url)
                    unique.append(url)

            return ','.join(unique) if unique else None

        except Exception as e:
            logger.warning(f"Error extracting image_urls: {e}")
            return None

    # ── Master method ─────────────────────────────────────────────────────────

    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта и возврат словаря."""
        return {
            'dish_name':    self.extract_dish_name(),
            'description':  self.extract_description(),
            'ingredients':  self.extract_ingredients(),
            'instructions': self.extract_steps(),
            'category':     self.extract_category(),
            'prep_time':    self.extract_prep_time(),
            'cook_time':    self.extract_cook_time(),
            'total_time':   self.extract_total_time(),
            'notes':        self.extract_notes(),
            'image_urls':   self.extract_image_urls(),
            'tags':         self.extract_tags(),
        }


def main() -> None:
    """Точка входа для обработки директории с HTML-файлами рецептов."""
    import os

    preprocessed_dir = os.path.join('preprocessed', 'eten-en-drinken_infonu_nl')

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(EtenEnDrinkenInfonuNlExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print('Использование: python eten-en-drinken_infonu_nl.py')


if __name__ == '__main__':
    main()
