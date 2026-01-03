"""
Экстрактор данных рецептов для сайта desidakaar.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class DesidakaarExtractor(BaseRecipeExtractor):
    """Экстрактор для desidakaar.com"""
    
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
                    # Проверяем @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict):
                                item_type = item.get('@type', '')
                                if isinstance(item_type, list) and 'Recipe' in item_type:
                                    return item
                                elif item_type == 'Recipe':
                                    return item
                    # Проверяем сам объект
                    item_type = data.get('@type', '')
                    if isinstance(item_type, list) and 'Recipe' in item_type:
                        return data
                    elif item_type == 'Recipe':
                        return data
                        
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
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
        
        # Альтернатива - из заголовка страницы
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Из meta тегов
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " Recipe", " - Site Name"
            title = re.sub(r'\s+(Recipe|desidakaar).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Из title тега
        title = self.soup.find('title')
        if title:
            text = title.get_text()
            text = re.sub(r'\s*\|.*$', '', text)
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
        
        # og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour"
            
        Returns:
            dict: {"name": "flour", "amount": "1", "unit": "cup"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅜': '0.375',
            '⅛': '0.125', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Для одно-буквенных единиц (g, l) требуем число перед ними
        pattern = r'^([\d\s/.,]+)\s+(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|packs?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads)\s+(.+)|^([\d\s/.,]+)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "unit": None
            }
        
        # Паттерн имеет две альтернативы:
        # Группа 1-3: amount + unit + name (с единицей)
        # Группа 4-5: amount + name (без единицы)
        groups = match.groups()
        if groups[0] is not None:  # Совпало первое правило (с единицей)
            amount_str, unit, name = groups[0], groups[1], groups[2]
        else:  # Совпало второе правило (без единицы)
            amount_str, unit, name = groups[3], None, groups[4]
        
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
                        try:
                            total += float(part)
                        except ValueError:
                            # Если не число, пропускаем
                            pass
                amount = str(total)
            else:
                # Обработка обычных чисел и смешанных дробей (после замены unicode)
                # Может быть "2 0.5" после замены "2 ½"
                parts = amount_str.split()
                if len(parts) > 1:
                    # Смешанное число
                    total = 0
                    for part in parts:
                        try:
                            total += float(part.replace(',', '.'))
                        except ValueError:
                            pass
                    amount = str(total) if total > 0 else amount_str
                else:
                    amount = amount_str.replace(',', '.')
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|for serving)\b', '', name, flags=re.IGNORECASE)
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
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате списка словарей"""
        json_ld = self._get_json_ld_data()
        
        ingredients = []
        
        # Попытка извлечь из JSON-LD
        if json_ld and 'recipeIngredient' in json_ld:
            for ingredient_text in json_ld['recipeIngredient']:
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        # Если JSON-LD не помог, ищем в HTML
        if not ingredients:
            # Ищем контейнер с ингредиентами по различным селекторам
            ingredient_containers = [
                self.soup.find('ul', class_=re.compile(r'ingredient', re.I)),
                self.soup.find('div', class_=re.compile(r'ingredient', re.I)),
                self.soup.find('div', attrs={'itemprop': 'recipeIngredient'}),
            ]
            
            for container in ingredient_containers:
                if not container:
                    continue
                
                # Извлекаем элементы списка
                items = container.find_all('li')
                if not items:
                    items = container.find_all('p')
                if not items:
                    # Ищем элементы с itemprop="recipeIngredient"
                    items = self.soup.find_all(attrs={'itemprop': 'recipeIngredient'})
                
                for item in items:
                    ingredient_text = item.get_text(separator=' ', strip=True)
                    ingredient_text = self.clean_text(ingredient_text)
                    
                    # Пропускаем заголовки секций
                    if ingredient_text and not ingredient_text.endswith(':'):
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
                
                if ingredients:
                    break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
        steps = []
        
        # Попытка извлечь из JSON-LD
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
            instructions_containers = [
                self.soup.find('ol', class_=re.compile(r'instruction', re.I)),
                self.soup.find('div', class_=re.compile(r'instruction', re.I)),
                self.soup.find('div', class_=re.compile(r'direction', re.I)),
            ]
            
            for container in instructions_containers:
                if not container:
                    continue
                
                # Извлекаем шаги
                step_items = container.find_all('li')
                if not step_items:
                    step_items = container.find_all('p')
                if not step_items:
                    # Ищем элементы с itemprop="recipeInstructions"
                    step_items = self.soup.find_all(attrs={'itemprop': 'recipeInstructions'})
                
                for item in step_items:
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    
                    if step_text:
                        steps.append(step_text)
                
                if steps:
                    break
        
        # Если нумерация не была в HTML, добавляем её
        if steps and not re.match(r'^\d+\.', steps[0]):
            steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
        
        return ' '.join(steps) if steps else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности в формате: 202 kcal; 2/11/27"""
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
            
            # Форматируем: "202 kcal; 2/11/27"
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
        
        # Альтернатива - из meta тегов
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Из хлебных крошек
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
        
        # Альтернатива - из HTML
        time_elem = self.soup.find(attrs={'itemprop': 'prepTime'})
        if time_elem:
            # Проверяем datetime атрибут
            if time_elem.get('datetime'):
                return self.parse_iso_duration(time_elem['datetime'])
            # Или берем текст
            return self.clean_text(time_elem.get_text())
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        # Альтернатива - из HTML
        time_elem = self.soup.find(attrs={'itemprop': 'cookTime'})
        if time_elem:
            # Проверяем datetime атрибут
            if time_elem.get('datetime'):
                return self.parse_iso_duration(time_elem['datetime'])
            # Или берем текст
            return self.clean_text(time_elem.get_text())
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        # Альтернатива - из HTML
        time_elem = self.soup.find(attrs={'itemprop': 'totalTime'})
        if time_elem:
            # Проверяем datetime атрибут
            if time_elem.get('datetime'):
                return self.parse_iso_duration(time_elem['datetime'])
            # Или берем текст
            return self.clean_text(time_elem.get_text())
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями/советами
        notes_keywords = ['note', 'tip', 'hint', 'advice', 'suggestion']
        
        # Ищем по классам
        for keyword in notes_keywords:
            notes_section = self.soup.find(class_=re.compile(keyword, re.I))
            if notes_section:
                # Извлекаем текст
                p = notes_section.find('p')
                if p:
                    text = self.clean_text(p.get_text())
                    return text if text else None
                
                # Если нет параграфа, берем весь текст
                text = notes_section.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                return text if text else None
        
        # Ищем в параграфах с ключевыми словами
        all_paragraphs = self.soup.find_all('p')
        for p in all_paragraphs:
            text = p.get_text(strip=True).lower()
            if any(kw in text for kw in ['feel free', 'you can substitute', 'keep in mind', 
                                          'for best results', 'freezes well', 'can be served']):
                cleaned_text = self.clean_text(p.get_text())
                return cleaned_text if cleaned_text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Список общих слов для фильтрации
        stopwords = {
            'recipe', 'recipes', 'easy', 'quick', 'food', 'cooking',
            'desidakaar', 'desidakaar.com', 'how to make', 'how to'
        }
        
        tags_list = []
        
        # Извлекаем из мета-тега keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            tags_string = meta_keywords['content']
            tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        # Или из parsely-tags
        if not tags_list:
            parsely_meta = self.soup.find('meta', attrs={'name': 'parsely-tags'})
            if parsely_meta and parsely_meta.get('content'):
                tags_string = parsely_meta['content']
                tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        # Или из JSON-LD keywords
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
        
        # Фильтрация тегов
        filtered_tags = []
        for tag in tags_list:
            tag_lower = tag.lower().strip()
            
            # Пропускаем стоп-слова
            if tag_lower in stopwords:
                continue
            
            # Пропускаем короткие теги
            if len(tag) < 3:
                continue
            
            filtered_tags.append(tag)
        
        # Удаляем дубликаты
        seen = set()
        unique_tags = []
        for tag in filtered_tags:
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen.add(tag_lower)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        json_ld = self._get_json_ld_data()
        
        # Извлекаем из JSON-LD
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
        
        # Ищем изображения с itemprop="image"
        itemprop_images = self.soup.find_all(attrs={'itemprop': 'image'})
        for img in itemprop_images:
            if img.get('src'):
                urls.append(img['src'])
            elif img.get('content'):
                urls.append(img['content'])
        
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
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "desidakaar_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(DesidakaarExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python desidakaar_com.py")


if __name__ == "__main__":
    main()
