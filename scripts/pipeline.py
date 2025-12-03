

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

def run_explorer(explorer:SiteExplorer, max_urls: int, max_depth: int, forbid_success_mark: bool = False):
    
    try:
        explorer.connect_to_chrome()
        explorer.explore(max_urls=max_urls, max_depth=max_depth, forbid_success_mark=forbid_success_mark)
    except KeyboardInterrupt:
        logger.info("\nПрервано пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
    finally:
        explorer.close()
    
MAX_PAGES = 100	
BATCH_SIZE = 30
# Добавить сохранения состояния между запусками
def main():
	# https://www.food.com
	#url3 = "https://www.marmiton.org/"
	#url2 = "https://food-guide.canada.ca"
	url = "https://www.recetasgratis.net/"
	max_depth = 5
	explorer = SiteExplorer(url, debug_mode=True, use_db=True)
	#explorer.add_helper_urls(["https://www.goodnes.com/es/recetas/"], depth=2)
	# предварительный запуск для просмотра сайта и получения хоть каких-то ссылок 
	#run_explorer(explorer, max_urls=BATCH_SIZE, max_depth=max_depth, forbid_success_mark=True)
	# Экспорт состояния после первого batch
	#state = explorer.export_state()
     
	analyzer = RecipeAnalyzer()
	pattern = analyzer.analyse_recipe_page_pattern(site_id=explorer.site_id)
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
	
	for batch in range(0, MAX_PAGES, BATCH_SIZE):

		logger.info(f"\n=== Запуск основного исследования, страницы {batch+1} - {batch+BATCH_SIZE} ===")
		run_explorer(explorer, max_urls=BATCH_SIZE, max_depth=max_depth)
		
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
				explorer.set_pattern(pattern) # обновление паттерна в эксеплорере

	# очищаем не нужные данные
	#analyzer.cleanup_non_recipe_pages(site_id=explorer.site_id)

			
if __name__ == "__main__":
	main()