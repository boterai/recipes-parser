"""
Экстрактор данных рецептов для сайта rambler.ru
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


class RamblerRuExtractor(BaseRecipeExtractor):
    """Экстрактор для rambler.ru"""

    # ---------------------------------------------------------------------------
    # Внутренние хелперы
    # ---------------------------------------------------------------------------

    def _get_article_ld_json(self) -> Optional[dict]:
        """Возвращает первый скрипт LD+JSON с @type == 'Article'."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Article':
                    return data
            except (json.JSONDecodeError, KeyError):
                continue
        return None

    def _get_preloaded_state(self) -> Optional[dict]:
        """
        Извлекает объект window.__PRELOADED_STATE__ из inline-скрипта.
        Заменяет undefined / NaN → null для корректного JSON-парсинга.
        """
        for script in self.soup.find_all('script'):
            text = script.string or ''
            idx = text.find('window.__PRELOADED_STATE__ = ')
            if idx < 0:
                continue
            start = idx + len('window.__PRELOADED_STATE__ = ')
            brace_count = 0
            end = start
            for i, ch in enumerate(text[start:], start=start):
                if ch == '{':
                    brace_count += 1
                elif ch == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end = i + 1
                        break
            raw = text[start:end]
            clean = re.sub(r'\bundefined\b', 'null', raw)
            clean = re.sub(r'\bNaN\b', 'null', clean)
            try:
                return json.loads(clean)
            except json.JSONDecodeError as exc:
                logger.warning('Не удалось разобрать __PRELOADED_STATE__: %s', exc)
        return None

    def _get_article_entry(self) -> Optional[dict]:
        """
        Возвращает словарь статьи из commonData.entries.entities
        (первый и единственный ключ для страниц рецептов).
        """
        state = self._get_preloaded_state()
        if not state:
            return None
        entities = (
            state.get('commonData', {})
            .get('entries', {})
            .get('entities', {})
        )
        if not entities:
            return None
        article_id = next(iter(entities))
        return entities.get(article_id)

    def _get_draft_blocks(self) -> list:
        """Возвращает список draft.blocks из данных статьи."""
        entry = self._get_article_entry()
        if not entry:
            return []
        return entry.get('draft', {}).get('blocks', []) or []

    # ---------------------------------------------------------------------------
    # Парсинг ингредиентов
    # ---------------------------------------------------------------------------

    @staticmethod
    def _parse_amount(raw: str) -> Optional[object]:
        """
        Конвертирует строку с количеством в число (int / float) или
        возвращает исходную строку, если число не выражено.
        """
        if not raw:
            return None
        raw = raw.strip()
        # Диапазоны вида "2–3" или "30–50" — берём как строку
        if re.search(r'[–—-]', raw):
            return raw
        # Дробь вида "1/4"
        if '/' in raw:
            parts = raw.split()
            total = 0.0
            for part in parts:
                part = part.strip()
                if '/' in part:
                    try:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    except (ValueError, ZeroDivisionError):
                        return raw
                else:
                    try:
                        total += float(part.replace(',', '.'))
                    except ValueError:
                        return raw
            return int(total) if total == int(total) else total
        # Обычное число
        try:
            val = float(raw.replace(',', '.'))
            return int(val) if val == int(val) else val
        except ValueError:
            return raw if raw else None

    def _parse_russian_ingredient(self, text: str) -> Optional[dict]:
        """
        Разбирает строку ингредиента (русский текст) в структуру
        {"name": ..., "amount": ..., "unit": ...}.

        Поддерживаемые форматы:
          1. «name — amount unit» (кукурузный крахмал — 1/4 стакана)
          2. «amount unit name (комментарий)» (500 г молока (не обезжиренного))
          3. «name — по вкусу»
        """
        if not text:
            return None

        text = self.clean_text(text).rstrip(';').strip()
        if not text:
            return None

        # Шаблон с единицами измерения (русские)
        ru_units = (
            r'(?:г|гр|кг|мл|л|мг'
            r'|ст\.?\s*л\.?|ч\.?\s*л\.?'
            r'|шт\.?|штук[а-яА-Я]*'
            r'|стакан[а-яА-Я]*'
            r'|кусочк[а-яА-Я]*'
            r'|щепотк[а-яА-Я]*'
            r'|пучк[а-яА-Я]*'
            r'|горст[а-яА-Я]*'
            r'|веточк[а-яА-Я]*'
            r'|зубчик[а-яА-Я]*)'
        )

        # ── Формат 1: «name — amount unit» или «name — по вкусу» ──────────────
        if ' — ' in text or ' – ' in text:
            sep = ' — ' if ' — ' in text else ' – '
            parts = text.split(sep, 1)
            name = parts[0].strip()
            rest = parts[1].strip() if len(parts) > 1 else ''

            # "по вкусу" и похожие
            if re.match(r'^по\s+\w+', rest, re.IGNORECASE):
                return {'name': name, 'amount': None, 'unit': rest}

            # «amount unit»
            m = re.match(
                rf'^([\d.,/\s]+)\s*({ru_units})\b(.*)$',
                rest, re.IGNORECASE
            )
            if m:
                amount = self._parse_amount(m.group(1).strip())
                unit = m.group(2).strip()
                return {'name': name, 'amount': amount, 'unit': unit}

            # Просто число без явной единицы
            m2 = re.match(r'^([\d.,/–—\s-]+)\s*$', rest)
            if m2:
                amount = self._parse_amount(m2.group(1).strip())
                return {'name': name, 'amount': amount, 'unit': None}

            # rest — всё, что осталось, считаем единицей
            return {'name': name, 'amount': None, 'unit': rest if rest else None}

        # ── Формат 2: «amount unit name» ──────────────────────────────────────
        m = re.match(
            rf'^([\d.,/–—\s]+)\s*({ru_units})\s+(.+)$',
            text, re.IGNORECASE
        )
        if m:
            amount = self._parse_amount(m.group(1).strip())
            unit = m.group(2).strip()
            name = m.group(3).strip()
            # Убираем комментарии в скобках
            name = re.sub(r'\s*\([^)]*\)', '', name).strip().rstrip(';').strip()
            if not name:
                return None
            return {'name': name, 'amount': amount, 'unit': unit}

        # ── Формат 3: только название (без количества) ────────────────────────
        name = re.sub(r'\s*\([^)]*\)', '', text).strip().rstrip(';').strip()
        if name:
            return {'name': name, 'amount': None, 'unit': None}
        return None

    def _is_ingredient_list(self, items: list) -> bool:
        """
        Эвристика: проверяет, является ли список ингредиентным (а не советами).

        Ингредиентные пункты обычно:
        - короткие (avg < 150 символов),
        - содержат число или разделитель «—».
        Советы — длинные предложения без количеств.
        """
        if not items:
            return False
        texts = [
            (item.get('text', '') if isinstance(item, dict) else str(item))
            for item in items
        ]
        avg_len = sum(len(t) for t in texts) / len(texts)
        # Очень длинные пункты — скорее всего советы, не ингредиенты
        if avg_len > 150:
            return False
        ingredient_count = sum(
            1 for t in texts
            if re.search(r'\d', t) or ' — ' in t or ' – ' in t
        )
        return ingredient_count >= max(1, len(texts) // 2)

    # ---------------------------------------------------------------------------
    # Публичные методы извлечения
    # ---------------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда."""
        # 1. Article LD+JSON headline
        ld = self._get_article_ld_json()
        if ld and ld.get('headline'):
            return self.clean_text(ld['headline'])

        # 2. h1 в HTML
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        # 3. meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение краткого описания рецепта (первое предложение)."""
        # 1. Article LD+JSON description (первое предложение)
        ld = self._get_article_ld_json()
        if ld and ld.get('description'):
            desc = self.clean_text(ld['description'])
            # Берём только первое предложение
            first = re.split(r'(?<=[.!?])\s+', desc)[0]
            return first if first else desc

        # 2. annotation из PRELOADED_STATE
        entry = self._get_article_entry()
        if entry and entry.get('annotation'):
            desc = self.clean_text(entry['annotation'])
            first = re.split(r'(?<=[.!?])\s+', desc)[0]
            return first if first else desc

        # 3. meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            first = re.split(r'(?<=[.!?])\s+', desc)[0]
            return first if first else desc

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из draft-блоков или HTML-списков.
        Возвращает JSON-строку со списком словарей.

        Для статей с несколькими составными списками ингредиентов (например,
        основное блюдо + заправка) все смежные «ингредиентные» группы
        unordered-list-item, стоящие до первого ordered-list-item, объединяются.
        """
        blocks = self._get_draft_blocks()

        # Собираем группы смежных unordered-list-item ДО первого ordered-list-item.
        # После появления первого OL-блока ингредиентные UL-группы не берём.
        ingredient_groups: list[list[str]] = []
        current_ul: list[str] = []
        found_ol = False

        for b in blocks:
            btype = b.get('type', '')
            if found_ol:
                break
            if btype == 'unordered-list-item':
                current_ul.append(b.get('text', ''))
            else:
                if current_ul:
                    ingredient_groups.append(current_ul)
                    current_ul = []
                if btype == 'ordered-list-item':
                    found_ol = True

        if current_ul:
            ingredient_groups.append(current_ul)

        # Оставляем только группы, которые выглядят как ингредиенты
        selected_texts: list[str] = []
        for group in ingredient_groups:
            mock = [{'text': t} for t in group]
            if self._is_ingredient_list(mock):
                selected_texts.extend(group)

        # Если draft-блоки не дали результата — пробуем взять ПЕРВЫЙ
        # ингредиентный UL из всего документа (даже если он после OL).
        if not selected_texts:
            all_ul_groups: list[list[str]] = []
            current_ul2: list[str] = []
            for b in blocks:
                btype = b.get('type', '')
                if btype == 'unordered-list-item':
                    current_ul2.append(b.get('text', ''))
                else:
                    if current_ul2:
                        all_ul_groups.append(current_ul2)
                        current_ul2 = []
            if current_ul2:
                all_ul_groups.append(current_ul2)

            for group in all_ul_groups:
                mock = [{'text': t} for t in group]
                if self._is_ingredient_list(mock):
                    selected_texts = group
                    break

        # Если draft-блоки не дали результата — пробуем HTML <ul>
        if not selected_texts:
            article = self.soup.find('article')
            if article:
                # Перебираем UL-ы до первого OL
                for sibling in article.descendants:
                    if not hasattr(sibling, 'name'):
                        continue
                    if sibling.name == 'ol':
                        break
                    if sibling.name == 'ul':
                        items_text = [
                            li.get_text(separator=' ', strip=True)
                            for li in sibling.find_all('li')
                        ]
                        mock = [{'text': t} for t in items_text]
                        if self._is_ingredient_list(mock):
                            selected_texts.extend(items_text)

        if not selected_texts:
            logger.warning('%s: не найдены ингредиенты', self.html_path)
            return None

        ingredients = []
        for raw in selected_texts:
            # Некоторые строки содержат «+ дополнительный ингредиент»,
            # например: "120 г огурца без кожицы + 1 огурец для подачи"
            parts = re.split(r'\s*\+\s*', raw.rstrip(';'))
            for part in parts:
                part = part.strip().rstrip(';')
                if part:
                    parsed = self._parse_russian_ingredient(part)
                    if parsed:
                        ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """
        Извлечение шагов приготовления из draft-блоков или HTML <ol>.
        Берётся первая группа ordered-list-item.
        Возвращает строку с пронумерованными шагами.
        """
        blocks = self._get_draft_blocks()

        # Ищем первую группу ordered-list-item
        steps: list[str] = []
        in_ol = False

        for b in blocks:
            btype = b.get('type', '')
            if btype == 'ordered-list-item':
                steps.append(b.get('text', ''))
                in_ol = True
            else:
                if in_ol:
                    break   # Группа закончилась

        # Если draft-блоки не дали результата — пробуем HTML <ol>
        if not steps:
            article = self.soup.find('article')
            if article:
                ol = article.find('ol')
                if ol:
                    steps = [
                        li.get_text(separator=' ', strip=True)
                        for li in ol.find_all('li')
                        if li.get_text(strip=True)
                    ]

        if not steps:
            logger.warning('%s: не найдены инструкции', self.html_path)
            return None

        # Нумеруем, если нумерация ещё не проставлена
        numbered: list[str] = []
        for idx, step in enumerate(steps, 1):
            step_clean = self.clean_text(step)
            if step_clean:
                if not re.match(r'^\d+[\.\)]', step_clean):
                    numbered.append(f'{idx}. {step_clean}')
                else:
                    numbered.append(step_clean)

        return ' '.join(numbered) if numbered else None

    def extract_category(self) -> Optional[str]:
        """
        Категория блюда. На rambler.ru все рецепты относятся к разделу «Рецепты»
        без подкатегорий в HTML-метаданных. Возвращает None.
        """
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки. Не представлено в структурированном виде на сайте."""
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Время готовки. Не представлено в структурированном виде на сайте."""
        return None

    def extract_total_time(self) -> Optional[str]:
        """Общее время. Не представлено в структурированном виде на сайте."""
        return None

    @staticmethod
    def _is_notes_paragraph(text: str) -> bool:
        """
        Проверяет, что абзац является информативным примечанием к рецепту,
        а не ссылкой на другую статью, вступительной фразой или атрибуцией.
        """
        if not text:
            return False
        # Слишком короткий
        if len(text.split()) < 8:
            return False
        # Не заканчивается на знак конца предложения → скорее всего заголовок/ссылка
        if not re.search(r'[.!?»]$', text):
            return False
        # Паттерн атрибуции: «рассказала/рассказал «Рамблеру» ИмяФамилия»
        if re.search(r'рассказал[аи]?\s+[«»"«»]?Рамблер', text, re.IGNORECASE):
            return False
        return True

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок/советов.

        Стратегия:
        1. Ищем секцию-заголовок «Полезные советы» / «советы» и т.п.
           и берём первый содержательный (не вводный) абзац.
        2. Ищем первый h2/h3 раздел ПОСЛЕ группы ordered-list-item
           и берём первый содержательный абзац из этого раздела.
        3. Берём первый содержательный абзац сразу после OL-группы
           (финальное примечание к рецепту).
        4. EXPERT-цитата из draft-блоков (если цитата содержит практический совет).
        """
        blocks = self._get_draft_blocks()

        note_heading_pattern = re.compile(
            r'(полезн|совет|примечани|заметк|подав|хранен)', re.IGNORECASE
        )

        # ── Стратегия 1: ищем именованную «советы» секцию ────────────────────
        for i, b in enumerate(blocks):
            if b.get('type') == 'header-two' and note_heading_pattern.search(
                b.get('text', '')
            ):
                for j in range(i + 1, min(i + 20, len(blocks))):
                    nb = blocks[j]
                    nbtype = nb.get('type', '')
                    if nbtype in ('header-two', 'header-three'):
                        break
                    if nbtype == 'paragraph':
                        nt = nb.get('text', '').strip()
                        if self._is_notes_paragraph(nt):
                            return self.clean_text(nt)
                break  # искали первый подходящий заголовок

        # ── Стратегия 2 & 3: найти что-либо после OL ─────────────────────────
        in_ol = False
        ol_done = False

        for i, b in enumerate(blocks):
            btype = b.get('type', '')
            if btype == 'ordered-list-item':
                in_ol = True
            elif in_ol:
                ol_done = True
                in_ol = False

            if ol_done:
                # Стратегия 2: h2 после OL → берём первый содержательный абзац
                if btype == 'header-two':
                    for j in range(i + 1, min(i + 20, len(blocks))):
                        nb = blocks[j]
                        nbtype = nb.get('type', '')
                        if nbtype in ('header-two', 'header-three'):
                            break
                        if nbtype == 'paragraph':
                            nt = nb.get('text', '').strip()
                            if self._is_notes_paragraph(nt):
                                return self.clean_text(nt)
                    continue

                # Стратегия 3: первый содержательный абзац после OL
                if btype == 'paragraph':
                    nt = b.get('text', '').strip()
                    if self._is_notes_paragraph(nt):
                        return self.clean_text(nt)

        # ── Стратегия 4: EXPERT-цитата ────────────────────────────────────────
        state = self._get_preloaded_state()
        if state:
            entities = (
                state.get('commonData', {})
                .get('entries', {})
                .get('entities', {})
            )
            if entities:
                article_id = next(iter(entities))
                draft = entities[article_id].get('draft', {})
                entity_map = draft.get('entityMap', {})
                for entity in entity_map.values():
                    if entity.get('type') == 'EXPERT':
                        data = entity.get('data', {})
                        quote = data.get('quote', '')
                        if quote:
                            return self.clean_text(
                                re.sub(r'^[«"]|[»"]$', '', quote).strip()
                            )

        return None

    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов. Rambler не предоставляет явных тегов рецепта
        в разметке страницы — возвращает None.
        """
        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Извлечение URL изображений рецепта.
        Ищет og:image и изображения в теле статьи.
        """
        urls: list[str] = []

        # og:image (основное)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # Изображения внутри статьи
        article = self.soup.find('article')
        if article:
            for img in article.find_all('img'):
                src = (
                    img.get('src') or
                    img.get('data-src') or
                    img.get('data-lazy-src')
                )
                if src and src.startswith('http') and src not in urls:
                    # Берём только «настоящие» изображения с хостов rambler
                    if re.search(r'(rambler\.ru|store\.rambler|news\.store)', src):
                        urls.append(src)

        if not urls:
            return None

        # Убираем дубликаты, сохраняем порядок
        seen: set = set()
        unique: list[str] = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique)

    # ---------------------------------------------------------------------------
    # Основной метод
    # ---------------------------------------------------------------------------

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с полями рецепта. Все поля присутствуют;
            отсутствующие данные заполняются None.
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception:
            logger.exception('Ошибка при извлечении dish_name: %s', self.html_path)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception:
            logger.exception('Ошибка при извлечении description: %s', self.html_path)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception:
            logger.exception('Ошибка при извлечении ingredients: %s', self.html_path)
            ingredients = None

        try:
            instructions = self.extract_steps()
        except Exception:
            logger.exception('Ошибка при извлечении instructions: %s', self.html_path)
            instructions = None

        try:
            notes = self.extract_notes()
        except Exception:
            logger.exception('Ошибка при извлечении notes: %s', self.html_path)
            notes = None

        try:
            image_urls = self.extract_image_urls()
        except Exception:
            logger.exception('Ошибка при извлечении image_urls: %s', self.html_path)
            image_urls = None

        return {
            'dish_name': dish_name,
            'description': description,
            'ingredients': ingredients,
            'instructions': instructions,
            'category': self.extract_category(),
            'prep_time': self.extract_prep_time(),
            'cook_time': self.extract_cook_time(),
            'total_time': self.extract_total_time(),
            'notes': notes,
            'image_urls': image_urls,
            'tags': self.extract_tags(),
        }


def main() -> None:
    """
    Точка входа: обрабатывает все HTML-файлы из preprocessed/rambler_ru
    относительно корня репозитория.
    """
    repo_root = Path(__file__).parent.parent
    recipes_dir = repo_root / 'preprocessed' / 'rambler_ru'

    if recipes_dir.exists() and recipes_dir.is_dir():
        process_directory(RamblerRuExtractor, str(recipes_dir))
    else:
        print(f'Директория не найдена: {recipes_dir}')
        print('Использование: python rambler_ru.py')


if __name__ == '__main__':
    main()
