"""
Генератор и обработчик поисковых запросов для поиска рецептов
"""

import sys
import logging
from pathlib import Path
from typing import List, Optional
from sqlalchemy import text
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.common.db.mysql import MySQlManager
from src.common.gpt_client import GPTClient
from utils.languages import LANGUAGE_NAME_TO_CODE

logger = logging.getLogger(__name__)


class SearchQueryGenerator:
    """Генератор поисковых запросов для рецептов"""
    
    def __init__(self, max_non_searched: int = 10):
        """
            max_non_searched: Максимальное количество неиспользованных запросов в БД (если больше - не генерируем новые)
        """
        self._db = None
        self.gpt_client = GPTClient()
        self.max_non_searched = max_non_searched
    
    @property
    def db(self) -> MySQlManager:
        """Ленивое подключение к MySQL"""
        if self._db is None:
            self._db = MySQlManager()
            if not self._db.connect():
                raise ConnectionError("Не удалось подключиться к MySQL")
        return self._db
    
    def close(self):
        """Закрытие подключений"""
        if self._db:
            self._db.close()
    
    def get_query_count(self) -> int:
        """
        Получить количество поисковых запросов в БД
        
        Returns:
            Количество запросов
        """
        session = self.db.get_session()
        try:
            # Получаем количество запросов для которых не было найдено ни одной ссылки
            result = session.execute(text("SELECT COUNT(*) FROM search_query WHERE url_count = 0"))
            count = result.scalar()
            logger.info(f"Найдено {count} поисковых запросов в БД")
            return count
        finally:
            session.close()
    
    def generate_search_queries(self, count: int = 10) -> List[str]:
        """
        Генерация эффективных поисковых запросов через ChatGPT
        
        Args:
            count: Количество запросов для генерации
        
        Returns:
            Список поисковых запросов на английском
        """
        logger.info(f"Генерация {count} поисковых запросов через ChatGPT...")
        
        prompt = f"""Generate {count} effective search queries for finding recipe websites.

Return ONLY a JSON array of strings, without any additional text, explanations, or markdown formatting.

Example format:
["best chocolate cake recipe", "easy chicken dinner ideas", "vegetarian pasta recipes"]

Requirements for queries:
- Diverse (different cuisines, meal types, cooking methods)
- Mix specific and general queries
- Include popular recipe search patterns
- Focus on finding actual recipe websites

Generate {count} queries now:"""

        try:
            system_prompt = "You are a helpful assistant. Return ONLY valid JSON array of strings, without markdown code blocks or any additional text."
            
            response = self.gpt_client.request(
                system_prompt=system_prompt,
                user_prompt=prompt,
                model="gpt-4o-mini",
                temperature=0.8,
                max_tokens=500
            )
            
            # GPT должен вернуть список строк
            if isinstance(response, list):
                queries = [str(q).strip() for q in response if q]
            elif isinstance(response, dict) and 'queries' in response:
                queries = response['queries']
            else:
                logger.error(f"Неожиданный формат ответа от GPT: {type(response)}")
                return []
            
            logger.info(f"✓ Сгенерировано {len(queries)} запросов")
            return queries[:count]
            
        except Exception as e:
            logger.error(f"Ошибка генерации запросов: {e}")
            return []
    
    def translate_query(self, query: str, target_languages: List[str]) -> dict[str, str]:
        """
        Перевод поискового запроса на несколько языков через ChatGPT
        
        Args:
            query: Поисковый запрос на английском
            target_languages: Список языков для перевода
        
        Returns:
            Словарь {язык: переведенный_запрос}
        """
        logger.info(f"Перевод запроса '{query}' на {len(target_languages)} языков...")
        
        languages_str = ", ".join(target_languages)
        
        prompt = f"""Translate the following search query into these languages: {languages_str}

Original query (English): "{query}"

Return ONLY a JSON object with language names as keys and translations as values, without any additional text or markdown.

Example format:
{{"Spanish": "mejor receta de pastel de chocolate", "French": "meilleure recette de gâteau au chocolat"}}

Translate now:"""

        try:
            system_prompt = "You are a helpful translator specializing in culinary terminology. Return ONLY valid JSON object, without markdown code blocks or any additional text."
            
            response = self.gpt_client.request(
                system_prompt=system_prompt,
                user_prompt=prompt,
                model="gpt-4o-mini",
                temperature=0.3,
                max_tokens=1000
            )
            
            # GPT должен вернуть словарь переводов
            translations = {"English": query}  # Добавляем оригинал
            
            if isinstance(response, dict):
                # Если есть вложенный ключ 'translations'
                if 'translations' in response:
                    translations.update(response['translations'])
                else:
                    # Иначе сам response - это словарь переводов
                    translations.update(response)
            else:
                logger.error(f"Неожиданный формат ответа от GPT: {type(response)}")
                return {"English": query}
            
            logger.info(f"✓ Получено {len(translations)} переводов")
            return translations
            
        except Exception as e:
            logger.error(f"Ошибка перевода запроса: {e}")
            return {"English": query}
    
    def save_queries_to_db(self, queries_with_translations: dict[str, dict[str, str]]) -> int:
        """
        Сохранение запросов в БД
        
        Args:
            queries_with_translations: {original_query: {lang: translation}}
        
        Returns:
            Количество сохраненных запросов
        """
        session = self.db.get_session()
        saved_count = 0
        
        try:            
            for _, translations in queries_with_translations.items():
                for lang, query_text in translations.items():
                    # Определяем код языка (первые 2 буквы в нижнем регистре)
                    lang_code = LANGUAGE_NAME_TO_CODE.get(lang, lang)
                    
                    try:
                        # Вставка с игнорированием дубликатов
                        insert_query = text("""
                            INSERT INTO search_query (query, language)
                            VALUES (:query, :language)
                            ON DUPLICATE KEY UPDATE query = query
                        """)
                        
                        session.execute(insert_query, {
                            "query": query_text,
                            "language": lang_code
                        })
                        saved_count += 1
                    except Exception as e:
                        logger.warning(f"Ошибка сохранения запроса '{query_text}': {e}")
                        continue
            
            session.commit()
            logger.info(f"✓ Сохранено {saved_count} запросов в БД")
            return saved_count
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка сохранения запросов: {e}")
            return 0
        finally:
            session.close()
    
    def get_unsearched_queries(self, limit: Optional[int] = None) -> List[tuple[int, str, str]]:
        """
        Получить неиспользованные поисковые запросы из БД
        
        Args:
            limit: Максимальное количество запросов
        
        Returns:
            Список кортежей (id, query, language)
        """
        session = self.db.get_session()
        
        try:
            
            query = """
                SELECT id, query, language
                FROM search_query
                WHERE url_count = 0
                ORDER BY created_at ASC
            """
            
            if limit:
                query += f" LIMIT {limit}"
            
            result = session.execute(text(query))
            queries = [(row[0], row[1], row[2]) for row in result.fetchall()]
            
            logger.info(f"Найдено {len(queries)} неиспользованных запросов")
            return queries
            
        finally:
            session.close()
    
    def update_query_url_count(self, query_id: int, url_count: int):
        """
        Обновить количество найденных URL для запроса
        
        Args:
            query_id: ID запроса
            url_count: Количество найденных URL
        """
        session = self.db.get_session()
        
        try:
            update_query = text("""
                UPDATE search_query
                SET url_count = :url_count
                WHERE id = :id
            """)
            
            session.execute(update_query, {
                "id": query_id,
                "url_count": url_count
            })
            session.commit()
            logger.debug(f"✓ Обновлено url_count={url_count} для запроса ID={query_id}")
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка обновления url_count для запроса {query_id}: {e}")
        finally:
            session.close()
    
    def mark_query_as_searched(self, query_id: int, url_count: int = 0, recipe_url_count: int = 0):
        """
        Пометить запрос как использованный
        
        Args:
            query_id: ID запроса
            url_count: Количество найденных URL
            recipe_url_count: Количество URL с рецептами
        """
        session = self.db.get_session()
        
        try:
            
            update_query = text("""
                UPDATE search_query
                SET 
                    url_count = :url_count,
                    recipe_url_count = :recipe_url_count
                WHERE id = :id
            """)
            
            session.execute(update_query, {
                "id": query_id,
                "url_count": url_count,
                "recipe_url_count": recipe_url_count
            })
            session.commit()
            
        except Exception as e:
            session.rollback()
            logger.error(f"Ошибка обновления запроса {query_id}: {e}")
        finally:
            session.close()
