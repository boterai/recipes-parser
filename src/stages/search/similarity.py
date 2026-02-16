"""модуль для поиска и отметки рецептов как похожих"""

from __future__ import annotations
import json
import logging
import random
from dataclasses import dataclass
from typing import Optional, Literal
import os
import asyncio
import aiofiles

import numpy as np

if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.common.db.qdrant import QdrantRecipeManager
from src.common.gpt.client import GPTClient
from src.repositories.similarity import RecipeSimilarity
from src.repositories.image import ImageRepository
from src.models.recipe import Recipe

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


class _DSU:
    def __init__(self) -> None:
        self.parent: dict[int, int] = {}
        self.rank: dict[int, int] = {}
        self.size: dict[int, int] = {}  # размер кластера (хранится в корне)

    def find(self, x: int) -> int:
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
            self.size[x] = 1
            return x
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        
        # Суммируем размеры до объединения
        new_size = self.size.get(ra, 1) + self.size.get(rb, 1)
        
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1
        
        # Обновляем размер в новом корне
        self.size[ra] = new_size
    
    def get_size(self, x: int) -> int:
        """Возвращает размер кластера, содержащего элемент x."""
        root = self.find(x)
        return self.size.get(root, 1)


def build_clusters_from_dsu(dsu: _DSU, min_cluster_size: int) -> list[list[int]]:
    groups: dict[int, list[int]] = {}
    for node in dsu.parent.keys():
        root = dsu.find(node)
        groups.setdefault(root, []).append(node)

    clusters = [sorted(m) for m in groups.values() if len(m) >= min_cluster_size]
    clusters.sort(key=lambda c: (-len(c), c[0]))
    return clusters

@dataclass()
class ClusterParams:
    limit: int = 25               # top-K соседей на рецепт
    score_threshold: float = 0.9 # порог
    scroll_batch: int = 1000      # чтение ids из Qdrant
    query_batch: int = 64        # сколько векторов в batch query
    min_cluster_size: int = 5     # отбрасывать одиночки

    # параметры коллекции Qdrant
    collection_name: str = "full"
    using: str = "dense"

    # Ограничение выборки (для тестового прогона)
    max_recipes: int | None = None              # обработать не больше N рецептов всего
    last_point_id: Optional[int] = None         # с какого id наичнать итерацию
    sample_per_scroll_batch: int | None = None  # случайно взять N ids из каждого scroll батча
    sample_seed: int = 42                       # seed для воспроизводимой выборки

    union_top_k: int = 10        # сколько соседей юнифицировать в DSU
    max_async_tasks: int = 10    # максимальное число одновременных асинхронных задач
    
    # Параметры проверки центроида
    use_centroid_check: bool = True       # использовать проверку центроида при union
    centroid_threshold: float = 0.9      # минимальная похожесть с центроидом для объединения
    
    # Параметры адаптивного порога
    use_adaptive_threshold: bool = True   # использовать адаптивный порог (строже для больших кластеров)
    adaptive_min_cluster_size: int = 30   # применять адаптивный порог только для кластеров >= этого размера
    adaptive_size_factor: float = 0.002   # увеличение порога на каждый элемент кластера (сверх adaptive_min_cluster_size)
    adaptive_max_threshold: float = 0.98  # максимальный порог (верхний лимит)
    
    # Параметры валидации плотности кластеров
    min_cluster_size_for_validation: int = 5  # валидировать только кластеры >= этого размера
    density_min_similarity: float = 0.91      # порог похожести для validate_cluster_density

class SimilaritySearcher:
    def __init__(self, params: ClusterParams = None, build_type: Literal["image", "full", "ingredients"] = "full"):
        self.qd_collection_prefix = "recipes"
        self.gpt_client: GPTClient = GPTClient()
        self.similarity_repository = RecipeSimilarity()
        self.image_repository = ImageRepository()
        self._clickhouse_manager = None

        self.last_id: int | None = None
        self.dsu: _DSU = _DSU()
        self.params: ClusterParams = params
        self.rng = random.Random(params.sample_seed)
        self.set_params(build_type=build_type)
        self.dsu_filename = os.path.join("recipe_clusters", f"dsu_state_{build_type}_{self.params.score_threshold}.json")
        self.clusters_filename = os.path.join("recipe_clusters", f"{build_type}_clusters_{self.params.score_threshold}_{self.params.centroid_threshold}.json")
        self.cluter_image_mapping = os.path.join("recipe_clusters", f"clusters_to_image_ids_{self.params.score_threshold}_{self.params.centroid_threshold}.json")
        self.validated_centroids_filename = os.path.join("recipe_clusters", f"{build_type}_centroids_{self.params.score_threshold}_{self.params.centroid_threshold}.json")
        self.build_type = build_type
        
        # Центроиды кластеров: root_id -> vector (numpy array)
        self.cluster_centroids: dict[int, np.ndarray] = {}
        
        # Центроиды валидированных кластеров: cluster key -> page_id ближайшего к центроиду рецепта
        self.validated_centroids: dict[int, int] = {}

    @property
    def clickhouse_manager(self): # layz initialization + lazy import
        if not self._clickhouse_manager:
            from src.common.db.clickhouse import ClickHouseManager
            self._clickhouse_manager = ClickHouseManager()
            if not self._clickhouse_manager.connect():
                self._clickhouse_manager = None
                raise RuntimeError("Failed to connect to ClickHouse")
        return self._clickhouse_manager

    def save_dsu_state(self) -> None:
        """Сохраняет состояние DSU в файл."""
        # Конвертируем numpy arrays в списки для JSON
        centroids_serializable = {
            str(k): v.tolist() for k, v in self.cluster_centroids.items()
        }
        state = {
            "parent": self.dsu.parent,
            "rank": self.dsu.rank,
            "last_id": self.last_id,
            "centroids": centroids_serializable
        }
        with open(self.dsu_filename, 'w') as f:
            json.dump(state, f, indent=2)
        logger.info(f"Saved DSU state to {self.dsu_filename} (last_id={self.last_id}, centroids={len(self.cluster_centroids)})")

    def load_dsu_state(self) -> None:
        """Загружает состояние DSU из файла."""
        if not os.path.exists(self.dsu_filename):
            logger.warning(f"DSU state file {self.dsu_filename} not found, starting fresh")
            return
        
        with open(self.dsu_filename, 'r') as f:
            state:dict = json.load(f)
        
        # Восстанавливаем DSU
        self.dsu.parent = {int(k): int(v) for k, v in state.get("parent", {}).items()}
        self.dsu.rank = {int(k): int(v) for k, v in state.get("rank", {}).items()}
        self.last_id = state.get("last_id")
        
        # Восстанавливаем центроиды
        centroids_raw = state.get("centroids", {})
        self.cluster_centroids = {
            int(k): np.array(v, dtype=np.float32) for k, v in centroids_raw.items()
        }
        logger.info(f"Loaded DSU state from {self.dsu_filename} (last_id={self.last_id}, nodes={len(self.dsu.parent)}, centroids={len(self.cluster_centroids)})")

    def save_validated_centroids(self) -> None:
        """Сохраняет центроиды валидированных кластеров в файл.
        
        Формат: {cluster_index: page_id ближайшего к центроиду рецепта}
        """
        with open(self.validated_centroids_filename, 'w') as f:
            json.dump(self.validated_centroids, f, indent=2)
        logger.info(f"Saved {len(self.validated_centroids)} validated centroids to {self.validated_centroids_filename}")

    def load_validated_centroids(self) -> None:
        """Загружает центроиды валидированных кластеров из файла."""
        if not os.path.exists(self.validated_centroids_filename):
            logger.warning(f"Validated centroids file {self.validated_centroids_filename} not found")
            return
        
        with open(self.validated_centroids_filename, 'r') as f:
            raw = json.load(f)
        
        self.validated_centroids = {k: int(v) for k, v in raw.items()}
        logger.info(f"Loaded {len(self.validated_centroids)} validated centroids from {self.validated_centroids_filename}")

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Вычисляет косинусную похожесть между двумя векторами."""
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(vec1, vec2) / (norm1 * norm2))
    
    def _get_adaptive_threshold(self, cluster_size: int) -> float:
        """
        Вычисляет адаптивный порог на основе размера кластера.
        
        Чем больше кластер, тем строже порог — предотвращает "снежный ком".
        Для кластеров меньше adaptive_min_cluster_size (по умолчанию 30) 
        возвращается базовый centroid_threshold.
        
        Args:
            cluster_size: текущий размер кластера
            
        Returns:
            Адаптивный порог похожести
        """
        if not self.params.use_adaptive_threshold:
            return self.params.centroid_threshold
        
        # Для кластеров меньше минимального размера — базовый порог
        if cluster_size < self.params.adaptive_min_cluster_size:
            return self.params.centroid_threshold
        
        # Считаем прирост только от элементов сверх минимального размера
        extra_size = cluster_size - self.params.adaptive_min_cluster_size
        adaptive = self.params.centroid_threshold + (extra_size * self.params.adaptive_size_factor)
        return min(adaptive, self.params.adaptive_max_threshold)
    
    def _get_cluster_size(self, root_id: int) -> int:
        """
        Возвращает размер кластера из DSU.
        """
        return self.dsu.get_size(root_id)
    
    def union_with_centroid_check(
        self,
        src_id: int,
        dst_id: int,
        src_vec: np.ndarray,
        dst_vec: np.ndarray,
    ) -> bool:
        """
        Объединяет два элемента в DSU с проверкой центроида и адаптивным порогом.
        
        Предотвращает "транзитивный дрейф" кластеров, проверяя что новый элемент
        достаточно близок к центроиду существующего кластера.
        
        Адаптивный порог: чем больше кластер, тем строже проверка.
        
        Args:
            src_id: ID исходного элемента
            dst_id: ID целевого элемента  
            src_vec: Вектор исходного элемента
            dst_vec: Вектор целевого элемента
            
        Returns:
            True если объединение произошло, False если отклонено
        """
        src_root = self.dsu.find(src_id)
        dst_root = self.dsu.find(dst_id)
        
        # Уже в одном кластере
        if src_root == dst_root:
            return False
        
        # Получаем размеры кластеров
        src_size = self._get_cluster_size(src_root)
        dst_size = self._get_cluster_size(dst_root)
        max_size = max(src_size, dst_size)
        
        # Вычисляем адаптивный порог
        threshold = self._get_adaptive_threshold(max_size)
        
        # Получаем центроиды кластеров (или сами векторы если кластер новый)
        src_centroid = self.cluster_centroids.get(src_root, src_vec)
        dst_centroid = self.cluster_centroids.get(dst_root, dst_vec)
        
        # Проверяем похожесть dst с центроидом src кластера
        sim_dst_to_src_centroid = self._cosine_similarity(dst_vec, src_centroid)
        
        # Проверяем похожесть src с центроидом dst кластера  
        sim_src_to_dst_centroid = self._cosine_similarity(src_vec, dst_centroid)
        
        # Оба должны быть достаточно близки к центроидам (с адаптивным порогом)
        if sim_dst_to_src_centroid < threshold or sim_src_to_dst_centroid < threshold:
            return False
        
        # Выполняем объединение
        self.dsu.union(src_id, dst_id)
        
        # Обновляем центроид объединённого кластера (взвешенный по размеру)
        new_root = self.dsu.find(src_id)
        
        # Взвешенное усреднение центроидов по размеру кластеров
        new_centroid = (src_centroid * src_size + dst_centroid * dst_size) / (src_size + dst_size)
        # Нормализуем для косинусной метрики
        norm = np.linalg.norm(new_centroid)
        if norm > 0:
            new_centroid = new_centroid / norm
        
        self.cluster_centroids[new_root] = new_centroid
        
        # Удаляем старые центроиды если они отличаются от нового корня
        if src_root != new_root:
            self.cluster_centroids.pop(src_root, None)
        if dst_root != new_root:
            self.cluster_centroids.pop(dst_root, None)
        
        return True
    
    def init_centroid(self, point_id: int, vector: np.ndarray) -> None:
        """
        Инициализирует центроид для точки (если ещё не в кластере).
        Размер кластера автоматически отслеживается в DSU.
        
        Args:
            point_id: ID точки
            vector: Вектор точки
        """
        root = self.dsu.find(point_id)  # DSU автоматически инициализирует size=1 для новых элементов
        if root not in self.cluster_centroids:
            vec_np = np.array(vector, dtype=np.float32)
            norm = np.linalg.norm(vec_np)
            if norm > 0:
                vec_np = vec_np / norm
            self.cluster_centroids[root] = vec_np

    async def query_batch_async(self, q:QdrantRecipeManager, vectors: list[float]) -> Optional[list[int]]:
        for attempt in range(3):
            try:
                response = await q.async_query_batch(
                    collection_name=self.params.collection_name,
                    using=self.params.using,
                    vectors=vectors,
                    limit=self.params.limit,
                    score_threshold=self.params.score_threshold,
                )
                batch_hits: list[list[int]] = []
                for r in response:
                    batch_hits.append([int(p.id) for p in r.points])
                return batch_hits
            except TimeoutError:
                if attempt == 2:
                    raise
                # простой backoff + jitter
                delay = (2 ** attempt) + self.rng.random()
                logger.warning("Timeout in query_batch; retry %d; sleep %.2fs", attempt + 1, delay)
                await asyncio.sleep(delay)
        return None

    async def build_clusters_async(self, reuse_dsu: bool = True) -> list[list[int]]:
        """
        Кластеры по коллекциям из Qdrant.
        Предпосылка: point_id в Qdrant == pages.id, и named vector = params.using
        """
        q = QdrantRecipeManager(collection_prefix=self.qd_collection_prefix)
        await q.async_connect(connect_timeout=210) # увеличенный таймаут для долгих операций
        
        if not reuse_dsu or self.dsu is None:
            self.dsu = _DSU()

        processed = 0

        if self.params.collection_name is None:
            logger.error("params.collection_name is None")
            return []
        
        if self.params.using is None:
            logger.error("params.using is None")
            return []
        
        if self.params.last_point_id is not None:
            self.last_id = self.params.last_point_id

        sem = asyncio.Semaphore(self.params.max_async_tasks)

        async for vec_map in q.async_iter_points_with_vectors(
            collection_name=self.params.collection_name,
            batch_size=self.params.scroll_batch,
            using=self.params.using,
            last_point_id=self.last_id, scroll_timeout=210
        ):
            ids = list(vec_map)

            if not ids or ids == [self.last_id]:
                logger.info("No more ids to process, stopping.")
                break

            async def run_one(sub_ids: list[int], semaphore) -> tuple[list[int], list[list[int]]]:
                vectors = [vec_map[rid] for rid in sub_ids]
                async with semaphore:
                    batch_hits = await self.query_batch_async(q, vectors)

                return sub_ids, batch_hits

            tasks: list[asyncio.Task[tuple[list[int], list[list[int]]]]] = []
            for i in range(0, len(ids), self.params.query_batch):
                sub_ids = ids[i:i + self.params.query_batch]
                tasks.append(asyncio.create_task(run_one(sub_ids, sem)))

            for done in asyncio.as_completed(tasks):
                try:
                    sub_ids, batch_hits = await done
                except Exception as e:
                    logger.error(f"Error in async task: {e}")
                    continue

                if not batch_hits:
                    continue

                # union только top-K
                for src_id, hits in zip(sub_ids, batch_hits):
                    if not hits:
                        continue
                    
                    src_vec = vec_map.get(src_id)
                    if src_vec is None:
                        continue
                    
                    src_vec_np = np.array(src_vec, dtype=np.float32)
                    
                    # Инициализируем центроид для src если используем проверку
                    if self.params.use_centroid_check:
                        self.init_centroid(src_id, src_vec_np)
                    
                    top_hits = hits[:self.params.union_top_k] if self.params.union_top_k else hits
                    for dst_id in top_hits:
                        if dst_id == src_id:
                            continue
                        
                        if self.params.use_centroid_check:
                            dst_vec = vec_map.get(dst_id)
                            if dst_vec is not None:
                                dst_vec_np = np.array(dst_vec, dtype=np.float32)
                                self.init_centroid(dst_id, dst_vec_np)
                                self.union_with_centroid_check(int(src_id), dst_id, src_vec_np, dst_vec_np)
                            else:

                                self.dsu.union(int(src_id), dst_id)
                        else:
                            self.dsu.union(int(src_id), dst_id)

                processed += len(sub_ids)
                if self.params.max_recipes is not None and processed >= self.params.max_recipes:
                    for task in tasks:
                        task.cancel()
                    break

            self.last_id = max(ids)

            if reuse_dsu:
                self.save_dsu_state()
                logger.info("Processed %d recipes... (last_id=%s)", processed, self.last_id)

            if self.params.max_recipes is not None and processed >= self.params.max_recipes:
                break

        return build_clusters_from_dsu(self.dsu, self.params.min_cluster_size)
            
    
    def set_params(self, build_type: Literal["image", "full", "ingredients"] = "full"):
        """Кластеры по ингредиентам из Qdrant ingredients-коллекции."""
        if self.params is None:
            self.params = ClusterParams()
        if build_type == "image":
            self.params.collection_name = "images"
            self.params.using = "image"
        elif build_type == "ingredients":
            self.params.collection_name = "mv"
            self.params.using = "ingredients"
        else:  # full
            self.params.collection_name = "full"
            self.params.using = "dense"
    
    async def validate_cluster_density(
        self, 
        cluster: list[int], 
        q: QdrantRecipeManager,
        min_avg_similarity: float = 0.90
    ) -> tuple[float, list[int], Optional[int]]:
        """
        Проверяет плотность кластера и возвращает скорректированный кластер с удалёнными выбросами.
        
        Алгоритм:
        1. Вычисляем центроид кластера
        2. Удаляем элементы с похожестью к центроиду ниже порога
        3. Пересчитываем центроид и повторяем до стабилизации
        
        Args:
            cluster: список page_id рецептов в кластере
            q: QdrantRecipeManager для получения векторов
            min_avg_similarity: минимальный порог похожести с центроидом (default: 0.90)
            
        Returns:
            tuple[float, list[int], Optional[int]]: (средняя похожесть, скорректированный кластер, page_id ближайшего к центроиду)
        """
        if len(cluster) < 2:
            return 1.0, cluster, None
        
        # Получаем все векторы одним batch-запросом
        raw_vectors = await q.async_get_vectors(
            collection_name=self.params.collection_name,
            point_ids=cluster,
            using=self.params.using
        )
        
        # Нормализуем векторы и фильтруем None
        id_to_vec: dict[int, np.ndarray] = {}
        for page_id, vec in raw_vectors.items():
            if vec is not None:
                vec_np = np.array(vec, dtype=np.float32)
                norm = np.linalg.norm(vec_np)
                if norm > 0:
                    vec_np = vec_np / norm
                id_to_vec[page_id] = vec_np
        
        initial_count = len(id_to_vec)
        
        if initial_count < 2:
            logger.warning(f"Not enough vectors ({initial_count}) for cluster density validation")
            return 1.0, cluster, None
        
        # Итеративно удаляем выбросы
        max_iterations = 10
        for iteration in range(max_iterations):
            current_ids = list(id_to_vec.keys())
            if len(current_ids) < 2:
                break
            
            # Вычисляем центроид
            vectors = np.array([id_to_vec[pid] for pid in current_ids])
            centroid = np.mean(vectors, axis=0)
            centroid_norm = np.linalg.norm(centroid)
            if centroid_norm > 0:
                centroid = centroid / centroid_norm
            
            # Вычисляем похожесть каждого элемента с центроидом
            similarities = {
                pid: float(np.dot(id_to_vec[pid], centroid))
                for pid in current_ids
            }
            
            # Находим элементы ниже порога
            outliers = [pid for pid, sim in similarities.items() if sim < min_avg_similarity]
            
            if not outliers:
                # Нет выбросов - кластер стабилен
                break
            
            # Удаляем выбросы
            for pid in outliers:
                del id_to_vec[pid]
            
            logger.debug(
                f"Iteration {iteration + 1}: removed {len(outliers)} outliers, "
                f"remaining {len(id_to_vec)} elements"
            )
        
        # Финальная оценка
        final_ids = list(id_to_vec.keys())
        
        if len(final_ids) < 2:
            logger.warning(f"Cluster collapsed to {len(final_ids)} elements after density validation")
            return 0.0, final_ids, final_ids[0] if final_ids else None
        
        # Вычисляем финальную среднюю попарную похожесть
        vectors = np.array([id_to_vec[pid] for pid in final_ids])
        similarity_matrix = np.dot(vectors, vectors.T)
        n = len(final_ids)
        upper_indices = np.triu_indices(n, k=1)
        pairwise_similarities = similarity_matrix[upper_indices]
        
        avg_similarity = float(np.mean(pairwise_similarities))
        min_similarity = float(np.min(pairwise_similarities))
        
        removed_count = initial_count - len(final_ids)
        if removed_count > 0:
            logger.info(
                f"Cluster refined: {initial_count} → {len(final_ids)} elements "
                f"(removed {removed_count}), avg_sim={avg_similarity:.4f}, min_sim={min_similarity:.4f}"
            )
        else:
            logger.debug(
                f"Cluster OK: {len(final_ids)} elements, avg_sim={avg_similarity:.4f}, min_sim={min_similarity:.4f}"
            )

        # Вычисляем финальный центроид и находим ближайший к нему рецепт
        final_centroid = np.mean(vectors, axis=0)
        final_centroid_norm = np.linalg.norm(final_centroid)
        if final_centroid_norm > 0:
            final_centroid = final_centroid / final_centroid_norm
        
        # Находим page_id ближайшего к центроиду рецепта
        centroid_similarities = {
            pid: float(np.dot(id_to_vec[pid], final_centroid))
            for pid in final_ids
        }
        closest_to_centroid = max(centroid_similarities, key=centroid_similarities.get)
                    
        return avg_similarity, final_ids, closest_to_centroid

    async def split_cluster_by_density(
        self,
        cluster: list[int],
        q: QdrantRecipeManager,
        min_avg_similarity: float = 0.93,
        min_subcluster_size: int = 3
    ) -> list[tuple[list[int], int]]:
        """
        Разбивает кластер на подкластеры по плотности.
        
        Вместо удаления выбросов — группирует их в отдельные подкластеры.
        Использует попарную похожесть для построения графа связей.
        
        Args:
            cluster: список page_id рецептов в кластере
            q: QdrantRecipeManager для получения векторов
            min_avg_similarity: минимальная попарная похожесть для объединения (строже чем score_threshold)
            min_subcluster_size: минимальный размер подкластера
            
        Returns:
            Список кортежей (подкластер, page_id ближайшего к центроиду)
        """
        if len(cluster) < 2:
            return [(cluster, cluster[0])] if cluster else []
        
        # Получаем векторы
        raw_vectors = await q.async_get_vectors(
            collection_name=self.params.collection_name,
            point_ids=cluster,
            using=self.params.using
        )
        
        id_to_vec: dict[int, np.ndarray] = {}
        for page_id, vec in raw_vectors.items():
            if vec is not None:
                vec_np = np.array(vec, dtype=np.float32)
                norm = np.linalg.norm(vec_np)
                if norm > 0:
                    vec_np = vec_np / norm
                id_to_vec[page_id] = vec_np
        
        if len(id_to_vec) < 2:
            ids = list(id_to_vec.keys())
            return [(ids, ids[0])] if ids else []
        
        # Строим граф связей выше порога и объединяем через DSU
        ids = list(id_to_vec.keys())
        vectors = np.array([id_to_vec[pid] for pid in ids])
        similarity_matrix = np.dot(vectors, vectors.T)
        
        # Создаём локальный DSU для подкластеров
        sub_dsu = _DSU()
        
        n = len(ids)
        for i in range(n):
            sub_dsu.find(ids[i])  # инициализируем
            for j in range(i + 1, n):
                if similarity_matrix[i, j] >= min_avg_similarity:
                    sub_dsu.union(ids[i], ids[j])
        
        # Собираем подкластеры
        subclusters_raw = build_clusters_from_dsu(sub_dsu, min_cluster_size=min_subcluster_size)
        
        # Для каждого подкластера находим ближайший к центроиду элемент
        result: list[tuple[list[int], int]] = []
        clustered_ids = set()
        
        for sc in subclusters_raw:
            clustered_ids.update(sc)
            
            # Вычисляем центроид подкластера
            sc_vectors = np.array([id_to_vec[pid] for pid in sc])
            centroid = np.mean(sc_vectors, axis=0)
            centroid_norm = np.linalg.norm(centroid)
            if centroid_norm > 0:
                centroid = centroid / centroid_norm
            
            # Находим ближайший к центроиду
            sims = {pid: float(np.dot(id_to_vec[pid], centroid)) for pid in sc}
            closest = max(sims, key=sims.get)
            result.append((sc, closest))
        
        # Добавляем "сирот" (одиночные элементы) как отдельные кластеры если их достаточно
        orphans = [pid for pid in ids if pid not in clustered_ids]
        if orphans:
            # Пытаемся сгруппировать сирот между собой с более мягким порогом
            if len(orphans) >= min_subcluster_size:
                orphan_dsu = _DSU()
                orphan_vectors = np.array([id_to_vec[pid] for pid in orphans])
                orphan_sim_matrix = np.dot(orphan_vectors, orphan_vectors.T)
                
                # Используем чуть более мягкий порог для сирот
                softer_threshold = min_avg_similarity - 0.03
                for i, pid_i in enumerate(orphans):
                    orphan_dsu.find(pid_i)
                    for j, pid_j in enumerate(orphans[i+1:], i+1):
                        if orphan_sim_matrix[i, j] >= softer_threshold:
                            orphan_dsu.union(pid_i, pid_j)
                
                orphan_clusters = build_clusters_from_dsu(orphan_dsu, min_cluster_size=min_subcluster_size)
                for oc in orphan_clusters:
                    oc_vectors = np.array([id_to_vec[pid] for pid in oc])
                    centroid = np.mean(oc_vectors, axis=0)
                    centroid_norm = np.linalg.norm(centroid)
                    if centroid_norm > 0:
                        centroid = centroid / centroid_norm
                    sims = {pid: float(np.dot(id_to_vec[pid], centroid)) for pid in oc}
                    closest = max(sims, key=sims.get)
                    result.append((oc, closest))
        
        if len(result) > 1:
            logger.info(
                f"Cluster split: {len(cluster)} elements → {len(result)} subclusters "
                f"(sizes: {[len(sc) for sc, _ in result]})"
            )
        
        return result if result else [(cluster, cluster[0])]

    async def refine_clusters_with_split(
        self,
        clusters: list[list[int]],
        q: QdrantRecipeManager,
        min_cluster_size_for_validation: int | None = None,
        min_avg_similarity: float | None = None
    ) -> list[list[int]]:
        """
        Уточняет кластеры с возможностью разбиения на подкластеры.
        
        В отличие не удаляет выбросы, а группирует их 
        в отдельные подкластеры. Это позволяет не терять рецепты.
        
        Args:
            clusters: список кластеров для проверки
            q: QdrantRecipeManager
            min_cluster_size_for_validation: валидировать только кластеры >= этого размера
            min_avg_similarity: порог попарной похожести для разбиения (строже чем score_threshold)
            
        Returns:
            список уточнённых кластеров (может быть больше исходного!)
        """
        if min_cluster_size_for_validation is None:
            min_cluster_size_for_validation = self.params.min_cluster_size_for_validation
        if min_avg_similarity is None:
            min_avg_similarity = self.params.density_min_similarity
        
        refined = []
        skipped = 0
        split_count = 0
        
        # Очищаем старые центроиды перед новой валидацией
        self.validated_centroids.clear()
        
        for cluster in clusters:
            cluster_key = ','.join(map(str, sorted(cluster)))
            # Маленькие кластеры пропускаем без проверки
            if len(cluster) < min_cluster_size_for_validation:
                self.validated_centroids[cluster_key] = cluster[0]
                refined.append(cluster)
                skipped += 1
                continue
            
            # Разбиваем на подкластеры вместо удаления выбросов
            subclusters = await self.split_cluster_by_density(
                cluster=cluster,
                q=q,
                min_avg_similarity=min_avg_similarity,
                min_subcluster_size=self.params.min_cluster_size
            )
            
            if len(subclusters) > 1:
                split_count += 1
            
            for subcluster, closest_to_centroid in subclusters:
                if len(subcluster) >= self.params.min_cluster_size:
                    subcluster_key = ','.join(map(str, sorted(subcluster)))
                    self.validated_centroids[subcluster_key] = closest_to_centroid
                    refined.append(subcluster)
        
        logger.info(
            f"Cluster refinement with split: {len(clusters)} → {len(refined)} clusters, "
            f"skipped={skipped}, split={split_count}, centroids_saved={len(self.validated_centroids)}"
        )
        
        # Сохраняем центроиды в файл
        if self.validated_centroids:
            self.save_validated_centroids()
        
        return refined
    
    async def refine_clusters(
        self, 
        clusters: list[list[int]], 
        q: QdrantRecipeManager,
        min_cluster_size_for_validation: int | None = None,
        min_avg_similarity: float | None = None
    ) -> list[list[int]]:
        """
        Уточняет кластеры, валидируя только большие.
        
        Args:
            clusters: список кластеров для проверки
            q: QdrantRecipeManager
            min_cluster_size_for_validation: валидировать только кластеры >= этого размера (default: берётся из self.params)
            min_avg_similarity: порог похожести для validate_cluster_density (default: берётся из self.params)
            
        Returns:
            список уточнённых кластеров
        """
        # Используем параметры из ClusterParams если не переданы явно
        if min_cluster_size_for_validation is None:
            min_cluster_size_for_validation = self.params.min_cluster_size_for_validation
        if min_avg_similarity is None:
            min_avg_similarity = self.params.density_min_similarity
        
        refined = []
        skipped = 0
        validated = 0
        removed_total = 0
        
        # Очищаем старые центроиды перед новой валидацией
        self.validated_centroids.clear()
        
        for cluster in clusters:
            cluster_key = ','.join(map(str, sorted(cluster)))
            # Маленькие кластеры пропускаем без проверки
            if len(cluster) < min_cluster_size_for_validation:
                # Для невалидированных кластеров берём первый элемент как "центроид"
                self.validated_centroids[cluster_key] = cluster[0]
                refined.append(cluster)
                skipped += 1
                continue
            
            # Большие кластеры валидируем
            validated += 1
            avg_sim, refined_cluster, closest_to_centroid = await self.validate_cluster_density(
                cluster=cluster,
                q=q,
                min_avg_similarity=min_avg_similarity
            )
            
            removed_count = len(cluster) - len(refined_cluster)
            removed_total += removed_count
            
            if len(refined_cluster) >= self.params.min_cluster_size:
                # Сохраняем page_id ближайшего к центроиду рецепта (индекс в refined)
                self.validated_centroids[cluster_key] = closest_to_centroid if closest_to_centroid else refined_cluster[0]
                refined.append(refined_cluster)
                
                # Если кластер сильно уменьшился — логируем
                if removed_count > 0 and len(refined_cluster) < len(cluster) * 0.7:
                    logger.warning(
                        f"Cluster significantly reduced: {len(cluster)} → {len(refined_cluster)} "
                        f"(avg_sim={avg_sim:.4f})"
                    )
            else:
                logger.warning(
                    f"Cluster dropped after validation: {len(cluster)} → {len(refined_cluster)} "
                    f"(below min_cluster_size={self.params.min_cluster_size})"
                )
        
        logger.info(
            f"Cluster refinement complete: {len(clusters)} → {len(refined)} clusters, "
            f"skipped={skipped}, validated={validated}, removed_elements={removed_total}, "
            f"centroids_saved={len(self.validated_centroids)}"
        )
        
        # Сохраняем центроиды в файл
        if self.validated_centroids:
            self.save_validated_centroids()
        
        return refined
    
    def load_clusters_from_file(self) -> list[list[int]]:
        """Загружает кластеры из файла в формате JSON."""
        with open(self.clusters_filename, 'r') as f:
            clusters = json.load(f)
        return clusters
    
    def get_image_clusters_mapping(self) -> dict[str, dict[str, list[int]]]:
        """Загружает маппинг кластеров рецептов к изображениям из файла."""
        if not os.path.exists(self.cluter_image_mapping):
            logger.warning(f"Cluster to image mapping file {self.cluter_image_mapping} not found.")
            return {}
        
        with open(self.cluter_image_mapping, 'r') as f:
            page_ids_to_image_ids = json.load(f)
        
        return page_ids_to_image_ids
        
    async def save_clusters_to_file(
        self, 
        clusters: list[list[int]], 
        recalculate_mapping: bool = False, 
        refine_clusters: bool = False,
        refine_mode: Literal["trim", "split"] = "trim"
    ) -> None:
        """Сохраняет текущие кластеры в файл в формате JSON.
        
        Args:
            clusters: список кластеров для сохранения
            recalculate_mapping: пересчитать маппинг image_id -> page_id
            refine_clusters: применить уточнение кластеров
            refine_mode: режим уточнения:
                - "trim": удалять выбросы (refine_clusters)
                - "split": разбивать на подкластеры без потери рецептов (refine_clusters_with_split)
        """
        # конвертируем кластеры из изображений в кластеры по ID рецептов
        if self.build_type == "image":
            if not os.path.exists(self.cluter_image_mapping) or recalculate_mapping:
                page_ids_to_image_ids = {"image_to_page": {}, "page_to_image": {}}
                recipe_clisters = []
                for image_ids in clusters:
                    image_ids = sorted(image_ids)
                    page_ids = sorted(self.image_repository.get_page_ids_by_image_ids(image_ids))
                    if len(page_ids) < 2: # пропускаем одиночки
                        continue
                    recipe_clisters.append(page_ids)
                    page_ids_to_image_ids['page_to_image'][','.join(map(str, page_ids))] = image_ids
                    page_ids_to_image_ids['image_to_page'][','.join(map(str, image_ids))] = page_ids

                # сохраняем маппинг кластеров рецептов к изображениям
                async with aiofiles.open(self.cluter_image_mapping, 'w') as f:
                    await f.write(json.dumps(page_ids_to_image_ids, indent=2))
                logger.info(f"Saved clusters to image IDs mapping to file {self.cluter_image_mapping}.")
            else:
                async with aiofiles.open(self.cluter_image_mapping, 'r') as f:
                    page_ids_to_image_ids = json.loads(await f.read())
                recipe_clisters = []
                for image_ids in clusters:
                    image_ids = sorted(image_ids)
                    page_ids = page_ids_to_image_ids['image_to_page'].get(','.join(map(str, image_ids)), [])
                    page_ids = list(map(int, page_ids))
                    recipe_clisters.append(page_ids)
                
            clusters = recipe_clisters
            # поуллчаем 
        
        if refine_clusters:
            q = QdrantRecipeManager(collection_prefix=self.qd_collection_prefix)
            await q.async_connect(connect_timeout=210)
            
            if refine_mode == "split":
                # Разбиение на подкластеры — не теряем рецепты
                clusters = await self.refine_clusters_with_split(clusters=clusters, q=q)
            else:
                # Удаление выбросов — строгая очистка
                clusters = await self.refine_clusters(clusters=clusters, q=q)

        async with aiofiles.open(self.clusters_filename, 'w') as f:
            await f.write(json.dumps(clusters, indent=2))
        logger.info(f"Saved clusters to file {self.clusters_filename}.")

if __name__ == "__main__":
    while True:
        ss = SimilaritySearcher(params=ClusterParams(
                    limit=50,
                    score_threshold=0.88,
                    scroll_batch=3500,
                    centroid_threshold=0.91,
                    min_cluster_size=4,
                    use_centroid_check=True,
                    union_top_k=20,
                    query_batch=128,
                    density_min_similarity=0.9,
                    adaptive_max_threshold=0.97,
                    adaptive_min_cluster_size=15,
                    max_async_tasks=15,
                ), build_type="full") # "image", "full", "ingredients"
        try:
            ss.load_dsu_state()
            last_id = ss.last_id # получаем last id после загрузки состояния (такая штука работает только опираясь на тот факт, что каждй вновь доавбленный рецепт имеет id не меньше уже векторизованных рецептов, иначе рецепты могут быть пропущены)
            clusters = asyncio.run(ss.build_clusters_async())
            ss.save_dsu_state()
            print(f"Total clusters found: {len(clusters)}")
            print("Last processed ID:", ss.last_id)
            asyncio.run(ss.save_clusters_to_file(clusters))
            if last_id == ss.last_id: # конец обработки тк id не поменялся, значи новых значений нет
                logger.info("Processing complete.")
                break
        except Exception as e:
            logger.error(f"Error during cluster building: {e}")
            continue

    final_clusters = build_clusters_from_dsu(ss.dsu, min_cluster_size=4)
    # refine_mode="split" — разбивает на подкластеры без потери рецептов
    # refine_mode="trim" — удаляет выбросы (строже)
    asyncio.run(ss.save_clusters_to_file(final_clusters, recalculate_mapping=True, refine_clusters=True, refine_mode="split"))