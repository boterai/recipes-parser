"""
Экстрактор данных рецептов для сайта kotanyi.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KotanyiExtractor(BaseRecipeExtractor):
    """Экстрактор для kotanyi.com"""
    
    def extract_json_ld_recipe(self) -> Optional[dict]:
        """Извлечение данных Recipe из JSON-LD"""
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return None
    
    def parse_iso_duration(self, duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в виде строки, например "90 minutes"
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
        
        if total_minutes > 0:
            return f"{total_minutes} minutes"
        
        return None
    
    def parse_ingredient_string(self, ingredient_str: str) -> Optional[Dict[str, any]]:
        """
        Парсинг строки ингредиента из JSON-LD формата kotanyi.com
        
        Формат: "2kosa Vlečenega testa za štrudlje" или "200g Zamrznjenega graha" или " Voda"
        
        Args:
            ingredient_str: Строка ингредиента
            
        Returns:
            dict: {"name": "...", "amount": ..., "unit": "..."} или None
        """
        if not ingredient_str:
            return None
        
        ingredient_str = ingredient_str.strip()
        
        # Паттерн: начало строки может содержать число (целое или дробное), затем единицу, затем название
        # Примеры: "2kosa ...", "0.5žličke ...", "200g ...", "Voda" (без количества)
        # Если строка не начинается с числа, это просто название ингредиента
        
        # Сначала проверяем, начинается ли строка с числа
        number_match = re.match(r'^(\d+(?:\.\d+)?)', ingredient_str)
        
        if not number_match:
            # Нет числа в начале - вся строка это название
            return {
                "name": self.clean_text(ingredient_str),
                "amount": None,
                "unit": None
            }
        
        # Есть число в начале
        amount_str = number_match.group(1)
        rest = ingredient_str[len(amount_str):]
        
        # Теперь извлекаем единицу измерения (буквы сразу после числа)
        unit_match = re.match(r'^([a-zA-Zščćžđ]+)\s+(.+)$', rest, re.UNICODE)
        
        if not unit_match:
            # Нет единицы после числа - возможно число это просто часть названия
            return {
                "name": self.clean_text(ingredient_str),
                "amount": None,
                "unit": None
            }
        
        unit = unit_match.group(1)
        name = unit_match.group(2)
        
        # Обработка количества
        amount = None
        if amount_str:
            try:
                # Пробуем конвертировать в число
                amount_num = float(amount_str)
                # Если это целое число, сохраняем как int
                if amount_num.is_integer():
                    amount = int(amount_num)
                else:
                    amount = amount_num
            except ValueError:
                amount = None
        
        # Очистка названия
        name = self.clean_text(name) if name else None
        
        # Очистка единицы
        unit = unit.strip() if unit else None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        recipe_data = self.extract_json_ld_recipe()
        
        if recipe_data and 'name' in recipe_data:
            return self.clean_text(recipe_data['name'])
        
        # Fallback: из мета-тега title
        title_tag = self.soup.find('title')
        if title_tag:
            return self.clean_text(title_tag.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        recipe_data = self.extract_json_ld_recipe()
        
        if recipe_data and 'description' in recipe_data:
            desc = recipe_data['description']
            if desc:
                # Берем только первое предложение для краткости
                # Ищем первую точку, восклицательный или вопросительный знак
                import re
                match = re.search(r'^[^.!?]+[.!?]', desc)
                if match:
                    return self.clean_text(match.group(0))
                # Если не нашли знак препинания, возвращаем весь текст
                return self.clean_text(desc)
        
        # Fallback: из мета-тега description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        recipe_data = self.extract_json_ld_recipe()
        
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
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
        recipe_data = self.extract_json_ld_recipe()
        
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
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
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        recipe_data = self.extract_json_ld_recipe()
        
        if recipe_data and 'recipeCategory' in recipe_data:
            category = recipe_data['recipeCategory']
            # Маппинг на английский только для основных категорий
            category_mapping = {
                'Glavna jed': 'Main Course',
                'Predjed': 'Appetizer',
                'Priloga': 'Side Dish',
                'Juha': 'Soup',
                'Solata': 'Salad',
                'Sladica': 'Dessert',
                # Prigrizek оставляем как есть - в референсе он есть
            }
            return category_mapping.get(category, category)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        recipe_data = self.extract_json_ld_recipe()
        
        if recipe_data and 'prepTime' in recipe_data and recipe_data['prepTime']:
            return self.parse_iso_duration(recipe_data['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        recipe_data = self.extract_json_ld_recipe()
        
        if recipe_data and 'cookTime' in recipe_data and recipe_data['cookTime']:
            return self.parse_iso_duration(recipe_data['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        recipe_data = self.extract_json_ld_recipe()
        
        if recipe_data and 'totalTime' in recipe_data and recipe_data['totalTime']:
            return self.parse_iso_duration(recipe_data['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов из HTML"""
        # Ищем секцию с заголовком "Namig:" (Tip: в словенском)
        # Структура: <h3>Namig: </h3><p>текст заметки</p>
        
        # Ищем заголовок
        headings = self.soup.find_all(['h3', 'h4', 'h5'])
        
        for heading in headings:
            heading_text = heading.get_text(strip=True)
            if 'Namig' in heading_text or 'Tip' in heading_text or 'Tipp' in heading_text:
                # Ищем следующий параграф
                next_p = heading.find_next('p')
                if next_p:
                    note_text = self.clean_text(next_p.get_text())
                    return note_text if note_text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из HTML (emoji-префиксы) и JSON-LD keywords"""
        tags_list = []
        
        # 1. Извлекаем теги с emoji из HTML
        # В HTML теги обозначены emoji: 🥔Krompir, 🥛Mlečni Izdelki, и т.д.
        all_text = self.soup.get_text()
        
        # Паттерн: emoji followed by capitalized text (category tags)
        emoji_pattern = r'([🍽🍲🍴🌍🥦🥔🥛🔔👪🍱🎂💘🥩🐟🥗🍞🌾🍖🧀🥜🥕🍅🍆🌶🍇🍊🥐🧁🍪])([A-ZŠČĆŽĐ][a-zščćžđA-ZŠČĆŽĐ\s]+?)(?=[🍽🍲🍴🌍🥦🥔🥛🔔👪🍱🎂💘🥩🐟🥗🍞🌾🍖🧀🥜🥕🍅🍆🌶🍇🍊🥐🧁🍪]|Sestavine|$)'
        
        emoji_matches = re.findall(emoji_pattern, all_text, re.UNICODE)
        
        # Добавляем теги с emoji (исключаем некоторые общие категории вроде "Mednarodna kuhinja")
        exclude_tags = {'Glavna jed', 'Predjed', 'Priloga'}  # Категории блюд - уже есть в category
        
        for emoji, tag in emoji_matches:
            tag = tag.strip()
            if tag and tag not in exclude_tags:
                tags_list.append(tag)
        
        # 2. Дополнительно извлекаем теги из JSON-LD keywords (теги идут в конце списка)
        recipe_data = self.extract_json_ld_recipe()
        
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords'].split(',')
            
            # Теги в keywords обычно начинаются с категорий типа "Glavna jed" и идут до конца
            # Ищем первое вхождение категории
            start_idx = None
            for i, keyword in enumerate(keywords):
                keyword = keyword.strip()
                if keyword in ['Glavna jed', 'Predjed', 'Priloga', 'Juha', 'Solata', 'Sladica', 'Prigrizek']:
                    start_idx = i
                    break
            
            # Если нашли начало тегов, берем все остальные (кроме категорий блюд)
            if start_idx is not None:
                for keyword in keywords[start_idx:]:
                    keyword = keyword.strip()
                    if keyword and keyword not in exclude_tags and keyword not in tags_list:
                        # Исключаем "Mednarodna kuhinja" - слишком общий тег
                        if keyword != 'Mednarodna kuhinja':
                            tags_list.append(keyword)
        
        # Убираем дубликаты, сохраняя порядок
        unique_tags = []
        seen = set()
        for tag in tags_list:
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen.add(tag_lower)
                unique_tags.append(tag)
        
        if unique_tags:
            return ', '.join(unique_tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Из JSON-LD
        recipe_data = self.extract_json_ld_recipe()
        
        if recipe_data and 'image' in recipe_data:
            images = recipe_data['image']
            if isinstance(images, list):
                urls.extend([img for img in images if isinstance(img, str)])
            elif isinstance(images, str):
                urls.append(images)
        
        # 2. Из мета-тегов
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
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
            "instructions": self.extract_instructions(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """Точка входа для обработки примеров kotanyi.com"""
    import os
    
    # Обрабатываем папку preprocessed/kotanyi_com
    preprocessed_dir = os.path.join("preprocessed", "kotanyi_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка примеров из: {preprocessed_dir}")
        process_directory(KotanyiExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python kotanyi_com.py")


if __name__ == "__main__":
    main()
