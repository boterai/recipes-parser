"""
Модуль для запуска парсинга сайтов с использованием экстракторов
"""
import random
import logging
from pathlib import Path
from typing import Optional

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.stages.parse.explorer import explore_site
from src.repositories.site import SiteRepository

logger = logging.getLogger(__name__)


class RecipeParserRunner:
    """Класс для запуска парсинга рецептов с выбором модуля экстрактора"""
    
    def __init__(self, extractor_dir: str = "extractor"):
        """
        Args:
            extractor_dir: Путь к директории с экстракторами
        """
        self.extractor_dir = Path(extractor_dir)
        self.available_extractors = self._get_available_extractors()
        self.site_repository = SiteRepository()
    
    def _get_available_extractors(self) -> list[str]:
        """
        Получение списка доступных модулей экстракторов
        
        Returns:
            Список названий модулей (без расширения .py)
        """
        if not self.extractor_dir.exists():
            logger.error(f"Директория экстракторов не найдена: {self.extractor_dir}")
            return []
        
        extractors = []
        for file in self.extractor_dir.glob("*.py"):
            # Пропускаем __init__.py и base.py
            if file.stem not in ["__init__", "base"]:
                extractors.append(file.stem)
        
        logger.info(f"Найдено {len(extractors)} доступных экстракторов")
        return sorted(extractors)
    
    def get_random_extractor(self) -> Optional[str]:
        """
        Получение случайного модуля экстрактора
        
        Returns:
            Название модуля или None если нет доступных
        """
        if not self.available_extractors:
            logger.error("Нет доступных экстракторов")
            return None
        
        selected = random.choice(self.available_extractors)
        logger.info(f"Выбран случайный экстрактор: {selected}")
        return selected
        
    def run_parser(
        self,
        module_name: Optional[str] = None,
        port: int = 9222,
        max_urls: int = 5000,
        max_depth: int = 4,
        custom_logger: Optional[logging.Logger] = None
    ) -> bool:
        """
        Запуск парсинга с указанным или случайным модулем
        
        Args:
            module_name: Название модуля экстрактора (например, "allrecipes_com")
                        Если None, выбирается случайный модуль
            port: Порт для подключения к Chrome в режиме отладки
            max_urls: Максимальное количество URL для исследования
            max_depth: Максимальная глубина исследования
            helper_links: Дополнительные URL для добавления в очередь
            
        Returns:
            True если парсинг запущен успешно, False в случае ошибки
        """
        # Выбор модуля
        if module_name is None:
            module_name = self.get_random_extractor()
            if module_name is None:
                return False
        else:
            # Проверка существования модуля
            if module_name not in self.available_extractors:
                custom_logger.error(
                    f"Модуль '{module_name}' не найден. "
                    f"Доступные модули: {', '.join(self.available_extractors)}"
                )
                return False
        
        # Получение URL сайта
        site_orm = self.site_repository.get_by_name(module_name)
        if site_orm is None:
            custom_logger.error(f"URL для модуля '{module_name}' не найден в БД сайтов")
            return False
        
        custom_logger.info("=" * 60)
        custom_logger.info("Запуск парсинга")
        custom_logger.info(f"  Модуль: {module_name}")
        custom_logger.info(f"  URL: {site_orm.base_url}")
        custom_logger.info(f"  Порт отладки: {port}")
        custom_logger.info(f"  Макс. URL: {max_urls}")
        custom_logger.info(f"  Макс. глубина: {max_depth}")
        custom_logger.info("=" * 60)

        helper_links = None
        if site_orm.search_url:
            helper_links = [site_orm.search_url]
        
        try:
            # Запуск парсинга через explore_site
            explore_site(
                url=site_orm.base_url,
                max_urls=max_urls,
                max_depth=max_depth,
                recipe_pattern=site_orm.pattern,
                check_pages_with_extractor=True,
                check_url=True,
                debug_port=port,
                helper_links=helper_links,
                custom_logger=custom_logger
            )
            
            custom_logger.info(f"Парсинг {module_name} завершен успешно")
            return True
            
        except Exception as e:
            custom_logger.error(f"Ошибка при парсинге {module_name}: {e}", exc_info=True)
            return False


