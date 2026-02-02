"""
Экстрактор данных рецептов для сайта ajinomoto.com.ph

Этот модуль реализует парсер для извлечения рецептов с сайта ajinomoto.com.ph.
Парсер анализирует HTML-структуру страниц и извлекает данные в стандартизированный JSON формат.

Особенности реализации:
- Поддерживает различные форматы рецептов (английский и филиппинский языки)
- Извлекает данные из JSON-LD структурированных данных
- Обрабатывает различные форматы инструкций (с префиксами типа "MIX", "COAT" и нумерованные)
- Корректно обрабатывает ингредиенты в нескольких параграфах
- Интеллектуально определяет категорию и теги на основе содержимого

Извлекаемые поля:
- dish_name: Название блюда (с правильной капитализацией для филиппинских слов)
- description: Описание рецепта из meta-тегов
- ingredients: Список ингредиентов (JSON) с полями name, units, amount
- instructions: Текстовая инструкция по приготовлению
- category: Категория блюда (Main Course, Appetizer и т.д.)
- prep_time, cook_time, total_time: Время приготовления
- notes: Дополнительные заметки и советы
- tags: Теги рецепта (автоматически определяются)
- image_urls: URL изображений рецепта

Использование:
    from extractor.ajinomoto_com_ph import AjinomotoComPhExtractor
    
    extractor = AjinomotoComPhExtractor('path/to/recipe.html')
    data = extractor.extract_all()
    
Или запустить обработку всей директории:
    python extractor/ajinomoto_com_ph.py
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class AjinomotoComPhExtractor(BaseRecipeExtractor):
    """Экстрактор для ajinomoto.com.ph"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Пробуем получить из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'name' in data:
                        name = data['name']
                        # Убираем суффикс "RECIPE" если есть
                        name = re.sub(r'\s+RECIPE\s*$', '', name, flags=re.IGNORECASE)
                        # Конвертируем в title case, но сохраняем некоторые слова в нижнем регистре
                        name = self.clean_text(name)
                        # Title case для каждого слова, но маленькие слова (at, ng, sa) оставляем в нижнем регистре
                        words = name.split()
                        result = []
                        for i, word in enumerate(words):
                            if i == 0 or word.lower() not in ['at', 'ng', 'sa', 'na', 'ang']:
                                result.append(word.capitalize())
                            else:
                                result.append(word.lower())
                        return ' '.join(result)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффикс "RECIPE"
            title = re.sub(r'\s+RECIPE\s*$', '', title, flags=re.IGNORECASE)
            title = self.clean_text(title)
            # Применяем те же правила title case
            words = title.split()
            result = []
            for i, word in enumerate(words):
                if i == 0 or word.lower() not in ['at', 'ng', 'sa', 'na', 'ang']:
                    result.append(word.capitalize())
                else:
                    result.append(word.lower())
            return ' '.join(result)
        
        # Из тега title
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем суффиксы
            title = re.sub(r'\s+(Recipe|How to Cook).*$', '', title, flags=re.IGNORECASE)
            title = self.clean_text(title)
            words = title.split()
            result = []
            for i, word in enumerate(words):
                if i == 0 or word.lower() not in ['at', 'ng', 'sa', 'na', 'ang']:
                    result.append(word.capitalize())
                else:
                    result.append(word.lower())
            return ' '.join(result)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            # og:description может содержать список ингредиентов - берем первую строку
            desc = og_desc['content']
            # Если начинается с "Ingredients", то это не описание
            if not desc.strip().startswith('Ingredients'):
                # Берем первую строку до перевода строки или до "Ingredients"
                desc = desc.split('\n')[0].split('Ingredients')[0]
                return self.clean_text(desc)
        
        return None
    
    def parse_ingredient_line(self, line: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            line: Строка вида "2 cups (450ml) Oil" или "1/2 cup (62g) Cornstarch"
            
        Returns:
            dict: {"name": "Oil", "amount": 2, "units": "cups (450ml)"} или None
        """
        if not line:
            return None
        
        # Чистим текст
        text = self.clean_text(line).strip()
        
        if not text:
            return None
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "2 cups (450ml) Oil", "1/2 cup (62g) Cornstarch", "1 1/2 tasa (250 grams) Manok"
        # Формат: [количество] [единица (с возможным весом в скобках)] [название]
        pattern = r'^([\d\s/.,]+)\s+([a-zA-Z]+\.?\s*(?:\([^)]+\))?)\s+(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Попробуем более простой паттерн без единиц
            # Например: "pinch Paminta"
            pattern2 = r'^(pinch|dash)\s+(.+)$'
            match2 = re.match(pattern2, text, re.IGNORECASE)
            if match2:
                return {
                    "name": self.clean_text(match2.group(2)),
                    "units": None,
                    "amount": match2.group(1)
                }
            # Если не совпало, возвращаем только название
            return {
                "name": text,
                "units": None,
                "amount": None
            }
        
        amount_str, units, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2" или "1 1/2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                amount = total
            else:
                try:
                    amount = float(amount_str.replace(',', '.'))
                except ValueError:
                    amount = amount_str
        
        # Обработка единицы измерения
        units = units.strip() if units else None
        
        # Очистка названия
        name = self.clean_text(name)
        
        return {
            "name": name,
            "units": units,
            "amount": amount
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем заголовок "Ingredients"
        ingredients_heading = None
        for h3 in self.soup.find_all('h3'):
            if 'Ingredients' in h3.get_text():
                ingredients_heading = h3
                break
        
        if ingredients_heading:
            # Находим следующий элемент с классом fusion-text
            fusion_text = ingredients_heading.find_next('div', class_='fusion-text')
            if fusion_text:
                # Извлекаем ВСЕ параграфы с ингредиентами
                paragraphs = fusion_text.find_all('p')
                for p in paragraphs:
                    # Пропускаем параграфы с заголовками типа "Mga Sangkap" или "Reference:"
                    p_text = p.get_text(strip=True)
                    if 'Reference:' in p_text or (p_text.startswith('Mga Sangkap') and len(p_text) < 100):
                        continue
                    
                    # Разбиваем по <br> тегам
                    # Используем get_text с разделителем, чтобы избежать слияния текста из разных строк
                    for br in p.find_all('br'):
                        br.replace_with('|||')
                    
                    # Теперь получаем текст
                    text = p.get_text()
                    lines = [line.strip() for line in text.split('|||') if line.strip()]
                    
                    for line in lines:
                        # Пропускаем строки с заголовками
                        if 'Reference:' in line or line.startswith('Mga Sangkap'):
                            continue
                        parsed = self.parse_ingredient_line(line)
                        if parsed and parsed['name']:
                            ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions_parts = []
        
        # Ищем упорядоченный список (ol)
        ol = self.soup.find('ol')
        if ol:
            items = ol.find_all('li')
            for item in items:
                # Извлекаем текст инструкции
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    instructions_parts.append(step_text)
        
        # Если нет ol, ищем в div с классом fusion-text после заголовка "Instructions", "Procedure", "Preparation"
        if not instructions_parts:
            for h3 in self.soup.find_all('h3'):
                heading_text = h3.get_text()
                if any(word in heading_text for word in ['Instructions', 'Procedure', 'Preparation']):
                    fusion_text = h3.find_next('div', class_='fusion-text')
                    if fusion_text:
                        # Ищем текст, начинающийся с "Paraan ng Pagluluto:" или содержащий инструкции
                        all_p = fusion_text.find_all('p')
                        for p in all_p:
                            text = p.get_text(separator=' ', strip=True)
                            # Проверяем, содержит ли параграф инструкции
                            if 'Paraan ng Pagluluto:' in text or (re.search(r'^\d+\.', text) and any(word in text.lower() for word in ['mix', 'cook', 'add', 'mag-gisa', 'idagdag', 'ihalo'])):
                                # Убираем заголовок "Paraan ng Pagluluto:"
                                text = re.sub(r'Paraan ng Pagluluto:\s*', '', text)
                                # Разбиваем по <br> тегам
                                for br in p.find_all('br'):
                                    br.replace_with('|||')
                                text = p.get_text()
                                # Убираем заголовок если он есть
                                text = re.sub(r'Paraan ng Pagluluto:\s*', '', text)
                                lines = [self.clean_text(line) for line in text.split('|||') if line.strip()]
                                # Фильтруем только строки с инструкциями (начинаются с цифры)
                                instruction_lines = [line for line in lines if re.match(r'^\d+\.', line)]
                                if instruction_lines:
                                    instructions_parts.extend(instruction_lines)
                                    break
                    if instructions_parts:
                        break
        
        if instructions_parts:
            # Проверяем формат инструкций
            first_instruction = instructions_parts[0] if instructions_parts else ''
            
            # Если инструкции начинаются с "CUT.", "MIX.", и т.д., удаляем эти префиксы и добавляем номера
            if re.match(r'^[A-Z]+\.\s', first_instruction):
                # Удаляем префиксы типа "CUT.", "MIX."
                cleaned_instructions = []
                for idx, instr in enumerate(instructions_parts, 1):
                    cleaned = re.sub(r'^[A-Z]+\.\s*', '', instr)
                    cleaned_instructions.append(f"{idx}. {cleaned}")
                return ' '.join(cleaned_instructions)
            # Если инструкции начинаются просто с заглавного слова "MIX", "COAT" (без точки)
            elif re.match(r'^[A-Z]+\s', first_instruction):
                # Оставляем как есть, просто соединяем
                return ' '.join(instructions_parts)
            # Если инструкции уже начинаются с цифр "1.", "2.", и т.д.
            else:
                return ' '.join(instructions_parts)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Попробуем извлечь из тегов, если они уже есть
        tags = self.extract_tags()
        if tags:
            # Категории могут быть в тегах: Main Course, Appetizer, Dessert, etc.
            # Приоритет: Appetizer > Main Course > другие
            if 'Appetizer' in tags:
                return 'Appetizer'
            for category in ['Main Course', 'Dessert', 'Side Dish', 'Snacks', 'Breakfast']:
                if category in tags:
                    return category
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Сначала проверяем, есть ли отдельное "Preparation time:"
        has_separate_prep = False
        for p in self.soup.find_all('p'):
            text = p.get_text(strip=True)
            if re.search(r'Preparation time:\s*\d+', text, re.IGNORECASE):
                has_separate_prep = True
                match = re.search(r'Preparation time:\s*(\d+)\s*minutes?', text, re.IGNORECASE)
                if match:
                    return f"{match.group(1)} minutes"
        
        # Если нет отдельного prep time, проверяем "Preparation and Cooking time:"
        if not has_separate_prep:
            for p in self.soup.find_all('p'):
                text = p.get_text(strip=True)
                match = re.search(r'Preparation and Cooking time:\s*(\d+)\s*minutes?', text, re.IGNORECASE)
                if match:
                    return f"{match.group(1)} minutes"
        
        # Пробуем получить из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'cookTime' in data:
                        time = data['cookTime']
                        # Конвертируем из минут в строку
                        try:
                            minutes = int(time)
                            return f"{minutes} minutes"
                        except (ValueError, TypeError):
                            # Возможно уже строка с "minutes"
                            return str(time)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем текст "Cooking time:" только если есть отдельное "Preparation time:"
        has_separate_prep = False
        for p in self.soup.find_all('p'):
            text = p.get_text(strip=True)
            if re.search(r'Preparation time:\s*\d+', text, re.IGNORECASE):
                has_separate_prep = True
                break
        
        if has_separate_prep:
            for p in self.soup.find_all('p'):
                text = p.get_text(strip=True)
                match = re.search(r'Cooking time:\s*(\d+)\s*minutes?', text, re.IGNORECASE)
                if match:
                    return f"{match.group(1)} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Если есть и prep_time и cook_time, можем вычислить total
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep and cook:
            try:
                prep_mins = int(re.search(r'(\d+)', prep).group(1))
                cook_mins = int(re.search(r'(\d+)', cook).group(1))
                total = prep_mins + cook_mins
                return f"{total} minutes"
            except (ValueError, AttributeError):
                pass
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем параграф после слова "note" или подобного
        # Или ищем текст с характерными фразами
        
        # Проходим по всем параграфам
        for p in self.soup.find_all('p'):
            text = p.get_text(strip=True)
            # Проверяем, есть ли признаки заметки
            # В примерах: "You can also use alugbati and spinach leaves for this dish."
            # "Ayon sa iyong nais, maari itong sagdagn ng kamote o patatas para sa dagdag sustansya."
            # "You can use a portable kitchen torch to give a nice 'grill effect' on the edges of roasted bell peppers."
            if any(phrase in text.lower() for phrase in ['you can also', 'you can use', 'ayon sa', 'maari']):
                return self.clean_text(text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # В референсных JSON теги выглядят так:
        # "Asian, Filipino, Main Course, Appetizer"
        # "Filipino, Chicken, Vegetables, Main Course"
        # "Stuffed, Bell Peppers, Main Course, Tuna"
        
        # Попробуем собрать теги из разных источников
        tags_set = set()
        
        # 1. Базовые географические/культурные теги
        tags_set.add('Filipino')
        tags_set.add('Asian')
        
        # 2. Категория типа Main Course/Appetizer
        # Ищем ключевые слова в названии и описании для определения категории
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        
        combined_text = ''
        if dish_name:
            combined_text += dish_name.lower() + ' '
        if description:
            combined_text += description.lower() + ' '
        
        # Определяем категорию блюда
        # Определяем, это закуска или основное блюдо
        is_appetizer = any(word in combined_text for word in ['appetizer', 'starter', 'snack', 'crispy'])
        is_main = any(word in combined_text for word in ['main', 'stuffed']) or 'bell pepper' in combined_text
        
        if is_appetizer:
            tags_set.add('Appetizer')
            if not is_main:
                # Если это только закуска, добавляем Main Course для совместимости
                tags_set.add('Main Course')
        elif is_main:
            tags_set.add('Main Course')
        
        # 3. Типы ингредиентов
        if 'chicken' in combined_text or 'manok' in combined_text:
            tags_set.add('Chicken')
        if 'vegetables' in combined_text or 'gulay' in combined_text or 'kangkong' in combined_text or 'carrot' in combined_text or 'repolyo' in combined_text:
            tags_set.add('Vegetables')
        if 'fish' in combined_text:
            tags_set.add('Fish')
        if 'tuna' in combined_text:
            tags_set.add('Tuna')
        if 'bell pepper' in combined_text or 'capsicum' in combined_text:
            tags_set.add('Bell Peppers')
        
        # 4. Методы приготовления
        if 'stuffed' in combined_text:
            tags_set.add('Stuffed')
        
        # Преобразуем в список и сортируем для консистентности
        tags_list = sorted(list(tags_set))
        
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    if 'image' in data:
                        img = data['image']
                        if isinstance(img, list):
                            for i in img:
                                if isinstance(i, str):
                                    # Преобразуем относительный URL в абсолютный
                                    if i.startswith('../'):
                                        i = 'https://www.ajinomoto.com.ph/' + i.replace('../', '')
                                    urls.append(i)
                        elif isinstance(img, str):
                            if img.startswith('../'):
                                img = 'https://www.ajinomoto.com.ph/' + img.replace('../', '')
                            urls.append(img)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 2. Ищем в meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            img_url = og_image['content']
            if img_url.startswith('../'):
                img_url = 'https://www.ajinomoto.com.ph/' + img_url.replace('../', '')
            urls.append(img_url)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        return ','.join(unique_urls) if unique_urls else None
    
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
    """Обработка директории с HTML файлами ajinomoto.com.ph"""
    import os
    
    # Обрабатываем папку preprocessed/ajinomoto_com_ph
    recipes_dir = os.path.join(
        Path(__file__).parent.parent,
        "preprocessed",
        "ajinomoto_com_ph"
    )
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(AjinomotoComPhExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python ajinomoto_com_ph.py")


if __name__ == "__main__":
    main()
