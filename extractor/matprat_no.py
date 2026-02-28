"""
Экстрактор данных рецептов для сайта matprat.no
"""

import sys
from pathlib import Path
import json
import logging
import re
from typing import Optional

from bs4 import NavigableString

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class MatpratNoExtractor(BaseRecipeExtractor):
    """Экстрактор для matprat.no"""

    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение данных JSON-LD рецепта из страницы"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, KeyError, TypeError):
                logger.warning('Ошибка при разборе JSON-LD', exc_info=True)
                continue
        return None

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('name'):
            return self.clean_text(recipe['name'])

        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('description'):
            desc = self.clean_text(recipe['description'])
            return desc if desc else None

        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из структурированного HTML-списка.
        Элементы списка содержат отдельные span'ы для amount, unit и name.
        Рецепт может содержать несколько секций ингредиентов (ul.ingredientsList).
        """
        ingredients = []

        # Берём первый контейнер ingredients-list, чтобы избежать дублирования
        # (на странице есть десктопная и мобильная копии)
        ing_container = self.soup.find('div', class_='ingredients-list')
        ing_lists = ing_container.find_all('ul', class_='ingredientsList') if ing_container else []
        if not ing_lists:
            # Fallback: первый ul.ingredientsList без контейнера
            first = self.soup.find('ul', class_='ingredientsList')
            ing_lists = [first] if first else []

        for ing_list in ing_lists:
            for item in ing_list.find_all('li', itemprop='ingredients'):
                try:
                    amount_span = item.find('span', class_='amount')
                    unit_span = item.find('span', class_='unit')

                    # Все span'ы без класса — кандидаты на название
                    all_spans = item.find_all('span')
                    name_spans = [
                        s for s in all_spans
                        if not s.get('class') and s.get_text(strip=True)
                    ]

                    amount_raw = amount_span.get('data-amount') if amount_span else None
                    unit_raw = unit_span.get('data-unit') if unit_span else None

                    # Нормализуем количество: "2,5" -> "2.5"
                    amount = None
                    if amount_raw:
                        amount_str = amount_raw.replace(',', '.')
                        try:
                            amount = float(amount_str)
                            amount = int(amount) if amount == int(amount) else amount
                        except ValueError:
                            amount = amount_str

                    unit = self.clean_text(unit_raw) if unit_raw else None

                    # Название — первый span без класса (основное название ингредиента)
                    name = self.clean_text(name_spans[0].get_text()) if name_spans else None

                    # Проверяем, есть ли текстовый префикс перед span.amount
                    # (например, «saft av» в «saft av 1 stk. sitron»)
                    if amount_span:
                        prefix_parts = []
                        for node in item.children:
                            if node == amount_span:
                                break
                            if isinstance(node, NavigableString):
                                part = node.strip()
                                if part:
                                    prefix_parts.append(part)
                        if prefix_parts and name:
                            name = ' '.join(prefix_parts) + ' ' + name

                    if name:
                        ingredients.append({
                            'name': name,
                            'amount': amount,
                            'unit': unit,
                        })
                except Exception:
                    logger.warning('Ошибка при разборе ингредиента', exc_info=True)
                    continue

        # Если структурированный список не нашли, пробуем JSON-LD recipeIngredient
        if not ingredients:
            recipe = self._get_json_ld_recipe()
            if recipe and recipe.get('recipeIngredient'):
                for ing_str in recipe['recipeIngredient']:
                    ing_str = self.clean_text(ing_str)
                    if ing_str:
                        parsed = self._parse_ingredient_string(ing_str)
                        if parsed:
                            ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def _parse_ingredient_string(self, text: str) -> Optional[dict]:
        """Разбор строки ингредиента на name/amount/unit"""
        if not text:
            return None

        # Паттерн: «0,5 stk. frossen banan» или «200 g frosne mangobiter»
        pattern = (
            r'^([\d,./\s]+)?\s*'
            r'(stk\.|dl|g|kg|l|ml|ts|ss|pk|klype|bunt|neve|skive|fedd|'
            r'cups?|tbsp?|tsp?|oz|lb)'
            r'\.?\s+(.+)'
        )
        m = re.match(pattern, text.strip(), re.IGNORECASE)
        if m:
            amount_raw, unit, name = m.groups()
            amount = None
            if amount_raw:
                amount_str = amount_raw.strip().replace(',', '.')
                try:
                    amount = float(amount_str)
                    amount = int(amount) if amount == int(amount) else amount
                except ValueError:
                    amount = amount_str
            return {
                'name': self.clean_text(name),
                'amount': amount,
                'unit': unit.rstrip('.').strip() if unit else None,
            }

        return {'name': text, 'amount': None, 'unit': None}

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления из JSON-LD или HTML"""
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('recipeInstructions'):
            steps = []
            for idx, step in enumerate(recipe['recipeInstructions'], 1):
                if isinstance(step, dict):
                    text = self.clean_text(step.get('text', ''))
                elif isinstance(step, str):
                    text = self.clean_text(step)
                else:
                    continue
                if text:
                    steps.append(f'{idx}. {text}')
            if steps:
                return '\n'.join(steps)

        # Fallback: ищем шаги в HTML
        steps = []
        process_section = self.soup.find(
            'div', class_=re.compile(r'recipe.*process|new-recipe-details__process', re.I)
        )
        if process_section:
            step_items = process_section.find_all('li')
            if not step_items:
                step_items = process_section.find_all('p')
            for item in step_items:
                text = self.clean_text(item.get_text(separator=' ', strip=True))
                if text:
                    steps.append(text)
            if steps and not re.match(r'^\d+\.', steps[0]):
                steps = [f'{idx}. {step}' for idx, step in enumerate(steps, 1)]

        return '\n'.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из JSON-LD или тегов поиска"""
        recipe = self._get_json_ld_recipe()
        if recipe:
            category = recipe.get('recipeCategory')
            if category:
                if isinstance(category, list):
                    cats = [self.clean_text(c) for c in category if c]
                    if cats:
                        return ', '.join(cats)
                elif isinstance(category, str):
                    return self.clean_text(category) or None

        # Fallback: recipe-search-tags HTML элементы
        tags_list = self.soup.find('ul', class_='recipe-search-tags')
        if tags_list:
            tags = [
                self.clean_text(a.get_text())
                for a in tags_list.find_all('a', class_='recipe-search-tags__item-link')
                if a.get_text(strip=True)
            ]
            if tags:
                return ', '.join(tags)

        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления из HTML (отображаемое значение)"""
        # Ищем в new-recipe-description DL элемент с временем
        for dl in self.soup.find_all('dl', class_=re.compile(r'new-recipe-description', re.I)):
            time_dd = dl.find('dd', class_=re.compile(r'icon-time|extra-text', re.I))
            if time_dd:
                # Берём текст из span'ов или напрямую
                spans = time_dd.find_all('span', class_=re.compile(r'epi-editContainer', re.I))
                if spans:
                    text = self.clean_text(spans[-1].get_text())
                else:
                    text = self.clean_text(time_dd.get_text())
                if text:
                    return text

        # Fallback: любой dd с классом icon-time на странице
        dd_time = self.soup.find('dd', class_='icon-time')
        if dd_time:
            return self.clean_text(dd_time.get_text())

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки — не отображается отдельно на matprat.no"""
        return None

    def extract_total_time(self) -> Optional[str]:
        """Общее время — не отображается отдельно на matprat.no"""
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов из блока infobox"""
        infobox = self.soup.find('div', class_=re.compile(r'\binfobox\b', re.I))
        if infobox:
            rich = infobox.find('div', class_='rich-text')
            source = rich if rich else infobox
            text = self.clean_text(source.get_text(separator=' ', strip=True))
            # Убираем стандартный префикс «Kokketips: »
            text = re.sub(r'^Kokketips:\s*', '', text, flags=re.I)
            return text if text else None

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords или meta keywords"""
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('keywords'):
            kw = recipe['keywords']
            if isinstance(kw, str):
                tags = [t.strip() for t in kw.split(',') if t.strip()]
                if tags:
                    return ', '.join(tags)

        # Fallback: meta keywords
        meta_kw = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_kw and meta_kw.get('content'):
            tags = [t.strip() for t in meta_kw['content'].split(',') if t.strip()]
            if tags:
                return ', '.join(tags)

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из JSON-LD или og:image"""
        urls = []

        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('image'):
            img = recipe['image']
            if isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        url = item.get('url') or item.get('contentUrl')
                        if url:
                            urls.append(url)
            elif isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                url = img.get('url') or img.get('contentUrl')
                if url:
                    urls.append(url)

        # Дополняем из og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # Дедупликация
        seen = set()
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
            Словарь с данными рецепта (все поля присутствуют, None если не найдено)
        """
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


def main():
    import os
    recipes_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'preprocessed', 'matprat_no'
    )
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(MatpratNoExtractor, recipes_dir)
        return

    print(f'Директория не найдена: {recipes_dir}')
    print('Использование: python matprat_no.py')


if __name__ == '__main__':
    main()
