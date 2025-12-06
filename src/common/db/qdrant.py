"""
Менеджер работы с Qdrant для векторного добавления и поиска рецептов
"""

import logging
from typing import Any, Optional

from src.common.embedding import prepare_text, EmbeddingFunction
from config.db_config import QdrantConfig
from src.models.page import Page
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue,
    MultiVectorConfig, MultiVectorComparator, Document, Prefetch, HnswConfigDiff
    )

logger = logging.getLogger(__name__)


class QdrantManager:
    """Менеджер для работы с Qdrant векторной БД"""
    
    # Названия коллекций
    MODEL_COLBERT_ML = "jinaai/jina-colbert-v2"
    COLLECTION_RECIPES = "recipes"
    COLLECTION_INGREDIENTS = "ingredients"
    COLLECTION_INSTRUCTIONS = "instructions"
    COLLECTION_DESCRIPTIONS = "descriptions"
    COLLECTION_COLBERT = "recipes_colbert"  # ColBERT мультивекторная коллекция
    
    def __init__(self, embedding_dim: int = 384):
        """
        Инициализация подключения к Qdrant
        
        Args:
            embedding_dim: Размерность векторов (по умолчанию 384 для all-MiniLM-L6-v2)
        """
        self.client = None
        self.embedding_dim = embedding_dim
        
    def connect(self) -> bool:
        """Установка подключения к Qdrant"""
        try:
            params = QdrantConfig.get_connection_params()
            
            # Создаем клиент
            self.client = QdrantClient(
                host=params.get('host', 'localhost'),
                port=params.get('port', '6333'),
                api_key=params.get('api_key')
            )
            
            # Проверка подключения
            collections = self.client.get_collections()
            
            logger.info(f"Успешное подключение к Qdrant, коллекций: {len(collections.collections)}")
            
            # Создание коллекций если их нет
            self.create_collections()
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка подключения к Qdrant: {e}")
            return False
    
    def create_collections(self):
        """Создание коллекций в Qdrant"""
        if not self.client:
            return
        
        try:
            collections_to_create = [
                (self.COLLECTION_RECIPES, "Основная коллекция рецептов"),
                (self.COLLECTION_INGREDIENTS, "Коллекция ингредиентов"),
                (self.COLLECTION_INSTRUCTIONS, "Коллекция инструкций"),
                (self.COLLECTION_DESCRIPTIONS, "Коллекция описаний")
            ]
            
            for collection_name, description in collections_to_create:
                # Проверяем существование коллекции
                try:
                    self.client.get_collection(collection_name)
                    logger.info(f"Коллекция {collection_name} уже существует")
                except Exception:
                    # Создаем коллекцию
                    self.client.create_collection(
                        collection_name=collection_name,
                        vectors_config=VectorParams(
                            size=self.embedding_dim,
                            distance=Distance.COSINE
                        )
                    )
                    logger.info(f"Создана коллекция {collection_name}: {description}")
            
            # Создаем ColBERT мультивекторную коллекцию https://qdrant.tech/documentation/advanced-tutorials/using-multivector-representations/
            try:
                self.client.get_collection(self.COLLECTION_COLBERT)
                logger.info(f"Коллекция {self.COLLECTION_COLBERT} уже существует")
            except Exception:
                self.client.create_collection(
                    collection_name=self.COLLECTION_COLBERT,
                    vectors_config={
                        "recipe": VectorParams(
                            size=self.embedding_dim,
                            distance=Distance.COSINE
                        ),
                        "colbert": VectorParams(
                            size=128,  # ColBERT использует 128-размерные векторы
                            distance=Distance.COSINE,
                            multivector_config=MultiVectorConfig(
                                comparator=MultiVectorComparator.MAX_SIM
                            ),
                            hnsw_config=HnswConfigDiff(m=0)
                        )
                    }
                )
                logger.info(f"Создана ColBERT мультивекторная коллекция {self.COLLECTION_COLBERT}")
            
        except Exception as e:
            logger.error(f"Ошибка создания коллекций Qdrant: {e}")
    
    def add_recipe(
        self,
        page: Page,
        embedding_function,
        collections: Optional[list[str]] = None
    ) -> bool:
        """
        Добавление рецепта в Qdrant
        
        Args:
            page: Объект страницы с рецептом
            embedding_function: Функция для создания эмбеддингов (принимает текст, возвращает вектор)
            collections: Список коллекций для добавления (по умолчанию все)
            
        Returns:
            True если успешно добавлено
        """
        if not self.client:
            logger.warning("Qdrant не подключен")
            return False
        
        if not page.is_recipe or not page.dish_name:
            logger.warning(f"Пропущен: не рецепт или нет названия (ID: {page.id})")
            return False
        
        try:
            # Определяем коллекции для добавления
            if collections is None:
                collections = [
                    self.COLLECTION_RECIPES,
                    self.COLLECTION_INGREDIENTS,
                    self.COLLECTION_INSTRUCTIONS,
                    self.COLLECTION_DESCRIPTIONS,
                    self.COLLECTION_COLBERT
                ]
            
            # Базовые метаданные
            payload = {
                "dish_name": page.dish_name,
                "site_id": page.site_id,
            }
            
            # Добавляем в каждую коллекцию
            for collection_name in collections:
                # Определяем тип коллекции
                if collection_name == self.COLLECTION_INGREDIENTS:
                    if not page.ingredient:
                        continue
                    text = prepare_text(page, "ingredients")
                    
                elif collection_name == self.COLLECTION_INSTRUCTIONS:
                    if not page.step_by_step:
                        continue
                    text = prepare_text(page, "instructions")
                    
                elif collection_name == self.COLLECTION_DESCRIPTIONS:
                    if not page.description:
                        continue
                    text = prepare_text(page, "descriptions")
                elif collection_name == self.COLLECTION_COLBERT:
                    # ColBERT мультивекторная коллекция
                    self.add_recipe_colbert(page, embedding_function=embedding_function)
                    continue
                    
                else:  # COLLECTION_RECIPES
                    text = prepare_text(page, "main")
                
                if not text:
                    continue
                
                # Создаем эмбеддинг
                vector = embedding_function(text)
                
                # Добавляем точку
                point = PointStruct(
                    id=page.id,
                    vector=vector,
                    payload=payload
                )
                
                self.client.upsert(
                    collection_name=collection_name,
                    points=[point]
                )
            


            logger.info(f"✓ Добавлен рецепт: {page.dish_name} (ID: {page.id})")
            return True
            
        except Exception as e:
            logger.error(f"✗ Ошибка добавления рецепта {page.id}: {e}")
            return False
    
    def add_recipes_batch(
        self,
        pages: list[Page],
        embedding_function: EmbeddingFunction,
        batch_size: int = 100
    ) -> int:
        """
        Массовое добавление рецептов
        
        Args:
            pages: Список объектов страниц
            embedding_function: Функция для создания эмбеддингов
            batch_size: Размер батча
            
        Returns:
            Количество успешно добавленных рецептов
        """
        if not self.client:
            logger.warning("Qdrant не подключен")
            return 0
        
        added_count = 0
        
        # Батчи для каждой коллекции
        batches = {
            self.COLLECTION_RECIPES: [],
            self.COLLECTION_INGREDIENTS: [],
            self.COLLECTION_INSTRUCTIONS: [],
            self.COLLECTION_DESCRIPTIONS: [],
            self.COLLECTION_COLBERT: []
        }
        
        for page in pages:
            if not page.is_recipe or not page.dish_name:
                continue
            
            try:
                payload = {
                    "dish_name": page.dish_name,
                    "site_id": page.site_id,
                }
                
                # Основная коллекция
                text_main = prepare_text(page, "main")
                if text_main:
                    vector = embedding_function(text_main)
                    batches[self.COLLECTION_RECIPES].append(
                        PointStruct(id=page.id, vector=vector, payload=payload)
                    )

                    batches[self.COLLECTION_COLBERT].append(
                        PointStruct(id=page.id, vector={
                            "recipe": vector,
                            "colbert": Document(text=text_main, model=self.MODEL_COLBERT_ML)
                        }, payload=payload)
                    )
                
                # Ингредиенты
                if page.ingredient:
                    text_ing = prepare_text(page, "ingredients")
                    if text_ing:
                        vector = embedding_function(text_ing)
                        batches[self.COLLECTION_INGREDIENTS].append(
                            PointStruct(id=page.id, vector=vector, payload=payload)
                        )
                
                # Инструкции
                if page.step_by_step:
                    text_inst = prepare_text(page, "instructions")
                    if text_inst:
                        vector = embedding_function(text_inst)
                        batches[self.COLLECTION_INSTRUCTIONS].append(
                            PointStruct(id=page.id, vector=vector, payload=payload)
                        )
                
                # Описания
                if page.description:
                    text_desc = prepare_text(page, "descriptions")
                    if text_desc:
                        vector = embedding_function(text_desc)
                        batches[self.COLLECTION_DESCRIPTIONS].append(
                            PointStruct(id=page.id, vector=vector, payload=payload)
                        )
                
                added_count += 1
                
                # Загружаем батчи если достигли размера
                if added_count % batch_size == 0:
                    self._upload_batches(batches)
                    batches = {k: [] for k in batches}
                    logger.info(f"Обработано {added_count} рецептов...")
                
            except Exception as e:
                logger.error(f"✗ Ошибка подготовки рецепта {page.id}: {e}")
                continue
        
        # Загружаем остатки
        if any(batches.values()):
            self._upload_batches(batches)
        
        logger.info(f"✓ Всего добавлено {added_count} рецептов")
        return added_count
    
    def _upload_batches(self, batches: dict[str, list[PointStruct]]):
        """Загрузка батчей в Qdrant"""
        for collection_name, points in batches.items():
            if not points:
                continue

            if collection_name == self.COLLECTION_COLBERT:
                # ColBERT мультивекторная коллекция
                try:
                    self.client.upload_points(
                        collection_name=collection_name,
                        points=points
                    )
                except Exception as e:
                    logger.error(f"Ошибка загрузки батча в {collection_name}: {e}")
                continue
            
            try:
                self.client.upsert(
                    collection_name=collection_name,
                    points=points
                )
            except Exception as e:
                logger.error(f"Ошибка загрузки батча в {collection_name}: {e}")
    
    def search(
        self,
        query_vector: list[float],
        collection_name: str = None,
        limit: int = 10,
        site_id: Optional[int] = None,
        score_threshold: float = 0.0
    ) -> list[dict[str, Any]]:
        """
        Поиск похожих рецептов
        
        Args:
            query_vector: Вектор запроса
            collection_name: Название коллекции (по умолчанию recipes)
            limit: Количество результатов
            site_id: Фильтр по сайту
            score_threshold: Минимальный порог схожести
            
        Returns:
            Список найденных рецептов
        """
        if not self.client:
            logger.warning("Qdrant не подключен")
            return []
        
        if collection_name == self.COLLECTION_COLBERT:
            logger.warning("Для ColBERT используйте search_colbert метод")
            return []
        
        if collection_name is None:
            collection_name = self.COLLECTION_RECIPES
        
        try:
            # Создаем фильтр если нужен
            search_filter = None
            if site_id is not None:
                search_filter = Filter(
                    must=[
                        FieldCondition(
                            key="site_id",
                            match=MatchValue(value=site_id)
                        )
                    ]
                )
            
            # Выполняем поиск
            results = self.client.query_points(
                collection_name=collection_name,
                query=query_vector,
                limit=limit,
                query_filter=search_filter,
                score_threshold=score_threshold
            )
            
            # Форматируем результаты
            return [
                {
                    "id": hit.id,
                    "score": hit.score,
                    "page_id": hit.id,
                    "dish_name": hit.payload.get("dish_name"),
                    "site_id": hit.payload.get("site_id"),
                    "collection": collection_name
                }
                for hit in results.points
            ]
            
        except Exception as e:
            logger.error(f"Ошибка поиска в Qdrant: {e}")
            return []
    
    def delete_by_page_id(self, page_id: int) -> bool:
        """
        Удаление всех векторов для страницы
        
        Args:
            page_id: ID страницы
            
        Returns:
            True если успешно удалено
        """
        if not self.client:
            logger.warning("Qdrant не подключен")
            return False
        
        try:
            collections = [
                self.COLLECTION_RECIPES,
                self.COLLECTION_INGREDIENTS,
                self.COLLECTION_INSTRUCTIONS,
                self.COLLECTION_DESCRIPTIONS
            ]
            
            for collection_name in collections:
                self.client.delete(
                    collection_name=collection_name,
                    points_selector=Filter(
                        must=[
                            FieldCondition(
                                key="page_id",
                                match=MatchValue(value=page_id)
                            )
                        ]
                    )
                )
            
            logger.info(f"✗ Удалены векторы для page_id={page_id}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка удаления векторов: {e}")
            return False
    
    def get_stats(self) -> dict[str, Any]:
        """
        Получение статистики по коллекциям
        
        Returns:
            Словарь со статистикой
        """
        if not self.client:
            logger.warning("Qdrant не подключен")
            return {}
        
        try:
            stats = {}
            
            collections = [
                self.COLLECTION_RECIPES,
                self.COLLECTION_INGREDIENTS,
                self.COLLECTION_INSTRUCTIONS,
                self.COLLECTION_DESCRIPTIONS
            ]
            
            for collection_name in collections:
                try:
                    info = self.client.get_collection(collection_name)
                    if info.points_count == 0:
                        continue
                    stats[collection_name] = {
                        "points_count": info.points_count,
                        "status": info.status
                    }
                except Exception as e:
                    logger.warning(f"Не удалось получить статистику для {collection_name}: {e}")
            
            return stats
            
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            return {}
    
    def add_recipe_colbert(self, page: Page, embedding_function: EmbeddingFunction) -> bool:
        """
        Добавление рецепта в ColBERT мультивекторную коллекцию
        
        Args:
            page: Объект страницы с рецептом
            
        Returns:
            True если успешно добавлено
        """
        if not page.is_recipe or not page.dish_name:
            logger.warning(f"Пропущен: не рецепт или нет названия (ID: {page.id})")
            return False
        
        try:
            # Подготовка текста рецепта
            text = prepare_text(page, "main")
            if not text:
                logger.warning(f"Пропущен: пустой текст (ID: {page.id})")
                return False
            
            dense_vector = embedding_function(text) # основной вектор
            colbert_vector = Document(text=text, model=self.MODEL_COLBERT_ML) # вспомогательный вектор для уточнения поиска

            # Payload
            payload = {
                "page_id": page.id,
                "dish_name": page.dish_name,
                "site_id": page.site_id,
                "url": page.url,
                "language": page.language or "unknown"
            }
            
            # Добавляем точку с мультивектором
            self.client.upsert(
                collection_name=self.COLLECTION_COLBERT,
                points=[
                    PointStruct(
                        id=page.id,
                        vector={"colbert": colbert_vector, "recipe": dense_vector},  # Список векторов
                        payload=payload
                    )
                ]
            )
            
            logger.info(f"✓ Добавлен ColBERT мультивектор для: {page.dish_name} (ID: {page.id})")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка добавления ColBERT мультивектора: {e}")
            return False
    
    def search_colbert(
        self,
        query_text: str,
        limit: int = 10,
        embedding_function: EmbeddingFunction = None, # для основного вектора 
        score_threshold: float = 0.0
    ) -> list[dict[str, Any]]:
        """
        Поиск в ColBERT мультивекторной коллекции
        
        Args:
            query_text: Текст запроса
            limit: Количество результатов
            embedding_function: Функция для создания основного эмбеддинга
            score_threshold: Минимальный порог схожести
            
        Returns:
            Список найденных рецептов
        """
        if not self.client:
            logger.warning("Qdrant не подключен")
            return []
        
        try:
            dense_query = embedding_function(query_text) if embedding_function else None
            colbert_query = Document(text=query_text, model=self.MODEL_COLBERT_ML)
            
            # Выполняем поиск с мультивектором
            # Qdrant автоматически применит MAX_SIM для сравнения
            results = self.client.query_points(
                collection_name=self.COLLECTION_COLBERT,
                prefetch=Prefetch(
                    query=dense_query,
                    using="recipe"
                ),
                query=colbert_query,
                using="colbert",
                limit=limit,
                with_payload=True,
                score_threshold=score_threshold
            )
            
            # Форматируем результаты
            return [
                {
                    "page_id": hit.id,
                    "score": hit.score,
                    "dish_name": hit.payload.get("dish_name"),
                    "url": hit.payload.get("url"),
                    "site_id": hit.payload.get("site_id"),
                    "language": hit.payload.get("language"),
                    "method": "ColBERT"
                }
                for hit in results.points
            ]
            
        except Exception as e:
            logger.error(f"Ошибка поиска в ColBERT коллекции: {e}")
            return []
    
    def close(self):
        """Закрытие подключения"""
        if self.client:
            self.client.close()
            logger.info("Подключение к Qdrant закрыто")
