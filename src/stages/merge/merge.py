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
from src.models.image import Image
from src.common.gpt.client import GPTClient
from src.common.db.clickhouse import ClickHouseManager
from src.repositories.page import PageRepository
from src.repositories.merged_recipe import MergedRecipeRepository
from src.repositories.image import ImageRepository

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
    
    def __init__(self, score_threshold: float = 0.94, clusters_build_type: str = "full"):
        self.merger = ConservativeRecipeMerger()
        self._olap_db = None
        self.page_repository = PageRepository()
        self.merge_repository = MergedRecipeRepository()
        self.image_repository = ImageRepository()
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
                                  validate_gpt: bool = False, target_language: Optional[str] = None) -> Optional[MergedRecipe]:
         # Генерируем 1 вариацию
        variation = await self._generate_single_variation_gpt(
            base=base,
            cluster_recipes=batch_recipes,
            variation_index=variation_index,
            target_language=target_language
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
    
    async def create_variations(
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
            return [merged.to_pydantic(get_images=False)]
        
        # Загружаем рецепты
        recipes = self.olap_db.get_recipes_by_ids(cluster)
        if not recipes:
            logger.error(f"Не найдены рецепты для кластера {cluster}")
            return None
        
        for recipe in recipes:
            if not recipe.ingredients_with_amounts: # fallback при отсутствии переведенных ингредиентов с количеством
                recipe.fill_ingredients_with_amounts(self.page_repository)
            recipe.language  = recipe_language  # OLAP только с английскими рецептами

        return await self.create_variations_from_cluster(
            recipes=recipes,
            validate_gpt=validate_gpt,
            save_to_db=save_to_db,
            max_variations=max_variations,
            max_merged_recipes=max_merged_recipes,
            image_ids=image_ids,
            target_language=recipe_language
            )
    
    async def create_variations_from_cluster(
        self,
        recipes: list[Recipe],
        validate_gpt: bool,
        save_to_db: bool,
        max_variations: int,
        max_merged_recipes: int,
        image_ids: Optional[list[int]] = None,
        target_language: Optional[str] = None
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
        used_base_ids = set()  # Отслеживаем использованные базовые рецепты
        max_attempts = max_variations * 3  # Лимит попыток избежать бесконечного цикла
        attempts = 0
        
        tasks = []
        i = 1
        while len(tasks) < max_variations and attempts < max_attempts:
            attempts += 1
            
            # Выбираем новый уникальный базовый рецепт для каждой вариации
            # Исключаем уже использованные базовые рецепты
            available_for_base = [r for r in recipes if r.page_id not in used_base_ids]
            
            if not available_for_base:
                logger.warning("Все рецепты уже использованы в качестве базовых, сбрасываем список")
                used_base_ids.clear()
                available_for_base = recipes
            
            base = self.merger._select_best_base(available_for_base)
            used_base_ids.add(base.page_id)
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
                validate_gpt=validate_gpt,
                target_language=target_language
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
    
    async def add_image_to_merged_recipe(self, merged_recipe: MergedRecipe, add_best_image: bool = False) -> bool:
        """
            Добавляет валидные изображения к MergedRecipe по его ID
            Args:
                merged_recipe_id: ID MergedRecipe
        
        """
        
        images = self.image_repository.get_by_page_ids(merged_recipe.page_ids)
        if not images:
            logger.warning(f"Изображения для MergedRecipe ID {merged_recipe.id} не найдены")
            return
        
        urls = [img.image_url for img in images if img.image_url]

        image_validator = self.merger.validate_images_for_recipe if not add_best_image else self.merger.select_best_images_for_recipe
        valid_urls = await image_validator(merged_recipe, urls)
        if not valid_urls:
            logger.warning(f"Нет валидных изображений для MergedRecipe ID {merged_recipe.id}")
            return False
        valid_images_id = [img.id for img in images if img.image_url in valid_urls]
        self.merge_repository.add_images_to_recipe(merged_recipe.id, valid_images_id)
        return True
    
    async def _generate_single_variation_gpt(
        self,
        base: Recipe,
        cluster_recipes: list[Recipe],
        variation_index: int = 1,
        target_language: Optional[str] = None
    ) -> Optional[MergedRecipe]:
        """Генерирует ОДНУ вариацию рецепта через GPT из данных кластера
        
        Args:
            base: Базовый рецепт
            cluster_recipes: Список рецептов кластера
            variation_index: Индекс вариации
            target_language: Целевой язык для генерации (например 'en', 'ru', 'de'). 
                           Если None - использует язык входных рецептов.
        """
        
        # Определяем инструкцию по языку
        if target_language:
            language_instruction = f"Output the recipe in {target_language.upper()} language. Translate ALL text including dish name, ingredients, instructions, AND measurement units (g→г, cup→чашка, tbsp→ст.л., etc.)."
        else:
            language_instruction = "Use the SAME language as the input recipes (they are all in the same language)"
        
        system_prompt = f"""You are a professional chef creating a recipe variation.

TASK: Create ONE EXECUTABLE recipe variation from the provided recipes.

STRICT RULES - DO NOT VIOLATE:
1. USE ONLY ingredients and techniques from the provided recipes - DO NOT invent new ones
2. Combine elements from source recipes in a unique way
3. Output language: {language_instruction}
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
{{
  "dish_name": "name",
  "description": "description",
  "ingredients_with_amounts": [
    {{"name": "ingredient name", "amount": 100, "unit": "g"}},
    ...
  ],
  "instructions": "Step 1. Do this. Step 2. Then do that. Step 3. Continue with... (as many steps as needed)",
  "tags": ["tag1", "tag2", "tag3"],
  "cook_time": "X minutes or X hours X minutes" or null,
  "prep_time": "X minutes or X hours X minutes" or null,
  "source_notes": "which recipes contributed what (English, for logging)"
}}

CRITICAL - UNITS MUST BE IN TARGET LANGUAGE:
- For English: g, kg, ml, l, cup, tbsp, tsp, oz, lb, piece, clove, etc.
- For Russian: г, кг, мл, л, чашка, ст.л., ч.л., шт, зубчик, etc.
- NEVER mix languages - if target is English, ALL units must be English
- Check each ingredient's unit field before outputting

TAGS RULES:
- Select 3-7 relevant tags that accurately describe the FINAL recipe
- Tags should reflect: dish type, cuisine, diet restrictions, cooking method, main ingredients
- Use lowercase English tags (e.g. "vegetarian", "quick", "italian", "baked", "chicken")
- Only include tags that truly apply to the final combined recipe
- If source recipes have conflicting tags (e.g. one is "vegan", another has meat), choose based on final recipe"""

        # Форматируем рецепты
        def format_recipe(r: Recipe, label: str) -> str:
            ings = r.ingredients_with_amounts or []
            ing_list = "\n".join([
                f"  - {ing.get('name', '')}: {ing.get('amount', '')} {ing.get('unit', '')}"
                for ing in ings[:30]
            ])
            inst = (r.instructions or "")[:3000]
            tags_str = ", ".join(r.tags) if r.tags else "N/A"
            return f"""{label}:
Name: {r.dish_name}
Prep: {r.prep_time or 'N/A'}, Cook: {r.cook_time or 'N/A'}
Tags: {tags_str}
Ingredients: 
{ing_list}
Instructions: {inst}"""

        # Базовый рецепт первый
        recipes_text = format_recipe(base, "BASE RECIPE")
        
        # Остальные рецепты
        other_recipes = [r for r in cluster_recipes if r.page_id != base.page_id]
        for i, r in enumerate(other_recipes):
            recipes_text += "\n\n" + format_recipe(r, f"SOURCE RECIPE {i+1}")

        language_requirement = f"Output in {target_language.upper()} language" if target_language else "Output in the SAME language as the base recipe"
        
        user_prompt = f"""Create ONE executable recipe variation (#{variation_index}) using ONLY these {len(cluster_recipes)} recipes:

{recipes_text}

Requirements:
- Use ONLY ingredients and techniques from the recipes above
- {language_requirement}
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
                tags=result.get('tags', []),
                cook_time=str(result.get('cook_time') or base.cook_time or ''),
                prep_time=str(result.get('prep_time') or base.prep_time or ''),
                merge_comments=f"variation #{variation_index}; {result.get('source_notes', '')}",
                language=base.language or "unknown",
                cluster_type=self.clusters_build_type,
                score_threshold=self.score_threshold,
                gpt_validated=False,
                merge_model=GPT_MODEL_MERGE
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
        variations = await generator.create_variations(
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