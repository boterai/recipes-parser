"""
Экстрактор данных рецептов для сайта violetacostas.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class VioletaCostasExtractor(BaseRecipeExtractor):
    """Экстрактор для violetacostas.com"""
    
    def _get_json_ld_recipe(self) -> Optional[dict]:
        """
        Извлекает данные Recipe из JSON-LD структуры
        
        Returns:
            Словарь с данными Recipe или None
        """
        # Ищем все script теги с type="application/ld+json"
        json_ld_scripts = self.soup.find_all('script', {'type': 'application/ld+json'})
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                # Проверяем, есть ли @graph (схема с графом)
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Recipe':
                            return item
                # Или это может быть напрямую Recipe объект
                elif data.get('@type') == 'Recipe':
                    return data
                    
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Сначала пробуем JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and recipe_data.get('name'):
            return self.clean_text(recipe_data['name'])
        
        # Альтернативно - ищем h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Или из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала пробуем из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        # JSON-LD может содержать description, но часто пустой
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and recipe_data.get('description'):
            return self.clean_text(recipe_data['description'])
        
        return None
    
    def _parse_ingredient_string(self, ingredient_str: str) -> Dict[str, Optional[str]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_str: строка вида "50 gramos almendras" или "1 limón"
            
        Returns:
            Словарь с ключами name, amount, unit
        """
        ingredient_str = self.clean_text(ingredient_str)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "50 gramos almendras", "1 cda miel", "1 limón"
        # Улучшенный паттерн, который не захватывает первый символ названия как unit
        pattern = r'^(\d+(?:[.,/]\d+)?)\s+(gramos?|g|ml|l|taza|cdas?|cucharadas?|cucharaditas?|kg)\s+(.+)$'
        
        match = re.match(pattern, ingredient_str, re.IGNORECASE)
        
        if match:
            amount = match.group(1)
            unit = match.group(2)
            name = match.group(3).strip()
            
            return {
                "name": name,
                "amount": amount,
                "unit": unit
            }
        
        # Паттерн без единицы измерения: "1 limón", "2 huevos"
        pattern2 = r'^(\d+(?:[.,/]\d+)?)\s+(.+)$'
        match2 = re.match(pattern2, ingredient_str, re.IGNORECASE)
        
        if match2:
            return {
                "name": match2.group(2).strip(),
                "amount": match2.group(1),
                "unit": None
            }
        
        # Если не смогли распарсить, возвращаем всё как название
        return {
            "name": ingredient_str,
            "amount": None,
            "unit": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из JSON-LD
        
        Returns:
            JSON строка с массивом ингредиентов в формате [{name, amount, units}]
        """
        recipe_data = self._get_json_ld_recipe()
        
        if not recipe_data or 'recipeIngredient' not in recipe_data:
            return None
        
        ingredients_list = []
        
        for ingredient_str in recipe_data['recipeIngredient']:
            parsed = self._parse_ingredient_string(ingredient_str)
            
            # Используем 'units' вместо 'unit' для совместимости с эталоном
            ingredients_list.append({
                "name": parsed["name"],
                "units": parsed["unit"],
                "amount": parsed["amount"]
            })
        
        # Возвращаем как JSON строку
        return json.dumps(ingredients_list, ensure_ascii=False)
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        recipe_data = self._get_json_ld_recipe()
        
        if not recipe_data or 'recipeInstructions' not in recipe_data:
            return None
        
        instructions = recipe_data['recipeInstructions']
        
        # Если это список объектов HowToStep
        if isinstance(instructions, list):
            steps = []
            for i, step in enumerate(instructions, 1):
                if isinstance(step, dict):
                    # Извлекаем текст из объекта HowToStep
                    text = step.get('text') or step.get('name') or ''
                    text = self.clean_text(text)
                    # Убираем начальные дефисы, пробелы и нумерацию
                    text = re.sub(r'^[-\s]+', '', text)
                    text = re.sub(r'^\d+[.)]\s*', '', text)
                    # Убираем лишние точки в конце предложений перед добавлением номера
                    text = text.rstrip('. ')
                    if text:
                        steps.append(f"{i}. {text}.")
                elif isinstance(step, str):
                    text = self.clean_text(step)
                    text = re.sub(r'^[-\s]+', '', text)
                    text = text.rstrip('. ')
                    steps.append(f"{i}. {text}.")
            
            return ' '.join(steps) if steps else None
        
        # Если это строка
        if isinstance(instructions, str):
            return self.clean_text(instructions)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории блюда"""
        # Ищем в JSON-LD Article
        json_ld_scripts = self.soup.find_all('script', {'type': 'application/ld+json'})
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list) and sections:
                                # Возвращаем первую подходящую категорию
                                for section in sections:
                                    if 'recetas' not in section.lower():
                                        return section
                                # Если все содержат "recetas", берем первую
                                return sections[0]
                            elif isinstance(sections, str):
                                return sections
                                
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # В JSON-LD violetacostas.com нет prepTime
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        # В JSON-LD violetacostas.com нет cookTime
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # В JSON-LD violetacostas.com нет totalTime
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение дополнительных заметок"""
        # Ищем раздел с заметками/советами в HTML
        # Обычно это может быть в div с классом типа "notes", "tips" и т.д.
        
        # Пробуем найти специфичные секции
        notes_selectors = [
            ('div', {'class': re.compile(r'note', re.I)}),
            ('div', {'class': re.compile(r'tip', re.I)}),
            ('p', {'class': re.compile(r'note', re.I)}),
        ]
        
        for tag, attrs in notes_selectors:
            element = self.soup.find(tag, attrs)
            if element:
                text = self.clean_text(element.get_text())
                if text and len(text) > 20:  # Минимальная длина для заметки
                    # Убираем префикс "Nota:"
                    text = re.sub(r'^Nota:\s*', '', text, flags=re.IGNORECASE)
                    return text
        
        # Альтернативно, ищем параграфы после рецепта с ключевыми словами
        all_paragraphs = self.soup.find_all('p')
        for p in all_paragraphs:
            text = self.clean_text(p.get_text())
            # Ищем параграфы, которые начинаются с подсказок
            if text and any(keyword in text.lower() for keyword in ['puedes sustituir', 'nota:', 'consejo:', 'tip:']):
                # Убираем префикс "Nota:"
                text = re.sub(r'^Nota:\s*', '', text, flags=re.IGNORECASE)
                return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Пробуем из articleSection в JSON-LD
        json_ld_scripts = self.soup.find_all('script', {'type': 'application/ld+json'})
        
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            sections = item['articleSection']
                            if isinstance(sections, list):
                                for section in sections:
                                    # Извлекаем теги из названий разделов
                                    section_lower = section.lower()
                                    if 'saludable' in section_lower or 'sana' in section_lower:
                                        tags.append('saludable')
                                    if 'vegan' in section_lower:
                                        tags.append('vegana')
                                    if 'fácil' in section_lower or 'easy' in section_lower:
                                        tags.append('fácil')
                                        
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        # Также ищем meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content'].split(',')
            for kw in keywords:
                kw = self.clean_text(kw).lower()
                if kw and kw not in tags:
                    tags.append(kw)
        
        # Возвращаем теги через запятую с пробелом
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Пробуем из JSON-LD
        recipe_data = self._get_json_ld_recipe()
        
        if recipe_data and 'image' in recipe_data:
            images = recipe_data['image']
            
            if isinstance(images, list):
                # Берем первые несколько изображений
                for img in images[:3]:
                    if isinstance(img, str):
                        urls.append(img)
                    elif isinstance(img, dict) and 'url' in img:
                        urls.append(img['url'])
            elif isinstance(images, str):
                urls.append(images)
        
        # Также пробуем из og:image
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
        
        # Возвращаем через запятую без пробелов
        return ','.join(urls) if urls else None
    
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
    """Обработка всех HTML файлов в директории preprocessed/violetacostas_com"""
    import os
    
    # Находим корень репозитория
    current_dir = Path(__file__).parent.parent
    recipes_dir = current_dir / "preprocessed" / "violetacostas_com"
    
    if recipes_dir.exists() and recipes_dir.is_dir():
        print(f"Обработка директории: {recipes_dir}")
        process_directory(VioletaCostasExtractor, str(recipes_dir))
    else:
        print(f"Директория не найдена: {recipes_dir}")
        print("Использование: python violetacostas_com.py")


if __name__ == "__main__":
    main()
