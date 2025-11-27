"""
Менеджер базы данных для работы с MySQL
"""

import logging
from typing import Optional, List
from datetime import datetime
import sqlalchemy
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

from config.db_config import DBConfig
from src.models import Site, Page

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Менеджер для работы с MySQL"""
    
    def __init__(self):
        """Инициализация подключения к БД"""
        self.engine: sqlalchemy.Engine = None
        self.local_session = None
        
    def connect(self):
        """Установка подключения к БД"""
        try:
            connection_url = DBConfig.get_connection_url()
            self.engine = sqlalchemy.create_engine(
                connection_url,
                pool_pre_ping=True,
                pool_recycle=3600,
                echo=False
            )
            self.local_session = sessionmaker(bind=self.engine)
            
            # Проверка подключения
            with self.engine.connect() as conn:
                conn.execute(sqlalchemy.text("SELECT 1"))
            
            logger.info("Успешное подключение к MySQL")
            
            # Создание таблиц если их нет
            self.create_tables()
            
            return True
            
        except SQLAlchemyError as e:
            logger.error(f"Ошибка подключения к MySQL: {e}")
            return False
    
    def create_tables(self):
        """Создание таблиц если их не существует"""
        try:
            with self.engine.connect() as conn:
                # Создание таблицы sites
                conn.execute(sqlalchemy.text("""
                    CREATE TABLE IF NOT EXISTS sites (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        base_url VARCHAR(500) NOT NULL UNIQUE,
                        language VARCHAR(10),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        INDEX idx_name (name)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """))
                
                # Создание таблицы pages
                conn.execute(sqlalchemy.text("""
                    CREATE TABLE IF NOT EXISTS pages (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        site_id INT NOT NULL,
                        url VARCHAR(1000) NOT NULL,
                        pattern VARCHAR(500),
                        title TEXT,
                        language VARCHAR(10),
                        html_path VARCHAR(500),
                        metadata_path VARCHAR(500),
                        
                        -- Данные рецепта (NULL = отсутствует)
                        ingredients TEXT,
                        step_by_step TEXT,
                        dish_name VARCHAR(500),
                        image_blob BLOB,
                        nutrition_info TEXT,
                        rating DECIMAL(3,2),
                        author VARCHAR(255),
                        category VARCHAR(255),
                        prep_time VARCHAR(100),
                        cook_time VARCHAR(100),
                        total_time VARCHAR(100),
                        servings VARCHAR(50),
                        difficulty_level VARCHAR(50),
                        description TEXT,
                        notes TEXT,
                        
                        -- Оценка
                        confidence_score DECIMAL(5,2) DEFAULT 0.00,
                        is_recipe BOOLEAN DEFAULT FALSE,
                        
                        -- Метаданные
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        
                        FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE,
                        UNIQUE KEY unique_site_url (site_id, url(500)),
                        INDEX idx_is_recipe (is_recipe),
                        INDEX idx_confidence (confidence_score)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """))
                
                conn.commit()
                logger.info("Таблицы созданы или уже существуют")
                
        except SQLAlchemyError as e:
            logger.error(f"Ошибка создания таблиц: {e}")
    
    def get_session(self) -> Session:
        """Получение сессии БД"""
        if not self.local_session:
            self.connect()
        return self.local_session()
    
    def create_or_get_site(self, name: str, base_url: str, language: str = None) -> Optional[int]:
        """
        Создание или получение ID сайта
        
        Args:
            name: Название сайта
            base_url: Базовый URL
            language: Язык сайта
            
        Returns:
            ID сайта или None при ошибке
        """
        session = self.get_session()
        
        try:
            # Поиск существующего сайта
            result = session.execute(
                sqlalchemy.text("SELECT id FROM sites WHERE base_url = :base_url"),
                {"base_url": base_url}
            ).fetchone()
            
            if result:
                site_id = result[0]
                logger.info(f"Найден существующий сайт: {name} (ID: {site_id})")
                return site_id
            
            # Создание нового сайта
            result = session.execute(
                sqlalchemy.text("""
                    INSERT INTO sites (name, base_url, language)
                    VALUES (:name, :base_url, :language)
                """),
                {
                    "name": name,
                    "base_url": base_url,
                    "language": language
                }
            )
            session.commit()
            site_id = result.lastrowid
            
            logger.info(f"Создан новый сайт: {name} (ID: {site_id})")
            return site_id
            
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Ошибка при создании сайта: {e}")
            return None
        finally:
            session.close()
    
    def save_page(self, site_id: int, url: str, pattern: str, title: str,
                  language: str, html_path: str, metadata_path: str) -> Optional[int]:
        """
        Сохранение информации о странице
        
        Args:
            site_id: ID сайта
            url: URL страницы
            pattern: Паттерн URL
            title: Заголовок страницы
            language: Язык страницы
            html_path: Путь к HTML файлу
            metadata_path: Путь к файлу метаданных
            
        Returns:
            ID страницы или None при ошибке
        """
        session = self.get_session()
        
        try:
            # Проверка существования
            result = session.execute(
                sqlalchemy.text("SELECT id FROM pages WHERE site_id = :site_id AND url = :url"),
                {"site_id": site_id, "url": url}
            ).fetchone()
            
            if result:
                logger.debug(f"Страница уже существует: {url}")
                return result[0]
            
            # Вставка новой страницы
            result = session.execute(
                sqlalchemy.text("""
                    INSERT INTO pages (site_id, url, pattern, title, language, html_path, metadata_path)
                    VALUES (:site_id, :url, :pattern, :title, :language, :html_path, :metadata_path)
                """),
                {
                    "site_id": site_id,
                    "url": url,
                    "pattern": pattern,
                    "title": title,
                    "language": language,
                    "html_path": html_path,
                    "metadata_path": metadata_path
                }
            )
            session.commit()
            
            return result.lastrowid
            
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Ошибка сохранения страницы: {e}")
            return None
        finally:
            session.close()
    
    def get_page_by_id(self, page_id: int) -> Optional[Page]:
        """
        Получение страницы по ID
        
        Args:
            page_id: ID страницы
            
        Returns:
            Объект Page или None если не найдена
        """
        session = self.get_session()
        
        try:
            result = session.execute(
                sqlalchemy.text("SELECT * FROM pages WHERE id = :page_id"),{"page_id": page_id}).fetchone()
            
            if not result:
                logger.warning(f"Страница с ID {page_id} не найдена")
                return None
            
            page = Page.model_validate(dict(result._mapping))
            return page
            
        except SQLAlchemyError as e:
            logger.error(f"Ошибка получения страницы по ID: {e}")
            return None
        finally:
            session.close()
    
    def close(self):
        """Закрытие подключения"""
        if self.engine:
            self.engine.dispose()
            logger.info("Подключение к MySQL закрыто")
