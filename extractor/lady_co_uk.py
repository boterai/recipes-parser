"""
Экстрактор данных рецептов для сайта lady.co.uk
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class LadyCoUkExtractor(BaseRecipeExtractor):
    """Экстрактор для lady.co.uk"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке страницы (h1 с классом title)
        h1_title = self.soup.find('h1', class_='title')
        if h1_title:
            return self.clean_text(h1_title.get_text())
        
        # Альтернативно - из meta тега title
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем суффикс " | lady.co.uk"
            title = re.sub(r'\s*\|\s*lady\.co\.uk.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в параграфах описание
        paragraphs = self.soup.find_all('p')
        
        for p in paragraphs:
            text = p.get_text(strip=True)
            
            # Вариант 1: Ищем паттерн "This/It was a dish served ... involving ..."
            match = re.search(r'((?:This|It) was a dish served [^.]+\.)', text, re.IGNORECASE)
            if match:
                desc = self.clean_text(match.group(1))
                # Добавляем также часть про "involving" если она есть в следующих предложениях
                involving_match = re.search(r'involving ([^.]+)', text, re.IGNORECASE)
                if involving_match:
                    full_desc = f"A dish served to George V, involving {involving_match.group(1)}."
                    return self.clean_text(full_desc)
                return desc
            
            # Вариант 2: Ищем просто "involving"
            if 'involving' in text.lower() and len(text) > 30:
                # Ищем предложение с "involving"
                sentences = re.split(r'[.!?]', text)
                for sentence in sentences:
                    if 'involving' in sentence.lower() and len(sentence) > 20:
                        desc = self.clean_text(sentence.strip())
                        if desc and not desc.endswith('.'):
                            desc += '.'
                        # Попробуем извлечь только часть про блюдо
                        # "baked potatoes filled with ..."
                        match2 = re.search(r'involving ([^,]+,[^,]+, and [^.]+)', desc, re.IGNORECASE)
                        if match2:
                            return f"A dish involving {match2.group(1)}."
                        return desc
        
        # Вариант 3: Ищем фразы типа "light and savoury/savory"
        for p in paragraphs:
            text = p.get_text(strip=True)
            if any(phrase in text.lower() for phrase in ['light and savory', 'light and savoury']):
                # Извлекаем первое предложение
                sentences = re.split(r'[.!?]', text)
                if sentences and len(sentences[0]) > 20 and len(sentences[0]) < 300:
                    desc = self.clean_text(sentences[0].strip())
                    if desc and not desc.endswith('.'):
                        desc += '.'
                    return desc
        
        # Вариант 4: Ищем описание в первом параграфе, если он содержит кулинарные термины
        for p in paragraphs:
            text = p.get_text(strip=True)
            if any(word in text.lower() for word in ['recipe for', 'simple recipe']):
                if len(text) > 20 and len(text) < 300:
                    # Берем первое предложение
                    sentences = re.split(r'[.!?]', text)
                    if sentences:
                        desc = self.clean_text(sentences[0].strip())
                        if desc and not desc.endswith('.'):
                            desc += '.'
                        return desc
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Способ 1: Ищем текст с маркером ◆ (ромбик)
        all_text = self.soup.get_text()
        lines = all_text.split('\n')
        ingredient_lines = []
        collecting_ingredients = False
        
        for line in lines:
            line = line.strip()
            
            # Начинаем собирать ингредиенты после "SERVES"
            if re.match(r'SERVES\s+\d+', line, re.IGNORECASE):
                collecting_ingredients = True
                continue
            
            # Останавливаемся на первом шаге инструкции
            if re.match(r'^\d+\.\s+', line) and collecting_ingredients:
                break
            
            if line.startswith('◆') and collecting_ingredients:
                # Убираем маркер ◆
                ingredient_text = line.replace('◆', '').strip()
                
                # Пропускаем служебные строки
                if 'YOU WILL NEED' in ingredient_text:
                    continue
                if len(ingredient_text) > 100:  # Слишком длинная строка - вероятно, не ингредиент
                    continue
                
                ingredient_lines.append(ingredient_text)
        
        # Способ 2: Если не нашли через ◆, ищем через <li> теги
        if not ingredient_lines:
            # Ищем все <ul> перед первым шагом инструкций
            uls = self.soup.find_all('ul')
            for ul in uls:
                # Проверяем, что это список ингредиентов, а не навигация
                ul_text = ul.get_text(strip=True)
                # Пропускаем списки меню и навигации
                if any(word in ul_text.lower() for word in ['subscribe', 'login', 'register', 'menu', 'browse', 'contact']):
                    continue
                
                # Получаем все <li> элементы
                items = ul.find_all('li')
                if items and len(items) > 2:  # Минимум 3 элемента, чтобы это был список ингредиентов
                    # Проверяем, что хотя бы один элемент похож на ингредиент
                    sample_text = items[0].get_text(strip=True)
                    if re.match(r'^\d+', sample_text):  # Начинается с цифры - вероятно, ингредиент
                        for item in items:
                            ingredient_text = item.get_text(strip=True)
                            if ingredient_text and len(ingredient_text) < 200:
                                ingredient_lines.append(ingredient_text)
                        break  # Нашли список ингредиентов, выходим
        
        # Парсим каждый ингредиент
        for ingredient_text in ingredient_lines:
            parsed = self.parse_ingredient(ingredient_text)
            if parsed:
                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "100g butter" или "4 medium baking potatoes, washed"
            
        Returns:
            dict: {"name": "butter", "amount": "100", "unit": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Сначала пробуем числовой паттерн в начале
        # Примеры: "100g butter", "4 medium baking potatoes", "1 tsp vanilla"
        
        # Паттерн 1: число + единица измерения + название
        pattern1 = r'^(\d+(?:\.\d+)?)\s*(g|kg|ml|l|tsp|tbsp|tablespoon|teaspoon|cup|oz|lb)?\s*(.+)$'
        match = re.match(pattern1, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка названия - удаляем лишние описания в скобках и после запятой
            name = re.sub(r'\([^)]*\)', '', name)  # Убираем скобки
            name = re.sub(r',.*$', '', name)  # Убираем все после запятой
            name = name.strip()
            
            # Убираем лишние слова типа "plus extra for"
            name = re.sub(r'\bplus extra.*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\bextra for.*$', '', name, flags=re.IGNORECASE)
            name = name.strip()
            
            return {
                "name": name,
                "amount": amount_str,
                "unit": unit if unit else None
            }
        
        # Паттерн 2: просто название (без числа) или особые случаи
        # Примеры: "Salt and freshly ground black pepper", "Handful of cheese"
        
        # Проверяем наличие "handful", "pinch", "big pinch"
        match_special = re.search(r'^(handful|big pinch|pinch|dash|sprinkle)\s+of\s+(.+)$', text, re.IGNORECASE)
        if match_special:
            amount_text, name = match_special.groups()
            name = re.sub(r',.*$', '', name).strip()
            return {
                "name": name,
                "amount": amount_text,
                "unit": None
            }
        
        # Паттерн для "X [descriptor] Y" (например, "2 egg yolks plus 8 egg whites")
        # Разбиваем по "plus" или "and" и берем только первую часть
        if ' plus ' in text.lower():
            parts = re.split(r'\s+plus\s+', text, maxsplit=1, flags=re.IGNORECASE)
            if parts:
                # Рекурсивно парсим первую часть
                return self.parse_ingredient(parts[0])
        
        # Паттерн для "Salt and pepper" - берем как есть
        if re.match(r'^(salt|pepper|black pepper)', text, re.IGNORECASE):
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
        
        # Если не смогли распарсить, возвращаем как есть
        return {
            "name": text,
            "amount": None,
            "unit": None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем пронумерованные шаги (1., 2., 3., и т.д.)
        all_text = self.soup.get_text()
        
        # Разбиваем текст на строки
        lines = all_text.split('\n')
        
        # Ищем строки, начинающиеся с "1.", "2.", и т.д.
        for line in lines:
            line = line.strip()
            # Проверяем, начинается ли строка с номера и точки
            match = re.match(r'^(\d+)\.\s+(.+)$', line)
            if match:
                step_num, step_text = match.groups()
                step_text = self.clean_text(step_text)
                if step_text and len(step_text) > 10:  # Фильтруем короткие строки
                    steps.append(f"{step_num}. {step_text}")
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Для lady.co.uk категория может быть в тегах или в тексте
        # Проверяем, есть ли упоминание "STARTER", "DESSERT", и т.д. в тексте
        all_text = self.soup.get_text().upper()
        
        if 'AS A STARTER' in all_text or 'STARTER' in all_text:
            return 'Starter'
        elif 'DESSERT' in all_text or 'BISCUITS' in all_text:
            return 'Dessert'
        elif 'MAIN' in all_text:
            return 'Main Course'
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте упоминания времени
        all_text = self.soup.get_text()
        
        # Паттерны для поиска времени готовки
        patterns = [
            r'bake.*?for.*?(\d+)\s*minutes?',
            r'cook.*?for.*?(\d+)\s*minutes?',
            r'bake.*?for.*?(?:about|approximately)?\s*(\d+)\s*minutes?',
            r'for an hour',  # специальный случай
        ]
        
        for pattern in patterns:
            match = re.search(pattern, all_text, re.IGNORECASE)
            if match:
                if 'hour' in pattern:
                    return '60 minutes'
                else:
                    minutes = match.group(1)
                    return f'{minutes} minutes'
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # В данных примерах prep_time часто не указано явно
        # Можно попытаться найти в тексте
        all_text = self.soup.get_text()
        
        patterns = [
            r'prep.*?(\d+)\s*minutes?',
            r'preparation.*?(\d+)\s*minutes?',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, all_text, re.IGNORECASE)
            if match:
                minutes = match.group(1)
                return f'{minutes} minutes'
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # В примерах часто не указано явно
        all_text = self.soup.get_text()
        
        patterns = [
            r'total.*?(\d+)\s*minutes?',
            r'total.*?(\d+)\s*hours?',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, all_text, re.IGNORECASE)
            if match:
                time_value = match.group(1)
                if 'hour' in pattern:
                    return f'{int(time_value) * 60} minutes'
                else:
                    return f'{time_value} minutes'
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Заметки могут быть в двух местах:
        # 1. До списка ингредиентов (обычно последнее предложение параграфа перед SERVES)
        # 2. После списка инструкций
        
        all_text = self.soup.get_text()
        lines = all_text.split('\n')
        
        # Ищем заметки ПЕРЕД "SERVES" (более распространенный случай)
        for i, line in enumerate(lines):
            if re.match(r'SERVES\s+\d+', line, re.IGNORECASE):
                # Смотрим на несколько строк до SERVES
                for j in range(max(0, i-10), i):
                    candidate = lines[j].strip()
                    # Ищем строки с определенными паттернами
                    if any(phrase in candidate.lower() for phrase in [
                        'original recipe contains',
                        'make sure everyone',
                        'keeps for up to',
                        "it's an embellishment",
                        'soufflé waits for no one'
                    ]):
                        # Нашли заметку
                        note = self.clean_text(candidate)
                        # Извлекаем только релевантное предложение
                        sentences = note.split('.')
                        for sent in sentences:
                            if any(p in sent.lower() for p in [
                                'original recipe',
                                'make sure',
                                'keeps for',
                                'embellishment',
                                'waits for no one'
                            ]):
                                result = sent.strip()
                                if result and not result.endswith('.'):
                                    result += '.'
                                return result
                break
        
        # Также ищем заметки ПОСЛЕ последнего шага инструкции
        last_step_idx = -1
        last_step_num = 0
        for i, line in enumerate(lines):
            match = re.match(r'^(\d+)\.\s+', line.strip())
            if match:
                step_num = int(match.group(1))
                if step_num > last_step_num:
                    last_step_num = step_num
                    last_step_idx = i
        
        # Ищем заметки после последнего шага
        if last_step_idx >= 0:
            for i in range(last_step_idx + 1, min(last_step_idx + 15, len(lines))):
                line = lines[i].strip()
                # Проверяем, содержит ли строка полезную информацию
                if line and len(line) > 20 and len(line) < 200:
                    # Пропускаем строки с "This recipe appeared", "is published"
                    if any(skip in line.lower() for skip in ['this recipe appeared', 'is published', 'giuseppe', 'tom parker', 'cooking &']):
                        continue
                    # Пропускаем служебные строки
                    if any(word in line.lower() for word in ['copyright', 'all rights', '©', 'rather leave the cooking']):
                        continue
                    # Если строка начинается не с цифры и не с ◆
                    if not re.match(r'^\d+\.', line) and not line.startswith('◆'):
                        # Это может быть заметка
                        note = self.clean_text(line)
                        # Проверяем, что это действительно похоже на заметку
                        if note and len(note) > 15:
                            # Дополнительная проверка на содержание
                            if any(word in note.lower() for word in ['keeps for', 'keep for', 'serve', 'tip:', 'note:']):
                                return note
                            # Или если это первая подходящая строка после инструкций (но не прошла проверки выше)
                            # пропускаем ее
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Теги могут быть в meta-тегах или в тексте
        # Для lady.co.uk проверим описание и содержимое
        
        tags = []
        
        # Ищем ключевые слова в тексте, которые могут быть тегами
        all_text = self.soup.get_text().lower()
        
        # Список возможных тегов на основе контента
        possible_tags = {
            'soufflé': 'soufflé',
            'souffle': 'soufflé',
            'smoked haddock': 'smoked haddock',
            'starter': 'starter',
            'dessert': 'dessert',
            'biscuits': 'biscuits',
            'italian': 'Italian',
            'main course': 'main course',
            'main dish': 'main dish',
        }
        
        for keyword, tag in possible_tags.items():
            if keyword in all_text and tag not in tags:
                tags.append(tag)
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url and url.startswith('http'):
                urls.append(url)
        
        # 2. Ищем в twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if url and url.startswith('http') and url not in urls:
                urls.append(url)
        
        # Убираем дубликаты и форматируем
        if urls:
            unique_urls = []
            seen = set()
            for url in urls:
                if url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            return ','.join(unique_urls)
        
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
    import os
    # Обрабатываем папку preprocessed/lady_co_uk
    recipes_dir = os.path.join("preprocessed", "lady_co_uk")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(LadyCoUkExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python lady_co_uk.py")


if __name__ == "__main__":
    main()
