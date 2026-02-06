"""
Конфигурация парсеров и остальных скриптов
"""
import os
from typing import Optional
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

class Config:
    """Централизованная конфигурация приложения из переменных окружения"""
    
    # MySQL настройки
    MYSQL_HOST: str = os.getenv('MYSQL_HOST', 'localhost')
    MYSQL_PORT: int = int(os.getenv('MYSQL_PORT', '3306'))
    MYSQL_USER: str = os.getenv('MYSQL_USER', 'root')
    MYSQL_PASSWORD: str = os.getenv('MYSQL_PASSWORD', '')
    MYSQL_DATABASE: str = os.getenv('MYSQL_DATABASE', 'recipe_parser')
    
    # OpenAI настройки
    GPT_API_KEY: str = os.getenv('GPT_API_KEY', '')
    GPT_MODEL_MINI: str = os.getenv('GPT_MODEL_MINI', 'gpt-4o-mini')
    GPT_MODEL_MERGE: str = os.getenv('GPT_MODEL_MERGE', 'gpt-4o-mini')
    GPT_MODEL_TRANSLATE: str = os.getenv('GPT_MODEL_TRANSLATE', 'gpt-3.5-turbo')
    PROXY: Optional[str] = os.getenv('PROXY')
    SOCKS5: Optional[str] = os.getenv('SOCKS5')
    
    # ClickHouse настройки
    CLICKHOUSE_HOST: str = os.getenv('CLICKHOUSE_HOST', 'localhost')
    CLICKHOUSE_PORT: int = int(os.getenv('CLICKHOUSE_PORT', '9000'))
    CLICKHOUSE_USER: str = os.getenv('CLICKHOUSE_USER', 'default')
    CLICKHOUSE_DATABASE: str = os.getenv('CLICKHOUSE_DATABASE', 'recipe_parser')
    CLICKHOUSE_PASSWORD: str = os.getenv('CLICKHOUSE_PASSWORD', '')
    CLICKHOUSE_SECURE: bool = os.getenv('CLICKHOUSE_SECURE', '0') == '1'
    CLICKHOUSE_RECIPE_TABLE: str = os.getenv('CLICKHOUSE_RECIPE_TABLE', 'recipe_en')
    CLICKHOUSE_SCHEMA: str = os.getenv('CLICKHOUSE_SCHEMA', 'db/schemas/clickhouse.sql')
    # Qdrant настройки
    QDRANT_HOST: str = os.getenv('QDRANT_HOST', 'localhost')
    QDRANT_PORT: int = int(os.getenv('QDRANT_PORT', '6333'))
    QDRANT_API_KEY: Optional[str] = os.getenv('QDRANT_API_KEY', None)
    QDRANT_HTTPS: bool = int(os.getenv('QDRANT_HTTPS', '0').lower()) == 1
    
    # Qdrant коллекции
    QDRANT_FULL_COLLECTION: str = os.getenv('QDRANT_FULL_COLLECTION', 'full')
    QDRANT_MV_COLLECTION: str = os.getenv('QDRANT_MV_COLLECTION', 'mv')
    QDRANT_IMAGES_COLLECTION: str = os.getenv('QDRANT_IMAGES_COLLECTION', 'images_1152')
    
    # GitHub настройки
    GITHUB_TOKEN: str = os.getenv('GITHUB_TOKEN', '')
    GITHUB_REPO_OWNER: str = os.getenv('GITHUB_REPO_OWNER', '')
    GITHUB_REPO_NAME: str = os.getenv('GITHUB_REPO_NAME', '')
    
    # Настройки векторизации
    TARGET_LANGUAGE: str = os.getenv('TARGET_LANGUAGE', 'en')
    VECTORIZE_BATCH_SIZE: int = int(os.getenv('VECTORIZE_BATCH_SIZE', '15'))
    VECTORIZE_BATCH_SIZE_IMAGES: int = int(os.getenv('VECTORIZE_BATCH_SIZE_IMAGES', '16'))
    TRANSLATE_BATCH_SIZE: int = int(os.getenv('TRANSLATE_BATCH_SIZE', '20'))
    TRANSLATE_MAX_RETRIES: int = int(os.getenv('TRANSLATE_MAX_RETRIES', '5'))
    IMAGE_DOWNLOAD_DIR: str = os.getenv('IMAGE_DOWNLOAD_DIR', 'images')
    
    # Настройки слияния рецептов
    MERGE_SIMILARITY_THRESHOLD: float = float(os.getenv('MERGE_SIMILARITY_THRESHOLD', '0.85'))
    MERGE_BATCH_SIZE: int = int(os.getenv('MERGE_BATCH_SIZE', '10'))
    MERGE_MAX_RETRIES: int = int(os.getenv('MERGE_MAX_RETRIES', '5'))
    MERGE_MAX_MERGE_RECIPES: int = int(os.getenv('MERGE_MAX_MERGE_RECIPES', '3'))
    MERGE_BUILD_TYPE: str = os.getenv('MERGE_BUILD_TYPE', 'full')
    MERGE_MAX_VARIATIONS: int = int(os.getenv('MERGE_MAX_VARIATIONS', '5'))
    MERGE_VALIDATE_GPT: bool = int(os.getenv('MERGE_VALIDATE_GPT', '1').lower()) == 1
    MERGE_SAVE_TO_DB: bool = int(os.getenv('MERGE_SAVE_TO_DB', '1').lower()) == 1
    MERGE_HISTORY_FOLDER: str = os.getenv('MERGE_HISTORY_FOLDER', 'history')
    
    # Настройки кластеризации по схожести
    SIMILARITY_SCROLL_BATCH_SIZE: int = int(os.getenv('SIMILARITY_SCROLL_BATCH_SIZE', '1000'))
    SIMILARITY_QUERY_BATCH_SIZE: int = int(os.getenv('SIMILARITY_QUERY_BATCH_SIZE', '128'))
    SIMILARITY_LIMIT: int = int(os.getenv('SIMILARITY_LIMIT', '30'))
    SIMILARITY_TOP_K: int = int(os.getenv('SIMILARITY_TOP_K', '5'))

    # настройки парсера
    PARSER_DIR: str = os.getenv('PARSER_DIR', 'parsed')
    PARSER_PREPROCESSED_FOLDER: str = os.getenv('PARSER_PREPROCESSED_FOLDER', 'preprocessed')
    PARSER_DEFAULT_CHROME_PORT: int = int(os.getenv('PARSER_DEFAULT_CHROME_PORT', '9222'))
    PARSER_DEFAULT_MAX_PAGES_PER_SITE: int = int(os.getenv('PARSER_DEFAULT_MAX_PAGES_PER_SITE', '300'))
    PARSER_DEFAULT_CRAWL_DEPTH: int = int(os.getenv('PARSER_DEFAULT_CRAWL_DEPTH', '4'))
    PARSER_DEFAULT_IMPLICIT_WAIT: int = int(os.getenv('PARSER_DEFAULT_IMPLICIT_WAIT', '10'))
    PARSER_DEFAULT_PAGE_LOAD_TIMEOUT: int = int(os.getenv('PARSER_DEFAULT_PAGE_LOAD_TIMEOUT', '30'))
    PARSER_PROXY: Optional[str] = os.getenv('PARSER_PROXY', None)
    
# единый экземпляр конфигурации
config = Config()
