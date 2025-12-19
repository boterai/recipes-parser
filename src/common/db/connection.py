"""
Singleton для управления единым подключением к БД
"""

import logging
from typing import Optional
from src.common.db.mysql import MySQlManager

logger = logging.getLogger(__name__)


class DatabaseConnection:
    """Singleton для управления единым подключением к БД"""
    
    _instance: Optional['DatabaseConnection'] = None
    _mysql_manager: Optional[MySQlManager] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def get_mysql_manager(cls) -> MySQlManager:
        """
        Получить единый экземпляр MySQLManager для всех репозиториев
        
        Returns:
            MySQlManager: Общий менеджер подключения к БД
        """
        if cls._mysql_manager is None:
            cls._mysql_manager = MySQlManager()
            if not cls._mysql_manager.connect():
                raise ConnectionError("Не удалось подключиться к MySQL")
            logger.info("✓ Создано единое подключение к MySQL (connection pool)")
        return cls._mysql_manager
    
    @classmethod
    def close(cls):
        """Закрыть общее подключение к БД"""
        if cls._mysql_manager:
            cls._mysql_manager.close()
            cls._mysql_manager = None
            logger.info("✓ Закрыто общее подключение к MySQL")
    
    @classmethod
    def reset(cls):
        """Сбросить singleton (полезно для тестов)"""
        cls.close()
        cls._instance = None


# Удобная функция для получения менеджера
def get_db_connection() -> MySQlManager:
    """
    Получить единое подключение к БД для всех репозиториев
    
    Returns:
        MySQlManager: Общий менеджер подключения
    """
    return DatabaseConnection.get_mysql_manager()
