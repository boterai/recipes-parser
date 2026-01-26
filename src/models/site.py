"""
Модели для сайта (Pydantic и SQLAlchemy)
"""

from datetime import datetime
from urllib.parse import urlparse
from typing import Optional
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, text
from src.models.base import Base

def get_name_base_url_from_url(url: str) -> tuple[str, str]:
    """
    Извлечь имя сайта и базовый URL из полного URL
    
    Args:
        url: Полный URL страницы
    
    Returns:
        Кортеж (имя сайта, базовый URL)
    """
    parsed_url = urlparse(url)
    base_domain = parsed_url.netloc.replace('www.', '')
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}/"
    site_name = base_domain.replace('.', '_')
    return site_name, base_url


class SiteORM(Base):
    """SQLAlchemy модель для таблицы sites"""
    
    __tablename__ = 'sites'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    pattern = Column(String(500))
    base_url = Column(String(500), nullable=False, unique=True)
    search_url = Column(String(1000))
    searched = Column(Boolean, default=False)
    language = Column(String(10))
    created_at = Column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))
    updated_at = Column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'))

    def to_pydantic(self) -> 'Site':
        """Конвертация ORM модели в Pydantic"""
        return Site.model_validate(self)

class Site(BaseModel):
    """Pydantic модель сайта для парсинга"""
    
    id: Optional[int] = None
    name: str
    base_url: str
    search_url: Optional[str] = None
    searched: Optional[bool] = None
    pattern: Optional[str] = None  # строка с паттернами для страниц
    language: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True  # Позволяет создавать из ORM объектов
    
    @classmethod
    def from_orm(cls, site_orm: SiteORM) -> 'Site':
        """
        Создать Pydantic модель из SQLAlchemy ORM
        
        Args:
            site_orm: SQLAlchemy объект SiteORM
        
        Returns:
            Site (Pydantic модель)
        """
        return cls.model_validate(site_orm)
    
    def to_orm(self, exclude_none: bool = True) -> SiteORM:
        """
        Создать SQLAlchemy ORM объект из Pydantic модели
        
        Args:
            exclude_none: Исключить поля со значением None
        
        Returns:
            SiteORM (SQLAlchemy модель)
        """
        data = self.model_dump(
            exclude={'id', 'created_at', 'updated_at'} if exclude_none else None,
            exclude_none=exclude_none
        )
        return SiteORM(**data)
    
    def update_orm(self, site_orm: SiteORM, exclude_none: bool = True) -> SiteORM:
        """
        Обновить существующий ORM объект данными из Pydantic модели
        
        Args:
            site_orm: Существующий SQLAlchemy объект
            exclude_none: Исключить поля со значением None
        
        Returns:
            Обновленный SiteORM объект
        """
        data = self.model_dump(
            exclude={'id', 'created_at', 'updated_at'},
            exclude_none=exclude_none
        )
        
        for key, value in data.items():
            if hasattr(site_orm, key):
                setattr(site_orm, key, value)
        
        return site_orm
    
    def set_url(self, base_url: str):
        """
        Установить базовый URL и имя сайта на его основе
        
        Args:
            base_url: Базовый URL сайта
        """
        name, base_url = get_name_base_url_from_url(base_url)
        self.base_url = base_url
        self.name = name
