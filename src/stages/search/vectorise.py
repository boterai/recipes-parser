
"""
Модуль для векторизации рецептов с использованием векторных БД.
"""

from typing import Any, Optional
from pathlib import Path
import sys
import logging

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.models.page import Page
from src.models.page import Recipe
from src.models.search_config import ComponentWeights
from src.common.db.qdrant import QdrantRecipeManager
from src.common.db.clickhouse import ClickHouseManager
from src.common.embedding import EmbeddingFunction, ImageEmbeddingFunction
from src.repositories.page import PageRepository
from src.repositories.image import ImageRepository
from src.models.image import Image


logger = logging.getLogger(__name__)

NO_EMBEDDING_ERROR = "Embedding function не установлена. Используйте set_embedding_function()"

class RecipeVectorizer:
    """Векторизатор рецептов на основе векторной БД"""
    
    def __init__(self, vector_db: QdrantRecipeManager = None, olap_database: ClickHouseManager = None):
        """
        Инициализация векторизатора
        
        Args:
            vector_db: Реализация векторной БД (по умолчанию QdrantManager)
            olap_database: OLAP база данных (по умолчанию ClickHouseManager)
            db: Транзакционная база данных (по умолчанию MySQlManager)
        """
        self._vector_db = vector_db
        self._olap_database = olap_database
        self.page_repository = PageRepository()
        self.image_repository = ImageRepository()
    
    @property
    def vector_db(self) -> QdrantRecipeManager:
        """Ленивое подключение к векторной БД"""
        if self._vector_db is None:
            self._vector_db = QdrantRecipeManager()
            if not self._vector_db.connect():
                raise ConnectionError("Не удалось подключиться к векторной БД")
        return self._vector_db
    
    @property
    def olap_database(self) -> ClickHouseManager:
        """Ленивое подключение к ClickHouse"""
        if self._olap_database is None:
            self._olap_database = ClickHouseManager()
            if not self._olap_database.connect():
                raise ConnectionError("Не удалось подключиться к ClickHouse")
        return self._olap_database

    def close(self):
        """Закрытие подключений к БД"""
        if self._vector_db is not None:
            self._vector_db.close()
        if self._olap_database is not None:
            self._olap_database.close()

    def vectorise_all_recipes(
            self, 
            embedding_function: EmbeddingFunction, 
            batch_size: int = 8,
            site_id: Optional[int] = None,
            dims: int = 1024,
            vectorised: bool = False 
        ) -> int:
        """
        Добавление всех рецептов в векторную БД для конкретного сайта или вообще всех сайтов

        Args:
            embedding_function: Функция для получения эмбеддингов
            batch_size: Размер партии для векторизации
            site_id: Идентификатор сайта для векторизации (если None, то для всех сайтов)
            dims: Размерность плотных векторов
            colbert_dims: Размерность разреженных векторов ColBERT
            vectorised: Флаг, указывающий, векторизованы ли уже рецепты
        """

        sites = []
        if site_id is not None:
            sites = [site_id]
        else:
            sites = self.page_repository.get_recipe_sites()
        
        if not sites:
            logger.warning("Нет сайтов для векторизации")
            return 0

        self.vector_db.create_collections(dims=dims)
        total = 0
        total_vectorised = 0
        for site_id in sites:
            logger.info(f"Начинаем векторизацию рецептов для сайта {site_id}")
            while (recipes := self.olap_database.get_recipes_by_site(site_id=site_id, vectorised=vectorised, limit=batch_size)):
                if len(recipes) == 0:
                    logger.info(f"Все рецепты для сайта {site_id} уже векторизованы или отсутствуют")
                    break
                print(f"Векторизуем партию из {len(recipes)} страниц, сайт {site_id}")
                batch = self.vector_db.vectorise_recipes(pages=recipes, embedding_function=embedding_function, batch_size=batch_size,
                                              mark_vectorised_callback=self.olap_database.insert_recipes_batch)
                total_vectorised += batch
                total += len(recipes)
                logger.info(f"Векторизовано рецептов в этой партии: {batch}/{len(recipes)}")
            logger.info(f"Завершена векторизация партии для сайта {site_id}")

        logger.info(f"Всего векторизовано рецептов: {total_vectorised}/{total}")
        return total_vectorised
    
    async def vectorise_images_async(
            self, 
            embed_function: ImageEmbeddingFunction, 
            limit: Optional[int]  = None, 
            image_retrieve_limit: int = 1000,
            batch_size: int = 8
            ):
        """
        Векторизация изображений рецептов
        
        Args:
            image_paths: Список путей к изображениям
            embed_function: Функция для получения эмбеддингов
            
        Returns:
            Список векторов для каждого изображения
        """
        total = limit
        if limit is None:
            total = self.image_repository.get_not_vectorised_count()
        processed = 0
        last_page_id = None
        while processed < total:
            images = self.image_repository.get_not_vectorised(limit=image_retrieve_limit, last_page_id=last_page_id)
            if not images:
                logger.info("Нет невекторизованных изображений для обработки")
                return
            
            processed += await self.vector_db.vectorise_images_async(
                images=images,
                embedding_function=embed_function,
                batch_size=batch_size,
                mark_vectorised_callback=self.image_repository.mark_as_vectorised
            )
            logger.info(f"Всего векторизовано изображений: {processed}/{total}")
            last_page_id = images[-1].page_id #чтобы не повторяться