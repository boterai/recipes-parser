"""
Pydantic модель для сайта
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, HttpUrl


class Site(BaseModel):
    """Модель сайта для парсинга"""
    
    id: Optional[int] = None
    name: str
    base_url: str
    patterns: Optional[str] = None  # JSON строка с паттернами для страниц
    language: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
