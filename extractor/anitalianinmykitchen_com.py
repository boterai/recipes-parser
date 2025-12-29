"""
Экстрактор данных рецептов для сайта anitalianinmykitchen.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class AnItalianInMyKitchenExtractor(BaseRecipeExtractor):
    """Экстрактор для anitalianinmykitchen.com"""
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в читаемый формат
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M" или "PT145M"
            
        Returns:
            Время в читаемом формате, например "2 hours 25 minutes"
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
        
        # Если только минуты и их больше 60, конвертируем в часы
        if hours == 0 and minutes >= 60:
            hours = minutes // 60
            minutes = minutes % 60
        
        # Формируем строку
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour" + ("s" if hours > 1 else ""))
        if minutes > 0:
            parts.append(f"{minutes} minute" + ("s" if minutes > 1 else ""))
        
        return ' '.join(parts) if parts else None
    
    def get_recipe_json_ld(self) -> Optional[dict]:
        """Извлечение данных рецепта из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            if not script.string:
                continue
            
            try:
                data = json.loads(script.string)
                
                # Проверяем @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            return item
                
                # Проверяем прямой Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Fallback к meta тегу
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'description' in recipe_data:
            return self.clean_text(recipe_data['description'])
        
        # Fallback к meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient_string(self, ingredient_str: str) -> dict:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_str: Строка вида "2 cups lukewarm water"
            
        Returns:
            dict: {"name": "Water", "amount": "2", "units": "cups"}
        """
        if not ingredient_str:
            return {"name": None, "amount": None, "units": None}
        
        text = self.clean_text(ingredient_str)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "2 cups water", "1½ tablespoons yeast", "1 pinch sugar", "2-3 tablespoons oil"
        pattern = r'^([\d\s/.,½¼¾⅓⅔⅛⅜⅝⅞\-]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?)?s?\s+(.+)'
        
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
            # Заменяем дроби
            amount_str = amount_str.replace('½', '.5').replace('¼', '.25').replace('¾', '.75')
            amount_str = amount_str.replace('⅓', '.33').replace('⅔', '.67')
            amount_str = amount_str.replace('⅛', '.125').replace('⅜', '.375').replace('⅝', '.625').replace('⅞', '.875')
            
            # Сохраняем диапазоны как есть (например, "2-3")
            # Обработка дробей типа "1/2" или "1 1/2"
            if '/' in amount_str and '-' not in amount_str:
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
                # Для диапазонов и обычных чисел оставляем как есть
                amount = amount_str.replace(',', '.').strip()
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия - убираем лишние пробелы
        name = name.strip()
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredients_list = []
            for ingredient_str in recipe_data['recipeIngredient']:
                parsed = self.parse_ingredient_string(ingredient_str)
                if parsed and parsed['name']:
                    ingredients_list.append(parsed)
            
            if ingredients_list:
                return json.dumps(ingredients_list, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                for item in instructions:
                    if isinstance(item, dict):
                        # HowToSection с itemListElement
                        if item.get('@type') == 'HowToSection' and 'itemListElement' in item:
                            for step in item['itemListElement']:
                                if isinstance(step, dict) and 'text' in step:
                                    steps.append(self.clean_text(step['text']))
                        # Прямой HowToStep
                        elif item.get('@type') == 'HowToStep' and 'text' in item:
                            steps.append(self.clean_text(item['text']))
                    elif isinstance(item, str):
                        steps.append(self.clean_text(item))
            
            if steps:
                return ' '.join(steps)
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'nutrition' in recipe_data:
            nutrition = recipe_data['nutrition']
            
            # Извлекаем калории
            calories = nutrition.get('calories', '')
            
            # Извлекаем БЖУ
            protein = nutrition.get('proteinContent', '')
            fat = nutrition.get('fatContent', '')
            carbs = nutrition.get('carbohydrateContent', '')
            
            # Формируем полную строку с дополнительной информацией
            parts = []
            
            if calories:
                parts.append(f"Calories: {calories}")
            if carbs:
                parts.append(f"Carbohydrates: {carbs}")
            if protein:
                parts.append(f"Protein: {protein}")
            if fat:
                parts.append(f"Fat: {fat}")
            
            # Добавляем дополнительные параметры
            if 'saturatedFatContent' in nutrition:
                parts.append(f"Saturated Fat: {nutrition['saturatedFatContent']}")
            if 'unsaturatedFatContent' in nutrition:
                poly_fat = nutrition.get('unsaturatedFatContent', '')
                # Разделяем на полиненасыщенные и мононенасыщенные если возможно
                if poly_fat:
                    parts.append(f"Polyunsaturated Fat: {poly_fat}")
            if 'sodiumContent' in nutrition:
                parts.append(f"Sodium: {nutrition['sodiumContent']}")
            if 'potassiumContent' in nutrition:
                parts.append(f"Potassium: {nutrition['potassiumContent']}")
            if 'fiberContent' in nutrition:
                parts.append(f"Fiber: {nutrition['fiberContent']}")
            if 'sugarContent' in nutrition:
                parts.append(f"Sugar: {nutrition['sugarContent']}")
            if 'vitaminCContent' in nutrition:
                parts.append(f"Vitamin C: {nutrition['vitaminCContent']}")
            if 'calciumContent' in nutrition:
                parts.append(f"Calcium: {nutrition['calciumContent']}")
            if 'ironContent' in nutrition:
                parts.append(f"Iron: {nutrition['ironContent']}")
            if 'cholesterolContent' in nutrition:
                parts.append(f"Cholesterol: {nutrition['cholesterolContent']}")
            if 'vitaminAContent' in nutrition:
                parts.append(f"Vitamin A: {nutrition['vitaminAContent']}")
            
            if parts:
                return ' | '.join(parts)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            categories = recipe_data['recipeCategory']
            if isinstance(categories, list):
                return ', '.join(categories)
            return str(categories)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'prepTime' in recipe_data:
            iso_time = recipe_data['prepTime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'cookTime' in recipe_data:
            iso_time = recipe_data['cookTime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'totalTime' in recipe_data:
            iso_time = recipe_data['totalTime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Сначала пробуем найти "Recipe Tip" заголовок и следующий параграф
        h2_tip = self.soup.find('h2', string=lambda x: x and 'Recipe Tip' in x)
        if h2_tip:
            next_p = h2_tip.find_next_sibling('p')
            if next_p:
                text = self.clean_text(next_p.get_text())
                if text:
                    return text
        
        # Если нет tip заголовка, ищем в wprm-recipe-notes
        notes_section = self.soup.find(class_='wprm-recipe-notes')
        if notes_section:
            # Извлекаем span элементы с текстом, пропуская рекламу
            spans = notes_section.find_all('span', style=lambda x: x and 'display: block' in x)
            texts = []
            for span in spans:
                text = self.clean_text(span.get_text())
                # Пропускаем заголовки
                if text and text not in ['Recipe Notes', 'Notes']:
                    texts.append(text)
            
            if texts:
                return ' '.join(texts)
            
            # Если нет span, берем весь текст
            text = self.clean_text(notes_section.get_text())
            # Убираем заголовок "Notes" или "Recipe Notes"
            text = re.sub(r'^(Notes|Recipe Notes)\s*:?\s*', '', text, flags=re.I)
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        recipe_data = self.get_recipe_json_ld()
        
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Разделяем по запятой и очищаем
                tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                return ', '.join(tags)
            elif isinstance(keywords, list):
                return ', '.join(keywords)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        recipe_data = self.get_recipe_json_ld()
        
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
        
        # Дополнительно проверяем meta теги
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
        
        # Убираем дубликаты
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
            "nutrition_info": self.extract_nutrition_info(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/anitalianinmykitchen_com
    preprocessed_dir = os.path.join("preprocessed", "anitalianinmykitchen_com")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(AnItalianInMyKitchenExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python anitalianinmykitchen_com.py")


if __name__ == "__main__":
    main()
