"""
Модуль для сканирования карт сайта (sitemap.xml, HTML sitemap) для сбора URL
"""
import gzip
import logging
import xml.etree.ElementTree as ET
import time
from typing import Optional
from urllib.parse import urljoin, urlparse
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)


class SitemapScanner:
    """Сканер карт сайта (XML и HTML) для сбора URL"""
    
    # Общие пути к sitemap
    COMMON_SITEMAP_PATHS = [
        '/sitemap.xml',
        '/sitemap.xml.gz',
        '/sitemap_index.xml',
        '/sitemap-index.xml',
        '/post-sitemap.xml',
        '/page-sitemap.xml',
        '/recipe-sitemap.xml',
        '/recipes-sitemap.xml',
        '/sitemap/sitemap.xml',
        '/sitemap/sitemap-index.xml',
        '/sitemap.html',
        '/sitemap/',
    ]
    
    # Namespaces для парсинга XML
    NAMESPACES = {
        'sitemap': 'http://www.sitemaps.org/schemas/sitemap/0.9',
        'image': 'http://www.google.com/schemas/sitemap-image/1.1',
        'news': 'http://www.google.com/schemas/sitemap-news/0.9',
    }
    
    def __init__(self, base_url: str,
                 active_driver: webdriver.Chrome,
                 max_recursion_depth: int = 10,
                 custom_logger: Optional[logging.Logger] = None
                 ):
        """
        Args:
            base_url: Базовый URL сайта
            active_driver: Активный Selenium WebDriver
            max_recursion_depth: Максимальная глубина рекурсии для вложенных sitemap
            page_load_timeout: Таймаут загрузки страницы (секунды)
            custom_logger: Пользовательский логгер
        """
        self.driver = active_driver
        self.base_url = base_url.rstrip('/')
        self.max_recursion_depth = max_recursion_depth
        self.logger = custom_logger or logger

        self.visited_sitemaps = set()
    
    def fetch_sitemap(self, sitemap_url: str) -> Optional[str]:
        """
        Загрузка содержимого sitemap через Selenium (поддерживает gzip сжатие)
        
        Args:
            sitemap_url: URL sitemap
            
        Returns:
            XML содержимое или None при ошибке
        """
        try:
            self.driver.get(sitemap_url)
            
            # Даем странице время на загрузку
            time.sleep(2)
            
            # Получаем содержимое страницы
            content = self.driver.page_source
            
            # Проверяем на gzip сжатие (если браузер не распаковал автоматически)
            # В большинстве случаев браузер сам распаковывает gzip
            if sitemap_url.endswith('.gz'):
                try:
                    # Пытаемся распаковать если содержимое в бинарном виде
                    if content.startswith('\x1f\x8b'):  # gzip magic bytes
                        content = gzip.decompress(content.encode('latin-1')).decode('utf-8')
                        self.logger.info("  Распакован gzip sitemap")
                except Exception as e:
                    self.logger.warning(f"  Не удалось распаковать gzip, используем как есть: {e}")
            
            # Проверяем что получили XML
            if not content.strip().startswith('<?xml') and not content.strip().startswith('<'):
                self.logger.warning(f"  Возможно не XML: {content[:100]}")
            
            return content
            
        except TimeoutException:
            self.logger.error(f"Таймаут загрузки {sitemap_url}")
            return None
        except WebDriverException as e:
            self.logger.error(f"Ошибка Selenium при загрузке {sitemap_url}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Неожиданная ошибка загрузки {sitemap_url}: {e}")
            return None
    
    def parse_sitemap_index(self, xml_content: str) -> list[str]:
        """
        Парсинг sitemap index для получения ссылок на отдельные sitemap
        
        Args:
            xml_content: XML содержимое sitemap index
            
        Returns:
            Список URL отдельных sitemap
        """
        sitemap_urls = []
        
        try:
            root = ET.fromstring(xml_content)
            
            # Поиск тегов <sitemap><loc>
            for sitemap in root.findall('.//sitemap:sitemap', self.NAMESPACES):
                loc = sitemap.find('sitemap:loc', self.NAMESPACES)
                if loc is not None and loc.text:
                    sitemap_urls.append(loc.text.strip())
            
            # Fallback: поиск без namespace
            if not sitemap_urls:
                for sitemap in root.findall('.//sitemap'):
                    loc = sitemap.find('loc')
                    if loc is not None and loc.text:
                        sitemap_urls.append(loc.text.strip())
            
            self.logger.info(f"Найдено {len(sitemap_urls)} sitemap в индексе")
            
        except ET.ParseError as e:
            self.logger.error(f"Ошибка парсинга XML sitemap index: {e}")
        
        return sitemap_urls
    
    def parse_sitemap_urls(self, xml_content: str) -> set[str]:
        """
        Парсинг sitemap для извлечения URL
        
        Args:
            xml_content: XML содержимое sitemap
            
        Returns:
            Множество найденных URL
        """
        urls = set()
        
        try:
            root = ET.fromstring(xml_content)
            
            # Поиск тегов <url><loc>
            for url_elem in root.findall('.//sitemap:url', self.NAMESPACES):
                loc = url_elem.find('sitemap:loc', self.NAMESPACES)
                if loc is not None and loc.text:
                    urls.add(loc.text.strip())
            
            # Fallback: поиск без namespace
            if not urls:
                for url_elem in root.findall('.//url'):
                    loc = url_elem.find('loc')
                    if loc is not None and loc.text:
                        urls.add(loc.text.strip())
            
            self.logger.info(f"Извлечено {len(urls)} URL из sitemap")
            
        except ET.ParseError as e:
            self.logger.error(f"Ошибка парсинга XML sitemap: {e}")
        
        return urls
    
    def parse_html_sitemap(self, html_content: str, sitemap_url: str) -> set[str]:
        """
        Парсинг HTML sitemap для извлечения URL
        
        Args:
            html_content: HTML содержимое sitemap
            sitemap_url: URL sitemap для построения абсолютных ссылок
            
        Returns:
            Множество найденных URL
        """
        urls = set()
        
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Извлекаем все ссылки из <a href="...">
            for link in soup.find_all('a', href=True):
                href = link['href'].strip()
                
                # Пропускаем якоря и javascript
                if href.startswith('#') or href.startswith('javascript:'):
                    continue
                
                # Преобразуем в абсолютный URL
                absolute_url = urljoin(sitemap_url, href)
                
                # Проверяем что это валидный HTTP(S) URL
                parsed = urlparse(absolute_url)
                if parsed.scheme in ('http', 'https'):
                    urls.add(absolute_url)
            
            self.logger.info(f"Извлечено {len(urls)} URL из HTML sitemap")
            
        except Exception as e:
            self.logger.error(f"Ошибка парсинга HTML sitemap: {e}")
        
        return urls
    
    def _is_html_sitemap(self, content: str) -> bool:
        """
        Проверка, является ли содержимое HTML sitemap
        
        Args:
            content: Содержимое для проверки
            
        Returns:
            True если это HTML
        """
        content_lower = content.strip().lower()
        
        # Проверяем наличие HTML тегов
        html_indicators = [
            '<!doctype html',
            '<html',
            '<head>',
            '<body>',
            '<div',
            '<table'
        ]
        
        return any(indicator in content_lower for indicator in html_indicators)
    
    def scan_sitemap(self, sitemap_url: Optional[str] = None, depth: int = 0) -> set[str]:
        """
        Рекурсивное сканирование sitemap (может быть index или обычный sitemap)
        
        Args:
            sitemap_url: URL sitemap (если None, используется стандартный путь)
            depth: Текущая глубина рекурсии
            
        Returns:
            Множество найденных URL
        """
        if sitemap_url is None:
            sitemap_url = urljoin(self.base_url, '/sitemap.xml')
        
        # Проверка глубины рекурсии
        if depth > self.max_recursion_depth:
            self.logger.warning(f"Достигнута максимальная глубина рекурсии ({self.max_recursion_depth}) для {sitemap_url}")
            return set()
        
        # Проверка, не посещали ли мы уже этот sitemap
        if sitemap_url in self.visited_sitemaps:
            self.logger.debug(f"Sitemap уже был обработан: {sitemap_url}")
            return set()
        
        # Отмечаем как посещенный
        self.visited_sitemaps.add(sitemap_url)
        
        # Загружаем содержимое
        content = self.fetch_sitemap(sitemap_url)
        if not content:
            return set()
        
        # Определяем формат sitemap (XML или HTML)
        if self._is_html_sitemap(content):
            # HTML sitemap - извлекаем все ссылки
            self.logger.info(f"{'  ' * depth}├─ Обнаружен HTML sitemap (глубина {depth})")
            urls = self.parse_html_sitemap(content, sitemap_url)
            if urls:
                self.logger.info(f"{'  ' * depth}└─ Извлечено {len(urls)} URL из HTML sitemap")
            return urls
        
        # XML sitemap - определяем тип (index или обычный)
        is_index = self._is_sitemap_index(content)
        
        if is_index:
            # Это sitemap index - рекурсивно обрабатываем вложенные sitemap
            self.logger.info(f"{'  ' * depth}├─ Обнаружен XML sitemap index (глубина {depth})")
            sitemap_urls = self.parse_sitemap_index(content)
            
            all_urls = set()
            for i, sub_sitemap_url in enumerate(sitemap_urls, 1):
                is_last = (i == len(sitemap_urls))
                prefix = '└─' if is_last else '├─'
                self.logger.info(f"{'  ' * depth}{prefix} Обработка вложенного sitemap {i}/{len(sitemap_urls)}: {sub_sitemap_url}")
                
                # Рекурсивный вызов для вложенного sitemap
                urls = self.scan_sitemap(sub_sitemap_url, depth=depth + 1)
                all_urls.update(urls)
            
            return all_urls
        else:
            # Обычный XML sitemap с URL
            urls = self.parse_sitemap_urls(content)
            if urls:
                self.logger.info(f"{'  ' * depth}└─ Извлечено {len(urls)} URL из XML sitemap")
            return urls
    
    def _is_sitemap_index(self, xml_content: str) -> bool:
        """
        Проверка, является ли XML содержимое sitemap index
        
        Args:
            xml_content: XML содержимое
            
        Returns:
            True если это sitemap index
        """
        # Проверяем наличие тегов sitemap index
        if '<sitemapindex' in xml_content.lower():
            return True
        
        # Дополнительная проверка: есть ли теги <sitemap> вместо <url>
        try:
            root = ET.fromstring(xml_content)
            
            # Ищем теги <sitemap>
            has_sitemap_tags = (
                len(root.findall('.//sitemap:sitemap', self.NAMESPACES)) > 0 or
                len(root.findall('.//sitemap')) > 0
            )
            
            return has_sitemap_tags
            
        except ET.ParseError:
            return False
    
    def discover_and_scan_all(self, custom_paths: Optional[list[str]] = None) -> set[str]:
        """
        Поиск и сканирование всех доступных sitemap на сайте
        
        Args:
            custom_paths: Дополнительные пути для проверки
            
        Returns:
            Множество всех найденных URL
        """
        # Сбрасываем visited_sitemaps для нового сканирования
        self.visited_sitemaps.clear()
        
        all_urls = set()
        paths_to_try = self.COMMON_SITEMAP_PATHS.copy()
        
        if custom_paths:
            paths_to_try.extend(custom_paths)
        
        # Также проверим robots.txt для поиска sitemap
        robots_sitemaps = self._get_sitemaps_from_robots()
        if robots_sitemaps:
            self.logger.info(f"Найдено {len(robots_sitemaps)} sitemap в robots.txt")
            paths_to_try.extend(robots_sitemaps)
        
        # Удаляем дубликаты
        unique_sitemap_urls = set()
        for path in paths_to_try:
            if path.startswith('http'):
                unique_sitemap_urls.add(path)
            else:
                unique_sitemap_urls.add(urljoin(self.base_url, path))
        
        self.logger.info(f"Проверка {len(unique_sitemap_urls)} потенциальных начальных sitemap")
        
        for sitemap_url in unique_sitemap_urls:
            urls = self.scan_sitemap(sitemap_url)
            if urls:
                all_urls.update(urls)
                self.logger.info(f"✓ Всего из этого sitemap и его вложенных: {len(urls)} URL")
        
        return all_urls
    
    def _get_sitemaps_from_robots(self) -> list[str]:
        """
        Извлечение URL sitemap из robots.txt через Selenium
        
        Returns:
            Список URL sitemap из robots.txt
        """
        sitemap_urls = []
        robots_url = urljoin(self.base_url, '/robots.txt')
        
        try:
            self.logger.info(f"Проверка robots.txt через Selenium: {robots_url}")
            self.driver.get(robots_url)
            time.sleep(1)
            
            # Получаем текст robots.txt
            robots_text = self.driver.page_source
            
            # Иногда браузер оборачивает текст в <pre> или <body>
            if '<pre>' in robots_text:
                import re
                match = re.search(r'<pre>(.*?)</pre>', robots_text, re.DOTALL)
                if match:
                    robots_text = match.group(1)
            elif '<body>' in robots_text:
                import re
                match = re.search(r'<body>(.*?)</body>', robots_text, re.DOTALL)
                if match:
                    robots_text = match.group(1)
            
            # Парсим robots.txt построчно
            for line in robots_text.split('\n'):
                line = line.strip()
                if line.lower().startswith('sitemap:'):
                    sitemap_url = line.split(':', 1)[1].strip()
                    sitemap_urls.append(sitemap_url)
                    self.logger.info(f"Найден sitemap в robots.txt: {sitemap_url}")
            
        except Exception as e:
            self.logger.warning(f"Не удалось загрузить robots.txt: {e}")
        
        return sitemap_urls
    
    def filter_urls_by_domain(self, urls: set[str], base_domain: str) -> set[str]:
        """
        Фильтрация URL по домену
        
        Args:
            urls: Множество URL для фильтрации
            base_domain: Базовый домен для проверки
            
        Returns:
            Отфильтрованное множество URL того же домена
        """
        filtered = set()
        base_domain = base_domain.replace('www.', '')
        
        for url in urls:
            try:
                domain = urlparse(url).netloc.replace('www.', '')
                if domain == base_domain:
                    filtered.add(url)
            except Exception:
                continue
        
        return filtered
    
    def reset(self):
        """Сброс состояния сканера (очистка посещенных sitemap)"""
        self.visited_sitemaps.clear()
        self.logger.info("Состояние сканера сброшено")
