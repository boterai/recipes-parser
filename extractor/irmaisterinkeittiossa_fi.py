"""
Экстрактор данных рецептов для сайта irmaisterinkeittiossa.fi
"""

import sys
import json
import logging
import re
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)

# Стандартные единицы измерения (извлекаются в поле unit)
FINNISH_UNITS = [
    'rkl',   # ruokalusikka (столовая ложка)
    'tl',    # teelusikka (чайная ложка)
    'dl',    # deciliter
    'ml',    # milliliter
    'kg',    # kilogram
    'mg',    # milligram
    'kpl',   # kappale (штука)
    'annos', # annos (порция)
    'pussi', # pussi (пакет, полная форма)
    'l',     # liter
    'g',     # gram
]

# Аббревиатуры контейнеров — включаются в поле amount вместе с числом
CONTAINER_ABBREVS = ['prk', 'tlk', 'pkt', 'ps']

# Слова-количества (не числа, но обозначают количество)
QUANTITY_WORDS = ['muutama', 'muutaman', 'pari']


class IrmaisterinkeittiossaFiExtractor(BaseRecipeExtractor):
    """Экстрактор для irmaisterinkeittiossa.fi"""

    def _parse_ingredient(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный словарь.

        Args:
            text: текст ингредиента из <li>

        Returns:
            Словарь {name, amount, unit} или None если текст пустой
        """
        # Если весь текст в скобках — снимаем обёртку, но сохраняем содержимое
        if text.startswith('(') and text.endswith(')'):
            text = text[1:-1].strip()
            # Убираем вводные слова вроде "haluteessasi" (если хочешь), "tarvittaessa" и т.п.
            text = re.sub(r'^(haluteessasi|tarvittaessa|halutessasi)\s+', '', text, flags=re.IGNORECASE)
        else:
            # Удаляем инлайн-примечания в скобках (не сам ингредиент)
            text = re.sub(r'\([^)]*\)', '', text).strip()

        if not text:
            return None

        amount: Optional[str] = None
        unit: Optional[str] = None
        name: str = text

        # Убираем приблизительное "noin" или "n." в начале
        text_clean = re.sub(r'^n\.?\s+', '', text.strip(), flags=re.IGNORECASE)

        # Паттерн для числа в начале: целое, диапазон, дробь, десятичное
        num_pattern = r'^(\d+(?:[,./]\d+)?(?:\s*-\s*\d+(?:[,./]\d+)?)?)'
        num_match = re.match(num_pattern, text_clean)

        if num_match:
            amount_str = num_match.group(1).strip()
            rest = text_clean[num_match.end():].strip()

            # Сначала проверяем аббревиатуры контейнеров (входят в amount)
            for abbrev in CONTAINER_ABBREVS:
                pattern = r'^(' + re.escape(abbrev) + r')(?:\s|$)'
                m = re.match(pattern, rest, re.IGNORECASE)
                if m:
                    amount_str = amount_str + ' ' + abbrev
                    rest = rest[m.end():].strip()
                    break

            # Затем проверяем стандартные единицы измерения
            matched_unit = None
            matched_rest = rest
            for u in FINNISH_UNITS:
                pattern = r'^(' + re.escape(u) + r')(?:\s|$)'
                m = re.match(pattern, rest, re.IGNORECASE)
                if m:
                    matched_unit = u
                    matched_rest = rest[m.end():].strip()
                    break

            amount = amount_str
            unit = matched_unit
            name = matched_rest if matched_rest else rest
        else:
            # Нет числа: проверяем слова-количества (muutama, pari)
            words = text_clean.split()
            if words and words[0].lower() in QUANTITY_WORDS:
                unit = words[0].lower()
                name = ' '.join(words[1:]) if len(words) > 1 else text_clean
            else:
                name = text_clean

        cleaned_name = self.clean_text(name) if name else None
        return {
            "name": cleaned_name,
            "amount": amount,
            "unit": unit,
        }

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда из h1 в article"""
        article = self.soup.find('article')
        if article:
            h1 = article.find('h1')
            if h1:
                return self.clean_text(h1.get_text())

        # Запасной вариант — og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        logger.warning("dish_name not found")
        return None

    def extract_description(self) -> Optional[str]:
        """
        Извлечение описания рецепта.

        На сайте irmaisterinkeittiossa.fi отдельного текстового блока-описания
        в теле статьи нет, поэтому возвращаем None.
        """
        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из раздела AINEKSET.

        Returns:
            JSON-строка со списком ингредиентов или None
        """
        article = self.soup.find('article')
        if not article:
            logger.warning("Article element not found")
            return None

        # Ищем h2 с заголовком раздела ингредиентов
        ingredients_h2 = None
        for h2 in article.find_all('h2'):
            if 'AINEKSET' in h2.get_text().upper():
                ingredients_h2 = h2
                break

        if not ingredients_h2:
            logger.warning("Ingredients section (AINEKSET) not found")
            return None

        # Ищем список ul, следующий за h2
        ul = ingredients_h2.find_next('ul')
        if not ul:
            logger.warning("Ingredients <ul> not found after AINEKSET heading")
            return None

        ingredients = []
        for li in ul.find_all('li'):
            text = li.get_text().strip()
            if not text:
                continue
            ingredient = self._parse_ingredient(text)
            if ingredient and ingredient.get('name'):
                ingredients.append(ingredient)

        if not ingredients:
            return None

        return json.dumps(ingredients, ensure_ascii=False)

    def extract_instructions(self) -> Optional[str]:
        """
        Извлечение шагов приготовления из раздела VALMISTUS.

        Returns:
            Строка со всеми шагами или None
        """
        article = self.soup.find('article')
        if not article:
            return None

        # Ищем h2 с заголовком раздела приготовления
        instructions_h2 = None
        for h2 in article.find_all('h2'):
            if 'VALMISTUS' in h2.get_text().upper():
                instructions_h2 = h2
                break

        if not instructions_h2:
            logger.warning("Instructions section (VALMISTUS) not found")
            return None

        # Собираем текст из <p> тегов после h2 до следующего h2
        steps = []
        current = instructions_h2.next_sibling
        while current:
            if hasattr(current, 'name') and current.name:
                if current.name == 'h2':
                    break
                if current.name == 'p':
                    step_text = self.clean_text(current.get_text())
                    if step_text:
                        steps.append(step_text)
            current = current.next_sibling

        return ' '.join(steps) if steps else None

    def _extract_categories(self) -> list:
        """Извлечение списка категорий из заголовка статьи"""
        article = self.soup.find('article')
        if not article:
            return []

        # Ищем ссылки-категории по href с параметром categories
        categories = []
        for a in article.find_all('a', href=re.compile(r'categories=')):
            text = self.clean_text(a.get_text())
            if text:
                categories.append(text)

        return categories

    def extract_category(self) -> Optional[str]:
        """Извлечение первичной категории рецепта"""
        categories = self._extract_categories()
        return categories[0] if categories else None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из дополнительных категорий"""
        categories = self._extract_categories()
        if len(categories) > 1:
            return ','.join(c.lower() for c in categories[1:])
        return None

    def extract_image_urls(self) -> Optional[str]:
        """
        Извлечение URL основного изображения рецепта.

        Returns:
            URL изображения или None
        """
        # Ищем основное изображение (атрибут data-main-image)
        img = self.soup.find('img', attrs={'data-main-image': True})
        if img:
            src = img.get('src', '')
            if src and src.startswith('http'):
                # Берём базовый URL без параметров трансформации Sanity CDN
                return src.split('?')[0]

        # Запасной вариант — og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            return og_image['content']

        return None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с полями рецепта
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()

        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": None,
            "cook_time": None,
            "total_time": None,
            "notes": None,
            "tags": tags,
            "image_urls": image_urls,
        }


def main():
    import os
    recipes_dir = os.path.join("preprocessed", "irmaisterinkeittiossa_fi")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(IrmaisterinkeittiossaFiExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python irmaisterinkeittiossa_fi.py")


if __name__ == "__main__":
    main()
