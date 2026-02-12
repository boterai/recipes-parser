import sys
import logging
from pathlib import Path
import asyncio
import os
import json
import random
# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.normalization import normalize_ingredients_list
import random

from src.stages.search.similarity import SimilaritySearcher, ClusterParams, build_clusters_from_dsu
from src.stages.merge.merge import ClusterVariationGenerator
from src.repositories.merged_recipe import MergedRecipeRepository
from typing import Literal, Optional
from config.config import config
# Базовая настройка только для консоли
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(threadName)s] - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)

logger = logging.getLogger(__name__)

def get_ss_from_config(score_thresold: float, build_type: Literal["image", "full", "ingredients"]) -> SimilaritySearcher:
    return SimilaritySearcher(params=ClusterParams(
            limit=config.SIMILARITY_LIMIT,
            score_threshold=score_thresold,
            scroll_batch=config.SIMILARITY_SCROLL_BATCH_SIZE,
            query_batch=config.SIMILARITY_QUERY_BATCH_SIZE,
            min_cluster_size=config.SIMILARITY_MIN_CLUSTER_SIZE,
            min_cluster_size_for_validation=config.SIMILARITY_MIN_CLUSTER_SIZE_FOR_VALIDATION,
            union_top_k=config.SIMILARITY_UNION_TOP_K,
            centroid_threshold=score_thresold + config.MERGE_CENTROID_THRESHOLD_STEP,
            density_min_similarity=score_thresold + config.MERGE_CENTROID_THRESHOLD_STEP
        ), build_type=build_type) # "image", "full", "ingredients"

def load_centroids(score_thresold: float, build_type: Literal["image", "full", "ingredients"]) -> dict[int, list[float]]:
    ss = get_ss_from_config(score_thresold, build_type)
    ss.load_validated_centroids()
    return ss.validated_centroids

async def create_clusters(score_thresold: float, build_type: Literal["image", "full", "ingredients"], check_cluster_update: bool = True) -> list[list[int]]:
    """
    create_clusters - создает кластеры рецептов на основе заданного порога схожести и типа построения кластеров.
    Args:
        score_thresold: Порог схожести для кластеризации (по умолчанию из конфигурации).
        build_type: Тип построения кластеров ("image", "full", "ingredients") (по умолчанию из конфигурации).
        check_cluster_update: Флаг, указывающий, следует ли загружать кластеры из файла без проверки на обновления из векторной базы данных (по умолчанию False).
    """
    last_error_id = None
    consecutive_same_count = 0
    recalculate_mapping = True # пересчет маппинга изображений к кластерам (только в том случае, если что-то добавилось)
    first_loaded_last_id = None
    while True:
        ss = get_ss_from_config(score_thresold, build_type)
        if check_cluster_update is False and (data := ss.load_clusters_from_file()):
            return data

        try:
            ss.load_dsu_state()
            if first_loaded_last_id is None:
                first_loaded_last_id = ss.last_id
            last_id = ss.last_id # получаем last id после загрузки состояния (такая штука работает только опираясь на тот факт, что каждй вновь доавбленный рецепт имеет id не меньше уже векторизованных рецептов, иначе рецепты могут быть пропущены)
            clusters = await ss.build_clusters_async()
            ss.save_dsu_state()
            print(f"Total clusters found: {len(clusters)}")
            print("Last processed ID:", ss.last_id)
            await ss.save_clusters_to_file(clusters)
            if ss.last_id == last_id:
                logger.info("Processing complete.")
                if ss.last_id == first_loaded_last_id:
                    recalculate_mapping = False
                break

        except Exception as e:
            if last_error_id == ss.last_id:
                consecutive_same_count += 1
            else:
                consecutive_same_count = 0
                last_error_id = ss.last_id

            logger.error(f"Error during cluster building: {e}")
            random_sleep_time = random.uniform(5, 15) * (consecutive_same_count + 1)
            logger.info(f"Sleeping for {random_sleep_time:.2f} seconds before retrying...")
            await asyncio.sleep(random_sleep_time)
            continue

    final_clusters = build_clusters_from_dsu(ss.dsu, min_cluster_size=config.SIMILARITY_MIN_CLUSTER_SIZE)
    await ss.save_clusters_to_file(final_clusters, recalculate_mapping=recalculate_mapping, refine_clusters=True, refine_mode="split")
    return ss.load_clusters_from_file()

def save_clusters_to_history(clusters: list[list[int]], filename: str):
    os.makedirs(config.MERGE_HISTORY_FOLDER, exist_ok=True)
    with open(filename, "w") as f:
        json.dump(clusters, f)

def load_clusters_from_history(filename: str) -> list[list[int]]:
    if not os.path.exists(filename):
        return []
    with open(filename, "r") as f:
        return json.load(f)

async def run_merge_expand_base_recipe(
        score_thresold: float | None, 
        build_type: Literal["full", "ingredients"] | None,
        max_variation_per_cluster: int | None = 1,
        max_aggregated_recipes: int = 8,
        max_recipes_per_gpt_merge_request: int = 4,
        max_recipes_with_centroid: Optional[int] = None,
        check_cluster_update: bool = False
        ):
    
    """
        Запускает процесс генерации вариаций рецептов на основе кластеров, расширяя базовые рецепты.
        Args:
            score_thresold: Порог схожести для кластеризации (по умолчанию из конфигурации).
            build_type: Тип построения кластеров ("image", "full", "ingredients") (по умолчанию из конфигурации).
            max_variation_per_cluster: Максимальное количество вариаций на кластер (по умолчанию из конфигурации).
            max_aggregated_recipes: Максимальное количество рецептов в объединенном рецепте (по умолчанию из конфигурации).
            max_recipes_with_centroid: Максимальное количество рецептов, включающих центроид кластера (по умолчанию None, что означает без ограничений).
            check_cluster_update: Флаг, указывающий, следует ли проверять обновления кластеров в процессе генерации (по умолчанию False).
        Returns:
            None
    """

    cluster_processing_history = os.path.join(config.MERGE_HISTORY_FOLDER, f"unprocessed_clusters_{build_type}_{score_thresold}_{score_thresold + 0.02}.json")
    existing_clusters = load_clusters_from_history(cluster_processing_history)

    merger = ClusterVariationGenerator(score_threshold=score_thresold, clusters_build_type=build_type, max_recipes_per_gpt_merge_request=max_recipes_per_gpt_merge_request)
    clusters = await create_clusters(score_thresold, build_type, check_cluster_update=check_cluster_update)
    centroids = load_centroids(score_thresold, build_type)

    if existing_clusters:
        logger.info(f"Загружено {len(existing_clusters)} кластеров из истории, всего кластеров {len(clusters)}, пропускаем уже обработанные...")
        processed_set = {tuple(sorted(cluster)) for cluster in existing_clusters}
        clusters = [cluster for cluster in clusters if tuple(sorted(cluster)) not in processed_set]
        logger.info(f"Осталось {len(clusters)} кластеров для обработки после фильтрации истории.")

    for cluster in clusters:
        cluster_key = ','.join(map(str, sorted(cluster)))
        cluster_centroid = centroids.get(cluster_key)
        if cluster_centroid is None:
            logger.warning(f"No validated centroid found for cluster {cluster}, skipping...")
            continue
        random.shuffle(cluster) # перемешиваем cluster, чтобы при боьшом ко-ве рецептов расширять разными рецептами
        try:
            await generate_from_one_cluster(
                merger=merger,
                cluster=cluster,
                cluster_centroid=cluster_centroid,
                max_variations= max_variation_per_cluster,
                max_aggregated_recipes= max_aggregated_recipes,
                max_recipes_with_centroid=max_recipes_with_centroid
            )
            existing_clusters.append(cluster)
            save_clusters_to_history(existing_clusters, cluster_processing_history)
        except Exception as e:
            logger.error(f"Error processing cluster {cluster}: {e}")
            continue

async def generate_from_one_cluster(
        merger: ClusterVariationGenerator, 
        cluster: list[int], 
        cluster_centroid: int, 
        max_variations: int, 
        max_aggregated_recipes: int,
        max_recipes_with_centroid: Optional[int] = None
        ):
    """Генерирует вариации рецептов для одного кластера, расширяя базовый рецепт.
    Args:
        merger: Экземпляр ClusterVariationGenerator для генерации рецептов.
        cluster: Список page_id рецептов в кластере.
        cluster_centroid: page_id рецепта, являющегося центроидом кластера (наиболее репрезентативного рецепта).
        max_variations: Максимальное количество вариаций для генерации на кластер.
    """
    
    existing_recipes = merger.merge_repository.get_by_base_recipe_ids(cluster) or []
    if max_recipes_with_centroid:
        current_recipes = merger.merge_repository.count_pages_with_digit_in_csv(cluster_centroid)
        if current_recipes >= max_recipes_with_centroid:
            logger.info(f"Cluster centroid {cluster_centroid} already has {current_recipes} recipes, skipping generation for this centroid...")
            return
    
    used_base_recipes = [mr.base_recipe_id for mr in existing_recipes]
    not_used_base_recipes_ids = [bid for bid in cluster if bid  not in used_base_recipes]
    
    completed = [mr for mr in existing_recipes if mr.recipe_count >= max_aggregated_recipes]
    incomplete = [mr for mr in existing_recipes if mr.recipe_count < max_aggregated_recipes]
    
    remaining_slots = max_variations - len(completed)
    if remaining_slots <= 0:
        logger.info(f"Cluster already has {len(completed)} completed variations, skipping...")
        return
    
    tasks = []
    for mr in incomplete:
        tasks.append(merger.create_canonical_recipe_with_gpt(
            existing_merged=mr,
            base_recipe_id=mr.base_recipe_id,
            cluster_recipes=cluster,
            target_language=config.TARGET_LANGUAGE,
            save_to_db=True,
            max_aggregaeted_recipes=max_aggregated_recipes
        ))

    while len(tasks) < remaining_slots and not_used_base_recipes_ids:
        if cluster_centroid in not_used_base_recipes_ids:
            base_recipe_id = cluster_centroid
            not_used_base_recipes_ids.remove(cluster_centroid)
        else:
            base_recipe_id = not_used_base_recipes_ids.pop(0)

        tasks.append(merger.create_canonical_recipe_with_gpt(
            existing_merged=None,
            base_recipe_id=base_recipe_id,
            cluster_recipes=cluster,
            target_language=config.TARGET_LANGUAGE,
            save_to_db=True,
            max_aggregaeted_recipes=max_aggregated_recipes
        ))

    if tasks:
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    # "image", "full", "ingredients"
    """config.MERGE_CENTROID_THRESHOLD_STEP = 0.01
    
    cluster = [1315,17901,17926,17933,23708,39593,53037,53044,58759,75844,81233,88609,102693,104002,104004,120756,133869,135430,182671,183541,183589,191702]
    base_recipe = 81233
    merger = ClusterVariationGenerator(score_threshold=0.92, clusters_build_type="full", max_recipes_per_gpt_merge_request=4)
    asyncio.run(generate_from_one_cluster( merger=merger, cluster=cluster, cluster_centroid=base_recipe, 
                                          max_variations=2, 
                                          max_aggregated_recipes=8, 
                                          max_recipes_with_centroid=2 ))"""


    asyncio.run(run_merge_expand_base_recipe(score_thresold=0.96, 
                                             build_type="ingredients", 
                                             max_variation_per_cluster=1, 
                                             max_aggregated_recipes=6, 
                                             max_recipes_per_gpt_merge_request=4,
                                             max_recipes_with_centroid=1,
                                             check_cluster_update=True))
