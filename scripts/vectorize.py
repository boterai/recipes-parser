"""
Скрипт для векторизации рецептов из БД в Qdrant
"""

import sys
from pathlib import Path
import logging

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.common.embedding import get_embedding_function, get_image_embedding_function
from src.stages.search.vectorise import RecipeVectorizer
from src.models.recipe import Recipe
from src.stages.search.similarity import SimilaritySearcher, ClusterParams, _build_clusters_from_dsu

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

def add_recipes():
    batch_size = 15 # примерный размер батча для векторизации и добавления в Qdrant при котором не происходит timeout
    rv = RecipeVectorizer()

    embed_func, dims = get_embedding_function(batch_size=batch_size)
    rv.add_all_recipes(
        embedding_function=embed_func,
        batch_size=batch_size,
        dims=dims)
    
def search_similar(recipe_id: int = 21427, use_weighted: bool = True,
                   score_threshold: float = 0.0, limit: int = 6):
    """Поиск похожих рецептов для заданного recipe_id и вывод их на экран
    Args:
        recipe_id: ID рецепта для поиска похожих
        use_weighted: использовать ли взвешенный поиск
        score_threshold: порог схожести для фильтрации результатов
        limit: максимальное количество возвращаемых похожих рецептов
    """
    rv = RecipeVectorizer()


    embed_func, _ = get_embedding_function(batch_size=1)
    
    recipe = rv.olap_database.get_recipes_by_ids([recipe_id])
    if not recipe:
        print(f"Recipe with id {recipe_id} not found")
        return
    recipe = recipe[0]
    
    similar_recipes: list[float, Recipe] = []
    if use_weighted:
        similar_recipes = rv.get_similar_recipes_weighted(
            recipe=recipe,
            embed_function=embed_func,
            limit=limit,
            score_threshold=score_threshold
        )
    else:
        similar_recipes = rv.get_similar_recipes_full(
            recipe=recipe,
            embed_function=embed_func,
            limit=limit,
            score_threshold=score_threshold
        )

    if len(similar_recipes) == 0:
        print(f"No similar recipes found for recipe ID {recipe_id}")
        return
    print(f"Похожие рецепты для рецепта ID: {recipe_id} - {recipe.dish_name}:")
    for score, sim_recipe in similar_recipes:
        print(f"ID: {sim_recipe.page_id}, Блюдо: {sim_recipe.dish_name}, Score: {score}")


def create_similarity_clusters(filepath: str, dsu_filepath: str):
    """Создание кластеров похожих рецептов и сохранение их в файл."""
    ss = SimilaritySearcher()
    ss.load_dsu_state(dsu_filepath)
    while True:
        clusters = ss.build_clusters(
            params=ClusterParams(
                max_recipes=1000,
                limit=30,
                score_threshold=0.95,
                scroll_batch=500,
                query_batch=32,
                collection_name="mv",
                using="ingredients",
            )
        )
        ss.save_dsu_state(dsu_filepath)
        print(f"Total clusters found: {len(clusters)}")
        print("Last processed ID:", ss.last_id)
        ss.save_clusters_to_file(filepath, clusters)
        if ss.last_id is None:
            logger.info("Processing complete.")
            break

    final_clusters = _build_clusters_from_dsu(ss.dsu, min_cluster_size=2)
    ss.save_clusters_to_file(filepath, final_clusters)

def check_and_save_similarity_clusters(filepath: str):
    """Проверка наличия недобавленных рецептов в кластеры и сохранение обновлённых кластеров."""
    ss = SimilaritySearcher()
    clusters = ss.load_clusters_from_file(filepath)
    ss.process_and_save_clusters(clusters=clusters, filepath=filepath)

if __name__ == '__main__':
    filepath = "recipe_clusters/full_clusters95_no_batch.txt"
    dsu_filepath = "recipe_clusters/ingredients95_dsu_state.json"
    check_and_save_similarity_clusters(filepath)
    #add_recipes()
    # Векторизация рецептов (по дефолту всех рецептов, содержащихся в clickhouse)
    #search_similar(recipe_id=19, use_weighted=False, score_threshold=0.0, limit=6)
