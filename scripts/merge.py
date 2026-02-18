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
            density_min_similarity=score_thresold + config.MERGE_CENTROID_THRESHOLD_STEP
        ), build_type=build_type) # "image", "full", "ingredients"

def load_centroids(score_thresold: float, build_type: Literal["image", "full", "ingredients"]) -> dict[int, list[float]]:
    ss = get_ss_from_config(score_thresold, build_type)
    ss.load_validated_centroids()
    return ss.validated_centroids

async def generate_recipe_clusters(similarity_threshold: float, build_type: Literal["image", "full", "ingredients"], check_cluster_update: bool = True):
    """
    create_clusters - создает кластеры рецептов на основе заданного порога схожести и типа построения кластеров.
    Args:
        similarity_threshold: Порог схожести для кластеризации (по умолчанию из конфигурации).
        build_type: Тип построения кластеров ("image", "full", "ingredients") (по умолчанию из конфигурации).
        check_cluster_update: Флаг, указывающий, следует ли загружать кластеры из файла без проверки на обновления из векторной базы данных (по умолчанию False).
    """
    last_error_id = None
    consecutive_same_count = 0
    recalculate_mapping = True # пересчет маппинга изображений к кластерам (только в том случае, если что-то добавилось)
    first_loaded_last_id = None
    while True:
        ss = get_ss_from_config(similarity_threshold, build_type)
        if check_cluster_update is False and ss.load_clusters_from_file():
            return

        try:
            check_cluster_update = True # чтобы не вылететь после первой итерации
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
    await ss.save_clusters_to_file(final_clusters, recalculate_mapping=recalculate_mapping, refine_clusters=recalculate_mapping, refine_mode="split")

def save_clusters_to_history(clusters: list[list[int]], filename: str):
    os.makedirs(config.MERGE_HISTORY_FOLDER, exist_ok=True)
    with open(filename, "w") as f:
        json.dump(clusters, f)

def load_clusters_from_history(filename: str) -> list[list[int]]:
    if not os.path.exists(filename):
        return []
    with open(filename, "r") as f:
        return json.load(f)

async def execute_cluster_batch(tasks: list, clusters_in_batch: list[str]) -> tuple[list[list[int]], int]:
    """Выполняет асинхронные задачи и обрабатывает результаты, возвращая список успешно обработанных кластеров.
    Args:
        tasks: Список асинхронных задач для выполнения.
        clusters_in_batch: Список кластеров, соответствующих каждой задаче.
    Returns:
        Список кластеров, для которых задачи были успешно выполнены."""
    success_clusters = []
    processed_count = 0
    completed_tasks = await asyncio.gather(*tasks, return_exceptions=True)
    for i, result in enumerate(completed_tasks):
        if isinstance(result, Exception):
            logger.error(f"Error in task for cluster {clusters_in_batch[i]}: {result}")
        else:
            for merged_recipes in completed_tasks:
                if merged_recipes and not isinstance(merged_recipes, Exception):
                    logger.info(f"Created {len(merged_recipes)} variations.")
                    processed_count += 1

            success_clusters.append(clusters_in_batch[i])

    return success_clusters, processed_count

async def merge_cluster_recipes(
        similarity_threshold: float | None, 
        build_type: Literal["full", "ingredients"] | None,
        max_variation_per_cluster: int | None = 1,
        max_aggregated_recipes: int = 8,
        max_recipes_per_gpt_merge_request: int = 4,
        check_cluster_update: bool = False, 
        limit: Optional[int] = None
        ):
    
    """
        Запускает процесс генерации вариаций рецептов на основе кластеров, расширяя базовые рецепты (в первую очередь центры кластеров).
        Args:
            similarity_threshold: Порог схожести для кластеризации.
            build_type: Тип построения кластеров ("image", "full", "ingredients").
            max_variation_per_cluster: Максимальное количество вариаций на кластер.
            max_aggregated_recipes: Максимальное количество рецептов в объединенном рецепте.
            check_cluster_update: Флаг, указывающий, следует ли проверять обновления кластеров в процессе генерации (по умолчанию False).
        Returns:
            None
    """

    cluster_processing_history = os.path.join(config.MERGE_HISTORY_FOLDER, f"unprocessed_clusters_max_recipes_{max_aggregated_recipes}.json")
    existing_clusters = load_clusters_from_history(cluster_processing_history)

    merger = ClusterVariationGenerator(score_threshold=similarity_threshold, clusters_build_type=build_type, max_recipes_per_gpt_merge_request=max_recipes_per_gpt_merge_request)
    await generate_recipe_clusters(similarity_threshold, build_type, check_cluster_update=check_cluster_update)
    centroids = load_centroids(similarity_threshold, build_type)
    if not centroids:
        logger.info(f"No centroids found for build type - {build_type}, score_threshold - {similarity_threshold}, exiting...")
        return

    total_tasks = len(centroids)
    if existing_clusters:
        logger.info(f"Загружено {len(existing_clusters)} кластеров из истории, всего кластеров {len(centroids)}, пропускаем уже обработанные.")
        centroids = {k: v for k, v in centroids.items() if k not in existing_clusters}
        logger.info(f"Осталось {len(centroids)} кластеров для обработки после фильтрации истории.")

    total = 0
    tasks = []
    clusters_in_current_batch = []

    for cluster, centroid in centroids.items():
        cluster_list = list(map(int, cluster.split(",")))
        clusters_in_current_batch.append(cluster)

        tasks.append(generate_from_one_cluster(
                merger=merger,
                cluster=cluster_list,
                cluster_centroid=centroid,
                max_variations= max_variation_per_cluster,
                max_aggregated_recipes= max_aggregated_recipes
            ))
        
        if len(tasks) >= config.MERGE_MAX_MERGE_RECIPES or len(existing_clusters) == total_tasks: # набран батч или все кластеры уже были в истории
            success_clusters, processed = await execute_cluster_batch(tasks, clusters_in_current_batch)
            total += processed
            existing_clusters.extend(success_clusters)
            save_clusters_to_history(existing_clusters, cluster_processing_history)

            tasks = []
            clusters_in_current_batch = []

        
        if limit and total >= limit:
            logger.info(f"Достигнут лимит в {limit} успешно обработанных кластеров, останавливаемся.")
            break

async def generate_from_one_cluster(
        merger: ClusterVariationGenerator, 
        cluster: list[int], 
        cluster_centroid: int, 
        max_variations: int, 
        max_aggregated_recipes: int  
    ):
    """Генерирует вариации рецептов для одного кластера, расширяя базовый рецепт.
    Args:
        merger: Экземпляр ClusterVariationGenerator для генерации рецептов.
        cluster: Список page_id рецептов в кластере.
        cluster_centroid: page_id рецепта, являющегося центроидом кластера (наиболее репрезентативного рецепта).
        max_variations: Максимальное количество вариаций для генерации на кластер. (вариацией считается рецепт, который в своем составе содержит centroid)
    """
    recipe_variations = merger.merge_repository.get_pages_with_digits_in_csv(cluster) or [] # получает все рецепты, где есть любой рецепт из кластера

    used_base_recipes = [mr.base_recipe_id for mr in recipe_variations]
    not_used_base_recipes_ids = [bid for bid in cluster if bid  not in used_base_recipes]
    
    completed = [mr for mr in recipe_variations if mr.recipe_count >= max_aggregated_recipes]
    incomplete = [mr for mr in recipe_variations if mr.recipe_count < max_aggregated_recipes]
    
    remaining_slots = max_variations - len(completed)
    if remaining_slots <= 0:
        logger.info(f"Cluster already has {len(completed)} completed variations, skipping...")
        return
    
    tasks = []
    for mr in incomplete:
        mr = mr.to_pydantic(get_images=False)
        tasks.append(merger.create_canonical_recipe_with_gpt(
            existing_merged=mr,
            base_recipe_id=mr.base_recipe_id,
            cluster_recipes=cluster,
            target_language=config.TARGET_LANGUAGE,
            save_to_db=True,
            max_aggregated_recipes=max_aggregated_recipes
        ))
        random.shuffle(cluster)

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
            max_aggregated_recipes=max_aggregated_recipes
        ))
        random.shuffle(cluster)

    if tasks:
        response = await asyncio.gather(*tasks, return_exceptions=True)
        evaluate_merge_results(response, cluster_len=len(cluster), max_aggregated_recipes=max_aggregated_recipes, merge_repository=merger.merge_repository)

def evaluate_merge_results(response, cluster_len:int, max_aggregated_recipes: int, merge_repository: MergedRecipeRepository):
    for res in response:
        if isinstance(res, Exception):
            logger.error(f"Error during GPT merge: {res}")
        elif res is None:
            logger.info("Variation was not created or updated.")
        else:
            # рецепт отмечается как успешный, если в нем достаточно рецептов из кластера (включая базовый рецепт), даже если он не достиг максимального количества рецептов для объединения (max_aggregated_recipes), так как в некоторых кластерах может быть недостаточно рецептов для достижения этого порога
            res = merge_repository.get_by_id(res.id)
            if res.recipe_count >= max_aggregated_recipes or (cluster_len >= config.SIMILARITY_MIN_CLUSTER_SIZE and res.recipe_count >= cluster_len):
                res.is_completed = True
                merge_repository.update(res)
                logger.info(f"✓ Variation with id {res.id} created and marked as completed with {res.recipe_count} recipes.")


def view_merge_recipe(recipe_id: int):
    repo = MergedRecipeRepository()
    merged_recipe = repo.get_by_id(recipe_id)
    if merged_recipe:
        print(merged_recipe.to_pydantic(get_images=False))
    else:
        print(f"Merged recipe with id {recipe_id} not found.")

if __name__ == "__main__":
    #view_merge_recipe(8462)
    # "image", "full", "ingredients"
    #cluster = [18621,18622,18627,18631,18709,21450,21469,22826,41619,64861,80441,113320,113839,113843,113870,118374,127450,127460,127807,130235,137954,139693,139698,139736,139784,139810,139827,139830,139832,140052,140086,140197,140198,140201,140344,146581,146582,161614,180924,183498,185474,194091,194098,194099,194100,194364,194376,194496,194690,197415,197417,197420,198223]
    #base_recipe =  137954
    #merger = ClusterVariationGenerator(score_threshold=0.89, clusters_build_type="full", max_recipes_per_gpt_merge_request=4)
    #merger.merge_repository.mark_recipe_as_completed(8490)
    #config.MERGE_CENTROID_THRESHOLD_STEP = 0.02
    #asyncio.run(generate_from_one_cluster(merger=merger, cluster=cluster, cluster_centroid=base_recipe, 
    #                          max_variations=1, max_aggregated_recipes=10))
    #config.MERGE_MAX_MERGE_RECIPES = 1
    config.MERGE_CENTROID_THRESHOLD_STEP = 0.01
    asyncio.run(merge_cluster_recipes(similarity_threshold=0.92, 
                                             build_type="full", 
                                             max_variation_per_cluster=1, 
                                             max_aggregated_recipes=9, # + 1 базовый 
                                             max_recipes_per_gpt_merge_request=4,
                                             check_cluster_update=False, 
                                             limit=150))
