"""
Экстрактор данных рецептов для сайта fitline.com
"""

import logging
import sys
import json
import re
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class FitlineComExtractor(BaseRecipeExtractor):
    """Экстрактор для fitline.com"""

    # Unicode дроби → строковые представления
    _FRACTION_MAP = {
        '½': '1/2', '¼': '1/4', '¾': '3/4',
        '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
        '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
        '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5',
    }

    # Единицы измерения (порядок важен: сначала длинные совпадения)
    _UNITS = [
        # Метрические
        'kg', 'g', 'ml', 'l',
        # Английские объёмные
        'tbsp', 'tsp', 'cup', 'cups', 'oz', 'lb', 'lbs',
        # Корейские
        '큰술', '작은술', '컵', '개', '장', '방울', '줄기', '조각',
        '봉지', '캔', '묶음', '인분', '팩', '쪽',
    ]

    def _extract_story_data(self) -> Optional[dict]:
        """
        Извлечение данных рецепта из Next.js RSC payload скриптов
        (self.__next_f.push([1, "..."]) содержит story content Storyblok)
        """
        scripts = self.soup.find_all('script')
        for script in scripts:
            raw = script.string
            if not raw:
                continue

            m = re.match(r'self\.__next_f\.push\(\[1,(.+)\]\)\s*$', raw.strip(), re.DOTALL)
            if not m:
                continue

            try:
                payload_str = json.loads(m.group(1))
            except (json.JSONDecodeError, ValueError):
                continue

            if not isinstance(payload_str, str) or '"story"' not in payload_str:
                continue

            # Формат payload: "20:[...JSON...]"  — убираем числовой префикс
            colon_idx = payload_str.find(':')
            if colon_idx < 0:
                continue

            json_part = payload_str[colon_idx + 1:]
            try:
                rsc_data = json.loads(json_part)
            except (json.JSONDecodeError, ValueError):
                continue

            # Обходим RSC-структуру: ищем dict с ключом "story"
            story = self._find_story_in_rsc(rsc_data)
            if story:
                return story

        return None

    def _find_story_in_rsc(self, obj) -> Optional[dict]:
        """Рекурсивный поиск объекта 'story' в RSC-данных"""
        if isinstance(obj, dict):
            if 'story' in obj:
                return obj['story']
            for v in obj.values():
                result = self._find_story_in_rsc(v)
                if result:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = self._find_story_in_rsc(item)
                if result:
                    return result
        return None

    # ------------------------------------------------------------------
    # Разбор ингредиентов
    # ------------------------------------------------------------------

    def _parse_ingredient(self, text: str) -> dict:
        """
        Разбирает строку ингредиента на поля name / amount / unit.

        Примеры входных строк:
          "다진 닭고기 100g"
          "상추잎 2장 (큰 사이즈)"
          "마늘가루 ½작은술"
          "소금, 후추 약간"
          "FitLine microSolve⁺ Omega 3 37방울"
        """
        if not text:
            return {"name": None, "amount": None, "unit": None}

        text = text.strip()

        # Удаляем скобочные пояснения в конце: "(큰 사이즈)", "(잘게 썬 것)" и т.п.
        text_no_paren = re.sub(r'\s*\([^)]*\)\s*$', '', text).strip()

        # Удаляем запятые с пояснением в конце: ", 깍둑썰기"
        text_no_paren = re.sub(r'\s*,\s*[가-힣\w]+썰기\s*$', '', text_no_paren).strip()

        # Заменяем Unicode-дроби на строковые обозначения
        text_for_parse = text_no_paren
        for frac, replacement in self._FRACTION_MAP.items():
            text_for_parse = text_for_parse.replace(frac, replacement)

        name, amount, unit = self._split_ingredient(text_for_parse)

        # Восстанавливаем Unicode-дроби в amount
        if amount:
            for frac, replacement in self._FRACTION_MAP.items():
                amount = amount.replace(replacement, frac)

        return {
            "name": name.strip() if name else None,
            "amount": amount.strip() if amount else None,
            "unit": unit.strip() if unit else None,
        }

    def _split_ingredient(self, text: str):
        """
        Возвращает (name, amount, unit).

        Алгоритм:
        1. Проверяем наличие числа + единицы в конце строки.
        2. Если нашли — имя = всё до числа, amount = число, unit = единица.
        3. Если нет числа, но есть слово "약간" (a little) — amount = "약간".
        4. Иначе всё — имя.
        """
        units_pattern = '|'.join(re.escape(u) for u in self._UNITS)

        # Паттерн: «имя» «[пробел] число [единица]» в конце строки
        # число может быть: 100, 1/2, .5 и т.д.
        number_re = r'(\d+(?:[./]\d+)?)'
        pattern = (
            r'^(.+?)\s+'
            + number_re
            + r'\s*(' + units_pattern + r')?\s*$'
        )

        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            name, amount, unit = match.group(1), match.group(2), match.group(3)
            return name, amount, unit or None

        # Нет числа — ищем «약간» (немного) или аналогичные слова в конце
        misc_amount_re = r'^(.+?)\s+(약간|적당량|조금|한줌|필요한\s*만큼)\s*$'
        match2 = re.match(misc_amount_re, text)
        if match2:
            return match2.group(1), match2.group(2), None

        # Ничего не нашли
        return text, None, None

    # ------------------------------------------------------------------
    # Методы извлечения данных
    # ------------------------------------------------------------------

    def extract_dish_name(self, content: dict) -> Optional[str]:
        """Название блюда из story.content.title"""
        title = content.get('title')
        if title:
            return self.clean_text(title)
        return None

    def extract_description(self, content: dict) -> Optional[str]:
        """Краткое описание из story.content.caption (анонс)"""
        caption = content.get('caption')
        if caption:
            return self.clean_text(caption)
        return None

    def extract_ingredients(self, content: dict) -> Optional[str]:
        """
        Ингредиенты из story.content.ingredients.
        Каждый элемент содержит поле "text" в виде строки.
        Возвращает JSON-строку списка [{name, amount, unit}].
        """
        raw_ingredients = content.get('ingredients', [])
        if not raw_ingredients:
            logger.warning("Поле 'ingredients' отсутствует или пусто")
            return None

        parsed = []
        for item in raw_ingredients:
            text = item.get('text', '') if isinstance(item, dict) else str(item)
            text = self.clean_text(text)
            if text:
                parsed.append(self._parse_ingredient(text))

        return json.dumps(parsed, ensure_ascii=False) if parsed else None

    def extract_instructions(self, content: dict) -> Optional[str]:
        """
        Шаги приготовления из story.content.preparation.
        Возвращает строку с нумерованными шагами.
        """
        steps = content.get('preparation', [])
        if not steps:
            logger.warning("Поле 'preparation' отсутствует или пусто")
            return None

        lines = []
        for i, step in enumerate(steps, start=1):
            text = step.get('text', '') if isinstance(step, dict) else str(step)
            text = self.clean_text(text)
            if text:
                lines.append(f"{i}. {text}")

        return '\n'.join(lines) if lines else None

    def extract_category(self, content: dict) -> Optional[str]:
        """Категория из story.content.type (список строк)"""
        type_list = content.get('type', [])
        if isinstance(type_list, list) and type_list:
            return ', '.join(self.clean_text(t) for t in type_list if t)
        if isinstance(type_list, str) and type_list:
            return self.clean_text(type_list)
        return None

    def extract_prep_time(self, content: dict) -> Optional[str]:
        """Время подготовки из story.content.preparationTime (минуты)"""
        prep_time = content.get('preparationTime')
        if prep_time is not None:
            try:
                minutes = int(prep_time)
                return f"{minutes} minutes"
            except (ValueError, TypeError):
                return self.clean_text(str(prep_time))
        return None

    def extract_image_urls(self, content: dict) -> Optional[str]:
        """URL изображения из story.content.image.filename"""
        image = content.get('image', {})
        if isinstance(image, dict):
            filename = image.get('filename')
            if filename:
                return filename
        return None

    def extract_tags(self, story: dict) -> Optional[str]:
        """Теги из story.tag_list"""
        tag_list = story.get('tag_list', [])
        if isinstance(tag_list, list) and tag_list:
            return ' ,'.join(self.clean_text(t) for t in tag_list if t)
        return None

    # ------------------------------------------------------------------
    # Основной метод
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            dict с полями: dish_name, description, ingredients, instructions,
            category, prep_time, cook_time, total_time, notes, image_urls, tags
        """
        story = self._extract_story_data()

        if story is None:
            logger.warning("Не удалось найти данные рецепта (story) в HTML: %s", self.html_path)
            return {
                "dish_name": None,
                "description": None,
                "ingredients": None,
                "instructions": None,
                "category": None,
                "prep_time": None,
                "cook_time": None,
                "total_time": None,
                "notes": None,
                "image_urls": None,
                "tags": None,
            }

        content = story.get('content', {})

        return {
            "dish_name": self.extract_dish_name(content),
            "description": self.extract_description(content),
            "ingredients": self.extract_ingredients(content),
            "instructions": self.extract_instructions(content),
            "category": self.extract_category(content),
            "prep_time": self.extract_prep_time(content),
            "cook_time": None,
            "total_time": None,
            "notes": None,
            "image_urls": self.extract_image_urls(content),
            "tags": self.extract_tags(story),
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    preprocessed_dir = Path("preprocessed") / "fitline_com"

    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        process_directory(FitlineComExtractor, str(preprocessed_dir))
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python fitline_com.py")


if __name__ == "__main__":
    main()
