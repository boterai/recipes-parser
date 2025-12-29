"""
Экстрактор данных рецептов для сайта veganhome.it
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class VeganhomeItExtractor(BaseRecipeExtractor):
    """Экстрактор для veganhome.it"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в title
        title = self.soup.find('title')
        if title:
            title_text = title.get_text()
            # Убираем суффиксы типа " - Ricetta vegan [VeganHome]", "Ricetta ... [VeganHome]"
            title_text = re.sub(r'\s*-\s*Ricetta.*$', '', title_text, flags=re.IGNORECASE)
            title_text = re.sub(r'\s*Ricetta\s+', '', title_text, flags=re.IGNORECASE)
            title_text = re.sub(r'\s*\[VeganHome\].*$', '', title_text, flags=re.IGNORECASE)
            title_text = re.sub(r'\s*\(.*?\)\s*', ' ', title_text)  # Убираем скобки
            return self.clean_text(title_text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Убираем префикс "Ricetta <название> - "
            desc = re.sub(r'^Ricetta\s+[^-]+-\s*', '', desc)
            desc = self.clean_text(desc)
            return desc if desc else None
        
        return None
    
    def parse_ingredient_line(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Patterns to handle:
        - "250 g di polenta istantanea" -> {name: "polenta istantanea", units: "g", amount: 250}
        - "1 litro di acqua" -> {name: "acqua", units: "litro", amount: 1}
        - "un cucchiaio succo di limone" -> {name: "succo di limone", units: "cucchiaio", amount: 1}
        - "un cucchiaio di semi di lino tritati" -> {name: "semi di lino tritati", units: "cucchiaio", amount: 1}
        - "un pizzico di sale" -> {name: "sale", units: "pizzico", amount: 1} OR {name: "sale", units: None, amount: "un pizzico"}
        - "una manciata di piselli freschi" -> {name: "piselli freschi", units: None, amount: "una manciata"}
        - "riso basmati a piacere" -> {name: "riso basmati", units: "a piacere", amount: None}
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Pattern 1: Number + unit + "di" + name
        # Examples: "250 g di polenta istantanea", "1 litro di acqua", "200 grammi di insalata"
        pattern1 = r'^(\d+(?:[.,]\d+)?)\s+(g|grammi?|kg|litro?|ml|cespi?)\s+di\s+(.+)$'
        match = re.match(pattern1, text, re.IGNORECASE)
        if match:
            amount_str, unit, name = match.groups()
            amount = float(amount_str.replace(',', '.')) if '.' in amount_str or ',' in amount_str else int(amount_str)
            # Remove parenthetical notes
            name = re.sub(r'\s*\([^)]+\)\s*', ' ', name).strip()
            return {
                "name": name,
                "units": unit,
                "amount": amount
            }
        
        # Pattern 2: Number + unit + "di" + name (for cucchiai/cucchiaini)
        # Examples: "2 cucchiai di olio", "3 cucchiai di olio", "1 cucchiaino di curcuma"
        pattern2 = r'^(\d+(?:[.,]\d+)?)\s+(cucchiaio|cucchiai|cucchiaino|cucchiaini)\s+di\s+(.+)$'
        match = re.match(pattern2, text, re.IGNORECASE)
        if match:
            amount_str, unit, name = match.groups()
            amount = float(amount_str.replace(',', '.')) if '.' in amount_str or ',' in amount_str else int(amount_str)
            name = re.sub(r'\s*\([^)]+\)\s*', ' ', name).strip()
            return {
                "name": name,
                "units": unit,
                "amount": amount
            }
        
        # Pattern 3: "un/una" + unit + "di" + name
        # Examples: "un cucchiaio di semi di lino tritati", "un cucchiaino di tahini", "un pizzico di sale"
        # This is tricky because "un pizzico" can be either units="pizzico" or amount="un pizzico"
        pattern3 = r'^(un[ao]?)\s+(cucchiaio|cucchiai|cucchiaino|cucchiaini|pizzico)\s+di\s+(.+)$'
        match = re.match(pattern3, text, re.IGNORECASE)
        if match:
            quant, unit, name = match.groups()
            name = re.sub(r'\s*\([^)]+\)\s*', ' ', name).strip()
            
            # For cucchiaio/cucchiaino: always extract as units
            if 'cucchiai' in unit.lower() or 'cucchiaino' in unit.lower() or 'cucchiaini' in unit.lower():
                return {
                    "name": name,
                    "units": unit,
                    "amount": 1
                }
            
            # For pizzico: check if it's a simple ingredient (1 word) or complex (multiple words)
            # Simple ingredients like "sale" get units="pizzico"
            # Complex ingredients like "basilico tritato" get amount="un pizzico"
            if 'pizzico' in unit.lower() or 'pizzichi' in unit.lower():
                # Check if the name is simple (one word, common ingredient)
                # Common simple kitchen ingredients
                simple_ingredients = ['sale', 'pepe', 'zucchero', 'farina', 'olio', 'acqua']
                name_words = name.split()
                
                if len(name_words) == 1 and name.lower() in simple_ingredients:
                    # Simple ingredient: extract units
                    return {
                        "name": name,
                        "units": "pizzico",
                        "amount": 1
                    }
                else:
                    # Complex ingredient: keep "un pizzico" as amount
                    return {
                        "name": name,
                        "units": None,
                        "amount": "un pizzico"
                    }
            
            return {
                "name": name,
                "units": unit,
                "amount": 1
            }
        
        # Pattern 4: "un/una" + unit + name (without "di")
        # Examples: "un cucchiaio succo di limone", "mezzo cucchiaio succo di arancia"
        pattern4 = r'^(un[ao]?|mezz[ao]?)\s+(cucchiaio|cucchiai|cucchiaino|cucchiaini)\s+(.+)$'
        match = re.match(pattern4, text, re.IGNORECASE)
        if match:
            quant, unit, name = match.groups()
            name = re.sub(r'\s*\([^)]+\)\s*', ' ', name).strip()
            
            amount = 1 if quant.lower().startswith('un') else 0.5
            return {
                "name": name,
                "units": unit,
                "amount": amount
            }
        
        # Pattern 5: "una manciata di" + name
        pattern5 = r'^una\s+manciata\s+di\s+(.+)$'
        match = re.match(pattern5, text, re.IGNORECASE)
        if match:
            name = match.group(1)
            # Remove parenthetical notes
            name = re.sub(r'\s*\([^)]+\)\s*', ' ', name).strip()
            return {
                "name": name,
                "units": None,
                "amount": "una manciata"
            }
        
        # Pattern 6: Simple number + name (no unit)
        # Examples: "1 carota", "2 pomodori", "1 gambo di sedano"
        pattern6 = r'^(\d+)\s+(.+)$'
        match = re.match(pattern6, text)
        if match:
            amount_str, name = match.groups()
            amount = int(amount_str)
            name = re.sub(r'\s*\([^)]+\)\s*', ' ', name).strip()
            return {
                "name": name,
                "units": None,
                "amount": amount
            }
        
        # Pattern 7: Name + "a piacere"
        # Example: "riso basmati a piacere"
        pattern7 = r'^(.+?)\s+a\s+piacere$'
        match = re.match(pattern7, text, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            return {
                "name": name,
                "units": "a piacere",
                "amount": None
            }
        
        # Pattern 8: Just ingredient name (no amount, no unit)
        # Examples: "sale", "olio extravergine d'oliva"
        return {
            "name": text,
            "units": None,
            "amount": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем список ингредиентов через класс "safe"
        ingredient_list = self.soup.find('ul', class_='safe')
        
        if ingredient_list:
            items = ingredient_list.find_all('li')
            
            for item in items:
                ingredient_text = item.get_text(strip=True)
                parsed = self.parse_ingredient_line(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Ищем заголовок "Preparazione" и берем следующий параграф
        preparazione_header = self.soup.find('h2', string=re.compile(r'Preparazione', re.I))
        
        if preparazione_header:
            # Берем следующий элемент p
            next_p = preparazione_header.find_next('p')
            if next_p:
                # Извлекаем текст, заменяя <br> на пробелы
                text = next_p.get_text(separator=' ', strip=True)
                return self.clean_text(text)
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # В примерах не было информации о питательности
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в хлебных крошках (breadcrumbs)
        # Пример: <a href="/ricette/antipasti/">Antipasti</a>
        breadcrumb_links = self.soup.find_all('a', href=re.compile(r'/ricette/[^/]+/$'))
        
        if breadcrumb_links:
            # Берем последнюю категорию
            category = breadcrumb_links[-1].get_text(strip=True)
            return self.clean_text(category)
        
        # Альтернативно из URL
        canonical = self.soup.find('link', rel='canonical')
        if canonical and canonical.get('href'):
            url = canonical['href']
            # Извлекаем категорию из URL вида /ricette/antipasti/...
            match = re.search(r'/ricette/([^/]+)/', url)
            if match:
                category = match.group(1).replace('-', ' ').title()
                return self.clean_text(category)
        
        return None
    
    def extract_time_from_display(self) -> Optional[str]:
        """
        Извлечение времени из блока с иконкой часов
        Это может быть total_time или prep_time в зависимости от рецепта
        """
        # Ищем элемент с иконкой часов
        clock_icon = self.soup.find('i', class_=re.compile(r'fa-clock', re.I))
        
        if clock_icon:
            # Ищем родительский элемент p
            parent_p = clock_icon.find_parent('p')
            if parent_p:
                time_text = parent_p.get_text(strip=True)
                # Убираем текст иконки и лишние пробелы
                time_text = self.clean_text(time_text)
                # Возвращаем как есть (не нормализуем minuti -> minutes, чтобы соответствовать reference)
                return time_text if time_text else None
        
        return None
    
    def extract_cook_time_from_instructions(self) -> Optional[str]:
        """
        Извлечение времени готовки из текста инструкций
        Ищет паттерны типа "circa 20 minuti", "per 20 minuti", "20 minutes"
        """
        instructions = self.extract_instructions()
        if not instructions:
            return None
        
        # Паттерны для поиска времени в тексте
        patterns = [
            r'(?:circa|per)\s+(\d+)\s*minut[oi]',  # "circa 20 minuti", "per 20 minuti"
            r'(\d+)\s*minutes?',  # "20 minutes"
            r'(\d+)°.*?(\d+)\s*minut[oi]',  # "200° per circa 20 minuti"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, instructions, re.IGNORECASE)
            if match:
                # Берем последнюю группу (время в минутах)
                time_value = match.group(match.lastindex if match.lastindex else 1)
                return f"{time_value} minutes"
        
        return None
    
    def has_cooking_in_instructions(self) -> bool:
        """
        Проверяет, упоминается ли готовка/варка в инструкциях
        """
        instructions = self.extract_instructions()
        if not instructions:
            return False
        
        # Ключевые слова, указывающие на процесс готовки
        cooking_keywords = [
            r'\bcuoce[re]',  # cuocere, cuocerci
            r'\bcottura',
            r'\bforno',
            r'\bsobbollire',
            r'\bebollizione',
            r'\bfriggere',
            r'\barrostire',
        ]
        
        for keyword in cooking_keywords:
            if re.search(keyword, instructions, re.IGNORECASE):
                return True
        
        return False
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Время подготовки - это общее время для рецептов без готовки (салаты и т.д.)
        # Если есть готовка, то prep_time = None
        
        time_display = self.extract_time_from_display()
        has_cooking = self.has_cooking_in_instructions()
        
        # Если нет готовки, то время из дисплея - это prep_time
        # (уже нормализовано в extract_time_from_display)
        if time_display and not has_cooking:
            return time_display
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Сначала пытаемся найти специфичное время готовки в инструкциях
        cook_time_from_text = self.extract_cook_time_from_instructions()
        if cook_time_from_text:
            return cook_time_from_text  # Уже в формате "XX minutes"
        
        # Если есть упоминание готовки, но нет специфичного времени,
        # используем общее время как cook_time
        time_display = self.extract_time_from_display()
        has_cooking = self.has_cooking_in_instructions()
        
        if time_display and has_cooking:
            # Нормализуем "minuti" -> "minutes" для cook_time
            time_display = re.sub(r'(\d+)\s*minuti', r'\1 minutes', time_display, flags=re.IGNORECASE)
            return time_display
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Общее время - это время из дисплея, если есть готовка
        time_display = self.extract_time_from_display()
        has_cooking = self.has_cooking_in_instructions()
        
        # Если есть готовка, то время из дисплея - это total_time
        if time_display and has_cooking:
            # Нормализуем "minuti" -> "minutes" для total_time
            time_display = re.sub(r'(\d+)\s*minuti', r'\1 minutes', time_display, flags=re.IGNORECASE)
            return time_display
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с заголовком "Note"
        notes_header = self.soup.find('h2', string=re.compile(r'Note', re.I))
        
        if notes_header:
            # Берем следующий параграф
            next_p = notes_header.find_next('p')
            if next_p:
                text = next_p.get_text(separator=' ', strip=True)
                # Убираем лишние точки в конце
                text = re.sub(r'\.{2,}$', '', text)
                # Добавляем финальную точку, если её нет
                if text and not text.endswith('.'):
                    text = text + '.'
                text = self.clean_text(text)
                return text if text else None
        
        # НЕ извлекаем copyright как notes - только явные Note секции
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # В примерах тегов не было
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # Ищем изображение в контенте
        img_thumbnail = self.soup.find('img', class_='img-thumbnail')
        if img_thumbnail and img_thumbnail.get('src'):
            src = img_thumbnail['src']
            # Преобразуем относительный URL в абсолютный
            if src.startswith('/'):
                src = f"https://www.veganhome.it{src}"
            if src not in urls:
                urls.append(src)
        
        # Убираем дубликаты
        if urls:
            return ','.join(urls)
        
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
    import os
    # Обрабатываем папку preprocessed/veganhome_it
    preprocessed_dir = os.path.join("preprocessed", "veganhome_it")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(VeganhomeItExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python veganhome_it.py")


if __name__ == "__main__":
    main()
