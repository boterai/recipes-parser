"""
Модели для похожести рецептов (Pydantic и SQLAlchemy)
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from sqlalchemy import Column, BigInteger, Integer, TIMESTAMP, ForeignKey, Index, text, PrimaryKeyConstraint, Text
from src.models.base import Base
import hashlib

def calculate_pages_csv_and_hash(page_ids: list[int]) -> tuple[str, str]:
    """Вычисляет csv и SHA256 хеш для отсортированного CSV списка page_id"""
    sorted_ids = sorted(page_ids)
    pages_csv = ','.join(str(pid) for pid in sorted_ids)
    sha256 = hashlib.sha256()
    sha256.update(pages_csv.encode('utf-8'))
    return pages_csv, sha256.hexdigest()

class RecipeClusterORM(Base):
    """SQLAlchemy модель для таблицы recipe_clusters"""
    
    __tablename__ = 'recipe_clusters'
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    pages_hash_sha256 = Column(Text(64), nullable=False)  # CHAR(64) - SHA2 хеш отсортированных page_id
    pages_csv = Column(Text, nullable=False)  # LONGTEXT - CSV строка page_id через запятую
    created_at = Column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))
    
    # Constraints и индексы
    __table_args__ = (
        Index('uq_pages_hash', 'pages_hash_sha256', unique=True),
    )
    
    def to_pydantic(self) -> 'RecipeCluster':
        """Конвертация ORM модели в Pydantic"""
        return RecipeCluster.model_validate(self)


class RecipeCluster(BaseModel):
    """Pydantic модель для кластера рецептов"""
    
    id: Optional[int] = None
    pages_hash_sha256: str
    pages_csv: str
    created_at: Optional[datetime] = None

    def set_pages(self, page_ids: list[int]) -> None:
        """Устанавливает pages_csv и pages_hash_sha256 по списку page_ids"""
        self.pages_csv, self.pages_hash_sha256 = calculate_pages_csv_and_hash(page_ids)
    
    def to_orm(self) -> RecipeClusterORM:
        """Конвертация Pydantic модели в ORM"""
        return RecipeClusterORM(
            id=self.id,
            pages_hash_sha256=self.pages_hash_sha256,
            pages_csv=self.pages_csv,
            created_at=self.created_at
        )
    
    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": 1,
                "pages_hash_sha256": "abc123...",
                "pages_csv": "1,15,23",
                "created_at": "2025-12-30T10:00:00"
            }
        }


class RecipeSimilarityORM(Base):
    """SQLAlchemy модель для таблицы recipe_similarities (membership: page -> cluster)"""
    
    __tablename__ = 'recipe_similarities'
    
    page_id = Column(Integer, ForeignKey('pages.id', ondelete='CASCADE'), nullable=False, primary_key=True)
    cluster_id = Column(BigInteger, ForeignKey('recipe_clusters.id', ondelete='CASCADE'), nullable=False, primary_key=True)
    created_at = Column(TIMESTAMP, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    
    # Constraints и индексы (PRIMARY KEY определён через primary_key=True выше)
    __table_args__ = (
        PrimaryKeyConstraint('cluster_id', 'page_id'),
        Index('idx_page_id', 'page_id'),
    )
    
    def to_pydantic(self) -> 'RecipeSimilarity':
        """Конвертация ORM модели в Pydantic"""
        return RecipeSimilarity.model_validate(self)


class RecipeSimilarity(BaseModel):
    """Pydantic модель для membership рецепта в кластере"""
    
    page_id: int
    cluster_id: int
    created_at: Optional[datetime] = None
    
    def to_orm(self) -> RecipeSimilarityORM:
        """Конвертация Pydantic модели в ORM"""
        return RecipeSimilarityORM(
            page_id=self.page_id,
            cluster_id=self.cluster_id,
            created_at=self.created_at
        )
    
    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "page_id": 123,
                "cluster_id": 1,
                "created_at": "2025-12-30T10:00:00"
            }
        }
