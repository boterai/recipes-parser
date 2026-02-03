"""
Экстрактор данных рецептов для сайта tomiz.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TomizExtractor(BaseRecipeExtractor):
    """Экстрактор для tomiz.com"""
    
    def _get_recipe_json_ld(self) -> Optional[dict]:
        """
        Извлечение данных Recipe из JSON-LD
        
        Returns:
            Словарь с данными Recipe или None
        """
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Если это список, ищем Recipe в нем
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                # Если напрямую Recipe
                elif isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах с текстом, например "90 minutes", или None если 0
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
        
        # Возвращаем None если время = 0
        return f"{total_minutes} minutes" if total_minutes > 0 else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " | レシピ | 富澤商店"
            title = re.sub(r'\s*\|.*$', '', title)
            return self.clean_text(title)
        
        # Из title
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            title = re.sub(r'\s*\|.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            # Убираем HTML теги (включая <br> и &lt;br&gt;)
            desc = re.sub(r'&lt;br\s*/?\&gt;', '', desc)  # Убираем HTML-encoded <br>
            desc = re.sub(r'<br\s*/?>', '', desc)          # Убираем обычные <br>
            desc = re.sub(r'<[^>]+>', '', desc)            # Затем остальные теги
            return self.clean_text(desc)
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Dict[str, any]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "春よ恋 100% 200g" или "水 140g"
            
        Returns:
            dict: {"name": "春よ恋", "amount": 200, "units": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст (убираем лишние пробелы вокруг зенкаку пробелов)
        text = self.clean_text(ingredient_text)
        # Заменяем полноширинные пробелы на обычные
        text = text.replace('　', ' ')
        
        # Паттерн для извлечения количества и единицы в конце строки
        # Примеры: "春よ恋 100% 200g", "水 140g", "小さじ1"
        # Сначала пробуем самый распространенный случай: название + число + единица
        pattern = r'^(.+?)\s+(\d+(?:\.\d+)?)\s*([a-zA-Zа-яА-Яぁ-んァ-ヶ㏄]+)$'
        match = re.match(pattern, text)
        
        if match:
            name, amount, unit = match.groups()
            # Убираем процент из имени если он там есть (например "100%")
            name = re.sub(r'\s+\d+%$', '', name.strip())
            return {
                "name": name,
                "amount": float(amount) if '.' in amount else int(amount),
                "units": unit
            }
        
        # Паттерн для случаев с единицами без количества (например "適量")
        pattern2 = r'^(.+?)\s+(適量|少々|お好みで)$'
        match2 = re.match(pattern2, text)
        
        if match2:
            name, unit = match2.groups()
            return {
                "name": name.strip(),
                "amount": None,
                "units": unit
            }
        
        # Паттерн для японских единиц измерения с числом после них (小さじ1, 大さじ2)
        pattern3 = r'^(.+?)\s+(小さじ|大さじ|カップ|個|枚|本|袋|缶)(\d+(?:\.\d+)?)?$'
        match3 = re.match(pattern3, text)
        
        if match3:
            name, unit, amount = match3.groups()
            return {
                "name": name.strip(),
                "amount": float(amount) if amount and '.' in amount else (int(amount) if amount else None),
                "units": unit
            }
        
        # Если паттерн не совпал, возвращаем только название
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredients = []
        recipe_ingredients = recipe_data['recipeIngredient']
        
        if isinstance(recipe_ingredients, list):
            for ingredient_text in recipe_ingredients:
                if isinstance(ingredient_text, str):
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления из JSON-LD"""
        recipe_data = self._get_recipe_json_ld()
        
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        steps = []
        instructions = recipe_data['recipeInstructions']
        
        if isinstance(instructions, list):
            for idx, step in enumerate(instructions, 1):
                if isinstance(step, dict) and 'text' in step:
                    step_text = self.clean_text(step['text'])
                    steps.append(f"{idx}. {step_text}")
                elif isinstance(step, str):
                    step_text = self.clean_text(step)
                    steps.append(f"{idx}. {step_text}")
        elif isinstance(instructions, str):
            # Если это просто строка
            return self.clean_text(instructions)
        
        return '\n'.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data:
            # Проверяем keywords сначала (берем первое ключевое слово)
            if 'keywords' in recipe_data:
                keywords = recipe_data['keywords']
                if isinstance(keywords, str):
                    # Берем первое ключевое слово как категорию
                    parts = keywords.split(',')
                    if parts:
                        return self.clean_text(parts[0])
            
            # Проверяем recipeCategory
            if 'recipeCategory' in recipe_data:
                category = recipe_data['recipeCategory']
                if isinstance(category, str):
                    return self.clean_text(category)
                elif isinstance(category, list):
                    return ', '.join([self.clean_text(c) for c in category if c])
        
        # Ищем в хлебных крошках
        breadcrumb_script = self.soup.find('script', type='application/ld+json')
        if breadcrumb_script:
            try:
                data = json.loads(breadcrumb_script.string)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'BreadcrumbList':
                            items = item.get('itemListElement', [])
                            # Берем предпоследний элемент (последний - это сам рецепт)
                            if len(items) >= 2:
                                second_last = items[-2]
                                if 'item' in second_last and 'name' in second_last['item']:
                                    return self.clean_text(second_last['item']['name'])
            except (json.JSONDecodeError, KeyError, AttributeError):
                pass
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_recipe_json_ld()
        
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок (для tomiz.com обычно нет отдельных заметок)"""
        # В структуре tomiz.com нет явного поля для заметок
        # Можно попробовать найти в HTML, но обычно их нет
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Сначала пробуем из meta keywords (более подробные теги)
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            raw_tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            
            # Фильтруем теги
            for tag in raw_tags:
                # Пропускаем технические теги (коды, числа, названия компаний)
                if re.match(r'^\d+$', tag):  # Только числа
                    continue
                if '!!' in tag or '富澤商店' in tag or 'いそべさきこ' in tag:
                    continue
                if re.match(r'^\d{6,}', tag):  # Технические коды
                    continue
                
                # Извлекаем ключевые слова из составных тегов
                # Например "ヘルシーパン" -> "ヘルシー", "パン"
                if 'パン' in tag and tag != 'パン':
                    # Добавляем составной тег и части
                    parts = tag.split('パン')
                    if parts[0]:
                        tags_list.append(parts[0])
                    tags_list.append('パン')
                elif tag not in tags_list:
                    tags_list.append(tag)
        
        # Если не нашли в meta, пробуем из JSON-LD keywords
        if not tags_list:
            recipe_data = self._get_recipe_json_ld()
            if recipe_data and 'keywords' in recipe_data:
                keywords = recipe_data['keywords']
                if isinstance(keywords, str):
                    tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        # Удаляем дубликаты, сохраняя порядок
        if tags_list:
            seen = set()
            unique_tags = []
            for tag in tags_list:
                # Пропускаем пустые и слишком короткие теги
                if tag and len(tag) >= 2 and tag not in seen:
                    seen.add(tag)
                    unique_tags.append(tag)
            
            # Возвращаем как строку через запятую с пробелом
            return ', '.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Сначала пробуем из JSON-LD
        recipe_data = self._get_recipe_json_ld()
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
        # Также пробуем из meta og:image
        if not urls:
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
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/tomiz_com
    recipes_dir = os.path.join("preprocessed", "tomiz_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(TomizExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python tomiz_com.py")


if __name__ == "__main__":
    main()
