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

logger = logging.getLogger(__name__)

GPT_MODEL_MERGE = os.getenv('GPT_MODEL_MERGE', 'gpt-4o-mini')

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
    
    def _select_best_base(self, recipes: list[Recipe], top_k: int = 3) -> Recipe:
        """
        Эвристический выбор лучшего базового рецепта
        
        Выбирает случайный рецепт из топ-K лучших по качеству.
        Это обеспечивает разнообразие при повторных вызовах.
        
        Критерии (в порядке приоритета):
        1. Количество ингредиентов (больше = лучше)
        2. Длина инструкций (детальнее = лучше)
        3. Наличие времени готовки
        4. Наличие описания
        5. Короткое название (без лишних деталей)
        
        Args:
            recipes: Список рецептов
            top_k: Из скольких лучших выбирать случайный (по умолчанию 3)
            
        Returns:
            Случайный рецепт из топ-K лучших
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
        
        # Берём топ-K (или меньше если рецептов мало)
        top_candidates = sorted_recipes[:min(top_k, len(sorted_recipes))]
        
        # Выбираем случайный из топ-K
        return random.choice(top_candidates)
    
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


class ClusterVariationGenerator:
    """Генератор вариаций из кластера рецептов"""
    
    def __init__(self, score_threshold: float = 0.94, clusters_build_type: str = "full"):
        self.merger = ConservativeRecipeMerger()
        self._olap_db = None
        self.page_repository = PageRepository()
        self.merge_repository = MergedRecipeRepository()
        self.score_threshold = score_threshold
        self.clusters_build_type = clusters_build_type
        self.merged_recipe_schema = json.load(open("src/models/schemas/merged_recipe.json", "r", encoding="utf-8"))

    @property
    def olap_db(self) -> ClickHouseManager:
        """Ленивая инициализация ClickHouse менеджера"""
        if not self._olap_db:
            self._olap_db = ClickHouseManager()
            if not self._olap_db.connect():
                raise ConnectionError("Не удалось подключиться к ClickHouse OLAP базе")
        return self._olap_db
    

    async def generate_variations(self, base: Recipe, batch_recipes: list[Recipe], variation_index: int,
                                  validate_gpt: bool = False) -> Optional[MergedRecipe]:
         # Генерируем 1 вариацию
        variation = await self._generate_single_variation_gpt(
            base=base,
            cluster_recipes=batch_recipes,
            variation_index=variation_index
        )
        
        if not variation:
            return None
        
        # Валидация
        if validate_gpt:
            is_valid, reason = await self.merger.validate_with_gpt(base, variation)
            if not is_valid:
                logger.warning(f"Вариация '{variation.dish_name}' не прошла валидацию: {reason}")
                return None
            variation.gpt_validated = True
        return variation

    async def create_variations_with_same_lang(
            self,
            cluster: list[int],
            validate_gpt: bool = True,
            save_to_db: bool = False,
            max_variations: int = 3,
            max_merged_recipes: int = 3,
            image_ids: Optional[list[int]] = None
    ) -> list[MergedRecipe]:
        """
        Создает вариации рецептов используя данных из mysql pages по языковым группам
        """
        merged_recipes = []
        # Загружаем рецепты
        recipes = self.page_repository.get_recipes(page_ids=cluster)
        if not recipes or len(recipes) < 1:
            logger.warning(f"Не найдены рецепты для кластера: {cluster}")
            return []
        
        recipes = [r.to_pydantic().to_recipe() for r in recipes]

        # Группируем по языкам
        lang_groups: dict[str: list[Recipe]] = {}
        for r in recipes:
            lang = r.language or "unknown"
            if lang not in lang_groups:
                lang_groups[lang] = []
            lang_groups[lang].append(r)

        # Создаём вариации для каждой языковой группы
        for lang, lang_recipes in lang_groups.items():
            max_combinations = self.merger.calculate_max_combinations( 
                n=len(lang_recipes),
                k=min(max_merged_recipes, len(lang_recipes)),
                max_variations=max_variations
            )
            if max_combinations == 0:
                logger.info(f"Недостаточно рецептов для создания вариаций на языке '{lang}'")
                continue

            variations = await self.create_variations_from_cluster(
                recipes=lang_recipes,
                validate_gpt=validate_gpt,
                save_to_db=save_to_db,
                max_variations=max_combinations,
                max_merged_recipes=max_merged_recipes,
                image_ids=image_ids
            )
            merged_recipes.extend(variations)
        return merged_recipes
    
    async def create_variations_from_olap(
        self,
        cluster: list[int],
        validate_gpt: bool = True,
        save_to_db: bool = False,
        max_variations: int = 3,
        max_merged_recipes: int = 3,
        recipe_language: str = "en",
        image_ids: Optional[list[int]] = None
        ) -> Optional[list[MergedRecipe]]:
        """
        создает вариации рецептов используя данных из clickhouse olap
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
            recipe.language  = recipe_language  # OLAP только с английскими рецептами

        max_combinations = self.merger.calculate_max_combinations( 
            n=len(recipes),
            k=min(max_merged_recipes, len(recipes)),
            max_variations=max_variations
        )
        if max_combinations == 0:
            return None

        return await self.create_variations_from_cluster(
            recipes=recipes,
            validate_gpt=validate_gpt,
            save_to_db=save_to_db,
            max_variations=max_combinations,
            max_merged_recipes=max_merged_recipes,
            image_ids=image_ids
            )
    
    async def create_variations_from_cluster(
        self,
        recipes: list[Recipe],
        validate_gpt: bool,
        save_to_db: bool,
        max_variations: int,
        max_merged_recipes: int,
        image_ids: Optional[list[int]] = None
    ) -> list[MergedRecipe]:
        """
        Создаёт 1-N различных вариаций рецепта на основе кластера.
        
        GPT НЕ придумывает ничего нового — только комбинирует информацию
        из переданных рецептов кластера.
        
        Стратегия:
        - Каждый запрос к GPT генерирует 1 рецепт
        - Базовый рецепт + случайные (max_merged_recipes-1) других
        - Повторяем с разными комбинациями до max_variations
        
        Args:
            cluster: список page_id рецептов в кластере
            validate_gpt: валидировать вариации через GPT
            save_to_db: сохранять в БД
            max_variations: максимум вариаций для генерации
            max_merged_recipes: максимум рецептов для передачи в GPT за 1 запрос
            
        Returns:
            список MergedRecipe вариаций
        """       
        recipes = self.merger.remove_equal_recipes(recipes)
        if not recipes:
            logger.warning("После удаления дубликатов не осталось рецептов")
            return []
        
        if len(recipes) < 2:
            logger.warning("Недостаточно рецептов для создания вариаций (нужно минимум 2)")
            return []
        
        variations = []
        used_combinations = set()  # Отслеживаем использованные комбинации
        max_attempts = max_variations * 3  # Лимит попыток избежать бесконечного цикла
        attempts = 0
        
        tasks = []
        i = 1
        while len(tasks) < max_variations and attempts < max_attempts:
            attempts += 1
            
            # Каждую итерацию выбираем новый базовый рецепт из топ-K лучших
            base = self.merger._select_best_base(recipes, top_k=max_variations+1)
            logger.info(f"Итерация {attempts}: выбран базовый рецепт: {base.dish_name} (page_id={base.page_id})")
            
            # Остальные рецепты (без базового)
            other_recipes = [r for r in recipes if r.page_id != base.page_id]
            
            # Выбираем случайные рецепты для этой итерации
            num_others = min(max_merged_recipes - 1, len(other_recipes))
            selected_others = random.sample(other_recipes, num_others)
            
            # Создаём ключ комбинации для проверки уникальности (включая base)
            combo_key = tuple(sorted([base.page_id] + [r.page_id for r in selected_others]))
            if combo_key in used_combinations:
                # Пробуем другую комбинацию
                continue
            used_combinations.add(combo_key)
            
            # Формируем список для GPT: базовый + выбранные
            batch_recipes = [base] + selected_others

            # проверка нет ли такого рецептв в уже созданных вариациях
            if save_to_db:
                existing = self.merge_repository.get_by_page_ids([r.page_id for r in batch_recipes])
                if existing:
                    logger.info(f"Вариация с page_ids={combo_key} уже существует в БД, пропускаем")
                    continue
            
            logger.info(f"Генерация вариации {i}/{max_variations}: "
                       f"base={base.page_id} + {[r.page_id for r in selected_others]}")
            

            tasks.append(self.generate_variations(
                base=base,
                batch_recipes=batch_recipes,
                variation_index=i,
                validate_gpt=validate_gpt
            ))
            i+=1

        for task in asyncio.as_completed(tasks):
            try:
                variation = await task
                if variation:
                    variations.append(variation)
                    if image_ids:
                        variation.image_ids = image_ids
                    logger.info(f"Создана вариация: {variation.dish_name} (page_ids={variation.page_ids})")
            except Exception as e:
                logger.error(f"Ошибка при создании вариации: {e}")

        # Сохранение
        if save_to_db and variations:
            self.merge_repository.create_merged_recipes_batch(variations)
        
        return variations
    
    async def _generate_single_variation_gpt(
        self,
        base: Recipe,
        cluster_recipes: list[Recipe],
        variation_index: int = 1
    ) -> Optional[MergedRecipe]:
        """Генерирует ОДНУ вариацию рецепта через GPT из данных кластера"""
        
        system_prompt = """You are a professional chef creating a recipe variation.

TASK: Create ONE EXECUTABLE recipe variation from the provided recipes.

STRICT RULES - DO NOT VIOLATE:
1. USE ONLY ingredients and techniques from the provided recipes - DO NOT invent new ones
2. Combine elements from source recipes in a unique way
3. Output language: Use the SAME language as the input recipes (they are all in the same language)
4. The recipe must be EXECUTABLE and REALISTIC:
   - All ingredients must be used in instructions
   - Cooking times must be realistic
   - Steps must be in logical order
5. CONSISTENCY: amounts in instructions MUST match ingredients_with_amounts exactly
6. Preserve the core dish identity - the result must be the same dish type
7. INSTRUCTIONS FORMAT - ALWAYS use this exact format:
   "Step 1. First instruction text. Step 2. Second instruction text. Step 3. ..."
   - Each step starts with "Step N." (with period after number)
   - Number of steps can vary (from 2 to 20+) - use as many as needed
   - All steps in a single string, separated by spaces
   - No line breaks, no bullet points, no dashes
   - Keep steps clear and concise

FORBIDDEN:
- Adding ingredients not present in ANY source recipe
- Inventing new cooking techniques not mentioned in sources
- Changing the fundamental nature of the dish
- Using placeholder or vague instructions
- Using numbered lists, bullet points, or line breaks in instructions

Return ONLY valid JSON (no markdown):
{
  "dish_name": "name",
  "description": "description",
  "ingredients_with_amounts": [
    {"name": "ingredient name", "amount": 100, "unit": "g"},
    ...
  ],
  "instructions": "Step 1. Do this. Step 2. Then do that. Step 3. Continue with... (as many steps as needed)",
  "cook_time": "X minutes or X hours X minutes" or null,
  "prep_time": "X minutes or X hours X minutes" or null,
  "source_notes": "which recipes contributed what (English, for logging)"
}"""

        # Форматируем рецепты
        def format_recipe(r: Recipe, label: str) -> str:
            ings = r.ingredients_with_amounts or []
            ing_list = "\n".join([
                f"  - {ing.get('name', '')}: {ing.get('amount', '')} {ing.get('unit', '')}"
                for ing in ings[:30]
            ])
            inst = (r.instructions or "")[:3000]
            return f"""{label}:
Name: {r.dish_name}
Prep: {r.prep_time or 'N/A'}, Cook: {r.cook_time or 'N/A'}
Ingredients: 
{ing_list}
Instructions: {inst}"""

        # Базовый рецепт первый
        recipes_text = format_recipe(base, "BASE RECIPE")
        
        # Остальные рецепты
        other_recipes = [r for r in cluster_recipes if r.page_id != base.page_id]
        for i, r in enumerate(other_recipes):
            recipes_text += "\n\n" + format_recipe(r, f"SOURCE RECIPE {i+1}")

        user_prompt = f"""Create ONE executable recipe variation (#{variation_index}) using ONLY these {len(cluster_recipes)} recipes:

{recipes_text}

Requirements:
- Use ONLY ingredients and techniques from the recipes above
- Output in the SAME language as the base recipe
- Create a unique combination that is different from the sources
- The recipe must be fully executable"""

        try:
            result = await self.merger.gpt_client.async_request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.4,  # немного выше для разнообразия между вариациями
                max_tokens=2500,
                timeout=90,
                model=GPT_MODEL_MERGE,
                response_schema=self.merged_recipe_schema
            )
            
            if not result or not isinstance(result, dict):
                return None
            
            page_ids = [r.page_id for r in cluster_recipes]
            
            merged = MergedRecipe(
                page_ids=page_ids,
                dish_name=result.get('dish_name', base.dish_name),
                description=result.get('description', ''),
                ingredients=result.get('ingredients_with_amounts', []),
                instructions=result.get('instructions', ''),
                cooking_time=str(result.get('cook_time') or base.cook_time or ''),
                prep_time=str(result.get('prep_time') or base.prep_time or ''),
                merge_comments=f"variation #{variation_index}; {result.get('source_notes', '')}",
                language=base.language or "unknown",
                cluster_type=self.clusters_build_type,
                score_threshold=self.score_threshold,
                gpt_validated=False

            )
            
            return merged
            
        except Exception as e:
            logger.error(f"GPT single variation generation failed: {e}")
            return None

# Пример использования в main
if __name__ == "__main__":
    import random
    import asyncio
    logging.basicConfig(level=logging.INFO)

    async def example():
        generator = ClusterVariationGenerator()
        
        # Пример кластера
        cluster = [209,
    8860,
    8862,
    8874,
    8875,
    11439,
    11582,
    11816,
    11853,
    11875,
    12643]
        random.shuffle(cluster)
        
        max_variations = min(1, max(3, len(cluster) / 4))
        variations = await generator.create_variations_from_olap(
            cluster=cluster,
            validate_gpt=True,
            save_to_db=True,
            max_variations=max_variations,
            max_merged_recipes=4
        )
        for var in variations:
            print(f"Создана вариация: {var.dish_name}")
            print(f"  Ингредиенты: {len(var.ingredients)} items")
            print(f"""{', '.join([f"{i.get('name')} {i.get('amount')} {i.get('unit')}" for i in var.ingredients])}""" )
            print(f"  Описание: {len(var.description)} chars")
            print(var.description)
            print(f"  Инструкции: {len(var.instructions)} chars")
            print(var.instructions)
            print("-----")
        #for batch in batched(cluster, 3):
        #    if len(batch) < 2:
        #        continue
        #    pairwise = await generator.create_variation_best_base_gpt(cluster=list(batch), validate_gpt=True, save_to_db=True)
        #    print(f"Создана 1 вариация лучшим базовым через GPT:    {pairwise.dish_name if pairwise else 'нет вариации'}")

    asyncio.run(example())