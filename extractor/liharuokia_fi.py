"""
Экстрактор данных рецептов для сайта liharuokia.fi
"""

import sys
from pathlib import Path
import json
import re
import logging
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Единицы измерения, используемые на сайте liharuokia.fi (финские и метрические)
FINNISH_UNITS = {
    'g', 'kg', 'dl', 'l', 'ml', 'cl',
    'rkl', 'tl', 'kpl', 'prk', 'tlk', 'pss', 'rs', 'pak', 'pkk', 'ps',
    'annos', 'pala', 'viipale', 'nippu', 'oksa', 'pkt',
}

# Слова-количества (неточные меры, которые могут стоять вместо числа)
FINNISH_AMOUNT_WORDS = [
    'maun mukaan',
    'tarpeen mukaan',
    'halutessasi',
    'ripaus',
    'pari',
    'muutama',
    'vähän',
    'runsaasti',
    'sopivasti',
]

# Суффиксы подготовки, которые убираются после запятой в названии ингредиента
_PREP_NOTES_RE = re.compile(
    r',\s*(?:lohkottuna|murskattuna|hienonnettuna|silputtuna|viimeistelyyn'
    r'|lisukkeeksi|tarjoiluun|kuorittuna|pilkottuna|raastettuna|pehmennettynä'
    r'|pehmennettyinä|jäähdytettynä|sulatettuna|kylmänä|kuumana)\s*$',
    re.IGNORECASE
)


class LiharuokiaFiExtractor(BaseRecipeExtractor):
    """Экстрактор для liharuokia.fi"""

    def _get_json_ld(self) -> Optional[dict]:
        """Извлечение данных из JSON-LD (schema.org Recipe)"""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
                items = data if isinstance(data, list) else [data]
                for item in items:
                    item_type = item.get('@type', '')
                    if item_type == 'Recipe' or (
                        isinstance(item_type, list) and 'Recipe' in item_type
                    ):
                        return item
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    def _get_tab_pane(self, tab_number: int):
        """Возвращает div-панель вкладки по номеру (1, 2, 3)"""
        # Сначала ищем по data-w-tab атрибуту
        tab = self.soup.find('div', attrs={'data-w-tab': f'Tab {tab_number}'})
        if tab and 'recipe-tab' in (tab.get('class') or []):
            return tab
        # Резервный поиск по id шаблона Webflow
        return self.soup.find('div', id=f'w-tabs-0-data-w-pane-{tab_number - 1}')

    @staticmethod
    def _strip_markdown_markers(text: str) -> str:
        """Удаляет маркеры markdown ** из текста"""
        return re.sub(r'\*\*', '', text).strip()

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем h1 внутри блока main-recipe-card
        card = self.soup.find('div', class_='main-recipe-card')
        if card:
            h1 = card.find('h1')
            if h1:
                name = self._strip_markdown_markers(
                    self.clean_text(h1.get_text())
                )
                if name:
                    return name

        # Резерв: og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self._strip_markdown_markers(
                self.clean_text(og_title['content'])
            )

        # Резерв: JSON-LD
        ld = self._get_json_ld()
        if ld and ld.get('name'):
            return self._strip_markdown_markers(self.clean_text(ld['name']))

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Предпочитаем meta description (более развёрнутое, чем og)
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        # og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    @staticmethod
    def _normalize_amount(raw: str) -> str:
        """Нормализует строку количества: диапазон-разделитель → дефис, пробелы убрать"""
        raw = re.sub(r'\s*–\s*', '-', raw)
        raw = re.sub(r'\s+', '', raw)
        return raw

    @staticmethod
    def _clean_name(name: str) -> str:
        """Очищает название ингредиента от скобочных пояснений и суффиксов подготовки"""
        name = re.sub(r'\([^)]*\)', '', name)
        name = _PREP_NOTES_RE.sub('', name)
        name = re.sub(r',\s*$', '', name)
        name = re.sub(r'\s{2,}', ' ', name)
        return name.strip()

    @staticmethod
    def _parse_ingredient_line(line: str) -> Optional[dict]:
        """
        Разбирает строку ингредиента в формат {name, amount, unit}.

        Форматы:
          "800 g naudan paistilihaa"
          "2 sipulia"
          "4 kpl valkosipulinkynsiä"
          "1/2 tlk hillosipuleita"
          "1-2 l vettä"
          "ripaus mustapippuria"
          "Ripaus kuivattuja chilinpaloja"
          "maun mukaan suolaa"
          "2 kevätsipulin vartta viimeistelyyn"
          "1½ rkl soijakastiketta"
        """
        line = re.sub(r'\s+', ' ', line).strip()
        if not line:
            return None

        # Убираем скобочные уточнения типа "(esim. pork tai beef dumplings)"
        line_clean = re.sub(r'\([^)]*\)', '', line).strip()
        # Убираем суффиксы подготовки и запятые, нормализуем пробелы
        line_clean = _PREP_NOTES_RE.sub('', line_clean)
        line_clean = re.sub(r',\s*$', '', line_clean)
        line_clean = re.sub(r'\s{2,}', ' ', line_clean).strip()

        if not line_clean:
            return None

        # --- Слова-количества в начале строки (напр. "ripaus mustapippuria") ---
        for word in sorted(FINNISH_AMOUNT_WORDS, key=len, reverse=True):
            pattern = rf'^{re.escape(word)}\s+(.+)$'
            m = re.match(pattern, line_clean, re.IGNORECASE)
            if m:
                name = LiharuokiaFiExtractor._clean_name(m.group(1))
                return {'name': name, 'amount': word.lower(), 'unit': None}

        # --- Слова-количества в конце строки (напр. "Mustapippuria maun mukaan") ---
        for word in sorted(FINNISH_AMOUNT_WORDS, key=len, reverse=True):
            pattern = rf'^(.+?)\s+{re.escape(word)}$'
            m = re.match(pattern, line_clean, re.IGNORECASE)
            if m:
                name = LiharuokiaFiExtractor._clean_name(m.group(1))
                return {'name': name, 'amount': word.lower(), 'unit': None}

        # Шаблон количества:
        #   - целое число с возможной Unicode-дробью: 1, 2, 1½, 2¼ …
        #   - дробь через слэш: 1/2
        #   - диапазон: 1-2, 1–2, 6–8, 1.5-2
        amount_pattern = (
            r'(\d+[½¼¾⅓⅔⅛⅜]?'             # целое + необязательная дробь
            r'(?:[.,]\d+)?'                  # необязательная десятичная часть
            r'(?:\s*[–\-]\s*\d+[½¼¾⅓⅔⅛⅜]?' # необязательный диапазон
            r'(?:[.,]\d+)?)?'
            r')'
        )

        # Единицы (все строчные)
        unit_list = '|'.join(sorted(FINNISH_UNITS, key=len, reverse=True))
        unit_pattern = rf'({unit_list})'

        # Полный шаблон: <amount> <unit> <name>
        full_pattern = rf'^{amount_pattern}\s+{unit_pattern}\s+(.+)$'
        m = re.match(full_pattern, line_clean, re.IGNORECASE)
        if m:
            raw_amount = LiharuokiaFiExtractor._normalize_amount(m.group(1))
            name = LiharuokiaFiExtractor._clean_name(m.group(3))
            return {
                'name': name,
                'amount': raw_amount,
                'unit': m.group(2).lower(),
            }

        # Только количество без единицы: "2 sipulia", "6–8 fileetä"
        simple_pattern = rf'^{amount_pattern}\s+(.+)$'
        m = re.match(simple_pattern, line_clean)
        if m:
            raw_amount = LiharuokiaFiExtractor._normalize_amount(m.group(1))
            name = LiharuokiaFiExtractor._clean_name(m.group(2))
            return {
                'name': name,
                'amount': raw_amount,
                'unit': None,
            }

        # Без количества: "Limetti- tai sitruunaviipaleita tarjoiluun"
        name = LiharuokiaFiExtractor._clean_name(line_clean)
        if name:
            return {'name': name, 'amount': None, 'unit': None}

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из вкладки «ainekset» (Tab 1)"""
        tab = self._get_tab_pane(1)
        if not tab:
            logger.warning("Вкладка с ингредиентами (Tab 1) не найдена")
            return None

        ingredients = []
        rich = tab.find('div', class_='w-richtext') or tab

        # Вариант 1: маркированный или нумерованный список <ul>/<ol>
        list_el = rich.find(['ul', 'ol'])
        if list_el:
            for li in list_el.find_all('li'):
                text = self.clean_text(li.get_text(separator=' ', strip=True))
                # Пропускаем заголовки секций (содержат только жирный текст
                # или заканчиваются двоеточием)
                if text.endswith(':'):
                    continue
                parsed = self._parse_ingredient_line(text)
                if parsed:
                    ingredients.append(parsed)
        else:
            # Вариант 2: абзацы с <br> — каждый фрагмент между <br> = ингредиент
            for p in rich.find_all('p'):
                # Заменяем <br> на новую строку, затем разбиваем
                for br in p.find_all('br'):
                    br.replace_with('\n')
                block = p.get_text(separator='')
                for line in block.splitlines():
                    text = self.clean_text(line)
                    if not text:
                        continue
                    parsed = self._parse_ingredient_line(text)
                    if parsed:
                        ingredients.append(parsed)

        if not ingredients:
            logger.warning("Ингредиенты не найдены")
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления из вкладки «valmistusohje» (Tab 2)"""
        tab = self._get_tab_pane(2)
        if not tab:
            logger.warning("Вкладка с инструкциями (Tab 2) не найдена")
            return None

        rich = tab.find('div', class_='w-richtext') or tab
        steps = []

        # Вариант 1: нумерованный список <ol>
        ol = rich.find('ol')
        if ol:
            for li in ol.find_all('li'):
                text = self.clean_text(li.get_text(separator=' ', strip=True))
                if text:
                    steps.append(text)
            if steps:
                return '\n'.join(steps)

        # Вариант 2: абзацы <p> с нумерацией
        for p in rich.find_all('p'):
            text = self.clean_text(p.get_text(separator=' ', strip=True))
            if not text:
                continue
            # Останавливаемся на разделителе "---" или SEO-маркере "**"
            if text == '---' or re.match(r'^\*\*.*\*\*$', text):
                break
            # Пропускаем строки без нумерации, похожие на примечания/заголовки
            # (включаем только строки начинающиеся с числа)
            if re.match(r'^\d+\.?\s', text):
                # Убираем нумерацию: "1. текст" → "текст"
                text = re.sub(r'^\d+\.\s*', '', text)
                steps.append(text)
            elif steps:
                # Ненумерованный текст после шагов (напр. "Tarjoile keitettyjen...")
                # добавляем как продолжение последнего шага или отдельно
                steps.append(text)

        if not steps:
            logger.warning("Шаги приготовления не найдены")
            return None

        return '\n'.join(steps)

    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда (из JSON-LD или метаданных)"""
        ld = self._get_json_ld()
        if ld:
            cat = ld.get('recipeCategory')
            if cat:
                if isinstance(cat, list):
                    return ', '.join(cat)
                return self.clean_text(str(cat))
        return None

    def _extract_about_items(self) -> dict:
        """
        Извлекает данные из блока «Tietoja reseptistä» (about-the-recipe-card).
        Возвращает словарь {label_lower: value}.
        """
        result = {}
        card = self.soup.find('div', class_='about-the-recipe-card')
        if not card:
            return result
        for item in card.find_all('div', class_='about-the-recipe-item'):
            wrapper = item.find('div', class_='about-the-recipe-text-wrapper')
            if not wrapper:
                continue
            divs = wrapper.find_all('div', recursive=False)
            if len(divs) >= 2:
                label = self.clean_text(divs[0].get_text()).lower().rstrip(':')
                value = self.clean_text(divs[1].get_text())
                if label and value:
                    result[label] = value
        return result

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На liharuokia.fi поле prepTime отсутствует в HTML и JSON-LD
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        # Блок «Tietoja reseptistä» — метка «valmistusaika»
        about = self._extract_about_items()
        cook_time = about.get('valmistusaika')
        if cook_time:
            return cook_time

        # Резерв: JSON-LD cookTime
        ld = self._get_json_ld()
        if ld and ld.get('cookTime'):
            return self.clean_text(str(ld['cookTime']))

        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени приготовления"""
        # На liharuokia.fi cookTime в about-карточке соответствует полному времени
        return self.extract_cook_time()

    def extract_notes(self) -> Optional[str]:
        """Извлечение примечаний/заметок к рецепту"""
        # Попытка 1: Tab 3 («lisätietoja») — только если первый элемент не h1/h2 (SEO)
        tab3 = self._get_tab_pane(3)
        if tab3:
            rich3 = tab3.find('div', class_='w-richtext') or tab3
            children = [
                c for c in rich3.children
                if hasattr(c, 'name') and c.name
            ]
            if children and children[0].name not in ('h1', 'h2'):
                # Берём только абзацы, без заголовков
                paragraphs = [
                    self.clean_text(p.get_text(separator=' ', strip=True))
                    for p in rich3.find_all('p')
                    if self.clean_text(p.get_text(separator=' ', strip=True))
                ]
                if paragraphs:
                    return ' '.join(paragraphs[:3])

        # Попытка 2: нечисловые абзацы в Tab 2 после пронумерованных шагов
        tab2 = self._get_tab_pane(2)
        if tab2:
            rich2 = tab2.find('div', class_='w-richtext') or tab2
            note_lines = []
            past_steps = False
            for p in rich2.find_all('p'):
                text = self.clean_text(p.get_text(separator=' ', strip=True))
                if not text:
                    continue
                if text == '---' or re.match(r'^\*\*.*\*\*$', text):
                    break
                if re.match(r'^\d+\.?\s', text):
                    past_steps = True
                elif past_steps:
                    note_lines.append(text)
            if note_lines:
                return ' '.join(note_lines)

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords"""
        ld = self._get_json_ld()
        if ld and ld.get('keywords'):
            kw = ld['keywords']
            if isinstance(kw, list):
                return ', '.join(kw)
            return self.clean_text(str(kw))
        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls = []

        # og:image — основное фото рецепта
        og_img = self.soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            url = og_img['content'].strip()
            if url and url not in urls:
                urls.append(url)

        # JSON-LD image как резерв
        ld = self._get_json_ld()
        if ld:
            ld_img = ld.get('image')
            if ld_img:
                if isinstance(ld_img, list):
                    for img in ld_img:
                        img_url = (img.get('url') if isinstance(img, dict) else str(img)).strip()
                        if img_url and img_url not in urls:
                            urls.append(img_url)
                elif isinstance(ld_img, dict):
                    img_url = ld_img.get('url', '').strip()
                    if img_url and img_url not in urls:
                        urls.append(img_url)
                else:
                    img_url = str(ld_img).strip()
                    if img_url and img_url not in urls:
                        urls.append(img_url)

        return ','.join(urls) if urls else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта

        Returns:
            Словарь с данными рецепта
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        instructions = self.extract_steps()
        notes = self.extract_notes()

        return {
            'dish_name': dish_name,
            'description': description,
            'ingredients': self.extract_ingredients(),
            'instructions': instructions,
            'category': self.extract_category(),
            'prep_time': self.extract_prep_time(),
            'cook_time': self.extract_cook_time(),
            'total_time': self.extract_total_time(),
            'notes': notes,
            'image_urls': self.extract_image_urls(),
            'tags': self.extract_tags(),
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os

    preprocessed_dir = os.path.join('preprocessed', 'liharuokia_fi')

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(LiharuokiaFiExtractor, preprocessed_dir)
        return

    print(f'Директория не найдена: {preprocessed_dir}')
    print('Использование: python liharuokia_fi.py')


if __name__ == '__main__':
    main()
