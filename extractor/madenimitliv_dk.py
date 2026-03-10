"""
Экстрактор данных рецептов для сайта madenimitliv.dk
"""

import sys
import logging
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class MadenimitlivDkExtractor(BaseRecipeExtractor):
    """Экстрактор для madenimitliv.dk (WordPress + WPRM plugin)"""

    def _get_json_ld_data(self) -> dict:
        """
        Извлечение JSON-LD данных из страницы.

        Returns:
            Словарь с ключами 'recipe' и 'article', содержащими соответствующие
            JSON-LD объекты (или пустые dict, если не найдены).
        """
        result: dict = {}
        scripts = self.soup.find_all("script", type="application/ld+json")
        for script in scripts:
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                graph = data.get("@graph", [])
                if not isinstance(graph, list):
                    continue
                for item in graph:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get("@type", "")
                    if item_type == "Recipe" and "recipe" not in result:
                        result["recipe"] = item
                    elif item_type == "Article" and "article" not in result:
                        result["article"] = item
            except (json.JSONDecodeError, AttributeError, KeyError) as exc:
                logger.debug("Failed to parse JSON-LD block: %s", exc)
                continue
        return result

    def _parse_wprm_time_container(self, container) -> Optional[str]:
        """
        Разбирает WPRM-контейнер времени и возвращает строку вида
        «N timer M minutter» (на датском).

        Args:
            container: BeautifulSoup элемент контейнера времени.

        Returns:
            Строка с временем или None.
        """
        if container is None:
            return None

        hours_el = container.find(
            class_=lambda x: x and "wprm-recipe-details-hours" in x.split() if x else False
        )
        mins_el = container.find(
            class_=lambda x: x and "wprm-recipe-details-minutes" in x.split() if x else False
        )

        hrs: Optional[str] = None
        mins: Optional[str] = None

        if hours_el:
            # Берём только прямой текстовый узел, игнорируя sr-only
            direct_text = hours_el.find(string=True, recursive=False)
            if direct_text:
                hrs = direct_text.strip()

        if mins_el:
            direct_text = mins_el.find(string=True, recursive=False)
            if direct_text:
                mins = direct_text.strip()

        parts = []
        if hrs and hrs.isdigit() and int(hrs) > 0:
            parts.append(f"{hrs} timer")
        if mins and mins.isdigit() and int(mins) > 0:
            parts.append(f"{mins} minutter")

        return " ".join(parts) if parts else None

    def _format_iso_duration(self, duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration (PT380M, PT1H30M) в датскую строку
        вида «N timer M minutter».

        Args:
            duration: строка ISO 8601 вида «PT20M» или «PT1H30M».

        Returns:
            Читаемая строка или None.
        """
        if not duration or not duration.startswith("PT"):
            return None

        body = duration[2:]
        hours = 0
        minutes = 0

        hour_match = re.search(r"(\d+)H", body)
        if hour_match:
            hours = int(hour_match.group(1))

        min_match = re.search(r"(\d+)M", body)
        if min_match:
            minutes = int(min_match.group(1))

        # Нормализуем лишние минуты в часы
        hours += minutes // 60
        minutes = minutes % 60

        parts = []
        if hours > 0:
            parts.append(f"{hours} timer")
        if minutes > 0:
            parts.append(f"{minutes} minutter")

        return " ".join(parts) if parts else None

    # ------------------------------------------------------------------
    # Основные методы извлечения
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """
        Извлечение названия блюда.

        Приоритет: h1 страницы (обрезается после « – »)
        → WPRM-название → JSON-LD Recipe.name → og:title.
        """
        # 1. h1 страницы — самое естественное название
        h1 = self.soup.find("h1")
        if h1:
            title = self.clean_text(h1.get_text())
            if title:
                # Убираем суффикс «– bedste opskrift …» и аналогичные
                title = re.split(r"\s+[–—-]\s+", title)[0].strip()
                # Убираем завершающую точку
                title = title.rstrip(".")
                if title:
                    return title

        # 2. WPRM-имя рецепта
        name_el = self.soup.find(class_="wprm-recipe-name")
        if name_el:
            return self.clean_text(name_el.get_text()) or None

        # 3. JSON-LD Recipe.name
        json_ld = self._get_json_ld_data()
        recipe_name = json_ld.get("recipe", {}).get("name")
        if recipe_name:
            return self.clean_text(recipe_name) or None

        # 4. og:title (удаляем суффикс сайта)
        og_title = self.soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"]
            title = re.sub(r"\s*[|I]\s*Madenimitliv.*$", "", title, flags=re.IGNORECASE)
            return self.clean_text(title) or None

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта из вводного абзаца поста."""
        # 1. Первый абзац в .single_post_content (тело статьи)
        content_div = self.soup.find(class_="single_post_content")
        if content_div:
            first_p = content_div.find("p")
            if first_p:
                text = self.clean_text(first_p.get_text())
                if text:
                    return text

        # 2. og:description
        og_desc = self.soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            return self.clean_text(og_desc["content"]) or None

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из WPRM-структуры HTML.

        Returns:
            JSON-строка со списком словарей {name, amount, unit} или None.
        """
        container = self.soup.find(class_="wprm-recipe-ingredients-container")
        if not container:
            logger.warning("Ingredients container not found in %s", self.html_path)
            return None

        ingredients = []
        for li in container.find_all("li", class_="wprm-recipe-ingredient"):
            amount_el = li.find(class_="wprm-recipe-ingredient-amount")
            unit_el = li.find(class_="wprm-recipe-ingredient-unit")
            name_el = li.find(class_="wprm-recipe-ingredient-name")

            if not name_el:
                continue

            name = self.clean_text(name_el.get_text())
            if not name:
                continue

            amount = self.clean_text(amount_el.get_text()) if amount_el else None
            unit = self.clean_text(unit_el.get_text()) if unit_el else None

            # Нормализуем запятую как десятичный разделитель → точку
            if amount:
                amount = amount.replace(",", ".")

            ingredients.append({"name": name, "amount": amount, "unit": unit})

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """
        Извлечение шагов приготовления.

        Приоритет: JSON-LD (HowToStep / HowToSection) → WPRM HTML.

        Returns:
            Строка с пронумерованными шагами или None.
        """
        json_ld = self._get_json_ld_data()
        instructions_data = json_ld.get("recipe", {}).get("recipeInstructions", [])

        if instructions_data:
            steps = []
            step_num = 1

            for item in instructions_data:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("@type", "")

                if item_type == "HowToStep":
                    text = self.clean_text(item.get("text", ""))
                    if text:
                        steps.append(f"{step_num}. {text}")
                        step_num += 1

                elif item_type == "HowToSection":
                    for sub in item.get("itemListElement", []):
                        if isinstance(sub, dict) and sub.get("@type") == "HowToStep":
                            text = self.clean_text(sub.get("text", ""))
                            if text:
                                steps.append(f"{step_num}. {text}")
                                step_num += 1

            if steps:
                return " ".join(steps)

        # Fallback: WPRM HTML
        container = self.soup.find(class_="wprm-recipe-instructions-container")
        if container:
            steps = []
            for step_el in container.find_all(class_="wprm-recipe-instruction"):
                text_el = step_el.find(class_="wprm-recipe-instruction-text")
                raw = text_el.get_text() if text_el else step_el.get_text()
                text = self.clean_text(raw)
                if text:
                    steps.append(text)
            if steps:
                return " ".join(steps)

        logger.warning("Instructions not found in %s", self.html_path)
        return None

    # Приоритетные категории типа блюда
    _PRIORITY_CATEGORIES = {
        "Forretter", "Hovedretter", "Desserter", "Dessert",
        "Tilbehør", "Supper", "Snacks", "Brød", "Bagværk",
        "Kage", "Tærte", "Salater", "Morgenmad", "Mellemmåltid",
    }

    def extract_category(self) -> Optional[str]:
        """
        Извлечение категории из Article.articleSection в JSON-LD.

        Сначала ищет раздел из известных категорий блюд.
        Иначе — первый раздел без тире, чтобы отфильтровать длинные строки
        вида «Aftensmad - masser af …».

        Returns:
            Строка-категория или None.
        """
        json_ld = self._get_json_ld_data()
        article_section = json_ld.get("article", {}).get("articleSection", [])

        if not isinstance(article_section, list) or not article_section:
            return None

        # 1. Ищем известную категорию блюда
        for section in article_section:
            if isinstance(section, str) and section in self._PRIORITY_CATEGORIES:
                return self.clean_text(section) or None

        # 2. Первый раздел без описания (нет « - »)
        for section in article_section:
            if isinstance(section, str) and " - " not in section and len(section) <= 40:
                return self.clean_text(section) or None

        # 3. Первый раздел как есть
        return self.clean_text(article_section[0]) if article_section else None

    def extract_cook_time(self) -> Optional[str]:
        """
        Извлечение времени приготовления из WPRM custom-time-container
        (метка «Stegetid»/«Tilberedningstid» и т. п.).

        Returns:
            Строка вида «N timer» или «M minutter» или None.
        """
        wprm = self.soup.find(class_="wprm-recipe-container")
        if not wprm:
            return None

        custom_time_div = wprm.find(
            class_=lambda x: x and "wprm-recipe-custom-time-container" in x.split() if x else False
        )
        return self._parse_wprm_time_container(custom_time_div)

    def extract_total_time(self) -> Optional[str]:
        """
        Извлечение общего времени из WPRM total-time-container или JSON-LD.

        Returns:
            Строка вида «N timer M minutter» или None.
        """
        wprm = self.soup.find(class_="wprm-recipe-container")
        if wprm:
            total_time_div = wprm.find(
                class_=lambda x: x and "wprm-recipe-total-time-container" in x.split() if x else False
            )
            parsed = self._parse_wprm_time_container(total_time_div)
            if parsed:
                return parsed

        # Fallback: JSON-LD ISO 8601
        json_ld = self._get_json_ld_data()
        total_time_iso = json_ld.get("recipe", {}).get("totalTime")
        if total_time_iso:
            return self._format_iso_duration(total_time_iso)

        return None

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок из WPRM notes-container.

        Фильтрует блоки «Se også», содержащие только ссылки без текстового содержания.

        Returns:
            Строка с заметками или None.
        """
        notes_container = self.soup.find(class_="wprm-recipe-notes-container")
        if not notes_container:
            return None

        notes_div = notes_container.find(class_="wprm-recipe-notes")
        if not notes_div:
            return None

        # Собираем текстовые узлы из <span> и <p>, игнорируя заголовки и ссылки
        text_parts = []
        for el in notes_div.find_all(["p", "span"]):
            text = self.clean_text(el.get_text())
            if text and len(text) > 5:
                text_parts.append(text)

        if not text_parts:
            return None

        combined = " ".join(text_parts)
        return combined if len(combined) > 5 else None

    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов из Article.keywords в JSON-LD.
        Запасной вариант: Article.articleSection.

        Returns:
            Строка с тегами, разделёнными «, » или None.
        """
        json_ld = self._get_json_ld_data()
        article = json_ld.get("article", {})

        keywords = article.get("keywords", [])
        if isinstance(keywords, list) and keywords:
            return ", ".join(str(k) for k in keywords)

        # Fallback: articleSection
        article_section = article.get("articleSection", [])
        if isinstance(article_section, list) and article_section:
            # Берём упрощённые короткие разделы (без дефисов-тире)
            simple = [s.split(" - ")[0] for s in article_section if isinstance(s, str)]
            return ", ".join(simple) if simple else None

        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Извлечение URL изображений из JSON-LD Recipe.image.

        Returns:
            URL-адреса через запятую (без пробелов) или None.
        """
        json_ld = self._get_json_ld_data()
        images = json_ld.get("recipe", {}).get("image", [])

        if isinstance(images, str) and images:
            return images
        if isinstance(images, list):
            urls = [img for img in images if isinstance(img, str) and img]
            if urls:
                return ",".join(urls)

        # Fallback: og:image
        og_image = self.soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            return og_image["content"]

        return None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта в едином формате проекта.
        """
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_steps(),
            "category": self.extract_category(),
            "prep_time": None,  # не публикуется на madenimitliv.dk
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls(),
        }


def main() -> None:
    """Точка входа: обрабатывает директорию preprocessed/madenimitliv_dk."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "madenimitliv_dk")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(MadenimitlivDkExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python madenimitliv_dk.py")


if __name__ == "__main__":
    main()
