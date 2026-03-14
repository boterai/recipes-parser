"""
Экстрактор данных рецептов для сайта catine.ro
"""

import logging
import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class CatineRoExtractor(BaseRecipeExtractor):
    """Экстрактор для catine.ro"""

    # Romanian units for ingredient parsing
    _RO_UNITS = [
        r'linguri(?:ță|te|țe)?',  # linguriță, linguri, lingurițe
        r'legătur[ăi]',           # legătură, legături
        r'bucăț[iă]',             # bucăți, bucată
        r'pachete?',
        r'porț[iă]',              # porție, porții
        r'kg',
        r'gr?',                   # g, gr
        r'ml',
        r'litri?',                # litru, litri
        r'l\b',
        r'cl',
        r'dl',
        r'căni?',                 # cană, căni
        r'feli[ei]',              # felie, felii
        r'căpățân[ăi]',
        r'fire?',                 # fir, fire
        r'buc\.?',
        r'vârf(?:uri)?\s+de\s+cuțit',
    ]
    _RO_UNITS_PATTERN = '|'.join(_RO_UNITS)

    def _get_article_json_ld(self) -> Optional[dict]:
        """Извлечение данных Article из JSON-LD"""
        for script in self.soup.find_all('script', type='application/ld+json'):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Article':
                            return item
            except (json.JSONDecodeError, KeyError):
                continue
        return None

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из h1"""
        h1 = self.soup.find('h1', class_='ex-h1')
        if not h1:
            h1 = self.soup.find('h1')
        if h1:
            title = self.clean_text(h1.get_text())
            # Remove "rețetă de ..." subtitle if separated by colon
            # e.g. "Falafel: rețetă de chiftele libaneze din năut" → "Falafel"
            if ':' in title:
                title = title.split(':')[0].strip()
            return title if title else None

        # Fallback: og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = self.clean_text(og_title['content'])
            # Remove " - CaTine.ro" suffix
            title = re.sub(r'\s*-\s*CaTine\.ro\s*$', '', title, flags=re.IGNORECASE)
            if ':' in title:
                title = title.split(':')[0].strip()
            return title if title else None

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания из meta description"""
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def _parse_ro_ingredient(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента (румынский формат) в структурированный формат.

        Формат: [количество] [единица] [de/din/cu/...] [название]
        Пример: "250 gr boabe de năut" → {"name": "boabe de năut", "amount": "250", "unit": "gr"}

        Args:
            text: строка ингредиента

        Returns:
            dict {"name": ..., "amount": ..., "unit": ...} или None
        """
        if not text:
            return None

        # Normalize whitespace and non-breaking spaces
        text = re.sub(r'[\xa0\u200b]+', ' ', text)
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

        # Patterns for amount: digits, ranges (3-4), fractions (1/2), decimals (2.5)
        amount_pat = r'(\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?(?:\s+\d+/\d+)?|\d+/\d+|puțin[ăă]?|câteva|câțiva|după\s+gust|o\b)'
        units_pat = self._RO_UNITS_PATTERN

        # Main pattern: amount (optional) + unit (optional) + ["de"/"din"/"cu"] + name
        pattern = (
            r'^'
            r'(?:(' + amount_pat + r')\s+)?'   # optional amount
            r'(?:(' + units_pat + r')\s+)?'    # optional unit
            r'(?:(?:de|din|cu|la)\s+)?'        # optional Romanian preposition
            r'(.+)'                             # name
            r'$'
        )

        match = re.match(pattern, text, re.IGNORECASE | re.UNICODE)
        if not match:
            return {"name": text, "amount": None, "unit": None}

        amount_outer = match.group(1)   # the full amount capture from outer group
        unit = match.group(3)           # unit
        name = match.group(4)           # name

        # Clean up amount
        amount = None
        if amount_outer:
            amount = re.sub(r'\s+', '', amount_outer.strip())  # remove inner spaces
            # Normalize decimal comma
            amount = amount.replace(',', '.')

        # Clean up unit
        if unit:
            unit = unit.strip()

        # Clean up name
        if name:
            name = self.clean_text(name)
            # Remove trailing prepositions/connectors
            name = re.sub(r'\s+(și|sau|cu|de|din|la)\s*$', '', name, flags=re.IGNORECASE)
            name = name.strip()

        if not name or len(name) < 2:
            return None

        return {
            "name": name,
            "amount": amount,
            "unit": unit,
        }

    def _find_ingredients_section(self):
        """
        Finds the h2 element that marks the start of the ingredients section.
        Returns None if not found.
        """
        for h2 in self.soup.find_all('h2'):
            if re.search(r'ingrediente', h2.get_text(), re.IGNORECASE):
                return h2
        return None

    def _find_instructions_section(self):
        """
        Finds the h2 element that marks the start of the instructions section.
        Returns None if not found.
        """
        for h2 in self.soup.find_all('h2'):
            if re.search(r'mod\s+de\s+preparare|preparare|instruc', h2.get_text(), re.IGNORECASE):
                return h2
        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов.

        Ингредиенты расположены в ul.wp-block-list после h2 с "Ingrediente"
        и до h2 с "Mod de preparare".
        """
        h2_ing = self._find_ingredients_section()
        if not h2_ing:
            logger.warning("Не найден раздел ингредиентов на странице %s", self.html_path)
            return None

        h2_prep = self._find_instructions_section()

        # Collect all ul.wp-block-list between ingredients h2 and instructions h2
        ingredients = []
        current = h2_ing.find_next_sibling()

        while current:
            # Stop if we hit the instructions heading
            if current.name == 'h2':
                if h2_prep and current == h2_prep:
                    break
                # Any other h2 that looks like "Mod de preparare"
                if re.search(r'mod\s+de\s+preparare|preparare', current.get_text(), re.IGNORECASE):
                    break

            if current.name == 'ul':
                for li in current.find_all('li'):
                    raw = li.get_text(separator=' ', strip=True)
                    raw = re.sub(r'[\xa0\u200b]+', ' ', raw).strip()
                    if not raw:
                        continue
                    parsed = self._parse_ro_ingredient(raw)
                    if parsed:
                        ingredients.append(parsed)

            current = current.find_next_sibling()

        if not ingredients:
            logger.warning("Ингредиенты не найдены на странице %s", self.html_path)
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def _collect_paragraphs_from_section(self, start_h2, stop_patterns=None) -> list:
        """
        Collects all paragraph texts starting from a given h2 element,
        across multiple div.post-content blocks, until a stop condition is met.

        Args:
            start_h2: BeautifulSoup h2 element to start from
            stop_patterns: list of regex patterns for h3 text that stops collection

        Returns:
            list of paragraph text strings
        """
        if stop_patterns is None:
            stop_patterns = []

        paragraphs = []
        # We need to traverse siblings of start_h2 AND siblings in subsequent post-content divs

        # First: collect from siblings of start_h2 in its parent
        current = start_h2.find_next_sibling()
        collecting = True

        def _process_element(elem):
            """Returns (text, should_stop) where should_stop means stop collecting."""
            if elem.name == 'h2':
                return None, True  # Always stop at h2
            if elem.name == 'h3':
                text = elem.get_text(strip=True)
                for pat in stop_patterns:
                    if re.search(pat, text, re.IGNORECASE):
                        return None, True
            if elem.name == 'p':
                # Skip paragraphs with "related" content or navigation
                classes = elem.get('class', [])
                if any(c in ' '.join(classes) for c in ['related', 'advertisement', 'ad-']):
                    return None, False
                txt = self.clean_text(elem.get_text(separator=' ', strip=True))
                # Skip very short/promotional paragraphs
                if txt and len(txt) > 5:
                    # Skip "Spor și poftă bună!" and promotional teasers
                    if re.match(r'^(spor|citește|reclamă|publicitate|advertisement)', txt, re.IGNORECASE):
                        return None, False
                    return txt, False
            return None, False

        while current and collecting:
            txt, stop = _process_element(current)
            if stop:
                collecting = False
                break
            if txt:
                paragraphs.append(txt)
            current = current.find_next_sibling()

        if not collecting:
            return paragraphs

        # If we ran out of siblings, continue in subsequent post-content divs
        parent_div = start_h2.find_parent('div', class_='post-content')
        if not parent_div:
            return paragraphs

        # Find all post-content divs and get the ones after parent_div
        all_content_divs = self.soup.find_all('div', class_='post-content')
        found_parent = False
        for div in all_content_divs:
            if div == parent_div:
                found_parent = True
                continue
            if not found_parent:
                continue

            # Process children of this div
            for child in div.children:
                if not hasattr(child, 'name') or not child.name:
                    continue
                txt, stop = _process_element(child)
                if stop:
                    return paragraphs
                if txt:
                    paragraphs.append(txt)

        return paragraphs

    def extract_instructions(self) -> Optional[str]:
        """
        Извлечение инструкций по приготовлению.

        Инструкции расположены в p-элементах после h2 "Mod de preparare",
        могут распределяться по нескольким div.post-content блокам.
        """
        h2_prep = self._find_instructions_section()
        if not h2_prep:
            logger.warning("Не найден раздел инструкций на странице %s", self.html_path)
            return None

        # Stop notes sections from being included in instructions
        notes_stop_patterns = [
            r'cu\s+ce\s+poți\s+servi',
            r'sfat',
            r'sugestie',
            r'cum\s+se\s+servește',
            r'notă',
            r'recomand',
        ]

        paragraphs = self._collect_paragraphs_from_section(h2_prep, stop_patterns=notes_stop_patterns)

        # Also collect paragraphs from h3 sub-sections within instructions
        # (e.g. "Cum se prepară sosul bechamel", "Cum asamblezi și coci lasagna")
        all_h3s = h2_prep.find_all_next('h3')
        for h3 in all_h3s:
            h3_text = h3.get_text(strip=True)
            # Stop at notes-like h3
            stop = False
            for pat in notes_stop_patterns:
                if re.search(pat, h3_text, re.IGNORECASE):
                    stop = True
                    break
            if stop:
                break
            # Stop at next h2
            prev_h2 = h3.find_previous('h2')
            if prev_h2 and prev_h2 != h2_prep:
                break

        if not paragraphs:
            logger.warning("Инструкции не найдены на странице %s", self.html_path)
            return None

        return ' '.join(paragraphs)

    def extract_steps(self) -> Optional[str]:
        """Alias for extract_instructions (for compatibility with base pattern)"""
        return self.extract_instructions()

    def extract_category(self) -> Optional[str]:
        """
        Извлечение категории из хлебных крошек.

        Пример: "Home // Lifestyle // Rețete // Falafel..." → "Rețete"
        """
        # Try breadcrumbs div first
        breadcrumbs_div = self.soup.find('div', class_='breadcrumbs')
        if breadcrumbs_div:
            text = breadcrumbs_div.get_text()
            # Split by // or > separator
            parts = [p.strip() for p in re.split(r'\s*//\s*|\s*>\s*', text) if p.strip()]
            # Remove "Home" at start
            parts = [p for p in parts if p.lower() not in ('home', 'acasă', '')]
            # The category is the last item before the article title (second to last)
            if len(parts) >= 2:
                return self.clean_text(parts[-2])
            elif parts:
                return self.clean_text(parts[-1])

        # Fallback: JSON-LD BreadcrumbList
        for script in self.soup.find_all('script', type='application/ld+json'):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BreadcrumbList':
                            items = item.get('itemListElement', [])
                            # Category is the second-to-last item that has "item" URL
                            named_items = [i for i in items if 'name' in i and 'item' in i]
                            if named_items:
                                return self.clean_text(named_items[-1]['name'])
            except (json.JSONDecodeError, KeyError):
                continue

        # Fallback: articleSection from JSON-LD
        article = self._get_article_json_ld()
        if article:
            section = article.get('articleSection')
            if isinstance(section, list) and section:
                return self.clean_text(section[0])
            elif isinstance(section, str) and section:
                return self.clean_text(section)

        return None

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение дополнительных заметок/советов.

        Ищет h3-секции вида "Cu ce poți servi...", "Sfat", "Sugestie" и т.п.
        после раздела инструкций.
        """
        notes_h3_patterns = [
            r'cu\s+ce\s+poți\s+servi',
            r'sfat',
            r'sugestie',
            r'cum\s+se\s+servește',
            r'notă',
            r'recomand',
            r'mod\s+de\s+servire',
        ]

        h2_prep = self._find_instructions_section()
        if not h2_prep:
            return None

        # Collect all h3 elements that appear after h2_prep
        # and match one of our notes patterns
        notes_paragraphs = []

        all_h3s = h2_prep.find_all_next('h3')
        for h3 in all_h3s:
            h3_text = h3.get_text(strip=True)
            is_notes = False
            for pat in notes_h3_patterns:
                if re.search(pat, h3_text, re.IGNORECASE):
                    is_notes = True
                    break
            if not is_notes:
                continue

            # Check that this h3 is not within a cookie/GDPR banner
            if re.search(r'cookie|gdpr|parteneri|date\s+personale', h3_text, re.IGNORECASE):
                continue

            # Collect paragraphs after this h3
            current = h3.find_next_sibling()
            while current:
                if current.name in ['h2', 'h3']:
                    break
                if current.name == 'p':
                    txt = self.clean_text(current.get_text(separator=' ', strip=True))
                    if txt and len(txt) > 10:
                        if not re.match(r'^(spor|citește|reclamă)', txt, re.IGNORECASE):
                            notes_paragraphs.append(txt)
                current = current.find_next_sibling()

        if not notes_paragraphs:
            return None

        return ' '.join(notes_paragraphs)

    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов из JSON-LD Article keywords.
        """
        article = self._get_article_json_ld()
        if article:
            keywords = article.get('keywords')
            if isinstance(keywords, list) and keywords:
                return ','.join(k.strip() for k in keywords if k.strip())
            elif isinstance(keywords, str) and keywords:
                return keywords.strip()

        # Fallback: meta keywords
        meta_kw = self.soup.find('meta', {'name': 'keywords'})
        if meta_kw and meta_kw.get('content'):
            return self.clean_text(meta_kw['content'])

        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Извлечение URL изображений.

        Источники:
        1. og:image (главное изображение)
        2. figure.wp-block-image img в div.post-content
        3. thumbnailUrl из JSON-LD
        """
        urls = []

        # 1. og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content'].strip()
            if url:
                urls.append(url)

        # 2. Images in post-content figures
        _placeholder_patterns = re.compile(
            r'placeholder|lazy_placeholder|blank\.gif|spacer\.gif|data:image',
            re.IGNORECASE,
        )
        for div in self.soup.find_all('div', class_='post-content'):
            for figure in div.find_all('figure', class_=re.compile(r'wp-block-image')):
                img = figure.find('img')
                if img:
                    src = (
                        img.get('data-src') or
                        img.get('data-lazy-src') or
                        img.get('data-orig-file') or
                        img.get('src')
                    )
                    if (
                        src
                        and src.startswith('http')
                        and not _placeholder_patterns.search(src)
                        and src not in urls
                    ):
                        urls.append(src)

        # 3. thumbnailUrl from JSON-LD (Article)
        article = self._get_article_json_ld()
        if article:
            thumb = article.get('thumbnailUrl')
            if thumb and isinstance(thumb, str) and thumb not in urls:
                urls.append(thumb)

        # Deduplicate preserving order
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ','.join(unique_urls) if unique_urls else None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки (недоступно из структурированных данных)."""
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления (недоступно из структурированных данных)."""
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени (недоступно из структурированных данных)."""
        return None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()

        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": self.extract_image_urls(),
        }


def main():
    import os
    recipes_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "preprocessed",
        "catine_ro",
    )
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(CatineRoExtractor, recipes_dir)
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python catine_ro.py")


if __name__ == "__main__":
    main()
