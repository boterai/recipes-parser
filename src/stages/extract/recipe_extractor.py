"""Фабрика экстракторов для извлечения данных рецептов из HTML"""
import os
import sys
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import importlib.util

from src.models.page import Page
from src.models.site import SiteORM

logger = logging.getLogger(__name__)
from src.repositories.page import PageRepository
from src.repositories.site import SiteRepository
from typing import Optional, Dict, Any, Type
from extractor.base import BaseRecipeExtractor

class RecipeExtractor:
    """Выбирает и использует подходящий экстрактор для сайта"""
    
    def __init__(self, page_repository: PageRepository = None, site_repository: SiteRepository = None):
        self.extractors_cache: Dict[int, Type[BaseRecipeExtractor]] = {}
        self.output_dir = "extracted_recipes"
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)
        
        if page_repository is None:
            page_repository = PageRepository()
        if site_repository is None:
            site_repository = SiteRepository()

        self.page_repository = page_repository
        self.site_repository = site_repository

        sites_orm: list[SiteORM] = self.site_repository.get_all()
        # Маппинг site_id -> имя модуля экстрактора
        self.extractor_map: Dict[int, str] = {}
        for site in sites_orm:
            self.extractor_map[site.id] = site.name


    def _get_output_filename(self, html_path: str) -> str:
        return os.path.join(
            self.output_dir,
            html_path.replace(".html", ".json")
        )
    
    def _get_extractor_module_name(self, site_id: int) -> Optional[str]:
        """Определяет имя модуля экстрактора по site_id или домену"""
        
        # Сначала проверяем маппинг по site_id
        if site_id in self.extractor_map:
            return self.extractor_map[site_id]
        
        return None
    
    def _load_extractor_class(self, module_name: str) -> Type[BaseRecipeExtractor]:
        """Динамически загружает класс экстрактора из модуля"""
        # Путь к файлу экстрактора
        extractor_path = os.path.join('extractor', f'{module_name}.py')
        
        if not os.path.exists(extractor_path):
            raise FileNotFoundError(f"Extractor module not found: {extractor_path}")
        
        # Динамическая загрузка модуля
        spec = importlib.util.spec_from_file_location(module_name, extractor_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module: {module_name}")
        
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        
        # Находим класс экстрактора (ищем класс с "Extractor" в имени)
        for attr_name in dir(module):
            if 'Extractor' in attr_name and not attr_name.startswith('_') and attr_name != 'BaseRecipeExtractor':
                extractor_class = getattr(module, attr_name)
                if isinstance(extractor_class, type):
                    return extractor_class
        
        raise ImportError(f"No Extractor class found in module: {module_name}")
    
    def _get_extractor(self, site_id: int) -> Type[BaseRecipeExtractor]:
        """Получает экземпляр экстрактора для сайта (с кешированием)"""
        
        if site_id in self.extractors_cache:
            return self.extractors_cache[site_id]
        
        module_name = self._get_extractor_module_name(site_id)
        if module_name is None:
            raise ValueError(f"No extractor available for site_id={site_id}")
        
        extractor_class = self._load_extractor_class(module_name)
        self.extractors_cache[site_id] = extractor_class
        
        return extractor_class
    
    def extract_from_html(self, html_path: str, site_id: int) -> Optional[Dict[str, Any]]:
        """
        Извлекает данные рецепта из HTML файла
        
        Args:
            html_path: путь к HTML файлу
            site_id: ID сайта в БД
            
        Returns:
            Словарь с данными рецепта или None если извлечение не удалось
        """
        
        try:
            # Получаем класс экстрактора
            extractor_class = self._get_extractor(site_id)
            
            # Создаем экземпляр и извлекаем данные
            extractor = extractor_class(html_path)
            recipe_data = extractor.extract_all()
            
            return recipe_data
            
        except Exception as e:
            print(f"Ошибка извлечения из {html_path}: {e}")
            return None
    
    def extract_and_update_page(self, page: Page) -> Optional[Page]:
        """
        Извлекает данные рецепта и обновляет объект PageORM (без сохранения в БД)
        
        Args:
            page: объект PageORM для извлечения
            
        Returns:
            Обновленный PageORM или None если ошибка
        """

        if not page.html_path or not Path(page.html_path).exists():
            print(f"HTML файл не найден: {page.html_path}")
            return None
        
        recipe_data = self.extract_from_html(page.html_path, page.site_id)
        
        if recipe_data is None:
            return None
        
        # Если ключевые поля отсутствуют, помечаем как не рецепт
        key_fields = ['dish_name', 'ingredients', 'instructions']
        if not all(field in recipe_data and recipe_data[field] for field in key_fields):
            page.confidence_score = 10
            page.is_recipe = False
            return page
        
        # Обновляем объект PageORM данными из словаря
        page.update_from_dict(recipe_data)
        page.confidence_score = 50
        page.is_recipe = True
        
        return page