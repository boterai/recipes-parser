"""
Экстрактор данных рецептов для сайта alexanderlagarmat.se
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class AlexanderLagarmatExtractor(BaseRecipeExtractor):
    """Экстрактор для alexanderlagarmat.se"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Данные могут быть списком или словарем
                if isinstance(data, list):
                    # Ищем Recipe в списке
                    for item in data:
                        if isinstance(item, dict):
                            item_type = item.get('@type', '')
                            if isinstance(item_type, list) and 'Recipe' in item_type:
                                return item
                            elif item_type == 'Recipe':
                                return item
                elif isinstance(data, dict):
                    item_type = data.get('@type', '')
                    if isinstance(item_type, list) and 'Recipe' in item_type:
                        return data
                    elif item_type == 'Recipe':
                        return data
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "20 minuter" или "1 timme 30 minuter"
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
        
        # Форматируем результат на шведском
        parts = []
        if hours > 0:
            parts.append(f"{hours} timme" if hours == 1 else f"{hours} timmar")
        if minutes > 0:
            parts.append(f"{minutes} minuter" if minutes != 1 else f"{minutes} minut")
        
        return ' '.join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Альтернатива - из заголовка страницы
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Из meta title
        title = self.soup.find('title')
        if title:
            text = title.get_text()
            # Убираем суффиксы
            text = re.sub(r'\s*-.*Alexander Lagar Mat.*$', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\s+Recipe.*$', '', text, flags=re.IGNORECASE)
            return self.clean_text(text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
        # Альтернатива - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Из div.description
        desc_div = self.soup.find('div', class_='description')
        if desc_div:
            p = desc_div.find('p')
            if p:
                return self.clean_text(p.get_text())
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате списка словарей"""
        ingredients = []
        
        # Сначала пытаемся извлечь из data-атрибутов (наиболее структурированный источник)
        ingredient_list = self.soup.find('ul', class_='ingredient-list')
        if ingredient_list:
            items = ingredient_list.find_all('li')
            for item in items:
                name = item.get('data-ingredient-name')
                amount = item.get('data-ingredient-amount')
                unit = item.get('data-ingredient-unit')
                
                # Если есть data-атрибуты, используем их
                if name:
                    ingredients.append({
                        "name": name,
                        "amount": amount,
                        "unit": unit
                    })
                else:
                    # Иначе парсим текст
                    ingredient_text = item.get_text(strip=True)
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        # Если не нашли через ul.ingredient-list, пробуем через JSON-LD
        if not ingredients:
            json_ld = self._get_json_ld_data()
            if json_ld and 'recipeIngredient' in json_ld:
                for ingredient_text in json_ld['recipeIngredient']:
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "100 g smör" или "2 dl grädde"
            
        Returns:
            dict: {"name": "smör", "amount": "100", "unit": "g"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Шведские единицы измерения
        pattern = r'^([\d\s/.,]+)?\s*(g|kg|ml|dl|l|msk|tsk|krm|st|klyftor?|matskedar?|teskedar?|kryddmått|liter|gram|kilo|stycken?|paket|burk(?:ar)?|skivor?|halvor?|hela?|bit(?:ar)?|huvud(?:en)?|knippe|kvist(?:ar)?)?\s*(.+)'
        
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
                amount = str(total)
            else:
                amount = amount_str.replace(',', '.')
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы типа "efter smak", "valfritt" (но НЕ "för rullning", "för servering" и т.д.)
        name = re.sub(r'\b(efter smak|valfritt|ungefär)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
        steps = []
        
        # Пробуем через JSON-LD
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        steps.append(f"{idx}. {step_text}")
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        steps.append(f"{idx}. {step_text}")
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
        
        # Если JSON-LD не помог, ищем в HTML
        if not steps:
            instructions_section = self.soup.find('section', class_='instructions')
            if instructions_section:
                step_items = instructions_section.find_all('li')
                if not step_items:
                    step_items = instructions_section.find_all('p')
                
                for idx, item in enumerate(step_items, 1):
                    step_text = self.clean_text(item.get_text(strip=True))
                    if step_text:
                        # Если уже есть номер, не добавляем
                        if re.match(r'^\d+\.', step_text):
                            steps.append(step_text)
                        else:
                            steps.append(f"{idx}. {step_text}")
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        json_ld = self._get_json_ld_data()
        
        if json_ld:
            # Пробуем recipeCategory
            if 'recipeCategory' in json_ld:
                category = json_ld['recipeCategory']
                if isinstance(category, list):
                    return ', '.join(category)
                return str(category)
            
            # Пробуем recipeCuisine
            if 'recipeCuisine' in json_ld:
                cuisine = json_ld['recipeCuisine']
                if isinstance(cuisine, list):
                    return ', '.join(cuisine)
                return str(cuisine)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        # Альтернатива - из HTML
        prep_time_elem = self.soup.find('span', class_='prep-time')
        if prep_time_elem:
            text = prep_time_elem.get_text(strip=True)
            # Убираем префикс "Förberedelse:"
            text = re.sub(r'^Förberedelse:\s*', '', text, flags=re.IGNORECASE)
            return self.clean_text(text)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        # Альтернатива - из HTML
        cook_time_elem = self.soup.find('span', class_='cook-time')
        if cook_time_elem:
            text = cook_time_elem.get_text(strip=True)
            # Убираем префикс "Tillagningstid:"
            text = re.sub(r'^Tillagningstid:\s*', '', text, flags=re.IGNORECASE)
            return self.clean_text(text)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        # Альтернатива - из HTML
        total_time_elem = self.soup.find('span', class_='total-time')
        if total_time_elem:
            text = total_time_elem.get_text(strip=True)
            # Убираем префикс "Total tid:"
            text = re.sub(r'^Total tid:\s*', '', text, flags=re.IGNORECASE)
            return self.clean_text(text)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями
        notes_section = self.soup.find('section', class_='notes')
        
        if notes_section:
            # Ищем параграф
            p = notes_section.find('p')
            if p:
                text = self.clean_text(p.get_text())
                return text if text else None
            
            # Если нет параграфа, берем весь текст и убираем заголовок
            text = notes_section.get_text(separator=' ', strip=True)
            # Убираем заголовок "Tips"
            text = re.sub(r'^Tips\s*', '', text, flags=re.IGNORECASE)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Сначала пробуем извлечь из HTML (приоритет, т.к. там может быть больше тегов)
        tags_div = self.soup.find('div', class_='recipe-tags')
        if tags_div:
            # Удаляем span элемент, если есть
            for span in tags_div.find_all('span'):
                span.decompose()
            text = tags_div.get_text(strip=True)
            tags_list = [tag.strip() for tag in text.split(',') if tag.strip()]
        
        # Если не нашли в HTML, ищем в JSON-LD
        if not tags_list:
            json_ld = self._get_json_ld_data()
            if json_ld and 'keywords' in json_ld:
                keywords = json_ld['keywords']
                if isinstance(keywords, str):
                    tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                elif isinstance(keywords, list):
                    tags_list = keywords
        
        if not tags_list:
            return None
        
        # Возвращаем как строку через запятую с пробелом
        return ', '.join(tags_list)
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем в JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        if 'url' in item:
                            urls.append(item['url'])
                        elif 'contentUrl' in item:
                            urls.append(item['contentUrl'])
        
        # Дополнительно ищем в meta тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # Ищем в article img
        article = self.soup.find('article', class_='recipe')
        if article:
            imgs = article.find_all('img')
            for img_tag in imgs:
                src = img_tag.get('src')
                if src and src not in urls:
                    urls.append(src)
        
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
            "instructions": self.extract_steps(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "alexanderlagarmat_se")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(AlexanderLagarmatExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python alexanderlagarmat_se.py")


if __name__ == "__main__":
    main()
