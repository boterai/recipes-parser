"""
Экстрактор данных рецептов для сайта timenews.co.id
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TimenewsCoIdExtractor(BaseRecipeExtractor):
    """Экстрактор для timenews.co.id"""
    
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
                    
                    # Проверяем сам data
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
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_data()
        
        # Сначала пробуем из JSON-LD
        if json_ld and 'name' in json_ld:
            dish_name = self.clean_text(json_ld['name'])
            # Убираем общие префиксы типа "Resep ..."
            dish_name = re.sub(r'^(Resep\s+)', '', dish_name, flags=re.IGNORECASE)
            return dish_name
        
        # Альтернатива - из заголовка h1
        h1 = self.soup.find('h1')
        if h1:
            dish_name = self.clean_text(h1.get_text())
            dish_name = re.sub(r'^(Resep\s+)', '', dish_name, flags=re.IGNORECASE)
            return dish_name
        
        # Из meta title
        title = self.soup.find('title')
        if title:
            text = title.get_text()
            # Убираем суффиксы
            text = re.sub(r'\s*[-|].*$', '', text)
            text = re.sub(r'^(Resep\s+)', '', text, flags=re.IGNORECASE)
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
        
        # Из первого параграфа в основном контенте
        main_content = self.soup.find('div', class_=re.compile(r'entry-content|article-content|post-content', re.I))
        if main_content:
            first_p = main_content.find('p')
            if first_p:
                return self.clean_text(first_p.get_text())
        
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
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Поддержка английских и индонезийских единиц измерения
        pattern = r'^([\d\s/.,]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|packs?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads|buah|lembar|batang|siung|butir|sendok makan|sendok teh|ekor|secukupnya)?\s*(.+)'
        
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
        # Удаляем фразы "to taste", "as needed", "optional" и индонезийские аналоги
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|for serving|secukupnya)\b', '', name, flags=re.IGNORECASE)
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
            
            if ingredients:
                return json.dumps(ingredients, ensure_ascii=False)
        
        # Если JSON-LD не дал результата, ищем в HTML
        main_content = self.soup.find('div', class_=re.compile(r'entry-content|article-content|post-content', re.I))
        if not main_content:
            return None
        
        # Ищем секцию с ингредиентами по заголовку
        for heading in main_content.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text().strip().lower()
            
            # Проверяем, содержит ли заголовок ключевые слова (на индонезийском и английском)
            if any(keyword in heading_text for keyword in ['bahan', 'ingredient', 'materials']):
                # Собираем все списки после этого заголовка до следующего заголовка
                current = heading.find_next_sibling()
                while current and current.name not in ['h2', 'h3', 'h4']:
                    if current.name in ['ul', 'ol']:
                        items = current.find_all('li')
                        for item in items:
                            ingredient_text = item.get_text(separator=' ', strip=True)
                            # Пропускаем заголовки секций (обычно заканчиваются на ':')
                            if not ingredient_text.strip().endswith(':'):
                                parsed = self.parse_ingredient(ingredient_text)
                                if parsed and parsed['name']:
                                    ingredients.append(parsed)
                    current = current.find_next_sibling()
                
                if ingredients:
                    break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
        # Сначала пробуем из JSON-LD
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            steps = []
            
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
            
            if steps:
                return ' '.join(steps)
        
        # Если JSON-LD не дал результата, ищем в HTML
        steps = []
        main_content = self.soup.find('div', class_=re.compile(r'entry-content|article-content|post-content', re.I))
        if not main_content:
            return None
        
        # Ищем секцию с инструкциями по заголовку
        for heading in main_content.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text().strip().lower()
            
            # Проверяем, содержит ли заголовок ключевые слова (на индонезийском и английском)
            if any(keyword in heading_text for keyword in ['cara', 'langkah', 'instruction', 'direction', 'method', 'steps']):
                # Собираем все списки после этого заголовка до следующего заголовка
                current = heading.find_next_sibling()
                while current:
                    if current.name in ['h2', 'h3', 'h4']:
                        # Проверяем, не начинается ли следующий заголовок раздела (Tips, Notes и т.д.)
                        next_heading_text = current.get_text().strip().lower()
                        if any(keyword in next_heading_text for keyword in ['tips', 'catatan', 'note', 'saran', 'variasi', 'manfaat', 'nilai gizi']):
                            break
                    
                    if current.name in ['ol', 'ul']:
                        items = current.find_all('li')
                        for item in items:
                            step_text = item.get_text(separator=' ', strip=True)
                            step_text = self.clean_text(step_text)
                            if step_text:
                                steps.append(step_text)
                    current = current.find_next_sibling()
                    if not current:
                        break
                
                if steps:
                    break
        
        # Если нумерация не была в HTML, добавляем её
        if steps and not re.match(r'^\d+\.', steps[0]):
            steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
        
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
        
        # Ищем в хлебных крошках
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
        
        # Если JSON-LD не дал результата, ищем в HTML
        main_content = self.soup.find('div', class_=re.compile(r'entry-content|article-content|post-content', re.I))
        if main_content:
            text = main_content.get_text()
            
            # Паттерны для времени подготовки (на индонезийском и английском)
            patterns = [
                r'prep(?:aration)?\s+time[:\s]+(\d+[-\s]*\d*\s*(?:menit|minutes?|hour?s|hrs?))',
                r'waktu\s+persiapan[:\s]+(\d+[-\s]*\d*\s*(?:menit|minutes?|hour?s|hrs?))',
                r'persiapan[:\s]+(\d+[-\s]*\d*\s*(?:menit|minutes?|hour?s|hrs?))',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    time_str = self.clean_text(match.group(1))
                    # Конвертируем "menit" в "minutes"
                    time_str = time_str.replace('menit', 'minutes')
                    return time_str
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        # Если JSON-LD не дал результата, ищем в HTML
        main_content = self.soup.find('div', class_=re.compile(r'entry-content|article-content|post-content', re.I))
        if main_content:
            text = main_content.get_text()
            
            patterns = [
                r'cook(?:ing)?\s+time[:\s]+(\d+[-\s]*\d*\s*(?:menit|minutes?|hour?s|hrs?))',
                r'waktu\s+memasak[:\s]+(\d+[-\s]*\d*\s*(?:menit|minutes?|hour?s|hrs?))',
                r'memasak[:\s]+(\d+[-\s]*\d*\s*(?:menit|minutes?|hour?s|hrs?))',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    time_str = self.clean_text(match.group(1))
                    time_str = time_str.replace('menit', 'minutes')
                    return time_str
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        # Если JSON-LD не дал результата, ищем в HTML
        main_content = self.soup.find('div', class_=re.compile(r'entry-content|article-content|post-content', re.I))
        if main_content:
            text = main_content.get_text()
            
            patterns = [
                r'total\s+time[:\s]+(\d+[-\s]*\d*\s*(?:menit|minutes?|hour?s|hrs?))',
                r'waktu\s+total[:\s]+(\d+[-\s]*\d*\s*(?:menit|minutes?|hour?s|hrs?))',
                r'total\s+waktu[:\s]+(\d+[-\s]*\d*\s*(?:menit|minutes?|hour?s|hrs?))',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    time_str = self.clean_text(match.group(1))
                    time_str = time_str.replace('menit', 'minutes')
                    return time_str
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        main_content = self.soup.find('div', class_=re.compile(r'entry-content|article-content|post-content', re.I))
        if not main_content:
            return None
        
        # Ищем секции с заголовками о советах/примечаниях
        for heading in main_content.find_all(['h2', 'h3', 'h4']):
            heading_text = heading.get_text().strip().lower()
            
            # Проверяем ключевые слова (на индонезийском и английском)
            if any(keyword in heading_text for keyword in ['tips', 'catatan', 'note', 'saran', 'hint']):
                # Собираем текст из следующих параграфов
                notes_texts = []
                current = heading.find_next_sibling()
                
                while current and current.name not in ['h2', 'h3', 'h4']:
                    if current.name == 'p':
                        text = current.get_text(strip=True)
                        if text and len(text) > 10:
                            notes_texts.append(self.clean_text(text))
                    elif current.name in ['ul', 'ol']:
                        items = current.find_all('li')
                        for item in items[:2]:  # Берем первые 2 элемента
                            text = item.get_text(strip=True)
                            if text and len(text) > 10:
                                notes_texts.append(self.clean_text(text))
                    current = current.find_next_sibling()
                    
                    if len(notes_texts) >= 2:  # Ограничиваем 2 заметками
                        break
                
                if notes_texts:
                    return ' '.join(notes_texts[:2])
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Список общих слов и фраз без смысловой нагрузки для фильтрации
        stopwords = {
            'recipe', 'recipes', 'resep', 'timenews', 'easy', 'quick', 'mudah',
            'food', 'makanan', 'masakan', 'cooking', 'memasak'
        }
        
        tags_list = []
        
        # 1. Извлекаем из мета-тега keywords
        meta_keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            tags_string = meta_keywords['content']
            tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        # 2. Если не нашли, пробуем parsely-tags
        if not tags_list:
            parsely_meta = self.soup.find('meta', attrs={'name': 'parsely-tags'})
            if parsely_meta and parsely_meta.get('content'):
                tags_string = parsely_meta['content']
                tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        # 3. Если не нашли, пробуем из JSON-LD keywords
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
        
        # 1. Ищем в JSON-LD
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
        
        # 2. Ищем в meta тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Ищем основное изображение статьи
        main_image = self.soup.find('img', class_=re.compile(r'wp-post-image|featured-image|main-image', re.I))
        if main_image and main_image.get('src'):
            urls.append(main_image['src'])
        
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
    preprocessed_dir = os.path.join("preprocessed", "timenews_co_id")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(TimenewsCoIdExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python timenews_co_id.py")


if __name__ == "__main__":
    main()
