"""
Анализ HTML страниц с использованием ChatGPT API для определения полноты данных рецепта
"""

import os
import logging
import json
import time
from pathlib import Path
from typing import Optional, Any
from decimal import Decimal
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import requests
from dotenv import load_dotenv
import sqlalchemy

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.common.database import DatabaseManager

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# OpenAI API настройки
GPT_API_KEY = os.getenv('GPT_API_KEY')
GPT_PROXY = os.getenv('PROXY', None)
GPT_MODEL_MINI = os.getenv('GPT_MODEL_MINI', 'gpt-4o-mini') # gpt-4o-mini

GPT_API_URL = "https://api.openai.com/v1/chat/completions"


class RecipeAnalyzer:
    """Анализатор HTML страниц для извлечения данных рецептов"""
    
    def __init__(self):
        """Инициализация анализатора"""
        self.db = DatabaseManager()
        if not self.db.connect():
            raise ConnectionError("Не удалось подключиться к БД")
        
        logger.info("RecipeAnalyzer инициализирован")
    
    def analyze_title_with_gpt(self, title: str, url: str) -> dict[str, Any]: # TODO: отпарвить на анлиз сразу все ссылки, а не по одной
        """
        Быстрый анализ заголовка страницы для определения вероятности рецепта
        
        Args:
            title: Заголовок страницы
            url: URL страницы
            
        Returns:
            Словарь с результатами: is_likely_recipe, confidence
        """
        prompt = f"""Проанализируй заголовок веб-страницы и определи, является ли это страницей с рецептом блюда (только одного блюда, а не короткий список).

URL: {url}
ЗАГОЛОВОК: {title}

Верни ответ ТОЛЬКО в формате JSON:
{{
    "is_likely_recipe": true/false,
    "confidence": 0-100,
}}

Признаки рецепта:
- Название блюда в заголовке
- Слова: recipe, рецепт, how to make, cook, приготовить
- НЕ рецепт: about, contact, login, category, gallery, news, article"""

        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {GPT_API_KEY}"
            }
            
            payload = {
                "model": GPT_MODEL_MINI,
                "messages": [
                    {
                        "role": "system",
                        "content": "Ты эксперт по классификации веб-страниц с рецептами. Отвечаешь только валидным JSON."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.1,
                "max_tokens": 200
            }
            
            proxies = {"http": GPT_PROXY, "https": GPT_PROXY} if GPT_PROXY else None
            response = requests.post(
                GPT_API_URL,
                headers=headers,
                json=payload,
                timeout=30,
                proxies=proxies
            )
            
            response.raise_for_status()
            response_data = response.json()
            result_text = response_data['choices'][0]['message']['content'].strip()
            
            # Очистка от markdown
            if result_text.startswith('```json'):
                result_text = result_text[7:]
            if result_text.startswith('```'):
                result_text = result_text[3:]
            if result_text.endswith('```'):
                result_text = result_text[:-3]
            
            result = json.loads(result_text.strip())
            return result
            
        except Exception as e:
            logger.error(f"Ошибка анализа заголовка: {e}")
            return {"is_likely_recipe": False, "confidence": 0, "reason": f"Error: {str(e)}"}
    
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
        prompt = f"""Проанализируй HTML страницу и определи, является ли это страницей рецепта.
Если это рецепт, извлеки следующие данные:

URL: {url}

ТЕКСТ СТРАНИЦЫ:
{page_text}

Верни ответ ТОЛЬКО в формате JSON со следующими полями:
{{
    "is_recipe": true/false,
    "confidence_score": 0-100 (процент уверенности),
    "dish_name": "название блюда или null",
    "ingredients": "список ингредиентов в текстовом формате или null",
    "step_by_step": "пошаговая инструкция приготовления или null",
}}

ВАЖНО:
- Если поле не найдено, ставь null
- is_recipe = true только если есть ingredients И step_by_step
- confidence_score зависит от полноты данных (100 = все поля заполнены полоностью и это является рецептом)
- Возвращай ТОЛЬКО валидный JSON без комментариев"""

        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {GPT_API_KEY}"
            }
            
            payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "system",
                        "content": "Ты эксперт по анализу веб-страниц с рецептами. Возвращаешь только валидный JSON."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.1,
            }

            proxies = None
            if GPT_PROXY:
                proxies = {
                    "http": GPT_PROXY,
                    "https": GPT_PROXY
                }
            
            response = requests.post(
                GPT_API_URL,
                headers=headers,
                json=payload,
                proxies=proxies
            )
            
            response.raise_for_status()
            
            response_data = response.json()
            result_text = response_data['choices'][0]['message']['content'].strip()
            
            # Очистка от markdown форматирования если есть
            if result_text.startswith('```json'):
                result_text = result_text[7:]
            if result_text.startswith('```'):
                result_text = result_text[3:]
            if result_text.endswith('```'):
                result_text = result_text[:-3]
            
            result = json.loads(result_text.strip())
            
            logger.info(f"GPT анализ завершен: is_recipe={result.get('is_recipe')}, confidence={result.get('confidence_score')}%")
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON от GPT: {e}")
            logger.error(f"Ответ GPT: {result_text if 'result_text' in locals() else 'N/A'}")
            return {
                "is_recipe": False,
                "confidence_score": 0,
                "error": "JSON decode error"
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка HTTP запроса к GPT: {e}")
            return {
                "is_recipe": False,
                "confidence_score": 0,
                "error": str(e)
            }
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
            update_data = {
                "page_id": page_id,
                "is_recipe": analysis.get("is_recipe", False),
                "confidence_score": Decimal(str(analysis.get("confidence_score", 0))),
                "dish_name": analysis.get("dish_name"),
                "ingredients": analysis.get("ingredients"),
                "step_by_step": analysis.get("step_by_step"),
                "prep_time": analysis.get("prep_time"),
                "cook_time": analysis.get("cook_time"),
                "total_time": analysis.get("total_time"),
                "servings": analysis.get("servings"),
                "difficulty_level": analysis.get("difficulty_level"),
                "author": analysis.get("author"),
                "category": analysis.get("category"),
                "rating": Decimal(str(analysis["rating"])) if analysis.get("rating") else None,
                "nutrition_info": analysis.get("nutrition_info")
            }
            
            # SQL запрос на обновление
            sql = """
                UPDATE pages SET
                    is_recipe = :is_recipe,
                    confidence_score = :confidence_score,
                    dish_name = :dish_name,
                    ingredients = :ingredients,
                    step_by_step = :step_by_step,
                    prep_time = :prep_time,
                    cook_time = :cook_time,
                    total_time = :total_time,
                    servings = :servings,
                    difficulty_level = :difficulty_level,
                    author = :author,
                    category = :category,
                    rating = :rating,
                    nutrition_info = :nutrition_info
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
    
    # TODO  make filtrarion with one request, not multiple
    def filter_pages_by_titles(self, site_id: Optional[int] = None, limit: Optional[int] = None) -> list[int]:
        """
        Предварительная фильтрация страниц по заголовкам
        
        Args:
            site_id: ID сайта (опционально)
            limit: Максимальное количество страниц для анализа
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
            """
            
            if site_id:
                sql += f" AND site_id = {site_id}"
            
            if limit:
                sql += f" LIMIT {limit}"
            
            result = session.execute(sqlalchemy.text(sql))
            pages = result.fetchall()
            
            total = len(pages)
            logger.info(f"Найдено {total} страниц для анализа заголовков")
            
            receipes = []
            
            for idx, (page_id, url, title) in enumerate(pages, 1):
                logger.info(f"\n[{idx}/{total}] Анализ заголовка: {title}")
                
                # Анализ заголовка
                result = self.analyze_title_with_gpt(title, url)
                
                if result.get('is_likely_recipe'):
                    receipes.append(page_id)
                    logger.info(f"  ✓ ВЕРОЯТНО РЕЦЕПТ (уверенность: {result.get('confidence')}%) - {result.get('reason')}")
                else:
                    logger.info(f"  ✗ Не рецепт (уверенность: {result.get('confidence')}%) - {result.get('reason')}")
                
                # Пауза между запросами
                if idx < total:
                    time.sleep(1)
            
        except Exception as e:
            logger.error(f"Ошибка при анализе заголовков: {e}")
        finally:
            session.close()

        return receipes
    # [15, 18, 19, 24, 29]
    def analyze_all_pages(self, site_id: Optional[int] = None, limit: Optional[int] = None, filter_by_title: bool = False):
        """
        Анализ всех страниц (или только указанного сайта)
        
        Args:
            site_id: ID сайта (опционально)
            limit: Максимальное количество страниц для анализа
            filter_by_title: Если True, сначала фильтрует по заголовкам
        """
        session = self.db.get_session()
        if filter_by_title:
            logger.info("Начинается фильтрация страниц по заголовкам...")
            recipe_page_ids = self.filter_pages_by_titles(site_id=site_id, limit=limit)
            logger.info(f"Фильтрация завершена. Найдено {len(recipe_page_ids)} вероятных рецептов по заголовкам.")
        
        try:
            # Получение страниц для анализа (где еще не проводился анализ)
            sql = """
                SELECT id, url, html_path
                FROM pages
                WHERE html_path IS NOT NULL
                AND is_recipe = FALSE
                AND confidence_score = 0
            """
            
            if site_id:
                sql += f" AND site_id = {site_id}"
            
            if limit:
                sql += f" LIMIT {limit}"

            if filter_by_title and recipe_page_ids:
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
                    
                    # Проверка, является ли рецептом
                    check_sql = "SELECT is_recipe FROM pages WHERE id = :page_id"
                    is_recipe = session.execute(
                        sqlalchemy.text(check_sql), 
                        {"page_id": page_id}
                    ).fetchone()[0]
                    
                    if is_recipe:
                        recipe_count += 1
                
                # Пауза между запросами к API
                if idx < total:
                    time.sleep(2)  # 2 секунды между запросами
            
            logger.info(f"\n{'='*60}")
            logger.info(f"Анализ завершен:")
            logger.info(f"  Обработано: {success_count}/{total}")
            logger.info(f"  Найдено рецептов: {recipe_count}")
            logger.info(f"{'='*60}")
            
        except Exception as e:
            logger.error(f"Ошибка при анализе страниц: {e}")
        finally:
            session.close()

    def analyse_recipe_page_pattern(self, site_id: int, recalculate: bool = False) -> str:
        """
        Анализ URL страниц с рецептами и создание regex паттерна с помощью GPT
        
        Args:
            site_id: ID сайта
            
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
            
            prompt = f"""Проанализируй список URL страниц с рецептами и создай универсальные regex паттерны для их поиска.

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

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {GPT_API_KEY}"
            }
            
            payload = {
                "model": "gpt-4.1",
                "messages": [
                    {
                        "role": "system",
                        "content": "Ты эксперт по regex и анализу URL структур. Создаёшь точные паттерны для поиска страниц."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.1,
                "max_tokens": 500
            }
            
            proxies = {"http": GPT_PROXY, "https": GPT_PROXY} if GPT_PROXY else None
            response = requests.post(
                GPT_API_URL,
                headers=headers,
                json=payload,
                timeout=60,
                proxies=proxies
            )
            
            response.raise_for_status()
            response_data = response.json()
            result_text = response_data['choices'][0]['message']['content'].strip()
            
            # Очистка от markdown
            if result_text.startswith('```json'):
                result_text = result_text[7:]
            if result_text.startswith('```'):
                result_text = result_text[3:]
            if result_text.endswith('```'):
                result_text = result_text[:-3]
            
            result = json.loads(result_text.strip())
            
            patterns = result.get('patterns', [])
            if not patterns:
                logger.warning("GPT: Не удалось создать паттерны")
                return []
            
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
            
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON от GPT: {e}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка запроса к GPT: {e}")
        except Exception as e:
            logger.error(f"Ошибка при анализе шаблона страниц с рецептами: {e}")
            import traceback
            traceback.print_exc()
        finally:
            session.close()
            
        return pattern

    def delete_unused_data(self, site_id: int):
        """
        Удаление неиспользуемых данных из БД (например, страниц без HTML)
        """
        session = self.db.get_session()
        
        try:
            # получить страницы, которые надо удалить 
            select_paths = "SELECT html_path, metadata_path FROM pages WHERE is_recipe = FALSE AND site_id = :site_id"
            result = session.execute(sqlalchemy.text(select_paths, {"site_id": site_id}))
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
    """Главная функция"""
    
    analyzer = RecipeAnalyzer()

    try:
        #analyzer.delete_unused_data()
        pattern = analyzer.analyse_recipe_page_pattern(site_id=1)
        analyzer.analyze_all_pages(limit=None, filter_by_title=True)
    except KeyboardInterrupt:
        logger.info("\nПрервано пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        analyzer.close()


if __name__ == "__main__":
    main()
