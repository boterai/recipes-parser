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
from src.repositories.cluster_page import ClusterPageRepository
from itertools import batched

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
        repo = ClusterPageRepository()


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
    
    # Параметры проверки центроида (отключены для уменьшения размера файлов DSU)
    centroid_threshold: float = 0.9      # минимальная похожесть с центроидом для объединения (только если use_centroid_check=True)
        
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
        state = {
            "parent": self.dsu.parent,
            "rank": self.dsu.rank,
            "last_id": self.last_id
        }
        with open(self.dsu_filename, 'w') as f:
            json.dump(state, f, indent=2)
        logger.info(f"Saved DSU state to {self.dsu_filename} (last_id={self.last_id})")

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
        
        logger.info(f"Loaded DSU state from {self.dsu_filename} (last_id={self.last_id}, nodes={len(self.dsu.parent)})")

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

    def save_validated_centroids_to_databsae(self, batch_size: int = 10) -> None:
        """Сохраняет валидированные центроиды в базу данных (таблица cluster_page)"""
        if not self.validated_centroids:
            logger.warning("No validated centroids to save to database")
            return
        repo = ClusterPageRepository()
        # Подготовка данных для batch вставки
        clusters_to_save: dict[int, list[int]] = {}
        for batch in batched(self.validated_centroids.items(), batch_size):
            for cluster_idx, centroid_page_id in batch:
                clusters_to_save[centroid_page_id] = [int(i) for i in cluster_idx.split(",")]  # предполагая, что cluster_idx - это строка с page_id через запятую
            try:
                repo.add_cluster_pages_batch(clusters_to_save)
            except Exception as e:
                logger.error(f"Error preparing batch for database insertion, trying to load one by one: {e}")
                for centroid_page_id, cluster in clusters_to_save.items():
                    try:
                        repo.add_cluster_pages_batch({centroid_page_id: cluster}) 
                    except Exception as e_inner:
                        logger.error(f"Failed to save centroid {centroid_page_id} to database: {e_inner}")

            clusters_to_save = {}

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Вычисляет косинусную похожесть между двумя векторами."""
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(vec1, vec2) / (norm1 * norm2))


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

                # union только top-K (без проверки центроидов для уменьшения размера DSU)
                for src_id, hits in zip(sub_ids, batch_hits):
                    if not hits:
                        continue
                    
                    top_hits = hits[:self.params.union_top_k] if self.params.union_top_k else hits
                    for dst_id in top_hits:
                        if dst_id == src_id:
                            continue
                        
                        # Простой union без проверки центроидов
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
    

    def _build_dsu_chunked(
        self,
        ids: list[int],
        id_to_vec: dict[int, np.ndarray],
        threshold: float,
        chunk_size: int = 1000
    ) -> _DSU:
        """
        Строит DSU по попарной похожести, обрабатывая матрицу чанками.
        
        Вместо создания полной N×N матрицы, вычисляет похожести блоками,
        что позволяет обрабатывать большие кластеры без переполнения памяти.
        
        Args:
            ids: список ID элементов
            id_to_vec: словарь ID -> нормализованный вектор
            threshold: порог похожести для объединения
            chunk_size: размер чанка (по умолчанию 1000 — матрица 1000×1000 ≈ 4MB)
            
        Returns:
            _DSU с построенными связями
        """
        sub_dsu = _DSU()
        n = len(ids)
        
        # Инициализируем все элементы в DSU
        for pid in ids:
            sub_dsu.find(pid)
        
        # Собираем векторы в numpy array для эффективного вычисления
        vectors = np.array([id_to_vec[pid] for pid in ids], dtype=np.float32)
        
        # Обрабатываем матрицу похожести чанками
        for i_start in range(0, n, chunk_size):
            i_end = min(i_start + chunk_size, n)
            chunk_i = vectors[i_start:i_end]
            
            # Для верхнетреугольной части: j >= i_start
            for j_start in range(i_start, n, chunk_size):
                j_end = min(j_start + chunk_size, n)
                chunk_j = vectors[j_start:j_end]
                
                # Вычисляем блок матрицы похожести
                sim_block = np.dot(chunk_i, chunk_j.T)
                
                # Находим пары выше порога
                for local_i in range(sim_block.shape[0]):
                    global_i = i_start + local_i
                    
                    # Определяем начальный j чтобы избежать дублирования (j > i)
                    if j_start == i_start:
                        local_j_start = local_i + 1
                    else:
                        local_j_start = 0
                    
                    for local_j in range(local_j_start, sim_block.shape[1]):
                        global_j = j_start + local_j
                        
                        if global_j <= global_i:
                            continue
                        
                        if sim_block[local_i, local_j] >= threshold:
                            sub_dsu.union(ids[global_i], ids[global_j])
        
        return sub_dsu

    async def split_cluster_by_density(
        self,
        cluster: list[int],
        q: QdrantRecipeManager,
        min_avg_similarity: float = 0.93,
        min_subcluster_size: int = 3,
        chunk_size: int = 1000
    ) -> list[tuple[list[int], int]]:
        """
        Разбивает кластер на подкластеры по плотности.
        
        Вместо удаления выбросов — группирует их в отдельные подкластеры.
        Использует попарную похожесть для построения графа связей.
        Оптимизирован для больших кластеров через чанковую обработку.
        
        Args:
            cluster: список page_id рецептов в кластере
            q: QdrantRecipeManager для получения векторов
            min_avg_similarity: минимальная попарная похожесть для объединения (строже чем score_threshold)
            min_subcluster_size: минимальный размер подкластера
            chunk_size: размер чанка для матричных операций (меньше = меньше памяти)
            
        Returns:
            Список кортежей (подкластер, page_id ближайшего к центроиду)
        """
        if len(cluster) < 2:
            return [(cluster, cluster[0])] if cluster else []
        
        # Получаем векторы батчами для очень больших кластеров
        batch_size = 500
        id_to_vec: dict[int, np.ndarray] = {}
        
        for batch_start in range(0, len(cluster), batch_size):
            batch_ids = cluster[batch_start:batch_start + batch_size]
            raw_vectors = await q.async_get_vectors(
                collection_name=self.params.collection_name,
                point_ids=batch_ids,
                using=self.params.using
            )
            
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
        
        ids = list(id_to_vec.keys())
        n = len(ids)
        
        # Для больших кластеров используем чанковую обработку
        if n > chunk_size:
            logger.debug(f"Large cluster ({n} elements), using chunked processing with chunk_size={chunk_size}")
        
        # Строим DSU чанками
        sub_dsu = self._build_dsu_chunked(ids, id_to_vec, min_avg_similarity, chunk_size)
        
        # Собираем подкластеры
        subclusters_raw = build_clusters_from_dsu(sub_dsu, min_cluster_size=min_subcluster_size)
        
        # Для каждого подкластера находим ближайший к центроиду элемент
        result: list[tuple[list[int], int]] = []
        clustered_ids = set()
        
        for sc in subclusters_raw:
            clustered_ids.update(sc)
            
            # Вычисляем центроид подкластера
            sc_vectors = np.array([id_to_vec[pid] for pid in sc], dtype=np.float32)
            centroid = np.mean(sc_vectors, axis=0)
            centroid_norm = np.linalg.norm(centroid)
            if centroid_norm > 0:
                centroid = centroid / centroid_norm
            
            # Находим ближайший к центроиду
            sims = {pid: float(np.dot(id_to_vec[pid], centroid)) for pid in sc}
            closest = max(sims, key=sims.get)
            result.append((sc, closest))
        
        # Добавляем "сирот" как отдельные кластеры если их достаточно
        orphans = [pid for pid in ids if pid not in clustered_ids]
        if orphans and len(orphans) >= min_subcluster_size:
            # Используем чуть более мягкий порог для сирот
            softer_threshold = min_avg_similarity - 0.03
            orphan_dsu = self._build_dsu_chunked(orphans, id_to_vec, softer_threshold, chunk_size)
            
            orphan_clusters = build_clusters_from_dsu(orphan_dsu, min_cluster_size=min_subcluster_size)
            for oc in orphan_clusters:
                oc_vectors = np.array([id_to_vec[pid] for pid in oc], dtype=np.float32)
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
        refine_clusters: bool = False
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

            clusters = await self.refine_clusters_with_split(clusters=clusters, q=q)

        async with aiofiles.open(self.clusters_filename, 'w') as f:
            await f.write(json.dumps(clusters, indent=2))
        logger.info(f"Saved clusters to file {self.clusters_filename}.")

if __name__ == "__main__":
    while True:
        ss = SimilaritySearcher(params=ClusterParams(
                    limit=40,
                    score_threshold=0.92,
                    scroll_batch=3500,
                    centroid_threshold=0.93,
                    min_cluster_size=4,
                    union_top_k=20,
                    query_batch=128,
                    density_min_similarity=0.9,
                    max_async_tasks=15,
                ), build_type="full") # "image", "full", "ingredients"
        try:
            ss.load_dsu_state()
            last_id = ss.last_id # получаем last id после загрузки состояния (такая штука работает только опираясь на тот факт, что каждй вновь доавбленный рецепт имеет id не меньше уже векторизованных рецептов, иначе рецепты могут быть пропущены)
            clusters = asyncio.run(ss.build_clusters_async())
            ss.save_dsu_state()
            print(f"Total clusters found: {len(clusters)}")
            print("Last processed ID:", ss.last_id)
            # Центроиды вычисляются локально в методах валидации
            asyncio.run(ss.save_clusters_to_file(clusters))
            if last_id == ss.last_id: # конец обработки тк id не поменялся, значи новых значений нет
                logger.info("Processing complete.")
                break
        except Exception as e:
            logger.error(f"Error during cluster building: {e}")
            continue

    final_clusters = build_clusters_from_dsu(ss.dsu, min_cluster_size=4)
    asyncio.run(ss.save_clusters_to_file(final_clusters, recalculate_mapping=True, refine_clusters=True))
    ss.save_validated_centroids_to_databsae()