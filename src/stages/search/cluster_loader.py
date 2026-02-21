
import logging 

import os
import json
from config.config import config

logger = logging.getLogger(__name__)

class LocalClusterLoader:
    """
    хранит истории обработки для возможности не наичнать каждый раз обработку с самого начала
    """
    def __init__(self, build_type: str, score_threshold: float, density_min_similarity: float):
        self.build_type = build_type
        self.score_threshold = score_threshold
        self.density_min_similarity = density_min_similarity

        self.path_dsu = os.path.join("recipe_clusters", f"dsu_state_{build_type}_{self.score_threshold}.json")
        self.path_clusters = os.path.join("recipe_clusters", f"{build_type}_clusters_{self.score_threshold}_{self.density_min_similarity}.json")
        self.path_image_mapping = os.path.join("recipe_clusters", f"clusters_to_image_ids_{self.score_threshold}_{self.density_min_similarity}.json")
        self.path_validated_centroids = os.path.join("recipe_clusters", f"{build_type}_centroids_{self.score_threshold}_{self.density_min_similarity}.json")
        self.path_validated_centroids_history = os.path.join("recipe_clusters", f"{build_type}_refined_history_{self.score_threshold}_{self.density_min_similarity}.json")

    @staticmethod
    def load_json_file(filename: str) -> dict:
        if not os.path.exists(filename):
            logger.info(f"File {filename} does not exist. Returning empty dict.")
            return {}
        
        with open(filename, 'r') as f:
            try:
                data = json.load(f)
                logger.info(f"Loaded data from {filename}.")
                return data
            except json.JSONDecodeError:
                logger.warning(f"File {filename} is empty or corrupted. Returning empty dict.")
                return {}
    
    @staticmethod
    def save_json_file(filename: str, data: dict):
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
            logger.info(f"Saved data to {filename}.")

    def load_image_cluster_mapping(self) -> dict:
        return self.load_json_file(self.path_image_mapping)
    
    def save_image_cluster_mapping(self, mapping: dict): 
        self.save_json_file(self.path_image_mapping, mapping)

    def load_clusters(self) -> dict:
        return self.load_json_file(self.path_clusters)
    
    def save_clusters(self, clusters: dict):
        self.save_json_file(self.path_clusters, clusters)

    def save_dsu_state(self, dsu_state: dict):
        self.save_json_file(self.path_dsu, dsu_state)

    def load_dsu_state(self) -> dict:
        return self.load_json_file(self.path_dsu)
    
    def save_validated_centroids(self, centroids: dict):
        if not centroids:
            logger.info(f"No validated centroids to save. Skipping saving to {self.path_validated_centroids}.")
            return
        self.save_json_file(self.path_validated_centroids, centroids)

    def load_validated_centroids(self) -> dict:
        centroids = self.load_json_file(self.path_validated_centroids)
        if not centroids:
            logger.info(f"No validated centroids found in {self.path_validated_centroids}. Starting with empty dict.")
        
        centroids = {int(k): v for k, v in centroids.items()}
        return centroids
    
    def save_validated_centroids_history(self, history: dict):
        if not history:
            logger.info(f"No validated centroids history to save. Skipping saving to {self.path_validated_centroids_history}.")
            return
        self.save_json_file(self.path_validated_centroids_history, history)
    
    def load_validated_centroids_history(self) -> dict:
        history = self.load_json_file(self.path_validated_centroids_history)
        if not history:
            logger.info(f"No validated centroids history found in {self.path_validated_centroids_history}. Starting with empty dict.")
            return {}
        return history
    
    def retrieve_unvalidated_clusters_with_centroids_and_history(self, clusters: list[set[int]]) -> tuple[list[list[int]], dict[int, list[int]], dict[str, list[int]]]:
        """
            Returns
            - Список кластеров, которые не были проверены (их ключей нет в истории)
            - Словарь валидированных центроидов для кластеров, которые были проверены
            - Историю проверенных кластеров и их центроидов
        
        """
        logger.info(f"Retrieving unvalidated clusters. Total clusters: {len(clusters)}")
        history = self.load_validated_centroids_history()
        if not history:
            return clusters, {}, {}
        

        validated_centroids = self.load_validated_centroids()
            
        cluster_keys = {','.join(map(str, sorted(cluster))): cluster for cluster in clusters}
        
        for history_key, centroids in history.items(): # удаляем из кластеров те, что уже были проверены и их центроиды, тк кластер мог измениться и они могли стать невалидными
            if history_key in cluster_keys:
                clusters.remove(cluster_keys[history_key])
            else:
                for centroid_page_id in centroids: # удаляем все центроилы, елси кластер изменился и не найден
                    if centroid_page_id in validated_centroids:
                        del validated_centroids[centroid_page_id]
        logger.info(f"Unvalidated clusters retrieved: {len(clusters)}. Validated centroids: {len(validated_centroids)}. History entries: {len(history)}.")
        return clusters, validated_centroids, history
