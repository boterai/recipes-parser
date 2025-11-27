"""
Скрипт для запуска Stage 1: Exploration
"""

import sys
import logging
from pathlib import Path

# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.stages.parse import SiteExplorer

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


def main():
    
    url = "https://www.allrecipes.com/"
    max_urls = 400
    max_depth = 4
    
    explorer = SiteExplorer(url, debug_mode=True, use_db=True)
    
    try:
        explorer.connect_to_chrome()
        explorer.load_state()
        explorer.explore(max_urls=max_urls, max_depth=max_depth)
    except KeyboardInterrupt:
        logger.info("\nПрервано пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
    finally:
        explorer.close()


if __name__ == "__main__":
    # Создание директории для логов
    Path("logs").mkdir(exist_ok=True)
    main()
