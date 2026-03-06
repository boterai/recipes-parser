"""
Экстрактор данных рецептов для сайта recetteriche.com
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


# Маппинг категорий WordPress-slug → читаемое название
_CATEGORY_MAP = {
    "desserts": "Dessert",
    "plats": "Main Course",
    "entrees": "Starter",
    "petit-dejeuner": "Breakfast",
    "soupes": "Soup",
    "salades": "Salad",
    "snacks": "Snack",
    "boissons": "Drink",
}


class RecetteRicheExtractor(BaseRecipeExtractor):
    """Экстрактор для recetteriche.com"""

    # ------------------------------------------------------------------ helpers

    def _get_article(self):
        """Возвращает тег <article> страницы (или <body> как запасной вариант)."""
        return self.soup.find("article") or self.soup.find("body")

    def _get_section_after_heading(self, heading_re: re.Pattern):
        """
        Возвращает список тегов между заголовком h2, текст которого
        совпадает с heading_re, и следующим заголовком h2.
        """
        article = self._get_article()
        if not article:
            return []

        h2 = article.find("h2", string=heading_re)
        if not h2:
            return []

        elements = []
        sibling = h2.find_next_sibling()
        while sibling and sibling.name != "h2":
            elements.append(sibling)
            sibling = sibling.find_next_sibling()
        return elements

    def _collect_li_texts(self, elements) -> list[str]:
        """
        Собирает тексты всех <li> элементов (в т.ч. вложенных списков)
        из переданных тегов.
        """
        texts = []
        for el in elements:
            if el.name not in ("ul", "ol"):
                continue
            for li in el.find_all("li", recursive=False):
                # Проверяем наличие вложенного списка (тематические подгруппы)
                sub_list = li.find(["ul", "ol"])
                if sub_list:
                    for sub_li in sub_list.find_all("li", recursive=False):
                        raw = sub_li.get_text(separator=" ", strip=True)
                        if raw:
                            texts.append(raw)
                else:
                    raw = li.get_text(separator=" ", strip=True)
                    if raw:
                        texts.append(raw)
        return texts

    # ------------------------------------------------ ingredient parsing

    @staticmethod
    def _replace_unicode_fractions(text: str) -> str:
        """Заменяет Unicode-дроби на десятичные строки."""
        fractions = {
            "½": "0.5", "¼": "0.25", "¾": "0.75",
            "⅓": "0.333", "⅔": "0.667", "⅛": "0.125",
            "⅜": "0.375", "⅝": "0.625", "⅞": "0.875",
        }
        for ch, rep in fractions.items():
            text = text.replace(ch, rep)
        return text

    @staticmethod
    def _str_to_number(s: str):
        """Конвертирует строку в int или float; возвращает строку если не удалось."""
        try:
            val = float(s.replace(",", "."))
            return int(val) if val == int(val) else round(val, 4)
        except (ValueError, OverflowError):
            return s

    def _parse_ingredient_item(self, text: str) -> Optional[dict]:
        """
        Разбирает строку ингредиента на {name, amount, unit}.

        Формат строк на recetteriche.com:
          «▢ <кол-во> <единица> [de/d'/du/des] <название> [: описание]»
        или просто
          «▢ <название> [: описание]»  (без количества)

        Возвращает None если строку нельзя распознать как ингредиент.
        """
        if not text:
            return None

        # Убираем маркер ▢/□ и эмодзи
        text = re.sub(r"^[▢□\s]+", "", text).strip()
        text = re.sub(r"[\U0001F300-\U0001FFFF\U00002600-\U000027BF]", "", text)
        text = re.sub(r"\s+", " ", text).strip()

        # Берём только текст до первого двоеточия (убираем описание)
        text = text.split(":")[0].strip().rstrip(".,;")

        if not text:
            return None

        # Заменяем Unicode-дроби
        text = self._replace_unicode_fractions(text)

        # --- Попытка извлечь ведущее число ---
        num_pattern = re.compile(
            r"^((?:\d+\s+)?\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?)\s+"
        )
        num_match = num_pattern.match(text)

        if not num_match:
            # Нет числа → только название
            name = text.lower()
            name = re.sub(r"\([^)]*\)", "", name).strip()
            name = re.sub(r"\s+", " ", name).strip()
            return {"name": name, "amount": None, "unit": None} if name else None

        amount_str = num_match.group(1).strip()
        amount = self._str_to_number(amount_str)
        remaining = text[num_match.end():]

        # --- Ищем разделитель «de/d'/du/des/l'» между единицей и названием ---
        # Обрабатываем как прямой апостроф ('), так и типографский (', U+2019)
        connector_re = re.compile(
            r"\s+(?:de|du|des)\s+|\s+d['\u2019]|\s+l['\u2019]", re.IGNORECASE
        )
        matches = list(connector_re.finditer(remaining))

        if not matches:
            # Нет разделителя → весь хвост считаем единицей
            unit = remaining.strip() or None
            return {"name": None, "amount": amount, "unit": unit}

        # Берём первый разделитель
        m = matches[0]
        unit_raw = remaining[: m.start()].strip() or None
        name_raw = remaining[m.end():].strip()

        # Если name_raw начинается с числа (вложенное уточнение типа «200 g de X»),
        # ищем следующий разделитель
        sub_num = re.match(r"^[\d.,]+\s+\S+\s+", name_raw)
        if sub_num:
            sub_connector = connector_re.search(name_raw)
            if sub_connector:
                name_raw = name_raw[sub_connector.end():].strip()

        # Обрезаем имя по первой запятой и убираем хвостовые скобки
        if "," in name_raw:
            name_raw = name_raw.split(",")[0]
        name_raw = re.sub(r"\s*\([^)]*\)\s*$", "", name_raw).strip()
        name = name_raw.lower() if name_raw else None

        if not name:
            return None

        return {"name": name, "amount": amount, "unit": unit_raw}

    # ---------------------------------------------------------------- extractors

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из <h1>."""
        article = self._get_article()
        if not article:
            return None

        h1 = article.find("h1")
        if h1:
            return self.clean_text(h1.get_text())

        # Запасной вариант: og:title
        og_title = self.soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return self.clean_text(og_title["content"])

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение первого абзаца статьи (введение/анонс)."""
        article = self._get_article()
        if not article:
            return None

        entry_content = article.find(class_="entry-content") or article

        for child in entry_content.children:
            if not hasattr(child, "name"):
                continue
            if child.name == "h2":
                break
            if child.name == "p":
                text = self.clean_text(child.get_text())
                if text and len(text) > 30:
                    return text

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из секции «Ingrédients».

        Возвращает JSON-строку со списком словарей {name, amount, unit}
        или None если ингредиенты не найдены.
        """
        elements = self._get_section_after_heading(
            re.compile(r"ingr", re.IGNORECASE)
        )

        if not elements:
            logger.warning("Секция ингредиентов не найдена: %s", self.html_path)
            return None

        raw_texts = self._collect_li_texts(elements)
        ingredients = []

        for raw in raw_texts:
            # Фильтруем строки без числа И без ▢ (скорее всего описания/советы)
            has_number = bool(re.match(r"^\s*[\d▢□½¼¾⅓⅔⅛]", raw))
            if not has_number:
                continue

            parsed = self._parse_ingredient_item(raw)
            if parsed:
                ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """
        Извлечение инструкций из секции «Instructions».

        Объединяет текст всех шагов в одну строку.
        """
        elements = self._get_section_after_heading(
            re.compile(r"instruction", re.IGNORECASE)
        )

        if not elements:
            logger.warning("Секция инструкций не найдена: %s", self.html_path)
            return None

        steps = []
        step_num = 1

        for el in elements:
            if el.name == "ol":
                for li in el.find_all("li", recursive=True):
                    text = self.clean_text(li.get_text(separator=" "))
                    if text:
                        steps.append(f"{step_num}. {text}")
                        step_num += 1

            elif el.name == "p":
                text = self.clean_text(el.get_text(separator=" "))
                # Принимаем только абзацы, начинающиеся с эмодзи-цифры или цифры
                if text and re.match(r"^[0-9]|^[1-9]️⃣|^\d️", text):
                    # Убираем emoji-цифровой префикс и восстанавливаем нумерацию
                    text_clean = re.sub(
                        r"^[\d️⃣]+\s*[\.,:]?\s*", "", text
                    ).strip()
                    if text_clean:
                        steps.append(f"{step_num}. {text_clean}")
                        step_num += 1

        return " ".join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """
        Извлечение категории из CSS-класса <article> (category-*).
        """
        article = self._get_article()
        if not article:
            return None

        classes = article.get("class", [])
        for cls in classes:
            if cls.startswith("category-"):
                slug = cls[len("category-"):]
                return _CATEGORY_MAP.get(slug, slug.replace("-", " ").title())

        return None

    def _extract_time_value(self, pattern: re.Pattern) -> Optional[str]:
        """
        Ищет в секции «Temps de Préparation» строку, совпадающую с pattern,
        и возвращает значение после двоеточия.

        Поддерживает два формата разметки на сайте:
          - <strong>Temps de préparation : 5 minutes</strong><ul>…</ul>
          - <strong>Temps de préparation :</strong> 15 minutes
        """
        elements = self._get_section_after_heading(
            re.compile(r"temps|dur[eé]e", re.IGNORECASE)
        )

        for el in elements:
            if el.name not in ("ul", "ol"):
                continue
            for li in el.find_all("li", recursive=False):
                # Предпочитаем текст из <strong> — он содержит метку (+иногда значение)
                strong = li.find("strong")
                if not strong:
                    continue

                label_text = strong.get_text(strip=True)
                if not pattern.search(label_text):
                    continue

                # Вариант 1: значение внутри <strong> (например «Temps : 5 minutes»)
                if ":" in label_text:
                    after_colon = label_text.split(":", 1)[1].strip()
                    if after_colon:
                        return self.clean_text(after_colon)

                # Вариант 2: значение находится в текстовом узле после <strong>
                value_parts = []
                for sibling in strong.next_siblings:
                    if hasattr(sibling, "name"):
                        # Останавливаемся на вложенном списке (описание шага)
                        if sibling.name in ("ul", "ol"):
                            break
                        value_parts.append(sibling.get_text(strip=True))
                    else:
                        value_parts.append(str(sibling).strip())

                value = " ".join(p for p in value_parts if p).strip()
                # Убираем ведущее двоеточие (в некоторых страницах «: 15 minutes»)
                value = re.sub(r"^[:\s]+", "", value).strip()
                if value:
                    return self.clean_text(value)

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки."""
        return self._extract_time_value(
            re.compile(r"temps\s+de\s+pr[eé]p", re.IGNORECASE)
        )

    def extract_cook_time(self) -> Optional[str]:
        """Время готовки."""
        return self._extract_time_value(
            re.compile(r"temps\s+de\s+cuis", re.IGNORECASE)
        )

    def extract_total_time(self) -> Optional[str]:
        """Общее время приготовления."""
        return self._extract_time_value(
            re.compile(r"dur[eé]e\s+totale|temps\s+total", re.IGNORECASE)
        )

    def extract_notes(self) -> Optional[str]:
        """Извлечение советов/заметок из секции «Conseils»."""
        elements = self._get_section_after_heading(
            re.compile(r"conseil", re.IGNORECASE)
        )

        if not elements:
            return None

        notes_parts = []

        for el in elements:
            if el.name in ("ol", "ul"):
                for li in el.find_all("li", recursive=False):
                    text = self.clean_text(li.get_text(separator=" "))
                    if text:
                        notes_parts.append(text)
            elif el.name == "p":
                text = self.clean_text(el.get_text(separator=" "))
                if text:
                    notes_parts.append(text)

        return " ".join(notes_parts) if notes_parts else None

    def extract_tags(self) -> Optional[str]:
        """
        Тегов на recetteriche.com нет — возвращаем None.
        """
        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Извлечение URL изображений рецепта из тега <img> внутри статьи.
        Исключаются логотипы и аватары автора.
        """
        article = self._get_article()
        if not article:
            return None

        urls = []
        seen: set[str] = set()

        for img in article.find_all("img"):
            src = img.get("src", "")
            # Берём только изображения с домена uploads (контентные)
            if not src or "wp-content/uploads" not in src:
                continue
            # Исключаем логотип и аватар автора (небольшие картинки в sidebar/header)
            img_classes = img.get("class", [])
            if "is-logo-image" in img_classes or "header-image" in img_classes:
                continue
            # Исключаем изображения автора по размеру/классу
            if "avatar" in " ".join(img_classes).lower():
                continue
            if src not in seen:
                seen.add(src)
                urls.append(src)

        return ",".join(urls) if urls else None

    # ----------------------------------------------------------------- main API

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта.
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
    """Точка входа для обработки директории с HTML-файлами recetteriche.com."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "recetteriche_com")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(RecetteRicheExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python recetteriche_com.py")


if __name__ == "__main__":
    main()
