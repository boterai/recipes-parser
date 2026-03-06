"""
Экстрактор данных рецептов для сайта umlynarzy.pl
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


class UmlynarzyPlExtractor(BaseRecipeExtractor):
    """Экстрактор для umlynarzy.pl"""

    # Mapping of Polish food words in oblique cases → nominative form
    _PL_FOOD_MAP = {
        # Genitive → nominative
        'mąki': 'mąka', 'drożdży': 'drożdże', 'wody': 'woda', 'oliwy': 'oliwa',
        'soli': 'sól', 'cukru': 'cukier', 'mleka': 'mleko', 'masła': 'masło',
        'boczku': 'boczek', 'cebuli': 'cebula', 'mięsa': 'mięso', 'wina': 'wino',
        'bulionu': 'bulion', 'makaronu': 'makaron', 'parmezanu': 'parmezan',
        'passaty': 'passata', 'selera': 'seler naciowy',
        'przecieru': 'przecier pomidorowy',
        'mięsa mielonego': 'mięso mielone',
        # Accusative → nominative
        'cebulę': 'cebula', 'marchewkę': 'marchew', 'marchewi': 'marchew',
        'mąkę': 'mąka', 'oliwę': 'oliwa', 'wodę': 'woda', 'passatę': 'passata',
        # Instrumental → nominative
        'parmezanem': 'parmezan', 'solą': 'sól', 'masłem': 'masło',
        'mąką': 'mąka', 'mlekiem': 'mleko',
        # Nominative self-mappings (used for instruction-text word scan)
        'marchew': 'marchew', 'bulion': 'bulion', 'passata': 'passata',
        'parmezan': 'parmezan', 'makaron': 'makaron', 'cebula': 'cebula',
        'boczek': 'boczek', 'masło': 'masło', 'mleko': 'mleko',
        'mąka': 'mąka', 'woda': 'woda', 'oliwa': 'oliwa', 'sól': 'sól',
        'cukier': 'cukier', 'mięso': 'mięso', 'wino': 'wino',
        'drożdże': 'drożdże',
    }

    # Bold words that are units rather than ingredient names
    _UNIT_BOLD_WORDS = frozenset({
        'łyżeczka', 'łyżka', 'szklanka', 'łyżeczki', 'łyżki', 'szklanki',
        'łyżeczkę', 'łyżkę', 'szklankę',
    })

    # Bold words/phrases that are not food ingredients
    _NON_FOOD_BOLD = frozenset({
        'składnik', 'składniki', 'składników', 'typ', 'sprawdzaj', 'ilość', 'rola',
        'rodzaj', 'ważna', 'płaska', 'kremowa', 'kremowa baza', 'sos', 'warzywa',
        'mięsny', 'baza', 'przepisowi', 'czas', 'minuty', 'stopni',
        'daniu z makaronu',
    })

    def _normalize_pl_food(self, word: str) -> Optional[str]:
        """Map a Polish food word from an oblique case form to nominative"""
        return self._PL_FOOD_MAP.get(word.lower().strip())

    def _get_main_content(self):
        """Возвращает основной блок контента страницы (наибольший div.entry-content)"""
        entries = self.soup.find_all('div', class_=lambda x: x and 'entry-content' in x)
        if not entries:
            return self.soup
        return max(entries, key=lambda e: len(e.get_text()))

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем h1 заголовок
        h1 = self.soup.find('h1', class_=re.compile(r'page-title|entry-title|post-title', re.I))
        if not h1:
            h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        # Из og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффикс " - U młynarzy..."
            title = re.sub(r'\s*[-–|]\s*U m[lł]ynarzy.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            # Убираем обрезку вида "... [...] " или "… [...]"
            desc = re.sub(r'\s*[\[…\]]+\s*$', '', desc).strip()
            desc = re.sub(r'\s*\.\.\.\s*$', '', desc).strip()
            # Убираем trailing heading artifacts (e.g. "Czego potrzebujesz")
            desc = re.sub(r'\s+\w[\w\s]{0,40}$', lambda m: m.group() if '.' in m.group() else '', desc)
            return self.clean_text(desc.strip())

        # Из JSON-LD WebPage description
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                items = data.get('@graph', [data]) if isinstance(data, dict) else data
                for item in (items if isinstance(items, list) else [items]):
                    if isinstance(item, dict) and item.get('@type') == 'WebPage':
                        wp_desc = item.get('description')
                        if wp_desc:
                            return self.clean_text(wp_desc)
            except (json.JSONDecodeError, AttributeError):
                continue

        # Из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        return None

    def _parse_ingredient_text(self, text: str) -> dict:
        """
        Разбирает текст ингредиента на name/amount/unit.

        Форматы:
        - "300-450g mąki" → name="mąka", amount="300-450", unit="g"
        - "Marchew – 500 g" → name="Marchew", amount="500", unit="g"
        - "Jajka kurze – najlepiej w temperaturze pokojowej, rozmiar M lub L"
          → name="Jajka kurze", amount=None, unit="M lub L"
        - "szczypta cukru" → name="cukier", amount="szczypta", unit=None
        """
        text = self.clean_text(text)
        if not text:
            return {"name": None, "amount": None, "unit": None}

        # Шаблоны единиц измерения (польские)
        units = (
            r'kg|g|dag|mg|l|ml|dl|cl|łyżki|łyżka|łyżkę|łyżeczki|łyżeczka|łyżeczkę'
            r'|szklanki|szklanka|szklankę|garści|garść|sztuki|sztuk|sztuka|szt\.'
            r'|plaster|plastry|plasterki|gałązki|gałązka|ząbki|ząbek|liście|liść'
            r'|opakowanie|paczka|puszka|słoik'
        )

        # Формат: "name – amount unit" или "name – description, rozmiar X"
        dash_split = re.split(r'\s*[–—-]\s+', text, maxsplit=1)
        if len(dash_split) == 2:
            name_part = dash_split[0].strip()
            rest = dash_split[1].strip()

            # Попробуем извлечь amount/unit из правой части
            amount_match = re.search(
                r'(\d[\d\s,./½¼¾\-–]*)\s*(' + units + r')',
                rest, re.IGNORECASE
            )
            if amount_match:
                amount = amount_match.group(1).strip()
                unit = amount_match.group(2).strip()
                return {"name": name_part, "amount": amount, "unit": unit}

            # Ищем "rozmiar X Y Z" (может быть несколько слов, напр. "M lub L")
            size_match = re.search(r'rozmiar\s+(.+?)(?:,|$)', rest, re.IGNORECASE)
            if size_match:
                return {"name": name_part, "amount": None, "unit": size_match.group(1).strip()}

            # Просто название без количества
            return {"name": name_part, "amount": None, "unit": None}

        # Формат: "amount unit name" или "amount unit of name"
        amount_unit_match = re.match(
            r'^(szczypta|odrobina|garść|pęczek|kilka|trochę|½|¼|¾|\d[\d\s,./\-–]*)\s+'
            r'(' + units + r')\s+(.+)$',
            text, re.IGNORECASE
        )
        if amount_unit_match:
            return {
                "name": self.clean_text(amount_unit_match.group(3)),
                "amount": amount_unit_match.group(1).strip(),
                "unit": amount_unit_match.group(2).strip(),
            }

        # Формат: "amount unit" в любом месте строки (name первое слово)
        inline_match = re.search(
            r'(\d[\d\s,./½¼¾\-–]*)\s*(' + units + r')\b\s*(.+)?',
            text, re.IGNORECASE
        )
        if inline_match:
            name_candidate = text[:inline_match.start()].strip() or (inline_match.group(3) or '').strip()
            return {
                "name": self.clean_text(name_candidate) if name_candidate else None,
                "amount": inline_match.group(1).strip(),
                "unit": inline_match.group(2).strip(),
            }

        # Нет структурированных данных — просто название
        return {"name": text, "amount": None, "unit": None}

    def _extract_ingredients_from_table(self, table) -> list:
        """Извлечение ингредиентов из таблицы вида Składnik | Ilość"""
        ingredients = []
        rows = table.find_all('tr')
        if not rows:
            return ingredients

        # Проверяем заголовки
        headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(['th', 'td'])]
        if not headers or not any(kw in ' '.join(headers) for kw in ['składnik', 'ilość', 'ingredient']):
            return ingredients

        name_idx = next((i for i, h in enumerate(headers) if 'składnik' in h or 'ingredient' in h), 0)
        amount_idx = next((i for i, h in enumerate(headers) if 'ilość' in h or 'amount' in h), 1)

        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            if len(cells) <= name_idx:
                continue
            name = self.clean_text(cells[name_idx].get_text())
            if not name:
                continue

            amount_text = ''
            if len(cells) > amount_idx:
                amount_text = self.clean_text(cells[amount_idx].get_text())

            # Парсим amount и unit из строки вида "500 g", "4 łyżki", "1 kg (mrożone) / 700 g (świeże)"
            if amount_text:
                amt_match = re.match(
                    r'^(\d[\d\s,./½¼¾\-–]*)\s*(kg|g|dag|ml|l|dl|łyżki?|łyżeczki?|szklanki?|sztuk[ia]?|szt\.?|łyżkę|łyżeczkę|szklankę)?(.*)$',
                    amount_text, re.IGNORECASE
                )
                if amt_match:
                    amount = amt_match.group(1).strip()
                    unit_base = (amt_match.group(2) or '').strip()
                    remainder = (amt_match.group(3) or '').strip()
                    unit = (unit_base + ' ' + remainder).strip() if remainder else unit_base
                    ingredients.append({"name": name, "amount": amount, "unit": unit or None})
                else:
                    ingredients.append({"name": name, "amount": None, "unit": amount_text})
            else:
                ingredients.append({"name": name, "amount": None, "unit": None})

        return ingredients

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        main_content = self._get_main_content()

        # 1. Ищем таблицу со Składnik/Ilość
        for table in main_content.find_all('table'):
            rows = table.find_all('tr')
            if rows:
                headers_text = rows[0].get_text(strip=True).lower()
                if 'składnik' in headers_text or 'ilość' in headers_text:
                    ingredients = self._extract_ingredients_from_table(table)
                    if ingredients:
                        return json.dumps(ingredients, ensure_ascii=False)

        # 2. Ищем список после заголовка "Składniki" / "Czego potrzebujesz"
        heading_patterns = re.compile(
            r'sk[lł]adniki|czego potrzebujesz|sk[lł]adnik[io]|potrzebne sk[lł]adniki',
            re.IGNORECASE
        )
        for heading in main_content.find_all(['h2', 'h3', 'h4'], string=heading_patterns):
            sibling = heading.find_next_sibling()
            while sibling and sibling.name not in ['h2', 'h3', 'h4']:
                if sibling.name in ['ul', 'ol']:
                    items = sibling.find_all('li')
                    ingredients = []
                    for li in items:
                        text = self.clean_text(li.get_text(separator=' '))
                        if text:
                            parsed = self._parse_ingredient_text(text)
                            if parsed.get('name'):
                                ingredients.append(parsed)
                    if ingredients:
                        return json.dumps(ingredients, ensure_ascii=False)
                sibling = sibling.find_next_sibling()

        # 3. Fallback: извлечение из параграфов раздела с составом (по HTML-элементам)
        # Собираем элементы из ВСЕХ подходящих секций, затем делаем одну экстракцию
        ingredient_section_patterns = re.compile(
            r'wybór sk[lł]adników|sk[lł]adniki|sos boloński|sos rzeczamelowy'
            r'|jak przygotować|uk[lł]adanie warstw',
            re.IGNORECASE
        )
        all_section_elements: list = []
        seen_elements: set = set()

        def _collect_elements(heading_el):
            """Collect paragraph elements under a heading until the next h2."""
            collected = []
            sib = heading_el.find_next_sibling()
            while sib and sib.name not in ['h2']:
                if sib.name == 'p' and 'Zobacz także' not in sib.get_text():
                    if id(sib) not in seen_elements:
                        seen_elements.add(id(sib))
                        collected.append(sib)
                elif sib.name in ['h3', 'h4']:
                    sub = sib.find_next_sibling()
                    while sub and sub.name not in ['h2', 'h3', 'h4']:
                        if sub.name == 'p' and 'Zobacz także' not in sub.get_text():
                            if id(sub) not in seen_elements:
                                seen_elements.add(id(sub))
                                collected.append(sub)
                        sub = sub.find_next_sibling()
                sib = sib.find_next_sibling()
            return collected

        for heading in main_content.find_all(['h2', 'h3'], string=ingredient_section_patterns):
            all_section_elements.extend(_collect_elements(heading))

        if all_section_elements:
            ingredients = self._extract_ingredients_from_html_elements(all_section_elements)
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        return None

    def _extract_ingredients_from_html_elements(self, elements) -> list:
        """
        Extract ingredients from a list of BS4 paragraph elements using two passes.

        Pass 1 (amount-aware, for ingredient-description sections like pizza):
          A) Bold-text ingredient name + amount/unit from same paragraph
          B) "Płaska łyżeczka soli" – explicit unit-prefix + genitive food word
          C) "Szczypta/odrobina X" – indefinite quantities
          D) "Xg/ml foodword" – explicit amounts with mass/volume units

        Pass 2 (word scan, for instruction-style sections like lasagne):
          Scans every word in each paragraph against _PL_FOOD_MAP and adds any
          recognized food name that was not already found in pass 1.
          Also recognizes fixed compound food phrases regardless of order.
        """
        ingredients: list = []
        seen: set = set()
        unit_re = r'kg|dag|g\b|ml|dl|l\b|łyżk[ia]?|łyżecz[kni][ia]?|szklank[iae]?'

        def _find_amt_unit(text: str):
            m = re.search(r'(\d[\d\s,./\-–]*)\s*(' + unit_re + r')\b', text, re.I)
            if m:
                return m.group(1).strip(), m.group(2).strip()
            m2 = re.search(r'([½¼¾])\s*(' + unit_re + r')\b', text, re.I)
            if m2:
                return m2.group(1), m2.group(2)
            m3 = re.search(r'(p[lł]aska\s+)?(' + unit_re + r')\b', text, re.I)
            if m3 and m3.group(2):
                prefix = (m3.group(1) or '').strip()
                unit = (prefix + ' ' + m3.group(2)).strip() if prefix else m3.group(2)
                return None, unit
            return None, None

        def _add(name: str, amount=None, unit=None):
            key = name.lower().strip()
            if key and key not in seen and len(key) >= 2:
                seen.add(key)
                ingredients.append({"name": name, "amount": amount, "unit": unit})

        # ---- PASS 1: amount-aware extraction ----
        for el in elements:
            if el.name != 'p':
                continue
            para_text = el.get_text()

            # A: Bold word = ingredient name (1-2 words only); find amount/unit in paragraph
            for strong in el.find_all(['strong', 'b']):
                word = strong.get_text(strip=True)
                word_low = word.lower()
                # Skip unit words, non-food bold, and 3+ word adjectival phrases
                if (word_low in self._UNIT_BOLD_WORDS
                        or word_low in self._NON_FOOD_BOLD
                        or len(word_low) < 2
                        or len(word_low.split()) > 2):
                    continue
                normalized = self._normalize_pl_food(word_low) or word_low
                if normalized in self._NON_FOOD_BOLD:
                    continue
                amount, unit = _find_amt_unit(para_text)
                _add(normalized, amount, unit)

            # B: "Płaska łyżeczka soli" → sól, 1, płaska łyżeczka
            m = re.search(
                r'(p[lł]aska)\s+(łyżeczk[aią]?)\s+([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]{3,})\b',
                para_text, re.I
            )
            if m:
                food_gen = m.group(3).lower()
                normalized = self._normalize_pl_food(food_gen) or food_gen
                _add(normalized, '1', 'płaska łyżeczka')

            # C: "szczypta/odrobina X"
            for m in re.finditer(
                r'(szczypta|odrobina|garść)\s+([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]{3,})\b',
                para_text, re.I
            ):
                food_gen = m.group(2).lower()
                normalized = self._normalize_pl_food(food_gen) or food_gen
                _add(normalized, m.group(1).lower(), None)

            # D: "Xg/Xml foodword" with Polish case normalization
            for m in re.finditer(
                r'(\d[\d,./\-–]*)\s*(kg|dag|g\b|ml|dl)\s+([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]{3,})\b',
                para_text, re.I
            ):
                food_word = m.group(3).lower()
                if food_word in {'instant', 'świeżych', 'suchych', 'ciepłej', 'gorącej',
                                  'się', 'lub', 'nie', 'na', 'do', 'po'}:
                    continue
                normalized = self._normalize_pl_food(food_word) or food_word
                _add(normalized, m.group(1).strip(), m.group(2).strip())

        # ---- PASS 2: word scan for instruction-style sections ----
        # Fixed compound phrases (check substring in full paragraph text)
        _compound_phrases = [
            ('seler naciowy', 'seler naciowy'),
            ('przecier pomidorowy', 'przecier pomidorowy'),
            ('gałki muszkatołowej', 'gałka muszkatołowa'),
            ('gałka muszkatołowa', 'gałka muszkatołowa'),
            ('płaty makaronu', 'płaty makaronu'),
            ('mięso mielone', 'mięso mielone'),
            ('mięsa mielonego', 'mięso mielone'),
        ]
        for el in elements:
            if el.name != 'p':
                continue
            para_lower = el.get_text().lower()

            # Check compound phrases first so single-word scan doesn't split them
            for phrase, nom in _compound_phrases:
                if phrase in para_lower:
                    _add(nom)

            # Scan individual words against _PL_FOOD_MAP (both oblique and nominative forms)
            for w in re.findall(r'[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+', para_lower):
                normalized = self._normalize_pl_food(w)
                if normalized:
                    _add(normalized)

        return ingredients

    def _extract_ingredients_from_paragraphs(self, text: str) -> list:
        """Legacy text-based extraction; kept for backward compatibility."""
        # This is now superseded by _extract_ingredients_from_html_elements,
        # but kept in case callers pass plain text.
        return []

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        main_content = self._get_main_content()
        steps = []

        # 1. Ищем h3 с "Krok N" (нумерованные шаги)
        krok_headings = main_content.find_all(
            ['h3', 'h4'], string=re.compile(r'^krok\s+\d+', re.IGNORECASE)
        )
        if krok_headings:
            for heading in krok_headings:
                step_text_parts = []
                sibling = heading.find_next_sibling()
                while sibling and sibling.name not in ['h2', 'h3', 'h4']:
                    if sibling.name in ['p', 'div']:
                        txt = self.clean_text(sibling.get_text(separator=' '))
                        if txt and 'Zobacz także' not in txt:
                            step_text_parts.append(txt)
                    sibling = sibling.find_next_sibling()
                if step_text_parts:
                    steps.append(step_text_parts[0])  # берём первый параграф каждого шага
            if steps:
                numbered = [f"{i}. {s}" for i, s in enumerate(steps, 1)]
                return ' '.join(numbered)

        # 2. Ищем раздел с инструкциями по заголовку
        instruction_patterns = re.compile(
            r'instrukcja|jak przygotowa|krok po kroku|przygotowanie|sposób przygotowania',
            re.IGNORECASE
        )
        for heading in main_content.find_all(['h2', 'h3'], string=instruction_patterns):
            sibling = heading.find_next_sibling()
            while sibling and sibling.name != 'h2':
                if sibling.name in ['ol', 'ul']:
                    for li in sibling.find_all('li'):
                        txt = self.clean_text(li.get_text(separator=' '))
                        if txt:
                            steps.append(txt)
                elif sibling.name == 'p':
                    txt = self.clean_text(sibling.get_text(separator=' '))
                    if txt and 'Zobacz także' not in txt:
                        steps.append(txt)
                elif sibling.name in ['h3', 'h4']:
                    # собираем заголовки подшагов
                    step_title = self.clean_text(sibling.get_text())
                    next_sib = sibling.find_next_sibling()
                    while next_sib and next_sib.name not in ['h2', 'h3', 'h4']:
                        if next_sib.name == 'p':
                            txt = self.clean_text(next_sib.get_text(separator=' '))
                            if txt and 'Zobacz także' not in txt:
                                steps.append(txt)
                                break
                        next_sib = next_sib.find_next_sibling()
                sibling = sibling.find_next_sibling()

            if steps:
                break

        # 3. Fallback: ищем ключевые секции с описанием приготовления
        if not steps:
            prep_patterns = re.compile(
                r'sos boloński|sos beszamel|pieczeni|gotuj|smaż|podgrzej|rozgrzej|wyrabiaj|układaj|piecz',
                re.IGNORECASE
            )
            for p in main_content.find_all('p'):
                txt = self.clean_text(p.get_text(separator=' '))
                if txt and prep_patterns.search(txt) and len(txt) > 40 and 'Zobacz także' not in txt:
                    steps.append(txt)
            if steps:
                steps = steps[:6]  # ограничиваем количество шагов

        if not steps:
            return None

        # Добавляем нумерацию если её нет
        if not re.match(r'^\d+\.', steps[0]):
            steps = [f"{i}. {s}" for i, s in enumerate(steps, 1)]

        return ' '.join(steps)

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда"""
        # Из блока hero-section (первая ссылка на категорию)
        hero = self.soup.find('div', class_='hero-section')
        if hero:
            header = hero.find('header')
            if header:
                cat_link = header.find('a')
                if cat_link:
                    return self.clean_text(cat_link.get_text())

        # Из хлебных крошек
        breadcrumb = self.soup.find(class_=re.compile(r'breadcrumb', re.I))
        if breadcrumb:
            links = breadcrumb.find_all('a')
            # Берём последнюю ссылку категории (не "Strona główna")
            for link in reversed(links):
                text = self.clean_text(link.get_text())
                if text and 'strona g' not in text.lower():
                    return text

        # Из классов article (category-XXX)
        article = self.soup.find('article')
        if article:
            classes = article.get('class', [])
            for cls in classes:
                if cls.startswith('category-'):
                    cat = cls[len('category-'):]
                    cat = cat.replace('-', ' ').title()
                    return cat

        # Из meta article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])

        return None

    def _extract_time_from_text(self, text: str) -> Optional[str]:
        """Извлекает строку времени из текста (например '2 godziny 15 minut' → '2 hours 15 minutes')"""
        # Ищем паттерны: "X godzin(y) Y minut", "X godzin(y)", "X-Y minut", "X minut"
        pattern = re.search(
            r'(\d+)\s*godzin[ay]?\s*(?:i\s*)?(\d+)?\s*minut[y]?'
            r'|(\d+[-–]\d+)\s*minut[y]?'
            r'|(\d+)\s*minut[y]?'
            r'|(\d+)\s*godzin[ay]?',
            text, re.IGNORECASE
        )
        if not pattern:
            return None

        hours_h = pattern.group(1)
        mins_h = pattern.group(2)
        range_m = pattern.group(3)
        single_m = pattern.group(4)
        hours_only = pattern.group(5)

        if hours_h and mins_h:
            return f"{hours_h} hour{'s' if int(hours_h) > 1 else ''} {mins_h} minutes"
        elif hours_h:
            return f"{hours_h} hour{'s' if int(hours_h) > 1 else ''}"
        elif range_m:
            return f"{range_m} minutes"
        elif single_m:
            return f"{single_m} minutes"
        elif hours_only:
            return f"{hours_only} hour{'s' if int(hours_only) > 1 else ''}"
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        main_content = self._get_main_content()
        full_text = main_content.get_text()

        # Ищем явные упоминания времени подготовки
        prep_keywords = re.compile(
            r'czas przygotowania[:\s]+(.{3,50}?)(?:\.|,|\n|$)'
            # Достать из холодильника за X минут до готовки
            r'|wyjmij.{0,30}?lodówki.{0,60}?(\d+[-–]\d+\s*minut[ay]?)'
            r'|wyjmij.{0,30}?lodówki.{0,60}?(\d+\s*minut[ay]?)',
            re.IGNORECASE
        )
        for match in prep_keywords.finditer(full_text):
            for grp in match.groups():
                if grp:
                    result = self._extract_time_from_text(grp)
                    if result:
                        return result

        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        main_content = self._get_main_content()
        full_text = main_content.get_text()

        # 1. Ищем в тексте (приоритет над таблицей)
        cook_keywords = re.compile(
            r'czas gotowania[:\s]+(.{3,50}?)(?:\.|,|\n|$)'
            r'|gotuj(?:emy)? przez\s+(\d[\d,./½¼¾\-–]*\s*(?:godzin[ay]?|minut[ay]?))'
            r'|duś\b.{0,30}?(\d+\s*godzin[ay]?)'
            r'|wystarczy\s+(?:ok(?:o[lł]o)?\s+)?(\d+[-–]\d+\s*minut[ay]?)'
            r'|wystarczy\s+(?:ok(?:o[lł]o)?\s+)?(\d+\s*minut[ay]?)',
            re.IGNORECASE
        )
        for match in cook_keywords.finditer(full_text):
            for grp in match.groups():
                if grp:
                    result = self._extract_time_from_text(grp)
                    if result:
                        return result

        # 2. Fallback: ищем в таблице "Czas pieczenia"
        for table in main_content.find_all('table'):
            header_row = table.find('tr')
            if not header_row:
                continue
            headers = [th.get_text(strip=True).lower() for th in header_row.find_all(['th', 'td'])]
            if 'czas pieczenia' in headers or 'czas gotowania' in headers:
                time_col = next((i for i, h in enumerate(headers) if 'czas' in h), None)
                if time_col is not None:
                    data_rows = table.find_all('tr')[1:]
                    if data_rows:
                        cells = data_rows[0].find_all(['td', 'th'])
                        if len(cells) > time_col:
                            val = self.clean_text(cells[time_col].get_text())
                            result = self._extract_time_from_text(val)
                            if result:
                                return result

        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        main_content = self._get_main_content()
        full_text = main_content.get_text()

        total_keywords = re.compile(
            r'czas ca[lł]kowity[:\s]+(.{3,50}?)(?:\.|,|\n|$)'
            r'|[lł][aą]cznie.*?(\d[\d\s\-–]*(?:minut[ay]?|godzin[ay]?))',
            re.IGNORECASE
        )
        for match in total_keywords.finditer(full_text):
            for grp in match.groups():
                if grp:
                    result = self._extract_time_from_text(grp)
                    if result:
                        return result
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов"""
        main_content = self._get_main_content()

        # Ищем раздел "Porady" / "Wskazówki" / "Tips"
        notes_patterns = re.compile(r'praktyczne porady|porady|wskazówki|tip', re.IGNORECASE)
        for heading in main_content.find_all(['h2', 'h3', 'h4'], string=notes_patterns):
            notes_parts = []
            sibling = heading.find_next_sibling()
            while sibling and sibling.name not in ['h2']:
                if sibling.name == 'p':
                    txt = self.clean_text(sibling.get_text(separator=' '))
                    if txt and 'Zobacz także' not in txt:
                        notes_parts.append(txt)
                elif sibling.name in ['ul', 'ol']:
                    for li in sibling.find_all('li'):
                        txt = self.clean_text(li.get_text(separator=' '))
                        if txt:
                            notes_parts.append(txt)
                elif sibling.name in ['h3', 'h4']:
                    # Собираем первый параграф из каждой подсекции
                    sub_sib = sibling.find_next_sibling()
                    while sub_sib and sub_sib.name not in ['h2', 'h3', 'h4']:
                        if sub_sib.name == 'p':
                            txt = self.clean_text(sub_sib.get_text(separator=' '))
                            if txt and 'Zobacz także' not in txt:
                                notes_parts.append(txt)
                                break
                        sub_sib = sub_sib.find_next_sibling()
                sibling = sibling.find_next_sibling()
            if notes_parts:
                return ' '.join(notes_parts[:3])  # ограничиваем первыми 3 абзацами

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Из div.entry-tags
        tags_div = self.soup.find('div', class_='entry-tags')
        if tags_div:
            links = tags_div.find_all('a')
            if links:
                tags = [self.clean_text(link.get_text().lstrip('#')) for link in links]
                tags = [t for t in tags if t]
                if tags:
                    return ', '.join(tags)

        # Из JSON-LD Article keywords
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                items = data.get('@graph', [data]) if isinstance(data, dict) else data
                for item in (items if isinstance(items, list) else [items]):
                    if isinstance(item, dict) and item.get('@type') == 'Article':
                        keywords = item.get('keywords', [])
                        if keywords:
                            if isinstance(keywords, list):
                                return ', '.join(keywords)
                            return str(keywords)
            except (json.JSONDecodeError, AttributeError):
                continue

        # Из article CSS классов tag-*
        article = self.soup.find('article')
        if article:
            classes = article.get('class', [])
            tags = []
            for cls in classes:
                if cls.startswith('tag-') and not re.match(r'^tag-link-', cls):
                    tag = cls[4:].replace('-', ' ')
                    tags.append(tag)
            if tags:
                return ', '.join(tags)

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls = []

        # Из JSON-LD (ImageObject)
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                items = data.get('@graph', [data]) if isinstance(data, dict) else data
                for item in (items if isinstance(items, list) else [items]):
                    if not isinstance(item, dict):
                        continue
                    # thumbnailUrl
                    thumb = item.get('thumbnailUrl')
                    if thumb and thumb not in urls:
                        urls.append(thumb)
                    # ImageObject
                    if item.get('@type') == 'ImageObject':
                        url = item.get('url') or item.get('contentUrl')
                        if url and url not in urls:
                            urls.append(url)
            except (json.JSONDecodeError, AttributeError):
                continue

        # Из og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)

        # Из основного контента (img теги)
        main_content = self._get_main_content()
        for img in main_content.find_all('img'):
            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
            if src and src.startswith('http') and src not in urls:
                urls.append(src)

        return ','.join(urls) if urls else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта

        Returns:
            Словарь с данными рецепта
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception as e:
            logger.warning("Ошибка извлечения dish_name: %s", e)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as e:
            logger.warning("Ошибка извлечения description: %s", e)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as e:
            logger.warning("Ошибка извлечения ingredients: %s", e)
            ingredients = None

        try:
            instructions = self.extract_steps()
        except Exception as e:
            logger.warning("Ошибка извлечения instructions: %s", e)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as e:
            logger.warning("Ошибка извлечения category: %s", e)
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception as e:
            logger.warning("Ошибка извлечения prep_time: %s", e)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception as e:
            logger.warning("Ошибка извлечения cook_time: %s", e)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception as e:
            logger.warning("Ошибка извлечения total_time: %s", e)
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception as e:
            logger.warning("Ошибка извлечения notes: %s", e)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as e:
            logger.warning("Ошибка извлечения tags: %s", e)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as e:
            logger.warning("Ошибка извлечения image_urls: %s", e)
            image_urls = None

        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "notes": notes,
            "tags": tags,
            "image_urls": image_urls,
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os

    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "umlynarzy_pl")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(UmlynarzyPlExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python umlynarzy_pl.py")


if __name__ == "__main__":
    main()
