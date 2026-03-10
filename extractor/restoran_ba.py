"""
Экстрактор данных рецептов для сайта restoran.ba
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

# Bosnian/Croatian measurement units
_BOSNIAN_UNITS = (
    r'kg|kilogram[ai]?|kilograma?'
    r'|dag|dekagram[ai]?'
    r'|g|gram[ai]?|grama'
    r'|ml|mililitr[ai]?|mililitara?'
    r'|dl|decilitr[ai]?|decilitara?'
    r'|cl|centilitr[ai]?'
    r'|l|litr[ai]?|litre?'
    r'|kašika|kašike?|kašiku'
    r'|kašičica|kašičice?|kašičicu'
    r'|šolja|šolje?|šolju'
    r'|šalica|šalice?'
    r'|kom(?:ad(?:a)?)?'
    r'|čen|čena'
    r'|vezica|vezice?'
    r'|pakovanje|pakety?'
    r'|paketic[ae]?|paket[ai]?'
    r'|kriška|kriške?'
    r'|grančica|grančice?'
    r'|list[ai]?|listić[ai]?'
    r'|konzerv[ae]?'
    r'|kap(?:i)?'
    r'|vrećica|vrećice?'
    r'|šaka|šake'
    r'|zrno|zrna'
    r'|glavica|glavice?'
)

_UNIT_RE = re.compile(
    r'^(' + _BOSNIAN_UNITS + r')\b',
    re.IGNORECASE,
)

_AMOUNT_RE = re.compile(
    r'^(\d+(?:[.,]\d+)?(?:\s+do\s+\d+(?:[.,]\d+)?)?(?:\s+\d+/\d+)?|\d+/\d+)',
    re.IGNORECASE,
)

# Sections that indicate ingredients
_INGREDIENTS_SECTIONS = re.compile(r'sastojc', re.IGNORECASE)

# Sections that indicate instructions/preparation
_INSTRUCTIONS_SECTIONS = re.compile(
    r'(priprema|postupak|kuhanje|pečenje)',
    re.IGNORECASE,
)

# Sections that indicate notes/tips
_NOTES_SECTIONS = re.compile(
    r'(savjet|napomen|posluživanj|zanimljivost|završni koraci|završna)',
    re.IGNORECASE,
)


class RestoranBaExtractor(BaseRecipeExtractor):
    """Экстрактор для restoran.ba"""

    # ------------------------------------------------------------------ #
    # Internal helpers                                                      #
    # ------------------------------------------------------------------ #

    def _get_content_block(self):
        """Return the main article body element."""
        # Primary selector: inner block of the single post content module
        single_content = self.soup.find(
            'div', class_=re.compile(r'tdb_single_content', re.I)
        )
        if single_content:
            inner = single_content.find('div', class_='tdb-block-inner')
            if inner:
                return inner

        # Fallback: look for any tdb-block-inner that contains recipe headings
        for block in self.soup.find_all('div', class_='tdb-block-inner'):
            text = block.get_text()
            if re.search(r'\bSastojc', text, re.I) or re.search(r'\bPriprema\b', text, re.I):
                return block

        # Last resort: use the article element
        return self.soup.find('article')

    def _get_sections(self):
        """
        Parse the content block into a list of (heading_text, elements) pairs.

        Each pair contains the h2/h3 heading text and the list of direct
        sibling elements until the next heading.
        """
        block = self._get_content_block()
        if not block:
            return []

        sections = []
        current_heading = None
        current_elements = []

        for child in block.children:
            name = getattr(child, 'name', None)
            if not name:
                continue
            if name in ('h2', 'h3'):
                if current_heading is not None or current_elements:
                    sections.append((current_heading, current_elements))
                current_heading = child.get_text(strip=True)
                current_elements = []
            else:
                current_elements.append(child)

        # Append the last section
        if current_heading is not None or current_elements:
            sections.append((current_heading, current_elements))

        return sections

    def _get_json_ld_blog_posting(self) -> Optional[dict]:
        """Return the BlogPosting JSON-LD entry, if any."""
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                graph = data.get('@graph', [data] if isinstance(data, dict) else [])
                for item in graph:
                    if isinstance(item, dict) and item.get('@type') in (
                        'BlogPosting', 'Article', 'NewsArticle'
                    ):
                        return item
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    # ------------------------------------------------------------------ #
    # Ingredient parsing                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_ingredient_line(raw: str) -> Optional[dict]:
        """
        Parse a single ingredient line (Bosnian/Croatian) into
        {"name": str, "amount": str|int|float|None, "unit": str|None}.

        Supported formats (first token is amount or unit-word or plain name):
          "6 glavica luka"         → amount=6, unit=None, name="glavica luka"
          "55 g maslaca"           → amount=55, unit="g", name="maslaca"
          "prstohvat muškatnog..." → amount="prstohvat", unit=None, name="muškatnog..."
          "sol"                    → amount=None, unit=None, name="sol"
        """
        text = raw.strip()
        text = re.sub(r'^[•·\-–—*]+\s*', '', text)
        text = re.sub(r'[,.]$', '', text).strip()
        if not text:
            return None

        amount: Optional[object] = None
        unit: Optional[str] = None
        name: str = text

        # ---- Case 1: starts with a number --------------------------------
        m_amount = _AMOUNT_RE.match(text)
        if m_amount:
            amount_raw = m_amount.group(1)
            remainder = text[m_amount.end():].strip()

            # Check if next token is a known unit
            m_unit = _UNIT_RE.match(remainder)
            if m_unit:
                unit = m_unit.group(1)
                name = remainder[m_unit.end():].strip()
            else:
                name = remainder

            # Normalise amount string to a number when possible
            amount_str = amount_raw.strip()
            range_m = re.match(
                r'(\d+(?:[.,]\d+)?)\s+do\s+(\d+(?:[.,]\d+)?)', amount_str
            )
            if range_m:
                amount_str = range_m.group(2).replace(',', '.')
            else:
                amount_str = amount_str.replace(',', '.')

            try:
                float_val = float(amount_str)
                amount = int(float_val) if float_val == int(float_val) else float_val
            except ValueError:
                amount = amount_str

        # ---- Case 2: no leading number – may start with a word like
        #              "prstohvat" or a plain ingredient name ---------------
        else:
            # Check if the first word is a known unit
            m_unit_first = _UNIT_RE.match(text)
            if m_unit_first:
                unit = m_unit_first.group(1)
                name = text[m_unit_first.end():].strip()
            else:
                # Check for non-standard amounts like "prstohvat", "po ukusu"
                non_num_amount = re.match(
                    r'^(prstohvat|po\s+ukusu|malo|po\s+želji|po\s+potrebi)\s+(.+)',
                    text,
                    re.IGNORECASE,
                )
                if non_num_amount:
                    amount = non_num_amount.group(1)
                    name = non_num_amount.group(2).strip()
                # else: amount=None, unit=None, name=text (already set)

        # Clean up name
        name = re.sub(r'\(\s*\d+\s*[a-zA-Z]+\s*\)', '', name).strip()
        name = re.sub(r'[,.]$', '', name).strip()

        if not name:
            return None

        return {"name": name, "amount": amount, "unit": unit}

    # ------------------------------------------------------------------ #
    # Public extraction methods                                             #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Primary: h1 in the main article header
        block = self._get_content_block()
        if block:
            h1 = block.find('h1')
            if h1:
                return self.clean_text(h1.get_text())

        # Fallback: page-level h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        # Last resort: og:title without site suffix
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*[:\-–|]\s*(?:Restoran\.ba|recept.*)$', '', title, flags=re.I)
            return self.clean_text(title)

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта (первый абзац после вводного заголовка)"""
        sections = self._get_sections()
        for heading, elements in sections:
            if heading is None:
                continue
            # Skip ingredient/instruction sections
            if _INGREDIENTS_SECTIONS.search(heading) or _INSTRUCTIONS_SECTIONS.search(heading):
                continue
            # Take first paragraph from intro-like or first section
            for el in elements:
                if getattr(el, 'name', None) == 'p':
                    text = self.clean_text(el.get_text())
                    if text:
                        return text
            # Only use the very first section for description
            break

        # Fallback: meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из всех секций 'Sastojci'"""
        sections = self._get_sections()
        ingredients = []

        for heading, elements in sections:
            if heading is None or not _INGREDIENTS_SECTIONS.search(heading):
                continue

            for el in elements:
                if getattr(el, 'name', None) != 'ul':
                    continue
                for li in el.find_all('li'):
                    raw = self.clean_text(li.get_text())
                    if not raw:
                        continue
                    parsed = self._parse_ingredient_line(raw)
                    if parsed:
                        ingredients.append(parsed)

        if not ingredients:
            logger.warning("No ingredients found in %s", self.html_path)
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления из всех секций 'Priprema'"""
        sections = self._get_sections()
        steps = []

        for heading, elements in sections:
            if heading is None or not _INSTRUCTIONS_SECTIONS.search(heading):
                continue

            for el in elements:
                tag = getattr(el, 'name', None)
                if tag == 'ol':
                    for li in el.find_all('li'):
                        text = self.clean_text(li.get_text())
                        if text:
                            steps.append(text)
                elif tag == 'ul':
                    for li in el.find_all('li'):
                        text = self.clean_text(li.get_text())
                        if text:
                            steps.append(text)
                elif tag == 'p':
                    text = self.clean_text(el.get_text())
                    if text:
                        steps.append(text)

        if not steps:
            logger.warning("No instructions found in %s", self.html_path)
            return None

        # Add numbering if not already present
        if steps and not re.match(r'^\d+\.', steps[0]):
            steps = [f"{i}. {s}" for i, s in enumerate(steps, 1)]

        return ' '.join(steps)

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из JSON-LD articleSection"""
        blog_posting = self._get_json_ld_blog_posting()
        if blog_posting:
            section = blog_posting.get('articleSection', '')
            if section:
                # "Recepti, Slana jela" → "Slana jela"
                parts = [p.strip() for p in section.split(',')]
                # Return the most specific (last non-empty, non-generic) part
                filtered = [p for p in parts if p.lower() not in ('recepti', 'recipes')]
                if filtered:
                    return self.clean_text(filtered[-1])
                if parts:
                    return self.clean_text(parts[-1])

        # Fallback: breadcrumb – last category link before current page
        breadcrumb = self.soup.find(
            'nav', attrs={'aria-label': re.compile(r'breadcrumb', re.I)}
        ) or self.soup.find('div', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumb:
            links = breadcrumb.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки – не структурировано в HTML restoran.ba"""
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Время приготовления – не структурировано в HTML restoran.ba"""
        return None

    def extract_total_time(self) -> Optional[str]:
        """Общее время – не структурировано в HTML restoran.ba"""
        return None

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок/советов из секций советов или финальной секции.

        Приоритет: секции с 'Savjet', 'Napomene', 'posluživanj', 'Završni koraci'
        Запасной вариант: секция 'Završna rijec'
        """
        sections = self._get_sections()
        fallback_text = None

        for heading, elements in sections:
            if heading is None:
                continue

            # Skip ingredient/instruction sections
            if _INGREDIENTS_SECTIONS.search(heading) or _INSTRUCTIONS_SECTIONS.search(heading):
                continue

            is_notes = _NOTES_SECTIONS.search(heading)
            texts = []
            for el in elements:
                if getattr(el, 'name', None) in ('p', 'ul', 'ol'):
                    t = self.clean_text(el.get_text(separator=' '))
                    if t:
                        texts.append(t)

            if not texts:
                continue

            combined = ' '.join(texts)

            if is_notes:
                # Primary notes section – return immediately
                if 'završna' in heading.lower():
                    # "Završna riječ" is a fallback, not primary
                    fallback_text = combined
                else:
                    return combined

            elif 'završna' in heading.lower():
                fallback_text = combined

        return fallback_text

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords"""
        blog_posting = self._get_json_ld_blog_posting()
        if blog_posting:
            kw = blog_posting.get('keywords', '')
            if kw:
                return self.clean_text(kw)

        # Fallback: meta keywords
        meta_kw = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_kw and meta_kw.get('content'):
            return self.clean_text(meta_kw['content'])

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls = []

        # Primary: og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # Featured image in the page
        featured_div = self.soup.find(
            'div', class_=re.compile(r'tdb_single_featured_image', re.I)
        )
        if featured_div:
            for img in featured_div.find_all('img'):
                src = (
                    img.get('src')
                    or img.get('data-src')
                    or img.get('data-lazy-src')
                )
                if src and src not in urls:
                    urls.append(src)

        # Deduplicate
        seen = set()
        unique = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта

        Returns:
            Словарь с данными рецепта в едином формате проекта
        """
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_steps(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags(),
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "restoran_ba")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(RestoranBaExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python restoran_ba.py")


if __name__ == "__main__":
    main()
