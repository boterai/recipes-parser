"""
базовый класс экстарктора данных рецептов
Все классы должны наследоваться от этого класса и реализовывать метод extract_all
Все классы должны быть реализованы в файлах внутри папки extractor/
Все классы должны находиться в папках по именам доменов сайтов, чтобы не приходилось меня класс при добавлении нового сайта
Для поиска все наследники должны иметь имя вида <SiteName>Extractor, например AllRecipesExtractor (ищем класс с "Extractor" в имени при импорте модуля)
"""

import html
import json
import sys
from pathlib import Path
import re
from bs4 import BeautifulSoup
from typing import Optional, Type
from abc import ABC, abstractmethod

# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))


class BaseRecipeExtractor(ABC):
    """базовый эксрактор данных рецептов"""
    
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
        
        # Декодируем HTML entities (&#039; -> ', &quot; -> ", etc.)
        text = html.unescape(text)
        
        # Удаляем Unicode символы типа ▢, □, ✓ и другие специальные символы
        text = re.sub(r'[▢□✓✔▪▫●○■]', '', text)
        # Удаляем лишние пробелы
        text = re.sub(r'\s+', ' ', text)
        # Убираем пробелы в начале и конце
        text = text.strip()
        return text
    
    @abstractmethod
    def extract_all(self) -> dict:
        """Извлечение всех данных рецепта из HTML"""
        raise NotImplementedError("Метод extract_all должен быть реализован в подклассе")


def process_html_file(extractor_class: Type[BaseRecipeExtractor], 
                      html_path: str, 
                      output_path: Optional[str] = None) -> dict:
    """
    Обработка одного HTML файла
    
    Args:
        html_path: Путь к HTML файлу
        output_path: Путь для сохранения JSON (если None, то рядом с HTML)
    
    Returns:
        Извлеченные данные
    """
    extractor = extractor_class(html_path)
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


def process_directory(extractor_class: Type[BaseRecipeExtractor],  directory_path: str):
    """
    Обработка всех HTML файлов в директории
    
    Args:
        directory_path: Путь к директории с HTML файлами
    """    
    dir_path = Path(directory_path)
    html_files = list(dir_path.glob('*.html'))
    
    print(f"Найдено {len(html_files)} HTML файлов")
    print("=" * 60)
    
    for html_file in html_files:
        try:
            process_html_file(extractor_class, str(html_file))
        except Exception as e:
            print(f"✗ Ошибка при обработке {html_file.name}: {e}")
            import traceback
            traceback.print_exc()
    
    print("=" * 60)
    print("Обработка завершена!")