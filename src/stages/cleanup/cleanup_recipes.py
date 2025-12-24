"""
Утилиты для очистки БД от страниц без рецептов в таблице pages
"""

import sys
from pathlib import Path
import logging

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.common.db.clickhouse import ClickHouseManager
from src.common.db.qdrant import QdrantRecipeManager
from src.repositories.page import PageRepository
from src.models.page import PageORM
from sqlalchemy import text

logger = logging.getLogger(__name__)


class RecipeCleanup:
    """Класс для очистки БД от ненужных рецептов"""
    
    def __init__(self):
        self.page_repository = PageRepository()
    
    def remove_empty_recipes(self) -> int:
        """
        Удаление рецептов без ингредиентов или инструкций из таблицы pages
        
        Returns:
            Количество удаленных записей
        """
        
        session = self.page_repository.get_session()
        
        try:
            deleted = session.query(PageORM).filter(
                (PageORM.ingredients == None) | (text("JSON_LENGTH(ingredients) = 0")) |
                (PageORM.instructions == None) | (PageORM.instructions == "") | 
                (PageORM.dish_name == None) | (PageORM.dish_name == "")
            ).delete(synchronize_session=False)
            session.commit()
            logger.info(f"✓ Удалено {deleted} пустых рецептов из таблицы pages")
            return deleted
            
        finally:
            session.close()
    
    # можно добавить метод для орфанед векторов, но пока их по идее нет


def main():
    cleanup = RecipeCleanup()
    cleanup.remove_empty_recipes()


if __name__ == '__main__':
    main()