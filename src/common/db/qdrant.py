"""
Менеджер работы с Qdrant для векторного добавления и поиска рецептов
"""

import logging
from typing import Any, Optional
from itertools import batched
from src.common.embedding import prepare_text, EmbeddingFunction, ContentType, get_content_types
from config.db_config import QdrantConfig
from src.models.page import Page
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    MultiVectorConfig, MultiVectorComparator,
    Prefetch, HnswConfigDiff
    )

logger = logging.getLogger(__name__)

class QdrantError(Exception):
    """Базовый класс для ошибок Qdrant"""
    pass


class QdrantNotConnectedError(QdrantError):
    """Ошибка: Qdrant не подключен"""
    def __init__(self, message: str = "Qdrant не подключен. Вызовите connect() перед использованием."):
        self.message = message
        super().__init__(self.message)


class QdrantCollectionNotFoundError(QdrantError):
    """Ошибка: коллекция не найдена"""
    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self.message = f"Коллекция '{collection_name}' не найдена в Qdrant"
        super().__init__(self.message)


class QdrantRecipeManager:
    """Менеджер для работы с Qdrant векторной БД"""
    
    def __init__(self, content_types: list[str] = None, collection_prefix: str = "recipes"):
        """
        Инициализация подключения к Qdrant
        
        Args:
            dense_vectors: Список типов эмбеддингов для создания коллекций
            collection_prefix: Префикс для названий коллекций (используется чтобы разделить два типа коллекций для тестов)
        """
        self.client = None
        self.content_types = content_types if content_types else get_content_types()
        
        # Названия коллекций
        self.collections = {
            vector_type: f"{collection_prefix}_{vector_type}" 
            for vector_type in self.content_types
        }
        
        
    def connect(self) -> bool:
        """Установка подключения к Qdrant"""
        try:
            params = QdrantConfig.get_connection_params()
            
            # Создаем клиент
            self.client = QdrantClient(
                host=params.get('host', 'localhost'),
                port=params.get('port', '6333'),
                api_key=params.get('api_key'),
                timeout=40 # увеличенный таймаут для больших операций
            )
            return True
            
        except Exception as e:
            logger.error(f"Ошибка подключения к Qdrant: {e}")
            return False
        
    def create_collections(
            self, 
            dense_dim: int = 1024, 
            colbert_dim: int = 1024) -> bool:
        """
        Создание отдельных коллекций для каждого типа эмбеддинга
        
        Args:
            dense_dim: Размерность плотных векторов (1024 для BGE-M3)
        
        Returns:
            True если успешно создано или уже существует
        """
        if not self.client:
            raise QdrantNotConnectedError()
        
        try:
            existing_collections = self.client.get_collections().collections
            existing_names = {col.name for col in existing_collections}
            
            for _, collection_name in self.collections.items():
                # Проверяем существование
                if collection_name in existing_names:
                    logger.info(f"✓ Коллекция '{collection_name}' уже существует")
                    continue
                
                vectors_config = {
                    "dense": VectorParams(
                        size=dense_dim,
                        distance=Distance.COSINE
                    ),
                    "colbert": VectorParams(
                        size=colbert_dim,
                        distance=Distance.COSINE,
                        multivector_config=MultiVectorConfig(
                            comparator=MultiVectorComparator.MAX_SIM
                        ),
                        hnsw_config=HnswConfigDiff(m=0)
                    )
                    }
                
                # Создаем коллекцию
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=vectors_config
                )
                logger.info(f"✓ Создана коллекция '{collection_name}'")
            
            return True
            
        except Exception as e:
            logger.error(f"✗ Ошибка создания коллекций: {e}")
            return False


    def add_recipes(
            self, 
            pages: list[Page], 
            embedding_function: EmbeddingFunction, 
            batch_size: int = 50) -> int:
        """
        Массовое добавление рецептов в отдельные коллекции
        
        Args:
            pages: Список объектов страниц с рецептами
            embedding_function: Функция для создания эмбеддингов
            batch_size: Размер батча (уменьшен до 10 для избежания timeout)
        Returns:
            Количество успешно добавленных рецептов
        """
        if not self.client:
            raise QdrantNotConnectedError()
        
        added_count = 0
        
        for batch_num, batch in enumerate(batched(pages, batch_size), 1):
            try:
                # Фильтруем валидные страницы
                valid_pages: list[Page] = [p for p in batch if p.is_recipe and p.dish_name]
                if not valid_pages:
                    logger.warning(f"Батч {batch_num}: нет валидных рецептов")
                    continue
                
                # Обрабатываем каждый тип эмбеддинга отдельно
                for vector_type in self.content_types:
                    collection_name = self.collections[vector_type]
                    
                    # Собираем тексты для этого типа
                    texts: list[str] = []
                    valid_indices = []
                    
                    for idx, page in enumerate(valid_pages):
                        text = prepare_text(page, vector_type)
                        if text:
                            texts.append(text)
                            valid_indices.append(idx)
                    
                    if not texts:
                        logger.warning(f"Батч {batch_num}, тип '{vector_type}': нет текстов")
                        continue

                    use_colbert = (vector_type not in ["description+name", "full"]) # всегда True (таймаут на больших текстах, поэтому full иногда можно отключить)
                    dense_vecs, colbert_vecs = embedding_function(
                        texts,
                        is_query=False,
                        use_colbert=use_colbert
                    )
                    
                    # Создаем точки для этой коллекции
                    points = []
                    for i, page_idx in enumerate(valid_indices):
                        page: Page = valid_pages[page_idx]
                        
                        # Формируем векторы
                        vectors = {"dense": dense_vecs[i]}
                        if use_colbert and colbert_vecs:
                            vectors["colbert"] = colbert_vecs[i]
                        
                        point = PointStruct(
                            id=page.id,
                            vector=vectors,
                            payload={
                                "page_id": page.id,
                                "dish_name": page.dish_name,
                                "site_id": page.site_id,
                                "language": page.language or "unknown",
                            }
                        )
                        points.append(point)
                    
                    # Загружаем в коллекцию
                    if points:
                        self.client.upsert(
                            collection_name=collection_name,
                            points=points,
                            wait=True
                        )
                        logger.info(f"✓ Батч {batch_num}, '{vector_type}': {len(points)} рецептов")
                
                added_count += len(valid_pages)
                logger.info(f"✓ Батч {batch_num} завершен: всего {added_count} рецептов")
            
            except Exception as e:
                logger.error(f"✗ Ошибка батча {batch_num}: {e}")
                continue
        
        logger.info(f"✓ Итого добавлено: {added_count} рецептов в {len(self.collections)} коллекций")
        return added_count
    
    def search(
        self,
        query_text: str,
        limit: int = 10,
        embedding_function: EmbeddingFunction = None, # для основного вектора 
        score_threshold: float = 0.0,
        use_colbert: Optional[bool] = None,
        content_type: str = "full"
    ) -> list[dict[str, Any]]:
        """
        Поиск в ColBERT мультивекторной коллекции
        
        Args:
            query_text: Текст запроса
            limit: Количество результатов
            embedding_function: Функция для создания основного эмбеддинга
            score_threshold: Минимальный порог схожести
            use_colbert: Использовать ColBERT вектор
            content_type: тип контента из рецепта для поиска
            
        Returns:
            Список найденных рецептов
        """
        if use_colbert is None:
            use_colbert = (content_type not in ["description+name", "full"])

        if not self.client:
            logger.warning("Qdrant не подключен")
            return []
        
        try:
            dense_query, colbert_query = embedding_function(query_text, is_query=True, use_colbert=use_colbert)
            dense_query = dense_query[0]

            # Выполняем поиск с мультивектором
            if use_colbert and colbert_query is not None:
                results = self.client.query_points(
                    collection_name=self.collections[content_type],
                    prefetch=Prefetch(
                        query=dense_query,
                        using="dense"
                    ),
                    query=colbert_query[0],
                    using="colbert",
                    limit=limit,
                    with_payload=True,
                    score_threshold=score_threshold
                )
            else:
                results = self.client.query_points(
                    collection_name=self.collections[content_type],
                    query=dense_query,
                    using="dense",
                    limit=limit,
                    with_payload=True,
                    score_threshold=score_threshold
                )
            
            # Форматируем результаты
            return [{
                    "page_id": hit.id,
                    "score": hit.score,
                    "dish_name": hit.payload.get("dish_name"),
                    "site_id": hit.payload.get("site_id"),
                    "language": hit.payload.get("language"),
                    "method": "ColBERT" if use_colbert else "Dense"
                } for hit in results.points
            ]
            
        except Exception as e:
            logger.error(f"Ошибка поиска в ColBERT коллекции: {e}")
            return []
    
    def close(self):
        """Закрытие подключения"""
        if self.client:
            self.client.close()
            logger.info("Подключение к Qdrant закрыто")
