
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
from src.common.embedding import EmbeddingFunction, prepare_text

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
    
    def get_all_site_ids(self) -> list[int]:
        """Получение всех ID сайтов, для которых есть рецепты в БД страниц"""
        site_ids = []
        with self.page_database.get_session() as session:
            sql = "SELECT DISTINCT site_id FROM sites WHERE is_recipe = TRUE"
            result = session.execute(sqlalchemy.text(sql))
            rows = result.fetchall()
            site_ids = [row[0] for row in rows]
        return site_ids
    
    def close(self):
        """Закрытие подключений к БД"""
        if self.connected:
            self.vector_db.close()
            self.page_database.close()
            self.connected = False
        logger.info("Подключения к БД закрыты")

    def add_all_recipes(
            self, 
            embedding_function: EmbeddingFunction, 
            batch_size: int = 8,
            site_id: Optional[int] = None,
            dims: int = 1024,
            colbert_dims: int = 1024
        ) -> int:
        """Добавление всех рецептов в векторную БД для конкретного сайта или вообще всех сайтов"""

        self.vector_db.create_collections(colbert_dim=colbert_dims, dense_dim=dims)
        if site_id is not None:
            pages = self.get_pages(site_id=site_id)
            if len(pages) == 0:
                print(f"Нет страниц для векторизации для сайта {site_id}, пропускаем")
                return 0
            print(f"Векторизуем партию из {len(pages)} страниц, сайт {site_id}")
            return self.vector_db.add_recipes(pages=pages, embedding_function=embedding_function, batch_size=batch_size)

        sites = self.get_all_site_ids()
        total_added = 0
        for site in sites:
            pages = self.get_pages(site_id=site)
            if len(pages) == 0:
                print(f"Нет страниц для векторизации для сайта {site}, пропускаем")
                continue

            addedd = self.vector_db.add_recipes(pages=pages, embedding_function=embedding_function, batch_size=batch_size)
            print(f"Всего добавлено для сайта {site}: {addedd}/{len(pages)}")
            total_added += addedd
        
        return total_added

    def get_similar_recipes(
            self, 
            page: Page, 
            embed_function: EmbeddingFunction, 
            content_type: str = "full", 
            limit: int = 6,
            score_threshold: float = 0.0,
        ) -> list[dict[str, Any]]:
        """Поиск похожих рецептов в векторной БД"""

        query_text = prepare_text(page, content_type=content_type)
        return self.vector_db.search(
            query_text=query_text,
            embedding_function=embed_function,
            limit=limit,
            content_type=content_type,
            score_threshold=score_threshold
        )
    
    def get_similar_recipes_as_pages(
            self, 
            page: Page, 
            embed_function: EmbeddingFunction, 
            content_type: str = "full", 
            limit: int = 6,
            score_threshold: float = 0.0,
        ) -> list[float, Page]:
        """Поиск похожих рецептов в векторной БД и возврат их как объекты Page + score схожести c изначальным вариантом"""

        results = self.get_similar_recipes(
            page=page,
            embed_function=embed_function,
            content_type=content_type,
            limit=limit,
            score_threshold=score_threshold
        )
        
        if len(results) == 0:
            return []
        
        # Создаем маппинг page_id -> score
        score_map = {res['page_id']: res['score'] for res in results}
        
        pages_with_scores: list[float, Page] = []
        with self.page_database.get_session() as session:
            sql = "SELECT * FROM pages WHERE id IN :ids"
            result = session.execute(sqlalchemy.text(sql), {"ids": tuple(score_map.keys())})
            rows = result.fetchall()
            
            # Возвращаем tuple (score, Page) для каждой страницы
            for row in rows:
                page_obj = Page.model_validate(dict(row._mapping))
                score = score_map.get(page_obj.id, 0.0)
                pages_with_scores.append((score, page_obj))
        
        pages_with_scores.sort(key=lambda x: x[0], reverse=True)
        
        return pages_with_scores
        
    
    
    