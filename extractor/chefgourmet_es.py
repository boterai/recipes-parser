"""
Экстрактор данных рецептов для сайта chefgourmet.es
"""

import copy
import sys
import json
import re
import logging
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class ChefGourmetEsExtractor(BaseRecipeExtractor):
    """Экстрактор для chefgourmet.es"""

    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD"""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
            except (json.JSONDecodeError, KeyError):
                continue
        return None

    @staticmethod
    def _format_duration(iso_duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в формат "X mins" / "X h Y mins"

        Args:
            iso_duration: строка вида "PT0H5M" или "PT1H35M"

        Returns:
            Строка вида "5 mins", "1 h 35 mins" или None при нулевом времени
        """
        if not iso_duration or not iso_duration.startswith('PT'):
            return None

        duration = iso_duration[2:]  # убираем "PT"

        hours = 0
        minutes = 0

        hour_match = re.search(r'(\d+)H', duration)
        if hour_match:
            hours = int(hour_match.group(1))

        min_match = re.search(r'(\d+)M', duration)
        if min_match:
            minutes = int(min_match.group(1))

        if hours == 0 and minutes == 0:
            return None

        parts = []
        if hours > 0:
            parts.append(f"{hours} h")
        if minutes > 0:
            parts.append(f"{minutes} mins")

        return ' '.join(parts)

    @staticmethod
    def _shorten_title(title: str) -> str:
        """Возвращает часть заголовка до двоеточия (если оно есть)"""
        if ':' in title:
            return title.split(':')[0].strip()
        return title

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # JSON-LD name — наиболее надёжный источник
        json_ld = self._get_json_ld_recipe()
        if json_ld and json_ld.get('name'):
            return self.clean_text(self._shorten_title(json_ld['name']))

        # Первый h2.dr-title — главный заголовок рецепта
        title_elem = self.soup.find('h2', class_='dr-title')
        if title_elem:
            return self.clean_text(self._shorten_title(title_elem.get_text()))

        # og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*-\s*www\.chefgourmet\.es.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(self._shorten_title(title))

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем <p> внутри div.dr-summary
        summary = self.soup.find(class_='dr-summary')
        if summary:
            p = summary.find('p')
            if p:
                return self.clean_text(p.get_text())

        # Запасной вариант — JSON-LD description
        json_ld = self._get_json_ld_recipe()
        if json_ld and json_ld.get('description'):
            return self.clean_text(json_ld['description'])

        # meta description
        meta = self.soup.find('meta', {'name': 'description'})
        if meta and meta.get('content'):
            return self.clean_text(meta['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []

        ingr_list = self.soup.find(class_='dr-ingredients-list')
        if ingr_list:
            for li in ingr_list.find_all('li'):
                qty_span = li.find('span', class_='ingredient_quantity')
                unit_span = li.find('span', class_='ingredient_unit')

                amount_raw = qty_span.get_text(strip=True) if qty_span else None
                unit_raw = unit_span.get_text(strip=True) if unit_span else None

                # Парсим количество в число
                amount = None
                if amount_raw:
                    try:
                        val = float(amount_raw.replace(',', '.'))
                        amount = int(val) if val.is_integer() else val
                    except ValueError:
                        amount = amount_raw

                # Пустая единица → None
                units = unit_raw if unit_raw else None

                # Название: текст li без span-элементов
                li_copy = copy.copy(li)
                for span in li_copy.find_all('span'):
                    span.decompose()
                name = self.clean_text(li_copy.get_text())

                if name:
                    ingredients.append({
                        "name": name,
                        "units": units,
                        "amount": amount,
                    })

            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        # Запасной вариант — JSON-LD recipeIngredient
        json_ld = self._get_json_ld_recipe()
        if json_ld and json_ld.get('recipeIngredient'):
            for ing_text in json_ld['recipeIngredient']:
                parsed = self._parse_jsonld_ingredient(ing_text)
                if parsed:
                    ingredients.append(parsed)
            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

        return None

    def _parse_jsonld_ingredient(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента из JSON-LD формата:
        "<amount> <unit> <name>" или "<amount>  <name>" (двойной пробел = нет единицы)
        """
        if not text:
            return None

        text = self.clean_text(text)

        # Паттерн: число, затем двойной пробел (нет единицы) или один пробел + слово-единица
        m = re.match(r'^(\d+(?:[.,]\d+)?)\s{2,}(.+)$', text)
        if m:
            amount_str, name = m.group(1), m.group(2)
            try:
                val = float(amount_str.replace(',', '.'))
                amount = int(val) if val.is_integer() else val
            except ValueError:
                amount = amount_str
            return {"name": self.clean_text(name), "units": None, "amount": amount}

        m = re.match(r'^(\d+(?:[.,]\d+)?)\s+(\S+)\s+(.+)$', text)
        if m:
            amount_str, unit, name = m.group(1), m.group(2), m.group(3)
            try:
                val = float(amount_str.replace(',', '.'))
                amount = int(val) if val.is_integer() else val
            except ValueError:
                amount = amount_str
            return {"name": self.clean_text(name), "units": unit, "amount": amount}

        return {"name": text, "units": None, "amount": None}

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []

        # Ищем div.dr-instruction внутри dr-instructions
        inst_section = self.soup.find(class_='dr-instructions')
        if inst_section:
            for div in inst_section.find_all('div', class_='dr-instruction'):
                text = self.clean_text(div.get_text())
                if text:
                    steps.append(text)

        if not steps:
            # Запасной вариант — JSON-LD recipeInstructions
            json_ld = self._get_json_ld_recipe()
            if json_ld and json_ld.get('recipeInstructions'):
                for step in json_ld['recipeInstructions']:
                    if isinstance(step, dict):
                        text = self.clean_text(step.get('text', ''))
                    else:
                        text = self.clean_text(str(step))
                    if text:
                        steps.append(text)

        if not steps:
            return None

        # Определяем, нужна ли нумерация: если большинство шагов содержат "ЗаголовокШага: текст"
        named_pattern = re.compile(r'^[A-ZÁÉÍÓÚÜÑ][^:]{1,40}:\s')
        named_count = sum(1 for s in steps if named_pattern.match(s))
        has_named_steps = named_count > len(steps) / 2

        if has_named_steps:
            numbered = []
            idx = 1
            for step in steps:
                # Удаляем префикс "ЗаголовокШага: "
                stripped = re.sub(r'^[^:]{1,40}:\s*', '', step)
                numbered.append(f"{idx}. {stripped}")
                idx += 1
            return ' '.join(numbered)

        return ' '.join(steps)

    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        json_ld = self._get_json_ld_recipe()
        if json_ld:
            category = json_ld.get('recipeCategory')
            if category:
                if isinstance(category, list):
                    return ', '.join(category)
                return self.clean_text(str(category))

        # Из HTML элемента dr-category
        cat_elem = self.soup.find(class_='dr-category')
        if cat_elem:
            text = cat_elem.get_text(strip=True)
            # Убираем метку "Receta:"
            text = re.sub(r'^Receta:\s*', '', text)
            return self.clean_text(text) or None

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self._get_json_ld_recipe()
        if json_ld and json_ld.get('prepTime'):
            return self._format_duration(json_ld['prepTime'])

        # HTML fallback
        elem = self.soup.find(class_='dr-prep-time')
        if elem:
            title = elem.find(class_='dr-meta-title')
            if title:
                title.decompose()
            return self.clean_text(elem.get_text()) or None

        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_recipe()
        if json_ld and json_ld.get('cookTime'):
            return self._format_duration(json_ld['cookTime'])
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_recipe()
        if json_ld and json_ld.get('totalTime'):
            return self._format_duration(json_ld['totalTime'])

        # HTML fallback
        elem = self.soup.find(class_='dr-total-time')
        if elem:
            title = elem.find(class_='dr-meta-title')
            if title:
                title.decompose()
            return self.clean_text(elem.get_text()) or None

        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок из секции dr-note"""
        note_section = self.soup.find(class_='dr-note')
        if note_section:
            p = note_section.find('p')
            if p:
                return self.clean_text(p.get_text()) or None
            # Убираем заголовок "Notas" и возвращаем остаток
            text = note_section.get_text(separator=' ', strip=True)
            text = re.sub(r'^Notas\s*', '', text)
            return self.clean_text(text) or None
        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из div.dr-keywords или JSON-LD keywords"""
        keywords_elem = self.soup.find(class_='dr-keywords')
        if keywords_elem:
            text = keywords_elem.get_text(strip=True)
            # Убираем метку "Palabras clave:"
            text = re.sub(r'^Palabras clave:\s*', '', text)
            return self.clean_text(text) or None

        # Запасной вариант — JSON-LD keywords
        json_ld = self._get_json_ld_recipe()
        if json_ld and json_ld.get('keywords'):
            return self.clean_text(json_ld['keywords'])

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls = []

        json_ld = self._get_json_ld_recipe()
        if json_ld and json_ld.get('image'):
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        url = item.get('url') or item.get('contentUrl')
                        if url:
                            urls.append(url)
            elif isinstance(img, dict):
                url = img.get('url') or img.get('contentUrl')
                if url:
                    urls.append(url)

        # og:image как запасной вариант
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # Убираем дубликаты
        seen: set = set()
        unique: list = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта

        Returns:
            Словарь с данными рецепта
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
    """Точка входа для обработки директории с HTML файлами"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "chefgourmet_es")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ChefGourmetEsExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python chefgourmet_es.py")


if __name__ == "__main__":
    main()
