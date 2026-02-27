"""
Экстрактор данных рецептов для сайта demotivateur.fr
"""

import sys
import logging
import json
import re
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory

logger = logging.getLogger(__name__)


class DemotivateurFrExtractor(BaseRecipeExtractor):
    """Экстрактор для demotivateur.fr"""

    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение данных Recipe из JSON-LD"""
        for script in self.soup.find_all('script', type='application/ld+json'):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
            except (json.JSONDecodeError, KeyError):
                continue
        return None

    def _get_body(self):
        """Получение основного блока контента страницы"""
        return self.soup.find('div', class_='body-food')

    def _get_body_lines(self) -> list:
        """
        Возвращает список строк из основного контента.
        Заменяет <br> на переносы строк и объединяет разбитые строки ингредиентов.
        """
        body = self._get_body()
        if not body:
            return []

        # Работаем с копией, чтобы не менять оригинальный soup
        from bs4 import BeautifulSoup as _BS
        body_copy = _BS(str(body), 'lxml').find('div', class_='body-food')
        if not body_copy:
            return []

        # Заменяем <br> на маркер переноса
        for br in body_copy.find_all('br'):
            br.replace_with('\n')

        text = body_copy.get_text(separator='\n')
        raw_lines = [line.strip() for line in text.split('\n')]

        # Нормализуем non-breaking space
        raw_lines = [line.replace('\xa0', ' ').strip() for line in raw_lines]

        # Объединяем «разорванные» строки ингредиентов
        # Случай 1: строка — только «-» (элемент разбит по inline-тегу)
        # Случай 2: строка вида «- 1» без названия (число + inline-ссылка)
        result = []
        i = 0
        while i < len(raw_lines):
            line = raw_lines[i]
            if not line:
                i += 1
                continue

            is_split = (
                line == '-'
                or re.match(r'^-\s*[\d/,\.]+\s*$', line)
            )

            if is_split:
                combined = line
                i += 1
                while i < len(raw_lines):
                    nxt = raw_lines[i]
                    if not nxt:
                        i += 1
                        continue
                    # Стоп, если это новый ингредиент или шаг рецепта
                    if nxt.startswith('-') or re.match(r'^\d+[.\)]', nxt):
                        break
                    # Пропускаем отдельную пунктуацию
                    if nxt in ('.', ',', ';', ':'):
                        i += 1
                        continue
                    combined = combined.rstrip() + ' ' + nxt
                    i += 1
                    break
                result.append(combined.strip())
            else:
                result.append(line)
                i += 1

        return result

    # ------------------------------------------------------------------
    # Вспомогательные методы парсинга ингредиентов
    # ------------------------------------------------------------------

    _UNITS_PATTERN = (
        r'cuill[eè]res?\s+[àa]\s+soupe'
        r'|cuill[eè]re?\s+[àa]\s+soupe'
        r'|cuill[eè]res?\s+[àa]\s+caf[eé]'
        r'|cuill[eè]re?\s+[àa]\s+caf[eé]'
        r'|C\s+A\s+S'
        r'|C\s+A\s+C'
        r'|sachets?'
        r'|bo[iî]tes?'
        r'|bottes?'
        r'|verres?'
        r'|litres?'
        r'|kg'
        r'|cl'
        r'|ml'
        r'|g'
        r'|L'
    )

    def _parse_amount(self, amount_str: str):
        """Конвертирует строку количества в число (int или float)"""
        amount_str = amount_str.strip()
        if '/' in amount_str:
            parts = amount_str.split('/')
            try:
                val = float(parts[0]) / float(parts[1])
                return int(val) if val == int(val) else round(val, 4)
            except (ValueError, ZeroDivisionError):
                return amount_str
        try:
            val = float(amount_str.replace(',', '.'))
            return int(val) if val == int(val) else val
        except ValueError:
            return amount_str

    def _parse_single_ingredient(self, text: str) -> Optional[dict]:
        """
        Парсинг одной строки ингредиента.

        Формат: «[amount] [units] [de/d'/des/du] name»
        или «name» (без количества).
        """
        text = text.strip().rstrip('.,;')
        if not text:
            return None

        # Убираем префиксы du/de la/des/de l'
        du_re = re.compile(
            r'^(?:[Dd]u\s+|[Dd]e\s+la\s+|[Dd]es\s+|[Dd][\'e]\s+l[\'e]\s*|[Dd][\'e]\s+)',
            re.IGNORECASE
        )

        amount = None
        units = None
        name = text

        # Пробуем «number unit [de/d'...] name»
        full_re = re.compile(
            rf'^([\d]+(?:[,./]\d+)?(?:\s*/\s*[\d]+)?)\s+'
            rf'({self._UNITS_PATTERN})\s+'
            rf'(?:de\s+|d[\']\s*|des\s+|du\s+)?(.+)$',
            re.IGNORECASE
        )
        m = full_re.match(text)
        if m:
            amount = self._parse_amount(m.group(1))
            units = re.sub(r'\s+', ' ', m.group(2)).strip()
            name = m.group(3).strip()
        else:
            # Пробуем «number [de/d'...] name» (без единицы)
            num_re = re.compile(
                r'^([\d]+(?:[,./]\d+)?(?:\s*/\s*[\d]+)?)\s+'
                r'(?:de\s+|d[\']\s*|des\s+|du\s+)?(.+)$',
                re.IGNORECASE
            )
            m2 = num_re.match(text)
            if m2:
                amount = self._parse_amount(m2.group(1))
                name = m2.group(2).strip()
            else:
                # Убираем «Du/De la/...» в начале
                name = du_re.sub('', text).strip()

        # Убираем скобки с примечаниями и лишние символы
        name = re.sub(r'\([^)]*\)', '', name).strip()
        # Убираем суффикс "pour ..." (указание на способ применения)
        name = re.sub(r'\s+pour\s+.+$', '', name, flags=re.IGNORECASE).strip()
        name = re.sub(r'\s+', ' ', name).strip().rstrip('.,;')

        if not name:
            return None

        return {"name": name, "amount": amount, "units": units}

    def _parse_ingredient_line(self, line: str) -> list:
        """
        Парсинг строки ингредиента в список словарей.
        Возвращает список, так как одна строка может содержать несколько
        ингредиентов (например, «Sel, poivre» или «Du sel et du poivre»).
        """
        # Убираем ведущий дефис
        line = line.lstrip('-').strip().rstrip('.,;').strip()
        if not line:
            return []

        # Случай «X et Y» для ингредиентов без количества:
        # «Du sel et du poivre pour l'assaisonnement»
        du_prefix = re.compile(
            r'^(?:[Dd]u\s+|[Dd]e\s+la\s+|[Dd]es\s+|[Dd][\'e]\s+l[\'e]\s*|[Dd][\'e]\s+)',
        )
        if du_prefix.match(line) and ' et ' in line.lower():
            parts = re.split(r'\s+et\s+', line, flags=re.IGNORECASE)
            result = []
            for part in parts:
                part = part.strip().rstrip('.,;').strip()
                parsed = self._parse_single_ingredient(part)
                if parsed:
                    result.append(parsed)
            return result

        # Случай «Sel, poivre» — запятая разделяет ингредиенты без количества
        if ',' in line and not re.match(r'^[\d/]', line):
            parts = [p.strip().rstrip('.,;').strip() for p in line.split(',')]
            # Проверяем, что все части — это короткие названия без чисел
            if all(parts) and all(
                not re.match(r'^[\d/]', p) and len(p) <= 40 for p in parts
            ):
                result = []
                for part in parts:
                    parsed = self._parse_single_ingredient(part)
                    if parsed:
                        result.append(parsed)
                if result:
                    return result

        parsed = self._parse_single_ingredient(line)
        return [parsed] if parsed else []

    # ------------------------------------------------------------------
    # Публичные методы извлечения полей
    # ------------------------------------------------------------------

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Пробуем <title> — убираем префикс «Recette »
        title_tag = self.soup.find('title')
        if title_tag:
            title = self.clean_text(title_tag.get_text())
            title = re.sub(r'^Recette\s+', '', title, flags=re.IGNORECASE).strip()
            if title:
                return title

        # Из JSON-LD
        json_ld = self._get_json_ld_recipe()
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])

        # Из h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())

        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])

        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])

        return None

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из тела страницы"""
        lines = self._get_body_lines()
        if not lines:
            return None

        all_ingredients = []
        in_ingredients = False

        def _is_ingredients_header(text: str) -> bool:
            return (
                bool(re.search(r'ingr[eé]dient', text, re.IGNORECASE))
                and not text.startswith('-')
                and len(text) < 200
            )

        def _is_instructions_header(text: str) -> bool:
            return bool(re.search(
                r'pr[eé]paration|[eé]tapes?\s+d[eé]taill',
                text, re.IGNORECASE
            )) and not text.startswith('-') and len(text) < 300

        for line in lines:
            if _is_ingredients_header(line):
                in_ingredients = True
                continue

            if _is_instructions_header(line):
                # Переходим в режим инструкций — но сначала заканчиваем сбор
                in_ingredients = False
                continue

            if in_ingredients:
                if line.startswith('-'):
                    parsed = self._parse_ingredient_line(line)
                    all_ingredients.extend(parsed)
                elif re.match(r'^\d+[.\)]', line):
                    # Начались шаги — выходим из режима ингредиентов
                    in_ingredients = False

        if not all_ingredients:
            logger.warning("Ингредиенты не найдены: %s", self.html_path)
            return None

        return json.dumps(all_ingredients, ensure_ascii=False)

    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        lines = self._get_body_lines()
        if not lines:
            return None

        steps = []
        in_instructions = False

        def _is_step_line(text: str) -> bool:
            return bool(re.match(r'^\d+[.\)]', text))

        def _is_instructions_header(text: str) -> bool:
            # Не считаем шаги рецепта заголовком секции
            if _is_step_line(text):
                return False
            return bool(re.search(
                r'pr[eé]paration|[eé]tapes?\s+d[eé]taill',
                text, re.IGNORECASE
            )) and not text.startswith('-') and len(text) < 300

        def _is_section_title(text: str) -> bool:
            """Заголовок раздела (например, 'RECETTE CHOU-FLEUR FRIT')"""
            return (
                len(text) < 100
                and not _is_step_line(text)
                and not text.startswith('-')
                and (text.isupper() or bool(re.match(r'^RECETTE\s+', text, re.IGNORECASE)))
            )

        # Некоторые страницы содержат блок с видео или рекламой между шагами
        noise_patterns = re.compile(
            r'^(?:La suite après cette vidéo|×|Publicité|▶)',
            re.IGNORECASE
        )

        for line in lines:
            if _is_instructions_header(line):
                in_instructions = True
                continue

            # Новый заголовок ингредиентов означает конец текущей инструкции
            # (Проверяем, что строка не является шагом рецепта)
            if (
                re.search(r'ingr[eé]dient', line, re.IGNORECASE)
                and not line.startswith('-')
                and not _is_step_line(line)
            ):
                in_instructions = False
                continue

            if in_instructions:
                if noise_patterns.match(line):
                    continue
                if _is_step_line(line):
                    steps.append(line)
                elif _is_section_title(line):
                    # Заголовок следующего рецепта — не добавляем в шаги
                    continue
                elif steps and line in ('.', '!', '?'):
                    # Одиночный знак препинания — завершаем предыдущий шаг
                    steps[-1] = steps[-1].rstrip() + line
                elif steps and not line.startswith('-') and len(line) > 5:
                    # Продолжение текущего шага только если шаг явно не завершён
                    # (не оканчивается точкой, восклицательным или вопросительным знаком)
                    if not _is_step_line(line) and not re.search(r'[.!?]\s*$', steps[-1]):
                        steps[-1] = steps[-1] + ' ' + line

        if not steps:
            logger.warning("Шаги приготовления не найдены: %s", self.html_path)
            return None

        return ' '.join(steps)

    def extract_category(self) -> Optional[str]:
        """Извлечение категории (из JSON-LD или хлебных крошек)"""
        json_ld = self._get_json_ld_recipe()
        if json_ld:
            if 'recipeCategory' in json_ld:
                cat = json_ld['recipeCategory']
                return ', '.join(cat) if isinstance(cat, list) else str(cat)
            if 'recipeCuisine' in json_ld:
                cuisine = json_ld['recipeCuisine']
                return ', '.join(cuisine) if isinstance(cuisine, list) else str(cuisine)

        # Из хлебных крошек — берём последний значимый элемент
        breadcrumbs = self.soup.find('ol', class_='breadcrumb')
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            categories = [
                self.clean_text(a.get_text())
                for a in links
                if self.clean_text(a.get_text()).lower() not in ('accueil', 'home', 'food')
            ]
            if categories:
                return categories[-1]

        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки (из JSON-LD)"""
        json_ld = self._get_json_ld_recipe()
        if json_ld and 'prepTime' in json_ld:
            return self._parse_iso_duration(json_ld['prepTime'])
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления (из JSON-LD)"""
        json_ld = self._get_json_ld_recipe()
        if json_ld and 'cookTime' in json_ld:
            return self._parse_iso_duration(json_ld['cookTime'])
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени (из JSON-LD)"""
        json_ld = self._get_json_ld_recipe()
        if json_ld and 'totalTime' in json_ld:
            return self._parse_iso_duration(json_ld['totalTime'])
        return None

    @staticmethod
    def _parse_iso_duration(duration: str) -> Optional[str]:
        """Конвертирует ISO 8601 duration в читаемый формат"""
        if not duration or not duration.startswith('PT'):
            return None
        duration = duration[2:]
        hours = 0
        minutes = 0
        h_match = re.search(r'(\d+)H', duration)
        if h_match:
            hours = int(h_match.group(1))
        m_match = re.search(r'(\d+)M', duration)
        if m_match:
            minutes = int(m_match.group(1))
        parts = []
        if hours:
            parts.append(f"{hours} hr{'s' if hours > 1 else ''}")
        if minutes:
            parts.append(f"{minutes} min{'s' if minutes > 1 else ''}")
        return ' '.join(parts) if parts else None

    def extract_notes(self) -> Optional[str]:
        """
        Извлечение заметок к рецепту.
        Ищем короткий абзац после блока шагов (советы / призыв к действию).
        """
        lines = self._get_body_lines()

        # Находим позицию последнего шага в списке строк
        last_step_idx = -1
        for idx, line in enumerate(lines):
            if re.match(r'^\d+[.\)]', line):
                last_step_idx = idx

        if last_step_idx < 0:
            return None

        # После последнего шага ищем короткий абзац-подсказку.
        # Строка должна быть похожа на законченное предложение:
        # заканчиваться '.', '!' или '?' и иметь достаточную длину.
        for line in lines[last_step_idx + 1:]:
            if not line:
                continue
            if line.startswith('-') or re.match(r'^\d+[.\)]', line):
                continue
            if re.search(r'ingr[eé]dient|pr[eé]paration', line, re.IGNORECASE):
                continue
            # Пропускаем заголовки разделов
            if line.isupper() or re.match(r'^RECETTE\s+', line, re.IGNORECASE):
                continue
            # Принимаем только строки, похожие на предложение (с знаком в конце)
            if re.search(r'[.!?]\s*$', line) and 10 < len(line) <= 300:
                return self.clean_text(line)

        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из мета-тегов"""
        # Parsely-tags
        parsely = self.soup.find('meta', attrs={'name': 'parsely-tags'})
        if parsely and parsely.get('content'):
            tags = [t.strip() for t in parsely['content'].split(',') if t.strip()]
            if tags:
                return ', '.join(tags)

        # Keywords
        keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if keywords and keywords.get('content'):
            tags = [t.strip() for t in keywords['content'].split(',') if t.strip()]
            if tags:
                return ', '.join(tags)

        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []

        # JSON-LD image
        json_ld = self._get_json_ld_recipe()
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                urls.append(img.get('url') or img.get('contentUrl', ''))
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        urls.append(item.get('url') or item.get('contentUrl', ''))

        # og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])

        # twitter:image
        tw_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if tw_image and tw_image.get('content'):
            urls.append(tw_image['content'])

        # Изображения внутри основного контента (src тегов <img>)
        body = self._get_body()
        if body:
            for img_tag in body.find_all('img', src=True):
                src = img_tag['src']
                if src and src.startswith('http') and not src.endswith('.gif'):
                    urls.append(src)

        # Дедупликация с сохранением порядка
        seen = set()
        unique = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return ','.join(unique) if unique else None

    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта.

        Returns:
            Словарь с данными рецепта.
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
    """Точка входа для обработки директории с HTML‑файлами"""
    import os

    preprocessed_dir = os.path.join("preprocessed", "demotivateur_fr")

    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(DemotivateurFrExtractor, preprocessed_dir)
        return

    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python demotivateur_fr.py")


if __name__ == "__main__":
    main()
