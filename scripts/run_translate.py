import sys
import logging
from pathlib import Path

# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.stages.translate import Translator
from src.common.db.mysql import MySQlManager
from src.models.site import SiteORM

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)



def main():
    mysql = MySQlManager()
    if not mysql.connect():
        logger.error("Не удалось подключиться к базе данных")
        return
    
    session = mysql.get_session()
    exsisting = session.query(SiteORM).filter(SiteORM.id == 24).first()
    if not exsisting:
        logger.error("Сайт с ID=24 не найден в базе данных")
        return
    
    session.close()

    translator = Translator(target_language="en")
    translator.translate_and_save_batch(
        site_id=24,
        batch_size=10, # большой батч только, если целевой язык совпадает с исходным
    )

if __name__ == "__main__":
    main()
