"""
Экстрактор данных рецептов для сайта rezepteoma.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class RezepteomaComExtractor(BaseRecipeExtractor):
    """Экстрактор для rezepteoma.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1 с классом entry-title
        entry_title = self.soup.find('h1', class_='entry-title')
        if entry_title:
            title = self.clean_text(entry_title.get_text())
            # Название может содержать ":", разделяющий название и описание
            if ':' in title:
                parts = title.split(':', 1)
                return self.clean_text(parts[0])
            return title
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - Аlte Oma Rezepte"
            title = re.sub(r'\s*-\s*Аlte Oma Rezepte.*$', '', title, flags=re.IGNORECASE)
            # Разделяем название и описание, если есть двоеточие
            if ':' in title:
                parts = title.split(':', 1)
                return self.clean_text(parts[0])
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в заголовке h1 - описание идет после двоеточия
        entry_title = self.soup.find('h1', class_='entry-title')
        if entry_title:
            title = self.clean_text(entry_title.get_text())
            if ':' in title:
                parts = title.split(':', 1)
                if len(parts) > 1:
                    return self.clean_text(parts[1])
        
        # Альтернативно - из og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r'\s*-\s*Аlte Oma Rezepte.*$', '', title, flags=re.IGNORECASE)
            if ':' in title:
                parts = title.split(':', 1)
                if len(parts) > 1:
                    return self.clean_text(parts[1])
        
        # Еще один источник - og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            # Убираем "Zutaten:" и все после него, берем только описание
            desc = re.sub(r'Zutaten:.*$', '', desc, flags=re.DOTALL)
            desc = self.clean_text(desc)
            if desc and len(desc) > 10:  # Если осталось что-то осмысленное
                return desc
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем параграф, содержащий "Zutaten:"
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            # Ищем параграф с текстом "Zutaten:" и ингредиентами на той же строке
            for p in entry_content.find_all('p'):
                text = p.get_text()
                if 'Zutaten:' in text and len(text) > len('Zutaten:') + 10:
                    # Извлекаем ингредиенты из p.contents, которые разделены <br/> тегами
                    # p.contents содержит список: ['Zutaten:', <br/>, '100g Speck', <br/>, ...]
                    for content in p.contents:
                        # Пропускаем br теги
                        if hasattr(content, 'name') and content.name == 'br':
                            continue
                        
                        # Берем только строки (текстовые узлы)
                        if isinstance(content, str):
                            line = content.strip()
                            # Пропускаем "Zutaten:", "Richtungen:", "Vorbereitung:" и пустые строки
                            if line and not line.startswith(('Zutaten', 'Richtungen', 'Vorbereitung')):
                                parsed = self.parse_ingredient(line)
                                if parsed:
                                    ingredients.append(parsed)
                    
                    break
        
        # Если ингредиенты не найдены, пробуем извлечь из og:description
        if not ingredients:
            og_desc = self.soup.find('meta', property='og:description')
            if og_desc and og_desc.get('content'):
                desc = og_desc['content']
                # Ищем секцию "Zutaten" в описании
                if 'Zutaten' in desc:
                    # Извлекаем текст после "Zutaten" до "[…]" или конца
                    zutaten_match = re.search(r'Zutaten\s+(.+?)(?:\s*\[…\]|$)', desc, re.DOTALL)
                    if zutaten_match:
                        zutaten_text = zutaten_match.group(1)
                        # Разбиваем по паттерну: "Название количество единица"
                        # Примеры: "Geschälte Tomaten 400 gr", "Rigatoni 360 gr"
                        lines = zutaten_text.split('\n')
                        for line in lines:
                            line = line.strip()
                            if line:
                                # Попытка парсинга в формате "название количество единица"
                                parsed = self.parse_ingredient_from_description(line)
                                if parsed:
                                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient_from_description(self, text: str) -> Optional[dict]:
        """
        Парсинг ингредиента из og:description
        Формат: "Geschälte Tomaten 400 gr" -> {"name": "Geschälte Tomaten", "amount": 400, "units": "gr"}
        """
        if not text:
            return None
        
        text = self.clean_text(text)
        
        # Паттерн: название в начале, затем количество и единица в конце
        # Примеры: "Geschälte Tomaten 400 gr", "Ei 1", "Knoblauch 1 clove"
        pattern = r'^(.+?)\s+(\d+(?:[.,]\d+)?)\s*(gr|g|kg|ml|l|clove|bunch|qb)?$'
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            name, amount_str, unit = match.groups()
            
            # Обработка количества
            if amount_str:
                if '.' in amount_str or ',' in amount_str:
                    amount = float(amount_str.replace(',', '.'))
                else:
                    amount = int(amount_str)
            else:
                amount = None
            
            return {
                "name": self.clean_text(name),
                "units": unit if unit else None,
                "amount": amount
            }
        
        # Если не совпал паттерн, возвращаем просто название
        return {
            "name": text,
            "units": None,
            "amount": None
        }
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        Формат: "100g Speck" -> {"name": "Speck", "amount": 100, "units": "g"}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "100g Speck", "1 rechteckiger Blätterteig", "2 Eier", "50g getrocknete Tomaten", "2 ganze Eier"
        # Сначала пробуем паттерн с единицей измерения сразу после числа (без пробела или с пробелом)
        pattern1 = r'^(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l|EL|TL|Prise|Prisen|rechteckiger|ganz|ganze)?\s+(.+)$'
        match = re.match(pattern1, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Обработка количества - конвертируем в int если это целое число
            if amount_str:
                if '.' in amount_str or ',' in amount_str:
                    amount = float(amount_str.replace(',', '.'))
                else:
                    amount = int(amount_str)
            else:
                amount = None
            
            # Обработка единицы измерения - нормализуем "ganze" -> "ganz"
            if unit:
                if unit.lower() == 'ganze':
                    unit = 'ganz'
            
            # Очистка названия
            name = self.clean_text(name)
            if not name or len(name) < 2:
                return None
            
            return {
                "name": name,
                "units": unit,
                "amount": amount
            }
        
        # Если паттерн не совпал, возвращаем как есть (только название)
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем ordered list в entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем упорядоченный список
        ol = entry_content.find('ol', class_='wp-block-list')
        if ol:
            # Извлекаем шаги из элементов списка
            step_items = ol.find_all('li')
            for item in step_items:
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                if step_text:
                    steps.append(step_text)
        
        # Если не нашли упорядоченный список, ищем инструкции в формате "Schritt N" + текст
        if not steps:
            paragraphs = entry_content.find_all('p')
            i = 0
            while i < len(paragraphs):
                p = paragraphs[i]
                text = self.clean_text(p.get_text())
                
                # Проверяем, является ли это заголовком шага (например, "Schritt 1")
                if text and re.match(r'^Schritt\s+\d+$', text, re.IGNORECASE):
                    # Следующий параграф должен содержать инструкцию
                    if i + 1 < len(paragraphs):
                        next_p = paragraphs[i + 1]
                        instruction_text = self.clean_text(next_p.get_text())
                        if instruction_text and len(instruction_text) > 10:
                            # Убираем цифру в конце (например, "текст1." -> "текст.")
                            instruction_text = re.sub(r'\d+\.$', '.', instruction_text)
                            instruction_text = re.sub(r'\d+$', '', instruction_text)
                            steps.append(instruction_text)
                        i += 2  # Пропускаем следующий параграф, т.к. уже обработали
                        continue
                i += 1
        
        # Если инструкции все еще не найдены, ищем нумерованные параграфы в формате "1. Название:", "2. Название:"
        if not steps:
            paragraphs = entry_content.find_all('p')
            for p in paragraphs:
                text = self.clean_text(p.get_text())
                
                # Проверяем, начинается ли текст с цифры и точки (например, "1. Den Teig vorbereiten:")
                # или с жирного текста "**1. Den Teig:**"
                match = re.match(r'^(\d+)\.\s*(.+)', text, re.IGNORECASE)
                if match:
                    instruction_num, instruction_text = match.groups()
                    # Убираем жирные маркеры ** из текста
                    instruction_text = re.sub(r'\*\*', '', instruction_text)
                    instruction_text = self.clean_text(instruction_text)
                    if instruction_text and len(instruction_text) > 10:
                        steps.append(instruction_text)
        
        # Объединяем все шаги в одну строку через пробел
        if steps:
            instructions = ' '.join(steps)
            # Добавляем точку в конце, если её нет
            if not instructions.endswith(('.', '!', '?')):
                instructions += '.'
            return instructions
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления из текста инструкций"""
        instructions = self.extract_instructions()
        if not instructions:
            return None
        
        # Ищем паттерн времени в инструкциях
        # Примеры: "15-20 Minuten", "30 Minuten", "1 Stunde"
        time_pattern = r'(\d+(?:\s*-\s*\d+)?)\s*(Minuten|Minute|Stunden|Stunde|min|Min)'
        match = re.search(time_pattern, instructions, re.IGNORECASE)
        
        if match:
            time_value = match.group(1).strip()
            time_unit = match.group(2).strip()
            
            # Нормализуем единицы
            if time_unit.lower() in ['minute', 'minuten', 'min']:
                return f"{time_value} minutes"
            elif time_unit.lower() in ['stunde', 'stunden']:
                return f"{time_value} hours"
            
            return f"{time_value} {time_unit}"
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории - для rezepteoma.com обычно не указана"""
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки - обычно не указано отдельно"""
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени - обычно не указано отдельно"""
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок - обычно не указаны"""
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов - обычно не указаны"""
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем в meta-тегах
        # og:image - обычно главное изображение
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
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
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "notes": self.extract_notes(),
            "tags": self.extract_tags(),
            "image_urls": self.extract_image_urls()
        }


def main():
    """
    Точка входа для обработки директории с HTML-страницами rezepteoma.com
    """
    import os
    
    # Путь к директории с примерами
    preprocessed_dir = os.path.join(
        Path(__file__).parent.parent,
        "preprocessed",
        "rezepteoma_com"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(RezepteomaComExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python rezepteoma_com.py")


if __name__ == "__main__":
    main()
