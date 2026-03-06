"""
Экстрактор данных рецептов для сайта izekesillatok.hu
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


class IzekesIllatokHuExtractor(BaseRecipeExtractor):
    """Экстрактор для izekesillatok.hu"""

    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD типа Recipe из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')

        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue

                data = json.loads(script.string)

                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            item_type = item.get('@type', '')
                            if isinstance(item_type, list) and 'Recipe' in item_type:
                                return item
                            elif item_type == 'Recipe':
                                return item
                elif isinstance(data, dict):
                    item_type = data.get('@type', '')
                    if isinstance(item_type, list) and 'Recipe' in item_type:
                        return data
                    elif item_type == 'Recipe':
                        return data

            except (json.JSONDecodeError, KeyError):
                continue

        return None

    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат

        Args:
            duration: строка вида "PT20M" или "PT1H30M"

        Returns:
            Время в формате "20 minutes" или "1 hour 30 minutes"
        """
        if not duration or not duration.startswith('PT'):
            return None

        duration = duration[2:]  # Убираем "PT"

        hours = 0
        minutes = 0

        hour_match = re.search(r'(\d+)H', duration)
        if hour_match:
            hours = int(hour_match.group(1))

        min_match = re.search(r'(\d+)M', duration)
        if min_match:
            minutes = int(min_match.group(1))

        if minutes >= 60 and hours == 0:
            hours = minutes // 60
            minutes = minutes % 60

        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")

        return ' '.join(parts) if parts else None

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])

        # Из h1 с классом recipe-title-main
        h1 = self.soup.find('h1', class_='recipe-title-main')
        if h1:
            return self.clean_text(h1.get_text())

        # Из h1 в общем случае
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        # Из og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])

        logger.warning("dish_name не найдено")
        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Приоритет: первый абзац секции recipe-story-main
        story = self.soup.find('div', class_='recipe-story-main')
        if story:
            first_p = story.find('p')
            if first_p:
                text = self.clean_text(first_p.get_text())
                if text:
                    return text

        # Из JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])

        # Из meta description
        meta_desc = self.soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        logger.warning("description не найдено")
        return None

    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов.

        Основной источник — HTML-блок .ingredient-item с data-атрибутами
        (data-name, data-quantity, data-unit), где name/amount/unit уже разделены.
        Запасной вариант — JSON-LD recipeIngredient.
        """
        ingredients = []

        # Приоритет: HTML ingredient-item (name/amount/unit уже разделены)
        ingredient_items = self.soup.find_all('div', class_='ingredient-item')
        if ingredient_items:
            for item in ingredient_items:
                name = item.get('data-name', '').strip()
                quantity = item.get('data-quantity', '').strip()
                unit = item.get('data-unit', '').strip()

                if not name:
                    # Попытка извлечь из внутренних span-элементов
                    name_span = item.find('span', class_='ingredient-name')
                    qty_span = item.find('span', class_='ingredient-quantity')
                    unit_span = item.find('span', class_='ingredient-unit')
                    if name_span:
                        name = self.clean_text(name_span.get_text())
                    if qty_span:
                        quantity = self.clean_text(qty_span.get_text())
                    if unit_span:
                        unit = self.clean_text(unit_span.get_text())

                if name:
                    ingredients.append({
                        "name": self.clean_text(name),
                        "amount": quantity if quantity else None,
                        "unit": unit if unit else None,
                    })

            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)

        # Запасной вариант: JSON-LD recipeIngredient
        json_ld = self._get_json_ld_data()
        if json_ld and 'recipeIngredient' in json_ld:
            for ingredient_text in json_ld['recipeIngredient']:
                parsed = self._parse_ingredient_text(ingredient_text)
                if parsed:
                    ingredients.append(parsed)

        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)

        logger.warning("ingredients не найдено")
        return None

    def _parse_ingredient_text(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента вида "3 db Túlérett banán" в словарь.

        Args:
            text: Строка вида "250 g Gluténmentes lisztkeverék"

        Returns:
            dict: {"name": "...", "amount": "...", "unit": "..."}
        """
        if not text:
            return None

        text = self.clean_text(text)

        # Паттерн для венгерских и стандартных единиц измерения
        pattern = (
            r'^([\d\s/.,½¼¾⅓⅔⅛]+)?\s*'
            r'(db|g|kg|ml|dl|l|tk\.|ek\.|csipet|fej|csokor|szelet|gerezd|'
            r'cups?|tbsp?|tsp?|tablespoons?|teaspoons?|oz|lbs?|pinch)?\s*'
            r'(.+)'
        )

        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            amount = (match.group(1) or '').strip() or None
            unit = (match.group(2) or '').strip() or None
            name = (match.group(3) or '').strip() or text
        else:
            amount = None
            unit = None
            name = text

        return {
            "name": name,
            "amount": amount,
            "unit": unit,
        }

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []

        # Из JSON-LD recipeInstructions
        json_ld = self._get_json_ld_data()
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        steps.append(f"{idx}. {step['text']}")
                    elif isinstance(step, str):
                        steps.append(f"{idx}. {step}")

            if steps:
                return ' '.join(steps)

        # Запасной вариант: HTML шаги приготовления
        steps_container = self.soup.find(class_=re.compile(r'step.*list|instruction.*list|recipe.*steps', re.I))
        if steps_container:
            step_items = steps_container.find_all('li')
            if not step_items:
                step_items = steps_container.find_all('p')
            for item in step_items:
                step_text = self.clean_text(item.get_text(separator=' ', strip=True))
                if step_text:
                    steps.append(step_text)

        if steps:
            if not re.match(r'^\d+\.', steps[0]):
                steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
            return ' '.join(steps)

        logger.warning("instructions не найдено")
        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Из JSON-LD recipeCategory
        json_ld = self._get_json_ld_data()
        if json_ld and 'recipeCategory' in json_ld:
            category = json_ld['recipeCategory']
            if isinstance(category, list):
                # Фильтруем автоматически сгенерированные категории
                filtered = [c for c in category if '(Auto)' not in c]
                if filtered:
                    return ', '.join(filtered)
                elif category:
                    return ', '.join(category)
            elif isinstance(category, str):
                return self.clean_text(category)

        # Из HTML тегов категорий
        category_tags = self.soup.find_all('a', class_='category-tag')
        if category_tags:
            categories = [self.clean_text(tag.get_text()) for tag in category_tags]
            categories = [c for c in categories if c]
            if categories:
                return ', '.join(categories)

        # Из хлебных крошек
        breadcrumbs = self.soup.find(class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())

        logger.warning("category не найдено")
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self._get_json_ld_data()
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])

        return self._extract_time_from_html('Előkészítés')

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_data()
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])

        return self._extract_time_from_html('Főzés')

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])

        return self._extract_time_from_html('Teljes idő')

    def _extract_time_from_html(self, label: str) -> Optional[str]:
        """
        Извлечение значения времени из HTML блока recipe-meta-card по метке.

        Args:
            label: Метка, например 'Előkészítés', 'Főzés', 'Teljes idő'
        """
        meta_items = self.soup.find_all('div', class_='recipe-meta-item')
        for item in meta_items:
            label_span = item.find('span', class_='meta-label')
            if label_span and self.clean_text(label_span.get_text()) == label:
                value_span = item.find('span', class_='meta-value')
                if value_span:
                    return self.clean_text(value_span.get_text())
        return None

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок и советов к рецепту.

        Источники (в порядке приоритета):
        1. Советы (Tipp:) из секции recipe-story-main
        2. Ответы из FAQ блока (dl > dd)
        3. Советы из step-tip-interactive блоков
        """
        notes_parts = []
        seen: set = set()

        def _add_note(text: str) -> None:
            text = self.clean_text(text)
            if text and text not in seen:
                seen.add(text)
                notes_parts.append(text)

        # 1. Советы из recipe-story-main (после тега <b>Tipp:</b>)
        story = self.soup.find('div', class_='recipe-story-main')
        if story:
            # Обходим все текстовые узлы после жирного тега "Tipp:"
            bold_tags = story.find_all('b')
            for bold in bold_tags:
                if 'Tipp' in bold.get_text():
                    # Собираем текст следующих текстовых/inline-узлов
                    tip_text = ''
                    for sibling in bold.next_siblings:
                        if hasattr(sibling, 'name') and sibling.name in ('p', 'div', 'br'):
                            break
                        tip_text += str(sibling)
                    tip_text = re.sub(r'<[^>]+>', '', tip_text)
                    tip_text = self.clean_text(tip_text)
                    if tip_text:
                        _add_note(tip_text)

        # 2. Ответы из FAQ-блока (dl > dd)
        faq_dl = self.soup.find('dl')
        if faq_dl:
            for dd in faq_dl.find_all('dd'):
                _add_note(dd.get_text(separator=' ', strip=True))

        # 3. Советы из step-tip-interactive
        tips = self.soup.find_all(class_='step-tip-interactive')
        for tip in tips:
            text = tip.get_text(separator=' ', strip=True)
            text = re.sub(r'^Tipp:\s*', '', text)
            _add_note(text)

        return ' '.join(notes_parts) if notes_parts else None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта из JSON-LD keywords"""
        json_ld = self._get_json_ld_data()
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if isinstance(keywords, str) and keywords.strip():
                # Нормализуем разделители — ключевые слова могут быть через запятую
                tags = [t.strip() for t in keywords.split(',') if t.strip()]
                return ', '.join(tags) if tags else None
            elif isinstance(keywords, list):
                tags = [t.strip() for t in keywords if t.strip()]
                return ', '.join(tags) if tags else None

        logger.warning("tags не найдено")
        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений рецепта"""
        urls = []

        # Из JSON-LD image
        json_ld = self._get_json_ld_data()
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                url = img.get('url') or img.get('contentUrl')
                if url:
                    urls.append(url)
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        url = item.get('url') or item.get('contentUrl')
                        if url:
                            urls.append(url)

        # Дополнительно из og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # Убираем дубликаты, сохраняя порядок
        seen: set = set()
        unique_urls = []
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

    preprocessed_dir = os.path.join("preprocessed", "izekesillatok_hu")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(IzekesIllatokHuExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python izekesillatok_hu.py")


if __name__ == "__main__":
    main()
