"""
Pydantic модель для страницы
"""

from datetime import datetime
from typing import Optional
from decimal import Decimal
from pydantic import BaseModel, Field


class Page(BaseModel):
    """Модель спарсенной страницы"""
    
    # Основные поля
    id: Optional[int] = None
    site_id: int
    url: str
    pattern: Optional[str] = None
    title: Optional[str] = None
    language: Optional[str] = None
    html_path: Optional[str] = None
    metadata_path: Optional[str] = None
    
    # Данные рецепта (NULL = отсутствует)
    ingredients: Optional[str] = None  # TEXT - JSON или список ингредиентов
    step_by_step: Optional[str] = None  # TEXT - JSON или текст с шагами
    dish_name: Optional[str] = None  # VARCHAR(500) - название блюда
    image_blob: Optional[bytes] = None  # BLOB - бинарные данные изображения
    nutrition_info: Optional[str] = None  # TEXT - JSON с питательной ценностью
    rating: Optional[Decimal] = None  # DECIMAL(3,2)
    author: Optional[str] = None  # VARCHAR(255)
    category: Optional[str] = None  # VARCHAR(255)
    prep_time: Optional[str] = None  # VARCHAR(100) - "30 minutes"
    cook_time: Optional[str] = None  # VARCHAR(100) - "45 minutes"
    total_time: Optional[str] = None  # VARCHAR(100) - "1 hour 15 minutes"
    servings: Optional[str] = None  # VARCHAR(50) - "4 servings"
    difficulty_level: Optional[str] = None  # VARCHAR(50) - "easy", "medium", "hard"
    
    # Оценка достоверности
    confidence_score: Optional[Decimal] = Field(default=Decimal('0.00'))
    is_recipe: bool = False
    
    # Метаданные
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
        json_encoders = {
            Decimal: lambda v: float(v) if v is not None else None
        }