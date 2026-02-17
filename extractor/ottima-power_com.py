"""
Экстрактор данных рецептов для сайта ottima-power.com
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.base import BaseRecipeExtractor, process_directory


class OttimaPowerExtractor(BaseRecipeExtractor):
    """Экстрактор для ottima-power.com"""
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в h1 с классом entry-title
        h1 = self.soup.find('h1', class_='entry-title')
        if h1:
            return self.clean_text(h1.get_text())
        
        # Альтернативно - любой h2
        h2 = self.soup.find('h2')
        if h2:
            return self.clean_text(h2.get_text())
        
        # Из title тега
        title = self.soup.find('title')
        if title:
            text = title.get_text()
            # Убираем суффиксы типа " | Ottima"
            text = re.sub(r'\s*\|.*$', '', text)
            return self.clean_text(text)
        
        return None
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем div с описанием рецепта (обычно идет перед метаданными рецепта)
        # Находим div который содержит Course/Prep Time/etc и берем предыдущий div с текстом
        course_div = None
        for div in self.soup.find_all('div', style=""):
            text = div.get_text(strip=True)
            if text.startswith('Course:'):
                course_div = div
                break
        
        if course_div:
            # Ищем предыдущий div с текстом (не пустой)
            prev_div = course_div.find_previous('div')
            while prev_div:
                text = prev_div.get_text(strip=True)
                # Проверяем, что это не служебный div и содержит существенный текст
                if text and len(text) > 50 and not text.startswith(('Print', 'Pin', 'Course:', 'Cuisine:', 'Keyword:', 'Prep Time:', 'Cook Time:')):
                    # Проверяем, что нет изображений
                    if not prev_div.find('img'):
                        # Убираем trailing запятую
                        text = re.sub(r',\s*$', '', text)
                        return self.clean_text(text)
                prev_div = prev_div.find_previous('div')
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем все li с style="list-style-type: disc;" (это ингредиенты)
        # Они идут перед заголовком "Instructions"
        instructions_h3 = self.soup.find('h3', string=re.compile(r'Instructions', re.I))
        
        if instructions_h3:
            # Ищем все li перед Instructions
            all_lis = self.soup.find_all('li', style=re.compile(r'list-style-type:\s*disc', re.I))
            
            for li in all_lis:
                # Проверяем, что li идет до instructions_h3
                # Простая проверка: если li находится до h3 в дереве
                ingredient_text = li.get_text(strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                if ingredient_text:
                    parsed = self.parse_ingredient(ingredient_text)
                    if parsed:
                        ingredients.append(parsed)
        
        return json.dumps(ingredients, ensure_ascii=False) if ingredients else None
    
    def parse_ingredient(self, ingredient_text: str) -> Optional[dict]:
        """
        Парсинг строки ингредиента в структурированный формат
        
        Args:
            ingredient_text: Строка вида "1 cup all-purpose flour" или "2 pounds chicken"
            
        Returns:
            dict: {"name": "flour", "amount": "1", "units": "cup"} или None
        """
        if not ingredient_text:
            return None
        
        # Чистим текст
        text = self.clean_text(ingredient_text).lower()
        
        # Заменяем Unicode дроби на числа
        fraction_map = {
            '½': '1/2', '¼': '1/4', '¾': '3/4',
            '⅓': '1/3', '⅔': '2/3', '⅛': '1/8',
            '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
            '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5'
        }
        
        for fraction, decimal in fraction_map.items():
            text = text.replace(fraction, decimal)
        
        # Паттерн для извлечения количества, единицы и названия
        # Примеры: "1 cup flour", "2 tablespoons butter", "1/2 teaspoon salt"
        pattern = r'^([\d\s/.,]+)?\s*(cups?|tablespoons?|teaspoons?|tbsps?|tsps?|pounds?|ounces?|lbs?|oz|grams?|kilograms?|g|kg|milliliters?|liters?|ml|l|pinch(?:es)?|dash(?:es)?|packages?|cans?|jars?|bottles?|inch(?:es)?|slices?|cloves?|bunches?|sprigs?|whole|halves?|quarters?|pieces?|head|heads)?\s*(.+)'
        
        match = re.match(pattern, text, re.IGNORECASE)
        
        if not match:
            # Если паттерн не совпал, возвращаем только название
            return {
                "name": text,
                "amount": None,
                "units": None
            }
        
        amount_str, unit, name = match.groups()
        
        # Обработка количества
        amount = None
        if amount_str:
            amount_str = amount_str.strip()
            amount = amount_str
        
        # Обработка единицы измерения
        unit = unit.strip() if unit else None
        
        # Очистка названия
        # Удаляем скобки с содержимым
        name = re.sub(r'\([^)]*\)', '', name)
        # Удаляем фразы "to taste", "as needed", "optional"
        name = re.sub(r'\b(to taste|as needed|or more|if needed|optional|for garnish)\b', '', name, flags=re.IGNORECASE)
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
        steps = []
        
        # Ищем заголовок Instructions
        instructions_h3 = self.soup.find('h3', string=re.compile(r'Instructions', re.I))
        
        if instructions_h3:
            # Ищем следующий ul после h3
            ul = instructions_h3.find_next('ul')
            if ul:
                # Извлекаем li с style="list-style-type: decimal;"
                step_items = ul.find_all('li', style=re.compile(r'list-style-type:\s*decimal', re.I))
                
                for item in step_items:
                    # Ищем вложенный div
                    div = item.find('div')
                    if div:
                        step_text = div.get_text(separator=' ', strip=True)
                    else:
                        step_text = item.get_text(separator=' ', strip=True)
                    
                    step_text = self.clean_text(step_text)
                    
                    if step_text:
                        # Удаляем запятую в конце (если это последняя часть предложения)
                        step_text = re.sub(r',(\s*)$', r'.\1', step_text)
                        steps.append(step_text)
        
        return ' '.join(steps) if steps else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем div с текстом "Course:" который не содержит другие ключевые слова
        divs = self.soup.find_all('div', style="")
        
        for div in divs:
            text = div.get_text(strip=True)
            # Проверяем, что это div только с Course, без других метаданных
            if text.startswith('Course:') and 'Cuisine:' not in text and 'Keyword:' not in text:
                # Извлекаем категорию
                category = text.replace('Course:', '').strip()
                # Берем последнюю категорию через запятую (обычно самая специфичная)
                if ',' in category:
                    category = category.split(',')[-1].strip()
                return self.clean_text(category)
        
        # Альтернативно - из post-category
        post_cat = self.soup.find('span', class_='post-category')
        if post_cat:
            a = post_cat.find('a')
            if a:
                return self.clean_text(a.get_text())
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        # Ищем div с текстом "Prep Time:"
        divs = self.soup.find_all('div', style="")
        
        for div in divs:
            text = div.get_text(strip=True)
            if text.startswith('Prep Time:'):
                # Извлекаем только Prep Time (без Cook Time)
                time = text.replace('Prep Time:', '').strip()
                # Убираем все после "Cook Time:" если оно попало
                if 'Cook Time:' in time:
                    time = time.split('Cook Time:')[0].strip()
                return self.clean_text(time)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        # Ищем div с текстом "Cook Time:"
        divs = self.soup.find_all('div', style="")
        
        for div in divs:
            text = div.get_text(strip=True)
            if text.startswith('Cook Time:'):
                # Извлекаем время
                time = text.replace('Cook Time:', '').strip()
                return self.clean_text(time)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        # Ищем div с текстом "Total Time:"
        divs = self.soup.find_all('div', style="")
        
        for div in divs:
            text = div.get_text(strip=True)
            if text.startswith('Total Time:'):
                # Извлекаем время
                time = text.replace('Total Time:', '').strip()
                return self.clean_text(time)
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        # Ищем заголовок Notes или Hinweise (немецкий)
        notes_h3 = self.soup.find('h3', string=re.compile(r'Notes?|Hinweise', re.I))
        
        if notes_h3:
            # Ищем следующий div или p после h3
            next_elem = notes_h3.find_next(['div', 'p'])
            if next_elem:
                text = next_elem.get_text(separator=' ', strip=True)
                # Берем только первое предложение до первой точки с запятой или второго предложения
                # так как часто далее идет длинное описание
                if ',' in text:
                    # Ищем первое законченное предложение
                    sentences = text.split('.')
                    if sentences:
                        # Берем первое предложение и добавляем точку
                        first_sentence = sentences[0].strip()
                        if first_sentence:
                            return self.clean_text(first_sentence + '.')
                return self.clean_text(text)
        
        return None
    
    def extract_tags(self) -> Optional[str]:
        """Извлечение тегов"""
        # Ищем div с текстом "Keyword:"
        divs = self.soup.find_all('div', style="")
        
        for div in divs:
            text = div.get_text(strip=True)
            if text.startswith('Keyword:'):
                # Извлекаем теги
                tags = text.replace('Keyword:', '').strip()
                return self.clean_text(tags)
        
        return None
    
    def extract_image_urls(self) -> Optional[str]:
        """Извлечение URL изображений"""
        urls = []
        
        # Ищем все img теги в контенте
        # Обычно главное изображение находится в параграфе после заголовка
        imgs = self.soup.find_all('img')
        
        for img in imgs:
            src = img.get('src')
            if src and src.startswith('http'):
                # Пропускаем иконки и маленькие изображения
                if 'avatar' not in src.lower() and 'icon' not in src.lower():
                    urls.append(src)
        
        # Убираем дубликаты, сохраняя порядок
        if urls:
            seen = set()
            unique_urls = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            # Возвращаем как строку через запятую
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
    # Обрабатываем папку preprocessed/ottima-power_com
    repo_root = Path(__file__).parent.parent
    recipes_dir = repo_root / "preprocessed" / "ottima-power_com"
    
    if recipes_dir.exists() and recipes_dir.is_dir():
        process_directory(OttimaPowerExtractor, str(recipes_dir))
        return
    
    print(f"Директория не найдена: {recipes_dir}")
    print("Использование: python ottima-power_com.py")


if __name__ == "__main__":
    main()
