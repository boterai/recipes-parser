"""Скрипт для запуска Stage 3 - извлечение данных рецептов из HTML"""

import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.common.database import DatabaseManager
from src.common.database import DatabaseManager
from src.stages.extract import RecipeExtractor


def main():
    """Основная функция"""
    
    # Инициализация БД
    db = DatabaseManager()
    if not db.connect():
        print("Не удалось подключиться к базе данных")
        return
    
    # Создаем экстрактор
    extractor = RecipeExtractor(db)
    extractor.process_site_recipes(site_id=5)


if __name__ == '__main__':
    main()
