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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException
from bs4 import BeautifulSoup

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import config.config as config
from src.common.db.mysql import MySQlManager
from src.stages.extract.recipe_extractor import RecipeExtractor
from src.stages.analyse.analyse import RecipeAnalyzer
import sqlalchemy
from src.models.page import Page
# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Multilingual recipe-related keywords for URL and content detection
RECIPE_KEYWORDS = {
    'url': [
        'recipe', 'recipes', 'recette', 'recettes', 'рецепт', 'рецепты', 
        'ricetta', 'ricette', 'rezept', 'rezepte', 'receta', 'recetas',
        'tarif', 'tarifler', 'レシピ', '食谱', '조리법', 'وصفة'
    ],
    'ingredients': [
        'ingredients', 'ingredient', 'ингредиенты', 'ингредиент', 
        'ingrédients', 'ingrédient', 'ingredientes', 'ingrediente',
        'ingredienti', 'zutaten', 'malzemeler', '材料', '配料', '재료'
    ],
    'instructions': [
        'instructions', 'steps', 'directions', 'method', 'preparation',
        'шаги', 'приготовление', 'инструкции', 'étapes', 'préparation',
        'paso', 'pasos', 'procedimento', 'zubereitung', 'hazırlanış',
        '作り方', '手順', '步骤', '조리 방법'
    ],
    'cooking': [
        'cooking', 'cook', 'cuisine', 'cuire', 'готовить', 'готовка',
        'cocinar', 'cucinare', 'kochen', 'pişirmek', '料理', '烹饪', '요리'
    ],
    'time': [
        'cooking time', 'prep time', 'время приготовления', 'время готовки',
        'temps de préparation', 'tiempo de preparación', 'tempo di preparazione',
        'vorbereitungszeit', 'hazırlama süresi', '調理時間', '准备时间', '조리 시간'
    ],
    'dish_types': [
        'dinner', 'lunch', 'breakfast', 'dessert', 'appetizer', 'snack',
        'обед', 'ужин', 'завтрак', 'десерт', 'закуска',
        'dîner', 'déjeuner', 'petit-déjeuner', 'dessert', 'entrée',
        'cena', 'comida', 'desayuno', 'postre', 'aperitivo',
        'abendessen', 'mittagessen', 'frühstück', 'nachtisch',
        'akşam yemeği', 'öğle yemeği', 'kahvaltı', 'tatlı'
    ],
    'common_foods': [
        'chicken', 'fish', 'beef', 'pork', 'pasta', 'rice', 'salad', 'soup',
        'курица', 'рыба', 'говядина', 'свинина', 'паста', 'рис', 'салат', 'суп',
        'poulet', 'poisson', 'boeuf', 'porc', 'pâtes', 'riz', 'salade', 'soupe',
        'pollo', 'pescado', 'carne', 'cerdo', 'arroz', 'ensalada', 'sopa',
        'tavuk', 'balık', 'et', 'makarna', 'pilav', 'salata', 'çorba'
    ]
}


class SiteExplorer:
    """Исследователь структуры сайта с поддержкой многоязычных рецептов"""
    
    def __init__(self, base_url: str, debug_mode: bool = True, use_db: bool = True, recipe_pattern: str = None,
                 max_errors: int = 3):
        """
        Args:
            base_url: Базовый URL сайта
            debug_mode: Если True, подключается к открытому Chrome с отладкой
            use_db: Если True, сохраняет данные в MySQL
            recipe_pattern: Regex паттерн для поиска URL с рецептами (опционально)
            max_errors: Максимальное количество ошибок подряд перед остановкой
        """
        self.base_url = base_url
        self.debug_mode = debug_mode
        self.use_db = use_db
        self.driver = None
        self.db = None
        self.site_id = None
        self.recipe_pattern = recipe_pattern
        self.recipe_regex = None
        self.request_count = 0  # Счетчик запросов для адаптивных пауз
        self.max_errors = max_errors
        self.analyzer = None
        
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
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}/"
        
        # Множества для отслеживания
        self.visited_urls: Set[str] = set()
        self.url_patterns: Dict[str, List[str]] = {}  # паттерн -> список URL
        self.failed_urls: Set[str] = set()
        self.referrer_map: Dict[str, str] = {}  # URL -> referrer URL (откуда пришли)
        self.successful_referrers: Set[str] = set()  # URLs страниц, которые привели к рецептам
        self.exploration_queue: List[tuple] = []  # Очередь URL для исследования: [(url, depth), ...]
        
        # Файлы для сохранения
        self.save_dir = os.path.join(config.PARSED_DIR, self.site_name,"exploration")
        os.makedirs(self.save_dir, exist_ok=True)
        
        self.state_file = os.path.join(self.save_dir, "exploration_state.json")
        self.patterns_file = os.path.join(self.save_dir, "url_patterns.json")
        
        # Подключение к БД
        if self.use_db:
            self.db = MySQlManager()
            if self.db.connect():
                self.site_id = self.db.create_or_get_site(
                    name=self.site_name,
                    base_url=base_url,
                    language=None  # Будет определен при парсинге
                )
                if self.site_id:
                    logger.info(f"Работа с сайтом ID: {self.site_id}")
                    
                    # Если паттерн не задан, загружаем из БД
                    if not recipe_pattern:
                        self.load_pattern_from_db()
                    
                    # Загружаем посещенные URL из БД
                    self.load_visited_urls_from_db()
                else:
                    logger.warning("Не удалось создать/получить ID сайта")
                    self.use_db = False
            else:
                logger.warning("Не удалось подключиться к БД, продолжаем без БД")
                self.use_db = False
        
        # Инициализация экстрактора для проверки и извлечения рецептов
        self.recipe_extractor = None
        if self.use_db and self.db:
            self.recipe_extractor = RecipeExtractor(self.db)


    def set_pattern(self, pattern: str):
        self.recipe_pattern = pattern
        try:
            self.recipe_regex = re.compile(pattern)
            logger.info(f"Используется regex паттерн для рецептов: {pattern}")
        except re.error as e:
            logger.error(f"Неверный regex паттерн: {e}")
            self.recipe_regex = None
    
    def load_pattern_from_db(self):
        """
        Загрузка regex паттерна рецептов из БД для данного сайта
        """
        if not self.use_db or not self.site_id:
            return
        
        try:
            session = self.db.get_session()
            
            sql = "SELECT recipe_pattern FROM sites WHERE id = :site_id"
            result = session.execute(sqlalchemy.text(sql), {"site_id": self.site_id})
            row = result.fetchone()
            
            if row and row[0]:
                pattern = row[0]
                self.recipe_pattern = pattern
                try:
                    self.recipe_regex = re.compile(pattern)
                    logger.info(f"Загружен паттерн из БД: {pattern}")
                except re.error as e:
                    logger.error(f"Неверный regex паттерн из БД: {e}")
                    self.recipe_regex = None
            else:
                logger.info("Паттерн рецептов не найден в БД")
            
            session.close()
            
        except Exception as e:
            logger.error(f"Ошибка загрузки паттерна из БД: {e}")
    
    def load_visited_urls_from_db(self):
        """
        Загрузка всех уже посещенных URL для данного сайта из БД
        """
        if not self.use_db or not self.site_id:
            return
        
        try:
            session = self.db.get_session()
            
            sql = "SELECT url, pattern FROM pages WHERE site_id = :site_id"
            result = session.execute(sqlalchemy.text(sql), {"site_id": self.site_id})
            rows = result.fetchall()
            
            loaded_count = 0
            for url, pattern in rows:
                if url:
                    self.visited_urls.add(url)
                    loaded_count += 1
                    
                    # Добавляем в паттерны
                    if pattern:
                        if pattern not in self.url_patterns:
                            self.url_patterns[pattern] = []
                        if url not in self.url_patterns[pattern]:
                            self.url_patterns[pattern].append(url)
            
            if loaded_count > 0:
                logger.info(f"Загружено {loaded_count} посещенных URL из БД")
                logger.info(f"Найдено {len(self.url_patterns)} уникальных паттернов")
            else:
                logger.info("В БД нет ранее посещенных URL для этого сайта")
            
            session.close()
            
        except Exception as e:
            logger.error(f"Ошибка загрузки посещенных URL из БД: {e}")
    
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
    
    def check_and_extract_recipe(self, url: str, pattern: str, page_index: int) -> bool:
        """
        Проверяет наличие рецепта на странице и извлекает полные данные с сохранением в БД
        
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
        if not (self.use_db and self.site_id):
            logger.warning(" БД не используется, пропускаем проверку рецепта")
            return False
            # Создаем объект Page для БД


        page = Page(site_id=self.site_id, 
                    url=url, 
                    pattern=pattern, 
                    html_path=self.save_page_as_file(pattern, page_index))


        
            
        # Извлекаем полные данные рецепта
        recipe_data = self.recipe_extractor.extract_and_update_page(page)
        
        # UPSERT
        upsert_sql = """
            INSERT INTO pages (
                site_id, url, pattern, html_path,
                is_recipe, confidence_score,
                dish_name, description, 
                ingredient, step_by_step,
                prep_time, cook_time, total_time,
                servings, difficulty_level,
                category, nutrition_info,
                notes, rating, tags, title, language, image_urls
            ) VALUES (
                :site_id, :url, :pattern, :html_path,
                :is_recipe, :confidence_score,
                :dish_name, :description,
                :ingredient, :step_by_step,
                :prep_time, :cook_time, :total_time,
                :servings, :difficulty_level,
                :category, :nutrition_info,
                :notes, :rating, :tags, :title, :language, :image_urls
            )
            ON DUPLICATE KEY UPDATE
                is_recipe = VALUES(is_recipe),
                confidence_score = VALUES(confidence_score),
                dish_name = VALUES(dish_name),
                description = VALUES(description),
                ingredient = VALUES(ingredient),
                step_by_step = VALUES(step_by_step),
                prep_time = VALUES(prep_time),
                cook_time = VALUES(cook_time),
                total_time = VALUES(total_time),
                servings = VALUES(servings),
                difficulty_level = VALUES(difficulty_level),
                category = VALUES(category),
                nutrition_info = VALUES(nutrition_info),
                notes = VALUES(notes),
                rating = VALUES(rating),
                tags = VALUES(tags),
                title = VALUES(title),
                language = VALUES(language),
                image_urls = VALUES(image_urls)
        """

        upsert_on_non_recipe = """
            INSERT INTO pages (
                site_id, url, pattern, html_path,
                is_recipe, confidence_score, title, language
            ) VALUES (
                :site_id, :url, :pattern, :html_path,
                :is_recipe, :confidence_score, :title, :language
            )
            ON DUPLICATE KEY UPDATE
                is_recipe = VALUES(is_recipe),
                confidence_score = VALUES(confidence_score), 
                title = VALUES(title),
                language = VALUES(language)
            """
        
        # Подготовка данных
        upsert_data = {
            "site_id": self.site_id,
            "url": url,
            "pattern": pattern,
            "html_path": page.html_path,
            "title": self.driver.title,
            "language": self.driver.execute_script("return document.documentElement.lang") or 'unknown',
            **recipe_data
        }

        if recipe_data.get("is_recipe", False) is True:
            self.mark_page_as_successful(url)
        else:
            upsert_sql = upsert_on_non_recipe

        try:
            with self.db.get_session() as session:
                session.execute(sqlalchemy.text(upsert_sql), upsert_data)
                session.commit()
        except Exception as e:
            logger.error(f"Ошибка сохранения страницы в БД: {e}")
            return False
        
        dish_name = recipe_data.get('dish_name', 'Unknown')
        logger.info(f"  ✓ Рецепт '{dish_name}' сохранен в БД")
        return True
        

    def get_recipe_likelihood_score(self, url: str, link_text: str = "", context_text: str = "") -> float:
        """
        Вычисляет вероятность того, что URL ведет к рецепту (0-100)
        
        Args:
            url: URL для анализа
            link_text: Текст ссылки (anchor text)
            context_text: Окружающий текст вокруг ссылки
            
        Returns:
            Оценка вероятности от 0 до 100
        """
        score = 0.0
        url_lower = url.lower()
        link_text_lower = link_text.lower()
        context_lower = context_text.lower()
        
        # 1. Проверка URL (максимум 40 баллов)
        # Прямые совпадения с recipe keywords в URL
        url_recipe_matches = sum(1 for kw in RECIPE_KEYWORDS['url'] if kw in url_lower)
        score += min(url_recipe_matches * 15, 40)  # До 40 баллов
        
        # Паттерны URL с номерами (часто рецепты)
        if re.search(r'/\d{4,}', url) or re.search(r'recipe[-_]\d+', url_lower):
            score += 10
        
        # 2. Проверка текста ссылки (максимум 30 баллов)
        # Прямые совпадения с keywords в тексте ссылки
        for category, keywords in RECIPE_KEYWORDS.items():
            matches = sum(1 for kw in keywords if kw in link_text_lower)
            if category == 'url':
                score += min(matches * 10, 20)
            elif category in ['ingredients', 'instructions']:
                score += min(matches * 5, 10)
        
        # Названия блюд в тексте ссылки
        dish_matches = sum(1 for kw in RECIPE_KEYWORDS['common_foods'] if kw in link_text_lower)
        score += min(dish_matches * 3, 10)
        
        # 3. Проверка контекста (максимум 20 баллов)
        context_recipe_score = 0
        for category in ['ingredients', 'instructions', 'cooking', 'time']:
            matches = sum(1 for kw in RECIPE_KEYWORDS[category] if kw in context_lower)
            context_recipe_score += matches
        score += min(context_recipe_score * 2, 20)
        
        # 4. Бонусы за комбинации (максимум 10 баллов)
        # URL содержит recipe + текст ссылки содержит еду
        if any(kw in url_lower for kw in RECIPE_KEYWORDS['url']):
            if any(kw in link_text_lower for kw in RECIPE_KEYWORDS['common_foods']):
                score += 10
        
        return min(score, 100)  # Ограничиваем максимумом 100
    

    def quick_recipe_check(self, soup: BeautifulSoup = None) -> tuple:
        """
        Быстрая проверка страницы на наличие рецепта без полной экстракции
        
        Args:
            soup: BeautifulSoup объект (если None, парсит текущую страницу)
            
        Returns:
            (has_recipe, confidence): True если вероятно рецепт, оценка уверенности 0-100
        """
        if soup is None:
            html = self.driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
        
        confidence = 0
        
        # 1. Проверка JSON-LD schema (30 баллов)
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    schema_type = data.get('@type', '')
                    if 'Recipe' in str(schema_type):
                        confidence += 30
                        break
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and 'Recipe' in str(item.get('@type', '')):
                            confidence += 30
                            break
            except (json.JSONDecodeError, AttributeError):
                continue
        
        # 2. Проверка meta тегов (20 баллов)
        og_type = soup.find('meta', property='og:type')
        if og_type and 'recipe' in og_type.get('content', '').lower():
            confidence += 20
        
        # 3. Проверка семантических тегов (20 баллов)
        recipe_indicators = [
            soup.find('div', class_=re.compile(r'recipe', re.I)),
            soup.find('article', class_=re.compile(r'recipe', re.I)),
            soup.find(attrs={'itemtype': re.compile(r'Recipe', re.I)}),
        ]
        if any(recipe_indicators):
            confidence += 20
        
        # 4. Проверка структуры контента (30 баллов)
        text = soup.get_text().lower()
        
        # Ингредиенты
        has_ingredients = any(kw in text for kw in RECIPE_KEYWORDS['ingredients'][:5])
        if has_ingredients:
            confidence += 10
        
        # Инструкции
        has_instructions = any(kw in text for kw in RECIPE_KEYWORDS['instructions'][:5])
        if has_instructions:
            confidence += 10
        
        # Время приготовления
        has_time = any(kw in text for kw in RECIPE_KEYWORDS['time'][:5])
        if has_time:
            confidence += 5
        
        # Типичные продукты
        food_count = sum(1 for kw in RECIPE_KEYWORDS['common_foods'][:20] if kw in text)
        confidence += min(food_count, 5)
        
        # Решение: рецепт если уверенность >= 40
        return (confidence >= 40, confidence)
    
    
    def should_explore_url(self, url: str) -> bool:
        """
        Проверка, нужно ли исследовать данный URL
        
        Args:
            url: URL для проверки            
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
                    time.sleep(random.uniform(0.3, 0.5))
                
                # Быстрая прокрутка в конец
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(0.3, 0.6))
            else:
                # Обычная прокрутка
                num_scrolls = random.randint(3, 5)
                scroll_step = total_height // num_scrolls
                
                current_position = 0
                for i in range(num_scrolls):
                    current_position += scroll_step
                    self.driver.execute_script(f"window.scrollTo(0, {current_position});")
                    time.sleep(random.uniform(0.4, 0.8))
                
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(0.5, 1.0))
            
        except Exception as e:
            logger.debug(f"Ошибка при прокрутке: {e}")


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
        try:
            
            # Получение метаданных
            title = self.driver.title
            language = self.driver.execute_script("return document.documentElement.lang") or 'unknown'
            filepath = self.save_page_as_file(pattern, page_index)
            filename = os.path.basename(filepath)
            # Сохранение в БД
            if self.use_db and self.site_id:
                page_id = self.db.save_page(
                    site_id=self.site_id,
                    url=url,
                    pattern=pattern,
                    title=title,
                    language=language,
                    html_path=os.path.relpath(filepath),
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
            logger.error(f"Ошибка извлечения ссылок: {e}")
            return []
    

    def extract_links_with_priority(self) -> List[tuple]:
        """
        Извлечение ссылок с приоритизацией на основе многоязычных признаков рецептов
        
        Returns:
            Список кортежей (url, likelihood_score, link_text) отсортированных по убыванию вероятности
        """
        try:
            soup = BeautifulSoup(self.driver.page_source, 'lxml')
            links_with_scores = []
            
            for link in soup.find_all('a', href=True):
                href = link['href']
                absolute_url = urljoin(self.driver.current_url, href)
                
                # Очистка от якорей и параметров
                clean_url = absolute_url.split('#')[0].split('?')[0]
                
                if not (clean_url and self.is_same_domain(clean_url)):
                    continue
                
                # Извлечение контекста ссылки
                link_text = link.get_text(strip=True)
                
                # Получение окружающего текста (родитель + соседи)
                context_parts = []
                
                # Текст родительского элемента
                parent = link.parent
                if parent:
                    # Текст до ссылки
                    for sibling in parent.find_all_previous(string=True, limit=3):
                        if sibling.strip():
                            context_parts.insert(0, sibling.strip())
                    
                    # Текст после ссылки
                    for sibling in parent.find_all_next(string=True, limit=3):
                        if sibling.strip():
                            context_parts.append(sibling.strip())
                
                context_text = ' '.join(context_parts)[:200]  # Ограничиваем длину
                
                # Вычисляем вероятность
                score = self.get_recipe_likelihood_score(clean_url, link_text, context_text)
                
                links_with_scores.append((clean_url, score, link_text))
            
            # Удаляем дубликаты (оставляем с максимальным score)
            unique_links = {}
            for url, score, text in links_with_scores:
                if url not in unique_links or score > unique_links[url][0]:
                    unique_links[url] = (score, text)
            
            # Формируем финальный список
            result = [(url, score, text) for url, (score, text) in unique_links.items()]
            
            # Сортируем по убыванию вероятности
            result.sort(key=lambda x: x[1], reverse=True)
            
            logger.info(f"Найдено {len(result)} уникальных ссылок")
            if result:
                top_5 = result[:5]
                logger.info("Топ-5 ссылок по вероятности:")
                for url, score, text in top_5:
                    logger.info(f"  [{score:.0f}] {text[:30]}... -> {url[:60]}...")
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка извлечения ссылок с приоритетом: {e}")
            return []
    
    
    def  export_state(self) -> dict:
        """Экспорт состояния для передачи в другой экземпляр
        
        Returns:
            Словарь с полным состоянием explorer
        """
        return {
            'base_url': self.base_url,
            'recipe_pattern': self.recipe_pattern,
            'visited_urls': list(self.visited_urls),
            'url_patterns': dict(self.url_patterns),
            'failed_urls': list(self.failed_urls),
            'referrer_map': dict(self.referrer_map),
            'successful_referrers': list(self.successful_referrers),
            'exploration_queue': list(self.exploration_queue),
            'request_count': self.request_count,
            'site_id': self.site_id,
            'site_name': self.site_name,
            'exported_at': time.strftime('%Y-%m-%d %H:%M:%S')
        }
    
    def add_helper_urls(self, urls: List[str], depth: int = 0):
        """
        Добавляет вспомогательные URL в очередь исследования
        
        Args:
            urls: Список URL для добавления
            depth: Начальная глубина для этих URL (по умолчанию 0)
        """
        added_count = 0
        for url in urls:
            # Проверяем что URL того же домена
            if not self.is_same_domain(url):
                logger.warning(f"Пропущен URL другого домена: {url}")
                continue
            
            # Проверяем что URL еще не посещен и не в очереди
            if url not in self.visited_urls and (url, depth) not in self.exploration_queue:
                self.exploration_queue.append((url, depth))
                added_count += 1
                logger.info(f"  + Добавлен в очередь: {url}")
        
        # Сортируем очередь по приоритету
        self.exploration_queue.sort(key=lambda x: self.get_url_priority(x[0]))
        
        logger.info(f"Добавлено {added_count} вспомогательных URL в очередь")
        logger.info(f"Всего в очереди: {len(self.exploration_queue)} URL")
    
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
        if new_pattern and new_pattern != self.recipe_pattern:
            self.recipe_pattern = new_pattern
            try:
                self.recipe_regex = re.compile(new_pattern)
                logger.info(f"Обновлен regex паттерн: {new_pattern}")
            except re.error as e:
                logger.error(f"Неверный regex паттерн при импорте: {e}")
        
        logger.info(f"Состояние импортировано: {len(self.visited_urls)} посещенных URL, "
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
        
        logger.info(f"Состояние сохранено: {len(self.visited_urls)} посещено, {len(self.url_patterns)} паттернов")
    
    def load_state(self) -> bool:
        """Загрузка сохраненного состояния из файла"""
        if not os.path.exists(self.state_file):
            logger.info("Файл состояния не найден, начинаем с нуля")
            return False
        
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            
            self.import_state(state)
            
            logger.info("Загружено состояние:")
            logger.info(f"  Посещено URL: {len(self.visited_urls)}")
            logger.info(f"  Найдено паттернов: {len(self.url_patterns)}")
            logger.info(f"  URL в очереди: {len(self.exploration_queue)}")
            logger.info(f"  Успешных источников: {len(self.successful_referrers)}")
            logger.info(f"  Ошибок: {len(self.failed_urls)}")
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка загрузки состояния: {e}")
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
        """
        referrer = self.referrer_map.get(current_url)
        if referrer:
            self.successful_referrers.add(referrer)
            logger.info(f"  ✓ Источник отмечен как успешный: {referrer}")
    

    def explore_multilingual(self, max_urls: int = 100, max_depth: int = 3, 
                            min_likelihood: float = 30.0, quick_check: bool = True) -> int:
        """
        Многоязычное исследование сайта с приоритизацией рецептов
        
        Args:
            max_urls: Максимальное количество URL для посещения
            max_depth: Максимальная глубина обхода
            min_likelihood: Минимальная вероятность для посещения URL (0-100)
            quick_check: Использовать быструю проверку на рецепт перед полной экстракцией
            
        Returns:
            Количество успешно найденных рецептов
        """
        logger.info(f"🌍 Начало многоязычного исследования сайта: {self.base_url}")
        logger.info(f"Параметры: max_urls={max_urls}, max_depth={max_depth}, min_likelihood={min_likelihood}")
        
        # Очередь с приоритетами: (priority_score, url, depth, link_text)
        import heapq
        priority_queue = []
        
        # Стартуем с базового URL
        heapq.heappush(priority_queue, (-100, self.base_url, 0, "Home"))
        
        urls_explored = 0
        recipes_found = 0
        
        while priority_queue and urls_explored < max_urls:
            # Извлекаем URL с наивысшим приоритетом (heapq - min-heap, поэтому отрицательные)
            neg_priority, current_url, depth, link_text = heapq.heappop(priority_queue)
            priority = -neg_priority
            
            # Проверка глубины
            if depth > max_depth:
                continue
            
            # Проверка, нужно ли посещать
            if current_url in self.visited_urls:
                continue
            
            if not self.should_explore_url(current_url):
                continue
            
            # Пропускаем URL с низкой вероятностью (кроме первого уровня)
            if depth > 0 and priority < min_likelihood:
                logger.debug(f"Пропущен URL с низкой вероятностью [{priority:.0f}]: {current_url}")
                continue
            
            try:
                logger.info(f"[{urls_explored + 1}/{max_urls}] [{priority:.0f}] {link_text[:30]}...")
                logger.info(f"  URL: {current_url}")
                logger.info(f"  Глубина: {depth}")
                
                # Переход на страницу
                try:
                    self.driver.get(current_url)
                except TimeoutException:
                    logger.warning(f"Timeout при загрузке {current_url}")
                    continue
                
                # Ожидание загрузки
                try:
                    WebDriverWait(self.driver, 15).until(
                        lambda d: d.execute_script('return document.readyState') == 'complete'
                    )
                except TimeoutException:
                    logger.warning("Timeout при загрузке страницы, продолжаем")
                
                # Адаптивная задержка
                self.request_count += 1
                delay = random.uniform(1.0, 2.0) if self.request_count % 10 != 0 else random.uniform(3, 5)
                time.sleep(delay)
                
                # Прокрутка страницы
                self.slow_scroll_page(quick_mode=True)
                
                # Отмечаем как посещенный
                self.visited_urls.add(current_url)
                urls_explored += 1
                
                # Получение паттерна
                pattern = self.get_url_pattern(current_url)
                if pattern not in self.url_patterns:
                    self.url_patterns[pattern] = []
                
                page_index = len(self.url_patterns[pattern]) + 1
                self.url_patterns[pattern].append(current_url)
                
                # Быстрая проверка на рецепт (если включено)
                is_recipe = False
                confidence = 0
                
                if quick_check:
                    is_recipe, confidence = self.quick_recipe_check()
                    logger.info(f"  Быстрая проверка: {'✓ РЕЦЕПТ' if is_recipe else '✗ не рецепт'} (уверенность: {confidence})")
                
                # Если похоже на рецепт - делаем полную экстракцию
                if is_recipe and self.recipe_extractor:
                    if self.check_and_extract_recipe(current_url, pattern, page_index):
                        recipes_found += 1
                        logger.info(f"  🎯 Найдено рецептов: {recipes_found}")
                        
                        # Обновляем паттерн если нужно
                        if self.recipe_regex is None or not self.is_recipe_url(current_url):
                            logger.info("  📝 Обновление паттерна рецептов...")
                            if self.analyzer is None:
                                self.analyzer = RecipeAnalyzer(
                                    site_id=self.site_id,
                                    db_manager=self.db,
                                    sample_size=10
                                )
                            new_pattern = self.analyzer.analyse_recipe_page_pattern(site_id=self.site_id)
                            if new_pattern:
                                self.set_pattern(new_pattern)
                
                # Извлечение новых ссылок с приоритетами
                new_links = self.extract_links_with_priority()
                logger.info(f"  Найдено ссылок: {len(new_links)}")
                
                # Добавляем в приоритетную очередь
                added = 0
                for link_url, link_score, link_txt in new_links:
                    if link_url not in self.visited_urls and link_score >= min_likelihood:
                        # Запоминаем источник
                        if link_url not in self.referrer_map:
                            self.referrer_map[link_url] = current_url
                        
                        # Добавляем в очередь (отрицательный приоритет для max-heap)
                        heapq.heappush(priority_queue, (-link_score, link_url, depth + 1, link_txt))
                        added += 1
                
                logger.info(f"  Добавлено в очередь: {added} ссылок (мин. вероятность {min_likelihood})")
                
                # Периодическое сохранение
                if urls_explored % 10 == 0:
                    self.save_state()
                    logger.info(f"💾 Состояние сохранено: {urls_explored} URL, {recipes_found} рецептов")
                
            except Exception as e:
                logger.error(f"Ошибка при обработке {current_url}: {e}")
                self.failed_urls.add(current_url)
                continue
        
        # Финальное сохранение
        self.save_state()
        
        logger.info("\n" + "="*60)
        logger.info("🎉 Многоязычное исследование завершено!")
        logger.info(f"Посещено URL: {urls_explored}")
        logger.info(f"Найдено рецептов: {recipes_found}")
        logger.info(f"Найдено паттернов: {len(self.url_patterns)}")
        logger.info(f"Успешных источников: {len(self.successful_referrers)}")
        logger.info(f"Ошибок: {len(self.failed_urls)}")
        logger.info("="*60 + "\n")
        
        return recipes_found
    
    
    def explore(self, max_urls: int = 100, max_depth: int = 3, session_urls: bool = True, 
                check_pages_with_extractor:bool = False,
                forbid_success_mark: bool = False,
                check_url: bool = False) -> int:
        """
        Исследование структуры сайта
        
        Args:
            max_urls: Максимальное количество URL для посещения
            max_depth: Максимальная глубина обхода
            session_urls: Если True, то не учитывает старые посещенные URL при подсчтее max urls
            forbid_success_mark: Если True, не отмечает успешные источники (для случаев отсутсвия паттерна)
            check_pages_with_extractor: Если True, проверяет каждую страницу экстрактором рецептов
            check_url: Если True, проверяет каждый на реджекс паттерн перед экстракцией (парамтер касается только экстракции)
        Returns:
            urls_explored: Количество успешно посещенных URL в этой сессии
        """
        logger.info(f"Начало исследования сайта: {self.base_url}")
        logger.info(f"Цель: найти до {max_urls} уникальных паттернов URL")
        
        # Очередь URL для обхода: (url, depth)
        # Если есть сохраненная очередь - используем её, иначе начинаем с base_url
        if self.exploration_queue:
            queue = list(self.exploration_queue)
            logger.info(f"Продолжаем с сохраненной очередью: {len(queue)} URL")
        else:
            queue = [(self.base_url, 0)]
            logger.info("Начинаем новое исследование")
        
        urls_explored = len(self.visited_urls)

        if session_urls:
            urls_explored = 0  # Считаем только в этой сессии
        
        # Логирование начальной стратегии
        initial_strategy = "глубина (паттерн рецептов не найден)" if self.recipe_regex is None else "ширина (паттерн рецептов найден)"
        logger.info(f"Стратегия обхода: {initial_strategy}")

        err_count = 0  # Счетчик ошибок подряд
        last_strategy = self.recipe_regex is not None  # Для отслеживания переключений

        while queue and urls_explored < max_urls:
            # Выбираем стратегию: если паттерна нет - идем вглубь (LIFO), иначе вширь (FIFO)
            has_recipe_pattern = self.recipe_regex is not None
            
            # Логируем переключение стратегии
            if has_recipe_pattern != last_strategy:
                new_strategy = "ширина (паттерн найден)" if has_recipe_pattern else "глубина (паттерн потерян)"
                logger.info(f"⚡ Переключение стратегии: {new_strategy}")
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
            if not self.should_explore_url(current_url) and urls_explored > 0 and not check_pages_with_extractor:
                continue
            
            try:
                logger.info(f"[{urls_explored + 1}/{max_urls}] Переход на: {current_url}")
                logger.info(f"  Паттерн: {pattern}, Глубина: {depth}")
                
                # Переход на страницу
                try:
                    self.driver.get(current_url)
                except TimeoutException:
                    logger.warning(f"Timeout при загрузке {current_url}")
                
                # Ожидание загрузки (сокращено до 15 сек)
                try:
                    WebDriverWait(self.driver, 15).until(
                        lambda d: d.execute_script('return document.readyState') == 'complete'
                    )
                except TimeoutException:
                    logger.warning("Timeout при загрузке страницы, продолжаем")
                
                # Адаптивная задержка: короче в начале, длиннее после каждых 10 запросов
                self.request_count += 1
                if self.request_count % 10 == 0:
                    # Каждые 10 запросов - более длинная пауза для снижения подозрительности
                    delay = random.uniform(3, 5)
                    logger.info(f"  Длинная пауза после {self.request_count} запросов: {delay:.1f}с")
                else:
                    # Обычная короткая пауза
                    delay = random.uniform(0.8, 1.5)
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
                            logger.info("  Обновление паттерна URL, так как найден рецепт на странице")
                            if self.analyzer is None:
                                self.analyzer = RecipeAnalyzer(
                                    site_id=self.site_id,
                                    db_manager=self.db,
                                    sample_size=10
                                )
                            pattern =  self.analyzer.analyse_recipe_page_pattern(site_id=self.site_id)
                            
                # Если задан regex паттерн - сохраняем рецепт, иначе сохраняем все страницы
                elif self.should_extract_recipe(current_url):
                    if not forbid_success_mark: self.mark_page_as_successful(current_url)
                    self.save_page_html(current_url, pattern, page_index)

                # Извлечение новых ссылок
                new_links = self.extract_links()
                logger.info(f"  Найдено ссылок: {len(new_links)}")
                
                # Добавление новых ссылок в очередь с отслеживанием источника
                # Если паттерн рецептов не найден - приоритизируем глубину (DFS)
                # Если паттерн найден - используем ширину (BFS)
                has_recipe_pattern = self.recipe_regex is not None
                
                for link in new_links:
                    if self.should_explore_url(link) or len(queue) == 0:
                        # Запоминаем источник перехода
                        if link not in self.referrer_map:
                            self.referrer_map[link] = current_url
                        
                        # DFS (вглубь): добавляем в начало очереди если паттерна нет
                        # BFS (вширь): добавляем в конец очереди если паттерн есть
                        if has_recipe_pattern:
                            queue.append((link, depth + 1))
                        else:
                            queue.insert(0, (link, depth + 1))
                
                # Сортируем очередь по приоритету только если паттерн найден
                if has_recipe_pattern:
                    queue.sort(key=lambda x: self.get_url_priority(x[0]))
                
                # Периодическое сохранение
                if urls_explored % 10 == 0:
                    self.exploration_queue = queue  # Сохраняем текущую очередь
                    self.save_state()
                
            except Exception as e:
                logger.error(f"Ошибка при обработке {current_url}: {e}")
                self.failed_urls.add(current_url)
                self.exploration_queue = queue  # Сохраняем очередь при ошибке
                self.save_state()  # Сохранение при ошибке
                err_count += 1
                if err_count >= self.max_errors:
                    logger.error(f"Превышено максимальное количество ошибок подряд ({self.max_errors}), остановка исследования.")
                    break
                continue
        
        # Финальное сохранение с текущей очередью
        self.exploration_queue = queue
        self.save_state()
        
        logger.info(f"\n{'='*60}")
        logger.info("Исследование завершено" if err_count < self.max_errors else "Исследование остановлено из-за ошибок")
        logger.info(f"Результаты сохранены в: {self.save_dir}")
        logger.info(f"  - {self.state_file} - состояние")
        logger.info(f"  - {self.patterns_file} - найденные паттерны")
        logger.info(f"  - *.html - сохраненные страницы ({sum(len(urls) for urls in self.url_patterns.values())} файлов)")
        logger.info("Для продолжения используйте: explorer.load_state() или explorer.import_state(state)")
        logger.info(f"{'='*60}")
        return urls_explored

    
    def close(self):
        """Закрытие браузера и БД"""
        if self.driver and not self.debug_mode:
            self.driver.quit()
        if self.db:
            self.db.close()
        logger.info("Готово")


def explore_site(url: str, max_urls: int = 1000, max_depth: int = 4, recipe_pattern: str = None,
                 check_pages_with_extractor: bool = False,
                 forbid_success_mark: bool = False,
                 check_url: bool = False):
    """
    Функция для исследования сайта с обработкой ошибок и прерываний
    
    Args:
        explorer: Объект SiteExplorer
        max_urls: Максимальное количество URL для исследования
        max_depth: Максимальная глубина исследования
    """
    urls_explored = 0
    try:
        # Цикл для продолжения исследования до достижения max_urls (на случай ошибок или прерываний)
        while urls_explored < max_urls:
            explorer = SiteExplorer(url, debug_mode=True, use_db=True, recipe_pattern=recipe_pattern)
            explorer.connect_to_chrome()
            explorer.load_state()
            explored = explorer.explore(max_urls=max_urls, max_depth=max_depth, check_url=check_url, check_pages_with_extractor=check_pages_with_extractor, forbid_success_mark=forbid_success_mark)
            urls_explored += explored
            logger.info(f"Всего исследовано URL: {urls_explored}/{max_urls}")
    except KeyboardInterrupt:
        logger.info("\nПрервано пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
    finally:
        explorer.close()

def main():
    url = "https://www.allrecipes.com/"
    # паттерн формируется после анализа несколкьих URL
    search_pattern = "(^/recipe/\d+/[a-z0-9-]+/?$)|(^/[a-z0-9-]+-recipe-\d+/?$)"
    max_depth = 3
    
    explorer = SiteExplorer(url, debug_mode=True, use_db=True, recipe_pattern=search_pattern)
    
    try:
        #isR = explorer.is_recipe_url("https://www.allrecipes.com/recipe/23439/perfect-pumpkin-pie/")
        explorer.connect_to_chrome()
        explorer.explore(max_urls=3, max_depth=max_depth)

        explorer.explore(max_urls=3, max_depth=max_depth, session_urls=True)
    except KeyboardInterrupt:
        logger.info("\nПрервано пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        sys.exit(1)
    finally:
        explorer.close()


if __name__ == "__main__":
    main()
