"""
Автоматический парсер рецептов через DuckDuckGo с Selenium
"""

import random
import sys
import time
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import config.config as config
from src.stages.parse.search_query_generator import SearchQueryGenerator
from src.models.site import Site, get_name_base_url_from_url
from src.repositories.site import SiteRepository
from src.repositories.search_query import SearchQueryRepository
from src.stages.parse.site_preparation_pipeline import SitePreparationPipeline
from pathlib import Path
from utils.languages import POPULAR_LANGUAGES

class AutoScraper:
    """Автоматический сборщик рецептов через DuckDuckGo"""
    
    def __init__(self, debug_mode: bool = True, debug_port: Optional[int] = None,
                 custom_logger: Optional[logging.Logger] = None):
        """
        Инициализация скрапера
        
        Args:
            debug_mode: Если True, подключается к открытому Chrome с отладкой
            debug_port: Порт для подключения к существующему Chrome (по умолчанию из config)
        """
        self.debug_mode = debug_mode
        self.debug_port = debug_port if debug_port is not None else config.CHROME_DEBUG_PORT
        self.driver = None
        self.site_repository = SiteRepository()
        self.search_query_repository = SearchQueryRepository()
        self.site_preparation_pipeline = SitePreparationPipeline(debug_port=debug_port) # все значения установлены как дефолтные
        if custom_logger:
            self.logger = custom_logger
        else:
            self.logger = logging.getLogger(__name__)

    def connect_to_chrome(self):
        """Подключение к Chrome в отладочном режиме"""
        if self.driver:
            return
        
        chrome_options = Options()
        
        if self.debug_mode:
            chrome_options.add_experimental_option(
                "debuggerAddress", 
                f"localhost:{self.debug_port}"
            )
            self.logger.info(f"Подключение к Chrome на порту {self.debug_port}")
        else:
            chrome_options.add_argument("--start-maximized")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            # Ротация User-Agent для меньшей детекции
            user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ]
            chrome_options.add_argument(f"user-agent={random.choice(user_agents)}")
        
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.implicitly_wait(config.IMPLICIT_WAIT)
            self.driver.set_page_load_timeout(config.PAGE_LOAD_TIMEOUT)
            self.logger.info("Успешное подключение к браузеру")
        except WebDriverException as e:
            self.logger.error(f"Ошибка подключения к браузеру: {e}")
            if self.debug_mode:
                self.logger.error(
                    f"\nЗапустите Chrome командой:\n"
                    f"google-chrome --remote-debugging-port={self.debug_port} "
                    f"--user-data-dir=./chrome_debug_{self.debug_port}\n"
                )
            raise
    
    def search_duckduckgo(self, query: str, max_results: int = 20) -> list[str]:
        """
        Поиск по DuckDuckGo и сбор ссылок
        
        Args:
            query: Поисковый запрос
            max_results: Максимальное количество результатов
        
        Returns:
            Список найденных URL
        """
        self.connect_to_chrome()
        
        self.logger.info(f"Поиск в DuckDuckGo: '{query}'")
        
        try:
            # Переходим на DuckDuckGo
            self.driver.get('https://duckduckgo.com/')
            time.sleep(2)
            
            # Находим поле поиска
            search_box = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.NAME, 'q'))
            )
            
            # Вводим запрос
            search_box.clear()
            search_box.send_keys(query)
            search_box.send_keys(Keys.RETURN)
            
            # Ждем загрузки результатов
            time.sleep(3)
            
            urls = set()
            scroll_pause = 2
            last_height = self.driver.execute_script("return document.body.scrollHeight")
            
            # Скроллим и собираем ссылки
            while len(urls) < max_results:
                # Находим все ссылки на результаты
                try:
                    # DuckDuckGo использует разные селекторы
                    result_links = self.driver.find_elements(By.CSS_SELECTOR, 'a[data-testid="result-title-a"]')
                    
                    if not result_links:
                        # Альтернативный селектор
                        result_links = self.driver.find_elements(By.CSS_SELECTOR, 'article a')
                    
                    for link in result_links:
                        try:
                            url = link.get_attribute('href')
                            if url and url.startswith('http'):
                                # Пропускаем внутренние ссылки DuckDuckGo
                                if 'duckduckgo.com' not in url:
                                    urls.add(url)
                                    
                                    if len(urls) >= max_results:
                                        break
                        except Exception:
                            continue
                    
                    # Скроллим вниз
                    self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(scroll_pause)
                    
                    # Проверяем новую высоту
                    new_height = self.driver.execute_script("return document.body.scrollHeight")
                    if new_height == last_height:
                        # Достигли конца страницы
                        break
                    last_height = new_height
                    
                except Exception as e:
                    self.logger.warning(f"Ошибка при сборе ссылок: {e}")
                    break
            
            urls_list = list(urls)[:max_results]
            self.logger.info(f"✓ Собрано {len(urls_list)} уникальных URL")
            return urls_list
            
        except TimeoutException:
            self.logger.error("Timeout при загрузке DuckDuckGo")
            return []
        except Exception as e:
            self.logger.error(f"Ошибка поиска в DuckDuckGo: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _create_sites_from_urls(self, urls: list[str], query_language: str) -> set:
        """
        Создать сайты в БД из списка URL
        
        Args:
            urls: Список URL
            query_language: Язык для новых сайтов
        
        Returns:
            Словарь {url: site_id}
        """
        self.logger.info(f"Создание сайтов из {len(urls)} URL...")
        saved_urls = set()

        for url in urls:
            try:
                # Извлекаем домен
                name, base_url = get_name_base_url_from_url(url)
                
                # Создаем модель сайта
                site = Site(
                    name=name,
                    search_url=url,
                    base_url=base_url,
                    language=query_language,
                    is_recipe_site=False
                )
                
                site_orm = self.site_repository.create_or_get(site)
                if site_orm.pattern is not None or site_orm.is_recipe_site:
                    self.logger.info(f"✓ Сайт уже существует и является сайтом с рецептом: {base_url} (ID={site_orm.id})")
                    continue  # Сайт уже существует
                saved_urls.add(url)
                
            except Exception as e:
                self.logger.error(f"Ошибка создания сайта для URL {url}: {e}")
                continue
        
        self.logger.info(f"✓ Подготовлено {len(saved_urls)} сайтов")
        return saved_urls
    
    def _check_pages_for_recipes(self, saved_urls: set) -> tuple[int, int]:
        """
        Проверить страницы на наличие рецептов
        
        Args:
            url_to_site_id: Словарь {url: site_id}
        
        Returns:
            (количество_обработанных, количество_рецептов)
        """
        self.logger.info(f"Проверка {len(saved_urls)} страниц на рецепты...")
        
        processed_count = 0
        recipe_count = 0
        
        for url in saved_urls:
            try:

                if self.site_preparation_pipeline.prepare_site(url, max_pages=60, driver=self.driver):
                    recipe_count += 1
                    
                processed_count += 1
                
            except Exception as e:
                self.logger.error(f"Ошибка обработки URL {url}: {e}")
                continue
        
        self.logger.info(f"✓ Обработано {processed_count} URL, найдено {recipe_count} рецептов")
        return processed_count, recipe_count
    
    def process_urls(self, urls: list[str], query_language: str, query_id: int) -> tuple[int, int]:
        """
        Обработка найденных URL (создание сайтов и проверка страниц)
        
        Args:
            urls: Список URL для обработки
            query_language: Язык поискового запроса
            query_id: ID поискового запроса для обновления статистики
        
        Returns:
            (количество_обработанных_url, количество_найденных_рецептов)
        """
        if not urls:
            return 0, 0
        
        self.logger.info(f"Обработка {len(urls)} URL...")
        
        # Шаг 1: Создаём все сайты в БД
        saved_urls = self._create_sites_from_urls(urls, query_language)
        
        # Шаг 2: Обновляем статистику в search_query
        self.search_query_repository.update_query_statistics(query_id, len(saved_urls), 0)
        
        # Шаг 3: Проверяем страницы на рецепты
        processed_count, recipe_count = self._check_pages_for_recipes(saved_urls)

        # Шаг 4: Обновляем статистику в search_query с учётом найденных рецептов
        self.search_query_repository.update_query_statistics(query_id, processed_count, recipe_count)
        
        return processed_count, recipe_count
    
    def run_auto_scraping(
        self, 
        min_queries: int = 10,
        queries_to_process: int = 5,
        results_per_query: int = 10,
        min_unprocessed_sites: int = 100,
        generate_from_recipes: bool = True,
        generate_with_gpt: bool = False,
    ):
        """
        Автоматический сбор рецептов
        
        Args:
            min_queries: Минимальное количество запросов в БД
            queries_to_process: Сколько запросов обработать за раз
            results_per_query: Сколько результатов собирать на запрос
            min_unprocessed_sites: Минимальное количество необработанных сайтов для запуска поиска новых
            generate_from_recipes: Генерировать запросы на основе существующих рецептов (для поиска используются рецепты из БД)
            generate_with_gpt: Генерировать запросы с помощью GPT
        """
        try:
            # 0. Проверяем количество необработанных сайтов
            self.logger.info("\n[0/4] Проверка количества необработанных сайтов...")
            unprocessed_count = self.site_repository.count_sites_without_pattern()
            
            self.logger.info(f"  Найдено необработанных сайтов (без паттерна): {unprocessed_count}")
            self.logger.info(f"  Минимум требуется: {min_unprocessed_sites}")
            
            if unprocessed_count >= min_unprocessed_sites:
                self.logger.info(f"\n{'='*70}")
                self.logger.info("✓ ДОСТАТОЧНО НЕОБРАБОТАННЫХ САЙТОВ")
                self.logger.info(f"  Необработанных сайтов: {unprocessed_count} >= {min_unprocessed_sites}")
                self.logger.info("  Поиск новых сайтов не требуется")
                self.logger.info(f"{'='*70}\n")
                
                # здесь проводим обработку уже имеющихся сайтов
                self.logger.info("Начинаем обработку необработанных сайтов...\n")
                sites = self.site_repository.get_unprocessed_sites(limit=min_unprocessed_sites, random_order=True) # получаем случайные необработанные сайты
                for site in sites:
                    try:
                        self.logger.info(f"\n=== Обработка сайта ID={site.id}, URL={site.base_url} ===")
                        if self.site_preparation_pipeline.prepare_site(site.search_url, max_pages=60, custom_logger=self.logger):
                            self.logger.info(f"✓ Сайт ID={site.id} обработан и содержит рецепты")
                        else:
                            self.logger.info(f"→ Сайт ID={site.id} обработан, но рецепты не найдены")
                    except Exception as e:
                        self.logger.error(f"Ошибка обработки сайта ID={site.id}, URL={site.base_url}: {e}")
                        continue
                return
            
            self.logger.info(f"→ Недостаточно необработанных сайтов ({unprocessed_count} < {min_unprocessed_sites})")
            self.logger.info("→ Начинаем поиск новых сайтов через DuckDuckGo...\n")
            
            generator = SearchQueryGenerator(max_non_searched=10, query_repository=self.search_query_repository)
            # 1. Проверяем и генерируем запросы если нужно
            self.logger.info("\n[1/4] Проверка и генерация поисковых запросов...")
            if self.search_query_repository.get_unsearched_count() < min_queries:
                # генерируем новые запросы, елси остлоьс меньше минимального
                
                if generate_with_gpt:
                    new_queries = generator.generate_search_queries(count=10) # запросы генерирует chatGPT
                elif generate_from_recipes:
                    new_queries = generator.get_queries_from_existing_recipes(count=10)
                    if not new_queries:
                        self.logger.warning("Не удалось сгенерировать запросы на основе существующих рецептов, пробуем GPT...")
                        new_queries = generator.generate_search_queries(count=10)
                else:
                    self.logger.warning("Нет способа сгенерировать новые запросы (generate_from_recipes и generate_with_gpt отключены)")
                    new_queries = []

                query_results = {}
                for query in new_queries:
                    translated = generator.translate_query(query=query, target_languages=random.sample(POPULAR_LANGUAGES, k=5))
                    query_results[query] = translated
                
                generator.save_queries_to_db(query_results)
                self.logger.info(f"Сгенерировано {len(new_queries)} новых поисковых запросов:")
            
            # 2. Получаем неиспользованные запросы
            self.logger.info("\n[2/4] Получение неиспользованных запросов...")
            search_queries = self.search_query_repository.get_unsearched_queries(limit=queries_to_process)
            queries = [q.to_pydantic() for q in search_queries]
            
            if not queries:
                self.logger.warning("Нет неиспользованных запросов")
                return
            
            self.logger.info(f"✓ Будет обработано {len(queries)} запросов")
            
            # 3. Обрабатываем каждый запрос
            self.logger.info("\n[3/4] Поиск в DuckDuckGo...")
            
            total_urls = 0
            total_recipes = 0
            
            for idx, query in enumerate(queries, 1):
                self.logger.info(f"\n--- Запрос {idx}/{len(queries)} ---")
                self.logger.info(f"ID: {query.id}, Язык: {query.language}")
                self.logger.info(f"Запрос: '{query.query}'")
                
                # Ищем в DuckDuckGo
                urls = self.search_duckduckgo(query.query, max_results=results_per_query)
                
                # Обрабатываем найденные URL (включая обновление url_count в search_query)
                processed, recipes = self.process_urls(urls, query_language=query.language, query_id=query.id)

                total_urls += processed
                total_recipes += recipes
                self.logger.info(f"✓ Запрос обработан: {processed} URL, {recipes} рецептов")
                
                # Задержка между запросами
                time.sleep(3)
            
            # 4. Проверяем итоговое количество необработанных сайтов
            self.logger.info("\n[4/4] Проверка итогов...")
            final_unprocessed_count = self.site_repository.count_sites_without_pattern()
            
            # Итоги
            self.logger.info("\n" + "="*70)
            self.logger.info("ИТОГИ ПОИСКА:")
            self.logger.info(f"  Обработано запросов: {len(queries)}")
            self.logger.info(f"  Найдено URL: {total_urls}")
            self.logger.info(f"  Найдено рецептов: {total_recipes}")
            self.logger.info(f"  Необработанных сайтов до: {unprocessed_count}")
            self.logger.info(f"  Необработанных сайтов после: {final_unprocessed_count}")
            self.logger.info(f"  Добавлено новых: {final_unprocessed_count - unprocessed_count}")
            self.logger.info("="*70)
            
        except Exception as e:
            self.logger.error(f"Ошибка при автоматическом сборе: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.close()


    def close(self):
        """Закрытие всех подключений"""
        if self.driver and not self.debug_mode:
            self.driver.quit()
            self.logger.info("WebDriver закрыт")
