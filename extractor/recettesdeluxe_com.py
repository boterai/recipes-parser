"""
Экстрактор данных рецептов для сайта recettesdeluxe.com
Сайт использует WordPress + плагин Tasty Recipes.
Основные источники данных:
  - JSON-LD (@type: Recipe) — название, описание, ингредиенты (базовые), инструкции, времена, категория
  - Блок .tasty-recipes в HTML — более надёжные человекочитаемые времена, заметки, описание
  - Основной текст статьи — более детальные ингредиенты с количеством и единицами
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


class RecettesDeluxeComExtractor(BaseRecipeExtractor):
    """Экстрактор для recettesdeluxe.com (WordPress + Tasty Recipes)"""

    # ------------------------------------------------------------------ #
    #  Вспомогательные методы                                             #
    # ------------------------------------------------------------------ #

    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Возвращает первый объект JSON-LD с @type == 'Recipe' или None."""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                # Может быть dict или list
                candidates = data if isinstance(data, list) else [data]
                for item in candidates:
                    if not isinstance(item, dict):
                        continue
                    t = item.get('@type', '')
                    if t == 'Recipe' or (isinstance(t, list) and 'Recipe' in t):
                        return item
                    # Внутри @graph
                    for node in item.get('@graph', []):
                        if not isinstance(node, dict):
                            continue
                        t2 = node.get('@type', '')
                        if t2 == 'Recipe' or (isinstance(t2, list) and 'Recipe' in t2):
                            return node
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return None

    @staticmethod
    def _iso_to_human(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат.

        Примеры:
          "PT20M"    -> "20 minutes"
          "PT1H"     -> "1 hour"
          "PT8H20M"  -> "8 hours 20 minutes"
        """
        if not duration or not duration.startswith('PT'):
            return None
        rest = duration[2:]
        hours = 0
        minutes = 0
        h = re.search(r'(\d+)H', rest)
        m = re.search(r'(\d+)M', rest)
        if h:
            hours = int(h.group(1))
        if m:
            minutes = int(m.group(1))
        parts = []
        if hours:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        return ' '.join(parts) if parts else None

    # ------------------------------------------------------------------ #
    #  Ингредиенты                                                        #
    # ------------------------------------------------------------------ #

    # Упорядоченный список паттернов для французских единиц измерения.
    # Порядок важен: длинные / более специфичные паттерны — первыми.
    # После каждого аббревиатурного юнита требуем (?=\s|$|,|\() чтобы
    # исключить ложные совпадения (напр. «g» в «gros»).
    _FR_UNIT_PATTERNS = [
        # Многословные единицы — сначала
        r'cuillères?\s+à\s+soupe',
        r'cuillères?\s+à\s+thé',
        r'cuillères?\s+à\s+table',
        r'cuillère\s+à\s+café',
        r'tasses?\s*(?:\([^)]*\))?',
        # Аббревиатуры — длинные перед короткими
        r'lbs?(?=\s|$|,|\()',
        r'oz(?=\s|$|,|\()',
        r'pcs?(?=\s|$|,|\()',
        r'kg(?=\s|$|,|\()',
        r'mg(?=\s|$|,|\()',
        r'ml(?=\s|$|,|\()',
        r'cl(?=\s|$|,|\()',
        r'dl(?=\s|$|,|\()',
        r'cm(?=\s|$|,|\()',
        r'g(?=\s|$|,|\()',
        r'l(?=\s|$|,|\()',
    ]

    def parse_ingredient_fr(self, text: str) -> Optional[dict]:
        """
        Разбирает строку французского ингредиента в словарь
        {name, amount, unit}.

        Поддерживаемые форматы:
          "265 g de farine T45"           -> {amount:"265", unit:"g",    name:"farine T45"}
          "1 lb de bœuf à ragoût"          -> {amount:"1",   unit:"lb",   name:"bœuf à ragoût"}
          "3 tasses (750 ml) de bouillon"  -> {amount:"3",   unit:"tasses (750 ml)", name:"bouillon de bœuf"}
          "1 cuillère à thé de thym"       -> {amount:"1",   unit:"cuillère à thé", name:"thym frais"}
          "5 jaunes d'œufs"               -> {amount:"5",   unit:None,   name:"jaunes d'œufs"}
          "Sel, au goût"                   -> {amount:None,  unit:"au goût", name:"Sel"}
          "Huile de friture"               -> {amount:None,  unit:None,   name:"Huile de friture"}
        """
        if not text:
            return None
        text = self.clean_text(text)
        if not text:
            return None

        # Случай «X, au goût» (Sel, au goût / Poivre du moulin, au goût)
        low = text.lower()
        if ', au goût' in low:
            idx = low.index(', au goût')
            name = text[:idx].strip()
            return {'name': name, 'amount': None, 'unit': 'au goût'}

        # Пытаемся извлечь число в начале строки
        # Дроби: «1/2», «1 1/2», десятичные: «1.5», «1,5», целые: «265»
        amount_re = re.compile(
            r'^(\d+(?:[.,]\d+)?(?:\s+\d+/\d+)?|\d+/\d+)\s+'
        )
        am = amount_re.match(text)
        if not am:
            # Нет числа в начале → только название
            return {'name': text, 'amount': None, 'unit': None}

        raw_amount = am.group(1).strip()
        remaining = text[am.end():]

        # Нормализуем дробь вида «1 1/2» → «1.5»
        def _normalize_amount(s: str) -> str:
            s = s.replace(',', '.')
            parts = s.split()
            if len(parts) == 2 and '/' in parts[1]:
                num, den = parts[1].split('/', 1)
                try:
                    return str(float(parts[0]) + float(num) / float(den))
                except ValueError:
                    pass
            if '/' in s and ' ' not in s:
                num, den = s.split('/', 1)
                try:
                    return str(float(num) / float(den))
                except ValueError:
                    pass
            return s

        amount = _normalize_amount(raw_amount)

        # Пытаемся сопоставить единицы измерения
        unit = None
        name_part = remaining

        for pat in self._FR_UNIT_PATTERNS:
            m = re.match(r'(?i)^(' + pat + r')\s*', remaining)
            if m:
                unit = m.group(1).strip()
                name_part = remaining[m.end():]
                break

        # Убираем предлог «de» / «d'» перед названием
        # Апостроф может быть U+0027 (ASCII), U+2019 (типографский) и т.п.
        name_part = re.sub(r"(?i)^(?:de\s+|d\s*[\u0027\u2019\u02bc\u0060]\s*)", '', name_part).strip()
        if not name_part and remaining.strip():
            # Если после юнита ничего не осталось — берём исходный текст как имя
            name_part = remaining.strip()

        return {'name': name_part, 'amount': amount, 'unit': unit}

    @staticmethod
    def _json_ld_has_amounts(items: list) -> bool:
        """
        Проверяет, содержат ли строки из JSON-LD recipeIngredient
        числовые количества (т.е. начинаются ли с цифры или дроби).
        Возвращает True, если хотя бы половина строк начинается с числа.
        """
        if not items:
            return False
        count = sum(1 for s in items if re.match(r'^[\d¼½¾⅓⅔⅛]', s.strip()))
        return count >= len(items) / 2

    def _parse_ingredient_list(self, texts: list) -> list:
        """Парсит список текстовых строк ингредиентов."""
        result = []
        for text in texts:
            text = self.clean_text(text)
            if text:
                parsed = self.parse_ingredient_fr(text)
                if parsed:
                    result.append(parsed)
        return result

    def _extract_ingredients_from_json_ld(self) -> list:
        """Извлекает и парсит ингредиенты из JSON-LD recipeIngredient."""
        ld = self._get_json_ld_recipe()
        if not ld or 'recipeIngredient' not in ld:
            return []
        return self._parse_ingredient_list(ld['recipeIngredient'])

    def _extract_ingredients_from_article(self) -> list:
        """
        Извлекает ингредиенты из основного текста статьи
        (h2 с «Ingr» → все ul/li до следующего h2).
        Здесь обычно есть количество и единицы измерения.
        """
        ingr_h2 = None
        for h2 in self.soup.find_all('h2'):
            if 'ingr' in h2.get_text(strip=True).lower():
                ingr_h2 = h2
                break
        if not ingr_h2:
            return []

        texts = []
        node = ingr_h2.find_next_sibling()
        while node and node.name != 'h2':
            if node.name == 'ul':
                for li in node.find_all('li'):
                    t = li.get_text(separator=' ', strip=True)
                    if t:
                        texts.append(t)
            node = node.find_next_sibling()
        return self._parse_ingredient_list(texts)

    def _extract_ingredients_from_tasty_recipes(self) -> list:
        """
        Извлекает ингредиенты из блока .tasty-recipes-ingredients.
        Используется как запасной вариант.
        """
        block = self.soup.find('div', class_='tasty-recipes-ingredients')
        if not block:
            return []
        texts = []
        for li in block.find_all('li'):
            t = li.get_text(separator=' ', strip=True)
            if t:
                texts.append(t)
        return self._parse_ingredient_list(texts)

    def extract_ingredients(self) -> Optional[str]:
        """
        Возвращает JSON-строку со списком ингредиентов.

        Приоритет:
          1. JSON-LD recipeIngredient — если строки содержат числовые количества
             (наиболее надёжный источник, данные хорошо структурированы)
          2. Раздел «Ingrédients» в теле статьи (когда JSON-LD не содержит
             количеств, как на некоторых страницах)
          3. Блок .tasty-recipes-ingredients в HTML
        """
        try:
            ld = self._get_json_ld_recipe()
            ld_items = ld.get('recipeIngredient', []) if ld else []

            # 1. JSON-LD с количествами
            if self._json_ld_has_amounts(ld_items):
                ingredients = self._extract_ingredients_from_json_ld()
                if ingredients:
                    return json.dumps(ingredients, ensure_ascii=False)

            # 2. Из тела статьи
            ingredients = self._extract_ingredients_from_article()
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

            # 3. Из tasty-recipes блока
            ingredients = self._extract_ingredients_from_tasty_recipes()
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

            # 4. JSON-LD без количеств (крайний случай)
            if ld_items:
                ingredients = self._extract_ingredients_from_json_ld()
                if ingredients:
                    return json.dumps(ingredients, ensure_ascii=False)

        except Exception as e:
            logger.warning(f"Ошибка при извлечении ингредиентов: {e}")
        return None

    # ------------------------------------------------------------------ #
    #  Инструкции                                                         #
    # ------------------------------------------------------------------ #

    def _instructions_from_json_ld(self) -> Optional[str]:
        """
        Возвращает строку инструкций из JSON-LD recipeInstructions,
        если шаги содержат осмысленный текст (не просто заголовки).
        """
        ld = self._get_json_ld_recipe()
        if not ld or 'recipeInstructions' not in ld:
            return None
        steps_raw = ld['recipeInstructions']
        texts = []
        for step in steps_raw:
            if isinstance(step, dict):
                t = self.clean_text(step.get('text', ''))
            elif isinstance(step, str):
                t = self.clean_text(step)
            else:
                continue
            if t:
                texts.append(t)
        if not texts:
            return None
        # Считаем «подробными», если средняя длина шага > 40 символов
        avg_len = sum(len(t) for t in texts) / len(texts)
        if avg_len < 40:
            return None
        return ' '.join(texts)

    def _instructions_from_tasty_recipes(self) -> Optional[str]:
        """Возвращает инструкции из блока .tasty-recipes-instructions."""
        block = self.soup.find('div', class_='tasty-recipes-instructions')
        if not block:
            return None
        steps = []
        for li in block.find_all('li'):
            t = li.get_text(separator=' ', strip=True)
            t = self.clean_text(t)
            if t:
                steps.append(t)
        if not steps:
            return None
        avg_len = sum(len(s) for s in steps) / len(steps)
        if avg_len < 40:
            return None
        return ' '.join(steps)

    def _instructions_from_article(self) -> Optional[str]:
        """
        Возвращает инструкции из раздела «Préparation» в теле статьи.
        Собирает заголовки h3 + параграфы p до следующего h2.
        """
        prep_h2 = None
        for h2 in self.soup.find_all('h2'):
            txt = h2.get_text(strip=True).lower()
            if 'prép' in txt or 'preparat' in txt or 'cuisson' in txt:
                prep_h2 = h2
                break
        if not prep_h2:
            return None

        parts = []
        node = prep_h2.find_next_sibling()
        while node and node.name != 'h2':
            if node.name == 'h3':
                title = self.clean_text(node.get_text())
                if title:
                    parts.append(title + ' :')
            elif node.name == 'p':
                t = self.clean_text(node.get_text(separator=' ', strip=True))
                if t:
                    parts.append(t)
            node = node.find_next_sibling()
        return ' '.join(parts) if parts else None

    def extract_instructions(self) -> Optional[str]:
        """
        Возвращает строку с инструкциями приготовления.
        Приоритет:
          1. JSON-LD recipeInstructions (если шаги детальные)
          2. Tasty Recipes HTML блок (если шаги детальные)
          3. Раздел «Préparation» в теле статьи
        """
        try:
            result = self._instructions_from_json_ld()
            if result:
                return result
            result = self._instructions_from_tasty_recipes()
            if result:
                return result
            return self._instructions_from_article()
        except Exception as e:
            logger.warning(f"Ошибка при извлечении инструкций: {e}")
            return None

    # ------------------------------------------------------------------ #
    #  Основные поля                                                      #
    # ------------------------------------------------------------------ #

    def extract_dish_name(self) -> Optional[str]:
        """Название блюда: JSON-LD → tasty-recipes-title → h1."""
        try:
            ld = self._get_json_ld_recipe()
            if ld and 'name' in ld:
                return self.clean_text(ld['name'])

            title_tag = self.soup.find('h2', class_='tasty-recipes-title')
            if title_tag:
                return self.clean_text(title_tag.get_text())

            h1 = self.soup.find('h1')
            if h1:
                return self.clean_text(h1.get_text())
        except Exception as e:
            logger.warning(f"Ошибка при извлечении названия: {e}")
        return None

    def extract_description(self) -> Optional[str]:
        """Описание: JSON-LD → tasty-recipes-description-body → meta description."""
        try:
            ld = self._get_json_ld_recipe()
            if ld and 'description' in ld:
                return self.clean_text(ld['description'])

            desc_body = self.soup.find('div', class_='tasty-recipes-description-body')
            if desc_body:
                t = self.clean_text(desc_body.get_text(separator=' ', strip=True))
                if t:
                    return t

            meta = self.soup.find('meta', {'name': 'description'})
            if meta and meta.get('content'):
                return self.clean_text(meta['content'])
        except Exception as e:
            logger.warning(f"Ошибка при извлечении описания: {e}")
        return None

    def extract_category(self) -> Optional[str]:
        """Категория: JSON-LD recipeCategory → tasty-recipes-category span."""
        try:
            ld = self._get_json_ld_recipe()
            if ld and 'recipeCategory' in ld:
                cat = ld['recipeCategory']
                if isinstance(cat, list):
                    cat = cat[0] if cat else None
                if cat:
                    return self.clean_text(str(cat))

            cat_span = self.soup.find('span', class_='tasty-recipes-category')
            if cat_span:
                t = self.clean_text(cat_span.get_text())
                if t:
                    return t
        except Exception as e:
            logger.warning(f"Ошибка при извлечении категории: {e}")
        return None

    def _extract_time_from_tasty(self, css_class: str) -> Optional[str]:
        """Извлекает время из span с указанным CSS-классом (человекочитаемый формат)."""
        span = self.soup.find('span', class_=css_class)
        if span:
            t = self.clean_text(span.get_text())
            if t:
                return t
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки: tasty-recipes span → JSON-LD ISO."""
        try:
            t = self._extract_time_from_tasty('tasty-recipes-prep-time')
            if t:
                return t
            ld = self._get_json_ld_recipe()
            if ld and 'prepTime' in ld:
                return self._iso_to_human(ld['prepTime'])
        except Exception as e:
            logger.warning(f"Ошибка при извлечении prep_time: {e}")
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Время приготовления: tasty-recipes span → JSON-LD ISO."""
        try:
            t = self._extract_time_from_tasty('tasty-recipes-cook-time')
            if t:
                return t
            ld = self._get_json_ld_recipe()
            if ld and 'cookTime' in ld:
                return self._iso_to_human(ld['cookTime'])
        except Exception as e:
            logger.warning(f"Ошибка при извлечении cook_time: {e}")
        return None

    def extract_total_time(self) -> Optional[str]:
        """Общее время: tasty-recipes span → JSON-LD ISO."""
        try:
            t = self._extract_time_from_tasty('tasty-recipes-total-time')
            if t:
                return t
            ld = self._get_json_ld_recipe()
            if ld and 'totalTime' in ld:
                return self._iso_to_human(ld['totalTime'])
        except Exception as e:
            logger.warning(f"Ошибка при извлечении total_time: {e}")
        return None

    def extract_notes(self) -> Optional[str]:
        """
        Заметки к рецепту.
        Приоритет:
          1. Блок .tasty-recipes-notes-body (основной источник)
          2. Разделы «Astuces» / «Conseils» в теле статьи — добавляются
             если основные заметки слишком короткие (< 120 символов)
        """
        try:
            parts = []

            # 1. Tasty-Recipes notes — обрабатываем элементы списка отдельно
            notes_body = self.soup.find('div', class_='tasty-recipes-notes-body')
            if notes_body:
                lis = notes_body.find_all('li')
                if lis:
                    note_items = [
                        self.clean_text(li.get_text(separator=' ', strip=True))
                        for li in lis
                    ]
                    note_items = [x for x in note_items if x]
                    if note_items:
                        parts.append('. '.join(note_items))
                else:
                    t = self.clean_text(
                        notes_body.get_text(separator=' ', strip=True)
                    )
                    if t:
                        parts.append(t)

            # 2. Если основных заметок мало, добавляем из тела статьи
            primary_len = len(parts[0]) if parts else 0
            if primary_len < 120:
                for h in self.soup.find_all(['h2', 'h3']):
                    txt_low = h.get_text(strip=True).lower()
                    if any(k in txt_low for k in ('astuce', 'conseil', 'note', 'tip')):
                        node = h.find_next_sibling()
                        count = 0
                        while node and node.name not in ('h2', 'h3') and count < 6:
                            if node.name == 'p':
                                t = self.clean_text(
                                    node.get_text(separator=' ', strip=True)
                                )
                                if t and t not in ' '.join(parts):
                                    parts.append(t)
                            node = node.find_next_sibling()
                            count += 1

            if parts:
                return ' '.join(parts)
        except Exception as e:
            logger.warning(f"Ошибка при извлечении notes: {e}")
        return None

    def extract_tags(self) -> Optional[str]:
        """
        Теги/ключевые слова:
          JSON-LD keywords → блок .tasty-recipes-keywords.
        """
        try:
            ld = self._get_json_ld_recipe()
            if ld and 'keywords' in ld:
                kw = ld['keywords']
                if isinstance(kw, list):
                    kw = ', '.join(kw)
                kw = self.clean_text(str(kw))
                if kw:
                    return kw

            kw_div = self.soup.find('div', class_='tasty-recipes-keywords')
            if kw_div:
                t = kw_div.get_text(separator=' ', strip=True)
                # Убираем метку «Mots clés:» / «Keywords:»
                t = re.sub(r'^(?:Mots\s+clés?|Keywords?)\s*:\s*', '', t, flags=re.IGNORECASE)
                t = self.clean_text(t)
                if t:
                    return t
        except Exception as e:
            logger.warning(f"Ошибка при извлечении tags: {e}")
        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        URL изображений из JSON-LD image, og:image, twitter:image.
        Возвращает строку URL, разделённых запятой (без пробелов).
        """
        urls: list = []
        try:
            # JSON-LD
            ld = self._get_json_ld_recipe()
            if ld and 'image' in ld:
                img = ld['image']
                if isinstance(img, str):
                    urls.append(img)
                elif isinstance(img, list):
                    for i in img:
                        if isinstance(i, str):
                            urls.append(i)
                        elif isinstance(i, dict):
                            url = i.get('url') or i.get('contentUrl')
                            if url:
                                urls.append(url)
                elif isinstance(img, dict):
                    url = img.get('url') or img.get('contentUrl')
                    if url:
                        urls.append(url)

            # og:image
            og = self.soup.find('meta', property='og:image')
            if og and og.get('content'):
                urls.append(og['content'])

            # twitter:image
            tw = self.soup.find('meta', attrs={'name': 'twitter:image'})
            if tw and tw.get('content'):
                urls.append(tw['content'])

            # Дедупликация
            seen: set = set()
            unique = []
            for u in urls:
                if u and u not in seen:
                    seen.add(u)
                    unique.append(u)
            return ','.join(unique) if unique else None
        except Exception as e:
            logger.warning(f"Ошибка при извлечении image_urls: {e}")
        return None

    # ------------------------------------------------------------------ #
    #  Публичный API                                                      #
    # ------------------------------------------------------------------ #

    def extract_all(self) -> dict:
        """
        Извлекает все поля рецепта и возвращает словарь.
        Все поля присутствуют; отсутствующие значения → None.
        """
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_instructions(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags(),
        }


def main() -> None:
    """
    Точка входа: обрабатывает все HTML-файлы из
    preprocessed/recettesdeluxe_com (относительно корня репозитория).
    """
    import os
    root = Path(__file__).parent.parent
    recipes_dir = root / "preprocessed" / "recettesdeluxe_com"
    if recipes_dir.exists() and recipes_dir.is_dir():
        process_directory(RecettesDeluxeComExtractor, str(recipes_dir))
    else:
        print(f"Директория не найдена: {recipes_dir}")


if __name__ == "__main__":
    main()
