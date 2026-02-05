"""
Экстрактор данных рецептов для сайта morsblog.dk
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MorsblogExtractor(BaseRecipeExtractor):
    """Экстрактор для morsblog.dk"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            title = self.clean_text(h1.get_text())
            # Извлекаем основное название блюда из заголовка
            # Убираем "Den Bedste", "Opskrift", "Guide til at lave" и т.д.
            # Ищем ключевые слова блюда
            
            # Убираем префиксы
            title = re.sub(r'^(Den Bedste|Guide til at lave laekre|Guide til at lave|En Sund og Laekker)\s+', '', title, flags=re.IGNORECASE)
            # Убираем суффиксы
            title = re.sub(r'\s+(Opskrift|Guide).*$', '', title, flags=re.IGNORECASE)
            # Убираем двоеточие и всё после
            if ':' in title:
                title = title.split(':')[0]
            
            return title.strip()
        
        # Альтернативно - из тега title
        title_tag = self.soup.find('title')
        if title_tag:
            return self.clean_text(title_tag.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем первый параграф после h1 в article
        article = self.soup.find('div', class_='article')
        if article:
            h1 = article.find('h1')
            if h1:
                # Берём следующий элемент после h1
                next_elem = h1.find_next_sibling('p')
                if next_elem:
                    text = self.clean_text(next_elem.get_text())
                    # Берём только первое предложение для краткости
                    if '.' in text:
                        first_sentence = text.split('.')[0] + '.'
                        return first_sentence
                    return text
        
        # Альтернативно - ищем мета-описание
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient_text(self, text: str) -> Optional[Dict[str, Optional[str]]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            text: Строка вида "200 g mel" или "2 store gulerødder, revet"
            
        Returns:
            dict: {"name": "mel", "amount": "200", "units": "g"}
        """
        if not text:
            return None
        
        text = self.clean_text(text).lower()
        
        # Убираем описания в скобках и после запятой
        text = re.sub(r'\([^)]*\)', '', text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "200 g mel", "2 store gulerødder", "1 tsk salt"
        # Поддерживаемые единицы (используем non-capturing group)
        units_pattern = r'(?:g|kg|dl|ml|l|tsk|spsk|stk|stykker?|fed|large|tern|revet|skåret|skrællet)'
        
        # Пробуем найти паттерн: число + единица + название
        pattern = r'^(\d+(?:[.,]\d+)?)\s+(' + units_pattern + r')\s+(.+)$'
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            groups = match.groups()
            amount = groups[0]
            unit = groups[1]
            name = groups[2]
            # Очищаем название от лишних описаний
            name = re.sub(r',.*$', '', name).strip()
            name = re.sub(r'\(.*\)$', '', name).strip()
            
            # Конвертируем amount в int если возможно
            try:
                amount_val = int(float(amount.replace(',', '.')))
            except:
                amount_val = amount.replace(',', '.')
            
            return {
                "name": name,
                "amount": amount_val,
                "units": unit
            }
        
        # Пробуем паттерн: число + название (без единицы, но проверим слово после числа)
        pattern2 = r'^(\d+(?:[.,]\d+)?)\s+(.+)$'
        match2 = re.match(pattern2, text, re.IGNORECASE)
        
        if match2:
            amount, rest = match2.groups()
            # Проверяем, начинается ли rest с единицы измерения
            rest_parts = rest.split(None, 1)
            unit = None
            name = rest
            
            if len(rest_parts) > 0:
                first_word = rest_parts[0]
                # Проверяем, является ли первое слово единицей или описанием
                if re.match(units_pattern, first_word, re.IGNORECASE):
                    unit = first_word
                    name = rest_parts[1] if len(rest_parts) > 1 else first_word
                # Специальная обработка для ингредиентов без явной единицы (как "æg", "salt", "peber")
                # Если название - это обычный ингредиент без единицы, подразумеваем "stk"
                elif first_word in ['æg', 'aeblinger', 'citroner', 'appelsiner', 'løg', 'hvidløg']:
                    unit = 'stk'
                    name = rest
                # Если это описательное слово (store, lille и т.д.), оставляем в названии
                elif first_word in ['store', 'lille', 'små', 'mellemstore', 'hele', 'frisk', 'friske']:
                    # Проверяем следующее слово
                    if len(rest_parts) > 1:
                        second_word = rest_parts[1] if len(rest_parts) > 1 else ''
                        # Если второе слово - это продукт без единицы
                        if second_word in ['gulerødder', 'æg', 'kartofler', 'løg']:
                            unit = 'stk' if second_word != 'gulerødder' else 'large'
                            name = rest
                        else:
                            name = rest
                    else:
                        name = rest
                else:
                    # Это часть названия, не единица
                    name = rest
            
            # Очищаем название
            name = re.sub(r',.*$', '', name).strip()
            name = re.sub(r'\(.*\)$', '', name).strip()
            
            if not name or len(name) < 2:
                return None
            
            # Конвертируем amount в int если возможно
            try:
                amount_val = int(float(amount.replace(',', '.')))
            except:
                amount_val = amount.replace(',', '.')
            
            return {
                "name": name,
                "amount": amount_val,
                "units": unit
            }
        
        # Если ничего не совпало, возвращаем только название
        # Убираем прилагательные типа "store", "revet" и т.д.
        name = re.sub(r'^(store|lille|revet|hakket|skåret|skrællet)\s+', '', text, flags=re.IGNORECASE)
        name = re.sub(r',.*$', '', name).strip()
        
        return {
            "name": name,
            "amount": None,
            "units": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients_list = []
        
        # Ищем список ингредиентов в статье
        article = self.soup.find('div', class_='article')
        if not article:
            return None
        
        # Ищем все ul списки в article
        ul_lists = article.find_all('ul')
        
        for ul in ul_lists:
            # Проверяем, что это список ингредиентов (не FAQ и т.д.)
            # Обычно список ингредиентов идёт перед заголовком "Fremgangsmåde" или "Instruktioner"
            parent_ol = ul.find_parent('ol')
            if parent_ol:
                # Это вложенный список в инструкциях
                items = ul.find_all('li', recursive=False)
                for item in items:
                    # Извлекаем текст, убирая вложенные теги
                    text = item.get_text(strip=True)
                    if text:
                        parsed = self.parse_ingredient_text(text)
                        if parsed and parsed.get('name'):
                            ingredients_list.append(parsed)
            else:
                # Это отдельный список ингредиентов
                items = ul.find_all('li', recursive=False)
                temp_ingredients = []
                for item in items:
                    text = item.get_text(strip=True)
                    if text:
                        parsed = self.parse_ingredient_text(text)
                        if parsed and parsed.get('name'):
                            temp_ingredients.append(parsed)
                
                # Добавляем, если нашли хотя бы 2 ингредиента
                if len(temp_ingredients) >= 2:
                    ingredients_list.extend(temp_ingredients)
        
        if ingredients_list:
            return json.dumps(ingredients_list, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions = []
        
        # Ищем ordered list с инструкциями
        article = self.soup.find('div', class_='article')
        if not article:
            return None
        
        # Ищем все ol списки
        ol_lists = article.find_all('ol')
        
        for ol in ol_lists:
            items = ol.find_all('li', recursive=False)
            temp_instructions = []
            
            for item in items:
                # Проверяем, нет ли вложенного ul (это секция ингредиентов)
                if item.find('ul'):
                    # Пропускаем, это секция с ингредиентами
                    continue
                
                # Извлекаем текст инструкции
                text = item.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                
                if text:
                    temp_instructions.append(text)
            
            # Добавляем инструкции, если нашли
            if temp_instructions:
                instructions.extend(temp_instructions)
        
        if instructions:
            return ' '.join(instructions)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Пробуем определить категорию по содержимому
        description = self.extract_description()
        title = self.extract_dish_name()
        
        if not description and not title:
            return None
        
        combined_text = f"{title or ''} {description or ''}".lower()
        
        # Словарь ключевых слов для категорий
        category_keywords = {
            'Dessert': ['dessert', 'tærte', 'kage', 'sødt'],
            'Snack': ['boller', 'snack', 'mellemmåltid'],
            'Main Course': ['hovedret', 'aftensmad', 'kartofler med fyld', 'bagekartofler'],
            'Breakfast': ['morgenmad', 'brød'],
            'Appetizer': ['forret', 'appetizer'],
            'Salad': ['salat'],
            'Soup': ['suppe'],
        }
        
        # Ищем совпадения
        for category, keywords in category_keywords.items():
            for keyword in keywords:
                if keyword in combined_text:
                    return category
        
        return None
    
    def extract_time_from_text(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени из текста инструкций
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Получаем весь текст статьи
        article = self.soup.find('div', class_='article')
        if not article:
            return None
        
        text = article.get_text()
        
        # Паттерны для поиска времени
        if time_type == 'prep':
            # Ищем упоминания времени подготовки - обычно первое упоминание времени
            # или в контексте "ca. 15 minutter" для подготовки
            all_times = re.findall(r'(\d+(?:-\d+)?)\s*minut', text, re.IGNORECASE)
            if all_times:
                # Берём первое упомянутое время (обычно это prep time)
                return f"{all_times[0]} minutes"
        elif time_type == 'cook':
            # Ищем время приготовления/запекания - берём упоминание с "bag" или большее время
            patterns = [
                r'yderligere\s+(\d+(?:-\d+)?)\s*minut',  # "yderligere 25-30 minutter"
                r'(\d+(?:-\d+)?)\s*minut',
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    time_value = match.group(1)
                    # Если это диапазон, берём максимальное значение
                    if '-' in time_value:
                        time_value = time_value.split('-')[1]
                    return f"{time_value} minutes"
        else:  # total
            # Для общего времени попробуем найти упоминание общего времени
            patterns = [
                r'total.*?(\d+(?:-\d+)?)\s*minut',
                r'i alt.*?(\d+(?:-\d+)?)\s*minut',
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    time_value = match.group(1)
                    return f"{time_value} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time_from_text('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time_from_text('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Специальная обработка для overnight
        article = self.soup.find('div', class_='article')
        if article and 'natten over' in article.get_text().lower():
            return 'overnight + 30 minutes'
        
        # Сначала пробуем найти явное упоминание
        total = self.extract_time_from_text('total')
        if total:
            return total
        
        # Если не нашли, пробуем вычислить из всех упоминаний времени
        if article:
            text = article.get_text()
            all_times = re.findall(r'(\d+(?:-\d+)?)\s*minut', text, re.IGNORECASE)
            if all_times:
                # Суммируем все упомянутые времена или берём максимальное
                # Для простоты берём сумму первых двух (обычно prep + cook)
                if len(all_times) >= 2:
                    try:
                        time1 = int(all_times[0].split('-')[-1])
                        time2 = int(all_times[1].split('-')[-1])
                        total_minutes = time1 + time2
                        return f"{total_minutes} minutes"
                    except:
                        pass
                # Если только одно время, используем его
                elif len(all_times) == 1:
                    return f"{all_times[0]} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секции с вариациями, советами
        article = self.soup.find('div', class_='article')
        if not article:
            return None
        
        # Ищем заголовки с "Variationer"
        note_headers = article.find_all('h2', string=re.compile(r'Variationer', re.IGNORECASE))
        
        notes_text = []
        
        for header in note_headers:
            # Берём следующий параграф
            next_p = header.find_next_sibling('p')
            if next_p:
                text = self.clean_text(next_p.get_text())
                # Берём только первое предложение для краткости
                if text and '.' in text:
                    first_sentence = text.split('.')[0] + '.'
                    notes_text.append(first_sentence)
                elif text:
                    notes_text.append(text)
        
        if notes_text:
            # Возвращаем первый найденный совет
            return notes_text[0]
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Извлекаем ключевые слова из заголовка
        title = self.extract_dish_name()
        if title:
            # Берём основные слова из названия блюда
            words = title.lower().split()
            # Фильтруем стоп-слова
            stopwords = {'den', 'bedste', 'en', 'med', 'til', 'og', 'opskrift', 'guide', 'lave', 'la'}
            for word in words:
                clean_word = re.sub(r'[^\wæøå]', '', word)
                if clean_word and clean_word not in stopwords and len(clean_word) > 2:
                    if clean_word not in tags:
                        tags.append(clean_word)
        
        # Добавляем категорию как тег
        category = self.extract_category()
        if category:
            cat_lower = category.lower()
            if cat_lower not in tags:
                tags.append(cat_lower)
        
        # Добавляем ключевое слово из описания
        description = self.extract_description()
        if description:
            desc_lower = description.lower()
            # Специфичные датские слова для тегов
            if 'efterår' in desc_lower and 'efterår' not in tags:
                tags.append('efterår')
        
        if tags:
            return ', '.join(tags[:5])  # Ограничиваем 5 тегами
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # Ищем изображения в статье
        article = self.soup.find('div', class_='article')
        if article:
            images = article.find_all('img')
            for img in images:
                src = img.get('src')
                if src and src.startswith('/'):
                    # Относительный URL, добавляем домен
                    src = f"https://morsblog.dk{src}"
                if src and src not in urls:
                    urls.append(src)
        
        if urls:
            return ','.join(urls)
        
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
            "instructions": self.extract_instructions(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Обработка директории с HTML файлами morsblog.dk"""
    import os
    
    # Путь к директории с примерами
    preprocessed_dir = os.path.join("preprocessed", "morsblog_dk")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(MorsblogExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python morsblog_dk.py")


if __name__ == "__main__":
    main()
