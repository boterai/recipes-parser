"""
Экстрактор данных рецептов для сайта mesterszakacs.hu
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class MesterszakacsExtractor(BaseRecipeExtractor):
    """Экстрактор для mesterszakacs.hu"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # На сайте mesterszakacs.hu нет явного описания, только meta description
        # но она содержит начало инструкций, поэтому возвращаем None
        return None
    
    def parse_ingredient_text(self, text: str) -> dict:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            text: Строка вида "2 vöröshagyma" или "10 dkg zsír vagy 6-7 evőkanál olaj"
            
        Returns:
            dict: {"name": "...", "units": "...", "amount": "..."}
        """
        if not text:
            return {"name": None, "units": None, "amount": None}
        
        text = self.clean_text(text).strip()
        
        # Паттерн для извлечения: [количество] [единица] название
        # Примеры: "2 vöröshagyma", "10 dkg zsír", "1.5 dl (15 dkg) rizsből főzött párolt rizs"
        
        # Единицы измерения на венгерском (non-capturing group)
        units_pattern = r'(?:dkg|kg|g|dl|l|ml|evőkanál|kiskanál|mokkáskanál|késhegynyi|csepp|csipet|db|darab|gerezd|fej|szál|csokor|nagy|púpozott|csapott)'
        
        # Пытаемся найти количество и единицу в начале строки
        # Паттерн: число (может быть диапазон с дефисом) + единица + остаток
        # Примеры: "10 dkg zsír", "40-50 dkg lilakáposzta"
        pattern = r'^([\d.,]+(?:\s*-\s*[\d.,]+)?)\s+(' + units_pattern + r')\s+(.+)$'
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount = match.group(1).strip()
            unit = match.group(2).strip() if match.group(2) else None
            name = match.group(3).strip() if match.group(3) else text
            
            # Очистка названия от скобок (например, "(15 dkg)")
            if name:
                name = re.sub(r'\([^)]*\)', '', name).strip()
            
            # Конвертируем amount в число если возможно
            try:
                if '-' not in amount and '.' not in amount:
                    amount = int(amount)
                elif '-' not in amount:
                    amount = float(amount)
                # Если есть диапазон, оставляем как строку
            except (ValueError, AttributeError):
                pass
            
            return {
                "name": name if name else text,
                "units": unit,
                "amount": amount
            }
        
        # Если нет единицы, но есть количество в начале
        # Примеры: "2 vöröshagyma", "1 tojás"
        pattern2 = r'^([\d.,\-]+(?:\s*-\s*[\d.,]+)?)\s+(.+)$'
        match2 = re.match(pattern2, text)
        
        if match2:
            amount = match2.group(1).strip()
            name = match2.group(2).strip()
            
            # Очистка названия
            name = re.sub(r'\([^)]*\)', '', name).strip()
            
            # Конвертируем amount в число если возможно
            try:
                if '-' not in amount and '.' not in amount:
                    amount = int(amount)
                elif '-' not in amount:
                    amount = float(amount)
            except (ValueError, AttributeError):
                pass
            
            return {
                "name": name,
                "units": "pieces",
                "amount": amount
            }
        
        # Если ничего не нашли, возвращаем только название
        return {
            "name": text,
            "units": None,
            "amount": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем все div с классом hozzavalokmobilitem
        ingredient_items = self.soup.find_all('div', class_='hozzavalokmobilitem')
        
        for item in ingredient_items:
            # Извлекаем текст, убирая маркер списка
            text = item.get_text()
            # Убираем маркер "•" и пробелы
            text = text.replace('•', '').strip()
            
            if text:
                parsed = self.parse_ingredient_text(text)
                if parsed and parsed['name']:
                    ingredients.append(parsed)
        
        if ingredients:
            return json.dumps(ingredients, ensure_ascii=False)
        
        return None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем все параграфы с классом methodline
        method_lines = self.soup.find_all('p', class_='methodline')
        
        for line in method_lines:
            # Извлекаем текст
            text = line.get_text(separator=' ', strip=True)
            text = self.clean_text(text)
            
            if text:
                steps.append(text)
        
        if steps:
            return ' '.join(steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем dt с текстом "Kategória"
        cat_dt = self.soup.find('dt', string=re.compile(r'Kategória', re.IGNORECASE))
        if cat_dt:
            # Находим следующий dd элемент
            cat_dd = cat_dt.find_next_sibling('dd')
            if cat_dd:
                return self.clean_text(cat_dd.get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # На сайте mesterszakacs.hu нет явного prep_time
        # Оставляем None, если не найдено
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем dt с текстом "Elkészítési idő"
        time_dt = self.soup.find('dt', string=re.compile(r'Elkészítési idő', re.IGNORECASE))
        if time_dt:
            time_dd = time_dt.find_next_sibling('dd')
            if time_dd:
                time_text = self.clean_text(time_dd.get_text())
                # Конвертируем "60-120 perc" в "60-120 minutes"
                if 'perc' in time_text.lower():
                    time_text = time_text.replace('perc', 'minutes')
                return time_text
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # На сайте mesterszakacs.hu нет явного total_time
        # Оставляем None, если не найдено
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с заметками/советами
        # На mesterszakacs.hu это обычно после method_full, с заголовком "fűződő történet, jótanács"
        
        # Ищем h2 с текстом содержащим "történet" или "jótanács"
        note_heading = self.soup.find('h2', string=re.compile(r'történet|jótanács', re.I))
        if note_heading:
            # Берем следующий параграф
            next_p = note_heading.find_next('p')
            if next_p:
                text = next_p.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                return text if text else None
        
        # Альтернативный вариант: ищем блок после method_full
        method_full = self.soup.find('div', id='method_full')
        if method_full:
            # Ищем следующий div/p после method_full
            next_elem = method_full.find_next_sibling()
            while next_elem and next_elem.name in ['h2', 'p', 'div']:
                if next_elem.name == 'p' and next_elem.get_text().strip():
                    text = next_elem.get_text(separator=' ', strip=True)
                    text = self.clean_text(text)
                    # Проверяем, что это не реклама или другой контент
                    if text and len(text) > 30 and not text.startswith('Még több'):
                        return text
                next_elem = next_elem.find_next_sibling()
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Стратегия: извлекаем из названия блюда
        dish_name = self.extract_dish_name()
        if dish_name:
            # Обрабатываем название
            name_lower = dish_name.lower()
            
            # Если название состоит из одного слова, добавляем его и категорию
            words_in_name = len(name_lower.split())
            if words_in_name == 1:
                tags.append(name_lower)
                # Добавляем категорию
                category = self.extract_category()
                if category:
                    tags.append(category.lower())
                return ', '.join(tags)
            
            # Для составных названий разбираем по частям
            # "Füstölt sajttal rakott, csőben sült zöldségek" -> ["füstölt sajttal rakott", "csőben sült zöldségek"]
            phrases = [p.strip() for p in name_lower.split(',')]
            
            # Обрабатываем каждую фразу
            for phrase in phrases:
                words = phrase.split()
                i = 0
                while i < len(words):
                    word = words[i]
                    
                    # Проверяем, не начинается ли с этого места устойчивое выражение
                    # Паттерны: "csőben sült", "jól főtt", и т.д. (adverb/postposition + participle)
                    if i + 1 < len(words):
                        next_word = words[i + 1]
                        # Если следующее слово - причастие
                        if next_word in ['sült', 'főtt', 'sütött', 'rakott', 'párolt', 'rántott', 'főzött']:
                            # И текущее слово заканчивается на характерные суффиксы (adverbial)
                            if word.endswith(('ben', 'ban', 'en', 'an', 'on', 'ön', 'en')):
                                # Сохраняем фразу из двух слов
                                tags.append(f"{word} {next_word}")
                                i += 2
                                continue
                    
                    # Обычная обработка слова
                    if len(word) > 2:
                        # Удаляем венгерские падежные окончания
                        word_cleaned = re.sub(r'(tal|tel|val|vel|nak|nek|ból|ből|ban|ben|hoz|hez|höz|ra|re|tól|től|ért|ba|be|on|en|ön|ak|ek|ok|ök)$', '', word)
                        
                        # Если после удаления суффикса слово стало слишком коротким, используем оригинал
                        if len(word_cleaned) > 2:
                            word = word_cleaned
                        
                        # Фильтруем стоп-слова
                        stopwords = {'a', 'az', 'és', 'vagy', 'de', 'meg', 'is', 'csak', 'mint', 'ha', 'ez', 'egy'}
                        if word not in stopwords:
                            tags.append(word)
                    
                    i += 1
        
        if tags:
            # Удаляем дубликаты, сохраняя порядок
            seen = set()
            unique_tags = []
            for tag in tags:
                if tag not in seen:
                    seen.add(tag)
                    unique_tags.append(tag)
            return ', '.join(unique_tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем img с id="recipeImage"
        recipe_img = self.soup.find('img', id='recipeImage')
        if recipe_img and recipe_img.get('src'):
            src = recipe_img['src']
            # Если URL относительный, добавляем домен
            if src.startswith('/'):
                src = 'https://mesterszakacs.hu' + src
            urls.append(src)
        
        # Также проверяем meta og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            if url not in urls:
                urls.append(url)
        
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
    # Обрабатываем папку preprocessed/mesterszakacs_hu
    preprocessed_dir = os.path.join("preprocessed", "mesterszakacs_hu")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        process_directory(MesterszakacsExtractor, str(preprocessed_dir))
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python mesterszakacs_hu.py")


if __name__ == "__main__":
    main()
