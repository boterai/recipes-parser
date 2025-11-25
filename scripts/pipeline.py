

import sys
import logging
from pathlib import Path

# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.stage1_exploration import SiteExplorer
from src.stage2_analyse.analyse import RecipeAnalyzer

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
        

def main():
	url = "https://pinchofyum.com/"
	explorer = SiteExplorer(url, debug_mode=True, use_db=True)
	
	# предварительный запуск для просмотра сайта и получения хоть каких-то ссылок 
	run_explorer(explorer, max_urls=30, max_depth=3)
     
	analyzer = RecipeAnalyzer()
	pattern = ""
	try:
		# анализ данных Stage 1 и получение паттерна страниц с рецептами, если не получится создать паттерн или он будет не удачный, 
		# то снова будем парсить все подряд и попробуем еще. (Сейчас тестово 1 попытка на поиск паттерна, может его и не надо использвоать)
		analyzer.analyze_all_pages(site_id=explorer.site_id, filter_by_title=True)
		pattern = analyzer.analyse_recipe_page_pattern(site_id=explorer.site_id)
		if pattern:
			logger.info(f"Найден паттерн страниц с рецептами: {pattern}")
			analyzer.delete_unused_data(explorer.site_id)
	except KeyboardInterrupt:
		logger.info("\nПрервано пользователем")
	except Exception as e:
		logger.error(f"Ошибка: {e}", exc_info=True)
		sys.exit(1)
	finally:
		analyzer.close()

	if pattern:
		logger.info(f"Использование паттерна для исследования: {pattern}")
		explorer = SiteExplorer(url, debug_mode=True, use_db=True, recipe_pattern=pattern)
	# продолжить сбор всех подряд страниц с использованием паттерна или без (мб случай паттерн найден, но очень узкий и если ничего не найдется, то надо его отбарсывать)
	run_explorer(explorer, max_urls=200, max_depth=3)
	analyzer.analyze_all_pages(site_id=explorer.site_id, filter_by_title=True) # тут паттерны должнв 

if __name__ == "__main__":
	main()