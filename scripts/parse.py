"""
основной скрипт для парсинга рецептов с различных сайтов
парсит сайты для которых уже есть экстракторы
"""

import sys
import logging
from pathlib import Path
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

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

SITES_CONFIG = {
    1: {
        'name': '24kitchen_nl',
        'debug_port': 9222,
    },
    2: {
        'name': 'speedinfo_com_ua',
        'debug_port': 9223,
    },
    3: {
        'name': 'onedaywetakeatrain_fi',
        'debug_port': 9224,
    },
    4: {
        'name': 'chefkoch_de',
        'debug_port': 9225,
    },
    5: {
        'name': 'kitchen_sayidaty_net',
        'debug_port': 9226,
    }
}


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


def run_parser_thread(module_name: str, port: int, max_urls: int = 5000, max_depth: int = 4):
    """
    Запуск парсера в отдельном потоке с собственным логгером
    
    Args:
        module_name: Имя модуля экстрактора
        port: Порт Chrome
        max_urls: Максимальное количество URL
        max_depth: Максимальная глубина обхода
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
            custom_logger=thread_logger
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
        custom_logger=main_logger
    )


def run_parallel(ports: list[int], max_workers: int = None, modules: list[str] = None):
    """
    Запуск парсеров в нескольких потоках с отдельными логами
    
    Args:
        ports: Список портов для парсинга
        max_workers: Максимальное количество потоков (по умолчанию = len(ports))
    """
    logger.info(f"{'='*60}")
    logger.info(f"ПАРАЛЛЕЛЬНЫЙ ЗАПУСК {len(ports)} ПАРСЕРОВ")
    logger.info(f"{'='*60}")
    
    parser = RecipeParserRunner(extractor_dir="extractor")
    
    # Выбираем случайные уникальные модули
    if modules is None:
        random_modules = set()
        while len(random_modules) < len(ports):
            random_extractor = parser.get_random_extractor()
            if random_extractor is None:
                logger.error("Нет доступных экстракторов для выбора")
                return
            random_modules.add(random_extractor)
        
        random_modules = list(random_modules)
        modules = random_modules
    
    # Логируем план
    logger.info("\nПлан запуска:")
    for i, (port, module) in enumerate(zip(ports, modules), 1):
        logger.info(f"  [{i}] {module} → port {port} → logs/{module}_{port}.log")
    
    logger.info(f"\n{'='*60}\n")
    
    # Запускаем в потоках
    max_workers = max_workers or len(ports)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Создаем futures
        futures = {
            executor.submit(
                run_parser_thread, 
                module, 
                port, 
                max_urls=5000, 
                max_depth=4
            ): (module, port)
            for port, module in zip(ports, modules)
        }
        
        # Ждем завершения
        for future in as_completed(futures):
            module, port = futures[future]
            try:
                future.result()
                logger.info(f"✓ Поток {module}:{port} завершен")
            except Exception as e:
                logger.error(f"✗ Ошибка в потоке {module}:{port}: {e}")
    
    logger.info(f"\n{'='*60}")
    logger.info("ВСЕ ПАРСЕРЫ ЗАВЕРШЕНЫ")
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
        default=[9222, 9223],
        help='Список портов для параллельного запуска (по умолчанию: 9222 9223 9224)'
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=None,
        help='Максимальное количество параллельных потоков'
    )

    parser.add_argument(
        '--modules',
        type=str,
        default=["web_coolinarika_com", "domacirecepti_net", "24kitchen_nl", "simplyrecipes_com", "speedinfo_com_ua"],
        help='Имя модуля экстрактора для одиночного запуска (по умолчанию: 24kitchen_nl)'
    )
    
    args = parser.parse_args()
    
    if args.parallel:
        run_parallel(ports=args.ports, max_workers=args.workers)
    else:
        main(args.modules[0], args.ports[0])