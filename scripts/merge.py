import sys
import logging
from pathlib import Path
import argparse
import asyncio
import os
import json
import random
# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.stages.search.similarity import SimilaritySearcher, ClusterParams, build_clusters_from_dsu
from src.stages.merge.merge import ClusterVariationGenerator
from src.repositories.merged_recipe import MergedRecipeRepository
from typing import Literal
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
                    limit=30,
                    score_threshold=score_thresold,
                    scroll_batch=1000,
                    query_batch=128
                ), build_type=build_type) # "image", "full", "ingredients"
        
        if os.path.exists(ss.clusters_filename):
            logger.info("Загружаем кластеры из файла...")
            return ss.load_clusters_from_file(), ss.get_image_clusters_mapping()
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
    os.makedirs("history", exist_ok=True)
    with open(filename, "w") as f:
        json.dump(clusters, f)

def load_clusters_from_history(filename: str) -> list[list[int]]:
    if not os.path.exists(filename):
        return []
    with open(filename, "r") as f:
        return json.load(f)

async def run_merge_with_same_lang(score_thresold: float, 
                    build_type: Literal["image", "full", "ingredients"],
                    max_variations: int = 3, 
                    validate_gpt: bool = True, 
                    save_to_db: bool = True, 
                    max_merged_recipes: int = 4, 
                    merge_from_olap: bool = True):
    
    cluster_processing_history = os.path.join("history", f"unprocessed_clusters_{build_type}_{score_thresold}.json")
    existing_clusters = load_clusters_from_history(cluster_processing_history)

    merger = ClusterVariationGenerator(score_threshold=score_thresold, clusters_build_type=build_type)
    clusters, cluster_mapping = await create_clusters(score_thresold, build_type)
    if build_type == "image":
        cluster_mapping = cluster_mapping.get("page_to_image", {})

    if existing_clusters:
        logger.info(f"Загружено {len(existing_clusters)} кластеров из истории, пропускаем уже обработанные...")
        processed_set = {tuple(sorted(cluster)) for cluster in existing_clusters}
        clusters = [cluster for cluster in clusters if tuple(sorted(cluster)) not in processed_set]
        logger.info(f"Осталось {len(clusters)} кластеров для обработки после фильтрации истории.")

    merge_function = merger.create_variations_from_olap if merge_from_olap else merger.create_variations_with_same_lang

    for cluster in clusters:
        if len(cluster) < 2:
            continue  # пропускаем одиночки
        image_ids = None
        if build_type == "image":
            cluster_key = ','.join(map(str, sorted(cluster)))
            image_ids = cluster_mapping.get(cluster_key)
        try:
            merged_recipe = await merge_function(
                cluster, 
                validate_gpt=validate_gpt, 
                save_to_db=save_to_db, 
                max_variations=max_variations,
                max_merged_recipes=max_merged_recipes,
                image_ids=image_ids
                )
            if merged_recipe:
                logger.info(f"Created {len(merged_recipe)} variations.")

            # сохраняем на каждой итерации чтобы неп отерять прогресс
            existing_clusters.append(cluster)
            save_clusters_to_history(existing_clusters, cluster_processing_history)
        except Exception as e:
            logger.error(f"Error merging cluster with pages {cluster}: {e}")

def view_recipes(merge_recipe_id: int = 534):
    mr = MergedRecipeRepository()
    merged_recipes = mr.get_by_id_with_images(merge_recipe_id)
    img_urls = [img.id for img in merged_recipes.images] if merged_recipes and merged_recipes.images else []
    logger.info(f"Merged Recipe ID: {merged_recipes.id if merged_recipes else 'Not Found'}")
    logger.info(f"Image URLs: {img_urls}")   

if __name__ == "__main__":
    from dotenv import load_dotenv # загружаем для доступа к .env переменным
    load_dotenv()

    parser = argparse.ArgumentParser(description="Cluster recipes based on similarity.")
    parser.add_argument(
        "--score_threshold",
        type=float,
        default=0.95,
        help="Score threshold for clustering (default: 0.95)"
    )
    parser.add_argument(
        "--build_type",
        type=str,
        choices=["image", "full", "ingredients"],
        default="full",
        help="Type of build for clustering (default: full)"
    )
    args = parser.parse_args()

    asyncio.run(run_merge_with_same_lang(args.score_threshold, args.build_type))