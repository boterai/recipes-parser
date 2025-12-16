"""
Менеджер работы с Qdrant для векторного добавления и поиска рецептов
"""

import logging
from typing import Any, Optional
from itertools import batched
from src.common.embedding import EmbeddingFunction
from config.db_config import QdrantConfig
from src.models.page import Page
from src.models.recipe import Recipe
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
    
    def __init__(self, collection_prefix: str = "recipes"):
        """
        Инициализация подключения к Qdrant
        
        Args:
            dense_vectors: Список типов эмбеддингов для создания коллекций
            collection_prefix: Префикс для названий коллекций (используется чтобы разделить два типа коллекций для тестов)
        """
        self.client = None
        self.collection_prefix = collection_prefix
        self.collections = {"full": f"{collection_prefix}_full", # no colbert locally
                            "mv": f"{collection_prefix}_mv", # multivector search
                            "ingredients": f"{collection_prefix}_ingredients", # ingredients + colbert
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
                https=False,
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

            
            for col_type, collection_name in self.collections.items():
                # Проверяем существование
                if collection_name in existing_names:
                    logger.info(f"✓ Коллекция '{collection_name}' уже существует")
                    continue

                match col_type:
                    case "full":
                        vectors_config = {
                            "dense": VectorParams(
                                size=dense_dim,
                                distance=Distance.COSINE
                            )
                        }
                    case "mv":
                        vectors_config = {
                            "ingredients": VectorParams(
                                size=dense_dim,
                                distance=Distance.COSINE
                            ),
                            "description": VectorParams(
                                size=dense_dim,
                                distance=Distance.COSINE,
                            ),
                            "instructions": VectorParams(
                                size=dense_dim,
                                distance=Distance.COSINE,
                            ),
                            "dish_name": VectorParams(
                                size=dense_dim,
                                distance=Distance.COSINE,
                            ),
                            "tags": VectorParams(
                                size=dense_dim,
                                distance=Distance.COSINE,
                            ),
                            "meta": VectorParams(
                                size=dense_dim,
                                distance=Distance.COSINE,
                            )
                        }
                    case "ingredients":
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
            batch_size: Размер батча
        Returns:
            Количество успешно добавленных рецептов
        """
        if not self.client:
            raise QdrantNotConnectedError()
        
        added_count = 0
        
        for batch_num, batch in enumerate(batched(pages, batch_size), 1):
            try:
                # Конвертируем Page в Recipe, фильтруем валидные
                valid_recipes: list[Recipe] = []
                for p in batch:
                    if p.is_recipe and p.dish_name and p.ingredient and p.step_by_step:
                        valid_recipes.append(p.to_recipe())
                
                if not valid_recipes:
                    logger.warning(f"Батч {batch_num}: нет валидных рецептов")
                    continue
                
                # Обрабатываем каждую коллекцию
                for col_type, collection_name in self.collections.items():
                    if col_type == "full":
                        # Коллекция full: один dense вектор на полный текст
                        texts = [r.get_full_recipe_str() for r in valid_recipes]
                        dense_vecs, _ = embedding_function(texts, is_query=False, use_colbert=False)
                        
                        points = []
                        for i, recipe in enumerate(valid_recipes):
                            point = PointStruct(
                                id=recipe.page_id if hasattr(recipe, 'id') else i,
                                vector={"dense": dense_vecs[i]},
                                payload={
                                    "dish_name": recipe.dish_name,
                                    "description": recipe.description or "",
                                    "id": recipe.page_id
                                }
                            )
                            points.append(point)
                        
                        self.client.upsert(collection_name=collection_name, points=points, wait=True)
                        logger.info(f"✓ Батч {batch_num}, 'full': {len(points)} рецептов")
                    
                    elif col_type == "mv":
                        # Коллекция mv: multiple dense vectors (ingredients, description, instructions, dish_name, tags, meta)
                        points = []
                        for recipe in valid_recipes:
                            # Собираем тексты для каждого компонента
                            comp_texts = {
                                "ingredients": recipe.ingredient or "",
                                "description": recipe.description or "",
                                "instructions": recipe.step_by_step or "",
                                "dish_name": recipe.dish_name or "",
                                "tags": recipe.tags or "",
                                "meta": recipe.get_meta_str() or ""
                            }
                            
                            # Фильтруем пустые
                            comp_texts = {k: v for k, v in comp_texts.items() if v.strip()}
                            
                            if not comp_texts:
                                continue
                            
                            # Создаем embedding для каждого компонента
                            texts_list = list(comp_texts.values())
                            keys_list = list(comp_texts.keys())
                            dense_vecs, _ = embedding_function(texts_list, is_query=False, use_colbert=False)
                            
                            # Формируем multi-vector payload
                            vectors = {key: dense_vecs[idx] for idx, key in enumerate(keys_list)}
                            
                            point = PointStruct(
                                id=recipe.page_id if hasattr(recipe, 'id') else hash(recipe.dish_name),
                                vector=vectors,
                                payload={
                                    "dish_name": recipe.dish_name,
                                    "description": recipe.description or "",
                                    "id": recipe.page_id
                                }
                            )
                            points.append(point)
                        
                        if points:
                            self.client.upsert(collection_name=collection_name, points=points, wait=True)
                            logger.info(f"✓ Батч {batch_num}, 'mv': {len(points)} рецептов")
                    
                    elif col_type == "ingredients":
                        # Коллекция ingredients: dense + colbert на ингредиенты
                        texts = [r.ingredient or "" for r in valid_recipes if r.ingredient]
                        if not texts:
                            logger.warning(f"Батч {batch_num}, 'ingredients': нет ингредиентов")
                            continue
                        
                        dense_vecs, colbert_vecs = embedding_function(texts, is_query=False, use_colbert=True)
                        
                        points = []
                        for i, recipe in enumerate(valid_recipes):
                            if not recipe.ingredient:
                                continue
                            
                            vectors = {"dense": dense_vecs[i]}
                            if colbert_vecs:
                                vectors["colbert"] = colbert_vecs[i]
                            
                            point = PointStruct(
                                id=recipe.page_id if hasattr(recipe, 'id') else i,
                                vector=vectors,
                                payload={
                                    "dish_name": recipe.dish_name,
                                    "ingredients": recipe.ingredient,
                                    "id": recipe.page_id
                                }
                            )
                            points.append(point)
                        
                        if points:
                            self.client.upsert(collection_name=collection_name, points=points, wait=True)
                            logger.info(f"✓ Батч {batch_num}, 'ingredients': {len(points)} рецептов")
                
                added_count += len(valid_recipes)
                logger.info(f"✓ Батч {batch_num} завершен: всего {added_count} рецептов")
            
            except Exception as e:
                logger.error(f"✗ Ошибка батча {batch_num}: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        logger.info(f"✓ Итого добавлено: {added_count} рецептов в {len(self.collections)} коллекций")
        return added_count
    
    def search(
        self,
        query_recipe: Recipe,
        limit: int = 10,
        embedding_function: EmbeddingFunction = None,
        score_threshold: float = 0.0,
        collection_type: str = "full",
        use_colbert: bool = False
    ) -> list[dict[str, Any]]:
        """
        Поиск похожих рецептов в указанной коллекции
        
        Args:
            query_recipe: Рецепт для поиска похожих
            limit: Количество результатов
            embedding_function: Функция для создания эмбеддинга
            score_threshold: Минимальный порог схожести
            collection_type: Тип коллекции ("full", "mv", "ingredients")
            
        Returns:
            Список найденных рецептов с метаданными
        """
        if not self.client:
            logger.warning("Qdrant не подключен")
            return []
        
        collection_name = self.collections.get(collection_type)
        if not collection_name:
            logger.error(f"Неизвестный тип коллекции: {collection_type}")
            return []
        
        try:
            if collection_type == "full":
                # Поиск по полному тексту (dense only)
                query_text = query_recipe.get_full_recipe_str()
                dense_query, _ = embedding_function(query_text, is_query=True, use_colbert=False)
                
                results = self.client.query_points(
                    collection_name=collection_name,
                    query=dense_query[0],
                    using="dense",
                    limit=limit,
                    with_payload=True,
                    score_threshold=score_threshold
                )
                
                return [{
                    "recipe_id": hit.id,
                    "score": hit.score,
                    "dish_name": hit.payload.get("dish_name"),
                    "description": hit.payload.get("description"),
                    "method": "Dense"
                } for hit in results.points]
            
            elif collection_type == "mv":
                # Поиск по multi-vector (взвешенная сумма компонентов)
                comp_texts = query_recipe.prepare_multivector_data()
                
                # Фильтруем пустые
                comp_texts = {k: v for k, v in comp_texts.items() if v.strip()}
                
                if not comp_texts:
                    logger.warning("Нет компонентов для поиска в mv коллекции")
                    return []
                
                # Создаем эмбеддинги для каждого компонента
                texts_list = list(comp_texts.values())
                keys_list = list(comp_texts.keys())
                dense_vecs, _ = embedding_function(texts_list, is_query=True, use_colbert=False)
                
                # Выполняем поиск по первому ключевому компоненту (например, ingredients)
                # и используем prefetch для остальных
                primary_key = keys_list[0]
                primary_vec = dense_vecs[0]
                
                # Простой поиск по первому вектору (можно расширить с prefetch)
                results = self.client.query_points(
                    collection_name=collection_name,
                    query=primary_vec,
                    using=primary_key,
                    limit=limit,
                    with_payload=True,
                    score_threshold=score_threshold
                )
                
                return [{
                    "recipe_id": hit.id,
                    "score": hit.score,
                    "dish_name": hit.payload.get("dish_name"),
                    "description": hit.payload.get("description"),
                    "method": f"MultiVector-{primary_key}"
                } for hit in results.points]
            
            elif collection_type == "ingredients":
                # Поиск с ColBERT по ингредиентам
                query_text = query_recipe.ingredient or ""
                if not query_text:
                    logger.warning("Нет ингредиентов для поиска")
                    return []
                
                dense_query, colbert_query = embedding_function(query_text, is_query=True, use_colbert=True)
                
                # Двухэтапный поиск: prefetch с dense, затем ре-ранкинг с ColBERT
                if colbert_query and use_colbert:
                    results = self.client.query_points(
                        collection_name=collection_name,
                        prefetch=Prefetch(
                            query=dense_query[0],
                            using="dense",
                            limit=limit * 2  # Берем больше для ре-ранкинга
                        ),
                        query=colbert_query[0],
                        using="colbert",
                        limit=limit,
                        with_payload=True,
                        score_threshold=score_threshold
                    )
                else:
                    # Fallback на dense только
                    results = self.client.query_points(
                        collection_name=collection_name,
                        query=dense_query[0],
                        using="dense",
                        limit=limit,
                        with_payload=True,
                        score_threshold=score_threshold
                    )
                
                return [{
                    "recipe_id": hit.id,
                    "score": hit.score,
                    "dish_name": hit.payload.get("dish_name"),
                    "ingredients": hit.payload.get("ingredients"),
                    "method": "ColBERT+Dense" if colbert_query else "Dense"
                } for hit in results.points]
            
            else:
                logger.error(f"Неподдерживаемый тип коллекции: {collection_type}")
                return []
            
        except Exception as e:
            logger.error(f"Ошибка поиска в коллекции '{collection_type}': {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def search_multivector_weighted(
        self,
        query_recipe: Recipe,
        limit: int = 10,
        embedding_function: EmbeddingFunction = None,
        score_threshold: float = 0.0,
        component_weights: Optional[dict[str, float]] = None
    ) -> list[dict[str, Any]]:
        """
        Взвешенный поиск по мультивекторной коллекции с приоритетами компонентов
        
        Выполняет отдельный поиск по каждому компоненту рецепта, затем объединяет
        результаты с учетом весов компонентов.
        
        Args:
            query_recipe: Рецепт для поиска похожих
            limit: Количество финальных результатов
            embedding_function: Функция для создания эмбеддинга
            score_threshold: Минимальный порог схожести
            component_weights: Словарь весов для компонентов
                По умолчанию: {
                    "ingredients": 0.35,  # Самый приоритетный
                    "dish_name": 0.25,
                    "description": 0.15,
                    "instructions": 0.15,
                    "tags": 0.05,
                    "meta": 0.05
                }
        
        Returns:
            Список рецептов с взвешенным score
        """
        if not self.client:
            logger.warning("Qdrant не подключен")
            return []
        
        collection_name = self.collections.get("mv")
        if not collection_name:
            logger.error("Мультивекторная коллекция не найдена")
            return []
        
        # Веса по умолчанию (сумма = 1.0)
        if component_weights is None:
            component_weights = {
                "ingredients": 0.35,    # Ингредиенты - самый важный компонент
                "dish_name": 0.25,      # Название блюда
                "description": 0.15,    # Описание
                "instructions": 0.15,   # Инструкции приготовления
                "tags": 0.05,           # Теги
                "meta": 0.05            # Метаданные (время, калории)
            }
        
        try:
            # Подготовка компонентов запроса
            comp_texts = query_recipe.prepare_multivector_data()
            
            # Фильтруем пустые компоненты
            comp_texts = {k: v for k, v in comp_texts.items() if v.strip()}
            
            if not comp_texts:
                logger.warning("Нет компонентов для поиска")
                return []
            
            # Создаем эмбеддинги для всех компонентов
            texts_list = list(comp_texts.values())
            keys_list = list(comp_texts.keys())
            dense_vecs, _ = embedding_function(texts_list, is_query=True, use_colbert=False)
            
            # Словарь для накопления score по каждому recipe_id
            # {recipe_id: {"total_score": float, "component_scores": {component: score}, "payload": dict}}
            recipe_scores = {}
            
            # Выполняем поиск по каждому компоненту
            search_limit = limit * 3  # Берем больше кандидатов для каждого компонента
            
            for idx, component_name in enumerate(keys_list):
                weight = component_weights.get(component_name, 0)
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
                    "description": data["payload"].get("description"),
                    "method": "MultiVector-Weighted",
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
