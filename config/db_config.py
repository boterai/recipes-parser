"""
Настройки базы данных
"""

import os
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()


class MySQLConfig:
    """Конфигурация MySQL"""
    
    MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
    MYSQL_PORT = int(os.getenv('MYSQL_PORT', 3306))
    MYSQL_USER = os.getenv('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
    MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'recipe_parser')
    
    @classmethod
    def get_connection_url(cls) -> str:
        """Получение URL подключения для SQLAlchemy"""
        # Экранирование спецсимволов в пароле и логине
        password_escaped = quote_plus(cls.MYSQL_PASSWORD)
        user_escaped = quote_plus(cls.MYSQL_USER)
        
        return (
            f"mysql+pymysql://{user_escaped}:{password_escaped}"
            f"@{cls.MYSQL_HOST}:{cls.MYSQL_PORT}/{cls.MYSQL_DATABASE}"
            f"?charset=utf8mb4"
        )


class ClickHouseConfig:
    """Конфигурация ClickHouse"""
    
    CH_HOST = os.getenv('CLICKHOUSE_HOST', 'localhost')
    CH_PORT = int(os.getenv('CLICKHOUSE_PORT', 9000))
    CH_USER = os.getenv('CLICKHOUSE_USER', 'default')
    CH_PASSWORD = os.getenv('CLICKHOUSE_PASSWORD', '')
    CH_DATABASE = os.getenv('CLICKHOUSE_DATABASE', 'recipes')
    CH_SECURE = bool(int(os.getenv('CLICKHOUSE_SECURE', '1')))
    
    @classmethod
    def get_connection_params(cls) -> dict:
        """Параметры подключения к ClickHouse"""
        return {
            'host': cls.CH_HOST,
            'port': cls.CH_PORT,
            'user': cls.CH_USER,
            'password': cls.CH_PASSWORD,
            'database': cls.CH_DATABASE,
            'secure': cls.CH_SECURE
        }


class QdrantConfig:
    """Конфигурация Qdrant"""
    
    QDRANT_HOST = os.getenv('QDRANT_HOST_CLOUD', 'localhost')
    QDRANT_PORT = int(os.getenv('QDRANT_PORT_CLOUD', 6333))
    QDRANT_API_KEY = os.getenv('QDRANT_API_KEY_CLOUD', None)
    QDRANT_HTTPS = os.getenv('QDRANT_HTTPS', 'false').lower() == 'true'
    
    @classmethod
    def get_connection_params(cls) -> dict:
        """Параметры подключения к Qdrant"""
        return {
            'host': cls.QDRANT_HOST,
            'port': cls.QDRANT_PORT,
            'api_key': cls.QDRANT_API_KEY,
            'https': cls.QDRANT_HTTPS
        }
