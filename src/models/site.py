"""
Модели для сайта (Pydantic и SQLAlchemy)
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class SiteORM(Base):
    """SQLAlchemy модель для таблицы sites"""
    
    __tablename__ = 'sites'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    recipe_pattern = Column(String(500))
    base_url = Column(String(500), nullable=False, unique=True)
    language = Column(String(10))
    is_recipe_site = Column(Boolean, default=False)
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
    is_recipe_site: bool = False
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
