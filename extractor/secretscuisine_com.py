"""
Экстрактор данных рецептов для сайта secretscuisine.com
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class SecretscuisineComExtractor(BaseRecipeExtractor):
    """Экстрактор для secretscuisine.com"""

    # Multi-word French units must come before single-letter units to match greedily
    _FRENCH_UNITS: List[str] = [
        r'cuillères?\s+à\s+soupe',
        r'cuillères?\s+à\s+café',
        r'c\.\s*à\s*s\.',
        r'c\.\s*à\s*c\.',
        r'tasses?',
        r'verres?',
        r'sachets?',
        r'bouquets?',
        r'branches?',
        r'feuilles?',
        r'tranches?',
        r'pincées?',
        r'gouttes?',
        r'kg',
        r'mg',
        r'ml',
        r'cl',
        r'dl',
        r'g',
        r'l',
        r'morceaux?',
        r'pièces?',
    ]

    def _get_jsonld_recipe(self) -> Optional[Dict[str, Any]]:
        """Извлечение объекта Recipe из JSON-LD"""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
            except (json.JSONDecodeError, AttributeError):
                continue

            items: List[Any] = data if isinstance(data, list) else [data]

            for item in items:
                if not isinstance(item, dict):
                    continue
                t = item.get('@type', '')
                if t == 'Recipe' or (isinstance(t, list) and 'Recipe' in t):
                    return item

            # Support @graph wrapper
            if isinstance(data, dict) and '@graph' in data:
                for item in data['@graph']:
                    if not isinstance(item, dict):
                        continue
                    t = item.get('@type', '')
                    if t == 'Recipe' or (isinstance(t, list) and 'Recipe' in t):
                        return item

        return None

    # ------------------------------------------------------------------
    # Dish name
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_og_title(raw: str) -> str:
        """
        Извлекает название блюда из og:title, убирая маркетинговые суффиксы.

        Примеры:
          «Poulet au Curry - Recette facile prête en 30 minutes - Secrets Cuisine»
            → «Poulet au Curry»
          «Pâtes tout en un tomate-basilic prêtes en 15 min - Secrets Cuisine»
            → «Pâtes tout en un tomate-basilic»
        """
        # Strip site name and everything after " - Secrets Cuisine"
        title = re.sub(r'\s+-\s+Secrets?\s*Cuisine.*$', '', raw, flags=re.IGNORECASE)
        # Strip prêtes/prêt en … suffix (pasta-style)
        title = re.sub(r'\s+prêtes?\s+en\s+.*$', '', title, flags=re.IGNORECASE)
        # Strip remaining " - …" marketing clauses (e.g. "- Recette facile")
        title = re.sub(r'\s+-\s+.*$', '', title)
        return title.strip()

    def _extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Most reliable: og:title (stripped of marketing suffixes)
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            cleaned = self._clean_og_title(og_title['content'])
            if cleaned:
                return self.clean_text(cleaned)

        # Fallback: h1.landing__title
        h1 = self.soup.find('h1', class_='landing__title')
        if h1:
            return self.clean_text(h1.get_text())

        # Fallback: h2.recipe__title inside #recipe section
        recipe_section = self.soup.find(id='recipe')
        if recipe_section:
            h2 = recipe_section.find('h2', class_='recipe__title')
            if h2:
                return self.clean_text(h2.get_text())

        logger.warning("Could not extract dish name from %s", self.html_path)
        return None

    # ------------------------------------------------------------------
    # Description
    # ------------------------------------------------------------------

    def _extract_description(self, recipe_ld: Optional[dict]) -> Optional[str]:
        """Извлечение описания рецепта"""
        # landing__tldr is a rich intro paragraph shown to visitors
        tldr = self.soup.find(class_='landing__tldr')
        if tldr:
            text = self.clean_text(tldr.get_text())
            if text:
                return text

        # First paragraph inside article.article > .article__wrapper
        article = self.soup.find('article', class_='article')
        if article:
            wrapper = article.find(class_='article__wrapper')
            if wrapper:
                first_p = wrapper.find('p')
                if first_p:
                    text = self.clean_text(first_p.get_text())
                    if text:
                        return text

        # Short description from #recipe <p> tag (= JSON-LD description)
        recipe_section = self.soup.find(id='recipe')
        if recipe_section:
            p = recipe_section.find('p')
            if p:
                text = self.clean_text(p.get_text())
                if text:
                    return text

        # JSON-LD description
        if recipe_ld and recipe_ld.get('description'):
            return self.clean_text(recipe_ld['description'])

        logger.warning("Could not extract description from %s", self.html_path)
        return None

    # ------------------------------------------------------------------
    # Ingredients
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_ingredient_name(name: str) -> str:
        """
        Очистка названия ингредиента:
        - удаление длинных поясняющих скобок (технические описания),
        - удаление инструкций нарезки после запятой,
        - нормализация регистра (строчные буквы).
        """
        # Strip long parenthetical notes (> 12 chars) such as
        # "(temps de cuisson entre 8 et 11 minutes)" or "(épaisse ou liquide, 15% ou 30%)"
        # but keep short modifiers like "(optionnel)" or "(facultatif)"
        def _maybe_strip_paren(m: re.Match) -> str:
            content = m.group(1)
            return '' if len(content) > 12 else m.group(0)

        name = re.sub(r'\s*\(([^)]*)\)', _maybe_strip_paren, name).strip()

        # Strip trailing cutting/slicing instruction after comma:
        # ", coupés en morceaux", ", en lanières", ", en fleurettes"
        name = re.sub(
            r',\s+(?:coupés?\s+en\s+\S+|en\s+\S+(?:\s+\S+)?)$',
            '',
            name,
            flags=re.IGNORECASE,
        ).strip()

        return name.lower()

    def _parse_french_ingredient(self, raw: str) -> Optional[Dict[str, Any]]:
        """
        Парсинг строки ингредиента на французском в {name, amount, unit}.

        Поддерживает шаблоны:
          «600 g d'aiguillettes de poulet»   → {amount:"600", unit:"g", name:"aiguillettes de poulet"}
          «2 cuillères à soupe de fécule»    → {amount:"2", unit:"cuillères à soupe", name:"fécule"}
          «1 oignon moyen»                   → {amount:"1", unit:"piece", name:"oignon moyen"}
          «Sel et poivre au goût»            → {amount:"au goût", unit:None, name:"sel et poivre"}
          «Sel et poivre»                    → {amount:None, unit:None, name:"sel et poivre"}
        """
        text = self.clean_text(raw)
        if not text:
            return None

        # Normalise Unicode fractions before numeric matching
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
        }
        normalized = text
        for frac, rep in fraction_map.items():
            normalized = normalized.replace(frac, rep)

        # Numeric prefix pattern: "1", "2", "1/2", "1 1/2", "0.5"
        num_pat = r'(?:(?:\d+\s+)?\d+/\d+|\d+(?:[.,]\d+)?)'

        # Article/preposition that may separate unit from ingredient name
        article_pat = r"(?:d[e']|du\s+|des\s+|de\s+la\s+|de\s+l'|de\s+)?"

        # Try each unit (multi-word first)
        for unit_re in self._FRENCH_UNITS:
            pattern = (
                r'^(' + num_pat + r')\s+'
                r'(' + unit_re + r')\s+'
                + article_pat
                + r'(.+)$'
            )
            m = re.match(pattern, normalized, re.IGNORECASE)
            if m:
                amount_str = m.group(1).strip()
                matched_unit = m.group(2).strip()
                name = self._clean_ingredient_name(m.group(3))
                return {'name': name, 'amount': amount_str, 'unit': matched_unit}

        # No recognized unit — try just number + name
        m = re.match(r'^(' + num_pat + r')\s+(.+)$', normalized)
        if m:
            amount_str = m.group(1).strip()
            name = self._clean_ingredient_name(m.group(2))
            # Infer piece unit from count
            try:
                val = float(amount_str.replace(',', '.'))
                unit: Optional[str] = 'piece' if val == 1 else 'pieces'
            except ValueError:
                unit = None
            return {'name': name, 'amount': amount_str, 'unit': unit}

        # No number — check for "X au goût" / "X à volonté" pattern
        au_gout_m = re.match(r'^(.+?)\s+(au\s+goût|à\s+volonté)$', text, re.IGNORECASE)
        if au_gout_m:
            return {
                'name': self._clean_ingredient_name(au_gout_m.group(1)),
                'amount': au_gout_m.group(2),
                'unit': None,
            }

        # Plain ingredient — no number, no amount
        return {'name': text.lower(), 'amount': None, 'unit': None}

    def _extract_ingredients(self, recipe_ld: Optional[dict]) -> Optional[str]:
        """Извлечение ингредиентов"""
        raw_texts: List[str] = []

        # Prefer HTML: structured span elements in #recipe-ingredients
        recipe_section = self.soup.find(id='recipe')
        if recipe_section:
            ing_div = recipe_section.find(id='recipe-ingredients')
            if ing_div:
                for span in ing_div.find_all('span', class_='recipe__interact-list-content'):
                    text = self.clean_text(span.get_text())
                    if text:
                        raw_texts.append(text)

        # Fallback: JSON-LD recipeIngredient
        if not raw_texts and recipe_ld:
            raw_texts = [
                t for t in recipe_ld.get('recipeIngredient', []) if isinstance(t, str)
            ]

        if not raw_texts:
            logger.warning("Could not extract ingredients from %s", self.html_path)
            return None

        ingredients = []
        for raw in raw_texts:
            parsed = self._parse_french_ingredient(raw)
            if parsed:
                ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    # ------------------------------------------------------------------
    # Instructions
    # ------------------------------------------------------------------

    def _extract_instructions(self, recipe_ld: Optional[dict]) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        steps: List[str] = []

        # Prefer HTML: p.recipe__interact-list-content inside #recipe-instructions
        recipe_section = self.soup.find(id='recipe')
        if recipe_section:
            instr_div = recipe_section.find(id='recipe-instructions')
            if instr_div:
                for p in instr_div.find_all('p', class_='recipe__interact-list-content'):
                    text = self.clean_text(p.get_text())
                    if text:
                        steps.append(text)

        # Fallback: JSON-LD recipeInstructions
        if not steps and recipe_ld:
            for step in recipe_ld.get('recipeInstructions', []):
                if isinstance(step, dict):
                    text = self.clean_text(step.get('text', ''))
                elif isinstance(step, str):
                    text = self.clean_text(step)
                else:
                    continue
                if text:
                    steps.append(text)

        if not steps:
            logger.warning("Could not extract instructions from %s", self.html_path)
            return None

        return ' '.join(steps)

    # ------------------------------------------------------------------
    # Category
    # ------------------------------------------------------------------

    def _extract_category(self, recipe_ld: Optional[dict]) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Prefer HTML: category link in #recipe-info
        recipe_section = self.soup.find(id='recipe')
        if recipe_section:
            info_div = recipe_section.find(id='recipe-info')
            if info_div:
                for a in info_div.find_all('a', href=True):
                    if '/categories/' in a.get('href', ''):
                        return self.clean_text(a.get_text())

        # Fallback: JSON-LD recipeCategory
        if recipe_ld:
            cat = recipe_ld.get('recipeCategory')
            if cat:
                return self.clean_text(str(cat))

        logger.warning("Could not extract category from %s", self.html_path)
        return None

    # ------------------------------------------------------------------
    # Times
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_time_text(text: str) -> Optional[str]:
        """
        Преобразование HTML-строки времени в «X minutes».

        Примеры: «10 min» → «10 minutes», «1 h 30 min» → «90 minutes»
        """
        text = text.strip()
        # Simple "N min"
        m = re.match(r'^(\d+)\s*min(?:utes?)?$', text, re.IGNORECASE)
        if m:
            return f"{m.group(1)} minutes"
        # "N h M min"
        m = re.match(r'^(\d+)\s*h\s*(\d+)\s*min(?:utes?)?$', text, re.IGNORECASE)
        if m:
            total = int(m.group(1)) * 60 + int(m.group(2))
            return f"{total} minutes"
        # "N h" only
        m = re.match(r'^(\d+)\s*h$', text, re.IGNORECASE)
        if m:
            return f"{int(m.group(1)) * 60} minutes"
        return text if text else None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """Конвертирует ISO 8601 duration в «X minutes»"""
        if not duration or not duration.startswith('PT'):
            return None
        body = duration[2:]
        hours_match = re.search(r'(\d+)H', body)
        mins_match = re.search(r'(\d+)M', body)
        hours = int(hours_match.group(1)) if hours_match else 0
        mins = int(mins_match.group(1)) if mins_match else 0
        total = hours * 60 + mins
        return f"{total} minutes" if total > 0 else None

    def _extract_time_from_html(self, time_type: str) -> Optional[str]:
        """Извлечение времени из блока .recipe__times в HTML"""
        label_map = {
            'prep': 'Temps de Préparation',
            'cook': 'Temps de Cuisson',
            'total': 'Temps Total',
        }
        label = label_map.get(time_type, '').lower()

        recipe_section = self.soup.find(id='recipe')
        if not recipe_section:
            return None
        times_div = recipe_section.find(class_='recipe__times')
        if not times_div:
            return None

        for item in times_div.find_all(class_='recipe__times-item'):
            strong = item.find('strong')
            if strong and label in strong.get_text().lower():
                highlight = item.find(class_='recipe__highlight')
                if highlight:
                    return self._parse_time_text(highlight.get_text().strip())
        return None

    def _extract_time(self, time_type: str, recipe_ld: Optional[dict]) -> Optional[str]:
        """Извлечение времени: HTML → JSON-LD fallback"""
        html_time = self._extract_time_from_html(time_type)
        if html_time:
            return html_time

        if recipe_ld:
            key_map = {'prep': 'prepTime', 'cook': 'cookTime', 'total': 'totalTime'}
            key = key_map.get(time_type)
            if key and key in recipe_ld:
                return self._parse_iso_duration(recipe_ld[key])
        return None

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------

    def _extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes: List[str] = []

        # Main notes list: ol#recipe-notes inside #recipe section
        recipe_section = self.soup.find(id='recipe')
        if recipe_section:
            notes_elem = recipe_section.find(id='recipe-notes')
            if notes_elem:
                for li in notes_elem.find_all('li'):
                    text = self.clean_text(li.get_text())
                    if text:
                        notes.append(text)

        if not notes:
            return None

        return ' '.join(notes)

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def _extract_tags(self, recipe_ld: Optional[dict]) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords"""
        if recipe_ld:
            keywords = recipe_ld.get('keywords')
            if keywords:
                if isinstance(keywords, str):
                    return keywords
                if isinstance(keywords, list):
                    return ', '.join(str(k) for k in keywords if k)

        # Fallback: meta keywords
        meta_kw = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_kw and meta_kw.get('content'):
            return meta_kw['content']

        return None

    # ------------------------------------------------------------------
    # Image URLs
    # ------------------------------------------------------------------

    def _extract_image_urls(self, recipe_ld: Optional[dict]) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls: List[str] = []

        # Primary: JSON-LD Recipe image field
        if recipe_ld:
            images = recipe_ld.get('image', [])
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

        # Fallback: og:image
        if not urls:
            og_img = self.soup.find('meta', property='og:image')
            if og_img and og_img.get('content'):
                urls.append(og_img['content'])

        if not urls:
            return None

        # Deduplicate, preserve order
        seen_urls: set = set()
        unique_urls: List[str] = []
        for u in urls:
            if u and u not in seen_urls:
                seen_urls.add(u)
                unique_urls.append(u)

        return ','.join(unique_urls) if unique_urls else None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта из HTML"""
        recipe_ld = self._get_jsonld_recipe()

        return {
            'dish_name': self._extract_dish_name(),
            'description': self._extract_description(recipe_ld),
            'ingredients': self._extract_ingredients(recipe_ld),
            'instructions': self._extract_instructions(recipe_ld),
            'category': self._extract_category(recipe_ld),
            'prep_time': self._extract_time('prep', recipe_ld),
            'cook_time': self._extract_time('cook', recipe_ld),
            'total_time': self._extract_time('total', recipe_ld),
            'notes': self._extract_notes(),
            'image_urls': self._extract_image_urls(recipe_ld),
            'tags': self._extract_tags(recipe_ld),
        }


def main() -> None:
    """Точка входа: обрабатывает директорию preprocessed/secretscuisine_com"""
    import os

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    preprocessed_dir = os.path.join(repo_root, 'preprocessed', 'secretscuisine_com')

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(SecretscuisineComExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python secretscuisine_com.py")


if __name__ == '__main__':
    main()
