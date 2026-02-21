import sys
import logging
from pathlib import Path
import asyncio
import os
import json
import random
# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))
import random

from src.stages.search.similarity import SimilaritySearcher, ClusterParams, build_clusters_from_dsu
from src.stages.merge.merge import ClusterVariationGenerator
from src.repositories.merged_recipe import MergedRecipeRepository
from src.repositories.cluster_page import ClusterPageRepository
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

async def generate_recipe_clusters(similarity_threshold: float, build_type: Literal["image", "full", "ingredients"], check_cluster_update: bool = True):
    """
    create_clusters - создает кластеры рецептов на основе заданного порога схожести и типа построения кластеров и сохраняет их в бд.
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
        if check_cluster_update is False and ss.local_cluster_loader.load_clusters():
            return

        try:
            check_cluster_update = True # чтобы не вылететь после первой итерации
            ss.load_dsu_state()
            if first_loaded_last_id is None:
                first_loaded_last_id = ss.last_id
            last_id = ss.last_id # получаем last id после загрузки состояния (такая штука работает только опираясь на тот факт, что каждй вновь доавбленный рецепт имеет id не меньше уже векторизованных рецептов, иначе рецепты могут быть пропущены)
            clusters = await ss.build_clusters_async()
            ss.save_dsu_state()
            print(f"Total clusters found: {len(clusters)}, last processed ID: {ss.last_id}")
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
    await ss.save_clusters_to_file(final_clusters, recalculate_mapping=recalculate_mapping, refine_clusters=recalculate_mapping)

async def execute_cluster_batch(tasks: list, clusters_in_batch: list[str]) -> int:
    """Выполняет асинхронные задачи и обрабатывает результаты, возвращая список успешно обработанных кластеров.
    Args:
        tasks: Список асинхронных задач для выполнения.
        clusters_in_batch: Список кластеров, соответствующих каждой задаче.
    Returns:
        Список кластеров, для которых задачи были успешно выполнены."""
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

    return processed_count

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
    # проверяем есть ил кластеры, при необходимоси обновляем бд
    await generate_recipe_clusters(similarity_threshold, build_type, check_cluster_update=check_cluster_update)

    cluster_repo = ClusterPageRepository()
    if (total_tasks := cluster_repo.get_cluster_count()) == 0:
        logger.info("No clusters found in the database, exiting...")
        return
    
    logger.info(f"Total clusters to process: {total_tasks}")
    merger = ClusterVariationGenerator(score_threshold=similarity_threshold, clusters_build_type=build_type, max_recipes_per_gpt_merge_request=max_recipes_per_gpt_merge_request)
    get_cluster_function = cluster_repo.get_clusters_without_merged_recipes if max_variation_per_cluster == 1 else cluster_repo.get_clusters
    total = 0
    last_cluster_id = None
    while True:
        centroids, last_cluster_id = get_cluster_function(limit=config.MERGE_MAX_MERGE_RECIPES, last_cluster_id=last_cluster_id)
        if not centroids:
            logger.info("No more clusters to process, exiting...")
            break

        tasks = [
            generate_from_one_cluster(
                merger=merger,
                cluster=cluster,
                cluster_centroid=centroid,
                max_variations= max_variation_per_cluster,
                max_aggregated_recipes= max_aggregated_recipes
            ) for centroid, cluster in centroids.items()
        ]
        total += await execute_cluster_batch(tasks, list(centroids.values()))
        if limit and total >= limit:
            logger.info(f"Достигнут лимит в {limit} успешно обработанных кластеров, останавливаемся.")
            break

async def make_recipe_variations(similarity_threshold: float, build_type: Literal["image", "full", "ingredients"], max_variations_per_recipe: int =1,
                                 limit: int | None = None):
    merger = ClusterVariationGenerator(score_threshold=similarity_threshold, clusters_build_type=build_type, max_recipes_per_gpt_merge_request=5)
    total = 0
    last_id: Optional[int] = None
    while True:
        canonical_recipes = merger.merge_repository.get_canonical_recipes(max_variations=max(0, max_variations_per_recipe-1), limit=config.MERGE_MAX_MERGE_RECIPES, last_id=last_id)
        if not canonical_recipes:
            logger.info("Нет канонических рецептов для генерации вариаций, останавливаемся.")
            break

        tasks = []
        for canonical in canonical_recipes:
            tasks.append(merger.create_recipe_variation(
                canonical_recipe_id=canonical.id,
                save_to_db=True
            ))
            last_id = canonical.id

        completed_tasks = await asyncio.gather(*tasks, return_exceptions=True)
        for res in completed_tasks:
            if isinstance(res, Exception):
                logger.error(f"Error during variation generation: {res}")
            elif res is None:
                logger.info("Variation was not created or updated.")
            else:
                total += 1
                logger.info(f"✓ Variation with id {res.id} created. Total variations created: {total}")

        if limit and total >= limit:
            logger.info(f"Достигнут лимит в {limit} успешно созданных вариаций, останавливаемся.")
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
                logger.info(f"✓ Merged recipe with id {res.id} created and marked as completed with {res.recipe_count} recipes.")


def view_merge_recipe(recipe_id: int):
    repo = MergedRecipeRepository()
    merged_recipe = repo.get_by_id(recipe_id)
    if merged_recipe:
        print(merged_recipe.to_pydantic(get_images=False))
    else:
        print(f"Merged recipe with id {recipe_id} not found.")

if __name__ == "__main__":
    config.MERGE_CENTROID_THRESHOLD_STEP = 0.02
    #config.MERGE_MAX_MERGE_RECIPES = 1
    #asyncio.run(make_recipe_variations(similarity_threshold=0.92, build_type="full", max_variations_per_recipe=1, limit=10))
    #merger = merger = ClusterVariationGenerator(score_threshold=0.9, clusters_build_type="full", max_recipes_per_gpt_merge_request=5)
    asyncio.run(make_recipe_variations(similarity_threshold=0.9, build_type="full", max_variations_per_recipe=1, limit=100))
    
    asyncio.run(merge_cluster_recipes(similarity_threshold=0.9, 
                                             build_type="full", 
                                             max_variation_per_cluster=1, 
                                             max_aggregated_recipes=9, # + 1 базовый 
                                             max_recipes_per_gpt_merge_request=4,
                                             check_cluster_update=False, 
                                             limit=150))
