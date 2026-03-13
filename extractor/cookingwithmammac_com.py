"""
Экстрактор данных рецептов для сайта cookingwithmammac.com

Сайт использует плагин WP Recipe Maker (WPRM) для WordPress.
Данные рецепта находятся в div.wprm-recipe-container с классами вида wprm-recipe-*.
"""

import logging
import sys
from pathlib import Path
import json
import re
from bs4 import BeautifulSoup, NavigableString, Tag
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class CookingWithMammacComExtractor(BaseRecipeExtractor):
    """Экстрактор для cookingwithmammac.com (WP Recipe Maker)"""

    def _get_recipe_card(self) -> Optional[Tag]:
        """Возвращает корневой элемент карточки рецепта WPRM"""
        card = self.soup.find('div', class_='wprm-recipe-container')
        if not card:
            logger.warning('WPRM recipe container not found')
        return card

    def _get_article_json_ld(self) -> Optional[dict]:
        """Возвращает Article-объект из JSON-LD (@graph)"""
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _wprm_span_text(span: Tag) -> str:
        """
        Возвращает текстовое значение WPRM-span, исключая скрытые screen-reader элементы.
        """
        value = ''
        for child in span.children:
            if isinstance(child, NavigableString):
                value += str(child)
            elif isinstance(child, Tag):
                child_classes = ' '.join(child.get('class', []))
                if 'sr-only' not in child_classes and 'screen-reader' not in child_classes:
                    value += child.get_text()
        return value.strip()

    def _extract_wprm_time(self, recipe_card: Tag, time_type: str) -> Optional[str]:
        """
        Извлекает время (prep_time / cook_time / total_time) из WPRM-карточки.

        WPRM хранит часы и минуты в отдельных span-ах:
          wprm-recipe-details wprm-recipe-details-hours  wprm-recipe-<time_type>
          wprm-recipe-details wprm-recipe-details-minutes wprm-recipe-<time_type>
        """
        hours: Optional[int] = None
        minutes: Optional[int] = None

        pattern = re.compile(r'wprm-recipe-details\b')
        for span in recipe_card.find_all('span', class_=pattern):
            classes = ' '.join(span.get('class', []))
            if f'wprm-recipe-{time_type}' not in classes:
                continue
            if 'wprm-recipe-details-unit' in classes:
                continue

            raw = self._wprm_span_text(span)
            # Remove trailing unit word that may be embedded (e.g. "15minutes" → "15")
            num_match = re.match(r'^(\d+)', raw)
            if not num_match:
                continue
            val = int(num_match.group(1))

            if 'wprm-recipe-details-hours' in classes:
                hours = val
            elif 'wprm-recipe-details-minutes' in classes:
                minutes = val

        if hours is None and minutes is None:
            return None

        parts = []
        if hours:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        return ' '.join(parts)

    # ------------------------------------------------------------------
    # Public extraction methods
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        card = self._get_recipe_card()
        if card:
            name_tag = card.find('h2', class_='wprm-recipe-name')
            if name_tag:
                return self.clean_text(name_tag.get_text())

        # Fallback: og:title без суффикса сайта
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*[-|]\s*Cooking with Mamma C.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title) or None

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Предпочитаем WPRM-summary как описание, специфичное для рецепта
        card = self._get_recipe_card()
        if card:
            summary = card.find('div', class_='wprm-recipe-summary')
            if summary:
                text = self.clean_text(summary.get_text(separator=' '))
                if text:
                    return text

        # Fallback: meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из WPRM.

        WPRM хранит каждый ингредиент в <li class="wprm-recipe-ingredient"> со спанами:
          wprm-recipe-ingredient-amount  — количество
          wprm-recipe-ingredient-unit    — единица измерения
          wprm-recipe-ingredient-name    — название
        """
        card = self._get_recipe_card()
        if not card:
            return None

        ingredients = []
        for li in card.find_all('li', class_='wprm-recipe-ingredient'):
            amount_tag = li.find('span', class_='wprm-recipe-ingredient-amount')
            unit_tag = li.find('span', class_='wprm-recipe-ingredient-unit')
            name_tag = li.find('span', class_='wprm-recipe-ingredient-name')

            if not name_tag:
                continue

            amount = self.clean_text(amount_tag.get_text()) if amount_tag else None
            unit = self.clean_text(unit_tag.get_text()) if unit_tag else None
            name = self.clean_text(name_tag.get_text())

            if not name:
                continue

            # Normalize Unicode fractions in amount
            if amount:
                fraction_map = {
                    '½': '1/2', '¼': '1/4', '¾': '3/4',
                    '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
                }
                for frac, repl in fraction_map.items():
                    amount = amount.replace(frac, repl)

            ingredients.append({
                'name': name,
                'amount': amount or None,
                'unit': unit or None,
            })

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления из WPRM"""
        card = self._get_recipe_card()
        if not card:
            return None

        steps = []
        for li in card.find_all('li', class_='wprm-recipe-instruction'):
            text = self.clean_text(li.get_text(separator=' '))
            if text:
                steps.append(text)

        if steps:
            # Добавляем нумерацию если её нет
            if not re.match(r'^\d+[.)]\s', steps[0]):
                steps = [f"{i}. {s}" for i, s in enumerate(steps, 1)]
            return ' '.join(steps)

        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда"""
        card = self._get_recipe_card()
        if card:
            course = card.find('span', class_='wprm-recipe-course')
            if course:
                return self.clean_text(course.get_text())

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        card = self._get_recipe_card()
        if not card:
            return None
        return self._extract_wprm_time(card, 'prep_time')

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        card = self._get_recipe_card()
        if not card:
            return None
        return self._extract_wprm_time(card, 'cook_time')

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        card = self._get_recipe_card()
        if not card:
            return None
        return self._extract_wprm_time(card, 'total_time')

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок к рецепту"""
        card = self._get_recipe_card()
        if not card:
            return None

        notes_div = card.find('div', class_='wprm-recipe-notes')
        if notes_div:
            text = self.clean_text(notes_div.get_text(separator=' '))
            return text if text else None

        return None

    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов.

        Приоритет:
        1. JSON-LD Article.keywords
        2. JSON-LD Article.articleSection
        3. WPRM cuisine
        """
        tags: list[str] = []

        article = self._get_article_json_ld()
        if article:
            # keywords (могут быть list или str)
            kw = article.get('keywords')
            if isinstance(kw, list):
                tags.extend(kw)
            elif isinstance(kw, str) and kw:
                tags.extend([k.strip() for k in kw.split(',')])

            # articleSection
            sections = article.get('articleSection')
            if isinstance(sections, list):
                tags.extend(sections)
            elif isinstance(sections, str) and sections:
                tags.append(sections)

        # Добавляем cuisine из WPRM если ещё нет
        card = self._get_recipe_card()
        if card:
            cuisine_tag = card.find('span', class_='wprm-recipe-cuisine')
            if cuisine_tag:
                cuisine = self.clean_text(cuisine_tag.get_text())
                if cuisine:
                    tags.append(cuisine)

        if not tags:
            return None

        # Очищаем и дедуплицируем теги
        seen: set[str] = set()
        result: list[str] = []
        for tag in tags:
            cleaned = self.clean_text(str(tag))
            lower = cleaned.lower()
            if cleaned and lower not in seen:
                seen.add(lower)
                result.append(cleaned)

        return ', '.join(result) if result else None

    def extract_image_urls(self) -> Optional[str]:
        """
        Извлечение URL изображений рецепта.

        Источники (в порядке приоритета):
        1. ImageObject в JSON-LD @graph
        2. og:image meta
        3. WPRM-карточка img (data-lazy-src / srcset / src)
        """
        urls: list[str] = []

        # 1. JSON-LD @graph ImageObject
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if not isinstance(item, dict):
                            continue
                        if item.get('@type') == 'ImageObject':
                            url = item.get('url') or item.get('contentUrl')
                            if url and url not in urls:
                                urls.append(url)
            except (json.JSONDecodeError, KeyError):
                continue

        # 2. og:image
        og_img = self.soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            url = og_img['content']
            if url not in urls:
                urls.append(url)

        # 3. WPRM recipe card images
        card = self._get_recipe_card()
        if card:
            for img in card.find_all('img'):
                # Prefer real URLs over base64 / placeholder SVGs
                for attr in ('data-lazy-src', 'src'):
                    url = img.get(attr, '')
                    if url and not url.startswith('data:') and url not in urls:
                        urls.append(url)
                        break

        if not urls:
            return None

        # Дедупликация и ограничение до 3 изображений
        seen: set[str] = set()
        unique: list[str] = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique.append(url)
            if len(unique) >= 3:
                break

        return ','.join(unique) if unique else None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта
        """
        try:
            dish_name = self.extract_dish_name()
            description = self.extract_description()
            ingredients = self.extract_ingredients()
            instructions = self.extract_steps()
            category = self.extract_category()
            notes = self.extract_notes()
            tags = self.extract_tags()
        except Exception as exc:
            logger.error('Unexpected error during extraction: %s', exc, exc_info=True)
            dish_name = description = ingredients = instructions = None
            category = notes = tags = None

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


def main() -> None:
    recipes_dir = Path(__file__).parent.parent / 'preprocessed' / 'cookingwithmammac_com'
    if recipes_dir.exists() and recipes_dir.is_dir():
        process_directory(CookingWithMammacComExtractor, str(recipes_dir))
        return

    print(f'Директория не найдена: {recipes_dir}')
    print('Использование: python cookingwithmammac_com.py')


if __name__ == '__main__':
    main()
