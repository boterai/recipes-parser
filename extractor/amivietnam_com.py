"""
Экстрактор данных рецептов для сайта amivietnam.com
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


class AmiVietnamExtractor(BaseRecipeExtractor):
    """Экстрактор для amivietnam.com"""

    # Ключевые слова для поиска секций по-вьетнамски
    _INGREDIENT_KEYWORDS = ['nguyên liệu', 'nguyên liêu', 'nguyen lieu']
    _INSTRUCTION_KEYWORDS = ['cách làm', 'quy trình', 'bước chuẩn bị', 'hướng dẫn',
                              'thực hiện', 'cach lam', 'quy trinh']
    _NOTES_KEYWORDS = ['lưu ý', 'mẹo', 'ghi chú', 'luu y', 'meo']

    # Вьетнамские единицы измерения и их нормализация
    # Compound units must come before their shorter prefixes in the alternation
    _UNIT_PATTERNS = re.compile(
        r'^(\d+(?:[.,/]\d+)?(?:\s+\d+(?:[.,/]\d+)?)?)\s*'
        r'(muỗng\s+cà\s+phê|thìa\s+cà\s+phê|'
        r'tablespoons?|teaspoons?|'
        r'pounds?|kilograms?|grams?|milliliters?|liters?|ounces?|'
        r'cloves?|bunches?|slices?|pieces?|'
        r'gói|quả|thìa|muỗng|bó|lát|miếng|củ|tép|cái|hộp|túi|chai|lon|'
        r'giọt|nhúm|chút|phần|'
        r'kg|ml|mg|lbs?|tbsp|tsp|cups?|oz|g)\s*',
        re.IGNORECASE | re.UNICODE
    )

    def _heading_matches(self, heading_text: str, keywords: list) -> bool:
        """Проверяет, содержит ли заголовок один из ключевых слов"""
        text_lower = heading_text.lower().strip()
        return any(kw in text_lower for kw in keywords)

    def _get_section_content(self, keywords: list) -> list:
        """
        Возвращает список элементов-соседей после первого заголовка,
        содержащего один из ключевых слов.
        Останавливается на следующем заголовке того же или выше уровня.
        """
        entry_content = self.soup.find(class_='entry-content')
        if not entry_content:
            return []

        for heading in entry_content.find_all(['h2', 'h3', 'h4', 'h5']):
            if self._heading_matches(heading.get_text(), keywords):
                siblings = []
                current = heading.find_next_sibling()
                while current:
                    if current.name in ['h2', 'h3', 'h4', 'h5']:
                        break
                    siblings.append(current)
                    current = current.find_next_sibling()
                return siblings
        return []

    def _parse_ingredient_text(self, text: str) -> Optional[dict]:
        """
        Парсит строку ингредиента в структурированный формат.

        Поддерживает несколько форматов:
          - "225g Bơ" или "225 g Bơ"  → amount=225, unit=g, name=Bơ
          - "Bơ: 225g"                 → amount=225, unit=g, name=Bơ
          - "Bánh sampa"               → amount=None, unit=None, name=Bánh sampa
        """
        if not text:
            return None

        text = self.clean_text(text)

        # Убираем скобочные пояснения в конце
        text_clean = re.sub(r'\s*\([^)]*\)\s*$', '', text).strip()

        # Pattern: number unit name
        match = self._UNIT_PATTERNS.match(text_clean)
        if match:
            amount_str = match.group(1).strip()
            unit = match.group(2).strip()
            name = text_clean[match.end():].strip().rstrip(',.:;')
            if name:
                return {
                    "name": name,
                    "amount": amount_str,
                    "unit": unit
                }

        # Pattern: name: number unit  (e.g. "Bơ: 225g" or "Bơ: 225 g")
        colon_match = re.match(
            r'^(.+?):\s*(\d+(?:[.,/]\d+)?(?:\s+\d+(?:[.,/]\d+)?)?)\s*'
            r'([a-zA-ZÀ-ỹ]+(?:\s+[a-zA-ZÀ-ỹ]+)*)?\s*$',
            text_clean,
            re.IGNORECASE | re.UNICODE
        )
        if colon_match:
            name = colon_match.group(1).strip()
            amount_str = colon_match.group(2).strip()
            unit = colon_match.group(3).strip() if colon_match.group(3) else None
            return {
                "name": name,
                "amount": amount_str,
                "unit": unit
            }

        # No amount/unit found — return as name only
        name = text_clean.rstrip(',.:;').strip()
        if not name or len(name) < 2:
            return None
        return {
            "name": name,
            "amount": None,
            "unit": None
        }

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            return self.clean_text(h1.get_text())

        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из секции с заголовком 'Nguyên liệu'"""
        ingredients = []

        entry_content = self.soup.find(class_='entry-content')
        if not entry_content:
            return None

        # Find the first heading matching ingredient keywords
        ingredient_heading = None
        for heading in entry_content.find_all(['h2', 'h3', 'h4', 'h5']):
            if self._heading_matches(heading.get_text(), self._INGREDIENT_KEYWORDS):
                ingredient_heading = heading
                break

        if not ingredient_heading:
            logger.warning("Не найдена секция ингредиентов в %s", self.html_path)
            return None

        # Collect ul/ol elements until next heading of same/higher level
        current = ingredient_heading.find_next_sibling()
        while current:
            if current.name in ['h2', 'h3', 'h4', 'h5']:
                break
            if current.name in ['ul', 'ol']:
                for li in current.find_all('li', recursive=False):
                    strong = li.find('strong')
                    if strong:
                        # Pattern 1: <strong>Name:</strong> amount unit
                        name = self.clean_text(strong.get_text()).rstrip(':').strip()
                        # Get remaining text after the strong tag
                        rest = li.get_text(separator=' ', strip=True)
                        strong_text = strong.get_text(strip=True)
                        rest = rest[len(strong_text):].strip()
                        # Try to parse amount/unit from rest
                        rest_clean = re.sub(r'\s*\([^)]*\)', '', rest).strip()
                        amt_unit = self._UNIT_PATTERNS.match(rest_clean)
                        if amt_unit:
                            amount = amt_unit.group(1).strip()
                            unit = amt_unit.group(2).strip()
                        else:
                            # Try just a number at the start
                            num_match = re.match(r'^(\d+(?:[.,/]\d+)?)\s*$', rest_clean)
                            if num_match:
                                amount = num_match.group(1)
                                unit = None
                            else:
                                amount = rest_clean if rest_clean else None
                                unit = None
                        if name:
                            ingredients.append({
                                "name": name,
                                "amount": amount if amount else None,
                                "unit": unit
                            })
                    else:
                        # Pattern 2/3: plain text "amount unit name"
                        li_text = li.get_text(separator=' ', strip=True)
                        parsed = self._parse_ingredient_text(li_text)
                        if parsed:
                            ingredients.append(parsed)
                if ingredients:
                    break
            current = current.find_next_sibling()

        if not ingredients:
            logger.warning("Ингредиенты не найдены в %s", self.html_path)
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []

        entry_content = self.soup.find(class_='entry-content')
        if not entry_content:
            return None

        # Find heading matching instruction keywords
        instruction_heading = None
        for heading in entry_content.find_all(['h2', 'h3', 'h4', 'h5']):
            if self._heading_matches(heading.get_text(), self._INSTRUCTION_KEYWORDS):
                instruction_heading = heading
                break

        if not instruction_heading:
            logger.warning("Не найдена секция инструкций в %s", self.html_path)
            return None

        current = instruction_heading.find_next_sibling()
        while current:
            if current.name in ['h2', 'h3']:
                break
            if current.name == 'p':
                text = self.clean_text(current.get_text())
                if text:
                    steps.append(text)
            elif current.name in ['ul', 'ol']:
                for li in current.find_all('li'):
                    text = self.clean_text(li.get_text(separator=' '))
                    if text:
                        steps.append(text)
            current = current.find_next_sibling()

        if not steps:
            logger.warning("Инструкции не найдены в %s", self.html_path)
            return None

        return ' '.join(steps)

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из CSS-классов статьи"""
        article = self.soup.find('article')
        if not article:
            return None

        classes = article.get('class', [])
        cat_classes = [c for c in classes if c.startswith('category-')]

        # Filter out generic categories
        skip = {'category-uncategorized', 'category-tin-tuc', 'category-tin-khac'}
        categories = []
        for c in cat_classes:
            name = c[len('category-'):]
            if c not in skip:
                # Convert slug to readable name
                name = name.replace('-', ' ').title()
                categories.append(name)

        if categories:
            return categories[0]

        return None

    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Время prep/cook/total для amivietnam.com обычно не представлено
        в структурированном виде — возвращаем None.
        """
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prep')

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('cook')

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('total')

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов из секции 'Lưu ý' или 'Mẹo'"""
        siblings = self._get_section_content(self._NOTES_KEYWORDS)
        if not siblings:
            return None

        parts = []
        for elem in siblings:
            if elem.name == 'p':
                text = self.clean_text(elem.get_text())
                if text:
                    parts.append(text)
            elif elem.name in ['ul', 'ol']:
                for li in elem.find_all('li'):
                    text = self.clean_text(li.get_text(separator=' '))
                    if text:
                        parts.append(text)

        return ' '.join(parts) if parts else None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из CSS-классов статьи (tag-*)"""
        article = self.soup.find('article')
        if not article:
            return None

        classes = article.get('class', [])
        tag_classes = [c for c in classes if c.startswith('tag-')]

        # Skip very generic tags
        skip_slugs = {'ami', 'ami-viet-nam'}
        tags = []
        seen = set()
        for c in tag_classes:
            slug = c[len('tag-'):]
            if slug in skip_slugs:
                continue
            # Convert slug to readable tag
            tag = slug.replace('-', ' ')
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)

        return ', '.join(tags) if tags else None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []

        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            img_url = twitter_image['content']
            if img_url not in urls:
                urls.append(img_url)

        return ','.join(urls) if urls else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()

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
            "image_urls": self.extract_image_urls(),
            "tags": tags,
        }


def main():
    import os
    recipes_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "preprocessed",
        "amivietnam_com"
    )
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(AmiVietnamExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python amivietnam_com.py")


if __name__ == "__main__":
    main()