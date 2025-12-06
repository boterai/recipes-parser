"""
Pydantic модель для страницы
"""

from datetime import datetime
from typing import Optional, Any
from decimal import Decimal
from pydantic import BaseModel, Field
import json

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
    ingredient: Optional[str] = None  #  JSON список ингредиентов
    description: Optional[str] = None  # TEXT - описание рецепта
    step_by_step: Optional[str] = None  # TEXT - JSON или текст с шагами
    dish_name: Optional[str] = None  # VARCHAR(500) - название блюда
    nutrition_info: Optional[str] = None  # TEXT - JSON с питательной ценностью
    rating: Optional[float] = None  # DECIMAL(3,2)
    author: Optional[str] = None  # VARCHAR(255)
    category: Optional[str] = None  # VARCHAR(255)
    prep_time: Optional[str] = None  # VARCHAR(100) - "30 minutes"
    cook_time: Optional[str] = None  # VARCHAR(100) - "45 minutes"
    total_time: Optional[str] = None  # VARCHAR(100) - "1 hour 15 minutes"
    servings: Optional[str] = None  # VARCHAR(50) - "4 servings"
    difficulty_level: Optional[str] = None  # VARCHAR(50) - "easy", "medium", "hard"
    notes: Optional[str] = None  # TEXT - дополнительные заметки или советы
    image_urls: Optional[str] = None  # TEXT - URL изображения
    tags: Optional[str] = None  # TEXT - теги через запятую

    
    # Оценка достоверности
    confidence_score: Optional[float] = Field(default=float('0.00'))
    is_recipe: bool = False
    
    # Метаданные
    created_at: Optional[datetime] = None

    def to_json(self) -> dict:
        """Преобразование модели в JSON-совместимый словарь"""
        data = self.model_dump(mode='json', exclude_none=True)
        return data
        
    def receipt_to_json(self) -> dict:
        """Преобразование данных рецепта в JSON-совместимый словарь"""
        recipe_fields = [
            'dish_name', 'description', 'ingredients', 'step_by_step', 'nutrition_info',
            'rating', 'category', 'prep_time', 'cook_time',
            'total_time', 'servings', 'difficulty_level', 'notes', 'ingredients_names', 'tags', 'image_urls'
        ]
        data = {field: getattr(self, field) for field in recipe_fields if getattr(self, field) is not None}
        return data
    
    def ingredient_to_str(self, separator: str = ", ") -> str:
        """возвращает все игредиенты через запятую"""
        if not self.ingredient:
            return ""
        try:
            ingredients: list[dict[str, Any]] = json.loads(self.ingredient)
            names = [item.get('name', '').strip() for item in ingredients if 'name' in item]
            return separator.join(names)
        except json.JSONDecodeError:
            return ""
        
    def ingredient_to_list(self) -> list[str]:
        """возвращает все игредиенты списком строк"""
        if not self.ingredient:
            return []
        try:
            ingredients: list[dict[str, Any]] = json.loads(self.ingredient)
            names = [item.get('name', '').strip() for item in ingredients if 'name' in item]
            return names
        except json.JSONDecodeError:
            return []
    
    class Config:
        from_attributes = True
        json_encoders = {
            Decimal: lambda v: float(v) if v is not None else None
        }