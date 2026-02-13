"""
Настройки базы данных
"""
from urllib.parse import quote_plus
from dotenv import load_dotenv
load_dotenv()

from config.config import config


class MySQLConfig:
    """Конфигурация MySQL"""
    
    MYSQL_HOST = config.MYSQL_HOST
    MYSQL_PORT = config.MYSQL_PORT
    MYSQL_USER = config.MYSQL_USER
    MYSQL_PASSWORD = config.MYSQL_PASSWORD
    MYSQL_DATABASE = config.MYSQL_DATABASE
    
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
    
    CH_HOST = config.CLICKHOUSE_HOST
    CH_PORT = config.CLICKHOUSE_PORT
    CH_USER = config.CLICKHOUSE_USER
    CH_PASSWORD = config.CLICKHOUSE_PASSWORD
    CH_DATABASE = config.CLICKHOUSE_DATABASE
    CH_SECURE = config.CLICKHOUSE_SECURE
    CH_PROXY = config.SOCKS5
    CH_RECIPE_TABLE = config.CLICKHOUSE_RECIPE_TABLE
    
    @classmethod
    def get_connection_params(cls) -> dict:
        """Параметры подключения к ClickHouse"""
        return {
            'host': cls.CH_HOST,
            'port': cls.CH_PORT,
            'user': cls.CH_USER,
            'password': cls.CH_PASSWORD,
            'database': cls.CH_DATABASE,
            'secure': cls.CH_SECURE,
            'proxy': cls.CH_PROXY
        }


class QdrantConfig:
    """Конфигурация Qdrant"""
    
    QDRANT_HOST = config.QDRANT_HOST
    QDRANT_PORT = config.QDRANT_PORT
    QDRANT_API_KEY = config.QDRANT_API_KEY
    QDRANT_HTTPS = config.QDRANT_HTTPS
    QDRANT_PROXY = config.PROXY
    
    @classmethod
    def get_connection_params(cls) -> dict:
        """Параметры подключения к Qdrant"""
        return {
            'host': cls.QDRANT_HOST,
            'port': cls.QDRANT_PORT,
            'api_key': cls.QDRANT_API_KEY,
            'https': cls.QDRANT_HTTPS,
            'proxy': cls.QDRANT_PROXY
        }
