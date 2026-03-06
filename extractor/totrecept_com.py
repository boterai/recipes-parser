"""
Экстрактор данных рецептов для сайта totrecept.com
"""

import logging
import re
import json
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class TotreceptComExtractor(BaseRecipeExtractor):
    """Экстрактор для totrecept.com"""

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _get_recipe_div(self):
        """Возвращает корневой div с itemtype=http://schema.org/Recipe."""
        return self.soup.find(attrs={"itemtype": "http://schema.org/Recipe"})

    def _get_content_div(self):
        """Возвращает div.s-post-content из recipe div."""
        recipe_div = self._get_recipe_div()
        if recipe_div is None:
            logger.warning("Recipe microdata div not found in %s", self.html_path)
            return None
        return recipe_div.find("div", class_="s-post-content")

    def _is_cooking_bl_layout(self) -> bool:
        """True, если страница использует layout с div.cooking-bl для шагов."""
        content = self._get_content_div()
        if content is None:
            return False
        return bool(content.find("div", class_="cooking-bl"))

    # ------------------------------------------------------------------ #
    # Field extractors
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда."""
        recipe_div = self._get_recipe_div()
        if recipe_div is None:
            return None
        try:
            h1 = recipe_div.find("h1", itemprop="headline")
            if h1:
                return self.clean_text(h1.get_text())
            # Fallback: любой h1 в recipe div
            h1 = recipe_div.find("h1")
            if h1:
                return self.clean_text(h1.get_text())
        except Exception as exc:
            logger.warning("extract_dish_name error: %s", exc)
        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение краткого описания рецепта."""
        content = self._get_content_div()
        if content is None:
            return None
        try:
            if self._is_cooking_bl_layout():
                # Layout 1: описание в div.article-text
                article_text = content.find("div", class_="article-text")
                if article_text:
                    paragraphs = [
                        self.clean_text(p.get_text())
                        for p in article_text.find_all("p")
                        if p.get_text(strip=True)
                    ]
                    text = " ".join(paragraphs)
                    return text if text else None
            else:
                # Layout 2 (ringredients): описание в первом безымянном div
                first_div = content.find("div", class_=None)
                if first_div:
                    # Ищем span с текстом описания (первый не пустой span без itemprop)
                    for span in first_div.find_all("span", recursive=False):
                        text = self.clean_text(span.get_text())
                        if text and "totrecept" not in text.lower():
                            return text
                    # Если span не нашли — берем текстовые узлы напрямую
                    texts = []
                    for child in first_div.children:
                        if hasattr(child, "get_text"):
                            t = self.clean_text(child.get_text())
                            if t and "totrecept" not in t.lower() and "Время" not in t:
                                texts.append(t)
                        elif str(child).strip():
                            t = self.clean_text(str(child))
                            if t and "totrecept" not in t.lower():
                                texts.append(t)
                    text = " ".join(texts)
                    return text if text else None
        except Exception as exc:
            logger.warning("extract_description error: %s", exc)
        return None

    # ------------------------------------------------------------------ #

    def _parse_ingredient_ru(self, li_or_div: "Union[Any, Any]") -> Optional[Dict[str, Any]]:
        """
        Парсит элемент списка ингредиентов в словарь {name, amount, unit}.

        Args:
            li_or_div: BeautifulSoup Tag — элемент <li> или <div>.

        Поддерживает два формата:
          - <li><a>Молоко</a>— 400 мл</li>
          - <li><span><a><span>Баклажан</span></a> — <span>1 кг</span></span></li>
          - <div>Мука<span>—</span><span>600  г</span></div>
        """
        try:
            tag_name = getattr(li_or_div, "name", None)

            if tag_name == "li":
                # --- Format 1: ul.ul-nice > li ---
                # Название — из первой <a>-ссылки (рекурсивный поиск)
                link = li_or_div.find("a")
                if link:
                    name = link.get_text(strip=True)
                else:
                    name = ""

                # Убираем комментарии в скобках из имени
                name = re.sub(r"\([^)]*\)", "", name).strip()

                # Получаем полный текст li и убираем из него имя, чтобы получить tail
                full_text = li_or_div.get_text(separator=" ", strip=True)
                # Убираем все тексты ссылок из полного текста
                links = li_or_div.find_all("a")
                for a in links:
                    full_text = full_text.replace(a.get_text(strip=True), "", 1)
                # Убираем разделитель «—» и комментарии в скобках
                full_text = re.sub(r"\([^)]*\)", "", full_text)
                tail = re.sub(r"^[\s/—–\-]+", "", full_text).strip()
                tail = re.sub(r"^[\s—–\-]+", "", tail).strip()

                amount, unit = self._split_amount_unit(tail)
                if not name:
                    return None
                return {"name": name, "amount": amount, "unit": unit}

            elif tag_name == "div":
                # --- Format 2: div.ringredients > div ---
                # Структура: "Мука<span>—</span><span>600  г</span>"
                full_text = li_or_div.get_text(separator=" ", strip=True)
                # Убираем разделитель «—»
                full_text = re.sub(r"\s*—\s*", "—", full_text)
                if "—" not in full_text:
                    return None
                parts = full_text.split("—", 1)
                name = parts[0].strip()
                rest = parts[1].strip() if len(parts) > 1 else ""
                amount, unit = self._split_amount_unit(rest)
                if not name:
                    return None
                return {"name": name, "amount": amount, "unit": unit}

        except Exception as exc:
            logger.warning("_parse_ingredient_ru error: %s", exc)
        return None

    @staticmethod
    def _to_number(s: str):
        """
        Преобразует строковое представление числа/дроби в int или float.
        Примеры: '400' -> 400, '0.5' -> 0.5, '1/2' -> 0.5, '1 1/2' -> 1.5
        Если не удалось — возвращает строку как есть.
        """
        s = s.strip()
        try:
            # Попытка смешанного формата «1 1/2»
            parts = s.split()
            total = 0.0
            for part in parts:
                if "/" in part:
                    num, denom = part.split("/", 1)
                    total += float(num) / float(denom)
                else:
                    total += float(part.replace(",", "."))
            # Возвращаем int если число целое
            return int(total) if total == int(total) else total
        except (ValueError, ZeroDivisionError):
            return s

    def _split_amount_unit(self, text: str):
        """
        Разбивает строку «400 мл» или «по вкусу» на (amount, unit).

        Returns:
            (amount, unit) — оба могут быть None
        """
        text = self.clean_text(text)
        if not text:
            return None, None

        # Специальный случай: «по вкусу», «по желанию» и т.п. — нет чёткого количества
        if re.match(r"^по\s+\w+", text, re.IGNORECASE):
            return None, text

        # Паттерн: число (целое / дробь «1/2» / смешанная «1 1/2» / десятичная) + единица
        match = re.match(
            r"^(\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?)\s*(.*)$",
            text,
            re.IGNORECASE,
        )
        if match:
            amount_str = match.group(1).strip()
            unit_str = match.group(2).strip() if match.group(2) else None
            amount = self._to_number(amount_str) if amount_str else None
            return amount, unit_str or None

        # Если всё не распознано — возвращаем как amount без unit
        return text, None

    # ------------------------------------------------------------------ #

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате JSON-строки."""
        content = self._get_content_div()
        if content is None:
            return None
        ingredients: List[Dict[str, Any]] = []
        try:
            if self._is_cooking_bl_layout():
                # Layout 1: ul.ul-nice > li
                for ul in content.find_all("ul", class_="ul-nice"):
                    for li in ul.find_all("li"):
                        parsed = self._parse_ingredient_ru(li)
                        if parsed:
                            ingredients.append(parsed)
            else:
                # Layout 2: div.ringredients > div (пропускаем заголовок «Ингредиенты:»)
                ringredients = content.find("div", class_="ringredients")
                if ringredients:
                    for div in ringredients.find_all("div", recursive=False):
                        text = div.get_text(strip=True)
                        # Пропускаем заголовок
                        if text in ("Ингредиенты:", "Ингредиенты") or "—" not in text:
                            continue
                        parsed = self._parse_ingredient_ru(div)
                        if parsed:
                            ingredients.append(parsed)
        except Exception as exc:
            logger.warning("extract_ingredients error: %s", exc)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    # ------------------------------------------------------------------ #

    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления."""
        content = self._get_content_div()
        if content is None:
            return None
        steps: List[str] = []
        try:
            if self._is_cooking_bl_layout():
                # Layout 1: div.cooking-bl — каждый блок это шаг
                for bl in content.find_all("div", class_="cooking-bl"):
                    # Текст шага — в div > p внутри cooking-bl (не в <a> ссылках)
                    inner_divs = bl.find_all("div", recursive=False)
                    step_text_parts: List[str] = []
                    for inner in inner_divs:
                        for p in inner.find_all("p"):
                            t = self.clean_text(p.get_text())
                            if t:
                                step_text_parts.append(t)
                    step_text = " ".join(step_text_parts).strip()

                    # Пропускаем пустые шаги
                    if not step_text:
                        continue

                    # Пропускаем рекламные вставки (содержат типичные ключевые слова)
                    if re.search(r"Ингредиенты для|Рецепт «", step_text):
                        continue

                    steps.append(step_text)

                # Нумеруем шаги, если они не пронумерованы
                if steps and not re.match(r"^\d+\.", steps[0]):
                    steps = [f"{i}. {s}" for i, s in enumerate(steps, 1)]

            else:
                # Layout 2: div.rtext > p (нумерованные абзацы)
                rtext = content.find("div", class_="rtext")
                if rtext:
                    for p in rtext.find_all("p"):
                        t = self.clean_text(p.get_text())
                        # Пропускаем «Приятного аппетита!» и пустые строки
                        if not t:
                            continue
                        steps.append(t)
                    # Последний абзац не является нумерованным шагом —
                    # это завершающая ремарка (типа «Приятного аппетита!»),
                    # которую extract_notes() вернёт отдельно.
                    if steps and not re.match(r"^\d+\.", steps[-1]):
                        steps.pop()

        except Exception as exc:
            logger.warning("extract_instructions error: %s", exc)

        return " ".join(steps) if steps else None

    # ------------------------------------------------------------------ #

    def extract_notes(self) -> Optional[str]:
        """Извлечение дополнительных заметок к рецепту."""
        content = self._get_content_div()
        if content is None:
            return None
        try:
            if self._is_cooking_bl_layout():
                # Layout 1: последний безымянный div после всех cooking-bl блоков
                first_inner = content.find("div", class_=None)
                if first_inner is None:
                    return None
                cooking_bls = first_inner.find_all("div", class_="cooking-bl")
                if not cooking_bls:
                    return None
                last_bl = cooking_bls[-1]
                # Ищем следующий безымянный div
                current = last_bl.next_sibling
                while current is not None:
                    if (
                        hasattr(current, "name")
                        and current.name == "div"
                        and not current.get("class")
                    ):
                        text = self.clean_text(current.get_text())
                        if text:
                            return text
                    current = current.next_sibling
            else:
                # Layout 2: последний p в div.rtext («Приятного аппетита!» и т.п.)
                rtext = content.find("div", class_="rtext")
                if rtext:
                    paragraphs = [
                        p for p in rtext.find_all("p") if p.get_text(strip=True)
                    ]
                    if paragraphs:
                        last_p = paragraphs[-1]
                        t = self.clean_text(last_p.get_text())
                        # Возвращаем только если это не нумерованный шаг
                        if t and not re.match(r"^\d+\.", t):
                            return t
        except Exception as exc:
            logger.warning("extract_notes error: %s", exc)
        return None

    # ------------------------------------------------------------------ #

    def _extract_time_from_text(self, label: str) -> Optional[str]:
        """
        Ищет время приготовления по метке (например, «Время приготовления»).
        Возвращает строку вроде «90 минут» или «1 час».
        """
        content = self._get_content_div()
        if content is None:
            return None
        try:
            # Layout 1: <p><strong>Время приготовления:</strong>90 минут</p>
            for strong in content.find_all("strong"):
                if label in strong.get_text():
                    p = strong.find_parent("p")
                    if p:
                        text = p.get_text(separator=" ", strip=True)
                        # Убираем метку
                        text = re.sub(re.escape(label) + r":?\s*", "", text).strip()
                        if text:
                            return text
            # Layout 2: первый div содержит span с меткой и вложенным span со значением
            first_div = content.find("div", class_=None)
            if first_div:
                for span in first_div.find_all("span"):
                    if label in span.get_text():
                        # Вложенный span содержит значение
                        inner = span.find("span")
                        if inner:
                            return self.clean_text(inner.get_text())
                        # Иначе — всё текстовое содержимое span минус метку
                        text = span.get_text(separator=" ", strip=True)
                        text = re.sub(re.escape(label) + r":?\s*", "", text).strip()
                        if text:
                            return text
        except Exception as exc:
            logger.warning("_extract_time_from_text error: %s", exc)
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени приготовления."""
        return self._extract_time_from_text("Время приготовления")

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки (не представлено в HTML явно)."""
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки (не представлено в HTML явно)."""
        return None

    # ------------------------------------------------------------------ #

    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта."""
        recipe_div = self._get_recipe_div()
        if recipe_div is None:
            return None
        try:
            tags_div = recipe_div.find("div", class_="bb-tags")
            if tags_div:
                # Ссылка с rel="category tag" — это категория (не просто тег)
                cat_link = tags_div.find(
                    "a", rel=lambda r: r and "category" in r and "tag" in r
                )
                if cat_link:
                    text = self.clean_text(cat_link.get_text())
                    return text if text else None
        except Exception as exc:
            logger.warning("extract_category error: %s", exc)
        return None

    # ------------------------------------------------------------------ #

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта (строка через «, »)."""
        recipe_div = self._get_recipe_div()
        if recipe_div is None:
            return None
        try:
            tags_div = recipe_div.find("div", class_="bb-tags")
            if not tags_div:
                return None
            seen = set()
            tags: List[str] = []
            for a in tags_div.find_all("a"):
                rel = a.get("rel", [])
                text = self.clean_text(a.get_text()).strip()
                if not text:
                    continue
                # Пропускаем ссылки-категории (только rel="category tag") и
                # ссылки-источники вроде «povarenok.ru», «kedem.ru»
                if re.search(r"\.[a-z]{2,}$", text, re.IGNORECASE):
                    continue
                if text.lower() in seen:
                    continue
                seen.add(text.lower())
                tags.append(text)
            return ", ".join(tags) if tags else None
        except Exception as exc:
            logger.warning("extract_tags error: %s", exc)
        return None

    # ------------------------------------------------------------------ #

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта (через запятую без пробелов)."""
        urls: List[str] = []
        seen: set = set()

        def add(url: str):
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        try:
            # 1. og:image — главное изображение
            og = self.soup.find("meta", property="og:image")
            if og and og.get("content"):
                add(og["content"])

            # 2. Изображения внутри recipe div
            recipe_div = self._get_recipe_div()
            if recipe_div:
                # Micro-data image
                meta_img = recipe_div.find("meta", itemprop="url")
                if meta_img and meta_img.get("content"):
                    add(meta_img["content"])

                content = recipe_div.find("div", class_="s-post-content")
                if content:
                    for img in content.find_all("img"):
                        src = img.get("src", "")
                        # Берём только изображения с домена totrecept.com
                        try:
                            hostname = urlparse(src).hostname or ""
                        except Exception:
                            hostname = ""
                        if hostname == "totrecept.com" or hostname.endswith(".totrecept.com"):
                            add(src)
        except Exception as exc:
            logger.warning("extract_image_urls error: %s", exc)

        return ",".join(urls) if urls else None

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта."""
        try:
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
        except Exception as exc:
            logger.error("extract_all failed for %s: %s", self.html_path, exc)
            dish_name = description = ingredients = instructions = category = None
            prep_time = cook_time = total_time = notes = tags = image_urls = None

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
    """Обработка HTML-файлов из preprocessed/totrecept_com."""
    recipes_dir = Path(__file__).parent.parent / "preprocessed" / "totrecept_com"
    if recipes_dir.exists() and recipes_dir.is_dir():
        process_directory(TotreceptComExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")


if __name__ == "__main__":
    main()
