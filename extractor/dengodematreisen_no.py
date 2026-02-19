"""
Экстрактор данных рецептов для сайта dengodematreisen.no
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class DengodematreisenNoExtractor(BaseRecipeExtractor):
    """Экстрактор для dengodematreisen.no"""
    
    def _get_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение Recipe из JSON-LD структурированных данных"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Проверка на @graph структуру
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            return item
                
                # Проверка на массив
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                
                # Проверка на прямой Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Fallback: meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s*\|\s*.*$', '', title)
            return self.clean_text(title)
        
        # Fallback: h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            if desc and desc.strip():
                return self.clean_text(desc)
        
        # Fallback: meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Fallback: og:description  
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients_list = []
        
        # Сначала пробуем извлечь из HTML с детализированной структурой
        ingredient_items = self.soup.find_all('li', class_='wprm-recipe-ingredient')
        
        if ingredient_items:
            for item in ingredient_items:
                # Извлекаем компоненты отдельно
                amount_elem = item.find('span', class_='wprm-recipe-ingredient-amount')
                unit_elem = item.find('span', class_='wprm-recipe-ingredient-unit')
                name_elem = item.find('span', class_='wprm-recipe-ingredient-name')
                
                # Обработка amount
                amount = None
                if amount_elem:
                    amount_text = amount_elem.get_text(strip=True)
                    if amount_text:
                        # Обработка дробей
                        amount_text = amount_text.replace('½', '0.5').replace('¼', '0.25').replace('¾', '0.75')
                        amount_text = amount_text.replace('⅓', '0.33').replace('⅔', '0.67').replace('⅛', '0.125')
                        try:
                            # Попытка конвертировать в число
                            if '/' in amount_text:
                                parts = amount_text.split()
                                total = 0
                                for part in parts:
                                    if '/' in part:
                                        num, denom = part.split('/')
                                        total += float(num) / float(denom)
                                    else:
                                        total += float(part)
                                amount = total
                            else:
                                amount = float(amount_text.replace(',', '.'))
                        except ValueError:
                            amount = amount_text
                
                # Обработка unit
                unit = None
                if unit_elem:
                    unit = unit_elem.get_text(strip=True)
                
                # Обработка name
                name = None
                if name_elem:
                    name = self.clean_text(name_elem.get_text())
                
                if name:
                    ingredients_list.append({
                        "name": name,
                        "amount": amount,
                        "units": unit  # Используем "units" для соответствия эталону
                    })
        
        # Fallback: JSON-LD
        if not ingredients_list:
            recipe_data = self._get_json_ld_recipe()
            if recipe_data and 'recipeIngredient' in recipe_data:
                for ingredient_str in recipe_data['recipeIngredient']:
                    # Парсим строку ингредиента
                    parsed = self._parse_ingredient_string(ingredient_str)
                    if parsed:
                        ingredients_list.append(parsed)
        
        return json.dumps(ingredients_list, ensure_ascii=False) if ingredients_list else None
    
    def _parse_ingredient_string(self, ingredient_str: str) -> Optional[Dict]:
        """
        Парсинг строки ингредиента из JSON-LD
        Пример: "6 dl soyamelk" -> {"name": "soyamelk", "amount": 6, "units": "dl"}
        """
        if not ingredient_str:
            return None
        
        text = self.clean_text(ingredient_str)
        
        # Паттерн: количество [единица] название
        # Пример: "6 dl soyamelk", "100 gr pistasjkjerner", "5 ss akasiehonning"
        pattern = r'^([\d\s/.,]+)?\s*(dl|gr|ss|ts|kg|g|ml|l|stk|plate|plater)?\s*(.+?)(?:\s*\([^)]*\))?$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
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
                amount = total
            else:
                try:
                    amount = float(amount_str.replace(',', '.'))
                except ValueError:
                    amount = amount_str
        
        # Очистка названия
        name = name.strip() if name else None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit.strip() if unit else None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        instructions_parts = []
        
        # JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        if step_text:
                            instructions_parts.append(step_text)
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        if step_text:
                            instructions_parts.append(step_text)
            elif isinstance(instructions, str):
                return self.clean_text(instructions)
        
        # Fallback: HTML
        if not instructions_parts:
            instruction_items = self.soup.find_all('li', class_='wprm-recipe-instruction')
            for item in instruction_items:
                text_div = item.find('div', class_='wprm-recipe-instruction-text')
                if text_div:
                    step_text = self.clean_text(text_div.get_text())
                    if step_text:
                        instructions_parts.append(step_text)
        
        return ' '.join(instructions_parts) if instructions_parts else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            if isinstance(category, list):
                return ', '.join(category)
            elif isinstance(category, str):
                return self.clean_text(category)
        
        # Fallback: meta article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'prepTime' in recipe_data:
            return self._parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'cookTime' in recipe_data:
            return self._parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'totalTime' in recipe_data:
            return self._parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def _parse_iso_duration(self, duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в читаемом формате, например "1 hour 30 minutes"
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
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Ищем в HTML блок с заметками/советами
        notes_div = self.soup.find('div', class_='wprm-recipe-notes')
        if notes_div:
            # Извлекаем текст, пропуская заголовок
            paragraphs = notes_div.find_all('p')
            if paragraphs:
                notes_text = ' '.join([self.clean_text(p.get_text()) for p in paragraphs])
                return notes_text if notes_text else None
            
            # Если нет параграфов, берем весь текст
            text = notes_div.get_text(separator=' ', strip=True)
            # Убираем возможный заголовок "Notater" или "Notes"
            text = re.sub(r'^(Notater|Notes)\s*:?\s*', '', text, flags=re.IGNORECASE)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # JSON-LD keywords
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Ищем в @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'keywords' in item:
                            keywords = item['keywords']
                            if isinstance(keywords, list):
                                tags_list.extend([str(k).lower() for k in keywords])
                            elif isinstance(keywords, str):
                                tags_list.extend([t.strip().lower() for t in keywords.split(',')])
                            break
                
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        if tags_list:
            # Удаляем дубликаты, сохраняя порядок
            seen = set()
            unique_tags = []
            for tag in tags_list:
                # Очистка от HTML entities (например, &amp;)
                tag = tag.replace('&amp;', '&').strip()
                if tag and tag not in seen and len(tag) > 1:
                    seen.add(tag)
                    unique_tags.append(tag)
            
            return ', '.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
        # Fallback: meta og:image
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
        
        # Удаляем дубликаты
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
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Путь к директории с предобработанными файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "preprocessed",
        "dengodematreisen_no"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(DengodematreisenNoExtractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python dengodematreisen_no.py")


if __name__ == "__main__":
    main()
