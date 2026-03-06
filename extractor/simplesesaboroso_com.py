"""
Экстрактор данных рецептов для сайта simplesesaboroso.com
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

from bs4 import NavigableString

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class SimpleSeSaborosoExtractor(BaseRecipeExtractor):
    """Экстрактор для simplesesaboroso.com"""

    # Portuguese units commonly found on the site
    _PT_UNITS = (
        r'x[ií]caras?\s*\(ch[aá]\)',
        r'x[ií]caras?\s*\(caf[eé]\)',
        r'x[ií]caras?',
        r'colheres?\s*\(sopa\)',
        r'colheres?\s*\(ch[aá]\)',
        r'colheres?\s*de\s*sopa',
        r'colheres?\s*de\s*ch[aá]',
        r'colher\s*\(sopa\)',
        r'colher\s*\(ch[aá]\)',
        r'colher\s*de\s*sopa',
        r'colher\s*de\s*ch[aá]',
        r'colheres?',
        r'kg',
        r'g\b',
        r'ml',
        r'l\b',
        r'litros?',
        r'gramas?',
        r'quilogramas?',
        r'mililitros?',
        r'pitadas?',
        r'unidades?',
        r'dentes?',
        r'pedaços?',
        r'fatias?',
        r'folhas?',
        r'ramos?',
        r'colher',
    )
    _PT_UNIT_RE = re.compile(
        r'^(' + '|'.join(_PT_UNITS) + r')\s*(?:de\s+)?',
        re.IGNORECASE,
    )

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _get_article_body_soup(self):
        """
        Возвращает BeautifulSoup-объект тела статьи из JSON-LD типа 'article'.
        """
        from bs4 import BeautifulSoup

        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'article':
                    article_html = data.get('articleBody', '')
                    if article_html:
                        return BeautifulSoup(article_html, 'lxml')
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    def _get_section_after_heading(self, body_soup, heading_keywords: list):
        """
        Ищет первый заголовок (h2/h3/h4), содержащий одно из ключевых слов,
        и возвращает список непосредственных содержательных элементов до
        следующего заголовка того же или более высокого уровня.
        """
        if body_soup is None:
            return None, []

        heading = None
        for tag in body_soup.find_all(['h2', 'h3', 'h4']):
            text_lower = tag.get_text().lower().strip()
            if any(kw in text_lower for kw in heading_keywords):
                heading = tag
                break

        if heading is None:
            return None, []

        siblings = []
        node = heading.next_sibling
        while node:
            if isinstance(node, NavigableString):
                siblings.append(node)
            elif node.name in ('h2', 'h3', 'h4'):
                break
            else:
                siblings.append(node)
            node = node.next_sibling

        return heading, siblings

    def _extract_items_from_siblings(self, siblings: list) -> list:
        """
        Извлекает список текстовых элементов из siblings секции.
        Поддерживает два формата:
          - ul/ol со списком li (формат goulash/curry/ratatouille)
          - текстовые узлы с префиксом '- ' (формат bolo)
        """
        # Check if any ul/ol elements present
        list_elements = [
            n for n in siblings
            if not isinstance(n, NavigableString) and n.name in ('ul', 'ol')
        ]
        if list_elements:
            items = []
            for ul_or_ol in list_elements:
                for li in ul_or_ol.find_all('li', recursive=False):
                    text = self.clean_text(li.get_text())
                    if text:
                        items.append(text)
            return items

        # Fall back: collect all text and split by "- " markers
        full_text = self._collect_section_text(siblings)
        return self._parse_text_list(full_text)

    def _collect_section_text(self, siblings: list) -> str:
        """Собирает весь текст из списка siblings, пропуская Gutenberg-маркеры."""
        parts = []
        for node in siblings:
            if isinstance(node, NavigableString):
                text = str(node)
                # Skip Gutenberg block markers (e.g. " wp:list ", " /wp:heading ")
                if re.search(r'\bwp:', text):
                    continue
                parts.append(text)
            elif node.name not in ('script', 'style'):
                parts.append(node.get_text())
        return ''.join(parts)

    def _parse_text_list(self, text: str) -> list:
        """
        Разбирает текст с пунктами в формате '- item\\n- item' в список строк.
        """
        lines = text.strip().splitlines()
        items = []
        for line in lines:
            line = line.strip()
            if line.startswith('- '):
                line = line[2:].strip()
            if line:
                items.append(line)
        return items

    # ------------------------------------------------------------------ #
    #  Ingredient parsing                                                  #
    # ------------------------------------------------------------------ #

    def _parse_ingredient(self, raw: str) -> Optional[dict]:
        """
        Парсит строку ингредиента на Portuguese в структуру
        {"name": ..., "amount": ..., "unit": ...}.
        """
        text = self.clean_text(raw)
        if not text:
            return None

        # ---- fraction normalization ----
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
        }
        for f, rep in fraction_map.items():
            text = text.replace(f, rep)

        # ---- attempt to parse "<amount> <unit> de <name>" ----
        # Pattern: optional leading number/fraction, optional unit, rest is name

        # number (integer, decimal, or fraction like 1/2 or 1 1/2)
        num_pat = r'(?:\d+\s+)?\d+/\d+|\d+[.,]\d+|\d+'
        num_re = re.compile(rf'^({num_pat})\s*', re.IGNORECASE)

        amount = None
        unit = None
        remainder = text

        m = num_re.match(remainder)
        if m:
            amount_str = m.group(1).strip()
            remainder = remainder[m.end():]

            # Try to parse amount as numeric
            try:
                if '/' in amount_str:
                    parts = amount_str.split()
                    total = 0.0
                    for p in parts:
                        if '/' in p:
                            n, d = p.split('/')
                            total += float(n) / float(d)
                        else:
                            total += float(p)
                    # Keep as int if whole number, else float
                    amount = int(total) if total == int(total) else total
                else:
                    val = float(amount_str.replace(',', '.'))
                    amount = int(val) if val == int(val) else val
            except ValueError:
                amount = amount_str

        # Try to match unit
        unit_m = self._PT_UNIT_RE.match(remainder)
        if unit_m:
            unit = unit_m.group(1).strip()
            remainder = remainder[unit_m.end():]

        # Clean up "de " prefix before ingredient name
        remainder = re.sub(r'^de\s+', '', remainder, flags=re.IGNORECASE)
        # Remove parenthetical clarifications at end
        remainder = re.sub(r'\s*\([^)]*\)\s*$', '', remainder)
        # Remove trailing quality notes
        remainder = re.sub(
            r'\s+(a gosto|opcion[a-z]+|opcional|opcional para.*|aprox\b.*|ou .*|cortad[ao].*|picad[ao].*|ralad[ao].*)',
            '',
            remainder,
            flags=re.IGNORECASE,
        )
        name = self.clean_text(remainder)

        if not name:
            return None

        return {"name": name, "amount": amount, "unit": unit}

    # ------------------------------------------------------------------ #
    #  Public extract methods                                              #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*[-–|].*$', '', title)
            return self.clean_text(title)

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из articleBody"""
        body_soup = self._get_article_body_soup()
        if body_soup is None:
            logger.warning('articleBody not found for %s', self.html_path)
            return None

        _heading, siblings = self._get_section_after_heading(
            body_soup, ['ingredi']
        )
        if not siblings:
            logger.warning('Ingredients section not found in %s', self.html_path)
            return None

        raw_items = self._extract_items_from_siblings(siblings)

        if not raw_items:
            logger.warning('No ingredients found in %s', self.html_path)
            return None

        ingredients = []
        for raw in raw_items:
            parsed = self._parse_ingredient(raw)
            if parsed:
                ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления из articleBody"""
        body_soup = self._get_article_body_soup()
        if body_soup is None:
            return None

        _heading, siblings = self._get_section_after_heading(
            body_soup, ['modo de preparo', 'modo de preparação', 'preparo', 'preparação', 'instruções']
        )
        if not siblings:
            logger.warning('Instructions section not found in %s', self.html_path)
            return None

        steps = self._extract_items_from_siblings(siblings)

        if not steps:
            return None

        # Numbered if not already
        if steps and not re.match(r'^\d+\.', steps[0]):
            steps = [f"{i}. {s}" for i, s in enumerate(steps, 1)]

        return ' '.join(steps)

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из jeg_meta_category"""
        cat_div = self.soup.find(class_=re.compile(r'jeg_meta_category', re.I))
        if cat_div:
            links = cat_div.find_all('a', rel=re.compile(r'category', re.I))
            if links:
                categories = [self.clean_text(a.get_text()) for a in links if a.get_text().strip()]
                if categories:
                    return ', '.join(categories)

        # Fallback: breadcrumbs
        breadcrumb = self.soup.find(attrs={'itemtype': re.compile(r'BreadcrumbList', re.I)})
        if breadcrumb:
            items = breadcrumb.find_all(attrs={'itemprop': 'name'})
            if len(items) > 1:
                return self.clean_text(items[-2].get_text())

        return None

    def _extract_cook_time_from_instructions(self) -> Optional[str]:
        """
        Пытается извлечь время приготовления из текста инструкций.
        Ищет паттерны вида 'X minutos/horas de cozimento/forno'.
        """
        body_soup = self._get_article_body_soup()
        if body_soup is None:
            return None

        _heading, siblings = self._get_section_after_heading(
            body_soup, ['modo de preparo', 'modo de preparação', 'preparo']
        )
        if not siblings:
            return None

        # Collect full text of instructions
        instr_text = self._collect_section_text(siblings)

        # Look for patterns like "cozinhar por X minutos", "forno por X a Y minutos"
        # Handle both single values and ranges ("30 a 40 minutos")
        patterns = [
            r'(?:forno|cozinhar?|coz[ia]nhar?|assar?|deixar?)\s+(?:[a-zà-ú]+\s+)*?(?:cerca\s+de\s+)?(\d+)\s*(?:a\s+\d+\s*)?(minutos?|horas?)',
            r'(?:por\s+(?:cerca\s+de\s+)?)(\d+)\s*(?:a\s+\d+\s*)?(minutos?|horas?)',
        ]

        for pat in patterns:
            matches = re.findall(pat, instr_text, re.IGNORECASE)
            if matches:
                # Take the largest value found (typically the main cook time)
                best = None
                best_minutes = 0
                for val_str, unit_str in matches:
                    val = int(val_str)
                    in_minutes = val * 60 if 'hora' in unit_str.lower() else val
                    if in_minutes > best_minutes:
                        best_minutes = in_minutes
                        best = (val, unit_str.lower())

                if best:
                    val, unit_str = best
                    if 'hora' in unit_str:
                        return f"{val * 60} minutes"
                    return f"{val} minutes"

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки — не указывается явно на сайте"""
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self._extract_cook_time_from_instructions()

    def extract_total_time(self) -> Optional[str]:
        """Общее время — не указывается явно на сайте"""
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок из секции 'Dicas e Variações'"""
        body_soup = self._get_article_body_soup()
        if body_soup is None:
            return None

        _heading, siblings = self._get_section_after_heading(
            body_soup, ['dica', 'nota', 'observa', 'variação', 'variações']
        )
        if not siblings:
            return None

        notes_items = self._extract_items_from_siblings(siblings)
        return ' '.join(notes_items) if notes_items else None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из jeg_post_tags"""
        tags_div = self.soup.find(class_=re.compile(r'jeg_post_tags', re.I))
        if tags_div:
            tag_links = tags_div.find_all('a', rel='tag')
            if tag_links:
                tags = [self.clean_text(a.get_text()) for a in tag_links if a.get_text().strip()]
                return ', '.join(tags) if tags else None

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []

        # 1. og:image meta tag
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # 2. Images inside articleBody
        body_soup = self._get_article_body_soup()
        if body_soup:
            for img in body_soup.find_all('img'):
                src = img.get('src') or img.get('data-src') or ''
                if src and src.startswith('http') and src not in urls:
                    urls.append(src)

        if not urls:
            return None

        # Deduplicate preserving order
        seen = set()
        unique = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта.
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_steps()
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
            "image_urls": self.extract_image_urls(),
            "tags": tags,
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "simplesesaboroso_com")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(SimpleSeSaborosoExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python simplesesaboroso_com.py")


if __name__ == "__main__":
    main()
