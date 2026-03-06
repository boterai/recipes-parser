"""
Экстрактор данных рецептов для сайта bonkers.com.tr
"""

import sys
from pathlib import Path
import json
import logging
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class BonkersComTrExtractor(BaseRecipeExtractor):
    """Экстрактор для bonkers.com.tr"""

    # Turkish measurement units (longest first to avoid partial matches)
    _TR_UNITS = [
        'yemek kaşığı', 'çay kaşığı', 'su bardağı',
        'tutam', 'paket', 'demet', 'dilim', 'adet',
        'büyük', 'küçük', 'orta',
        'litre', 'lt',
        'kg', 'gr', 'g', 'ml', 'l',
    ]

    # Turkish number words
    _TR_NUMBERS = {
        'bir': '1', 'iki': '2', 'üç': '3', 'dört': '4', 'beş': '5',
        'altı': '6', 'yedi': '7', 'sekiz': '8', 'dokuz': '9', 'on': '10',
    }

    def _get_article(self):
        """Получение основного элемента статьи"""
        return self.soup.find('article', attrs={'data-hook': 'post'})

    def _get_content_paragraphs(self) -> list:
        """
        Возвращает список текстовых параграфов контента статьи,
        исключая элементы внутри списков и служебные параграфы.
        """
        article = self._get_article()
        if not article:
            return []

        result = []
        for p in article.find_all('p'):
            # Пропускаем параграфы внутри списков
            if any(parent.name in ('li', 'ul', 'ol') for parent in p.parents):
                continue
            text = self.clean_text(p.get_text())
            if not text:
                continue
            # Пропускаем служебные параграфы
            if 'Güncelleme' in text or 'Etiketler' in text:
                continue
            result.append(text)
        return result

    def _get_etiketler_container(self):
        """Возвращает контейнер секции 'Etiketler' (теги/категории)"""
        article = self._get_article()
        if not article:
            return None
        for p in article.find_all('p'):
            if 'Etiketler' in p.get_text():
                # section -> parent div container
                section = p.parent
                return section.parent if section else None
        return None

    def _parse_ingredient(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента на турецком языке в структурированный формат.

        Args:
            text: Строка вида "150 gr tereyağı" или "1/2 su bardağı şeker"

        Returns:
            dict: {"name": ..., "amount": ..., "unit": ...} или None
        """
        if not text:
            return None

        original = text
        # Удаляем пояснения в скобках ("(iri kırılmış)", "(isteğe bağlı)" и т.п.)
        text = re.sub(r'\([^)]*\)', '', text).strip()
        # Убираем префиксы-пояснения типа "Üzeri için:", "Üst için:" (заканчиваются на ":")
        # которые указывают на назначение ингредиента, а не его количество
        text = re.sub(r'^[^:]{1,20}:\s*', '', text)
        # Убираем "Üzeri için" без двоеточия
        text = re.sub(r'^[Üü]zeri\s+için\s+', '', text, flags=re.IGNORECASE)
        text = self.clean_text(text)

        if not text:
            return None

        amount: Optional[str] = None
        unit: Optional[str] = None
        name: str = text

        # --- Попытка извлечь числовое количество в начале строки ---
        # Поддерживаем дроби ("1/2"), диапазоны ("10-12"), целые числа
        num_pattern = re.compile(
            r'^(\d+\s*/\s*\d+|\d+[-–]\d+|\d+(?:[.,]\d+)?)\s+(.*)',
            re.DOTALL,
        )
        match = num_pattern.match(text)
        if match:
            raw_amount, rest = match.group(1).strip(), match.group(2).strip()
            # Нормализуем дроби в числа
            frac_match = re.match(r'^(\d+)\s*/\s*(\d+)$', raw_amount)
            if frac_match:
                num, denom = int(frac_match.group(1)), int(frac_match.group(2))
                amount = str(num / denom) if denom else raw_amount
            else:
                amount = raw_amount.replace(',', '.')
            # Попытка найти единицу измерения
            for u in self._TR_UNITS:
                if rest.lower().startswith(u.lower()):
                    unit = u
                    name = rest[len(u):].strip().lstrip(',;').strip()
                    break
            else:
                name = rest
        else:
            # Проверяем начало на турецкие числительные ("bir", "iki" и т.д.)
            lower = text.lower()
            for tr_word, digit in self._TR_NUMBERS.items():
                if lower.startswith(tr_word + ' '):
                    rest = text[len(tr_word):].strip()
                    # Проверяем: следующее слово — единица измерения?
                    for u in self._TR_UNITS:
                        if rest.lower().startswith(u.lower()):
                            amount = digit
                            unit = u
                            name = rest[len(u):].strip().lstrip(',;').strip()
                            break
                    # Если единица не найдена — не разбиваем
                    break

        # Финальная очистка названия
        name = self.clean_text(name.lstrip(':;,').strip())
        if not name:
            name = self.clean_text(original)

        return {'name': name, 'amount': amount, 'unit': unit}

    # ------------------------------------------------------------------
    # Методы извлечения данных
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        article = self._get_article()
        if not article:
            return None
        h1 = article.find('h1')
        if not h1:
            return None
        name = self.clean_text(h1.get_text())
        # Убираем суффикс " Tarifi" (название рецепта на турецком)
        name = re.sub(r'\s+[Tt]arifi\s*$', '', name).strip()
        return name if name else None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта из og:description"""
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        # Запасной вариант — первый параграф контента статьи
        paragraphs = self._get_content_paragraphs()
        return self.clean_text(paragraphs[0]) if paragraphs else None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из HTML"""
        article = self._get_article()
        if not article:
            return None

        # Ищем заголовок секции ингредиентов
        malzeme_h2 = None
        for h2 in article.find_all('h2'):
            if 'Malzeme' in h2.get_text():
                malzeme_h2 = h2
                break

        if not malzeme_h2:
            logger.warning('Malzemeler section not found in %s', self.html_path)
            return None

        ul = malzeme_h2.find_next('ul')
        if not ul:
            logger.warning('Ingredients list not found in %s', self.html_path)
            return None

        ingredients = []
        for li in ul.find_all('li'):
            text = self.clean_text(li.get_text())
            if not text:
                continue
            parsed = self._parse_ingredient(text)
            if parsed:
                ingredients.append(parsed)

        if not ingredients:
            return None
        return json.dumps(ingredients, ensure_ascii=False)

    def extract_steps(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        article = self._get_article()
        if not article:
            return None

        # Ищем заголовок секции инструкций
        hazirlanis_h2 = None
        for h2 in article.find_all('h2'):
            if 'Hazırlanışı' in h2.get_text():
                hazirlanis_h2 = h2
                break

        if not hazirlanis_h2:
            logger.warning('Hazırlanışı section not found in %s', self.html_path)
            return None

        ol = hazirlanis_h2.find_next('ol')
        if not ol:
            logger.warning('Instructions list not found in %s', self.html_path)
            return None

        steps = []
        for li in ol.find_all('li'):
            text = self.clean_text(li.get_text())
            if text:
                steps.append(text)

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из секции тегов статьи"""
        container = self._get_etiketler_container()
        if not container:
            return None

        for a in container.find_all('a'):
            href = a.get('href', '')
            if '/blog/categories/' in href:
                return self.clean_text(a.get_text())

        return None

    def _extract_time_from_instructions(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени из текста инструкций.

        Args:
            time_type: 'cook' (dakika) или 'total' (saat)

        Returns:
            Строка вида "25-30 minutes" или "3 hours", или None
        """
        instructions_text = self.extract_steps()
        if not instructions_text:
            return None

        if time_type == 'cook':
            # Ищем паттерн: число/диапазон + "dakika" рядом с "pişir"
            # Например: "yaklaşık 25-30 dakika pişirin"
            pattern = re.compile(
                r'(\d+[-–]\d+|\d+)\s*dakika\b',
                re.IGNORECASE,
            )
            for match in pattern.finditer(instructions_text):
                context = instructions_text[
                    max(0, match.start() - 60): match.end() + 60
                ]
                if re.search(r'pişir', context, re.IGNORECASE):
                    value = match.group(1).replace('–', '-')
                    return f'{value} minutes'

        elif time_type == 'total':
            # Ищем паттерн: число/диапазон + "saat"
            pattern = re.compile(
                r'(\d+[-–]\d+|\d+)\s*saat\b',
                re.IGNORECASE,
            )
            match = pattern.search(instructions_text)
            if match:
                value = match.group(1).replace('–', '-')
                return f'{value} hours'

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки (обычно не указывается на сайте)"""
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления (dakika)"""
        return self._extract_time_from_instructions('cook')

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени (saat)"""
        return self._extract_time_from_instructions('total')

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок (параграф после инструкций)"""
        paragraphs = self._get_content_paragraphs()
        # Первый параграф — описание; остальные — заметки
        note_parts = [p for p in paragraphs[1:] if len(p) > 30]
        if not note_parts:
            return None
        return ' '.join(note_parts)

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из секции 'Etiketler'"""
        container = self._get_etiketler_container()
        if not container:
            return None

        tags = []
        for a in container.find_all('a'):
            href = a.get('href', '')
            if '/blog/tags/' in href:
                tag_text = self.clean_text(a.get_text())
                if tag_text:
                    tags.append(tag_text)

        return ', '.join(tags) if tags else None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []

        # 1. JSON-LD: BlogPosting имеет поле image
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.text)
                image = data.get('image')
                if isinstance(image, dict) and image.get('url'):
                    url = image['url']
                    if url and url not in urls:
                        urls.append(url)
                elif isinstance(image, str) and image:
                    if image not in urls:
                        urls.append(image)
            except (json.JSONDecodeError, AttributeError):
                continue

        # 2. og:image как запасной вариант
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                url = og_image['content']
                if url and url not in urls:
                    urls.append(url)

        return ','.join(urls) if urls else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта
        """
        try:
            dish_name = self.extract_dish_name()
        except Exception:
            logger.exception('Error extracting dish_name from %s', self.html_path)
            dish_name = None

        try:
            description = self.extract_description()
        except Exception:
            logger.exception('Error extracting description from %s', self.html_path)
            description = None

        try:
            ingredients = self.extract_ingredients()
        except Exception:
            logger.exception('Error extracting ingredients from %s', self.html_path)
            ingredients = None

        try:
            instructions = self.extract_steps()
        except Exception:
            logger.exception('Error extracting instructions from %s', self.html_path)
            instructions = None

        try:
            category = self.extract_category()
        except Exception:
            logger.exception('Error extracting category from %s', self.html_path)
            category = None

        try:
            prep_time = self.extract_prep_time()
        except Exception:
            logger.exception('Error extracting prep_time from %s', self.html_path)
            prep_time = None

        try:
            cook_time = self.extract_cook_time()
        except Exception:
            logger.exception('Error extracting cook_time from %s', self.html_path)
            cook_time = None

        try:
            total_time = self.extract_total_time()
        except Exception:
            logger.exception('Error extracting total_time from %s', self.html_path)
            total_time = None

        try:
            notes = self.extract_notes()
        except Exception:
            logger.exception('Error extracting notes from %s', self.html_path)
            notes = None

        try:
            tags = self.extract_tags()
        except Exception:
            logger.exception('Error extracting tags from %s', self.html_path)
            tags = None

        try:
            image_urls = self.extract_image_urls()
        except Exception:
            logger.exception('Error extracting image_urls from %s', self.html_path)
            image_urls = None

        return {
            'dish_name': dish_name,
            'description': description,
            'ingredients': ingredients,
            'instructions': instructions,
            'category': category,
            'prep_time': prep_time,
            'cook_time': cook_time,
            'total_time': total_time,
            'notes': notes,
            'image_urls': image_urls,
            'tags': tags,
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os

    preprocessed_dir = os.path.join('preprocessed', 'bonkers_com_tr')

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(BonkersComTrExtractor, preprocessed_dir)
        return

    print(f'Директория не найдена: {preprocessed_dir}')
    print('Использование: python bonkers_com_tr.py')


if __name__ == '__main__':
    main()
