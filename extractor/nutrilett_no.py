"""
Экстрактор данных рецептов для сайта nutrilett.no
"""

import sys
import json
import logging
import re
from pathlib import Path
from typing import Optional, Dict, Any, List

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory
from bs4 import Tag

logger = logging.getLogger(__name__)


class NutrilettNoExtractor(BaseRecipeExtractor):
    """Экстрактор для nutrilett.no"""

    def _get_json_ld_recipe(self) -> Optional[Dict[str, Any]]:
        """Извлечение данных рецепта из JSON-LD (Schema.org Recipe)"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.debug("Failed to parse JSON-LD script block")
        return None

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('name'):
            return self.clean_text(recipe['name'])

        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def _extract_notes_raw(self) -> Optional[str]:
        """Вспомогательный метод: извлечение заметок без финальной очистки"""
        rich_blocks = self.soup.find_all('div', class_='rich-text-block')
        if len(rich_blocks) < 2:
            return None

        second_block = rich_blocks[1]

        # Iterate direct children looking for <p> tags
        for child in second_block.children:
            if not isinstance(child, Tag) or child.name != 'p':
                continue
            b_tag = child.find('b')
            if b_tag:
                text = b_tag.get_text(strip=True)
                if text and len(text) > 5:
                    return text
            else:
                text = child.get_text(strip=True)
                # Skip nutritional info paragraphs
                if text and not re.match(
                    r'(Kalorier|Fiber|Proteiner|Protein|Fett|Karbohydrater|Sukker)',
                    text
                ):
                    return text.lstrip('*').strip() or None

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта (первый абзац из первого rich-text-block)"""
        rich_blocks = self.soup.find_all('div', class_='rich-text-block')
        desc_text: Optional[str] = None

        if rich_blocks:
            first_block = rich_blocks[0]
            first_p = first_block.find('p')
            if first_p:
                first_b = first_p.find('b')
                if first_b:
                    desc_text = self.clean_text(first_b.get_text())

        if not desc_text:
            # Fallback: use JSON-LD description
            recipe = self._get_json_ld_recipe()
            if recipe and recipe.get('description'):
                desc_text = self.clean_text(recipe['description'])

        if not desc_text:
            return None

        # Strip standard boilerplate suffixes (portion/calorie info and cross-links)
        desc_text = re.sub(
            r'\s*(Oppskriften holder til|Denne oppskriften holder til'
            r'|Perfekt som et|Oppskrift for \d+|Se også:).*$',
            '',
            desc_text,
            flags=re.IGNORECASE | re.DOTALL,
        )

        # If the notes text appears inside the description, strip it from that point
        notes_raw = self._extract_notes_raw()
        if notes_raw:
            prefix = notes_raw[:20] if len(notes_raw) >= 20 else notes_raw
            if prefix in desc_text:
                pos = desc_text.find(prefix)
                desc_text = desc_text[:pos].rstrip()

        desc_text = desc_text.strip()
        return desc_text if desc_text else None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок / советов к рецепту"""
        raw = self._extract_notes_raw()
        if raw:
            return self.clean_text(raw)
        return None

    # ------------------------------------------------------------------ #
    #  Ingredient parsing                                                  #
    # ------------------------------------------------------------------ #

    # Ordered list of common Norwegian measurement units (longer first to
    # avoid partial matches, e.g. "liter" before "l")
    _UNITS_RE = re.compile(
        r'^(?P<amount>[\d]+[,.]?[\d]*)\s+'
        r'(?P<unit>ss|ts|dl|ml|liter|desiliter|cl|l\b|kg|gram|g\b|stk|neve|klype|'
        r'boks|pk|pose|skiver?|fedd|kopp|glass)\s+'
        r'(?P<name>.+)$',
        re.IGNORECASE,
    )
    _NO_UNIT_RE = re.compile(
        r'^(?P<amount>[\d]+[,.]?[\d]*)\s+(?P<name>.+)$'
    )

    @staticmethod
    def _to_number(amount_str: str):
        """Конвертирует строку с числом (возможно с запятой) в int или float"""
        normalized = amount_str.replace(',', '.')
        try:
            val = float(normalized)
            return int(val) if val == int(val) else val
        except ValueError:
            return amount_str

    def _parse_ingredient(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Парсинг строки ингредиента норвежского формата «количество [единица] название».

        Примеры:
            "75 g frosne blåbær"  -> {"name": "frosne blåbær", "amount": 75, "unit": "g"}
            "1 frossen banan"     -> {"name": "frossen banan", "amount": 1,  "unit": None}
            "1,5 dl koffeinfri…"  -> {"name": "koffeinfri…",  "amount": 1.5,"unit": "dl"}
        """
        if not text:
            return None
        text = self.clean_text(text)

        m = self._UNITS_RE.match(text)
        if m:
            return {
                "name": m.group('name').strip(),
                "amount": self._to_number(m.group('amount')),
                "unit": m.group('unit'),
            }

        m = self._NO_UNIT_RE.match(text)
        if m:
            return {
                "name": m.group('name').strip(),
                "amount": self._to_number(m.group('amount')),
                "unit": None,
            }

        # Plain name without quantity
        return {"name": text, "amount": None, "unit": None}

    # ------------------------------------------------------------------ #
    #  Main extraction methods                                             #
    # ------------------------------------------------------------------ #

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов (список словарей, сериализованный в JSON-строку)"""
        ingredients: List[Dict[str, Any]] = []

        # Primary source: JSON-LD recipeIngredient
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('recipeIngredient'):
            for item in recipe['recipeIngredient']:
                parsed = self._parse_ingredient(item)
                if parsed:
                    ingredients.append(parsed)

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        # Fallback: HTML ingredient list (ul.list-decimal after h3 "Ingredienser:")
        try:
            uls = self.soup.find_all('ul', class_=lambda c: c and 'list-decimal' in c)
            for ul in uls:
                h3 = ul.find_previous_sibling('h3')
                if h3 and 'ingredienser' in h3.get_text(strip=True).lower():
                    for li in ul.find_all('li'):
                        parsed = self._parse_ingredient(li.get_text())
                        if parsed:
                            ingredients.append(parsed)
                    break
        except Exception as exc:
            logger.warning("Error extracting ingredients from HTML: %s", exc)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        steps: List[str] = []

        # Primary source: JSON-LD recipeInstructions
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('recipeInstructions'):
            for step in recipe['recipeInstructions']:
                if isinstance(step, dict) and step.get('text'):
                    steps.append(self.clean_text(step['text']))
                elif isinstance(step, str):
                    steps.append(self.clean_text(step))

        if steps:
            # Strip footnote asterisks (e.g. "Topp* med …" → "Topp med …")
            cleaned = [re.sub(r'\*+', '', s).strip() for s in steps]
            return ' '.join(s for s in cleaned if s)

        # Fallback: HTML instruction list (ul.list-decimal after h3 "Slik gjør du:")
        try:
            uls = self.soup.find_all('ul', class_=lambda c: c and 'list-decimal' in c)
            for ul in uls:
                h3 = ul.find_previous_sibling('h3')
                if h3 and 'gjør' in h3.get_text(strip=True).lower():
                    for li in ul.find_all('li'):
                        text = self.clean_text(li.get_text())
                        if text:
                            steps.append(text)
                    break
        except Exception as exc:
            logger.warning("Error extracting instructions from HTML: %s", exc)

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('recipeCategory'):
            return self.clean_text(recipe['recipeCategory'])
        return None

    @staticmethod
    def _parse_iso_duration(duration: Optional[str]) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемое время (например «45 minutes»).
        Возвращает None для пустых/отсутствующих значений.
        """
        if not duration or not duration.startswith('PT'):
            return None
        body = duration[2:]
        if not body:
            return None

        hours = 0
        minutes = 0
        h_match = re.search(r'(\d+)H', body)
        if h_match:
            hours = int(h_match.group(1))
        m_match = re.search(r'(\d+)M', body)
        if m_match:
            minutes = int(m_match.group(1))

        total = hours * 60 + minutes
        if total <= 0:
            return None
        return f"{total} minutes"

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe = self._get_json_ld_recipe()
        if recipe:
            return self._parse_iso_duration(recipe.get('prepTime'))
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe = self._get_json_ld_recipe()
        if recipe:
            return self._parse_iso_duration(recipe.get('cookTime'))
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени приготовления"""
        recipe = self._get_json_ld_recipe()
        if recipe:
            return self._parse_iso_duration(recipe.get('totalTime'))
        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords"""
        recipe = self._get_json_ld_recipe()
        if not recipe:
            return None
        keywords = recipe.get('keywords')
        if not keywords:
            return None
        if isinstance(keywords, list):
            tags = [k.strip().lower() for k in keywords if isinstance(k, str) and k.strip()]
            return ', '.join(tags) if tags else None
        if isinstance(keywords, str) and keywords.strip():
            return keywords.strip().lower()
        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls: List[str] = []

        # From JSON-LD
        recipe = self._get_json_ld_recipe()
        if recipe and recipe.get('image'):
            img = recipe['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend(i for i in img if isinstance(i, str))
            elif isinstance(img, dict):
                url = img.get('url') or img.get('contentUrl')
                if url:
                    urls.append(url)

        # From og:image meta tag
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # Deduplicate while preserving order
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
        """Извлечение всех данных рецепта"""
        try:
            dish_name = self.extract_dish_name()
        except Exception as exc:
            logger.warning("Error extracting dish_name: %s", exc)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as exc:
            logger.warning("Error extracting description: %s", exc)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as exc:
            logger.warning("Error extracting ingredients: %s", exc)
            ingredients = None

        try:
            instructions = self.extract_instructions()
        except Exception as exc:
            logger.warning("Error extracting instructions: %s", exc)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as exc:
            logger.warning("Error extracting category: %s", exc)
            category = None

        try:
            notes = self.extract_notes()
        except Exception as exc:
            logger.warning("Error extracting notes: %s", exc)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as exc:
            logger.warning("Error extracting tags: %s", exc)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as exc:
            logger.warning("Error extracting image_urls: %s", exc)
            image_urls = None

        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "image_urls": image_urls,
            "tags": tags,
        }


def main():
    import os
    recipes_dir = os.path.join("preprocessed", "nutrilett_no")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(NutrilettNoExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python nutrilett_no.py [путь_к_директории]")


if __name__ == "__main__":
    main()
