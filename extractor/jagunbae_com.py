"""
Экстрактор данных рецептов для сайта jagunbae.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class JagunbaeComExtractor(BaseRecipeExtractor):
    """Экстрактор для jagunbae.com (Ghost CMS, Korean recipe blog)"""

    def _get_content_div(self):
        """Получение основного контентного блока статьи"""
        return self.soup.find(class_='gh-content')

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Primary: <h1 class="gh-article-title">
        h1 = self.soup.find('h1', class_='gh-article-title')
        if h1:
            name = self.clean_text(h1.get_text())
            # Strip " 레시피" (recipe) suffix common on jagunbae.com titles
            name = re.sub(r'\s*레시피\s*$', '', name).strip()
            return name if name else None

        # Fallback: og:title meta tag
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = self.clean_text(og_title['content'])
            title = re.sub(r'\s*레시피\s*$', '', title).strip()
            return title if title else None

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Primary: article excerpt element (Ghost CMS)
        excerpt = self.soup.find(class_='gh-article-excerpt')
        if excerpt:
            text = self.clean_text(excerpt.get_text())
            if text:
                return text

        # Fallback: first paragraph in article content
        content_div = self._get_content_div()
        if content_div:
            first_p = content_div.find('p')
            if first_p:
                text = self.clean_text(first_p.get_text())
                if text:
                    return text

        # Final fallback: meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        return None

    def _parse_korean_ingredient(self, text: str) -> Optional[dict]:
        """
        Парсинг корейского текста ингредиента в структурированный формат.

        Корейский формат: "название количество единица"
        Примеры:
            "무가당 두유 220g" -> {"name": "무가당 두유", "amount": "220", "unit": "g"}
            "아몬드 1/4 cup (40g)" -> {"name": "아몬드", "amount": "1/4", "unit": "cup"}
            "파프리카 1개" -> {"name": "파프리카", "amount": "1", "unit": "개"}
        """
        if not text:
            return None

        # Remove parenthetical content like "(175~180g)"
        clean = re.sub(r'\([^)]*\)', '', text).strip()
        if not clean:
            return None

        # Pattern: name (1+words) + amount (number, optionally fraction) + unit (word/word group)
        # Handles both attached unit "220g" and spaced unit "1/4 cup"
        pattern = (
            r'^(.+?)\s+'
            r'((?:\d+\s+)?\d+(?:/\d+)?(?:\.\d+)?)\s*'
            r'([가-힣a-zA-Z]+(?:\s+[가-힣a-zA-Z]+)?)$'
        )
        match = re.match(pattern, clean, re.UNICODE)
        if match:
            name = self.clean_text(match.group(1))
            amount = match.group(2).strip()
            unit = match.group(3).strip()
            return {"name": name, "amount": amount, "unit": unit}

        # No amount/unit found — return just the name
        return {
            "name": self.clean_text(clean),
            "amount": None,
            "unit": None,
        }

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из секции 재료"""
        content_div = self._get_content_div()
        if not content_div:
            return None

        # Find any heading (h2/h3/h4) containing 재료 (ingredients)
        for heading in content_div.find_all(['h2', 'h3', 'h4']):
            if '재료' not in heading.get_text(strip=True):
                continue

            # Walk siblings until the next same-or-higher-level heading
            heading_level = int(heading.name[1])
            next_elem = heading.find_next_sibling()
            while next_elem:
                sibling_level = (
                    int(next_elem.name[1])
                    if next_elem.name and re.match(r'^h[1-6]$', next_elem.name)
                    else None
                )
                if sibling_level is not None and sibling_level <= heading_level:
                    break

                if next_elem.name == 'ul':
                    ingredients = []
                    for li in next_elem.find_all('li'):
                        item_text = self.clean_text(li.get_text(separator=' '))
                        if item_text:
                            parsed = self._parse_korean_ingredient(item_text)
                            if parsed:
                                ingredients.append(parsed)
                    if ingredients:
                        return json.dumps(ingredients, ensure_ascii=False)
                    break  # ul found but empty — stop looking

                next_elem = next_elem.find_next_sibling()

            # Return None if the first 재료 heading yields nothing
            return None

        return None

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления из секции 순서 или kg-product-card"""
        content_div = self._get_content_div()
        if not content_div:
            return None

        # Primary: find 순서 heading and collect figure captions (step-by-step photos)
        for heading in content_div.find_all(['h2', 'h3', 'h4']):
            if '순서' not in heading.get_text(strip=True):
                continue

            heading_level = int(heading.name[1])
            steps = []
            next_elem = heading.find_next_sibling()
            while next_elem:
                sibling_level = (
                    int(next_elem.name[1])
                    if next_elem.name and re.match(r'^h[1-6]$', next_elem.name)
                    else None
                )
                if sibling_level is not None and sibling_level <= heading_level:
                    break

                elem_classes = next_elem.get('class', [])
                if 'kg-image-card' in elem_classes and 'kg-card-hascaption' in elem_classes:
                    figcap = next_elem.find('figcaption')
                    if figcap:
                        step_text = self.clean_text(figcap.get_text())
                        if step_text:
                            steps.append(step_text)

                next_elem = next_elem.find_next_sibling()

            if steps:
                return '\n'.join(f"{i}. {step}" for i, step in enumerate(steps, 1))
            break  # heading found but no captions

        # Fallback: kg-product-card ordered list (compact summary steps)
        product_card = self.soup.find(class_='kg-product-card')
        if product_card:
            desc_div = product_card.find(class_='kg-product-card-description')
            if desc_div:
                step_items = desc_div.find_all('li')
                if step_items:
                    steps = [self.clean_text(li.get_text(separator=' ')) for li in step_items]
                    steps = [s for s in steps if s]
                    if steps:
                        return '\n'.join(f"{i}. {step}" for i, step in enumerate(steps, 1))

        return None

    def extract_category(self) -> Optional[str]:
        """Категория — не предоставляется на jagunbae.com"""
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки — не предоставляется на jagunbae.com"""
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Время готовки — не предоставляется на jagunbae.com"""
        return None

    def extract_total_time(self) -> Optional[str]:
        """Общее время — не предоставляется на jagunbae.com"""
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок из toggle-блока или Q&A секции"""
        # Primary: Ghost CMS toggle card (optional/extra ingredients section)
        toggle_card = self.soup.find(class_='kg-toggle-card')
        if toggle_card:
            toggle_content = toggle_card.find(class_='kg-toggle-content')
            if toggle_content:
                # Process each list item with empty separator to avoid
                # spurious spaces between bold spans and adjacent particles
                items = toggle_content.find_all('li')
                if items:
                    parts = []
                    for li in items:
                        item_text = self.clean_text(li.get_text(separator=''))
                        if item_text:
                            parts.append(item_text)
                    text = ' '.join(parts)
                else:
                    text = self.clean_text(toggle_content.get_text(separator=''))
                if text:
                    return text

        # Fallback: Q&A section
        content_div = self._get_content_div()
        if content_div:
            for heading in content_div.find_all(['h2', 'h3', 'h4']):
                heading_text = heading.get_text(strip=True)
                if 'Q' in heading_text and 'A' in heading_text:
                    heading_level = int(heading.name[1])
                    parts = []
                    next_elem = heading.find_next_sibling()
                    while next_elem:
                        sibling_level = (
                            int(next_elem.name[1])
                            if next_elem.name and re.match(r'^h[1-6]$', next_elem.name)
                            else None
                        )
                        if sibling_level is not None and sibling_level <= heading_level:
                            break
                        # Process each li to keep questions and answers readable
                        items = next_elem.find_all('li')
                        if items:
                            for li in items:
                                item_text = self.clean_text(li.get_text(separator=' '))
                                if item_text:
                                    parts.append(item_text)
                        else:
                            text = self.clean_text(next_elem.get_text(separator=' '))
                            if text:
                                parts.append(text)
                        next_elem = next_elem.find_next_sibling()
                    if parts:
                        return ' '.join(parts)

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из мета-тегов article:tag"""
        tags = [
            m.get('content')
            for m in self.soup.find_all('meta', property='article:tag')
            if m.get('content')
        ]
        return ', '.join(tags) if tags else None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls = []
        seen: set = set()

        def _add(url: str) -> None:
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        # Primary: og:image (main recipe photo)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            _add(og_image['content'])

        # Additional: absolute-URL images inside the article content
        content_div = self._get_content_div()
        if content_div:
            for img in content_div.find_all('img'):
                src = img.get('src') or img.get('data-src') or ''
                if src.startswith('http'):
                    _add(src)

        return ','.join(urls) if urls else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта в едином формате проекта.
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
    import os
    recipes_dir = os.path.join("preprocessed", "jagunbae_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(JagunbaeComExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python jagunbae_com.py [путь_к_директории]")


if __name__ == "__main__":
    main()
