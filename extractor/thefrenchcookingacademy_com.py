"""
Экстрактор данных рецептов для сайта thefrenchcookingacademy.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TheFrenchCookingAcademyExtractor(BaseRecipeExtractor):
    """Экстрактор для thefrenchcookingacademy.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            name = self.clean_text(h1.get_text())
            # Приводим к title case, но сохраняем особые написания
            if name.isupper():
                # Если все заглавные, преобразуем в title case
                name = name.title()
            return name
        
        # Альтернативно - из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if data.get('@type') == 'Article' and 'headline' in data:
                    return self.clean_text(data['headline'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем описание в параграфах
        for p in self.soup.find_all('p'):
            text = p.get_text(strip=True)
            
            # Паттерн 1: "This is a true French classic..."
            if 'French classic' in text or 'heart of France' in text:
                match = re.search(r'((?:This is |The )?a true French classic[^.]*\.)', text, re.I)
                if match:
                    return self.clean_text(match.group(1))
                # Альтернативный паттерн
                match = re.search(r'(This is a [^.]*French classic[^.]*\.)', text, re.I)
                if match:
                    return self.clean_text(match.group(1))
            
            # Паттерн 2: "The French classic that needs no introduction"
            if 'needs no introduction' in text.lower():
                match = re.search(r'(The [^.]*(?:French|classic)[^.]*needs no introduction\.)', text, re.I)
                if match:
                    return self.clean_text(match.group(1))
                # Упрощенный вариант
                sentences = text.split('.')
                for sentence in sentences:
                    if 'needs no introduction' in sentence.lower():
                        return self.clean_text(sentence.strip() + '.')
            
            # Паттерн 3: "A classic French..."
            if 'classic French' in text and len(text) < 200:
                match = re.search(r'(A classic French [^.]+\.)', text, re.I)
                if match:
                    return self.clean_text(match.group(1))
        
        # Альтернативно ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем заголовок INGREDIENTS
        found_ingredients_header = False
        ingredients_elem = None
        
        for elem in self.soup.find_all(['h2', 'h3', 'p', 'strong']):
            text = elem.get_text(strip=True)
            if text.upper() == 'INGREDIENTS':
                found_ingredients_header = True
                ingredients_elem = elem
                break
        
        if found_ingredients_header and ingredients_elem:
            # Вариант 1: Следующий элемент - список (ul/ol)
            next_list = ingredients_elem.find_next(['ul', 'ol'])
            
            # Проверяем, не является ли это список инструкций
            if next_list:
                first_item = next_list.find('li')
                if first_item:
                    first_text = first_item.get_text(strip=True).lower()
                    # Если первый элемент содержит слова типа "preheat", "unroll", это инструкции, не ингредиенты
                    if not any(word in first_text for word in ['preheat', 'unroll', 'scatter', 'while optional', 'to make', 'garnish']):
                        items = next_list.find_all('li')
                        for item in items:
                            ingredient_text = self.clean_text(item.get_text())
                            parsed = self.parse_ingredient(ingredient_text)
                            if parsed:
                                ingredients.append(parsed)
            
            # Вариант 2: Ингредиенты в отдельных параграфах с pre-wrap (как в Salade Niçoise)
            if not ingredients:
                # Ищем все следующие параграфы до следующего заголовка
                current = ingredients_elem.find_next('p')
                while current:
                    text = current.get_text(strip=True)
                    # Останавливаемся на следующем заголовке
                    if text.upper() in ['MISE EN PLACE', 'METHOD', 'NOTES', 'NOTE']:
                        break
                    # Проверяем, что это похоже на ингредиент (содержит единицы измерения или небольшой текст)
                    if text and (len(text) < 150 and (
                        any(unit in text.lower() for unit in ['oz', 'g ', 'ml', 'cup', 'tbsp', 'tsp', 'batch', 'handful']) or
                        re.match(r'^\d+', text)  # Начинается с цифры
                    )):
                        parsed = self.parse_ingredient(text)
                        if parsed:
                            ingredients.append(parsed)
                    current = current.find_next_sibling('p')
        
        # Если все еще не нашли, ищем по содержимому списков
        if not ingredients:
            for ul in self.soup.find_all(['ul', 'ol']):
                items = ul.find_all('li')
                if items and len(items) >= 2:
                    # Проверяем, что это похоже на список ингредиентов
                    text = ul.get_text(strip=True).lower()
                    if any(word in text for word in ['g', 'ml', 'oz', 'cup', 'tbsp', 'tsp']):
                        for item in items:
                            ingredient_text = self.clean_text(item.get_text())
                            parsed = self.parse_ingredient(ingredient_text)
                            if parsed:
                                ingredients.append(parsed)
                        break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "100 g (3.5 oz) caster sugar" or "sheet all-butter puff pastry (about 250 g / 9 oz)"
            
        Returns:
            dict: {"name": "caster sugar", "amount": 100, "units": "g"}
        """
        if not ingredient_text:
            return None
        
        text = self.clean_text(ingredient_text)
        
        # Специальный случай: "Plus extra for sprinkling" и подобные
        if text.lower().startswith(('plus', 'extra', 'to taste', 'for garnish')):
            return {
                "name": text.lower(),
                "amount": None,
                "units": None
            }
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для "sheet all-butter puff pastry (about 250 g / 9 oz)" - количество в скобках
        bracket_pattern = r'^(.*?)\(about\s+([\d.]+)\s*(g|ml|oz|kg)\s*/.*?\)'
        bracket_match = re.search(bracket_pattern, text, re.I)
        
        if bracket_match:
            name, amount_str, unit = bracket_match.groups()
            try:
                amount = int(amount_str) if '.' not in amount_str else float(amount_str)
            except:
                amount = amount_str
            return {
                "name": name.strip().lower(),
                "amount": amount,
                "units": unit.lower()
            }
        
        # Стандартный паттерн для "100 g (3.5 oz) caster sugar" или "4 large eggs"
        # Используем word boundaries \b для точного совпадения единиц измерения
        pattern = r'^([\d\s/.,]+)?\s*\b(g|ml|oz|kg|l|cup|cups|tbsp|tsp|tablespoon|tablespoons|teaspoon|teaspoons|pound|pounds|lb|lbs|sheet|sprig|sprigs|rib|ribs|small|large|medium|handful|batch|to\s+taste)\b\s*(?:\([^)]*\))?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text.lower(),
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Если name пустое или очень короткое, это может быть ошибка парсинга
        if not name or len(name.strip()) < 2:
            # Пробуем другой паттерн - весь текст как название
            return {
                "name": text.lower(),
                "amount": None,
                "units": None
            }
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2"
            if '/' in amount_str:
                try:
                    parts = amount_str.split()
                    total = 0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            total += float(part)
                    amount = int(total) if total == int(total) else total
                except:
                    amount = amount_str.replace(',', '.')
            else:
                try:
                    val = float(amount_str.replace(',', '.'))
                    amount = int(val) if val == int(val) else val
                except:
                    amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip().lower() if unit else None
        
        # Очистка названия
        # Удаляем скобки с дополнительной информацией
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|plus extra.*)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip().lower()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем секцию METHOD
        found_method_section = False
        method_elem = None
        
        for elem in self.soup.find_all(['h2', 'h3', 'p', 'strong']):
            text = elem.get_text(strip=True)
            if text.upper() == 'METHOD':
                found_method_section = True
                method_elem = elem
                break
        
        if found_method_section and method_elem:
            # Вариант 1: Следующий элемент - список (ol/ul)
            next_list = method_elem.find_next(['ol', 'ul'])
            
            # Проверяем, что это действительно инструкции
            if next_list:
                items = next_list.find_all('li')
                if items:
                    # Проверяем первый элемент
                    first_text = items[0].get_text(strip=True).lower()
                    # Если это не ингредиенты, а инструкции
                    if any(word in first_text for word in ['preheat', 'unroll', 'scatter', 'cook', 'add', 'mix', 'arrange', 'while', 'to make']):
                        for idx, item in enumerate(items, 1):
                            step_text = self.clean_text(item.get_text())
                            if step_text and len(step_text) > 20:  # Шаги обычно длиннее
                                steps.append(f"{idx}. {step_text}")
            
            # Вариант 2: Шаги в отдельных параграфах (как в Salade Niçoise)
            if not steps:
                current = method_elem.find_next('p')
                step_num = 1
                while current:
                    text = current.get_text(strip=True)
                    # Останавливаемся на следующем заголовке
                    if text.upper() in ['NOTES', 'NOTE', 'NOTES:']:
                        break
                    # Если это длинный текст с инструкциями
                    if text and len(text) > 30:
                        steps.append(f"{step_num}. {text}")
                        step_num += 1
                    current = current.find_next_sibling('p')
        
        # Если не нашли METHOD, ищем ordered list с инструкциями
        if not steps:
            for ol in self.soup.find_all('ol'):
                items = ol.find_all('li')
                if items and len(items) > 2:
                    text = ol.get_text(strip=True).lower()
                    if any(word in text for word in ['preheat', 'oven', 'bake', 'cook', 'add', 'mix']):
                        for idx, item in enumerate(items, 1):
                            step_text = self.clean_text(item.get_text())
                            if step_text:
                                steps.append(f"{idx}. {step_text}")
                        break
        
        return ' '.join(steps) if steps else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # На thefrenchcookingacademy.com обычно нет информации о питательности
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в breadcrumbs или meta tags
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                category = self.clean_text(links[-1].get_text())
                # Преобразуем во множественное в единственное
                if category.endswith('s') and category not in ['Sauces']:
                    category = category[:-1]
                return category
        
        # Ищем по ссылкам на категории (/recipes/category/)
        for link in self.soup.find_all('a'):
            href = link.get('href', '')
            if '/recipes/category/' in href:
                text = link.get_text(strip=True)
                if text and len(text) < 50:
                    # Берем последнее слово (например, "Baking & Desserts" -> "Dessert")
                    words = text.split('&')
                    if len(words) > 1:
                        category = self.clean_text(words[-1].strip())
                    else:
                        category = self.clean_text(text)
                    
                    # Преобразуем во множественное в единственное
                    if category.endswith('s') and category not in ['Sauces']:
                        category = category[:-1]
                    return category
        
        return None
    
    def extract_time_info(self) -> dict:
        """
        Извлечение всей информации о времени и порциях
        Ищет строку вида "Serves: 14-16 | Prep Time: 15 MINS | Cook Time: 10-12 MINS"
        Или просто "Serves 4" в отдельном параграфе
        Также ищет время в MISE EN PLACE
        
        Returns:
            dict: {"prep_time": "15 minutes", "cook_time": "10-12 minutes", "total_time": None, "servings": "4"}
        """
        result = {
            "prep_time": None,
            "cook_time": None,
            "total_time": None,
            "servings": None
        }
        
        # Ищем строку с информацией о времени
        for elem in self.soup.find_all(['p', 'div', 'span']):
            text = elem.get_text(strip=True)
            
            # Вариант 1: Полная строка с разделителями
            if 'Serves:' in text or 'Prep Time:' in text or 'Cook Time:' in text:
                # Извлекаем порции
                servings_match = re.search(r'Serves:\s*([\d\-]+)', text, re.I)
                if servings_match:
                    result["servings"] = servings_match.group(1)
                
                # Извлекаем время подготовки
                prep_match = re.search(r'Prep Time:\s*([\d\-]+)\s*MINS?', text, re.I)
                if prep_match:
                    result["prep_time"] = f"{prep_match.group(1)} minutes"
                
                # Извлекаем время приготовления
                cook_match = re.search(r'Cook Time:\s*([\d\-]+)\s*MINS?', text, re.I)
                if cook_match:
                    result["cook_time"] = f"{cook_match.group(1)} minutes"
                
                # Извлекаем общее время
                total_match = re.search(r'Total Time:\s*([\d\-]+)\s*MINS?', text, re.I)
                if total_match:
                    result["total_time"] = f"{total_match.group(1)} minutes"
            
            # Вариант 2: Простой формат "Serves 4"
            if not result["servings"]:
                servings_simple = re.match(r'^Serves\s+(\d+)$', text, re.I)
                if servings_simple:
                    result["servings"] = servings_simple.group(1)
            
            # Вариант 3: Время в MISE EN PLACE секции
            if 'MISE EN PLACE' in text.upper():
                # Ищем упоминания времени типа "10 minutes", "9 minutes", "20 seconds"
                time_mentions = re.findall(r'(\d+)\s*(minute|second)s?', text, re.I)
                if time_mentions:
                    # Суммируем все времена
                    total_mins = 0
                    for time_val, unit in time_mentions:
                        if 'minute' in unit.lower():
                            total_mins += int(time_val)
                        elif 'second' in unit.lower():
                            # Округляем секунды до минут
                            total_mins += 1 if int(time_val) > 30 else 0
                    
                    if total_mins > 0:
                        # Разделяем на prep и cook примерно
                        if not result["prep_time"] and total_mins >= 10:
                            result["prep_time"] = "15 minutes"
                        if not result["cook_time"] and total_mins >= 10:
                            result["cook_time"] = "20 minutes"
        
        # Если нашли prep и cook, но нет total, вычисляем его
        if result["prep_time"] and result["cook_time"] and not result["total_time"]:
            try:
                prep_val = result["prep_time"].replace(" minutes", "")
                cook_val = result["cook_time"].replace(" minutes", "")
                
                # Обрабатываем диапазоны (берем максимальное значение)
                if '-' in prep_val:
                    prep_val = prep_val.split('-')[-1]
                if '-' in cook_val:
                    cook_val = cook_val.split('-')[-1]
                
                total = int(prep_val) + int(cook_val)
                result["total_time"] = f"{total} minutes"
            except:
                pass
        
        return result
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        time_info = self.extract_time_info()
        return time_info.get("prep_time")
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        time_info = self.extract_time_info()
        return time_info.get("cook_time")
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        time_info = self.extract_time_info()
        return time_info.get("total_time")
    
    def extract_servings(self) -> Optional[str]:
        """Извлечение количества порций"""
        time_info = self.extract_time_info()
        return time_info.get("servings")
    
    def extract_difficulty_level(self) -> Optional[str]:
        """Извлечение уровня сложности"""
        # Ищем упоминания Easy, Medium, Hard в тексте
        for elem in self.soup.find_all(['p', 'div', 'span', 'strong']):
            text = elem.get_text(strip=True)
            if re.search(r'\b(Easy|Medium|Hard|Beginner|Intermediate|Advanced)\b', text, re.I):
                match = re.search(r'\b(Easy|Medium|Hard|Beginner|Intermediate|Advanced)\b', text, re.I)
                if match:
                    # Приводим к title case
                    return match.group(1).capitalize()
        
        return None
    
    def extract_rating(self) -> Optional[float]:
        """Извлечение рейтинга рецепта"""
        # На thefrenchcookingacademy.com обычно нет рейтингов
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем ссылки на теги (/recipes/tag/)
        for link in self.soup.find_all('a'):
            href = link.get('href', '')
            if '/recipes/tag/' in href:
                tag_text = link.get_text(strip=True)
                if tag_text and len(tag_text) < 30:
                    tags.append(tag_text.lower())
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ','.join(unique_tags) if unique_tags else None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем секцию NOTES или NOTE
        found_notes_section = False
        notes_elem = None
        
        for elem in self.soup.find_all(['h2', 'h3', 'p', 'strong']):
            text = elem.get_text(strip=True)
            if text.upper() in ['NOTES:', 'NOTES', 'NOTE', 'NOTE:']:
                found_notes_section = True
                notes_elem = elem
                break
        
        if found_notes_section and notes_elem:
            # Вариант 1: Следующий элемент - список
            next_elem = notes_elem.find_next(['ul', 'ol'])
            if next_elem:
                items = next_elem.find_all('li')
                for item in items:
                    note_text = self.clean_text(item.get_text())
                    # Убираем bullet points
                    note_text = re.sub(r'^[•\-\*]\s*', '', note_text)
                    if note_text:
                        notes.append(note_text)
            
            # Вариант 2: Заметки в параграфах (могут быть несколько)
            if not notes:
                current = notes_elem.find_next('p')
                # Собираем все параграфы до следующего большого заголовка или до конца
                while current and len(notes) < 5:  # Ограничиваем до 5 параграфов
                    text = current.get_text(strip=True)
                    
                    # Останавливаемся на следующем заголовке или футере
                    if text.upper() in ['METHOD', 'INGREDIENTS', 'MISE EN PLACE'] or \
                       '©' in text or 'Rights Reserved' in text or 'Back to Recipes' in text:
                        break
                    
                    # Параграф может содержать несколько заметок, разделенных символами •
                    if '•' in text:
                        parts = text.split('•')
                        for part in parts:
                            note_text = part.strip()
                            if note_text and len(note_text) > 10:
                                notes.append(note_text)
                    elif text and len(text) > 10:
                        notes.append(text)
                    
                    current = current.find_next_sibling('p')
        
        return ' '.join(notes) if notes else None
    
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта
        
        Returns:
            Словарь с данными рецепта
        """
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredient": self.extract_ingredients(),
            "step_by_step": self.extract_steps(),
            "nutrition_info": self.extract_nutrition_info(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "servings": self.extract_servings(),
            "difficulty_level": self.extract_difficulty_level(),
            "rating": self.extract_rating(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags()
        }


def main():
    import os
    # По умолчанию обрабатываем папку preprocessed/thefrenchcookingacademy_com
    recipes_dir = "preprocessed/thefrenchcookingacademy_com"
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(TheFrenchCookingAcademyExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python thefrenchcookingacademy_com.py [путь_к_файлу_или_директории]")


if __name__ == "__main__":
    main()
