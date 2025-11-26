

import sys
import logging
from pathlib import Path

# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.stages.parse import SiteExplorer
from src.stages.analyse import RecipeAnalyzer

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
    
MAX_PAGES = 150	
BATCH_SIZE = 30
# Добавить сохранения состояния между запусками
def main():
	url = "https://www.recipetineats.com/"
	explorer = SiteExplorer(url, debug_mode=True, use_db=True)
	
	# предварительный запуск для просмотра сайта и получения хоть каких-то ссылок 
	run_explorer(explorer, max_urls=BATCH_SIZE, max_depth=3)
	# Экспорт состояния после первого batch
	state = explorer.export_state()
     
	analyzer = RecipeAnalyzer()
	try:
		# анализ данных Stage 1 и получение паттерна страниц с рецептами
		recipes = analyzer.analyze_all_pages(site_id=explorer.site_id, filter_by_title=True)
		if recipes > 1 and (explorer.recipe_pattern is None and explorer.recipe_regex is None): # можно исктаь паттерн соовтетсвия 
			pattern = analyzer.analyse_recipe_page_pattern(site_id=explorer.site_id)
			if pattern:
				logger.info(f"Использование паттерна для исследования: {pattern}")
				explorer = SiteExplorer(url, debug_mode=True, use_db=True, recipe_pattern=pattern)
				explorer.import_state(state)  # Продолжаем с того же места

	except KeyboardInterrupt:
		logger.info("\nПрервано пользователем")
	except Exception as e:
		logger.error(f"Ошибка: {e}", exc_info=True)
		sys.exit(1)
	
	for batch in range(0, MAX_PAGES, BATCH_SIZE):

		logger.info(f"\n=== Запуск основного исследования, страницы {batch+1} - {batch+BATCH_SIZE} ===")
		run_explorer(explorer, max_urls=BATCH_SIZE, max_depth=3)
		
		# Экспортируем текущее состояние перед анализом
		state = explorer.export_state()
		
		results = analyzer.analyze_all_pages(site_id=explorer.site_id, filter_by_title=True)
		
		if results == 0 and pattern:
			logger.info("Сбрасываем паттерн возможно он не подходит")
			explorer = SiteExplorer(url, debug_mode=True, use_db=True)
			explorer.import_state(state)  # Восстанавливаем состояние
			pattern = ""
		
		if results > 0 and not pattern:
			pattern = analyzer.analyse_recipe_page_pattern(site_id=explorer.site_id)
			if pattern:
				logger.info(f"Найден паттерн страниц с рецептами: {pattern}")
				explorer = SiteExplorer(url, debug_mode=True, use_db=True, recipe_pattern=pattern)
				explorer.import_state(state)  # Продолжаем с сохраненного состояния

	# очищаем не нужные данные
	#analyzer.cleanup_non_recipe_pages(site_id=explorer.site_id)

			
if __name__ == "__main__":
	main()