"""модуль для поиска и отметки рецептов как похожих"""

from __future__ import annotations
import json
import logging
import random
from dataclasses import dataclass, field
from typing import Optional

if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.common.db.qdrant import QdrantRecipeManager
from src.common.gpt_client import GPTClient
from src.repositories.similarity import RecipeSimilarity
from src.models.recipe import Recipe
from src.common.db.clickhouse import ClickHouseManager

logger = logging.getLogger(__name__)


class SimilaritySearchType:
    FULL_TEXT = 'full_text'
    WEIGHTED = 'weighted'
    INGREDIENTS = 'ingredients'
    IMAGE = 'image'


class SimilarityMetric:
    COSINE = 'cosine'
    DOT = 'dot'
    EUCLID = 'euclid'


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


def _build_clusters_from_dsu(dsu: _DSU, min_cluster_size: int) -> list[list[int]]:
    groups: dict[int, list[int]] = {}
    for node in dsu.parent.keys():
        root = dsu.find(node)
        groups.setdefault(root, []).append(node)

    clusters = [sorted(m) for m in groups.values() if len(m) >= min_cluster_size]
    clusters.sort(key=lambda c: (-len(c), c[0]))
    return clusters


def _apply_sampling_and_limits(
    ids: list[int],
    *,
    rng: random.Random,
    processed: int,
    max_recipes: int | None,
    sample_per_scroll_batch: int | None,
) -> list[int]:
    if sample_per_scroll_batch is not None and len(ids) > sample_per_scroll_batch:
        ids = rng.sample(ids, sample_per_scroll_batch)

    if max_recipes is None:
        return ids

    remaining = max_recipes - processed
    if remaining <= 0:
        return []
    if len(ids) > remaining:
        ids = ids[:remaining]
    return ids


def _normalize_mv_weights(
    components: list[str],
    component_weights: dict[str, float],
) -> tuple[list[str], dict[str, float]]:
    components = [c for c in components if c]
    if not components:
        raise ValueError("components is empty")

    if not component_weights:
        w = 1.0 / float(len(components))
        return components, dict.fromkeys(components, w)

    weights = {c: float(component_weights.get(c, 0.0)) for c in components}
    weights = {c: w for c, w in weights.items() if w > 0.0}
    if not weights:
        raise ValueError("component_weights resulted in all-zero weights")
    return list(weights.keys()), weights


def _merge_component_hits(
    *,
    aggregated: dict[int, dict[int, float]],
    src_ids: list[int],
    hits_per_src: list[list[dict[str, float]]],
    weight: float,
) -> None:
    for sid, hits in zip(src_ids, hits_per_src):
        score_map = aggregated.get(sid)
        if score_map is None:
            continue
        for h in hits:
            dst_id = int(h["recipe_id"])
            if dst_id == sid:
                continue
            score_map[dst_id] = score_map.get(dst_id, 0.0) + float(h["score"]) * weight


def _union_top_neighbors(dsu: _DSU, aggregated: dict[int, dict[int, float]], limit: int) -> None:
    for sid, score_map in aggregated.items():
        if not score_map:
            continue
        top = sorted(score_map.items(), key=lambda x: x[1], reverse=True)[:limit]
        for dst_id, _ in top:
            dsu.union(int(sid), int(dst_id))


@dataclass(frozen=True)
class ClusterParams:
    limit: int = 25               # top-K соседей на рецепт
    score_threshold: float = 0.92 # порог
    scroll_batch: int = 1000      # чтение ids из Qdrant
    query_batch: int = 64        # сколько векторов в batch query
    min_cluster_size: int = 2     # отбрасывать одиночки

    # параметры коллекции Qdrant
    collection_name: str = "full"
    using: str = "dense"

    # weighted-mv параметры: делаем несколько запросов (по компонентам) и сливаем результаты
    components: list[str] = field(default_factory=lambda: [
        "ingredients",
        "description",
        "instructions",
        "dish_name",
        "tags",
        "meta",
    ])
    component_weights: dict[str, float] = field(default_factory=dict)
    candidate_multiplier: int = 3  # сколько кандидатов брать с каждого компонента (limit * multiplier)

    # Ограничение выборки (для тестового прогона)
    max_recipes: int | None = None              # обработать не больше N рецептов всего
    sample_per_scroll_batch: int | None = None  # случайно взять N ids из каждого scroll батча
    sample_seed: int = 42                       # seed для воспроизводимой выборки


class SimilaritySearcher:
    def __init__(self):
        self.qd_collection_prefix = "recipes"
        self.gpt_client: GPTClient = GPTClient()
        self.similarity_repository = RecipeSimilarity()
        self.clickhouse_manager = ClickHouseManager()
        if not self.clickhouse_manager.connect(): # перенести куда-нибудь не сюда или не использвоать тут clickhuouse
            raise RuntimeError("Failed to connect to ClickHouse")
        self.clusters = []
        self.cluster_filepath = None

    def build_full_text_clusters_via_qdrant(
        self,
        params: ClusterParams = ClusterParams()
    ) -> list[list[int]]:
        """
        Кластеры по full_text из Qdrant full-коллекции.
        Предпосылка: point_id в Qdrant == pages.id, и named vector = 'dense'.
        """

        q = QdrantRecipeManager(collection_prefix=self.qd_collection_prefix)
        q.connect(timeout=120.0) # увеличенный таймаут для долгих операций

        dsu = _DSU()
        processed = 0
        rng = random.Random(params.sample_seed)

        collection_name = params.collection_name or "full"
        using = params.using or "dense"

        for ids in q.iter_point_ids(batch_size=params.scroll_batch, collection_name=collection_name):
            ids = _apply_sampling_and_limits(
                ids,
                rng=rng,
                processed=processed,
                max_recipes=params.max_recipes,
                sample_per_scroll_batch=params.sample_per_scroll_batch,
            )
            if not ids:
                break

            for i in range(0, len(ids), params.query_batch):
                sub_ids = ids[i:i + params.query_batch]
                vec_map = q.retrieve_vectors(sub_ids, collection_name=collection_name, using=using)
                if not vec_map:
                    continue

                src_ids = list(vec_map.keys())
                vectors = [vec_map[rid] for rid in src_ids]

                batch_hits = q.query_batch(
                    collection_name=collection_name,
                    using=using,
                    vectors=vectors,
                    limit=params.limit,
                    score_threshold=params.score_threshold,
                )

                for src_id, hits in zip(src_ids, batch_hits):
                    for h in hits:
                        dst_id = int(h["recipe_id"])
                        if dst_id != src_id:
                            dsu.union(src_id, dst_id)

                processed += len(src_ids)
                if params.max_recipes is not None and processed >= params.max_recipes:
                    break

            logger.info("Processed %d recipes...", processed)
            if params.max_recipes is not None and processed >= params.max_recipes:
                break
        
        self.clusters = _build_clusters_from_dsu(dsu, params.min_cluster_size)
        return self.clusters

    def build_weighted_mv_clusters_via_qdrant(
        self,
        params: ClusterParams = ClusterParams()
    ) -> list[list[int]]:
        """Кластеры по multivector: делаем несколько kNN запросов (по компонентам) и сливаем score.

        Важно:
        - `params.collection_name` должен быть "mv" (по умолчанию)
        - `params.using` игнорируется
        - `params.components` определяет, по каким named-векторам искать
        - `params.component_weights` если пустой, используется равномерное распределение по components
        """

        q = QdrantRecipeManager(collection_prefix=self.qd_collection_prefix)
        q.connect()

        dsu = _DSU()
        processed = 0
        rng = random.Random(params.sample_seed)

        collection_name = params.collection_name or "mv"
        components, weights = _normalize_mv_weights(params.components, params.component_weights)
        search_limit = max(1, int(params.limit) * max(1, int(params.candidate_multiplier)))

        for ids in q.iter_point_ids(batch_size=params.scroll_batch, collection_name=collection_name):
            ids = _apply_sampling_and_limits(
                ids,
                rng=rng,
                processed=processed,
                max_recipes=params.max_recipes,
                sample_per_scroll_batch=params.sample_per_scroll_batch,
            )
            if not ids:
                break

            for i in range(0, len(ids), params.query_batch):
                sub_ids = ids[i:i + params.query_batch]

                vecs_by_id = q.retrieve_vectors_multi(
                    sub_ids,
                    collection_name=collection_name,
                    using_list=components,
                )
                if not vecs_by_id:
                    continue

                src_ids = list(vecs_by_id.keys())
                aggregated: dict[int, dict[int, float]] = {sid: {} for sid in src_ids}

                for comp in components:
                    weight = float(weights.get(comp, 0.0))
                    if weight <= 0.0:
                        continue

                    src_ids_comp: list[int] = []
                    vectors_comp: list[list[float]] = []
                    for sid in src_ids:
                        v = vecs_by_id.get(sid, {}).get(comp)
                        if v is None:
                            continue
                        src_ids_comp.append(sid)
                        vectors_comp.append(v)

                    if not vectors_comp:
                        continue

                    comp_hits = q.query_batch(
                        vectors=vectors_comp,
                        collection_name=collection_name,
                        using=comp,
                        limit=search_limit,
                        score_threshold=params.score_threshold,
                    )

                    _merge_component_hits(
                        aggregated=aggregated,
                        src_ids=src_ids_comp,
                        hits_per_src=comp_hits,
                        weight=weight,
                    )

                _union_top_neighbors(dsu, aggregated, params.limit)

                processed += len(src_ids)
                if params.max_recipes is not None and processed >= params.max_recipes:
                    break

            logger.info("Processed %d recipes...", processed)
            if params.max_recipes is not None and processed >= params.max_recipes:
                break

        self.clusters = _build_clusters_from_dsu(dsu, params.min_cluster_size)
        return self.clusters
    
    def load_clusters_from_file(self, filepath: str) -> list[list[int]]:
        """Загружает кластеры из файла в формате JSON."""
        if self.cluster_filepath is None:
            self.cluster_filepath = filepath
        with open(filepath, 'r') as f:
            clusters = json.load(f)
        self.clusters = clusters
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
        

    def process_and_save_clusters(self, offest: Optional[int] = 0) -> None:
        """
        processes loaded clusters, asks GPT to filter them, and saves to DB, skips already saved clusters.
        """
        if not self.clusters:
            logger.warning("No clusters to process.")
            return
        
        for num, cluster in enumerate(self.clusters[offest:], start=offest):
            if self.is_cluster_present(cluster):
                continue
            similar_clusters = self.ask_chatgpt_about_cluster(cluster)
            if set(similar_clusters) != set(cluster):
                self.clusters[num] = similar_clusters
                if self.cluster_filepath:
                    # Обновляем файл кластеров после любого обновления, чтобы не терять прогресс
                    with open(self.cluster_filepath, 'w') as f:
                        f.write(json.dumps(self.clusters, indent=2))
                    logger.info(f"Updated cluster file {self.cluster_filepath} after GPT filtering.")
            
            if not similar_clusters:
                logger.info("Skipping empty cluster after GPT filtering.")
                continue
            
            self.similarity_repository.save_cluster_with_members(similar_clusters)
            logger.info(f"Saved cluster {num + 1}/{len(self.clusters)} with {len(similar_clusters)} members.")
        
    def save_clusters_to_file(self, filepath: str) -> None:
        """Сохраняет текущие кластеры в файл в формате JSON."""
        with open(filepath, 'w') as f:
            f.write(json.dumps(self.clusters, indent=2))
        logger.info(f"Saved clusters to file {filepath}.")

if __name__ == "__main__":
    ss = SimilaritySearcher(
        search_type=SimilaritySearchType.FULL_TEXT,
        model_name="text-embedding-3-small",
        metric=SimilarityMetric.COSINE,
    )
    # показывает более хорошие кластеры, чем weighted
    clusters = ss.build_full_text_clusters_via_qdrant(
        params=ClusterParams(
            #max_recipes=500,
            limit=20,
            score_threshold=0.94,
            scroll_batch=1000,
            query_batch=16,
            collection_name="full",
        )
    )
    with open("full_text_clusters94.txt", "w") as f:
        f.write(json.dumps(clusters, indent=2))

    for c in clusters:
        print(c)


    """
    ss.search_type = SimilaritySearchType.WEIGHTED
    clusters = ss.build_weighted_mv_clusters_via_qdrant(
        params=ClusterParams(
            max_recipes=500,
            limit=25,
            score_threshold=0.90,
            scroll_batch=1000,
            query_batch=32,
            collection_name="mv",
            # пример: берём только ingredients+instructions (остальные можно оставить по умолчанию)
            components=["ingredients", "instructions", "dish_name", "tags"],
            component_weights={"ingredients": 0.4, "instructions": 0.3, "dish_name": 0.2, "tags": 0.1},
            candidate_multiplier=3
        )
    )
    for c in clusters:
        print(c)"""