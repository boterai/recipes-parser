
"""
Модуль для векторизации рецептов с использованием Qdrant.
"""

# Для чего: 
# Искать похожие рецепты и вариации на основе ингредиентов и инструкций.

from typing import List, Dict, Any, Optional
from pathlib import Path
import sys
import logging

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.models.page import Page
from src.common.db.qdrant import QdrantManager

logger = logging.getLogger(__name__)


class RecipeVectorizer:
    """Векторизатор рецептов на основе Qdrant"""
    
    def __init__(self, embedding_dim: int = 384):
        """
        Инициализация векторизатора
        
        Args:
            embedding_dim: Размерность векторов эмбеддингов
        """
        self.qdrant = QdrantManager(embedding_dim=embedding_dim)
        self.embedding_function = None
        
    def connect(self) -> bool:
        """Подключение к Qdrant"""
        return self.qdrant.connect()
    
    def set_embedding_function(self, embedding_function):
        """
        Установка функции для создания эмбеддингов
        
        Args:
            embedding_function: Функция, принимающая текст и возвращающая вектор
        """
        self.embedding_function = embedding_function
    
    def _prepare_text(self, page: Page, collection_type: str = "main") -> str:
        """
        Подготовка текста для создания эмбеддинга
        
        Args:
            page: Объект страницы с рецептом
            collection_type: Тип коллекции
            
        Returns:
            Объединенный текст для эмбеддинга
        """
        return self.qdrant._prepare_text(page, collection_type)
    
    def add_recipe(self, page: Page) -> bool:
        """
        Добавление одного рецепта в векторную БД
        
        Args:
            page: Объект страницы с рецептом
            
        Returns:
            True если успешно добавлено
        """
        if not self.embedding_function:
            logger.error("Embedding function не установлена. Используйте set_embedding_function()")
            return False
        
        return self.qdrant.add_recipe(page, self.embedding_function)
    
    def add_recipes_batch(self, pages: List[Page], batch_size: int = 100) -> int:
        """
        Массовое добавление рецептов
        
        Args:
            pages: Список объектов страниц с рецептами
            batch_size: Размер батча
            
        Returns:
            Количество успешно добавленных рецептов
        """
        if not self.embedding_function:
            logger.error("Embedding function не установлена. Используйте set_embedding_function()")
            return 0
        
        return self.qdrant.add_recipes_batch(pages, self.embedding_function, batch_size)
    
    def search(
        self,
        query: str,
        n_results: int = 5,
        site_id: Optional[int] = None,
        collection_name: str = "recipes",
        score_threshold: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Поиск похожих рецептов
        
        Args:
            query: Поисковый запрос (текст)
            n_results: Количество результатов
            site_id: Фильтр по сайту
            collection_name: Коллекция для поиска ("recipes", "ingredients", "instructions", "descriptions")
            score_threshold: Минимальный порог схожести
            
        Returns:
            Список найденных рецептов с метаданными
        """
        if not self.embedding_function:
            logger.error("Embedding function не установлена. Используйте set_embedding_function()")
            return []
        
        # Создаем вектор запроса
        query_vector = self.embedding_function(query)
        
        # Выполняем поиск через Qdrant
        return self.qdrant.search(
            query_vector=query_vector,
            collection_name=collection_name,
            limit=n_results,
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
        return self.qdrant.delete_by_page_id(page_id)
    
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
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получение статистики коллекции
        
        Returns:
            Словарь со статистикой
        """
        return self.qdrant.get_stats()
    
    def close(self):
        """Закрытие подключения"""
        self.qdrant.close()



