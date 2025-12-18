"""
Автоматический парсер рецептов через DuckDuckGo с Selenium
"""

import sys
import time
import logging
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse, urljoin
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.stages.parse.search_query_generator import SearchQueryGenerator
from src.stages.parse.explorer import SiteExplorer
from src.models.site import Site, SiteORM
from src.common.db.mysql import MySQlManager

logger = logging.getLogger(__name__)


class AutoScraper:
    """Автоматический сборщик рецептов через DuckDuckGo"""
    
    def __init__(self, headless: bool = False):
        """
        Инициализация скрапера
        
        Args:
            headless: Запускать браузер в фоновом режиме
        """
        self.headless = headless
        self.driver = None
        self.query_generator = SearchQueryGenerator()
        self.db = MySQlManager()
        if not self.db.connect():
            raise ConnectionError("Не удалось подключиться к базе данных")
    
    def _init_driver(self):
        """Инициализация Selenium WebDriver"""
        if self.driver:
            return
        
        logger.info("Инициализация Selenium WebDriver...")
        
        options = webdriver.ChromeOptions()
        
        if self.headless:
            options.add_argument('--headless')
        
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        self.driver = webdriver.Chrome(options=options)
        logger.info("✓ WebDriver инициализирован")
    
    def search_duckduckgo(self, query: str, max_results: int = 20) -> List[str]:
        """
        Поиск по DuckDuckGo и сбор ссылок
        
        Args:
            query: Поисковый запрос
            max_results: Максимальное количество результатов
        
        Returns:
            Список найденных URL
        """
        self._init_driver()
        
        logger.info(f"Поиск в DuckDuckGo: '{query}'")
        
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
                        except:
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
                    logger.warning(f"Ошибка при сборе ссылок: {e}")
                    break
            
            urls_list = list(urls)[:max_results]
            logger.info(f"✓ Собрано {len(urls_list)} уникальных URL")
            return urls_list
            
        except TimeoutException:
            logger.error("Timeout при загрузке DuckDuckGo")
            return []
        except Exception as e:
            logger.error(f"Ошибка поиска в DuckDuckGo: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def process_urls(self, urls: List[str], query_language: str, query_id: Optional[int] = None) -> tuple[int, int]:
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
        
        logger.info(f"Обработка {len(urls)} URL...")
        
        # Шаг 1: Создаём все сайты в БД и собираем мапу URL -> site_id
        logger.info(f"[1/3] Создание сайтов в БД...")
        url_to_site_id = {}
        session = self.db.get_session()
        
        for url in urls:
            try:
                # Извлекаем домен
                parsed = urlparse(url)
                domain = parsed.netloc
                
                if not domain:
                    continue
                
                # Убираем www.
                domain = domain.replace('www.', '')
                base_url = f"https://{domain}"
                
                # Проверяем существует ли сайт в БД
                existing_site = session.query(SiteORM).filter(SiteORM.base_url == base_url).first()
                
                if not existing_site:
                    # Создаем новый сайт
                    site = Site(
                        name=domain.replace('.', '_'),
                        base_url=base_url,
                        language=query_language,
                        is_recipe_site=False  # Пока неизвестно
                    )

                    site_orm = site.to_orm()
                    session.add(site_orm)
                    session.commit()
                    
                    site_id = site_orm.id
                    if not site_id:
                        logger.warning(f"Не удалось добавить сайт {domain}")
                        continue
                    
                    logger.info(f"✓ Создан новый сайт: {domain} (ID: {site_id})")
                else:
                    site_id = existing_site.id
                    logger.debug(f"Сайт {domain} уже существует (ID: {site_id})")
                
                url_to_site_id[url] = site_id
                
            except Exception as e:
                logger.error(f"Ошибка создания сайта для URL {url}: {e}")
                continue
        
        logger.info(f"✓ Подготовлено {len(url_to_site_id)} сайтов")
        
        # Шаг 2: Обновляем статистику в search_query
        if query_id:
            logger.info(f"[2/3] Обновление статистики для запроса ID={query_id}...")
            try:
                self.db.update_query_url_count(query_id, len(urls))
                logger.info(f"✓ Обновлено url_count={len(urls)} для запроса ID={query_id}")
            except Exception as e:
                logger.error(f"Ошибка обновления статистики запроса: {e}")
        
        # Шаг 3: Обрабатываем URL (проверяем страницы на рецепты)
        logger.info(f"[3/3] Проверка страниц на рецепты...")
        
        processed_count = 0
        recipe_count = 0
        
        for url, site_id in url_to_site_id.items():
            try:
                # Проверяем страницу
                page = self.explorer.check_page(url, site_id)
                
                if page and page.is_recipe:
                    recipe_count += 1
                    logger.info(f"✓ Найден рецепт: {url}")
                
                processed_count += 1
                
                # Небольшая задержка между запросами
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Ошибка обработки URL {url}: {e}")
                continue
        
        logger.info(f"✓ Обработано {processed_count} URL, найдено {recipe_count} рецептов")
        return processed_count, recipe_count
    
    def run_auto_scraping(
        self, 
        min_queries: int = 10,
        queries_to_process: int = 5,
        results_per_query: int = 20
    ):
        """
        Автоматический сбор рецептов
        
        Args:
            min_queries: Минимальное количество запросов в БД
            queries_to_process: Сколько запросов обработать за раз
            results_per_query: Сколько результатов собирать на запрос
        """
        logger.info("="*70)
        logger.info("Запуск автоматического сбора рецептов")
        logger.info("="*70)
        
        try:
            # 1. Проверяем и генерируем запросы если нужно
            logger.info("\n[1/3] Проверка и генерация поисковых запросов...")
            added = self.query_generator.generate_and_save_queries(
                min_queries=min_queries,
                queries_per_batch=5
            )
            
            if added > 0:
                logger.info(f"✓ Добавлено {added} новых запросов")
            
            # 2. Получаем неиспользованные запросы
            logger.info(f"\n[2/3] Получение неиспользованных запросов...")
            queries = self.query_generator.get_unsearched_queries(limit=queries_to_process)
            
            if not queries:
                logger.warning("Нет неиспользованных запросов")
                return
            
            logger.info(f"✓ Будет обработано {len(queries)} запросов")
            
            # 3. Обрабатываем каждый запрос
            logger.info(f"\n[3/3] Обработка запросов...")
            
            total_urls = 0
            total_recipes = 0
            
            for idx, (query_id, query_text, query_lang) in enumerate(queries, 1):
                logger.info(f"\n--- Запрос {idx}/{len(queries)} ---")
                logger.info(f"ID: {query_id}, Язык: {query_lang}")
                logger.info(f"Запрос: '{query_text}'")
                
                # Ищем в DuckDuckGo
                urls = self.search_duckduckgo(query_text, max_results=results_per_query)
                
                # Обрабатываем найденные URL (включая обновление url_count в search_query)
                processed, recipes = self.process_urls(urls, query_lang, query_id=query_id)
                
                total_urls += processed
                total_recipes += recipes
                
                # Помечаем запрос как использованный и обновляем recipe_url_count
                self.query_generator.mark_query_as_searched(
                    query_id=query_id,
                    url_count=len(urls),
                    recipe_url_count=recipes
                )
                
                logger.info(f"✓ Запрос обработан: {processed} URL, {recipes} рецептов")
                
                # Задержка между запросами
                time.sleep(3)
            
            # Итоги
            logger.info("\n" + "="*70)
            logger.info("ИТОГИ:")
            logger.info(f"  Обработано запросов: {len(queries)}")
            logger.info(f"  Найдено URL: {total_urls}")
            logger.info(f"  Найдено рецептов: {total_recipes}")
            logger.info("="*70)
            
        except Exception as e:
            logger.error(f"Ошибка при автоматическом сборе: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.close()
    
    def close(self):
        """Закрытие всех подключений"""
        if self.driver:
            self.driver.quit()
            logger.info("WebDriver закрыт")
        
        self.query_generator.close()
        self.explorer.close()


def main():
    """Главная функция"""
    import argparse
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    parser = argparse.ArgumentParser(description='Автоматический сбор рецептов через DuckDuckGo')
    parser.add_argument('--headless', action='store_true', help='Запустить браузер в фоновом режиме')
    parser.add_argument('--min-queries', type=int, default=10, help='Минимум запросов в БД')
    parser.add_argument('--queries-to-process', type=int, default=5, help='Сколько запросов обработать')
    parser.add_argument('--results-per-query', type=int, default=20, help='Результатов на запрос')
    
    args = parser.parse_args()
    
    scraper = AutoScraper(headless=args.headless)
    
    try:
        scraper.run_auto_scraping(
            min_queries=args.min_queries,
            queries_to_process=args.queries_to_process,
            results_per_query=args.results_per_query
        )
    except KeyboardInterrupt:
        logger.info("\n\nПрервано пользователем")
    finally:
        scraper.close()


if __name__ == '__main__':
    main()
