"""
Модели для поисковых запросов (Pydantic и SQLAlchemy)
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, TIMESTAMP, text, Index
from src.models.base import Base


class SearchQueryORM(Base):
    """SQLAlchemy модель для таблицы search_query"""
    
    __tablename__ = 'search_query'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    query = Column(String(500), nullable=False)
    language = Column(String(10))
    url_count = Column(Integer, default=0)
    recipe_url_count = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))
    
    # Индекс
    __table_args__ = (
        Index('unique_query', 'query', unique=True, mysql_length=191),
    )
    
    def to_pydantic(self) -> 'SearchQuery':
        """Конвертация ORM модели в Pydantic"""
        return SearchQuery.model_validate(self)


class SearchQuery(BaseModel):
    """Pydantic модель поискового запроса для рецептов"""
    
    id: Optional[int] = None
    query: str
    language: Optional[str] = None
    url_count: int = 0
    recipe_url_count: int = 0
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
    
    @classmethod
    def from_orm(cls, query_orm: SearchQueryORM) -> 'SearchQuery':
        """
        Создать Pydantic модель из SQLAlchemy ORM
        
        Args:
            query_orm: SQLAlchemy объект SearchQueryORM
        
        Returns:
            SearchQuery (Pydantic модель)
        """
        return cls.model_validate(query_orm)
    
    def to_orm(self, exclude_none: bool = True) -> SearchQueryORM:
        """
        Создать SQLAlchemy ORM объект из Pydantic модели
        
        Args:
            exclude_none: Исключить поля со значением None
        
        Returns:
            SearchQueryORM (SQLAlchemy модель)
        """
        data = self.model_dump(
            exclude={'id', 'created_at'},
            exclude_none=exclude_none
        )
        return SearchQueryORM(**data)
    
    def update_orm(self, query_orm: SearchQueryORM, exclude_none: bool = True) -> SearchQueryORM:
        """
        Обновить существующий ORM объект данными из Pydantic модели
        
        Args:
            query_orm: Существующий SQLAlchemy объект
            exclude_none: Исключить поля со значением None
        
        Returns:
            Обновленный SearchQueryORM объект
        """
        data = self.model_dump(
            exclude={'id', 'created_at'},
            exclude_none=exclude_none
        )
        
        for key, value in data.items():
            if hasattr(query_orm, key):
                setattr(query_orm, key, value)
        
        return query_orm
