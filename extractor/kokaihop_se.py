"""
Экстрактор данных рецептов для сайта kokaihop.se
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class KokaiHopExtractor(BaseRecipeExtractor):
    """Экстрактор для kokaihop.se"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в div с классом recipeTitle
        recipe_title_div = self.soup.find('div', class_='recipeTitle')
        if recipe_title_div:
            h1 = recipe_title_div.find('h1')
            if h1:
                return self.clean_text(h1.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " - Author - Recept"
            title = re.sub(r'\s*-\s*\w+\s*-\s*Recept.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        # Ещё вариант - тег title
        title_tag = self.soup.find('title')
        if title_tag:
            title = title_tag.get_text()
            # Убираем суффиксы
            title = re.sub(r'\s*-\s*\w+\s*-\s*Recept.*$', '', title, flags=re.IGNORECASE)
            return self.clean_text(title)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем в div с классом recipeTitle -> span (описание)
        recipe_title_div = self.soup.find('div', class_='recipeTitle')
        if recipe_title_div:
            span = recipe_title_div.find('span')
            if span:
                desc = self.clean_text(span.get_text())
                if desc:
                    return desc
        
        # Альтернативно - из meta тега og:description
        og_desc = self.soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            desc = og_desc['content']
            # Если это общее описание сайта, пропускаем
            if 'över 700 000 medlemmar' not in desc:
                return self.clean_text(desc)
        
        return None
    
    def parse_ingredient_line(self, ingredient_text: str) -> Optional[Dict[str, any]]:
        """
        Парсинг строки ингредиента в структурированный формат
        Формат в HTML: "amount unit name" (например: "125 gram rumstempererat smör")
        
        Args:
            ingredient_text: Строка вида "125 gram smör"
            
        Returns:
            dict: {"name": "smör", "amount": 125, "units": "gram"}
        """
        if not ingredient_text:
            return None
        
        text = self.clean_text(ingredient_text).strip()
        
        # Паттерн: number (int/float) + unit + name
        # Примеры: "125 gram smör", "3 st ägg", "2 msk vaniljsocker"
        pattern = r'^(\d+(?:[.,]\d+)?)\s+(gram|st|msk|tsk|krm|dl|ml|l|kg)?(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str, unit, name = match.groups()
            
            # Конвертируем amount в число
            amount = amount_str.replace(',', '.')
            try:
                # Пробуем преобразовать в int, если целое число
                if '.' not in amount:
                    amount = int(amount)
                else:
                    amount = float(amount)
            except ValueError:
                amount = 0
            
            # Очистка названия
            name = name.strip()
            unit = unit.strip() if unit else None
            
            return {
                "name": name,
                "units": unit,
                "amount": amount
            }
        
        # Если паттерн не совпал, возвращаем как есть
        return {
            "name": text,
            "units": None,
            "amount": 0
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем список ингредиентов
        ingredients_list = self.soup.find('ul', class_='ingredientsList')
        
        if ingredients_list:
            items = ingredients_list.find_all('li')
            
            for item in items:
                ingredient_text = item.get_text(strip=True)
                
                # Парсим ингредиент
                parsed = self.parse_ingredient_line(ingredient_text)
                if parsed:
                    ingredients.append(parsed)
        
        # Возвращаем как JSON-строку
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем div с классом recipeInstructions
        instructions_div = self.soup.find('div', class_='recipeInstructions')
        
        if instructions_div:
            # Извлекаем шаги (элементы списка)
            step_items = instructions_div.find_all('li')
            
            for item in step_items:
                # Извлекаем текст, удаляя номер шага если он есть в <strong>
                step_text = item.get_text(separator=' ', strip=True)
                # Удаляем нумерацию вида "1.", "2." в начале
                step_text = re.sub(r'^\d+\.\s*', '', step_text)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    steps.append(step_text)
        
        # Объединяем шаги с нумерацией
        if steps:
            numbered_steps = [f"{i}. {step}" for i, step in enumerate(steps, 1)]
            return ' '.join(numbered_steps)
        
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в div с классом infoListWrapper
        info_wrapper = self.soup.find('div', class_='infoListWrapper')
        
        if info_wrapper:
            # Ищем текст, который содержит "Maträtt:"
            text = info_wrapper.get_text()
            
            # Паттерн для извлечения категории после "Maträtt:"
            match = re.search(r'Maträtt:\s*([^T]+?)(?:Tillagning:|$)', text)
            if match:
                category = match.group(1).strip()
                return self.clean_text(category)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем в тексте инструкций время вида "25-30 minuter" или "30 minuter"
        instructions_div = self.soup.find('div', class_='recipeInstructions')
        
        if instructions_div:
            text = instructions_div.get_text()
            
            # Паттерн для времени: "число-число minuter" или "число minuter"
            # Примеры: "25-30 minuter", "30 minuter", "1 timme"
            patterns = [
                r'(\d+(?:-\d+)?)\s*min(?:uter?|s?)',
                r'(\d+)\s*tim(?:me|mar)?'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    time_str = match.group(1)
                    # Возвращаем в формате "X minutes" или "X-Y minutes"
                    return f"{time_str} minutes"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # В kokaihop.se обычно не указывается отдельно prep_time
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # В kokaihop.se обычно не указывается отдельно total_time
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок к рецепту"""
        # Ищем параграфы с текстом "Hoppas det blir gott"
        for p in self.soup.find_all('p'):
            text = p.get_text(separator=' ', strip=True)
            if 'Hoppas' in text or 'kommentar' in text:
                # Проверяем, что это достаточно длинный текст
                if len(text) > 20:
                    return self.clean_text(text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем теги в метаданных или в HTML
        # В примерах JSON теги выглядят как "#Blåbärspulver"
        
        # Проверяем meta keywords
        meta_keywords = self.soup.find('meta', {'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            keywords = meta_keywords['content']
            # Фильтруем теги, которые начинаются с #
            tags = [tag.strip() for tag in keywords.split(',') if tag.strip().startswith('#')]
            if tags:
                return ', '.join(tags)
        
        # Ищем в тексте страницы теги с #
        all_text = self.soup.get_text()
        hashtag_pattern = r'#\w+'
        tags = re.findall(hashtag_pattern, all_text)
        if tags:
            # Убираем дубликаты
            unique_tags = list(dict.fromkeys(tags))
            return ', '.join(unique_tags[:5])  # Ограничиваем количество
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # 1. Ищем в мета-тегах og:image
        og_image = self.soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            urls.append(og_image['content'])
        
        # 2. Ищем в мета-тегах twitter:image
        twitter_image = self.soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            urls.append(twitter_image['content'])
        
        # 3. Ищем изображения в теле документа (CloudFront URLs)
        images = self.soup.find_all('img')
        for img in images:
            src = img.get('src', '')
            # Фильтруем только изображения рецептов (CloudFront)
            if 'cloudfront.net' in src and src not in urls:
                urls.append(src)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        # Возвращаем как строку через запятую без пробелов
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
    """Обработка HTML файлов из директории preprocessed/kokaihop_se"""
    import os
    
    # Путь к директории с HTML-файлами
    repo_root = Path(__file__).parent.parent
    preprocessed_dir = repo_root / "preprocessed" / "kokaihop_se"
    
    if preprocessed_dir.exists() and preprocessed_dir.is_dir():
        print(f"Обработка файлов из: {preprocessed_dir}")
        process_directory(KokaiHopExtractor, str(preprocessed_dir))
    else:
        print(f"Директория не найдена: {preprocessed_dir}")
        print("Использование: python kokaihop_se.py")


if __name__ == "__main__":
    main()
