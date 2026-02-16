"""
Экстрактор данных рецептов для сайта teresasrecipes.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TeresasRecipesExtractor(BaseRecipeExtractor):
    """Экстрактор для teresasrecipes.com"""
    
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
        result_parts = []
        if hours > 0:
            result_parts.append(f"{hours} hour" + ("s" if hours > 1 else ""))
        if minutes > 0:
            result_parts.append(f"{minutes} minute" + ("s" if minutes > 1 else ""))
        
        return " ".join(result_parts) if result_parts else None
    
    def get_json_ld_recipe(self) -> Optional[dict]:
        """Получение данных рецепта из JSON-LD"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем, является ли это Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Приоритет: JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Альтернатива: meta теги
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффикс " - Teresa's Recipes"
            title = re.sub(r"\s*-\s*Teresa['']?s\s+Recipes\s*$", '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Ищем в заголовке страницы
        h1 = self.soup.find('h1', class_='display-4')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Приоритет: JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Альтернатива: meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Убираем стандартные фразы в конце
            desc = re.sub(r'\s+Get detailed ingredients list.*$', '', desc, flags=re.IGNORECASE)
            return self.clean_text(desc)
        
        # og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def parse_ingredient_line(self, ingredient_line: str) -> Dict[str, Optional[str]]:
        """
        Парсинг строки ингредиента из JSON-LD в структурированный формат
        
        Args:
            ingredient_line: Строка вида "Paprika, 1 teaspoon" или "Egg, 1, beaten"
            
        Returns:
            dict: {"name": "Paprika", "amount": "1", "unit": "teaspoon"}
        """
        if not ingredient_line:
            return {"name": None, "amount": None, "unit": None}
        
        # Очищаем текст
        text = self.clean_text(ingredient_line)
        
        # Разделяем по первой запятой на название и остальное
        parts = text.split(',', 1)
        
        if len(parts) == 1:
            # Только название
            return {
                "name": parts[0].strip(),
                "amount": None,
                "unit": None
            }
        
        name = parts[0].strip()
        rest = parts[1].strip()
        
        # Парсим количество и единицу из остальной части
        # Формат может быть: "1 teaspoon", "1/2 cup", "as needed", "to taste", "1, beaten"
        # "1 cup (preferably whole wheat or panko for extra crunch)"
        
        # Если это "as needed" или "to taste" - это количество без единицы
        if rest.lower() in ['as needed', 'to taste']:
            return {
                "name": name,
                "amount": rest,
                "unit": None
            }
        
        # Убираем скобки и их содержимое для корректного парсинга
        rest_clean = re.sub(r'\([^)]*\)', '', rest).strip()
        
        # Паттерн для извлечения числа/дроби и единицы измерения
        # Примеры: "1 teaspoon", "1/2 cup", "1", "1, beaten"
        # Сначала пробуем паттерн с количеством и единицей
        pattern = r'^([\d\s/]+)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)(?:,\s*(.+))?$'
        match = re.match(pattern, rest_clean)
        
        if match:
            amount_str, unit_str, extra = match.groups()
            
            amount = amount_str.strip() if amount_str else None
            unit = unit_str.strip() if unit_str else None
            
            # Если есть extra (например, что-то после запятой), добавляем к unit
            if extra:
                if unit:
                    unit = f"{unit}, {extra.strip()}"
                else:
                    unit = extra.strip()
            
            return {
                "name": name,
                "amount": amount,
                "unit": unit
            }
        
        # Если предыдущий паттерн не сработал, пробуем только число и extra
        # Для случаев типа "1, beaten"
        pattern2 = r'^([\d\s/]+)(?:,\s*(.+))?$'
        match2 = re.match(pattern2, rest_clean)
        
        if match2:
            amount_str, extra = match2.groups()
            amount = amount_str.strip() if amount_str else None
            unit = extra.strip() if extra else None
            
            return {
                "name": name,
                "amount": amount,
                "unit": unit
            }
        
        # Последний вариант - возвращаем все как amount
        return {
            "name": name,
            "amount": rest,
            "unit": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Приоритет: JSON-LD (самый структурированный источник)
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'recipeIngredient' in recipe_data:
            for ingredient_line in recipe_data['recipeIngredient']:
                parsed = self.parse_ingredient_line(ingredient_line)
                if parsed and parsed['name']:
                    # Используем "units" вместо "unit" для соответствия формату из JSON примера
                    ingredients.append({
                        "name": parsed['name'],
                        "units": parsed['unit'],
                        "amount": parsed['amount']
                    })
            
            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
        
        # Альтернатива: парсинг из HTML (dt/dd структура)
        dl = self.soup.find('dl', class_='mb-0')
        if dl:
            dts = dl.find_all('dt', class_='mb-0 mt-2')
            dds = dl.find_all('dd', class_='mb-1 text-muted')
            
            # Проходим по парам dt/dd
            for dt, dd in zip(dts, dds):
                # Извлекаем название из dt (обычно внутри <a>)
                name_elem = dt.find('a')
                if name_elem:
                    name = self.clean_text(name_elem.get_text())
                else:
                    name = self.clean_text(dt.get_text())
                
                # Извлекаем количество и единицу из dd
                amount_unit = self.clean_text(dd.get_text())
                
                # Парсим количество и единицу
                amount = None
                unit = None
                
                if amount_unit:
                    # Паттерн для разбора "1 teaspoon", "1/2 cup", "as needed"
                    pattern = r'^([\d\s/.,]+)?\s*(.+)?$'
                    match = re.match(pattern, amount_unit)
                    
                    if match:
                        amount_str, unit_str = match.groups()
                        
                        if amount_str and amount_str.strip():
                            amount = amount_str.strip()
                            unit = unit_str.strip() if unit_str else None
                        else:
                            # Весь текст - это количество (например, "as needed", "to taste")
                            amount = amount_unit
                
                ingredients.append({
                    "name": name,
                    "units": unit,
                    "amount": amount
                })
            
            return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        steps = []
        
        # Приоритет: JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        if step_text:
                            steps.append(step_text)
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        if step_text:
                            steps.append(step_text)
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            
            return ' '.join(steps) if steps else None
        
        # Альтернатива: парсинг из HTML
        instructions_section = self.soup.find('ol', class_='recipe-instructions')
        if instructions_section:
            step_items = instructions_section.find_all('li')
            
            for item in step_items:
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    steps.append(step_text)
            
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Приоритет: JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'recipeCategory' in recipe_data:
            return self.clean_text(recipe_data['recipeCategory'])
        
        # Альтернатива: meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Последний элемент обычно категория
            parts = [k.strip() for k in keywords.split(',')]
            if parts:
                # Ищем категорию (обычно "Main Course", "Dessert" и т.д.)
                for part in reversed(parts):
                    if part and part not in ['recipe', '']:
                        # Проверяем, похоже ли на категорию
                        if any(word in part.lower() for word in ['course', 'dish', 'dessert', 'appetizer', 'soup', 'salad']):
                            return self.clean_text(part)
        
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
        """Извлечение заметок и советов из секции Tips"""
        # Ищем секцию с Tips
        tips_section = self.soup.find('div', id='tips-section')
        
        if tips_section:
            tips = []
            # Извлекаем все tips-text элементы
            tips_items = tips_section.find_all('span', class_='tips-text')
            
            for item in tips_items:
                tip_text = self.clean_text(item.get_text())
                if tip_text:
                    tips.append(tip_text)
            
            return ' '.join(tips) if tips else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # На данном сайте теги не обнаружены в примерах
        # Возвращаем None
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. JSON-LD
        recipe_data = self.get_json_ld_recipe()
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
        
        # 2. og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 3. twitter:image
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
            
            # Возвращаем как строку, разделенную запятыми
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
    """Обработка всех HTML файлов в preprocessed/teresasrecipes_com"""
    import os
    
    # Определяем путь к директории с примерами
    repo_root = Path(__file__).parent.parent
    preprocessed_dir = repo_root / "preprocessed" / "teresasrecipes_com"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обработка файлов из: {preprocessed_dir}")
        process_directory(TeresasRecipesExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python teresasrecipes_com.py")


if __name__ == "__main__":
    main()
