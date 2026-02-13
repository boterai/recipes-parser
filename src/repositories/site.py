"""
Репозиторий для работы с сайтами
"""

import logging
from typing import Optional, Literal
from sqlalchemy import or_, func

from src.repositories.base import BaseRepository
from src.models.site import SiteORM, Site
from src.models.page import PageORM
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
        
    def get_by_site_names(self, site_names: list[str]) -> list[SiteORM]:
        """Получить сайты по списку имен"""
        with self.get_session() as session:
            return session.query(SiteORM).filter(
                SiteORM.name.in_(site_names)
            ).all()
    
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
    
    def search_by_domain(self, domain_pattern: str) -> list[SiteORM]:
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
                ), SiteORM.search_url.isnot(None), SiteORM.searched == False
            ).count()
            return count
        
    def get_unprocessed_sites(self, limit: Optional[int] = None, random_order: bool = False) -> list[SiteORM]:
        """
        Получить список сайтов без паттерна и не прошедших поиск рецептов
        
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
                ), SiteORM.search_url.isnot(None), SiteORM.searched == False
            )

            if random_order:
                query = query.order_by(func.random())

            if limit == 1:
                site = query.first()
                return [site] if site else []
            
            if limit:
                query = query.limit(limit)
            
            return query.all()
        
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

    def get_extractors(self, max_recipes: Optional[int] = None, min_recipes: Optional[int] = None,
                       order: Literal["asc", "desc"] = "desc") -> list[str]:
        """
        получить доменные имена сайтов, для которых есть экстракторы и которые еще не набрали максимум рецептов
        
        Args:
            max_recipes_per_module: Максимальное количество рецептов на модуль (опционально)
        
        Returns:
            Список SiteORM объектов
        """
        with self.get_session() as session:
            query = (
                session.query(
                    SiteORM,
                )
                .join(PageORM, PageORM.site_id == SiteORM.id)
                .filter(PageORM.is_recipe == True)
                .group_by(SiteORM.id, SiteORM.name)
            )

            if order == "asc":
                query = query.order_by(func.count(PageORM.id).asc())
            else:
                query = query.order_by(func.count(PageORM.id).desc())
            
            if max_recipes is not None:
                query = query.having(func.count(PageORM.id) <= max_recipes)

            if min_recipes is not None:
                query = query.having(func.count(PageORM.id) >= min_recipes)

            results = query.all()

            extractors = [site.name for site in results]
            return extractors
        
    def update_language(self, site_id: int, language: str) -> bool:
        """
        Обновить язык сайта
        
        Args:
            site_id: ID сайта
        """
        session = self.get_session()
        try:
            site = session.query(SiteORM).filter(SiteORM.id == site_id).first()
            if site:
                site.language = language
                session.commit()
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка обновления языка для сайта {site_id}: {e}")
            return False
        finally:
            session.close()