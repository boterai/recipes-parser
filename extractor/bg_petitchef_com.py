"""
Экстрактор данных рецептов для сайта bg.petitchef.com
"""

import sys
import json
import logging
import re
from pathlib import Path
from typing import Optional, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class BgPetitchefComExtractor(BaseRecipeExtractor):
    """Экстрактор для bg.petitchef.com"""

    BASE_URL = "https://bg.petitchef.com"

    # Болгарские единицы измерения
    _MULTI_WORD_UNITS = [
        "супени лъжици",
        "супена лъжица",
        "чаени лъжички",
        "чаена лъжичка",
    ]
    _SINGLE_WORD_UNITS = [
        "мл", "г", "гр", "кг", "л", "cl", "dl", "ml",
        "бр", "с.л.", "ч.л.", "сл", "чл",
        "чаша", "глава", "капка", "щипка", "пакетче", "кубче",
    ]

    def get_recipe_json_ld(self) -> Optional[Dict[str, Any]]:
        """Извлечение данных Recipe из JSON-LD"""
        for script in self.soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get("@type") == "Recipe":
                    return data
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    def get_base_url(self) -> str:
        """Определение базового URL страницы"""
        canonical = self.soup.find("link", {"rel": "canonical"})
        if canonical and canonical.get("href"):
            href = canonical["href"]
            # Берём только схему + хост
            match = re.match(r"(https?://[^/]+)", href)
            if match:
                return match.group(1)
        return self.BASE_URL

    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат

        Args:
            duration: строка вида «PT20M» или «PT1H30M»

        Returns:
            Время в читаемом формате, например «20 minutes» или «1 hour 30 minutes»
        """
        if not duration or not duration.startswith("PT"):
            return None

        body = duration[2:]  # убираем «PT»

        hours = 0
        minutes = 0

        hour_match = re.search(r"(\d+)H", body)
        if hour_match:
            hours = int(hour_match.group(1))

        min_match = re.search(r"(\d+)M", body)
        if min_match:
            minutes = int(min_match.group(1))

        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")

        return " ".join(parts) if parts else None

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # 1. Пробуем og:title — убираем болгарский префикс «Рецепта за/Рецепта:»
        og_title = self.soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
            # Убираем «Рецепта за», «Рецепта:», «Рецепта »
            prefix_re = re.compile(r"^Рецепта\s*(?:за\s*|:\s*)", re.IGNORECASE)
            if prefix_re.match(title):
                cleaned = prefix_re.sub("", title)
                # Убираем точку в конце
                cleaned = cleaned.rstrip(".")
                cleaned = self.clean_text(cleaned)
                if cleaned:
                    return cleaned

        # 2. JSON-LD name
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and recipe_data.get("name"):
            return self.clean_text(recipe_data["name"])

        # 3. h1.title
        h1 = self.soup.find("h1", class_="title")
        if h1:
            return self.clean_text(h1.get_text())

        logger.warning("Не удалось извлечь dish_name из %s", self.html_path)
        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # 1. JSON-LD Recipe.description
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and recipe_data.get("description"):
            desc = self.clean_text(recipe_data["description"])
            if desc:
                # Берём первое предложение (до первого «.» или «!» или «?»)
                first = re.split(r"(?<=[.!?])\s", desc, maxsplit=1)[0]
                return first.strip() if first else desc

        # 2. meta description
        meta_desc = self.soup.find("meta", {"name": "description"})
        if meta_desc and meta_desc.get("content"):
            return self.clean_text(meta_desc["content"])

        return None

    def _is_section_header(self, text: str) -> bool:
        """Проверяет, является ли строка заголовком секции ингредиентов"""
        if not text:
            return True
        # Строки вида «Пълнеж с канела:», «за покриване:»
        if text.endswith(":"):
            return True
        # Строки вида «За чийзкейка», «За покафеняване»
        if re.match(r"^За\s+", text):
            return True
        return False

    def parse_ingredient_text(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Парсинг строки ингредиента в структурированный формат

        Args:
            text: строка вида «400 мл мляко» или «1/2 ч.л. ванилия»

        Returns:
            Словарь с полями name, amount, unit или None для заголовков секций
        """
        text = self.clean_text(text)
        if not text:
            return None

        if self._is_section_header(text):
            return None

        # Паттерн для суммы: «1 и 1/2», «1/2», «25», «1», «1.5»
        # Взаимно исключающие форматы: десятичное ИЛИ дробное (с «и»)
        amount_re = r"(\d+(?:[.,]\d+)?(?:\s+и\s+\d+/\d+)?|(?:\d+/\d+))"
        match = re.match(rf"^{amount_re}\s+", text)

        if not match:
            # Нет числа — просто название ингредиента (напр. «масло», «захар»)
            return {"name": text, "amount": None, "unit": None}

        amount = match.group(1).strip()
        rest = text[match.end():]

        unit: Optional[str] = None
        name = rest

        # Сначала ищем многословные единицы
        for mu in self._MULTI_WORD_UNITS:
            if rest.lower().startswith(mu):
                unit = mu
                name = rest[len(mu):].strip()
                break

        # Потом однословные
        if unit is None:
            parts = rest.split(None, 1)
            if parts:
                candidate = parts[0]
                # Сравниваем как с оригиналом, так и без крайней точки
                candidate_stripped = candidate.rstrip(".")
                units_lower = [u.lower() for u in self._SINGLE_WORD_UNITS]
                if candidate.lower() in units_lower or candidate_stripped.lower() in units_lower:
                    # Используем нормализованный вариант без крайней точки
                    unit = candidate_stripped if candidate_stripped.lower() in units_lower else candidate
                    name = parts[1].strip() if len(parts) > 1 else ""

        # Убираем пояснения в скобках из имени только если совсем пустое
        if not name:
            name = rest.strip()

        return {"name": name, "amount": amount, "unit": unit}

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD recipeIngredient (primary) или HTML"""
        ingredients: list = []

        # 1. JSON-LD recipeIngredient
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and recipe_data.get("recipeIngredient"):
            for item in recipe_data["recipeIngredient"]:
                parsed = self.parse_ingredient_text(str(item))
                if parsed:
                    ingredients.append(parsed)

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        # 2. Fallback: HTML ul.ingredients-ul
        ing_section = self.soup.find("section", id="rd-ingredients")
        if ing_section:
            for label in ing_section.find_all("label"):
                text = self.clean_text(label.get_text())
                parsed = self.parse_ingredient_text(text)
                if parsed:
                    ingredients.append(parsed)

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        logger.warning("Не удалось извлечь ингредиенты из %s", self.html_path)
        return None

    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []

        # 1. JSON-LD recipeInstructions
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and recipe_data.get("recipeInstructions"):
            instructions = recipe_data["recipeInstructions"]
            for idx, step in enumerate(instructions, 1):
                if isinstance(step, dict):
                    text = self.clean_text(step.get("text", ""))
                elif isinstance(step, str):
                    text = self.clean_text(step)
                else:
                    continue
                if text:
                    steps.append(f"{idx}. {text}")
            if steps:
                return " ".join(steps)

        # 2. Fallback: HTML ul.rd-steps li
        steps_section = self.soup.find("section", id="rd-steps")
        if steps_section:
            for idx, li in enumerate(steps_section.find_all("li"), 1):
                text = self.clean_text(li.get_text(separator=" "))
                if text:
                    steps.append(f"{idx}. {text}")
            if steps:
                return " ".join(steps)

        logger.warning("Не удалось извлечь инструкции из %s", self.html_path)
        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # 1. JSON-LD recipeCategory
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and recipe_data.get("recipeCategory"):
            return self.clean_text(str(recipe_data["recipeCategory"]))

        # 2. Breadcrumbs — предпоследний элемент (перед названием рецепта)
        breadcrumb = self.soup.find("ol", class_="breadcrumb")
        if breadcrumb:
            items = [
                self.clean_text(li.get_text())
                for li in breadcrumb.find_all("li")
                if li.get_text(strip=True)
            ]
            # Структура: Начало > Рецепти > Категория > Название
            if len(items) >= 3:
                return items[-2]

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and recipe_data.get("prepTime"):
            return self.parse_iso_duration(recipe_data["prepTime"])
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and recipe_data.get("cookTime"):
            return self.parse_iso_duration(recipe_data["cookTime"])
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and recipe_data.get("totalTime"):
            return self.parse_iso_duration(recipe_data["totalTime"])
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/наблюдений (секция rd-obs)"""
        obs_section = self.soup.find("section", id="rd-obs")
        if not obs_section:
            return None

        paragraphs = obs_section.find_all("p")
        notes_parts = []
        for p in paragraphs:
            text = self.clean_text(p.get_text(separator=" "))
            if text:
                notes_parts.append(text)

        return " ".join(notes_parts) if notes_parts else None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords"""
        recipe_data = self.get_recipe_json_ld()
        if recipe_data and recipe_data.get("keywords"):
            raw = str(recipe_data["keywords"]).strip()
            if raw:
                # keywords может быть строкой через запятую
                tags = [t.strip() for t in raw.split(",") if t.strip()]
                return ", ".join(tags) if tags else None

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта (карусель + шаговые фото)"""
        base_url = self.get_base_url()
        urls: list = []
        seen: set = set()

        def add_url(raw: str) -> None:
            """Нормализует URL и добавляет в список, если он новый"""
            if not raw:
                return
            raw = raw.strip()
            if raw.startswith("//"):
                raw = "https:" + raw
            elif raw.startswith("/"):
                raw = base_url + raw
            if raw not in seen:
                seen.add(raw)
                urls.append(raw)

        # 1. Главное изображение и изображения карусели
        carousel = self.soup.find("div", id="rd-carousel")
        if carousel:
            for img in carousel.find_all("img"):
                add_url(img.get("src", ""))

        # 2. Изображения шагов (внутри ul.rd-steps)
        steps_ul = self.soup.find("ul", class_="rd-steps")
        if steps_ul:
            for img in steps_ul.find_all("img"):
                add_url(img.get("src", "") or img.get("data-src", ""))

        # 3. Fallback: JSON-LD image
        if not urls:
            recipe_data = self.get_recipe_json_ld()
            if recipe_data:
                img_field = recipe_data.get("image")
                if isinstance(img_field, str):
                    add_url(img_field)
                elif isinstance(img_field, list):
                    for item in img_field:
                        if isinstance(item, str):
                            add_url(item)

        return ",".join(urls) if urls else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта

        Returns:
            Словарь с данными рецепта
        """
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
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls(),
        }


def main() -> None:
    """Точка входа для обработки директории с HTML-файлами bg.petitchef.com"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "bg_petitchef_com")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(BgPetitchefComExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python bg_petitchef_com.py")


if __name__ == "__main__":
    main()
