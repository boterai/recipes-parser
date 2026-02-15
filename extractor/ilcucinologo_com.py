"""
Экстрактор данных рецептов для сайта ilcucinologo.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class IlCucinologoExtractor(BaseRecipeExtractor):
    """Экстрактор для ilcucinologo.com"""
    
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
                    # Проверяем @graph (часто используется на итальянских сайтах)
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
        h1 = self.soup.find('h1', class_=re.compile(r'recipe.*title|entry.*title|post.*title', re.I))
        if not h1:
            h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Из meta title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - Il Cucinologo" или " | Recipe"
            title = re.sub(r'\s*[-|]\s*(Il Cucinologo|Recipe).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        title = self.soup.find('title')
        if title:
            text = title.get_text()
            text = re.sub(r'\s*[-|].*$', '', text)
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
        
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате списка словарей"""
        json_ld = self._get_json_ld_data()
        
        ingredients = []
        
        # Пробуем извлечь из JSON-LD
        if json_ld and 'recipeIngredient' in json_ld:
            for ingredient_text in json_ld['recipeIngredient']:
                if isinstance(ingredient_text, str):
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        # Если JSON-LD не дал результата, ищем в HTML
        if not ingredients:
            # Ищем список ингредиентов по различным селекторам
            ingredient_lists = [
                self.soup.find('ul', class_=re.compile(r'ingredient', re.I)),
                self.soup.find('div', class_=re.compile(r'ingredient', re.I)),
                self.soup.find('ol', class_=re.compile(r'ingredient', re.I))
            ]
            
            for container in ingredient_lists:
                if not container:
                    continue
                
                items = container.find_all('li')
                if not items:
                    items = container.find_all('p')
                
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
        # Поддерживаем как английские, так и итальянские единицы измерения
        pattern = r'^([\d\s/.,]+)?\s*(cups?|cucchiai?|cucchiaini?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grammi?|chilogrammi?|grams?|kilograms?|g|kg|millilitri?|litri?|milliliters?|liters?|ml|l|pizzico|pizzichi|pinch(?:es)?|dash(?:es)?|confezioni?|lattine?|packages?|cans?|jars?|bottles?|fette?|slices?|spicchi?|cloves?|mazzi?|bunches?|sprigs?|intero|interi|metà|quarti?|pezzi?|whole|halves?|quarters?|pieces?|head|heads|q\.?b\.?)?\s*(.+)'
        
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
                amount = str(total) if not total.is_integer() else str(int(total))
            else:
                try:
                    val = float(amount_str.replace(',', '.'))
                    amount = str(int(val)) if val.is_integer() else str(val)
                except:
                    amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы типа "a piacere", "quanto basta", "optional"
        name = re.sub(r'\b(a piacere|quanto basta|q\.?b\.?|to taste|as needed|or more|if needed|optional|for garnish|per guarnire)\b', '', name, flags=re.IGNORECASE)
        # Удаляем специфичные суффиксы
        name = re.sub(r',\s*(drained|grated|sliced|chopped|minced|crushed|tritato|grattugiato|affettato|scolato).*$', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы, запятые и точки
        name = re.sub(r'[,;.]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
        steps = []
        
        # Пробуем извлечь из JSON-LD
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
        
        # Если JSON-LD не дал результата, ищем в HTML
        if not steps:
            instruction_containers = [
                self.soup.find('ol', class_=re.compile(r'instruction|step|procedimento|preparazione', re.I)),
                self.soup.find('div', class_=re.compile(r'instruction|step|procedimento|preparazione', re.I))
            ]
            
            for container in instruction_containers:
                if not container:
                    continue
                
                step_items = container.find_all('li')
                if not step_items:
                    step_items = container.find_all('p')
                
                for idx, item in enumerate(step_items, 1):
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    
                    if step_text:
                        # Добавляем нумерацию, если её нет
                        if not re.match(r'^\d+\.', step_text):
                            steps.append(f"{idx}. {step_text}")
                        else:
                            steps.append(step_text)
                
                if steps:
                    break
        
        return ' '.join(steps) if steps else None
    
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
        # Ищем секции с примечаниями/советами
        note_sections = [
            self.soup.find(class_=re.compile(r'note|tip|consiglio|suggerimento', re.I)),
            self.soup.find('div', class_=re.compile(r'note|tip|consiglio|suggerimento', re.I))
        ]
        
        for section in note_sections:
            if section:
                text = section.get_text(separator=' ', strip=True)
                # Убираем заголовок, если есть
                text = re.sub(r'^(Note|Tip|Consiglio|Suggerimento)s?\s*:?\s*', '', text, flags=re.I)
                text = self.clean_text(text)
                if text:
                    return text
        
        # Ищем параграфы с ключевыми словами
        paragraphs = self.soup.find_all('p')
        for p in paragraphs:
            text = p.get_text(strip=True)
            # Итальянские и английские ключевые слова
            if any(keyword in text.lower() for keyword in [
                'consiglio', 'suggerimento', 'nota', 'tip', 'note',
                'si può', 'puoi', 'you can', 'feel free', 'optional'
            ]):
                cleaned_text = self.clean_text(text)
                if cleaned_text and len(cleaned_text) > 20:
                    return cleaned_text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Извлекаем из мета-тега keywords
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        # Пробуем parsely-tags
        if not tags_list:
            parsely_meta = self.soup.find('meta', attrs={'name': 'parsely-tags'})
            if parsely_meta and parsely_meta.get('content'):
                tags_string = parsely_meta['content']
                tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        # Пробуем article:tag
        if not tags_list:
            article_tags = self.soup.find_all('meta', property='article:tag')
            for tag_meta in article_tags:
                if tag_meta.get('content'):
                    tags_list.append(tag_meta['content'].strip())
        
        if not tags_list:
            return None
        
        # Фильтрация и очистка тегов
        stopwords = {
            'recipe', 'recipes', 'ricetta', 'ricette', 'cucina', 'cooking',
            'il cucinologo', 'ilcucinologo'
        }
        
        filtered_tags = []
        for tag in tags_list:
            tag_lower = tag.lower()
            
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "ilcucinologo_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(IlCucinologoExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python ilcucinologo_com.py")


if __name__ == "__main__":
    main()
