"""
Экстрактор данных рецептов для сайта buttalapasta.it
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ButtalaPastaExtractor(BaseRecipeExtractor):
    """Экстрактор для buttalapasta.it"""
    
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
                    
                    # Проверяем прямой Recipe
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
        
        # Если минут больше 60 и нет часов, конвертируем в часы и минуты
        if minutes >= 60 and hours == 0:
            hours = minutes // 60
            minutes = minutes % 60
        
        # Форматируем результат (используем единообразные сокращения)
        parts = []
        if hours > 0:
            parts.append(f"{hours} hr{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} min{'s' if minutes > 1 else ''}")
        
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
        
        # Из заголовка с классом entry-title (часто используется в WordPress)
        entry_title = self.soup.find(class_='entry-title')
        if entry_title:
            return self.clean_text(entry_title.get_text())
        
        # Из meta title
        title = self.soup.find('title')
        if title:
            text = title.get_text()
            # Убираем суффиксы типа " - Butta la Pasta"
            text = re.sub(r'\s*[-|].*$', '', text)
            text = re.sub(r'\s+Ricetta.*$', '', text, flags=re.IGNORECASE)
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
        
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        # Ищем в первом параграфе после заголовка
        h1 = self.soup.find('h1')
        if h1:
            # Ищем следующий параграф
            next_p = h1.find_next('p')
            if next_p:
                text = next_p.get_text(strip=True)
                if len(text) > 20:  # Минимальная длина описания
                    return self.clean_text(text)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "200 g farina" или "2 cucchiai burro"
            
        Returns:
            dict: {"name": "farina", "amount": "200", "unit": "g"}
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
        
        # Паттерн для извлечения количества, единицы и названия
        # Поддерживаем итальянские и английские единицы измерения
        pattern = r'^([\d\s/.,]+)?\s*(g|kg|ml|l|grammi?|chilogrammi?|litri?|millilitri?|cucchiai[oe]?|cucchiaini?|tazz[ae]|pezz[oi]|fett[ae]|spicchi[oe]?|foglie?|rametti?|pizzic[oi]|q\.?b\.?|quanto basta|cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads)?\s*(.+)'
        
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
        # Удаляем фразы вроде "a piacere", "quanto basta", "optional"
        name = re.sub(r'\b(a piacere|quanto basta|q\.?b\.?|to taste|as needed|or more|if needed|optional|for garnish|per guarnire)\b', '', name, flags=re.IGNORECASE)
        # Удаляем специфичные суффиксы вроде ", tritato", ", affettato" и т.д.
        name = re.sub(r',\s*(tritato|affettato|grattugiato|fresco|secco|a pezzi|tagliato|scolato|drained|grated|sliced|chopped|minced|crushed|fresh|dried).*$', '', name, flags=re.IGNORECASE)
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
        
        # Сначала пробуем из JSON-LD
        if json_ld and 'recipeIngredient' in json_ld:
            for ingredient_text in json_ld['recipeIngredient']:
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        # Если не нашли в JSON-LD, ищем в HTML
        if not ingredients:
            # Ищем список ингредиентов по различным классам и структурам
            ingredient_lists = [
                self.soup.find('ul', class_=re.compile(r'ingredient', re.I)),
                self.soup.find('div', class_=re.compile(r'ingredient', re.I)),
                self.soup.find('ul', class_=re.compile(r'recipe-ingredient', re.I)),
            ]
            
            for ingredient_list in ingredient_lists:
                if not ingredient_list:
                    continue
                
                # Извлекаем элементы списка
                items = ingredient_list.find_all('li')
                if not items:
                    items = ingredient_list.find_all('p')
                
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
        
        # Fallback: заголовки (напр. <h2>/<h3>) с текстом 'ingredienti' и последующие списки/параграфы
        if not ingredients:
            for header in self.soup.find_all(['h1','h2','h3','h4']):
                header_text = header.get_text(strip=True)
                if header_text and re.search(r'ingredienti|ingredient', header_text, re.I):
                    sibling = header.find_next_sibling()
                    while sibling:
                        if sibling.name and re.match(r'h[1-6]', sibling.name):
                            break
                        if sibling.name in ['ul','ol']:
                            for li in sibling.find_all('li'):
                                it = self.clean_text(li.get_text(separator=' ', strip=True))
                                parsed = self.parse_ingredient(it)
                                if parsed:
                                    ingredients.append(parsed)
                            break
                        if sibling.name == 'p':
                            lines = [ln.strip() for ln in sibling.get_text(separator='\n').split('\n') if ln.strip()]
                            for line in lines:
                                parsed = self.parse_ingredient(line)
                                if parsed:
                                    ingredients.append(parsed)
                            if ingredients:
                                break
                        sibling = sibling.find_next_sibling()
                    if ingredients:
                        break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
        steps = []
        
        # Сначала из JSON-LD
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict):
                        if 'text' in step:
                            step_text = self.clean_text(step['text'])
                            steps.append(f"{idx}. {step_text}")
                        elif 'itemListElement' in step:
                            # HowToSection с подшагами
                            for sub_step in step['itemListElement']:
                                if isinstance(sub_step, dict) and 'text' in sub_step:
                                    step_text = self.clean_text(sub_step['text'])
                                    steps.append(f"{len(steps) + 1}. {step_text}")
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        steps.append(f"{idx}. {step_text}")
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
        
        # Если не нашли в JSON-LD, ищем в HTML
        if not steps:
            instruction_lists = [
                self.soup.find('ol', class_=re.compile(r'instruction', re.I)),
                self.soup.find('div', class_=re.compile(r'instruction', re.I)),
                self.soup.find('ol', class_=re.compile(r'recipe-instruction', re.I)),
            ]
            
            for instruction_list in instruction_lists:
                if not instruction_list:
                    continue
                
                # Извлекаем шаги
                step_items = instruction_list.find_all('li')
                if not step_items:
                    step_items = instruction_list.find_all('p')
                
                for idx, item in enumerate(step_items, 1):
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    
                    if step_text:
                        # Если уже есть нумерация, оставляем как есть
                        if re.match(r'^\d+\.', step_text):
                            steps.append(step_text)
                        else:
                            steps.append(f"{idx}. {step_text}")
                
                if steps:
                    break
        
        # Fallback: заголовки с шагами (итальянские ключевые слова) и сбор следующего контента
        if not steps:
            for header in self.soup.find_all(['h1','h2','h3','h4']):
                header_text = header.get_text(strip=True)
                if header_text and re.search(r'(come si prepar|come si fa|come preparare|preparaz|procediment|come si prepara la)', header_text, re.I):
                    sibling = header.find_next_sibling()
                    while sibling:
                        if sibling.name and re.match(r'h[1-6]', sibling.name):
                            break
                        if sibling.name in ['ol','ul']:
                            for li in sibling.find_all('li'):
                                lt = self.clean_text(li.get_text(separator=' ', strip=True))
                                if lt:
                                    steps.append(lt)
                        if sibling.name == 'p':
                            text = self.clean_text(sibling.get_text(separator=' ', strip=True))
                            if text:
                                parts = [s.strip() for s in re.split(r'\.\s+|\n', text) if s.strip()]
                                for part in parts:
                                    steps.append(part)
                        sibling = sibling.find_next_sibling()
                    if steps:
                        break
        
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
        
        # Альтернатива - из мета тегов
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if not breadcrumbs:
            breadcrumbs = self.soup.find('div', class_=re.compile(r'breadcrumb', re.I))
        
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                # Берем категорию перед рецептом
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
        # Ищем секции с примечаниями
        note_keywords = [
            'note', 'consiglio', 'suggerimento', 'tip', 'importante',
            'attenzione', 'variante', 'conservazione'
        ]
        
        # Ищем заголовки с ключевыми словами
        for keyword in note_keywords:
            headers = self.soup.find_all(['h2', 'h3', 'h4', 'strong', 'b'])
            for header in headers:
                header_text = header.get_text(strip=True).lower()
                if keyword in header_text:
                    # Ищем следующий параграф или текст
                    next_elem = header.find_next(['p', 'div'])
                    if next_elem:
                        text = next_elem.get_text(separator=' ', strip=True)
                        cleaned_text = self.clean_text(text)
                        if cleaned_text and len(cleaned_text) > 10:
                            return cleaned_text
        
        # Ищем div или section с классом notes
        notes_section = self.soup.find(class_=re.compile(r'note', re.I))
        if notes_section:
            text = notes_section.get_text(separator=' ', strip=True)
            cleaned_text = self.clean_text(text)
            if cleaned_text and len(cleaned_text) > 10:
                return cleaned_text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Список стоп-слов для фильтрации
        stopwords = {
            'recipe', 'recipes', 'ricetta', 'ricette', 'cucina', 'cooking',
            'buttalapasta', 'butta la pasta', 'food', 'easy', 'facile'
        }
        
        # Извлекаем из мета-тега keywords
        keywords_meta = self.soup.find('meta', attrs={'name': 'keywords'})
        if keywords_meta and keywords_meta.get('content'):
            tags_string = keywords_meta['content']
            tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        # Извлекаем из мета-тега parsely-tags
        if not tags_list:
            parsely_meta = self.soup.find('meta', attrs={'name': 'parsely-tags'})
            if parsely_meta and parsely_meta.get('content'):
                tags_string = parsely_meta['content']
                tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        # Извлекаем из JSON-LD keywords
        if not tags_list:
            json_ld = self._get_json_ld_data()
            if json_ld and 'keywords' in json_ld:
                keywords = json_ld['keywords']
                if isinstance(keywords, str):
                    tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                elif isinstance(keywords, list):
                    tags_list = keywords
        
        # Ищем теги в HTML (часто используются <a> с rel="tag")
        if not tags_list:
            tag_links = self.soup.find_all('a', rel='tag')
            if tag_links:
                tags_list = [link.get_text(strip=True) for link in tag_links]
        
        if not tags_list:
            return None
        
        # Фильтрация тегов
        filtered_tags = []
        for tag in tags_list:
            tag_lower = tag.lower()
            
            # Пропускаем точные совпадения со стоп-словами
            if tag_lower in stopwords:
                continue
            
            # Пропускаем теги короче 3 символов
            if len(tag) < 3:
                continue
            
            filtered_tags.append(tag)
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in filtered_tags:
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen.add(tag_lower)
                unique_tags.append(tag)
        
        # Возвращаем как строку через запятую с пробелом
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
        
        # Ищем изображения в контенте рецепта
        if not urls:
            # Ищем изображения с классами, содержащими recipe, featured, wp-post
            img_tags = self.soup.find_all('img', class_=re.compile(r'(recipe|featured|wp-post|entry)', re.I))
            for img in img_tags[:3]:  # Берем первые 3
                if img.get('src'):
                    urls.append(img['src'])
                elif img.get('data-src'):
                    urls.append(img['data-src'])
        
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
            Словарь с данными рецепта со всеми обязательными полями
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
    preprocessed_dir = os.path.join("preprocessed", "buttalapasta_it")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(ButtalaPastaExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python buttalapasta_it.py")


if __name__ == "__main__":
    main()
