import sys
import logging
from pathlib import Path

# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.stages.translate import Translator
from src.common.db.clickhouse import ClickHouseManager

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)



def main():
    translator = Translator(target_language="en")
    translator.translate_and_save_batch(
        site_id=30,
        batch_size=10, # большой батч только, если целевой язык совпадает с исходным
    )

if __name__ == "__main__":
    main()
