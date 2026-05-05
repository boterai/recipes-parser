"""
Экстрактор данных рецептов для сайта bezglutenskaradost.com
Сайт на хорватском языке. WordPress + Elementor, контент в div.elementor-widget-theme-post-content.
Метаданные (заголовок, категория, теги) берутся из JSON-LD Yoast (@type: Article).
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Хорватские единицы измерения и их нормализованные аналоги
CROATIAN_UNITS = [
    "čajna žličica", "čajne žličice", "čajnih žličica",
    "jušna žlica", "jušne žlice", "jušnih žlica",
    "čajna žlica", "čajne žlice", "čajnih žlica",
    "žličica", "žlica",
    "šalica", "šalice",
    "dl", "ml", "cl",
    "kg", "dag", "g",
    "l",
    "kom", "komad", "komada",
]

# Сортируем по длине (сначала длинные, чтобы "čajna žličica" не распарсилось как "žličica")
CROATIAN_UNITS_SORTED = sorted(CROATIAN_UNITS, key=len, reverse=True)

# Ключевые слова для нахождения секции ингредиентов
INGREDIENT_KEYWORDS = re.compile(r'^\s*SASTOJCI\b|^\s*Sastojci\b', re.IGNORECASE)

# Дополнительные секции с ингредиентами (PREMAZ, Punjenje, Nadjev, Umak, …)
EXTRA_INGREDIENT_KEYWORDS = re.compile(
    r'^\s*(PREMAZ|Premaz|PUNJENJE|Punjenje|NADJEV|Nadjev|UMAK|Umak|'
    r'GLAZURA|Glazura|FIL|Fil)\b',
    re.IGNORECASE
)

# Ключевые слова для нахождения секции инструкций
INSTRUCTION_KEYWORDS = re.compile(r'^\s*PRIPREMA\b|^\s*Priprema\b|^\s*NAČIN PRIPREME\b', re.IGNORECASE)

# "Dobar tek!" — конец инструкций / начало постскриптума
DOBAR_TEK = re.compile(r'dobar\s+tek', re.IGNORECASE)

# Ключевые слова для нот/советов
NOTE_KEYWORDS = re.compile(
    r'čuvaj|savjet|napomena|napomene|preporuka|možete|prilagođen|slobodno',
    re.IGNORECASE
)


def _split_compound_ingredient(text: str) -> List[str]:
    """
    Разбивает составной ингредиент вида «290 g MIX C plus 30 g za brašniti»
    на отдельные строки, если встречается «plus N unit».
    Если разбиение не удалось, возвращает список из одного элемента.
    """
    units_re = "|".join(re.escape(u) for u in CROATIAN_UNITS_SORTED)
    # Ищем разделитель «plus <число> <единица>»
    split_pattern = re.compile(
        rf"\s+plus\s+(\d+(?:[.,/]\d+)?)\s+({units_re})\s+",
        re.IGNORECASE
    )
    m = split_pattern.search(text)
    if not m:
        return [text]

    first = text[:m.start()].strip()
    rest = text[m.start() + len("plus "):].strip()
    return [first, rest]


class BezglutenskaradostComExtractor(BaseRecipeExtractor):
    """Экстрактор для bezglutenskaradost.com"""

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _get_post_content_container(self):
        """Возвращает div.elementor-widget-container внутри elementor-widget-theme-post-content."""
        widget = self.soup.find("div", class_="elementor-widget-theme-post-content")
        if widget:
            return widget.find("div", class_="elementor-widget-container")
        return None

    def _get_yoast_article_data(self) -> Optional[dict]:
        """Извлекает данные @type:Article из JSON-LD Yoast."""
        for script in self.soup.find_all("script", type="application/ld+json"):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                graph = data.get("@graph") if isinstance(data, dict) else None
                if graph:
                    for item in graph:
                        if isinstance(item, dict) and item.get("@type") == "Article":
                            return item
            except (json.JSONDecodeError, AttributeError, KeyError):
                continue
        return None

    def _iter_content_elements(self):
        """
        Итерирует прямые дочерние теги контейнера контента (p, ul, figure, …).
        Возвращает элементы BeautifulSoup.
        """
        container = self._get_post_content_container()
        if not container:
            return []
        return [el for el in container.children if hasattr(el, "name") and el.name]

    # ------------------------------------------------------------------
    # Парсинг ингредиентов
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_ingredient_text(text: str) -> dict:
        """
        Парсит строку ингредиента вида «500 g MIX B brašna» или «pola čajne žličice sode»
        в словарь {"name": …, "amount": …, "unit": …}.
        """
        if not text:
            return {"name": text, "amount": None, "unit": None}

        original = text.strip()
        # Нормализуем пробелы
        text = re.sub(r"\s+", " ", original).strip()

        # Заменяем Unicode-дроби
        fraction_map = {
            "½": "1/2", "¼": "1/4", "¾": "3/4",
            "⅓": "1/3", "⅔": "2/3", "⅛": "1/8",
        }
        for frac, rep in fraction_map.items():
            text = text.replace(frac, rep)

        # --- Попытка 1: «[количество] [единица] название» ---
        # Количество: число, дробь, «pola», «par», «malo»
        amount_pattern = r"(?P<amount>\d+(?:[.,/]\d+)?(?:\s*[–\-]\s*\d+(?:[.,/]\d+)?)?|pola|par|malo|nekoliko)"
        # Единица: одна из известных хорватских единиц
        units_re = "|".join(re.escape(u) for u in CROATIAN_UNITS_SORTED)
        unit_pattern = rf"(?P<unit>{units_re})"

        full_pattern = rf"^\s*{amount_pattern}\s+{unit_pattern}\s+(?P<name>.+)$"
        m = re.match(full_pattern, text, re.IGNORECASE)
        if m:
            return {
                "name": m.group("name").strip(),
                "amount": m.group("amount").strip(),
                "unit": m.group("unit").strip(),
            }

        # --- Попытка 2: «[количество] название» (без единицы) ---
        no_unit_pattern = rf"^\s*{amount_pattern}\s+(?P<name>.+)$"
        m = re.match(no_unit_pattern, text, re.IGNORECASE)
        if m:
            return {
                "name": m.group("name").strip(),
                "amount": m.group("amount").strip(),
                "unit": None,
            }

        # --- Попытка 3: только название ---
        return {"name": text, "amount": None, "unit": None}

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из HTML-контента."""
        elements = self._iter_content_elements()
        if not elements:
            logger.warning("Контейнер контента не найден для %s", self.html_path)
            return None

        ingredients: List[dict] = []
        collecting = False          # собираем ингредиенты
        current_section: Optional[str] = None  # метка текущей дополнительной секции

        for el in elements:
            if el.name == "p":
                text = el.get_text(" ", strip=True)

                if INGREDIENT_KEYWORDS.match(text):
                    collecting = True
                    current_section = None
                    continue

                if collecting and EXTRA_INGREDIENT_KEYWORDS.match(text):
                    # Дополнительная секция (PREMAZ, PUNJENJE, …)
                    m = EXTRA_INGREDIENT_KEYWORDS.match(text)
                    current_section = m.group(1).capitalize() if m else None
                    continue

                if collecting and INSTRUCTION_KEYWORDS.match(text):
                    # Дошли до инструкций — заканчиваем сбор ингредиентов
                    break

            elif el.name == "ul" and collecting:
                for li in el.find_all("li"):
                    raw = self.clean_text(li.get_text(" ", strip=True))
                    if not raw:
                        continue
                    # Нормализуем пробел перед скобками и внутри скобок
                    # «palenta( žganci)» → «palenta (žganci)»
                    raw = re.sub(r"(\w)\(\s*", r"\1 (", raw)

                    # Разбиваем «N unit A plus N unit B» на два ингредиента
                    sub_items = _split_compound_ingredient(raw)
                    for sub_raw in sub_items:
                        parsed = self._parse_ingredient_text(sub_raw)
                        if parsed and parsed.get("name"):
                            # Добавляем метку секции в название
                            if current_section:
                                label = current_section.lower()
                                name = parsed["name"]
                                if f"({label})" not in name.lower():
                                    parsed["name"] = f"{name} ({label})"
                            ingredients.append(parsed)

        if not ingredients:
            logger.warning("Ингредиенты не найдены в %s", self.html_path)
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Инструкции
    # ------------------------------------------------------------------

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления."""
        elements = self._iter_content_elements()
        if not elements:
            return None

        steps: List[str] = []
        collecting = False

        for el in elements:
            if el.name == "p":
                text = self.clean_text(el.get_text(" ", strip=True))
                if not text:
                    continue

                if INSTRUCTION_KEYWORDS.match(text):
                    collecting = True
                    continue

                if collecting:
                    # Прекращаем при переходе к секции ингредиентов
                    if INGREDIENT_KEYWORDS.match(text) or EXTRA_INGREDIENT_KEYWORDS.match(text):
                        break
                    steps.append(text)

        if not steps:
            logger.warning("Инструкции не найдены в %s", self.html_path)
            return None

        return " ".join(steps)

    # ------------------------------------------------------------------
    # Заголовок
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из JSON-LD (Article.headline)."""
        article = self._get_yoast_article_data()
        if article and article.get("headline"):
            return self.clean_text(article["headline"])

        # Запасной вариант — h2 elementor-heading-title, который совпадает
        # с первым упоминанием заголовка поста
        for h2 in self.soup.find_all("h2", class_="elementor-heading-title"):
            text = h2.get_text(strip=True)
            if text and "@" not in text and len(text) > 4:
                return self.clean_text(text)

        # og:title — убираем суффикс сайта
        og_title = self.soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"]
            title = re.sub(r"\s*[–—-]\s*Bezglutenska radost.*$", "", title, flags=re.I)
            return self.clean_text(title)

        return None

    # ------------------------------------------------------------------
    # Описание
    # ------------------------------------------------------------------

    def extract_description(self) -> Optional[str]:
        """
        Описание — вводные абзацы перед секцией ингредиентов.
        Если их нет, возвращаем None.
        """
        elements = self._iter_content_elements()
        intro_paragraphs: List[str] = []

        for el in elements:
            if el.name == "p":
                text = self.clean_text(el.get_text(" ", strip=True))
                if not text:
                    continue
                if INGREDIENT_KEYWORDS.match(text) or INSTRUCTION_KEYWORDS.match(text):
                    break
                intro_paragraphs.append(text)
            elif el.name == "ul":
                # UL встретился раньше "SASTOJCI:" — значит, это часть вводного текста
                break

        if not intro_paragraphs:
            return None

        return " ".join(intro_paragraphs)

    # ------------------------------------------------------------------
    # Категория и теги
    # ------------------------------------------------------------------

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из Article.articleSection (JSON-LD)."""
        article = self._get_yoast_article_data()
        if not article:
            return None
        section = article.get("articleSection")
        if not section:
            return None
        if isinstance(section, list):
            return ", ".join(section)
        return self.clean_text(str(section))

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из Article.keywords (JSON-LD)."""
        article = self._get_yoast_article_data()
        if not article:
            return None
        keywords = article.get("keywords")
        if not keywords:
            return None
        if isinstance(keywords, list):
            return ", ".join(kw for kw in keywords if kw)
        return self.clean_text(str(keywords))

    # ------------------------------------------------------------------
    # Время
    # ------------------------------------------------------------------

    def _extract_times_from_instructions(self):
        """
        Разбирает инструкции и ищет упоминания времени.
        Возвращает dict: {"prep": str|None, "cook": str|None}
        """
        steps_text = self.extract_steps() or ""
        if not steps_text:
            return {"prep": None, "cook": None}

        # Паттерны для значений времени
        # Исключаем числа перед символом градуса (°C / °F) — это температура, не время
        time_value_re = re.compile(
            r"(\d+\s+do\s+\d+|\d+[–\-]\d+|pola sata|(?<!\d°)\b\d+\b(?!\s*°))",
            re.IGNORECASE
        )

        # Паттерны для единиц времени
        minutes_re = re.compile(r"\bminut[ae]?\b", re.IGNORECASE)
        hours_re = re.compile(r"\bsat[ai]?\b", re.IGNORECASE)
        half_hour_re = re.compile(r"pola sata", re.IGNORECASE)

        def normalize_time(val: str, unit: str) -> Optional[str]:
            """Преобразует значение времени в строку вида «30 minutes»."""
            val = val.strip()
            # «pola sata» → 30 минут
            if half_hour_re.search(val):
                return "30 minutes"
            # Диапазон «N do M» → «N-M»
            val = re.sub(r"(\d+)\s+do\s+(\d+)", r"\1-\2", val)
            # Диапазон «N–M»  уже с дефисом
            val = re.sub(r"(\d+)\s*[–]\s*(\d+)", r"\1-\2", val)
            if not re.search(r"\d", val):
                return None
            if "sat" in unit.lower():
                # Часы → минуты
                m = re.search(r"(\d+)", val)
                if m:
                    mins = int(m.group(1)) * 60
                    return f"{mins} minutes"
            return f"{val} minutes"

        prep_time: Optional[str] = None
        cook_time: Optional[str] = None

        # Разбиваем на предложения для поиска
        sentences = re.split(r"(?<=[.!?])\s+", steps_text)

        for sent in sentences:
            sent_lower = sent.lower()
            # Поиск значения времени в предложении
            tv_match = time_value_re.search(sent)
            if not tv_match:
                continue
            tv = tv_match.group(1)

            # Определяем единицу времени
            if half_hour_re.search(tv):
                unit = "minuta"
            elif minutes_re.search(sent):
                unit = "minuta"
            elif hours_re.search(sent):
                unit = "sat"
            else:
                continue

            time_str = normalize_time(tv, unit)
            if not time_str:
                continue

            # Контекст определяет тип времени
            is_cook = bool(re.search(
                r"\bpec[i]?\b|\bpecite\b|\bpeć\b|\bpečenje\b|\bzagr[ij]{1,2}[ae]\b|\bkuhajte\b|\bkuhaj\b",
                sent_lower
            ))
            is_prep = bool(re.search(
                r"\bhladnjak\b|\bdiž[ea]\b|\bdigne\b|\bdizati\b|\bmirov[ao]\b|\bodmaranje\b",
                sent_lower
            ))

            if is_cook and cook_time is None:
                cook_time = time_str
            elif is_prep and prep_time is None:
                prep_time = time_str

        return {"prep": prep_time, "cook": cook_time}

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки."""
        return self._extract_times_from_instructions().get("prep")

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления."""
        return self._extract_times_from_instructions().get("cook")

    def extract_total_time(self) -> Optional[str]:
        """Общее время (не представлено на сайте явно)."""
        return None

    # ------------------------------------------------------------------
    # Заметки
    # ------------------------------------------------------------------

    def extract_notes(self) -> Optional[str]:
        """
        Заметки/советы — это:
        1. Текст после «Dobar tek!» в контенте (если есть).
        2. Или последний абзац инструкций, содержащий типичные «хранение/совет» слова.
        """
        elements = self._iter_content_elements()
        if not elements:
            return None

        collecting_instructions = False
        after_dobar_tek: List[str] = []
        instruction_paragraphs: List[str] = []
        found_dobar_tek = False

        for el in elements:
            if el.name == "p":
                text = self.clean_text(el.get_text(" ", strip=True))
                if not text:
                    continue

                if INSTRUCTION_KEYWORDS.match(text):
                    collecting_instructions = True
                    continue

                if collecting_instructions:
                    if DOBAR_TEK.search(text):
                        found_dobar_tek = True
                        continue

                    if found_dobar_tek:
                        after_dobar_tek.append(text)
                    else:
                        instruction_paragraphs.append(text)

        # Приоритет: текст после «Dobar tek!»
        if after_dobar_tek:
            return " ".join(after_dobar_tek)

        # Запасной вариант: последние абзацы инструкций с ключевыми словами
        for para in reversed(instruction_paragraphs):
            if NOTE_KEYWORDS.search(para):
                return para

        return None

    # ------------------------------------------------------------------
    # Изображения
    # ------------------------------------------------------------------

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из контента и мета-тегов."""
        urls: List[str] = []
        seen: set = set()

        def add_url(url: Optional[str]):
            if url and url not in seen and "gravatar" not in url:
                seen.add(url)
                urls.append(url)

        # og:image — главное изображение
        og_image = self.soup.find("meta", property="og:image")
        if og_image:
            add_url(og_image.get("content"))

        # JSON-LD ImageObject (primaryimage + thumbnailUrl)
        for script in self.soup.find_all("script", type="application/ld+json"):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                graph = data.get("@graph") if isinstance(data, dict) else None
                if graph:
                    for item in graph:
                        if not isinstance(item, dict):
                            continue
                        if item.get("@type") == "ImageObject":
                            add_url(item.get("url") or item.get("contentUrl"))
                        elif item.get("@type") in ("Article", "WebPage"):
                            add_url(item.get("thumbnailUrl"))
            except (json.JSONDecodeError, AttributeError, KeyError):
                continue

        # Изображения из контента поста (src и data-src)
        container = self._get_post_content_container()
        if container:
            for img in container.find_all("img"):
                # Предпочитаем оригинал (src или data-src)
                for attr in ("src", "data-src"):
                    raw = img.get(attr, "")
                    if raw and not raw.startswith("data:"):
                        # Убираем resize-суффиксы, чтобы получить исходник
                        clean = re.sub(r"-\d+x\d+(\.\w+\.webp|\.\w+)$", r"\1", raw)
                        add_url(clean)
                        break

        return ",".join(urls) if urls else None

    # ------------------------------------------------------------------
    # Главный метод
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта."""
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
    """Обработка HTML-файлов из preprocessed/bezglutenskaradost_com."""
    import os

    base_dir = Path(__file__).parent.parent
    recipes_dir = base_dir / "preprocessed" / "bezglutenskaradost_com"

    if recipes_dir.exists() and recipes_dir.is_dir():
        process_directory(BezglutenskaradostComExtractor, str(recipes_dir))
    else:
        print(f"Директория не найдена: {recipes_dir}")
        print("Использование: python bezglutenskaradost_com.py")


if __name__ == "__main__":
    main()
