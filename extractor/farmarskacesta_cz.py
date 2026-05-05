"""
Recipe data extractor for farmarskacesta.cz
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

# Czech cooking units mapping
_CZ_UNITS = [
    # Tablespoon variants
    r'lžíc[ei]',
    # Teaspoon variants
    r'lžičk[ay]',
    # Cup variants
    r'šálk[yůu]',
    r'šálek',
    # Weight
    r'kg',
    r'g',
    r'dkg',
    # Volume
    r'ml',
    r'dl',
    r'l',
    # Piece/count
    r'kus[ůy]?',
    r'ks',
    r'pieces?',
    # Other common
    r'hrnek',
    r'hrnk[yůu]',
    r'špetka',
    r'špetku',
    r'špetk[ay]',
    r'balíček',
    r'balíčk[yůu]',
    r'plátk[yůu]',
    r'plátek',
    r'stroužk[yůu]',
    r'stroužek',
    r'svazek',
    r'svazeček',
]

# Pattern that matches a unit at word boundary
_UNIT_RE = re.compile(
    r'\b(' + '|'.join(_CZ_UNITS) + r')\b',
    re.IGNORECASE,
)

# Czech time words
_TIME_KEYWORDS = {
    'prep': [
        r'doba\s+p[řr][íi]pravy\s+je\s+p[řr]ibli[žz]n[ěe]\s+([\d]+(?:\s*hodina?)?(?:\s*minut)?)',
        r'doba\s+p[řr][íi]pravy\s+je\s+([\d]+(?:\s*hodina?)?(?:\s*minut)?)',
        r'p[řr][íi]prava\s+trvá\s+([\d]+(?:\s*hodina?)?(?:\s*minut)?)',
        r'p[řr][íi]prava:\s*([\d]+(?:\s*hodina?)?(?:\s*minut)?)',
    ],
    'cook': [
        r'doba\s+va[řr]en[íi]\s+je\s+([\d]+(?:\s*hodina?)?(?:\s*minut)?)',
        r'doba\s+va[řr]en[íi]\s+([\d]+(?:\s*hodina?)?(?:\s*minut)?)',
        r'va[řr]en[íi]\s+([\d]+(?:\s*hodina?)?(?:\s*minut)?)',
        r'pečte\s+([\d]+(?:\s*hodina?)?(?:\s*minut)?)',
    ],
}


class FarmarskacestaExtractor(BaseRecipeExtractor):
    """Extractor for farmarskacesta.cz recipe pages."""

    # ------------------------------------------------------------------ #
    #  Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _get_article_json_ld(self) -> Optional[dict]:
        """Return the Article JSON-LD object (not wrapped in @graph), or None."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
                if isinstance(data, dict):
                    if data.get('@type') == 'Article':
                        return data
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and item.get('@type') == 'Article':
                                return item
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return None

    def _get_entry_content(self):
        """Return the main entry-content div."""
        return self.soup.find('div', class_='entry-content')

    def _next_meaningful_sibling(self, tag):
        """Return the next non-empty sibling element of *tag*."""
        sibling = tag.find_next_sibling()
        while sibling and not sibling.get_text(strip=True):
            sibling = sibling.find_next_sibling()
        return sibling

    @staticmethod
    def _normalize_time_value(raw: str) -> Optional[str]:
        """
        Convert a Czech time fragment like '10 minut', '45 minut',
        '1 hodina', '1 hodinu', '1 hodina 30 minut' into English.
        """
        raw = raw.strip()
        hours = 0
        minutes = 0

        h_match = re.search(r'(\d+)\s*hodin[au]?', raw, re.IGNORECASE)
        m_match = re.search(r'(\d+)\s*minut', raw, re.IGNORECASE)

        if h_match:
            hours = int(h_match.group(1))
        if m_match:
            minutes = int(m_match.group(1))

        hour_word = 'hour' if hours == 1 else 'hours'
        if hours and minutes:
            return f'{hours} {hour_word} {minutes} minutes'
        if hours:
            return f'{hours} {hour_word}'
        if minutes:
            return f'{minutes} minutes'

        # Fallback: just return the raw number if present
        num = re.search(r'\d+', raw)
        if num:
            return f'{num.group()} minutes'
        return None

    # ------------------------------------------------------------------ #
    #  Field extractors                                                     #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Extract the dish name from h1.post-title or og:title."""
        h1 = self.soup.find('h1', class_='post-title')
        if h1:
            return self.clean_text(h1.get_text())

        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        return None

    def extract_description(self) -> Optional[str]:
        """Extract the recipe intro paragraph."""
        entry = self._get_entry_content()
        if not entry:
            return None

        # The first paragraph before any h2 is the description
        for elem in entry.children:
            if getattr(elem, 'name', None) == 'h2':
                break
            if getattr(elem, 'name', None) == 'p':
                text = self.clean_text(elem.get_text())
                if text:
                    return text

        # Fallback: Article JSON-LD description
        ld = self._get_article_json_ld()
        if ld and ld.get('description'):
            desc = ld['description']
            if desc and desc.lower() != 'default':
                return self.clean_text(desc)

        # Fallback: og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def _parse_ingredient_line(self, text: str) -> Optional[dict]:
        """
        Parse a single Czech ingredient line into {name, amount, unit}.

        Examples:
            "4 střední brambory (ideálně varný typ A)"
            "2 lžíce olivového oleje"
            "1/2 lžičky černého pepře"
            "50 g strouhaného sýra (např. čedar)"
            "sůl a pepř"
            "slanina (podle chuti, volitelně)"
        """
        text = self.clean_text(text)
        if not text:
            return None

        # Replace Unicode fractions
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
        }
        for fr, repl in fraction_map.items():
            text = text.replace(fr, repl)

        # Pattern: optional-amount  optional-unit  name
        # Amount can be "1", "1/2", "0.5", "2-3", etc.
        amount_pattern = r'^([\d]+(?:[.,/\-][\d]+)?(?:\s+[\d]+/[\d]+)?)'
        # Build unit alternatives for inline matching
        unit_alternatives = '|'.join(_CZ_UNITS)
        unit_pattern = rf'\s*({unit_alternatives})\s+'
        # Try: amount + unit + name
        full_match = re.match(
            amount_pattern + unit_pattern + r'(.+)',
            text,
            re.IGNORECASE,
        )
        if full_match:
            raw_amount = full_match.group(1).strip()
            unit = full_match.group(2).strip()
            name = full_match.group(3).strip()
            amount = self._normalize_amount(raw_amount)
            name = self._clean_ingredient_name(name)
            return {'name': name, 'amount': amount, 'unit': unit}

        # Try: amount + name (no unit)
        no_unit_match = re.match(amount_pattern + r'\s+(.+)', text, re.IGNORECASE)
        if no_unit_match:
            raw_amount = no_unit_match.group(1).strip()
            name = no_unit_match.group(2).strip()
            amount = self._normalize_amount(raw_amount)
            name = self._clean_ingredient_name(name)
            if name:
                return {'name': name, 'amount': amount, 'unit': None}

        # No amount at all – just a name
        name = self._clean_ingredient_name(text)
        if name:
            return {'name': name, 'amount': None, 'unit': None}

        return None

    @staticmethod
    def _normalize_amount(raw: str) -> Optional[str]:
        """Normalise a raw amount string."""
        raw = raw.strip()
        if not raw:
            return None
        # Handle "1/2" fractions
        if re.match(r'^\d+/\d+$', raw):
            num, den = raw.split('/')
            try:
                return str(round(int(num) / int(den), 4)).rstrip('0').rstrip('.')
            except ZeroDivisionError:
                return raw
        # Handle "1 1/2" (mixed numbers)
        mixed = re.match(r'^(\d+)\s+(\d+)/(\d+)$', raw)
        if mixed:
            whole, num, den = mixed.groups()
            try:
                val = int(whole) + int(num) / int(den)
                return str(round(val, 4)).rstrip('0').rstrip('.')
            except ZeroDivisionError:
                return raw
        return raw.replace(',', '.')

    @staticmethod
    def _clean_ingredient_name(name: str) -> str:
        """Remove parenthetical qualifiers and trailing punctuation."""
        # Remove parenthetical notes like "(ideálně varný typ A)", "(podle chuti)"
        name = re.sub(r'\([^)]*\)', '', name)
        # Remove trailing comma/semicolon
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        return name

    def extract_ingredients(self) -> Optional[str]:
        """Extract ingredients list as a JSON string."""
        entry = self._get_entry_content()
        if not entry:
            logger.warning('No entry-content found in %s', self.html_path)
            return None

        ingredients: List[dict] = []

        # Find h2 "Ingredience" and take its following ul
        for h2 in entry.find_all('h2'):
            if re.search(r'ingredien', h2.get_text(strip=True), re.IGNORECASE):
                ul = h2.find_next_sibling('ul')
                if ul:
                    for li in ul.find_all('li'):
                        text = self.clean_text(li.get_text(separator=' ', strip=True))
                        if text:
                            parsed = self._parse_ingredient_line(text)
                            if parsed:
                                ingredients.append(parsed)
                break

        if not ingredients:
            logger.warning('No ingredients found in %s', self.html_path)
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def extract_instructions(self) -> Optional[str]:
        """Extract preparation steps as a single string."""
        entry = self._get_entry_content()
        if not entry:
            return None

        steps = []

        # Find h2 "Postup přípravy" (or similar)
        for h2 in entry.find_all('h2'):
            h2_text = h2.get_text(strip=True).lower()
            if re.search(r'postup|p[řr][íi]prav|krok', h2_text, re.IGNORECASE):
                ol = h2.find_next_sibling('ol')
                if ol:
                    for li in ol.find_all('li'):
                        step = self.clean_text(li.get_text(separator=' ', strip=True))
                        if step:
                            steps.append(step)
                break

        if not steps:
            logger.warning('No instructions found in %s', self.html_path)
            return None

        return ' '.join(steps)

    def _extract_time_from_section(self) -> dict:
        """
        Parse prep_time, cook_time, and total_time from the
        'Počet porcí a doba přípravy' section paragraph.
        """
        result = {'prep_time': None, 'cook_time': None, 'total_time': None}
        entry = self._get_entry_content()
        if not entry:
            return result

        for h2 in entry.find_all('h2'):
            h2_text = h2.get_text(strip=True).lower()
            if re.search(r'po[čc]et\s+porc[íi]|doba\s+p[řr][íi]prav', h2_text, re.IGNORECASE):
                p = h2.find_next_sibling('p')
                if p:
                    text = self.clean_text(p.get_text())
                    result = self._parse_times(text)
                break

        return result

    @staticmethod
    def _parse_times(text: str) -> dict:
        """
        Parse a time description paragraph like:
          "Recept je na 4 porce. Doba přípravy je 10 minut, doba vaření 45 minut."
          "Doba přípravy je přibližně 30 minut, doba vaření je 1 hodina."
        """
        result = {'prep_time': None, 'cook_time': None, 'total_time': None}

        # Prep time
        prep_match = re.search(
            r'doba\s+p[řr][íi]pravy\s+je\s+p[řr]ibli[žz]n[ěe]\s+([\d]+(?:\s+hodin[au]?)?(?:\s*minut)?)',
            text, re.IGNORECASE,
        )
        if not prep_match:
            prep_match = re.search(
                r'doba\s+p[řr][íi]pravy\s+je\s+([\d]+(?:\s+hodin[au]?)?(?:\s*minut)?)',
                text, re.IGNORECASE,
            )
        if prep_match:
            raw = prep_match.group(1)
            # If no time unit captured, look right after the number
            if not re.search(r'hodin|minut', raw, re.IGNORECASE):
                # Try to get next word
                pos = prep_match.end()
                next_word = re.match(r'\s*(\w+)', text[pos:])
                if next_word:
                    raw = raw + ' ' + next_word.group(1)
            result['prep_time'] = FarmarskacestaExtractor._normalize_time_value(raw)

        # Cook time
        cook_match = re.search(
            r'doba\s+va[řr]en[íi]\s+(?:je\s+)?([\d]+(?:\s+hodin[au]?)?(?:\s*minut)?)',
            text, re.IGNORECASE,
        )
        if cook_match:
            raw = cook_match.group(1)
            if not re.search(r'hodin|minut', raw, re.IGNORECASE):
                pos = cook_match.end()
                next_word = re.match(r'\s*(\w+)', text[pos:])
                if next_word:
                    raw = raw + ' ' + next_word.group(1)
            result['cook_time'] = FarmarskacestaExtractor._normalize_time_value(raw)

        # Total time: compute from prep + cook if both available
        prep_min = FarmarskacestaExtractor._time_to_minutes(result['prep_time'])
        cook_min = FarmarskacestaExtractor._time_to_minutes(result['cook_time'])
        if prep_min is not None and cook_min is not None:
            total = prep_min + cook_min
            result['total_time'] = FarmarskacestaExtractor._minutes_to_str(total)

        return result

    @staticmethod
    def _time_to_minutes(time_str: Optional[str]) -> Optional[int]:
        """Convert '10 minutes', '1 hour', '1 hour 30 minutes' to total minutes."""
        if not time_str:
            return None
        hours = 0
        minutes = 0
        h_match = re.search(r'(\d+)\s*hour', time_str, re.IGNORECASE)
        m_match = re.search(r'(\d+)\s*minute', time_str, re.IGNORECASE)
        if h_match:
            hours = int(h_match.group(1))
        if m_match:
            minutes = int(m_match.group(1))
        total = hours * 60 + minutes
        return total if total > 0 else None

    @staticmethod
    def _minutes_to_str(minutes: int) -> str:
        """Convert integer minutes to human-readable English string."""
        if minutes < 60:
            return f'{minutes} minutes'
        hours = minutes // 60
        mins = minutes % 60
        hour_word = 'hour' if hours == 1 else 'hours'
        if mins:
            return f'{hours} {hour_word} {mins} minutes'
        return f'{hours} {hour_word}'

    def extract_category(self) -> Optional[str]:
        """Extract category from JSON-LD articleSection."""
        try:
            ld = self._get_article_json_ld()
            if ld and ld.get('articleSection'):
                section = ld['articleSection']
                if isinstance(section, list):
                    section = section[0] if section else None
                if section:
                    # The articleSection is often a comma-separated list of tags;
                    # use the first meaningful token as the category.
                    parts = [p.strip() for p in section.split(',') if p.strip()]
                    if parts:
                        return self.clean_text(parts[0])
        except Exception:
            logger.exception('Error extracting category from %s', self.html_path)

        # Fallback: breadcrumb second link
        breadcrumb = self.soup.find('nav', id='breadcrumb')
        if breadcrumb:
            links = breadcrumb.find_all('a')
            if len(links) >= 2:
                return self.clean_text(links[-1].get_text())

        return None

    def extract_notes(self) -> Optional[str]:
        """
        Gather notes from the 'Alternativní ingredience' and 'Užitečné tipy' sections.
        """
        entry = self._get_entry_content()
        if not entry:
            return None

        note_keywords = re.compile(
            r'alternativn[íi]|u[žz]ite[čc]n[éě]\s+tip|tip[sy]|pozn[áa]mk[ay]|záv[ěe]r',
            re.IGNORECASE,
        )

        notes_parts = []

        for h2 in entry.find_all('h2'):
            if note_keywords.search(h2.get_text(strip=True)):
                # Collect text from all sibling p/ul/li until next h2
                current = h2.find_next_sibling()
                while current and getattr(current, 'name', None) != 'h2':
                    if getattr(current, 'name', None) in ('p', 'ul', 'ol'):
                        text = self.clean_text(current.get_text(separator=' ', strip=True))
                        if text:
                            notes_parts.append(text)
                    current = current.find_next_sibling()

        if not notes_parts:
            return None

        return ' '.join(notes_parts)

    def extract_tags(self) -> Optional[str]:
        """Extract tags from JSON-LD articleSection."""
        try:
            ld = self._get_article_json_ld()
            if ld and ld.get('articleSection'):
                section = ld['articleSection']
                if isinstance(section, list):
                    section = ', '.join(str(s) for s in section)
                if section:
                    return self.clean_text(section)
        except Exception:
            logger.exception('Error extracting tags from %s', self.html_path)

        # Fallback: meta keywords
        meta_kw = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_kw and meta_kw.get('content'):
            return self.clean_text(meta_kw['content'])

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Extract image URLs from the entry-content area and og:image."""
        urls = []
        seen: set = set()

        def _add(url: str) -> None:
            if not url:
                return
            # Normalise protocol-relative URLs before deduplication
            if url.startswith('//'):
                url = 'https:' + url
            if url not in seen:
                seen.add(url)
                urls.append(url)

        # 1. og:image (primary)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            _add(og_image['content'])

        # 2. Images within entry-content (skip thumbnails / cached thumbs / avatars)
        entry = self._get_entry_content()
        if entry:
            for img in entry.find_all('img'):
                src = (
                    img.get('src')
                    or img.get('data-src')
                    or img.get('data-lazy-src')
                )
                if not src:
                    continue
                # Skip tiny thumbnails and cached thumbs
                if re.search(r'-\d+x\d+\.', src) or '/cache/' in src or 'stub_' in src:
                    continue
                # Skip avatars
                if 'avatar' in src.lower() or 'default-avatar' in src.lower():
                    continue
                _add(src)

        return ','.join(urls) if urls else None

    # ------------------------------------------------------------------ #
    #  Public API                                                           #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """Extract all recipe data and return as a dict."""
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()

        times = self._extract_time_from_section()

        return {
            'dish_name': dish_name,
            'description': description,
            'ingredients': ingredients,
            'instructions': instructions,
            'category': category,
            'prep_time': times.get('prep_time'),
            'cook_time': times.get('cook_time'),
            'total_time': times.get('total_time'),
            'notes': notes,
            'tags': tags,
            'image_urls': image_urls,
        }


def main() -> None:
    import os

    base_dir = Path(__file__).parent.parent
    recipes_dir = base_dir / 'preprocessed' / 'farmarskacesta_cz'

    if recipes_dir.exists() and recipes_dir.is_dir():
        process_directory(FarmarskacestaExtractor, str(recipes_dir))
        return

    print(f'Directory not found: {recipes_dir}')
    print('Usage: python farmarskacesta_cz.py')


if __name__ == '__main__':
    main()
