"""
Модели для изображений рецептов (Pydantic и SQLAlchemy)
"""

from datetime import datetime
from typing import Optional
import hashlib
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, ForeignKey, text, Index
from sqlalchemy.orm import relationship
from src.models.base import Base
import requests
from PIL import Image as PIL
from PIL.Image import Image as PILImage
import logging
from io import BytesIO
import os
import aiohttp
import asyncio

PROXY = os.getenv('PROXY', None)
logger = logging.getLogger(__name__)

class ImageORM(Base):
    """SQLAlchemy модель для таблицы images"""
    
    __tablename__ = 'images'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    page_id = Column(Integer, ForeignKey('pages.id', ondelete='CASCADE'), nullable=False)
    image_url = Column(String(1000), nullable=False)
    # image_url_hash - это computed column в MySQL, не включаем в ORM для insert/update
    local_path = Column(String(500))
    remote_storage_url = Column(String(500))
    created_at = Column(TIMESTAMP, server_default=text('CURRENT_TIMESTAMP'))
    vectorised = Column(Boolean, default=False)
    
    # Relationships
    page = relationship("PageORM", back_populates="images")
    
    # Индексы (image_url_hash индекс создан в MySQL, не нужен здесь)
    __table_args__ = (
        Index('idx_page_id', 'page_id'),
    )
    
    @staticmethod
    def hash_url(image_url: str) -> str:
        """
        Вычислить SHA256 хеш URL изображения
        
        Args:
            image_url: URL изображения
        
        Returns:
            SHA256 хеш в виде hex строки (64 символа)
        """
        return hashlib.sha256(image_url.encode('utf-8')).hexdigest()
    
    def to_pydantic(self) -> 'Image':
        """Конвертация ORM модели в Pydantic"""
        return Image.model_validate(self)
    
    def update_from_dict(self, data: dict, exclude: Optional[set] = None) -> 'ImageORM':
        """
        Обновить поля ORM объекта из словаря
        
        Args:
            data: Словарь с данными для обновления
            exclude: Набор полей для исключения из обновления
        
        Returns:
            Self (для chaining)
        """
        exclude = exclude or {'id', 'created_at', 'image_url_hash'}
        
        for key, value in data.items():
            # Пропускаем исключенные поля и поля, которых нет в модели
            if key in exclude or not hasattr(self, key):
                continue
            
            # Обновляем только если значение не None
            if value is not None:
                setattr(self, key, value)
        
        return self

class Image(BaseModel):
    """Pydantic модель для изображения рецепта"""
    
    # Основные поля
    id: Optional[int] = None
    page_id: int
    image_url: str
    image_url_hash: Optional[str] = None
    local_path: Optional[str] = None
    remote_storage_url: Optional[str] = None
    vectorised: bool = False
    
    # Метаданные
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
    
    def to_json(self) -> dict:
        """Преобразование модели в JSON-совместимый словарь"""
        return self.model_dump(mode='json', exclude_none=True)
    

def download_image(image_url: str, timeout: float = 30.0, max_retries: int = 3) -> PILImage | None:
    """
    Скачать изображение по URL и вернуть как PIL.Image.Image (без сохранения на диск).
    
    Args:
        image_url: URL изображения
        timeout: Таймаут запроса в секундах (по умолчанию 30)
        max_retries: Максимальное количество попыток (по умолчанию 3)
    
    Returns:
        PIL.Image.Image или None при ошибке
    """
    for attempt in range(max_retries):
        try:
            response = requests.get(
                image_url,
                timeout=timeout,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
                proxies={
                    "http": PROXY,
                    "https": PROXY
                } if PROXY else None
            )
            response.raise_for_status()

            img = PIL.open(BytesIO(response.content))
            img.load()
            return img

        except requests.Timeout as e:
            if attempt < max_retries - 1:
                logger.warning(f"Timeout downloading image {image_url} (attempt {attempt + 1}/{max_retries}), retrying...")
                continue
            else:
                logger.error(f"Failed to download image {image_url} after {max_retries} attempts: {e}")
                return None
        except requests.RequestException as e:
            logger.error(f"Failed to download image {image_url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to decode image {image_url}: {e}")
            return None
    
    return None


async def download_image_async(image_url: str, max_retries: int = 3, use_proxy: bool = True) -> PILImage | None:
    """
    Асинхронно скачать изображение по URL и вернуть как PIL.Image.Image (без сохранения на диск).
    
    Args:
        image_url: URL изображения
        timeout: Таймаут запроса в секундах (по умолчанию 30)
        max_retries: Максимальное количество попыток (по умолчанию 3)
    
    Returns:
        PIL.Image.Image или None при ошибке
    """
    proxy = None
    if use_proxy:
        proxy = PROXY

    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    image_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    },
                    proxy=proxy
                ) as response:
                    response.raise_for_status()
                    content = await response.read()
                    img = PIL.open(BytesIO(content))
                    img.load()
                    return img

        except asyncio.TimeoutError as e:
            if attempt < max_retries - 1:
                logger.warning(f"Timeout downloading image {image_url} (attempt {attempt + 1}/{max_retries}), retrying...")
                continue
            else:
                logger.error(f"Failed to download image {image_url} after {max_retries} attempts: {e}")
                return None
        except aiohttp.ClientError as e:
            logger.error(f"Failed to download image {image_url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to decode image {image_url}: {e}")
            return None
    
    return None
