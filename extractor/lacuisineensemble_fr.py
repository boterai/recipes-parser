"""
Экстрактор данных рецептов для сайта lacuisineensemble.fr
Сайт использует WordPress + WP Recipe Maker (WPRM).
Основной источник структурированных данных — JSON-LD (@graph → Recipe)
и WPRM-разметка в HTML (классы wprm-recipe-*).
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


class LacuisineensembleFrExtractor(BaseRecipeExtractor):
    """Экстрактор для lacuisineensemble.fr (WordPress + WP Recipe Maker)"""

    def _get_recipe_json_ld(self) -> Optional[dict]:
        """
        Ищет и возвращает объект Recipe из JSON-LD разметки страницы.
        Поддерживает @graph, список и одиночный объект Recipe.
        """
        for script in self.soup.find_all('script', type='application/ld+json'):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
            except (json.JSONDecodeError, AttributeError):
                logger.debug("Не удалось разобрать JSON-LD скрипт")
                continue

            if isinstance(data, dict):
                if data.get('@type') == 'Recipe':
                    return data
                for item in data.get('@graph', []):
                    if isinstance(item, dict) and item.get('@type') == 'Recipe':
                        return item
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get('@type') == 'Recipe':
                        return item
        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Преобразует ISO 8601 длительность в строку вида «X minutes».

        Args:
            duration: строка вида «PT10M» или «PT1H30M»

        Returns:
            Строка «N minutes» или None
        """
        if not duration or not duration.startswith('PT'):
            return None
        s = duration[2:]  # убираем 'PT'
        hours, minutes = 0, 0
        h = re.search(r'(\d+)H', s)
        m = re.search(r'(\d+)M', s)
        if h:
            hours = int(h.group(1))
        if m:
            minutes = int(m.group(1))
        total = hours * 60 + minutes
        return f"{total} minutes" if total > 0 else None

    @staticmethod
    def _strip_french_de(name: str) -> str:
        """Убирает ведущий французский артикль «de », «d'» или «d'» из названия ингредиента."""
        return re.sub(r"^d[e'\u2019]\s*", '', name, flags=re.IGNORECASE).strip()

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из WPRM или JSON-LD."""
        # 1. WPRM-заголовок рецепта
        el = self.soup.find(class_='wprm-recipe-name')
        if el:
            name = self.clean_text(el.get_text())
            if name:
                return name
        # 2. JSON-LD
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('name'):
            return self.clean_text(recipe['name'])
        # 3. Заголовок h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания из WPRM summary, JSON-LD или og:description."""
        # 1. WPRM summary
        el = self.soup.find(class_='wprm-recipe-summary')
        if el:
            text = self.clean_text(el.get_text())
            if text:
                return text
        # 2. JSON-LD
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('description'):
            return self.clean_text(recipe['description'])
        # 3. og:description
        og = self.soup.find('meta', property='og:description')
        if og and og.get('content'):
            return self.clean_text(og['content'])
        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из WPRM li-элементов.
        Каждый ингредиент — словарь {'name', 'amount', 'unit'}.
        Убирает французский артикль «de/d'» из начала названия.
        """
        ingredients = []
        items = self.soup.find_all('li', class_='wprm-recipe-ingredient')
        if not items:
            logger.warning("Элементы ингредиентов WPRM не найдены: %s", self.html_path)
            return None

        for item in items:
            amount_el = item.find(class_='wprm-recipe-ingredient-amount')
            unit_el = item.find(class_='wprm-recipe-ingredient-unit')
            name_el = item.find(class_='wprm-recipe-ingredient-name')
            if not name_el:
                continue
            name = self._strip_french_de(self.clean_text(name_el.get_text()))
            amount = self.clean_text(amount_el.get_text()) if amount_el else None
            unit = self.clean_text(unit_el.get_text()) if unit_el else None
            if name:
                ingredients.append({
                    "name": name,
                    "amount": amount or None,
                    "unit": unit or None,
                })

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_instructions(self) -> Optional[str]:
        """
        Извлечение шагов приготовления из JSON-LD (приоритет)
        или WPRM HTML-элементов (запасной вариант).
        """
        steps = []
        # 1. JSON-LD recipeInstructions
        recipe = self._get_recipe_json_ld()
        if recipe and 'recipeInstructions' in recipe:
            for step in recipe['recipeInstructions']:
                if isinstance(step, dict):
                    text = self.clean_text(step.get('text', ''))
                elif isinstance(step, str):
                    text = self.clean_text(step)
                else:
                    continue
                if text:
                    steps.append(text)
            if steps:
                return ' '.join(steps)

        # 2. WPRM HTML-инструкции
        instr_items = self.soup.find_all('li', class_='wprm-recipe-instruction')
        for item in instr_items:
            text_el = item.find(class_='wprm-recipe-instruction-text')
            text = self.clean_text((text_el or item).get_text())
            if text:
                steps.append(text)

        if not steps:
            logger.warning("Шаги приготовления не найдены: %s", self.html_path)
        return ' '.join(steps) if steps else None

    def _wprm_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени из WPRM HTML-элементов (для страниц без JSON-LD).

        Args:
            time_type: «prep_time», «cook_time» или «total_time»

        Returns:
            Строка «N minutes» или None
        """
        hours, minutes = 0, 0
        hours_el = self.soup.find(class_=re.compile(rf'wprm-recipe-{time_type}-hours\b'))
        mins_el = self.soup.find(class_=re.compile(rf'wprm-recipe-{time_type}-minutes\b'))
        if hours_el:
            h_text = next(
                (s.strip() for s in hours_el.strings if s.strip().isdigit()), None
            )
            if h_text:
                hours = int(h_text)
        if mins_el:
            m_text = next(
                (s.strip() for s in mins_el.strings if s.strip().isdigit()), None
            )
            if m_text:
                minutes = int(m_text)
        total = hours * 60 + minutes
        return f"{total} minutes" if total > 0 else None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки."""
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('prepTime'):
            return self._parse_iso_duration(recipe['prepTime'])
        return self._wprm_time('prep_time')

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления."""
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('cookTime'):
            return self._parse_iso_duration(recipe['cookTime'])
        return self._wprm_time('cook_time')

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени."""
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('totalTime'):
            return self._parse_iso_duration(recipe['totalTime'])
        return self._wprm_time('total_time')

    def extract_category(self) -> Optional[str]:
        """Извлечение категории (type de plat / course) из WPRM или JSON-LD."""
        # 1. WPRM course-спаны (не контейнер и не лейбл)
        values = []
        for span in self.soup.find_all(class_='wprm-recipe-course'):
            classes = span.get('class', [])
            if 'wprm-recipe-course-container' in classes or 'wprm-recipe-course-label' in classes:
                continue
            text = self.clean_text(span.get_text())
            if text:
                values.append(text)
        if values:
            return ', '.join(values)
        # 2. JSON-LD recipeCategory
        recipe = self._get_recipe_json_ld()
        if recipe:
            cats = recipe.get('recipeCategory', [])
            if isinstance(cats, list) and cats:
                return ', '.join(str(c) for c in cats)
            if isinstance(cats, str) and cats:
                return cats
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок к рецепту из WPRM notes-секции."""
        notes_el = self.soup.find(class_='wprm-recipe-notes')
        if notes_el:
            text = self.clean_text(notes_el.get_text())
            if text:
                return text
        return None

    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов из WPRM keyword/cuisine спанов или JSON-LD.
        Формат: строка с тегами через «, ».
        """
        tags = []

        # 1. WPRM keyword-спаны
        for span in self.soup.find_all(class_='wprm-recipe-keyword'):
            classes = span.get('class', [])
            if 'wprm-recipe-keyword-container' in classes or 'wprm-recipe-keyword-label' in classes:
                continue
            text = self.clean_text(span.get_text())
            if text:
                tags.extend(t.strip() for t in text.split(',') if t.strip())

        # 2. WPRM cuisine-спаны
        for span in self.soup.find_all(class_='wprm-recipe-cuisine'):
            classes = span.get('class', [])
            if 'wprm-recipe-cuisine-container' in classes or 'wprm-recipe-cuisine-label' in classes:
                continue
            text = self.clean_text(span.get_text())
            if text:
                tags.extend(t.strip() for t in text.split(',') if t.strip())

        # 3. JSON-LD keywords + recipeCuisine как запасной вариант
        if not tags:
            recipe = self._get_recipe_json_ld()
            if recipe:
                kw = recipe.get('keywords', '')
                if isinstance(kw, list):
                    tags.extend(str(k) for k in kw if k)
                elif isinstance(kw, str) and kw:
                    tags.extend(t.strip() for t in kw.split(',') if t.strip())
                cuisine = recipe.get('recipeCuisine', [])
                if isinstance(cuisine, list):
                    tags.extend(str(c) for c in cuisine if c)
                elif isinstance(cuisine, str) and cuisine:
                    tags.append(cuisine)

        if not tags:
            return None

        # Дедупликация с сохранением порядка
        seen: set = set()
        unique = []
        for t in tags:
            key = t.lower()
            if key not in seen:
                seen.add(key)
                unique.append(t)
        return ', '.join(unique)

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из JSON-LD или og:image."""
        urls = []
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
                        url = i.get('url') or i.get('contentUrl')
                        if url:
                            urls.append(url)
        # 2. og:image как запасной вариант
        if not urls:
            og = self.soup.find('meta', property='og:image')
            if og and og.get('content'):
                urls.append(og['content'])

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
            Словарь с полями: dish_name, description, ingredients, instructions,
            category, prep_time, cook_time, total_time, notes, image_urls, tags.
        """
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_instructions(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags(),
        }


def main():
    repo_root = Path(__file__).parent.parent
    directory_path = repo_root / "preprocessed" / "lacuisineensemble_fr"
    if directory_path.exists() and directory_path.is_dir():
        process_directory(LacuisineensembleFrExtractor, str(directory_path))
    else:
        print(f"Директория не найдена: {directory_path}")
        print("Использование: python lacuisineensemble_fr.py")


if __name__ == "__main__":
    main()
