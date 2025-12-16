from __future__ import annotations

from typing import Optional
from pydantic import BaseModel

class Recipe(BaseModel):
    """Recipe entity with fields optimized for similarity search.
    рецепты могут раниться в БД, переведенные на какой-то конкретный язык
    """
    # Core content
    page_id: int
    dish_name: str
    description: Optional[str] = None
    tags: Optional[str] = None

    # Structured content
    ingredient: str
    step_by_step: str

    # Meta
    cook_time: Optional[int] = None
    prep_time: Optional[int] = None
    total_time: Optional[int] = None
    nutrition_info: Optional[str] = None
    category: Optional[str] = None

    def prepare_multivector_data(self, max_instruction_length: int = 300, max_description_length: int = 300) -> dict:
        """Подготавливает данные для мульти-векторного эмбеддинга"""
        return {
                "ingredients": self.ingredient or "",
                "description": self.description[:max_description_length] or "",
                "instructions": self.step_by_step[:max_instruction_length] or "",
                "dish_name": self.dish_name or "",
                "tags": self.tags or "",
                "meta": self.get_meta_str() or ""
            }
    
    def is_int_str(self, s: str) -> bool:
        s = s.strip()
        return s.isdigit()

    def get_meta_str(self) -> str:
        """Возвращает строковое представление метаданных рецепта"""
        meta_parts = []
        if self.cook_time is not None:
            if self.is_int_str(str(self.cook_time)):
                self.cook_time = f"{self.cook_time} minutes"
            meta_parts.append(f"Cook time: {self.cook_time}")
        if self.prep_time is not None:
            if self.is_int_str(str(self.prep_time)):
                self.prep_time = f"{self.prep_time} minutes"
            meta_parts.append(f"Prep time: {self.prep_time}")
        if self.total_time is not None:
            if self.is_int_str(str(self.cook_time)):
                self.total_time = f"{self.total_time} minutes"
            meta_parts.append(f"Total time: {self.total_time}")
        if self.nutrition_info is not None:
            meta_parts.append(f"Calories: {self.nutrition_info}")
        return "; ".join(meta_parts)
    
    def get_full_recipe_str(self) -> str:
        """Возвращает полное текстовое представление рецепта для поиска"""
        parts = []
        if self.dish_name:
            parts.append(self.dish_name)
        if self.description:
            parts.append(self.description[:300])
        if self.ingredient:
            parts.append(self.ingredient)
        if self.step_by_step:
            parts.append(self.step_by_step[:600])
        if self.tags:
            parts.append(self.tags[:150])
        
        return " ".join(parts)
    
    def to_dict(self, required_fields: Optional[list] = None) -> dict:
        """Преобразование Recipe в словарь JSON"""
        response = self.model_dump()
        if required_fields:
            response = {key: response[key] for key in required_fields if key in response}
        return response
