"""
Экстрактор данных рецептов для сайта laruedessaveurs.fr
"""

import logging
import sys
from pathlib import Path
import json
import re
from typing import Optional, List

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class LaruedessaveursExtractor(BaseRecipeExtractor):
    """Экстрактор для laruedessaveurs.fr"""

    # French units regex for ingredient parsing
    _FRENCH_UNITS = (
        r'cuillères? à soupe'
        r'|cuillères? à café'
        r'|cuillère à soupe'
        r'|cuillère à café'
        r'|tasses?'
        r'|litres?'
        r'|kilogrammes?'
        r'|grammes?'
        r'|livres?'
        r'|pièces?'
        r'|branches?'
        r'|gousses?'
        r'|pointes?'
        r'|feuilles?'
        r'|tranches?'
        r'|oz'
        r'|lb'
        r'|kg'
        r'|ml'
        r'|cl'
        r'|dl'
        r'|g'
        r'|l'
    )

    def _get_yoast_article_data(self) -> Optional[dict]:
        """Извлечение Article-блока из Yoast JSON-LD"""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Article':
                            return item
            except (json.JSONDecodeError, KeyError):
                continue
        return None

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        title_tag = self.soup.find('title')
        if title_tag:
            title = self.clean_text(title_tag.get_text())
            # Strip site name suffix
            title = re.sub(r'\s*[-–|]\s*La Rue Des Saveurs.*$', '', title, flags=re.IGNORECASE)
            return title if title else None

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            text = self.clean_text(og_desc['content'])
            # Skip if it looks like an ingredient list dump
            if text and not text.lower().startswith('ingrédients'):
                return text

        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            text = self.clean_text(meta_desc['content'])
            if text and not text.lower().startswith('ingrédients'):
                return text

        return None

    def _parse_french_ingredient(self, text: str) -> Optional[dict]:
        """
        Парсит строку ингредиента на французском языке.

        Примеры входных строк:
          "300 g de riz arborio."
          "2 cuillères à soupe d'huile d'olive"
          "1/4 tasse d'huile d'olive"
          "1 oignon pelé et coupé en dés."

        Returns:
            dict с ключами name, amount, unit или None
        """
        if not text:
            return None

        text = self.clean_text(text).rstrip('.')

        # Заменяем Unicode дроби
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
        }
        for frac, rep in fraction_map.items():
            text = text.replace(frac, rep)

        # Нормализуем запятую в числах: "1,5" -> "1.5"
        text = re.sub(r'(\d),(\d)', r'\1.\2', text)

        # Паттерн: (число/дробь) (единица) (de/d'/d'/d )(название)
        pattern = re.compile(
            r'^([\d]+(?:[./][\d]+)?(?:\s+[\d]+/[\d]+)?)\s*'
            r'(' + self._FRENCH_UNITS + r')\s*'
            r"(?:de?\s+|d['\u2019]\s*)?"
            r'(.+)$',
            re.IGNORECASE
        )
        match = pattern.match(text)
        if match:
            amount_str, unit, name = match.groups()
            amount = self._parse_amount(amount_str)
            name = self.clean_text(name).rstrip('.')
            return {'name': name, 'amount': amount, 'unit': unit.strip()}

        # Паттерн без единицы: (число) (de/d'/d )(название)
        pattern_no_unit = re.compile(
            r'^([\d]+(?:[./][\d]+)?(?:\s+[\d]+/[\d]+)?)\s+'
            r"(?:de?\s+|d['\u2019]\s*)?"
            r'(.+)$',
            re.IGNORECASE
        )
        match = pattern_no_unit.match(text)
        if match:
            amount_str, name = match.groups()
            # Only treat as "no unit" if name doesn't start with a unit word
            unit_check = re.match(r'^(' + self._FRENCH_UNITS + r')\b', name, re.IGNORECASE)
            if not unit_check:
                amount = self._parse_amount(amount_str)
                name = self.clean_text(name).rstrip('.')
                return {'name': name, 'amount': amount, 'unit': None}

        # Нет числа — только название
        return {'name': self.clean_text(text), 'amount': None, 'unit': None}

    @staticmethod
    def _parse_amount(amount_str: str) -> Optional[str]:
        """Нормализует строку количества"""
        if not amount_str:
            return None
        amount_str = amount_str.strip()
        # Обработка дробей: "1/2" или "1 1/2"
        parts = amount_str.split()
        total = 0.0
        for part in parts:
            if '/' in part:
                try:
                    num, denom = part.split('/')
                    total += float(num) / float(denom)
                except (ValueError, ZeroDivisionError):
                    return amount_str
            else:
                try:
                    total += float(part)
                except ValueError:
                    return amount_str
        # Убираем лишние нули: 1.0 -> "1", 0.5 -> "0.5"
        if total == int(total):
            return str(int(total))
        return str(total)

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []

        # 1. Структурированный формат: div.ingredients-section > ul > li
        ingredients_section = self.soup.find('div', class_='ingredients-section')
        if ingredients_section:
            for li in ingredients_section.find_all('li'):
                text = self.clean_text(li.get_text(separator=' ', strip=True))
                if text:
                    parsed = self._parse_french_ingredient(text)
                    if parsed:
                        ingredients.append(parsed)

        # 2. Неструктурированный формат: block-callout с wp-block-list
        if not ingredients:
            for bc in self.soup.find_all('div', class_='block-callout'):
                ul = bc.find('ul', class_='wp-block-list')
                if ul:
                    items = ul.find_all('li')
                    # Проверяем, что список похож на ингредиенты (хотя бы часть элементов с числами)
                    num_with_digits = sum(1 for li in items if re.search(r'\d', li.get_text()))
                    if num_with_digits >= len(items) // 2:
                        for li in items:
                            # Берём только текст strong (название), остальное — описание
                            strong = li.find('strong')
                            if strong:
                                name_text = self.clean_text(strong.get_text())
                                ingredients.append({'name': name_text, 'amount': None, 'unit': None})
                            else:
                                text = self.clean_text(li.get_text(separator=' ', strip=True))
                                if text:
                                    parsed = self._parse_french_ingredient(text)
                                    if parsed:
                                        ingredients.append(parsed)
                        if ingredients:
                            break

        if not ingredients:
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        steps = []

        # 1. Структурированный формат: div.method-section > ol > li
        method_section = self.soup.find('div', class_='method-section')
        if method_section:
            ol = method_section.find('ol')
            if ol:
                for li in ol.find_all('li'):
                    text = self.clean_text(li.get_text(separator=' ', strip=True)).rstrip('.')
                    if text:
                        steps.append(text)
            if steps:
                return '. '.join(steps) + '.'

        # 2. Секция "Photos étape par étape" или аналогичная
        entry = self.soup.find('div', class_='entry-content')
        if entry:
            for h2 in entry.find_all('h2'):
                h2_text = h2.get_text().lower()
                if any(kw in h2_text for kw in ['étape', 'step', 'comment faire', 'comment préparer', 'préparation']):
                    sibling = h2.find_next_sibling()
                    while sibling:
                        if sibling.name in ['h2', 'h3'] and sibling != h2:
                            break
                        if sibling.name == 'p':
                            text = self.clean_text(sibling.get_text(separator=' ', strip=True))
                            if text and len(text) > 20:
                                steps.append(text)
                        sibling = sibling.find_next_sibling()
                    if steps:
                        return ' '.join(steps)

        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # 1. Из Yoast JSON-LD articleSection
        article_data = self._get_yoast_article_data()
        if article_data:
            section = article_data.get('articleSection')
            if section:
                if isinstance(section, list) and section:
                    return self.clean_text(section[0])
                if isinstance(section, str):
                    return self.clean_text(section)

        # 2. Из CSS-классов article (category-*)
        article = self.soup.find('article')
        if article:
            for cls in article.get('class', []):
                if cls.startswith('category-'):
                    return self.clean_text(cls.replace('category-', '').replace('-', ' '))

        return None

    def _extract_time_from_text(self, keywords: List[str]) -> Optional[str]:
        """Пытается найти время в тексте страницы по ключевым словам"""
        entry = self.soup.find('div', class_='entry-content')
        if not entry:
            return None
        text = entry.get_text(separator=' ')
        for kw in keywords:
            # Ищем паттерн "N heures" или "N minutes" рядом с ключевым словом
            pattern = re.compile(
                r'\b' + re.escape(kw) + r'\b.{0,60}'
                r'(\d+(?:[.,]\d+)?)\s*'
                r'(heures?|minutes?|mins?|hrs?)',
                re.IGNORECASE
            )
            m = pattern.search(text)
            if m:
                num = m.group(1).replace(',', '.')
                unit = m.group(2).lower()
                if unit.startswith('h'):
                    return f"{num} hour{'s' if float(num) != 1 else ''}"
                else:
                    return f"{num} minute{'s' if float(num) != 1 else ''}"
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self._extract_time_from_text(['préparation', 'préparer', 'prep'])

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Check method-section for time hints
        method_section = self.soup.find('div', class_='method-section')
        if method_section:
            text = method_section.get_text(separator=' ')
            m = re.search(
                r'(\d+(?:[.,]\d+)?)\s*(?:à|-)\s*(\d+(?:[.,]\d+)?)\s*(minutes?|mins?)',
                text, re.IGNORECASE
            )
            if m:
                return f"{m.group(1)}-{m.group(2)} {m.group(3).lower()}"
            m = re.search(
                r'(\d+(?:[.,]\d+)?)\s*(heures?|minutes?|mins?|hrs?)',
                text, re.IGNORECASE
            )
            if m:
                num = m.group(1)
                unit = m.group(2).lower()
                return f"{num} {'hour' if unit.startswith('h') else 'minute'}{'s' if float(num.replace(',', '.')) != 1 else ''}"

        return self._extract_time_from_text(['cuisson', 'cuire', 'cook'])

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self._extract_time_from_text(['total', 'au total', 'temps total'])

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # 1. Структурированный: div.method-section > ul (после ol)
        method_section = self.soup.find('div', class_='method-section')
        if method_section:
            # Find ULs that come after OL (tips)
            ol = method_section.find('ol')
            if ol:
                tips = []
                sibling = ol.find_next_sibling()
                while sibling:
                    if sibling.name == 'ul':
                        for li in sibling.find_all('li'):
                            text = self.clean_text(li.get_text(separator=' ', strip=True))
                            if text:
                                tips.append(text)
                    sibling = sibling.find_next_sibling()
                if tips:
                    return '. '.join(tip.rstrip('.') for tip in tips) + '.'

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # 1. Из Yoast JSON-LD keywords
        article_data = self._get_yoast_article_data()
        if article_data:
            keywords = article_data.get('keywords')
            if keywords:
                if isinstance(keywords, list):
                    tags = [self.clean_text(k).lower() for k in keywords if k]
                    return ', '.join(tags) if tags else None
                if isinstance(keywords, str):
                    return self.clean_text(keywords).lower()

        # 2. Из CSS-классов article (tag-*)
        article = self.soup.find('article')
        if article:
            tags = []
            for cls in article.get('class', []):
                if cls.startswith('tag-'):
                    tags.append(cls.replace('tag-', '').replace('-', ' '))
            if tags:
                return ', '.join(tags)

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []

        # 1. og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # 2. Изображения из контентной части статьи (entry-content)
        entry = self.soup.find('div', class_='entry-content')
        if entry:
            for img in entry.find_all('img'):
                src = img.get('src') or img.get('data-src') or img.get('data-pin-media', '')
                if src and src.startswith('http') and 'laruedessaveurs' in src:
                    if src not in urls:
                        urls.append(src)

        # Убираем дубликаты
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ','.join(unique_urls) if unique_urls else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта

        Returns:
            Словарь с данными рецепта
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception:
            logger.exception("Error extracting dish_name")
            dish_name = None

        try:
            description = self.extract_description()
        except Exception:
            logger.exception("Error extracting description")
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception:
            logger.exception("Error extracting ingredients")
            ingredients = None

        try:
            instructions = self.extract_instructions()
        except Exception:
            logger.exception("Error extracting instructions")
            instructions = None

        try:
            category = self.extract_category()
        except Exception:
            logger.exception("Error extracting category")
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception:
            logger.exception("Error extracting prep_time")
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception:
            logger.exception("Error extracting cook_time")
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception:
            logger.exception("Error extracting total_time")
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception:
            logger.exception("Error extracting notes")
            notes = None

        try:
            tags = self.extract_tags()
        except Exception:
            logger.exception("Error extracting tags")
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception:
            logger.exception("Error extracting image_urls")
            image_urls = None

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


def main():
    import os
    recipes_dir = os.path.join("preprocessed", "laruedessaveurs_fr")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(LaruedessaveursExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python laruedessaveurs_fr.py [путь_к_директории]")


if __name__ == "__main__":
    main()
