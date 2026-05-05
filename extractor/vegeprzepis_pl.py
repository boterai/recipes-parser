"""
Экстрактор данных рецептов для сайта vegeprzepis.pl
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

# Polish measurement units (regex alternation, no outer group)
_POLISH_UNITS = (
    r'kg|dag|dkg|g|dl|cl|ml|l'
    r'|łyżk[aięi]|łyżek'
    r'|łyżeczk[aięi]'
    r'|szklank[aięi]|szklanek'
    r'|puszk[aię]|puszek'
    r'|opakow(?:anie|ania|ań)'
    r'|pęczk[aiu]?|pęczki|pęczków'
    r'|plast(?:erek|erka|ry|erków)'
    r'|kawałk[aiu]?|kawałki|kawałków'
    r'|szczypty?|szczypci'
    r'|sztuk[ai]?|sztuk'
    r'|garść|garści'
    r'|mała|małej|małe'
    r'|duża|dużej|duże'
    r'|gramów|gram'
    r'|kilogram(?:ów|a)?'
    r'|litr(?:ów|a)?'
    r'|mililitr(?:ów|a)?'
)

# Compiled pattern: optional amount, optional unit, name
_INGREDIENT_RE = re.compile(
    r'^(\d+(?:[.,/]\d+)?(?:\s+\d+/\d+)?)\s*'
    r'(?:(' + _POLISH_UNITS + r')\s+)?'
    r'(.+)',
    re.IGNORECASE,
)

# Pattern for parenthetical measure: "1 puszka (400 g) sos pomidorowy"
_PAREN_MEASURE_RE = re.compile(
    r'^(\d+(?:[.,]\d+)?)\s+\S+\s*\((\d+(?:[.,]\d+)?)\s*(' + _POLISH_UNITS + r')\)\s+(.+)',
    re.IGNORECASE,
)


class VegeprzepisPlExtractor(BaseRecipeExtractor):
    """Экстрактор для vegeprzepis.pl"""

    # ------------------------------------------------------------------ helpers

    def _get_json_ld_blog_posting(self) -> Optional[dict]:
        """Извлечение BlogPosting из JSON-LD @graph"""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'BlogPosting':
                            return item
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
        return None

    def _get_article(self):
        """Получение основного блока статьи"""
        return self.soup.find('article')

    # ------------------------------------------------------------------ extractors

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Preferred: h1.post-title or h1.entry-title
        h1 = self.soup.find('h1', class_=re.compile(r'post-title|entry-title', re.I))
        if not h1:
            h1 = self.soup.find('h1')

        if h1:
            title = h1.get_text(strip=True)
            # Strip common site suffix variants
            title = re.sub(r'\s*[–\-]\s*(?:Tradycyjny\s+)?(?:Polski\s+)?Vege\s+przepis\s*$',
                           '', title, flags=re.IGNORECASE)
            return self.clean_text(title) or None

        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*[–\-]\s*Vege\s+przepis\s*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title) or None

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        article = self._get_article()
        if article:
            # Option 1: paragraph after "Wprowadzenie" heading
            for h in article.find_all(['h2', 'h3']):
                if 'wprowadzeni' in h.get_text(strip=True).lower():
                    sibling = h.find_next_sibling()
                    if sibling and sibling.name == 'p':
                        text = self.clean_text(sibling.get_text(strip=True))
                        if text:
                            return text

            # Option 2: first substantial paragraph before the "Składniki" content
            # Works for both flat (h2/h3 "Składniki") and nested (section "Składniki") layouts
            def _is_skladniki(tag) -> bool:
                return tag.name in ['h2', 'h3', 'section'] and \
                       'składni' in tag.get_text(strip=True).lower()

            for section in article.find_all('section'):
                found_desc: Optional[str] = None
                for child in section.children:
                    if not hasattr(child, 'name') or not child.name:
                        continue
                    if child.name == 'p':
                        txt = self.clean_text(child.get_text(strip=True))
                        if txt and len(txt) > 40:
                            found_desc = txt
                    elif _is_skladniki(child):
                        if found_desc:
                            return found_desc
                        break

        # Fallback: meta description (may be truncated by the site)
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content']) or None

        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content']) or None

        return None

    def _parse_ingredient_line(self, line: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат.

        Args:
            line: Например "1 kg ziemniaków" или "2 łyżki mąki"

        Returns:
            dict: {"name": "...", "amount": "...", "unit": "..."} или None
        """
        if not line:
            return None
        text = self.clean_text(line).strip()
        if not text:
            return None

        # Handle "1 puszka (400 g) sosu pomidorowego" → extract unit from parenthetical
        paren_m = _PAREN_MEASURE_RE.match(text)
        if paren_m:
            amount = paren_m.group(2).replace(',', '.')
            unit = paren_m.group(3).lower()
            name = self.clean_text(paren_m.group(4))
            return {"name": name, "amount": amount, "unit": unit}

        m = _INGREDIENT_RE.match(text)
        if not m:
            return {"name": text, "amount": None, "unit": None}

        amount_str, unit, name = m.group(1), m.group(2), m.group(3)

        # Parse amount (handle fractions like "1/2" or "1 1/2")
        amount_str = (amount_str or '').strip()
        amount: Optional[str] = None
        if amount_str:
            if '/' in amount_str:
                total = 0.0
                for part in amount_str.split():
                    if '/' in part:
                        try:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        except (ValueError, ZeroDivisionError):
                            pass
                    else:
                        try:
                            total += float(part.replace(',', '.'))
                        except ValueError:
                            pass
                amount = str(int(total)) if total == int(total) else str(round(total, 4))
            else:
                amount = amount_str.replace(',', '.')

        # Clean unit
        unit_clean = unit.lower() if unit else None

        # Clean name: remove trailing preparation descriptions after comma
        name = re.sub(
            r',\s*(drobno\s+posiekana?|pokrojona?|posiekany?|starty?|roztopiony?|rozpuszczony?)',
            '', name, flags=re.IGNORECASE
        )
        name = self.clean_text(name).strip()

        if not name:
            return None

        return {"name": name, "amount": amount, "unit": unit_clean}

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        article = self._get_article()
        if not article:
            logger.warning("No <article> found in %s", self.html_path)
            return None

        ingredients = []

        # Find UL following a h2/h3 heading that contains "Składniki"
        for h in article.find_all(['h2', 'h3']):
            if 'składni' in h.get_text(strip=True).lower():
                sibling = h.find_next_sibling()
                if sibling and sibling.name == 'ul':
                    for li in sibling.find_all('li'):
                        text = li.get_text(separator=' ', strip=True)
                        text = self.clean_text(text)
                        if text and not text.endswith(':'):
                            parsed = self._parse_ingredient_line(text)
                            if parsed:
                                ingredients.append(parsed)
                    if ingredients:
                        break

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        article = self._get_article()
        if not article:
            logger.warning("No <article> found in %s", self.html_path)
            return None

        steps = []

        # Keywords that indicate preparation/instructions headings
        instruction_kw = ('krok', 'przygotow', 'sposób', 'sposob')

        for h in article.find_all(['h2', 'h3']):
            txt_lower = h.get_text(strip=True).lower()
            if any(kw in txt_lower for kw in instruction_kw):
                sibling = h.find_next_sibling()
                if sibling and sibling.name == 'ol':
                    for li in sibling.find_all('li'):
                        step_text = self.clean_text(li.get_text(separator=' ', strip=True))
                        if step_text:
                            steps.append(step_text)
                    if steps:
                        break

        if not steps:
            return None

        numbered = [f"{i}. {s}" for i, s in enumerate(steps, 1)]
        return ' '.join(numbered)

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из JSON-LD BlogPosting.articleSection"""
        blog_posting = self._get_json_ld_blog_posting()
        if blog_posting:
            section = blog_posting.get('articleSection')
            if section:
                return self.clean_text(str(section)) or None

        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content']) or None

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки (не представлено на сайте)"""
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления из текста инструкций"""
        article = self._get_article()
        if not article:
            return None

        def _parse_minutes(time_str: str) -> int:
            """Return the upper bound in minutes for a time string like '3-4 minuty' or '30 minut'."""
            # Range like "3-4"
            range_m = re.match(r'(\d+)[-–](\d+)', time_str)
            if range_m:
                return int(range_m.group(2))
            num_m = re.match(r'(\d+)', time_str)
            if num_m:
                return int(num_m.group(1))
            return 0

        def _find_max_time(text: str) -> Optional[str]:
            """Find the largest time value mentioned in *text*."""
            pattern = r'(\d+[-–]\d+\s+minut[a-z]*|\d+\s+minut[a-z]*)'
            matches = re.findall(pattern, text, re.IGNORECASE)
            if not matches:
                return None
            best = max(matches, key=_parse_minutes)
            best = re.sub(r'minut\w*', 'minutes', best.strip(), flags=re.IGNORECASE)
            return best

        # First try to find time within the instructions OL
        instruction_kw = ('krok', 'przygotow', 'sposób', 'sposob')
        for h in article.find_all(['h2', 'h3']):
            txt_lower = h.get_text(strip=True).lower()
            if any(kw in txt_lower for kw in instruction_kw):
                sibling = h.find_next_sibling()
                if sibling and sibling.name == 'ol':
                    result = _find_max_time(sibling.get_text())
                    if result:
                        return result

        # Fallback: search whole article text
        return _find_max_time(article.get_text())

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени (не представлено на сайте)"""
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и дополнительной информации"""
        article = self._get_article()
        if not article:
            return None

        # Keywords that indicate a notes/additional-info heading
        notes_kw = ('informacje dodatkow', 'dodatkowe informacj', 'dodatkow')
        fallback_kw = ('podsumow',)

        def _collect_text_after_heading(heading) -> str:
            """Collect text content from siblings until the next h2."""
            parts = []
            sibling = heading.find_next_sibling()
            while sibling and sibling.name != 'h2':
                if sibling.name == 'ul':
                    for li in sibling.find_all('li'):
                        li_text = self.clean_text(li.get_text(separator=' ', strip=True))
                        if li_text:
                            parts.append(li_text)
                elif sibling.name == 'p':
                    p_text = self.clean_text(sibling.get_text(separator=' ', strip=True))
                    if p_text:
                        parts.append(p_text)
                sibling = sibling.find_next_sibling()
            return ' '.join(parts)

        # Primary: "Informacje dodatkowe" / "Dodatkowe informacje"
        for h in article.find_all(['h2', 'h3']):
            txt_lower = h.get_text(strip=True).lower()
            if any(kw in txt_lower for kw in notes_kw):
                result = _collect_text_after_heading(h)
                if result:
                    return result

        # Fallback: "Podsumowanie" section
        for h in article.find_all(['h2', 'h3']):
            txt_lower = h.get_text(strip=True).lower()
            if any(kw in txt_lower for kw in fallback_kw):
                result = _collect_text_after_heading(h)
                if result:
                    return result

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD BlogPosting.keywords"""
        blog_posting = self._get_json_ld_blog_posting()
        if blog_posting:
            keywords = blog_posting.get('keywords')
            if keywords:
                if isinstance(keywords, list):
                    tags = [k.strip() for k in keywords if k.strip()]
                    return ', '.join(tags) if tags else None
                elif isinstance(keywords, str) and keywords.strip():
                    return keywords.strip()

        # Fallback: meta[name=keywords]
        meta_kw = self.soup.find('meta', {'name': 'keywords'})
        if meta_kw and meta_kw.get('content'):
            return self.clean_text(meta_kw['content']) or None

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls: list = []

        # 1. og:image (usually the main recipe image)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # 2. twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])

        # 3. Article images from vegeprzepis.pl/wp-content/uploads (uploaded media)
        article = self._get_article()
        if article:
            for img in article.find_all('img'):
                src = (img.get('src') or img.get('data-src')
                       or img.get('data-lazy-src') or '')
                if 'vegeprzepis.pl/wp-content/uploads' in src:
                    urls.append(src)

        # Deduplicate, preserve order
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


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "vegeprzepis_pl")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(VegeprzepisPlExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python vegeprzepis_pl.py")


if __name__ == "__main__":
    main()
