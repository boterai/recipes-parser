from typing import Optional
from src.repositories.base import BaseRepository
from src.models.cluster_page import ClusterPageORM, ClusterPage
from src.models.merged_recipe import MergedRecipeORM
from src.models.page import PageORM
from src.common.db.connection import get_db_connection
from sqlalchemy import func
import logging

logger = logging.getLogger(__name__)

class ClusterPageRepository(BaseRepository[ClusterPageORM]):

    def __init__(self, mysql_manager=None):
        # Используем общее подключение если не передано явно
        if mysql_manager is None:
            mysql_manager = get_db_connection()
        super().__init__(ClusterPageORM, mysql_manager)

    def add_cluster_pages_batch(
        self, 
        clusters: dict[int, list[int]]  # {centroid_page_id: [page_id1, page_id2, ...]}
    ) -> dict[int, int]:
        """
        Batch-добавление нескольких кластеров за один раз.
        
        Args:
            clusters: словарь {centroid_page_id: [список page_ids в кластере]}
        
        Returns:
            Dict[int, int]: {centroid_page_id: cluster_id}
        """
        if not clusters:
            return {}
        
        session = self.get_session()
        result_mapping = {}
        
        # Собираем все page_ids для одного запроса
        all_page_ids = set()
        for centroid, pages in clusters.items():
            all_page_ids.update(pages)
            if centroid not in pages:
                raise ValueError(f"Центроид {centroid} должен быть в списке страниц")
            
        existing_page_ids = {row[0] for row in session.query(PageORM.id).filter(PageORM.id.in_(all_page_ids)).all()}
        
        missing_page_ids = all_page_ids - existing_page_ids
        if missing_page_ids:
            logger.warning(f"Следующие page_id не найдены в БД и будут пропущены: {missing_page_ids}")
            # Удаляем отсутствующие page_id из кластеров
            for centroid, pages in clusters.items():
                clusters[centroid] = [pid for pid in pages if pid in existing_page_ids]
        
        # Находим существующие связи одним запросом
        existing = session.query(ClusterPageORM).filter(
            ClusterPageORM.page_id.in_(all_page_ids)
        ).all()
        
        # Группируем по page_id для быстрого поиска
        existing_by_page = {cp.page_id: cp for cp in existing}
        
        # Определяем максимальный cluster_id для генерации новых
        max_cluster_id = session.query(func.max(ClusterPageORM.cluster_id)).scalar() or 0
        next_cluster_id = max_cluster_id + 1
        
        # Подготавливаем batch для вставки
        records_to_insert = []
        centroids_to_update = []  # [(cluster_id, old_centroid_page_id, new_centroid_page_id)]
        
        for centroid_page_id, page_ids in clusters.items():
            # Проверяем есть ли страницы этого кластера уже в БД
            existing_clusters = set()
            for page_id in page_ids:
                if page_id in existing_by_page:
                    existing_clusters.add(existing_by_page[page_id].cluster_id)
            
            if len(existing_clusters) > 1:
                logger.warning(f"Страницы кластера с центроидом {centroid_page_id} принадлежат разным кластерам: {existing_clusters}. Скорее всего созданный кластер включает в себя более мелкие из другой выборки.")
                continue
            
            # Определяем cluster_id
            if existing_clusters:
                cluster_id = existing_clusters.pop()
                
                # Проверяем нужно ли сменить центроид
                old_centroid = next(
                    (cp for cp in existing if cp.cluster_id == cluster_id and cp.is_centroid),
                    None
                )
                if old_centroid and old_centroid.page_id != centroid_page_id:
                    centroids_to_update.append((cluster_id, old_centroid.page_id, centroid_page_id))
            else:
                cluster_id = next_cluster_id
                next_cluster_id += 1
            
            result_mapping[centroid_page_id] = cluster_id
            
            # Готовим записи для вставки (только новые страницы)
            for page_id in page_ids:
                if page_id not in existing_by_page or existing_by_page[page_id].cluster_id != cluster_id:
                    records_to_insert.append({
                        'cluster_id': cluster_id,
                        'page_id': page_id,
                        'is_centroid': (page_id == centroid_page_id)
                    })
        
        # Batch insert
        if records_to_insert:
            session.bulk_insert_mappings(ClusterPageORM, records_to_insert)
        
        # Обновляем центроиды
        for cluster_id, old_centroid_id, new_centroid_id in centroids_to_update:
            # Сбрасываем старый
            session.query(ClusterPageORM).filter(
                ClusterPageORM.cluster_id == cluster_id,
                ClusterPageORM.page_id == old_centroid_id
            ).update({"is_centroid": False}, synchronize_session=False)
            
            # Устанавливаем новый
            session.query(ClusterPageORM).filter(
                ClusterPageORM.cluster_id == cluster_id,
                ClusterPageORM.page_id == new_centroid_id
            ).update({"is_centroid": True}, synchronize_session=False)
        
        session.commit()
        return result_mapping

    def add_cluster_pages(self, page_ids: list[int], cluster_centroid_page_id: int) -> list[int]:
        """Обёртка над batch-методом для одиночных кластеров"""
        result = self.add_cluster_pages_batch({cluster_centroid_page_id: page_ids})
        return result[cluster_centroid_page_id]
    
    def get_similar_pages(self, page_id: int) -> list[int]:
        """Получить страницы, принадлежащие тому же кластеру, что и данная страница"""
        session = self.get_session()
        try:
            cluster_id_subquery = (
                session.query(ClusterPageORM.cluster_id)
                .filter(ClusterPageORM.page_id == page_id)
                .scalar_subquery()
            )

            similar_pages = (
                session.query(ClusterPageORM.page_id)
                .filter(
                    ClusterPageORM.cluster_id == cluster_id_subquery,
                    ClusterPageORM.page_id != page_id 
                )
                .all()
            )

            return [pid for (pid,) in similar_pages]
        finally:
            session.close()

    def get_clusters_for_pages(self, page_ids: list[int]) -> dict[int, int]:
        """Получить mapping {page_id: cluster_id} для списка page_id"""
        session = self.get_session()
        try:
            clusters = (
                session.query(ClusterPageORM.page_id, ClusterPageORM.cluster_id)
                .filter(ClusterPageORM.page_id.in_(page_ids))
                .all()
            )
            parsed_pages = dict(clusters)  # {page_id: cluster_id}
            for page_id in page_ids:
                if page_id not in parsed_pages:
                    parsed_pages[page_id] = None  # Явно указываем, что кластер не найден
            return parsed_pages
        finally:
            session.close()

    def get_cluster_count(self) -> int:
        """Получить общее количество кластеров"""
        session = self.get_session()
        try:
            count = session.query(func.count(func.distinct(ClusterPageORM.cluster_id))).scalar()
            return count
        finally:
            session.close()

    def get_clusters(self, limit: int = 10, last_cluster_id: Optional[int] = None) -> tuple[dict[int, list[int]], Optional[int]]:
        """
        Получить кластеры с их страницами.
        
        Args:
            limit: максимальное количество кластеров для возврата
            last_cluster_id: если указано, возвращать только кластеры с id > last_cluster_id
            
        Returns:
            Tuple of (Dict[int, List[int]], Optional[int]): ({centroid_page_id: [page_id1, page_id2, ...]}, last_cluster_id)
        """
        session = self.get_session()
        try:
            query = (
                session.query(ClusterPageORM.cluster_id, ClusterPageORM.page_id)
                .filter(ClusterPageORM.is_centroid == True)
            )
            if last_cluster_id is not None:
                query = query.filter(ClusterPageORM.cluster_id > last_cluster_id)
            centroids = query.order_by(ClusterPageORM.cluster_id).limit(limit).all()

            if not centroids:
                return {}, None

            # cluster_id -> centroid_page_id, без лишних запросов
            cluster_to_centroid = dict(centroids)  # {cluster_id: centroid_page_id}
            cluster_ids = list(cluster_to_centroid.keys())

            cluster_pages = (
                session.query(ClusterPageORM.cluster_id, ClusterPageORM.page_id)
                .filter(ClusterPageORM.cluster_id.in_(cluster_ids))
                .all()
            )

            result = {}
            for cluster_id, page_id in cluster_pages:
                centroid_page_id = cluster_to_centroid[cluster_id]
                if centroid_page_id not in result:
                    result[centroid_page_id] = []
                result[centroid_page_id].append(page_id)

            return result, max(cluster_ids)
        finally:
            session.close()

    def get_clusters_without_merged_recipes(self, limit: int = 10, last_cluster_id: Optional[int] = None) -> tuple[dict[int, list[int]], Optional[int]]:
        """
        Получить кластеры, центроиды которых не имеют merged_recipes.
        
        Args:
            limit: максимальное количество кластеров для возврата
            last_cluster_id: если указано, возвращать только кластеры с id > last_cluster_id
            
        Returns:
            Tuple of (Dict[int, List[int]], Optional[int]): ({centroid_page_id: [page_id1, page_id2, ...]}, last_cluster_id)
        """
        session = self.get_session()
        try:
            
            # Находим центроиды без merged_recipes
            query = (
                session.query(
                    ClusterPageORM.cluster_id,
                    ClusterPageORM.page_id
                )
                .outerjoin(
                    MergedRecipeORM,
                    ClusterPageORM.page_id == MergedRecipeORM.base_recipe_id
                )
                .filter(
                    MergedRecipeORM.id.is_(None),
                    ClusterPageORM.is_centroid == True
                )
            )
            
            if last_cluster_id is not None:
                query = query.filter(ClusterPageORM.cluster_id > last_cluster_id)
            
            orphan_centroids = query.order_by(ClusterPageORM.cluster_id).limit(limit).all()
            
            if not orphan_centroids:
                return {}, None
            
            # Маппинг cluster_id -> centroid_page_id
            cluster_to_centroid = dict(orphan_centroids)
            cluster_ids = list(cluster_to_centroid.keys())
            
            # Получаем все page_ids для этих кластеров
            cluster_pages = (
                session.query(
                    ClusterPageORM.cluster_id,
                    ClusterPageORM.page_id
                )
                .filter(ClusterPageORM.cluster_id.in_(cluster_ids))
                .all()
            )
            
            # Группируем по centroid_page_id
            result = {}
            for cluster_id, page_id in cluster_pages:
                centroid_page_id = cluster_to_centroid[cluster_id]
                if centroid_page_id not in result:
                    result[centroid_page_id] = []
                result[centroid_page_id].append(page_id)
            
            return result, max(cluster_ids)
        finally:
            session.close()
        