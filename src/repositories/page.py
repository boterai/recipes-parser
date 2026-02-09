"""
Репозиторий для работы с страницами
"""

import logging
from typing import Optional, List
from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError  
from src.repositories.base import BaseRepository
from src.models.page import PageORM, Page
from src.models.image import ImageORM
from src.common.db.connection import get_db_connection

logger = logging.getLogger(__name__)


class PageRepository(BaseRepository[PageORM]):
    """Репозиторий для работы со страницами"""
    
    def __init__(self, mysql_manager=None):
        # Используем общее подключение если не передано явно
        if mysql_manager is None:
            mysql_manager = get_db_connection()
        super().__init__(PageORM, mysql_manager)
    
    def get_by_url(self, site_id: int, url: str) -> Optional[PageORM]:
        """
        Получить страницу по site_id и URL
        
        Args:
            site_id: ID сайта
            url: URL страницы
        
        Returns:
            PageORM или None
        """
        session = self.get_session()
        try:
            return session.query(PageORM).filter(
                and_(
                    PageORM.site_id == site_id,
                    PageORM.url == url
                )
            ).first()
        finally:
            session.close()

    def get_for_translation(self, last_processed_id: int, site_id: Optional[int]=None, limit: int = 100) -> List[PageORM]:
        session = self.get_session()
        try:
            query = session.query(PageORM).filter(PageORM.is_recipe == True, 
                                                        PageORM.ingredients != None, 
                                                        PageORM.dish_name != None,
                                                        PageORM.instructions != None, 
                                                        PageORM.id > last_processed_id)
                    
            if site_id:
                query = query.filter(PageORM.site_id == site_id)

            query = query.order_by(PageORM.id.asc()).limit(limit)
            return query.all()
        finally:
            session.close()
    
    def get_by_site(self, site_id: int, limit: Optional[int] = None, confidence_score: Optional[int] = None,
                    offset: Optional[int] = None) -> List[PageORM]:
        """
        Получить все страницы определенного сайта
        
        Args:
            site_id: ID сайта
            limit: Максимальное количество страниц
        
        Returns:
            Список страниц
        """
        session = self.get_session()
        try:
            query = session.query(PageORM).filter(PageORM.site_id == site_id)

            if confidence_score is not None:
                query = query.filter(PageORM.confidence_score >= confidence_score)
            
            if limit:
                query = query.limit(limit)
            
            if offset:
                query = query.offset(offset)
            
            return query.all()
        finally:
            session.close()
    
    def get_recipes(self, site_id: Optional[int] = None, language: Optional[str] = None, 
                    limit: Optional[int] = None, random_order: bool = False, order_by_id: bool = False,
                    page_ids: Optional[list[int]] = None) -> List[PageORM]:
        """
        Получить страницы с рецептами
        
        Args:
            site_id: ID сайта (опционально)
            language: Язык (опционально)
            limit: Максимальное количество
            random_order: Если True, возвращает в случайном порядке
        
        Returns:
            Список страниц с рецептами
        """
        session = self.get_session()
        try:
            query = session.query(PageORM).filter(PageORM.is_recipe == True, PageORM.instructions != None, PageORM.instructions != "",
                                                  PageORM.ingredients != None)
            
            if page_ids:
                query = query.filter(PageORM.id.in_(page_ids))
            
            if site_id:
                query = query.filter(PageORM.site_id == site_id)
            
            if language:
                query = query.filter(PageORM.language == language)
            
            # Сортировка
            if random_order:
                query = query.order_by(func.random())  # Случайный порядок
            elif order_by_id:
                query = query.order_by(PageORM.id.asc())  # По id
            else:
                query = query.order_by(PageORM.confidence_score.desc())  # По уверенности
            
            if limit:
                query = query.limit(limit)
            
            return query.all()
        finally:
            session.close()

    def get_recipes_ids(self, site_id: Optional[int] = None, language: Optional[str] = None, 
                    limit: Optional[int] = None, random_order: bool = False) -> List[int]:
        """
        Получить страницы с рецептами
        
        Args:
            site_id: ID сайта (опционально)
            language: Язык (опционально)
            limit: Максимальное количество
            random_order: Если True, возвращает в случайном порядке
        
        Returns:
            Список страниц с рецептами
        """
        session = self.get_session()
        try:
            query = session.query(PageORM).filter(PageORM.is_recipe == True, PageORM.instructions != None, PageORM.instructions != "",
                                                  PageORM.ingredients != None)
            
            if site_id:
                query = query.filter(PageORM.site_id == site_id)
            
            if language:
                query = query.filter(PageORM.language == language)
            
            # Сортировка
            if random_order:
                query = query.order_by(func.random())  # Случайный порядок
            else:
                query = query.order_by(PageORM.id.asc())  # По id
            
            if limit:
                query = query.limit(limit)
            
            result = query.with_entities(PageORM.id).all()
            return [row[0] for row in result]
        finally:
            session.close()
    
    
    def create_or_update(self, page_data: Page) -> Optional[PageORM]:
        """
        Создать новую страницу или обновить существующую
        
        Args:
            page_data: Pydantic модель с данными страницы
        
        Returns:
            PageORM объект
        """
        # Проверяем существование по site_id + url
        existing = self.get_by_url(page_data.site_id, page_data.url)
        
        if existing:
            # Обновляем существующую
            page_data.update_orm(existing)
            updated = self.update(existing)
            logger.debug(f"✓ Обновлена страница ID={existing.id}: {page_data.url}")
            return updated
        else:
            # Создаем новую
            page_orm = page_data.to_orm()
            created = self.create(page_orm)
            logger.debug(f"✓ Создана новая страница ID={created.id}: {page_data.url}")
            return created
    
    def create_with_images(self, page_data: Page, image_urls: List[str]) -> Optional[PageORM]:
        """
        Создать страницу с изображениями в одной транзакции
        
        Args:
            page_data: Pydantic модель с данными страницы
            image_urls: Список URL изображений
        
        Returns:
            PageORM объект с загруженными images или None при ошибке
        """
        session = self.get_session()
        try:
            # Создаем ORM объект страницы
            page_orm = page_data.to_orm()
            
            # Добавляем изображения через relationship
            if image_urls:
                page_orm.images = [
                    ImageORM(image_url=url) 
                    for url in image_urls
                ]
            
            # Сохраняем в одной транзакции (images сохранятся автоматически благодаря cascade)
            session.add(page_orm)
            session.commit()
            
            # Обновляем объект чтобы получить актуальные данные
            session.refresh(page_orm)
            
            logger.debug(f"✓ Создана страница ID={page_orm.id} с {len(image_urls)} изображениями: {page_data.url}")
            return page_orm
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка создания страницы с изображениями: {e}")
            return None
        finally:
            session.close()
    
    def create_or_update_with_images(self, page_orm: PageORM|Page, image_urls: List[str], 
                                      replace_images: bool = False) -> Optional[PageORM]:
        """
        Создать новую страницу с изображениями или обновить существующую
        
        Args:
            page_data: Pydantic модель с данными страницы
            image_urls: Список URL изображений для добавления
            replace_images: Если True, заменяет все существующие изображения, иначе добавляет новые
        
        Returns:
            PageORM объект с загруженными images
        """
        session = self.get_session()
        try:
            if page_orm.id: # ищем по ID если есть
                existing = session.query(PageORM).filter(PageORM.id == page_orm.id).first()
            else: # иначе по URL
                existing = session.query(PageORM).filter(PageORM.url == page_orm.url).first()
                
            if existing:
                # Обновляем существующую страницу
                # Обновляем поля страницы
                existing.update_from_page(page_orm)
                
                if image_urls:
                    if replace_images:
                        # Заменяем все изображения
                        existing.images.clear()
                        existing.images = [
                            ImageORM(image_url=url)
                            for url in image_urls
                        ]
                        logger.debug(f"✓ Заменено {len(image_urls)} изображений для страницы ID={existing.id}")
                    else:
                        # Добавляем только новые (проверяем дубликаты)
                        existing_urls = {img.image_url for img in existing.images}
                        new_images = [
                            ImageORM(image_url=url)
                            for url in image_urls
                            if url not in existing_urls
                        ]
                        existing.images.extend(new_images)
                        logger.debug(f"✓ Добавлено {len(new_images)} новых изображений для страницы ID={existing.id}")
                
                session.commit()
                session.refresh(existing)
                
                logger.debug(f"✓ Обновлена страница ID={existing.id}: {existing.url}")
                return existing
            else:
                page_orm = page_orm if isinstance(page_orm, PageORM) else page_orm.to_orm()

                # Добавляем изображения через relationship
                if image_urls:
                    page_orm.images = [
                        ImageORM(image_url=url) 
                        for url in image_urls
                    ]
                
                # Сохраняем в одной транзакции
                session.add(page_orm)
                session.commit()
                session.refresh(page_orm)
                
                logger.debug(f"✓ Создана страница ID={page_orm.id} с {len(image_urls)} изображениями: {page_orm.url}")
                return page_orm
        except IntegrityError as ie:
            session.rollback()
            logger.error(f"Ошибка целостности данных при сохранении страницы: {ie}")
            if "Duplicate entry" in str(ie) and  "for key 'images.unique_image_url_hash'" in str(ie):
                logger.error("Попытка сохранить дублирующееся изображение. Пробуем обновить/сохранить страницу без привязки к изображению")
                page = page_orm.to_pydantic() if isinstance(page_orm, PageORM) else page_orm
                return self.create_or_update(page)
            return None
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка обновления страницы с изображениями: {e}")
            return None
        finally:
            session.close()
    
    def count_recipes_by_site(self, site_id: int) -> int:
        """
        Подсчитать количество рецептов для сайта
        
        Args:
            site_id: ID сайта
        
        Returns:
            Количество рецептов
        """
        session = self.get_session()
        try:
            return session.query(PageORM).filter(
                and_(
                    PageORM.site_id == site_id,
                    PageORM.is_recipe == True
                )
            ).count()
        finally:
            session.close()
    
    def delete_by_site(self, site_id: int) -> int:
        """
        Удалить все страницы определенного сайта
        
        Args:
            site_id: ID сайта
        
        Returns:
            Количество удаленных страниц
        """
        session = self.get_session()
        try:
            deleted_count = session.query(PageORM).filter(
                PageORM.site_id == site_id
            ).delete()
            session.commit()
            logger.info(f"✓ Удалено {deleted_count} страниц для сайта ID={site_id}")
            return deleted_count
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка удаления страниц сайта {site_id}: {e}")
            return 0
        finally:
            session.close()

    def update_page_language_by_site(self, site_id: int, language: str) -> int:
        """
        Обновить язык для всех страниц определенного сайта
        
        Args:
            site_id: ID сайта
            language: Новый язык для всех страниц сайта
            
        Returns:
            Количество обновленных страниц
        """
        session = self.get_session()
        try:
            updated_count = session.query(PageORM).filter(
                PageORM.site_id == site_id
            ).update({PageORM.language: language})
            session.commit()
            logger.info(f"✓ Обновлен язык на '{language}' для {updated_count} страниц сайта ID={site_id}")
            return updated_count
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка обновления языка для сайта {site_id}: {e}")
            return 0
        finally:
            session.close()
    
    def bulk_update(self, pages: List[PageORM]) -> int:
        """
        Массовое обновление страниц в БД (bulk update)
        
        Args:
            pages: Список PageORM объектов для обновления
        
        Returns:
            Количество обновленных страниц
        """
        if not pages:
            return 0
        
        session = self.get_session()
        try:
            # Используем bulk_update_mappings для быстрого обновления
            mappings = []
            for page in pages:
                # Конвертируем ORM объект в словарь для bulk update
                mapping = {
                    'id': page.id,
                    'is_recipe': page.is_recipe,
                    'confidence_score': page.confidence_score,
                    'dish_name': page.dish_name,
                    'description': page.description,
                    'ingredients': page.ingredients,
                    'instructions': page.instructions,
                    'prep_time': page.prep_time,
                    'cook_time': page.cook_time,
                    'total_time': page.total_time,
                    'category': page.category,
                    'notes': page.notes,
                    'tags': page.tags
                }
                mappings.append(mapping)
            
            # Выполняем bulk update
            session.bulk_update_mappings(PageORM, mappings)
            session.commit()
            
            logger.info(f"✓ Массово обновлено {len(pages)} страниц")
            return len(pages)
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка массового обновления страниц: {e}")
            raise e
        finally:
            session.close()
    
    def mark_as_non_recipes(self, page_ids: List[int]) -> int:
        """
        Пометка страниц как не являющихся рецептами
        Устанавливает is_recipe = FALSE, confidence_score = 10 (вывод только по заголовку)
        
        Args:
            page_ids: Список ID страниц
            
        Returns:
            Количество обновленных записей
        """
        if not page_ids:
            return 0
        
        session = self.get_session()
        try:
            # Используем bulk_update_mappings для эффективного обновления
            mappings = [
                {
                    'id': page_id,
                    'is_recipe': False,
                    'confidence_score': 10
                }
                for page_id in page_ids
            ]
            
            session.bulk_update_mappings(PageORM, mappings)
            session.commit()
            
            updated_count = len(page_ids)
            logger.info(f"✓ Помечено {updated_count} страниц как не рецепты")
            return updated_count
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при пометке не рецептов: {e}")
            return 0
        finally:
            session.close()

    def get_recipe_sites(self, min_site_id: Optional[int] = None) -> List[int]:
        """
        Получить список уникальных site_id, для которых есть страницы с рецептами
        
        Returns:
            Список site_id
        """
        session = self.get_session()
        try:
            query = session.query(PageORM.site_id).filter(
                PageORM.is_recipe == True,
                PageORM.ingredients != None,
                PageORM.dish_name != None,
                PageORM.instructions != None
            )

            if min_site_id is not None:
                query = query.filter(PageORM.site_id >= min_site_id)
            
            site_ids = query.distinct().order_by(PageORM.site_id.asc()).all()
            site_ids = [sid[0] for sid in site_ids]
            return site_ids
        finally:
            session.close()