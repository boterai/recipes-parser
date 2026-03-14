"""
Экстрактор данных рецептов для сайта fimela.com
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


# Indonesian units of measurement
_ID_UNITS = (
    r'sendok teh|sendok makan|sendok sup|sendok takar'
    r'|sdt|sdm|sds'
    r'|gelas|mangkuk|cangkir'
    r'|kg|gram|g\b|mg'
    r'|liter|ml|l\b'
    r'|buah|batang|lembar|helai|potong|iris|siung|biji|butir|genggam|ikat'
    r'|porsi|loyang|bungkus|sachet|kaleng|botol|toples'
    r'|cm|mm|inch'
    r'|cup|tbsp|tsp|oz|lb|lbs'
)

# Section header keywords (Indonesian)
_BAHAN_KEYWORDS = re.compile(r'\bbahan\b', re.IGNORECASE)
_CARA_KEYWORDS = re.compile(r'\bcara\s+membuat\b|\blangkah\b|\bpetunjuk\b|\bpembuatan\b', re.IGNORECASE)
_TIPS_KEYWORDS = re.compile(r'\btips?\b|\bsaran\b|\bcatatan\b|\bnote\b', re.IGNORECASE)


class FimelaComExtractor(BaseRecipeExtractor):
    """Экстрактор для fimela.com"""

    def _get_content_body(self):
        """Возвращает основной контейнер с содержимым статьи."""
        # Primary selector used by fimela.com
        body = self.soup.find('div', class_='article-content-body__item-content')
        if body:
            return body
        # Fallback: any article content body
        body = self.soup.find('div', class_=re.compile(r'article-content-body', re.I))
        return body

    @staticmethod
    def _is_section_header(elem) -> bool:
        """Проверяет, является ли элемент заголовком секции (содержит strong или это h2/h3)."""
        if not hasattr(elem, 'name') or not elem.name:
            return False
        if elem.name in ('h2', 'h3', 'h4'):
            return True
        if elem.name == 'p':
            strong = elem.find('strong')
            if strong:
                return True
            text = elem.get_text(strip=True)
            # Short bold-looking paragraphs with no sentence ending punctuation
            if text and len(text) < 80 and not text.endswith('.'):
                return True
        return False

    @staticmethod
    def _header_text(elem) -> str:
        """Извлекает текст заголовка секции."""
        return elem.get_text(strip=True) if elem else ''

    @staticmethod
    def _strip_resep_prefix(title: str) -> str:
        """Удаляет префикс 'Resep ' (Рецепт) из заголовка fimela.com."""
        return re.sub(r'^Resep\s+', '', title, flags=re.IGNORECASE).strip()

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда."""
        # Primary: h1.read-page--header--title
        h1 = self.soup.find('h1', class_=re.compile(r'read-page--header--title', re.I))
        if h1:
            return self._strip_resep_prefix(self.clean_text(h1.get_text()))

        # Fallback: any h1
        h1 = self.soup.find('h1')
        if h1:
            return self._strip_resep_prefix(self.clean_text(h1.get_text()))

        # Fallback: og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self._strip_resep_prefix(self.clean_text(og_title['content']))

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта из вступительных абзацев статьи."""
        body = self._get_content_body()
        if not body:
            # Fallback to meta description
            meta = self.soup.find('meta', {'name': 'description'})
            if meta and meta.get('content'):
                return self.clean_text(meta['content'])
            return None

        intro_parts = []
        for elem in body.children:
            if not hasattr(elem, 'name') or not elem.name:
                continue

            # Skip non-text containers
            classes = ' '.join(elem.get('class', []))
            if any(k in classes for k in ('advertisement', 'ad-', 'rating', 'baca-juga', 'boost-video')):
                continue

            # Stop at any section header (ingredient, instruction, or other sub-headings like "Manfaat")
            if self._is_section_header(elem):
                break

            if elem.name == 'p':
                txt = elem.get_text(separator=' ', strip=True)
                txt = self.clean_text(txt)
                # Strip the "Fimela.com, Jakarta -" site byline prefix
                txt = re.sub(r'^Fimela\.com\s*,\s*Jakarta\s*[-–—]?\s*', '', txt, flags=re.IGNORECASE)
                txt = re.sub(r'^Sahabat Fimela\s*,?\s*inilah\s+resep\s*', '', txt, flags=re.IGNORECASE)
                # Capitalize the first letter if it was lowered by stripping
                if txt and txt[0].islower():
                    txt = txt[0].upper() + txt[1:]
                if txt and len(txt) > 20:
                    intro_parts.append(txt)

        description = ' '.join(intro_parts) if intro_parts else None

        if not description:
            # Fallback: og:description
            og = self.soup.find('meta', property='og:description')
            if og and og.get('content'):
                description = self.clean_text(og['content'])

        return description

    def _parse_ingredient(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента на индонезийском.

        Форматы:
          '1 buah pisang beku'             → {amount:'1', unit:'buah', name:'pisang beku'}
          '100 ml susu almond'             → {amount:'100', unit:'ml', name:'susu almond'}
          '1 sendok teh bubuk matcha'      → {amount:'1', unit:'sendok teh', name:'bubuk matcha'}
          'secukupnya es batu'             → {amount:'secukupnya', unit:None, name:'es batu'}
          'Es batu secukupnya'             → {amount:'secukupnya', unit:None, name:'es batu'}
          'Stroberi segar, iris tipis'     → {amount:None, unit:None, name:'stroberi segar, iris tipis'}
        """
        if not text:
            return None

        original = text
        text = self.clean_text(text)

        # Normalise Unicode fractions
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
        }
        for frac, repl in fraction_map.items():
            text = text.replace(frac, repl)

        # Check if the entire entry looks like a header/sub-section (e.g. "Topping (opsional):")
        stripped = text.strip()
        if stripped.endswith(':') and len(stripped) < 60:
            return None

        amount = None
        unit = None
        name = text

        # Pattern: optional leading amount, optional unit, rest is name
        # Amount can be: digit(s) possibly with fraction, or Indonesian quantity words
        amount_pattern = r'^(\d+(?:[.,/]\d+)?(?:\s+\d+/\d+)?)\s*'
        special_amounts = r'^(secukupnya|sesuai\s+selera|sedikit|secukup(?:nya)?|sejumput|1\s+genggam)\s*'

        # Try special amount words at the start
        m = re.match(special_amounts, text, re.IGNORECASE)
        if m:
            amount = m.group(1).strip()
            rest = text[m.end():].strip()
            name = rest if rest else text
            unit = None
            return {"name": name if name else stripped, "amount": amount, "unit": unit}

        # Check for "secukupnya" or "sesuai selera" anywhere in the text
        # Handles cases like "Es batu secukupnya (opsional, ...)"
        m_secukupnya = re.search(r'\b(secukupnya|sesuai\s+selera)\b', text, re.IGNORECASE)
        if m_secukupnya:
            amount = m_secukupnya.group(1).strip()
            # Remove the amount word and optional notes to get the name
            name = text[:m_secukupnya.start()].strip()
            suffix = text[m_secukupnya.end():].strip()
            # Keep "(opsional)" if present in the suffix
            if re.match(r'^\s*\(opsional', suffix, re.IGNORECASE):
                name = name + ' (opsional)'
            name = re.sub(r'\s+', ' ', name).strip(' ,')
            return {"name": name if name else stripped, "amount": amount, "unit": None}

        # Check for "secukupnya" or "sesuai selera" at the end
        m_end = re.search(r'\s+(secukupnya|sesuai\s+selera|sedikit)$', text, re.IGNORECASE)
        if m_end:
            amount = m_end.group(1).strip()
            name = text[:m_end.start()].strip()
            name = re.sub(r'\s*\(opsional\)', '', name, flags=re.IGNORECASE).strip()
            return {"name": name if name else stripped, "amount": amount, "unit": None}

        # Try numeric amount at start
        m_amt = re.match(amount_pattern, text, re.IGNORECASE)
        if m_amt:
            raw_amount = m_amt.group(1).strip()
            rest_after_amount = text[m_amt.end():]

            # Try to match a unit
            unit_pattern = r'^(' + _ID_UNITS + r')\s+'
            m_unit = re.match(unit_pattern, rest_after_amount, re.IGNORECASE)
            if m_unit:
                unit = m_unit.group(1).strip()
                rest_after_unit = rest_after_amount[m_unit.end():]
            else:
                unit = None
                rest_after_unit = rest_after_amount

            name = rest_after_unit.strip()
            # Normalise amount
            amount = raw_amount

            if name:
                return {"name": name, "amount": amount, "unit": unit}

        # No amount found – return the whole text as name
        return {"name": stripped, "amount": None, "unit": None}

    def _collect_ingredient_uls(self, body) -> list:
        """
        Проходит по content body и собирает <ul> элементы,
        которые идут после заголовка секции с "Bahan" или "Topping".
        """
        collecting = False
        ingredient_uls = []

        for elem in body.children:
            if not hasattr(elem, 'name') or not elem.name:
                continue

            classes = ' '.join(elem.get('class', []))
            if any(k in classes for k in ('advertisement', 'ad-', 'rating', 'baca-juga', 'boost-video')):
                continue

            if self._is_section_header(elem):
                header = self._header_text(elem)
                if _BAHAN_KEYWORDS.search(header) or re.search(r'\btopping\b', header, re.IGNORECASE):
                    collecting = True
                    continue
                elif _CARA_KEYWORDS.search(header) or _TIPS_KEYWORDS.search(header):
                    # Stop collecting ingredients
                    collecting = False
                    continue
                else:
                    # Other header – stop collecting
                    collecting = False
                    continue

            if collecting and elem.name == 'ul':
                ingredient_uls.append(elem)

        return ingredient_uls

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из HTML."""
        body = self._get_content_body()
        if not body:
            return None

        ingredient_uls = self._collect_ingredient_uls(body)

        ingredients = []
        for ul in ingredient_uls:
            for li in ul.find_all('li'):
                text = li.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                if not text:
                    continue
                parsed = self._parse_ingredient(text)
                if parsed:
                    ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления."""
        body = self._get_content_body()
        if not body:
            return None

        in_instructions = False
        steps = []
        found_numbered = False  # Whether we've seen at least one numbered step

        for elem in body.children:
            if not hasattr(elem, 'name') or not elem.name:
                continue

            classes = ' '.join(elem.get('class', []))
            if any(k in classes for k in ('advertisement', 'ad-', 'rating', 'baca-juga', 'boost-video')):
                continue

            if self._is_section_header(elem):
                header = self._header_text(elem)
                if _CARA_KEYWORDS.search(header):
                    in_instructions = True
                    continue
                elif in_instructions:
                    # Next section after instructions – stop
                    break

            if in_instructions and elem.name == 'p':
                txt = elem.get_text(separator=' ', strip=True)
                txt = self.clean_text(txt)
                if txt:
                    is_numbered = bool(re.match(r'^\d+\.', txt))
                    if is_numbered:
                        found_numbered = True
                        steps.append(txt)
                    elif found_numbered:
                        # After numbered steps, stop on un-numbered conclusion text
                        break
                    else:
                        # Before any numbered steps – still collect
                        steps.append(txt)

        if not steps:
            return None

        return ' '.join(steps)

    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта."""
        # fimela.com shows a tag category label as span.fimela-tags--snippet__name
        cat_span = self.soup.find('span', class_='fimela-tags--snippet__name')
        if cat_span:
            txt = self.clean_text(cat_span.get_text())
            if txt:
                return txt

        # Fallback: breadcrumb section (second item in BreadcrumbList JSON-LD)
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string) if script.string else None
                if not data:
                    continue
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get('@type') == 'BreadcrumbList':
                        elements = item.get('itemListElement', [])
                        # Position 2 (index 1) is the section, e.g. "Food"
                        if len(elements) >= 2:
                            name = elements[1].get('name', '')
                            if name and name.lower() not in ('fimela', 'fimela.com'):
                                return self.clean_text(name)
            except (json.JSONDecodeError, AttributeError):
                continue

        # Fallback: header subtitle (e.g. "Food")
        subtitle = self.soup.find('p', class_=re.compile(r'read-page--header--subtitle', re.I))
        if subtitle:
            txt = self.clean_text(subtitle.get_text())
            if txt:
                return txt

        return None

    def _extract_recipe_detail_time(self, keyword: str) -> Optional[str]:
        """
        Извлекает время из div.fimela--recipe-details__container.
        keyword: строка вроде 'cooking-time' или 'prep-time' (CSS class suffix).
        """
        container = self.soup.find(
            'div',
            class_=re.compile(r'fimela--recipe-details__container', re.I)
        )
        if not container:
            return None

        # Find the time text span within the container
        time_text_span = container.find('span', class_='fimela--recipe-details__text')
        if time_text_span:
            return self.clean_text(time_text_span.get_text())

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки."""
        container = self.soup.find('div', class_=re.compile(r'fimela--recipe-details__container.*prep', re.I))
        if container:
            span = container.find('span', class_='fimela--recipe-details__text')
            if span:
                return self.clean_text(span.get_text())
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления."""
        # fimela.com uses class 'cooking-time' on the container div
        containers = self.soup.find_all('div', class_=re.compile(r'fimela--recipe-details__container', re.I))
        for container in containers:
            classes = ' '.join(container.get('class', []))
            title_span = container.find('span', class_='fimela--recipe-details__title')
            title_text = title_span.get_text(strip=True).lower() if title_span else ''
            if 'cooking-time' in classes or 'waktu' in title_text or 'cook' in title_text:
                time_span = container.find('span', class_='fimela--recipe-details__text')
                if time_span:
                    return self.clean_text(time_span.get_text())
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени."""
        containers = self.soup.find_all('div', class_=re.compile(r'fimela--recipe-details__container', re.I))
        for container in containers:
            title_span = container.find('span', class_='fimela--recipe-details__title')
            title_text = title_span.get_text(strip=True).lower() if title_span else ''
            if 'total' in title_text:
                time_span = container.find('span', class_='fimela--recipe-details__text')
                if time_span:
                    return self.clean_text(time_span.get_text())
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение советов/заметок к рецепту."""
        body = self._get_content_body()
        if not body:
            return None

        in_tips = False
        notes_items = []

        for elem in body.children:
            if not hasattr(elem, 'name') or not elem.name:
                continue

            classes = ' '.join(elem.get('class', []))
            if any(k in classes for k in ('advertisement', 'ad-', 'rating', 'baca-juga', 'boost-video')):
                continue

            if self._is_section_header(elem):
                header = self._header_text(elem)
                if _TIPS_KEYWORDS.search(header):
                    in_tips = True
                    continue
                elif in_tips:
                    break

            if in_tips and elem.name == 'ul':
                for li in elem.find_all('li'):
                    txt = li.get_text(separator=' ', strip=True)
                    txt = self.clean_text(txt)
                    if txt:
                        notes_items.append(txt)
                break  # Only first tips ul

        return ' '.join(notes_items) if notes_items else None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта."""
        tags_ul = self.soup.find('ul', class_='fimela-tags--snippet__list')
        if not tags_ul:
            return None

        tags = []
        for li in tags_ul.find_all('li', class_='fimela-tags--snippet__item'):
            txt = li.get_text(strip=True)
            # Skip the "Hashtag Lainnya..." button item
            if txt and 'hashtag lainnya' not in txt.lower() and 'lainnya' not in txt.lower():
                tags.append(txt)

        return ', '.join(tags) if tags else None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта."""
        urls = []

        # Primary: og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content'].strip()
            if url:
                urls.append(url)

        # Secondary: JSON-LD NewsArticle image
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string) if script.string else None
                if not data:
                    continue
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get('@type') in ('NewsArticle', 'Article', 'BlogPosting'):
                        images = item.get('image', [])
                        if isinstance(images, str):
                            images = [images]
                        for img in images:
                            if isinstance(img, dict):
                                img = img.get('url', img.get('contentUrl', ''))
                            if img and img not in urls:
                                urls.append(img)
            except (json.JSONDecodeError, AttributeError):
                continue

        # Tertiary: article main image (read-page--top-media)
        top_media = self.soup.find('div', class_='read-page--top-media')
        if top_media:
            for img in top_media.find_all('img'):
                src = img.get('src') or img.get('data-src', '')
                if src and src.startswith('http') and src not in urls:
                    urls.append(src)

        if not urls:
            return None

        # Remove duplicates preserving order
        seen = set()
        unique = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                unique.append(u)

        return ','.join(unique)

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта в едином формате проекта.
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception as e:
            logger.warning("Ошибка при извлечении dish_name: %s", e)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as e:
            logger.warning("Ошибка при извлечении description: %s", e)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as e:
            logger.warning("Ошибка при извлечении ingredients: %s", e)
            ingredients = None

        try:
            instructions = self.extract_instructions()
        except Exception as e:
            logger.warning("Ошибка при извлечении instructions: %s", e)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as e:
            logger.warning("Ошибка при извлечении category: %s", e)
            category = None

        try:
            notes = self.extract_notes()
        except Exception as e:
            logger.warning("Ошибка при извлечении notes: %s", e)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as e:
            logger.warning("Ошибка при извлечении tags: %s", e)
            tags = None

        try:
            prep_time = self.extract_prep_time()
        except Exception as e:
            logger.warning("Ошибка при извлечении prep_time: %s", e)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception as e:
            logger.warning("Ошибка при извлечении cook_time: %s", e)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception as e:
            logger.warning("Ошибка при извлечении total_time: %s", e)
            total_time = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as e:
            logger.warning("Ошибка при извлечении image_urls: %s", e)
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
    """Точка входа для обработки директории с HTML файлами."""
    import os

    preprocessed_dir = os.path.join("preprocessed", "fimela_com")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(FimelaComExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python fimela_com.py")


if __name__ == "__main__":
    main()
