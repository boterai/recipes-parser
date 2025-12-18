"""
Скрипт для запуска Stage 1: Exploration
"""
import random
import sys
import logging
from pathlib import Path

# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.stages.parse import SearchQueryGenerator, AutoScraper
from utils.languages import POPULAR_LANGUAGES
# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)



def main():
    autoParse = AutoScraper()
    autoParse.search_duckduckgo()



    """generator = SearchQueryGenerator(max_non_searched=10)
    new_queries = generator.generate_search_queries(count=10)

    query_results = {}
    for query in new_queries:
        translated = generator.translate_query(query=query, target_languages=random.sample(POPULAR_LANGUAGES, k=10))
        query_results[query] = translated
    
    generator.save_queries_to_db(query_results)
    

        
    logger.info(f"Сгенерировано {len(new_queries)} новых поисковых запросов:")"""
    
    


if __name__ == "__main__":
    # Создание директории для логов
    Path("logs").mkdir(exist_ok=True)
    main()
