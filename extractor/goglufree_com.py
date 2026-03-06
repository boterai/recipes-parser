"""
Экстрактор данных рецептов для сайта goglufree.com
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

# Chinese numeral mapping
CHINESE_NUMERALS = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
    '半': 0.5,
}

# Keywords that indicate a process/instruction heading in pages content
PAGE_PROCESS_KEYWORDS = ['可以采用', '制作方法', '烹饪方法']

# Max number of machine/method names to include in page instructions
PAGE_INSTRUCTION_MAX_ITEMS = 8

# Regex pattern for extracting ingredient names from composition paragraphs.
# Matches common Chinese prefix-noun food items (天然X, 有机X) and specific
# key ingredients like 藜麦 that appear in product description text on this site.
COMPOSITION_INGREDIENT_PATTERN = re.compile(
    r'天然[\u4e00-\u9fff]{2}'
    r'|有机[\u4e00-\u9fff]{2}'
    r'|藜麦(?:面条粉|面粉)?'
)


class GogluFreeExtractor(BaseRecipeExtractor):
    """Экстрактор для goglufree.com"""

    def _get_main_content(self):
        """Возвращает основной контент страницы (fr-view или rte)"""
        content = self.soup.find('div', class_='fr-view')
        if not content:
            content = self.soup.find(class_='rte')
        return content

    def _get_content_lines(self) -> list[str]:
        """
        Извлекает все строки текста из основного контента,
        разбивая содержимое <p> по <br> тегам.
        """
        content = self._get_main_content()
        if not content:
            return []

        lines = []
        for p in content.find_all('p'):
            # Collect text segments separated by <br>
            segments = []
            current = []
            for child in p.children:
                if child.name == 'br':
                    seg = self.clean_text(''.join(c.get_text() if hasattr(c, 'get_text') else str(c)
                                                  for c in current))
                    if seg:
                        segments.append(seg)
                    current = []
                else:
                    current.append(child)

            # Last segment after final <br> (or whole paragraph if no <br>)
            seg = self.clean_text(''.join(c.get_text() if hasattr(c, 'get_text') else str(c)
                                          for c in current))
            if seg:
                segments.append(seg)

            lines.extend(segments)

        return lines

    def _is_ingredient_line(self, line: str) -> bool:
        """Проверяет, является ли строка записью ингредиента по формату 'name - amount unit'"""
        return bool(re.search(r'[-–]\s*[\d一二三四五六七八九十半]', line))

    def _is_step_line(self, line: str) -> bool:
        """Проверяет, является ли строка шагом приготовления"""
        return bool(re.match(r'^\d+[.\s。]', line))

    def _get_ld_json(self) -> Optional[dict]:
        """Извлекает данные LD+JSON (Article или Recipe)"""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, dict):
                    return data
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            return item
            except (json.JSONDecodeError, ValueError):
                continue
        return None

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Из LD+JSON headline
        ld = self._get_ld_json()
        if ld and ld.get('headline'):
            name = self.clean_text(ld['headline'])
            # Remove subtitle after dash (e.g., "无麸质小米香蕉面包-无蛋/无素蛋白")
            name = re.sub(r'\s*[-–]\s*无蛋.*$', '', name)
            name = re.sub(r'\s*[-–]\s*[无蛋无素].*$', '', name)
            return name if name else None

        # Из og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = self.clean_text(og_title['content'])
            # Remove English subtitle like "/ Goglufree ..."
            title = re.sub(r'\s*/\s*Goglufree.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*[-–]\s*[无].*$', '', title)
            return title if title else None

        # Из заголовка страницы (h1)
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта из первого вводного параграфа"""
        lines = self._get_content_lines()
        if not lines:
            return None

        dish_name = self.extract_dish_name()
        for line in lines:
            # Stop at ingredient lines
            if self._is_ingredient_line(line):
                break
            # Stop at step markers
            if self._is_step_line(line) or re.match(r'^步骤[：:。]?$', line):
                break
            # Skip very short lines
            if len(line) < 5:
                continue
            # Skip section headers (ending with ：or :)
            if line.rstrip().endswith('：') or line.rstrip().endswith(':'):
                continue
            # Skip announcement-style lines (新食谱报到 etc.)
            if re.match(r'^新食谱报到', line):
                continue
            # Skip lines that are mostly the dish title
            if dish_name and (
                line.strip('！!') == dish_name
                or (dish_name in line and len(line) < len(dish_name) + 20)
            ):
                continue
            return line

        return None

    def parse_ingredient_line(self, line: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в формате 'название - количество единица'

        Примеры:
            "小米面包粉 - 1 包（含酵母）" → {"name": "小米面包粉", "amount": 1, "unit": "包"}
            "温水- 200g" → {"name": "温水", "amount": 200, "unit": "g"}
            "酵母 - 一小包" → {"name": "酵母", "amount": 1, "unit": "小包"}
        """
        if not line:
            return None

        line = self.clean_text(line)

        # Pattern: "name - amount unit" or "name- amount unit"
        match = re.match(
            r'^(.+?)\s*[-–]\s*'
            r'([一二三四五六七八九十半][\d./]*|[\d]+(?:[./\-][\d]+)?)\s*'
            r'([a-zA-Z\u4e00-\u9fff]+(?:[\s\u4e00-\u9fff]*[a-zA-Z\u4e00-\u9fff]+)?)'
            r'(?:\s*[（(][^）)]*[）)])?'
            r'\s*$',
            line
        )

        if not match:
            return None

        name, amount_str, unit = match.groups()
        name = self.clean_text(re.sub(r'\s*[（(][^）)]*[）)]\s*$', '', name))

        # Convert amount
        amount = None
        if amount_str:
            if amount_str in CHINESE_NUMERALS:
                amount = CHINESE_NUMERALS[amount_str]
            else:
                try:
                    amount = int(amount_str)
                except ValueError:
                    try:
                        amount = float(amount_str)
                    except ValueError:
                        amount = amount_str

        unit = self.clean_text(unit) if unit else None

        if not name or len(name) < 1:
            return None

        return {"name": name, "amount": amount, "unit": unit}

    def _extract_composition_ingredients(self, lines: list[str]) -> list[dict]:
        """
        Извлечение ингредиентов из абзаца, описывающего состав продукта.
        Используется как запасной метод, когда структурированный список ингредиентов
        недоступен. Ищет упоминания типа '天然糙米', '有机荞麦', '藜麦' в тексте.
        Ищет первый абзац, в котором COMPOSITION_INGREDIENT_PATTERN находит
        хотя бы 2 совпадения (признак перечисления состава).
        """
        for line in lines:
            matches = COMPOSITION_INGREDIENT_PATTERN.findall(line)
            if len(matches) < 2:
                # Not a composition paragraph — too few ingredients mentioned
                continue
            seen: set[str] = set()
            result = []
            for item in matches:
                # Remove parenthetical annotations e.g. "藜麦（Quinoa）"
                item = re.sub(r'\s*[（(][^）)]*[）)]\s*', '', item).strip()
                if item and item not in seen:
                    seen.add(item)
                    result.append({"name": item, "amount": None, "unit": None})
            if result:
                return result
        return []
        return []

    def _extract_page_instructions(self) -> Optional[str]:
        """
        Извлечение инструкций для страниц-продуктов, где способы приготовления
        представлены в виде перечня методов/машин после вводного заголовка.
        Например: '藜麦面条可以采用几种机器来进行制: 《谷留香》无线手持制面机, ...'
        """
        content = self._get_main_content()
        if not content:
            return None

        process_keywords = PAGE_PROCESS_KEYWORDS

        for p in content.find_all('p'):
            text = p.get_text(strip=True)
            if not any(kw in text for kw in process_keywords):
                continue
            if len(text) > 120:
                continue

            # Found the heading — collect machine/method names from subsequent headline paragraphs
            heading = re.sub(r'[：:]\s*$', '', text)
            machine_names = []

            sibling = p.find_next_sibling('p')
            while sibling and len(machine_names) < PAGE_INSTRUCTION_MAX_ITEMS:
                sib_text = sibling.get_text(strip=True)
                sib_itemprop = sibling.get('itemprop', '')

                if not sib_text:
                    sibling = sibling.find_next_sibling('p')
                    continue

                # Skip navigation / "still in progress" lines
                if '中文' in sib_text or '👈' in sib_text or 'still in progress' in sib_text.lower():
                    sibling = sibling.find_next_sibling('p')
                    continue

                # Only collect headline paragraphs that contain Chinese text
                if (sib_itemprop == 'headline'
                        and re.search(r'[\u4e00-\u9fff]', sib_text)
                        and len(sib_text) <= 80):
                    # Keep the Chinese portion (before "/" in bilingual headings)
                    chinese_part = self.clean_text(sib_text.split('/')[0])
                    if chinese_part and len(chinese_part) >= 3:
                        machine_names.append(chinese_part)

                sibling = sibling.find_next_sibling('p')

            if machine_names:
                return heading + ': ' + ', '.join(machine_names)
            return heading + '。'

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        lines = self._get_content_lines()
        if not lines:
            return None

        ingredients = []
        in_ingredients = False

        for line in lines:
            # Skip step lines and note lines
            if self._is_step_line(line) or line.startswith('步骤'):
                break

            # Detect ingredient lines by pattern
            if self._is_ingredient_line(line):
                in_ingredients = True
                parsed = self.parse_ingredient_line(line)
                if parsed:
                    ingredients.append(parsed)
            elif in_ingredients and (line.endswith('：') or line.endswith(':')):
                # Section headers like "ENO效果材料：" - continue collecting
                continue

        if not ingredients:
            # Fallback: extract from composition description paragraph
            ingredients = self._extract_composition_ingredients(lines)

        if not ingredients:
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        lines = self._get_content_lines()
        if not lines:
            return None

        steps = []
        in_steps = False

        for line in lines:
            if line.strip('：:') == '步骤' or line == '步骤：' or line == '步骤:':
                in_steps = True
                continue

            if in_steps and self._is_step_line(line):
                steps.append(line)

        if steps:
            return ' '.join(steps)

        # For pages without numbered steps, look for a process description with machine/method list
        return self._extract_page_instructions()

    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # goglufree.com does not expose category in a structured way
        # Try to extract from meta article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])

        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки (приоритет - время выпечки в духовке)"""
        lines = self._get_content_lines()
        if not lines:
            return None

        # Oven/baking keywords in Chinese
        oven_keywords = ['放入烤炉', '放入烤箱', '烘烤', '烤至', '放进烤']
        time_range_pattern = r'(\d+)[-–](\d+)\s*分钟'
        time_single_pattern = r'(\d+)\s*分钟'

        candidates = []

        # First pass: look for time near strong oven keywords (放入烤炉/烤箱, 烘烤)
        for line in lines:
            if any(kw in line for kw in oven_keywords):
                # Find all range times in this line
                for m in re.finditer(time_range_pattern, line):
                    low, high = int(m.group(1)), int(m.group(2))
                    candidates.append((low, high, m.group(0)))
                if not candidates:
                    for m in re.finditer(time_single_pattern, line):
                        val = int(m.group(1))
                        candidates.append((val, val, m.group(0)))

        if candidates:
            # Take the one with the largest maximum time
            best = max(candidates, key=lambda x: x[1])
            raw = best[2]
            result = re.sub(r'\s*分钟$', ' minutes', raw)
            return self.clean_text(result)

        # Second pass: look for any cooking time range in all lines
        for line in lines:
            for m in re.finditer(time_range_pattern, line):
                low, high = int(m.group(1)), int(m.group(2))
                candidates.append((low, high, m.group(0)))

        if candidates:
            best = max(candidates, key=lambda x: x[1])
            raw = best[2]
            result = re.sub(r'\s*分钟$', ' minutes', raw)
            return self.clean_text(result)

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        lines = self._get_content_lines()
        notes_parts = []
        for line in lines:
            if line.startswith('建议：') or line.startswith('建议:'):
                note = self.clean_text(line[3:])
                if note:
                    notes_parts.append(note)

        if notes_parts:
            return ' '.join(notes_parts)

        # For pages without explicit "建议：" prefix, look for usage notes
        # e.g., "此面粉可制作：手工面条/板面、乌冬面、饺子皮等等。"
        usage_keywords = ['可制作', '可以用来', '可用于']
        for line in lines:
            if any(kw in line for kw in usage_keywords):
                # Take only the first sentence (up to first 。)
                first_sentence = re.split(r'。', line)[0]
                # Remove the first colon/colon separator
                text = re.sub(r'[：:]\s*', '', first_sentence, count=1)
                # Normalize "等等" → "等" and add period
                text = re.sub(r'等等\s*$', '等', text)
                # Remove trailing single CJK characters that got mixed in (line break artefacts)
                text = re.sub(r'\s+[\u4e00-\u9fff]\s*$', '', text)
                text = self.clean_text(text)
                if text and len(text) > 3:
                    return text + '。'

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Try keywords meta tag
        keywords = self.soup.find('meta', {'name': 'keywords'})
        if keywords and keywords.get('content'):
            tags = [t.strip() for t in keywords['content'].split(',') if t.strip()]
            if tags:
                return ', '.join(tags)

        # Try article:tag meta tags
        article_tags = self.soup.find_all('meta', property='article:tag')
        if article_tags:
            tags = [t.get('content', '').strip() for t in article_tags if t.get('content')]
            if tags:
                return ', '.join(tags)

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls = []
        seen = set()

        # From LD+JSON (article image)
        ld = self._get_ld_json()
        if ld:
            images = ld.get('image', [])
            if isinstance(images, str):
                images = [images]
            for img_url in images:
                if isinstance(img_url, str) and img_url not in seen:
                    urls.append(img_url)
                    seen.add(img_url)

        # OG image (if not the same as logo)
        og_img = self.soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            img_url = og_img['content']
            if img_url not in seen:
                urls.append(img_url)
                seen.add(img_url)

        # Images inside main content
        content = self._get_main_content()
        if content:
            from urllib.parse import urlparse
            for img in content.find_all('img'):
                src = img.get('src')
                if src and src.startswith('http') and src not in seen:
                    # Only include images from the store-assets CDN domain
                    try:
                        host = urlparse(src).hostname or ''
                    except Exception:
                        host = ''
                    if host == 'cdn.store-assets.com':
                        urls.append(src)
                        seen.add(src)

        if not urls:
            return None

        return ','.join(urls)

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта

        Returns:
            Словарь с данными рецепта
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception as e:
            logger.warning("Ошибка извлечения dish_name: %s", e)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as e:
            logger.warning("Ошибка извлечения description: %s", e)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as e:
            logger.warning("Ошибка извлечения ingredients: %s", e)
            ingredients = None

        try:
            instructions = self.extract_steps()
        except Exception as e:
            logger.warning("Ошибка извлечения instructions: %s", e)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as e:
            logger.warning("Ошибка извлечения category: %s", e)
            category = None

        try:
            notes = self.extract_notes()
        except Exception as e:
            logger.warning("Ошибка извлечения notes: %s", e)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as e:
            logger.warning("Ошибка извлечения tags: %s", e)
            tags = None

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
            "tags": tags,
            "image_urls": self.extract_image_urls(),
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "goglufree_com")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(GogluFreeExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python goglufree_com.py")


if __name__ == "__main__":
    main()
