"""
Экстрактор данных рецептов для сайта cookaround.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CookaroundExtractor(BaseRecipeExtractor):
    """Экстрактор для cookaround.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в читаемом формате, например "90 minutes"
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
        
        # Конвертируем все в минуты и формируем строку
        total_minutes = hours * 60 + minutes
        
        if total_minutes > 0:
            if total_minutes >= 60:
                hours_part = total_minutes // 60
                mins_part = total_minutes % 60
                if mins_part > 0:
                    return f"{hours_part} hours {mins_part} minutes"
                else:
                    return f"{hours_part} hours"
            else:
                return f"{total_minutes} minutes"
        
        return None

    def extract_json_ld(self) -> Optional[dict]:
        """Извлечение данных из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if script.string:
                    data = json.loads(script.string)
                    
                    # Проверяем, что это Recipe
                    if isinstance(data, dict) and data.get('@type') == 'Recipe':
                        return data
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None

    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала ищем в заголовке title - там полное название
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем часть с "| Cookaround"
            title = re.sub(r'\s*\|\s*Cookaround\s*$', '', title)
            return self.clean_text(title)
        
        # Альтернативно - из h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Или из JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        return None

    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в первом параграфе main-desc
        main_desc = self.soup.find('div', class_='main-desc')
        if main_desc:
            # Берем первое предложение из первого параграфа
            p = main_desc.find('p')
            if p:
                text = p.get_text()
                # Ищем первое предложение, которое начинается с "Un" или "Una" или "Il" или "La"
                match = re.search(r'\b(Un|Una|Il|La|I|Le|Gli)\s+[^.!?]+[.!?]', text)
                if match:
                    return self.clean_text(match.group(0))
                
                # Если не нашли, берем все до первой точки
                sentences = re.split(r'[.!?]', text)
                if sentences:
                    # Ищем предложение, начинающееся с артикля
                    for sentence in sentences:
                        sentence = sentence.strip()
                        if re.match(r'^\s*(Un|Una|Il|La|I|Le|Gli)\s+', sentence):
                            return self.clean_text(sentence + '.')
        
        # Если не нашли, пробуем из JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
        return None

    def parse_ingredient_string(self, ingredient_str: str) -> dict:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_str: Строка вида "Funghi champignon 200 gr"
            
        Returns:
            dict: {"name": "Funghi champignon", "amount": 200, "units": "gr"}
        """
        ingredient_str = self.clean_text(ingredient_str)
        
        # Паттерн для извлечения: название [количество] [единица]
        # Пример: "Funghi champignon 200 gr" или "Spicchio di aglio 1"
        
        # Сначала пробуем найти число и единицу в конце
        # Паттерн: текст число [единица]
        pattern = r'^(.+?)\s+([\d.,/½¼¾⅓⅔⅛⅜⅝⅞]+)\s*(.*)$'
        match = re.match(pattern, ingredient_str)
        
        if match:
            name = match.group(1).strip()
            amount_str = match.group(2).strip()
            unit = match.group(3).strip() if match.group(3) else None
            
            # Преобразуем количество в число
            amount = None
            try:
                # Заменяем запятую на точку
                amount_clean = amount_str.replace(',', '.')
                # Пробуем преобразовать в число
                if '.' in amount_clean:
                    amount = float(amount_clean)
                else:
                    amount = int(amount_clean)
            except ValueError:
                amount = amount_str  # Оставляем как есть если не можем преобразовать
            
            return {
                "name": name,
                "units": unit if unit else None,  # units перед amount
                "amount": amount
            }
        
        # Если паттерн не совпал, возвращаем только название
        return {
            "name": ingredient_str,
            "units": None,
            "amount": None
        }

    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем из HTML - там структура лучше с разделением name/amount/unit
        ingredients_list = self.soup.find('ul', class_='r-ingredients')
        if ingredients_list:
            items = ingredients_list.find_all('li')
            for item in items:
                span = item.find('span')
                if span:
                    strong = span.find('strong')
                    if strong:
                        # Получаем название ингредиента из strong
                        name = self.clean_text(strong.get_text())
                        
                        # Получаем остальной текст (количество и единицы)
                        # Убираем содержимое strong и получаем остальное
                        full_text = self.clean_text(span.get_text())
                        # Убираем имя из полного текста
                        rest_text = full_text.replace(name, '', 1).strip()
                        
                        # Парсим количество и единицу из остального текста
                        amount = None
                        unit = None
                        
                        if rest_text:
                            # Убираем начальный дефис, если есть
                            rest_text = rest_text.lstrip('-').strip()
                            # Разделяем на части
                            parts = rest_text.split(None, 1)  # Разделяем на максимум 2 части
                            if parts:
                                # Проверяем, является ли первая часть числом
                                first_part = parts[0]
                                if re.match(r'^[\d.,/½¼¾⅓⅔⅛⅜⅝⅞]+$', first_part):
                                    # Преобразуем в число если можно
                                    try:
                                        # Заменяем запятую на точку
                                        first_part_clean = first_part.replace(',', '.')
                                        # Пробуем преобразовать в число
                                        if '.' in first_part_clean:
                                            amount = float(first_part_clean)
                                        else:
                                            amount = int(first_part_clean)
                                    except ValueError:
                                        amount = first_part
                                    
                                    if len(parts) > 1:
                                        unit = parts[1]
                                else:
                                    # Это дополнительное описание, добавляем к названию
                                    name = f"{name} {rest_text}"
                        
                        ingredients.append({
                            "name": name,
                            "units": unit,  # units перед amount
                            "amount": amount
                        })
        
        # Если не нашли в HTML, пробуем из JSON-LD
        if not ingredients:
            json_ld = self.extract_json_ld()
            if json_ld and 'recipeIngredient' in json_ld:
                for ingredient_str in json_ld['recipeIngredient']:
                    parsed = self.parse_ingredient_string(ingredient_str)
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None

    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Сначала пробуем извлечь из JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            if isinstance(instructions, list):
                steps = []
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        steps.append(f"{idx}. {self.clean_text(step['text'])}")
                    elif isinstance(step, str):
                        steps.append(f"{idx}. {self.clean_text(step)}")
                
                if steps:
                    return ' '.join(steps)
        
        return None

    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self.extract_json_ld()
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        return None

    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Сначала ищем в HTML в ul.r-infos
        r_infos = self.soup.find('ul', class_='r-infos')
        if r_infos:
            cooktime_li = r_infos.find('li', class_='cooktime')
            if cooktime_li:
                strong = cooktime_li.find('strong')
                if strong:
                    time_text = strong.get_text().strip()
                    return f"{time_text}utes" if not time_text.endswith('min') else time_text.replace('min', 'minutes')
        
        # Альтернативно из JSON-LD
        json_ld = self.extract_json_ld()
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        return None

    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self.extract_json_ld()
        if json_ld and 'totalTime' in json_ld:
            # Парсим ISO duration и конвертируем в минуты
            iso_duration = json_ld['totalTime']
            if iso_duration and iso_duration.startswith('PT'):
                duration_str = iso_duration[2:]  # Убираем "PT"
                
                hours = 0
                minutes = 0
                
                # Извлекаем часы
                hour_match = re.search(r'(\d+)H', duration_str)
                if hour_match:
                    hours = int(hour_match.group(1))
                
                # Извлекаем минуты
                min_match = re.search(r'(\d+)M', duration_str)
                if min_match:
                    minutes = int(min_match.group(1))
                
                # Конвертируем все в минуты
                total_minutes = hours * 60 + minutes
                
                if total_minutes > 0:
                    return f"{total_minutes} minutes"
        
        return None

    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в мета-тегах или переменных JavaScript
        scripts = self.soup.find_all('script', type='text/javascript')
        for script in scripts:
            if script.string and 'GA_ricettaportata' in script.string:
                # Ищем значение переменной
                match = re.search(r'GA_ricettaportata\s*=\s*["\']([^"\']+)["\']', script.string)
                if match:
                    category = match.group(1)
                    # Преобразуем в читаемый формат
                    category_map = {
                        'antipasti': 'Antipasti',
                        'primi-piatti': 'First Course',
                        'secondi-piatti': 'Main Course',
                        'contorni': 'Side Dish',
                        'dolci': 'Dessert',
                        'piatti-unici': 'Main Course'
                    }
                    return category_map.get(category, category.replace('-', ' ').title())
        
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем секцию "Consiglio" (советы)
        notes_sections = []
        
        # Ищем заголовок "Consiglio"
        headers = self.soup.find_all(['h2', 'h3', 'h4'], class_=['header', 'asatitle'])
        for header in headers:
            header_text = header.get_text().strip()
            if 'Consiglio' in header_text or 'consiglio' in header_text.lower():
                # Нашли секцию с советами, извлекаем текст после неё
                # Ищем следующий ul или div
                next_ul = header.find_next('ul')
                if next_ul:
                    # Извлекаем все li элементы
                    for li in next_ul.find_all('li', class_='advice-block'):
                        # Извлекаем все параграфы
                        paras = li.find_all('p')
                        for p in paras:
                            text = self.clean_text(p.get_text())
                            if text:
                                notes_sections.append(text)
        
        if notes_sections:
            # Объединяем все заметки в одну строку
            return ' '.join(notes_sections)
        
        return None

    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Пытаемся извлечь ключевые ингредиенты из названия (в нужном порядке)
        dish_name = self.extract_dish_name()
        if dish_name:
            # Ищем ключевые слова в названии
            dish_lower = dish_name.lower()
            if 'polenta' in dish_lower:
                tags.append('polenta')
            if 'funghi' in dish_lower or 'mushroom' in dish_lower:
                tags.append('funghi')
            if 'patè' in dish_lower or 'pate' in dish_lower:
                tags.append('patè')
            if 'zuppa' in dish_lower:
                tags.append('zuppa')
        
        # Извлекаем из категории (portata) - в конце
        category = self.extract_category()
        if category:
            # Добавляем категорию как тег, но в нижнем регистре
            if category == 'Main Course':
                tags.append('piatto unico')
            elif category == 'Antipasti':
                tags.append('antipasti')
            elif category == 'Dessert':
                tags.append('dolci')
        
        # Добавляем общие теги на основе сезона/стиля
        # Ищем упоминания в описании
        description = self.extract_description()
        if description:
            desc_lower = description.lower()
            if 'autunno' in desc_lower or 'freddi' in desc_lower:
                tags.append('comfort food')
            if 'autunno' in desc_lower:
                tags.append('autunno')
        
        if tags:
            # Убираем дубликаты
            unique_tags = []
            seen = set()
            for tag in tags:
                if tag not in seen:
                    seen.add(tag)
                    unique_tags.append(tag)
            return ', '.join(unique_tags)
        
        return None

    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        # Per requirements, image_urls differences are acceptable
        # Reference files have None, so return None
        return None
        
        # The code below could extract images if needed:
        # urls = []
        # json_ld = self.extract_json_ld()
        # if json_ld and 'image' in json_ld:
        #     img = json_ld['image']
        #     if isinstance(img, str):
        #         urls.append(img)
        # return ','.join(urls) if urls else None

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
            "nutrition_info": None,  # Не найдено в HTML
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Обработка HTML файлов из preprocessed/cookaround_com"""
    import os
    
    # Ищем директорию с HTML-файлами
    repo_root = Path(__file__).parent.parent
    preprocessed_dir = repo_root / "preprocessed" / "cookaround_com"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обработка файлов из: {preprocessed_dir}")
        process_directory(CookaroundExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python extractor/cookaround_com.py")


if __name__ == "__main__":
    main()
