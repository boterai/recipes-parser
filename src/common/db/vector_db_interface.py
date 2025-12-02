from typing import Protocol, Any, Optional
from src.models.page import Page

class VectorDBInterface(Protocol):
    """Интерфейс для векторных баз данных"""
    
    def connect(self) -> bool:
        """Подключение к БД"""
        ...
    
    def add_recipe(self, page: Page, embedding_function) -> bool:
        """Добавление одного рецепта"""
        ...
    
    def add_recipes_batch(self, pages: list[Page], embedding_function, batch_size: int = 100) -> int:
        """Массовое добавление рецептов"""
        ...
    
    def search(self, query_vector: list[float], collection_name: str = None, 
               limit: int = 10, site_id: Optional[int] = None, 
               score_threshold: float = 0.0) -> list[dict[str, Any]]:
        """Поиск похожих рецептов"""
        ...
    
    def delete_by_page_id(self, page_id: int) -> bool:
        """Удаление рецепта"""
        ...
    
    def get_stats(self) -> dict[str, Any]:
        """Получение статистики"""
        ...
    
    def close(self):
        """Закрытие подключения"""
        ...
