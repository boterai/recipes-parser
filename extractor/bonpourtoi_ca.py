"""
Экстрактор данных рецептов для сайта bonpourtoi.ca
"""

import sys
import logging
from pathlib import Path
import json
import re
from typing import Optional, Union

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class BonPourToiCaExtractor(BaseRecipeExtractor):
    """Экстрактор для bonpourtoi.ca"""

    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы (тип Recipe)"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')

        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue

                data = json.loads(script.string)

                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            item_type = item.get('@type', '')
                            if isinstance(item_type, list) and 'Recipe' in item_type:
                                return item
                            elif item_type == 'Recipe':
                                return item
                elif isinstance(data, dict):
                    item_type = data.get('@type', '')
                    if isinstance(item_type, list) and 'Recipe' in item_type:
                        return data
                    elif item_type == 'Recipe':
                        return data

            except (json.JSONDecodeError, KeyError):
                continue

        return None

    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат

        Args:
            duration: строка вида "PT20M", "PT1H30M" или "Pt4H15M"

        Returns:
            Время в формате "20 minutes", "1h30" или None
        """
        if not duration:
            return None

        # Нормализация: приводим к верхнему регистру
        duration_upper = duration.upper().strip()
        if not duration_upper.startswith('PT'):
            return None

        duration_body = duration_upper[2:]  # Убираем "PT"

        hours = 0
        minutes = 0

        hour_match = re.search(r'(\d+)H', duration_body)
        if hour_match:
            hours = int(hour_match.group(1))

        min_match = re.search(r'(\d+)M', duration_body)
        if min_match:
            minutes = int(min_match.group(1))

        if not hours and not minutes:
            return None

        # Форматируем как на сайте (h-нотация)
        if hours > 0 and minutes > 0:
            return f"{hours}h{minutes:02d}"
        elif hours > 0:
            return f"{hours}h"
        else:
            return f"{minutes} minutes"

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_data()

        if json_ld and json_ld.get('name'):
            return self.clean_text(json_ld['name'])

        # Альтернатива - из заголовка h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        # Из meta title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*[-|].*$', '', title)
            return self.clean_text(title)

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Используем og:description — краткое, стабильное
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        json_ld = self._get_json_ld_data()
        if json_ld and json_ld.get('description'):
            # Берём первое предложение/абзац
            desc = self.clean_text(json_ld['description'])
            first_para = desc.split('\n')[0]
            return first_para if first_para else None

        return None

    # ------------------------------------------------------------------
    # Ингредиенты
    # ------------------------------------------------------------------

    def _parse_qty_spans(self, spans: list) -> tuple:
        """
        Разбирает список текстов из span.qty в (amount, unit).

        Логика:
          - 3 span'а: span[0]+span[1] = дробное число, span[2] = единица
          - 2 span'а: span[0] = количество, span[1] = единица
          - 1 span: парсим строку вида "3,3 lb (1,5 kg)" → (3.3, "lb")
        """
        non_empty = [s for s in spans if s.strip()]
        if not non_empty:
            return None, None

        fraction_map = {
            '½': 0.5, '¼': 0.25, '¾': 0.75,
            '⅓': 1 / 3, '⅔': 2 / 3, '⅛': 0.125,
            '⅜': 0.375, '⅝': 0.625, '⅞': 0.875,
        }

        def _to_number(s: str) -> Optional[Union[float, int]]:
            """Конвертирует строку количества в число."""
            s = s.strip()
            # Unicode дроби
            if s in fraction_map:
                v = fraction_map[s]
                return int(v) if v == int(v) else v
            # Заменяем запятую на точку (французский формат 3,3 → 3.3)
            s_norm = s.replace(',', '.')
            try:
                v = float(s_norm)
                return int(v) if v == int(v) else v
            except ValueError:
                return None

        def _parse_combined(text: str) -> tuple:
            """Парсит строку вида '3,3 lb (1,5 kg)' → (3.3, 'lb')."""
            # Убираем содержимое в скобках
            text_clean = re.sub(r'\s*\([^)]*\)', '', text).strip()
            # Попытка разбить на число и единицу
            m = re.match(r'^([½¼¾⅓⅔⅛⅜⅝⅞\d][,./\d\s½¼¾⅓⅔⅛⅜⅝⅞]*)\s+(.+)$', text_clean)
            if m:
                raw_num, unit = m.group(1).strip(), m.group(2).strip()
                # Замена дробей
                for frac, val in fraction_map.items():
                    raw_num = raw_num.replace(frac, str(val))
                raw_num = raw_num.replace(',', '.')
                try:
                    v = float(raw_num)
                    amount = int(v) if v == int(v) else v
                    return amount, unit
                except ValueError:
                    pass
            # Нет единицы — всё строка является числом?
            num = _to_number(text_clean)
            if num is not None:
                return num, None
            # Не можем разобрать
            return None, text_clean if text_clean else None

        if len(non_empty) == 1:
            return _parse_combined(non_empty[0])

        elif len(non_empty) == 2:
            # span[0] = количество, span[1] = единица (обычно)
            amount = _to_number(non_empty[0])
            if amount is None:
                # Может быть дробь вроде "¾ tasse" — парсим вместе
                return _parse_combined(' '.join(non_empty))
            return amount, non_empty[1].strip()

        else:
            # 3+ non-empty spans: первые два — целая + дробная части, последний — единица
            whole = _to_number(non_empty[0])
            frac = _to_number(non_empty[1])
            unit = non_empty[-1].strip()
            if whole is not None and frac is not None:
                total = whole + frac
                amount = int(total) if total == int(total) else total
                return amount, unit
            elif whole is not None:
                return whole, unit
            else:
                # Всё не разобрать — объединяем в строку
                combined = ' '.join(non_empty[:-1])
                return _parse_combined(combined + ' ' + non_empty[-1])

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из HTML структуры list-item-ingredient"""
        ingredients = []

        items = self.soup.find_all('li', class_='list-item-ingredient')
        for item in items:
            try:
                content = item.find('div', class_='list-item-label-content')
                if not content:
                    continue

                name_tag = content.find('p')
                if not name_tag:
                    continue
                name = self.clean_text(name_tag.get_text())
                if not name:
                    continue

                # Предпочитаем традиционные меры (qty-trad)
                qty_div = content.find('div', class_='qty-trad')
                if not qty_div:
                    qty_div = content.find('div', class_='qty-metric')

                amount: Optional[Union[float, int, str]] = None
                unit: Optional[str] = None

                if qty_div:
                    spans = [s.get_text(strip=True) for s in qty_div.find_all('span', class_='qty')]
                    amount, unit = self._parse_qty_spans(spans)

                ingredients.append({
                    "name": name,
                    "amount": amount,
                    "unit": unit,
                })
            except Exception as e:
                logger.warning("Ошибка при разборе ингредиента: %s", e)
                continue

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        # Резервный вариант — из JSON-LD (менее структурированный)
        logger.warning("HTML ингредиенты не найдены, используем JSON-LD recipeIngredient")
        json_ld = self._get_json_ld_data()
        if json_ld and json_ld.get('recipeIngredient'):
            for raw in json_ld['recipeIngredient']:
                ingredients.append({"name": self.clean_text(raw), "amount": None, "unit": None})
            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

        return None

    # ------------------------------------------------------------------
    # Инструкции
    # ------------------------------------------------------------------

    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления из JSON-LD или HTML"""
        steps = []

        json_ld = self._get_json_ld_data()
        if json_ld and json_ld.get('recipeInstructions'):
            instructions = json_ld['recipeInstructions']

            def _collect_steps(items):
                for item in items:
                    if isinstance(item, str):
                        steps.append(item)
                    elif isinstance(item, dict):
                        itype = item.get('@type', '')
                        if itype == 'HowToStep':
                            steps.append(item.get('text', ''))
                        elif itype == 'HowToSection':
                            _collect_steps(item.get('itemListElement', []))

            if isinstance(instructions, list):
                _collect_steps(instructions)
            elif isinstance(instructions, str):
                steps.append(instructions)

            if steps:
                numbered = [f"{i}. {self.clean_text(s)}" for i, s in enumerate(steps, 1) if s]
                return ' '.join(numbered)

        # Резервный вариант — из HTML
        logger.warning("JSON-LD инструкции не найдены, ищем в HTML")
        step_items = self.soup.find_all('li', class_=re.compile(r'step|instruction', re.I))
        if not step_items:
            ol = self.soup.find('ol', class_=re.compile(r'instruction|step|preparation', re.I))
            if ol:
                step_items = ol.find_all('li')

        for item in step_items:
            text = self.clean_text(item.get_text(separator=' ', strip=True))
            if text:
                steps.append(text)

        if steps:
            if not re.match(r'^\d+\.', steps[0]):
                steps = [f"{i}. {s}" for i, s in enumerate(steps, 1)]
            return ' '.join(steps)

        return None

    # ------------------------------------------------------------------
    # Категория
    # ------------------------------------------------------------------

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из JSON-LD или HTML"""
        json_ld = self._get_json_ld_data()
        if json_ld and json_ld.get('recipeCategory'):
            return self.clean_text(str(json_ld['recipeCategory']))

        # Из HTML-блока categories
        cats_div = self.soup.find('div', class_='cats')
        if cats_div:
            cat_items = cats_div.find_all('li')
            cats = [self.clean_text(li.get_text()) for li in cat_items if li.get_text(strip=True)]
            if cats:
                return ', '.join(cats)

        return None

    # ------------------------------------------------------------------
    # Время
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_time_str(t: str) -> str:
        """Нормализует строку времени: 'min' → 'minutes'"""
        t = t.strip()
        t = re.sub(r'\bmin\b', 'minutes', t, flags=re.IGNORECASE)
        return t

    @staticmethod
    def _time_str_to_minutes(t: str) -> Optional[int]:
        """Конвертирует строку времени в минуты для сравнения."""
        t = t.strip()
        # "1h20" или "1h"
        m = re.match(r'^(\d+)h(\d+)?$', t)
        if m:
            h = int(m.group(1))
            mn = int(m.group(2)) if m.group(2) else 0
            return h * 60 + mn
        # "30 min" или "30 minutes"
        m = re.match(r'^(\d+)\s*min', t, re.I)
        if m:
            return int(m.group(1))
        return None

    @staticmethod
    def _minutes_to_time_str(total_min: int) -> str:
        """Конвертирует минуты в строку времени."""
        h, mn = divmod(total_min, 60)
        if h > 0 and mn > 0:
            return f"{h}h{mn:02d}"
        elif h > 0:
            return f"{h}h"
        else:
            return f"{total_min} minutes"

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки из HTML"""
        span = self.soup.find('span', class_='preparation-time')
        if span:
            raw = self.clean_text(span.get_text())
            return self._normalize_time_str(raw) if raw else None

        # Резервный вариант — JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and json_ld.get('prepTime'):
            return self.parse_iso_duration(json_ld['prepTime'])

        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления из HTML"""
        span = self.soup.find('span', class_='bake-time')
        if span:
            raw = self.clean_text(span.get_text())
            return self._normalize_time_str(raw) if raw else None

        # Резервный вариант — JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and json_ld.get('cookTime'):
            return self.parse_iso_duration(json_ld['cookTime'])

        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени.

        Предпочитает JSON-LD, но проверяет разумность значения:
        если JSON-LD total меньше суммы prep+cook, пересчитывает.
        """
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()

        computed_min: Optional[int] = None
        if prep and cook:
            p_min = self._time_str_to_minutes(prep)
            c_min = self._time_str_to_minutes(cook)
            if p_min is not None and c_min is not None:
                computed_min = p_min + c_min

        json_ld = self._get_json_ld_data()
        if json_ld and json_ld.get('totalTime'):
            iso_total = self.parse_iso_duration(json_ld['totalTime'])
            if iso_total:
                iso_min = self._time_str_to_minutes(iso_total)
                # Используем JSON-LD только если оно >= computed (разумно)
                if computed_min is None or (iso_min is not None and iso_min >= computed_min):
                    return iso_total
                # Иначе, JSON-LD total, скорее всего, содержит ошибку — считаем сами

        if computed_min is not None:
            return self._minutes_to_time_str(computed_min)

        return None

    # ------------------------------------------------------------------
    # Заметки
    # ------------------------------------------------------------------

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок из блока 'Bon à savoir' (section-tip)"""
        section_tip = self.soup.find('div', class_='section-tip')
        if section_tip:
            tip_text_div = section_tip.find('div', class_='tip-text')
            if tip_text_div:
                text = self.clean_text(tip_text_div.get_text(separator=' ', strip=True))
                return text if text else None

        return None

    # ------------------------------------------------------------------
    # Теги
    # ------------------------------------------------------------------

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords"""
        json_ld = self._get_json_ld_data()
        if json_ld and json_ld.get('keywords'):
            keywords = json_ld['keywords']
            if isinstance(keywords, list):
                tags = [self.clean_text(k) for k in keywords if k]
            else:
                # Строка, разделённая запятыми
                tags = [self.clean_text(k) for k in str(keywords).split(',') if k.strip()]
            # Убираем финальные точки
            tags = [re.sub(r'\.$', '', t).strip() for t in tags if t]
            tags = [t for t in tags if t]
            if tags:
                return ', '.join(tags)

        return None

    # ------------------------------------------------------------------
    # Изображения
    # ------------------------------------------------------------------

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из JSON-LD и мета-тегов"""
        urls = []

        # 1. Из JSON-LD image
        json_ld = self._get_json_ld_data()
        if json_ld and json_ld.get('image'):
            images = json_ld['image']
            if isinstance(images, str):
                urls.append(images)
            elif isinstance(images, list):
                for img in images:
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, dict):
                        url = img.get('url') or img.get('contentUrl')
                        if url:
                            urls.append(url)
            elif isinstance(images, dict):
                url = images.get('url') or images.get('contentUrl')
                if url:
                    urls.append(url)

        # 2. Из мета-тегов (если JSON-LD не дал результата)
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])

        # Убираем дубликаты
        seen: set = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ','.join(unique_urls) if unique_urls else None

    # ------------------------------------------------------------------
    # Главный метод
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception as e:
            logger.error("Ошибка извлечения dish_name: %s", e)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as e:
            logger.error("Ошибка извлечения description: %s", e)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as e:
            logger.error("Ошибка извлечения ingredients: %s", e)
            ingredients = None

        try:
            instructions = self.extract_instructions()
        except Exception as e:
            logger.error("Ошибка извлечения instructions: %s", e)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as e:
            logger.error("Ошибка извлечения category: %s", e)
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception as e:
            logger.error("Ошибка извлечения prep_time: %s", e)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception as e:
            logger.error("Ошибка извлечения cook_time: %s", e)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception as e:
            logger.error("Ошибка извлечения total_time: %s", e)
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception as e:
            logger.error("Ошибка извлечения notes: %s", e)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as e:
            logger.error("Ошибка извлечения tags: %s", e)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as e:
            logger.error("Ошибка извлечения image_urls: %s", e)
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
            "tags": tags,
            "image_urls": image_urls,
        }


def main():
    import os
    recipes_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "preprocessed",
        "bonpourtoi_ca",
    )
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(BonPourToiCaExtractor, recipes_dir)
        return

    print(f"Директория не найдена: {recipes_dir}")


if __name__ == "__main__":
    main()
