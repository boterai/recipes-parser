"""
Экстрактор данных рецептов для сайта matia.gr
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MatiaGrExtractor(BaseRecipeExtractor):
    """Экстрактор для matia.gr"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в мета-тегах og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " .: Γλυκά .: Ματιά"
            title = re.sub(r'\s+\.:.*$', '', title)
            return self.clean_text(title)
        
        # Альтернативно - из заголовка страницы
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем суффиксы
            title = re.sub(r'\s+\.:.*$', '', title)
            return self.clean_text(title)
        
        # Попытка из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'headline' in item:
                            return self.clean_text(item['headline'])
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Убираем суффиксы
            desc = re.sub(r'\s+\.:.*$', '', desc)
            return self.clean_text(desc)
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            desc = re.sub(r'\s+\.:.*$', '', desc)
            return self.clean_text(desc)
        
        return None
    
    def parse_ingredient_line(self, line: str) -> Optional[Dict[str, Optional[str]]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            line: Строка вида "1 κιλό αλεύρι για όλες τις χρήσεις"
            
        Returns:
            dict: {"name": "αλεύρι", "amount": "1", "unit": "κιλό"}
        """
        if not line:
            return None
        
        # Чистим текст
        text = self.clean_text(line)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1 κιλό αλεύρι", "2 3/4 κούπες ζάχαρη", "4 αυγά"
        # Поддерживаем дроби типа "1/2", "2 3/4"
        pattern = r'^([\d\s/]+)?\s*(κιλό|κιλά|κούπες?|κούπας?|κουταλιές?|κουταλάκι[α]?|φακελάκι[α]?|γραμμάρια?|λίτρ[α]?|ml|l|g|kg|шт\.|πρέζα)?\s*(.+)'
        
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
            amount = amount_str.strip()
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "για όλες τις χρήσεις", "για πασπάλισμα" и т.д.
        name = re.sub(r'\bγια\s+.*$', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
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
        
        # Ищем секцию с ингредиентами
        ylika_section = self.soup.find('p', class_='ylika')
        
        if ylika_section:
            # Получаем текст и разбиваем по <br>
            # Сначала заменяем <br> на специальный разделитель
            for br in ylika_section.find_all('br'):
                br.replace_with('|||NEWLINE|||')
            
            # Получаем текст
            text = ylika_section.get_text()
            
            # Разбиваем по строкам
            lines = text.split('|||NEWLINE|||')
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Парсим строку ингредиента
                parsed = self.parse_ingredient_line(line)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Ищем секцию с инструкциями (класс "ektelesh")
        instructions_section = self.soup.find('p', class_='ektelesh')
        
        if instructions_section:
            # Заменяем <br> на пробелы для правильного соединения
            for br in instructions_section.find_all('br'):
                br.replace_with(' ')
            
            text = instructions_section.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            return text if text else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в мета-тегах article:section
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Альтернативно - из JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        if item.get('@type') == 'Article' and 'articleSection' in item:
                            section = item['articleSection']
                            # articleSection может быть строкой или списком
                            if isinstance(section, list):
                                return self.clean_text(section[0]) if section else None
                            return self.clean_text(section)
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в тексте инструкций упоминания времени подготовки/отдыха
        instructions_section = self.soup.find('p', class_='ektelesh')
        
        if instructions_section:
            text = instructions_section.get_text()
            
            # Ищем паттерны: "ξεκουραστεί για μισή ώρα", "ξεκουραστεί για 30 λεπτά"
            # Паттерн для отдыха теста
            rest_match = re.search(r'ξεκουραστεί.*?(?:για\s+)?(?:μισή\s+ώρα|(\d+)\s*(?:λεπτ[άα]|ώρ[αες]))', text, re.IGNORECASE)
            if rest_match:
                if 'μισή ώρα' in rest_match.group(0):
                    return "30 minutes"
                elif rest_match.group(1):
                    return f"{rest_match.group(1)} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        # Ищем в тексте инструкций упоминания времени
        instructions_section = self.soup.find('p', class_='ektelesh')
        
        if instructions_section:
            text = instructions_section.get_text()
            
            # Ищем конкретные паттерны времени готовки в духовке/на плите
            # "ψήνουμε ... για X λεπτά", "ψήνουμε ... δέκα λεπτά"
            # Более широкий паттерн для поиска времени после глаголов готовки
            baking_match = re.search(r'ψήνουμε.{0,100}?(?:για\s+)?(?:(?:ένα\s+)?τέταρτο(?:\s+της\s+ώρας)?|είκοσι\s+(?:περίπου\s+)?λεπτ[άα]|δέκα\s+(?:περίπου\s+)?λεπτ[άα]|(\d+)\s+(?:περίπου\s+)?λεπτ[άα])', text, re.IGNORECASE)
            if baking_match:
                if 'τέταρτο' in baking_match.group(0):
                    return "15 minutes"
                elif 'είκοσι' in baking_match.group(0):
                    return "20 minutes"
                elif 'δέκα' in baking_match.group(0):
                    return "10 minutes"
                elif baking_match.group(1):
                    return f"{baking_match.group(1)} minutes"
            
            # Если не нашли, ищем общие упоминания времени с числами
            time_match = re.search(r'(\d+)\s*(?:περίπου\s+)?λεπτ[άα]', text, re.IGNORECASE)
            if time_match:
                minutes = time_match.group(1)
                # Фильтруем слишком малые числа (например, "5 пόντους")
                if int(minutes) >= 10:
                    return f"{minutes} minutes"
            
            # Словами (для случаев без чисел)
            time_words = {
                'είκοσι λεπτ': '20',
                'δέκα λεπτ': '10',
                'τέταρτο': '15',
            }
            
            for greek_time, minutes in time_words.items():
                if greek_time in text.lower():
                    return f"{minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Можем попытаться вычислить из prep_time и cook_time
        # Но для matia.gr обычно нет отдельного total_time
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Для matia.gr обычно нет отдельной секции с заметками
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из meta-тегов article:tag"""
        tags_list = []
        
        # Ищем все мета-теги article:tag
        tag_metas = self.soup.find_all('meta', property='article:tag')
        
        for tag_meta in tag_metas:
            if tag_meta.get('content'):
                tag = tag_meta['content'].strip()
                if tag:
                    tags_list.append(tag)
        
        # Возвращаем как строку через запятую и пробел
        return ', '.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            # Фильтруем общие логотипы
            if 'matia-colours' not in url and 'matia-logo' not in url:
                urls.append(url)
        
        # twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if 'matia-colours' not in url and 'matia-logo' not in url:
                urls.append(url)
        
        # 2. Ищем в JSON-LD
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, dict) and '@graph' in data:
                    for item in data['@graph']:
                        # ImageObject
                        if item.get('@type') == 'ImageObject':
                            if 'url' in item:
                                url = item['url']
                                if 'matia-colours' not in url and 'matia-logo' not in url:
                                    urls.append(url)
            except (json.JSONDecodeError, KeyError):
                continue
        
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
    """Обработка всех HTML файлов из директории preprocessed/matia_gr"""
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "preprocessed",
        "matia_gr"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(MatiaGrExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python matia_gr.py")


if __name__ == "__main__":
    main()
