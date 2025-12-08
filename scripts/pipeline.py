

import sys
import logging
from pathlib import Path

# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.stages.parse import SiteExplorer
from src.stages.analyse import RecipeAnalyzer
from src.stages.parse import explore_site
from scripts.make_test_data import make_test_data

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
	#explorer.add_helper_urls(["https://www.ricardocuisine.com/recettes/10151-orge-au-canard-confit-et-oignons-rotis",
	#					   "https://www.ricardocuisine.com/recettes/plats-principaux/canard"], depth=2)
	# предварительный запуск для просмотра сайта и получения хоть каких-то ссылок 
	run_explorer(explorer, max_urls=BATCH_SIZE, max_depth=max_depth)
	# Экспорт состояния после первого batch
	state = explorer.export_state()
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
	#make_test_data(20) # создать тестовые данные для анализа и создания парсера (создается в папке recipes/)
	# после создания парсера можно запустить полноценный парсинг
	explore_site(url, max_urls=max_urls, max_depth=max_depth, check_pages_with_extractor=True, check_url=check_url, debug_port=debug_port)
	
def main():
	pipeline(
		debug_port=9225,
		#url="https://www.cucchiaio.it/ricette/",
		#url="https://recipe.sgethai.com/",
		url="https://www.gastronom.ru/group",
		max_depth=5,
		max_urls=5000,
		check_url=True)

			
if __name__ == "__main__":
	main()