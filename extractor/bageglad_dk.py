"""
Экстрактор данных рецептов для сайта bageglad.dk

bageglad.dk — датский кулинарный блог на WordPress,
использующий плагин WP Recipe Maker (WPRM) для разметки рецептов.
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


class BageGladDkExtractor(BaseRecipeExtractor):
    """Экстрактор для bageglad.dk (WordPress + WP Recipe Maker)"""

    # ------------------------------------------------------------------ #
    # Внутренние вспомогательные методы                                   #
    # ------------------------------------------------------------------ #

    def _get_json_ld_graph(self) -> list:
        """Возвращает список узлов из JSON-LD @graph (или пустой список)."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
                if isinstance(data, dict) and '@graph' in data:
                    return data['@graph']
            except (json.JSONDecodeError, AttributeError):
                continue
        return []

    def _wprm_time(self, time_type: str) -> Optional[str]:
        """
        Извлекает время из WPRM-контейнера (prep / cook / total).

        WPRM рендерит каждый тип в отдельный блок:
          wprm-recipe-{type}-time-container
        Внутри — span-ы с классами:
          wprm-recipe-{type}_time-hours   (часы)
          wprm-recipe-{type}_time-minutes (минуты)
        """
        container = self.soup.find(class_=f'wprm-recipe-{time_type}-time-container')
        if not container:
            return None

        hours_el = container.find(class_=f'wprm-recipe-{time_type}_time-hours')
        mins_el = container.find(class_=f'wprm-recipe-{time_type}_time-minutes')

        hours = 0
        minutes = 0

        if hours_el:
            # Удаляем screen-reader текст перед извлечением числа
            for sr in hours_el.find_all(class_='sr-only'):
                sr.decompose()
            try:
                hours = int(hours_el.get_text(strip=True))
            except ValueError:
                logger.debug('Не удалось распарсить часы для %s_time', time_type)

        if mins_el:
            for sr in mins_el.find_all(class_='sr-only'):
                sr.decompose()
            try:
                minutes = int(mins_el.get_text(strip=True))
            except ValueError:
                logger.debug('Не удалось распарсить минуты для %s_time', time_type)

        if hours == 0 and minutes == 0:
            return None

        if hours > 0 and minutes > 0:
            return f'{hours} hours {minutes} minutes'
        if hours > 0:
            return f'{hours} hours'
        return f'{minutes} minutes'

    # ------------------------------------------------------------------ #
    # Публичные методы извлечения полей                                   #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда.

        Приоритет:
        1. H1 (страница bageglad.dk обычно содержит два H1: «Menu» в навигации
           и фактическое название рецепта).
        2. Элемент WPRM wprm-recipe-name.
        3. <title> страницы.
        """
        for h1 in self.soup.find_all('h1'):
            text = self.clean_text(h1.get_text())
            if text and text.lower() != 'menu':
                return text

        wprm_name = self.soup.find(class_='wprm-recipe-name')
        if wprm_name:
            return self.clean_text(wprm_name.get_text())

        title_tag = self.soup.find('title')
        if title_tag:
            return self.clean_text(title_tag.get_text())

        logger.warning('Не удалось извлечь название блюда из %s', self.html_path)
        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение краткого описания рецепта.

        Приоритет:
        1. WPRM summary (wprm-recipe-summary) — описание внутри карточки рецепта.
        2. Второй тег meta[name=description] — добавляется WPRM и содержит
           описание рецепта (первый тег — SEO-описание от Yoast/RankMath).
        3. Первый тег meta[name=description] — запасной вариант.
        """
        wprm_summary = self.soup.find(class_='wprm-recipe-summary')
        if wprm_summary:
            text = self.clean_text(wprm_summary.get_text())
            if text:
                return text

        all_meta_descs = self.soup.find_all('meta', {'name': 'description'})
        # На bageglad.dk второй тег meta description — это WPRM-описание рецепта
        if len(all_meta_descs) >= 2:
            content = all_meta_descs[1].get('content', '').strip()
            if content:
                return self.clean_text(content)

        if all_meta_descs:
            content = all_meta_descs[0].get('content', '').strip()
            if content:
                return self.clean_text(content)

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из WPRM-блока.

        WPRM сериализует каждый ингредиент в отдельный li.wprm-recipe-ingredient
        с дочерними span-ами:
          wprm-recipe-ingredient-amount  → количество
          wprm-recipe-ingredient-unit    → единица измерения
          wprm-recipe-ingredient-name    → название
        """
        container = self.soup.find(class_='wprm-recipe-ingredients-container')
        if not container:
            logger.warning('Блок ингредиентов не найден в %s', self.html_path)
            return None

        ingredients = []
        for item in container.find_all(class_='wprm-recipe-ingredient'):
            amount_el = item.find(class_='wprm-recipe-ingredient-amount')
            unit_el = item.find(class_='wprm-recipe-ingredient-unit')
            name_el = item.find(class_='wprm-recipe-ingredient-name')

            amount = self.clean_text(amount_el.get_text()) if amount_el else None
            unit = self.clean_text(unit_el.get_text()) if unit_el else None
            name_raw = self.clean_text(name_el.get_text()) if name_el else None

            if not name_raw:
                continue

            # Удаляем маркеры сносок (*, **, †, ‡ и т.п.) из конца названия
            name = re.sub(r'[\*†‡]+$', '', name_raw).strip()

            ingredients.append({
                'name': name,
                'amount': amount,
                'unit': unit,
            })

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления из WPRM-блока.

        WPRM хранит каждый шаг в li.wprm-recipe-instruction с дочерним
        div/span.wprm-recipe-instruction-text.
        """
        container = self.soup.find(class_='wprm-recipe-instructions-container')
        if not container:
            logger.warning('Блок инструкций не найден в %s', self.html_path)
            return None

        steps = []
        for step in container.find_all(class_='wprm-recipe-instruction'):
            text_el = step.find(class_='wprm-recipe-instruction-text')
            text = self.clean_text(
                text_el.get_text(separator=' ') if text_el else step.get_text(separator=' ')
            )
            if text:
                steps.append(text)

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта.

        Приоритет:
        1. Предпоследний элемент BreadcrumbList из JSON-LD @graph
           (последний элемент — сам рецепт, предпоследний — ближайшая категория).
        2. Первый элемент articleSection из Article JSON-LD, не являющийся
           «Alle opskrifter» / «Alle indlæg».
        """
        graph = self._get_json_ld_graph()

        for node in graph:
            if node.get('@type') == 'BreadcrumbList':
                items = node.get('itemListElement', [])
                # Предпоследний — непосредственная родительская категория
                if len(items) >= 2:
                    cat = items[-2].get('name', '')
                    cat = self.clean_text(cat)
                    if cat:
                        return cat

        # Запасной вариант: articleSection из Article-узла
        generic = {'alle opskrifter', 'alle indlæg'}
        for node in graph:
            if node.get('@type') == 'Article':
                sections = node.get('articleSection', [])
                if isinstance(sections, list):
                    for section in sections:
                        s = self.clean_text(section)
                        if s and s.lower() not in generic:
                            return s

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки из WPRM."""
        return self._wprm_time('prep')

    def extract_cook_time(self) -> Optional[str]:
        """Время приготовления из WPRM."""
        return self._wprm_time('cook')

    def extract_total_time(self) -> Optional[str]:
        """Общее время из WPRM."""
        return self._wprm_time('total')

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок из WPRM-блока нот (wprm-recipe-notes-container).

        Заголовок («Noter») пропускается. Маркеры сносок (* ** †) удаляются.
        """
        container = self.soup.find(class_='wprm-recipe-notes-container')
        if not container:
            return None

        # Собираем только содержимое div.wprm-recipe-notes (без заголовка)
        notes_div = container.find(class_='wprm-recipe-notes')
        if notes_div:
            text = self.clean_text(notes_div.get_text(separator=' '))
        else:
            # Резервный вариант: весь текст контейнера без заголовка h3
            header = container.find(class_='wprm-recipe-header')
            if header:
                header.decompose()
            text = self.clean_text(container.get_text(separator=' '))

        if not text:
            return None

        # Удаляем маркеры сносок в начале каждого предложения (* **)
        text = re.sub(r'\*+', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text if text else None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD Article.keywords.

        keywords — список строк, возвращается как строка через «, ».
        Значения приводятся к нижнему регистру.
        """
        graph = self._get_json_ld_graph()
        for node in graph:
            if node.get('@type') == 'Article':
                keywords = node.get('keywords', [])
                if isinstance(keywords, list) and keywords:
                    tags = [self.clean_text(k).lower() for k in keywords if k]
                    return ', '.join(t for t in tags if t) or None
                if isinstance(keywords, str) and keywords.strip():
                    return self.clean_text(keywords).lower()
        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений.

        Приоритет:
        1. og:image — главная картинка страницы.
        2. JSON-LD ImageObject (contentUrl / url) из @graph.
        3. thumbnailUrl из Article/WebPage узла JSON-LD.
        """
        urls: list[str] = []
        seen: set[str] = set()

        def _add(url: Optional[str]) -> None:
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        og_image = self.soup.find('meta', property='og:image')
        if og_image:
            _add(og_image.get('content'))

        graph = self._get_json_ld_graph()
        for node in graph:
            if node.get('@type') == 'ImageObject':
                _add(node.get('contentUrl') or node.get('url'))
            thumb = node.get('thumbnailUrl')
            if thumb:
                _add(thumb)

        return ','.join(urls) if urls else None

    # ------------------------------------------------------------------ #
    # Точка входа                                                         #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта из HTML-страницы bageglad.dk.

        Returns:
            Словарь со всеми полями рецепта. Отсутствующие значения — None.
        """
        try:
            dish_name = self.extract_dish_name()
            description = self.extract_description()
            ingredients = self.extract_ingredients()
            instructions = self.extract_steps()
            category = self.extract_category()
            prep_time = self.extract_prep_time()
            cook_time = self.extract_cook_time()
            total_time = self.extract_total_time()
            notes = self.extract_notes()
            tags = self.extract_tags()
            image_urls = self.extract_image_urls()
        except Exception:
            logger.exception('Критическая ошибка при обработке %s', self.html_path)
            dish_name = description = ingredients = instructions = None
            category = prep_time = cook_time = total_time = None
            notes = tags = image_urls = None

        return {
            'dish_name': dish_name,
            'description': description,
            'ingredients': ingredients,
            'instructions': instructions,
            'category': category,
            'prep_time': prep_time,
            'cook_time': cook_time,
            'total_time': total_time,
            'notes': notes,
            'image_urls': image_urls,
            'tags': tags,
        }


def main() -> None:
    """Точка входа: обрабатывает все HTML-файлы в preprocessed/bageglad_dk."""
    import os

    preprocessed_dir = os.path.join('preprocessed', 'bageglad_dk')
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(BageGladDkExtractor, preprocessed_dir)
        return

    print(f'Директория не найдена: {preprocessed_dir}')
    print('Использование: python bageglad_dk.py')


if __name__ == '__main__':
    main()
