"""
Экстрактор данных рецептов для сайта essen-und-trinken.de
"""

import sys
import logging
from pathlib import Path
import json
import re
from typing import Optional, List

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Ключевые слова для определения основного типа блюда (категория).
# Порядок имеет значение: более специфичные типы стоят раньше.
_FOOD_TYPE_KEYWORDS = [
    'kuchen', 'torte', 'tarte', 'tart', 'pie',
    'gebäck', 'gebaeck', 'keks', 'kekse', 'plätzchen', 'plaetzchen',
    'beilage', 'hauptgericht', 'vorspeise', 'dessert', 'nachtisch',
    'suppe', 'eintopf', 'ragout', 'auflauf',
    'cocktail',  # до aperitif — более специфичный тип
    'getränk', 'getraenk', 'getränke', 'getraenke',
    'aperitif', 'shot', 'smoothie', 'shake',
    'salat', 'pizza', 'pasta', 'risotto', 'quiche',
    'sandwich', 'burger', 'wrap', 'bowl', 'curry',
    'mousse', 'parfait', 'sorbet', 'eis', 'pralinen', 'bonbon',
    'muffin', 'brownie', 'strudel', 'gugelhupf',
    'brot', 'brötchen',
    'steak', 'schnitzel', 'roulade', 'braten',
    'frühstück', 'fingerfood', 'dip', 'sauce', 'marinade',
    'snack', 'frittata', 'soufflé',
]


class EssenUndTrinkenDeExtractor(BaseRecipeExtractor):
    """Экстрактор для essen-und-trinken.de"""

    # ------------------------------------------------------------------ #
    # Вспомогательные методы                                             #
    # ------------------------------------------------------------------ #

    def _get_recipe_ld_json(self) -> Optional[dict]:
        """Возвращает первый JSON-LD блок с типом Recipe, или None."""
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get('@type', '')
                    types = item_type if isinstance(item_type, list) else [item_type]
                    if 'Recipe' in types:
                        return item
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в человекочитаемый формат.

        Примеры:
            'PT35M'  -> '35 minutes'
            'PT1H'   -> '1 hour'
            'PT1H30M' -> '1 hour 30 minutes'
        """
        if not duration or not duration.startswith('PT'):
            return None

        body = duration[2:]
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

        if total_minutes < 60:
            return f"{total_minutes} minutes"
        if total_minutes % 60 == 0:
            h = total_minutes // 60
            return f"{h} hour" if h == 1 else f"{h} hours"
        h = total_minutes // 60
        m = total_minutes % 60
        hour_part = f"{h} hour" if h == 1 else f"{h} hours"
        return f"{hour_part} {m} minutes"

    # ------------------------------------------------------------------ #
    # Метод извлечения названия блюда                                     #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из h1 с очисткой SEO-суффиксов."""
        h1 = self.soup.find('h1')
        if not h1:
            return None

        title = self.clean_text(h1.get_text())
        if not title:
            return None

        # Убираем суффикс после em-dash или дефиса с пробелами: " – ..."
        title = re.sub(r'\s+[–\-]\s+.+$', '', title)
        # Убираем суффикс ": Rezept ..." (без учёта регистра)
        title = re.sub(r'\s*:\s+Rezept\b.*$', '', title, flags=re.IGNORECASE)
        # Убираем суффикс ": So geht ..." / ": So wird ..."
        title = re.sub(r'\s*:\s+So\s+\w+.*$', '', title, flags=re.IGNORECASE)
        # Убираем суффикс, оканчивающийся на "!" или "?"
        title = re.sub(r'\s*:[^:]+[!?]$', '', title)

        return self.clean_text(title) or None

    # ------------------------------------------------------------------ #
    # Метод извлечения описания                                           #
    # ------------------------------------------------------------------ #

    def extract_description(self) -> Optional[str]:
        """Извлечение короткого описания рецепта (intro)."""
        # Приоритет: div.recipe__intro (наиболее точный intro-текст)
        intro = self.soup.find(class_='recipe__intro')
        if intro:
            text = self.clean_text(intro.get_text())
            if text:
                return text

        # Запасной вариант: JSON-LD description
        ld = self._get_recipe_ld_json()
        if ld and ld.get('description'):
            return self.clean_text(ld['description'])

        # Запасной вариант: og:description meta
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    # ------------------------------------------------------------------ #
    # Метод извлечения ингредиентов                                       #
    # ------------------------------------------------------------------ #

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из HTML-секции recipe-ingredients.

        Структура HTML:
            <x-beautify-number data-base-value="350">350</x-beautify-number>
            <p class="recipe-ingredients__label">
                <span class="recipe-ingredients__unit-singular">g</span>
                <span class="recipe-ingredients__unit-plural">g</span>
                <span data-label="">Mehl</span>
                <span>(optional extra info)</span>  <!-- не всегда -->
            </p>
        """
        ing_section = self.soup.find('section', class_='recipe-ingredients')
        if not ing_section:
            logger.warning("recipe-ingredients section not found")
            return None

        # Контейнер с парами amount + label
        portions = ing_section.find(class_=re.compile(r'recipe-ingredients__list', re.I))
        if not portions:
            logger.warning("recipe-ingredients__list not found")
            return None

        # Собираем все x-beautify-number и p.recipe-ingredients__label по порядку
        amounts = portions.find_all(
            'x-beautify-number',
            class_=re.compile(r'recipe-ingredients__amount', re.I)
        )
        labels = portions.find_all(
            'p',
            class_=re.compile(r'recipe-ingredients__label', re.I)
        )

        if len(amounts) != len(labels):
            logger.warning(
                "Mismatch: %d amounts vs %d labels — trying pairwise anyway",
                len(amounts), len(labels)
            )

        ingredients: List[dict] = []
        for amount_tag, label_tag in zip(amounts, labels):
            # --- Количество ---
            raw_amount = amount_tag.get('data-base-value', '').strip()
            amount = raw_amount if raw_amount else None

            # --- Единица измерения и название ---
            unit_singular = label_tag.find(
                'span', class_='recipe-ingredients__unit-singular'
            )
            unit_text = self.clean_text(unit_singular.get_text()) if unit_singular else ''

            # Span с названием ингредиента (имеет атрибут data-label)
            name_span = label_tag.find('span', attrs={'data-label': True})
            name_text = self.clean_text(name_span.get_text()) if name_span else ''

            # Дополнительный span без специального класса (например "(Kl. M)", "(weich)")
            extra_text = ''
            for span in label_tag.find_all('span'):
                span_classes = span.get('class', [])
                has_unit_class = any(
                    'recipe-ingredients__unit' in c for c in span_classes
                )
                has_data_label = span.has_attr('data-label')
                if not has_unit_class and not has_data_label:
                    raw = self.clean_text(span.get_text())
                    if raw:
                        extra_text = raw
                        break

            # Правила определения unit и name при наличии extra_text
            if extra_text:
                # Если extra_text в скобках и unit пустой → extra_text = unit
                parens_match = re.match(r'^\((.+)\)$', extra_text)
                if parens_match and not unit_text:
                    unit_text = parens_match.group(1).strip()
                elif unit_text:
                    # unit есть → extra_text добавляется к имени
                    name_text = f"{name_text} {extra_text}".strip() if name_text else extra_text

            ingredients.append({
                "name": name_text or None,
                "amount": amount,
                "unit": unit_text or None,
            })

        if not ingredients:
            logger.warning("No ingredients extracted from HTML")
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    # ------------------------------------------------------------------ #
    # Метод извлечения инструкций                                         #
    # ------------------------------------------------------------------ #

    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления из JSON-LD или HTML."""
        # 1. Пробуем JSON-LD recipeInstructions
        ld = self._get_recipe_ld_json()
        if ld and 'recipeInstructions' in ld:
            instructions = ld['recipeInstructions']
            steps = []
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict):
                        text = step.get('text', '')
                    elif isinstance(step, str):
                        text = step
                    else:
                        continue
                    text = self.clean_text(text)
                    if text:
                        steps.append(text)
            elif isinstance(instructions, str):
                text = self.clean_text(instructions)
                if text:
                    steps.append(text)

            if steps:
                return ' '.join(steps)

        # 2. Запасной вариант: HTML-блок с шагами приготовления
        prep_group = self.soup.find(
            'div', class_=re.compile(r'group--preparation-steps', re.I)
        )
        if prep_group:
            step_items = prep_group.find_all('li', class_=re.compile(r'group__text-element', re.I))
            steps = []
            for item in step_items:
                text_div = item.find(class_=re.compile(r'text-element--step', re.I))
                text = (text_div or item).get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                if text:
                    steps.append(text)
            if steps:
                return ' '.join(steps)

        logger.warning("Instructions not found")
        return None

    # ------------------------------------------------------------------ #
    # Метод извлечения категории                                          #
    # ------------------------------------------------------------------ #

    def extract_category(self) -> Optional[str]:
        """
        Извлечение основной категории блюда из recipe-meta__item--categories.

        Для каждой категории определяется позиция первого совпадающего ключевого слова
        в _FOOD_TYPE_KEYWORDS (чем меньше позиция — тем специфичнее тип блюда).
        Возвращается категория с наименьшей позицией совпадения.
        """
        categories = self._get_all_recipe_categories()
        if not categories:
            return None

        best_cat: Optional[str] = None
        best_pos = len(_FOOD_TYPE_KEYWORDS)  # «бесконечность»

        for cat in categories:
            cat_lower = cat.lower()
            for pos, keyword in enumerate(_FOOD_TYPE_KEYWORDS):
                if keyword in cat_lower:
                    if pos < best_pos:
                        best_pos = pos
                        best_cat = cat
                    break  # для данной категории найдено первое совпадение

        # Если ни одна категория не совпала — возвращаем первую
        return best_cat if best_cat is not None else categories[0]

    def _get_all_recipe_categories(self) -> List[str]:
        """Возвращает список всех категорий из блока 'Dieses Rezept ist'."""
        cat_item = self.soup.find(class_='recipe-meta__item--categories')
        if not cat_item:
            return []

        from bs4 import Tag as _Tag

        categories = []
        # Перебираем все дочерние элементы: и ссылки, и текстовые узлы
        for child in cat_item.children:
            if isinstance(child, _Tag):
                if child.name == 'a':
                    text = self.clean_text(child.get_text())
                    if text:
                        categories.append(text)
            else:
                # NavigableString — текстовый узел (например "Alkohol,")
                text = str(child).strip().rstrip(',').strip()
                if text and text not in ('Dieses Rezept ist', ''):
                    # Может содержать несколько значений через запятую
                    for part in text.split(','):
                        part = part.strip()
                        if part:
                            categories.append(part)

        return categories

    # ------------------------------------------------------------------ #
    # Методы извлечения времени                                          #
    # ------------------------------------------------------------------ #

    def extract_total_time(self) -> Optional[str]:
        """Общее время приготовления из JSON-LD или HTML 'Fertig in'."""
        # Из JSON-LD
        ld = self._get_recipe_ld_json()
        if ld:
            total = ld.get('totalTime')
            if total:
                result = self._parse_iso_duration(total)
                if result:
                    return result

        # Из HTML: recipe-meta__item--cook-time
        cook_time_item = self.soup.find(class_='recipe-meta__item--cook-time')
        if cook_time_item:
            # Ищем span с самим значением времени
            spans = cook_time_item.find_all('span')
            for span in spans:
                text = self.clean_text(span.get_text())
                # Пропускаем заголовки ("Fertig in", "Fertig:")
                if text and not re.match(r'^(Fertig|Ready|Bereit)', text, re.IGNORECASE):
                    # Конвертируем "35 Minuten" → "35 minutes"
                    return self._normalize_german_time(text)

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки из JSON-LD prepTime."""
        ld = self._get_recipe_ld_json()
        if ld:
            prep = ld.get('prepTime')
            if prep:
                return self._parse_iso_duration(prep)
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Время готовки из JSON-LD cookTime или текста инструкций."""
        ld = self._get_recipe_ld_json()
        if ld:
            cook = ld.get('cookTime')
            if cook:
                return self._parse_iso_duration(cook)

        # Попробуем извлечь время из текста инструкций
        instructions = self.extract_instructions()
        if instructions:
            return self._extract_cook_time_from_text(instructions)

        return None

    @staticmethod
    def _normalize_german_time(text: str) -> Optional[str]:
        """Конвертирует немецкое время 'X Minuten' / 'X Stunden' в 'X minutes'."""
        text = text.strip()
        # "35 Minuten" → "35 minutes"
        m = re.match(r'^(\d+)\s+Minuten?$', text, re.IGNORECASE)
        if m:
            return f"{m.group(1)} minutes"
        # "1 Stunde" / "2 Stunden"
        m = re.match(r'^(\d+)\s+Stunden?$', text, re.IGNORECASE)
        if m:
            h = int(m.group(1))
            return f"{h} hour" if h == 1 else f"{h} hours"
        # "1 Stunde 30 Minuten"
        m = re.match(r'^(\d+)\s+Stunden?\s+(\d+)\s+Minuten?$', text, re.IGNORECASE)
        if m:
            h = int(m.group(1))
            mins = int(m.group(2))
            hour_part = f"{h} hour" if h == 1 else f"{h} hours"
            return f"{hour_part} {mins} minutes"
        return text or None

    @staticmethod
    def _extract_cook_time_from_text(text: str) -> Optional[str]:
        """Извлекает время готовки из текста инструкций по кулинарным глаголам."""
        # Диапазон минут перед глаголом готовки: "20–30 Minuten backen"
        range_pattern = (
            r'(\d+)\s*[–\-]\s*(\d+)\s*(?:Min\.?|Minuten?)'
            r'\s+(?:gar\s+)?'
            r'(?:backen|braten|kochen|garen|schmoren|dünsten|dämpfen'
            r'|ziehen|frittieren|grillen|rösten|simmern|pochieren|blanchieren)'
        )
        m = re.search(range_pattern, text, re.IGNORECASE)
        if m:
            return f"{m.group(1)}-{m.group(2)} minutes"

        # Одно значение минут перед глаголом: "16 Minuten backen"
        single_pattern = (
            r'(\d+)\s*(?:Min\.?|Minuten?)'
            r'\s+(?:gar\s+)?'
            r'(?:backen|braten|kochen|garen|schmoren|dünsten|dämpfen'
            r'|ziehen|frittieren|grillen|rösten|simmern|pochieren|blanchieren)'
        )
        m = re.search(single_pattern, text, re.IGNORECASE)
        if m:
            return f"{m.group(1)} minutes"

        return None

    # ------------------------------------------------------------------ #
    # Метод извлечения заметок/советов                                   #
    # ------------------------------------------------------------------ #

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок/советов.

        Приоритеты поиска:
          1. Встроенный инфобокс (recipe__embedded-list-element) БЕЗ заголовка h3 —
             чистый совет (например Aperol Spritz).
          2. Параграф с тегом <strong>Tipp:</strong> в тексте рецепта.
          3. Встроенный инфобокс с заголовком h3, начинающимся на «Tipp» —
             редакционный совет.
          4. Список-советов после заголовка h2 с «Tipp» в тексте.
        """
        # 1. Инфобокс без заголовка h3 (чистый «Tipp:» блок)
        for infobox in self.soup.find_all(class_='recipe__embedded-list-element'):
            h3 = infobox.find('h3')
            if h3:
                # Если h3 начинается на "Tipp" — это редакционный совет (приоритет 3)
                continue
            content = infobox.find(
                class_=re.compile(r'infobox-text|list-element__content', re.I)
            )
            if content:
                text = self.clean_text(content.get_text())
                text = re.sub(r'^Tipps?\s*:\s*', '', text, flags=re.IGNORECASE)
                if text:
                    return text

        # 2. Параграф с <strong>Tipp:</strong> в теле рецепта
        recipe_body = self.soup.find(class_='recipe__body')
        if recipe_body:
            for p in recipe_body.find_all('p'):
                strong = p.find('strong')
                if strong and re.match(r'^Tipps?:?$', strong.get_text(strip=True), re.IGNORECASE):
                    text = self.clean_text(p.get_text())
                    text = re.sub(r'^Tipps?\s*:\s*', '', text, flags=re.IGNORECASE)
                    if text:
                        return text

        # 3. Инфобокс с заголовком h3 начинающимся на «Tipp»
        for infobox in self.soup.find_all(class_='recipe__embedded-list-element'):
            h3 = infobox.find('h3')
            if h3 and re.match(r'^Tipp', h3.get_text(strip=True), re.IGNORECASE):
                content = infobox.find(
                    class_=re.compile(r'infobox-text|list-element__content', re.I)
                )
                if content:
                    text = self.clean_text(content.get_text())
                    if text:
                        return text

        # 4. Список после заголовка h2 «Tipps» / «Tipp»
        h2_tipps = self.soup.find('h2', string=re.compile(r'Tipp', re.I))
        if h2_tipps:
            next_elem = h2_tipps.find_next_sibling()
            if next_elem:
                text = self.clean_text(next_elem.get_text(separator=' '))
                if text:
                    # Берём только первый смысловой блок советов
                    text = re.split(r'\s{2,}', text)[0].strip()
                    if text:
                        return text

        return None

    # ------------------------------------------------------------------ #
    # Метод извлечения тегов                                             #
    # ------------------------------------------------------------------ #

    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов: все категории из 'Dieses Rezept ist'
        плюс 'Rezepteigenschaften' (основные категории).
        """
        tags: List[str] = []

        # Все категории из recipe-meta__item--categories (включая plain-text узлы)
        tags.extend(self._get_all_recipe_categories())

        # Ингредиентные/свойства из recipe-meta__item--main-categories
        main_cat_item = self.soup.find(class_='recipe-meta__item--main-categories')
        if main_cat_item:
            for a in main_cat_item.find_all('a'):
                text = self.clean_text(a.get_text())
                if text:
                    tags.append(text)

        if not tags:
            return None

        # Убираем дубликаты, сохраняя порядок
        seen: set = set()
        unique_tags: List[str] = []
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)

        return ','.join(unique_tags)

    # ------------------------------------------------------------------ #
    # Метод извлечения URL изображений                                   #
    # ------------------------------------------------------------------ #

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из JSON-LD и meta-тегов."""
        urls: List[str] = []

        # 1. JSON-LD image
        ld = self._get_recipe_ld_json()
        if ld and 'image' in ld:
            images = ld['image']
            if isinstance(images, list):
                for img in images:
                    if isinstance(img, dict) and img.get('url'):
                        urls.append(img['url'])
                    elif isinstance(img, str):
                        urls.append(img)
            elif isinstance(images, dict) and images.get('url'):
                urls.append(images['url'])
            elif isinstance(images, str):
                urls.append(images)

        # 2. og:image как запасной вариант
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])

        if not urls:
            return None

        # Убираем дубликаты, сохраняя порядок
        seen: set = set()
        unique_urls: List[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ','.join(unique_urls) if unique_urls else None

    # ------------------------------------------------------------------ #
    # Главный метод                                                       #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с полями: dish_name, description, ingredients, instructions,
            category, prep_time, cook_time, total_time, notes, image_urls, tags.
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
            "image_urls": image_urls,
            "tags": tags,
        }


def main():
    """Обработка всех HTML-файлов из директории preprocessed/essen-und-trinken_de."""
    import os
    recipes_dir = os.path.join("preprocessed", "essen-und-trinken_de")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(EssenUndTrinkenDeExtractor, recipes_dir)
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python extractor/essen-und-trinken_de.py")


if __name__ == "__main__":
    main()
