"""
Экстрактор данных рецептов для сайта vieuxbalsamique.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional
sys.path.insert(0, str(Path(__file__).parent.parent))

from extractor.base import BaseRecipeExtractor, process_directory


class VieuxBalsamiqueExtractor(BaseRecipeExtractor):
    """Экстрактор для vieuxbalsamique.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах, например "90"
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
        
        return str(total_minutes) if total_minutes > 0 else None
    
    def extract_from_json_ld(self) -> dict:
        """Извлечение данных из JSON-LD схемы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                script_content = script.string
                if not script_content:
                    continue
                
                data = json.loads(script_content.strip())
                
                # Может быть массив или объект
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                elif isinstance(data, dict):
                    # Может быть вложенная структура с @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and item.get('@type') == 'Recipe':
                                return item
                    elif data.get('@type') == 'Recipe':
                        return data
                    
            except json.JSONDecodeError:
                continue
        
        return {}
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'name' in json_data:
            return self.clean_text(json_data['name'])
        
        # Из HTML
        recipe_name = self.soup.find('h2', class_='wprm-recipe-name')
        if recipe_name:
            return self.clean_text(recipe_name.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'description' in json_data:
            return self.clean_text(json_data['description'])
        
        # Из HTML
        summary = self.soup.find('div', class_='wprm-recipe-summary')
        if summary:
            return self.clean_text(summary.get_text())
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов с количествами"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'recipeIngredient' in json_data:
            ingredients_list = json_data['recipeIngredient']
            cleaned = []
            for ing in ingredients_list:
                # Удаляем лишние пробелы
                cleaned_ing = ' '.join(ing.split()).strip()
                cleaned.append(cleaned_ing)
            
            return ', '.join(cleaned) if cleaned else None
        
        return None
    
    def extract_ingredients_names(self) -> Optional[str]:
        """Извлечение только названий ингредиентов без количеств"""
        # Получаем полный список ингредиентов
        ingredients_raw = self.extract_ingredients()
        if not ingredients_raw:
            return None
        
        lines = ingredients_raw.split(',')
        names = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Убираем количество и единицы измерения в начале
            # Паттерн: числа, дроби, единицы измерения
            cleaned = re.sub(r'^\s*\d+[\d\s/.-]*\s*(?:cuillères?\s+à\s+(?:soupe|thé|café)|tasse|ml|g|kg|lb|oz)?\s*(?:de\s+)?', '', line, flags=re.IGNORECASE)
            
            # Убираем примечания в скобках
            cleaned = re.sub(r'\([^)]+\)', '', cleaned).strip()
            
            # Убираем артикли в начале
            cleaned = re.sub(r'^(?:de\s+|d\'|l\'|le\s+|la\s+|les\s+)', '', cleaned, flags=re.IGNORECASE).strip()
            
            if cleaned and len(cleaned) > 1:
                names.append(cleaned)
        
        return ', '.join(names) if names else None
    
    def extract_step_by_step(self) -> Optional[str]:
        """Извлечение пошаговых инструкций"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'recipeInstructions' in json_data:
            instructions = json_data['recipeInstructions']
            steps = []
            
            for step in instructions:
                if isinstance(step, dict):
                    text = step.get('text', '').strip()
                    if text:
                        # Удаляем HTML теги
                        text = re.sub(r'<[^>]+>', '', text)
                        # Нормализуем пробелы
                        text = ' '.join(text.split())
                        steps.append(text)
                elif isinstance(step, str):
                    steps.append(step.strip())
            
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        if json_data and 'recipeCategory' in json_data:
            category = json_data['recipeCategory']
            if isinstance(category, list) and category:
                return self.clean_text(category[0])
            elif isinstance(category, str):
                return self.clean_text(category)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_data = self.extract_from_json_ld()
        if json_data and 'prepTime' in json_data:
            return self.parse_iso_duration(json_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_data = self.extract_from_json_ld()
        if json_data and 'cookTime' in json_data:
            return self.parse_iso_duration(json_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_data = self.extract_from_json_ld()
        if json_data and 'totalTime' in json_data:
            return self.parse_iso_duration(json_data['totalTime'])
        
        # Если нет totalTime, складываем prep_time + cook_time
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep or cook:
            prep_min = int(prep) if prep else 0
            cook_min = int(cook) if cook else 0
            total = prep_min + cook_min
            return str(total) if total > 0 else None
        
        return None

    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и примечаний"""
        # Ищем в HTML
        notes_section = self.soup.find('div', class_='wprm-recipe-notes')
        if notes_section:
            return self.clean_text(notes_section.get_text())
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        json_data = self.extract_from_json_ld()
        if json_data and 'nutrition' in json_data:
            nutrition = json_data['nutrition']
            if isinstance(nutrition, dict):
                # Формируем строку в формате: "202 kcal; 2/11/27"
                parts = []
                
                # Калории
                if 'calories' in nutrition:
                    calories = nutrition['calories']
                    # Убираем единицы, оставляем только число
                    calories_num = re.search(r'(\d+(?:\.\d+)?)', str(calories))
                    if calories_num:
                        parts.append(f"{calories_num.group(1)} kcal")
                
                # Белки/Жиры/Углеводы
                protein = None
                fat = None
                carbs = None
                
                if 'proteinContent' in nutrition:
                    protein_str = str(nutrition['proteinContent'])
                    protein_match = re.search(r'(\d+(?:\.\d+)?)', protein_str)
                    if protein_match:
                        protein = protein_match.group(1)
                
                if 'fatContent' in nutrition:
                    fat_str = str(nutrition['fatContent'])
                    fat_match = re.search(r'(\d+(?:\.\d+)?)', fat_str)
                    if fat_match:
                        fat = fat_match.group(1)
                
                if 'carbohydrateContent' in nutrition:
                    carbs_str = str(nutrition['carbohydrateContent'])
                    carbs_match = re.search(r'(\d+(?:\.\d+)?)', carbs_str)
                    if carbs_match:
                        carbs = carbs_match.group(1)
                
                if protein and fat and carbs:
                    parts.append(f"{protein}/{fat}/{carbs}")
                
                if parts:
                    return '; '.join(parts)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Из JSON-LD
        json_data = self.extract_from_json_ld()
        tags = []
        
        if json_data:
            # Кухня
            if 'recipeCuisine' in json_data:
                cuisine = json_data['recipeCuisine']
                if isinstance(cuisine, list):
                    tags.extend([c.lower() for c in cuisine])
                elif isinstance(cuisine, str):
                    tags.append(cuisine.lower())
            
            # Категория
            if 'recipeCategory' in json_data:
                category = json_data['recipeCategory']
                if isinstance(category, list):
                    tags.extend([c.lower() for c in category])
                elif isinstance(category, str):
                    tags.append(category.lower())
            
            # Ключевые слова
            if 'keywords' in json_data:
                keywords = json_data['keywords']
                if isinstance(keywords, str):
                    kw_list = [kw.strip().lower() for kw in keywords.split(',')]
                    tags.extend(kw_list)
                elif isinstance(keywords, list):
                    tags.extend([kw.lower() for kw in keywords])
        
        # Убираем дубликаты
        if tags:
            seen = set()
            unique_tags = []
            for tag in tags:
                if tag and tag not in seen:
                    seen.add(tag)
                    unique_tags.append(tag)
            
            return ', '.join(unique_tags) if unique_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Если есть @graph, ищем ImageObject и Recipe
                if '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
                        # Recipe с image
                        elif item.get('@type') == 'Recipe' and 'image' in item:
                            img = item['image']
                            if isinstance(img, str):
                                urls.append(img)
                            elif isinstance(img, dict):
                                if 'url' in img:
                                    urls.append(img['url'])
                                elif 'contentUrl' in img:
                                    urls.append(img['contentUrl'])
                            elif isinstance(img, list):
                                for img_item in img:
                                    if isinstance(img_item, str):
                                        urls.append(img_item)
                                    elif isinstance(img_item, dict):
                                        if 'url' in img_item:
                                            urls.append(img_item['url'])
                                        elif 'contentUrl' in img_item:
                                            urls.append(img_item['contentUrl'])
                
                # Если Recipe напрямую (без @graph)
                elif data.get('@type') == 'Recipe' and 'image' in data:
                    img = data['image']
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, dict):
                        if 'url' in img:
                            urls.append(img['url'])
                        elif 'contentUrl' in img:
                            urls.append(img['contentUrl'])
                    elif isinstance(img, list):
                        for img_item in img:
                            if isinstance(img_item, str):
                                urls.append(img_item)
                            elif isinstance(img_item, dict):
                                if 'url' in img_item:
                                    urls.append(img_item['url'])
                                elif 'contentUrl' in img_item:
                                    urls.append(img_item['contentUrl'])
            
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
            return ', '.join(unique_urls) if unique_urls else None
        
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
        ingredients_names = self.extract_ingredients_names()
        step_by_step = self.extract_step_by_step()
        category = self.extract_category()
        notes = self.extract_notes()
        tags = self.extract_tags()
        
        return {
            "dish_name": dish_name.lower() if dish_name else None,
            "description": description.lower() if description else None,
            "ingredients": ingredients.lower() if ingredients else None,
            "ingredients_names": ingredients_names.lower() if ingredients_names else None,
            "step_by_step": step_by_step.lower() if step_by_step else None,
            "nutrition_info": self.extract_nutrition_info(),
            "category": category.lower() if category else None,
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": notes.lower() if notes else None,
            "tags": tags,
            "image_urls": self.extract_image_urls()
        }


def main():
    """Основная функция для обработки файлов"""
    import sys
    
    if len(sys.argv) < 2:
        print("Использование: python vieuxbalsamique_com.py <путь_к_директории>")
        sys.exit(1)
    
    directory = sys.argv[1]
    process_directory(VieuxBalsamiqueExtractor, directory)


if __name__ == "__main__":
    main()
