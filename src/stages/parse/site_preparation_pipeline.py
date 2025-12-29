"""
Pipeline для автоматической подготовки данных сайта и поиска паттернов рецептов
"""

import logging
import sys
import os
import json
import shutil
from pathlib import Path
from typing import Optional, List
from urllib.parse import urlparse
from selenium import webdriver
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.stages.parse.explorer import SiteExplorer, run_explorer
from src.stages.analyse.analyse import RecipeAnalyzer
from src.repositories.site import SiteRepository
from src.repositories.page import PageRepository
from src.models.site import SiteORM, get_name_base_url_from_url

logger = logging.getLogger(__name__)


class SitePreparationPipeline:
    """
    Pipeline для подготовки данных сайта перед созданием парсера
    
    Выполняет:
    1. Исследование структуры сайта (explorer)
    2. Анализ страниц и поиск рецептов (analyzer)
    3. Определение паттерна URL с рецептами
    """
    
    def __init__(self, 
                 debug_port: int = 9222,
                 batch_size: int = 30,
                 max_depth: int = 4,
                 max_urls_per_pattern: int = 4, # рекомендуется ставить на 1 больше чем min_recipes
                 min_recipes: int = 3,
                 preprocessed_recipe_folder: str = "preprocessed"):
        """
        Args:
            debug_port: Порт для подключения к Chrome
            batch_size: Размер одного батча исследования
            max_depth: Максимальная глубина обхода
            max_urls_per_pattern: Лимит URL на паттерн при первичном сборе
            min_recipes: Минимальное количество рецептов для поиска паттерна и для признания сайта сайтом с рецептами
        """
        self.debug_port = debug_port
        self.batch_size = batch_size
        self.max_depth = max_depth
        self.max_urls_per_pattern = max_urls_per_pattern
        self.min_recipes = min_recipes
        self.preprocessed_recipe_folder = preprocessed_recipe_folder
        self.site_repository = SiteRepository()
        self.page_repository = PageRepository()
        self.analyzer = RecipeAnalyzer()
        logger.info(f"Pipeline инициализирован: batch={batch_size}, depth={max_depth}, "
                   f"min_recipes={min_recipes}")
        
    def _is_preparation_required(self, site_orm: SiteORM) -> bool:
        """
        Проверка необходимости подготовки сайта
        
        Логика:
        1. Если рецептов >= min_recipes И есть паттерн → подготовка не нужна
        2. Если рецептов >= min_recipes НО нет паттерна → установить паттерн и завершить
        3. Если рецептов < min_recipes → продолжить подготовку
        
        Args:
            site_id: ID сайта
        
        Returns:
            (is_required, message): 
                - True если нужна подготовка, False если можно завершить
                - message: причина решения
        """
        logger.info(f"→ Проверка необходимости подготовки для сайта ID={site_orm.id}...")
        

        # Считаем количество рецептов
        recipes_count = self.page_repository.count_recipes_by_site(site_orm.id)
        has_pattern = bool(site_orm.pattern)
        
        logger.info(f"  Найдено рецептов: {recipes_count}")
        logger.info(f"  Паттерн установлен: {'Да' if has_pattern else 'Нет'}")
        
        # Случай 1: Есть достаточно рецептов И есть паттерн → готово
        if recipes_count >= self.min_recipes and has_pattern:
            message = (f"✓ Сайт уже подготовлен!\n"
                      f"  Рецептов: {recipes_count} (требуется >= {self.min_recipes})\n"
                      f"  Паттерн: {site_orm.pattern}")
            logger.info(message)
            # Создаем или пересоздаем тестовые данные на вский случай
            self.make_test_data(site_orm)
            return False
        
        # Случай 2: Есть достаточно рецептов НО нет паттерна → найти и установить паттерн
        if recipes_count >= self.min_recipes and not has_pattern:
            logger.info(f"→ Найдено {recipes_count} рецептов, но паттерн не установлен")
            logger.info("→ Попытка определить паттерн...")
            
            try:
                pattern = self.analyzer.analyse_recipe_page_pattern(site_id=site_orm.id)
                
                if pattern:
                    message = (f"✓ Паттерн успешно установлен!\n"
                              f"  Рецептов: {recipes_count}\n"
                              f"  Паттерн: {pattern}\n"
                              f"  Подготовка завершена")
                    logger.info(message)
                    
                    # Создаем тестовые данные после установки паттерна
                    self.make_test_data(site_orm)
                    
                    return False
                else:
                    message = (f"⚠ Не удалось определить паттерн из {recipes_count} рецептов\n"
                              f"Требуется дополнительное исследование")
                    logger.warning(message)
                    return True
                    
            except Exception as e:
                logger.error(f"Ошибка при определении паттерна: {e}")
                return True
        
        # Случай 3: Недостаточно рецептов → продолжить исследование
        message = (f"→ Требуется дополнительное исследование\n"
                  f"  Текущее количество рецептов: {recipes_count}\n"
                  f"  Требуется минимум: {self.min_recipes}\n"
                  f"  Паттерн: {'установлен' if has_pattern else 'не установлен'}")
        logger.info(message)
        return True
    
    def prepare_site(self, 
                    url: str,
                    max_pages: int = 150,
                    driver: Optional[webdriver.Chrome] = None,
                    custom_logger: Optional[logging.Logger] = None) -> bool:
        """
        Подготовка данных для создания парсера рецептов
        
        Процесс:
        0. Проверка необходимости подготовки (если сайт существует)
        1. Первичное исследование (batch_size страниц)
        2. Анализ найденных страниц
        3. Поиск паттерна рецептов
        4. Дополнительные батчи до нахождения паттерна или max_pages
        
        Args:
            url: Базовый URL сайта
            helper_links: Вспомогательные ссылки для начала
            max_pages: Максимальное количество страниц для исследования
        
        Returns:
            site_found: bool - True если сайт подготовлен и паттерн найден, False иначе
        """
        if custom_logger:
            logger = custom_logger
        else: 
            logger = logging.getLogger(__name__)
        logger.info(f"\n{'='*70}")
        logger.info(f"НАЧАЛО ПОДГОТОВКИ САЙТА: {url}")
        logger.info(f"{'='*70}")
        logger.info(f"Параметры: batch={self.batch_size}, max_depth={self.max_depth}, "
                   f"max_pages={max_pages}")
        
        # Проверяем, существует ли сайт и нужна ли подготовка
        name, _ = get_name_base_url_from_url(url)
        
        site_orm = self.site_repository.get_by_name(name)
        if site_orm is None:
            site_orm = self.site_repository.get_by_name(name)
        if site_orm:
            logger.info(f"\n{'='*60}")
            logger.info("ШАГ 0: Проверка необходимости подготовки")
            logger.info(f"{'='*60}")
            
            is_required = self._is_preparation_required(site_orm)
            if not is_required:
                logger.info(f"\n{'='*70}")
                logger.info("ПОДГОТОВКА НЕ ТРЕБУЕТСЯ")
                logger.info(f"{'='*70}\n")
                self.site_repository.mark_site_as_searched(site_orm.id)
                return True
        
        # Создаем explorer для исследования
        explorer = SiteExplorer(
            url, 
            debug_mode=True, 
            debug_port=self.debug_port,
            max_urls_per_pattern=self.max_urls_per_pattern,
            driver=driver,
            custom_logger=logger
        )

        if site_orm.search_url:
            explorer.add_helper_urls([site_orm.search_url], depth=1)
        
        # Первичное исследование
        logger.info(f"\n{'='*60}")
        logger.info("ШАГ 1: Первичное исследование сайта")
        logger.info(f"{'='*60}")
        
        run_explorer(explorer, max_urls=self.batch_size, max_depth=self.max_depth)
        
        site_id = explorer.site.id
        state = explorer.export_state()
        
        logger.info(f"✓ Сайт создан в БД: ID={site_id}")
        
        # Первичный анализ
        logger.info(f"\n{'='*60}")
        logger.info("ШАГ 2: Первичный анализ страниц")
        logger.info(f"{'='*60}")
        
        try:
            recipes_found = self.analyzer.analyze_all_pages(
                site_id=site_id,
                filter_by_title=True,
                stop_analyse=self.min_recipes
            )

            if recipes_found == 0: # по идее должен бвть хотя бы 1 рецепт по первой ссылке, если его нет, то выходим
                logger.warning("✗ Не найдено рецептов на сайте после первичного анализа")
                explorer.close()
                self.site_repository.mark_site_as_searched(site_orm.id)
                return False
            
            logger.info(f"✓ Найдено рецептов: {recipes_found}")
            
            # Если нашли рецепты - ищем паттерн, для поиска паттерна хватит и 2 рецептов на первый раз
            if recipes_found > 1:
                pattern = self._try_find_pattern(site_id, explorer)
                if pattern and recipes_found >= self.min_recipes:
                    logger.info(f"\n{'='*70}")
                    logger.info("✓ УСПЕХ: Паттерн найден после первичного анализа")
                    logger.info(f"  Паттерн: {pattern}")
                    logger.info(f"  Сайт ID: {site_id}")
                    logger.info(f"{'='*70}\n")
                    
                    # Создаем тестовые данные
                    self.make_test_data(site_orm)
                    
                    explorer.close()
                    self.site_repository.mark_site_as_searched(site_orm.id)
                    return True
            
            # Дополнительные батчи
            batches_completed = 1
            total_pages = self.batch_size
            
            while total_pages < max_pages:
                batch_num = batches_completed + 1
                next_batch_size = min(self.batch_size, max_pages - total_pages)
                
                logger.info(f"\n{'='*60}")
                logger.info(f"ШАГ {batch_num + 1}: Дополнительное исследование (батч #{batch_num})")
                logger.info(f"Страницы: {total_pages + 1} - {total_pages + next_batch_size}")
                logger.info(f"{'='*60}")
                
                # Продолжаем исследование
                run_explorer(explorer, max_urls=next_batch_size, max_depth=self.max_depth)
                total_pages += next_batch_size
                
                # Экспортируем состояние
                state = explorer.export_state()
                
                # Анализируем новые страницы
                recipes_found = self.analyzer.analyze_all_pages(
                    site_id=site_id,
                    filter_by_title=True,
                    stop_analyse=self.min_recipes
                )
                
                logger.info(f"✓ Всего найдено рецептов: {recipes_found}")
                
                # Если паттерн был, но рецепты не находятся - сбрасываем
                if recipes_found == 0 and explorer.site.pattern:
                    logger.warning("⚠ Паттерн не работает, сбрасываем и продолжаем")
                    explorer = self._reset_explorer_pattern(url, state, driver=driver, custom_logger=logger)
                    continue
                
                # Пытаемся найти паттерн
                if recipes_found >= self.min_recipes:
                    pattern = self._try_find_pattern(site_id, explorer)
                    if pattern:
                        logger.info(f"\n{'='*70}")
                        logger.info(f"✓ УСПЕХ: Паттерн найден после {batch_num} батчей")
                        logger.info(f"  Паттерн: {pattern}")
                        logger.info(f"  Сайт ID: {site_id}")
                        logger.info(f"  Исследовано страниц: {total_pages}")
                        logger.info(f"{'='*70}\n")
                        
                        # Создаем тестовые данные
                        self.make_test_data(site_orm)
                        
                        explorer.close()
                        self.site_repository.mark_site_as_searched(site_orm.id)
                        return True
                
                batches_completed += 1
            
            # Паттерн не найден
            logger.warning(f"\n{'='*70}")
            logger.warning("✗ НЕУДАЧА: Паттерн не найден")
            logger.warning(f"  Исследовано страниц: {total_pages}")
            logger.warning(f"  Найдено рецептов: {recipes_found}")
            logger.warning(f"  Минимум требуется: {self.min_recipes}")
            logger.warning(f"{'='*70}\n")
            explorer.close()
            self.site_repository.mark_site_as_searched(site_orm.id)
            return False
            
        except Exception as e:
            logger.error(f"Критическая ошибка при подготовке сайта: {e}", exc_info=True)
            explorer.close()
            return False
    
    def _try_find_pattern(self, site_id: int, explorer: SiteExplorer) -> Optional[str]:
        """
        Попытка найти паттерн URL с рецептами
        
        Args:
            site_id: ID сайта
            explorer: Экземпляр explorer для обновления
        
        Returns:
            Найденный паттерн или None
        """
        if explorer.site.pattern:
            logger.info(f"Паттерн уже установлен: {explorer.site.pattern}")
            return explorer.site.pattern
        
        logger.info("→ Анализ URL для определения паттерна...")
        
        try:
            pattern = self.analyzer.analyse_recipe_page_pattern(site_id=site_id)
            
            if pattern:
                explorer.set_pattern(pattern)
                logger.info("✓ Паттерн определен и установлен")
                return pattern
            else:
                logger.info("✗ Не удалось определить паттерн")
                return None
                
        except Exception as e:
            logger.error(f"Ошибка при поиске паттерна: {e}")
            return None
    
    def _reset_explorer_pattern(self, url: str, state: dict, driver: Optional[webdriver.Chrome] = None,
                                custom_logger: Optional[logging.Logger] = None) -> SiteExplorer:
        """
        Сброс паттерна explorer с восстановлением состояния
        
        Args:
            url: URL сайта
            state: Сохраненное состояние explorer
        
        Returns:
            Новый экземпляр explorer
        """
        logger.info("→ Создание нового explorer без паттерна...")
        
        new_explorer = SiteExplorer(
            url,
            debug_mode=True,
            debug_port=self.debug_port,
            max_urls_per_pattern=self.max_urls_per_pattern - 2,  # Уменьшаем лимит
            driver=driver,
            custom_logger=custom_logger
        )
        
        new_explorer.import_state(state)
        logger.info("✓ Состояние восстановлено")
        
        return new_explorer
    
    def make_test_data(self, site_orm: SiteORM) -> int:
        """
        Создание тестовых данных (копирование HTML и JSON рецептов)
        
        Args:
            site_id: ID сайта
            folder: Папка для сохранения данных
        
        Returns:
            Количество скопированных рецептов
        """
        logger.info(f"\n{'='*60}")
        logger.info("СОЗДАНИЕ ТЕСТОВЫХ ДАННЫХ")
        logger.info(f"{'='*60}")
        
        try:
            site_name = site_orm.name
            
            # Получаем все рецепты сайта
            recipe_pages = self.page_repository.get_recipes(site_id=site_orm.id)
            
            if not recipe_pages:
                logger.warning(f"Нет рецептов для сайта {site_name} (ID={site_orm.id})")
                return 0
            
            logger.info(f"Найдено {len(recipe_pages)} рецептов для сайта '{site_name}'")
            
            # Создаем директорию для тестовых данных
            recipes_path = os.path.join(self.preprocessed_recipe_folder, site_name)
            os.makedirs(recipes_path, exist_ok=True)
            logger.info(f"Папка для данных: {recipes_path}")
            
            copied_count = 0
            
            for page_orm in recipe_pages:
                page = page_orm.to_pydantic()
                
                if not page.html_path or not os.path.exists(page.html_path):
                    logger.debug(f"HTML файл не найден для страницы {page.id}: {page.html_path}")
                    continue
                
                # Получаем имя файла из html_path
                html_filename = os.path.basename(page.html_path)
                
                # Копируем HTML файл
                dest_html_path = os.path.join(recipes_path, html_filename)
                shutil.copy2(page.html_path, dest_html_path)
                
                # Сохраняем файл с извлеченными данными
                extracted_data_filename = html_filename.replace(".html", ".json")
                extracted_data_path = os.path.join(recipes_path, extracted_data_filename)
                
                with open(extracted_data_path, "w", encoding="utf-8") as f:
                    json.dump(page.page_to_json(), f, ensure_ascii=False, indent=4)
                
                copied_count += 1
                logger.debug(f"  ✓ {html_filename} + {extracted_data_filename}")
            
            logger.info(f"✓ Скопировано {copied_count} рецептов в {recipes_path}")
            logger.info(f"{'='*60}\n")
            
            return copied_count
            
        except Exception as e:
            logger.error(f"Ошибка при создании тестовых данных: {e}", exc_info=True)
            return 0
    
    def close(self):
        """Закрытие ресурсов"""
        self.analyzer.close()
        logger.info("Pipeline закрыт")

