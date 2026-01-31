from typing import Optional
from pydantic import BaseModel, model_validator
import json
import logging


class Recipe(BaseModel):
    """Recipe entity with fields optimized for similarity search.
    рецепты хранятся в Clickhouse, переведенные на какой-то конкретный язык
    """
    # page id in Mysql
    page_id: int
    site_id: int # для более эффективной батчевой вставки в БД и поиска по уже вставленным данным

    # Basic str content
    dish_name: str
    description: Optional[str] = None
    instructions: str

    # Structured content
    ingredients:  Optional[list[str]] = None  # список ингредиентов без количества
    tags: Optional[list[str]] = None
    ingredients_with_amounts: Optional[list[dict]] = None  # список словарей с name и amount

    # Meta
    cook_time: Optional[str] = None
    prep_time: Optional[str] = None
    total_time: Optional[str] = None
    category: Optional[str] = None

    # системные поля
    vectorised: Optional[bool] = False  # было ли произведено векторное представление рецепта   

    language: Optional[str] = None  # язык рецепта (код ISO 639-1)

    @model_validator(mode='after')
    def auto_normalise(self) -> 'Recipe':
        """Автоматическая нормализация после создания объекта"""
        self.normalise_ingredients_with_amounts()
        if self.ingredients_with_amounts and not self.ingredients:
            self.ingredients = [item["name"] for item in self.ingredients_with_amounts]
        return self

    def get_multivector_data(self, max_instruction_length: int = 400) -> dict:
        """Подготавливает данные для мульти-векторного эмбеддинга"""
        return {
                "ingredients": self.ingredient_to_str(),
                "instructions": self.instructions[:max_instruction_length] or "",
                "dish_name": self.dish_name or "",
                "tags": self.tags_to_str(),
                "meta": self.get_meta_str() or ""
            }
    
    def amount_to_float(self, amount) -> Optional[float]:
        """Преобразует количество в float, если возможно"""
        try:
            return float(amount)
        except (ValueError, TypeError):
            return None
    
    def normalise_ingredients_with_amounts(self):
        """Нормализует ingredients_with_amounts, приводя имена к нижнему регистру и корректя типы"""
        if not self.ingredients_with_amounts:
            return
        normalised_ingredients = []
        for item in self.ingredients_with_amounts:
            name = item.get("name", "").strip().lower()
            amount = item.get("amount", None)
            unit = item.get("unit", "").strip().lower() if item.get("unit") else None
            normalised_ingredients.append({
                "name": name,
                "amount": self.amount_to_float(amount),
                "unit": unit
            })
        self.ingredients_with_amounts = normalised_ingredients
    
    def ingredient_to_str(self, separator: str = ", ") -> str:
        """Возвращает ингредиенты в виде строки"""
        if not self.ingredients:
            return ""
        return separator.join(self.ingredients)
    
    def tags_to_str(self, separator: str = ", ") -> str:
        """Возвращает теги в виде строки"""
        if not self.tags:
            return ""
        return separator.join(self.tags)

    def get_meta_str(self) -> str:
        """Возвращает строковое представление метаданных рецепта"""
        meta_parts = []
        if self.cook_time:
            meta_parts.append(f"Cook time: {self.cook_time}")
        if self.prep_time:
            meta_parts.append(f"Prep time: {self.prep_time}")
        if self.total_time:
            meta_parts.append(f"Total time: {self.total_time}")
        return "; ".join(meta_parts)
    
    def get_full_recipe_str(self) -> str:
        """Возвращает полное текстовое представление рецепта для поиска"""
        parts = []
        if self.dish_name:
            parts.append(self.dish_name)
        if self.description:
            parts.append(self.description[:200])
        if self.ingredients:
            parts.append(self.ingredient_to_str())
        if self.instructions:
            parts.append(self.instructions[:600])
        if self.tags:
            parts.append(self.tags_to_str()[:100])
        
        return " ".join(parts)
    
    def normalaize_instructions(self) -> str:
        """Нормализует инструкции, убирая лишние пробелы и переносы строк"""
        if self.instructions and '[' in self.instructions and ']' in self.instructions:
            try:
                steps = json.loads(self.instructions)
                if isinstance(steps, list):
                    cleaned_steps = [step.strip() for step in steps if isinstance(step, str)]
                    self.instructions = " ".join(cleaned_steps).strip()
                    return self.instructions
            except json.JSONDecodeError:
                pass
        return self.instructions.strip() if self.instructions else ""
    
    def to_dict_for_translation(self) -> dict:
        """Возвращает словарь с полями рецепта для перевода"""
        return {
            "dish_name": self.dish_name,
            "description": self.description,
            "ingredients_with_amounts": self.ingredients_with_amounts,
            "tags": self.tags,
            "category": self.category,
            "instructions": self.normalaize_instructions(),
            "cook_time": self.cook_time,
            "prep_time": self.prep_time,
            "total_time": self.total_time
        }
    
    def to_dict(self, required_fields: Optional[list] = None) -> dict:
        """Преобразование Recipe в словарь JSON"""
        response = self.model_dump()
        if required_fields:
            response = {key: response[key] for key in required_fields if key in response}
        if response.get("ingredients_with_amounts"):
            response["ingredients"] = [item["name"] for item in response["ingredients_with_amounts"]]
        return response
    
    def list_fields_to_lower(self):
        """Преобразует все строковые элементы в списках к нижнему регистру"""
        if self.ingredients:
            self.ingredients = [i.strip().lower() for i in self.ingredients]
        if self.tags:
            self.tags = [t.strip().lower() for t in self.tags]
    
    def fill_ingredients_with_amounts(self, page_repository):
        """Заполняет ingredients_with_amounts на основе ingredients, если оно пусто"""
        page_data = page_repository.get_by_id(self.page_id)
        ingredients_with_amounts: list[dict] = []
        normalised_ingredients = []
        try:
            ingredients_with_amounts = json.loads(page_data.ingredients or "[]")
        except json.JSONDecodeError:
            logging.warning(f"Ошибка декодирования ingredients_with_amounts для страницы ID={self.page_id}")
            return
        if page_data and page_data.ingredients:
            for name, full_data in zip(self.ingredients, ingredients_with_amounts):
                if full_data:
                    normalised_ingredients.append({"name": name, "amount": full_data.get("amount", ""),"unit": full_data.get("unit", "")})
            self.ingredients_with_amounts = normalised_ingredients

