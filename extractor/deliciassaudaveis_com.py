"""
Экстрактор данных рецептов для сайта deliciassaudaveis.com

Сайт использует WordPress с темой Blocksy.
Некоторые страницы имеют плагин WPZOOM Recipe Card Block (структурированная карточка рецепта),
другие — статьи в формате ручного блог-поста с заголовками H2/H3.
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


class DeliciasSaudaveisComExtractor(BaseRecipeExtractor):
    """Экстрактор для deliciassaudaveis.com"""

    # ── ISO 8601 duration ─────────────────────────────────────────────────────

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """Конвертирует ISO 8601 duration в строку «X minutes»."""
        if not duration or not duration.startswith('PT'):
            return None
        body = duration[2:]
        hours, minutes = 0, 0
        h_match = re.search(r'(\d+)H', body)
        m_match = re.search(r'(\d+)M', body)
        if h_match:
            hours = int(h_match.group(1))
        if m_match:
            minutes = int(m_match.group(1))
        total = hours * 60 + minutes
        if total <= 0:
            return None
        return f"{total} minutes"

    # ── WPZOOM recipe card helpers ────────────────────────────────────────────

    def _get_wpzoom_card(self):
        """Возвращает div.wp-block-wpzoom-recipe-card-block-recipe-card или None."""
        return self.soup.find(
            class_='wp-block-wpzoom-recipe-card-block-recipe-card'
        )

    def _get_wpzoom_jsonld(self) -> Optional[dict]:
        """Читает JSON-LD, встроенный внутри блока WPZOOM."""
        card = self._get_wpzoom_card()
        if not card:
            return None
        script = card.find('script')
        if not script or not script.string:
            return None
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and data.get('@type') == 'Recipe':
                return data
        except (json.JSONDecodeError, ValueError):
            logger.warning("Не удалось разобрать JSON-LD в блоке WPZOOM")
        return None

    # ── Ingredient parsing ────────────────────────────────────────────────────

    def _parse_ingredient(self, text: str) -> Optional[dict]:
        """
        Разбирает строку ингредиента на name / amount / unit.

        Поддерживает:
        - «500g de carne moída» → amount=500, unit=g, name=carne moída
        - «2 xícaras de farinha de milho» → amount=2, unit=xícaras, name=farinha de milho
        - «1 cebola picada» → amount=1, unit=None, name=cebola picada
        - «Sal a gosto» → amount=a gosto, unit=None, name=Sal
        - «Alface picada» → amount=None, unit=None, name=Alface picada
        """
        if not text:
            return None
        text = self.clean_text(text)
        # Удаляем завершающие знаки препинания в конце строки (.,;)
        text = re.sub(r'[.,;]+$', '', text).strip()
        if not text:
            return None

        # Заменяем Unicode-дроби
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
        }
        for fr, dec in fraction_map.items():
            text = text.replace(fr, dec)

        # Единицы измерения (португальские + метрические + английские)
        # «dentes» намеренно исключены — это часть имени ингредиента («3 dentes de alho»)
        units_pattern = (
            r'xícaras?|colheres?\s+de\s+(?:chá|sopa)|colher\s+de\s+(?:chá|sopa)|'
            r'colheres?\s+(?:chá|sopa)|'
            r'kg|g\b|ml|l\b|mg|'
            r'litros?|mililitros?|gramas?|quilogramas?|'
            r'pitadas?|pacotes?|latas?|fatias?|'
            r'cups?|tablespoons?|teaspoons?|tbsps?|tsps?|'
            r'pounds?|ounces?|lbs?|oz\b|'
            r'pieces?|slices?|cloves?|heads?'
        )

        # 1) «500g de nome» или «500ml de nome» (число+единица слитно)
        m = re.match(
            r'^([\d.,/\s]+)\s*(' + units_pattern + r')\s+(?:de\s+)?(.+)$',
            text, re.IGNORECASE
        )
        if not m:
            # «500g nome» (без «de»)
            m = re.match(
                r'^([\d.,/]+)(' + units_pattern + r')\s+(.+)$',
                text, re.IGNORECASE
            )
        if m:
            raw_amount, unit, name = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
            amount = self._normalize_amount(raw_amount)
            name_clean = re.sub(r'[.,;]+$', '', self.clean_text(name)).strip()
            return {"name": name_clean, "amount": amount or raw_amount, "unit": unit}

        # 2) Число (возможно дробь «1 1/2»), потом название без единицы
        m = re.match(r'^((?:\d+\s+)?\d+/\d+|\d+[.,]?\d*)\s+(.+)$', text)
        if m:
            raw_amount = m.group(1).strip()
            name = re.sub(r'[.,;]+$', '', m.group(2)).strip()
            amount = self._normalize_amount(raw_amount)
            return {"name": self.clean_text(name), "amount": amount or raw_amount, "unit": None}

        # 3) «Sal a gosto» — текстовое количество «a gosto» в конце
        m = re.match(r'^(.+?)\s+(a\s+gosto(?:\s+.*)?)$', text, re.IGNORECASE)
        if m:
            name = re.sub(r'[.,;]+$', '', m.group(1)).strip()
            return {"name": self.clean_text(name), "amount": m.group(2).strip(), "unit": None}

        # 4) Не удалось распарсить — возвращаем всё как название
        clean_name = re.sub(r'[.,;]+$', '', self.clean_text(text)).strip()
        return {"name": clean_name, "amount": None, "unit": None}

    @staticmethod
    def _normalize_amount(raw: str) -> Optional[str]:
        """Нормализует строку количества: «1 1/2» → «1 1/2» (оставляем как есть)."""
        raw = raw.strip()
        if not raw:
            return None
        # Дробь вида «1 1/2»
        if re.match(r'^\d+\s+\d+/\d+$', raw):
            return raw
        # Простая дробь «1/2»
        if re.match(r'^\d+/\d+$', raw):
            return raw
        # Число
        return raw

    # ── Main content area helper ──────────────────────────────────────────────

    def _get_main_article(self):
        """
        Возвращает основной article (тип post) или entry-content div.
        """
        # Ищем article с классом post/type-post
        for art in self.soup.find_all('article'):
            classes = art.get('class', [])
            if any(c in classes for c in ('type-post', 'post')):
                return art
        # Запасной вариант
        return self.soup.find(id='content') or self.soup.find('main') or self.soup.find('article')

    def _get_entry_content(self):
        """Возвращает div.entry-content основной статьи."""
        art = self._get_main_article()
        if art:
            ec = art.find(class_='entry-content')
            if ec:
                return ec
        return self.soup.find(class_='entry-content')

    def _find_section_after_heading(self, heading_keywords: list[str], heading_tag: str = 'h2'):
        """
        Возвращает список элементов, следующих за заголовком H2/H3,
        текст которого содержит одно из ключевых слов.
        Останавливается на следующем H2.
        """
        ec = self._get_entry_content()
        if not ec:
            return []

        target_h = None
        for h in ec.find_all(heading_tag):
            h_text = h.get_text(strip=True).lower()
            if any(kw in h_text for kw in heading_keywords):
                target_h = h
                break
        if not target_h:
            return []

        siblings = []
        curr = target_h.find_next_sibling()
        while curr:
            if curr.name == 'h2':
                break
            if curr.name and curr.get_text(strip=True):
                siblings.append(curr)
            curr = curr.find_next_sibling()
        return siblings

    # ── Field extractors ──────────────────────────────────────────────────────

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда."""
        # 1) WPZOOM JSON-LD
        ld = self._get_wpzoom_jsonld()
        if ld and ld.get('name'):
            return self.clean_text(ld['name'])

        # 2) H1 в entry-content (статья-рецепт)
        ec = self._get_entry_content()
        if ec:
            h1 = ec.find('h1')
            if h1:
                return self.clean_text(h1.get_text())

        # 3) Первый H1 на странице
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        # 4) og:title
        og = self.soup.find('meta', property='og:title')
        if og and og.get('content'):
            title = og['content']
            title = re.sub(r'\s*[-|]\s*Delicias.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания (первый информативный абзац)."""
        ec = self._get_entry_content()
        if ec:
            # Ищем первый непустой <p> с достаточным текстом,
            # который не является техническим параграфом
            for p in ec.find_all('p'):
                text = self.clean_text(p.get_text())
                if (len(text) > 50
                        and 'last updated' not in text.lower()
                        and 'tabela de conteúdos' not in text.lower()):
                    return text

        # Запасной вариант — og:description
        og = self.soup.find('meta', property='og:description')
        if og and og.get('content'):
            return self.clean_text(og['content'])

        meta = self.soup.find('meta', {'name': 'description'})
        if meta and meta.get('content'):
            return self.clean_text(meta['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов."""
        ingredients = []

        # 1) WPZOOM JSON-LD → recipeIngredient
        ld = self._get_wpzoom_jsonld()
        if ld and ld.get('recipeIngredient'):
            for item in ld['recipeIngredient']:
                parsed = self._parse_ingredient(str(item))
                if parsed:
                    ingredients.append(parsed)
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        # 2) HTML: UL/OL под заголовком «ingredi*»
        siblings = self._find_section_after_heading(
            ['ingredi'],
            heading_tag='h2'
        )
        for elem in siblings:
            if elem.name in ('ul', 'ol'):
                for li in elem.find_all('li'):
                    text = self.clean_text(li.get_text())
                    if text:
                        parsed = self._parse_ingredient(text)
                        if parsed:
                            ingredients.append(parsed)
            elif elem.name == 'h3':
                # Подзаголовки подгрупп — пропускаем, ингредиенты в ul'ах ниже
                continue

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления."""
        steps = []

        # 1) WPZOOM JSON-LD → recipeInstructions
        ld = self._get_wpzoom_jsonld()
        if ld and ld.get('recipeInstructions'):
            for step in ld['recipeInstructions']:
                if isinstance(step, dict):
                    text = self.clean_text(step.get('text') or step.get('name') or '')
                elif isinstance(step, str):
                    text = self.clean_text(step)
                else:
                    continue
                if text:
                    steps.append(text)
            if steps:
                return ' '.join(steps)

        # 2) HTML: элементы под заголовком «preparo / passo / modo / instruc*»
        siblings = self._find_section_after_heading(
            ['preparo', 'passo a passo', 'modo de', 'instruc', 'directions']
        )

        for elem in siblings:
            if elem.name == 'ol':
                for i, li in enumerate(elem.find_all('li'), 1):
                    # Удаляем префикс-заголовок «Título:» если есть
                    raw = self.clean_text(li.get_text())
                    # Если li начинается с «Ключ: Текст», оставляем только Текст
                    colon_split = raw.split(':', 1)
                    if len(colon_split) == 2 and len(colon_split[0]) < 50:
                        raw = colon_split[1].strip()
                    if raw:
                        steps.append(f"{i}. {raw}")
            elif elem.name == 'ul':
                for li in elem.find_all('li'):
                    text = self.clean_text(li.get_text())
                    if text:
                        steps.append(text)
            elif elem.name == 'p':
                text = self.clean_text(elem.get_text())
                if text:
                    steps.append(text)
            elif elem.name == 'h3':
                # Субзаголовки шагов — не включаем в результат
                continue

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории."""
        # 1) WPZOOM JSON-LD
        ld = self._get_wpzoom_jsonld()
        if ld:
            cat = ld.get('recipeCategory') or ld.get('recipeCuisine')
            if cat:
                if isinstance(cat, list) and cat:
                    return self.clean_text(cat[0])
                elif isinstance(cat, str):
                    return self.clean_text(cat)

        # 2) meta article:section
        meta_sec = self.soup.find('meta', property='article:section')
        if meta_sec and meta_sec.get('content'):
            return self.clean_text(meta_sec['content'])

        # 3) Hero section category link
        hero = self.soup.find(class_='hero-section')
        if hero:
            link = hero.find('a')
            if link:
                return self.clean_text(link.get_text())

        return None

    def _extract_time_from_info_section(self, keywords: list[str]) -> Optional[str]:
        """
        Ищет время в разделе «Informações Adicionais» (список «Ключ: Значение»).
        """
        siblings = self._find_section_after_heading(['informa'])
        for elem in siblings:
            if elem.name in ('ul', 'ol'):
                for li in elem.find_all('li'):
                    li_text = self.clean_text(li.get_text(separator=':'))
                    li_lower = li_text.lower()
                    if any(kw in li_lower for kw in keywords):
                        # Формат «Tempo de preparo: 30 minutos» — берём значение после «:»
                        parts = li_text.split(':')
                        if len(parts) >= 2:
                            value = parts[-1].strip()
                            if value:
                                return value
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки."""
        # 1) WPZOOM JSON-LD
        ld = self._get_wpzoom_jsonld()
        if ld and ld.get('prepTime'):
            return self._parse_iso_duration(ld['prepTime'])

        # 2) Раздел «Informações Adicionais»
        return self._extract_time_from_info_section(['tempo de preparo', 'preparo', 'prep'])

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления."""
        # 1) WPZOOM JSON-LD
        ld = self._get_wpzoom_jsonld()
        if ld and ld.get('cookTime'):
            return self._parse_iso_duration(ld['cookTime'])

        # 2) Раздел «Informações Adicionais»
        return self._extract_time_from_info_section(['tempo de cozimento', 'cozimento', 'cooking'])

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени."""
        # 1) WPZOOM JSON-LD
        ld = self._get_wpzoom_jsonld()
        if ld and ld.get('totalTime'):
            return self._parse_iso_duration(ld['totalTime'])

        # 2) Раздел «Informações Adicionais»
        return self._extract_time_from_info_section(['tempo total', 'total'])

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов."""
        # 1) WPZOOM: div.recipe-card-notes + параграфы после карточки рецепта
        card = self._get_wpzoom_card()
        if card:
            texts = []

            notes_div = card.find(class_='recipe-card-notes')
            if notes_div:
                for elem in notes_div.find_all(['li', 'p']):
                    t = self.clean_text(elem.get_text())
                    if t and t.lower() not in ('notes', 'notas', 'note'):
                        texts.append(t)

            # Параграфы, следующие за блоком WPZOOM в entry-content
            ec = self._get_entry_content()
            if ec:
                after_card = False
                for child in ec.find_all(True, recursive=False):
                    if child == card:
                        after_card = True
                        continue
                    if after_card and child.name == 'p':
                        t = self.clean_text(child.get_text())
                        if t and len(t) > 20:
                            texts.append(t)

            if texts:
                return ' '.join(texts)

        # 2) HTML: секция «Dicas / Varia / Nota / Observa»
        siblings = self._find_section_after_heading(
            ['dica', 'varia', 'nota', 'observa', 'tips']
        )
        texts = []
        for elem in siblings:
            if elem.name in ('ul', 'ol'):
                for li in elem.find_all('li'):
                    raw = self.clean_text(li.get_text())
                    # Убираем субзаголовок вида «Título: Текст»
                    parts = raw.split(':', 1)
                    if len(parts) == 2 and len(parts[0]) < 60:
                        raw = parts[1].strip()
                    if raw:
                        texts.append(raw)
            elif elem.name == 'p':
                t = self.clean_text(elem.get_text())
                if t:
                    texts.append(t)

        return ' '.join(texts) if texts else None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из span.tag или meta article:tag."""
        tags = []

        # 1) span.tag в основной статье
        art = self._get_main_article()
        if art:
            for span in art.find_all('span', class_='tag'):
                t = self.clean_text(span.get_text())
                if t:
                    tags.append(t)

        # 2) meta article:tag
        if not tags:
            for meta in self.soup.find_all('meta', property='article:tag'):
                t = self.clean_text(meta.get('content', ''))
                if t:
                    tags.append(t)

        if not tags:
            return None

        # Дедупликация с сохранением порядка
        seen = set()
        unique = []
        for t in tags:
            lower = t.lower()
            if lower not in seen:
                seen.add(lower)
                unique.append(t)

        return ', '.join(unique)

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений."""
        urls = []

        # 1) og:image
        og = self.soup.find('meta', property='og:image')
        if og and og.get('content'):
            urls.append(og['content'])

        # 2) WPZOOM JSON-LD → image
        ld = self._get_wpzoom_jsonld()
        if ld:
            img = ld.get('image')
            if isinstance(img, str) and img:
                urls.append(img)
            elif isinstance(img, list):
                urls.extend(i for i in img if isinstance(i, str) and i)

        # Дедупликация
        seen: set = set()
        unique = []
        for u in urls:
            if u and u not in seen:
                seen.add(u)
                unique.append(u)

        return ','.join(unique) if unique else None

    # ── extract_all ───────────────────────────────────────────────────────────

    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта."""
        try:
            dish_name = self.extract_dish_name()
        except Exception as e:
            logger.error("dish_name: %s", e)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception as e:
            logger.error("description: %s", e)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception as e:
            logger.error("ingredients: %s", e)
            ingredients = None

        try:
            instructions = self.extract_instructions()
        except Exception as e:
            logger.error("instructions: %s", e)
            instructions = None

        try:
            category = self.extract_category()
        except Exception as e:
            logger.error("category: %s", e)
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception as e:
            logger.error("prep_time: %s", e)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception as e:
            logger.error("cook_time: %s", e)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception as e:
            logger.error("total_time: %s", e)
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception as e:
            logger.error("notes: %s", e)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception as e:
            logger.error("tags: %s", e)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception as e:
            logger.error("image_urls: %s", e)
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
    import os
    recipes_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "preprocessed",
        "deliciassaudaveis_com",
    )
    if os.path.isdir(recipes_dir):
        process_directory(DeliciasSaudaveisComExtractor, recipes_dir)
    else:
        print(f"Директория не найдена: {recipes_dir}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
