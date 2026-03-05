"""
Экстрактор данных рецептов для сайта repassansgluten.com
Сайт использует плагин Tasty Recipes (WordPress) с JSON-LD разметкой.
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class RepassansGlutenExtractor(BaseRecipeExtractor):
    """Экстрактор для repassansgluten.com"""

    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение данных JSON-LD типа Recipe из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                # Прямой объект Recipe
                if isinstance(data, dict):
                    if data.get('@type') == 'Recipe':
                        return data
                    # @graph может содержать Recipe
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and item.get('@type') == 'Recipe':
                                return item
                # Список объектов
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
            except (json.JSONDecodeError, KeyError):
                continue
        return None

    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат.
        Возвращает None для некорректных (отрицательных) значений.

        Args:
            duration: строка вида "PT20M" или "PT1H30M"

        Returns:
            Строка вида "20 minutes" или "1 hour 30 minutes", либо None
        """
        if not duration or not duration.startswith('PT'):
            return None
        # Пропускаем отрицательные значения (баг сайта)
        if 'PT-' in duration or duration.startswith('PT-'):
            return None

        duration_body = duration[2:]  # убираем "PT"

        hours = 0
        minutes = 0

        hour_match = re.search(r'(\d+)H', duration_body)
        if hour_match:
            hours = int(hour_match.group(1))

        min_match = re.search(r'(\d+)M', duration_body)
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

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Tasty Recipes плагин: заголовок рецепта
        title_elem = self.soup.find(class_='tasty-recipes-title')
        if title_elem:
            return self.clean_text(title_elem.get_text())

        # Главный h1 страницы
        h1 = self.soup.find('h1')
        if h1:
            text = self.clean_text(h1.get_text())
            if text:
                return text

        # Из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and recipe_data.get('name'):
            return self.clean_text(recipe_data['name'])

        # Из мета-тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Tasty Recipes: тело описания
        desc_body = self.soup.find(class_='tasty-recipes-description-body')
        if desc_body:
            return self.clean_text(desc_body.get_text())

        # Из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and recipe_data.get('description'):
            return self.clean_text(recipe_data['description'])

        # Из мета description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        return None

    def _parse_ingredient_para(self, para) -> Optional[dict]:
        """
        Парсинг одного параграфа ингредиента из блока Tasty Recipes.

        Структура HTML:
          <p>
            <span data-amount="500" [data-unit="ml"]>500 [ml]</span>
            [единица измерения] [предлог] название
          </p>

        Returns:
            dict {"name": str, "amount": int|float|str|None, "unit": str|None}
        """
        span = para.find('span', attrs={'data-amount': True})
        if not span:
            text = self.clean_text(para.get_text())
            if text:
                return {"name": text, "amount": None, "unit": None}
            return None

        amount_str = (span.get('data-amount') or '').strip()
        unit = (span.get('data-unit') or '').strip() or None

        # Преобразуем количество в число
        amount: Optional[object] = None
        if amount_str:
            try:
                amount = int(amount_str) if amount_str.isdigit() else float(amount_str)
            except (ValueError, TypeError):
                amount = amount_str

        # Собираем оставшийся текст (текстовые узлы и inline-теги после span)
        remaining_parts = []
        for sibling in span.next_siblings:
            if isinstance(sibling, str):
                remaining_parts.append(sibling)
            elif hasattr(sibling, 'name') and sibling.name in ('strong', 'em', 'b', 'i', 'a'):
                remaining_parts.append(sibling.get_text())
            # Пропускаем div/ins/script (рекламные блоки)

        remaining = ' '.join(remaining_parts).strip()

        if not unit and remaining:
            # Единицу не нашли в data-unit — пробуем извлечь из начала оставшегося текста
            unit_match = re.match(
                r'^(ml|cl|dl|l|g|kg|mg|tasse[s]?|c\.\s*à\s*soupe|c\.\s*à\s*thé|tbsp|tsp|cup[s]?)\b',
                remaining, re.IGNORECASE
            )
            if unit_match:
                unit = unit_match.group(1)
                remaining = remaining[unit_match.end():].strip()
        elif unit and remaining:
            # Удаляем единицу из начала remaining, если она там повторяется
            remaining = re.sub(
                r'^' + re.escape(unit) + r'\s*',
                '',
                remaining,
                flags=re.IGNORECASE
            ).strip()

        # Удаляем примечания в скобках: "(2 tasses)", "(env. 3)", "(l'Hirondelle ou Rapunzel)"
        remaining = re.sub(r'\([^)]*\)', '', remaining).strip()

        # Удаляем французские предлоги в начале: "de", "d'", "du", "des", "l'"
        remaining = re.sub(
            r"^(de\s+|d['\u2019]|du\s+|des\s+|l['\u2019])",
            '',
            remaining,
            flags=re.IGNORECASE
        ).strip()

        name = self.clean_text(remaining)
        if not name:
            return None

        return {"name": name, "amount": amount, "unit": unit}

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из блока Tasty Recipes"""
        ingr_div = self.soup.find(class_='tasty-recipes-ingredients')
        if not ingr_div:
            return None

        # Ищем тело блока ингредиентов
        body_div = ingr_div.find('div', attrs={'data-tasty-recipes-customization': True})
        if not body_div:
            body_div = ingr_div

        ingredients = []
        for p in body_div.find_all('p'):
            parsed = self._parse_ingredient_para(p)
            if parsed:
                ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instr_div = self.soup.find(class_='tasty-recipes-instructions')
        if instr_div:
            body_div = instr_div.find('div', attrs={'data-tasty-recipes-customization': True})
            if not body_div:
                body_div = instr_div

            steps = []
            for p in body_div.find_all('p'):
                text = self.clean_text(p.get_text())
                if text:
                    steps.append(text)

            if steps:
                return ' '.join(steps)

        # Запасной вариант: JSON-LD (первый шаг обычно чистый, остальные могут содержать мусор)
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            steps = []
            for idx, step in enumerate(instructions, 1):
                if isinstance(step, dict) and 'text' in step:
                    text = self.clean_text(step['text'])
                    if text:
                        steps.append(f"{idx}. {text}")
                elif isinstance(step, str):
                    text = self.clean_text(step)
                    if text:
                        steps.append(f"{idx}. {text}")
            if steps:
                return ' '.join(steps)

        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда"""
        # Tasty Recipes: поле категории
        cat_elem = self.soup.find(class_='tasty-recipes-category')
        if cat_elem:
            return self.clean_text(cat_elem.get_text())

        # Из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and recipe_data.get('recipeCategory'):
            cat = recipe_data['recipeCategory']
            if isinstance(cat, list):
                return ', '.join(cat)
            return self.clean_text(str(cat))

        return None

    def _extract_time_from_html(self, css_class: str) -> Optional[str]:
        """Извлечение времени напрямую из HTML-элемента Tasty Recipes"""
        elem = self.soup.find(class_=css_class)
        if elem:
            text = self.clean_text(elem.get_text())
            return text if text else None
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and recipe_data.get('prepTime'):
            result = self.parse_iso_duration(recipe_data['prepTime'])
            if result:
                return result

        # Запасной вариант: HTML-элемент
        return self._extract_time_from_html('tasty-recipes-prep-time')

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and recipe_data.get('cookTime'):
            result = self.parse_iso_duration(recipe_data['cookTime'])
            if result:
                return result

        return self._extract_time_from_html('tasty-recipes-cook-time')

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and recipe_data.get('totalTime'):
            result = self.parse_iso_duration(recipe_data['totalTime'])
            if result:
                return result
            # Если JSON-LD содержит отрицательное значение (баг сайта) — не fallback на HTML

        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов к рецепту"""
        notes_body = self.soup.find(class_='tasty-recipes-notes-body')
        if notes_body:
            paragraphs = []
            for p in notes_body.find_all('p'):
                text = self.clean_text(p.get_text())
                if text:
                    paragraphs.append(text)
            if paragraphs:
                return ' '.join(paragraphs)

        # Если нет отдельного body, берём весь блок заметок (без заголовка)
        notes_div = self.soup.find(class_='tasty-recipes-notes')
        if notes_div:
            # Убираем заголовок h3
            for h in notes_div.find_all(['h2', 'h3', 'h4']):
                h.decompose()
            text = self.clean_text(notes_div.get_text())
            return text if text else None

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта"""
        # JSON-LD keywords
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and recipe_data.get('keywords'):
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                tags = [t.strip() for t in keywords.split(',') if t.strip()]
                return ', '.join(tags) if tags else None
            if isinstance(keywords, list):
                return ', '.join(str(k).strip() for k in keywords if k)

        # WordPress post tags (rel="tag")
        tag_links = self.soup.find_all('a', rel='tag')
        if tag_links:
            tags = [self.clean_text(a.get_text()) for a in tag_links]
            tags = [t for t in tags if t]
            return ', '.join(tags) if tags else None

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls = []

        # JSON-LD: поле image в Recipe
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
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
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])

        if not urls:
            return None

        # Убираем дубликаты, сохраняя порядок
        seen: set = set()
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
            Словарь с данными рецепта в стандартном формате проекта.
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
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls(),
        }


def main():
    """Точка входа для обработки директории с HTML-страницами"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "repassansgluten_com")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(RepassansGlutenExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python repassansgluten_com.py")


if __name__ == "__main__":
    main()
