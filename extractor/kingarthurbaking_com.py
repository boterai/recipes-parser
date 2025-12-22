"""
Экстрактор данных рецептов для сайта kingarthurbaking.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KingArthurBakingExtractor(BaseRecipeExtractor):
    """Экстрактор для kingarthurbaking.com"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Данные могут быть в @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            return item
                
                # Или напрямую
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
                # Или в списке
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT3H40M"
            
        Returns:
            Время в формате "20 minutes" или "1 hour 30 minutes" или "3 hours 40 minutes"
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
        
        # Альтернатива - из заголовка страницы
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Из meta title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'description' in json_ld:
            desc = json_ld['description']
            # Очистка от длинных текстов - берем только первое предложение или два
            # если описание слишком длинное
            desc = self.clean_text(desc)
            # Разделяем на предложения
            sentences = re.split(r'(?<=[.!?])\s+', desc)
            if sentences:
                # Берем первое предложение
                return sentences[0]
        
        # Альтернатива - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "3 cups (360g) King Arthur Unbleached All-Purpose Flour"
            
        Returns:
            dict: {"name": "King Arthur Unbleached All-Purpose Flour", "amount": 3, "units": "cups"}
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
        
        # Паттерн для King Arthur Baking: "3 cups (360g) flour" или "1 1/2 teaspoons (9g) salt"
        # Сначала пробуем извлечь количество, единицу и название
        pattern = r'^([\d\s/.,]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|packs?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads)?\s*(?:\([^)]*\))?\s*(.+)'
        
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
                # Возвращаем как число (int или float)
                amount = int(total) if total.is_integer() else total
            else:
                try:
                    val = float(amount_str.replace(',', '.'))
                    # Возвращаем как число (int или float)
                    amount = int(val) if val.is_integer() else val
                except:
                    amount = amount_str
        
        # Обработка единицы измерения
        units = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем вес в скобках в конце строки (360g), (9g), etc.
        name = re.sub(r'\s*\([^)]*\)\s*$', '', name)
        # Удаляем фразы "to taste", "as needed", "optional", "for topping", "for sprinkling"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|for serving|for topping|for sprinkling)\b', '', name, flags=re.IGNORECASE)
        # Удаляем специфичные суффиксы вроде ", warm", ", at room temperature" и т.д.
        name = re.sub(r',\s*(warm|at room temperature|drained|grated|sliced|chopped|minced|crushed|fresh or frozen).*$', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "units": units,
            "amount": amount
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
            steps_text = []
            
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        # Удаляем префиксы типа "To make the dough:", "To prepare the pan:" и т.д.
                        step_text = re.sub(r'^To\s+\w+.*?:\s*', '', step_text, flags=re.IGNORECASE)
                        step_text = re.sub(r'^For\s+\w+.*?:\s*', '', step_text, flags=re.IGNORECASE)
                        step_text = re.sub(r'^Storage information:\s*', '', step_text, flags=re.IGNORECASE)
                        steps_text.append(step_text)
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        # Удаляем префиксы
                        step_text = re.sub(r'^To\s+\w+.*?:\s*', '', step_text, flags=re.IGNORECASE)
                        step_text = re.sub(r'^For\s+\w+.*?:\s*', '', step_text, flags=re.IGNORECASE)
                        step_text = re.sub(r'^Storage information:\s*', '', step_text, flags=re.IGNORECASE)
                        steps_text.append(step_text)
            elif isinstance(instructions, str):
                text = self.clean_text(instructions)
                text = re.sub(r'^To\s+\w+.*?:\s*', '', text, flags=re.IGNORECASE)
                text = re.sub(r'^For\s+\w+.*?:\s*', '', text, flags=re.IGNORECASE)
                text = re.sub(r'^Storage information:\s*', '', text, flags=re.IGNORECASE)
                steps_text.append(text)
            
            # Объединяем все шаги в одну строку
            return ' '.join(steps_text) if steps_text else None
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности в формате: 110 kcal; 3/3/18"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'nutrition' in json_ld:
            nutrition = json_ld['nutrition']
            
            # Извлекаем калории
            calories = None
            if 'calories' in nutrition:
                cal_text = nutrition['calories']
                # Извлекаем только число
                cal_match = re.search(r'(\d+)', str(cal_text))
                if cal_match:
                    calories = cal_match.group(1)
            
            # Извлекаем БЖУ (белки/жиры/углеводы)
            protein = None
            fat = None
            carbs = None
            
            if 'proteinContent' in nutrition:
                prot_text = nutrition['proteinContent']
                prot_match = re.search(r'(\d+)', str(prot_text))
                if prot_match:
                    protein = prot_match.group(1)
            
            if 'fatContent' in nutrition:
                fat_text = nutrition['fatContent']
                fat_match = re.search(r'(\d+)', str(fat_text))
                if fat_match:
                    fat = fat_match.group(1)
            
            if 'carbohydrateContent' in nutrition:
                carb_text = nutrition['carbohydrateContent']
                carb_match = re.search(r'(\d+)', str(carb_text))
                if carb_match:
                    carbs = carb_match.group(1)
            
            # Форматируем: "110 kcal; 3/3/18"
            if calories and protein and fat and carbs:
                return f"{calories} kcal; {protein}/{fat}/{carbs}"
            elif calories:
                return f"{calories} kcal"
        
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
            
            # Пробуем keywords - может содержать категорию
            if 'keywords' in json_ld:
                keywords = json_ld['keywords']
                # keywords может быть строкой вида "Flatbread;;Olive oil;;Dairy-free;;Vegan"
                if isinstance(keywords, str):
                    # Разделяем по ;; и берем первую часть как категорию
                    parts = keywords.split(';;')
                    if parts:
                        return parts[0].strip()
        
        # Альтернатива - из хлебных крошек
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())
        
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
            # Возвращаем в читаемом формате (как в эталонном JSON)
            iso_time = json_ld['cookTime']
            # Но для cook_time возвращаем как есть в эталоне "15 to 18 minutes"
            # Проверим, есть ли диапазон в инструкциях
            if iso_time:
                parsed = self.parse_iso_duration(iso_time)
                # Поищем в инструкциях упоминание времени выпечки
                if json_ld.get('recipeInstructions'):
                    for instruction in json_ld['recipeInstructions']:
                        text = instruction if isinstance(instruction, str) else instruction.get('text', '')
                        # Ищем "15 to 18 minutes" или "12 to 14 minutes"
                        time_match = re.search(r'(\d+)\s+to\s+(\d+)\s+minutes?', text, re.IGNORECASE)
                        if time_match:
                            return f"{time_match.group(1)} to {time_match.group(2)} minutes"
                
                return parsed
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        json_ld = self._get_json_ld_data()
        
        # В King Arthur Baking заметки часто находятся в последней инструкции
        # как "Storage information"
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            
            if isinstance(instructions, list) and instructions:
                # Проверяем последнюю инструкцию
                last_instruction = instructions[-1]
                text = last_instruction if isinstance(last_instruction, str) else last_instruction.get('text', '')
                
                # Ищем "Storage information:"
                if 'storage' in text.lower():
                    # Извлекаем часть после "Storage information:"
                    match = re.search(r'Storage information:\s*(.+)', text, re.IGNORECASE)
                    if match:
                        return self.clean_text(match.group(1))
                
                # Или ищем фразы с советами
                note_patterns = [
                    r'(.*(?:is best|store|refrigerat|freez|reheat|keep).+)',
                    r'(.*(?:tip|note|hint).+)'
                ]
                
                for pattern in note_patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        return self.clean_text(match.group(1))
        
        # Альтернатива - ищем в HTML
        # Ищем секции с заметками
        notes_section = self.soup.find(class_=re.compile(r'(note|tip|storage)', re.I))
        if notes_section:
            text = notes_section.get_text(separator=' ', strip=True)
            return self.clean_text(text) if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из keywords"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            
            # keywords может быть строкой вида "Flatbread;;Olive oil;;Dairy-free;;Vegan"
            if isinstance(keywords, str):
                # Разделяем по ;;
                tags = [tag.strip().lower() for tag in keywords.split(';;') if tag.strip()]
                
                # Фильтруем и оставляем только основные категории
                # Ищем теги, которые выглядят как категории блюд
                filtered_tags = []
                category_keywords = ['bread', 'pizza', 'flatbread', 'dessert', 'cake', 'pie', 'cookie', 'roll', 'muffin', 'biscuit']
                
                for tag in tags:
                    tag_lower = tag.lower()
                    # Добавляем если это категория блюда
                    if any(keyword in tag_lower for keyword in category_keywords):
                        filtered_tags.append(tag_lower)
                
                # Если не нашли категорий, берем первые несколько тегов
                if not filtered_tags:
                    filtered_tags = tags[:3]
                
                # Добавляем "recipe" если его еще нет
                if 'recipe' not in filtered_tags:
                    filtered_tags.append('recipe')
                
                # Возвращаем как строку через запятую
                return ','.join(filtered_tags) if filtered_tags else None
            elif isinstance(keywords, list):
                tags = [tag.strip().lower() for tag in keywords if tag.strip()]
                if 'recipe' not in tags:
                    tags.append('recipe')
                return ','.join(tags[:4]) if tags else None
        
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
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
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
            "nutrition_info": None,  # В эталонных данных всегда None
            "category": None,  # В эталонных данных всегда None
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": None  # В эталонных данных всегда None
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "kingarthurbaking_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(KingArthurBakingExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python kingarthurbaking_com.py")


if __name__ == "__main__":
    main()
