"""
Экстрактор данных рецептов для сайта madfolket.dk
"""

import sys
import logging
from pathlib import Path
import json
import re
from typing import Optional, List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class MadfolketDkExtractor(BaseRecipeExtractor):
    """Экстрактор для madfolket.dk (Inertia.js / JSON-LD)"""

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _get_inertia_recipe(self) -> Optional[Dict[str, Any]]:
        """
        Извлекает данные рецепта из атрибута data-page тега #app
        (Inertia.js SPA).
        """
        app_div = self.soup.find('div', id='app')
        if not app_div:
            return None
        data_page_attr = app_div.get('data-page')
        if not data_page_attr:
            return None
        try:
            page_data = json.loads(data_page_attr)
            return page_data.get('props', {}).get('recipe', {}).get('data')
        except (json.JSONDecodeError, AttributeError):
            logger.warning("Не удалось разобрать data-page JSON")
            return None

    def _get_json_ld_recipe(self) -> Optional[Dict[str, Any]]:
        """Возвращает первый JSON-LD объект с @type == 'Recipe'."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                elif isinstance(data, dict):
                    if data.get('@type') == 'Recipe':
                        return data
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    @staticmethod
    def _format_minutes(minutes: Any) -> Optional[str]:
        """Форматирует количество минут в строку вида '45 minutes'."""
        if minutes is None:
            return None
        try:
            m = int(minutes)
            return f"{m} minutes" if m > 0 else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """Конвертирует ISO 8601 duration (PT45M, PT1H30M) в '90 minutes'."""
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
        total = hours * 60 + minutes
        return f"{total} minutes" if total > 0 else None

    # ------------------------------------------------------------------ #
    #  Field extractors                                                    #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Название блюда."""
        recipe = self._get_inertia_recipe()
        if recipe and recipe.get('name'):
            return self.clean_text(recipe['name'])

        ld = self._get_json_ld_recipe()
        if ld and ld.get('name'):
            return self.clean_text(ld['name'])

        og = self.soup.find('meta', property='og:title')
        if og and og.get('content'):
            return self.clean_text(og['content'])

        return None

    def extract_description(self) -> Optional[str]:
        """Краткое описание рецепта."""
        recipe = self._get_inertia_recipe()
        if recipe and recipe.get('description'):
            return self.clean_text(recipe['description'])

        ld = self._get_json_ld_recipe()
        if ld and ld.get('description'):
            return self.clean_text(ld['description'])

        meta = self.soup.find('meta', {'name': 'description'})
        if meta and meta.get('content'):
            return self.clean_text(meta['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Возвращает JSON-строку списка ингредиентов с полями name/amount/unit.
        Основной источник — Inertia data-page (структурированные данные
        по частям рецепта).  Запасной — JSON-LD recipeIngredient.
        """
        # --- Primary: Inertia data-page ---
        recipe = self._get_inertia_recipe()
        if recipe and recipe.get('parts'):
            ingredients: List[Dict[str, Any]] = []
            for part in recipe['parts']:
                for ing in part.get('ingredients', []):
                    name = self.clean_text(ing.get('name', ''))
                    if not name:
                        continue
                    pivot = ing.get('pivot', {})
                    raw_qty = pivot.get('quantity')
                    unit_obj = ing.get('unit') or {}
                    unit = unit_obj.get('abbreviation') or unit_obj.get('name')

                    # Нормализуем количество: убираем trailing zeros ("1.00" → "1")
                    amount: Optional[str] = None
                    if raw_qty is not None:
                        try:
                            fval = float(str(raw_qty))
                            if fval == int(fval):
                                amount = str(int(fval))
                            else:
                                amount = str(fval)
                        except (ValueError, TypeError):
                            amount = str(raw_qty).strip()

                    ingredients.append({
                        "name": name,
                        "unit": unit,
                        "amount": amount,
                    })
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        # --- Fallback: JSON-LD recipeIngredient ---
        ld = self._get_json_ld_recipe()
        if ld and ld.get('recipeIngredient'):
            ingredients = []
            for raw in ld['recipeIngredient']:
                parsed = self._parse_ingredient_string(raw)
                if parsed:
                    ingredients.append(parsed)
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        return None

    def _parse_ingredient_string(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Разбирает строку вида '150.00 gram Langkornet ris' на компоненты.
        Используется только как запасной вариант (JSON-LD строки).
        """
        if not text:
            return None
        text = self.clean_text(text)

        # Стандартные единицы madfolket.dk (датские сокращения и полные имена)
        units_pattern = (
            r'gram|g\b|liter|l\b|milliliter|ml|dl|'
            r'teske|tsk|spiseske|spsk|styk|stk|'
            r'fed\b|cm\b|skiver|stængler|stk\b'
        )
        pattern = rf'^([\d.,]+)\s+({units_pattern})\s+(.+)$'
        m = re.match(pattern, text, re.IGNORECASE)
        if m:
            raw_amount, unit, name = m.group(1), m.group(2), m.group(3)
            # Нормализуем количество
            try:
                fval = float(raw_amount.replace(',', '.'))
                amount = str(int(fval)) if fval == int(fval) else str(fval)
            except ValueError:
                amount = raw_amount
            # Убираем комментарий в скобках из имени
            name = re.sub(r'\s*\([^)]*\)', '', name).strip()
            return {"name": name, "unit": unit, "amount": amount}

        # Нет совпадения — возвращаем всё как название
        return {"name": text, "unit": None, "amount": None}

    def extract_instructions(self) -> Optional[str]:
        """Возвращает все шаги приготовления одной строкой."""
        # --- Primary: Inertia data-page ---
        recipe = self._get_inertia_recipe()
        if recipe and recipe.get('parts'):
            steps: List[str] = []
            for part in recipe['parts']:
                for step in part.get('instructions', []):
                    desc = step.get('description', '')
                    if desc:
                        steps.append(self.clean_text(desc))
            if steps:
                return ' '.join(steps)

        # --- Fallback: JSON-LD recipeInstructions ---
        ld = self._get_json_ld_recipe()
        if ld and ld.get('recipeInstructions'):
            steps = []
            instructions = ld['recipeInstructions']
            for item in instructions:
                if isinstance(item, str):
                    steps.append(self.clean_text(item))
                elif isinstance(item, dict):
                    if item.get('@type') == 'HowToSection':
                        for sub in item.get('itemListElement', []):
                            if isinstance(sub, dict) and sub.get('text'):
                                steps.append(self.clean_text(sub['text']))
                    elif item.get('text'):
                        steps.append(self.clean_text(item['text']))
            if steps:
                return ' '.join(steps)

        return None

    def extract_category(self) -> Optional[str]:
        """
        Категория блюда.
        Предпочитаем группу 'maltiid' (тип приёма пищи) из tags_by_group.
        Запасной вариант — recipeCategory из JSON-LD.
        """
        recipe = self._get_inertia_recipe()
        if recipe:
            tbg = recipe.get('tags_by_group', {}) or {}
            for group_key in ('maltiid', 'rettype'):
                group = tbg.get(group_key)
                if group and isinstance(group, list) and group:
                    return self.clean_text(group[0].get('name', ''))

        ld = self._get_json_ld_recipe()
        if ld and ld.get('recipeCategory'):
            return self.clean_text(ld['recipeCategory'])

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки."""
        recipe = self._get_inertia_recipe()
        if recipe and recipe.get('prep_time_minutes') is not None:
            return self._format_minutes(recipe['prep_time_minutes'])

        ld = self._get_json_ld_recipe()
        if ld and ld.get('prepTime'):
            return self._parse_iso_duration(ld['prepTime'])

        return None

    def extract_cook_time(self) -> Optional[str]:
        """Время готовки."""
        recipe = self._get_inertia_recipe()
        if recipe and recipe.get('cook_time_minutes') is not None:
            return self._format_minutes(recipe['cook_time_minutes'])

        ld = self._get_json_ld_recipe()
        if ld and ld.get('cookTime'):
            return self._parse_iso_duration(ld['cookTime'])

        return None

    def extract_total_time(self) -> Optional[str]:
        """Общее время приготовления."""
        recipe = self._get_inertia_recipe()
        if recipe:
            prep = recipe.get('prep_time_minutes')
            cook = recipe.get('cook_time_minutes')
            if prep is not None and cook is not None:
                try:
                    total = int(prep) + int(cook)
                    return self._format_minutes(total) if total > 0 else None
                except (ValueError, TypeError):
                    pass

        ld = self._get_json_ld_recipe()
        if ld and ld.get('totalTime'):
            return self._parse_iso_duration(ld['totalTime'])

        return None

    def extract_notes(self) -> Optional[str]:
        """
        Заметки из раздела 'Gennemsigtighed' (прозрачность / AI-disclaimer).
        Ищем в HTML: div с классом 'border-border' содержащий список li.
        """
        try:
            # Ищем блок прозрачности по его характерному классу
            transparency_div = self.soup.find(
                'div',
                class_=lambda c: c and 'border-border' in c and 'bg-muted' in c
            )
            if transparency_div:
                items = transparency_div.find_all('span', class_=lambda c: c and 'text-muted' in c)
                texts = [self.clean_text(s.get_text()) for s in items if s.get_text(strip=True)]
                if texts:
                    return ' '.join(texts)

            # Запасной: ищем блок с заголовком 'Gennemsigtighed'
            header = self.soup.find(string=re.compile(r'Gennemsigtighed', re.I))
            if header:
                container = header.parent
                for _ in range(4):
                    container = container.parent
                    li_texts = [
                        self.clean_text(li.get_text())
                        for li in container.find_all('li')
                        if li.get_text(strip=True)
                    ]
                    if li_texts:
                        return ' '.join(li_texts)
        except Exception as exc:
            logger.warning("Ошибка при извлечении notes: %s", exc)

        return None

    def extract_tags(self) -> Optional[str]:
        """
        Теги рецепта из массива tags в Inertia data-page.
        Запасной вариант — keywords из JSON-LD.
        """
        recipe = self._get_inertia_recipe()
        if recipe and recipe.get('tags'):
            names = [
                self.clean_text(t.get('name', ''))
                for t in recipe['tags']
                if t.get('name')
            ]
            if names:
                return ','.join(names)

        ld = self._get_json_ld_recipe()
        if ld and ld.get('keywords'):
            keywords_raw = ld['keywords']
            # Фильтруем служебные слова
            stopwords = {'opskrift', 'dansk mad', 'madlavning'}
            tags = [
                k.strip()
                for k in keywords_raw.split(',')
                if k.strip() and k.strip().lower() not in stopwords
            ]
            if tags:
                return ','.join(tags)

        return None

    def extract_image_urls(self) -> Optional[str]:
        """URL изображений рецепта через запятую без пробелов."""
        urls: List[str] = []

        # 1. Основное изображение из Inertia data-page
        recipe = self._get_inertia_recipe()
        if recipe and recipe.get('image_url'):
            urls.append(recipe['image_url'])

        # 2. Изображения из JSON-LD
        ld = self._get_json_ld_recipe()
        if ld and ld.get('image'):
            img = ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend(i for i in img if isinstance(i, str))
            elif isinstance(img, dict):
                url = img.get('url') or img.get('contentUrl')
                if url:
                    urls.append(url)

        # 3. og:image как запасной вариант
        og = self.soup.find('meta', property='og:image')
        if og and og.get('content'):
            urls.append(og['content'])

        # Убираем дубликаты, сохраняя порядок
        seen: set = set()
        unique: List[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта; отсутствующие поля равны None.
        """
        try:
            dish_name = self.extract_dish_name()
            description = self.extract_description()
            ingredients = self.extract_ingredients()
            instructions = self.extract_instructions()
            category = self.extract_category()
            prep_time = self.extract_prep_time()
            cook_time = self.extract_cook_time()
            total_time = self.extract_total_time()
            notes = self.extract_notes()
            tags = self.extract_tags()
            image_urls = self.extract_image_urls()
        except Exception as exc:
            logger.error("Критическая ошибка при разборе %s: %s", self.html_path, exc)
            dish_name = description = ingredients = instructions = None
            category = prep_time = cook_time = total_time = None
            notes = tags = image_urls = None

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


def main() -> None:
    """Точка входа для обработки директории с HTML файлами."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "madfolket_dk")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(MadfolketDkExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python madfolket_dk.py")


if __name__ == "__main__":
    main()
