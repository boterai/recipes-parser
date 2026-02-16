"""
Экстрактор данных рецептов для сайта nonnaantoinette.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class NonnaAntoinetteExtractor(BaseRecipeExtractor):
    """Экстрактор для nonnaantoinette.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке H1
        h1 = self.soup.find('h1')
        if h1:
            title = h1.get_text(strip=True)
            # Конвертируем из UPPERCASE в Title Case
            return self.clean_text(title.title())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем параграф, который содержит описание рецепта
        # Обычно это первый параграф после заголовка
        paragraphs = self.soup.find_all('p')
        
        for para in paragraphs:
            text = para.get_text(strip=True)
            # Ищем параграф с достаточным объемом текста (описание обычно больше 20 символов)
            # и исключаем служебные тексты
            if text and len(text) > 20 and len(text) < 500:
                # Проверяем, что это не часть инструкций (нет слов типа "Preheat", "Mix", etc.)
                if not any(word in text for word in ['Preheat', 'Mix ', 'Bake ', 'Place ', 'Add ', 'Sift ']):
                    cleaned = self.clean_text(text)
                    if cleaned:
                        # Берем только первое предложение как описание
                        sentences = cleaned.split('.')
                        if sentences and sentences[0]:
                            return sentences[0].strip() + '.'
                        return cleaned
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "3 3/4 cups 00 flour (450 gr)"
            
        Returns:
            dict: {"name": "00 flour", "amount": 3.75, "units": "cups"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем "I " (letter I with space) в начале на "1 " (number 1)
        text = re.sub(r'^I\s+', '1 ', text)
        
        # Заменяем Unicode дроби на обычные
        fraction_map = {
            '½': ' 1/2', '¼': ' 1/4', '¾': ' 3/4',
            '⅓': ' 1/3', '⅔': ' 2/3', '⅛': ' 1/8',
            '⅜': ' 3/8', '⅝': ' 5/8', '⅞': ' 7/8',
            '⅕': ' 1/5', '⅖': ' 2/5', '⅗': ' 3/5', '⅘': ' 4/5'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "3 3/4 cups 00 flour", "1 1/2 sticks butter", "1 tsp vanilla extract", "Pinch of salt"
        pattern = r'^([\d\s/.,]+)?\s*(cups?|cup|tablespoons?|teaspoons?|tbsps?|tbsp|tsps?|tsp|pounds?|ounces?|lbs?|lb|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|pinch|dash(?:es)?|packages?|pkg|cans?|jars?|boxes?|box|bottles?|sticks?|stick|whole|halves?|quarters?|pieces?|cloves?|shots?|shot)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2" или "3 3/4"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0.0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        try:
                            total += float(part)
                        except ValueError:
                            pass
                amount = total if total > 0 else None
            else:
                try:
                    amount = float(amount_str.replace(',', '.'))
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем префиксы "of" (например, "Pinch of salt" -> "salt")
        name = re.sub(r'^\s*of\s+', '', name, flags=re.IGNORECASE)
        # Удаляем скобки с содержимым (например, "(Double Zero flour - 450 gr)" or "(or rum)")
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional", "softened", "room temperature"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|softened|room temperature|more if needed|see tips)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем заголовок "Ingredients:"
        ingr_header = self.soup.find('span', string=lambda t: t and t.strip() == 'Ingredients:')
        
        if not ingr_header:
            # Альтернативный поиск через h5
            ingr_header = self.soup.find('h5', string=lambda t: t and 'Ingredient' in str(t))
        
        if not ingr_header:
            return None
        
        # Извлекаем все span элементы на странице
        all_spans = self.soup.find_all('span')
        
        # Используем флаг для отслеживания, где мы находимся
        in_ingredients_section = False
        seen_ingredients = set()
        
        for span in all_spans:
            text = span.get_text(strip=True)
            
            # Начинаем собирать ингредиенты после заголовка "Ingredients:"
            if text == 'Ingredients:':
                in_ingredients_section = True
                continue
            
            # Продолжаем в секции filling (это тоже ингредиенты)
            if 'For the filling' in text:
                # Пропускаем сам заголовок, но продолжаем собирать
                continue
            
            # Останавливаемся только на "Directions:" или "Preparation:"
            if text == 'Directions:' or text == 'Preparation:':
                break
            
            # Собираем ингредиенты только в секции ингредиентов
            if in_ingredients_section:
                # Пропускаем пустые, заголовки и очень короткие строки
                if not text or len(text) < 3 or (text.endswith(':') and len(text) < 30):
                    continue
                
                # Пропускаем дубликаты
                if text in seen_ingredients:
                    continue
                
                # Проверяем, что это похоже на ингредиент
                # Ингредиенты могут:
                # 1. Начинаться с числа
                # 2. Начинаться с "Pinch"
                # 3. Быть просто названием продукта (Nutella, Chocolate, etc.)
                is_ingredient = (
                    any(c.isdigit() for c in text) or 
                    text.lower().startswith('pinch') or 
                    text.lower().startswith('i ') or  # Letter I as number 1
                    any(unit in text.lower() for unit in ['cup', 'tbsp', 'tsp', 'gram', 'stick', 'oz', 'lb', 'whole', 'egg', 'shot', 'box', 'can', 'jar']) or
                    # Для ингредиентов без количества (в секции filling)
                    # Исключаем инструкции по ключевым словам с word boundaries
                    (in_ingredients_section and len(text) < 50 and not re.search(r'\b(mix|add|place|bake|preheat|stir|combine|pour)\b', text.lower()))
                )
                
                if is_ingredient:
                    # Специальная обработка для "egg plus yolk" - разбиваем на два ингредиента
                    if 'plus' in text.lower() and 'egg' in text.lower():
                        # Парсим "1 egg plus one yolk" как два отдельных ингредиента
                        parts = re.split(r'\s+plus\s+', text, flags=re.IGNORECASE)
                        for part in parts:
                            part = part.strip()
                            if part:
                                # Нормализуем "one" -> "1"
                                part = re.sub(r'\bone\b', '1', part, flags=re.IGNORECASE)
                                parsed = self.parse_ingredient(part)
                                if parsed and parsed.get('name'):
                                    ingredients.append(parsed)
                    else:
                        parsed = self.parse_ingredient(text)
                        if parsed and parsed.get('name'):
                            ingredients.append(parsed)
                    
                    seen_ingredients.add(text)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Ищем заголовок "Preparation:" или "Directions:" или "Instructions:"
        instruction_header = None
        stop_keywords = ['Preparation:', 'Directions:', 'Instructions:', 'Method:']
        for keyword in stop_keywords:
            header = self.soup.find('span', string=lambda t: t and keyword in str(t))
            if not header:
                header = self.soup.find('h5', string=lambda t: t and keyword in str(t))
            if header:
                instruction_header = header
                break
        
        if not instruction_header:
            return None
        
        # Извлекаем все span элементы
        all_spans = self.soup.find_all('span')
        
        # Флаг для отслеживания секции инструкций
        in_instructions_section = False
        instruction_texts = []
        seen_instructions = set()
        
        for span in all_spans:
            text = span.get_text(strip=True)
            
            # Начинаем собирать инструкции после заголовка
            if any(keyword in text for keyword in stop_keywords):
                in_instructions_section = True
                continue
            
            # Останавливаемся на следующих заголовках секций (Notes, Tips, etc.)
            if text.endswith(':') and len(text) < 30:
                # Это может быть новый заголовок секции
                if any(word in text for word in ['Note', 'Tips', 'Storage', 'Serving']):
                    break
            
            # Собираем инструкции
            if in_instructions_section:
                # Пропускаем пустые и очень короткие строки
                if not text or len(text) < 15:
                    continue
                
                # Пропускаем дубликаты
                if text in seen_instructions:
                    continue
                
                # Проверяем, что это действительно инструкция (содержит глаголы действия)
                # Инструкции обычно начинаются с глаголов: Mix, Add, Bake, Place, etc.
                cleaned = self.clean_text(text)
                if cleaned:
                    instruction_texts.append(cleaned)
                    seen_instructions.add(text)
        
        if instruction_texts:
            # Объединяем все инструкции в один текст
            return ' '.join(instruction_texts)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Категория обычно находится в третьем H1 теге
        h1_tags = self.soup.find_all('h1')
        
        # Проверяем последний h1 (обычно третий)
        if len(h1_tags) >= 3:
            last_h1_text = h1_tags[2].get_text(strip=True)
            
            # Специальные случаи маппинга
            if last_h1_text == 'Pastries':
                return 'Dessert'
            elif last_h1_text in ['Cookies', 'Dessert', 'Appetizer', 'Main Course', 'Salad', 'Soup', 'Breakfast']:
                # Для "Cookies" - используем эвристику на основе названия блюда
                # Если рецепт содержит традиционное итальянское название (не стандартное английское),
                # то это скорее всего "Dessert"
                if last_h1_text == 'Cookies':
                    dish_name = self.extract_dish_name()
                    if dish_name:
                        # Итальянские/традиционные печенья обычно категория "Dessert"
                        # Стандартные американские - "Cookies"
                        # Простая эвристика: если название заканчивается на -i или содержит итальянские слова
                        italian_patterns = ['cci', 'tti', 'oli', 'zzi']
                        if any(pattern in dish_name.lower() for pattern in italian_patterns):
                            return 'Dessert'
                    # Иначе возвращаем "Cookies"
                    return 'Cookies'
                return last_h1_text
        
        # По умолчанию возвращаем "Dessert" для сайта с рецептами десертов
        return 'Dessert'
    
    def extract_time(self, time_label: str) -> Optional[str]:
        """
        Извлечение времени приготовления
        
        Args:
            time_label: Label для времени (например, "Prep", "Cook", "Total")
        """
        # Ищем текст, содержащий время в формате "30 minutes", "10 to 15 minutes", etc.
        all_spans = self.soup.find_all('span')
        
        # Для prep time ищем текст с "refrigerat", "chill", "rest"
        # Для cook time ищем текст с "bake", "cook", "oven"
        # Для total time пытаемся сложить prep + cook или искать явное указание
        
        prep_time_value = None
        cook_time_value = None
        
        for span in all_spans:
            text = span.get_text(strip=True).lower()
            
            # Пропускаем, если нет упоминания времени
            if 'minute' not in text and 'hour' not in text:
                continue
            
            # Извлекаем значение времени
            time_match = re.search(r'(\d+(?:\s*to\s*\d+|\s*-\s*\d+)?)\s*(?:minutes?|mins?)', text, re.IGNORECASE)
            if not time_match:
                continue
                
            time_value = time_match.group(1)
            
            # Определяем тип времени по контексту
            if any(word in text for word in ['refrigerat', 'chill', 'rest', 'place both dough']):
                # Это prep time
                if time_label.lower() in ['prep', 'preparation']:
                    return f"{time_value} minutes"
                prep_time_value = time_value
                
            elif any(word in text for word in ['bake', 'cook', 'oven', 'hot oven']):
                # Это cook time
                if time_label.lower() == 'cook':
                    return f"{time_value} minutes"
                cook_time_value = time_value
        
        # Для total time пытаемся вычислить
        if time_label.lower() == 'total':
            if prep_time_value and cook_time_value:
                # Парсим числа и складываем
                try:
                    # Обрабатываем prep time
                    prep_num = int(prep_time_value.split()[0])
                    
                    # Обрабатываем cook time (может быть диапазон "10 to 15" или "12-13")
                    if 'to' in cook_time_value or '-' in cook_time_value:
                        # Берем максимальное значение из диапазона
                        numbers = re.findall(r'\d+', cook_time_value)
                        if numbers:
                            cook_num = max(int(n) for n in numbers)
                        else:
                            cook_num = 0
                    else:
                        cook_num = int(cook_time_value.split()[0])
                    
                    total = prep_num + cook_num
                    return f"{total} minutes"
                except (ValueError, IndexError):
                    pass
            # Если не можем вычислить, возвращаем None
            return None
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        return self.extract_time('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('total')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок/примечаний"""
        # Ищем текст, который начинается с "You may", "Storage", "Tips", "These cookies", etc.
        notes_keywords = ['You may', 'Storage', 'Tips', 'Note:', 'Notes:', 'Many things', 'These cookies', 'Feel free']
        
        all_spans = self.soup.find_all('span')
        notes_texts = []
        seen_notes = set()
        
        for span in all_spans:
            text = span.get_text(strip=True)
            
            # Пропускаем дубликаты
            if text in seen_notes:
                continue
            
            # Проверяем, начинается ли текст с ключевых слов для заметок
            if text and any(text.startswith(keyword) for keyword in notes_keywords):
                cleaned = self.clean_text(text)
                if cleaned and len(cleaned) > 20:
                    notes_texts.append(cleaned)
                    seen_notes.add(text)
        
        if notes_texts:
            return ' '.join(notes_texts)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Tags are not reliably present in the HTML for this site
        # They might be added manually or stored in a database
        # Return None if not found in common places
        
        # Проверяем мета-теги
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            if tags_list:
                # Фильтруем короткие теги
                filtered = [tag for tag in tags_list if len(tag) >= 3]
                if filtered:
                    return ', '.join(filtered)
        
        # Если не нашли в мета-тегах, возвращаем None
        # (теги могут отсутствовать в HTML и храниться отдельно)
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем изображения в теге img
        images = self.soup.find_all('img')
        
        for img in images:
            src = img.get('src')
            if src and src.startswith('http'):
                # Фильтруем служебные изображения (логотипы, иконки, аватары)
                if not any(word in src.lower() for word in ['logo', 'icon', 'avatar', 'button', 'social']):
                    # Проверяем, что это изображение из медиа-библиотеки сайта
                    # Используем более безопасную проверку с urlparse
                    from urllib.parse import urlparse
                    try:
                        parsed_url = urlparse(src)
                        # Проверяем домен изображения более строго (exact match или subdomain)
                        netloc = parsed_url.netloc.lower()
                        if (netloc == 'wixstatic.com' or netloc.endswith('.wixstatic.com') or
                            netloc == 'nonnaantoinette.com' or netloc.endswith('.nonnaantoinette.com')):
                            if src not in urls:
                                urls.append(src)
                    except Exception:
                        # Если не удалось распарсить URL, пропускаем
                        continue
        
        # Ограничиваем количество изображений (обычно не больше 10)
        if urls:
            # Возвращаем через запятую без пробелов
            return ','.join(urls[:10])
        
        return None
    
    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта"""
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
            "tags": self.extract_tags()
        }


def main():
    """
    Точка входа для обработки HTML файлов nonnaantoinette.com
    Обрабатывает все HTML файлы в директории preprocessed/nonnaantoinette_com
    """
    import os
    
    # Определяем путь к директории с HTML файлами
    script_dir = Path(__file__).parent.parent
    html_dir = script_dir / 'preprocessed' / 'nonnaantoinette_com'
    
    if html_dir.exists():
        print(f"Обработка файлов из {html_dir}")
        process_directory(NonnaAntoinetteExtractor, str(html_dir))
    else:
        print(f"Директория {html_dir} не найдена")


if __name__ == '__main__':
    main()
