"""
Экстрактор данных рецептов для сайта jonathangarnier.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class JonathanGarnierExtractor(BaseRecipeExtractor):
    """Экстрактор для jonathangarnier.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверка Article (blog recipes)
                if isinstance(data, dict):
                    if data.get('@type') == 'Article' and 'headline' in data:
                        return self.clean_text(data['headline'])
                    # Проверка Product (product recipes)
                    if data.get('@type') == 'Product' and 'name' in data:
                        return self.clean_text(data['name'])
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Альтернативно - из meta тегов
        meta_title = self.soup.find('meta', property='og:title')
        if meta_title and meta_title.get('content'):
            return self.clean_text(meta_title['content'])
        
        # Из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            return self.clean_text(title_tag.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Проверяем, является ли это blog recipe (Article)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    # Для Article проверяем наличие реального description
                    if data.get('@type') == 'Article':
                        desc_field = data.get('description', '')
                        # Если description пустой или содержит "Servings:", это не настоящее описание
                        if desc_field and not desc_field.startswith('Servings:'):
                            return self.clean_text(desc_field)
                        else:
                            # Для blog recipes без описания возвращаем None
                            return None
                    # Для Product
                    if data.get('@type') == 'Product' and 'description' in data:
                        desc = self.clean_text(data['description'])
                        if desc:
                            return desc
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Только если не нашли JSON-LD, ищем в meta тегах
        # Но избегаем meta description, если он содержит "Servings:" (это blog recipe)
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = self.clean_text(meta_desc['content'])
            if desc and not desc.startswith('Servings:'):
                return desc
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = self.clean_text(og_desc['content'])
            if desc and not desc.startswith('Servings:'):
                return desc
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Сначала пробуем извлечь из JSON-LD (blog recipes)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Article':
                    article_body = data.get('articleBody', '')
                    if article_body:
                        # Парсим структурированные ингредиенты из articleBody
                        ingredients = self._parse_ingredients_from_article_body(article_body)
                        if ingredients:
                            return json.dumps(ingredients, ensure_ascii=False)
                            
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Для продуктов: ищем в accordion с Ingredients
        accordion_divs = self.soup.find_all('details', class_='accordion')
        
        for accordion in accordion_divs:
            summary = accordion.find('summary')
            if not summary:
                continue
            
            # Проверяем, содержит ли заголовок "Ingredients"
            heading = summary.get_text(strip=True)
            if 'Ingredient' in heading:
                # Извлекаем содержимое
                content_div = accordion.find('div', class_='accordion__content')
                if content_div:
                    # Ищем текст с ингредиентами
                    rich_text = content_div.find('div', class_='metafield-rich_text_field')
                    if rich_text:
                        # Извлекаем текст ингредиентов
                        ingredients_text = rich_text.get_text(separator=' ', strip=True)
                        # Удаляем "Ingredients:" и "Contains:" части
                        ingredients_text = re.sub(r'^Ingredients:\s*', '', ingredients_text, flags=re.IGNORECASE)
                        # Разделяем по "Contains:" и берем первую часть
                        if 'Contains:' in ingredients_text:
                            ingredients_text = ingredients_text.split('Contains:')[0]
                        
                        # Парсим ингредиенты из списка через запятую
                        ingredients = self._parse_ingredients_from_text(ingredients_text)
                        if ingredients:
                            return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def _parse_ingredients_from_article_body(self, article_body: str) -> list:
        """
        Парсинг ингредиентов из articleBody (blog recipes)
        Ищет паттерн: "количество единица название"
        """
        ingredients = []
        
        # Разбиваем на строки
        lines = article_body.split('\n')
        
        # Отслеживаем секции
        in_ingredient_section = False
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Проверяем секции
            if 'FRESH HOMEMADE PASTA' in line or 'The stuffing' in line or 'Mushroom stew' in line or 'The garnish' in line:
                in_ingredient_section = True
                continue
            
            if line == 'Preparation' or (line.isupper() and 'PREPARATION' in line):
                in_ingredient_section = False
                continue
            
            # Пропускаем заголовки других секций
            if line.startswith('Servings:') or line.startswith('Cooking:'):
                continue
            
            # Если мы в секции ингредиентов
            if in_ingredient_section:
                # Паттерн для строки ингредиента: "количество единица название"
                # Примеры: "1l (4 cups) flour", "4 whole eggs", "60 ml (4 tbsp) olive oil"
                pattern = r'^([\d/.½¼¾⅓⅔]+)\s*([a-zA-Z]+)?\s*(?:\([^)]*\))?\s*(.+)'
                match = re.match(pattern, line, re.IGNORECASE)
                
                if match:
                    amount_str, unit, name = match.groups()
                    
                    # Обработка количества
                    amount = None
                    if amount_str:
                        amount_str = amount_str.strip()
                        # Обработка дробей
                        if '/' in amount_str:
                            parts = amount_str.split('/')
                            if len(parts) == 2:
                                try:
                                    amount = float(parts[0]) / float(parts[1])
                                except:
                                    amount = amount_str
                        # Обработка Unicode дробей
                        elif '½' in amount_str:
                            amount = 0.5
                        elif '¼' in amount_str:
                            amount = 0.25
                        elif '¾' in amount_str:
                            amount = 0.75
                        elif '⅓' in amount_str:
                            amount = 0.33
                        elif '⅔' in amount_str:
                            amount = 0.67
                        else:
                            try:
                                amount = float(amount_str)
                            except:
                                amount = amount_str
                    
                    # Очистка названия от дополнительных деталей
                    if name:
                        # Удаляем описания в скобках
                        name = re.sub(r'\([^)]*\)', '', name)
                        # Удаляем фразы "to taste", "as needed", "optional"
                        name = re.sub(r',?\s*(to taste|as needed|or more|if needed|optional|for garnish|chopped|grated|finely chopped|cubed|removed|leaves removed|barbecued or grilled).*$', '', name, flags=re.IGNORECASE)
                        name = name.strip().strip(',').strip()
                    
                    if name and len(name) >= 2:
                        ingredients.append({
                            "name": name,
                            "amount": amount,
                            "units": unit if unit else None
                        })
        
        return ingredients
    
    def _parse_ingredients_from_text(self, text: str) -> list:
        """
        Парсинг ингредиентов из текста, разделенного запятыми (product recipes)
        Извлекает только основные ингредиенты без деталей в скобках
        """
        ingredients = []
        
        # Очищаем текст
        text = self.clean_text(text)
        
        # Удаляем префикс "Ingredients:"
        text = re.sub(r'^Ingredients:\s*', '', text, flags=re.IGNORECASE)
        
        # Первый проход: разделяем по запятым, но учитываем скобки
        # Используем более сложный паттерн для разделения
        parts = []
        current_part = ""
        paren_depth = 0
        bracket_depth = 0
        
        for char in text:
            if char == '(':
                paren_depth += 1
            elif char == ')':
                paren_depth -= 1
            elif char == '[':
                bracket_depth += 1
            elif char == ']':
                bracket_depth -= 1
            elif char == ',' and paren_depth == 0 and bracket_depth == 0:
                if current_part.strip():
                    parts.append(current_part.strip())
                current_part = ""
                continue
            
            current_part += char
        
        # Добавляем последний элемент
        if current_part.strip():
            parts.append(current_part.strip())
        
        # Второй проход: очищаем каждую часть
        for part in parts:
            # Удаляем детали в скобках и квадратных скобках
            clean_name = re.sub(r'\([^)]*\)', '', part)
            clean_name = re.sub(r'\[[^\]]*\]', '', clean_name)
            clean_name = clean_name.strip()
            
            # Пропускаем "Contains" секцию и все после нее
            if clean_name.lower().startswith('contains'):
                break
            
            if clean_name and len(clean_name) >= 2:
                # Для product recipes обычно нет структурированных данных amount/unit
                ingredients.append({
                    "name": clean_name,
                    "amount": None,
                    "units": None
                })
        
        return ingredients
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions = []
        
        # Сначала пробуем извлечь из JSON-LD (blog recipes)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Article':
                    article_body = data.get('articleBody', '')
                    if article_body:
                        # Извлекаем только секции Preparation
                        instructions = self._extract_preparation_from_article(article_body)
                        if instructions:
                            return ' '.join(instructions)
                            
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Для продуктов: ищем в accordion с Direction
        accordion_divs = self.soup.find_all('details', class_='accordion')
        
        for accordion in accordion_divs:
            summary = accordion.find('summary')
            if not summary:
                continue
            
            # Проверяем, содержит ли заголовок "Direction"
            heading = summary.get_text(strip=True)
            if 'Direction' in heading:
                # Извлекаем содержимое
                content_div = accordion.find('div', class_='accordion__content')
                if content_div:
                    # Ищем текст с инструкциями
                    rich_text = content_div.find('div', class_='metafield-rich_text_field')
                    if rich_text:
                        # Извлекаем все параграфы
                        paragraphs = rich_text.find_all('p')
                        for p in paragraphs:
                            text = p.get_text(separator=' ', strip=True)
                            text = self.clean_text(text)
                            if text:
                                instructions.append(text)
        
        return ' '.join(instructions) if instructions else None
    
    def _extract_preparation_from_article(self, article_body: str) -> list:
        """
        Извлечение инструкций из articleBody (blog recipes)
        """
        instructions = []
        lines = article_body.split('\n')
        
        in_preparation_section = False
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Проверяем начало секции Preparation
            if line == 'Preparation' or 'Preparation' in line:
                in_preparation_section = True
                continue
            
            # Пропускаем заголовки других секций (они обычно в верхнем регистре или заканчиваются на ":")
            if line.isupper() and len(line.split()) <= 4:
                in_preparation_section = False
                continue
            
            if line.endswith(':') and len(line.split()) <= 5:
                in_preparation_section = False
                continue
            
            # Если мы в секции Preparation и это не ингредиент
            if in_preparation_section:
                # Пропускаем строки, которые похожи на ингредиенты
                if re.match(r'^[\d/.]+\s*[a-zA-Z]*\s*\(', line):
                    continue
                
                # Добавляем как инструкцию
                instructions.append(self.clean_text(line))
        
        return instructions
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в JSON-LD (для продуктов)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Product':
                    if 'category' in data:
                        return self.clean_text(data['category'])
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в JSON-LD articleBody (blog recipes)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Article':
                    article_body = data.get('articleBody', '')
                    # Ищем "Preparation: XX minutes"
                    prep_match = re.search(r'Preparation:\s*(\d+\s*minutes?)', article_body, re.IGNORECASE)
                    if prep_match:
                        return self.clean_text(prep_match.group(1))
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в JSON-LD articleBody (blog recipes)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Article':
                    article_body = data.get('articleBody', '')
                    # Ищем "Cooking: XX minutes"
                    cook_match = re.search(r'Cooking:\s*(\d+\s*minutes?)', article_body, re.IGNORECASE)
                    if cook_match:
                        return self.clean_text(cook_match.group(1))
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Для продуктов: извлекаем из инструкций (например, "35 to 40 minutes")
        instructions = self.extract_instructions()
        if instructions:
            # Ищем паттерны времени в инструкциях
            time_match = re.search(r'(\d+\s*to\s*\d+\s*minutes?)', instructions, re.IGNORECASE)
            if time_match:
                return self.clean_text(time_match.group(1))
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в JSON-LD articleBody (blog recipes)
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and data.get('@type') == 'Article':
                    article_body = data.get('articleBody', '')
                    
                    # Пытаемся вычислить из prep + cook
                    prep_match = re.search(r'Preparation:\s*(\d+)\s*minutes?', article_body, re.IGNORECASE)
                    cook_match = re.search(r'Cooking:\s*(\d+)\s*minutes?', article_body, re.IGNORECASE)
                    
                    if prep_match and cook_match:
                        prep_mins = int(prep_match.group(1))
                        cook_mins = int(cook_match.group(1))
                        total_mins = prep_mins + cook_mins
                        return f"{total_mins} minutes"
                        
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем в accordion с Conservation
        accordion_divs = self.soup.find_all('details', class_='accordion')
        
        for accordion in accordion_divs:
            summary = accordion.find('summary')
            if not summary:
                continue
            
            # Проверяем, содержит ли заголовок "Conservation"
            heading = summary.get_text(strip=True)
            if 'Conservation' in heading:
                # Извлекаем содержимое
                content_div = accordion.find('div', class_='accordion__content')
                if content_div:
                    # Ищем текст с заметками
                    multi_line = content_div.find('span', class_='metafield-multi_line_text_field')
                    if multi_line:
                        notes = multi_line.get_text(strip=True)
                        notes = self.clean_text(notes)
                        if notes:
                            return notes
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Для blog recipes - ищем в div с классом article-tags
        article_tags_div = self.soup.find('div', class_='article-tags')
        if article_tags_div:
            # Ищем все ссылки с классом badge
            tag_links = article_tags_div.find_all('a', class_='badge')
            if tag_links:
                tags = [self.clean_text(link.get_text()) for link in tag_links]
                tags = [tag for tag in tags if tag]
                # Удаляем дубликаты, сохраняя порядок
                seen = set()
                unique_tags = []
                for tag in tags:
                    if tag not in seen:
                        seen.add(tag)
                        unique_tags.append(tag)
                if unique_tags:
                    return ','.join(unique_tags)
        
        return None
    
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
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict):
                    # Product
                    if data.get('@type') == 'Product' and 'image' in data:
                        img = data['image']
                        if isinstance(img, str):
                            urls.append(img)
                        elif isinstance(img, list):
                            urls.extend([i for i in img if isinstance(i, str)])
                        elif isinstance(img, dict) and 'url' in img:
                            urls.append(img['url'])
                            
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
        instructions = self.extract_instructions()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
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
    
    # Определяем путь к директории с preprocessed данными
    repo_root = Path(__file__).parent.parent
    preprocessed_dir = repo_root / "preprocessed" / "jonathangarnier_com"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        process_directory(JonathanGarnierExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python jonathangarnier_com.py")


if __name__ == "__main__":
    main()
