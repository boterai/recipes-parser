"""
Экстрактор данных рецептов для сайта edeka.de (rezeptwelt)
"""

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import List, Optional, Set, Union

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class EdekaDeExtractor(BaseRecipeExtractor):
    """Экстрактор для edeka.de (rezeptwelt)"""

    # ------------------------------------------------------------------ #
    # Вспомогательные методы                                              #
    # ------------------------------------------------------------------ #

    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение JSON-LD данных рецепта (тип Recipe)"""
        for script in self.soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, dict):
                    if data.get("@type") == "Recipe":
                        return data
                    # Поддержка @graph
                    for item in data.get("@graph", []):
                        if isinstance(item, dict) and item.get("@type") == "Recipe":
                            return item
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") == "Recipe":
                            return item
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в строку вида "X minutes".

        Args:
            duration: строка вида "PT20M" или "PT1H30M"

        Returns:
            Строка, например "90 minutes", или None
        """
        if not duration or not duration.startswith("PT"):
            return None

        body = duration[2:]  # Убираем "PT"
        hours = 0
        minutes = 0

        hour_match = re.search(r"(\d+)H", body)
        if hour_match:
            hours = int(hour_match.group(1))

        min_match = re.search(r"(\d+)M", body)
        if min_match:
            minutes = int(min_match.group(1))

        total = hours * 60 + minutes
        return f"{total} minutes" if total > 0 else None

    @staticmethod
    def _normalize_amount(raw: str) -> Optional[Union[int, float, str]]:
        """
        Нормализует строку количества ингредиента.

        Преобразует немецкий десятичный разделитель «,» в «.» и
        конвертирует в int / float при возможности.

        Returns:
            int, float или строка; None если строка пустая.
        """
        if raw is None:
            return None
        raw = raw.strip().replace(",", ".")
        if not raw:
            return None
        try:
            f = float(raw)
            return int(f) if f == int(f) else f
        except ValueError:
            return raw

    # ------------------------------------------------------------------ #
    # Методы извлечения полей                                             #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get("name"):
            return self.clean_text(recipe["name"])

        # Запасной вариант — заголовок h1
        h1 = self.soup.find("h1")
        if h1:
            return self.clean_text(h1.get_text())

        # og:title
        og_title = self.soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return self.clean_text(og_title["content"])

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get("description"):
            return self.clean_text(recipe["description"])

        # og:description
        og_desc = self.soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            return self.clean_text(og_desc["content"])

        # meta description
        meta_desc = self.soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            return self.clean_text(meta_desc["content"])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из HTML-структуры страницы.

        На edeka.de каждый ингредиент представлен элементом <dl> с
        классом grid-cols-[1fr_2fr]:
          <dt> содержит два <span>: первый — количество, второй — единица.
          <dd> содержит название ингредиента.
        Когда у ингредиента нет количества, <dd> имеет класс col-start-2
        и <dt> отсутствует.
        """
        ingredients = []

        ingr_dls = self.soup.find_all(
            "dl", class_=lambda c: c and "grid-cols-[1fr_2fr]" in c
        )

        for dl in ingr_dls:
            dd = dl.find("dd")
            if not dd:
                continue

            name = self.clean_text(dd.get_text(strip=True))
            if not name:
                continue

            amount: Optional[object] = None
            unit: Optional[str] = None

            dt = dl.find("dt")
            if dt:
                spans = dt.find_all("span")
                if len(spans) >= 2:
                    raw_amount = spans[0].get_text(strip=True)
                    raw_unit = spans[1].get_text(strip=True)
                    amount = self._normalize_amount(raw_amount)
                    unit = raw_unit if raw_unit else None
                elif len(spans) == 1:
                    amount = self._normalize_amount(spans[0].get_text(strip=True))
                else:
                    # dt без span — весь текст как количество
                    amount = self._normalize_amount(dt.get_text(strip=True))

            ingredients.append({"name": name, "amount": amount, "unit": unit})

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        # Запасной вариант — recipeIngredient из JSON-LD
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get("recipeIngredient"):
            return json.dumps(
                [{"name": self.clean_text(i), "amount": None, "unit": None}
                 for i in recipe["recipeIngredient"] if i and i.strip()],
                ensure_ascii=False,
            )

        return None

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления из JSON-LD"""
        recipe = self._get_recipe_json_ld()
        if not recipe:
            return None

        instructions_data = recipe.get("recipeInstructions")
        if not instructions_data:
            return None

        steps = []
        if isinstance(instructions_data, list):
            for idx, step in enumerate(instructions_data, 1):
                if isinstance(step, dict):
                    text = self.clean_text(step.get("text", ""))
                elif isinstance(step, str):
                    text = self.clean_text(step)
                else:
                    continue
                if text:
                    steps.append(f"{idx}. {text}")
        elif isinstance(instructions_data, str):
            text = self.clean_text(instructions_data)
            if text:
                steps.append(text)

        return " ".join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из JSON-LD"""
        recipe = self._get_recipe_json_ld()
        if recipe:
            category = recipe.get("recipeCategory")
            if category:
                if isinstance(category, list):
                    return self.clean_text(", ".join(category))
                return self.clean_text(str(category))

        # Запасной вариант — breadcrumbs
        breadcrumbs = self.soup.find("nav", class_=re.compile(r"breadcrumb", re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all("a")
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())

        return None

    def _extract_time_from_html(self, dt_label: str) -> Optional[str]:
        """
        Извлечение времени из HTML-элемента <dl> по метке <dt>.

        На edeka.de основные временные метки:
          «Zubereitungszeit» (время подготовки / общее время приготовления)
          «Gesamtzeit»       (общее время)

        Args:
            dt_label: точное содержимое <dt>

        Returns:
            Строка со временем (например, «25 min.»), или None.
        """
        for dl in self.soup.find_all("dl"):
            dt = dl.find("dt")
            if dt and dt.get_text(strip=True) == dt_label:
                dd = dl.find("dd")
                if dd:
                    return self.clean_text(dd.get_text(strip=True))
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get("prepTime"):
            result = self._parse_iso_duration(recipe["prepTime"])
            if result:
                return result

        # Запасной вариант — HTML
        return self._extract_time_from_html("Zubereitungszeit")

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get("cookTime"):
            result = self._parse_iso_duration(recipe["cookTime"])
            if result:
                return result

        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get("totalTime"):
            result = self._parse_iso_duration(recipe["totalTime"])
            if result:
                return result

        # Запасной вариант — HTML
        return self._extract_time_from_html("Gesamtzeit")

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок / советов к рецепту.

        Сайт edeka.de не имеет выделенного блока советов на большинстве
        страниц рецептов, поэтому возвращаем None, если специальный блок
        не найден.
        """
        # Ищем элементы с типичными ключевыми словами для советов
        for tag in self.soup.find_all(["p", "div", "aside", "section"]):
            cls = " ".join(tag.get("class", []))
            if re.search(r"tipp|tip|hint|note|advice", cls, re.I):
                text = self.clean_text(tag.get_text(separator=" ", strip=True))
                if text and len(text) > 20:
                    return text

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из поля keywords в JSON-LD"""
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get("keywords"):
            keywords = recipe["keywords"]
            if isinstance(keywords, list):
                tags = [self.clean_text(k) for k in keywords if k and k.strip()]
            else:
                tags = [t.strip() for t in str(keywords).split(",") if t.strip()]
            return ", ".join(tags) if tags else None

        return None

    def _get_base_url(self) -> str:
        """Определение базового URL сайта для разрешения относительных URL"""
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get("url"):
            m = re.match(r"(https?://[^/]+)", recipe["url"])
            if m:
                return m.group(1)

        canonical = self.soup.find("link", rel="canonical")
        if canonical and canonical.get("href"):
            m = re.match(r"(https?://[^/]+)", canonical["href"])
            if m:
                return m.group(1)

        return "https://www.edeka.de"

    def _resolve_url(self, url: str, base: str) -> str:
        """Преобразует относительный URL в абсолютный"""
        if url.startswith("http://") or url.startswith("https://"):
            return url
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return base.rstrip("/") + url
        return url

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        base = self._get_base_url()
        urls = []

        # 1. og:image
        og_image = self.soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            urls.append(self._resolve_url(og_image["content"], base))

        # 2. JSON-LD image
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get("image"):
            img = recipe["image"]
            raw_urls: List[str] = []
            if isinstance(img, str):
                raw_urls.append(img)
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        raw_urls.append(item)
                    elif isinstance(item, dict):
                        u = item.get("url") or item.get("contentUrl") or ""
                        if u:
                            raw_urls.append(u)
            elif isinstance(img, dict):
                u = img.get("url") or img.get("contentUrl")
                if u:
                    raw_urls.append(u)

            for u in raw_urls:
                urls.append(self._resolve_url(u, base))

        # Убираем дубликаты, сохраняем порядок
        seen: Set[str] = set()
        unique: List[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ",".join(unique) if unique else None

    # ------------------------------------------------------------------ #
    # Публичный API                                                        #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта в едином формате проекта.
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception:
            logger.exception("Ошибка при извлечении dish_name из %s", self.html_path)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception:
            logger.exception("Ошибка при извлечении description из %s", self.html_path)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception:
            logger.exception(
                "Ошибка при извлечении ingredients из %s", self.html_path
            )
            ingredients = None

        try:
            instructions = self.extract_steps()
        except Exception:
            logger.exception(
                "Ошибка при извлечении instructions из %s", self.html_path
            )
            instructions = None

        try:
            category = self.extract_category()
        except Exception:
            logger.exception("Ошибка при извлечении category из %s", self.html_path)
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception:
            logger.exception("Ошибка при извлечении prep_time из %s", self.html_path)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception:
            logger.exception("Ошибка при извлечении cook_time из %s", self.html_path)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception:
            logger.exception("Ошибка при извлечении total_time из %s", self.html_path)
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception:
            logger.exception("Ошибка при извлечении notes из %s", self.html_path)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception:
            logger.exception("Ошибка при извлечении tags из %s", self.html_path)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception:
            logger.exception(
                "Ошибка при извлечении image_urls из %s", self.html_path
            )
            image_urls = None

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


def main() -> None:
    """Точка входа для обработки директории с HTML файлами"""
    preprocessed_dir = os.path.join("preprocessed", "edeka_de")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(EdekaDeExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python edeka_de.py")


if __name__ == "__main__":
    main()
