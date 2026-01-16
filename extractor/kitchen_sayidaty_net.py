"""
Экстрактор данных рецептов для сайта kitchen.sayidaty.net (Arabic recipes)
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KitchenSayidatyNetExtractor(BaseRecipeExtractor):
    """Экстрактор для kitchen.sayidaty.net"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах, например "90"
        """
        if not duration or not duration.startswith('PT'):
            return None
        
        duration = duration[2:]  # Убираем "PT"
        
        hours = 0
        minutes = 0
        
        # Извлекаем часы
        hour_match = re.search(r'(\d+)H', duration)
        if hour_match:
            hours = int(hour_match.group(1))
        
        # Извлекаем минуты
        min_match = re.search(r'(\d+)M', duration)
        if min_match:
            minutes = int(min_match.group(1))
        
        # Конвертируем все в минуты
        total_minutes = hours * 60 + minutes
        
        return str(total_minutes) if total_minutes > 0 else None
    
    def get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных из JSON-LD schema"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            if not script.string:
                continue
            
            try:
                # Убираем пробелы и переводы строк в начале и конце
                json_text = script.string.strip()
                
                # Заменяем HTML entities и управляющие символы
                json_text = json_text.replace('&nbsp;', ' ')
                json_text = json_text.replace('&amp;', '&')
                json_text = json_text.replace('&lt;', '<')
                json_text = json_text.replace('&gt;', '>')
                
                # Заменяем табуляцию на пробелы
                json_text = json_text.replace('\t', ' ')
                
                # Удаляем множественные пробелы
                json_text = re.sub(r'\s+', ' ', json_text)
                
                # Пытаемся очистить проблемные символы в массивах
                # Убираем лишние пробелы вокруг запятых в массивах
                json_text = re.sub(r'\s*,\s*', ',', json_text)
                json_text = re.sub(r'\[\s+', '[', json_text)
                json_text = re.sub(r'\s+\]', ']', json_text)
                
                data = json.loads(json_text)
                
                # Проверяем тип Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError) as e:
                # Пытаемся более агрессивную очистку
                try:
                    # Убираем все переносы строк и лишние пробелы
                    json_text_clean = re.sub(r'\s+', ' ', script.string.strip())
                    json_text_clean = json_text_clean.replace('&nbsp;', ' ')
                    data = json.loads(json_text_clean)
                    if isinstance(data, dict) and data.get('@type') == 'Recipe':
                        return data
                except:
                    continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем JSON-LD
        json_data = self.get_json_ld_data()
        if json_data and 'name' in json_data:
            return self.clean_text(json_data['name'])
        
        # Альтернативно - из заголовка страницы
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффикс "| مطبخ سيدتي"
            title = re.sub(r'\|.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем JSON-LD
        json_data = self.get_json_ld_data()
        if json_data and 'description' in json_data:
            return self.clean_text(json_data['description'])
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Из intro-text div
        intro_text = self.soup.find('div', class_='intro-text')
        if intro_text:
            return self.clean_text(intro_text.get_text())
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем JSON-LD (самый надежный)
        json_data = self.get_json_ld_data()
        if json_data and 'recipeIngredient' in json_data:
            for ing in json_data['recipeIngredient']:
                parsed = self.parse_ingredient(ing)
                if parsed:
                    ingredients.append(parsed)
        
        # Если JSON-LD не дал результата, ищем в HTML
        if not ingredients:
            # Ищем div с классом ingredients-area
            ing_area = self.soup.find('div', class_='ingredients-area')
            if ing_area:
                # Проходим по всем элементам (могут быть группы ингредиентов)
                # Сначала проверяем ul.ing-group
                ing_groups = ing_area.find_all('ul', class_='ing-group')
                for group in ing_groups:
                    items = group.find_all('li')
                    for item in items:
                        text = self.clean_text(item.get_text())
                        parsed = self.parse_ingredient(text)
                        if parsed:
                            ingredients.append(parsed)
                
                # Теперь проверяем прямые элементы (не в группах)
                # Ищем все строки начинающиеся с "-"
                text_content = ing_area.get_text()
                lines = text_content.split('\n')
                for line in lines:
                    line = line.strip()
                    if line.startswith('-'):
                        # Убираем "-" в начале
                        line = line[1:].strip()
                        # Пропускаем заголовки (они обычно заканчиваются на ":")
                        if not line.endswith(':'):
                            parsed = self.parse_ingredient(line)
                            if parsed:
                                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Сначала пробуем JSON-LD
        json_data = self.get_json_ld_data()
        if json_data and 'recipeInstructions' in json_data:
            instructions = json_data['recipeInstructions']
            if isinstance(instructions, str):
                # Убираем HTML теги
                instructions = re.sub(r'<[^>]+>', '', instructions)
                # Убираем лишние пробелы и переводы строк
                instructions = re.sub(r'\s+', ' ', instructions).strip()
                
                # Разбиваем на предложения (арабские предложения заканчиваются на точку или علامة)
                # Арабские маркеры конца предложения: . ، ؛
                sentences = []
                
                # Разбиваем по точкам, но сохраняем точки
                parts = re.split(r'(\.)', instructions)
                current_sentence = ""
                
                for part in parts:
                    if part == '.':
                        if current_sentence:
                            current_sentence += part
                            sentences.append(current_sentence.strip())
                            current_sentence = ""
                    else:
                        current_sentence += part
                
                # Добавляем последнее предложение если есть
                if current_sentence.strip():
                    sentences.append(current_sentence.strip())
                
                # Фильтруем короткие и пустые предложения
                steps = []
                for sent in sentences:
                    sent = sent.strip()
                    # Пропускаем очень короткие (менее 10 символов)
                    if len(sent) > 10:
                        # Удаляем примечания в конце (начинаются с "تعلمي أيضاً" и т.д.)
                        if 'تعلمي أيضاً' in sent or 'يمكن' in sent[:15]:
                            continue
                        steps.append(sent)
                
                # Возвращаем в формате JSON массива
                if steps:
                    return ' '.join(steps)
                else:
                    # Если не получилось разбить, возвращаем весь текст как один шаг
                    return self.clean_text(instructions)
        
        # Альтернативно - из HTML
        # Ищем div с классом preparation-area
        prep_area = self.soup.find('div', class_='preparation-area')
        if prep_area:
            # Ищем упорядоченный список
            ol = prep_area.find('ol')
            if ol:
                steps = []
                for idx, li in enumerate(ol.find_all('li'), 1):
                    step_text = self.clean_text(li.get_text())
                    if step_text:
                        steps.append(step_text)
                
                return json.dumps(steps, ensure_ascii=False) if steps else None
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности в формате: 202 kcal; 2/11/27"""
        json_data = self.get_json_ld_data()
        if json_data and 'nutrition' in json_data:
            nutrition = json_data['nutrition']
            
            # Извлекаем калории
            if 'calories' in nutrition:
                cal_text = str(nutrition['calories'])
                # Извлекаем число (может быть '1835 cal' или '1835')
                cal_match = re.search(r'(\d+)', cal_text)
                if cal_match:
                    calories = cal_match.group(1)
                    return f"{calories} kcal"
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем JSON-LD
        json_data = self.get_json_ld_data()
        if json_data and 'recipeCategory' in json_data:
            category = json_data['recipeCategory']
            # Может быть строкой с запятыми
            if isinstance(category, str):
                # Разбиваем по запятым и берем значащие части
                parts = [p.strip() for p in category.split(',') if p.strip()]
                # Фильтруем пустые строки
                parts = [p for p in parts if p and len(p) > 1]
                if parts:
                    return ', '.join(parts)
        
        # Альтернативно - из хлебных крошек
        breadcrumbs = self.soup.find('ul', class_='breadcrumbs')
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            # Берем предпоследний элемент (обычно это категория)
            if len(links) >= 2:
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_data = self.get_json_ld_data()
        if json_data and 'prepTime' in json_data:
            return self.parse_iso_duration(json_data['prepTime'])
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # На kitchen.sayidaty.net обычно нет отдельного cookTime
        # Есть только prepTime и totalTime
        # Можем вычислить: cookTime = totalTime - prepTime
        json_data = self.get_json_ld_data()
        if json_data:
            total_time = None
            prep_time = None
            
            if 'totalTime' in json_data:
                total_time = self.parse_iso_duration(json_data['totalTime'])
            if 'prepTime' in json_data:
                prep_time = self.parse_iso_duration(json_data['prepTime'])
            
            # Вычисляем время приготовления
            if total_time and prep_time:
                try:
                    cook_minutes = int(total_time) - int(prep_time)
                    if cook_minutes > 0:
                        return str(cook_minutes)
                except (ValueError, TypeError):
                    pass
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_data = self.get_json_ld_data()
        if json_data and 'totalTime' in json_data:
            return self.parse_iso_duration(json_data['totalTime'])
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # На kitchen.sayidaty.net заметки обычно в конце инструкций
        # Например: "تعلمي أيضاً: سلطة الحمص التركية"
        prep_area = self.soup.find('div', class_='preparation-area')
        if prep_area:
            # Ищем параграфы после списка
            paragraphs = prep_area.find_all('p')
            notes = []
            for p in paragraphs:
                text = self.clean_text(p.get_text())
                # Пропускаем пустые строки
                if text and len(text) > 5:
                    notes.append(text)
            
            if notes:
                return ' '.join(notes)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Сначала пробуем извлечь из JavaScript dataLayer (самый полный источник)
        scripts = self.soup.find_all('script')
        for script in scripts:
            if not script.string:
                continue
            
            # Ищем строку с tags в dataLayer.push
            match = re.search(r"tags:\s*'?\[([^\]]+)\]'?", script.string)
            if match:
                tags_str = match.group(1)
                # Парсим JSON массив тегов
                try:
                    # Добавляем скобки обратно для парсинга
                    tags_json = '[' + tags_str + ']'
                    tags_list = json.loads(tags_json)
                    if tags_list:
                        # Очищаем каждый тег
                        cleaned_tags = [self.clean_text(tag) for tag in tags_list if tag]
                        cleaned_tags = [tag for tag in cleaned_tags if tag and len(tag) > 2]
                        if cleaned_tags:
                            return ', '.join(cleaned_tags)
                except json.JSONDecodeError:
                    pass
        
        # Альтернативно - пробуем JSON-LD
        json_data = self.get_json_ld_data()
        if json_data and 'keywords' in json_data:
            keywords = json_data['keywords']
            if isinstance(keywords, str):
                return self.clean_text(keywords)
        
        # Из meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        # Или из div с классом tags-area (HTML теги на странице)
        tags_area = self.soup.find('div', class_='tags-area')
        if tags_area:
            links = tags_area.find_all('a')
            tags = [self.clean_text(link.get_text()) for link in links]
            tags = [tag for tag in tags if tag and len(tag) > 2]
            if tags:
                return ', '.join(tags)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат (Arabic text)
        
        Args:
            ingredient_text: Строка вида " البصل الأحمرنصف حبةمفروم ناعم" или "خبز التورتيلا 8 أرغفة"
            
        Returns:
            dict: {"name": "البصل الأحمر", "amount": "نصف", "unit": "حبة"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Добавляем пробелы вокруг чисел, если их нет (для случаев вроде "الدجاج2 صدر")
        text = re.sub(r'([^\d\s])(\d)', r'\1 \2', text)  # Пробел перед числом
        text = re.sub(r'(\d)([^\d\s.,/])', r'\1 \2', text)  # Пробел после числа
        
        # Список арабских и английских единиц измерения
        units_pattern = r'(أرغفة|رغيف|كوب|أكواب|ملعقة كبيرة|ملاعق كبيرة|ملعقة صغيرة|ملاعق صغيرة|غرام|كيلوغرام|ملعقة|حبة|حبات|ضمة|قطعة|قطع|رشة|كيلو|ملل|لتر|جرام|باوند|صدر|صدور)'
        
        # Паттерн для чисел (арабские цифры и слова)
        amount_pattern = r'(\d+[\d.,/\s]*|نصف|ثلث|ربع|كامل|كاملة|واحد|واحدة|اثنان|اثنين|ثلاثة|أربعة|خمسة|ستة|سبعة|ثمانية|تسعة|عشرة)'
        
        # Стратегия: ищем количество, затем единицу, остальное - название
        
        # 1. Ищем число в начале или середине текста
        amount = None
        unit = None
        name = text
        
        # Сначала ищем единицу измерения
        unit_match = re.search(units_pattern, text)
        
        if unit_match:
            unit = unit_match.group(1)
            unit_start = unit_match.start()
            unit_end = unit_match.end()
            
            # Текст до единицы
            before_unit = text[:unit_start]
            # Текст после единицы
            after_unit = text[unit_end:]
            
            # Ищем число в тексте до единицы (с конца, чтобы найти ближайшее к единице)
            amount_match = None
            for match in re.finditer(amount_pattern, before_unit):
                amount_match = match
            
            if amount_match:
                amount = amount_match.group(1).strip()
                # Название - это текст ДО количества
                name = before_unit[:amount_match.start()].strip()
                
                # Если название пустое, возможно оно идет после числа но до единицы
                if not name:
                    between = before_unit[amount_match.end():].strip()
                    if between:
                        name = between
            else:
                # Количества нет, название - весь текст до единицы
                name = before_unit.strip()
            
            # Добавляем описание после единицы, если оно короткое и значимое
            # (избегаем добавления длинных примечаний)
            after_clean = after_unit.strip()
            # Проверяем, не является ли это примечанием (содержит "ممكن", "يمكن" и т.д.)
            is_note = any(word in after_clean for word in ['ممكن', 'يمكن', 'استبدال', 'أو'])
            if after_clean and len(after_clean) < 30 and not is_note:
                if name:
                    name = f"{name} {after_clean}"
                else:
                    name = after_clean
                    
        else:
            # Единица измерения не найдена
            # Пытаемся найти хотя бы количество
            amount_match = re.search(amount_pattern, text)
            if amount_match:
                amount = amount_match.group(1).strip()
                # Название - текст до количества
                name = text[:amount_match.start()].strip()
                if not name:
                    # Или после количества
                    name = text[amount_match.end():].strip()
        
        # Финальная очистка названия
        if name:
            # Удаляем лишние пробелы
            name = re.sub(r'\s+', ' ', name).strip()
            # Удаляем мусорные символы в начале/конце
            name = name.strip(' /-')
        
        # Если название пустое, используем весь исходный текст
        if not name:
            name = text
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Сначала пробуем JSON-LD
        json_data = self.get_json_ld_data()
        if json_data and 'image' in json_data:
            images = json_data['image']
            if isinstance(images, list):
                urls.extend(images)
            elif isinstance(images, str):
                urls.append(images)
        
        # Альтернативно - из meta og:image
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
        
        # Убираем дубликаты, берем первые 3
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
                    if len(unique_urls) >= 3:
                        break
            
            return ', '.join(unique_urls) if unique_urls else None
        
        return None
    
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта
        
        Returns:
            Словарь с данными рецепта
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name.lower() if dish_name else None,
            "description": description.lower() if description else None,
            "ingredients": ingredients,
            "instructions": instructions.lower() if instructions else None,
            "nutrition_info": self.extract_nutrition_info(),
            "category": category.lower() if category else None,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes.lower() if notes else None,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # По умолчанию обрабатываем папку parsed/kitchen_sayidaty_net/exploration
    recipes_dir = os.path.join("recipes", "kitchen_sayidaty_net")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(KitchenSayidatyNetExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python kitchen_sayidaty_net.py [путь_к_файлу_или_директории]")


if __name__ == "__main__":
    main()
