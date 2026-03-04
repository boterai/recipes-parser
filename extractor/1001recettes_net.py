"""
Экстрактор данных рецептов для сайта 1001recettes.net
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


class Recettes1001Extractor(BaseRecipeExtractor):
    """Экстрактор для 1001recettes.net"""

    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в строку вида 'N minutes'

        Args:
            duration: строка вида "PT20M" или "PT1H30M"

        Returns:
            Время в формате "N minutes"
        """
        if not duration or not duration.startswith('PT'):
            return None

        remainder = duration[2:]  # Убираем "PT"
        hours = 0
        minutes = 0

        hour_match = re.search(r'(\d+)H', remainder)
        if hour_match:
            hours = int(hour_match.group(1))

        min_match = re.search(r'(\d+)M', remainder)
        if min_match:
            minutes = int(min_match.group(1))

        total_minutes = hours * 60 + minutes
        return f"{total_minutes} minutes" if total_minutes > 0 else None

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('name'):
            return self.clean_text(recipe['name'])

        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('description'):
            return self.clean_text(recipe['description'])

        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из структурированного HTML"""
        ingredients = []

        ingr_container = self.soup.find('div', class_='liste-ingredient')
        if ingr_container:
            for item in ingr_container.find_all('div', class_='ingredient'):
                label = item.find('label')
                if not label:
                    continue

                amount_el = label.find('span', class_='chiffre-ingredient')
                unit_el = label.find('strong')

                amount_raw = self.clean_text(amount_el.get_text()) if amount_el else None
                unit = self.clean_text(unit_el.get_text()) if unit_el else None

                # Текст после unit_el — это название ингредиента (после "de ")
                name_text = None
                if unit_el:
                    # Берём текстовые узлы после strong
                    parts = []
                    for node in unit_el.next_siblings:
                        text = node.string if hasattr(node, 'string') else str(node)
                        if text:
                            parts.append(text)
                    name_text = ' '.join(parts).strip()
                    # Убираем начальный предлог "de "
                    name_text = re.sub(r'^de\s+', '', name_text, flags=re.IGNORECASE)
                    name_text = self.clean_text(name_text)
                elif amount_el:
                    # Без unit: берём всё после amount
                    parts = []
                    for node in amount_el.next_siblings:
                        text = node.string if hasattr(node, 'string') else str(node)
                        if text:
                            parts.append(text)
                    name_text = ' '.join(parts).strip()
                    name_text = re.sub(r'^de\s+', '', name_text, flags=re.IGNORECASE)
                    name_text = self.clean_text(name_text)
                else:
                    name_text = self.clean_text(label.get_text())

                if not name_text:
                    continue

                # Нормализуем количество
                amount = None
                if amount_raw:
                    try:
                        amount = int(amount_raw) if '.' not in amount_raw else float(amount_raw)
                    except ValueError:
                        amount = amount_raw

                ingredients.append({
                    "name": name_text,
                    "units": unit,
                    "amount": amount
                })

            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        # Запасной вариант — из JSON-LD recipeIngredient
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('recipeIngredient'):
            for raw in recipe['recipeIngredient']:
                raw = self.clean_text(raw)
                if raw:
                    ingredients.append({"name": raw, "units": None, "amount": None})
            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

        return None

    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('recipeInstructions'):
            steps = []
            for idx, step in enumerate(recipe['recipeInstructions'], 1):
                if isinstance(step, dict):
                    text = self.clean_text(step.get('text', ''))
                elif isinstance(step, str):
                    text = self.clean_text(step)
                else:
                    continue
                if text:
                    steps.append(f"Étape {idx}: {text}")
            if steps:
                return ' '.join(steps)

        # Запасной вариант — из HTML
        steps = []
        content_area = self.soup.find('div', class_=re.compile(r'entry-content|post-content', re.I))
        if content_area:
            step_headers = content_area.find_all('h3', class_='wp-block-heading')
            for h in step_headers:
                label = self.clean_text(h.get_text())
                p = h.find_next_sibling('p')
                if p:
                    text = self.clean_text(p.get_text())
                    if text:
                        steps.append(f"{label}: {text}")

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда"""
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])

        breadcrumb = self.soup.find(class_=re.compile(r'breadcrumb', re.I))
        if breadcrumb:
            links = breadcrumb.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())

        return None

    @staticmethod
    def _extract_time_from_div(div) -> Optional[str]:
        """Извлечение текста времени из div с несколькими тегами p"""
        if not div:
            return None
        for p in div.find_all('p'):
            text = p.get_text(strip=True)
            if text:
                return text
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        prep_el = self.soup.find('div', class_='info-temps')
        text = self._extract_time_from_div(prep_el)
        if text:
            return self.clean_text(text)

        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('prepTime'):
            return self._parse_iso_duration(recipe['prepTime'])

        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        cook_el = self.soup.find('div', class_='info-temps-cuisson')
        text = self._extract_time_from_div(cook_el)
        if text:
            return self.clean_text(text)

        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('cookTime'):
            return self._parse_iso_duration(recipe['cookTime'])

        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени приготовления"""
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('totalTime'):
            return self._parse_iso_duration(recipe['totalTime'])

        # Вычисляем сумму prep_time + cook_time
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()

        def _to_minutes(time_str: Optional[str]) -> Optional[int]:
            if not time_str:
                return None
            m = re.search(r'(\d+)', time_str)
            return int(m.group(1)) if m else None

        prep_min = _to_minutes(prep)
        cook_min = _to_minutes(cook)

        if prep_min is not None and cook_min is not None:
            return f"{prep_min + cook_min} minutes"

        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов шефа"""
        astuce = self.soup.find('div', class_='astuce')
        if astuce:
            text = astuce.get_text(separator=' ', strip=True)
            # Убираем заголовок "Mon astuce de chef"
            text = re.sub(r"^Mon astuce de chef\s*", '', text, flags=re.IGNORECASE)
            text = self.clean_text(text)
            return text if text else None

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта"""
        # Из ссылок с rel=tag
        tag_links = self.soup.find_all('a', rel='tag')
        if tag_links:
            tags = [self.clean_text(t.get_text()) for t in tag_links if t.get_text(strip=True)]
            tags = [t for t in tags if t]
            if tags:
                return ', '.join(tags)

        # Из классов основного элемента article (tag-xxx)
        article = self.soup.find('article')
        if article:
            class_list = article.get('class', [])
            tags = []
            for cls in class_list:
                if cls.startswith('tag-'):
                    tag = cls[4:].replace('-', ' ')
                    tags.append(tag)
            if tags:
                return ', '.join(tags)

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls = []

        recipe = self._get_json_ld_recipe()
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

        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # Дедупликация
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return ','.join(unique_urls) if unique_urls else None

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
    import os
    recipes_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "preprocessed",
        "1001recettes_net"
    )
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(Recettes1001Extractor, recipes_dir)
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python 1001recettes_net.py")


if __name__ == "__main__":
    main()
