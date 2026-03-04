"""
Экстрактор данных рецептов для сайта zhcn.julinse.com
"""

import sys
from pathlib import Path
import json
import re
import logging
from typing import Optional, Union

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class ZhcnJulinseComExtractor(BaseRecipeExtractor):
    """Экстрактор для zhcn.julinse.com"""

    # Стандартные разделы рецепта (используются для навигации по HTML)
    _SECTION_INGREDIENTS = '配料'   # Ингредиенты
    _SECTION_PREP = '制备'          # Приготовление
    _SECTION_NUTRITION = '营养'     # Питательность

    # Известные китайские единицы измерения (порядок важен — длинные первыми)
    _CN_UNITS = [
        '汤匙', '茶匙', '毫升', '千克', '盎司',
        '杯', '磅', '克', '升', '个', '条', '片', '块',
        '颗', '粒', '袋', '罐', '瓶', '包', '勺', '碗',
        '根', '枚', '只', '头', '把', '捆', '束', '匙',
    ]

    # Размерные прилагательные (заменяются единицей '个')
    _CN_SIZE_QUALIFIERS = frozenset({'中', '大', '小'})

    # Слова-фильтры для пропуска строк с данными о питательности
    _NUTRITION_KEYWORDS = frozenset({
        '卡路里', '脂肪', '碳水化合物', '蛋白质',
    })

    def _get_article_content(self):
        """Возвращает основной блок контента статьи."""
        return self.soup.find('div', class_='amp-wp-article-content')

    def _get_h3_sections(self):
        """Возвращает список всех h3-тегов внутри контента."""
        content = self._get_article_content()
        if content is None:
            return []
        return content.find_all('h3')

    def _find_h3_by_keyword(self, keyword: str):
        """Находит первый h3, содержащий заданное ключевое слово."""
        for h3 in self._get_h3_sections():
            if keyword in h3.get_text():
                return h3
        return None

    def _get_time_paragraph(self):
        """Находит абзац с информацией о времени приготовления."""
        content = self._get_article_content()
        if content is None:
            return None
        for p in content.find_all('p'):
            if '总时间' in p.get_text():
                return p
        return None

    # ------------------------------------------------------------------
    # Парсинг ингредиентов
    # ------------------------------------------------------------------

    # Маппинг Unicode-дробей в десятичные значения
    _UNICODE_FRACTIONS: dict = {
        '½': 0.5, '¼': 0.25, '¾': 0.75,
        '⅓': 1/3, '⅔': 2/3, '⅛': 0.125,
        '⅜': 0.375, '⅝': 0.625, '⅞': 0.875,
    }

    def _normalize_fractions(self, text: str) -> str:
        """Заменяет Unicode-дроби: '1½' → '1.5', '½' → '0.5'."""
        result = text
        for frac, val in self._UNICODE_FRACTIONS.items():
            # Дробь, идущая сразу после цифры: "1½" → "1.5"
            result = re.sub(
                r'(\d)' + re.escape(frac),
                lambda m, v=val: str(int(m.group(1)) + v),
                result,
            )
            # Одиночная дробь: "½" → "0.5"
            result = result.replace(frac, str(val))
        return result

    def _parse_amount(self, s: str) -> Optional[Union[int, float, str]]:
        """Конвертирует строку количества в число (int/float) или оставляет как строку."""
        s = s.strip()
        if s == '半':
            return 0.5
        try:
            if '/' in s:
                parts = s.split()
                total = 0.0
                for part in parts:
                    if '/' in part:
                        num, den = part.split('/')
                        total += float(num) / float(den)
                    else:
                        total += float(part)
                return int(total) if total == int(total) else total
            val = float(s)
            return int(val) if val == int(val) else val
        except (ValueError, ZeroDivisionError):
            return s

    def _parse_cn_ingredient(self, text: str) -> Optional[dict]:
        """
        Парсит строку ингредиента в структурированный словарь.

        Returns:
            dict с полями name, amount, units или None, если строка не является ингредиентом.
        """
        text = self.clean_text(text)
        if not text:
            return None

        # Пропускаем заголовки разделов (заканчиваются на '：' или ':')
        if text.endswith('：') or text.endswith(':'):
            return None

        # Нормализуем Unicode-дроби для числового парсинга
        normalized = self._normalize_fractions(text)

        # Числовой паттерн (порядок важен: сначала смешанные дроби, затем простые,
        # затем целые числа; дроби стоят перед целыми, чтобы "1/2" не стало "1")
        number_pat = (
            r'^(半'
            r'|\d+\s+\d+/\d+'   # смешанная дробь: "1 1/2"
            r'|\d+/\d+'          # простая дробь: "1/2"
            r'|\d+(?:\.\d+)?'    # целое или десятичное: "3", "1.5"
            r')'
        )
        m = re.match(number_pat, normalized)

        if not m:
            # Нет числа — только название ингредиента
            name = self._clean_ingredient_name(text)
            if not name:
                return None
            return {'name': name, 'amount': None, 'units': None}

        amount_str = m.group(1)
        amount = self._parse_amount(amount_str)
        # Используем normalized для остатка, чтобы позиция m.end() была корректной
        remainder = normalized[m.end():].strip()

        unit = None
        name = remainder

        # Проверяем скобочную единицу вида（8盎司）包装
        # Ограничиваем длину слова-единицы до 1-2 символов, чтобы не захватить название
        paren_unit_m = re.match(r'^（([^）]+)）(\S{1,2})', remainder)
        if paren_unit_m:
            unit = paren_unit_m.group(1) + paren_unit_m.group(2)
            name = remainder[paren_unit_m.end():].strip()
        else:
            # Ищем стандартную единицу измерения
            for u in self._CN_UNITS:
                if remainder.startswith(u):
                    unit = u
                    name = remainder[len(u):].strip()
                    break

            # Проверяем размерные прилагательные (大/中/小 → '个')
            if unit is None:
                size_m = re.match(r'^([大中小])', remainder)
                if size_m:
                    unit = '个'
                    name = remainder[1:].strip()

        # Если единицы не найдены — используем '个' как счётную единицу
        if unit is None and remainder:
            unit = '个'
            name = remainder

        name = self._clean_ingredient_name(name)
        # После счётной единицы '个' удаляем ведущее прилагательное размера
        # (напр. "3个大鸡蛋" → "鸡蛋"; не трогаем "大蒜粉", где 大 — часть слова)
        if unit == '个' and name and name[0] in '大中小' and len(name) > 1:
            name = name[1:].strip()
        if not name:
            return None

        return {'name': name, 'amount': amount, 'units': unit}

    @staticmethod
    def _clean_ingredient_name(name: str) -> str:
        """Очищает название ингредиента от скобок и примечаний."""
        # Удаляем скобочные примечания
        name = re.sub(r'（[^）]*）', '', name)
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем перечисление альтернатив: "干牛至或其他意大利调味料" → "干牛至"
        name = re.sub(r'或其[他它].*$', '', name)
        # Удаляем описание после запятой
        name = re.sub(r'，.*$', '', name)
        return name.strip()

    # ------------------------------------------------------------------
    # Публичные методы извлечения данных
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлекает название блюда из тега <title>, убирая суффикс '食谱'."""
        title_tag = self.soup.find('title')
        if title_tag:
            txt = self.clean_text(title_tag.get_text())
            txt = re.sub(r'食谱$', '', txt).strip()
            return txt if txt else None
        logger.warning("Тег <title> не найден в %s", self.html_path)
        return None

    def extract_description(self) -> Optional[str]:
        """
        Извлекает вступительное описание рецепта.

        Абзацы расположены между строкой с временем приготовления
        и заголовком раздела ингредиентов.
        """
        content = self._get_article_content()
        if content is None:
            return None

        ingr_h3 = self._find_h3_by_keyword(self._SECTION_INGREDIENTS)
        time_p = self._get_time_paragraph()

        if ingr_h3 is None or time_p is None:
            logger.warning("Не удалось найти раздел ингредиентов или абзац со временем в %s",
                           self.html_path)
            return None

        desc_paragraphs = []
        sib = time_p.find_next_sibling()
        while sib and sib != ingr_h3:
            if sib.name == 'p':
                txt = self.clean_text(sib.get_text())
                if txt:
                    desc_paragraphs.append(txt)
            sib = sib.find_next_sibling()

        return desc_paragraphs[0] if desc_paragraphs else None

    def extract_ingredients(self) -> Optional[str]:
        """Извлекает список ингредиентов в структурированном JSON-формате."""
        content = self._get_article_content()
        if content is None:
            return None

        ingr_h3 = self._find_h3_by_keyword(self._SECTION_INGREDIENTS)
        if ingr_h3 is None:
            logger.warning("Раздел '配料' не найден в %s", self.html_path)
            return None

        ul = ingr_h3.find_next_sibling('ul')
        if ul is None:
            logger.warning("Список ингредиентов (ul) не найден после '配料' в %s", self.html_path)
            return None

        li_texts = [li.get_text(separator=' ', strip=True) for li in ul.find_all('li')]
        ingredients = []
        i = 0

        while i < len(li_texts):
            text = self.clean_text(li_texts[i])

            # Пропускаем заголовки подразделов (напр. "对于地壳：")
            if text.endswith('：') or text.endswith(':'):
                i += 1
                continue

            # Особый случай: "3中" — только число + размер, следующий li — название
            qty_only_m = re.match(r'^(\d+)\s*([大中小])?\s*$', text)
            if qty_only_m and i + 1 < len(li_texts):
                amount_val = int(qty_only_m.group(1))
                next_text = self.clean_text(li_texts[i + 1])
                name = self._clean_ingredient_name(next_text)
                if name:
                    ingredients.append({'name': name, 'amount': amount_val, 'units': '个'})
                    i += 2
                    continue

            parsed = self._parse_cn_ingredient(text)
            if parsed:
                ingredients.append(parsed)
            i += 1

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """Извлекает шаги приготовления из раздела '制备'."""
        content = self._get_article_content()
        if content is None:
            return None

        prep_h3 = self._find_h3_by_keyword(self._SECTION_PREP)
        if prep_h3 is None:
            logger.warning("Раздел '制备' не найден в %s", self.html_path)
            return None

        steps = []
        sib = prep_h3.find_next_sibling()
        while sib and sib.name != 'h3':
            if sib.name == 'ol':
                for li in sib.find_all('li'):
                    txt = self.clean_text(li.get_text(separator=' ', strip=True))
                    if txt:
                        steps.append(txt)
            sib = sib.find_next_sibling()

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Категория блюда (не представлена в HTML в структурированном виде)."""
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлекает время подготовки из абзаца с временными метками."""
        p = self._get_time_paragraph()
        if p is None:
            return None
        m = re.search(r'准备\s*(\d+)分钟', p.get_text())
        if m:
            return f"{m.group(1)} minutes"
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлекает время приготовления (烹饪 или 煮)."""
        p = self._get_time_paragraph()
        if p is None:
            return None
        m = re.search(r'(?:烹饪|煮)\s*(\d+)分钟', p.get_text())
        if m:
            return f"{m.group(1)} minutes"
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлекает общее время приготовления."""
        p = self._get_time_paragraph()
        if p is None:
            return None
        m = re.search(r'总时间\s*(\d+)分钟', p.get_text())
        if m:
            return f"{m.group(1)} minutes"
        return None

    def extract_notes(self) -> Optional[str]:
        """
        Извлекает дополнительные заметки/советы.

        Берётся первый h3-раздел после '制备', который не является
        стандартным разделом рецепта.
        """
        prep_h3 = self._find_h3_by_keyword(self._SECTION_PREP)
        if prep_h3 is None:
            return None

        next_h3 = prep_h3.find_next_sibling('h3')
        if next_h3 is None:
            return None

        texts = []
        sib = next_h3.find_next_sibling()
        while sib and sib.name != 'h3':
            if sib.name in ('p', 'ul', 'ol'):
                txt = self.clean_text(sib.get_text(separator=' ', strip=True))
                if txt:
                    texts.append(txt)
            sib = sib.find_next_sibling()

        return ' '.join(texts) if texts else None

    def extract_tags(self) -> Optional[str]:
        """Теги (не представлены в HTML в структурированном виде)."""
        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлекает URL главного изображения рецепта."""
        fig = self.soup.find('figure', class_='amp-wp-article-featured-image')
        if fig:
            img = fig.find('amp-img')
            if img and img.get('src'):
                return img['src']
        logger.warning("Изображение рецепта не найдено в %s", self.html_path)
        return None

    def extract_all(self) -> dict:
        """
        Извлекает все данные рецепта и возвращает их в виде словаря.

        Returns:
            dict со всеми полями рецепта (отсутствующие поля заполняются None).
        """
        return {
            'dish_name': self.extract_dish_name(),
            'description': self.extract_description(),
            'ingredients': self.extract_ingredients(),
            'instructions': self.extract_steps(),
            'category': self.extract_category(),
            'prep_time': self.extract_prep_time(),
            'cook_time': self.extract_cook_time(),
            'total_time': self.extract_total_time(),
            'notes': self.extract_notes(),
            'image_urls': self.extract_image_urls(),
            'tags': self.extract_tags(),
        }


def main():
    """Точка входа для обработки директории с HTML-файлами."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "zhcn_julinse_com")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ZhcnJulinseComExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python zhcn_julinse_com.py")


if __name__ == "__main__":
    main()
