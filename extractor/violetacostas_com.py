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
        
        # Преобразуем текстовые числа в цифры
        text_numbers = {
            'un ': '1 ', 'una ': '1 ', 'dos ': '2 ', 'tres ': '3 ',
            'cuatro ': '4 ', 'cinco ': '5 ', 'seis ': '6 '
        }
        ingredient_lower = ingredient_str.lower()
        for text_num, digit in text_numbers.items():
            if ingredient_lower.startswith(text_num):
                ingredient_str = digit + ingredient_str[len(text_num):]
                break
        
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
    
    def _extract_ingredients_from_html(self) -> Optional[str]:
        """
        Извлечение ингредиентов из HTML для страниц без JSON-LD Recipe
        
        Returns:
            JSON строка с массивом ингредиентов
        """
        ingredients_list = []
        seen_ingredients = set()
        
        # Стратегия 1: Ищем <ul> список после заголовка "Ingredientes"
        # Это самый надежный способ для страниц с правильной структурой
        headers = self.soup.find_all(['h2', 'h3', 'strong'])
        for header in headers:
            if 'ingrediente' in header.get_text().lower():
                # Нашли заголовок с ингредиентами, ищем следующий <ul> список
                ul = header.find_next('ul')
                if ul:
                    # Проверяем, что это действительно список ингредиентов, а не навигация
                    # Навигационные элементы обычно содержат стрелки или ссылки
                    li_items = ul.find_all('li')
                    
                    # Проверка: если большинство элементов содержат стрелки/навигацию, пропускаем
                    nav_count = sum(1 for li in li_items if any(char in li.get_text() for char in ['←', '→', '»', '«']))
                    if nav_count > len(li_items) / 2:
                        # Это навигация, не ингредиенты
                        continue
                    
                    # Извлекаем все <li> элементы
                    for li in li_items:
                        text = self.clean_text(li.get_text())
                        if text and len(text) < 200:  # Разумная длина для ингредиента
                            # Дополнительная проверка: пропускаем навигационные элементы
                            if any(char in text for char in ['←', '→', '»', '«']):
                                continue
                            
                            normalized = text.lower().strip()
                            if normalized not in seen_ingredients:
                                seen_ingredients.add(normalized)
                                parsed = self._parse_ingredient_string(text)
                                ingredients_list.append({
                                    "name": parsed["name"],
                                    "units": parsed["unit"],
                                    "amount": parsed["amount"]
                                })
                    
                    # Если нашли ингредиенты в списке, возвращаем результат
                    if ingredients_list:
                        return json.dumps(ingredients_list, ensure_ascii=False)
        
        # Стратегия 2: Если списка нет, ищем ингредиенты в strong тегах
        # Это для страниц, где ингредиенты выделены жирным в параграфах
        found_ingredients_section = False
        all_elements = self.soup.find_all(['h3', 'h2', 'p', 'strong'])
        
        for elem in all_elements:
            elem_text = elem.get_text().lower()
            
            # Проверяем заголовок ингредиентов
            if elem.name in ['h3', 'h2'] and 'ingrediente' in elem_text:
                found_ingredients_section = True
                continue
            
            # Если мы в секции ингредиентов
            if found_ingredients_section:
                # Если встретили новый заголовок шагов/приготовления, выходим
                if elem.name in ['h3', 'h2'] and any(word in elem_text for word in ['paso', 'preparar', 'batir', 'calentar']):
                    break
                
                # Извлекаем текст из strong тегов или из параграфов
                if elem.name == 'strong':
                    text = elem.get_text().strip()
                elif elem.name == 'p':
                    # Разбиваем параграф на части, включая plain text после strong тегов
                    # Сначала извлекаем все strong теги
                    strong_texts = [s.get_text().strip() for s in elem.find_all('strong')]
                    
                    # Также извлекаем plain text (может быть в конце параграфа)
                    # Получаем весь текст и пытаемся найти части без strong
                    full_text = elem.get_text()
                    for strong_text in strong_texts:
                        full_text = full_text.replace(strong_text, '|SPLIT|')
                    
                    # Разбиваем и добавляем все части
                    all_parts = full_text.split('|SPLIT|')
                    all_parts = [p.strip() for p in all_parts if p.strip()]
                    
                    # Объединяем strong теги и plain text части
                    potential_ingredients = strong_texts + all_parts
                    
                    for text in potential_ingredients:
                        if not text:
                            continue
                        
                        text_lower = text.lower()
                        
                        # Проверяем паттерны ингредиентов
                        ingredient_starters = ['un ', 'una ', 'dos ', 'tres ', 'cuatro ', 'cinco ']
                        ingredient_starters += [str(i) + ' ' for i in range(1, 1000)]
                        ingredient_starters += [str(i) + '/' for i in range(1, 10)]
                        
                        is_ingredient = any(text_lower.startswith(starter) for starter in ingredient_starters)
                        has_food_keywords = any(word in text_lower for word in 
                            ['huevo', 'plátano', 'yogur', 'leche', 'avena', 'copo', 
                             'clara', 'bebida', 'vegetal', 'pan', 'harina', 'gramos'])
                        
                        if is_ingredient and has_food_keywords:
                            normalized = text.lower().strip()
                            if normalized not in seen_ingredients and len(normalized) < 100:
                                seen_ingredients.add(normalized)
                                parsed = self._parse_ingredient_string(text)
                                ingredients_list.append({
                                    "name": parsed["name"],
                                    "units": parsed["unit"],
                                    "amount": parsed["amount"]
                                })
                                
                                # Ограничиваем количество
                                if len(ingredients_list) >= 10:
                                    break
                    continue
                else:
                    continue
                
                # Обработка standalone strong тегов
                text_lower = elem.get_text().lower()
                
                ingredient_starters = ['un ', 'una ', 'dos ', 'tres ', 'cuatro ', 'cinco ']
                ingredient_starters += [str(i) + ' ' for i in range(1, 1000)]
                ingredient_starters += [str(i) + '/' for i in range(1, 10)]
                
                is_ingredient = any(text_lower.startswith(starter) for starter in ingredient_starters)
                has_food_keywords = any(word in text_lower for word in 
                    ['huevo', 'plátano', 'yogur', 'leche', 'avena', 'copo', 
                     'clara', 'bebida', 'vegetal', 'pan', 'harina'])
                
                if is_ingredient and has_food_keywords:
                    text = elem.get_text().strip()
                    normalized = text.lower().strip()
                    if normalized not in seen_ingredients:
                        seen_ingredients.add(normalized)
                        parsed = self._parse_ingredient_string(text)
                        ingredients_list.append({
                            "name": parsed["name"],
                            "units": parsed["unit"],
                            "amount": parsed["amount"]
                        })
        
        if ingredients_list:
            return json.dumps(ingredients_list, ensure_ascii=False)
        
        return None
    
    def _extract_instructions_from_html(self) -> Optional[str]:
        """
        Извлечение инструкций из HTML для страниц без JSON-LD Recipe
        
        Returns:
            Строка с пошаговыми инструкциями
        """
        # Ищем h3 заголовки, которые обозначают шаги
        h3_tags = self.soup.find_all('h3')
        
        steps = []
        step_count = 0
        
        for h3 in h3_tags:
            h3_text = h3.get_text().strip().lower()
            
            # Пропускаем заголовки, которые явно не являются шагами
            skip_keywords = ['ingrediente', 'nota', 'versión', 'pixelcafe', 'receta']
            if any(keyword in h3_text for keyword in skip_keywords):
                continue
            
            # Ищем заголовки, которые похожи на шаги
            step_keywords = ['batir', 'mezclar', 'calentar', 'añadir', 'cocinar', 
                           'preparar', 'verter', 'esperar', 'dar vuelta', 'sartén']
            
            if any(keyword in h3_text for keyword in step_keywords):
                # Получаем следующий параграф с описанием шага
                next_p = h3.find_next('p')
                if next_p:
                    step_text = self.clean_text(next_p.get_text())
                    # Берем первое предложение или до определенной длины
                    sentences = step_text.split('. ')
                    if sentences:
                        step_count += 1
                        steps.append(f"{step_count}. {sentences[0].strip()}.")
                        
                        # Ограничиваем количество шагов
                        if step_count >= 5:
                            break
        
        if steps:
            return ' '.join(steps)
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов из JSON-LD или HTML
        
        Returns:
            JSON строка с массивом ингредиентов в формате [{name, amount, units}]
        """
        recipe_data = self._get_json_ld_recipe()
        
        # Сначала пробуем JSON-LD
        if recipe_data and 'recipeIngredient' in recipe_data:
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
        
        # Если JSON-LD нет, пробуем извлечь из HTML
        return self._extract_ingredients_from_html()
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления из JSON-LD или HTML"""
        recipe_data = self._get_json_ld_recipe()
        
        # Сначала пробуем JSON-LD
        if recipe_data and 'recipeInstructions' in recipe_data:
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
        
        # Если JSON-LD нет, пробуем извлечь из HTML
        return self._extract_instructions_from_html()
    
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
            # Но игнорируем те, которые содержат слишком много упоминаний ингредиентов
            if text and any(keyword in text.lower() for keyword in ['puedes sustituir', 'nota:', 'consejo:', 'tip:', 'ideal para']):
                # Проверяем, не является ли это списком ингредиентов
                # (если много strong тегов внутри, это скорее всего список ингредиентов)
                strong_tags_in_p = p.find_all('strong')
                if len(strong_tags_in_p) > 3:
                    continue
                
                # Убираем префикс "Nota:"
                text = re.sub(r'^Nota:\s*', '', text, flags=re.IGNORECASE)
                
                # Ограничиваем длину заметки
                if len(text) < 300:
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
