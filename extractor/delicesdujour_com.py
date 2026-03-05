"""
Экстрактор данных рецептов для сайта delicesdujour.com
"""

import sys
import logging
from pathlib import Path
import json
import re
from typing import Optional, Union

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class DelicesDuJourExtractor(BaseRecipeExtractor):
    """Экстрактор для delicesdujour.com"""

    # Французские единицы измерения (упорядочены по убыванию длины для
    # предотвращения частичных совпадений)
    _FRENCH_UNITS: list[tuple[str, str]] = [
        (r'cuill[eè]res?\s+à\s+soupe', 'cuillère à soupe'),
        (r'cuill[eè]res?\s+à\s+caf[eé]', 'cuillère à café'),
        (r'c\.\s*à\s*soupe', 'c. à soupe'),
        (r'c\.\s*à\s*caf[eé]', 'c. à café'),
        (r'kg', 'kg'),
        (r'g(?!\w)', 'g'),
        (r'cl', 'cl'),
        (r'dl', 'dl'),
        (r'ml', 'ml'),
        (r'l(?![a-z])', 'l'),
    ]

    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных Recipe из JSON-LD скриптов страницы."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        if 'Recipe' in item_type:
                            return item
                    elif item_type == 'Recipe':
                        return item
            except (json.JSONDecodeError, KeyError, AttributeError) as exc:
                logger.debug('Ошибка парсинга JSON-LD: %s', exc)
        return None

    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат «X minutes».

        Args:
            duration: строка вида «PT20M» или «PT1H30M»

        Returns:
            Строка вида «20 minutes», «90 minutes» и т.п., либо None
        """
        if not duration or not duration.startswith('PT'):
            return None

        body = duration[2:]  # убираем «PT»
        hours = 0
        minutes = 0

        hour_match = re.search(r'(\d+)H', body)
        if hour_match:
            hours = int(hour_match.group(1))

        min_match = re.search(r'(\d+)M', body)
        if min_match:
            minutes = int(min_match.group(1))

        total = hours * 60 + minutes
        return f'{total} minutes' if total > 0 else None

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда."""
        json_ld = self._get_json_ld_data()
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])

        h1 = self.soup.find('h1', class_='landing__title')
        if h1:
            return self.clean_text(h1.get_text())

        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта."""
        json_ld = self._get_json_ld_data()
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])

        meta = self.soup.find('meta', {'name': 'description'})
        if meta and meta.get('content'):
            return self.clean_text(meta['content'])

        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    @staticmethod
    def _parse_numeric_amount(amount_str: str) -> Union[int, float, str, None]:
        """Преобразует строку с числом/дробью в числовое значение."""
        if not amount_str:
            return None
        s = amount_str.strip().replace(',', '.')
        if '/' in s:
            try:
                num, denom = s.split('/')
                val = float(num.strip()) / float(denom.strip())
                return int(val) if val.is_integer() else val
            except (ValueError, ZeroDivisionError):
                return amount_str
        try:
            val = float(s)
            return int(val) if val.is_integer() else val
        except ValueError:
            return amount_str

    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсит строку французского ингредиента в структурированный словарь.

        Args:
            ingredient_text: строка вида «500 g de filets de morue dessalée»

        Returns:
            dict с ключами name, amount, unit или None
        """
        if not ingredient_text:
            return None

        text = self.clean_text(ingredient_text)

        # Заменяем Unicode-дроби
        for frac, val in {'½': '1/2', '¼': '1/4', '¾': '3/4', '⅓': '1/3', '⅔': '2/3'}.items():
            text = text.replace(frac, val)

        # Убираем пояснения в скобках (например, «(30 % pour fouetter)»)
        text = re.sub(r'\s*\([^)]*\)', '', text).strip()

        if not text:
            return None

        # Строка начинается с буквы → просто название, нет количества
        if not re.match(r'^[\d/]', text):
            return {'name': text, 'amount': None, 'unit': None}

        # Извлекаем ведущее число или дробь (например «500», «1/2», «0.5»)
        num_match = re.match(r'^([\d]+(?:[.,]\d+)?|[\d]+\s*/\s*[\d]+)\s+(.*)', text)
        if not num_match:
            return {'name': text, 'amount': None, 'unit': None}

        amount_str = num_match.group(1).strip()
        remainder = num_match.group(2).strip()
        amount = self._parse_numeric_amount(amount_str)

        # Проверяем каждую известную единицу измерения
        for unit_re, unit_str in self._FRENCH_UNITS:
            # Шаблон: {unit} (de|d'|d') {name}
            m = re.match(
                rf"^(?:{unit_re})\s+(?:de?\s+|d['\u2019])(.+)$",
                remainder,
                re.IGNORECASE,
            )
            if m:
                name = m.group(1).strip()
                return {'name': name, 'amount': amount, 'unit': unit_str}

        # Нет единицы. Проверяем только пробельную связку «<слово> de <название>»
        # (например «1/2 bouquet de basilic» → amount=«1/2 bouquet», name=«basilic»).
        # Сжатую форму «d'» здесь НЕ разбиваем — она часть составного названия
        # (например «3 gousses d'ail» → amount=3, name=«gousses d'ail»).
        m = re.match(r'^(\S+)\s+de\s+(.+)$', remainder, re.IGNORECASE)
        if m:
            pre_de = m.group(1).strip()
            name = m.group(2).strip()
            new_amount = f'{amount_str} {pre_de}'
            return {'name': name, 'amount': new_amount, 'unit': None}

        # Число сразу за названием, без единицы и связки
        return {'name': remainder, 'amount': amount, 'unit': None}

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате JSON-строки списка словарей."""
        json_ld = self._get_json_ld_data()
        ingredients = []

        raw_list: list[str] = []

        if json_ld and 'recipeIngredient' in json_ld:
            raw_list = json_ld['recipeIngredient']
        else:
            # Резервный вариант: из HTML-списка ингредиентов
            ingr_div = self.soup.find('div', id='recipe-ingredients')
            if ingr_div:
                for span in ingr_div.find_all('span', class_='recipe__interact-list-content'):
                    t = self.clean_text(span.get_text())
                    if t:
                        raw_list.append(t)

        for item in raw_list:
            parsed = self.parse_ingredient(item)
            if parsed:
                ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления."""
        json_ld = self._get_json_ld_data()
        steps: list[str] = []

        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        steps.append(f'{idx}. {self.clean_text(step["text"])}')
                    elif isinstance(step, str):
                        steps.append(f'{idx}. {self.clean_text(step)}')
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))

            if steps:
                return ' '.join(steps)

        # Резервный вариант: из HTML-списка инструкций
        instr_div = self.soup.find('div', id='recipe-instructions')
        if instr_div:
            for idx, p in enumerate(
                instr_div.find_all('p', class_='recipe__interact-list-content'), 1
            ):
                t = self.clean_text(p.get_text())
                if t:
                    steps.append(f'{idx}. {t}')
            if steps:
                return ' '.join(steps)

        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда."""
        json_ld = self._get_json_ld_data()
        if json_ld:
            if 'recipeCategory' in json_ld:
                cat = json_ld['recipeCategory']
                return ', '.join(cat) if isinstance(cat, list) else str(cat)
            if 'recipeCuisine' in json_ld:
                cuisine = json_ld['recipeCuisine']
                return ', '.join(cuisine) if isinstance(cuisine, list) else str(cuisine)

        # Резервный вариант: из хлебных крошек
        breadcrumb = self.soup.find('ol', class_='breadcrumb')
        if breadcrumb:
            links = breadcrumb.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки."""
        json_ld = self._get_json_ld_data()
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления."""
        json_ld = self._get_json_ld_data()
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени приготовления."""
        json_ld = self._get_json_ld_data()
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        return None

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок/советов к рецепту.

        Порядок приоритетов:
        1. <ol id="recipe-notes"> — структурированный список заметок
        2. <aside class="note"> с заголовком «Conseils de pro» / «Conseils»
        """
        # 1. Структурированный список заметок
        notes_ol = self.soup.find('ol', id='recipe-notes')
        if not notes_ol:
            notes_ol = self.soup.find('ol', class_='recipe__static-list')
        if notes_ol:
            items = [self.clean_text(li.get_text()) for li in notes_ol.find_all('li')]
            items = [i for i in items if i]
            if items:
                return ' '.join(items)

        # 2. Секция «Conseils de pro» / «Conseils» в aside.note
        for aside in self.soup.find_all('aside', class_='note'):
            h2 = aside.find('h2')
            if not h2:
                continue
            title = h2.get_text(strip=True).lower()
            if any(kw in title for kw in ('conseils', 'astuce', 'tips', 'pro')):
                items = [self.clean_text(li.get_text()) for li in aside.find_all('li')]
                items = [i for i in items if i]
                if items:
                    # Добавляем точку в конце предложений, если её нет
                    sentences = []
                    for item in items:
                        sentences.append(item if item.endswith('.') else item + '.')
                    return ' '.join(sentences)

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords."""
        json_ld = self._get_json_ld_data()
        if json_ld and 'keywords' in json_ld:
            kw = json_ld['keywords']
            if isinstance(kw, list):
                tags = [self.clean_text(k) for k in kw if k]
            else:
                tags = [t.strip() for t in str(kw).split(',') if t.strip()]
            tags = [t for t in tags if t]
            return ', '.join(tags) if tags else None

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта."""
        urls: list[str] = []

        json_ld = self._get_json_ld_data()
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        url = item.get('url') or item.get('contentUrl')
                        if url:
                            urls.append(url)
            elif isinstance(img, dict):
                url = img.get('url') or img.get('contentUrl')
                if url:
                    urls.append(url)

        # Дополнительно из og:image (если ещё не добавлено)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # Убираем дубликаты, сохраняя порядок
        seen: set[str] = set()
        unique_urls: list[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ','.join(unique_urls) if unique_urls else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта в едином формате проекта.
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
            'tags': self.extract_tags(),
            'image_urls': self.extract_image_urls(),
        }


def main() -> None:
    """Точка входа: обрабатывает директорию с HTML-страницами рецептов."""
    import os

    preprocessed_dir = os.path.join('preprocessed', 'delicesdujour_com')
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(DelicesDuJourExtractor, preprocessed_dir)
        return

    print(f'Директория не найдена: {preprocessed_dir}')
    print('Использование: python delicesdujour_com.py')


if __name__ == '__main__':
    main()
