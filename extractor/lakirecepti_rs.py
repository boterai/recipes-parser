"""
Экстрактор данных рецептов для сайта lakirecepti.rs
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class LakireceptiExtractor(BaseRecipeExtractor):
    """Экстрактор для lakirecepti.rs"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем h2 с itemprop="name"
        name_elem = self.soup.find('h2', itemprop='name')
        if name_elem:
            return self.clean_text(name_elem.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа "Laki Recepti"
            title = re.sub(r'\s*[●▫]\s*.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Описание - это первый параграф в entry-content (или его первая часть)
        entry_content = self.soup.find('div', class_='inner-post-entry')
        if entry_content:
            # Получаем прямые дочерние параграфы
            paragraphs = entry_content.find_all('p', recursive=False)
            
            # Первый параграф содержит описание
            if paragraphs:
                text = paragraphs[0].get_text(separator=' ', strip=True)
                # Очищаем текст
                text = self.clean_text(text)
                
                # Описание обычно заканчивается на первом предложении (до точки или восклицательного знака)
                # Ищем первое предложение
                sentence_end = re.search(r'[.!]\s+[А-ЯЁ]', text)
                if sentence_end:
                    # Берем до конца первого предложения
                    description = text[:sentence_end.start() + 1].strip()
                    return description
                
                # Если нет второго предложения, возвращаем весь текст
                return text
        
        return None
    
    def parse_ingredient_item(self, ingredient_text: str) -> list:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "150 gr bebi spanaća" или "ZAČINI: so, biber i susam" 
                            или "350 gr + 2 kašike ovsenog brašna"
            
        Returns:
            list: Список словарей [{"name": "...", "amount": "...", "unit": "..."}]
        """
        if not ingredient_text:
            return []
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Специальный случай: несколько количеств разделенных "+" (например "350 gr + 2 kašike ovsenog brašna")
        if '+' in text:
            # Разделяем по +
            parts = text.split('+')
            if len(parts) >= 2:
                # Извлекаем название из последней части
                last_part = parts[-1].strip()
                # Парсим последнюю часть чтобы получить название
                last_match = re.match(r'^(\d+(?:[.,/]\d+)?)\s*(paket|paketa|gr|kg|ml|l|litar|litara|kom|komad|komada|kašika|kašike|kašičica|kašičice|šolja|šolje|glavica|glavice|češanj|česnja|polovina|g)?\s*(.+?)(?:\s*\([^)]+\))?$', last_part, re.IGNORECASE)
                
                if last_match:
                    # Получаем название ингредиента
                    name = last_match.group(3).strip()
                    name = re.sub(r'\([^)]*\)', '', name)
                    name = re.sub(r'\s+', ' ', name).strip()
                    
                    # Парсим каждую часть с количеством
                    result = []
                    for part in parts:
                        part = part.strip()
                        # Если это не последняя часть, добавляем название
                        if part != parts[-1]:
                            part = part + ' ' + name
                        
                        # Парсим количество и единицу
                        match = re.match(r'^(\d+(?:[.,/]\d+)?)\s*(paket|paketa|gr|kg|ml|l|litar|litara|kom|komad|komada|kašika|kašike|kašičica|kašičice|šolja|šolje|glavica|glavice|češanj|česnja|polovina|g)?\s*(.+?)(?:\s*\([^)]+\))?$', part, re.IGNORECASE)
                        if match:
                            amount_str, unit, ing_name = match.groups()
                            
                            # Обработка количества - конвертация дробей
                            amount = amount_str.strip() if amount_str else None
                            if amount and '/' in amount:
                                frac_parts = amount.split('/')
                                if len(frac_parts) == 2:
                                    try:
                                        amount = str(float(frac_parts[0]) / float(frac_parts[1]))
                                    except:
                                        pass
                            
                            # Обработка единицы измерения
                            unit = unit.strip() if unit else None
                            
                            # Очистка названия
                            ing_name = re.sub(r'\([^)]*\)', '', ing_name)
                            ing_name = re.sub(r'\s+', ' ', ing_name).strip()
                            
                            result.append({
                                "name": ing_name,
                                "amount": amount,
                                "unit": unit
                            })
                    
                    return result if result else self._parse_single_ingredient(text)
        
        # Специальный случай: список через запятую после двоеточия (например "ZAČINI: so, biber i susam")
        if ':' in text and (',' in text or ' i ' in text):
            # Берем часть после двоеточия
            items_part = text.split(':', 1)[1].strip()
            # Разделяем по запятой и "i" (и)
            items = re.split(r',\s*|\s+i\s+', items_part)
            result = []
            for item in items:
                item = item.strip()
                if item:
                    result.append({
                        "name": item,
                        "amount": None,
                        "unit": None
                    })
            return result
        
        # Обычный случай - один ингредиент
        return self._parse_single_ingredient(text)
    
    def _parse_single_ingredient(self, text: str) -> list:
        """Парсинг одного ингредиента"""
        # Паттерн для извлечения количества, единицы и названия
        pattern = r'^(\d+(?:[.,/]\d+)?)\s*(paket|paketa|gr|kg|ml|l|litar|litara|kom|komad|komada|kašika|kašike|kašičica|kašičice|šolja|šolje|glavica|glavice|češanj|česnja|polovina|g|kašike|kašika|kašičica)?\s*(.+?)(?:\s*\([^)]+\))?$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества - конвертация дробей
            amount = amount_str.strip() if amount_str else None
            if amount and '/' in amount:
                parts = amount.split('/')
                if len(parts) == 2:
                    try:
                        amount = str(float(parts[0]) / float(parts[1]))
                    except:
                        pass
            
            # Обработка единицы измерения
            unit = unit.strip() if unit else None
            
            # Очистка названия - удаляем содержимое в скобках
            name = re.sub(r'\([^)]*\)', '', name)
            name = re.sub(r'\s+', ' ', name).strip()
            
            return [{
                "name": name,
                "amount": amount,
                "unit": unit
            }]
        
        # Если паттерн не совпал, возвращаем как есть
        return [{
            "name": text,
            "amount": None,
            "unit": None
        }]
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients_list = []
        
        # Ищем все элементы с itemprop="recipeIngredient"
        ingredient_items = self.soup.find_all('span', itemprop='recipeIngredient')
        
        for item in ingredient_items:
            ingredient_text = item.get_text(strip=True)
            ingredient_text = self.clean_text(ingredient_text)
            
            # Пропускаем пустые
            if not ingredient_text:
                continue
            
            # Парсим ингредиент (может вернуть несколько элементов)
            parsed_list = self.parse_ingredient_item(ingredient_text)
            for parsed in parsed_list:
                # Используем формат с "units" вместо "unit" для совместимости с примером
                ingredients_list.append({
                    "name": parsed["name"],
                    "units": parsed["unit"],
                    "amount": parsed["amount"]
                })
        
        return json.dumps(ingredients_list, ensure_ascii=False) if ingredients_list else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления (instructions)"""
        # Ищем div с itemprop="recipeInstructions"
        instructions_div = self.soup.find('div', itemprop='recipeInstructions')
        
        if not instructions_div:
            return None
        
        # Извлекаем все шаги из ol > li
        steps = []
        step_items = instructions_div.find_all('li')
        
        for item in step_items:
            step_text = item.get_text(separator=' ', strip=True)
            step_text = self.clean_text(step_text)
            
            if step_text:
                steps.append(step_text)
        
        # Возвращаем как одну строку, разделенную пробелами
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем span с itemprop="recipeCategory"
        category_elem = self.soup.find('span', itemprop='recipeCategory')
        category = None
        if category_elem:
            category = self.clean_text(category_elem.get_text())
        
        # Проверяем теги для более точной категоризации
        tags = self.extract_tags()
        if tags:
            tags_lower = tags.lower()
            # Проверяем на десерты/сладости
            if any(word in tags_lower for word in ['dezert', 'slatkiš', 'desert', 'torta', 'kolač']):
                return 'Dessert'
        
        # Переводим на английский для соответствия формату
        if category:
            category_lower = category.lower()
            if 'vegetarij' in category_lower or 'vegan' in category_lower:
                return 'Main Course'
            elif 'desert' in category_lower or 'slatkiš' in category_lower or 'poslasc' in category_lower:
                return 'Dessert'
            elif 'glavno jelo' in category_lower or 'main' in category_lower:
                return 'Main Course'
            return category
        
        return None
    
    def parse_time_text(self, time_text: str) -> Optional[str]:
        """
        Извлечение времени из текста и конвертация в формат "N minutes"
        
        Args:
            time_text: Строка вида "10 minuta" или "30 minuta"
            
        Returns:
            Время в формате "10 minutes"
        """
        if not time_text:
            return None
        
        # Извлекаем число из текста
        match = re.search(r'(\d+)', time_text)
        if match:
            minutes = match.group(1)
            return f"{minutes} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем time с itemprop="prepTime"
        prep_time_elem = self.soup.find('time', itemprop='prepTime')
        if prep_time_elem:
            time_text = prep_time_elem.get_text(strip=True)
            return self.parse_time_text(time_text)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем time с itemprop="cookTime"
        cook_time_elem = self.soup.find('time', itemprop='cookTime')
        if cook_time_elem:
            time_text = cook_time_elem.get_text(strip=True)
            return self.parse_time_text(time_text)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Получаем prep и cook time
        prep_time_text = None
        cook_time_text = None
        
        prep_elem = self.soup.find('time', itemprop='prepTime')
        if prep_elem:
            prep_time_text = prep_elem.get_text(strip=True)
        
        cook_elem = self.soup.find('time', itemprop='cookTime')
        if cook_elem:
            cook_time_text = cook_elem.get_text(strip=True)
        
        # Ищем totalTime в HTML
        total_time_elem = self.soup.find('time', itemprop='totalTime')
        total_time_text = None
        if total_time_elem:
            total_time_text = total_time_elem.get_text(strip=True)
        
        # Если totalTime совпадает с cookTime, значит нужно сложить prep + cook
        if total_time_text and cook_time_text and total_time_text == cook_time_text:
            # Вычисляем сумму
            if prep_time_text and cook_time_text:
                prep_match = re.search(r'(\d+)', prep_time_text)
                cook_match = re.search(r'(\d+)', cook_time_text)
                if prep_match and cook_match:
                    prep_min = int(prep_match.group(1))
                    cook_min = int(cook_match.group(1))
                    total = prep_min + cook_min
                    return f"{total} minutes"
        
        # Иначе возвращаем значение из totalTime
        if total_time_text:
            return self.parse_time_text(total_time_text)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Заметки могут быть во втором параграфе ИЛИ в остатке первого параграфа
        
        entry_content = self.soup.find('div', class_='inner-post-entry')
        if entry_content:
            # Получаем прямые дочерние параграфы
            paragraphs = entry_content.find_all('p', recursive=False)
            
            if paragraphs:
                # Проверяем первый параграф
                text = paragraphs[0].get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                
                # Ищем второе предложение (после первого предложения)
                sentence_end = re.search(r'[.!]\s+([А-ЯЁ])', text)
                if sentence_end:
                    # Заметки - это всё после первого предложения
                    notes = text[sentence_end.start() + 1:].strip()
                    if notes:
                        return notes
                
                # Если в первом параграфе нет заметок, проверяем второй
                if len(paragraphs) >= 2:
                    second_text = paragraphs[1].get_text(separator=' ', strip=True)
                    # Пропускаем если это ссылка на источник
                    if second_text and not second_text.startswith('Ovaj recept je preuzet'):
                        clean_text = self.clean_text(second_text)
                        return clean_text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Ищем div с class="post-tags"
        tags_div = self.soup.find('div', class_='post-tags')
        if tags_div:
            # Извлекаем все ссылки
            tag_links = tags_div.find_all('a', rel='tag')
            for link in tag_links:
                tag_text = link.get_text(strip=True)
                if tag_text:
                    tags_list.append(tag_text)
        
        # Возвращаем как строку через запятую с пробелом
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в JSON-LD
        scripts = self.soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Обработка @graph структуры
                if '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                urls.append(item['url'])
                            elif 'contentUrl' in item:
                                urls.append(item['contentUrl'])
                
                # BlogPosting с image
                if isinstance(data, dict) and data.get('@type') == 'BlogPosting':
                    if 'image' in data:
                        img = data['image']
                        if isinstance(img, dict) and 'url' in img:
                            urls.append(img['url'])
                        elif isinstance(img, str):
                            urls.append(img)
            
            except (json.JSONDecodeError, KeyError):
                continue
        
        # 3. Ищем изображение в рецепте
        recipe_thumb = self.soup.find('div', class_='penci-recipe-thumb')
        if recipe_thumb:
            img = recipe_thumb.find('img')
            if img and img.get('src'):
                urls.append(img['src'])
        
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
    """Обработка всех HTML файлов в директории preprocessed/lakirecepti_rs"""
    import os
    
    # Путь к директории с примерами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "preprocessed",
        "lakirecepti_rs"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(LakireceptiExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python lakirecepti_rs.py")


if __name__ == "__main__":
    main()
