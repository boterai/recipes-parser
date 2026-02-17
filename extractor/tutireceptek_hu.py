"""
Экстрактор данных рецептов для сайта tutireceptek.hu
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class TutireceptekExtractor(BaseRecipeExtractor):
    """Экстрактор для tutireceptek.hu"""
    
    # Список общих слов без смысловой нагрузки для фильтрации тегов
    STOPWORDS = {
        'recept', 'receptek', 'étel', 'ital', 'koktél', 'turmix',
        'sütemény', 'torta', 'főzés', 'sütés', 'édesség', 'köret',
        'halétel', 'főétel', 'pizza', 'szendvics', 'szendvicskrém', 'leves'
    }
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке H1
        h1 = self.soup.find('h1')
        if h1:
            title = h1.get_text(strip=True)
            # Убираем " recept" в конце
            title = re.sub(r'\s+recept$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Альтернативно из title
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text(strip=True)
            title = re.sub(r'\s+recept$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Убираем шаблонные фразы
            desc = re.sub(r'^Itt a .+ receptjét olvashatod: hozzávalók, elkészítés módja\.?$', '', desc, flags=re.IGNORECASE)
            desc = self.clean_text(desc)
            if desc:
                return desc
        
        return None
    
    def parse_ingredient_line(self, line: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            line: Строка вида "1 fej vöröshagyma" или "20 dkg burgonya"
            
        Returns:
            dict: {"name": "vöröshagyma", "amount": "1", "unit": "fej"} или None
        """
        if not line:
            return None
        
        # Чистим текст
        text = self.clean_text(line).strip()
        
        # Убираем маркеры списка
        text = re.sub(r'^[\*\-\+]\s*', '', text)
        # Убираем точку с запятой и точку в конце
        text = re.sub(r'[;,.]$', '', text)
        text = text.strip()
        
        if not text or len(text) < 2:
            return None
        
        # Список единиц измерения (важно сначала искать более длинные)
        units = [
            'kávéskanál', 'kávékanál', 'evőkanál', 'evokanál',
            'dekagram', 'deciliter', 'milliliter', 'kilogram',
            'fej', 'fejet', 'gerezd', 'db', 'darab',
            'dkg', 'kg', 'g', 'dl', 'l', 'ml',
            'pohár', 'csokor', 'csomag', 'csipet',
            'kevés', 'friss', 'felvert', 'fél'
        ]
        
        # Сначала пробуем паттерн с количеством в начале (с пробелом)
        pattern1 = r'^([\d,./]+)\s+(' + '|'.join(units) + r')\s+(.+)$'
        match = re.match(pattern1, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
        else:
            # Пробуем паттерн с количеством и единицей БЕЗ пробела (например "30dkg")
            pattern1b = r'^([\d,./]+)(' + '|'.join(units) + r')\s+(.+)$'
            match = re.match(pattern1b, text, re.IGNORECASE)
            
            if match:
                amount_str, unit, name = match.groups()
            else:
                # Пробуем паттерн с "fél" или другим модификатором перед единицей
                # Например: "fél kávéskanál só"
                pattern2 = r'^(fél|negyed|egy)\s+(' + '|'.join(units) + r')\s+(.+)$'
                match = re.match(pattern2, text, re.IGNORECASE)
                
                if match:
                    modifier, unit, name = match.groups()
                    # Преобразуем модификатор в число
                    modifier_map = {
                        'fél': '0.5',
                        'negyed': '0.25',
                        'egy': '1'
                    }
                    amount_str = modifier_map.get(modifier.lower(), modifier)
                else:
                    # Пробуем только единицу + название (без количества)
                    # Например: "friss majoranna", "kevés olívaolaj"
                    pattern3 = r'^(' + '|'.join(units) + r')\s+(.+)$'
                    match = re.match(pattern3, text, re.IGNORECASE)
                    
                    if match:
                        unit, name = match.groups()
                        amount_str = None
                    else:
                        # Пробуем количество + название (без единицы)
                        # Например: "2 tojás"
                        pattern4 = r'^([\d,./]+)\s+(.+)$'
                        match = re.match(pattern4, text, re.IGNORECASE)
                        
                        if match:
                            amount_str, name = match.groups()
                            unit = None
                        else:
                            # Если паттерн не совпал, возвращаем только название
                            return {
                                "name": text,
                                "amount": None,
                                "unit": None
                            }
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip().replace(',', '.')
            # Обработка дробей типа "1/2"
            if '/' in amount_str:
                parts = amount_str.split('/')
                if len(parts) == 2:
                    try:
                        amount = str(float(parts[0]) / float(parts[1]))
                    except (ValueError, ZeroDivisionError):
                        amount = amount_str
                else:
                    amount = amount_str
            else:
                amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        name = name.strip()
        # Убираем скобки с содержимым (например "(elhagyható)")
        name = re.sub(r'\([^)]*\)', '', name)
        # Убираем точки в конце
        name = re.sub(r'\.$', '', name)
        name = name.strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "unit": unit
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Находим секцию с ингредиентами
        # Ищем <strong>Hozzávalók:</strong>
        strong_tags = self.soup.find_all('strong')
        hozzavalok_section = None
        
        for tag in strong_tags:
            if 'hozzávalók' in tag.get_text().lower():
                hozzavalok_section = tag
                break
        
        if not hozzavalok_section:
            return None
        
        # Собираем текст после этого тега до следующего <strong>
        current = hozzavalok_section.next_sibling
        ingredient_text = []
        
        while current:
            if hasattr(current, 'name'):
                if current.name == 'strong':
                    # Достигли следующей секции
                    break
                if current.name == 'br':
                    current = current.next_sibling
                    continue
            
            if hasattr(current, 'get_text'):
                text = current.get_text(strip=True)
            else:
                text = str(current).strip()
            
            if text:
                ingredient_text.append(text)
            
            current = current.next_sibling
        
        # Парсим каждую строку ингредиента
        for line in ingredient_text:
            # Пропускаем заголовки секций (например "A tésztához:", "Hozzávalók 4 személyre:")
            if ':' in line or 'személyre' in line.lower():
                continue
            
            # Разбиваем по запятым, если есть несколько ингредиентов в одной строке
            if ',' in line:
                parts = line.split(',')
                for part in parts:
                    parsed = self.parse_ingredient_line(part)
                    if parsed:
                        ingredients.append(parsed)
            else:
                parsed = self.parse_ingredient_line(line)
                if parsed:
                    ingredients.append(parsed)
        
        if ingredients:
            # Преобразуем в формат JSON с полями name, units, amount
            formatted_ingredients = []
            for ing in ingredients:
                formatted_ingredients.append({
                    "name": ing["name"],
                    "units": ing["unit"],
                    "amount": ing["amount"]
                })
            return json.dumps(formatted_ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Находим секцию с инструкциями
        # Ищем <strong>Elkészítés:</strong>
        strong_tags = self.soup.find_all('strong')
        elkeszites_section = None
        
        for tag in strong_tags:
            if 'elkészítés' in tag.get_text().lower():
                elkeszites_section = tag
                break
        
        if not elkeszites_section:
            return None
        
        # Собираем текст после этого тега до следующего <strong>
        current = elkeszites_section.next_sibling
        instruction_parts = []
        
        while current:
            if hasattr(current, 'name'):
                if current.name == 'strong':
                    # Достигли следующей секции
                    break
                if current.name == 'br':
                    current = current.next_sibling
                    continue
                if current.name == 'em':
                    # Это автор рецепта, пропускаем
                    break
            
            if hasattr(current, 'get_text'):
                text = current.get_text(strip=True)
            else:
                text = str(current).strip()
            
            if text:
                instruction_parts.append(text)
            
            current = current.next_sibling
        
        if instruction_parts:
            # Объединяем все части в одну строку
            instructions = ' '.join(instruction_parts)
            return self.clean_text(instructions)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Находим секцию категории
        # Ищем <strong>Kategória:</strong>
        strong_tags = self.soup.find_all('strong')
        kategoria_section = None
        
        for tag in strong_tags:
            if 'kategória' in tag.get_text().lower():
                kategoria_section = tag
                break
        
        if not kategoria_section:
            return None
        
        # Ищем ссылку после этого тега
        current = kategoria_section.next_sibling
        while current:
            if hasattr(current, 'name'):
                if current.name == 'a':
                    return self.clean_text(current.get_text())
                if current.name == 'strong':
                    # Достигли следующей секции
                    break
            current = current.next_sibling
        
        return None
    
    def extract_time_from_text(self, text: str, pattern: str) -> Optional[str]:
        """
        Извлечение времени из текста инструкций или заметок
        
        Args:
            text: Текст для поиска
            pattern: Паттерн для поиска (например, "perc" для минут)
        """
        if not text:
            return None
        
        # Ищем паттерны времени в тексте
        # Например: "30 perc", "10-15 perc", "30-40 perc"
        time_pattern = r'(\d+(?:-\d+)?)\s*' + pattern
        match = re.search(time_pattern, text, re.IGNORECASE)
        
        if match:
            time_value = match.group(1)
            return f"{time_value} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в тексте инструкций упоминания о времени подготовки
        instructions = self.extract_instructions()
        if instructions:
            # Ищем упоминания "pihentessük" (отдых теста) и время перед этим
            prep_pattern = r'(\d+)\s*percig.*?pihen'
            match = re.search(prep_pattern, instructions, re.IGNORECASE)
            if match:
                return f"{match.group(1)} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте инструкций упоминания времени готовки
        instructions = self.extract_instructions()
        notes = self.extract_notes()
        
        # Объединяем тексты для поиска
        search_text = (instructions or '') + ' ' + (notes or '')
        
        # Ищем упоминания времени готовки/жарки/варки
        # Например: "10-15 perc", "30-40 perc alatt"
        patterns = [
            r'(?:süs|fo[zž]|pir).*?(\d+(?:-\d+)?)\s*perc',
            r'(\d+(?:-\d+)?)\s*perc(?:ig|et|re|)\s*(?:alatt)?.*?(?:süs|fo[zž]|pir|megpir)',
            r'kb\.\s*(\d+(?:-\d+)?)\s*perc'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, search_text, re.IGNORECASE)
            if match:
                time_value = match.group(1)
                return f"{time_value} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Обычно не указывается явно, можно попробовать вычислить из prep + cook
        # Но для простоты оставим None, если не найдено явно
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Находим секцию с заметками
        # Ищем <strong>Tanácsok:</strong> или <strong>Fortély:</strong>
        strong_tags = self.soup.find_all('strong')
        notes_section = None
        
        for tag in strong_tags:
            text = tag.get_text().lower()
            if 'tanács' in text or 'fortély' in text:
                notes_section = tag
                break
        
        if not notes_section:
            return None
        
        # Собираем текст после этого тега до следующей секции или конца
        current = notes_section.next_sibling
        notes_parts = []
        
        while current:
            if hasattr(current, 'name'):
                if current.name == 'strong':
                    # Достигли следующей секции
                    break
                if current.name == 'br':
                    current = current.next_sibling
                    continue
                if current.name == 'em':
                    # Это автор рецепта, пропускаем
                    break
                if current.name == 'h2':
                    # Достигли рекомендаций
                    break
            
            if hasattr(current, 'get_text'):
                text = current.get_text(strip=True)
            else:
                text = str(current).strip()
            
            if text and text != 'Fortély:':
                notes_parts.append(text)
            
            current = current.next_sibling
        
        if notes_parts:
            notes = ' '.join(notes_parts)
            return self.clean_text(notes)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов из meta keywords"""
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Разбиваем по запятым
            tags_list = [tag.strip() for tag in keywords.split(',') if tag.strip()]
            
            # Фильтруем общие слова
            filtered_tags = []
            for tag in tags_list:
                tag_lower = tag.lower()
                # Пропускаем точные совпадения со стоп-словами
                if tag_lower in self.STOPWORDS:
                    continue
                # Пропускаем теги, которые заканчиваются на " recept"
                if tag_lower.endswith(' recept'):
                    continue
                
                filtered_tags.append(tag)
            
            if filtered_tags:
                return ', '.join(filtered_tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        # На этом сайте изображения могут быть в разных местах
        # Проверяем разные источники
        urls = []
        
        # 1. Ищем изображения в контенте страницы
        # Ищем все img теги (кроме иконок и служебных)
        images = self.soup.find_all('img')
        for img in images:
            src = img.get('src', '')
            # Пропускаем служебные изображения
            if 'fejlec' in src or 'ikon' in src or 'menu' in src or 'kategoria' in src:
                continue
            # Пропускаем очень маленькие изображения
            if src and src.startswith('http'):
                urls.append(src)
        
        if urls:
            # Убираем дубликаты
            seen = set()
            unique_urls = []
            for url in urls:
                if url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            if unique_urls:
                return ','.join(unique_urls)
        
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
    # Обрабатываем папку preprocessed/tutireceptek_hu
    preprocessed_dir = os.path.join("preprocessed", "tutireceptek_hu")
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(TutireceptekExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python tutireceptek_hu.py")


if __name__ == "__main__":
    main()
