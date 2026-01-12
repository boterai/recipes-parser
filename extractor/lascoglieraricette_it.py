"""
Экстрактор данных рецептов для сайта lascoglieraricette.it
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class LascoglieraricetteItExtractor(BaseRecipeExtractor):
    """Экстрактор для lascoglieraricette.it"""
    
    def _get_json_ld_data(self) -> Optional[dict]:
        """Извлечение данных JSON-LD из страницы"""
        json_ld_scripts = self.soup.find_all('script', type='application/ld+json')
        
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                    
                data = json.loads(script.string)
                
                # Данные обычно в @graph
                if isinstance(data, dict) and '@graph' in data:
                    return data
                        
            except (json.JSONDecodeError, KeyError):
                continue
        
        return None
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем через itemprop
        name_elem = self.soup.find(attrs={'itemprop': 'headline'})
        if name_elem:
            return self.clean_text(name_elem.get_text())
        
        # Альтернативно - через h1
        h1 = self.soup.find('h1')
        if h1:
            return self.clean_text(h1.get_text())
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем через itemprop
        desc_elem = self.soup.find(attrs={'itemprop': 'description'})
        if desc_elem:
            return self.clean_text(desc_elem.get_text())
        
        # Альтернативно - из meta
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def parse_ingredient_text(self, text: str) -> Dict[str, Optional[str]]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            text: Строка вида "Funghi freschi 300 g" или "Sale q.b."
            
        Returns:
            dict: {"name": "...", "units": "...", "amount": ...}
        """
        text = self.clean_text(text)
        
        # Паттерн для ингредиентов с количеством и единицами
        # Примеры: "Funghi freschi 300 g", "Aglio 2 spicchi"
        match = re.search(r'^(.+?)\s+([\d,\.]+)\s*(.+)$', text)
        if match:
            name, amount_str, unit = match.groups()
            # Убираем скобки и комментарии из названия
            name = re.sub(r'\([^)]*\).*$', '', name).strip()
            # Конвертируем amount в число
            try:
                amount = float(amount_str.replace(',', '.'))
                # Если это целое число, возвращаем int
                if amount.is_integer():
                    amount = int(amount)
            except (ValueError, AttributeError):
                amount = amount_str
            
            return {
                "name": name,
                "units": unit.strip(),
                "amount": amount
            }
        
        # Паттерн для ингредиентов с q.b. (quanto basta - сколько нужно)
        match = re.search(r'^(.+?)\s+(q\.b\.|a piacere).*$', text, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            # Убираем скобки и комментарии
            name = re.sub(r'\([^)]*\).*$', '', name).strip()
            return {
                "name": name,
                "units": "q.b.",
                "amount": None
            }
        
        # Если не удалось распарсить, возвращаем только название
        name = re.sub(r'\([^)]*\).*$', '', text).strip()
        return {
            "name": name,
            "units": None,
            "amount": None
        }
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем все элементы с itemprop="ingredients"
        ingredient_elems = self.soup.find_all(attrs={'itemprop': 'ingredients'})
        
        for elem in ingredient_elems:
            text = elem.get_text(strip=True)
            if text:
                parsed = self.parse_ingredient_text(text)
                if parsed and parsed.get('name'):
                    ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def extract_instructions(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        # Ищем ol с itemprop="recipeInstructions"
        instructions_elem = self.soup.find(attrs={'itemprop': 'recipeInstructions'})
        
        if instructions_elem:
            # Собираем все li внутри
            steps = []
            for li in instructions_elem.find_all('li'):
                text = li.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                if text:
                    steps.append(text)
            
            if steps:
                # Соединяем шаги в одну строку
                return ' '.join(steps)
        
        return None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности (обычно отсутствует на этом сайте)"""
        return None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в JSON-LD
        json_ld = self._get_json_ld_data()
        
        if json_ld and '@graph' in json_ld:
            for item in json_ld['@graph']:
                if item.get('@type') == 'Article' and 'articleSection' in item:
                    sections = item['articleSection']
                    if isinstance(sections, list) and len(sections) > 0:
                        return sections[0]
                    elif isinstance(sections, str):
                        return sections
        
        # Альтернативно - ищем в breadcrumbs
        breadcrumb = self.soup.find('p', id='breadcrumbs')
        if breadcrumb:
            links = breadcrumb.find_all('a')
            # Берем последнюю категорию перед самим рецептом
            if len(links) >= 2:
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_time_from_text(self, text: str) -> Optional[str]:
        """
        Извлечение времени из текста инструкций
        
        Args:
            text: Текст, где может быть указано время
            
        Returns:
            Время в читаемом формате
        """
        if not text:
            return None
        
        # Паттерны для поиска времени: "7-8 minuti", "30 minuti", "2-3 minutes"
        patterns = [
            r'(\d+(?:-\d+)?)\s*(minuti|minutes|min)',
            r'(\d+(?:-\d+)?)\s*(ore|hours|hour|hr)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                time_val = match.group(1)
                unit = match.group(2).lower()
                
                # Нормализуем единицы
                if unit in ['minuti', 'minutes', 'min']:
                    return f"{time_val} minutes"
                elif unit in ['ore', 'hours', 'hour', 'hr']:
                    return f"{time_val} hours"
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки (обычно отсутствует на этом сайте)"""
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени готовки"""
        # Пробуем извлечь из текста инструкций
        instructions = self.extract_instructions()
        if instructions:
            return self.extract_time_from_text(instructions)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени (обычно отсутствует на этом сайте)"""
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок (обычно отсутствует на этом сайте)"""
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Теги часто встречаются в тексте страницы или мета-данных
        # Но обычно на этом сайте они не представлены структурированно
        # Можем попробовать извлечь ключевые слова из названия
        
        dish_name = self.extract_dish_name()
        if dish_name:
            # Извлекаем ключевые слова из названия блюда
            words = dish_name.lower().split()
            # Фильтруем короткие слова (предлоги и т.д.)
            keywords = [w for w in words if len(w) > 2 and w not in ['con', 'per', 'alla', 'del', 'della', 'dei', 'delle', 'gli']]
            if keywords:
                return ', '.join(keywords)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем изображения через itemprop="image"
        img_elems = self.soup.find_all(attrs={'itemprop': 'image'})
        
        for img in img_elems:
            # Получаем src или data-src
            src = img.get('src') or img.get('data-src')
            if src and src.startswith('http'):  # Фильтруем data: URIs
                urls.append(src)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_urls = []
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
    """Точка входа для обработки HTML файлов из preprocessed/lascoglieraricette_it"""
    import os
    
    # Путь к директории с HTML-страницами
    recipes_dir = os.path.join("preprocessed", "lascoglieraricette_it")
    
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        print(f"Обработка директории: {recipes_dir}")
        process_directory(LascoglieraricetteItExtractor, recipes_dir)
    else:
        print(f"Директория не найдена: {recipes_dir}")
        print("Использование: python lascoglieraricette_it.py")


if __name__ == "__main__":
    main()
