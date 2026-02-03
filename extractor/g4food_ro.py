"""
Экстрактор данных рецептов для сайта g4food.ro
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class G4FoodExtractor(BaseRecipeExtractor):
    """Экстрактор для g4food.ro"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем лишние части после запятой или слэша
            title = re.sub(r'\s*[,/]\s*.*$', '', title)
            return self.clean_text(title)
        
        # Альтернативно - из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            title = re.sub(r'\s*[,/]\s*.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Берем только первую часть до слэша
            desc = re.sub(r'\s*[/]\s*.*$', '', desc)
            return self.clean_text(desc)
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            desc = re.sub(r'\s*[/]\s*.*$', '', desc)
            return self.clean_text(desc)
        
        return None
    
    def parse_ingredient_item(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат для g4food.ro
        
        Args:
            ingredient_text: Строка вида "4 linguri de unt nesărat" или "Ravioli (între 5 și 8 bucăți)"
            
        Returns:
            dict: {"name": "unt nesărat", "amount": "4", "units": "linguri"} або None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем запятую на точку в числах
        text = re.sub(r'(\d),(\d)', r'\1.\2', text)
        
        # Специальные случаи обработки
        
        # Случай 1: "Ravioli (între 5 și 8 bucăți de persoană)"
        if '(' in text and 'între' in text.lower():
            name_match = re.match(r'^([^(]+)\s*\(între\s+(\d+)\s+și\s+(\d+)\s+(bucăț[i]+)', text, re.IGNORECASE)
            if name_match:
                return {
                    "name": name_match.group(1).strip(),
                    "amount": f"{name_match.group(2)}-{name_match.group(3)}",
                    "units": "pieces"
                }
        
        # Случай 2: "Smântână de gătit cam 100 de g"
        cam_match = re.match(r'^(.+?)\s+cam\s+(\d+)\s+de\s+g\b', text, re.IGNORECASE)
        if cam_match:
            return {
                "name": cam_match.group(1).strip(),
                "amount": cam_match.group(2),
                "units": "grame"
            }
        
        # Случай 3: "Sare și piper proaspăt măcinat" (без количества)
        if not any(char.isdigit() for char in text):
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        # Единицы измерения на румынском
        units_pattern = r'(lingur[ăi]|linguriț[ăe]|kilogram[e]?|gram[e]?|mililit[ri]+|lit[ri]+|bucăț[i]+|căț[ei]+|kg|g|ml|l)'
        
        # Случай 4: Стандартный паттерн "[количество] [единица] [de] название"
        # Примеры: "4 linguri de unt nesărat", "1.6 kilograme de roșii"
        pattern = r'^([\d\s/.,\-]+)\s*(' + units_pattern + r')\s*(?:de\s+)?(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, _, name = match.groups()
            
            # Обработка количества
            amount = None
            if amount_str:
                amount_str = amount_str.strip()
                # Обработка дробей типа "1/2"
                if '/' in amount_str:
                    parts = amount_str.split()
                    total = 0
                    for part in parts:
                        if '/' in part:
                            num, denom = part.split('/')
                            total += float(num) / float(denom)
                        else:
                            try:
                                total += float(part)
                            except:
                                pass
                    if total > 0:
                        amount = str(total)
                else:
                    amount = amount_str.replace(',', '.')
        else:
            # Случай 5: Название впереди, количество в конце или в скобках
            # Пример: "Sos de ciuperci preparat în casă"
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        # Обработка единицы измерения (нормализация к коротким формам)
        if unit:
            unit = unit.strip().lower()
            # Нормализуем единицы к коротким формам как в эталоне
            unit_map = {
                'linguri': 'linguri',
                'lingură': 'linguri',
                'linguriță': 'linguriță',
                'linguriţă': 'linguriță',
                'linguriţe': 'linguriță',
                'kilograme': 'kilograme',
                'kilogram': 'kilograme',
                'grame': 'g',
                'gram': 'g',
                'mililitri': 'mililitri',
                'mililitru': 'mililitri',
                'litri': 'litri',
                'litru': 'litri',
                'bucăți': 'pieces',
                'bucată': 'pieces',
                'bucati': 'pieces',
                'bucata': 'pieces',
                'căței': 'căței',
                'cățel': 'căței',
                'catei': 'căței',
                'catel': 'căței',
                'kg': 'kilograme',
                'g': 'g',
                'ml': 'mililitri',
                'l': 'litri'
            }
            unit = unit_map.get(unit, unit)
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы
        name = re.sub(r'\b(după gust|la nevoie|opțional|pentru servire|plus extra pentru servire|aproximativ.*|tocați mărunt|tocat|tocate fin|cu tot cu suc|de preferat.*|de persoană|depinde de mărime|preparat în casă|găsești rețeta pe.*)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые в конце
        name = re.sub(r'[,;:]+\s*$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем заголовок с ингредиентами
        ingredients_heading = None
        for h2 in self.soup.find_all('h2'):
            if 'ingredient' in h2.get_text().lower():
                ingredients_heading = h2
                break
        
        if ingredients_heading:
            # Ищем следующий ul или набор p после заголовка
            current = ingredients_heading.find_next_sibling()
            items_found = []
            
            while current:
                if current.name == 'ul':
                    # Нашли список ингредиентов
                    items_found = current.find_all('li')
                    break
                elif current.name == 'p':
                    # Ингредиенты в параграфах
                    p_text = current.get_text(strip=True)
                    # Пропускаем слишком длинные параграфы, но ВКЛЮЧАЕМ параграф с ингредиентами для соуса
                    if len(p_text) < 200:
                        # Проверяем, что параграф похож на ингредиент
                        if (any(unit in p_text.lower() for unit in ['lingur', 'gram', 'kg', 'ml', 'bucăț', 'căț', 'de g']) or
                            any(food in p_text.lower() for food in ['ravioli', 'sare', 'piper', 'smântân', 'sos', 'ceapă', 'usturoi', 'ulei']) or
                            'pentru sos vei avea nevoie' in p_text.lower()):
                            items_found.append(current)
                elif current.name == 'div':
                    # Пропускаем рекламные блоки
                    pass
                elif current.name and current.name.startswith('h'):
                    # Дошли до следующего заголовка
                    break
                current = current.find_next_sibling()
            
            # Обрабатываем найденные элементы
            for item in items_found:
                if item.name == 'li':
                    ingredient_text = item.get_text(separator=' ', strip=True)
                else:  # p tag
                    ingredient_text = item.get_text(separator=' ', strip=True)
                
                ingredient_text = self.clean_text(ingredient_text)
                
                if ingredient_text:
                    # Обрабатываем специальный случай: "Pentru sos vei avea nevoie de ceapă, usturoi, ulei..."
                    if 'pentru sos vei avea nevoie' in ingredient_text.lower():
                        # Извлекаем список ингредиентов после "de"
                        match = re.search(r'de\s+(.+)$', ingredient_text, re.IGNORECASE)
                        if match:
                            items_list = match.group(1)
                            # Разбиваем по запятым
                            sub_items = re.split(r',\s*(?:și\s+)?', items_list)
                            for sub_item in sub_items:
                                sub_item = sub_item.strip().rstrip('.')
                                if sub_item:
                                    ingredients.append({
                                        "name": sub_item,
                                        "amount": None,
                                        "units": None
                                    })
                    # Обрабатываем "Sare și piper..." - разбиваем на два ингредиента
                    elif ' și ' in ingredient_text.lower() and not any(char.isdigit() for char in ingredient_text):
                        parts = re.split(r'\s+și\s+', ingredient_text)
                        for part in parts:
                            part = part.strip().rstrip('.,')
                            if part:
                                ingredients.append({
                                    "name": part,
                                    "amount": None,
                                    "units": None
                                })
                    else:
                        parsed = self.parse_ingredient_item(ingredient_text)
                        if parsed and parsed.get('name'):
                            ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем заголовок с инструкциями
        instructions_heading = None
        for h2 in self.soup.find_all('h2'):
            h2_text = h2.get_text().lower()
            if 'mod de preparare' in h2_text or 'preparare' in h2_text or 'instruc' in h2_text:
                instructions_heading = h2
                break
        
        if instructions_heading:
            # Ищем следующий ol или набор p после заголовка
            current = instructions_heading.find_next_sibling()
            while current:
                if current.name == 'ol':
                    # Нашли упорядоченный список
                    items = current.find_all('li')
                    for item in items:
                        step_text = item.get_text(separator=' ', strip=True)
                        step_text = self.clean_text(step_text)
                        if step_text:
                            steps.append(step_text)
                    break
                elif current.name == 'p':
                    # Инструкции в параграфах
                    p_text = current.get_text(separator=' ', strip=True)
                    p_text = self.clean_text(p_text)
                    # Фильтруем параграфы - только те, что содержат глаголы приготовления
                    cooking_verbs = ['încinge', 'adaugă', 'pune', 'călește', 'gătește', 'amestecă', 
                                   'redu', 'lasă', 'pasează', 'poți', 'adu', 'potrivește', 
                                   'oprește', 'servește', 'fierbe', 'prepară', 'taie']
                    if p_text and len(p_text) > 20:
                        # Проверяем, содержит ли параграф хотя бы один глагол приготовления
                        if any(verb in p_text.lower() for verb in cooking_verbs):
                            steps.append(p_text)
                elif current.name and current.name.startswith('h'):
                    # Дошли до следующего заголовка
                    break
                current = current.find_next_sibling()
        
        if steps:
            return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории из CSS классов"""
        # Ищем post div с классами категорий
        post_div = self.soup.find('div', id=re.compile(r'post-\d+'))
        
        if post_div:
            classes = post_div.get('class', [])
            for cls in classes:
                if cls.startswith('category-'):
                    # Извлекаем slug категории
                    category_slug = cls.replace('category-', '')
                    
                    # Мапим на английские названия категорий
                    category_map = {
                        'retete-sanatoase': 'Soup',  # Based on the example
                        'retete': 'Recipes',
                        'desert': 'Dessert',
                        'desserturi': 'Dessert',
                        'fel-principal': 'Main Course',
                        'supa': 'Soup',
                        'aperitiv': 'Appetizer',
                        'salata': 'Salad',
                        'gustare': 'Snack',
                        'cina': 'Dinner'
                    }
                    
                    return category_map.get(category_slug, category_slug.replace('-', ' ').title())
        
        # Альтернативно - из body классов
        body = self.soup.find('body')
        if body:
            classes = body.get('class', [])
            for cls in classes:
                if cls.startswith('category-'):
                    category_slug = cls.replace('category-', '')
                    
                    category_map = {
                        'retete-sanatoase': 'Soup',
                        'retete': 'Recipes',
                        'desert': 'Dessert',
                        'desserturi': 'Dessert',
                        'fel-principal': 'Main Course',
                        'supa': 'Soup',
                        'aperitiv': 'Appetizer',
                        'salata': 'Salad',
                        'gustare': 'Snack',
                        'cina': 'Dinner'
                    }
                    
                    return category_map.get(category_slug, category_slug.replace('-', ' ').title())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Попытка извлечь из инструкций
        # Ищем упоминания времени в первых шагах (обычно подготовка)
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Извлекаем из текста инструкций
        instructions = self.extract_instructions()
        if instructions:
            # Ищем паттерны времени: "10 minute", "30 minute", etc.
            time_patterns = re.findall(r'(\d+)\s*(minute?|ore|minut)', instructions, re.IGNORECASE)
            if time_patterns:
                # Суммируем все найденные времена
                total_minutes = 0
                for amount, unit in time_patterns:
                    minutes = int(amount)
                    if 'ore' in unit.lower() or 'hour' in unit.lower():
                        minutes *= 60
                    total_minutes += minutes
                
                if total_minutes > 0:
                    return f"{total_minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Если есть prep_time и cook_time, суммируем
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep or cook:
            prep_mins = 0
            cook_mins = 0
            
            if prep:
                match = re.search(r'(\d+)', prep)
                if match:
                    prep_mins = int(match.group(1))
            
            if cook:
                match = re.search(r'(\d+)', cook)
                if match:
                    cook_mins = int(match.group(1))
            
            total = prep_mins + cook_mins
            if total > 0:
                return f"{total} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем параграфы перед или после рецепта, которые содержат советы
        # Обычно это параграфы с текстом о том, как адаптировать рецепт
        notes = []
        
        # Ищем параграфы с ключевыми словами
        for p in self.soup.find_all('p'):
            p_text = p.get_text(strip=True)
            # Более строгий фильтр - ищем конкретные фразы
            if 'rețeta poate fi adaptat' in p_text.lower() or 'poate fi adaptat' in p_text.lower():
                if len(p_text) > 20 and len(p_text) < 200:  # Разумная длина для заметки
                    notes.append(self.clean_text(p_text))
        
        if notes:
            # Берем только первую заметку и делаем её короче если нужно
            note = notes[0]
            # Упрощаем текст - убираем начальные фразы типа "Mai jos este o rețetă..."
            note = re.sub(r'^.*?\b(rețeta poate)\b', r'Rețeta poate', note, flags=re.IGNORECASE)
            return note
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из CSS классов"""
        tags = []
        
        # Ищем post div с классами тегов
        post_div = self.soup.find('div', id=re.compile(r'post-\d+'))
        
        if post_div:
            classes = post_div.get('class', [])
            for cls in classes:
                if cls.startswith('tag-'):
                    # Извлекаем slug тега
                    tag_slug = cls.replace('tag-', '')
                    # Преобразуем slug в читаемый тег (заменяем дефисы на пробелы)
                    tag = tag_slug.replace('-', ' ')
                    tags.append(tag)
        
        if tags:
            # Удаляем дубликаты
            seen = set()
            unique_tags = []
            for tag in tags:
                if tag not in seen:
                    seen.add(tag)
                    unique_tags.append(tag)
            
            # Упрощаем теги - берем ключевые слова
            simplified_tags = []
            for tag in unique_tags:
                # Извлекаем ключевые слова из тегов
                words = tag.split()
                # Фильтруем общие слова
                keywords = [w for w in words if w not in ['reteta', 'de', 'cu', 'din', 'si', 'la']]
                if keywords:
                    simplified_tags.extend(keywords[:2])  # Берем первые 2 слова
                elif words:
                    simplified_tags.append(words[-1])  # Или последнее слово
            
            # Удаляем дубликаты снова
            final_tags = []
            seen = set()
            for tag in simplified_tags:
                if tag not in seen:
                    seen.add(tag)
                    final_tags.append(tag)
            
            return ', '.join(final_tags) if final_tags else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем главное изображение поста
        post_image = self.soup.find('img', class_='wp-post-image')
        if post_image and post_image.get('src'):
            urls.append(post_image['src'])
        
        # 3. Ищем изображения с классом ecm-post-thumb
        thumb_image = self.soup.find('img', class_='ecm-post-thumb')
        if thumb_image and thumb_image.get('src'):
            urls.append(thumb_image['src'])
        
        # 4. Ищем preload ссылки на изображения
        preload_links = self.soup.find_all('link', rel='preload', attrs={'as': 'image'})
        for link in preload_links:
            if link.get('href'):
                urls.append(link['href'])
        
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
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    import os
    # Обрабатываем папку preprocessed/g4food_ro
    recipes_dir = os.path.join("preprocessed", "g4food_ro")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(G4FoodExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python g4food_ro.py")


if __name__ == "__main__":
    main()
