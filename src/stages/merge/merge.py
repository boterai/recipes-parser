"""
Консервативное создание вариаций рецептов из кластеров.

Стратегии:
1. Попарное объединение: каждый рецепт с каждым -> N*(N-1)/2 вариаций
2. Групповое объединение: все рецепты -> 1 улучшенная версия
3. Базовое + остальные: один базовый + улучшения от других -> 1 вариация
"""

import logging
from typing import Optional
import asyncio
import json
import math
import random
import os

if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.models.page import Recipe
from src.models.merged_recipe import MergedRecipe
from src.common.gpt.client import GPTClient
from src.common.db.clickhouse import ClickHouseManager
from src.repositories.page import PageRepository
from src.repositories.merged_recipe import MergedRecipeRepository
from src.repositories.image import ImageRepository
from src.repositories.cluster_page import ClusterPageRepository
from config.config import config

logger = logging.getLogger(__name__)

class ConservativeRecipeMerger:
    """Консервативное объединение рецептов без изменения сути"""
    
    def __init__(self):
        self.gpt_client = GPTClient()    

    def remove_equal_recipes(self, recipes: list[Recipe]) -> list[Recipe]:
        """Удаление слишком похожих рецептов из кластера"""
        unique_recipes: list[Recipe] = []
        
        for recipe in recipes:
            is_similar = False
            for u_recipe in unique_recipes:
                name_diff = self._name_difference(recipe.dish_name, u_recipe.dish_name)
                inst_diff = self._instruction_difference(recipe.instructions,u_recipe.instructions)
                ingredient_overlap = self._ingredient_overlap(recipe.ingredients, u_recipe.ingredients)
                
                if name_diff < 0.2 and inst_diff < 0.2 and ingredient_overlap > 0.95:
                    is_similar = True
                    logger.debug(f"Пропущен похожий рецепт: {recipe.dish_name} ~ {u_recipe.dish_name}")
                    break
            
            if not is_similar:
                unique_recipes.append(recipe)
        
        return unique_recipes
    
    def _ingredient_overlap(self, ings1: list[str], ings2: list[str]) -> float:
        """Вычисление доли общих ингредиентов между двумя списками"""
        set1 = set(ings1)
        set2 = set(ings2)
        
        if not set1 or not set2:
            return 0.0
        
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        return intersection / union
    
    def calculate_max_combinations(self, n: int, k: int, max_variations: int) -> int:
        """
        Вычисление максимального количества комбинаций для объединения рецептов
        """
        if n < 2:
            return 0
        max_possible_combinations = math.comb(n, k) if k <= n else 0
        return min(max_variations, max_possible_combinations)
    
    def _instruction_difference(self, s1: str, s2: str) -> float:
        """
        Оценка различия инструкций (0.0 = идентичны, 1.0 = полностью разные)
        """
        if not s1 or not s2:
            return 1.0
        
        # Пересечение ключевых слов
        words1 = set(s1.lower().split())
        words2 = set(s2.lower().split())
        
        if not words1 or not words2:
            return 1.0
        
        word_overlap = len(words1 & words2) / len(words1 | words2)
        word_diff = 1 - word_overlap
        
        # Разница в длине
        len_diff = abs(len(s1) - len(s2)) / max(len(s1), len(s2))
        
        return (len_diff + word_diff) / 2
    
    def _name_difference(self, name1: str, name2: str) -> float:
        """Оценка различия названий"""
        if not name1 or not name2:
            return 1.0
        
        n1 = set(name1.lower().split())
        n2 = set(name2.lower().split())
        
        if not n1 or not n2:
            return 1.0
        
        overlap = len(n1 & n2) / len(n1 | n2)
        return 1 - overlap
    
    def _select_best_base(self, recipes: list[Recipe]) -> Recipe:
        """
        Эвристический выбор лучшего базового рецепта
        
        Критерии (в порядке приоритета):
        1. Количество ингредиентов (больше = лучше)
        2. Длина инструкций (детальнее = лучше)
        3. Наличие времени готовки
        4. Наличие описания
        5. Короткое название (без лишних деталей)
        
        Args:
            recipes: Список рецептов
            
        Returns:
            Лучший рецепт для использования в качестве базы
        """
        def score(r: Recipe) -> tuple:
            ing_count = len(r.ingredients) if r.ingredients else 0
            inst_len = len(r.instructions) if isinstance(r.instructions, str) else len(str(r.instructions or ""))
            
            return (
                ing_count,
                inst_len,
                bool(r.cook_time or 0),
                bool(r.prep_time or 0),
                bool(r.description or 0),
                -len(r.dish_name)  # короткое название лучше
            )
        
        # Сортируем по скору (лучшие в начале)
        sorted_recipes = sorted(recipes, key=score, reverse=True)
        
        # Выбираем случайный из топ-K
        return sorted_recipes[0]
    
    async def validate_with_gpt(
        self,
        original: Recipe,
        enhanced: MergedRecipe
    ) -> tuple[bool, str]:
        """
        Валидация через GPT: не изменилась ли суть рецепта
        
        Args:
            original: Исходный рецепт
            enhanced: Улучшенный рецепт
            
        Returns:
            (валиден, причина)
        """
        system_prompt = """You are a recipe validation expert. Your job is to APPROVE recipes unless there's a critical problem.

DEFAULT: APPROVE (valid=true). Only reject for CRITICAL issues.

ALWAYS APPROVE (valid=true):
- Different ingredient amounts or proportions
- Added or removed seasonings, spices, herbs
- Different cooking times or temperatures  
- More or fewer steps in instructions
- Different cooking techniques for same result
- Added garnishes, toppings, or serving suggestions
- Different unit measurements (g vs oz, cups vs ml)
- Ingredient substitutions that make sense
- Combined or split cooking steps
- Additional tips or notes
- Missing or added optional ingredients

REJECT ONLY IF (valid=false):
- Dish became completely different type (soup → cake, salad → stew)
- ALL main ingredients removed (chicken removed from chicken soup)
- Recipe is nonsensical or impossible to execute
- Instructions contradict each other critically

When in doubt: APPROVE. The goal is combining recipes, not perfect replication.

Return JSON: {"valid": true/false, "reason": "brief reason"}"""

        orig_ings = original.ingredients[:10] if original.ingredients else []
        enh_ings = [i.get('name', '') for i in (enhanced.ingredients or [])[:10]]

        user_prompt = f"""Original: {original.dish_name}
Key ingredients: {', '.join(orig_ings[:5])}

Enhanced: {enhanced.dish_name}
Key ingredients: {', '.join(enh_ings[:5])}

Is this still the same dish type? (approve unless completely different dish)"""

        try:
            result = await self.gpt_client.async_request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1
            )
            
            return result.get('valid', True), result.get('reason', 'No reason provided')
            
        except Exception as e:
            logger.error(f"GPT validation failed: {e}")
            return True, "GPT unavailable, assuming valid"

    async def validate_images_for_recipe(
        self,
        recipe: MergedRecipe,
        image_urls: list[str],
        min_valid_ratio: float = 0.5
    ) -> list[str]:
        """
        Проверяет, подходят ли изображения к рецепту через GPT Vision.
        
        Args:
            recipe: Merged рецепт для проверки
            image_urls: Список URL изображений для проверки
            min_valid_ratio: Минимальная доля валидных изображений (по умолчанию 50%)
            
        Returns:
            (valid_urls, validation_results) - список валидных URL и детали проверки
        """
        if not image_urls:
            return []
        
        # Берём ключевые ингредиенты для проверки
        key_ingredients = [
            ing.get('name', '') 
            for ing in (recipe.ingredients or [])[:5]
            if ing.get('name')
        ]
        
        system_prompt = """You are a food image validator. Check if images match the given recipe.

For EACH image, evaluate:
1. Does the dish type match? (soup should look like soup, salad like salad, etc.)
2. Are key ingredients visible or expected in this type of dish?
3. Is it a photo of finished dish (not raw ingredients, not packaging)?

APPROVE if the image reasonably represents this type of dish.
REJECT only if:
- Completely different dish type (e.g., cake image for soup recipe)
- Not a food photo at all (landscape, person, text only)
- Raw ingredients only, not a prepared dish
- Packaging/product photo instead of cooked dish

Return JSON array with validation for each image in order:
[
  {"index": 0, "valid": true, "confidence": 0.9, "reason": "Shows prepared pasta dish with visible tomatoes"},
  {"index": 1, "valid": false, "confidence": 0.8, "reason": "Image shows raw vegetables, not cooked dish"}
]"""

        user_prompt = f"""Recipe: {recipe.dish_name}
Key ingredients: {', '.join(key_ingredients)}
Description: {(recipe.description or '')[:200]}

Validate these {len(image_urls)} images. Do they show this dish or similar?"""

        try:
            result = await self.gpt_client.async_request_with_images(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                image_urls=image_urls,
                temperature=0.1,
                max_tokens=300 + len(image_urls) * 100
            )
            
            # Парсим результат
            validation_results = result if isinstance(result, list) else []
            
            valid_urls = []
            for item in validation_results:
                idx = item.get('index', -1)
                if item.get('valid', False) and 0 <= idx < len(image_urls) and item.get('confidence', 0) >= min_valid_ratio:
                    valid_urls.append(image_urls[idx])
                    logger.debug(f"Image {idx} VALID: {item.get('reason', 'N/A')}")
                else:
                    logger.debug(f"Image {idx} REJECTED: {item.get('reason', 'N/A')}")
            
            valid_ratio = len(valid_urls) / len(image_urls) if image_urls else 0
            logger.info(f"Image validation for '{recipe.dish_name}': "
                       f"{len(valid_urls)}/{len(image_urls)} valid ({valid_ratio:.0%})")
            
            return valid_urls
            
        except Exception as e:
            logger.error(f"GPT Vision validation failed: {e}")
            # При ошибке возвращаем все изображения (fail-open)
            return image_urls

    async def select_best_images_for_recipe(
        self,
        recipe: MergedRecipe,
        image_urls: list[str],
        max_images: int = 3
    ) -> list[str]:
        """
        Выбирает лучшее изображение (или группу визуально связанных изображений) для рецепта.
        
        Возвращает несколько изображений ТОЛЬКО если они выглядят как фото одного блюда 
        с разных ракурсов (например, целиком + в разрезе + крупный план).
        НЕ возвращает смесь разных фотографий разных блюд.
        
        Args:
            recipe: Merged рецепт для проверки
            image_urls: Список URL изображений-кандидатов
            max_images: Максимальное количество изображений для возврата
            
        Returns:
            Список URL лучших изображений (1-max_images штук)
        """
        if not image_urls:
            return []
        
        if len(image_urls) == 1:
            return image_urls
        
        # Берём ключевые ингредиенты для контекста
        key_ingredients = [
            ing.get('name', '') 
            for ing in (recipe.ingredients or [])[:5]
            if ing.get('name')
        ]
        
        system_prompt = """You are a professional food photographer selecting the BEST image(s) to represent a recipe.

TASK: From the provided images, select the BEST representation of the dish.

SELECTION CRITERIA (in order of importance):
1. VISUAL APPEAL - appetizing, well-lit, good composition
2. DISH ACCURACY - clearly shows the finished dish as described
3. INGREDIENT VISIBILITY - key ingredients are visible or recognizable
4. PHOTO QUALITY - sharp, well-focused, good colors (not over/under-exposed)
5. PRESENTATION - plated nicely, appropriate serving style

MULTIPLE IMAGES RULE:
Return MORE THAN ONE image ONLY if they are clearly photos of THE SAME DISH from different angles:
- Same plate/bowl photographed from above + side view ✓
- Whole dish + close-up of the same dish ✓  
- Full portion + slice/bite showing inside ✓

DO NOT return multiple images if:
- They show DIFFERENT dishes (even if same recipe type)
- Different plating/presentation styles
- Clearly from different photo sessions
- Mix of professional and amateur photos

Return JSON:
{
  "selected_indices": [0],  // or [0, 2] if they're same dish from different angles
  "best_index": 0,  // the single BEST image
  "reasoning": "Brief explanation of why this image best represents the dish",
  "is_same_dish_series": false  // true only if multiple images show literally the same dish
}"""

        user_prompt = f"""Recipe: {recipe.dish_name}
Key ingredients: {', '.join(key_ingredients)}
Description: {(recipe.description or '')[:200]}

Select the BEST image(s) from these {len(image_urls)} options to represent this recipe.
Remember: multiple images ONLY if they're clearly the same dish photographed from different angles."""

        try:
            result = await self.gpt_client.async_request_with_images(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                image_urls=image_urls[:10],  # Лимит на количество изображений для GPT
                temperature=0.1,
                max_tokens=500
            )
            
            if not result or not isinstance(result, dict):
                logger.warning("Invalid GPT response for image selection, returning first image")
                return [image_urls[0]]
            
            selected_indices = result.get('selected_indices', [])
            best_index = result.get('best_index', 0)
            is_same_dish = result.get('is_same_dish_series', False)
            reasoning = result.get('reasoning', 'N/A')
            
            logger.info(f"Image selection for '{recipe.dish_name}': "
                       f"best={best_index}, selected={selected_indices}, "
                       f"same_dish_series={is_same_dish}, reason: {reasoning}")
            
            # Если несколько изображений, но это НЕ серия одного блюда - берём только лучшее
            if len(selected_indices) > 1 and not is_same_dish:
                logger.info(f"Multiple images selected but not same dish series, using only best (index={best_index})")
                selected_indices = [best_index]
            
            # Валидируем индексы
            valid_indices = [i for i in selected_indices if 0 <= i < len(image_urls)]
            
            if not valid_indices:
                # Fallback на best_index
                if 0 <= best_index < len(image_urls):
                    valid_indices = [best_index]
                else:
                    valid_indices = [0]
            
            # Ограничиваем количество
            valid_indices = valid_indices[:max_images]
            
            return [image_urls[i] for i in valid_indices]
            
        except Exception as e:
            logger.error(f"GPT Vision image selection failed: {e}")
            # При ошибке возвращаем первое изображение
            return [image_urls[0]] if image_urls else []

class ClusterVariationGenerator:
    """Генератор вариаций из кластера рецептов"""
    
    def __init__(self, score_threshold: float = 0.94, clusters_build_type: str = "full", max_recipes_per_gpt_merge_request: int = 3):
        self.merger = ConservativeRecipeMerger()
        self._olap_db = None
        self.page_repository = PageRepository()
        self.merge_repository = MergedRecipeRepository()
        self.image_repository = ImageRepository()
        self.cluster_page_repository = ClusterPageRepository()
        self.score_threshold = score_threshold
        self.clusters_build_type = clusters_build_type
        self.merged_recipe_schema = json.load(open("src/models/schemas/merged_recipe.json", "r", encoding="utf-8"))
        self.max_merge_recipes_per_request = max_recipes_per_gpt_merge_request # макс кол-во рецептов для передачи в 1 запросе при генерации вариации через GPT (включая базовый рецепт)

    @property
    def olap_db(self) -> ClickHouseManager:
        if not self._olap_db:
            self._olap_db = ClickHouseManager()
            if not self._olap_db.connect():
                raise ConnectionError("Не удалось подключиться к ClickHouse")
        return self._olap_db

    async def create_canonical_recipe_with_gpt(
        self, 
        existing_merged: Optional[MergedRecipe],
        base_recipe_id: int, 
        cluster_recipes: list[int], 
        target_language: Optional[str] = None,
        save_to_db: bool = True,
        max_aggregated_recipes: int = 5
    ) -> Optional[MergedRecipe]:
        """
        Генерирует каноничный рецепт для кластера через GPT, комбинируя информацию из всех рецептов кластера.
        Основывается на базовом рецепте (самой середине кластера) и добавляет элементы из других рецептов, 
        сохраняя суть блюда и не позволяя рецепту "дрейфовать".
        
        Алгоритм:
        1. Изначально выбирается базовый рецепт (самый центр по кластеру - передается извне) и если присутсвует существующий merged рецепт - он используется как основа для расширения, иначе - базовый рецепт.
        3. Если есть - проверяется какими рецептами он еще не расширен, расширяется оставшимися
        4. Если расширен всеми - ничего не делается (возвращается существующий)
        5. Если нет merge - создается новый merge рецепт на основе базового и других рецептов кластера
        6. После каждого расширения проводится валидация относительно БАЗОВОГО рецепта.
           Если валидация не пройдена - откат последнего добавления, продолжаем с другими рецептами
        
        Args:
            existing_merged: Существующий MergedRecipe для данного base_recipe_id (если есть)
            base_recipe_id: page_id базового рецепта (ближайшего к центроиду кластера)
            cluster_recipes: Список page_id рецептов кластера (включая base_recipe_id)
            target_language: Целевой язык для генерации
            save_to_db: Сохранять ли результат в БД
            max_aggregated_recipes: Максимальное количество рецептов из кластера для агрегации в один canonical (включая базовый). Если в кластере больше, будут выбраны рандомные
            
        Returns:
            MergedRecipe или None если не удалось создать
        """
        if existing_merged:
            used_page_ids = set(existing_merged.page_ids or [])

            # Находим неиспользованные рецепты
            remaining_recipes = [pid for pid in cluster_recipes if pid not in used_page_ids]
            
            if not remaining_recipes:
                logger.info(f"Canonical recipe для base_recipe_id={base_recipe_id} уже полностью расширен")
                return None
            
            max_aggregated_recipes = max(1, max_aggregated_recipes + 1 - len(used_page_ids)) # +1 для базового рецепта
            
            logger.info(f"Расширяем существующий canonical recipe {existing_merged.id} добавлением {max_aggregated_recipes} рецептов")
            
            # Расширяем существующий merged recipe
            return await self._expand_canonical_recipe(
                existing_merged=existing_merged,
                base_recipe_id=base_recipe_id,
                new_recipe_ids=remaining_recipes,
                target_language=target_language,
                save_to_db=save_to_db,
                max_aggregated_recipes=max_aggregated_recipes
            )
        
        # Создаем новый canonical recipe
        logger.info(f"Создаем новый canonical recipe для base_recipe_id={base_recipe_id}")
        return await self._create_new_canonical_recipe(
            base_recipe_id=base_recipe_id,
            cluster_recipes=cluster_recipes,
            target_language=target_language,
            save_to_db=save_to_db,
            max_aggregated_recipes=max_aggregated_recipes
        )
    
    async def create_recipe_variation(
        self,
        canonical_recipe_id: int,
        variation_source_ids: Optional[list[int]] = None,
        save_to_db: bool = True
    ) -> Optional[MergedRecipe]:
        """
        Создает вариацию существующего канонического рецепта.
        
        Публичный метод для генерации вариаций рецептов.
        Вариация - это альтернативный способ приготовления того же блюда
        (например, с другими специями, заменой ингредиентов, другим методом готовки).
        
        Args:
            canonical_recipe_id: ID канонического рецепта (из таблицы merged_recipes)
            variation_source_ids: Список page_id рецептов для создания вариации (1-5 штук)
            save_to_db: Сохранять ли результат в БД
            
        Returns:
            MergedRecipe вариации или None если не удалось создать
            
        Example:
            generator = ClusterVariationGenerator()
            
            # Создаем вариацию канонического рецепта пасты
            variation = await generator.create_recipe_variation(
                canonical_recipe_id=123,
                variation_source_ids=[456, 789],  # 2 рецепта с другими специями
                save_to_db=True
            )
        """
        # Получаем canonical recipe из БД
        canonical_orm = self.merge_repository.get_by_id(canonical_recipe_id)
        if not canonical_orm:
            logger.error(f"Canonical recipe {canonical_recipe_id} не найден в БД")
            return None
        
        canonical_recipe = canonical_orm.to_pydantic(get_images=False)

        if not variation_source_ids:
            variation_count = random.randint(1, 4) # Случайное количество рецептов для вариации

            logger.error("Нет рецептов для создания вариации, ищем подходящие рецепты для вариации...")
            possible_sources = self.cluster_page_repository.get_similar_pages(canonical_recipe.base_recipe_id)
            if not possible_sources:
                logger.error(f"Не найдено похожих рецептов для base_recipe_id={canonical_recipe.base_recipe_id}")
                return None
            
            variation_source_ids = [pid for pid in possible_sources if pid not in (canonical_recipe.page_ids or [])]
            variation_source_ids = random.sample(variation_source_ids, min(variation_count, len(variation_source_ids)))
            if len(variation_source_ids) < min(variation_count, len(possible_sources)):
                possible_sources = [pid for pid in possible_sources if pid in (canonical_recipe.page_ids or [])]
                variation_source_ids = random.sample(possible_sources, min(variation_count-len(variation_source_ids), len(possible_sources)))
                
        # Генерируем вариацию
        return await self._generate_variation_from_canonical(
            canonical_recipe=canonical_recipe,
            variation_source_ids=variation_source_ids,
            save_to_db=save_to_db
        )
    
    async def _create_new_canonical_recipe(
        self,
        base_recipe_id: int,
        cluster_recipes: list[int],
        target_language: Optional[str] = None,
        save_to_db: bool = True, 
        max_aggregated_recipes: int = 5
    ) -> Optional[MergedRecipe]:
        """Создать новый canonical recipe с нуля"""
        
        # Получаем базовый рецепт из ClickHouse
        base_recipes = self.olap_db.get_recipes_by_ids([base_recipe_id])
        if not base_recipes:
            logger.error(f"Базовый рецепт {base_recipe_id} не найден в ClickHouse")
            return None
        
        base_recipe = base_recipes[0]
        if not base_recipe.ingredients_with_amounts:
            base_recipe.fill_ingredients_with_amounts(self.page_repository)
        
        # Язык из базового рецепта или переданный
        recipe_language = target_language or base_recipe.language or 'en'
        base_recipe.language = recipe_language
        
        # Начинаем с merged recipe только из базового рецепта
        current_merged = MergedRecipe(
            page_ids=[base_recipe_id],
            base_recipe_id=base_recipe_id,
            dish_name=base_recipe.dish_name,
            description=base_recipe.description or '',
            ingredients=base_recipe.ingredients_with_amounts or [],
            instructions=[base_recipe.instructions] if base_recipe.instructions else [],
            tags=base_recipe.tags or [],
            cook_time=str(base_recipe.cook_time or ''),
            prep_time=str(base_recipe.prep_time or ''),
            merge_comments=f"canonical from base {base_recipe_id}",
            language=recipe_language,
            cluster_type=self.clusters_build_type,
            score_threshold=self.score_threshold,
            gpt_validated=True,
            merge_model=config.GPT_MODEL_MERGE
        )
        
        # Итеративно добавляем рецепты из кластера batch'ами
        other_recipe_ids = [pid for pid in cluster_recipes if pid != base_recipe_id]
        
        # Batch size = max_merge_recipes_per_request - 1 (1 слот занят canonical/base)
        batch_size = min(max_aggregated_recipes, max(1, self.max_merge_recipes_per_request - 1))
        aggregated_count = 0
        
        for i in range(0, len(other_recipe_ids), batch_size):
            batch_ids = other_recipe_ids[i:i + batch_size]
            batch_ids = batch_ids[:min(max_aggregated_recipes - aggregated_count, len(batch_ids))]  # Учитываем уже добавленные рецепты
            if not batch_ids:
                break
            
            # Пробуем расширить batch'ем
            expanded = await self._try_expand_with_recipes_batch(
                current_merged=current_merged,
                base_recipe=base_recipe,
                new_recipe_ids=batch_ids,
                target_language=recipe_language
            )
            
            if expanded:
                current_merged = expanded
                logger.info(f"✓ Canonical recipe расширен batch'ем {batch_ids}")
                aggregated_count += len(batch_ids)
            else:
                # Fallback: пробуем по одному если batch не прошёл
                logger.info(f"✗ Batch {batch_ids} не прошёл, пробуем по одному...")
                for recipe_id in batch_ids:
                    single_expanded = await self._try_expand_with_recipes_batch(
                        current_merged=current_merged,
                        base_recipe=base_recipe,
                        new_recipe_ids=[recipe_id],
                        target_language=recipe_language
                    )
                    if single_expanded:
                        current_merged = single_expanded
                        logger.info(f"✓ Canonical recipe расширен рецептом {recipe_id}")
                        aggregated_count += 1

                    else:
                        logger.info(f"✗ Рецепт {recipe_id} не прошел валидацию, пропущен")
            
            if aggregated_count >= max_aggregated_recipes:
                logger.info(f"Достигнут лимит агрегации {max_aggregated_recipes} рецептов, прекращаем расширение")
                break

        # Финальная GPT валидация перед сохранением (экономим запросы - проверяем только итоговый результат)
        if current_merged and aggregated_count > 0:
            is_valid, reason = await self.merger.validate_with_gpt(base_recipe, current_merged)
            if not is_valid:
                logger.warning(f"Финальная валидация canonical recipe не пройдена: {reason}. Возвращаем только базовый рецепт.")
                return None  # Не сохраняем рецепт, так как он не прошёл валидацию, возвращаем None
            else:
                current_merged.gpt_validated = True
        
        # Сохраняем в БД
        if save_to_db and current_merged:
            try:
                saved = self.merge_repository.create_merged_recipe(current_merged)
                current_merged.id = saved.id
                logger.info(f"✓ Canonical recipe сохранён, id={saved.id}")
            except Exception as e:
                logger.error(f"Ошибка сохранения canonical recipe: {e}")
        
        return current_merged
    
    async def _expand_canonical_recipe(
        self,
        existing_merged: MergedRecipe,
        base_recipe_id: int,
        new_recipe_ids: list[int],
        target_language: Optional[str] = None,
        save_to_db: bool = True,
        max_aggregated_recipes: int = 5
    ) -> Optional[MergedRecipe]:
        """Расширить существующий canonical recipe новыми рецептами (batch по max_merge_recipes_per_request-1)"""
        
        # Получаем базовый рецепт для валидации
        base_recipes = self.olap_db.get_recipes_by_ids([base_recipe_id])
        if not base_recipes:
            logger.error(f"Базовый рецепт {base_recipe_id} не найден")
            return existing_merged
        
        base_recipe = base_recipes[0]
        if not base_recipe.ingredients_with_amounts:
            base_recipe.fill_ingredients_with_amounts(self.page_repository)
        
        recipe_language = target_language or base_recipe.language or 'en'
        current_merged = existing_merged
        
        had_expansions = False
        # Batch size = max_merge_recipes_per_request - 1 (1 слот занят canonical/base)
        batch_size = min(max_aggregated_recipes, max(1, self.max_merge_recipes_per_request - 1))
        aggregated_count = 0

        for i in range(0, len(new_recipe_ids), batch_size):
            batch_ids = new_recipe_ids[i:i + batch_size]
            batch_ids = batch_ids[:min(max_aggregated_recipes - aggregated_count, len(batch_ids))]  # Учитываем уже добавленные рецепты
            if not batch_ids:
                break

            expanded = await self._try_expand_with_recipes_batch(
                current_merged=current_merged,
                base_recipe=base_recipe,
                new_recipe_ids=batch_ids,
                target_language=recipe_language
            )
            
            if expanded:
                current_merged = expanded
                had_expansions = True
                logger.info(f"✓ Canonical recipe расширен batch'ем {batch_ids}")
                aggregated_count += len(batch_ids)
            else:
                # Fallback: пробуем по одному если batch не прошёл
                logger.info(f"✗ Batch {batch_ids} не прошёл, пробуем по одному...")
                for recipe_id in batch_ids:
                    single_expanded = await self._try_expand_with_recipes_batch(
                        current_merged=current_merged,
                        base_recipe=base_recipe,
                        new_recipe_ids=[recipe_id],
                        target_language=recipe_language
                    )
                    if single_expanded:
                        current_merged = single_expanded
                        had_expansions = True
                        logger.info(f"✓ Canonical recipe расширен рецептом {recipe_id}")
                        aggregated_count += 1
                    else:
                        logger.info(f"✗ Рецепт {recipe_id} не прошел валидацию, пропущен")

            if aggregated_count >= max_aggregated_recipes:
                logger.info(f"Достигнут лимит агрегации {max_aggregated_recipes} рецептов, прекращаем расширение")
                break
        
        # Финальная GPT валидация перед обновлением (только если были изменения)
        if had_expansions and aggregated_count > 0:
            is_valid, reason = await self.merger.validate_with_gpt(base_recipe, current_merged)
            if not is_valid:
                logger.warning(f"Финальная валидация расширения не пройдена: {reason}. Откат изменений.")
                return None  # Не сохраняем изменения, так как итоговый рецепт не прошёл валидацию, возвращаем None
            else:
                current_merged.gpt_validated = True
                logger.info("✓ Расширенный canonical recipe прошёл финальную GPT валидацию")
        
        # Обновляем в БД если были изменения и рецепт прошел финальную валидацию
        if save_to_db and had_expansions:
            try:
                updated = self.merge_repository.update_merged_recipe(existing_merged.id, current_merged)
                if updated:
                    logger.info(f"✓ Canonical recipe {existing_merged.id} обновлен")
                    return updated.to_pydantic(get_images=False)
            except Exception as e:
                logger.error(f"Ошибка обновления canonical recipe: {e}")
        
        return current_merged
    
    async def _try_expand_with_recipes_batch(
        self,
        current_merged: MergedRecipe,
        base_recipe: Recipe,
        new_recipe_ids: list[int],
        target_language: str
    ) -> Optional[MergedRecipe]:
        """
        Попытка расширить merged recipe добавлением batch рецептов (до max_merge_recipes_per_request-1).
        Возвращает расширенный рецепт если валидация прошла, иначе None.
        """
        # Получаем новые рецепты
        new_recipes = self.olap_db.get_recipes_by_ids(new_recipe_ids)
        if not new_recipes:
            logger.warning(f"Рецепты {new_recipe_ids} не найдены в ClickHouse")
            return None
        
        for recipe in new_recipes:
            if not recipe.ingredients_with_amounts:
                recipe.fill_ingredients_with_amounts(self.page_repository)
        
        # Генерируем расширенную версию через GPT (batch)
        expanded = await self._generate_expanded_canonical(
            current_merged=current_merged,
            base_recipe=base_recipe,
            new_recipes=new_recipes,
            target_language=target_language
        )
        
        if not expanded:
            return None
        
        # Обновляем page_ids
        added_ids = [r.page_id for r in new_recipes if r.page_id not in (expanded.page_ids or [])]
        expanded.page_ids = (current_merged.page_ids or []) + added_ids
        
        expanded.gpt_validated = False  # Валидация будет выполнена перед сохранением
        return expanded
    
    async def _generate_variation_from_canonical(
        self,
        canonical_recipe: MergedRecipe,
        variation_source_ids: list[int],
        save_to_db: bool = True
    ) -> Optional[MergedRecipe]:
        """
        Генерирует вариацию от существующего канонического рецепта.
        
        Вариация - это альтернативный способ приготовления того же блюда:
        - Другие приправы/специи (базилик вместо орегано)
        - Замена основного ингредиента (курица вместо свинины)
        - Другой метод приготовки (запечь вместо жарить)
        - Дополнительные топпинги или гарниры
        
        Args:
            canonical_recipe: Базовый канонический рецепт для создания вариации
            variation_source_ids: Список page_id рецептов (1-5), которые будут источниками идей для вариации
            save_to_db: Сохранять ли результат в БД
            
        Returns:
            MergedRecipe вариации или None если не удалось создать
        """
        if not variation_source_ids or len(variation_source_ids) > self.max_merge_recipes_per_request - 1:
            logger.warning(f"Некорректное количество source рецептов для вариации: {len(variation_source_ids)}")
            return None
        
        # Получаем source рецепты из ClickHouse
        source_recipes = self.olap_db.get_recipes_by_ids(variation_source_ids)
        if not source_recipes:
            logger.error(f"Source рецепты {variation_source_ids} не найдены в ClickHouse")
            return None
        
        # Заполняем ingredients_with_amounts если нужно
        for recipe in source_recipes:
            if not recipe.ingredients_with_amounts:
                recipe.fill_ingredients_with_amounts(self.page_repository)
        
        recipe_language = 'en'
        
        # Генерируем вариацию через GPT
        variation = await self._generate_variation_with_gpt(
            canonical_recipe=canonical_recipe,
            source_recipes=source_recipes,
            target_language=recipe_language
        )
        
        if not variation:
            logger.warning("Не удалось сгенерировать вариацию через GPT")
            return None
        
        # Устанавливаем метаданные вариации
        variation.page_ids = list(set(variation_source_ids + canonical_recipe.page_ids))  # Включаем страницы источников и канонического рецепта
        variation.base_recipe_id = canonical_recipe.base_recipe_id  # Связываем с тем же base_recipe
        variation.language = recipe_language
        variation.cluster_type = self.clusters_build_type
        variation.score_threshold = self.score_threshold
        variation.merge_model = config.GPT_MODEL_MERGE
        variation.is_variation = True # отметить рецепт как вариацию
        
        # Валидация: вариация не должна быть совершенно другим блюдом
        # Сравниваем с базовым рецептом canonical
        base_recipes = self.olap_db.get_recipes_by_ids([canonical_recipe.base_recipe_id])
        if base_recipes:
            base_recipe = base_recipes[0]
            if not base_recipe.ingredients_with_amounts:
                base_recipe.fill_ingredients_with_amounts(self.page_repository)
            
            is_valid, reason = await self.merger.validate_with_gpt(base_recipe, variation)
            if not is_valid:
                logger.warning(f"Вариация не прошла валидацию: {reason}")
                return None
            
            variation.gpt_validated = True
        
        # Сохраняем в БД
        if save_to_db:
            try:
                saved = self.merge_repository.create_merged_recipe(variation)
                variation.id = saved.id
                logger.info(f"✓ Вариация рецепта сохранена, id={saved.id}")
            except Exception as e:
                logger.error(f"Ошибка сохранения вариации: {e}")
        
        return variation
    
    async def _generate_variation_with_gpt(
        self,
        canonical_recipe: MergedRecipe,
        source_recipes: list[Recipe],
        target_language: str
    ) -> Optional[MergedRecipe]:
        """Генерация вариации рецепта через GPT"""
        
        if target_language:
            language_instruction = f"Output in {target_language.upper()} language. Translate ALL text including dish name, ingredients, instructions, AND measurement units."
        else:
            language_instruction = "Use the SAME language as the canonical recipe"
            
        system_prompt = f"""Create a VARIATION of the canonical recipe using ideas from source recipes.

GOAL: Create an ALTERNATIVE way to make the same dish type, NOT a completely different dish.

VARIATION TYPES (choose what fits):
1. Ingredient substitution: chicken → turkey, beef → lamb, soy sauce → tamari
2. Spice/herb variation: oregano → basil, cumin → coriander
3. Cooking method: pan-fry → bake, grill → roast
4. Texture variation: crispy → tender, smooth → chunky
5. Flavor profile: spicy → mild, sweet → savory
6. Garnish/topping: add nuts, different cheese, fresh herbs
7. Side dish/accompaniment: different vegetables, grain, sauce

STRICT RULES:
1. {language_instruction}
2. SAME DISH TYPE: If canonical is "pasta", variation MUST be pasta. No "pasta" → "stew" or "salad".
3. CORE PRESERVED: Main cooking technique and dish structure stay similar
4. CLEAR DIFFERENCE: Variation should be noticeably different from canonical (not just tiny tweaks)
5. EXECUTABLE: Complete, working recipe with all steps
6. NATURAL VOICE: Write as standalone recipe. NEVER say "variation", "alternative version", "based on"
7. dish_name: Reflect the variation (e.g., "Spicy Chicken Pasta" vs "Creamy Chicken Pasta")
8. DESCRIPTION: 1-2 sentences highlighting what makes THIS version special
9. SOURCE-ONLY: Use ONLY ingredients/techniques from canonical + source recipes. NO invention.
10. INSTRUCTIONS: Array of detailed step strings. Each step = complete sentence.
11. NO OPTIONALS: Exact amounts only.
12. REALISTIC: 8-18 core ingredients. Don't include every possible variation.
13. NO BRANDS: Remove all brand names. Generic terms only.

WHAT TO TAKE FROM SOURCES:
- Different spices/seasonings
- Alternative main ingredients (if same category: protein→protein, vegetable→vegetable)
- Different cooking temperatures/times
- Alternative garnishes or toppings
- Complementary side elements

Return JSON only:
{{"dish_name": "variation name", "description": "what makes this version special", "ingredients_with_amounts": [{{"name": "x", "amount": 100, "unit": "g"}}], "instructions": ["step 1", "step 2"], "tags": ["tag1"], "cook_time": "X min" or null, "prep_time": "X min" or null, "variation_notes": "internal: key differences from canonical"}}"""

        def format_merged(m: MergedRecipe) -> str:
            ings = m.ingredients or []
            ing_list = "\n".join([
                f"  - {ing.get('name', '')}: {ing.get('amount', '')} {ing.get('unit', '')}"
                for ing in ings[:30]
            ])
            return f"""Name: {m.dish_name}
Description: {m.description or 'N/A'}
Prep: {m.prep_time or 'N/A'}, Cook: {m.cook_time or 'N/A'}
Tags: {', '.join(m.tags or [])}
Ingredients:
{ing_list}
Instructions: {(m.instructions or '')[:5000]}"""

        def format_recipe(r: Recipe, label: str) -> str:
            ings = r.ingredients_with_amounts or []
            ing_list = "\n".join([
                f"  - {ing.get('name', '')}: {ing.get('amount', '')} {ing.get('unit', '')}"
                for ing in ings[:30]
            ])
            return f"""{label}:
Name: {r.dish_name}
Description: {(r.description or 'N/A')[:500]}
Prep: {r.prep_time or 'N/A'}, Cook: {r.cook_time or 'N/A'}
Tags: {', '.join(r.tags or [])}
Ingredients:
{ing_list}
Instructions: {(r.instructions or '')[:5000]}"""

        sources_text = "\n\n".join([
            format_recipe(r, f"SOURCE RECIPE {i+1} (use for variation ideas)")
            for i, r in enumerate(source_recipes)
        ])
        
        user_prompt = f"""CANONICAL RECIPE (the base to create variation from):
{format_merged(canonical_recipe)}

{sources_text}

TASK: Create ONE variation of the canonical recipe using interesting elements from the {len(source_recipes)} source recipe(s).
The variation should be a different but valid way to make a similar dish.
Example: if canonical is "Tomato Basil Pasta", variation could be "Spicy Arrabbiata Pasta" or "Creamy Garlic Pasta"."""

        try:
            result = await self.merger.gpt_client.async_request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.7,  # Выше температура для большего разнообразия вариаций
                max_tokens=2500,
                request_timeout=90,
                model=config.GPT_MODEL_MERGE,
                response_schema=self.merged_recipe_schema
            )
            
            if not result or not isinstance(result, dict):
                return None
            
            variation_notes = result.get('variation_notes', '')
            source_ids_str = ','.join([str(r.page_id) for r in source_recipes])
            merge_comment = f"variation from canonical {canonical_recipe.id} using sources [{source_ids_str}]: {variation_notes}"
            
            variation = MergedRecipe(
                page_ids=[],  # Будет заполнено в вызывающем методе
                base_recipe_id=canonical_recipe.base_recipe_id,
                dish_name=result.get('dish_name', canonical_recipe.dish_name),
                description=result.get('description', ''),
                ingredients=result.get('ingredients_with_amounts', []),
                instructions=result.get('instructions', []),
                tags=result.get('tags', canonical_recipe.tags or []),
                cook_time=str(result.get('cook_time') or ''),
                prep_time=str(result.get('prep_time') or ''),
                merge_comments=merge_comment,
                language=canonical_recipe.language,
                cluster_type=canonical_recipe.cluster_type,
                score_threshold=canonical_recipe.score_threshold,
                gpt_validated=False,
                merge_model=config.GPT_MODEL_MERGE
            )
            
            return variation
            
        except Exception as e:
            logger.error(f"GPT variation generation failed: {e}")
            return None
        
    
    async def _generate_expanded_canonical(
        self,
        current_merged: MergedRecipe,
        base_recipe: Recipe,
        new_recipes: list[Recipe],
        target_language: str
    ) -> Optional[MergedRecipe]:
        """Генерация расширенного canonical recipe через GPT (batch до max_merge_recipes_per_request-1 рецептов)"""
        
        if not new_recipes:
            return None
        
        num_sources = len(new_recipes)
        
        if target_language:
            language_instruction = f"Output in {target_language.upper()} language. Translate ALL text including dish name, ingredients, instructions, AND measurement units."
        else:
            language_instruction = "Use the SAME language as the canonical recipe"
        system_prompt = f"""Create one SEO-OPTIMIZED, executable recipe from the provided sources.

GOAL: Maximize search visibility while keeping the recipe executable.

RULES:
1. {language_instruction}
2. SOURCE-ONLY: Use ONLY data from provided recipes. NEVER invent.
3. ORIGINAL VOICE: Write as if this is the ONLY recipe. NEVER mention "combined", "merged", "sources", "variations".
4. SEO-RICH dish_name: Natural name a cook would say aloud. Max 5-6 words. Add 1-2 key descriptor (method/flavor) only if essential. Sounds like a restaurant menu, not a blog title.
5. DESCRIPTION: 1-2 sentences. Dish texture, taste, appeal. No fluff.
6. EXECUTABLE: Logical step order, realistic temps/times, proper techniques.
7. NO OPTIONALS: No "optional", "alternatively". Exact amounts only.
8. INSTRUCTIONS: Array of detailed step strings (NO prefix). Each step = complete sentence with technique + timing/temp + visual cue if possible. NOT: "Mix flour". YES: "Whisk flour, salt, and baking powder until combined". 
9. TAGS: 5-10 lowercase (cuisine, diet, method, main ingredient).
10. CONSISTENCY: Every ingredient in list MUST appear in instructions and vice versa.
11. NATURAL INGREDIENT COUNT: Keep it realistic (8-18 core ingredients max). Recipe should look home-cooked, not like a fusion experiment. Don't include every variation from sources.
12. NO ADVERTISING: Remove ALL brand names from ingredients and instructions. Use generic terms instead. Example: "Kikkoman soy sauce" → "soy sauce", "Barilla pasta" → "pasta", "Philadelphia cream cheese" → "cream cheese". Keep only the ingredient type, never the brand.

MERGE LOGIC:
- 2+ sources have ingredient → include with averaged amount
- Prefer detailed instructions over adding more ingredients
- Prioritize quality over quantity: better to have well-explained 10 ingredients than rushed 20
- cook_time/prep_time must match actual steps

Return JSON only:
{{"dish_name": "SEO-rich name", "description": "1-2 concise sentences", "ingredients_with_amounts": [{{"name": "x", "amount": 100, "unit": "g"}}], "instructions": ["step 1 text", "step 2 text"], "tags": ["tag1"], "cook_time": "X min" or null, "prep_time": "X min" or null, "enhancement_notes": "internal: changes made"}}"""

        def format_merged(m: MergedRecipe) -> str:
            ings = m.ingredients or []
            ing_list = "\n".join([
                f"  - {ing.get('name', '')}: {ing.get('amount', '')} {ing.get('unit', '')}"
                for ing in ings[:30]
            ])
            return f"""Name: {m.dish_name}
Description: {m.description or 'N/A'}
Prep: {m.prep_time or 'N/A'}, Cook: {m.cook_time or 'N/A'}
Tags: {', '.join(m.tags or [])}
Ingredients:
{ing_list}
Instructions: {(m.instructions or '')[:5000]}"""

        def format_recipe(r: Recipe, label: str) -> str:
            ings = r.ingredients_with_amounts or []
            ing_list = "\n".join([
                f"  - {ing.get('name', '')}: {ing.get('amount', '')} {ing.get('unit', '')}"
                for ing in ings[:30]
            ])
            return f"""{label}:
Name: {r.dish_name}
Description: {(r.description or 'N/A')[:500]}
Prep: {r.prep_time or 'N/A'}, Cook: {r.cook_time or 'N/A'}
Tags: {', '.join(r.tags or [])}
Ingredients:
{ing_list}
Instructions: {(r.instructions or '')[:5000]}"""

        # Формируем prompt с несколькими source recipes
        sources_text = "\n\n".join([
            format_recipe(r, f"SOURCE RECIPE {i+1} (page_id={r.page_id})")
            for i, r in enumerate(new_recipes)
        ])
        
        user_prompt = f"""BASE RECIPE (the original, must be preserved):
{format_recipe(base_recipe, 'BASE RECIPE')}

CURRENT CANONICAL RECIPE (our refined version):
{format_merged(current_merged)}

{sources_text}

TASK: Enhance the CANONICAL recipe with elements from the {num_sources} SOURCE RECIPE(S), but try to keep it true to the BASE.
Only add elements that enhance without changing the dish's identity completely.
If sources have conflicting info, prefer the most common or reasonable approach."""
        try:
            result = await self.merger.gpt_client.async_request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.5,
                max_tokens=2500,
                request_timeout=90,
                model=config.GPT_MODEL_MERGE,
                response_schema=self.merged_recipe_schema
            )
            
            if not result or not isinstance(result, dict):
                return None
            
            # Формируем merge_comments с информацией о добавленных рецептах
            added_ids = [str(r.page_id) for r in new_recipes]
            enhancement_notes = result.get('enhancement_notes', '')
            merge_comment = f"{current_merged.merge_comments}; +[{','.join(added_ids)}]: {enhancement_notes}"
            
            expanded = MergedRecipe(
                page_ids=current_merged.page_ids,
                base_recipe_id=current_merged.base_recipe_id,
                dish_name=result.get('dish_name', current_merged.dish_name),
                description=result.get('description', current_merged.description),
                ingredients=result.get('ingredients_with_amounts', current_merged.ingredients),
                instructions=result.get('instructions', current_merged.instructions),
                tags=result.get('tags', current_merged.tags),
                cook_time=str(result.get('cook_time') or current_merged.cook_time or ''),
                prep_time=str(result.get('prep_time') or current_merged.prep_time or ''),
                merge_comments=merge_comment,
                language=current_merged.language,
                cluster_type=current_merged.cluster_type,
                score_threshold=current_merged.score_threshold,
                gpt_validated=False,
                merge_model=config.GPT_MODEL_MERGE
            )
            
            return expanded
            
        except Exception as e:
            logger.error(f"GPT canonical expansion failed: {e}")
            return None
    
    async def add_image_to_merged_recipe(self, merged_recipe: MergedRecipe, add_best_image: bool = False) -> bool:
        """
            Добавляет валидные изображения к MergedRecipe по его ID
            Args:
                merged_recipe_id: ID MergedRecipe
        
        """
        
        images = self.image_repository.get_by_page_ids(merged_recipe.page_ids)
        if not images:
            logger.warning(f"Изображения для MergedRecipe ID {merged_recipe.id} не найдены")
            return False
        
        urls = [img.image_url for img in images if img.image_url]

        image_validator = self.merger.validate_images_for_recipe if not add_best_image else self.merger.select_best_images_for_recipe
        valid_urls = await image_validator(merged_recipe, urls)
        if not valid_urls:
            logger.warning(f"Нет валидных изображений для MergedRecipe ID {merged_recipe.id}")
            return False
        valid_images_id = [img.id for img in images if img.image_url in valid_urls]
        self.merge_repository.add_images_to_recipe(merged_recipe.id, valid_images_id)
        return True


# Пример использования
async def example_create_variations():
    """
    Пример создания вариаций рецептов.
    
    Workflow:
    1. Создается canonical (основной) рецепт из кластера
    2. На основе canonical создаются вариации (с другими специями, методами готовки и т.д.)
    """
    generator = ClusterVariationGenerator(
        score_threshold=0.94,
        clusters_build_type="full",
        max_recipes_per_gpt_merge_request=5
    )
    
    # Шаг 1: Создаем canonical recipe из кластера
    canonical = await generator.create_canonical_recipe_with_gpt(
        existing_merged=None,
        base_recipe_id=12345,  # Центроид кластера
        cluster_recipes=[12345, 12346, 12347, 12348, 12349],  # Все рецепты кластера
        target_language='en',
        save_to_db=True,
        max_aggregated_recipes=5
    )
    
    if not canonical:
        logger.error("Не удалось создать canonical recipe")
        return
    
    logger.info(f"✓ Создан canonical recipe: '{canonical.dish_name}' (ID={canonical.id})")
    
    # Шаг 2: Создаем вариации на основе canonical
    # Вариация 1: с рецептами использующими другие специи
    variation_1 = await generator.create_recipe_variation(
        canonical_recipe_id=canonical.id,
        variation_source_ids=[12350, 12351],  # 2 рецепта с базиликом вместо орегано
        target_language='en',
        save_to_db=True
    )
    
    if variation_1:
        logger.info(f"✓ Вариация 1: '{variation_1.dish_name}' (ID={variation_1.id})")
    
    # Вариация 2: с другим методом приготовки
    variation_2 = await generator.create_recipe_variation(
        canonical_recipe_id=canonical.id,
        variation_source_ids=[12352, 12353, 12354],  # 3 рецепта с запеканием вместо жарки
        target_language='en',
        save_to_db=True
    )
    
    if variation_2:
        logger.info(f"✓ Вариация 2: '{variation_2.dish_name}' (ID={variation_2.id})")
    
    # Вариация 3: с заменой основного ингредиента
    variation_3 = await generator.create_recipe_variation(
        canonical_recipe_id=canonical.id,
        variation_source_ids=[12355],  # 1 рецепт с курицей вместо свинины
        target_language='en',
        save_to_db=True
    )
    
    if variation_3:
        logger.info(f"✓ Вариация 3: '{variation_3.dish_name}' (ID={variation_3.id})")
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Итого создано:")
    logger.info(f"  - 1 canonical recipe: '{canonical.dish_name}'")
    logger.info(f"  - {sum([1 for v in [variation_1, variation_2, variation_3] if v])} вариации")
    logger.info(f"{'='*60}\n")


if __name__ == "__main__":
    # Пример использования
    asyncio.run(example_create_variations())