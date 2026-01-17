from src.common.db.clickhouse import ClickHouseManager
from src.common.gpt_client import GPTClient
from src.models.recipe import Recipe
from typing import Optional
import logging
import json
from src.models.search_config import ComponentWeights, SearchProfiles
logger = logging.getLogger(__name__)

class SearchSimilarInClickhouse:

    def __init__(self, clickhouse_db: ClickHouseManager = None):
        """
        Инициализация поиска похожих рецептов в ClickHouse
        
        Args:
            clickhouse_db: Менеджер ClickHouse (по умолчанию ClickHouseManager)
        """
        self.clickhouse_db = clickhouse_db or ClickHouseManager()
        if not self.clickhouse_db.connect():
            raise ConnectionError("Не удалось подключиться к ClickHouse")
        self.gpt_client = GPTClient()

    def search_recipe_regex_by_text_query(
        self,
        text_query: str,
        table_name: str = "recipe_en",
        limit: int = 10
    ) -> list[tuple[float, Recipe]]:
        """
        Поиск рецептов по текстовому запросу с использованием GPT для генерации regex паттернов
        
        Args:
            text_query: Текстовый запрос пользователя (например: "курица с чесноком в духовке, но не жареная")
            table_name: Имя таблицы для поиска
            limit: Максимальное количество результатов
        
        Returns:
            Список кортежей (relevance_score, Recipe)
        """
        if not text_query or not text_query.strip():
            logger.warning("Пустой текстовый запрос")
            return []
        
        try:
            # Используем GPT для генерации regex паттернов
            logger.info(f"Генерация regex паттернов для: '{text_query}'")
            
            system_prompt = """You are a search query analyzer for recipe search that generates RE2 regex patterns for ClickHouse.
Extract search parameters and generate regex patterns from user's natural language query.

IMPORTANT: ClickHouse uses RE2 regex engine. DO NOT use \\b word boundaries - they are not supported in RE2.
Instead, use (^|\\s|[^a-zA-Z]) before and ($|\\s|[^a-zA-Z]) after words for word matching.

Return ONLY valid JSON with the following structure:
{
    "dish_name": ["pattern1", "pattern2"],  // RE2 regex patterns for dish name/type
    "ingredients": ["pattern1", "pattern2"],  // RE2 regex patterns for ingredients
    "instructions": ["pattern1", "pattern2"],  // RE2 regex patterns for cooking methods
    "instructions_negatives": ["pattern1"],  // RE2 regex patterns to EXCLUDE from instructions
    "ingredients_negatives": ["pattern1"],  // RE2 regex patterns to EXCLUDE from ingredients
    "description": ["pattern1"]  // RE2 regex patterns for description
}

Rules for RE2 regex patterns:
1. DO NOT use \\b - use spaces or word boundaries manually: "(^|\\s)[Cc]hicken($|\\s|[^a-zA-Z])"
2. Use case-insensitive patterns: [Cc] for 'c', [Bb] for 'b', etc.
3. Include variations: "bake" → "(bak(e|ed|ing)|oven)"
4. For negatives, detect phrases like "not", "no", "without", "avoid"
5. Use alternation (|) for synonyms: "(chicken|poultry)"
6. Keep patterns simple - RE2 doesn't support all PCRE features
7. If a field has no values, use empty array []
8. Return ONLY the JSON object, no explanations
9. Avoid complex lookaheads/lookbehinds - RE2 has limited support

Examples:
Query: "курица с чесноком в духовке, но не жареная"
{
    "dish_name": ["[Cc]hicken", "[Pp]oultry"],
    "ingredients": ["[Cc]hicken", "[Gg]arlic"],
    "instructions": ["(bak(e|ed|ing)|oven|roast(ed|ing)?)"],
    "instructions_negatives": ["(fr(y|ied|ying)|deep.?fr(y|ied))"],
    "ingredients_negatives": [],
    "description": []
}

Query: "pasta with tomatoes without meat"
{
    "dish_name": ["[Pp]asta"],
    "ingredients": ["[Pp]asta", "[Tt]omat(o|oes)"],
    "instructions": [],
    "instructions_negatives": [],
    "ingredients_negatives": ["(meat|beef|pork|chicken|lamb)"],
    "description": []
}

Query: "quick chocolate dessert"
{
    "dish_name": ["[Dd]essert"],
    "ingredients": ["[Cc]hocolate"],
    "instructions": [],
    "instructions_negatives": [],
    "ingredients_negatives": [],
    "description": ["(quick|fast|easy)"]
}"""

            user_prompt = f'Generate regex patterns for: "{text_query}"'

            # Запрос к GPT
            search_params = self.gpt_client.request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model="gpt-4.1",
                temperature=0.1,
                max_tokens=500
            )
            
            # Вызываем full_recipe_regex_search с сгенерированными regex паттернами
            return self.full_recipe_regex_search(
                dish_name=search_params.get('dish_name') or None,
                ingredients=search_params.get('ingredients') or None,
                instructions=search_params.get('instructions') or None,
                instructions_negatives=search_params.get('instructions_negatives') or None,
                ingredients_negatives=search_params.get('ingredients_negatives') or None,
                description=search_params.get('description') or None,
                table_name=table_name,
                limit=limit
            )
            
        except Exception as e:
            logger.error(f"Ошибка при regex поиске по текстовому запросу: {e}")
            import traceback
            traceback.print_exc()
            
            # Fallback на обычный текстовый поиск
            logger.info("Использование fallback на обычный текстовый поиск")
            return self.search_recipes_by_text_query(text_query, table_name, limit)

    def search_recipes_by_text_query(
        self,
        text_query: str,
        table_name: str = "recipe_en",
        limit: int = 10
    ) -> list[tuple[float, Recipe]]:
        """
        Поиск рецептов по текстовому запросу с использованием GPT для извлечения параметров
        
        Args:
            text_query: Текстовый запрос пользователя (например: "курица с чесноком в духовке, но не жареная")
            table_name: Имя таблицы для поиска
            limit: Максимальное количество результатов
        
        Returns:
            Список кортежей (relevance_score, Recipe)
        """
        if not text_query or not text_query.strip():
            logger.warning("Пустой текстовый запрос")
            return []
        
        try:
            # Используем GPT для извлечения структурированных параметров поиска
            logger.info(f"Извлечение параметров поиска для: '{text_query}'")
            
            system_prompt = """You are a search query analyzer for recipe search. 
Extract search parameters from user's natural language query.

Return ONLY valid JSON with the following structure:
{
    "dish_name": ["keyword1", "keyword2"],  // Words related to dish name/type
    "ingredients": ["ingredient1", "ingredient2"],  // Specific ingredients mentioned
    "instructions": ["method1", "method2"],  // Cooking methods (bake, fry, roast, etc.)
    "instructions_negatives": ["method1"],  // Methods to EXCLUDE (if user says "not fried", "no baking")
    "ingredients_negatives": ["ingredient1"],  // Ingredients to EXCLUDE (if user says "no meat", "without sugar")
    "description": ["keyword1"]  // Other descriptive words (quick, easy, healthy, etc.)
}

Rules:
1. Extract keywords in English and their synonyms
2. Include method variations: "bake" → ["bake", "baked", "baking", "oven"]
3. For negatives, detect phrases like "not", "no", "without", "avoid"
4. If a field has no values, use empty array []
5. Return ONLY the JSON object, no explanations

Examples:
Query: "курица с чесноком в духовке, но не жареная"
{
    "dish_name": ["chicken"],
    "ingredients": ["chicken", "garlic"],
    "instructions": ["bake", "baked", "oven", "roast"],
    "instructions_negatives": ["fry", "fried", "deep-fry"],
    "ingredients_negatives": [],
    "description": []
}

Query: "pasta with tomatoes without meat"
{
    "dish_name": ["pasta"],
    "ingredients": ["pasta", "tomato", "tomatoes"],
    "instructions": [],
    "instructions_negatives": [],
    "ingredients_negatives": ["meat", "beef", "pork", "chicken"],
    "description": []
}"""

            user_prompt = f'Extract search parameters from: "{text_query}"'

            # Запрос к GPT
            search_params = self.gpt_client.request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model="gpt-4.1",
                temperature=0.1,
                max_tokens=500
            )
            
            # Вызываем full_recipe_search с извлеченными параметрами
            return self.full_recipe_search(
                dish_name=search_params.get('dish_name') or None,
                ingredients=search_params.get('ingredients') or None,
                instructions=search_params.get('instructions') or None,
                instructions_negatives=search_params.get('instructions_negatives') or None,
                ingredients_negatives=search_params.get('ingredients_negatives') or None,
                description=search_params.get('description') or None,
                table_name=table_name,
                limit=limit
            )
            
        except Exception as e:
            logger.error(f"Ошибка при поиске по текстовому запросу: {e}")
            import traceback
            traceback.print_exc()
            
            # Используем fallback метод
            logger.info("Использование fallback метода поиска")
            return self._fallback_text_search(text_query, table_name, limit)


    def search_recipes_by_ingredients(
        self, 
        recipe: Optional[Recipe] = None, 
        recipe_id: Optional[int] = None,
        ingredients: Optional[list[str]] = None,
        threshold: float = 0.6,
        table_name: str = "recipe_en",
        limit: int = 50
    ) -> list[tuple[float, Recipe]]:
        """
        search_cosine_recipes_by_ingredients - Поиск похожих рецептов по ингредиентам 
        с использованием косинусной меры
        
        Args:
            recipe: Рецепт для поиска похожих
            recipe_id: ID рецепта (если recipe не передан)
            threshold: Порог схожести для фильтрации результатов (0.0 - 1.0)
            limit: Максимальное количество результатов
            table_name: Имя таблицы
        
        Returns:
            Список кортежей (cosine_score, Recipe)
        """
        if recipe is None and recipe_id is None and not ingredients:
            raise ValueError("Должен быть предоставлен либо recipe, либо recipe_id, либо ingredients")
        
        # Получаем рецепт если передан только ID
        if recipe is None and recipe_id is not None:
            recipes = self.clickhouse_db.get_recipes_by_ids([recipe_id], table_name=table_name)
            if not recipes:
                logger.warning(f"Рецепт с id={recipe_id} не найден в ClickHouse")   
                return []
            recipe = recipes[0]
            ingredients = recipe.ingredients
        
        # Проверяем что есть ингредиенты
        if not ingredients:
            logger.warning(f"Рецепт ID={recipe.page_id} не содержит ингредиенто")
            return []
        
        query = f"""
            SELECT 
                page_id,
                dish_name,
                ingredients,
                description,
                instructions,
                tags,
                category,
                cook_time,
                prep_time,
                total_time,
                arraySum(arrayMap(
                    pattern -> if(arrayExists(ing -> positionCaseInsensitive(ing, pattern) > 0, ingredients), 1, 0),
                    %(target_ingredients)s)
                ) / length(%(target_ingredients)s) as matched_ingredients
            FROM {table_name}
            WHERE page_id != %(exclude_page_id)s
            AND length(ingredients) > 0
            HAVING matched_ingredients >= %(threshold)s
            ORDER BY matched_ingredients DESC
            LIMIT %(limit)s
        """
        
        params = {
            'target_ingredients': ingredients,
            'exclude_page_id': recipe.page_id if recipe else -1,
            'threshold': threshold,
            'limit': limit
        }
        
        try:
            # Выполняем запрос
            df = self.clickhouse_db.client.query_df(query, parameters=params)
            
            if len(df) == 0:
                logger.info(f"Рецепты с косинусной схожестью >= {threshold} не найдены")
                return []
            
            results = self.clickhouse_db.parse_recipes_from_dataframe(df, score_column='matched_ingredients')
            return results
            
        except Exception as e:
            logger.error(f"Ошибка поиска похожих рецептов: {e}")
            import traceback
            traceback.print_exc()
            return []

        
    def full_recipe_search(
        self,
        description: list[str] = None,
        dish_name: list[str] = None,
        instructions: list[str] = None,
        instructions_negatives: list[str] = None,
        ingredients: list[str] = None,
        ingredients_negatives: list[str] = None,
        table_name: str = "recipe_en",
        limit: int = 20
    ) -> list[tuple[float, Recipe]]:
        """
        full_recipe_search - Комплексный поиск рецептов по всем полям с нормализованной релевантностью
        
        Args:
            description: Ключевые слова для поиска в описании
            dish_name: Ключевые слова для поиска в названии блюда
            instructions: Ключевые слова для поиска в инструкциях
            instructions_negatives: Слова, которые НЕ должны быть в инструкциях
            ingredients: Ингредиенты для поиска
            ingredients_negatives: Ингредиенты, которых НЕ должно быть
            table_name: Имя таблицы
            limit: Максимальное количество результатов
        
        Returns:
            Список кортежей (relevance_score, Recipe)
            relevance_score - бал релевантности от 0 до 4 (максимум 4 - все поля совпали ингредиенты, описание, название, инструкции)
        """
        # Подготовка условий и параметров
        positive_conditions = []
        negative_conditions = []
        score_parts = []
        params = {'limit': limit}
        
        # Поиск по названию блюда
        if dish_name:
            params['dish_name_keywords'] = dish_name
            params['dish_name_count'] = len(dish_name)
            positive_conditions.append("multiSearchAnyCaseInsensitive(dish_name, %(dish_name_keywords)s) > 0")
            score_parts.append("""
                arraySum(arrayMap(
                    pos -> if(pos > 0, 1, 0),
                    multiSearchAllPositionsCaseInsensitive(dish_name, %(dish_name_keywords)s)
                )) / %(dish_name_count)s
            """)
        
        # Поиск по описанию
        if description:
            params['description_keywords'] = description
            params['description_count'] = len(description)
            positive_conditions.append("multiSearchAnyCaseInsensitive(description, %(description_keywords)s) > 0")
            score_parts.append("""
                arraySum(arrayMap(
                    pos -> if(pos > 0, 1, 0),
                    multiSearchAllPositionsCaseInsensitive(description, %(description_keywords)s)
                )) / %(description_count)s
            """)
        
        # Поиск по инструкциям
        if instructions:
            params['instructions_keywords'] = instructions
            params['instructions_count'] = len(instructions)
            positive_conditions.append("multiSearchAnyCaseInsensitive(instructions, %(instructions_keywords)s) > 0")
            score_parts.append("""
                arraySum(arrayMap(
                    pos -> if(pos > 0, 1, 0),
                    multiSearchAllPositionsCaseInsensitive(instructions, %(instructions_keywords)s)
                )) / %(instructions_count)s
            """)
        
        # Негативные условия для инструкций
        if instructions_negatives:
            params['instructions_negatives'] = instructions_negatives
            negative_conditions.append("multiSearchAnyCaseInsensitive(instructions, %(instructions_negatives)s) = 0")
        
        # Поиск по ингредиентам
        if ingredients:
            params['ingredients_keywords'] = ingredients
            params['ingredients_count'] = float(len(ingredients))
            # Быстрая проверка для WHERE: есть ли хотя бы один паттерн в ингредиентах
            positive_conditions.append("""
                arrayExists(ing -> multiSearchAnyCaseInsensitive(ing, %(ingredients_keywords)s) > 0, ingredients)
            """)
            # Точный подсчет для score: сколько паттернов найдено
            score_parts.append("""
                arraySum(arrayMap(
                    pattern -> if(arrayExists(ing -> positionCaseInsensitive(ing, pattern) > 0, ingredients), 1, 0),
                    %(ingredients_keywords)s
                )) / %(ingredients_count)s
            """)
        
        # Негативные условия для ингредиентов
        if ingredients_negatives:
            params['ingredients_negatives'] = ingredients_negatives
            negative_conditions.append("""
                NOT arrayExists(
                    pattern -> arrayExists(ing -> positionCaseInsensitive(ing, pattern) > 0, ingredients),
                    %(ingredients_negatives)s
                )
            """)
        
        if not positive_conditions and not negative_conditions:
            logger.warning("Не указаны параметры поиска")
            return []
        
        # Формируем WHERE clause: (позитивные OR) AND (негативные AND)
        where_parts = []
        if positive_conditions:
            where_parts.append("(" + " OR ".join(f"({c})" for c in positive_conditions) + ")")
        if negative_conditions:
            where_parts.extend(f"({c})" for c in negative_conditions)
        
        where_clause = " AND ".join(where_parts)
        score_calculation = " + ".join(score_parts) if score_parts else "0"
        
        query = f"""
            SELECT 
                page_id,
                dish_name,
                ingredients,
                description,
                instructions,
                tags,
                category,
                cook_time,
                prep_time,
                total_time,
                ({score_calculation}) as relevance_score
            FROM {table_name}
            WHERE {where_clause}
            HAVING relevance_score > 0
            ORDER BY relevance_score DESC
            LIMIT %(limit)s
        """
        
        try:
            df = self.clickhouse_db.client.query_df(query, parameters=params)
            
            if len(df) == 0:
                logger.info("Рецепты по заданным критериям не найдены")
                return []
            
            results = self.clickhouse_db.parse_recipes_from_dataframe(df, score_column='relevance_score')
            logger.info(f"Найдено {len(results)} рецептов (комплексный поиск)")
            return results
            
        except Exception as e:
            logger.error(f"Ошибка комплексного поиска: {e}")
            import traceback
            traceback.print_exc()
            return []

    def full_recipe_regex_search(
        self,
        description: list[str] = None,
        dish_name: list[str] = None,
        instructions: list[str] = None,
        instructions_negatives: list[str] = None,
        ingredients: list[str] = None,
        ingredients_negatives: list[str] = None,
        table_name: str = "recipe_en",
        limit: int = 20
    ) -> list[tuple[float, Recipe]]:
        """
        full_recipe_regex_search - Поиск рецептов по регулярным выражениям с подсчетом релевантности
        
        Args:
            description_regex: Список regex паттернов для описания
            dish_name_regex: Список regex паттернов для названия блюда
            instructions_regex: Список regex паттернов для инструкций
            ingredients_regex: Список regex паттернов для ингредиентов
            tag_args: Список тегов для точного поиска
            table_name: Имя таблицы
            limit: Максимальное количество результатов
        
        Returns:
            Список кортежей (relevance_score, Recipe)
        """
        # Подготовка условий
        conditions = []
        negative_conditions = []
        score_parts = []
        params = {'limit': limit}
        
        # Поиск по названию блюда (regex)
        if dish_name:
            params['dish_name_patterns'] = dish_name
            params['dish_name_count'] = len(dish_name)
            conditions.append("length(multiMatchAllIndices(dish_name, %(dish_name_patterns)s)) > 0")
            score_parts.append("length(multiMatchAllIndices(dish_name, %(dish_name_patterns)s)) / %(dish_name_count)s")
        
        # Поиск по описанию (regex)
        if description:
            params['description_patterns'] = description
            params['description_count'] = len(description)
            conditions.append("length(multiMatchAllIndices(description, %(description_patterns)s)) > 0")
            score_parts.append("length(multiMatchAllIndices(description, %(description_patterns)s)) / %(description_count)s")
        
        # Поиск по инструкциям (regex)
        if instructions:
            params['instructions_patterns'] = instructions
            params['instructions_count'] = len(instructions)
            conditions.append("length(multiMatchAllIndices(instructions, %(instructions_patterns)s)) > 0")
            score_parts.append("length(multiMatchAllIndices(instructions, %(instructions_patterns)s)) / %(instructions_count)s")
        
        # Негативные условия для инструкций (regex)
        if instructions_negatives:
            params['instructions_negatives_patterns'] = instructions_negatives
            negative_conditions.append("length(multiMatchAllIndices(instructions, %(instructions_negatives_patterns)s)) = 0")
        
        # Поиск по ингредиентам (regex)
        if ingredients:
            params['ingredients_patterns'] = ingredients
            params['ingredients_count'] = len(ingredients)
            conditions.append("""
                    arrayExists(
                        pattern -> arrayExists(ing -> match(ing, pattern), ingredients),
                        %(ingredients_patterns)s
                    )
                """)
            score_parts.append("""
                arraySum(arrayMap(
                    pattern -> if(arrayExists(ing -> match(ing, pattern), ingredients), 1, 0),
                    %(ingredients_patterns)s
                )) / %(ingredients_count)s
            """)
        
        # Негативные условия для ингредиентов (regex)
        if ingredients_negatives:
            params['ingredients_negatives_patterns'] = ingredients_negatives
            negative_conditions.append("""
                NOT arrayExists(
                    pattern -> arrayExists(ing -> match(ing, pattern), ingredients),
                    %(ingredients_negatives_patterns)s
                )
            """)
        
        if not conditions and not negative_conditions:
            logger.warning("Не указаны параметры для regex поиска")
            return []
        
        # Формируем WHERE: (позитивные OR) AND (негативные AND)
        where_parts = []
        if conditions:
            where_parts.append("(" + " OR ".join(f"({c})" for c in conditions) + ")")
        if negative_conditions:
            where_parts.extend(f"({c})" for c in negative_conditions)
        
        where_clause = " AND ".join(where_parts)
        score_calculation = " + ".join(score_parts)
        
        query = f"""
            SELECT 
                page_id,
                dish_name,
                ingredients,
                description,
                instructions,
                tags,
                category,
                cook_time,
                prep_time,
                total_time,
                ({score_calculation}) as relevance_score
            FROM {table_name}
            WHERE {where_clause}
            HAVING relevance_score > 0
            ORDER BY relevance_score DESC
            LIMIT %(limit)s
        """
        
        try:
            df = self.clickhouse_db.client.query_df(query, parameters=params)
            
            if len(df) == 0:
                logger.info("Рецепты по regex паттернам не найдены")
                return []
            
            results = self.clickhouse_db.parse_recipes_from_dataframe(df, score_column='relevance_score')
            logger.info(f"Найдено {len(results)} рецептов по regex поиску")
            return results
            
        except Exception as e:
            logger.error(f"Ошибка regex поиска: {e}")
            import traceback
            traceback.print_exc()
            return []