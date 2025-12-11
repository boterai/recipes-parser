

import sys
import logging
from pathlib import Path
import argparse

# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.stages.parse import SiteExplorer
from src.stages.analyse import RecipeAnalyzer
from src.stages.parse import explore_site
from scripts.make_test_data import make_test_data
from multiprocessing import Process

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

def run_explorer(explorer:SiteExplorer, max_urls: int, max_depth: int):
    
    try:
        explorer.connect_to_chrome()
        explorer.explore(max_urls=max_urls, max_depth=max_depth)
    except KeyboardInterrupt:
        logger.info("\nПрервано пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
    finally:
        explorer.close()
    
MAX_PREPAREPAGES = 100	
BATCH_SIZE = 30
SITE_ID = None
# Добавить сохранения состояния между запусками
def prepare_data_for_parser_creation(url: str, max_depth: int, debug_port: int = 9222):
	global SITE_ID
	explorer = SiteExplorer(url, debug_mode=True, debug_port=debug_port, max_urls_per_pattern=3)
	#explorer.add_helper_urls(["https://kitchen.sayidaty.net/node/36893/%D8%B1%D8%A7%D9%81%D9%8A%D9%88%D9%84%D9%8A-%D8%A8%D8%A7%D9%84%D8%B5%D9%8A%D9%86%D9%8A%D8%A9-%D8%A8%D8%A7%D9%84%D9%81%D9%8A%D8%AF%D9%8A%D9%88/%D9%88%D8%B5%D9%81%D8%A7%D8%AA-%D8%B7%D8%A8%D8%AE/%D9%88%D8%B5%D9%81%D8%A7%D8%AA-%D8%A7%D9%84%D9%81%D9%8A%D8%AF%D9%8A%D9%88",
	#					   "https://kitchen.sayidaty.net/node/37135/%D9%85%D9%83%D8%B1%D9%88%D9%86%D8%A9-%D8%A7%D9%84%D9%81%D9%88%D8%AA%D8%B4%D9%8A%D9%86%D9%8A-%D8%A8%D8%A7%D9%84%D8%AF%D8%AC%D8%A7%D8%AC/%D9%88%D8%B5%D9%81%D8%A7%D8%AA-%D8%B7%D8%A8%D8%AE/%D9%88%D8%B5%D9%81%D8%A7%D8%AA"], depth=2)
	# предварительный запуск для просмотра сайта и получения хоть каких-то ссылок 
	#run_explorer(explorer, max_urls=BATCH_SIZE, max_depth=max_depth)
	# Экспорт состояния после первого batch
	#state = explorer.export_state()
	SITE_ID = explorer.site_id
	analyzer = RecipeAnalyzer()
	try:
		# анализ данных Stage 1 и получение паттерна страниц с рецептами
		recipes = analyzer.analyze_all_pages(site_id=explorer.site_id, filter_by_title=True, stop_analyse=3)
		if recipes > 1 and (explorer.recipe_pattern is None and explorer.recipe_regex is None): # можно исктаь паттерн соответствия 
			pattern = analyzer.analyse_recipe_page_pattern(site_id=explorer.site_id)
			if pattern: 
				explorer.set_pattern(pattern) # обновление паттерна в эксеплорере
				logger.info(f"Найден паттерн страниц с рецептами: {pattern}")
				return # если паттерн найден, завершаем работу, пробуем создать полноценный парсер из полученных данных

	except KeyboardInterrupt:
		logger.info("\nПрервано пользователем")
	except Exception as e:
		logger.error(f"Ошибка: {e}", exc_info=True)
		sys.exit(1)
	
	for batch in range(0, MAX_PREPAREPAGES, BATCH_SIZE):

		logger.info(f"\n=== Запуск основного исследования, страницы {batch+1} - {batch+BATCH_SIZE} ===")
		run_explorer(explorer, max_urls=BATCH_SIZE, max_depth=max_depth)
		
		# Экспортируем текущее состояние перед анализом
		state = explorer.export_state()
		
		results = analyzer.analyze_all_pages(site_id=explorer.site_id, filter_by_title=True)
		
		if results == 0 and pattern:
			logger.info("Сбрасываем паттерн возможно он не подходит")
			explorer = SiteExplorer(url, debug_mode=True, debug_port=debug_port, max_urls_per_pattern=3)
			explorer.import_state(state)  # Восстанавливаем состояние
			pattern = ""
		
		if results > 0 and not explorer.recipe_pattern:
			pattern = analyzer.analyse_recipe_page_pattern(site_id=explorer.site_id)
			if pattern:
				explorer.set_pattern(pattern) # обновление паттерна в эксеплорере
				logger.info(f"Найден паттерн страниц с рецептами: {pattern}")
				return # если паттерн найден, завершаем работу, пробуем создать полноценный парсер из полученных данных

def pipeline(debug_port: int = 9222, url: str = "", max_depth: int = 4, max_urls: int = 10000, check_url: bool = True):
	#prepare_data_for_parser_creation(url=url, max_depth=max_depth, debug_port=debug_port)
	#make_test_data(8) # создать тестовые данные для анализа и создания парсера (создается в папке recipes/)
	# после создания парсера можно запустить полноценный парсинг
	explore_site(url, max_urls=max_urls, max_depth=max_depth, check_pages_with_extractor=True, check_url=check_url, debug_port=debug_port)


SITES_CONFIG = [
	{	'id': 1,
        'url': 'https://www.allrecipes.com/',
        'debug_port': 9222,
    },
	{
		'id': 2,
        'url': 'https://www.nefisyemektarifleri.com/',
        'debug_port': 9223,
    },
    {
		'id': 3,
        'url': 'https://recipe.sgethai.com/',
        'debug_port': 9224,
    },
    {
		'id': 4,
        'url': 'https://www.chefkoch.de/',
        'debug_port': 9225,
    },
    {
		'id': 5,
        'url': 'https://kitchen.sayidaty.net/',
        'debug_port': 9226,
    },
    {
		'id': 6,
        'url': 'https://www.kikkoman.co.jp/',
        'debug_port': 9227,
    },
	{
		'id': 7,
		'url': 'https://www.povarenok.ru/',
		'debug_port': 9228,
	},
	{
		'id': 8,
		'url': 'https://www.gastronom.ru/',
		'debug_port': 9229,
	}
]


def run_config(config):
	"""Запуск парсинга для одной конфигурации"""
	logger.info(f"Запуск конфигурации #{config['id']}: {config['url']}")
	pipeline(
		debug_port=config['debug_port'],
		url=config['url'],
		max_depth=5,
		max_urls=10000,
		check_url=True
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


def main():
	parser = argparse.ArgumentParser(description='Recipe parser pipeline')
	parser.add_argument('--config', type=int, help='Номер конфигурации для запуска (1-6)')
	parser.add_argument('--parallel', action='store_true', help='Запустить все конфигурации параллельно')
	
	args = parser.parse_args()
	
	if args.parallel:
		logger.info("Запуск всех конфигураций параллельно...")
		run_parallel()
	elif args.config:
		# Поиск конфигурации по ID
		config = next((c for c in SITES_CONFIG if c['id'] == args.config), None)
		if config:
			run_config(config)
		else:
			logger.error(f"Конфигурация с ID {args.config} не найдена. Доступны: {[c['id'] for c in SITES_CONFIG]}")
			sys.exit(1)
	else:
		# По умолчанию запускаем первую конфигурацию
		logger.info("Не указан параметр --config или --parallel, запуск конфигурации #1 по умолчанию")
		run_config(SITES_CONFIG[0])

			
if __name__ == "__main__":
	main()