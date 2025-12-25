"""
Менеджер работы с Qdrant для векторного добавления и поиска рецептов
"""

import time
import logging
from typing import Any, Optional
from itertools import batched
from src.common.embedding import EmbeddingFunction
from config.db_config import QdrantConfig
from src.models.recipe import Recipe
from src.models.search_config import ComponentWeights, SearchProfiles
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct)

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
    _instance = None
    _client = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(QdrantRecipeManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, collection_prefix: str = "recipes"):
        """
        Инициализация подключения к Qdrant
        
        Args:
            collection_prefix: Префикс для названий коллекций (используется чтобы разделить два типа коллекций для тестов)
        """
        if not QdrantRecipeManager._initialized:
            self.collection_prefix = collection_prefix
            self.full_collection = "full"
            self.mv_collection = "mv"
            self.collections = {
                "full": f"{collection_prefix}_full",
                "mv": f"{collection_prefix}_mv",
            }
            self.connected = False
            
            QdrantRecipeManager._initialized = True
            logger.info(f"Инициализирован QdrantRecipeManager с префиксом '{collection_prefix}'")
        else:
            if collection_prefix != self.collection_prefix:
                logger.warning(
                    f"QdrantRecipeManager уже инициализирован с префиксом '{self.collection_prefix}'. "
                    f"Игнорируем новый префикс '{collection_prefix}'"
                )
    @property
    def client(self) -> Optional[QdrantClient]:
        """Получение клиента ClickHouse"""
        return self._client
    
    @client.setter
    def client(self, value: Optional[QdrantClient]):
        """Установка клиента ClickHouse"""
        self._client = value
        
    def connect(self, retry_attempts: int = 3, retry_delay: float = 2.0) -> bool:
        """Установка подключения к Qdrant с повторными попытками
        
        Args:
            retry_attempts: Количество попыток подключения
            retry_delay: Базовая задержка между попытками (в секундах)
        
        Returns:
            True если подключение успешно, False иначе
        """
        if self.client is not None:
            try:
                self.client.get_collections()
                logger.info("✓ Уже подключено к Qdrant")
                return True
            except Exception:
                logger.warning("⚠ Существующее подключение к Qdrant недействительно, повторное подключение...")
                self.close()

        params = QdrantConfig.get_connection_params()
        
        for attempt in range(retry_attempts):
            try:
                logger.info(f"Попытка подключения к Qdrant {attempt + 1}/{retry_attempts}...")
                
                # Базовые параметры подключения
                client_kwargs = {
                    'host': params.get('host', 'localhost'),
                    'port': params.get('port', '6333'),
                    'api_key': params.get('api_key'),
                    'https': params.get('https', False),
                    'timeout': 40  # увеличенный таймаут для больших операций
                }
                
                # Добавляем прокси если указан в конфигурации
                if params.get('proxy'):
                    logger.info(f"Использование прокси: {params['proxy']}")
                    client_kwargs['proxy'] = params['proxy']
                
                # Создаем клиент
                self.client = QdrantClient(**client_kwargs)
                
                # Проверка подключения
                self.client.get_collections()
                
                logger.info("✓ Успешное подключение к Qdrant")
                return True
                
            except Exception as e:
                if attempt < retry_attempts - 1:
                    # Экспоненциальная задержка: delay * 2^attempt
                    delay = retry_delay * (2 ** attempt)
                    logger.warning(f"✗ Ошибка подключения к Qdrant (попытка {attempt + 1}/{retry_attempts}): {e}")
                    logger.info(f"Повторная попытка через {delay:.1f}с...")
                    time.sleep(delay)
                else:
                    logger.error(f"✗ Не удалось подключиться к Qdrant после {retry_attempts} попыток: {e}")
        
        # Если дошли сюда - все попытки исчерпаны
        return False
        
    def create_collections(self, dims: int = 1024) -> bool:
        """
        Создание отдельных коллекций для каждого типа эмбеддинга
        
        Args:
            dims: Размерность плотных векторов (1024 для BGE-en)
        
        Returns:
            True если успешно создано или уже существует
        """
        if not self.client:
            raise QdrantNotConnectedError()
        
        try:
            existing_collections = self.client.get_collections().collections
            existing_names = {col.name for col in existing_collections}

            
            for col_type, collection_name in self.collections.items():
                # Проверяем существование
                if collection_name in existing_names:
                    logger.info(f"✓ Коллекция '{collection_name}' уже существует")
                    continue

                match col_type:
                    case "full":
                        vectors_config = {
                            "dense": VectorParams(
                                size=dims,
                                distance=Distance.COSINE
                            )
                        }
                    case "mv":
                        vectors_config = {
                            "ingredients": VectorParams(
                                size=dims,
                                distance=Distance.COSINE
                            ),
                            "description": VectorParams(
                                size=dims,
                                distance=Distance.COSINE,
                            ),
                            "instructions": VectorParams(
                                size=dims,
                                distance=Distance.COSINE,
                            ),
                            "dish_name": VectorParams(
                                size=dims,
                                distance=Distance.COSINE,
                            ),
                            "tags": VectorParams(
                                size=dims,
                                distance=Distance.COSINE,
                            ),
                            "meta": VectorParams(
                                size=dims,
                                distance=Distance.COSINE,
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


    def _add_to_full_collection(
        self, 
        batch: list[Recipe], 
        collection_name: str,
        embedding_function: EmbeddingFunction,
        batch_num: int
    ) -> int:
        """
        Добавление рецептов в коллекцию 'full' (один dense вектор на полный текст)
        
        Args:
            batch: Батч рецептов
            collection_name: Имя коллекции
            embedding_function: Функция эмбеддинга
            batch_num: Номер батча для логирования
            
        Returns:
            Количество добавленных рецептов
        """
        texts = [r.get_full_recipe_str() for r in batch]
        dense_vecs = embedding_function(texts, is_query=False)
        
        points = []
        for i, recipe in enumerate(batch):
            point = PointStruct(
                id=recipe.page_id,
                vector={"dense": dense_vecs[i]},
                payload={
                    "dish_name": recipe.dish_name,
                    "id": recipe.page_id
                }
            )
            points.append(point)
        
        self.client.upsert(collection_name=collection_name, points=points, wait=True)
        logger.info(f"✓ Батч {batch_num}, 'full': {len(points)} рецептов")
        return len(points)
    
    def _add_to_multivector_collection(
        self,
        batch: list[Recipe],
        collection_name: str,
        embedding_function: EmbeddingFunction,
        batch_num: int
    ) -> int:
        """
        Добавление рецептов в мультивекторную коллекцию (отдельные векторы для компонентов)
        
        Args:similar_recipes: list[float, Recipe]
            batch: Батч рецептов
            collection_name: Имя коллекции
            embedding_function: Функция эмбеддинга
            batch_num: Номер батча для логирования
            
        Returns:
            Количество добавленных рецептов
        """
        points = []
        for recipe in batch:
            # Собираем тексты для каждого компонента
            comp_texts = recipe.get_multivector_data()
            
            # Фильтруем пустые
            comp_texts = {k: v for k, v in comp_texts.items() if v.strip()}
            
            if not comp_texts:
                continue
            
            # Создаем dense embedding для каждого компонента
            texts_list = list(comp_texts.values())
            keys_list = list(comp_texts.keys())
            
            dense_vecs = embedding_function(texts_list, is_query=False)
            vectors = {key: dense_vecs[idx] for idx, key in enumerate(keys_list)}
            
            point = PointStruct(
                id=recipe.page_id,
                vector=vectors,
                payload={
                    "dish_name": recipe.dish_name,
                    "id": recipe.page_id
                }
            )
            points.append(point)
        
        if points:
            self.client.upsert(collection_name=collection_name, points=points, wait=True)
            logger.info(f"✓ Батч {batch_num}, 'mv': {len(points)} рецептов")
            return len(points)
        return 0
    
    def _mark_vectorised(self, recipes: list[Recipe], mark_vectorised_callback = None):
        """
        _mark_vectorised Пометка рецептов как векторизованные через callback функцию

        Args:
            recipes: Список рецептов для пометки
            mark_vectorised_callback: Функция для пометки рецептов как векторизованных (принимает list[Recipe])
        """

        if not mark_vectorised_callback:
            return
        for page in recipes:
            page.vectorised = True
        try:
            marked = mark_vectorised_callback(recipes)
            logger.info(f"✓ Помечено {marked} рецептов как векторизованные")
        except Exception as e:
            logger.warning(f"⚠ Ошибка при пометке рецептов как векторизованных: {e}")

    def add_recipes(
            self, 
            pages: list[Recipe], 
            embedding_function: EmbeddingFunction, 
            batch_size: int = 50,
            mark_vectorised_callback = None) -> int:
        """
        Массовое добавление рецептов в отдельные коллекции
        
        Args:
            pages: Список объектов страниц с рецептами
            embedding_function: Функция для создания эмбеддингов
            batch_size: Размер батча
            mark_vectorised_callback: Функция для пометки рецептов как векторизованных (принимает list[int] page_ids)
        Returns:
            Количество успешно добавленных рецептов
        """
        if not self.client:
            raise QdrantNotConnectedError()
        
        added_count = 0
        
        for batch_num, batch in enumerate(batched(pages, batch_size), 1):
            try:
                # Обрабатываем каждую коллекцию
                for col_type, collection_name in self.collections.items():
                    if col_type == "full":
                        self._add_to_full_collection(batch, collection_name, embedding_function, batch_num)
                    elif col_type == "mv":
                        self._add_to_multivector_collection(batch, collection_name, embedding_function, batch_num)
                
                added_count += len(batch)
                logger.info(f"✓ Батч {batch_num} завершен: всего {added_count} рецептов")
                
                # Помечаем рецепты как векторизованные
                self._mark_vectorised(batch, mark_vectorised_callback)
            
            except Exception as e:
                logger.error(f"✗ Ошибка батча {batch_num}: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        logger.info(f"✓ Итого добавлено: {added_count} рецептов в {len(self.collections)} коллекций")
        return added_count
    
    def search_full(
        self,
        query_vector: list[float],
        limit: int = 10,
        score_threshold: float = 0.0,

    ) -> list[dict[str, Any]]:
        """
        Поиск похожих рецептов в указанной коллекции
        
        Args:
            query_recipe: вектор запроса
            limit: Количество результатов
            embedding_function: Функция для создания эмбеддинга
            score_threshold: Минимальный порог схожести            
        Returns:
            Список найденных рецептов с метаданными
        """
        if not self.client:
            logger.warning("Qdrant не подключен")
            return []
        collection = self.collections.get(self.full_collection)
        try:
            results = self.client.query_points(
                collection_name=collection,
                query=query_vector,
                using="dense",
                limit=limit,
                with_payload=True,
                score_threshold=score_threshold
            )
            
            return [{
                "recipe_id": hit.id,
                "score": hit.score,
                "dish_name": hit.payload.get("dish_name"),
                "method": "Dense"
            } for hit in results.points]
        
        except Exception as e:
            logger.error(f"Ошибка поиска в коллекции 'full': {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def search_multivector_weighted(
        self,
        recipe: Recipe,
        limit: int = 10,
        embedding_function: EmbeddingFunction = None,
        score_threshold: float = 0.0,
        component_weights: Optional[ComponentWeights] = None
    ) -> list[dict[str, Any]]:
        """
        Взвешенный поиск по мультивекторной коллекции с приоритетами компонентов
        
        Выполняет отдельный поиск по каждому компоненту рецепта, затем объединяет
        результаты с учетом весов компонентов.
        
        Args:
            recipe: Рецепт для поиска похожих
            limit: Количество финальных результатов
            embedding_function: Функция для создания эмбеддинга
            score_threshold: Минимальный порог схожести
            component_weights: Словарь весов для компонентов
        
        Returns:
            Список рецептов с взвешенным score
        """
        if not self.client:
            logger.warning("Qdrant не подключен")
            return []
        
        collection_name = self.collections.get(self.mv_collection)
        if not collection_name:
            logger.error("Мультивекторная коллекция не найдена")
            return []
        
        # Веса по умолчанию (сумма = 1.0)
        if component_weights is None:
            component_weights = SearchProfiles.BALANCED

        weights_dict = component_weights.to_dict()
            
        try:
            # Подготовка компонентов запроса
            comp_texts = recipe.get_multivector_data()
            
            # Фильтруем пустые компоненты
            comp_texts = {k: v for k, v in comp_texts.items() if v.strip()}
            
            if not comp_texts:
                logger.warning("Нет компонентов для поиска")
                return []
            
            # Фильтруем компоненты с нулевым весом перед созданием эмбеддингов
            comp_texts = {k: v for k, v in comp_texts.items() if weights_dict.get(k, 0) > 0}
            
            if not comp_texts:
                logger.warning("Все компоненты имеют нулевой вес")
                return []
            
            # Создаем эмбеддинги только для компонентов с ненулевым весом
            texts_list = list(comp_texts.values())
            keys_list = list(comp_texts.keys())
            dense_vecs = embedding_function(texts_list, is_query=True)
            
            # Словарь для накопления score по каждому recipe_id
            # {recipe_id: {"total_score": float, "component_scores": {component: score}, "payload": dict}}
            recipe_scores = {}
            
            # Выполняем поиск по каждому компоненту
            search_limit = limit * 3  # Берем больше кандидатов для каждого компонента
            
            for idx, component_name in enumerate(keys_list):
                weight = weights_dict.get(component_name, 0)
                if weight == 0:
                    continue
                
                try:
                    # Поиск по этому компоненту
                    results = self.client.query_points(
                        collection_name=collection_name,
                        query=dense_vecs[idx],
                        using=component_name,
                        limit=search_limit,
                        with_payload=True,
                        score_threshold=score_threshold
                    )
                    
                    # Обрабатываем результаты
                    for hit in results.points:
                        recipe_id = hit.id
                        component_score = hit.score * weight  # Взвешенный score
                        
                        if recipe_id not in recipe_scores:
                            recipe_scores[recipe_id] = {
                                "total_score": 0.0,
                                "component_scores": {},
                                "payload": hit.payload,
                                "matches": 0  # Количество компонентов с совпадениями
                            }
                        
                        recipe_scores[recipe_id]["total_score"] += component_score
                        recipe_scores[recipe_id]["component_scores"][component_name] = hit.score
                        recipe_scores[recipe_id]["matches"] += 1
                    
                    logger.debug(f"Компонент '{component_name}': найдено {len(results.points)} рецептов")
                
                except Exception as e:
                    logger.warning(f"Ошибка поиска по компоненту '{component_name}': {e}")
                    continue
            
            # Сортируем по итоговому взвешенному score
            sorted_recipes = sorted(
                recipe_scores.items(),
                key=lambda x: (x[1]["total_score"], x[1]["matches"]),  # Сначала по score, потом по количеству совпадений
                reverse=True
            )[:limit]
            
            # Форматируем результаты
            results = []
            for recipe_id, data in sorted_recipes:
                results.append({
                    "recipe_id": recipe_id,
                    "score": data["total_score"],
                    "dish_name": data["payload"].get("dish_name"),
                    "component_scores": data["component_scores"],  # Детализация по компонентам
                    "matches": data["matches"]  # Количество совпавших компонентов
                })
            
            logger.info(f"Найдено {len(results)} рецептов с взвешенным поиском")
            return results
            
        except Exception as e:
            logger.error(f"Ошибка взвешенного поиска: {e}")
            import traceback
            traceback.print_exc()
            return []
        

    def close(self):
        """Закрытие подключения"""
        if self.client:
            self.client.close()
            logger.info("Подключение к Qdrant закрыто")
