"""
Экстрактор данных рецептов для сайта gastronom.ru
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional
sys.path.insert(0, str(Path(__file__).parent.parent))

from extractor.base import BaseRecipeExtractor, process_directory


class GastronomRuExtractor(BaseRecipeExtractor):
    
    def extract_from_json_ld(self) -> dict:
        """Извлечение данных из JSON-LD схемы (наиболее надежный способ)"""
        # Ищем script с type="application/ld+json"
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                script_content = script.string
                if not script_content:
                    continue
                
                # На gastronom.ru может быть несколько JSON объектов склеенных вместе
                # Пробуем разделить их по закрывающей скобке + открывающей
                json_objects = []
                
                # Ищем паттерн }{ который указывает на склеенные JSON
                if '}{' in script_content:
                    # Разделяем склеенные JSON
                    parts = script_content.split('}{')
                    for i, part in enumerate(parts):
                        if i == 0:
                            json_objects.append(part + '}')
                        elif i == len(parts) - 1:
                            json_objects.append('{' + part)
                        else:
                            json_objects.append('{' + part + '}')
                else:
                    json_objects.append(script_content)
                
                # Парсим каждый JSON объект
                for json_str in json_objects:
                    try:
                        data = json.loads(json_str.strip())
                        
                        # Проверяем, это ли Recipe schema
                        if isinstance(data, dict) and data.get('@type') == 'Recipe':
                            return data
                    except json.JSONDecodeError:
                        continue
                        
            except Exception:
                continue
        
        return {}
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        json_ld = self.extract_from_json_ld()
        if json_ld.get('name'):
            return self.clean_text(json_ld['name'])
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r',\s*пошаговый рецепт.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Из JSON-LD
        json_ld = self.extract_from_json_ld()
        if json_ld.get('description'):
            return self.clean_text(json_ld['description'])
        
        # Из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Убираем шаблонные фразы
            desc = re.sub(r'\.\s*Вкусный рецепт приготовления.*$', '', desc)
            return self.clean_text(desc)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "курица гриль 1 шт." или "масло сливочное 40 г"
            
        Returns:
            dict: {"name": "курица гриль", "amount": "1", "unit": "шт."} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
        # Паттерн для извлечения названия, количества и единицы (русский формат)
        # Примеры: "курица гриль 1 шт.", "масло сливочное 40 г", "соль по вкусу"
        
        # Сначала пробуем паттерн: название + количество + единица
        pattern = r'^(.+?)\s+([\d.,]+)\s*(шт\.?|г\.?|кг\.?|мл\.?|л\.?|ст\.?\s*л\.?|ч\.?\s*л\.?|стак\.?|зубч?\.?(?:ик)?\(?а\)?|по вкусу)?$'
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            name, amount, unit = match.groups()
            
            # Очистка названия
            name = name.strip()
            
            # Обработка количества
            amount = amount.replace(',', '.') if amount else None
            
            # Обработка единицы
            unit = unit.strip() if unit else None
            
            return {
                "name": name,
                "amount": amount,
                "unit": unit
            }
        
        # Если не совпал паттерн с количеством, проверяем "по вкусу"
        if 'по вкусу' in text:
            name = re.sub(r'\s+по вкусу', '', text).strip()
            return {
                "name": name,
                "amount": None,
                "unit": "по вкусу"
            }
        
        # Иначе возвращаем только название
        return {
            "name": text,
            "amount": None,
            "unit": None
        }
    
    def extract_ingredients_names(self) -> Optional[str]:
        """Извлечение списка названий ингредиентов (без количества)"""
        # Из JSON-LD получаем массив названий ингредиентов
        json_ld = self.extract_from_json_ld()
        ingredients_list = json_ld.get('recipeIngredient', [])
        
        if ingredients_list:
            # Удаляем дубликаты, сохраняя порядок
            seen = set()
            unique_ingredients = []
            for ing in ingredients_list:
                ing_clean = self.clean_text(ing)
                if ing_clean and ing_clean not in seen:
                    ing_clean = ing_clean.lower()
                    seen.add(ing_clean)
                    unique_ingredients.append(ing_clean)
            
            if unique_ingredients:
                return ', '.join(unique_ingredients)
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в нормализованном JSON формате"""
        ingredient_items = []
        
        # Сначала пробуем извлечь из pageContext (самый надежный источник)
        scripts = self.soup.find_all('script', id='vite-plugin-ssr_pageContext')
        
        for script in scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                # Ищем ingredients в pageProps.page.content.ingredients
                if 'pageProps' in data and 'page' in data['pageProps']:
                    page = data['pageProps']['page']
                    
                    if 'content' in page and 'ingredients' in page['content']:
                        ingredients = page['content']['ingredients']
                        
                        for ing in ingredients:
                            if not isinstance(ing, dict):
                                continue
                            
                            name = ing.get('name')
                            if not name:
                                continue
                            
                            # Извлекаем количество и единицу
                            amount = ing.get('quantityInGramms') or ing.get('formattedQuantity')
                            unit = ing.get('formattedUnit')
                            
                            # Если unit пустой, пробуем извлечь из legacyQuantity
                            if not unit or unit == '':
                                legacy_qty = ing.get('legacyQuantity', '')
                                # Ищем единицу в legacyQuantity (например "1 ст.л", "по вкусу")
                                if 'по вкусу' in legacy_qty.lower():
                                    unit = 'по вкусу'
                                    amount = None
                                elif 'ст.л' in legacy_qty or 'ст. л' in legacy_qty:
                                    unit = 'ст.л.'
                                elif 'ч.л' in legacy_qty or 'ч. л' in legacy_qty:
                                    unit = 'ч.л.'
                                elif 'шт' in legacy_qty:
                                    unit = 'шт.'
                            
                            # Преобразуем количество в строку
                            if amount is not None:
                                amount = str(amount)
                            
                            ingredient_items.append({
                                "name": name.lower(),
                                "amount": amount,
                                "unit": unit if unit else None
                            })
                        
                        # Если нашли ингредиенты, возвращаем их
                        if ingredient_items:
                            return json.dumps(ingredient_items, ensure_ascii=False)
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Если не нашли в pageContext, пробуем старый метод с itemprop
        ingredients = self.soup.find_all(attrs={'itemprop': 'recipeIngredient'})
        
        if ingredients:
            for ing in ingredients:
                # Полный текст уже содержит название и количество
                text = self.clean_text(ing.get_text()).lower()
                if text:
                    # Парсим в структурированный формат
                    parsed = self.parse_ingredient(text)
                    if parsed:
                        ingredient_items.append(parsed)
        
        return json.dumps(ingredient_items, ensure_ascii=False) if ingredient_items else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Из JSON-LD
        json_ld = self.extract_from_json_ld()
        if json_ld.get('recipeInstructions'):
            instructions = json_ld['recipeInstructions']
            
            for idx, step in enumerate(instructions, 1):
                # Очищаем HTML теги если есть
                step_text = re.sub(r'<[^>]+>', '', step)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    # Добавляем нумерацию если её нет
                    if not step_text.startswith(f'Шаг {idx}'):
                        step_text = f"Шаг {idx}: {step_text}"
                    steps.append(step_text)
            
            return ' '.join(steps)
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности в формате: 99 kcal; 4/3/18"""
        # Из JSON-LD
        json_ld = self.extract_from_json_ld()
        nutrition = json_ld.get('nutrition', {})
        
        if nutrition:
            # Извлекаем калории (только число)
            calories = None
            if nutrition.get('calories'):
                cal_match = re.search(r'(\d+(?:\.\d+)?)', nutrition['calories'])
                if cal_match:
                    calories = cal_match.group(1)
            
            # Извлекаем белки/жиры/углеводы (только числа)
            protein = None
            if nutrition.get('proteinContent'):
                prot_match = re.search(r'(\d+(?:\.\d+)?)', nutrition['proteinContent'])
                if prot_match:
                    protein = prot_match.group(1)
            
            fat = None
            if nutrition.get('fatContent'):
                fat_match = re.search(r'(\d+(?:\.\d+)?)', nutrition['fatContent'])
                if fat_match:
                    fat = fat_match.group(1)
            
            carbs = None
            if nutrition.get('carbohydrateContent'):
                carbs_match = re.search(r'(\d+(?:\.\d+)?)', nutrition['carbohydrateContent'])
                if carbs_match:
                    carbs = carbs_match.group(1)
            
            # Формат: "99 kcal; 4/3/18"
            if calories and protein and fat and carbs:
                return f"{calories} kcal; {protein}/{fat}/{carbs}"
            elif calories:
                return f"{calories} kcal"
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Из JSON-LD
        json_ld = self.extract_from_json_ld()
        category = json_ld.get('recipeCategory')
        
        if category:
            # Переводим на английский для унификации
            category_map = {
                'Второе блюдо': 'Main Course',
                'Закуска': 'Appetizer',
                'Салат': 'Salad',
                'Суп': 'Soup',
                'Десерт': 'Dessert',
                'Выпечка': 'Baking',
                'Напиток': 'Beverage'
            }
            return category_map.get(category, category)
        
        return None
    
    def parse_time(self, iso_duration: str) -> Optional[str]:
        """
        Парсинг ISO 8601 duration в минуты
        
        Args:
            iso_duration: Строка вида "PT2H30M" или "PT30M"
        
        Returns:
            Строка с количеством минут: "150" для PT2H30M
        """
        if not iso_duration or iso_duration == 'PT':
            return None
        
        # Парсим ISO duration
        match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?', iso_duration)
        if not match:
            return None
        
        hours, minutes = match.groups()
        
        total_minutes = 0
        if hours:
            total_minutes += int(hours) * 60
        if minutes:
            total_minutes += int(minutes)
        
        return str(total_minutes) if total_minutes > 0 else None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self.extract_from_json_ld()
        prep_time = json_ld.get('prepTime')
        
        if prep_time:
            return self.parse_time(prep_time)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self.extract_from_json_ld()
        cook_time = json_ld.get('cookTime')
        
        if cook_time:
            return self.parse_time(cook_time)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self.extract_from_json_ld()
        total_time = json_ld.get('totalTime')
        
        if total_time:
            return self.parse_time(total_time)
        
        return None
    
    def extract_servings(self) -> Optional[str]:
        """Извлечение количества порций"""
        json_ld = self.extract_from_json_ld()
        servings = json_ld.get('recipeYield')
        
        if servings:
            return str(servings)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию "Особенности рецепта" или "Совет"
        notes_section = self.soup.find(id='advice')
        
        if notes_section:
            # Извлекаем текст
            note_text = notes_section.get_text(separator=' ', strip=True)
            note_text = self.clean_text(note_text)
            
            # Убираем заголовки секций
            note_text = re.sub(r'^(Особенности рецепта|Совет)[:.]?\s*', '', note_text, flags=re.IGNORECASE)
            
            if note_text:
                return note_text.lower()
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON структуры pageContext"""
        scripts = self.soup.find_all('script', id='vite-plugin-ssr_pageContext')
        
        for script in scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                # Ищем tags в pageProps.page
                if 'pageProps' in data and 'page' in data['pageProps']:
                    tags = data['pageProps']['page'].get('tags', [])
                    
                    if tags:
                        # Извлекаем имена тегов
                        tag_names = [tag['name'] for tag in tags if 'name' in tag]
                        return ', '.join(tag_names).lower() if tag_names else None
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        image_urls = []
        
        # 1. Из meta тега og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            image_urls.append(og_image['content'])
        
        # 2. Из JSON-LD
        json_ld = self.extract_from_json_ld()
        if json_ld.get('image'):
            img = json_ld['image']
            if isinstance(img, str):
                image_urls.append(img)
            elif isinstance(img, list):
                image_urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                if 'url' in img:
                    image_urls.append(img['url'])
                elif 'contentUrl' in img:
                    image_urls.append(img['contentUrl'])
        
        # Убираем дубликаты, сохраняя порядок
        if image_urls:
            seen = set()
            unique_urls = []
            for url in image_urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            return ', '.join(unique_urls) if unique_urls else None
        
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
        instructions = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name.lower() if dish_name else None,
            "description": description.lower() if description else None,
            "ingredients": ingredients,
            "instructions": instructions.lower() if instructions else None,
            "nutrition_info": self.extract_nutrition_info(),  # Формат: "99 kcal; 4/3/18"
            "category": category.lower() if category else None,
            "prep_time": self.extract_prep_time(),  
            "cook_time": self.extract_cook_time(), 
            "total_time": self.extract_total_time(),  
            "notes": notes,  
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    import os

    recipes_dir = os.path.join("recipes", "gastronom_ru")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(GastronomRuExtractor, str(recipes_dir))
        return

    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python gastronom_ru.py [путь_к_файлу_или_директории]")


if __name__ == "__main__":
    main()
