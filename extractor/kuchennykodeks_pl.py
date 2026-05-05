"""
Экстрактор данных рецептов для сайта kuchennykodeks.pl
"""

import logging
import sys
import json
import re
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Polish unit vocabulary (matches forms used on the site)
# ---------------------------------------------------------------------------
_POLISH_UNITS_LIST = [
    # metric weight/volume
    'kg', 'dag', 'g', 'ml', 'dl', 'l',
    # spoons – longest first to avoid partial matches
    'łyżka stołowa', 'łyżki stołowe', 'łyżek stołowych',
    'łyżeczka', 'łyżeczki', 'łyżeczek',
    'łyżka', 'łyżki', 'łyżek',
    # cups
    'szklanka', 'szklanki', 'szklanek',
    # handfuls
    'garść', 'garście', 'garści',
    # pieces / sheets / slices
    'płatów', 'płaty', 'płat',
    'plastrów', 'plastry', 'plaster',
    'pęczków', 'pęczki', 'pęczek',
    'kawałków', 'kawałki', 'kawałek',
    'liści', 'liście', 'liść',
    # cans / packages
    'puszek', 'puszki', 'puszka',
    'opakowań', 'opakowania', 'opakowanie', 'opak.',
    # countable abbreviation
    'szt.', 'szt',
]

# Build a single regex that matches any known unit (word-boundary aware).
# Units with spaces need special treatment – handled in parser logic.
_UNITS_RE = re.compile(
    r'\b(' + '|'.join(re.escape(u) for u in _POLISH_UNITS_LIST) + r')\b',
    re.IGNORECASE | re.UNICODE,
)

# Quantity words that represent an amount without a numeric value
_WORD_AMOUNTS = {
    'szczypta', 'szczyptę', 'szczyptą',
    'kilka', 'pare', 'parę',
    'trochę', 'trochę', 'odrobina', 'odrobinę',
    'do smaku', 'do podania', 'wg uznania', 'według uznania',
}

# Suffixes to strip from ingredient names
_STRIP_SUFFIXES_RE = re.compile(
    r'\b(do smaku|do podania|wg\.?\s*uznania|wed[łl]ug uznania|opcjonalnie|'
    r'lub wi[eę]cej|je[sś]li potrzeba|wedle uznania)\b.*$',
    re.IGNORECASE | re.UNICODE,
)

# Polish time patterns: "X minut(y/ę)", "X godzin(y)", "ok./około X minut"
_TIME_RE = re.compile(
    r'(?:ok\.?|oko[łl]o|minimum|mniej\s+wi[eę]cej|przez|po)\s*'
    r'(\d+(?:[.,]\d+)?)\s*'
    r'(minut[yęa]?|min\.?|godzin[yę]?|godz\.?|h\b)',
    re.IGNORECASE | re.UNICODE,
)

# Heading keywords that indicate the start of the ingredients section
_INGREDIENTS_HEADING_RE = re.compile(
    r'sk[łl]adnik|potrzebne|lista\s+sk[łl]adnik|co\s+potrzebujemy',
    re.IGNORECASE | re.UNICODE,
)

# Heading keywords that indicate "how to prepare / instructions"
_INSTRUCTIONS_HEADING_RE = re.compile(
    r'jak\s+przygotowa[ćc]|jak\s+zrobi[ćc]|przygotowanie|spos[óo]b|'
    r'kroki|wykonanie|przepis\s+krok',
    re.IGNORECASE | re.UNICODE,
)

# Heading keywords that indicate notes / serving suggestions
_NOTES_HEADING_RE = re.compile(
    r'jak\s+podawa[ćc]|podanie|wskazówk|porad[ay]?|uwag[ai]?|'
    r'not[ae]\b|tip[sy]?\b|ciekawostk',
    re.IGNORECASE | re.UNICODE,
)

# Inline "important" markers
_IMPORTANT_MARKER_RE = re.compile(
    r'^\s*(?:wa[żz]ne|uwaga|wskaz[óo]wka|porada|tip)\s*[:\-–]',
    re.IGNORECASE | re.UNICODE,
)


class KuchennykodeksPlExtractor(BaseRecipeExtractor):
    """Экстрактор для kuchennykodeks.pl (польский кулинарный сайт)"""

    # ------------------------------------------------------------------
    # Helper: find the main article entry-content div
    # ------------------------------------------------------------------
    def _get_entry_content(self):
        return self.soup.find('div', class_=re.compile(r'\bentry-content\b'))

    # ------------------------------------------------------------------
    # dish_name
    # ------------------------------------------------------------------
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из h1.entry-title"""
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            text = self.clean_text(h1.get_text())
            # Remove "– subtitle" / "- subtitle" suffixes
            text = re.sub(r'\s+[–\-]\s+.*$', '', text).strip()
            return text or None

        # Fallback: og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            text = self.clean_text(og_title['content'])
            text = re.sub(r'\s+[–\-]\s+.*$', '', text).strip()
            return text or None

        return None

    # ------------------------------------------------------------------
    # description
    # ------------------------------------------------------------------
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта – первый жирный параграф в entry-content"""
        content = self._get_entry_content()
        if not content:
            return None

        for p in content.find_all('p', recursive=False):
            # Look for a <p> that wraps its text in <strong> (the intro paragraph)
            if p.find('strong') and not p.find_parent(['ul', 'ol']):
                text = self.clean_text(p.get_text(separator=' '))
                if len(text) > 40:
                    return text

        # Wider search in case not direct child
        for p in content.find_all('p'):
            if p.find('strong') and not p.find_parent(['ul', 'ol', 'li']):
                text = self.clean_text(p.get_text(separator=' '))
                if len(text) > 40:
                    return text

        # Fallback: meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        return None

    # ------------------------------------------------------------------
    # ingredients
    # ------------------------------------------------------------------
    def _parse_ingredient_text(self, raw: str) -> list:
        """
        Разбирает строку с ингредиентом (возможно несколько через '+')
        и возвращает список dict с ключами name/amount/unit.
        """
        if not raw:
            return []

        results = []
        # Split multiple ingredients on a single line (e.g. "2 żółtka + 1 całe jajko")
        parts = re.split(r'\s*\+\s*', raw)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            parsed = self._parse_single_ingredient(part)
            if parsed:
                results.append(parsed)
        return results

    def _parse_single_ingredient(self, text: str) -> Optional[dict]:
        """
        Парсинг одного ингредиента.
        Формат на сайте: 'AMOUNT UNIT NAME' или 'AMOUNT NAME' или 'NAME'
        """
        if not text:
            return None

        # Strip HTML entities and normalize whitespace
        text = self.clean_text(text)
        if not text:
            return None

        # Strip trailing suffix "do smaku", "opcjonalnie" etc.
        text = _STRIP_SUFFIXES_RE.sub('', text).strip()
        text = re.sub(r'\s+', ' ', text).strip()

        if not text:
            return None

        # --- Try to match a leading numeric amount ---
        # Handles: 200, 1/3, 9-12, 2,5  (including Unicode fractions)
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
        }
        for frac, rep in fraction_map.items():
            text = text.replace(frac, rep)

        num_pattern = r'^(\d+(?:[\/\-]\d+)?(?:[,.]\d+)?)\s*'
        num_match = re.match(num_pattern, text)

        amount = None
        unit = None
        name_text = text

        if num_match:
            amount = num_match.group(1).strip()
            rest = text[num_match.end():]

            # Try to match a unit word immediately after the number
            unit_match = _UNITS_RE.match(rest)
            if unit_match:
                unit = unit_match.group(1)
                name_text = rest[unit_match.end():].strip()
            else:
                # Check for compound units with parenthetical hint, e.g. "(około 500 g)"
                paren_unit_match = re.search(r'\(([^)]+)\)\s*$', rest)
                if paren_unit_match:
                    potential_unit = paren_unit_match.group(1).strip()
                    unit = potential_unit
                    name_text = rest[:paren_unit_match.start()].strip()
                else:
                    name_text = rest.strip()
        else:
            # No leading number – check for word amounts like "szczypta"
            lower_text = text.lower()
            matched_word_amount = None
            for wa in sorted(_WORD_AMOUNTS, key=len, reverse=True):
                if lower_text.startswith(wa):
                    matched_word_amount = wa
                    break

            if matched_word_amount:
                amount = matched_word_amount
                name_text = text[len(matched_word_amount):].strip()
            else:
                name_text = text

        # Clean up name: remove trailing/leading punctuation, normalize spaces
        name_text = re.sub(r'^[,;\-–]+', '', name_text).strip()
        name_text = re.sub(r'[,;]+$', '', name_text).strip()
        name_text = re.sub(r'\s+', ' ', name_text)

        # Remove redundant "do smaku" etc. from name as well
        name_text = _STRIP_SUFFIXES_RE.sub('', name_text).strip()

        # Fix orphaned opening parenthesis left at end after suffix stripping
        # e.g. "czerwonego wina (" → "czerwonego wina"
        name_text = re.sub(r'\s*\(\s*$', '', name_text).strip()

        # Remove trailing comma/semicolon again after all cleanups
        name_text = re.sub(r'[,;\s]+$', '', name_text)

        if not name_text or len(name_text) < 1:
            return None

        # Normalize unit to None if empty string
        if unit is not None:
            unit = unit.strip() or None

        return {
            'name': name_text,
            'amount': amount,
            'unit': unit,
        }

    def _collect_ingredient_lists(self, start_tag, stop_tags=None):
        """
        Собирает все элементы ингредиентов из ul.wp-block-list после start_tag,
        останавливаясь на stop_tags (список тегов BeautifulSoup).
        """
        ingredients = []
        stop_tags = stop_tags or []
        stop_names = [t.name for t in stop_tags] if stop_tags else []

        sibling = start_tag.find_next_sibling()
        while sibling:
            # Stop if we reach one of the stop headings
            if stop_tags and sibling in stop_tags:
                break
            tag_name = sibling.name if sibling.name else ''

            # Treat another h2 (same level) as stop
            if tag_name == 'h2' and sibling != start_tag:
                # Only stop if it's NOT an ingredient sub-section
                heading_text = sibling.get_text(strip=True).lower()
                if not _INGREDIENTS_HEADING_RE.search(heading_text):
                    break

            if tag_name == 'ul' and 'wp-block-list' in (sibling.get('class') or []):
                for li in sibling.find_all('li'):
                    li_text = self.clean_text(li.get_text(separator=' '))
                    if li_text and not li_text.endswith(':'):
                        parsed = self._parse_ingredient_text(li_text)
                        ingredients.extend(parsed)

            sibling = sibling.find_next_sibling()

        return ingredients

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в JSON-строку"""
        content = self._get_entry_content()
        if not content:
            return None

        ingredients = []

        # Find the h2/h3 heading for ingredients
        for heading in content.find_all(['h2', 'h3']):
            heading_text = heading.get_text(strip=True)
            if _INGREDIENTS_HEADING_RE.search(heading_text):
                # Collect ingredient ULs until the next h2 (instructions / other)
                found = self._collect_ingredient_lists(heading)
                if found:
                    ingredients.extend(found)
                    # If we found the main ingredients h2, break
                    if heading.name == 'h2':
                        break

        if not ingredients:
            logger.warning('kuchennykodeks_pl: No ingredients found in %s', self.html_path)
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    # ------------------------------------------------------------------
    # instructions
    # ------------------------------------------------------------------
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций из всех ol.wp-block-list в статье"""
        content = self._get_entry_content()
        if not content:
            return None

        # Check if there is an instructions heading (h2/h3)
        # We only want ordered lists that come AFTER the first instruction heading
        # (to avoid accidentally picking up other OLs).
        instruction_h2 = None
        for heading in content.find_all(['h2', 'h3']):
            heading_text = heading.get_text(strip=True)
            if _INSTRUCTIONS_HEADING_RE.search(heading_text):
                instruction_h2 = heading
                break

        all_steps: list[str] = []

        if instruction_h2:
            # Collect every ol.wp-block-list sibling after the first instruction heading
            # until end of article footer
            sibling = instruction_h2.find_next_sibling()
            while sibling:
                tag_name = sibling.name if sibling.name else ''
                # Stop at footer
                if tag_name == 'footer':
                    break

                if tag_name == 'ol' and 'wp-block-list' in (sibling.get('class') or []):
                    for li in sibling.find_all('li'):
                        step_text = self.clean_text(li.get_text(separator=' '))
                        if step_text:
                            all_steps.append(step_text)
                elif tag_name == 'h3':
                    # Sub-section heading – include as a label in instructions
                    heading_label = self.clean_text(sibling.get_text())
                    if heading_label and _INSTRUCTIONS_HEADING_RE.search(heading_label):
                        pass  # skip pure "How to prepare" headers
                    elif heading_label and not _NOTES_HEADING_RE.search(heading_label):
                        all_steps.append(heading_label + ':')

                sibling = sibling.find_next_sibling()
        else:
            # Fallback: collect all OLs in entry-content
            for ol in content.find_all('ol', class_='wp-block-list'):
                for li in ol.find_all('li'):
                    step_text = self.clean_text(li.get_text(separator=' '))
                    if step_text:
                        all_steps.append(step_text)

        if not all_steps:
            logger.warning('kuchennykodeks_pl: No instructions found in %s', self.html_path)
            return None

        # Number steps (skip lines that already look like sub-headings ending with ':')
        numbered: list[str] = []
        step_num = 1
        for step in all_steps:
            if step.endswith(':'):
                # Section heading – keep as-is without number
                numbered.append(step)
            else:
                numbered.append(f'{step_num}. {step}')
                step_num += 1

        return '\n'.join(numbered)

    # ------------------------------------------------------------------
    # category
    # ------------------------------------------------------------------
    def extract_category(self) -> Optional[str]:
        """Извлечение категории из div.tags-links или хлебных крошек"""
        # Primary: tags-links section
        tags_div = self.soup.find('div', class_='tags-links')
        if tags_div:
            links = tags_div.find_all('a', attrs={'rel': re.compile(r'category')})
            cats = [self.clean_text(a.get_text()) for a in links if a.get_text(strip=True)]
            if cats:
                return ', '.join(cats)

        # Fallback: breadcrumb
        breadcrumb = self.soup.find('div', class_=re.compile(r'breadcrumb'))
        if breadcrumb:
            links = breadcrumb.find_all('a')
            # Skip first (home) and take the rest
            cats = [self.clean_text(a.get_text()) for a in links[1:] if a.get_text(strip=True)]
            if cats:
                return ', '.join(cats)

        # Fallback: article class attribute "category-XXX"
        article = self.soup.find('article', id=re.compile(r'^post-'))
        if article:
            classes = ' '.join(article.get('class', []))
            cat_match = re.search(r'category-([a-z0-9\-]+)', classes, re.IGNORECASE)
            if cat_match:
                return cat_match.group(1).replace('-', ' ')

        return None

    # ------------------------------------------------------------------
    # times
    # ------------------------------------------------------------------
    @staticmethod
    def _minutes_to_str(minutes: float) -> str:
        """Конвертирует минуты в строку 'X minutes'"""
        mins = int(round(minutes))
        return f'{mins} minutes'

    def _extract_all_times_from_text(self, text: str) -> list[float]:
        """Находит все упоминания времени в тексте и возвращает список минут"""
        times = []
        for m in _TIME_RE.finditer(text):
            value_str = m.group(1).replace(',', '.')
            unit_str = m.group(2).lower()
            try:
                value = float(value_str)
            except ValueError:
                continue
            if unit_str.startswith('godz') or unit_str == 'h':
                value *= 60
            times.append(value)
        return times

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления из текста рецепта"""
        content = self._get_entry_content()
        if not content:
            return None

        # Collect text from all ordered list items (cooking steps)
        ol_texts = []
        for ol in content.find_all('ol', class_='wp-block-list'):
            for li in ol.find_all('li'):
                ol_texts.append(li.get_text(separator=' ', strip=True))

        full_text = ' '.join(ol_texts)
        times = self._extract_all_times_from_text(full_text)

        if not times:
            # Try broader search across all content
            all_text = content.get_text(separator=' ', strip=True)
            times = self._extract_all_times_from_text(all_text)

        if not times:
            return None

        # Return the maximum cooking time found
        max_time = max(times)
        return self._minutes_to_str(max_time)

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки – на сайте явно не указывается, возвращаем None"""
        return None

    def extract_total_time(self) -> Optional[str]:
        """Общее время – на сайте явно не указывается, возвращаем None"""
        return None

    # ------------------------------------------------------------------
    # notes
    # ------------------------------------------------------------------
    @staticmethod
    def _is_heading_paragraph(p_tag) -> bool:
        """
        Возвращает True, если параграф является лишь заголовком
        (только <strong> с вопросительным знаком или восклицательным).
        """
        # A paragraph that contains only a single <strong> element with no extra text
        # and reads as a heading/question is not real note content.
        text = p_tag.get_text(strip=True)
        if not text:
            return True
        # Heading-like: very short, ends with '?' or is only bold
        children = [c for c in p_tag.children if str(c).strip()]
        if len(children) == 1:
            child = children[0]
            if hasattr(child, 'name') and child.name == 'strong':
                if text.endswith('?') or len(text) < 60:
                    return True
        return False

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок / советов.
        Стратегия:
        1. Параграфы с маркерами 'Ważne:', 'Uwaga:', 'Wskazówka:' и т.п.
        2. Параграфы после последнего <ol> в entry-content (пропуская заголовки).
        3. Последний содержательный параграф статьи.
        """
        content = self._get_entry_content()
        if not content:
            return None

        notes_parts: list[str] = []

        # --- Strategy 1: important-marker paragraphs anywhere in content ---
        for p in content.find_all('p'):
            p_text = self.clean_text(p.get_text(separator=' '))
            if _IMPORTANT_MARKER_RE.match(p_text) and len(p_text) > 20:
                if not self._is_heading_paragraph(p):
                    notes_parts.append(p_text)

        # --- Strategy 2: paragraphs after last <ol> (skip bold headings) ---
        all_ols = content.find_all('ol', class_='wp-block-list')
        if all_ols:
            last_ol = all_ols[-1]
            sibling = last_ol.find_next_sibling()
            while sibling:
                tag_name = sibling.name if sibling.name else ''
                if tag_name == 'footer':
                    break
                if tag_name == 'p':
                    if self._is_heading_paragraph(sibling):
                        sibling = sibling.find_next_sibling()
                        continue
                    p_text = self.clean_text(sibling.get_text(separator=' '))
                    # Skip list-header paragraphs that end with ":"
                    if p_text.rstrip().endswith(':'):
                        sibling = sibling.find_next_sibling()
                        continue
                    if len(p_text) > 20 and p_text not in notes_parts:
                        notes_parts.append(p_text)
                sibling = sibling.find_next_sibling()

        if notes_parts:
            return ' '.join(notes_parts)

        # --- Strategy 3: last non-heading paragraph in entry-content ---
        all_ps = [
            p for p in content.find_all('p')
            if not p.find_parent(['ul', 'ol']) and not self._is_heading_paragraph(p)
        ]
        if all_ps:
            last_p_text = self.clean_text(all_ps[-1].get_text(separator=' '))
            if len(last_p_text) > 20:
                return last_p_text

        return None

    # ------------------------------------------------------------------
    # tags
    # ------------------------------------------------------------------
    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов.
        Сайт не публикует мета-keywords, поэтому пробуем:
        1. Явные теги из div.tags-links (теги, не категории).
        2. Ключевые слова из заголовка статьи.
        """
        tags: list[str] = []

        # Check for tag links (non-category rel="tag")
        tags_div = self.soup.find('div', class_='tags-links')
        if tags_div:
            tag_links = tags_div.find_all('a', attrs={'rel': re.compile(r'\btag\b')})
            # Exclude links that are purely category links
            for a in tag_links:
                rel_val = ' '.join(a.get('rel', []))
                if 'category' not in rel_val:
                    tag_text = self.clean_text(a.get_text())
                    if tag_text:
                        tags.append(tag_text.lower())

        if tags:
            return ', '.join(tags)

        return None

    # ------------------------------------------------------------------
    # image_urls
    # ------------------------------------------------------------------
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL основного изображения рецепта (только из основного контента)"""
        urls: list[str] = []
        seen: set[str] = set()

        def _add(url: str) -> None:
            url = url.strip()
            if url and url not in seen and url.startswith('http'):
                seen.add(url)
                urls.append(url)

        content = self._get_entry_content()

        # 1. Main post image: figure.image-single-wrapper inside entry-content
        if content:
            figure = content.find('figure', class_='image-single-wrapper')
            if figure:
                img = figure.find('img')
                if img:
                    for attr in ('data-src', 'src'):
                        val = img.get(attr, '')
                        if val:
                            _add(val)
                            break

        # 2. img.wp-post-image inside the main article element only
        article = self.soup.find('article', id=re.compile(r'^post-'))
        if article and not urls:
            for img in article.find_all('img', class_=re.compile(r'\bwp-post-image\b')):
                for attr in ('data-src', 'src'):
                    val = img.get(attr, '')
                    if val:
                        _add(val)
                        break
                if urls:
                    break  # Only the first post image

        # 3. og:image meta tag as fallback
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                _add(og_image['content'])

        if urls:
            return ','.join(urls)

        return None

    # ------------------------------------------------------------------
    # extract_all
    # ------------------------------------------------------------------
    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта"""
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()

        return {
            'dish_name': dish_name,
            'description': description,
            'ingredients': ingredients,
            'instructions': instructions,
            'category': category,
            'prep_time': self.extract_prep_time(),
            'cook_time': self.extract_cook_time(),
            'total_time': self.extract_total_time(),
            'notes': notes,
            'tags': tags,
            'image_urls': self.extract_image_urls(),
        }


def main() -> None:
    """Точка входа для обработки директории с HTML файлами kuchennykodeks.pl"""
    import os

    preprocessed_dir = os.path.join('preprocessed', 'kuchennykodeks_pl')

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(KuchennykodeksPlExtractor, preprocessed_dir)
        return

    print(f'Директория не найдена: {preprocessed_dir}')
    print('Использование: python kuchennykodeks_pl.py')


if __name__ == '__main__':
    main()
