import sys
import logging
from pathlib import Path
import argparse
import asyncio
import os
import json
# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.stages.search.similarity import SimilaritySearcher, ClusterParams, build_clusters_from_dsu
from src.stages.merge.merge import ClusterVariationGenerator
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

async def create_clusters(score_thresold: float, build_type: Literal["image", "full", "ingredients"]) -> list[list[int]]:
    while True:
        ss = SimilaritySearcher(params=ClusterParams(
                    limit=30,
                    score_threshold=score_thresold,
                    scroll_batch=1000,
                    query_batch=128
                ), build_type=build_type) # "image", "full", "ingredients"
        
        if os.path.exists(ss.clusters_filename):
            logger.info("Загружаем кластеры из файла...")
            return ss.load_clusters_from_file()
        try:
            ss.load_dsu_state()
            clusters = await ss.build_clusters_async()
            ss.save_dsu_state()
            print(f"Total clusters found: {len(clusters)}")
            print("Last processed ID:", ss.last_id)
            ss.save_clusters_to_file(clusters)
            if ss.last_id is None:
                logger.info("Processing complete.")
                break
        except Exception as e:
            logger.error(f"Error during cluster building: {e}")
            ss.save_dsu_state()
            continue

    final_clusters = build_clusters_from_dsu(ss.dsu, min_cluster_size=2)
    ss.save_clusters_to_file(final_clusters)
    return final_clusters

def save_clusters_to_history(clusters: list[list[int]], filename: str):
    os.makedirs("history", exist_ok=True)
    with open(filename, "w") as f:
        json.dump(clusters, f)

def load_clusters_from_history(filename: str) -> list[list[int]]:
    if not os.path.exists(filename):
        return []
    with open(filename, "r") as f:
        return json.load(f)

async def run_merge(score_thresold: float, 
                    build_type: Literal["image", "full", "ingredients"],
                    max_variations: int = 3, 
                    validate_gpt: bool = True, 
                    save_to_db: bool = True, 
                    max_merged_recipes: int = 4):
    
    cluster_processing_history = os.path.join("history", f"unprocessed_clusters_{build_type}_{score_thresold}.json")
    existing_clusters = load_clusters_from_history(cluster_processing_history)

    merger = ClusterVariationGenerator(score_threshold=score_thresold, clusters_build_type=build_type)
    clusters = await create_clusters(score_thresold, build_type)

    if existing_clusters:
        logger.info(f"Загружено {len(existing_clusters)} кластеров из истории, пропускаем уже обработанные...")
        processed_set = {tuple(sorted(cluster)) for cluster in existing_clusters}
        clusters = [cluster for cluster in clusters if tuple(sorted(cluster)) not in processed_set]
        logger.info(f"Осталось {len(clusters)} кластеров для обработки после фильтрации истории.")

    for cluster in clusters:
        try:
            merged_recipe = await merger.create_variations_with_same_lang(
                cluster, 
                validate_gpt=validate_gpt, 
                save_to_db=save_to_db, 
                max_variations=max_variations,
                max_merged_recipes=max_merged_recipes
                )
            if merged_recipe:
                logger.info(f"Created {len(merged_recipe)} variations.")

            # сохраняем на каждой итерации чтобы неп отерять прогресс
            existing_clusters.append(cluster)
            save_clusters_to_history(existing_clusters, cluster_processing_history)
        except Exception as e:
            logger.error(f"Error merging cluster with pages {cluster}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cluster recipes based on similarity.")
    parser.add_argument(
        "--score_threshold",
        type=float,
        default=0.94,
        help="Score threshold for clustering (default: 0.94)"
    )
    parser.add_argument(
        "--build_type",
        type=str,
        choices=["image", "full", "ingredients"],
        default="ingredients",
        help="Type of build for clustering (default: full)"
    )
    args = parser.parse_args()

    asyncio.run(run_merge(args.score_threshold, args.build_type))