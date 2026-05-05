"""
Экстрактор данных рецептов для сайта laurasbakery.nl
Сайт построен на WordPress + WP Recipe Maker (WPRM).
Основные источники данных:
  - JSON-LD (@graph → Recipe) — описание, время, шаги, изображения
  - JSON-LD (@graph → Article) — теги, категории
  - WPRM-разметка (HTML-элементы с классами wprm-*) — ингредиенты, примечания, времена
"""

import logging
import sys
import json
import re
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class LaurasbakeryNlExtractor(BaseRecipeExtractor):
    """Экстрактор для laurasbakery.nl (WordPress + WP Recipe Maker)"""

    # ------------------------------------------------------------------ #
    # Вспомогательные методы                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_iso_duration(duration: Optional[str]) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в строку вида «X minutes» или «X hours Y minutes».

        Args:
            duration: строка вида «PT20M» или «PT1H30M» или «PT235M»

        Returns:
            Строка вида «10 minutes», «3 hours», «3 hours 55 minutes» или None
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

        # PT235M — нет часовой метки, считаем минуты
        total_minutes = hours * 60 + minutes

        if total_minutes <= 0:
            return None

        h = total_minutes // 60
        m = total_minutes % 60

        if h > 0 and m > 0:
            return f"{h} hour{'s' if h != 1 else ''} {m} minute{'s' if m != 1 else ''}"
        if h > 0:
            return f"{h} hour{'s' if h != 1 else ''}"
        return f"{m} minute{'s' if m != 1 else ''}"

    def _get_recipe_json_ld(self) -> Optional[dict]:
        """
        Возвращает узел типа Recipe из JSON-LD (@graph или прямой объект).
        """
        for script in self.soup.find_all('script', type='application/ld+json'):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
            except json.JSONDecodeError:
                continue

            if isinstance(data, dict) and '@graph' in data:
                for node in data['@graph']:
                    if isinstance(node, dict) and node.get('@type') == 'Recipe':
                        return node

            if isinstance(data, dict):
                t = data.get('@type', '')
                if t == 'Recipe' or (isinstance(t, list) and 'Recipe' in t):
                    return data

            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        t = item.get('@type', '')
                        if t == 'Recipe' or (isinstance(t, list) and 'Recipe' in t):
                            return item

        return None

    def _get_article_json_ld(self) -> Optional[dict]:
        """
        Возвращает узел типа Article из JSON-LD @graph.
        """
        for script in self.soup.find_all('script', type='application/ld+json'):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
            except json.JSONDecodeError:
                continue

            if isinstance(data, dict) and '@graph' in data:
                for node in data['@graph']:
                    if isinstance(node, dict) and node.get('@type') == 'Article':
                        return node

        return None

    # ------------------------------------------------------------------ #
    # Методы извлечения полей                                              #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Приоритет 1: WPRM HTML
        name_elem = self.soup.find(class_='wprm-recipe-name')
        if name_elem:
            name = self.clean_text(name_elem.get_text())
            if name:
                # Убираем слово " recept" / " recepten" в любом месте заголовка
                name = re.sub(r'\s+recept(?:en)?\b', ' ', name, flags=re.IGNORECASE).strip()
                name = re.sub(r'\s{2,}', ' ', name).strip()
                return name if name else None

        # Приоритет 2: JSON-LD Recipe.name
        recipe = self._get_recipe_json_ld()
        if recipe:
            name = self.clean_text(recipe.get('name', ''))
            if name:
                name = re.sub(r'\s+recept(?:en)?\b', ' ', name, flags=re.IGNORECASE).strip()
                name = re.sub(r'\s{2,}', ' ', name).strip()
                return name if name else None

        # Запасной вариант: og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = self.clean_text(og_title['content'])
            # Убираем суффикс сайта
            title = re.sub(r'\s*[-|].*Laura.*$', '', title, flags=re.IGNORECASE).strip()
            return title if title else None

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Приоритет 1: WPRM summary
        summary = self.soup.find(class_='wprm-recipe-summary')
        if summary:
            text = self.clean_text(summary.get_text())
            if text:
                return text

        # Приоритет 2: JSON-LD Recipe.description
        recipe = self._get_recipe_json_ld()
        if recipe:
            desc = recipe.get('description', '')
            if desc:
                return self.clean_text(desc)

        # Запасной вариант: og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из WPRM-разметки.
        Каждый ингредиент возвращается как {"name", "amount", "unit"}.
        Если WPRM не найден, парсим recipeIngredient из JSON-LD.
        """
        ingredients = []

        # Приоритет 1: WPRM <li class="wprm-recipe-ingredient">
        wprm_items = self.soup.find_all('li', class_='wprm-recipe-ingredient')
        if wprm_items:
            for item in wprm_items:
                amount_elem = item.find(class_='wprm-recipe-ingredient-amount')
                unit_elem = item.find(class_='wprm-recipe-ingredient-unit')
                name_elem = item.find(class_='wprm-recipe-ingredient-name')

                amount = self.clean_text(amount_elem.get_text()) if amount_elem else None
                unit = self.clean_text(unit_elem.get_text()) if unit_elem else None
                name = self.clean_text(name_elem.get_text()) if name_elem else None

                if not name:
                    continue

                ingredients.append({
                    'name': name,
                    'amount': amount if amount else None,
                    'unit': unit if unit else None,
                })

            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        # Приоритет 2: JSON-LD recipeIngredient (строки)
        recipe = self._get_recipe_json_ld()
        if recipe:
            raw_ings = recipe.get('recipeIngredient', [])
            for raw in raw_ings:
                if not isinstance(raw, str):
                    continue
                parsed = self._parse_ingredient_text(self.clean_text(raw))
                if parsed:
                    ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def _parse_ingredient_text(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента вида «80 gram fijne kristalsuiker» в структурированный формат.

        Args:
            text: строка ингредиента

        Returns:
            dict {"name", "amount", "unit"} или None
        """
        if not text:
            return None

        original = text
        text = text.strip()

        # Паттерн: [количество] [единица] название
        pattern = (
            r'^([\d\s/.,½¼¾⅓⅔⅛]+)?'                  # количество (необязательно)
            r'\s*'
            r'(gram|g\b|ml|liter|l\b|tl|el|blaadjes?|snuf(?:je)?|stuks?|zakje)?'  # единица (необязательно)
            r'\s*(.+)$'
        )

        m = re.match(pattern, text, re.IGNORECASE)
        if not m:
            return {'name': original, 'amount': None, 'unit': None}

        amount_str, unit, name = m.groups()
        amount = amount_str.strip() if amount_str and amount_str.strip() else None
        unit = unit.strip() if unit and unit.strip() else None
        name = name.strip() if name else original

        if not name:
            return None

        return {'name': name, 'amount': amount, 'unit': unit}

    def extract_steps(self) -> Optional[str]:
        """
        Извлечение шагов приготовления.
        Использует WPRM HTML, затем JSON-LD recipeInstructions.
        """
        steps = []

        # Приоритет 1: WPRM HTML
        wprm_steps = self.soup.find_all('li', class_='wprm-recipe-instruction')
        if wprm_steps:
            for step in wprm_steps:
                text_div = step.find(class_='wprm-recipe-instruction-text')
                text = self.clean_text((text_div or step).get_text(separator=' '))
                if text:
                    steps.append(text)
            if steps:
                return ' '.join(steps)

        # Приоритет 2: JSON-LD recipeInstructions
        recipe = self._get_recipe_json_ld()
        if recipe:
            instructions = recipe.get('recipeInstructions', [])
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict):
                        text = self.clean_text(step.get('text', ''))
                    elif isinstance(step, str):
                        text = self.clean_text(step)
                    else:
                        continue
                    if text:
                        steps.append(text)
            elif isinstance(instructions, str):
                text = self.clean_text(instructions)
                if text:
                    steps.append(text)

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """
        Извлечение категории блюда.
        Берём из Article.articleSection в JSON-LD или WPRM course.
        """
        # Приоритет 1: JSON-LD Recipe.recipeCategory
        recipe = self._get_recipe_json_ld()
        if recipe:
            cat = recipe.get('recipeCategory')
            if isinstance(cat, list) and cat:
                return ', '.join(c.strip() for c in cat if isinstance(c, str) and c.strip())
            if isinstance(cat, str) and cat.strip():
                return self.clean_text(cat)

        # Приоритет 2: Article.articleSection → ищем смысловую категорию (не технические теги)
        article = self._get_article_json_ld()
        if article:
            sections = article.get('articleSection', [])
            if isinstance(sections, list) and sections:
                # Ищем знакомые категории блюд (приоритет)
                food_sections = [s for s in sections if isinstance(s, str) and
                                 any(k in s.lower() for k in ['dessert', 'cake', 'bread', 'brood', 'koek',
                                                               'taart', 'pasta', 'salad', 'soep', 'snack',
                                                               'ontbijt', 'diner', 'lunch', 'brunch'])]
                if food_sections:
                    # Нормализуем известные голландские категории во множественном числе
                    _plural_map = {
                        'desserts': 'Dessert',
                        'taarten': 'Taart',
                        'koeken': 'Koek',
                        'cakes': 'Cake',
                        'broden': 'Brood',
                        'soepen': 'Soep',
                        'salades': 'Salade',
                    }
                    cat_lower = food_sections[0].lower()
                    cat_text = _plural_map.get(cat_lower, food_sections[0])
                    return self.clean_text(cat_text)
                # Иначе возвращаем первую непустую секцию
                for s in sections:
                    if isinstance(s, str) and s.strip():
                        return self.clean_text(s)

        # Приоритет 3: WPRM course block
        course = self.soup.find(class_='wprm-recipe-course-container')
        if course:
            text = re.sub(r'^Course[\s:,]*', '', course.get_text(strip=True), flags=re.I).strip()
            if text:
                return self.clean_text(text)

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe = self._get_recipe_json_ld()
        if recipe:
            return self._parse_iso_duration(recipe.get('prepTime'))
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe = self._get_recipe_json_ld()
        if recipe:
            return self._parse_iso_duration(recipe.get('cookTime'))
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe = self._get_recipe_json_ld()
        if recipe:
            return self._parse_iso_duration(recipe.get('totalTime'))
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов из WPRM-блока"""
        container = self.soup.find(class_='wprm-recipe-notes-container')
        if not container:
            return None

        text = container.get_text(separator='\n', strip=True)
        # Убираем заголовок «Notes» / «Notities» / «Tips»
        text = re.sub(r'^(Notes|Notities|Tips)[\s:\n]*', '', text, flags=re.I).strip()
        # Убираем шорткоды WPRM
        text = re.sub(r'\[/?wprm[^\]]*\]', '', text, flags=re.I).strip()
        # Нормализуем переносы строк
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = self.clean_text(text)
        return text if text else None

    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов из Article.keywords в JSON-LD.
        """
        # Приоритет 1: Article.keywords (Yoast SEO)
        article = self._get_article_json_ld()
        if article:
            keywords = article.get('keywords', [])
            if isinstance(keywords, list) and keywords:
                return ', '.join(k.strip().lower() for k in keywords if isinstance(k, str) and k.strip())
            if isinstance(keywords, str) and keywords.strip():
                return keywords.strip().lower()

        # Приоритет 2: Recipe.keywords
        recipe = self._get_recipe_json_ld()
        if recipe:
            keywords = recipe.get('keywords')
            if isinstance(keywords, str) and keywords.strip():
                return keywords.strip()
            if isinstance(keywords, list):
                return ', '.join(k.strip() for k in keywords if isinstance(k, str) and k.strip())

        # Запасной вариант: meta keywords
        meta_kw = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_kw and meta_kw.get('content'):
            return self.clean_text(meta_kw['content'])

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls: list = []

        # 1. JSON-LD Recipe.image
        recipe = self._get_recipe_json_ld()
        if recipe:
            img = recipe.get('image')
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                for i in img:
                    if isinstance(i, str):
                        urls.append(i)
                    elif isinstance(i, dict):
                        for key in ('url', 'contentUrl'):
                            if i.get(key):
                                urls.append(i[key])
                                break
            elif isinstance(img, dict):
                for key in ('url', 'contentUrl'):
                    if img.get(key):
                        urls.append(img[key])
                        break

        # 2. og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # 3. twitter:image
        tw_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if tw_image and tw_image.get('content'):
            urls.append(tw_image['content'])

        # Дедупликация с сохранением порядка
        seen: set = set()
        unique: list = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    # ------------------------------------------------------------------ #
    # Главный метод                                                        #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта (все поля присутствуют, None если не найдено)
        """
        try:
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
                'tags': None,
                'image_urls': None,
            }


def main() -> None:
    """Точка входа: обрабатывает директорию preprocessed/laurasbakery_nl."""
    base_dir = Path(__file__).parent.parent
    recipes_dir = base_dir / 'preprocessed' / 'laurasbakery_nl'

    if recipes_dir.exists() and recipes_dir.is_dir():
        process_directory(LaurasbakeryNlExtractor, str(recipes_dir))
    else:
        print(f'Директория не найдена: {recipes_dir}')
        print('Использование: python laurasbakery_nl.py')


if __name__ == '__main__':
    main()
