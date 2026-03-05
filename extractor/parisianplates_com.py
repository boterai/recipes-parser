"""
Экстрактор данных рецептов для сайта parisianplates.com
"""

import sys
from pathlib import Path
import json
import logging
import re
from typing import Optional, Union

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class ParisianPlatesExtractor(BaseRecipeExtractor):
    """Экстрактор для parisianplates.com"""

    # ------------------------------------------------------------------ #
    # Французские единицы измерения (в порядке убывания длины для жадного
    # совпадения)
    # ------------------------------------------------------------------ #
    _FR_UNITS = [
        r'cuill[eè]res?\s+à\s+soupe',
        r'cuill[eè]res?\s+à\s+caf[eé]',
        r'cuill\.\s+à\s+soupe',
        r'cuill\.\s+à\s+caf[eé]',
        r'c\.\s+à\s+soupe',
        r'c\.\s+à\s+caf[eé]',
        r'millilitres?',
        r'kilogrammes?',
        r'centilitres?',
        r'grammes?',
        r'litres?',
        r'kg',
        r'ml',
        r'cl',
        r'dl',
        r'g',
        r'l',
        r'gousses?',
        r'tranches?',
        r'pincées?',
        r'paquets?',
        r'bouquets?',
        r'bo[iî]tes?',
        r'verres?',
        r'tasses?',
        r'brins?',
        r'morceaux?',
        r'portions?',
        r'petits?',
        r'grandes?',
        r'gros(?:se)?',
        r'moyens?',
    ]

    # Скомпилированный паттерн для единиц
    _UNIT_RE = re.compile(
        r'^(' + r'|'.join(_FR_UNITS) + r')\b',
        re.IGNORECASE | re.UNICODE,
    )

    # Паттерн числа (целое, дробное, Unicode-дробь или смешанное)
    _FRAC_MAP = {
        '½': '1/2', '¼': '1/4', '¾': '3/4',
        '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
        '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
        '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5',
    }

    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение объекта Recipe из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    t = item.get('@type', '')
                    types = t if isinstance(t, list) else [t]
                    if 'Recipe' in types:
                        return item
            except (json.JSONDecodeError, AttributeError, TypeError):
                logger.warning("Не удалось разобрать JSON-LD скрипт", exc_info=True)
        return None

    # ------------------------------------------------------------------ #
    # Вспомогательные методы
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в строку вида "X minutes" / "X hours Y minutes"

        Args:
            duration: строка вида "PT20M" или "PT1H30M"

        Returns:
            Строка типа "20 minutes" или None
        """
        if not duration or not duration.startswith('PT'):
            return None
        body = duration[2:]
        hours = 0
        minutes = 0
        h_match = re.search(r'(\d+)H', body)
        m_match = re.search(r'(\d+)M', body)
        if h_match:
            hours = int(h_match.group(1))
        if m_match:
            minutes = int(m_match.group(1))
        total_minutes = hours * 60 + minutes
        if total_minutes == 0:
            return None
        if hours > 0 and minutes > 0:
            return f"{hours} hours {minutes} minutes"
        if hours > 0:
            return f"{hours} hours"
        return f"{total_minutes} minutes"

    @classmethod
    def _normalise_amount_str(cls, text: str) -> str:
        """Заменяет Unicode-дроби на ASCII-эквиваленты"""
        for uc, asc in cls._FRAC_MAP.items():
            text = text.replace(uc, asc)
        return text

    @staticmethod
    def _eval_amount(amount_str: str) -> Optional[Union[int, float, str]]:
        """
        Вычисляет числовое значение строки с дробью или целым числом.
        Поддерживает: "450", "1/2", "1 1/2", "0.5"

        Returns:
            int или float, либо исходная строка, если не удалось разобрать
        """
        amount_str = amount_str.strip()
        if not amount_str:
            return None
        try:
            # Целое
            if re.match(r'^\d+$', amount_str):
                return int(amount_str)
            # Дробь вида "1/2"
            if re.match(r'^\d+/\d+$', amount_str):
                num, den = amount_str.split('/')
                return int(num) / int(den)
            # Смешанное "1 1/2"
            mixed = re.match(r'^(\d+)\s+(\d+)/(\d+)$', amount_str)
            if mixed:
                whole, num, den = mixed.groups()
                return int(whole) + int(num) / int(den)
            # Десятичное
            return float(amount_str.replace(',', '.'))
        except (ValueError, ZeroDivisionError):
            return amount_str  # возвращаем как строку

    def _parse_french_ingredient(self, raw: str) -> dict:
        """
        Разбирает строку ингредиента на французском языке в структуру
        {"name": ..., "amount": ..., "unit": ...}.

        Args:
            raw: строка вида "450 grammes de poulet haché" и т.п.

        Returns:
            dict с ключами name, amount, unit
        """
        if not raw:
            return {"name": None, "amount": None, "unit": None}

        text = self._normalise_amount_str(raw).strip()

        # Нормализуем случаи без пробела между числом и единицей: "250g", "400ml"
        text = re.sub(
            r'^(\d+(?:[.,]\d+)?)(g|kg|ml|cl|dl|l)\b',
            r'\1 \2',
            text,
            flags=re.IGNORECASE,
        )

        # --- 1. Попытка извлечь числовое количество в начале строки ---
        amount_raw = None
        rest = text

        # Дробь со смешанным числом: "1 1/2", "2 3/4"
        mixed_m = re.match(r'^(\d+\s+\d+/\d+)\s+(.*)', text)
        if mixed_m:
            amount_raw = mixed_m.group(1).strip()
            rest = mixed_m.group(2).strip()
        else:
            # Простая дробь или число: "450", "1/2", "0.5"
            num_m = re.match(r'^([\d]+(?:[.,]\d+)?(?:\s*/\s*\d+)?)\s+(.*)', text)
            if num_m:
                amount_raw = num_m.group(1).strip()
                rest = num_m.group(2).strip()

        amount = self._eval_amount(amount_raw) if amount_raw else None

        # --- 2. Попытка извлечь единицу измерения ---
        # Единицу ищем только если было найдено числовое количество
        unit = None
        name_part = rest

        if rest and amount is not None:
            unit_m = self._UNIT_RE.match(rest)
            if unit_m:
                unit = unit_m.group(0).strip()
                name_part = rest[unit_m.end():].strip()

        # --- 3. Удаление предлогов "de"/"d'" перед названием ---
        name_part = re.sub(r"^d[e']?\s*", '', name_part, flags=re.IGNORECASE).strip()

        # --- 4. Удаление пояснений в скобках и хвостовых запятых ---
        name_part = re.sub(r'\s*\([^)]*\)', '', name_part)
        name_part = re.sub(r',.*$', '', name_part)
        name_part = name_part.strip(' ,;')

        # Если количество не найдено, но вся строка — это имя
        if amount is None and not unit and not name_part:
            name_part = text

        name = self.clean_text(name_part).lower() if name_part else self.clean_text(text).lower()

        return {
            "name": name if name else None,
            "amount": amount,
            "unit": unit,
        }

    # ------------------------------------------------------------------ #
    # Методы извлечения полей
    # ------------------------------------------------------------------ #

    @staticmethod
    def _clean_page_title(raw: str) -> str:
        """
        Очищает заголовок страницы от суффикса сайта и подзаголовков.

        Пример:
            "Pâtes en une casserole - prêtes en 15 minutes - Parisian Plates"
            → "Pâtes en une casserole"
        """
        # Убираем суффикс сайта "- Parisian Plates" (может идти после любых "-")
        title = re.sub(r'\s*[-|]\s*Parisian Plates.*$', '', raw, flags=re.IGNORECASE)
        # Убираем последний подзаголовок (если ещё есть " - что-то")
        title = re.sub(r'\s+-\s+[^-]+$', '', title)
        return title.strip()

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # 1. og:title — обычно содержит наиболее описательное название
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            cleaned = self._clean_page_title(og_title['content'])
            if cleaned:
                return self.clean_text(cleaned)

        # 2. JSON-LD Recipe name
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('name'):
            return self.clean_text(recipe['name'])

        # 3. <h2 class="recipe__title">
        recipe_title = self.soup.find('h2', class_=re.compile(r'recipe__title', re.I))
        if recipe_title:
            return self.clean_text(recipe_title.get_text())

        # 4. <h1>
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('description'):
            return self.clean_text(recipe['description'])

        # Fallback: meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        # Fallback: og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD recipeIngredient"""
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('recipeIngredient'):
            raw_list = recipe['recipeIngredient']
            ingredients = []
            for raw in raw_list:
                if not isinstance(raw, str):
                    continue
                parsed = self._parse_french_ingredient(raw)
                if parsed.get('name'):
                    ingredients.append(parsed)
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        # Fallback: HTML-список ингредиентов
        container = self.soup.find('div', id='recipe-ingredients')
        if container:
            items = container.find_all('span', class_='recipe__interact-list-content')
            if items:
                ingredients = []
                for item in items:
                    text = self.clean_text(item.get_text())
                    if text:
                        parsed = self._parse_french_ingredient(text)
                        if parsed.get('name'):
                            ingredients.append(parsed)
                if ingredients:
                    return json.dumps(ingredients, ensure_ascii=False)

        return None

    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций из JSON-LD recipeInstructions"""
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('recipeInstructions'):
            steps = []
            for idx, step in enumerate(recipe['recipeInstructions'], 1):
                if isinstance(step, dict):
                    text = step.get('text', '').strip()
                    if text:
                        steps.append(f"{idx}. {text}")
                elif isinstance(step, str) and step.strip():
                    steps.append(f"{idx}. {step.strip()}")
            if steps:
                return ' '.join(steps)

        # Fallback: HTML-список инструкций
        container = self.soup.find('ol', id='recipe-instructions') or \
                    self.soup.find('div', id='recipe-instructions')
        if container:
            items = container.find_all(['li', 'p'])
            steps = []
            for idx, item in enumerate(items, 1):
                text = self.clean_text(item.get_text(separator=' '))
                if text:
                    steps.append(f"{idx}. {text}")
            if steps:
                return ' '.join(steps)

        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда"""
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('recipeCategory'):
            return self.clean_text(recipe['recipeCategory'])

        # Fallback: хлебные крошки
        breadcrumb = self.soup.find(class_=re.compile(r'breadcrumb', re.I))
        if breadcrumb:
            links = breadcrumb.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('prepTime'):
            return self._parse_iso_duration(recipe['prepTime'])

        # Fallback: HTML
        item = self.soup.find('span', title=re.compile(r'pr[eé]parer|pr[eé]paration', re.I))
        if item:
            return self.clean_text(item.get_text())

        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('cookTime'):
            return self._parse_iso_duration(recipe['cookTime'])

        # Fallback: HTML
        item = self.soup.find('span', title=re.compile(r'cuire|cuisson', re.I))
        if item:
            return self.clean_text(item.get_text())

        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('totalTime'):
            return self._parse_iso_duration(recipe['totalTime'])

        # Fallback: HTML
        item = self.soup.find('span', title=re.compile(r'total|complet', re.I))
        if item:
            return self.clean_text(item.get_text())

        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов из секции Notes"""
        notes_ol = self.soup.find('ol', id='recipe-notes')
        if notes_ol:
            items = notes_ol.find_all('li')
            texts = [self.clean_text(li.get_text()).rstrip('.') for li in items
                     if li.get_text(strip=True)]
            if texts:
                return '. '.join(texts)

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из поля keywords в JSON-LD"""
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('keywords'):
            return self.clean_text(recipe['keywords'])

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls: list[str] = []

        # 1. Основное изображение из JSON-LD (первый элемент из image[])
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('image'):
            img_field = recipe['image']
            if isinstance(img_field, str):
                urls.append(img_field)
            elif isinstance(img_field, list):
                # Берём первый элемент (оригинал без CDN-ресайза)
                for url in img_field:
                    if isinstance(url, str) and 'cdn-cgi' not in url:
                        urls.append(url)
                        break
                # Если только CDN ссылки — берём первую
                if not urls and img_field:
                    first = img_field[0]
                    if isinstance(first, str):
                        urls.append(first)

        # 2. og:image (резерв)
        if not urls:
            og_img = self.soup.find('meta', property='og:image')
            if og_img and og_img.get('content'):
                urls.append(og_img['content'])

        # 3. Пошаговые изображения из тела статьи
        content_div = self.soup.find('div', class_=re.compile(r'content|article|body', re.I))
        if content_div:
            for img in content_div.find_all('img'):
                src = img.get('src') or ''
                # Только изображения из assets (не логотипы, не аватары)
                if '/assets/images/' in src and 'cdn-cgi' not in src:
                    full_url = src if src.startswith('http') else \
                        f"https://parisianplates.com{src}"
                    if full_url not in urls:
                        urls.append(full_url)

        if not urls:
            return None

        # Убираем дубликаты
        seen: set[str] = set()
        unique: list[str] = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                unique.append(u)

        return ','.join(unique)

    # ------------------------------------------------------------------ #
    # Публичный метод
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта в едином формате.
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception:
            logger.exception("Ошибка при извлечении dish_name")
            dish_name = None

        try:
            description = self.extract_description()
        except Exception:
            logger.exception("Ошибка при извлечении description")
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception:
            logger.exception("Ошибка при извлечении ingredients")
            ingredients = None

        try:
            instructions = self.extract_instructions()
        except Exception:
            logger.exception("Ошибка при извлечении instructions")
            instructions = None

        try:
            category = self.extract_category()
        except Exception:
            logger.exception("Ошибка при извлечении category")
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception:
            logger.exception("Ошибка при извлечении prep_time")
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception:
            logger.exception("Ошибка при извлечении cook_time")
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception:
            logger.exception("Ошибка при извлечении total_time")
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception:
            logger.exception("Ошибка при извлечении notes")
            notes = None

        try:
            tags = self.extract_tags()
        except Exception:
            logger.exception("Ошибка при извлечении tags")
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception:
            logger.exception("Ошибка при извлечении image_urls")
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


def main():
    """Точка входа для обработки директории с HTML-страницами"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "parisianplates_com")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ParisianPlatesExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python parisianplates_com.py")


if __name__ == "__main__":
    main()
