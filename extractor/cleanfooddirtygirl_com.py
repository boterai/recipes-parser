"""
Экстрактор данных рецептов для сайта cleanfooddirtygirl.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class CleanFoodDirtyGirlExtractor(BaseRecipeExtractor):
    """Экстрактор для cleanfooddirtygirl.com"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
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
                    # Ищем в @graph
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict):
                                item_type = item.get('@type', '')
                                if isinstance(item_type, list) and 'Recipe' in item_type:
                                    return item
                                elif item_type == 'Recipe':
                                    return item
                    
                    # Проверяем сам корневой объект
                    item_type = data.get('@type', '')
                    if isinstance(item_type, list) and 'Recipe' in item_type:
                        return data
                    elif item_type == 'Recipe':
                        return data
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'name' in json_ld:
            return self.clean_text(json_ld['name'])
        
        # Альтернативно - из заголовка WPRM
        wprm_title = self.soup.find('h2', class_='wprm-recipe-name')
        if wprm_title:
            return self.clean_text(wprm_title.get_text())
        
        # Из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
        # Альтернативно - из WPRM summary
        wprm_summary = self.soup.find('div', class_='wprm-recipe-summary')
        if wprm_summary:
            return self.clean_text(wprm_summary.get_text())
        
        # Из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    @staticmethod
    def parse_fraction_to_decimal(text: str) -> Optional[float]:
        """
        Конвертирует дроби и смешанные числа в десятичные
        
        Args:
            text: строка вида "1½", "2¼", "⅓", "1 1/2", "2 3/4", "2-3"
            
        Returns:
            Десятичное число или None
        """
        if not text:
            return None
        
        # Для диапазонов типа "2-3" берем первое число
        if '-' in text and text.replace('-', '').replace(' ', '').replace('.', '').isdigit():
            text = text.split('-')[0].strip()
        
        # Заменяем Unicode дроби на десятичные
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8',
            '⅐': '0.14', '⅑': '0.11', '⅒': '0.1'
        }
        
        for fraction, decimal in fraction_map.items():
            if fraction in text:
                # Если есть цифра перед дробью (например "1½"), это смешанное число
                before_fraction = text.split(fraction)[0].strip()
                if before_fraction and before_fraction[-1].isdigit():
                    # Извлекаем целую часть
                    whole_match = re.search(r'(\d+)$', before_fraction)
                    if whole_match:
                        return float(whole_match.group(1)) + float(decimal)
                # Иначе просто заменяем дробь
                text = text.replace(fraction, decimal)
        
        # Обработка формата "1 1/2" или "2 3/4"
        if '/' in text:
            parts = text.split()
            total = 0.0
            for part in parts:
                if '/' in part:
                    num, denom = part.split('/')
                    total += float(num) / float(denom)
                elif part.replace('.', '').replace(',', '').isdigit():
                    total += float(part.replace(',', '.'))
            return total
        
        # Просто число
        try:
            return float(text.replace(',', '.'))
        except ValueError:
            return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов из WPRM структуры"""
        ingredients_list = []
        
        # Ищем WPRM recipe ingredients
        wprm_ingredients = self.soup.find_all('li', class_='wprm-recipe-ingredient')
        
        for ingredient_li in wprm_ingredients:
            # Извлекаем amount, unit, name из отдельных spans
            amount_span = ingredient_li.find('span', class_='wprm-recipe-ingredient-amount')
            unit_span = ingredient_li.find('span', class_='wprm-recipe-ingredient-unit')
            name_span = ingredient_li.find('span', class_='wprm-recipe-ingredient-name')
            
            if not name_span:
                continue
            
            name = self.clean_text(name_span.get_text())
            
            # Пропускаем ингредиенты явно помеченные как optional
            # но НЕ пропускаем ингредиенты "for garnish" - они включаются
            if '(optional)' in name.lower():
                continue
            
            # Очищаем название от лишних деталей (убираем описания после запятой)
            # Например: "zucchini, unpeeled and cut into ½-inch cubes" -> "zucchini"
            if ',' in name:
                name = name.split(',')[0].strip()
            
            # Конвертируем amount в число (int если целое, иначе float)
            amount = None
            if amount_span:
                amount_text = self.clean_text(amount_span.get_text())
                if amount_text:
                    decimal_val = self.parse_fraction_to_decimal(amount_text)
                    if decimal_val is not None:
                        # Преобразуем в int если это целое число
                        if decimal_val == int(decimal_val):
                            amount = int(decimal_val)
                        else:
                            amount = decimal_val
            
            units = None
            if unit_span:
                units = self.clean_text(unit_span.get_text())
            
            ingredient_dict = {
                "name": name,
                "units": units,
                "amount": amount
            }
            
            ingredients_list.append(ingredient_dict)
        
        if ingredients_list:
            return json.dumps(ingredients_list, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Сначала пробуем извлечь из JSON-LD
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            if isinstance(instructions, list):
                for step in instructions:
                    if isinstance(step, dict) and 'text' in step:
                        step_text = self.clean_text(step['text'])
                        steps.append(step_text)
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        steps.append(step_text)
            
            if steps:
                # Добавляем нумерацию: "1. ", "2. ", etc.
                numbered_steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
                return ' '.join(numbered_steps)
        
        # Если JSON-LD не помог, ищем в WPRM HTML
        # Сначала ищем все группы инструкций с их заголовками
        instruction_groups = self.soup.find_all('div', class_='wprm-recipe-instruction-group')
        
        if instruction_groups:
            all_steps = []
            for group in instruction_groups:
                # Заголовок группы не добавляем как отдельный шаг, чтобы не нарушать нумерацию
                # (группы типа "Spices", "Everything else" не должны быть в инструкциях)
                
                # Добавляем все шаги из группы
                wprm_instructions = group.find_all('li', class_='wprm-recipe-instruction')
                for instruction_li in wprm_instructions:
                    instruction_text_div = instruction_li.find('div', class_='wprm-recipe-instruction-text')
                    if instruction_text_div:
                        step_text = self.clean_text(instruction_text_div.get_text())
                        if step_text:
                            all_steps.append(step_text)
            
            if all_steps:
                # Добавляем нумерацию
                numbered_steps = [f"{idx}. {step}" for idx, step in enumerate(all_steps, 1)]
                return ' '.join(numbered_steps)
        else:
            # Если нет групп, просто берем все инструкции
            wprm_instructions = self.soup.find_all('li', class_='wprm-recipe-instruction')
            
            for instruction_li in wprm_instructions:
                instruction_text_div = instruction_li.find('div', class_='wprm-recipe-instruction-text')
                if instruction_text_div:
                    step_text = self.clean_text(instruction_text_div.get_text())
                    if step_text:
                        steps.append(step_text)
            
            if steps:
                # Добавляем нумерацию
                numbered_steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
                return ' '.join(numbered_steps)
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # На сайте cleanfooddirtygirl.com обычно нет данных о питательности
        # Возвращаем None
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeCategory' in json_ld:
            category = json_ld['recipeCategory']
            if isinstance(category, list):
                return ', '.join(category)
            return self.clean_text(category)
        
        # Альтернативно - из WPRM course
        wprm_course = self.soup.find('span', class_='wprm-recipe-course')
        if wprm_course:
            return self.clean_text(wprm_course.get_text())
        
        # Из метаданных статьи
        article_section = self.soup.find('meta', property='article:section')
        if article_section and article_section.get('content'):
            return self.clean_text(article_section['content'])
        
        return None
    
    @staticmethod
    def _format_time_parts(hours: int, minutes: int) -> Optional[str]:
        """
        Форматирует часы и минуты в читаемую строку
        
        Args:
            hours: количество часов
            minutes: количество минут
            
        Returns:
            Время в формате "20 minutes" или "1 hour 30 minutes"
        """
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
        return ' '.join(parts) if parts else None
    
    @staticmethod
    def parse_time_text(time_text: str) -> Optional[str]:
        """
        Парсинг времени из текста
        
        Args:
            time_text: строка вида "20 mins", "1 hr 30 mins", "40 minutes"
            
        Returns:
            Время в формате "20 minutes" или "1 hour 30 minutes"
        """
        if not time_text:
            return None
        
        time_text = time_text.lower().strip()
        
        # Извлекаем часы и минуты
        hours = 0
        minutes = 0
        
        # Ищем часы
        hour_match = re.search(r'(\d+)\s*(?:hour|hr|h)s?', time_text)
        if hour_match:
            hours = int(hour_match.group(1))
        
        # Ищем минуты
        min_match = re.search(r'(\d+)\s*(?:minute|min|m)s?', time_text)
        if min_match:
            minutes = int(min_match.group(1))
        
        return CleanFoodDirtyGirlExtractor._format_time_parts(hours, minutes)
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в WPRM структуре
        prep_time_span = self.soup.find('span', class_='wprm-recipe-prep_time')
        if prep_time_span:
            time_text = self.clean_text(prep_time_span.get_text())
            return self.parse_time_text(time_text)
        
        # Из JSON-LD (если есть)
        json_ld = self._get_json_ld_data()
        if json_ld and 'prepTime' in json_ld:
            # ISO 8601 формат
            iso_time = json_ld['prepTime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в WPRM структуре
        cook_time_span = self.soup.find('span', class_='wprm-recipe-cook_time')
        if cook_time_span:
            time_text = self.clean_text(cook_time_span.get_text())
            return self.parse_time_text(time_text)
        
        # Из JSON-LD (если есть)
        json_ld = self._get_json_ld_data()
        if json_ld and 'cookTime' in json_ld:
            # ISO 8601 формат
            iso_time = json_ld['cookTime']
            return self.parse_iso_duration(iso_time)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в WPRM структуре
        total_time_span = self.soup.find('span', class_='wprm-recipe-total_time')
        if total_time_span:
            time_text = self.clean_text(total_time_span.get_text())
            return self.parse_time_text(time_text)
        
        # Из JSON-LD (если есть)
        json_ld = self._get_json_ld_data()
        if json_ld and 'totalTime' in json_ld:
            # ISO 8601 формат
            iso_time = json_ld['totalTime']
            return self.parse_iso_duration(iso_time)
        
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
        
        return CleanFoodDirtyGirlExtractor._format_time_parts(hours, minutes)
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем WPRM notes
        notes_div = self.soup.find('div', class_='wprm-recipe-notes')
        if notes_div:
            # Извлекаем текст, убирая HTML теги
            notes_text = notes_div.get_text(separator=' ', strip=True)
            return self.clean_text(notes_text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Ищем в JSON-LD keywords
        json_ld = self._get_json_ld_data()
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if isinstance(keywords, list):
                tags_list.extend(keywords)
            elif isinstance(keywords, str):
                # Разделяем по запятой
                tags_list.extend([tag.strip() for tag in keywords.split(',') if tag.strip()])
        
        # Фильтруем стоп-слова
        stopwords = {
            'recipe', 'recipes', 'how to make', 'how to', 'easy', 'cooking', 'quick',
            'food', 'kitchen', 'simple', 'best', 'make', 'ingredients', 'video',
            'clean food dirty girl', 'healthy vegan recipes', 'no oil recipes',
            'plant based', 'plant based recipes', 'vegan recipes', 'wfpb',
            'wfpb recipes', 'whole food plant based', 'whole food plant based recipes'
        }
        
        filtered_tags = []
        for tag in tags_list:
            tag_lower = tag.lower().strip()
            if tag_lower not in stopwords and len(tag_lower) >= 3:
                filtered_tags.append(tag_lower)
        
        # Удаляем дубликаты
        seen = set()
        unique_tags = []
        for tag in filtered_tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем в JSON-LD
        json_ld = self._get_json_ld_data()
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                urls.extend([i for i in img if isinstance(i, str)])
            elif isinstance(img, dict):
                if 'url' in img:
                    urls.append(img['url'])
                elif 'contentUrl' in img:
                    urls.append(img['contentUrl'])
        
        # Ищем в meta og:image
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
    """Точка входа для обработки директории с HTML файлами"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "cleanfooddirtygirl_com")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(CleanFoodDirtyGirlExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python cleanfooddirtygirl_com.py")


if __name__ == "__main__":
    main()
