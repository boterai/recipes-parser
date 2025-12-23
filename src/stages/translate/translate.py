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
from src.common.db.clickhouse import ClickHouseManager
from src.common.gpt_client import GPTClient
import sqlalchemy
from src.models.page import Page
from src.models.page import Recipe
from utils.languages import LanguageCodes, validate_and_normalize_language

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Translator:
    def __init__(self, target_language: str = 'en'):
        """
        Инициализация переводчика
        Args:
            target_language: Целевой язык для перевода (по умолчанию 'en' - английский)
        """
        # Валидация и нормализация языка
        normalized_lang = validate_and_normalize_language(target_language)
        if not normalized_lang:
            raise ValueError(
                f"Неподдерживаемый язык: '{target_language}'. "
                f"Доступные языки: {', '.join(list(LanguageCodes.keys()))}"
            )
        
        self.target_language = normalized_lang
        self.lang_variations = LanguageCodes.get(normalized_lang)
        self.lang_variations = {lang.lower() for lang in self.lang_variations}
        
        self.db = MySQlManager()
        self.olap_db = ClickHouseManager()
        
        self.olap_table = f"recipe_{self.target_language}"
        # Инициализация GPT клиента
        self.gpt_client = GPTClient()

        if self.db.connect() is False:
            logger.error("Не удалось подключиться к MySQL")
            raise RuntimeError("MySQL connection failed")

        if self.olap_db.connect() is False:
            logger.error("Не удалось подключиться к ClickHouse")
            raise RuntimeError("ClickHouse connection failed")
    
    def translate_and_save_page(self, page_id: int, overwrite: bool = False) -> Optional[Recipe]:
        """
        Переводит и сохраняет страницу с рецептом в БД
        
        Args:
            page: Объект страницы для перевода
        
        Returns:
            Переведенный объект Page или None в случае ошибки
        """

        if overwrite is False:
            recipes: Recipe = self.olap_db.get_recipes_by_ids([page_id], table_name=self.olap_table)
            if recipes:
                recipe = recipes[0]
                logger.info(f"Рецепт с ID={page_id} уже переведен и сохранен в таблице recipe_ru")
                return recipe

        # Получаем страницу из БД
        page = self.db.get_page_by_id(page_id)
        if not page:
            logger.error(f"Страница с ID={page_id} не найдена в БД")
            return None
        
        recipe = page.to_recipe()
        # Переводим страницу
        translated_recipe = self.translate_recipe(recipe)
        if not translated_recipe:
            logger.error(f"Не удалось перевести страницу с ID={page_id}")
            return None
        # Сохраняем перевод в БД
        if self.olap_db.insert_recipes_batch([translated_recipe], table_name=self.olap_table) != 1:
            logger.error(f"Ошибка при сохранении перевода страницы ID={page_id} в ClickHouse")
            return None
        return translated_recipe
        
    def translate_and_save_batch(self, site_id: int = None, batch_size: int = 100, start_from_id: Optional[int] = None):
        """
        Переводит пакет страниц с рецептами для заданного site_id
        
        Args:
            site_id: ID сайта для фильтрации (если None, обрабатываются все)
            batch_size: Размер пакета для обработки
            start_from_id: ID страницы, с которой начать обработку (для продолжения)
        """
        # Если указан start_from_id, работаем в режиме последовательной обработки
        if start_from_id is not None:
            self._sequential_translate(site_id, batch_size, start_from_id)
            return
        
        # сравниваем ID из OLAP и MySQL
        logger.info(f"Получение списка непереведенных страниц для site_id={site_id}...")
        
        # Получаем все ID из ClickHouse (уже переведенные)
        translated_ids = set(self.olap_db.get_page_ids_by_site(site_id=site_id, table_name=self.olap_table))
        logger.info(f"Найдено {len(translated_ids)} переведенных страниц в ClickHouse")
        
        # Если нет переведенных страниц, переходим к последовательному режиму
        if len(translated_ids) == 0:
            logger.info("Нет переведенных страниц. Переход к последовательному режиму обработки...")
            self._sequential_translate(site_id, batch_size, start_from_id=0)
            return
        
        # Получаем все валидные ID рецептов из MySQL
        with self.db.get_session() as session:
            query = """
                SELECT id FROM pages
                WHERE is_recipe = TRUE
                AND ingredients IS NOT NULL
                AND dish_name IS NOT NULL
                AND instructions IS NOT NULL
            """
            if site_id:
                query += f" AND site_id = {site_id}"
            query += " ORDER BY id ASC"
            
            result = session.execute(sqlalchemy.text(query))
            mysql_ids = set(row.id for row in result.fetchall())
        
        logger.info(f"Найдено {len(mysql_ids)} валидных рецептов в MySQL")
        
        # Вычисляем разницу - ID которые есть в MySQL, но нет в ClickHouse
        untranslated_ids = sorted(mysql_ids - translated_ids)
        logger.info(f"Найдено {len(untranslated_ids)} непереведенных страниц")
        
        if not untranslated_ids:
            logger.info("Все страницы уже переведены!")
            return
        
        # Если минимальный непереведенный ID больше максимального переведенного,
        # значит все новые страницы идут последовательно - переходим к sequential режиму
        max_translated_id = max(translated_ids) if translated_ids else 0
        min_untranslated_id = min(untranslated_ids)
        
        if min_untranslated_id > max_translated_id:
            logger.info(f"Все непереведенные страницы (начиная с ID={min_untranslated_id}) идут после переведенных (до ID={max_translated_id})")
            logger.info("Переход к последовательному режиму обработки...")
            self._sequential_translate(site_id, batch_size, start_from_id=min_untranslated_id)
            return
        
        # Обрабатываем только непереведенные ID батчами
        for i in range(0, len(untranslated_ids), batch_size):
            batch_ids = untranslated_ids[i:i + batch_size]
            
            with self.db.get_session() as session:
                # Получаем страницы по списку ID
                placeholders = ','.join([f':id_{j}' for j in range(len(batch_ids))])
                query = f"""
                    SELECT * FROM pages
                    WHERE id IN ({placeholders})
                    ORDER BY id ASC
                """
                params = {f'id_{j}': page_id for j, page_id in enumerate(batch_ids)}
                
                result = session.execute(sqlalchemy.text(query), params)
                pages_data = result.fetchall()
            
            if pages_data:
                logger.info(f"Обработка батча {i // batch_size + 1}/{(len(untranslated_ids) + batch_size - 1) // batch_size}")
                self._process_batch(pages_data)
    
    def _sequential_translate(self, site_id: int, batch_size: int, start_from_id: int):
        """
        Последовательная обработка страниц начиная с указанного ID
        
        Args:
            site_id: ID сайта для фильтрации (если None, обрабатываются все)
            batch_size: Размер пакета для обработки
            start_from_id: ID страницы, с которой начать обработку
        """
        logger.info(f"Режим последовательной обработки начиная с ID={start_from_id}")
        last_processed_id = start_from_id - 1 if start_from_id > 0 else 0
        
        while True:
            with self.db.get_session() as session:
                query = """
                    SELECT * FROM pages
                    WHERE is_recipe = TRUE
                    AND ingredients IS NOT NULL
                    AND dish_name IS NOT NULL
                    AND instructions IS NOT NULL
                    AND id > :last_id
                """
                
                if site_id:
                    query += f" AND site_id = {site_id}"
                
                query += f" ORDER BY id ASC LIMIT {batch_size}"
                
                result = session.execute(sqlalchemy.text(query), {"last_id": last_processed_id})
                pages_data = result.fetchall()
            
                if not pages_data:
                    logger.info("Все страницы переведены!")
                    break
                
                self._process_batch(pages_data)
                last_processed_id = pages_data[-1].id
                
                # Если получили меньше страниц чем batch_size, значит это последний батч
                if len(pages_data) < batch_size:
                    logger.info("Это был последний батч. Все страницы обработаны!")
                    break
    
    def _process_batch(self, pages_data):
        """
        Вспомогательный метод для обработки батча страниц
        
        Args:
            pages_data: Список данных страниц из БД
        """
        logger.info(f"Найдено {len(pages_data)} страниц для перевода (начиная с ID={pages_data[0].id})")
        
        # Шаг 1: Переводим весь батч
        translated_recipes = []
        for i, page_data in enumerate(pages_data, 1):
            try:
                page_data = Page.model_validate(dict(page_data._mapping))
                recipe = page_data.to_recipe()
                
                logger.info(f"[{i}/{len(pages_data)}] Перевод страницы ID={recipe.page_id}: {recipe.dish_name}")
                
                if page_data.language.lower() in self.lang_variations:
                    translated_recipe = recipe
                    translated_recipe.list_fields_to_lower()
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
                logger.error(f"Ошибка при переводе страницы ID={page_data}: {e}")
                continue
        
        # Шаг 2: Сохраняем весь переведенный батч в БД одной транзакцией
        if self.olap_db.insert_recipes_batch(translated_recipes, table_name=self.olap_table) == len(translated_recipes):
            logger.info(f"✓ Батч из {len(translated_recipes)} переведенных страниц успешно сохранен в ClickHouse")
        else:
            logger.warning("⚠ Частичная ошибка при сохранении батча")

    def translate_recipe(self, recipe: Recipe) -> Optional[Recipe]:
        """
        Переводит данные рецепта на целевой язык
        
        Args:
            page: Объект страницы для перевода
        
        Returns:
            Новый объект Page с переведенными данными
        """
        try:
            # Подготавливаем данные для перевода
            recipe_data = recipe.to_dict_for_translation()
            # Системный промпт для перевода рецепта
            system_prompt = f"""You are a professional recipe translator. Translate the following recipe JSON to {self.target_language} language.

IMPORTANT:
1. Translate completely and accurately these fields: "dish_name", "description", "ingredients", "tags", "category", "instructions"
2. Return the result in the same JSON format without changing the structure or adding any comments
3. If a field is null or empty, leave it as is
4. Preserve all measurements, numbers, and formatting
5. Keep the translation natural and culinary-appropriate for the target language"""

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
            translated_recipe.list_fields_to_lower() # преобразуем все переведнные названия к нижнесу регистру
            
            logger.info(f"Страница ID={translated_recipe.page_id} успешно переведена")
            return translated_recipe
            
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON ответа от GPT для страницы ID={recipe.page_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка при переводе страницы ID={recipe.page_id}: {e}")
            return None
