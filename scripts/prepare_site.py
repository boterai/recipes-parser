"""
Скрипт для запуска подготовки сайтов (поиск и создание экстракторов)
"""
import sys
import logging
from pathlib import Path
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.stages.parse.auto_scraper import AutoScraper

# Создаем директорию для логов
LOGS_DIR = Path(__file__).parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(threadName)s] - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


def setup_thread_logger(port: int) -> logging.Logger:
    """
    Создать отдельный логгер для потока
    
    Args:
        port: Порт Chrome для этого потока
    
    Returns:
        Настроенный логгер
    """
    logger_name = f"prepare_site.port_{port}"
    thread_logger = logging.getLogger(logger_name)
    thread_logger.setLevel(logging.INFO)
    
    # Убираем наследование handlers от root logger
    thread_logger.propagate = False
    
    # Файл для логов этого потока
    log_file = LOGS_DIR / f"prepare_site_{port}.log"
    
    # FileHandler для записи в файл
    file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    
    # StreamHandler для консоли
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Форматирование
    formatter = logging.Formatter(
        '%(asctime)s - [%(threadName)s] - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Добавляем handlers
    thread_logger.addHandler(file_handler)
    thread_logger.addHandler(console_handler)
    
    return thread_logger


def prepare_thread(port: int, min_unprocessed_sites: int = 150):
    """
    Запуск подготовки сайтов в отдельном потоке
    
    Args:
        port: Порт Chrome
        min_unprocessed_sites: Минимальное количество необработанных сайтов
        generate_from_recipes: Генерировать ли из рецептов
    """
    thread_logger = setup_thread_logger(port)
    
    thread_logger.info(f"{'='*60}")
    thread_logger.info(f"ЗАПУСК ПОДГОТОВКИ САЙТОВ НА ПОРТУ {port}")
    thread_logger.info(f"{'='*60}")
    
    try:
        auto_scraper = AutoScraper(debug_port=port, custom_logger=thread_logger)
        auto_scraper.run_auto_scraping(
            generate_from_recipes=False,
            min_unprocessed_sites=min_unprocessed_sites
        )
        
        thread_logger.info(f"✓ Подготовка сайтов на порту {port} завершена успешно")
        
    except Exception as e:
        thread_logger.error(f"✗ Ошибка при подготовке сайтов на порту {port}: {e}", exc_info=True)
    
    finally:
        # Закрываем handlers
        for handler in thread_logger.handlers[:]:
            handler.close()
            thread_logger.removeHandler(handler)


def prepare(port: int = 9222, min_unprocessed_sites: int = 150, generate_from_recipes: bool = True):
    """Подготовка сайтов (одиночный режим)"""
    auto_scraper = AutoScraper(debug_port=port)
    auto_scraper.run_auto_scraping(
        generate_from_recipes=generate_from_recipes,
        min_unprocessed_sites=min_unprocessed_sites
    )


def run_parallel_preparation(
    ports: list[int],
    min_unprocessed_sites: int = 150
):
    """
    Запуск подготовки сайтов в нескольких потоках
    
    Args:
        ports: Список портов Chrome
        max_workers: Максимальное количество потоков
        min_unprocessed_sites: Минимальное количество необработанных сайтов
        generate_from_recipes: Генерировать ли из рецептов
    """
    # Логируем план
    for i, port in enumerate(ports, 1):
        logger.info(f"  [{i}] Port {port} → logs/prepare_site_{port}.log")
    
    logger.info(f"\n{'='*60}\n")
    
    # Запускаем в потоках
    max_workers = len(ports)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                prepare_thread,
                port,
                min_unprocessed_sites=min_unprocessed_sites,
            ): port
            for port in ports
        }
        
        # Ждем завершения
        for future in as_completed(futures):
            port = futures[future]
            try:
                future.result()
                logger.info(f"✓ Поток port {port} завершен")
            except Exception as e:
                logger.error(f"✗ Ошибка в потоке port {port}: {e}")
    
    logger.info(f"\n{'='*60}")
    logger.info("ВСЯ ПОДГОТОВКА САЙТОВ ЗАВЕРШЕНА")
    logger.info(f"Логи сохранены в: {LOGS_DIR}")
    logger.info(f"{'='*60}")


def preprocess_sites():
    from src.stages.parse.auto_scraper import AutoScraper
    from src.stages.analyse.analyse import RecipeAnalyzer
    """Предварительная обработка сайтов перед парсингом"""
    analyzer = RecipeAnalyzer()
    analyzer.analyze_all_pages(site_id=280, filter_by_title=True, stop_analyse=3)

    autoScraper = AutoScraper(debug_port=9222)
    autoScraper._check_pages_for_recipes({"https://smachnoho.com.ua/"})



if __name__ == "__main__":
    preprocess_sites()

    parser = argparse.ArgumentParser(description='Подготовка сайтов для парсинга рецептов')
    parser.add_argument(
        '--parallel',
        action='store_true',
        default=True,
        help='Запустить в нескольких потоках'
    )
    parser.add_argument(
        '--ports',
        type=int,
        nargs='+',
        default=[9222, 9223],
        help='Список портов Chrome (по умолчанию: 9222)'
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=None,
        help='Максимальное количество параллельных потоков'
    )
    parser.add_argument(
        '--min-sites',
        type=int,
        default=150,
        help='Минимальное количество необработанных сайтов (по умолчанию: 150)'
    )
    
    args = parser.parse_args()
    
    if args.parallel:
        run_parallel_preparation(
            ports=args.ports,
            min_unprocessed_sites=args.min_sites
        )
    else:
        prepare(
            port=args.ports[0],
            min_unprocessed_sites=args.min_sites       
            )
