"""
Экстрактор данных рецептов для сайта bithealthier.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class BitHealthierExtractor(BaseRecipeExtractor):
    """Экстрактор для bithealthier.com"""
    
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
                    # Проверяем основной объект
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
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Из meta title
        title = self.soup.find('title')
        if title:
            text = title.get_text()
            # Убираем суффиксы
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
        
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов в формате списка словарей
        Приоритет: JSON-LD с детальной структурой, затем recipeIngredient
        """
        json_ld = self._get_json_ld_data()
        
        ingredients = []
        
        # Сначала ищем в JSON-LD детальную структуру ингредиентов
        if json_ld:
            # Проверяем recipeIngredient с детальной структурой
            if 'recipeIngredient' in json_ld:
                recipe_ingredients = json_ld['recipeIngredient']
                
                # Если это список объектов с name, amount, unit
                if isinstance(recipe_ingredients, list):
                    for ing in recipe_ingredients:
                        if isinstance(ing, dict):
                            # Если есть структурированные поля
                            if 'name' in ing or 'ingredient' in ing:
                                ingredient_dict = {
                                    "name": self.clean_text(ing.get('name') or ing.get('ingredient', '')),
                                    "amount": str(ing.get('amount', '')) if ing.get('amount') else None,
                                    "unit": self.clean_text(ing.get('unit', '')) if ing.get('unit') else None
                                }
                                if ingredient_dict['name']:
                                    ingredients.append(ingredient_dict)
                            else:
                                # Иначе это строка
                                ing_text = str(ing)
                                parsed = self.parse_ingredient(ing_text)
                                if parsed:
                                    ingredients.append(parsed)
                        elif isinstance(ing, str):
                            # Парсим строковое представление
                            parsed = self.parse_ingredient(ing)
                            if parsed:
                                ingredients.append(parsed)
        
        # Если не нашли ингредиенты в JSON-LD, ищем в HTML
        if not ingredients:
            # Ищем элементы со структурированными атрибутами
            ingredient_items = self.soup.find_all(attrs={
                'itemprop': re.compile(r'recipeIngredient', re.I)
            })
            
            for item in ingredient_items:
                ingredient_text = item.get_text(strip=True)
                if ingredient_text:
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
            
            # Если не нашли через itemprop, ищем списки
            if not ingredients:
                ingredient_lists = [
                    self.soup.find('ul', class_=re.compile(r'ingredient', re.I)),
                    self.soup.find('div', class_=re.compile(r'ingredient', re.I))
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
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        pattern = r'^([\d\s/.,]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|packs?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads)?\s*(.+)'
        
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
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict):
                        if 'text' in step:
                            step_text = self.clean_text(step['text'])
                            steps.append(f"{idx}. {step_text}")
                        elif 'itemListElement' in step:
                            # HowToSection с подшагами
                            for substep in step['itemListElement']:
                                if isinstance(substep, dict) and 'text' in substep:
                                    step_text = self.clean_text(substep['text'])
                                    steps.append(f"{len(steps) + 1}. {step_text}")
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        steps.append(f"{idx}. {step_text}")
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            
            if steps:
                return ' '.join(steps)
        
        # Если JSON-LD не помог, ищем в HTML
        instruction_items = self.soup.find_all(attrs={
            'itemprop': re.compile(r'recipeInstructions?', re.I)
        })
        
        if instruction_items:
            steps = []
            for idx, item in enumerate(instruction_items, 1):
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                if step_text:
                    steps.append(f"{idx}. {step_text}")
            
            if steps:
                return ' '.join(steps)
        
        # Ищем упорядоченный или неупорядоченный список инструкций
        instruction_containers = [
            self.soup.find('ol', class_=re.compile(r'instruction', re.I)),
            self.soup.find('div', class_=re.compile(r'instruction', re.I))
        ]
        
        for container in instruction_containers:
            if not container:
                continue
            
            step_items = container.find_all('li')
            if not step_items:
                step_items = container.find_all('p')
            
            steps = []
            for idx, item in enumerate(step_items, 1):
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    # Если нет нумерации, добавляем
                    if not re.match(r'^\d+\.', step_text):
                        steps.append(f"{idx}. {step_text}")
                    else:
                        steps.append(step_text)
            
            if steps:
                return ' '.join(steps)
        
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
            # Проверяем атрибут datetime
            if time_elem.get('datetime'):
                return self.parse_iso_duration(time_elem['datetime'])
            # Иначе берем текст
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
            # Проверяем атрибут datetime
            if time_elem.get('datetime'):
                return self.parse_iso_duration(time_elem['datetime'])
            # Иначе берем текст
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
            # Проверяем атрибут datetime
            if time_elem.get('datetime'):
                return self.parse_iso_duration(time_elem['datetime'])
            # Иначе берем текст
            return self.clean_text(time_elem.get_text())
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секции с заметками/примечаниями
        note_sections = [
            self.soup.find(class_=re.compile(r'note', re.I)),
            self.soup.find(class_=re.compile(r'tip', re.I)),
            self.soup.find(id=re.compile(r'note', re.I)),
        ]
        
        for section in note_sections:
            if section:
                # Извлекаем текст, игнорируя заголовки
                paragraphs = section.find_all('p')
                if paragraphs:
                    notes = []
                    for p in paragraphs:
                        text = self.clean_text(p.get_text())
                        if text:
                            notes.append(text)
                    if notes:
                        return ' '.join(notes)
                
                # Если нет параграфов, берем весь текст
                text = section.get_text(separator=' ', strip=True)
                # Убираем заголовок "Notes:" и подобное
                text = re.sub(r'^(Note|Notes|Tips?|Chef\'?s?\s+Note)s?\s*:?\s*', '', text, flags=re.IGNORECASE)
                text = self.clean_text(text)
                if text:
                    return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # 1. Из JSON-LD keywords
        json_ld = self._get_json_ld_data()
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if isinstance(keywords, str):
                tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            elif isinstance(keywords, list):
                tags_list = [str(tag).strip() for tag in keywords if tag]
        
        # 2. Из meta тега keywords
        if not tags_list:
            meta_keywords = self.soup.find('meta', {'name': 'keywords'})
            if meta_keywords and meta_keywords.get('content'):
                keywords_string = meta_keywords['content']
                tags_list = [tag.strip() for tag in keywords_string.split(',') if tag.strip()]
        
        # 3. Из parsely-tags
        if not tags_list:
            parsely_meta = self.soup.find('meta', attrs={'name': 'parsely-tags'})
            if parsely_meta and parsely_meta.get('content'):
                tags_string = parsely_meta['content']
                tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        # 4. Из article:tag
        if not tags_list:
            article_tags = self.soup.find_all('meta', property='article:tag')
            for tag_elem in article_tags:
                if tag_elem.get('content'):
                    tags_list.append(tag_elem['content'].strip())
        
        if not tags_list:
            return None
        
        # Фильтрация стоп-слов
        stopwords = {
            'recipe', 'recipes', 'easy', 'quick', 'simple', 'best',
            'bithealthier', 'food', 'cooking', 'homemade'
        }
        
        filtered_tags = []
        for tag in tags_list:
            tag_lower = tag.lower().strip()
            
            # Пропускаем стоп-слова
            if tag_lower in stopwords:
                continue
            
            # Пропускаем очень короткие теги
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
        
        # Возвращаем как строку через запятую с пробелом
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        json_ld = self._get_json_ld_data()
        
        # 1. Из JSON-LD
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
        
        # 2. Из meta тегов
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Из itemprop="image"
        itemprop_images = self.soup.find_all(attrs={'itemprop': 'image'})
        for img_elem in itemprop_images:
            if img_elem.name == 'img' and img_elem.get('src'):
                urls.append(img_elem['src'])
            elif img_elem.name == 'meta' and img_elem.get('content'):
                urls.append(img_elem['content'])
        
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
            Словарь с данными рецепта (все обязательные поля присутствуют)
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
    preprocessed_dir = os.path.join("preprocessed", "bithealthier_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(BitHealthierExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python bithealthier_com.py")


if __name__ == "__main__":
    main()
