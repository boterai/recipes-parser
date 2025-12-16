import sys
import time
import json
import random
from pathlib import Path
from typing import  Optional
import logging

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.common.db.mysql import MySQlManager
from src.common.gpt_client import GPTClient
import sqlalchemy
from src.models.page import Page
from src.models.page import Recipe

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Translator:
    def __init__(self, target_language: str = 'ru'):
        """
        Инициализация переводчика
        Args:
            target_language: Целевой язык для перевода (по умолчанию 'ru' - русский)
        """
        self.target_language = target_language
        self.table_name = f"pages_{self.target_language}"
        self.db = MySQlManager()
        
        # Инициализация GPT клиента
        self.gpt_client = GPTClient()
        
        for i in range(1, 4):  # Пытаемся подключиться 3 раза
            if self.db.connect():
                # попробовать создать таблицы, если их нет для переводов
                logger.info("Успешно подключились к БД")
                if self.create_translation_table() is False:
                    logger.error("Не удалось создать таблицу для переводов")
                    raise RuntimeError("Cannot create translation table")
                break
            else:
                logger.error("Не удалось подключиться к БД")
            if i < 3:
                logger.info("Повторная попытка подключения к БД через несколько секунд...")
            if i == 3:
                logger.error("Превышено количество попыток подключения к БД. Работа без БД невозможна")
                self.db = None
                raise RuntimeError("DB connection failed")
            time.sleep(random.uniform(4, 6))

    def create_translation_table(self) -> bool:
        """Создание таблицы для хранения переводов, если она не существует"""
        if self.db is None:
            logger.error("Нет подключения к БД. Невозможно создать таблицу переводов.")
            return False
        
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            `page_id` INT NOT NULL PRIMARY KEY,
            `description` text,
            `tags` text,
            `ingredient` text, 
            `step_by_step` text,
            `dish_name` varchar(500) DEFAULT NULL,
            `category` varchar(255) DEFAULT NULL,
            `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT `pages_s` FOREIGN KEY (`page_id`) REFERENCES `pages` (`id`) ON DELETE CASCADE
            )
            """
        
        with self.db.get_session() as session:
            try:
                session.execute(sqlalchemy.text(create_table_query))
                session.commit()
                logger.info(f"Таблица {self.table_name} успешно создана или уже существует.")
            except Exception as e:
                logger.error(f"Ошибка при создании таблицы {self.table_name}: {e}")
                session.rollback()
                return False
        
        return True
    
    def translate_and_save_page(self, page_id: int) -> Optional[Recipe]:
        """
        Переводит и сохраняет страницу с рецептом в БД
        
        Args:
            page: Объект страницы для перевода
        
        Returns:
            Переведенный объект Page или None в случае ошибки
        """

        recipe: Recipe = self.db.get_recipe_by_id(page_id, table_name=self.table_name)
        if recipe:
            logger.info(f"Рецепт с ID={page_id} уже переведен и сохранен в таблице {self.table_name}")
            return recipe

        # Получаем страницу из БД
        page = self.db.get_page_by_id(page_id)
        if not page:
            logger.error(f"Страница с ID={page_id} не найдена в БД")
            return None
        
        recipe = page.to_recipe()
        # Переводим страницу
        translated_page = self.translate_recipe(recipe)
        if not translated_page:
            logger.error(f"Не удалось перевести страницу с ID={page_id}")
            return None
        # Сохраняем перевод в БД
        if self.save_recipe(translated_page):
            logger.info(f"Перевод для страницы ID={page_id} успешно сохранен в {self.table_name}")
            return translated_page
        else:
            logger.error(f"Ошибка при сохранении перевода страницы ID={page_id}")
            return None
        
        
    def translate_and_save_batch(self, site_id: int = None, batch_size: int = 100, start_from_id: int = 0):
        """
        Переводит пакет страниц с рецептами для заданного site_id
        
        Args:
            site_id: ID сайта для фильтрации (если None, обрабатываются все)
            batch_size: Размер пакета для обработки
            start_from_id: ID страницы, с которой начать обработку (для продолжения)
        """
        last_processed_id = start_from_id
        
        while True:
            with self.db.get_session() as session:
                # Формируем запрос для получения страниц без перевода
                query = f"""
                    SELECT p.* FROM pages p
                    LEFT JOIN {self.table_name} pt ON p.id = pt.page_id
                    WHERE p.is_recipe = TRUE
                    AND p.ingredient IS NOT NULL
                    AND p.dish_name IS NOT NULL
                    AND p.step_by_step IS NOT NULL
                    AND pt.page_id IS NULL
                    AND p.id > :last_id
                """
                
                if site_id:
                    query += f" AND p.site_id = {site_id}"
                
                query += f" ORDER BY p.id ASC LIMIT {batch_size}"
                
                result = session.execute(sqlalchemy.text(query), {"last_id": last_processed_id})
                pages_data = result.fetchall()
                
                if not pages_data:
                    logger.info("Все страницы переведены!")
                    break
                
                logger.info(f"Найдено {len(pages_data)} страниц для перевода (начиная с ID={pages_data[0].id})")
                
                # Шаг 1: Переводим весь батч
                translated_recipes = []
                for i, page_data in enumerate(pages_data, 1):
                    try:
                        page_data = Page.model_validate(dict(page_data._mapping))
                        recipe = page_data.to_recipe()
                        last_processed_id = recipe.page_id
                        
                        logger.info(f"[{i}/{len(pages_data)}] Перевод страницы ID={recipe.page_id}: {recipe.dish_name}")
                        
                        if page_data.language == self.target_language:
                            translated_recipe = recipe
                            logger.info(f"✓ Страница ID={recipe.page_id} уже на целевом языке {self.target_language}")
                        else:
                            translated_recipe = self.translate_recipe(recipe)
                            # Пауза между запросами к GPT API
                            time.sleep(random.uniform(.2, 1))
                        
                        if translated_recipe:
                            translated_recipes.append(translated_recipe)
                            logger.info(f"✓ Страница ID={recipe.page_id} успешно переведена")
                        else:
                            logger.warning(f"✗ Не удалось перевести страницу ID={recipe.page_id}")
                        
                    except Exception as e:
                        logger.error(f"Ошибка при переводе страницы ID={recipe.page_id}: {e}")
                        continue
                
                # Шаг 2: Сохраняем весь переведенный батч в БД одной транзакцией
                if translated_recipes:
                    logger.info(f"Сохранение {len(translated_recipes)} переведенных рецептов в БД...")
                    saved_count = self.save_recipes_batch(translated_recipes)
                    logger.info(f"✓ Сохранено {saved_count}/{len(translated_recipes)} рецептов")
                
                logger.info(f"Обработан батч. Последний ID: {last_processed_id}")
                
                # Если получили меньше страниц чем batch_size, значит это последний батч
                if len(pages_data) < batch_size:
                    logger.info("Это был последний батч. Все страницы обработаны!")
                    break

    def save_recipe(self, recipe: Recipe) -> bool:
        """
        Переводит и сохраняет страницу с рецептом в БД
        
        Args:
            page: Объект страницы для перевода
        
        Returns:
            Переведенный объект Page или None в случае ошибки
        """
        # Сохраняем перевод в БД
        with self.db.get_session() as session:
            try:
                insert_query = sqlalchemy.text(f"""
                    INSERT INTO {self.table_name} 
                    (page_id, description, tags, ingredient, step_by_step, 
                     dish_name, category)
                    VALUES 
                    (:page_id, :description, :tags, :ingredient, :step_by_step,
                     :dish_name, :category)
                     AS new_values
                     ON DUPLICATE KEY UPDATE
                        description = new_values.description,
                        tags = new_values.tags,
                        ingredient = new_values.ingredient,
                        step_by_step = new_values.step_by_step,
                        dish_name = new_values.dish_name,
                        category = new_values.category
                """)
                
                session.execute(insert_query, recipe.to_dict())
                
                session.commit()
                logger.info(f"Перевод для страницы ID={recipe.page_id} успешно сохранен в {self.table_name}")
                return True
                
            except Exception as e:
                logger.error(f"Ошибка при сохранении перевода для страницы ID={recipe.page_id}: {e}")
                session.rollback()
                return False

    def save_recipes_batch(self, recipes: list[Recipe]) -> int:
        """
        Сохраняет батч переведенных рецептов в БД одной транзакцией
        
        Args:
            recipes: Список объектов Recipe для сохранения
        
        Returns:
            Количество успешно сохраненных рецептов
        """
        if not recipes:
            return 0
        
        with self.db.get_session() as session:
            try:
                insert_query = sqlalchemy.text(f"""
                    INSERT INTO {self.table_name} 
                    (page_id, description, tags, ingredient, step_by_step, 
                     dish_name, category)
                    VALUES 
                    (:page_id, :description, :tags, :ingredient, :step_by_step,
                     :dish_name, :category)
                     AS new_values
                     ON DUPLICATE KEY UPDATE
                        description = new_values.description,
                        tags = new_values.tags,
                        ingredient = new_values.ingredient,
                        step_by_step = new_values.step_by_step,
                        dish_name = new_values.dish_name,
                        category = new_values.category
                """)
                
                # Подготавливаем данные для batch insert
                recipes_data = [recipe.to_dict() for recipe in recipes]
                
                # Выполняем batch insert
                session.execute(insert_query, recipes_data)
                session.commit()
                
                logger.info(f"Батч из {len(recipes)} рецептов успешно сохранен в {self.table_name}")
                return len(recipes)
                
            except Exception as e:
                logger.error(f"Ошибка при сохранении батча рецептов: {e}")
                session.rollback()
                return 0

    def translate_recipe(self, recipe: Recipe) -> Optional[Recipe]:
        """
        Переводит данные рецепта на целевой язык одним запросом к GPT
        
        Args:
            page: Объект страницы для перевода
        
        Returns:
            Новый объект Page с переведенными данными
        """
        try:
            # Подготавливаем данные для перевода
            recipe_data = recipe.to_dict(required_fields=["dish_name", "description", "ingredient", "tags", "category", "step_by_step"])
            
            # Системный промпт для перевода рецепта
            system_prompt = f"""Ты переводчик рецептов. Переведи следующий JSON с рецептом на {self.target_language} язык.
ВАЖНО:
1. Переведи полностью: "dish_name", "description", "ingredient", "tags", "category", "step_by_step"
2. Верни результат в том же JSON формате, не изменяя структуру и не добавляя никаких комментариев
3. Если поле null или пустое, оставь его как есть"""

            user_prompt = json.dumps(recipe_data, ensure_ascii=False)
            
            # Отправляем запрос к GPT
            response = self.gpt_client.request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model="gpt-3.5-turbo",
                temperature=0.3,
                max_tokens=3000
            )
            
            # Парсим ответ от GPT
            if isinstance(response, dict):
                translation = response
            elif isinstance(response, str):
                translation = json.loads(response)
            else:
                logger.error(f"Неожиданный формат ответа от GPT: {type(response)}")
                return None
            
            # обновляем recipe данными перевода
            final_recipe = recipe.to_dict()
            final_recipe.update(translation)
            
            translated_recipe = Recipe(**final_recipe)
            
            logger.info(f"Страница ID={translated_recipe.page_id} успешно переведена одним запросом")
            return translated_recipe
            
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON ответа от GPT для страницы ID={recipe.page_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка при переводе страницы ID={recipe.page_id}: {e}")
            return None
