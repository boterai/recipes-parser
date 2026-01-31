"""
Модели для страницы (Pydantic и SQLAlchemy)
"""

from datetime import datetime
from typing import Optional, Any
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator, model_validator
import json
from sqlalchemy import Column, Integer, String, Boolean, DECIMAL, TIMESTAMP, Text, ForeignKey, text, Index
from sqlalchemy.orm import relationship
from sqlalchemy.inspection import inspect
from src.models.base import Base
from src.models.recipe import Recipe
from src.models.image import ImageORM, Image
from utils.languages import validate_and_normalize_language

class PageORM(Base):
    """SQLAlchemy модель для таблицы pages"""
    
    __tablename__ = 'pages'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, ForeignKey('sites.id', ondelete='CASCADE'), nullable=False)
    url = Column(String(1000), nullable=False)
    pattern = Column(String(500))
    title = Column(Text)
    language = Column(String(10))
    html_path = Column(String(500))
    
    # Данные рецепта
    ingredients = Column(Text)  # JSON список ингредиентов
    instructions = Column(Text)  # JSON или текст с шагами
    dish_name = Column(String(500))
    category = Column(String(255))
    prep_time = Column(String(100))
    cook_time = Column(String(100))
    total_time = Column(String(100))
    description = Column(Text)
    notes = Column(Text)
    tags = Column(Text)
    
    # Оценка
    confidence_score = Column(DECIMAL(5, 2), default=0.00)
    is_recipe = Column(Boolean, default=False)
    
    # Метаданные
    created_at = Column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))
    
    # Relationships
    images = relationship(
        "ImageORM",
        back_populates="page",
        cascade="all, delete-orphan",
        lazy="select"
    )
    
    # Индексы
    __table_args__ = (
        Index('unique_site_url', 'site_id', 'url', unique=True, mysql_length={'url': 500}),
        Index('idx_is_recipe', 'is_recipe'),
        Index('idx_confidence', 'confidence_score'),
    )
    
    def to_pydantic(self) -> 'Page':
        """Конвертация ORM модели в Pydantic"""
        return Page.model_validate(self)
    
    def update_from_dict(self, data: dict, exclude: Optional[set] = None) -> 'PageORM':
        """
        Обновить поля ORM объекта из словаря (дополнить, не заменить все)
        
        Args:
            data: Словарь с данными для обновления
            exclude: Набор полей для исключения из обновления
        
        Returns:
            Self (для chaining)
        """
        exclude = exclude or {'id', 'created_at'}
        
        for key, value in data.items():
            # Пропускаем исключенные поля и поля, которых нет в модели
            if key in exclude or not hasattr(self, key):
                continue
            
            # Обновляем только если значение не None (для дополнения)
            if value is not None:
                setattr(self, key, value)
        
        return self
    
    def update_from_page(self, other: 'PageORM', exclude: Optional[set] = None) -> 'PageORM':
        """
        Обновить поля из другого объекта PageORM (только не нулевые поля)
        
        Args:
            other: Другой объект PageORM, из которого берутся данные
            exclude: Набор полей для исключения из обновления
        
        Returns:
            Self (для chaining)
        """
        exclude = exclude or {'id', 'created_at'}
        
        # Получаем все поля ORM модели
        for column in self.__table__.columns:
            field_name = column.name
            
            # Пропускаем исключенные поля
            if field_name in exclude:
                continue
            
            # Получаем значение из другого объекта
            other_value = getattr(other, field_name, None)
            
            # Обновляем только если значение не None
            if other_value is not None:
                setattr(self, field_name, other_value)
        
        return self

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
    category: Optional[str] = None  # VARCHAR(255)
    prep_time: Optional[str] = None  # VARCHAR(100) - "30 minutes"
    cook_time: Optional[str] = None  # VARCHAR(100) - "45 minutes"
    total_time: Optional[str] = None  # VARCHAR(100) - "1 hour 15 minutes"
    notes: Optional[str] = None  # TEXT - дополнительные заметки или советы
    image_urls: Optional[str] = None  # TEXT - URL изображения
    images: Optional[list[Image]] = None  # Список объектов изображений (при наличии)
    tags: Optional[str] = None  # TEXT - теги через запятую

    # Оценка достоверности
    confidence_score: Optional[float] = Field(default=float('0.00'))
    is_recipe: Optional[bool] = False
    
    # Метаданные
    created_at: Optional[datetime] = None

    @model_validator(mode='before')
    @classmethod
    def handle_orm_images(cls, data):
        """Игнорировать поле images при конвертации из ORM для избежания lazy load ошибки"""
        # Если это ORM объект (PageORM), удаляем images из данных для валидации
        if hasattr(data, '__tablename__'):  # Проверка что это SQLAlchemy модель
            # Проверяем, загружено ли поле images (не вызывая lazy load)
            insp = inspect(data)
            if 'images' in insp.unloaded:
                # Создаем словарь из атрибутов, исключая images
                orm_dict = {}
                for column in data.__table__.columns:
                    orm_dict[column.name] = getattr(data, column.name, None)
                return orm_dict
        return data

    def to_json(self) -> dict:
        """Преобразование модели в JSON-совместимый словарь"""
        data = self.model_dump(mode='json', exclude_none=True)
        return data
        
    def page_to_json(self) -> dict:
        """Преобразование данных рецепта в JSON-совместимый словарь"""
        recipe_fields = [
            'dish_name', 'description', 'ingredients', 'instructions',
            'category', 'prep_time', 'cook_time','total_time', 
            'notes', 'tags'
        ]
        data = {field: getattr(self, field) for field in recipe_fields}
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
            ingredients_with_amounts=json.loads(self.ingredients) if self.ingredients else [],
            instructions=self.instructions or "",
            cook_time=self.cook_time or "",
            prep_time=self.prep_time or "",
            total_time=self.total_time or "",
            category=self.category or "",
            notes=self.notes or "",
            language=validate_and_normalize_language(self.language) or self.language
        )
    
    @classmethod
    def from_orm(cls, page_orm: PageORM) -> 'Page':
        """
        Создать Pydantic модель из SQLAlchemy ORM
        
        Args:
            page_orm: SQLAlchemy объект PageORM
        
        Returns:
            Page (Pydantic модель)
        """
        return cls.model_validate(page_orm)
    
    def to_orm(self, exclude_none: bool = True) -> PageORM:
        """
        Создать SQLAlchemy ORM объект из Pydantic модели
        
        Args:
            exclude_none: Исключить поля со значением None
        
        Returns:
            PageORM (SQLAlchemy модель)
        """
        data = self.model_dump(
            exclude={'id', 'created_at', 'metadata_path', 'image_urls'},
            exclude_none=exclude_none
        )
        page =  PageORM(**data)
        if self.image_urls is not None:
            images = [
                    ImageORM(page_id=self.id, image_url=url.strip())
                    for url in self.image_urls.split(",") if url.strip()
                ]
            page.images = images
        return page
    
    def update_orm(self, page_orm: PageORM, exclude_none: bool = True) -> PageORM:
        """
        Обновить существующий ORM объект данными из Pydantic модели
        
        Args:
            page_orm: Существующий SQLAlchemy объект
            exclude_none: Исключить поля со значением None
        
        Returns:
            Обновленный PageORM объект
        """
        data = self.model_dump(
            exclude={'id', 'created_at', 'metadata_path'},
            exclude_none=exclude_none
        )
        
        for key, value in data.items():
            if hasattr(page_orm, key):
                setattr(page_orm, key, value)
        
        return page_orm

    def update_from_dict(self, data: dict, exclude: Optional[set] = None) -> 'Page':
        """
        Обновить поля модели из словаря (дополнить, не заменить)
        
        Args:
            data: Словарь с данными для обновления
            exclude: Набор полей для исключения из обновления
        
        Returns:
            Self (для chaining)
        """
        exclude = exclude or set()
        
        for key, value in data.items():
            # Пропускаем исключенные поля и поля, которых нет в модели
            if key in exclude or not hasattr(self, key):
                continue
            
            # Обновляем только если значение не None (для дополнения, а не замены)
            if value is not None:
                setattr(self, key, value)
        
        return self
    
    class Config:
        from_attributes = True
        json_encoders = {
            Decimal: lambda v: float(v) if v is not None else None
        }
