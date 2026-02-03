"""модуль для поиска и отметки рецептов как похожих"""

from __future__ import annotations
import json
import logging
import random
from dataclasses import dataclass
from typing import Optional, Literal
import os
import asyncio

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

    def find(self, x: int) -> int:
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
            return x
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


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
    score_threshold: float = 0.92 # порог
    scroll_batch: int = 1000      # чтение ids из Qdrant
    query_batch: int = 64        # сколько векторов в batch query
    min_cluster_size: int = 2     # отбрасывать одиночки

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
        self.clusters_filename = os.path.join("recipe_clusters", f"{build_type}_clusters_{self.params.score_threshold}.json")
        self.cluter_image_mapping = os.path.join("recipe_clusters", f"clusters_to_image_ids_{self.params.score_threshold}.json")
        self.build_type = build_type

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
                    
                    top_hits = hits[:self.params.union_top_k] if self.params.union_top_k else hits
                    for dst_id in top_hits:
                        if dst_id != src_id:
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
        
    
    def load_clusters_from_file(self) -> list[list[int]]:
        """Загружает кластеры из файла в формате JSON."""
        with open(self.clusters_filename, 'r') as f:
            clusters = json.load(f)
        return clusters

    def is_cluster_present(self, cluster: list[int]) -> bool:
        if self.similarity_repository.find_cluster_by_exact_members(cluster) is None:
            logger.info(f"Cluster with pages {cluster} is not present in DB.")
            return False
        logger.info(f"Cluster with pages {cluster} is already present in DB.")
        return True
    
    def ask_chatgpt_about_cluster(self, cluster: list[int]) -> list[int]:
        """Анализирует кластер рецептов через GPT и возвращает список ID действительно похожих блюд.
        
        Args:
            cluster: список page_id рецептов в кластере
            
        Returns:
            список page_id рецептов, которые GPT определил как одинаковые/похожие блюда
        """
        MAX_RECIPES_PER_REQUEST = 15  # Ограничение на размер кластера для одного запроса к GPT
        
        recipes: list[Recipe] = self.clickhouse_manager.get_recipes_by_ids(cluster)
        
        if not recipes:
            logger.warning(f"No recipes found for cluster {cluster}")
            return []
        
        # Если кластер слишком большой - берём первые N рецептов или разбиваем на части
        if len(recipes) > MAX_RECIPES_PER_REQUEST:
            logger.warning(f"Cluster too large ({len(recipes)} recipes), taking first {MAX_RECIPES_PER_REQUEST}")
            recipes = recipes[:MAX_RECIPES_PER_REQUEST]
        
        # Формируем данные для GPT: только ключевые поля
        recipes_data = []
        for recipe in recipes:
            recipes_data.append({
                "id": recipe.page_id,
                "dish_name": recipe.dish_name,
                "ingredients": recipe.ingredients[:20] if recipe.ingredients else [],  # ограничиваем количество ингредиентов
                "instructions": recipe.instructions[:500] if recipe.instructions else ""  # обрезаем длинные инструкции
            })
        
        system_prompt = """You are a recipe similarity expert. Your task is to analyze a group of recipes and determine which ones represent the EXACT SAME DISH with only minimal variations.

Compare recipes based on:
1. Dish name - must refer to the same dish (e.g., "Chocolate Cake" vs "Šokoladinis tortas" are OK, but "Chocolate Cake" vs "Brownie" are different dishes)
2. Ingredients - core ingredients must be identical. Minor differences in quantities, optional ingredients, or garnish are acceptable, but substituting main ingredients means different dishes
3. Instructions - cooking method must be essentially the same. Different techniques (baking vs frying, grilling vs roasting) mean different dishes

Be STRICT: Only group recipes that are clearly the same dish. Different dishes (even if similar category) should be excluded.

Examples of SAME dish: "Italian Tiramisu", "Tiramisu Classico", "Classic Tiramisu Recipe"
Examples of DIFFERENT dishes: "Tiramisu" vs "Panna Cotta", "Grilled Chicken" vs "Fried Chicken", "Beef Stew" vs "Beef Curry"

CRITICAL: Return ONLY valid JSON array of integers, no markdown, no explanation. Example: [1, 5, 23]"""

        user_prompt = f"""Analyze these recipes and return IDs of those that are the SAME or VERY SIMILAR dishes:

{json.dumps(recipes_data, indent=2, ensure_ascii=False)}

Return ONLY JSON array of IDs representing similar recipes."""

        try:
            result = self.gpt_client.request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
                max_tokens=500,
                timeout=60
            )
            
            # GPT должен вернуть массив целых чисел
            if isinstance(result, list):
                similar_ids = [int(rid) for rid in result if isinstance(rid, (int, str)) and str(rid).isdigit()]
                logger.info(f"GPT identified {len(similar_ids)}/{len(recipes)} recipes as similar in cluster")
                return similar_ids
            else:
                logger.error(f"Unexpected GPT response format: {type(result)}")
                return []
                
        except Exception as e:
            logger.error(f"Error calling GPT for cluster analysis: {e}")
            return []
        
    def process_and_save_clusters(self, clusters: list[list[int]]) -> None:
        """
        processes loaded clusters, asks GPT to filter them, and saves to DB, skips already saved clusters.
        """
        if not clusters:
            logger.warning("No clusters to process.")
            return
        
        for num, cluster in enumerate(clusters):
            if self.is_cluster_present(cluster):
                continue
            similar_clusters = self.ask_chatgpt_about_cluster(cluster)
            if set(similar_clusters) != set(cluster):
                clusters[num] = similar_clusters
                if self.clusters_filename:
                    # Обновляем файл кластеров после любого обновления, чтобы не терять прогресс
                    with open(self.clusters_filename, 'w') as f:
                        f.write(json.dumps(clusters, indent=2))
                    logger.info(f"Updated cluster file {self.clusters_filename} after GPT filtering.")
            
            if not similar_clusters:
                logger.info("Skipping empty cluster after GPT filtering.")
                continue
            
            self.similarity_repository.save_cluster_with_members(similar_clusters)
            logger.info(f"Saved cluster {num + 1}/{len(clusters)} with {len(similar_clusters)} members.")

    def get_image_clusters_mapping(self) -> dict[str, dict[str, list[int]]]:
        """Загружает маппинг кластеров рецептов к изображениям из файла."""
        if not os.path.exists(self.cluter_image_mapping):
            logger.warning(f"Cluster to image mapping file {self.cluter_image_mapping} not found.")
            return {}
        
        with open(self.cluter_image_mapping, 'r') as f:
            page_ids_to_image_ids = json.load(f)
        
        return page_ids_to_image_ids
        
    def save_clusters_to_file(self, clusters: list[list[int]]) -> None:
        """Сохраняет текущие кластеры в файл в формате JSON."""
        # конвертируем кластеры из изображений в кластеры по ID рецептов
        if self.build_type == "image":
            if not os.path.exists(self.cluter_image_mapping):
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
                with open(self.cluter_image_mapping, 'w') as f:
                    f.write(json.dumps(page_ids_to_image_ids, indent=2))
                logger.info(f"Saved clusters to image IDs mapping to file {self.cluter_image_mapping}.")
            else:
                with open(self.cluter_image_mapping, 'r') as f:
                    page_ids_to_image_ids = json.load(f)
                recipe_clisters = []
                for image_ids in clusters:
                    image_ids = sorted(image_ids)
                    page_ids = page_ids_to_image_ids['image_to_page'].get(','.join(map(str, image_ids)), [])
                    page_ids = list(map(int, page_ids))
                    recipe_clisters.append(page_ids)
                
            clusters = recipe_clisters
            # поуллчаем 
        with open(self.clusters_filename, 'w') as f:
            f.write(json.dumps(clusters, indent=2))
        logger.info(f"Saved clusters to file {self.clusters_filename}.")

if __name__ == "__main__":

    while True:
        ss = SimilaritySearcher(params=ClusterParams(
                    limit=30,
                    score_threshold=0.93,
                    scroll_batch=1000,
                    union_top_k=7,
                    query_batch=128
                ), build_type="full") # "image", "full", "ingredients"
        try:
            ss.load_dsu_state()
            last_id = ss.last_id # получаем last id после загрузки состояния (такая штука работает только опираясь на тот факт, что каждй вновь доавбленный рецепт имеет id не меньше уже векторизованных рецептов, иначе рецепты могут быть пропущены)
            clusters = asyncio.run(ss.build_clusters_async())
            ss.save_dsu_state()
            print(f"Total clusters found: {len(clusters)}")
            print("Last processed ID:", ss.last_id)
            ss.save_clusters_to_file(clusters)
            if last_id == ss.last_id: # конец обработки тк id не поменялся, значи новых значений нет
                logger.info("Processing complete.")
                break
        except Exception as e:
            logger.error(f"Error during cluster building: {e}")
            ss.save_dsu_state()
            continue

    final_clusters = build_clusters_from_dsu(ss.dsu, min_cluster_size=2)
    ss.save_clusters_to_file(final_clusters)