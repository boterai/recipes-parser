"""
скрипт для разбиения на кластеры в оснвоном нужен для тетсирвоаняи наилучшего ращбиения на класеры
"""
import sys
from pathlib import Path
import logging
import asyncio

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.stages.search.similarity import SimilaritySearcher, ClusterParams, build_clusters_from_dsu
from config.config import config

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)


if __name__ == '__main__':
    import dotenv
    dotenv.load_dotenv()
    # скорее всего наиболее оптимальный варинат 0.89 0.91 для разбиения на кластеры
    config.QDRANT_COLLECTION_PREFIX = "recipes2" # для тестирования кластеризации лучше использовать отдельную коллекцию, чтобы не мешать основным данным и иметь возможность экспериментировать с параметрами кластеризации

    for score_threshold, density in [(0.88, 0.92), (0.9, 0.92), (0.88, 0.91), (0.89, 0.91), (0.88, 0.9), (0.91, 0.93)]: # можно поэкспериментировать с этими параметрами для получения оптимального количества кластеров и их качества
        while True:
            ss = SimilaritySearcher(params=ClusterParams(
                        limit=40,
                        score_threshold=score_threshold,
                        scroll_batch=3500,
                        min_cluster_size=4,
                        union_top_k=15,
                        non_mutual_top_k=6,
                        query_batch=128,
                        density_min_similarity=density,
                        max_async_tasks=15,
                    ), build_type="full") # "image", "full", "ingredients"
            #ss.save_validated_centroids_to_databsae(batch_size=10, allow_update=True) # можно не расширяя существущие кластеры обогатить их
            try:
                ss.load_dsu_state()
                last_id = ss.last_id # получаем last id после загрузки состояния (такая штука работает только опираясь на тот факт, что каждй вновь доавбленный рецепт имеет id не меньше уже векторизованных рецептов, иначе рецепты могут быть пропущены)
                clusters = asyncio.run(ss.build_clusters_async())
                ss.save_dsu_state()
                print(f"Total clusters found: {len(clusters)}")
                print("Last processed ID:", ss.last_id)
                asyncio.run(ss.save_clusters_to_file(clusters))
                if last_id == ss.last_id: # конец обработки тк id не поменялся, значи новых значений нет
                    logger.info("Processing complete.")
                    break
            except Exception as e:
                logger.error(f"Error during cluster building: {e}")
                continue

        final_clusters = build_clusters_from_dsu(ss.dsu, min_cluster_size=4)
        asyncio.run(ss.save_clusters_to_file(final_clusters, recalculate_mapping=True, refine_clusters=True))