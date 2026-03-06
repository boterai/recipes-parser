"""
Экстрактор данных рецептов для сайта cpastry.com
"""

import logging
import re
import sys
import json
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class CpastryComExtractor(BaseRecipeExtractor):
    """Экстрактор для cpastry.com (WordPress + AIOSEO Recipe schema)"""

    # ------------------------------------------------------------------ #
    # Вспомогательные методы
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """Конвертирует ISO 8601 duration (PT45M / PT1H30M) в строку вида '45 minutes'."""
        if not duration or not duration.startswith("PT"):
            return None

        rest = duration[2:]
        hours = 0
        minutes = 0

        h_match = re.search(r"(\d+)H", rest)
        if h_match:
            hours = int(h_match.group(1))

        m_match = re.search(r"(\d+)M", rest)
        if m_match:
            minutes = int(m_match.group(1))

        total_minutes = hours * 60 + minutes
        if total_minutes == 0:
            return None

        if total_minutes % 60 == 0:
            hours_out = total_minutes // 60
            return f"{hours_out} hour{'s' if hours_out != 1 else ''}"
        elif hours > 0:
            return f"{hours} hour{'s' if hours != 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}"
        else:
            return f"{total_minutes} minute{'s' if total_minutes != 1 else ''}"

    def _get_recipe_jsonld(self) -> Optional[dict]:
        """
        Извлекает объект Recipe из JSON-LD.
        Поддерживает как структуру {\"@graph\": [...]}, так и одиночный объект Recipe.
        """
        scripts = self.soup.find_all("script", type="application/ld+json")
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
            except json.JSONDecodeError:
                logger.warning(
                    "Не удалось разобрать JSON-LD скрипт (первые 200 символов): %s",
                    script.string[:200] if script.string else "<empty>",
                )
                continue

            if isinstance(data, dict):
                # @graph
                if "@graph" in data:
                    for item in data["@graph"]:
                        if isinstance(item, dict) and item.get("@type") == "Recipe":
                            return item
                # одиночный Recipe
                if data.get("@type") == "Recipe":
                    return data

            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "Recipe":
                        return item

        return None

    # Список распространённых китайских и международных единиц измерения
    _UNITS = [
        # Китайские
        "克", "千克", "斤", "毫升", "升", "汤匙", "茶匙", "个", "根", "片",
        "条", "杯", "袋", "包", "盒", "块", "瓣", "颗", "粒", "滴", "盎司",
        # Английские (встречаются на многоязычных страницах)
        "g", "kg", "ml", "l", "tbsp", "tsp", "cup", "cups", "oz", "lb", "lbs",
        "tablespoon", "tablespoons", "teaspoon", "teaspoons",
        "gram", "grams", "kilogram", "kilograms",
        "milliliter", "milliliters", "liter", "liters",
        "pound", "pounds", "ounce", "ounces",
        "pinch", "dash", "clove", "cloves", "slice", "slices", "piece", "pieces",
    ]

    # ------------------------------------------------------------------ #
    # Парсинг ингредиентов из HTML-параграфа
    # ------------------------------------------------------------------ #

    def _parse_ingredient_line(self, line: str) -> Optional[dict]:
        """
        Разбирает строку ингредиента, используя метрические единицы там, где представлены обе системы.

        Примеры входных строк:
          «9.5 盎司/270 克黄油 RT»   → {name: «黄油», amount: «270», unit: «克»}
          «4 个大蛋黄»               → {name: «大蛋黄», amount: «4», unit: «个»}
          «1 汤匙柠檬汁»              → {name: «柠檬汁», amount: «1», unit: «汤匙»}
          «50 克 切碎山核桃»          → {name: «切碎山核桃», amount: «50», unit: «克»}
        """
        line = self.clean_text(line)
        if not line:
            return None

        # Сортируем единицы по убыванию длины, чтобы «汤匙» находили раньше «匙»
        units_sorted = sorted(self._UNITS, key=len, reverse=True)
        units_pattern = "|".join(re.escape(u) for u in units_sorted)

        # ---- 1. Двойной формат: «9.5 盎司/270 克黄油 RT» ----
        # Берём метрическую часть (после «/»).
        # «RT» — суффикс «room temperature» (комнатная температура), игнорируется.
        dual = re.match(
            rf"[\d.,]+\s*\S+\s*/\s*([\d.,]+)\s*({units_pattern})\s*(.+?)(?:\s+RT)?\s*$",
            line,
            re.IGNORECASE,
        )
        if dual:
            amount = dual.group(1).strip()
            unit = dual.group(2).strip()
            name = dual.group(3).strip()
            return {"name": name, "amount": amount, "unit": unit}

        # ---- 2. Паттерн: число + единица (вплотную или через пробел) + название ----
        m = re.match(
            rf"^([\d.,/]+)\s*({units_pattern})\s+(.+)$",
            line,
            re.IGNORECASE,
        )
        if m:
            amount = m.group(1).strip()
            unit = m.group(2).strip()
            name = re.sub(r"\s+RT\s*$", "", m.group(3), flags=re.IGNORECASE).strip()
            return {"name": name, "amount": amount, "unit": unit}

        # ---- 3. Число + единица без пробела + название (только китайские иероглифы) ----
        m = re.match(
            rf"^([\d.,/]+)\s*({units_pattern})(.+)$",
            line,
            re.IGNORECASE,
        )
        if m:
            amount = m.group(1).strip()
            unit = m.group(2).strip()
            name = re.sub(r"\s+RT\s*$", "", m.group(3), flags=re.IGNORECASE).strip()
            return {"name": name, "amount": amount, "unit": unit}

        # ---- 4. Только число и название (без единицы) ----
        m = re.match(r"^([\d.,/]+)\s+(.+)$", line)
        if m:
            amount = m.group(1).strip()
            name = re.sub(r"\s+RT\s*$", "", m.group(2), flags=re.IGNORECASE).strip()
            return {"name": name, "amount": amount, "unit": None}

        # ---- 5. Только название ----
        logger.debug("Не удалось разобрать строку ингредиента: %s", line)
        return {"name": line, "amount": None, "unit": None}

    def _extract_ingredients_from_html(self) -> list:
        """
        Извлекает ингредиенты из текстового блока uk-text-lead на странице.
        Блок содержит заголовок рецепта, затем маркер «原料：» (или Ingredients:),
        затем по одному ингредиенту на строку.
        """
        ingredients = []

        text_lead = self.soup.find(
            "div", class_=lambda c: c and "uk-text-lead" in c
        )
        if not text_lead:
            return ingredients

        paragraph = text_lead.find("p")
        if not paragraph:
            return ingredients

        # Берём текст, разбивая по <br>
        raw_lines = []
        for item in paragraph.descendants:
            if hasattr(item, "name") and item.name == "br":
                raw_lines.append("\n")
            elif isinstance(item, str):
                raw_lines.append(item)

        full_text = "".join(raw_lines)
        lines = [l.strip() for l in full_text.split("\n") if l.strip()]

        # Ищем начало списка ингредиентов
        ingredient_started = False
        ingredient_markers = re.compile(
            r"(原料|配料|配方|材料|Ingredients?)\s*[：:]*\s*$", re.IGNORECASE
        )

        for line in lines:
            if not ingredient_started:
                if ingredient_markers.search(line):
                    ingredient_started = True
                continue

            parsed = self._parse_ingredient_line(line)
            if parsed:
                ingredients.append(parsed)

        return ingredients

    # ------------------------------------------------------------------ #
    # Публичные методы извлечения данных
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Название блюда из JSON-LD или h1."""
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get("name"):
            return self.clean_text(recipe["name"])

        h1 = self.soup.find("h1")
        if h1:
            return self.clean_text(h1.get_text())

        og_title = self.soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return self.clean_text(og_title["content"])

        return None

    def extract_description(self) -> Optional[str]:
        """
        Краткое описание рецепта.
        Берём первую строку из текстового блока uk-text-lead (до маркера «原料：»).
        """
        text_lead = self.soup.find(
            "div", class_=lambda c: c and "uk-text-lead" in c
        )
        if text_lead:
            paragraph = text_lead.find("p")
            if paragraph:
                raw_lines = []
                for item in paragraph.descendants:
                    if hasattr(item, "name") and item.name == "br":
                        raw_lines.append("\n")
                    elif isinstance(item, str):
                        raw_lines.append(item)

                full_text = "".join(raw_lines)
                lines = [l.strip() for l in full_text.split("\n") if l.strip()]

                ingredient_markers = re.compile(
                    r"(原料|配料|配方|材料|Ingredients?)\s*[：:]*\s*$", re.IGNORECASE
                )
                for line in lines:
                    if ingredient_markers.search(line):
                        break
                    desc = self.clean_text(line)
                    if desc:
                        return desc

        # Резервно — meta description
        meta_desc = self.soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            return self.clean_text(meta_desc["content"])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Ингредиенты в виде JSON-строки.
        Пытается извлечь структурированные ингредиенты (name/amount/unit)
        из HTML-параграфа; при неудаче использует recipeIngredient из JSON-LD.
        """
        # Приоритет — HTML-параграф (содержит количества и единицы)
        ingredients = self._extract_ingredients_from_html()

        # Если HTML не дал результата — fallback на JSON-LD
        if not ingredients:
            recipe = self._get_recipe_jsonld()
            if recipe and recipe.get("recipeIngredient"):
                for item in recipe["recipeIngredient"]:
                    if isinstance(item, str) and item.strip():
                        ingredients.append(
                            {"name": self.clean_text(item), "amount": None, "unit": None}
                        )

        if not ingredients:
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def extract_instructions(self) -> Optional[str]:
        """
        Шаги приготовления из JSON-LD recipeInstructions.
        Если JSON-LD не содержит инструкций, извлекает из HTML.
        """
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get("recipeInstructions"):
            parts = []
            for step in recipe["recipeInstructions"]:
                if isinstance(step, dict) and step.get("text"):
                    parts.append(self.clean_text(step["text"]))
                elif isinstance(step, str):
                    parts.append(self.clean_text(step))
            if parts:
                return " ".join(parts)

        # Fallback — HTML (el-content внутри секции «Method»)
        method_section = self.soup.find(
            "div",
            class_=lambda c: c and "uk-width-2-3@m" in c and "uk-flex-first@m" in c,
        )
        if method_section:
            el_content = method_section.find("div", class_="el-content")
            if el_content:
                return self.clean_text(el_content.get_text(separator="\n"))

        return None

    def extract_category(self) -> Optional[str]:
        """Категория из JSON-LD (recipeCategory / recipeCuisine)."""
        recipe = self._get_recipe_jsonld()
        if recipe:
            parts = []
            if recipe.get("recipeCategory"):
                parts.append(self.clean_text(str(recipe["recipeCategory"])))
            if recipe.get("recipeCuisine"):
                parts.append(self.clean_text(str(recipe["recipeCuisine"])))
            if parts:
                return ", ".join(parts)

        # Хлебные крошки
        breadcrumb = self.soup.find("nav", class_=re.compile(r"breadcrumb", re.I))
        if breadcrumb:
            links = breadcrumb.find_all("a")
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())

        return None

    def _extract_time_from_jsonld(self, time_key: str) -> Optional[str]:
        """Извлечение времени из JSON-LD по ключу (prepTime, cookTime, totalTime)."""
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get(time_key):
            return self._parse_iso_duration(recipe[time_key])
        return None

    def _extract_cook_time_from_instructions(self) -> Optional[str]:
        """
        Пытается извлечь время готовки из текста инструкций.
        Ищет паттерны вида «45 分钟», «1 hour», «30 minutes».
        """
        instructions = self.extract_instructions()
        if not instructions:
            return None

        # Китайские минуты
        m = re.search(r"(\d+)\s*分钟", instructions)
        if m:
            mins = int(m.group(1))
            return f"{mins} minute{'s' if mins != 1 else ''}"

        # Английские единицы времени
        m = re.search(r"(\d+)\s*(hour|minute)s?", instructions, re.IGNORECASE)
        if m:
            num = int(m.group(1))
            unit = m.group(2).lower()
            return f"{num} {unit}{'s' if num != 1 else ''}"

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки."""
        return self._extract_time_from_jsonld("prepTime")

    def extract_cook_time(self) -> Optional[str]:
        """Время приготовления."""
        result = self._extract_time_from_jsonld("cookTime")
        if result:
            return result
        return self._extract_cook_time_from_instructions()

    def extract_total_time(self) -> Optional[str]:
        """Общее время."""
        return self._extract_time_from_jsonld("totalTime")

    def extract_notes(self) -> Optional[str]:
        """Заметки к рецепту из HTML."""
        # В cpastry.com заметки находятся в el-content при наличии h3.el-title с текстом «Примечания»
        method_section = self.soup.find(
            "div",
            class_=lambda c: c and "uk-width-2-3@m" in c and "uk-flex-first@m" in c,
        )
        if method_section:
            for title_elem in method_section.find_all("h3", class_="el-title"):
                title_text = title_elem.get_text(strip=True)
                # Если заголовок не «Примечания/Notes», пропускаем
                if re.search(r"(note|tip|hint|примечани|совет)", title_text, re.IGNORECASE):
                    content = title_elem.find_next_sibling("div", class_="el-content")
                    if content:
                        text = self.clean_text(content.get_text())
                        return text if text else None

        return None

    def extract_tags(self) -> Optional[str]:
        """Теги из JSON-LD keywords."""
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get("keywords"):
            keywords = recipe["keywords"]
            if isinstance(keywords, list):
                tags = [self.clean_text(k) for k in keywords if k.strip()]
            else:
                tags = [t.strip() for t in str(keywords).split(",") if t.strip()]
            return ", ".join(tags) if tags else None

        return None

    def extract_image_urls(self) -> Optional[str]:
        """URL изображений из JSON-LD и meta-тегов."""
        urls = []

        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get("image"):
            img = recipe["image"]
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                url = img.get("url") or img.get("contentUrl")
                if url:
                    urls.append(url)
            elif isinstance(img, list):
                for i in img:
                    if isinstance(i, str):
                        urls.append(i)
                    elif isinstance(i, dict):
                        url = i.get("url") or i.get("contentUrl")
                        if url:
                            urls.append(url)

        # og:image
        og_image = self.soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            urls.append(og_image["content"])

        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ",".join(unique_urls) if unique_urls else None

    # ------------------------------------------------------------------ #
    # Основной метод
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
        except Exception:
            logger.exception("Непредвиденная ошибка при извлечении данных из %s", self.html_path)
            dish_name = description = ingredients = instructions = None
            category = prep_time = cook_time = total_time = notes = tags = image_urls = None

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

    recipes_dir = os.path.join("preprocessed", "cpastry_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(CpastryComExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python cpastry_com.py")


if __name__ == "__main__":
    main()
