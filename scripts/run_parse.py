"""
Скрипт для запуска Stage 1: Exploration
"""
import random
import sys
import logging
from pathlib import Path
import json
# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.stages.parse.auto_scraper import AutoScraper
from src.stages.parse.site_preparation_pipeline import SitePreparationPipeline
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
    auto_scraper.run_auto_scraping()

def main():
    """Основная функция"""
    
            

if __name__ == "__main__":
    prepare()
