"""
Экстрактор данных рецептов для сайта receitacerta.blog.br
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ReceitaCertaBlogBrExtractor(BaseRecipeExtractor):
    """Экстрактор для receitacerta.blog.br"""

    def _get_yoast_schema(self) -> Optional[dict]:
        """Извлечение Yoast-схемы (Article/BlogPosting) из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')

        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                # Yoast нередко кладёт граф в {"@graph": [...]}
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict):
                            item_type = item.get('@type', '')
                            types = item_type if isinstance(item_type, list) else [item_type]
                            if 'Article' in types or 'BlogPosting' in types:
                                return item
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        return None

    def _get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение данных JSON-LD с типом Recipe"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')

        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict):
                        item_type = item.get('@type', '')
                        types = item_type if isinstance(item_type, list) else [item_type]
                        if 'Recipe' in types:
                            return item
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        return None

    def _get_article(self):
        """Возвращает тег <article> или весь документ как fallback"""
        return self.soup.find('article') or self.soup

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        article = self._get_article()

        # H1 внутри статьи — наиболее надёжный источник
        h1 = article.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        # Заголовок из Yoast-схемы
        yoast = self._get_yoast_schema()
        if yoast and yoast.get('headline'):
            return self.clean_text(yoast['headline'])

        # Имя из Recipe JSON-LD
        recipe_ld = self._get_recipe_json_ld()
        if recipe_ld and recipe_ld.get('name'):
            return self.clean_text(recipe_ld['name'])

        # Крайний вариант — og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Используем meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        # og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        # Первый содержательный абзац статьи
        article = self._get_article()
        for p in article.find_all('p'):
            text = p.get_text(strip=True)
            if text and len(text) > 30:
                return self.clean_text(text)

        return None

    def _parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента на португальском в структурированный формат.

        Примеры:
            "100g de fubá"                → {name:"fubá", amount:"100", unit:"g"}
            "2 xícaras (chá) de farinha"  → {name:"farinha", amount:"2", unit:"xícaras (chá)"}
            "1/2 xícara de chá de azeite" → {name:"azeite", amount:"1/2", unit:"xícara de chá"}
            "1 colher (sopa) de amido"    → {name:"amido de milho", amount:"1", unit:"colher (sopa)"}
            "Sal a gosto"                 → {name:"sal", amount:"a gosto", unit:None}
            "Pimenta dedo de moça"        → {name:"pimenta dedo de moça", amount:None, unit:None}
        """
        if not ingredient_text:
            return None

        text = self.clean_text(ingredient_text)

        # Замена Unicode-дробей на ASCII-дроби
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
        }
        for frac, repl in fraction_map.items():
            text = text.replace(frac, repl)

        # Нормализация дробей с обратным слэшем (1\2 → 1/2) — встречается на receitacerta.blog.br
        text = re.sub(r'(\d+)\\(\d+)', r'\1/\2', text)

        # Единицы измерения (португальские + международные).
        # Порядок важен: сначала составные ("xícara de chá"), потом простые ("xícara").
        unit_pattern = (
            r'(?:'
            r'xícaras?\s*de\s+chá|'              # xícara de chá
            r'xícaras?\s*de\s+café|'             # xícara de café
            r'xícaras?\s*\(chá\)|'               # xícara (chá)
            r'xícaras?\s*\(café\)|'              # xícara (café)
            r'xícaras?|'                          # xícara
            r'colher(?:es)?\s*\(sopa\)|'          # colher (sopa)
            r'colher(?:es)?\s*de\s+sopa|'         # colher de sopa
            r'colher(?:es)?\s*\(chá\)|'           # colher (chá)
            r'colher(?:es)?\s*de\s+chá|'          # colher de chá
            r'colher(?:es)?|'                     # colher
            r'kg\b|g\b|mg\b|'
            r'litros?|l\b|ml\b|'
            r'unidades?|und\.|'
            r'dentes?|'
            r'pitadas?|'
            r'fatias?|'
            r'folhas?|'
            r'ramos?|'
            r'pedaços?'
            r')'
        )

        # Паттерн 1: число сразу перед единицей (без пробела), напр. "100g de fubá", "100ml de água"
        m = re.match(
            r'^(\d[\d/.,]*)(' + unit_pattern + r')\s*(?:de\s+)?(.+)$',
            text,
            re.IGNORECASE,
        )
        if m:
            amount_str, unit, name = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
            name = re.sub(r'\s+', ' ', name)
            return {'name': name, 'amount': amount_str, 'unit': unit}

        # Паттерн 2: "N [unit] de nome" — число, пробел, единица, необязательное "de", название
        m = re.match(
            r'^([\d/.,]+(?:\s+[\d/.,]+)?)\s+(' + unit_pattern + r')\s*(?:de\s+)?(.+)$',
            text,
            re.IGNORECASE,
        )
        if m:
            amount_str, unit, name = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
            name = re.sub(r'\s+', ' ', name)
            return {'name': name, 'amount': amount_str, 'unit': unit}

        # Паттерн 3: "texto de N nome" — описатель + дробь/число + название
        # Например: "Suco de 1/2 limão" → name="Suco de limão", amount="1/2", unit=None
        m = re.match(
            r'^([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s]+)\s+de\s+([\d/.,]+)\s+(.+)$',
            text,
            re.IGNORECASE,
        )
        if m:
            prefix, amount_str, noun = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
            name = f"{prefix} de {noun}"
            return {'name': name, 'amount': amount_str, 'unit': None}

        # Паттерн 4: "N/N название" — число/дробь + название без единицы ("1/2 maço de coentro")
        m = re.match(r'^([\d/.,]+(?:\s+[\d/.,]+)?)\s+(.+)$', text)
        if m:
            amount_str = m.group(1).strip()
            name = m.group(2).strip()
            # Убираем лишнее "de" в начале названия
            name = re.sub(r'^de\s+', '', name, flags=re.IGNORECASE)
            return {'name': name, 'amount': amount_str, 'unit': None}

        # Паттерн 5: "название a gosto / q.b. / suficiente" — без числового количества
        m = re.match(r'^(.+?)\s+(a gosto|q\.b\.|suficiente.*)$', text, re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            amount = m.group(2).strip()
            return {'name': name, 'amount': amount, 'unit': None}

        # Паттерн 6: просто название (без числа и единицы)
        return {'name': text, 'amount': None, 'unit': None}

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из HTML-списков после заголовка 'Ingredientes'"""
        article = self._get_article()
        ingredients = []

        # Находим H2 с "Ingredientes"
        ingredients_h2 = None
        for h2 in article.find_all('h2'):
            if re.search(r'ingrediente', h2.get_text(), re.IGNORECASE):
                ingredients_h2 = h2
                break

        if not ingredients_h2:
            return None

        # Собираем все <ul> с ингредиентами до следующего H2
        for sibling in ingredients_h2.find_next_siblings():
            if sibling.name == 'h2':
                break
            if sibling.name == 'ul':
                for li in sibling.find_all('li'):
                    text = li.get_text(strip=True)
                    if text:
                        parsed = self._parse_ingredient(text)
                        if parsed:
                            ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления из раздела 'Modo de Preparo'"""
        article = self._get_article()

        # Находим H2 с "Modo de Preparo" / "Preparo" / "Como fazer"
        preparo_h2 = None
        for h2 in article.find_all('h2'):
            if re.search(r'preparo|modo de|como fazer', h2.get_text(), re.IGNORECASE):
                preparo_h2 = h2
                break

        if not preparo_h2:
            return None

        steps = []

        # Ищем нумерованные шаги и секционные заголовки в <p> / <ol>/<li>
        for sibling in preparo_h2.find_next_siblings():
            if sibling.name == 'h2':
                break

            # Нумерованный список (<ol>)
            if sibling.name == 'ol':
                for idx, li in enumerate(sibling.find_all('li'), 1):
                    text = self.clean_text(li.get_text())
                    if text:
                        steps.append(f"{idx}. {text}")
                continue

            if sibling.name == 'p':
                text = sibling.get_text(strip=True)
                if not text:
                    continue

                # Нумерованный шаг ("1. ...")
                if re.match(r'^\d+\.', text):
                    steps.append(self.clean_text(text))
                    continue

                # Короткий секционный заголовок (напр. "Tilápia", "Molho Tártaro")
                # — включаем его в инструкции с двоеточием
                if len(text) < 60 and '>>>' not in text and not any(
                    kw in text.lower()
                    for kw in ('você', 'gostou', 'média', 'nenhum', 'enviar')
                ):
                    steps.append(self.clean_text(text) + ':')

        if not steps:
            return None

        # Убираем одиночные "заголовки" в конце, которые остались без шагов
        while steps and steps[-1].endswith(':'):
            steps.pop()

        return '\n'.join(steps)

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из Yoast-схемы или breadcrumb"""
        yoast = self._get_yoast_schema()
        if yoast and yoast.get('articleSection'):
            section = yoast['articleSection']
            if isinstance(section, list):
                return ', '.join(section)
            return str(section)

        # Из breadcrumb — ищем ссылку с /category/ в href (предпоследний элемент)
        for a in self.soup.find_all('a', href=True):
            href = a.get('href', '')
            if re.search(r'/category/[^/]+/?$', href):
                # Берём последнее значимое совпадение (из breadcrumb внутри статьи)
                text = a.get_text(strip=True)
                if text:
                    return text

        return None

    def _extract_time_from_html(self, keyword_pattern: str) -> Optional[str]:
        """
        Поиск времени по ключевому слову в:
        - <li>Ключевое слово: N минут</li>
        - <p><strong>Ключевое слово:</strong> N минут</p>
        Возвращает строку вида "N minutes".
        """
        article = self._get_article()

        # Поиск в <li>
        for li in article.find_all('li'):
            text = li.get_text(strip=True)
            if re.search(keyword_pattern, text, re.IGNORECASE):
                return self._parse_time_string(text)

        # Поиск в <p> с <strong>
        for p in article.find_all('p'):
            strong = p.find('strong')
            if strong and re.search(keyword_pattern, strong.get_text(), re.IGNORECASE):
                text = p.get_text(strip=True)
                return self._parse_time_string(text)

        return None

    @staticmethod
    def _parse_time_string(text: str) -> Optional[str]:
        """
        Извлекает и нормализует время из строки.
        "Tempo de preparo: Cerca de 20 minutos." → "20 minutes"
        "Tempo de preparo:30 minutos"            → "30 minutes"
        """
        # Ищем число + единицу времени
        m = re.search(r'(\d+)\s*(hora[s]?|h\b|minuto[s]?|min\b)', text, re.IGNORECASE)
        if not m:
            return None
        value = int(m.group(1))
        unit_raw = m.group(2).lower()
        if unit_raw.startswith('hora') or unit_raw == 'h':
            total_minutes = value * 60
            return f"{total_minutes} minutes"
        return f"{value} minutes"

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self._extract_time_from_html(r'tempo de preparo|preparo')

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self._extract_time_from_html(r'tempo de cozimento|cozimento')

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self._extract_time_from_html(r'tempo total|total')

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок/советов.
        Ищет содержательные абзацы после секции "Modo de Preparo",
        а также дополнительные секции (порции, варианты подачи и т.д.),
        которые не являются нумерованными шагами и не являются ссылками.
        """
        article = self._get_article()

        # Стоп-слова, указывающие на нерелевантный контент
        _noise = (
            'você também pode', 'você pode gostar', 'gostou da', 'média da',
            'nenhum voto', 'enviar classificação', '>>>'
        )

        def _is_noise(text: str) -> bool:
            low = text.lower()
            return any(kw in low for kw in _noise)

        note_paragraphs = []

        # 1. Параграфы после "Modo de Preparo", которые не являются шагами
        preparo_h2 = None
        for h2 in article.find_all('h2'):
            if re.search(r'preparo|modo de|como fazer', h2.get_text(), re.IGNORECASE):
                preparo_h2 = h2
                break

        if preparo_h2:
            for sibling in preparo_h2.find_next_siblings():
                if sibling.name == 'h2':
                    break
                if sibling.name == 'p':
                    text = sibling.get_text(strip=True)
                    if _is_noise(text):
                        # Прекращаем собирать заметки как только встретили шум
                        break
                    if (
                        text
                        and len(text) > 20
                        and not re.match(r'^\d+\.', text)
                    ):
                        note_paragraphs.append(self.clean_text(text))

        # 2. Параграфы из секций вроде "Opções de Recheios", "Dicas", "Sugestões"
        extra_sections = re.compile(
            r'opç[oõ]es|recheio|dica[s]?|sugest[aã]o|sugest[oõ]es|rendimento|serve',
            re.IGNORECASE,
        )
        for h2 in article.find_all('h2'):
            if extra_sections.search(h2.get_text()):
                for sibling in h2.find_next_siblings():
                    if sibling.name == 'h2':
                        break
                    if sibling.name == 'p':
                        text = sibling.get_text(strip=True)
                        if (
                            text
                            and len(text) > 20
                            and not _is_noise(text)
                            and text not in note_paragraphs
                        ):
                            note_paragraphs.append(self.clean_text(text))

        # 3. Если после Modo de Preparo ничего — ищем пояснительные абзацы между Ingredientes
        #    и Modo de Preparo (например, о выходе)
        if not note_paragraphs:
            ingredients_h2 = None
            for h2 in article.find_all('h2'):
                if re.search(r'ingrediente', h2.get_text(), re.IGNORECASE):
                    ingredients_h2 = h2
                    break

            if ingredients_h2:
                for sibling in ingredients_h2.find_next_siblings():
                    if sibling.name == 'h2':
                        break
                    if sibling.name == 'p':
                        text = sibling.get_text(strip=True)
                        if (
                            text
                            and len(text) > 20
                            and not re.match(r'^\d+\.', text)
                            and not _is_noise(text)
                        ):
                            note_paragraphs.append(self.clean_text(text))

        return ' '.join(note_paragraphs) if note_paragraphs else None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из ключевых слов Yoast-схемы"""
        yoast = self._get_yoast_schema()
        if yoast and yoast.get('keywords'):
            kw = yoast['keywords']
            if isinstance(kw, list):
                tags = [self.clean_text(k) for k in kw if k]
            else:
                tags = [t.strip() for t in str(kw).split(',') if t.strip()]

            # Убираем дубликаты (без учёта регистра)
            seen: set = set()
            unique: list = []
            for tag in tags:
                tl = tag.lower()
                if tl not in seen:
                    seen.add(tl)
                    unique.append(tag)

            return ', '.join(unique) if unique else None

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls: list = []

        # Recipe JSON-LD — самый надёжный источник изображения рецепта
        recipe_ld = self._get_recipe_json_ld()
        if recipe_ld and recipe_ld.get('image'):
            img = recipe_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                urls.append(img.get('url') or img.get('contentUrl') or '')
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        urls.append(item.get('url') or item.get('contentUrl') or '')

        # Yoast thumbnailUrl
        yoast = self._get_yoast_schema()
        if yoast and yoast.get('thumbnailUrl'):
            urls.append(yoast['thumbnailUrl'])

        # og:image и twitter:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])

        # Дедупликация с сохранением порядка
        seen: set = set()
        unique_urls: list = []
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags(),
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "receitacerta_blog_br")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ReceitaCertaBlogBrExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python receitacerta_blog_br.py")


if __name__ == "__main__":
    main()
