"""
Экстрактор данных рецептов для сайта recipetineats.com (site_id = 6)
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional
from bs4 import BeautifulSoup
import os

# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))


class RecipeTinEatsExtractor:
    """Экстрактор для recipetineats.com"""
    
    def __init__(self, html_path: str):
        """
        Args:
            html_path: Путь к HTML файлу
        """
        self.html_path = html_path
        with open(html_path, 'r', encoding='utf-8') as f:
            self.soup = BeautifulSoup(f.read(), 'lxml')
    
    @staticmethod
    def clean_text(text: str) -> str:
        """Очистка текста от нечитаемых символов и нормализация"""
        if not text:
            return text
        
        # Удаляем Unicode символы типа ▢, □, ✓ и другие специальные символы
        text = re.sub(r'[▢□✓✔▪▫●○■]', '', text)
        # Удаляем лишние пробелы
        text = re.sub(r'\s+', ' ', text)
        # Убираем пробелы в начале и конце
        text = text.strip()
        return text
    
    @staticmethod
    def normalize_time(time_str: str) -> str:
        """Нормализация формата времени (добавление пробелов)"""
        if not time_str:
            return time_str
        
        # Паттерны для добавления пробелов: 30minutes -> 30 minutes
        time_str = re.sub(r'(\d+)(minutes?|hours?|days?|mins?|hrs?)', r'\1 \2', time_str, flags=re.IGNORECASE)
        # Убираем двойные пробелы
        time_str = re.sub(r'\s+', ' ', time_str)
        return time_str.strip()
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта
        recipe_header = self.soup.find('h2', class_='wprm-recipe-name')
        if recipe_header:
            return recipe_header.get_text(strip=True)
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            # Убираем суффиксы типа " - RecipeTin Eats"
            title = og_title['content']
            title = re.sub(r'\s*[-–—]\s*RecipeTin Eats.*$', '', title, flags=re.IGNORECASE)
            return title.strip()
        
        return None
    
    def extract_ingredients(self) -> Optional[str]:
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем контейнер с ингредиентами
        ingredient_list = self.soup.find('ul', class_='wprm-recipe-ingredients')
        if not ingredient_list:
            ingredient_list = self.soup.find('div', class_='wprm-recipe-ingredients')
        
        if ingredient_list:
            # Извлекаем все элементы списка ингредиентов
            items = ingredient_list.find_all('li', class_='wprm-recipe-ingredient')
            
            for item in items:
                # Собираем текст из всех частей ингредиента
                ingredient_text = item.get_text(separator=' ', strip=True)
                # Очищаем от нечитаемых символов
                ingredient_text = self.clean_text(ingredient_text)
                if ingredient_text:
                    ingredients.append(ingredient_text)
        
        return ', '.join(ingredients) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем контейнер с инструкциями
        instructions_list = self.soup.find('ul', class_='wprm-recipe-instructions')
        if not instructions_list:
            instructions_list = self.soup.find('div', class_='wprm-recipe-instructions')
        
        if instructions_list:
            # Извлекаем все шаги
            step_items = instructions_list.find_all('li', class_='wprm-recipe-instruction')
            
            for idx, item in enumerate(step_items, 1):
                # Извлекаем текст инструкции
                step_text = item.find('div', class_='wprm-recipe-instruction-text')
                if step_text:
                    text = step_text.get_text(separator=' ', strip=True)
                    text = re.sub(r'\s+', ' ', text)
                    if text:
                        steps.append(f"{idx}. {text}")
        
        return ' '.join(steps) if steps else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        nutrition_data = []
        
        # Ищем контейнер с питательной информацией
        nutrition_container = self.soup.find('div', class_='wprm-nutrition-label-container')
        
        if nutrition_container:
            # Извлекаем все элементы питательности
            nutrition_items = nutrition_container.find_all('span', class_='wprm-nutrition-label-text-nutrition-container')
            
            for item in nutrition_items:
                label = item.find('span', class_='wprm-nutrition-label-text-nutrition-label')
                value = item.find('span', class_='wprm-nutrition-label-text-nutrition-value')
                unit = item.find('span', class_='wprm-nutrition-label-text-nutrition-unit')
                
                if label and value:
                    label_text = label.get_text(strip=True).rstrip(':')
                    value_text = value.get_text(strip=True)
                    unit_text = unit.get_text(strip=True) if unit else ''
                    
                    nutrition_data.append(f"{label_text}: {value_text} {unit_text}".strip())
        
        return ', '.join(nutrition_data) if nutrition_data else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в метаданных рецепта
        course = self.soup.find('span', class_='wprm-recipe-course')
        if course:
            return course.get_text(strip=True)
        
        # Альтернативно - из мета-тегов
        article_section = self.soup.find('meta', property='article:section')
        if article_section and article_section.get('content'):
            return article_section['content']
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        prep_time = self.soup.find('span', class_='wprm-recipe-prep_time')
        if prep_time:
            time_text = prep_time.get_text(strip=True)
            return self.normalize_time(time_text)
        
        # Альтернативный поиск в метаданных
        prep_time_meta = self.soup.find('span', class_='wprm-recipe-details wprm-recipe-details-minutes wprm-recipe-prep_time')
        if prep_time_meta:
            minutes = prep_time_meta.get_text(strip=True)
            time_text = f"{minutes} minutes" if minutes.isdigit() else minutes
            return self.normalize_time(time_text)
        
        return None
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        cook_time = self.soup.find('span', class_='wprm-recipe-cook_time')
        if cook_time:
            time_text = cook_time.get_text(strip=True)
            return self.normalize_time(time_text)
        
        # Альтернативный поиск
        cook_time_meta = self.soup.find('span', class_='wprm-recipe-details wprm-recipe-details-minutes wprm-recipe-cook_time')
        if cook_time_meta:
            minutes = cook_time_meta.get_text(strip=True)
            time_text = f"{minutes} minutes" if minutes.isdigit() else minutes
            return self.normalize_time(time_text)
        
        return None
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        total_time = self.soup.find('span', class_='wprm-recipe-total_time')
        if total_time:
            time_text = total_time.get_text(strip=True)
            return self.normalize_time(time_text)
        
        # Альтернативный поиск
        total_time_meta = self.soup.find('span', class_='wprm-recipe-details wprm-recipe-details-minutes wprm-recipe-total_time')
        if total_time_meta:
            minutes = total_time_meta.get_text(strip=True)
            time_text = f"{minutes} minutes" if minutes.isdigit() else minutes
            return self.normalize_time(time_text)
        
        return None
    
    def extract_servings(self) -> Optional[str]:
        """Извлечение количества порций"""
        servings = self.soup.find('span', class_='wprm-recipe-servings')
        if servings:
            return servings.get_text(strip=True)
        
        return None
    
    def extract_difficulty_level(self) -> Optional[str]:
        """Извлечение уровня сложности"""
        # На этом сайте обычно нет явного указания сложности
        # Можем попробовать определить по времени или оставить как "Easy"
        return "Easy"
    
    def extract_description(self) -> Optional[str]:
        """Извлечение описания рецепта"""
        # Ищем описание в summary
        summary = self.soup.find('div', class_='wprm-recipe-summary')
        if summary:
            desc_text = summary.get_text(separator=' ', strip=True)
            return self.clean_text(desc_text)
        
        # Альтернативно - из meta description
        meta_desc = self.soup.find('meta', property='og:description')
        if meta_desc and meta_desc.get('content'):
            return self.clean_text(meta_desc['content'])
        
        return None
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем секцию с заметками
        notes_section = self.soup.find('div', class_='wprm-recipe-notes')
        if notes_section:
            # Извлекаем все параграфы
            paragraphs = notes_section.find_all(['p', 'li'])
            for p in paragraphs:
                note_text = p.get_text(strip=True)
                note_text = self.clean_text(note_text)
                if note_text:
                    notes.append(note_text)
        
        return ' '.join(notes) if notes else None
    
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
            "step_by_step": self.extract_steps(),
            "nutrition_info": self.extract_nutrition_info(),
            "category": self.extract_category(),
            "prep_time": self.extract_prep_time(),
            "cook_time": self.extract_cook_time(),
            "total_time": self.extract_total_time(),
            "servings": self.extract_servings(),
            "difficulty_level": self.extract_difficulty_level(),
            "notes": self.extract_notes()
        }


def process_html_file(html_path: str, output_path: Optional[str] = None) -> dict:
    """
    Обработка одного HTML файла
    
    Args:
        html_path: Путь к HTML файлу
        output_path: Путь для сохранения JSON (если None, то рядом с HTML)
    
    Returns:
        Извлеченные данные
    """
    extractor = RecipeTinEatsExtractor(html_path)
    data = extractor.extract_all()
    
    # Определяем путь для сохранения
    if output_path is None:
        output_path = html_path.replace('.html', '_extracted.json')
    
    # Сохраняем результат
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    
    print(f"✓ Обработан: {html_path}")
    print(f"  Сохранен: {output_path}")
    
    return data


def process_directory(directory_path: str):
    """
    Обработка всех HTML файлов в директории
    
    Args:
        directory_path: Путь к директории с HTML файлами
    """
    from pathlib import Path
    
    dir_path = Path(directory_path)
    html_files = list(dir_path.glob('*.html'))
    
    print(f"Найдено {len(html_files)} HTML файлов")
    print("=" * 60)
    
    for html_file in html_files:
        try:
            process_html_file(str(html_file))
        except Exception as e:
            print(f"✗ Ошибка при обработке {html_file.name}: {e}")
    
    print("=" * 60)
    print(f"Обработка завершена!")


def main():
    """Пример использования"""
    
    recipes_dir = os.path.join("recipes", "recipetineats_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(str(recipes_dir))
    else:
        print(f"Директория не найдена: {recipes_dir}")
        print("Использование: python site_6.py [путь_к_файлу_или_директории]")


if __name__ == "__main__":
    main()
