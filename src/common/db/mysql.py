"""
Менеджер базы данных для работы с MySQL
"""
import time
import logging
from typing import Optional
import sqlalchemy
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

from config.db_config import MySQLConfig
from src.models import Page
from src.models import Recipe
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
    
    def create_or_get_site(self, name: str, base_url: str, language: str = None) -> tuple[Optional[int], Optional[str]]:
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
                sqlalchemy.text("SELECT id, languge FROM sites WHERE base_url = :base_url"),
                {"base_url": base_url}
            ).fetchone()
            
            if result:
                site_id = result[0]
                language = result[1]
                logger.info(f"Найден существующий сайт: {name} (ID: {site_id}, language: {language})")
                return site_id, language
            
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
            return site_id, None
            
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Ошибка при создании сайта: {e}")
            return None, None
        finally:
            session.close()

    def update_site_language(self, site_id: int, language: str) -> bool:
        """
        Обновление языка сайта
        
        Args:
            site_id: ID сайта
            laanguage: Язык сайта

        """
        session = self.get_session()
        
        try:
            session.execute(
                sqlalchemy.text("""
                    UPDATE sites SET language = :language WHERE id = :site_id
                """),
                {
                    "language": language,
                    "site_id": site_id
                }
            )
            session.commit()
            logger.info(f"Обновлен язык сайта ID {site_id} на {language}")
            return True
            
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Ошибка при обновлении языка сайта: {e}")
            return False
        finally:
            session.close()
    
    def save_page(self, site_id: int, url: str, pattern: str, title: str,
                  language: str, html_path: str) -> Optional[int]:
        """
        Сохранение информации о странице
        
        Args:
            site_id: ID сайта
            url: URL страницы
            pattern: Паттерн URL
            title: Заголовок страницы
            language: Язык страницы
            html_path: Путь к HTML файлу
            
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
                    INSERT INTO pages (site_id, url, pattern, title, language, html_path)
                    VALUES (:site_id, :url, :pattern, :title, :language, :html_path)
                """),
                {
                    "site_id": site_id,
                    "url": url,
                    "pattern": pattern,
                    "title": title,
                    "language": language,
                    "html_path": html_path,
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
    
    def get_page_by_id(self, page_id: int, table_name: str = "pages") -> Optional[Page]:
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
                sqlalchemy.text(f"SELECT * FROM {table_name} WHERE id = :page_id"),{"page_id": page_id}).fetchone()
            
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

    def get_recipe_by_id(self, page_id: int, table_name: str = "pages") -> Optional[Recipe]:
        """
        Получение рецепта по ID страницы
        
        Args:
            page_id: ID страницы
            
        Returns:
            Объект Page или None если не найдена
        """
        session = self.get_session()
        
        try:
            result = session.execute(
                sqlalchemy.text(f"""SELECT r.*,
                                p.nutrition_info,
                                p.prep_time,
                                p.cook_time,
                                p.total_time
                                FROM {table_name} r
                                JOIN pages p ON p.id = r.page_id
                                WHERE r.page_id = :page_id"""),{"page_id": page_id}).fetchone()
            
            if not result:
                logger.warning(f"Рецепт с ID {page_id} не найден")
                return None
            
            recipe = Recipe.model_validate(dict(result._mapping))
            return recipe
            
        except SQLAlchemyError as e:
            logger.error(f"Ошибка получения рецепта по ID: {e}")
            return None
        finally:
            session.close()
    
    def get_pages_by_site_id(self, site_id: int, limit: Optional[int] = None, is_recipe: bool|None = None) -> list[Page]:
        """
        Получение страниц по ID сайта
        
        Args:
            site_id: ID сайта
            limit: Максимальное количество страниц (None = все)
            
        Returns:
            Список объектов Page
        """
        session = self.get_session()
        pages: list[Page] = []
        
        try:
            sql = "SELECT * FROM pages WHERE site_id = :site_id"
            if is_recipe is not None:
                sql += " AND is_recipe = :is_recipe"
            if limit:
                sql += f" LIMIT {limit}"
            
            result = session.execute(sqlalchemy.text(sql), {"site_id": site_id, "is_recipe": is_recipe} if is_recipe is not None else {"site_id": site_id})
            rows = result.fetchall()
            pages = [Page.model_validate(dict(row._mapping)) for row in rows]
            
            return pages
            
        except SQLAlchemyError as e:
            logger.error(f"Ошибка получения страниц по site_id: {e}")
        finally:
            session.close()
        
        return pages
    
    def close(self):
        """Закрытие подключения"""
        if self.engine:
            self.engine.dispose()
            logger.info("Подключение к MySQL закрыто")
