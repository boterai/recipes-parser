"""
Экстрактор данных рецептов для сайта receptik.cz
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ReceptikCzExtractor(BaseRecipeExtractor):
    """Экстрактор для receptik.cz"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # В receptik.cz используется @graph структура
                if isinstance(data, dict) and '@graph' in data:
                    # Ищем Article в @graph
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Article':
                            return item
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из meta og:title (обычно самый чистый вариант)
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - Receptik.cz" и " – recept..."
            title = re.sub(r'\s*-\s*Receptik\.cz\s*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'\s*–\s*recept.*$', '', title, flags=re.IGNORECASE)
            title = re.sub(r'^recept\s+na\s+', '', title, flags=re.IGNORECASE)
            clean_name = self.clean_text(title)
            if len(clean_name) > 3 and len(clean_name) < 100:
                return clean_name
        
        # Если не нашли в og:title, пробуем из JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'headline' in json_ld:
            headline = json_ld['headline']
            # Очищаем от "Recept na" и суффиксов
            clean_name = re.sub(r'^recept\s+na\s+', '', headline, flags=re.IGNORECASE)
            clean_name = re.sub(r'\s*–\s*recept.*$', '', clean_name, flags=re.IGNORECASE)
            clean_name = self.clean_text(clean_name)
            if len(clean_name) > 3 and len(clean_name) < 100:
                return clean_name
        
        # В последнюю очередь пробуем из h2 с классом wp-block-heading
        h2_headings = self.soup.find_all('h2', class_='wp-block-heading')
        for h2 in h2_headings:
            text = h2.get_text(strip=True)
            # Ищем заголовок с "recept" в названии
            if text and 'recept' in text.lower():
                # Удаляем слова "recept" и "na", а также "jednoduchý" (простой)
                clean_name = re.sub(r'\s*–\s*recept\s*$', '', text, flags=re.IGNORECASE)
                clean_name = re.sub(r'^(jednoduchý|snadný)\s+recept\s+na\s+', '', clean_name, flags=re.IGNORECASE)
                clean_name = re.sub(r'^recept\s+na\s+', '', clean_name, flags=re.IGNORECASE)
                clean_name = self.clean_text(clean_name)
                # Если после очистки остался текст разумной длины
                if len(clean_name) > 3 and len(clean_name) < 100:
                    return clean_name
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Получаем название блюда для поиска
        dish_name = self.extract_dish_name()
        
        # Сначала проверяем параграфы - ищем "Recept na [название] – ..."
        # Это специфичный паттерн для receptik.cz
        paragraphs = self.soup.find_all('p')
        for p in paragraphs[:15]:  # Проверяем первые 15 параграфов
            text = p.get_text(strip=True)
            if not text or len(text) < 40:
                continue
            
            # Проверяем, начинается ли с "Recept na" и содержит ли тире
            if text.lower().startswith('recept na') and '–' in text:
                # Проверяем, что это про наше блюдо
                if dish_name:
                    # Берем первые 5 символов каждого слова (основа слова) для сравнения
                    # чтобы обойти склонения в чешском языке
                    dish_words = dish_name.lower().split()
                    text_lower = text.lower()
                    # Ищем хотя бы одно слово длиной > 4 символов, чья основа есть в тексте
                    for word in dish_words:
                        if len(word) > 4:
                            # Берем первые 5-6 символов как основу
                            stem = word[:min(6, len(word))]
                            if stem in text_lower:
                                return self.clean_text(text)
                else:
                    return self.clean_text(text)
        
        # Затем ищем в meta og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc_text = og_desc['content']
            
            # Разбиваем на предложения
            sentences = []
            for s in desc_text.split('.'):
                s = s.strip()
                if s:
                    sentences.append(s)
            
            # Ищем предложение, которое содержит описание блюда
            if dish_name and sentences:
                # Получаем первое слово из названия (основное слово)
                dish_first_word = dish_name.lower().split()[0]
                
                # Ищем предложение, которое начинается с названия блюда и содержит "je"
                for sentence in sentences:
                    sentence_lower = sentence.lower()
                    # Проверяем, начинается ли предложение с названия блюда и содержит "je"
                    if sentence_lower.startswith(dish_first_word) and ' je ' in sentence_lower:
                        # Добавляем точку в конце если её нет
                        result = self.clean_text(sentence)
                        if not result.endswith('.'):
                            result += '.'
                        return result
            
            # Если не нашли точное совпадение, ищем предложение с "–" (тире), которое указывает на описание
            for sentence in sentences:
                if '–' in sentence:
                    # Берем часть после тире
                    parts = sentence.split('–', 1)
                    if len(parts) > 1 and len(parts[1].strip()) > 30:
                        result = self.clean_text(parts[1].strip())
                        if not result.endswith('.'):
                            result += '.'
                        return result
            
            # Если ничего не нашли, ищем любое предложение с "je" и достаточной длиной
            for sentence in sentences:
                if ' je ' in sentence.lower() and len(sentence) > 40:
                    result = self.clean_text(sentence)
                    if not result.endswith('.'):
                        result += '.'
                    return result
            
            # В крайнем случае возвращаем og:description полностью
            return self.clean_text(desc_text)
        
        # Альтернатива - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "500 g steaku ribeye" или "1/2 lžičky mořské soli"
            
        Returns:
            dict: {"name": "...", "amount": "...", "units": "..."}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Чешские единицы: g, kg, ml, l, lžíce (ложка), lžička (чайная ложка), šálek (чашка), stroužek (зубчик),
        # kus (штука), plátky/plátků (ломтики), konzerva (банка)
        # Важно: используем \b для границы слова чтобы не захватывать части слов
        
        # Сначала пробуем паттерн с составной единицей ("малая банка", "большой кусок" и т.д.)
        pattern_compound = r'^([\d\s/.,\-]+)\s+(malá|velká|velký|střední)\s+(konzerva|konzervy|balení|balíček|kus|kusy)\s+(.+)'
        match_compound = re.match(pattern_compound, text, re.IGNORECASE)
        
        if match_compound:
            amount_str, adjective, unit_base, name = match_compound.groups()
            # Объединяем прилагательное и единицу
            unit = f"{adjective} {unit_base}"
        else:
            # Обычный паттерн
            pattern = r'^([\d\s/.,\-]+)\s+(g|kg|ml|l|lžíce|lžic|lžička|lžičky|lžiček|šálek|šálku|šálků|stroužek|stroužky|stroužků|kus|kusy|kusů|plátky|plátek|plátků|konzerva|konzervy|konzerv|balení|balíček|balíčky|balíčků|špetka|špetky|špetek|teaspoon|tablespoon|tablespoons|teaspoons|tbsp|tsp|cup|cups|piece|pieces|slices|slice|clove|cloves)(?:\s|$)(.+)'
            
            match = re.match(pattern, text, re.IGNORECASE)
            
            if not match:
                # Если паттерн не совпал, пробуем без единицы измерения (только число + название)
                pattern_no_unit = r'^([\d\s/.,\-]+)\s+(.+)'
                match_no_unit = re.match(pattern_no_unit, text, re.IGNORECASE)
                
                if match_no_unit:
                    amount_str, name = match_no_unit.groups()
                    unit = None
                else:
                    # Если и это не совпало, возвращаем только название
                    return {
                        "name": text,
                        "amount": None,
                        "units": None
                    }
            else:
                amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка диапазонов типа "2-4"
            if '-' in amount_str and not amount_str.startswith('-'):
                # Берем среднее значение или просто сохраняем как строку
                amount = amount_str
            # Обработка дробей типа "1/2" или "1 1/2"
            elif '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                # Возвращаем как число (int или float)
                amount = int(total) if total == int(total) else total
            else:
                try:
                    val = float(amount_str.replace(',', '.'))
                    # Возвращаем как число (int или float)
                    amount = int(val) if val == int(val) else val
                except:
                    amount = amount_str
        
        # Обработка единицы измерения
        units = unit.strip() if unit else None
        
        # Специальная обработка для "natvrdo vařená" и подобных - это не единица измерения
        if units and 'vařená' in units.lower():
            # Это описание, а не единица - добавляем к названию
            name = f"{name}"
            units = units  # Сохраняем как units согласно reference
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "podle chuti" (по вкусу), "nebo více" (или больше), и т.д.
        # Также удаляем описания вроде "nakrájeného", "mleté" в конце
        name = re.sub(r',?\s*(podle chuti|nebo podle chuti|nebo více|volitelně|na ozdobu|na servírování|jemného|nakrájeného|nakrájené|nakrájená|na tenké plátky|na kostičky|mleté|strouhané|na kousky).*$', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате списка словарей"""
        ingredients = []
        
        # Ищем все ul.wp-block-list на странице
        ingredient_lists = self.soup.find_all('ul', class_='wp-block-list')
        
        # Обрабатываем списки, собирая ингредиенты пока они похожи на ингредиенты
        lists_processed = 0
        first_list_size = 0
        
        for ul in ingredient_lists:
            items = ul.find_all('li')
            
            if not items or len(items) == 0:
                continue
            
            # Проверяем первый элемент - если он похож на ингредиент, обрабатываем весь список
            first_item_text = items[0].get_text(strip=True)
            
            # Стоп-условия:
            # 1. Элемент слишком длинный (>150 символов)
            # 2. Содержит вопросительный знак (FAQ)
            # 3. Это одноэлементный список (обычно описание)
            # 4. Средняя длина элементов >100 символов
            
            if len(first_item_text) > 150 or '?' in first_item_text:
                break  # Дальше идут не ингредиенты
            
            if len(items) == 1:
                # Одноэлементные списки обычно не ингредиенты
                break
            
            # Проверяем средний размер элементов в списке
            avg_length = sum(len(li.get_text(strip=True)) for li in items) / len(items)
            
            # Ингредиенты обычно короткие (< 80 символов в среднем)
            if avg_length > 100:
                break  # Дальше идут описания
            
            # Обрабатываем список как ингредиенты
            list_ingredients = []
            for li in items:
                ingredient_text = li.get_text(separator=' ', strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                if ingredient_text:
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        list_ingredients.append(parsed)
            
            # Добавляем ингредиенты из этого списка
            ingredients.extend(list_ingredients)
            lists_processed += 1
            
            # Запоминаем размер первого списка
            if lists_processed == 1:
                first_list_size = len(list_ingredients)
            
            # Останавливаемся если:
            # - Первый список большой (>= 10 ингредиентов) - значит это полный рецепт
            # - Или обработали уже 2 списка
            # - Или набрали больше 22 ингредиентов
            if (lists_processed == 1 and first_list_size >= 10) or \
               lists_processed >= 2 or \
               len(ingredients) > 22:
                break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем ol.wp-block-list (нумерованный список шагов)
        instruction_lists = self.soup.find_all('ol', class_='wp-block-list')
        
        if instruction_lists:
            # Берем первый список как основной
            for li in instruction_lists[0].find_all('li'):
                step_text = li.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'articleSection' in json_ld:
            sections = json_ld['articleSection']
            if isinstance(sections, list):
                # Приоритет: "Hlavní jídla" (основные блюда) > другие категории
                if "Hlavní jídla" in sections:
                    return "Hlavní jídla"
                # Берем первую категорию если "Hlavní jídla" нет
                return sections[0] if sections else None
            return str(sections)
        
        # Альтернатива - из HTML ссылок категорий
        category_div = self.soup.find('div', class_='article-item__categories')
        if category_div:
            category_links = category_div.find_all('a')
            if category_links:
                return self.clean_text(category_links[0].get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На receptik.cz время часто нет в структурированном виде
        # Пытаемся найти в тексте статьи
        # Ищем паттерны типа "příprava: 15 minut" или "doba přípravy: 15 min"
        
        article_text = self.soup.get_text()
        
        # Паттерны для поиска времени подготовки
        patterns = [
            r'příprava[:\s]+(\d+\s*(?:minut|min|hodin|hod))',
            r'doba přípravy[:\s]+(\d+\s*(?:minut|min|hodin|hod))',
            r'preparation time[:\s]+(\d+\s*(?:minutes|mins|hours|hrs))',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, article_text, re.IGNORECASE)
            if match:
                time_text = match.group(1)
                # Нормализуем формат (преобразуем в minutes)
                return self.clean_text(time_text)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        article_text = self.soup.get_text()
        
        # Паттерны для поиска времени готовки
        patterns = [
            r'vaření[:\s]+(\d+\s*(?:minut|min|hodin|hod))',
            r'doba vaření[:\s]+(\d+\s*(?:minut|min|hodin|hod))',
            r'pečení[:\s]+(\d+\s*(?:minut|min|hodin|hod))',
            r'cooking time[:\s]+(\d+\s*(?:minutes|mins|hours|hrs))',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, article_text, re.IGNORECASE)
            if match:
                time_text = match.group(1)
                return self.clean_text(time_text)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        article_text = self.soup.get_text()
        
        # Паттерны для поиска общего времени
        patterns = [
            r'celková doba[:\s]+(\d+\s*(?:minut|min|hodin|hod))',
            r'celkem[:\s]+(\d+\s*(?:minut|min|hodin|hod))',
            r'total time[:\s]+(\d+\s*(?:minutes|mins|hours|hrs))',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, article_text, re.IGNORECASE)
            if match:
                time_text = match.group(1)
                return self.clean_text(time_text)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем параграфы после рецепта или с ключевыми словами
        # В receptik.cz заметки могут быть в начале или в конце статьи
        
        paragraphs = self.soup.find_all('p')
        
        # Ключевые слова для заметок
        note_keywords = [
            'tip', 'poznámka', 'rada', 'doporučení', 'není nic složitého',
            'můžete', 'je vhodné', 'je možné', 'snadno', 'rychle'
        ]
        
        for p in paragraphs:
            text = p.get_text(strip=True)
            if not text:
                continue
            
            # Проверяем, содержит ли параграф ключевые слова
            text_lower = text.lower()
            for keyword in note_keywords:
                if keyword in text_lower:
                    cleaned_text = self.clean_text(text)
                    # Возвращаем только если текст не слишком длинный
                    if len(cleaned_text) < 300:
                        return cleaned_text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # 1. Получаем категории из JSON-LD
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'articleSection' in json_ld:
            sections = json_ld['articleSection']
            if isinstance(sections, list):
                # Берем все категории кроме самой общей ("Hlavní jídla", "Maso")
                # и превращаем их в теги
                specific_sections = [s.lower() for s in sections if s not in ['Hlavní jídla', 'Maso', 'Pečivo']]
                tags_list.extend(specific_sections)
        
        # 2. Проверяем теги в HTML
        tags_div = self.soup.find('div', class_='article-item__tags')
        if tags_div:
            tag_links = tags_div.find_all('a')
            for tag_link in tag_links:
                tag_text = tag_link.get_text(strip=True).lower()
                # Пропускаем общие теги
                if tag_text not in ['recept', 'ingredience']:
                    tags_list.append(tag_text)
        
        # 3. Анализируем название блюда для извлечения ключевых слов
        dish_name = self.extract_dish_name()
        if dish_name:
            # Извлекаем тип блюда из названия (например, "pizza", "sendvič")
            name_lower = dish_name.lower()
            # Общие типы блюд в чешском
            dish_types = ['pizza', 'sendvič', 'polévka', 'salát', 'dezert', 'koláč', 'dort']
            for dtype in dish_types:
                if dtype in name_lower and dtype not in tags_list:
                    tags_list.append(dtype)
        
        # Удаляем дубликаты
        unique_tags = []
        seen = set()
        for tag in tags_list:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        # Возвращаем как строку через запятую с пробелом
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в meta og:image (обычно главное изображение)
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем изображения в статье с wp-post-image классом
        post_images = self.soup.find_all('img', class_=re.compile(r'wp-post-image'))
        for img in post_images:
            src = img.get('src') or img.get('data-src')
            if src and src not in urls:
                urls.append(src)
        
        # 3. Ищем изображения внутри figure элементов
        figures = self.soup.find_all('figure', class_='wp-block-image')
        for figure in figures:
            img = figure.find('img')
            if img:
                src = img.get('src') or img.get('data-src')
                if src and src not in urls:
                    # Пропускаем маленькие изображения (миниатюры)
                    if '150x150' not in src and '300x' not in src:
                        urls.append(src)
        
        # Ограничиваем до 3 изображений
        if urls:
            unique_urls = []
            seen = set()
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
                    if len(unique_urls) >= 3:
                        break
            
            return ','.join(unique_urls) if unique_urls else None
        
        return None
    
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
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "receptik_cz")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ReceptikCzExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python receptik_cz.py")


if __name__ == "__main__":
    main()
