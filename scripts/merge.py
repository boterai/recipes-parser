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

async def create_clusters(score_thresold: float, build_type: Literal["image", "full", "ingredients"]) -> tuple[list[list[int]], dict[int, list[int]]]:
    last_error_id = None
    consecutive_same_count = 0
    recalculate_mapping = True # пересчет маппинга изображений к кластерам (только в том случае, если что-то добавилось)
    first_loaded_last_id = None
    while True:
        ss = SimilaritySearcher(params=ClusterParams(
                    limit=config.SIMILARITY_LIMIT,
                    score_threshold=score_thresold,
                    scroll_batch=config.SIMILARITY_SCROLL_BATCH_SIZE,
                    query_batch=config.SIMILARITY_QUERY_BATCH_SIZE
                ), build_type=build_type) # "image", "full", "ingredients"
        
        try:
            ss.load_dsu_state()
            if first_loaded_last_id is None:
                first_loaded_last_id = ss.last_id
            last_id = ss.last_id # получаем last id после загрузки состояния (такая штука работает только опираясь на тот факт, что каждй вновь доавбленный рецепт имеет id не меньше уже векторизованных рецептов, иначе рецепты могут быть пропущены)
            clusters = await ss.build_clusters_async()
            ss.save_dsu_state()
            print(f"Total clusters found: {len(clusters)}")
            print("Last processed ID:", ss.last_id)
            ss.save_clusters_to_file(clusters)
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
            ss.save_dsu_state()
            random_sleep_time = min(random.uniform(5, 15) * (consecutive_same_count + 1))
            logger.info(f"Sleeping for {random_sleep_time:.2f} seconds before retrying...")
            await asyncio.sleep(random_sleep_time)
            continue

    final_clusters = build_clusters_from_dsu(ss.dsu, min_cluster_size=2)
    ss.save_clusters_to_file(final_clusters, recalculate_mapping=recalculate_mapping)
    return ss.load_clusters_from_file(), ss.get_image_clusters_mapping() # загружаем из файла, чтобы отдать уже правильные кластеры и создать маппинг, если это изображения

def save_clusters_to_history(clusters: list[list[int]], filename: str):
    os.makedirs(config.MERGE_HISTORY_FOLDER, exist_ok=True)
    with open(filename, "w") as f:
        json.dump(clusters, f)

def load_clusters_from_history(filename: str) -> list[list[int]]:
    if not os.path.exists(filename):
        return []
    with open(filename, "r") as f:
        return json.load(f)
    

async def execute_cluster_batch(tasks: list, clusters_in_batch: list[list[int]]) -> list[list[int]]:
    """Выполняет асинхронные задачи и обрабатывает результаты, возвращая список успешно обработанных кластеров.
    Args:
        tasks: Список асинхронных задач для выполнения.
        clusters_in_batch: Список кластеров, соответствующих каждой задаче.
    Returns:
        Список кластеров, для которых задачи были успешно выполнены."""
    success_clusters = []
    completed_tasks = await asyncio.gather(*tasks, return_exceptions=True)
    for i, result in enumerate(completed_tasks):
        if isinstance(result, Exception):
            logger.error(f"Error in task for cluster {clusters_in_batch[i]}: {result}")
        else:
            for merged_recipes in completed_tasks:
                if merged_recipes and not isinstance(merged_recipes, Exception):
                    logger.info(f"Created {len(merged_recipes)} variations.")
            success_clusters.append(clusters_in_batch[i])
    return success_clusters
    

async def run_merge(score_thresold: float, 
                    build_type: Literal["image", "full", "ingredients"],
                    max_variations: int = 3, 
                    validate_gpt: bool = True, 
                    save_to_db: bool = True, 
                    max_merged_recipes: int = 4, 
                    limit: Optional[int] = None):
    
    cluster_processing_history = os.path.join(config.MERGE_HISTORY_FOLDER, f"unprocessed_clusters_{build_type}_{score_thresold}.json")
    existing_clusters = load_clusters_from_history(cluster_processing_history)

    merger = ClusterVariationGenerator(score_threshold=score_thresold, clusters_build_type=build_type)
    clusters, cluster_mapping = await create_clusters(score_thresold, build_type)
    if build_type == "image":
        cluster_mapping = cluster_mapping.get("page_to_image", {})

    if existing_clusters:
        logger.info(f"Загружено {len(existing_clusters)} кластеров из истории, всего кластеров {len(clusters)}, пропускаем уже обработанные...")
        processed_set = {tuple(sorted(cluster)) for cluster in existing_clusters}
        clusters = [cluster for cluster in clusters if tuple(sorted(cluster)) not in processed_set]
        logger.info(f"Осталось {len(clusters)} кластеров для обработки после фильтрации истории.")
    total = 0
    used_batch_size = 0
    tasks = []
    clusters_in_current_batch = []
    
    for cluster in clusters:
        image_ids = None
        if build_type == "image":
            cluster_key = ','.join(map(str, sorted(cluster)))
            image_ids = cluster_mapping.get(cluster_key)

        # на основе этого параметра расчитывается возможность асинхронной генерации рецептов
        max_combinations = merger.merger.calculate_max_combinations( 
            n=len(cluster),
            k=min(max_merged_recipes, len(cluster)),
            max_variations=max_variations
        )

        tasks.append(merger.create_variations(
            cluster=cluster,
            validate_gpt=validate_gpt,
            save_to_db=save_to_db,
            max_variations=max_variations,
            max_merged_recipes=max_merged_recipes,
            recipe_language=config.TARGET_LANGUAGE,
            image_ids=image_ids
        ))
        clusters_in_current_batch.append(cluster)
        used_batch_size += max_combinations

        if used_batch_size >= config.MERGE_BATCH_SIZE:
            # Выполняем текущий батч
            success_clusters = await execute_cluster_batch(tasks, clusters_in_current_batch)
            total += len(success_clusters)
            logger.info(f"Всего успешно обработано кластеров в этом батче: {len(success_clusters)}/{len(clusters_in_current_batch)}")
            
            # Сохраняем обработанные кластеры в историю
            existing_clusters.extend(success_clusters)
            save_clusters_to_history(existing_clusters, cluster_processing_history)
            
            # Очищаем для следующего батча
            tasks = []
            clusters_in_current_batch = []
            used_batch_size = 0
            
            if limit and total >= limit:
                logger.info(f"Reached limit of {limit} merged recipes, stopping.")
                break

def view_recipes(merge_recipe_id: int = 534):
    mr = MergedRecipeRepository()
    merged_recipes = mr.get_by_id_with_images(merge_recipe_id)
    img_urls = [img.id for img in merged_recipes.images] if merged_recipes and merged_recipes.images else []
    logger.info(f"Merged Recipe ID: {merged_recipes.id if merged_recipes else 'Not Found'}")
    logger.info(f"Image URLs: {img_urls}")   

if __name__ == "__main__":
    from dotenv import load_dotenv # загружаем для доступа к .env переменным
    load_dotenv()
    # "image", "full", "ingredients"
    asyncio.run(run_merge(0.92, "full"))