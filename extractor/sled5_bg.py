"""
Экстрактор данных рецептов для сайта sled5.bg
Поддерживает два формата страниц:
  1. Новый формат с WordPress Recipe Maker (WPRM) плагином
  2. Старый формат с ингредиентами и инструкциями в простых абзацах
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Болгарские единицы измерения для парсинга текста (raw-строки для regex)
_BG_UNITS = [
    r'кг', r'г', r'мл', r'л', r'дл',
    r'с\.л', r'с\.л\.', r'ч\.л', r'ч\.л\.', r'ч\.ч\.', r'ч\.ч',
    r'бр\.', r'бр', r'бройки', r'бройка',
    r'пакет', r'пакетче', r'пакетчета',
    r'щипка', r'щипки',
    r'филия', r'филийки',
    r'глава', r'глави',
    r'скилидка', r'скилидки',
    r'чаша', r'чаши',
    r'лъжица', r'лъжици',
    r'чаена лъжица', r'супена лъжица',
]
_UNITS_PATTERN = r'(?:' + '|'.join(_BG_UNITS) + r')'


class Sled5BgExtractor(BaseRecipeExtractor):
    """Экстрактор для sled5.bg"""

    # ------------------------------------------------------------------ #
    # Вспомогательные методы                                               #
    # ------------------------------------------------------------------ #

    def _get_entry_content(self):
        """Возвращает основной блок контента статьи."""
        return self.soup.find('div', class_='entry-content')

    def _get_wprm(self):
        """Возвращает контейнер WPRM, если он присутствует на странице."""
        return self.soup.find('div', class_='wprm-recipe')

    def _get_wprm_container(self):
        """Возвращает внешний wprm-recipe-container для поиска соседних элементов."""
        return self.soup.find('div', class_='wprm-recipe-container')

    # ------------------------------------------------------------------ #
    # Название блюда                                                        #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда."""
        # Приоритет: заголовок WPRM рецепта
        wprm = self._get_wprm()
        if wprm:
            name_elem = wprm.find(class_='wprm-recipe-name')
            if name_elem:
                return self.clean_text(name_elem.get_text())

        # Fallback: h1 на странице
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        # og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        return None

    # ------------------------------------------------------------------ #
    # Описание                                                              #
    # ------------------------------------------------------------------ #

    def extract_description(self) -> Optional[str]:
        """Извлечение краткого описания рецепта."""
        entry = self._get_entry_content()
        if not entry:
            return None

        wprm_container = self._get_wprm_container()

        # Ищем первые абзацы текста до блока WPRM (или до ингредиентов)
        description_parts = []
        for elem in entry.children:
            if not hasattr(elem, 'name') or not elem.name:
                continue

            # Останавливаемся на WPRM контейнере
            if wprm_container and elem == wprm_container:
                break

            # Останавливаемся, когда встречаем ингредиенты (старый формат)
            if elem.name == 'p':
                strong = elem.find('strong')
                if strong and re.search(r'необходими|продукт', strong.get_text(), re.I):
                    break

                text = self.clean_text(elem.get_text(separator=' '))
                # Пропускаем пустые абзацы и рекламные блоки
                if text and len(text) > 20:
                    description_parts.append(text)

        return ' '.join(description_parts) if description_parts else None

    # ------------------------------------------------------------------ #
    # Ингредиенты                                                           #
    # ------------------------------------------------------------------ #

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате."""
        # --- WPRM формат ---
        wprm = self._get_wprm()
        if wprm:
            ingredients = self._extract_wprm_ingredients(wprm)
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        # --- Старый формат (абзац с Необходими продукти) ---
        entry = self._get_entry_content()
        if entry:
            ingredients = self._extract_old_format_ingredients(entry)
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        return None

    def _extract_wprm_ingredients(self, wprm) -> list:
        """Парсинг ингредиентов из WPRM блока."""
        ingredients = []
        for li in wprm.find_all('li', class_='wprm-recipe-ingredient'):
            amount_span = li.find('span', class_='wprm-recipe-ingredient-amount')
            unit_span = li.find('span', class_='wprm-recipe-ingredient-unit')
            name_span = li.find('span', class_='wprm-recipe-ingredient-name')

            name = self.clean_text(name_span.get_text()) if name_span else None
            amount = self.clean_text(amount_span.get_text()) if amount_span else None
            unit = self.clean_text(unit_span.get_text()) if unit_span else None

            if name:
                ingredients.append({
                    'name': name,
                    'unit': unit,
                    'amount': amount,
                })
        return ingredients

    def _extract_old_format_ingredients(self, entry) -> list:
        """Парсинг ингредиентов из старого формата (абзац с <br>-строками)."""
        ingredients = []
        ingredient_p = None

        for p in entry.find_all('p'):
            strong = p.find('strong')
            if strong and re.search(r'необходими|продукт', strong.get_text(), re.I):
                ingredient_p = p
                break

        if not ingredient_p:
            return []

        # Собираем строки из абзаца, разделённые <br>
        raw_lines = []
        for content in ingredient_p.contents:
            if hasattr(content, 'name'):
                if content.name == 'br':
                    continue
                if content.name == 'strong':
                    continue  # пропускаем заголовок
                text = content.get_text(separator=' ', strip=True)
            else:
                text = str(content).strip()

            if text:
                # Разбиваем по переносам, которые могут быть в тексте
                for line in re.split(r'\n', text):
                    line = self.clean_text(line)
                    if line:
                        raw_lines.append(line)

        for line in raw_lines:
            parsed = self._parse_bg_ingredient_line(line)
            if parsed:
                ingredients.append(parsed)

        return ingredients

    def _parse_bg_ingredient_line(self, line: str) -> Optional[dict]:
        """
        Парсинг одной строки ингредиента на болгарском языке.
        Формат: "6 кг печен червен пипер" -> {name, unit, amount}
        """
        if not line:
            return None

        # Паттерн: <amount> <unit> <name>
        pattern = (
            r'^(?:около\s+)?'
            r'([\d\s/.,]+(?:\s+[\d/.,]+)?)\s+'
            r'(' + _UNITS_PATTERN + r')\s+'
            r'(.+)$'
        )
        m = re.match(pattern, line.strip(), re.IGNORECASE)
        if m:
            amount_str = m.group(1).strip()
            unit = m.group(2).strip()
            name = self.clean_text(m.group(3))
            # Убираем уточнения в конце ("или на вкус" и т.п.)
            name = re.sub(r'\s+или на вкус$', '', name, flags=re.I).strip()
            return {'name': name, 'unit': unit, 'amount': amount_str}

        # Паттерн без единицы: просто "<amount> <name>" или просто "<name>"
        m2 = re.match(r'^([\d\s/.,]+)\s+(.+)$', line.strip())
        if m2:
            amount_str = m2.group(1).strip()
            name = self.clean_text(m2.group(2))
            name = re.sub(r'\s+или на вкус$', '', name, flags=re.I).strip()
            return {'name': name, 'unit': None, 'amount': amount_str}

        # Только название
        name = self.clean_text(line)
        if name:
            return {'name': name, 'unit': None, 'amount': None}

        return None

    # ------------------------------------------------------------------ #
    # Инструкции                                                            #
    # ------------------------------------------------------------------ #

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления."""
        entry = self._get_entry_content()
        if not entry:
            return None

        wprm_container = self._get_wprm_container()
        steps = []

        if wprm_container:
            steps = self._extract_instructions_after_wprm(wprm_container)
        else:
            steps = self._extract_instructions_old_format(entry)

        return ' '.join(steps) if steps else None

    def _extract_instructions_after_wprm(self, wprm_container) -> list:
        """Инструкции из абзацев после блока WPRM."""
        steps = []
        in_instructions = False

        for elem in wprm_container.next_siblings:
            if not hasattr(elem, 'name') or not elem.name:
                continue

            # Заголовок "Начин на приготвяне" (h3 или p > strong)
            if elem.name in ('h3', 'h2', 'h4'):
                text = elem.get_text(strip=True)
                if re.search(r'начин на приготвяне|приготвяне', text, re.I):
                    in_instructions = True
                    continue

            if elem.name == 'p':
                text = self.clean_text(elem.get_text(separator=' '))

                # Проверяем, не является ли это заголовком инструкций в p-теге
                strong = elem.find('strong')
                if strong and re.search(r'начин на приготвяне', strong.get_text(), re.I):
                    in_instructions = True
                    # Текст может идти сразу после заголовка
                    rest = re.sub(r'^Начин на приготвяне\s*:', '', text, flags=re.I).strip()
                    if rest:
                        steps.append(rest)
                    continue

                if not in_instructions:
                    continue

                # Стоп-условие: заметки или авторский блок
                if self._is_notes_paragraph(elem):
                    break
                if elem.find(class_=re.compile(r'sabox|author', re.I)):
                    break

                if text:
                    steps.append(text)

            # Авторский блок — останавливаемся
            if elem.name == 'div' and elem.find(class_=re.compile(r'sabox', re.I)):
                break

        return steps

    def _extract_instructions_old_format(self, entry) -> list:
        """Инструкции из старого формата страницы."""
        steps = []
        in_instructions = False

        for elem in entry.children:
            if not hasattr(elem, 'name') or not elem.name:
                continue

            if elem.name == 'p':
                strong = elem.find('strong')
                if strong and re.search(r'начин на приготвяне', strong.get_text(), re.I):
                    in_instructions = True
                    # Первая часть инструкций может быть в том же абзаце
                    rest = re.sub(r'^Начин на приготвяне\s*:', '', 
                                  elem.get_text(separator=' ', strip=True), flags=re.I).strip()
                    if rest:
                        steps.append(self.clean_text(rest))
                    continue

                if not in_instructions:
                    continue

                # Стоп-условие: заметки или авторский блок
                if self._is_notes_paragraph(elem):
                    break
                if elem.find(class_=re.compile(r'sabox|author|has-text-align-right', re.I)):
                    # "has-text-align-right" обычно содержит ссылку на автора
                    text = elem.get_text(strip=True)
                    if re.search(r'рецепт.*от|блог', text, re.I):
                        break

                text = self.clean_text(elem.get_text(separator=' '))
                if text:
                    steps.append(text)

            # Авторский блок — останавливаемся
            if elem.name == 'div' and elem.find(class_=re.compile(r'sabox', re.I)):
                break

        return steps

    # ------------------------------------------------------------------ #
    # Категория                                                             #
    # ------------------------------------------------------------------ #

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда."""
        wprm = self._get_wprm()
        if wprm:
            course = wprm.find('span', class_='wprm-recipe-course')
            if course:
                return self.clean_text(course.get_text())

        return None

    # ------------------------------------------------------------------ #
    # Время                                                                 #
    # ------------------------------------------------------------------ #

    def _extract_wprm_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени из WPRM блока.
        time_type: 'prep', 'cook', 'total'
        """
        wprm = self._get_wprm()
        if not wprm:
            return None

        # Ищем span с нужным классом, например wprm-recipe-cook_time-minutes
        minutes_span = wprm.find('span', class_=re.compile(
            rf'wprm-recipe-{time_type}_time-minutes', re.I))
        hours_span = wprm.find('span', class_=re.compile(
            rf'wprm-recipe-{time_type}_time-hours', re.I))

        hours = 0
        minutes = 0

        if hours_span:
            try:
                hours = int(re.search(r'\d+', hours_span.get_text()).group())
            except (AttributeError, ValueError):
                pass

        if minutes_span:
            try:
                minutes = int(re.search(r'\d+', minutes_span.get_text()).group())
            except (AttributeError, ValueError):
                pass

        total = hours * 60 + minutes
        if total <= 0:
            return None

        if total < 60:
            return f"{total} minutes"
        elif total % 60 == 0:
            return f"{total // 60} hours"
        else:
            return f"{total // 60} hours {total % 60} minutes"

    def _extract_time_from_text(self, text: str) -> Optional[str]:
        """Извлечение времени из произвольного текста (старый формат)."""
        if not text:
            return None

        # Ищем паттерны вида "около 30 минути" / "20 минути"
        m = re.search(r'(?:около\s+)?(\d+)\s+минут', text, re.I)
        if m:
            minutes = int(m.group(1))
            return f"{minutes} minutes"

        m = re.search(r'(?:около\s+)?(\d+)\s+час', text, re.I)
        if m:
            hours = int(m.group(1))
            return f"{hours} hours"

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки."""
        return self._extract_wprm_time('prep')

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления."""
        t = self._extract_wprm_time('cook')
        if t:
            return t

        # Старый формат — ищем время в тексте инструкций
        steps_text = self.extract_steps()
        if steps_text:
            return self._extract_time_from_text(steps_text)

        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени."""
        t = self._extract_wprm_time('total')
        if t:
            return t

        # Если нет отдельного total_time, но есть cook + prep — суммируем
        cook = self._extract_wprm_time('cook')
        prep = self._extract_wprm_time('prep')

        if cook and prep:
            def _to_minutes(s: str) -> int:
                h = re.search(r'(\d+)\s+hour', s)
                m = re.search(r'(\d+)\s+min', s)
                return (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)

            total = _to_minutes(cook) + _to_minutes(prep)
            if total > 0:
                if total < 60:
                    return f"{total} minutes"
                elif total % 60 == 0:
                    return f"{total // 60} hours"
                else:
                    return f"{total // 60} hours {total % 60} minutes"
        elif cook:
            return cook

        return None

    # ------------------------------------------------------------------ #
    # Заметки                                                               #
    # ------------------------------------------------------------------ #

    def _is_notes_paragraph(self, p_elem) -> bool:
        """Проверяет, является ли абзац блоком заметок."""
        text = p_elem.get_text(strip=True)
        return bool(text and (text.startswith('*') or
                               re.match(r'^по желание', text, re.I)))

    def extract_notes(self) -> Optional[str]:
        """Извлечение дополнительных заметок к рецепту."""
        entry = self._get_entry_content()
        if not entry:
            return None

        wprm_container = self._get_wprm_container()
        search_root = wprm_container or entry

        # Ищем абзац, начинающийся с '*' или 'По желание'
        siblings = (search_root.next_siblings
                    if wprm_container
                    else entry.children)

        for elem in siblings:
            if not hasattr(elem, 'name') or not elem.name:
                continue
            if elem.name == 'p' and self._is_notes_paragraph(elem):
                text = self.clean_text(elem.get_text(separator=' '))
                # Убираем ведущую звёздочку
                text = re.sub(r'^\*\s*', '', text).strip()
                return text if text else None

        return None

    # ------------------------------------------------------------------ #
    # Теги                                                                  #
    # ------------------------------------------------------------------ #

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов статьи."""
        tag_bar = self.soup.find('div', class_='tag-bar')
        if tag_bar:
            tags = [self.clean_text(a.get_text()) 
                    for a in tag_bar.find_all('a', rel='tag')]
            if tags:
                # Добавляем cuisine из WPRM как дополнительный тег
                wprm = self._get_wprm()
                if wprm:
                    cuisine = wprm.find('span', class_='wprm-recipe-cuisine')
                    if cuisine:
                        cuis_text = self.clean_text(cuisine.get_text())
                        if cuis_text and cuis_text not in tags:
                            tags.append(cuis_text)
                return ', '.join(tags)

        # Fallback: теги из rel="tag" атрибута
        tag_links = self.soup.find_all('a', rel='tag')
        if tag_links:
            tags = [self.clean_text(a.get_text()) for a in tag_links]
            return ', '.join(filter(None, tags))

        return None

    # ------------------------------------------------------------------ #
    # Изображения                                                           #
    # ------------------------------------------------------------------ #

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта."""
        urls = []
        seen = set()

        def _add(url: str):
            if url and url not in seen and 'svg+xml' not in url:
                seen.add(url)
                urls.append(url)

        # 1. og:image — главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            _add(og_image['content'])

        # 2. WPRM image — ссылка на основное фото рецепта
        wprm_img_div = self.soup.find('div', class_='wprm-recipe-image')
        if wprm_img_div:
            a = wprm_img_div.find('a')
            if a and a.get('href'):
                _add(a['href'])
            for img in wprm_img_div.find_all('img'):
                src = img.get('src') or img.get('data-lazy-src')
                if src and src.startswith('http'):
                    _add(src)

        # 3. Слайдшоу Jetpack
        slideshow = self.soup.find('div', class_='wp-block-jetpack-slideshow')
        if slideshow:
            for img in slideshow.find_all('img'):
                src = img.get('src') or img.get('data-lazy-src')
                if src and src.startswith('http'):
                    _add(src)

        return ','.join(urls) if urls else None

    # ------------------------------------------------------------------ #
    # Главный метод                                                         #
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
            instructions = self.extract_steps()
            category = self.extract_category()
            notes = self.extract_notes()
            tags = self.extract_tags()

            return {
                'dish_name': dish_name,
                'description': description,
                'ingredients': ingredients,
                'instructions': instructions,
                'category': category,
                'prep_time': self.extract_prep_time(),
                'cook_time': self.extract_cook_time(),
                'total_time': self.extract_total_time(),
                'notes': notes,
                'image_urls': self.extract_image_urls(),
                'tags': tags,
            }
        except Exception as exc:
            logger.error('Ошибка при извлечении данных из %s: %s', self.html_path, exc)
            return {
                'dish_name': None,
                'description': None,
                'ingredients': None,
                'instructions': None,
                'category': None,
                'prep_time': None,
                'cook_time': None,
                'total_time': None,
                'notes': None,
                'image_urls': None,
                'tags': None,
            }


def main():
    import os
    recipes_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'preprocessed', 'sled5_bg'
    )
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(Sled5BgExtractor, recipes_dir)
        return

    print(f'Директория не найдена: {recipes_dir}')
    print('Использование: python sled5_bg.py')


if __name__ == '__main__':
    main()
