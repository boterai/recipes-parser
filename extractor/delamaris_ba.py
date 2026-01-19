"""
Экстрактор данных рецептов для сайта delamaris.ba
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class DelamarisbaExtractor(BaseRecipeExtractor):
    """Экстрактор для delamaris.ba"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return self.clean_text(data.get('name'))
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в ow_single_recept_opis
        desc_div = self.soup.find('div', class_='ow_single_recept_opis')
        if desc_div:
            p = desc_div.find('p')
            if p:
                return self.clean_text(p.get_text())
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient_row(self, amount_text: str, name_text: str) -> Optional[Dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            amount_text: Текст с количеством, например "700 ml" или "50 g"
            name_text: Название ингредиента
            
        Returns:
            dict: {"name": "...", "amount": ..., "units": "..."} или None
        """
        if not name_text:
            return None
        
        # Очищаем тексты
        amount_text = self.clean_text(amount_text) if amount_text else ""
        name_text = self.clean_text(name_text)
        
        # Если это заголовок раздела, пропускаем
        if name_text in ['Bešamel', 'Nadjev od tune', 'Lazanje', 'Paprike', 'Umak od rajčice']:
            return None
        
        # Парсим amount_text для извлечения количества и единицы
        amount = None
        units = None
        
        if amount_text:
            # Ищем паттерн: число + единица измерения
            # Примеры: "700 ml", "50 g", "4 x 125 g", "12 listova", "5-7"
            # Обрабатываем диапазоны типа "5-7" - берем среднее
            if '-' in amount_text and re.match(r'^\d+-\d+$', amount_text):
                parts = amount_text.split('-')
                try:
                    avg = (int(parts[0]) + int(parts[1])) / 2
                    amount = int(avg) if avg.is_integer() else avg
                except ValueError:
                    amount = amount_text
            else:
                match = re.match(r'([\d\s/.,x]+)\s*([a-zA-Zščćžđ]+)?', amount_text)
                if match:
                    amount_str = match.group(1)
                    units = match.group(2)
                    
                    # Обрабатываем количество
                    # Убираем пробелы и заменяем x на *
                    amount_str = amount_str.replace(' ', '').replace('x', '*')
                    # Если есть умножение (например "4*125"), вычисляем
                    if '*' in amount_str:
                        try:
                            parts = amount_str.split('*')
                            total = float(parts[0]) * float(parts[1])
                            amount = int(total) if total.is_integer() else total
                        except (ValueError, IndexError):
                            amount = amount_str.replace('*', ' x ')
                    else:
                        try:
                            # Пробуем преобразовать в число
                            if '.' in amount_str or ',' in amount_str:
                                amount = float(amount_str.replace(',', '.'))
                            else:
                                amount = int(amount_str)
                        except ValueError:
                            amount = amount_str
        
        return {
            "name": name_text,
            "amount": amount,
            "units": units
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из HTML структуры"""
        ingredients = []
        
        # Ищем все строки ингредиентов
        ingredient_rows = self.soup.find_all('div', class_='ow_single_recept_sestavine_seznam_vrstica')
        
        for row in ingredient_rows:
            # В каждой строке есть два параграфа: количество и название
            amount_p = row.find('p', class_='ow_single_recept_kolicina')
            name_p = row.find('p', class_='ow_single_recept_sestavina')
            
            if amount_p and name_p:
                amount_text = amount_p.get_text(strip=True)
                name_text = name_p.get_text(strip=True)
                
                # Парсим ингредиент
                parsed = self.parse_ingredient_row(amount_text, name_text)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем секцию с шагами
        postupak_div = self.soup.find('div', class_='ow_single_recept_postopek_seznam')
        
        if postupak_div:
            # Извлекаем все шаги
            step_rows = postupak_div.find_all('div', class_='ow_single_recept_postopek_seznam_vrstica')
            
            for idx, row in enumerate(step_rows, 1):
                step_p = row.find('p', class_='ow_single_recept_sestavina')
                if step_p:
                    step_text = self.clean_text(step_p.get_text())
                    if step_text:
                        # Добавляем нумерацию, если её нет
                        if not re.match(r'^\d+\.', step_text):
                            step_text = f"{idx}. {step_text}"
                        steps.append(step_text)
        
        if not steps:
            # Пробуем извлечь из JSON-LD
            json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and data.get('@type') == 'Recipe':
                        instructions = data.get('recipeInstructions', [])
                        if isinstance(instructions, list):
                            for idx, step in enumerate(instructions, 1):
                                if isinstance(step, dict) and 'text' in step:
                                    step_text = self.clean_text(step['text'])
                                    if step_text:
                                        steps.append(f"{idx}. {step_text}")
                                elif isinstance(step, str):
                                    steps.append(f"{idx}. {step}")
                        break
                except (json.JSONDecodeError, KeyError):
                    continue
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Из breadcrumbs
        breadcrumbs = self.soup.find('div', id='breadcrumbs')
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            # Берем "Recepti" как категорию, если есть
            for link in links:
                text = self.clean_text(link.get_text())
                if text and text != 'Početna stranica':
                    return text
        
        # Значение по умолчанию из примеров
        return "Main Course"
    
    def parse_time_from_text(self, time_text: str) -> Optional[str]:
        """Парсинг времени из текста вида '60 min' или '30 minutes'"""
        if not time_text:
            return None
        
        time_text = time_text.strip()
        # Ищем паттерн: число + min/minutes
        match = re.search(r'(\d+)\s*(min|minutes?)', time_text, re.IGNORECASE)
        if match:
            return f"{match.group(1)} min"
        
        return time_text
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    time_key = {
                        'prep': 'prepTime',
                        'cook': 'cookTime',
                        'total': 'totalTime'
                    }.get(time_type)
                    
                    if time_key and time_key in data:
                        iso_time = data[time_key]
                        # Конвертируем ISO duration (PT60M) в минуты
                        if iso_time and iso_time.startswith('PT'):
                            iso_time = iso_time[2:]  # Убираем "PT"
                            
                            hours = 0
                            minutes = 0
                            
                            # Извлекаем часы
                            hour_match = re.search(r'(\d+)H', iso_time)
                            if hour_match:
                                hours = int(hour_match.group(1))
                            
                            # Извлекаем минуты
                            min_match = re.search(r'(\d+)M', iso_time)
                            if min_match:
                                minutes = int(min_match.group(1))
                            
                            # Конвертируем все в минуты
                            total_minutes = hours * 60 + minutes
                            
                            if total_minutes > 0:
                                return f"{total_minutes} min"
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если это total time, ищем в секции "Vrijeme"
        if time_type == 'total':
            cas_div = self.soup.find('div', class_='ow_single_recept_cas_inner')
            if cas_div:
                p = cas_div.find('p')
                if p:
                    time_text = self.clean_text(p.get_text())
                    return self.parse_time_from_text(time_text)
        
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
        """Извлечение заметок"""
        # Примечания могут быть в конце описания или отдельно
        # Для delamaris.ba примечаний обычно нет в HTML, проверяем JSON
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Теги могут быть в meta keywords или в специальных элементах
        # Для delamaris.ba проверим meta keywords
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Форматируем как строку с разделителем ", "
            return self.clean_text(keywords)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 2. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    img = data.get('image')
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, list):
                        urls.extend([i for i in img if isinstance(i, str)])
                    elif isinstance(img, dict):
                        if 'url' in img:
                            urls.append(img['url'])
                        elif 'contentUrl' in img:
                            urls.append(img['contentUrl'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            # Возвращаем как строку через запятую без пробелов
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
    import os
    # По умолчанию обрабатываем папку preprocessed/delamaris_ba
    recipes_dir = os.path.join("preprocessed", "delamaris_ba")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(DelamarisbaExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python delamaris_ba.py")


if __name__ == "__main__":
    main()
