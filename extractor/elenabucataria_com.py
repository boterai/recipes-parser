"""
Экстрактор данных рецептов для сайта elenabucataria.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class ElenaExtractor(BaseRecipeExtractor):
    """Экстрактор для elenabucataria.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке h1
        h1 = self.soup.find('h1')
        if h1:
            # Удаляем span с классом no-print (это "(Versiune tipărită)")
            for no_print_span in h1.find_all('span', class_='no-print'):
                no_print_span.decompose()
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - Elena Bucataria"
            title = re.sub(r'\s+-\s+Elena Bucataria.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем первый параграф после h1 (обычно в первой секции)
        h1 = self.soup.find('h1')
        if h1:
            # Ищем следующий section
            section = h1.find_next('section')
            if section:
                p = section.find('p')
                if p:
                    return self.clean_text(p.get_text())
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content']
            # Убираем "Versiune tipărită" и т.п.
            desc = re.sub(r'\s+-[^-]*Versiune tipărită.*$', '', desc, flags=re.IGNORECASE)
            return self.clean_text(desc)
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            desc = re.sub(r'\s+-[^-]*Versiune tipărită.*$', '', desc, flags=re.IGNORECASE)
            return self.clean_text(desc)
        
        return None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "680 grame mușchi de vita" или "4 cartofi medii"
            
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
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "680 grame mușchi", "4 cartofi medii", "1 linguriță pudră"
        # Поддерживаемые единицы (включая румынские)
        pattern = r'^([\d\s/.,]+)?\s*(grame|gram|g|kg|kilograme|linguriță|lingurițe|lingură|linguri|lingi|cană|căni|ml|milliliters?|l|liters?|bucăți|bucată|felii|felie|piese|piesa|pieces?|cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|head|heads|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|piece)?\s*(.+)'
        
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
                # Возвращаем как int, если целое число, иначе как float
                amount = int(total) if total == int(total) else total
            else:
                amount_str = amount_str.replace(',', '.')
                amount = float(amount_str)
                # Конвертируем в int, если это целое число
                amount = int(amount) if amount == int(amount) else amount
        
        # Очистка названия
        # Удаляем части после запятой (это часто инструкции по подготовке)
        name = re.split(r',', name)[0]
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем лишние запятые в конце
        name = re.sub(r'[,;]+$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if not name or len(name) < 2:
            return None
        
        return {
            "name": name,
            "amount": amount,
            "units": units
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем секцию с комментарием <!-- RecipeIngredients -->
        # Обходим все комментарии в поиске нужного
        for comment in self.soup.find_all(string=lambda text: isinstance(text, str) and 'RecipeIngredients' in text):
            # Находим родительский элемент комментария и следующий элемент
            parent = comment.parent
            if parent:
                # Ищем div с id="recipe-ingredients" или следующий после комментария
                ingredients_div = parent.find_next('div', id='recipe-ingredients')
                if not ingredients_div:
                    # Попробуем найти следующий section
                    ingredients_div = parent.find_next('section')
                
                if ingredients_div:
                    # Вариант 1: новая структура с span class="recipe__interact-list-content"
                    content_spans = ingredients_div.find_all('span', class_='recipe__interact-list-content')
                    if content_spans:
                        for span in content_spans:
                            ingredient_text = span.get_text(strip=True)
                            ingredient_text = self.clean_text(ingredient_text)
                            
                            if ingredient_text:
                                # Парсим в структурированный формат
                                parsed = self.parse_ingredient(ingredient_text)
                                if parsed:
                                    ingredients.append(parsed)
                        
                        if ingredients:
                            break
                    
                    # Вариант 2: старая структура с strong и span
                    ingredient_divs = ingredients_div.find_all('div', recursive=True)
                    
                    for div in ingredient_divs:
                        # Пропускаем заголовки категорий (h3, h4)
                        if div.find('h3') or div.find('h4'):
                            continue
                        
                        # Проверяем наличие strong и span
                        strong = div.find('strong')
                        span = div.find('span')
                        
                        if strong and span:
                            # Извлекаем текст ингредиента из span
                            ingredient_text = span.get_text(strip=True)
                            ingredient_text = self.clean_text(ingredient_text)
                            
                            if ingredient_text:
                                # Парсим в структурированный формат
                                parsed = self.parse_ingredient(ingredient_text)
                                if parsed:
                                    ingredients.append(parsed)
                    
                    if ingredients:
                        break
        
        # Альтернативный поиск - если не нашли через комментарий
        if not ingredients:
            # Ищем h2 или h3 с текстом "Ingrediente"
            header = self.soup.find(['h2', 'h3'], string=re.compile(r'Ingrediente', re.I))
            if header:
                # Ищем div с id="recipe-ingredients"
                ingredients_div = header.find_next('div', id='recipe-ingredients')
                if not ingredients_div:
                    ingredients_div = header.find_next('div')
                
                if ingredients_div:
                    # Вариант 1: новая структура
                    content_spans = ingredients_div.find_all('span', class_='recipe__interact-list-content')
                    if content_spans:
                        for span in content_spans:
                            ingredient_text = span.get_text(strip=True)
                            ingredient_text = self.clean_text(ingredient_text)
                            
                            if ingredient_text:
                                parsed = self.parse_ingredient(ingredient_text)
                                if parsed:
                                    ingredients.append(parsed)
                    else:
                        # Вариант 2: старая структура
                        ingredient_divs = ingredients_div.find_all('div', recursive=True)
                        
                        for div in ingredient_divs:
                            if div.find('h3') or div.find('h4'):
                                continue
                            
                            strong = div.find('strong')
                            span = div.find('span')
                            
                            if strong and span:
                                ingredient_text = span.get_text(strip=True)
                                ingredient_text = self.clean_text(ingredient_text)
                                
                                if ingredient_text:
                                    parsed = self.parse_ingredient(ingredient_text)
                                    if parsed:
                                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение инструкций по приготовлению"""
        instructions = []
        
        # Ищем секцию с комментарием <!-- RecipeInstructions -->
        for comment in self.soup.find_all(string=lambda text: isinstance(text, str) and 'RecipeInstructions' in text):
            parent = comment.parent
            if parent:
                # Ищем div с id="recipe-instructions" или следующий элемент
                instructions_div = parent.find_next('div', id='recipe-instructions')
                if not instructions_div:
                    instructions_div = parent.find_next('section')
                
                if instructions_div:
                    # Вариант 1: новая структура - ищем div с id вида "instruction-N"
                    instruction_divs = instructions_div.find_all('div', id=re.compile(r'^instruction-\d+'))
                    if instruction_divs:
                        for div in instruction_divs:
                            # Извлекаем весь текст из div
                            step_text = div.get_text(separator=' ', strip=True)
                            step_text = self.clean_text(step_text)
                            
                            if step_text:
                                instructions.append(step_text)
                        
                        if instructions:
                            break
                    
                    # Вариант 2: старая структура с strong и span
                    instruction_divs = instructions_div.find_all('div', recursive=True)
                    
                    for div in instruction_divs:
                        strong = div.find('strong')
                        span = div.find('span')
                        
                        if strong and span:
                            # Извлекаем номер шага из strong
                            step_num = strong.get_text(strip=True)
                            # Извлекаем текст инструкции из span
                            step_text = span.get_text(strip=True)
                            step_text = self.clean_text(step_text)
                            
                            if step_text:
                                # Форматируем как "01 - текст" (добавляем пробел после дефиса если его нет)
                                if step_num.endswith('-'):
                                    instructions.append(f"{step_num} {step_text}")
                                elif step_num.endswith(' -'):
                                    instructions.append(f"{step_num} {step_text}")
                                else:
                                    instructions.append(f"{step_num} {step_text}")
                    
                    if instructions:
                        break
        
        # Альтернативный поиск
        if not instructions:
            header = self.soup.find(['h2', 'h3'], string=re.compile(r'Instrucțiuni|Mod de preparare', re.I))
            if header:
                # Ищем div с id="recipe-instructions"
                instructions_div = header.find_next('div', id='recipe-instructions')
                if not instructions_div:
                    instructions_div = header.find_next('div')
                
                if instructions_div:
                    # Вариант 1: новая структура
                    instruction_divs = instructions_div.find_all('div', id=re.compile(r'^instruction-\d+'))
                    if instruction_divs:
                        for div in instruction_divs:
                            step_text = div.get_text(separator=' ', strip=True)
                            step_text = self.clean_text(step_text)
                            
                            if step_text:
                                instructions.append(step_text)
                    else:
                        # Вариант 2: старая структура
                        instruction_divs = instructions_div.find_all('div', recursive=True)
                        
                        for div in instruction_divs:
                            strong = div.find('strong')
                            span = div.find('span')
                            
                            if strong and span:
                                step_num = strong.get_text(strip=True)
                                step_text = span.get_text(strip=True)
                                step_text = self.clean_text(step_text)
                                
                                if step_text:
                                    if step_num.endswith('-'):
                                        instructions.append(f"{step_num} {step_text}")
                                    elif step_num.endswith(' -'):
                                        instructions.append(f"{step_num} {step_text}")
                                    else:
                                        instructions.append(f"{step_num} {step_text}")
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Проверяем другие возможные места
        # Иногда категория может быть в breadcrumbs или других местах
        # Для данного сайта категория может отсутствовать
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем элемент с текстом "Timp pentru pregătire"
        prep_label = self.soup.find('strong', string=re.compile(r'Timp pentru pregătire', re.I))
        if prep_label:
            # Ищем родительский div, содержащий и strong и span
            parent_container = prep_label.find_parent('div', class_='recipe__times-item')
            if not parent_container:
                # Может быть структура без класса
                parent_container = prep_label.find_parent('div')
            
            if parent_container:
                # Ищем span с классом recipe__highlight в том же контейнере
                time_span = parent_container.find('span', class_='recipe__highlight')
                if time_span:
                    return self.clean_text(time_span.get_text())
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем элемент с текстом "Timp de gătire"
        cook_label = self.soup.find('strong', string=re.compile(r'Timp de gătire', re.I))
        if cook_label:
            parent_container = cook_label.find_parent('div', class_='recipe__times-item')
            if not parent_container:
                parent_container = cook_label.find_parent('div')
            
            if parent_container:
                time_span = parent_container.find('span', class_='recipe__highlight')
                if time_span:
                    return self.clean_text(time_span.get_text())
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем элемент с текстом "Timp total"
        total_label = self.soup.find('strong', string=re.compile(r'Timp total', re.I))
        if total_label:
            parent_container = total_label.find_parent('div', class_='recipe__times-item')
            if not parent_container:
                parent_container = total_label.find_parent('div')
            
            if parent_container:
                time_span = parent_container.find('span', class_='recipe__highlight')
                if time_span:
                    return self.clean_text(time_span.get_text())
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем секцию с комментарием <!-- RecipeNotes -->
        for comment in self.soup.find_all(string=lambda text: isinstance(text, str) and 'RecipeNotes' in text):
            parent = comment.parent
            if parent:
                section = parent.find_next('section')
                if section:
                    # Ищем все div с заметками (те, что содержат strong и span)
                    note_divs = section.find_all('div', recursive=True)
                    
                    for div in note_divs:
                        strong = div.find('strong')
                        span = div.find('span')
                        
                        if strong and span:
                            # Извлекаем текст заметки из span
                            note_text = span.get_text(strip=True)
                            note_text = self.clean_text(note_text)
                            
                            if note_text:
                                notes.append(note_text)
                    
                    if notes:
                        break
        
        # Альтернативный поиск
        if not notes:
            h2 = self.soup.find('h2', string=re.compile(r'Note utile', re.I))
            if h2:
                section = h2.find_next('div')
                if section:
                    note_divs = section.find_all('div', recursive=True)
                    
                    for div in note_divs:
                        strong = div.find('strong')
                        span = div.find('span')
                        
                        if strong and span:
                            note_text = span.get_text(strip=True)
                            note_text = self.clean_text(note_text)
                            
                            if note_text:
                                notes.append(note_text)
        
        return ' '.join(notes) if notes else None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Проверяем meta теги
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        # Можно искать теги в других местах, но для данного сайта их может не быть
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в других meta тегах
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
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
    """Обработка директории с HTML файлами"""
    import os
    
    # Определяем путь к директории с preprocessed файлами
    project_root = Path(__file__).parent.parent
    recipes_dir = project_root / "preprocessed" / "elenabucataria_com"
    
    if recipes_dir.exists() and recipes_dir.is_dir():
        print(f"Обрабатываем директорию: {recipes_dir}")
        process_directory(ElenaExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python elenabucataria_com.py")


if __name__ == "__main__":
    main()
