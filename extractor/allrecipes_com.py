"""
Экстрактор данных рецептов для сайта allrecipes.com (site_id = 1)
"""

import sys
from pathlib import Path
import json
import re
from typing import Optional
from bs4 import BeautifulSoup

# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))


class AllRecipesExtractor:
    """Экстрактор для allrecipes.com"""
    
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
        """Очистка текста от лишних символов и нормализация"""
        if not text:
            return text
        
        # Удаляем лишние пробелы
        text = re.sub(r'\s+', ' ', text)
        # Убираем пробелы в начале и конце
        text = text.strip()
        return text
    
    def extract_dish_name(self) -> Optional[str]:
        """Извлечение названия блюда"""
        # Ищем в заголовке рецепта
        recipe_header = self.soup.find('h1', class_='article-heading')
        if recipe_header:
            return self.clean_text(recipe_header.get_text())
        
        # Альтернативно - из meta тега og:title
        og_title = self.soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
            # Убираем суффиксы типа " Recipe", " - Allrecipes"
            title = re.sub(r'\s+(Recipe|Allrecipes).*$', '', title, flags=re.IGNORECASE)
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
        """Извлечение ингредиентов"""
        ingredients = []
        
        # Ищем список ингредиентов через различные возможные классы
        ingredient_containers = [
            self.soup.find('ul', class_=re.compile(r'ingredient.*list', re.I)),
            self.soup.find('div', class_=re.compile(r'ingredient', re.I))
        ]
        
        for container in ingredient_containers:
            if not container:
                continue
                
            # Извлекаем элементы списка
            items = container.find_all('li')
            if not items:
                items = container.find_all('p')
            
            for item in items:
                # Извлекаем текст ингредиента
                ingredient_text = item.get_text(separator=' ', strip=True)
                ingredient_text = self.clean_text(ingredient_text)
                
                # Пропускаем заголовки секций (часто содержат двоеточие)
                if ingredient_text and not ingredient_text.endswith(':'):
                    ingredients.append(ingredient_text)
            
            if ingredients:
                break
        
        return ', '.join(ingredients) if ingredients else None
    
    def extract_steps(self) -> Optional[str]:
        """Извлечение шагов приготовления"""
        steps = []
        
        # Ищем контейнер с инструкциями
        instructions_containers = [
            self.soup.find('ol', class_=re.compile(r'instruction.*list', re.I)),
            self.soup.find('div', class_=re.compile(r'instruction', re.I))
        ]
        
        for container in instructions_containers:
            if not container:
                continue
            
            # Извлекаем шаги
            step_items = container.find_all('li')
            if not step_items:
                step_items = container.find_all('p')
            
            for item in step_items:
                # Извлекаем текст инструкции
                step_text = item.get_text(separator=' ', strip=True)
                step_text = self.clean_text(step_text)
                
                if step_text:
                    steps.append(step_text)
            
            if steps:
                break
        
        # Если нумерация не была в HTML, добавляем её
        if steps and not re.match(r'^\d+\.', steps[0]):
            steps = [f"{idx}. {step}" for idx, step in enumerate(steps, 1)]
        
        return ' '.join(steps) if steps else None
    
    def extract_nutrition_info(self) -> Optional[str]:
        """Извлечение информации о питательности"""
        nutrition_data = []
        
        # Ищем таблицу питательности
        nutrition_container = self.soup.find('div', class_=re.compile(r'nutrition', re.I))
        if not nutrition_container:
            nutrition_container = self.soup.find('table', class_=re.compile(r'nutrition', re.I))
        
        if nutrition_container:
            # Ищем строки с данными о питательности
            rows = nutrition_container.find_all(['tr', 'div', 'p'])
            
            for row in rows:
                text = row.get_text(separator=' ', strip=True)
                text = self.clean_text(text)
                
                # Проверяем, содержит ли строка питательные данные
                if re.search(r'\d+\s*(cal|g|mg|kcal)', text, re.I):
                    nutrition_data.append(text)
        
        # Альтернативный поиск через span или dt/dd
        if not nutrition_data:
            nutrition_items = self.soup.find_all(['span', 'dt', 'dd'], class_=re.compile(r'nutrition', re.I))
            for item in nutrition_items:
                text = item.get_text(strip=True)
                if text and re.search(r'\d', text):
                    nutrition_data.append(text)
        
        return '; '.join(nutrition_data) if nutrition_data else None
    
    def extract_category(self) -> Optional[str]:
        """Извлечение категории"""
        # Ищем в метаданных
        meta_section = self.soup.find('meta', property='article:section')
        if meta_section and meta_section.get('content'):
            return self.clean_text(meta_section['content'])
        
        # Ищем в хлебных крошках
        breadcrumbs = self.soup.find('nav', class_=re.compile(r'breadcrumb', re.I))
        if breadcrumbs:
            links = breadcrumbs.find_all('a')
            if len(links) > 1:  # Берем последнюю категорию перед самим рецептом
                return self.clean_text(links[-1].get_text())
        
        return None
    
    def extract_time(self, time_type: str) -> Optional[str]:
        """
        Извлечение времени (prep/cook/total)
        
        Args:
            time_type: Тип времени ('prep', 'cook', 'total')
        """
        # Ищем по data-атрибутам или классам
        time_patterns = {
            'prep': ['prep.*time', 'preparation'],
            'cook': ['cook.*time', 'cooking'],
            'total': ['total.*time', 'ready.*in']
        }
        
        patterns = time_patterns.get(time_type, [])
        
        for pattern in patterns:
            # Ищем элемент с временем
            time_elem = self.soup.find(class_=re.compile(pattern, re.I))
            if not time_elem:
                time_elem = self.soup.find(attrs={'data-test-id': re.compile(pattern, re.I)})
            
            if time_elem:
                time_text = time_elem.get_text(strip=True)
                return self.clean_text(time_text)
        
        return None
    
    def extract_prep_time(self) -> Optional[str]:
        """Извлечение времени подготовки"""
        return self.extract_time('prep')
    
    def extract_cook_time(self) -> Optional[str]:
        """Извлечение времени приготовления"""
        return self.extract_time('cook')
    
    def extract_total_time(self) -> Optional[str]:
        """Извлечение общего времени"""
        return self.extract_time('total')
    
    def extract_servings(self) -> Optional[str]:
        """Извлечение количества порций"""
        # Ищем элемент с порциями
        servings_elem = self.soup.find(class_=re.compile(r'servings?|yield', re.I))
        if not servings_elem:
            servings_elem = self.soup.find(attrs={'data-test-id': re.compile(r'servings?', re.I)})
        
        if servings_elem:
            text = servings_elem.get_text(strip=True)
            # Извлекаем только число или число с единицей
            match = re.search(r'\d+(?:\s*servings?)?', text, re.I)
            if match:
                return match.group(0)
        
        return None
    
    def extract_difficulty_level(self) -> Optional[str]:
        """Извлечение уровня сложности"""
        # На allrecipes обычно нет явного указания сложности
        # Можно попробовать определить по времени или оставить как "Easy"
        return "Easy"
    
    def extract_notes(self) -> Optional[str]:
        """Извлечение заметок и советов"""
        notes = []
        
        # Ищем секцию с примечаниями/советами
        notes_patterns = ['notes?', 'tips?', 'cook.*notes?', 'editor.*notes?']
        
        for pattern in notes_patterns:
            notes_section = self.soup.find(class_=re.compile(pattern, re.I))
            if notes_section:
                # Извлекаем текст
                note_text = notes_section.get_text(separator=' ', strip=True)
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
    extractor = AllRecipesExtractor(html_path)
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
    print("Обработка завершена!")


def main():
    import os
    # По умолчанию обрабатываем папку recipes/site_1
    recipes_dir = os.path.join("recipes", "allrecipes_com")
    if os.path.exists(recipes_dir) and os.path.isdir(recipes_dir):
        process_directory(str(recipes_dir))
    else:
        print(f"Директория не найдена: {recipes_dir}")
        print("Использование: python site_1.py [путь_к_файлу_или_директории]")


if __name__ == "__main__":
    main()
