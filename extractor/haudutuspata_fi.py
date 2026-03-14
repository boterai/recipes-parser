"""
Экстрактор данных рецептов для сайта haudutuspata.fi
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Finnish measurement units used on haudutuspata.fi (ordered longest-first for regex)
_FINNISH_UNIT_LIST = [
    "kilogrammaa", "kappaletta", "litraa", "pakettia", "paketti",
    "purkkia", "purkki", "pussia", "pussi",
    "rkl", "tl", "dl", "ml", "cl", "kg", "kpl", "pkt", "pss", "prk",
    "g", "l",
]

# Regex for amount+unit+name: matches strings like "1 rkl öljyä", "n. 800 g lihaa", "1–2 kpl porkkanaa"
_AMOUNT_RE = r"(?:n\.\s*|noin\s*)?(?P<amount>[\d]+(?:[,./\-][\d]+)?(?:\s[\d]+/[\d]+)?)"
_UNIT_CANDIDATES = "|".join(re.escape(u) for u in _FINNISH_UNIT_LIST)
# Unit must be followed by whitespace or end-of-string to avoid matching within words (e.g. "l" in "laakerinlehteä")
_INGREDIENT_PATTERN = re.compile(
    rf"^{_AMOUNT_RE}\s*(?P<unit>{_UNIT_CANDIDATES})(?=\s|$)\s*(?P<name>.+)?$",
    re.IGNORECASE,
)
# Fallback: amount only, no unit
_AMOUNT_ONLY_PATTERN = re.compile(
    rf"^{_AMOUNT_RE}\s+(?P<name>[^\d].*)$",
    re.IGNORECASE,
)


class HaudutuspataFiExtractor(BaseRecipeExtractor):
    """Экстрактор для haudutuspata.fi"""

    def _get_article(self):
        """Возвращает основной элемент статьи рецепта."""
        return self.soup.find("article") or self.soup.find("div", class_="entry-content")

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда."""
        article = self._get_article()
        if article:
            h2 = article.find("h2")
            if h2:
                return self.clean_text(h2.get_text())

        # Fallback: h1 на странице
        h1 = self.soup.find("h1")
        if h1:
            title = self.clean_text(h1.get_text())
            # Убираем префикс "Haudutuspataresepti: " если он есть
            title = re.sub(r"^Haudutuspataresepti:\s*", "", title, flags=re.IGNORECASE)
            return title if title else None

        # Fallback: og:title
        og_title = self.soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"]
            title = re.sub(r"^Haudutuspataresepti:\s*", "", title, flags=re.IGNORECASE)
            return self.clean_text(title) or None

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта."""
        article = self._get_article()
        if article:
            h2 = article.find("h2")
            if h2:
                # Первый <p> после h2 — описание
                sibling = h2.find_next_sibling()
                while sibling:
                    if sibling.name == "p":
                        text = self.clean_text(sibling.get_text())
                        # Пропускаем параграфы с метаданными (Annoksia/Vaikeustaso/Aika)
                        strong = sibling.find("strong")
                        if strong:
                            sibling = sibling.find_next_sibling()
                            continue
                        if text:
                            return text
                    elif sibling.name in ("h3", "h2", "ul", "ol"):
                        break
                    sibling = sibling.find_next_sibling()

        # Fallback: meta description
        meta_desc = self.soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            return self.clean_text(meta_desc["content"]) or None

        og_desc = self.soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            return self.clean_text(og_desc["content"]) or None

        return None

    def _parse_ingredient_text(self, text: str) -> dict:
        """
        Парсинг строки ингредиента на поля name/amount/unit.

        Обрабатывает форматы:
          "1 rkl öljyä"
          "n. 800 g naudan patalihaa"
          "1–2 laakerinlehteä"
          "Mustapippuria maun mukaan"
          "½ paketti vietnamilaisista bo kho -mausteseosta"
        """
        text = self.clean_text(text)
        if not text:
            return {"name": text, "amount": None, "unit": None}

        # Добавляем пробел между цифрой и Unicode-дробью, чтобы "1½" → "1 ½"
        text = re.sub(r"(\d)([½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘])", r"\1 \2", text)

        # Заменяем Unicode дроби на обычные
        fraction_map = {
            "½": "1/2", "¼": "1/4", "¾": "3/4",
            "⅓": "1/3", "⅔": "2/3", "⅛": "1/8",
            "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
            "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5",
        }
        for frac, rep in fraction_map.items():
            text = text.replace(frac, rep)

        # Нормализуем разделители в диапазонах (– → -)
        text = text.replace("–", "-").replace("—", "-")

        m = _INGREDIENT_PATTERN.match(text)
        if not m:
            # Пробуем: число без единицы + название
            m2 = _AMOUNT_ONLY_PATTERN.match(text)
            if m2:
                raw_amount = m2.group("amount") or ""
                raw_name = m2.group("name") or ""
                amount = self._normalise_amount(raw_amount)
                name = self._clean_name(raw_name)
                if name:
                    return {"name": name, "amount": amount, "unit": None}
            # Нет числа — всё название
            return {"name": text, "amount": None, "unit": None}

        raw_amount = m.group("amount") or ""
        raw_unit = m.group("unit") or ""
        raw_name = m.group("name") or ""

        amount = self._normalise_amount(raw_amount)
        unit: Optional[str] = raw_unit.strip() if raw_unit else None
        name = self._clean_name(raw_name)

        if not name:
            return {"name": text, "amount": None, "unit": None}

        return {"name": name, "amount": amount if amount else None, "unit": unit}

    @staticmethod
    def _normalise_amount(raw: str) -> Optional[str]:
        """Нормализует строку количества: "1,4" → "1.4", "1/2" → "0.5", "1 1/2" → "1.5"."""
        if not raw:
            return None
        amt = raw.strip().replace(",", ".")
        # Диапазон типа "1-2" или "0.5-1" — оставляем как есть
        if re.search(r"\d-\d", amt):
            return amt
        if "/" in amt:
            parts = amt.split()
            total = 0.0
            for part in parts:
                if "/" in part:
                    num_str, den_str = part.split("/", 1)
                    try:
                        total += float(num_str) / float(den_str)
                    except (ValueError, ZeroDivisionError):
                        return amt
                else:
                    try:
                        total += float(part)
                    except ValueError:
                        return amt
            return str(int(total)) if total == int(total) else str(total)
        return amt

    @staticmethod
    def _clean_name(raw: str) -> str:
        """Удаляет завершающие запятые/точки и лишние пробелы из названия ингредиента."""
        name = raw.strip()
        name = re.sub(r"[,;.]+$", "", name).strip()
        return name

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов (возвращает JSON-строку списка словарей)."""
        article = self._get_article()
        if not article:
            logger.warning("Не найден элемент article в %s", self.html_path)
            return None

        # Находим h3 «Ainekset»
        ainekset_h3 = article.find("h3", string=lambda t: t and "ainekset" in t.lower())
        if not ainekset_h3:
            logger.warning("Секция 'Ainekset' не найдена в %s", self.html_path)
            return None

        ingredients = []

        # Перебираем siblings до следующего h3
        sibling = ainekset_h3.find_next_sibling()
        while sibling:
            if sibling.name == "h3":
                break
            if sibling.name in ("ul", "ol"):
                for li in sibling.find_all("li", recursive=False):
                    text = self.clean_text(li.get_text())
                    if text:
                        parsed = self._parse_ingredient_text(text)
                        if parsed:
                            ingredients.append(parsed)
            sibling = sibling.find_next_sibling()

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению."""
        article = self._get_article()
        if not article:
            return None

        # Находим h3 «Valmistusohjeet»
        instr_h3 = article.find(
            "h3",
            string=lambda t: t and "valmistusohjeet" in t.lower(),
        )
        if not instr_h3:
            logger.warning("Секция 'Valmistusohjeet' не найдена в %s", self.html_path)
            return None

        _NOTE_KEYWORDS = ("vinkki", "huom", "lisätietoja", "muista", "tärkeää")
        steps = []
        sibling = instr_h3.find_next_sibling()
        while sibling:
            if sibling.name == "h3":
                break
            if sibling.name in ("ol", "ul"):
                for li in sibling.find_all("li", recursive=False):
                    text = self.clean_text(li.get_text())
                    if text:
                        steps.append(text)
            elif sibling.name == "p":
                text = self.clean_text(sibling.get_text())
                # Если параграф начинается с ключевого слова заметки — пропускаем
                if text and any(text.lower().startswith(kw) for kw in _NOTE_KEYWORDS):
                    break
                if text:
                    steps.append(text)
                break  # Останавливаемся после первого p после ol
            sibling = sibling.find_next_sibling()

        return " ".join(steps) if steps else None

    def _extract_meta_value(self, label: str) -> Optional[str]:
        """Извлечение значения мета-поля по метке (например, 'Valmisteluaika:')."""
        article = self._get_article()
        if not article:
            return None

        # Ищем <p> с <strong>Метка:</strong> значение
        for p in article.find_all("p"):
            strong = p.find("strong")
            if strong and label.lower() in strong.get_text().lower():
                # Текст параграфа за исключением самой метки
                full_text = self.clean_text(p.get_text())
                # Убираем метку из начала
                label_text = self.clean_text(strong.get_text())
                value = full_text[len(label_text):].strip(": ").strip()
                return value if value else None

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки."""
        return self._extract_meta_value("Valmisteluaika")

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления."""
        return self._extract_meta_value("Kypsennysaika")

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени (не присутствует на сайте, возвращаем None)."""
        return self._extract_meta_value("Kokonaisaika") or None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда."""
        # Пробуем JSON-LD articleSection
        scripts = self.soup.find_all("script", type="application/ld+json")
        for script in scripts:
            try:
                data = json.loads(script.string or "")
                graph = data.get("@graph", []) if isinstance(data, dict) else []
                for item in graph:
                    if item.get("@type") == "Article":
                        sections = item.get("articleSection", [])
                        if isinstance(sections, list) and sections:
                            return sections[0]
                        if isinstance(sections, str) and sections:
                            return sections
            except (json.JSONDecodeError, AttributeError):
                continue

        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок / советов.

        Проверяет два места:
        1. Отдельный h3 с ключевыми словами («Vinkki», «Huom», …)
        2. Параграф после блока инструкций, начинающийся с «Vinkki:»
        """
        article = self._get_article()
        if not article:
            return None

        note_keywords = ("vinkki", "huom", "lisätietoja", "muista", "tärkeää")

        # 1. Отдельный h3 с ключевым словом заметки
        note_h3 = article.find(
            "h3",
            string=lambda t: t and any(kw in t.lower() for kw in note_keywords),
        )
        if note_h3:
            notes_parts = []
            sibling = note_h3.find_next_sibling()
            while sibling:
                if sibling.name == "h3":
                    break
                if sibling.name == "p":
                    text = self.clean_text(sibling.get_text())
                    if text:
                        notes_parts.append(text)
                elif sibling.name in ("ul", "ol"):
                    for li in sibling.find_all("li", recursive=False):
                        text = self.clean_text(li.get_text())
                        if text:
                            notes_parts.append(text)
                sibling = sibling.find_next_sibling()
            if notes_parts:
                return " ".join(notes_parts)

        # 2. Параграф «Vinkki:» сразу после блока инструкций
        instr_h3 = article.find(
            "h3",
            string=lambda t: t and "valmistusohjeet" in t.lower(),
        )
        if instr_h3:
            sibling = instr_h3.find_next_sibling()
            while sibling:
                if sibling.name == "h3":
                    break
                if sibling.name == "p":
                    text = self.clean_text(sibling.get_text())
                    if text and any(text.lower().startswith(kw) for kw in note_keywords):
                        # Убираем «Vinkki:» / «Vinkki» префикс
                        note_text = re.sub(
                            r"^(?:" + "|".join(note_keywords) + r")[:\s]+",
                            "",
                            text,
                            flags=re.IGNORECASE,
                        ).strip()
                        return note_text if note_text else None
                sibling = sibling.find_next_sibling()

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта."""
        # Теги через rel="tag"
        tag_links = self.soup.find_all("a", rel=lambda r: r and "tag" in r)
        if tag_links:
            tags = [self.clean_text(a.get_text()) for a in tag_links if a.get_text(strip=True)]
            if tags:
                return ", ".join(tags)

        # Теги из meta keywords
        keywords_meta = self.soup.find("meta", attrs={"name": "keywords"})
        if keywords_meta and keywords_meta.get("content"):
            return self.clean_text(keywords_meta["content"]) or None

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта."""
        urls = []

        # og:image
        og_image = self.soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            urls.append(og_image["content"])

        # twitter:image
        twitter_image = self.soup.find("meta", attrs={"name": "twitter:image"})
        if twitter_image and twitter_image.get("content"):
            urls.append(twitter_image["content"])

        # Изображения внутри article (не логотип, не аватар)
        article = self._get_article()
        if article:
            for img in article.find_all("img"):
                src = img.get("src") or img.get("data-src") or ""
                if src and "logo" not in src.lower() and "avatar" not in src.lower() and "gravatar" not in src.lower():
                    urls.append(src)

        # Убираем дубликаты
        seen: set = set()
        unique: list = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ",".join(unique) if unique else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта.
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        total_time = self.extract_total_time()
        notes = self.extract_notes()
        tags = self.extract_tags()
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
            "tags": tags,
            "image_urls": image_urls,
        }


def main():
    import os

    recipes_dir = os.path.join("preprocessed", "haudutuspata_fi")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(HaudutuspataFiExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python haudutuspata_fi.py")


if __name__ == "__main__":
    main()
