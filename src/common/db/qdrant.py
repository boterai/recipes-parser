"""
Менеджер работы с Qdrant для векторного добавления и поиска рецептов
"""

import time
import logging
from typing import Optional
from itertools import batched
from src.common.embedding import EmbeddingFunction, ImageEmbeddingFunction
from config.db_config import QdrantConfig
from src.models.recipe import Recipe
from qdrant_client import QdrantClient, AsyncQdrantClient
from src.models.image import ImageORM, download_image_async
import asyncio
from qdrant_client.models import QueryRequest, QueryResponse
from collections.abc import AsyncIterator
from qdrant_client.models import (
    Distance, VectorParams, PointStruct)
import os

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
    _async_client = None

    def __new__(cls, *args, **kwargs):
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
            self.images_collection = "images"
            self.collections = {
                "full": f"{collection_prefix}_full",
                "mv": f"{collection_prefix}_mv",
                "images": f"{collection_prefix}_images_1152",
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

    @property
    def async_client(self) -> Optional[QdrantClient]:
        """Получение клиента ClickHouse"""
        return self._async_client
    
    @async_client.setter
    def async_client(self, value: Optional[QdrantClient]):
        """Установка клиента ClickHouse"""
        self._async_client = value

    async def async_connect(self, retry_attempts: int = 3, retry_delay: float = 2.0, connect_timeout: float = 30.0):
        if self.async_client is not None:
            try:
                await self.async_client.get_collections()
                logger.info("✓ Уже подключено к Qdrant")
                return True
            except Exception:
                logger.warning("⚠ Существующее подключение к Qdrant недействительно, повторное подключение...")

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
                    'timeout': connect_timeout
                }
                
                # Добавляем прокси если указан в конфигурации
                if params.get('proxy'):
                    logger.info(f"Использование прокси: {params['proxy']}")
                    client_kwargs['proxy'] = params['proxy']
                
                # Создаем клиент
                self.async_client = AsyncQdrantClient(**client_kwargs)
                
                # Проверка подключения
                await self.async_client.get_collections()
                
                logger.info("✓ Успешное подключение к Qdrant")
                return True
                
            except Exception as e:
                if attempt < retry_attempts - 1:
                    # Экспоненциальная задержка: delay * 2^attempt
                    delay = retry_delay * (2 ** attempt)
                    logger.warning(f"✗ Ошибка подключения к Qdrant (попытка {attempt + 1}/{retry_attempts}): {e}")
                    logger.info(f"Повторная попытка через {delay:.1f}с...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"✗ Не удалось подключиться к Qdrant после {retry_attempts} попыток: {e}")
        
        # Если дошли сюда - все попытки исчерпаны
        return False
        
    def connect(self, retry_attempts: int = 3, retry_delay: float = 2.0, timeout: float = 30.0) -> bool:
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
                    'timeout': timeout
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
        
    def create_collections(self, dims: int = 1024, image_dims: int = 1152) -> bool:
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
                    case "images":
                        vectors_config = {
                            "image": VectorParams(
                                size=image_dims,  # размер длz изображений
                                distance=Distance.COSINE
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

    def vectorise_recipes(
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
                    elif col_type == "mv": # TODO: подумать нужна ли вообще мультивекторная коллекция при наличии full
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
        
        logger.info(f"✓ Итого добавлено: {added_count} рецептов в {len(self.collections) - 1} коллекций")
        return added_count
    
    async def vectorise_images_async(
            self,
            images: list[ImageORM],
            embedding_function: ImageEmbeddingFunction,
            batch_size: int = 10,
            mark_vectorised_callback: callable = None
        ) -> int:
        """
        Добавление изображений рецептов в коллекцию images
        
        Args:
            images: Список объектов ImageORM с изображениями
            embedding_function: Функция для создания эмбеддингов изображений
            batch_size: Размер батча для upsert
            mark_vectorised_callback: Callback для пометки изображений как векторизованных (принимает list[int] image_ids)
        Returns:
            Количество успешно добавленных изображений
        """
        if not self.client:
            raise QdrantNotConnectedError()
        
        collection_name = self.collections.get(self.images_collection)
        if not collection_name:
            logger.error("Коллекция images не найдена")
            return 0
        
        added_count = 0
        
        for batch_num, batch_images in enumerate(batched(images, batch_size), 1):
            try:
                # Проверяем наличие локальных путей и загружаем по URL если нужно
                mark_as_vectorised: list[int] = []
                batch_to_process = []  # Только изображения с валидными данными

                img_to_upload = []
                img_pil_tasks = []
                
                for img in batch_images:
                    if img.local_path and os.path.isfile(img.local_path):
                        img_to_upload.append(img.local_path)
                        batch_to_process.append(img)
                    elif img.image_url:
                        # Загружаем изображение по URL
                        img_pil_tasks.append(download_image_async(img.image_url))
                    else:
                        logger.warning(f"⚠ Изображение ID={img.id} без local_path и image_url, пропускаем")

                    mark_as_vectorised.append(img.id) # все равно отмечаем как векторизованные, чтобы повторно не скачивать 

                # Выполняем асинхронную загрузку изображений по URL
                if img_pil_tasks:
                    downloaded_images = await asyncio.gather(*img_pil_tasks)
                    for idx, img_pil in enumerate(downloaded_images):
                        if img_pil:
                            img_to_upload.append(img_pil)
                            batch_to_process.append(batch_images[idx])
                        else:
                            logger.warning(f"⚠ Не удалось загрузить изображение: {batch_images[idx].image_url}")
                
                if not img_to_upload:
                    logger.warning(f"⚠ Батч {batch_num} не содержит валидных изображений")
                    if mark_as_vectorised:
                        try:
                            mark_vectorised_callback(mark_as_vectorised)
                            logger.debug(f"✓ Помечено {len(mark_as_vectorised)} изображений как векторизованные")
                        except Exception as e:
                            logger.warning(f"⚠ Ошибка при пометке изображений: {e}")
                    continue
                
                # Создаем векторы изображений
                image_vectors = embedding_function(img_to_upload)
                
                # Создаем точки для Qdrant
                points = [
                    PointStruct(
                        id=img.id,
                        vector={"image": vector},
                        payload={
                            "image_id": img.id,
                            "page_id": img.page_id  # Добавляем page_id для связи
                        }
                    )
                    for img, vector in zip(batch_to_process, image_vectors)
                ]
                
                self.client.upsert(collection_name=collection_name, points=points, wait=True)
                added_count += len(points)
                logger.info(f"✓ Батч {batch_num}, 'images': {len(points)} изображений")
            
                # Помечаем изображения как векторизованные
                if mark_vectorised_callback and mark_as_vectorised:
                    try:
                        mark_vectorised_callback(mark_as_vectorised)
                        logger.debug(f"✓ Помечено {len(mark_as_vectorised)} изображений как векторизованные")
                    except Exception as e:
                        logger.warning(f"⚠ Ошибка при пометке изображений: {e}")
                
            except Exception as e:
                logger.error(f"✗ Ошибка батча {batch_num}: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        logger.info(f"✓ Итого добавлено: {added_count} изображений")
        return added_count
            
    async def async_iter_points_with_vectors(
            self, 
            collection_name: str = "full", 
            batch_size: int = 1000, 
            using: str = "dense",
            last_point_id: int = None,
            scroll_timeout: int = 120) -> AsyncIterator[list[int]]:
        """
        Асинхронный итератор по всем точкам в коллекции, возвращающий батчи векторов.
        Args:
            collection_name: Имя коллекции
            batch_size: Размер батча для скрола
            last_point_id: Начальный point_id для скрола (если нужно продолжить с определенного места)
        """
        if not self.async_client:
            raise QdrantNotConnectedError()

        collection = self.collections.get(collection_name)
        offset = last_point_id

        while True:
            points, offset = await self.async_client.scroll(
                collection_name=collection,
                limit=batch_size,
                offset=offset,
                with_payload=False,
                with_vectors=True,
                timeout=scroll_timeout
            )
            if not points:
                return
            
            vec_map: dict[int, list[float]] = {}
            for p in points:
                pid = int(p.id)
                if last_point_id is not None and pid <= last_point_id:
                    continue

                v = p.vector.get(using) if isinstance(p.vector, dict) else p.vector
                if v is None:
                    continue

                vec_map[pid] = v

            if vec_map:
                yield vec_map

            if offset is None:
                return
    
    async def async_query_batch(
        self,
        vectors: list[list[float]],
        collection_name: str,
        using: str,
        limit: int = 30,
        score_threshold: float = 0.0,
    ) -> list[QueryResponse]:
        """
        Асинхронный Batch kNN по коллекции.
        Возвращает на каждый query-вектор список: [QueryResponse, ...]
        """
        if not self.async_client:
            raise QdrantNotConnectedError()

        collection = self.collections.get(collection_name)

        requests = [
            QueryRequest(
                query=v,
                using=using,
                limit=limit,
                score_threshold=score_threshold,
                with_payload=False,
            )
            for v in vectors
        ]
        resp = await self.async_client.query_batch_points(collection_name=collection, requests=requests)
        return resp


    def migrate_full_collection(self,new_collection_name: str,batch_size: int = 100,limit: int = 1000) -> int:
        """
        Мигрирует данные из старой mv коллекции в новую с обновленной структурой
        
        Args:
            new_collection_name: Имя новой коллекции
            dims: Размерность векторов
            batch_size: Размер батча для копирования
        
        Returns:
            Количество перенесенных точек
        """
        if not self.client:
            raise QdrantNotConnectedError()
        
        old_collection = "recipes_full"
                
        # Копируем данные батчами
        migrated_count = 0
        offset = 3000
        
        while True:
            records, offset = self.client.scroll(
                collection_name=old_collection,
                limit=batch_size,
                offset=offset,
                with_vectors=True,
                with_payload=True
            )
            
            if not records:
                break
            
            # Копируем векторы в новую коллекцию
            new_points = []
            for record in records:
                vector = record.vector.get("dense") if isinstance(record.vector, dict) else record.vector
                
                new_points.append(PointStruct(
                    id=record.id,
                    vector={"dense": vector},
                    payload=record.payload
                ))
            
            if new_points:
                self.client.upsert(
                    collection_name=new_collection_name,
                    points=new_points,
                    wait=True
                )
                migrated_count += len(new_points)
                logger.info(f"✓ Мигрировано {migrated_count} точек...")

                if migrated_count >= limit:
                    logger.info(f"✓ Достигнут лимит миграции: {migrated_count} точек")
                    break
            
            if offset is None:
                break
        
        logger.info(f"✓ Миграция завершена: {migrated_count} точек")
        
        return migrated_count