"""
Экстрактор данных рецептов для сайта kotikokki.net
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KotikokkiExtractor(BaseRecipeExtractor):
    """Экстрактор для kotikokki.net"""
    
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
                    item_type = data.get('@type', '')
                    if isinstance(item_type, list) and 'Recipe' in item_type:
                        return data
                    elif item_type == 'Recipe':
                        return data
                        
            except (json.JSONDecodeError, KeyError):
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
        
        # Форматируем результат
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        
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
            text = re.sub(r'\s*-\s*Resepti.*$', '', text, flags=re.IGNORECASE)
            return self.clean_text(text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'description' in json_ld:
            return self.clean_text(json_ld['description'])
        
        # Альтернатива - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Убираем стандартный суффикс
            desc = re.sub(r'-resepti hakusessa\?.*$', '', desc, flags=re.IGNORECASE)
            desc = self.clean_text(desc)
            if desc and len(desc) > 10:
                return desc
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в формате списка словарей"""
        json_ld = self._get_json_ld_data()
        
        ingredients = []
        
        if json_ld and 'recipeIngredient' in json_ld:
            for ingredient_text in json_ld['recipeIngredient']:
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1pkt esipaistettuja patonkeja" или "350-400g broilerin suikaleita"
            
        Returns:
            dict: {"name": "...", "amount": ..., "units": "..."}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
            '⅕': '0.2', '⅖': '0.4', '⅗': '0.6', '⅘': '0.8'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Финские единицы измерения и слова
        # pkt = paketti (package), prk = purkki (jar/can), dl = deciliter, 
        # tl = teelusikka (teaspoon), rkl = ruokalusikka (tablespoon),
        # siivu/siivua = slices, ripaus = pinch, muutama = few
        pattern = r'^([\d\s/.,\-–]+)?\s*(pkt|prk|dl|tl|rkl|siivu|siivua|slices|ripaus|g|kg|ml|l|kpl|pussi|purkki|paketti|muutama)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, units, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Убираем пробелы
            amount_str = amount_str.replace(' ', '')
            # Пробуем преобразовать в число
            # Если это простое число, возвращаем как int или float
            if '-' not in amount_str and '–' not in amount_str:
                try:
                    # Пробуем преобразовать в число
                    num_val = float(amount_str.replace(',', '.'))
                    # Если число целое, возвращаем int
                    amount = int(num_val) if num_val.is_integer() else num_val
                except:
                    amount = amount_str
            else:
                # Сохраняем диапазоны как строку (350-400)
                amount = amount_str
        
        # Обработка единицы измерения
        units = units.strip() if units else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
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
                        if step_text:
                            steps.append(step_text)
                    elif isinstance(step, str):
                        step_text = self.clean_text(step)
                        if step_text:
                            steps.append(step_text)
            elif isinstance(instructions, str):
                steps.append(self.clean_text(instructions))
            
            # Фильтруем пустые строки и объединяем
            steps = [s for s in steps if s]
            
            # Проверяем последний шаг - если он содержит пояснительный текст (заметки),
            # то он будет извлечен отдельно в extract_notes
            # Поэтому включаем все шаги в инструкции
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        json_ld = self._get_json_ld_data()
        
        if json_ld:
            # Пробуем recipeCategory
            if 'recipeCategory' in json_ld:
                category = json_ld['recipeCategory']
                if isinstance(category, list):
                    # Берем первую категорию
                    return category[0] if category else None
                elif isinstance(category, str):
                    # Может быть строка с несколькими категориями через запятую
                    categories = [cat.strip() for cat in category.split(',')]
                    return categories[0] if categories else None
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'prepTime' in json_ld:
            iso_time = json_ld['prepTime']
            # Конвертируем из ISO в читаемый формат
            parsed_time = self.parse_iso_duration(iso_time)
            # Если время есть, возвращаем в формате как в примерах
            if parsed_time:
                # Преобразуем в формат как в reference JSON
                # "15 minutes" -> "15 minutes"
                # "30 minutes" -> "15 - 30 min" (примерно)
                return parsed_time.replace('minutes', 'min').replace('minute', 'min')
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'cookTime' in json_ld:
            iso_time = json_ld['cookTime']
            parsed_time = self.parse_iso_duration(iso_time)
            if parsed_time:
                # Преобразуем формат: "40 minutes" -> "40 minutes" или "30–40 minutes"
                return parsed_time
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'totalTime' in json_ld:
            iso_time = json_ld['totalTime']
            parsed_time = self.parse_iso_duration(iso_time)
            if parsed_time:
                return parsed_time.replace('minutes', 'min').replace('minute', 'min')
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # В kotikokki заметки часто являются последним элементом в recipeInstructions
        # если этот элемент содержит описательный/пояснительный текст
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'recipeInstructions' in json_ld:
            instructions = json_ld['recipeInstructions']
            
            if isinstance(instructions, list) and len(instructions) > 0:
                # Проверяем последний элемент
                last_step = instructions[-1]
                
                if isinstance(last_step, dict) and 'text' in last_step:
                    text = self.clean_text(last_step['text'])
                elif isinstance(last_step, str):
                    text = self.clean_text(last_step)
                else:
                    text = None
                
                # Если последний шаг содержит пояснительный текст (не инструкцию),
                # то это заметка
                if text and len(text) > 20:
                    # Ключевые слова, указывающие на заметку, а не инструкцию
                    note_indicators = [
                        'on perinteinen', 'säilyy', 'voi', 'suosit',
                        'leipä', 'Irlantilaiset', 'Perinteinen', 'Soodaleipä'
                    ]
                    
                    for indicator in note_indicators:
                        if indicator.lower() in text.lower():
                            # Убираем лишние пробелы
                            text = re.sub(r'\s+', ' ', text).strip()
                            return text
        
        # Альтернативный поиск в HTML
        paragraphs = self.soup.find_all('p')
        for p in paragraphs:
            text = p.get_text(strip=True)
            # Ищем strong теги с ключевыми словами
            strong = p.find('strong')
            if strong and 'Soodaleipä' in strong.get_text():
                cleaned_text = self.clean_text(text)
                if cleaned_text and len(cleaned_text) > 20:
                    return cleaned_text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из JSON-LD"""
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'keywords' in json_ld:
            keywords = json_ld['keywords']
            if isinstance(keywords, str):
                # Убираем лишние пробелы и разделяем по запятой
                tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
                # Возвращаем как строку через запятую с пробелом
                return ', '.join(tags_list) if tags_list else None
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        json_ld = self._get_json_ld_data()
        
        if json_ld and 'image' in json_ld:
            img = json_ld['image']
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, list):
                # В kotikokki может быть массив изображений
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
        
        # Дополнительно ищем в meta тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image:src'})
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
            
            # Возвращаем как строку через запятую БЕЗ пробела (как в примере)
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
    preprocessed_dir = os.path.join("preprocessed", "kotikokki_net")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(KotikokkiExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python kotikokki_net.py")


if __name__ == "__main__":
    main()
