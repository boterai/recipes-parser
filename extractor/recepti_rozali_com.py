"""
Экстрактор данных рецептов для сайта recepti.rozali.com
"""

import sys
import json
import logging
import re
from pathlib import Path
from typing import Optional, Dict, Any, List

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class ReceptiRozaliComExtractor(BaseRecipeExtractor):
    """Экстрактор для recepti.rozali.com (болгарский сайт рецептов)"""

    BASE_URL = "https://recepti.rozali.com"

    # Болгарские многословные единицы измерения (сначала длинные, чтобы матчились раньше)
    _MULTI_WORD_UNITS: List[str] = [
        "супени лъжици",
        "супена лъжица",
        "чаени лъжички",
        "чаена лъжичка",
        "с. л.",
        "ч. л.",
    ]

    # Болгарские однословные единицы измерения
    _SINGLE_WORD_UNITS: List[str] = [
        "кг", "г", "гр", "мл", "л", "cl", "dl",
        "с.л.", "ч.л.", "сл", "чл",
        "чаша", "чаши", "глава", "глави", "шепа",
        "щипка", "щипки", "капка", "капки",
        "пакетче", "пакет", "кубче", "парче", "парчета",
        "бр", "бр.", "броя", "брой",
    ]

    # Болгарские заголовки секций рецепта
    _INGREDIENTS_MARKERS = re.compile(
        r"^\s*(продукти|необходими\s+продукти|съставки|нужни\s+продукти)",
        re.IGNORECASE,
    )
    _INSTRUCTIONS_MARKERS = re.compile(
        r"^\s*(начин\s+на\s+приготвяне|приготвяне|приготовление|стъпки|как\s+се\s+прави)",
        re.IGNORECASE,
    )
    _NOTES_MARKERS = re.compile(
        r"^\s*(съвети|бележки|забележка|полезни\s+съвети|съвет)",
        re.IGNORECASE,
    )

    # -----------------------------------------------------------------
    # Вспомогательные методы
    # -----------------------------------------------------------------

    def _get_json_ld_recipe(self) -> Optional[Dict[str, Any]]:
        """Извлечение данных Recipe из JSON-LD (поддерживает прямой формат, список и @graph)"""
        for script in self.soup.find_all("script", type="application/ld+json"):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
            except (json.JSONDecodeError, AttributeError):
                continue

            # Прямой словарь с типом Recipe
            if isinstance(data, dict):
                if data.get("@type") == "Recipe":
                    return data
                # @graph — поиск Recipe внутри
                for item in data.get("@graph", []):
                    if isinstance(item, dict) and item.get("@type") == "Recipe":
                        return item

            # Список — поиск Recipe
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        item_type = item.get("@type", "")
                        if item_type == "Recipe" or (
                            isinstance(item_type, list) and "Recipe" in item_type
                        ):
                            return item

        return None

    def _get_microdata_recipe(self) -> Optional[Any]:
        """Возвращает корневой элемент Schema.org Recipe (microdata) или None"""
        return self.soup.find(
            attrs={"itemtype": re.compile(r"schema\.org/Recipe", re.IGNORECASE)}
        )

    def _abs_url(self, raw: str) -> str:
        """Преобразует относительный URL в абсолютный"""
        if not raw:
            return raw
        raw = raw.strip()
        if raw.startswith("//"):
            return "https:" + raw
        if raw.startswith("/"):
            return self.BASE_URL + raw
        return raw

    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат.

        Args:
            duration: строка вида «PT20M» или «PT1H30M»

        Returns:
            Время в формате «20 minutes» или «1 hour 30 minutes»
        """
        if not duration or not duration.startswith("PT"):
            return None

        body = duration[2:]
        hours = 0
        minutes = 0

        h_match = re.search(r"(\d+)H", body)
        if h_match:
            hours = int(h_match.group(1))

        m_match = re.search(r"(\d+)M", body)
        if m_match:
            minutes = int(m_match.group(1))

        parts: List[str] = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")

        return " ".join(parts) if parts else None

    # -----------------------------------------------------------------
    # Парсинг ингредиентов
    # -----------------------------------------------------------------

    def _is_ingredient_section_header(self, text: str) -> bool:
        """Проверяет, является ли строка заголовком подраздела ингредиентов (а не ингредиентом)"""
        if not text:
            return True
        # «За тестото:», «За пълнежа:» и т.п.
        if text.endswith(":"):
            return True
        # «За крема», «За глазурата»
        if re.match(r"^За\s+\w+", text):
            return True
        return False

    def parse_ingredient(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Парсинг строки ингредиента в структурированный формат.

        Args:
            text: строка вида «400 мл мляко» или «1/2 ч.л. ванилия»

        Returns:
            Словарь {"name": ..., "amount": ..., "unit": ...} или None для заголовков
        """
        text = self.clean_text(text)
        if not text:
            return None

        if self._is_ingredient_section_header(text):
            return None

        # Заменяем Unicode дроби
        fraction_map = {
            "½": "1/2", "¼": "1/4", "¾": "3/4",
            "⅓": "1/3", "⅔": "2/3", "⅛": "1/8",
            "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
        }
        for frac, rep in fraction_map.items():
            text = text.replace(frac, rep)

        # Паттерн для количества: 1, 1.5, 1/2, 1-2, 2-3
        amount_re = r"(\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?(?:\s+\d+/\d+)?|(?:\d+/\d+))"
        m = re.match(rf"^{amount_re}\s*", text)

        if not m:
            return {"name": text, "amount": None, "unit": None}

        amount_str = m.group(1).strip()
        rest = text[m.end():]

        unit: Optional[str] = None
        name = rest

        # Сначала ищем многословные единицы
        rest_lower = rest.lower()
        for mu in self._MULTI_WORD_UNITS:
            if rest_lower.startswith(mu.lower()):
                unit = mu
                name = rest[len(mu):].strip()
                break

        # Потом однословные
        if unit is None:
            parts = rest.split(None, 1)
            if parts:
                original = parts[0]
                candidate = original.rstrip(".")
                units_lower = [u.lower() for u in self._SINGLE_WORD_UNITS]
                # Проверяем как оригинал (напр. «с.л.»), так и без последней точки
                if original.lower() in units_lower:
                    unit = original
                    name = parts[1].strip() if len(parts) > 1 else ""
                elif candidate.lower() in units_lower:
                    unit = candidate
                    name = parts[1].strip() if len(parts) > 1 else ""

        if not name:
            name = rest.strip()

        # Нормализация количества
        amount: Any = amount_str
        try:
            if "/" in amount_str:
                nums = amount_str.split("/")
                if len(nums) == 2:
                    amount = float(nums[0]) / float(nums[1])
            elif re.match(r"^\d+$", amount_str):
                amount = int(amount_str)
            else:
                amount = float(amount_str.replace(",", "."))
        except (ValueError, ZeroDivisionError):
            pass

        return {"name": name, "amount": amount, "unit": unit}

    # -----------------------------------------------------------------
    # Извлечение полей
    # -----------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # 1. JSON-LD
        jld = self._get_json_ld_recipe()
        if jld and jld.get("name"):
            return self.clean_text(jld["name"])

        # 2. Microdata: itemprop="name" внутри Recipe scope
        recipe_scope = self._get_microdata_recipe()
        if recipe_scope:
            name_elem = recipe_scope.find(attrs={"itemprop": "name"})
            if name_elem:
                return self.clean_text(name_elem.get_text())

        # 3. h1 — главный заголовок страницы
        h1 = self.soup.find("h1")
        if h1:
            title = self.clean_text(h1.get_text())
            if title:
                return title

        # 4. og:title — очищаем от суффикса сайта
        og_title = self.soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
            title = re.sub(r"\s*[-|–]\s*[Рр]озали.*$", "", title)
            title = re.sub(r"\s*[-|–]\s*[Рр]ецепти.*$", "", title)
            return self.clean_text(title) or None

        logger.warning("Не удалось извлечь dish_name из %s", self.html_path)
        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # 1. JSON-LD description
        jld = self._get_json_ld_recipe()
        if jld and jld.get("description"):
            return self.clean_text(jld["description"])

        # 2. Microdata itemprop="description"
        recipe_scope = self._get_microdata_recipe()
        if recipe_scope:
            desc_elem = recipe_scope.find(attrs={"itemprop": "description"})
            if desc_elem:
                text = self.clean_text(desc_elem.get_text())
                if text:
                    return text

        # 3. meta description
        meta_desc = self.soup.find("meta", {"name": "description"})
        if meta_desc and meta_desc.get("content"):
            return self.clean_text(meta_desc["content"])

        # 4. og:description
        og_desc = self.soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            return self.clean_text(og_desc["content"])

        # 5. Первый параграф вводного текста (до секции Продукти/Приготвяне)
        for p in self.soup.find_all("p"):
            text = self.clean_text(p.get_text())
            if text and len(text) > 30:
                # Пропускаем параграфы, которые являются навигацией/копирайтом
                if any(kw in text.lower() for kw in ["cookie", "copyright", "©", "всички права"]):
                    continue
                return text

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients: List[Dict[str, Any]] = []

        # 1. JSON-LD recipeIngredient
        jld = self._get_json_ld_recipe()
        if jld and jld.get("recipeIngredient"):
            for item in jld["recipeIngredient"]:
                parsed = self.parse_ingredient(str(item))
                if parsed:
                    ingredients.append(parsed)
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        # 2. Microdata: itemprop="recipeIngredient" или itemprop="ingredients"
        recipe_scope = self._get_microdata_recipe()
        if recipe_scope:
            for attr in ("recipeIngredient", "ingredients"):
                items = recipe_scope.find_all(attrs={"itemprop": attr})
                for item in items:
                    text = self.clean_text(item.get_text())
                    if text:
                        parsed = self.parse_ingredient(text)
                        if parsed:
                            ingredients.append(parsed)
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        # 3. HTML: ищем заголовок «Продукти» и затем список/абзацы
        ingredients = self._extract_ingredients_from_html()
        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        logger.warning("Не удалось извлечь ингредиенты из %s", self.html_path)
        return None

    def _extract_ingredients_from_html(self) -> List[Dict[str, Any]]:
        """Поиск ингредиентов через HTML-заголовки «Продукти»"""
        ingredients: List[Dict[str, Any]] = []

        for heading_tag in ("h1", "h2", "h3", "h4", "h5", "b", "strong"):
            for heading in self.soup.find_all(heading_tag):
                heading_text = self.clean_text(heading.get_text())
                if not self._INGREDIENTS_MARKERS.match(heading_text):
                    continue

                # Ищем список или параграфы после заголовка
                sibling = heading.find_next_sibling()
                while sibling:
                    if sibling.name in ("h1", "h2", "h3", "h4", "h5"):
                        break
                    if self._INSTRUCTIONS_MARKERS.match(
                        self.clean_text(sibling.get_text())
                    ):
                        break

                    if sibling.name == "ul":
                        for li in sibling.find_all("li"):
                            text = self.clean_text(li.get_text())
                            parsed = self.parse_ingredient(text)
                            if parsed:
                                ingredients.append(parsed)
                        break
                    elif sibling.name == "ol":
                        for li in sibling.find_all("li"):
                            text = self.clean_text(li.get_text())
                            parsed = self.parse_ingredient(text)
                            if parsed:
                                ingredients.append(parsed)
                        break
                    elif sibling.name == "p":
                        text = self.clean_text(sibling.get_text())
                        if text:
                            # Может быть несколько ингредиентов, разделённых переносами
                            for line in re.split(r"\n|<br\s*/?>", text):
                                line = self.clean_text(line)
                                parsed = self.parse_ingredient(line)
                                if parsed:
                                    ingredients.append(parsed)

                    sibling = sibling.find_next_sibling()

                if ingredients:
                    return ingredients

        return ingredients

    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps: List[str] = []

        # 1. JSON-LD recipeInstructions
        jld = self._get_json_ld_recipe()
        if jld and jld.get("recipeInstructions"):
            instructions = jld["recipeInstructions"]
            for idx, step in enumerate(instructions, 1):
                if isinstance(step, dict):
                    text = self.clean_text(step.get("text", ""))
                elif isinstance(step, str):
                    text = self.clean_text(step)
                else:
                    continue
                if text:
                    steps.append(f"{idx}. {text}")
            if steps:
                return " ".join(steps)

        # 2. Microdata: itemprop="recipeInstructions"
        recipe_scope = self._get_microdata_recipe()
        if recipe_scope:
            instr_elems = recipe_scope.find_all(attrs={"itemprop": "recipeInstructions"})
            for idx, elem in enumerate(instr_elems, 1):
                # Удаляем вложенные картинки перед получением текста
                for img in elem.find_all("img"):
                    img.decompose()
                text = self.clean_text(elem.get_text(separator=" "))
                if text:
                    steps.append(f"{idx}. {text}")
            if steps:
                return " ".join(steps)

        # 3. HTML: ищем заголовок «Начин на приготвяне» / «Приготвяне»
        steps = self._extract_instructions_from_html()
        if steps:
            return " ".join(steps)

        logger.warning("Не удалось извлечь инструкции из %s", self.html_path)
        return None

    def _extract_instructions_from_html(self) -> List[str]:
        """Поиск инструкций через HTML-заголовки"""
        steps: List[str] = []

        for heading_tag in ("h1", "h2", "h3", "h4", "h5", "b", "strong"):
            for heading in self.soup.find_all(heading_tag):
                heading_text = self.clean_text(heading.get_text())
                if not self._INSTRUCTIONS_MARKERS.match(heading_text):
                    continue

                sibling = heading.find_next_sibling()
                while sibling:
                    if sibling.name in ("h1", "h2", "h3", "h4", "h5"):
                        break

                    if sibling.name == "ol":
                        for idx, li in enumerate(sibling.find_all("li"), 1):
                            text = self.clean_text(li.get_text(separator=" "))
                            if text:
                                steps.append(f"{idx}. {text}")
                        break
                    elif sibling.name == "ul":
                        for idx, li in enumerate(sibling.find_all("li"), 1):
                            text = self.clean_text(li.get_text(separator=" "))
                            if text:
                                steps.append(f"{idx}. {text}")
                        break
                    elif sibling.name == "p":
                        text = self.clean_text(sibling.get_text(separator=" "))
                        if text and not self._NOTES_MARKERS.match(text):
                            steps.append(text)

                    sibling = sibling.find_next_sibling()

                if steps:
                    return steps

        return steps

    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # 1. JSON-LD recipeCategory
        jld = self._get_json_ld_recipe()
        if jld and jld.get("recipeCategory"):
            cat = jld["recipeCategory"]
            if isinstance(cat, list):
                return ", ".join(str(c) for c in cat)
            return self.clean_text(str(cat))

        # 2. Microdata itemprop="recipeCategory"
        recipe_scope = self._get_microdata_recipe()
        if recipe_scope:
            cat_elem = recipe_scope.find(attrs={"itemprop": "recipeCategory"})
            if cat_elem:
                text = self.clean_text(cat_elem.get_text())
                if text:
                    return text

        # 3. article:section meta
        meta_section = self.soup.find("meta", property="article:section")
        if meta_section and meta_section.get("content"):
            return self.clean_text(meta_section["content"])

        # 4. Хлебные крошки — предпоследний элемент
        for bc_sel in (
            {"class": re.compile(r"breadcrumb", re.I)},
            {"class": re.compile(r"crumb", re.I)},
        ):
            bc = self.soup.find(["nav", "ol", "ul", "div"], bc_sel)
            if bc:
                links = bc.find_all("a")
                if len(links) >= 2:
                    # последняя ссылка — категория (рецепт обычно span)
                    return self.clean_text(links[-1].get_text())

        # 5. Любой nav с 2+ ссылками (хлебные крошки без класса)
        for nav in self.soup.find_all("nav"):
            links = nav.find_all("a")
            if len(links) >= 2:
                # Пропускаем главную страницу (Начало/Home)
                category_links = [
                    a for a in links
                    if not re.match(r"^/?$", a.get("href", ""))
                ]
                if category_links:
                    return self.clean_text(category_links[-1].get_text())

        return None

    def _extract_time_from_html(self, time_type: str) -> Optional[str]:
        """Поиск времени в HTML по паттерну (резервный метод)"""
        patterns = {
            "prep": re.compile(r"(подготовка|prep)", re.I),
            "cook": re.compile(r"(готвене|приготвяне|cook)", re.I),
            "total": re.compile(r"(общо\s+вре|total)", re.I),
        }
        pat = patterns.get(time_type)
        if not pat:
            return None

        # Ищем label/strong/span с текстом-меткой, потом берём соседний текст
        for elem in self.soup.find_all(["span", "strong", "label", "td", "dt"]):
            if pat.search(elem.get_text()):
                # Значение — в следующем элементе или в родительской строке таблицы
                sibling = elem.find_next_sibling()
                if sibling:
                    text = self.clean_text(sibling.get_text())
                    if text:
                        return text
                parent = elem.parent
                if parent:
                    # В той же строке таблицы
                    td_next = elem.find_next("td")
                    if td_next:
                        return self.clean_text(td_next.get_text())

        return None

    def _extract_time(self, time_key: str, html_type: str) -> Optional[str]:
        """
        Универсальное извлечение времени по ключу JSON-LD / itemprop / HTML.

        Args:
            time_key:  ключ в JSON-LD («prepTime», «cookTime», «totalTime»)
            html_type: тип для HTML-поиска («prep», «cook», «total»)
        """
        # 1. JSON-LD
        jld = self._get_json_ld_recipe()
        if jld and jld.get(time_key):
            result = self.parse_iso_duration(jld[time_key])
            if result:
                return result

        # 2. Microdata itemprop
        itemprop_map = {
            "prepTime": "prepTime",
            "cookTime": "cookTime",
            "totalTime": "totalTime",
        }
        recipe_scope = self._get_microdata_recipe()
        if recipe_scope:
            time_elem = recipe_scope.find(attrs={"itemprop": itemprop_map.get(time_key, time_key)})
            if time_elem:
                content = time_elem.get("content") or time_elem.get("datetime")
                if content and content.startswith("PT"):
                    result = self.parse_iso_duration(content)
                    if result:
                        return result
                text = self.clean_text(time_elem.get_text())
                if text:
                    return text

        # 3. HTML fallback
        return self._extract_time_from_html(html_type)

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self._extract_time("prepTime", "prep")

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        return self._extract_time("cookTime", "cook")

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self._extract_time("totalTime", "total")

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # 1. Ищем HTML-заголовок «Съвети» / «Бележки»
        for heading_tag in ("h1", "h2", "h3", "h4", "h5", "b", "strong"):
            for heading in self.soup.find_all(heading_tag):
                heading_text = self.clean_text(heading.get_text())
                if not self._NOTES_MARKERS.match(heading_text):
                    continue

                notes_parts: List[str] = []
                sibling = heading.find_next_sibling()
                while sibling:
                    if sibling.name in ("h1", "h2", "h3", "h4", "h5"):
                        break
                    if sibling.name in ("ul", "ol"):
                        for li in sibling.find_all("li"):
                            text = self.clean_text(li.get_text())
                            if text:
                                notes_parts.append(text)
                        break
                    elif sibling.name == "p":
                        text = self.clean_text(sibling.get_text())
                        if text:
                            notes_parts.append(text)
                    sibling = sibling.find_next_sibling()

                if notes_parts:
                    return " ".join(notes_parts)

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта"""
        # 1. JSON-LD keywords
        jld = self._get_json_ld_recipe()
        if jld and jld.get("keywords"):
            raw = str(jld["keywords"]).strip()
            if raw:
                tags = [t.strip() for t in raw.split(",") if t.strip()]
                return ", ".join(tags) if tags else None

        # 2. article:tag meta
        tag_metas = self.soup.find_all("meta", property="article:tag")
        if tag_metas:
            tags = [
                self.clean_text(m["content"])
                for m in tag_metas
                if m.get("content")
            ]
            return ", ".join(tags) if tags else None

        # 3. Ссылки с классом/паттерном тега
        tag_links = self.soup.find_all("a", href=re.compile(r"/tag/|/etiketi/|/тагове/|/kategori", re.I))
        if tag_links:
            tags = [self.clean_text(a.get_text()) for a in tag_links if a.get_text(strip=True)]
            tags = list(dict.fromkeys(tags))  # убираем дубликаты
            return ", ".join(tags) if tags else None

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls: List[str] = []
        seen: set = set()

        def add(raw: str) -> None:
            if not raw:
                return
            url = self._abs_url(raw)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        # 1. JSON-LD image
        jld = self._get_json_ld_recipe()
        if jld:
            img_field = jld.get("image")
            if isinstance(img_field, str):
                add(img_field)
            elif isinstance(img_field, list):
                for item in img_field:
                    if isinstance(item, str):
                        add(item)
                    elif isinstance(item, dict):
                        add(item.get("url", "") or item.get("contentUrl", ""))
            elif isinstance(img_field, dict):
                add(img_field.get("url", "") or img_field.get("contentUrl", ""))

        # 2. Microdata itemprop="image"
        recipe_scope = self._get_microdata_recipe()
        if recipe_scope:
            for img_elem in recipe_scope.find_all(attrs={"itemprop": "image"}):
                add(img_elem.get("src") or img_elem.get("content") or "")

        # 3. og:image meta
        og_image = self.soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            add(og_image["content"])

        # 4. twitter:image meta
        tw_image = self.soup.find("meta", attrs={"name": "twitter:image"})
        if tw_image and tw_image.get("content"):
            add(tw_image["content"])

        # 5. Основное изображение рецепта — ищем img около заголовка
        if not urls:
            h1 = self.soup.find("h1")
            if h1:
                parent = h1.parent
                if parent:
                    for img in parent.find_all("img"):
                        add(img.get("src", "") or img.get("data-src", ""))

        return ",".join(urls) if urls else None

    # -----------------------------------------------------------------
    # Основной метод
    # -----------------------------------------------------------------

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта (все поля присутствуют, None если не найдено)
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
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls(),
        }


def main() -> None:
    """Точка входа для обработки директории с HTML-файлами recepti.rozali.com"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "recepti_rozali_com")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(ReceptiRozaliComExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python recepti_rozali_com.py")


if __name__ == "__main__":
    main()
