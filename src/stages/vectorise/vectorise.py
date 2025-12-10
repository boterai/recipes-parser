
"""
Модуль для векторизации рецептов с использованием векторных БД.
"""

from typing import Any, Optional
from pathlib import Path
import sys
import logging
import sqlalchemy

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.models.page import Page
from src.common.db.qdrant import QdrantRecipeManager
from src.common.db.mysql import MySQlManager

logger = logging.getLogger(__name__)

NO_EMBEDDING_ERROR = "Embedding function не установлена. Используйте set_embedding_function()"

class RecipeVectorizer:
    """Векторизатор рецептов на основе векторной БД"""
    
    def __init__(self, vector_db: QdrantRecipeManager = None, page_database: MySQlManager = None):
        """
        Инициализация векторизатора
        
        Args:
            vector_db: Реализация векторной БД (по умолчанию QdrantManager)
            embedding_dim: Размерность векторов эмбеддингов
        """
        if vector_db is None:
            self.vector_db = QdrantRecipeManager()
        else:
            self.vector_db = vector_db

        if page_database is None:
            self.page_database = MySQlManager()
        else:
            self.page_database = page_database
        self.connected = False
                
    def connect(self) -> bool:
        if self.connected:
            return True
        """Подключение к векторной БД и БД страниц"""
        if self.vector_db.connect() is False:
            logger.error("Не удалось подключиться к векторной БД")
            return False
        
        if self.page_database.connect() is False:
            logger.error("Не удалось подключиться к базе данных страниц")
            return False
        self.connected = True
        return True
    
    def get_pages(self, site_id: int = None, limit: int = None, ids: list[str] = None) -> list[Page]:
        """Получение страниц с рецептами для сайта из БД страниц"""
        sql_dict = {}
        sql = "SELECT * FROM pages WHERE is_recipe = TRUE AND dish_name IS NOT NULL AND ingredient IS NOT NULL and step_by_step IS NOT NULL"
        if site_id is not None:
            sql += " AND site_id = :site_id"
            sql_dict["site_id"] = site_id

        if ids is not None and len(ids) > 0:
            sql += " AND id IN :ids"
            sql_dict["ids"] = tuple(ids)

        if limit is not None:
            sql += " LIMIT :limit"
            sql_dict["limit"] = limit

        pages = []
        with self.page_database.get_session() as session:
            result = session.execute(sqlalchemy.text(sql), sql_dict)
            rows = result.fetchall()
            pages = [Page.model_validate(dict(row._mapping)) for row in rows]
        
        return pages
    
    def close(self):
        """Закрытие подключений к БД"""
        if self.connected:
            self.vector_db.close()
            self.page_database.close()
            self.connected = False
        logger.info("Подключения к БД закрыты")
        
    
    
    