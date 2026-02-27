"""
Экстрактор данных рецептов для сайта mundosaudavelfit.com.br
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MundoSaudavelFitExtractor(BaseRecipeExtractor):
    """Экстрактор для mundosaudavelfit.com.br"""

    def _get_article_json_ld(self) -> Optional[dict]:
        """Извлечение данных JSON-LD типа article из страницы"""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type', '').lower() == 'article':
                    return data
            except (json.JSONDecodeError, KeyError):
                continue
        return None

    def _get_article_body_soup(self):
        """Парсинг HTML из поля articleBody в JSON-LD"""
        from bs4 import BeautifulSoup
        data = self._get_article_json_ld()
        if data and 'articleBody' in data:
            return BeautifulSoup(data['articleBody'], 'lxml')
        return None

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Берём из JSON-LD article headline или H1 страницы
        data = self._get_article_json_ld()
        title = None
        if data:
            title = data.get('headline') or data.get('name')
        if not title:
            h1 = self.soup.find('h1')
            if h1:
                title = h1.get_text(strip=True)
        if not title:
            og = self.soup.find('meta', property='og:title')
            if og and og.get('content'):
                title = og['content']

        if not title:
            return None

        title = self.clean_text(title)

        # Убираем суффикс с именем сайта (" - Mundo Saudável Fit" и т.п.)
        title = re.sub(r'\s*[-–|]\s*Mundo Saud[aá]vel Fit\s*$', '', title, flags=re.I)

        # Убираем ведущие цифры и любые не-буквенные символы (emoji, символы и т.п.)
        title = re.sub(r'^\d+\s*', '', title)
        title = re.sub(r'^[^\w\u00C0-\u024F]+', '', title, flags=re.UNICODE)

        # Убираем подзаголовок после двоеточия или длинного тире
        title = re.split(r':\s+|\s+[–—]\s+', title)[0]

        # Убираем префикс "Receita (Tradicional|...) de "
        title = re.sub(r'^Receita\s+(?:\w+\s+)*de\s+', '', title, flags=re.I)

        return title.strip() or None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Предпочитаем og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = self.clean_text(og_desc['content'])
            # Если og:description отличается от заголовка, используем его
            og_title = self.soup.find('meta', property='og:title')
            title_text = og_title.get('content', '') if og_title else ''
            if desc and desc.lower() != title_text.lower():
                return desc

        # Запасной вариант — первый абзац articleBody
        body_soup = self._get_article_body_soup()
        if body_soup:
            first_p = body_soup.find('p')
            if first_p:
                return self.clean_text(first_p.get_text())

        return None

    def _parse_pt_ingredient(self, text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента на португальском в структурированный формат.

        Примеры:
          "500g de carne de frango ou cordeiro" → {"name": "carne de frango ou cordeiro", "amount": "500", "unit": "g"}
          "2 colheres de sopa de pasta de tomate" → {"name": "pasta de tomate", "amount": "2", "unit": "colheres de sopa"}
          "Sal a gosto" → {"name": "sal", "amount": None, "unit": "a gosto"}
        """
        if not text:
            return None

        text = self.clean_text(text)
        original = text

        # Специальная обработка: "X a gosto" (по вкусу)
        a_gosto_m = re.match(r'^(.+?)\s+a\s+gosto\s*$', text, re.I)
        if a_gosto_m:
            return {"name": a_gosto_m.group(1).strip().lower(), "amount": None, "unit": "a gosto"}

        # Заменяем Unicode-дроби
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
        }
        for frac, rep in fraction_map.items():
            text = text.replace(frac, rep)

        # Единицы измерения (португальский)
        PT_UNITS = (
            r'colheres?\s+de\s+(?:sopa|chá|sobremesa|café)',
            r'colher(?:es)?\s+de\s+(?:sopa|chá|sobremesa|café)',
            r'xícaras?(?:\s+de)?',
            r'xicaras?(?:\s+de)?',
            r'copos?(?:\s+de)?',
            r'pitadas?',
            r'dentes?',
            r'pedaços?',
            r'unidades?',
            r'fatias?',
            r'folhas?',
            r'ramos?',
            r'kg',
            r'g',
            r'ml',
            r'l(?!\w)',
            r'mg',
        )
        units_pattern = '|'.join(PT_UNITS)

        # Паттерн: [количество] [единица] [de] [название]
        pattern = (
            r'^'
            r'((?:\d+\s*(?:[/,\.]\s*\d+)?\s*(?:a\s+\d+)?)\s*)?'   # количество (опционально)
            r'(' + units_pattern + r')?\s*'                          # единица (опционально)
            r'(?:de\s+)?'                                            # предлог "de" (опционально)
            r'(.+)$'                                                  # название
        )

        m = re.match(pattern, text, re.IGNORECASE)

        amount: Optional[str] = None
        unit: Optional[str] = None
        name: str = original

        if m:
            raw_amount, raw_unit, raw_name = m.groups()

            # Обработка количества
            if raw_amount:
                raw_amount = raw_amount.strip()
                # Формат "X a Y" — берём максимальное значение
                range_m = re.match(r'(\d+(?:[.,]\d+)?)\s+a\s+(\d+(?:[.,]\d+)?)', raw_amount)
                if range_m:
                    amount = range_m.group(2).replace(',', '.')
                elif '/' in raw_amount:
                    parts = raw_amount.split()
                    total = 0.0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            try:
                                total += float(part.replace(',', '.'))
                            except ValueError:
                                pass
                    amount = str(total)
                else:
                    amount = raw_amount.replace(',', '.')

            if raw_unit:
                unit = re.sub(r'\s+de$', '', raw_unit.strip(), flags=re.I)

            if raw_name:
                name = self.clean_text(raw_name)
        else:
            # Специальная обработка: "NNNg de..." или "NNNml de..." без пробела
            compact = re.match(r'^(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l)\s+de\s+(.+)$', text, re.I)
            if compact:
                amount = compact.group(1).replace(',', '.')
                unit = compact.group(2)
                name = self.clean_text(compact.group(3))
            else:
                name = self.clean_text(text)

        # Убираем примечания в скобках и хвостовые запятые
        name = re.sub(r'\([^)]*\)', '', name).strip()
        name = re.sub(r'[;,]+$', '', name).strip()

        if not name:
            return None

        return {"name": name, "amount": amount, "unit": unit}

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из articleBody"""
        body_soup = self._get_article_body_soup()
        if not body_soup:
            return None

        ingredients = []

        # Ищем все UL и берём тот, который больше всего похож на список ингредиентов
        best_ul = None
        best_score = 0

        for ul in body_soup.find_all('ul'):
            items = ul.find_all('li')
            if len(items) < 2:
                continue
            # Считаем, сколько элементов начинаются с цифры или содержат кулинарные единицы
            score = sum(
                1 for li in items
                if re.search(r'^\d|colher|xícara|copo|pitada|g |kg |ml |l |gramas', li.get_text(), re.I)
            )
            if score > best_score:
                best_score = score
                best_ul = ul

        if best_ul:
            for li in best_ul.find_all('li'):
                text = li.get_text(separator=' ', strip=True)
                parsed = self._parse_pt_ingredient(text)
                if parsed:
                    ingredients.append(parsed)

        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления из OL в articleBody"""
        body_soup = self._get_article_body_soup()
        if not body_soup:
            return None

        steps = []

        ol = body_soup.find('ol')
        if ol:
            for li in ol.find_all('li'):
                text = li.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                if text:
                    steps.append(text)

        return ' '.join(steps) if steps else None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории из meta article:section"""
        sections = [
            m.get('content', '')
            for m in self.soup.find_all('meta', property='article:section')
            if m.get('content')
        ]
        if not sections:
            return None

        # Предпочитаем раздел, отличный от общего "RECEITAS"
        non_generic = [s for s in sections if s.upper() != 'RECEITAS']
        category = non_generic[0] if non_generic else sections[0]
        return self.clean_text(category)

    def _extract_cook_time_from_text(self) -> Optional[str]:
        """Извлечение времени готовки из текста инструкций"""
        body_soup = self._get_article_body_soup()
        if not body_soup:
            return None

        text = body_soup.get_text()

        # "X a Y minutos" → берём Y (максимальное)
        range_m = re.search(r'(\d+)\s+a\s+(\d+)\s*(?:minutos?|horas?)', text, re.I)
        if range_m:
            val = int(range_m.group(2))
            unit_m = re.search(r'(\d+)\s+a\s+\d+\s*(minutos?|horas?)', text, re.I)
            unit_word = unit_m.group(2).lower() if unit_m else 'minutos'
            if 'hora' in unit_word:
                return f"{val * 60} minutes"
            return f"{val} minutes"

        # "X minutos"
        simple_m = re.search(r'(\d+)\s*(minutos?|horas?)', text, re.I)
        if simple_m:
            val = int(simple_m.group(1))
            unit_word = simple_m.group(2).lower()
            if 'hora' in unit_word:
                return f"{val * 60} minutes"
            return f"{val} minutes"

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Время подготовки (не указано на сайте)"""
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        return self._extract_cook_time_from_text()

    def extract_total_time(self) -> Optional[str]:
        """Общее время (не указано на сайте)"""
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/советов из секции Dicas/Variações в articleBody"""
        body_soup = self._get_article_body_soup()
        if not body_soup:
            return None

        # Ключевые слова для поиска секции с советами
        keywords = re.compile(
            r'dica|variação|variações|notas?|tips?|observ|sugestão|extra', re.I
        )

        notes_parts = []

        # Ищем H2/H3 с ключевыми словами и собираем следующие элементы
        for heading in body_soup.find_all(['h2', 'h3']):
            if keywords.search(heading.get_text()):
                sib = heading.find_next_sibling()
                while sib and sib.name not in ['h2', 'h3']:
                    if sib.name == 'ul':
                        for li in sib.find_all('li'):
                            t = self.clean_text(li.get_text())
                            if t:
                                notes_parts.append(t)
                    elif sib.name == 'p':
                        t = self.clean_text(sib.get_text())
                        if t:
                            notes_parts.append(t)
                    sib = sib.find_next_sibling()
                if notes_parts:
                    break

        return ' '.join(notes_parts) if notes_parts else None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из recipe-tags-container (тело) или article:tag (meta)"""
        # 1. Попытка извлечь из recipe-tags-container в теле статьи
        body_soup = self._get_article_body_soup()
        if body_soup:
            container = body_soup.find(class_='recipe-tags-container')
            if container:
                tags = [
                    self.clean_text(span.get_text())
                    for span in container.find_all('span', class_='blog-tag')
                    if span.get_text(strip=True)
                ]
                if tags:
                    return ', '.join(tags)

        # 2. Запасной вариант — meta article:tag
        tag_metas = self.soup.find_all('meta', property='article:tag')
        tags = []
        site_name_pattern = re.compile(r'mundo\s+saud[aá]vel\s+fit', re.I)
        for m in tag_metas:
            content = m.get('content', '').strip()
            if content and not site_name_pattern.search(content):
                tags.append(content)

        return ', '.join(tags) if tags else None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений из og:image и JSON-LD"""
        urls = []

        # og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # JSON-LD article image
        data = self._get_article_json_ld()
        if data:
            img = data.get('image')
            if isinstance(img, dict):
                url = img.get('url') or img.get('contentUrl')
                if url and url not in urls:
                    urls.append(url)
            elif isinstance(img, str) and img not in urls:
                urls.append(img)

        # Убираем дубликаты
        seen: set = set()
        unique: list = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта

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

    preprocessed_dir = os.path.join("preprocessed", "mundosaudavelfit_com_br")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(MundoSaudavelFitExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python mundosaudavelfit_com_br.py")


if __name__ == "__main__":
    main()
