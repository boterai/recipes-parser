"""
Модели конфигурации для векторного поиска рецептов
"""

from pydantic import BaseModel, model_validator, ValidationError

class ComponentWeights(BaseModel):
    """
    Весовые коэффициенты для компонентов мультивекторного поиска
    
    Сумма всех весов должна быть равна 1.0.
    Вес 0.0 означает, что компонент не участвует в поиске.
    
    Примеры:
        >>> # Фокус на ингредиентах
        >>> weights = ComponentWeights(
        ...     ingredients=0.6,
        ...     dish_name=0.2,
        ...     description=0.1,
        ...     instructions=0.1
        ... )
        
        >>> # Без учета тегов и мета
        >>> weights = ComponentWeights(
        ...     ingredients=0.4,
        ...     dish_name=0.3,
        ...     description=0.15,
        ...     instructions=0.15,
        ...     tags=0.0,
        ...     meta=0.0
        ... )
    """
    ingredients: float = 0.35
    dish_name: float = 0.25
    description: float = 0.15
    instructions: float = 0.15
    tags: float = 0.05
    meta: float = 0.05

    @model_validator(mode='after')
    def validate_weights_sum(self) -> 'ComponentWeights':
        """Проверка что сумма весов равна 1.0"""
        total = (
            self.ingredients + 
            self.dish_name + 
            self.description +
            self.instructions + 
            self.tags + 
            self.meta
        )
        
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Сумма весов должна быть равна 1.0, получено: {total:.6f}\n"
                f"Текущие веса:\n"
                f"  ingredients={self.ingredients}\n"
                f"  dish_name={self.dish_name}\n"
                f"  description={self.description}\n"
                f"  instructions={self.instructions}\n"
                f"  tags={self.tags}\n"
                f"  meta={self.meta}"
            )
        
        return self
    
    @model_validator(mode='after')
    def validate_non_negative(self) -> 'ComponentWeights':
        """Проверка что все веса неотрицательные"""
        weights = {
            'ingredients': self.ingredients,
            'dish_name': self.dish_name,
            'description': self.description,
            'instructions': self.instructions,
            'tags': self.tags,
            'meta': self.meta
        }
        
        negative = [name for name, val in weights.items() if val < 0]
        if negative:
            raise ValueError(
                f"Веса не могут быть отрицательными. "
                f"Отрицательные значения в полях: {', '.join(negative)}"
            )
        
        return self
    
    def to_dict(self) -> dict[str, float]:
        """Преобразование в словарь для передачи в функции поиска"""
        return self.model_dump()

# Предустановленные профили поиска
class SearchProfiles:
    """Готовые профили весов для разных типов поиска"""
    
    # Фокус на ингредиентах (для поиска "что приготовить из...")
    INGREDIENTS_FOCUSED = ComponentWeights(
        ingredients=0.60,
        dish_name=0.20,
        description=0.10,
        instructions=0.10,
        tags=0.0,
        meta=0.0
    )
    
    # Сбалансированный поиск (по умолчанию)
    BALANCED = ComponentWeights(
        ingredients=0.35,
        dish_name=0.25,
        description=0.15,
        instructions=0.15,
        tags=0.05,
        meta=0.05
    )
    
    # Фокус на названии блюда (для поиска "найди рецепт X")
    NAME_FOCUSED = ComponentWeights(
        ingredients=0.20,
        dish_name=0.50,
        description=0.15,
        instructions=0.10,
        tags=0.05,
        meta=0.0
    )
    
    # Фокус на способе приготовления (для поиска "как приготовить...")
    INSTRUCTIONS_FOCUSED = ComponentWeights(
        ingredients=0.20,
        dish_name=0.15,
        description=0.10,
        instructions=0.50,
        tags=0.05,
        meta=0.0
    )
    
    # Только ингредиенты (игнорировать все остальное)
    INGREDIENTS_ONLY = ComponentWeights(
        ingredients=1.0,
        dish_name=0.0,
        description=0.0,
        instructions=0.0,
        tags=0.0,
        meta=0.0
    )

    CLICKHOUSE_DEFAULT = ComponentWeights(
        ingredients=0.40,
        dish_name=0.25,
        description=0.15,
        instructions=0.15,
        tags=0.05,
        meta=0.0
    )