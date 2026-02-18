"""
Модель для cluster page
"""

from src.models.base import Base
from sqlalchemy import Column, Integer, BigInteger, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from pydantic import BaseModel

class ClusterPageORM(Base):
    __tablename__ = 'cluster_page'

    cluster_id = Column(BigInteger, primary_key=True)
    page_id = Column(Integer, ForeignKey('pages.id', ondelete='CASCADE'), primary_key=True)
    is_centroid = Column(Boolean, default=False)  # отмечаем, что эта страница является центроидом кластера

    # Индексы для оптимизации запросов
    __table_args__ = (
        Index('idx_page_id', 'page_id'),
        Index('idx_centroid_lookup', 'page_id', 'is_centroid'),
    )

    # Связь с кластером и страницей
    page = relationship("PageORM", back_populates="cluster_pages")


    def to_pydantic(self) -> 'ClusterPage':
        return ClusterPage(
            cluster_id=self.cluster_id,
            page_id=self.page_id,
            is_centroid=self.is_centroid
        )

class ClusterPage(BaseModel):
    cluster_id: int
    page_id: int
    is_centroid: bool = False

    class Config:
        from_attributes = True

    def to_orm(self) -> ClusterPageORM:
        return ClusterPageORM(
            cluster_id=self.cluster_id,
            page_id=self.page_id,
            is_centroid=self.is_centroid
        )