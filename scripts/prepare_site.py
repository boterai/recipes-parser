"""
Скрипт для запуска Stage 1: Exploration
"""
import sys
import logging
from pathlib import Path
# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.stages.parse.auto_scraper import AutoScraper
# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

def prepare():
    # запустить подготовку сайтов для создания парсеров рецептов
    auto_scraper = AutoScraper(debug_port=9222)
    auto_scraper.run_auto_scraping(generate_from_recipes=True, min_unprocessed_sites=150)

if __name__ == "__main__":
    prepare()
