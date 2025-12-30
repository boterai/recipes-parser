import logging
from sqlalchemy import func

from src.repositories.base import BaseRepository
from src.models.similarity import RecipeSimilarityORM, RecipeClusterORM, calculate_pages_csv_and_hash
from src.common.db.connection import get_db_connection

logger = logging.getLogger(__name__)


class RecipeClusterSimilarity(BaseRepository[RecipeClusterORM]):
    """Репозиторий для работы с похожестью рецептов в кластерах"""
    
    def __init__(self, mysql_manager=None):
        # Используем общее подключение если не передано явно
        if mysql_manager is None:
            mysql_manager = get_db_connection()
        super().__init__(RecipeClusterORM, mysql_manager)

    def find_by_pages(self, pages: list[int]) -> RecipeClusterORM | None:
        """Находит кластер по SHA256 хешу страниц"""
        _, pages_hash_sha256 = calculate_pages_csv_and_hash(pages)
        session = self.get_session()
        try:
            cluster = (
                session.query(RecipeClusterORM)
                .filter(RecipeClusterORM.pages_hash_sha256 == pages_hash_sha256)
                .first()
            )
            return cluster
        finally:
            session.close()


class RecipeSimilarity(BaseRepository[RecipeSimilarityORM]):
    """Репозиторий для работы со страницами"""
    
    def __init__(self, mysql_manager=None):
        # Используем общее подключение если не передано явно
        if mysql_manager is None:
            mysql_manager = get_db_connection()
        super().__init__(RecipeSimilarityORM, mysql_manager)
        self.cluster_repo = RecipeClusterSimilarity(mysql_manager=mysql_manager)

    def find_cluster_by_exact_members(self, page_ids: list[int]) -> int | None:
        """Находит cluster_id, если существует кластер с точно таким набором page_ids.
        
        Returns:
            cluster_id если найден кластер с точно этими page_ids, иначе None
        """
        cluster = self.cluster_repo.find_by_pages(page_ids)
        return cluster.id if cluster else None

    def save_cluster_with_members(self, page_ids: list[int]) -> int | None:
        """Сохраняет кластер и все связи membership в одной транзакции.
        
        Args:
            page_ids: список page_id, которые входят в кластер
            
        Returns:
            cluster_id созданного кластера или None при ошибке
        """
        if not page_ids:
            logger.warning("Cannot save empty cluster")
            return None
        
        # Проверяем, не существует ли уже такой кластер
        existing_cluster = self.cluster_repo.find_by_pages(page_ids)
        if existing_cluster:
            logger.info(f"Cluster with pages {page_ids} already exists (id={existing_cluster.id})")
            return existing_cluster.id
        
        session = self.get_session()
        try:
            # 1. Создаём запись кластера
            pages_csv, pages_hash = calculate_pages_csv_and_hash(page_ids)
            cluster_orm = RecipeClusterORM(
                pages_csv=pages_csv,
                pages_hash_sha256=pages_hash
            )
            session.add(cluster_orm)
            session.flush()  # Получаем cluster_id до коммита
            
            cluster_id = cluster_orm.id
            logger.info(f"Created cluster {cluster_id} with {len(page_ids)} members")
            
            # 2. Создаём записи membership (recipe_similarities)
            for page_id in page_ids:
                member_orm = RecipeSimilarityORM(
                    cluster_id=cluster_id,
                    page_id=page_id
                )
                session.add(member_orm)
            
            session.commit()
            logger.info(f"Saved cluster {cluster_id} with {len(page_ids)} members successfully")
            return cluster_id
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving cluster with members: {e}")
            raise
        finally:
            session.close()