"""
Экстрактор данных рецептов для сайта putnikofer.hr
"""

import sys
from pathlib import Path
import json
import logging
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class PutnikoferHrExtractor(BaseRecipeExtractor):
    """Экстрактор для putnikofer.hr"""

    # Известные хорватские единицы измерения (в порядке убывания длины для корректного матчинга)
    _UNITS = [
        'žličice', 'žličica', 'žličicu',
        'žlice', 'žlica', 'žlicu',
        'srednje velikih', 'srednje',
        'litra', 'litre', 'litr',
        'dcl', 'dl', 'ml', 'kg', 'dkg', 'g', 'l',
        'komada', 'komad',
        'šalica', 'šalice', 'šalicu',
        'režnja', 'režanj',
    ]

    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD Schema.org"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')

        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue

                data = json.loads(script.string)

                # Данные могут быть словарём или списком
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            item_type = item.get('@type', '')
                            if (isinstance(item_type, list) and 'Recipe' in item_type) or item_type == 'Recipe':
                                return item
                elif isinstance(data, dict):
                    item_type = data.get('@type', '')
                    if (isinstance(item_type, list) and 'Recipe' in item_type) or item_type == 'Recipe':
                        return data

            except (json.JSONDecodeError, KeyError) as exc:
                logger.debug("Ошибка при разборе JSON-LD: %s", exc)
                continue

        return None

    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат.

        Args:
            duration: строка вида "PT20M" или "PT1H30M"

        Returns:
            Строка вида "20 minutes" или "1 hour 30 minutes"
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
        if total_minutes == 0:
            return None

        parts = []
        if total_minutes >= 60:
            h = total_minutes // 60
            m = total_minutes % 60
            parts.append(f"{h} hour{'s' if h > 1 else ''}")
            if m > 0:
                parts.append(f"{m} minute{'s' if m > 1 else ''}")
        else:
            parts.append(f"{total_minutes} minute{'s' if total_minutes > 1 else ''}")

        return ' '.join(parts)

    @classmethod
    def parse_ingredient(cls, text: str) -> Optional[dict]:
        """
        Разбор строки ингредиента в структурированный формат.

        Args:
            text: строка типа "500 g miješanog mljevenog mesa"

        Returns:
            Словарь {name, amount, unit} или None
        """
        text = text.strip()
        if not text:
            return None

        # Нормализуем десятичный разделитель: "0,5" → "0.5"
        normalized = text.replace(',', '.')

        # Шаблон: необязательное число (целое, дробное или дробь) + остаток строки
        number_re = re.compile(
            r'^(\d+(?:\.\d+)?(?:/\d+)?(?:-\d+(?:\.\d+)?)?)\s*(.*)',
            re.UNICODE
        )
        m = number_re.match(normalized)

        amount = None
        unit = None
        rest = text  # остаток без числа

        if m:
            raw_amount = m.group(1)
            rest = m.group(2).strip()

            # Обработка диапазонов вида "2-3": берём меньшее значение
            if '-' in raw_amount:
                raw_amount = raw_amount.split('-')[0]

            # Конвертируем в число
            try:
                if '/' in raw_amount:
                    num, denom = raw_amount.split('/')
                    amount = float(num) / float(denom)
                else:
                    amount = float(raw_amount)
                # Если дробная часть нулевая, возвращаем int
                if amount == int(amount):
                    amount = int(amount)
            except (ValueError, ZeroDivisionError):
                amount = None
                rest = text  # откатываемся

        # Поиск единицы измерения в начале rest (без учёта регистра)
        for unit_candidate in cls._UNITS:
            pattern = re.compile(
                r'^' + re.escape(unit_candidate) + r'(?:\s+|$)',
                re.IGNORECASE | re.UNICODE
            )
            um = pattern.match(rest)
            if um:
                unit = unit_candidate
                rest = rest[um.end():].strip()
                break

        # Убираем скобочные уточнения из названия (например, "(junetina ili miješano)")
        name = re.sub(r'\s*\([^)]*\)', '', rest).strip()
        # Убираем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        # Нормализуем первый символ: понижаем регистр, если он не число
        if name and name[0].isupper():
            name = name[0].lower() + name[1:]

        if not name:
            return None

        return {
            "name": name,
            "amount": amount,
            "unit": unit,
        }

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and recipe_data.get('name'):
            return self.clean_text(recipe_data['name'])

        # Запасной вариант: заголовок h1
        h1 = self.soup.find('h1', class_='heading')
        if h1:
            return self.clean_text(h1.get_text())

        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and recipe_data.get('description'):
            return self.clean_text(recipe_data['description'])

        # Запасной вариант: meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов.

        Возвращает JSON-строку со списком словарей {name, amount, unit}.
        """
        ingredients = []

        # Основной источник: JSON-LD recipeIngredient
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and recipe_data.get('recipeIngredient'):
            for item in recipe_data['recipeIngredient']:
                item_text = self.clean_text(item)
                if not item_text:
                    continue

                # Строки вида "Sol, papar, crvena paprika" без числа в начале
                # разбиваем по запятой на отдельные ингредиенты
                if not re.match(r'^\d', item_text):
                    parts = [p.strip() for p in item_text.split(',')]
                    for part in parts:
                        if part:
                            parsed = self.parse_ingredient(part)
                            if parsed:
                                ingredients.append(parsed)
                else:
                    parsed = self.parse_ingredient(item_text)
                    if parsed:
                        ingredients.append(parsed)

            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        # Запасной вариант: HTML-структура
        # 1. Новый шаблон: ul.checklist внутри блока с кнопкой id="recept"
        recept_btn = self.soup.find('button', id='recept')
        if recept_btn:
            recipe_block = recept_btn.parent
            checklist = recipe_block.find('ul', class_='checklist')
            if checklist:
                for li in checklist.find_all('li'):
                    item_text = self.clean_text(li.get_text(separator=' ', strip=True))
                    if item_text:
                        parsed = self.parse_ingredient(item_text)
                        if parsed:
                            ingredients.append(parsed)

        if not ingredients:
            # 2. Старый шаблон: ul.wp-block-list после заголовка SASTOJCI
            wysiwyg = self.soup.find('div', class_='wysiwyg-content')
            if wysiwyg:
                ing_list = wysiwyg.find('ul', class_='wp-block-list')
                if ing_list:
                    for li in ing_list.find_all('li'):
                        item_text = self.clean_text(li.get_text(separator=' ', strip=True))
                        if item_text:
                            parsed = self.parse_ingredient(item_text)
                            if parsed:
                                ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []

        # Основной источник: JSON-LD recipeInstructions
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and recipe_data.get('recipeInstructions'):
            instructions = recipe_data['recipeInstructions']
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

            if steps:
                return ' '.join(steps)

        # Запасной вариант: HTML-структура
        # 1. Новый шаблон: ol внутри блока с кнопкой id="recept"
        recept_btn = self.soup.find('button', id='recept')
        if recept_btn:
            recipe_block = recept_btn.parent
            ol = recipe_block.find('ol')
            if ol:
                for li in ol.find_all('li'):
                    text = self.clean_text(li.get_text(separator=' ', strip=True))
                    if text:
                        steps.append(text)

        if not steps:
            # 2. Старый шаблон: ul после заголовка POSTUPAK PRIPREME
            wysiwyg = self.soup.find('div', class_='wysiwyg-content')
            if wysiwyg:
                for ul in wysiwyg.find_all('ul'):
                    if ul.find_parent('ul'):
                        continue  # пропускаем вложенные списки
                    cls = ul.get('class', [])
                    if 'wp-block-list' in cls:
                        continue  # список ингредиентов, пропускаем
                    for li in ul.find_all('li', recursive=False):
                        text = self.clean_text(li.get_text(separator=' ', strip=True))
                        if text:
                            steps.append(text)

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда"""
        recipe_data = self._get_json_ld_recipe()
        if recipe_data:
            category = recipe_data.get('recipeCategory')
            if category:
                return self.clean_text(category)

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and recipe_data.get('prepTime'):
            return self.parse_iso_duration(recipe_data['prepTime'])
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and recipe_data.get('cookTime'):
            return self.parse_iso_duration(recipe_data['cookTime'])
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени приготовления"""
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and recipe_data.get('totalTime'):
            return self.parse_iso_duration(recipe_data['totalTime'])
        return None

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок / советов к рецепту.

        Стратегия:
        1. Для нового шаблона (с кнопкой #recept): ищет абзацы с явными
           указаниями на советы/вариации (prilagodbe, prilagoditi, savjet...).
        2. Для всех шаблонов: абзац непосредственно перед заголовком SASTOJCI.
        """
        # Ключевые слова, характерные для советов/примечаний к рецепту
        note_keywords = [
            'prilagodbe', 'prilagoditi',
            'nije skupi', 'nije skupo',
            'okus će biti bolji',
            'možete koristiti ono što',
            'preporučujemo',
        ]

        # Новый шаблон (с кнопкой #recept): ищем специфичные абзацы-советы
        recept_btn = self.soup.find('button', id='recept')
        if recept_btn:
            wysiwyg_blocks = self.soup.find_all('div', class_='wysiwyg-content')
            for block in wysiwyg_blocks:
                for p in block.find_all('p', recursive=True):
                    text = p.get_text(separator=' ', strip=True)
                    if not text or len(text) < 30:
                        continue
                    text_lower = text.lower()
                    if any(kw in text_lower for kw in note_keywords):
                        return self.clean_text(text)

        # Для всех шаблонов: абзац перед первым заголовком SASTOJCI / SASTOJCI:
        for heading in self.soup.find_all(['h2', 'div']):
            heading_text = heading.get_text(strip=True).upper()
            if heading_text in ('SASTOJCI', 'SASTOJCI:'):
                prev = heading.find_previous_sibling('p')
                if prev:
                    text = self.clean_text(prev.get_text(separator=' ', strip=True))
                    if text and len(text) > 30:
                        return text
                break  # берём только первый заголовок SASTOJCI

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта"""
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and recipe_data.get('keywords'):
            keywords = recipe_data['keywords']
            if isinstance(keywords, list):
                return ', '.join(self.clean_text(k) for k in keywords if k)
            if isinstance(keywords, str):
                return self.clean_text(keywords)

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls: list[str] = []

        # 1. JSON-LD Recipe image
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and recipe_data.get('image'):
            img = recipe_data['image']
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

        # 2. og:image мета-тег
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # 3. Изображения из wysiwyg-content (блоки wp-block-gallery)
        wysiwyg = self.soup.find('div', class_='wysiwyg-content')
        if wysiwyg:
            for img_tag in wysiwyg.find_all('img'):
                # Предпочитаем data-full-url (оригинальный размер)
                src = img_tag.get('data-full-url') or img_tag.get('src')
                if src and src.startswith('http'):
                    urls.append(src)

        # Удаляем дубликаты, сохраняя порядок
        seen: set[str] = set()
        unique_urls: list[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ','.join(unique_urls) if unique_urls else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта в едином формате проекта.
        """
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_steps(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags(),
        }


def main():
    """Точка входа для обработки директории с HTML-файлами putnikofer.hr"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "putnikofer_hr")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(PutnikoferHrExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python putnikofer_hr.py")


if __name__ == "__main__":
    main()
