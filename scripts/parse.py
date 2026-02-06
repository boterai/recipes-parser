"""
основной скрипт для парсинга рецептов с различных сайтов
парсит сайты для которых уже есть экстракторы
"""

import sys
import logging
from pathlib import Path
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import queue
from typing import Optional
# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.stages.parse.parse import RecipeParserRunner

# Создаем директорию для логов
LOGS_DIR = Path(__file__).parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Базовая настройка только для консоли
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(threadName)s] - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)

logger = logging.getLogger(__name__)


def setup_thread_logger(module_name: str, port: int) -> logging.Logger:
    """
    Создать отдельный логгер для потока
    
    Args:
        module_name: Имя модуля экстрактора
        port: Порт Chrome
    
    Returns:
        Настроенный логгер
    """
    # Уникальное имя логгера для потока
    logger_name = f"parser.{module_name}.{port}"
    thread_logger = logging.getLogger(logger_name)
    thread_logger.setLevel(logging.INFO)
    
    # Убираем наследование handlers от root logger
    thread_logger.propagate = False
    
    # Файл для логов этого потока
    log_file = LOGS_DIR / f"{module_name}_{port}.log"
    
    # FileHandler для записи в файл
    file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    
    # StreamHandler для консоли (опционально)
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


def run_parser_thread(module_name: str, port: int, max_urls: int = 5000, max_depth: int = 4, 
                      max_no_recipe_pages: Optional[int] = 30):
    """
    Запуск парсера в отдельном потоке с собственным логгером
    
    Args:
        module_name: Имя модуля экстрактора
        port: Порт Chrome
        max_urls: Максимальное количество URL
        max_depth: Максимальная глубина обхода
        max_no_recipe_pages: Максимальное количество страниц без рецептов перед остановкой
    """
    # Создаем отдельный логгер для этого потока
    thread_logger = setup_thread_logger(module_name, port)
    
    thread_logger.info(f"{'='*60}")
    thread_logger.info(f"ЗАПУСК ПАРСЕРА ДЛЯ {module_name}")
    thread_logger.info(f"Порт: {port}")
    thread_logger.info(f"Max URLs: {max_urls}, Max Depth: {max_depth}")
    thread_logger.info(f"{'='*60}")
    
    try:
        parser = RecipeParserRunner(extractor_dir="extractor")
        
        parser.run_parser(
            module_name=module_name, 
            port=port, 
            max_urls=max_urls, 
            max_depth=max_depth,
            custom_logger=thread_logger,
            max_no_recipe_pages=max_no_recipe_pages
        )
        
        thread_logger.info(f"✓ Парсинг {module_name} завершен успешно")
        
    except Exception as e:
        thread_logger.error(f"✗ Ошибка при парсинге {module_name}: {e}", exc_info=True)
    
    finally:
        # Закрываем handlers
        for handler in thread_logger.handlers[:]:
            handler.close()
            thread_logger.removeHandler(handler)


def main(module_name: str = "24kitchen_nl", port: int = 9222):
    """Запуск одного парсера"""
    parser = RecipeParserRunner(extractor_dir="extractor")
    
    # Настраиваем логгер для main
    main_logger = setup_thread_logger(module_name=module_name, port=port)
    
    main_logger.info("Запуск одиночного парсера")
    parser.run_parser(
        module_name=module_name, 
        port=port, 
        max_urls=5000, 
        max_depth=4,
        custom_logger=main_logger,
        max_no_recipe_pages=20
    )


def run_parallel(ports: list[int], modules: Optional[list[str]] = None, max_urls: int = 4000, 
                 max_depth: int = 4, max_recipes_per_module: Optional[int] = 4000):
    """
    Запуск парсеров в нескольких потоках с отдельными логами
    
    Args:
        ports: Список портов для парсинга
        max_workers: Максимальное количество потоков (по умолчанию = len(ports))
        max_recipes_per_module: Максимальное количество URL для каждого модуля (далее уже этотт модуль игнорируется)
    """
    logger.info(f"{'='*60}")
    logger.info(f"ПАРАЛЛЕЛЬНЫЙ ЗАПУСК {len(ports)} ПАРСЕРОВ")
    logger.info(f"{'='*60}")
    
    parser = RecipeParserRunner(extractor_dir="extractor")

    # получаем модули для парсинга с учетом max_recipes_per_module и сортируя по убыванию количества рецептов
    site_names = parser.site_repository.get_extractors(max_recipes=max_recipes_per_module, order="asc")

    if not modules:
        modules = [site_name for site_name in site_names if site_name in parser.available_extractors]
    else:
        extractors = [site_name for site_name in site_names if (site_name not in modules and site_name in parser.available_extractors)]
        modules.extend(extractors)
    
    logger.info(f"\nВсего модулей: {len(modules)}, Портов: {len(ports)}")
    
    # Очередь свободных портов
    free_ports = queue.Queue()
    for port in ports:
        free_ports.put(port)
    
    # Очередь модулей для обработки
    module_queue = queue.Queue()
    for module in modules:
        module_queue.put(module)
    
    # Счетчики результатов
    results = {
        "success": 0,
        "failed": 0,
        "lock": threading.Lock()
    }
        
    with ThreadPoolExecutor(max_workers=(len(ports))) as executor:

        futures = {}
        # Создаем futures
        while not free_ports.empty() and not module_queue.empty():
            port = free_ports.get()
            module = module_queue.get()
            
            future = executor.submit(
                run_parser_thread,
                module,
                port,
                max_urls,
                max_depth
            )
            futures[future] = (module, port)
            logger.info(f"▶ Запущен: {module} → port {port}")
    
        # Обрабатываем завершенные задачи и запускаем новые на освободившихся портах
        while futures:
            # Ждем завершения хотя бы одной задачи
            as_completed(futures.keys())
            
            for future in as_completed(futures.keys()):
                module, port = futures.pop(future)
                
                try:
                    future.result()
                    with results["lock"]:
                        results["success"] += 1
                        success_count = results["success"]
                    logger.info(f"✓ Завершен [{success_count}/{len(modules)}]: {module}:{port}")
                except Exception as e:
                    with results["lock"]:
                        results["failed"] += 1
                        failed_count = results["failed"]
                    logger.error(f"✗ Ошибка [{failed_count}]: {module}:{port} - {e}")
                
                # Порт освободился → возвращаем в очередь
                free_ports.put(port)
                
                # Если есть необработанные модули → запускаем на освободившемся порту
                if not module_queue.empty():
                    freed_port = free_ports.get()  # берем освободившийся порт
                    next_module = module_queue.get()
                    
                    new_future = executor.submit(
                        run_parser_thread,
                        next_module,
                        freed_port,
                        max_urls,
                        max_depth
                    )
                    futures[new_future] = (next_module, freed_port)
                    logger.info(f"▶ Запущен: {next_module} → port {freed_port} (после {module})")
                
                # Обрабатываем только одну завершенную задачу за итерацию
                break
    
    logger.info(f"\n{'='*60}")
    logger.info("ВСЕ ПАРСЕРЫ ЗАВЕРШЕНЫ")
    logger.info(f"Успешно: {results['success']}, Ошибок: {results['failed']}")
    logger.info(f"Логи сохранены в: {LOGS_DIR}")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Парсинг рецептов с сайтов')
    parser.add_argument(
        '--parallel',
        action='store_true',
        default=False,
        help='Запустить в нескольких потоках'
    )
    parser.add_argument(
        '--ports',
        type=int,
        nargs='+',
        default=[9222, 9223, 9224, 9225, 9226],
        help='Список портов для параллельного запуска (по умолчанию: 9222 9223 9224)'
    )

    parser.add_argument(
        '--modules',
        type=str,
        default=["unaricettaalgiorno_com", "xrysessyntages_com", "smachnoho_com_ua", "tl_usefultipsdiy_com"],
        help='Имя модуля экстрактора для одиночного запуска (по умолчанию: 24kitchen_nl)'
    )

    parser.add_argument(
        '--max_recipes_per_module',
        type=int,
        default=4000,
        help='Максимальное количество рецептов для каждого модуля при параллельном запуске'
    )

    parser.add_argument(
        '--max_urls',
        type=int,
        default=10_000,
        help='Максимальное количество просмотренных URL для каждого модуля'
    )
    
    args = parser.parse_args()
    
    if args.parallel:
        run_parallel(ports=args.ports,  modules=None, max_recipes_per_module=args.max_recipes_per_module, max_urls=args.max_urls)
    else:
        main("allrecipes_com", args.ports[0])