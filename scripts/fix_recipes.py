import sys
from pathlib import Path
# Добавление корневой директории в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

import hashlib
from collections import Counter
from src.repositories.cluster_page import ClusterPageRepository
from src.repositories.merged_recipe import MergedRecipeRepository, MergedRecipePagesRepository
import random
import logging


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(threadName)s] - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)
def get_most_appear_id(clusters: list[int]) -> int | None:
    count = Counter(clusters)
    most_common = count.most_common(1)
    if most_common:
        return most_common[0][0]
    return None

def main():
    cluster_page_repo = ClusterPageRepository()
    mr = MergedRecipeRepository()
    mrp = MergedRecipePagesRepository()

    while True:
        dat  = cluster_page_repo.get_merged_recipes_with_multiple_clusters(20)
        for item in dat:
            _, _, clusters, merge_recipe_id = item
            logger.info(f"Processing MergedRecipe ID: {merge_recipe_id} with clusters: {clusters}")
            cluster_ids = [int(cid) for cid in clusters.split(',')]
            most_appear = get_most_appear_id(cluster_ids)
            logger.info(f"Most appearing cluster ID for MergedRecipe ID {merge_recipe_id}: {most_appear}")
            if most_appear is not None:
                excluded_page_ids = mr.get_pages_in_other_clusters(merge_recipe_id, most_appear)
                merged_recipe = mr.get_by_id(merge_recipe_id)
                new_pages = sorted([int(i) for i in merged_recipe.pages_csv.split(',') if int(i) not in excluded_page_ids])
                if not new_pages:
                    mr.delete(merge_recipe_id)
                    continue
                if merged_recipe.base_recipe_id in excluded_page_ids:
                    merged_recipe.base_recipe_id = random.choice(new_pages) if new_pages else None
                merged_recipe.pages_csv = ','.join(map(str, new_pages))
                merged_recipe.pages_hash_sha256 = hashlib.sha256(merged_recipe.pages_csv.encode()).hexdigest()
                merged_recipe.recipe_count = len(new_pages)
                deleted_count = mrp.delete_by_page_ids_and_merge_recipe(excluded_page_ids, merge_recipe_id)
                if deleted_count != len(excluded_page_ids):
                    logger.warning(f"Deleted {deleted_count} MergedRecipePages, but expected to delete {len(excluded_page_ids)} for MergedRecipe ID: {merge_recipe_id}")
                try:
                    mr.update(merged_recipe)
                except Exception as e:
                    logger.error(f"Error updating MergedRecipe ID {merge_recipe_id}: {e}")
                    continue


def add_new_clusters():
    import json
    from itertools import batched
    repo = ClusterPageRepository(table_name="cluster_page_89")
    clusters = json.load(open("clusters/recipes2/full_clusters_0.89_0.91.json", "r"))
    for batch in batched(clusters, 100):
        cluster_batch = {}
        for cluster in batch:
            cluster_batch[random.choice(cluster)] = cluster
        repo.create_update_cluster_pages_batch(cluster_batch, update=False)





if __name__ == "__main__":
    add_new_clusters()