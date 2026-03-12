"""
Экстрактор данных рецептов для сайта becook.com
"""

import sys
import re
import json
import logging
from pathlib import Path
from typing import Optional

from bs4 import NavigableString, Tag

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class BecookComExtractor(BaseRecipeExtractor):
    """Экстрактор для becook.com"""

    def _get_base_url(self) -> str:
        """Извлечение базового URL из тега <base>"""
        base_tag = self.soup.find('base', href=True)
        if base_tag:
            return base_tag['href'].rstrip('/')
        return "http://www.becook.com"

    def _make_absolute_url(self, url: str) -> str:
        """Преобразование относительного URL в абсолютный"""
        if not url:
            return url
        if url.startswith('http://') or url.startswith('https://'):
            return url
        base = self._get_base_url()
        return base + '/' + url.lstrip('/')

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        title_div = self.soup.find('div', id='title')
        if title_div:
            h1 = title_div.find('h1')
            if h1:
                return self.clean_text(h1.get_text())

        # Резервный вариант: meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        # Резервный вариант: тег <title>
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Формат: "BeCook.com - Dish Name - ..."
            parts = title.split(' - ')
            if len(parts) >= 2:
                return self.clean_text(parts[1])

        logger.warning("Could not extract dish_name from %s", self.html_path)
        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        short_div = self.soup.find('div', id='short')
        if short_div:
            text = self.clean_text(short_div.get_text())
            if text:
                return text

        # Резервный вариант: meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        logger.warning("Could not extract description from %s", self.html_path)
        return None

    def _parse_amount_unit(self, th_text: str) -> tuple:
        """
        Парсинг количества и единицы из текста <th>

        Args:
            th_text: Текст вида "2 kašičice", "600 g", " malo", " po ukusu", " kom"

        Returns:
            Кортеж (amount, unit)
        """
        text = th_text.strip()
        if not text:
            return (None, None)

        # Числовое количество + единица: "2 kašičice", "600 g", "0.5 kašičice"
        match = re.match(r'^([\d.,]+)\s+(.+)$', text)
        if match:
            return (match.group(1), match.group(2).strip())

        # Только число: "2", "600"
        if re.match(r'^[\d.,]+$', text):
            return (text, None)

        # Текстовое количество без единицы: "malo", "po ukusu", "kom"
        return (text, None)

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из таблицы"""
        ingredients = []

        ingredients_div = self.soup.find('div', id='ingredients')
        if not ingredients_div:
            logger.warning("No ingredients div found in %s", self.html_path)
            return None

        table = ingredients_div.find('table')
        if not table:
            logger.warning("No ingredients table found in %s", self.html_path)
            return None

        rows = table.find_all('tr')
        for row in rows:
            th = row.find('th')
            td = row.find('td')

            if not th or not td:
                continue

            th_text = self.clean_text(th.get_text())
            name = self.clean_text(td.get_text())

            if not name:
                continue

            amount, unit = self._parse_amount_unit(th_text)

            ingredients.append({
                "name": name,
                "unit": unit,
                "amount": amount
            })

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def _collect_recipe_text(self, element, skip_tips: bool = True) -> list:
        """
        Рекурсивный обход дочерних элементов с пропуском специальных тегов.

        Args:
            element: BeautifulSoup элемент для обхода
            skip_tips: Пропускать ли span.tip и span.alert

        Returns:
            Список строк текста
        """
        parts = []
        for child in element.children:
            if isinstance(child, NavigableString):
                text = str(child)
                if text.strip():
                    parts.append(text)
            elif isinstance(child, Tag):
                # Пропускаем скрипты и изображения
                if child.name in ('script', 'img'):
                    continue
                # Пропускаем ссылки на JavaScript (viewImage)
                if child.name == 'a':
                    href = child.get('href', '')
                    if href.startswith('javascript:'):
                        continue
                # Пропускаем заголовки секций рецепта
                if child.name in ('h1', 'h2', 'h3'):
                    continue
                # Пропускаем советы и предупреждения
                if skip_tips and child.name == 'span':
                    classes = set(child.get('class', []))
                    if classes & {'tip', 'alert'}:
                        continue
                # Для тега <br> добавляем перенос строки
                if child.name == 'br':
                    parts.append('\n')
                    continue
                # Рекурсивный обход
                parts.extend(self._collect_recipe_text(child, skip_tips))
        return parts

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_div = self.soup.find('div', id='recipe')
        if not recipe_div:
            logger.warning("No recipe div found in %s", self.html_path)
            return None

        parts = self._collect_recipe_text(recipe_div, skip_tips=True)
        text = ''.join(parts)

        # Убираем [tip=N]...[/tip] блоки
        text = re.sub(r'\[tip=\d+\].*?\[/tip\]', '', text, flags=re.DOTALL)

        # Убираем "Prijatno!" в конце
        text = re.sub(r'\s*Prijatno!\s*$', '', text.rstrip(), flags=re.IGNORECASE)

        # Нормализуем: разбиваем на строки и убираем пустые
        lines = [line.strip() for line in text.split('\n')]
        lines = [line for line in lines if line]

        return '\n'.join(lines) if lines else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из хлебных крошек"""
        path_div = self.soup.find('div', id='path')
        if not path_div:
            return None

        links = path_div.find_all('a')
        # Берем последний элемент (самая специфичная категория)
        # Хлебные крошки: Recepti > Jela sa mesom > Govedina
        if len(links) >= 2:
            return self.clean_text(links[-1].get_text())
        elif len(links) == 1:
            return self.clean_text(links[0].get_text())

        return None

    def extract_preparation_time(self) -> Optional[str]:
        """
        Извлечение времени приготовления из li#preparation.
        Используется как значение для cook_time и total_time,
        поскольку сайт хранит единое поле «Priprema» без разделения
        на prep/cook.
        """
        prep_li = self.soup.find('li', id='preparation')
        if prep_li:
            text = self.clean_text(prep_li.get_text())
            # Формат: "Priprema: 120 min"
            match = re.search(r'(\d+)\s*min', text, re.IGNORECASE)
            if match:
                minutes = int(match.group(1))
                return f"{minutes} minutes"

        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов из span.tip, span.alert и [tip] блоков"""
        recipe_div = self.soup.find('div', id='recipe')
        if not recipe_div:
            return None

        notes_parts = []

        # Извлекаем <span class="tip"> и <span class="alert">
        for span in recipe_div.find_all('span', class_=['tip', 'alert']):
            text = self.clean_text(span.get_text())
            if text:
                notes_parts.append(text)

        # Извлекаем [tip=N]...[/tip] блоки из исходного текста
        raw_text = recipe_div.get_text()
        for match in re.finditer(r'\[tip=\d+\](.*?)\[/tip\]', raw_text, re.DOTALL):
            text = self.clean_text(match.group(1))
            if text:
                notes_parts.append(text)

        if notes_parts:
            return ' '.join(notes_parts)

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из div#tags"""
        tags_div = self.soup.find('div', id='tags')
        if not tags_div:
            return None

        tag_links = tags_div.find_all('a')
        tags = []
        for link in tag_links:
            tag = self.clean_text(link.get_text())
            if tag:
                tags.append(tag)

        return ', '.join(tags) if tags else None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений (главное + пошаговые)"""
        urls = []
        seen = set()

        def add_url(raw_url: str) -> None:
            url = self._make_absolute_url(raw_url)
            if url and url not in seen:
                urls.append(url)
                seen.add(url)

        # 1. Главное изображение рецепта
        main_img = self.soup.find('img', id='recipe-image')
        if main_img and main_img.get('src'):
            add_url(main_img['src'])

        # 2. Дополнительные изображения из JavaScript: recipeImages[N] = 'url';
        for script in self.soup.find_all('script'):
            if not script.string:
                continue
            for match in re.finditer(r"recipeImages\[\d+\]\s*=\s*'([^']+)'", script.string):
                add_url(match.group(1))

        # 3. Пошаговые изображения из div#recipe (thumbnails -> full size)
        recipe_div = self.soup.find('div', id='recipe')
        if recipe_div:
            for img in recipe_div.find_all('img'):
                src = img.get('src', '')
                if src:
                    # Конвертируем thumbnails в полноразмерные изображения
                    full_src = src.replace('uploads/recipes/thumbnails/', 'uploads/recipes/')
                    add_url(full_src)

        if not urls:
            return None

        return ','.join(urls)

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта

        Returns:
            Словарь с данными рецепта
        """
        total_time = self.extract_preparation_time()

        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_steps(),
            "category": self.extract_category(),
            "prep_time": None,
            "cook_time": total_time,
            "total_time": total_time,
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags(),
        }


def main():
    import os
    recipes_dir = os.path.join("preprocessed", "becook_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(BecookComExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python becook_com.py [путь_к_файлу_или_директории]")


if __name__ == "__main__":
    main()
