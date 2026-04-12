"""
Экстрактор данных рецептов для сайта deliciousmagazine.nl

Сайт использует WordPress с плагином WP Recipe Maker (WPRM).
Основной источник данных: JSON-LD (@graph → Recipe).
Ингредиенты извлекаются из WPRM HTML (отдельные поля amount/unit/name).
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class DeliciousMagazineNlExtractor(BaseRecipeExtractor):
    """Экстрактор для deliciousmagazine.nl (WPRM + JSON-LD)"""

    # ------------------------------------------------------------------ #
    # Вспомогательные методы                                              #
    # ------------------------------------------------------------------ #

    def _get_recipe_jsonld(self) -> Optional[dict]:
        """Возвращает объект Recipe из JSON-LD (@graph) или None."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
                if not isinstance(data, dict):
                    continue
                graph = data.get('@graph', [])
                for item in graph:
                    if isinstance(item, dict) and item.get('@type') == 'Recipe':
                        return item
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в человекочитаемую строку.

        Примеры:
            "PT20M"   → "20 minutes"
            "PT1H30M" → "1 hour 30 minutes"
            "PT200M"  → "3 hours 20 minutes"
        """
        if not duration or not duration.startswith('PT'):
            return None

        body = duration[2:]  # убираем "PT"

        hours = 0
        minutes = 0

        hour_match = re.search(r'(\d+)H', body)
        if hour_match:
            hours = int(hour_match.group(1))

        min_match = re.search(r'(\d+)M', body)
        if min_match:
            minutes = int(min_match.group(1))

        total_minutes = hours * 60 + minutes
        if total_minutes <= 0:
            return None

        h, m = divmod(total_minutes, 60)
        parts: List[str] = []
        if h:
            parts.append(f"{h} hour{'s' if h != 1 else ''}")
        if m:
            parts.append(f"{m} minute{'s' if m != 1 else ''}")
        return ' '.join(parts) if parts else None

    # ------------------------------------------------------------------ #
    # Поля рецепта                                                        #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Название блюда из JSON-LD или og:title."""
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('name'):
            return self.clean_text(recipe['name'])

        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*[\|·—–-]\s*delicious.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)

        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def extract_description(self) -> Optional[str]:
        """
        Краткое описание рецепта.

        Приоритет: og:description → meta[name=description] → WPRM summary.
        og:description / meta description содержат короткий анонс, пригодный для описания.
        WPRM summary нередко содержит советы/варианты (будет в notes).
        """
        for attr in ({'property': 'og:description'}, {'name': 'description'}):
            meta = self.soup.find('meta', attrs=attr)
            if meta and meta.get('content'):
                return self.clean_text(meta['content'])

        summary = self.soup.find(class_='wprm-recipe-summary')
        if summary:
            text = self.clean_text(summary.get_text(separator=' ', strip=True))
            if text:
                return text

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из WPRM HTML.

        Каждый элемент имеет вложенные spans:
          .wprm-recipe-ingredient-amount  — количество
          .wprm-recipe-ingredient-unit    — единица измерения
          .wprm-recipe-ingredient-name    — название
          .wprm-recipe-ingredient-notes   — примечание (необязательно)
        """
        ingredients: List[dict] = []

        items = self.soup.find_all(class_='wprm-recipe-ingredient')
        for item in items:
            amount_tag = item.find(class_='wprm-recipe-ingredient-amount')
            unit_tag = item.find(class_='wprm-recipe-ingredient-unit')
            name_tag = item.find(class_='wprm-recipe-ingredient-name')

            if not name_tag:
                continue

            name = self.clean_text(name_tag.get_text(separator=' ', strip=True))
            # Убираем завершающую запятую, которую WPRM иногда добавляет к name
            name = name.rstrip(',').strip()
            if not name:
                continue

            amount = self.clean_text(amount_tag.get_text(strip=True)) if amount_tag else None
            unit = self.clean_text(unit_tag.get_text(strip=True)) if unit_tag else None

            ingredients.append({
                "name": name,
                "unit": unit or None,
                "amount": amount or None,
            })

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        # Резервный вариант: recipeIngredient из JSON-LD (строки без структуры)
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('recipeIngredient'):
            for raw in recipe['recipeIngredient']:
                text = self.clean_text(raw)
                if text:
                    ingredients.append({"name": text, "unit": None, "amount": None})
            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

        return None

    def extract_instructions(self) -> Optional[str]:
        """Шаги из JSON-LD recipeInstructions или WPRM HTML."""
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('recipeInstructions'):
            steps: List[str] = []
            for idx, step in enumerate(recipe['recipeInstructions'], 1):
                if isinstance(step, dict):
                    text = self.clean_text(step.get('text') or step.get('name') or '')
                elif isinstance(step, str):
                    text = self.clean_text(step)
                else:
                    continue
                if text:
                    steps.append(f"{idx}. {text}")
            if steps:
                return ' '.join(steps)

        # Резервный вариант: WPRM HTML
        step_texts: List[str] = []
        for step in self.soup.find_all(class_='wprm-recipe-instruction-text'):
            text = self.clean_text(step.get_text(separator=' ', strip=True))
            if text:
                step_texts.append(text)
        if step_texts:
            return ' '.join(
                f"{i}. {t}" for i, t in enumerate(step_texts, 1)
            )

        return None

    def extract_category(self) -> Optional[str]:
        """Категория из JSON-LD recipeCategory или WPRM course."""
        recipe = self._get_recipe_jsonld()
        if recipe:
            categories = recipe.get('recipeCategory')
            if isinstance(categories, list) and categories:
                return self.clean_text(categories[0])
            if isinstance(categories, str) and categories:
                return self.clean_text(categories)

        course = self.soup.find(class_='wprm-recipe-course')
        if course:
            text = self.clean_text(course.get_text(strip=True))
            if text:
                return text

        return None

    def _extract_wprm_time(self, time_type: str) -> Optional[str]:
        """
        Извлекает время из WPRM HTML.

        time_type: 'prep', 'cook', или 'total'
        """
        hours_cls = f'wprm-recipe-{time_type}_time-hours'
        mins_cls = f'wprm-recipe-{time_type}_time-minutes'

        hours_el = self.soup.find(class_=hours_cls)
        mins_el = self.soup.find(class_=mins_cls)

        hours = int(hours_el.get_text(strip=True)) if hours_el and hours_el.get_text(strip=True).isdigit() else 0
        minutes = int(mins_el.get_text(strip=True)) if mins_el and mins_el.get_text(strip=True).isdigit() else 0

        total = hours * 60 + minutes
        if total <= 0:
            return None

        h, m = divmod(total, 60)
        parts: List[str] = []
        if h:
            parts.append(f"{h} hour{'s' if h != 1 else ''}")
        if m:
            parts.append(f"{m} minute{'s' if m != 1 else ''}")
        return ' '.join(parts) if parts else None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки из JSON-LD или WPRM HTML."""
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('prepTime'):
            result = self._parse_iso_duration(recipe['prepTime'])
            if result:
                return result
        return self._extract_wprm_time('prep')

    def extract_cook_time(self) -> Optional[str]:
        """Время готовки из JSON-LD или WPRM HTML."""
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('cookTime'):
            result = self._parse_iso_duration(recipe['cookTime'])
            if result:
                return result
        return self._extract_wprm_time('cook')

    def extract_total_time(self) -> Optional[str]:
        """Общее время из JSON-LD или WPRM HTML."""
        recipe = self._get_recipe_jsonld()
        if recipe and recipe.get('totalTime'):
            result = self._parse_iso_duration(recipe['totalTime'])
            if result:
                return result
        return self._extract_wprm_time('total')

    def extract_notes(self) -> Optional[str]:
        """
        Заметки из WPRM notes container.

        Если WPRM notes пусты, используем WPRM summary — на deliciousmagazine.nl
        summary нередко содержит советы/варианты приготовления, а не аннотацию.
        """
        notes_div = self.soup.find(class_='wprm-recipe-notes')
        if notes_div:
            text = self.clean_text(notes_div.get_text(separator=' ', strip=True))
            if text:
                return text

        summary = self.soup.find(class_='wprm-recipe-summary')
        if summary:
            text = self.clean_text(summary.get_text(separator=' ', strip=True))
            if text:
                return text

        return None

    def extract_tags(self) -> Optional[str]:
        """
        Теги из нескольких источников (в порядке приоритета):
          1. WPRM moment (.wprm-recipe-moment) — повод/случай
          2. WPRM cuisine (.wprm-recipe-cuisine) — кухня
          3. WPRM course (.wprm-recipe-course) — категория
          4. JSON-LD Recipe.keywords
          5. JSON-LD Recipe.recipeCuisine
          6. meta article:tag
        Дубликаты и пустые значения исключаются.
        """
        tags: List[str] = []

        # 1. WPRM moment (occasion tags: feestelijk, kerst, weekend, etc.)
        moment = self.soup.find(class_='wprm-recipe-moment')
        if moment:
            text = self.clean_text(moment.get_text(strip=True))
            for t in re.split(r'[,;]+', text):
                t = t.strip()
                if t:
                    tags.append(t)

        # 2. WPRM cuisine
        cuisine_el = self.soup.find(class_='wprm-recipe-cuisine')
        if cuisine_el:
            text = self.clean_text(cuisine_el.get_text(strip=True))
            for t in re.split(r'[,;]+', text):
                t = t.strip()
                if t:
                    tags.append(t)

        # 3. WPRM course
        course_el = self.soup.find(class_='wprm-recipe-course')
        if course_el:
            text = self.clean_text(course_el.get_text(strip=True))
            for t in re.split(r'[,;]+', text):
                t = t.strip()
                if t:
                    tags.append(t)

        # 4. JSON-LD Recipe.keywords
        recipe = self._get_recipe_jsonld()
        if recipe:
            keywords = recipe.get('keywords', '')
            if isinstance(keywords, list):
                tags.extend([k.strip() for k in keywords if k.strip()])
            elif isinstance(keywords, str):
                tags.extend([k.strip() for k in keywords.split(',') if k.strip()])

            # 5. JSON-LD Recipe.recipeCuisine
            json_cuisine = recipe.get('recipeCuisine', [])
            if isinstance(json_cuisine, list):
                tags.extend([c.strip() for c in json_cuisine if c.strip()])
            elif isinstance(json_cuisine, str) and json_cuisine.strip():
                tags.append(json_cuisine.strip())

        # 6. meta article:tag
        for meta in self.soup.find_all('meta', attrs={'name': 'article:tag'}):
            content = meta.get('content', '').strip()
            if content:
                tags.append(content)

        if not tags:
            return None

        # Дедупликация с сохранением порядка (без учёта регистра)
        seen: set = set()
        unique: List[str] = []
        for tag in tags:
            key = tag.lower()
            if key not in seen:
                seen.add(key)
                unique.append(tag)

        return ','.join(unique) if unique else None

    def extract_image_urls(self) -> Optional[str]:
        """URL изображений из JSON-LD или og:image."""
        urls: List[str] = []

        # 1. JSON-LD Recipe.image
        recipe = self._get_recipe_jsonld()
        if recipe:
            img = recipe.get('image')
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                for i in img:
                    if isinstance(i, str):
                        urls.append(i)
                    elif isinstance(i, dict):
                        url = i.get('url') or i.get('contentUrl')
                        if url:
                            urls.append(url)
            elif isinstance(img, dict):
                url = img.get('url') or img.get('contentUrl')
                if url:
                    urls.append(url)

        # 2. og:image как резерв
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # Дедупликация
        seen: set = set()
        unique: List[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    # ------------------------------------------------------------------ #
    # Основной метод                                                      #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта."""
        try:
            dish_name = self.extract_dish_name()
            description = self.extract_description()
            ingredients = self.extract_ingredients()
            instructions = self.extract_instructions()
            category = self.extract_category()
            notes = self.extract_notes()
            tags = self.extract_tags()

            return {
                "dish_name": dish_name,
                "description": description,
                "ingredients": ingredients,
                "instructions": instructions,
                "category": category,
                "prep_time": self.extract_prep_time(),
                "cook_time": self.extract_cook_time(),
                "total_time": self.extract_total_time(),
                "notes": notes,
                "image_urls": self.extract_image_urls(),
                "tags": tags,
            }
        except Exception as exc:
            logger.error("Ошибка при извлечении данных из %s: %s", self.html_path, exc, exc_info=True)
            return {
                "dish_name": None,
                "description": None,
                "ingredients": None,
                "instructions": None,
                "category": None,
                "prep_time": None,
                "cook_time": None,
                "total_time": None,
                "notes": None,
                "image_urls": None,
                "tags": None,
            }


def main() -> None:
    """Обработка всех HTML в директории preprocessed/deliciousmagazine_nl."""
    import os

    recipes_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'preprocessed',
        'deliciousmagazine_nl',
    )

    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(DeliciousMagazineNlExtractor, recipes_dir)
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python deliciousmagazine_nl.py")


if __name__ == "__main__":
    main()
