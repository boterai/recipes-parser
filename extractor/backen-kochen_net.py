"""
Экстрактор данных рецептов для сайта backen-kochen.net
Сайт использует плагин Tasty Recipes для WordPress.
"""

import sys
import json
import re
import logging
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class BackenKochenNetExtractor(BaseRecipeExtractor):
    """Экстрактор для backen-kochen.net (плагин Tasty Recipes)"""

    # Common German/English units for ingredient parsing
    _KNOWN_UNITS = {
        'g', 'kg', 'ml', 'l', 'cl', 'dl',
        'tsp', 'tbsp', 'cup', 'cups', 'oz', 'lb', 'lbs',
        'el', 'tl',  # German: Esslöffel, Teelöffel
        'pkg', 'pkt',
    }

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def _get_tasty_recipes_div(self):
        """Возвращает div.tasty-recipes или None"""
        return self.soup.find('div', class_='tasty-recipes')

    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение объекта Recipe из JSON-LD"""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    @staticmethod
    def _normalize_time_text(time_text: str) -> Optional[str]:
        """
        Нормализует отображаемое время из немецких форматов в английские.

        Примеры:
            "15 Minuten" -> "15 minutes"
            "1 Stunde" -> "1 hour"
        """
        if not time_text:
            return None
        text = time_text.strip()
        text = re.sub(r'\bMinuten\b', 'minutes', text)
        text = re.sub(r'\bMinute\b', 'minute', text)
        text = re.sub(r'\bStunden\b', 'hours', text)
        text = re.sub(r'\bStunde\b', 'hour', text)
        return text if text else None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration (PT15M, PT1H30M) в читаемый формат.

        Возвращает строку вида "15 minutes" или "1 hour 30 minutes".
        """
        if not duration or not duration.startswith('PT'):
            return None
        body = duration[2:]
        hours = 0
        minutes = 0
        h_match = re.search(r'(\d+)H', body)
        m_match = re.search(r'(\d+)M', body)
        if h_match:
            hours = int(h_match.group(1))
        if m_match:
            minutes = int(m_match.group(1))
        total_minutes = hours * 60 + minutes
        if total_minutes <= 0:
            return None
        if hours and minutes:
            return f"{hours} hour{'s' if hours > 1 else ''} {minutes} minute{'s' if minutes > 1 else ''}"
        if hours:
            return f"{hours} hour{'s' if hours > 1 else ''}"
        return f"{minutes} minute{'s' if minutes > 1 else ''}"

    def _parse_tasty_ingredient(self, li_elem) -> Optional[dict]:
        """
        Парсит элемент <li> из блока ингредиентов Tasty Recipes.

        Поддерживает:
          - <li><span data-amount="115" data-unit="g">115g</span> Butter</li>
          - <li><span data-amount="1">1</span> kg Kirschen</li>
          - <li><span data-amount="200">200</span>–<span data-amount="400">400</span> g Zucker</li>
          - <li>Essigwasser zur Sterilisation der Gläser</li>
        """
        spans = li_elem.find_all('span', attrs={'data-amount': True})

        if not spans:
            # Нет структурированных данных — только текст
            name = self.clean_text(li_elem.get_text())
            if not name:
                return None
            return {'name': name, 'amount': None, 'unit': None}

        # Количество: одно значение или диапазон (200–400)
        raw_amounts = [s.get('data-amount', '').strip() for s in spans]
        if len(raw_amounts) == 1:
            amount_str = raw_amounts[0]
        else:
            amount_str = '\u2013'.join(raw_amounts)  # em dash

        # Единица из атрибута первого span (если есть)
        unit = spans[0].get('data-unit', '').strip() or None

        # Текст, оставшийся после всех span-ов
        # Клонируем элемент и удаляем span-ы, чтобы получить "хвост"
        li_clone = BeautifulSoup(str(li_elem), 'lxml').find('li')
        for s in li_clone.find_all('span', attrs={'data-amount': True}):
            s.decompose()
        remaining = li_clone.get_text().strip().strip('\u2013').strip()

        if not unit and remaining:
            # Проверяем, не является ли первое слово единицей измерения
            words = remaining.split()
            if words and words[0].lower() in self._KNOWN_UNITS:
                unit = words[0]
                remaining = ' '.join(words[1:]).strip()

        # Очищаем название: убираем скобки и лишние пробелы
        name = re.sub(r'\([^)]*\)', '', remaining).strip()
        name = self.clean_text(name)

        if not name:
            name = self.clean_text(remaining)

        if not name:
            return None

        return {'name': name, 'amount': amount_str or None, 'unit': unit}

    # ------------------------------------------------------------------ #
    #  Extraction methods
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        tr = self._get_tasty_recipes_div()
        if tr:
            title = tr.find('h2', class_='tasty-recipes-title')
            if title:
                return self.clean_text(title.get_text())

        # Fallback: h1 на странице
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        # Fallback: JSON-LD
        jld = self._get_recipe_json_ld()
        if jld and jld.get('name'):
            return self.clean_text(jld['name'])

        # Fallback: og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        tr = self._get_tasty_recipes_div()
        if tr:
            desc = tr.find('div', class_='tasty-recipes-description-body')
            if not desc:
                desc = tr.find('div', class_='tasty-recipes-description')
            if desc:
                text = self.clean_text(desc.get_text())
                if text:
                    return text

        # Fallback: JSON-LD description
        jld = self._get_recipe_json_ld()
        if jld and jld.get('description'):
            return self.clean_text(jld['description'])

        # Fallback: meta description
        meta = self.soup.find('meta', attrs={'name': 'description'})
        if meta and meta.get('content'):
            return self.clean_text(meta['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в виде JSON-строки"""
        ingredients = []
        tr = self._get_tasty_recipes_div()
        if tr:
            ing_div = tr.find('div', class_='tasty-recipes-ingredients')
            if ing_div:
                for li in ing_div.find_all('li'):
                    parsed = self._parse_tasty_ingredient(li)
                    if parsed:
                        ingredients.append(parsed)

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        # Fallback: JSON-LD recipeIngredient
        jld = self._get_recipe_json_ld()
        if jld and jld.get('recipeIngredient'):
            for raw in jld['recipeIngredient']:
                text = self.clean_text(str(raw))
                if text:
                    ingredients.append({'name': text, 'amount': None, 'unit': None})
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        return None

    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        steps = []
        tr = self._get_tasty_recipes_div()
        if tr:
            inst_div = tr.find('div', class_='tasty-recipes-instructions')
            if inst_div:
                for li in inst_div.find_all('li'):
                    text = self.clean_text(li.get_text())
                    if text:
                        steps.append(text)

        if steps:
            return ' '.join(steps)

        # Fallback: JSON-LD recipeInstructions
        jld = self._get_recipe_json_ld()
        if jld and jld.get('recipeInstructions'):
            for step in jld['recipeInstructions']:
                if isinstance(step, dict) and step.get('text'):
                    steps.append(self.clean_text(step['text']))
                elif isinstance(step, str):
                    steps.append(self.clean_text(step))
            if steps:
                return ' '.join(steps)

        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        tr = self._get_tasty_recipes_div()
        if tr:
            cat = tr.find(class_='tasty-recipes-category')
            if cat:
                return self.clean_text(cat.get_text())

        # Fallback: JSON-LD recipeCategory
        jld = self._get_recipe_json_ld()
        if jld:
            cat = jld.get('recipeCategory')
            if cat:
                if isinstance(cat, list):
                    return self.clean_text(', '.join(cat))
                return self.clean_text(str(cat))

        return None

    def _extract_time_from_card(self, css_class: str) -> Optional[str]:
        """Извлечение отображаемого времени из карточки Tasty Recipes"""
        span = self.soup.find(class_=css_class)
        if span:
            text = self.clean_text(span.get_text())
            if text:
                return self._normalize_time_text(text)
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        result = self._extract_time_from_card('tasty-recipes-prep-time')
        if result:
            return result
        # Fallback: JSON-LD
        jld = self._get_recipe_json_ld()
        if jld and jld.get('prepTime'):
            return self._parse_iso_duration(jld['prepTime'])
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        result = self._extract_time_from_card('tasty-recipes-cook-time')
        if result:
            return result
        jld = self._get_recipe_json_ld()
        if jld and jld.get('cookTime'):
            return self._parse_iso_duration(jld['cookTime'])
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        result = self._extract_time_from_card('tasty-recipes-total-time')
        if result:
            return result
        jld = self._get_recipe_json_ld()
        if jld and jld.get('totalTime'):
            return self._parse_iso_duration(jld['totalTime'])
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок к рецепту"""
        tr = self._get_tasty_recipes_div()
        if tr:
            notes_body = tr.find('div', class_='tasty-recipes-notes-body')
            if not notes_body:
                notes_body = tr.find('div', class_='tasty-recipes-notes')
            if notes_body:
                items = notes_body.find_all('li')
                if items:
                    texts = [self.clean_text(li.get_text()) for li in items]
                    texts = [t for t in texts if t]
                    if texts:
                        return ' '.join(texts)
                # No li items — just raw text
                text = self.clean_text(notes_body.get_text())
                if text:
                    return text

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords"""
        jld = self._get_recipe_json_ld()
        if jld and jld.get('keywords'):
            kw = jld['keywords']
            if isinstance(kw, list):
                tags = [self.clean_text(k) for k in kw if k]
            else:
                tags = [t.strip() for t in str(kw).split(',') if t.strip()]
            tags = [t for t in tags if t]
            if tags:
                return ', '.join(tags)

        # Fallback: meta keywords
        meta_kw = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_kw and meta_kw.get('content'):
            kw = meta_kw['content']
            tags = [t.strip() for t in kw.split(',') if t.strip()]
            if tags:
                return ', '.join(tags)

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []

        # 1. JSON-LD image field (самый надёжный источник)
        jld = self._get_recipe_json_ld()
        if jld and jld.get('image'):
            img = jld['image']
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

        # 2. og:image как резервный вариант
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])

        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ','.join(unique_urls) if unique_urls else None

    # ------------------------------------------------------------------ #
    #  Main extraction method
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с полями: dish_name, description, ingredients, instructions,
            category, prep_time, cook_time, total_time, notes, image_urls, tags.
            Отсутствующие значения заполняются None.
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception as e:
            logger.warning('Failed to extract dish_name: %s', e)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as e:
            logger.warning('Failed to extract description: %s', e)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as e:
            logger.warning('Failed to extract ingredients: %s', e)
            ingredients = None

        try:
            instructions = self.extract_instructions()
        except Exception as e:
            logger.warning('Failed to extract instructions: %s', e)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as e:
            logger.warning('Failed to extract category: %s', e)
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception as e:
            logger.warning('Failed to extract prep_time: %s', e)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception as e:
            logger.warning('Failed to extract cook_time: %s', e)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception as e:
            logger.warning('Failed to extract total_time: %s', e)
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception as e:
            logger.warning('Failed to extract notes: %s', e)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as e:
            logger.warning('Failed to extract tags: %s', e)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as e:
            logger.warning('Failed to extract image_urls: %s', e)
            image_urls = None

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


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os

    preprocessed_dir = os.path.join('preprocessed', 'backen-kochen_net')

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(BackenKochenNetExtractor, preprocessed_dir)
        return

    print(f'Директория не найдена: {preprocessed_dir}')
    print('Использование: python backen-kochen_net.py')


if __name__ == '__main__':
    main()
