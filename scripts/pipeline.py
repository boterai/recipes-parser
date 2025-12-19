import sys
import logging
from pathlib import Path
import argparse

# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.stages.parse import explore_site
from src.stages.parse.auto_scraper import AutoScraper
from multiprocessing import Process

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

    
MAX_PREPAREPAGES = 100	
BATCH_SIZE = 30

def pipeline(debug_port: int = 9222, url: str = "", max_depth: int = 4, max_urls: int = 10000, check_url: bool = True, helper_links: list[str] = None):
	explore_site(url, max_urls=max_urls, max_depth=max_depth, check_pages_with_extractor=True, check_url=check_url, debug_port=debug_port, helper_links=helper_links)


SITES_CONFIG = [
	{	'id': 1,
        'name': 'allrecipes_com',
        'url': 'https://www.allrecipes.com/',
        'debug_port': 9222,
    },
	{
		'id': 2,
        'name': 'nefisyemektarifleri_com',
        'url': 'https://www.nefisyemektarifleri.com/',
        'debug_port': 9223,
    },
    {
		'id': 3,
        'name': 'recipe_sgethai_com',
        'url': 'https://recipe.sgethai.com/',
        'debug_port': 9224,
    },
    {
		'id': 4,
        'name': 'chefkoch_de',
        'url': 'https://www.chefkoch.de/',
        'debug_port': 9225,
    },
    {
		'id': 5,
        'name': 'kitchen_sayidaty_net',
        'url': 'https://kitchen.sayidaty.net/',
        'debug_port': 9226,
    },
    {
		'id': 6,
        'name': 'kikkoman_co_jp',
        'url': 'https://www.kikkoman.co.jp/',
        'debug_port': 9227,
    },
	{
		'id': 7,
        'name': 'povarenok_ru',
		'url': 'https://www.povarenok.ru/',
		'debug_port': 9228,
	},
	{
		'id': 8,
        'name': 'gastronom_ru',
		'url': 'https://www.gastronom.ru/',
		'debug_port': 9229,
	}
]


def run_config(config: dict):
	"""Запуск парсинга для одной конфигурации"""
	logger.info(f"Запуск конфигурации #{config['id']}: {config['url']}")
	pipeline(
		debug_port=config['debug_port'],
		url=config['url'],
		max_depth=5,
		max_urls=10000,
		check_url=True,
		helper_links=config.get('helper_links', [])
	)


def run_parallel():
	"""Запуск всех конфигураций параллельно"""
	processes = []
	
	for config in SITES_CONFIG:
		p = Process(target=run_config, args=(config,))
		p.start()
		processes.append(p)
		logger.info(f"Запущен процесс для конфигурации #{config['id']}: {config['url']} (PID: {p.pid})")
	
	# Ждем завершения всех процессов
	for p in processes:
		p.join()
	
	logger.info("Все процессы завершены")


def run_extractor_sites():
	"""Запуск скрапинга для сайтов с экстракторами"""
	logger.info("Запуск автоматического скрапинга для сайтов с экстракторами...")
	scraper = AutoScraper(debug_mode=True)
	
	try:
		scraper.run_recipe_site_scrapping(SITES_CONFIG)
	except KeyboardInterrupt:
		logger.info("\nПрервано пользователем")
	except Exception as e:
		logger.error(f"Ошибка при скрапинге: {e}")
		import traceback
		traceback.print_exc()
	finally:
		scraper.close()


def main():
	parser = argparse.ArgumentParser(description='Recipe parser pipeline')
	parser.add_argument('--config', type=int, help='Номер конфигурации для запуска (1-8)')
	parser.add_argument('--parallel', action='store_true', help='Запустить все конфигурации параллельно')
	parser.add_argument('--extractors', action='store_true', help='Запустить скрапинг для сайтов с экстракторами')
	
	args = parser.parse_args()
	
	if args.extractors:
		logger.info("Режим: Скрапинг сайтов с экстракторами")
		run_extractor_sites()
	elif args.parallel:
		logger.info("Запуск всех конфигураций параллельно...")
		run_parallel()
	elif args.config:
		# Поиск конфигурации по ID
		config = next((c for c in SITES_CONFIG if c['id'] == args.config), None)
		if config:
			run_config(config)
		else:
			sys.exit(1)
	else:
		# По умолчанию запускаем первую конфигурацию
		logger.info("Не указан параметр --config или --parallel, запуск конфигурации #1 по умолчанию")
		run_config(SITES_CONFIG[0])

			
if __name__ == "__main__":
	main()