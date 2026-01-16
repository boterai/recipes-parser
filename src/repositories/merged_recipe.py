"""
Репозиторий для работы с вариациями рецептов
"""

import logging
from typing import Optional

from src.repositories.base import BaseRepository
from src.models.merged_recipe import MergedRecipeORM, MergedRecipe
from src.models.page import PageORM
from src.models.merged_recipe import MergedRecipe
from src.common.db.connection import get_db_connection
import hashlib

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
                nutrition_info=merged_recipe.nutrition_info,
                prep_time=merged_recipe.prep_time,
                cook_time=merged_recipe.cook_time,
                merge_comments=merged_recipe.merge_comments
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
            recipe_by_hash = {}
            
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
                    nutrition_info=merged_recipe.nutrition_info,
                    prep_time=merged_recipe.prep_time,
                    cook_time=merged_recipe.cook_time,
                    merge_comments=merged_recipe.merge_comments
                )
                new_recipes.append(merged_recipe_orm)
            
            if new_recipes:
                # Bulk insert с добавлением в сессию
                session.add_all(new_recipes)
                session.commit()
                
                # Обновляем ID для возврата
                for orm_obj in new_recipes:
                    session.refresh(orm_obj)
                    created.append(orm_obj)
                
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
    
    def get_with_pages(self, merged_recipe_id: int) -> Optional[MergedRecipe]:
        """
        Получить объединенный рецепт с распарсенными page_ids
        
        Args:
            merged_recipe_id: ID объединенного рецепта
        
        Returns:
            MergedRecipe с заполненным page_ids
        """
        session = self.get_session()
        try:
            merged_recipe_orm = session.query(MergedRecipeORM).filter(
                MergedRecipeORM.id == merged_recipe_id
            ).first()
            
            if not merged_recipe_orm:
                return None
            
            # Создаем Pydantic модель (page_ids парсятся автоматически в from_orm)
            merged_recipe = MergedRecipe.from_orm(merged_recipe_orm)
            
            return merged_recipe
            
        finally:
            session.close()
    
    def get_pages_for_merged_recipe(self, merged_recipe_id: int) -> list[PageORM]:
        """
        Получить все страницы, связанные с объединенным рецептом
        
        Args:
            merged_recipe_id: ID объединенного рецепта
        
        Returns:
            Список PageORM
        """
        session = self.get_session()
        try:
            merged_recipe = session.query(MergedRecipeORM).filter(
                MergedRecipeORM.id == merged_recipe_id
            ).first()
            
            if not merged_recipe or not merged_recipe.pages_csv:
                return []
            
            # Парсим page_ids из CSV
            try:
                page_ids = [int(pid) for pid in merged_recipe.pages_csv.split(',') if pid.strip()]
            except (ValueError, AttributeError):
                return []
            
            # Загружаем страницы
            return session.query(PageORM).filter(
                PageORM.id.in_(page_ids)
            ).all()
        finally:
            session.close()
    
    def get_recipes_for_page(self, page_id: int) -> list[MergedRecipeORM]:
        """
        Получить все объединенные рецепты, в которых участвует данная страница
        
        Args:
            page_id: ID страницы
        
        Returns:
            Список MergedRecipeORM
        """
        session = self.get_session()
        try:
            # Поиск через LIKE в pages_csv (не самый эффективный, но работает)
            # Ищем: начало строки, середина, конец
            patterns = [
                f'{page_id},%',  # в начале
                f'%,{page_id},%',  # в середине
                f'%,{page_id}',  # в конце
                f'{page_id}'  # единственный
            ]
            
            from sqlalchemy import or_
            filters = [MergedRecipeORM.pages_csv.like(pattern) for pattern in patterns]
            
            return session.query(MergedRecipeORM).filter(or_(*filters)).all()
        finally:
            session.close()
    
    def update_merged_recipe(
        self,
        merged_recipe_id: int,
        dish_name: Optional[str] = None,
        ingredients: Optional[list[dict]] = None,
        instructions: Optional[str] = None,
        description: Optional[str] = None,
        nutrition_info: Optional[str] = None,
        prep_time: Optional[str] = None,
        cook_time: Optional[str] = None,
        merge_comments: Optional[str] = None
    ) -> Optional[MergedRecipeORM]:
        """
        Обновить объединенный рецепт
        
        Args:
            merged_recipe_id: ID объединенного рецепта
            dish_name: Новое название (опционально)
            ingredients: Новые ингредиенты (опционально)
            instructions: Новые инструкции (опционально)
            description: Новое описание (опционально)
            nutrition_info: Новая информация о питательности (опционально)
            prep_time: Новое время подготовки (опционально)
            cook_time: Новое время готовки (опционально)
            merge_comments: Новые комментарии (опционально)
        
        Returns:
            Обновленный объект MergedRecipeORM или None
        """
        session = self.get_session()
        try:
            merged_recipe = session.query(MergedRecipeORM).filter(
                MergedRecipeORM.id == merged_recipe_id
            ).first()
            
            if not merged_recipe:
                logger.warning(f"Объединенный рецепт {merged_recipe_id} не найден")
                return None
            
            # Обновляем поля
            if dish_name is not None:
                merged_recipe.dish_name = dish_name
            if ingredients is not None:
                merged_recipe.ingredients = ingredients
            if instructions is not None:
                merged_recipe.instructions = instructions
            if description is not None:
                merged_recipe.description = description
            if nutrition_info is not None:
                merged_recipe.nutrition_info = nutrition_info
            if prep_time is not None:
                merged_recipe.prep_time = prep_time
            if cook_time is not None:
                merged_recipe.cook_time = cook_time
            if merge_comments is not None:
                merged_recipe.merge_comments = merge_comments
            
            session.commit()
            session.refresh(merged_recipe)
            
            logger.info(f"✓ Объединенный рецепт {merged_recipe_id} обновлен")
            return merged_recipe
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка обновления объединенного рецепта {merged_recipe_id}: {e}")
            raise
        finally:
            session.close()
    
    def delete_merged_recipe(self, merged_recipe_id: int) -> bool:
        """
        Удалить объединенный рецепт
        
        Args:
            merged_recipe_id: ID объединенного рецепта
        
        Returns:
            True если удалено успешно
        """
        session = self.get_session()
        try:
            merged_recipe = session.query(MergedRecipeORM).filter(
                MergedRecipeORM.id == merged_recipe_id
            ).first()
            
            if not merged_recipe:
                logger.warning(f"Объединенный рецепт {merged_recipe_id} не найден")
                return False
            
            session.delete(merged_recipe)
            session.commit()
            
            logger.info(f"✓ Объединенный рецепт {merged_recipe_id} удален")
            return True
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка удаления объединенного рецепта {merged_recipe_id}: {e}")
            raise
        finally:
            session.close()
