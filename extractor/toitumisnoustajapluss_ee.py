"""
Экстрактор данных рецептов для сайта toitumisnoustajapluss.ee
"""

import sys
import logging
import json
import re
from pathlib import Path
from typing import Optional, List

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class ToitumisnoustajaplussEeExtractor(BaseRecipeExtractor):
    """Экстрактор для toitumisnoustajapluss.ee"""

    # Единицы измерения (эстонские и общепринятые)
    _UNITS_PATTERN = (
        r'kuhjaga\s+spl'   # heaped tablespoon (must come before spl)
        r'|spl'            # tablespoon (supilusikas)
        r'|tl'             # teaspoon (teelusikas)
        r'|peotäis'        # handful
        r'|punt'           # bunch
        r'|purk'           # can / jar
        r'|pakk'           # package
        r'|kg'             # kilogram
        r'|g'              # gram
        r'|ml'             # millilitre
        r'|l'              # litre
    )

    @staticmethod
    def clean_text(text: str) -> str:
        """Очистка текста с дополнительной нормализацией дефисов/тире."""
        text = BaseRecipeExtractor.clean_text(text)
        if text:
            # Убираем пробелы вокруг тире/дефиса в числовых диапазонах
            # Например: «2 – 3» → «2–3», «30 – 35» → «30–35»
            text = re.sub(r'(\d)\s+([–—\-])\s+(\d)', r'\1\2\3', text)
        return text

    def _get_ingredients_section(self):
        """Возвращает sticky-div с разделом ингредиентов."""
        content_inner = self.soup.find('div', class_='recipe__content-inner')
        if not content_inner:
            return None
        return content_inner.find('div', class_='sticky')

    def _get_instructions_section(self):
        """Возвращает div с разделом инструкций (col-span-2)."""
        return self.soup.find('div', class_='col-span-2')

    # ------------------------------------------------------------------
    # dish_name
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Название блюда из <h1 class='recipe__header-title'>."""
        h1 = self.soup.find('h1', class_='recipe__header-title')
        if h1:
            return self.clean_text(h1.get_text())

        # Запасной вариант: og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*-\s*Toitumisnõustaja\+?.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)

        return None

    # ------------------------------------------------------------------
    # description
    # ------------------------------------------------------------------

    def extract_description(self) -> Optional[str]:
        """Описание рецепта (на этом сайте обычно отсутствует)."""
        return None

    # ------------------------------------------------------------------
    # ingredients
    # ------------------------------------------------------------------

    def _parse_ingredient(
        self, raw_text: str, label_suffix: Optional[str] = None
    ) -> List[dict]:
        """
        Разбирает строку ингредиента в структурированный формат.

        Обрабатывает случаи вида:
          - «300 g veisehakkliha»
          - «1 väike sibul või pool sibulat»
          - «sool, pipar»  → два ингредиента

        Args:
            raw_text: строка из <li>
            label_suffix: суффикс для имени (например, «kuivpuruks»)

        Returns:
            Список словарей {"name": ..., "amount": ..., "unit": ...}
        """
        text = self.clean_text(raw_text)
        if not text:
            return []

        # Запятые без цифр → несколько ингредиентов («sool, pipar»)
        if ',' in text and not re.search(r'\d', text):
            results = []
            for part in text.split(','):
                part = part.strip()
                if part:
                    name = f"{part} ({label_suffix})" if label_suffix else part
                    results.append({"name": name, "amount": None, "unit": None})
            return results

        # Нормализация: «kuhjaga spl» → «spl»; «kuhjaga tl» → «tl»
        text = re.sub(r'\bkuhjaga\s+(spl|tl)\b', r'\1', text)

        # Замена Unicode-дробей на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
        }
        for frac, dec in fraction_map.items():
            text = text.replace(frac, dec)

        # Десятичная запятая → точка  (например «0,5» → «0.5»)
        text = re.sub(r'(\d),(\d)', r'\1.\2', text)

        # Паттерн: [количество] [единица] название
        # Количество: цифры, точка, дефис/тире, «c» (для «1c2» = кодировка дроби)
        pattern = (
            r'^([\d.,/c\s]+(?:\s*[–\-]\s*[\d.,/c]+)?)'   # количество
            r'(?:\s+(' + self._UNITS_PATTERN + r'))?'      # единица (опц.)
            r'\s+(.+)$'                                    # название
        )
        m = re.match(pattern, text)

        if m:
            amount_raw = m.group(1).strip()
            unit = m.group(2)
            name_raw = m.group(3).strip()

            # Удаляем скобочные уточнения из имени
            name = re.sub(r'\([^)]*\)', '', name_raw).strip()
            name = re.sub(r'\s+', ' ', name).strip() or name_raw

            if label_suffix:
                name = f"{name} ({label_suffix})"

            # Нормализация единицы (убираем «kuhjaga» если оно попало в группу)
            if unit:
                unit = re.sub(r'^kuhjaga\s+', '', unit).strip()

            return [{"name": name, "unit": unit, "amount": amount_raw}]

        # Нет числа в начале — проверяем, начинается ли строка с единицы измерения
        # Пример: «punt lehtsalatit» → amount: «punt», unit: None, name: «lehtsalatit»
        m_unit_first = re.match(
            r'^(' + self._UNITS_PATTERN + r')\s+(.+)$', text
        )
        if m_unit_first:
            unit_as_amount = re.sub(r'^kuhjaga\s+', '', m_unit_first.group(1)).strip()
            name_raw = m_unit_first.group(2).strip()
            name = re.sub(r'\([^)]*\)', '', name_raw).strip() or name_raw
            name = re.sub(r'\s+', ' ', name).strip()
            if label_suffix:
                name = f"{name} ({label_suffix})"
            return [{"name": name, "unit": None, "amount": unit_as_amount}]

        # Просто название без количества
        name = re.sub(r'\([^)]*\)', '', text).strip() or text
        if label_suffix:
            name = f"{name} ({label_suffix})"
        return [{"name": name, "unit": None, "amount": None}]

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из раздела «Koostisosad»."""
        sticky = self._get_ingredients_section()
        if not sticky:
            logger.warning("toitumisnoustajapluss_ee: ingredients section not found")
            return None

        # Ищем h2 «Koostisosad»
        koostisosad_h2 = None
        for h2 in sticky.find_all('h2'):
            if 'koostisosad' in h2.get_text(strip=True).lower():
                koostisosad_h2 = h2
                break

        if not koostisosad_h2:
            logger.warning("toitumisnoustajapluss_ee: Koostisosad h2 not found")
            return None

        all_ingredients: List[dict] = []
        current_label: Optional[str] = None

        # Перебираем сиблингов h2 внутри родительского тега
        parent = koostisosad_h2.parent
        children = list(parent.children)
        try:
            start_idx = children.index(koostisosad_h2) + 1
        except ValueError:
            start_idx = 0

        for elem in children[start_idx:]:
            if not hasattr(elem, 'name') or not elem.name:
                continue

            if elem.name == 'ul':
                for li in elem.find_all('li'):
                    # Удаляем изображения из текста ингредиента
                    for img in li.find_all('img'):
                        img.decompose()
                    li_text = li.get_text(separator=' ', strip=True)
                    parsed = self._parse_ingredient(li_text, current_label)
                    all_ingredients.extend(parsed)

            elif elem.name == 'p':
                # Проверяем: жирный текст, заканчивающийся «:» → метка раздела
                strong = elem.find('strong')
                if strong:
                    label_text = strong.get_text(strip=True)
                    if label_text.rstrip(':').strip():
                        # Берём первое значимое слово как суффикс (строчными)
                        first_word = re.split(r'[,\s]', label_text)[0].lower().strip(':')
                        current_label = first_word if first_word else None
                    else:
                        current_label = None
                else:
                    current_label = None

        return json.dumps(all_ingredients, ensure_ascii=False) if all_ingredients else None

    # ------------------------------------------------------------------
    # instructions
    # ------------------------------------------------------------------

    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций из раздела «Valmistamine»."""
        instructions_div = self._get_instructions_section()
        if not instructions_div:
            logger.warning("toitumisnoustajapluss_ee: instructions section not found")
            return None

        # Ищем h2 «Valmistamine»
        valmistamine_h2 = None
        for h2 in instructions_div.find_all('h2'):
            if 'valmistamine' in h2.get_text(strip=True).lower():
                valmistamine_h2 = h2
                break

        if not valmistamine_h2:
            logger.warning("toitumisnoustajapluss_ee: Valmistamine h2 not found")
            return None

        steps: List[str] = []

        parent = valmistamine_h2.parent
        children = list(parent.children)
        try:
            start_idx = children.index(valmistamine_h2) + 1
        except ValueError:
            start_idx = 0

        for elem in children[start_idx:]:
            if not hasattr(elem, 'name') or not elem.name:
                continue

            if elem.name == 'ul':
                for li in elem.find_all('li'):
                    # Удаляем изображения из шага
                    for img in li.find_all('img'):
                        img.decompose()
                    step_text = li.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    if step_text:
                        steps.append(step_text)

        return ' '.join(steps) if steps else None

    # ------------------------------------------------------------------
    # notes
    # ------------------------------------------------------------------

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок.
        Источники:
          - жирные параграфы (<strong> в <p>) после инструкций;
          - курсивные (<em>) элементы внутри шагов.
        """
        instructions_div = self._get_instructions_section()
        if not instructions_div:
            return None

        notes: List[str] = []

        # Жирные параграфы (<p><strong>…</strong></p>)
        for p in instructions_div.find_all('p'):
            strong_parts: List[str] = []
            for strong in p.find_all('strong'):
                t = strong.get_text(separator=' ', strip=True)
                if t:
                    strong_parts.append(t)
            if strong_parts:
                combined = self.clean_text(' '.join(strong_parts))
                if combined:
                    notes.append(combined)

        # Курсивные подсказки в шагах (<em>…</em> внутри <li>)
        for li in instructions_div.find_all('li'):
            for em in li.find_all('em'):
                em_text = em.get_text(strip=True).strip('()')
                em_text = self.clean_text(em_text)
                if em_text:
                    notes.append(em_text)

        return ' '.join(notes) if notes else None

    # ------------------------------------------------------------------
    # time
    # ------------------------------------------------------------------

    def _extract_html_time(self) -> Optional[str]:
        """Читает единственное значение времени из sticky-sidebar и нормализует."""
        sticky = self._get_ingredients_section()
        if not sticky:
            return None
        span = sticky.find('span', class_='ml-4')
        if span:
            time_str = span.get_text(strip=True)
            # Нормализуем сокращения: «45 min» → «45 minutes», «1 tund» → «1 hour»
            time_str = re.sub(r'\bmin\b', 'minutes', time_str)
            time_str = re.sub(r'\btundi?\b', 'hours', time_str)
            return time_str.strip()
        return None

    def _extract_cook_time_from_instructions(self) -> Optional[str]:
        """
        Пытается извлечь время готовки из текста инструкций.
        Ищет паттерн «X minutiks ahju» (X минут в духовке).
        """
        instructions_div = self._get_instructions_section()
        if not instructions_div:
            return None

        text = instructions_div.get_text(separator=' ')
        m = re.search(
            r'(\d+\s*[–\-]\s*\d+|\d+)\s+minutiks?\s+ahju',
            text,
            re.IGNORECASE,
        )
        if m:
            time_val = re.sub(r'\s+', '', m.group(1))
            return f"{time_val} minutes"
        return None

    def extract_prep_time(self) -> Optional[str]:
        """
        Время подготовки.
        Используется, когда не удалось извлечь cook_time из инструкций.
        """
        cook_time = self._extract_cook_time_from_instructions()
        if cook_time:
            return None
        return self._extract_html_time()

    def extract_cook_time(self) -> Optional[str]:
        """Время готовки из инструкций (паттерн «X minutiks ahju»)."""
        return self._extract_cook_time_from_instructions()

    def extract_total_time(self) -> Optional[str]:
        """
        Общее время.
        Используется только когда cook_time извлечён из инструкций.
        """
        cook_time = self._extract_cook_time_from_instructions()
        if not cook_time:
            return None
        return self._extract_html_time()

    # ------------------------------------------------------------------
    # category
    # ------------------------------------------------------------------

    def extract_category(self) -> Optional[str]:
        """Категория не присутствует на этих страницах."""
        return None

    # ------------------------------------------------------------------
    # tags
    # ------------------------------------------------------------------

    def extract_tags(self) -> Optional[str]:
        """
        Теги из блока заголовка рецепта.
        Текст после <h1> в div.recipe__header-content содержит теги вида
        «◻️ Gluteenivaba», «◻️ Vegan».
        """
        header_content = self.soup.find('div', class_='recipe__header-content')
        if not header_content:
            return None

        # Собираем текст, исключая содержимое h1
        h1 = header_content.find('h1')
        full_text = header_content.get_text(separator='\n')
        if h1:
            full_text = full_text.replace(h1.get_text(), '', 1)

        tags: List[str] = []
        for line in full_text.splitlines():
            # Убираем эмодзи и специальные символы в начале строки
            tag = re.sub(r'^[\W\s]+', '', line).strip()
            if tag:
                tags.append(tag)

        return ', '.join(tags) if tags else None

    # ------------------------------------------------------------------
    # image_urls
    # ------------------------------------------------------------------

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта."""
        seen: set = set()
        urls: List[str] = []

        def _add(url: Optional[str]) -> None:
            if url and url.startswith('http') and url not in seen:
                seen.add(url)
                urls.append(url)

        # og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image:
            _add(og_image.get('content'))

        # Изображения в блоке рецепта
        recipe_div = self.soup.find('div', class_='recipe')
        if recipe_div:
            for img in recipe_div.find_all('img'):
                src = img.get('src') or img.get('data-src')
                _add(src)

        # Изображения в разделе инструкций (пошаговые фото)
        instructions_div = self._get_instructions_section()
        if instructions_div:
            for img in instructions_div.find_all('img'):
                src = img.get('src') or img.get('data-src')
                # Относительные пути → абсолютные
                if src and not src.startswith('http'):
                    src = 'https://toitumisnoustajapluss.ee' + src
                _add(src)

        return ','.join(urls) if urls else None

    # ------------------------------------------------------------------
    # extract_all
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта."""
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags(),
        }


def main():
    """Точка входа для обработки директории с HTML файлами."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "toitumisnoustajapluss_ee")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ToitumisnoustajaplussEeExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python toitumisnoustajapluss_ee.py")


if __name__ == "__main__":
    main()
