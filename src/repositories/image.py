"""
Репозиторий для работы с изображениями рецептов
"""

import logging
from typing import Optional, List
from sqlalchemy import func

from src.repositories.base import BaseRepository
from src.models.image import ImageORM
from src.common.db.connection import get_db_connection

logger = logging.getLogger(__name__)


class ImageRepository(BaseRepository[ImageORM]):
    """Репозиторий для работы с изображениями рецептов"""
    
    def __init__(self, mysql_manager=None):
        # Используем общее подключение если не передано явно
        if mysql_manager is None:
            mysql_manager = get_db_connection()
        super().__init__(ImageORM, mysql_manager)
    
    def get_by_page_id(self, page_id: int, limit: Optional[int] = None) -> List[ImageORM]:
        """
        Получить все изображения для конкретной страницы
        
        Args:
            page_id: ID страницы
            limit: Максимальное количество изображений
        
        Returns:
            Список изображений
        """
        session = self.get_session()
        try:
            query = session.query(ImageORM).filter(ImageORM.page_id == page_id)
            
            if limit:
                query = query.limit(limit)
            
            return query.all()
        finally:
            session.close()
    
    
    def get_not_vectorised(
        self,
        limit: Optional[int] = None,
        page_id: Optional[int] = None
    ) -> List[ImageORM]:
        """
        Получить невекторизованные изображения
        
        Args:
            limit: Максимальное количество
            page_id: Фильтр по ID страницы (опционально)
        
        Returns:
            Список невекторизованных изображений
        """
        session = self.get_session()
        try:
            query = session.query(ImageORM).filter(ImageORM.vectorised == False)
            
            if page_id:
                query = query.filter(ImageORM.page_id == page_id)
            
            if limit:
                query = query.limit(limit)
            
            return query.all()
        finally:
            session.close()
    
    def get_vectorised(
        self,
        limit: Optional[int] = None,
        page_id: Optional[int] = None
    ) -> List[ImageORM]:
        """
        Получить векторизованные изображения
        
        Args:
            limit: Максимальное количество
            page_id: Фильтр по ID страницы (опционально)
        
        Returns:
            Список векторизованных изображений
        """
        session = self.get_session()
        try:
            query = session.query(ImageORM).filter(ImageORM.vectorised == True)
            
            if page_id:
                query = query.filter(ImageORM.page_id == page_id)
            
            if limit:
                query = query.limit(limit)
            
            return query.all()
        finally:
            session.close()
    
    def mark_as_vectorised(self, image_ids: List[int]) -> int:
        """
        Пометить изображения как векторизованные
        
        Args:
            image_ids: Список ID изображений
        
        Returns:
            Количество обновленных записей
        """
        session = self.get_session()
        try:
            count = session.query(ImageORM).filter(
                ImageORM.id.in_(image_ids)
            ).update(
                {'vectorised': True},
                synchronize_session=False
            )
            session.commit()
            logger.info(f"Помечено {count} изображений как векторизованные")
            return count
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при пометке изображений как векторизованные: {e}")
            raise
        finally:
            session.close()
    
    def get_with_local_path(
        self,
        limit: Optional[int] = None,
        vectorised: Optional[bool] = None
    ) -> List[ImageORM]:
        """
        Получить изображения с локальным путём
        
        Args:
            limit: Максимальное количество
            vectorised: Фильтр по статусу векторизации (опционально)
        
        Returns:
            Список изображений с локальным путём
        """
        session = self.get_session()
        try:
            query = session.query(ImageORM).filter(
                ImageORM.local_path.isnot(None),
                ImageORM.local_path != ''
            )
            
            if vectorised is not None:
                query = query.filter(ImageORM.vectorised == vectorised)
            
            if limit:
                query = query.limit(limit)
            
            return query.all()
        finally:
            session.close()
    
    def count_by_page_id(self, page_id: int) -> int:
        """
        Подсчитать количество изображений для страницы
        
        Args:
            page_id: ID страницы
        
        Returns:
            Количество изображений
        """
        session = self.get_session()
        try:
            return session.query(func.count(ImageORM.id)).filter(
                ImageORM.page_id == page_id
            ).scalar()
        finally:
            session.close()
    
    def delete_by_page_id(self, page_id: int) -> int:
        """
        Удалить все изображения для страницы
        
        Args:
            page_id: ID страницы
        
        Returns:
            Количество удаленных записей
        """
        session = self.get_session()
        try:
            count = session.query(ImageORM).filter(
                ImageORM.page_id == page_id
            ).delete(synchronize_session=False)
            session.commit()
            logger.info(f"Удалено {count} изображений для страницы {page_id}")
            return count
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при удалении изображений: {e}")
            raise
        finally:
            session.close()
