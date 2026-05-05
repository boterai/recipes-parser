"""
Экстрактор данных рецептов для сайта geradorreceitas.com.br
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


class GeradorReceitasComBrExtractor(BaseRecipeExtractor):
    """Экстрактор для geradorreceitas.com.br"""

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _get_json_ld(self) -> Optional[dict]:
        """Return the first Recipe JSON-LD object found on the page, or None."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or script.get_text())
            except (json.JSONDecodeError, TypeError):
                continue

            # Handle bare Recipe dict
            if isinstance(data, dict):
                item_type = data.get('@type', '')
                if (isinstance(item_type, str) and item_type == 'Recipe') or (
                    isinstance(item_type, list) and 'Recipe' in item_type
                ):
                    return data
                # Handle @graph
                for item in data.get('@graph', []):
                    t = item.get('@type', '')
                    if t == 'Recipe' or (isinstance(t, list) and 'Recipe' in t):
                        return item

            # Handle list of objects
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    t = item.get('@type', '')
                    if t == 'Recipe' or (isinstance(t, list) and 'Recipe' in t):
                        return item
        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """Convert ISO 8601 duration (e.g. 'PT15M', 'PT1H30M') to 'N minutes'."""
        if not duration or not duration.startswith('PT'):
            return None
        rest = duration[2:]
        hours, minutes = 0, 0
        h_match = re.search(r'(\d+)H', rest)
        m_match = re.search(r'(\d+)M', rest)
        if h_match:
            hours = int(h_match.group(1))
        if m_match:
            minutes = int(m_match.group(1))
        total = hours * 60 + minutes
        return f"{total} minutes" if total > 0 else None

    @staticmethod
    def _normalize_time_text(text: str) -> str:
        """Normalize Portuguese time text (e.g. '15 minutos') to '15 minutes'."""
        text = re.sub(r'\bminutos?\b', 'minutes', text, flags=re.IGNORECASE)
        text = re.sub(r'\bhoras?\b', 'hours', text, flags=re.IGNORECASE)
        return text.strip()

    # ------------------------------------------------------------------ #
    # Ingredient parsing
    # ------------------------------------------------------------------ #

    @staticmethod
    def _strip_prep_note(text: str) -> str:
        """Strip preparation notes that appear after a comma in ingredient text.

        Examples:
            "cebola média, picada"      -> "cebola média"
            "dentes de alho, picados"   -> "dentes de alho"
            "cebola pequena picada"     -> "cebola pequena picada"  (no comma)
        """
        prep_words = (
            r'picad[ao]s?|cortad[ao]s?|fatiado[ao]s?|ralad[ao]s?|'
            r'descascad[ao]s?|cozid[ao]s?|assad[ao]s?|moíd[ao]s?|'
            r'em\s+cubos|em\s+fatias|em\s+rodelas|ao\s+meio|'
            r'finamente|grosseiramente'
        )
        m = re.search(rf',\s*(?:{prep_words}).*$', text, re.IGNORECASE)
        if m:
            text = text[:m.start()]
        return text.strip()

    def _parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """Parse a Portuguese ingredient string into {name, amount, unit}.

        Handles patterns such as:
            "500g de peito de frango, cortado em cubos"
            "2 colheres de sopa de azeite"
            "1 xícara de arroz"
            "1 cebola média, picada"
            "Sal e pimenta do reino a gosto"
            "Queijo cheddar ralado (opcional)"  -> amount=None
        """
        if not ingredient_text:
            return None

        text = ingredient_text.strip()

        # Replace Unicode fractions
        fraction_map = {'½': '1/2', '¼': '1/4', '¾': '3/4', '⅓': '1/3', '⅔': '2/3'}
        for frac, rep in fraction_map.items():
            text = text.replace(frac, rep)

        # ---- Case 1: "a gosto" at the end --------------------------------
        if re.search(r'\ba\s+gosto\s*$', text, re.IGNORECASE):
            name = re.sub(r'\ba\s+gosto\s*$', '', text, flags=re.IGNORECASE)
            name = name.rstrip(',').strip()
            return {"name": name, "unit": None, "amount": "a gosto"}

        # ---- Case 2: No leading number → item has no specified quantity ---
        if not re.match(r'^[\d]', text):
            return {"name": text, "unit": None, "amount": None}

        # ---- Extract leading number (int, decimal, or fraction like 1/2) --
        number_match = re.match(
            r'^(\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?)\s*', text
        )
        if not number_match:
            return {"name": text, "unit": None, "amount": None}

        amount_str = number_match.group(1).strip()
        rest = text[number_match.end():]

        # ---- Case 3: number immediately followed by unit abbreviation -----
        # e.g. "500g de peito de frango..."
        abbrev_match = re.match(r'^(g|kg|ml|l)\b\s*', rest, re.IGNORECASE)
        if abbrev_match:
            unit = abbrev_match.group(1).lower()
            rest = rest[abbrev_match.end():]
            if rest.startswith('de '):
                rest = rest[3:]
            name = self._strip_prep_note(rest)
            return {"name": name, "unit": unit, "amount": amount_str}

        # ---- Case 4: known Portuguese volume/measure unit + "de " ---------
        # Note: colher(?:es)? correctly matches "colher" and "colheres" (not "colhere")
        pt_unit_patterns = [
            r'colher(?:es)?\s+de\s+sopa',
            r'colher(?:es)?\s+de\s+ch[aá]',
            r'xícara[s]?',
            r'copos?',
            r'sach[êe]s?',
            r'pitadas?',
            r'litros?',
            r'mililitros?',
            r'gramas?',
            r'quilogramas?',
        ]
        for unit_pat in pt_unit_patterns:
            m = re.match(rf'^({unit_pat})\s+de\s+', rest, re.IGNORECASE)
            if m:
                unit = m.group(1)
                rest = rest[m.end():]
                name = self._strip_prep_note(rest)
                return {"name": name, "unit": unit, "amount": amount_str}

        # ---- Case 5: plain number + name (no known unit) ------------------
        name = self._strip_prep_note(rest)
        return {"name": name, "unit": None, "amount": amount_str}

    # ------------------------------------------------------------------ #
    # Field extractors
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Extract recipe title, stripping subtitle and generic prefix."""
        jld = self._get_json_ld()
        name = None
        if jld:
            name = jld.get('name')

        if not name:
            h1 = self.soup.find('h1')
            if h1:
                name = h1.get_text(strip=True)

        if not name:
            og = self.soup.find('meta', property='og:title')
            if og and og.get('content'):
                name = og['content']

        if not name:
            return None

        name = self.clean_text(name)
        # Strip subtitle after ": " (e.g. "Frango: Uma Explosão!" → "Frango")
        name = re.sub(r'\s*:.*$', '', name).strip()
        # Strip leading "Receita de " prefix (common on this site)
        name = re.sub(r'^Receita\s+de\s+', '', name, flags=re.IGNORECASE).strip()
        return name if name else None

    def extract_description(self) -> Optional[str]:
        """Extract recipe description from JSON-LD or meta tags."""
        jld = self._get_json_ld()
        if jld and jld.get('description'):
            return self.clean_text(jld['description'])

        # Fallback: description paragraph visible on page
        p = self.soup.find('p', class_=re.compile(r'text-xl', re.I))
        if p:
            text = self.clean_text(p.get_text())
            if text:
                return text

        meta = self.soup.find('meta', {'name': 'description'})
        if meta and meta.get('content'):
            return self.clean_text(meta['content'])

        og = self.soup.find('meta', property='og:description')
        if og and og.get('content'):
            return self.clean_text(og['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Extract and parse ingredient list from JSON-LD recipeIngredient."""
        jld = self._get_json_ld()
        raw_ingredients: list[str] = []

        if jld and jld.get('recipeIngredient'):
            raw_ingredients = jld['recipeIngredient']

        if not raw_ingredients:
            # Fallback: parse HTML ingredient list
            ing_h2 = self.soup.find(
                'h2', string=lambda t: t and 'Ingrediente' in t
            )
            if ing_h2:
                parent = ing_h2.find_parent()
                ul = parent.find('ul') if parent else None
                if ul:
                    for li in ul.find_all('li'):
                        # Each li has a decorative span + a content span
                        spans = li.find_all('span')
                        if len(spans) >= 2:
                            raw_ingredients.append(
                                self.clean_text(spans[-1].get_text())
                            )
                        else:
                            text = self.clean_text(li.get_text())
                            if text:
                                raw_ingredients.append(text)

        if not raw_ingredients:
            logger.warning("No ingredients found in %s", self.html_path)
            return None

        parsed = []
        for item in raw_ingredients:
            ing = self._parse_ingredient(item)
            if ing:
                parsed.append(ing)

        return json.dumps(parsed, ensure_ascii=False) if parsed else None

    def extract_instructions(self) -> Optional[str]:
        """Extract cooking instructions from JSON-LD recipeInstructions."""
        jld = self._get_json_ld()
        steps: list[str] = []

        if jld and jld.get('recipeInstructions'):
            for step in jld['recipeInstructions']:
                if isinstance(step, dict) and step.get('text'):
                    steps.append(self.clean_text(step['text']))
                elif isinstance(step, str):
                    steps.append(self.clean_text(step))

        if not steps:
            # Fallback: HTML ordered list
            inst_h2 = self.soup.find(
                'h2', string=lambda t: t and 'Preparo' in t
            )
            if inst_h2:
                parent = inst_h2.find_parent()
                ol = parent.find('ol') if parent else None
                if ol:
                    for li in ol.find_all('li'):
                        # Each li has a numbered span + a content div
                        div = li.find('div')
                        if div:
                            text = self.clean_text(div.get_text())
                        else:
                            # Strip leading digit from concatenated text
                            text = re.sub(r'^\d+\s*', '', li.get_text(strip=True))
                            text = self.clean_text(text)
                        if text:
                            steps.append(text)

        if not steps:
            logger.warning("No instructions found in %s", self.html_path)
            return None

        return ' '.join(steps)

    def extract_category(self) -> Optional[str]:
        """Extract recipe category from JSON-LD recipeCategory."""
        jld = self._get_json_ld()
        if jld and jld.get('recipeCategory'):
            return self.clean_text(jld['recipeCategory'])
        return None

    def _extract_time_from_html(self, label: str) -> Optional[str]:
        """Extract time text from the visible metadata box for a given label.

        Args:
            label: Portuguese label to look for, e.g. 'Preparo' or 'Cozimento'.

        Returns:
            Normalised time string like '15 minutes', or None.
        """
        h3 = self.soup.find('h3', string=lambda t: t and t.strip() == label)
        if not h3:
            return None
        parent = h3.find_parent()
        if not parent:
            return None
        # The value is in a <p> sibling inside the same box
        p = parent.find('p')
        if p:
            text = self.clean_text(p.get_text())
            return self._normalize_time_text(text) if text else None
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Extract preparation time."""
        # Prefer HTML text (can be a range like '27-30 minutos')
        time_text = self._extract_time_from_html('Preparo')
        if time_text:
            return time_text
        # Fallback to JSON-LD ISO duration
        jld = self._get_json_ld()
        if jld and jld.get('prepTime'):
            return self._parse_iso_duration(jld['prepTime'])
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Extract cooking time."""
        time_text = self._extract_time_from_html('Cozimento')
        if time_text:
            return time_text
        jld = self._get_json_ld()
        if jld and jld.get('cookTime'):
            return self._parse_iso_duration(jld['cookTime'])
        return None

    def extract_total_time(self) -> Optional[str]:
        """Extract total time from HTML, JSON-LD, or compute from prep+cook."""
        # 1. HTML box labelled 'Total'
        time_text = self._extract_time_from_html('Total')
        if time_text:
            return time_text

        # 2. JSON-LD totalTime
        jld = self._get_json_ld()
        if jld and jld.get('totalTime'):
            return self._parse_iso_duration(jld['totalTime'])

        # 3. Compute from prep + cook if both are simple integers
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        if prep and cook:
            p_match = re.match(r'^(\d+)\s+minutes$', prep)
            c_match = re.match(r'^(\d+)\s+minutes$', cook)
            if p_match and c_match:
                total = int(p_match.group(1)) + int(c_match.group(1))
                return f"{total} minutes"

        return None

    def extract_notes(self) -> Optional[str]:
        """Extract tips/notes from the 'Dicas para esta receita' section."""
        dicas_h3 = self.soup.find(
            'h3', string=lambda t: t and 'Dicas' in t
        )
        if not dicas_h3:
            return None

        parent = dicas_h3.find_parent()
        if not parent:
            return None

        ul = parent.find('ul')
        if not ul:
            return None

        items = [
            self.clean_text(li.get_text())
            for li in ul.find_all('li')
            if li.get_text(strip=True)
        ]
        return ' '.join(items) if items else None

    def extract_tags(self) -> Optional[str]:
        """Extract tags from the Tags section or JSON-LD keywords."""
        # 1. HTML Tags section (spans inside the div following the h3)
        tags_h3 = self.soup.find('h3', string=lambda t: t and t.strip() == 'Tags')
        if tags_h3:
            parent = tags_h3.find_parent()
            if parent:
                tag_div = parent.find('div')
                if tag_div:
                    tags = [
                        self.clean_text(span.get_text())
                        for span in tag_div.find_all('span')
                        if span.get_text(strip=True)
                    ]
                    if tags:
                        return ', '.join(tags)

        # 2. JSON-LD keywords
        jld = self._get_json_ld()
        if jld and jld.get('keywords'):
            return self.clean_text(jld['keywords'])

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Extract image URLs from og:image meta and JSON-LD."""
        urls: list[str] = []

        # 1. og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # 2. twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])

        # 3. JSON-LD image
        jld = self._get_json_ld()
        if jld and jld.get('image'):
            img = jld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                url = img.get('url') or img.get('contentUrl')
                if url:
                    urls.append(url)
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        url = item.get('url') or item.get('contentUrl')
                        if url:
                            urls.append(url)

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """Extract all recipe data and return as a dict."""
        try:
            dish_name = self.extract_dish_name()
        except Exception:
            logger.exception("Error extracting dish_name from %s", self.html_path)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception:
            logger.exception("Error extracting description from %s", self.html_path)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception:
            logger.exception("Error extracting ingredients from %s", self.html_path)
            ingredients = None

        try:
            instructions = self.extract_instructions()
        except Exception:
            logger.exception("Error extracting instructions from %s", self.html_path)
            instructions = None

        try:
            category = self.extract_category()
        except Exception:
            logger.exception("Error extracting category from %s", self.html_path)
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception:
            logger.exception("Error extracting prep_time from %s", self.html_path)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception:
            logger.exception("Error extracting cook_time from %s", self.html_path)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception:
            logger.exception("Error extracting total_time from %s", self.html_path)
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception:
            logger.exception("Error extracting notes from %s", self.html_path)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception:
            logger.exception("Error extracting tags from %s", self.html_path)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception:
            logger.exception("Error extracting image_urls from %s", self.html_path)
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
    """Process all HTML files in the geradorreceitas_com_br preprocessed directory."""
    import os

    recipes_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'preprocessed',
        'geradorreceitas_com_br',
    )
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(GeradorReceitasComBrExtractor, recipes_dir)
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python geradorreceitas_com_br.py [путь_к_директории]")


if __name__ == '__main__':
    main()
