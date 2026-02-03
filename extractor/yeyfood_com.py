"""
Экстрактор данных рецептов для сайта yeyfood.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class YeyfoodExtractor(BaseRecipeExtractor):
    """Экстрактор для yeyfood.com"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        recipes = []
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Данные могут быть словарем
                if isinstance(data, dict):
                    item_type = data.get('@type', '')
                    if item_type == 'Recipe':
                        recipes.append(data)
                    
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and item.get('@type') == 'Recipe':
                                recipes.append(item)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Возвращаем самый полный рецепт (тот, у которого больше всего полей)
        if recipes:
            # Сортируем по количеству ключей, берем самый полный
            recipes.sort(key=lambda r: len(r.keys()), reverse=True)
            return recipes[0]
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в формате "20 minutes" или "1 hour 30 minutes"
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
            return self.clean_text(og_title['content'])
        
        # Из заголовка страницы
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Пробуем найти первый параграф в теле статьи  
        paragraphs = self.soup.find_all('p')
        for p in paragraphs:
            text = p.get_text(strip=True)
            # Ищем параграф, который начинается с названия блюда или описания
            if len(text) > 50:  # Должен быть достаточно длинным
                cleaned = self.clean_text(text)
                # Берем первые 2 предложения
                sentences = re.split(r'(?<=[.!?])\s+', cleaned)
                if len(sentences) >= 2:
                    result = ' '.join(sentences[:2])
                    # Убираем лишние точки
                    result = re.sub(r'\.+', '.', result)
                    if not result.endswith('.'):
                        result += '.'
                    return result
                elif len(sentences) == 1 and len(sentences[0]) > 50:
                    return sentences[0] if sentences[0].endswith('.') else sentences[0] + '.'
        
        # Если не нашли в параграфах, пробуем meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Если нет, пробуем JSON-LD
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'description' in json_ld:
            desc = json_ld['description']
            # Очищаем от [&hellip;] и других артефактов
            desc = re.sub(r'\[&hellip;\]', '', desc)
            desc = re.sub(r'\s+', ' ', desc).strip()
            return self.clean_text(desc)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour" или "1 (15 oz) can pumpkin puree"
            
        Returns:
            dict: {"name": "flour", "amount": "1", "units": "cup"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Пропускаем заголовки секций (например, "For the filling:")
        if text.endswith(':') or not text:
            return None
        
        # Заменяем Unicode дроби на числа с дробью
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5'
        }
        
        for fraction, replacement in fraction_map.items():
            text = text.replace(fraction, replacement)
        
        # Специальный паттерн для "1 (15 oz) can pumpkin puree"
        special_pattern = r'^([\d\s/]+)\s*\(([\d\s/]+)\s*([a-z]+)\)\s*(can|jar|bottle|package|pack)\s+(.+)$'
        special_match = re.match(special_pattern, text, re.IGNORECASE)
        
        if special_match:
            amount, size_amount, size_unit, container, name = special_match.groups()
            return {
                "name": name.strip(),
                "amount": amount.strip(),
                "units": f"{size_amount.strip()} {size_unit} {container}"
            }
        
        # Паттерн для обычных ингредиентов
        # Примеры: "1 cup flour", "2 tablespoons butter", "1/2 teaspoon salt", "3 large eggs"
        # Единица измерения опциональна
        pattern = r'^([\d\s/]+)?\s*\b(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|pinch(?:es)?|dash(?:es)?|packages?|packs?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|heads?)?\b\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества - сохраняем дроби как есть
        amount = None
        if amount_str:
            amount = amount_str.strip()
        
        # Обработка единицы измерения
        units = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем описания в конце типа ", melted", ", packed"
        name = re.sub(r',\s*(melted|packed|softened|chopped|diced|minced|grated|sliced).*$', '', name, flags=re.IGNORECASE)
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|for serving)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
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
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        # Удаляем префиксы типа "Preheat oven:" если они есть
                        step_text = re.sub(r'^[^:]+:\s*', '', step_text)
                        steps.append(step_text)
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        steps.append(step_text)
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в meta article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в JSON-LD
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
            # Попробуем преобразовать в формат из reference
            iso_time = self.parse_iso_duration(json_ld['prepTime'])
            # Проверяем, есть ли только минуты
            if iso_time:
                # Преобразуем "20 minutes" в "20 minutes"
                # Преобразуем "1 hour 30 minutes" в "1 hour 30 minutes"
                return iso_time
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'cookTime' in json_ld:
            iso_time = self.parse_iso_duration(json_ld['cookTime'])
            # Возвращаем в формате "45 minutes" или "1 hour 15 minutes"
            # Но если в reference указано "45-50 minutes", нужно проверить другие источники
            # Пока просто вернем то, что есть
            return iso_time
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'totalTime' in json_ld:
            iso_time = self.parse_iso_duration(json_ld['totalTime'])
            # Возвращаем в формате "1 hour 25 minutes"
            return iso_time
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем параграфы с <strong> тегами, которые содержат советы по приготовлению
        # Исключаем вопросы (Can I..., How long..., What can I...) и инструкции (Preheat oven:, etc.)
        paragraphs = self.soup.find_all('p')
        note_paragraphs = []
        
        # Паттерны для исключения
        exclude_patterns = [
            r'^Can\s+I\s+',
            r'^How\s+',
            r'^What\s+',
            r'^For\s+the\s+',
            r'^Preheat\s+',
            r'^Prepare\s+',
            r'^Make\s+',
            r'^Pour\s+',
            r'^Add\s+',
            r'^Bake:',
            r'^Cool:',
            r'^Assemble\s+',
            r'^This\s+pumpkin',
            r'^This\s+recipe',
            r'^I\'ve\s+made',
            r'^Before\s+you',
            r'^If\s+you\s+enjoyed'
        ]
        
        for p in paragraphs:
            strong_tag = p.find('strong')
            if strong_tag:
                text = p.get_text(strip=True)
                
                # Проверяем, не подходит ли под паттерны исключения
                should_exclude = any(re.match(pattern, text, re.IGNORECASE) for pattern in exclude_patterns)
                
                if not should_exclude and len(text) > 30:
                    # Убираем префикс с <strong> (например "Don't overbake:")
                    text = re.sub(r'^[^:]+:\s*', '', text)
                    cleaned_text = self.clean_text(text)
                    
                    # Берем только первое предложение из каждого параграфа
                    sentences = re.split(r'(?<=[.!?])\s+', cleaned_text)
                    if sentences and len(sentences[0]) > 20:
                        note_paragraphs.append(sentences[0])
        
        # Возвращаем первые 2-3 параграфа с заметками (по одному предложению каждый)
        if note_paragraphs:
            return ' '.join(note_paragraphs[:3])
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из meta article:tag"""
        tags_list = []
        
        # Ищем все meta теги с article:tag
        tag_metas = self.soup.find_all('meta', property='article:tag')
        for meta in tag_metas:
            if meta.get('content'):
                tag = meta['content'].strip()
                if tag:
                    tags_list.append(tag)
        
        if tags_list:
            return ', '.join(tags_list)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем в JSON-LD
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        if 'url' in item:
                            urls.append(item['url'])
                        elif 'contentUrl' in item:
                            urls.append(item['contentUrl'])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
        # Дополнительно ищем в meta og:image
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
    preprocessed_dir = os.path.join("preprocessed", "yeyfood_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(YeyfoodExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python yeyfood_com.py")


if __name__ == "__main__":
    main()
