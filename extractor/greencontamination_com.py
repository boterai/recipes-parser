"""
Экстрактор данных рецептов для сайта greencontamination.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class GreenContaminationExtractor(BaseRecipeExtractor):
    """Экстрактор для greencontamination.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем первый H2 в article
        article = self.soup.find('article')
        if article:
            h2 = article.find('h2')
            if h2:
                dish_name = self.clean_text(h2.get_text())
                return dish_name
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s+-\s+Green Contamination.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем второй H2 в article (обычно это краткое описание)
        article = self.soup.find('article')
        if article:
            h2_tags = article.find_all('h2')
            if len(h2_tags) >= 2:
                return self.clean_text(h2_tags[1].get_text())
        
        # Альтернативно - из meta description (берём только первое предложение)
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            # Берём только до первого восклицательного знака или точки
            match = re.match(r'^([^!.]+[!.])', desc)
            if match:
                return match.group(1)
            return desc
        
        return None
    
    def parse_ingredient_line(self, line: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            line: Строка вида "200 g farina di ceci" или "2C Olio di oliva" или "1c-2c sale"
            
        Returns:
            dict: {"name": "farina di ceci", "amount": "200", "units": "g"} или None
        """
        if not line:
            return None
        
        # Чистим текст
        text = self.clean_text(line).strip()
        
        # Специальный паттерн для диапазонов с единицами "1c-2c sale"
        range_pattern = r'^(\d+)([a-zA-Z]+)-(\d+)([a-zA-Z]+)\s+(.+)$'
        range_match = re.match(range_pattern, text)
        if range_match:
            amount = int(range_match.group(1))
            unit = f"{range_match.group(2)}-{range_match.group(3)}{range_match.group(4)}"
            name = range_match.group(5).strip()
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        
        # Паттерн для "1 o 2 cipolle rosse" - количество с "o" (или)
        or_pattern = r'^(\d+)\s+o\s+(\d+)\s+(.+)$'
        or_match = re.match(or_pattern, text)
        if or_match:
            amount = int(or_match.group(1))
            unit = f"o {or_match.group(2)}"
            name = or_match.group(3).strip()
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "200 g farina", "2C Olio", "600g acqua", "2 cipolle"
        # Поддерживаем различные форматы: "200 g", "200g", "2C", "q.b."
        pattern = r'^(\d+(?:[.,]\d+)?)\s*([a-zA-Z]+\.?)?\s+(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества - конвертируем в число
            amount = None
            if amount_str:
                amount_str = amount_str.replace(',', '.')
                try:
                    # Пробуем конвертировать в int, если целое число
                    if '.' not in amount_str:
                        amount = int(amount_str)
                    else:
                        amount = float(amount_str)
                except ValueError:
                    amount = amount_str
            
            # Обработка единицы измерения
            # Если единица - это часть названия (например, "cipolle"), unit будет None
            if unit and len(unit) > 3 and unit.lower() not in ['gram', 'cucchiai', 'cucchiaio']:
                # Вероятно это часть названия
                name = unit + ' ' + name
                unit = None
            
            # Очистка названия
            name = re.sub(r'\s+', ' ', name).strip()
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        
        # Если нет числа в начале (например, "Pepe", "Basilico")
        # Проверяем, не является ли это просто названием ингредиента
        if not re.match(r'^\d', text):
            # Может быть "q.b." в середине или конце
            qb_match = re.search(r'^(.+?)\s+(q\.b\.|QB)\.?$', text, re.IGNORECASE)
            if qb_match:
                name = qb_match.group(1).strip()
                return {
                    "name": name,
                    "amount": None,
                    "units": "q.b."
                }
            
            # Может быть "(facoltativo)" в названии
            facoltativo_match = re.search(r'^(.+?)\s+\(facoltativo\)', text, re.IGNORECASE)
            if facoltativo_match:
                name = facoltativo_match.group(1).strip()
                return {
                    "name": name,
                    "amount": None,
                    "units": "(facoltativo)"
                }
            
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        article = self.soup.find('article')
        if not article:
            return None
        
        # Находим все параграфы
        paragraphs = article.find_all('p')
        
        # Ищем параграф с "INGREDIENTI"
        ingredient_start_idx = None
        for i, p in enumerate(paragraphs):
            text = p.get_text().strip()
            if re.match(r'^INGREDIENTI[:\s]', text, re.IGNORECASE):
                ingredient_start_idx = i
                break
        
        if ingredient_start_idx is None:
            return None
        
        # Извлекаем ингредиенты из следующих параграфов
        # Продолжаем пока не встретим пустой параграф, заголовок или ключевое слово
        stop_keywords = ['preparazione', 'procedimento', 'istruzioni', 'note']
        
        for i in range(ingredient_start_idx + 1, len(paragraphs)):
            p = paragraphs[i]
            text = p.get_text().strip()
            
            # Останавливаемся если:
            # - пустой параграф
            # - содержит ключевое слово остановки
            # - слишком длинный (вероятно инструкция)
            if not text:
                continue
            
            if any(keyword in text.lower() for keyword in stop_keywords):
                break
            
            if len(text) > 100:
                break
            
            # Парсим ингредиент
            parsed = self.parse_ingredient_line(text)
            if parsed and parsed['name']:
                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        article = self.soup.find('article')
        if not article:
            return None
        
        # Ищем списки (ul или ol)
        lists = article.find_all(['ul', 'ol'])
        
        # Последний список обычно содержит инструкции
        # Первый список часто содержит метаданные (автор и т.д.)
        if len(lists) >= 2:
            instructions_list = lists[-1]
        elif len(lists) == 1:
            # Проверяем, не содержит ли единственный список метаданные
            items = lists[0].find_all('li')
            if items and 'autore' not in items[0].get_text().lower():
                instructions_list = lists[0]
            else:
                return None
        else:
            return None
        
        # Извлекаем шаги
        steps = []
        items = instructions_list.find_all('li')
        
        for item in items:
            step_text = item.get_text(separator=' ', strip=True)
            step_text = self.clean_text(step_text)
            
            if step_text and len(step_text) > 10:  # Минимальная длина для инструкции
                steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем в @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'BlogPosting' and 'articleSection' in item:
                            category = self.clean_text(item['articleSection'])
                            # Заменяем ", " на " " чтобы получить "Ricette salati" вместо "Ricette, salati"
                            category = category.replace(', ', ' ')
                            return category
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_time_from_text(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени из текстовых описаний
        
        Args:
            time_type: 'prep', 'cook', или 'total'
        """
        article = self.soup.find('article')
        if not article:
            return None
        
        # Ищем в параграфах упоминания времени
        paragraphs = article.find_all('p')
        
        # Для greencontamination времена могут быть в тексте инструкций
        # Например: "almeno un' oretta" (prep time), "10-12 minuti" (cook time)
        
        if time_type == 'prep':
            # Ищем упоминания времени подготовки/отдыха
            for p in paragraphs:
                text = p.get_text().lower()
                # "almeno un' oretta" или "1 ora"
                if 'ripos' in text or 'almeno' in text:
                    # Извлекаем время
                    hour_match = re.search(r"(\d+)\s*(?:or[ae]|hour)", text, re.IGNORECASE)
                    if hour_match:
                        hours = hour_match.group(1)
                        return f"{hours} hour" if hours == "1" else f"{hours} hours"
                    
                    # "oretta" обычно означает около часа
                    if 'oretta' in text:
                        return "1 hour"
        
        elif time_type == 'cook':
            # Ищем время готовки в духовке или на плите
            # Нужно суммировать все упоминания времени готовки
            total_minutes = 0
            
            for p in paragraphs:
                text = p.get_text().lower()
                if 'forno' in text or 'cottura' in text:
                    # Извлекаем все упоминания минут
                    min_matches = re.findall(r'(\d+)(?:-(\d+))?\s*minut', text, re.IGNORECASE)
                    for match in min_matches:
                        # Если диапазон, берём максимум
                        if match[1]:
                            total_minutes += int(match[1])
                        else:
                            total_minutes += int(match[0])
            
            if total_minutes > 0:
                return f"{total_minutes} minutes"
            
            return None
        
        elif time_type == 'total':
            # Общее время = prep + cook
            prep = self.extract_time_from_text('prep')
            cook = self.extract_time_from_text('cook')
            
            if prep and cook:
                # Парсим и суммируем
                prep_hours = 0
                prep_mins = 0
                cook_hours = 0
                cook_mins = 0
                
                # Парсим prep time
                if 'hour' in prep:
                    prep_hours = int(re.search(r'(\d+)', prep).group(1))
                elif 'minute' in prep:
                    prep_mins = int(re.search(r'(\d+)', prep).group(1))
                
                # Парсим cook time
                if 'hour' in cook:
                    cook_hours = int(re.search(r'(\d+)', cook).group(1))
                elif 'minute' in cook:
                    # Может быть диапазон типа "10-12"
                    cook_match = re.search(r'(\d+)(?:-\d+)?', cook)
                    if cook_match:
                        cook_mins = int(cook_match.group(1))
                
                # Суммируем
                total_hours = prep_hours + cook_hours
                total_mins = prep_mins + cook_mins
                
                if total_mins >= 60:
                    total_hours += total_mins // 60
                    total_mins = total_mins % 60
                
                # Форматируем
                if total_hours > 0 and total_mins > 0:
                    return f"{total_hours} hour {total_mins} minutes"
                elif total_hours > 0:
                    return f"{total_hours} hour" if total_hours == 1 else f"{total_hours} hours"
                elif total_mins > 0:
                    return f"{total_mins} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time_from_text('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        return self.extract_time_from_text('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time_from_text('total')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        article = self.soup.find('article')
        if not article:
            return None
        
        # Ищем параграфы с советами по подаче или заметками
        # Обычно находятся после инструкций
        paragraphs = article.find_all('p')
        
        # Ключевые слова для заметок
        note_keywords = ['potrebbe', 'servire', 'servita', 'consiglio', 'suggerimento', 'nota']
        
        for p in paragraphs:
            text = p.get_text().strip()
            
            # Проверяем наличие ключевых слов
            if any(keyword in text.lower() for keyword in note_keywords):
                # Убедимся, что это не слишком длинный текст (вероятно инструкция)
                if len(text) < 200:
                    return self.clean_text(text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем в meta keywords или других источниках
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        # Можем извлечь из текста "vegana", "senza glutine" и т.д.
        # Или использовать слова из названия/описания
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        
        tags = []
        
        # Мапинг итальянских ключевых слов на английские для совместимости
        keyword_map = {
            'vegana': 'vegan',
            'senza glutine': 'gluten-free',
            'ricetta': 'recipe'
        }
        
        # Собираем текст для проверки
        full_text = ''
        if dish_name:
            full_text += dish_name.lower() + ' '
        if description:
            full_text += description.lower()
        
        # Проверяем наличие ключевых слов
        for italian, english in keyword_map.items():
            if italian in full_text:
                if english not in tags:
                    tags.append(english)
        
        # Добавляем специфичные слова из названия как теги
        if dish_name:
            # Извлекаем основное слово (например, "farinata", "torta")
            words = dish_name.lower().split()
            for word in words:
                # Пропускаем служебные слова
                if word not in ['di', 'con', 'e', 'la', 'il', 'le', 'i', 'vegana', 'vegano', 'vegan']:
                    if len(word) > 4 and word not in tags:
                        # Добавляем первое значимое слово как тег
                        tags.append(word)
                        break
        
        # Добавляем "recipe" в конец
        if 'recipe' not in tags:
            tags.append('recipe')
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем в @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        # Ищем image в BlogPosting или WebPage
                        if item.get('@type') in ['BlogPosting', 'WebPage'] and 'image' in item:
                            img = item['image']
                            if isinstance(img, dict) and 'url' in img:
                                urls.append(img['url'])
                            elif isinstance(img, str):
                                urls.append(img)
                
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 2. Ищем в meta тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            return ','.join(unique_urls) if unique_urls else None
        
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
        instructions = self.extract_instructions()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    """
    Точка входа для обработки HTML файлов из preprocessed/greencontamination_com
    """
    import os
    
    # Путь к директории с примерами
    preprocessed_dir = os.path.join(
        Path(__file__).parent.parent,
        "preprocessed",
        "greencontamination_com"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка файлов из: {preprocessed_dir}")
        process_directory(GreenContaminationExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python greencontamination_com.py")


if __name__ == "__main__":
    main()
