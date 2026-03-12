"""
Экстрактор данных рецептов для сайта glutenfrihet.no
Сайт — WordPress-блог на норвежском языке с безглютеновыми рецептами.
"""

import logging
import sys
from pathlib import Path
import json
import re
from typing import Optional

from bs4 import NavigableString

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class GlutenfrihetNoExtractor(BaseRecipeExtractor):
    """Экстрактор для glutenfrihet.no"""

    # Norwegian measurement units (ordered from longest to shortest to avoid partial matches)
    _NO_UNITS = [
        'desiliter', 'liter',
        'klyper', 'klype',
        'pakker', 'pakke',
        'bokser', 'never',
        'skiver', 'glass',
        'stykker', 'neve',
        'boks', 'pk',
        'stk', 'dl', 'ml',
        'kg', 'ss', 'ts',
        'g', 'l',
    ]

    # Keywords indicating equipment section (to skip that ingredient list)
    _EQUIPMENT_KEYWORDS = {'utstyr', 'utstyr:', 'redskaper', 'redskaper:', 'equipment'}

    def _get_main_article(self):
        """Get the main article element for this page (excludes comment articles)."""
        articles = self.soup.find_all('article', id=re.compile(r'^post-\d+$'))
        if articles:
            return articles[0]
        return None

    def _get_recipe_content(self):
        """
        Find the entry-content div that contains the actual recipe.

        Some glutenfrihet.no pages embed an older recipe post (nested article)
        inside the current blog post.  When the nested article contains the
        "Du trenger" (ingredients) heading, that nested entry-content is returned.
        """
        main_article = self._get_main_article()
        if not main_article:
            return self.soup.find(class_='entry-content')

        entry = main_article.find(class_='entry-content')
        if not entry:
            return None

        # Check if there is a nested article with a "Du trenger" heading
        nested_articles = entry.find_all('article', id=re.compile(r'^post-\d+$'))
        for nested in nested_articles:
            nested_entry = nested.find(class_='entry-content')
            if nested_entry and self._find_section_start(nested_entry, ['du trenger', 'du trenger:']):
                return nested_entry

        return entry

    def _find_section_start(self, content, keywords: list):
        """
        Find the first tag that introduces a section identified by one of the keywords.

        Handles both heading tags (h2/h3) and paragraph-with-bold patterns
        (``<p><strong>Du trenger</strong></p>``) used on older posts.
        """
        for tag in content.find_all(['h1', 'h2', 'h3', 'h4', 'p']):
            tag_text = tag.get_text().strip().lower().rstrip(':')
            for keyword in keywords:
                if tag_text == keyword:
                    return tag
            # Paragraph whose only bold child matches the keyword
            if tag.name == 'p':
                strong = tag.find('strong')
                if strong:
                    strong_text = strong.get_text().strip().lower().rstrip(':')
                    for keyword in keywords:
                        if strong_text == keyword:
                            return tag
        return None

    # ------------------------------------------------------------------ #
    #  Public extraction methods                                           #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда."""
        # WordPress stores the post title in .entry-title
        entry_title = self.soup.find(class_='entry-title')
        if entry_title:
            name = self.clean_text(entry_title.get_text())
            if name:
                return name.title()

        # og:title (strip site suffix)
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*[–\-]\s*Glutenfrihet.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title).title()

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта из первого значимого абзаца."""
        content = self._get_recipe_content()
        if content:
            ingredients_start = self._find_section_start(content, ['du trenger', 'du trenger:'])
            for p in content.find_all('p'):
                if ingredients_start and p == ingredients_start:
                    break
                txt = p.get_text(strip=True)
                if txt and len(txt) > 30:
                    return self.clean_text(txt)

        # Fallback: og:description / meta description
        for attr, name in [('property', 'og:description'), ('name', 'description')]:
            meta = self.soup.find('meta', {attr: name})
            if meta and meta.get('content'):
                return self.clean_text(meta['content'])

        return None

    def parse_ingredient_no(self, text: str) -> Optional[dict]:
        """
        Разбирает строку норвежского ингредиента в структурированный формат.

        Примеры:
            "140 g glutenfri havregryn"  → {"name": "glutenfri havregryn", "amount": "140", "unit": "g"}
            "1-1,5 ts salt"              → {"name": "salt",  "amount": "1-1,5", "unit": "ts"}
            "2 modne bananer (ca. 250 g)"→ {"name": "modne bananer", "amount": "2", "unit": "stk"}
            "solsikkekjerner til pynt"   → {"name": "solsikkekjerner til pynt", "amount": None, "unit": None}
        """
        if not text:
            return None

        text = self.clean_text(text)

        # Replace Unicode fractions with ASCII equivalents
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
        }
        for frac, rep in fraction_map.items():
            text = text.replace(frac, rep)

        # Build units alternation (longest first to avoid partial matches)
        units_alt = '|'.join(re.escape(u) for u in self._NO_UNITS)

        # Pattern: amount [qualifier] unit name
        # Handles ranges ("1-1,5"), decimals with comma ("6,5"), fractions ("1/4")
        amount_pat = r'([\d,./][\d,./\s]*(?:-[\d,./\s]+)?)'
        qualifier_pat = r'(?:\s+(?:toppet|rause|gode|store|ca\.?|omtrent|halv|rund|godt))?'
        unit_pat = r'(' + units_alt + r')'
        name_pat = r'(.+)'

        full_pattern = r'^' + amount_pat + qualifier_pat + r'\s+' + unit_pat + r'\s+' + name_pat + r'$'

        match = re.match(full_pattern, text, re.IGNORECASE)
        if match:
            amount_str = match.group(1).strip()
            unit = match.group(2).strip()
            name = match.group(3).strip()
            # Normalise Norwegian decimal comma → period (e.g. "1,5" → "1.5")
            # but only if the comma is a decimal separator (not a thousands separator)
            amount_str = re.sub(r'(?<=\d),(?=\d)', '.', amount_str)
            # Remove parenthetical unit equivalents like "(ca. 250 g)", "(650 g)", "(ca 2,5 ts)"
            name = re.sub(
                r'\s*\((?:ca\.?\s*)?[\d,./\s]+\s*(?:g|kg|dl|ml|l|ts|ss|stk)\)',
                '', name
            )
            # Remove trailing asterisks (footnote markers)
            name = re.sub(r'\*+$', '', name).strip()
            name = re.sub(r',\s*$', '', name).strip()
            if name:
                return {"name": name, "amount": amount_str, "unit": unit}

        # Fallback: amount + name (no explicit unit → countable item → "stk")
        no_unit_pattern = r'^' + amount_pat + r'\s+' + name_pat + r'$'
        match2 = re.match(no_unit_pattern, text, re.IGNORECASE)
        if match2:
            amount_str = match2.group(1).strip()
            name = match2.group(2).strip()
            # Only use stk if amount is a small number (≤ 20)
            try:
                amt_val = float(amount_str.replace(',', '.').split('-')[0].split('/')[0])
                if amt_val <= 20:
                    name = re.sub(r'\s*\(ca\.?\s*[\d,./\s]+\s*(?:g|kg|dl|ml|l)\)', '', name)
                    name = re.sub(r'\*+$', '', name).strip()
                    name = re.sub(r',\s*$', '', name).strip()
                    if name:
                        return {"name": name, "amount": amount_str, "unit": "stk"}
            except ValueError:
                pass

        # No amount/unit found — just a name
        clean_name = re.sub(r'\*+$', '', text).strip()
        if clean_name:
            return {"name": clean_name, "amount": None, "unit": None}

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из секции «Du trenger»."""
        content = self._get_recipe_content()
        if not content:
            logger.warning("Recipe content not found in %s", self.html_path)
            return None

        start_tag = self._find_section_start(content, ['du trenger', 'du trenger:'])
        if not start_tag:
            logger.warning("'Du trenger' section not found in %s", self.html_path)
            return None

        ingredients: list = []
        skip_next_ul = False

        for sib in start_tag.next_siblings:
            if not hasattr(sib, 'name') or sib.name is None:
                continue

            # Stop at new major section heading
            if sib.name in ('h2', 'h3'):
                break

            # Stop at "Slik gjør du" bold paragraph
            if sib.name == 'p' and sib.find('strong'):
                strong_txt = sib.find('strong').get_text().strip().lower().rstrip(':')
                if 'slik gjør du' in strong_txt:
                    break

            # Detect equipment labels (skip the following <ul>)
            if sib.name == 'p':
                p_txt = sib.get_text().strip().lower().rstrip(':')
                if p_txt in self._EQUIPMENT_KEYWORDS:
                    skip_next_ul = True
                    continue

            if sib.name == 'ul':
                if skip_next_ul:
                    skip_next_ul = False
                    continue
                skip_next_ul = False  # reset for any subsequent ul

                for li in sib.find_all('li'):
                    raw = li.get_text(separator=' ', strip=True)
                    # Fix space-before-comma artefact produced by inline tags (e.g. <em>)
                    raw = re.sub(r'\s+,', ',', raw)
                    txt = self.clean_text(raw)
                    if txt:
                        parsed = self.parse_ingredient_no(txt)
                        if parsed:
                            ingredients.append(parsed)

        if not ingredients:
            logger.warning("No ingredients extracted from %s", self.html_path)
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления из секции «Slik gjør du»."""
        content = self._get_recipe_content()
        if not content:
            return None

        start_tag = self._find_section_start(content, ['slik gjør du', 'slik gjør du:'])
        if not start_tag:
            logger.warning("'Slik gjør du' section not found in %s", self.html_path)
            return None

        steps: list = []

        for sib in start_tag.next_siblings:
            # Handle plain text nodes (step text sometimes sits outside <p> tags)
            if isinstance(sib, NavigableString):
                txt = str(sib).strip()
                if txt and len(txt) > 5:
                    txt = self.clean_text(txt)
                    # Strip leading step number (e.g. "2. ")
                    txt = re.sub(r'^\d+\.\s*', '', txt)
                    if txt:
                        steps.append(txt)
                continue

            if not hasattr(sib, 'name') or sib.name is None:
                continue

            # Stop at new major section heading
            if sib.name in ('h2', 'h3'):
                break

            # Only process <p> tags (ignore <div> blocks like social sharing)
            if sib.name == 'p':
                txt = sib.get_text(strip=True)
                txt = self.clean_text(txt)
                if txt:
                    # Strip leading step number
                    txt = re.sub(r'^\d+\.\s*', '', txt)
                    if txt:
                        steps.append(txt)

        if not steps:
            logger.warning("No instructions extracted from %s", self.html_path)
            return None

        return ' '.join(steps)

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда."""
        # article:section meta tag
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])

        # <a rel="category tag"> links
        for a in self.soup.find_all('a', rel=re.compile(r'category')):
            txt = self.clean_text(a.get_text())
            if txt:
                return txt

        # article class attribute (category-*)
        main_article = self._get_main_article()
        if main_article:
            for cls in main_article.get('class', []):
                if cls.startswith('category-'):
                    cat = cls.replace('category-', '').replace('-', ' ')
                    return cat.title()

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта."""
        # Collect category texts to exclude them from tag list
        category_texts: set = set()
        for a in self.soup.find_all('a', rel=re.compile(r'category')):
            txt = self.clean_text(a.get_text())
            if txt:
                category_texts.add(txt.lower())

        tags: list = []
        seen: set = set()

        for a in self.soup.find_all('a', rel='tag'):
            txt = self.clean_text(a.get_text())
            if txt and txt.lower() not in category_texts:
                # Convert camelCase tag names to space-separated (e.g. "utenEgg" → "uten egg")
                normalized = re.sub(r'(?<=[a-zæøå])(?=[A-ZÆØÅ])', ' ', txt).lower()
                if normalized not in seen:
                    seen.add(normalized)
                    tags.append(normalized)

        # Fallback: article class (tag-*)
        if not tags:
            main_article = self._get_main_article()
            if main_article:
                for cls in main_article.get('class', []):
                    if cls.startswith('tag-'):
                        tag = cls.replace('tag-', '').replace('-', ' ')
                        if tag not in seen:
                            seen.add(tag)
                            tags.append(tag)

        return ', '.join(tags) if tags else None

    def _extract_time_from_instructions(self, time_type: str) -> Optional[str]:
        """Извлечение времени (prep / cook) из текста инструкций с помощью регулярных выражений."""
        instructions = self.extract_instructions()
        if not instructions:
            return None

        if time_type == 'cook':
            # Look for baking / frying / simmering time patterns
            patterns = [
                r'stek(?:e|es|t)?\s+(?:\w+\s+){0,4}i\s+(?:ca\.?\s+)?([\d,\s–\-]+)\s+minut',
                r'bak(?:e|es|t)?\s+(?:\w+\s+){0,4}i\s+(?:ca\.?\s+)?([\d,\s–\-]+)\s+minut',
                r'i\s+ovnen\s+i\s+(?:ca\.?\s+)?([\d,\s–\-]+)\s+minut',
            ]
        elif time_type == 'prep':
            # Look for resting / leavening / chilling time patterns
            patterns = [
                r'hev(?:e|ing)?\s+(?:\w+\s+){0,5}i\s+(?:ca\.?\s+)?([\d,\s–\-]+)\s+minut',
                r'sett\s+til\s+heving\s+(?:\w+\s+){0,5}i\s+(?:ca\.?\s+)?([\d,\s–\-]+)\s+minut',
            ]
        else:
            return None

        for pattern in patterns:
            match = re.search(pattern, instructions, re.IGNORECASE)
            if match:
                time_val = match.group(1).strip()
                # Normalise: collapse spaces around dashes / en-dashes
                time_val = re.sub(r'\s*[–]\s*', '-', time_val)
                time_val = time_val.strip()
                return f"{time_val} minutes"

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки."""
        return self._extract_time_from_instructions('prep')

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления."""
        return self._extract_time_from_instructions('cook')

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени."""
        return None  # glutenfrihet.no does not expose total time in structured form

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов (footnotes, allergiinfo, tips)."""
        content = self._get_recipe_content()
        if not content:
            return None

        notes_parts: list = []
        seen_texts: set = set()

        def _add_note(txt: str) -> None:
            txt = self.clean_text(txt)
            if txt and txt not in seen_texts:
                seen_texts.add(txt)
                notes_parts.append(txt)

        # 1. Footnote-style paragraphs that start with * (often allergy/substitution notes)
        for p in content.find_all('p'):
            raw = p.get_text(strip=True)
            if raw.startswith('*'):
                clean = re.sub(r'^\*+\s*', '', raw)
                # Remove embedded reference links (e.g. "**Jeg brukerTORO ...")
                clean = re.sub(r'\*\*.*', '', clean).strip()
                if clean:
                    _add_note(clean)

        # 2. "Allergiinfo" heading followed by a paragraph
        for tag in content.find_all(['p', 'h3', 'h4', 'strong']):
            if 'allergiinfo' in tag.get_text().lower():
                # Collect the next paragraph(s)
                for sib in tag.next_siblings:
                    if not hasattr(sib, 'name') or sib.name is None:
                        continue
                    if sib.name in ('h2', 'h3'):
                        break
                    if sib.name == 'p':
                        txt = sib.get_text(strip=True)
                        if txt and 'allergiinfo' not in txt.lower():
                            _add_note(txt)
                            break
                break

        return ' '.join(notes_parts) if notes_parts else None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из og:image и содержимого страницы."""
        urls: list = []
        seen: set = set()

        def _add_url(url: str) -> None:
            url = url.strip()
            if url and url not in seen and url.startswith('http'):
                seen.add(url)
                urls.append(url)

        # og:image (primary recipe photo)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            _add_url(og_image['content'])

        # Images inside the recipe entry-content
        content = self._get_recipe_content()
        if content:
            for img in content.find_all('img'):
                src = img.get('data-orig-file') or img.get('src', '')
                if src and 'glutenfrihet' in src:
                    _add_url(src)
                if len(urls) >= 3:
                    break

        return ','.join(urls) if urls else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            dict совместимый с JSON, содержащий поля рецепта.
        """
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_instructions(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags(),
        }


def main() -> None:
    """Обработать все HTML-файлы из директории preprocessed/glutenfrihet_no."""
    preprocessed_dir = Path(__file__).parent.parent / "preprocessed" / "glutenfrihet_no"
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        process_directory(GlutenfrihetNoExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python glutenfrihet_no.py")


if __name__ == "__main__":
    main()
