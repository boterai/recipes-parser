"""
Екстрактор даних рецептів для сайту zmorshki.in.ua
"""

import logging
import os
import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

BASE_URL = "https://zmorshki.in.ua"

# Ukrainian/Russian cooking units (ordered from longer to shorter to avoid partial matches)
_UA_UNITS_PATTERN = (
    r'(?:'
    r'ст\.?\s*ложок'                            # ст. ложок
    r'|ст\.?\s*ложк(?:и|а|у|ою|ах)?\.?'        # ст. ложки / ст.ложка
    r'|ч\.?\s*ложк(?:и|а|у|ою|ах|ок)?\.?'      # ч. ложки / ч.ложка / ч. ложок
    r'|ст\.?\s*л\.?'                             # ст. л.
    r'|ч\.?\s*л\.?'                              # ч. л.
    r'|столов(?:ої|а|у|ою)?\s*ложк(?:и|а|у|ою|ок)?'
    r'|чайн(?:ої|а|у|ою)?\s*ложк(?:и|а|у|ою|ок)?'
    r'|склян(?:ки|ка|ку|кою|ках)?\.?'            # склянки / склянка
    r'|пакетик(?:ів|а)?\.?'                      # пакетик
    r'|зубчик(?:ів|а|и)?\.?'                     # зубчики
    r'|пучк(?:а|ів)?\.?'                         # пучок / пучка
    r'|кусочк(?:ів|а|ек)?\.?'                    # кусочок
    r'|ломтик(?:ів|а)?\.?'                       # ломтик
    r'|щіпк(?:а|и|у|ою)?\.?'                     # щіпка
    r'|щепотк(?:и|у|а)?\.?'                      # щепотка
    r'|цибулин(?:а|и|ою)?\.?'                    # цибулина
    r'|гілочк(?:и|а|у|ою)?\.?'                   # гілочка
    r'|шт\.?'                                     # шт.
    r'|кг\.?'                                     # кг
    r'|гр?\.?'                                    # г / гр.
    r'|р\.?'                                      # р. (informal Ukrainian for гр.)
    r'|мл\.?'                                     # мл
    r'|л(?=\s|$|[.,;])'                           # л (litre) — only before space/end/punctuation
    r')'
)

# Numeric amount pattern: integer, decimal, fraction, range
_AMOUNT_PATTERN = r'(?:\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?(?:\s*/\s*\d+)?)'

# Combined amount+unit pattern (amount first, unit optional)
_AMOUNT_UNIT_RE = re.compile(
    r'^(' + _AMOUNT_PATTERN + r')\s*(' + _UA_UNITS_PATTERN + r')?\s*(.*)',
    re.IGNORECASE | re.DOTALL,
)

# Pattern for "Name – amount unit" or "Name — amount unit" (dash-separated)
_DASH_RE = re.compile(r'^(.+?)\s*[–—]\s*(.+)$', re.DOTALL)

# Keywords that precede ingredient lists
_INGR_KEYWORDS = re.compile(
    r'(?:інгредієнти|нам\s+знадобиться|знадобиться|склад|для\s+(?:тіста|начинки|соусу))',
    re.IGNORECASE,
)

# Keywords that precede instruction steps
_STEP_KEYWORDS = re.compile(
    r'(?:спосіб\s+приготування|як\s+(?:зробити|приготувати|готувати)|рецепт\s+(?:білого\s+)?соусу|приготування)',
    re.IGNORECASE,
)


class ZmorshkiInUaExtractor(BaseRecipeExtractor):
    """Екстрактор для zmorshki.in.ua"""

    # ------------------------------------------------------------------ #
    #  Допоміжні методи                                                    #
    # ------------------------------------------------------------------ #

    def _get_entry_content(self):
        """Повертає основний блок контенту статті."""
        return self.soup.find('div', class_='entry-content')

    @staticmethod
    def _normalize_unit(unit: Optional[str]) -> Optional[str]:
        """Нормалізує одиницю виміру (видаляє зайві крапки, пробіли)."""
        if not unit:
            return None
        return unit.strip().rstrip('.')

    @staticmethod
    def _parse_ingredient_line(text: str) -> Optional[Dict[str, Any]]:
        """
        Парсить рядок з інгредієнтом у словник {name, amount, unit}.

        Підтримувані формати:
        - Format A: "name amount unit"     — напр. «борошно 400 р.»
        - Format B: "amount unit name"     — напр. «250 гр. сиру моцарелла»
        - Format C: "Name – amount unit"   — напр. «Майонез – 4 ст. л.»
        """
        text = text.strip().rstrip(';').strip()
        if not text:
            return None

        # Format C: "Name – amount unit" (dash/em-dash separator)
        dash_match = _DASH_RE.match(text)
        if dash_match:
            name_part = dash_match.group(1).strip()
            rest = dash_match.group(2).strip()
            # Parse amount+unit from rest
            m = _AMOUNT_UNIT_RE.match(rest)
            if m:
                amount = m.group(1).strip() if m.group(1) else rest
                unit = ZmorshkiInUaExtractor._normalize_unit(m.group(2))
                tail = m.group(3).strip() if m.group(3) else ''
                if tail:
                    name_part = f"{name_part} {tail}"
            else:
                amount = rest
                unit = None
            return {'name': name_part, 'amount': amount, 'unit': unit}

        # Format B: starts with a digit → "amount unit name"
        if re.match(r'^\d', text):
            m = _AMOUNT_UNIT_RE.match(text)
            if m:
                amount = m.group(1).strip()
                unit = ZmorshkiInUaExtractor._normalize_unit(m.group(2))
                name = m.group(3).strip() if m.group(3) else ''
                if name:
                    return {'name': name, 'amount': amount, 'unit': unit}
            # If no unit matched, treat the whole thing as name
            return {'name': text, 'amount': None, 'unit': None}

        # Format A: "name amount unit" — name comes first, number somewhere inside
        # Try to split at the last occurrence of a number followed by optional unit
        amount_unit_re = re.compile(
            r'(\s+)(' + _AMOUNT_PATTERN + r')(\s*' + _UA_UNITS_PATTERN + r')?\s*$',
            re.IGNORECASE,
        )
        m = amount_unit_re.search(text)
        if m:
            name = text[:m.start()].strip()
            amount = m.group(2).strip()
            unit = ZmorshkiInUaExtractor._normalize_unit(m.group(3))
            return {'name': name, 'amount': amount, 'unit': unit}

        # No number found — treat entire text as name with null amount/unit
        return {'name': text, 'amount': None, 'unit': None}

    # ------------------------------------------------------------------ #
    #  Методи витягу даних                                                 #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Витягує назву страви."""
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            return self.clean_text(h1.get_text())

        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        return None

    def extract_description(self) -> Optional[str]:
        """Витягує опис рецепту."""
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Витягує список інгредієнтів з усіх розділів рецепту."""
        content = self._get_entry_content()
        if not content:
            logger.warning("entry-content не знайдено в %s", self.html_path)
            return None

        ingredients: List[Dict[str, Any]] = []
        seen_names: set = set()

        try:
            elements = content.find_all(['p', 'h2', 'h3', 'ul', 'ol'])
            prev_is_ingr_keyword = False

            for elem in elements:
                # Skip table of contents
                if 'table-of-contents' in ' '.join(elem.get('class') or []):
                    prev_is_ingr_keyword = False
                    continue

                text = elem.get_text(separator=' ', strip=True)

                if elem.name in ('p', 'h2', 'h3'):
                    prev_is_ingr_keyword = bool(_INGR_KEYWORDS.search(text))
                    continue

                if elem.name in ('ul', 'ol') and prev_is_ingr_keyword:
                    for li in elem.find_all('li', recursive=False):
                        li_text = self.clean_text(li.get_text(separator=' ', strip=True))
                        if not li_text:
                            continue
                        parsed = self._parse_ingredient_line(li_text)
                        if parsed and parsed.get('name'):
                            key = parsed['name'].lower().strip()
                            if key not in seen_names:
                                seen_names.add(key)
                                ingredients.append(parsed)
                    prev_is_ingr_keyword = False
                    continue

                prev_is_ingr_keyword = False

        except Exception as exc:
            logger.warning("Помилка при витягу інгредієнтів з %s: %s", self.html_path, exc)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_instructions(self) -> Optional[str]:
        """Витягує інструкції з приготування."""
        content = self._get_entry_content()
        if not content:
            return None

        steps: List[str] = []
        notes_buf: List[str] = []
        section_idx = 0

        try:
            elements = content.find_all(['p', 'h2', 'h3', 'ul', 'ol'])
            prev_is_step_keyword = False
            current_section_title = ''

            for elem in elements:
                if 'table-of-contents' in ' '.join(elem.get('class') or []):
                    prev_is_step_keyword = False
                    continue

                text = elem.get_text(separator=' ', strip=True)

                if elem.name == 'h2':
                    current_section_title = self.clean_text(text)
                    prev_is_step_keyword = False
                    continue

                if elem.name in ('p', 'h3'):
                    prev_is_step_keyword = bool(_STEP_KEYWORDS.search(text))
                    continue

                if elem.name in ('ul', 'ol') and prev_is_step_keyword:
                    section_idx += 1
                    section_steps = []
                    for li in elem.find_all('li', recursive=False):
                        li_text = self.clean_text(li.get_text(separator=' ', strip=True))
                        if not li_text:
                            continue
                        # Separate notes (tips) from actual steps
                        if re.match(r'^порад[аи]?:', li_text, re.IGNORECASE):
                            notes_buf.append(re.sub(r'^порад[аи]?:\s*', '', li_text, flags=re.IGNORECASE).strip())
                        else:
                            section_steps.append(li_text)
                    if section_steps:
                        # Format: "N. SectionTitle: step1 step2 step3"
                        header = f"{section_idx}. "
                        if current_section_title:
                            header += f"{current_section_title}: "
                        section_text = ' '.join(section_steps)
                        steps.append(f"{header}{section_text}")
                    prev_is_step_keyword = False
                    continue

                prev_is_step_keyword = False

        except Exception as exc:
            logger.warning("Помилка при витягу інструкцій з %s: %s", self.html_path, exc)

        # Store collected notes for later retrieval via extract_notes()
        self._notes_buf = notes_buf

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Витягує категорію рецепту з хлібних крихт або мета-тегів."""
        breadcrumb = self.soup.find(class_='breadcrumb')
        if breadcrumb:
            items = breadcrumb.find_all('span', class_='breadcrumb-item')
            # Last item is usually the category (skip "Головна")
            for item in reversed(items):
                cat_text = item.get_text(strip=True)
                if cat_text and cat_text.lower() not in ('головна', 'home'):
                    return self.clean_text(cat_text)

        # Fallback: og:section or article:section
        for prop in ('article:section', 'og:type'):
            meta = self.soup.find('meta', property=prop)
            if meta and meta.get('content'):
                return self.clean_text(meta['content'])

        return None

    def extract_notes(self) -> Optional[str]:
        """Витягує нотатки/поради до рецепту."""
        notes: List[str] = list(getattr(self, '_notes_buf', []))

        # Also scan paragraphs for standalone "Порада:" text
        content = self._get_entry_content()
        if content:
            for p in content.find_all('p'):
                text = self.clean_text(p.get_text(separator=' ', strip=True))
                if re.match(r'^порад[аи]?:', text, re.IGNORECASE):
                    note_text = re.sub(r'^порад[аи]?:\s*', '', text, flags=re.IGNORECASE).strip()
                    if note_text and note_text not in notes:
                        notes.append(note_text)

        return ' '.join(notes) if notes else None

    def extract_tags(self) -> Optional[str]:
        """Витягує теги рецепту."""
        # Try rel="tag" links
        tag_links = self.soup.find_all('a', rel='tag')
        if tag_links:
            tags = [self.clean_text(a.get_text()) for a in tag_links if a.get_text(strip=True)]
            if tags:
                return ', '.join(tags)

        # Try meta keywords
        meta_kw = self.soup.find('meta', {'name': 'keywords'})
        if meta_kw and meta_kw.get('content'):
            return self.clean_text(meta_kw['content'])

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Витягує URL зображень рецепту."""
        content = self._get_entry_content()
        if not content:
            return None

        urls: List[str] = []
        seen: set = set()

        for img in content.find_all('img'):
            # Try data-src first (lazy-load), then src
            src = (
                img.get('data-src')
                or img.get('data-lazy-src')
                or img.get('src', '')
            )
            if not src or 'data:image' in src:
                continue
            # Skip icons/logos (very small or svg)
            if src.endswith('.svg'):
                continue
            # Prepend base URL for relative paths
            if src.startswith('/'):
                src = BASE_URL + src
            if src in seen:
                continue
            seen.add(src)
            # Only include content images (from wp-content/uploads)
            if '/wp-content/uploads/' in src:
                urls.append(src)

        return ','.join(urls) if urls else None

    def extract_prep_time(self) -> Optional[str]:
        """Витягує час підготовки (на zmorshki.in.ua зазвичай відсутній)."""
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Витягує час готування (на zmorshki.in.ua зазвичай відсутній)."""
        return None

    def extract_total_time(self) -> Optional[str]:
        """Витягує загальний час приготування (на zmorshki.in.ua зазвичай відсутній)."""
        return None

    # ------------------------------------------------------------------ #
    #  Основний метод                                                       #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """Витягує всі дані рецепту та повертає словник."""
        # extract_instructions() populates _notes_buf used by extract_notes()
        instructions = self.extract_instructions()

        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": instructions,
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags(),
        }


def main() -> None:
    """Точка входу для обробки директорії з HTML-файлами."""
    preprocessed_dir = os.path.join("preprocessed", "zmorshki_in_ua")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ZmorshkiInUaExtractor, preprocessed_dir)
        return

    print(f"Директорія не знайдена: {preprocessed_dir}")
    print("Використання: python zmorshki_in_ua.py")


if __name__ == "__main__":
    main()
