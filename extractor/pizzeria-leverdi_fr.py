"""
Экстрактор данных рецептов для сайта pizzeria-leverdi.fr

WordPress (Astra theme), без плагина карточки рецепта.
Контент в div.entry-content со структурой h2/h3/p/ul/ol.
JSON-LD содержит только Article/WebPage/ImageObject (без Recipe schema).
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

# --------------------------------------------------------------------------- #
# Французские единицы измерения (расширенный список)
# --------------------------------------------------------------------------- #
_FR_UNITS = (
    r"cuillères?\s+à\s+soupe|c\.?\s*à\s*s\.?|cas"
    r"|cuillères?\s+à\s+café|c\.?\s*à\s*c\.?|cac"
    r"|cuillère?|c\.?\s*à\s*s\.?|tbsp|tsp"
    r"|kilogrammes?|kilos?|kg"
    r"|grammes?|g(?=\s|$|de\b)"
    r"|litres?|l(?=\s|$|de\b)"
    r"|centilitres?|cl"
    r"|décilitres?|dl"
    r"|millilitres?|ml"
    r"|tasses?|cup"
    r"|pincées?|pinch"
    r"|gousses?"
    r"|tranches?"
    r"|feuilles?"
    r"|brins?|bouquets?"
    r"|boîtes?|bocaux?"
    r"|sachets?"
    r"|paquets?"
    r"|morceaux?"
    r"|filets?"
    r"|unités?"
    r"|pièces?"
)

_FR_UNIT_RE = re.compile(
    r"^([\d]+(?:[.,]\d+)?(?:\s*/\s*[\d]+)?(?:\s*[-à]\s*[\d]+)?)"   # amount
    r"\s*(" + _FR_UNITS + r")"                                        # unit
    r"(?:\s+de\s+|\s+d['\u2019]\s*|\s+du\s+|\s+de\s+la\s+|\s+des\s+|\s+)?"  # de / d' / du ...
    r"(.+)$",
    re.IGNORECASE,
)

# Простые числа без единицы (счётные предметы)
_COUNT_RE = re.compile(
    r"^([\d]+(?:[.,]\d+)?)"
    r"(?:\s+de\s+|\s+d['\u2019]\s*|\s+du\s+|\s+de\s+la\s+|\s+des\s+|\s+)"
    r"(.+)$",
    re.IGNORECASE,
)

# Ключевые слова H2 для разных секций
_INGREDIENT_H2 = re.compile(r"ingr[eé]dient", re.IGNORECASE)
_PREP_H2 = re.compile(
    r"pr[eé]parat|[eé]tape|assemblag|cuisson|recette|r[eé]alisation",
    re.IGNORECASE,
)
_NOTES_H2 = re.compile(
    r"conseil|astuce|accord|suggestion|important|secret|variante",
    re.IGNORECASE,
)
_FAQ_H2 = re.compile(r"foire|faq|question|r[eé]ponse", re.IGNORECASE)
_DETAILED_H3 = re.compile(r"[eé]tapes?\s+d[eé]taill", re.IGNORECASE)

# Теги/блоки, которые нужно пропустить при поиске изображений
_SKIP_IMG_HOSTS = {"gravatar.com"}


class PizzeriaLeverdiFrExtractor(BaseRecipeExtractor):
    """Экстрактор для pizzeria-leverdi.fr (WordPress Astra, без плагина рецептов)."""

    # ------------------------------------------------------------------ #
    # Вспомогательные методы
    # ------------------------------------------------------------------ #

    def _get_entry_content(self):
        """Возвращает блок div.entry-content."""
        return self.soup.find("div", class_="entry-content")

    def _get_json_ld_graph(self) -> list:
        """Возвращает элементы @graph из первого JSON-LD скрипта."""
        for script in self.soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, dict) and "@graph" in data:
                    return data["@graph"]
            except (json.JSONDecodeError, TypeError):
                continue
        return []

    def _get_article_ld(self) -> Optional[dict]:
        """Возвращает объект Article из JSON-LD @graph."""
        for item in self._get_json_ld_graph():
            if isinstance(item, dict) and item.get("@type") == "Article":
                return item
        return None

    def _get_image_object_urls(self) -> List[str]:
        """Возвращает URL всех ImageObject из @graph."""
        urls: List[str] = []
        for item in self._get_json_ld_graph():
            if isinstance(item, dict) and item.get("@type") == "ImageObject":
                url = item.get("url") or item.get("contentUrl")
                if url:
                    urls.append(url)
        return urls

    # ------------------------------------------------------------------ #
    # Парсинг ингредиентов
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_ingredient(text: str) -> dict:
        """
        Разбирает строку ингредиента во французском стиле.

        Примеры:
          "300g de pâtes (spaghetti ou linguine)" → {name, amount, unit}
          "2 gousses d'ail, hachées"             → {name, amount, unit}
          "Guanciale: joue de porc salée"         → {name, amount=None, unit=None}
          "une pincée de sel"                     → {name, amount, unit}
        """
        # Нормализация: типографские апострофы → ASCII
        text = text.replace("\u2019", "'").replace("\u2018", "'")

        # Если строка содержит ":" — берём только имя до двоеточия
        if ":" in text:
            name = text.split(":")[0].strip()
            return {"name": name, "amount": None, "unit": None}

        # "une / un" → "1"
        t = re.sub(r"^une?\s+", "1 ", text.strip(), flags=re.IGNORECASE)

        m = _FR_UNIT_RE.match(t)
        if m:
            amount_str, unit_str, name = m.group(1), m.group(2), m.group(3)
            amount_str = amount_str.strip()
            unit_str = unit_str.strip()
            name = name.strip().rstrip(",;")
            return {
                "name": name,
                "amount": amount_str,
                "unit": unit_str,
            }

        m = _COUNT_RE.match(t)
        if m:
            amount_str, name = m.group(1).strip(), m.group(2).strip()
            name = name.rstrip(",;")
            return {
                "name": name,
                "amount": amount_str,
                "unit": None,
            }

        # Нет числа — всё имя
        name = text.strip().rstrip(",;")
        return {"name": name, "amount": None, "unit": None}

    # ------------------------------------------------------------------ #
    # Публичные методы извлечения
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлекает название блюда из h1.entry-title."""
        try:
            h1 = self.soup.find("h1", class_="entry-title")
            if not h1:
                h1 = self.soup.find("h1")
            if h1:
                title = self.clean_text(h1.get_text())
                # Убираем субтитул после " : "
                if " : " in title:
                    title = title.split(" : ")[0].strip()
                return title
        except Exception as e:
            logger.warning("Ошибка при извлечении dish_name: %s", e)
        return None

    def extract_description(self) -> Optional[str]:
        """Извлекает вводный абзац перед первым H2."""
        try:
            content = self._get_entry_content()
            if not content:
                # Fallback: og:description
                og = self.soup.find("meta", property="og:description")
                if og and og.get("content"):
                    return self.clean_text(og["content"])
                return None

            for elem in content.children:
                if not hasattr(elem, "name"):
                    continue
                if elem.name in ("h2", "h3"):
                    break
                if elem.name == "p":
                    text = self.clean_text(elem.get_text())
                    if text and len(text) > 20:
                        return text
        except Exception as e:
            logger.warning("Ошибка при извлечении description: %s", e)
        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Ищет первый UL после H2 с ключевым словом «ingrédient»
        и разбирает его элементы в структурированный формат.
        """
        try:
            content = self._get_entry_content()
            if not content:
                return None

            # Находим H2 с «ingrédient»
            ingredient_h2 = None
            for h2 in content.find_all("h2"):
                if _INGREDIENT_H2.search(h2.get_text()):
                    ingredient_h2 = h2
                    break

            if ingredient_h2 is None:
                logger.debug("H2 с 'ingrédient' не найден")
                return None

            # Ищем первый UL, который является непосредственным потомком
            # entry-content и следует за ingredient_h2 (до следующего H2)
            target_ul = None
            for sibling in ingredient_h2.find_next_siblings():
                if sibling.name == "h2":
                    break
                if sibling.name in ("ul", "ol"):
                    target_ul = sibling
                    break
                # Не заходим в H3-подсекции — ищем только на уровне H2
                if sibling.name == "h3":
                    break

            if target_ul is None:
                logger.debug("UL/OL после H2-ингредиентов не найден")
                return None

            ingredients = []
            for li in target_ul.find_all("li", recursive=False):
                text = self.clean_text(li.get_text(separator=" "))
                if not text:
                    continue
                parsed = self._parse_ingredient(text)
                if parsed and parsed.get("name"):
                    ingredients.append(parsed)

            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)
        except Exception as e:
            logger.warning("Ошибка при извлечении ingredients: %s", e)
        return None

    def extract_instructions(self) -> Optional[str]:
        """
        Извлекает шаги приготовления.

        Порядок поиска:
        1. H3 «Étapes détaillées» → первый UL/OL после него.
        2. H2 с ключевыми словами подготовки → все OL (затем UL) в секции.
        3. Все OL в entry-content (исключая FAQ-секции).
        """
        try:
            content = self._get_entry_content()
            if not content:
                return None

            steps: List[str] = []

            # --- Вариант 1: H3 "étapes détaillées" ---
            for h3 in content.find_all("h3"):
                if _DETAILED_H3.search(h3.get_text()):
                    for sibling in h3.find_next_siblings():
                        if sibling.name in ("h2", "h3"):
                            break
                        if sibling.name in ("ul", "ol"):
                            for li in sibling.find_all("li"):
                                text = self.clean_text(li.get_text(separator=" "))
                                if text:
                                    steps.append(text)
                            break
                    if steps:
                        break

            if steps:
                return " ".join(steps)

            # --- Вариант 2: H2 с ключевыми словами приготовления ---
            prep_h2_nodes = []
            for h2 in content.find_all("h2"):
                if _PREP_H2.search(h2.get_text()) and not _FAQ_H2.search(h2.get_text()):
                    prep_h2_nodes.append(h2)

            if prep_h2_nodes:
                # Собираем все OL из этих секций; если OL нет — берём UL
                for h2 in prep_h2_nodes:
                    for sibling in h2.find_next_siblings():
                        if sibling.name == "h2":
                            break
                        if sibling.name == "ol":
                            for li in sibling.find_all("li"):
                                text = self.clean_text(li.get_text(separator=" "))
                                if text:
                                    steps.append(text)

                # Если OL не дали результата, берём UL из первой prep-секции
                if not steps:
                    h2 = prep_h2_nodes[0]
                    for sibling in h2.find_next_siblings():
                        if sibling.name == "h2":
                            break
                        if sibling.name == "ul":
                            for li in sibling.find_all("li"):
                                text = self.clean_text(li.get_text(separator=" "))
                                if text:
                                    steps.append(text)
                            break

                if steps:
                    return " ".join(steps)

            # --- Вариант 3: первый OL в контенте ---
            first_ol = content.find("ol")
            if first_ol:
                for li in first_ol.find_all("li"):
                    text = self.clean_text(li.get_text(separator=" "))
                    if text:
                        steps.append(text)
                return " ".join(steps) if steps else None

        except Exception as e:
            logger.warning("Ошибка при извлечении instructions: %s", e)
        return None

    def extract_category(self) -> Optional[str]:
        """
        Извлекает категорию из JSON-LD Article.articleSection.
        Fallback: CSS-класс «category-*» на теге <article>.
        """
        try:
            article_ld = self._get_article_ld()
            if article_ld:
                section = article_ld.get("articleSection")
                if isinstance(section, list) and section:
                    return self.clean_text(section[0])
                if isinstance(section, str) and section:
                    return self.clean_text(section)

            # Fallback: CSS-класс статьи
            article_tag = self.soup.find("article")
            if article_tag:
                classes = article_tag.get("class", [])
                for cls in classes:
                    m = re.match(r"^category-(.+)$", cls)
                    if m:
                        return m.group(1).capitalize()
        except Exception as e:
            logger.warning("Ошибка при извлечении category: %s", e)
        return None

    def _extract_time_from_section(self, keyword_re: re.Pattern) -> Optional[str]:
        """
        Ищет упоминание времени в тексте секции H2/H3, имя которой
        совпадает с keyword_re. Возвращает первое найденное значение.
        """
        content = self._get_entry_content()
        if not content:
            return None

        time_re = re.compile(
            r"(\d+(?:\s*[-àa]\s*\d+)?\s*(?:heure|minute|min|h)s?)",
            re.IGNORECASE,
        )

        for heading in content.find_all(["h2", "h3"]):
            if keyword_re.search(heading.get_text()):
                for sibling in heading.find_next_siblings():
                    if sibling.name in ("h2", "h3"):
                        break
                    text = sibling.get_text(" ")
                    m = time_re.search(text)
                    if m:
                        return self.clean_text(m.group(1))
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлекает время подготовки (marinade / repos)."""
        try:
            content = self._get_entry_content()
            if not content:
                return None

            # Ищем «reposer/marinade pendant N minutes»
            text = content.get_text(" ")
            m = re.search(
                r"(?:reposer|marinade|mariner)\s+(?:pendant\s+)?(\d+(?:\s*[-à]\s*\d+)?\s*(?:minute|heure|min|h)s?)",
                text,
                re.IGNORECASE,
            )
            if m:
                t = self.clean_text(m.group(1))
                # нормализуем: "30 minutes" → "30 minutes"
                if not re.search(r"(?:minute|heure|min|h)s?", t, re.I):
                    t += " minutes"
                return t
        except Exception as e:
            logger.warning("Ошибка при извлечении prep_time: %s", e)
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлекает время готовки (cuire/cuisson N minutes)."""
        try:
            content = self._get_entry_content()
            if not content:
                return None

            text = content.get_text(" ")
            m = re.search(
                r"(?:cuire|cuisez?|cuisson|faites?\s+cuire|cuirrez?)\b[^.]{0,60}?\b(\d+(?:\s*[-àa]\s*\d+)?\s*(?:minute|heure|min|h)s?)",
                text,
                re.IGNORECASE,
            )
            if m:
                t = self.clean_text(m.group(1))
                if not re.search(r"(?:minute|heure|min|h)s?", t, re.I):
                    t += " minutes"
                return t
        except Exception as e:
            logger.warning("Ошибка при извлечении cook_time: %s", e)
        return None

    def extract_total_time(self) -> Optional[str]:
        """Общее время — не представлено на страницах сайта."""
        return None

    def extract_notes(self) -> Optional[str]:
        """
        Собирает текст советов и рекомендаций из секций H2/H3
        с ключевыми словами «Conseils», «Astuces», «Accord» и т.д.
        """
        try:
            content = self._get_entry_content()
            if not content:
                return None

            notes_parts: List[str] = []

            for heading in content.find_all(["h2", "h3"]):
                heading_text = heading.get_text(strip=True)
                if not _NOTES_H2.search(heading_text):
                    continue
                if _FAQ_H2.search(heading_text):
                    continue

                for sibling in heading.find_next_siblings():
                    if sibling.name in ("h2", "h3"):
                        break
                    if sibling.name == "p":
                        text = self.clean_text(sibling.get_text())
                        if text and len(text) > 15:
                            notes_parts.append(text)

            if notes_parts:
                # Дедупликация с сохранением порядка
                seen: set = set()
                unique: List[str] = []
                for part in notes_parts:
                    if part not in seen:
                        seen.add(part)
                        unique.append(part)
                return " ".join(unique)
        except Exception as e:
            logger.warning("Ошибка при извлечении notes: %s", e)
        return None

    def extract_tags(self) -> Optional[str]:
        """
        Извлекает теги из Article.articleSection (JSON-LD).
        Fallback: CSS-классы category-* на <article>.
        """
        try:
            article_ld = self._get_article_ld()
            if article_ld:
                section = article_ld.get("articleSection")
                if isinstance(section, list) and section:
                    return ", ".join(self.clean_text(s) for s in section if s)
                if isinstance(section, str) and section:
                    return self.clean_text(section)

            article_tag = self.soup.find("article")
            if article_tag:
                cats = []
                for cls in article_tag.get("class", []):
                    m = re.match(r"^category-(.+)$", cls)
                    if m:
                        cats.append(m.group(1))
                if cats:
                    return ", ".join(cats)
        except Exception as e:
            logger.warning("Ошибка при извлечении tags: %s", e)
        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Собирает URL изображений:
        1. og:image (главное изображение)
        2. ImageObject из JSON-LD @graph
        """
        try:
            urls: List[str] = []

            og_image = self.soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                urls.append(og_image["content"])

            for url in self._get_image_object_urls():
                if url not in urls:
                    urls.append(url)

            # Убираем дубликаты и SVG-заглушки
            seen: set = set()
            unique: List[str] = []
            for url in urls:
                if url and url not in seen and not url.startswith("data:"):
                    seen.add(url)
                    unique.append(url)

            return ",".join(unique) if unique else None
        except Exception as e:
            logger.warning("Ошибка при извлечении image_urls: %s", e)
        return None

    # ------------------------------------------------------------------ #
    # Основной метод
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """Извлекает все данные рецепта и возвращает словарь."""
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_instructions(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags(),
        }


def main() -> None:
    """Точка входа: обрабатывает HTML-файлы в preprocessed/pizzeria-leverdi_fr."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "pizzeria-leverdi_fr")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(PizzeriaLeverdiFrExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python pizzeria-leverdi_fr.py")


if __name__ == "__main__":
    main()
