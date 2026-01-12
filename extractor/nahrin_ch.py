"""
Экстрактор данных рецептов для сайта nahrin.ch
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class NahrinChExtractor(BaseRecipeExtractor):
    """Экстрактор для nahrin.ch"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега
        meta_title = self.soup.find('meta', property='og:title')
        if meta_title and meta_title.get('content'):
            title = meta_title['content']
            # Убираем суффиксы
            title = re.sub(r'\s+\|.*$', '', title)
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
        """Извлечение ингредиентов в формате JSON"""
        ingredients = []
        
        # Ищем таблицу ингредиентов
        ingredients_table = self.soup.find('table', class_='cms-ingredients')
        
        if not ingredients_table:
            return None
        
        # Извлекаем строки таблицы
        rows = ingredients_table.find_all('tr', itemprop='recipeIngredient')
        
        for row in rows:
            # Получаем ячейки
            tds = row.find_all('td')
            
            if len(tds) < 2:
                continue
            
            # Первая ячейка - количество и единица измерения
            # Вторая ячейка - название ингредиента
            amount_unit_text = self.clean_text(tds[0].get_text())
            name_text = self.clean_text(tds[1].get_text())
            
            if not name_text:
                continue
            
            # Парсим количество и единицу измерения
            amount = None
            unit = None
            
            # Проверяем, если количество и единица в тексте названия
            # Паттерн 1: "2-3 cm Ingwer" -> amount="2-3", unit="cm", name="Ingwer"
            # Паттерн 2: "2-3 cm de gingembre" -> amount="2-3", unit="cm", name="gingembre"
            # Паттерн 3: "Radice di zenzero di 2-3 cm" -> amount="2-3", unit="cm", name="Radice di zenzero"
            
            if not amount_unit_text:
                # Попробуем паттерн в начале
                name_pattern_start = r'^([\d\s.,\-/]+)\s+([a-zA-Zäöüß]+)\s+(?:de\s+|d[\'])?(.+)$'
                name_match = re.match(name_pattern_start, name_text)
                
                if name_match:
                    # Паттерн в начале: "2-3 cm de gingembre"
                    amount = name_match.group(1).strip()
                    unit = name_match.group(2).strip()
                    name_text = name_match.group(3).strip()
                else:
                    # Попробуем паттерн в конце: "Radice di zenzero di 2-3 cm"
                    name_pattern_end = r'^(.+?)\s+(?:di|de)\s+([\d\s.,\-/]+)\s+([a-zA-Zäöüß]+)$'
                    name_match = re.match(name_pattern_end, name_text)
                    
                    if name_match:
                        name_text = name_match.group(1).strip()
                        amount = name_match.group(2).strip()
                        unit = name_match.group(3).strip()
            else:
                # Количество и единица в первой ячейке
                # Паттерн для извлечения количества и единицы
                # Примеры: "100 g", "2", "2-3 cm", "1-2 EL", "0.5 Bund", "1-2 c."
                pattern = r'^([\d\s.,\-/]+)?\s*([a-zA-Zäöüß.]+)?$'
                match = re.match(pattern, amount_unit_text)
                
                if match:
                    amount_str, unit_str = match.groups()
                    
                    if amount_str:
                        amount = amount_str.strip()
                    
                    if unit_str:
                        unit = unit_str.strip()
            
            # Удаляем французские/итальянские предлоги из начала названия
            # "de pousses d'épinard" -> "pousses d'épinard"
            # "d'huile pimentée" -> "huile pimentée"
            # "di spinaci baby" -> "spinaci baby"
            # Учитываем разные типы апострофов: ' (U+0027) и ' (U+2019)
            # Пробел после предлога может отсутствовать (например, d'huile)
            name_text = re.sub(r"^(de|di|d['\u2019])\s*", '', name_text)
            
            # Удаляем дополнительные фразы в конце (например, "en pot", "in vasetto")
            # "bouillon de bœuf Intenso & Puro Nahrin en pot" -> "bouillon de bœuf Intenso & Puro Nahrin"
            name_text = re.sub(r'\s+(en pot|in vasetto)$', '', name_text, flags=re.I)
            
            # Формируем словарь ингредиента
            ingredient = {
                "name": name_text,
                "units": unit,  # Используем "units" как в примере JSON
                "amount": amount
            }
            
            ingredients.append(ingredient)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций приготовления"""
        # Ищем список инструкций
        instructions_list = self.soup.find('ol', itemprop='recipeInstructions')
        
        if not instructions_list:
            return None
        
        steps = []
        
        # Извлекаем все элементы списка с itemprop="recipeInstructions"
        step_items = instructions_list.find_all('li', itemprop='recipeInstructions')
        
        for item in step_items:
            step_text = self.clean_text(item.get_text())
            if step_text:
                steps.append(step_text)
        
        # Соединяем шаги в одну строку через пробел
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории рецепта"""
        # Ищем в отдельных span-элементах внутри блока recipe-details
        # Категория находится в span без класса, внутри span class="hidden"
        recipe_div = self.soup.find('div', class_='cms-recipe-details')
        
        if recipe_div:
            # Ищем все span элементы
            spans = recipe_div.find_all('span')
            
            # Приоритет категорий (основные типы блюд)
            category_priority = [
                'suppe', 'soupe', 'zuppa',  # Soup
                'salat', 'salade', 'insalata',  # Salad
                'hauptspeise', 'plat principal', 'piatto principale',  # Main dish
                'vorspeise', 'entrée', 'antipasti',  # Appetizer
                'dessert'  # Dessert
            ]
            
            for span in spans:
                text = self.clean_text(span.get_text())
                
                # Проверяем, что это категория блюда (одно слово или короткая фраза)
                if text and len(text) < 30:
                    text_lower = text.lower()
                    # Проверяем по приоритету
                    for cat in category_priority:
                        if cat in text_lower and len(text) < 20:
                            # Исключаем span с множественными тегами
                            if not any(other_cat in text_lower for other_cat in category_priority if other_cat != cat):
                                return text
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем span с текстом "Vorbereitungszeit" / "Temps de préparation" / "Tempo di preparazione"
        time_spans = self.soup.find_all('span')
        
        for span in time_spans:
            text = span.get_text(strip=True)
            
            # Проверяем разные языки
            if any(keyword in text.lower() for keyword in ['vorbereitungszeit', 'temps de préparation', 'tempo di preparazione', 'préparation']):
                # Извлекаем число минут
                match = re.search(r'(\d+)', text)
                if match:
                    minutes = match.group(1)
                    return f"{minutes} minutes"
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем span с текстом "Kochzeit" / "Temps de cuisson" / "Tempo di cottura"
        time_spans = self.soup.find_all('span')
        
        for span in time_spans:
            text = span.get_text(strip=True)
            
            # Проверяем разные языки
            if any(keyword in text.lower() for keyword in ['kochzeit', 'temps de cuisson', 'tempo di cottura', 'cuisson', 'cottura']):
                # Извлекаем число минут
                match = re.search(r'(\d+)', text)
                if match:
                    minutes = match.group(1)
                    return f"{minutes} minutes"
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Вычисляем на основе prep + cook, или ищем в тексте
        prep = self.extract_prep_time()
        cook = self.extract_cook_time()
        
        if prep and cook:
            # Извлекаем числа из строк
            prep_match = re.search(r'(\d+)', prep)
            cook_match = re.search(r'(\d+)', cook)
            
            if prep_match and cook_match:
                total = int(prep_match.group(1)) + int(cook_match.group(1))
                return f"{total} minutes"
        
        # Альтернативно ищем в тексте "20 Minuten" и т.д.
        # В описании может быть упоминание общего времени
        description = self.extract_description()
        if description:
            # Ищем паттерн "XX минут" в разных языках
            match = re.search(r'(\d+)\s+(minuten|minutes|minuti)', description.lower())
            if match:
                minutes = match.group(1)
                return f"{minutes} minutes"
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем элемент списка с классом "flex", который содержит "Tipp:"
        list_items = self.soup.find_all('li', class_='flex')
        
        for li in list_items:
            text = self.clean_text(li.get_text())
            
            # Проверяем, что это совет (начинается с "Tipp:" или содержит советы)
            if text and len(text) > 50:
                # Убираем префикс "Tipp:" если есть
                text = re.sub(r'^Tipp\s*:\s*', '', text, flags=re.I)
                text = re.sub(r'^Conseil\s*:\s*', '', text, flags=re.I)
                text = re.sub(r'^Suggerimento\s*:\s*', '', text, flags=re.I)
                
                # Проверяем, что это действительно совет
                if any(keyword in text.lower() for keyword in [
                    'können sie', 'verwenden', 'schnelle zubereitung',
                    'vous pouvez', 'utiliser', 'préparation rapide',
                    'potete', 'utilizzare', 'preparazione rapida'
                ]):
                    return text
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов рецепта"""
        # Ищем теги в отдельных span-элементах внутри блока recipe-details
        # Теги находятся в span без класса, внутри span без класса или class="hidden"
        recipe_div = self.soup.find('div', class_='cms-recipe-details')
        
        if not recipe_div:
            return None
        
        tags = []
        
        # Ищем все span элементы
        spans = recipe_div.find_all('span')
        
        for span in spans:
            text = self.clean_text(span.get_text())
            
            # Пропускаем пустые, очень короткие и системные тексты
            if not text or len(text) < 3:
                continue
            
            # Проверяем, что span не находится внутри таблицы (не ингредиент)
            ancestors = [p.name for p in span.parents]
            if 'table' in ancestors:
                continue
            
            # Пропускаем тексты, которые явно не теги
            skip_keywords = [
                'autor', 'vorbereitungszeit', 'kochzeit', 'min', 'drucken',
                'zutaten', 'tipp', 'temps', 'cuisson', 'préparation',
                'autore', 'tempo', 'cottura', 'preparazione', 'stampa'
            ]
            
            if any(keyword in text.lower() for keyword in skip_keywords):
                continue
            
            # Проверяем, что span не содержит другие span (не является контейнером)
            if span.find('span'):
                continue
            
            # Проверяем, что это похоже на тег (короткий текст, не время, не автор)
            # и не является названием ингредиента
            parent_class = span.parent.get('class', [])
            
            # Теги обычно находятся в span с классом "hidden" или без класса
            # но не в элементах с классами, связанными с временем или другими метаданными
            is_potential_tag = (
                not any('time' in str(c).lower() for c in parent_class) and
                not any('clock' in str(c).lower() for c in parent_class) and
                not any('hourglass' in str(c).lower() for c in parent_class) and
                text not in ['Food Blog ANA+NINA', 'plus', 'minus', 'printer', 'group-people2']
            )
            
            # Проверяем, является ли это тегом категории/типа блюда
            tag_keywords = [
                'gemüse', 'suppe', 'einfach', 'schnell', 'salat', 'sauce', 'dessert', 'hauptspeise',
                'légumes', 'soupe', 'rapide', 'facile', 'salade',
                'verdure', 'zuppa', 'veloce', 'facile', 'insalata'
            ]
            
            if is_potential_tag and any(keyword in text.lower() for keyword in tag_keywords):
                # Не добавляем если это уже категория
                if text not in tags:
                    tags.append(text)
        
        # Возвращаем теги через запятую с пробелом
        return ', '.join(tags) if tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 2. Ищем изображения на странице рецепта
        # Ищем картинки внутри блока рецепта
        recipe_images = self.soup.find_all('img', src=re.compile(r'\.(jpg|jpeg|png|webp)', re.I))
        
        for img in recipe_images:
            src = img.get('src', '')
            # Пропускаем иконки и маленькие изображения
            if src and 'icon' not in src.lower() and 'logo' not in src.lower():
                # Проверяем, что это полный URL
                if src.startswith('http'):
                    urls.append(src)
                elif src.startswith('/'):
                    # Добавляем домен
                    urls.append(f"https://www.nahrin.ch{src}")
        
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
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        # На сайте nahrin.ch не найдена информация о питательности в примерах
        # Возвращаем None
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
    """Точка входа для обработки HTML файлов nahrin.ch"""
    import os
    
    # Ищем директорию с HTML-страницами
    preprocessed_dir = os.path.join("preprocessed", "nahrin_ch")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(NahrinChExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python extractor/nahrin_ch.py")


if __name__ == "__main__":
    main()
