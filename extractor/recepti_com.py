"""
Экстрактор данных рецептов для сайта recepti.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ReceptiComExtractor(BaseRecipeExtractor):
    """Экстрактор для recepti.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем h1 с itemprop="name"
        h1_name = self.soup.find('h1', attrs={'itemprop': 'name'})
        if h1_name:
            return self.clean_text(h1_name.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # На recepti.com нет отдельного описания в HTML
        # Возвращаем None, как в эталонных JSON
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем элементы с itemprop="ingredients"
        ingredient_items = self.soup.find_all(attrs={'itemprop': 'ingredients'})
        
        for item in ingredient_items:
            ingredient_text = item.get_text(strip=True)
            ingredient_text = self.clean_text(ingredient_text)
            
            if ingredient_text:
                # Парсим в структурированный формат
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "4 svinjske šnicle" или "1 kašičica senfa"
            
        Returns:
            dict: {"name": "...", "amount": ..., "units": "..."} или None
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
        
        # Единицы измерения на сербском языке (только настоящие единицы измерения, не предметы)
        # Исключаем: šnite, kom, komad, čena, kocka и т.д. - это предметы, а не единицы
        units_pattern = r'(g|kg|ml|l|kašika|kašičica|kašike|kašičice|čaša|čaše|kesica|kesice|kutlača|kutlače|šolja|šolje|gr|po\s+ukusu|po\s+potrebi)'
        
        # Паттерн: число + единица + название или фраза + название
        pattern = r'^([\d\s/.,]+)?\s*(' + units_pattern + r')?\s*(.+)$'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, _, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            # Обработка дробей типа "1/2" или "1 1/2"
            if '/' in amount_str:
                parts = amount_str.split()
                total = 0
                for part in parts:
                    if '/' in part:
                        num, denom = part.split('/')
                        total += float(num) / float(denom)
                    else:
                        total += float(part)
                amount = total
            else:
                try:
                    amount = float(amount_str.replace(',', '.'))
                    # Если это целое число, оставляем как int
                    if amount == int(amount):
                        amount = int(amount)
                except ValueError:
                    amount = None
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "po ukusu", "po potrebi" из названия
        name = re.sub(r'\b(po ukusu|po potrebi)\b', '', name, flags=re.IGNORECASE)
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
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Ищем все элементы с itemprop="recipeInstructions"
        instructions_elems = self.soup.find_all(attrs={'itemprop': 'recipeInstructions'})
        
        if instructions_elems:
            steps = []
            for elem in instructions_elems:
                # Убираем вложенные изображения
                for img in elem.find_all('img'):
                    img.decompose()
                for a in elem.find_all('a', class_='fancybox'):
                    a.decompose()
                
                step_text = elem.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                if step_text:
                    steps.append(step_text)
            
            # Объединяем все шаги в одну строку
            return ' '.join(steps) if steps else None
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в breadcrumbs (хлебные крошки)
        breadcrumbs = self.soup.find('ul', class_='bc-items')
        if breadcrumbs:
            # Берем предпоследний элемент (последний - это сам рецепт)
            items = breadcrumbs.find_all('li', attrs={'itemprop': 'itemListElement'})
            if len(items) >= 2:
                # Ищем itemprop="name" в предпоследнем элементе
                category_elem = items[-2].find(attrs={'itemprop': 'name'})
                if category_elem:
                    return self.clean_text(category_elem.get_text())
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prepTime', 'cookTime', 'totalTime')
        """
        # Ищем элемент с соответствующим itemprop
        time_elem = self.soup.find(attrs={'itemprop': time_type})
        
        if time_elem:
            # Проверяем атрибут content (ISO 8601 формат)
            content = time_elem.get('content')
            if content:
                # Конвертируем ISO 8601 в минуты
                minutes = self.parse_iso_duration(content)
                if minutes:
                    return f"{minutes} min"
            
            # Если нет content, берем текст
            time_text = time_elem.get_text(strip=True)
            if time_text:
                return self.clean_text(time_text)
        
        return None
    
    @staticmethod
    def parse_iso_duration(duration: str) -> Optional[str]:
        """
        Конвертирует ISO 8601 duration в минуты
        
        Args:
            duration: строка вида "PT20M" или "PT1H30M"
            
        Returns:
            Время в минутах, например "90"
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
        
        return str(total_minutes) if total_minutes > 0 else None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Сначала пробуем найти prepTime
        prep = self.extract_time('prepTime')
        if prep:
            return prep
        
        # Если prepTime нет, но есть totalTime и нет cookTime,
        # используем totalTime как prep_time (как в эталонных данных)
        if not self.extract_time('cookTime'):
            total = self.extract_time('totalTime')
            if total:
                return total
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('cookTime')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('totalTime')
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с рекомендациями
        notes_section = self.soup.find('div', class_='recommend')
        
        if notes_section:
            # Извлекаем текст из параграфа
            p = notes_section.find('p')
            if p:
                text = self.clean_text(p.get_text())
                return text if text else None
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags_list = []
        
        # Ищем div с классом tags, который содержит span "Tagovi"
        tags_sections = self.soup.find_all('div', class_='tags')
        
        for tags_section in tags_sections:
            # Проверяем, есть ли внутри span с текстом "Tagovi"
            span = tags_section.find('span')
            if span and 'tagovi' in span.get_text().lower():
                # Извлекаем все ссылки на теги
                tag_links = tags_section.find_all('a', href=re.compile(r'/tag/'))
                
                for link in tag_links:
                    tag_text = self.clean_text(link.get_text())
                    if tag_text:
                        tags_list.append(tag_text)
                break
        
        # Возвращаем как строку через запятую без пробела
        return ','.join(tags_list) if tags_list else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем основное изображение рецепта с itemprop="image"
        main_image = self.soup.find('img', attrs={'itemprop': 'image'})
        if main_image and main_image.get('src'):
            src = main_image['src']
            # Преобразуем относительные URL в абсолютные
            if src.startswith('//'):
                src = 'https:' + src
            elif src.startswith('/'):
                src = 'https://www.recepti.com' + src
            urls.append(src)
        
        # 2. Ищем изображения шагов приготовления
        step_images = self.soup.find_all('a', class_='fancybox')
        for link in step_images:
            img = link.find('img')
            if img and img.get('src'):
                src = img['src']
                # Преобразуем относительные URL в абсолютные
                if src.startswith('//'):
                    src = 'https:' + src
                elif src.startswith('/'):
                    src = 'https://www.recepti.com' + src
                urls.append(src)
        
        # 3. Если не нашли через itemprop, ищем в meta og:image
        if not urls:
            og_image = self.soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                urls.append(og_image['content'])
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            # Возвращаем как строку через запятую без пробелов
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
    import os
    # Обрабатываем папку preprocessed/recepti_com
    recipes_dir = os.path.join("preprocessed", "recepti_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(ReceptiComExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python recepti_com.py")


if __name__ == "__main__":
    main()
