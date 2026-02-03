"""
Экстрактор данных рецептов для сайта tutirecept.hu
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TutireceptHuExtractor(BaseRecipeExtractor):
    """Экстрактор для tutirecept.hu"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах, например "20 minutes"
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
        
        if total_minutes > 0:
            # Форматируем в венгерский формат "20 perc" или используем английский "20 minutes"
            return f"{total_minutes} minutes"
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта с itemprop="name"
        recipe_header = self.soup.find('h1', class_='heading')
        if recipe_header:
            return self.clean_text(recipe_header.get_text())
        
        # Альтернативно - ищем просто h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " | Tutirecept"
            title = re.sub(r'\s*\|\s*Tutirecept.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в entry-description (может быть в div или p с этим классом)
        desc_elem = self.soup.find(class_='entry-description')
        if desc_elem:
            return self.clean_text(desc_elem.get_text())
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "50 dkg háztartási keksz" или "mazsola ízlés szerint"
            
        Returns:
            dict: {"name": "háztartási keksz", "amount": 50, "units": "dkg"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "50 dkg háztartási keksz", "2 dl tej", "1 csipet só"
        # Венгерские единицы измерения: dkg (dekagram), dl (deciliter), db (darab/piece), 
        # evőkanál (tablespoon), csomag (package), csipet (pinch), perc (minute)
        pattern = r'^([\d.,]+)?\s*(dkg|dl|db|g|kg|ml|l|evőkanál|teáskanál|csomag|csipet|perc|minutes?)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, units, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip().replace(',', '.')
            try:
                # Пытаемся конвертировать в число
                amount_float = float(amount_str)
                # Если целое число, возвращаем int
                if amount_float.is_integer():
                    amount = int(amount_float)
                else:
                    amount = amount_str  # Оставляем строкой для дробных
            except ValueError:
                amount = amount_str  # Оставляем строкой если не удалось конвертировать
        
        # Обработка единицы измерения
        units = units.strip() if units else None
        
        # Очистка названия
        name = name.strip()
        
        # Удаляем фразы "ízlés szerint" (to taste), "kb." (approximately), etc
        name = re.sub(r'\b(ízlés szerint|kb\.?|körülbelül|opcionális)\b', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем список ингредиентов через класс ingredients-list
        ingredients_list = self.soup.find('div', class_='ingredients-list')
        
        if ingredients_list:
            # Извлекаем элементы списка с классом ingredient-item
            items = ingredients_list.find_all(class_='ingredient-item')
            
            for item in items:
                # Извлекаем текст ингредиента
                ingredient_text = item.get_text(separator=' ', strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                if ingredient_text:
                    # Парсим в структурированный формат
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        # Если не нашли через класс, пробуем через itemprop
        if not ingredients:
            items = self.soup.find_all(itemprop='recipeIngredient')
            for item in items:
                ingredient_text = item.get_text(separator=' ', strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                if ingredient_text:
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем инструкции через класс dl-horizontal с itemprop="recipeInstructions"
        instructions_dl = self.soup.find('dl', class_='dl-horizontal')
        
        if instructions_dl:
            # Извлекаем все dd элементы (шаги)
            step_items = instructions_dl.find_all('dd')
            
            for item in step_items:
                # Извлекаем текст инструкции
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    steps.append(step_text)
        
        # Если не нашли через класс, пробуем через itemprop
        if not steps:
            instructions_elem = self.soup.find(itemprop='recipeInstructions')
            if instructions_elem:
                # Пробуем найти dd или p элементы внутри
                step_items = instructions_elem.find_all(['dd', 'p', 'li'])
                for item in step_items:
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    if step_text:
                        steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в meta-картах с классом recipe-meta-card
        # Сначала ищем "Fogás" (тип блюда/course)
        meta_cards = self.soup.find_all('div', class_='recipe-meta-card')
        
        for card in meta_cards:
            label = card.find(class_='meta-label')
            if label and 'fogás' in label.get_text().lower():
                value = card.find(class_='meta-value')
                if value:
                    # Извлекаем текст из ссылки или напрямую
                    link = value.find('a')
                    if link:
                        return self.clean_text(link.get_text())
                    return self.clean_text(value.get_text())
        
        # Если нет Fogás, ищем Főkategória (main category)
        for card in meta_cards:
            label = card.find(class_='meta-label')
            if label and 'kategória' in label.get_text().lower():
                value = card.find(class_='meta-value')
                if value:
                    # Извлекаем текст из ссылки или напрямую
                    link = value.find('a')
                    if link:
                        return self.clean_text(link.get_text())
                    return self.clean_text(value.get_text())
        
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prepTime', 'cookTime', 'totalTime')
        """
        # Ищем элемент time с соответствующим itemprop
        time_elem = self.soup.find('time', itemprop=time_type)
        
        if time_elem and time_elem.get('datetime'):
            iso_time = time_elem['datetime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prepTime')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('cookTime')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('totalTime')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями/советами
        notes_section = self.soup.find(class_=re.compile(r'note', re.I))
        
        if notes_section:
            text = notes_section.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Ищем теги в meta-картах
        meta_cards = self.soup.find_all('div', class_='recipe-meta-card')
        
        for card in meta_cards:
            label = card.find(class_='meta-label')
            if label and 'cím' in label.get_text().lower():  # "címke" = tag in Hungarian
                value = card.find(class_='meta-value')
                if value:
                    # Извлекаем все ссылки (теги)
                    links = value.find_all('a')
                    for link in links:
                        tag = self.clean_text(link.get_text())
                        if tag:
                            tags_list.append(tag.lower())
        
        # Также ищем в meta keywords
        if not tags_list:
            meta_keywords = self.soup.find('meta', {'name': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                keywords = meta_keywords['content']
                tags_list = [tag.strip().lower() for tag in keywords.split(',') if tag.strip()]
        
        # Возвращаем как строку через запятую
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем главное изображение с классом main-image
        main_img = self.soup.find('img', class_='main-image')
        if main_img and main_img.get('src'):
            urls.append(main_img['src'])
        
        # 2. Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 3. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Если data - это словарь с @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if isinstance(item, dict) and item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
            
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
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/tutirecept_hu
    project_root = Path(__file__).parent.parent
    recipes_dir = project_root / "preprocessed" / "tutirecept_hu"
    
    if recipes_dir.exists() and recipes_dir.is_dir():
        process_directory(TutireceptHuExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python tutirecept_hu.py")


if __name__ == "__main__":
    main()
