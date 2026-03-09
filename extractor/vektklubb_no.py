"""
Экстрактор данных рецептов для сайта vektklubb.no
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

# Norwegian culinary units (including informal measures and size descriptors
# that appear in place of measurement units on this site)
_NORWEGIAN_UNITS = {
    # Volume
    'dl', 'ml', 'l', 'cl',
    # Culinary spoons
    'ss', 'ts',
    # Weight
    'gram', 'g', 'kg',
    # Informal measures
    'neve', 'skvett', 'dæsj',
    # Pieces / counts
    'stk', 'stk.',
    # Size descriptors used as units on this site
    'liten', 'lite', 'lita', 'stor', 'store', 'stort',
    # Other
    'cm', 'boks', 'pose', 'pakke', 'skive', 'skiver',
    'bit', 'biter', 'blad', 'blader', 'kvist', 'kvister',
}

# Patterns in ingredient text that indicate serving/calorie info (not ingredients)
_NON_INGREDIENT_PATTERNS = re.compile(r'kcal|porsjon|kalorier', re.I)

# Breadcrumb categories to skip when determining recipe category
_BREADCRUMB_SKIP = {'hjem', 'inspirasjon'}


class VektklubbNoExtractor(BaseRecipeExtractor):
    """Экстрактор для vektklubb.no"""

    def _get_main_content(self):
        """
        Возвращает основной блок контента статьи.
        На vektklubb.no это div, содержащий тег h1 (родительский контейнер статьи).
        """
        h1 = self.soup.find('h1')
        if h1:
            return h1.parent
        return self.soup

    # ------------------------------------------------------------------
    # Извлечение названия блюда
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из тега h1."""
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        return None

    # ------------------------------------------------------------------
    # Извлечение описания
    # ------------------------------------------------------------------

    def extract_description(self) -> Optional[str]:
        """
        Извлечение вводного описания рецепта.
        На vektklubb.no первый абзац с data-testid="test__body-text"
        и дополнительным классом (класс лида) является анонсом статьи.
        """
        main = self._get_main_content()
        body_paragraphs = main.find_all('p', attrs={'data-testid': 'test__body-text'})
        if not body_paragraphs:
            return None

        first_p = body_paragraphs[0]
        text = self.clean_text(first_p.get_text(separator=' ', strip=True))
        return text if text else None

    # ------------------------------------------------------------------
    # Парсинг одного ингредиента
    # ------------------------------------------------------------------

    def _parse_ingredient_line(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в словарь {name, amount, unit}.

        Поддерживаемые форматы (норвежские):
          «1 dl melk»             -> name="melk",           amount="1",   unit="dl"
          «2 ss mager kesam»      -> name="mager kesam",    amount="2",   unit="ss"
          «100 gram jordbær»      -> name="jordbær",        amount="100", unit="gram"
          «1/2 kiwi»              -> name="kiwi",           amount="1/2", unit=None
          «1 liten gulrot»        -> name="gulrot",         amount="1",   unit="liten"
          «1 grønt eple»          -> name="grønt eple",     amount="1",   unit=None
          «0,5 avokado»           -> name="avokado",        amount="0.5", unit=None
          «20 stk. bringebær»     -> name="bringebær",      amount="20",  unit="stk."
          «Kiwi»                  -> name="kiwi",           amount=None,  unit=None
        """
        text = text.strip()
        if not text:
            return None

        # Пропускаем строки с информацией о порциях/калориях
        if _NON_INGREDIENT_PATTERNS.search(text):
            return None

        # Нормализуем запятую в десятичных числах
        text_norm = re.sub(r'(\d),(\d)', r'\1.\2', text)

        # Паттерн: число(а) в начале строки
        # Поддерживаем: целые, дробные (1/2), смешанные (1 1/2), десятичные (0.5)
        number_re = r'(?:\d+(?:\.\d+)?(?:\s*/\s*\d+)?|\d+\s*/\s*\d+)'
        leading_num_re = rf'^({number_re}(?:\s+{number_re})?)\s+'
        m = re.match(leading_num_re, text_norm)

        if not m:
            # Нет числа — только название
            return {
                'name': text.lower(),
                'amount': None,
                'unit': None,
            }

        amount_raw = m.group(1).strip()
        rest = text_norm[m.end():]

        # Нормализуем дробь вида «1 1/2» -> «1.5» если нужно, иначе оставляем
        # Для соответствия эталону оставляем строку как есть (e.g. "1/2")
        amount = amount_raw

        # Проверяем, является ли первое слово единицей измерения
        words = rest.split()
        if words and words[0].lower().rstrip('.') in _NORWEGIAN_UNITS:
            unit = words[0]
            name = ' '.join(words[1:]).strip() if len(words) > 1 else rest.strip()
        else:
            unit = None
            name = rest.strip()

        if not name:
            return None

        return {
            'name': name.lower(),
            'amount': amount,
            'unit': unit,
        }

    # ------------------------------------------------------------------
    # Извлечение ингредиентов
    # ------------------------------------------------------------------

    def _looks_like_ingredient(self, text: str) -> bool:
        """
        Эвристика: является ли текст строкой ингредиента.
        Ингредиенты начинаются с числа/дроби или являются коротким названием продукта.
        """
        # Начинается с числа, дроби или Unicode-дроби
        if re.match(r'^[\d½¼¾⅓⅔⅛]', text.strip()):
            return True
        # Короткая строка (≤ 5 слов) без глаголов (не инструкция)
        words = text.strip().split()
        if len(words) <= 5:
            # Если нет знаков препинания в конце и выглядит как продукт
            if not re.search(r'[.!?]$', text.strip()):
                return True
        return False

    def _is_tips_context(self, tag) -> bool:
        """Возвращает True, если тег находится внутри блока советов (Tips...)."""
        # Проверяем предшествующий заголовок
        prev = tag.find_previous_sibling()
        while prev:
            if getattr(prev, 'name', None) in ('h2', 'h3'):
                heading_text = prev.get_text(strip=True).lower()
                if 'tips' in heading_text or 'forslag' in heading_text:
                    return True
                # Другой тематический заголовок — прекращаем поиск
                return False
            prev = prev.find_previous_sibling()
        return False

    def _is_instruction_context(self, tag) -> bool:
        """Возвращает True, если тег стоит сразу после абзаца «Slik gjør du»."""
        prev = tag.find_previous_sibling()
        while prev:
            tag_name = getattr(prev, 'name', None)
            if tag_name == 'p':
                text = prev.get_text(strip=True)
                if re.search(r'slik gjør du', text, re.I):
                    return True
                # Любой другой абзац — прекращаем
                return False
            elif tag_name in ('h2', 'h3'):
                return False
            prev = prev.find_previous_sibling()
        return False

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов со страницы vektklubb.no.

        Применяемые стратегии:
        1. Абзацы с тегами <br> содержащие строки с количеством/мерой.
        2. Элементы <ul> / <ol>, которым предшествует абзац «trenger du:»
           или «Topping:», либо содержащие в большинстве строки с числами.
           Блоки советов (Tips) и инструкций (Slik gjør du) — пропускаются.
        """
        ingredients: list = []
        main = self._get_main_content()

        def add_ingredient(text: str) -> None:
            text = text.strip()
            if not text:
                return
            parsed = self._parse_ingredient_line(text)
            if parsed:
                ingredients.append(parsed)

        # ── Метод 1: параграфы с <br> ──────────────────────────────────
        for p in main.find_all('p', attrs={'data-testid': 'test__body-text'}):
            if not p.find('br'):
                continue
            raw_text = p.get_text(separator='\n', strip=True)
            lines = [ln.strip() for ln in raw_text.split('\n') if ln.strip()]
            if not lines:
                continue
            # Ингредиентный список — большинство строк начинаются с цифры
            num_count = sum(1 for ln in lines if re.match(r'^[\d½¼¾⅓⅔⅛]', ln))
            if num_count >= max(1, len(lines) // 2):
                for line in lines:
                    add_ingredient(line)

        # ── Метод 2: списки <ul>/<ol> по контексту ─────────────────────
        for lst in main.find_all(['ul', 'ol']):
            # Пропускаем блоки советов
            if self._is_tips_context(lst):
                continue
            # Пропускаем блоки инструкций
            if self._is_instruction_context(lst):
                continue

            items = [
                self.clean_text(li.get_text(separator=' ', strip=True))
                for li in lst.find_all('li')
                if li.get_text(strip=True)
            ]
            if not items:
                continue

            # Проверяем контекст: предшествует ли «trenger du:» или «Topping:»
            prev = lst.find_previous_sibling()
            context_ok = False
            while prev:
                tag_name = getattr(prev, 'name', None)
                if tag_name == 'p':
                    prev_text = prev.get_text(separator=' ', strip=True)
                    if re.search(r'trenger\s+du|topping\s*:', prev_text, re.I):
                        context_ok = True
                    break
                elif tag_name in ('h2', 'h3'):
                    # Предшествует заголовок рецепта — тоже OK
                    context_ok = True
                    break
                prev = prev.find_previous_sibling()

            # Если контекст неясен — проверяем, что большинство элементов
            # выглядят как ингредиенты
            if not context_ok:
                num_count = sum(
                    1 for it in items if re.match(r'^[\d½¼¾⅓⅔⅛]', it)
                )
                short_count = sum(
                    1 for it in items
                    if len(it.split()) <= 4 and not re.search(r'[.!?]$', it)
                )
                if num_count + short_count < max(1, len(items) // 2):
                    continue

            for item_text in items:
                if self._looks_like_ingredient(item_text):
                    add_ingredient(item_text)

        if not ingredients:
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Извлечение инструкций (шагов приготовления)
    # ------------------------------------------------------------------

    def extract_steps(self) -> Optional[str]:
        """
        Извлечение шагов приготовления.

        На vektklubb.no инструкции могут быть:
        1. В <ol> / <ul> сразу после абзаца «Slik gjør du det:» / «Slik gjør du:»
        2. Инлайн в том же абзаце после двоеточия.
        """
        steps: list = []
        main = self._get_main_content()

        body_paragraphs = main.find_all('p', attrs={'data-testid': 'test__body-text'})

        for p in body_paragraphs:
            text = p.get_text(separator=' ', strip=True)
            if not re.search(r'slik gjør du', text, re.I):
                continue

            # Инструкции встроены в тот же абзац?
            inline = re.split(r'slik gjør du[^:]*:\s*', text, flags=re.I, maxsplit=1)
            if len(inline) > 1 and inline[1].strip():
                steps.append(self.clean_text(inline[1].strip()))
                continue

            # Инструкции в следующем <ol> / <ul>
            sibling = p.find_next_sibling()
            while sibling:
                tag_name = getattr(sibling, 'name', None)
                if tag_name in ('ol', 'ul'):
                    for li in sibling.find_all('li'):
                        step_text = self.clean_text(
                            li.get_text(separator=' ', strip=True)
                        )
                        if step_text:
                            steps.append(step_text)
                    break
                elif tag_name == 'p':
                    break
                sibling = sibling.find_next_sibling()

        if not steps:
            return None

        # Нумеруем шаги, если они не пронумерованы
        if not re.match(r'^\d+\.', steps[0]):
            steps = [f'{i}. {s}' for i, s in enumerate(steps, 1)]

        return ' '.join(steps)

    # ------------------------------------------------------------------
    # Извлечение категории
    # ------------------------------------------------------------------

    def extract_category(self) -> Optional[str]:
        """
        Извлечение категории рецепта из «хлебных крошек».
        Возвращает самую конкретную категорию (последний элемент крошки,
        исключая «Hjem» и «Inspirasjon»).
        """
        breadcrumb = self.soup.find('div', class_='Cy69hpsQyo5yCgvkYegZ')
        if breadcrumb:
            links = breadcrumb.find_all('a')
            categories = [
                self.clean_text(a.get_text())
                for a in links
                if self.clean_text(a.get_text()).lower() not in _BREADCRUMB_SKIP
            ]
            if categories:
                return categories[-1]

        return None

    # ------------------------------------------------------------------
    # Извлечение времени
    # ------------------------------------------------------------------

    def _extract_time_from_heading(self, pattern: str) -> Optional[str]:
        """
        Вспомогательный метод: ищет заголовки (h2/h3) с указанием времени,
        соответствующие переданному паттерну, и возвращает найденное значение.
        """
        main = self._get_main_content()
        for heading in main.find_all(['h2', 'h3']):
            text = heading.get_text(strip=True)
            m = re.search(pattern, text, re.I)
            if m:
                return m.group(0)
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки."""
        # «Klar på 10 minutter» = «Ready in 10 minutes»
        val = self._extract_time_from_heading(r'\d+\s*minutter?|\d+\s*timer?')
        if val:
            # Нормализуем: «10 minutter» -> «10 minutes»
            val = re.sub(r'minutter?', 'minutes', val, flags=re.I)
            val = re.sub(r'timer?', 'hours', val, flags=re.I)
            return val.strip()
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления."""
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени (совпадает с prep_time на данном сайте)."""
        return self.extract_prep_time()

    # ------------------------------------------------------------------
    # Извлечение заметок / советов
    # ------------------------------------------------------------------

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение советов/заметок.
        Ищет блоки советов (h3 «Tips...»), за которыми следуют списки советов.
        """
        notes_parts: list = []
        main = self._get_main_content()

        for heading in main.find_all(['h2', 'h3']):
            text = heading.get_text(strip=True)
            if re.search(r'tips', text, re.I):
                # Собираем элементы списка, следующие за этим заголовком
                sibling = heading.find_next_sibling()
                while sibling:
                    tag_name = getattr(sibling, 'name', None)
                    if tag_name in ('ul', 'ol'):
                        for li in sibling.find_all('li'):
                            tip_text = self.clean_text(
                                li.get_text(separator=' ', strip=True)
                            )
                            if tip_text:
                                notes_parts.append(tip_text)
                        break
                    elif tag_name in ('h2', 'h3'):
                        break
                    sibling = sibling.find_next_sibling()

        return ' '.join(notes_parts) if notes_parts else None

    # ------------------------------------------------------------------
    # Извлечение тегов
    # ------------------------------------------------------------------

    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов страницы.
        На vektklubb.no явных тегов в HTML нет; возвращается None.
        """
        return None

    # ------------------------------------------------------------------
    # Извлечение URL изображений
    # ------------------------------------------------------------------

    def extract_image_urls(self) -> Optional[str]:
        """
        Извлечение URL изображений рецепта.
        Берётся из тега <img src=...> в основном контенте (не lazy-placeholder).
        """
        urls: list = []
        main = self._get_main_content()

        for img in main.find_all('img'):
            src = img.get('src', '')
            # Пропускаем placeholder (base64 data URI и tiny GIF)
            if src and not src.startswith('data:'):
                # Игнорируем аватары авторов (маленькие квадратные)
                alt = img.get('alt', '')
                # Проверяем, что это не аватар автора
                w_param = re.search(r'[?&]w=(\d+)', src)
                h_param = re.search(r'[?&]h=(\d+)', src)
                if w_param and h_param:
                    w, h = int(w_param.group(1)), int(h_param.group(1))
                    if w == h and w <= 200:
                        # Скорее всего, аватар автора
                        continue
                if src not in urls:
                    urls.append(src)

        if not urls:
            return None

        return ','.join(urls)

    # ------------------------------------------------------------------
    # Главный метод: сборка всех данных
    # ------------------------------------------------------------------

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
            'dish_name': dish_name.lower() if dish_name else None,
            'description': description.lower() if description else None,
            'ingredients': ingredients,
            'instructions': instructions.lower() if instructions else None,
            'category': category.lower() if category else None,
            'prep_time': self.extract_prep_time(),
            'cook_time': self.extract_cook_time(),
            'total_time': self.extract_total_time(),
            'notes': notes.lower() if notes else None,
            'tags': tags,
            'image_urls': self.extract_image_urls(),
        }


def main():
    import os
    recipes_dir = os.path.join('preprocessed', 'vektklubb_no')
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(VektklubbNoExtractor, str(recipes_dir))
        return

    print(f'Директория не найдена: {recipes_dir}')
    print('Использование: python vektklubb_no.py')


if __name__ == '__main__':
    main()
