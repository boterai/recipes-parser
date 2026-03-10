"""
Экстрактор данных рецептов для сайта petitchef.ro
"""

import sys
import json
import re
import logging
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

BASE_URL = "https://www.petitchef.ro"

# Romanian units recognized in ingredient strings
_RO_UNITS = (
    r'linguri(?:ță|te|țe)?|lingurițe|linguriță|linguri|linguriță',
    r'căni|cană|cupe?',
    r'pahare?',
    r'cutii|cutie',
    r'bucăți|bucată|buc',
    r'pungi|pungă',
    r'pachet(?:e)?',
    r'kilograme?|kg',
    r'grame?|g',
    r'mililitri|ml',
    r'litri|litru|l',
    r'fire|fir',
    r'felii|felie',
    r'buchet(?:e)?',
    r'vârfuri|vârf',
    r'praf(?:uri)?',
    r'picături|picătură',
    r'doze?|doze',
    r'maini|mână|mâini',
)
_RO_UNITS_PATTERN = '|'.join(_RO_UNITS)


class PetitchefRoExtractor(BaseRecipeExtractor):
    """Экстрактор для petitchef.ro"""

    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD"""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                # Sometimes embedded in @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('name'):
            return self.clean_text(recipe['name'])

        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта из og:title"""
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('description'):
            desc = recipe['description']
            # Remove common "Rețetă <Category> " prefix added by petitchef
            desc = re.sub(r'^Rețetă\s+\S+\s+', '', desc, flags=re.IGNORECASE).strip()
            return self.clean_text(desc) or None

        return None

    def _parse_ro_ingredient(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента (румынский формат) в структурированный словарь.

        Примеры входных строк:
          "-macaroane"               -> {"name": "macaroane", "amount": None, "unit": None}
          "-4 oua"                   -> {"name": "oua", "amount": "4", "unit": None}
          "250 ml vin rosu"          -> {"name": "vin rosu", "amount": "250", "unit": "ml"}
          "2-3 linguri faina"        -> {"name": "faina", "amount": "2-3", "unit": "linguri"}
          "o cutie foi de lasagna"   -> {"name": "foi de lasagna", "amount": "o", "unit": "cutie"}
        """
        if not text:
            return None

        text = self.clean_text(text)

        # Strip leading list markers (-, •, *, number.)
        text = re.sub(r'^[\-\*•]\s*', '', text).strip()
        text = re.sub(r'^\d+\.\s*', '', text).strip()

        if not text:
            return None

        # Replace Unicode fractions
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
        }
        for frac, repl in fraction_map.items():
            text = text.replace(frac, repl)

        # Pattern: optional_amount  optional_unit  name
        # amount: digits, ranges (2-3), fractions (1/2), decimals
        amount_pattern = r'([\d]+(?:[,./\-][\d]+)*(?:\s+[\d]+(?:[,./][\d]+)*)?)'
        # also allow word-amounts: "o", "un", "o felie de", "putin", "cateva", etc.
        word_amount_pattern = r'(o|un|niste|niște|câteva|cateva|putin|puțin|vreo|câțiva|cateva)'
        unit_pattern = r'(' + _RO_UNITS_PATTERN + r')'

        # Try: numeric_amount unit name
        m = re.match(
            r'^' + amount_pattern + r'\s+' + unit_pattern + r'\s+(.+)$',
            text, re.IGNORECASE
        )
        if m:
            return {
                "name": self.clean_text(m.group(3)),
                "amount": m.group(1).strip(),
                "unit": m.group(2).strip(),
            }

        # Try: numeric_amount name (no unit)
        m = re.match(
            r'^' + amount_pattern + r'\s+(.+)$',
            text, re.IGNORECASE
        )
        if m:
            return {
                "name": self.clean_text(m.group(2)),
                "amount": m.group(1).strip(),
                "unit": None,
            }

        # Try: word_amount unit name  e.g. "o cutie foi de lasagna"
        m = re.match(
            r'^' + word_amount_pattern + r'\s+' + unit_pattern + r'\s+(.+)$',
            text, re.IGNORECASE
        )
        if m:
            return {
                "name": self.clean_text(m.group(3)),
                "amount": m.group(1).strip(),
                "unit": m.group(2).strip(),
            }

        # Try: word_amount name  e.g. "o ceapa"
        m = re.match(
            r'^' + word_amount_pattern + r'\s+(.+)$',
            text, re.IGNORECASE
        )
        if m:
            return {
                "name": self.clean_text(m.group(2)),
                "amount": m.group(1).strip(),
                "unit": None,
            }

        # Fallback: entire text is the name
        return {
            "name": text,
            "amount": None,
            "unit": None,
        }

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD recipeIngredient"""
        recipe = self._get_recipe_json_ld()
        raw_list: list[str] = []

        if recipe and recipe.get('recipeIngredient'):
            raw_list = [str(i) for i in recipe['recipeIngredient']]

        if not raw_list:
            # Fallback: HTML ul.ingredients-ul
            for ul in self.soup.find_all('ul', class_='ingredients-ul'):
                for li in ul.find_all('li'):
                    txt = li.get_text(separator=' ', strip=True)
                    if txt:
                        raw_list.append(txt)

        if not raw_list:
            return None

        # Filter out section headers (e.g. "Sosul Ragu", "Sosul Beciamella")
        # — items that contain no digits and look like pure category labels
        # We keep them as name-only ingredients rather than discarding them.
        ingredients = []
        for raw in raw_list:
            parsed = self._parse_ro_ingredient(raw)
            if parsed:
                ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления из JSON-LD recipeInstructions"""
        recipe = self._get_recipe_json_ld()
        if not recipe:
            return self._extract_steps_from_html()

        instructions = recipe.get('recipeInstructions')
        if not instructions:
            return self._extract_steps_from_html()

        steps: list[str] = []

        if isinstance(instructions, str):
            # Single string — may contain all steps in one block
            text = self.clean_text(instructions)
            if text:
                steps.append(text)
        elif isinstance(instructions, list):
            for idx, step in enumerate(instructions, 1):
                if isinstance(step, dict) and step.get('text'):
                    step_text = self.clean_text(step['text'])
                    if step_text:
                        steps.append(f"{idx}. {step_text}")
                elif isinstance(step, str):
                    step_text = self.clean_text(step)
                    if step_text:
                        steps.append(f"{idx}. {step_text}")

        if steps:
            return ' '.join(steps)

        return self._extract_steps_from_html()

    def _extract_steps_from_html(self) -> Optional[str]:
        """Резервное извлечение шагов из HTML ul.rd-steps"""
        steps_ul = self.soup.find('ul', class_='rd-steps')
        if not steps_ul:
            return None

        steps: list[str] = []
        lis = steps_ul.find_all('li', recursive=False)
        if len(lis) > 1:
            for idx, li in enumerate(lis, 1):
                txt = self.clean_text(li.get_text(separator=' ', strip=True))
                if txt:
                    steps.append(f"{idx}. {txt}")
        else:
            for li in lis:
                txt = self.clean_text(li.get_text(separator=' ', strip=True))
                if txt:
                    steps.append(txt)

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из JSON-LD recipeCategory"""
        recipe = self._get_recipe_json_ld()
        if recipe:
            cat = recipe.get('recipeCategory')
            if cat:
                return self.clean_text(str(cat))
        return None

    def _parse_html_time(self, label_ro: str) -> Optional[str]:
        """
        Извлечение времени из HTML div.rd-times по румынскому label
        (label_ro: 'Preparare' или 'Gătire').
        """
        times_div = self.soup.find('div', class_='rd-times')
        if not times_div:
            return None

        for item in times_div.find_all('div', class_='rdt-item'):
            label_tag = item.find('i')
            if not label_tag:
                continue
            label_text = label_tag.get_text(strip=True)
            if label_text.lower() == label_ro.lower():
                # Collect text nodes that are NOT inside the <i> label
                value_parts = [
                    node for node in item.children
                    if node != label_tag and str(node).strip()
                ]
                value = ''.join(str(v) for v in value_parts).strip()
                return self.clean_text(value) or None

        return None

    def _parse_iso_duration(self, duration: str) -> Optional[str]:
        """Конвертирует ISO 8601 duration (PT1H30M) в читаемый формат"""
        if not duration or not duration.startswith('PT'):
            return None

        body = duration[2:]
        hours = 0
        minutes = 0

        h_match = re.search(r'(\d+)H', body)
        if h_match:
            hours = int(h_match.group(1))

        m_match = re.search(r'(\d+)M', body)
        if m_match:
            minutes = int(m_match.group(1))

        if hours and minutes:
            return f"{hours} hours {minutes} minutes"
        if hours:
            return f"{hours} hours"
        if minutes:
            return f"{minutes} minutes"
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки из HTML (или JSON-LD как запасной)"""
        html_time = self._parse_html_time('Preparare')
        if html_time:
            return html_time

        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('prepTime'):
            return self._parse_iso_duration(recipe['prepTime'])
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления из HTML (или JSON-LD как запасной)"""
        html_time = self._parse_html_time('Gătire')
        if html_time:
            return html_time

        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('cookTime'):
            return self._parse_iso_duration(recipe['cookTime'])
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени из JSON-LD totalTime"""
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('totalTime'):
            return self._parse_iso_duration(recipe['totalTime'])
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов к рецепту"""
        # petitchef.ro does not have a clearly delineated notes section in HTML
        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords"""
        recipe = self._get_recipe_json_ld()
        if recipe and recipe.get('keywords'):
            keywords = self.clean_text(str(recipe['keywords']))
            return keywords or None
        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из карусели и JSON-LD"""
        urls: list[str] = []
        seen: set[str] = set()

        def _add(url: str) -> None:
            url = url.strip()
            if not url or url in seen:
                return
            # Resolve relative URLs
            if url.startswith('/'):
                url = BASE_URL + url
            seen.add(url)
            urls.append(url)

        # 1. Carousel images (highest quality, recipe-specific)
        carousel = self.soup.find('div', id='rd-carousel')
        if carousel:
            for img in carousel.find_all('img'):
                src = img.get('src') or img.get('data-src') or ''
                if src and 'imgupl/recipe' in src:
                    _add(src)

        # 2. JSON-LD Recipe image
        recipe = self._get_recipe_json_ld()
        if recipe:
            img_field = recipe.get('image')
            if isinstance(img_field, str):
                _add(img_field)
            elif isinstance(img_field, list):
                for img in img_field:
                    if isinstance(img, str):
                        _add(img)
                    elif isinstance(img, dict):
                        _add(img.get('url', '') or img.get('contentUrl', ''))

        # 3. og:image as final fallback
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                _add(og_image['content'])

        return ','.join(urls) if urls else None

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
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls(),
        }


def main() -> None:
    """Точка входа для обработки директории с HTML файлами petitchef.ro"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "petitchef_ro")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(PetitchefRoExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python extractor/petitchef_ro.py")


if __name__ == "__main__":
    main()
