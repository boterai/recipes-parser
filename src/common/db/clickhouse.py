"""
Менеджер работы с ClickHouse для хранения слов из описаний рецептов
Также может использоваться как векторная БД (экспериментально)
"""

import logging
from typing import Any, Optional
import re
from config.db_config import ClickHouseConfig
import clickhouse_connect
from clickhouse_connect.driver import Client
from src.models.page import Page
from src.common.embedding import prepare_text, EmbeddingFunction

logger = logging.getLogger(__name__)

CONNECTION_ERROR = "Ошибка подключения к ClickHouse"

class ClickHouseManager:
    """Менеджер для работы с ClickHouse (включая векторную БД)"""
    
    def __init__(self, embedding_dim: int = 384):
        """
        Инициализация подключения к ClickHouse
        
        Args:
            embedding_dim: Размерность векторов эмбеддингов
        """
        self.client = None
        self.embedding_dim = embedding_dim
        
    def connect(self) -> bool:
        """Установка подключения к ClickHouse"""
        try:
            self.client: Client  = clickhouse_connect.get_client(**ClickHouseConfig.get_connection_params())
            
            # Проверка подключения
            self.client.command('SELECT 1')
            
            logger.info("Успешное подключение к ClickHouse")
            
            # Создание таблиц если их нет
            return self.create_tables()
        except Exception as e:
            logger.error(f"Ошибка подключения к ClickHouse: {e}")
            return False
    
    def create_tables(self) -> bool:
        """Создание таблиц в ClickHouse"""
        if not self.client:
            return False
        
        try:
            with open('db/schemas/clickhouse.sql', 'r', encoding='utf-8') as f:
                migration_schema = f.read()
        
            # Разбиваем на отдельные команды
            statements = [
                stmt.strip() 
                for stmt in migration_schema.split(';') 
                if stmt.strip() and not stmt.strip().startswith('#')
            ]
            
            # Выполняем по одному
            for statement in statements:
                if statement:
                    self.client.command(statement)
            
            logger.info("Таблицы ClickHouse созданы или уже существуют")
            return True
        except Exception as e:
            logger.error(f"Ошибка создания таблиц ClickHouse: {e}")
        
        return False
    
    def close(self):
        """Закрытие подключения"""
        if self.client:
            self.client.close()
            logger.info("Подключение к ClickHouse закрыто")
    
    # ===== Методы интерфейса VectorDBInterface =====
    
    def add_recipe(self, page: Page, embedding_function: EmbeddingFunction) -> bool:
        """
        Добавление одного рецепта в векторную БД
        
        Args:
            page: Объект страницы с рецептом
            embedding_function: Функция для создания эмбеддингов
            
        Returns:
            True если успешно добавлено
        """
        if not self.client:
            logger.warning(CONNECTION_ERROR)
            return False
        
        try:
            # Подготовка текста и создание эмбеддинга
            recipe_embedding = prepare_text(page, "main")
            recipe_embedding = embedding_function([recipe_embedding])

            ingredients_text = prepare_text(page, "ingredients")
            ingredient_embedding = embedding_function([ingredients_text])

            description_text = prepare_text(page, "description")
            description_embedding = embedding_function([description_text])

            instructions_text = prepare_text(page, "instructions")
            instruction_embedding = embedding_function([instructions_text])

            
            # Вставка в таблицу
            self.client.insert(
                "recipe_keywords",
               [[
                    page.id,
                    page.dish_name,
                    page.language,
                    page.ingredients_names, # временно в качестве кейвордов только имена ингредиентов
                    recipe_embedding,
                    ingredient_embedding,
                    description_embedding,
                    instruction_embedding
               ]],
               column_names=[
                   'page_id',
                   'dish_name',
                   'language',
                   'keywords',
                   'recipe_embedding',
                   'ingredient_embedding',
                   'description_embedding',
                   'instruction_embedding'
               ]
            )
            
            logger.info(f"Рецепт page_id={page.id} добавлен в ClickHouse")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка добавления рецепта в ClickHouse: {e}")
            return False
    
    def add_recipes_batch(self, pages: list[Page], embedding_function: EmbeddingFunction, batch_size: int = 100) -> int:
        """
        Массовое добавление рецептов
        
        Args:
            pages: Список страниц с рецептами
            embedding_function: Функция для создания эмбеддингов
            batch_size: Размер батча
            
        Returns:
            Количество успешно добавленных рецептов
        """
        if not self.client:
            logger.warning(CONNECTION_ERROR)
            return 0
        
        try:
            count = 0
            # Обработка батчами
            for i in range(0, len(pages), batch_size):
                batch = pages[i:i + batch_size]
                rows = []
                for page in pages[i:i + batch_size]:
                    # Подготовка текста и создание эмбеддинга
                    recipe_embedding = embedding_function(prepare_text(page, "main"))
                    ingredient_embedding = embedding_function(prepare_text(page, "ingredients"))
                    description_embedding = embedding_function(prepare_text(page, "description"))
                    instructions_embedding = embedding_function(prepare_text(page, "instructions"))
                    ingredients = [i.removeprefix(",").removesuffix(",") for i in  page.ingredients_names.split(', ')]  # временно в качестве кейвордов только имена ингредиентов
                    rows.append([page.id, 
                                 page.dish_name,
                                 page.language,
                                 ingredients,  # временно в качестве кейвордов только имена ингредиентов
                                 recipe_embedding,
                                 ingredient_embedding,
                                 description_embedding,
                                 instructions_embedding
                                 ]
                    )
                
                
                self.client.insert(
                "recipe_keywords",
                rows,
                column_names=[
                    'page_id', 'dish_name', 'language', 'keywords',
                    'recipe_embedding', 'ingredient_embedding', 
                    'description_embedding', 'instruction_embedding'
                ]
                )
                count += len(batch)
                logger.info(f"Добавлен батч {i // batch_size + 1}: {len(batch)} рецептов")
            
            logger.info(f"Всего добавлено {count} рецептов в ClickHouse")
            return count
            
        except Exception as e:
            logger.error(f"Ошибка массового добавления рецептов: {e}")
            return 0
    
    def search(
    self,
    query_vector: list[float],
    collection_name: str = "recipes",
    limit: int = 10,
    site_id: Optional[int] = None,
    score_threshold: float = 0.0
) -> list[dict[str, Any]]:
        """
        Поиск похожих рецептов по вектору (через косинусное расстояние)
        
        Args:
            query_vector: Вектор запроса
            collection_name: Тип эмбеддинга ('recipes', 'ingredients', 'instructions', 'descriptions')
            limit: Количество результатов
            site_id: Фильтр по сайту (не используется в новой схеме)
            score_threshold: Минимальный порог схожести
            
        Returns:
            Список найденных рецептов с метаданными
        """
        if not self.client:
            logger.warning("ClickHouse не подключен")
            return []
        
        try:
            
            # Выбираем колонку эмбеддинга в зависимости от collection_name
            embedding_column_map = {
                "recipes": "recipe_embedding",
                "ingredients": "ingredient_embedding",
                "instructions": "instructions_embedding",
                "descriptions": "description_embedding"
            }
            
            embedding_column = embedding_column_map.get(collection_name, "recipe_embedding")
            
            # Запрос поиска
            query = f"""
                SELECT 
                    page_id,
                    argMax(dish_name, updated_at) as dish_name,
                    argMax(language, updated_at) as language,
                    argMax(keywords, updated_at) as keywords,
                    cosineDistance(argMax({embedding_column}, updated_at), %(query_vector)s) as distance
                FROM recipe_keywords
                GROUP BY page_id
                ORDER BY distance ASC
                LIMIT %(limit)s
            """
            
            results = self.client.query(
                query,
                parameters={'query_vector': query_vector, 'limit': limit}
            )
            
            # Преобразуем результаты
            output = []
            for row in results.result_rows:
                page_id, dish_name, language, keywords, distance = row
                
                # Вычисляем score (1 - distance для косинусного расстояния)
                score = 1.0 - distance
                
                # Фильтруем по порогу
                if score < score_threshold:
                    continue
                
                output.append({
                    'page_id': page_id,
                    'dish_name': dish_name,
                    'language': language,
                    'keywords': keywords,
                    'score': score
                })
            
            logger.info(f"Найдено {len(output)} похожих рецептов")
            return output
            
        except Exception as e:
            logger.error(f"Ошибка поиска в ClickHouse: {e}")
            return []

