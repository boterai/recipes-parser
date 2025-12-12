from __future__ import annotations

from typing import Optional
from pydantic import BaseModel

class Recipe(BaseModel):
    """Recipe entity with fields optimized for similarity search."""
    # Core content
    id: Optional[int] = None
    dish_name: str
    description: Optional[str] = None
    tags: Optional[str] = None

    # Structured content
    ingredients: str
    step_by_step: str

    # Meta
    cook_time_minutes: Optional[int] = None
    prep_time_minutes: Optional[int] = None
    total_time_minutes: Optional[int] = None
    calories: Optional[str] = None

    def prepare_multivector_data(self, max_instruction_length: int = 300, max_description_length: int = 300) -> dict:
        """Подготавливает данные для мульти-векторного эмбеддинга"""
        return {
                "ingredients": self.ingredients or "",
                "description": self.description[:max_description_length] or "",
                "instructions": self.step_by_step[:max_instruction_length] or "",
                "dish_name": self.dish_name or "",
                "tags": self.tags or "",
                "meta": self.get_meta_str() or ""
            }

    def get_meta_str(self) -> str:
        """Возвращает строковое представление метаданных рецепта"""
        meta_parts = []
        if self.cook_time_minutes is not None:
            meta_parts.append(f"Cook time: {self.cook_time_minutes} minutes")
        if self.prep_time_minutes is not None:
            meta_parts.append(f"Prep time: {self.prep_time_minutes} minutes")
        if self.total_time_minutes is not None:
            meta_parts.append(f"Total time: {self.total_time_minutes} minutes")
        if self.calories is not None:
            meta_parts.append(f"Calories: {self.calories}")
        return "; ".join(meta_parts)
    
    def get_full_recipe_str(self) -> str:
        """Возвращает полное текстовое представление рецепта для поиска"""
        parts = []
        if self.dish_name:
            parts.append(self.dish_name)
        if self.description:
            parts.append(self.description[:300])
        if self.ingredients:
            parts.append(self.ingredients)
        if self.step_by_step:
            parts.append(self.step_by_step[:600])
        if self.tags:
            parts.append(self.tags[:150])
        
        return " ".join(parts)