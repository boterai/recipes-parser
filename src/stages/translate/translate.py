import sys
import time
import json
import random
from pathlib import Path
from typing import  Optional
import logging
import asyncio

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.common.db.clickhouse import ClickHouseManager
from src.common.gpt.client import GPTClient
from src.models.page import Page, PageORM
from src.models.page import Recipe
from utils.languages import LanguageCodes, validate_and_normalize_language
from src.repositories.page import PageRepository

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
    
        self.olap_db = ClickHouseManager()
        self.page_repository = PageRepository()
        
        self.olap_table = f"recipe_{self.target_language}"
        # Инициализация GPT клиента
        self.gpt_client = GPTClient()

        with open("src/models/schemas/translated_recipe.json", "r", encoding="utf-8") as f:
            self.translation_schema = json.load(f)

        if self.olap_db.connect() is False:
            logger.error("Не удалось подключиться к ClickHouse")
            raise RuntimeError("ClickHouse connection failed")
        
    async def translate_and_save_batch(self, site_id: int = None, batch_size: int = 100, start_from_id: Optional[int] = None):
        """
        Переводит пакет страниц с рецептами для заданного site_id
        
        Args:
            site_id: ID сайта для фильтрации (если None, обрабатываются все)
            batch_size: Размер пакета для обработки
            start_from_id: ID страницы, с которой начать обработку (для продолжения)
        """
        # Если указан start_from_id, работаем в режиме последовательной обработки
        if start_from_id is not None:
            await self._sequential_translate(site_id, batch_size, start_from_id)
            return
        
        # сравниваем ID из OLAP и MySQL
        logger.info(f"Получение списка непереведенных страниц для site_id={site_id}...")
        
        # Получаем все ID из ClickHouse (уже переведенные)
        translated_ids = set(self.olap_db.get_page_ids_by_site(site_id=site_id, table_name=self.olap_table))
        logger.info(f"Найдено {len(translated_ids)} переведенных страниц в ClickHouse")
        
        # Если нет переведенных страниц, переходим к последовательному режиму
        if len(translated_ids) == 0:
            logger.info("Нет переведенных страниц. Переход к последовательному режиму обработки...")
            await self._sequential_translate(site_id, batch_size, start_from_id=0)
            return
        
        mysql_ids = set(self.page_repository.get_recipes_ids(site_id=site_id))

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
            await self._sequential_translate(site_id, batch_size, start_from_id=min_untranslated_id)
            return
        
        # Обрабатываем только непереведенные ID батчами
        for i in range(0, len(untranslated_ids), batch_size):
            batch_ids = untranslated_ids[i:i + batch_size]
            
            with self.page_repository.get_session() as session:
                # Получаем страницы по списку ID
                pages = session.query(PageORM).filter(PageORM.id.in_(batch_ids)).order_by(PageORM.id.asc()).all()

            if pages:
                pages_data = [page.to_pydantic() for page in pages]
                logger.info(f"Обработка батча {i // batch_size + 1}/{(len(untranslated_ids) + batch_size - 1) // batch_size}")
                await self._process_batch(pages_data)
    
    async def _sequential_translate(self, site_id: int, batch_size: int, start_from_id: int):
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
            with self.page_repository.get_session() as session:
                query = session.query(PageORM).filter(PageORM.is_recipe == True, 
                                                     PageORM.ingredients != None, 
                                                     PageORM.dish_name != None,
                                                     PageORM.instructions != None, 
                                                     PageORM.id > last_processed_id)
                
                if site_id:
                    query = query.filter(PageORM.site_id == site_id)

                query = query.order_by(PageORM.id.asc()).limit(batch_size)
                pages_orm = query.all()
            
                if not pages_orm:
                    logger.info("Все страницы переведены!")
                    break
                
                pages_data = [page.to_pydantic() for page in pages_orm]
                await self._process_batch(pages_data)
                last_processed_id = pages_data[-1].id
                
                # Если получили меньше страниц чем batch_size, значит это последний батч
                if len(pages_data) < batch_size:
                    logger.info("Это был последний батч. Все страницы обработаны!")
                    break
    
    async def _process_batch(self, pages_data: list[Page]):
        """
        Вспомогательный метод для обработки батча страниц
        
        Args:
            pages_data: Список данных страниц из БД
        """
        logger.info(f"Найдено {len(pages_data)} страниц для перевода (начиная с ID={pages_data[0].id})")
        
        # Шаг 1: Переводим весь батч
        translated_recipes = []
        transaltion_tasks = []
        for i, page_data in enumerate(pages_data, 1):
            try:
                recipe = page_data.to_recipe()
                
                logger.info(f"[{i}/{len(pages_data)}] Перевод страницы ID={recipe.page_id}: {recipe.dish_name}")
                
                if page_data.language.lower() in self.lang_variations and page_data.site_id != 36:

                    translated_recipe = recipe
                    translated_recipe.list_fields_to_lower()
                    logger.info(f"✓ Страница ID={recipe.page_id} уже на целевом языке {self.target_language}")
                    if translated_recipe:
                        translated_recipes.append(translated_recipe)
                else:
                    transaltion_tasks.append(self.translate_recipe(recipe))
                
            except Exception as e:
                logger.error(f"Ошибка при переводе страницы ID={page_data}: {e}")
                continue
        
        if transaltion_tasks:
            translated_results = await asyncio.gather(*transaltion_tasks, return_exceptions=True)
            for result in translated_results:
                if isinstance(result, Exception):
                    logger.error(f"Ошибка при асинхронном переводе: {result}")
                elif result:
                    translated_recipes.append(result)
        # Шаг 2: Сохраняем весь переведенный батч в БД одной транзакцией
        if self.olap_db.insert_recipes_batch(translated_recipes, table_name=self.olap_table) == len(translated_recipes):
            logger.info(f"✓ Батч из {len(translated_recipes)} переведенных страниц успешно сохранен в ClickHouse")
        else:
            logger.warning("⚠ Частичная ошибка при сохранении батча")


    async def translate_recipe(self, recipe: Recipe) -> Optional[Recipe]:
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
1. Translate completely and accurately these fields: "dish_name", "description", "tags", "category", "ingredients_with_amounts", "instructions", "cook_time", "prep_time", "total_time".
2. Return the result in the same valid JSON format without changing the structure or adding any comments
3. If a field is null or empty, leave it as is
4. Preserve all measurements, numbers, and formatting
5. Keep the translation natural and culinary-appropriate for the target language
6. CRITICAL: Never use double quotes (") inside string values. Remove them entirely. For example: "tofu steaks" not "tofu "steaks"", use: tofu steaks. Check Instructions and Ingredients carefully.
7. Return ONLY valid JSON, no markdown formatting, no extra text
8. For "ingredients_with_amounts" field (array of objects with "name", "amount", "unit"):
   - Translate "name" (ingredient name) to the target language
   - Translate "unit" to the target language (e.g., "г" -> "g", "ложка" -> "tbsp", "стакан" -> "cup")
   - Convert string "amount" values to numbers: "whole" -> 1, "half" -> 0.5, "quarter" -> 0.25, "third" -> 0.33, "1/2" -> 0.5, "1/4" -> 0.25, "1/3" -> 0.33, "3/4" -> 0.75, "один" -> 1, "два" -> 2, "три" -> 3, "половина" -> 0.5, etc.
   - If amount is already a number, keep it unchanged
   - If amount cannot be converted to a number (e.g., "to taste", "по вкусу", "some", "немного"), use null
   - Example: {{"name": "мука", "amount": "half", "unit": "стакан"}} -> {{"name": "flour", "amount": 0.5, "unit": "cup"}}
   - Example: {{"name": "соль", "amount": "по вкусу", "unit": ""}} -> {{"name": "salt", "amount": null, "unit": ""}}
"""

            user_prompt = json.dumps(recipe_data, ensure_ascii=False)
            
            # Отправляем запрос к GPT
            response = await self.gpt_client.async_request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model="gpt-3.5-turbo",
                temperature=0.3,
                max_tokens=3000,
                response_schema=self.translation_schema
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

    async def translate_all(self, site_ids: Optional[list[int]] = None, batch_size: int = 10):
        """
        Основной метод для перевода всех страниц с рецептами
        """        
        if site_ids is None:
            site_ids = self.page_repository.get_recipe_sites()
            if not site_ids:
                logger.error("Не удалось получить список site_id с рецептами")
                return
        
        for i in site_ids:
            await self.translate_and_save_batch(site_id=i, batch_size=batch_size)
            
