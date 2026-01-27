"""
Скрипт для векторизации рецептов из БД в Qdrant
"""

import sys
import os
from pathlib import Path
import logging
import asyncio

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.common.embedding import get_embedding_function, get_image_embedding_function
from src.stages.search.vectorise import RecipeVectorizer
from src.models.recipe import Recipe
from src.stages.search.similarity import SimilaritySearcher, ClusterParams, build_clusters_from_dsu
from src.common.embedding import get_image_embedding_function
from src.stages.search.vectorise import RecipeVectorizer
from src.models.image import ImageORM, download_image_async

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

def vectorise_recipes():
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

async def validate_and_save_image(image_url: str, save_dir: str = "images", use_proxy: bool = True) -> str | None:
    """
    Проверяет валидность URL, скачивает изображение и сохраняет локально.
    
    Args:
        image_url: URL изображения для проверки и скачивания
        save_dir: Директория для сохранения (по умолчанию: ./images)
        timeout: Таймаут запроса в секундах
    
    Returns:
        Путь к сохраненному файлу или None при ошибке
    """
    try:
        # Скачиваем изображение как PIL.Image
        img = await download_image_async(image_url, use_proxy=use_proxy)
        if img is None:
            return None
        
        os.makedirs(save_dir, exist_ok=True)
        
        hash_name = ImageORM.hash_url(image_url)[:16]
        
        img_format = img.format or 'JPEG'
        ext = '.jpg' if img_format == 'JPEG' else f'.{img_format.lower()}'
        
        filename = hash_name + ext
        file_path = os.path.join(save_dir, filename)
        
        if img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')
            ext = '.jpg'
            filename = hash_name + ext
            file_path = os.path.join(save_dir, filename)
        
        img.save(file_path, quality=90, optimize=True)
        
        logger.info(f"Saved image: {image_url} -> {file_path}")
        return file_path
        
    except Exception as e:
        logger.error(f"Failed to validate/save image {image_url}: {e}")
        return None

async def vectorise_images():
    rv = RecipeVectorizer()
    embed_function, _ = get_image_embedding_function(
        batch_size=16
    )
    await rv.vectorise_images_async(
        embed_function=embed_function,
        limit=5000
    )

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

    final_clusters = build_clusters_from_dsu(ss.dsu, min_cluster_size=2)
    ss.save_clusters_to_file(filepath, final_clusters)

def check_and_save_similarity_clusters(filepath: str):
    """Проверка наличия недобавленных рецептов в кластеры и сохранение обновлённых кластеров."""
    ss = SimilaritySearcher()
    clusters = ss.load_clusters_from_file(filepath)
    ss.process_and_save_clusters(clusters=clusters, filepath=filepath)

if __name__ == '__main__':
    filepath = "recipe_clusters/full_clusters95_no_batch.txt"
    dsu_filepath = "recipe_clusters/ingredients95_dsu_state.json"
    #check_and_save_similarity_clusters(filepath)
    vectorise_recipes()
    #asyncio.run(vectorise_images())
    # Векторизация рецептов (по дефолту всех рецептов, содержащихся в clickhouse)
    #search_similar(recipe_id=19, use_weighted=False, score_threshold=0.0, limit=6)
