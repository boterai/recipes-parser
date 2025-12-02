
"""
Модуль для векторизации рецептов с использованием векторных БД.
"""

from typing import Any, Optional
from pathlib import Path
import sys
import logging

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.models.page import Page
from src.common.db.qdrant import QdrantManager
from src.common.db.vector_db_interface import VectorDBInterface

logger = logging.getLogger(__name__)

NO_EMBEDDING_ERROR = "Embedding function не установлена. Используйте set_embedding_function()"

class RecipeVectorizer:
    """Векторизатор рецептов на основе векторной БД"""
    
    def __init__(self, vector_db: Optional[VectorDBInterface] = None, embedding_dim: int = 384):
        """
        Инициализация векторизатора
        
        Args:
            vector_db: Реализация векторной БД (по умолчанию QdrantManager)
            embedding_dim: Размерность векторов эмбеддингов
        """
        if vector_db is None:
            self.vector_db = QdrantManager(embedding_dim=embedding_dim)
        else:
            self.vector_db = vector_db
        
        self.embedding_function = None
        
    def connect(self) -> bool:
        """Подключение к векторной БД"""
        return self.vector_db.connect()
    
    def set_embedding_function(self, embedding_function):
        """
        Установка функции для создания эмбеддингов
        
        Args:
            embedding_function: Функция, принимающая текст и возвращающая вектор
        """
        self.embedding_function = embedding_function
    
    def add_recipe(self, page: Page) -> bool:
        """
        Добавление одного рецепта в векторную БД
        
        Args:
            page: Объект страницы с рецептом
            
        Returns:
            True если успешно добавлено
        """
        if not self.embedding_function:
            logger.error(NO_EMBEDDING_ERROR)
            return False
        
        return self.vector_db.add_recipe(page, self.embedding_function)
    
    def add_recipes_batch(self, pages: list[Page], batch_size: int = 100) -> int:
        """
        Массовое добавление рецептов
        
        Args:
            pages: Список объектов страниц с рецептами
            batch_size: Размер батча
            
        Returns:
            Количество успешно добавленных рецептов
        """
        if not self.embedding_function:
            logger.error(NO_EMBEDDING_ERROR)
            return 0
        
        return self.vector_db.add_recipes_batch(pages, self.embedding_function, batch_size)
    
    def search(
        self,
        query: str,
        limit: int = 5,
        site_id: Optional[int] = None,
        collection_name: str = "recipes",
        score_threshold: float = 0.0
    ) -> list[dict[str, Any]]:
        """
        Поиск похожих рецептов
        
        Args:
            query: Поисковый запрос (текст)
            limit: Количество результатов
            site_id: Фильтр по сайту
            collection_name: Коллекция для поиска ("recipes", "ingredients", "instructions", "descriptions")
            score_threshold: Минимальный порог схожести
            
        Returns:
            Список найденных рецептов с метаданными
        """
        if not self.embedding_function:
            logger.error(NO_EMBEDDING_ERROR)
            return []
        
        # Создаем вектор запроса
        query_vector = self.embedding_function(query)
        
        # Выполняем поиск через векторную БД
        return self.vector_db.search(
            query_vector=query_vector,
            collection_name=collection_name,
            limit=limit,
            site_id=site_id,
            score_threshold=score_threshold
        )
    
    def delete_recipe(self, page_id: int) -> bool:
        """
        Удаление рецепта из векторной БД
        
        Args:
            page_id: ID страницы в БД
            
        Returns:
            True если успешно удалено
        """
        return self.vector_db.delete_by_page_id(page_id)
    
    def update_recipe(self, page: Page) -> bool:
        """
        Обновление рецепта (удаление + добавление)
        
        Args:
            page: Обновленный объект страницы
            
        Returns:
            True если успешно обновлено
        """
        self.delete_recipe(page.id)
        return self.add_recipe(page)
    
    def get_stats(self) -> dict[str, Any]:
        """
        Получение статистики коллекции
        
        Returns:
            Словарь со статистикой
        """
        return self.vector_db.get_stats()
    
    def close(self):
        """Закрытие подключения"""
        self.vector_db.close()



