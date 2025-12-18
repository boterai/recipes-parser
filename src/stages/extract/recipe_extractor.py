"""Фабрика экстракторов для извлечения данных рецептов из HTML"""
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any
import importlib.util

from src.common.db.mysql import MySQlManager
from src.models.page import Page
from src.models.site import Site
import sqlalchemy
from typing import Optional, Dict, Any, Type
from extractor.base import BaseRecipeExtractor

class RecipeExtractor:
    """Выбирает и использует подходящий экстрактор для сайта"""
    
    def __init__(self, db_manager: MySQlManager):
        self.db = db_manager
        self.extractors_cache: Dict[int, Type[BaseRecipeExtractor]] = {}
        self.output_dir = "extracted_recipes"
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)

        # получаем маппинг site_id -> домен из базы данных
        sql = "SELECT id, name, base_url FROM sites"
        with self.db.get_session() as session:
            result = session.execute(sqlalchemy.text(sql))
            rows = result.fetchall()
            sites = [Site.model_validate(dict(row._mapping)) for row in rows]
                
        
        # Маппинг site_id -> имя модуля экстрактора
        self.extractor_map: Dict[int, str] = {}
        for site in sites:
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
    
    def extract_page(self, page: Page) -> Optional[Dict[str, Any]]:
        """
        Извлекает данные рецепта из страницы
        
        Args:
            page: объект Page с информацией о странице
            
        Returns:
            Словарь с данными рецепта или None
        """
        
        if not page.html_path or not Path(page.html_path).exists():
            print(f"HTML файл не найден: {page.html_path}")
            return None

        return self.extract_from_html(page.html_path, page.site_id)
    
    def extract_and_update_page(self, page: Page) -> Optional[dict]:
        """
        Извлекает данные рецепта (без обновления БД)
        
        Args:
            page: объект Page для извлечения
            
        Returns:
            (True, recipe_data) если успешно, (False, None) если ошибка
        """
        
        recipe_data = self.extract_page(page)
        
        if recipe_data is None:
            return None
        
        # если ключевые поля отсутствуют, помечаем как не рецепт
        key_fields = ['dish_name', 'ingredients', 'instructions']
        if not all(field in recipe_data and recipe_data[field] for field in key_fields):
            return {
                "page_id": page.id,
                "confidence_score": 10,
                "is_recipe": False
            }
        
        # Подготавливаем данные для батч-обновления
        recipe_data["page_id"] = page.id
        recipe_data["confidence_score"] = 50
        recipe_data["is_recipe"] = True
        
        return recipe_data
    
    def batch_update_pages(self, recipes_data: list[dict], failed_pages: list[dict]) -> tuple[int, int]:
        """
        Батч-обновление страниц в БД
        
        Args:
            recipes_data: список словарей с данными успешных рецептов
            failed_pages: список словарей с данными неудачных страниц
            
        Returns:
            (success_count, failed_count)
        """
        success_count = 0
        failed_count = 0
        
        with self.db.get_session() as session:
            # Обновляем успешные рецепты батчем
            if recipes_data:
                sql_success = """
                    UPDATE pages SET
                        is_recipe = :is_recipe,
                        confidence_score = :confidence_score,
                        dish_name = :dish_name,
                        description = :description,
                        ingredients = :ingredients,
                        instructions = :instructions,
                        prep_time = :prep_time,
                        cook_time = :cook_time,
                        total_time = :total_time,
                        category = :category,
                        nutrition_info = :nutrition_info,
                        notes = :notes,
                        tags = :tags,
                        image_urls = :image_urls
                    WHERE id = :page_id
                """
                session.execute(sqlalchemy.text(sql_success), recipes_data)
                success_count = len(recipes_data)
            
            # Обновляем неудачные страницы батчем
            if failed_pages:
                sql_failed = """
                    UPDATE pages SET
                        confidence_score = :confidence_score,
                        is_recipe = :is_recipe
                    WHERE id = :page_id
                """
                session.execute(sqlalchemy.text(sql_failed), failed_pages)
                failed_count = len(failed_pages)
            
            session.commit()
        
        return success_count, failed_count
    
    def process_site_recipes(self, site_id: int, limit: Optional[int] = None, confidence_score: int = 0, batch_size: int = 100) -> Dict[str, int]:
        """
        Обрабатывает все рецепты для указанного сайта с батч-обновлением
        
        Args:
            site_id: ID сайта
            limit: максимальное количество страниц (None = все)
            confidence_score: минимальный балл достоверности для обработки
            batch_size: размер батча для обновления БД (по умолчанию 100)
            
        Returns:
            Статистика: {'processed': N, 'success': N, 'failed': N}
        """
        
        stats = {'processed': 0, 'success': 0, 'failed': 0}
        
        with self.db.get_session() as session:
            # Получаем страницы с рецептами без извлеченных данных
            query = "SELECT * FROM pages WHERE site_id = :site_id AND confidence_score > :confidence_score"
            if limit:
                query += f" LIMIT {limit}"

            results = session.execute(sqlalchemy.text(query), {"site_id": site_id, "confidence_score": confidence_score})
            rows = results.fetchall()
            pages = [Page.model_validate(dict(row._mapping)) for row in rows]
            
            print(f"\n{'='*60}")
            print(f"Обработка рецептов для site_id={site_id}")
            print(f"Найдено страниц: {len(pages)}")
            print(f"Размер батча: {batch_size}")
            print(f"{'='*60}\n")
            
            # Батч-обработка
            recipes_batch = []
            failed_batch = []
            
            for i, page in enumerate(pages, 1):
                stats['processed'] += 1
                
                print(f"[{i}/{len(pages)}] Извлечение из {page.id}...", end=' ')
                
                data = self.extract_and_update_page(page)
                
                if data and data.get("is_recipe", False):
                    recipes_batch.append(data)
                    stats['success'] += 1
                    print("✓")
                else:
                    if data:  # Есть данные о неудаче
                        failed_batch.append(data)
                    stats['failed'] += 1
                    print("✗")
                
                # Обновляем БД когда накопили достаточно или это последняя страница
                if len(recipes_batch) + len(failed_batch) >= batch_size or i == len(pages):
                    if recipes_batch or failed_batch:
                        print(f"\n  → Обновление БД: {len(recipes_batch)} успешных, {len(failed_batch)} неудачных...")
                        success_count, failed_count = self.batch_update_pages(recipes_batch, failed_batch)
                        print(f"  ✓ Обновлено в БД: {success_count + failed_count} записей\n")
                        
                        # Очищаем батчи
                        recipes_batch = []
                        failed_batch = []
        
        print(f"\n{'='*60}")
        print("Обработка завершена!")
        print(f"Обработано: {stats['processed']}")
        print(f"Успешно: {stats['success']}")
        print(f"Ошибок: {stats['failed']}")
        print(f"{'='*60}\n")
        
        return stats
