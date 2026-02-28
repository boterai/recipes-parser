"""
Экстрактор данных рецептов для сайта zena.net.hr
"""

import sys
import json
import re
import logging
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class ZenaNetHrExtractor(BaseRecipeExtractor):
    """Экстрактор для zena.net.hr"""

    def _get_article_text_div(self):
        """Получить основной блок текста статьи"""
        return self.soup.find('div', class_='se-article--text')

    def _is_collection_article(self) -> bool:
        """Проверить, является ли статья сборником нескольких рецептов"""
        article_text = self._get_article_text_div()
        if not article_text:
            return False
        h2_elements = article_text.find_all('h2', recursive=False)
        return len(h2_elements) >= 2

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Для статей-сборников берём первый H2 внутри текста
        if self._is_collection_article():
            article_text = self._get_article_text_div()
            if article_text:
                h2 = article_text.find('h2')
                if h2:
                    return self.clean_text(h2.get_text())

        # Для обычных статей берём H1
        h1 = self.soup.find('h1', class_='se-article--head')
        if h1:
            return self.clean_text(h1.get_text())

        # Запасной вариант: og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        article_text = self._get_article_text_div()

        # Для статей-сборников берём первый абзац после первого H2
        if self._is_collection_article() and article_text:
            h2 = article_text.find('h2')
            if h2:
                sibling = h2.next_sibling
                while sibling:
                    if hasattr(sibling, 'name') and sibling.name == 'p':
                        text = self.clean_text(sibling.get_text())
                        if text:
                            return text
                    sibling = sibling.next_sibling

        # Первый абзац тела статьи (содержит описание рецепта)
        if article_text:
            p1 = article_text.find('p', recursive=False)
            if p1:
                text = p1.get_text(' ', strip=True)
                # Убираем маркер "Sastojci:" и всё после него
                text = re.split(r'\s*Sastojci:\s*', text, flags=re.IGNORECASE)[0]
                text = self.clean_text(text)
                if text:
                    return text

        # Запасной вариант: подзаголовок статьи
        subhead = self.soup.find('div', class_='se-article--subhead')
        if subhead:
            text = self.clean_text(subhead.get_text())
            if text:
                return text

        # Запасной вариант: meta description
        for meta_name in ({'name': 'description'}, {'property': 'og:description'}):
            meta = self.soup.find('meta', meta_name)
            if meta and meta.get('content'):
                text = re.sub(r'<[^>]+>', '', meta['content'])
                text = self.clean_text(text)
                if text:
                    return text

        return None

    def _parse_ingredient(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат.

        Args:
            text: строка вида "2 zrele banane" или "100 g naribanog sira"

        Returns:
            dict с полями name, amount, units или None
        """
        if not text:
            return None

        text = self.clean_text(text)
        if not text:
            return None

        # Заменяем Unicode и текстовые дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
        }
        for sym, val in fraction_map.items():
            text = text.replace(sym, val)

        # Хорватские числительные
        word_numbers = {
            r'\bpola\b': '0.5',
            r'\bjedna\b': '1', r'\bjedan\b': '1', r'\bjedno\b': '1',
            r'\bdva\b': '2', r'\bdvije\b': '2',
            r'\btri\b': '3',
            r'\bčetiri\b': '4',
            r'\bpet\b': '5',
        }
        for pattern, replacement in word_numbers.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        # "1 i pol" -> 1.5
        text = re.sub(r'(\d+)\s+i\s+pol\b', lambda m: str(int(m.group(1)) + 0.5), text, flags=re.IGNORECASE)

        # Хорватские единицы измерения (nominativ, genitiv, akuzativ)
        units_pattern = (
            r'žlic(?:a|e|u)'
            r'|žličic(?:a|e|u)'
            r'|šalic(?:a|e|u)'
            r'|kg\b'
            r'|dag\b|dkg\b'
            r'|g\b|gr\b'
            r'|dcl\b|dl\b'
            r'|ml\b'
            r'|l\b'
            r'|kom(?:ad(?:a|e)?)?\b'
            r'|prstohvat\b'
            r'|kriška(?:e|i|u)?\b'
            r'|šaka(?:e)?\b'
            r'|paket(?:a|e)?\b'
            r'|list(?:a|ova)?\b'
            r'|grančic(?:a|e|u)?\b'
            r'|kap(?:i|a)?\b'
        )

        # Паттерн: [число|диапазон] [единица] название
        match = re.match(
            r'^([\d.,/]+(?:-[\d.,/]+)?(?:\s+[\d.,/]+)?)?\s*(' + units_pattern + r')?\s+(.+)$',
            text,
            re.IGNORECASE
        )

        if match:
            amount_str, unit, name = match.groups()
        else:
            # Только число/диапазон + название (без единицы)
            match2 = re.match(r'^([\d.,/]+(?:-[\d.,/]+)?)\s+(.+)$', text)
            if match2:
                amount_str, name = match2.groups()
                unit = None
            else:
                return {'name': text, 'amount': None, 'units': None}

        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Диапазон типа "2-3" оставляем как строку
            if re.match(r'^\d+(?:[.,]\d+)?-\d+(?:[.,]\d+)?$', amount_str):
                amount = amount_str
            elif '/' in amount_str:
                parts = amount_str.split()
                total = 0.0
                for part in parts:
                    if '/' in part:
                        try:
                            num, denom = part.split('/', 1)
                            total += float(num) / float(denom)
                        except (ValueError, ZeroDivisionError):
                            pass
                    else:
                        try:
                            total += float(part.replace(',', '.'))
                        except ValueError:
                            pass
                amount = total if total != 0.0 else None
            else:
                try:
                    amount = float(amount_str.replace(',', '.').strip())
                except ValueError:
                    amount = amount_str.strip() if amount_str.strip() else None

        # Очистка названия
        name = self.clean_text(name) if name else text
        name = re.sub(r'\s+', ' ', name).strip()

        if not name or len(name) < 2:
            return None

        return {
            'name': name,
            'amount': amount,
            'units': unit.strip() if unit else None,
        }

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        article_text = self._get_article_text_div()
        if not article_text:
            return None

        # Берём первый <itemizedlist> в тексте статьи
        itemizedlist = article_text.find('itemizedlist')
        if not itemizedlist:
            itemizedlist = article_text.find('ul')

        if not itemizedlist:
            return None

        ingredients = []

        # Пробуем <listitem> (кастомные теги сайта)
        items = itemizedlist.find_all('listitem')
        if not items:
            items = itemizedlist.find_all('li')

        for item in items:
            raw = item.get_text(' ', strip=True)
            if raw:
                parsed = self._parse_ingredient(raw)
                if parsed:
                    ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        article_text = self._get_article_text_div()
        if not article_text:
            return None

        # 1. Если есть <orderedlist> — шаги в порядке очерёдности
        orderedlist = article_text.find('orderedlist')
        if orderedlist:
            steps = []
            for item in orderedlist.find_all('listitem'):
                text = item.get_text(' ', strip=True)
                if text:
                    steps.append(text)
            if steps:
                return ' '.join(steps)

        # 2. Несколько <p> после заголовка "Postupak" / "Priprema"
        paragraphs = list(article_text.find_all('p', recursive=False))
        header_idx = None
        for i, p in enumerate(paragraphs):
            strong = p.find('strong')
            if strong:
                strong_text = strong.get_text(strip=True)
                if re.search(r'Postupak|Priprema', strong_text, re.I):
                    header_idx = i
                    break

        if header_idx is not None:
            steps = []
            for p in paragraphs[header_idx + 1:]:
                # Пропускаем пустые и элементы внедрения (embeds)
                if p.parent.name != 'div' or 'se-article--text' not in (p.parent.get('class') or []):
                    continue
                text = p.get_text(' ', strip=True)
                if text:
                    steps.append(text)
            if steps:
                return ' '.join(steps)

        # 3. Единый абзац с вложенными hmn:linebreak (шаги уже пронумерованы)
        for p in paragraphs:
            text = p.get_text(' ', strip=True)
            if re.search(r'Priprema:|Postupak', text, re.I) and len(text) > 50:
                # Убираем заголовок "Priprema:"
                text = re.sub(r'^Priprema:\s*', '', text, flags=re.I)
                text = re.sub(r'^Postupak[^:]*:\s*', '', text, flags=re.I)
                # Нормализуем "1.Zagrij" -> "1. Zagrij"
                text = re.sub(r'(\d+)\.([^\s\d])', r'\1. \2', text)
                return self.clean_text(text)

        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Из ссылки с именем раздела
        section_link = self.soup.find('a', class_='se-article--section-name')
        if section_link:
            text = self.clean_text(section_link.get_text())
            if text:
                return text

        # Из суперзаголовка
        supertitle = self.soup.find('div', class_='se-article--supertitle')
        if supertitle:
            text = self.clean_text(supertitle.get_text())
            if text:
                return text

        # Из мета-тега раздела
        meta_section = self.soup.find('meta', attrs={'name': 'se:articleSectionName'})
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])

        return None

    def _extract_time_from_text(self, text: str, time_type: str) -> Optional[str]:
        """
        Извлечение времени приготовления/подготовки из текста.

        Args:
            text: полный текст статьи
            time_type: 'cook', 'prep' или 'total'

        Returns:
            Время в формате "X minutes" или None
        """
        if not text:
            return None

        if time_type == 'cook':
            patterns = [
                r'peci\s+(?:oko\s+)?(\d+)\s*(?:-ak)?\s*minut',
                r'kuhaj?\s+(?:oko\s+)?(\d+)\s*(?:-ak)?\s*minut',
                r'peče\s+se\s+(?:oko\s+)?(\d+)\s*(?:-ak)?\s*minut',
                r'za\s+(?:otprilike\s+)?(\d+)\s+minut\w*\s+stavimo',
                r'gotov(?:a|o)?\s+(?:u\s+)?(\d+)\s+(?:samo\s+)?minut',
            ]
        elif time_type == 'prep':
            patterns = [
                r'minimalno\s+(\d+)\s+minut',
                r'ostavit[ie]?\s+[^\d]*(\d+)\s+minut',
                r'stoji\s+(?:circa|oko|minimalno\s+)?(\d+)\s+minut',
                r'priprema\s+traje\s+(?:oko\s+)?(\d+)\s+minut',
            ]
        else:  # total
            patterns = [
                r'ukupno\s+(?:oko\s+)?(\d+)\s+minut',
                r'gotov(?:a|o)?\s+za\s+(?:oko\s+)?(\d+)\s+minut',
            ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    minutes = int(match.group(1))
                    return f'{minutes} minutes'
                except (ValueError, IndexError):
                    pass

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        article_text = self._get_article_text_div()
        if article_text:
            return self._extract_time_from_text(
                article_text.get_text(' ', strip=True), 'prep'
            )
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        article_text = self._get_article_text_div()
        if article_text:
            return self._extract_time_from_text(
                article_text.get_text(' ', strip=True), 'cook'
            )
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        article_text = self._get_article_text_div()
        if article_text:
            return self._extract_time_from_text(
                article_text.get_text(' ', strip=True), 'total'
            )
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок к рецепту"""
        # На zena.net.hr нет выделенной секции заметок
        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из контейнера тем"""
        tags_container = self.soup.find('div', class_='se-article--tags-container')
        if not tags_container:
            return None

        tags = []
        for a in tags_container.find_all('a'):
            href = a.get('href', '')
            if '/tema/' in href:
                text = self.clean_text(a.get_text())
                if text:
                    tags.append(text.lower())

        return ', '.join(tags) if tags else None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls = []

        # og:image — главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # Изображение в тексте статьи
        article_text = self._get_article_text_div()
        if article_text:
            for img in article_text.find_all('img'):
                src = img.get('src') or img.get('data-src', '')
                if (src and src not in urls
                        and not src.startswith('/static')
                        and 'placeholder' not in src
                        and src.startswith(('http', '/'))):
                    if src.startswith('/'):
                        src = 'https://zena.net.hr' + src
                    urls.append(src)

        # Дедупликация
        seen: set = set()
        unique = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта
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
    import os
    recipes_dir = os.path.join('preprocessed', 'zena_net_hr')
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(ZenaNetHrExtractor, str(recipes_dir))
        return

    print(f'Директория не найдена: {recipes_dir}')


if __name__ == '__main__':
    main()
