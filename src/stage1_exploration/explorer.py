"""
Скрипт для исследования структуры сайта и сбора уникальных ссылок
"""
import os
import sys
import time
import json
import re
import random
from pathlib import Path
from urllib.parse import urlparse, urljoin
from typing import Set, Dict, List
import logging

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException
from bs4 import BeautifulSoup

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import config.config as config
from src.common.database import DatabaseManager

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SiteExplorer:
    """Исследователь структуры сайта"""
    
    def __init__(self, base_url: str, debug_mode: bool = True, use_db: bool = True, recipe_pattern: str = None):
        """
        Args:
            base_url: Базовый URL сайта
            debug_mode: Если True, подключается к открытому Chrome с отладкой
            use_db: Если True, сохраняет данные в MySQL
            recipe_pattern: Regex паттерн для поиска URL с рецептами (опционально)
        """
        self.base_url = base_url
        self.debug_mode = debug_mode
        self.use_db = use_db
        self.driver = None
        self.db = None
        self.site_id = None
        self.recipe_pattern = recipe_pattern
        self.recipe_regex = None
        
        # Компиляция regex паттерна если передан
        if recipe_pattern:
            try:
                self.recipe_regex = re.compile(recipe_pattern)
                logger.info(f"Используется regex паттерн для рецептов: {recipe_pattern}")
            except re.error as e:
                logger.error(f"Неверный regex паттерн: {e}")
                self.recipe_regex = None
        
        parsed_url = urlparse(base_url)
        self.base_domain = parsed_url.netloc.replace('www.', '')
        self.site_name = self.base_domain.replace('.', '_')
        
        # Множества для отслеживания
        self.visited_urls: Set[str] = set()
        self.url_patterns: Dict[str, List[str]] = {}  # паттерн -> список URL
        self.failed_urls: Set[str] = set()
        self.referrer_map: Dict[str, str] = {}  # URL -> referrer URL (откуда пришли)
        self.successful_referrers: Set[str] = set()  # URLs страниц, которые привели к рецептам
        
        # Файлы для сохранения
        self.save_dir = os.path.join(config.PARSED_DIR, self.site_name,"exploration")
        os.makedirs(self.save_dir, exist_ok=True)
        
        self.state_file = os.path.join(self.save_dir, "exploration_state.json")
        self.patterns_file = os.path.join(self.save_dir, "url_patterns.json")
        
        # Подключение к БД
        if self.use_db:
            self.db = DatabaseManager()
            if self.db.connect():
                self.site_id = self.db.create_or_get_site(
                    name=self.site_name,
                    base_url=base_url,
                    language=None  # Будет определен при парсинге
                )
                if self.site_id:
                    logger.info(f"Работа с сайтом ID: {self.site_id}")
                else:
                    logger.warning("Не удалось создать/получить ID сайта")
                    self.use_db = False
            else:
                logger.warning("Не удалось подключиться к БД, продолжаем без БД")
                self.use_db = False
    
    def connect_to_chrome(self):
        """Подключение к Chrome в отладочном режиме"""
        chrome_options = Options()
        
        if self.debug_mode:
            chrome_options.add_experimental_option(
                "debuggerAddress", 
                f"localhost:{config.CHROME_DEBUG_PORT}"
            )
            logger.info(f"Подключение к Chrome на порту {config.CHROME_DEBUG_PORT}")
        else:
            chrome_options.add_argument("--start-maximized")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.implicitly_wait(config.IMPLICIT_WAIT)
            self.driver.set_page_load_timeout(config.PAGE_LOAD_TIMEOUT)
            logger.info("Успешное подключение к браузеру")
        except WebDriverException as e:
            logger.error(f"Ошибка подключения к браузеру: {e}")
            if self.debug_mode:
                logger.error(
                    f"\nЗапустите Chrome командой:\n"
                    f"google-chrome --remote-debugging-port={config.CHROME_DEBUG_PORT} "
                    f"--user-data-dir=./chrome_debug\n"
                )
            raise
    
    def get_url_pattern(self, url: str) -> str:
        """
        Получение паттерна URL для группировки похожих ссылок
        
        Args:
            url: URL для анализа
            
        Returns:
            Паттерн URL (числа заменены на #, id заменены на {id})
        """
        parsed = urlparse(url)
        path = parsed.path
        
        # Замена чисел на #
        pattern = re.sub(r'\d+', '#', path)
        
        # Замена длинных идентификаторов на {id}
        pattern = re.sub(r'[a-f0-9]{8,}', '{id}', pattern, flags=re.IGNORECASE)
        
        # Удаление trailing slash для унификации
        pattern = pattern.rstrip('/')
        
        return pattern or '/'
    
    def is_same_domain(self, url: str) -> bool:
        """Проверка, принадлежит ли URL тому же домену"""
        try:
            domain = urlparse(url).netloc.replace('www.', '')
            return domain == self.base_domain
        except Exception:
            return False
    
    def is_recipe_url(self, url: str) -> bool:
        """
        Проверка, соответствует ли URL паттерну рецепта
        
        Args:
            url: URL для проверки
            
        Returns:
            True если URL соответствует паттерну рецепта
        """
        if not self.recipe_regex:
            return False
        
        try:
            parsed = urlparse(url)
            path = parsed.path
            return len(re.findall(self.recipe_pattern, path)) > 0
        except Exception as e:
            logger.debug(f"Ошибка проверки URL {url}: {e}")
            return False
    
    def should_explore_url(self, url: str, pattern: str) -> bool:
        """
        Проверка, нужно ли исследовать данный URL
        
        Args:
            url: URL для проверки
            pattern: Паттерн URL
            
        Returns:
            True если URL нужно посетить
        """
        # Пропускаем если уже посещали
        if url in self.visited_urls:
            return False
        
        # Пропускаем файлы
        if re.search(r'\.(jpg|jpeg|png|gif|pdf|zip|mp4|avi|css|js)$', url, re.IGNORECASE):
            return False
        
        # Пропускаем служебные страницы
        skip_patterns = [
            r'/login',
            r'/register',
            r'/signup',
            r'/signin',
            r'/auth',
            r'/account',
            r'/profile',
            r'/settings',
            r'/about',
            r'/contact',
            r'/privacy',
            r'/terms',
            r'/cookie',
            r'/newsletter',
            r'/subscribe',
            r'/unsubscribe',
            r'/cart',
            r'/checkout',
            r'/order',
            r'/search',
            r'/feedback',
            r'/help',
            r'/support',
            r'/faq',
            r'/advertise',
            r'/careers',
            r'/jobs',
        ]
        
        parsed = urlparse(url)
        path_lower = parsed.path.lower()
        
        for skip_pattern in skip_patterns:
            if re.search(skip_pattern, path_lower):
                logger.debug(f"Пропуск служебной страницы: {url}")
                return False
        
        # Ограничиваем количество URL одного паттерна для разнообразия
        if pattern in self.url_patterns and len(self.url_patterns[pattern]) >= 2:  # Максимум 2 URL одного типа
                return False
        
        return True
    
    def get_url_priority(self, url: str) -> int:
        """
        Определение приоритета URL для обхода
        TODO поудмать над логикой как-то тут не прям супер
        Args:
            url: URL для оценки
            
        Returns:
            Приоритет (меньше = выше приоритет)
        """
        # Приоритет 0 (наивысший): URL с паттерном рецепта
        if self.is_recipe_url(url):
            return 0
        
        # Приоритет 1: URL со страниц, которые привели к рецептам
        referrer = self.referrer_map.get(url)
        if referrer and referrer in self.successful_referrers:
            return 1
        
        # Приоритет 2: остальные URL
        return 2
    
    def slow_scroll_page(self):
        """Медленная прокрутка страницы для загрузки всего контента"""
        try:
            total_height = self.driver.execute_script("return document.body.scrollHeight")
            num_scrolls = random.randint(4, 7)
            scroll_step = total_height // num_scrolls
            
            current_position = 0
            for i in range(num_scrolls):
                current_position += scroll_step
                self.driver.execute_script(f"window.scrollTo(0, {current_position});")
                pause = random.uniform(0.8, 1.5)
                logger.debug(f"Прокрутка {i+1}/{num_scrolls}, пауза {pause:.1f}с")
                time.sleep(pause)
            
            # Прокрутка в конец
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(random.uniform(1.0, 2.0))
            
            # Возврат наверх
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(random.uniform(0.5, 1.0))
            
        except Exception as e:
            logger.debug(f"Ошибка при прокрутке: {e}")
    
    def save_page_html(self, url: str, pattern: str, page_index: int):
        """
        Сохранение HTML страницы и информации в БД
        
        Args:
            url: URL страницы
            pattern: Паттерн URL
            page_index: Индекс страницы в рамках паттерна
        """
        try:
            # Получение HTML
            html_content = self.driver.page_source
            
            # Создание имени файла из паттерна
            safe_pattern = pattern.replace('/', '_').replace('#', 'N').replace('{', '').replace('}', '').strip('_')
            if not safe_pattern:
                safe_pattern = 'index'
            
            filename = f"{safe_pattern}_{page_index}.html"
            filepath = os.path.join(self.save_dir,filename)
            
            # Сохранение HTML
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            # Получение метаданных
            title = self.driver.title
            language = self.driver.execute_script("return document.documentElement.lang") or 'unknown'
            
            # Сохранение метаданных в JSON
            metadata = {
                'url': url,
                'title': title,
                'language': language,
                'saved_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            
            metadata_file = os.path.join(self.save_dir, f"{safe_pattern}_{page_index}_metadata.json")
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            
            # Сохранение в БД
            if self.use_db and self.site_id:
                page_id = self.db.save_page(
                    site_id=self.site_id,
                    url=url,
                    pattern=pattern,
                    title=title,
                    language=language,
                    html_path=os.path.relpath(filepath),
                    metadata_path=os.path.relpath(metadata_file)
                )
                if page_id:
                    logger.info(f"  ✓ Сохранено: {filename} (DB ID: {page_id})")
                else:
                    logger.info(f"  ✓ Сохранено: {filename} (БД: ошибка)")
            else:
                logger.info(f"  ✓ Сохранено: {filename}")
            
        except Exception as e:
            logger.error(f"Ошибка сохранения страницы: {e}")
    
    def extract_links(self) -> List[str]:
        """Извлечение всех ссылок со страницы"""
        try:
            soup = BeautifulSoup(self.driver.page_source, 'lxml')
            links = []
            
            for link in soup.find_all('a', href=True):
                href = link['href']
                absolute_url = urljoin(self.driver.current_url, href)
                
                # Очистка от якорей и параметров
                clean_url = absolute_url.split('#')[0].split('?')[0]
                
                if clean_url and self.is_same_domain(clean_url):
                    links.append(clean_url)
            
            return list(set(links))  # Уникальные ссылки
            
        except Exception as e:
            logger.error(f"Ошибка извлечения ссылок: {e}")
            return []
    
    def save_state(self):
        """Сохранение текущего состояния исследования"""
        state = {
            'base_url': self.base_url,
            'visited_urls': list(self.visited_urls),
            'failed_urls': list(self.failed_urls),
            'referrer_map': self.referrer_map,
            'successful_referrers': list(self.successful_referrers),
            'total_visited': len(self.visited_urls),
            'total_failed': len(self.failed_urls),
            'total_successful_referrers': len(self.successful_referrers),
            'last_updated': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        
        # Сохранение паттернов
        patterns_data = {
            'patterns': {pattern: urls for pattern, urls in self.url_patterns.items()},
            'total_patterns': len(self.url_patterns),
            'total_unique_urls': sum(len(urls) for urls in self.url_patterns.values())
        }
        
        with open(self.patterns_file, 'w', encoding='utf-8') as f:
            json.dump(patterns_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Состояние сохранено: {len(self.visited_urls)} посещено, {len(self.url_patterns)} паттернов")
    
    def load_state(self) -> bool:
        """Загрузка сохраненного состояния"""
        if not os.path.exists(self.state_file):
            logger.info("Файл состояния не найден, начинаем с нуля")
            return False
        
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            
            self.visited_urls = set(state.get('visited_urls', []))
            self.failed_urls = set(state.get('failed_urls', []))
            self.referrer_map = state.get('referrer_map', {})
            self.successful_referrers = set(state.get('successful_referrers', []))
            
            if os.path.exists(self.patterns_file):
                with open(self.patterns_file, 'r', encoding='utf-8') as f:
                    patterns_data = json.load(f)
                    self.url_patterns = {k: v for k, v in patterns_data.get('patterns', {}).items()}
            
            logger.info("Загружено состояние:")
            logger.info(f"  Посещено URL: {len(self.visited_urls)}")
            logger.info(f"  Найдено паттернов: {len(self.url_patterns)}")
            logger.info(f"  Успешных источников: {len(self.successful_referrers)}")
            logger.info(f"  Ошибок: {len(self.failed_urls)}")
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка загрузки состояния: {e}")
            return False
    
    def explore(self, max_urls: int = 100, max_depth: int = 3):
        """
        Исследование структуры сайта
        
        Args:
            max_urls: Максимальное количество URL для посещения
            max_depth: Максимальная глубина обхода
        """
        logger.info(f"Начало исследования сайта: {self.base_url}")
        logger.info(f"Цель: найти до {max_urls} уникальных паттернов URL")
        
        # Загрузка сохраненного состояния
        #self.load_state()
        
        # Очередь URL для обхода: (url, depth)
        queue = [(self.base_url, 0)]
        urls_explored = len(self.visited_urls)
        
        while queue and urls_explored < max_urls:
            current_url, depth = queue.pop(0)
            
            # Проверка глубины
            if depth > max_depth:
                continue
            
            # Получение паттерна
            pattern = self.get_url_pattern(current_url)
            
            # Проверка, нужно ли посещать
            if not self.should_explore_url(current_url, pattern):
                continue
            
            try:
                logger.info(f"[{urls_explored + 1}/{max_urls}] Переход на: {current_url}")
                logger.info(f"  Паттерн: {pattern}, Глубина: {depth}")
                
                # Переход на страницу
                try:
                    self.driver.get(current_url)
                except TimeoutException:
                    logger.warning(f"Timeout при загрузке {current_url}")
                
                # Ожидание загрузки
                try:
                    WebDriverWait(self.driver, 40).until(
                        lambda d: d.execute_script('return document.readyState') == 'complete'
                    )
                except TimeoutException:
                    logger.warning("Timeout при загрузке страницы")
                
                # Задержка
                delay = 3 + random.uniform(1, 3)
                time.sleep(delay)
                
                # Прокрутка для загрузки контента
                self.slow_scroll_page()
                
                # Добавление в посещенные
                self.visited_urls.add(current_url)
                urls_explored += 1
                
                # Добавление в паттерн
                if pattern not in self.url_patterns:
                    self.url_patterns[pattern] = []
                
                page_index = len(self.url_patterns[pattern]) + 1
                self.url_patterns[pattern].append(current_url)
                
                # Сохранение HTML страницы

                # Если задан regex паттерн - сохраняем рецепт в противном случае сохраняем все страницы
                if (self.recipe_regex and self.is_recipe_url(current_url)) or self.recipe_regex is None:
                    if self.recipe_regex:
                        logger.info("  ✓ URL соответствует паттерну рецепта")
                        # Отмечаем источник как успешный
                        referrer = self.referrer_map.get(current_url)
                        if referrer:
                            self.successful_referrers.add(referrer)
                            logger.info(f"  ✓ Источник отмечен как успешный: {referrer}")

                    self.save_page_html(current_url, pattern, page_index)
                
                
                # Извлечение новых ссылок
                new_links = self.extract_links()
                logger.info(f"  Найдено ссылок: {len(new_links)}")
                
                # Добавление новых ссылок в очередь с отслеживанием источника
                for link in new_links:
                    link_pattern = self.get_url_pattern(link)
                    if self.should_explore_url(link, link_pattern):
                        # Запоминаем источник перехода
                        if link not in self.referrer_map:
                            self.referrer_map[link] = current_url
                        queue.append((link, depth + 1))
                
                # Сортируем очередь по приоритету
                queue.sort(key=lambda x: self.get_url_priority(x[0]))
                
                # Периодическое сохранение
                #if urls_explored % 10 == 0:
                #    self.save_state()
                
            except Exception as e:
                logger.error(f"Ошибка при обработке {current_url}: {e}")
                self.failed_urls.add(current_url)
                #self.save_state()  # Сохранение при ошибке
                continue
        
        # Финальное сохранение
        #self.save_state()
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Результаты сохранены в: {self.save_dir}")
        logger.info(f"  - {self.state_file} - состояние")
        logger.info(f"  - {self.patterns_file} - найденные паттерны")
        logger.info(f"  - *.html - сохраненные страницы ({sum(len(urls) for urls in self.url_patterns.values())} файлов)")
        logger.info(f"{'='*60}")

    
    def close(self):
        """Закрытие браузера и БД"""
        if self.driver and not self.debug_mode:
            self.driver.quit()
        if self.db:
            self.db.close()
        logger.info("Готово")


def main():
    url = "https://www.allrecipes.com/"
    # паттерн формируется после анализа несколкьих URL
    search_pattern = "(^/recipe/\d+/[a-z0-9-]+/?$)|(^/[a-z0-9-]+-recipe-\d+/?$)"
    max_urls = 130
    max_depth = 3
    
    explorer = SiteExplorer(url, debug_mode=True, use_db=True, recipe_pattern=search_pattern)
    
    try:
        #isR = explorer.is_recipe_url("https://www.allrecipes.com/recipe/23439/perfect-pumpkin-pie/")
        explorer.connect_to_chrome()
        explorer.explore(max_urls=max_urls, max_depth=max_depth)
    except KeyboardInterrupt:
        logger.info("\nПрервано пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        sys.exit(1)
    finally:
        explorer.close()


if __name__ == "__main__":
    main()
