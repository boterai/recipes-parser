#!/usr/bin/env python3
"""
Скрипт запуска Stage 2: Предварительный анализ HTML страниц с ChatGPT
"""

import sys
import argparse
from pathlib import Path

# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.stage2_analyse.analyse import RecipeAnalyzer


def main():
    
    analyzer = RecipeAnalyzer()
    
    try:
        analyzer.analyze_all_pages(site_id=1, limit=1)
    except KeyboardInterrupt:
        print("\nПрервано пользователем")
    except Exception as e:
        print(f"Ошибка: {e}")
        sys.exit(1)
    finally:
        analyzer.close()


if __name__ == "__main__":
    main()
