"""
Экстрактор данных рецептов для сайта sofra-recepti.com
"""

import sys
import logging
import json
import re
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class SofraReceptiExtractor(BaseRecipeExtractor):
    """Экстрактор для sofra-recepti.com"""

    # Слова-маркеры разделов рецепта (Bosnian/Croatian/Serbian)
    _INGREDIENTS_MARKERS = re.compile(
        r'^\s*sastojci', re.IGNORECASE
    )
    _INSTRUCTIONS_MARKERS = re.compile(
        r'^\s*(priprema|kako\s+(?:\w+\s+){0,3}pravi[m]?|postupak|način\s+pripreme)',
        re.IGNORECASE,
    )
    _SOURCE_MARKERS = re.compile(
        r'^\s*(izvor|source)\s*:', re.IGNORECASE
    )

    # Единицы измерения в боснийском/хорватском/сербском
    _UNITS_PATTERN = re.compile(
        r'^([\d\s,.]+)?\s*'
        r'(dl|ml|l|gr|g|kg|čaše?|šolje?|kašik[ae]|kašičic[ae]|'
        r'pakovanje|pakovan[jj]a|komad[a]?|komad[ai]?|'
        r'šak[ae]?|prstohvat[a]?|malo|po\s+ukusu)?\s*'
        r'(.+)',
        re.IGNORECASE,
    )

    def _get_summary_div(self):
        """Возвращает div.cm-entry-summary или None"""
        return self.soup.find(class_='cm-entry-summary')

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из h1"""
        # Предпочитаем h1.cm-entry-title
        h1 = self.soup.find('h1', class_='cm-entry-title')
        if not h1:
            h1 = self.soup.find('h1')
        if h1:
            title = self.clean_text(h1.get_text())
            # Убираем суффикс сайта
            title = re.sub(r'\s*[-–|]\s*sofra-recepti\.com\s*$', '', title, flags=re.IGNORECASE)
            # Если в заголовке есть двоеточие, берём часть до него
            if ':' in title:
                title = title.split(':', 1)[0].strip()
            return title if title else None

        # Запасной вариант: og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*[-–|]\s*sofra-recepti\.com\s*$', '', title, flags=re.IGNORECASE)
            if ':' in title:
                title = title.split(':', 1)[0].strip()
            return self.clean_text(title) or None

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        summary = self._get_summary_div()
        if not summary:
            return self._fallback_description()

        # Собираем вводные параграфы (до секции Sastojci / Priprema)
        intro_paragraphs = []
        for child in summary.children:
            if not hasattr(child, 'name') or not child.name:
                continue
            tag = child.name.lower()
            text = self.clean_text(child.get_text())
            if not text:
                continue

            # Стоп на маркерах разделов
            if tag in ('h2', 'h3', 'h4') and (
                self._INGREDIENTS_MARKERS.match(text)
                or self._INSTRUCTIONS_MARKERS.match(text)
            ):
                break
            if tag == 'p' and (
                self._INGREDIENTS_MARKERS.match(text)
                or self._INSTRUCTIONS_MARKERS.match(text)
                or self._SOURCE_MARKERS.match(text)
            ):
                break
            if tag == 'ul':
                break

            if tag == 'p':
                # Пропускаем параграф, который является просто заголовком (тем же, что в h1)
                dish_name = self.extract_dish_name()
                if dish_name and text.lower().startswith(dish_name.lower()):
                    # Это повторение заголовка — проверяем, есть ли часть после двоеточия
                    if ':' in text:
                        subtitle = text.split(':', 1)[1].strip()
                        if subtitle:
                            intro_paragraphs.append(subtitle)
                    continue
                intro_paragraphs.append(text)

        if intro_paragraphs:
            return intro_paragraphs[0]

        return self._fallback_description()

    def _fallback_description(self) -> Optional[str]:
        """Описание из meta-тега"""
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        return None

    # ------------------------------------------------------------------
    # Ингредиенты
    # ------------------------------------------------------------------

    def _parse_ingredient_text(self, text: str) -> Optional[dict]:
        """
        Разбирает строку ингредиента вида «200 ml slatke pavlake» на поля
        name / amount / unit.
        """
        text = self.clean_text(text)
        if not text:
            return None

        # Удаляем маркер списка «–» в начале
        text = re.sub(r'^[\-–—]\s*', '', text).strip()
        if not text:
            return None

        # Удаляем заметки в скобках, не меняя остаток
        text_no_paren = re.sub(r'\([^)]*\)', '', text).strip()

        # Попытка разобрать «количество единица название»
        pattern = re.compile(
            r'^'
            r'(?P<amount>[\d]+(?:[.,][\d]+)?(?:\s*[-–/]\s*[\d]+(?:[.,][\d]+)?)?)\s*'
            r'(?P<unit>dl|ml|l\b|gr|g\b|kg|čaše?|šolje?|kašik[ae]|kašičic[ae]|'
            r'pakovanje[a]?|pakovan[jj]a|komad[a]?|šak[ae]?|prstohvat[a]?|'
            r'kašičice?|kašik[ae]?)?\s*'
            r'(?P<name>.+)$',
            re.IGNORECASE,
        )

        m = pattern.match(text_no_paren)
        if m:
            amount_raw = m.group('amount').replace(',', '.').strip()
            unit = m.group('unit')
            name = self.clean_text(m.group('name'))

            # Нормализуем amount в число (int или float)
            try:
                amount_val: Optional[float] = float(amount_raw)
                if amount_val == int(amount_val):
                    amount_val = int(amount_val)  # type: ignore[assignment]
            except ValueError:
                amount_val = amount_raw  # type: ignore[assignment]

            # Если единица не определена, но имя начинается с единицы — уточним
            unit_clean = unit.strip() if unit else None

            # Очистка имени от остаточных мусорных символов
            name = re.sub(r'^[,;:\s]+|[,;:\s]+$', '', name)
            if not name:
                return None

            return {
                'name': name,
                'amount': amount_val,
                'unit': unit_clean,
            }

        # Нет количества (например «Malo čokolade za dekoraciju»)
        name = self.clean_text(text_no_paren)
        name = re.sub(r'^[,;:\s]+|[,;:\s]+$', '', name)
        if not name:
            return None
        return {
            'name': name,
            'amount': None,
            'unit': None,
        }

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов.

        Поддерживает два формата sofra-recepti.com:
        1. Маркированный список ul > li (новый формат).
        2. Параграф с элементами, разделёнными символом «–» (старый формат).
        """
        summary = self._get_summary_div()
        if not summary:
            return None

        children = [c for c in summary.children if hasattr(c, 'name') and c.name]
        ingredients = []
        in_ingredients = False

        for idx, child in enumerate(children):
            tag = child.name.lower()
            text = self.clean_text(child.get_text())

            # Ищем заголовок «Sastojci»
            if not in_ingredients:
                if (tag in ('h2', 'h3', 'h4') and self._INGREDIENTS_MARKERS.match(text)) or (
                    tag == 'p' and self._INGREDIENTS_MARKERS.match(text)
                ):
                    in_ingredients = True
                    continue
                continue

            # Уже внутри секции ингредиентов — останавливаемся на маркере Priprema
            if tag in ('h2', 'h3', 'h4') and self._INSTRUCTIONS_MARKERS.match(text):
                break
            if tag == 'p' and self._INSTRUCTIONS_MARKERS.match(text):
                break

            # Формат 1: маркированный список
            if tag == 'ul':
                for li in child.find_all('li'):
                    li_text = self.clean_text(li.get_text())
                    if li_text:
                        parsed = self._parse_ingredient_text(li_text)
                        if parsed:
                            ingredients.append(parsed)
                break

            # Формат 2: параграф с «–» разделителями
            if tag == 'p' and '–' in text:
                raw_parts = re.split(r'[–—]', text)
                for part in raw_parts:
                    part = part.strip()
                    if part:
                        parsed = self._parse_ingredient_text(part)
                        if parsed:
                            ingredients.append(parsed)
                break

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    # ------------------------------------------------------------------
    # Инструкции
    # ------------------------------------------------------------------

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        summary = self._get_summary_div()
        if not summary:
            return None

        children = [c for c in summary.children if hasattr(c, 'name') and c.name]
        steps = []
        in_instructions = False

        for child in children:
            tag = child.name.lower()
            text = self.clean_text(child.get_text())
            if not text:
                continue

            # Ищем маркер «Priprema» / «Kako ja pravim» и т.п.
            if not in_instructions:
                if (tag in ('h2', 'h3', 'h4') and self._INSTRUCTIONS_MARKERS.match(text)) or (
                    tag == 'p' and self._INSTRUCTIONS_MARKERS.match(text)
                ):
                    in_instructions = True
                continue

            # Пропускаем источник
            if self._SOURCE_MARKERS.match(text):
                continue

            if tag in ('p', 'li'):
                steps.append(text)
            elif tag in ('ol', 'ul'):
                for li in child.find_all('li'):
                    li_text = self.clean_text(li.get_text())
                    if li_text:
                        steps.append(li_text)

        return ' '.join(steps) if steps else None

    # ------------------------------------------------------------------
    # Категория
    # ------------------------------------------------------------------

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда"""
        # Из meta article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])

        # Из класса article: category-XXX
        article = self.soup.find('article')
        if article:
            for cls in article.get('class', []):
                if cls.startswith('category-'):
                    cat = cls[len('category-'):]
                    return self.clean_text(cat.replace('-', ' ').title())

        # Из заголовка секции
        cat_header = self.soup.find(class_='cm-entry-header-meta')
        if cat_header:
            cat_text = self.clean_text(cat_header.get_text())
            if cat_text:
                return cat_text

        return None

    # ------------------------------------------------------------------
    # Время
    # ------------------------------------------------------------------

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки — не представлено на странице явно"""
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Время готовки — не представлено на странице явно"""
        return None

    def extract_total_time(self) -> Optional[str]:
        """Общее время — не представлено на странице явно"""
        return None

    # ------------------------------------------------------------------
    # Заметки
    # ------------------------------------------------------------------

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок/дополнительных комментариев.
        Берём второй и последующие вводные параграфы (после описания).
        """
        summary = self._get_summary_div()
        if not summary:
            return None

        intro_paragraphs = []
        for child in summary.children:
            if not hasattr(child, 'name') or not child.name:
                continue
            tag = child.name.lower()
            text = self.clean_text(child.get_text())
            if not text:
                continue

            if tag in ('h2', 'h3', 'h4') and (
                self._INGREDIENTS_MARKERS.match(text)
                or self._INSTRUCTIONS_MARKERS.match(text)
            ):
                break
            if tag == 'p' and (
                self._INGREDIENTS_MARKERS.match(text)
                or self._INSTRUCTIONS_MARKERS.match(text)
                or self._SOURCE_MARKERS.match(text)
            ):
                break
            if tag == 'ul':
                break

            if tag == 'p':
                dish_name = self.extract_dish_name()
                if dish_name and text.lower().startswith(dish_name.lower()):
                    continue
                intro_paragraphs.append(text)

        # Первый параграф — описание; остальные — заметки
        if len(intro_paragraphs) > 1:
            return ' '.join(intro_paragraphs[1:])

        return None

    # ------------------------------------------------------------------
    # Теги
    # ------------------------------------------------------------------

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из ссылок с rel=tag"""
        tag_links = self.soup.find_all('a', rel='tag')
        tags = []
        for a in tag_links:
            tag_text = self.clean_text(a.get_text())
            if tag_text:
                tags.append(tag_text.lower())

        # Убираем дубликаты
        seen: set = set()
        unique_tags = []
        for t in tags:
            if t not in seen:
                seen.add(t)
                unique_tags.append(t)

        return ', '.join(unique_tags) if unique_tags else None

    # ------------------------------------------------------------------
    # Изображения
    # ------------------------------------------------------------------

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls = []

        # og:image — главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # Изображение в блоке cm-featured-image
        featured_div = self.soup.find(class_='cm-featured-image')
        if featured_div:
            img = featured_div.find('img')
            if img:
                src = img.get('src') or img.get('data-src', '')
                if src and src not in urls:
                    urls.append(src)

        # Убираем дубликаты
        seen: set = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ','.join(unique_urls) if unique_urls else None

    # ------------------------------------------------------------------
    # Главный метод
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта.
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception:
            logger.exception("Ошибка извлечения dish_name из %s", self.html_path)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception:
            logger.exception("Ошибка извлечения description из %s", self.html_path)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception:
            logger.exception("Ошибка извлечения ingredients из %s", self.html_path)
            ingredients = None

        try:
            instructions = self.extract_steps()
        except Exception:
            logger.exception("Ошибка извлечения instructions из %s", self.html_path)
            instructions = None

        try:
            category = self.extract_category()
        except Exception:
            logger.exception("Ошибка извлечения category из %s", self.html_path)
            category = None

        try:
            notes = self.extract_notes()
        except Exception:
            logger.exception("Ошибка извлечения notes из %s", self.html_path)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception:
            logger.exception("Ошибка извлечения tags из %s", self.html_path)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception:
            logger.exception("Ошибка извлечения image_urls из %s", self.html_path)
            image_urls = None

        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "image_urls": image_urls,
            "tags": tags,
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "sofra-recepti_com")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(SofraReceptiExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python sofra-recepti_com.py")


if __name__ == "__main__":
    main()
