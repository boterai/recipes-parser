-- View: v_merged_recipes_with_cluster
-- Описание: Объединяет merged_recipes с информацией о кластерах
-- Связывает merged_recipes -> merged_recipe_pages -> cluster_page для получения cluster_id
-- Группирует все page_id входящие в один merged_recipe

CREATE OR REPLACE VIEW `v_merged_recipes_with_cluster` AS
SELECT
    -- Кластерная информация
    COALESCE(MIN(cp.cluster_id), 0) AS cid, -- только для агрегации. у одного рецепта не может быть больше 1 кластера, но мб 0
    GROUP_CONCAT(cp.page_id SEPARATOR ',') AS included_recipes,

    -- Основные поля merged_recipe
    mr.id,
    mr.pages_hash_sha256,
    mr.pages_csv,
    mr.base_recipe_id,
    
    -- Данные рецепта
    mr.dish_name,
    mr.ingredients,
    mr.description,
    mr.instructions,
    mr.nutrition_info,
    
    -- Временная информация
    mr.prep_time,
    mr.cook_time,
    mr.created_at,
    
    -- Метаданные мержа
    mr.merge_comments,
    mr.language,
    mr.cluster_type,
    mr.gpt_validated,
    mr.score_threshold,
    mr.merge_model,
    
    -- Дополнительные атрибуты
    mr.tags,
    mr.is_completed,
    mr.recipe_count,
    mr.is_variation

FROM merged_recipes mr

-- Связь с pages через промежуточную таблицу merged_recipe_pages
LEFT JOIN merged_recipe_pages mrp ON mr.id = mrp.merged_recipe_id

-- Связь с кластерами через cluster_page
LEFT JOIN cluster_page cp ON mrp.page_id = cp.page_id

GROUP BY mr.id
ORDER BY cid; 


-- View: v_recipe_variations_grouped
-- Показывает все рецепты (базовые и вариации), которые имеют хотя бы одну вариацию
-- cid - уникальный идентификатор группы вариаций (основан на base_recipe_id)

CREATE OR REPLACE VIEW `v_recipe_variations_grouped` AS
SELECT 
    DENSE_RANK() OVER (ORDER BY mr.base_recipe_id ASC) AS cid,
    
    -- Все поля рецепта
    mr.id,
    mr.pages_hash_sha256,
    mr.pages_csv,
    mr.base_recipe_id,
    mr.dish_name,
    mr.ingredients,
    mr.description,
    mr.instructions,
    mr.nutrition_info,
    mr.prep_time,
    mr.cook_time,
    mr.merge_comments,
    mr.created_at,
    mr.language,
    mr.cluster_type,
    mr.gpt_validated,
    mr.score_threshold,
    mr.merge_model,
    mr.tags,
    mr.is_completed,
    mr.recipe_count,
    mr.is_variation

FROM merged_recipes mr

WHERE mr.base_recipe_id IN (
    SELECT DISTINCT base_recipe_id
    FROM merged_recipes
    WHERE is_variation = TRUE
)

ORDER BY mr.base_recipe_id, mr.is_variation;