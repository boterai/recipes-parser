"""
Экстрактор данных рецептов для сайта martinys.dk
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MartinysDkExtractor(BaseRecipeExtractor):
    """Экстрактор для martinys.dk"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем заголовок h2 в секции title-col
        title_col = self.soup.find('div', class_='title-col')
        if title_col:
            h2 = title_col.find('h2')
            if h2:
                return self.clean_text(h2.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа "%%page%% %%sep%%"
            title = re.sub(r'%%page%%.*$', '', title)
            title = re.sub(r'\s*–\s*martinysdk\s*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в blog_short_description
        short_desc = self.soup.find('div', class_='blog_short_description')
        if short_desc:
            # Берем первый параграф
            p = short_desc.find('p')
            if p:
                return self.clean_text(p.get_text())
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Или из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient_item(self, text: str) -> Optional[Dict[str, Optional[str]]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            text: Строка вида "400 g hakket lamme- og kalvekød" или "2 spsk. olivenolie"
            
        Returns:
            dict: {"name": "...", "amount": "...", "unit": "..."}
        """
        if not text:
            return None
        
        # Чистим текст
        text = self.clean_text(text).strip()
        
        # Пропускаем пустые и очень короткие строки
        if not text or len(text) < 2:
            return None
        
        # Пропускаем заголовки разделов (например, "KØDSAUCE", "TIL SERVERING")
        if text.isupper() or text.startswith('<h'):
            return None
        
        # Паттерн для извлечения: количество, единица, название
        # Примеры: "400 g hakket kød", "2 spsk. olivenolie", "1 hokkaido græskar", "salt"
        # Важно: единица измерения должна быть либо в конце слова (с точкой), либо отдельным словом
        pattern = r'^([\d\s/.,½¼¾⅓⅔]+)?\s*(g(?:\s|$)|kg(?:\s|$)|ml(?:\s|$)|dl(?:\s|$)|l(?:\s|$)|spsk\.|tsk\.|stk\.|fed|stort?|store|bakke)?\s*(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей (заменяем перед парсингом)
            fraction_map = {
                '½': '0.5', '¼': '0.25', '¾': '0.75',
                '⅓': '0.33', '⅔': '0.67'
            }
            for fraction, decimal in fraction_map.items():
                amount_str = amount_str.replace(fraction, decimal)
            
            # Обработка дробей типа "1/2" и чисел с пробелами типа "2 0.5"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part.replace(',', '.'))
                amount = str(total)
            elif ' ' in amount_str and len(amount_str.split()) == 2:
                # Обрабатываем "2 0.5" как сумму
                parts = amount_str.split()
                try:
                    total = sum(float(p.replace(',', '.')) for p in parts)
                    amount = str(total)
                except ValueError:
                    amount = amount_str.replace(',', '.')
            else:
                amount = amount_str.replace(',', '.')
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        name = name.strip() if name else ""
        
        # Удаляем фразы в скобках
        name = re.sub(r'\([^)]*\)', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем секцию ingredients_list
        ingredients_section = self.soup.find('div', class_='ingredients_list')
        if not ingredients_section:
            return None
        
        # Ищем ul с ингредиентами
        ul = ingredients_section.find('ul')
        if ul:
            for li in ul.find_all('li', recursive=False):
                # Пропускаем элементы с заголовками (h4, h5)
                if li.find(['h4', 'h5', 'h3']):
                    continue
                
                # Пропускаем элементы со ссылками (часто это "Forslag til dip")
                if li.find('a'):
                    continue
                
                # Извлекаем текст
                ingredient_text = li.get_text(strip=True)
                
                # Парсим ингредиент
                parsed = self.parse_ingredient_item(ingredient_text)
                if parsed:
                    # Переименовываем 'unit' в 'units' для соответствия формату
                    ingredients.append({
                        "name": parsed["name"],
                        "amount": parsed["amount"],
                        "units": parsed["unit"]
                    })
        else:
            # Альтернативный формат: ингредиенты в параграфе, разделенные <br>
            # Ищем параграф с "INGREDIENSER"
            paragraphs = ingredients_section.find_all('p')
            for p in paragraphs:
                # Получаем HTML содержимое параграфа
                html_content = str(p)
                
                # Проверяем, содержит ли параграф "INGREDIENSER"
                if 'INGREDIENSER' not in html_content:
                    continue
                
                # Разбиваем по <br> тегам
                parts = html_content.split('<br/>')
                
                # Флаг, что мы в секции ингредиентов
                in_ingredients = False
                
                for part in parts:
                    # Удаляем HTML теги
                    text = re.sub(r'<[^>]+>', '', part).strip()
                    
                    # Начало секции ингредиентов
                    if 'INGREDIENSER' in text:
                        in_ingredients = True
                        continue
                    
                    # Конец секции ингредиентов (начало инструкций)
                    if in_ingredients and any(keyword in text for keyword in ['Start med', 'Tænd ovnen', 'Lav nu', 'Skræl', 'Pil og hak']):
                        break
                    
                    # Пропускаем заголовки разделов
                    if text.isupper() and len(text) < 30:
                        continue
                    
                    # Пропускаем информацию о времени и порциях
                    if 'Forberedelse' in text or 'personer' in text or 'til' in text.lower() and len(text) < 50:
                        continue
                    
                    # Парсим ингредиент, если мы в секции ингредиентов
                    if in_ingredients and text and len(text) > 2:
                        parsed = self.parse_ingredient_item(text)
                        if parsed:
                            ingredients.append({
                                "name": parsed["name"],
                                "amount": parsed["amount"],
                                "units": parsed["unit"]
                            })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions = []
        
        # Ищем секцию ingredients_list
        ingredients_section = self.soup.find('div', class_='ingredients_list')
        if not ingredients_section:
            return None
        
        # Ищем все параграфы после ul (это инструкции)
        ul = ingredients_section.find('ul')
        if ul:
            # Берем все элементы после ul
            for elem in ul.find_next_siblings(['p', 'h5']):
                if elem.name == 'h5':
                    # Пропускаем заголовки разделов
                    continue
                
                text = elem.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                
                if text and len(text) > 10:
                    instructions.append(text)
        else:
            # Альтернативный формат: инструкции в параграфе, разделенные <br>
            paragraphs = ingredients_section.find_all('p')
            for p in paragraphs:
                html_content = str(p)
                
                # Проверяем, содержит ли параграф инструкции
                if 'INGREDIENSER' not in html_content:
                    continue
                
                # Разбиваем по <br> тегам
                parts = html_content.split('<br/>')
                
                # Флаг, что мы в секции инструкций
                in_instructions = False
                
                for part in parts:
                    # Удаляем HTML теги
                    text = re.sub(r'<[^>]+>', '', part).strip()
                    
                    # Начало инструкций (после ингредиентов)
                    if any(keyword in text for keyword in ['Start med', 'Tænd ovnen', 'Lav nu', 'Skræl kartofler', 'Pil og hak']):
                        in_instructions = True
                    
                    # Пропускаем заголовки разделов (написаны большими буквами)
                    if text.isupper() and len(text) < 30:
                        continue
                    
                    # Собираем инструкции
                    if in_instructions and text and len(text) > 10:
                        # Очищаем текст
                        text = self.clean_text(text)
                        instructions.append(text)
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда"""
        # Ищем в секции ingredients_list текст с типом блюда
        ingredients_section = self.soup.find('div', class_='ingredients_list')
        if ingredients_section:
            # Ищем первый параграф, который содержит "Tilbehør til" или "Hovedret til"
            first_p = ingredients_section.find('p')
            if first_p:
                text = first_p.get_text()
                
                # Проверяем на категорию
                if 'Tilbehør' in text or 'tilbehør' in text:
                    return 'Side Dish'
                elif 'Hovedret' in text or 'hovedret' in text:
                    return 'Main Course'
                elif 'Dessert' in text or 'dessert' in text:
                    return 'Dessert'
                elif 'Morgenmad' in text or 'morgenmad' in text:
                    return 'Breakfast'
        
        return None
    
    def extract_time_info(self) -> Dict[str, Optional[str]]:
        """
        Извлечение всех данных о времени из строки вида
        "Forberedelse 5 min /I alt 35 min" или "Forberedelse 30 /I alt 1 t 10 min"
        
        Returns:
            dict с ключами prep_time, cook_time, total_time
        """
        result = {
            'prep_time': None,
            'cook_time': None,
            'total_time': None
        }
        
        # Ищем в секции ingredients_list
        ingredients_section = self.soup.find('div', class_='ingredients_list')
        if not ingredients_section:
            return result
        
        # Ищем первый параграф, который содержит "Forberedelse"
        first_p = ingredients_section.find('p')
        if not first_p:
            return result
        
        text = first_p.get_text()
        
        # Паттерн для prep time: "Forberedelse 5 min" или "Forberedelse 30"
        prep_match = re.search(r'Forberedelse\s+(\d+)(?:\s+min)?', text, re.IGNORECASE)
        if prep_match:
            prep_minutes = prep_match.group(1)
            result['prep_time'] = f"{prep_minutes} minutes"
        
        # Паттерн для total time: "I alt 35 min" или "I alt 1 t 10 min"
        # Обрабатываем формат с часами и минутами
        total_match = re.search(r'I alt\s+(\d+)\s+t\s+(\d+)\s+min', text, re.IGNORECASE)
        if total_match:
            hours = int(total_match.group(1))
            minutes = int(total_match.group(2))
            total_minutes = hours * 60 + minutes
            result['total_time'] = f"{hours} hour {minutes} minutes"
        else:
            # Обрабатываем формат только с минутами
            total_match = re.search(r'I alt\s+(\d+)(?:\s+min)?', text, re.IGNORECASE)
            if total_match:
                total_minutes_str = total_match.group(1)
                result['total_time'] = f"{total_minutes_str} minutes"
        
        # Вычисляем cook_time, если есть оба значения
        if result['prep_time'] and result['total_time']:
            try:
                # Парсим минуты из строк
                prep_min = int(re.search(r'(\d+)', result['prep_time']).group(1))
                
                # Парсим total_time
                if 'hour' in result['total_time']:
                    hour_match = re.search(r'(\d+)\s+hour\s+(\d+)', result['total_time'])
                    if hour_match:
                        total_min = int(hour_match.group(1)) * 60 + int(hour_match.group(2))
                    else:
                        total_min = int(re.search(r'(\d+)', result['total_time']).group(1)) * 60
                else:
                    total_min = int(re.search(r'(\d+)', result['total_time']).group(1))
                
                cook_min = total_min - prep_min
                if cook_min > 0:
                    result['cook_time'] = f"{cook_min} minutes"
            except (AttributeError, ValueError):
                pass
        
        return result
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем в content_text секции TIP или примечания
        content_text = self.soup.find('div', class_='content_text')
        if not content_text:
            return None
        
        # Ищем параграфы с "TIP" или em/strong комбинациями
        for p in content_text.find_all('p'):
            text = p.get_text()
            if 'TIP' in text or 'tip' in text.lower():
                # Извлекаем текст после TIP:
                text = re.sub(r'TIP\s*:?\s*', '', text, flags=re.IGNORECASE)
                text = self.clean_text(text)
                return text if text else None
        
        # Также ищем последний параграф в секции как возможные заметки
        paragraphs = content_text.find_all('p')
        if paragraphs:
            # Проверяем последние несколько параграфов
            for p in reversed(paragraphs[-3:]):
                text = self.clean_text(p.get_text())
                # Если это длинный текст с информацией о питательности или советах
                if text and 50 < len(text) < 300:
                    # Проверяем, что это не основной контент
                    if any(word in text.lower() for word in ['servere', 'passe', 'bruges', 'kan', 'godt']):
                        return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Теги можно извлечь из названия блюда и категории
        dish_name = self.extract_dish_name()
        if dish_name:
            # Извлекаем ключевые слова из названия
            words = dish_name.lower().split()
            for word in words:
                if len(word) > 3 and word not in ['med', 'til', 'fra', 'som', 'den', 'det']:
                    tags.append(word)
        
        # Добавляем категорию
        category = self.extract_category()
        if category:
            if category == 'Side Dish':
                tags.append('tilbehør')
            elif category == 'Main Course':
                tags.append('hovedret')
        
        # Удаляем дубликаты
        seen = set()
        unique_tags = []
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Главное изображение из main_image
        main_image_div = self.soup.find('div', class_='main_image')
        if main_image_div:
            img = main_image_div.find('img')
            if img and img.get('src'):
                src = img['src']
                # Убираем параметры размера и берем оригинал
                src = re.sub(r'\?v=\d+&width=\d+', '', src)
                src = re.sub(r'\?v=\d+', '', src)
                # Добавляем протокол, если его нет
                if src.startswith('//'):
                    src = 'https:' + src
                urls.append(src)
        
        # 2. Из мета-тегов
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            # Убираем параметры
            url = re.sub(r'\?v=\d+', '', url)
            if url not in urls:
                urls.append(url)
        
        # 3. Изображения из content_text (дополнительные фото в статье)
        content_text = self.soup.find('div', class_='content_text')
        if content_text:
            for img in content_text.find_all('img'):
                src = img.get('src')
                if src:
                    # Очищаем URL
                    src = re.sub(r'\?v=\d+', '', src)
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('http'):
                        pass
                    else:
                        continue
                    
                    if src not in urls:
                        urls.append(src)
        
        # Берем максимум первые 3-5 изображений
        urls = urls[:5]
        
        return ','.join(urls) if urls else None
    
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта
        
        Returns:
            Словарь с данными рецепта
        """
        # Извлекаем время
        time_info = self.extract_time_info()
        
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredients": self.extract_ingredients(),
            "instructions": self.extract_instructions(),
            "category": self.extract_category(),
            "prep_time": time_info['prep_time'],
            "cook_time": time_info['cook_time'],
            "total_time": time_info['total_time'],
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/martinys_dk
    recipes_dir = os.path.join("preprocessed", "martinys_dk")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(MartinysDkExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python martinys_dk.py")


if __name__ == "__main__":
    main()
