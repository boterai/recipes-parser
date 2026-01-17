"""
Экстрактор данных рецептов для сайта teleculinaria.pt
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TeleculinariaExtractor(BaseRecipeExtractor):
    """Экстрактор для teleculinaria.pt"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Данные могут быть в @graph
                if isinstance(data, dict) and '@graph' in data:
                    # Ищем Recipe в @graph
                    for item in data['@graph']:
                        if isinstance(item, dict):
                            item_type = item.get('@type', '')
                            if item_type == 'Recipe':
                                return item
                # Или данные могут быть списком
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            item_type = item.get('@type', '')
                            if item_type == 'Recipe':
                                return item
                # Или напрямую объект Recipe
                elif isinstance(data, dict):
                    item_type = data.get('@type', '')
                    if item_type == 'Recipe':
                        return data
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT45M" или "PT1H30M"
            
        Returns:
            Время в формате "45 minutes" или "1 hour 30 minutes"
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
        
        # Форматируем результат
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Альтернатива - из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - Teleculinária"
            title = re.sub(r'\s*[-–]\s*Teleculinária.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Или из заголовка h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
        # Альтернатива - из meta og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        # Или из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате списка словарей"""
        json_ld = self._get_json_ld_data()
        
        ingredients = []
        
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
            ingredient_text: Строка вида "1 kg  Lingueirão" или "600 g  Feijão-branco cozido"
            
        Returns:
            dict: {"name": "Lingueirão", "amount": 1, "units": "kg"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1 kg  Lingueirão", "600 g  Feijão", "2  Cenouras", "q.b.  Sal e pimenta", "2  Dentes de alho"
        pattern = r'^([\d.,/]+)?\s*(kg|g|ml|l|dl|colheres?|colher|c\.|q\.b\.|embalagem|lata|ramo|unidades?)?\.?\s+(.+)$'
        
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
            amount_str = amount_str.strip()
            # Обработка дробей и десятичных чисел
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                amount = int(total) if total.is_integer() else total
            else:
                try:
                    val = float(amount_str.replace(',', '.'))
                    amount = int(val) if val.is_integer() else val
                except:
                    amount = amount_str
        
        # Обработка единицы измерения и названия
        units = unit.strip() if unit else None
        name = name.strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            steps_texts = []
            
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        steps_texts.append(step_text)
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        steps_texts.append(step_text)
            elif isinstance(instructions, str):
                steps_texts.append(self.clean_text(instructions))
            
            # Объединяем шаги в одну строку
            return ' '.join(steps_texts) if steps_texts else None
        
        return None
    
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
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем заметки в HTML
        # На teleculinaria.pt заметки могут быть в div с классом 'notas' или похожим
        
        # Пробуем найти секцию с заметками
        notes_section = self.soup.find('div', class_=re.compile(r'nota', re.I))
        if notes_section:
            # Ищем текст внутри wprm-recipe-notes
            notes_container = notes_section.find('div', class_='wprm-recipe-notes')
            if notes_container:
                # Извлекаем весь текст, включая содержимое тегов
                text = notes_container.get_text(separator=' ', strip=True)
                return self.clean_text(text) if text else None
        
        # Альтернативный поиск - ищем блок с классом 'wprm-recipe-notes'
        notes_container = self.soup.find('div', class_='wprm-recipe-notes')
        if notes_container:
            text = notes_container.get_text(separator=' ', strip=True)
            return self.clean_text(text) if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if isinstance(keywords, str):
                # Теги уже в формате строки с разделителями
                # Нормализуем: приводим к нижнему регистру и удаляем лишние пробелы
                tags = [tag.strip().lower() for tag in keywords.split(',') if tag.strip()]
                return ', '.join(tags) if tags else None
            elif isinstance(keywords, list):
                tags = [tag.lower() for tag in keywords]
                return ', '.join(tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
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
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            # Возвращаем как строку через запятую без пробелов (как в требованиях)
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
    preprocessed_dir = os.path.join("preprocessed", "teleculinaria_pt")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(TeleculinariaExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python teleculinaria_pt.py")


if __name__ == "__main__":
    main()
