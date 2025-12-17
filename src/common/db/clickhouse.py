"""
Менеджер работы с ClickHouse для хранения слов из описаний рецептов
Также может использоваться как векторная БД (экспериментально)
"""
import time
import logging
from typing import Optional
from config.db_config import ClickHouseConfig
import clickhouse_connect
from clickhouse_connect.driver import Client
from src.models.recipe import Recipe
logger = logging.getLogger(__name__)

CONNECTION_ERROR = "Ошибка подключения к ClickHouse"

class ClickHouseManager:
    """Менеджер для работы с ClickHouse (включая векторную БД)"""
    
    def __init__(self):
        """
        Инициализация подключения к ClickHouse
        
        Args:
            embedding_dim: Размерность векторов эмбеддингов
        """
        self.client = None
        
    def connect(self, retry_attempts: int = 3, retry_delay: float = 2.0) -> bool:
        """
        Установка подключения к ClickHouse с повторными попытками
        
        Args:
            retry_attempts: Количество попыток подключения
            retry_delay: Базовая задержка между попытками (в секундах)
        
        Returns:
            True если подключение успешно, False иначе
        """        
        conn_params = ClickHouseConfig.get_connection_params()
        
        for attempt in range(retry_attempts):
            try:
                logger.info(f"Попытка подключения к ClickHouse {attempt + 1}/{retry_attempts}...")
                
                self.client: Client = clickhouse_connect.get_client(
                    host=conn_params['host'],
                    user=conn_params['user'],
                    password=conn_params['password'],
                    secure=True,
                    connect_timeout=10,
                    send_receive_timeout=30
                )
                
                # Проверка подключения
                self.client.command('SELECT 1')
                
                logger.info("✓ Успешное подключение к ClickHouse")
                
                # Создание таблиц если их нет
                return self.create_tables()
                
            except Exception as e:
                if attempt < retry_attempts - 1:
                    # Экспоненциальная задержка: delay * 2^attempt
                    delay = retry_delay * (2 ** attempt)
                    logger.warning(f"✗ Ошибка подключения к ClickHouse (попытка {attempt + 1}/{retry_attempts}): {e}")
                    logger.info(f"Повторная попытка через {delay:.1f}с...")
                    time.sleep(delay)
                else:
                    logger.error(f"✗ Не удалось подключиться к ClickHouse после {retry_attempts} попыток: {e}")
        
        # Если дошли сюда - все попытки исчерпаны
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
    
    def insert_recipes_batch(self, recipes: list[Recipe], table_name: str = "recipe_ru") -> int:
        """
        Батчевая вставка рецептов в ClickHouse
        
        Args:
            recipes: Список объектов Recipe
            table_name: Имя таблицы (recipe_ru, recipe_en и т.д.)
        
        Returns:
            Количество успешно вставленных рецептов
        """
        if not self.client:
            logger.error("ClickHouse не подключен")
            return 0
        
        if not recipes:
            return 0
        
        try:
            # Подготавливаем данные для вставки
            data = []
            for recipe in recipes:
                data.append([
                    recipe.page_id,
                    recipe.site_id,
                    recipe.dish_name or "",
                    recipe.description or "",
                    recipe.instructions or "",
                    recipe.ingredients or [],
                    recipe.tags or [],
                    recipe.cook_time,
                    recipe.prep_time,
                    recipe.total_time,
                    recipe.nutrition_info,
                    recipe.category
                ])
            
            if not data:
                logger.warning("Нет валидных рецептов для вставки")
                return 0
            
            # Батчевая вставка
            self.client.insert(
                table_name,
                data,
                column_names=[
                    'page_id', 'site_id', 'dish_name', 'description', 'instructions',
                    'ingredients', 'tags', 'cook_time', 'prep_time', 
                    'total_time', 'nutrition_info', 'category'
                ]
            )
            
            logger.info(f"✓ Вставлено {len(data)} рецептов в {table_name}")
            return len(data)
            
        except Exception as e:
            logger.error(f"Ошибка батчевой вставки рецептов: {e}")
            import traceback
            traceback.print_exc()
            return 0
    
    def upsert_recipes_batch(self, recipes: list, table_name: str = "recipe_ru") -> int:
        """
        Батчевая вставка/обновление рецептов (благодаря ReplacingMergeTree)
        
        Args:
            recipes: Список объектов Recipe
            table_name: Имя таблицы (recipe_ru, recipe_en и т.д.)
        
        Returns:
            Количество успешно обработанных рецептов
        """
        # ReplacingMergeTree автоматически заменит записи с одинаковым page_id
        return self.insert_recipes_batch(recipes, table_name)
    
    def get_recipe_by_id(self, page_id: int, table_name: str = "recipe_ru") -> Optional[Recipe]:
        """
        Получение рецепта по ID
        
        Args:
            page_id: ID страницы
            table_name: Имя таблицы
        
        Returns:
            Объект Recipe или None
        """
        if not self.client:
            logger.error("ClickHouse не подключен")
            return None
        
        try:
            query = f"""
                SELECT 
                    page_id, site_id, dish_name, description, instructions,
                    ingredients, tags, cook_time, prep_time,
                    total_time, nutrition_info, category
                FROM {table_name}
                WHERE page_id = %(page_id)s
                ORDER BY last_updated DESC
                LIMIT 1
            """
            
            # Используем query_df для эффективного парсинга
            df = self.client.query_df(query, parameters={'page_id': page_id})
            
            if len(df) > 0:
                row = df.iloc[0]
                return Recipe(
                    page_id=int(row['page_id']),
                    site_id=int(row['site_id']),
                    dish_name=str(row['dish_name']),
                    description=str(row['description']) if row['description'] else None,
                    instructions=str(row['instructions']),
                    ingredients=list(row['ingredients']) if row['ingredients'] else [],
                    tags=list(row['tags']) if row['tags'] else None,
                    cook_time=str(row['cook_time']) if row['cook_time'] else None,
                    prep_time=str(row['prep_time']) if row['prep_time'] else None,
                    total_time=str(row['total_time']) if row['total_time'] else None,
                    nutrition_info=str(row['nutrition_info']) if row['nutrition_info'] else None,
                    category=str(row['category']) if row['category'] else None
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка получения рецепта {page_id}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_recipes_batch(self, page_ids: list[int], table_name: str = "recipe_ru") -> list[Recipe]:
        """
        Получение батча рецептов по списку ID
        
        Args:
            page_ids: Список ID страниц
            table_name: Имя таблицы
        
        Returns:
            Список объектов Recipe
        """
        if not self.client or not page_ids:
            return []
        
        try:
            query = f"""
                SELECT 
                    page_id, 
                    argMax(dish_name, last_updated) as dish_name, 
                    argMax(description, last_updated) as description,
                    armax(instructions, last_updated) as instructions,
                    argMax(ingredients, last_updated) as ingredients,
                    argMax(tags, last_updated) as tags,
                    argMax(cook_time, last_updated) as cook_time,
                    argMax(prep_time, last_updated) as prep_time,
                    argMax(total_time, last_updated) as total_time,
                    argMax(nutrition_info, last_updated) as nutrition_info,
                    argMax(category, last_updated) as category
                FROM {table_name}
                WHERE page_id IN %(page_ids)s
                ORDER BY page_id
                GROUP BY page_id
            """
            
            # Используем query_df для эффективного парсинга батча
            df = self.client.query_df(query, parameters={'page_ids': page_ids})
            
            if len(df) == 0:
                return []
            
            # Векторизованная конвертация DataFrame в список Recipe
            recipes = []
            for _, row in df.iterrows():
                try:
                    recipe = Recipe(
                        page_id=int(row['page_id']),
                        dish_name=str(row['dish_name']),
                        description=str(row['description']) if row['description'] else None,
                        instructions=str(row['instructions']),
                        ingredients=list(row['ingredients']) if row['ingredients'] else [],
                        tags=list(row['tags']) if row['tags'] else None,
                        cook_time=str(row['cook_time']) if row['cook_time'] else None,
                        prep_time=str(row['prep_time']) if row['prep_time'] else None,
                        total_time=str(row['total_time']) if row['total_time'] else None,
                        nutrition_info=str(row['nutrition_info']) if row['nutrition_info'] else None,
                        category=str(row['category']) if row['category'] else None
                    )
                    recipes.append(recipe)
                except Exception as e:
                    logger.warning(f"Ошибка парсинга рецепта page_id={row['page_id']}: {e}")
                    continue
            
            return recipes
            
        except Exception as e:
            logger.error(f"Ошибка получения батча рецептов: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_page_ids_by_site(self, site_id: int, table_name: str = "recipe_ru") -> list[int]:
        """
        Получение всех page_id для заданного site_id
        
        Args:
            site_id: ID сайта
            table_name: Имя таблицы
        
        Returns:
            Список всех page_id для данного сайта (отсортированный по возрастанию)
        """
        if not self.client:
            logger.error("ClickHouse не подключен")
            return []
        
        try:
            query = f"""
                SELECT DISTINCT page_id
                FROM {table_name}
                WHERE site_id = %(site_id)s
                ORDER BY page_id
            """
            
            df = self.client.query_df(query, parameters={'site_id': site_id})
            
            if len(df) == 0:
                logger.info(f"Нет рецептов для site_id={site_id} в {table_name}")
                return []
            
            page_ids = df['page_id'].astype(int).tolist()
            logger.info(f"Найдено {len(page_ids)} рецептов для site_id={site_id}")
            return page_ids
            
        except Exception as e:
            logger.error(f"Ошибка получения page_id для site_id={site_id}: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_last_page_id_by_site(self, site_id: int, table_name: str = "recipe_ru") -> Optional[int]:
        """
        Получение последнего (максимального) page_id для заданного site_id
        
        Args:
            site_id: ID сайта
            table_name: Имя таблицы
        
        Returns:
            Последний page_id или None если рецептов нет
        """
        if not self.client:
            logger.error("ClickHouse не подключен")
            return None
        
        try:
            query = f"""
                SELECT MAX(page_id) as max_page_id
                FROM {table_name}
                WHERE site_id = %(site_id)s
            """
            
            df = self.client.query_df(query, parameters={'site_id': site_id})
            
            if len(df) == 0 or df.iloc[0]['max_page_id'] is None:
                logger.info(f"Нет рецептов для site_id={site_id} в {table_name}")
                return None
            
            last_page_id = int(df.iloc[0]['max_page_id'])
            logger.info(f"Последний page_id для site_id={site_id}: {last_page_id}")
            return last_page_id
            
        except Exception as e:
            logger.error(f"Ошибка получения последнего page_id для site_id={site_id}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def close(self):
        """Закрытие подключения"""
        if self.client:
            self.client.close()
            logger.info("Подключение к ClickHouse закрыто")
    