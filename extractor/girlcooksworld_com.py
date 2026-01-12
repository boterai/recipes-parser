"""
Экстрактор данных рецептов для сайта girlcooksworld.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class GirlCooksWorldExtractor(BaseRecipeExtractor):
    """Экстрактор для girlcooksworld.com"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы (Article metadata)"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Ищем в @graph структуре Article
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Article':
                            return item
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в div.recipe с классом fn (hRecipe microformat)
        recipe_div = self.soup.find('div', class_='recipe')
        if recipe_div:
            title = recipe_div.find(class_='fn')
            if title:
                return self.clean_text(title.get_text())
        
        # Альтернативно из og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Dict[str, Optional[str]]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour" или "2 pounds chicken"
            
        Returns:
            dict: {"name": "flour", "amount": "1", "units": "cup"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).strip()
        
        # Если строка пустая или слишком короткая
        if not text or len(text) < 2:
            return None
        
        # Заменяем Unicode дроби на обычные дроби
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5'
        }
        
        for fraction, replacement in fraction_map.items():
            text = text.replace(fraction, replacement)
        
        # Паттерн для извлечения количества, единицы и названия
        # Поддерживает: "1 cup flour", "2 tablespoons butter", "1/2 teaspoon salt", "1-1/2 cups water"
        # Но НЕ "1 medium onion" где medium - это размер, а не единица
        pattern = r'^([\d\s/\-.,]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|t\.|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads|stalk)\s+(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
        else:
            # Попробуем без единицы, но с размером (medium, large, small)
            # "1 medium onion" -> amount=1, unit=None, name="medium onion"
            size_pattern = r'^([\d\s/\-.,]+)?\s*(.+)'
            size_match = re.match(size_pattern, text, re.IGNORECASE)
            if size_match:
                amount_str, name = size_match.groups()
                unit = None
            else:
                # Если ничего не совпало, возвращаем только название
                return {
                    "name": text,
                    "amount": None,
                    "units": None
                }
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Нормализуем количество (убираем лишние пробелы)
            amount_str = re.sub(r'\s+', ' ', amount_str)
            amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Сначала сохраняем оригинальное имя для проверки
        original_name = name
        
        # Удаляем скобочные пояснения из начала
        name = re.sub(r'^\([^)]*\)\s*', '', name)
        
        # Удаляем описательные слова и фразы, но только если они в конце или после запятой
        # "garlic, minced" -> "garlic"
        # "Jalapeno pepper, seeded and minced" -> "Jalapeno pepper"
        name = re.sub(r',\s*\b(to taste|as needed|or more|if needed|optional|for garnish|divided|seeded and minced|seeded|minced|chopped|finely chopped|roughly chopped|bruised and woody ends trimmed|bruised|trimmed|woody ends trimmed|in their juice)\b.*$', '', name, flags=re.IGNORECASE)
        
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        # Если имя стало слишком коротким после очистки, но оригинал был длинным,
        # возможно мы удалили слишком много
        if len(name) < 3 and len(original_name) > 10:
            # Попробуем более щадящую очистку
            name = original_name
            # Удаляем только после запятой
            name = re.sub(r',.*$', '', name)
            name = name.strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем div.recipe
        recipe_div = self.soup.find('div', class_='recipe')
        if not recipe_div:
            return None
        
        # Ищем div.ingredients внутри recipe
        ingredients_div = recipe_div.find('div', class_='ingredients')
        if not ingredients_div:
            return None
        
        # Получаем все параграфы с ингредиентами
        for p in ingredients_div.find_all('p'):
            # Получаем HTML и разбиваем по <br> тегам
            html = str(p)
            # Разбиваем по <br> или <br/>
            parts = re.split(r'<br\s*/?>', html)
            
            for part in parts:
                # Удаляем HTML теги
                from bs4 import BeautifulSoup as BS
                clean = BS(part, 'lxml').get_text().strip()
                # Удаляем ведущие звездочки
                clean = re.sub(r'^\*\s*', '', clean)
                
                if clean and len(clean) > 2:
                    # Парсим в структурированный формат
                    parsed = self.parse_ingredient(clean)
                    if parsed and parsed.get('name'):
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        # Ищем div.recipe
        recipe_div = self.soup.find('div', class_='recipe')
        if not recipe_div:
            return None
        
        # Ищем div.instructions внутри recipe
        instructions_div = recipe_div.find('div', class_='instructions')
        if not instructions_div:
            return None
        
        # Получаем все параграфы с инструкциями
        instruction_paras = instructions_div.find_all('p')
        if not instruction_paras:
            return None
        
        # Соединяем все параграфы в одну строку
        instructions_text = ' '.join([
            self.clean_text(p.get_text(separator=' ', strip=True))
            for p in instruction_paras
        ])
        
        return instructions_text if instructions_text else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # girlcooksworld.com не предоставляет информацию о питательности в стандартном формате
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Пробуем извлечь из JSON-LD Article
        json_ld = self._get_json_ld_data()
        if json_ld and 'articleSection' in json_ld:
            sections = json_ld['articleSection']
            if isinstance(sections, list) and sections:
                # Предпочитаем "Main Dishes", "Dessert" и другие основные категории
                # Ищем в списке приоритетные категории
                priority_categories = ['Main Dishes', 'Dessert', 'Appetizers', 'Salad', 'Soup', 'Breakfast']
                for cat in priority_categories:
                    if cat in sections:
                        return self.clean_text(cat)
                # Если нет приоритетных, возвращаем последнюю (обычно более специфичная)
                return self.clean_text(sections[-1])
            elif isinstance(sections, str):
                return self.clean_text(sections)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в div.recipe
        recipe_div = self.soup.find('div', class_='recipe')
        if recipe_div:
            prep_time = recipe_div.find(class_='preptime')
            if prep_time:
                return self.clean_text(prep_time.get_text())
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в div.recipe (class=cooktime)
        recipe_div = self.soup.find('div', class_='recipe')
        if recipe_div:
            cook_time = recipe_div.find(class_='cooktime')
            if cook_time:
                return self.clean_text(cook_time.get_text())
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Сначала пробуем найти явно указанное общее время (class=duration)
        recipe_div = self.soup.find('div', class_='recipe')
        if recipe_div:
            duration = recipe_div.find(class_='duration')
            if duration:
                return self.clean_text(duration.get_text())
        
        # Если не найдено, пробуем вычислить из prep и cook time
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep and cook:
            # Извлекаем числа из строк
            prep_match = re.search(r'(\d+)', prep)
            cook_match = re.search(r'(\d+)', cook)
            
            if prep_match and cook_match:
                prep_mins = int(prep_match.group(1))
                cook_mins = int(cook_match.group(1))
                total_mins = prep_mins + cook_mins
                
                # Форматируем результат
                if total_mins >= 60:
                    hours = total_mins // 60
                    mins = total_mins % 60
                    if mins > 0:
                        return f"{hours} hour{'s' if hours > 1 else ''} {mins} minutes"
                    else:
                        return f"{hours} hour{'s' if hours > 1 else ''}"
                else:
                    return f"{total_mins} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем секцию с заметками после рецепта
        recipe_div = self.soup.find('div', class_='recipe')
        if recipe_div:
            # Проверяем следующий элемент после recipe div
            next_sibling = recipe_div.find_next_sibling()
            if next_sibling:
                # Ищем параграфы с заметками
                notes_text = []
                for elem in recipe_div.find_next_siblings(['p', 'div']):
                    text = self.clean_text(elem.get_text())
                    # Прекращаем, если встретили другую секцию
                    if any(keyword in text.lower() for keyword in ['share', 'print', 'pin', 'related']):
                        break
                    if text and len(text) > 10:
                        notes_text.append(text)
                        break  # Берем только первую заметку
                
                if notes_text:
                    return notes_text[0]
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Извлекаем из JSON-LD Article keywords
        json_ld = self._get_json_ld_data()
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if isinstance(keywords, list):
                # Фильтруем служебные теги
                filtered = [k.lower() for k in keywords if k.lower() not in ['done']]
                return ', '.join(filtered) if filtered else None
            elif isinstance(keywords, str):
                return keywords.lower()
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. og:image - главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. JSON-LD ImageObject
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
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
            
            # Возвращаем как строку через запятую
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
            "nutrition_info": self.extract_nutrition_info(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """
    Точка входа для обработки HTML-файлов girlcooksworld.com
    """
    import os
    
    # Ищем директорию с preprocessed данными
    preprocessed_dir = os.path.join("preprocessed", "girlcooksworld_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка файлов из директории: {preprocessed_dir}")
        process_directory(GirlCooksWorldExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python girlcooksworld_com.py")


if __name__ == "__main__":
    main()
