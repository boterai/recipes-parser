"""
Экстрактор данных рецептов для сайта kitcheninred.com
"""

import logging
import json
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Категории, которые являются тегами-атрибутами или жанровыми маркерами,
# а не типами блюд — исключаем их при выборе основной категории
_GENERIC_CATEGORIES = {
    "tüm tariflerim",
    "dört mevsim",
    "sevgililer günü",
    "doğum günü",
    "parti",
    "çay saati",
    "vejetaryen",
    "glutensiz",
    "hafif ve sağlıklı",
    "temel tarifler",
    "sebzeli",
    "bayramlar",
    "yeni yıl",
    "anneler günü",
    "babalar günü",
}

# Турецкие единицы измерения (для разбора строки amount из HTML)
_TURKISH_UNITS = [
    "tepeleme yemek kaşığı",
    "tepeleme çorba kaşığı",
    "yemek kaşığı",
    "çorba kaşığı",
    "tatlı kaşığı",
    "çay kaşığı",
    "su bardağı",
    "çay bardağı",
    "kilogram",
    "gram",
    "litre",
    "büyük boy",
    "orta boy",
    "küçük boy",
    "bütün",
    "kg",
    "gr",
    "ml",
    "cc",
    "lt",
    "adet",
    "diş",
    "sap",
    "dal",
    "demet",
    "baş",
    "parça",
    "dilim",
    "tutam",
    "avuç",
    "tane",
    "kıyım",
    "bardak",
    "paket",
    "kutu",
    "şişe",
    "çiçek",
]

# Regex для поиска единиц измерения (сортировка по длине — более длинные паттерны первыми)
_UNIT_PATTERN = re.compile(
    r'^(' + '|'.join(re.escape(u) for u in sorted(_TURKISH_UNITS, key=len, reverse=True)) + r')\b',
    re.IGNORECASE | re.UNICODE,
)


class KitcheninredComExtractor(BaseRecipeExtractor):
    """Экстрактор для kitcheninred.com"""

    def _get_recipe_jsonld(self) -> Optional[dict]:
        """Возвращает первый объект Recipe из JSON-LD или None."""
        for script in self.soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue

            if isinstance(data, dict):
                if data.get("@type") == "Recipe":
                    return data
                # Проверяем @graph
                for item in data.get("@graph", []):
                    if isinstance(item, dict) and item.get("@type") == "Recipe":
                        return item
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "Recipe":
                        return item
        return None

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда."""
        # Основной источник: H1 внутри div.single-title
        title_div = self.soup.find("div", class_="single-title")
        if title_div:
            h1 = title_div.find("h1")
            if h1:
                name = self.clean_text(h1.get_text())
                return self._strip_tarifi_suffix(name)

        # Запасной вариант: любой H1
        h1 = self.soup.find("h1")
        if h1:
            name = self.clean_text(h1.get_text())
            return self._strip_tarifi_suffix(name)

        # Ещё один запасной вариант: JSON-LD
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get("name"):
            name = self.clean_text(recipe["name"])
            return self._strip_tarifi_suffix(name)

        # og:title
        og_title = self.soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            name = re.sub(r"\s*[-|–]\s*KitcheninRed.*$", "", og_title["content"], flags=re.IGNORECASE)
            name = self.clean_text(name)
            return self._strip_tarifi_suffix(name) if name else None

        return None

    @staticmethod
    def _strip_tarifi_suffix(name: str) -> str:
        """Удаляет суффикс ' Tarifi' (или ' tarifi') из конца названия."""
        return re.sub(r"\s+[Tt]arifi\s*$", "", name).strip()

    def extract_description(self) -> Optional[str]:
        """Извлечение краткого описания рецепта."""
        # Основной источник: div.quick-description-quote
        qdq = self.soup.find("div", class_="quick-description-quote")
        if qdq:
            p = qdq.find("p")
            text = self.clean_text(p.get_text() if p else qdq.get_text())
            if text:
                return text

        # Запасной вариант: og:description
        og_desc = self.soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            return self.clean_text(og_desc["content"])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате списка словарей."""
        ingredients = []

        # Основной источник: div.single-print-ingredients (печатный вариант)
        print_ingr = self.soup.find("div", class_="single-print-ingredients")
        if print_ingr:
            for pi in print_ingr.find_all("div", class_="print-ingredient"):
                name_span = pi.find("span", class_="ingredient-name")
                amount_span = pi.find("span", class_="ingredient-amount")

                # Пропускаем заголовки секций (нет имени ингредиента)
                if not name_span:
                    continue

                name_text = self.clean_text(name_span.get_text())
                if not name_text:
                    continue

                amount_raw = self.clean_text(amount_span.get_text()) if amount_span else ""
                amount, unit = self._parse_amount_unit(amount_raw)

                ingredients.append({
                    "name": name_text,
                    "amount": amount,
                    "unit": unit,
                })

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        # Запасной вариант: div.single-ingredients (мобильный/интерактивный вариант)
        single_ingr = self.soup.find("div", class_="single-ingredients")
        if single_ingr:
            for row in single_ingr.find_all("tr"):
                name_span = row.find("span", class_="ingredient-name")
                amount_span = row.find("span", class_="ingredient-amount")

                if not name_span:
                    continue

                name_text = self.clean_text(name_span.get_text())
                if not name_text:
                    continue

                amount_raw = self.clean_text(amount_span.get_text()) if amount_span else ""
                amount, unit = self._parse_amount_unit(amount_raw)

                ingredients.append({
                    "name": name_text,
                    "amount": amount,
                    "unit": unit,
                })

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    @staticmethod
    def _parse_amount_unit(raw: str):
        """
        Разбирает строку количества на (amount, unit).

        Примеры:
            "115 gr"                             → ("115", "gr")
            "2 çorba kaşığı"                     → ("2", "çorba kaşığı")
            "1 sap irice doğranmış"              → ("1", "sap")
            "1 (oda sıcaklığında)"               → ("1", None)
            "minicik bir parça (kabukları ...)"  → ("minicik bir parça", None)
            "7-8 dal"                            → ("7-8", "dal")
        """
        if not raw:
            return None, None

        # Убираем содержимое скобок (пояснения/уточнения)
        text = re.sub(r"\([^)]*\)", "", raw).strip()
        text = re.sub(r"\s{2,}", " ", text).strip()

        if not text:
            return raw.strip() or None, None

        # Попробуем выделить ведущее число (включая диапазоны и дроби)
        num_match = re.match(r"^([\d][\d\s\-/.,]*)", text)
        if num_match:
            num_str = num_match.group(1).strip().rstrip(",-. ")
            rest = text[len(num_match.group(1)):].strip()

            # Ищем единицу измерения в оставшемся тексте
            unit = None
            unit_m = _UNIT_PATTERN.match(rest)
            if unit_m:
                unit = unit_m.group(1).lower()
            elif rest and len(rest.split()) <= 3:
                # Если оставшийся фрагмент короткий — считаем его единицей
                unit = rest or None

            return num_str, unit

        # Числа нет — весь текст является описанием количества
        return text or None, None

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления."""
        steps = []

        # Основной источник: div.single-steps
        steps_div = self.soup.find("div", class_="single-steps")
        if steps_div:
            for step_cell in steps_div.find_all("div", class_="single-step-description-i"):
                # Берём текст параграфов внутри ячейки шага
                texts = []
                for p in step_cell.find_all("p"):
                    t = self.clean_text(p.get_text())
                    if t:
                        texts.append(t)
                if not texts:
                    t = self.clean_text(step_cell.get_text())
                    if t:
                        texts.append(t)
                if texts:
                    steps.append(" ".join(texts))

        if steps:
            return " ".join(steps)

        # Запасной вариант: JSON-LD recipeInstructions
        recipe = self._get_recipe_jsonld()
        if recipe:
            instructions = recipe.get("recipeInstructions", [])
            for step in instructions:
                if isinstance(step, dict):
                    t = self.clean_text(step.get("text", ""))
                elif isinstance(step, str):
                    t = self.clean_text(step)
                else:
                    t = ""
                if t:
                    steps.append(t)

        return " ".join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение основной кулинарной категории."""
        recipe = self._get_recipe_jsonld()
        if not recipe:
            return None

        category_raw = recipe.get("recipeCategory", "")
        if not category_raw:
            return None

        categories = [c.strip() for c in category_raw.split(",") if c.strip()]

        # Выбираем первую категорию, которая не является служебной меткой
        for cat in categories:
            if cat.lower() not in _GENERIC_CATEGORIES:
                return cat

        # Если все категории «общие», вернём первую
        return categories[0] if categories else None

    def extract_cook_time(self) -> Optional[str]:
        """Время приготовления (на сайте не выделяется отдельно)."""
        return None

    @staticmethod
    def _format_time_str(raw: str) -> Optional[str]:
        """
        Нормализует турецкую строку времени в человекочитаемый формат.

        Примеры:
            "45 dk"         → "45 minutes"
            "1 saat"        → "1 hour"
            "1 saat 30 dk"  → "1 hour 30 minutes"
        """
        raw = raw.strip()

        saat_match = re.search(r"(\d+[\d.,/-]*)\s*saat", raw, re.IGNORECASE)
        dk_match = re.search(r"(\d+[\d.,/-]*)\s*(?:dk|dakika|dak)", raw, re.IGNORECASE)

        hours_str = saat_match.group(1) if saat_match else None
        mins_str = dk_match.group(1) if dk_match else None

        parts = []
        if hours_str:
            try:
                h = int(hours_str)
                parts.append(f"{h} hour" if h == 1 else f"{h} hours")
            except ValueError:
                parts.append(f"{hours_str} hours")
        if mins_str:
            try:
                m = int(mins_str)
                parts.append(f"{m} minute" if m == 1 else f"{m} minutes")
            except ValueError:
                parts.append(f"{mins_str} minutes")

        if parts:
            return " ".join(parts)

        # Если не удалось распознать, возвращаем исходную строку
        return raw if raw else None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки (на сайте не отображается отдельно)."""
        return None

    def extract_total_time(self) -> Optional[str]:
        """Общее время приготовления из HTML-мета блока."""
        ct_li = self.soup.find("li", class_="single-meta-cooking-time")
        if ct_li:
            # Текст вида ": 45 dk" или ": 1 saat 30 dk"
            span = ct_li.find("span")
            raw = self.clean_text(span.get_text() if span else ct_li.get_text())
            # Убираем ведущие двоеточия и пробелы
            raw = re.sub(r"^[:\s]+", "", raw).strip()
            return self._format_time_str(raw) if raw else None
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов к рецепту."""
        # Ищем blockquote внутри основного контента
        content_div = self.soup.find("div", class_="single-content-self")
        if content_div:
            blockquotes = content_div.find_all("blockquote")
            notes_parts = []
            for bq in blockquotes:
                text = self.clean_text(bq.get_text(separator=" "))
                if text:
                    notes_parts.append(text)
            if notes_parts:
                return " ".join(notes_parts)

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из поля keywords в JSON-LD."""
        recipe = self._get_recipe_jsonld()
        if not recipe:
            return None

        keywords = recipe.get("keywords", "")
        if not keywords:
            return None

        # keywords — строка, разделённая запятыми
        tags = [t.strip() for t in keywords.split(",") if t.strip()]
        return ",".join(tags) if tags else None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта."""
        urls = []

        # og:image — основное изображение
        og_image = self.soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            urls.append(og_image["content"])

        # JSON-LD Recipe → image
        recipe = self._get_recipe_jsonld()
        if recipe:
            img = recipe.get("image")
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                for i in img:
                    if isinstance(i, str):
                        urls.append(i)
                    elif isinstance(i, dict):
                        urls.append(i.get("url") or i.get("contentUrl") or "")
            elif isinstance(img, dict):
                urls.append(img.get("url") or img.get("contentUrl") or "")

        # Дедупликация с сохранением порядка
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ",".join(unique_urls) if unique_urls else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта в едином формате проекта.
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_steps()
        category = self.extract_category()
        cook_time = self.extract_cook_time()
        notes = self.extract_notes()
        tags = self.extract_tags()

        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": cook_time,
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": self.extract_image_urls(),
        }


def main():
    """Точка входа: обрабатывает директорию preprocessed/kitcheninred_com."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "kitcheninred_com")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(KitcheninredComExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python kitcheninred_com.py")


if __name__ == "__main__":
    main()
