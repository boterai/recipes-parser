"""
Скрипт для исследования структуры сайта и сбора уникальных ссылок
"""
import os
import sys
import time
import json
import re
import random
import socket
import threading
from pathlib import Path
from urllib.parse import urlparse, urljoin
from typing import Set, Dict, List, Optional
import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException
from bs4 import BeautifulSoup

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.config import config
from src.stages.extract.recipe_extractor import RecipeExtractor
from src.stages.analyse.analyse import RecipeAnalyzer
from src.repositories.site import SiteRepository
from src.repositories.page import PageRepository
from src.models.site import Site
from src.models.page import Page
# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SiteExplorer:
    """Исследователь структуры сайта с поддержкой многоязычных рецептов"""
    
    def __init__(self, base_url: str, debug_mode: bool = True, recipe_pattern: str = None,
                 max_errors: int = 3, max_urls_per_pattern: int = None, debug_port: int = None,
                 driver: webdriver.Chrome = None, custom_logger: logging.Logger = None, 
                 max_no_recipe_pages: Optional[int] = None, proxy: str = None):
        """
        Args:
            base_url: Базовый URL сайта
            debug_mode: Если True, подключается к открытому Chrome с отладкой
            recipe_pattern: Regex паттерн для поиска URL с рецептами (опционально)
            max_errors: Максимальное количество ошибок подряд перед остановкой
            max_urls_per_pattern: Максимальное количество URL на один паттерн (None = без ограничений)
            debug_port: Порт для подключения к Chrome (по умолчанию из config)
            driver: Переданный экземпляр webdriver.Chrome (если None, создается новый)
            custom_logger: Пользовательский логгер (если None, используется стандартный)
            max_no_recipe_pages: Максимальное количество страниц без рецепта подряд (None = без ограничений). Если указано прерывает исследвоание сайта при достижении лимита
            proxy: Прокси сервер (формат: host:port или http://host:port). Если None, берется из config.PROXY
        """
        self.debug_mode = debug_mode
        self.debug_port = debug_port if debug_port is not None else config.PARSER_DEFAULT_CHROME_PORT
        self.proxy = proxy or config.PARSER_PROXY  # Берем из параметра или из конфига
        self.driver = driver
        self.recipe_regex = None
        self.request_count = 0  # Счетчик запросов для адаптивных пауз
        self.max_errors = max_errors
        self.max_urls_per_pattern = max_urls_per_pattern  # Лимит URL на паттерн (рекомендуется использовать для первоначальной сборки рецептовв, чтобы не собирать кучи одинаковых страниц)
        self.analyzer = None
        self.site_repository = SiteRepository()
        self.page_repository = PageRepository()
        self.site = Site(
            base_url=base_url,
            pattern=recipe_pattern,
            name="",
        )
        if custom_logger:
            self.logger = custom_logger
        else:
            self.logger = logger
        self.site.set_url(base_url)
        
        # Компиляция regex паттерна если передан
        if self.site.pattern:
            try:
                self.recipe_regex = re.compile(self.site.pattern)
                self.logger.info(f"Используется regex паттерн для рецептов: {self.site.pattern}")
            except re.error as e:
                self.logger.error(f"Неверный regex паттерн: {e}")
                self.recipe_regex = None
        
        parsed_url = urlparse(base_url)
        self.base_domain = parsed_url.netloc.replace('www.', '')
        
        # Множества для отслеживания
        self.visited_urls: Set[str] = set()
        self.url_patterns: Dict[str, List[str]] = {}  # паттерн -> список URL
        self.failed_urls: Set[str] = set()
        self.referrer_map: Dict[str, str] = {}  # URL -> referrer URL (откуда пришли)
        self.successful_referrers: Set[str] = set()  # URLs страниц, которые привели к рецептам
        self.exploration_queue: List[tuple] = []  # Очередь URL для исследования: [(url, depth), ...]
        
        # Файлы для сохранения
        self.save_dir = os.path.join(config.PARSER_DIR, self.site.name,"exploration")
        os.makedirs(self.save_dir, exist_ok=True)
        
        self.state_file = os.path.join(self.save_dir, "exploration_state.json")
        self.patterns_file = os.path.join(self.save_dir, "url_patterns.json")

        site_orm = self.site_repository.create_or_get(self.site) # надо оставить только site а остальные все убрать тип поля из сайта которые 
        self.site = site_orm.to_pydantic()
        
        # Загружаем посещенные URL из БД
        self.load_visited_urls_from_db()

        # Инициализация экстрактора для проверки и извлечения рецептов
        self.recipe_extractor = RecipeExtractor()
        self.max_no_recipe_pages: Optional[int] = max_no_recipe_pages 
        self.no_recipe_page_count: int = 0  # Счетчик страниц без рецепта подряд

    def set_pattern(self, pattern: str):
        self.site.pattern = pattern
        try:
            self.recipe_regex = re.compile(pattern)
            self.logger.info(f"Используется regex паттерн для рецептов: {pattern}")
        except re.error as e:
            self.logger.error(f"Неверный regex паттерн: {e}")
            self.recipe_regex = None
    
    
    def load_visited_urls_from_db(self):
        """
        Загрузка всех уже посещенных URL для данного сайта из БД
        """
        pages_orm = self.page_repository.get_by_site(site_id=self.site.id)
        
        loaded_count = 0
        for page in pages_orm:
            if page.url:
                self.visited_urls.add(page.url)
                loaded_count += 1
                
                if not page.pattern:
                    continue
                
                # Добавляем в паттерны
                if page.pattern not in self.url_patterns:
                    self.url_patterns[page.pattern] = []
                if page.url not in self.url_patterns[page.pattern]:
                    self.url_patterns[page.pattern].append(page.url)
        
        if loaded_count > 0:
            self.logger.info(f"Загружено {loaded_count} посещенных URL из БД")
            self.logger.info(f"Найдено {len(self.url_patterns)} уникальных паттернов")
            return
        
        self.logger.info("В БД нет ранее посещенных URL для этого сайта")
    
    def connect_to_chrome(self):
        """Подключение к Chrome в отладочном режиме"""

        if self.driver is not None:
             # Проверяем что подключение работает
            try:
                _ = self.driver.current_url
                self.logger.info("✓ Успешное подключение к браузеру")
                self.logger.info("Используется переданный экземпляр webdriver.Chrome")
                return
            except Exception as e:
                self.logger.warning(f"Подключение установлено, но проблема с сессией: {e}")
                self.driver.quit()

        chrome_options = Options()
        
        if self.debug_mode:
            # Проверяем доступность Chrome на указанном порту
            if not self._is_chrome_running(self.debug_port):
                error_msg = (
                    f"\n{'='*60}\n"
                    f"ОШИБКА: Chrome не запущен на порту {self.debug_port}\n\n"
                    f"Запустите Chrome командой:\n"
                    f"  google-chrome --remote-debugging-port={self.debug_port} "
                    f"--user-data-dir=./chrome_debug_{self.debug_port}\n\n"
                    f"Или проверьте что порт не занят:\n"
                    f"  lsof -i :{self.debug_port}\n"
                    f"{'='*60}\n"
                )
                self.logger.error(error_msg)
                raise WebDriverException(
                    f"Chrome не запущен на порту {self.debug_port}"
                )
            
            chrome_options.add_experimental_option(
                "debuggerAddress", 
                f"localhost:{self.debug_port}"
            )
            self.logger.info(f"Подключение к Chrome на порту {self.debug_port}")
        else:
            chrome_options.add_argument("--start-maximized")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            
            # Отключение ненужных сервисов Google (убирает ошибки GCM)
            chrome_options.add_argument("--disable-sync")
            chrome_options.add_argument("--disable-background-networking")
            chrome_options.add_argument("--disable-default-apps")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--log-level=3")
            
            # Ротация User-Agent для меньшей детекции
            user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ]
            chrome_options.add_argument(f"user-agent={random.choice(user_agents)}")
        
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.implicitly_wait(config.PARSER_DEFAULT_IMPLICIT_WAIT)
            self.driver.set_page_load_timeout(config.PARSER_DEFAULT_PAGE_LOAD_TIMEOUT)
            
            # Проверяем что подключение работает
            try:
                _ = self.driver.current_url
                self.logger.info("✓ Успешное подключение к браузеру")
            except Exception as e:
                self.logger.warning(f"Подключение установлено, но проблема с сессией: {e}")
                self.driver.quit()
                raise
                
        except WebDriverException as e:
            self.logger.error(f"Ошибка подключения к браузеру: {e}")
            if self.debug_mode:
                self.logger.error(
                    f"\nУбедитесь что Chrome запущен:\n"
                    f"  ps aux | grep chrome | grep {self.debug_port}\n"
                )
            raise
    
    def _is_chrome_running(self, port: int) -> bool:
        """
        Проверка запущен ли Chrome на указанном порту
        
        Args:
            port: Порт для проверки
        
        Returns:
            True если Chrome доступен
        """        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('localhost', port))
            sock.close()
            return result == 0
        except Exception:
            return False
    
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
        """Проверка, принадлежит ли URL тому же домену и соответствует ли префиксу"""
        try:
            domain = urlparse(url).netloc.replace('www.', '')
            
            # Проверка домена
            if domain != self.base_domain:
                return False
            
            return True
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
            return len(re.findall(self.site.pattern, path)) > 0
        except Exception as e:
            self.logger.debug(f"Ошибка проверки URL {url}: {e}")
            return False
    
    def check_and_extract_recipe(self, url: str, pattern: str, page_index: int) -> bool:
        """
        Проверяет наличие рецепта на странице и извлекает полные данные с сохранением в БД (сохраняет данные только если там есть рецепт)
        
        Args:
            html_content: HTML содержимое страницы
            url: URL страницы
            save_html: Сохранять ли HTML файл на диск
            
        Returns:
            (is_recipe, confidence_score, recipe_data)
            - is_recipe: True если найден рецепт
            - confidence_score: уровень уверенности (0-100)
            - recipe_data: извлеченные данные рецепта или None
        """
        language = self.driver.execute_script("return document.documentElement.lang") or 'unknown'
        page = Page(site_id=self.site.id, 
                    url=url, 
                    pattern=pattern, 
                    html_path=self.save_page_as_file(pattern, page_index),
                    title=self.driver.title,
                    language=language)

        # Извлекаем полные данные рецепта
        recipe_data: Optional[Page] = self.recipe_extractor.extract_and_update_page(page)
        if not recipe_data:
            self.logger.info(f"  ✗ Рецепт не найден на {url}")
            self.no_recipe_page_count += 1
            return False

        if (self.site.language is None or self.site.language != language) and language != 'unknown':
            self.site.language = language
            try:
                self.site_repository.update_language(site_id=self.site.id, language=language)
            except Exception as e:
                self.logger.error(f"Ошибка обновления языка сайта в БД: {e}")
        
        if recipe_data.is_recipe is False:
            self.logger.info(f"  ✗ Рецепт не найден на {url}")
            self.no_recipe_page_count += 1
            return False

        try:
            image_urls = recipe_data.image_urls.split(",") if recipe_data.image_urls else []
            self.page_repository.create_or_update_with_images(recipe_data, image_urls=image_urls)
        except Exception as e:
            self.logger.error(f"Ошибка сохранения страницы в БД: {e}")
            self.no_recipe_page_count += 1
            return False
        
        dish_name = recipe_data.dish_name or "Без названия"
        self.logger.info(f"  ✓ Рецепт '{dish_name}' сохранен в БД")
        self.no_recipe_page_count = 0 # сброс счетчика страниц без рецепта
        return True
    
    def should_explore_url(self, url: str, ignore_visited: bool = False) -> bool:
        """
        Проверка, нужно ли исследовать данный URL
        
        Args:
            url: URL для проверки     
            ignore_visited: Если True, игнорирует проверку на посещенные URL (используется для начальной загрузки ссылок)       
        Returns:
            True если URL нужно посетить
        """
        # Пропускаем если уже посещали
        if url in self.visited_urls and ignore_visited is False:
            return False
        
        # Проверка лимита URL на паттерн
        if self.max_urls_per_pattern is not None and self.recipe_regex is None:
            pattern = self.get_url_pattern(url)
            current_count = len(self.url_patterns.get(pattern, []))
            if current_count >= self.max_urls_per_pattern:
                self.logger.debug(f"Пропуск URL: достигнут лимит {self.max_urls_per_pattern} для паттерна {pattern}")
                return False
        
        # Пропускаем файлы
        if re.search(r'\.(jpg|jpeg|png|gif|pdf|zip|mp4|avi|css|js)$', url, re.IGNORECASE):
            return False
        
        # Пропускаем служебные страницы
        skip_patterns = [
            r'/answers'
            r'/login',
            r'/register',
            r'/signup',
            r'/blog',
            r'/news',
            r'/forum',
            r'/admin',
            r'/dashboard',
            r'/logout',
            r'/user'
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
            r'/feedback',
            r'/help',
            r'/support',
            r'/faq',
            r'/advertise',
            r'/careers',
            r'/jobs',
            r'/sitemap',
            r'/404',
            r'/500'
            r'/products',

        ]
        
        parsed = urlparse(url)
        path_lower = parsed.path.lower()
        
        for skip_pattern in skip_patterns:
            if re.search(skip_pattern, path_lower):
                self.logger.debug(f"Пропуск служебной страницы: {url}")
                return False
        return True
    
    def get_url_priority(self, url: str) -> int:
        """
        Определение приоритета URL для обхода

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
    
    def slow_scroll_page(self, quick_mode: bool = False):
        """Прокрутка страницы для загрузки контента
        
        Args:
            quick_mode: Если True, делает быструю прокрутку (для ускорения)
        """
        try:
            total_height = self.driver.execute_script("return document.body.scrollHeight")
            
            if quick_mode:
                # Быстрая прокрутка: 2-3 шага с короткими паузами
                num_scrolls = random.randint(2, 3)
                scroll_step = total_height // num_scrolls
                
                current_position = 0
                for i in range(num_scrolls):
                    current_position += scroll_step
                    self.driver.execute_script(f"window.scrollTo(0, {current_position});")
                    time.sleep(random.uniform(0.1, 0.5))
                
                # Быстрая прокрутка в конец
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(0.1, 0.3))
            else:
                # Обычная прокрутка
                num_scrolls = random.randint(3, 5)
                scroll_step = total_height // num_scrolls
                
                current_position = 0
                for i in range(num_scrolls):
                    current_position += scroll_step
                    self.driver.execute_script(f"window.scrollTo(0, {current_position});")
                    time.sleep(random.uniform(0.2, 0.4))
                
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(0.25, 0.5))
            
        except Exception as e:
            self.logger.debug(f"Ошибка при прокрутке: {e}")


    def save_page_as_file(self, pattern: str, page_index: int) -> str:
        """        
        Сохранение HTML страницы на файловую систему
        Args:
            pattern: Паттерн URL
            page_index: Индекс страницы в рамках паттерна
        Returns:
            Путь к сохраненному файлу HTML
        """

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

        return filepath

    
    def save_page_html(self, url: str, pattern: str, page_index: int):
        """
        Сохранение HTML страницы и информации в БД
        
        Args:
            url: URL страницы
            pattern: Паттерн URL
            page_index: Индекс страницы в рамках паттерна
        """
            
        # Получение метаданных
        title = self.driver.title
        language = self.driver.execute_script("return document.documentElement.lang") or 'unknown'
        filepath = self.save_page_as_file(pattern, page_index)
        filename = os.path.basename(filepath)
        page_orm = self.page_repository.create_or_update(
            Page(
                site_id=self.site.id,
                url=url,
                pattern=pattern,
                title=title,
                language=language,
                html_path=os.path.relpath(filepath)
            ))
    
        if page_orm.id:
            self.logger.info(f"  ✓ Сохранено: {filename} (DB ID: {page_orm.id})")
        else:
            self.logger.info(f"  ✓ Сохранено: {filename} (БД: ошибка)")


    
    def extract_links(self) -> List[str]:
        """
        Извлечение всех ссылок со страницы (без приоритизации)
        Для приоритизации используйте extract_links_with_priority()
        """
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
            self.logger.error(f"Ошибка извлечения ссылок: {e}")
            return []
    

    def extract_links_with_priority(self) -> List[str]:
        """
        Извлечение ссылок с приоритизацией успешных источников и разнообразия паттернов
        
        Приоритизация:
        1. Ссылки от успешных источников
        2. Ссылки с паттерном URL, отличным от текущей страницы (для разнообразия)
        
        Returns:
            Список URL (приоритетные ссылки в начале)
        """
        try:
            soup = BeautifulSoup(self.driver.page_source, 'lxml')
            priority_links = []  # От успешных источников
            different_pattern_links = []  # С другим паттерном
            regular_links = []  # Остальные
            seen_urls = set()
            
            current_url = self.driver.current_url
            is_successful_source = current_url in self.successful_referrers
            
            # Получаем паттерн текущего URL (числа заменены на #)
            current_pattern = self.get_url_pattern(current_url)
            
            for link in soup.find_all('a', href=True):
                href = link['href']
                absolute_url = urljoin(current_url, href)
                
                # Очистка от якорей и параметров
                clean_url = absolute_url.split('#')[0].split('?')[0]
                
                if not (clean_url and self.is_same_domain(clean_url)):
                    continue
                
                if clean_url in seen_urls:
                    continue
                
                seen_urls.add(clean_url)
                
                # Получаем паттерн ссылки
                link_pattern = self.get_url_pattern(clean_url)
                
                # Приоритет 1: Ссылки от успешных источников
                if is_successful_source:
                    priority_links.append(clean_url)
                # Приоритет 2: Ссылки с другим паттерном (для разнообразия)
                elif link_pattern != current_pattern:
                    different_pattern_links.append(clean_url)
                # Приоритет 3: Остальные (с таким же паттерном)
                else:
                    regular_links.append(clean_url)
            
            # Собираем в порядке приоритета
            result = priority_links + different_pattern_links + regular_links
            
            # Логирование для отладки
            if different_pattern_links:
                self.logger.debug(f"  Приоритизировано {len(different_pattern_links)} ссылок с другим паттерном (текущий: {current_pattern})")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Ошибка извлечения ссылок с приоритетом: {e}")
            return []
    
    
    def  export_state(self) -> dict:
        """Экспорт состояния для передачи в другой экземпляр
        
        Returns:
            Словарь с полным состоянием explorer
        """
        return {
            'base_url': self.site.base_url,
            'recipe_pattern': self.site.pattern,
            'visited_urls': list(self.visited_urls),
            'url_patterns': dict(self.url_patterns),
            'failed_urls': list(self.failed_urls),
            'referrer_map': dict(self.referrer_map),
            'successful_referrers': list(self.successful_referrers),
            'exploration_queue': list(self.exploration_queue),
            'request_count': self.request_count,
            'site_id': self.site.id,
            'site_name': self.site.name,
            'exported_at': time.strftime('%Y-%m-%d %H:%M:%S')
        }
    
    def add_helper_urls(self, urls: List[str], depth: int = 0):
        """
        Добавляет вспомогательные URL в очередь исследования
        
        Args:
            urls: Список URL для добавления
            depth: Начальная глубина для этих URL (по умолчанию 0)
        """
        # Сортируем очередь по приоритету
        self.exploration_queue.sort(key=lambda x: self.get_url_priority(x[0]))

        added_count = 0
        for url in urls:
            # Проверяем что URL того же домена
            if not self.is_same_domain(url):
                self.logger.warning(f"Пропущен URL другого домена: {url}")
                continue
            
            # Проверяем что URL еще не посещен и не в очереди
            self.exploration_queue.insert(0, (url, depth))
            added_count += 1
            self.logger.info(f"  + Добавлен в начало: {url}")
        
        
        self.logger.info(f"Добавлено {added_count} вспомогательных URL в очередь")
        self.logger.info(f"Всего в очереди: {len(self.exploration_queue)} URL")
    
    def import_state(self, state: dict):
        """Импорт состояния из другого экземпляра
        
        Args:
            state: Словарь состояния из export_state()
        """
        self.visited_urls = set(state.get('visited_urls', []))
        self.url_patterns = {k: v for k, v in state.get('url_patterns', {}).items()}
        self.failed_urls = set(state.get('failed_urls', []))
        self.referrer_map = dict(state.get('referrer_map', {}))
        self.successful_referrers = set(state.get('successful_referrers', []))
        self.exploration_queue = [tuple(item) for item in state.get('exploration_queue', [])]
        self.request_count = state.get('request_count', 0)
        
        # Обновляем regex паттерн если изменился
        new_pattern = state.get('recipe_pattern')
        if new_pattern and new_pattern != self.site.pattern:
            self.site.pattern = new_pattern
            try:
                self.recipe_regex = re.compile(new_pattern)
                self.logger.info(f"Обновлен regex паттерн: {new_pattern}")
            except re.error as e:
                self.logger.error(f"Неверный regex паттерн при импорте: {e}")
        
        self.logger.info(f"Состояние импортировано: {len(self.visited_urls)} посещенных URL, "
                   f"{len(self.url_patterns)} паттернов, {len(self.exploration_queue)} URL в очереди, "
                   f"{self.request_count} запросов")
    
    def save_state(self):
        """Сохранение текущего состояния исследования в файл"""
        state = self.export_state()
        
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        
        # Сохранение паттернов отдельно для совместимости
        patterns_data = {
            'patterns': dict(self.url_patterns),
            'total_patterns': len(self.url_patterns),
            'total_unique_urls': sum(len(urls) for urls in self.url_patterns.values())
        }
        
        with open(self.patterns_file, 'w', encoding='utf-8') as f:
            json.dump(patterns_data, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"Состояние сохранено: {len(self.visited_urls)} посещено, {len(self.url_patterns)} паттернов")
    
    def load_state(self) -> bool:
        """Загрузка сохраненного состояния из файла"""
        if not os.path.exists(self.state_file):
            self.logger.info("Файл состояния не найден, начинаем с нуля")
            return False
        
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            
            self.import_state(state)
            
            self.logger.info("Загружено состояние:")
            self.logger.info(f"  Посещено URL: {len(self.visited_urls)}")
            self.logger.info(f"  Найдено паттернов: {len(self.url_patterns)}")
            self.logger.info(f"  URL в очереди: {len(self.exploration_queue)}")
            self.logger.info(f"  Успешных источников: {len(self.successful_referrers)}")
            self.logger.info(f"  Ошибок: {len(self.failed_urls)}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка загрузки состояния: {e}")
            return False
        
    def should_extract_recipe(self, current_url: str) -> bool:
        """
        Проверка, нужно ли извлекать рецепт с текущей страницы
        
        Args:
            current_url: URL текущей страницы
            check_url: Проверять ли соответствие URL паттерну рецепта
            
        Returns:
            True если нужно извлекать рецепт
        """
        # Если паттерн не задан - извлекаем всегда
        if self.recipe_regex is None:
            return True
        
        # Если паттерн задан - проверяем соответствие
        return self.is_recipe_url(current_url)
        
    def mark_page_as_successful(self, current_url: str):
        """
        Отмечает страницу как успешную (с рецептом) и обновляет успешные источники
        Переупорядочивает очередь, ставя URL от успешного источника в начало
        """
        referrer = self.referrer_map.get(current_url)
        if referrer:
            self.successful_referrers.add(referrer)
            self.logger.info(f"  ✓ Источник отмечен как успешный: {referrer}")
            
            # Переупорядочиваем очередь: URL от успешного источника - в начало
            if self.exploration_queue:
                priority_urls = []
                other_urls = []
                
                for url_tuple in self.exploration_queue:
                    url, _ = url_tuple
                    if self.referrer_map.get(url) == referrer:
                        priority_urls.append(url_tuple)
                    else:
                        other_urls.append(url_tuple)
                
                if priority_urls:
                    # Приоритетные URL вперед, остальные после
                    self.exploration_queue = priority_urls + other_urls
                    self.logger.info(f"  ↑ {len(priority_urls)} URL от успешного источника передвинуты в начало очереди")
    
    def _navigate_with_timeout(self, url: str, timeout: int = 90) -> bool:
        """
        Переход на страницу с гарантированным timeout через отдельный поток
        
        Args:
            url: URL для загрузки
            timeout: Максимальное время ожидания в секундах
            
        Returns:
            True если загрузка успешна, False если timeout
        """
        load_complete = threading.Event()
        navigation_error = [None]  # Для передачи исключений из потока
        
        def navigate():
            try:
                self.driver.get(url)
                load_complete.set()
            except Exception as e:
                navigation_error[0] = e
                load_complete.set()
        
        # Запуск загрузки в отдельном потоке
        nav_thread = threading.Thread(target=navigate, daemon=True)
        nav_thread.start()
        
        # Ожидание с timeout
        if not load_complete.wait(timeout=timeout):
            # Timeout - принудительная остановка
            self.logger.warning(f"⏱ Timeout {timeout}s при загрузке, останавливаем")
            try:
                self.driver.execute_script("window.stop();")
            except Exception:
                pass
            return False
        
        # Проверка на ошибки навигации
        if navigation_error[0]:
            if isinstance(navigation_error[0], TimeoutException):
                self.logger.warning("⏱ Selenium TimeoutException при загрузке")
                try:
                    self.driver.execute_script("window.stop();")
                except Exception:
                    pass
                return False
            else:
                # Другие ошибки пробрасываем
                raise navigation_error[0]
        
        return True
    
    def explore(self, max_urls: int = 100, max_depth: int = 3, session_urls: bool = True, 
                check_pages_with_extractor:bool = False, check_url: bool = False) -> int:
        """
        Исследование структуры сайта
        
        Args:
            max_urls: Максимальное количество URL для посещения
            max_depth: Максимальная глубина обхода
            session_urls: Если True, то не учитывает старые посещенные URL при подсчтее max urls
            check_pages_with_extractor: Если True, проверяет каждую страницу экстрактором рецептов
            check_url: Если True, проверяет каждый на реджекс паттерн перед экстракцией (парамтер касается только экстракции)
        Returns:
            urls_explored: Количество успешно посещенных URL в этой сессии
        """
        self.logger.info(f"Начало исследования сайта: {self.site.base_url}")
        self.logger.info(f"Цель: найти до {max_urls} уникальных паттернов URL")
        
        # Очередь URL для обхода: (url, depth)
        # Если есть сохраненная очередь - используем её, иначе начинаем с base_url
        if self.exploration_queue:
            queue = list(self.exploration_queue)
            self.logger.info(f"Продолжаем с сохраненной очередью: {len(queue)} URL")
        else:
            queue = [(self.site.base_url, 0)]
            self.logger.info("Начинаем новое исследование")
        
        urls_explored = len(self.visited_urls)

        if session_urls:
            urls_explored = 0  # Считаем только в этой сессии
        
        # Логирование начальной стратегии
        initial_strategy = "глубина (паттерн рецептов не найден)" if self.recipe_regex is None else "ширина (паттерн рецептов найден)"
        self.logger.info(f"Стратегия обхода: {initial_strategy}")

        err_count = 0  # Счетчик ошибок подряд
        last_strategy = self.recipe_regex is not None  # Для отслеживания переключений

        while queue and urls_explored < max_urls:
            
            # Проверка лимита страниц без рецепта подряд
            if self.max_no_recipe_pages and self.no_recipe_page_count >= self.max_no_recipe_pages:
                self.logger.info(f"🚫 Превышен лимит {self.max_no_recipe_pages} страниц без рецепта подряд, остановка исследования")
                break
            # Выбираем стратегию: если паттерна нет - идем вглубь (LIFO), иначе вширь (FIFO)
            has_recipe_pattern = self.recipe_regex is not None
            
            # Логируем переключение стратегии
            if has_recipe_pattern != last_strategy:
                new_strategy = "ширина (паттерн найден)" if has_recipe_pattern else "глубина (паттерн потерян)"
                self.logger.info(f"⚡ Переключение стратегии: {new_strategy}")
                last_strategy = has_recipe_pattern
            
            # DFS: pop() берет с конца (последний добавленный - первым обрабатывается)
            # BFS: pop(0) берет с начала (первый добавленный - первым обрабатывается)
            current_url, depth = queue.pop() if not has_recipe_pattern else queue.pop(0)
            
            # Проверка глубины
            if depth > max_depth:
                continue
            
            # Получение паттерна
            pattern = self.get_url_pattern(current_url)
            
            # Проверка, нужно ли посещать
            ignore_visited = len(queue) <= 5  # В начале обхода игнорируем посещенные URL, чтобы быстрее набрать базу паттернов
            if self.should_explore_url(current_url, ignore_visited=ignore_visited) is False and urls_explored > 0 and not check_pages_with_extractor:
                continue
            
            try:
                self.logger.info(f"[{urls_explored + 1}/{max_urls}] Переход на: {current_url}")
                self.logger.info(f"  Паттерн: {pattern}, Глубина: {depth}")
                
                # Засекаем время начала загрузки
                page_load_start = time.time()
                
                # Используем новый метод с гарантированным timeout
                if not self._navigate_with_timeout(current_url, timeout=90):
                    self.logger.error("Не удалось загрузить страницу, пропускаем")
                    self.failed_urls.add(current_url)
                    err_count += 1
                    continue
                
                # Более надежное ожидание загрузки
                try:
                    # Ждем либо полной загрузки, либо interactive (достаточно для парсинга)
                    WebDriverWait(self.driver, 10).until(
                        lambda d: d.execute_script('return document.readyState') in ['complete', 'interactive']
                    )
                except TimeoutException:
                    self.logger.warning("⏱ Timeout при ожидании загрузки, но продолжаем")
                    # Проверяем что хоть что-то загрузилось
                    try:
                        body = self.driver.find_element("tag name", "body")
                        if not body:
                            raise RuntimeError("Страница пустая")
                    except Exception:
                        self.logger.error("Страница не загрузилась, пропускаем")
                        self.failed_urls.add(current_url)
                        continue
                     
                # Проверка на Cloudflare/Captcha
                try:
                    page_title = self.driver.title.lower()
                    page_source_snippet = self.driver.page_source[:5000].lower()  # Только начало для скорости
                    
                    # Проверка на защиту
                    protection_indicators = [
                        'cloudflare', 'captcha', 'are you a robot', 'access denied',
                        'just a moment', 'challenge', 'verify you are human'
                    ]
                    
                    if any(indicator in page_title or indicator in page_source_snippet 
                           for indicator in protection_indicators):
                        self.logger.warning(f"🛡️ Обнаружена защита от ботов на {current_url}")
                        self.logger.warning("Пауза 10 секунд для ручного решения...")
                        time.sleep(10)  # Даем время решить вручную
                        
                        # Проверяем еще раз
                        if any(indicator in self.driver.title.lower() for indicator in protection_indicators):
                            self.logger.error("Защита не пройдена, пропускаем URL")
                            self.failed_urls.add(current_url)
                            err_count += 1
                            continue
                except Exception as e:
                    self.logger.debug(f"Ошибка проверки защиты: {e}")
                
                # Логирование времени загрузки
                total_load_time = time.time() - page_load_start
                self.logger.debug(f"  ✓ Страница загружена за {total_load_time:.1f}s")
                
                # Адаптивная задержка: короче в начале, длиннее после каждых 10 запросов
                self.request_count += 1
                if self.request_count % 10 == 0:
                    # Каждые 10 запросов - более длинная пауза для снижения подозрительности
                    delay = random.uniform(1, 3)
                    self.logger.info(f"  Длинная пауза после {self.request_count} запросов: {delay:.1f}с")
                else:
                    # Обычная короткая пауза
                    delay = random.uniform(0.5, 1)
                time.sleep(delay)
                
                # Прокрутка для загрузки контента (быстрый режим для ускорения)
                use_quick_scroll = self.request_count % 3 != 0  # Каждый 3-й - обычная прокрутка
                self.slow_scroll_page(quick_mode=use_quick_scroll)
                
                # Добавление в посещенные
                self.visited_urls.add(current_url)
                urls_explored += 1
                
                # Добавление в паттерн
                if pattern not in self.url_patterns:
                    self.url_patterns[pattern] = []
                
                page_index = len(self.url_patterns[pattern]) + 1
                self.url_patterns[pattern].append(current_url)
                
                
                # Если задан режим проверки с экстрактором, дополнительно может быть задан режим провекри по паттерну
                if check_pages_with_extractor and (check_url is False or self.should_extract_recipe(current_url)):   
                    if self.check_and_extract_recipe(current_url, pattern, page_index):
                        # Если URL не соответствует паттерну, но рецепт найден - обновляем паттерн
                        if self.recipe_regex and not self.is_recipe_url(current_url):
                            self.logger.info("  Обновление паттерна URL, так как найден рецепт на странице")
                            if self.analyzer is None:
                                self.analyzer = RecipeAnalyzer()
                            pattern =  self.analyzer.analyse_recipe_page_pattern(site_id=self.site.id)
                            
                # Если задан regex паттерн - сохраняем рецепт, иначе сохраняем все страницы
                elif self.should_extract_recipe(current_url):
                    if self.site.pattern: self.mark_page_as_successful(current_url) # Если паттерн задан - отмечаем как успешный тк иначе не можем знать был ли вообще успех
                    self.save_page_html(current_url, pattern, page_index)

                # Извлечение новых ссылок
                new_links = self.extract_links_with_priority()
                self.logger.info(f"  Найдено ссылок: {len(new_links)}")
                
                # Добавление новых ссылок в очередь с отслеживанием источника
                # Если паттерн рецептов не найден - приоритизируем глубину (DFS)
                # Если паттерн найден - используем ширину (BFS)
                has_recipe_pattern = self.recipe_regex is not None
                
                for link_url in new_links:
                    if self.should_explore_url(link_url, ignore_visited=len(queue) <= 5): # Всегда добавляем, если очередь маленькая (для старта и чтобы не вылететь на начальном этапе)
                        # Запоминаем источник перехода
                        if link_url not in self.referrer_map:
                            self.referrer_map[link_url] = current_url
                        
                        # DFS (вглубь): добавляем в начало очереди если паттерна нет
                        # BFS (вширь): добавляем в конец очереди если паттерн есть
                        if has_recipe_pattern and check_url is True:
                            queue.append((link_url, depth + 1))
                        else:
                            queue.insert(0, (link_url, depth + 1))
                
                # Сортируем очередь по приоритету только если паттерн найден
                if has_recipe_pattern:
                    queue.sort(key=lambda x: self.get_url_priority(x[0]))
                
                # Периодическое сохранение
                if urls_explored % 10 == 0:
                    self.exploration_queue = queue  # Сохраняем текущую очередь
                    self.save_state()
                
            except KeyboardInterrupt:
                self.logger.warning("⌨️ Прервано пользователем, сохраняем состояние...")
                self.exploration_queue = queue
                self.save_state()
                raise
            except Exception as e:
                self.logger.error(f"Ошибка при обработке {current_url}: {e}")
                self.failed_urls.add(current_url)
                self.exploration_queue = queue  # Сохраняем очередь при ошибке
                self.save_state()  # Сохранение при ошибке
                err_count += 1
                if err_count >= self.max_errors:
                    self.logger.error(f"Превышено максимальное количество ошибок подряд ({self.max_errors}), остановка исследования.")
                    break
                continue
        
        # Финальное сохранение с текущей очередью
        self.exploration_queue = queue
        self.save_state()
        
        self.logger.info(f"\n{'='*60}")
        self.logger.info("Исследование завершено" if err_count < self.max_errors else "Исследование остановлено из-за ошибок")
        self.logger.info(f"Результаты сохранены в: {self.save_dir}")
        self.logger.info(f"  - {self.state_file} - состояние")
        self.logger.info(f"  - {self.patterns_file} - найденные паттерны")
        self.logger.info(f"  - *.html - сохраненные страницы ({sum(len(urls) for urls in self.url_patterns.values())} файлов)")
        self.logger.info("Для продолжения используйте: explorer.load_state() или explorer.import_state(state)")
        self.logger.info(f"{'='*60}")
        return urls_explored

    
    def close(self):
        """Закрытие браузера и БД"""
        if self.driver and not self.debug_mode:
            self.driver.quit()
        
        self.site_repository.close()
        self.page_repository.close()
        self.logger.info("Готово")


def explore_site(url: str, max_urls: int = 1000, max_depth: int = 4, recipe_pattern: str = None,
                 check_pages_with_extractor: bool = False,
                 check_url: bool = False,
                 max_urls_per_pattern: int = None, debug_port: int = 9222,
                 helper_links: List[str] = None,
                 custom_logger: Optional[logging.Logger] = None,
                 max_no_recipe_pages: Optional[int] = None) -> int:
    """
    Функция для исследования сайта с обработкой ошибок и прерываний
    
    Args:
        url: Базовый URL сайта
        max_urls: Максимальное количество URL для исследования
        max_depth: Максимальная глубина исследования
        recipe_pattern: Regex паттерн для поиска URL с рецептами
        check_pages_with_extractor: Проверять ли каждую страницу экстрактором рецептов
        check_url: Проверять ли URL на соответствие паттерну перед экстракцией
        max_urls_per_pattern: Максимальное количество URL на один паттерн (None = без ограничений)
        debug_port: Порт для подключения к Chrome
        helper_links: Список вспомогательных ссылок для начала исследования
        max_no_recipe_pages: Максимальное количество страниц без рецепта подряд (None = без ограничений)
        custom_logger: Пользовательский логгер (если None, используется стандартный)
    
    Returns:
        Количество исследованных URL
    """
    explorer = None  # Инициализация перед try
    if custom_logger is None:
        custom_logger = logger
    
    try:
        explorer = SiteExplorer(
            url, 
            debug_port=debug_port, 
            debug_mode=True, 
            recipe_pattern=recipe_pattern, 
            max_urls_per_pattern=max_urls_per_pattern,
            custom_logger=custom_logger,
            max_no_recipe_pages=max_no_recipe_pages
        )
        
        if helper_links:
            explorer.add_helper_urls(helper_links, depth=1)
        
        explorer.connect_to_chrome()
        explorer.load_state()
        
        urls_explored = explorer.explore(
            max_urls=max_urls, 
            max_depth=max_depth, 
            check_url=check_url, 
            check_pages_with_extractor=check_pages_with_extractor
        )
        
        custom_logger.info(f"✓ Исследование завершено: {urls_explored} URL")
        return urls_explored
        
    except KeyboardInterrupt:
        custom_logger.warning("\nПрервано пользователем")
        if explorer:
            explorer.save_state()
        raise
        
    except WebDriverException as e:
        custom_logger.error(f"Ошибка WebDriver: {e}")
        if explorer:
            explorer.save_state()
        raise
        
    except Exception as e:
        custom_logger.error(f"Критическая ошибка: {e}", exc_info=True)
        if explorer:
            explorer.save_state()
        raise
        
    finally:
        if explorer:
            explorer.close()

def run_explorer(explorer:SiteExplorer, max_urls: int, max_depth: int):
    
    try:
        explorer.connect_to_chrome()
        explorer.explore(max_urls=max_urls, max_depth=max_depth)
    except KeyboardInterrupt:
        logger.info("\nПрервано пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
    finally:
        explorer.close()

