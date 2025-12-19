"""
Базовый класс для всех SQLAlchemy ORM моделей
"""

from sqlalchemy.ext.declarative import declarative_base

# Единый Base для всех моделей - важно для работы foreign keys
Base = declarative_base()
