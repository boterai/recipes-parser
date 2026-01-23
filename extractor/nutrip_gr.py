"""
Экстрактор данных рецептов для сайта nutrip.gr
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class NutripGrExtractor(BaseRecipeExtractor):
    """Экстрактор для nutrip.gr"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                
                # Очистка JSON от возможных проблем (trailing commas и т.д.)
                json_str = script.string.strip()
                
                # Удаляем trailing commas перед закрывающими скобками
                json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
                
                data = json.loads(json_str)
                
                # Данные могут быть списком или словарем
                if isinstance(data, list):
                    # Ищем Recipe в списке
                    for item in data:
                        if isinstance(item, dict):
                            item_type = item.get('@type', '')
                            if isinstance(item_type, list) and 'Recipe' in item_type:
                                return item
                            elif item_type == 'Recipe':
                                return item
                elif isinstance(data, dict):
                    item_type = data.get('@type', '')
                    if isinstance(item_type, list) and 'Recipe' in item_type:
                        return data
                    elif item_type == 'Recipe':
                        return data
                        
            except (json.JSONDecodeError, KeyError) as e:
                continue
        
        return None
    
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
        
        # Если минут больше 60 и нет часов, конвертируем в часы и минуты
        if minutes >= 60 and hours == 0:
            hours = minutes // 60
            minutes = minutes % 60
        
        # Форматируем результат
        parts = []
        if hours > 0:
            # Используем греческие слова для времени
            if hours == 1:
                parts.append(f"{hours} ώρα")
            else:
                parts.append(f"{hours} ώρες")
        if minutes > 0:
            if minutes == 1:
                parts.append(f"{minutes} λεπτό")
            else:
                parts.append(f"{minutes} λεπτά")
        
        return ' '.join(parts) if parts else None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Альтернатива - из заголовка страницы
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Из meta title
        title = self.soup.find('title')
        if title:
            text = title.get_text()
            # Убираем суффиксы
            text = re.sub(r'\s*\|.*$', '', text)
            text = re.sub(r'\s+Recipe.*$', '', text, flags=re.IGNORECASE)
            return self.clean_text(text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Извлекаем из meta description (там обычно 2 предложения)
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Разбиваем на предложения
            sentences = re.split(r'[.!;]\s+', desc)
            # Берем ПЕРВОЕ предложение
            if sentences and sentences[0].strip():
                first_sentence = sentences[0].strip()
                if not first_sentence.endswith(('.', '!', ';', '…', '...')):
                    first_sentence += '.'
                return self.clean_text(first_sentence)
        
        # Альтернатива - из JSON-LD description (но это обычно длинный текст)
        json_ld = self._get_json_ld_data()
        if json_ld and 'description' in json_ld:
            desc = json_ld['description']
            # Извлекаем только текст до первого URL или до "Μπορεί επίσης"
            desc = re.split(r'https?://|Μπορεί επίσης', desc)[0]
            # Извлекаем первое предложение
            sentences = re.split(r'[.!;]\s+', desc)
            if sentences:
                first_sentence = sentences[0].strip()
                if first_sentence and not first_sentence.endswith(('.', '!', ';', '…', '...')):
                    first_sentence += '.'
                return self.clean_text(first_sentence) if first_sentence else None
        
        return None
    
    def parse_ingredient_nutrip(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат для nutrip.gr
        Формат: "1  τμχ. σπιτικό bagel" или "60  γρ.  τυρί κρέμα χαμηλό σε λιπαρά"
        
        Args:
            ingredient_text: Строка с ингредиентом
            
        Returns:
            dict: {"name": "...", "amount": "...", "units": "..."}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для греческих единиц измерения
        # Формат в nutrip.gr: "количество  единица. название" (например "1  τμχ. σπιτικό bagel")
        pattern = r'^(\d+(?:[.,]\d+)?)\s+([α-ωά-ώ]+\.)\s+(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, units, name = match.groups()
            
            # Обработка количества
            amount = amount_str.replace(',', '.')
            try:
                val = float(amount)
                amount = int(val) if val.is_integer() else val
            except:
                pass
            
            # units сохраняем с точкой
            
            # Очистка названия
            name = re.sub(r'\s+', ' ', name).strip()
            
            return {
                "name": name,
                "units": units,
                "amount": amount
            }
        
        # Если паттерн не совпал, пробуем другой формат (без количества)
        # Формат: "λίγο άνηθο" или "Σταγόνες λάιμ ή λεμόνι" или "φρέσκο πιπέρι"
        # В этом случае возвращаем весь текст как name
        return {
            "name": text,
            "units": None,
            "amount": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате списка словарей"""
        json_ld = self._get_json_ld_data()
        
        ingredients = []
        
        if json_ld and 'recipeIngredient' in json_ld:
            for ingredient_text in json_ld['recipeIngredient']:
                parsed = self.parse_ingredient_nutrip(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            steps = []
            
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        steps.append(step_text)
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        steps.append(step_text)
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            
            # Объединяем шаги в одну строку через пробел
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Сначала пробуем JSON-LD (приоритет для единообразия)
        json_ld = self._get_json_ld_data()
        
        if json_ld:
            # Пробуем recipeCategory
            if 'recipeCategory' in json_ld:
                category = json_ld['recipeCategory']
                if isinstance(category, list):
                    return ', '.join(category)
                return str(category)
            
            # Пробуем recipeCuisine
            if 'recipeCuisine' in json_ld:
                cuisine = json_ld['recipeCuisine']
                if isinstance(cuisine, list):
                    return ', '.join(cuisine)
                return str(cuisine)
        
        # Альтернатива - из HTML
        category_div = self.soup.find('div', class_='qodef-info--category')
        if category_div:
            category_link = category_div.find('a', class_='qodef-e-category')
            if category_link:
                return self.clean_text(category_link.get_text())
        
        # Альтернатива - из meta тегов
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'prepTime' in json_ld:
            return self.parse_iso_duration(json_ld['prepTime'])
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'cookTime' in json_ld:
            return self.parse_iso_duration(json_ld['cookTime'])
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'totalTime' in json_ld:
            return self.parse_iso_duration(json_ld['totalTime'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем div с классом qodef-note
        note_div = self.soup.find('div', class_='qodef-note')
        
        if note_div:
            # Извлекаем текст из span внутри
            span = note_div.find('span')
            if span:
                text = self.clean_text(span.get_text())
                return text if text else None
            
            # Если нет span, берем весь текст
            text = self.clean_text(note_div.get_text())
            return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD keywords и дополнительной семантической информации"""
        tags_set = set()
        
        json_ld = self._get_json_ld_data()
        
        # 1. Из JSON-LD keywords
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if isinstance(keywords, str):
                # Разбиваем по запятой и очищаем
                for tag in keywords.split(','):
                    tag = tag.strip()
                    if tag:
                        tags_set.add(tag)
            elif isinstance(keywords, list):
                for tag in keywords:
                    tag = str(tag).strip()
                    if tag:
                        tags_set.add(tag)
        
        # 2. Извлекаем ключевые слова из названия блюда (существительные)
        # Это помогает добавить теги вроде "καπνιστός σολομός" из "багель με καπνιστό σολομό"
        dish_name = self.extract_dish_name()
        if dish_name:
            # Ищем значимые слова (обычно после предлогов "με", "και", или отдельные слова)
            # Паттерн: "багель με καπνιστό σολομό" -> ["καπνιστός σολομός"]
            parts_match = re.search(r'με\s+([α-ωά-ώ\s]+)(?:\s+(?:και|ή)\s+|$)', dish_name, re.IGNORECASE)
            if parts_match:
                ingredient_phrase = parts_match.group(1).strip()
                # Нормализуем падеж (простое преобразование)
                if ingredient_phrase:
                    tags_set.add(ingredient_phrase)
        
        # 3. Из описания - ищем ключевые слова, например "πρωινό", "βραδινό"
        description = self.extract_description()
        if description:
            # Паттерны для типов приема пищи
            meal_types = re.findall(r'\b(πρωινό|βραδινό|μεσημεριανό|γεύμα|δείπνο|πρόγευμα)\b', description, re.IGNORECASE)
            for meal in meal_types:
                tags_set.add(meal.lower())
        
        if not tags_set:
            return None
        
        # Сортируем и объединяем через запятую с пробелом
        tags_list = sorted(list(tags_set))
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        if 'url' in item:
                            urls.append(item['url'])
                        elif 'contentUrl' in item:
                            urls.append(item['contentUrl'])
        
        # Дополнительно ищем в meta тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
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
            "instructions": self.extract_steps(),
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
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "nutrip_gr")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(NutripGrExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python nutrip_gr.py")


if __name__ == "__main__":
    main()
