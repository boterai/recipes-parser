"""
Экстрактор данных рецептов для сайта mundoreceitas.com

Сайт построен на WordPress + WP Recipe Maker (WPRM).
Основной источник данных — WPRM HTML-блоки; JSON-LD Recipe используется как
дополнительный источник (доступен не на всех страницах).
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


class MundoreceitasComExtractor(BaseRecipeExtractor):
    """Экстрактор для mundoreceitas.com (WordPress + WPRM)"""

    # ------------------------------------------------------------------ #
    #  Вспомогательные методы                                             #
    # ------------------------------------------------------------------ #

    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Возвращает первый JSON-LD объект типа Recipe или None."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            t = item.get('@type', '')
                            if t == 'Recipe' or (isinstance(t, list) and 'Recipe' in t):
                                return item
                elif isinstance(data, dict):
                    t = data.get('@type', '')
                    if t == 'Recipe' or (isinstance(t, list) and 'Recipe' in t):
                        return data
                    if '@graph' in data:
                        for item in data['@graph']:
                            if not isinstance(item, dict):
                                continue
                            t = item.get('@type', '')
                            if t == 'Recipe' or (isinstance(t, list) and 'Recipe' in t):
                                return item
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.debug("JSON-LD parse error: %s", exc)
        return None

    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат.

        Args:
            duration: строка вида "PT20M" или "PT1H30M"

        Returns:
            Строка вида "20 minutes", "1 hour 30 minutes" и т.п., или None.
        """
        if not duration or not duration.startswith('PT'):
            return None

        body = duration[2:]  # убираем "PT"
        hours = 0
        minutes = 0

        h_match = re.search(r'(\d+)H', body)
        if h_match:
            hours = int(h_match.group(1))

        m_match = re.search(r'(\d+)M', body)
        if m_match:
            minutes = int(m_match.group(1))

        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")

        return ' '.join(parts) if parts else None

    def _wprm_time(self, time_type: str) -> Optional[str]:
        """
        Извлекает время из WPRM HTML-блока.

        Args:
            time_type: 'prep', 'cook' или 'total'

        Returns:
            Строка вида "15 minutes", "1 hour 30 minutes" или None.
        """
        # Пробуем получить значение из WPRM spans
        # Классы: wprm-recipe-prep_time-minutes / wprm-recipe-prep_time-hours
        css_key = time_type + '_time'  # prep_time / cook_time / total_time

        hours = 0
        minutes = 0

        hours_el = self.soup.find('span', class_=f'wprm-recipe-{css_key}-hours')
        if hours_el:
            # Убираем sr-only текст внутри
            sr = hours_el.find(class_=re.compile(r'sr-only|screen-reader', re.I))
            if sr:
                sr.decompose()
            val = hours_el.get_text(strip=True)
            if val.isdigit():
                hours = int(val)

        mins_el = self.soup.find('span', class_=f'wprm-recipe-{css_key}-minutes')
        if mins_el:
            sr = mins_el.find(class_=re.compile(r'sr-only|screen-reader', re.I))
            if sr:
                sr.decompose()
            val = mins_el.get_text(strip=True)
            if val.isdigit():
                minutes = int(val)

        if hours == 0 and minutes == 0:
            return None

        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        return ' '.join(parts)

    # ------------------------------------------------------------------ #
    #  Публичные методы                                                    #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда."""
        # 1. WPRM name element (h1, h2 или span с классом wprm-recipe-name)
        name_el = self.soup.find(
            lambda tag: tag.name in ('h1', 'h2', 'h3', 'span')
            and tag.get('class')
            and 'wprm-recipe-name' in ' '.join(tag.get('class', []))
        )
        if name_el:
            name = self.clean_text(name_el.get_text(separator=' '))
            # Strip subtitle after colon (e.g. ": 7 Passos", ": Receita Rápida e Fácil")
            name = re.sub(r'\s*:.*$', '', name).strip()
            return name if name else None

        # 2. JSON-LD
        ld = self._get_json_ld_recipe()
        if ld and ld.get('name'):
            name = self.clean_text(ld['name'])
            name = re.sub(r'\s*:.*$', '', name).strip()
            return name if name else None

        # 3. og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*[-–|].*$', '', title)
            return self.clean_text(title)

        # 4. <title>
        title_el = self.soup.find('title')
        if title_el:
            text = title_el.get_text()
            text = re.sub(r'\s*[-–|].*$', '', text)
            return self.clean_text(text)

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта."""
        # 1. WPRM summary block
        summary_el = self.soup.find(
            class_=lambda c: c and 'wprm-recipe-summary' in (
                ' '.join(c) if isinstance(c, list) else c
            )
        )
        if summary_el:
            text = self.clean_text(summary_el.get_text(separator=' '))
            if text:
                return text

        # 2. JSON-LD description
        ld = self._get_json_ld_recipe()
        if ld and ld.get('description'):
            return self.clean_text(ld['description'])

        # 3. meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из WPRM HTML-блоков.

        Каждый ингредиент возвращается в формате::

            {"name": "...", "amount": "...", "unit": "..."}

        Поле notes (WPRM) присоединяется к name через пробел.
        Если unit-span отсутствует, пытаемся извлечь единицу измерения из name-span.
        """
        ingredients = []

        # Portuguese units that may appear at the start of the name span
        # when WPRM omits a separate unit span (e.g. wprm_print pages).
        # Deliberately excludes "dentes" / "folhas" — these are descriptive
        # parts of the ingredient name, not measurement units.
        _PT_UNITS = re.compile(
            r'^(colher(?:es)?\s+de\s+sopa|colher(?:es)?\s+de\s+chá|'
            r'xícaras?|unidades?|kg|g\b|ml|l\b|litros?|gramas?|'
            r'pitadas?|fatias?|ramos?|'
            r'copos?|sachês?|pacotes?|latas?|colher(?:es)?)',
            re.IGNORECASE,
        )

        li_items = self.soup.find_all(
            'li',
            class_=lambda c: c and 'wprm-recipe-ingredient' in (
                ' '.join(c) if isinstance(c, list) else c
            )
        )

        for li in li_items:
            amount_span = li.find('span', class_='wprm-recipe-ingredient-amount')
            unit_span = li.find('span', class_='wprm-recipe-ingredient-unit')
            name_span = li.find('span', class_='wprm-recipe-ingredient-name')
            notes_span = li.find(
                'span',
                class_=lambda c: c and 'wprm-recipe-ingredient-notes' in (
                    ' '.join(c) if isinstance(c, list) else c
                )
            )

            name = self.clean_text(name_span.get_text(separator=' ')) if name_span else None
            notes = self.clean_text(notes_span.get_text(separator=' ')) if notes_span else None
            if name and notes:
                name = f"{name} {notes}"

            amount = self.clean_text(amount_span.get_text()) if amount_span else None
            unit = self.clean_text(unit_span.get_text()) if unit_span else None

            # Extend compound Portuguese units when name carries the second part of the unit.
            # e.g. unit="colheres", name="de sopa de amido" → unit="colheres de sopa", name="amido"
            # e.g. unit="colher", name="de chá de páprica"  → unit="colher de chá",    name="páprica"
            if unit and name:
                _compound = [
                    (r'^colher(?:es)?$', r'^(de\s+sopa)\s+', lambda u, s: u + ' de sopa'),
                    (r'^colher(?:es)?$', r'^(de\s+chá)\s+', lambda u, s: u + ' de chá'),
                ]
                for unit_pat, name_pat, unit_fn in _compound:
                    if re.match(unit_pat, unit, re.IGNORECASE):
                        m = re.match(name_pat, name, re.IGNORECASE)
                        if m:
                            unit = unit_fn(unit, m.group(1))
                            name = name[m.end():].strip()
                            # Strip leftover "de " connector
                            name = re.sub(r'^de\s+', '', name, flags=re.IGNORECASE).strip()
                            break

            # Strip Portuguese connector "de " / "d'" from the beginning of the name
            # (occurs when WPRM stores "1 xícara de farinha" as unit="xícara", name="de farinha")
            if name and unit:
                name = re.sub(r'^de\s+', '', name, flags=re.IGNORECASE)
                name = re.sub(r"^d['\u2019]", '', name, flags=re.IGNORECASE)
                name = name.strip()

            # When there is no unit span but the name starts with a Portuguese unit,
            # extract it (e.g. name="colher de chá cominho" → unit="colher de chá", name="cominho")
            if name and not unit:
                m = _PT_UNITS.match(name)
                if m:
                    unit = m.group(1).strip()
                    name = name[m.end():].strip()
                    # Strip leftover connector "de " at the start of the remaining name
                    name = re.sub(r'^de\s+', '', name, flags=re.IGNORECASE).strip()

            # Extract "a gosto" from name when there is no amount
            # (e.g. "sal a gosto" → name="sal", amount="a gosto")
            if name and not amount:
                m_ag = re.search(r'\s+(a\s+gosto)$', name, re.IGNORECASE)
                if m_ag:
                    amount = m_ag.group(1)
                    name = name[:m_ag.start()].strip()

            if not name:
                continue

            ingredients.append({
                "name": name,
                "amount": amount if amount else None,
                "unit": unit if unit else None,
            })

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        # Запасной вариант: JSON-LD recipeIngredient (строки)
        ld = self._get_json_ld_recipe()
        if ld and ld.get('recipeIngredient'):
            for raw in ld['recipeIngredient']:
                parsed = self._parse_ingredient_string(self.clean_text(str(raw)))
                if parsed:
                    ingredients.append(parsed)
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        return None

    def _parse_ingredient_string(self, text: str) -> Optional[dict]:
        """Разбирает строку вида '1 kg carne bovina' в словарь."""
        if not text:
            return None

        # Заменяем Unicode дроби
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
        }
        for frac, dec in fraction_map.items():
            text = text.replace(frac, dec)

        # Паттерн: [amount] [unit] name
        pattern = (
            r'^([\d\s/.,]+)?\s*'
            r'(kg|g|ml|l|xícara(?:s)?|colher(?:es)?\s+de\s+(?:sopa|chá)|'
            r'colher(?:es)?\s+de\s+chá|colher(?:es)?\s+de\s+sopa|'
            r'cups?|tablespoons?|teaspoons?|tbsp?|tsp?|'
            r'lb|lbs|oz|mg|litro(?:s)?|unidade(?:s)?|dente(?:s)?|'
            r'fatia(?:s)?|folha(?:s)?|ramo(?:s)?|pitada(?:s)?|'
            r'copo(?:s)?|sachê(?:s)?|pacote(?:s)?|lata(?:s)?|'
            r'colher(?:es)?|xícara(?:s)?|punhado(?:s)?)?\s*'
            r'(.+)'
        )

        match = re.match(pattern, text, re.IGNORECASE)
        if not match:
            return {"name": text, "amount": None, "unit": None}

        amount_str, unit, name = match.groups()

        amount = amount_str.strip() if amount_str else None
        unit = unit.strip() if unit else None
        name = re.sub(r'\([^)]*\)', '', name or '').strip()
        name = re.sub(r'\s+', ' ', name).strip()

        if not name:
            return None

        return {"name": name, "amount": amount, "unit": unit}

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления."""
        steps = []

        # 1. WPRM instruction list items
        li_items = self.soup.find_all(
            'li',
            class_=lambda c: c and 'wprm-recipe-instruction' in (
                ' '.join(c) if isinstance(c, list) else c
            )
        )
        for li in li_items:
            # Prefer wprm-recipe-instruction-text div if present
            text_el = li.find(
                class_=lambda c: c and 'wprm-recipe-instruction-text' in (
                    ' '.join(c) if isinstance(c, list) else c
                )
            )
            raw = (text_el or li).get_text(separator=' ', strip=True)
            text = self.clean_text(raw)
            if text:
                steps.append(text)

        if steps:
            numbered = [f"{i}. {s}" for i, s in enumerate(steps, 1)]
            return ' '.join(numbered)

        # 2. JSON-LD recipeInstructions
        ld = self._get_json_ld_recipe()
        if ld and ld.get('recipeInstructions'):
            instructions = ld['recipeInstructions']
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and step.get('text'):
                        steps.append(f"{idx}. {self.clean_text(step['text'])}")
                    elif isinstance(step, str):
                        steps.append(f"{idx}. {self.clean_text(step)}")
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            if steps:
                return ' '.join(steps)

        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда."""
        # 1. WPRM course span
        course_el = self.soup.find('span', class_='wprm-recipe-course')
        if course_el:
            return self.clean_text(course_el.get_text())

        # 2. JSON-LD recipeCategory
        ld = self._get_json_ld_recipe()
        if ld:
            cat = ld.get('recipeCategory')
            if cat:
                if isinstance(cat, list):
                    return ', '.join(str(c) for c in cat)
                return self.clean_text(str(cat))

        # 3. article:section meta
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки."""
        # 1. WPRM HTML
        result = self._wprm_time('prep')
        if result:
            return result

        # 2. JSON-LD
        ld = self._get_json_ld_recipe()
        if ld and ld.get('prepTime'):
            return self.parse_iso_duration(ld['prepTime'])

        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления."""
        result = self._wprm_time('cook')
        if result:
            return result

        ld = self._get_json_ld_recipe()
        if ld and ld.get('cookTime'):
            return self.parse_iso_duration(ld['cookTime'])

        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени приготовления."""
        result = self._wprm_time('total')
        if result:
            return result

        ld = self._get_json_ld_recipe()
        if ld and ld.get('totalTime'):
            return self.parse_iso_duration(ld['totalTime'])

        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок (WPRM notes block)."""
        # div.wprm-recipe-notes (не контейнер, а сам блок с текстом)
        notes_div = self.soup.find(
            'div',
            class_=lambda c: c and 'wprm-recipe-notes' in (
                ' '.join(c) if isinstance(c, list) else c
            ) and 'container' not in (
                ' '.join(c) if isinstance(c, list) else c
            )
        )
        if notes_div:
            # Заменяем <br> на пробел для слитного текста
            for br in notes_div.find_all('br'):
                br.replace_with(' ')
            text = self.clean_text(notes_div.get_text(separator=' '))
            if text:
                return text

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из WPRM keyword block или JSON-LD keywords."""
        # 1. WPRM keyword span inside keyword-container (sibling of label span)
        keyword_container = self.soup.find(
            class_=lambda c: c and 'wprm-recipe-keyword-container' in (
                ' '.join(c) if isinstance(c, list) else c
            )
        )
        if keyword_container:
            kw_span = keyword_container.find(
                'span',
                class_=lambda c: c and 'wprm-recipe-keyword' in (
                    ' '.join(c) if isinstance(c, list) else c
                ) and 'label' not in (
                    ' '.join(c) if isinstance(c, list) else c
                )
            )
            if kw_span:
                raw = self.clean_text(kw_span.get_text(separator=''))
                if raw:
                    tags = [t.strip() for t in raw.split(',') if t.strip()]
                    return ', '.join(tags) if tags else None

        # 2. JSON-LD keywords
        ld = self._get_json_ld_recipe()
        if ld and ld.get('keywords'):
            raw = ld['keywords']
            if isinstance(raw, list):
                raw = ', '.join(str(k) for k in raw)
            tags = [t.strip() for t in str(raw).split(',') if t.strip()]
            return ', '.join(tags) if tags else None

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта."""
        urls: list[str] = []

        # 1. JSON-LD Recipe.image (наиболее полный список)
        ld = self._get_json_ld_recipe()
        if ld and ld.get('image'):
            img = ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        url = item.get('url') or item.get('contentUrl')
                        if url:
                            urls.append(url)
            elif isinstance(img, dict):
                url = img.get('url') or img.get('contentUrl')
                if url:
                    urls.append(url)

        # 2. og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # 3. twitter:image
        tw_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if tw_image and tw_image.get('content'):
            urls.append(tw_image['content'])

        if not urls:
            return None

        # Дедупликация с сохранением порядка
        seen: set[str] = set()
        unique: list[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с полями: dish_name, description, ingredients, instructions,
            category, prep_time, cook_time, total_time, notes, tags, image_urls.
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception as exc:
            logger.warning("dish_name extraction failed: %s", exc)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as exc:
            logger.warning("description extraction failed: %s", exc)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as exc:
            logger.warning("ingredients extraction failed: %s", exc)
            ingredients = None

        try:
            instructions = self.extract_steps()
        except Exception as exc:
            logger.warning("instructions extraction failed: %s", exc)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as exc:
            logger.warning("category extraction failed: %s", exc)
            category = None

        try:
            notes = self.extract_notes()
        except Exception as exc:
            logger.warning("notes extraction failed: %s", exc)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as exc:
            logger.warning("tags extraction failed: %s", exc)
            tags = None

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


def main() -> None:
    """Точка входа: обрабатывает директорию preprocessed/mundoreceitas_com."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "mundoreceitas_com")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(MundoreceitasComExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python mundoreceitas_com.py")


if __name__ == "__main__":
    main()
