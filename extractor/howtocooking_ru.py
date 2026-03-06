"""
Экстрактор данных рецептов для сайта howtocooking.ru
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

# Русские единицы измерения (упорядочены от более длинных к более коротким)
_RU_UNITS_PATTERN = (
    r'(?:'
    r'ст\.?\s*л\.?'          # ст.л. (столовая ложка)
    r'|ч\.?\s*л\.?'           # ч.л. (чайная ложка)
    r'|стак(?:ан(?:а|ов|е)?)?\.?'  # стакан/стак.
    r'|зубч(?:иков|ика|ик)?\.?'    # зубчиков/зубчик
    r'|веточк(?:и|ек|а)?'          # веточки/веточка
    r'|пучк(?:а|ов|и)?'            # пучок/пучка
    r'|горст(?:и|ей|ь)?'           # горсть/горсти
    r'|щепотк(?:и|у|а)?'           # щепотка/щепотки
    r'|по\s+вкусу'                  # по вкусу
    r'|порци(?:и|я|й)?'             # порция/порции
    r'|кусочк(?:ов|а|ек|и)?'        # кусочек/кусочки
    r'|ломтик(?:ов|а|ов)?'          # ломтик/ломтиков
    r'|мл'                           # мл
    r'|кг'                           # кг
    r'|гр?\.?'                       # г / гр.
    r'|л(?=\s|$)'                    # л (литр) — только перед пробелом или концом строки
    r'|шт\.?'                        # шт.
    r')'
)

# Числовой паттерн: целое, дробное, дробь через /, диапазон через дефис
_RU_AMOUNT_PATTERN = r'(?:\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?(?:\s*/\s*\d+)?)'


class HowtocookingRuExtractor(BaseRecipeExtractor):
    """Экстрактор для howtocooking.ru"""

    BASE_URL = "https://howtocooking.ru"

    # ------------------------------------------------------------------ #
    #  Вспомогательные методы                                              #
    # ------------------------------------------------------------------ #

    def _get_json_ld(self) -> Optional[dict]:
        """Извлечение данных JSON-LD с типом Recipe."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                candidates = data if isinstance(data, list) else [data]
                for item in candidates:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get('@type', '')
                    types = item_type if isinstance(item_type, list) else [item_type]
                    if 'Recipe' in types:
                        return item
            except (json.JSONDecodeError, KeyError):
                continue
        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration (PT1H30M) в читаемую строку.

        Returns:
            Например: "1 hour 30 minutes", "40 minutes", "2 hours"
        """
        if not duration or not duration.startswith('PT'):
            return None
        rest = duration[2:]

        hours = 0
        minutes = 0

        h_match = re.search(r'(\d+)H', rest)
        if h_match:
            hours = int(h_match.group(1))
        m_match = re.search(r'(\d+)M', rest)
        if m_match:
            minutes = int(m_match.group(1))

        parts = []
        if hours:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")

        return ' '.join(parts) if parts else None

    @staticmethod
    def _parse_info_time(time_str: str) -> Optional[str]:
        """
        Конвертирует строку вида «3 ч», «40 мин», «1 ч 20 мин» в читаемый формат.

        Returns:
            Например: "3 hours", "40 minutes", "1 hour 20 minutes"
        """
        if not time_str:
            return None
        time_str = time_str.strip()

        hours = 0
        minutes = 0

        h_match = re.search(r'(\d+)\s*ч(?:ас(?:а|ов)?)?', time_str)
        if h_match:
            hours = int(h_match.group(1))
        m_match = re.search(r'(\d+)\s*мин', time_str)
        if m_match:
            minutes = int(m_match.group(1))

        if not hours and not minutes:
            return None

        parts = []
        if hours:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")

        return ' '.join(parts)

    @staticmethod
    def _fix_merged_words(text: str) -> str:
        """
        Исправляет слипшиеся слова с предлогами, характерные для опечаток на сайте.
        Например: «приправадля» → «приправа для».

        Использует только длинные (4+ букв) предлоги, которые не являются
        стандартными окончаниями русских слов, чтобы избежать ложных срабатываний.
        """
        # Вставляем пробел перед предлогом, если он слиплся с предыдущим русским словом.
        # Lookahead: после предлога должна идти русская буква или пробел (конец слипшейся цепочки).
        long_prepositions = r'(?<=[а-яё])(для|через|между|после|перед|около|против)(?=\s|[а-яё])'
        return re.sub(long_prepositions, r' \1', text, flags=re.IGNORECASE)

    def _parse_ingredient_ru(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в русском формате.

        Поддерживает форматы:
        - «сахар 120 г»   → name=сахар, amount=120, unit=г
        - «1.2-1.5 кг мякоти свинины»  → name=мякоти свинины, amount=1.2-1.5, unit=кг
        - «ванилин»       → name=ванилин, amount=None, unit=None
        """
        if not text:
            return None

        text = self.clean_text(text)
        # Исправляем слипшиеся слова (например, «приправадля» → «приправа для»)
        text = self._fix_merged_words(text)

        # Нормализуем дроби: ½ → 1/2
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
        }
        for f, r in fraction_map.items():
            text = text.replace(f, r)

        # --- Формат 1: начинается с числа («amount unit name») ---
        amount_first = re.match(
            r'^(' + _RU_AMOUNT_PATTERN + r')\s+(' + _RU_UNITS_PATTERN + r')\s+(.+)$',
            text, re.IGNORECASE
        )
        if amount_first:
            raw_amount, unit, name = amount_first.group(1), amount_first.group(2), amount_first.group(3)
            return {
                "name": name.strip(),
                "amount": _normalize_amount(raw_amount),
                "unit": unit.strip(),
            }

        # Формат 1b: начинается с числа, но без единицы («3 луковицы»)
        amount_no_unit = re.match(
            r'^(' + _RU_AMOUNT_PATTERN + r')\s+(.+)$',
            text, re.IGNORECASE
        )
        if amount_no_unit and re.match(r'^\d', text):
            raw_amount, name = amount_no_unit.group(1), amount_no_unit.group(2)
            return {
                "name": name.strip(),
                "amount": _normalize_amount(raw_amount),
                "unit": None,
            }

        # --- Формат 2: имя первым («name amount unit» или «name amount») ---
        name_first = re.match(
            r'^(.+?)\s+(' + _RU_AMOUNT_PATTERN + r')\s*(' + _RU_UNITS_PATTERN + r')?$',
            text, re.IGNORECASE
        )
        if name_first:
            name, raw_amount, unit = (
                name_first.group(1),
                name_first.group(2),
                name_first.group(3),
            )
            # Если «name» — числовое выражение, скорее всего ложное срабатывание
            if re.match(r'^\d', name):
                pass  # упадём в fallback ниже
            else:
                return {
                    "name": name.strip(),
                    "amount": _normalize_amount(raw_amount),
                    "unit": unit.strip() if unit else None,
                }

        # --- Формат 3: только имя, без количества ---
        # Обрабатываем «по вкусу» как единицу
        if 'по вкусу' in text.lower():
            name = re.sub(r'\s*по\s+вкусу\s*', '', text, flags=re.IGNORECASE).strip()
            return {"name": name or text, "amount": None, "unit": "по вкусу"}

        return {"name": text, "amount": None, "unit": None}

    # ------------------------------------------------------------------ #
    #  Основные методы извлечения                                          #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда (h1 имеет правильный регистр)."""
        # Предпочитаем h1 — он содержит название в правильном регистре.
        # JSON-LD.name на howtocooking.ru всегда в нижнем регистре.
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        json_ld = self._get_json_ld()
        if json_ld and json_ld.get('name'):
            return self.clean_text(json_ld['name'])

        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем шаблонный суффикс «— Лучший Рецепт ... на HowtoCooking.ru!»
            title = re.sub(r'\s*—\s*Лучший\s+Рецепт.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title) or None

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение краткого описания рецепта (анонс/intro)."""
        # 1. .preview — краткий анонс под заголовком
        preview = self.soup.find(class_='preview')
        if preview:
            text = self.clean_text(preview.get_text())
            if text:
                return text

        # 2. og:title — содержит имя рецепта; используем как описание-заглушку
        # когда .preview отсутствует (meta description загрязнён списком ингредиентов).
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        # 3. JSON-LD description как последний вариант
        json_ld = self._get_json_ld()
        if json_ld and json_ld.get('description'):
            return self.clean_text(json_ld['description'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов.

        Первичный источник: JSON-LD recipeIngredient (полный список).
        Запасной: ul.ingredients li.
        """
        raw_items: list[str] = []

        json_ld = self._get_json_ld()
        if json_ld and json_ld.get('recipeIngredient'):
            raw_items = [str(i) for i in json_ld['recipeIngredient'] if i]

        if not raw_items:
            ingr_ul = self.soup.find('ul', class_='ingredients')
            if ingr_ul:
                raw_items = [
                    li.get_text(separator=' ', strip=True)
                    for li in ingr_ul.find_all('li')
                ]

        if not raw_items:
            logger.warning("Ингредиенты не найдены: %s", self.html_path)
            return None

        parsed = []
        for item in raw_items:
            result = self._parse_ingredient_ru(item)
            if result:
                parsed.append(result)

        return json.dumps(parsed, ensure_ascii=False) if parsed else None

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления из ol.steps."""
        steps_ol = self.soup.find('ol', class_='steps')
        if not steps_ol:
            logger.warning("Шаги приготовления не найдены: %s", self.html_path)
            return None

        steps = []
        for li in steps_ol.find_all('li', recursive=False):
            # Извлекаем текст, игнорируя вложенные изображения
            text = self.clean_text(li.get_text(separator=' ', strip=True))
            if text:
                steps.append(text)

        if not steps:
            return None

        return ' '.join(steps)

    def extract_category(self) -> Optional[str]:
        """
        Извлечение категории из хлебных крошек (второй уровень после «Рецепты»)
        или из JSON-LD recipeCategory.
        """
        breadcrumb = self.soup.find(class_='breadcrumb')
        if breadcrumb:
            links = [a.get_text(strip=True) for a in breadcrumb.find_all('a')]
            # Структура: [Рецепты, Категория, Подкатегория, Рецепт]
            # Берём второй элемент (индекс 1) — это верхний уровень категории
            if len(links) > 1:
                category = links[1]
                if category and category.lower() != 'рецепты':
                    return self.clean_text(category)

        json_ld = self._get_json_ld()
        if json_ld and json_ld.get('recipeCategory'):
            return self.clean_text(json_ld['recipeCategory'])

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки (prepTime из JSON-LD)."""
        json_ld = self._get_json_ld()
        if json_ld and json_ld.get('prepTime'):
            return self._parse_iso_duration(json_ld['prepTime'])
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления (cookTime из JSON-LD)."""
        json_ld = self._get_json_ld()
        if json_ld and json_ld.get('cookTime'):
            return self._parse_iso_duration(json_ld['cookTime'])
        return None

    def extract_total_time(self) -> Optional[str]:
        """
        Извлечение общего времени.

        Первичный источник: JSON-LD totalTime.
        Запасной: блок .info → «Время приготовления».
        """
        json_ld = self._get_json_ld()
        if json_ld and json_ld.get('totalTime'):
            result = self._parse_iso_duration(json_ld['totalTime'])
            if result:
                return result

        info_ul = self.soup.find('ul', class_='info')
        if info_ul:
            for li in info_ul.find_all('li'):
                text = li.get_text(separator=' ', strip=True)
                if 'Время' in text or 'время' in text:
                    # «Время приготовления:40 мин»
                    value = re.sub(r'^[^:]+:', '', text).strip()
                    return self._parse_info_time(value)

        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение примечаний (на howtocooking.ru обычно отсутствуют)."""
        return None

    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов из JSON-LD keywords.
        Фильтруем пустые и шаблонные строки.
        """
        json_ld = self._get_json_ld()
        keywords_raw = json_ld.get('keywords', '') if json_ld else ''

        if not keywords_raw:
            # Запасной: текст из .keywords div
            kw_div = self.soup.find(class_='keywords')
            if kw_div:
                keywords_raw = kw_div.get_text(separator=',', strip=True)

        if not keywords_raw:
            return None

        tags = [t.strip().lower() for t in keywords_raw.split(',') if t.strip()]
        # Убираем шаблонные «Простой рецепт», «Несложный рецепт» и т.п.
        stopwords = {'простой рецепт', 'несложный рецепт', 'сложный рецепт', ''}
        tags = [t for t in tags if t not in stopwords and len(t) > 1]

        # Удаляем дубликаты, сохраняя порядок
        seen: set[str] = set()
        unique: list[str] = []
        for t in tags:
            if t not in seen:
                seen.add(t)
                unique.append(t)

        return ', '.join(unique) if unique else None

    def extract_image_urls(self) -> Optional[str]:
        """
        Извлечение URL изображений рецепта.

        Первичный источник: JSON-LD image.
        Запасной: основное фото рецепта (img.lozad с data-src содержащим «recept»).
        """
        urls: list[str] = []

        # 1. JSON-LD image
        json_ld = self._get_json_ld()
        if json_ld and json_ld.get('image'):
            img_field = json_ld['image']
            if isinstance(img_field, str):
                urls.append(img_field)
            elif isinstance(img_field, list):
                for item in img_field:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        url = item.get('url') or item.get('contentUrl')
                        if url:
                            urls.append(url)
            elif isinstance(img_field, dict):
                url = img_field.get('url') or img_field.get('contentUrl')
                if url:
                    urls.append(url)

        # 2. Запасной: изображения шагов (lozad) — только те, что принадлежат рецепту
        if not urls:
            for img in self.soup.find_all('img', class_='lozad'):
                data_src = img.get('data-src', '')
                if 'recept' in data_src or 'ready' in data_src:
                    full_url = (
                        data_src if data_src.startswith('http')
                        else self.BASE_URL + data_src
                    )
                    urls.append(full_url)
                    break  # берём только первое основное фото

        if not urls:
            # og:image
            og = self.soup.find('meta', property='og:image')
            if og and og.get('content'):
                urls.append(og['content'])

        # Убираем дубликаты
        seen: set[str] = set()
        unique: list[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    # ------------------------------------------------------------------ #
    #  Основной метод                                                      #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта."""
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_steps()
        category = self.extract_category()
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
            "notes": self.extract_notes(),
            "tags": tags,
            "image_urls": self.extract_image_urls(),
        }


# ------------------------------------------------------------------ #
#  Вспомогательные функции модуля                                      #
# ------------------------------------------------------------------ #

def _normalize_amount(raw: str) -> object:
    """
    Нормализует строку количества:
    - «120» → 120 (int)
    - «0.5» → 0.5 (float)
    - «1/2» → 0.5 (float)
    - «1.2-1.5» → «1.2-1.5» (str, диапазон)
    """
    raw = raw.strip().replace(',', '.')

    # Диапазон (например «1.2-1.5»)
    if re.search(r'[-–]', raw):
        return raw

    # Дробь «1/2»
    if '/' in raw:
        parts = raw.split('/')
        try:
            result = float(parts[0]) / float(parts[1])
            return int(result) if result == int(result) else round(result, 4)
        except (ValueError, ZeroDivisionError):
            return raw

    # Целое или дробное число
    try:
        val = float(raw)
        return int(val) if val == int(val) else val
    except ValueError:
        return raw


def main() -> None:
    """Точка входа для обработки директории с HTML‑файлами."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "howtocooking_ru")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(HowtocookingRuExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python howtocooking_ru.py")


if __name__ == "__main__":
    main()
