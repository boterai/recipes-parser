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
from src.common.gpt.gpt_client import GPTClient
from utils.languages import LANGUAGE_NAME_TO_CODE
from src.models.search_query import SearchQueryORM, SearchQuery
from src.repositories.search_query import SearchQueryRepository
from src.repositories.page import PageRepository

logger = logging.getLogger(__name__)


class SearchQueryGenerator:
    """Генератор поисковых запросов для рецептов"""
    
    def __init__(self, max_non_searched: int = 10, query_repository: SearchQueryRepository = None):
        """
            max_non_searched: Максимальное количество неиспользованных запросов в БД (если больше - не генерируем новые)
        """
        self.gpt_client = GPTClient()
        if query_repository is not None:
            self.query_repository = query_repository
        else:
            self.query_repository = SearchQueryRepository()
        self.max_non_searched = max_non_searched
        self.paage_repository = PageRepository()
    
    def close(self):
        """Закрытие подключений"""
        if self.query_repository.close():
            logger.info("Закрыто подключение к БД")
    
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
["best chocolate cake recipe", "easy chicken dinner recipe", "vegetarian pasta recipe"]

Requirements for queries:
- Diverse (different cuisines, meal types, cooking methods)
- Mix specific and general queries
- Include popular recipe search patterns
- Focus on finding actual recipe websites
- Focus on finding concrete recipe pages

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
    
    def get_queries_from_existing_recipes(self, count: int = 10) -> List[str]:
        """
        Генерация поисковых запросов на основе существующих рецептов в БД
        Берет случайные рецепты и использует их названия для поиска похожих на других сайтах
        
        Args:
            count: Количество запросов для генерации
        
        Returns:
            Список поисковых запросов (названий блюд)
        """
        logger.info(f"Генерация {count} запросов на основе существующих рецептов...")
        
        try:
            # Получаем случайные рецепты из БД с названиями
            recipes = self.paage_repository.get_recipes(
                limit=count * 2,  # Берем с запасом на случай пустых названий
                random_order=True
            )
            
            if not recipes:
                logger.warning("Нет рецептов в БД для генерации запросов")
                return []
            
            # Извлекаем названия блюд
            dish_names = []
            for recipe in recipes:
                if recipe.dish_name and len(recipe.dish_name.strip()) > 0:
                    dish_names.append(recipe.dish_name.strip())
            
            if not dish_names:
                logger.warning("Не найдено рецептов с названиями блюд")
                return []
            
            logger.info(f"✓ Получено {len(dish_names)} запросов из существующих рецептов")
            logger.info(f"  Примеры: {', '.join(dish_names[:3])}")
            
            return dish_names
            
        except Exception as e:
            logger.error(f"Ошибка генерации запросов из рецептов: {e}")
            import traceback
            traceback.print_exc()
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

Original query: "{query}"

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
        saved_count = 0
        
        try:            
            for _, translations in queries_with_translations.items():
                for lang, query_text in translations.items():
                    lang_code = LANGUAGE_NAME_TO_CODE.get(lang, lang)
                    query_orm = SearchQueryORM(
                        query=query_text,
                        language=lang_code
                    )
                    self.query_repository.upsert(query_orm)
                    saved_count += 1
            
            logger.info(f"✓ Сохранено {saved_count} запросов в БД")
            return saved_count
        except Exception as e:
            logger.error(f"Ошибка сохранения запросов: {e}")
            return 0