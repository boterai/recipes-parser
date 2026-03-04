"""
Экстрактор данных рецептов для сайта pomalyhrnec.blogspot.com
"""

import sys
import logging
from pathlib import Path
import json
import re
from typing import Optional
from urllib.parse import urlparse
from bs4 import NavigableString

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class PomalyhrnecBlogspotComExtractor(BaseRecipeExtractor):
    """Экстрактор для pomalyhrnec.blogspot.com"""

    def _get_post_body(self):
        """Получение основного блока контента поста."""
        return self.soup.find('div', class_=re.compile(r'post-body'))

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда."""
        title_tag = self.soup.find('h3', class_=re.compile(r'post-title'))
        if title_tag:
            return self.clean_text(title_tag.get_text())

        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта."""
        post_body = self._get_post_body()
        if not post_body:
            return None

        # Стиль рецепта 2: <p style="text-align: justify;">
        p_justify = post_body.find('p', style=re.compile(r'justify', re.I))
        if p_justify:
            return self.clean_text(p_justify.get_text(separator=' '))

        # Стиль рецепта 1: span с justify внутри первого MsoNormal div
        first_mso = post_body.find('div', class_='MsoNormal')
        if first_mso:
            span = first_mso.find('span', style=re.compile(r'justify', re.I))
            if span:
                return self.clean_text(span.get_text())

        # Стиль рецепта 3: первый div с justify-стилем (не MsoNormal)
        for div in post_body.find_all('div', style=re.compile(r'justify', re.I)):
            classes = div.get('class', []) or []
            if 'MsoNormal' not in classes:
                text = self.clean_text(div.get_text(separator=' '))
                if text and not text.lower().startswith('doporučení'):
                    return text

        return None

    def _parse_ingredient(self, line: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат.

        Args:
            line: строка вида "800g hovězího masa" или "3 lžičky sladké papriky"

        Returns:
            dict с полями name, amount, unit или None
        """
        if not line:
            return None

        line = self.clean_text(line)

        # Пропускаем строки заметок и служебные строки
        if line.startswith('-') or line.lower().startswith('doporučení'):
            return None
        if 'POSTUP' in line.upper():
            return None

        # Строки вида "(masox) - není nutné..." — извлекаем имя из скобок
        paren_match = re.match(r'^\(([^)]+)\)', line)
        if paren_match:
            return {"name": paren_match.group(1), "amount": None, "unit": None}

        czech_units = (
            r'(?:g|kg|ml|dl|l|lžíce?|lžičky?|špetky?|stroužky?|hrnk(?:y|ů)?|ks|'
            r'svazk(?:y|ů)?|plátk(?:y|ů)?|kus(?:y|ů)?)'
        )

        # Шаблон 1: число + единица без пробела + имя  ("800g hovězího masa")
        m = re.match(
            r'^([\d,./]+(?:-[\d,./]+)?)\s*(' + czech_units + r')\s+(.+)$',
            line, re.I
        )
        if m:
            return self._build_ingredient(m.group(1), m.group(2), m.group(3))

        # Шаблон 2: число + пробел + единица + пробел + имя ("3 lžičky sladké papriky")
        m = re.match(
            r'^([\d,./]+(?:-[\d,./]+)?)\s+(' + czech_units + r')\s+(.+)$',
            line, re.I
        )
        if m:
            return self._build_ingredient(m.group(1), m.group(2), m.group(3))

        # Шаблон 3: число + пробел + описатель + пробел + имя ("4 menší cibule")
        m = re.match(r'^([\d,./]+(?:-[\d,./]+)?)\s+(\w+)\s+(.+)$', line, re.I)
        if m and len(m.group(2)) <= 12:
            return self._build_ingredient(m.group(1), m.group(2), m.group(3))

        # Шаблон 4: число + пробел + имя ("4-5 cibulí")
        m = re.match(r'^([\d,./]+(?:-[\d,./]+)?)\s+(.+)$', line, re.I)
        if m:
            return self._build_ingredient(m.group(1), None, m.group(2))

        # Шаблон 5: только имя ("hladká mouka", "sůl")
        return {"name": line, "amount": None, "unit": None}

    def _build_ingredient(
        self, amount_str: str, unit: Optional[str], name: str
    ) -> Optional[dict]:
        """Создание словаря ингредиента с нормализованным количеством."""
        # Обрабатываем количество
        amount = None
        if amount_str:
            amount_str = amount_str.strip().replace(',', '.')
            if '-' in amount_str and not amount_str.startswith('-'):
                amount = amount_str  # Диапазон оставляем строкой
            elif '/' in amount_str:
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
                            total += float(part)
                        except ValueError:
                            pass
                amount = int(total) if total == int(total) else total if total > 0 else None
            else:
                try:
                    val = float(amount_str)
                    amount = int(val) if val == int(val) else val
                except ValueError:
                    amount = None

        # Очищаем имя ингредиента
        name = re.sub(r'\([^)]*\)', '', name)
        name = re.sub(r'\s+jako\s+příloha\s*$', '', name, flags=re.I)
        name = re.sub(r'\s+', ' ', name).strip()

        if not name or len(name) < 2:
            return None

        return {"name": name, "amount": amount, "unit": unit}

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов."""
        post_body = self._get_post_body()
        if not post_body:
            return None

        lines: list[str] = []

        # Подход 1: <p style="text-align: left;"> (стиль рецепта 2)
        p_left = post_body.find('p', style=re.compile(r'text-align:\s*left', re.I))
        if p_left:
            for content in p_left.contents:
                if isinstance(content, NavigableString):
                    text = content.strip()
                    if text:
                        lines.extend(text.split('\n'))

        # Подход 2: дивы MsoNormal (стиль рецепта 1)
        if not lines:
            mso_divs = post_body.find_all('div', class_='MsoNormal')
            if mso_divs:
                instr_div = post_body.find(
                    'div', class_='MsoNormal', style=re.compile(r'justify', re.I)
                )
                first_mso = mso_divs[0]

                # Текстовые узлы в первом div (первый ингредиент)
                for content in first_mso.contents:
                    if isinstance(content, NavigableString):
                        text = content.strip()
                        if text:
                            lines.append(text)

                # Последующие MsoNormal-дивы (до блока инструкций)
                for div in mso_divs[1:]:
                    if instr_div and div is instr_div:
                        break
                    style = div.get('style', '') or ''
                    if 'justify' in style.lower():
                        break
                    text = div.get_text(strip=True)
                    if text and not text.lower().startswith('doporučení'):
                        lines.append(text)

        # Подход 3: текстовый анализ (стиль рецепта 3 и запасной вариант)
        if not lines:
            all_text_lines = [
                l.strip()
                for l in post_body.get_text(separator='\n').split('\n')
                if l.strip()
            ]
            notes_start = next(
                (i for i, l in enumerate(all_text_lines) if l.lower().startswith('doporučení')),
                None
            )
            content_lines = all_text_lines[:notes_start] if notes_start is not None else all_text_lines

            # Находим последнюю длинную строку (инструкции)
            instr_idx = next(
                (i for i in range(len(content_lines) - 1, -1, -1) if len(content_lines[i]) > 100),
                None
            )
            if instr_idx is not None:
                pre_instr = content_lines[:instr_idx]
                # Собираем ингредиенты: с первой строки, начинающейся с цифры
                first_digit_idx = next(
                    (i for i, l in enumerate(pre_instr) if re.match(r'^\d', l)),
                    None
                )
                if first_digit_idx is not None:
                    for line in pre_instr[first_digit_idx:]:
                        if len(line) <= 80:
                            lines.append(line)

        # Парсим строки ингредиентов
        ingredients = []
        for line in lines:
            for part in line.split('\n'):
                part = part.strip()
                if part:
                    try:
                        parsed = self._parse_ingredient(part)
                        if parsed and len(parsed.get('name', '')) >= 2:
                            ingredients.append(parsed)
                    except Exception as exc:
                        logger.warning("Не удалось разобрать ингредиент %r: %s", part, exc)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению."""
        post_body = self._get_post_body()
        if not post_body:
            return None

        # Стиль рецепта 1: MsoNormal с justify
        instr_div = post_body.find(
            'div', class_='MsoNormal', style=re.compile(r'justify', re.I)
        )
        if instr_div:
            text = self.clean_text(instr_div.get_text(separator=' '))
            if text and not text.lower().startswith('doporučení') and len(text) > 50:
                return text

        # Стили рецептов 2/3: последний длинный justify-div перед "Doporučení:"
        justify_divs = post_body.find_all('div', style=re.compile(r'justify', re.I))
        for div in reversed(justify_divs):
            text = self.clean_text(div.get_text(separator=' '))
            if (
                text
                and len(text) > 100
                and not text.lower().startswith('doporučení')
                and not text.lower().startswith('update')
                and 'POSTUP' not in text.upper()[:30]
            ):
                return text

        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов (секция «Doporučení:»)."""
        post_body = self._get_post_body()
        if not post_body:
            return None

        lines = [
            l.strip()
            for l in post_body.get_text(separator='\n').split('\n')
            if l.strip()
        ]

        notes_start = next(
            (i for i, l in enumerate(lines) if l.lower().startswith('doporučení')),
            None
        )
        if notes_start is None:
            return None

        postup_idx = next(
            (i for i in range(notes_start + 1, len(lines)) if 'POSTUP PŘÍPRAVY' in lines[i].upper()),
            None
        )

        notes_lines = lines[notes_start + 1 : postup_idx]
        if not notes_lines:
            return None

        parts = []
        for line in notes_lines:
            if not line or line == '-':
                continue
            if line.startswith('-'):
                line = line[1:].strip()
            if line:
                parts.append(line)

        return '. '.join(parts) if parts else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории — по умолчанию Main Course для этого сайта."""
        return "Main Course"

    def extract_cook_time(self) -> Optional[str]:
        """
        Извлечение времени приготовления из текста инструкций.
        Ищет паттерны вида «na X-Yh» или «na X h».
        """
        instructions = self.extract_steps()
        if not instructions:
            return None

        # Ищем паттерны типа "na 8-10h", "na 6-7h", "na 9 h", "na 5-6 h"
        time_pattern = r'na\s+([\d]+(?:[,-][\d]+)?)\s*h(?:odin)?'
        all_values: list[float] = []
        for match in re.finditer(time_pattern, instructions.lower()):
            time_str = match.group(1)
            if '-' in time_str:
                for part in time_str.split('-'):
                    try:
                        all_values.append(float(part))
                    except ValueError:
                        pass
            else:
                try:
                    all_values.append(float(time_str))
                except ValueError:
                    pass

        if not all_values:
            return None

        min_t = min(all_values)
        max_t = max(all_values)
        min_s = str(int(min_t)) if min_t == int(min_t) else str(min_t)
        max_s = str(int(max_t)) if max_t == int(max_t) else str(max_t)

        return f"{min_s} hours" if min_t == max_t else f"{min_s}-{max_s} hours"

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки."""
        instructions = self.extract_steps()
        if not instructions:
            return None

        if 'přes noc' in instructions.lower() or 'celý den' in instructions.lower():
            return 'overnight'

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из меток блога (<a rel='tag'>)."""
        labels = self.soup.find_all('a', rel='tag')
        if not labels:
            return None

        seen: set[str] = set()
        tags: list[str] = []
        for label in labels:
            text = self.clean_text(label.get_text())
            if text and text not in seen:
                seen.add(text)
                tags.append(text)

        return ', '.join(tags) if tags else None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта."""
        urls: list[str] = []

        # 1. og:image мета-тег
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # 2. JSON-LD
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, dict) and 'image' in data:
                    img = data['image']
                    if isinstance(img, dict) and 'url' in img:
                        if img['url'] not in urls:
                            urls.append(img['url'])
                    elif isinstance(img, str) and img not in urls:
                        urls.append(img)
            except (json.JSONDecodeError, KeyError, AttributeError) as exc:
                logger.debug("Ошибка при разборе JSON-LD: %s", exc)

        # 3. Ссылки на изображения в теле поста (Blogger-ссылки высокого разрешения)
        _image_host = 'blogger.googleusercontent.com'
        post_body = self._get_post_body()
        if post_body:
            for a_tag in post_body.find_all('a', href=True):
                href = a_tag['href']
                try:
                    parsed_href = urlparse(href)
                    netloc = parsed_href.netloc
                    if (
                        (netloc == _image_host or netloc.endswith('.' + _image_host))
                        and href not in urls
                    ):
                        urls.append(href)
                except Exception:  # pragma: no cover
                    pass

        if not urls:
            return None

        seen: set[str] = set()
        unique_urls: list[str] = []
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
        try:
            dish_name = self.extract_dish_name()
        except Exception as exc:
            logger.warning("Ошибка при извлечении dish_name: %s", exc)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as exc:
            logger.warning("Ошибка при извлечении description: %s", exc)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as exc:
            logger.warning("Ошибка при извлечении ingredients: %s", exc)
            ingredients = None

        try:
            instructions = self.extract_steps()
        except Exception as exc:
            logger.warning("Ошибка при извлечении instructions: %s", exc)
            instructions = None

        try:
            notes = self.extract_notes()
        except Exception as exc:
            logger.warning("Ошибка при извлечении notes: %s", exc)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as exc:
            logger.warning("Ошибка при извлечении tags: %s", exc)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as exc:
            logger.warning("Ошибка при извлечении image_urls: %s", exc)
            image_urls = None

        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time() if instructions else None,
            "cook_time": self.extract_cook_time() if instructions else None,
            "total_time": None,
            "notes": notes,
            "tags": tags,
            "image_urls": image_urls,
        }


def main():
    import os
    repo_root = Path(__file__).parent.parent
    preprocessed_dir = repo_root / "preprocessed" / "pomalyhrnec_blogspot_com"

    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        process_directory(PomalyhrnecBlogspotComExtractor, str(preprocessed_dir))
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python pomalyhrnec_blogspot_com.py")


if __name__ == "__main__":
    main()
