from typing import Optional
from src.repositories.base import BaseRepository
from src.models.cluster_page import ClusterPageORM, ClusterPage
from src.models.merged_recipe import MergedRecipeORM
from src.models.page import PageORM
from sqlalchemy.orm import Session
from src.common.db.connection import get_db_connection
from sqlalchemy import func, or_, case
import logging
from collections import defaultdict 

logger = logging.getLogger(__name__)

class ClusterPageRepository(BaseRepository[ClusterPageORM]):

    def __init__(self, mysql_manager=None):
        # Используем общее подключение если не передано явно
        if mysql_manager is None:
            mysql_manager = get_db_connection()
        super().__init__(ClusterPageORM, mysql_manager)


    def get_existing_pages_for_clusters(self, clusters: dict[int, list[int]]) -> set[int]:
        session = self.get_session()
        all_page_ids = {i for pages in clusters.values() for i in pages}
            
        existing_page_ids = {row[0] for row in session.query(PageORM.id).filter(PageORM.id.in_(all_page_ids)).all()}
        
        missing_page_ids = all_page_ids - existing_page_ids
        if missing_page_ids:
            logger.warning(f"Следующие page_id не найдены в БД и будут пропущены: {missing_page_ids}")
            # Удаляем отсутствующие page_id из кластеров
            for centroid, pages in clusters.items():
                clusters[centroid] = [pid for pid in pages if pid in existing_page_ids]

        # Находим существующие связи одним запросом
        return session.query(ClusterPageORM).filter(
            ClusterPageORM.page_id.in_(all_page_ids)
        ).all()

    def get_max_cluster_id(self) -> int:
        session = self.get_session()
        try:
            max_cluster_id = session.query(func.max(ClusterPageORM.cluster_id)).scalar()
            return max_cluster_id or 0
        finally:
            session.close()    

    def create_update_cluster_pages_batch(
        self, 
        clusters: dict[int, list[int]],  # {centroid_page_id: [page_id1, page_id2, ...]}
        update: bool = True
    ) -> dict[int, int]:
        """
        Batch-обновление/создание нескольких кластеров за один раз.
        
        Args:
            clusters: словарь {centroid_page_id: [список page_ids в кластере]}
            update: если True, разрешает обновление существующих кластеров (включая смену центроида), если False, пропускает кластеры, страницы которых уже принадлежат другому кластеру
        
        Returns:
            Dict[int, int]: {centroid_page_id: cluster_id}
        """
        if not clusters:
            return {}
        
        session = self.get_session()
        result_mapping = {}
        
        all_page_ids = {i for pages in clusters.values() for i in pages}

        # Находим существующие связи одним запросом
        existing = session.query(ClusterPageORM).filter(
            ClusterPageORM.page_id.in_(all_page_ids)
        ).all()
    
        # Собираем все page_ids для одного запроса
        # группируем по page_id для проверки существующих кластеров
        existing_by_page = {cp.page_id: cp for cp in existing}
        
        # Определяем максимальный cluster_id для генерации новых
        next_cluster_id = self.get_max_cluster_id() + 1
        
        # Подготавливаем batch для вставки
        records_to_insert = []
        centroids_to_update = []  # [(cluster_id, old_centroid_page_id, new_centroid_page_id)]
        
        for centroid_page_id, page_ids in clusters.items():
            # Проверяем есть ли страницы этого кластера уже в БД
            existing_clusters = {existing_by_page[pid].cluster_id for pid in page_ids if pid in existing_by_page}

            if len(existing_clusters) == 1 and not update:
                logger.warning(f"Страницы кластера с центроидом {centroid_page_id} уже принадлежат существующему кластеру: {existing_clusters}. Пропускаем этот кластер из-за запрета обновлений.")
                continue
            
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
            
            # Готовим записи для вставки (только новые страницы, расширяем существющий кластер, не создавая дублей)
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
        result = self.create_update_cluster_pages_batch({cluster_centroid_page_id: page_ids})
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

    def get_clusters_with_merged_recipes(self, limit: int = 10, completed_recipes: int = 0, last_cluster_id: Optional[int] = None,
                                        max_agregated_recipes: int = None) -> tuple[dict[int, list[int]], Optional[int]]:
        """
        Получить кластеры, страницы которых имеют не больше, чем передано рецептов в MergedRecipeORM (по умолчанию 0, то есть без merged рецептов).
        
        Args:
            limit: максимальное количество кластеров для возврата
            completed_recipes: максимальное количество merged рецептов, связанных со страницами кластера (по умолчанию 0, то есть без merged рецептов)
            last_cluster_id: если указано, возвращать только кластеры с id > last_cluster_id
            recipes_per_merged: если указано, фильтровать страницы, у которых в MergedRecipeORM количество рецептов для merged рецепта больше или равно этому числу. готовым считается рецепт, содержащий в себе более, чем указано страниц
            
        Returns:
            Tuple of (Dict[int, List[int]], Optional[int]): ({centroid_page_id: [page_id1, page_id2, ...]}, last_cluster_id)
        """
        session = self.get_session()
        try:
            
            # Находим кластеры по количеству merged_recipes
            completed_col = func.count(MergedRecipeORM.base_recipe_id).label('completed_recipes')
            
            # Считаем только "готовые" рецепты через CASE WHEN
            completed_col = func.count(
                case((MergedRecipeORM.recipe_count >= max_agregated_recipes, 1))
            ).label('completed_recipes') if max_agregated_recipes is not None else func.count(MergedRecipeORM.base_recipe_id).label('completed_recipes')

            query = (
                session.query(
                    ClusterPageORM.cluster_id,
                    func.count(ClusterPageORM.page_id).label('page_ids'),
                    completed_col
                )
                .outerjoin(
                    MergedRecipeORM,
                    ClusterPageORM.page_id == MergedRecipeORM.base_recipe_id
                )
                .group_by(ClusterPageORM.cluster_id)
                .having(completed_col <= completed_recipes)  # фильтр ПОСЛЕ группировки
                .order_by(ClusterPageORM.cluster_id)
            )

            if last_cluster_id is not None:
                query = query.filter(ClusterPageORM.cluster_id > last_cluster_id)

            cluster_results = query.limit(limit).all()

            if not cluster_results:
                return {}, None

            cluster_ids = [r.cluster_id for r in cluster_results]

            cluster_pages = (
                session.query(
                    ClusterPageORM.cluster_id, 
                    ClusterPageORM.page_id,
                    ClusterPageORM.is_centroid
                )
                .filter(ClusterPageORM.cluster_id.in_(cluster_ids))
                .all()
            )
            
            # Группируем по centroid_page_id
            cluster_id_to_centroid: dict[int, int] = {}
            pages_by_cluster: dict[int, list[int]] = defaultdict(list)

            for cluster_id, page_id, is_centroid in cluster_pages:
                if is_centroid:
                    cluster_id_to_centroid[cluster_id] = page_id
                pages_by_cluster[cluster_id].append(page_id)

            result: dict[int, list[int]] = {}
            for cluster_id, page_ids in pages_by_cluster.items():
                centroid_page_id = cluster_id_to_centroid.get(cluster_id)
                if centroid_page_id is None:
                    logger.warning(f"Кластер с id {cluster_id} не имеет центроида, пропускаем его страницы")
                    continue
                result[centroid_page_id] = page_ids

            return result, max(cluster_ids)
        finally:
            session.close()
        