"""
Скрипт для запуска Stage 1: Exploration
"""

import sys
import logging
from pathlib import Path

# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.stages.parse import explore_site

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)



def main():
    
    url = "https://www.allrecipes.com/"
    max_urls = 1000
    max_depth = 4
    
    explore_site(url, max_urls=max_urls, max_depth=max_depth)


if __name__ == "__main__":
    # Создание директории для логов
    Path("logs").mkdir(exist_ok=True)
    main()
