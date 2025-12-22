"""
Репозиторий для работы с сайтами
"""

import logging
from typing import Optional, List
from sqlalchemy import or_, func

from src.repositories.base import BaseRepository
from src.models.site import SiteORM, Site
from src.common.db.connection import get_db_connection

logger = logging.getLogger(__name__)


class SiteRepository(BaseRepository[SiteORM]):
    """Репозиторий для работы с сайтами"""
    
    def __init__(self, mysql_manager=None):
        # Используем общее подключение если не передано явно
        if mysql_manager is None:
            mysql_manager = get_db_connection()
        super().__init__(SiteORM, mysql_manager)
    
    def get_by_base_url(self, base_url: str) -> Optional[SiteORM]:
        """
        Получить сайт по base_url
        
        Args:
            base_url: Базовый URL сайта
        
        Returns:
            SiteORM или None
        """
        with self.get_session() as session:
            return session.query(SiteORM).filter(SiteORM.base_url == base_url).first()
    
    def get_by_name(self, name: str) -> Optional[SiteORM]:
        """Получить сайт по имени"""
        with self.get_session() as session:
            return session.query(SiteORM).filter(
                SiteORM.name == name
            ).first()
    
    def get_recipe_sites(self, language: Optional[str] = None) -> List[SiteORM]:
        """
        Получить все сайты с рецептами
        
        Args:
            language: Фильтр по языку (опционально)
        
        Returns:
            Список сайтов с рецептами
        """
        with self.get_session() as session:
            query = session.query(SiteORM).filter(
                SiteORM.is_recipe_site == True
            )
            
            if language:
                query = query.filter(SiteORM.language == language)
            
            return query.all()
    
    def create_or_get(self, site_data: Site) -> SiteORM:
        """
        Создать новый сайт или получить существующий
        
        Args:
            site_data: Pydantic модель с данными сайта
        
        Returns:
            SiteORM объект
        """
        # Проверяем существование
        existing = self.get_by_name(site_data.name)
        
        if existing:
            logger.debug(f"Сайт {site_data.base_url} уже существует (ID: {existing.id})")
            return existing
        
        # Создаем новый
        site_orm = site_data.to_orm()
        created = self.create(site_orm)
        
        logger.info(f"✓ Создан новый сайт: {site_data.name} (ID: {created.id})")
        return created
    
    def update_recipe_status(self, site_id: int, is_recipe_site: bool) -> bool:
        """
        Обновить статус сайта (является ли рецептным)
        
        Args:
            site_id: ID сайта
            is_recipe_site: Флаг рецептного сайта
        
        Returns:
            True если обновлено успешно
        """
        session = self.get_session()
        try:
            site = session.query(SiteORM).filter(SiteORM.id == site_id).first()
            if site:
                site.is_recipe_site = is_recipe_site
                session.commit()
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка обновления статуса сайта {site_id}: {e}")
            return False
        finally:
            session.close()
    
    def search_by_domain(self, domain_pattern: str) -> List[SiteORM]:
        """
        Поиск сайтов по части домена
        
        Args:
            domain_pattern: Часть домена для поиска
        
        Returns:
            Список найденных сайтов
        """
        with self.get_session() as session:
            return session.query(SiteORM).filter(
                or_(
                    SiteORM.base_url.like(f"%{domain_pattern}%"),
                    SiteORM.name.like(f"%{domain_pattern}%")
                )
            ).all()
    
    def count_sites_without_pattern(self) -> int:
        """
        Подсчитать количество сайтов без паттерна
        (т.е. необработанных сайтов)
        
        Returns:
            Количество сайтов
        """
        with self.get_session() as session:
            count = session.query(SiteORM).filter(
                or_(
                    SiteORM.pattern.is_(None),
                    SiteORM.pattern == ''
                ), SiteORM.is_recipe_site == False,
                SiteORM.search_url.isnot(None), SiteORM.searched == False
            ).count()
            return count
        

    def get_unprocessed_sites(self, limit: int = 10, random_order: bool = False) -> List[SiteORM]:
        """
        Получить список сайтов без паттерна
        
        Args:
            limit: Максимальное количество сайтов для получения
        
        Returns:
            Список SiteORM объектов
        """
        with self.get_session() as session:
            query = session.query(SiteORM).filter(
                or_(
                    SiteORM.pattern.is_(None),
                    SiteORM.pattern == ''
                ), SiteORM.is_recipe_site == False,
                SiteORM.search_url.isnot(None), SiteORM.searched == False
            )

            if random_order:
                query = query.order_by(func.random())

            sites = query.limit(limit).all()
            return sites
        

    def mark_site_as_searched(self, site_id: int) -> bool:
        """
        Пометить сайт как прошедший поиск рецептов
        
        Args:
            site_id: ID сайта
        
        Returns:
            True если успешно
        """
        session = self.get_session()
        try:
            site = session.query(SiteORM).filter(SiteORM.id == site_id).first()
            if site:
                site.searched = True
                session.commit()
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка пометки сайта {site_id} как прошедшего поиск: {e}")
            return False
        finally:
            session.close()