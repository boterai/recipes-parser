
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
from src.common.embedding import EmbeddingFunction
from src.repositories.page import PageRepository

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

    def add_all_recipes(
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
                batch = self.vector_db.add_recipes(pages=recipes, embedding_function=embedding_function, batch_size=batch_size,
                                              mark_vectorised_callback=self.olap_database.insert_recipes_batch)
                total_vectorised += batch
                total += len(recipes)
                logger.info(f"Векторизовано рецептов в этой партии: {batch}/{len(recipes)}")
            logger.info(f"Завершена векторизация партии для сайта {site_id}")

        logger.info(f"Всего векторизовано рецептов: {total_vectorised}/{total}")
        return total_vectorised

    def vectors_to_recipes(
            self, 
            initial_recipe_id: int,
            vector_results: list[dict[str, Any]]
        ) -> list[float, Recipe]:
        """
            Преобразование результатов поиска в векторной БД в объекты Page с оценкой схожести
        Args:
            vector_results: Результаты поиска в векторной БД
        Returns:
            Список кортежей (score, Recipe)"""

        # Создаем маппинг recipe_id -> score
        score_map = {res['recipe_id']: res['score'] for res in vector_results}
        
        recipe_with_scores: list[float, Page] = []
        recipes = self.olap_database.get_recipes_by_ids(list(score_map.keys()))
            
        # Возвращаем tuple (score, Page) для каждого рецепта
        for recipe in recipes:
            if recipe.page_id == initial_recipe_id:
                continue  # пропускаем исходный рецепт
            score = score_map.get(recipe.page_id, 0.0)
            recipe_with_scores.append((score, recipe))
        
        recipe_with_scores.sort(key=lambda x: x[0], reverse=True)
        
        return recipe_with_scores
    
    def get_similar_recipes_full(
            self, 
            recipe: Recipe, 
            embed_function: EmbeddingFunction, 
            limit: int = 6,
            score_threshold: float = 0.0,
        ) -> list[float, Recipe]:
        """
        get_similar_recipes_full  - Поиск похожих рецептов в векторной БД и возврат их как объекты Page + score схожести c изначальным вариантом
        Args:
            recipe: Рецепт для поиска похожих
            embed_function: Функция для получения эмбеддингов
            limit: Максимальное количество возвращаемых похожих рецептов
            score_threshold: Порог схожести для фильтрации результатов
        """
        query = recipe.get_full_recipe_str()
        query_recipe = embed_function(texts=[query], is_query=True)[0]
        
        results = self.vector_db.search_full(
            query_vector=query_recipe,
            limit=limit+1,  # +1 чтобы исключить сам рецепт из результатов
            score_threshold=score_threshold
        )
        
        if len(results) == 0:
            return []
        
        return self.vectors_to_recipes(recipe.page_id, results)
        
    
    def get_similar_recipes_weighted(
            self, 
            recipe: Recipe,
            embed_function: EmbeddingFunction, 
            limit: int = 6,
            score_threshold: float = 0.0,
            component_weights: Optional[ComponentWeights] = None
        ) -> list[float, Page]:
        """Поиск похожих рецептов в векторной БД с учетом типа контента и возврат их как объекты Page + score схожести c изначальным вариантом"""

        results = self.vector_db.search_multivector_weighted(
            recipe=recipe,
            embed_function=embed_function,
            limit=limit + 1,  # +1 чтобы исключить сам рецепт из результатов
            score_threshold=score_threshold,
            component_weights=component_weights
        )
        
        if len(results) == 0:
            return []
        
        return self.vectors_to_recipes(recipe.page_id, results)