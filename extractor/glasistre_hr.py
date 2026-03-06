"""
Экстрактор данных рецептов для сайта glasistre.hr
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


class GlasistrHrExtractor(BaseRecipeExtractor):
    """Экстрактор для glasistre.hr"""

    # Croatian/metric units for ingredient parsing
    _CR_UNITS = (
        r'dag|dkg|kg|g|grami|grama|gram'
        r'|dcl|dl|ml|litra|litre|litr|l'
        r'|žlica|žlice|žlicu|žl'
        r'|žličica|žličice|žličicu|žličica|žličicu'
        r'|šalica|šalice|šalicu'
        r'|komad|komada|kom'
        r'|kriška|kriške|kriška'
        r'|prstohvat|prstohvatom'
        r'|malo|malo'
        r'|vezica|vezice'
        r'|režanj|režnja|režnjeva'
        r'|list|lista|listova'
        r'|tsp|tbsp|cup|cups|oz|lb|lbs|g|kg|ml|l'
    )

    def _get_content_div(self):
        """Возвращает основной контентный блок страницы"""
        return self.soup.find('div', id='CloudHub_Element_Content')

    def _detect_layout(self) -> str:
        """
        Определяет тип вёрстки страницы.

        Returns:
            'gitekst'  – старая вёрстка (абзацы <p class="GITekst">)
            'h2ul'     – новая вёрстка (заголовки <h2> + <ul>/<p>)
        """
        content_div = self._get_content_div()
        if content_div and content_div.find('p', class_='GITekst'):
            return 'gitekst'
        return 'h2ul'

    # ------------------------------------------------------------------
    # dish_name
    # ------------------------------------------------------------------
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Предпочитаем og:title, убирая суффиксы сайта
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем «RECEPT: » / «Recept dana: » / «Recept:» и т.п.
            title = re.sub(r'^Recept\s+dana\s*[:–-]\s*', '', title, flags=re.IGNORECASE)
            title = re.sub(r'^RECEPT\s*[:–-]\s*', '', title, flags=re.IGNORECASE)
            # Убираем суффиксы вида «… začas je gotov»? — нет, оставляем полное название
            return self.clean_text(title)

        # Запасной вариант — первый h1 страницы
        h1 = self.soup.find('h1')
        if h1:
            text = self.clean_text(h1.get_text())
            if text:
                return text

        return None

    # ------------------------------------------------------------------
    # description
    # ------------------------------------------------------------------
    def extract_description(self) -> Optional[str]:
        """Извлечение краткого описания рецепта"""
        content_div = self._get_content_div()

        layout = self._detect_layout()

        if layout == 'gitekst' and content_div:
            # Первый GITekst-абзац содержит вводное описание
            first_p = content_div.find('p', class_='GITekst')
            if first_p:
                text = self.clean_text(first_p.get_text())
                # Если первый абзац — это сам рецепт (начинается с «Sastojci:»), пропускаем
                if text and not text.lower().startswith('sastojci'):
                    return text

        if layout == 'h2ul' and content_div:
            # Первый <p> без класса до первого <h2> — вводный текст
            for child in content_div.children:
                if not hasattr(child, 'name') or not child.name:
                    continue
                if child.name == 'h2':
                    break
                if child.name == 'p':
                    text = self.clean_text(child.get_text())
                    if text:
                        return text

        # Fallback — og:description / meta description
        for attr, name in [('property', 'og:description'), ('name', 'description'),
                            ('name', 'twitter:description')]:
            meta = self.soup.find('meta', {attr: name})
            if meta and meta.get('content'):
                content = self.clean_text(meta['content'])
                if content and content.lower() not in ('sastojci:', 'sastojci'):
                    return content

        return None

    # ------------------------------------------------------------------
    # Ingredient parsing (Croatian units)
    # ------------------------------------------------------------------
    def parse_ingredient(self, text: str) -> Optional[dict]:
        """
        Разбирает строку ингредиента на {name, amount, unit}.

        Поддерживаемые форматы:
          «25 dag bijelog brašna»
          «1,5 žličica soda bikarbone»
          «4 dcl kefira, jogurta ili slično»
          «sol i svježe mljeveni papar»
          «malo čilija (po želji)»
        """
        if not text:
            return None

        # Заменяем Unicode дроби
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
        }
        for frac, dec in fraction_map.items():
            text = text.replace(frac, dec)

        # Нормализуем текст (запятая как десятичный разделитель -> точка)
        text = self.clean_text(text)

        # Паттерн: [количество] [единица] название
        units_re = self._CR_UNITS
        pattern = (
            r'^([\d]+(?:[.,]\d+)?(?:\s*[-–]\s*[\d]+(?:[.,]\d+)?)?(?:\s*[\d]+/[\d]+)?)'
            r'(?:\s+(' + units_re + r'))?\s+'
            r'(.+)$'
        )

        match = re.match(pattern, text, re.IGNORECASE)

        if not match:
            # Нет числа — только название
            name = re.sub(r'\(.*?\)', '', text).strip()
            name = re.sub(r',\s*$', '', name).strip()
            return {'name': name or text, 'amount': None, 'unit': None}

        amount_str, unit, name = match.groups()

        # Нормализуем количество (строка -> число)
        amount_str = amount_str.strip().replace(',', '.')
        # Диапазон типа «3–4» — берём первое значение
        range_match = re.match(r'^([\d.]+)\s*[-–]\s*[\d.]+$', amount_str)
        if range_match:
            amount_str = range_match.group(1)

        try:
            amount_val = float(amount_str)
            amount = int(amount_val) if amount_val == int(amount_val) else amount_val
        except ValueError:
            amount = amount_str

        unit = unit.strip() if unit else None

        # Чистим название
        name = re.sub(r'\(.*?\)', '', name).strip()
        name = re.sub(r',\s*$', '', name).strip()
        name = re.sub(r'\s+', ' ', name)

        if not name:
            return None

        return {'name': name, 'amount': amount, 'unit': unit}

    # ------------------------------------------------------------------
    # ingredients
    # ------------------------------------------------------------------
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        content_div = self._get_content_div()
        if not content_div:
            logger.warning("Не найден блок контента CloudHub_Element_Content")
            return None

        layout = self._detect_layout()

        if layout == 'gitekst':
            # Ищем секцию «Sastojci:» и берём абзацы до «Postupak:»
            paragraphs = content_div.find_all('p', class_='GITekst')
            in_ingredients = False
            for p in paragraphs:
                text = p.get_text(strip=True)
                text_lower = text.lower()
                if text_lower in ('sastojci:', 'sastojci'):
                    in_ingredients = True
                    continue
                if text_lower in ('postupak:', 'postupak', 'priprema:', 'priprema'):
                    break
                if in_ingredients and text:
                    parsed = self.parse_ingredient(text)
                    if parsed:
                        ingredients.append(parsed)

        else:  # h2ul layout
            # Ищем <h2> «Sastojci» и берём элементы <li> из ближайших <ul>
            sastojci_h2 = None
            for h2 in content_div.find_all('h2'):
                if 'sastojci' in h2.get_text(strip=True).lower():
                    sastojci_h2 = h2
                    break

            if sastojci_h2:
                # Обходим последующих siblings до следующего h2
                for sibling in sastojci_h2.next_siblings:
                    if not hasattr(sibling, 'name') or not sibling.name:
                        continue
                    if sibling.name == 'h2':
                        break
                    if sibling.name == 'ul':
                        for li in sibling.find_all('li'):
                            item_text = self.clean_text(li.get_text(separator=' ', strip=True))
                            if item_text:
                                parsed = self.parse_ingredient(item_text)
                                if parsed:
                                    ingredients.append(parsed)
                    elif sibling.name == 'p':
                        # Иногда ингредиенты находятся в абзацах-подзаголовках (напр. «Za meso:»)
                        # Пропускаем, т.к. реальные ингредиенты в следующих <ul>
                        pass

        if not ingredients:
            logger.warning("Ингредиенты не найдены")
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    # Ключевые слова, начинающие секцию заметок/советов
    _NOTE_HEADERS = (
        'savjet više', 'savjet:', 'savjet', 'mali trik', 'mali trik za još bolji okus',
        'napomena', 'napomena:', 'nota:', 'zanimljivost:', 'dobar tek!', 'dobar tek',
    )

    # ------------------------------------------------------------------
    # instructions
    # ------------------------------------------------------------------
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        content_div = self._get_content_div()
        if not content_div:
            logger.warning("Не найден блок контента CloudHub_Element_Content")
            return None

        layout = self._detect_layout()
        steps = []

        if layout == 'gitekst':
            paragraphs = content_div.find_all('p', class_='GITekst')
            in_steps = False
            for p in paragraphs:
                text = p.get_text(strip=True)
                text_lower = text.lower()
                if text_lower in ('postupak:', 'postupak', 'priprema:', 'priprema'):
                    in_steps = True
                    continue
                if in_steps and text:
                    steps.append(self.clean_text(text))

        else:  # h2ul layout
            # Ищем <h2> «Priprema» (или «Postupak»)
            priprema_h2 = None
            for h2 in content_div.find_all('h2'):
                h2_text = h2.get_text(strip=True).lower()
                if 'priprema' in h2_text or 'postupak' in h2_text:
                    priprema_h2 = h2
                    break

            if priprema_h2:
                for sibling in priprema_h2.next_siblings:
                    if not hasattr(sibling, 'name') or not sibling.name:
                        continue
                    if sibling.name == 'h2':
                        break
                    if sibling.name in ('p', 'li'):
                        text = self.clean_text(sibling.get_text(separator=' ', strip=True))
                        if not text or sibling.get('class', []) == ['inline-image']:
                            continue
                        # Останавливаемся на заголовках заметок
                        if text.lower() in self._NOTE_HEADERS:
                            break
                        steps.append(text)
                    elif sibling.name in ('ul', 'ol'):
                        for li in sibling.find_all('li'):
                            text = self.clean_text(li.get_text(separator=' ', strip=True))
                            if text:
                                steps.append(text)

        # Отфильтровываем «Dobar tek!» и пустые строки
        steps = [s for s in steps if s and s.lower() not in ('dobar tek!', 'dobar tek')]

        if not steps:
            logger.warning("Шаги приготовления не найдены")
            return None

        return ' '.join(steps)

    # ------------------------------------------------------------------
    # category  (страница не публикует категорию явно)
    # ------------------------------------------------------------------
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Пытаемся получить из article:section или breadcrumbs
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])

        breadcrumb = self.soup.find(class_=re.compile(r'breadcrumb', re.I))
        if breadcrumb:
            links = breadcrumb.find_all('a')
            if links:
                return self.clean_text(links[-1].get_text())

        return None

    # ------------------------------------------------------------------
    # times  (glasistre.hr не публикует структурированные времена)
    # ------------------------------------------------------------------
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Попытка извлечь время готовки из текста инструкции (напр. «peči 50 minuta»)
        content_div = self._get_content_div()
        if not content_div:
            return None

        layout = self._detect_layout()
        # Собираем текст инструкции
        if layout == 'gitekst':
            paragraphs = content_div.find_all('p', class_='GITekst')
            in_steps = False
            text_parts = []
            for p in paragraphs:
                t = p.get_text(strip=True)
                if t.lower() in ('postupak:', 'postupak', 'priprema:', 'priprema'):
                    in_steps = True
                    continue
                if in_steps and t:
                    text_parts.append(t)
            text = ' '.join(text_parts)
        else:
            priprema_h2 = None
            for h2 in content_div.find_all('h2'):
                if 'priprema' in h2.get_text(strip=True).lower() or 'postupak' in h2.get_text(strip=True).lower():
                    priprema_h2 = h2
                    break
            if not priprema_h2:
                return None
            parts = []
            for sib in priprema_h2.next_siblings:
                if not hasattr(sib, 'name') or not sib.name:
                    continue
                if sib.name == 'h2':
                    break
                parts.append(sib.get_text(separator=' ', strip=True))
            text = ' '.join(parts)

        # Ищем паттерн вида «peći/peći/kuhati/pirjati X minuta/sati»
        match = re.search(
            r'(?:peć[i]|peč[i]|peche?|kuhat[i]|pirjat[i]|peći|peče|pechi)\s+'
            r'(?:još\s+)?(\d+(?:[,.]\d+)?)\s*(minut[aie]?|sat[iah]?)',
            text, re.IGNORECASE
        )
        if match:
            amount = match.group(1).replace(',', '.')
            unit = match.group(2)
            return f"{amount} {unit}"

        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return None

    # ------------------------------------------------------------------
    # notes
    # ------------------------------------------------------------------
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов"""
        content_div = self._get_content_div()
        if not content_div:
            return None

        layout = self._detect_layout()

        if layout == 'gitekst':
            # В старой вёрстке нет явного блока «Napomena» — описание рецепта содержит совет
            # Берём первый GITekst-абзац, который идёт после секции «Sastojci»
            # (то есть сам описательный вводный абзац)
            # Но он уже возвращается как description.  Здесь возвращаем None.
            return None

        # Новая вёрстка: ищем параграф с ключевым словом заметки
        note_trigger_keywords = ('savjet više', 'savjet:', 'mali trik', 'mali trik za još bolji okus',
                                 'napomena', 'napomena:', 'nota:', 'savjet')

        paragraphs = content_div.find_all('p')
        for idx, p in enumerate(paragraphs):
            if p.get('class', []) == ['inline-image']:
                continue
            text = self.clean_text(p.get_text())
            if text.lower() in note_trigger_keywords:
                # Следующий абзац — текст заметки
                for next_p in paragraphs[idx + 1:]:
                    if next_p.get('class', []) == ['inline-image']:
                        continue
                    note_text = self.clean_text(next_p.get_text())
                    if note_text and note_text.lower() not in ('dobar tek!', 'dobar tek'):
                        return note_text
                break

        return None

    # ------------------------------------------------------------------
    # tags
    # ------------------------------------------------------------------
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # glasistre.hr не публикует теги в мета-тегах
        # Попытка найти теги-ссылки внутри блока контента
        content_div = self._get_content_div()
        tags = []

        if content_div:
            tags_block = content_div.find(class_=re.compile(r'tag', re.I))
            if tags_block:
                for a in tags_block.find_all('a'):
                    tag = self.clean_text(a.get_text())
                    if tag:
                        tags.append(tag)

        if not tags:
            return None

        return ', '.join(tags)

    # ------------------------------------------------------------------
    # image_urls
    # ------------------------------------------------------------------
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        seen = set()

        def add(url: str):
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        # Приоритет 1: og:image (высокое качество, стабильный URL)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            add(og_image['content'])

        # Приоритет 2: twitter:image
        tw_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if tw_image and tw_image.get('content'):
            add(tw_image['content'])

        # Приоритет 3: главное изображение статьи (td-post-featured-image2)
        featured = self.soup.find('div', class_='td-post-featured-image2')
        if featured:
            img = featured.find('img')
            if img and img.get('src'):
                add(img['src'])

        return ','.join(urls) if urls else None

    # ------------------------------------------------------------------
    # extract_all
    # ------------------------------------------------------------------
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception:
            logger.exception("Ошибка при извлечении dish_name")
            dish_name = None

        try:
            description = self.extract_description()
        except Exception:
            logger.exception("Ошибка при извлечении description")
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception:
            logger.exception("Ошибка при извлечении ingredients")
            ingredients = None

        try:
            instructions = self.extract_steps()
        except Exception:
            logger.exception("Ошибка при извлечении instructions")
            instructions = None

        try:
            category = self.extract_category()
        except Exception:
            logger.exception("Ошибка при извлечении category")
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception:
            logger.exception("Ошибка при извлечении prep_time")
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception:
            logger.exception("Ошибка при извлечении cook_time")
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception:
            logger.exception("Ошибка при извлечении total_time")
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception:
            logger.exception("Ошибка при извлечении notes")
            notes = None

        try:
            tags = self.extract_tags()
        except Exception:
            logger.exception("Ошибка при извлечении tags")
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception:
            logger.exception("Ошибка при извлечении image_urls")
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
    """Точка входа для обработки директории с HTML файлами"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "glasistre_hr")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(GlasistrHrExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python glasistre_hr.py")


if __name__ == "__main__":
    main()
