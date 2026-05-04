"""
Экстрактор данных рецептов для сайта diyetz.com
Сайт построен на WordPress + WP Recipe Maker (WPRM).
Основной источник данных — HTML-элементы WPRM, JSON-LD используется как резервный источник.
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


class DiyetzComExtractor(BaseRecipeExtractor):
    """Экстрактор для diyetz.com (WordPress + WP Recipe Maker)"""

    # ------------------------------------------------------------------ #
    # Вспомогательные методы                                               #
    # ------------------------------------------------------------------ #

    def _get_wprm_block(self):
        """
        Возвращает основной WPRM-блок рецепта (div.wprm-recipe-template-tarif-ablonu).
        Если он не найден, пробует любой достаточно большой WPRM-блок.
        """
        for div in self.soup.find_all('div'):
            cls = div.get('class', [])
            if 'wprm-recipe' in cls and 'wprm-recipe-template-tarif-ablonu' in cls:
                return div
        # Fallback: любой div с классом wprm-recipe
        for div in self.soup.find_all('div'):
            cls = div.get('class', [])
            if 'wprm-recipe' in cls and len(str(div)) > 3000:
                return div
        return None

    def _get_recipe_json_ld(self) -> Optional[dict]:
        """
        Возвращает словарь типа Recipe из JSON-LD (первый найденный).
        Поддерживает формат { @graph: [...] } и прямой объект.
        """
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
            except json.JSONDecodeError:
                continue

            # Формат { @graph: [...] }
            if isinstance(data, dict) and '@graph' in data:
                for node in data['@graph']:
                    if isinstance(node, dict) and node.get('@type') == 'Recipe':
                        return node

            # Прямой объект
            if isinstance(data, dict):
                item_type = data.get('@type', '')
                if item_type == 'Recipe' or (isinstance(item_type, list) and 'Recipe' in item_type):
                    return data

            # Список объектов
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get('@type', '')
                    if item_type == 'Recipe' or (isinstance(item_type, list) and 'Recipe' in item_type):
                        return item

        return None

    @staticmethod
    def _parse_iso_duration(duration: Optional[str]) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в строку вида «X minutes» / «X hours» / «X days».

        Args:
            duration: строка вида «PT20M», «PT1H30M», «P3DT2H»

        Returns:
            Строка вида «10 minutes», «2 hours», «3 days» или None
        """
        if not duration:
            return None

        # Поддерживаем форматы P...T... и PT...
        body = duration.upper()
        if body.startswith('P'):
            body = body[1:]  # убираем «P»

        days = 0
        hours = 0
        minutes = 0

        # Дни перед «T»
        day_match = re.search(r'(\d+)D', body)
        if day_match:
            days = int(day_match.group(1))

        # Часы и минуты после «T»
        t_idx = body.find('T')
        if t_idx != -1:
            after_t = body[t_idx + 1:]
            hour_match = re.search(r'(\d+)H', after_t)
            if hour_match:
                hours = int(hour_match.group(1))
            min_match = re.search(r'(\d+)M', after_t)
            if min_match:
                minutes = int(min_match.group(1))
        else:
            # Нет разделителя T — пробуем извлечь H и M напрямую
            hour_match = re.search(r'(\d+)H', body)
            if hour_match:
                hours = int(hour_match.group(1))
            min_match = re.search(r'(\d+)M', body)
            if min_match:
                minutes = int(min_match.group(1))

        total_minutes = days * 24 * 60 + hours * 60 + minutes

        if total_minutes == 0:
            return None

        def _plural(n: int, word: str) -> str:
            return f"{n} {word}{'s' if n != 1 else ''}"

        if total_minutes < 60:
            return _plural(total_minutes, 'minute')
        elif total_minutes < 1440:
            return _plural(round(total_minutes / 60), 'hour')
        else:
            return _plural(round(total_minutes / 1440), 'day')

    # ------------------------------------------------------------------ #
    # Методы извлечения полей                                              #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из WPRM h2 или JSON-LD."""
        wprm = self._get_wprm_block()
        if wprm:
            name_h2 = wprm.find('h2', class_=lambda c: c and 'wprm-recipe-name' in c)
            if name_h2:
                # Удаляем вложенные span из ez-toc
                for span in name_h2.find_all('span', class_=lambda c: c and 'ez-toc-section' in c):
                    span.decompose()
                text = self.clean_text(name_h2.get_text(separator=' ', strip=True))
                if text:
                    return text

        # Резервный источник — JSON-LD
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('name'):
            return self.clean_text(recipe['name'])

        # og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания из WPRM summary или JSON-LD."""
        wprm = self._get_wprm_block()
        if wprm:
            summary = wprm.find('div', class_=lambda c: c and 'wprm-recipe-summary' in c)
            if summary:
                text = self.clean_text(summary.get_text(separator=' ', strip=True))
                if text:
                    return text

        # Резервный источник — JSON-LD
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('description'):
            return self.clean_text(recipe['description'])

        # meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из WPRM li.wprm-recipe-ingredient.
        Каждый ингредиент разбивается на поля name / amount / unit.
        """
        wprm = self._get_wprm_block()
        ingredients = []

        if wprm:
            ing_items = wprm.find_all('li', class_=lambda c: c and 'wprm-recipe-ingredient' in c)
            for item in ing_items:
                amount_span = item.find('span', class_=lambda c: c and 'wprm-recipe-ingredient-amount' in c)
                unit_span = item.find('span', class_=lambda c: c and 'wprm-recipe-ingredient-unit' in c)
                name_span = item.find('span', class_=lambda c: c and 'wprm-recipe-ingredient-name' in c)

                amount = self.clean_text(amount_span.get_text(strip=True)) if amount_span else None
                unit = self.clean_text(unit_span.get_text(strip=True)) if unit_span else None
                name = self.clean_text(name_span.get_text(strip=True)) if name_span else None

                # Нормализуем пустые строки до None
                amount = amount or None
                unit = unit or None
                name = name or None

                # Пропускаем полностью пустые элементы
                if not name and not amount:
                    continue

                ingredients.append({
                    "name": name,
                    "amount": amount,
                    "unit": unit,
                })

        # Резервный источник — JSON-LD recipeIngredient (список строк)
        if not ingredients:
            recipe = self._get_recipe_json_ld()
            if recipe and recipe.get('recipeIngredient'):
                for ing_str in recipe['recipeIngredient']:
                    parsed = self._parse_ingredient_string(str(ing_str))
                    if parsed:
                        ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def _parse_ingredient_string(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента «1 cup flour» в {'name': ..., 'amount': ..., 'unit': ...}.
        """
        text = self.clean_text(text)
        if not text:
            return None

        # Заменяем Unicode-дроби
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
        }
        for fr, dec in fraction_map.items():
            text = text.replace(fr, dec)

        # Пробуем выделить количество в начале
        amount_match = re.match(r'^([\d/.,]+)\s*(.+)$', text)
        if amount_match:
            amount_str = amount_match.group(1).strip()
            rest = amount_match.group(2).strip()
            return {
                "name": rest,
                "amount": amount_str if amount_str else None,
                "unit": None,
            }

        return {"name": text, "amount": None, "unit": None}

    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления из WPRM или JSON-LD."""
        steps = []

        wprm = self._get_wprm_block()
        if wprm:
            inst_container = wprm.find('div', class_=lambda c: c and 'wprm-recipe-instructions-container' in c)
            if inst_container:
                step_items = inst_container.find_all('li', class_=lambda c: c and 'wprm-recipe-instruction' in c)
                for idx, item in enumerate(step_items, 1):
                    text_div = item.find('div', class_=lambda c: c and 'wprm-recipe-instruction-text' in c)
                    text = self.clean_text(
                        (text_div or item).get_text(separator=' ', strip=True)
                    )
                    if text:
                        steps.append(f"{idx}. {text}")

        # Резервный источник — JSON-LD recipeInstructions
        if not steps:
            recipe = self._get_recipe_json_ld()
            if recipe and recipe.get('recipeInstructions'):
                instructions = recipe['recipeInstructions']
                if isinstance(instructions, list):
                    for idx, step in enumerate(instructions, 1):
                        if isinstance(step, dict):
                            text = self.clean_text(step.get('text', '') or step.get('name', ''))
                        else:
                            text = self.clean_text(str(step))
                        if text:
                            steps.append(f"{idx}. {text}")
                elif isinstance(instructions, str):
                    return self.clean_text(instructions)

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из WPRM span.wprm-recipe-course."""
        wprm = self._get_wprm_block()
        if wprm:
            # Точный поиск по списку классов, исключаем wprm-recipe-course-label
            course_span = None
            for span in wprm.find_all('span'):
                cls_list = span.get('class', [])
                if 'wprm-recipe-course' in cls_list and 'wprm-recipe-course-label' not in cls_list:
                    course_span = span
                    break
            if course_span:
                text = self.clean_text(course_span.get_text(strip=True))
                if text:
                    return text

        # Резервный источник — JSON-LD recipeCategory
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('recipeCategory'):
            cat = recipe['recipeCategory']
            if isinstance(cat, list) and cat:
                return self.clean_text(cat[0])
            if isinstance(cat, str):
                return self.clean_text(cat)

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки из JSON-LD."""
        recipe = self._get_recipe_json_ld()
        if recipe:
            prep = recipe.get('prepTime')
            if prep:
                result = self._parse_iso_duration(prep)
                if result:
                    return result

        # Резервный источник — WPRM HTML
        return self._extract_wprm_time('prep')

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления из JSON-LD."""
        recipe = self._get_recipe_json_ld()
        if recipe:
            cook = recipe.get('cookTime')
            if cook:
                result = self._parse_iso_duration(cook)
                if result:
                    return result

        return self._extract_wprm_time('cook')

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени из JSON-LD."""
        recipe = self._get_recipe_json_ld()
        if recipe:
            total = recipe.get('totalTime')
            if total:
                result = self._parse_iso_duration(total)
                if result:
                    return result

        return self._extract_wprm_time('total')

    def _extract_wprm_time(self, time_type: str) -> Optional[str]:
        """
        Резервное извлечение времени из WPRM HTML-контейнера.
        Использует имена классов (hours/minutes/days) для определения единиц.
        """
        from bs4 import NavigableString, Tag

        wprm = self._get_wprm_block()
        if not wprm:
            return None

        container = None
        for div in wprm.find_all('div'):
            cls_list = div.get('class', [])
            if f'wprm-recipe-{time_type}-time-container' in cls_list:
                container = div
                break
        if not container:
            return None

        # Ищем span с классом wprm-recipe-{type}_time (без unit и label)
        detail_spans = []
        for span in container.find_all('span'):
            cls_list = span.get('class', [])
            cls_str = ' '.join(cls_list)
            prefix = f'wprm-recipe-{time_type}_time'
            if prefix in cls_str and 'unit' not in cls_str and 'label' not in cls_str:
                detail_spans.append(span)

        parts = []
        for span in detail_spans:
            # Определяем единицу из имени класса
            cls_str = ' '.join(span.get('class', []))
            if 'days' in cls_str:
                unit = 'days'
            elif 'hours' in cls_str:
                unit = 'hours'
            elif 'minutes' in cls_str:
                unit = 'minutes'
            else:
                unit = ''

            # Извлекаем число, пропуская sr-only вложенные spans
            text_parts = []
            for child in span.children:
                if isinstance(child, NavigableString):
                    text_parts.append(str(child))
                elif isinstance(child, Tag):
                    child_cls = child.get('class', [])
                    if 'sr-only' not in child_cls:
                        text_parts.append(child.get_text())
            value = ''.join(text_parts).strip()

            if value and unit:
                parts.append(f"{value} {unit}")

        return ' '.join(parts) if parts else None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок из WPRM div.wprm-recipe-notes."""
        wprm = self._get_wprm_block()
        if not wprm:
            return None

        notes_container = wprm.find(
            'div',
            class_=lambda c: c and 'wprm-recipe-notes-container' in c
        )
        if not notes_container:
            return None

        # Ищем внутренний div с классом wprm-recipe-notes
        notes_inner = notes_container.find(
            'div',
            class_=lambda c: c and 'wprm-recipe-notes' in c
        )
        target = notes_inner if notes_inner else notes_container

        # Сначала пробуем li-элементы
        lis = target.find_all('li')
        if lis:
            texts = [self.clean_text(li.get_text(separator=' ', strip=True)) for li in lis]
            texts = [t for t in texts if t]
            if texts:
                return ' '.join(texts)

        # Затем параграфы
        ps = target.find_all('p')
        if ps:
            texts = [self.clean_text(p.get_text(separator=' ', strip=True)) for p in ps]
            texts = [t for t in texts if t]
            if texts:
                return ' '.join(texts)

        # Последний вариант — весь текст блока (убираем заголовок)
        # Убираем заголовок h3
        h3 = notes_container.find('h3')
        if h3:
            h3.extract()

        text = self.clean_text(notes_container.get_text(separator=' ', strip=True))
        return text if text else None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из WPRM span.wprm-recipe-keyword или JSON-LD keywords."""
        wprm = self._get_wprm_block()
        if wprm:
            # Точное совпадение: ищем span с классом wprm-recipe-keyword, но не wprm-recipe-keyword-label
            kw_span = None
            for span in wprm.find_all('span'):
                cls_list = span.get('class', [])
                if 'wprm-recipe-keyword' in cls_list and 'wprm-recipe-keyword-label' not in cls_list:
                    kw_span = span
                    break
            if kw_span:
                raw = kw_span.get_text(strip=True)
                if raw:
                    # Нормализуем арабскую запятую «،» в латинскую «,»
                    normalized = raw.replace('،', ',')
                    parts = [p.strip() for p in normalized.split(',') if p.strip()]
                    return ', '.join(parts) if parts else None

        # Резервный источник — JSON-LD keywords
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('keywords'):
            raw = recipe['keywords']
            if isinstance(raw, list):
                return ', '.join([self.clean_text(k) for k in raw if k])
            if isinstance(raw, str):
                normalized = raw.replace('،', ',')
                parts = [p.strip() for p in normalized.split(',') if p.strip()]
                return ', '.join(parts) if parts else None

        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Извлечение URL изображений из og:image, JSON-LD и WPRM image.
        Предпочитает оригинальные размеры (без суффиксов -300x200 и т.п.).
        """
        urls = []

        # 1. og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # 2. JSON-LD image
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('image'):
            img = recipe['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                url = img.get('url') or img.get('contentUrl')
                if url:
                    urls.append(url)

        # 3. WPRM recipe image (из srcset берём оригинал — наибольший)
        wprm = self._get_wprm_block()
        if wprm:
            wprm_img_div = wprm.find('div', class_=lambda c: c and 'wprm-recipe-image' in c)
            if wprm_img_div:
                img_tag = wprm_img_div.find('img')
                if img_tag:
                    srcset = img_tag.get('srcset', '')
                    if srcset:
                        # Берём URL с максимальной шириной
                        best_url = None
                        best_width = 0
                        for part in srcset.split(','):
                            part = part.strip()
                            tokens = part.split()
                            if len(tokens) >= 2:
                                url_part = tokens[0]
                                descriptor = tokens[1]
                                if descriptor.endswith('w'):
                                    try:
                                        width = int(descriptor[:-1])
                                        if width > best_width:
                                            best_width = width
                                            best_url = url_part
                                    except ValueError:
                                        pass
                                # Пропускаем дескрипторы x (плотность пикселей)
                            elif len(tokens) == 1:
                                best_url = tokens[0]
                        if best_url:
                            urls.append(best_url)
                    elif img_tag.get('src'):
                        urls.append(img_tag['src'])

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
        Извлечение всех данных рецепта.

        Returns:
            Словарь со всеми полями рецепта.
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception as e:
            logger.warning(f"Error extracting dish_name: {e}")
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as e:
            logger.warning(f"Error extracting description: {e}")
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as e:
            logger.warning(f"Error extracting ingredients: {e}")
            ingredients = None

        try:
            instructions = self.extract_instructions()
        except Exception as e:
            logger.warning(f"Error extracting instructions: {e}")
            instructions = None

        try:
            category = self.extract_category()
        except Exception as e:
            logger.warning(f"Error extracting category: {e}")
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception as e:
            logger.warning(f"Error extracting prep_time: {e}")
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception as e:
            logger.warning(f"Error extracting cook_time: {e}")
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception as e:
            logger.warning(f"Error extracting total_time: {e}")
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception as e:
            logger.warning(f"Error extracting notes: {e}")
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as e:
            logger.warning(f"Error extracting tags: {e}")
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as e:
            logger.warning(f"Error extracting image_urls: {e}")
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
    import os
    base_dir = Path(__file__).parent.parent
    recipes_dir = base_dir / "preprocessed" / "diyetz_com"
    if recipes_dir.exists() and recipes_dir.is_dir():
        process_directory(DiyetzComExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python diyetz_com.py [путь_к_директории]")


if __name__ == "__main__":
    main()
