"""
Базовый репозиторий для работы с моделями
"""

from typing import TypeVar, Generic, Optional, List, Type
from sqlalchemy.orm import Session
from sqlalchemy.ext.declarative import DeclarativeMeta

from src.common.db.mysql import MySQlManager

T = TypeVar('T', bound=DeclarativeMeta)


class BaseRepository(Generic[T]):
    """Базовый репозиторий с CRUD операциями"""
    
    def __init__(self, model: Type[T], mysql_manager: Optional[MySQlManager] = None):
        """
        Args:
            model: SQLAlchemy ORM модель
            mysql_manager: Менеджер подключения (передаётся общее подключение через get_db_connection())
        """
        self.model = model
        self._mysql = mysql_manager
    
    @property
    def mysql(self) -> MySQlManager:
        """Получить MySQLManager (должен быть передан через конструктор)"""
        if self._mysql is None:
            raise RuntimeError(
                "MySQLManager не инициализирован. "
                "Репозиторий должен получить общее подключение через get_db_connection()"
            )
        return self._mysql
    
    def get_session(self) -> Session:
        """Получить сессию SQLAlchemy"""
        return self.mysql.get_session()
    
    def close(self):
        """
        Закрыть подключение репозитория (deprecated)
        
        Note: 
            Общее подключение закрывается через DatabaseConnection.close()
            Этот метод оставлен для обратной совместимости
        """
        pass  # Ничего не делаем, подключение общее
    
    def get_by_id(self, id: int) -> Optional[T]:
        """Получить объект по ID"""
        with self.get_session() as session:
            return session.query(self.model).filter(self.model.id == id).first()
    
    def get_all(self, limit: Optional[int] = None, offset: int = 0) -> List[T]:
        """Получить все объекты"""
        with self.get_session() as session:
            query = session.query(self.model).offset(offset)
            if limit:
                query = query.limit(limit)
            return query.all()
    
    def create(self, obj: T) -> Optional[T]:
        """Создать новый объект"""
        session = self.get_session()
        try:
            session.add(obj)
            session.commit()
            session.refresh(obj)
            return obj
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
    
    def update(self, obj: T) -> Optional[T]:
        """Обновить существующий объект"""
        session = self.get_session()
        try:
            session.merge(obj)
            session.commit()
            return obj
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
    
    def upsert(self, obj: T) -> Optional[T]:
        """
        Создать новый объект или обновить существующий (INSERT ... ON DUPLICATE KEY UPDATE)
        
        Args:
            obj: SQLAlchemy ORM объект
        
        Returns:
            Созданный или обновленный объект
        """
        session = self.get_session()
        try:
            merged = session.merge(obj)
            session.commit()
            session.refresh(merged)
            return merged
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
    
    def delete(self, id: int) -> bool:
        """Удалить объект по ID"""
        session = self.get_session()
        try:
            obj = session.query(self.model).filter(self.model.id == id).first()
            if obj:
                session.delete(obj)
                session.commit()
                return True
            return False
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
    
    def count(self) -> int:
        """Подсчитать количество объектов"""
        with self.get_session() as session:
            return session.query(self.model).count()