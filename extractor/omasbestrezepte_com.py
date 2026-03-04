"""
Экстрактор данных рецептов для сайта omasbestrezepte.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class OmasBestRezepteExtractor(BaseRecipeExtractor):
    """Экстрактор для omasbestrezepte.com"""

    # Немецкие единицы измерения
    _DE_UNITS = (
        r'Tassen?|Esslöffel|EL|Teelöffel|TL|Päckchen?|Prisen?|Prise'
        r'|Becher?|Bund|Stück|Scheiben?|Zehen?|Zweig(?:e)?'
        r'|kg|g|mg|l|ml|cl|dl'
    )

    def _get_entry_content(self):
        """Возвращает основной блок контента страницы"""
        return self.soup.find('div', class_='entry-content')

    def _find_section_list(self, keywords: list) -> Optional[object]:
        """
        Находит UL/OL, следующий за **коротким** параграфом-заголовком,
        содержащим одно из ключевых слов.

        Длинные параграфы (> 100 символов) считаются описательным текстом,
        а не заголовками разделов.

        Args:
            keywords: список строк для поиска в тексте параграфа

        Returns:
            Найденный тег ul/ol или None
        """
        entry = self._get_entry_content()
        if not entry:
            return None

        children = [c for c in entry.children if hasattr(c, 'name') and c.name]
        for i, child in enumerate(children):
            if child.name == 'p':
                text = child.get_text(strip=True)
                # Только короткие параграфы могут быть заголовками разделов
                if len(text) > 100:
                    continue
                if any(kw.lower() in text.lower() for kw in keywords):
                    # Следующий элемент должен быть ul или ol
                    for j in range(i + 1, len(children)):
                        sibling = children[j]
                        if sibling.name in ('ul', 'ol'):
                            return sibling
                        # Пропускаем пустые блоки
                        if sibling.get_text(strip=True):
                            break
        return None

    def _parse_german_ingredient(self, text: str) -> Optional[dict]:
        """
        Разбирает строку немецкого ингредиента на составляющие.

        Args:
            text: строка вида "150 g Mehl" или "1 ½ Tassen feines Maismehl"

        Returns:
            dict с полями name, amount, unit или None
        """
        if not text:
            return None

        text = self.clean_text(text)

        # Заменяем Unicode дроби на десятичные числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.333', '⅔': '0.667', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
        }
        for frac, dec in fraction_map.items():
            text = text.replace(frac, dec)

        # Специальный случай: "Eine Prise <name>" → amount=None, unit="Prise"
        prise_match = re.match(
            r'^(?:Eine?|Ein)\s+(Prise|Hauch|Handvoll|Messerspitze)\s+(.+)$',
            text, re.IGNORECASE
        )
        if prise_match:
            return {
                'name': self.clean_text(prise_match.group(2)),
                'amount': None,
                'unit': prise_match.group(1),
            }

        # Основной паттерн: [количество] [единица] название
        # Количество может быть "1", "1.5", "0.5 1" (смешанное число), "1 0.5"
        pattern = (
            r'^((?:\d+(?:[.,]\d+)?(?:\s+\d+(?:[.,]\d+)?)?)?)'  # количество
            r'\s*'
            r'(' + self._DE_UNITS + r')?'                        # единица
            r'\s*'
            r'(.+?)$'                                            # название
        )
        match = re.match(pattern, text, re.IGNORECASE)
        if not match:
            return {'name': text, 'amount': None, 'unit': None}

        raw_amount, unit, name = match.groups()

        # Обработка количества
        amount = None
        raw_amount = raw_amount.strip() if raw_amount else ''
        if raw_amount:
            raw_amount = raw_amount.replace(',', '.')
            parts = raw_amount.split()
            try:
                total = sum(float(p) for p in parts)
                # Сохраняем как int если целое
                amount = int(total) if total == int(total) else total
            except ValueError:
                amount = None

        unit = unit.strip() if unit else None
        name = self.clean_text(name) if name else None

        if not name or len(name) < 1:
            return None

        return {'name': name, 'amount': amount, 'unit': unit}

    def _parse_time_string(self, text: str) -> Optional[str]:
        """
        Извлекает время из строки вида "Vorbereitungszeit: ca. 15 Minuten".

        Returns:
            Строка вида "15 minutes" или None
        """
        # Ищем число + единицу времени
        match = re.search(r'(\d+)\s*(?:Minuten?|Stunden?|Min\.?|Std\.?)', text, re.IGNORECASE)
        if not match:
            return None

        value = int(match.group(1))

        # Если единица — часы, конвертируем в минуты
        if re.search(r'Stunden?|Std\.?', match.group(0), re.IGNORECASE):
            value *= 60

        return f"{value} minutes"

    # ------------------------------------------------------------------
    # Методы извлечения полей
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала ищем h1
        h1 = self.soup.find('h1')
        if h1:
            name = self.clean_text(h1.get_text())
            if name:
                return name

        # Затем первый заголовок в блоке контента
        entry = self._get_entry_content()
        if entry:
            for tag in ('h1', 'h2', 'h3', 'h4'):
                heading = entry.find(tag)
                if heading:
                    name = self.clean_text(heading.get_text())
                    if name:
                        return name

        # Последний вариант — og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффикс " - Omas beste Rezepte"
            title = re.sub(r'\s*[-–|]\s*Omas.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title) or None

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта из вступительного параграфа"""
        entry = self._get_entry_content()
        if not entry:
            return None

        # Короткие метки-заголовки разделов, которые не являются описанием
        section_labels = re.compile(
            r'^(Zutaten|Küchengeräte|Küchenutensilien|Zubehör|Zubereitungszeit'
            r'|Vorbereitungs|Backzeit|Gesamtzeit|Zubereitung|Anleitung'
            r'|Tipps|Variationen|Hinweis|Fazit|Zeitangaben|Benötigt'
            r'|Schritt)',
            re.IGNORECASE
        )

        for child in entry.children:
            if not hasattr(child, 'name') or child.name != 'p':
                continue
            text = self.clean_text(child.get_text())
            if not text or len(text) < 20:
                continue
            # Пропускаем короткие метки разделов
            if len(text) < 80 and section_labels.search(text):
                continue
            # Убираем emoji-символы в начале строки
            text = re.sub(r'^[^\w\d\(]+', '', text)
            # Убираем префикс «Einführung» (с возможным пробелом или без)
            text = re.sub(r'^Einf[uü]hrung\s*', '', text, flags=re.IGNORECASE)
            text = text.strip()
            if len(text) >= 20:
                # Берём первое предложение
                sentences = re.split(r'(?<=[.!?])\s+', text)
                return sentences[0] if sentences else text

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из списка после раздела «Zutaten»"""
        ingredients_ul = self._find_section_list(
            ['Zutaten', 'Zutat', 'Zutaten:']
        )
        if not ingredients_ul:
            return None

        ingredients = []
        for li in ingredients_ul.find_all('li'):
            raw = self.clean_text(li.get_text())
            if not raw:
                continue
            parsed = self._parse_german_ingredient(raw)
            if parsed:
                ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_instructions(self) -> Optional[str]:
        """
        Извлечение шагов приготовления.

        Поддерживает два варианта верстки:
        1. Параграф «Zubereitung» → OL со шагами
        2. Параграф «Zubereitung» → чередующиеся OL (заголовок) + UL (шаги)
        """
        entry = self._get_entry_content()
        if not entry:
            return None

        def _is_instr_heading(text: str) -> bool:
            """Определяет, является ли параграф заголовком раздела инструкций."""
            # Заголовки разделов — короткие тексты (< 80 символов)
            if len(text) > 80:
                return False
            # "Zubereitung" без "Zubereitungszeit"
            if re.search(r'Zubereitung(?!szeit)', text, re.IGNORECASE):
                return True
            if re.search(r'\bAnleitung\b', text, re.IGNORECASE):
                return True
            if re.search(r'Schritt-für-Schritt', text, re.IGNORECASE):
                return True
            return False

        children = [c for c in entry.children if hasattr(c, 'name') and c.name]
        start_idx = None
        for i, child in enumerate(children):
            if child.name == 'p' and _is_instr_heading(child.get_text(strip=True)):
                start_idx = i
                break

        if start_idx is None:
            return None

        steps = []
        step_counter = 1

        for child in children[start_idx + 1:]:
            # Останавливаемся на следующей непустой секции-параграфе
            if child.name == 'p':
                text = child.get_text(strip=True)
                if text:
                    break

            if child.name == 'ol':
                li_items = child.find_all('li')
                # Если OL содержит только заголовки подраздела — пропускаем сам OL
                if all(
                    len(li.get_text(strip=True)) < 60
                    and li.get_text(strip=True).endswith(':')
                    for li in li_items
                ):
                    continue
                for li in li_items:
                    step_text = self.clean_text(li.get_text())
                    if step_text and not step_text.endswith(':'):
                        steps.append(f"{step_counter}. {step_text}")
                        step_counter += 1

            elif child.name == 'ul':
                for li in child.find_all('li'):
                    step_text = self.clean_text(li.get_text())
                    if step_text:
                        steps.append(f"{step_counter}. {step_text}")
                        step_counter += 1

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из мета-тега article:section"""
        meta = self.soup.find('meta', property='article:section')
        if meta and meta.get('content'):
            return self.clean_text(meta['content'])

        # Резервный вариант — хлебные крошки
        breadcrumb = self.soup.find(attrs={'@type': 'BreadcrumbList'})
        if not breadcrumb:
            # Ищем в JSON-LD
            for script in self.soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script.string or '')
                    graph = data.get('@graph', []) if isinstance(data, dict) else []
                    for item in graph:
                        if item.get('@type') == 'BreadcrumbList':
                            items = item.get('itemListElement', [])
                            if len(items) >= 2:
                                # Берём предпоследний элемент (категория)
                                cat = items[-2].get('item', {}).get('name')
                                if cat and cat.lower() != 'home':
                                    return self.clean_text(cat)
                except (json.JSONDecodeError, KeyError, AttributeError):
                    continue

        return None

    def _extract_time_from_ul(self, ul, keywords: list) -> Optional[str]:
        """Ищет строку времени по ключевым словам в элементах списка"""
        if not ul:
            return None
        for li in ul.find_all('li'):
            text = li.get_text(strip=True)
            if any(kw.lower() in text.lower() for kw in keywords):
                return self._parse_time_string(text)
        return None

    def _get_time_ul(self):
        """Возвращает UL с информацией о времени приготовления"""
        return self._find_section_list(
            ['Zubereitungszeit', 'Backzeit', 'Zeitangaben',
             'Vorbereitungs- und Backzeit', 'Kochzeit']
        )

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        ul = self._get_time_ul()
        return self._extract_time_from_ul(
            ul, ['Vorbereitungszeit', 'Vorbereitung']
        )

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        ul = self._get_time_ul()
        return self._extract_time_from_ul(
            ul, ['Backzeit', 'Kochzeit', 'Garzeit', 'Bratzeit']
        )

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        ul = self._get_time_ul()
        return self._extract_time_from_ul(
            ul, ['Gesamtdauer', 'Gesamtzeit', 'Gesamt']
        )

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов из раздела «Tipps»"""
        notes_ul = self._find_section_list(
            ['Tipps', 'Variationen', 'Hinweis', 'Notiz']
        )
        if not notes_ul:
            return None

        items = [
            self.clean_text(li.get_text())
            for li in notes_ul.find_all('li')
            if self.clean_text(li.get_text())
        ]
        return ' '.join(items) if items else None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов — на сайте отсутствуют"""
        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из мета-тегов и JSON-LD"""
        urls = []

        # og:image — главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # twitter:image
        tw_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if tw_image and tw_image.get('content'):
            urls.append(tw_image['content'])

        # JSON-LD ImageObject в @graph
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
                graph = data.get('@graph', []) if isinstance(data, dict) else []
                for item in graph:
                    if item.get('@type') == 'ImageObject':
                        url = item.get('url') or item.get('contentUrl')
                        if url:
                            urls.append(url)
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue

        # Убираем дубликаты, сохраняя порядок
        seen: set = set()
        unique: list = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с полями рецепта
        """
        return {
            'dish_name': self.extract_dish_name(),
            'description': self.extract_description(),
            'ingredients': self.extract_ingredients(),
            'instructions': self.extract_instructions(),
            'category': self.extract_category(),
            'prep_time': self.extract_prep_time(),
            'cook_time': self.extract_cook_time(),
            'total_time': self.extract_total_time(),
            'notes': self.extract_notes(),
            'image_urls': self.extract_image_urls(),
            'tags': self.extract_tags(),
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os

    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join('preprocessed', 'omasbestrezepte_com')

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(OmasBestRezepteExtractor, preprocessed_dir)
        return

    print(f'Директория не найдена: {preprocessed_dir}')
    print('Использование: python omasbestrezepte_com.py')


if __name__ == '__main__':
    main()
