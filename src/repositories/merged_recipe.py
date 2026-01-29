"""
Репозиторий для работы с вариациями рецептов
"""

import logging
from typing import Optional, List

from src.repositories.base import BaseRepository
from src.models.merged_recipe import MergedRecipeORM, MergedRecipe, merged_recipe_images
from src.models.merged_recipe import MergedRecipe
from src.models.image import ImageORM
from src.common.db.connection import get_db_connection
import hashlib
from sqlalchemy import insert, delete

logger = logging.getLogger(__name__)


class MergedRecipeRepository(BaseRepository[MergedRecipeORM]):
    """Репозиторий для работы с объединенными рецептами"""
    
    def __init__(self, mysql_manager=None):
        if mysql_manager is None:
            mysql_manager = get_db_connection()
        super().__init__(MergedRecipeORM, mysql_manager)
    
    
    def create_merged_recipe(
        self,
        merged_recipe: MergedRecipe
    ) -> MergedRecipeORM:
        """
        Создать новый объединенный рецепт из Pydantic модели
        
        Args:
            merged_recipe: MergedRecipe объект с данными рецепта
        
        Returns:
            Созданный объект MergedRecipeORM
        """
        session = self.get_session()
        try:
            # Извлекаем данные из Pydantic модели
            page_ids = merged_recipe.page_ids or []
            if not page_ids:
                raise ValueError("page_ids обязательно должны быть указаны")
            
            # Создаем pages_csv и hash
            sorted_ids = sorted(page_ids)
            pages_csv = ','.join(map(str, sorted_ids))
            pages_hash = hashlib.sha256(pages_csv.encode()).hexdigest()
            
            # Проверяем существование
            existing = session.query(MergedRecipeORM).filter(
                MergedRecipeORM.pages_hash_sha256 == pages_hash
            ).first()
            
            if existing:
                logger.warning(f"Объединенный рецепт для страниц {pages_csv} уже существует (id={existing.id})")
                return existing
            
            # Создаем новый ORM объект из данных Pydantic модели
            merged_recipe_orm = MergedRecipeORM(
                pages_hash_sha256=pages_hash,
                pages_csv=pages_csv,
                dish_name=merged_recipe.dish_name,
                ingredients=merged_recipe.ingredients,
                instructions=merged_recipe.instructions,
                description=merged_recipe.description,
                prep_time=merged_recipe.prep_time,
                cook_time=merged_recipe.cook_time,
                merge_comments=merged_recipe.merge_comments,
                language=merged_recipe.language,
                cluster_type=merged_recipe.cluster_type,
                gpt_validated=merged_recipe.gpt_validated,
                score_threshold=merged_recipe.score_threshold
            )
            
            session.add(merged_recipe_orm)
            session.commit()
            session.refresh(merged_recipe_orm)
            
            logger.info(f"✓ Создан объединенный рецепт {merged_recipe_orm.id}: {merged_recipe.dish_name} (страницы: {pages_csv})")
            return merged_recipe_orm
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка создания объединенного рецепта: {e}")
            raise
        finally:
            session.close()
    
    def create_merged_recipes_batch(
        self,
        merged_recipes: list[MergedRecipe]
    ) -> list[MergedRecipeORM]:
        """
        Создать несколько объединенных рецептов за один раз (batch insert)
        
        Args:
            merged_recipes: Список MergedRecipe объектов
        
        Returns:
            Список созданных MergedRecipeORM объектов
        """
        if not merged_recipes:
            return []
        
        session = self.get_session()
        try:
            created = []
            
            # Собираем хэши для проверки существования
            hashes_to_check = []
            recipe_by_hash: dict[str, MergedRecipe] = {}
            
            for merged_recipe in merged_recipes:
                page_ids = merged_recipe.page_ids or []
                if not page_ids:
                    logger.warning(f"Пропущен рецепт без page_ids: {merged_recipe.dish_name}")
                    continue
                
                sorted_ids = sorted(page_ids)
                pages_csv = ','.join(map(str, sorted_ids))
                pages_hash = hashlib.sha256(pages_csv.encode()).hexdigest()
                
                hashes_to_check.append(pages_hash)
                recipe_by_hash[pages_hash] = merged_recipe
            
            # Проверяем существующие за один запрос
            existing = session.query(MergedRecipeORM).filter(
                MergedRecipeORM.pages_hash_sha256.in_(hashes_to_check)
            ).all()
            
            existing_hashes = {r.pages_hash_sha256 for r in existing}
            logger.info(f"Найдено {len(existing_hashes)} существующих рецептов из {len(hashes_to_check)}")
            
            # Создаем только новые
            new_recipes = []
            recipe_image_mapping = {}
            
            for pages_hash, merged_recipe in recipe_by_hash.items():
                if pages_hash in existing_hashes:
                    logger.debug(f"Пропущен существующий рецепт: {merged_recipe.dish_name}")
                    continue
                
                # Пересчитываем CSV для нового объекта
                sorted_ids = sorted(merged_recipe.page_ids)
                pages_csv = ','.join(map(str, sorted_ids))
                
                merged_recipe_orm = MergedRecipeORM(
                    pages_hash_sha256=pages_hash,
                    pages_csv=pages_csv,
                    dish_name=merged_recipe.dish_name,
                    ingredients=merged_recipe.ingredients,
                    instructions=merged_recipe.instructions,
                    description=merged_recipe.description,
                    prep_time=merged_recipe.prep_time,
                    cook_time=merged_recipe.cook_time,
                    merge_comments=merged_recipe.merge_comments,
                    language=merged_recipe.language,
                    cluster_type=merged_recipe.cluster_type,
                    gpt_validated=merged_recipe.gpt_validated,
                    score_threshold=merged_recipe.score_threshold
                )
                new_recipes.append(merged_recipe_orm)
                
                # Сохраняем image_ids для последующей связки
                if merged_recipe.image_ids:
                    recipe_image_mapping[merged_recipe_orm] = merged_recipe.image_ids
            
            if new_recipes:
                # Bulk insert с добавлением в сессию
                session.add_all(new_recipes)
                session.commit()
                
                # Обновляем ID для возврата и собираем связи для промежуточной таблицы
                image_links = []
                for orm_obj in new_recipes:
                    session.refresh(orm_obj)
                    created.append(orm_obj)
                    
                    # Если есть image_ids, добавляем их в список для batch insert
                    if orm_obj in recipe_image_mapping:
                        image_ids = recipe_image_mapping[orm_obj]
                        for img_id in image_ids:
                            image_links.append({
                                'merged_recipe_id': orm_obj.id,
                                'image_id': img_id
                            })
                
                # Batch insert связей в merged_recipe_images
                if image_links:
                    stmt = insert(merged_recipe_images).values(image_links)
                    session.execute(stmt)
                    session.commit()
                    logger.info(f"✓ Добавлено {len(image_links)} связей с изображениями")
                
                logger.info(f"✓ Создано {len(created)} новых объединенных рецептов")
            else:
                logger.info("Все рецепты уже существуют, новых не создано")
            
            return created
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка batch создания объединенных рецептов: {e}")
            raise
        finally:
            session.close()
    
    def get_by_pages_hash(self, pages_hash: str) -> Optional[MergedRecipeORM]:
        """
        Получить объединенный рецепт по хэшу страниц
        
        Args:
            pages_hash: SHA256 хэш списка page_ids
        
        Returns:
            MergedRecipeORM или None
        """
        session = self.get_session()
        try:
            return session.query(MergedRecipeORM).filter(
                MergedRecipeORM.pages_hash_sha256 == pages_hash
            ).first()
        finally:
            session.close()
    
    def get_by_page_ids(self, page_ids: list[int]) -> Optional[MergedRecipeORM]:
        """
        Получить объединенный рецепт по списку page_ids
        
        Args:
            page_ids: Список ID страниц
        
        Returns:
            MergedRecipeORM или None
        """
        sorted_ids = sorted(page_ids)
        pages_csv = ','.join(map(str, sorted_ids))
        pages_hash = hashlib.sha256(pages_csv.encode()).hexdigest()
        
        return self.get_by_pages_hash(pages_hash)
    
    def get_all(self, limit = None, offset = 0):
        return super().get_all(limit, offset)
    
    # Методы для работы с промежуточной таблицей merged_recipe_images
    
    def add_images_to_recipe(
        self,
        merged_recipe_id: int,
        image_ids: List[int]
    ) -> int:
        """
        Привязать изображения к объединенному рецепту
        
        Args:
            merged_recipe_id: ID объединенного рецепта
            image_ids: Список ID изображений
        
        Returns:
            Количество добавленных связей
        """
        if not image_ids:
            return 0
        
        session = self.get_session()
        try:
            # Проверяем существование рецепта
            recipe = session.query(MergedRecipeORM).filter(
                MergedRecipeORM.id == merged_recipe_id
            ).first()
            
            if not recipe:
                raise ValueError(f"Merged recipe с id={merged_recipe_id} не найден")
            
            # Проверяем существующие связи
            existing_image_ids = {img.id for img in recipe.images}
            new_image_ids = [img_id for img_id in image_ids if img_id not in existing_image_ids]
            
            if not new_image_ids:
                logger.info(f"Все изображения уже привязаны к merged_recipe {merged_recipe_id}")
                return 0
            
            # Добавляем новые связи через промежуточную таблицу
            values = [
                {'merged_recipe_id': merged_recipe_id, 'image_id': img_id}
                for img_id in new_image_ids
            ]
            
            stmt = insert(merged_recipe_images).values(values)
            result = session.execute(stmt)
            session.commit()
            
            added_count = result.rowcount
            logger.info(f"✓ Добавлено {added_count} изображений к merged_recipe {merged_recipe_id}")
            return added_count
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка привязки изображений к merged_recipe: {e}")
            raise
        finally:
            session.close()
    
    def get_images_for_recipe(
        self,
        merged_recipe_id: int
    ) -> List[ImageORM]:
        """
        Получить все изображения для объединенного рецепта
        
        Args:
            merged_recipe_id: ID объединенного рецепта
        
        Returns:
            Список ImageORM объектов
        """
        session = self.get_session()
        try:
            recipe = session.query(MergedRecipeORM).filter(
                MergedRecipeORM.id == merged_recipe_id
            ).first()
            
            if not recipe:
                return []
            
            return recipe.images
            
        finally:
            session.close()