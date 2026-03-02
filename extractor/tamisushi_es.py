"""
Экстрактор данных рецептов для сайта tamisushi.es
"""

import sys
from pathlib import Path
import json
import logging
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Spanish measurement units
_ES_UNITS = (
    r'tazas?',
    r'cucharadas?',
    r'cucharaditas?',
    r'cucharas?',
    r'gramos?',
    r'kilogramos?',
    r'g',
    r'kg',
    r'mililitros?',
    r'litros?',
    r'ml',
    r'l',
    r'pizcas?',
    r'hojas?',
    r'latas?',
    r'unidades?',
    r'porciones?',
    r'tiras?',
    r'rebanadas?',
    r'dientes?',
    r'ramitas?',
    r'rodajas?',
    r'onzas?',
    r'oz',
    r'lbs?',
)
_ES_UNIT_RE = r'(?:' + '|'.join(_ES_UNITS) + r')'

# Number patterns: integer, decimal, fraction (1/2), mixed (1 1/2), unicode fraction
_FRAC_MAP = {
    '½': '1/2', '¼': '1/4', '¾': '3/4',
    '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
    '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
    '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5',
}


def _normalize_unicode_fracs(text: str) -> str:
    for uf, rep in _FRAC_MAP.items():
        text = text.replace(uf, ' ' + rep)
    return text


def _parse_amount(amount_str: str) -> Optional[float]:
    """Parse a Spanish amount string like '2', '1/3', '1 1/2', '2.5' into a float."""
    if not amount_str:
        return None
    amount_str = amount_str.strip()
    try:
        parts = amount_str.split()
        total = 0.0
        for part in parts:
            if '/' in part:
                num, denom = part.split('/', 1)
                total += float(num) / float(denom)
            else:
                total += float(part.replace(',', '.'))
        return int(total) if total == int(total) else total
    except (ValueError, ZeroDivisionError):
        return None


class TamiSushiExtractor(BaseRecipeExtractor):
    """Экстрактор для tamisushi.es"""

    def _get_entry_content(self):
        """Возвращает основной контентный блок страницы."""
        return self.soup.find('div', class_='entry-content')

    def _find_instrucciones_block(self):
        """
        Возвращает H2-элемент с блоком «Instrucciones…» (основной рецептурный блок),
        либо None если не найден.
        """
        entry = self._get_entry_content()
        if not entry:
            return None
        for h2 in entry.find_all('h2'):
            txt = h2.get_text().strip().lower()
            if 'instrucciones' in txt:
                return h2
        return None

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из тега H1."""
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        # Fallback: og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания из мета-тега description."""
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        return None

    def _parse_ingredient_line(self, line: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат.

        Поддерживает форматы:
          - «2 tazas de arroz para sushi»
          - «Arroz para sushi: 2 tazas»
          - «1/3 de taza de vinagre»
          - «Alga nori (opcional)»
          - «1 huevo»
        """
        if not line:
            return None

        # Normalize unicode fractions
        text = _normalize_unicode_fracs(line.strip())

        # Remove parenthetical notes
        text = re.sub(r'\([^)]*\)', '', text)
        # Remove trailing info after long dashes or "–"
        text = re.sub(r'\s*[–—]\s*.*$', '', text)
        text = re.sub(r'\s+', ' ', text).strip()

        if not text:
            return None

        # Pattern 1: "NAME: AMOUNT UNIT" (colon-separated, name first)
        colon_match = re.match(
            r'^(.+?):\s*([\d\s/.,]+)\s+(' + _ES_UNIT_RE + r')\b.*$',
            text, re.IGNORECASE
        )
        if colon_match:
            name = self.clean_text(colon_match.group(1))
            amount = _parse_amount(colon_match.group(2))
            unit = colon_match.group(3).strip()
            if name:
                return {"name": name, "amount": amount, "unit": unit}

        # Pattern 2: "AMOUNT [de] UNIT [de] NAME" (amount first)
        num_first = re.match(
            r'^([\d\s/.,]+)\s+(?:de\s+)?(' + _ES_UNIT_RE + r')\s+(?:de\s+)?(.+)$',
            text, re.IGNORECASE
        )
        if num_first:
            amount = _parse_amount(num_first.group(1))
            unit = num_first.group(2).strip()
            name = self.clean_text(num_first.group(3))
            if name:
                return {"name": name, "amount": amount, "unit": unit}

        # Pattern 3: "AMOUNT NAME" (number but no recognized unit)
        num_name = re.match(r'^([\d\s/.,]+)\s+(.+)$', text)
        if num_name:
            amount = _parse_amount(num_name.group(1))
            name = self.clean_text(num_name.group(2))
            if name and len(name) >= 2:
                return {"name": name, "amount": amount, "unit": None}

        # Pattern 4: plain name without amount
        name = self.clean_text(text)
        if name and len(name) >= 2:
            return {"name": name, "amount": None, "unit": None}

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из блока «Instrucciones…».
        Собирает все подразделы «Ingredientes» и «Condimentos» внутри этого блока.
        Fallback: первый раздел «Ingredientes» во всём entry-content.
        """
        instruc_h2 = self._find_instrucciones_block()
        entry = self._get_entry_content()

        def _collect_from_block(start_elem) -> list:
            ingredients: list = []
            node = start_elem.find_next_sibling()
            while node and node.name != 'h2':
                if node.name in ('h3', 'h4'):
                    heading_txt = node.get_text().strip().lower()
                    if 'ingrediente' in heading_txt or 'condimento' in heading_txt:
                        sib = node.find_next_sibling()
                        if sib and sib.name in ('ul', 'ol'):
                            for li in sib.find_all('li'):
                                item_text = self.clean_text(li.get_text(separator=' '))
                                parsed = self._parse_ingredient_line(item_text)
                                if parsed:
                                    ingredients.append(parsed)
                node = node.find_next_sibling()
            return ingredients

        # Primary: collect from the instrucciones block
        if instruc_h2:
            ingredients = _collect_from_block(instruc_h2)
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        # Fallback: first ingredientes h3/h4 in entry-content
        if entry:
            for heading in entry.find_all(['h2', 'h3', 'h4']):
                txt = heading.get_text().strip().lower()
                if 'ingrediente' not in txt:
                    continue
                sib = heading.find_next_sibling()
                if sib and sib.name in ('ul', 'ol'):
                    ingredients = []
                    for li in sib.find_all('li'):
                        item_text = self.clean_text(li.get_text(separator=' '))
                        parsed = self._parse_ingredient_line(item_text)
                        if parsed:
                            ingredients.append(parsed)
                    if ingredients:
                        return json.dumps(ingredients, ensure_ascii=False)

        logger.debug("No ingredients section found in %s", self.html_path)
        return None

    def extract_steps(self) -> Optional[str]:
        """
        Извлечение шагов из блока «Instrucciones…» — все элементы <ol> внутри него.
        Fallback: первый раздел «Preparación» или «Instrucciones» в entry-content.
        """
        instruc_h2 = self._find_instrucciones_block()
        entry = self._get_entry_content()

        def _steps_from_ols(start_elem) -> list:
            steps: list = []
            node = start_elem.find_next_sibling()
            while node and node.name != 'h2':
                if node.name == 'ol':
                    for li in node.find_all('li', recursive=False):
                        step_text = self.clean_text(li.get_text(separator=' '))
                        if step_text:
                            steps.append(step_text)
                node = node.find_next_sibling()
            return steps

        if instruc_h2:
            steps = _steps_from_ols(instruc_h2)
            if steps:
                numbered = [f"{i}. {s}" for i, s in enumerate(steps, 1)]
                return ' '.join(numbered)

        # Fallback: first h3/h4 with 'preparación'/'instrucciones' followed by ul/ol
        if entry:
            for heading in entry.find_all(['h2', 'h3', 'h4']):
                txt = heading.get_text().strip().lower()
                if not any(k in txt for k in ('preparación', 'preparacion', 'instrucciones', 'pasos')):
                    continue
                sib = heading.find_next_sibling()
                if sib and sib.name in ('ul', 'ol'):
                    steps = []
                    for li in sib.find_all('li'):
                        step_text = self.clean_text(li.get_text(separator=' '))
                        if step_text:
                            steps.append(step_text)
                    if steps:
                        numbered = [f"{i}. {s}" for i, s in enumerate(steps, 1)]
                        return ' '.join(numbered)

        logger.debug("No instructions section found in %s", self.html_path)
        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из мета-тега article:section."""
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        # Fallback: breadcrumbs
        breadcrumb = self.soup.find('section', class_=re.compile(r'custom.*content|breadcrumb', re.I))
        if breadcrumb:
            links = breadcrumb.find_all('a')
            if len(links) >= 2:
                return self.clean_text(links[-1].get_text())
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение советов/заметок из блоков .recipe-tip."""
        tips = self.soup.find_all('div', class_='recipe-tip')
        if not tips:
            return None
        tip_texts = []
        for tip in tips:
            text = self.clean_text(tip.get_text(separator=' '))
            if text:
                tip_texts.append(text)
        return ' '.join(tip_texts) if tip_texts else None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из ссылок с rel='tag'."""
        tag_links = self.soup.find_all('a', rel='tag')
        if not tag_links:
            return None
        seen: set = set()
        unique_tags = []
        for link in tag_links:
            tag = self.clean_text(link.get_text())
            if tag and tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        return ', '.join(unique_tags) if unique_tags else None

    def extract_image_urls(self) -> Optional[str]:
        """
        Извлечение URL изображений рецепта из мета-тегов og:image и
        data-src атрибутов img-тегов в основном контенте (без иконок, аватаров, миниатюр).
        """
        urls: list = []

        # og:image — главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])

        # data-src images in entry-content (lazy-loaded), skip non-photo URLs
        entry = self._get_entry_content()
        if entry:
            for img in entry.find_all('img'):
                src = img.get('data-src') or img.get('src') or ''
                if (src.startswith('http')
                        and 'wp-content/uploads' in src
                        and '-150x150.' not in src
                        and 'litespeed/avatar' not in src
                        and re.search(r'\.(jpg|jpeg|png|webp)(\?|$)', src, re.I)):
                    urls.append(src)

        if not urls:
            return None

        seen: set = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ','.join(unique_urls) if unique_urls else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта в едином формате проекта.
        """
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_steps(),
            "category": self.extract_category(),
            "prep_time": None,
            "cook_time": None,
            "total_time": None,
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls(),
        }


def main():
    """Точка входа для обработки директории с HTML файлами."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "tamisushi_es")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(TamiSushiExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python tamisushi_es.py")


if __name__ == "__main__":
    main()
