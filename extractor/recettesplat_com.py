"""
Экстрактор данных рецептов для сайта recettesplat.com
"""

import os
import sys
import logging
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class RecettesplatComExtractor(BaseRecipeExtractor):
    """Экстрактор для recettesplat.com"""

    # ---------------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------------

    def _get_entry_content(self):
        """Возвращает div.entry-content или None"""
        return self.soup.find(class_='entry-content')

    def _parse_sections(self) -> dict:
        """
        Разбирает div.entry-content на секции:
        'description', 'ingredients', 'instructions', 'notes'.

        Логика:
        - Элементы ДО первого h4 → description.
        - h4 с ключевым словом «ingrédient» / «pour le» / «pour la» / «pour les»
          переключает режим в ingredients.
        - h4 с «préparation» / «preparation» переключает в instructions.
        - h4 или p с «conseil» / «note» / «astuce» / «conclusion»
          переключает в notes.
        - Если явный заголовок «préparation» не найден, то после секций
          ингредиентов каждый <p> классифицируется отдельно: параграф,
          содержащий <br>-строки или начинающийся с цифры/дроби, считается
          ингредиентом; иначе — инструкцией.
        """
        ec = self._get_entry_content()
        if not ec:
            return {'description': [], 'ingredients': [], 'instructions': [], 'notes': []}

        sections: dict = {'description': [], 'ingredients': [], 'instructions': [], 'notes': []}
        state = 'description'
        has_explicit_instruction_h4 = False

        # First pass: check whether any h4 explicitly signals "préparation"
        for h4 in ec.find_all('h4'):
            if re.search(r'pr[eé]paration', h4.get_text(), re.IGNORECASE):
                has_explicit_instruction_h4 = True
                break

        for element in ec.children:
            if not hasattr(element, 'name') or not element.name:
                continue

            # Skip ad / code-block containers
            if element.name == 'div':
                classes = element.get('class') or []
                if 'code-block' in classes or 'adsbygoogle' in classes:
                    continue

            tag_text = element.get_text(strip=True).lower()

            # ----- h4 → section marker -----
            if element.name == 'h4':
                if re.search(r'pr[eé]paration|preparation', tag_text, re.IGNORECASE):
                    state = 'instructions'
                elif re.search(r'conseil|note\b|astuce|conclusion', tag_text, re.IGNORECASE):
                    state = 'notes'
                elif re.search(r'ingr[eé]dient|pour\s+le\b|pour\s+la\b|pour\s+les\b', tag_text, re.IGNORECASE):
                    state = 'ingredients'
                elif state == 'description':
                    # First h4 that doesn't match any keyword still signals end of description
                    state = 'ingredients'
                # else: keep current state (e.g. another sub-heading in ingredients)
                continue

            # ----- p / ul / ol → content -----
            if element.name in ('p', 'ul', 'ol'):
                raw_text = element.get_text(separator='\n', strip=True)
                if not raw_text:
                    continue

                if state == 'ingredients' and not has_explicit_instruction_h4:
                    # No explicit prep header → decide per-paragraph
                    if self._paragraph_looks_like_ingredient(element):
                        sections['ingredients'].append(element)
                    else:
                        state = 'instructions'
                        sections['instructions'].append(element)
                else:
                    sections[state].append(element)

        return sections

    @staticmethod
    def _paragraph_looks_like_ingredient(p_tag) -> bool:
        """
        Эвристика: параграф считается ингредиентом, если:
        - содержит <br>-теги (список через переносы строк), ИЛИ
        - первая непустая строка начинается с цифры, дроби или Unicode-дроби.
        """
        # Multi-line ingredient blocks always have <br> tags
        if p_tag.find('br'):
            first_lines = [
                ln.strip()
                for ln in p_tag.get_text(separator='\n', strip=True).splitlines()
                if ln.strip()
            ]
            if first_lines:
                first = first_lines[0]
                # The paragraph starts with a number/fraction → treat as ingredients
                if re.match(r'^[\d½¼¾⅓⅔⅛/]', first):
                    return True
        # Single-line paragraph starting with a digit or fraction → ingredient
        text = p_tag.get_text(strip=True)
        return bool(re.match(r'^[\d½¼¾⅓⅔⅛/]', text))

    @staticmethod
    def _is_note_line(line: str) -> bool:
        """
        Строка считается примечанием (а не ингредиентом), если она:
        - длиннее 60 символов, И
        - не начинается с цифры/дроби, И
        - содержит хотя бы одну точку.
        """
        if len(line) > 60 and not re.match(r'^[\d½¼¾⅓⅔⅛/]', line) and '.' in line:
            return True
        return False

    # ---------------------------------------------------------------------------
    # Public extraction methods
    # ---------------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из h1.entry-title"""
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            return self.clean_text(h1.get_text())

        # Fallback: any h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания — первые абзацы до любого h4"""
        sections = self._parse_sections()
        parts = []
        for p in sections['description']:
            text = self.clean_text(p.get_text(separator=' ', strip=True))
            if text:
                parts.append(text)
        if parts:
            return ' '.join(parts)

        # Fallback: meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов в формате списка словарей:
        [{"name": "...", "amount": "...", "unit": "..."}]
        """
        sections = self._parse_sections()
        ingredients: list = []

        for p_tag in sections['ingredients']:
            # Paragraphs may be <br/>-separated multi-ingredient blocks or single-line items
            raw = p_tag.get_text(separator='\n', strip=True)
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]

            for line in lines:
                # Split merged lines like "1 feuille de laurier4 c. à. soupe de ..."
                # caused by missing <br/> tags in the source HTML.
                sub_lines = self._split_merged_ingredient_line(line)

                for sub_line in sub_lines:
                    sub_line = sub_line.strip()
                    if not sub_line:
                        continue
                    # Skip note-like sentences embedded in the ingredient paragraph
                    if self._is_note_line(sub_line):
                        logger.debug("Skipping note line in ingredients: %s", sub_line[:80])
                        continue

                    parsed = self.parse_ingredient(sub_line)
                    if parsed and parsed.get('name'):
                        ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    @staticmethod
    def _split_merged_ingredient_line(line: str) -> list:
        """
        Разбивает склеенные строки ингредиентов на отдельные.

        Например, «1 feuille de laurier4 c. à. soupe de pâte de tomate»
        возникает когда в HTML отсутствует тег <br/> между строками.
        Эвристика: если цифра идёт непосредственно за буквой → сплит.
        """
        # Split at boundary letter→digit (no space between them)
        # French letters include accented characters
        split = re.sub(
            r'([a-zA-ZàâäéèêëîïôùûüÿœæÀÂÄÉÈÊËÎÏÔÙÛÜŸŒÆ])(\d)',
            r'\1\n\2',
            line,
        )
        return [s.strip() for s in split.splitlines() if s.strip()]

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        sections = self._parse_sections()
        steps: list = []

        for p_tag in sections['instructions']:
            # Paragraphs may be <br/>-separated multi-step blocks or single sentences
            raw = p_tag.get_text(separator='\n', strip=True)
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            for line in lines:
                text = self.clean_text(line)
                if text:
                    steps.append(text)

        if steps:
            return ' '.join(steps)

        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из span.meta-category"""
        mc = self.soup.find(class_='meta-category')
        if mc:
            a = mc.find('a')
            if a:
                return self.clean_text(a.get_text())
            return self.clean_text(mc.get_text())

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки (нет структурированных данных на сайте)"""
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления (нет структурированных данных на сайте)"""
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени (нет структурированных данных на сайте)"""
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок / советов"""
        sections = self._parse_sections()
        parts = []

        for p_tag in sections['notes']:
            text = self.clean_text(p_tag.get_text(separator=' ', strip=True))
            if text:
                parts.append(text)

        if parts:
            return ' '.join(parts)

        # Fallback: look for "Conseils" / "Note" / "Astuces" keyword in entry-content
        ec = self._get_entry_content()
        if not ec:
            return None

        for p in ec.find_all('p'):
            text = p.get_text(strip=True)
            if re.match(r'Conseils?\s*(:|de\s)', text, re.IGNORECASE):
                # Collect the following siblings as notes
                note_parts = [self.clean_text(text)]
                for sib in p.next_siblings:
                    if not hasattr(sib, 'name') or not sib.name:
                        continue
                    if sib.name == 'h4':
                        break
                    sib_text = self.clean_text(sib.get_text(separator=' ', strip=True))
                    if sib_text:
                        note_parts.append(sib_text)
                if note_parts:
                    # Remove the heading line itself if it's just a label
                    if len(note_parts) > 1:
                        note_parts = note_parts[1:]
                    return ' '.join(note_parts)

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из div.meta-tags"""
        mt = self.soup.find(class_='meta-tags')
        if mt:
            tags = [
                self.clean_text(a.get_text())
                for a in mt.find_all('a')
                if a.get_text(strip=True)
            ]
            if tags:
                return ', '.join(tags)

        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Извлечение URL изображений рецепта.
        Приоритет: img.wp-post-image внутри div.meta-image.
        """
        urls: list = []

        # Primary: featured image with class wp-post-image inside meta-image div
        meta_image_div = self.soup.find(class_='meta-image')
        if meta_image_div:
            img = meta_image_div.find('img', class_='wp-post-image')
            if not img:
                img = meta_image_div.find('img', src=True)
            if img and img.get('src'):
                urls.append(img['src'])

        # Fallback: og:image meta tag
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])

        # Deduplicate while preserving order
        seen: set = set()
        unique: list = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    # ---------------------------------------------------------------------------
    # Ingredient parser
    # ---------------------------------------------------------------------------

    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсит строку ингредиента на французском языке.

        Поддерживаемые форматы:
        - «2 lb (908 gr) de cubes de bœuf» → {amount: "2", unit: "lb", name: "cubes de bœuf"}
        - «400 g de tagliatelles» → {amount: "400", unit: "g", name: "tagliatelles"}
        - «2 œufs» → {amount: "2", unit: null, name: "œufs"}
        - «Sel et poivre» → {amount: null, unit: null, name: "Sel et poivre"}
        """
        if not ingredient_text:
            return None

        text = self.clean_text(ingredient_text)

        # Remove parenthetical metric equivalents like "(908 gr)" or "(2,5 ml)"
        text_clean = re.sub(r'\([^)]*\)', '', text).strip()
        # Remove «(facultatif)» or similar
        text_clean = re.sub(r'\(facultatif\)', '', text_clean, flags=re.IGNORECASE).strip()

        # Normalize unicode fractions
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
        }
        for frac, repl in fraction_map.items():
            text_clean = text_clean.replace(frac, repl)

        # French units (ordered longest first to avoid partial matches).
        # Note: "feuilles", "branches", "tranches", "bottes" are intentionally
        # omitted because they form part of French ingredient names
        # (e.g. "feuille de laurier", "branche de céleri").
        french_units = [
            r'cuillères?\s+à\s+soupe',
            r'cuillères?\s+à\s+café',
            r'cuillères?\s+à\s+thé',
            r'c\.?\s*à\.?\s*soupe',
            r'c\.?\s*à\.?\s*café',
            r'c\.?\s*à\.?\s*thé',
            r'tasses?',
            r'litres?',
            r'sachets?',
            r'pièces?',
            r'pincées?',
            r'gousses?',
            r'kg',
            r'g\b',
            r'mg',
            r'ml',
            r'cl',
            r'dl',
            r'lb',
            r'oz',
        ]
        units_pattern = '|'.join(french_units)

        # Apostrophe: support both straight (U+0027) and curly (U+2019) forms
        apos = r"['\u2019]"

        # Amount patterns: integers, decimals, fractions, ranges like "650 à 750"
        amount_pat = r'([\d]+(?:[,.][\d]+)?(?:\s*(?:à|-)\s*[\d]+(?:[,.][\d]+)?)?(?:\s*/\s*[\d]+)?)'

        # Pattern 1: AMOUNT UNIT [de/d'/des/du/la/le] NAME
        pattern1 = rf'^{amount_pat}\s+({units_pattern})(?:\s+(?:de\s+|d{apos}\s*|du\s+|des\s+|la\s+|le\s+|les\s+))?(.+)$'
        match = re.match(pattern1, text_clean, re.IGNORECASE)
        if match:
            amount = self._normalize_amount(match.group(1))
            unit = self.clean_text(match.group(2))
            name = self.clean_text(match.group(3)) if match.group(3) else None
            if name:
                # Strip leading "d'" / "de " prepositions from name if regex didn't consume them
                name = re.sub(rf'^d{apos}', '', name, flags=re.IGNORECASE).strip()
                name = re.sub(r'^de\s+', '', name, flags=re.IGNORECASE).strip()
                return {'name': name, 'amount': amount, 'unit': unit}

        # Pattern 2: AMOUNT NAME (no unit)
        pattern2 = rf'^{amount_pat}\s+(.+)$'
        match2 = re.match(pattern2, text_clean, re.IGNORECASE)
        if match2:
            amount_str = match2.group(1)
            name = self.clean_text(match2.group(2))
            # Make sure the first group is truly a number
            if re.match(r'^[\d/.,\s]+$', amount_str.replace('à', '').replace('-', '')):
                amount = self._normalize_amount(amount_str)
                # Strip leading "d'" / "de " prepositions from name
                name = re.sub(rf'^d{apos}', '', name, flags=re.IGNORECASE).strip()
                name = re.sub(r'^de\s+', '', name, flags=re.IGNORECASE).strip()
                return {'name': name, 'amount': amount, 'unit': None}

        # Pattern 3: plain name without amount
        name = text_clean.strip()
        if name and len(name) >= 2:
            return {'name': name, 'amount': None, 'unit': None}

        return None

    @staticmethod
    def _normalize_amount(amount_str: str) -> Optional[str]:
        """Нормализует строку количества (заменяет «à» и пробелы на «-»)."""
        if not amount_str:
            return None
        normalized = amount_str.strip()
        # Normalize range separator "650 à 750" → "650-750"
        normalized = re.sub(r'\s+à\s+', '-', normalized)
        normalized = re.sub(r'\s+', '', normalized)
        return normalized if normalized else None

    # ---------------------------------------------------------------------------
    # Main entry point
    # ---------------------------------------------------------------------------

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            dict с полями: dish_name, description, ingredients, instructions,
            category, prep_time, cook_time, total_time, notes, image_urls, tags.
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception:
            logger.exception("Ошибка при извлечении dish_name")
            dish_name = None

        try:
            description = self.extract_description()
        except Exception:
            logger.exception("Ошибка при извлечении description")
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception:
            logger.exception("Ошибка при извлечении ingredients")
            ingredients = None

        try:
            instructions = self.extract_steps()
        except Exception:
            logger.exception("Ошибка при извлечении instructions")
            instructions = None

        try:
            category = self.extract_category()
        except Exception:
            logger.exception("Ошибка при извлечении category")
            category = None

        try:
            notes = self.extract_notes()
        except Exception:
            logger.exception("Ошибка при извлечении notes")
            notes = None

        try:
            tags = self.extract_tags()
        except Exception:
            logger.exception("Ошибка при извлечении tags")
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception:
            logger.exception("Ошибка при извлечении image_urls")
            image_urls = None

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
            'image_urls': image_urls,
            'tags': tags,
        }


def main() -> None:
    """Точка входа для обработки директории с HTML файлами recettesplat.com."""
    preprocessed_dir = os.path.join('preprocessed', 'recettesplat_com')

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(RecettesplatComExtractor, preprocessed_dir)
        return

    print(f'Директория не найдена: {preprocessed_dir}')
    print('Использование: python recettesplat_com.py')


if __name__ == '__main__':
    main()
