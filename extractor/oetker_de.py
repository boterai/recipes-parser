"""
Экстрактор данных рецептов для сайта oetker.de
"""

import html as html_module
import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class OetkerDeExtractor(BaseRecipeExtractor):
    """Экстрактор для oetker.de"""

    def __init__(self, html_path: str):
        super().__init__(html_path)
        self._next_data: Optional[dict] = self._parse_next_data()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_next_data(self) -> Optional[dict]:
        """Извлечение структурированных данных из тега <script id="__NEXT_DATA__">."""
        script = self.soup.find("script", id="__NEXT_DATA__")
        if not script or not script.string:
            return None
        try:
            data = json.loads(script.string)
            return (
                data.get("props", {})
                .get("pageProps", {})
                .get("recipe")
            )
        except (json.JSONDecodeError, AttributeError):
            logger.warning("Не удалось распарсить __NEXT_DATA__ в %s", self.html_path)
            return None

    @staticmethod
    def _strip_html(text: str) -> str:
        """Удаление HTML-тегов и декодирование HTML-сущностей из строки."""
        if not text:
            return text
        cleaned = BeautifulSoup(text, "lxml").get_text(separator=" ", strip=True)
        cleaned = html_module.unescape(cleaned)
        # Убираем пробелы перед знаками препинания (артефакты разбора HTML)
        cleaned = re.sub(r"\s+([.,;:!?])", r"\1", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @staticmethod
    def _parse_amount_unit(amount_unit_text: Optional[str]):
        """
        Разбивает строку вида "125 g", "etwa 1 Pck.", "½ Bund", "etwas"
        на кортеж (amount, unit).

        Возвращает (amount_str, unit_str) или (None, None).
        """
        if not amount_unit_text:
            return None, None

        text = amount_unit_text.strip()
        if not text:
            return None, None

        # Аббревиатуры единиц, которые выделяем в отдельное поле
        unit_abbrevs = (
            r"g|kg|mg|ml|l|cl|dl"
            r"|EL|TL|Pck\.|Stk\.|Pkg\.|Msp\."
            r"|gestr\.\s+TL|gestr\. TL"
        )
        pattern = re.compile(
            r"^(.*?)\s+(" + unit_abbrevs + r")$",
            re.IGNORECASE,
        )
        m = pattern.match(text)
        if m:
            amount = m.group(1).strip() or None
            unit = m.group(2).strip()
            return amount, unit

        # Единица не выделяется → всё в amount
        return text, None

    # ------------------------------------------------------------------
    # Field extractors
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда."""
        if self._next_data:
            title = self._next_data.get("Title")
            if title:
                return self.clean_text(title)

        # Запасной вариант — тег <h1 itemprop="name">
        h1 = self.soup.find("h1", itemprop="name") or self.soup.find("h1")
        if h1:
            return self.clean_text(h1.get_text())
        return None

    def extract_description(self) -> Optional[str]:
        """
        Извлечение краткого описания рецепта из ShortDescription
        с удалением маркетинговых CTA-фраз.
        """
        if self._next_data:
            short = self._next_data.get("ShortDescription", "") or ""
            if short:
                desc = self._clean_short_description(short)
                return self.clean_text(desc) if desc else None

        # Запасной вариант — первый <div itemprop="description">
        desc_el = self.soup.find(itemprop="description")
        if desc_el:
            text = desc_el.get_text(strip=True)
            return self.clean_text(self._clean_short_description(text)) or None
        return None

    @staticmethod
    def _clean_short_description(text: str) -> str:
        """Удаление типовых CTA-фраз из начала и конца описания."""
        # Начальная фраза вида "Entdecke dein neues Lieblings-X Rezept!"
        text = re.sub(
            r"^Entdecke dein neues Lieblings-[^!]+!\s*",
            "",
            text,
        )
        # Концевые CTA-фразы (без зависимости от порядка)
        trailing_patterns = [
            r"\s*Jetzt direkt \w+!$",
            r"\s*Probier es gleich aus!$",
            r"\s*–\s*jetzt ausprobieren!$",
            r"\s*Jetzt \w+ ausprobieren!$",
        ]
        for pat in trailing_patterns:
            text = re.sub(pat, "", text.rstrip())
        text = text.strip()
        # Добавляем точку в конце, если нет знака препинания
        if text and text[-1] not in ".!?":
            text += "."
        return text

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из IngredientsAndEquipmentBlocks (NEXT_DATA).
        Запасной вариант — HTML-элементы <div itemprop="ingredients">.
        """
        ingredients = []

        # Основной путь — структурированные данные из __NEXT_DATA__
        if self._next_data:
            blocks = self._next_data.get("IngredientsAndEquipmentBlocks", []) or []
            for block in blocks:
                for ing in block.get("Ingredients", []) or []:
                    name = ing.get("ArticleSummaryText")
                    if not name:
                        continue
                    name = self.clean_text(name)
                    amount_unit_text = ing.get("AmountAndUnitSummaryText")
                    amount, unit = self._parse_amount_unit(amount_unit_text)
                    ingredients.append(
                        {"name": name, "amount": amount, "unit": unit}
                    )

        # Запасной вариант — HTML-теги с itemprop="ingredients"
        if not ingredients:
            ingr_elements = self.soup.find_all(itemprop="ingredients")
            for el in ingr_elements:
                children = el.find_all("div", recursive=False)
                if len(children) >= 2:
                    amount_unit_text = children[0].get_text(strip=True) or None
                    name_text = children[1].get_text(strip=True)
                    name = self.clean_text(name_text)
                    if not name:
                        continue
                    amount, unit = self._parse_amount_unit(amount_unit_text)
                    ingredients.append(
                        {"name": name, "amount": amount, "unit": unit}
                    )

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления из ClassicInstruction.PreparationBlocks."""
        steps = []

        if self._next_data:
            ci = self._next_data.get("ClassicInstruction") or {}
            blocks = ci.get("PreparationBlocks", []) or []
            for block in blocks:
                if block.get("IsStep") and block.get("Description"):
                    desc = self._strip_html(block["Description"])
                    desc = self.clean_text(desc)
                    if desc:
                        steps.append(desc)

        # Запасной вариант — HTML-элементы
        if not steps:
            step_els = self.soup.find_all("p", class_="step-links")
            seen: set = set()
            for el in step_els:
                text = self.clean_text(el.get_text(separator=" ", strip=True))
                if text and text not in seen:
                    seen.add(text)
                    steps.append(text)

        if not steps:
            return None

        # Нумеруем шаги только если их больше одного
        if len(steps) > 1:
            return " ".join(f"{i + 1}. {step}" for i, step in enumerate(steps))
        return steps[0]

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда из MenuTypes."""
        if self._next_data:
            menu_types = self._next_data.get("MenuTypes", []) or []
            if menu_types:
                title = menu_types[0].get("Title")
                if title:
                    return self.clean_text(title)
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки из PreparationTimeInMinutes."""
        if self._next_data:
            minutes = self._next_data.get("PreparationTimeInMinutes")
            if minutes:
                return f"{minutes} minutes"

        # Запасной вариант — meta itemprop="totalTime"
        meta_time = self.soup.find(itemprop="totalTime")
        if meta_time:
            content = meta_time.get("content", "")
            if content:
                parsed = self._parse_iso_duration(content)
                if parsed:
                    return f"{parsed} minutes"
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Время приготовления (термообработки) — недоступно в структурированных данных."""
        return None

    def extract_total_time(self) -> Optional[str]:
        """
        Общее время: берётся из itemprop="totalTime" (ISO 8601),
        только если отличается от времени подготовки.
        """
        meta_time = self.soup.find(itemprop="totalTime")
        if not meta_time:
            return None
        content = meta_time.get("content", "")
        if not content:
            return None
        total_minutes = self._parse_iso_duration(content)
        if total_minutes is None:
            return None

        # Не возвращаем total_time, если оно совпадает с prep_time
        prep_minutes = (self._next_data or {}).get("PreparationTimeInMinutes")
        if prep_minutes is not None and int(total_minutes) == int(prep_minutes):
            return None

        return f"{total_minutes} minutes"

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[int]:
        """Конвертирует ISO 8601 duration (PT20M, PT1H30M) в минуты."""
        if not duration or not duration.upper().startswith("PT"):
            return None
        duration = duration[2:]
        hours = 0
        minutes = 0
        h_match = re.search(r"(\d+)H", duration, re.I)
        m_match = re.search(r"(\d+)M", duration, re.I)
        if h_match:
            hours = int(h_match.group(1))
        if m_match:
            minutes = int(m_match.group(1))
        total = hours * 60 + minutes
        return total if total > 0 else None

    def extract_notes(self) -> Optional[str]:
        """Извлечение советов/подсказок из ClassicInstruction.Tips."""
        notes: list[str] = []

        if self._next_data:
            ci = self._next_data.get("ClassicInstruction") or {}
            tips = ci.get("Tips", []) or []
            for tip in tips:
                text = tip.get("Text", "") or ""
                if text:
                    cleaned = self._strip_html(text)
                    cleaned = self.clean_text(cleaned)
                    if cleaned:
                        notes.append(cleaned)

        return " ".join(notes) if notes else None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из DietTypes (диетические характеристики рецепта)."""
        if self._next_data:
            diet_types = self._next_data.get("DietTypes", []) or []
            titles = [
                self.clean_text(dt["Title"])
                for dt in diet_types
                if dt.get("Title")
            ]
            return ", ".join(titles) if titles else None
        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из Images[].Formats[].Url."""
        urls: list[str] = []

        if self._next_data:
            images = self._next_data.get("Images", []) or []
            for img in images:
                formats = img.get("Formats", []) or []
                if formats:
                    url = formats[0].get("Url")
                    if url:
                        urls.append(url)

        # Запасной вариант — meta itemprop="image"
        if not urls:
            meta_img = self.soup.find("meta", itemprop="image")
            if meta_img:
                content = meta_img.get("content", "")
                if content and content.startswith("http"):
                    urls.append(content)

        return ",".join(urls) if urls else None

    # ------------------------------------------------------------------
    # Main extraction entry point
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с полями: dish_name, description, ingredients,
            instructions, category, prep_time, cook_time, total_time,
            notes, image_urls, tags.
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
    """Точка входа для обработки директории с HTML-страницами oetker.de."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "oetker_de")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(OetkerDeExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python oetker_de.py")


if __name__ == "__main__":
    main()
