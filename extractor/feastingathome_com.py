"""
Экстрактор данных рецептов для сайта feastingathome.com
"""

import logging
import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class FeastingAtHomeExtractor(BaseRecipeExtractor):
    """Экстрактор для feastingathome.com"""

    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD (@graph → Recipe)"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')

        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue

                data = json.loads(script.string)

                # Обрабатываем @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if not isinstance(item, dict):
                            continue
                        item_type = item.get('@type', '')
                        if isinstance(item_type, list) and 'Recipe' in item_type:
                            return item
                        if item_type == 'Recipe':
                            return item

                # Данные могут быть списком
                if isinstance(data, list):
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        item_type = item.get('@type', '')
                        if isinstance(item_type, list) and 'Recipe' in item_type:
                            return item
                        if item_type == 'Recipe':
                            return item

                # Данные могут быть словарём напрямую
                if isinstance(data, dict):
                    item_type = data.get('@type', '')
                    if isinstance(item_type, list) and 'Recipe' in item_type:
                        return data
                    if item_type == 'Recipe':
                        return data

            except (json.JSONDecodeError, KeyError) as exc:
                logger.debug("Ошибка разбора JSON-LD: %s", exc)
                continue

        return None

    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат «X minutes» / «X hours Y minutes».

        Args:
            duration: строка вида «PT20M» или «PT1H30M»

        Returns:
            Строка, например «20 minutes» или «1 hour 30 minutes»
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

        if hours == 0 and minutes == 0:
            return None

        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")

        return ' '.join(parts)

    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат.

        Args:
            ingredient_text: строка вида «1 cup all-purpose flour»

        Returns:
            dict: {«name»: ..., «amount»: ..., «unit»: ...} или None
        """
        if not ingredient_text:
            return None

        text = self.clean_text(ingredient_text)

        # Заменяем Unicode-дроби на десятичные числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8',
        }
        for frac, dec in fraction_map.items():
            text = text.replace(frac, dec)

        text_lower = text.lower()

        # Примечание: однобуквенные единицы (g, l) защищены границей слова (\b),
        # чтобы не ловить первую букву слова (например «garlic», «large»)
        units_pattern = (
            r'cups?|tablespoons?|teaspoons?|tbsps?|tsps?|'
            r'pounds?|ounces?|lbs?|oz|grams?|kilograms?|kg\b|g\b|'
            r'milliliters?|liters?|ml\b|l\b|'
            r'pinch(?:es)?|dash(?:es)?|'
            r'packages?|cans?|jars?|bottles?|'
            r'inch(?:es)?|slices?|cloves?|bunches?|sprigs?|'
            r'whole|halves?|quarters?|pieces?|head|heads|'
            r'stalks?|strips?|blocks?|fillets?|handfuls?'
        )

        # Количество допускает диапазоны вида «1-2», «8-12», обычные дроби «1/2»
        # и смешанные числа «1 1/2»
        amount_pattern = r'[\d][\d\s/.,\-]*'
        pattern = rf'^({amount_pattern})?\s*({units_pattern})?\s*(.+)'
        match = re.match(pattern, text_lower, re.IGNORECASE)

        if not match:
            return {'name': text, 'amount': None, 'unit': None}

        amount_str, unit, name = match.groups()

        # Обработка количества
        amount: Optional[str] = None
        if amount_str:
            amount_str = amount_str.strip().rstrip('-').strip()
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0.0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        try:
                            total += float(num) / float(denom)
                        except (ValueError, ZeroDivisionError):
                            pass
                    else:
                        try:
                            total += float(part.replace(',', '.'))
                        except ValueError:
                            pass
                amount = str(total) if total else amount_str
            else:
                amount = amount_str.replace(',', '.')

        unit = unit.strip() if unit else None

        # Очистка названия
        name = re.sub(r'\([^)]*\)', '', name)  # убираем скобки
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish)\b', '', name, flags=re.IGNORECASE)
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()

        if not name or len(name) < 2:
            return None

        return {'name': name, 'amount': amount, 'unit': unit}

    # ------------------------------------------------------------------ #
    # Методы извлечения отдельных полей                                    #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe = self._get_json_ld_recipe()
        if recipe and 'name' in recipe:
            return self.clean_text(recipe['name'])

        # Запасной вариант — H1 заголовок
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        # Meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s+[|–-].*$', '', title)
            return self.clean_text(title)

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe = self._get_json_ld_recipe()
        if recipe and 'description' in recipe:
            return self.clean_text(recipe['description'])

        # Описание страницы из JSON-LD WebPage
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'WebPage':
                            if 'description' in item:
                                return self.clean_text(item['description'])
            except (json.JSONDecodeError, KeyError):
                continue

        # meta description / og:description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def _extract_ingredient_from_li(self, li_elem) -> Optional[dict]:
        """
        Извлечение ингредиента из <li> элемента tasty-recipes.

        Структура: nutrifox-quantity (data-amount, data-unit) + nutrifox-unit + nutrifox-name.
        Если структурные атрибуты отсутствуют — парсит aria-label или полный текст.
        """
        # Проверяем, что это не разделитель (строка из тире/дефисов)
        full_text_raw = li_elem.get_text(strip=True)
        if re.match(r'^[-–—\s]+$', full_text_raw):
            return None

        # 1. Попытка взять структурированные nutrifox-данные
        qty_span = li_elem.find(class_='nutrifox-quantity')
        unit_span = li_elem.find(class_='nutrifox-unit')
        name_span = li_elem.find(class_='nutrifox-name')

        amount: Optional[str] = None
        unit: Optional[str] = None
        name: Optional[str] = None

        if qty_span:
            amount = qty_span.get('data-amount') or self.clean_text(qty_span.get_text())

        if unit_span:
            unit = self.clean_text(unit_span.get_text())

        if name_span:
            name = self.clean_text(name_span.get_text())

        # Если имя нашли структурно — возвращаем сразу
        if name and amount is not None:
            return {'name': name, 'amount': amount or None, 'unit': unit}

        # 2. Если структурных данных не хватает — используем aria-label
        checkbox = li_elem.find('input', {'aria-label': True})
        if checkbox:
            full_text = self.clean_text(checkbox.get('aria-label', ''))
            # Пропускаем разделители
            if full_text and not re.match(r'^[-–—\s]+$', full_text):
                parsed = self.parse_ingredient(full_text)
                if parsed:
                    # Обогащаем структурными данными, если они есть
                    if amount and not parsed.get('amount'):
                        parsed['amount'] = amount
                    if unit and not parsed.get('unit'):
                        parsed['unit'] = unit
                    return parsed

        # 3. Последний вариант — весь текст <li>
        full_text = self.clean_text(full_text_raw)
        if full_text and not full_text.endswith(':') and not re.match(r'^[-–—\s]+$', full_text):
            return self.parse_ingredient(full_text)

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из HTML (tasty-recipes) или JSON-LD"""
        ingredients = []

        # Приоритет 1 — структурированный HTML плагина Tasty Recipes
        instr_body = self.soup.find('div', class_='tasty-recipes-ingredients-body')
        if instr_body:
            for li in instr_body.find_all('li'):
                parsed = self._extract_ingredient_from_li(li)
                if parsed:
                    ingredients.append(parsed)
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        # Приоритет 2 — JSON-LD recipeIngredient
        recipe = self._get_json_ld_recipe()
        if recipe and 'recipeIngredient' in recipe:
            for raw in recipe['recipeIngredient']:
                raw = self.clean_text(str(raw))
                if re.match(r'^[-–—\s]+$', raw):
                    continue
                parsed = self.parse_ingredient(raw)
                if parsed:
                    ingredients.append(parsed)
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        # Приоритет 3 — произвольный HTML-список ингредиентов
        for container in [
            self.soup.find('ul', class_=re.compile(r'ingredient', re.I)),
            self.soup.find('div', class_=re.compile(r'ingredient', re.I)),
        ]:
            if not container:
                continue
            items = container.find_all('li') or container.find_all('p')
            for item in items:
                text = self.clean_text(item.get_text(separator=' ', strip=True))
                if text and not text.endswith(':'):
                    parsed = self.parse_ingredient(text)
                    if parsed:
                        ingredients.append(parsed)
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        return None

    def extract_steps(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        steps = []

        # Приоритет 1 — блок tasty-recipes-instructions-body (наиболее полный)
        instr_body = self.soup.find('div', class_='tasty-recipes-instructions-body')
        if instr_body:
            for item in instr_body.find_all(['li', 'p']):
                text = self.clean_text(item.get_text(separator=' ', strip=True))
                if text:
                    steps.append(text)
            if steps:
                if not re.match(r'^\d+\.', steps[0]):
                    steps = [f"{idx}. {s}" for idx, s in enumerate(steps, 1)]
                return ' '.join(steps)

        # Приоритет 2 — JSON-LD recipeInstructions
        recipe = self._get_json_ld_recipe()
        if recipe and 'recipeInstructions' in recipe:
            instructions = recipe['recipeInstructions']
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    text = None
                    if isinstance(step, dict) and 'text' in step:
                        text = self.clean_text(step['text'])
                    elif isinstance(step, str):
                        text = self.clean_text(step)
                    if text:
                        steps.append(f"{idx}. {text}")
            elif isinstance(instructions, str):
                return self.clean_text(instructions)

        if steps:
            return ' '.join(steps)

        # Приоритет 3 — HTML-контейнеры с instruction в классе
        for container in [
            self.soup.find('ol', class_=re.compile(r'instruction', re.I)),
            self.soup.find('div', class_=re.compile(r'instruction', re.I)),
        ]:
            if not container:
                continue
            step_items = container.find_all('li') or container.find_all('p')
            for item in step_items:
                text = self.clean_text(item.get_text(separator=' ', strip=True))
                if text:
                    steps.append(text)
            if steps:
                break

        if steps and not re.match(r'^\d+\.', steps[0]):
            steps = [f"{idx}. {s}" for idx, s in enumerate(steps, 1)]

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        recipe = self._get_json_ld_recipe()
        if recipe:
            category = recipe.get('recipeCategory')
            if category:
                if isinstance(category, list):
                    return self.clean_text(', '.join(str(c) for c in category))
                return self.clean_text(str(category))

        # Хлебные крошки
        breadcrumb = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumb:
            links = breadcrumb.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe = self._get_json_ld_recipe()
        if recipe and 'prepTime' in recipe:
            return self.parse_iso_duration(recipe['prepTime'])

        time_elem = self.soup.find(attrs={'itemprop': 'prepTime'})
        if time_elem:
            return self.clean_text(time_elem.get_text(strip=True))

        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe = self._get_json_ld_recipe()
        if recipe and 'cookTime' in recipe:
            return self.parse_iso_duration(recipe['cookTime'])

        time_elem = self.soup.find(attrs={'itemprop': 'cookTime'})
        if time_elem:
            return self.clean_text(time_elem.get_text(strip=True))

        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени приготовления"""
        recipe = self._get_json_ld_recipe()
        if recipe and 'totalTime' in recipe:
            return self.parse_iso_duration(recipe['totalTime'])

        time_elem = self.soup.find(attrs={'itemprop': 'totalTime'})
        if time_elem:
            return self.clean_text(time_elem.get_text(strip=True))

        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок (секция Notes / tasty-recipes-notes-body)"""
        # 1. Основной — специальный класс плагина Tasty Recipes
        notes_body = self.soup.find('div', class_='tasty-recipes-notes-body')
        if notes_body:
            text = self.clean_text(notes_body.get_text(separator=' ', strip=True))
            if text:
                return text

        # 2. Запасной — найти заголовок «Notes» и взять следующий sibling
        for heading in self.soup.find_all(['h2', 'h3', 'h4']):
            if heading.get_text(strip=True).lower() == 'notes':
                sib = heading.find_next_sibling()
                if sib:
                    text = self.clean_text(sib.get_text(separator=' ', strip=True))
                    if text:
                        return text

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords"""
        recipe = self._get_json_ld_recipe()
        tags_raw = []

        if recipe and 'keywords' in recipe:
            kw = recipe['keywords']
            if isinstance(kw, list):
                tags_raw = [str(k).strip() for k in kw if k]
            elif isinstance(kw, str):
                tags_raw = [t.strip() for t in kw.split(',') if t.strip()]

        if not tags_raw:
            return None

        # Убираем дубликаты без изменения регистра
        seen: set = set()
        unique: list = []
        for tag in tags_raw:
            key = tag.lower()
            if key not in seen:
                seen.add(key)
                unique.append(tag)

        return ', '.join(unique) if unique else None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls = []

        recipe = self._get_json_ld_recipe()
        if recipe and 'image' in recipe:
            img = recipe['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                urls.append(img.get('url') or img.get('contentUrl') or '')
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        url = item.get('url') or item.get('contentUrl')
                        if url:
                            urls.append(url)

        # Дополнительно из мета-тегов
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])

        # Убираем дубликаты и пустые строки
        if urls:
            seen: set = set()
            unique: list = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique.append(url)
            return ','.join(unique) if unique else None

        return None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта в едином формате проекта.
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception as exc:
            logger.warning("Ошибка извлечения dish_name: %s", exc)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as exc:
            logger.warning("Ошибка извлечения description: %s", exc)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as exc:
            logger.warning("Ошибка извлечения ingredients: %s", exc)
            ingredients = None

        try:
            instructions = self.extract_steps()
        except Exception as exc:
            logger.warning("Ошибка извлечения instructions: %s", exc)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as exc:
            logger.warning("Ошибка извлечения category: %s", exc)
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception as exc:
            logger.warning("Ошибка извлечения prep_time: %s", exc)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception as exc:
            logger.warning("Ошибка извлечения cook_time: %s", exc)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception as exc:
            logger.warning("Ошибка извлечения total_time: %s", exc)
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception as exc:
            logger.warning("Ошибка извлечения notes: %s", exc)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as exc:
            logger.warning("Ошибка извлечения tags: %s", exc)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as exc:
            logger.warning("Ошибка извлечения image_urls: %s", exc)
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


def main() -> None:
    """Точка входа: обработка директории preprocessed/feastingathome_com"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "feastingathome_com")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(FeastingAtHomeExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python feastingathome_com.py")


if __name__ == "__main__":
    main()
