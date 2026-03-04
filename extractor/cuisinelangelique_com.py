"""
Экстрактор данных рецептов для сайта cuisinelangelique.com
"""

import logging
import sys
import copy
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class CuisineLangeliqueExtractor(BaseRecipeExtractor):
    """Экстрактор для cuisinelangelique.com"""

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_time_text(text: str) -> Optional[str]:
        """
        Извлекает число минут из текста вида «20 MINUTES» или «1H 30 MINUTES»
        и возвращает строку «N minutes».

        Args:
            text: текст вида «PRÉPARATION : 20 MINUTES»

        Returns:
            Строка «N minutes» или None
        """
        # Извлекаем числа и единицы (часы/минуты)
        text_upper = text.upper()
        hours = 0
        minutes = 0

        h_match = re.search(r'(\d+)\s*H(?:EURE)?S?\b', text_upper)
        m_match = re.search(r'(\d+)\s*MIN', text_upper)

        if h_match:
            hours = int(h_match.group(1))
        if m_match:
            minutes = int(m_match.group(1))

        total = hours * 60 + minutes
        return f"{total} minutes" if total > 0 else None

    @staticmethod
    def _parse_ingredient_text(text: str) -> Optional[dict]:
        """
        Парсит строку ингредиента в структурированный формат.

        Обрабатывает французский формат сайта:
          «210 g (1 1/2 tasse) de farine tout usage»
          «0,5 ml (1/8 c. à thé) de sel»
          «3 oeufs larges, blancs séparés des jaunes»

        Returns:
            dict {'name': str, 'amount': int|float, 'unit': str} или None
        """
        if not text:
            return None

        # Нормализуем запятую-разделитель дробной части
        text = re.sub(r'(\d),(\d)', r'\1.\2', text.strip())
        # Нормализуем множественные пробелы
        text = re.sub(r'\s+', ' ', text)

        # --- Паттерн 1: «число [g|ml] [(опционально)] [de |d'] название[, примечания]» ---
        p1 = re.match(
            r'^([\d.]+)\s*(g|ml)\s*(?:\([^)]*\))?\s*(?:de\s+|d\')(.+?)(?:\s*[*]+\s*.*)?$',
            text,
            re.IGNORECASE,
        )
        if p1:
            amount_str, unit, name = p1.groups()
            amount_val = float(amount_str)
            amount: int | float = int(amount_val) if amount_val == int(amount_val) else amount_val
            # Очищаем название: убираем запятую с примечаниями в конце
            name = re.sub(r',.*$', '', name).strip()
            # Убираем остаточные * и пробелы
            name = name.rstrip('* ').strip()
            return {"name": name, "amount": amount, "unit": unit.lower()}

        # --- Паттерн 2: «число название[, примечания]» (без единицы измерения) ---
        p2 = re.match(r'^(\d+)\s+([^\s,]+(?:\s+[^\s,]+)?)(?:,.*)?$', text)
        if p2:
            amount_str, name_part = p2.groups()
            # Берём только первое слово как название ингредиента
            first_word = name_part.split()[0]
            return {"name": first_word, "amount": int(amount_str), "unit": "unit"}

        # --- Запасной вариант: возвращаем весь текст как название ---
        return {"name": text, "amount": None, "unit": None}

    # ------------------------------------------------------------------
    # Методы извлечения отдельных полей
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из <span class='lead'> внутри h1[itemprop='name']"""
        h1 = self.soup.find('h1', itemprop='name')
        if h1:
            lead = h1.find('span', class_='lead')
            if lead:
                return self.clean_text(lead.get_text())
            # Запасной вариант: полный текст h1 без bio-sans-gluten
            bio = h1.find('span', class_='bio-sans-gluten')
            if bio:
                bio.decompose()
            return self.clean_text(h1.get_text())
        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания из <span class='bio-sans-gluten'> в h1"""
        h1 = self.soup.find('h1', itemprop='name')
        if h1:
            bio = h1.find('span', class_='bio-sans-gluten')
            if bio:
                return self.clean_text(bio.get_text())
        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из <ul itemprop='ingredients'>.

        Возвращает JSON-строку со списком объектов
        {'name': str, 'amount': int|float|None, 'unit': str|None}.
        """
        ingredients = []

        for ul in self.soup.find_all('ul', itemprop='ingredients'):
            for li in ul.find_all('li'):
                # Работаем с копией, чтобы не изменять оригинал
                li_copy = copy.copy(li)

                # Удаляем <em> блоки (содержат примечания и рекламные ссылки)
                for em in li_copy.find_all('em'):
                    em.decompose()

                # Получаем чистый текст ингредиента
                raw = li_copy.get_text(separator=' ', strip=True)
                raw = self.clean_text(raw)

                if not raw:
                    continue

                parsed = self._parse_ingredient_text(raw)
                if parsed:
                    ingredients.append(parsed)

        if not ingredients:
            logger.warning("Ингредиенты не найдены: %s", self.html_path)
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def extract_instructions(self) -> Optional[str]:
        """
        Извлечение инструкций из всех <ol> в основном блоке рецепта.

        Основная секция инструкций имеет itemprop='recipeInstructions'.
        Дополнительные секции (например, отдельный раздел конфитюра) могут
        располагаться в дополнительных <ol> без этого атрибута внутри
        того же блока <article role='main'>.
        """
        # Ищем основной блок статьи
        article = self.soup.find('article', role='main')
        search_root = article if article else self.soup

        # Находим первый ol с recipeInstructions
        first_ol = search_root.find('ol', itemprop='recipeInstructions')
        if not first_ol:
            logger.warning("Инструкции не найдены: %s", self.html_path)
            return None

        steps = []

        # Собираем шаги из основного ol
        for li in first_ol.find_all('li'):
            text = self.clean_text(li.get_text(separator=' ', strip=True))
            if text:
                steps.append(text)

        # Собираем шаги из дополнительных ol (без itemprop), следующих после основного
        for sibling in first_ol.find_next_siblings():
            if sibling.name == 'ol' and not sibling.get('itemprop'):
                for li in sibling.find_all('li'):
                    text = self.clean_text(li.get_text(separator=' ', strip=True))
                    if text:
                        steps.append(text)

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """
        Категория на сайте не указывается явно на странице рецепта.
        Возвращает None.
        """
        return None

    def _extract_time_element(self, itemprop_value: str, label_keyword: str) -> Optional[str]:
        """
        Ищет <time itemprop='...'> с нужной меткой (PRÉPARATION, CUISSON и т.д.)
        и возвращает значение в минутах.

        Args:
            itemprop_value: значение атрибута itemprop («prepTime», «cookTime» и т.д.)
            label_keyword:  ключевое слово в тексте метки (без учёта регистра)

        Returns:
            Строка «N minutes» или None
        """
        for time_el in self.soup.find_all('time', itemprop=itemprop_value):
            text = time_el.get_text(separator=' ', strip=True)
            if label_keyword.lower() in text.lower():
                strong = time_el.find('strong')
                time_text = strong.get_text(strip=True) if strong else text
                result = self._parse_time_text(time_text)
                if result:
                    return result
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки (метка PRÉPARATION)"""
        return self._extract_time_element('prepTime', 'PRÉPARATION')

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления (метка CUISSON)"""
        return self._extract_time_element('cookTime', 'CUISSON')

    def extract_total_time(self) -> Optional[str]:
        """
        Общее время вычисляется как сумма времени подготовки и приготовления.
        Если одно из значений недоступно — возвращает None.
        """
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        if not prep or not cook:
            return None

        def _to_minutes(time_str: str) -> Optional[int]:
            m = re.search(r'(\d+)', time_str)
            return int(m.group(1)) if m else None

        prep_min = _to_minutes(prep)
        cook_min = _to_minutes(cook)
        if prep_min is not None and cook_min is not None:
            return f"{prep_min + cook_min} minutes"
        return None

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок/советов к рецепту.

        Приоритет:
        1. Первый <p> после <h3> с «CONSEIL PRATIQUE»
        2. Первый <p> после <h3> с «VARIANTE»
        3. Первый <p><em> или <em><strong> в основном блоке контента
        """
        # Ищем блок col-md-10 — основной контентный контейнер рецепта
        content_block = self.soup.find('div', class_='col-md-10')
        if not content_block:
            return None

        def _clean_note(text: str) -> str:
            # Убираем ведущие * ** и пробелы
            return re.sub(r'^[\s*]+', '', text).strip()

        # 1 + 2. Ищем CONSEIL PRATIQUE или VARIANTE
        for h3 in content_block.find_all('h3'):
            heading_text = h3.get_text(strip=True).upper()
            if 'CONSEIL PRATIQUE' in heading_text or 'VARIANTE' in heading_text:
                # Берём первый <p> после h3
                sibling = h3.find_next_sibling()
                while sibling:
                    if sibling.name == 'p':
                        note_text = self.clean_text(sibling.get_text(separator=' ', strip=True))
                        note_text = _clean_note(note_text)
                        if note_text:
                            return note_text
                    sibling = sibling.find_next_sibling()

        # 3. Запасной вариант: <p><em> или <em><strong> в контентном блоке
        for child in content_block.children:
            if not hasattr(child, 'name'):
                continue
            if child.name == 'p':
                em = child.find('em')
                if em:
                    text = self.clean_text(em.get_text(separator=' ', strip=True))
                    if text:
                        return text
            elif child.name == 'em':
                text = self.clean_text(child.get_text(separator=' ', strip=True))
                if text:
                    return text

        return None

    def extract_tags(self) -> Optional[str]:
        """
        Извлечение тегов из текста <span class='bio-sans-gluten'>.

        Разбивает описание на ключевые слова диетических категорий:
        «sans gluten», «sans produits laitiers», «hypotoxique», «végétalien» и т.д.
        """
        description = self.extract_description()
        if not description:
            return None

        # Убираем «Recette» в начале
        desc = re.sub(r'^Recette\s+', '', description, flags=re.IGNORECASE).strip()
        # Убираем скобочные пояснения вида «(sans caséine)»
        desc = re.sub(r'\([^)]*\)', '', desc)
        # Убираем точку в конце
        desc = desc.rstrip('.')

        # Разбиваем по «,» и «et» с нормализацией
        parts = re.split(r',|\bet\b', desc, flags=re.IGNORECASE)

        tags = []
        seen: set = set()
        for part in parts:
            # Нормализуем форму (végétalienne → végétalien)
            tag = re.sub(r'ienne$', 'ien', part.strip(), flags=re.IGNORECASE)
            tag = self.clean_text(tag).lower()
            if tag and len(tag) >= 3 and tag not in seen:
                seen.add(tag)
                tags.append(tag)

        return ', '.join(tags) if tags else None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL главного изображения рецепта"""
        urls = []

        # 1. Основное фото с itemprop='image'
        img = self.soup.find('img', itemprop='image')
        if img:
            src = img.get('src') or img.get('data-src')
            if src:
                urls.append(src)

        # 2. og:image в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # Убираем дубликаты, сохраняя порядок
        seen: set = set()
        unique: list = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    # ------------------------------------------------------------------
    # Главный метод
    # ------------------------------------------------------------------

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с полями: dish_name, description, ingredients,
            instructions, category, prep_time, cook_time, total_time,
            notes, image_urls, tags.
        """
        try:
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
        except Exception as exc:
            logger.error("Ошибка при извлечении данных из %s: %s", self.html_path, exc)
            return {
                "dish_name": None,
                "description": None,
                "ingredients": None,
                "instructions": None,
                "category": None,
                "prep_time": None,
                "cook_time": None,
                "total_time": None,
                "notes": None,
                "image_urls": None,
                "tags": None,
            }


def main() -> None:
    """Точка входа: обрабатывает директорию preprocessed/cuisinelangelique_com"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "cuisinelangelique_com")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(CuisineLangeliqueExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python cuisinelangelique_com.py")


if __name__ == "__main__":
    main()
