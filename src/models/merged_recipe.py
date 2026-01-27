"""
Модели для вариаций рецептов (Pydantic и SQLAlchemy)
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Column, String, TIMESTAMP, Text, text, BIGINT, JSON, CHAR
from src.models.base import Base
import hashlib


class MergedRecipeORM(Base):
    """SQLAlchemy модель для таблицы merged_recipes"""
    
    __tablename__ = 'merged_recipes'
    
    id = Column(BIGINT, primary_key=True, autoincrement=True)    
    # Хэш и CSV списка страниц (для уникальности и быстрого доступа)
    pages_hash_sha256 = Column(CHAR(64), nullable=False, unique=True)
    pages_csv = Column(Text)  # CSV ID страниц: "1,15,23"
    
    # Данные объединенного рецепта
    dish_name = Column(String(500))  # 100% обязательное поле
    ingredients = Column(JSON)  # 100% обязательное поле - список ингредиентов с amounts
    description = Column(Text)
    instructions = Column(Text)  # 100% обязательное поле
    prep_time = Column(String(100))
    cook_time = Column(String(100))

    # Комментарии об объединении
    merge_comments = Column(Text)

    # язык объедененных рецептов, чтобы можно было фильтровать по языку (основной режим - объединение на английском)
    language = Column(String(10), default='en')  # язык рецепта (код ISO 639-1)
    cluster_type = Column(String(50))  # "image", "full", "ingredients"
    gpt_validated = Column(String(5), default='TRUE')  # было ли
    score_threshold = Column(String(10), default='0.00')  # порог схожести для объединения
    
    # Метаданные
    created_at = Column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))
        
    def __repr__(self):
        return f"<MergedRecipeORM(id={self.id}, dish='{self.dish_name}'>"
    
    def to_pydantic(self) -> 'MergedRecipe':
        """Конвертировать ORM объект в Pydantic модель"""
        # Парсим page_ids из pages_csv
        page_ids = []
        if self.pages_csv:
            try:
                page_ids = [int(pid) for pid in self.pages_csv.split(',') if pid.strip()]
            except (ValueError, AttributeError):
                page_ids = []
        
        return MergedRecipe(
            id=self.id,
            pages_hash_sha256=self.pages_hash_sha256,
            pages_csv=self.pages_csv,
            dish_name=self.dish_name,
            ingredients=self.ingredients,
            description=self.description,
            instructions=self.instructions,
            prep_time=self.prep_time,
            cook_time=self.cook_time,
            merge_comments=self.merge_comments,
            created_at=self.created_at,
            page_ids=page_ids,
            language=self.language,
            cluster_type=self.cluster_type,
            gpt_validated=self.gpt_validated,
            score_threshold=self.score_threshold
        )


# Pydantic модели для API/сериализации
class MergedRecipe(BaseModel):
    """Pydantic модель для объединенного рецепта"""
    
    id: Optional[int] = None
    # (автоматически генерируются из page_ids)
    pages_hash_sha256: Optional[str] = None
    pages_csv: Optional[str] = None
    
    # Данные рецепта
    dish_name: Optional[str] = None
    ingredients: Optional[list[dict]] = None
    description: Optional[str] = None
    instructions: Optional[str] = None
    prep_time: Optional[str] = None
    cook_time: Optional[str] = None
    
    # Комментарии
    merge_comments: Optional[str] = None

    language: Optional[str] = 'en'  # язык рецепта (код ISO 639-1)
    cluster_type: Optional[str] = None  # "image", "full", "ingredients"
    gpt_validated: Optional[bool] = True
    score_threshold: Optional[float] = 0.00
    
    # Метаданные
    created_at: Optional[datetime] = None
    
    # Связанные страницы (из pages_csv)
    page_ids: Optional[list[int]] = Field(default_factory=list)
    
    @model_validator(mode='after')
    def generate_hash_and_csv(self):
        """Автоматически генерирует pages_hash_sha256 и pages_csv из page_ids"""
        if self.page_ids and not self.pages_hash_sha256:
            # Сортируем для консистентности
            sorted_ids = sorted(self.page_ids)
            pages_csv = ','.join(map(str, sorted_ids))
            pages_hash = hashlib.sha256(pages_csv.encode()).hexdigest()
            
            self.pages_csv = pages_csv
            self.pages_hash_sha256 = pages_hash
        
        return self
    page_ids: Optional[list[int]] = Field(default_factory=list)
    
    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }
    
    @classmethod
    def from_orm(cls, orm_obj: MergedRecipeORM) -> 'MergedRecipe':
        """Создать Pydantic модель из ORM объекта"""
        # Парсим page_ids из pages_csv
        page_ids = []
        if orm_obj.pages_csv:
            try:
                page_ids = [int(pid) for pid in orm_obj.pages_csv.split(',') if pid.strip()]
            except (ValueError, AttributeError):
                page_ids = []
        
        return cls(
            id=orm_obj.id,
            pages_hash_sha256=orm_obj.pages_hash_sha256,
            pages_csv=orm_obj.pages_csv,
            dish_name=orm_obj.dish_name,
            ingredients=orm_obj.ingredients,
            description=orm_obj.description,
            instructions=orm_obj.instructions,
            prep_time=orm_obj.prep_time,
            cook_time=orm_obj.cook_time,
            merge_comments=orm_obj.merge_comments,
            created_at=orm_obj.created_at,
            page_ids=page_ids,
            language=orm_obj.language,
            cluster_type=orm_obj.cluster_type,
            gpt_validated=orm_obj.gpt_validated,
            score_threshold=orm_obj.score_threshold
        )
