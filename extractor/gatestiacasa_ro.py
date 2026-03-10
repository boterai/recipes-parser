"""
Экстрактор данных рецептов для сайта gatestiacasa.ro
"""

import sys
import logging
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Known Romanian measurement units (lowercase for matching)
ROMANIAN_UNITS = {
    'g', 'gr', 'grame', 'gram',
    'kg', 'kilograme', 'kilogram',
    'ml', 'mililitri', 'mililitru',
    'l', 'litru', 'litri',
    'linguri', 'lingura', 'linguriță', 'lingurițe', 'lingurita', 'lingurițe',
    'cana', 'căni', 'cani', 'ceasca', 'cești',
    'bucăți', 'bucata', 'bucăți', 'buc', 'bucati', 'bucata',
    'felii', 'felie',
    'căței', 'catei', 'caței',
    'pachet', 'pachete',
    'conserve', 'cutie', 'cutii',
    'varf', 'vârf',
}

# Category slug to readable name mapping, ordered by specificity
CATEGORY_MAP = {
    'retete-supe-ciorbe-supe': 'Soup',
    'retete-salate': 'Salate',
    'retete-garnituri': 'Garnituri',
    'deserturi': 'Dessert',
    'retete-deserturi': 'Dessert',
    'retete-aperitive': 'Aperitive',
    'retete-gustari': 'Gustari',
    'retete-mic-dejun': 'Mic Dejun',
    'retete-vegetariene': 'Vegetarian',
    'retete-carne-pasare': 'Carne Pasare',
    'retete-carne-porc': 'Carne Porc',
    'retete-carne-vita': 'Carne Vita',
    'retete-peste': 'Peste',
    'retete-bucataria-italiana': 'Italia',
    'retete-bucataria-franceza': 'Franta',
    'retete-bucataria-germana': 'Germania',
    'retete-bucataria-indiana': 'India',
    'retete-bucataria-mexicana': 'Mexican',
    'retete-bucataria-spaniola': 'Spania',
    'retete-asiatice': 'Asiatic',
    'bucatarie-romaneasca': 'Bucatarie Romaneasca',
    'bucatarie-americana': 'Bucatarie Americana',
    'masa-de-craciun': 'Masa de Craciun',
    'masa-de-paste': 'Masa de Paste',
    'retete-cina': 'Main Course',
    'retete-pranz': 'Main Course',
}

# Priority order: more specific food-type categories come first,
# then meal-time categories (cina/pranz → Main Course), then cuisine/origin
CATEGORY_PRIORITY = [
    'retete-supe-ciorbe-supe',
    'retete-salate',
    'retete-garnituri',
    'deserturi',
    'retete-deserturi',
    'retete-aperitive',
    'retete-gustari',
    'retete-mic-dejun',
    'retete-cina',
    'retete-pranz',
    'retete-vegetariene',
    'retete-carne-pasare',
    'retete-carne-porc',
    'retete-carne-vita',
    'retete-peste',
    'retete-bucataria-italiana',
    'retete-bucataria-franceza',
    'retete-bucataria-germana',
    'retete-bucataria-indiana',
    'retete-bucataria-mexicana',
    'retete-bucataria-spaniola',
    'retete-asiatice',
    'bucatarie-romaneasca',
    'bucatarie-americana',
    'masa-de-craciun',
    'masa-de-paste',
]


class GatestiacasaRoExtractor(BaseRecipeExtractor):
    """Экстрактор для gatestiacasa.ro"""

    def _get_main_post_classes(self) -> list:
        """Извлекает список CSS-классов главного div поста."""
        main_div = self.soup.find('div', class_=re.compile(r'post-\d+.*type-post'))
        if main_div:
            return main_div.get('class', [])
        return []

    def _find_section_content(self, keyword: str) -> list:
        """
        Находит все элементы ul/ol/p после H2, содержащего keyword,
        до следующего H2/hr.
        """
        h2s = self.soup.find_all('h2')
        for h2 in h2s:
            text = h2.get_text(strip=True).upper()
            if keyword.upper() in text:
                elements = []
                next_el = h2.find_next_sibling()
                while next_el:
                    if next_el.name == 'h2':
                        break
                    elements.append(next_el)
                    next_el = next_el.find_next_sibling()
                return elements
        return []

    def _parse_time_str(self, time_str: str) -> Optional[str]:
        """
        Конвертирует строку времени из Romanian ("30 min", "3 ore", "1 oră 30 min")
        в формат "X minutes" / "X hours" / "X hours Y minutes".

        Args:
            time_str: строка вида "30 min", "3 ore", "1 oră 30 min"

        Returns:
            Форматированная строка времени или None
        """
        if not time_str:
            return None

        time_str = time_str.strip()

        hours = 0
        minutes = 0

        # Match hours: "3 ore", "1 oră", "2 ore"
        ore_match = re.search(r'(\d+)\s*or[eă]', time_str, re.IGNORECASE)
        if ore_match:
            hours = int(ore_match.group(1))

        # Match minutes: "30 min", "25 min"
        min_match = re.search(r'(\d+)\s*min', time_str, re.IGNORECASE)
        if min_match:
            minutes = int(min_match.group(1))

        if hours == 0 and minutes == 0:
            return None

        if hours > 0 and minutes > 0:
            hour_word = "hour" if hours == 1 else "hours"
            return f"{hours} {hour_word} {minutes} minutes"
        elif hours > 0:
            hour_word = "hour" if hours == 1 else "hours"
            return f"{hours} {hour_word}"
        else:
            return f"{minutes} minutes"

    def _time_to_minutes(self, time_str: str) -> int:
        """Конвертирует строку времени в минуты для вычисления общего времени."""
        if not time_str:
            return 0
        hours = 0
        minutes = 0
        ore_match = re.search(r'(\d+)\s*or[eă]', time_str, re.IGNORECASE)
        if ore_match:
            hours = int(ore_match.group(1))
        min_match = re.search(r'(\d+)\s*min', time_str, re.IGNORECASE)
        if min_match:
            minutes = int(min_match.group(1))
        return hours * 60 + minutes

    def _minutes_to_str(self, total_minutes: int) -> Optional[str]:
        """Конвертирует минуты в читаемую строку."""
        if total_minutes <= 0:
            return None
        if total_minutes < 60:
            return f"{total_minutes} minutes"
        hours = total_minutes // 60
        mins = total_minutes % 60
        hour_word = "hour" if hours == 1 else "hours"
        if mins > 0:
            return f"{hours} {hour_word} {mins} minutes"
        return f"{hours} {hour_word}"

    def extract_dish_name(self) -> Optional[str]:
        """
        Извлечение названия блюда.
        Сначала пробуем og:title (с очисткой суффикса), затем H1.
        """
        try:
            # og:title often has full name like "Lasagna Italiană - Rețetă Tradițională..."
            og_title = self.soup.find('meta', property='og:title')
            if og_title and og_title.get('content'):
                title = og_title['content']
                # Strip common suffixes separated by " - " or ":"
                title = re.split(r'\s*[-–:]\s+(?:Rețetă|Reteta|Recipe)', title, maxsplit=1)[0]
                title = self.clean_text(title)
                if title:
                    return title

            # Fallback to H1
            h1 = self.soup.find('h1')
            if h1:
                return self.clean_text(h1.get_text())
        except Exception as e:
            logger.warning(f"Error extracting dish name: {e}")
        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта из meta description."""
        try:
            # Try og:description first
            og_desc = self.soup.find('meta', property='og:description')
            if og_desc and og_desc.get('content'):
                return self.clean_text(og_desc['content'])

            # Fallback to meta name="description"
            meta_desc = self.soup.find('meta', {'name': 'description'})
            if meta_desc and meta_desc.get('content'):
                return self.clean_text(meta_desc['content'])
        except Exception as e:
            logger.warning(f"Error extracting description: {e}")
        return None

    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат.

        Поддерживаемые форматы:
        - "Morcovi – 6 bucăți"        (name – amount unit)
        - "400g de carne de vită"     (amountunit de name)
        - "2 linguri de ulei"          (amount unit de name)
        - "500 g mazăre"               (amount unit name)
        - "1 ceapă mare"               (amount name)
        - "sare și piper după gust"   (name după gust)

        Returns:
            dict: {"name": ..., "amount": ..., "unit": ...} или None
        """
        if not ingredient_text:
            return None

        text = self.clean_text(ingredient_text)
        if not text:
            return None

        # Remove parenthetical notes (e.g., "(pre-coapte sau nu, ...)", "(mărime medie)")
        # but only when they appear at the end and after ingredient quantity/name
        text_no_paren = re.sub(r'\s*\([^)]*\)\s*$', '', text).strip()
        if text_no_paren:
            text = text_no_paren

        # Format: "Name – Amount Unit" (e.g., "Morcovi – 6 bucăți")
        dash_match = re.match(r'^(.+?)\s*[–-]\s*(\d+[\d./,]*)\s+(.*?)$', text)
        if dash_match:
            name, amount, unit = dash_match.groups()
            return {
                "name": name.strip(),
                "amount": amount.strip(),
                "unit": unit.strip() if unit.strip() else None
            }

        # Format: "name, după gust" or "name după gust"
        gust_match = re.match(r'^(.+?),?\s+după\s+gust.*$', text, re.IGNORECASE)
        if gust_match:
            name = gust_match.group(1).strip()
            return {"name": name, "amount": "după gust", "unit": None}

        # Format: "Nunit de name" (e.g., "400g de carne de vită")
        no_space_match = re.match(r'^(\d+[\d./,]*)([a-zăîșțâ]{1,5})\s+de\s+(.+)$', text, re.IGNORECASE)
        if no_space_match:
            amount, unit, name = no_space_match.groups()
            return {
                "name": name.strip(),
                "amount": amount.strip(),
                "unit": unit.strip()
            }

        # Format: "N unit de name" (e.g., "2 linguri de ulei de măsline")
        unit_de_match = re.match(r'^(\d+[\d./,\s]*)\s+([\wăîșțâ]+)\s+de\s+(.+)$', text, re.IGNORECASE)
        if unit_de_match:
            amount, unit, name = unit_de_match.groups()
            amount = amount.strip()
            unit_lower = unit.strip().lower()
            name = name.strip()
            if unit_lower in ROMANIAN_UNITS:
                return {"name": name, "amount": amount, "unit": unit.strip()}
            # If not a known unit, treat word as part of name
            return {"name": f"{unit} de {name}", "amount": amount, "unit": None}

        # Format: "N unit name" (e.g., "500 g mazăre", "2 linguri ulei")
        unit_name_match = re.match(r'^(\d+[\d./,\s]*)\s+([\wăîșțâ]{1,15})\s+(.+)$', text, re.IGNORECASE)
        if unit_name_match:
            amount, unit, name = unit_name_match.groups()
            if unit.strip().lower() in ROMANIAN_UNITS:
                return {
                    "name": name.strip(),
                    "amount": amount.strip(),
                    "unit": unit.strip()
                }

        # Format: "N name" (e.g., "1 ceapă mare", "12 foi de lasagna")
        num_name_match = re.match(r'^(\d+[\d./,]*)\s+(.+)$', text)
        if num_name_match:
            amount, name = num_name_match.groups()
            return {"name": name.strip(), "amount": amount.strip(), "unit": None}

        # Fallback: whole string as name
        return {"name": text, "amount": None, "unit": None}

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из секции под H2 'INGREDIENTELE'.
        Возвращает JSON-строку со списком ингредиентов.
        """
        try:
            ingredients = []
            elements = self._find_section_content('INGREDIENT')
            if not elements:
                logger.warning("No ingredients section found")
                return None

            for el in elements:
                if el.name == 'ul':
                    for li in el.find_all('li'):
                        item_text = self.clean_text(li.get_text(separator=' ', strip=True))
                        if item_text:
                            parsed = self.parse_ingredient(item_text)
                            if parsed:
                                ingredients.append(parsed)

            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
        except Exception as e:
            logger.warning(f"Error extracting ingredients: {e}")
            return None

    def extract_steps(self) -> Optional[str]:
        """
        Извлечение инструкций из секции под H2 'METODA DE PREPARARE' или 'PREPARARE'.
        Возвращает все шаги как одну строку.
        """
        try:
            steps = []
            elements = self._find_section_content('PREPARARE')
            if not elements:
                logger.warning("No preparation section found")
                return None

            for el in elements:
                if el.name == 'ul':
                    for li in el.find_all('li'):
                        step_text = self.clean_text(li.get_text(separator=' ', strip=True))
                        if step_text:
                            steps.append(step_text)
                elif el.name == 'p':
                    p_text = self.clean_text(el.get_text(strip=True))
                    # Skip section subheadings (short strings often ending with ":")
                    if p_text and not p_text.endswith(':') and len(p_text) > 20:
                        steps.append(p_text)

            return ' '.join(steps) if steps else None
        except Exception as e:
            logger.warning(f"Error extracting steps: {e}")
            return None

    def _get_time_paragraph(self) -> Optional[str]:
        """Возвращает текст абзаца с временными данными рецепта."""
        for strong in self.soup.find_all('strong'):
            text = strong.get_text(strip=True)
            if 'Timp de' in text:
                p = strong.parent
                if p:
                    return p.get_text(strip=True)
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки."""
        try:
            para = self._get_time_paragraph()
            if para:
                match = re.search(r'Timp de pregătire:\s*([^|]+)', para, re.IGNORECASE)
                if match:
                    return self._parse_time_str(match.group(1).strip())
        except Exception as e:
            logger.warning(f"Error extracting prep time: {e}")
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки."""
        try:
            para = self._get_time_paragraph()
            if para:
                match = re.search(r'Timp de gătire:\s*([^|]+)', para, re.IGNORECASE)
                if match:
                    return self._parse_time_str(match.group(1).strip())
        except Exception as e:
            logger.warning(f"Error extracting cook time: {e}")
        return None

    def extract_total_time(self) -> Optional[str]:
        """Вычисление общего времени (prep + cook)."""
        try:
            para = self._get_time_paragraph()
            if para:
                prep_str = None
                cook_str = None
                prep_match = re.search(r'Timp de pregătire:\s*([^|]+)', para, re.IGNORECASE)
                if prep_match:
                    prep_str = prep_match.group(1).strip()
                cook_match = re.search(r'Timp de gătire:\s*([^|]+)', para, re.IGNORECASE)
                if cook_match:
                    cook_str = cook_match.group(1).strip()

                total_mins = self._time_to_minutes(prep_str) + self._time_to_minutes(cook_str)
                return self._minutes_to_str(total_mins)
        except Exception as e:
            logger.warning(f"Error extracting total time: {e}")
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок из секции 'SUGESTII SI RECOMANDARI'."""
        try:
            elements = self._find_section_content('SUGESTII')
            if not elements:
                return None

            notes_parts = []
            for el in elements:
                # Stop before nutritional information section
                el_text_upper = el.get_text(strip=True).upper()
                if 'NUTRITIONAL' in el_text_upper or ('INFORMATII' in el_text_upper and 'PENTRU' in el_text_upper):
                    break
                if el.name in ('ul', 'ol'):
                    for li in el.find_all('li'):
                        note_text = self.clean_text(li.get_text(separator=' ', strip=True))
                        if note_text:
                            notes_parts.append(note_text)
                elif el.name == 'p':
                    p_text = self.clean_text(el.get_text(strip=True))
                    if p_text and len(p_text) > 10:
                        notes_parts.append(p_text)

            return ' '.join(notes_parts) if notes_parts else None
        except Exception as e:
            logger.warning(f"Error extracting notes: {e}")
            return None

    def extract_category(self) -> Optional[str]:
        """
        Извлечение категории из CSS-классов главного поста.
        Использует таблицу приоритетов для выбора наиболее подходящей категории.
        """
        try:
            classes = self._get_main_post_classes()
            cat_slugs = [c.replace('category-', '') for c in classes if c.startswith('category-')]

            for priority_slug in CATEGORY_PRIORITY:
                if priority_slug in cat_slugs:
                    return CATEGORY_MAP.get(priority_slug)

            # Fallback: use first category class
            if cat_slugs:
                slug = cat_slugs[0]
                return CATEGORY_MAP.get(slug, slug.replace('-', ' ').title())
        except Exception as e:
            logger.warning(f"Error extracting category: {e}")
        return None

    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов из CSS-классов tag-* главного поста.
        """
        try:
            classes = self._get_main_post_classes()
            tags = [
                c.replace('tag-', '').replace('-', ' ')
                for c in classes
                if c.startswith('tag-')
            ]
            return ', '.join(tags) if tags else None
        except Exception as e:
            logger.warning(f"Error extracting tags: {e}")
        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из og:image и JSON-LD."""
        try:
            urls = []

            # 1. og:image
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])

            # 2. twitter:image
            twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
            if twitter_image and twitter_image.get('content'):
                urls.append(twitter_image['content'])

            # 3. JSON-LD (BlogPosting or ImageObject)
            scripts = self.soup.find_all('script', type='application/ld+json')
            for script in scripts:
                try:
                    data = json.loads(script.string)
                    graph = data.get('@graph', []) if isinstance(data, dict) else []
                    for item in graph:
                        if not isinstance(item, dict):
                            continue
                        item_type = item.get('@type', '')
                        if item_type == 'ImageObject':
                            img_url = item.get('url') or item.get('contentUrl')
                            if img_url:
                                urls.append(img_url)
                        elif item_type == 'BlogPosting':
                            img = item.get('image', {})
                            if isinstance(img, dict):
                                img_url = img.get('url') or img.get('contentUrl')
                                if img_url:
                                    urls.append(img_url)
                            elif isinstance(img, str):
                                urls.append(img)
                except (json.JSONDecodeError, AttributeError):
                    continue

            # Deduplicate preserving order
            seen: set = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)

            return ','.join(unique_urls) if unique_urls else None
        except Exception as e:
            logger.warning(f"Error extracting image URLs: {e}")
        return None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта из HTML.

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
    """Точка входа для обработки директории с HTML файлами."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "gatestiacasa_ro")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(GatestiacasaRoExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python gatestiacasa_ro.py")


if __name__ == "__main__":
    main()
