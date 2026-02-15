"""
Экстрактор данных рецептов для сайта tl.inditics.com

Примечание: Этот модуль является алиасом для tl_delachieve_com,
так как preprocessed данные находятся в директории tl_delachieve_com.
"""

import sys
from pathlib import Path

# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

# Импортируем всё из tl_delachieve_com
from extractor.tl_delachieve_com import TlDelachieveExtractor

# Для совместимости с именем модуля
TlInditicsExtractor = TlDelachieveExtractor


def main():
    """
    Точка входа для обработки директории с HTML-страницами
    """
    import os
    from extractor.base import process_directory
    
    # Сначала пробуем найти директорию tl_inditics_com
    preprocessed_dir = os.path.join("preprocessed", "tl_inditics_com")
    
    if not (os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir)):
        # Если нет, используем tl_delachieve_com
        preprocessed_dir = os.path.join("preprocessed", "tl_delachieve_com")
        print(f"Директория tl_inditics_com не найдена, используем: {preprocessed_dir}")
    
    if os.path.exists(preprocessed_dir) and os.path.isdir(preprocessed_dir):
        print(f"Обработка директории: {preprocessed_dir}")
        process_directory(TlDelachieveExtractor, preprocessed_dir)
        return
    
    print(f"Директория не найдена: {preprocessed_dir}")
    print("Использование: python tl_inditics_com.py")


if __name__ == "__main__":
    main()
