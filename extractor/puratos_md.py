"""
Экстрактор данных рецептов для сайта puratos.md
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class PuratosMdExtractor(BaseRecipeExtractor):
    """Экстрактор для puratos.md"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в hero title
        hero_title = self.soup.find('h1', class_='p-hero__title')
        if hero_title:
            return self.clean_text(hero_title.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return self.clean_text(og_title['content'])
        
        # Из title тега
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем суффиксы типа " - Puratos"
            title = re.sub(r'\s*-\s*Puratos.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Сначала ищем в текстовом блоке на странице (более подробное описание)
        # Ищем параграфы в области hero или intro
        intro_paragraphs = self.soup.find_all('p')
        for p in intro_paragraphs:
            text = p.get_text(strip=True)
            # Пропускаем короткие параграфы и те, что содержат только автора
            if len(text) > 50 and 'Autor' not in text and 'Transformă' in text or 'desert' in text.lower():
                return self.clean_text(text)
        
        # Если не нашли в параграфах, ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        # Альтернативно - из og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return self.clean_text(og_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Пытаемся найти данные в JavaScript (наиболее точный источник)
        scripts = self.soup.find_all('script')
        for script in scripts:
            if not script.string:
                continue
            
            # Ищем JSON с ингредиентами в window.___PRELOADEDSTATE___
            if '___PRELOADEDSTATE___' in script.string and 'ingredients_list' in script.string:
                # Извлекаем JSON объект с ингредиентами
                match = re.search(r'window\.___PRELOADEDSTATE___\.aem\.resources\["[^"]*ingredients_list"\]\s*=\s*(\{.*?\});', script.string, re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group(1))
                        if 'groups' in data:
                            for group in data['groups']:
                                if 'ingredients' in group:
                                    for ing in group['ingredients']:
                                        name = ing.get('ingredientLabel', '')
                                        amount = ing.get('ingredientUnits', '')
                                        # Убираем символы * из имени
                                        name = name.replace('*', '').strip()
                                        
                                        # Определяем единицу измерения из заголовка или явно из данных
                                        unit = data.get('unitsHeader', 'g')
                                        
                                        # Пробуем преобразовать amount в число
                                        try:
                                            amount_num = int(amount) if amount else None
                                        except (ValueError, TypeError):
                                            amount_num = amount
                                        
                                        ingredients.append({
                                            "name": name,
                                            "units": unit,
                                            "amount": amount_num
                                        })
                        if ingredients:
                            return json.dumps(ingredients, ensure_ascii=False)
                    except (json.JSONDecodeError, KeyError, ValueError):
                        pass
        
        # Если JSON не найден, парсим из HTML таблицы
        ingredient_table = self.soup.find('table', class_='table-condensed')
        if ingredient_table:
            # Определяем единицу измерения из заголовка таблицы
            unit = 'g'  # По умолчанию
            header_th = ingredient_table.find('thead')
            if header_th:
                header_text = header_th.get_text()
                if 'ml' in header_text:
                    unit = 'ml'
                elif 'g' in header_text:
                    unit = 'g'
            
            rows = ingredient_table.find('tbody').find_all('tr') if ingredient_table.find('tbody') else []
            for row in rows:
                # Пропускаем заголовки групп (th с colspan)
                if row.find('th', {'colspan': True}):
                    continue
                
                # Пропускаем строки с итогами
                if 'info' in row.get('class', []):
                    continue
                
                cells = row.find_all('td')
                if len(cells) >= 2:
                    name_cell = cells[0]
                    amount_cell = cells[1]
                    
                    # Извлекаем название (может быть ссылкой или текстом)
                    name = name_cell.get_text(strip=True)
                    # Убираем символы * из имени
                    name = name.replace('*', '').strip()
                    
                    # Извлекаем количество
                    amount = amount_cell.get_text(strip=True)
                    
                    if name and amount:
                        # Пробуем преобразовать amount в число
                        try:
                            amount_num = int(amount)
                        except (ValueError, TypeError):
                            amount_num = amount
                        
                        ingredients.append({
                            "name": name,
                            "units": unit,
                            "amount": amount_num
                        })
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        instructions = []
        
        # Пытаемся найти данные в JavaScript
        scripts = self.soup.find_all('script')
        for script in scripts:
            if not script.string:
                continue
            
            # Ищем JSON с методом в window.___PRELOADEDSTATE___
            if '___PRELOADEDSTATE___' in script.string and 'method' in script.string:
                # Извлекаем JSON объект с методом
                match = re.search(r'window\.___PRELOADEDSTATE___\.aem\.resources\["[^"]*method"\]\s*=\s*(\{.*?\});', script.string, re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group(1))
                        if 'methodItems' in data:
                            for item in data['methodItems']:
                                step_text = item.get('methodText', '')
                                if step_text:
                                    instructions.append(self.clean_text(step_text))
                        if instructions:
                            return ' '.join(instructions)
                    except (json.JSONDecodeError, KeyError):
                        pass
        
        # Если JSON не найден, парсим из HTML
        # Ищем контейнер с шагами
        method_container = self.soup.find('div', class_='recipe-page__method')
        if method_container:
            # Ищем пошаговые элементы
            step_items = method_container.find_all('div', class_='step-by-step-list-item')
            if step_items:
                for item in step_items:
                    step_text = item.get_text(separator=' ', strip=True)
                    step_text = self.clean_text(step_text)
                    if step_text:
                        instructions.append(step_text)
            else:
                # Если нет пошаговых элементов, ищем таблицы с инструкциями
                # Ищем все таблицы с классом table-bare
                tables = method_container.find_all('table', class_='table-bare')
                for table in tables:
                    rows = table.find_all('tr')
                    for row in rows:
                        # Извлекаем заголовок (название этапа)
                        header = row.find('th', class_='p-table-text')
                        if header:
                            header_text = self.clean_text(header.get_text())
                            if header_text:
                                instructions.append(header_text + ':')
                        
                        # Извлекаем текст инструкции
                        cells = row.find_all('td', class_='p-table-text')
                        for cell in cells:
                            text = cell.get_text(separator=' ', strip=True)
                            text = self.clean_text(text)
                            if text and text != ' ':
                                instructions.append(text)
        
        return ' '.join(instructions) if instructions else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Можно попробовать извлечь из breadcrumbs или meta tags
        # Но в примерах puratos.md это обычно "Dessert"
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:
                return self.clean_text(links[-1].get_text())
        
        # По умолчанию для puratos.md
        return "Dessert"
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # В HTML файлах puratos.md время не всегда явно указано
        # Можно попробовать найти в тексте или вернуть "null"
        return "null"
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте инструкций упоминания о времени выпечки/готовки
        instructions = self.extract_instructions()
        if instructions:
            # Паттерн для времени выпечки с температурой: "180°C... 25-30 de minute" или "25- 30 de minute"
            time_pattern = r'(?:\d+)°[CF].*?(\d+)\s*[-–]\s*(\d+)\s+(?:de\s+)?minut[eși]*'
            match = re.search(time_pattern, instructions, re.IGNORECASE)
            if match:
                time_str = match.group(1) + '-' + match.group(2) + ' minutes'
                return time_str
            
            # Паттерн для времени выпечки с температурой (одно число): "180°C... 17 minute"
            time_pattern2 = r'(?:\d+)°[CF].*?timp\s+de\s+(\d+)\s+(?:de\s+)?minut[eși]*'
            match = re.search(time_pattern2, instructions, re.IGNORECASE)
            if match:
                time_str = match.group(1) + ' minutes'
                return time_str
            
            # Англоязычный паттерн: "for 17 minutes"
            time_pattern_en = r'(?:for\s+)?(\d+)\s*[-–]\s*(\d+)\s+minutes?'
            match = re.search(time_pattern_en, instructions, re.IGNORECASE)
            if match:
                return match.group(1) + '-' + match.group(2) + ' minutes'
            
            # Англоязычный паттерн с одним числом
            time_pattern_en2 = r'(?:for\s+)(\d+)\s+minutes?'
            match = re.search(time_pattern_en2, instructions, re.IGNORECASE)
            if match:
                return match.group(1) + ' minutes'
        
        return "null"
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # В HTML файлах puratos.md общее время обычно не указано явно
        return "null"
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем секцию с примечаниями или декором после метода
        # В примерах есть текст типа "Pe mousse-ul glazurat..."
        
        # Ищем все параграфы в p-editor
        editor_paragraphs = self.soup.find_all('div', class_=re.compile(r'p-editor'))
        notes = []
        for elem in editor_paragraphs:
            p_tag = elem.find('p')
            if p_tag:
                text = p_tag.get_text(strip=True)
                # Проверяем, содержит ли текст ключевые слова для заметок
                # или находится после инструкций
                if any(keyword in text.lower() for keyword in ['decor', 'notă', 'sfat', 'important', 'atenție', 'pe mousse']):
                    notes.append(self.clean_text(text))
        
        if notes:
            return ' '.join(notes)
        
        return "null"
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        tags = []
        
        # Ищем в meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            tags.extend([tag.strip() for tag in keywords.split(',') if tag.strip()])
        
        # Добавляем название рецепта как тег
        dish_name = self.extract_dish_name()
        if dish_name:
            tags.append(dish_name)
        
        # Добавляем категорию как тег
        category = self.extract_category()
        if category:
            tags.append(category)
        
        # Добавляем "Puratos" как тег бренда
        tags.append("Puratos")
        
        # Убираем дубликаты
        seen = set()
        unique_tags = []
        for tag in tags:
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen.add(tag_lower)
                unique_tags.append(tag)
        
        return ', '.join(unique_tags) if unique_tags else None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем hero background image
        hero_bg = self.soup.find('div', class_='p-hero__background')
        if hero_bg:
            style = hero_bg.get('style', '')
            # Извлекаем URL из style="background-image:url(...)"
            match = re.search(r'background-image:\s*url\(["\']?([^"\'()]+)["\']?\)', style)
            if match:
                img_url = match.group(1)
                if img_url.startswith('/'):
                    img_url = 'https://www.puratos.md' + img_url
                urls.append(img_url)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        return ','.join(unique_urls) if unique_urls else None
    
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
            "image_urls": self.extract_image_urls(),
            "tags": self.extract_tags()
        }


def main():
    """
    Точка входа для обработки директории с HTML-страницами puratos_md
    """
    import os
    
    # Обрабатываем папку preprocessed/puratos_md относительно корня репозитория
    repo_root = Path(__file__).parent.parent
    recipes_dir = repo_root / "preprocessed" / "puratos_md"
    
    if recipes_dir.exists() and recipes_dir.is_dir():
        print(f"Обработка директории: {recipes_dir}")
        process_directory(PuratosMdExtractor, str(recipes_dir))
    else:
        print(f"Директория не найдена: {recipes_dir}")
        print("Использование: python puratos_md.py")


if __name__ == "__main__":
    main()
