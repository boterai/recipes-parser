"""
Экстрактор данных рецептов для сайта mumaskitchen.de

Сайт построен на WordPress с плагином Tasty Recipes.
Основные источники данных:
  - Карточка рецепта Tasty Recipes (div.tasty-recipes / div.tasty-recipe-instructions и др.)
  - JSON-LD типа Recipe (application/ld+json)
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional, Union

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class MumaskitchenDeExtractor(BaseRecipeExtractor):
    """Экстрактор для mumaskitchen.de (WordPress + Tasty Recipes plugin)"""

    # Немецкие и английские единицы измерения (в порядке убывания длины, чтобы избежать
    # частичных совпадений более длинных единиц)
    GERMAN_UNITS = [
        # Весовые
        "kg", "g",
        # Объёмные
        "dl", "cl", "ml", "l",
        # Немецкие кулинарные единицы
        "EL", "TL", "el", "tl",
        "Würfeln", "Würfel",
        "Prisen", "Prise",
        "Tassen", "Tasse",
        "Becher",
        "Stücke", "Stück", "Stck",
        "Zehen", "Zehe",
        "Scheiben", "Scheibe",
        "Bündel", "Bund",
        "Zweige", "Zweig",
        "Dosen", "Dose",
        "Pakete", "Paket", "Pkt",
        "Handvoll",
        # Английские (могут встречаться)
        "cups", "cup", "tbsp", "tsp", "oz", "lbs", "lb",
    ]

    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD (тип Recipe)"""
        scripts = self.soup.find_all("script", type="application/ld+json")
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                # Прямой тип Recipe
                if isinstance(data, dict) and data.get("@type") == "Recipe":
                    return data
                # Массив объектов
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") == "Recipe":
                            return item
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return None

    # ------------------------------------------------------------------
    # Извлечение отдельных полей
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Основной источник: заголовок карточки Tasty Recipes
        title_elem = self.soup.find("h2", class_="tasty-recipes-title")
        if title_elem:
            return self.clean_text(title_elem.get_text())

        # Запасной: JSON-LD Recipe
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and recipe_data.get("name"):
            return self.clean_text(recipe_data["name"])

        # Запасной: заголовок h1
        h1 = self.soup.find("h1")
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Блок описания Tasty Recipes
        desc_div = self.soup.find("div", class_="tasty-recipes-description")
        if desc_div:
            p = desc_div.find("p")
            if p:
                text = self.clean_text(p.get_text())
                if text:
                    return text
            # Если нет тега <p>, берём весь текст блока
            text = self.clean_text(desc_div.get_text(separator=" ", strip=True))
            if text:
                return text

        # Запасной: JSON-LD Recipe description
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and recipe_data.get("description"):
            return self.clean_text(recipe_data["description"])

        # Запасной: meta description
        meta_desc = self.soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            return self.clean_text(meta_desc["content"])

        return None

    # ------------------------------------------------------------------
    # Ингредиенты
    # ------------------------------------------------------------------

    def _parse_amount(self, amount_str: str) -> Optional[Union[int, float]]:
        """Конвертация строки количества в число (int или float)"""
        if not amount_str:
            return None
        amount_str = amount_str.strip()
        try:
            # Дробь вида "1/4" или смешанная "1 1/2"
            if "/" in amount_str:
                parts = amount_str.split()
                total = 0.0
                for part in parts:
                    if "/" in part:
                        num, denom = part.split("/")
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                # Возвращаем int, если значение целое
                return int(total) if total == int(total) else total
            val = float(amount_str)
            return int(val) if val == int(val) else val
        except (ValueError, ZeroDivisionError):
            return None

    def _parse_ingredient_text(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный словарь.

        Поддерживает:
          - немецкую десятичную запятую: "0,5" → 0.5
          - Unicode-дроби: ½, ¼, ¾, ⅓ и т.д.
          - дроби ASCII: "1/4", "1/2"
          - смешанные числа: "1 1/2"
          - немецкие и английские единицы измерения

        Returns:
            {"name": str, "amount": int|float|None, "unit": str|None}
        """
        if not text:
            return None

        text = self.clean_text(text)

        # Заменяем Unicode-дроби на ASCII
        fraction_map = {
            "½": "1/2", "¼": "1/4", "¾": "3/4",
            "⅓": "1/3", "⅔": "2/3",
            "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
            "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5",
        }
        for frac, repl in fraction_map.items():
            text = text.replace(frac, repl)

        # Нормализуем немецкую десятичную запятую: "0,5" → "0.5"
        text = re.sub(r"(\d),(\d)", r"\1.\2", text)

        # Единицы для regex (сортированы по убыванию длины — важно для корректного матчинга)
        units_sorted = sorted(self.GERMAN_UNITS, key=len, reverse=True)
        units_pattern = "|".join(re.escape(u) for u in units_sorted)

        # Паттерн числа: целое, десятичное, дробь, смешанная дробь
        num_pat = r"(?:\d+\s*/\s*\d+|\d+\.\d+|\d+)"
        # Составное число: "1 1/2", "1.5" и т.п.
        amount_pat = rf"(?:{num_pat}(?:\s+{num_pat})?)"

        # Вариант 1: "число единица название"
        match = re.match(
            rf"^({amount_pat})\s+({units_pattern})\s+(.+)$",
            text,
            re.IGNORECASE,
        )
        if match:
            amount_str, unit, name = match.groups()
            return {
                "name": self.clean_text(name),
                "amount": self._parse_amount(amount_str.strip()),
                "unit": unit.strip(),
            }

        # Вариант 2: "число название" (без единицы)
        match = re.match(rf"^({amount_pat})\s+(.+)$", text)
        if match:
            amount_str, name = match.groups()
            # Убеждаемся, что это действительно число, а не слово
            if re.fullmatch(r"[\d ./]+", amount_str.strip()):
                return {
                    "name": self.clean_text(name),
                    "amount": self._parse_amount(amount_str.strip()),
                    "unit": None,
                }

        # Вариант 3: только название (без числа и единицы)
        return {"name": text, "amount": None, "unit": None}

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в виде JSON-строки списка словарей"""
        ingredients = []

        # Основной источник: HTML-блок Tasty Recipes
        ingr_body = self.soup.find("div", class_="tasty-recipes-ingredients-body")
        if ingr_body:
            items = ingr_body.find_all("li")
            for item in items:
                # strip=False + ручной strip: правильно обрабатывает "280 g Weizenmehl"
                # (пробел между span и текстовым узлом сохраняется) и "0,5 TL Backpulver"
                # (запятая сразу после span без пробела сохраняется).
                text = item.get_text(separator="", strip=False).strip()
                text = self.clean_text(text)
                if text:
                    parsed = self._parse_ingredient_text(text)
                    if parsed:
                        ingredients.append(parsed)

        # Запасной: JSON-LD recipeIngredient
        if not ingredients:
            recipe_data = self._get_recipe_json_ld()
            if recipe_data and "recipeIngredient" in recipe_data:
                for ingr_text in recipe_data["recipeIngredient"]:
                    text = self.clean_text(str(ingr_text))
                    if text:
                        parsed = self._parse_ingredient_text(text)
                        if parsed:
                            ingredients.append(parsed)

        if not ingredients:
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Инструкции
    # ------------------------------------------------------------------

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления в виде одной строки"""
        steps = []

        # Основной источник: HTML-блок Tasty Recipes
        instructions_div = self.soup.find("div", class_="tasty-recipe-instructions")
        if instructions_div:
            body = instructions_div.find(
                "div", class_="tasty-recipes-instructions-body"
            )
            if body:
                items = body.find_all("li")
                for item in items:
                    text = self.clean_text(
                        item.get_text(separator=" ", strip=True)
                    )
                    if text:
                        steps.append(text)

        if steps:
            return " ".join(steps)

        # Запасной: JSON-LD recipeInstructions
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and "recipeInstructions" in recipe_data:
            for step in recipe_data["recipeInstructions"]:
                if isinstance(step, dict):
                    text = self.clean_text(step.get("text", ""))
                elif isinstance(step, str):
                    text = self.clean_text(step)
                else:
                    continue
                if text:
                    steps.append(text)

        return " ".join(steps) if steps else None

    # ------------------------------------------------------------------
    # Категория и время
    # ------------------------------------------------------------------

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда"""
        # Из карточки Tasty Recipes
        cat_elem = self.soup.find("span", class_="tasty-recipes-category")
        if cat_elem:
            text = self.clean_text(cat_elem.get_text())
            if text:
                return text

        # Запасной: JSON-LD recipeCategory
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and recipe_data.get("recipeCategory"):
            return self.clean_text(str(recipe_data["recipeCategory"]))

        return None

    def _extract_time_html(self, css_class: str) -> Optional[str]:
        """Извлечение времени из HTML-элемента Tasty Recipes по CSS-классу"""
        elem = self.soup.find("span", class_=css_class)
        if elem:
            text = self.clean_text(elem.get_text())
            return text if text else None
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self._extract_time_html("tasty-recipes-prep-time")

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self._extract_time_html("tasty-recipes-cook-time")

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self._extract_time_html("tasty-recipes-total-time")

    # ------------------------------------------------------------------
    # Заметки, теги, изображения
    # ------------------------------------------------------------------

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов к рецепту"""
        notes_div = self.soup.find("div", class_="tasty-recipes-notes")
        if notes_div:
            body = notes_div.find("div", class_="tasty-recipes-notes-body")
            if body:
                # Список пунктов
                items = body.find_all("li")
                if items:
                    texts = [
                        self.clean_text(item.get_text(separator=" ", strip=True))
                        for item in items
                    ]
                    texts = [t for t in texts if t]
                    if texts:
                        return " ".join(texts)

                # Параграфы
                paras = body.find_all("p")
                if paras:
                    texts = [
                        self.clean_text(p.get_text(separator=" ", strip=True))
                        for p in paras
                    ]
                    texts = [t for t in texts if t]
                    if texts:
                        return " ".join(texts)

                # Весь текст блока как запасной вариант
                text = self.clean_text(body.get_text(separator=" ", strip=True))
                if text:
                    return text

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из поля keywords JSON-LD Recipe"""
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and recipe_data.get("keywords"):
            kw = recipe_data["keywords"]
            if isinstance(kw, list):
                return ", ".join(k.strip() for k in kw if k.strip())
            if isinstance(kw, str) and kw.strip():
                return kw.strip()

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls = []

        # Основной источник: JSON-LD Recipe image
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and "image" in recipe_data:
            img = recipe_data["image"]
            if isinstance(img, list):
                for item in img:
                    if isinstance(item, str) and item:
                        urls.append(item)
                    elif isinstance(item, dict):
                        url = item.get("url") or item.get("contentUrl")
                        if url:
                            urls.append(url)
            elif isinstance(img, str) and img:
                urls.append(img)
            elif isinstance(img, dict):
                url = img.get("url") or img.get("contentUrl")
                if url:
                    urls.append(url)

        # Запасной: изображение из карточки Tasty Recipes
        if not urls:
            img_div = self.soup.find("div", class_="tasty-recipes-image")
            if img_div:
                img_tag = img_div.find("img")
                if img_tag:
                    src = img_tag.get("src") or img_tag.get("data-src")
                    if src:
                        urls.append(src)

        # Запасной: og:image
        if not urls:
            og_image = self.soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                urls.append(og_image["content"])

        # Дедупликация с сохранением порядка
        seen: set = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ",".join(unique_urls) if unique_urls else None

    # ------------------------------------------------------------------
    # Основной метод
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта из HTML.

        Returns:
            Словарь со всеми полями рецепта. Отсутствующие поля — None.
        """
        result: dict = {
            "dish_name": None,
            "description": None,
            "ingredients": None,
            "instructions": None,
            "category": None,
            "prep_time": None,
            "cook_time": None,
            "total_time": None,
            "notes": None,
            "tags": None,
            "image_urls": None,
        }

        extractors = {
            "dish_name": self.extract_dish_name,
            "description": self.extract_description,
            "ingredients": self.extract_ingredients,
            "instructions": self.extract_steps,
            "category": self.extract_category,
            "prep_time": self.extract_prep_time,
            "cook_time": self.extract_cook_time,
            "total_time": self.extract_total_time,
            "notes": self.extract_notes,
            "tags": self.extract_tags,
            "image_urls": self.extract_image_urls,
        }

        for field, extractor_fn in extractors.items():
            try:
                result[field] = extractor_fn()
            except Exception as exc:
                logger.warning(
                    "Ошибка при извлечении поля '%s' из %s: %s",
                    field,
                    self.html_path,
                    exc,
                )

        return result


def main() -> None:
    """Запуск экстрактора для директории preprocessed/mumaskitchen_de"""
    import os

    recipes_dir = os.path.join("preprocessed", "mumaskitchen_de")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(MumaskitchenDeExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Запустите скрипт из корня репозитория.")


if __name__ == "__main__":
    main()
