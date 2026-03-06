"""
Экстрактор данных рецептов для сайта saboreshoje.com
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

# Portuguese unit keywords for ingredient parsing
_PT_UNITS = (
    r'colheres?\s+de\s+s(?:o|ó)pa',    # colher de sopa / colheres de sopa
    r'colheres?\s+de\s+ch(?:a|á)',       # colher de chá / colheres de chá
    r'x(?:í|i)caras?\s+de\s+ch(?:a|á)', # xícara de chá
    r'x(?:í|i)caras?',                   # xícara / xícaras
    r'colheres?',                         # colher / colheres
    r'litros?',                           # litro / litros
    r'mililitros?',                       # mililitro / mililitros
    r'quilogramas?',                      # quilograma
    r'quilos?',                           # quilo / quilos
    r'gramas?',                           # grama / gramas
    r'\bkg\b', r'\bml\b', r'\bg\b', r'\bl\b',   # abbreviations – word-boundary guarded
    r'peda(?:ç|c)os?',                   # pedaço
    r'fatias?',                           # fatia
    r'dentes?',                           # dente (de alho)
    r'ramos?',                            # ramo
    r'pitadas?',                          # pitada
    r'doses?',                            # dose
    r'unidades?',                         # unidade
    r'latas?',                            # lata
    r'copos?',                            # copo
    r'pacotes?',                          # pacote
)
_UNIT_PATTERN = '|'.join(_PT_UNITS)

# Portuguese fraction map
_FRACTION_MAP = {
    '½': '1/2', '¼': '1/4', '¾': '3/4',
    '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
}


class SaboreshojEExtractor(BaseRecipeExtractor):
    """Экстрактор для saboreshoje.com (WordPress-based recipe article site)"""

    # ------------------------------------------------------------------ #
    # Helper: get the main post content area                              #
    # ------------------------------------------------------------------ #

    def _get_post_content(self):
        """Return the <div class='wp-block-post-content'> element, or None."""
        return self.soup.find('div', class_='wp-block-post-content')

    # ------------------------------------------------------------------ #
    # Helper: section extractor                                           #
    # ------------------------------------------------------------------ #

    def _get_section_text(self, keyword: str) -> Optional[str]:
        """
        Find the first H2/H3 whose text matches *keyword* (case-insensitive)
        inside the post content, then collect all subsequent <p> siblings
        until the next heading.

        Returns the joined paragraph text or None.
        """
        content = self._get_post_content()
        if not content:
            return None

        for heading in content.find_all(['h2', 'h3']):
            if re.search(keyword, heading.get_text(), re.I):
                parts = []
                sibling = heading.find_next_sibling()
                while sibling and sibling.name not in ('h2', 'h3'):
                    if sibling.name == 'p':
                        text = sibling.get_text(separator=' ', strip=True)
                        # Skip navigation-like cross-links ("Do mesmo gênero :")
                        if not re.match(
                            r'(?:do mesmo gênero|em paralelo|também para|isso pode interessar)',
                            text,
                            re.I,
                        ):
                            parts.append(text)
                    sibling = sibling.find_next_sibling()
                if parts:
                    return ' '.join(parts)
        return None

    # ------------------------------------------------------------------ #
    # Ingredient helpers                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_ingredient_line(line: str) -> Optional[dict]:
        """
        Parse a single ingredient string into {name, amount, unit}.

        Handles patterns like:
          "200 g de farinha de trigo"
          "1 colher de chá de cominho"
          "sal a gosto"
          "azeite extra-virgem"
        """
        if not line:
            return None

        # Normalize unicode fractions
        for frac, repl in _FRACTION_MAP.items():
            line = line.replace(frac, repl)

        line = re.sub(r'\s+', ' ', line).strip()

        # Pattern: optional amount + optional unit + optional "de" + name
        pattern = (
            r'^'
            r'([\d]+(?:[.,/]\d+)?(?:\s*-\s*[\d]+(?:[.,/]\d+)?)?)?'  # amount (e.g. "1", "1/2", "30-40")
            r'\s*'
            r'(' + _UNIT_PATTERN + r')?'                              # unit
            r'\s*(?:de\s+)?'                                           # optional "de"
            r'(.+)$'
        )

        m = re.match(pattern, line, re.I)
        if not m:
            return {'name': SaboreshojEExtractor.clean_text(line), 'amount': None, 'unit': None}

        amount_str, unit, name = m.group(1), m.group(2), m.group(3)

        amount = amount_str.strip() if amount_str and amount_str.strip() else None
        unit = unit.strip() if unit else None
        name = re.sub(r'\s+', ' ', name).strip(' ,;') if name else None

        if not name:
            return None

        return {'name': SaboreshojEExtractor.clean_text(name), 'amount': amount, 'unit': unit}

    def _extract_ingredients_from_text(self, text: str, use_article_pattern: bool = True) -> list:
        """
        Given free-form article text from the ingredients section, extract
        individual ingredient names.

        Strategy:
          1. Look for UL/OL list items inside the section (best structure).
          2. Extract comma-separated items from enumeration phrases
             ("como X, Y e Z", "inclui X, Y e Z", "utilize X, Y e Z", …).
          3. Extract items introduced with definite article
             ("O sal", "A água", "A manteiga ou óleo", …).
        Results from steps 2 and 3 are combined and deduplicated.
        """
        # Noise patterns to skip lines/chunks (navigation cross-links etc.)
        _noise_re = re.compile(
            r'(?:do mesmo gênero|em paralelo|também para|isso pode interessar'
            r'|guia\s|descubra\s+como|confira\s+o\s+passo|segredo\s+para)',
            re.I,
        )
        # Verb forms that indicate method descriptions or non-ingredients
        _verb_inf_re = re.compile(
            r'(?:^|\s)(?:tostar|moer|refogar|picar|cortar|misturar|combinar|'
            r'fritar|cozer|assar|dourar|saltear|temperar|emulsionar|mexer|'
            r'bater|incorporar|fique|cresça|esteja|seja|tenha|fa[çc]a|obter|'
            r'usar|utilizar|adicionar|acrescentar|preparar|cozinhar)\b',
            re.I,
        )
        # Generic verb-phrase and adjective indicators (not ingredient names)
        _verb_phrase_re = re.compile(
            r'\b(?:garantem|costuma|impacta|proporciona[mr]?|adicionam|alimentam|'
            r'ajudam|deve[mr]?|permite[mr]?|influencia[mr]?|resulta[mr]?|'
            r'realça|conferindo|realçando|mantém|contribu[ií]|envolvem|'
            r'substitui|controla|ajuda|influencia|saborosa|frescos?|'
            r'começa|inclui|contém|tem\b|traz|oferece|confere|apresenta|'
            r'está|prévio|dessas?)\b',
            re.I,
        )

        ingredients: list = []

        # --- 1. Try list items first (best-structured source) ---
        content = self._get_post_content()
        if content:
            ingr_heading = None
            for h in content.find_all(['h2', 'h3']):
                if re.search(r'ingrediente', h.get_text(), re.I):
                    ingr_heading = h
                    break

            if ingr_heading:
                sibling = ingr_heading.find_next_sibling()
                while sibling and sibling.name not in ('h2', 'h3'):
                    if sibling.name in ('ul', 'ol'):
                        for li in sibling.find_all('li'):
                            item_text = self.clean_text(li.get_text())
                            if item_text and not _noise_re.search(item_text):
                                parsed = self._parse_ingredient_line(item_text)
                                if parsed:
                                    ingredients.append(parsed)
                    sibling = sibling.find_next_sibling()

        if ingredients:
            return ingredients

        # --- Shared set to deduplicate across steps 2 & 3 ---
        seen_keys: set = set()

        def _add_item(raw: str) -> None:
            """Clean, validate, and add an ingredient item."""
            # Strip common leading connectors and articles-with-prepositions
            item = re.sub(
                r'^(?:além\s+d[aeo]s?\s+|também\s+|e\s+|[aA]\s+de\s+|[oO]\s+de\s+)\s*',
                '',
                raw,
                flags=re.I,
            )
            # Strip standalone leading articles ("a ", "o ", "as ", "os ")
            item = re.sub(r'^(?:[aAoO]s?\s+)(?=\S)', '', item)
            item = item.strip(' .,;')
            # Skip too-long, too-short, noisy, or verb-phrase items
            if not item or len(item) > 50 or len(item) < 3:
                return
            if _noise_re.search(item) or _verb_inf_re.search(item) or _verb_phrase_re.search(item):
                return
            # Skip items that are obviously not ingredients (pure adjective phrases etc.)
            if re.search(r'\b(?:essencial|fundamental|natural|suficiente|adequad[ao])\s*$', item, re.I):
                return
            key = item.lower()
            if key not in seen_keys:
                seen_keys.add(key)
                parsed = self._parse_ingredient_line(item)
                if parsed:
                    ingredients.append(parsed)

        # --- 2. Extract from enumeration patterns ---
        enum_patterns = [
            r'(?:como|incluindo|inclui|tais como|ingredientes?[^:]*:)\s+([^.]+)',
            r'(?:utilize|use|adicione|acrescente)\s+([^.]+)',
        ]
        for pattern in enum_patterns:
            for match in re.finditer(pattern, text, re.I):
                chunk = match.group(1)
                if _noise_re.search(chunk):
                    continue
                items = re.split(r',\s*(?:e\s+|ou\s+)?|,?\s+e\s+', chunk)
                for item in items:
                    _add_item(item)

        # --- 3. Extract items introduced with definite article ---
        # Only run when text comes from a specific ingredient section (not full content),
        # to avoid false positives from general article sentences.
        if not use_article_pattern:
            return ingredients

        article_pattern = re.compile(
            r'(?:^|\.\s+)[OA]s?\s+([a-zA-ZÀ-ÿ][^,.;]+?)'
            r'(?:\s*[,;.]|\s+(?:por exemplo|também|adicionam|garantem|deve|'
            r'substitui|controla|ajuda|influencia|componente|é|são|'
            r'inclui|contém|deve|tem\s|traz|oferece|confere|apresenta|está))',
            re.M,
        )
        for m in article_pattern.finditer(text):
            _add_item(m.group(1))

        return ingredients

    # ------------------------------------------------------------------ #
    # Public extraction methods                                            #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Название блюда — из тега <h1>."""
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        title_tag = self.soup.find('title')
        if title_tag:
            text = re.sub(r'\s*[–—|-].*$', '', title_tag.get_text())
            return self.clean_text(text) or None

        return None

    def extract_description(self) -> Optional[str]:
        """
        Краткое описание рецепта.

        Приоритеты:
          1. Первый H2 в post-content (подзаголовок / описание рецепта).
          2. Первый абзац в теле статьи (если нет H2).
        """
        _noise_re = re.compile(
            r'(?:do mesmo gênero|em paralelo|também para|isso pode interessar)',
            re.I,
        )
        content = self._get_post_content()
        if content:
            # First H2 often contains the recipe subtitle / description
            first_h2 = content.find('h2')
            if first_h2:
                return self.clean_text(first_h2.get_text())

            # Fall back to first meaningful paragraph
            for p in content.find_all('p'):
                text = p.get_text(separator=' ', strip=True)
                if text and not _noise_re.search(text):
                    return self.clean_text(text)

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Список ингредиентов в формате JSON-строки.

        Сначала ищет раздел с заголовком "ingrediente*", затем при
        необходимости парсит параграфы с перечислениями (без шумовых абзацев).
        """
        _noise_re = re.compile(
            r'(?:do mesmo gênero|em paralelo|também para|isso pode interessar'
            r'|guia\s|descubra\s+como|confira\s+o\s+passo|segredo\s+para)',
            re.I,
        )
        try:
            section_text = self._get_section_text(r'ingrediente')
            has_section = section_text is not None
            if not section_text:
                # No dedicated section – scan content paragraphs, filtering noise
                content = self._get_post_content()
                if content:
                    clean_parts = [
                        p.get_text(separator=' ', strip=True)
                        for p in content.find_all('p')
                        if not _noise_re.search(p.get_text())
                    ]
                    section_text = ' '.join(clean_parts) if clean_parts else None

            if not section_text:
                return None

            # Only use article-pattern extraction when we have a dedicated
            # ingredients section to avoid false positives in full-article scans.
            ingredients = self._extract_ingredients_from_text(
                section_text, use_article_pattern=has_section
            )
            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
        except Exception as exc:
            logger.warning('extract_ingredients failed: %s', exc)
            return None

    def extract_steps(self) -> Optional[str]:
        """
        Инструкция по приготовлению — склеенные абзацы из раздела
        "passo a passo" / "preparo" / "preparação".

        Если такого раздела нет, возвращает объединённый текст статьи.
        """
        try:
            for kw in (r'passo\s+a\s+passo', r'preparo', r'prepara(?:ção|cao)'):
                text = self._get_section_text(kw)
                if text:
                    return self.clean_text(text)

            # Fallback: all paragraphs from post content
            content = self._get_post_content()
            if content:
                _noise_re = re.compile(
                    r'(?:do mesmo gênero|em paralelo|também para|isso pode interessar)',
                    re.I,
                )
                parts = []
                for p in content.find_all('p'):
                    t = p.get_text(separator=' ', strip=True)
                    if t and not _noise_re.search(t):
                        parts.append(t)
                if parts:
                    return self.clean_text(' '.join(parts))

            return None
        except Exception as exc:
            logger.warning('extract_steps failed: %s', exc)
            return None

    def extract_category(self) -> Optional[str]:
        """
        Категория статьи из блока категорий WordPress Kubio.
        """
        try:
            cat_block = self.soup.find(
                'div',
                class_=re.compile(r'wp-block-kubio-post-categories__tags', re.I),
            )
            if cat_block:
                text = self.clean_text(cat_block.get_text())
                if text:
                    return text

            # Fallback: first category link in nav
            for a in self.soup.find_all('a', href=re.compile(r'/category/')):
                text = self.clean_text(a.get_text())
                if text:
                    return text

            return None
        except Exception as exc:
            logger.warning('extract_category failed: %s', exc)
            return None

    def _extract_time_from_text(self, content_text: str, time_type: str) -> Optional[str]:
        """
        Try to find time values by scanning the article body.

        For 'cook' looks for oven/baking time patterns,
        for 'prep' looks for preparation time patterns,
        for 'total' looks for total time patterns.
        """
        # Patterns that capture ranges like "30 a 40 minutos" or "30-40 minutos"
        patterns = {
            'cook': [
                r'(?:assar|forno|cozinhar|cozimento)[^.]*?(\d+\s*(?:a\s*\d+|[–-]\s*\d+)?\s*(?:minutos?|horas?))',
                r'(\d+\s*(?:a\s*\d+|[–-]\s*\d+)\s*minutos?)(?:[^.]*?(?:assar|forno))',
            ],
            'prep': [
                r'(?:preparo|preparação|mistura)[^.]*?(\d+\s*(?:a\s*\d+|[–-]\s*\d+)?\s*(?:minutos?|horas?))',
            ],
            'total': [
                r'(?:tempo\s+total|total\s+de\s+tempo)[^.]*?(\d+\s*(?:a\s*\d+|[–-]\s*\d+)?\s*(?:minutos?|horas?))',
            ],
        }

        for pattern in patterns.get(time_type, []):
            m = re.search(pattern, content_text, re.I)
            if m:
                raw = m.group(1).strip()
                # Normalize "30 a 40 minutos" → "30-40 minutes"
                raw = re.sub(r'\s*a\s*', '-', raw)
                raw = re.sub(r'\s*[–]\s*', '-', raw)
                raw = re.sub(r'minutos?', 'minutes', raw, flags=re.I)
                raw = re.sub(r'horas?', 'hours', raw, flags=re.I)
                return self.clean_text(raw)

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки."""
        try:
            content = self._get_post_content()
            if content:
                return self._extract_time_from_text(content.get_text(), 'prep')
            return None
        except Exception as exc:
            logger.warning('extract_prep_time failed: %s', exc)
            return None

    def extract_cook_time(self) -> Optional[str]:
        """Время приготовления."""
        try:
            content = self._get_post_content()
            if content:
                return self._extract_time_from_text(content.get_text(), 'cook')
            return None
        except Exception as exc:
            logger.warning('extract_cook_time failed: %s', exc)
            return None

    def extract_total_time(self) -> Optional[str]:
        """Общее время приготовления."""
        try:
            content = self._get_post_content()
            if content:
                return self._extract_time_from_text(content.get_text(), 'total')
            return None
        except Exception as exc:
            logger.warning('extract_total_time failed: %s', exc)
            return None

    def extract_notes(self) -> Optional[str]:
        """
        Заметки к рецепту — ищет абзац с ключевыми словами
        "nota", "dica", "observação", "atenção" или последний абзац статьи.
        """
        try:
            content = self._get_post_content()
            if not content:
                return None

            _noise_re = re.compile(
                r'(?:do mesmo gênero|em paralelo|também para|isso pode interessar)',
                re.I,
            )
            note_kw = re.compile(r'\b(?:nota|dica|observa(?:ção|cao)|aten(?:ção|cao))\b', re.I)

            for p in content.find_all('p'):
                text = p.get_text(separator=' ', strip=True)
                if text and note_kw.search(text) and not _noise_re.search(text):
                    return self.clean_text(text)

            # Fallback: last meaningful paragraph
            paragraphs = [
                p.get_text(separator=' ', strip=True)
                for p in content.find_all('p')
                if p.get_text(strip=True) and not _noise_re.search(p.get_text())
            ]
            if paragraphs:
                return self.clean_text(paragraphs[-1])

            return None
        except Exception as exc:
            logger.warning('extract_notes failed: %s', exc)
            return None

    def extract_tags(self) -> Optional[str]:
        """
        Теги статьи.

        Предпочитает реальные теги WordPress (<a href='/tag/…'>),
        затем использует категорию самой статьи (из post-categories блока),
        иначе – все категории из навигации.
        """
        try:
            # 1. Real tag links (highest priority)
            tag_links = [
                a.get_text(strip=True)
                for a in self.soup.find_all('a', href=re.compile(r'/tag/'))
                if a.get_text(strip=True)
            ]
            if tag_links:
                seen: set = set()
                unique: list = []
                for t in tag_links:
                    if t.lower() not in seen:
                        seen.add(t.lower())
                        unique.append(t)
                return ', '.join(unique)

            # 2. Post-specific categories (from the inline post-categories block)
            cat_block = self.soup.find(
                'div',
                class_=re.compile(r'wp-block-kubio-post-categories__tags', re.I),
            )
            if cat_block:
                # Collect all <a> links within the block
                block_cats = [
                    a.get_text(strip=True)
                    for a in cat_block.find_all('a')
                    if a.get_text(strip=True)
                ]
                if not block_cats:
                    # Plain text fallback
                    text = self.clean_text(cat_block.get_text())
                    if text:
                        block_cats = [text]
                if block_cats:
                    seen = set()
                    unique = []
                    for c in block_cats:
                        if c.lower() not in seen:
                            seen.add(c.lower())
                            unique.append(c)
                    return ', '.join(unique)

            return None
        except Exception as exc:
            logger.warning('extract_tags failed: %s', exc)
            return None

    def extract_image_urls(self) -> Optional[str]:
        """
        URL изображений рецепта.

        Порядок поиска:
          1. Featured image (<figure class='wp-block-post-featured-image'>).
          2. Images in article figures (<figure class='wp-block-image'>).
          3. og:image meta.
        """
        try:
            urls: list = []

            # 1. Featured image (handles both standard WP and Kubio theme class names)
            feat_fig = self.soup.find(
                'figure',
                class_=re.compile(r'(?:kubio-post-featured-image|wp-block-post-featured-image)', re.I),
            )
            if feat_fig:
                img = feat_fig.find('img')
                if img and img.get('src'):
                    urls.append(img['src'])

            # 2. Article body images (figures without the site logo)
            for fig in self.soup.find_all('figure', class_=re.compile(r'wp-block-image', re.I)):
                img = fig.find('img')
                if img and img.get('src'):
                    src = img['src']
                    # Skip site logo/icon
                    if 'saboreshoje.png' not in src and 'saboreshoje-' not in src:
                        if src not in urls:
                            urls.append(src)

            # 3. og:image fallback
            og = self.soup.find('meta', property='og:image')
            if og and og.get('content') and og['content'] not in urls:
                urls.append(og['content'])

            # Deduplicate
            seen: set = set()
            unique: list = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique.append(url)

            return ','.join(unique) if unique else None
        except Exception as exc:
            logger.warning('extract_image_urls failed: %s', exc)
            return None

    # ------------------------------------------------------------------ #
    # Main entry point                                                     #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта."""
        return {
            'dish_name': self.extract_dish_name(),
            'description': self.extract_description(),
            'ingredients': self.extract_ingredients(),
            'instructions': self.extract_steps(),
            'category': self.extract_category(),
            'prep_time': self.extract_prep_time(),
            'cook_time': self.extract_cook_time(),
            'total_time': self.extract_total_time(),
            'notes': self.extract_notes(),
            'image_urls': self.extract_image_urls(),
            'tags': self.extract_tags(),
        }


def main() -> None:
    """Точка входа: обрабатывает все HTML-файлы в preprocessed/saboreshoje_com."""
    import os

    preprocessed_dir = os.path.join('preprocessed', 'saboreshoje_com')
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(SaboreshojEExtractor, preprocessed_dir)
        return

    print(f'Директория не найдена: {preprocessed_dir}')
    print('Использование: python saboreshoje_com.py')


if __name__ == '__main__':
    main()
