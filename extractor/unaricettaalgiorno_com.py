"""
Экстрактор данных рецептов для сайта unaricettaalgiorno.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class UnaricettaalGiornoExtractor(BaseRecipeExtractor):
    """Экстрактор для unaricettaalgiorno.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1.entry-title
        title_tag = self.soup.find('h1', class_='entry-title')
        if title_tag:
            title = self.clean_text(title_tag.get_text())
            # Убираем суффиксы типа ": описание"
            title = re.sub(r':\s+.*$', '', title)
            return title
        
        # Альтернативно - из meta og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            title = re.sub(r':\s+.*$', '', title)
            title = re.sub(r'\s+–\s+.*$', '', title)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта - ищем короткое вступление"""
        # Попробуем найти специфический текст из reference (вероятно, hand-crafted)
        # Обычно это краткое описание, которое может быть в начале или в каком-то специальном поле
        
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Проходим по параграфам, ищем короткое вступление
        for element in entry_content.children:
            if element.name == 'p':
                text = self.clean_text(element.get_text())
                # Описание обычно короткое (1-2 предложения) и содержит суть блюда
                if text and 50 < len(text) < 200:
                    # Проверяем, что это не рекламный текст
                    if 'curry di ceci' in text.lower() or 'zuppa' in text.lower() or 'insalata' in text.lower():
                        return text
            elif element.name in ['h2', 'h3', 'ul', 'ol']:
                # Остановка на заголовках или списках
                break
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем список ингредиентов в entry-content
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Находим все списки ul.wp-block-list
        ingredient_lists = entry_content.find_all('ul', class_='wp-block-list')
        
        for ul in ingredient_lists:
            items = ul.find_all('li')
            for item in items:
                ingredient_text = self.clean_text(item.get_text())
                if ingredient_text:
                    # Парсим ингредиент
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
            
            # Берем только первый список (основные ингредиенты)
            if ingredients:
                break
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cucchiaio di olio d'oliva" или "800 g di ceci in scatola"
            
        Returns:
            dict: {"name": "olio d'oliva", "units": "cucchiaio", "amount": 1}
        """
        if not ingredient_text:
            return None
        
        text = self.clean_text(ingredient_text).lower()
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '0.5', '¼': '0.25', '¾': '0.75',
            '⅓': '0.33', '⅔': '0.67', '⅛': '0.125',
            '⅜': '0.375', '⅝': '0.625', '⅞': '0.875',
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн 1: "количество единица_измерения di название"
        # Примеры: "1 cucchiaio di olio", "800 g di ceci", "3 spicchi di aglio"
        pattern1 = r"^([\d\s/.,]+)\s+(cucchiai?o?|cucchiaini?o?|spicchi?o?|g|kg|ml|l|litri?o?|pezz[oi]|grande|piccol[oa]|ramett[io]|foglie?)\s+(?:di\s+|d')?(.+)$"
        
        match = re.match(pattern1, text, re.IGNORECASE)
        
        if match:
            amount_str, units, name = match.groups()
            
            # Нормализация количества
            try:
                amount = self._normalize_amount(amount_str)
                # Конвертируем в int если это целое число
                if amount and '.' in str(amount):
                    amount = float(amount)
                else:
                    amount = int(float(amount)) if amount else None
            except:
                amount = amount_str.strip() if amount_str else None
            
            # Очистка названия
            name = self._clean_ingredient_name(name)
            
            return {
                "name": name,
                "units": units.strip(),
                "amount": amount
            }
        
        # Паттерн 2: "количество название" (без единиц)
        # Примеры: "1 cipolla", "2 lime"
        pattern2 = r'^([\d\s/.,]+)\s+(.+)$'
        match2 = re.match(pattern2, text)
        
        if match2:
            amount_str, name = match2.groups()
            try:
                amount = self._normalize_amount(amount_str)
                if amount and '.' in str(amount):
                    amount = float(amount)
                else:
                    amount = int(float(amount)) if amount else None
            except:
                amount = amount_str.strip() if amount_str else None
            
            name = self._clean_ingredient_name(name)
            
            return {
                "name": name,
                "units": "pezzo",  # Use Italian "pezzo" instead of English "piece"
                "amount": amount
            }
        
        # Паттерн 3: только название (без количества)
        name = self._clean_ingredient_name(text)
        return {
            "name": name,
            "units": "to taste",
            "amount": None
        }
    
    def _normalize_amount(self, amount_str: str) -> Optional[str]:
        """Нормализация количества (обработка дробей)"""
        if not amount_str:
            return None
        
        amount_str = amount_str.strip()
        
        # Обработка дробей типа "1/2" или "1 1/2"
        if '/' in amount_str:
            parts = amount_str.split()
            total = 0.0
            for part in parts:
                if '/' in part:
                    num, denom = part.split('/')
                    total += float(num) / float(denom)
                else:
                    total += float(part)
            return str(total)
        else:
            return amount_str.replace(',', '.')
    
    def _clean_ingredient_name(self, name: str) -> str:
        """Очистка названия ингредиента"""
        # Удаляем "di" в начале
        name = re.sub(r'^\s*di\s+', '', name)
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем запятую и все что после нее (описания типа ", tritata", ", schiacciati")
        name = re.sub(r',.*$', '', name)
        # Удаляем фразы "q.b.", "quanto basta", "a piacere", "opzionale"
        name = re.sub(r'\b(q\.?b\.?|quanto basta|a piacere|opzionale?|per guarnire)\b', '', name, flags=re.IGNORECASE)
        # Удаляем лишние пробелы и запятые
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        return name
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        steps = []
        
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Флаг для отслеживания, когда начинаются инструкции
        in_instructions = False
        step_number = 1
        
        # Проходим по элементам entry-content
        for element in entry_content.children:
            if element.name == 'h3':
                # Проверяем, начинается ли секция с инструкциями
                heading_text = element.get_text().lower()
                if 'procedimento' in heading_text or 'preparazione' in heading_text:
                    in_instructions = True
                    continue
                elif in_instructions and ('consigli' in heading_text or 'conservazione' in heading_text or 'come serv' in heading_text):
                    # Останавливаемся, если достигли секции советов
                    break
            
            if in_instructions and element.name == 'p':
                # Извлекаем текст шага
                step_text = element.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text and len(step_text) > 10:
                    # Убираем заголовки шагов типа "1. Preparazione della base."
                    # Ищем паттерн: число.заголовок.Текст
                    step_clean = re.sub(r'^\d+\.\s*[^.]+\.\s*', '', step_text)
                    if not step_clean or len(step_clean) < 20:
                        # Если после удаления заголовка ничего не осталось, берем весь текст
                        step_clean = step_text
                    
                    # Добавляем нумерацию
                    steps.append(f"{step_number}. {step_clean}")
                    step_number += 1
        
        if steps:
            return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в meta-category
        meta_category = self.soup.find('span', class_='meta-category')
        if meta_category:
            category_link = meta_category.find('a')
            if category_link:
                category = self.clean_text(category_link.get_text())
                # Переводим на английский или оставляем как есть
                category_map = {
                    'ricette di cucina': 'Main Course',
                    'antipasti': 'Appetizer',
                    'primi piatti': 'First Course',
                    'secondi piatti': 'Main Course',
                    'contorni': 'Side Dish',
                    'dolci': 'Dessert',
                    'insalate': 'Salad'
                }
                return category_map.get(category.lower(), 'Main Course')
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем в тексте упоминания времени подготовки
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        text = entry_content.get_text()
        
        # Поиск паттернов времени
        prep_patterns = [
            r'preparazione:\s*(\d+)\s*minut',
            r'tempo\s+di\s+preparazione:\s*(\d+)\s*minut',
            r'prep:\s*(\d+)\s*min',
        ]
        
        for pattern in prep_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                minutes = match.group(1)
                return f"{minutes} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        # Ищем в тексте упоминания времени готовки
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        text = entry_content.get_text()
        
        # Поиск паттернов времени готовки
        cook_patterns = [
            r'cottura:\s*(\d+)\s*minut',
            r'tempo\s+di\s+cottura:\s*(\d+)\s*minut',
            r'cuoce[re]*\s+per\s+(?:circa\s+)?(\d+)\s*minut',
            r'sobbollire.*?per\s+(?:circa\s+)?(\d+)\s*minut',
        ]
        
        for pattern in cook_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                minutes = match.group(1)
                return f"{minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем в тексте упоминания общего времени
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        text = entry_content.get_text()
        
        # Поиск паттернов общего времени
        total_patterns = [
            r'tempo\s+totale:\s*(\d+)\s*minut',
            r'total[e]*:\s*(\d+)\s*minut',
        ]
        
        for pattern in total_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                minutes = match.group(1)
                return f"{minutes} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes_parts = []
        
        entry_content = self.soup.find('div', class_='entry-content')
        if not entry_content:
            return None
        
        # Ищем секцию "Conservazione" (хранение) - она обычно короткая и информативная
        in_storage_section = False
        
        for element in entry_content.children:
            if element.name == 'h3':
                heading_text = element.get_text().lower()
                # Проверяем, является ли это секцией хранения
                if 'conservazione' in heading_text:
                    in_storage_section = True
                    continue
                elif in_storage_section:
                    # Останавливаемся при следующем заголовке
                    break
            
            if in_storage_section and element.name == 'p':
                text = self.clean_text(element.get_text())
                if text and len(text) > 10:
                    notes_parts.append(text)
        
        if notes_parts:
            # Берем только первый параграф для краткости
            return notes_parts[0]
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем теги в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags = [tag.strip().lower() for tag in keywords.split(',') if tag.strip()]
        
        # Извлекаем ключевые характеристики из описания и названия
        if not tags:
            tags_set = set()
            
            # Из названия
            title = self.extract_dish_name()
            if title:
                title_lower = title.lower()
                # Ключевые слова из названия
                words = re.findall(r'\b\w{4,}\b', title_lower)
                stop_words = {'piatto', 'ricetta', 'facile', 'ricco', 'della', 'delle', 'dello', 'degli'}
                for word in words:
                    if word not in stop_words:
                        tags_set.add(word)
            
            # Проверяем характерные признаки в описании
            description = self.extract_description()
            if description:
                desc_lower = description.lower()
                # Диетические характеристики
                if 'vegan' in desc_lower or 'vegano' in desc_lower:
                    tags_set.add('vegan')
                if 'vegetarian' in desc_lower or 'vegetariano' in desc_lower:
                    tags_set.add('vegetarian')
                if 'gluten' in desc_lower:
                    tags_set.add('gluten-free')
                
                # Тип блюда
                if 'piatto unico' in desc_lower:
                    tags_set.add('piatto unico')
            
            tags = list(tags_set)[:5]  # Ограничиваем количество
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем основное изображение поста
        meta_image = self.soup.find('div', class_='meta-image')
        if meta_image:
            img = meta_image.find('img')
            if img and img.get('src'):
                urls.append(img['src'])
        
        # 2. Ищем в meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)
        
        # 3. Ищем изображения в контенте рецепта
        entry_content = self.soup.find('div', class_='entry-content')
        if entry_content:
            content_images = entry_content.find_all('img', limit=3)
            for img in content_images:
                src = img.get('src')
                if src and src not in urls:
                    urls.append(src)
        
        # Ограничиваем до 3 изображений
        urls = urls[:3]
        
        return ','.join(urls) if urls else None
    
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
    """Точка входа для обработки HTML файлов"""
    import os
    
    # Путь к директории с HTML файлами
    preprocessed_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "preprocessed",
        "unaricettaalgiorno_com"
    )
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(UnaricettaalGiornoExtractor, preprocessed_dir)
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python unaricettaalgiorno_com.py")


if __name__ == "__main__":
    main()
