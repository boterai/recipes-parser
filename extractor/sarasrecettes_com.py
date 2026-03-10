"""
Экстрактор данных рецептов для сайта sarasrecettes.com
"""

import logging
import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


# Французские единицы измерения (от длинных к коротким, чтобы жадный поиск работал корректно)
FRENCH_UNITS = [
    r'cuillères?\s+à\s+café',
    r'cuillères?\s+à\s+soupe',
    r'tasses?',
    r'litres?',
    r'millilitres?',
    r'kilogrammes?',
    r'grammes?',
    r'cl',
    r'ml',
    r'kg',
    r'g\b',
    r'l\b',
    r'pincées?',
    r'brins?',
    r'tranches?',
    r'morceaux?',
    r'gros',
    r'grandes?',
    r'petites?',
    r'unités?',
    r'portions?',
]

# Скомпилируем общий паттерн для единиц
_UNIT_PATTERN = re.compile(
    r'^(' + '|'.join(FRENCH_UNITS) + r')\s+',
    re.IGNORECASE
)

# Паттерн для числа в начале строки (целые, дроби, смешанные)
_AMOUNT_PATTERN = re.compile(r'^([\d]+(?:\s*[/]\s*[\d]+)?(?:\s+[\d]+(?:\s*[/]\s*[\d]+)?)*)\s*')

# Замена дробных символов
_FRACTION_MAP = {
    '½': '1/2', '¼': '1/4', '¾': '3/4',
    '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
    '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
}


class SarasRecettesComExtractor(BaseRecipeExtractor):
    """Экстрактор для sarasrecettes.com"""

    # ------------------------------------------------------------------ #
    #  Вспомогательные методы                                             #
    # ------------------------------------------------------------------ #

    def _get_json_ld(self) -> Optional[dict]:
        """Возвращает Recipe-объект из JSON-LD или None."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
            except json.JSONDecodeError:
                continue

            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                t = item.get('@type', '')
                types = t if isinstance(t, list) else [t]
                if 'Recipe' in types:
                    return item

        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в строку «N minutes».

        Примеры: «PT15M» → «15 minutes», «PT1H30M» → «90 minutes».
        """
        if not duration or not isinstance(duration, str):
            return None
        duration = duration.upper()
        if not duration.startswith('PT'):
            return None
        body = duration[2:]
        hours = 0
        minutes = 0
        h = re.search(r'(\d+)H', body)
        m = re.search(r'(\d+)M', body)
        if h:
            hours = int(h.group(1))
        if m:
            minutes = int(m.group(1))
        total = hours * 60 + minutes
        if total <= 0:
            return None
        return f"{total} minutes"

    def _parse_french_ingredient(self, raw: str) -> Optional[dict]:
        """
        Разбирает строку французского ингредиента в структуру
        {name, amount, unit}.

        Формат ввода примеры:
          «2 ½ tasses (312.5 g) de farine ordinaire.»
          «3 gros œufs.»
          «1/4 tasse d'édulcorant au choix (sirop d'érable conseillé).»
          «Spray de cuisson.»
        """
        if not raw:
            return None

        text = raw.strip().rstrip('.')

        # Заменяем Unicode-дроби
        for sym, repl in _FRACTION_MAP.items():
            text = text.replace(sym, repl)

        # Извлекаем количество из начала строки
        amount_str: Optional[str] = None
        rest = text

        amount_match = _AMOUNT_PATTERN.match(text)
        if amount_match:
            amount_str = amount_match.group(1).strip()
            rest = text[amount_match.end():]

        # Убираем скобочную альтернативу сразу после количества/единицы
        # (например, «(312.5 g)» или «(1 bâton / 113 g)»)
        rest = re.sub(r'^\s*\([^)]*\)\s*', '', rest)

        # Ищем единицу измерения
        unit: Optional[str] = None
        unit_match = _UNIT_PATTERN.match(rest)
        if unit_match:
            unit = unit_match.group(1)
            rest = rest[unit_match.end():]

        # Убираем скобочный вариант после единицы
        rest = re.sub(r'^\s*\([^)]*\)\s*', '', rest)

        # Убираем французский предлог «de» или «d'» перед названием
        rest = re.sub(r"^d[e']?\s*", '', rest, flags=re.IGNORECASE)

        name = self.clean_text(rest).rstrip('.,;:')

        # Если единица не найдена и нет предлога «de», весь «rest» — это название.
        # Убираем скобку с числовым значением в конце названия
        # (напр., «bananes moyennes-grandes très mûres (1 tasse écrasée)»)
        if unit is None and amount_str:
            name = re.sub(r'\s*\([^)]*\d[^)]*\)\s*$', '', name).strip()

        if not name:
            logger.warning("Не удалось извлечь название из ингредиента: %s", raw)
            return None

        return {
            "name": name,
            "amount": amount_str,
            "unit": unit,
        }

    # ------------------------------------------------------------------ #
    #  Методы извлечения отдельных полей                                  #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда."""
        ld = self._get_json_ld()
        if ld and ld.get('name'):
            return self.clean_text(ld['name'])

        title_tag = self.soup.find('h2', class_='recipe__title')
        if title_tag:
            return self.clean_text(title_tag.get_text())

        og = self.soup.find('meta', property='og:title')
        if og and og.get('content'):
            title = og['content']
            title = re.sub(r'\s*[-|].*Sara.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта."""
        ld = self._get_json_ld()
        if ld and ld.get('description'):
            return self.clean_text(ld['description'])

        # Первый <p> внутри секции рецепта
        recipe_section = self.soup.find('section', id='recipe')
        if not recipe_section:
            recipe_section = self.soup.find('section', class_='recipe')
        if recipe_section:
            wrapper = recipe_section.find('div', class_='recipe__wrapper')
            if wrapper:
                p = wrapper.find('p')
                if p:
                    return self.clean_text(p.get_text())

        meta = self.soup.find('meta', {'name': 'description'})
        if meta and meta.get('content'):
            return self.clean_text(meta['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном виде."""
        raw_ingredients: list[str] = []

        # Приоритет — JSON-LD
        ld = self._get_json_ld()
        if ld and ld.get('recipeIngredient'):
            raw_ingredients = ld['recipeIngredient']

        # Фолбек — HTML div#recipe-ingredients
        if not raw_ingredients:
            ing_div = self.soup.find('div', id='recipe-ingredients')
            if ing_div:
                spans = ing_div.find_all('span', class_='recipe__interact-list-content')
                raw_ingredients = [s.get_text(strip=True) for s in spans]

        if not raw_ingredients:
            return None

        parsed = []
        for raw in raw_ingredients:
            item = self._parse_french_ingredient(raw)
            if item:
                parsed.append(item)

        return json.dumps(parsed, ensure_ascii=False) if parsed else None

    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению."""
        steps: list[str] = []

        # Приоритет — JSON-LD
        ld = self._get_json_ld()
        if ld and ld.get('recipeInstructions'):
            instructions = ld['recipeInstructions']
            for step in instructions:
                if isinstance(step, dict):
                    text = step.get('text', '')
                elif isinstance(step, str):
                    text = step
                else:
                    continue
                text = self.clean_text(text)
                if text:
                    steps.append(text)

        # Фолбек — HTML div#recipe-instructions
        if not steps:
            instr_div = self.soup.find('div', id='recipe-instructions')
            if instr_div:
                for p in instr_div.find_all('p', class_='recipe__interact-list-content'):
                    text = self.clean_text(p.get_text())
                    if text:
                        steps.append(text)

        if not steps:
            return None

        return ' '.join(steps)

    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта."""
        ld = self._get_json_ld()
        if ld and ld.get('recipeCategory'):
            cat = ld['recipeCategory']
            return self.clean_text(cat if isinstance(cat, str) else ', '.join(cat))

        info_div = self.soup.find('div', id='recipe-info')
        if info_div:
            for a in info_div.find_all('a', href=True):
                if '/categories/' in a['href']:
                    return self.clean_text(a.get_text())

        return None

    def _extract_time_from_html(self, label_keywords: list[str]) -> Optional[str]:
        """Поиск времени в блоке recipe__times по ключевым словам метки."""
        times_div = self.soup.find('div', class_='recipe__times')
        if not times_div:
            return None
        for item in times_div.find_all('div', class_='recipe__times-item'):
            strong = item.find('strong')
            highlight = item.find('span', class_='recipe__highlight')
            if strong and highlight:
                label = strong.get_text(strip=True).lower()
                if any(kw in label for kw in label_keywords):
                    return self.clean_text(highlight.get_text()).lower()
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки."""
        ld = self._get_json_ld()
        if ld and ld.get('prepTime'):
            return self._parse_iso_duration(ld['prepTime'])
        return self._extract_time_from_html(['préparation', 'prep'])

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления."""
        ld = self._get_json_ld()
        if ld and ld.get('cookTime'):
            return self._parse_iso_duration(ld['cookTime'])
        return self._extract_time_from_html(['cuisson', 'cook'])

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени."""
        ld = self._get_json_ld()
        if ld and ld.get('totalTime'):
            return self._parse_iso_duration(ld['totalTime'])
        return self._extract_time_from_html(['total'])

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов."""
        notes_ol = self.soup.find('ol', id='recipe-notes')
        if not notes_ol:
            notes_ol = self.soup.find(id='recipe-notes')
        if notes_ol:
            items = [self.clean_text(li.get_text()) for li in notes_ol.find_all('li')]
            items = [i for i in items if i]
            if items:
                return ' '.join(items)
        return None

    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов: категория + диетические метки + кухня.
        """
        tags: list[str] = []

        info_div = self.soup.find('div', id='recipe-info')
        if info_div:
            for wrapper in info_div.find_all('div', class_='icon-wrapper'):
                strong = wrapper.find('strong')
                if not strong:
                    continue
                label = strong.get_text(strip=True).lower()

                # Категория
                if 'catégorie' in label or 'categorie' in label:
                    a = wrapper.find('a')
                    if a:
                        tags.append(self.clean_text(a.get_text()))

                # Диетические метки (могут быть через запятую)
                elif 'régime' in label or 'regime' in label:
                    span = wrapper.find('span', class_='recipe__highlight')
                    if span:
                        for diet in span.get_text(strip=True).split(','):
                            d = self.clean_text(diet)
                            if d:
                                tags.append(d)

                # Кухня
                elif 'cuisine' in label:
                    span = wrapper.find('span', class_='recipe__highlight')
                    if span:
                        tags.append(self.clean_text(span.get_text()))

        # Добавляем ключевые слова из JSON-LD (первые значимые)
        ld = self._get_json_ld()
        if ld and ld.get('keywords'):
            kw_str = ld['keywords']
            keywords = [self.clean_text(k) for k in kw_str.split(',') if self.clean_text(k)]
            for kw in keywords[:3]:
                if kw not in tags:
                    tags.append(kw)

        if not tags:
            return None

        # Убираем дубликаты, сохраняя порядок
        seen: set[str] = set()
        unique: list[str] = []
        for t in tags:
            key = t.lower()
            if key not in seen:
                seen.add(key)
                unique.append(t)

        return ', '.join(unique)

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта."""
        urls: list[str] = []

        # JSON-LD (самый надёжный источник)
        ld = self._get_json_ld()
        if ld and ld.get('image'):
            img = ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend(i for i in img if isinstance(i, str))
            elif isinstance(img, dict):
                u = img.get('url') or img.get('contentUrl')
                if u:
                    urls.append(u)

        # og:image как запасной вариант
        if not urls:
            og = self.soup.find('meta', property='og:image')
            if og and og.get('content'):
                urls.append(og['content'])

        # Изображения из статьи (пошаговые фото и т.д.)
        article = self.soup.find('article', class_='article')
        if article:
            for img in article.find_all('img', src=True):
                src = img['src']
                if src.startswith('/assets/images/') or src.startswith('https://'):
                    if src.startswith('/'):
                        src = 'https://sarasrecettes.com' + src
                    if src not in urls:
                        urls.append(src)

        if not urls:
            return None

        # Убираем дубликаты, сохраняя порядок
        seen: set[str] = set()
        unique: list[str] = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique)

    # ------------------------------------------------------------------ #
    #  Главный метод                                                       #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта.
        """
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
        except Exception as exc:
            logger.error("Ошибка при парсинге %s: %s", self.html_path, exc, exc_info=True)
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
                "tags": None,
                "image_urls": None,
            }

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


def main() -> None:
    """Точка входа: обрабатывает директорию preprocessed/sarasrecettes_com."""
    import os
    base = Path(__file__).parent.parent
    directory = base / "preprocessed" / "sarasrecettes_com"
    if directory.exists() and directory.is_dir():
        process_directory(SarasRecettesComExtractor, str(directory))
    else:
        print(f"Директория не найдена: {directory}")


if __name__ == "__main__":
    main()
