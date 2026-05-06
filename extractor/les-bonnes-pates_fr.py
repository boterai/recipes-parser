"""
Экстрактор данных рецептов для сайта les-bonnes-pates.fr
"""

import logging
import sys
from pathlib import Path
import json
import re
from typing import Optional, List

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class LesBonnesPatesFrExtractor(BaseRecipeExtractor):
    """Экстрактор для les-bonnes-pates.fr

    Сайт является WordPress-блогом без плагина рецептов и JSON-LD Recipe-схемы.
    Данные извлекаются из HTML-структуры статьи:
      - Название: тег <h1>
      - Описание: первый абзац <p> в .entry-content
      - Ингредиенты: списки <ul> под заголовком h2 со словом «ingrédient»
      - Инструкции: списки <ol>/<ul> под заголовком h2 со словом «préparation»/«étapes»
      - Категория: CSS-класс «category-XXX» на теге <article>
      - Времена: текстовые паттерны в содержимом статьи
      - Заметки: параграфы/списки под заголовками «conseil»/«astuce»/«suggestion»
    """

    # Маппинг слагов категорий WordPress → читаемое название на английском
    _CATEGORY_MAP = {
        "pates": "Main Course",
        "riz": "Main Course",
        "desserts": "Dessert",
        "pommes": "Dessert",
        "salades": "Salad",
        "soupes": "Soup",
        "entrees": "Starter",
        "plat-principal": "Main Course",
        "viandes": "Main Course",
        "poissons": "Main Course",
        "legumes": "Side Dish",
    }

    # Французские глаголы в повелительном наклонении, встречающиеся
    # в начале элементов списка ингредиентов
    _FR_IMPERATIVE_VERBS = (
        r"choisis|opte|intègre|ajoute|utilise|mets|verse|rassemble|prépare"
        r"|incorpore|réserve|fais|faites|prends|prenez|coupe|coupez"
    )

    # Французские единицы измерения для парсинга ингредиентов
    _FR_UNITS_PATTERN = (
        r"g|gr|grammes?|kg|kilogrammes?"
        r"|ml|cl|dl|l|litres?"
        r"|cuillères?\s+à\s+soupe|cuillères?\s+à\s+café"
        r"|c\.?\s*à\s*s\.?|c\.?\s*à\s*c\.?"
        r"|tasses?|verres?"
        r"|sachets?|paquets?|tranches?|portions?|morceaux?"
        r"|pincée?s?|gouttes?"
    )

    # Минимальная длина текста (символов), чтобы считаться значимым фрагментом
    _MIN_TEXT_LENGTH = 20

    # Допустимые границы длины имени ингредиента (символов)
    _MIN_INGREDIENT_NAME_LEN = 2   # «ай» / «sel»
    _MAX_INGREDIENT_NAME_LEN = 60  # «pâtes longues (spaghettis ou linguines)»

    # Минимальная длина абзаца-инструкции — длиннее _MIN_TEXT_LENGTH,
    # чтобы фильтровать однословные глагольные предложения
    _MIN_INSTRUCTION_PARA_LENGTH = 40

    # Глаголы кулинарного действия (используется для выявления параграфов-инструкций)
    # Примечания по дизайну:
    #   • saute(?:[rz]\w*)?\b — соответствует «saute», «sauter», «sautez», но НЕ «sauté»
    #     (поскольку «é» — символ Unicode и не входит в [rz], а также образует
    #     границу слова после «saute» только если следующий символ не является словесным)
    #   • cuis(?:ez|ent|ons|iez)\b — только спряжённые формы «cuire»; исключает
    #     «cuisine» (кухня) и «cuisson» (время готовки)
    _COOKING_ACTION_RE = re.compile(
        r"\b(?:rinc|plonge|égoutt|mélange|verse|incorpore|ajoute|assaisonn|porte|préchauff|bouill)\w*\b"
        r"|\bsaute(?:[rz]\w*)?\b"
        r"|\bfais\s+(?:chauffer|sauter|revenir|cuire|bouillir)\b"
        r"|\bfaites\s+\w+\b"
        r"|\bcuire\b|\bcuis(?:ez|ent|ons|iez)\b",
        re.IGNORECASE,
    )

    def _get_entry_content(self):
        """Возвращает основной контейнер содержимого .entry-content"""
        return self.soup.find("div", class_="entry-content")

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _iter_section(self, entry, h2_keywords: List[str]):
        """
        Генерирует дочерние элементы entry-content, принадлежащие разделу,
        чей заголовок h2 содержит хотя бы одно из h2_keywords.

        Итерация останавливается при встрече следующего тега h2.
        """
        in_section = False
        for el in entry.children:
            if not hasattr(el, "name") or not el.name:
                continue
            if el.name == "h2":
                text = el.get_text(strip=True).lower()
                if any(kw in text for kw in h2_keywords):
                    in_section = True
                elif in_section:
                    return  # следующий h2 завершает секцию
            elif in_section:
                yield el

    def _get_first_para_before_h3(self, entry, h2_keywords: List[str]) -> Optional[str]:
        """
        Возвращает текст первого элемента <p> в разделе h2 (до появления первого h3).

        Используется для извлечения вводного абзаца раздела, который часто содержит
        ключевые ингредиенты или краткое изложение инструкций.
        """
        h3_seen = False
        for el in self._iter_section(entry, h2_keywords):
            if el.name == "h3":
                h3_seen = True
            elif el.name == "p" and not h3_seen:
                text = el.get_text(separator=" ", strip=True)
                if text:
                    return self.clean_text(text)
        return None

    def _extract_prose_ingredients_from_text(self, text: str) -> List[dict]:
        """
        Извлекает упоминания ингредиентов из прозаического французского текста.

        Применяет четыре паттерна:
          1. «comme des/les X, Y et Z»
          2. «Opte pour des X comme les Y ou les Z» → «X (Y ou Z)»
          3. «avec de l'/du/des/quelques X[, Y et Z]»
          4. «Privilégie l'X et de l'Y»
        """

        def _split_and_clean(items_text: str) -> List[str]:
            """Разбивает перечень «X, Y et Z» и очищает артикли."""
            parts = re.split(r",\s*|\s+et\s+|\s+ou\s+", items_text)
            cleaned = []
            for p in parts:
                p = p.strip()
                # Убираем ведущие «et »/«ou » (остаток после «, et» разбивки)
                p = re.sub(r"^(?:et|ou)\s+", "", p, flags=re.IGNORECASE)
                # Убираем неопределённые артикли / предлоги
                p = re.sub(
                    r"^(?:des?\s+|les?\s+|l[\u2019\u2018]?\s*|de\s+la\s+"
                    r"|du\s+|d[\u2019\u2018]\s*|quelques\s+"
                    r"|un\s+peu\s+de\s+|un\s+filet\s+de\s+|une\s+\w+\s+de\s+)",
                    "",
                    p,
                    flags=re.IGNORECASE,
                )
                # Убираем хвостовую фразу «pour ...» / «afin de ...»
                p = re.sub(
                    r"\s+(?:pour|afin\s+de|afin\s+d[\u2019])\s+.+$",
                    "",
                    p,
                    flags=re.IGNORECASE,
                )
                p = p.strip().rstrip(".,;()")
                if self._MIN_INGREDIENT_NAME_LEN < len(p) < self._MAX_INGREDIENT_NAME_LEN:
                    cleaned.append(p)
            return cleaned

        found: List[str] = []

        # Паттерн 1: «comme des/les/le X, Y et Z»
        for m in re.finditer(
            r"comme\s+(?:des?\s*|les?\s*|l[\u2019\u2018]?\s*)([^.]+?)(?:\.|$)",
            text,
            re.IGNORECASE,
        ):
            found.extend(_split_and_clean(m.group(1)))

        # Паттерн 2: «Opte pour des X [comme les Y ou les Z]» → «X (Y ou Z)»
        for m in re.finditer(
            r"[Oo]pte\s+pour\s+(?:des?\s*|les?\s*)(.+?)(?:\.|$)",
            text,
            re.IGNORECASE,
        ):
            raw = m.group(1).strip().rstrip(".,;")
            like_m = re.search(
                r"^(.+?)\s+comme\s+(?:les?\s*|des?\s*)(.+)", raw, re.IGNORECASE
            )
            if like_m:
                main_part = like_m.group(1).strip().rstrip(",")
                specs = re.sub(
                    r"\s*(les?\s+|des?\s+)", " ", like_m.group(2)
                ).strip().rstrip(".,;")
                found.append(f"{main_part} ({specs})")
            else:
                item = re.sub(
                    r"^(?:des?\s+|les?\s+|l[\u2019]?\s*)", "", raw, flags=re.IGNORECASE
                )
                if self._MIN_INGREDIENT_NAME_LEN < len(item.strip()) < self._MAX_INGREDIENT_NAME_LEN:
                    found.append(item.strip())

        # Паттерн 3: «avec de l'/du/des/quelques X[, Y et Z]»
        for m in re.finditer(
            r"\bavec\s+(?:de\s+(?:l[\u2019\u2018]\s*|la\s+|les?\s+)"
            r"|du\s+|des?\s+|l[\u2019\u2018]\s*|quelques\s+|un\s+filet\s+de\s+)"
            r"([^.]+?)(?:\.|$)",
            text,
            re.IGNORECASE,
        ):
            found.extend(_split_and_clean(m.group(1)))

        # Паттерн 4: «Privilégie l'X et de l'Y»
        for m in re.finditer(
            r"[Pp]rivilégi\w+\s+(?:l[\u2019\u2018]|les?\s+|des?\s+|du\s+)"
            r"([^.]+?)(?:\s+pour\s+|\.|$)",
            text,
            re.IGNORECASE,
        ):
            items_text = m.group(1)
            items = re.split(
                r"\s+et\s+(?:(?:de\s+)?(?:l[\u2019\u2018]|les?\s+|des?\s+|du\s+))?",
                items_text,
            )
            for item in items:
                item = re.sub(
                    r"^(?:des?\s+|les?\s+|l[\u2019]?\s*|de\s+la\s+|du\s+)",
                    "",
                    item.strip(),
                    flags=re.IGNORECASE,
                )
                item = item.strip().rstrip(".,;")
                if self._MIN_INGREDIENT_NAME_LEN < len(item) < self._MAX_INGREDIENT_NAME_LEN:
                    found.append(item)

        return [{"name": item, "amount": None, "unit": None} for item in found]

    def _clean_ingredient_text(self, text: str) -> str:
        """
        Очищает строку элемента ингредиентного списка:
          - убирает ведущие французские повелительные глаголы;
          - убирает «pour <цель>» в конце;
          - убирает неопределённые артикли (des, de la, de l', d', le, la, les, un, une);
          - убирает завершающую пунктуацию.
        """
        text = self.clean_text(text)
        if not text:
            return text

        # Убираем ведущий глагол (Choisis des ..., Opte pour ..., и т.д.)
        text = re.sub(
            rf"^(?:{self._FR_IMPERATIVE_VERBS})\s+",
            "",
            text,
            flags=re.IGNORECASE,
        )

        # Убираем «pour» + остаток в начале (после «Opte pour»)
        text = re.sub(r"^pour\s+", "", text, flags=re.IGNORECASE)

        # Убираем «pour <цель>» или «afin de» в конце
        text = re.sub(
            r"\s+(?:pour|afin\s+de|afin\s+d['\u2019])\s+.+$",
            "",
            text,
            flags=re.IGNORECASE,
        )

        # Убираем ведущие артикли / предлоги
        text = re.sub(
            r"^(?:des|de\s+la|de\s+l['\u2019]|d['\u2019]|les|la|le|un|une)\s+",
            "",
            text,
            flags=re.IGNORECASE,
        )

        # Убираем завершающую пунктуацию
        text = text.rstrip(".,;").strip()

        return text

    def _parse_ingredient_french(self, raw_text: str) -> Optional[dict]:
        """
        Разбирает строку ингредиента в структурированный словарь
        {"name": ..., "amount": ..., "unit": ...}.

        Args:
            raw_text: Строка из HTML, например «200 g de farine» или «crevettes fraîches»

        Returns:
            dict или None, если текст слишком короткий.
        """
        text = self._clean_ingredient_text(raw_text)
        if not text or len(text) < 2:
            return None

        # Нормализуем Unicode-дроби
        fraction_map = {
            "\u00bd": "0.5",
            "\u00bc": "0.25",
            "\u00be": "0.75",
            "\u2153": "0.33",
            "\u2154": "0.67",
            "\u215b": "0.125",
        }
        for frac, val in fraction_map.items():
            text = text.replace(frac, val)

        # Паттерн: число? единица? (de/d')? название
        pattern = (
            rf"^([\d\s/.,]+)?\s*"
            rf"({self._FR_UNITS_PATTERN})?\s*"
            rf"(?:de\s+|d['\u2019])?"
            rf"(.+)"
        )
        match = re.match(pattern, text, re.IGNORECASE)

        if not match:
            return {"name": text, "amount": None, "unit": None}

        amount_str, unit, name = match.groups()

        # Обработка количества
        amount = None
        if amount_str and amount_str.strip():
            amount_str = amount_str.strip()
            try:
                if "/" in amount_str:
                    parts = amount_str.split()
                    total = 0.0
                    for part in parts:
                        if "/" in part:
                            num, denom = part.split("/")
                            total += float(num) / float(denom)
                        else:
                            total += float(part)
                    amount = str(int(total)) if total == int(total) else str(total)
                else:
                    amount = amount_str.replace(",", ".")
            except (ValueError, ZeroDivisionError):
                amount = amount_str

        unit = unit.strip() if unit and unit.strip() else None

        # Очищаем название
        name = self.clean_text(name) if name else None
        if name:
            # Убираем дополнительные описания «coupées en julienne», «pour la couleur», etc.
            name = re.sub(
                r"\s+(?:pour\s+(?:la|le|les|une|un|sa|son|leur)\s+.+|coupée?s?|émincée?s?|haché?e?s?|râpé?e?s?)$",
                "",
                name,
                flags=re.IGNORECASE,
            )
            name = name.rstrip(".,;").strip()

        if not name or len(name) < 2:
            return None

        return {"name": name, "amount": amount, "unit": unit}

    def _extract_time_from_text(self, text: str) -> Optional[str]:
        """
        Ищет первое упоминание времени в строке (N minutes / N heures).
        Поддерживает диапазоны: «2 à 4 minutes», «2 et 4 minutes», «2-4 minutes».

        Returns:
            Строка типа «30 minutes», «2-4 minutes» или None.
        """
        match = re.search(
            r"(\d+(?:\s*(?:à|et|[-\u2013])\s*\d+)?)\s*(minutes?|heures?|heure|min|h)\b",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        amount = match.group(1).strip()
        # Нормализуем «à»/«et» → «-» для диапазонов
        amount = re.sub(r"\s*(?:à|et)\s*", "-", amount)
        unit = match.group(2).strip().lower()
        if "heure" in unit or unit == "h":
            return f"{amount} hours"
        return f"{amount} minutes"

    # ------------------------------------------------------------------
    # Публичные методы извлечения данных
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из тега <h1>"""
        h1 = self.soup.find("h1")
        if h1:
            text = h1.get_text(strip=True)
            # Убираем французский подзаголовок после « : »
            text = re.sub(r"\s*:\s*.+$", "", text).strip()
            # Убираем подзаголовок после « - »
            text = re.sub(r"\s+-\s+.+$", "", text).strip()
            # Убираем вопросительный знак в конце
            text = text.rstrip("?").strip()
            return self.clean_text(text) if text else None

        # Запасной вариант: og:title
        og_title = self.soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"]
            title = re.sub(r"\s*[-\u2013|]\s*.*$", "", title)
            return self.clean_text(title)

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания: первый содержательный абзац в .entry-content"""
        entry = self._get_entry_content()
        if entry:
            for el in entry.children:
                if not hasattr(el, "name") or not el.name:
                    continue
                if el.name == "p":
                    text = el.get_text(separator=" ", strip=True)
                    text = self.clean_text(text)
                    if text and len(text) > self._MIN_TEXT_LENGTH:
                        return text

        # Запасные варианты
        for meta_name in ({"name": "description"}, {"property": "og:description"}):
            meta = self.soup.find("meta", meta_name)
            if meta and meta.get("content"):
                return self.clean_text(meta["content"])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из раздела h2 «ingrédient».

        Стратегия (три прохода):
          1. Структурированные UL/OL из раздела «ingrédient».
          2. Прозаические паттерны из вводного абзаца раздела «ingrédient».
          3. Прозаические паттерны из первых абзацев разделов «cuisson des» и «assemblage»
             — для захвата приправ и трав, упомянутых в шагах готовки.

        Возвращает JSON-строку со списком словарей {"name", "amount", "unit"}.
        """
        entry = self._get_entry_content()
        if not entry:
            logger.warning("les-bonnes-pates: entry-content not found (ingredients)")
            return None

        ingredients: list = []
        seen_names: set = set()

        def _add(ingr_dict: dict) -> None:
            key = ingr_dict["name"].lower().strip()
            if key and key not in seen_names:
                seen_names.add(key)
                ingredients.append(ingr_dict)

        # 1. Структурированные списки из раздела «ingrédient»
        for el in self._iter_section(entry, ["ingrédient", "ingredient"]):
            if el.name not in ("ul", "ol"):
                continue
            # Пропускаем OL-«замены/варианты» под h3 с ними
            parent_h3 = el.find_previous_sibling("h3")
            if parent_h3:
                h3_text = parent_h3.get_text(strip=True).lower()
                if any(
                    kw in h3_text
                    for kw in ("substitution", "option", "variante", "remplacement")
                ):
                    continue

            for li in el.find_all("li"):
                raw = li.get_text(separator=" ", strip=True)
                parsed = self._parse_ingredient_french(raw)
                if parsed:
                    _add(parsed)

        # 2. Прозаические паттерны из вводного абзаца раздела «ingrédient»
        ingr_intro = self._get_first_para_before_h3(entry, ["ingrédient", "ingredient"])
        if ingr_intro:
            for ingr in self._extract_prose_ingredients_from_text(ingr_intro):
                _add(ingr)

        # 3. Прозаические паттерны из первых абзацев разделов готовки
        #    (перехватывает приправы / зелень, упоминаемые в кулинарных инструкциях)
        for cooking_kw in (["cuisson des"], ["assemblage"]):
            para = self._get_first_para_before_h3(entry, cooking_kw)
            if para:
                for ingr in self._extract_prose_ingredients_from_text(para):
                    _add(ingr)

        if not ingredients:
            logger.warning("les-bonnes-pates: no ingredients found")
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def extract_steps(self) -> Optional[str]:
        """
        Извлечение инструкций приготовления.

        Сканирует h2-разделы «préparation»/«étapes»/«cuisson»/«assemblage».
        Собирает:
          - параграфы с кулинарными глаголами (prose-шаги из разделов без OL);
          - OL-элементы из не-исключённых h3-подразделов.
        При полном отсутствии контента — используется первый UL из раздела «préparation».
        """
        entry = self._get_entry_content()
        if not entry:
            logger.warning("les-bonnes-pates: entry-content not found (steps)")
            return None

        # h2 со словами, означающими раздел инструкций
        step_h2_keywords = [
            "préparation", "étapes", "etapes", "cuisson", "assemblage", "technique"
        ]
        # h3, под которыми OL/P содержат советы/варианты, а не шаги рецепта
        exclude_h3_keywords = [
            "astuce", "conseil", "option", "substitution", "variante", "gagner",
            "présentation", "personnelle", "herbe", "épice", "nutritionnel",
        ]

        para_steps: list = []  # параграфы с кулинарными глаголами (в порядке документа)
        ol_items: list = []
        ul_first: list = []
        current_h2: Optional[str] = None
        current_h3: Optional[str] = None
        in_step_section = False

        for el in entry.children:
            if not hasattr(el, "name") or not el.name:
                continue

            if el.name == "h2":
                current_h2 = el.get_text(strip=True).lower()
                current_h3 = None
                in_step_section = any(kw in current_h2 for kw in step_h2_keywords)
                continue

            if el.name == "h3":
                current_h3 = el.get_text(strip=True).lower()
                continue

            if not in_step_section:
                continue

            is_excluded_h3 = current_h3 and any(
                kw in current_h3 for kw in exclude_h3_keywords
            )

            if el.name == "ul" and not ul_first:
                ul_first = [
                    self.clean_text(li.get_text(separator=" ", strip=True))
                    for li in el.find_all("li")
                    if li.get_text(strip=True)
                ]

            elif el.name == "ol":
                # Пропускаем OL под заголовком h3 с советами/вариантами
                if is_excluded_h3:
                    continue
                for li in el.find_all("li"):
                    text = self.clean_text(li.get_text(separator=" ", strip=True))
                    if text:
                        ol_items.append(text)

            elif el.name == "p" and not is_excluded_h3:
                # Включаем параграф, если он содержит кулинарные глаголы действия
                text = self.clean_text(el.get_text(separator=" ", strip=True))
                if text and len(text) > self._MIN_INSTRUCTION_PARA_LENGTH and self._COOKING_ACTION_RE.search(text):
                    para_steps.append(text)

        # Объединяем: prose-шаги + OL. Если ничего нет — fallback на первый UL
        steps = para_steps + ol_items
        if not steps:
            steps = ul_first

        if not steps:
            logger.warning("les-bonnes-pates: no instructions found")
            return None

        return " ".join(steps)

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из CSS-класса «category-XXX» тега <article>"""
        article = self.soup.find("article")
        if article:
            for cls in article.get("class", []):
                if cls.startswith("category-"):
                    slug = cls[len("category-"):]
                    return self._CATEGORY_MAP.get(slug, slug.replace("-", " ").title())
        return None

    def extract_prep_time(self) -> Optional[str]:
        """
        Извлечение времени подготовки.

        Ищет паттерны «reposer X minutes» / «temps de préparation X».
        """
        entry = self._get_entry_content()
        if not entry:
            return None

        text = entry.get_text()

        prep_patterns = [
            # «reposer [N chars] X minutes» — гибкий паттерн для «reposer sous un linge humide pendant 30 minutes»
            r"reposer[^.]{0,60}?(\d+(?:\s*(?:à|et|[-\u2013])\s*\d+)?)\s*(minutes?|heures?|h)\b",
            r"temps?\s+de\s+prépara\w*[^.]{0,30}?(\d+(?:\s*(?:à|et|[-\u2013])\s*\d+)?)\s*(minutes?|heures?)",
            r"prépara\w+[^.]{0,30}?(\d+(?:\s*(?:à|et|[-\u2013])\s*\d+)?)\s*(minutes?|heures?)",
        ]

        for pattern in prep_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                amount = re.sub(r"\s*(?:à|et)\s*", "-", match.group(1).strip())
                unit = match.group(2).strip().lower()
                if "heure" in unit or unit == "h":
                    return f"{amount} hours"
                return f"{amount} minutes"

        return None

    def extract_cook_time(self) -> Optional[str]:
        """
        Извлечение времени приготовления.

        Приоритет: тег h3 «Temps de cuisson» → паттерны в тексте.
        """
        entry = self._get_entry_content()
        if not entry:
            return None

        # Ищем раздел h3 «Temps de cuisson»
        for h3 in entry.find_all("h3"):
            if "temps de cuisson" in h3.get_text(strip=True).lower():
                nxt = h3.find_next_sibling()
                if nxt and nxt.name == "p":
                    t = self._extract_time_from_text(nxt.get_text())
                    if t:
                        return t

        text = entry.get_text()

        cook_patterns = [
            r"(?:en|plat\s+savoureux\s+en|prêt\s+en)\s+(?:moins\s+de\s+)?(\d+)\s*(minutes?|heures?)",
            r"cuire\s+(?:pendant\s+)?(\d+(?:\s*[-\u2013]\s*\d+)?)\s*(minutes?|heures?)",
            r"cuisson\s+(?:de\s+)?(?:entre\s+)?(\d+(?:\s+(?:à|et)\s+\d+)?)\s*(minutes?|heures?)",
        ]

        for pattern in cook_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                amount = re.sub(r"\s*(?:à|et)\s*", "-", match.group(1).strip())
                unit = match.group(2).strip().lower()
                if "heure" in unit or unit == "h":
                    return f"{amount} hours"
                return f"{amount} minutes"

        return None

    def extract_total_time(self) -> Optional[str]:
        """
        Извлечение общего времени.

        Ищет паттерны «prêt en X minutes» / «repas … en X minutes».
        """
        entry = self._get_entry_content()
        if not entry:
            return None

        text = entry.get_text()

        total_patterns = [
            r"(?:prêt\s+en|repas\s+(?:complet\s+)?en)\s+(?:moins\s+de\s+)?(\d+)\s*(minutes?|heures?)",
            r"(?:temps\s+total|total)\s*:?\s*(\d+)\s*(minutes?|heures?)",
            r"(?:en\s+(?:seulement\s+)?)(\d+)\s*(minutes?|heures?)\s*(?:chrono|seulement|tout\s+au\s+plus|maxi)",
        ]

        for pattern in total_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                amount = match.group(1).strip()
                unit = match.group(2).strip().lower()
                if "heure" in unit or unit == "h":
                    return f"{amount} hours"
                return f"{amount} minutes"

        return None

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение советов/заметок из разделов h2 «conseil»/«astuce»/«suggestion».
        """
        entry = self._get_entry_content()
        if not entry:
            return None

        note_keywords = ["astuce", "conseil", "suggestion", "variante", "remarque"]
        notes: list = []

        for el in self._iter_section(entry, note_keywords):
            if el.name == "p":
                text = self.clean_text(el.get_text(separator=" ", strip=True))
                if text and len(text) > self._MIN_TEXT_LENGTH:
                    notes.append(text)
            elif el.name in ("ul", "ol"):
                for li in el.find_all("li"):
                    text = self.clean_text(li.get_text(separator=" ", strip=True))
                    if text and len(text) > self._MIN_TEXT_LENGTH // 2:
                        notes.append(text)

        if not notes:
            return None

        return " ".join(notes)

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из meta keywords или ссылок rel=tag"""
        meta_kw = self.soup.find("meta", {"name": "keywords"})
        if meta_kw and meta_kw.get("content"):
            return self.clean_text(meta_kw["content"])

        tag_links = self.soup.find_all("a", rel="tag")
        if tag_links:
            tags = [a.get_text(strip=True) for a in tag_links if a.get_text(strip=True)]
            if tags:
                return ", ".join(tags)

        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Извлечение URL изображений рецепта.

        Исключаются логотипы сайта и аватары авторов.
        """
        _EXCLUDE = ("gravatar", "logo", "avatar")

        def _is_excluded(url: str, alt: str) -> bool:
            combined = (url + " " + alt).lower()
            return any(kw in combined for kw in _EXCLUDE)

        urls: list = []
        seen: set = set()

        # og:image
        og_image = self.soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            url = og_image["content"]
            if not _is_excluded(url, "") and url not in seen:
                urls.append(url)
                seen.add(url)

        # Изображения в контенте статьи
        entry = self._get_entry_content()
        if entry:
            for img in entry.find_all("img"):
                src = img.get("data-lazy-src") or img.get("src", "")
                alt = img.get("alt", "")
                if (
                    src
                    and "svg+xml" not in src
                    and not _is_excluded(src, alt)
                    and src not in seen
                ):
                    urls.append(src)
                    seen.add(src)

        return ",".join(urls) if urls else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            dict с полями: dish_name, description, ingredients, instructions,
            category, prep_time, cook_time, total_time, notes, image_urls, tags.
        """
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_steps(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags(),
        }


def main():
    import os

    recipes_dir = os.path.join("preprocessed", "les-bonnes-pates_fr")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(LesBonnesPatesFrExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python les-bonnes-pates_fr.py [путь_к_файлу_или_директории]")


if __name__ == "__main__":
    main()
