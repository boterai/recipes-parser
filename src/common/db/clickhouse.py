"""
Менеджер работы с ClickHouse для хранения слов из описаний рецептов
Также может использоваться как векторная БД (экспериментально)
"""
import time
import logging
import urllib3
from typing import Optional
from config.db_config import ClickHouseConfig
import clickhouse_connect
from clickhouse_connect.driver import Client
from src.models.recipe import Recipe
from urllib.parse import urlparse
from urllib3.contrib.socks import SOCKSProxyManager

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
        
        # Настройка пула с прокси если указан
        pool_manager = None
        if conn_params.get('proxy'):
            logger.info(f"Использование прокси для ClickHouse: {conn_params['proxy']}")
            
            # Парсим URL прокси
            parsed = urlparse(conn_params['proxy'])
            
            # Проверяем тип прокси (HTTP/HTTPS или SOCKS5)
            if parsed.scheme in ('socks5', 'socks5h'):
                
                pool_manager = SOCKSProxyManager(
                    conn_params['proxy'],
                    timeout=urllib3.Timeout(connect=30.0, read=300.0),
                    retries=urllib3.Retry(total=3, backoff_factor=0.5)
                )
            else:
                # HTTP/HTTPS прокси
                proxy_headers = None
                if parsed.username and parsed.password:
                    proxy_headers = urllib3.make_headers(
                        proxy_basic_auth=f"{parsed.username}:{parsed.password}"
                    )
                
                proxy_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
                
                pool_manager = urllib3.ProxyManager(
                    proxy_url,
                    proxy_headers=proxy_headers,
                    timeout=urllib3.Timeout(connect=30.0, read=300.0),
                    retries=urllib3.Retry(total=3, backoff_factor=0.5)
                )
        
        try:
            for attempt in range(retry_attempts):
                try:
                    logger.info(f"Попытка подключения к ClickHouse {attempt + 1}/{retry_attempts}...")
                    
                    # Используем интерфейс в зависимости от secure
                    interface = 'https' if conn_params['secure'] else 'http'
                    
                    client_kwargs = {
                        'host': conn_params['host'],
                        'database': conn_params['database'],
                        'port': conn_params['port'],
                        'user': conn_params['user'],
                        'password': conn_params['password'],
                        'secure': conn_params['secure'],
                        'interface': interface,
                        'connect_timeout': 30,
                        'send_receive_timeout': 300
                    }
                    
                    # Добавляем pool_manager если есть прокси
                    if pool_manager:
                        client_kwargs['pool_mgr'] = pool_manager
                    
                    self.client: Client = clickhouse_connect.get_client(**client_kwargs)
                    
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
        finally:
            # Закрываем pool_manager если был создан
            if pool_manager:
                pool_manager.clear()
    
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
    
    def insert_recipes_batch(self, recipes: list[Recipe], table_name: str = "recipe_en") -> int:
        """
        Батчевая вставка рецептов в ClickHouse
        
        Args:
            recipes: Список объектов Recipe
            table_name: Имя таблицы (recipe_en, recipe_en и т.д.)
        
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
                    recipe.vectorised,
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
                    'total_time', 'nutrition_info', 'vectorised', 'category'
                ]
            )
            
            logger.info(f"✓ Вставлено {len(data)} рецептов в {table_name}")
            return len(data)
            
        except Exception as e:
            logger.error(f"Ошибка батчевой вставки рецептов: {e}")
            import traceback
            traceback.print_exc()
            return 0
    
    def upsert_recipes_batch(self, recipes: list, table_name: str = "recipe_en") -> int:
        """
        Батчевая вставка/обновление рецептов (благодаря ReplacingMergeTree)
        
        Args:
            recipes: Список объектов Recipe
            table_name: Имя таблицы (recipe_en, recipe_ru и т.д.)
        
        Returns:
            Количество успешно обработанных рецептов
        """
        # ReplacingMergeTree автоматически заменит записи с одинаковым page_id
        return self.insert_recipes_batch(recipes, table_name)
    
    def _parse_recipes_from_dataframe(self, df) -> list[Recipe]:
        """
        Общая функция для парсинга DataFrame в список Recipe
        
        Args:
            df: DataFrame с данными рецептов
            
        Returns:
            Список объектов Recipe
        """
        recipes = []
        for _, row in df.iterrows():
            try:
                site_id = row.get('site') or row.get('site_id') # чтоыб не пересекалось в argmax иногда используется site, чаще site_id
                site_id = int(site_id) if site_id is not None else 0
                recipe = Recipe(
                    page_id=int(row['page_id']),
                    site_id=site_id,
                    dish_name=str(row['dish_name']),
                    description=str(row['description']),
                    instructions=str(row['instructions']),
                    ingredients=list(row['ingredients']),
                    tags=list(row['tags']),
                    cook_time=str(row['cook_time']),
                    prep_time=str(row['prep_time']),
                    total_time=str(row['total_time']),
                    nutrition_info=str(row['nutrition_info']),
                    category=str(row['category']),
                    vectorised=bool(row.get('vectorised', False))
                )
                recipes.append(recipe)
            except Exception as e:
                logger.warning(f"Ошибка парсинга рецепта page_id={row['page_id']}: {e}")
                continue
        return recipes
    
    def get_recipes_by_ids(
        self, 
        page_ids: list[int],
        table_name: str = "recipe_en"
    ) -> list[Recipe]:
        """
        Получение рецептов по списку ID
        
        Args:
            page_ids: Список ID страниц
            table_name: Имя таблицы
        
        Returns:
            Список объектов Recipe
        """
        if not page_ids:
            logger.warning("Пустой список page_ids")
            return []
        
        try:
            query = f"""
                SELECT 
                    page_id,
                    argMax(site_id, last_updated) as site_id,
                    argMax(dish_name, last_updated) as dish_name, 
                    argMax(description, last_updated) as description,
                    argMax(instructions, last_updated) as instructions,
                    argMax(ingredients, last_updated) as ingredients,
                    argMax(tags, last_updated) as tags,
                    argMax(cook_time, last_updated) as cook_time,
                    argMax(prep_time, last_updated) as prep_time,
                    argMax(total_time, last_updated) as total_time,
                    argMax(nutrition_info, last_updated) as nutrition_info,
                    argMax(category, last_updated) as category,
                    argMax(vectorised, last_updated) as vectorised
                FROM {table_name}
                WHERE page_id IN %(page_ids)s
                GROUP BY page_id
                ORDER BY page_id
            """
            
            df = self.client.query_df(query, parameters={'page_ids': page_ids})
            
            if len(df) == 0:
                logger.info("Рецепты не найдены по списку ID")
                return []
            
            recipes = self._parse_recipes_from_dataframe(df)
            logger.info(f"Получено {len(recipes)} рецептов по списку из {len(page_ids)} ID")
            return recipes
            
        except Exception as e:
            logger.error(f"Ошибка получения рецептов по ID: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_recipes_by_site(
        self,
        site_id: int,
        limit: Optional[int] = None,
        vectorised: Optional[bool] = None,
        table_name: str = "recipe_en"
    ) -> list[Recipe]:
        """
        Получение рецептов по site_id с фильтрацией
        
        Args:
            site_id: ID сайта
            limit: Максимальное количество рецептов
            vectorised: Если True - только векторизованные, False - только невекторизованные, None - все
            table_name: Имя таблицы
        
        Returns:
            Список объектов Recipe
        """
        if not self.client:
            logger.error("ClickHouse не подключен")
            return []
        
        try:
            query = f"""
                SELECT 
                    page_id,
                    argMax(site_id, last_updated) as site,
                    argMax(dish_name, last_updated) as dish_name, 
                    argMax(description, last_updated) as description,
                    argMax(instructions, last_updated) as instructions,
                    argMax(ingredients, last_updated) as ingredients,
                    argMax(tags, last_updated) as tags,
                    argMax(cook_time, last_updated) as cook_time,
                    argMax(prep_time, last_updated) as prep_time,
                    argMax(total_time, last_updated) as total_time,
                    argMax(nutrition_info, last_updated) as nutrition_info,
                    argMax(category, last_updated) as category,
                    argMax(vectorised, last_updated) as vectorised
                FROM {table_name}
                WHERE site_id = %(site_id)s
                GROUP BY page_id
            """
            
            params = {'site_id': site_id}
            
            # Добавляем фильтр по vectorised через HAVING (после агрегации)
            if vectorised is not None:
                query += " HAVING vectorised = %(vectorised)s"
                params['vectorised'] = vectorised
            
            query += " ORDER BY page_id"
            
            # Добавляем лимит если указан
            if limit is not None:
                query += " LIMIT %(limit)s"
                params['limit'] = limit
            
            df = self.client.query_df(query, parameters=params)
            
            if len(df) == 0:
                logger.info(f"Рецепты не найдены для site_id={site_id}")
                return []
            
            recipes = self._parse_recipes_from_dataframe(df)
            
            vectorised_str = "все" if vectorised is None else ("векторизованные" if vectorised else "невекторизованные")
            logger.info(f"Получено {len(recipes)} {vectorised_str} рецептов для site_id={site_id}")
            
            return recipes
            
        except Exception as e:
            logger.error(f"Ошибка получения рецептов для site_id={site_id}: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_page_ids_by_site(self, site_id: int, table_name: str = "recipe_en") -> list[int]:
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

    def close(self):
        """Закрытие подключения"""
        if self.client:
            self.client.close()
            logger.info("Подключение к ClickHouse закрыто")
    