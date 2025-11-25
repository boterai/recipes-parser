"""
Настройки базы данных
"""

import os
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()


class DBConfig:
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