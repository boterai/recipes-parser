"""
Экстрактор данных рецептов для сайта adamfaliq.com
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class AdamfaliqComExtractor(BaseRecipeExtractor):
    """Экстрактор для adamfaliq.com (WordPress-блог с рецептами)"""

    # Ключевые слова заголовков секции ингредиентов (многоязычные)
    _INGREDIENT_SECTION_KEYWORDS = re.compile(
        r'ingredient|ingredi[eë]nt|složen|zutaten|ingrédient|ingrediente',
        re.IGNORECASE,
    )

    # Ключевые слова заголовков секции инструкций (многоязычные)
    _INSTRUCTION_SECTION_KEYWORDS = re.compile(
        r'instruct|anleitung|návod|directive|instruccion|steps|preparation|'
        r'method|bereiding|bereien|stap',
        re.IGNORECASE,
    )

    # Единицы измерения — расширенный список (включая нидерландские/немецкие)
    _UNITS = re.compile(
        r'\b(cups?|cup|kopjes?|kopje|tassen?|tasse|šálky?|šálek'
        r'|tablespoons?|tbsps?|eetlepels?|eetlepel|esslöffels?|esslöffel'
        r'|polévkov[aá]\s+lžíce|polévková\s+lžíce'
        r'|teaspoons?|tsps?|theelepels?|theelepel|teelöffels?|teelöffel|lžička|lžičky'
        r'|pounds?|lbs?'
        r'|ounces?|oz'
        r'|grams?|gramms?|gr?\b'
        r'|kilograms?|kg'
        r'|milliliters?|millilitres?|ml'
        r'|liters?|litres?|l\b'
        r'|teentjes?|teentje|strouž[ek]+'  # cloves (Dutch/Czech)
        r'|stukk?s?|stück|ks\b'            # pieces
        r'|handf?ul|handvol'
        r'|pinch(?:es)?|snufje|snufjes'
        r'|dash(?:es)?'
        r'|packages?|pakk?etje'
        r'|cans?|blikje|blikjes'
        r'|slices?|plakjes?|plakje'
        r'|sprigs?|takje|takjes'
        r'|bunches?|bosje|bosjes'
        r'|heads?|kop|köpfe'
        r'|unzen?|unze'                    # ounces (German)
        r')\b',
        re.IGNORECASE,
    )

    # Фразы, которые следует удалять из названия ингредиента
    _STRIP_FROM_NAME = re.compile(
        r'\b(naar\s+smaak|to\s+taste|nach\s+geschmack|dle\s+chuti'
        r'|as\s+needed|if\s+needed|optional'
        r'|for\s+garnish|zum\s+garnieren'
        r')\b',
        re.IGNORECASE,
    )

    # Фразы, обозначающие способ подготовки (всё после запятой или таких слов)
    _PREP_AFTER_COMMA = re.compile(
        r',\s*(in\s+blokjes|in\s+würfel|nakrájen(?:é|ím)?\s+na\s+\S+|in\s+cubes?'
        r'|in\s+würfel\s+geschnitten'
        r'|gekookt[e]?\s+(?:en\s+)?uitgelekt|gedroogd[e]?'
        r'|ontdarmd|deveined|sauber|uitgelekt|abgetropft|schoon'
        r').*$',
        re.IGNORECASE,
    )

    # Слова-прилагательные подготовки в начале имени (strip them off)
    _LEADING_PREP_ADJECTIVES = re.compile(
        r'^(gedeveineerde?|ontdarm[de]?|gekookt[e]?|gedroogd[e]?'
        r'|geröstet[e]?|sušen[éý]?)\s+',
        re.IGNORECASE,
    )

    # Суффиксные слова подготовки после имени ингредиента
    _TRAILING_PREP_WORDS = re.compile(
        r'[,\s]+(gekookt[e]?,?\s*uitgelekt[e]?,?\s*(?:en\s+)?schoon'
        r'|ontdarmd[e]?\s+gekookt[e]?,?\s*uitgelekt[e]?,?\s*(?:en\s+)?schoon'
        r'|deveined,?\s*cooked,?\s*drained(?:\s+and\s+clean)?'
        r')[.]*$',
        re.IGNORECASE,
    )

    # Паттерн для обнаружения кухонного оборудования (не ингредиент)
    _EQUIPMENT_KEYWORDS = re.compile(
        r'\b(stoomboot|steamer|pan\b|pot\b|topf\b|hrnec\b|parník\b'
        r'|meisje|machine|apparaat|gerät)\b',
        re.IGNORECASE,
    )

    # Unicode дроби → строковое значение
    _FRACTIONS = {
        '½': '1/2', '¼': '1/4', '¾': '3/4',
        '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
        '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
        '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5',
    }

    # ---------------------------------------------------------------------------
    # Вспомогательные методы
    # ---------------------------------------------------------------------------

    def _find_recipe_container(self):
        """Возвращает div, содержащий блок рецепта (заголовок h2 + ингредиенты + инструкции)."""
        entry = self.soup.find(class_='entry-content')
        if not entry:
            logger.warning("entry-content not found")
            return None

        # Ищем h2 — название рецепта внутри entry-content
        h2 = entry.find('h2')
        if h2:
            # Родительский контейнер h2 — это и есть блок рецепта
            container = h2.find_parent('div')
            if container and container != entry:
                return container
        return entry

    def _normalize_fractions(self, text: str) -> str:
        """Заменяет Unicode-дроби и склеенные дроби (21/2 → 2.5)."""
        for uc, ascii_frac in self._FRACTIONS.items():
            text = text.replace(uc, f' {ascii_frac} ')

        # "21/2" → "2 1/2"  (число без пробела перед дробью)
        text = re.sub(r'(\d)(\d)/(\d)', r'\1 \2/\3', text)
        return text

    def _fraction_to_float(self, text: str) -> Optional[float]:
        """Конвертирует строку вида '1 1/2' или '1/4' или '2.5' в float."""
        text = text.strip()
        if not text:
            return None
        try:
            # Смешанное число типа "1 1/2"
            mixed = re.match(r'^(\d+)\s+(\d+)/(\d+)$', text)
            if mixed:
                whole = int(mixed.group(1))
                num = int(mixed.group(2))
                denom = int(mixed.group(3))
                return whole + num / denom

            # Обычная дробь "1/4"
            frac = re.match(r'^(\d+)/(\d+)$', text)
            if frac:
                return int(frac.group(1)) / int(frac.group(2))

            return float(text.replace(',', '.'))
        except (ValueError, ZeroDivisionError):
            return None

    def _format_amount(self, value: float) -> str:
        """Форматирует число: целые — без точки, дроби — с точкой."""
        if value == int(value):
            return str(int(value))
        return str(round(value, 4)).rstrip('0').rstrip('.')

    # ---------------------------------------------------------------------------
    # Парсинг одного ингредиента
    # ---------------------------------------------------------------------------

    def _parse_ingredient(self, raw_text: str) -> Optional[dict]:
        """
        Разбирает строку ингредиента на name / amount / unit.

        Примеры входных строк:
          "21/2 kopjes Bloem voorbereid voor tamales"
          "– 8 oz Reuzel"
          "1 1/4 cups kippenbouillon"
          "maïsbladeren"
          "zout en peper naar smaak"
        """
        if not raw_text:
            return None

        text = self.clean_text(raw_text)
        if not text:
            return None

        # Удаляем ведущие тире (– или -)
        text = re.sub(r'^[–\-]\s*', '', text)

        # Нормализуем дроби
        text = self._normalize_fractions(text)
        # Нормализуем пробелы после замены дробей
        text = re.sub(r'\s+', ' ', text).strip()

        # -----------------------------------------------------------------
        # Попытка 1: число + единица + название
        # -----------------------------------------------------------------
        amount: Optional[str] = None
        unit: Optional[str] = None
        name: str = text

        # Извлекаем ведущее число (целое, дробь, смешанное)
        amount_pattern = re.match(
            r'^((?:\d+\s+)?\d+/\d+|\d+(?:[.,]\d+)?)\s*(.*)', text
        )
        if amount_pattern:
            raw_amount = amount_pattern.group(1).strip()
            rest = amount_pattern.group(2).strip()
            value = self._fraction_to_float(raw_amount)
            if value is not None:
                amount = self._format_amount(value)
                text = rest

        # Извлекаем единицу измерения в начале оставшегося текста
        unit_match = re.match(r'^(' + self._UNITS.pattern + r')\s+(.*)', text, re.IGNORECASE)
        if unit_match:
            unit = unit_match.group(1).strip()
            name = unit_match.group(len(unit_match.groups())).strip()
        else:
            name = text

        # -----------------------------------------------------------------
        # Чистка названия
        # -----------------------------------------------------------------
        # Удаляем трейлинговые слова подготовки (gekookt, uitgelekt, schoon и т.п.)
        name = self._TRAILING_PREP_WORDS.sub('', name)
        # Удаляем ведущие прилагательные подготовки (gedeveineerde, ontdarmd и т.п.)
        name = self._LEADING_PREP_ADJECTIVES.sub('', name)
        # Удаляем описание подготовки после специфических слов с запятой
        name = self._PREP_AFTER_COMMA.sub('', name)
        # Удаляем фразы "naar smaak", "to taste" и т.п.
        name = self._STRIP_FROM_NAME.sub('', name)
        # Нормализуем пробелы вокруг апострофа ("paprika ' s" → "paprika's")
        # Учитываем как обычный апостроф ('), так и типографский (')
        name = re.sub(r"\s+['\u2018\u2019\u02bc]\s*s\b", "'s", name)
        # Заменяем оставшиеся запятые пробелами (например, "ui, geroosterde" → "ui geroosterde")
        name = name.replace(',', ' ')
        # Удаляем висящие знаки пунктуации
        name = re.sub(r"[;.']+$", '', name)
        name = re.sub(r'\s+', ' ', name).strip()

        if not name:
            return None

        return {
            "name": name,
            "amount": amount,
            "unit": unit,
        }

    # ---------------------------------------------------------------------------
    # Извлечение данных
    # ---------------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлекает название блюда из h2 внутри entry-content."""
        entry = self.soup.find(class_='entry-content')
        if entry:
            h2 = entry.find('h2')
            if h2:
                return self.clean_text(h2.get_text())

        # Запасной вариант — h1 с классом entry-title
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def extract_description(self) -> Optional[str]:
        """
        Извлекает описание рецепта.
        Приоритет: meta description → og:description → первый содержательный параграф.
        """
        # 1. meta[name=description]
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content', '').strip():
            return self.clean_text(meta_desc['content'])

        # 2. og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content', '').strip():
            return self.clean_text(og_desc['content'])

        # 3. Первый содержательный параграф в entry-content
        entry = self.soup.find(class_='entry-content')
        if entry:
            # Ищем параграфы до блока рецепта (div с "Save Recipe")
            recipe_box = None
            for div in entry.find_all('div', recursive=False):
                if 'Save Recipe' in div.get_text():
                    recipe_box = div
                    break

            for p in entry.find_all('p'):
                # Не заходим внутрь блока рецепта
                if recipe_box and recipe_box in p.parents:
                    continue
                text = self.clean_text(p.get_text())
                # Пропускаем короткие/навигационные фразы
                if text and len(text) > 60 and 'click' not in text.lower() and 'klik' not in text.lower():
                    return text

        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлекает ингредиенты из секции ингредиентов внутри блока рецепта.
        Возвращает JSON-строку со списком словарей.
        """
        container = self._find_recipe_container()
        if not container:
            return None

        ingredients = []

        # Ищем h3, содержащий ключевые слова ингредиентов
        ingredient_section = None
        for h3 in container.find_all(['h3', 'h2']):
            if self._INGREDIENT_SECTION_KEYWORDS.search(h3.get_text()):
                ingredient_section = h3.find_parent('div') or h3
                break

        if ingredient_section is None:
            logger.warning("Ingredient section not found in %s", self.html_path)
            return None

        # Собираем все li из этой секции (включая подсекции h4)
        for li in ingredient_section.find_all('li'):
            # Пропускаем элементы оглавления (toc_list)
            if li.find_parent(class_='toc_list') or li.find_parent(id='toc_container'):
                continue

            raw = self.clean_text(li.get_text())
            if not raw:
                continue

            parsed = self._parse_ingredient(raw)
            if parsed:
                # Пропускаем пункты, которые выглядят как кухонное оборудование
                if self._EQUIPMENT_KEYWORDS.search(parsed['name']):
                    logger.debug("Skipping equipment item: %s", parsed['name'])
                    continue
                ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_instructions(self) -> Optional[str]:
        """
        Извлекает инструкции из секции инструкций.
        Пункты, начинающиеся с '***', не включаются (это заметки).
        Возвращает строку вида '1. Шаг первый\n2. Шаг второй\n...'.
        """
        container = self._find_recipe_container()
        if not container:
            return None

        instruction_section = None
        for h3 in container.find_all(['h3', 'h2']):
            if self._INSTRUCTION_SECTION_KEYWORDS.search(h3.get_text()):
                instruction_section = h3.find_parent('div') or h3
                break

        if instruction_section is None:
            logger.warning("Instruction section not found in %s", self.html_path)
            return None

        steps = []
        for li in instruction_section.find_all('li'):
            text = self.clean_text(li.get_text())
            if not text:
                continue
            # Пункты с '***' — это заметки, пропускаем
            if text.startswith('***'):
                continue
            steps.append(text)

        if not steps:
            return None

        # Нумеруем шаги, если нумерация отсутствует
        if steps and not re.match(r'^\d+[.)]\s', steps[0]):
            steps = [f"{i}. {step}" for i, step in enumerate(steps, 1)]

        return '\n'.join(steps)

    def extract_notes(self) -> Optional[str]:
        """
        Извлекает заметки — пункты инструкций, начинающиеся с '***'.
        """
        container = self._find_recipe_container()
        if not container:
            return None

        instruction_section = None
        for h3 in container.find_all(['h3', 'h2']):
            if self._INSTRUCTION_SECTION_KEYWORDS.search(h3.get_text()):
                instruction_section = h3.find_parent('div') or h3
                break

        if instruction_section is None:
            return None

        notes = []
        for li in instruction_section.find_all('li'):
            text = self.clean_text(li.get_text())
            if text and text.startswith('***'):
                # Убираем ведущие '***' и пробелы
                note = re.sub(r'^\*+\s*', '', text).strip()
                if note:
                    notes.append(note)

        return ' '.join(notes) if notes else None

    def extract_category(self) -> Optional[str]:
        """
        Извлекает категорию рецепта.
        Источники: entry-category → articleSection в JSON-LD → article class.
        """
        # 1. entry-category div
        cat_div = self.soup.find(class_='entry-category')
        if cat_div:
            # Берём текст первой ссылки
            link = cat_div.find('a')
            if link:
                return self.clean_text(link.get_text())
            text = self.clean_text(cat_div.get_text())
            if text:
                return text

        # 2. articleSection из JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                graph = data.get('@graph', []) if isinstance(data, dict) else []
                for item in graph:
                    if item.get('@type') == 'Article' and 'articleSection' in item:
                        sections = item['articleSection']
                        # Берём первую значимую секцию (не языковую метку)
                        parts = [s.strip() for s in sections.split(',')]
                        for part in parts:
                            if part and not re.match(r'^pll_', part) and len(part) > 1:
                                return part
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue

        # 3. Класс article (category-XXX)
        article = self.soup.find('article')
        if article:
            for cls in article.get('class', []):
                if cls.startswith('category-'):
                    cat = cls.replace('category-', '').replace('-', ' ').title()
                    return cat

        return None

    def extract_tags(self) -> Optional[str]:
        """
        Извлекает теги рецепта.
        Источники: entry-tags → meta keywords → rel=tag ссылки.
        """
        # 1. entry-tags
        tags_div = self.soup.find(class_='entry-tags')
        if tags_div:
            links = [a.get_text().strip() for a in tags_div.find_all('a') if a.get_text().strip()]
            if links:
                return ', '.join(links)

        # 2. meta keywords
        meta_kw = self.soup.find('meta', {'name': 'keywords'})
        if meta_kw and meta_kw.get('content', '').strip():
            return self.clean_text(meta_kw['content'])

        # 3. a[rel=tag]
        tag_links = [
            a.get_text().strip()
            for a in self.soup.find_all('a', rel=lambda r: r and 'tag' in r)
            if a.get_text().strip()
        ]
        if tag_links:
            return ', '.join(tag_links)

        return None

    def extract_prep_time(self) -> Optional[str]:
        """
        Возвращает время подготовки.
        На adamfaliq.com явного поля нет — возвращаем None.
        """
        return None

    def extract_cook_time(self) -> Optional[str]:
        """
        Возвращает время приготовления.
        На adamfaliq.com явного поля нет — возвращаем None.
        """
        return None

    def extract_total_time(self) -> Optional[str]:
        """
        Возвращает общее время приготовления.
        На adamfaliq.com явного поля нет — возвращаем None.
        """
        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Извлекает URL изображений из entry-content и мета-тегов.
        Дубликаты удаляются; возвращается строка URL через запятую.
        """
        seen: set = set()
        urls: list = []

        def add_url(url: str) -> None:
            url = url.strip()
            if url and url not in seen:
                # Skip gravatar/avatar images (profile pictures, not recipe photos)
                hostname = urlparse(url).hostname or ''
                if 'gravatar.com' in hostname:
                    return
                seen.add(url)
                urls.append(url)

        # 1. og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            add_url(og_image['content'])

        # 2. JSON-LD — Article.image
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                graph = data.get('@graph', []) if isinstance(data, dict) else []
                for item in graph:
                    if item.get('@type') == 'Article':
                        img = item.get('image', {})
                        img_url = img.get('url') or img.get('contentUrl') if isinstance(img, dict) else img
                        if isinstance(img_url, str):
                            add_url(img_url)
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue

        # 3. Изображения в entry-content (src или data-lazy-src)
        entry = self.soup.find(class_='entry-content')
        if entry:
            for img in entry.find_all('img'):
                src = img.get('src') or img.get('data-lazy-src') or ''
                add_url(src)

        return ','.join(urls) if urls else None

    # ---------------------------------------------------------------------------
    # Основной метод
    # ---------------------------------------------------------------------------

    def extract_all(self) -> dict:
        """
        Извлекает все данные рецепта и возвращает словарь.
        Отсутствующие данные — None.
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception as e:
            logger.error("Error extracting dish_name: %s", e)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as e:
            logger.error("Error extracting description: %s", e)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as e:
            logger.error("Error extracting ingredients: %s", e)
            ingredients = None

        try:
            instructions = self.extract_instructions()
        except Exception as e:
            logger.error("Error extracting instructions: %s", e)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as e:
            logger.error("Error extracting category: %s", e)
            category = None

        try:
            notes = self.extract_notes()
        except Exception as e:
            logger.error("Error extracting notes: %s", e)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as e:
            logger.error("Error extracting tags: %s", e)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as e:
            logger.error("Error extracting image_urls: %s", e)
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
    """Обрабатывает директорию preprocessed/adamfaliq_com относительно корня репозитория."""
    import os
    repo_root = Path(__file__).parent.parent
    recipes_dir = repo_root / 'preprocessed' / 'adamfaliq_com'
    if recipes_dir.exists() and recipes_dir.is_dir():
        process_directory(AdamfaliqComExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python adamfaliq_com.py")


if __name__ == "__main__":
    main()
