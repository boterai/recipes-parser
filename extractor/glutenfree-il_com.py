"""
Экстрактор данных рецептов для сайта glutenfree-il.com
"""

import logging
import sys
import json
import re
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class GlutenFreeIlExtractor(BaseRecipeExtractor):
    """Экстрактор для glutenfree-il.com"""

    # Hebrew units and their English equivalents (used for normalisation)
    HEBREW_UNITS = {
        'כוסות': 'cups',
        'כוס': 'cup',
        'כפות': 'tablespoons',
        'כף': 'tablespoon',
        'כפיות': 'teaspoons',
        'כפית': 'teaspoon',
        'גרמים': 'grams',
        'גרם': 'gram',
        "ג'": 'g',
        'מיליליטר': 'ml',
        "מ\"ל": 'ml',
        'ליטרים': 'liters',
        'ליטר': 'liter',
        'חבילות': 'packages',
        'חבילה': 'package',
        'יחידות': 'units',
        'יחידה': 'unit',
        'שיני': 'cloves',
        'שן': 'clove',
        'קורט': 'pinch',
        'חופן': 'handful',
        'קילוגרם': 'kg',
        'ק"ג': 'kg',
    }

    # Hebrew number words
    HEBREW_NUMBERS = {
        'אחת': 1,
        'אחד': 1,
        'שתיים': 2,
        'שניים': 2,
        'שתי': 2,
        'שני': 2,
        'שלוש': 3,
        'שלושה': 3,
        'ארבע': 4,
        'ארבעה': 4,
        'חמש': 5,
        'חמישה': 5,
        'שש': 6,
        'ששה': 6,
        'שבע': 7,
        'שבעה': 7,
        'שמונה': 8,
        'תשע': 9,
        'תשעה': 9,
        'עשר': 10,
        'עשרה': 10,
        'חצי': 0.5,
        'שליש': 0.33,
        'שלישית': 0.33,
        'רבע': 0.25,
    }

    def _get_json_ld_graph(self) -> list:
        """Извлечение графа JSON-LD (Yoast schema) со страницы"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    return data['@graph']
            except (json.JSONDecodeError, ValueError):
                continue
        return []

    def _get_entry_content(self):
        """Возвращает элемент entry-content (тело статьи)"""
        return self.soup.find('div', class_=re.compile(r'entry-content', re.I))

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из заголовка страницы"""
        title_elem = self.soup.find(class_='page-title')
        if title_elem:
            title = self.clean_text(title_elem.get_text())
            # Strip "מתכון:" or "מתכון :" prefix (Recipe:)
            title = re.sub(r'^מתכון\s*:\s*', '', title, flags=re.IGNORECASE)
            # Strip subtitle after " | "
            title = re.split(r'\s*\|\s*', title)[0]
            return self.clean_text(title) or None

        # Fallback: og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'^מתכון\s*:\s*', '', title)
            title = re.split(r'\s*\|\s*', title)[0]
            # Strip site name suffix
            title = re.sub(r'\s*-\s*ללא גלוטן.*$', '', title)
            return self.clean_text(title) or None

        # Fallback: h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text()) or None

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # page-description element (hero section below title)
        page_desc = self.soup.find(class_='page-description')
        if page_desc:
            text = self.clean_text(page_desc.get_text())
            if text:
                return text

        # meta description fallback
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        # og:description fallback
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def _parse_hebrew_amount(self, text: str) -> tuple:
        """
        Parses a Hebrew ingredient string into (amount, unit, name).

        Returns:
            Tuple of (amount, unit, name) where amount may be int/float/None,
            unit may be str/None, and name is str.
        """
        text = text.strip()

        # Remove trailing period and parenthetical notes (e.g. "(...)")
        text = re.sub(r'\s*\([^)]*\)', '', text)
        text = text.rstrip('.')
        text = self.clean_text(text)

        # Strip leading label like "להמתקה:", "לציפוי:", "לרוטב:", etc.
        text = re.sub(r'^[^:]+:\s*', '', text)
        text = self.clean_text(text)

        amount = None
        unit = None
        name = text

        # Unicode fraction replacement
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
        }
        for frac, val in fraction_map.items():
            text = text.replace(frac, val)

        # Try to match a leading numeric amount (including fractions like "1/2", "2-3")
        # Pattern: optional_number unit? rest
        num_pattern = r'^([\d]+(?:[.,]\d+)?(?:\s*/\s*[\d]+)?(?:\s*[-–]\s*[\d]+(?:[.,]\d+)?)?)\s+'
        num_match = re.match(num_pattern, text)

        if num_match:
            raw_amount = num_match.group(1).strip()
            rest = text[num_match.end():]

            # Normalize range "2-3" or "2–3" -> take max
            range_match = re.match(r'^([\d.,]+)\s*[-–]\s*([\d.,]+)$', raw_amount)
            if range_match:
                try:
                    amount = float(range_match.group(2).replace(',', '.'))
                    if amount == int(amount):
                        amount = int(amount)
                except ValueError:
                    amount = None
            elif '/' in raw_amount:
                # Handle fractions like "1/2" or "1 1/2"
                parts = raw_amount.split()
                total = 0.0
                for part in parts:
                    if '/' in part:
                        try:
                            n, d = part.split('/')
                            total += float(n) / float(d)
                        except (ValueError, ZeroDivisionError):
                            pass
                    else:
                        try:
                            total += float(part.replace(',', '.'))
                        except ValueError:
                            pass
                amount = total if total > 0 else None
                if amount and amount == int(amount):
                    amount = int(amount)
            else:
                try:
                    amount = float(raw_amount.replace(',', '.'))
                    if amount == int(amount):
                        amount = int(amount)
                except ValueError:
                    amount = None

            # Try to match a Hebrew unit at the start of rest
            unit_match = self._match_hebrew_unit(rest)
            if unit_match:
                unit, name = unit_match
            else:
                name = rest

        else:
            # Try Hebrew number words at the start
            word_match = self._match_hebrew_number_word(text)
            if word_match:
                amount, rest = word_match
                unit_match = self._match_hebrew_unit(rest)
                if unit_match:
                    unit, name = unit_match
                else:
                    name = rest
            else:
                # Try unit at start without explicit amount (e.g. "כף קורנפלור")
                unit_match = self._match_hebrew_unit(text)
                if unit_match:
                    unit, name = unit_match
                    amount = 1  # Implied single unit

        # Clean up name
        name = self.clean_text(name.strip(' .,'))
        if not name:
            name = text

        return amount, unit, name

    def _match_hebrew_unit(self, text: str) -> Optional[tuple]:
        """
        Tries to match a Hebrew unit at the start of text.

        Returns:
            (unit_string, remainder_name) or None
        """
        # Sort by length descending so we match longer units first
        for heb_unit in sorted(self.HEBREW_UNITS.keys(), key=len, reverse=True):
            pattern = r'^' + re.escape(heb_unit) + r'\s+'
            m = re.match(pattern, text)
            if m:
                remainder = text[m.end():]
                return heb_unit, remainder.strip()

        # Also handle plural "גרם" (already in dict but try exact word match)
        # Hebrew unit at start with word boundary
        for heb_unit in sorted(self.HEBREW_UNITS.keys(), key=len, reverse=True):
            if text.startswith(heb_unit):
                remainder = text[len(heb_unit):].strip()
                if not remainder or not remainder[0].isalpha():
                    return heb_unit, remainder.strip(' .,')

        return None

    def _match_hebrew_number_word(self, text: str) -> Optional[tuple]:
        """
        Matches Hebrew number words (like חצי, אחת, etc.) at the start of text.

        Returns:
            (numeric_value, remainder_text) or None
        """
        for word, value in sorted(self.HEBREW_NUMBERS.items(), key=lambda x: len(x[0]), reverse=True):
            pattern = r'^' + re.escape(word) + r'\s+'
            if re.match(pattern, text, re.IGNORECASE):
                remainder = text[len(word):].strip()
                return value, remainder

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из списков статьи"""
        entry = self._get_entry_content()
        if not entry:
            logger.warning("entry-content not found for %s", self.html_path)
            return None

        ingredients = []

        # Collect all <ul> elements in the entry content that appear before or
        # near instruction sections.  We take ALL <ul> lists that contain <li>
        # items because ingredients on this site are always in <ul> blocks.
        ul_elements = entry.find_all('ul')

        for ul in ul_elements:
            items = ul.find_all('li', recursive=False)
            if not items:
                items = ul.find_all('li')
            for li in items:
                raw = li.get_text(separator=' ', strip=True)
                raw = self.clean_text(raw)
                if not raw:
                    continue
                try:
                    amount, unit, name = self._parse_hebrew_amount(raw)
                    if name:
                        ingredients.append({
                            'name': name,
                            'amount': amount,
                            'unit': unit,
                        })
                except Exception as exc:
                    logger.debug("Failed to parse ingredient %r: %s", raw, exc)
                    ingredients.append({'name': raw, 'amount': None, 'unit': None})

        if not ingredients:
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def extract_steps(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        entry = self._get_entry_content()
        if not entry:
            return None

        steps = []

        # 1. Try <ol> elements first (structured instructions)
        ol_elements = entry.find_all('ol')
        for ol in ol_elements:
            for idx, li in enumerate(ol.find_all('li'), start=1):
                step_text = self.clean_text(li.get_text(separator=' ', strip=True))
                if step_text:
                    steps.append(f"{idx}. {step_text}")

        if steps:
            return ' '.join(steps)

        # 2. Fallback: look for paragraph that follows "איך מכינים?" / "אופן ההכנה:"
        instruction_headers = [
            'איך מכינים',
            'אופן ההכנה',
            'הכנה',
            'הוראות הכנה',
        ]
        all_paragraphs = entry.find_all(['p', 'h2', 'h3'])
        for i, elem in enumerate(all_paragraphs):
            text = elem.get_text()
            for header in instruction_headers:
                if header in text:
                    # The instruction content may be in the same element or the next
                    # Check if the element contains a <br> followed by content
                    br_tag = elem.find('br')
                    if br_tag:
                        # Get text after the <br>
                        instruction_text = ''
                        for sibling in br_tag.next_siblings:
                            if hasattr(sibling, 'get_text'):
                                instruction_text += sibling.get_text(separator=' ')
                            else:
                                instruction_text += str(sibling)
                        instruction_text = self.clean_text(instruction_text)
                        if instruction_text:
                            return instruction_text

                    # Check next paragraph
                    if i + 1 < len(all_paragraphs):
                        next_elem = all_paragraphs[i + 1]
                        next_text = self.clean_text(next_elem.get_text(separator=' ', strip=True))
                        if next_text and not any(h in next_text for h in instruction_headers):
                            return next_text
                    break

        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из meta-categories или JSON-LD articleSection"""
        # 1. From JSON-LD articleSection
        graph = self._get_json_ld_graph()
        for item in graph:
            if item.get('@type') == 'Article':
                sections = item.get('articleSection', [])
                if isinstance(sections, list) and sections:
                    return self.clean_text(sections[0])
                elif isinstance(sections, str) and sections:
                    return self.clean_text(sections)

        # 2. From meta-categories link text
        meta_cats = self.soup.find(class_='meta-categories')
        if meta_cats:
            link = meta_cats.find('a')
            if link:
                return self.clean_text(link.get_text())

        return None

    def _extract_time_from_text(self, text: str, time_label: str) -> Optional[str]:
        """
        Searches for a time value in article text near a label keyword.

        Args:
            text: Full article text
            time_label: Hebrew keyword to search near

        Returns:
            Time string like "40 minutes" or None
        """
        # Look for label followed by a time value on the same line/nearby
        patterns = [
            r'(?:' + re.escape(time_label) + r')[^\n]{0,40}?(\d+)\s*(?:עד\s*\d+\s*)?(?:דקות|minutes)',
            r'(\d+)\s*(?:עד\s*(\d+)\s*)?דקות',
        ]

        # First try label-specific
        label_pattern = r'(?:' + re.escape(time_label) + r')[^\n]{0,60}?(\d+)\s*(?:עד\s*(\d+)\s*)?(?:דקות|minutes)'
        m = re.search(label_pattern, text, re.IGNORECASE)
        if m:
            # Take the larger number in a range
            val = int(m.group(2)) if m.group(2) else int(m.group(1))
            return f"{val} minutes"

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        entry = self._get_entry_content()
        if not entry:
            return None
        text = entry.get_text()
        # Look for prep time labels
        for label in ['זמן הכנה', 'הכנה:', 'זמן מנוחה', 'לשעה']:
            result = self._extract_time_from_text(text, label)
            if result:
                return result
        # Look for "שעה" (hour) pattern
        m = re.search(r'(?:לשעה|שעת)\s*(?:מנוחה|קירור|אחסון)?', text)
        if m:
            return '60 minutes'
        return None

    def _parse_cook_time_from_text(self, text: str) -> Optional[int]:
        """
        Parses cooking time minutes from a text block.

        Handles:
        - "X minutes + Y more minutes" patterns (sums them)
        - "X to Y minutes" ranges (takes the max)
        - Simple "X minutes" values
        """
        # Pattern 1: "X דקות ... Y דקות נוספות" — sequential phases, sum them
        additional_pattern = r'(\d+)\s*דקות[^.!?]{0,60}?(\d+)\s*דקות\s+(?:נוספות|עוד)'
        m = re.search(additional_pattern, text)
        if m:
            return int(m.group(1)) + int(m.group(2))

        # Pattern 2: range "X עד Y דקות"
        range_pattern = r'(\d+)\s*(?:עד)\s*(?:ל-|כ-)?(\d+)\s*דקות'
        m = re.search(range_pattern, text)
        if m:
            return int(m.group(2))  # Take the max of the range

        # Pattern 3: simple "X דקות" (last occurrence that's baking/cooking)
        single_pattern = r'(?:כ-|ל-|כ)?(\d+)\s*דקות'
        matches = re.findall(single_pattern, text)
        if matches:
            # Return the largest value (most likely the main cooking time)
            return max(int(v) for v in matches)

        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        entry = self._get_entry_content()
        if not entry:
            return None
        text = entry.get_text()

        minutes = self._parse_cook_time_from_text(text)
        if minutes:
            return f"{minutes} minutes"

        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        entry = self._get_entry_content()
        if not entry:
            return None
        text = entry.get_text()

        result = self._extract_time_from_text(text, 'זמן כולל')
        if result:
            return result

        # Try to sum prep_time and cook_time if both available
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        if prep and cook:
            try:
                prep_min = int(re.search(r'(\d+)', prep).group(1))
                cook_min = int(re.search(r'(\d+)', cook).group(1))
                total = prep_min + cook_min
                return f"{total} minutes"
            except (AttributeError, ValueError):
                pass

        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов из статьи (первый заметный совет)"""
        entry = self._get_entry_content()
        if not entry:
            return None

        # 1. Look for explicit (non-numbered) tip sections:
        #    h3/h2 containing "טיפ" / "הערה" / "שימו לב" that are NOT regular article tips
        #    (i.e., not starting with a digit + period)
        for header in entry.find_all(['h2', 'h3']):
            header_text = header.get_text()
            if (re.search(r'טיפ|הערה|שימו לב', header_text, re.I) and
                    not re.match(r'^\d+\.', header_text.strip())):
                next_sib = header.find_next_sibling('p')
                if next_sib:
                    note_text = self.clean_text(next_sib.get_text(separator=' ', strip=True))
                    if note_text:
                        return note_text

        # 2. Use first numbered tip heading text (e.g. h2/h3 "1. ...")
        numbered_headers = entry.find_all(
            ['h2', 'h3'],
            string=re.compile(r'^\d+\.', re.I)
        )
        if numbered_headers:
            header_text = self.clean_text(numbered_headers[0].get_text())
            # Strip leading "N. " prefix
            header_text = re.sub(r'^\d+\.\s*', '', header_text)
            if header_text:
                return header_text

        # 3. Look for <em> (italic) notes at the end of the article
        em_tags = entry.find_all('em')
        for em in em_tags:
            em_text = self.clean_text(em.get_text())
            if em_text and len(em_text) > 20:
                return em_text

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из категорий статьи"""
        tags = []

        # From JSON-LD articleSection
        graph = self._get_json_ld_graph()
        for item in graph:
            if item.get('@type') == 'Article':
                sections = item.get('articleSection', [])
                if isinstance(sections, list):
                    tags.extend([s for s in sections if s])
                elif isinstance(sections, str) and sections:
                    tags.append(sections)

        # From meta-categories links
        meta_cats = self.soup.find(class_='meta-categories')
        if meta_cats:
            for a in meta_cats.find_all('a'):
                tag_text = self.clean_text(a.get_text())
                if tag_text and tag_text not in tags:
                    tags.append(tag_text)

        if not tags:
            return None

        # Return as comma-separated string (deduplicated)
        seen = set()
        unique_tags = []
        for t in tags:
            if t not in seen:
                seen.add(t)
                unique_tags.append(t)

        return ', '.join(unique_tags)

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls = []

        # 1. og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # 2. JSON-LD ImageObject in the @graph
        graph = self._get_json_ld_graph()
        for item in graph:
            if item.get('@type') == 'ImageObject':
                url = item.get('url') or item.get('contentUrl')
                if url and url not in urls:
                    urls.append(url)

        # 3. Thumbnail URL from JSON-LD Article/WebPage
        for item in graph:
            thumbnail = item.get('thumbnailUrl')
            if thumbnail and thumbnail not in urls:
                urls.append(thumbnail)

        # 4. Article images (wp-post-image in the hero section)
        hero = self.soup.find(class_='hero-section')
        if hero:
            for img in hero.find_all('img'):
                src = img.get('src')
                if src and src not in urls:
                    urls.append(src)

        if not urls:
            return None

        # Deduplicate and return as comma-joined string (no spaces)
        seen = set()
        unique_urls = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                unique_urls.append(u)

        return ','.join(unique_urls)

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            dict со всеми полями рецепта (поля с отсутствующими данными — None)
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception as exc:
            logger.error("dish_name extraction failed: %s", exc)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as exc:
            logger.error("description extraction failed: %s", exc)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as exc:
            logger.error("ingredients extraction failed: %s", exc)
            ingredients = None

        try:
            instructions = self.extract_steps()
        except Exception as exc:
            logger.error("instructions extraction failed: %s", exc)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as exc:
            logger.error("category extraction failed: %s", exc)
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception as exc:
            logger.error("prep_time extraction failed: %s", exc)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception as exc:
            logger.error("cook_time extraction failed: %s", exc)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception as exc:
            logger.error("total_time extraction failed: %s", exc)
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception as exc:
            logger.error("notes extraction failed: %s", exc)
            notes = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as exc:
            logger.error("image_urls extraction failed: %s", exc)
            image_urls = None

        try:
            tags = self.extract_tags()
        except Exception as exc:
            logger.error("tags extraction failed: %s", exc)
            tags = None

        return {
            'dish_name': dish_name,
            'description': description,
            'ingredients': ingredients,
            'instructions': instructions,
            'category': category,
            'prep_time': prep_time,
            'cook_time': cook_time,
            'total_time': total_time,
            'notes': notes,
            'image_urls': image_urls,
            'tags': tags,
        }


def main():
    """Точка входа для обработки директории с HTML-страницами"""
    import os

    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join('preprocessed', 'glutenfree-il_com')

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(GlutenFreeIlExtractor, preprocessed_dir)
        return

    print(f'Директория не найдена: {preprocessed_dir}')
    print('Использование: python glutenfree-il_com.py')


if __name__ == '__main__':
    main()
