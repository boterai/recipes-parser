"""
Экстрактор данных рецептов для сайта fittkonyha.com
Венгерский блог о рецептах без белой муки и добавленного сахара (WordPress).
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

from bs4 import Tag

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class FittkonyhaCom(BaseRecipeExtractor):
    """Экстрактор для fittkonyha.com"""

    # ------------------------------------------------------------------ #
    #  Вспомогательные: время                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_hungarian_time(text: str) -> Optional[str]:
        """
        Пытается извлечь время из текста на венгерском языке.

        Шаблоны:
          - «35 percig»  →  «35 minutes»
          - «40-45 percig»  →  «40-45 minutes»
          - «1 óra 15 perc»  →  «75 minutes»
          - «15 percet»  →  «15 minutes»

        Returns:
            Строка вида «N minutes» / «N-M minutes» или None.
        """
        if not text:
            return None

        # Диапазон минут: «40-45 perc»
        m = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*perc', text, re.IGNORECASE)
        if m:
            return f"{m.group(1)}-{m.group(2)} minutes"

        # Часы + минуты: «1 óra 15 perc»
        m = re.search(r'(\d+)\s*óra\s*(\d+)\s*perc', text, re.IGNORECASE)
        if m:
            total = int(m.group(1)) * 60 + int(m.group(2))
            return f"{total} minutes"

        # Только часы: «1 óra»
        m = re.search(r'(\d+)\s*óra', text, re.IGNORECASE)
        if m:
            total = int(m.group(1)) * 60
            return f"{total} minutes"

        # Только минуты: «35 percig», «15 percet», «2 perc»
        m = re.search(r'(\d+)\s*perc', text, re.IGNORECASE)
        if m:
            return f"{m.group(1)} minutes"

        return None

    # ------------------------------------------------------------------ #
    #  Вспомогательные: ингредиенты                                        #
    # ------------------------------------------------------------------ #

    # Известные венгерские единицы измерения (длинные варианты раньше)
    _HU_UNITS = [
        "csapott tk", "csapott ek", "csapott kk",
        "tk", "ek", "kk", "dl", "ml", "cl", "l",
        "dkg", "kg", "g",
        "db", "cs", "csomag", "csipetnyi", "csipet",
        "marék", "csokor", "gerezd", "szelet",
        "teáskanál", "evőkanál",
    ]
    # Регулярное выражение для захвата «N unit name» или «name»
    _UNIT_RE = re.compile(
        r'^([\d.,/½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘]+(?:\s*[-–]\s*[\d.,/½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘]+)?)\s+'
        r'(' + '|'.join(re.escape(u) for u in _HU_UNITS) + r')\s+'
        r'(.+)',
        re.IGNORECASE,
    )
    # Альтернатива: «N name» (нет единицы)
    _AMOUNT_RE = re.compile(
        r'^([\d.,/½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘]+(?:\s*[-–]\s*[\d.,/½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘]+)?)\s+'
        r'(.+)',
        re.IGNORECASE,
    )

    def _parse_ingredient_line(self, text: str) -> Optional[dict]:
        """
        Разбирает одну строку ингредиента в {name, amount, unit}.

        Поддерживаемые форматы:
          «70 g zabpehelyliszt»          →  name=zabpehelyliszt, amount=70, unit=g
          «1 csapott tk sütőpor»         →  name=sütőpor, amount=1, unit=csapott tk
          «1 tojás»                      →  name=tojás,  amount=1,  unit=None
          «csipetnyi só»                 →  name=só,     amount=csipetnyi, unit=None
          «fél g kókuszolaj»             →  name=kókuszolaj, amount=0.5, unit=g
          «só»                           →  name=só,     amount=None, unit=None
        """
        if not text:
            return None

        text = self.clean_text(text)
        if not text:
            return None

        # Замена «fél» на «0.5» и похожих слов
        text = re.sub(r'\bfél\b', '0.5', text, flags=re.IGNORECASE)

        # Пробуем «N unit name»
        m = self._UNIT_RE.match(text)
        if m:
            amount_raw, unit, name = m.group(1), m.group(2), m.group(3)
            name = self._clean_ingredient_name(name)
            return {"name": name, "amount": amount_raw.strip(), "unit": unit.strip()} if name else None

        # Пробуем «csipetnyi/kevés/ízlés szerint name»  — специальные слова-количества
        m = re.match(
            r'^(csipetnyi|csipet|ízlés szerint|kevés|szükség szerint|szükség esetén)\s+(.+)',
            text, re.IGNORECASE,
        )
        if m:
            amount_word, name = m.group(1), m.group(2)
            name = self._clean_ingredient_name(name)
            return {"name": name, "amount": amount_word.strip(), "unit": None} if name else None

        # Пробуем «N name» (без единицы)
        m = self._AMOUNT_RE.match(text)
        if m:
            amount_raw, name = m.group(1), m.group(2)
            name = self._clean_ingredient_name(name)
            return {"name": name, "amount": amount_raw.strip(), "unit": None} if name else None

        # Всё остальное → только name
        name = self._clean_ingredient_name(text)
        return {"name": name, "amount": None, "unit": None} if name else None

    @staticmethod
    def _clean_ingredient_name(name: str) -> str:
        """Убирает пояснения в скобках и лишние символы из названия."""
        # Убираем только дополнительные пояснения (но не единицы в скобках)
        name = re.sub(r'\([^)]*\)', '', name)
        # Убираем «VAGY helyette …» (или вместо …)
        name = re.sub(r'\s*VAGY\s+helyette\s+.*', '', name, flags=re.IGNORECASE)
        # Убираем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip(' ,;.')
        return name

    def _get_ingredient_text(self, li) -> str:
        """Получить текст элемента списка без скобочных пояснений-ссылок."""
        texts = []
        for child in li.descendants:
            if isinstance(child, Tag):
                continue  # пропускаем теги, обрабатываем только текстовые узлы
            text = str(child).strip()
            if text:
                texts.append(text)
        return ' '.join(texts)

    # ------------------------------------------------------------------ #
    #  Публичные методы extract_*                                          #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда."""
        entry = self.soup.find('div', class_='entry-content')
        if entry:
            # Некоторые страницы используют h5 как заголовок рецепта
            h5 = entry.find('h5')
            if h5:
                return self.clean_text(h5.get_text())

        # Основной h1 (второй тег h1, первый обычно пустой)
        h1_tags = self.soup.find_all('h1')
        for h1 in h1_tags:
            text = self.clean_text(h1.get_text())
            if text:
                return text

        # Fallback: og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*[-–|]\s*FittKonyha.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title) or None

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта."""
        dish_name = self.extract_dish_name() or ''

        # Из первого содержательного <p> в entry-content (приоритет)
        entry = self.soup.find('div', class_='entry-content')
        if entry:
            stop_patterns = re.compile(
                r'facebook\.com|instagram\.com|twitter|youtube|fittkonyha\.info',
                re.IGNORECASE,
            )
            for p in entry.find_all('p'):
                text = self.clean_text(p.get_text())
                if not text or len(text) < 20:
                    continue
                if stop_patterns.search(text):
                    continue
                # Пропускаем заголовки/служебные параграфы
                if re.match(r'^(Hozzávalók|Szénhidrát|Kalória)', text, re.IGNORECASE):
                    continue
                # Пропускаем параграф, если он является просто повтором названия блюда
                if dish_name and text.lower().strip() == dish_name.lower().strip():
                    continue
                return text

        # Из JSON-LD WebPage description
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                graph = data.get('@graph', []) if isinstance(data, dict) else []
                for item in graph:
                    if item.get('@type') == 'WebPage' and item.get('description'):
                        desc = self.clean_text(item['description'])
                        # Пропускаем строки с ключевыми словами (запятые без глаголов)
                        if desc and len(desc) > 30 and not re.match(r'^[\w\s,]+,$', desc):
                            return desc
            except (json.JSONDecodeError, AttributeError):
                continue

        # Fallback: og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content']) or None

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов.

        Ищет <ul> после параграфа «Hozzávalók:» в блоке entry-content.
        """
        entry = self.soup.find('div', class_='entry-content')
        if not entry:
            logger.warning("entry-content не найден")
            return None

        ingredients = []
        children = list(entry.children)

        # Ищем маркер «Hozzávalók»
        found_marker = False
        for child in children:
            if not hasattr(child, 'name') or not child.name:
                continue
            if child.name == 'p':
                txt = child.get_text(strip=True).lower()
                if 'hozzávalók' in txt or 'hozzávaló' in txt:
                    found_marker = True
                    continue
            if found_marker and child.name == 'ul':
                for li in child.find_all('li'):
                    raw = self._get_ingredient_text(li)
                    parsed = self._parse_ingredient_line(raw)
                    if parsed:
                        ingredients.append(parsed)
                break

        # Fallback: просто первый <ul> в entry-content
        if not ingredients:
            first_ul = entry.find('ul')
            if first_ul:
                for li in first_ul.find_all('li'):
                    raw = self._get_ingredient_text(li)
                    parsed = self._parse_ingredient_line(raw)
                    if parsed:
                        ingredients.append(parsed)

        if not ingredients:
            logger.warning("Ингредиенты не найдены")
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def extract_instructions(self) -> Optional[str]:
        """
        Извлечение инструкций по приготовлению.

        Берёт параграф(ы) после первого <ul> в entry-content,
        которые не содержат только заголовки, калорийную информацию
        или ссылки на соцсети.
        """
        entry = self.soup.find('div', class_='entry-content')
        if not entry:
            return None

        stop_patterns = re.compile(
            r'facebook\.com|instagram\.com|twitter|youtube|fittkonyha\.info',
            re.IGNORECASE,
        )
        calorie_patterns = re.compile(
            r'szénhidrát\s+és\s+kalória|kcal|kalória',
            re.IGNORECASE,
        )

        children = list(entry.children)
        after_ul = False
        parts = []

        for child in children:
            if not hasattr(child, 'name') or not child.name:
                continue
            if child.name == 'ul':
                after_ul = True
                continue
            if after_ul and child.name == 'p':
                text = self.clean_text(child.get_text())
                if not text:
                    continue
                if stop_patterns.search(text):
                    break
                if calorie_patterns.search(text):
                    break
                if len(text) > 15:
                    parts.append(text)
            # hr закрывает инструкции
            if after_ul and child.name == 'hr':
                break

        if not parts:
            return None

        return ' '.join(parts)

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок.

        Короткие параграфы после основных инструкций (до hr или соцсетей).
        """
        entry = self.soup.find('div', class_='entry-content')
        if not entry:
            return None

        stop_patterns = re.compile(
            r'facebook\.com|instagram\.com|twitter|youtube|fittkonyha\.info',
            re.IGNORECASE,
        )
        calorie_patterns = re.compile(
            r'szénhidrát\s+és\s+kalória|kcal|kalória',
            re.IGNORECASE,
        )

        children = list(entry.children)
        after_ul = False
        instructions_found = False
        note_parts = []

        for child in children:
            if not hasattr(child, 'name') or not child.name:
                continue
            if child.name == 'ul':
                after_ul = True
                continue
            if after_ul and child.name == 'p':
                text = self.clean_text(child.get_text())
                if not text:
                    continue
                if stop_patterns.search(text):
                    break
                if calorie_patterns.search(text):
                    break
                # Первый «длинный» параграф — инструкции, последующие — заметки
                if not instructions_found:
                    if len(text) > 30:
                        instructions_found = True
                    continue
                # Это уже заметки
                if len(text) > 5:
                    note_parts.append(text)
            if after_ul and child.name == 'hr':
                break

        return ' '.join(note_parts) if note_parts else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из мета-блока entry-meta."""
        entry_meta = self.soup.find('div', class_='entry-meta')
        if entry_meta:
            cat_link = entry_meta.find('a', rel=re.compile(r'category'))
            if cat_link:
                return self.clean_text(cat_link.get_text())

        # Fallback: JSON-LD Article.articleSection
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                graph = data.get('@graph', []) if isinstance(data, dict) else []
                for item in graph:
                    if item.get('@type') == 'Article':
                        sections = item.get('articleSection', [])
                        if sections:
                            return sections[0] if isinstance(sections, list) else sections
            except (json.JSONDecodeError, AttributeError):
                continue

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из мета-блока entry-meta."""
        entry_meta = self.soup.find('div', class_='entry-meta')
        if entry_meta:
            # rel='tag' only — excludes links with rel='category tag'
            tag_links = [
                a for a in entry_meta.find_all('a')
                if a.get('rel') == ['tag']
            ]
            if tag_links:
                return ','.join(self.clean_text(a.get_text()) for a in tag_links)
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                graph = data.get('@graph', []) if isinstance(data, dict) else []
                for item in graph:
                    if item.get('@type') == 'Article':
                        kw = item.get('keywords', [])
                        if kw:
                            if isinstance(kw, list):
                                return ','.join(kw)
                            return kw
            except (json.JSONDecodeError, AttributeError):
                continue

        return None

    # ------------------------------------------------------------------ #
    #  Время                                                               #
    # ------------------------------------------------------------------ #

    def _extract_times_from_instructions(self):
        """
        Анализирует текст инструкций и возвращает (prep_time, cook_time, total_time).

        Эвристика для fittkonyha.com:
        - «X percig sütöttem / sütjük / sütöm»  →  cook_time
        - «X percig főzzük / főzöm»              →  cook_time
        - «X percet pihentetjük / pihentetni»    →  prep_time
        - «X percig pihentetjük»                 →  prep_time
        - Прочие упоминания «X perc» после глагола приготовления → cook_time
        """
        instructions = self.extract_instructions()
        if not instructions:
            return None, None, None

        prep_time = None
        cook_time = None

        # Паттерны для prep_time (пассивное ожидание)
        prep_patterns = [
            r'([\d]+(?:\s*[-–]\s*[\d]+)?)\s*perc(?:et|ig)?\s+pihentet',
            r'pihentet\w+\s+([\d]+(?:\s*[-–]\s*[\d]+)?)\s*perc',
            r'([\d]+(?:\s*[-–]\s*[\d]+)?)\s*perc(?:ig)?\s+állni',
            r'([\d]+(?:\s*[-–]\s*[\d]+)?)\s*perc(?:et)?\s+várakoz',
        ]
        for pat in prep_patterns:
            m = re.search(pat, instructions, re.IGNORECASE)
            if m:
                raw = m.group(1)
                prep_time = self._parse_hungarian_time(raw + ' perc')
                break

        # Паттерны для cook_time (активная готовка)
        cook_patterns = [
            r'([\d]+(?:\s*[-–]\s*[\d]+)?)\s*perc(?:ig)?\s+s[uü]t',
            r's[uü]t\w+\s+([\d]+(?:\s*[-–]\s*[\d]+)?)\s*perc',
            r'([\d]+(?:\s*[-–]\s*[\d]+)?)\s*perc(?:ig)?\s+f[oő]z',
            r'f[oő]z\w+\s+([\d]+(?:\s*[-–]\s*[\d]+)?)\s*perc',
            r'([\d]+(?:\s*[-–]\s*[\d]+)?)\s*perc(?:ig)?\s+(?:párol|grill|párold)',
        ]
        for pat in cook_patterns:
            m = re.search(pat, instructions, re.IGNORECASE)
            if m:
                raw = m.group(1)
                cook_time = self._parse_hungarian_time(raw + ' perc')
                break

        # Если cook_time не нашли, ищем любой диапазон с «perc» в инструкциях
        if not cook_time:
            m = re.search(
                r'(?<!\d[,.])\b([\d]+\s*[-–]\s*[\d]+)\s*perc',
                instructions, re.IGNORECASE,
            )
            if m:
                cook_time = self._parse_hungarian_time(m.group(0))

        # total_time
        total_time = None
        if prep_time and cook_time:
            # Простое сложение, если оба числовые
            p = re.search(r'(\d+)', prep_time)
            c = re.search(r'(\d+)', cook_time)
            if p and c:
                total_time = f"{int(p.group(1)) + int(c.group(1))} minutes"

        return prep_time, cook_time, total_time

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки."""
        prep, _, _ = self._extract_times_from_instructions()
        return prep

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления."""
        _, cook, _ = self._extract_times_from_instructions()
        return cook

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени."""
        _, _, total = self._extract_times_from_instructions()
        return total

    # ------------------------------------------------------------------ #
    #  Изображения                                                         #
    # ------------------------------------------------------------------ #

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта."""
        urls = []

        # 1. og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # 2. JSON-LD ImageObject / thumbnailUrl
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                graph = data.get('@graph', []) if isinstance(data, dict) else []
                for item in graph:
                    if item.get('@type') == 'ImageObject':
                        img_url = item.get('url') or item.get('contentUrl')
                        if img_url:
                            urls.append(img_url)
            except (json.JSONDecodeError, AttributeError):
                continue

        # 3. <img> в entry-content (только фото рецепта, не иконки)
        entry = self.soup.find('div', class_='entry-content')
        if entry:
            for img in entry.find_all('img'):
                src = img.get('src') or img.get('data-src') or ''
                # Фильтрация: только wp-content/uploads, не иконки/плагины
                if 'wp-content/uploads' not in src or 'fittkonyha.com' not in src:
                    continue
                # Пропускаем маленькие иконки (icon, logo, star, loading)
                if re.search(r'icon|logo|star|loading|arrow|banner', src, re.IGNORECASE):
                    continue
                urls.append(src)

        # Дедупликация с сохранением порядка
        seen = set()
        unique = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    # ------------------------------------------------------------------ #
    #  Основной метод                                                      #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            dict со следующими полями:
            dish_name, description, ingredients, instructions,
            category, prep_time, cook_time, total_time,
            notes, image_urls, tags
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        total_time = self.extract_total_time()
        image_urls = self.extract_image_urls()

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
            "image_urls": image_urls,
            "tags": tags,
        }


def main():
    import os
    recipes_dir = os.path.join("preprocessed", "fittkonyha_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(FittkonyhaCom, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python fittkonyha_com.py [путь_к_директории]")


if __name__ == "__main__":
    main()
