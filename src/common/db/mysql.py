"""
Менеджер базы данных для работы с MySQL
"""
import time
import logging
import sqlalchemy
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

from config.db_config import MySQLConfig
logger = logging.getLogger(__name__)


class MySQlManager:
    """Менеджер для работы с MySQL"""
    
    def __init__(self):
        """Инициализация подключения к БД"""
        self.engine: sqlalchemy.Engine = None
        self.local_session = None
        
    def connect(self, retry_attempts: int = 3, retry_delay: float = 2.0):
        """
        Установка подключения к БД с повторными попытками
        
        Args:
            retry_attempts: Количество попыток подключения
            retry_delay: Базовая задержка между попытками (в секундах)
        
        Returns:
            True если подключение успешно, False иначе
        """
        
        connection_url = MySQLConfig.get_connection_url()
        
        for attempt in range(retry_attempts):
            try:
                logger.info(f"Попытка подключения к MySQL {attempt + 1}/{retry_attempts}...")
                
                self.engine = sqlalchemy.create_engine(
                    connection_url,
                    pool_pre_ping=True,
                    pool_recycle=3600,
                    pool_size=5,
                    max_overflow=10,
                    pool_timeout=30,
                    connect_args={'connect_timeout': 10},
                    echo=False
                )
                self.local_session = sessionmaker(bind=self.engine,
                                                  expire_on_commit=False,
                                                  autoflush=True,
                                                  autocommit=False)
                
                # Проверка подключения
                with self.engine.connect() as conn:
                    conn.execute(sqlalchemy.text("SELECT 1"))
                
                logger.info("✓ Успешное подключение к MySQL")
                
                # Создание таблиц если их нет
                return self.create_tables()
                
            except SQLAlchemyError as e:                
                if attempt < retry_attempts - 1:
                    # Экспоненциальная задержка: delay * 2^attempt
                    delay = retry_delay * (2 ** attempt)
                    logger.warning(f"✗ Ошибка подключения к MySQL (попытка {attempt + 1}/{retry_attempts}): {e}")
                    logger.info(f"Повторная попытка через {delay:.1f}с...")
                    time.sleep(delay)
                else:
                    logger.error(f"✗ Не удалось подключиться к MySQL после {retry_attempts} попыток: {e}")
        
        return False
    
    def create_tables(self) -> bool:
        """Создание таблиц если их не существует"""
        try:
            with open("db/schemas/mysql.sql", "r", encoding="utf-8") as f:
                migration_schema = f.read()
            
            # Разделяем SQL-выражения по точке с запятой
            statements = [
                stmt.strip() 
                for stmt in migration_schema.split(';') 
                if stmt.strip()
            ]
            
            with self.engine.connect() as conn:
                for statement in statements:
                    if statement:  # Пропускаем пустые
                        conn.execute(sqlalchemy.text(statement))
                conn.commit()
                
            logger.info("Таблицы созданы или уже существуют")
            return True
        except SQLAlchemyError as e:
            logger.error(f"Ошибка создания таблиц: {e}")

        return False
    
    def get_session(self) -> Session:
        """Получение сессии БД"""
        if not self.local_session and not self.connect():
                raise RuntimeError("Не удалось подключиться к базе данных")
        return self.local_session()
            
    def close(self):
        """Закрытие подключения"""
        if self.engine:
            self.engine.dispose()
            logger.info("Подключение к MySQL закрыто")
