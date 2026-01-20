"""
Консервативное создание вариаций рецептов из кластеров.

Стратегии:
1. Попарное объединение: каждый рецепт с каждым -> N*(N-1)/2 вариаций
2. Групповое объединение: все рецепты -> 1 улучшенная версия
3. Базовое + остальные: один базовый + улучшения от других -> 1 вариация
"""

import logging
from typing import Optional, List, Tuple
from dataclasses import dataclass
from collections import Counter
import asyncio

if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.models.page import Recipe
from src.models.merged_recipe import MergedRecipe, MergedRecipeORM
from src.common.gpt.client import GPTClient
from src.common.db.clickhouse import ClickHouseManager
from src.repositories.page import PageRepository
from src.repositories.merged_recipe import MergedRecipeRepository

logger = logging.getLogger(__name__)


@dataclass
class MergeThresholds:
    """Пороги для консервативного объединения"""
    min_similarity: float = 0.85           # Минимальная векторная схожесть по рецепту польностью по full коллекции
    min_ingredient_overlap: float = 0.75    # 75%+ общих ингредиентов
    max_instruction_diff: float = 0.3      # Максимум 30% различия в шагах
    max_name_length_diff: float = 0.5      # Названия не должны сильно отличаться


class ConservativeRecipeMerger:
    """Консервативное объединение рецептов без изменения сути"""
    
    def __init__(self, thresholds: Optional[MergeThresholds] = None):
        self.thresholds = thresholds or MergeThresholds()
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
    
    def _ingredient_overlap(self, ings1: List[str], ings2: List[str]) -> float:
        """Вычисление доли общих ингредиентов между двумя списками"""
        set1 = set(ings1)
        set2 = set(ings2)
        
        if not set1 or not set2:
            return 0.0
        
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        return intersection / union
    
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
    
    async def merge_with_best_base_gpt(
        self,
        recipes: List[Recipe],
        auto_select_base: bool = True,
        base_recipe: Optional[Recipe] = None
    ) -> Recipe:
        """
        Стратегия: выбрать лучший рецепт как базу + улучшить через GPT
        
        Комбинирует эвристический выбор базового рецепта с GPT объединением.
        
        Args:
            recipes: Список рецептов (2+)
            auto_select_base: Автоматически выбрать лучший базовый эвристически
            base_recipe: Явно указанный базовый рецепт (если auto_select_base=False)
            
        Returns:
            Улучшенный рецепт через GPT с гарантированной базой
        """
        if len(recipes) < 2:
            raise ValueError("Нужно минимум 2 рецепта для объединения")
        
        # Выбираем базовый рецепт
        if auto_select_base:
            base = self._select_best_base(recipes)
            logger.info(f"Эвристически выбран базовый рецепт: {base.dish_name} (page_id={base.page_id})")
        elif base_recipe:
            base = base_recipe
            logger.info(f"Использован указанный базовый рецепт: {base.dish_name}")
        else:
            raise ValueError("Нужно указать auto_select_base=True или передать base_recipe")
        
        # Убеждаемся что базовый рецепт первый в списке
        recipes_ordered = [base] + [r for r in recipes if r.page_id != base.page_id]
        
        # Объединяем через GPT со стратегией "best_base"
        result = await self.merge_multiple_with_gpt(
            recipes=recipes_ordered,
            strategy="best_base"
        )
        
        logger.info(f"✓ Best-base GPT merge: {base.page_id} + {len(recipes)-1} others -> {result.dish_name}")
        return result
    
    def _select_best_base(self, recipes: List[Recipe]) -> Recipe:
        """
        Эвристический выбор лучшего базового рецепта
        
        Критерии (в порядке приоритета):
        1. Количество ингредиентов (больше = лучше)
        2. Длина инструкций (детальнее = лучше)
        3. Наличие времени готовки
        4. Наличие описания
        5. Короткое название (без лишних деталей)
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
        
        return max(recipes, key=score)
    
    async def merge_multiple_with_gpt(
        self,
        recipes: List[Recipe],
        strategy: str = "consensus"
    ) -> MergedRecipe:
        """
        Умное объединение нескольких рецептов (3+) через ChatGPT за один проход
        
        GPT анализирует ВСЕ рецепты одновременно и создаёт единый консенсус,
        избегая накопления ошибок от последовательных merge'ей.
        
        Args:
            recipes: Список рецептов (3+ для эффективности)
            strategy: Стратегия объединения:
                - "consensus": создать консенсус из всех рецептов
                - "best_base": выбрать лучший как базу, дополнить остальными (можно эврестически выбрать лучший и потом объединить через гпт)
            
        Returns:
            Объединённый рецепт через GPT
        """
        if len(recipes) < 2:
            raise ValueError("Нужно минимум 2 рецепта для объединения")
        
        if len(recipes) == 2:
            # Для двух рецептов используем стандартный метод
            return await self.merge_with_gpt(recipes[0], recipes[1])
        
        system_prompt = f"""You are a professional chef and recipe editor.

Your task: analyze {len(recipes)} similar recipes and create ONE optimal merged version.

CRITICAL RULES:
1. Preserve dish identity - all recipes are variations of the same dish
2. Strategy: {"Create a consensus combining best elements from all recipes" if strategy == "consensus" else "Select the best recipe as base, enhance with details from others"}
3. Ingredients: 
   - Include ingredients present in majority (50%+) of recipes
   - Use most common amounts/units as baseline
   - Keep ingredients that improve the dish (even if in minority)
4. Instructions:
   - Merge steps logically, preserving technique consistency
   - Use most detailed/clear instructions as foundation
   - Ensure executable order: prep → cook → serve
5. Resolve conflicts intelligently:
   - Different temps/times: choose most common or middle ground
   - Different techniques: pick most reliable/detailed
6. CONSISTENCY CHECK: Numbers/amounts in instructions MUST match ingredients_with_amounts exactly
   - If ingredient list says "100g sugar", instructions must also say "100g sugar"
   - All quantities referenced in instructions must appear in ingredients list
7. INGREDIENT USAGE: Every ingredient MUST be used in instructions
   - If an ingredient is not mentioned/used in cooking steps, DO NOT include it
   - Only list ingredients that are actually needed for the recipe
8. The result MUST be executable and consistent

Return ONLY valid JSON (no markdown, no comments):
{{
  "dish_name": "best name (shortest, clearest)",
  "description": "combined description highlighting what makes this version optimal",
  "ingredients_with_amounts": [
    {{"name": "ingredient", "amount": 100, "unit": "g"}},
    ...
  ],
  "instructions": "combined step-by-step instructions as single string",
  "cook_time": time or null, example: "45 minutes" or null,
  "prep_time": minutes_or_null, example: "15 minutes" or null,
  "merge_notes": "what was improved/combined from which recipes"
}}"""

        # Форматируем все рецепты
        def format_recipe_summary(r: Recipe, idx: int) -> str:
            ings = r.ingredients_with_amounts or []
            inst = r.instructions if isinstance(r.instructions, str) else str(r.instructions or "")
            
            # Ограничиваем для токенов
            ing_list = "\n".join([
                f"  - {ing.get('name', '')}: {ing.get('amount', '')} {ing.get('unit', '')}"
                for ing in ings[:20]
            ])
            
            inst_preview = inst[:1500] + ("..." if len(inst) > 800 else "")
            
            return f"""RECIPE {idx + 1}:
Name: {r.dish_name}
Prep: {getattr(r, 'prep_time', 'N/A')}, Cook: {getattr(r, 'cooking_time', 'N/A')}
Ingredients ({len(ings)}): {ing_list}
Instructions: {inst_preview}
---"""

        recipes_text = "\n\n".join([
            format_recipe_summary(r, i) for i, r in enumerate(recipes[:10])  # лимит 10 рецептов
        ])
        
        user_prompt = f"""Analyze and merge these {len(recipes)} recipes into ONE optimal version:

{recipes_text}

Strategy: {strategy}
Create the best executable recipe combining elements from all sources."""

        try:
            result = await self.gpt_client.async_request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=2500,
                timeout=90
            )
            
            base = recipes[0]
            
            return self._create_merged_from_gpt_result(
                base=base,
                page_ids=[r.page_id for r in recipes],
                result=result
            )
            
        except Exception as e:
            logger.error(f"GPT multi-merge failed: {e}")
        
    def _create_merged_from_gpt_result(
        self,
        base: Recipe,
        page_ids: list[int],
        result: dict
    ) -> MergedRecipe:
        merged = MergedRecipe(
                page_ids=page_ids,
                dish_name=result.get('dish_name', base.dish_name),
                description=result.get('description', base.description or ''),
                ingredients=result.get('ingredients_with_amounts', base.ingredients_with_amounts or []),
                instructions=result.get('instructions', base.instructions),
                cooking_time=str(result.get('cook_time') or base.cook_time or ""),
                prep_time=str(result.get('prep_time') or base.prep_time or ""),
                merge_comments=result.get('merge_notes', '')
            )
            
        # Обновляем также список ingredients на основе ingredients_with_amounts
        if merged.merge_comments:
            logger.info(f"GPT merge notes: {merged.merge_comments}")
        
        logger.info(f"✓ GPT merge: {page_ids} -> {merged.dish_name}")
        return merged
    
    async def merge_with_gpt(
        self,
        recipe1: Recipe,
        recipe2: Recipe,
        preserve_all_details: bool = True
    ) -> MergedRecipe:
        """
        Умное объединение двух рецептов через ChatGPT
        
        GPT анализирует оба рецепта и создаёт улучшенную версию,
        сохраняя все важные детали из обоих источников.
        
        Args:
            recipe1: Первый рецепт (обычно базовый)
            recipe2: Второй рецепт (дополнительный)
            preserve_all_details: Сохранять все детали или оптимизировать
            
        Returns:
            Объединённый рецепт через GPT
        """
        system_prompt = """You are a professional chef and recipe editor.

Your task: intelligently merge two similar recipes into one enhanced version.

CRITICAL RULES:
1. Preserve dish identity - it must remain the same dish type
2. Select best ingredients from both recipes - include those that improve the dish (with amounts/units)
   - Keep core ingredients that define the dish
   - Add ingredients that enhance flavor, texture, or presentation
   - Omit redundant or conflicting ingredients that don't add value
3. Merge instructions: combine steps, keep important details from both
4. If recipes differ in technique, choose the better/more detailed one
5. Fill missing metadata (cooking time, preparation time) from either recipe
6. Resolve conflicts intelligently (e.g., different amounts -> average or range)
7. CONSISTENCY CHECK: Numbers/amounts in instructions MUST match ingredients_with_amounts exactly
   - If ingredient list says "200g flour", instructions must also say "200g flour"
   - Ensure all quantities referenced in instructions appear in ingredients list
8. INGREDIENT USAGE: Every ingredient MUST be used in instructions
   - If an ingredient is not mentioned/used in cooking steps, DO NOT include it
   - Only list ingredients that are actually needed for the recipe
9. The result must be a complete, executable recipe

Return ONLY valid JSON (no markdown, no comments):
{
  "dish_name": "best name (shortest, clearest)",
  "description": "combined description highlighting improvements",
  "ingredients_with_amounts": [
    {"name": "ingredient", "amount": 100, "unit": "g"},
    ...
  ],
  "instructions": "combined step-by-step instructions as single string",
  "cook_time": time or nul example 20 minutes,
  "prep_time": time or nul example 20 minutes,
  "merge_notes": "what was improved/combined"
}"""

        # Форматируем рецепты для GPT
        def format_recipe(r: Recipe, label: str) -> str:
            ings = r.ingredients_with_amounts or []
            inst = r.instructions if isinstance(r.instructions, str) else str(r.instructions or "")
            
            ing_list = "\n".join([
                f"  - {ing.get('name', '')}: {ing.get('amount', '')} {ing.get('unit', '')}"
                for ing in ings[:30]  # лимит для токенов
            ])
            
            # Обрезаем инструкции если слишком длинные
            inst_preview = inst[:1500] + ("..." if len(inst) > 1500 else "")
            
            return f"""{label}:
Name: {r.dish_name}
Prep time: {getattr(r, 'prep_time', 'N/A')}
Cooking time: {getattr(r, 'cooking_time', 'N/A')}

Ingredients ({len(ings)} total):
{ing_list}

Instructions:
{inst_preview}"""

        user_prompt = f"""Merge these two recipes into one enhanced version:

{format_recipe(recipe1, "RECIPE 1")}

{format_recipe(recipe2, "RECIPE 2")}

Mode: {"preserve all details" if preserve_all_details else "optimize for clarity"}

Create the best possible merged version."""

        try:
            result = await self.gpt_client.async_request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,  # низкая для консистентности
                max_tokens=2000,
                timeout=60
            )

            return self._create_merged_from_gpt_result(
                base=recipe1,
                page_ids=[recipe1.page_id, recipe2.page_id],
                result=result
            )
            
        except Exception as e:
            logger.error(f"GPT merge failed: {e}")
    
    async def validate_with_gpt(
        self,
        original: Recipe,
        enhanced: MergedRecipe
    ) -> Tuple[bool, str]:
        """
        Валидация через GPT: не изменилась ли суть рецепта
        
        Args:
            original: Исходный рецепт
            enhanced: Улучшенный рецепт
            
        Returns:
            (валиден, причина)
        """
        system_prompt = """You are a recipe validation expert with a PERMISSIVE approach.
Check if an enhanced recipe preserved the core identity of the original.

IMPORTANT: Be LENIENT. Small improvements are ACCEPTABLE and should be validated as TRUE:
- Adding seasonings/spices (pepper, salt, herbs) - VALID
- Adding garnish or optional toppings - VALID
- More specific ingredient amounts - VALID
- More detailed cooking instructions - VALID
- Adding cooking tips or variations - VALID
- Combining similar steps for clarity - VALID

REJECT only if there are MAJOR changes:
- Dish type changed completely (soup → salad, cake → cookies)
- Core ingredients removed (e.g., removing chicken from chicken curry)
- Cooking method fundamentally different (baking → frying)
- Recipe becomes incoherent or contradictory

When in doubt, mark as VALID. The goal is to improve recipes, not reject minor enhancements.

Return JSON: {"valid": true/false, "reason": "short explanation"}"""

        orig_ings = original.ingredients[:10]
        enh_ings = [i.get('name', '') for i in (enhanced.ingredients or [])[:10]]
        
        orig_inst = original.instructions
        enh_inst = enhanced.instructions

        user_prompt = f"""Original recipe:
Name: {original.dish_name}
Ingredients: {', '.join(orig_ings)}
Instructions length: {len(orig_inst)} chars

Enhanced recipe:
Name: {enhanced.dish_name}
Ingredients: {', '.join(enh_ings)}
Instructions length: {len(enh_inst)} chars

Did the enhancement preserve the recipe identity?"""

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


class ClusterVariationGenerator:
    """Генератор вариаций из кластера рецептов"""
    
    def __init__(self, thresholds: Optional[MergeThresholds] = None):
        self.merger = ConservativeRecipeMerger(thresholds)
        self.olap_db = ClickHouseManager()
        if not self.olap_db.connect():
            raise ConnectionError("Failed to connect to ClickHouse")
        self.page_repository = PageRepository()
        self.merge_repository = MergedRecipeRepository()
    
    async def create_variations_pairwise_gpt(
        self,
        cluster: list[int],
        validate_gpt: bool = True,
        save_to_db: bool = False,
        max_variations: int = 5
    ) -> List[Recipe]:
        """
        Стратегия: попарное объединение через GPT (умное слияние)
        
        Использует ChatGPT для интеллектуального объединения каждой пары,
        сохраняя все важные детали из обоих рецептов.
        
        Args:
            cluster: список page_id рецептов
            validate_gpt: валидировать через GPT
            save_to_db: сохранять в БД
            
        Returns:
            список вариаций
        """
        if len(cluster) < 2:
            logger.warning("Кластер слишком маленький для попарного объединения")
            return []
        
        # Загружаем все рецепты кластера
        recipes = self.olap_db.get_recipes_by_ids(cluster)
        if not recipes:
            logger.error(f"Не найдены рецепты для кластера {cluster}")
            return []
        
        for recipe in recipes:
            recipe.fill_ingredients_with_amounts(self.page_repository)  

        recipes = self.merger.remove_equal_recipes(recipes)
        if len(recipes) < 2:
            logger.warning("После удаления похожих рецептов в кластере осталось меньше 2 уникальных")
            return []
        
        logger.info(f"Попарное объединение через GPT: {len(recipes)} рецептов -> {len(recipes)*(len(recipes)-1)//2} пар")
        
        variations = []
        
        # Попарно объединяем через GPT
        for i, recipe1 in enumerate(recipes):
            for recipe2 in recipes[i+1:]:
                try:

                    merged: MergedRecipeORM = self.merge_repository.get_by_page_ids([recipe1.page_id, recipe2.page_id])
                    if merged:
                        logger.info(f"Использован кэшированный GPT merge для {recipe1.page_id}-{recipe2.page_id}")
                        variation = merged.to_pydantic()
                        variations.append(variation)
                        continue

                    # GPT объединяет оба рецепта
                    variation = await self.merger.merge_with_gpt(recipe1, recipe2)
                    if not variation:
                        logger.warning(f"GPT merge вернул пустой результат для {recipe1.page_id}-{recipe2.page_id}")
                        continue
                    # Валидация
                    if validate_gpt:
                        is_valid, reason = await self.merger.validate_with_gpt(recipe1, variation)
                        if not is_valid:
                            logger.warning(f"GPT-пара {recipe1.page_id}-{recipe2.page_id} не прошла валидацию: {reason}")
                            continue
                    
                    variations.append(variation)
                    logger.info(f"✓ GPT вариация {recipe1.page_id}+{recipe2.page_id}: {variation.dish_name}")
                    
                    if max_variations and len(variations) >= max_variations:
                        logger.info(f"Достигнуто максимальное число вариаций {max_variations}, остановка.")
                        if save_to_db: 
                            self.merge_repository.create_merged_recipes_batch(variations)
                        return variations
                    
                except Exception as e:
                    logger.error(f"Ошибка GPT-объединения {recipe1.page_id}-{recipe2.page_id}: {e}")
                    continue
        
        # Сохранение
        if save_to_db and variations:
            self.merge_repository.create_merged_recipes_batch(variation)
        
        return variations
    
    async def create_variation_best_base_gpt(
        self,
        cluster: List[int],
        validate_gpt: bool = True,
        save_to_db: bool = False
    ) -> Optional[Recipe]:
        """
        Стратегия: лучший базовый + GPT объединение
        
        Комбинирует эвристический выбор базы с GPT merge для надёжности.
        
        Args:
            cluster: список page_id рецептов
            validate_gpt: валидировать через GPT
            save_to_db: сохранять в БД
            
        Returns:
            улучшенная вариация с надёжной базой
        """
        if len(cluster) < 2:
            logger.warning("Кластер слишком маленький")
            return None
        
        # проверка на то, что вариация уже создана и возвращение из бд
        merged = self.merge_repository.get_by_page_ids(cluster)
        if merged:
            logger.info(f"Использован кэшированный GPT merge для {cluster}")
            return merged.to_pydantic()
        
        # Загружаем рецепты
        recipes = self.olap_db.get_recipes_by_ids(cluster)
        if not recipes:
            logger.error(f"Не найдены рецепты для кластера {cluster}")
            return None
        
        for recipe in recipes:
            recipe.fill_ingredients_with_amounts(self.page_repository)

        recipes = self.merger.remove_equal_recipes(recipes)
        if len(recipes) < 2:
            logger.warning("После удаления похожих рецептов в кластере осталось меньше 2 уникальных")
            return []
        
        logger.info(f"Best-base GPT объединение: {len(recipes)} рецептов")
        
        try:
            # Объединяем через гибридный метод
            variation = await self.merger.merge_with_best_base_gpt(recipes)
            if not variation:
                logger.warning("Best-base GPT merge вернул пустой результат")
                return None
            # Валидация
            if validate_gpt: # предполагается, что базовый рецепт - recipes[0]
                is_valid, reason = await self.merger.validate_with_gpt(recipes[0], variation)
                if not is_valid:
                    logger.warning(f"Best-base GPT вариация не прошла валидацию: {reason}")
                    return None
            
            logger.info(f"✓ Best-base GPT вариация: {variation.dish_name}")
            
            # Сохранение
            if save_to_db:
                self.merge_repository.create_merged_recipe(variation)
            
            return variation
            
        except Exception as e:
            logger.error(f"Ошибка best-base GPT объединения: {e}")
            return None

    def _select_best_base(self, recipes: List[Recipe]) -> Recipe:
        """Выбор лучшего базового рецепта (самый полный и детальный)"""
        def score(r: Recipe) -> tuple:
            ing_count = len(r.ingredients) if r.ingredients else 0
            inst_len = len(r.instructions) if isinstance(r.instructions, str) else len(str(r.instructions or ""))
            
            return (
                ing_count,
                inst_len,
                bool(getattr(r, 'cooking_time', None)),
                bool(getattr(r, 'description', None)),
                -len(r.dish_name)  # короткое название лучше
            )
        
        return max(recipes, key=score)


# Пример использования в main
if __name__ == "__main__":
    import random
    from itertools import batched
    import asyncio
    logging.basicConfig(level=logging.INFO)
    cl = [4978,7772,34395]
    async def example():
        generator = ClusterVariationGenerator()
        
        # Пример кластера
        cluster = [7872,
    7882,
    7887,
    33645]
        random.shuffle(cluster)
        pairwises = await generator.create_variations_pairwise_gpt(cluster=cluster, validate_gpt=False, save_to_db=True, max_variations=2)
        print(f"Создано {len(pairwises)} попарных вариаций через GPT.")
        pairwise = await generator.create_variation_best_base_gpt(cluster=cluster, validate_gpt=False, save_to_db=True)
        print(f"Создана 1 вариация лучшим базовым через GPT:    {pairwise.dish_name if pairwise else 'нет вариации'}")

        #for batch in batched(cluster, 3):
        #    if len(batch) < 2:
        #        continue
        #    pairwise = await generator.create_variation_best_base_gpt(cluster=list(batch), validate_gpt=True, save_to_db=True)
        #    print(f"Создана 1 вариация лучшим базовым через GPT:    {pairwise.dish_name if pairwise else 'нет вариации'}")
    
    asyncio.run(example())