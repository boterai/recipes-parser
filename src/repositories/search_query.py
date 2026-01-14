"""
Репозиторий для работы с поисковыми запросами
"""

import logging
from typing import Optional, List

from src.repositories.base import BaseRepository
from src.models.search_query import SearchQueryORM
from src.common.db.connection import get_db_connection
from sqlalchemy import func

logger = logging.getLogger(__name__)


class SearchQueryRepository(BaseRepository[SearchQueryORM]):
    """Репозиторий для работы с поисковыми запросами"""
    
    def __init__(self, mysql_manager=None):
        # Используем общее подключение если не передано явно
        if mysql_manager is None:
            mysql_manager = get_db_connection()
        super().__init__(SearchQueryORM, mysql_manager)
    
    def get_unsearched_count(self) -> int:
        """
        Получить количество неиспользованных запросов
        
        Returns:
            Количество запросов с url_count = 0
        """
        with self.get_session() as session:
            return session.query(SearchQueryORM).filter(SearchQueryORM.url_count == 0).count()
    
    def get_unsearched_queries(self, limit: Optional[int] = None, random_order: bool = False, unique_languages: bool = False) -> List[SearchQueryORM]:
        """
        Получить неиспользованные поисковые запросы
        
        Args:
            limit: Максимальное количество запросов
            random_order: Случайный порядок
            unique_languages: Вернуть только один запрос на каждый уникальный язык
        
        Returns:
            Список неиспользованных запросов
        """
        with self.get_session() as session:
            query = session.query(SearchQueryORM).filter(SearchQueryORM.url_count == 0)

            if unique_languages:
                # Подзапрос: получить минимальный ID для каждого языка
                subquery = (
                    session.query(
                        SearchQueryORM.language,
                        func.min(SearchQueryORM.id).label('min_id')
                    )
                    .filter(SearchQueryORM.url_count == 0)
                    .group_by(SearchQueryORM.language)
                    .subquery()
                )
                
                # Фильтруем основной запрос по результатам подзапроса
                query = query.join(
                    subquery,
                    (SearchQueryORM.language == subquery.c.language) &
                    (SearchQueryORM.id == subquery.c.min_id)
                )
            
            if random_order:
                query = query.order_by(func.random())
            else:
                query = query.order_by(SearchQueryORM.created_at.asc())

            if limit:
                query = query.limit(limit)

            return query.all()
    
    def upsert(self, new_query: SearchQueryORM) -> Optional[SearchQueryORM]:
        """
        Создать новый запрос или обновить существующий по уникальному полю query
        
        Args:
            query_text: Текст поискового запроса (уникальный ключ)
            language: Код языка
            url_count: Количество найденных URL
            recipe_url_count: Количество URL с рецептами
        
        Returns:
            SearchQueryORM объект или None при ошибке
        """
        session = self.get_session()
        try:
            # Ищем существующий запрос по уникальному ключу
            existing = session.query(SearchQueryORM).filter(SearchQueryORM.query == new_query.query).first()
            
            if existing:
                # Обновляем существующий
                existing.language = new_query.language
                existing.url_count = new_query.url_count
                existing.recipe_url_count = new_query.recipe_url_count
                session.commit()
                session.refresh(existing)
                logger.debug(f"✓ Обновлен запрос ID={existing.id}: '{new_query.query}'")
                return existing
            else:
                session.add(new_query)
                session.commit()
                session.refresh(new_query)
                logger.debug(f"✓ Создан новый запрос ID={new_query.id}: '{new_query.query}'")
                return new_query
                
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка upsert запроса '{new_query.query}': {e}")
            return None
        finally:
            session.close()

    def update_query_statistics(self, query_id: int, url_count: int = 0,  recipe_count: int = 0) -> bool:
        """
        Обновить статистику для поискового запроса
        
        Args:
            query_id: ID запроса
            url_count: Количество найденных URL
        
        Returns:
            True если обновлено успешно
        """
        logger.info(f"Обновление статистики для запроса ID={query_id}...")
        
        try:
            query_orm = self.get_by_id(query_id)
            if query_orm:
                query_orm.url_count = url_count
                query_orm.recipe_url_count = recipe_count 
                self.update(query_orm)
                logger.info(f"✓ Обновлено url_count={url_count} для запроса ID={query_id}")
                return True
            else:
                logger.warning(f"Запрос ID={query_id} не найден")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка обновления статистики запроса: {e}")
            return False
    
