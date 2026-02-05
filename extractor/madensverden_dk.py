"""
Экстрактор данных рецептов для сайта madensverden.dk
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MadensverdenExtractor(BaseRecipeExtractor):
    """Экстрактор для madensverden.dk"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в формат с единицами
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT210M"
            
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
        
        # Если только минуты, конвертируем в часы если >= 60
        if hours == 0 and minutes >= 60:
            hours = minutes // 60
            minutes = minutes % 60
        
        # Форматируем в текст
        if hours > 0 and minutes > 0:
            hour_text = "hour" if hours == 1 else "hours"
            return f"{hours} {hour_text} {minutes} minutes"
        elif hours > 0:
            hour_text = "hour" if hours == 1 else "hours"
            return f"{hours} {hour_text}"
        elif minutes > 0:
            return f"{minutes} minutes"
        
        return None
    
    def get_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение Recipe объекта из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем Recipe в @graph
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            return item
                
                # Если Recipe напрямую
                if data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала из JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'name' in recipe_data:
            name = recipe_data['name']
            # Убираем суффиксы типа " – pumpkin pie"
            name = re.sub(r'\s*[–-]\s*[^–-]+$', '', name)
            return self.clean_text(name)
        
        # Из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*[–-]\s*[^–-]+$', '', title)
            return self.clean_text(title)
        
        # Из h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала из JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем ингредиенты в HTML (приоритет, т.к. там есть структура)
        ingredient_items = self.soup.find_all('li', class_=lambda x: x and 'wprm-recipe-ingredient' in x)
        
        if ingredient_items:
            for item in ingredient_items:
                # Извлекаем amount, unit, name, notes из отдельных элементов
                amount_elem = item.find(class_=lambda x: x and 'amount' in x.lower())
                unit_elem = item.find(class_=lambda x: x and 'unit' in x.lower())
                name_elem = item.find(class_=lambda x: x and 'name' in x.lower())
                notes_elem = item.find(class_=lambda x: x and 'notes' in x.lower())
                
                amount = None
                unit = None
                name = None
                
                if amount_elem:
                    amount_text = self.clean_text(amount_elem.get_text())
                    # Конвертируем запятую в точку для чисел
                    amount_text = amount_text.replace(',', '.')
                    # Пробуем преобразовать в число
                    try:
                        amount = float(amount_text) if '.' in amount_text else int(amount_text)
                    except ValueError:
                        amount = amount_text if amount_text else None
                
                if unit_elem:
                    unit = self.clean_text(unit_elem.get_text())
                    unit = unit if unit else None
                
                # Если unit пустой, но есть notes, используем notes как unit
                if not unit and notes_elem:
                    notes_text = self.clean_text(notes_elem.get_text())
                    if notes_text:
                        # Убираем скобки
                        notes_text = notes_text.strip('()')
                        unit = notes_text
                
                if name_elem:
                    name = self.clean_text(name_elem.get_text())
                    # Убираем примечания в скобках
                    name = re.sub(r'\([^)]*\)', '', name)
                    name = self.clean_text(name)
                
                if name:
                    ingredients.append({
                        "name": name,
                        "units": unit,  # Используем "units" как в примере JSON
                        "amount": amount
                    })
        
        # Если не нашли в HTML, пробуем из JSON-LD
        if not ingredients:
            recipe_data = self.get_json_ld_recipe()
            if recipe_data and 'recipeIngredient' in recipe_data:
                for ing_text in recipe_data['recipeIngredient']:
                    parsed = self.parse_ingredient(ing_text)
                    if parsed:
                        ingredients.append({
                            "name": parsed['name'],
                            "units": parsed['unit'],
                            "amount": parsed['amount']
                        })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "200 g hvedemel"
            
        Returns:
            dict: {"name": "hvedemel", "amount": 200, "unit": "g"}
        """
        if not ingredient_text:
            return None
        
        text = self.clean_text(ingredient_text)
        
        # Паттерн: число + единица + название
        # Примеры: "200 g hvedemel", "2 spsk sukker"
        pattern = r'^([\d.,/-]+)?\s*([a-zæøåA-ZÆØÅ]+)?\s+(.+)$'
        
        match = re.match(pattern, text)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                amount_str = amount_str.replace(',', '.')
                try:
                    amount = float(amount_str) if '.' in amount_str else int(amount_str)
                except ValueError:
                    amount = amount_str
            
            # Очистка названия
            name = re.sub(r'\([^)]*\)', '', name)
            name = self.clean_text(name)
            
            return {
                "name": name,
                "amount": amount,
                "unit": unit if unit else None
            }
        
        # Если не совпал паттерн, возвращаем только название
        return {
            "name": text,
            "amount": None,
            "unit": None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Из JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'recipeInstructions' in recipe_data:
            for step in recipe_data['recipeInstructions']:
                if isinstance(step, dict) and 'text' in step:
                    step_text = self.clean_text(step['text'])
                    if step_text:
                        steps.append(step_text)
                elif isinstance(step, str):
                    step_text = self.clean_text(step)
                    if step_text:
                        steps.append(step_text)
        
        # Если нашли в JSON-LD, возвращаем
        if steps:
            return ' '.join(steps)
        
        # Иначе ищем в HTML
        instruction_items = self.soup.find_all('li', class_=lambda x: x and 'wprm-recipe-instruction' in x)
        
        for item in instruction_items:
            step_text = item.get_text(separator=' ', strip=True)
            step_text = self.clean_text(step_text)
            if step_text:
                steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Из JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            if isinstance(category, list):
                return self.clean_text(category[0]) if category else None
            return self.clean_text(category)
        
        # Из meta article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'prepTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['prepTime'])
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'cookTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['cookTime'])
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'totalTime' in recipe_data:
            return self.parse_iso_duration(recipe_data['totalTime'])
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем заголовок "Tips" и собираем параграфы до следующего заголовка
        # Берем первые 2 параграфа, как в примерах
        for header in self.soup.find_all(['h2', 'h3', 'h4']):
            header_text = header.get_text(strip=True).lower()
            if 'tip' in header_text:
                # Собираем параграфы после заголовка
                paragraphs = []
                next_elem = header.find_next_sibling()
                while next_elem:
                    if next_elem.name == 'p':
                        text = next_elem.get_text(separator=' ', strip=True)
                        text = self.clean_text(text)
                        if text:
                            paragraphs.append(text)
                            # Берем только первые 2 параграфа
                            if len(paragraphs) >= 2:
                                break
                    elif next_elem.name in ['h2', 'h3', 'h4']:
                        # Дошли до следующего заголовка
                        break
                    next_elem = next_elem.find_next_sibling()
                
                if paragraphs:
                    return ' '.join(paragraphs)
        
        # Также проверяем wprm-recipe-notes
        notes_div = self.soup.find('div', class_=lambda x: x and 'wprm-recipe-notes' in x and 'private' not in ' '.join(x).lower())
        if notes_div:
            text = notes_div.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Из JSON-LD можем взять категорию и кухню
        recipe_data = self.get_json_ld_recipe()
        if recipe_data:
            # Добавляем категорию
            if 'recipeCategory' in recipe_data:
                category = recipe_data['recipeCategory']
                if isinstance(category, list):
                    tags.extend([c.lower() for c in category])
                else:
                    tags.append(category.lower())
            
            # Добавляем кухню
            if 'recipeCuisine' in recipe_data:
                cuisine = recipe_data['recipeCuisine']
                if isinstance(cuisine, list):
                    tags.extend([c.lower() for c in cuisine])
                else:
                    tags.append(cuisine.lower())
        
        # Дополнительно ищем в meta keywords
        keywords = self.soup.find('meta', attrs={'name': 'keywords'})
        if keywords and keywords.get('content'):
            keyword_list = [k.strip().lower() for k in keywords['content'].split(',')]
            tags.extend(keyword_list)
        
        # Из article:tag
        article_tags = self.soup.find_all('meta', property='article:tag')
        for tag_elem in article_tags:
            if tag_elem.get('content'):
                tags.append(tag_elem['content'].lower())
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_tags = []
        for tag in tags:
            tag = self.clean_text(tag)
            if tag and tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Из JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'image' in recipe_data:
            images = recipe_data['image']
            if isinstance(images, str):
                urls.append(images)
            elif isinstance(images, list):
                urls.extend([img for img in images if isinstance(img, str)])
            elif isinstance(images, dict):
                if 'url' in images:
                    urls.append(images['url'])
                elif 'contentUrl' in images:
                    urls.append(images['contentUrl'])
        
        # Из meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        return ','.join(unique_urls) if unique_urls else None
    
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
            "instructions": self.extract_instructions(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """Обработка HTML файлов из директории preprocessed/madensverden_dk"""
    import os
    
    # Директория с примерами
    preprocessed_dir = os.path.join("preprocessed", "madensverden_dk")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(MadensverdenExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python madensverden_dk.py")


if __name__ == "__main__":
    main()
