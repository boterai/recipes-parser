"""
Анализ HTML страниц с использованием ChatGPT API для определения полноты данных рецепта
"""

import json
import os
import logging
import time
from pathlib import Path
from typing import Optional, Any
from decimal import Decimal
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import sqlalchemy

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.common.db.mysql import MySQlManager
from src.common.gpt_client import GPTClient

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RecipeAnalyzer:
    """Анализатор HTML страниц для извлечения данных рецептов"""
    
    def __init__(self):
        """Инициализация анализатора"""
        self.db = MySQlManager()
        if not self.db.connect():
            raise ConnectionError("Не удалось подключиться к БД")
        
        self.gpt_client = GPTClient()
        logger.info("RecipeAnalyzer инициализирован")
    
    def analyze_titles_with_gpt(self, pages: dict[int, dict[str, str]]) -> list[int]:
        """
        Быстрый анализ заголовков страниц для определения вероятности рецепта
        
        Args:
            pages: Словарь формата {page_id: {"url": url, "title": title}}
            
        Returns:
            Список page_id, которые вероятно являются рецептами
        """
        if not pages:
            logger.warning("Пустой список страниц для анализа")
            return []
    
        
        # Создаем текст для анализа (построчно для лучшей читаемости)
        pages_text = json.dumps(pages, indent=2, ensure_ascii=False)
        
        system_prompt = """Ты эксперт по классификации веб-страниц кулинарных сайтов. 
Твоя задача - определить, какие страницы содержат РЕЦЕПТ ОДНОГО КОНКРЕТНОГО БЛЮДА.
Отвечаешь ТОЛЬКО валидным JSON."""
        
        user_prompt = f"""Проанализируй заголовки и URL веб-страниц. Определи, какие страницы являются рецептами ОДНОГО блюда.

СТРАНИЦЫ ДЛЯ АНАЛИЗА:
{pages_text}

КРИТЕРИИ РЕЦЕПТА (должно быть название конкретного блюда):
✓ ДА - это РЕЦЕПТ:
  - "Chocolate Chip Cookies Recipe"
  - "How to Make Perfect Lasagna"
  - "Beef Stew - Easy Recipe"
  - "Пирог с яблоками - рецепт"
  - URL содержит: /recipe/, /recipes/dish-name

✗ НЕТ - это НЕ рецепт:
  - "10 Best Desserts" (список рецептов)
  - "Dessert Recipes" (категория)
  - "About Us", "Contact", "Blog"
  - "Gallery", "News", "Article"
  - URL содержит: /category/, /about, /contact, /tag/, /author/

Верни ТОЛЬКО JSON с ID страниц, которые являются рецептами:
{{
    "recipe_ids": [1, 5, 12]
}}

ВАЖНО: 
- Возвращай массив чисел (ID)
- Если НЕТ рецептов - верни пустой массив []
- НЕ включай списки рецептов, категории, служебные страницы"""

        try:
            result = self.gpt_client.request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
            )
            
            recipe_ids = result.get("recipe_ids", [])
            logger.info(f"GPT определил {len(recipe_ids)} рецептов из {len(pages)} страниц: {recipe_ids}")
            
            return recipe_ids
            
        except Exception as e:
            logger.error(f"Ошибка анализа заголовков: {e}")
            return []
    
    def extract_text_from_html(self, html_path: str) -> Optional[str]:
        """
        Извлечение текста из HTML файла
        
        Args:
            html_path: Путь к HTML файлу
            
        Returns:
            Извлеченный текст или None при ошибке
        """
        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            soup = BeautifulSoup(html_content, 'lxml')
            
            # Удаление скриптов и стилей
            for script in soup(['script', 'style', 'nav', 'footer', 'header']):
                script.decompose()
            
            # Извлечение текста
            text = soup.get_text(separator='\n', strip=True)
            
            # Ограничение размера для API
            max_chars = 30000
            if len(text) > max_chars:
                text = text[:max_chars] + "\n... (текст обрезан)"
            
            return text
            
        except Exception as e:
            logger.error(f"Ошибка извлечения текста из {html_path}: {e}")
            return None
    
    def analyze_with_gpt(self, page_text: str, url: str) -> dict[str, Any]:
        """
        Анализ страницы с использованием ChatGPT API
        
        Args:
            page_text: Текст страницы
            url: URL страницы (для контекста)
            
        Returns:
            Словарь с результатами анализа
        """
        system_prompt = "Ты эксперт по анализу веб-страниц с рецептами. Возвращаешь только валидный JSON."
        
        user_prompt = f"""Проанализируй HTML страницу и определи, является ли это страницей рецепта.
Если это рецепт, извлеки следующие данные:

URL: {url}

ТЕКСТ СТРАНИЦЫ:
{page_text}

Верни ответ ТОЛЬКО в формате JSON со следующими полями:
{{
    "is_recipe": true/false,
    "confidence_score": 0-100 (процент уверенности),
    "dish_name": "название блюда или null",
    "description": "краткое описание рецепта/блюда или null",
    "ingredient": "список ингредиентов в формате JSON спиком [name: name, amount: amount, units: units] или null",
    "step_by_step": "пошаговая инструкция приготовления или null",
    "prep_time": "время подготовки (например, '15 minutes') или null",
    "cook_time": "время приготовления (например, '30 minutes') или null",
    "total_time": "общее время (например, '45 minutes') или null",
    "category": "категория/тип блюда (например, 'Dessert', 'Main Course') или null",
    "nutrition_info": "информация о питательной ценности в текстовом формате или null",
    "notes": "дополнительные заметки, советы, замены ингредиентов или null",
    "tags": "теги через запятую или null"
}}

ВАЖНО:
- Если поле не найдено, ставь null
- is_recipe = true только если поля ingredient, dish_name, step_by_step иначе ВСЕГДА, БЕЗ ИСКЛЮЧЕНИЙ false
- confidence_score зависит от полноты данных (100 = все поля заполнены полностью и это является рецептом)
- Для времени используй единицы измерения из текста (minutes, hours и т.д.)
- Возвращай ТОЛЬКО валидный JSON без комментариев, если каких=то полей нет - ставь null в этом поле"""

        try:
            result = self.gpt_client.request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            
            logger.info(f"GPT анализ завершен: is_recipe={result.get('is_recipe')}, confidence={result.get('confidence_score')}%")
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка запроса к GPT: {e}")
            return {
                "is_recipe": False,
                "confidence_score": 0,
                "error": str(e)
            }
    
    def update_page_analysis(self, page_id: int, analysis: dict[str, Any]) -> bool:
        """
        Обновление записи страницы с результатами анализа
        
        Args:
            page_id: ID страницы в БД
            analysis: Результаты анализа от GPT
            
        Returns:
            True при успехе, False при ошибке
        """
        session = self.db.get_session()
        
        try:
            # Подготовка данных
            ingredients = analysis.get("ingredient")
            if ingredients and isinstance(ingredients, list):
                ingredients = json.dumps(ingredients, ensure_ascii=False)
            if not isinstance(analysis.get("step_by_step"), str):
                analysis["step_by_step"] = json.dumps(analysis.get("step_by_step"), ensure_ascii=False)
            update_data = {
                "page_id": page_id,
                "is_recipe": analysis.get("is_recipe", False),
                "confidence_score": Decimal(str(analysis.get("confidence_score", 0))),
                "dish_name": analysis.get("dish_name"),
                "description": analysis.get("description"),
                "step_by_step": analysis.get("step_by_step"),
                "prep_time": analysis.get("prep_time"),
                "cook_time": analysis.get("cook_time"),
                "total_time": analysis.get("total_time"),
                "category": analysis.get("category"),
                "nutrition_info": analysis.get("nutrition_info"),
                "notes": analysis.get("notes"),
                "tags": analysis.get("tags"),
                "ingredient": ingredients
            }
            
            # SQL запрос на обновление
            sql = """
                UPDATE pages SET
                    is_recipe = :is_recipe,
                    confidence_score = :confidence_score,
                    dish_name = :dish_name,
                    description = :description,
                    ingredient = :ingredient,
                    step_by_step = :step_by_step,
                    prep_time = :prep_time,
                    cook_time = :cook_time,
                    total_time = :total_time,
                    category = :category,
                    nutrition_info = :nutrition_info,
                    notes = :notes,
                    tags = :tags
                WHERE id = :page_id
            """
            
            session.execute(sqlalchemy.text(sql), update_data)
            session.commit()
            
            logger.info(f"Страница ID {page_id} обновлена в БД")
            return True
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка обновления страницы {page_id}: {e}")
            return False
        finally:
            session.close()
    
    def analyze_page(self, page_id: int, html_path: str, url: str) -> bool:
        """
        Полный цикл анализа страницы
        
        Args:
            page_id: ID страницы в БД
            html_path: Путь к HTML файлу
            url: URL страницы
            
        Returns:
            True при успехе, False при ошибке
        """
        logger.info(f"Анализ страницы ID {page_id}: {url}")
        
        # Извлечение текста
        page_text = self.extract_text_from_html(html_path)
        if not page_text:
            logger.warning(f"Не удалось извлечь текст из {html_path}")
            return False
        
        # Анализ с GPT
        analysis = self.analyze_with_gpt(page_text, url)
        
        # Обновление БД
        return self.update_page_analysis(page_id, analysis)
    
    def filter_pages_by_titles(self, site_id: Optional[int] = None, limit: Optional[int] = None) -> tuple[list[int], list[int]]:
        """
        Предварительная фильтрация страниц по заголовкам
        
        Args:
            site_id: ID сайта (опционально)
            limit: Максимальное количество страниц для анализа
        Returns:
            Список page_id, которые вероятно являются рецептами, которые не являются рецептами
        
        """
        session = self.db.get_session()
        
        try:
            # Получение всех страниц с заголовками
            sql = """
                SELECT id, url, title
                FROM pages
                WHERE title IS NOT NULL
                AND is_recipe = FALSE
                AND confidence_score = 0
                AND pattern != '/'
            """
            
            if site_id:
                sql += f" AND site_id = {site_id}"
            
            if limit:
                sql += f" LIMIT {limit}"
            
            result = session.execute(sqlalchemy.text(sql))
            pages = result.fetchall()
            
            total = len(pages)
            logger.info(f"Найдено {total} страниц для анализа заголовков")

            pages_to_analyze = {}
            recipe_ids = []
            not_recipe_ids = set()

            
            for page_id, url, title in pages:
                not_recipe_ids.add(page_id)
                pages_to_analyze[page_id] = {"title": title, "url": url}
                if len(pages_to_analyze) >= 15: # анализируем загоовки батчами по 15 штук
                    ids = self.analyze_titles_with_gpt(pages_to_analyze)
                    recipe_ids.extend(ids)
                    not_recipe_ids.difference_update(ids)
                    pages_to_analyze = {}

            logger.info(f"После фильтрации по заголовкам осталось {len(recipe_ids)} вероятных рецептов")
            return recipe_ids, list(not_recipe_ids)
            
        except Exception as e:
            logger.error(f"Ошибка при анализе заголовков: {e}")
        finally:
            session.close()

        return [], list(not_recipe_ids)

    def mark_as_non_recipes(self, page_ids: list[int]) -> int:
        """
        Пометка страниц как не являющихся рецептами
        пометка is_recipe = FALSE, confidence_score = 10 тк вывод сделан только на оснвоании заглоовка
        
        Args:
            page_ids: Список ID страниц
            
        Returns:
            Количество обновленных записей
        """
        if not page_ids:
            return 0
        
        session = self.db.get_session()
        
        try:
            sql = """
                UPDATE pages
                SET is_recipe = FALSE,
                    confidence_score = 10
                WHERE id IN :page_ids
            """
            result = session.execute(sqlalchemy.text(sql), {"page_ids": tuple(page_ids)})
            session.commit()
            
            updated_count = result.rowcount
            logger.info(f"Помечено {updated_count} страниц как не рецепты")
            return updated_count
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при пометке не рецептов: {e}")
            return 0
        finally:
            session.close()

    def analyze_all_pages(self, site_id: Optional[int] = None, limit: Optional[int] = None, 
                          filter_by_title: bool = False, recalculate: bool = False,
                          page_ids: list = None, stop_analyse: Optional[int] = None) -> int:
        """
        Анализ всех страниц (или только указанного сайта)
        
        Args:
            site_id: ID сайта (опционально)
            limit: Максимальное количество страниц для анализа
            filter_by_title: Если True, сначала фильтрует по заголовкам
            recalculate: Если True, пересчитывает анализ для уже обработанных страниц
            page_ids: Список конкретных page_id для анализа (опционально)
            stop_analyse: Максимальное количество страниц c цептами для анализа, после которых можно прекратить анализ (опционально)
        Returns:
            Количество страниц с рецептами после анализа
        """
        session = self.db.get_session()
        recipe_page_ids = []
        no_recipe_ids = []
        if filter_by_title:
            logger.info("Начинается фильтрация страниц по заголовкам...")
            recipe_page_ids, no_recipe_ids = self.filter_pages_by_titles(site_id=site_id, limit=limit)
            logger.info(f"Фильтрация завершена. Найдено {len(recipe_page_ids)} вероятных рецептов по заголовкам.")
        
        try:
            # Получение страниц для анализа (где еще не проводился анализ)
            sql = """
                SELECT id, url, html_path
                FROM pages
                WHERE html_path IS NOT NULL
            """

            if page_ids is not None:
                ids_str = ','.join(map(str, page_ids))
                sql += f" AND id IN ({ids_str})"

            if recalculate is False:
                sql += " AND is_recipe = FALSE AND confidence_score = 0"  # анализируем только неанализированные или помеченные как не рецепты
            
            if site_id:
                sql += f" AND site_id = {site_id}"
            
            if limit and not recipe_page_ids and not page_ids:
                sql += f" LIMIT {limit}"

            if filter_by_title and recipe_page_ids: # фильтрация по ID из заголовков если не удаось получить из заголовка хоть 1 рецепт, то првоеряем все подярд
                ids_str = ','.join(map(str, recipe_page_ids))
                sql += f" AND id IN ({ids_str})"
            
            result = session.execute(sqlalchemy.text(sql))
            pages = result.fetchall()
            
            total = len(pages)
            logger.info(f"Найдено {total} страниц для анализа")
            
            success_count = 0
            recipe_count = 0
            
            for idx, (page_id, url, html_path) in enumerate(pages, 1):
                logger.info(f"\n[{idx}/{total}] Обработка страницы {page_id}")
                
                # Проверка существования файла
                if not os.path.exists(html_path):
                    logger.warning(f"Файл не найден: {html_path}")
                    continue
                
                # Анализ страницы
                if self.analyze_page(page_id, html_path, url):
                    success_count += 1
                    
                    session.commit()
                    # Проверка, является ли рецептом
                    check_sql = "SELECT is_recipe FROM pages WHERE id = :page_id"
                    is_recipe = session.execute(
                        sqlalchemy.text(check_sql), 
                        {"page_id": page_id}
                    ).fetchone()[0]
                    
                    if is_recipe:
                        recipe_count += 1

                    if stop_analyse and recipe_count >= stop_analyse:
                        logger.info(f"Достигнуто максимальное количество рецептов для анализа: {stop_analyse}. Прекращение анализа.")
                        break
                
                # Пауза между запросами к API
                if idx < total:
                    time.sleep(2)  # 2 секунды между запросами
            
            self.mark_as_non_recipes(no_recipe_ids)
            logger.info(f"\n{'='*60}")
            logger.info(f"  Обработано: {success_count}/{total}")
            logger.info(f"  Найдено рецептов: {recipe_count}")
            logger.info(f"{'='*60}")
            return recipe_count
            
        except Exception as e:
            logger.error(f"Ошибка при анализе страниц: {e}")
        finally:
            session.close()
        
        return 0

    def analyse_recipe_page_pattern(self, site_id: int, recalculate: bool = False) -> str:
        """
        Анализ URL страниц с рецептами и создание regex паттерна с помощью GPT
        
        Args:
            site_id: ID сайта
            recalculate: Пересчитать паттерн, даже если он уже есть
            
        Returns:
            Regex паттерн для поиска страниц с рецептами или пустая строка если невозможно
        """
        pattern = ""
        session = self.db.get_session()

        if not recalculate:
            # Проверка, есть ли уже паттерн в БД
            sql_check = "SELECT recipe_pattern FROM sites WHERE id = :site_id"
            result_check = session.execute(
                sqlalchemy.text(sql_check),
                {"site_id": site_id}
            ).fetchone()
            existing_pattern = result_check[0] if result_check else None
            if existing_pattern:
                logger.info(f"Паттерн уже существует для сайта ID {site_id}, пропускаем анализ.")
                return existing_pattern
        
        try:
            # Получение всех URL страниц с рецептами
            sql = f"SELECT url FROM pages WHERE is_recipe = TRUE AND site_id = {site_id}"
            result = session.execute(sqlalchemy.text(sql))
            pages = result.fetchall()
            urls = [page[0] for page in pages]
            
            if not urls:
                logger.warning(f"Нет рецептов для сайта ID {site_id}")
                return ""
            
            logger.info(f"Найдено {len(urls)} URL с рецептами для анализа паттерна")
            
            # Извлечение только path из URL (без домена)
            paths = []
            for url in urls: 
                parsed = urlparse(url)
                path: str = parsed.path
                if parsed.query:  # Если есть query параметры, добавляем их
                    path += f"?{parsed.query}"
                path = path.removesuffix('/')  # Удаляем конечный слэш для унификации
                path = path.removeprefix('/')  # Удаляем начальный слэш для унификации
                paths.append(path)
            
            # Формирование запроса к GPT
            urls_text = "\n".join(paths)
            
            system_prompt = "Ты эксперт по regex и анализу URL структур. Создаёшь точные паттерны для поиска страниц."
            
            user_prompt = f"""Проанализируй список URL страниц с рецептами и создай универсальные regex паттерны для их поиска.

ПРИМЕРЫ URL С РЕЦЕПТАМИ:
{urls_text}

Задача:
1. Найди ВСЕ возможные паттерны в структуре URL
2. Создай несколько regex паттернов, если URL имеют разную структуру
3. Если создать паттерны невозможно (URL слишком разнородные), верни пустой список

Верни ответ в формате JSON:
{{
    "patterns": [],
}}

Примеры хороших паттернов (для path без домена):
- ^/recipe/\\d+/[a-z0-9-]+/?$ - для путей типа /recipe/123/chicken-soup/
- ^/recipes/[a-z0-9-]+/?$ - для путей типа /recipes/pasta-carbonara/
- ^/[a-z0-9-]+-recipe-\\d+/?$ - для путей типа /chicken-soup-recipe-123/
- ^/gallery/[a-z0-9-]+/?$ - для путей типа /gallery/best-thanksgiving-desserts/
- ^/\\d+/[a-z0-9-]+/?$ - для путей типа /12345/beef-stew/

ВАЖНО: 
- Все примеры даны БЕЗ домена, только path
- Используй \\d+ для чисел, [a-z0-9-]+ для слов с дефисами
- Если есть разные структуры - возвращай несколько паттернов
- Возвращай ТОЛЬКО валидный JSON без markdown"""

            result = self.gpt_client.request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model="gpt-4.1",
                max_tokens=500,
                timeout=60
            )
            
            patterns = result.get('patterns', [])
            if not patterns:
                logger.warning("GPT: Не удалось создать паттерны")
                return ""
            
            confidence = result.get('confidence', 0)
            explanation = result.get('explanation', '')
            
            logger.info(f"Создано {len(patterns)} regex паттернов (уверенность {confidence}%)")
            logger.info(f"Общее объяснение: {explanation}")
            
            # Объединяем паттерны в один через | (OR)
            pattern = '|'.join(f'({p})' for p in patterns)
            
            logger.info(f"\nИтоговый паттерн (комбинированный): {pattern}")
            
            # Сохранение паттерна в БД для сайта
            update_sql = """
                UPDATE sites 
                SET recipe_pattern = :recipe_pattern 
                WHERE id = :site_id
            """
            session.execute(sqlalchemy.text(update_sql), {
                "recipe_pattern": pattern,
                "site_id": site_id
            })
            session.commit()
            logger.info(f"Паттерн сохранён в БД для сайта ID {site_id}")
            
        except Exception as e:
            logger.error(f"Ошибка при анализе шаблона страниц с рецептами: {e}")
            import traceback
            traceback.print_exc()
        finally:
            session.close()
            
        return pattern

    def cleanup_non_recipe_pages(self, site_id: int):
        """
        Удаление неиспользуемых данных из БД (например, страниц без HTML)
        """
        session = self.db.get_session()
        
        try:
            # получить страницы, которые надо удалить 
            select_paths = "SELECT html_path, metadata_path FROM pages WHERE is_recipe = FALSE AND site_id = :site_id"
            result = session.execute(sqlalchemy.text(select_paths), {"site_id": site_id})
            pages = result.fetchall()

            for html_path, metadata_path in pages:
                # Удаление HTML файла
                if html_path and os.path.exists(html_path):
                    os.remove(html_path)
                    logger.info(f"Удалён HTML файл: {html_path}")
                
                # Удаление метаданных
                if metadata_path and os.path.exists(metadata_path):
                    os.remove(metadata_path)
                    logger.info(f"Удалён файл метаданных: {metadata_path}")

            # Удаление страниц без HTML
            delete_sql = "DELETE FROM pages WHERE is_recipe = FALSE"
            result = session.execute(sqlalchemy.text(delete_sql))
            deleted_count = result.rowcount
            session.commit()
            
            logger.info(f"Удалено {deleted_count} страниц без рецептов из БД")
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка при удалении неиспользуемых данных: {e}")
        finally:
            session.close()
    
    def close(self):
        """Закрытие соединений"""
        if self.db:
            self.db.close()
        logger.info("Анализатор закрыт")


def main():

    site_id = 1  # пример site_id для анализа
    analyzer = RecipeAnalyzer()
    session = analyzer.db.get_session()
    results = session.execute(sqlalchemy.text("SELECT id from pages WHERE site_id = 1 AND is_recipe = TRUE LIMIT 2"))
    session.close()
    page_ids = [row[0] for row in results.fetchall()]
    try:
        analyzer.analyze_all_pages(site_id=site_id, page_ids=page_ids, recalculate=True)

        analyzer.analyze_all_pages(site_id=site_id, limit=15, filter_by_title=True)
        analyzer.analyze_all_pages(limit=None, filter_by_title=True)
    except KeyboardInterrupt:
        logger.info("\nПрервано пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        analyzer.close()


if __name__ == "__main__":
    main()
