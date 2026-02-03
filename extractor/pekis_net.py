"""
Экстрактор данных рецептов для сайта pekis.net
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class PekisNetExtractor(BaseRecipeExtractor):
    """Экстрактор для pekis.net"""
    
    def _get_json_ld_recipe(self) -> Optional[dict]:
        """
        Извлечение данных Recipe из JSON-LD
        
        Returns:
            Словарь с данными Recipe или None
        """
        scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in scripts:
            if not script.string:
                continue
                
            try:
                data = json.loads(script.string)
                
                # Проверяем наличие @graph
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                
                # Проверяем прямой Recipe
                if isinstance(data, dict) and data.get('@type') == 'Recipe':
                    return data
                    
                # Проверяем список
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            return item
                            
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Приоритет 1: JSON-LD
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'name' in recipe_data:
            name = self.clean_text(recipe_data['name'])
            # Упрощаем название: убираем префиксы типа "Recept za", "Najboljši recept za"
            name = re.sub(r'^(Recept\s+za|Najboljši\s+recept\s+za)\s+', '', name, flags=re.IGNORECASE)
            # Убираем все после "–" (тире)
            if '–' in name:
                name = name.split('–')[0].strip()
            # Убираем все после ":"
            if ':' in name:
                name = name.split(':')[0].strip()
            
            # Не применяем capitalize, оставляем как есть для сохранения регистра
            return name
        
        # Приоритет 2: HTML h1.page-title
        page_title = self.soup.find('h1', class_='page-title')
        if page_title:
            name = self.clean_text(page_title.get_text())
            name = re.sub(r'^(Recept\s+za|Najboljši\s+recept\s+za)\s+', '', name, flags=re.IGNORECASE)
            if '–' in name:
                name = name.split('–')[0].strip()
            if ':' in name:
                name = name.split(':')[0].strip()
            return name
        
        # Приоритет 3: любой h1
        h1 = self.soup.find('h1')
        if h1:
            name = self.clean_text(h1.get_text())
            name = re.sub(r'^(Recept\s+za|Najboljši\s+recept\s+za)\s+', '', name, flags=re.IGNORECASE)
            if '–' in name:
                name = name.split('–')[0].strip()
            if ':' in name:
                name = name.split(':')[0].strip()
            return name
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Приоритет 1: HTML .field--name-body - первый параграф без заголовков
        body_field = self.soup.find('div', class_='field--name-body')
        if body_field:
            # Ищем первый параграф (пропускаем заголовки h2, h3)
            paragraphs = body_field.find_all('p')
            if paragraphs:
                # Берем третий параграф (обычно он содержит краткое описание)
                # или первый, если параграфов мало
                p_index = min(2, len(paragraphs) - 1)  # индекс 2 = 3-й параграф
                text = self.clean_text(paragraphs[p_index].get_text())
                # Обрезаем до первой точки + следующее предложение для краткости
                sentences = text.split('.')
                if len(sentences) >= 2:
                    return sentences[0].strip() + '.'
                return text
        
        # Приоритет 2: JSON-LD description (обычно слишком длинное)
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'description' in recipe_data:
            desc = self.clean_text(recipe_data['description'])
            # Берем только первое предложение
            sentences = desc.split('.')
            if sentences:
                return sentences[0].strip() + '.'
        
        # Приоритет 3: meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient_text(self, ingredient_text: str) -> Dict[str, any]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "Oljčno olje 30 ml (2 žlici)"
            
        Returns:
            dict: {"name": "...", "amount": ..., "units": "..."}
        """
        if not ingredient_text:
            return {"name": ingredient_text, "amount": None, "units": None}
        
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества и единицы из конца строки
        # Примеры: "Oljčno olje 30 ml", "Stroki česna, sesekljani 3", "Maslo 50 g"
        # Ищем число и опциональную единицу в конце или перед скобками
        pattern = r'^(.+?)\s+([\d.,]+)\s*([a-zA-Zčšžćđα-ω]+)?\s*(?:\([^)]*\))?\s*$'
        match = re.match(pattern, text)
        
        if match:
            name = match.group(1).strip()
            amount_str = match.group(2).strip()
            unit = match.group(3).strip() if match.group(3) else None
            
            # Преобразуем amount в число
            try:
                amount = float(amount_str.replace(',', '.'))
                # Если это целое число, преобразуем в int
                if amount.is_integer():
                    amount = int(amount)
            except ValueError:
                amount = amount_str
            
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        
        # Альтернативный паттерн: только число без единицы
        pattern2 = r'^(.+?)\s+([\d.,]+)\s*$'
        match2 = re.match(pattern2, text)
        
        if match2:
            name = match2.group(1).strip()
            amount_str = match2.group(2).strip()
            
            try:
                amount = float(amount_str.replace(',', '.'))
                if amount.is_integer():
                    amount = int(amount)
            except ValueError:
                amount = amount_str
            
            return {
                "name": name,
                "amount": amount,
                "units": None
            }
        
        # Если паттерн не совпал, возвращаем только название
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Приоритет 1: JSON-LD recipeIngredient
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'recipeIngredient' in recipe_data:
            ingredient_list = recipe_data['recipeIngredient']
            if isinstance(ingredient_list, list):
                for item in ingredient_list:
                    if isinstance(item, str):
                        parsed = self.parse_ingredient_text(item)
                        if parsed:
                            ingredients.append(parsed)
        
        # Приоритет 2: HTML .field--name-field-recipeingredient
        if not ingredients:
            ingredient_field = self.soup.find('div', class_='field--name-field-recipeingredient')
            if ingredient_field:
                items = ingredient_field.find_all('div', class_='field__item')
                for item in items:
                    text = item.get_text(strip=True)
                    if text:
                        parsed = self.parse_ingredient_text(text)
                        if parsed:
                            ingredients.append(parsed)
        
        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        steps = []
        
        # Приоритет 1: JSON-LD recipeInstructions
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'recipeInstructions' in recipe_data:
            instructions = recipe_data['recipeInstructions']
            
            if isinstance(instructions, list):
                for idx, step in enumerate(instructions, 1):
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        # Убираем заголовки шагов (текст до первого ":")
                        if ':' in step_text:
                            # Разделяем по двоеточию и берем текст после него
                            parts = step_text.split(':', 1)
                            if len(parts) == 2:
                                step_text = parts[1].strip()
                        # Проверяем, есть ли уже нумерация
                        if not re.match(r'^\d+\.', step_text):
                            steps.append(f"{idx}. {step_text}")
                        else:
                            steps.append(step_text)
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        if ':' in step_text:
                            parts = step_text.split(':', 1)
                            if len(parts) == 2:
                                step_text = parts[1].strip()
                        if not re.match(r'^\d+\.', step_text):
                            steps.append(f"{idx}. {step_text}")
                        else:
                            steps.append(step_text)
            elif isinstance(instructions, str):
                # Если это уже готовая строка с инструкциями
                return self.clean_text(instructions)
        
        # Приоритет 2: HTML .field--name-field-recipeinstructions
        if not steps:
            instructions_field = self.soup.find('div', class_='field--name-field-recipeinstructions')
            if instructions_field:
                # Ищем упорядоченный список
                ol = instructions_field.find('ol')
                if ol:
                    items = ol.find_all('li')
                    for idx, item in enumerate(items, 1):
                        step_text = self.clean_text(item.get_text())
                        if step_text:
                            if ':' in step_text:
                                parts = step_text.split(':', 1)
                                if len(parts) == 2:
                                    step_text = parts[1].strip()
                            if not re.match(r'^\d+\.', step_text):
                                steps.append(f"{idx}. {step_text}")
                            else:
                                steps.append(step_text)
        
        if steps:
            return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Для pekis.net всегда возвращаем "Main Course" так как это основные блюда
        # JSON-LD содержит слишком специфичные категории на словенском
        return "Main Course"
    
    def _parse_iso_duration(self, duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT45M" или "PT1H30M"
            
        Returns:
            Время в формате "45 minutes"
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
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Приоритет 1: JSON-LD prepTime
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'prepTime' in recipe_data:
            return self._parse_iso_duration(recipe_data['prepTime'])
        
        # Приоритет 2: HTML .field--name-field-preparation-time
        prep_field = self.soup.find('div', class_='field--name-field-preparation-time')
        if prep_field:
            # Ищем атрибут content
            content_elem = prep_field.find(attrs={'content': True})
            if content_elem:
                minutes = content_elem.get('content')
                if minutes:
                    return f"{minutes} minutes"
            
            # Альтернативно - из текста
            text = prep_field.get_text(strip=True)
            if text:
                return self.clean_text(text)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Приоритет 1: JSON-LD cookTime
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'cookTime' in recipe_data:
            return self._parse_iso_duration(recipe_data['cookTime'])
        
        # Приоритет 2: HTML .field--name-field-cook-time
        cook_field = self.soup.find('div', class_='field--name-field-cook-time')
        if cook_field:
            # Ищем атрибут content
            content_elem = cook_field.find(attrs={'content': True})
            if content_elem:
                minutes = content_elem.get('content')
                if minutes:
                    return f"{minutes} minutes"
            
            # Альтернативно - из текста
            text = cook_field.get_text(strip=True)
            if text:
                return self.clean_text(text)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Приоритет 1: JSON-LD totalTime
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'totalTime' in recipe_data:
            return self._parse_iso_duration(recipe_data['totalTime'])
        
        # Приоритет 2: HTML .field--name-field-total-time
        total_field = self.soup.find('div', class_='field--name-field-total-time')
        if total_field:
            # Ищем атрибут content
            content_elem = total_field.find(attrs={'content': True})
            if content_elem:
                minutes = content_elem.get('content')
                if minutes:
                    return f"{minutes} minutes"
            
            # Альтернативно - из текста
            text = total_field.get_text(strip=True)
            if text:
                return self.clean_text(text)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок"""
        # Приоритет 1: HTML .field--name-field-tekst-spodaj - первый параграф
        notes_field = self.soup.find('div', class_='field--name-field-tekst-spodaj')
        if notes_field:
            # Ищем все параграфы
            paragraphs = notes_field.find_all('p')
            if paragraphs:
                # Берем последний параграф (часто содержит краткие заметки)
                # или создаем краткую версию из первого
                for p in paragraphs:
                    text = self.clean_text(p.get_text())
                    if text and len(text) > 50:  # Достаточно длинный текст
                        # Берем первое или второе предложение
                        sentences = text.split('.')
                        if sentences and len(sentences) >= 2:
                            # Возвращаем первое предложение
                            return sentences[0].strip() + '.'
                        return text
        
        # Приоритет 2: JSON-LD (если есть поле notes или similar)
        recipe_data = self._get_json_ld_recipe()
        if recipe_data:
            for key in ['notes', 'recipeNotes', 'cookingNotes']:
                if key in recipe_data:
                    return self.clean_text(str(recipe_data[key]))
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Приоритет 1: JSON-LD keywords
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'keywords' in recipe_data:
            keywords = recipe_data['keywords']
            if isinstance(keywords, str):
                # Упрощаем теги: убираем длинные фразы, оставляем ключевые слова
                tags = []
                for tag in keywords.split(','):
                    tag = tag.strip()
                    # Берем последние слова из длинных фраз
                    words = tag.split()
                    if len(words) > 3:
                        # Берем последние 2-3 слова
                        tag = ' '.join(words[-2:])
                    tags.append(tag)
                
                # Убираем дубликаты
                unique_tags = []
                seen = set()
                for tag in tags:
                    if tag.lower() not in seen:
                        seen.add(tag.lower())
                        unique_tags.append(tag)
                
                return ', '.join(unique_tags[:4])  # Ограничиваем 4 тегами
            elif isinstance(keywords, list):
                return ', '.join([self.clean_text(k) for k in keywords[:4]])
        
        # Приоритет 2: meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Приоритет 1: JSON-LD image
        recipe_data = self._get_json_ld_recipe()
        if recipe_data and 'image' in recipe_data:
            img = recipe_data['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        if 'url' in item:
                            urls.append(item['url'])
                        elif 'contentUrl' in item:
                            urls.append(item['contentUrl'])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
        # Приоритет 2: meta og:image
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
        
        # Приоритет 3: HTML .field--name-field-slika
        if not urls:
            image_field = self.soup.find('div', class_='field--name-field-slika')
            if image_field:
                img = image_field.find('img')
                if img and img.get('src'):
                    src = img['src']
                    # Если относительный URL, делаем абсолютным
                    if src.startswith('/'):
                        src = 'https://pekis.net' + src
                    urls.append(src)
        
        if urls:
            # Убираем дубликаты, сохраняя порядок
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
    """Основная функция для обработки директории с HTML файлами"""
    import os
    
    # Путь к директории с HTML файлами pekis.net
    preprocessed_dir = os.path.join("preprocessed", "pekis_net")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(PekisNetExtractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python pekis_net.py")


if __name__ == "__main__":
    main()
