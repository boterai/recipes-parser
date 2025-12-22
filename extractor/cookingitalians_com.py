"""
Экстрактор данных рецептов для сайта cookingitalians.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CookingItaliansExtractor(BaseRecipeExtractor):
    """Экстрактор для cookingitalians.com"""
    
    def __init__(self, html_path: str):
        super().__init__(html_path)
        self._json_ld_recipe = None
        self._wprm_recipe = None
        self._extract_embedded_data()
    
    def _extract_embedded_data(self):
        """Извлечение данных из JSON-LD и window.wprm_recipes"""
        # Извлечение из JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            self._json_ld_recipe = item
                            break
            except (json.JSONDecodeError, AttributeError):
                continue
        
        # Извлечение из window.wprm_recipes
        scripts = self.soup.find_all('script')
        for script in scripts:
            if script.string and 'window.wprm_recipes' in script.string:
                try:
                    match = re.search(r'window\.wprm_recipes\s*=\s*({.*?})(?=;|\s*</script>)', 
                                    script.string, re.DOTALL)
                    if match:
                        recipes_data = json.loads(match.group(1))
                        # Берем первый рецепт (обычно это основной рецепт страницы)
                        recipe_id = list(recipes_data.keys())[0]
                        self._wprm_recipe = recipes_data[recipe_id]
                        break
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в читаемом формате, например "20 minutes" или "1 hour 30 minutes"
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
        
        # Форматируем в читаемый вид
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        if self._json_ld_recipe and 'name' in self._json_ld_recipe:
            name = self._json_ld_recipe['name']
            # Убираем суффикс " Recipe"
            name = re.sub(r'\s+Recipe\s*$', '', name, flags=re.IGNORECASE)
            return self.clean_text(name)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s+(Recipe|Cooking Italians).*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Убираем префикс "Cooking Italians - "
            desc = re.sub(r'^Cooking Italians\s*-\s*', '', desc, flags=re.IGNORECASE)
            return self.clean_text(desc)
        
        # Альтернативно - из JSON-LD description
        if self._json_ld_recipe and self._json_ld_recipe.get('description'):
            return self.clean_text(self._json_ld_recipe['description'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном виде"""
        ingredients = []
        
        # Используем данные из window.wprm_recipes (наиболее структурированные)
        if self._wprm_recipe and 'ingredients' in self._wprm_recipe:
            for ing in self._wprm_recipe['ingredients']:
                # Конвертируем amount в int если это возможно
                amount = ing.get('amount')
                if amount:
                    try:
                        # Пробуем сконвертировать в число (int или float)
                        if '.' in str(amount) or '/' in str(amount):
                            amount = float(amount)
                        else:
                            amount = int(amount)
                    except (ValueError, TypeError):
                        # Если не получилось, оставляем как строку
                        pass
                else:
                    amount = None
                
                ingredient_dict = {
                    "name": ing.get('name', ''),
                    "units": ing.get('unit') if ing.get('unit') else None,
                    "amount": amount
                }
                ingredients.append(ingredient_dict)
        
        # Если не удалось получить из WPRM, пробуем из JSON-LD
        elif self._json_ld_recipe and 'recipeIngredient' in self._json_ld_recipe:
            for ing_text in self._json_ld_recipe['recipeIngredient']:
                parsed = self.parse_ingredient(ing_text)
                if parsed:
                    ingredients.append(parsed)
        
        # Если ничего не нашли, ищем в HTML напрямую
        else:
            # Ищем списки ингредиентов по заголовкам
            headers = self.soup.find_all(['h2', 'h3', 'h4', 'strong', 'b'])
            for header in headers:
                header_text = header.get_text(strip=True).lower()
                if 'ingredient' in header_text:
                    # Ищем следующий список после заголовка
                    next_list = header.find_next(['ul', 'ol'])
                    if next_list:
                        items = next_list.find_all('li', recursive=False)
                        for item in items:
                            ing_text = item.get_text(strip=True)
                            parsed = self.parse_ingredient(ing_text)
                            if parsed:
                                ingredients.append(parsed)
                        break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour" или "14 oz flour"
            
        Returns:
            dict: {"name": "flour", "amount": 1, "units": "cup"} или None
        """
        if not ingredient_text:
            return None
        
        text = self.clean_text(ingredient_text).lower()
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Обновлен для поддержки более широкого списка единиц
        pattern = r'^([\d\s/.,]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|fl\s*oz|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|beaten|juice of \d+ lemon)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
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
            try:
                if '/' in amount_str:
                    parts = amount_str.split()
                    total = 0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            total += float(part)
                    # Конвертируем в int если это целое число
                    amount = int(total) if total.is_integer() else total
                else:
                    amount_val = float(amount_str.replace(',', '.'))
                    amount = int(amount_val) if amount_val.is_integer() else amount_val
            except ValueError:
                # Если не можем распарсить число, оставляем как строку
                amount = amount_str
        
        # Очистка названия
        name = re.sub(r'\([^)]*\)', '', name)
        name = re.sub(r',\s*plus extra.*$', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish|for dusting)\b', '', name, flags=re.IGNORECASE)
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        return {
            "name": name if name else text,
            "amount": amount,
            "units": unit.strip() if unit else None
        }
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Извлекаем из JSON-LD
        if self._json_ld_recipe and 'recipeInstructions' in self._json_ld_recipe:
            instructions = self._json_ld_recipe['recipeInstructions']
            
            if isinstance(instructions, list):
                for item in instructions:
                    # HowToSection с вложенными шагами
                    if isinstance(item, dict) and item.get('@type') == 'HowToSection':
                        section_name = item.get('name', '')
                        # Добавляем название секции только если оно не начинается с "–"
                        if section_name and not section_name.startswith('–'):
                            steps.append(section_name)
                        
                        # Извлекаем шаги внутри секции
                        if 'itemListElement' in item:
                            for step in item['itemListElement']:
                                if isinstance(step, dict) and 'text' in step:
                                    step_text = step['text']
                                    # Убираем префикс "– " если есть
                                    step_text = re.sub(r'^[–-]\s*', '', step_text)
                                    steps.append(step_text)
                    
                    # HowToStep напрямую
                    elif isinstance(item, dict) and 'text' in item:
                        steps.append(item['text'])
                    
                    # Простая строка
                    elif isinstance(item, str):
                        steps.append(item)
        
        # Если ничего не нашли в JSON-LD, ищем в HTML
        if not steps:
            # Ищем по заголовкам - более строго фильтруем чтобы избежать "Preparation: 20 minutes"
            headers = self.soup.find_all(['h2', 'h3', 'h4', 'strong', 'b'])
            for header in headers:
                header_text = header.get_text(strip=True).lower()
                # Ищем точное совпадение или начало строки
                if (header_text in ['instructions', 'directions', 'method', 'steps', 'how to make'] or
                    header_text.startswith('instruction') or 
                    header_text.startswith('direction') or
                    header_text == 'method' or
                    header_text.startswith('how to ')):
                    # Ищем следующий список или параграфы после заголовка
                    next_list = header.find_next(['ol', 'ul'])
                    if next_list:
                        items = next_list.find_all('li', recursive=False)
                        # Проверяем что это не список ингредиентов (первый элемент не содержит "oz", "cup" в начале)
                        if items:
                            first_item = items[0].get_text(strip=True).lower()
                            # Если первый элемент начинается с числа и единицы измерения, это вероятно ингредиенты
                            if not re.match(r'^\d+\s*(oz|cup|tablespoon|teaspoon|pound|gram|ml|l)\b', first_item):
                                for item in items:
                                    step_text = item.get_text(strip=True)
                                    if step_text:
                                        steps.append(step_text)
                                break
        
        if steps:
            # Объединяем все шаги в одну строку, разделяя предложениями
            return ' '.join(steps)
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """
        Извлечение информации о питательности
        Ищем в HTML таблице (более полная информация) или JSON-LD
        """
        # Сначала ищем заголовок "Nutritional Facts" и таблицу после него
        headers = self.soup.find_all(['h2', 'h3', 'h4'])
        for header in headers:
            header_text = header.get_text(strip=True)
            if 'nutritional' in header_text.lower() or 'nutrition' in header_text.lower():
                # Ищем следующую таблицу
                table = header.find_next('table')
                if table:
                    rows = table.find_all('tr')
                    nutrition_parts = []
                    
                    for row in rows:
                        cells = row.find_all('td')
                        if len(cells) >= 2:
                            label = cells[0].get_text(strip=True)
                            value = cells[1].get_text(strip=True)
                            
                            # Форматируем в нужный вид
                            if label and value and label.lower() != 'nutrient':
                                nutrition_parts.append(f"{label}: {value}")
                    
                    if nutrition_parts:
                        return ', '.join(nutrition_parts)
        
        # Альтернативный поиск - таблица с классом nutrition
        nutrition_table = self.soup.find('table', class_=re.compile(r'nutrition', re.I))
        if nutrition_table:
            rows = nutrition_table.find_all('tr')
            nutrition_parts = []
            
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 2:
                    label = cells[0].get_text(strip=True)
                    value = cells[1].get_text(strip=True)
                    
                    if label and value:
                        nutrition_parts.append(f"{label}: {value}")
            
            if nutrition_parts:
                return ', '.join(nutrition_parts)
        
        # Если не нашли в таблице, пробуем JSON-LD
        if self._json_ld_recipe and 'nutrition' in self._json_ld_recipe:
            nutrition = self._json_ld_recipe['nutrition']
            
            # Простой формат - только калории
            if 'calories' in nutrition:
                calories = nutrition['calories']
                return calories
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в классе article (category-dessert)
        article = self.soup.find('article')
        if article and article.get('class'):
            classes = article['class']
            for cls in classes:
                if cls.startswith('category-'):
                    category = cls.replace('category-', '').replace('-', ' ')
                    return category.title()
        
        # Ищем в ссылках с rel="tag" и category в href
        category_links = self.soup.find_all('a', rel='tag')
        for link in category_links:
            href = link.get('href', '')
            if '/category/' in href:
                return self.clean_text(link.get_text())
        
        # Ищем в JSON-LD
        if self._json_ld_recipe and 'recipeCategory' in self._json_ld_recipe:
            category = self._json_ld_recipe['recipeCategory']
            if isinstance(category, list):
                return ', '.join(category)
            return self.clean_text(category)
        
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Извлекаем из JSON-LD
        if self._json_ld_recipe:
            time_keys = {
                'prep': 'prepTime',
                'cook': 'cookTime',
                'total': 'totalTime'
            }
            
            key = time_keys.get(time_type)
            if key and key in self._json_ld_recipe:
                iso_time = self._json_ld_recipe[key]
                return self.parse_iso_duration(iso_time)
        
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
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями
        notes_section = self.soup.find('div', class_=re.compile(r'wprm-recipe-notes', re.I))
        
        if notes_section:
            # Получаем текст, убирая заголовок
            paragraphs = notes_section.find_all('p')
            if paragraphs:
                notes_text = ' '.join([p.get_text(strip=True) for p in paragraphs])
            else:
                notes_text = notes_section.get_text(separator=' ', strip=True)
            
            # Убираем заголовки "Notes", "Key Notes:", и префиксы "–"
            notes_text = re.sub(r'^(Key\s+)?Notes?\s*:?\s*', '', notes_text, flags=re.IGNORECASE)
            notes_text = re.sub(r'^[–-]\s*', '', notes_text)
            
            return self.clean_text(notes_text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем в JSON-LD keywords
        if self._json_ld_recipe and 'keywords' in self._json_ld_recipe:
            keywords = self._json_ld_recipe['keywords']
            if isinstance(keywords, str):
                # Разделяем по запятым
                tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            elif isinstance(keywords, list):
                tags = keywords
        
        # Если не нашли в JSON-LD, собираем из категорий в классах article
        if not tags:
            article = self.soup.find('article')
            if article and article.get('class'):
                classes = article['class']
                for cls in classes:
                    if cls.startswith('category-'):
                        # Извлекаем название категории
                        category = cls.replace('category-', '').replace('-', ' ')
                        tags.append(category.title())
            
            # Также добавляем основную категорию рецепта если есть
            category = self.extract_category()
            if category and category not in tags:
                tags.append(category)
            
            # Извлекаем ключевые слова из названия блюда
            dish_name = self.extract_dish_name()
            if dish_name:
                # Разбиваем на слова и берем значимые
                words = dish_name.split()
                # Убираем стоп-слова
                stopwords = {'recipe', 'with', 'and', 'or', 'the', 'a', 'an', 'in', 'to', 'for', 'of', 'at', 'by', 'on'}
                for word in words:
                    # Очищаем от скобок и знаков препинания
                    clean_word = word.strip('()[]{},.!?"\'-').lower()
                    if clean_word and len(clean_word) > 2 and clean_word not in stopwords:
                        # Капитализируем для единообразия
                        if clean_word not in [t.lower() for t in tags]:
                            tags.append(clean_word.title())
        
        # Удаляем дубликаты сохраняя порядок
        unique_tags = []
        seen = set()
        for tag in tags:
            tag_normalized = tag.strip().lower()
            if tag_normalized and tag_normalized not in seen:
                seen.add(tag_normalized)
                unique_tags.append(tag.strip())
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в JSON-LD
        if self._json_ld_recipe and 'image' in self._json_ld_recipe:
            img = self._json_ld_recipe['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
        # 2. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if url not in urls:
                urls.append(url)
        
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
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_steps()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "nutrition_info": self.extract_nutrition_info(),
            "category": category,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/cookingitalians_com
    recipes_dir = os.path.join("preprocessed", "cookingitalians_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(CookingItaliansExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python cookingitalians_com.py")


if __name__ == "__main__":
    main()
