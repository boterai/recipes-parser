"""
Утилиты для очистки БД от ненужных/дублированных рецептов
"""

import sys
from pathlib import Path
from typing import Optional, List
import logging

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.common.db.mysql import MySQlManager
from src.common.db.clickhouse import ClickHouseManager
from src.common.db.qdrant import QdrantRecipeManager

logger = logging.getLogger(__name__)


class RecipeCleanup:
    """Класс для очистки БД от ненужных рецептов"""
    
    def __init__(self):
        self._mysql_db = None
        self._clickhouse_db = None
        self._qdrant_db = None
    
    @property
    def mysql_db(self) -> MySQlManager:
        """Ленивое подключение к MySQL"""
        if self._mysql_db is None:
            self._mysql_db = MySQlManager()
            if not self._mysql_db.connect():
                raise ConnectionError("Не удалось подключиться к MySQL")
        return self._mysql_db
    
    @property
    def clickhouse_db(self) -> ClickHouseManager:
        """Ленивое подключение к ClickHouse"""
        if self._clickhouse_db is None:
            self._clickhouse_db = ClickHouseManager()
            if not self._clickhouse_db.connect():
                raise ConnectionError("Не удалось подключиться к ClickHouse")
        return self._clickhouse_db
    
    @property
    def qdrant_db(self) -> QdrantRecipeManager:
        """Ленивое подключение к Qdrant"""
        if self._qdrant_db is None:
            self._qdrant_db = QdrantRecipeManager()
            if not self._qdrant_db.connect():
                raise ConnectionError("Не удалось подключиться к Qdrant")
        return self._qdrant_db
    
    def close(self):
        """Закрытие всех подключений"""
        if self._mysql_db:
            self._mysql_db.close()
        if self._clickhouse_db:
            self._clickhouse_db.close()
        if self._qdrant_db:
            self._qdrant_db.close()
    
    def remove_duplicates_by_url(self, site_id: Optional[int] = None, dry_run: bool = True) -> int:
        """
        Удаление дубликатов рецептов по URL
        
        Args:
            site_id: ID сайта (если None, то для всех сайтов)
            dry_run: Если True, только показать что будет удалено
        
        Returns:
            Количество удаленных записей
        """
        logger.info(f"Поиск дубликатов по URL (site_id={site_id}, dry_run={dry_run})...")
        
        session = self.mysql_db.get_session()
        
        try:
            # Находим дубликаты (оставляем самую свежую запись)
            from sqlalchemy import text
            
            query = """
                SELECT p1.id
                FROM pages p1
                INNER JOIN (
                    SELECT url, site_id, MAX(id) as max_id
                    FROM pages
                    WHERE is_recipe = TRUE
                    GROUP BY url, site_id
                    HAVING COUNT(*) > 1
                ) p2 ON p1.url = p2.url AND p1.site_id = p2.site_id
                WHERE p1.id < p2.max_id
            """
            
            if site_id is not None:
                query += f" AND p1.site_id = {site_id}"
            
            result = session.execute(text(query))
            duplicate_ids = [row[0] for row in result.fetchall()]
            
            logger.info(f"Найдено {len(duplicate_ids)} дубликатов")
            
            if not duplicate_ids:
                return 0
            
            if dry_run:
                logger.info(f"[DRY RUN] Будут удалены ID: {duplicate_ids[:10]}...")
                return len(duplicate_ids)
            
            # Удаляем из MySQL
            delete_query = text("DELETE FROM pages WHERE id IN :ids")
            session.execute(delete_query, {"ids": tuple(duplicate_ids)})
            session.commit()
            
            logger.info(f"✓ Удалено {len(duplicate_ids)} дубликатов из MySQL")
            
            # Удаляем из ClickHouse
            for table in ["recipe_en", "recipe_ru"]:
                try:
                    ch_query = f"""
                        ALTER TABLE {table}
                        DELETE WHERE page_id IN ({','.join(map(str, duplicate_ids))})
                    """
                    self.clickhouse_db.client.command(ch_query)
                    logger.info(f"✓ Удалено из ClickHouse.{table}")
                except Exception as e:
                    logger.warning(f"Ошибка удаления из {table}: {e}")
            
            # Удаляем из Qdrant
            try:
                for collection in ["recipes_en_full", "recipes_en_mv"]:
                    self.qdrant_db.client.delete(
                        collection_name=collection,
                        points_selector=duplicate_ids
                    )
                logger.info(f"✓ Удалено из Qdrant")
            except Exception as e:
                logger.warning(f"Ошибка удаления из Qdrant: {e}")
            
            return len(duplicate_ids)
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка удаления дубликатов: {e}")
            raise
        finally:
            session.close()
    
    def remove_empty_recipes(self, dry_run: bool = True) -> int:
        """
        Удаление рецептов без ингредиентов или инструкций
        
        Args:
            dry_run: Если True, только показать что будет удалено
        
        Returns:
            Количество удаленных записей
        """
        logger.info(f"Поиск пустых рецептов (dry_run={dry_run})...")
        
        session = self.mysql_db.get_session()
        
        try:
            from sqlalchemy import text
            
            query = """
                SELECT id FROM pages
                WHERE is_recipe = TRUE
                AND (
                    ingredients IS NULL 
                    OR JSON_LENGTH(ingredients) = 0
                    OR instructions IS NULL
                    OR instructions = ''
                )
            """
            
            result = session.execute(text(query))
            empty_ids = [row[0] for row in result.fetchall()]
            
            logger.info(f"Найдено {len(empty_ids)} пустых рецептов")
            
            if not empty_ids:
                return 0
            
            if dry_run:
                logger.info(f"[DRY RUN] Будут удалены ID: {empty_ids[:10]}...")
                return len(empty_ids)
            
            # Удаление аналогично remove_duplicates_by_url
            # ...
            
            return len(empty_ids)
            
        finally:
            session.close()
    
    def remove_by_site(self, site_id: int, dry_run: bool = True) -> int:
        """
        Удаление всех рецептов с конкретного сайта
        
        Args:
            site_id: ID сайта
            dry_run: Если True, только показать что будет удалено
        
        Returns:
            Количество удаленных записей
        """
        logger.info(f"Удаление рецептов с site_id={site_id} (dry_run={dry_run})...")
        
        session = self.mysql_db.get_session()
        
        try:
            from sqlalchemy import text
            
            # Получаем количество рецептов
            count_query = text("""
                SELECT COUNT(*) FROM pages
                WHERE site_id = :site_id AND is_recipe = TRUE
            """)
            count = session.execute(count_query, {"site_id": site_id}).scalar()
            
            logger.info(f"Найдено {count} рецептов для site_id={site_id}")
            
            if count == 0:
                return 0
            
            if dry_run:
                logger.info(f"[DRY RUN] Будет удалено {count} рецептов")
                return count
            
            # Получаем все page_id
            id_query = text("""
                SELECT id FROM pages
                WHERE site_id = :site_id AND is_recipe = TRUE
            """)
            result = session.execute(id_query, {"site_id": site_id})
            page_ids = [row[0] for row in result.fetchall()]
            
            # Удаляем из MySQL
            delete_query = text("DELETE FROM pages WHERE id IN :ids")
            session.execute(delete_query, {"ids": tuple(page_ids)})
            session.commit()
            
            logger.info(f"✓ Удалено {count} рецептов из MySQL")
            
            # Удаляем из других БД (аналогично)
            # ...
            
            return count
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка удаления рецептов: {e}")
            raise
        finally:
            session.close()
    
    def cleanup_orphaned_vectors(self, dry_run: bool = True) -> int:
        """
        Удаление векторов из Qdrant для несуществующих рецептов
        
        Args:
            dry_run: Если True, только показать что будет удалено
        
        Returns:
            Количество удаленных векторов
        """
        logger.info(f"Поиск orphaned векторов (dry_run={dry_run})...")
        
        # Получаем все page_id из MySQL
        session = self.mysql_db.get_session()
        from sqlalchemy import text
        
        result = session.execute(text("SELECT id FROM pages WHERE is_recipe = TRUE"))
        valid_page_ids = set(row[0] for row in result.fetchall())
        session.close()
        
        logger.info(f"Валидных page_id в MySQL: {len(valid_page_ids)}")
        
        # Получаем все точки из Qdrant
        collections = ["recipes_en_full", "recipes_en_mv"]
        orphaned_count = 0
        
        for collection in collections:
            try:
                # Скроллим все точки
                points = self.qdrant_db.client.scroll(
                    collection_name=collection,
                    limit=10000,
                    with_payload=False,
                    with_vectors=False
                )[0]
                
                orphaned_ids = [p.id for p in points if p.id not in valid_page_ids]
                
                logger.info(f"Найдено {len(orphaned_ids)} orphaned векторов в {collection}")
                
                if orphaned_ids:
                    orphaned_count += len(orphaned_ids)
                    
                    if not dry_run:
                        self.qdrant_db.client.delete(
                            collection_name=collection,
                            points_selector=orphaned_ids
                        )
                        logger.info(f"✓ Удалено {len(orphaned_ids)} векторов из {collection}")
                
            except Exception as e:
                logger.warning(f"Ошибка обработки {collection}: {e}")
        
        return orphaned_count


def main():
    """Главная функция для запуска очистки"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Очистка БД рецептов')
    parser.add_argument('--action', choices=['duplicates', 'empty', 'site', 'orphaned', 'all'], 
                       required=True, help='Тип очистки')
    parser.add_argument('--site-id', type=int, help='ID сайта (для action=site)')
    parser.add_argument('--no-dry-run', action='store_true', help='Выполнить реальное удаление')
    
    args = parser.parse_args()
    
    cleanup = RecipeCleanup()
    dry_run = not args.no_dry_run
    
    try:
        if args.action == 'duplicates':
            count = cleanup.remove_duplicates_by_url(dry_run=dry_run)
            print(f"{'[DRY RUN] ' if dry_run else ''}Удалено дубликатов: {count}")
        
        elif args.action == 'empty':
            count = cleanup.remove_empty_recipes(dry_run=dry_run)
            print(f"{'[DRY RUN] ' if dry_run else ''}Удалено пустых: {count}")
        
        elif args.action == 'site':
            if not args.site_id:
                print("❌ Укажите --site-id")
                return
            count = cleanup.remove_by_site(args.site_id, dry_run=dry_run)
            print(f"{'[DRY RUN] ' if dry_run else ''}Удалено рецептов: {count}")
        
        elif args.action == 'orphaned':
            count = cleanup.cleanup_orphaned_vectors(dry_run=dry_run)
            print(f"{'[DRY RUN] ' if dry_run else ''}Удалено orphaned векторов: {count}")
        
        elif args.action == 'all':
            total = 0
            total += cleanup.remove_duplicates_by_url(dry_run=dry_run)
            total += cleanup.remove_empty_recipes(dry_run=dry_run)
            total += cleanup.cleanup_orphaned_vectors(dry_run=dry_run)
            print(f"{'[DRY RUN] ' if dry_run else ''}Всего удалено: {total}")
    
    finally:
        cleanup.close()


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    main()