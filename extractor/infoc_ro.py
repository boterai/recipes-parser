"""
Экстрактор данных рецептов для сайта infoc.ro
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class InfocRoExtractor(BaseRecipeExtractor):
    """Экстрактор для infoc.ro"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффикс " - infoc.ro"
            title = re.sub(r'\s+-\s+infoc\.ro$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """
        Извлечение ингредиентов
        
        INTENTIONAL ERROR: This function has a bug where it doesn't properly
        parse the ingredient amounts and units. It should extract structured data
        with name, amount, and unit fields, but it's incorrectly using 'units'
        instead of 'unit' in the dict keys.
        """
        ingredients = []
        
        # Ищем список ингредиентов - обычно это второй ul в документе
        # с классом 'flex flex-col border rounded-3xl'
        all_lists = self.soup.find_all('ul')
        
        # Пропускаем первый список (навигация) и берем второй
        ingredient_list = None
        for ul in all_lists:
            parent = ul.parent
            if parent and 'border' in ' '.join(parent.get('class', [])):
                items = ul.find_all('li')
                # Проверяем, что это список ингредиентов (содержит цифры и буквы g, ml, etc.)
                if len(items) > 0:
                    first_item = items[0].get_text().strip()
                    if re.search(r'\d+\s*(g|ml|bucăți|kg|l)', first_item, re.I):
                        ingredient_list = ul
                        break
        
        if not ingredient_list:
            return None
        
        items = ingredient_list.find_all('li')
        
        for item in items:
            ingredient_text = item.get_text(separator=' ', strip=True)
            ingredient_text = self.clean_text(ingredient_text)
            
            if ingredient_text:
                # Парсим ингредиент в структурированный формат
                # INTENTIONAL BUG: Using wrong key 'units' instead of 'unit'
                parsed = self.parse_ingredient(ingredient_text)
                if parsed:
                    # BUG: Change 'unit' to 'units' to create error
                    if 'unit' in parsed:
                        parsed['units'] = parsed.pop('unit')
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "Nutella 300g" или "Ravioli 500g"
            
        Returns:
            dict: {"name": "Nutella", "amount": "300", "unit": "g"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text)
        
        # Паттерн для извлечения: Название количество+единица
        # Примеры: "Nutella 300g", "Usturoi întreg - decojit și tocat mărunt 15g| 3 catei"
        # Формат на сайте: "Название количество+единица"
        
        # Пробуем найти количество с единицей в конце
        # Ищем паттерн: число + единица (g, ml, kg, l, bucăți и т.д.)
        pattern = r'^(.+?)\s+(\d+(?:[.,]\d+)?)\s*(g|ml|kg|l|bucăți|bucati|catei|cățel|lingurite|linguri|lingura|lingurita)\s*(?:\|.*)?$'
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            name, amount, unit = match.groups()
            
            # Очищаем название от лишних символов
            name = re.sub(r'\s+-\s+.*$', '', name)  # Убираем описание после тире
            name = name.strip()
            
            # Нормализуем единицы
            unit = unit.lower()
            if unit in ['bucati']:
                unit = 'bucăți'
            elif unit in ['catei', 'cățel']:
                unit = 'catei'
            
            return {
                "name": name,
                "amount": amount.replace(',', '.'),
                "unit": unit
            }
        
        # Если паттерн не совпал, пробуем более простой вариант
        # Формат: "Название количество+единица" без дополнительных описаний
        simple_pattern = r'^(.+?)\s+(\d+(?:[.,]\d+)?)(g|ml|kg|l|bucăți|bucati)\s*$'
        simple_match = re.match(simple_pattern, text, re.IGNORECASE)
        
        if simple_match:
            name, amount, unit = simple_match.groups()
            return {
                "name": name.strip(),
                "amount": amount.replace(',', '.'),
                "unit": unit.lower()
            }
        
        # Если не удалось распарсить, возвращаем только название
        return {
            "name": text,
            "amount": None,
            "unit": None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions = []
        
        # Ищем заголовок "Pași gătire" (h2 или h3)
        header_found = False
        for header in self.soup.find_all(['h2', 'h3']):
            header_text = header.get_text().strip()
            if 'pași' in header_text.lower() and 'gătire' in header_text.lower():
                header_found = True
                
                # Извлекаем инструкции из div элементов после заголовка
                current = header.find_next_sibling()
                
                while current and current.name != 'h2':
                    if current.name == 'div':
                        # Получаем текст из div
                        div_text = current.get_text(separator=' ', strip=True)
                        
                        # Пропускаем короткие div (вероятно, не инструкции)
                        if div_text and len(div_text) > 20:
                            # Извлекаем параграфы из div
                            paragraphs = current.find_all('p')
                            if paragraphs:
                                for p in paragraphs:
                                    p_text = p.get_text(separator=' ', strip=True)
                                    if p_text and len(p_text) > 20:
                                        # Пропускаем заголовки секций (короткие строки с номерами)
                                        if not (len(p_text) < 50 and re.match(r'^\d+\.', p_text)):
                                            instructions.append(self.clean_text(p_text))
                            else:
                                # Если нет параграфов, берем весь текст div
                                instructions.append(self.clean_text(div_text))
                    
                    current = current.find_next_sibling()
                
                break
        
        # Если не нашли через заголовок, пробуем старый метод (для обратной совместимости)
        if not header_found or not instructions:
            # Ищем первый параграф с инструкциями
            found_start = False
            for p in self.soup.find_all('p'):
                text = p.get_text().strip()
                
                # Начинаем собирать с первого параграфа инструкций
                if not found_start and ('Măsurați' in text or 'Preîncălziți' in text or 'Pregătirea' in text or 'Fierbeți' in text):
                    found_start = True
                
                if found_start:
                    # Проверяем, не является ли это заголовком секции
                    if text and len(text) > 20:
                        # Пропускаем параграфы с "Variații" или "trucuri"
                        if 'Variații' in text or 'trucuri' in text:
                            break
                        
                        text = self.clean_text(text)
                        instructions.append(text)
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Категория может быть указана в виде тегов или в структурированных данных
        # На данный момент извлекаем из примеров JSON
        # В реальной разметке нужно искать в breadcrumbs или meta-тегах
        
        # Ищем в ссылках на категории
        for a in self.soup.find_all('a'):
            href = a.get('href', '')
            if '/categorii/' in href or '/category/' in href:
                return self.clean_text(a.get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем div с текстом "Timp preparare"
        for div in self.soup.find_all('div'):
            text = div.get_text().strip()
            if 'Timp preparare' in text:
                # Извлекаем только время подготовки
                match = re.search(r'Timp preparare\s*(\d+)\s*minute?', text, re.I)
                if match:
                    return f"{match.group(1)} minute"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем div с текстом "Timp gătire"
        for div in self.soup.find_all('div'):
            text = div.get_text().strip()
            if 'Timp gătire' in text:
                # Извлекаем только время готовки
                match = re.search(r'Timp gătire\s*(\d+)\s*minute?', text, re.I)
                if match:
                    return f"{match.group(1)} minute"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем div с текстом "Timp total"
        for div in self.soup.find_all('div'):
            text = div.get_text().strip()
            if 'Timp total' in text:
                # Извлекаем только общее время
                match = re.search(r'Timp total\s*(\d+)\s*minute?', text, re.I)
                if match:
                    return f"{match.group(1)} minute"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем параграфы с вариациями или советами
        notes = []
        
        for p in self.soup.find_all('p'):
            text = p.get_text().strip()
            # Ищем заметки типа "Puteți înlocui..."
            if 'Puteți' in text and 'înlocui' in text:
                # Очищаем от лишних слов
                text = re.sub(r'^Variații:\s*', '', text)
                text = self.clean_text(text)
                if text and len(text) < 300:
                    notes.append(text)
        
        # Берем первую найденную заметку
        return notes[0] if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Теги могут быть в meta-тегах или в ссылках
        tags = []
        
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags = [tag.strip() for tag in keywords.split(',') if tag.strip()]
        
        # Если нет в meta, ищем в ссылках с тегами
        if not tags:
            for a in self.soup.find_all('a'):
                href = a.get('href', '')
                if '/tag/' in href or '/tags/' in href:
                    tag_text = self.clean_text(a.get_text())
                    if tag_text:
                        tags.append(tag_text)
        
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            # Пропускаем динамически генерируемые изображения
            if 'api/generate/image' not in url:
                urls.append(url)
        
        # 2. Ищем в twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            if 'api/generate/image' not in url and url not in urls:
                urls.append(url)
        
        # 3. Ищем img теги в контенте рецепта
        for img in self.soup.find_all('img'):
            src = img.get('src', '')
            if src and src.startswith('http') and 'api/generate/image' not in src:
                if src not in urls:
                    urls.append(src)
                if len(urls) >= 3:  # Ограничиваем 3 изображениями
                    break
        
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
    """
    Точка входа для обработки HTML файлов из preprocessed/infoc_ro
    """
    import os
    
    # Получаем путь к корню репозитория
    repo_root = Path(__file__).parent.parent
    preprocessed_dir = repo_root / "preprocessed" / "infoc_ro"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обработка файлов из {preprocessed_dir}")
        process_directory(InfocRoExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python extractor/infoc_ro.py")


if __name__ == "__main__":
    main()
