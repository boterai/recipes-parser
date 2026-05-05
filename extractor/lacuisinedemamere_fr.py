"""
Экстрактор данных рецептов для сайта lacuisinedemamere.fr
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

# French measurement units (singular and plural forms)
_FRENCH_UNITS = [
    r'cuillères?\s+à\s+soupe',
    r'cuillères?\s+à\s+café',
    r'cuillères?\s+à\s+dessert',
    r'c\.?\s*à\s*s\.?',
    r'c\.?\s*à\s*c\.?',
    r'sachets?',
    r'bouquets?',
    r'gousses?',
    r'tranches?',
    r'feuilles?',
    r'brins?',
    r'kg|g|mg',
    r'litres?|l',
    r'ml|cl|dl',
    r'tasses?',
    r'verres?',
    r'poignées?',
    r'pincées?',
    r'cubes?',
    r'plaquettes?',
    r'paquets?',
    r'boîtes?',
    r'pièces?',
    r'portions?',
    r'filets?',
]

_UNIT_PATTERN = '(?:' + '|'.join(_FRENCH_UNITS) + ')'

# Pattern: optional_amount optional_unit [de/d'/d'] name
_INGREDIENT_RE = re.compile(
    r'^([\d,./]+)?\s*'
    r'(' + _UNIT_PATTERN + r')?\s*'
    r'(?:de\s+|d\u2019|d\')?'
    r'(.+)$',
    re.IGNORECASE,
)

# Pattern for a plain number followed by a name (no unit)
_AMOUNT_NAME_RE = re.compile(r'^([\d,./]+)\s+(.+)$')

# Patterns for time lines in the "Temps de préparation et cuisson" section
_PREP_RE = re.compile(r'Temps\s+de\s+pr[eé]paration\s*:\s*(.+)', re.IGNORECASE)
_COOK_RE = re.compile(r'Temps\s+de\s+cuisson\s*:\s*(.+)', re.IGNORECASE)
_REST_RE = re.compile(r'Temps\s+de\s+repos\s*:\s*(.+)', re.IGNORECASE)

# Pattern for "X minute(s)" / "X heure(s) [Y minute(s)]"
_TIME_MINUTES_RE = re.compile(r'(\d+)\s*(?:minute[s]?|min)', re.IGNORECASE)
_TIME_HOURS_RE = re.compile(
    r'(\d+)\s*heure[s]?\s*(?:(\d+)\s*(?:minute[s]?|min))?', re.IGNORECASE
)


def _parse_duration(text: str) -> Optional[str]:
    """
    Convert a French duration string like '30 minutes', '1 heure', '1 heure 30 minutes'
    into a normalised English string like '30 minutes', '1 hour', '1 hour 30 minutes'.
    Returns None if the text cannot be parsed.
    """
    if not text:
        return None
    text = text.strip()

    m = _TIME_HOURS_RE.match(text)
    if m:
        h = int(m.group(1))
        mn = int(m.group(2)) if m.group(2) else 0
        if mn:
            return f'{h} hour {mn} minutes' if h == 1 else f'{h} hours {mn} minutes'
        return f'{h} hour' if h == 1 else f'{h} hours'

    m = _TIME_MINUTES_RE.match(text)
    if m:
        return f'{m.group(1)} minutes'

    return text


def _sum_durations(durations: list) -> Optional[str]:
    """
    Sum a list of parsed duration strings (output of _parse_duration) and return
    a single normalised duration string.
    """
    total_minutes = 0
    for d in durations:
        if not d:
            continue
        mh = re.match(r'(\d+)\s*hour[s]?\s*(?:(\d+)\s*minute[s]?)?', d)
        if mh:
            total_minutes += int(mh.group(1)) * 60
            if mh.group(2):
                total_minutes += int(mh.group(2))
            continue
        mm = re.match(r'(\d+)\s*minute[s]?', d)
        if mm:
            total_minutes += int(mm.group(1))

    if total_minutes == 0:
        return None

    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        h_label = 'hour' if hours == 1 else 'hours'
        return f'{hours} {h_label} {minutes} minutes'
    if hours:
        return f'{hours} hour' if hours == 1 else f'{hours} hours'
    return f'{total_minutes} minutes'


def _parse_ingredient_line(line: str) -> Optional[dict]:
    """
    Parse a single French ingredient line such as:
      '500g de farine', '1 sachet de levure', '1 œuf', 'Sel et poivre', 'Sel et poivre au goût'

    Returns a dict {'name': str, 'amount': str|None, 'unit': str|None} or None.
    """
    line = line.strip()

    # Strip leading dash / em-dash / en-dash markers
    line = re.sub(r'^[–—\-]+\s*', '', line).strip()

    if not line:
        return None

    # Handle trailing "au goût" / "selon votre goût" as a special unit
    au_gout_unit = None
    au_gout_match = re.search(r'\s+(au\s+goût|selon\s+(?:votre\s+)?goût)$', line, re.IGNORECASE)
    if au_gout_match:
        au_gout_unit = au_gout_match.group(1)
        line = line[:au_gout_match.start()].strip()

    m = _INGREDIENT_RE.match(line)
    if m:
        amount_str, unit, name = m.groups()
        # Discard matches where neither amount nor unit was captured and
        # the whole line ended up in 'name' only — still valid.
        amount = amount_str.strip() if amount_str else None
        unit = unit.strip() if unit else au_gout_unit
        name = name.strip() if name else None

        # If unit was not detected, try plain "number name" pattern
        if amount is None and unit is None:
            plain = _AMOUNT_NAME_RE.match(line)
            if plain:
                amount = plain.group(1)
                name = plain.group(2).strip()
                unit = au_gout_unit

        if not name:
            return None

        return {'name': name, 'amount': amount, 'unit': unit}

    # Fallback: try plain "number name"
    plain = _AMOUNT_NAME_RE.match(line)
    if plain:
        return {'name': plain.group(2).strip(), 'amount': plain.group(1), 'unit': au_gout_unit}

    # No amount/unit at all
    return {'name': line, 'amount': None, 'unit': au_gout_unit}


class LacuisinedemamereFrExtractor(BaseRecipeExtractor):
    """Extractor for lacuisinedemamere.fr recipe pages."""

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    def _get_entry_content(self):
        """Return the main entry-content div."""
        return self.soup.find('div', class_='entry-content')

    def _section_paragraph(self, heading_text: str) -> Optional[str]:
        """
        Find the first <p> sibling immediately following the <h2> whose text
        contains *heading_text* (case-insensitive) inside entry-content.
        Returns the paragraph text or None.
        """
        content = self._get_entry_content()
        if not content:
            return None

        for h2 in content.find_all('h2'):
            if heading_text.lower() in h2.get_text(strip=True).lower():
                p = h2.find_next_sibling('p')
                if p:
                    return p.get_text()
        return None

    def _section_paragraphs(self, heading_text: str) -> list:
        """
        Return a list of all <p> siblings following the <h2> matching
        *heading_text* up to the next <h2>.
        """
        content = self._get_entry_content()
        if not content:
            return []

        for h2 in content.find_all('h2'):
            if heading_text.lower() in h2.get_text(strip=True).lower():
                results = []
                for sib in h2.next_siblings:
                    if sib.name == 'h2':
                        break
                    if sib.name == 'p':
                        text = sib.get_text().strip()
                        if text:
                            results.append(text)
                return results
        return []

    # -----------------------------------------------------------------
    # Public extraction methods
    # -----------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Extract the recipe title from the page <h1> or og:title."""
        content = self._get_entry_content()
        if content:
            h1 = content.find('h1')
            if h1:
                name = self.clean_text(h1.get_text())
                # Strip "Recette " prefix that appears on many pages
                name = re.sub(r'^Recette\s+', '', name, flags=re.IGNORECASE).strip()
                return name if name else None

        # Fallback: og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = self.clean_text(og_title['content'])
            # Remove site suffix
            title = re.sub(r'\s*-\s*La Cuisine de ma Mère.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'^Recette\s+', '', title, flags=re.IGNORECASE).strip()
            return title if title else None

        return None

    def extract_description(self) -> Optional[str]:
        """Extract the intro / short description paragraph."""
        text = self._section_paragraph('Description de la recette')
        if text:
            # Take only the first sentence(s) up to the first double newline
            # or the full paragraph if it is short enough.
            paragraphs = [p.strip() for p in text.strip().split('\n') if p.strip()]
            if paragraphs:
                return self.clean_text(paragraphs[0])

        # Fallback: og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Extract ingredients from the "Ingrédients" section paragraphs.
        Lines start with '–' and are of the form "Xunit de name".
        Multiple sub-sections (e.g. "Pour la pâte :") are supported.
        Returns a JSON string of a list of {name, amount, unit} dicts.
        """
        paragraphs = self._section_paragraphs('Ingrédient')
        if not paragraphs:
            # Fallback: recipeIngredient from JSON-LD
            return self._ingredients_from_jsonld()

        ingredients = []
        for text in paragraphs:
            for line in text.split('\n'):
                line = line.strip()
                if not line:
                    continue
                # Skip sub-section headers like "Pour la pâte :", "Pour 4 personnes :"
                if re.search(r':\s*$', line) and not line.startswith('–') and not line.startswith('-'):
                    continue

                parsed = _parse_ingredient_line(line)
                if parsed:
                    ingredients.append(parsed)

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        return self._ingredients_from_jsonld()

    def _ingredients_from_jsonld(self) -> Optional[str]:
        """Fallback: parse ingredients from JSON-LD recipeIngredient."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    raw = data.get('recipeIngredient', [])
                    if raw and any(r.strip() for r in raw):
                        ingredients = []
                        for item in raw:
                            if not item.strip():
                                continue
                            parsed = _parse_ingredient_line(item)
                            if parsed:
                                ingredients.append(parsed)
                        if ingredients:
                            return json.dumps(ingredients, ensure_ascii=False)
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    def extract_instructions(self) -> Optional[str]:
        """
        Extract numbered preparation steps from the "Étapes de préparation" section.
        Returns a single string with all steps.
        """
        text = self._section_paragraph('Étapes de préparation')
        if not text:
            text = self._section_paragraph('tapes de pr')

        if text:
            # Strip leading step numbers (1. 2. …) and join as clean prose
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            cleaned = []
            for line in lines:
                # Remove leading number+dot
                line = re.sub(r'^\d+\.\s*', '', line)
                if line:
                    cleaned.append(line)
            if cleaned:
                return self.clean_text(' '.join(cleaned))

        # Fallback: JSON-LD recipeInstructions
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    instructions = data.get('recipeInstructions', [])
                    steps = []
                    for step in instructions:
                        if isinstance(step, dict):
                            steps.append(step.get('text', ''))
                        elif isinstance(step, str):
                            steps.append(step)
                    if steps:
                        return self.clean_text(' '.join(steps))
            except (json.JSONDecodeError, AttributeError):
                continue

        return None

    def _extract_times_from_section(self) -> dict:
        """
        Parse the "Temps de préparation et cuisson" section paragraph and
        return a dict with keys 'prep', 'cook', 'rest' (all Optional[str]).
        """
        text = self._section_paragraph('Temps de préparation')
        result = {'prep': None, 'cook': None, 'rest': None}

        if not text:
            logger.debug('Time section not found')
            return result

        for line in text.split('\n'):
            line = line.strip()
            m = _PREP_RE.match(line)
            if m:
                result['prep'] = _parse_duration(m.group(1).strip())
                continue
            m = _COOK_RE.match(line)
            if m:
                result['cook'] = _parse_duration(m.group(1).strip())
                continue
            m = _REST_RE.match(line)
            if m:
                result['rest'] = _parse_duration(m.group(1).strip())

        return result

    def extract_prep_time(self) -> Optional[str]:
        return self._extract_times_from_section().get('prep')

    def extract_cook_time(self) -> Optional[str]:
        return self._extract_times_from_section().get('cook')

    def extract_total_time(self) -> Optional[str]:
        times = self._extract_times_from_section()
        return _sum_durations([times.get('prep'), times.get('cook'), times.get('rest')])

    def extract_notes(self) -> Optional[str]:
        """
        Collect tips and conservation advice from h2/h3 sections that
        typically follow the preparation steps.
        """
        note_keywords = ['astuce', 'comment conserver', 'comment am', 'une fa']
        stop_words = ('conclusion', 'faq', 'hashtag', 'question')

        content = self._get_entry_content()
        if not content:
            return None

        collected = []
        for tag in content.find_all(['h2', 'h3']):
            heading = tag.get_text(strip=True).lower()
            # Skip structural sections
            if any(stop in heading for stop in stop_words):
                continue
            if any(kw in heading for kw in note_keywords):
                p = tag.find_next_sibling('p')
                if p:
                    text = self.clean_text(p.get_text())
                    if text:
                        collected.append(text)

        return ' '.join(collected) if collected else None

    def extract_tags(self) -> Optional[str]:
        """
        Extract tags from the 'Hashtags' section paragraph.
        The paragraph typically looks like '#Cuisine #Recette #Géorgie …'.
        Returns a comma-separated string of tag names (without '#'), or None
        if no hashtags are found.
        """
        text = self._section_paragraph('Hashtags')
        if text:
            tags = re.findall(r'#(\w[\w\u00C0-\u024F]*)', text)
            if tags:
                return ','.join(tags)

        return None

    def extract_category(self) -> Optional[str]:
        """
        Extract category from the WordPress article CSS classes
        (e.g. 'category-recettes', 'category-recettes-de-maman').
        Returns the most specific non-generic category name, or None.
        """
        article = self.soup.find('article')
        if article:
            classes = article.get('class', [])
            # These are too generic to be useful as a recipe category
            generic = {
                'recettes', 'recettes-du-moment', 'recettes-de-maman',
                'recettes-faciles-et-rapides', 'recettes-de-saison',
            }
            categories = []
            for cls in classes:
                if cls.startswith('category-'):
                    cat = cls[len('category-'):]
                    if cat not in generic:
                        categories.append(cat.replace('-', ' '))
            if categories:
                return ', '.join(categories)

        # Fallback: breadcrumb JSON-LD
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'BreadcrumbList':
                    items = data.get('itemListElement', [])
                    # Second-to-last item is usually the category
                    if len(items) >= 2:
                        name = items[-2].get('item', {}).get('name', '')
                        if name and name.lower() not in ('home', 'recettes', 'accueil'):
                            return self.clean_text(name)
            except (json.JSONDecodeError, AttributeError):
                continue

        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Collect image URLs from og:image meta tag and JSON-LD Recipe image.
        Returns a comma-separated string of unique URLs or None.
        """
        urls = []

        # 1. og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # 2. JSON-LD Recipe image
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    img = data.get('image')
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, dict):
                        url = img.get('url') or img.get('contentUrl')
                        if url:
                            urls.append(url)
                    elif isinstance(img, list):
                        for i in img:
                            if isinstance(i, str):
                                urls.append(i)
                            elif isinstance(i, dict):
                                u = i.get('url') or i.get('contentUrl')
                                if u:
                                    urls.append(u)
            except (json.JSONDecodeError, AttributeError):
                continue

        # Deduplicate preserving order
        seen: set = set()
        unique: list = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    # -----------------------------------------------------------------
    # Main extraction entry-point
    # -----------------------------------------------------------------

    def extract_all(self) -> dict:
        """
        Extract all recipe data from the HTML page.

        Returns:
            dict with keys: dish_name, description, ingredients, instructions,
            category, prep_time, cook_time, total_time, notes, image_urls, tags.
            Missing values are set to None.
        """
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
        except Exception as exc:
            logger.error('Unexpected error during extraction: %s', exc, exc_info=True)
            dish_name = description = ingredients = instructions = None
            category = prep_time = cook_time = total_time = notes = tags = image_urls = None

        return {
            'dish_name': dish_name.lower() if dish_name else None,
            'description': description,
            'ingredients': ingredients,
            'instructions': instructions,
            'category': category,
            'prep_time': prep_time,
            'cook_time': cook_time,
            'total_time': total_time,
            'notes': notes,
            'image_urls': image_urls,
            'tags': tags,
        }


def main():
    """Entry point: process all HTML files in preprocessed/lacuisinedemamere_fr."""
    import os

    preprocessed_dir = os.path.join('preprocessed', 'lacuisinedemamere_fr')

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(LacuisinedemamereFrExtractor, preprocessed_dir)
        return

    print(f'Директория не найдена: {preprocessed_dir}')
    print('Использование: python lacuisinedemamere_fr.py')


if __name__ == '__main__':
    main()
