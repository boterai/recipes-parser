"""
Скрипт для запуска подготовки сайтов (поиск и создание экстракторов)
"""
import sys
import logging
from pathlib import Path
import argparse
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed

# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.stages.parse.auto_scraper import AutoScraper
from src.stages.workflow.copilot_workflow import CopilotWorkflow

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

def create_issues(issue_prefix: str = "Создать парсер "):
    """
    создание issues для новых парсеров
    """
    workflow = CopilotWorkflow()
    workflow.check_review_requested_prs(issue_prefix=issue_prefix)

def merge_completed_prs():
    """
    проверка и слияние завершенных PRs
    """
    workflow = CopilotWorkflow()
    workflow.check_review_requested_prs()


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


def run_one_site_thread(port: int, sites_q: queue.Queue, max_pages: int =60):
    """
    Запуск подготовки сайтов в отдельном потоке
    
    Args:
        port: Порт Chrome
        site: Сайт для подготовки
        max_pages: Максимальное количество страниц для проверки сайта на наличие рецептов
    """
    thread_logger = setup_thread_logger(port)
    
    thread_logger.info(f"{'='*60}")
    thread_logger.info(f"ЗАПУСК ПОДГОТОВКИ САЙТОВ НА ПОРТУ {port}")
    thread_logger.info(f"{'='*60}")
    auto_scraper = AutoScraper(debug_port=port, custom_logger=thread_logger)
    
    try:
        while True:
            try:
                site = sites_q.get_nowait()
            except queue.Empty:
                thread_logger.info(f"Очередь сайтов пуста, завершаем поток на порту {port}")
                break

            try:
                thread_logger.info(f"\n=== Обработка сайта ID={site.id}, URL={site.base_url} ===")
                auto_scraper.process_one_site(site, max_pages=max_pages)
                thread_logger.info(f"✓ Подготовка сайтов на порту {port} завершена успешно")
            except Exception as e:
                thread_logger.error(f"✗ Ошибка при подготовке сайта ID={site.id}, URL={site.base_url}: {e}", exc_info=True)
                continue
            finally:
                sites_q.task_done()

        thread_logger.info(f"Все сайты из очереди обработаны на порту {port}")

    except Exception as e:
        thread_logger.error(f"✗ Ошибка при подготовке сайтов на порту {port}: {e}", exc_info=True)
    
    finally:
        # Закрываем handlers
        for handler in thread_logger.handlers[:]:
            handler.close()
            thread_logger.removeHandler(handler)


def prepare(port: int = 9222, min_unprocessed_sites: int = 150, generate_from_recipes: bool = True, generate_with_gpt: bool = False):
    """Подготовка сайтов (одиночный режим)"""
    auto_scraper = AutoScraper(debug_port=port)
    auto_scraper.find_new_sites(
        generate_from_recipes=generate_from_recipes,
        target_sites_count=min_unprocessed_sites,
        generate_with_gpt=generate_with_gpt
    )
    sites = auto_scraper.site_repository.get_unprocessed_sites()
    for site in sites:
        auto_scraper.process_one_site(site)


def run_parallel_preparation(
    ports: list[int],
    target_sites_count: int = 150, 
    generate_from_recipes: bool = False,
    generate_with_gpt: bool = True,
    max_pages: int = 60
):
    """
    Запуск подготовки сайтов в нескольких потоках
    
    Args:
        ports: Список портов Chrome
        max_workers: Максимальное количество потоков
        target_sites_count: Кол-во сайтов, которое нужно проверить (при необходимости сгенерировать новые из рецептов или с помощью GPT)
        generate_from_recipes: Генерировать ли из рецептов
        generate_with_gpt: Генерировать ли с помощью GPT
        max_pages: Максимальное количество страниц для проверки сайта на наличие рецептов
    """
    if not ports:
        logger.error("Список портов пуст, невозможно запустить подготовку сайтов")
        return
    # Логируем план
    for i, port in enumerate(ports, 1):
        logger.info(f"  [{i}] Port {port} → logs/prepare_site_{port}.log")
    
    auto_scraper = AutoScraper(debug_port=ports[0], custom_logger=logger)

    # сначала проверим, нужно ли вообще искать новые сайты
    auto_scraper.find_new_sites(
        generate_from_recipes=generate_from_recipes,
        target_sites_count=target_sites_count,
        generate_with_gpt=generate_with_gpt
    )
    # получаем необходимое количество сайтов для подготовки
    sites = auto_scraper.site_repository.get_unprocessed_sites(random_order=True, limit=target_sites_count)
    sites = [s.to_pydantic() for s in sites]

    logger.info(f"Всего необработанных сайтов для подготовки: {len(sites)}")

    site_q = queue.Queue()
    for site in sites:
        site_q.put(site)

    # Запускаем в потоках
    max_workers = len(ports)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_one_site_thread,port,site_q, max_pages): port
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

if __name__ == "__main__":

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
        default=[9222],
        help='Список портов Chrome (по умолчанию: 9222)'
    )

    parser.add_argument(
        '--target-sites-count',
        type=int,
        default=200,
        help='Минимальное количество необработанных, те уже собранных сайтов (по умолчанию: 150)'
    )

    parser.add_argument(
        '--generate-from-recipes',
        action='store_true',
        default=False,
        help='Генерировать новые сайты из уже собранных рецептов'
    )

    parser.add_argument(
        '--generate-with-gpt',
        action='store_true',
        default=True,
        help='Генерировать новые сайты с помощью GPT'
    )
    
    args = parser.parse_args()
    
    if args.parallel:
        run_parallel_preparation(
            ports=args.ports,
            target_sites_count=args.target_sites_count,
            generate_from_recipes=args.generate_from_recipes,
            generate_with_gpt=args.generate_with_gpt
        )
    else:
        prepare(
            port=args.ports[0],
            min_unprocessed_sites=args.target_sites_count,
            generate_from_recipes=args.generate_from_recipes,
            generate_with_gpt=args.generate_with_gpt   
            )
