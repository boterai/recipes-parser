from src.repositories.base import BaseRepository
from src.models.cluster_page import ClusterPageORM, ClusterPage
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
                raise ValueError(
                    f"Страницы для центроида {centroid_page_id} принадлежат "
                    f"разным кластерам: {existing_clusters}"
                )
            
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

    def add_cluster_pages(self, page_ids: list[int], cluster_centroid_page_id: int) -> int:
        """Обёртка над batch-методом для одиночных кластеров"""
        result = self.add_cluster_pages_batch({cluster_centroid_page_id: page_ids})
        return result[cluster_centroid_page_id]
        
