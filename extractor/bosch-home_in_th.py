"""
Экстрактор данных рецептов для сайта bosch-home.in.th
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class BoschHomeExtractor(BaseRecipeExtractor):
    """Экстрактор для bosch-home.in.th"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в h1 заголовке
        h1 = self.soup.find('h1', class_='a-heading')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta title
        meta_title = self.soup.find('meta', {'name': 'title'})
        if meta_title and meta_title.get('content'):
            title = meta_title['content']
            # Убираем суффиксы типа " Recipe"
            title = re.sub(r'\s+Recipe\s*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов в структурированном формате"""
        ingredients = []
        
        # Ищем заголовок "Ingredients" и следующую за ним таблицу
        ingredients_heading = None
        for h2 in self.soup.find_all('h2', class_='a-heading'):
            if 'ingredients' in h2.get_text().lower():
                ingredients_heading = h2
                break
        
        if not ingredients_heading:
            return None
        
        # Находим таблицу после заголовка
        table = ingredients_heading.find_next('table')
        if not table:
            return None
        
        # Извлекаем все ячейки таблицы
        cells = table.find_all('td')
        
        for cell in cells:
            ingredient_text = cell.get_text(strip=True)
            if not ingredient_text:
                continue
            
            # Парсим каждый ингредиент
            parsed = self.parse_ingredient(ingredient_text)
            if parsed:
                ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[Dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Примеры:
        "100ml Chicken Stock" -> {"name": "Chicken Stock", "amount": 100, "units": "ml"}
        "20g Coriander" -> {"name": "Coriander", "amount": 20, "units": "g"}
        "1 Teaspoon Chilli Powder" -> {"name": "Chilli Powder", "amount": 1, "units": "Teaspoon"}
        "To Taste Salt" -> {"name": "Salt", "amount": None, "units": "To Taste"}
        """
        if not ingredient_text:
            return None
        
        text = self.clean_text(ingredient_text)
        
        # Паттерн 1: "To Taste <Name>"
        match = re.match(r'^To\s+Taste\s+(.+)$', text, re.IGNORECASE)
        if match:
            return {
                "name": match.group(1),
                "amount": None,
                "units": "To Taste"
            }
        
        # Паттерн 2: "<Число><Единица> <Название>"
        # Примеры: "100ml Chicken Stock", "20g Coriander", "1kg Chicken"
        match = re.match(r'^([\d.]+)\s*(ml|g|kg|Teaspoon|Tablespoon|Tablespoons|sheets?|unit|Teaspoons)s?\s+(.+)$', text, re.IGNORECASE)
        if match:
            amount = match.group(1)
            unit = match.group(2)
            name = match.group(3)
            # Convert amount to number
            try:
                amount = int(amount) if '.' not in amount else float(amount)
            except ValueError:
                pass
            return {
                "name": name,
                "amount": amount,
                "units": unit
            }
        
        # Паттерн 3: "<Число> <Название>"
        # Примеры: "1 Cinnamon Stick", "5 Cloves", "2 Egg Yolks"
        match = re.match(r'^([\d.]+)\s+(.+)$', text, re.IGNORECASE)
        if match:
            amount = match.group(1)
            # Convert amount to number
            try:
                amount = int(amount) if '.' not in amount else float(amount)
            except ValueError:
                pass
            return {
                "name": match.group(2),
                "amount": amount,
                "units": None
            }
        
        # Паттерн 4: "<Число> <Единица> <Название>"
        # Примеры: "1 Teaspoon Chilli Powder", "2 Tablespoons Curry Powder"
        match = re.match(r'^([\d.]+)\s+(Teaspoon|Tablespoon|sheets?|Tablespoons|Teaspoons)\s+(.+)$', text, re.IGNORECASE)
        if match:
            amount = match.group(1)
            # Convert amount to number
            try:
                amount = int(amount) if '.' not in amount else float(amount)
            except ValueError:
                pass
            return {
                "name": match.group(3),
                "amount": amount,
                "units": match.group(2)
            }
        
        # Паттерн 5: "<Число>g <Название>"
        match = re.match(r'^([\d.]+)g\s+(.+)$', text, re.IGNORECASE)
        if match:
            amount = match.group(1)
            # Convert amount to number
            try:
                amount = int(amount) if '.' not in amount else float(amount)
            except ValueError:
                pass
            return {
                "name": match.group(2),
                "amount": amount,
                "units": "g"
            }
        
        # Если не подошло ни одно правило, возвращаем только название
        return {
            "name": text,
            "amount": None,
            "units": None
        }
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем заголовок "Methods" или "1. Methods"
        methods_heading = None
        for h2 in self.soup.find_all('h2', class_='a-heading'):
            heading_text = h2.get_text().strip()
            if 'method' in heading_text.lower():
                methods_heading = h2
                break
        
        if not methods_heading:
            return None
        
        # Находим все блоки с инструкциями после заголовка Methods
        # Инструкции находятся в <p> внутри <div class="text js-content">
        current = methods_heading.find_next('div', class_='m-contenttextmedia')
        
        # Счетчик для остановки на продуктовых блоках
        seen_product_text = False
        
        while current and not seen_product_text:
            # Ищем текстовый блок в текущем элементе
            text_div = current.find('div', class_='text')
            if text_div:
                # Извлекаем все параграфы
                paragraphs = text_div.find_all('p')
                for p in paragraphs:
                    step_text = self.clean_text(p.get_text())
                    if not step_text or len(step_text) <= 5:
                        continue
                    
                    # Пропускаем текст о продуктах (обычно начинается с "Full power", "The steam oven" и т.д.)
                    if any(keyword in step_text for keyword in ['Full power', 'The steam oven', 'Induction hobs', 'These features']):
                        seen_product_text = True
                        break
                    
                    # Убираем нумерацию в начале, если есть
                    step_text = re.sub(r'^\d+\.\s*', '', step_text)
                    if step_text:
                        steps.append(step_text)
            
            # Переходим к следующему блоку contenttextmedia
            current = current.find_next_sibling('div', class_='m-contenttextmedia')
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории из breadcrumb"""
        # Ищем в хлебных крошках - последняя категория перед рецептом
        breadcrumb = self.soup.find('nav', class_='m-breadcrumb-rebrush')
        if breadcrumb:
            crumbs = breadcrumb.find_all('div', class_='crumb')
            if len(crumbs) >= 1:
                # Берем предпоследнюю крошку (последняя - это сам рецепт)
                category_crumb = crumbs[-1]
                link = category_crumb.find('a')
                if link:
                    category_text = link.get_text(strip=True)
                    # Убираем "&amp;" и подобные
                    category_text = re.sub(r'\s*&amp;\s*', ' & ', category_text)
                    # Преобразуем "Bread & Pastries" -> "Snack" по логике
                    # На самом деле в JSON примере категория "Snack", но в breadcrumb "Bread & Pastries"
                    # Возьмем как есть из breadcrumb
                    return self.clean_text(category_text)
        
        return None
    
    def extract_time_info(self) -> tuple:
        """
        Извлечение информации о времени из блока с параметрами рецепта
        Returns: (prep_time, cook_time, total_time)
        """
        prep_time = None
        cook_time = None
        total_time = None
        
        # Ищем блок с информацией о времени в тизере
        teaser = self.soup.find('div', class_='teaser')
        if teaser:
            # Извлекаем все параграфы
            paragraphs = teaser.find_all('p')
            for p in paragraphs:
                text = p.get_text(strip=True)
                
                # Preparation Time: 50 mins
                if 'preparation time' in text.lower():
                    match = re.search(r':\s*(.+)', text)
                    if match:
                        prep_time = self.clean_text(match.group(1))
                
                # Cooking Time: 30 mins
                elif 'cooking time' in text.lower():
                    match = re.search(r':\s*(.+)', text)
                    if match:
                        cook_time = self.clean_text(match.group(1))
                
                # Total Time (если есть)
                elif 'total time' in text.lower():
                    match = re.search(r':\s*(.+)', text)
                    if match:
                        total_time = self.clean_text(match.group(1))
        
        return prep_time, cook_time, total_time
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        prep_time, _, _ = self.extract_time_info()
        return prep_time
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        _, cook_time, _ = self.extract_time_info()
        return cook_time
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        _, _, total_time = self.extract_time_info()
        return total_time
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок (если есть)"""
        # В данном сайте нет явной секции с заметками
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов (если есть)"""
        # В HTML файлах не обнаружено явных тегов
        # Можно попробовать извлечь из meta keywords, если есть
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            return self.clean_text(meta_keywords['content'])
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Главное изображение из stage/slider
        stage_images = self.soup.find_all('div', class_='m-stage')
        for stage in stage_images:
            img = stage.find('img')
            if img and img.get('src'):
                url = img['src']
                # Добавляем протокол, если нужно
                if url.startswith('//'):
                    url = 'https:' + url
                urls.append(url)
        
        # 2. Изображения из галереи (пошаговые фото)
        galleries = self.soup.find_all('div', class_='m-mediagallery')
        for gallery in galleries:
            images = gallery.find_all('img')
            for img in images:
                if img.get('src'):
                    url = img['src']
                    if url.startswith('//'):
                        url = 'https:' + url
                    if url not in urls:
                        urls.append(url)
        
        # 3. Изображения из contenttextmedia
        content_media = self.soup.find_all('div', class_='m-contenttextmedia')
        for block in content_media:
            images = block.find_all('img')
            for img in images:
                if img.get('src'):
                    url = img['src']
                    if url.startswith('//'):
                        url = 'https:' + url
                    if url not in urls:
                        urls.append(url)
        
        # Убираем дубликаты, сохраняя порядок
        unique_urls = []
        seen = set()
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        return ','.join(unique_urls) if unique_urls else None
    
    def extract_all(self) -> dict:
        """
        Извлечение всех данных рецепта
        
        Returns:
            Словарь с данными рецепта
        """
        dish_name = self.extract_dish_name()
        description = self.extract_description()
        ingredients = self.extract_ingredients()
        instructions = self.extract_instructions()
        category = self.extract_category()
        prep_time = self.extract_prep_time()
        cook_time = self.extract_cook_time()
        total_time = self.extract_total_time()
        notes = self.extract_notes()
        tags = self.extract_tags()
        image_urls = self.extract_image_urls()
        
        return {
            "dish_name": dish_name,
            "description": description,
            "ingredients": ingredients,
            "instructions": instructions,
            "category": category,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "notes": notes,
            "tags": tags,
            "image_urls": image_urls
        }


def main():
    """Точка входа для тестирования экстрактора"""
    import os
    
    # Обрабатываем папку preprocessed/bosch-home_in_th
    recipes_dir = os.path.join("preprocessed", "bosch-home_in_th")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(BoschHomeExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python bosch-home_in_th.py")


if __name__ == "__main__":
    main()
