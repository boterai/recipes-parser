"""
Экстрактор данных рецептов для сайта receiteria.com.br
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ReceiteriaCombBrExtractor(BaseRecipeExtractor):
    """Экстрактор для receiteria.com.br"""
    
    def extract_from_json_ld(self) -> dict:
        """Извлечение данных из JSON-LD схемы (наиболее надежный способ)"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Функция для проверки типа Recipe
                def is_recipe(item):
                    item_type = item.get('@type', '')
                    if isinstance(item_type, list):
                        return 'Recipe' in item_type
                    return item_type == 'Recipe'
                
                # Ищем Recipe в данных
                recipe_data = None
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and is_recipe(item):
                            recipe_data = item
                            break
                elif isinstance(data, dict):
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and is_recipe(item):
                                recipe_data = item
                                break
                    elif is_recipe(data):
                        recipe_data = data
                
                if recipe_data:
                    return recipe_data
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return {}
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        json_ld = self.extract_from_json_ld()
        if json_ld.get('name'):
            return self.clean_text(json_ld['name'])
        
        # Ищем в заголовке рецепта
        h1_tags = self.soup.find_all('h1')
        for h1 in h1_tags:
            text = self.clean_text(h1.get_text())
            if text and len(text) > 3:
                return text
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - Receiteria"
            title = re.sub(r'\s*[-|]\s*(Receiteria|Receita).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Из JSON-LD
        json_ld = self.extract_from_json_ld()
        if json_ld.get('description'):
            return self.clean_text(json_ld['description'])
        
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        # Ищем первый параграф после заголовка
        intro = self.soup.find(class_=re.compile(r'intro|description|summary', re.I))
        if intro:
            return self.clean_text(intro.get_text())
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "200g de farinha" ou "2 xícaras de açúcar"
            
        Returns:
            dict: {"name": "farinha", "amount": "200", "unit": "g"} ou None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для португальского языка с учетом составных единиц
        # Примеры: "200g de farinha", "2 xícaras de açúcar", "1 colher de sopa de manteiga"
        # Единицы измерения на португальском
        pattern = r'^([\d\s/.,]+)?\s*(g|gramas?|kg|quilogramas?|ml|mililitros?|litros?|xícaras?|latas?|colheres?\s+(?:de\s+)?(?:sopa|chá|café)|colher\s+(?:de\s+)?(?:sopa|chá|café)|unidades?|dentes?|pitadas?|a\s+gosto|quanto\s+baste?)?\s*(?:de\s+)?(.+)'
        
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
        if unit:
            unit = unit.strip()
            # Нормализация составных единиц
            unit = re.sub(r'\s+', ' ', unit)
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "a gosto", "quanto baste", "opcional"
        name = re.sub(r'\b(a gosto|quanto baste|opcional|se necessário|para decorar)\b', '', name, flags=re.IGNORECASE)
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
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем извлечь из JSON-LD (наиболее структурированный формат)
        json_ld = self.extract_from_json_ld()
        if json_ld.get('recipeIngredient'):
            recipe_ingredients = json_ld['recipeIngredient']
            if isinstance(recipe_ingredients, list):
                for ingredient_text in recipe_ingredients:
                    if isinstance(ingredient_text, str):
                        parsed = self.parse_ingredient(ingredient_text)
                        if parsed:
                            ingredients.append(parsed)
                
                if ingredients:
                    return json.dumps(ingredients, ensure_ascii=False)
        
        # Если JSON-LD не помог, ищем в HTML
        # Ищем список ингредиентов через различные возможные классы
        ingredient_containers = [
            self.soup.find('ul', class_=re.compile(r'ingredient', re.I)),
            self.soup.find('div', class_=re.compile(r'ingredient', re.I)),
            self.soup.find('div', id=re.compile(r'ingredient', re.I))
        ]
        
        for container in ingredient_containers:
            if not container:
                continue
                
            # Извлекаем элементы списка
            items = container.find_all('li')
            if not items:
                items = container.find_all('p')
            
            for item in items:
                # Извлекаем текст ингредиента
                ingredient_text = item.get_text(separator=' ', strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                # Пропускаем заголовки секций (часто содержат двоеточие)
                if ingredient_text and not ingredient_text.endswith(':'):
                    # Парсим в структурированный формат
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
            
            if ingredients:
                break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld = self.extract_from_json_ld()
        if json_ld.get('recipeInstructions'):
            instructions = json_ld['recipeInstructions']
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict):
                        if 'text' in step:
                            steps.append(f"{idx}. {self.clean_text(step['text'])}")
                        elif 'itemListElement' in step:
                            # HowToSection
                            for sub_step in step['itemListElement']:
                                if isinstance(sub_step, dict) and 'text' in sub_step:
                                    steps.append(self.clean_text(sub_step['text']))
                    elif isinstance(step, str):
                        steps.append(f"{idx}. {self.clean_text(step)}")
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            
            if steps:
                return ' '.join(steps)
        
        # Если JSON-LD не помог, ищем в HTML
        instructions_containers = [
            self.soup.find('ol', class_=re.compile(r'instruction|steps|modo.*preparo|preparo', re.I)),
            self.soup.find('div', class_=re.compile(r'instruction|steps|modo.*preparo|preparo', re.I)),
            self.soup.find('div', id=re.compile(r'instruction|steps|modo.*preparo|preparo', re.I))
        ]
        
        for container in instructions_containers:
            if not container:
                continue
            
            # Извлекаем шаги
            step_items = container.find_all('li')
            if not step_items:
                step_items = container.find_all('p')
            
            for idx, item in enumerate(step_items, 1):
                # Извлекаем текст инструкции
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    # Добавляем нумерацию если её нет
                    if not re.match(r'^\d+\.', step_text):
                        step_text = f"{idx}. {step_text}"
                    steps.append(step_text)
            
            if steps:
                break
        
        return ' '.join(steps) if steps else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности в формате: 202 kcal; 2/11/27"""
        # Из JSON-LD
        json_ld = self.extract_from_json_ld()
        if json_ld.get('nutrition'):
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
        
        # Ищем в HTML
        nutrition_section = self.soup.find(class_=re.compile(r'nutrition|nutri[çc][ãa]o', re.I))
        if nutrition_section:
            text = nutrition_section.get_text()
            # Ищем паттерны калорий и БЖУ
            cal_match = re.search(r'(\d+)\s*(?:kcal|cal)', text, re.I)
            if cal_match:
                return f"{cal_match.group(1)} kcal"
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Из JSON-LD
        json_ld = self.extract_from_json_ld()
        if json_ld.get('recipeCategory'):
            category = json_ld['recipeCategory']
            if isinstance(category, list):
                return ', '.join([self.clean_text(c) for c in category])
            return self.clean_text(category)
        
        if json_ld.get('recipeCuisine'):
            cuisine = json_ld['recipeCuisine']
            if isinstance(cuisine, list):
                return ', '.join([self.clean_text(c) for c in cuisine])
            return self.clean_text(cuisine)
        
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find(class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах с единицей, например "90 minutes"
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
            return f"{total_minutes} minutes"
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Из JSON-LD
        json_ld = self.extract_from_json_ld()
        
        # Маппинг типов времени на ключи JSON-LD
        time_keys = {
            'prep': 'prepTime',
            'cook': 'cookTime',
            'total': 'totalTime'
        }
        
        key = time_keys.get(time_type)
        if key and json_ld.get(key):
            iso_time = json_ld[key]
            return self.parse_iso_duration(iso_time)
        
        # Ищем в HTML
        time_patterns = {
            'prep': ['prep.*time', 'tempo.*preparo', 'prepar'],
            'cook': ['cook.*time', 'tempo.*cozimento', 'cozimento'],
            'total': ['total.*time', 'tempo.*total', 'total']
        }
        
        patterns = time_patterns.get(time_type, [])
        
        for pattern in patterns:
            time_elem = self.soup.find(class_=re.compile(pattern, re.I))
            if not time_elem:
                time_elem = self.soup.find(attrs={'data-time': re.compile(pattern, re.I)})
            
            if time_elem:
                time_text = time_elem.get_text(strip=True)
                # Извлекаем число и единицу
                time_match = re.search(r'(\d+)\s*(min|minutos?|hora?|h)', time_text, re.I)
                if time_match:
                    value = time_match.group(1)
                    unit = time_match.group(2).lower()
                    # Конвертируем в минуты
                    if 'h' in unit or 'hora' in unit:
                        return f"{int(value) * 60} minutes"
                    else:
                        return f"{value} minutes"
                return self.clean_text(time_text)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('total')
    
    def extract_rating(self) -> Optional[float]:
        """Извлечение рейтинга рецепта"""
        # Из JSON-LD
        json_ld = self.extract_from_json_ld()
        if json_ld.get('aggregateRating'):
            rating_data = json_ld['aggregateRating']
            if 'ratingValue' in rating_data:
                try:
                    return float(rating_data['ratingValue'])
                except (ValueError, TypeError):
                    pass
        
        # Ищем в HTML
        rating_elem = self.soup.find(class_=re.compile(r'rating|avalia[çc][ãa]o', re.I))
        if rating_elem:
            text = rating_elem.get_text()
            rating_match = re.search(r'(\d+(?:[.,]\d+)?)', text)
            if rating_match:
                try:
                    return float(rating_match.group(1).replace(',', '.'))
                except ValueError:
                    pass
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями/советами
        notes_sections = [
            self.soup.find(class_=re.compile(r'note|tip|dica|observa[çc][ãa]o', re.I)),
            self.soup.find('div', id=re.compile(r'note|tip|dica', re.I))
        ]
        
        for notes_section in notes_sections:
            if notes_section:
                # Сначала пробуем найти параграф внутри (без заголовка)
                p = notes_section.find('p')
                if p:
                    text = self.clean_text(p.get_text())
                    return text if text else None
                
                # Если нет параграфа, берем весь текст и убираем заголовок
                text = notes_section.get_text(separator=' ', strip=True)
                text = re.sub(r'^(Notas?|Dicas?|Observa[çc][õo]es?)\s*:?\s*', '', text, flags=re.IGNORECASE)
                text = self.clean_text(text)
                if text:
                    return text
        
        return None
    
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Список стоп-слов для фильтрации
        stopwords = {
            'recipe', 'recipes', 'receita', 'receitas', 'how to make', 'how to', 'easy', 
            'cooking', 'quick', 'food', 'kitchen', 'simple', 'best', 'make', 'ingredients',
            'video', 'meal', 'prep', 'ideas', 'tips', 'tricks', 'hacks', 'home', 'family',
            'prepare', 'friends', 'homemade', 'dish', 'perfect', 'favorite', 'delicious',
            'tutorial', 'demo', 'how', 'to', 'facil', 'fácil', 'rapido', 'rápido',
            'como fazer', 'passo a passo', 'culinária', 'culinaria', 'cozinha'
        }
        
        tags_list = []
        
        # 1. Пробуем извлечь из meta-тега keywords
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags_list = [tag.strip().lower() for tag in keywords.split(',') if tag.strip()]
        
        # 2. Ищем в meta-тегах parsely или article:tag
        if not tags_list:
            parsely_meta = self.soup.find('meta', attrs={'name': 'parsely-tags'})
            if parsely_meta and parsely_meta.get('content'):
                tags_string = parsely_meta['content']
                tags_list = [tag.strip().lower() for tag in tags_string.split(',') if tag.strip()]
        
        # 3. Ищем теги article:tag
        if not tags_list:
            article_tags = self.soup.find_all('meta', property='article:tag')
            if article_tags:
                tags_list = [tag.get('content').lower() for tag in article_tags if tag.get('content')]
        
        # 4. Ищем в JSON-LD
        if not tags_list:
            json_ld = self.extract_from_json_ld()
            if json_ld.get('keywords'):
                keywords = json_ld['keywords']
                if isinstance(keywords, str):
                    tags_list = [tag.strip().lower() for tag in keywords.split(',') if tag.strip()]
                elif isinstance(keywords, list):
                    tags_list = [tag.lower() for tag in keywords if isinstance(tag, str)]
        
        if not tags_list:
            return None
        
        # Фильтрация тегов
        filtered_tags = []
        for tag in tags_list:
            # Пропускаем точные совпадения со стоп-словами
            if tag in stopwords:
                continue
            
            # Пропускаем теги короче 3 символов
            if len(tag) < 3:
                continue
            
            filtered_tags.append(tag)
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in filtered_tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        # Возвращаем как строку через запятую
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 2. Ищем в JSON-LD
        json_ld = self.extract_from_json_ld()
        if json_ld.get('image'):
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
        # 3. Ищем изображения в контенте рецепта
        recipe_content = self.soup.find(class_=re.compile(r'recipe.*content|receita', re.I))
        if recipe_content:
            images = recipe_content.find_all('img')
            for img in images[:3]:  # Берем до 3 изображений
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
            Словарь с данными рецепта
        """
        return {
            "dish_name": self.extract_dish_name(),
            "description": self.extract_description(),
            "ingredient": self.extract_ingredients(),
            "step_by_step": self.extract_steps(),
            "nutrition_info": self.extract_nutrition_info(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "rating": self.extract_rating(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Точка входа для обработки рецептов receiteria.com.br"""
    import os
    
    # Ищем директорию с HTML-страницами относительно корня репозитория
    recipes_dir = os.path.join("preprocessed", "receiteria_com_br")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(ReceiteriaCombBrExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python receiteria_com_br.py")


if __name__ == "__main__":
    main()
