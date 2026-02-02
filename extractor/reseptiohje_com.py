"""
Экстрактор данных рецептов для сайта reseptiohje.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ReseptiohjExtractor(BaseRecipeExtractor):
    """Экстрактор для reseptiohje.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в JSON-LD (самый надежный источник)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    name = data.get('name')
                    if name:
                        return self.clean_text(name)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - ищем в h1 после заголовка сайта
        h1_tags = self.soup.find_all('h1')
        for h1 in h1_tags:
            text = h1.get_text().strip()
            # Пропускаем заголовок сайта "Resepti ohje"
            if text and text != "Resepti ohje" and len(text) > 3:
                return self.clean_text(text)
        
        # Еще один вариант - из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффикс " resepti - Reseptiohje"
            title = re.sub(r'\s+resepti\s*-\s*Reseptiohje.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в основном div с рецептом
        main_div = self.soup.find('div', style=re.compile(r'line-height.*padding.*font-size'))
        
        if main_div:
            # Ищем текст между h2 и первым <br/> или <strong>
            h2 = main_div.find('h2')
            if h2:
                # Собираем текст после h2 до первого <strong> или <h4>
                description_parts = []
                for sibling in h2.next_siblings:
                    if sibling.name in ['strong', 'h4', 'h3']:
                        break
                    if isinstance(sibling, str):
                        text = sibling.strip()
                        if text and text != '<br/>' and not text.startswith('-'):
                            description_parts.append(text)
                    elif sibling.name == 'br':
                        continue
                
                if description_parts:
                    description = ' '.join(description_parts)
                    description = self.clean_text(description)
                    
                    # Эвристика: если описание короткое (под 150 символов), берем только первое предложение
                    # Иначе берем все предложения
                    if description and len(description) < 170:
                        # Берем только первое предложение
                        match = re.match(r'^([^.]+\.)', description)
                        if match:
                            return match.group(1).strip()
                    
                    return description if description else None
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем секцию с ингредиентами в основном div
        main_div = self.soup.find('div', style=re.compile(r'line-height.*padding.*font-size'))
        
        if main_div:
            # Ищем заголовок "Ainesosat:"
            h4_tags = main_div.find_all('h4')
            for h4 in h4_tags:
                if 'ainesosa' in h4.get_text().lower():
                    # Ингредиенты идут после этого заголовка до следующего h4
                    current = h4.next_sibling
                    while current:
                        if hasattr(current, 'name') and current.name == 'h4':
                            break
                        
                        if isinstance(current, str):
                            text = current.strip()
                            # Строки с ингредиентами начинаются с "-"
                            if text.startswith('-'):
                                # Убираем начальный "-" и парсим
                                ingredient_text = text[1:].strip()
                                parsed = self.parse_ingredient(ingredient_text)
                                if parsed:
                                    ingredients.append(parsed)
                        
                        current = current.next_sibling
                    
                    break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "450-550 g jauhoja" или "1 tl suolaa"
            
        Returns:
            dict: {"name": "jauhoja", "amount": "450-550", "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для финских рецептов: количество + единица + название
        # Примеры: "450-550 g jauhoja", "1 tl suolaa", "4,5 dl piimää", "n. 1 rkl voita"
        # Сначала пробуем паттерн с "n." (примерно)
        pattern_approx = r'^n\.\s*([\d\s,.\-]+)?\s*(g|kg|ml|dl|l|tl|rkl|kpl|pussi|prk|pkt)?\.?\s*(.+)'
        match = re.match(pattern_approx, text, re.IGNORECASE)
        
        if not match:
            # Стандартный паттерн
            pattern = r'^([\d\s,.\-]+)?\s*(g|kg|ml|dl|l|tl|rkl|kpl|pussi|prk|pkt)?\.?\s*(.+)'
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
            amount = amount_str.strip()
            # Заменяем запятую на точку для десятичных чисел
            amount = amount.replace(',', '.')
        
        # Обработка единицы измерения (units вместо unit по примеру)
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем текст в скобках
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы типа "sulatettuna"
        name = re.sub(r'\b(sulatettuna|kuumana|kylmänä)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit  # Используем "units" как в примере JSON
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем секцию с инструкциями в основном div
        main_div = self.soup.find('div', style=re.compile(r'line-height.*padding.*font-size'))
        
        if main_div:
            # Ищем заголовок "Ohjeet:"
            h4_tags = main_div.find_all('h4')
            for h4 in h4_tags:
                if 'ohjeet' in h4.get_text().lower() or 'ohje' in h4.get_text().lower():
                    # Инструкции идут после этого заголовка
                    current = h4.next_sibling
                    step_num = 1
                    
                    while current:
                        # Останавливаемся при встрече следующего h4
                        if hasattr(current, 'name') and current.name in ['h4', 'h3']:
                            break
                        
                        if isinstance(current, str):
                            text = current.strip()
                            # Шаги начинаются с числа и точки
                            if re.match(r'^\d+\.', text):
                                step_text = self.clean_text(text)
                                if step_text:
                                    steps.append(step_text)
                                    step_num += 1
                        
                        current = current.next_sibling
                    
                    break
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в основном div, в секции с временем приготовления
        main_div = self.soup.find('div', style=re.compile(r'line-height.*padding.*font-size'))
        
        if main_div:
            # Категория может быть в тегах (ссылки в конце)
            tags_p = main_div.find('p', class_='tags')
            if tags_p:
                links = tags_p.find_all('a')
                if links:
                    # Ищем категории типа "Leipä", "Jälkiruoka" и т.д.
                    # Фильтруем общие теги и специфичные дескрипторы
                    generic_tags = {'aamupala', 'arkiruoka', 'edulliset', 'ruoka', 'eat & go', 
                                   'nopea', 'helppo', 'quick', 'easy', 'irlantilainen', 
                                   'nopea leipä', 'rustiikkinen', 'soodaleipä', 'leivonta'}
                    
                    for link in links:
                        category = link.get_text().strip()
                        # Ищем категории, но не общие и не специфичные дескрипторы
                        if category and category.lower() not in generic_tags:
                            return self.clean_text(category)
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Ищем в основном div
        main_div = self.soup.find('div', style=re.compile(r'line-height.*padding.*font-size'))
        
        if time_type == 'cook':
            # Cook time извлекаем из инструкций
            instructions = self.extract_instructions()
            if instructions:
                # Ищем упоминания времени приготовления (обычно время в духовке/на плите)
                cook_matches = re.findall(r'(\d+(?:-\d+)?)\s*minuutt', instructions, re.IGNORECASE)
                if cook_matches:
                    # Берем последнее упоминание (обычно время выпечки/варки)
                    return f"{cook_matches[-1]} minutes"
            return None
        
        # Для prep и total используем "Valmistusaika"
        valmistusaika_minutes = None
        
        if main_div:
            # Ищем "Valmistusaika:"
            for strong_tag in main_div.find_all('strong'):
                if 'valmistusaika' in strong_tag.get_text().lower():
                    # Время идет после этого тега
                    next_text = strong_tag.next_sibling
                    if isinstance(next_text, str):
                        time_match = re.search(r'(\d+)\s*minuutt', next_text, re.IGNORECASE)
                        if time_match:
                            valmistusaika_minutes = int(time_match.group(1))
                            break
        
        if valmistusaika_minutes is None:
            return None
        
        if time_type == 'prep':
            # Логика для prep_time:
            # Если Valmistusaika значительно больше cook_time, это prep_time
            # Иначе это total_time и prep_time = None
            cook_time_str = self.extract_time('cook')
            if cook_time_str:
                # Парсим cook_time (может быть "30 minutes" или "30-35 minutes")
                cook_match = re.search(r'(\d+)(?:-(\d+))?', cook_time_str)
                if cook_match:
                    # Берем максимальное значение если диапазон
                    cook_minutes = int(cook_match.group(2) or cook_match.group(1))
                    
                    # Если Valmistusaika > cook_time + 5 минут, считаем это prep_time
                    if valmistusaika_minutes > cook_minutes + 5:
                        return f"{valmistusaika_minutes} minutes"
            
            # В остальных случаях prep_time = None
            return None
        
        elif time_type == 'total':
            # Логика для total_time:
            prep_time_str = self.extract_time('prep')
            cook_time_str = self.extract_time('cook')
            
            if prep_time_str and cook_time_str:
                # Если есть prep_time, total = prep + cook
                prep_mins = int(re.search(r'\d+', prep_time_str).group())
                cook_match = re.search(r'(\d+)(?:-(\d+))?', cook_time_str)
                if cook_match:
                    cook_mins = int(cook_match.group(2) or cook_match.group(1))
                    total = prep_mins + cook_mins
                    return f"{total} minutes"
            else:
                # Если prep_time = None, total_time = Valmistusaika
                return f"{valmistusaika_minutes} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('total')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем текст после инструкций до секции с питательностью
        main_div = self.soup.find('div', style=re.compile(r'line-height.*padding.*font-size'))
        
        if main_div:
            # Ищем заголовок "Ohjeet:" и берем текст после последнего шага
            h4_tags = main_div.find_all('h4')
            for i, h4 in enumerate(h4_tags):
                if 'ohjeet' in h4.get_text().lower():
                    # Ищем следующий h4 (обычно "Ravintosisältö")
                    if i + 1 < len(h4_tags):
                        next_h4 = h4_tags[i + 1]
                        # Текст между инструкциями и следующим заголовком
                        current = h4.next_sibling
                        notes_parts = []
                        last_step_found = False
                        
                        while current and current != next_h4:
                            if isinstance(current, str):
                                text = current.strip()
                                # Пропускаем шаги (начинаются с числа)
                                if re.match(r'^\d+\.', text):
                                    last_step_found = True
                                elif last_step_found and text and not text.startswith('<br'):
                                    # Это заметка после последнего шага
                                    notes_parts.append(text)
                            
                            current = current.next_sibling
                        
                        if notes_parts:
                            notes = ' '.join(notes_parts)
                            notes = self.clean_text(notes)
                            return notes if notes else None
                    
                    break
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Фильтруем только очень общие теги
        very_generic_tags = {'ruoka', 'eat & go'}
        
        # Ищем секцию с тегами
        main_div = self.soup.find('div', style=re.compile(r'line-height.*padding.*font-size'))
        
        if main_div:
            tags_p = main_div.find('p', class_='tags')
            if tags_p:
                links = tags_p.find_all('a')
                for link in links:
                    tag = link.get_text().strip()
                    # Фильтруем только очень общие теги
                    if tag and tag.lower() not in very_generic_tags:
                        tags_list.append(tag)
        
        # Добавляем название блюда как последний тег, но только если:
        # 1. Оно не слишком длинное (меньше 30 символов)
        # 2. Оно еще не покрыто существующими тегами
        dish_name = self.extract_dish_name()
        if dish_name and dish_name not in tags_list and len(dish_name) < 30:
            # Проверяем, не содержится ли основная часть названия уже в тегах
            dish_lower = dish_name.lower()
            already_covered = False
            for tag in tags_list:
                # Если тег содержит значительную часть названия блюда
                if len(tag) > 5 and tag.lower() in dish_lower:
                    already_covered = True
                    break
            
            if not already_covered:
                tags_list.append(dish_name)
        
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
                    img = data.get('image')
                    if img:
                        if isinstance(img, str):
                            urls.append(img)
                        elif isinstance(img, list):
                            urls.extend([i for i in img if isinstance(i, str)])
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
    import os
    # Обрабатываем папку preprocessed/reseptiohje_com
    recipes_dir = os.path.join("preprocessed", "reseptiohje_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(ReseptiohjExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python reseptiohje_com.py")


if __name__ == "__main__":
    main()
