"""
Pydantic модель для страницы
"""

from datetime import datetime
from typing import Optional, Any
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator
import json
from src.models.recipe import Recipe

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
    ingredients: Optional[str] = None  #  JSON список ингредиентов
    description: Optional[str] = None  # TEXT - описание рецепта
    instructions: Optional[str] = None  # TEXT - JSON или текст с шагами
    dish_name: Optional[str] = None  # VARCHAR(500) - название блюда
    nutrition_info: Optional[str] = None  # TEXT - JSON с питательной ценностью
    category: Optional[str] = None  # VARCHAR(255)
    prep_time: Optional[str] = None  # VARCHAR(100) - "30 minutes"
    cook_time: Optional[str] = None  # VARCHAR(100) - "45 minutes"
    total_time: Optional[str] = None  # VARCHAR(100) - "1 hour 15 minutes"
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
        
    def page_to_json(self) -> dict:
        """Преобразование данных рецепта в JSON-совместимый словарь"""
        recipe_fields = [
            'dish_name', 'description', 'ingredients', 'instructions', 'nutrition_info',
            'rating', 'category', 'prep_time', 'cook_time',
            'total_time', 'difficulty_level', 'notes', 'tags', 'image_urls'
        ]
        data = {field: getattr(self, field) for field in recipe_fields if getattr(self, field) is not None}
        return data
        
    def ingredients_to_json(self) -> list[str]:
        if not self.ingredients:
            return []
        try:
            ingredients: list[dict[str, Any]] = json.loads(self.ingredients)
            ingredients = [str(i.get("name")).strip() for i in ingredients if isinstance(i, dict) and "name" in i]
            return ingredients
        except json.JSONDecodeError:
            return []
        
    def tags_to_json(self) -> list[str]:
        if not self.tags:
            return []
        tags_list = [tag.strip() for tag in self.tags.split(",") if tag.strip()]
        return tags_list
    
    @field_validator('prep_time', 'cook_time', 'total_time', mode='before')
    @classmethod
    def normalize_time(cls, v: Optional[str]) -> Optional[str]:
        """
        Автоматическая нормализация времени при создании объекта.
        Если значение - это только число, добавляет ' minutes'
        
        Args:
            v: Значение времени (может быть None, число или строка)
            
        Returns:
            Нормализованная строка времени или None
        """
        if v is None:
            return None
        
        # Преобразуем в строку и очищаем
        v_str = str(v).strip()
        
        if not v_str:
            return None
        
        # Если это только число (без букв), добавляем "minutes"
        if v_str.isdigit():
            return f"{v_str} minutes"
        
        # Если уже есть единицы измерения, возвращаем как есть
        return v_str

    def to_recipe(self) -> Recipe:
        """Преобразование Page в модель Recipe"""
        return Recipe(
            page_id=self.id,
            site_id=self.site_id,
            dish_name=self.dish_name or "",
            description=self.description,
            tags=self.tags_to_json(),
            ingredients=self.ingredients_to_json(),
            instructions=self.instructions or "",
            cook_time=self.cook_time or "",
            prep_time=self.prep_time or "",
            total_time=self.total_time or "",
            nutrition_info=self.nutrition_info or "",
            category=self.category or ""
        )   
    
    class Config:
        from_attributes = True
        json_encoders = {
            Decimal: lambda v: float(v) if v is not None else None
        }
